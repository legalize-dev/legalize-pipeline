"""Discovery for LDBIS document cards."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

from legalize.fetcher.base import LegislativeClient, NormDiscovery
from legalize.fetcher.mk.client import LDBISClient


class LDBISDiscovery(NormDiscovery):
    """Discover all cards from the official search, or a captured scope file."""

    @classmethod
    def create(cls, source: dict):
        return cls(source or {})

    def __init__(self, source: dict | None = None):
        self.source = source or {}

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        scope_file = self.source.get("scope_file")
        if scope_file:
            yield from (
                line.strip().split("\t", 1)[0]
                for line in Path(scope_file).read_text().splitlines()
                if line.strip()
            )
            return
        if not isinstance(client, LDBISClient):
            raise TypeError("LDBISDiscovery requires LDBISClient")
        yield from client.discover_scope()

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        if not isinstance(client, LDBISClient):
            raise TypeError("LDBISDiscovery requires LDBISClient")
        yield from client.discover_publication_date(target_date)
