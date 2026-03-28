"""Tests for the FileCache."""

import time

from legalize.fetcher.cache import FileCache


class TestFileCache:
    def test_put_and_get(self, tmp_path):
        cache = FileCache(tmp_path, ttl_hours=1)
        cache.put("https://example.com/test", b"<xml>content</xml>", {"ETag": '"abc123"'})

        entry = cache.get("https://example.com/test")
        assert entry is not None
        assert entry.content == b"<xml>content</xml>"
        assert entry.headers["ETag"] == '"abc123"'

    def test_cache_miss(self, tmp_path):
        cache = FileCache(tmp_path, ttl_hours=1)
        assert cache.get("https://example.com/nonexistent") is None

    def test_ttl_expiry(self, tmp_path):
        cache = FileCache(tmp_path, ttl_hours=0)  # TTL = 0 hours = expires immediately
        cache.put("https://example.com/test", b"content", {})

        # With TTL 0, it should expire immediately
        time.sleep(0.01)
        assert cache.get("https://example.com/test") is None

    def test_etag_retrieval(self, tmp_path):
        cache = FileCache(tmp_path, ttl_hours=1)
        cache.put("https://example.com/test", b"content", {"ETag": '"v1"'})

        assert cache.etag_for("https://example.com/test") == '"v1"'

    def test_etag_missing(self, tmp_path):
        cache = FileCache(tmp_path, ttl_hours=1)
        assert cache.etag_for("https://example.com/nonexistent") is None

    def test_last_modified_retrieval(self, tmp_path):
        cache = FileCache(tmp_path, ttl_hours=1)
        cache.put("https://example.com/test", b"content", {"Last-Modified": "Mon, 01 Jan 2024"})

        assert cache.last_modified_for("https://example.com/test") == "Mon, 01 Jan 2024"

    def test_invalidate(self, tmp_path):
        cache = FileCache(tmp_path, ttl_hours=1)
        cache.put("https://example.com/test", b"content", {})
        cache.invalidate("https://example.com/test")

        assert cache.get("https://example.com/test") is None

    def test_clear(self, tmp_path):
        cache = FileCache(tmp_path, ttl_hours=1)
        cache.put("https://example.com/a", b"a", {})
        cache.put("https://example.com/b", b"b", {})
        cache.clear()

        assert cache.get("https://example.com/a") is None
        assert cache.get("https://example.com/b") is None

    def test_different_keys_independent(self, tmp_path):
        cache = FileCache(tmp_path, ttl_hours=1)
        cache.put("https://example.com/a", b"content-a", {})
        cache.put("https://example.com/b", b"content-b", {})

        assert cache.get("https://example.com/a").content == b"content-a"
        assert cache.get("https://example.com/b").content == b"content-b"
