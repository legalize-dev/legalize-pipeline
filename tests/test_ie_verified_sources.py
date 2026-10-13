"""Keep verified source repairs separate from unknown dates and amendments."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest

from legalize.fetcher.ie.effects import fetch_effects, parse_effects
from legalize.fetcher.ie.parser import ISBMetadataParser, ISBTextParser

FIXTURES = Path(__file__).parent / "fixtures/ie"


@pytest.mark.parametrize(
    ("identifier", "published", "made", "basis"),
    [
        ("IE-2003-si-79", "2003-02-28", "2003-02-28", "final_signature"),
        ("IE-2003-si-497", "2003-11-07", "2003-10-21", "gazette_notice"),
        ("IE-2006-si-341", "2006-06-29", "2006-06-29", "final_signature"),
    ],
)
def test_verified_instrument_dates_preserve_body_and_distinct_date_semantics(
    identifier, published, made, basis
):
    raw = (FIXTURES / f"sample-{identifier.lower()}-fifth.html").read_bytes()
    metadata = ISBMetadataParser().parse(raw, identifier)
    version = ISBTextParser().parse_text(raw)[0].versions[0]
    assert metadata.publication_date == version.publication_date == date.fromisoformat(published)
    extra = dict(metadata.extra)
    assert extra["made_date"] == made
    assert extra["publication_date_basis"] == basis
    assert "signature_date_unknown" not in extra
    if identifier == "IE-2003-si-79":
        assert json.loads(extra["signature_dates"]) == ["2003-02-18", "2003-02-28"]
        assert extra["signature_date_source"].endswith("pdf#page=20")
        with pytest.raises(ValueError, match="lacks its title or enactment date"):
            ISBMetadataParser().parse(raw.replace(b"79/2003", b"80/2003"), "IE-2003-si-80")
    elif identifier == "IE-2006-si-341":
        assert any("29h June 2006" in p.text for p in version.paragraphs)
        assert "[^1]: OJ L56/8 of 2.3.2005" in [p.text for p in version.paragraphs]
    else:
        paragraphs = [p.text for p in version.paragraphs]
        assert any("Directive 93/22/EEC" in p and "[^6]" in p for p in paragraphs)
        note = next(p for p in paragraphs if p.startswith("[^1-fn_10]:"))
        assert "net asset value of units" in note
        assert "the stock exchange in the country of marketing" in note
        assert sum("the stock exchange in the country of marketing" in p for p in paragraphs) == 1
        assert any("prices[^1-fn_10]" in p for p in paragraphs)


@pytest.mark.parametrize(
    ("identifier", "published"),
    [
        ("IE-2021-act-3", "2021-03-18"),
        ("IE-2022-act-38", "2022-12-02"),
    ],
)
def test_official_pdf_corroborates_xml_typographical_errors(identifier, published):
    raw = (FIXTURES / f"sample-{identifier.lower()}-fifth.xml").read_bytes()
    metadata = ISBMetadataParser().parse(raw, identifier)
    version = ISBTextParser().parse_text(raw)[0].versions[0]
    assert metadata.publication_date == version.publication_date == date.fromisoformat(published)
    if identifier == "IE-2022-act-38":
        assert dict(metadata.extra)["identity_source_printed_numbers"] == "38, 39"
        assert dict(metadata.extra)["identity_correction_source"].endswith("en.act.2022.0038.pdf")
        with pytest.raises(ValueError, match="different Act"):
            ISBMetadataParser().parse(raw, "IE-2022-act-39")


def directory(identifier):
    raw = (FIXTURES / f"sample-effects-fifth-{identifier.removeprefix('IE-')}.html").read_bytes()
    notes = []
    return parse_effects(raw, identifier, editorial_notes=notes), notes


@pytest.mark.parametrize(
    ("identifier", "source"),
    [
        ("IE-2010-act-25", "IE-2011-act-28"),
        ("IE-2011-act-10", "IE-2017-act-22"),
        ("IE-2006-act-26", "IE-2017-act-4"),
        ("IE-2006-act-23", "IE-2022-act-7"),
        ("IE-2009-act-45", "IE-2012-act-22"),
    ],
)
def test_named_citations_resolve_the_actual_enactment(identifier, source):
    effects, _ = directory(identifier)
    assert any(e["source_id"] == source for e in effects)
    if identifier == "IE-2006-act-26":
        assert not any(e["source_id"] == "IE-2014-act-4" for e in effects)


def test_unmarked_judicial_footnote_covers_both_named_subsections_only():
    effects, notes = directory("IE-2006-act-26")
    findings = [n for n in notes if n["kind"] == "judicial_finding"]
    assert {n["note"] for n in findings} == {"S. 99(9)*", "S. 99(10)*"}
    assert all("Moore" in n["footnotes"][0] for n in findings)
    assert any(e["note"].startswith("S. 99") for e in effects)


@pytest.mark.parametrize(("identifier", "count"), [("IE-2007-act-10", 4), ("IE-2013-act-23", 1)])
def test_unresolved_collective_membership_preserves_context_without_invented_dates(
    identifier, count
):
    effects, notes = directory(identifier)
    assert len([n for n in notes if n["kind"] == "collective_citation"]) == count
    assert effects
    assert all("publication_date" not in n for n in notes)


def test_unaccented_parliamentary_resolutions_remain_source_notes():
    effects, notes = directory("IE-2009-act-32")
    assert effects == []
    assert len(notes) == 16
    assert all(n["kind"] == "parliamentary_resolution" for n in notes)
    assert any("24 June 2020" in n["provision"] for n in notes)


@pytest.mark.parametrize(
    "phrase",
    [
        "Act included in collectively cited Example Acts",
        "Act included in Example Acts",
        "Act, Part 5 (ss. 57-63) included in collectively cited Example Acts",
        "Collective citation Example Acts 1967 to 2008",
    ],
)
def test_earlier_collective_member_is_context_but_later_member_retains_its_reform(phrase):
    def enacted(year):
        return f'<html><title>Example Act {year}</title><a href="/isbc/2000_1.html">History</a><div id="act">[1st January, {year}]</div></html>'.encode()

    rows = f'<h2 id="effects">Effects</h2><table><tr><td>{phrase}</td><td>1/1990</td></tr><tr><td>{phrase}</td><td>1/2010</td></tr></table>'.encode()
    client = Mock(_base_url="https://www.irishstatutebook.ie")
    client._get.return_value = rows
    client.get_metadata.side_effect = lambda identifier: enacted(identifier.split("-")[1])
    notes = []
    effects = fetch_effects(client, "IE-2000-act-1", enacted(2000), editorial_notes=notes)
    assert [e["source_id"] for e in effects] == ["IE-2010-act-1"]
    assert notes[0]["source_id"] == "IE-1990-act-1"
    assert notes[0]["publication_date"] == "1990-01-01"
    assert notes[0]["directory_url"].endswith("/isbc/2000_1.html")
    assert notes[0]["kind"] == "collective_citation"
    with pytest.raises(ValueError, match="requires a provenance sink"):
        fetch_effects(client, "IE-2000-act-1", enacted(2000))


@pytest.mark.parametrize("clause", ["subst. by 23/2014", "inserted by23/2014"])
def test_abbreviated_indirect_citation_selects_the_later_amender(clause):
    raw = f'<h2 id="effects">Effects</h2><table><tr><td>S. 3 amended</td><td>39/1997, s. 4 ({clause}, s. 10)</td></tr></table>'.encode()
    assert [e["source_id"] for e in parse_effects(raw, "IE-2000-act-1")] == ["IE-2014-act-23"]


@pytest.mark.parametrize(
    "citation",
    [
        "Pensions Act 1990 (No. 25 of 1990), s. 9A",
        "Pensions Act 1990 (25/1990), s. 9A(see amendment)",
    ],
)
def test_pensions_reference_uses_the_2013_insertion(citation):
    raw = f'<h2 id="effects">Effects</h2><table><tr><td>References construed</td><td>{citation}</td></tr></table>'.encode()
    effect = parse_effects(raw, "IE-2000-act-1")[0]
    assert effect["source_id"] == "IE-2013-act-20"
    assert effect["directory_source_id"] == "IE-1990-act-25"
    assert effect["effective_date"] == "2014-03-07"
