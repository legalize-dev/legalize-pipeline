"""Exact source defects remain visible without silently renumbering or losing entries."""

from copy import deepcopy
from dataclasses import replace
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re

import pytest

from legalize.fetcher.ie import pdf

FIXTURES = Path(__file__).parent / "fixtures/ie"
EVIDENCE = json.loads((FIXTURES / "pdf-label-defects-evidence.json").read_text())


def source(record):
    raw = gzip.decompress((FIXTURES / record["file"]).read_bytes())
    assert sha256(raw).hexdigest() == record["sha256"]
    return raw


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_source_labels_and_every_existing_entry_are_preserved_with_a_warning(record):
    raw = source(record)
    paragraphs, cutoff = pdf.parse_revised_pdf(raw)
    assert cutoff
    headings = [p.text for p in paragraphs if p.css_class == "articulo"]
    warning = pdf.source_warning(raw)
    if record["identifier"] == "IE-2004-act-3":
        assert [h for h in headings if h.startswith("30M.")] == [
            "30M. **Record of stillbirths.**",
            "30M. **Definition (Part 3C).**",
        ]
        assert "repeats section number 30M" in warning
        assert any("establish and maintain a record of stillbirths" in p.text for p in paragraphs)
    elif record["identifier"] == "IE-2005-act-20":
        assert any(h.startswith("33D.") for h in headings)
        assert any(h.startswith("33F.") for h in headings)
        assert not any(h.startswith("33E.") for h in headings)
        assert "section 33E" in warning and "absent from the body" in warning
        assert "not been reconstructed" in warning
    else:
        assert [h for h in headings if h.startswith("69.")] == [
            "69. **Appeal against refusal or revocation of licence.**",
            "69. **Regulations in relation to animal marts.**",
        ]
        assert not any(h.startswith("70.") for h in headings)
        assert any(h.startswith("71M.") and "Musk Rats Act 1933" in h for h in headings)
        index = next(i for i, p in enumerate(paragraphs) if p.text.startswith("71M."))
        assert paragraphs[index + 1].text.startswith("All licences")
        assert "revoked" in paragraphs[index + 1].text
        assert "numbered 70 in the contents" in warning
        assert "Section 71M's body omits its number" in warning


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_unknown_bytes_never_inherit_numbering_or_omission_exceptions(record):
    raw = source(record) + b"\n"
    assert pdf.source_warning(raw) is None
    with pytest.raises(pdf.UnsupportedPDF, match="Duplicate primary section|missing sections"):
        pdf.parse_revised_pdf(raw)


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_known_bytes_do_not_allow_other_missing_sections(monkeypatch, record):
    raw = source(record)
    events, cutoff, expected = pdf._read(raw)
    monkeypatch.setattr(pdf, "_read", lambda _: (events, cutoff, expected | {"9999"}))
    with pytest.raises(pdf.UnsupportedPDF, match="9999"):
        pdf.parse_revised_pdf(raw)


@pytest.mark.parametrize("identifier, number", [("IE-2004-act-3", "30M"), ("IE-2013-act-15", "69")])
def test_a_verified_duplicate_cannot_hide_the_loss_of_one_entry(monkeypatch, identifier, number):
    raw = source(next(r for r in EVIDENCE if r["identifier"] == identifier))
    events, cutoff, expected = pdf._read(raw)
    indices = [i for i, e in enumerate(events) if re.search(rf"\b{number}\.\s*—", e.text)]
    assert len(indices) == 2
    del events[indices[0] : indices[1]]
    monkeypatch.setattr(pdf, "_read", lambda _: (events, cutoff, expected))
    with pytest.raises(
        pdf.UnsupportedPDF, match="duplicate section entries were not fully preserved"
    ):
        pdf.parse_revised_pdf(raw)


def test_unnumbered_marginal_section_requires_its_verified_body(monkeypatch):
    raw = source(next(r for r in EVIDENCE if r["identifier"] == "IE-2013-act-15"))
    events, cutoff, expected = pdf._read(raw)
    index = next(i for i, e in enumerate(events) if "All licences granted under" in e.text)
    chars = deepcopy(events[index].chars)
    first = next(c for c in chars if c["text"] == "A" and c["x0"] > 140)
    first["text"] = "X"
    events[index] = replace(events[index], chars=chars)
    monkeypatch.setattr(pdf, "_read", lambda _: (events, cutoff, expected))
    with pytest.raises(pdf.UnsupportedPDF, match="71M"):
        pdf.parse_revised_pdf(raw)
