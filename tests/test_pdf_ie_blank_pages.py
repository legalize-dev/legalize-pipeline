"""Blank separator pages are distinct from unreadable text or vector-only content."""

from hashlib import sha256
import json
from pathlib import Path

import pytest

from legalize.fetcher.ie import pdf

FIXTURES = Path(__file__).parent / "fixtures/ie"
RECORD = json.loads((FIXTURES / "pdf-blank-page-evidence.json").read_text())


def source():
    raw = (FIXTURES / RECORD["file"]).read_bytes()
    assert sha256(raw).hexdigest() == RECORD["fixture_sha256"]
    return raw


def test_white_separator_page_does_not_erase_surrounding_legislation():
    paragraphs, cutoff = pdf.parse_revised_pdf(source())
    assert cutoff
    assert any(p.css_class == "articulo" and p.text.startswith("1.") for p in paragraphs)
    assert any("carrying out of a request" in p.text for p in paragraphs)
    assert not any("Related legislation" in p.text for p in paragraphs)
    assert not any("[image omitted]" in p.text for p in paragraphs)


@pytest.mark.parametrize("mark", ["fill", "stroke"])
def test_a_page_with_visible_vector_content_cannot_be_discarded(monkeypatch, mark):
    original = pdf.pdfplumber.open

    def vector_page(*args, **kwargs):
        document = original(*args, **kwargs)
        rectangle = document.pages[RECORD["blank_page"] - 1].objects["rect"][0]
        assert rectangle["top"] > 78
        if mark == "fill":
            rectangle["non_stroking_color"] = (0, 0, 0)
        else:
            rectangle["stroke"] = True
        return document

    monkeypatch.setattr(pdf.pdfplumber, "open", vector_page)
    with pytest.raises(pdf.UnsupportedPDF, match="Empty page inside Revised Act PDF body"):
        pdf.parse_revised_pdf(source())


@pytest.mark.parametrize("missing", ["identity", "editorial_description"])
def test_an_introduction_without_verified_backmatter_is_preserved(monkeypatch, missing):
    original = pdf.pdfplumber.open

    def changed_page(*args, **kwargs):
        document = original(*args, **kwargs)
        page = document.pages[-1]
        extract = page.extract_text_lines

        def lines(*args, **kwargs):
            result = extract(*args, **kwargs)
            for line in result:
                if missing == "identity" and line["text"].startswith("Number 23"):
                    line["text"] = "Schedule introduction"
                if missing == "editorial_description" and line["text"].startswith(
                    "This Revised Act presents the text"
                ):
                    line["text"] = "An unverified introductory paragraph"
            return result

        monkeypatch.setattr(page, "extract_text_lines", lines)
        return document

    monkeypatch.setattr(pdf.pdfplumber, "open", changed_page)
    paragraphs, _ = pdf.parse_revised_pdf(source())
    assert any("Related legislation" in p.text for p in paragraphs)
