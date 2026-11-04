"""Discovery of Uruguayan norms via IMPO number range iteration.

IMPO has no catalog/search endpoint. Discovery works by iterating through
sequential law numbers and checking which ones exist. Law numbers run from
~1 (1826) to ~20500 (2026), but post-1935 laws (9500+) are most reliable.

IMPORTANT: IMPO requires the correct year in the URL. There is no redirect
or fallback — a wrong year returns an HTML login page (treated as not found).
We use an approximate number→year mapping to estimate the year, then try
a few candidates around that estimate.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from legalize.fetcher.base import LegislativeClient, NormDiscovery
from legalize.fetcher.uy.client import IMPOClient

logger = logging.getLogger(__name__)

# Collections to iterate during full discovery
DEFAULT_COLLECTIONS = ("leyes", "decretos-ley", "constitucion")

# Approximate law number → year mapping (based on real IMPO data).
# Used to estimate the year for a given law number.
# Format: (law_number, year) — sorted by law_number.
_NUMBER_YEAR_LANDMARKS = (
    (1, 1826),
    (1000, 1870),
    (3000, 1905),
    (5000, 1914),
    (7000, 1919),
    (9000, 1932),
    (10000, 1941),
    (11000, 1948),
    (12000, 1953),
    (13000, 1960),
    (14000, 1971),
    (15000, 1980),
    (16000, 1989),
    (17000, 1998),
    (18000, 2006),
    (19000, 2012),
    (19500, 2017),
    (20000, 2021),
    (20200, 2023),
    (20400, 2025),
    (20500, 2026),
)


def _estimate_year(law_number: int) -> int:
    """Estimate the year for a law number using linear interpolation."""
    if law_number <= _NUMBER_YEAR_LANDMARKS[0][0]:
        return _NUMBER_YEAR_LANDMARKS[0][1]
    if law_number >= _NUMBER_YEAR_LANDMARKS[-1][0]:
        return _NUMBER_YEAR_LANDMARKS[-1][1]

    for i in range(len(_NUMBER_YEAR_LANDMARKS) - 1):
        n0, y0 = _NUMBER_YEAR_LANDMARKS[i]
        n1, y1 = _NUMBER_YEAR_LANDMARKS[i + 1]
        if n0 <= law_number <= n1:
            # Linear interpolation
            frac = (law_number - n0) / (n1 - n0)
            return int(y0 + frac * (y1 - y0))

    return _NUMBER_YEAR_LANDMARKS[-1][1]


def _year_candidates(law_number: int) -> list[int]:
    """Return a list of candidate years to try for a law number.

    The landmark table is dense enough that the estimate is usually
    correct or off by ±1, so we try just 3 years (estimate, ±1) by
    default. The discovery loop also remembers the previous successful
    year and tries it first, which catches runs of consecutive laws
    in the same year much faster than a fixed candidate list.
    """
    est = _estimate_year(law_number)
    return [est, est + 1, est - 1]


class IMPODiscovery(NormDiscovery):
    """Discovers Uruguayan norms by iterating number ranges on IMPO."""

    @classmethod
    def create(cls, source: dict) -> IMPODiscovery:
        collections = source.get("collections", list(DEFAULT_COLLECTIONS))
        law_number_max = source.get("law_number_max", 20500)
        law_number_start = source.get("law_number_start", 9000)
        catalog_path = source.get("catalog_path")
        decretos_ley_catalog_path = source.get("decretos_ley_catalog_path")
        # generic_fetch_all injects the data dir as `cache_dir`; that's where
        # `scripts/build_uy_catalog.py` writes the pre-built catalogs by default.
        if catalog_path is None and source.get("cache_dir"):
            catalog_path = str(Path(source["cache_dir"]) / "catalog.json")
        if decretos_ley_catalog_path is None and source.get("cache_dir"):
            decretos_ley_catalog_path = str(Path(source["cache_dir"]) / "decretos-ley.catalog.json")
        return cls(
            collections=collections,
            law_number_max=law_number_max,
            law_number_start=law_number_start,
            catalog_path=catalog_path,
            decretos_ley_catalog_path=decretos_ley_catalog_path,
        )

    def __init__(
        self,
        collections: list[str] | None = None,
        law_number_max: int = 20500,
        law_number_start: int = 9000,
        catalog_path: str | None = None,
        decretos_ley_catalog_path: str | None = None,
    ) -> None:
        self._collections = collections or list(DEFAULT_COLLECTIONS)
        self._law_number_max = law_number_max
        # Pre-1935 laws (numbers 1..~9500) are mostly unindexed in IMPO and
        # waste hours of HTTP probes for almost no hits. Default start is
        # 9000 — the dense post-1935 range. Override via source.law_number_start.
        self._law_number_start = law_number_start
        # If a pre-built catalog exists (created by
        # `scripts/build_uy_catalog.py`), use it instead of probing IMPO
        # one number at a time. The catalog is a JSON list of norm IDs.
        self._catalog_path = catalog_path
        self._decretos_ley_catalog_path = decretos_ley_catalog_path

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Yield norm IDs for all collections.

        For 'leyes': iterates numbers 1 to law_number_max, trying
        estimated years based on the number→year mapping.

        For 'constitucion': yields the single known entry.
        For 'decretos-ley': iterates the 1973-1985 range.
        """
        assert isinstance(client, IMPOClient)

        for collection in self._collections:
            if collection == "constitucion":
                yield from self._discover_constitucion(client)
            elif collection == "leyes":
                yield from self._discover_leyes(client, **kwargs)
            elif collection == "decretos-ley":
                yield from self._discover_decretos_ley(client, **kwargs)
            else:
                logger.warning("Unknown collection: %s", collection)

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Check recent law numbers above the last known max.

        Tries numbers from last_known+1 to last_known+100,
        using target_date.year and the previous year as candidates.
        """
        assert isinstance(client, IMPOClient)
        start = kwargs.get("last_known_number", self._law_number_max)
        year = target_date.year

        for num in range(start + 1, start + 100):
            for y in (year, year - 1):
                norm_id = f"leyes/{num}-{y}"
                data = client.get_text(norm_id)
                if data:
                    logger.info("Found new law: %s", norm_id)
                    yield norm_id
                    break

    def _discover_constitucion(self, client: IMPOClient) -> Iterator[str]:
        """Yield the single Constitution entry."""
        norm_id = "constitucion/1967-1967"
        data = client.get_text(norm_id)
        if data:
            yield norm_id

    def _discover_leyes(self, client: IMPOClient, **kwargs) -> Iterator[str]:
        """Iterate law numbers, trying estimated year candidates for each.

        Optimization: laws are usually published in monotonic year order,
        so the previous successful year is by far the best first guess
        for the next number. We remember it and try it before the
        landmark-based estimate, which collapses runs of consecutive
        laws to a single HTTP probe per number.

        Fast path: if a pre-built catalog file is available (created by
        `scripts/build_uy_catalog.py`), it is used directly with no HTTP
        probing at all.
        """
        if self._catalog_path and Path(self._catalog_path).exists():
            try:
                cached = json.loads(Path(self._catalog_path).read_text(encoding="utf-8"))
                logger.info(
                    "Loaded %d laws from catalog cache at %s",
                    len(cached),
                    self._catalog_path,
                )
                yield from cached
                return
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(
                    "Catalog at %s unreadable, falling back to probing: %s",
                    self._catalog_path,
                    exc,
                )

        limit = kwargs.get("limit", self._law_number_max)
        start = kwargs.get("start", self._law_number_start)
        found = 0
        last_year: int | None = None

        for num in range(start, min(limit + 1, self._law_number_max + 1)):
            candidates = _year_candidates(num)
            if last_year is not None and last_year not in candidates:
                candidates = [last_year, *candidates]
            elif last_year is not None:
                # Move last_year to the front for sticky-success behavior
                candidates = [last_year, *(c for c in candidates if c != last_year)]

            for year in candidates:
                norm_id = f"leyes/{num}-{year}"
                data = client.get_text(norm_id)
                if data:
                    found += 1
                    last_year = year
                    if found % 100 == 0:
                        logger.info("Laws discovered so far: %d (at number %d)", found, num)
                    yield norm_id
                    break  # found the right year, move to next number

    def _discover_decretos_ley(self, client: IMPOClient, **kwargs) -> Iterator[str]:
        """Iterate decreto-ley numbers (1973-1985 period).

        Fast path: read the pre-built catalog at
        `<data_dir>/decretos-ley.catalog.json` if it exists, written by
        `scripts/build_uy_catalog.py --collection decretos-ley`.
        """
        if self._decretos_ley_catalog_path and Path(self._decretos_ley_catalog_path).exists():
            try:
                cached = json.loads(
                    Path(self._decretos_ley_catalog_path).read_text(encoding="utf-8")
                )
                logger.info(
                    "Loaded %d decretos-ley from catalog cache at %s",
                    len(cached),
                    self._decretos_ley_catalog_path,
                )
                yield from cached
                return
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(
                    "Catalog at %s unreadable, falling back to probing: %s",
                    self._decretos_ley_catalog_path,
                    exc,
                )

        limit = kwargs.get("limit", 16000)
        start = kwargs.get("start", 14000)

        for num in range(start, limit + 1):
            for year in range(1973, 1986):
                norm_id = f"decretos-ley/{num}-{year}"
                data = client.get_text(norm_id)
                if data:
                    yield norm_id
                    break  # found the right year, move to next number
