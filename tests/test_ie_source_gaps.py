"""Verified publication evidence must not become a guessed signature or commencement."""

from datetime import date
from pathlib import Path

import pytest

from legalize.fetcher.ie.effects import parse_effects
from legalize.fetcher.ie.parser import ISBMetadataParser, ISBTextParser

FIXTURES = Path(__file__).parent / "fixtures/ie"


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("IE-2002-si-174", "2002-04-29"),
        ("IE-2003-si-689", "2003-12-17"),
        ("IE-2007-si-139", "2007-03-30"),
        ("IE-2024-act-24", "2024-07-15"),
    ],
)
def test_additional_source_variants_keep_metadata_and_body_aligned(identifier, expected):
    ext = "html" if "-si-" in identifier else "xml"
    raw = (FIXTURES / f"sample-{identifier.lower()}-fourth.{ext}").read_bytes()
    metadata = ISBMetadataParser().parse(raw, identifier)
    version = ISBTextParser().parse_text(raw)[0].versions[0]
    assert metadata.publication_date == version.publication_date == date.fromisoformat(expected)
    if identifier == "IE-2024-act-24":
        assert dict(metadata.extra)["identity_source_printed_numbers"] == "5, 24"
        with pytest.raises(ValueError, match="different Act"):
            ISBMetadataParser().parse(raw, "IE-2024-act-5")


def test_independent_gazette_notice_preserves_unknown_signature_and_original_body():
    raw = (FIXTURES / "sample-ie-2002-si-575-fourth.html").read_bytes()
    metadata = ISBMetadataParser().parse(raw, "IE-2002-si-575")
    version = ISBTextParser().parse_text(raw)[0].versions[0]
    assert metadata.publication_date == version.publication_date == date(2002, 12, 17)
    extra = dict(metadata.extra)
    assert extra["publication_date_basis"] == "gazette_notice"
    assert extra["publication_date_source"].endswith("2002%2012%2017%20IO%20Issue.PDF#page=3")
    assert extra["signature_date_unknown"] == "true"
    assert "made_date" not in extra
    assert any("Official Seal" in p.text and "___" in p.text for p in version.paragraphs)
    with pytest.raises(ValueError, match="different instrument"):
        ISBMetadataParser().parse(raw, "IE-2002-si-576")
    altered = raw.replace(b"575/2002", b"576/2002")
    with pytest.raises(ValueError, match="lacks its title or enactment date"):
        ISBMetadataParser().parse(altered, "IE-2002-si-576")


def test_wicklow_publication_notice_does_not_invent_the_blank_signature_day():
    raw = (FIXTURES / "sample-ie-2002-si-248-gazette.html").read_bytes()
    metadata = ISBMetadataParser().parse(raw, "IE-2002-si-248")
    version = ISBTextParser().parse_text(raw)[0].versions[0]
    assert metadata.publication_date == version.publication_date == date(2002, 8, 9)
    extra = dict(metadata.extra)
    assert extra["signature_date_unknown"] == "true"
    assert extra["publication_date_basis"] == "gazette_notice"
    assert extra["publication_date_source"].endswith("2002%2008%2009%20IO%20Issue.PDF#page=5")
    assert "made_date" not in extra
    assert any("this day of March, 2002" in p.text for p in version.paragraphs)
    with pytest.raises(ValueError, match="different instrument"):
        ISBMetadataParser().parse(raw, "IE-2002-si-249")


@pytest.mark.parametrize("identifier", ["IE-1976-act-23", "IE-2013-act-51"])
def test_verified_empty_directories_preserve_the_coverage_gap(identifier):
    suffix = identifier.removeprefix("IE-").replace("-act-", "-")
    raw = (FIXTURES / f"sample-effects-eleventh-{suffix}.html").read_bytes()
    notes = []
    assert parse_effects(raw, identifier, editorial_notes=notes) == []
    assert len(notes) == 1
    assert notes[0]["kind"] == "source_coverage_warning"
    assert "does not establish" in notes[0]["note"]
    with pytest.raises(ValueError, match="requires a provenance sink"):
        parse_effects(raw, identifier)
    with pytest.raises(ValueError, match="no source rows"):
        parse_effects(raw + b" ", identifier, editorial_notes=[])


@pytest.mark.parametrize(
    ("identifier", "source_id", "count"),
    [("IE-1923-act-15", "IE-1924-act-42", 1), ("IE-2005-act-11", "IE-2015-act-61", 3)],
)
def test_verified_directory_year_transpositions_preserve_the_printed_claim(
    identifier, source_id, count
):
    suffix = identifier.removeprefix("IE-").replace("-act-", "-")
    raw = (FIXTURES / f"sample-effects-eleventh-{suffix}.html").read_bytes()
    effects = parse_effects(raw, identifier)
    corrected = [e for e in effects if e["source_id"] == source_id]
    assert len(corrected) == count
    for effect in corrected:
        assert "/1942" in effect["provision"] or "61/2005" in effect["provision"]
        assert effect["source_correction"].endswith(
            "/1924/act/42/section/2/enacted/en/html"
            if source_id == "IE-1924-act-42"
            else "/2015/act/61/section/1/enacted/en/html"
        )


def test_comma_punctuation_keeps_a_statutory_instrument_out_of_the_act_namespace():
    raw = (FIXTURES / "sample-effects-eleventh-2000-30.html").read_bytes()
    effects = parse_effects(raw, "IE-2000-act-30")
    corrected = [e for e in effects if e.get("directory_source_id") == "IE-1993-si-419"]
    assert len(corrected) == 2
    assert all(e["source_id"] == "IE-2008-si-295" for e in corrected)
    assert all("-si-" in e["source_id"] for e in effects)
    assert all("S,I, No. 419 of 1993" in e["provision"] for e in effects)


def test_parenthetical_commencement_does_not_hide_the_actual_amending_instrument():
    raw = (FIXTURES / "sample-effects-eleventh-2015-16.html").read_bytes()
    effects = parse_effects(raw, "IE-2015-act-16")
    effect = next(e for e in effects if e["provision"].startswith("Redundancy Payments Act 1967"))
    assert effect["source_id"] == "IE-2015-act-22"
    assert effect["effective_date"] == "2015-10-01"
    assert effect["note"] == "S. 44 applied with modifications"


def test_verified_december_typo_does_not_change_the_official_body():
    raw = (FIXTURES / "sample-signature-2019-685.html").read_bytes()
    metadata = ISBMetadataParser().parse(raw, "IE-2019-si-685")
    version = ISBTextParser().parse_text(raw)[0].versions[0]
    assert metadata.publication_date == version.publication_date == date(2020, 1, 3)
    assert dict(metadata.extra)["made_date"] == "2019-12-20"
    assert any("Dated this 20 day of Dcember 2019" in p.text for p in version.paragraphs)


def rows(identifier):
    raw = (FIXTURES / f"sample-effects-fourth-{identifier.removeprefix('IE-')}.html").read_bytes()
    notes = []
    return parse_effects(raw, identifier, editorial_notes=notes), notes


def test_blank_separator_does_not_inherit_previous_repeal_or_discard_pending_repeal():
    effects, _ = rows("IE-2001-act-43")
    pending = [e for e in effects if e["note"] == "S. 8 repealed"]
    assert len(pending) == 1
    assert pending[0]["source_id"] == "IE-2022-act-50"
    assert pending[0]["pending"] and pending[0]["effective_date"] is None


def test_verified_repeal_retains_its_actual_commencement():
    effects, _ = rows("IE-1983-act-35")
    repeal = next(e for e in effects if e["whole_repeal"])
    assert repeal["source_id"] == "IE-2008-act-1"
    assert repeal["effective_date"] == "2008-05-05"
    assert repeal["commencement_source"].endswith("/2008/si/126/made/en/html")


@pytest.mark.parametrize(
    ("identifier", "kind"),
    [
        ("IE-2001-act-48", "directory_classification"),
        ("IE-2003-act-25", "source_coverage_warning"),
        ("IE-2001-act-25", "parliamentary_resolution"),
        ("IE-1996-act-17", "judicial_finding"),
        ("IE-2005-act-27", "directory_context"),
    ],
)
def test_source_qualifications_survive_without_invented_legislative_dates(identifier, kind):
    effects, notes = rows(identifier)
    assert effects and any(n.get("kind") == kind for n in notes)
    assert all("effective_date" not in n and "publication_date" not in n for n in notes)
    if identifier == "IE-2005-act-27":
        assert all(not e["note"].startswith("Registration Boards") for e in effects)


@pytest.mark.parametrize(
    ("identifier", "source"),
    [
        ("IE-1983-act-24", "IE-1990-act-18"),
        ("IE-2003-act-32", "IE-2021-act-49"),
        ("IE-1998-act-16", "IE-2009-act-5"),
    ],
)
def test_verified_missing_or_mistyped_citations_keep_primary_evidence(identifier, source):
    effects, _ = rows(identifier)
    assert any(e["source_id"] == source and e.get("source_correction") for e in effects)


def test_own_section_reference_is_not_a_separate_amending_instrument():
    effects, _ = rows("IE-2005-act-11")
    assert all(e["provision"] != "s 1(4)" for e in effects)
