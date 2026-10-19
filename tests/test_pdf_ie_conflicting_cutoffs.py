"""Only byte-verified catalogue/cover dates can resolve contradictory PDF headings."""

from datetime import date
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pytest

from legalize.fetcher.ie.effects import source_date
from legalize.fetcher.ie.history import revised_catalog
from legalize.fetcher.ie.pdf import UnsupportedPDF, parse_revised_pdf, source_warning

FIXTURES = Path(__file__).parent / "fixtures/ie"
EVIDENCE = json.loads((FIXTURES / "pdf-conflicting-cutoffs-evidence.json").read_text())


def pdf_bytes(record):
    raw = (FIXTURES / record["file"]).read_bytes()
    return gzip.decompress(raw) if record["file"].endswith(".gz") else raw


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_verified_cover_and_catalogue_cutoff_preserves_the_conflict(record):
    raw = pdf_bytes(record)
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
    raw = pdf_bytes(record) + b"\n"
    assert source_warning(raw) is None
    with pytest.raises(UnsupportedPDF, match="Conflicting Revised Act PDF cover dates"):
        parse_revised_pdf(raw)


def test_each_surveyed_cover_date_pin_matches_its_evidence():
    from legalize.fetcher.ie.pdf import _KNOWN_CUTOFF_CONFLICTS

    pins = json.loads((FIXTURES / "pdf-cover-date-pins.json").read_text())
    for pin in pins:
        assert _KNOWN_CUTOFF_CONFLICTS[pin["sha256"]] == (
            date.fromisoformat(pin["cutoff"]),
            date.fromisoformat(pin["other_date"]),
        )
        # The corroborated date is the front cover's and the catalogue row's.
        assert [d for page, d in pin["pages"] if page == 0] == [pin["cutoff"]]
        assert {d for _, d in pin["pages"]} == {pin["cutoff"], pin["other_date"]}
