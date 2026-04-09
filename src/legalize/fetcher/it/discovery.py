"""Norm discovery for Italian legislation via Normattiva API.

Discovery uses ricerca/semplice with filtriMap to enumerate all acts by type.
Daily uses ricerca/aggiornati to find recently modified acts.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date
from typing import TYPE_CHECKING

from legalize.fetcher.base import LegislativeClient, NormDiscovery

if TYPE_CHECKING:
    from legalize.fetcher.it.client import NormattivaClient

logger = logging.getLogger(__name__)

# Act types to include in v1 scope (Republican era + key historical)
V1_ACT_TYPES = [
    "COS",  # Costituzione (1)
    "PLC",  # Legge Costituzionale (49)
    "PLE",  # Legge (32,637)
    "PLL",  # Decreto Legislativo (2,894)
    "PDL",  # Decreto-Legge (3,846)
    "PPR",  # DPR (47,756)
    "PCM_DPC",  # DPCM (357)
    "DCT",  # Decreto (2,530)
]

# Maximum items per page in the API
MAX_PER_PAGE = 100


class NormattivaDiscovery(NormDiscovery):
    """Discover Italian legislative acts via Normattiva search API."""

    def __init__(self, act_types: list[str] | None = None) -> None:
        self._act_types = act_types or V1_ACT_TYPES

    @classmethod
    def create(cls, source: dict) -> NormattivaDiscovery:
        act_types = source.get("act_types", V1_ACT_TYPES)
        return cls(act_types=act_types)

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Discover all norm IDs in scope.

        Iterates through each act type, paginating through all results.
        Yields codiceRedazionale identifiers.
        """
        nclient: NormattivaClient = client  # type: ignore[assignment]
        seen: set[str] = set()

        for tipo in self._act_types:
            logger.info("Discovering acts of type %s", tipo)
            yield from self._discover_type(nclient, tipo, seen)

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Discover acts modified on a specific date.

        Uses ricerca/aggiornati with the target date as a 24-hour window.
        """
        nclient: NormattivaClient = client  # type: ignore[assignment]

        date_from = f"{target_date.isoformat()}T00:00:00.000Z"
        date_to = f"{target_date.isoformat()}T23:59:59.000Z"

        try:
            result = nclient.search_updated(date_from, date_to)
        except Exception:
            logger.error("Failed to fetch updated acts for %s", target_date, exc_info=True)
            return

        acts = result.get("listaAtti", [])
        logger.info("Found %d updated acts for %s", len(acts), target_date)

        for act in acts:
            codice = act.get("codiceRedazionale", "")
            if codice:
                yield codice

    def _discover_type(self, client: NormattivaClient, tipo: str, seen: set[str]) -> Iterator[str]:
        """Paginate through all acts of a given type."""
        page = 1
        total_yielded = 0

        while True:
            try:
                result = client.search_simple(
                    text="*",
                    order="vecchio",
                    page=page,
                    per_page=MAX_PER_PAGE,
                    filters={"codice_tipo_provvedimento": tipo},
                )
            except Exception:
                logger.error("Search failed for type %s page %d", tipo, page, exc_info=True)
                break

            acts = result.get("listaAtti", [])
            if not acts:
                break

            for act in acts:
                codice = act.get("codiceRedazionale", "")
                if codice and codice not in seen:
                    seen.add(codice)
                    yield codice
                    total_yielded += 1

            total_pages = result.get("numeroPagine", 1)
            if page >= total_pages:
                break
            page += 1

        logger.info("Type %s: yielded %d acts", tipo, total_yielded)
