"""Discovery of Finnish statutes via the Finlex open data API.

Bootstrap: paginates through the ``statute-consolidated/list`` endpoint
(10 items per page, ~4,250 pages for all Finnish consolidated statutes).

Daily updates: uses the ``publishedSince`` query parameter to find statutes
that have been added or modified since the last run.

Norm IDs use ``{year}/{number}`` format (e.g. ``1999/731``).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import date

from legalize.fetcher.base import LegislativeClient, NormDiscovery
from legalize.fetcher.fi.client import FinlexClient

logger = logging.getLogger(__name__)

# Pattern to extract year and number from Finlex AKN URIs.
# Example: .../statute-consolidated/1999/731/fin@20180817
_URI_PATTERN = re.compile(r"/statute-consolidated/(\d{4})/(\d+)/")

# Items per page for the list endpoint (API maximum is 10).
_PAGE_SIZE = 10


class FinlexDiscovery(NormDiscovery):
    """Discovers Finnish consolidated statutes via the Finlex API.

    Bootstrap: ~4,250 paginated requests (10 items/page × ~42,500 statutes).
    Daily: 1-2 paginated requests using publishedSince filter.
    """

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Yield all consolidated statute IDs as ``{year}/{number}``."""
        assert isinstance(client, FinlexClient)

        page = 1
        total = 0
        seen: set[str] = set()

        while True:
            items = client.list_statutes(page=page, limit=_PAGE_SIZE)
            if not items:
                break

            for item in items:
                norm_id = _extract_norm_id(item.get("akn_uri", ""))
                if norm_id and norm_id not in seen:
                    seen.add(norm_id)
                    total += 1
                    yield norm_id

            if len(items) < _PAGE_SIZE:
                break

            page += 1
            if page % 500 == 0:
                logger.info("Discovery progress: page %d, %d statutes so far", page, total)

        logger.info("Discovery complete: %d unique statutes across %d pages", total, page)

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Yield IDs of statutes modified since *target_date*.

        Uses the ``publishedSince`` query parameter, which takes an ISO
        8601 *instant* — the offset is required. We query for anything
        published since midnight UTC of the target date.

        Finlex used to accept a naive ``YYYY-MM-DDTHH:MM:SS`` and now
        answers 400 to it, which turned every day of the daily into an
        error and Finland into a repo that had not moved since August.
        """
        assert isinstance(client, FinlexClient)

        since = f"{target_date.isoformat()}T00:00:00Z"
        page = 1
        total = 0
        seen: set[str] = set()

        while True:
            items = client.list_statutes(
                page=page,
                limit=_PAGE_SIZE,
                published_since=since,
            )
            if not items:
                break

            for item in items:
                norm_id = _extract_norm_id(item.get("akn_uri", ""))
                if norm_id and norm_id not in seen:
                    seen.add(norm_id)
                    total += 1
                    yield norm_id

            if len(items) < _PAGE_SIZE:
                break
            page += 1

        logger.info("Daily discovery for %s: %d statutes", target_date, total)


def _extract_norm_id(akn_uri: str) -> str | None:
    """Extract ``{year}/{number}`` from a Finlex AKN URI.

    Example input:
        https://opendata.finlex.fi/.../statute-consolidated/2025/51/fin@
    Returns: ``"2025/51"``
    """
    match = _URI_PATTERN.search(akn_uri)
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}"
