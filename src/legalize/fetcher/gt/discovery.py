from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from legalize.fetcher.base import LegislativeClient, NormDiscovery


class GTFixtureDiscovery(NormDiscovery):
    """Fixture-backed discovery for initial Guatemala integration."""

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        yield "decreto-57-2008"
        yield "decreto-13-2013"

    def discover_daily(
        self,
        client: LegislativeClient,
        target_date: date,
        **kwargs,
    ) -> Iterator[str]:
        if target_date == date(2013, 11, 12):
            yield "decreto-13-2013"
