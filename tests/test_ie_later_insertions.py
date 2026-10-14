"""A later inserted provision belongs to its amender, not the host Act's date."""

import gzip
import json
from hashlib import sha256
from pathlib import Path

from lxml import html
import pytest

from legalize.fetcher.ie.effects import parse_effects, source_date

FIXTURES = Path(__file__).parent / "fixtures/ie"
EVIDENCE = json.loads((FIXTURES / "later-insertion-evidence.json").read_text())


def read_source(filename):
    raw = (FIXTURES / filename).read_bytes()
    return gzip.decompress(raw) if filename.endswith(".gz") else raw


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"] + ":" + r["provision"])
def test_later_insertions_retain_citations_and_use_verified_amenders(record):
    for key in ("directory", "proof", "commencement_proof", "schedule_proof"):
        if key not in record:
            continue
        source = record[key]
        raw = read_source(source["file"])
        assert sha256(raw).hexdigest() == source["sha256"]
        if "quote" in source:
            assert source["quote"] in " ".join(html.fromstring(raw).text_content().split())
    raw = read_source(record["directory"]["file"])
    effects = parse_effects(raw, record["identifier"], editorial_notes=[])
    matched = [e for e in effects if e["provision"] == record["provision"]]
    assert len(matched) == 1
    effect = matched[0]
    assert effect["source_id"] == record["amender"]
    assert effect["source_correction"] == record["proof"]["url"]
    assert effect["directory_source_id"] == record["original_id"]
    if record["commencement"]:
        assert effect["commencement"] == record["commencement"]
        assert effect["effective_date"] == source_date(record["commencement"]).isoformat()
        assert effect["commencement_source"] == record["commencement_proof"]["url"]
        if record["identifier"] == "IE-2013-act-18":
            assert effect["directory_commencement"] == "29 September 1961"
        if record["identifier"] == "IE-2003-act-15":
            assert effect["directory_commencement"] == "1 January 2002"


def test_unverified_provisions_are_not_assigned_to_known_amenders():
    raw = b'<h2 id="effects">Effects</h2><table><tr><td>Applied</td><td>27/1988, s. 44</td></tr></table>'
    effect = parse_effects(raw, "IE-1997-act-39")[0]
    assert effect["source_id"] == "IE-1988-act-27"
    assert "source_correction" not in effect


@pytest.mark.parametrize(
    ("identifier", "file", "citation"),
    [
        ("IE-1958-act-5", "sample-effects-spent-1958-5.html", "20/1956"),
        ("IE-1978-act-24", "sample-effects-tertiary-1978-act-24.html", "30/1954"),
        ("IE-1982-act-25", "sample-effects-tertiary-1982-act-25.html", "30/1954"),
        ("IE-1990-act-35", "sample-effects-spent-1990-35.html", "30/1954"),
    ],
)
def test_spent_classification_keeps_outgoing_citations_out_of_reform_history(
    identifier, file, citation
):
    raw = (FIXTURES / file).read_bytes()
    notes = []
    assert parse_effects(raw, identifier, editorial_notes=notes) == []
    assert len(notes) == 1
    assert notes[0]["kind"] == "directory_classification"
    assert notes[0]["note"] == "Spent"
    assert citation in notes[0]["provision"]
    assert "expired" in notes[0]["provision"]
    with pytest.raises(ValueError, match="requires a provenance sink"):
        parse_effects(raw, identifier)


def test_spent_continuations_stop_before_a_separate_dated_effect():
    raw = b'<h2 id="effects">Effects</h2><table><tr><td>Spent</td><td>Amended</td></tr><tr><td></td><td>20/1956</td></tr><tr><td>Repealed</td><td>1/2000</td></tr></table>'
    notes = []
    effects = parse_effects(raw, "IE-1958-act-5", editorial_notes=notes)
    assert len(effects) == 1
    assert effects[0]["source_id"] == "IE-2000-act-1"
    assert effects[0]["whole_repeal"]
    assert notes[0]["provision"] == "Amended 20/1956"
