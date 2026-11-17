"""Austria RIS (Rechtsinformationssystem) HTTP client.

Data source: https://data.bka.gv.at/ris/api/v2.6/
License: CC BY 4.0 (OGD Austria — https://www.data.gv.at)
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from legalize.fetcher.base import HttpClient

logger = logging.getLogger(__name__)

API_BASE = "https://data.bka.gv.at/ris/api/v2.6"
DOC_BASE = "https://www.ris.bka.gv.at/Dokumente/Bundesnormen"


class RISClient(HttpClient):
    """HTTP client for the Austrian RIS open data API (Bundesrecht konsolidiert).

    Austria's API returns one XML per NOR (paragraph/article). To get a full law,
    we first fetch metadata (by Gesetzesnummer) to find all NOR IDs, then fetch
    each NOR XML and combine them into a single document.
    """

    @classmethod
    def create(cls, country_config):
        """Create RISClient from CountryConfig."""
        source = country_config.source or {}
        return cls(requests_per_second=float(source.get("requests_per_second", 4.0)))

    def __init__(self, requests_per_second: float = 4.0) -> None:
        # www.ris.bka.gv.at sits behind a bot check (Myra) that answers bursts with a
        # 503 "checking your browser" page and then keeps refusing the address for
        # hours. 25 req/s tripped it from GitHub runners on every run from late
        # October 2026, and 20 req/s from a residential address; 4-8 req/s did not.
        super().__init__(requests_per_second=requests_per_second)

    def get_text(self, gesetzesnummer: str, meta_data: bytes | None = None) -> bytes:
        """Fetch all NOR XMLs for a Gesetzesnummer and combine them.

        1. Fetches metadata to find all NOR IDs for this law
        2. Downloads each NOR XML
        3. Wraps them in a combined <combined_nor_documents> element

        Args:
            gesetzesnummer: Stable law identifier, e.g. '10002333'
            meta_data: Pre-fetched metadata bytes (avoids redundant API call).

        Returns:
            Combined XML bytes with all NOR documents.
        """
        if meta_data is None:
            meta_data = self.get_metadata(gesetzesnummer)
        nor_ids = self._extract_nor_ids(meta_data)

        if not nor_ids:
            raise ValueError(f"No NOR documents found for Gesetzesnummer {gesetzesnummer}")

        logger.info("Fetching %d NOR documents for %s", len(nor_ids), gesetzesnummer)

        # Fetch NOR XMLs in parallel (up to 8 concurrent) for speed
        nor_xmls: dict[str, str] = {}

        def _fetch_one(nor_id: str) -> tuple[str, str | None]:
            try:
                xml = self._fetch_nor_xml(nor_id)
                content = xml.decode("utf-8", errors="replace")
                content = content.replace('<?xml version="1.0" encoding="UTF-8"?>', "").strip()
                return (nor_id, content)
            except Exception as exc:
                logger.warning("Could not fetch NOR %s: %s", nor_id, exc)
                return (nor_id, None)

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_fetch_one, nid): nid for nid in nor_ids}
            for future in as_completed(futures):
                nid, content = future.result()
                if content:
                    nor_xmls[nid] = content

        # Each NOR is one paragraph of the law. Combining the ones that did
        # arrive would commit the law with the rest deleted: a fictitious
        # amendment. From October 2026 RIS answered GitHub runners with a 503
        # bot check for most NORs, and that is how laws such as the
        # Bankwesengesetz were published nearly empty. Fail the whole law
        # instead; the daily keeps the day open and retries it.
        missing = [nid for nid in nor_ids if nid not in nor_xmls]
        if missing:
            raise RuntimeError(
                f"Gesetzesnummer {gesetzesnummer}: {len(missing)} of {len(nor_ids)} "
                f"NOR documents could not be fetched (first: {missing[0]})"
            )

        # Reassemble in original order
        parts = ['<?xml version="1.0" encoding="UTF-8"?>']
        parts.append(f'<combined_nor_documents gesetzesnummer="{gesetzesnummer}">')
        for nor_id in nor_ids:
            if nor_id in nor_xmls:
                parts.append(nor_xmls[nor_id])
        parts.append("</combined_nor_documents>")
        return "\n".join(parts).encode("utf-8")

    def get_metadata(self, gesetzesnummer: str) -> bytes:
        """Fetch JSON metadata for all NOR entries of a Gesetzesnummer.

        Paginates to collect ALL NOR documents (some laws have 2000+).
        Returns a combined JSON with all documents.
        """
        all_docs = []
        page = 1

        while True:
            params = {
                "Applikation": "BrKons",
                "Gesetzesnummer": gesetzesnummer,
                "Seitennummer": page,
                "DokumenteProSeite": "OneHundred",
            }
            resp = self._request("GET", f"{API_BASE}/Bundesrecht", params=params)
            data = json.loads(resp.content)
            results = data.get("OgdSearchResult", {}).get("OgdDocumentResults", {})
            docs = results.get("OgdDocumentReference", [])
            if isinstance(docs, dict):
                docs = [docs]

            if not docs:
                break

            all_docs.extend(docs)
            hits_info = results.get("Hits", {})
            total = int(hits_info.get("#text", "0"))
            logger.info(
                "Page %d: %d docs (total: %d/%d)",
                page,
                len(docs),
                len(all_docs),
                total,
            )

            if len(all_docs) >= total:
                break
            page += 1

        # Reconstruct a single response with all docs
        combined = {
            "OgdSearchResult": {
                "OgdDocumentResults": {
                    "Hits": {"#text": str(len(all_docs))},
                    "OgdDocumentReference": all_docs,
                }
            }
        }
        return json.dumps(combined).encode("utf-8")

    def get_page(self, page: int = 1, page_size: int = 100, **filters: str) -> bytes:
        """Generic paginated search against the Bundesrecht endpoint."""
        params: dict[str, str | int] = {
            "Applikation": "BrKons",
            "Seitennummer": page,
            "DokumenteProSeite": "OneHundred",
            **filters,
        }
        return self._get(f"{API_BASE}/Bundesrecht", params=params)

    # ── Internal helpers ──

    def _fetch_nor_xml(self, nor_id: str) -> bytes:
        """Fetch the XML of one NOR document."""
        url = f"{DOC_BASE}/{nor_id}/{nor_id}.xml"
        return self._get(url)

    @staticmethod
    def _extract_nor_ids(meta_data: bytes) -> list[str]:
        """Extract all NOR IDs from a metadata API response."""
        data = json.loads(meta_data)
        docs = (
            data.get("OgdSearchResult", {})
            .get("OgdDocumentResults", {})
            .get("OgdDocumentReference", [])
        )
        if isinstance(docs, dict):
            docs = [docs]
        return [
            d["Data"]["Metadaten"]["Technisch"]["ID"]
            for d in docs
            if isinstance(d, dict)
            and "Data" in d
            and "Metadaten" in d["Data"]
            and "Technisch" in d["Data"]["Metadaten"]
            and "ID" in d["Data"]["Metadaten"]["Technisch"]
        ]
