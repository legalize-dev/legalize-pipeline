"""Norm discovery for the United Kingdom.

Two entry points:
- discover_all: iterate every configured type code via the aggregate Atom
  feed. Yields ``{type}-{year}-{number}`` IDs.
- discover_daily: poll /update/data.feed filtered to a single date and keep
  only entries whose type is in our tracked set.

Covers both primary legislation (Acts/Measures: ukpga, asp, asc, anaw, mwa,
nia) and secondary legislation (Statutory Instruments: uksi, ssi, wsi, nisr,
nisro). The feed returns an empty page for years before a type existed,
which is cheap (one HTTP request that 200s with zero entries), so we don't
hard-code type→start-year mappings.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import date
from typing import TYPE_CHECKING

from lxml import etree

from legalize.fetcher.base import LegislativeClient, NormDiscovery
from legalize.fetcher.uk.client import NS, LEGISLATION_TYPES

if TYPE_CHECKING:
    from legalize.fetcher.uk.client import LegislationGovUkClient

logger = logging.getLogger(__name__)

# atom:id carries two different shapes depending on the feed:
#   per-year feed:   http://www.legislation.gov.uk/id/ukpga/2018/12
#   update feed:     http://www.legislation.gov.uk/ukpga/1992/12/1993-11-30/data.xml/published/...
# The optional ``id/`` segment covers both.
_ID_RE = re.compile(
    r"legislation\.gov\.uk/(?:id/)?(?P<type>[a-z]+)/(?P<year>\d{4})/(?P<number>\d+)"
)

# The per-year feed bounds. legislation.gov.uk hosts ukpga back to 1266 but
# modern schema coverage is post-1988. We still iterate from 1801 so that
# ``discover_all`` captures every Act of any vintage — empty years are cheap.
_MIN_YEAR = 1801


def _entry_to_norm_id(entry_id: str) -> str | None:
    """Extract ``{type}-{year}-{number}`` from an atom:id URI."""
    match = _ID_RE.search(entry_id)
    if not match:
        return None
    type_code = match.group("type")
    if type_code not in LEGISLATION_TYPES:
        return None
    return f"{type_code}-{int(match.group('year'))}-{int(match.group('number'))}"


class LegislationGovUkDiscovery(NormDiscovery):
    """Discover UK legislation via the legislation.gov.uk Atom feeds."""

    def __init__(
        self,
        types: tuple[str, ...] = LEGISLATION_TYPES,
        min_year: int = _MIN_YEAR,
        max_year: int | None = None,
    ) -> None:
        self._types = types
        self._min_year = min_year
        self._max_year = max_year

    @classmethod
    def create(cls, source: dict) -> LegislationGovUkDiscovery:
        src = source or {}
        return cls(
            types=tuple(src.get("types", LEGISLATION_TYPES)),
            min_year=int(src.get("min_year", _MIN_YEAR)),
            max_year=src.get("max_year"),
        )

    # ─── Required contract ──────────────────────────────────────

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Yield every norm ID across every configured type.

        Uses the aggregate Atom feed ``/{type}/data.feed?page=N&results-count=100``
        which returns all norms of a type across all years — much faster than
        iterating per-year feeds (the aggregate feed skips the dozens of
        empty historical years that each type has to its name).
        """
        uk: LegislationGovUkClient = client  # type: ignore[assignment]
        total = 0

        for type_code in self._types:
            type_total = 0
            page = 1
            while True:
                try:
                    body = uk.get_type_feed(type_code, page=page)
                except Exception as exc:
                    logger.warning("Discovery failed for %s page %d: %s", type_code, page, exc)
                    break
                try:
                    root = etree.fromstring(body)
                except etree.XMLSyntaxError:
                    break
                entries = root.findall("atom:entry", NS)
                if not entries:
                    break
                for entry in entries:
                    eid = entry.find("atom:id", NS)
                    if eid is None or not eid.text:
                        continue
                    norm_id = _entry_to_norm_id(eid.text)
                    if norm_id:
                        type_total += 1
                        total += 1
                        yield norm_id
                if len(entries) < 100:
                    break
                page += 1
            logger.info("Discovered %d %s norms", type_total, type_code)
        logger.info("UK discovery complete: %d laws across %d types", total, len(self._types))

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Yield norm IDs touched on a specific date (publication log).

        The update feed lists every publication/revision event. We filter to
        the ones whose ``<atom:id>`` points at a law of a tracked type and
        whose ``<atom:updated>`` matches the target date.
        """
        uk: LegislationGovUkClient = client  # type: ignore[assignment]
        try:
            body = uk.get_update_feed(target_date)
        except Exception as exc:
            logger.warning("Update feed fetch failed for %s: %s", target_date, exc)
            return
        try:
            root = etree.fromstring(body)
        except etree.XMLSyntaxError:
            return
        seen: set[str] = set()
        for entry in root.findall(".//atom:entry", NS):
            # The update feed points at provision-level URIs; strip to the law.
            eid = entry.find("atom:id", NS)
            if eid is None or not eid.text:
                continue
            norm_id = _entry_to_norm_id(eid.text)
            if not norm_id or norm_id in seen:
                continue
            seen.add(norm_id)
            yield norm_id
