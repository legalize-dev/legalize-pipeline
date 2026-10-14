"""Misfiled claims and earlier hosts remain provenance, never fictitious reforms."""

import base64
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
EVIDENCE = json.loads((FIXTURES / "context-citations-evidence.json").read_text())


def source(record):
    raw = gzip.decompress((FIXTURES / record["file"]).read_bytes())
    assert sha256(raw).hexdigest() == record["sha256"]
    return raw


def relations(record, *, changed=None, sink=True):
    expected = [
        record["relation"],
        *([record["later_relation"]] if "later_relation" in record else []),
    ]
    doc = html.fromstring(source(record["directory"]))
    table = html.Element("table")
    previous_note = ""
    for row in doc.xpath('//*[@id="effects"]/following-sibling::table[1]//tr'):
        cells = row.xpath("./td")
        if cells and (note := " ".join(cells[0].text_content().split())):
            previous_note = note
        if len(cells) in (2, 4) and " ".join(cells[1].text_content().split()) in {
            e["provision"] for e in expected
        }:
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
    client.get_metadata.side_effect = lambda identifier: source(
        record["source"]
        if identifier == record["relation"]["source_id"]
        else record["later_metadata"]
    )
    notes = [] if sink else None
    enacted = source(record["enacted"])
    effects = fetch_effects(client, record["identifier"], enacted, editorial_notes=notes)
    encoded = base64.b64encode(enacted).decode()
    envelope = json.dumps(
        {
            "legalize_ie": 1,
            "identifier": record["identifier"],
            "metadata": encoded,
            "versions": [{"format": "enacted", "url": record["enacted"]["url"], "data": encoded}],
            "effects": effects,
            "editorial_notes": notes,
        }
    ).encode()
    return effects, notes, envelope


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_verified_directory_context_preserves_the_original_claim_and_actual_history(record):
    effects, notes, envelope = relations(record)
    assert len(notes) == 1
    assert notes[0]["kind"] == record["kind"]
    assert notes[0]["reason"]
    assert notes[0]["basis_source"] == record["proof"]["url"]
    for key, value in record["relation"].items():
        assert notes[0][key] == value
    assert effects == ([record["later_relation"]] if "later_relation" in record else [])
    norm = _parse_on(envelope, date(2026, 10, 13))
    assert {reform.norm_id for reform in norm.reforms} == {
        record["identifier"],
        *(effect["source_id"] for effect in effects),
    }
    assert json.loads(dict(norm.metadata.extra)["legislation_directory_notes"]) == notes


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
@pytest.mark.parametrize("changed", ["note", "provision"])
def test_unverified_directory_claim_still_fails_the_history_date_check(record, changed):
    effects, notes, envelope = relations(record, changed=changed)
    assert notes == []
    assert record["relation"]["source_id"] in {effect["source_id"] for effect in effects}
    with pytest.raises(ValueError, match="predates the original publication"):
        _parse_on(envelope, date(2026, 10, 13))


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_directory_context_cannot_be_discarded_without_provenance(record):
    with pytest.raises(ValueError, match="requires a provenance sink"):
        relations(record, sink=False)


@pytest.mark.parametrize("record", EVIDENCE[:3], ids=lambda r: r["identifier"])
def test_original_instrument_and_target_enactment_confirm_the_different_act(record):
    proof = html.fromstring(source(record["proof"]))
    text = " ".join(proof.xpath('//*[@id="act"]')[0].text_content().split())
    target = ISBMetadataParser().parse(source(record["target"]), record["actual_target"])
    assert target.title == record["target"]["title"]
    year, number = record["actual_target"].split("-")[1::2]
    assert any(f"/{year}/en/act/pub/{int(number):04}/" in href for href in proof.xpath("//a/@href"))
    if record["actual_target"] == "IE-1988-act-29":
        assert '"The Act" means the Local Government (Multi-Storey Buildings) Act, 1988' in text
        assert "4. (1) Form No. 7" in text and "5. A certificate, pursuant to section 4 (1)" in text
    else:
        assert (
            "2. The appropriate limit for the purposes of paragraph (b) of section 26 (1) of the Housing Act, 1966"
            in text
        )


def test_1992_cessation_explicitly_identifies_the_1981_insertion_into_the_1975_host():
    record = EVIDENCE[-1]
    proof = " ".join(html.fromstring(source(record["proof"])).text_content().split())
    assert (
        "(inserted by section 37 (1) of the Finance Act, 1981 ) of paragraph 9 of the Order of 1975"
        in proof
    )
    assert "shall not be charged or levied on or after the 1st day of November, 1992" in proof
