"""Marginal text that is not a section caption keeps its words and its place.

Evidence: tests/fixtures/ie/pdf-margin-variant-evidence.json (page excerpts of the
official PDFs: cover, first section, and the page with the marginal text).
"""

from hashlib import sha256
import json
from pathlib import Path

import pytest

from legalize.fetcher.ie.pdf import UnsupportedPDF, _read, parse_revised_pdf

FIXTURES = Path(__file__).parent / "fixtures/ie"
EVIDENCE = json.loads((FIXTURES / "pdf-margin-variant-evidence.json").read_text())


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_margin_text_is_a_caption_or_stays_as_legal_text(record):
    raw = (FIXTURES / record["file"]).read_bytes()
    assert sha256(raw).hexdigest() == record["fixture_sha256"]
    paragraphs, cutoff = parse_revised_pdf(raw)
    assert cutoff
    matching = [
        p
        for p in paragraphs
        if record["phrase"] in p.text.replace("*", "") or record["phrase"] in p.text
    ]
    assert len(matching) == 1, [(p.css_class, p.text[:80]) for p in paragraphs]
    assert matching[0].css_class == record["css_class"]


def test_a_caption_above_its_label_needs_the_label_row(monkeypatch):
    """Moving the label two lines down leaves the centred caption orphaned."""
    from legalize.fetcher.ie import pdf

    record = next(r for r in EVIDENCE if r["identifier"] == "IE-2015-act-2")
    raw = (FIXTURES / record["file"]).read_bytes()
    events, cutoff, expected = _read(raw)
    label = next(e for e in events if getattr(e, "text", "").startswith("Central Bank 189."))
    for char in label.chars:
        if char["x0"] > 140:
            char["top"] += 30
            char["bottom"] += 30
    monkeypatch.setattr(pdf, "_read", lambda data, **_kw: (events, cutoff, expected))
    with pytest.raises(UnsupportedPDF, match="Unassigned marginal text"):
        parse_revised_pdf(raw)
