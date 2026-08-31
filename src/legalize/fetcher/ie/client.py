"""Irish Statute Book (ISB) + Oireachtas API HTTP client.

Text source (XML): https://www.irishstatutebook.ie/eli/{year}/act/{number}/enacted/en/xml
Text source (HTML fallback): https://www.irishstatutebook.ie/eli/{year}/act/{number}/enacted/en/print
Metadata source: https://api.oireachtas.ie/v1/legislation
Revised Acts: https://revisedacts.lawreform.ie/eli/{year}/act/{number}/revised/en/html
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import requests

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

_ISB_BASE = "https://www.irishstatutebook.ie"
_OIREACHTAS_API = "https://api.oireachtas.ie"
_REVISED_ACTS_BASE = "https://revisedacts.lawreform.ie"


def _parse_norm_id(norm_id: str) -> tuple[int, str, str]:
    """Parse norm_id into (year, act_type, number).

    Formats:
    - IE-2024-act-1  → (2024, "act", "1")
    - IE-2015-act-C34 → (2015, "ca", "34")  (Constitutional Amendment)
    - IE-2023-act-P1  → (2023, "prv", "1")  (Private Act)
    """
    parts = norm_id.split("-")
    # IE-2024-act-1 → ["IE", "2024", "act", "1"]
    year = int(parts[1])
    raw_num = parts[3]

    if raw_num.startswith("C"):
        return year, "ca", raw_num[1:]
    if raw_num.startswith("P"):
        return year, "prv", raw_num[1:]
    return year, "act", raw_num


class ISBClient(HttpClient):
    """HTTP client for Irish legislation.

    Two endpoints:
    - ISB: XML text of Acts (irishstatutebook.ie)
    - Oireachtas API: JSON metadata catalog (api.oireachtas.ie)
    """

    @classmethod
    def create(cls, country_config: CountryConfig) -> ISBClient:
        source = country_config.source or {}
        return cls(
            isb_base=source.get("isb_base_url", _ISB_BASE),
            api_base=source.get("api_base_url", _OIREACHTAS_API),
            requests_per_second=source.get("requests_per_second", 2.0),
            request_timeout=source.get("request_timeout", 30),
            max_retries=source.get("max_retries", 3),
        )

    def __init__(
        self,
        isb_base: str = _ISB_BASE,
        api_base: str = _OIREACHTAS_API,
        requests_per_second: float = 2.0,
        request_timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        super().__init__(
            base_url=isb_base,
            requests_per_second=requests_per_second,
            request_timeout=request_timeout,
            max_retries=max_retries,
        )
        self._api_base = api_base.rstrip("/")

    def get_text(self, norm_id: str) -> bytes:
        """Fetch the Act text from ISB.

        Tries XML first (/enacted/en/xml). If 404, falls back to
        the print HTML view (/enacted/en/print) — pre-1995 acts
        only have HTML, not XML.

        Supports act types: act, ca (constitutional amendment), prv (private).
        """
        year, act_type, number = _parse_norm_id(norm_id)
        eli_path = f"{self._base_url}/eli/{year}/{act_type}/{number}/enacted/en"

        # Try XML first (available for ~1995+ acts)
        try:
            return self._get(f"{eli_path}/xml")
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                logger.debug("No XML for %s, falling back to HTML print view", norm_id)
            else:
                raise

        # Fallback to HTML print view
        return self._get(f"{eli_path}/print")

    def get_metadata(self, norm_id: str) -> bytes:
        """Fetch Act metadata from Oireachtas API.

        URL: /v1/legislation?act_year={year}&act_no={number}&limit=1
        Returns the raw JSON response bytes.
        """
        year, act_type, number = _parse_norm_id(norm_id)
        url = f"{self._api_base}/v1/legislation"
        return self._get(
            url,
            params={
                "act_year": str(year),
                "act_no": str(number),
                "limit": "1",
                "lang": "en",
            },
        )

    def get_legislation_page(self, *, skip: int = 0, limit: int = 50, **params: str) -> dict:
        """Fetch a page of legislation from the Oireachtas API.

        Used by discovery to paginate through the full catalog.
        """
        url = f"{self._api_base}/v1/legislation"
        query = {
            "bill_status": "Enacted",
            "skip": str(skip),
            "limit": str(limit),
            "lang": "en",
            **params,
        }
        data = self._get(url, params=query)
        return json.loads(data)

    def get_updated_since(
        self, since_date: str, *, skip: int = 0, limit: int = 50, **params: str
    ) -> dict:
        """Fetch legislation updated since a date (for daily discovery).

        since_date: ISO date string, e.g. '2026-04-01'.
        """
        return self.get_legislation_page(skip=skip, limit=limit, last_updated=since_date, **params)

    def get_revised_text(self, norm_id: str) -> bytes | None:
        """Fetch consolidated text from Revised Acts (revisedacts.lawreform.ie).

        Returns HTML bytes if the act has a revised version, None if 404.
        Only ~560 acts have revised versions.
        """
        year, act_type, number = _parse_norm_id(norm_id)
        url = f"{_REVISED_ACTS_BASE}/eli/{year}/{act_type}/{number}/revised/en/html"
        try:
            return self._get(url)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return None
            raise
