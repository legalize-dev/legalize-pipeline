"""Printed labels and exact corroborated headings retain complete section boundaries."""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pytest

from legalize.fetcher.ie import pdf

FIXTURES = Path(__file__).parent / "fixtures/ie"
EVIDENCE = json.loads((FIXTURES / "pdf-incomplete-headings-evidence.json").read_text())


def source(identifier):
    record = next(r for r in EVIDENCE if r["identifier"] == identifier)
    raw = (FIXTURES / record["file"]).read_bytes()
    assert sha256(raw).hexdigest() == record["sha256"]
    return raw


@pytest.mark.parametrize("identifier", [r["identifier"] for r in EVIDENCE])
def test_complete_bodies_keep_printed_labels_and_editorial_backmatter_separate(identifier):
    raw = source(identifier)
    paragraphs, cutoff = pdf.parse_revised_pdf(raw)
    assert cutoff
    headings = [p.text for p in paragraphs if p.css_class == "articulo"]
    if identifier == "IE-2012-act-26":
        assert len(headings) == 12
        assert "5." in headings
        index = next(i for i, p in enumerate(paragraphs) if p.text == "5.")
        assert "make a scheme or schemes" in paragraphs[index + 1].text
    elif identifier == "IE-2017-act-11":
        assert len(headings) == 17
        assert "10. **Jurisdiction**" in headings
        assert "14. **Amendment of Bail Act 1997**" in headings
        index = next(i for i, p in enumerate(paragraphs) if p.text.startswith("14. **"))
        assert paragraphs[index + 1].text.startswith("The Schedule")
        assert any("[^1]:" in p.text and "14.8.2013" in p.text for p in paragraphs)
        assert "omits section 14's number" in pdf.source_warning(raw)
    else:
        assert len(headings) == 109
        assert not any("Related legislation" in p.text for p in paragraphs)
        assert pdf.source_warning(raw) is None


@pytest.mark.parametrize(
    "identifier, prefix, number",
    [("IE-2012-act-26", "5.—", "5"), ("IE-2017-act-11", "10 (1)", "10")],
)
@pytest.mark.parametrize("font", ["Calibri", "Calibri-Italic"])
def test_uncaptioned_or_periodless_labels_still_require_nonitalic_bold_digits(
    monkeypatch, identifier, prefix, number, font
):
    raw = source(identifier)
    events, cutoff, expected = pdf._read(raw)
    index = next(i for i, e in enumerate(events) if e.text.startswith(prefix))
    chars = deepcopy(events[index].chars)
    for c in chars[: len(number)]:
        assert c["text"].isdigit()
        c["fontname"] = font
    events[index] = replace(events[index], chars=chars)
    monkeypatch.setattr(pdf, "_read", lambda _, **_kw: (events, cutoff, expected))
    with pytest.raises(
        pdf.UnsupportedPDF, match=f"missing sections listed in its contents: {number}$"
    ):
        pdf.parse_revised_pdf(raw)


def test_uncaptioned_label_requires_its_contents_entry(monkeypatch):
    raw = source("IE-2012-act-26")
    events, cutoff, expected = pdf._read(raw)
    expected.remove("5")
    monkeypatch.setattr(pdf, "_read", lambda _, **_kw: (events, cutoff, expected))
    paragraphs, _ = pdf.parse_revised_pdf(raw)
    assert not any(p.css_class == "articulo" and p.text == "5." for p in paragraphs)
    assert any("make a scheme or schemes" in p.text for p in paragraphs)


def test_changed_bytes_cannot_inherit_an_unnumbered_section_exception():
    raw = source("IE-2017-act-11") + b"\n"
    assert pdf.source_warning(raw) is None
    with pytest.raises(pdf.UnsupportedPDF, match="missing sections listed in its contents: 14$"):
        pdf.parse_revised_pdf(raw)


@pytest.mark.parametrize("missing", ["title", "body"])
def test_known_bytes_still_require_the_verified_heading_and_body(monkeypatch, missing):
    raw = source("IE-2017-act-11")
    events, cutoff, expected = pdf._read(raw)
    prefix = "Amendment of Bail" if missing == "title" else "The Schedule to the Bail"
    index = next(i for i, e in enumerate(events) if e.text.startswith(prefix))
    chars = deepcopy(events[index].chars)
    chars[0]["text"] = "X"
    events[index] = replace(events[index], chars=chars)
    monkeypatch.setattr(pdf, "_read", lambda _, **_kw: (events, cutoff, expected))
    with pytest.raises(pdf.UnsupportedPDF, match="missing sections listed in its contents: 14$"):
        pdf.parse_revised_pdf(raw)
