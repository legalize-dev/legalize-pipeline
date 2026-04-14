"""Norm discovery for Slovakia via the Slov-Lex API gateway.

The API's /vyhladavanie/predpisZbierky/rozsirene endpoint returns a
Solr-backed paginated catalog of all laws. Supports up to 5,000 rows
per request, so the full ~26K catalog requires only 6 requests.

Norm IDs are "{year}/{number}" strings derived from the IRI field.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import date
from typing import TYPE_CHECKING

from legalize.fetcher.base import LegislativeClient, NormDiscovery

if TYPE_CHECKING:
    from legalize.fetcher.sk.client import SlovLexClient

logger = logging.getLogger(__name__)

_PAGE_SIZE = 5000


class SlovLexDiscovery(NormDiscovery):
    """Discover Slovak laws via the Slov-Lex API gateway catalog."""

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Yield all norm IDs from the Zbierka zákonov catalog.

        Paginates through the API in chunks of 5,000. Each doc's IRI
        has the form /SK/ZZ/{year}/{number}/{date} — we extract
        year/number as the stable norm ID.

        Yields: "{year}/{number}" strings, e.g. "1992/460".
        """
        slovlex: SlovLexClient = client  # type: ignore[assignment]
        start = 0
        total = None
        seen: set[str] = set()

        while True:
            raw = slovlex.search_catalog(rows=_PAGE_SIZE, start=start)
            data = json.loads(raw)

            if total is None:
                total = data.get("numFound", 0)
                logger.info("Catalog contains %d laws", total)

            docs = data.get("docs", [])
            if not docs:
                break

            for doc in docs:
                norm_id = _iri_to_norm_id(doc.get("iri", ""))
                if norm_id and norm_id not in seen:
                    seen.add(norm_id)
                    yield norm_id

            start += len(docs)
            logger.info("Discovery: %d/%d (yielded %d unique)", start, total, len(seen))

            if start >= total:
                break

        logger.info("Discovery complete: %d unique laws", len(seen))

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Yield norm IDs published on a specific date.

        Queries the catalog filtering by year, then checks each doc's
        vyhlaseny (promulgation) date against the target.
        """
        slovlex: SlovLexClient = client  # type: ignore[assignment]
        target_str = target_date.isoformat()
        year = str(target_date.year)
        start = 0
        seen: set[str] = set()

        while True:
            raw = slovlex.search_catalog(rows=_PAGE_SIZE, start=start, rocnik=year)
            data = json.loads(raw)
            docs = data.get("docs", [])
            if not docs:
                break

            for doc in docs:
                # vyhlaseny is "2024-12-27T00:00:00Z"
                pub = (doc.get("vyhlaseny") or "")[:10]
                if pub == target_str:
                    norm_id = _iri_to_norm_id(doc.get("iri", ""))
                    if norm_id and norm_id not in seen:
                        seen.add(norm_id)
                        yield norm_id

            start += len(docs)
            total = data.get("numFound", 0)
            if start >= total:
                break

        logger.info("Daily discovery for %s: %d laws", target_date, len(seen))


def _iri_to_norm_id(iri: str) -> str | None:
    """Extract year/number from an IRI path.

    "/SK/ZZ/2024/401/20250301" → "2024/401"
    "/SK/ZZ/1992/460/19921001" → "1992/460"
    """
    parts = iri.strip("/").split("/")
    # Expected: SK/ZZ/{year}/{number}/{date_suffix}
    if len(parts) >= 4 and parts[0] == "SK" and parts[1] == "ZZ":
        return f"{parts[2]}/{parts[3]}"
    return None
