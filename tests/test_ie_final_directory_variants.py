"""Final catalogue source forms preserve court findings and the true amender."""

from pathlib import Path

import pytest
from lxml import html, etree

from legalize.fetcher.ie.effects import parse_effects

FIXTURES = Path(__file__).parent / "fixtures/ie"


def source(identifier):
    return (FIXTURES / f"sample-effects-seventh-{identifier.removeprefix('IE-')}.html").read_bytes()


@pytest.mark.parametrize(
    ("identifier", "count"),
    [
        ("IE-2015-act-66", 1),
        ("IE-2015-act-16", 1),
        ("IE-2015-act-27", 2),
    ],
)
def test_court_findings_retain_provenance_without_becoming_legislative_events(identifier, count):
    notes = []
    assert parse_effects(source(identifier), identifier, editorial_notes=notes) == []
    assert len(notes) == count
    assert all(n["kind"] == "judicial_finding" and "publication_date" not in n for n in notes)
    if identifier == "IE-2015-act-16":
        assert notes[0]["directory_date"] == "6 April 2024"
        assert "[2021] IESC 24" in notes[0]["directory_date_source"]
    if identifier == "IE-2015-act-27":
        assert any(n["note"].endswith("declared constitutional") for n in notes)
        assert any(n["note"].endswith("declared unconstitutional") for n in notes)
    with pytest.raises(ValueError, match="editorial_notes destination"):
        parse_effects(source(identifier), identifier)


@pytest.mark.parametrize(
    ("identifier", "amender", "host"),
    [
        ("IE-1984-act-9", "IE-1992-act-28", "9/1992"),
        ("IE-1966-act-21", "IE-1998-act-33", "28/1988"),
    ],
)
def test_amender_on_next_source_row_replaces_the_host_citation(identifier, amender, host):
    effects = parse_effects(source(identifier), identifier)
    assert len(effects) == 1
    assert effects[0]["source_id"] == amender
    assert host in effects[0]["provision"]
    assert "by " in effects[0]["provision"]


@pytest.mark.parametrize("missing", ["row", "blank_note"])
def test_dangling_indirect_citation_cannot_borrow_an_unrelated_next_row(missing):
    doc = html.fromstring(source("IE-1984-act-9"))
    rows = doc.xpath("//tr")
    if missing == "row":
        rows[1].getparent().remove(rows[1])
    else:
        rows[1].find("td").text = "A separate effect"
    with pytest.raises(ValueError, match="unresolved affecting provision"):
        parse_effects(etree.tostring(doc), "IE-1984-act-9")


def test_named_adoption_repeal_keeps_its_verified_source_and_commencement():
    effects = parse_effects(source("IE-2015-act-9"), "IE-2015-act-9")
    assert len(effects) == 1
    assert effects[0]["source_id"] == "IE-2017-act-19"
    assert effects[0]["effective_date"] == "2017-10-19"
    assert effects[0]["source_correction"].endswith("/2017/act/19/section/2/enacted/en/html")
