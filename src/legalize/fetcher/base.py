"""Abstract base for legislative API clients and norm discovery."""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import date
from typing import TYPE_CHECKING, Any

import requests

from legalize.models import NormMetadata

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)


class LegislativeClient(ABC):
    """Base class for country-specific legislative API clients.

    Each country implements its own client with endpoints for:
    - Fetching consolidated text (XML/HTML)
    - Fetching metadata
    - Rate limiting and caching
    """

    @classmethod
    def create(cls, country_config: CountryConfig) -> LegislativeClient:
        """Create a client instance from country config.

        Override in subclass to read source-specific params.
        Default: no-args constructor.
        """
        return cls()

    @abstractmethod
    def get_text(self, norm_id: str) -> bytes:
        """Fetch the consolidated text of a norm (XML or HTML)."""

    @abstractmethod
    def get_metadata(self, norm_id: str) -> bytes:
        """Fetch metadata for a norm."""

    @abstractmethod
    def close(self) -> None:
        """Clean up resources."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


_DEFAULT_USER_AGENT = "legalize-bot/1.0 (+https://github.com/legalize-dev/legalize)"
# Retry on rate-limit and transient gateway errors. BCN's nuevo.leychile.cl
# returns intermittent 502s during discovery walks; CloudFront 504s also
# happen on rare cold-start fetches. Retrying with backoff is safe because
# all our endpoints are GETs with idempotent semantics.
_RETRY_STATUS_CODES = (429, 502, 503, 504)


class HttpClient(LegislativeClient):
    """Base class for HTTP-based legislative clients.

    Provides requests.Session with configurable User-Agent,
    thread-safe rate limiting, and retry with exponential backoff.

    Subclasses implement get_text/get_metadata using self._get().
    """

    def __init__(
        self,
        *,
        base_url: str = "",
        user_agent: str = _DEFAULT_USER_AGENT,
        request_timeout: int = 30,
        max_retries: int = 3,
        requests_per_second: float = 2.0,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") if base_url else ""
        self._timeout = request_timeout
        self._max_retries = max_retries

        self._session = requests.Session()
        self._session.headers["User-Agent"] = user_agent
        if extra_headers:
            self._session.headers.update(extra_headers)

        # Thread-safe rate limiter
        self._min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0
        self._last_request: float = 0.0
        self._rate_lock = threading.Lock()

    def _wait_rate_limit(self) -> None:
        """Wait if needed to respect the rate limit."""
        if self._min_interval <= 0:
            return
        with self._rate_lock:
            elapsed = time.monotonic() - self._last_request
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_request = time.monotonic()

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        headers: dict[str, str] | None = None,
        json: dict | None = None,
        data: bytes | None = None,
        timeout: int | None = None,
    ) -> requests.Response:
        """HTTP request with rate limiting and retry on transient errors."""
        self._wait_rate_limit()
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = self._session.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    json=json,
                    data=data,
                    timeout=timeout or self._timeout,
                )
                if resp.status_code in _RETRY_STATUS_CODES and attempt < self._max_retries - 1:
                    wait = 2**attempt
                    logger.warning(
                        "%s %d on %s, retrying in %ds (attempt %d/%d)",
                        method,
                        resp.status_code,
                        url,
                        wait,
                        attempt + 1,
                        self._max_retries,
                    )
                    time.sleep(wait)
                    self._wait_rate_limit()
                    continue
                resp.raise_for_status()
                return resp
            except requests.HTTPError:
                raise  # Non-retryable HTTP errors (404, 400, etc.)
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < self._max_retries - 1:
                    wait = 2**attempt
                    logger.warning(
                        "Request error (attempt %d/%d): %s",
                        attempt + 1,
                        self._max_retries,
                        exc,
                    )
                    time.sleep(wait)
        raise last_exc or RuntimeError(f"Failed {method} {url}")

    def _get(self, url: str, **kwargs) -> bytes:
        """GET request returning response body as bytes."""
        return self._request("GET", url, **kwargs).content

    def close(self) -> None:
        """Close the HTTP session."""
        self._session.close()


class NormDiscovery(ABC):
    """Base class for discovering norms in a country's catalog.

    Each country publishes legislation differently:
    - Spain: daily BOE sumario XML
    - France: LEGI XML dumps with versioning
    - UK: Atom publication feed
    - Germany: static XML with HTTP header change detection
    """

    @classmethod
    def create(cls, source: dict) -> NormDiscovery:
        """Create a discovery instance from source config.

        Override in subclass to read source-specific params.
        Default: no-args constructor.
        """
        return cls()

    @abstractmethod
    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Discover all norm IDs in the catalog."""

    @abstractmethod
    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Discover norms published/updated on a specific date."""


class TextParser(ABC):
    """Base class for parsing consolidated text into structured blocks.

    Each country's XML/HTML format is different, but the output
    is always a list of Block objects with version history.
    """

    @abstractmethod
    def parse_text(self, data: bytes) -> list[Any]:
        """Parse consolidated text into a list of Block objects."""

    def extract_reforms(self, data: bytes) -> list[Any]:
        """Extract reform timeline from consolidated text.

        Default: parse text into blocks, then extract reforms from
        version dates. Override for country-specific logic (e.g., SE
        parses SFSR amendment register, DE reads standangabe metadata).
        """
        from legalize.transformer.xml_parser import extract_reforms

        blocks = self.parse_text(data)
        return extract_reforms(blocks)


class MetadataParser(ABC):
    """Base class for parsing norm metadata.

    Each country has different metadata fields, rank hierarchies,
    and status flags, but the output is always NormMetadata.
    """

    @abstractmethod
    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        """Parse raw metadata into NormMetadata."""
