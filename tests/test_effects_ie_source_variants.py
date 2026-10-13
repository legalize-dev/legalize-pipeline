"""Directory qualifications and judicial references retain their original evidence."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from lxml import html

from legalize.fetcher.ie.effects import _DUTY_ORDERS, fetch_effects, norm_id_from_url, parse_effects

FIXTURES = Path(__file__).parent / "fixtures/ie"


def directory(note, provision):
    return f'<h3 id="effects">Effects</h3><table><tr><td>{note}</td><td>{provision}</td></tr></table>'.encode()


@pytest.mark.parametrize(("citation", "expected"), list(_DUTY_ORDERS.items()))
def test_abbreviated_duty_order_is_verified_against_the_official_index(citation, expected):
    kind, number, year = citation
    doc = html.fromstring((FIXTURES / f"sample-duty-order-index-{year}.html").read_bytes())
    title = ("Emergency " if kind == "E.I.D." else "") + f"Imposition of Duties (No. {number})"
    links = [link for link in doc.xpath("//a") if link.text_content().startswith(title)]
    assert len(links) == 1
    assert norm_id_from_url(links[0].get("href")) == expected
    provision = f"{kind} (No. {number}) O., {year}, par. 23"
    effects = parse_effects(directory("S. 1 repealed", provision), "IE-1924-act-27")
    assert [effect["source_id"] for effect in effects] == [expected]
    assert effects[0]["provision"] == provision


def test_two_duty_orders_are_not_partially_resolved():
    source = directory("S. 1 amended", "E.I.D. (No. 223) O., 1941 E.I.D. (No. 357) O., 1955")
    assert {effect["source_id"] for effect in parse_effects(source, "IE-1927-act-38")} == {
        "IE-1941-si-464",
        "IE-1955-si-173",
    }
    with pytest.raises(ValueError, match="unresolved duties order"):
        parse_effects(source.replace(b"357", b"999"), "IE-1927-act-38")


def test_missing_compensation_citation_uses_the_confirming_primary_provision():
    raw = (FIXTURES / "sample-effects-blank-citation-1923-15.html").read_bytes()
    effects = parse_effects(raw, "IE-1923-act-15")
    effect = next(e for e in effects if e["note"].startswith("Compensation under collectively"))
    assert effect["source_id"] == "IE-1937-act-18"
    assert effect["provision"] == ""
    assert effect["source_correction"].endswith("/1937/act/18/section/17/enacted/en/html")
    evidence = html.fromstring(
        (FIXTURES / "sample-finance-1937-section17.html").read_bytes()
    ).text_content()
    assert "Damage to Property (Compensation) Acts, 1923 to 1933" in evidence
    assert "pay in money out of moneys provided by the Oireachtas" in " ".join(evidence.split())
    with pytest.raises(ValueError, match="no affecting provision"):
        parse_effects(raw, "IE-1923-act-16")


@pytest.mark.parametrize(
    ("year", "number", "count"),
    [(1924, 16, 1), (1927, 23, 2), (1935, 6, 2), (1937, 30, 1), (1946, 26, 9)],
)
def test_judicial_rows_preserve_evidence_without_inventing_legislative_ids_or_dates(
    year, number, count
):
    raw = (FIXTURES / f"sample-effects-judicial-{year}-{number}.html").read_bytes()
    notes = []
    identifier = f"IE-{year}-act-{number}"
    client = Mock(_base_url="https://www.irishstatutebook.ie")
    client._get.return_value = raw
    effects = fetch_effects(
        client,
        identifier,
        f'<a href="/isbc/{year}_{number}.html">Amendments</a>'.encode(),
        editorial_notes=notes,
    )
    assert effects == []
    assert len(notes) == count
    assert all(n["kind"] == "judicial_finding" and n["note"] for n in notes)
    assert all(n["provision"] or n["footnotes"] for n in notes)
    assert all(n["directory_url"].endswith(f"/isbc/{year}_{number}.html") for n in notes)
    assert not any(
        "source_id" in n or "publication_date" in n or "effective_date" in n for n in notes
    )
    client.get_metadata.assert_not_called()
    with pytest.raises(ValueError, match="editorial_notes destination"):
        parse_effects(raw, identifier)
    if year == 1935:
        assert len(notes[0]["footnotes"]) == len(notes[1]["footnotes"]) == 1
        assert "C.C. v" in notes[0]["footnotes"][0]
        assert "Douglas v" in notes[1]["footnotes"][0]


def test_unexplained_asterisk_or_unknown_citation_still_fails():
    for raw in [directory("S. 1*", ""), directory("S. 1 declared invalid", "Unknown source")]:
        with pytest.raises(ValueError):
            parse_effects(raw, "IE-1924-act-1", editorial_notes=[])


def test_spent_provision_retains_its_explanation():
    notes = []
    raw = (FIXTURES / "sample-effects-spent-provision-1938-18.html").read_bytes()
    parse_effects(raw, "IE-1938-act-18", editorial_notes=notes)
    assert notes == [
        {
            "note": "Spent",
            "provision": "Cesser in s. 3 and provisions relate to year commencing 6 April 1938 only.",
        }
    ]


def test_scope_headers_are_attached_to_the_next_amendments():
    raw = (FIXTURES / "sample-effects-scope-1942-22.html").read_bytes()
    notes = [e["note"] for e in parse_effects(raw, "IE-1942-act-22")]
    assert any(n.startswith("PART IIIA CHAPTER 2A:") for n in notes)
    assert any(n.startswith("PART IIIA CHAPTER 1:") for n in notes)
    assert any(n.startswith("PARTS IIID, IV:") for n in notes)
