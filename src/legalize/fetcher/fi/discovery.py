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
from datetime import date, timedelta

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
    Daily: one pagination per date in the window (see discover_daily).
    """

    def __init__(self) -> None:
        # "Everything modified on or after D", per date. generic_daily walks
        # the window forward and each date is needed twice — once as the day
        # itself, once as the previous day's upper bound — so caching turns
        # two paginations per day into one.
        self._since_cache: dict[date, list[str]] = {}

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

    def _ids_since(self, client: FinlexClient, since: date) -> list[str]:
        """Every statute Finlex reports as modified on or after *since*."""
        cached = self._since_cache.get(since)
        if cached is not None:
            return cached

        stamp = f"{since.isoformat()}T00:00:00Z"
        page = 1
        ids: list[str] = []
        seen: set[str] = set()

        while True:
            items = client.list_statutes(page=page, limit=_PAGE_SIZE, published_since=stamp)
            if not items:
                break

            for item in items:
                norm_id = _extract_norm_id(item.get("akn_uri", ""))
                if norm_id and norm_id not in seen:
                    seen.add(norm_id)
                    ids.append(norm_id)

            if len(items) < _PAGE_SIZE:
                break
            page += 1

        # Only this date and the ones after it can still be asked for.
        self._since_cache = {d: v for d, v in self._since_cache.items() if d >= since}
        self._since_cache[since] = ids
        return ids

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Yield statutes whose most recent modification falls on *target_date*.

        ``publishedSince`` is a cumulative lower bound — everything modified
        from that instant onwards, not what changed that day. Finlex offers no
        upper bound: publishedBefore, publishedUntil, publishedTo, dateTo and
        every other candidate are accepted and then silently ignored, and the
        list items carry nothing but an AKN URI and a status, so there is no
        date to bound on client-side either. The day's set is therefore the
        difference between two cumulative queries.

        Without that difference a 9-day window asked for "everything since day
        one" nine times over — 6,394 statute fetches for 857 distinct statutes
        — and ran the job past its 55-minute cap. Worse than slow: each day
        re-rendered the same statute with that day's date in ``last_updated``
        (transformer.frontmatter), so one statute would have been committed
        once per day of the window, each time under a different date.

        A statute modified twice inside the window is yielded once, on the day
        of its latest modification.
        """
        assert isinstance(client, FinlexClient)

        on_or_after = self._ids_since(client, target_date)
        later = set(self._ids_since(client, target_date + timedelta(days=1)))

        total = 0
        for norm_id in on_or_after:
            if norm_id not in later:
                total += 1
                yield norm_id

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
