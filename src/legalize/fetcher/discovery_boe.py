"""BOE-specific norm discovery — wraps sumario.py and catalogo.py.

Implements the NormDiscovery interface for Spain's BOE.
The existing sumario.py and catalogo.py modules do the real work.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from legalize.fetcher.base import LegislativeClient, NormDiscovery


class BOEDiscovery(NormDiscovery):
    """Discover norms via BOE sumarios and catalog API."""

    def __init__(self, config=None):
        self.config = config

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Discover all norms via BOE catalog API."""
        from legalize.fetcher.catalogo import iter_normas_from_catalog
        yield from iter_normas_from_catalog(client, self.config)

    def discover_daily(self, client: LegislativeClient, target_date: date, **kwargs) -> Iterator[str]:
        """Discover norms from a BOE daily sumario."""
        from legalize.fetcher.sumario import parse_sumario
        scope = kwargs.get("scope", self.config.scope if self.config else None)
        xml_data = client.get_sumario(target_date)
        dispositions = parse_sumario(xml_data, scope)
        for disp in dispositions:
            yield disp.id_norma
