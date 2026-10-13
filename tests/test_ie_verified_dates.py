"""Known XML conflicts require source-specific, independently captured date evidence."""

import json
from datetime import date
from pathlib import Path

import pytest
from lxml import etree

from legalize.fetcher.ie.parser import ISBMetadataParser, ISBTextParser

FIXTURES = Path(__file__).parent / "fixtures/ie"
CASES = json.loads((FIXTURES / "verified-enactment-dates.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["identifier"])
def test_verified_conflict_preserves_source_date_and_corroboration(case):
    raw = (FIXTURES / case["file"]).read_bytes()
    metadata = ISBMetadataParser().parse(raw, case["identifier"])
    version = ISBTextParser().parse_text(raw)[0].versions[0]
    assert (
        metadata.publication_date
        == version.publication_date
        == date.fromisoformat(case["expected_date"])
    )
    extra = dict(metadata.extra)
    assert extra["enactment_date_source_value"] == case["raw_date"]
    assert extra["enactment_date_correction_source"] == case["corroboration"]["source_url"]
    root = etree.fromstring(raw)
    root.find("metadata/dateofenactment").text = case["raw_date"][:4] + "0101"
    with pytest.raises(ValueError, match="Conflicting"):
        ISBMetadataParser().parse(etree.tostring(root), case["identifier"])


def test_unknown_act_cannot_borrow_another_acts_date_correction():
    case = CASES[0]
    raw = (FIXTURES / case["file"]).read_bytes().replace(b"Number</i> 5", b"Number</i> 999")
    assert raw != (FIXTURES / case["file"]).read_bytes()
    with pytest.raises(ValueError, match="Conflicting"):
        ISBTextParser().parse_text(raw)
