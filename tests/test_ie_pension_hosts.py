"""An older host correction must preserve the other instruments in the same row."""

import gzip
from hashlib import sha256
import json
from pathlib import Path

from lxml import html
import pytest

from legalize.fetcher.ie.effects import parse_effects

FIXTURES = Path(__file__).parent / "fixtures/ie"
EVIDENCE = json.loads((FIXTURES / "pension-host-evidence.json").read_text())


def source(record):
    raw = gzip.decompress((FIXTURES / record["file"]).read_bytes())
    assert sha256(raw).hexdigest() == record["sha256"]
    return raw


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_replaced_pension_schedule_uses_its_own_source_and_commencement(record):
    proof = " ".join(html.fromstring(source(record["proof"])).text_content().split())
    assert "substituting the following for Schedule C" in proof
    assert "These Regulations come into operation on 1st August 2008" in proof
    assert "section 44 of the Competition Act 2002" in proof
    assert "section 119 of the Planning and Development Act 2000" in proof
    assert "section 121 of the Planning and Development Act 2000" in proof
    effects = parse_effects(source(record["directory"]), record["identifier"], editorial_notes=[])
    for original in record["relations"]:
        matches = [
            effect
            for effect in effects
            if (effect["note"], effect["provision"]) == (original["note"], original["provision"])
        ]
        corrected = next(effect for effect in matches if effect["source_id"] == "IE-2008-si-295")
        assert corrected["directory_source_id"] == "IE-1993-si-419"
        assert corrected["source_correction"] == record["proof"]["url"]
        assert corrected["directory_commencement"] == original["commencement"]
        assert corrected["directory_commencement_source"] == original["commencement_source"]
        assert corrected["commencement_source"] == record["proof"]["url"]
        assert corrected["effective_date"] == "2008-08-01"
        if record["identifier"] == "IE-2000-act-30":
            assert {effect["source_id"] for effect in matches} == {
                "IE-2008-si-295",
                "IE-2013-si-135",
                "IE-2014-si-268",
                "IE-2019-si-39",
            }
            for effect in matches:
                if effect is not corrected:
                    assert "source_correction" not in effect
                    assert effect["commencement"] == original["commencement"]
                    assert effect["effective_date"] is None
        else:
            assert len(matches) == 1
    for followup in record.get("followups", []):
        text = " ".join(html.fromstring(source(followup)).text_content().split())
        assert "section 119 of the Planning and Development Act 2000" in text
        assert "section 121 of the Planning and Development Act 2000" in text


@pytest.mark.parametrize("prefix", ["S.I. Nos.", "S,I, Nos.", "S.I. nos."])
@pytest.mark.parametrize("separator", [", ", " and "])
def test_plural_instrument_lists_preserve_each_identity_and_stop_at_the_list(prefix, separator):
    provision = f"{prefix} 135 of 2013, 268 of 2014{separator}39 of 2019; reg. 2 of 2020"
    raw = f'<h2 id="effects">Effects</h2><table><tr><td>Applied</td><td>{provision}</td></tr></table>'.encode()
    effects = parse_effects(raw, "IE-2000-act-30")
    assert {effect["source_id"] for effect in effects} == {
        "IE-2013-si-135",
        "IE-2014-si-268",
        "IE-2019-si-39",
    }
    assert all(effect["provision"] == provision for effect in effects)
    assert not any("source_correction" in effect for effect in effects)


def test_criminal_evidence_rule_predates_the_new_offences_as_a_general_rule():
    records = json.loads((FIXTURES / "preexisting-rules-evidence.json").read_text())
    record = next(r for r in records if r["identifier"] == "IE-1997-act-26")
    proof = " ".join(html.fromstring(source(record["proof"])).text_content().split())
    assert "an offence involving violence or the threat of violence to a person" in proof
    effects = parse_effects(source(record["directory"]), record["identifier"], editorial_notes=[])
    original = record["relations"][0]
    effect = next(effect for effect in effects if effect["provision"] == original["provision"])
    assert effect["note"] == original["note"]
