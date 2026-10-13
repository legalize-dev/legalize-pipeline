"""Cached eISB text, Oireachtas metadata and LRC history downloads."""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

import requests

from legalize.fetcher.base import HttpClient
from legalize.fetcher.cache import FileCache

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

_ISB_BASE = "https://www.irishstatutebook.ie"
_OIREACHTAS_API = "https://api.oireachtas.ie"
_REVISED_ACTS_BASE = "https://revisedacts.lawreform.ie"
CONSTITUTION_ID = "IE-1937-constitution"
_refresh_cutoff: float | None = None
_refresh_locks: dict[str, threading.Lock] = {}
_refresh_locks_guard = threading.Lock()


@contextmanager
def refresh_sources():
    """Refresh mutable URLs once per run, across short-lived clients and worker threads."""
    global _refresh_cutoff
    previous = _refresh_cutoff
    _refresh_cutoff = previous if previous is not None else time.time()
    if previous is None:
        _refresh_locks.clear()
    try:
        yield
    finally:
        _refresh_cutoff = previous
        if previous is None:
            _refresh_locks.clear()


def _parse_norm_id(norm_id: str) -> tuple[int, str, str]:
    """Return the source year, ELI type and unprefixed number."""
    match = re.fullmatch(r"IE-(\d{4})-(act|si)-([CP]?)([1-9]\d*)", norm_id)
    if match is None:
        raise ValueError(f"Invalid Irish Act identifier: {norm_id}")
    year, kind, prefix, number = match.groups()
    if kind == "si":
        if prefix:
            raise ValueError(f"Invalid Irish instrument identifier: {norm_id}")
        return int(year), "si", number
    return int(year), {"": "act", "C": "ca", "P": "prv"}[prefix], number


class ISBClient(HttpClient):
    """Download official source bytes with persistent, URL-keyed caching."""

    # Public eISB catalogue URLs intermittently return 403 and then succeed unchanged.
    _retry_status_codes = HttpClient._retry_status_codes + (403,)

    @classmethod
    def create(cls, country_config: CountryConfig) -> ISBClient:
        source = country_config.source or {}
        cache_dir = Path(country_config.data_dir or country_config.cache_dir) / "raw"
        return cls(
            isb_base=source.get("isb_base_url", _ISB_BASE),
            api_base=source.get("api_base_url", _OIREACHTAS_API),
            requests_per_second=float(source.get("requests_per_second", 2.0)),
            request_timeout=int(source.get("request_timeout", 30)),
            max_retries=int(source.get("max_retries", 3)),
            cache=FileCache(cache_dir),
        )

    def __init__(
        self,
        isb_base: str = _ISB_BASE,
        api_base: str = _OIREACHTAS_API,
        requests_per_second: float = 2.0,
        request_timeout: int = 30,
        max_retries: int = 3,
        cache: FileCache | None = None,
    ) -> None:
        super().__init__(
            base_url=isb_base,
            requests_per_second=requests_per_second,
            request_timeout=request_timeout,
            max_retries=max_retries,
        )
        self._api_base = api_base.rstrip("/")
        self._cache = cache
        self._archive_cache = (
            FileCache(cache._dir, ttl_hours=24 * 365 * 100) if cache is not None else None
        )

    def _get(self, url: str, *, bypass_cache: bool = False, **kwargs) -> bytes:
        key = requests.Request("GET", url, params=kwargs.get("params")).prepare().url
        assert key is not None
        parsed = urlparse(key)
        version_ids = parse_qs(parsed.query, keep_blank_values=True).get("versionId", [])
        # S3's null version can be overwritten when bucket versioning is suspended.
        immutable = parsed.hostname == "rev-acts.s3.eu-west-1.amazonaws.com" and (
            len(version_ids) == 1 and version_ids[0] not in ("", "null")
        )
        cache = self._archive_cache if immutable else self._cache
        with _refresh_locks_guard:
            lock = (
                _refresh_locks.setdefault(key, threading.Lock())
                if cache is not None
                else nullcontext()
            )
        with lock:
            if cache is not None and not bypass_cache:
                entry = cache.get(key)
                if entry is not None and (
                    immutable or _refresh_cutoff is None or entry.timestamp >= _refresh_cutoff
                ):
                    return entry.content
            data = super()._get(url, **kwargs)
            if cache is not None:
                cache.put(key, data, {})
            return data

    def get_act_index(self, year: int, *, refresh: bool = False) -> bytes:
        """Return the public/private/constitutional Act catalogue for one year."""
        return self._get(f"{self._base_url}/eli/{year}/act", bypass_cache=refresh)

    def get_enacted_text(self, norm_id: str) -> bytes:
        """Return source XML, falling back to complete print HTML on 404."""
        if norm_id == CONSTITUTION_ID:
            return self._get(f"{self._base_url}/eli/cons/en/html")
        year, act_type, number = _parse_norm_id(norm_id)
        if act_type == "si":
            return self._get(f"{self._base_url}/eli/{year}/si/{number}/made/en/html")
        eli_path = f"{self._base_url}/eli/{year}/{act_type}/{number}/enacted/en"
        try:
            return self._get(f"{eli_path}/xml")
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code != 404:
                raise
        return self._get(f"{eli_path}/print")

    def get_text(self, norm_id: str, meta_data: bytes | None = None) -> bytes:
        """Bundle authentic source versions and amendment history."""
        from legalize.fetcher.ie.history import fetch_text

        return fetch_text(self, norm_id, meta_data)

    def get_metadata(self, norm_id: str) -> bytes:
        """Use enacted-source metadata, enriched only by matching parliamentary records."""
        from legalize.fetcher.ie.parser import ISBMetadataParser

        if norm_id == CONSTITUTION_ID:
            return self.get_enacted_text(norm_id)
        year, act_type, _ = _parse_norm_id(norm_id)
        if act_type == "si":
            return self.get_enacted_text(norm_id)
        enacted = self.get_enacted_text(norm_id)
        try:
            data = self._get(
                f"{self._api_base}/v1/legislation",
                params={
                    "act_year": str(year),
                    "act_no": norm_id.rsplit("-", 1)[1],
                    "bill_status": "Enacted",
                    "limit": "1",
                    "lang": "en",
                },
            )
            envelope = json.dumps(
                {
                    "legalize_ie_metadata": 1,
                    "enacted": base64.b64encode(enacted).decode("ascii"),
                    "parliament": json.loads(data),
                },
                ensure_ascii=False,
            ).encode("utf-8")
            ISBMetadataParser().parse(envelope, norm_id)
            return envelope
        except ValueError:
            logger.info("No matching API metadata for %s; using enacted source", norm_id)
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code != 404:
                raise
        return enacted

    def get_legislation_page(self, *, skip: int = 0, limit: int = 50, **params: str) -> dict:
        """Fetch supplementary enacted-Act metadata from the parliamentary API."""
        query = {
            "bill_status": "Enacted",
            "skip": str(skip),
            "limit": str(limit),
            "lang": "en",
            **params,
        }
        data = self._get(
            f"{self._api_base}/v1/legislation",
            params=query,
            bypass_cache="last_updated" in params,
        )
        return json.loads(data)

    def get_updated_since(
        self, since_date: str, *, skip: int = 0, limit: int = 50, **params: str
    ) -> dict:
        return self.get_legislation_page(skip=skip, limit=limit, last_updated=since_date, **params)

    def get_revised_text(self, norm_id: str) -> bytes | None:
        """Return the latest LRC HTML, preserving non-404 source failures."""
        year, act_type, number = _parse_norm_id(norm_id)
        url = f"{_REVISED_ACTS_BASE}/eli/{year}/{act_type}/{number}/revised/en/html"
        try:
            return self._get(url)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            raise
