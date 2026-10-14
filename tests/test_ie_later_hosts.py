"""Later host insertions and amendments retain the directory's original claims."""

import gzip
from hashlib import sha256
import json
from pathlib import Path
import re

from lxml import html
import pytest

from legalize.fetcher.ie.effects import parse_effects

FIXTURES = Path(__file__).parent / "fixtures/ie"
EVIDENCE = json.loads((FIXTURES / "later-host-evidence.json").read_text())


def source(record):
    raw = gzip.decompress((FIXTURES / record["file"]).read_bytes())
    assert sha256(raw).hexdigest() == record["sha256"]
    return raw


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_later_host_sources_preserve_claims_without_inventing_commencement(record):
    proof = " ".join(html.fromstring(source(record["proof"])).text_content().split())
    if record["identifier"] == "IE-1993-act-8":
        assert "130. The Act of 1971 is amended by the insertion" in proof
        assert re.search(r"section 11\s*\(2\) of the Comptroller and Auditor General", proof)
        amender = "IE-2022-act-31"
    else:
        assert "(c) by inserting the following Schedule after Schedule A" in proof
        assert "Section 251 of the Act of 2005" in proof
        assert "Section 257 of the Act of 2005" in proof
        amender = "IE-2012-si-448"
    effects = parse_effects(source(record["directory"]), record["identifier"], editorial_notes=[])
    for original in record["relations"]:
        matched = [
            effect
            for effect in effects
            if (effect["note"], effect["provision"]) == (original["note"], original["provision"])
        ]
        assert len(matched) == 1
        effect = matched[0]
        assert effect["source_id"] == amender
        assert effect["directory_source_id"] == original["source_id"]
        assert effect["source_correction"] == record["proof"]["url"]
        for key in ("commencement", "commencement_source", "effective_date", "pending"):
            assert effect[key] == original[key]


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_unverified_host_provisions_remain_unresolved(record):
    original = record["relations"][0]
    raw = f'<h2 id="effects">Effects</h2><table><tr><td>{original["note"]}</td><td>{original["provision"]} (unverified)</td></tr></table>'.encode()
    effect = parse_effects(raw, record["identifier"])[0]
    assert effect["source_id"] == original["source_id"]
    assert "source_correction" not in effect


def test_rent_footnote_keeps_both_continuity_and_the_later_amendment():
    record = EVIDENCE[1]
    proof = " ".join(
        html.fromstring(source(record["continuation_amendment"])).text_content().split()
    )
    assert "7. In the modification of section 250" in proof
    assert "Schedule A to the Principal Regulations" in proof
    effects = parse_effects(source(record["directory"]), record["identifier"], editorial_notes=[])
    matched = [
        effect for effect in effects if effect["provision"] == "S.I. No. 188 of 1998, sch. A"
    ]
    assert {effect["source_id"] for effect in matched} == {"IE-1998-si-188", "IE-2011-si-600"}
    amendment = next(effect for effect in matched if effect["source_id"] == "IE-2011-si-600")
    assert amendment["directory_source_id"] == "IE-1998-si-188"
    assert amendment["source_correction"] == record["continuation_amendment"]["url"]
    assert any(
        "** See also S.I. No. 600 of 2011, reg. 7" in t for t in amendment["directory_footnotes"]
    )
    assert amendment["effective_date"] is None


@pytest.mark.parametrize("missing", ["footnote", "note", "provision"])
def test_rent_amendment_requires_the_exact_linked_footnote(missing):
    record = EVIDENCE[1]
    raw = source(record["directory"])
    changes = {
        "footnote": (b"600 of 2011", b"600 of 2010"),
        "note": (b"S. 250 applied", b"S. 249 applied"),
        "provision": (b"188 of 1998</a>, sch. A", b"188 of 1998</a>, sch. Z"),
    }
    before, after = changes[missing]
    assert before in raw
    effects = parse_effects(raw.replace(before, after), record["identifier"], editorial_notes=[])
    assert not any(effect["source_id"] == "IE-2011-si-600" for effect in effects)


def test_rent_continuity_is_supported_by_the_original_re_enactment():
    record = next(
        r
        for r in json.loads((FIXTURES / "preexisting-rules-evidence.json").read_text())
        if r["identifier"] == "IE-2005-act-26"
    )
    enacted = html.fromstring(source(record["enacted"]))
    inspector = " ".join(enacted.xpath('//*[@id="SEC250"]')[0].text_content().split())
    continuity = " ".join(enacted.xpath('//*[@id="SEC361"]')[0].text_content().split())
    instruments = " ".join(enacted.xpath('//*[@id="SEC362"]')[0].text_content().split())
    original = " ".join(html.fromstring(source(record["proof"])).text_content().split())
    assert "[1993 s212(1)" in inspector
    assert "corresponding provision of this Act" in continuity
    assert "shall continue in force as if made or issued under this Act" in instruments
    assert "Section 212 212. (1)" in original
