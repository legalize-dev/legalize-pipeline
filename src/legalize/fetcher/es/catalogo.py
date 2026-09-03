"""Norm discovery in the BOE catalog.

It does expose one. ``/api/legislacion-consolidada?limit=&offset=`` returns the
whole consolidated catalogue — 12,387 norms — in **two** requests, because a
page caps at 10,000 entries. The sweep it replaces walked 14,926 daily
summaries to reconstruct the same list (#99), and `discover_all` had been
calling a function that was never written, so `legalize bootstrap -c es` raised
an ImportError before fetching anything.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date, timedelta

import requests
from lxml import etree

from legalize.config import Config
from legalize.fetcher.es.client import BOEClient
from legalize.fetcher.es.config import ScopeConfig
from legalize.fetcher.es.sumario import parse_summary

logger = logging.getLogger(__name__)


#: The API's own ceiling for one page. Asking for more returns 10,000.
_PAGE_SIZE = 10_000


def iter_norms_from_catalog(client: BOEClient, config: Config | None = None) -> Iterator[str]:
    """Every norm the BOE keeps a consolidated text for, newest first.

    Paged by offset, which the source orders by `fecha_actualizacion`. That
    order can shift between two requests seconds apart, so identifiers are
    de-duplicated: a norm consolidated mid-sweep must not be yielded twice, and
    one that slides across the page boundary is picked up by the daily.
    """
    offset = 0
    seen: set[str] = set()
    while True:
        root = etree.fromstring(client.get_catalog(_PAGE_SIZE, offset))
        code = root.findtext("status/code", "").strip()
        if code != "200":
            raise ValueError(f"BOE catalogue returned {code}: {root.findtext('status/text', '')}")
        entries = root.findall("data/item")
        if not entries:
            return
        for entry in entries:
            identifier = (entry.findtext("identificador") or "").strip()
            if identifier and identifier not in seen:
                seen.add(identifier)
                yield identifier
        if len(entries) < _PAGE_SIZE:
            return
        offset += len(entries)


def iter_fixed_norms(config: Config) -> Iterator[str]:
    """Generates BOE IDs from the fixed norms list in config.

    Fixed norms are those always included in bootstrap,
    regardless of the scope dates.
    """
    cc = config.get_country("es")
    for boe_id in cc.source.get("normas_fijas", []):
        yield boe_id


def iter_norms_from_summaries(
    client: BOEClient,
    config: Config,
    start_date: date,
    end_date: date,
) -> Iterator[str]:
    """Discovers BOE IDs by iterating daily summaries over a date range.

    Useful for bootstrap when all legislation published in a period
    should be included, not just fixed norms.

    Summaries are published Monday through Saturday only.

    Args:
        client: BOE HTTP client.
        config: Configuration (for scope).
        start_date: Start date (inclusive).
        end_date: End date (inclusive).

    Yields:
        BOE IDs of dispositions within scope.
    """
    cc = config.get_country("es")
    scope = ScopeConfig(
        ranks=cc.source.get("rangos", []),
        fixed_norms=cc.source.get("normas_fijas", []),
    )
    seen: set[str] = set()
    current = start_date

    while current <= end_date:
        # No BOE on Sundays
        if current.weekday() == 6:
            current += timedelta(days=1)
            continue

        try:
            xml_data = client.get_sumario(current)
            dispositions = parse_summary(xml_data, scope)

            for disp in dispositions:
                if disp.id_boe not in seen:
                    seen.add(disp.id_boe)
                    yield disp.id_boe

        except requests.RequestException:
            logger.warning("Error processing summary for %s, continuing", current, exc_info=True)

        current += timedelta(days=1)
