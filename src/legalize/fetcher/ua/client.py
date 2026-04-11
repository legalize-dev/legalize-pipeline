"""Ukraine legislative client — data.rada.gov.ua / zakon.rada.gov.ua.

Uses .txt for full law text and .xml for metadata (HTML with <meta> tags).
JSON endpoints for per-document access are unreliable, so we avoid them.
The /laws/main/r/page{N}.json endpoint (recently updated) does work and
is used for daily discovery.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from urllib.parse import quote

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

_OPEN_DATA_UA = "OpenData"


class RadaClient(HttpClient):
    """HTTP client for the Verkhovna Rada legislative portal.

    Two base URLs are used:
    - data.rada.gov.ua — open data API (discovery lists, .txt, .xml, daily JSON)
    - zakon.rada.gov.ua — web portal (type lists like t1.txt, t21.txt)
    """

    def __init__(
        self,
        *,
        base_url: str,
        zakon_base_url: str,
        request_timeout: int = 30,
        max_retries: int = 5,
        requests_per_second: float = 1.0,
    ) -> None:
        super().__init__(
            base_url=base_url,
            user_agent=_OPEN_DATA_UA,
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
        )
        self._zakon_base_url = zakon_base_url.rstrip("/")
        self._token: str | None = None

    @classmethod
    def create(cls, country_config: CountryConfig) -> RadaClient:
        src = country_config.source
        return cls(
            base_url=src.get("base_url", "https://data.rada.gov.ua"),
            zakon_base_url=src.get("zakon_base_url", "https://zakon.rada.gov.ua"),
            request_timeout=src.get("request_timeout", 30),
            max_retries=src.get("max_retries", 5),
            requests_per_second=src.get("requests_per_second", 1.0),
        )

    @staticmethod
    def _encode_nreg(nreg: str) -> str:
        """URL-encode nreg, keeping ``/`` literal."""
        return quote(nreg, safe="/")

    def _ensure_token(self) -> None:
        """Fetch a daily API token for JSON endpoints."""
        if self._token is not None:
            return
        try:
            raw = self._get(f"{self._base_url}/api/token")
            data = json.loads(raw)
            self._token = data["token"]
            logger.info("Obtained Rada API token (expires in %ss)", data.get("expire"))
        except Exception:
            logger.warning("Failed to obtain API token, JSON endpoints may fail")
            self._token = _OPEN_DATA_UA

    def get_text(self, norm_id: str) -> bytes:
        """Fetch plain-text law content via /laws/show/{nreg}.txt."""
        url = f"{self._base_url}/laws/show/{self._encode_nreg(norm_id)}.txt"
        return self._get(url)

    def get_metadata(self, norm_id: str) -> bytes:
        """Fetch metadata via /laws/show/{nreg}.xml (HTML with <meta> tags)."""
        url = f"{self._base_url}/laws/show/{self._encode_nreg(norm_id)}.xml"
        return self._get(url)

    def get_discovery_list(self, list_name: str) -> bytes:
        """Fetch a discovery list (perv0/1/2.txt). Returns CP1251-encoded bytes."""
        url = f"{self._base_url}/ogd/zak/laws/data/csv/{list_name}"
        return self._get(url)

    def get_type_list(self, type_id: str) -> bytes:
        """Fetch a type list from zakon.rada.gov.ua (e.g. t1.txt for laws)."""
        url = f"{self._zakon_base_url}/laws/main/{type_id}.txt"
        return self._get(url)

    def get_recent_page(self, page: int) -> bytes:
        """Fetch recently updated documents (JSON). Requires API token."""
        self._ensure_token()
        url = f"{self._base_url}/laws/main/r/page{page}.json"
        old_ua = self._session.headers.get("User-Agent")
        try:
            self._session.headers["User-Agent"] = self._token or _OPEN_DATA_UA
            return self._get(url)
        finally:
            self._session.headers["User-Agent"] = old_ua or _OPEN_DATA_UA
