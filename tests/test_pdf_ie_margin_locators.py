"""Source locators and historical marginal references retain their text and position."""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import re

import pytest

from legalize.fetcher.ie.pdf import UnsupportedPDF, parse_revised_pdf

FIXTURES = Path(__file__).parent / "fixtures/ie"
EVIDENCE = json.loads((FIXTURES / "pdf-margin-locator-regressions.json").read_text())
NOTES = {
    "IE-1994-act-16": ["F137[Section 7F.]"],
    "IE-1996-act-16": ["Section l"],
    "IE-1996-act-20": ["Paragraph 2 (2) of Second Schedule."],
    "IE-1996-act-34": ["Section 2.F21[...]"],
    "IE-1999-act-15": ["Subsection (1).", "Subsection (5)."],
    "IE-2006-act-29": ["Section7(2)."],
    "IE-2009-act-27": [
        "[CA 1881, s. 67]",
        "[[SLA 1882, ss. 2, 59, 60]",
        "[BC(JT) A 1899]",
        "[LPAA 1859, s. 24][LPAA 1860, s. 8]",
    ],
}


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_wrapped_schedule_locators_and_historical_citations_remain_separate(record):
    raw = (FIXTURES / record["file"]).read_bytes()
    assert sha256(raw).hexdigest() == record["fixture_sha256"]
    paragraphs, cutoff = parse_revised_pdf(raw)
    assert cutoff
    assert any(p.css_class == "articulo" and p.text.startswith("1.") for p in paragraphs)
    for note in NOTES[record["identifier"]]:
        matching = [p for p in paragraphs if re.sub(r"\*", "", p.text) == note]
        assert len(matching) == 1, (note, [(p.css_class, p.text) for p in paragraphs])
        assert matching[0].css_class == "parrafo"
    if record["identifier"] == "IE-2009-act-27":
        texts = [p.text for p in paragraphs]
        heading = next(i for i, t in enumerate(texts) if t == "4. **Service of notices.**")
        reference = texts.index("[CA 1881, s. 67]")
        assert (
            heading
            < reference
            < next(i for i, t in enumerate(texts) if "by leaving it at the address" in t)
        )


def test_unrecognised_marginal_text_still_rejects_the_snapshot(monkeypatch):
    from legalize.fetcher.ie import pdf

    record = next(r for r in EVIDENCE if r["identifier"] == "IE-1999-act-15")
    raw = (FIXTURES / record["file"]).read_bytes()
    events, cutoff, expected = pdf._read(raw)
    index = next(i for i, event in enumerate(events) if event.text.startswith("Subsection"))
    chars = deepcopy(events[index].chars)
    letters = sorted(
        (c for c in chars if c["x0"] < 140 and c["text"].isalpha()), key=lambda c: c["x0"]
    )
    assert "".join(c["text"] for c in letters) == "Subsection"
    for char, letter in zip(letters, "Unverified", strict=True):
        char["text"] = letter
    events[index] = replace(events[index], chars=chars)
    monkeypatch.setattr(pdf, "_read", lambda _, **_kw: (events, cutoff, expected))
    with pytest.raises(UnsupportedPDF, match="Unassigned marginal text"):
        parse_revised_pdf(raw)
