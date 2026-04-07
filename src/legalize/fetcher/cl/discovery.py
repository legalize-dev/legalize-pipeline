"""Discovery of Chilean norms via the BCN exportarBSimpleMetas CSV API."""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Iterator
from datetime import date
from typing import TYPE_CHECKING

from legalize.fetcher.base import LegislativeClient, NormDiscovery
from legalize.fetcher.cl.client import BCNClient

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Default norm types to include in discovery (skip resoluciones, ordenanzas).
DEFAULT_SCOPE = frozenset(
    {
        "Ley",
        "Decreto con Fuerza de Ley",
        "Decreto Ley",
        "Decreto Supremo",
        "Tratado Internacional",
        "Ley Orgánica Constitucional",
        "Ley de Quórum Calificado",
        "Decreto",
    }
)


class BCNDiscovery(NormDiscovery):
    """Discovers Chilean norms from BCN search API (CSV pagination)."""

    def __init__(self, scope: frozenset[str] | None = None) -> None:
        self._scope = scope or DEFAULT_SCOPE

    @classmethod
    def create(cls, source: dict) -> BCNDiscovery:
        ranks = source.get("ranks")
        scope = frozenset(ranks) if ranks else None
        return cls(scope=scope)

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Paginate through exportarBSimpleMetas to find all norm IDs.

        Yields idNorma values for norms whose type is in scope.
        Iterates each norm type separately to control pagination.

        BCN's nuevo.leychile.cl is intermittently flaky and returns 502/504 on
        certain page boundaries even after the HTTP retries in HttpClient. We
        soft-skip a stuck page after a few attempts so a single bad page does
        not abort a multi-hour bootstrap.
        """
        import requests

        assert isinstance(client, BCNClient)
        seen: set[str] = set()

        for tipo in sorted(self._scope):
            page = 1
            # BCN requires totalitems > 0 to return data.
            # Start with a high estimate; the API caps at the actual total.
            total = "500000"
            consecutive_failures = 0
            max_consecutive_failures = 3
            # BCN's exportarBSimpleMetas silently ignores `npagina` and returns
            # the same first page on every request — see RESEARCH-CHILE.md §7.5.
            # Detect "no new IDs on this page" and move on to the next type
            # after one stale page (allowing for one flaky duplicate page).
            stale_pages = 0
            max_stale_pages = 1

            while True:
                size_before = len(seen)
                try:
                    csv_data = client.search(
                        page=page,
                        items_per_page=100,
                        total=total,
                        tipo_norma=tipo,
                    )
                except requests.HTTPError as exc:
                    consecutive_failures += 1
                    logger.warning(
                        "[%s] Page %d failed (%s); skip attempt %d/%d",
                        tipo,
                        page,
                        exc,
                        consecutive_failures,
                        max_consecutive_failures,
                    )
                    if consecutive_failures >= max_consecutive_failures:
                        logger.error(
                            "[%s] Giving up at page %d after %d consecutive failures",
                            tipo,
                            page,
                            consecutive_failures,
                        )
                        break
                    page += 1
                    continue

                consecutive_failures = 0
                rows = _parse_csv(csv_data)
                if not rows:
                    break

                for row in rows:
                    id_norma = row.get("Identificación de la Norma", "").strip()
                    if id_norma and id_norma not in seen:
                        seen.add(id_norma)
                        yield id_norma

                added_now = len(seen) - size_before
                logger.info(
                    "[%s] Page %d: %d rows (+%d new), %d unique total",
                    tipo,
                    page,
                    len(rows),
                    added_now,
                    len(seen),
                )

                # Stop conditions:
                # 1. fewer rows than requested → end of data
                if len(rows) < 100:
                    break
                # 2. no new unique IDs on this page → BCN is returning stale
                #    duplicates (the API ignores npagina). Move to next type.
                if added_now == 0:
                    stale_pages += 1
                    if stale_pages >= max_stale_pages:
                        logger.info(
                            "[%s] No new norms on page %d — moving to next type",
                            tipo,
                            page,
                        )
                        break
                else:
                    stale_pages = 0
                page += 1

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Yield norms published on a specific date.

        BCN's fc_pb filter doesn't support exact-date queries, so we filter
        by year (fc_de) and match publication dates client-side.
        """
        assert isinstance(client, BCNClient)
        target_str = target_date.isoformat()  # YYYY-MM-DD
        year = str(target_date.year)

        page = 1
        while True:
            csv_data = client.search(
                page=page,
                items_per_page=100,
                total="50000",
                fc_de=year,
            )
            rows = _parse_csv(csv_data)
            if not rows:
                break

            for row in rows:
                pub_date = row.get("Fecha de Publicación", "").strip()
                if pub_date == target_str:
                    id_norma = row.get("Identificación de la Norma", "").strip()
                    if id_norma:
                        yield id_norma

            # Results are sorted newest-first; if we've passed the target
            # date (all dates in this page are older), stop early.
            last_date = rows[-1].get("Fecha de Publicación", "").strip()
            if last_date < target_str:
                break

            if len(rows) < 100:
                break
            page += 1

    def _in_scope(self, tipo_norma: str) -> bool:
        """Check if a norm type is in the configured scope."""
        return tipo_norma in self._scope


def _parse_csv(data: bytes) -> list[dict[str, str]]:
    """Parse CSV bytes from exportarBSimpleMetas into list of dicts.

    BCN CSV uses semicolons, UTF-8 with BOM, and wraps the first column
    header in quotes embedded inside the BOM sequence.
    """
    # BCN returns UTF-8 with BOM (utf-8-sig handles BOM removal)
    for encoding in ("utf-8-sig", "utf-8", "iso-8859-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", errors="replace")

    # Skip empty responses
    text = text.strip()
    if not text:
        return []

    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    rows = list(reader)

    # Normalize column names: BCN wraps the first column in extra quotes
    # after BOM removal, e.g. '"Identificación de la Norma"' instead of
    # 'Identificación de la Norma'. Strip surrounding quotes from all keys.
    normalized: list[dict[str, str]] = []
    for row in rows:
        normalized.append({k.strip('"'): v for k, v in row.items()})
    return normalized
