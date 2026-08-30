"""Norm discovery for Ireland via Oireachtas API.

Uses the /v1/legislation endpoint to discover enacted Acts:
- discover_all: paginates through the full catalog
- discover_daily: uses last_updated parameter to find recent changes
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date
from typing import TYPE_CHECKING

from legalize.fetcher.base import LegislativeClient, NormDiscovery

if TYPE_CHECKING:
    from legalize.fetcher.ie.client import ISBClient

logger = logging.getLogger(__name__)

_PAGE_SIZE = 50


def _act_to_norm_id(act: dict) -> str | None:
    """Extract norm_id from an Oireachtas API act record.

    Returns 'IE-{year}-act-{number}' or None if missing data.
    """
    year = act.get("actYear")
    number = act.get("actNo")
    if not year or not number:
        return None
    return f"IE-{year}-act-{number}"


class ISBDiscovery(NormDiscovery):
    """Discover Irish Acts via the Oireachtas API."""

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Yield norm IDs for all enacted Acts.

        Paginates through the Oireachtas API catalog.
        """
        isb: ISBClient = client  # type: ignore[assignment]
        skip = 0
        total = 0

        while True:
            page = isb.get_legislation_page(skip=skip, limit=_PAGE_SIZE)

            results = page.get("results", [])
            if not results:
                break

            for item in results:
                bill = item.get("bill", {})
                act = bill.get("act", {})
                if not act:
                    continue

                norm_id = _act_to_norm_id(act)
                if norm_id:
                    total += 1
                    yield norm_id

            bill_count = page.get("head", {}).get("counts", {}).get("billCount", 0)
            skip += _PAGE_SIZE

            if skip >= bill_count:
                break

            logger.info("Discovery progress: %d/%d acts", total, bill_count)

        logger.info("Discovery complete: %d enacted Acts found", total)

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Yield norm IDs for Acts updated on or after target_date.

        Uses the last_updated parameter of the Oireachtas API.
        Paginates through results to avoid truncation at page size.
        """
        isb: ISBClient = client  # type: ignore[assignment]
        skip = 0

        while True:
            page = isb.get_updated_since(target_date.isoformat(), skip=skip, limit=_PAGE_SIZE)

            results = page.get("results", [])
            if not results:
                break

            for item in results:
                bill = item.get("bill", {})
                act = bill.get("act", {})
                if not act:
                    continue

                norm_id = _act_to_norm_id(act)
                if norm_id:
                    yield norm_id

            if len(results) < _PAGE_SIZE:
                break

            skip += _PAGE_SIZE
