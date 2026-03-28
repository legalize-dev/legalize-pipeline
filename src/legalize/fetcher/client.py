"""HTTP client for the BOE open data API.

Implements voluntary rate limiting, exponential backoff with jitter,
and conditional requests (ETag/Last-Modified) via FileCache.
"""

from __future__ import annotations

import logging
import time
from datetime import date

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from legalize.config import BOEConfig
from legalize.fetcher.cache import FileCache

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple token bucket to limit requests per second."""

    def __init__(self, requests_per_second: float):
        self._min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0
        self._last_request = 0.0

    def wait(self) -> None:
        if self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.monotonic()


class BOEClient:
    """Client for the BOE open data API (https://www.boe.es/datosabiertos/)."""

    def __init__(self, config: BOEConfig, cache: FileCache):
        self._config = config
        self._cache = cache
        self._rate_limiter = RateLimiter(config.requests_per_second)

        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": config.user_agent,
            "Accept": "application/xml",
        })

        # Retry with backoff for server errors
        retry = Retry(
            total=config.max_retries,
            backoff_factor=config.retry_backoff_base,
            backoff_jitter=config.retry_backoff_base * config.retry_jitter,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

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

        # Rate limiting
        self._rate_limiter.wait()

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
        response = self._session.get(
            url,
            headers=headers,
            timeout=self._config.request_timeout,
        )

        # 304 Not Modified → return from cache
        if response.status_code == 304:
            entry = self._cache.get(url)
            if entry is not None:
                logger.debug("304 Not Modified, using cache: %s", url)
                return entry.content

        response.raise_for_status()

        # Save to cache
        cache_headers = {}
        if "ETag" in response.headers:
            cache_headers["ETag"] = response.headers["ETag"]
        if "Last-Modified" in response.headers:
            cache_headers["Last-Modified"] = response.headers["Last-Modified"]

        self._cache.put(url, response.content, cache_headers)
        return response.content

    # ── Public endpoints ──

    def get_sumario(self, fecha: date) -> bytes:
        """Fetches the BOE daily summary for a date: /api/boe/sumario/{YYYYMMDD}."""
        path = f"/api/boe/sumario/{fecha.strftime('%Y%m%d')}"
        return self._fetch(self._build_url(path))

    def get_texto_consolidado(self, id_boe: str, bypass_cache: bool = False) -> bytes:
        """Fetches the consolidated text XML: /api/legislacion-consolidada/id/{id}/texto."""
        path = f"/api/legislacion-consolidada/id/{id_boe}/texto"
        return self._fetch(self._build_url(path), bypass_cache=bypass_cache)

    def get_metadatos(self, id_boe: str) -> bytes:
        """Fetches metadata for a norm: /api/legislacion-consolidada/id/{id}/metadatos."""
        path = f"/api/legislacion-consolidada/id/{id_boe}/metadatos"
        return self._fetch(self._build_url(path))

    def get_indice(self, id_boe: str) -> bytes:
        """Fetches the block index: /api/legislacion-consolidada/id/{id}/texto/indice."""
        path = f"/api/legislacion-consolidada/id/{id_boe}/texto/indice"
        return self._fetch(self._build_url(path))

    def get_catalogo(
        self,
        rango: str | None = None,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
        offset: int = 0,
    ) -> bytes:
        """Queries the consolidated legislation catalog with filters."""
        params: dict[str, str] = {}
        if rango:
            params["rango"] = rango
        if fecha_desde:
            params["fecha_desde"] = fecha_desde.isoformat()
        if fecha_hasta:
            params["fecha_hasta"] = fecha_hasta.isoformat()
        if offset > 0:
            params["offset"] = str(offset)

        url = self._build_url("/api/legislacion-consolidada")
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        return self._fetch(url)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> BOEClient:
        return self

    def __exit__(self, *args) -> None:
        self.close()
