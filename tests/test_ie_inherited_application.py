"""Earlier application rules remain provenance when a verified re-enactment carries them forward."""

import base64
from copy import deepcopy
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import Mock

from lxml import html
import pytest

from legalize.fetcher.ie.effects import fetch_effects
from legalize.fetcher.ie.history import _parse_on

FIXTURES = Path(__file__).parent / "fixtures/ie"
EVIDENCE = json.loads((FIXTURES / "inherited-application-evidence.json").read_text())


def source(record):
    raw = (FIXTURES / record["file"]).read_bytes()
    assert sha256(raw).hexdigest() == record["sha256"]
    return raw


def inherited(record, missing=None, sink=True):
    doc = html.fromstring(source(record["directory"]))
    table = html.Element("table")
    expected = {e["provision"].strip() for e in record["predating"]}
    for row in doc.xpath('//*[@id="effects"]/following-sibling::table[1]//tr'):
        cells = row.xpath("./td")
        if len(cells) == 2 and " ".join(cells[1].text_content().split()) in expected:
            table.append(deepcopy(row))
    assert len(table) == len(record["predating"])
    directory = b'<h3 id="effects">Effects</h3>' + html.tostring(table)
    for node in doc.xpath('//*[@id="effects"]/following-sibling::*[not(self::table)]'):
        if missing == "relation_note" and "Interpretation" in node.text_content():
            directory += b"<p>*Unrelated provision: See Interpretation Act, 1937, s. 20 (1).</p>"
        else:
            directory += html.tostring(node)
    enacted = source(record["enacted"])
    if missing == "directory_note":
        directory = directory.replace(b"Interpretation Act", b"Unverified reference")
    if missing == "re_enactment":
        enacted = enacted.replace(b"corresponding", b"unverified")
    client = Mock(_base_url="https://www.irishstatutebook.ie")
    client._get.side_effect = lambda url: (
        directory
        if url == record["directory"]["url"]
        else f'<a href="{record["directory"]["url"]}">History</a>'.encode()
    )
    client.get_metadata.side_effect = lambda identifier: source(record["dependencies"][identifier])
    notes = [] if sink else None
    effects = fetch_effects(client, record["identifier"], enacted, editorial_notes=notes)
    encoded = base64.b64encode(enacted).decode()
    envelope = json.dumps(
        {
            "legalize_ie": 1,
            "identifier": record["identifier"],
            "metadata": encoded,
            "versions": [
                {"format": "enacted", "url": "https://www.irishstatutebook.ie", "data": encoded}
            ],
            "effects": effects,
            "editorial_notes": notes,
        }
    ).encode()
    return effects, notes, envelope


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_verified_continuity_preserves_every_relation_without_antedated_reforms(record):
    effects, notes, envelope = inherited(record)
    assert effects == []
    assert len(notes) == len(record["predating"])
    assert {n["provision"] for n in notes} == {e["provision"] for e in record["predating"]}
    assert all(n["type"] == "pre_existing_application" for n in notes)
    assert all("Interpretation Act, 1937" in n["continuity_basis"]["directory_note"] for n in notes)
    norm = _parse_on(envelope, date(2026, 10, 13))
    assert [r.norm_id for r in norm.reforms] == [record["identifier"]]
    assert json.loads(dict(norm.metadata.extra)["legislation_directory_notes"]) == notes


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
@pytest.mark.parametrize("missing", ["directory_note", "re_enactment", "relation_note"])
def test_unverified_earlier_application_is_listed_undated(record, missing):
    effects, notes, envelope = inherited(record, missing)
    assert len(effects) == len(record["predating"])
    assert notes == []
    norm = _parse_on(envelope, date(2026, 10, 13))
    undated = {u["source_id"] for u in json.loads(dict(norm.metadata.extra)["undated_amendments"])}
    assert {e["source_id"] for e in effects} <= undated
    assert not undated & {r.norm_id for r in norm.reforms}


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_inherited_application_cannot_discard_provenance(record):
    with pytest.raises(ValueError, match="requires a provenance sink"):
        inherited(record, sink=False)
