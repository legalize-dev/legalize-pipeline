"""Verified source provisions correct exact bad directory years without inventing dates."""

import gzip
from hashlib import sha256
import json
from pathlib import Path

from lxml import html
import pytest

from legalize.fetcher.ie.effects import parse_effects

FIXTURES = Path(__file__).parent / "fixtures/ie"
EVIDENCE = json.loads((FIXTURES / "verified-year-evidence.json").read_text())
PROOF_QUOTES = {
    "IE-1996-act-32": ["section 14 of the Health (Amendment) (No. 3) Act, 1996 (No. 32 of 1996)"],
    "IE-1993-act-27": [
        "(11) Rule 1",
        "Part I of the Third Schedule",
        "(13) This section shall come into operation",
    ],
    "IE-2000-act-34": [
        "“Act of 2000” means the Fisheries (Amendment) Act 2000 (No. 34 of 2000).",
        "5. Bye-laws of the type which prohibit the taking",
    ],
    "IE-1989-act-6": ["section 5(2) of that Act", "section 6(2) of that Act"],
}


def source(record):
    raw = gzip.decompress((FIXTURES / record["file"]).read_bytes())
    assert sha256(raw).hexdigest() == record["sha256"]
    return raw


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_verified_source_repairs_preserve_original_claims(record):
    proof = " ".join(html.fromstring(source(record["proof"])).text_content().split())
    assert all(quote in proof for quote in PROOF_QUOTES[record["identifier"]])
    effects = parse_effects(source(record["directory"]), record["identifier"], editorial_notes=[])
    for original in record["relations"]:
        effect = next(
            e
            for e in effects
            if (e["note"], e["provision"]) == (original["note"], original["provision"])
        )
        assert effect["source_id"] == record["amender"]
        assert effect["directory_source_id"] == original["source_id"]
        assert effect["source_correction"] == record["proof"]["url"]
        if record["identifier"] == "IE-2000-act-34":
            assert effect["directory_commencement"] == original["commencement"]
            assert effect["directory_commencement_source"] == original["commencement_source"]
            assert effect["commencement"] == effect["commencement_source"] == ""
            assert effect["effective_date"] is None
        else:
            assert effect["commencement"] == original["commencement"]


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_verified_source_repairs_do_not_apply_to_another_provision(record):
    original = record["relations"][0]
    raw = f'<h2 id="effects">Effects</h2><table><tr><td>{original["note"]}</td><td>{original["provision"]} (unverified)</td></tr></table>'.encode()
    effect = parse_effects(raw, record["identifier"])[0]
    assert effect["source_id"] == original["source_id"]
    assert "source_correction" not in effect
