"""HTTP client for the BOE open data API.

Rate limiting and retry come from :class:`HttpClient`; this adds the
conditional requests (ETag/Last-Modified) served out of FileCache.
"""

from __future__ import annotations

import logging
from datetime import date

from legalize.fetcher.base import HttpClient
from legalize.fetcher.es.config import BOEConfig
from legalize.fetcher.cache import FileCache

logger = logging.getLogger(__name__)


class BOEClient(HttpClient):
    """Client for the BOE open data API (https://www.boe.es/datosabiertos/)."""

    @classmethod
    def create(cls, country_config):
        """Create BOEClient from CountryConfig."""
        from legalize.fetcher.cache import FileCache

        source = country_config.source
        config = BOEConfig(
            base_url=source.get("base_url", BOEConfig.base_url),
            requests_per_second=source.get("requests_per_second", BOEConfig.requests_per_second),
            request_timeout=source.get("request_timeout", BOEConfig.request_timeout),
            max_retries=source.get("max_retries", BOEConfig.max_retries),
        )
        cache = FileCache(country_config.cache_dir)
        return cls(config, cache)

    def __init__(self, config: BOEConfig, cache: FileCache):
        super().__init__(
            base_url=config.base_url,
            user_agent=config.user_agent,
            request_timeout=config.request_timeout,
            max_retries=config.max_retries,
            requests_per_second=config.requests_per_second,
            extra_headers={"Accept": "application/xml"},
        )
        self._config = config
        self._cache = cache

    def _build_url(self, path: str) -> str:
        return f"{self._config.base_url}{path}"

    def _fetch(self, url: str, bypass_cache: bool = False) -> bytes:
        """Fetch with cache, rate limiting, and conditional requests."""
        # Try cache first
        if not bypass_cache:
            entry = self._cache.get(url)
            if entry is not None:
                logger.debug("Cache hit: %s", url)
                return entry.content

        # Conditional headers
        headers: dict[str, str] = {}
        if not bypass_cache:
            etag = self._cache.etag_for(url)
            if etag:
                headers["If-None-Match"] = etag
            last_modified = self._cache.last_modified_for(url)
            if last_modified:
                headers["If-Modified-Since"] = last_modified

        logger.info("GET %s", url)
        response = self._request("GET", url, headers=headers)

        # 304 Not Modified → return from cache
        if response.status_code == 304:
            entry = self._cache.get(url)
            if entry is not None:
                logger.debug("304 Not Modified, using cache: %s", url)
                return entry.content

        # Save to cache
        cache_headers = {}
        if "ETag" in response.headers:
            cache_headers["ETag"] = response.headers["ETag"]
        if "Last-Modified" in response.headers:
            cache_headers["Last-Modified"] = response.headers["Last-Modified"]

        self._cache.put(url, response.content, cache_headers)
        return response.content

    # ── Public endpoints ──

    def get_sumario(self, target_date: date) -> bytes:
        """Fetches the BOE daily summary for a date: /api/boe/sumario/{YYYYMMDD}."""
        path = f"/api/boe/sumario/{target_date.strftime('%Y%m%d')}"
        return self._fetch(self._build_url(path))

    def get_text(self, id_boe: str) -> bytes:
        """Fetches the consolidated text XML (implements LegislativeClient interface)."""
        return self.get_consolidated_text(id_boe)

    def get_consolidated_text(self, id_boe: str, bypass_cache: bool = False) -> bytes:
        """Fetches the consolidated text XML: /api/legislacion-consolidada/id/{id}/texto."""
        path = f"/api/legislacion-consolidada/id/{id_boe}/texto"
        return self._fetch(self._build_url(path), bypass_cache=bypass_cache)

    def get_updated(self, start: date, end: date) -> bytes:
        """Norms whose consolidated text the BOE updated in [start, end].

        ``/api/legislacion-consolidada?from=&to=`` filters on ``fecha_actualizacion``,
        i.e. when the BOE folded an amendment into the consolidated text — which is
        the only place the source states what actually changed. Never cached: the
        answer for a window keeps growing until the BOE finishes consolidating it.
        """
        path = (
            f"/api/legislacion-consolidada"
            f"?from={start.strftime('%Y%m%d')}&to={end.strftime('%Y%m%d')}"
        )
        return self._fetch(self._build_url(path), bypass_cache=True)

    def get_catalog(self, limit: int, offset: int) -> bytes:
        """One page of the consolidated catalogue.

        ``/api/legislacion-consolidada?limit=&offset=`` is the filterable
        catalogue endpoint this module's docstring said the BOE does not
        expose. It caps a page at 10,000 entries, so the whole catalogue —
        12,387 norms — is two requests, against the 14,926 daily summaries the
        sweep it replaces would have walked (#99).
        """
        path = f"/api/legislacion-consolidada?limit={limit}&offset={offset}"
        return self._fetch(self._build_url(path))

    def get_metadata(self, id_boe: str) -> bytes:
        """Fetches metadata for a norm: /api/legislacion-consolidada/id/{id}/metadatos."""
        path = f"/api/legislacion-consolidada/id/{id_boe}/metadatos"
        return self._fetch(self._build_url(path))

    def get_disposition_xml(self, id_boe: str) -> bytes:
        """Fetches the raw BOE disposition XML: /diario_boe/xml.php?id={id}.

        This is the full diary entry XML (not the open data API) which
        contains an <analisis> section with references to affected norms.
        """
        base = self._config.base_url.rsplit("/", 1)[0]
        url = f"{base}/diario_boe/xml.php?id={id_boe}"
        return self._fetch(url)
