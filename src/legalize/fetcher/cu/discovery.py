"""Norm discovery for Cuban legislation via the Gaceta Oficial catalog.

The Gaceta catalog page (``/es/algunas-legislaciones-cubanas``) exposes the
law *names* as plain table rows (e.g. ``Decreto-Ley 86/2024 "De la Caja de
Resarcimientos".``) but **no ``.pdf`` links** — verified 2026-04-xx across
the whole page including pagination. The URL map therefore lives in the
manifest, which is the source of truth for what we ingest.

Discovery strategy:

* ``discover_all`` — the manifest keys. Every manifest entry has a PDF URL
  and full metadata, so the full 53-law corpus is exactly the manifest.

* ``discover_daily`` — two signals:

  1. **Manifest dates** (the real incremental trigger). Each manifest entry
     carries the Gaceta ``publication_date``; the daily job yields every
     law whose publication date matches the target date. Upstream adds a
     new law to ``manifest.json`` with its Gaceta date, and the next daily
     run picks it up automatically.

  2. **Catalog diff** (a human/CI early-warning). We re-fetch the catalog
     page, parse the law-name rows, and match them against the manifest by
     a ``(rank, number, year)`` signature. Rows that have no manifest entry
     are logged as warnings — they are genuinely new laws that still need
     an upstream manifest entry before they can be ingested (there is no
     crawlable PDF URL on the catalog page to guess from).

Yields stable manifest identifiers (e.g. ``Ley-143-2021-Proceso-Penal``)
which double as the ``cu/*.md`` filenames.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import date

from legalize.fetcher.base import LegislativeClient, NormDiscovery

logger = logging.getLogger(__name__)

# Rank words as they appear at the start of catalog rows / manifest titles.
_RANK_WORDS = (
    "decreto-ley",
    "decreto ley",
    "decreto_law",
    "resolución",
    "resolucion",
    "decreto",
    "ley",
    "código",
    "codigo",
    "constitución",
    "constitucion",
    "instrucción",
    "instruccion",
    "acuerdo",
)

_RANK_NORMALIZED = {
    "decreto-ley": "decreto_ley",
    "decreto ley": "decreto_ley",
    "decreto_law": "decreto_ley",
    "decreto": "decreto",
    "ley": "ley",
    "resolución": "otro",
    "resolucion": "otro",
    "código": "codigo",
    "codigo": "codigo",
    "constitución": "constitucion",
    "constitucion": "constitucion",
    "instrucción": "otro",
    "instruccion": "otro",
    "acuerdo": "otro",
}

# "Ley 86/2024 ...", "Decreto-Ley No. 304 de 2012 ...", "Ley No. 143 de 2021 ..."
_NUMBER_YEAR_RE = re.compile(
    r"(?:No\.?\s*)?(\d{1,4})\s*(?:/\s*(\d{4})|de\s+(\d{4}))?\b", re.IGNORECASE
)


def _parse_law_signature(text: str) -> tuple[str | None, int | None, int | None]:
    """Extract ``(rank, number, year)`` from a law name or title.

    ``year`` may be ``None`` (some catalog rows omit it, e.g. ``Ley 56 ...``).
    Returns ``(None, None, None)`` when the text has no recognizable rank.
    """
    stripped = re.sub(r"\s+", " ", text).strip()
    rank: str | None = None
    match = None
    for word in _RANK_WORDS:
        m = re.match(re.escape(word) + r"\b", stripped, re.IGNORECASE)
        if m:
            rank = _RANK_NORMALIZED.get(word.lower(), "otro")
            match = m
            break
    if rank is None:
        return None, None, None

    tail = stripped[match.end() :]
    m = _NUMBER_YEAR_RE.search(tail)
    if not m:
        return rank, None, None
    number = int(m.group(1)) if m.group(1) else None
    year = None
    for group in (m.group(2), m.group(3)):
        if group:
            year = int(group)
            break
    return rank, number, year


def _signature_from_title(title: str) -> tuple[str | None, int | None, int | None]:
    """Same signature extraction, tolerant of the manifest title shape.

    Manifest titles look like ``Ley No. 143 de 2021, Del Proceso Penal``
    (rank then No. then number then ``de YYYY``); the number regex already
    handles both ``/`` and ``de`` year separators.
    """
    return _parse_law_signature(title)


def _matches(
    sig_a: tuple[str | None, int | None, int | None],
    sig_b: tuple[str | None, int | None, int | None],
) -> bool:
    """True when two signatures refer to the same law.

    Rank and number must agree; year must agree when both are known (a
    missing year on either side is tolerated).
    """
    ra, na, ya = sig_a
    rb, nb, yb = sig_b
    if ra != rb or na != nb or na is None:
        return False
    return not (ya is not None and yb is not None and ya != yb)


class GacetaDiscovery(NormDiscovery):
    """Discovers Cuban laws via the manifest + the catalog page."""

    def discover_all(
        self,
        client: LegislativeClient,
        **kwargs,
    ) -> Iterator[str]:
        """Yield every manifest identifier in sorted order."""
        if not hasattr(client, "get_manifest_keys"):
            raise TypeError("GacetaDiscovery requires GacetaClient")
        yield from client.get_manifest_keys()

    def discover_daily(
        self,
        client: LegislativeClient,
        target_date: date,
        **kwargs,
    ) -> Iterator[str]:
        """Yield manifest identifiers published on the target date.

        Also scans the catalog page and logs warnings for law-name rows that
        have no manifest entry yet (new laws awaiting an upstream manifest
        update — the catalog has no crawlable PDF URLs to guess from).
        """
        if not hasattr(client, "get_manifest"):
            raise TypeError("GacetaDiscovery requires GacetaClient")

        manifest = client.get_manifest()
        target_str = target_date.isoformat()
        yielded: set[str] = set()
        for key, entry in manifest.items():
            if (entry.get("publication_date") or "") == target_str:
                yielded.add(key)
                yield key

        # Catalog diff — early warning for new laws, never a fetch trigger.
        try:
            catalog_html = client.get_catalog().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            logger.warning("GacetaDiscovery: catalog fetch failed: %s", exc)
            return

        known: list[tuple[str | None, int | None, int | None]] = [
            _signature_from_title(entry.get("title") or "") for entry in manifest.values()
        ]
        seen_rows: set[tuple[str | None, int | None, int | None]] = set()
        for row in _extract_catalog_rows(catalog_html):
            sig = _parse_law_signature(row)
            if sig == (None, None, None) or sig in seen_rows:
                continue
            seen_rows.add(sig)
            if not any(_matches(sig, k) for k in known):
                logger.warning(
                    "GacetaDiscovery: catalog row has no manifest entry — "
                    "add it to manifest.json to ingest: %r",
                    row,
                )


def _extract_catalog_rows(html: str) -> list[str]:
    """Pull the law-name rows out of the catalog table HTML.

    The catalog renders each law as a table cell like
    ``Decreto-Ley 86/2024 "De la Caja de Resarcimientos".`` with an
    ellipsis truncation for long titles (``...``).
    """
    rows: list[str] = []
    for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", html, re.DOTALL | re.IGNORECASE):
        text = re.sub(r"<[^>]+>", " ", cell)
        text = re.sub(r"\s+", " ", text).strip()
        text = text.replace("\xa0", " ").strip()
        if text:
            rows.append(text)
    return rows
