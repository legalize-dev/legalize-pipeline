"""Verified scanned appendices remain explicit omissions, never silently blank pages."""

from datetime import date
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pytest

from legalize.fetcher.ie import pdf

FIXTURES = Path(__file__).parent / "fixtures/ie"
EVIDENCE = json.loads((FIXTURES / "pdf-scanned-appendices-evidence.json").read_text())


def source(record, monkeypatch):
    raw = gzip.decompress((FIXTURES / record["file"]).read_bytes())
    assert sha256(raw).hexdigest() == record["fixture_sha256"]
    assert pdf._KNOWN_SCANNED_APPENDICES[record["sha256"]] == frozenset(record["scanned_pages"])
    if record["fixture_pages"] != "complete":
        monkeypatch.setitem(
            pdf._KNOWN_SCANNED_APPENDICES,
            record["fixture_sha256"],
            frozenset(record["fixture_scanned_pages"]),
        )
    return raw


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_scanned_appendices_keep_source_order_counts_and_a_warning(monkeypatch, record):
    raw = source(record, monkeypatch)
    paragraphs, cutoff = pdf.parse_revised_pdf(raw)
    omitted = [i for i, p in enumerate(paragraphs) if "[image omitted]" in p.text]
    assert len(omitted) == len(record["fixture_scanned_pages"])
    warning = pdf.source_warning(raw)
    assert "scanned legal forms or tables" in warning
    assert "contents are not transcribed" in warning
    assert all(str(page) in warning for page in record["fixture_scanned_pages"])
    if record["identifier"] == "IE-2015-act-2":
        assert cutoff == date(2021, 2, 1)
        assert sum(p.css_class == "articulo" for p in paragraphs) == 201
        assert "Section 116" in paragraphs[omitted[0] - 1].text
        assert omitted == [len(paragraphs) - 2, len(paragraphs) - 1]
    else:
        assert cutoff == date(2018, 8, 17)
        assert "2005/214/JHA" in paragraphs[omitted[0] - 1].text
        assert paragraphs[omitted[0] + 1].text == "]"
        assert len(paragraphs) > omitted[0] + 2


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_unknown_pdf_bytes_cannot_inherit_scanned_page_exceptions(monkeypatch, record):
    raw = source(record, monkeypatch) + b"\n"
    assert pdf.source_warning(raw) is None
    with pytest.raises(pdf.UnsupportedPDF, match="Image-only Revised Act PDF body page"):
        pdf.parse_revised_pdf(raw)


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_verified_source_does_not_allow_an_unlisted_scanned_page(monkeypatch, record):
    raw = source(record, monkeypatch)
    monkeypatch.setitem(pdf._KNOWN_SCANNED_APPENDICES, sha256(raw).hexdigest(), frozenset({9999}))
    with pytest.raises(pdf.UnsupportedPDF, match="Image-only Revised Act PDF body page"):
        pdf.parse_revised_pdf(raw)


def test_scanned_appendix_exception_cannot_hide_missing_sections(monkeypatch):
    raw = source(EVIDENCE[0], monkeypatch)
    events, cutoff, expected = pdf._read(raw)
    monkeypatch.setattr(pdf, "_read", lambda _: (events, cutoff, expected | {"9999"}))
    with pytest.raises(pdf.UnsupportedPDF, match="missing sections.*9999"):
        pdf.parse_revised_pdf(raw)
