"""Column numbering must not split a ruled header into invented data rows."""

from hashlib import sha256
import json
from pathlib import Path

import pytest

from legalize.fetcher.ie import pdf

FIXTURES = Path(__file__).parent / "fixtures/ie"
RECORD = json.loads((FIXTURES / "pdf-numbered-table-header-evidence.json").read_text())


def source():
    raw = (FIXTURES / RECORD["file"]).read_bytes()
    assert sha256(raw).hexdigest() == RECORD["fixture_sha256"]
    return raw


def test_wrapped_numbered_headers_preserve_all_cells_and_complete_amending_text():
    paragraphs, cutoff = pdf.parse_revised_pdf(source())
    assert str(cutoff) == "2019-01-28"
    tables = [p.text for p in paragraphs if p.css_class == "table"]
    assert len(tables) == 3
    assert all("| Item (1) | Provision affected (2) | Amendment (3) |" in t for t in tables)
    assert "| 2 | Regulation 9(7) |" in tables[0]
    assert "| 2 | Regulation 4 |" in tables[1]
    assert "| 1 | Regulation 2(2) |" in tables[2]
    assert "rights of third parties existing before the direction comes into effect" in tables[2]
    assert len(tables[2].splitlines()) == 4


def test_unverified_column_labels_do_not_bypass_ambiguous_row_guard(monkeypatch):
    original = pdf.pdfplumber.open

    def changed_header(*args, **kwargs):
        document = original(*args, **kwargs)
        page = document.pages[-1]
        table_page = page.filter(lambda o: o["object_type"] != "rect" or o.get("stroke"))
        box = table_page.find_tables()[-1].rows[0].cells[1]
        digit = next(c for c in page.chars if c["text"] == "2" and pdf._inside(c, box))
        digit["text"] = "9"
        return document

    monkeypatch.setattr(pdf.pdfplumber, "open", changed_header)
    with pytest.raises(pdf.UnsupportedPDF, match="Ambiguous row boundaries"):
        pdf.parse_revised_pdf(source())
