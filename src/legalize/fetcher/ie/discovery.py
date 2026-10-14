"""Discover Irish Acts from eISB, with parliamentary API update metadata."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import date
from typing import TYPE_CHECKING

from lxml import html

from legalize.fetcher.base import LegislativeClient, NormDiscovery
from legalize.fetcher.ie.client import CONSTITUTION_ID, _parse_norm_id

if TYPE_CHECKING:
    from legalize.fetcher.ie.client import ISBClient

logger = logging.getLogger(__name__)

_PAGE_SIZE = 50


def _act_to_norm_id(act: dict) -> str | None:
    year, number = act.get("actYear"), act.get("actNo")
    if not year or not number:
        return None
    norm_id = f"IE-{year}-act-{number}"
    _parse_norm_id(norm_id)
    return norm_id


def _index_norm_ids(data: bytes, year: int) -> list[str]:
    """Read all Act namespaces, deduplicating Irish/English manifestations."""
    root = html.fromstring(data)
    result: dict[str, None] = {}
    for href in root.xpath("//tbody//a/@href"):
        match = re.search(r"(?:en|ga)/act/(pub|prv|cam)/(\d+)/", href)
        if match:
            kind, number = match.groups()
            prefix = {"pub": "", "prv": "P", "cam": "C"}[kind]
        else:
            match = re.search(r"(?:en|ga)\.(act|prv|ca)\.(\d{4})\.(\d+)\.pdf", href)
            if not match:
                continue
            kind, pdf_year, number = match.groups()
            if int(pdf_year) != year:
                raise ValueError(f"Act index {year} links to PDF for {pdf_year}: {href}")
            prefix = {"act": "", "prv": "P", "ca": "C"}[kind]
        norm_id = f"IE-{year}-act-{prefix}{int(number)}"
        _parse_norm_id(norm_id)
        result[norm_id] = None
    if not result:
        raise ValueError(f"No Acts found in the eISB index for {year}")
    return list(result)


class ISBDiscovery(NormDiscovery):
    """Treat eISB's annual indexes as the primary Act catalogue."""

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        isb: ISBClient = client  # type: ignore[assignment]
        start = int(kwargs.get("year_from", 1922))
        end = int(kwargs.get("year_to", date.today().year))
        if start < 1922 or end < start:
            raise ValueError(f"Invalid Irish Act year range: {start}..{end}")
        yield CONSTITUTION_ID
        for year in range(start, end + 1):
            ids = _index_norm_ids(isb.get_act_index(year), year)
            logger.info("Discovered %d Acts from eISB for %d", len(ids), year)
            yield from ids

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Yield all API metadata updates, including more than one result page."""
        isb: ISBClient = client  # type: ignore[assignment]
        skip = 0
        seen: set[str] = set()
        while True:
            page = isb.get_updated_since(target_date.isoformat(), skip=skip, limit=_PAGE_SIZE)
            results = page.get("results", [])
            if not results:
                break
            for item in results:
                norm_id = _act_to_norm_id(item.get("bill", {}).get("act", {}))
                if norm_id and norm_id not in seen:
                    seen.add(norm_id)
                    yield norm_id
            if len(results) < _PAGE_SIZE:
                break
            skip += _PAGE_SIZE
