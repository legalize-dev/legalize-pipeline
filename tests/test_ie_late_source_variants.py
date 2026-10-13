"""Later catalogue entries retain source dates, references and editorial findings."""

import json
from datetime import date
from hashlib import sha256
from pathlib import Path

import pytest

from legalize.fetcher.ie.effects import parse_effects
from legalize.fetcher.ie.parser import ISBMetadataParser, ISBTextParser, _signature_dates

FIXTURES = Path(__file__).parent / "fixtures/ie"


@pytest.mark.parametrize(
    "evidence",
    json.loads((FIXTURES / "additional-signature-evidence.json").read_text()),
    ids=lambda evidence: evidence["identifier"],
)
def test_verified_signature_blocks_keep_metadata_and_body_dates_aligned(evidence):
    raw = (FIXTURES / evidence["file"]).read_bytes()
    assert sha256(raw).hexdigest() == evidence["fixture_sha256"]
    if evidence["expected_date"] is None:
        with pytest.raises(ValueError, match="lacks its title or enactment date"):
            ISBMetadataParser().parse(raw, evidence["identifier"])
        with pytest.raises(ValueError, match="date"):
            ISBTextParser().parse_text(raw)
        return
    metadata = ISBMetadataParser().parse(raw, evidence["identifier"])
    version = ISBTextParser().parse_text(raw)[0].versions[0]
    expected = date.fromisoformat(evidence["expected_date"])
    assert metadata.publication_date == version.publication_date == expected
    extra = dict(metadata.extra)
    signatures = evidence["signature_dates"]
    if signatures:
        assert extra["made_date"] == signatures[-1]
        if len(signatures) > 1:
            assert json.loads(extra["signature_dates"]) == signatures
        assert extra["publication_date_basis"] == "final_signature"
    else:
        assert extra["signature_date_unknown"] == "true"
        assert extra["publication_date_basis"] == "gazette_notice"
        assert extra["publication_date_source"] == evidence["corroboration"]["url"]
        assert "made_date" not in extra
    if "/ga/" in evidence["source_url"]:
        assert extra["language"] == "ga"


@pytest.mark.parametrize(
    "text",
    [
        "a Deed dated the 17th day of February 1965",
        "an Order made 23 January 2003",
        "The commencement date is 17/02/2005.",
        "The certificate was given 23 January 2003.",
    ],
)
def test_referenced_dates_are_not_signature_blocks(text):
    assert _signature_dates(text) == []


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("IE-1988-si-372", "1988-12-12"),
        ("IE-1993-si-212", "1993-07-19"),
        ("IE-2005-si-642", "2005-10-12"),
        ("IE-1982-si-49", "1982-03-12"),
    ],
)
def test_signature_prefix_and_abbreviated_month_punctuation(identifier, expected):
    _, year, _, number = identifier.split("-")
    raw = (FIXTURES / f"sample-signature-{year}-{number}.html").read_bytes()
    metadata = ISBMetadataParser().parse(raw, identifier)
    version = ISBTextParser().parse_text(raw)[0].versions[0]
    assert metadata.publication_date == version.publication_date == date.fromisoformat(expected)
    if identifier == "IE-2005-si-642":
        assert json.loads(dict(metadata.extra)["signature_dates"]) == [
            "2005-10-06",
            "2005-10-12",
        ]


@pytest.mark.parametrize("month", ["Meitheamh", "Mheitheamh"])
def test_irish_june_signature_keeps_both_inflected_month_forms(month):
    assert _signature_dates(
        f"ARNA THABHAIRT faoi mo Shéala Oifigiúil an 25 lá seo de {month} 1987."
    ) == [date(1987, 6, 25)]


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("IE-1974-si-94", "1974-04-01"),
        ("IE-1997-si-375", "1997-09-10"),
        ("IE-1998-si-549", "1998-12-30"),
        ("IE-1998-si-553", "1998-12-30"),
        ("IE-2000-si-262", "2000-07-31"),
        ("IE-2000-si-433", "2000-12-15"),
        ("IE-2001-si-501", "2001-11-06"),
        ("IE-2003-si-249", "2003-06-23"),
        ("IE-2004-si-379", "2004-06-14"),
        ("IE-2017-act-14", "2017-06-28"),
    ],
)
def test_actual_signature_and_identity_variants(identifier, expected):
    ext = "html" if "-si-" in identifier else "xml"
    raw = (FIXTURES / f"sample-{identifier.lower()}-tertiary.{ext}").read_bytes()
    metadata = ISBMetadataParser().parse(raw, identifier)
    version = ISBTextParser().parse_text(raw)[0].versions[0]
    assert metadata.publication_date == version.publication_date == date.fromisoformat(expected)
    assert version.paragraphs
    if identifier == "IE-2017-act-14":
        assert dict(metadata.extra)["identity_source_printed_numbers"] == "12, 14"
        assert dict(metadata.extra)["identity_correction_source"].endswith(
            "/2017/act/14/enacted/en/html"
        )
        with pytest.raises(ValueError, match="different Act"):
            ISBMetadataParser().parse(raw, "IE-2017-act-12")
    if identifier == "IE-2000-si-433":
        text = "\n".join(p.text for p in version.paragraphs)
        assert text.count("[^1]") == text.count("[^2]") == 2
        assert "All Type Technical exams are charged separately." in text


def test_reversed_signature_requires_both_halves_and_ignores_approval_dates():
    assert _signature_dates("Social Welfare this 1st day of April, 1974.") == []
    assert (
        _signature_dates(
            "Dáil Éireann on 21st March, 1974, and Seanad Éireann on 20th March, 1974."
        )
        == []
    )


@pytest.mark.parametrize(
    "identifier",
    [
        "IE-1978-act-24",
        "IE-1982-act-25",
        "IE-1946-act-15",
        "IE-1986-act-9",
        "IE-1952-act-25",
        "IE-1992-act-23",
        "IE-1967-act-21",
        "IE-1984-act-22",
        "IE-1990-act-33",
        "IE-1979-act-27",
        "IE-1988-act-25",
        "IE-1990-act-29",
        "IE-1990-act-20",
        "IE-1986-act-13",
        "IE-1988-act-28",
        "IE-1992-act-18",
    ],
)
def test_directory_rows_remain_resolvable_and_preserve_nonlegislative_notes(identifier):
    raw = (FIXTURES / f"sample-effects-tertiary-{identifier.removeprefix('IE-')}.html").read_bytes()
    notes = []
    effects = parse_effects(raw, identifier, editorial_notes=notes)
    assert effects or notes or identifier == "IE-1990-act-29"
    if identifier in {"IE-1978-act-24", "IE-1982-act-25"}:
        assert any(", expired 31 December 1992." in e["provision"] for e in effects)
    if identifier == "IE-1986-act-9":
        assert any(
            e["source_id"] == "IE-2019-act-8" and "29(2A) inserted" in e["note"] for e in effects
        )
    if identifier in {"IE-1952-act-25", "IE-1992-act-23", "IE-1990-act-33"}:
        assert any(n.get("kind") == "judicial_finding" and n.get("footnotes") for n in notes)
    if identifier == "IE-1984-act-22":
        assert {n["kind"] for n in notes} == {"parliamentary_resolution"}
        assert any("Dáil Éireann" in n["provision"] for n in notes)
        assert any("Seanad Éireann" in n["provision"] for n in notes)
    if identifier == "IE-1967-act-21":
        assert any(
            e["source_id"] == "IE-2023-act-8"
            and e.get("source_correction", "").endswith("/section/32/enacted/en/html")
            for e in effects
        )
    if identifier == "IE-1990-act-20":
        assert any(
            e["source_id"] == "IE-2005-act-11" and e["note"] == "S. 3(5A) inserted" for e in effects
        )
    if identifier == "IE-1988-act-28":
        assert any(
            e["source_id"] == "IE-2014-act-21"
            and "Housing (Miscellaneous Provisions) Act 2014" in e["provision"]
            for e in effects
        )


@pytest.mark.parametrize(
    "wording", ["as inserted by", "as ins. by", "inserted by", "as amended by"]
)
def test_written_amender_identity_overrides_links_copied_from_host_act(wording):
    raw = f'<h3 id="effects">Effects</h3><table><tr><td>Application extended</td><td><a href="/eli/1992/act/12">12/1992</a>, s. 14C {wording} 2/2017, s. <a href="/eli/1992/act/12/section/36">36</a></td></tr></table>'.encode()
    effects = parse_effects(raw, "IE-1995-act-32")
    assert [e["source_id"] for e in effects] == ["IE-2017-act-2"]
    assert "12/1992" in effects[0]["provision"]


@pytest.mark.parametrize(
    "provision", ["25/1990, s. 9A", "25/1990, s. 9A (see", "Pensions Act 1990 (25/1990), s. 9A"]
)
def test_pensions_rename_applies_to_references_in_other_enactments(provision):
    raw = f'<h3 id="effects">Effects</h3><table><tr><td>References construed</td><td>{provision}</td></tr></table>'.encode()
    effects = parse_effects(raw, "IE-1994-act-13")
    assert effects[0]["source_id"] == "IE-2013-act-20"
    assert effects[0]["directory_source_id"] == "IE-1990-act-25"
    assert effects[0]["effective_date"] == "2014-03-07"
