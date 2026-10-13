"""Real source formatting must not change enactment identity or signature dates."""

from datetime import date
from pathlib import Path

import pytest
from lxml import etree

from legalize.fetcher.ie.parser import ISBMetadataParser, ISBTextParser, _signature_dates

FIXTURES = Path(__file__).parent / "fixtures/ie"


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("IE-1936-si-340", "1936-11-20"),
        ("IE-1945-si-144", "1945-06-16"),
        ("IE-1947-si-417", "1947-12-19"),
        ("IE-1948-si-45", "1948-01-30"),
        ("IE-1982-si-158", "1982-05-27"),
        ("IE-1987-si-223", "1987-09-02"),
        ("IE-1997-si-314", "1997-07-15"),
        ("IE-2000-si-217", "2000-01-11"),
        ("IE-2001-si-63", "2001-03-02"),
        ("IE-2003-si-505", "2003-10-29"),
        ("IE-2005-si-48", "2005-01-25"),
        ("IE-2005-si-766", "2005-12-02"),
    ],
)
def test_signature_variants_agree_between_metadata_and_body(identifier, expected):
    raw = (FIXTURES / f"sample-{identifier.lower()}-signature.html").read_bytes()
    metadata = ISBMetadataParser().parse(raw, identifier)
    version = ISBTextParser().parse_text(raw)[0].versions[0]
    assert metadata.publication_date == version.publication_date == date.fromisoformat(expected)
    if identifier == "IE-1982-si-158":
        assert dict(metadata.extra)["signature_dates"] == '["1982-05-10", "1982-05-27"]'
    if identifier == "IE-2000-si-217":
        assert dict(metadata.extra)["signature_dates"] == '["1999-10-27", "2000-01-11"]'


def test_signature_with_blank_form_underscores_is_still_a_signature():
    raw = (FIXTURES / "sample-ie-2005-si-229-signature.html").read_bytes()
    assert ISBMetadataParser().parse(raw, "IE-2005-si-229").publication_date == date(2005, 4, 29)


def test_spelled_commencement_and_unfilled_signature_forms_are_not_signatures():
    text = (
        "This Order comes into operation on the first day of January, One Thousand Nine Hundred and Forty-eight. "
        "Dated the day of 19 Signed ........"
    )
    assert _signature_dates(text) == []
    assert _signature_dates(
        "Dated the thirty-first day of December, One Thousand Nine Hundred and Ninety-nine."
    ) == [date(1999, 12, 31)]


@pytest.mark.parametrize(
    ("identifier", "wrong_number", "wrong_year"),
    [
        ("IE-1951-act-8", "6", "1951"),
        ("IE-1936-act-14", "15", "1936"),
        ("IE-2004-act-7", "7", "2003"),
        ("IE-1955-act-25", "26", "1955"),
        ("IE-1948-act-13", "48", "1948"),
    ],
)
def test_identity_uses_printed_actnumber_with_original_xml_fields_preserved(
    identifier, wrong_number, wrong_year
):
    raw = (FIXTURES / f"sample-{identifier.lower()}-identity.xml").read_bytes()
    metadata = ISBMetadataParser().parse(raw, identifier)
    extra = dict(metadata.extra)
    assert extra["official_number"] == identifier.split("-")[-1]
    assert extra["year"] == identifier.split("-")[1]
    assert extra["identity_source_number"] == wrong_number
    assert extra["identity_source_year"] == wrong_year
    assert extra["identity_basis"] == "isb_frontmatter_actnumber"
    with pytest.raises(ValueError, match="different Act"):
        ISBMetadataParser().parse(raw, f"IE-{wrong_year}-act-{wrong_number}")
    root = etree.fromstring(raw)
    root.remove(root.find("frontmatter"))
    with pytest.raises(ValueError, match="different Act"):
        ISBMetadataParser().parse(etree.tostring(root), identifier)
