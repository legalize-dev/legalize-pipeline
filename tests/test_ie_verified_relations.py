"""Earlier instruments a directory cites: each relation verified against its source text.

Evidence: tests/fixtures/ie/verified-relations-2026-10-19.json, with the exact eISB
bytes of each norm, its Legislation Directory page and every cited instrument.
"""

import base64
from datetime import date
import gzip
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import Mock

from lxml import html
import pytest

from legalize.fetcher.ie.effects import _text, fetch_effects
from legalize.fetcher.ie.history import _parse_on

FIXTURES = Path(__file__).parent / "fixtures/ie"
EVIDENCE = json.loads((FIXTURES / "verified-relations-2026-10-19.json").read_text())
ISB = "https://www.irishstatutebook.ie"


def source(entry):
    raw = gzip.decompress((FIXTURES / entry["file"]).read_bytes())
    assert sha256(raw).hexdigest() == entry["sha256"]
    return raw


def directory(record, changed):
    """The verified rows of the real directory page, with its footnotes."""
    doc = html.fromstring(source(record["directory"]))
    wanted = {(r["note"], r["provision"]) for r in record["relations"]}
    rows = []
    for row in doc.xpath("//tr"):
        cells = row.xpath("./td")
        texts = [_text(cell) for cell in cells]
        for note, provision in wanted:
            if note in texts and provision in texts:
                cell = cells[texts.index(provision)]
                markup = html.tostring(cell, encoding="unicode")
                if changed:
                    markup = markup.replace("</td>", " (unverified)</td>")
                dates = "".join(html.tostring(c, encoding="unicode") for c in cells[2:4])
                rows.append(
                    f"<tr><td>{note}</td>{markup}{dates if len(cells) == 4 and texts[0] == note else ''}</tr>"
                )
    assert len(rows) == len(wanted)
    footnotes = "".join(
        html.tostring(node, encoding="unicode")
        for node in doc.xpath('//*[@id="effects"]/following-sibling::*[not(self::table)]')
    )
    return f'<h2 id="effects">Effects</h2><table>{"".join(rows)}</table>{footnotes}'.encode()


def relations(record, *, changed=False):
    page = source(record["page"]) if "page" in record else None
    minimal = directory(record, changed)
    client = Mock(_base_url=ISB)
    client._get.side_effect = lambda url, **_: minimal if "/isbc/" in url else page
    client.get_metadata.side_effect = lambda key: source(record["dependencies"][key])
    enacted = source(record["enacted"])
    notes = []
    effects = fetch_effects(client, record["identifier"], enacted, editorial_notes=notes)
    encoded = base64.b64encode(enacted).decode()
    envelope = json.dumps(
        {
            "legalize_ie": 1,
            "identifier": record["identifier"],
            "metadata": encoded,
            "versions": [{"format": "enacted", "url": ISB, "data": encoded}],
            "effects": effects,
            "editorial_notes": notes,
        }
    ).encode()
    return effects, notes, envelope


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_verified_earlier_relations_keep_their_claims_without_antedated_history(record):
    effects, notes, envelope = relations(record)
    claims = [(r["note"], r["provision"]) for r in record["relations"]]
    if record["kind"] == "later_host":
        assert notes == []
        assert [(e["note"], e["provision"]) for e in effects] == claims
        assert {e["source_id"] for e in effects} == {"IE-2004-act-22"}
        assert {e["directory_source_id"] for e in effects} == {"IE-1930-act-2"}
        assert {e["publication_date"] for e in effects} == {"2004-07-18"}
    else:
        assert effects == []
        assert sorted((n["note"], n["provision"]) for n in notes) == sorted(claims)
        assert {n.get("kind", n.get("type")) for n in notes} == {record["kind"]}
    norm = _parse_on(envelope, date(2026, 10, 19))
    assert all(r.date >= norm.reforms[0].date for r in norm.reforms)


@pytest.mark.parametrize("record", EVIDENCE, ids=lambda r: r["identifier"])
def test_changed_claims_are_listed_undated_not_verified(record):
    effects, notes, envelope = relations(record, changed=True)
    assert notes == [] and effects
    norm = _parse_on(envelope, date(2026, 10, 19))
    undated = {u["source_id"] for u in json.loads(dict(norm.metadata.extra)["undated_amendments"])}
    assert {e["source_id"] for e in effects} <= undated
    assert not undated & {r.norm_id for r in norm.reforms}
