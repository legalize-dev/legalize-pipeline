"""Norm discovery for the United Kingdom.

Two entry points:
- discover_all: iterate every configured type code via the aggregate Atom
  feed. Yields ``{type}-{year}-{number}`` IDs.
- discover_daily: page the publication log (/update/data.feed) back to the
  day asked for and keep the laws of a tracked type published on it.

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
from datetime import UTC, date, datetime
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
        # The publication log of this run: day each law was last published, and
        # the oldest day it was read back to. See discover_daily.
        self._last_published: dict[str, date] = {}
        self._read_back_to: date | None = None

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
        """Yield the tracked laws whose latest publication fell on ``target_date``.

        The daily fetches a law's current text and dates the commit by this day,
        so a law published again on a later day is left for that day: its text
        is the later one. Days are UTC, as the log writes them.

        The log is read once per run, back to the oldest day asked for —
        ``generic_daily`` asks oldest first, one day at a time. A failed fetch
        raises, so the day is not closed with nothing found.
        """
        if self._read_back_to is None or target_date < self._read_back_to:
            self._last_published = _last_published(client, target_date)
            self._read_back_to = target_date
        for norm_id, day in self._last_published.items():
            if day == target_date:
                yield norm_id


def _last_published(client: LegislationGovUkClient, since: date) -> dict[str, date]:
    """Day of each tracked law's newest event in the publication log, back to ``since``.

    legislation.gov.uk ignores start-date, end-date and results-count on
    /update/data.feed: every request answers with the newest 20 events of the
    whole log, so the only way to a day is to page back to it (about 40 pages
    for a working day in November 2026). New events push entries down while we
    page, which repeats an entry and never skips one.
    """
    last: dict[str, date] = {}
    page = 1
    while True:
        root = etree.fromstring(client.get_update_feed(page))
        # A log that ignored ``page`` too would serve page 1 forever.
        served = root.findtext("leg:page", namespaces=NS)
        if served != str(page):
            raise ValueError(f"update feed served page {served!r} when asked for page {page}")
        entries = root.findall("atom:entry", NS)
        if not entries:
            return last  # the start of the log
        oldest = None
        for entry in entries:
            updated = datetime.fromisoformat(entry.findtext("atom:updated", namespaces=NS))
            day = updated.astimezone(UTC).date()
            oldest = min(oldest or day, day)
            # Changes-only events (/changes/affecting/...) do not match: the text
            # is not republished, only the list of effects.
            norm_id = _entry_to_norm_id(entry.findtext("atom:id", default="", namespaces=NS))
            if norm_id and since <= day and last.get(norm_id, date.min) < day:
                last[norm_id] = day
        if oldest < since:
            return last
        page += 1
