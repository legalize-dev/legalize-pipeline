import re
from datetime import date

import pytest

from legalize.fetcher.ie.effects import norm_id_from_url, parse_effects, source_date


def test_citation_identity_keeps_act_namespaces():
    assert (
        norm_id_from_url("https://www.irishstatutebook.ie/2019/en/act/cam/0038/index.html")
        == "IE-2019-act-C38"
    )
    assert (
        norm_id_from_url("https://www.irishstatutebook.ie/2023/en/act/prv/0001/index.html")
        == "IE-2023-act-P1"
    )
    assert (
        norm_id_from_url("https://www.irishstatutebook.ie/2024/en/si/0356.html") == "IE-2024-si-356"
    )


def test_inserted_and_substituted_relations_use_the_amending_instrument():
    from pathlib import Path

    source = (Path(__file__).parent / "fixtures/ie/sample-effects-companies-2014.html").read_bytes()
    effects = parse_effects(source, "IE-2014-act-38")
    indirect = [
        row for row in effects if re.search(r"as (?:inserted|substituted) by", row["provision"])
    ]
    assert len(indirect) == 16
    assert {row["source_id"] for row in indirect} == {
        "IE-2024-act-11",
        "IE-2022-act-39",
        "IE-2019-act-2",
        "IE-2017-act-41",
        "IE-2015-act-61",
        "IE-2018-si-6",
        "IE-2020-act-8",
        "IE-2021-act-30",
    }
    assert not any(int(row["source_id"].split("-")[1]) < 2014 for row in effects)
    assert any("Gas Regulation Act 2013 (39/2013)" in row["provision"] for row in indirect)


def test_indirect_relation_preserves_namespaces_even_when_year_and_number_match():
    source = b"""<h3 id="effects">Effects</h3><table><tr><td>Application restricted</td>
    <td>Public Act (<a href="/eli/2020/act/1">1/2020</a>) as <em>inserted</em> by
    Private Act (<a href="/eli/2020/prv/1">1/2020</a>), s. 2</td></tr></table>"""
    assert [row["source_id"] for row in parse_effects(source, "IE-2014-act-38")] == [
        "IE-2020-act-P1"
    ]


def test_companies_commencement_repairs_preserve_the_directory_claims():
    from pathlib import Path

    source = (Path(__file__).parent / "fixtures/ie/sample-effects-companies-2014.html").read_bytes()
    effects = parse_effects(source, "IE-2014-act-38")
    repaired = [row for row in effects if row.get("directory_commencement")]
    assert len(repaired) == 11
    expected = {
        "IE-2024-act-11": ("2014-06-03", "2024-06-01", "/2024/si/208/made/en/html"),
        "IE-2022-act-39": ("2013-03-29", "2023-01-01", "/2022/si/678/made/en/html"),
        "IE-2019-act-2": ("1983-11-08", "2019-09-30", "/2019/si/439/made/en/html"),
        "IE-2017-act-41": ("2001-11-01", "2017-12-25", "/isbc/2017_41.html#commencement"),
    }
    for row in repaired:
        old, actual, evidence = expected[row["source_id"]]
        assert source_date(row["directory_commencement"]).isoformat() == old
        assert row["directory_commencement_source"]
        assert row["effective_date"] == actual
        assert row["source_correction"].endswith(evidence)
        assert row["commencement_source"] == row["source_correction"]
    assert not any(
        row.get("directory_commencement") for row in parse_effects(source, "IE-2014-act-39")
    )
    altered = source.replace(b">20</a>(b)", b">99</a>(b)")
    assert altered != source
    gas = next(
        row
        for row in parse_effects(altered, "IE-2014-act-38")
        if row["source_id"] == "IE-2024-act-11"
    )
    assert "directory_commencement" not in gas


def test_effects_keep_pending_repeals_and_do_not_invent_publication_dates():
    source = b"""<h3 id="effects">Effects</h3><table><tbody>
    <tr><td>S. 19 repealed</td><td><a href="/2026/en/act/pub/0014/index.html">14/2026</a></td>
    <td></td><td>Not yet commenced. Commencement order required</td></tr>
    <tr><td>S. 21 repealed</td><td><a href="/2024/en/si/0356.html">S.I. 356/2024</a></td>
    <td>31 July 2024</td><td>Regulation 3</td></tr>
    <tr><td></td><td><a href="/2024/en/si/0357.html">S.I. 357/2024</a></td>
    <td>1 August 2024</td><td>Regulation 4</td></tr>
    </tbody></table>"""
    effects = parse_effects(source, "IE-2015-act-29")
    assert effects[0]["pending"] and not effects[0]["whole_repeal"]
    assert effects[1]["effective_date"] == "2024-07-31"
    assert "publication_date" not in effects[1]
    assert effects[2]["note"] == "S. 21 repealed"


def test_older_directory_can_cite_constitution_without_a_link():
    source = b"""<h3 id="effects">Effects</h3><table><tr>
    <td>*Repealed</td><td>Constitution of Ireland 1937, Art.48</td></tr></table>"""
    effects = parse_effects(source, "IE-1922-act-1")
    assert effects[0]["whole_repeal"]
    assert effects[0]["source_id"] == "IE-1937-constitution"


def test_constitution_repeal_takes_effect_on_stated_operation_date_not_adoption():
    from pathlib import Path
    from unittest.mock import Mock

    from legalize.fetcher.ie.effects import fetch_effects

    fixtures = Path(__file__).parent / "fixtures/ie"
    client = Mock(_base_url="https://www.irishstatutebook.ie")
    client._get.return_value = (fixtures / "sample-effects-constitution-1922.html").read_bytes()
    client.get_metadata.return_value = (fixtures / "sample-constitution.html").read_bytes()
    effects = fetch_effects(client, "IE-1922-act-1", b'<a href="/isbc/1922_1.html">Amendments</a>')
    assert len(effects) == 1
    effect = effects[0]
    assert effect["whole_repeal"] and not effect["pending"]
    assert effect["publication_date"] == "1937-07-01"
    assert effect["effective_date"] == "1937-12-29"
    assert effect["commencement"] == "In operation as from 29th December, 1937"
    assert effect["commencement_source"].endswith("/eli/cons/en/html#article48")
    client.get_metadata.assert_called_once_with("IE-1937-constitution")


@pytest.mark.parametrize(
    ("original", "replacement", "message"),
    [
        (b"In operation as from ", b"Operation date unavailable: ", "stated operation date"),
        (b"repealed as on and from that date", b"repealed", "repeal commencement rule"),
    ],
)
def test_constitution_repeal_does_not_guess_when_source_rule_is_missing(
    original, replacement, message
):
    from pathlib import Path
    from unittest.mock import Mock

    from legalize.fetcher.ie.effects import fetch_effects

    fixtures = Path(__file__).parent / "fixtures/ie"
    client = Mock(_base_url="https://www.irishstatutebook.ie")
    client._get.return_value = (fixtures / "sample-effects-constitution-1922.html").read_bytes()
    client.get_metadata.return_value = (
        (fixtures / "sample-constitution.html").read_bytes().replace(original, replacement)
    )
    with pytest.raises(ValueError, match=message):
        fetch_effects(client, "IE-1922-act-1", b'<a href="/isbc/1922_1.html">Amendments</a>')


def test_unknown_directory_markup_is_not_no_amendments():
    with pytest.raises(ValueError, match="no effects section"):
        parse_effects(b"<html>Service unavailable</html>", "IE-2024-act-1")
    assert source_date("31 February 2024") is None
    assert source_date("2nd August, 2024") == date(2024, 8, 2)


def test_live_constitution_table_uses_signature_date_not_identifier_year():
    from pathlib import Path
    from unittest.mock import Mock

    from legalize.fetcher.ie.effects import fetch_effects

    source = (Path(__file__).parent / "fixtures/ie/sample-constitution.html").read_bytes()
    client = Mock(_base_url="https://www.irishstatutebook.ie")
    effects = fetch_effects(client, "IE-1937-constitution", source)
    assert len(effects) == 32
    fourth = next(effect for effect in effects if effect["source_id"] == "IE-1972-act-C4")
    assert fourth["publication_date"] == "1973-01-05"
    assert "minimum voting age" in fourth["note"]
    assert effects[-1]["publication_date"] == "2019-06-11"
    client._get.assert_not_called()
    client.get_metadata.assert_not_called()


def test_live_pending_repeals_use_enactment_and_si_publication_dates():
    from pathlib import Path
    from unittest.mock import Mock

    from legalize.fetcher.ie.effects import fetch_effects

    fixtures = Path(__file__).parent / "fixtures/ie"
    client = Mock(_base_url="https://www.irishstatutebook.ie")
    client._get.return_value = (fixtures / "sample-effects-environment-2015.html").read_bytes()
    sources = {
        "IE-2026-act-14": (fixtures / "sample-effects-act-2026-14-metadata.json").read_bytes(),
        "IE-2024-si-356": (fixtures / "sample-effects-source-si-2024-356.html").read_bytes(),
        "IE-2024-si-357": (fixtures / "sample-effects-source-si-2024-357.html").read_bytes(),
    }
    client.get_metadata.side_effect = sources.__getitem__
    page = b'<html><a href="/isbc/2015_29.html">Amendments</a></html>'
    effects = fetch_effects(client, "IE-2015-act-29", page)
    assert len(effects) == 7
    pending = [effect for effect in effects if effect["source_id"] == "IE-2026-act-14"]
    assert len(pending) == 5
    assert all(effect["pending"] and not effect["whole_repeal"] for effect in pending)
    assert all(effect["publication_date"] == "2026-06-18" for effect in pending)
    instrument = next(effect for effect in effects if effect["source_id"] == "IE-2024-si-356")
    assert instrument["effective_date"] == "2024-07-31"
    assert instrument["publication_date"] == "2024-08-02"
    assert client.get_metadata.call_count == 3


def test_actual_private_directory_groups_and_explicit_si_labels():
    from pathlib import Path

    fixtures = Path(__file__).parent / "fixtures/ie"
    source = (fixtures / "sample-effects-private-1925.html").read_bytes()
    first = parse_effects(source, "IE-1925-act-P1")
    assert len(first) == 1 and first[0]["whole_repeal"]
    assert first[0]["source_id"] == "IE-1944-act-21"
    assert parse_effects(source, "IE-1925-act-P2") == []
    third = parse_effects(source, "IE-1925-act-P3")
    assert not any(effect["note"].startswith("References construed:") for effect in third)
    assert {effect["source_id"] for effect in third} == {
        "IE-2013-act-50",
        "IE-1996-si-183",
        "IE-1991-si-83",
        "IE-2021-act-13",
    }
    source = (fixtures / "sample-effects-private-2003.html").read_bytes()
    assert {effect["source_id"] for effect in parse_effects(source, "IE-2003-act-P1")} == {
        "IE-2020-si-451",
        "IE-2012-act-28",
    }


def test_tax_directory_repairs_retain_exact_source_and_primary_evidence():
    from pathlib import Path

    fixtures = Path(__file__).parent / "fixtures/ie"
    effects = parse_effects(
        (fixtures / "sample-effects-tax-source-errors.html").read_bytes(), "IE-1997-act-39"
    )
    assert len(effects) == 6
    assert effects[0]["source_id"] == "IE-2006-act-6"
    assert effects[0]["provision"] == "2006, ss. 26(1)(a), 26(2)"
    assert effects[0]["source_correction"].endswith("/2006/act/6/section/26/enacted/en/html")
    assert all(effect["source_id"] == "IE-2024-act-43" for effect in effects[1:5])
    assert all(effect["provision"] == "" for effect in effects[1:5])
    assert effects[5]["source_id"] == "IE-2018-act-30"
    assert effects[5]["note"] == effects[5]["provision"]
    assert effects[5]["source_correction"].endswith("/2018/act/30/section/60/enacted/en/html")
    with pytest.raises(ValueError, match="unresolved affecting"):
        parse_effects(
            (fixtures / "sample-effects-tax-source-errors.html").read_bytes(), "IE-1997-act-40"
        )


def test_unknown_blank_effect_and_empty_table_are_not_silently_discarded():
    with pytest.raises(ValueError, match="no affecting provision"):
        parse_effects(
            b'<h3 id="effects">Effects</h3><table><tr><td>S. 9 repealed</td><td></td></tr></table>',
            "IE-2024-act-1",
        )
    with pytest.raises(ValueError, match="no source rows"):
        parse_effects(b'<h3 id="effects">Effects</h3><table></table>', "IE-2024-act-1")
    with pytest.raises(ValueError, match="unresolved affecting provision"):
        parse_effects(
            b'<h3 id="effects">Effects</h3><table><tr><td>S. 9 inserted</td>'
            b"<td>Section 15 of the External Act</td></tr></table>",
            "IE-2024-act-1",
        )


def test_source_spent_classification_is_separate_from_real_repeal():
    from pathlib import Path

    source = (Path(__file__).parent / "fixtures/ie/sample-effects-spent-1929.html").read_bytes()
    notes = []
    effects = parse_effects(source, "IE-1929-act-10", editorial_notes=notes)
    assert len(effects) == 1
    assert effects[0]["source_id"] == "IE-2016-act-20"
    assert effects[0]["whole_repeal"]
    assert effects[0]["provision"] == "20/2016, ss. 1, 2, schedule"
    assert notes == [{"note": "Spent."}]


def test_inserted_pensions_provision_uses_inserting_act_and_actual_commencement():
    from pathlib import Path

    source = (
        Path(__file__).parent / "fixtures/ie/sample-effects-appropriation-2002.html"
    ).read_bytes()
    effects = parse_effects(source, "IE-2002-act-28")
    assert len(effects) == 2
    assert {effect["source_id"] for effect in effects} == {"IE-2013-act-20"}
    assert {effect["effective_date"] for effect in effects} == {"2014-03-07"}
    first = effects[0]
    assert first["provision"] == "25/1990, s. 9A"
    assert first["directory_source_id"] == "IE-1990-act-25"
    assert first["directory_commencement"] == "21 December 1990"
    assert "331 of 1990" in first["directory_commencement_source"]
    assert first["source_correction"].endswith("/2013/act/20/section/26/enacted/en/html")
    assert first["commencement_source"].endswith("/2014/si/103/made/en/html")
    assert "publication_date" not in first
    # The verified correction does not silently change another norm's history.
    untouched = parse_effects(source, "IE-2002-act-29")
    assert untouched[0]["source_id"] == "IE-1990-act-25"


def test_spent_note_has_directory_provenance_but_no_invented_source_or_date():
    from pathlib import Path
    from unittest.mock import Mock

    from lxml import html

    from legalize.fetcher.ie.effects import fetch_effects

    source = (Path(__file__).parent / "fixtures/ie/sample-effects-spent-1929.html").read_bytes()
    doc = html.fromstring(source)
    # Isolate the actual editorial row to verify that it cannot trigger metadata lookup.
    row = doc.xpath('//tr[td[normalize-space(.)="Spent."]]')[0]
    directory = b'<h3 id="effects">Effects</h3><table>' + html.tostring(row) + b"</table>"
    client = Mock(_base_url="https://www.irishstatutebook.ie")
    client._get.return_value = directory
    notes = []
    effects = fetch_effects(
        client,
        "IE-1929-act-10",
        b'<a href="/isbc/1929_10.html">Amendments</a>',
        editorial_notes=notes,
    )
    assert effects == []
    assert notes == [
        {"note": "Spent.", "directory_url": "https://www.irishstatutebook.ie/isbc/1929_10.html"}
    ]
    client.get_metadata.assert_not_called()


@pytest.mark.parametrize("note", ["Not affected", "Not Affected", "Not affected."])
def test_unaffected_classification_is_case_insensitive(note):
    source = f'<h3 id="effects">Effects</h3><table><tr><td>{note}</td><td></td></tr></table>'
    assert parse_effects(source.encode(), "IE-1935-act-39") == []


@pytest.mark.parametrize("note", ["Spent under section 9", "Spent; repealed", "Expired"])
def test_other_undated_classifications_are_not_assumed_to_be_editorial(note):
    source = f'<h3 id="effects">Effects</h3><table><tr><td>{note}</td><td></td></tr></table>'
    with pytest.raises(ValueError, match="no affecting provision"):
        parse_effects(source.encode(), "IE-1929-act-10")


def test_spent_rows_with_further_source_data_are_not_discarded_as_editorial():
    source = (
        b'<h3 id="effects">Effects</h3><table><tr><td>Spent.</td>'
        b'<td><a href="/eli/2016/act/20/enacted/en/html">20/2016</a></td></tr></table>'
    )
    notes = []
    effects = parse_effects(source, "IE-1929-act-10", editorial_notes=notes)
    assert effects[0]["source_id"] == "IE-2016-act-20"
    assert notes == []
    with pytest.raises(ValueError, match="no affecting provision"):
        parse_effects(
            b'<h3 id="effects">Effects</h3><table><tr><td>Spent.</td><td></td>'
            b"<td>14 May 1929</td><td></td></tr></table>",
            "IE-1929-act-10",
        )


def test_404_does_not_mean_no_amendments():
    from unittest.mock import Mock

    import requests

    from legalize.fetcher.ie.effects import fetch_effects

    client = Mock(_base_url="https://www.irishstatutebook.ie")
    response = requests.Response()
    response.status_code = 404
    client._get.side_effect = requests.HTTPError("Directory unavailable", response=response)
    with pytest.raises(requests.HTTPError):
        fetch_effects(
            client,
            "IE-2024-act-1",
            b'<html><a href="/isbc/2024_1.html">Amendments</a></html>',
        )


def test_si_directory_follows_the_sources_number_range():
    from pathlib import Path
    from unittest.mock import Mock

    from legalize.fetcher.ie.effects import fetch_effects

    fixtures = Path(__file__).parent / "fixtures/ie"
    client = Mock(_base_url="https://www.irishstatutebook.ie")
    pages = {
        "https://www.irishstatutebook.ie/isbc/si2024.html": (
            fixtures / "sample-effects-si-index-2024.html"
        ).read_bytes(),
        "https://www.irishstatutebook.ie/isbc/si2024_351-400.html": (
            fixtures / "sample-effects-si-range-2024.html"
        ).read_bytes(),
    }
    client._get.side_effect = pages.__getitem__
    effects = fetch_effects(
        client,
        "IE-2024-si-356",
        (fixtures / "sample-effects-source-si-2024-356.html").read_bytes(),
    )
    assert effects == []
    assert client._get.call_count == 2


def _airport_application_relations(*, directory_note=True, re_enactment=True):
    import base64
    import json
    from pathlib import Path
    from unittest.mock import Mock

    from legalize.fetcher.ie.effects import fetch_effects

    fixtures = Path(__file__).parent / "fixtures/ie"
    directory = (fixtures / "sample-effects-animals-1966-airport.html").read_bytes()
    enacted = (fixtures / "sample-effects-animals-1966.xml").read_bytes()
    if not directory_note:
        directory = directory.replace(
            b"See s. 20 (1), Interpretation Act, 1937.", b"Unverified reference."
        )
    if not re_enactment:
        enacted = enacted.replace(
            b"Any document referring to any repealed enactment", b"A document"
        )
    client = Mock(_base_url="https://www.irishstatutebook.ie")
    client._get.side_effect = {
        "https://www.irishstatutebook.ie/eli/1966/act/6/enacted/en/html": b'<a href="/isbc/1966_6.html">Amendments</a>',
        "https://www.irishstatutebook.ie/isbc/1966_6.html": directory,
    }.__getitem__
    client.get_metadata.side_effect = {
        "IE-1947-si-115": (fixtures / "sample-effects-airport-1947.html").read_bytes(),
        "IE-1951-si-60": (fixtures / "sample-effects-airport-1951.html").read_bytes(),
    }.__getitem__
    notes = []
    effects = fetch_effects(client, "IE-1966-act-6", enacted, editorial_notes=notes)
    encoded = base64.b64encode(enacted).decode()
    envelope = json.dumps(
        {
            "legalize_ie": 1,
            "identifier": "IE-1966-act-6",
            "metadata": encoded,
            "versions": [
                {
                    "format": "enacted",
                    "url": "https://www.irishstatutebook.ie/eli/1966/act/6/enacted/en/html",
                    "data": encoded,
                }
            ],
            "effects": effects,
            "editorial_notes": notes,
        }
    ).encode()
    return effects, notes, envelope


def test_inherited_airport_application_is_preserved_without_antedated_reforms():
    import json

    from legalize.fetcher.ie import history

    effects, notes, envelope = _airport_application_relations()
    assert effects == []
    assert [(note["source_id"], note["publication_date"]) for note in notes] == [
        ("IE-1947-si-115", "1947-04-21"),
        ("IE-1951-si-60", "1951-03-06"),
    ]
    for note, number, year in zip(notes, (115, 60), (1947, 1951), strict=True):
        assert note["type"] == "pre_existing_application"
        assert note["reason"]
        assert note["note"] == "Excl. provns. ext. to Customs-free Airport. *"
        assert note["provision"] == f"S.R. & O. No. {number} of {year}"
        assert (
            note["source_url"]
            == f"https://www.irishstatutebook.ie/eli/{year}/si/{number}/made/en/html"
        )
        assert note["directory_url"] == "https://www.irishstatutebook.ie/isbc/1966_6.html"
        assert note["effective_date"] is None
        assert (
            "See s. 20 (1), Interpretation Act, 1937." in note["continuity_basis"]["directory_note"]
        )
        assert note["continuity_basis"]["interpretation_source"].endswith(
            "/1937/act/38/section/20/enacted/en/html"
        )
        assert note["continuity_basis"]["re_enactment_source"].endswith(
            "/1966/act/6/section/9/enacted/en/html"
        )
    norm = history._parse_on(envelope, date(2026, 10, 8))
    assert [(reform.norm_id, reform.date) for reform in norm.reforms] == [
        ("IE-1966-act-6", date(1966, 3, 1))
    ]
    assert json.loads(dict(norm.metadata.extra)["legislation_directory_notes"]) == notes


@pytest.mark.parametrize("missing", ["directory_note", "re_enactment"])
def test_older_effect_without_verified_continuity_still_fails(missing):
    from legalize.fetcher.ie import history

    effects, notes, envelope = _airport_application_relations(**{missing: False})
    assert len(effects) == 2
    assert notes == []
    with pytest.raises(ValueError, match="effect IE-1947-si-115 predates the original publication"):
        history._parse_on(envelope, date(2026, 10, 8))
