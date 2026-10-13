"""Verified earlier rules remain explicit provenance, never antedated reforms."""

import base64
from dataclasses import replace
from datetime import date
import gzip
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import Mock

from lxml import html
import pytest

from legalize.fetcher.ie.effects import fetch_effects
from legalize.fetcher.ie.history import _parse_on
from legalize.fetcher.ie.parser import ISBMetadataParser

FIXTURES = Path(__file__).parent / "fixtures/ie"
EVIDENCE = json.loads((FIXTURES / "preexisting-rules-evidence.json").read_text())


def source(record):
    raw = gzip.decompress((FIXTURES / record["file"]).read_bytes())
    assert sha256(raw).hexdigest() == record["sha256"]
    return raw


def relations(record, *, changed=None, sink=True):
    doc = html.fromstring(source(record["directory"]))
    table = html.Element("table")
    expected = {e["provision"] for e in record["relations"]}
    previous_note = ""
    for row in doc.xpath('//*[@id="effects"]/following-sibling::table[1]//tr'):
        cells = row.xpath("./td")
        if cells and (note := " ".join(cells[0].text_content().split())):
            previous_note = note
        if len(cells) in (2, 4) and " ".join(cells[1].text_content().split()) in expected:
            if not " ".join(cells[0].text_content().split()):
                cells[0].text = previous_note
            if changed:
                cell = cells[0 if changed == "note" else 1]
                cell.text = " ".join(cell.text_content().split()) + " (unverified)"
                for child in list(cell):
                    cell.remove(child)
            table.append(row)
    assert len(table) == len(expected)
    directory = b'<h2 id="effects">Effects</h2>' + html.tostring(table)
    client = Mock(_base_url="https://www.irishstatutebook.ie")
    client._get.side_effect = lambda url: (
        directory
        if url == record["directory"]["url"]
        else f'<a href="{record["directory"]["url"]}">History</a>'.encode()
    )
    client.get_metadata.side_effect = lambda identifier: source(record["dependencies"][identifier])
    notes = [] if sink else None
    enacted = source(record["enacted"])
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
def test_verified_earlier_rules_preserve_all_dates_claims_and_provenance(record):
    effects, notes, envelope = relations(record)
    assert effects == []
    assert len(notes) == len(record["relations"])
    for note, expected in zip(notes, record["relations"], strict=True):
        assert note["kind"] == "pre_existing_rule"
        assert note["reason"] and note["basis_source"].startswith(
            "https://www.irishstatutebook.ie/"
        )
        for key, value in expected.items():
            assert note[key] == value
    norm = _parse_on(envelope, date(2026, 10, 13))
    assert [r.norm_id for r in norm.reforms] == [record["identifier"]]
    assert json.loads(dict(norm.metadata.extra)["legislation_directory_notes"]) == notes


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
@pytest.mark.parametrize("changed", ["note", "provision"])
def test_unverified_claims_are_not_silently_filtered(record, changed):
    effects, notes, envelope = relations(record, changed=changed)
    assert len(effects) == len(record["relations"])
    assert notes == []
    with pytest.raises(ValueError, match="predates the original publication"):
        _parse_on(envelope, date(2026, 10, 13))


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_preexisting_rules_require_preserved_provenance(record):
    with pytest.raises(ValueError, match="requires a provenance sink"):
        relations(record, sink=False)


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_classification_does_not_remove_a_later_effect(monkeypatch, record):
    original = ISBMetadataParser.parse
    earlier = date(min(int(r["publication_date"][:4]) for r in record["relations"]) - 1, 1, 1)

    def parse(self, data, norm_id):
        result = original(self, data, norm_id)
        return (
            replace(result, publication_date=earlier) if norm_id == record["identifier"] else result
        )

    monkeypatch.setattr(ISBMetadataParser, "parse", parse)
    effects, notes, _ = relations(record)
    assert len(effects) == len(record["relations"])
    assert notes == []
