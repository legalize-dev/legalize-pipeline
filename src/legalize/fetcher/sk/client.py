"""Slov-Lex HTTP client for Slovak Republic legislation.

Two backends:
- API gateway (api-gateway.slov-lex.sk) — JSON catalog + version resolution
- Static site (static.slov-lex.sk) — HTML law text + version history pages

No authentication required for either endpoint.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

_DEFAULT_API = "https://api-gateway.slov-lex.sk"
_DEFAULT_STATIC = "https://static.slov-lex.sk"


class SlovLexClient(HttpClient):
    """HTTP client for the Slovak Slov-Lex legislation portal.

    Endpoints used:
    - GET  api-gateway/vyhladavanie/predpisZbierky/rozsirene  → catalog JSON
    - GET  static/SK/ZZ/{year}/{number}/                      → version history HTML
    - GET  static/SK/ZZ/{year}/{number}/{YYYYMMDD}.portal     → law text HTML fragment
    """

    @classmethod
    def create(cls, country_config: CountryConfig) -> SlovLexClient:
        source = country_config.source or {}
        return cls(
            api_base=source.get("api_base", _DEFAULT_API),
            static_base=source.get("static_base", _DEFAULT_STATIC),
            requests_per_second=source.get("requests_per_second", 2.0),
            request_timeout=source.get("request_timeout", 30),
            max_retries=source.get("max_retries", 5),
        )

    def __init__(
        self,
        api_base: str = _DEFAULT_API,
        static_base: str = _DEFAULT_STATIC,
        requests_per_second: float = 2.0,
        request_timeout: int = 30,
        max_retries: int = 5,
    ) -> None:
        super().__init__(
            base_url=api_base,
            requests_per_second=requests_per_second,
            request_timeout=request_timeout,
            max_retries=max_retries,
        )
        self._api_base = api_base.rstrip("/")
        self._static_base = static_base.rstrip("/")

    # ── Catalog / discovery ──

    def search_catalog(self, *, rows: int = 5000, start: int = 0, **filters: str) -> bytes:
        """Paginated search of the Zbierka zákonov catalog.

        Supported filter params: typPredp, rocnik, cislo, text.
        Returns JSON with numFound, start, docs[].
        """
        params = {"rows": str(rows), "start": str(start)}
        params.update(filters)
        url = f"{self._api_base}/vyhladavanie/predpisZbierky/rozsirene"
        return self._get(url, params=params)

    # ── Version history ──

    def get_version_history(self, year: str, number: str) -> bytes:
        """Fetch the version history page for a law.

        Returns the full HTML page containing effectivenessHistoryItem rows.
        """
        url = f"{self._static_base}/static/SK/ZZ/{year}/{number}/"
        return self._get(url)

    # ── Law text ──

    def get_text(self, norm_id: str) -> bytes:
        """Fetch the current (latest) version text of a law.

        norm_id format: "{year}/{number}" e.g. "1992/460".
        Resolves the latest version IRI via the API, then fetches the
        portal fragment. Falls back to the history page if API fails.
        """
        year, number = norm_id.split("/", 1)
        # Resolve current version IRI
        try:
            import json

            url = f"{self._api_base}/vyhladavanie/predpisZbierky/znenie"
            resp = self._get(url, params={"predpis": f"/SK/ZZ/{year}/{number}"})
            data = json.loads(resp)
            if data.get("docs"):
                iri = data["docs"][0]["iri"]
                # Extract date suffix from IRI: /SK/ZZ/1992/460/20250101
                date_suffix = iri.rsplit("/", 1)[-1]
                return self.get_text_at_version(year, number, date_suffix)
        except Exception:
            logger.debug("Failed to resolve version IRI for %s, using history page", norm_id)

        # Fallback: parse history page to find latest version
        from legalize.fetcher.sk.parser import parse_version_history

        history_html = self.get_version_history(year, number)
        versions = parse_version_history(history_html)
        if versions:
            latest = versions[-1]
            return self.get_text_at_version(year, number, latest["date_suffix"])

        raise ValueError(f"No versions found for {norm_id}")

    def get_text_at_version(self, year: str, number: str, date_suffix: str) -> bytes:
        """Fetch a specific version's text as an HTML portal fragment.

        date_suffix is YYYYMMDD, e.g. "20250101".
        """
        url = f"{self._static_base}/static/SK/ZZ/{year}/{number}/{date_suffix}.portal"
        return self._get(url)

    def get_metadata(self, norm_id: str) -> bytes:
        """Fetch metadata from the API catalog.

        norm_id format: "{year}/{number}".
        Returns JSON from the catalog search filtered by exact citation.
        """
        year, number = norm_id.split("/", 1)
        return self.search_catalog(rows=1, cislo=f"{number}/{year}")

    def get_catalog_entry(self, norm_id: str) -> bytes:
        """Fetch a single catalog entry for a law (convenience wrapper)."""
        return self.get_metadata(norm_id)

    # ── PDF (for source URL) ──

    @staticmethod
    def pdf_url(year: str, number: str, date_suffix: str) -> str:
        """Build the legally-binding PDF URL for a version."""
        return (
            f"{_DEFAULT_STATIC}/static/pdf/SK/ZZ/{year}/{number}"
            f"/ZZ_{year}_{number}_{date_suffix}.pdf"
        )
