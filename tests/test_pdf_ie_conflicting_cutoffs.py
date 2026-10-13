"""Only byte-verified catalogue/cover dates can resolve contradictory PDF headings."""

from datetime import date
from hashlib import sha256
import json
from pathlib import Path

import pytest

from legalize.fetcher.ie.effects import source_date
from legalize.fetcher.ie.history import revised_catalog
from legalize.fetcher.ie.pdf import UnsupportedPDF, parse_revised_pdf, source_warning

FIXTURES = Path(__file__).parent / "fixtures/ie"
EVIDENCE = json.loads((FIXTURES / "pdf-conflicting-cutoffs-evidence.json").read_text())


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_verified_cover_and_catalogue_cutoff_preserves_the_conflict(record):
    raw = (FIXTURES / record["file"]).read_bytes()
    assert sha256(raw).hexdigest() == record["sha256"]
    catalogue = record["catalogue"]
    excerpt = (FIXTURES / catalogue["excerpt_file"]).read_bytes()
    assert sha256(excerpt).hexdigest() == catalogue["excerpt_sha256"]
    rows = revised_catalog(excerpt)[record["identifier"]]
    assert len(rows) == 1
    assert rows[0]["catalog_date"] == record["cutoff"]
    assert record["url"] in (rows[0]["url"], rows[0].get("pdf_url"))
    paragraphs, cutoff = parse_revised_pdf(raw)
    assert cutoff == date.fromisoformat(record["cutoff"])
    assert any(p.css_class == "articulo" and p.text.startswith("1.") for p in paragraphs)
    warning = source_warning(raw)
    assert "conflicting revision dates" in warning
    assert "front cover and the LRC catalogue" in warning
    assert record["cutoff"] in warning
    for printed in record["printed_dates"]:
        assert source_date(printed).isoformat() in warning


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_an_unverified_pdf_cannot_inherit_another_files_cutoff(record):
    raw = (FIXTURES / record["file"]).read_bytes() + b"\n"
    assert source_warning(raw) is None
    with pytest.raises(UnsupportedPDF, match="Conflicting Revised Act PDF cover dates"):
        parse_revised_pdf(raw)
