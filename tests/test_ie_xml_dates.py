"""Nonstandard compact XML dates require the printed enactment date as evidence."""

from datetime import date
from pathlib import Path

import pytest

from legalize.fetcher.ie.parser import ISBMetadataParser, ISBTextParser

FIXTURES = Path(__file__).parent / "fixtures/ie"


@pytest.mark.parametrize(
    ("identifier", "expected", "raw_date"),
    [
        ("IE-1923-act-24", date(1923, 7, 16), "19231607"),
        ("IE-1949-act-27", date(1949, 11, 17), "19491711"),
        ("IE-1998-act-26", date(1998, 7, 7), "1998077"),
        ("IE-1998-act-44", date(1998, 12, 8), "199801208"),
    ],
)
def test_real_compact_dates_preserve_source_value_and_agree_across_parsers(
    identifier, expected, raw_date
):
    raw = (FIXTURES / f"sample-{identifier.lower()}-enactment.xml").read_bytes()
    metadata = ISBMetadataParser().parse(raw, identifier)
    version = ISBTextParser().parse_text(raw)[0].versions[0]
    assert metadata.publication_date == version.publication_date == expected
    assert dict(metadata.extra)["enactment_date_source_value"] == raw_date
    assert dict(metadata.extra)["publication_date_basis"] == "isb_frontmatter_enactment_date"


def document(raw_date, printed_date):
    return f"""<act><metadata><title>Original Act</title><number>1</number><year>1923</year>
    <dateofenactment>{raw_date}</dateofenactment></metadata>
    <frontmatter><p>{printed_date}</p></frontmatter><body><p>Legal text.</p></body></act>""".encode()


def test_ambiguous_compact_date_is_resolved_by_the_printed_month_name():
    raw = document("19230708", "[7th August, 1923.]")
    assert ISBMetadataParser().parse(raw, "IE-1923-act-1").publication_date == date(1923, 8, 7)
    assert ISBTextParser().parse_text(raw)[0].versions[0].publication_date == date(1923, 8, 7)


@pytest.mark.parametrize(
    ("raw_date", "printed_date"), [("19231607", ""), ("19230708", "[9th August, 1923.]")]
)
def test_unverified_or_conflicting_nonstandard_date_is_rejected(raw_date, printed_date):
    raw = document(raw_date, printed_date)
    with pytest.raises(ValueError):
        ISBMetadataParser().parse(raw, "IE-1923-act-1")
    with pytest.raises(ValueError):
        ISBTextParser().parse_text(raw)
