"""Earlier rules for a collectively cited family are retained as context."""

import gzip
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import Mock

from lxml import html
import pytest

from legalize.fetcher.ie.effects import fetch_effects

FIXTURES = Path(__file__).parent / "fixtures/ie"
EVIDENCE = json.loads((FIXTURES / "collective-application-evidence.json").read_text())


def source(record):
    raw = gzip.decompress((FIXTURES / record["file"]).read_bytes())
    assert sha256(raw).hexdigest() == record["sha256"]
    return raw


def relations(record, *, explicit=True, sink=True):
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
            table.append(row)
    assert len(table) == len(expected)
    directory = b'<h2 id="effects">Effects</h2>' + html.tostring(table)
    if not explicit:
        directory = directory.replace(b"collectively cited", b"other referenced").replace(
            b"Collectively cited", b"Other referenced"
        )
    client = Mock(_base_url="https://www.irishstatutebook.ie")
    client._get.side_effect = lambda url: (
        directory
        if url == record["directory"]["url"]
        else f'<a href="{record["directory"]["url"]}">History</a>'.encode()
    )
    client.get_metadata.side_effect = lambda identifier: source(record["dependencies"][identifier])
    notes = [] if sink else None
    effects = fetch_effects(
        client, record["identifier"], source(record["enacted"]), editorial_notes=notes
    )
    return effects, notes


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_earlier_collective_application_preserves_every_source_claim(record):
    effects, notes = relations(record)
    assert effects == []
    assert len(notes) == len(record["relations"])
    for note, expected in zip(notes, record["relations"], strict=True):
        assert note["kind"] == "pre_existing_collective_application"
        assert note["reason"]
        for key in (
            "source_id",
            "provision",
            "publication_date",
            "effective_date",
            "commencement_source",
        ):
            assert note[key] == expected[key]


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_earlier_unqualified_reference_is_not_silently_removed(record):
    effects, notes = relations(record, explicit=False)
    assert len(effects) == len(record["relations"])
    assert notes == []


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_earlier_collective_application_requires_preserved_provenance(record):
    with pytest.raises(ValueError, match="requires a provenance sink"):
        relations(record, sink=False)


def test_later_collective_application_remains_a_dated_effect():
    directory = b'<h2 id="effects">Effects</h2><table><tr><td>Collectively cited Example Acts applied with modifications</td><td>1/2010</td></tr></table>'

    def enacted(year):
        return f'<html><title>Example Act {year}</title><a href="/isbc/2000_1.html">History</a><div id="act">[1st January, {year}]</div></html>'.encode()

    client = Mock(_base_url="https://www.irishstatutebook.ie")
    client._get.return_value = directory
    client.get_metadata.return_value = enacted(2010)
    notes = []
    effects = fetch_effects(client, "IE-2000-act-1", enacted(2000), editorial_notes=notes)
    assert [e["source_id"] for e in effects] == ["IE-2010-act-1"]
    assert notes == []
