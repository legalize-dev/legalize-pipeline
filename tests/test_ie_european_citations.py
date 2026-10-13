"""European amendments inside an instrument title do not change its Irish identity."""

import gzip
from hashlib import sha256
import json
from pathlib import Path

import pytest

from legalize.fetcher.ie.effects import parse_effects

FIXTURES = Path(__file__).parent / "fixtures/ie"


def test_original_companies_directory_keeps_the_irish_audit_instrument():
    record = json.loads((FIXTURES / "companies-european-citation-evidence.json").read_text())
    raw = gzip.decompress((FIXTURES / record["file"]).read_bytes())
    assert sha256(raw).hexdigest() == record["sha256"]
    effects = parse_effects(raw, "IE-2014-act-38", editorial_notes=[])
    matches = [
        effect for effect in effects if effect["note"] == "S. 905(2)(n) applied with modifications"
    ]
    assert len(matches) == 1
    assert matches[0]["source_id"] == "IE-2016-si-312"
    assert matches[0]["provision"].startswith("S.I. No. 312/2016 - European Union")
    assert "as amended by Directive 2014/56/EU" in matches[0]["provision"]
    assert not {"IE-2014-act-56", "IE-2014-act-537"} & {e["source_id"] for e in effects}


@pytest.mark.parametrize(
    "european",
    [
        "Directive 2014/56/EU",
        "Regulation (EU) No 537/2014",
        "Regulation (EC) No 1606/2002",
        "Regulation (EEC) No 2137/1985",
    ],
)
@pytest.mark.parametrize("linked", [False, True])
def test_european_title_amendment_preserves_linked_and_unlinked_irish_instruments(european, linked):
    label = "S.I. No. 312/2016"
    citation = f'<a href="/eli/2016/si/312/made/en/html">{label}</a>' if linked else label
    provision = f"{citation} - European Union (Statutory Audits, as amended by {european}) Regulations 2016, reg. 3"
    raw = f'<h2 id="effects">Effects</h2><table><tr><td>Applied</td><td>{provision}</td></tr></table>'.encode()
    effects = parse_effects(raw, "IE-2014-act-38")
    assert [effect["source_id"] for effect in effects] == ["IE-2016-si-312"]


def test_an_actual_later_irish_amender_is_still_selected_after_a_european_title_reference():
    provision = "S.I. No. 312/2016 (Directive 2006/43/EC, as amended by Directive 2014/56/EU), as amended by S.I. No. 123/2020, reg. 3"
    raw = f'<h2 id="effects">Effects</h2><table><tr><td>Amended</td><td>{provision}</td></tr></table>'.encode()
    effects = parse_effects(raw, "IE-2014-act-38")
    assert [effect["source_id"] for effect in effects] == ["IE-2020-si-123"]
