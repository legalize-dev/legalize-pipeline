"""ELI API client for Polish legislation (Sejm).

The Sejm exposes a public REST API at https://api.sejm.gov.pl/eli that returns:
- Metadata as JSON per act: /acts/{publisher}/{year}/{pos}
- Consolidated text as HTML:  /acts/{publisher}/{year}/{pos}/text.html
- Hierarchical structure JSON: /acts/{publisher}/{year}/{pos}/struct
- Per-year paginated search:  /acts/search?publisher=XX&year=YYYY&limit=500
- Change feed for daily path: /changes/acts?since=YYYY-MM-DDTHH:MM:SS

The API is public, no authentication. The WAF rejects unknown query parameters
with an HTTP 200 HTML body titled "Request Rejected", so the client stays
conservative and only uses documented parameters.

Internal norm_id format: "{publisher}-{year}-{pos}" (dashes, filesystem-safe).
The client translates it back to ELI form ("{publisher}/{year}/{pos}") for URLs.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

DEFAULT_BASE_URL = "https://api.sejm.gov.pl/eli"
DEFAULT_PUBLISHER = "DU"
SEARCH_LIMIT_MAX = 500


def norm_id_to_eli(norm_id: str) -> str:
    """Convert internal "DU-2024-1907" → ELI "DU/2024/1907"."""
    parts = norm_id.split("-")
    if len(parts) != 3:
        raise ValueError(f"Invalid PL norm_id: {norm_id!r} (expected PUBLISHER-YEAR-POS)")
    return "/".join(parts)


def eli_to_norm_id(eli: str) -> str:
    """Convert ELI "DU/2024/1907" → internal "DU-2024-1907"."""
    return eli.replace("/", "-")


class EliClient(HttpClient):
    """HTTP client for the Polish Sejm ELI API."""

    @classmethod
    def create(cls, country_config: CountryConfig) -> EliClient:
        source = country_config.source or {}
        return cls(
            base_url=source.get("base_url", DEFAULT_BASE_URL),
            publisher=source.get("publisher", DEFAULT_PUBLISHER),
            request_timeout=source.get("request_timeout", 30),
            max_retries=source.get("max_retries", 5),
            requests_per_second=source.get("requests_per_second", 2.0),
        )

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        publisher: str = DEFAULT_PUBLISHER,
        request_timeout: int = 30,
        max_retries: int = 5,
        requests_per_second: float = 2.0,
    ) -> None:
        super().__init__(
            base_url=base_url,
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
            extra_headers={"Accept": "application/json"},
        )
        self.publisher = publisher

    # ─── Per-act fetches ───

    def get_metadata(self, norm_id: str) -> bytes:
        """Fetch the metadata JSON for a single act."""
        eli = norm_id_to_eli(norm_id)
        return self._get(f"{self._base_url}/acts/{eli}")

    def get_text(self, norm_id: str, meta_data: bytes | None = None) -> bytes:
        """Fetch the HTML consolidated text of a single act.

        Raises ValueError if the act has no HTML (the API returns a zero-byte
        body with HTTP 200 in that case).

        The pipeline passes pre-fetched metadata bytes via ``meta_data`` so
        that we can inject a marker comment with the norm_id and publication
        date into the HTML. The parser reads the marker back (since the body
        itself does not carry the ELI or a structured publication date).
        """
        eli = norm_id_to_eli(norm_id)
        data = self._get(
            f"{self._base_url}/acts/{eli}/text.html",
            headers={"Accept": "text/html"},
        )
        if not data:
            raise ValueError(f"Act {norm_id} has no HTML text (PDF-only)")

        pub_date = ""
        if meta_data:
            try:
                pub_date = str(json.loads(meta_data).get("announcementDate") or "")
            except (json.JSONDecodeError, AttributeError):
                pub_date = ""

        marker = f"<!--LEGALIZE norm_id={norm_id} pub_date={pub_date}-->\n".encode()
        return marker + data

    # ─── Discovery / daily fetches ───

    def search_year(self, year: int, offset: int = 0, limit: int = SEARCH_LIMIT_MAX) -> bytes:
        """List acts for a given year (paginated). Returns raw JSON bytes.

        Uses the /acts/search endpoint with publisher+year filtering.
        """
        if limit > SEARCH_LIMIT_MAX:
            limit = SEARCH_LIMIT_MAX
        return self._get(
            f"{self._base_url}/acts/search",
            params={
                "publisher": self.publisher,
                "year": year,
                "limit": limit,
                "offset": offset,
            },
        )

    def get_changes(self, since_iso: str, offset: int = 0, limit: int = SEARCH_LIMIT_MAX) -> bytes:
        """Fetch acts whose API record changed since a given ISO timestamp.

        Used by the daily path: the cursor is the last successful run time.
        """
        if limit > SEARCH_LIMIT_MAX:
            limit = SEARCH_LIMIT_MAX
        return self._get(
            f"{self._base_url}/changes/acts",
            params={"since": since_iso, "limit": limit, "offset": offset},
        )
