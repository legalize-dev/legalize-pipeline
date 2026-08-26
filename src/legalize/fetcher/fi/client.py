"""HTTP client for Finlex open data API (Finland).

Finlex publishes consolidated Finnish legislation as Akoma Ntoso XML via a
public REST API at https://opendata.finlex.fi/finlex/avoindata/v1.

No authentication required. Rate limit: returns HTTP 429 when exceeded
(no published threshold). License: CC BY 4.0.

API documentation:
  - https://www.finlex.fi/en/open-data/integration-quick-guide
  - https://opendata.finlex.fi/swagger-ui/index.html
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

_DEFAULT_API_BASE = "https://opendata.finlex.fi/finlex/avoindata/v1"


class FinlexClient(HttpClient):
    """Client for the Finlex consolidated-legislation API.

    Norm IDs use the format ``{year}/{number}`` (e.g. ``1999/731`` for the
    Finnish Constitution). The client maps these to Finlex API paths.
    """

    def __init__(self, *, api_base: str = _DEFAULT_API_BASE, **kwargs) -> None:
        super().__init__(base_url=api_base, **kwargs)
        self._api_base = api_base.rstrip("/")

    @classmethod
    def create(cls, country_config: CountryConfig) -> FinlexClient:
        source = country_config.source or {}
        return cls(
            api_base=source.get("api_base", _DEFAULT_API_BASE),
            request_timeout=int(source.get("request_timeout", 30)),
            max_retries=int(source.get("max_retries", 5)),
            requests_per_second=float(source.get("requests_per_second", 2.0)),
        )

    # ── Single-document fetches ──

    def get_text(self, norm_id: str) -> bytes:
        """Fetch the latest consolidated XML for a statute.

        *norm_id* is ``{year}/{number}`` — e.g. ``1999/731``.  The method
        paginates through the multi-version listing endpoint (max 4 per page)
        to find the latest Finnish expression, then fetches that version.

        Pagination is needed because the API returns mixed fin/swe expressions
        and the first page may contain only Swedish versions for bilingual laws.
        """
        year, number = _split_norm_id(norm_id)

        from lxml import etree

        ns = {"akn": "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"}

        for page in range(1, 20):
            url = (
                f"{self._api_base}/akn/fi/act/statute-consolidated"
                f"/{year}/{number}?page={page}&limit=4"
            )
            listing_xml = self._get(url)
            root = etree.fromstring(listing_xml)
            exprs = root.findall(".//akn:FRBRExpression", ns)
            if not exprs:
                break
            for expr in exprs:
                lang_el = expr.find("akn:FRBRlanguage", ns)
                uri_el = expr.find("akn:FRBRuri", ns)
                if lang_el is not None and lang_el.get("language") == "fin" and uri_el is not None:
                    version_path = uri_el.get("value", "")
                    return self._get(f"{self._api_base}{version_path}")
            if len(exprs) < 4:
                break

        # Fallback: try bare fin@ (for statutes with a single version)
        url_bare = f"{self._api_base}/akn/fi/act/statute-consolidated/{year}/{number}/fin@"
        return self._get(url_bare)

    def get_metadata(self, norm_id: str) -> bytes:
        """Metadata is embedded in the same XML as the text."""
        return self.get_text(norm_id)

    # ── Version-specific fetches ──

    # ── Discovery helpers ──

    def list_statutes(
        self,
        page: int = 1,
        limit: int = 10,
        *,
        lang_version: str = "fin@",
        published_since: str | None = None,
        type_statute: str | None = None,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> list[dict]:
        """Paginate through the consolidated-statute list endpoint.

        Returns a list of ``{"akn_uri": ..., "status": ...}`` dicts.
        """
        params: dict[str, str] = {
            "format": "json",
            "page": str(page),
            "limit": str(limit),
            "langAndVersion": lang_version,
        }
        if published_since:
            params["publishedSince"] = published_since
        if type_statute:
            params["typeStatute"] = type_statute
        if start_year is not None:
            params["startYear"] = str(start_year)
        if end_year is not None:
            params["endYear"] = str(end_year)

        url = f"{self._api_base}/akn/fi/act/statute-consolidated/list"
        data = self._get(url, params=params)
        return json.loads(data)


def _split_norm_id(norm_id: str) -> tuple[str, str]:
    """Split ``{year}/{number}`` or ``{year}-{number}`` into (year, number)."""
    if "/" in norm_id:
        year, number = norm_id.split("/", 1)
    elif "-" in norm_id:
        year, number = norm_id.split("-", 1)
    else:
        raise ValueError(f"Invalid Finnish norm_id format: {norm_id}")
    return year, number
