"""Norm discovery for Greek Government Gazette (ΦΕΚ) Issue Α'.

Walks the official Εθνικό Τυπογραφείο catalog year by year via the
``simpleSearch`` endpoint of ``searchetv99.azurewebsites.net``. The API
returns up to 12,000 items per call (verified 2026-04-08), so a single
year's worth of Α' issues (≈250-400 items) always fits in one page —
no pagination needed.

Yields stable norm_ids of the form ``FEK-A-{N}-{Y}`` (e.g.
``FEK-A-167-2013``) ordered chronologically (year ascending, document
number ascending within each year). The chronological order matters
for Phase 2 amendment processing: a law can only be modified by
documents published *after* it, so iterating in order means amending
laws appear after the laws they modify.

The daily incremental flow uses the same simpleSearch endpoint with
``datePublished`` filtering — wired in ``discover_daily``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date

from legalize.fetcher.base import LegislativeClient, NormDiscovery
from legalize.fetcher.gr.client import GreekClient, make_norm_id

logger = logging.getLogger(__name__)

# Default scope: Issue group Α' (laws, presidential decrees, treaties).
# Other groups (Β=ministerial decisions, Γ=appointments, Δ=urban planning,
# ...) are out of scope for v1 and live in different repositories.
_DEFAULT_ISSUE_GROUP = 1

# Year range. The API has data from 1833 in principle but text-layer
# PDFs only become reliable from 2000 onwards (verified during the
# previous bootstrap), and the National Printing House continues
# publishing every weekday. We start at 2000 and let the upper bound
# float — anything beyond ``today.year`` simply returns 0 hits and is
# skipped.
_DEFAULT_YEAR_FROM = 2000
_DEFAULT_YEAR_TO_CAP = 2030  # safety cap; real upper bound is current year


class GreekDiscovery(NormDiscovery):
    """Discovers Greek FEK Α' issues via the official searchetv99 API.

    Implementation:

    * ``discover_all`` walks ``year_from`` to ``year_to`` (inclusive),
      issuing one ``simpleSearch`` per year and yielding the resulting
      norm_ids in document-number order. The API does not require
      pagination at this scope (≈250-400 items per year fit in one page).

    * ``discover_daily`` filters by ``datePublished`` to fetch only
      documents published on or after a target date — used by the
      daily CI cron.
    """

    def discover_all(
        self,
        client: LegislativeClient,
        *,
        issue_group: int = _DEFAULT_ISSUE_GROUP,
        year_from: int = _DEFAULT_YEAR_FROM,
        year_to: int | None = None,
        **kwargs,
    ) -> Iterator[str]:
        """Yield every FEK Α' norm_id in the configured year range."""
        if not isinstance(client, GreekClient):
            raise TypeError(f"GreekDiscovery requires GreekClient, got {type(client).__name__}")

        # If no upper bound is given, walk through *next year* as well so
        # late-December items aren't missed when the bootstrap runs in
        # January. The cap protects against runaway loops.
        upper = year_to if year_to is not None else min(date.today().year + 1, _DEFAULT_YEAR_TO_CAP)
        logger.info(
            "GreekDiscovery: walking issue group %d (%s) from %d to %d",
            issue_group,
            "Α" if issue_group == 1 else f"#{issue_group}",
            year_from,
            upper,
        )

        total_yielded = 0
        for year in range(year_from, upper + 1):
            try:
                hits = client.simple_search(year=year, issue_group=issue_group)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "GreekDiscovery: simpleSearch failed for year %d: %s",
                    year,
                    exc,
                )
                continue

            if not hits:
                logger.debug("GreekDiscovery: year %d → 0 items", year)
                continue

            # Sort by document number ascending so the iteration is
            # chronological within the year. (The API returns items in
            # arbitrary order, often by relevance score.)
            try:
                hits.sort(key=lambda h: int(h.get("search_DocumentNumber") or 0))
            except (ValueError, TypeError):
                # Defensive: if a doc number can't be parsed as int,
                # fall back to lexicographic order so the run still
                # makes progress.
                hits.sort(key=lambda h: str(h.get("search_DocumentNumber") or ""))

            seen_in_year: set[int] = set()
            for hit in hits:
                try:
                    doc_num = int(hit["search_DocumentNumber"])
                except (KeyError, ValueError, TypeError):
                    continue
                if doc_num in seen_in_year:
                    continue
                seen_in_year.add(doc_num)
                norm_id = make_norm_id(year, issue_group, doc_num)
                total_yielded += 1
                yield norm_id

            logger.info(
                "GreekDiscovery: year %d → %d items",
                year,
                len(seen_in_year),
            )

        logger.info("GreekDiscovery: yielded %d total norm_ids", total_yielded)

    def discover_daily(
        self,
        client: LegislativeClient,
        target_date: date,
        *,
        issue_group: int = _DEFAULT_ISSUE_GROUP,
        **kwargs,
    ) -> Iterator[str]:
        """Yield norm_ids published on (or after) a specific date.

        The official ``simpleSearch`` endpoint accepts ``datePublished``
        and ``dateReleased`` parameters but **silently ignores them**
        when the request is sent without an explicit ``selectYear``
        (verified empirically 2026-04-08). The API returns 12,000
        results regardless, including items from 1833.

        Workaround: query the target year via ``selectYear`` and filter
        client-side. The year-restricted result set is small (≈250-400
        items for Α'), so the post-filter is essentially free.
        """
        if not isinstance(client, GreekClient):
            raise TypeError(f"GreekDiscovery requires GreekClient, got {type(client).__name__}")

        try:
            hits = client.simple_search(year=target_date.year, issue_group=issue_group)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "GreekDiscovery.discover_daily failed for %s: %s",
                target_date.isoformat(),
                exc,
            )
            return

        if not hits:
            return

        # Filter by exact publication date. The API returns dates in
        # MM/DD/YYYY format with a "00:00:00" suffix.
        target_str = target_date.strftime("%m/%d/%Y")
        matches = [
            h for h in hits if (h.get("search_PublicationDate") or "").startswith(target_str)
        ]
        if not matches:
            logger.info(
                "GreekDiscovery: no FEK Α' published on %s",
                target_date.isoformat(),
            )
            return

        try:
            matches.sort(key=lambda h: int(h.get("search_DocumentNumber") or 0))
        except (ValueError, TypeError):
            matches.sort(key=lambda h: str(h.get("search_DocumentNumber") or ""))

        for hit in matches:
            try:
                doc_num = int(hit["search_DocumentNumber"])
            except (KeyError, ValueError, TypeError):
                continue
            yield make_norm_id(target_date.year, issue_group, doc_num)
