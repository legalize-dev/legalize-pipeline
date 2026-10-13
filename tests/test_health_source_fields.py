"""Health inspects source metadata, not the HTTP cache's bookkeeping."""

import gzip
import json

import pytest

from legalize.cli import _source_fields
from legalize.fetcher.cache import FileCache


def test_file_cache_sidecar_is_not_legislative_metadata(tmp_path):
    cache = FileCache(tmp_path)
    cache.put("https://source.test/law", b"<act>Official text</act>", {"ETag": "revision-1"})
    sidecar = next(tmp_path.glob("*.meta.json"))
    assert _source_fields(sidecar) == {}


@pytest.mark.parametrize("compressed", [False, True])
def test_source_fields_with_cache_like_names_are_preserved(tmp_path, compressed):
    path = tmp_path / ("law.meta.json.gz" if compressed else "law.meta.json")
    fields = {
        "key": "Official identifier",
        "headers": {"title": "Official title"},
        "timestamp": 1970,
    }
    opener = gzip.open if compressed else open
    with opener(path, "wt", encoding="utf-8") as handle:
        json.dump(fields, handle)
    assert _source_fields(path) == {
        "key": "Official identifier",
        "headers.title": "Official title",
        "timestamp": 1970,
    }
