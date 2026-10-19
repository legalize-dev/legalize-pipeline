"""Statutory instrument shapes met while closing the dependency set of the Acts."""

from unittest.mock import Mock

import pytest

from legalize.fetcher.ie.effects import fetch_effects, parse_effects
from legalize.fetcher.ie.parser import ISBTextParser, _signature_dates
from legalize.fetcher.ie.pdf import _month_number

ISB = "https://www.irishstatutebook.ie"


def instrument(body: str, number: int = 1, year: int = 2000) -> bytes:
    return (
        f"<html><head><title>S.I. No. {number}/{year} - Test Regulations {year}</title></head>"
        f'<body><div id="si"><p>S.I. No. {number} of {year}</p><p>TEST REGULATIONS</p>{body}'
        f"<p>GIVEN under my Official Seal, this 1st day of June, {year}.</p></div></body></html>"
    ).encode()


def text_of(raw: bytes) -> str:
    blocks = ISBTextParser().parse_text(raw)
    return "\n".join(p.text for b in blocks for p in b.versions[0].paragraphs)


@pytest.mark.parametrize(
    ("reference", "definition", "body", "note"),
    [
        # ^(1) in the body and in the definition.
        (
            "Directive 98/58/EC<sup>(1)</sup>",
            "<sup>(1)</sup> O.J. No. L 221",
            "Directive 98/58/EC[^1]",
            "O.J. No. L 221",
        ),
        # (^1) definition for a plain superscript.
        (
            "Directive<sup>1</sup>",
            "(<sup>1</sup>) Opinion delivered",
            "Directive[^1]",
            "Opinion delivered",
        ),
        # A bold reference and a wholly bold definition keep their emphasis.
        (
            "county council <b>(1)</b>",
            "<b>(1) Insert name of county council.</b>",
            "county council [^1]",
            "**Insert name of county council.**",
        ),
        # Forms glue the mark to the word and number the notes "1.".
        (
            "this order:1",
            "1. Where the land is a house.",
            "this order:[^1]",
            "Where the land is a house.",
        ),
        (
            "withdrawn (Note 1)",
            "1. Neither this heading appears.",
            "withdrawn (Note 1) [^1]",
            "Neither this heading appears.",
        ),
        ("(*)", "(*) End-to-end routing.", "[^star1]", "End-to-end routing."),
        (
            "person<sup>**</sup>",
            "<sup>**</sup>Personal signature.",
            "person[^star2]",
            "Personal signature.",
        ),
        ("Garda<sup>#</sup>", "<sup>#</sup> To be completed.", "Garda[^hash]", "To be completed."),
        (
            "(name of Surety)<sup>NOTE ONE</sup>",
            "<sup>NOTE ONE</sup>Surety must be a member.",
            "(name of Surety)[^note-one]",
            "Surety must be a member.",
        ),
        # A definition without a mark of its own takes the body's mark.
        (
            "Directive 89/369/EEC<sup>1</sup>",
            "OJ L 186. 30.6.1989, p. 27",
            "Directive 89/369/EEC[^1]",
            "OJ L 186. 30.6.1989, p. 27",
        ),
        (
            "investigation]*",
            "Note: The paragraphs marked * may be omitted.",
            "investigation][^star1]",
            "Note: The paragraphs marked * may be omitted.",
        ),
    ],
)
def test_instrument_footnote_shapes_link_reference_and_definition(
    reference, definition, body, note
):
    raw = instrument(
        f'<p>The Minister, giving effect to {reference} <a name="ret_fn_0"></a> hereby makes.</p>'
        f'<p><a name="fn_0"></a>{definition}</p>'
    )
    text = text_of(raw)
    assert body in text
    label = body.rsplit("[^", 1)[1].split("]")[0]
    assert f"[^{label}]: {note}" in text


def test_reference_marks_compare_without_parentheses_or_emphasis():
    raw = instrument(
        '<p>Directive 98/58/EC<sup>(1)</sup> <a name="ret_fn_0"></a> and the <b>NOTE</b>'
        '<sup><b>2</b></sup> <a name="ret_fn_1"></a></p>'
        '<p><a name="fn_0"></a><sup>1</sup>O.J. No. L 221.</p>'
        '<p><a name="fn_1"></a><small><sup>2</sup> omit note.</small></p>'
    )
    text = text_of(raw)
    assert "98/58/EC[^1]" in text and "**NOTE**[^2]" in text
    assert "[^1]: O.J. No. L 221." in text and "[^2]: omit note." in text


def test_a_definition_printing_another_number_still_fails():
    raw = instrument(
        '<p>Directive 89/106/EEC<sup>10</sup> <a name="ret_fn_0"></a> of 21 December.</p>'
        '<p><a name="fn_0"></a>1. OJ L 229, 30.8.1980, p. 1.</p>'
    )
    with pytest.raises(ValueError, match="disagrees with its anchor"):
        text_of(raw)


def test_an_empty_definition_leaves_the_exponent_unlinked():
    raw = instrument(
        '<p>Emission Limit Values (mg/Nm<sup>3</sup> <a name="ret_fn_0"></a>)</p>'
        '<p><a name="fn_0"></a> </p>'
    )
    text = text_of(raw)
    assert "mg/Nm^3" in text and "[^" not in text


def test_months_accept_three_letter_abbreviations_only():
    assert _month_number("Mar") == _month_number("March") == 3
    for name in ("Ma", "Mary", "Jux"):
        with pytest.raises(ValueError):
            _month_number(name)


def test_irish_signature_without_accents_or_with_an_illegible_mark():
    text = (
        "ARNA THABHAIRT faoi mo Sheala Oifigiuil an 29 lá seo de Meitheamh[illegible], 2001. "
        "ARNA THABHAIRT faoi Shéala Oifigiúil an Aire Airgeadais an 30 lá seo de "
        "Meitheamh[illegible], 2001."
    )
    assert [day.isoformat() for day in _signature_dates(text)] == ["2001-06-29", "2001-06-30"]


def annual_directory(rows: str, number: int = 667, year: int = 2004) -> bytes:
    return (
        f'<table><tr><td rowspan="1"><a name="a{number - 1}_{year}"></a>{number - 1}</td>'
        f"<td>Other Order</td><td>Not affected</td><td></td></tr>{rows}"
        f'<tr><td><a name="a{number + 1}_{year}"></a>{number + 1}</td><td>Next Order</td>'
        "<td>Not affected</td><td></td></tr></table>"
    ).encode()


def directory_client(directory: bytes, sources: dict[str, bytes]):
    client = Mock(_base_url=ISB)
    client._get.side_effect = lambda url: (
        directory if url == f"{ISB}/isbc/si2004.html" else b"<html></html>"
    )
    client.get_metadata.side_effect = sources.__getitem__
    return client


def made(number: int, year: int, day: str) -> bytes:
    return instrument(
        f'<p><a href="{ISB}/isbc/si{year}.html">History</a></p>', number, year
    ).replace(b"1st day of June", day.encode())


def act(number: int, year: int, day: str) -> bytes:
    return (
        f"<html><head><title>Test Act {year}</title></head><body><div id='act'>"
        f"<p>Number {number} of {year}</p><p>TEST ACT {year}</p>"
        f"<p>AN ACT TO TEST. [{day}]</p><p>BE IT ENACTED BY THE OIREACHTAS AS FOLLOWS:</p>"
        "</div></body></html>"
    ).encode()


GROUP = (
    '<tr><td rowspan="{rows}"><a name="a667_2004"></a>667</td><td><i>Order 2004</i></td>'
    "<td>{note}</td><td>{provision}</td></tr>"
)


def test_annual_footnote_names_the_later_instrument_through_which_an_earlier_one_acts():
    directory = annual_directory(
        GROUP.format(
            rows=1,
            note="Revoked",
            provision=f'<a href="{ISB}/1995/en/act/pub/0002/index.html">2/1995</a>, s. 45*',
        )
        + '<tr><td colspan="4"><hr/></td></tr><tr><td colspan="4">*See Adoptive Leave Act 2005 '
        f'(<a href="{ISB}/2005/en/act/pub/0025/index.html">No. 25 of 2005</a>), ss. 21, 22(3)</td></tr>'
    )
    sources = {
        "IE-1995-act-2": act(2, 1995, "15th March, 1995"),
        "IE-2005-act-25": act(25, 2005, "8th July, 2005"),
    }
    notes = []
    effects = fetch_effects(
        directory_client(directory, sources),
        "IE-2004-si-667",
        made(667, 2004, "20th day of October"),
        editorial_notes=notes,
    )
    assert [(e["source_id"], e["directory_source_id"], e["publication_date"]) for e in effects] == [
        ("IE-2005-act-25", "IE-1995-act-2", "2005-07-08")
    ]
    assert effects[0]["whole_repeal"] and not notes
    assert not any(key.startswith("_") for key in effects[0])


@pytest.mark.parametrize(
    "note", ["Continued in force under Health Act 1970 (1/1970)", "Revoked", "Reg. 3 amended"]
)
def test_an_earlier_instrument_without_a_named_later_source_still_fails(note):
    directory = annual_directory(
        GROUP.format(
            rows=1,
            note=note,
            provision=f'<a href="{ISB}/1995/en/act/pub/0002/index.html">2/1995</a>, s. 45*',
        )
        # A footnote naming another earlier instrument cannot date the effect either.
        + '<tr><td colspan="4">*See also '
        f'<a href="{ISB}/1990/en/act/pub/0001/index.html">1/1990</a></td></tr>'
    )
    sources = {
        "IE-1995-act-2": act(2, 1995, "15th March, 1995"),
        "IE-1990-act-1": act(1, 1990, "1st March, 1990"),
    }
    notes = []
    effects = fetch_effects(
        directory_client(directory, sources),
        "IE-2004-si-667",
        made(667, 2004, "20th day of October"),
        editorial_notes=notes,
    )
    # Left dated before the instrument, so history refuses it until it is researched.
    assert [e["source_id"] for e in effects] == ["IE-1995-act-2"]
    assert not notes


def test_annual_directory_omission_is_a_coverage_warning_not_an_empty_history():
    notes = []
    assert (
        parse_effects(
            annual_directory("", number=128, year=1996), "IE-1996-si-128", editorial_notes=notes
        )
        == []
    )
    assert notes[0]["kind"] == "source_coverage_warning"
    with pytest.raises(ValueError, match="no matching norm"):
        parse_effects(b"<table></table>", "IE-1996-si-128", editorial_notes=[])


@pytest.mark.parametrize(
    ("note", "provision", "recorded"),
    [
        ("Spent 31 Dec 2004", "Regs. 1(b), 4 and sch.", True),
        ("Reg. 2 applies", "Regs. 1(b), 3", False),
        ("Expired at end of academic year 2002/2003", "", True),
    ],
)
def test_own_regulations_and_expiry_are_classifications(note, provision, recorded):
    notes = []
    directory = annual_directory(GROUP.format(rows=1, note=note, provision=provision))
    assert parse_effects(directory, "IE-2004-si-667", editorial_notes=notes) == []
    assert [(n["kind"], n["note"]) for n in notes] == (
        [("directory_classification", note)] if recorded else []
    )


def test_dependency_closure_keeps_walking_past_a_failure(monkeypatch, tmp_path):
    from legalize.fetcher.ie import bootstrap
    from legalize.pipeline import NothingPublished

    graph = {"root": ["bad", "good"], "good": ["deeper"], "deeper": ["deepest"], "deepest": []}
    config = Mock()
    config.get_country.return_value = Mock(data_dir=str(tmp_path), max_workers=2)
    fetched = []
    monkeypatch.setattr(
        bootstrap,
        "load_norma_from_json",
        lambda path: Mock(reforms=[Mock(norm_id=f"IE-{key}") for key in graph[path.stem[3:]]]),
    )

    def fetch(_config, _country, key):
        fetched.append(key)
        return None if key == "IE-bad" else object()

    monkeypatch.setattr(bootstrap, "generic_fetch_one", fetch)
    with pytest.raises(NothingPublished, match="unavailable: IE-bad$"):
        bootstrap.fetch_dependencies(config, ["IE-root"])
    assert sorted(fetched) == ["IE-bad", "IE-deeper", "IE-deepest", "IE-good"]


def test_a_starred_note_citing_nothing_is_ignored():
    directory = annual_directory(
        GROUP.format(rows=1, note="Revoked", provision="S.I. No. 609 of 2005, art. 3")
        + '<tr><td colspan="4"><hr/></td></tr>'
        '<tr><td colspan="4">*Grace v Catering Joint Labour Committee [2011] IEHC 277</td></tr>'
    )
    effects = parse_effects(directory, "IE-2004-si-667", editorial_notes=[])
    assert [e["source_id"] for e in effects] == ["IE-2005-si-609"]
    assert "_footnote_ids" not in effects[0]


def test_footnote_after_continuation_rows_written_without_rowspan():
    directory = annual_directory(
        '<tr><td><a name="a667_2004"></a>667</td><td><i>Order 2004</i></td>'
        f'<td>Revoked</td><td><a href="{ISB}/1995/en/act/pub/0002/index.html">2/1995</a>, s. 45*</td></tr>'
        "<tr><td></td><td></td><td>Art. 4 revoked</td><td>S.I. No. 1 of 2005, art. 2</td></tr>"
        '<tr><td colspan="4"><hr/></td></tr><tr><td colspan="4">*See '
        f'<a href="{ISB}/2005/en/act/pub/0025/index.html">No. 25 of 2005</a></td></tr>'
    )
    effects = parse_effects(directory, "IE-2004-si-667", editorial_notes=[])
    assert effects[0]["_footnote_ids"] == ["IE-2005-act-25"]
