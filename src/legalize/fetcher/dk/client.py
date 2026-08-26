"""HTTP client for Retsinformation (Denmark).

Retsinformation is the official Danish legal information system, managed by
Civilstyrelsen.  Legislation is available as LexDania 2.1 XML via European
Legislation Identifier (ELI) URLs.

Two data channels:
  - ELI XML: ``https://www.retsinformation.dk/eli/{path}/xml``
    Full document text + metadata.  No auth.  No documented rate limit (behind
    Cloudflare — use a real User-Agent).
  - Harvest API: ``https://api.retsinformation.dk/v1/Documents``
    Daily change feed.  No auth.  1 req / 10 s, operating hours 03:00-23:45.
  - Metadata API: ``https://www.retsinformation.dk/api/document/metadata/{accn}``
    Schema.org JSON-LD with ``legislationConsolidates`` for version chaining.

License: public domain (Lov om ophavsret, section 9).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

_DEFAULT_BASE = "https://www.retsinformation.dk"
_HARVEST_API = "https://api.retsinformation.dk"


class RetsinformationClient(HttpClient):
    """Client for Danish legislation on retsinformation.dk.

    Norm IDs use ELI path format: ``lta/{year}/{number}`` for Lovtidende A
    documents.  The client resolves these to full ELI XML URLs.
    """

    def __init__(
        self,
        *,
        base_url: str = _DEFAULT_BASE,
        harvest_api: str = _HARVEST_API,
        **kwargs,
    ) -> None:
        super().__init__(base_url=base_url, **kwargs)
        self._harvest_api = harvest_api.rstrip("/")

    @classmethod
    def create(cls, country_config: CountryConfig) -> RetsinformationClient:
        source = country_config.source or {}
        return cls(
            base_url=source.get("base_url", _DEFAULT_BASE),
            harvest_api=source.get("harvest_api", _HARVEST_API),
            request_timeout=int(source.get("request_timeout", 30)),
            max_retries=int(source.get("max_retries", 5)),
            requests_per_second=float(source.get("requests_per_second", 2.0)),
        )

    # ── Document fetches ──

    def get_text(self, norm_id: str) -> bytes:
        """Fetch LexDania XML for a document.

        *norm_id* is either an ELI path (``lta/2024/62``) or an accession
        number (``A20240006229``).  Both resolve to the XML endpoint.
        """
        if norm_id.startswith(("A", "B", "C")):
            # Accession number
            url = f"{self._base_url}/eli/accn/{norm_id}/xml"
        else:
            # ELI path (lta/2024/62)
            url = f"{self._base_url}/eli/{norm_id}/xml"
        return self._get(url)

    def get_metadata(self, norm_id: str) -> bytes:
        """Metadata is embedded in the same XML as the text."""
        return self.get_text(norm_id)

    # ── Version chain helpers ──

    # ── Daily change feed ──

    def get_daily_changes(self, date_str: str | None = None) -> list[dict]:
        """Fetch documents changed on a given date (harvest API).

        *date_str* is ``YYYY-MM-DD``.  If omitted, returns today's changes.
        Max 10 days lookback.  Returns list of document change records.
        """
        url = f"{self._harvest_api}/v1/Documents"
        params = {}
        if date_str:
            params["date"] = date_str
        data = self._get(url, params=params)
        return json.loads(data)
