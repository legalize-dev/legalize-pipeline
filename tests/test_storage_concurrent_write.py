"""The destination file must never hold half a document.

Portugal has 128 identifier pairs — two portarias with the same number, a
retificação reachable twice — and eight reparse workers opened the same
``{identifier}.json`` at once. Both truncated it, both wrote from their own offset,
and what landed was one document with the tail of another stuck to it. Every later
reader skipped those files, so 128 laws left the corpus without a word: the survival
check counted them as "could not read", not as "lost".

The race itself is timing-dependent and not worth pinning to a flaky test. What is
worth pinning is the contract that removes it: serialise somewhere private, and only
then rename into place, so the destination goes from one whole document to another.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date

import pytest

from legalize import storage
from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    ParsedNorm,
    Rank,
    Version,
)
from legalize.storage import (
    overwritten_identifiers,
    reset_write_tracking,
    save_structured_json,
)

IDENTIFIER = "DRE-PORT-1-2010"


def _norm(blocks: int) -> ParsedNorm:
    metadata = NormMetadata(
        title="Portaria n.º 1/2010",
        short_title="Portaria 1/2010",
        identifier=IDENTIFIER,
        country="pt",
        rank=Rank("portaria"),
        publication_date=date(2010, 1, 7),
        status=NormStatus.IN_FORCE,
        department="Ministério das Finanças",
        source="https://diariodarepublica.pt/x",
    )
    version = Version(
        norm_id="pub:portaria:1-2010",
        publication_date=date(2010, 1, 7),
        effective_date=date(2010, 1, 7),
        paragraphs=(Paragraph(css_class="parrafo", text="Texto."),),
    )
    return ParsedNorm(
        metadata=metadata,
        blocks=tuple(
            Block(id=f"a{i}", block_type="artigo", title=f"Artigo {i}", versions=(version,))
            for i in range(blocks)
        ),
        reforms=(),
    )


def test_a_write_that_dies_halfway_leaves_the_previous_file_whole(tmp_path, monkeypatch):
    reset_write_tracking()
    path = save_structured_json(tmp_path, _norm(60))
    before = path.read_text(encoding="utf-8")

    def dies_halfway(data, handle, **kwargs):
        handle.write('{\n  "metadata": {\n    "title": "half a doc')
        raise OSError("no space left on device")

    monkeypatch.setattr(storage.json, "dump", dies_halfway)
    with pytest.raises(OSError):
        save_structured_json(tmp_path, _norm(1))

    assert path.read_text(encoding="utf-8") == before
    json.loads(path.read_text(encoding="utf-8"))
    # And nothing left behind to be mistaken for a law.
    assert [p.name for p in (tmp_path / "json").iterdir()] == [path.name]


def test_the_same_norm_written_twice_is_not_a_clash(tmp_path):
    """A retry or a duplicate discovery entry must not fork the file."""
    reset_write_tracking()
    first = save_structured_json(tmp_path, _norm(1))
    second = save_structured_json(tmp_path, _norm(2))

    assert first == second
    assert overwritten_identifiers() == {}
    assert [p.name for p in (tmp_path / "json").iterdir()] == [first.name]


def test_a_second_law_on_one_identifier_is_kept_beside_the_first(tmp_path):
    """Portugal published two unrelated acts as "Portaria n.º 953/2008".

    One is in Série I and concessions hunting rights; the other is in Série II and
    sets insurance fees. Before this, the second write replaced the first — and
    because the file name is also the Markdown name, the law disappeared from the
    corpus with nothing to show it had ever been there. 6,862 of them.
    """
    reset_write_tracking()
    first = save_structured_json(tmp_path, _norm(1))
    other = _norm(1)
    other = ParsedNorm(
        metadata=replace(
            other.metadata,
            publication_date=date(2010, 6, 30),
            source="https://diariodarepublica.pt/otro",
        ),
        blocks=other.blocks,
        reforms=other.reforms,
    )
    second = save_structured_json(tmp_path, other)

    assert first.name == f"{IDENTIFIER}.json"
    assert second.name == f"{IDENTIFIER}-20100630.json"
    assert overwritten_identifiers() == {IDENTIFIER: 1}
    # Both laws are readable, and each one keeps its own identifier.
    assert json.loads(first.read_text())["metadata"]["identifier"] == IDENTIFIER
    assert json.loads(second.read_text())["metadata"]["identifier"] == f"{IDENTIFIER}-20100630"
