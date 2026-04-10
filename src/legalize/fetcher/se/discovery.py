"""Norm discovery for Swedish legislation via the Riksdagen API.

Paginates through the Riksdagen /dokumentlista/ endpoint to discover
SFS (Svensk Forfattningssamling) numbers for base statutes.

Filters out amendment SFS entries (andrings-SFS) which modify
existing laws rather than creating new ones.

Reference: https://data.riksdagen.se/dokumentlista/?doktyp=sfs&format=json
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from datetime import date

from legalize.fetcher.base import LegislativeClient, NormDiscovery

logger = logging.getLogger(__name__)

_RIKSDAGEN_LIST_URL = "https://data.riksdagen.se/dokumentlista"

# Patterns that identify amendment SFS entries (not base laws).
# These modify existing laws rather than creating new statutes.
_AMENDMENT_PATTERNS = (
    re.compile(r"om\s+ändring\s+i", re.IGNORECASE),
    re.compile(r"om\s+upphävande\s+av", re.IGNORECASE),
)

# Pattern to extract the base law SFS number from an amendment title.
# Example: "Lag (2024:123) om ändring i brottsbalken (1962:700)" -> "1962:700"
_BASE_SFS_PATTERN = re.compile(r"\((\d{4}:\d+)\)\s*$")


def _is_amendment(title: str) -> bool:
    """Check if a title indicates an amendment (andrings-SFS).

    Amendment titles typically contain "om ändring i" (amending)
    or "om upphävande av" (repealing).
    """
    return any(p.search(title) for p in _AMENDMENT_PATTERNS)


def _extract_base_sfs(title: str) -> str | None:
    """Extract the base law's SFS number from an amendment title.

    Example:
        "Lag (2024:123) om ändring i brottsbalken (1962:700)"
        -> "1962:700"

    Returns None if no base SFS number can be extracted.
    """
    match = _BASE_SFS_PATTERN.search(title)
    return match.group(1) if match else None


class SwedishDiscovery(NormDiscovery):
    """Discovers Swedish statutes via the Riksdagen Open Data API.

    Paginates through /dokumentlista/?doktyp=sfs sorted by date.
    Filters out amendment SFS entries to yield only base statutes.
    """

    def discover_all(
        self,
        client: LegislativeClient,
        **kwargs,
    ) -> Iterator[str]:
        """Discover all base statute SFS numbers in the Riksdagen catalog.

        Paginates through the full SFS catalog sorted by date ascending.
        Filters OUT amendment entries (titles containing "om ändring i"
        or "om upphävande av") since those modify existing laws.

        Args:
            client: A SwedishClient instance for HTTP requests.

        Yields:
            SFS numbers like "1962:700", "2018:218".
        """
        seen: set[str] = set()
        page = 1
        count = 0
        pages_without_new = 0
        # The Riksdagen SFS catalog has ~1.3M entries (mostly amendments).
        # Base statutes are ~10K. Once we stop finding new ones for 200
        # consecutive pages (~40K amendment entries), we can safely stop.
        _MAX_EMPTY_PAGES = 200

        while True:
            url = (
                f"{_RIKSDAGEN_LIST_URL}/"
                f"?doktyp=sfs&sort=datum&sortorder=asc"
                f"&format=json&utformat=json&p={page}"
            )
            logger.debug("Fetching SFS catalog page %d", page)
            raw = self._fetch_list(client, url)
            documents, has_more = self._parse_list_response(raw)

            if not documents:
                break

            found_new = False
            for doc in documents:
                title = doc.get("titel", "")
                sfs = doc.get("beteckning", "")

                if not sfs:
                    continue

                # Skip amendment entries
                if _is_amendment(title):
                    logger.debug("Skipping amendment SFS: %s — %s", sfs, title)
                    continue

                if sfs not in seen:
                    seen.add(sfs)
                    count += 1
                    found_new = True
                    logger.info("Discovered: SFS %s — %s", sfs, title)
                    yield sfs

            if found_new:
                pages_without_new = 0
            else:
                pages_without_new += 1
                if pages_without_new >= _MAX_EMPTY_PAGES:
                    logger.info(
                        "Early exit: %d pages with no new base statutes. "
                        "Stopping discovery at page %d.",
                        _MAX_EMPTY_PAGES,
                        page,
                    )
                    break

            if not has_more:
                break
            page += 1

        logger.info("Total discovered: %d base statutes (%d pages)", count, page)

    def discover_daily(
        self,
        client: LegislativeClient,
        target_date: date,
        **kwargs,
    ) -> Iterator[str]:
        """Discover statutes published or updated on a specific date.

        For base statutes, yields the SFS number directly.
        For amendment entries, extracts and yields the base law's
        SFS number instead (the law being amended).

        Args:
            client: A SwedishClient instance for HTTP requests.
            target_date: The date to search for.

        Yields:
            SFS numbers of affected base statutes.
        """
        date_str = target_date.strftime("%Y-%m-%d")
        seen: set[str] = set()

        url = (
            f"{_RIKSDAGEN_LIST_URL}/"
            f"?doktyp=sfs&from={date_str}&tom={date_str}"
            f"&format=json&utformat=json"
        )
        logger.info("Discovering SFS for date %s", date_str)
        raw = self._fetch_list(client, url)
        documents, _ = self._parse_list_response(raw)

        for doc in documents:
            title = doc.get("titel", "")
            sfs = doc.get("beteckning", "")

            if not sfs:
                continue

            if _is_amendment(title):
                # For amendments, yield the base law's SFS number
                base_sfs = _extract_base_sfs(title)
                if base_sfs and base_sfs not in seen:
                    seen.add(base_sfs)
                    logger.info(
                        "Amendment SFS %s affects base law %s",
                        sfs,
                        base_sfs,
                    )
                    yield base_sfs
            else:
                if sfs not in seen:
                    seen.add(sfs)
                    logger.info("New/updated SFS %s — %s", sfs, title)
                    yield sfs

    # ── Internal helpers ──

    @staticmethod
    def _fetch_list(client: LegislativeClient, url: str) -> bytes:
        """Fetch a document list URL using the client's session.

        Uses the client's internal _get method if available (SwedishClient),
        otherwise falls back to a direct requests call.
        """
        if hasattr(client, "_get"):
            return client._get(url)  # type: ignore[attr-defined]
        # Fallback for testing or non-SwedishClient instances
        import requests as req

        resp = req.get(
            url,
            timeout=30,
            headers={
                "User-Agent": "legalize-bot/1.0",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.content

    @staticmethod
    def _parse_list_response(data: bytes) -> tuple[list[dict], bool]:
        """Parse a Riksdagen /dokumentlista/ JSON response.

        Returns:
            Tuple of (list of document dicts, has_more_pages).
        """
        try:
            result = json.loads(data)
        except json.JSONDecodeError:
            logger.warning("Failed to parse Riksdagen list response")
            return [], False

        doc_list = result.get("dokumentlista", {})
        documents = doc_list.get("dokument") or []

        # Check pagination: @nasta_sida indicates there are more pages
        has_more = bool(doc_list.get("@nasta_sida"))

        return documents, has_more
