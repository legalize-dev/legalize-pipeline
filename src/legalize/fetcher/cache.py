"""Local cache for BOE HTTP responses.

Stores downloaded XMLs on disk with configurable TTL and support for
conditional requests (ETag / Last-Modified).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class CacheEntry:
    """Cache entry with content and HTTP headers."""

    content: bytes
    headers: dict[str, str]
    timestamp: float  # time.time() when stored


class FileCache:
    """Filesystem cache with TTL and ETag support."""

    def __init__(self, cache_dir: str | Path, ttl_hours: int = 24):
        self._dir = Path(cache_dir)
        self._ttl_seconds = ttl_hours * 3600
        self._dir.mkdir(parents=True, exist_ok=True)

    def _key_to_paths(self, key: str) -> tuple[Path, Path]:
        """Generates paths for content and metadata from a key (URL)."""
        h = hashlib.sha256(key.encode()).hexdigest()[:16]
        return self._dir / f"{h}.xml", self._dir / f"{h}.meta.json"

    def get(self, key: str) -> Optional[CacheEntry]:
        """Returns the cached entry if it exists and has not expired."""
        content_path, meta_path = self._key_to_paths(key)

        if not content_path.exists() or not meta_path.exists():
            return None

        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)

        # Check TTL
        age = time.time() - meta.get("timestamp", 0)
        if age > self._ttl_seconds:
            return None

        content = content_path.read_bytes()
        return CacheEntry(
            content=content,
            headers=meta.get("headers", {}),
            timestamp=meta.get("timestamp", 0),
        )

    def put(self, key: str, content: bytes, headers: dict[str, str]) -> None:
        """Stores content with its response headers."""
        content_path, meta_path = self._key_to_paths(key)

        content_path.write_bytes(content)

        meta = {
            "key": key,
            "headers": headers,
            "timestamp": time.time(),
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    def etag_for(self, key: str) -> Optional[str]:
        """Returns the stored ETag for conditional requests."""
        _, meta_path = self._key_to_paths(key)
        if not meta_path.exists():
            return None

        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        return meta.get("headers", {}).get("ETag")

    def last_modified_for(self, key: str) -> Optional[str]:
        """Returns the stored Last-Modified for conditional requests."""
        _, meta_path = self._key_to_paths(key)
        if not meta_path.exists():
            return None

        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        return meta.get("headers", {}).get("Last-Modified")

    def invalidate(self, key: str) -> None:
        """Removes an entry from the cache."""
        content_path, meta_path = self._key_to_paths(key)
        content_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)

    def clear(self) -> None:
        """Clears all cache entries."""
        for path in self._dir.iterdir():
            path.unlink(missing_ok=True)
