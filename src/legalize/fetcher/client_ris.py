"""Austria RIS (Rechtsinformationssystem) HTTP client.

Data source: https://data.bka.gv.at/ris/api/v2.6/
License: CC BY 4.0 (OGD Austria — https://www.data.gv.at)
"""
from __future__ import annotations

import time

import httpx

from legalize.fetcher.base import LegislativeClient

API_BASE = "https://data.bka.gv.at/ris/api/v2.6"
DOC_BASE = "https://www.ris.bka.gv.at/Dokumente/Bundesnormen"
RATE_LIMIT_DELAY = 0.5  # seconds between requests


class RISClient(LegislativeClient):
    """HTTP client for the Austrian RIS open data API (Bundesrecht konsolidiert)."""

    def __init__(self) -> None:
        self._http = httpx.Client(timeout=30, follow_redirects=True)

    def get_texto(self, nor_id: str) -> bytes:
        """Fetch the XML of one NOR document (a single paragraph/article).

        nor_id is a NOR* identifier like 'NOR12030057'.
        """
        url = f"{DOC_BASE}/{nor_id}/{nor_id}.xml"
        r = self._http.get(url)
        r.raise_for_status()
        time.sleep(RATE_LIMIT_DELAY)
        return r.content

    def get_metadatos(self, gesetzesnummer: str) -> bytes:
        """Fetch JSON metadata for all NOR entries of a Gesetzesnummer.

        Returns raw JSON bytes of the full API response (OgdSearchResult).
        gesetzesnummer is the stable law identifier, e.g. '10002333'.
        """
        params = {
            "Applikation": "BrKons",
            "Gesetzesnummer": gesetzesnummer,
            "Seitennummer": 1,
            "Dokumentnummer": 100,
        }
        r = self._http.get(f"{API_BASE}/Bundesrecht", params=params)
        r.raise_for_status()
        return r.content

    def get_page(self, page: int = 1, page_size: int = 100, **filters: str) -> bytes:
        """Generic paginated search against the Bundesrecht endpoint."""
        params: dict[str, str | int] = {
            "Applikation": "BrKons",
            "Seitennummer": page,
            "Dokumentnummer": page_size,
            **filters,
        }
        r = self._http.get(f"{API_BASE}/Bundesrecht", params=params)
        r.raise_for_status()
        time.sleep(RATE_LIMIT_DELAY)
        return r.content

    def close(self) -> None:
        self._http.close()
