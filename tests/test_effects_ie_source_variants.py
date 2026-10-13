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
    links = [
        link
        for link in doc.xpath("//a")
        if link.text_content().replace("(No ", "(No. ").startswith(title)
    ]
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


@pytest.mark.parametrize(
    ("provision", "identifier"),
    [
        ("S.I. No. 345 of of 2002, reg. 5(14)", "IE-2002-si-345"),
        ("S. I. No. 174, of 1974, par. 8", "IE-1974-si-174"),
        ("I.D. (No. 128), O., 1962", "IE-1962-si-163"),
        ("E.I.D. (No. S. I. 141) O., 1954", "IE-1954-si-141"),
        ("8 of 2006, s. 33(1)(b)", "IE-2006-act-8"),
    ],
)
def test_secondary_citation_punctuation_preserves_original_reference(provision, identifier):
    effect = parse_effects(directory("S. 1 amended", provision), "IE-1923-act-1")[0]
    assert effect["source_id"] == identifier
    assert effect["provision"] == provision


@pytest.mark.parametrize(
    ("year", "number", "expected"),
    [(1936, 55, "IE-1979-si-408"), (1936, 45, "IE-1989-act-3"), (1942, 22, "IE-2013-act-20")],
)
def test_missing_and_shortened_citations_are_tied_to_exact_primary_evidence(year, number, expected):
    raw = (FIXTURES / f"sample-effects-secondary-{year}-{number}.html").read_bytes()
    effects = parse_effects(raw, f"IE-{year}-act-{number}")
    assert effects and {e["source_id"] for e in effects} == {expected}
    if number == 55:
        assert all("S.I. No. 408 of 1979" in e["directory_footnotes"][0] for e in effects)
        with pytest.raises(ValueError, match="unresolved affecting"):
            parse_effects(raw.split(b"</table>")[0] + b"</table>", f"IE-{year}-act-{number}")
    else:
        assert all("source_correction" in e for e in effects)
        with pytest.raises(ValueError):
            parse_effects(raw, f"IE-{year}-act-999")
    if number == 45:
        text = " ".join(
            html.fromstring((FIXTURES / "sample-insurance-1989-schedule1.html").read_bytes())
            .text_content()
            .split()
        )
        assert "Section 3, in the definition of" in text and "industrial assurance business" in text


def test_gazette_proclamation_is_preserved_without_fabricating_an_instrument_id():
    raw = (FIXTURES / "sample-effects-secondary-1939-13.html").read_bytes()
    notes = []
    assert parse_effects(raw, "IE-1939-act-13", editorial_notes=notes) == []
    assert len(notes) == 2
    assert all(
        n["kind"] == "gazette_proclamation" and n["gazette_date"] == "1939-08-22" for n in notes
    )
    assert not any("source_id" in n for n in notes)


def test_undated_virtual_repeal_classification_does_not_invent_a_repeal_event():
    raw = (FIXTURES / "sample-effects-secondary-1955-28.html").read_bytes()
    notes = []
    assert parse_effects(raw, "IE-1955-act-28", editorial_notes=notes) == []
    assert notes == [
        {"kind": "directory_classification", "note": "Virt. Rep., Principal Act, Rep."}
    ]


def test_expired_qualifier_stays_with_the_outgoing_citation():
    raw = (FIXTURES / "sample-effects-secondary-1958-5.html").read_bytes()
    notes = []
    assert parse_effects(raw, "IE-1958-act-5", editorial_notes=notes) == []
    assert notes == [
        {
            "kind": "directory_classification",
            "note": "Spent",
            "provision": "Amended 20/1956 , expired.",
        }
    ]


def test_part_headers_may_state_their_section_range():
    raw = (FIXTURES / "sample-effects-secondary-1961-24.html").read_bytes()
    assert any(
        e["note"].startswith("PART I (ss. 1-10):") for e in parse_effects(raw, "IE-1961-act-24")
    )


def test_judgment_date_in_prose_is_preserved_with_its_source_footnote():
    raw = (FIXTURES / "sample-effects-secondary-1977-12.html").read_bytes()
    notes = []
    assert parse_effects(raw, "IE-1977-act-12", editorial_notes=notes) == []
    assert len(notes) == 1 and "4 June 2021" in notes[0]["provision"]
    assert "04/06/2021" in notes[0]["footnotes"][0]
