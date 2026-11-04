"""Norm discovery for China's National Database of Laws and Regulations."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date
from typing import TYPE_CHECKING, Any

from legalize.fetcher.base import LegislativeClient, NormDiscovery
from legalize.fetcher.cn.client import CNClient

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class CNDiscovery(NormDiscovery):
    """Discovers legislation IDs from the National Database of Laws and Regulations."""

    @classmethod
    def create(cls, source: dict) -> CNDiscovery:
        """Create a discovery instance from source configuration."""
        scope = source.get("scope", "national")
        return cls(scope=scope)

    def __init__(self, *, scope: str = "national") -> None:
        self.scope = scope

    def discover_all(self, client: LegislativeClient, **kwargs: Any) -> Iterator[str]:
        """Discover all norm identifiers in the catalog.

        Paginates through /law-search/search/list until all rows are exhausted.
        """
        if not isinstance(client, CNClient):
            raise TypeError(f"Expected CNClient, got {type(client)}")

        page_num = 1
        page_size = 50
        total_discovered = 0

        while True:
            logger.info("Discovering norms: page %d (size %d)", page_num, page_size)
            data = client.search_list(page_num=page_num, page_size=page_size)
            if data.get("code") != 200:
                logger.error("Failed to discover norms at page %d: %s", page_num, data.get("msg"))
                break

            rows = data.get("rows", [])
            if not rows:
                break

            total = data.get("total", 0)
            for row in rows:
                bbbs = row.get("bbbs")
                if bbbs:
                    yield bbbs
                    total_discovered += 1

            if total_discovered >= total or len(rows) < page_size:
                break

            page_num += 1

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs: Any
    ) -> Iterator[str]:
        """Discover norms promulgated or effective on a specific date."""
        if not isinstance(client, CNClient):
            raise TypeError(f"Expected CNClient, got {type(client)}")

        date_str = target_date.isoformat()
        # Query by promulgation date range [target_date, target_date]
        data = client.search_list(
            page_num=1,
            page_size=100,
            gbrq=[date_str, date_str],
        )

        if data.get("code") == 200:
            for row in data.get("rows", []):
                bbbs = row.get("bbbs")
                if bbbs:
                    yield bbbs
