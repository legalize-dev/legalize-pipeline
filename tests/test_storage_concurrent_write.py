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


def test_a_shadowed_law_is_counted(tmp_path):
    reset_write_tracking()
    save_structured_json(tmp_path, _norm(1))
    assert overwritten_identifiers() == {}
    save_structured_json(tmp_path, _norm(2))
    assert overwritten_identifiers() == {IDENTIFIER: 1}
