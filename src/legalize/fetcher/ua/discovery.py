"""Ukraine norm discovery — zakon.rada.gov.ua type lists + data.rada.gov.ua.

Discovery uses type lists from ``zakon.rada.gov.ua/laws/main/t{N}.txt``
(UTF-8, one nreg per line) combined with the ``perv1.txt`` curated list
from ``data.rada.gov.ua`` (CP1251, different nreg format).

Which type lists to fetch is configurable via ``config.yaml``::

    ua:
      source:
        type_lists: ["t1", "t3", "t4", "t5", "t21", "t216"]
        include_perv1: true

Daily discovery uses the ``/laws/main/r/page{N}.json`` endpoint.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import date
from typing import TYPE_CHECKING

from legalize.fetcher.base import LegislativeClient, NormDiscovery

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Default type lists: laws, codes, constitution
_DEFAULT_TYPE_LISTS = ["t1", "t21", "t216"]


def nreg_to_identifier(nreg: str) -> str:
    """Convert an official nreg to a filesystem-safe identifier.

    ``254к/96-ВР`` → ``254к-96-вр``  (lowercase, ``/`` replaced with ``-``).
    """
    return nreg.lower().replace("/", "-")


def parse_discovery_list(data: bytes) -> Iterator[str]:
    """Parse a CP1251-encoded discovery list (perv*.txt) into nreg strings."""
    text = data.decode("cp1251", errors="replace")
    for line in text.splitlines():
        nreg = line.strip()
        if nreg:
            yield nreg


def parse_type_list(data: bytes) -> Iterator[str]:
    """Parse a UTF-8 type list (t*.txt) into nreg strings."""
    text = data.decode("utf-8", errors="replace")
    for line in text.splitlines():
        nreg = line.strip()
        if nreg:
            yield nreg


class RadaDiscovery(NormDiscovery):
    """Discover Ukrainian norms from type lists and open data lists."""

    def __init__(
        self,
        *,
        type_lists: list[str] | None = None,
        include_perv1: bool = True,
    ) -> None:
        self._type_lists = type_lists or _DEFAULT_TYPE_LISTS
        self._include_perv1 = include_perv1

    @classmethod
    def create(cls, source: dict) -> RadaDiscovery:
        return cls(
            type_lists=source.get("type_lists", _DEFAULT_TYPE_LISTS),
            include_perv1=source.get("include_perv1", True),
        )

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Yield nregs from configured type lists and optionally perv1.txt.

        Deduplicates across all sources.  Type lists come from
        ``zakon.rada.gov.ua/laws/main/t{N}.txt`` (UTF-8).  The perv1.txt
        list from ``data.rada.gov.ua`` uses a different nreg format and
        CP1251 encoding.
        """
        seen: set[str] = set()
        total = 0

        # Fetch from each type list
        for type_id in self._type_lists:
            try:
                data = client.get_type_list(type_id)  # type: ignore[attr-defined]
                count = 0
                for nreg in parse_type_list(data):
                    if nreg not in seen:
                        seen.add(nreg)
                        yield nreg
                        count += 1
                total += count
                logger.info("Discovered %d norms from %s.txt", count, type_id)
            except Exception:
                logger.error("Failed to fetch type list %s.txt", type_id, exc_info=True)

        # Optionally include perv1.txt (different nreg format, CP1251)
        if self._include_perv1:
            try:
                data = client.get_discovery_list("perv1.txt")  # type: ignore[attr-defined]
                count = 0
                for nreg in parse_discovery_list(data):
                    if nreg not in seen:
                        seen.add(nreg)
                        yield nreg
                        count += 1
                total += count
                logger.info("Discovered %d additional norms from perv1.txt", count)
            except Exception:
                logger.error("Failed to fetch perv1.txt", exc_info=True)

        logger.info("Total discovered: %d unique norms", total)

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Yield nregs of laws updated on *target_date*.

        Uses ``/laws/main/r/page{N}.json`` which returns recently updated
        documents.  Each entry has ``orgdat`` as an int in ``YYYYMMDD`` format.
        We paginate until entries are older than target_date.
        """
        target_int = int(target_date.strftime("%Y%m%d"))
        seen: set[str] = set()
        page = 1

        while True:
            raw = client.get_recent_page(page)  # type: ignore[attr-defined]
            data = json.loads(raw)
            entries = data.get("list", [])

            if not entries:
                break

            found_any = False
            for entry in entries:
                orgdat = entry.get("orgdat", 0)
                nreg = entry.get("nreg", "")

                if not nreg:
                    continue

                if orgdat == target_int and nreg not in seen:
                    seen.add(nreg)
                    yield nreg
                    found_any = True
                elif orgdat < target_int:
                    logger.info(
                        "Daily discovery: %d norms on %s (page %d)",
                        len(seen),
                        target_date,
                        page,
                    )
                    return

            if not found_any and page > 10:
                break
            page += 1

        logger.info("Daily discovery: %d norms on %s", len(seen), target_date)
