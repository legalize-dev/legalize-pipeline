"""Fedlex discovery — Switzerland.

SPARQL-based discovery of Swiss federal acts in the Classified Compilation
(``eli/cc/``, aka SR — Systematic Collection). Uses the JOLux ontology
(reused verbatim from Luxembourg) with Fedlex-specific ELI URIs.

Scope v1: only ``cc/`` laws that have at least one Akoma Ntoso XML
consolidation in the requested language (German by default). This excludes
the ~12K of 17K laws that only exist as PDF/DOC (pre-2021 consolidations
that Fedlex has not back-filled yet).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date
from typing import TYPE_CHECKING

from legalize.fetcher.base import NormDiscovery
from legalize.fetcher.ch.client import (
    EU_LANG,
    EU_LANG_BASE,
    JOLUX_NS,
    SPARQL_PAGE_SIZE,
    USER_FORMAT_XML,
    FedlexClient,
    eli_url_to_norm_id,
)

__all__ = ["FedlexDiscovery"]
_ = USER_FORMAT_XML  # re-exported for daily query

if TYPE_CHECKING:
    from legalize.fetcher.base import LegislativeClient

logger = logging.getLogger(__name__)


class FedlexDiscovery(NormDiscovery):
    """Discover Swiss federal legislation via Fedlex SPARQL."""

    def __init__(self, language: str = "de") -> None:
        if language not in EU_LANG:
            raise ValueError(
                f"Unsupported Fedlex language {language!r}; expected one of {sorted(EU_LANG)}"
            )
        self._language = language
        self._language_uri = f"{EU_LANG_BASE}/{EU_LANG[language]}"

    @classmethod
    def create(cls, source) -> FedlexDiscovery:
        source_dict = source.source if hasattr(source, "source") else (source or {})
        return cls(language=(source_dict or {}).get("language", "de"))

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Yield all ``cc/`` norm IDs, regardless of XML availability.

        Uses cursor pagination (``FILTER (STR(?cca) > "<last>")``) on a
        simple single-triple query — adding the ``isRealizedBy → userFormat``
        join to this query made Virtuoso time out above the first page
        (90s+ for page 2). We therefore discover the full universe of
        ConsolidationAbstracts cheaply and let ``FedlexClient.get_text``
        skip laws that have no DE XML (it calls ``get_consolidations``,
        which is the per-law filter).

        This is a pragmatic trade: discovery returns ~17K CCAs instead of
        the ~5,139 that actually have DE XML, but the total bootstrap cost
        is unchanged because ``get_consolidations`` runs one cheap SPARQL
        per law either way.
        """
        if not isinstance(client, FedlexClient):
            raise TypeError(f"Expected FedlexClient, got {type(client).__name__}")

        cursor = ""
        total = 0
        page = 0
        while True:
            cursor_filter = f'FILTER (STR(?cca) > "{cursor}")' if cursor else ""
            query = f"""PREFIX jolux: <{JOLUX_NS}>
SELECT DISTINCT ?cca WHERE {{
  GRAPH ?g {{
    ?cca a jolux:ConsolidationAbstract .
    FILTER (CONTAINS(STR(?cca), "/eli/cc/"))
    {cursor_filter}
  }}
}} ORDER BY ?cca LIMIT {SPARQL_PAGE_SIZE}"""

            result = client.sparql_query(query)
            bindings = result.get("results", {}).get("bindings", [])
            if not bindings:
                break
            page += 1
            last_uri = ""
            for binding in bindings:
                cca_uri = binding["cca"]["value"]
                last_uri = cca_uri
                yield eli_url_to_norm_id(cca_uri)
                total += 1
            logger.info(
                "Discovery page %d: %d results (cumulative %d)",
                page,
                len(bindings),
                total,
            )
            if len(bindings) < SPARQL_PAGE_SIZE:
                break
            cursor = last_uri

        logger.info("Discovery complete: %d norms found", total)

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Yield norm IDs whose consolidation becomes applicable on ``target_date``.

        Fedlex schedules reforms via the ``jolux:dateApplicability`` on
        Consolidation nodes. A single date typically triggers 5-30 norms.

        We deliberately do NOT query by ``jolux:publicationDate`` on the
        ConsolidationAbstract — that field carries the act's ORIGINAL
        enactment date (often decades ago), not the reform date.
        """
        if not isinstance(client, FedlexClient):
            raise TypeError(f"Expected FedlexClient, got {type(client).__name__}")

        iso_date = target_date.isoformat()
        query = f"""PREFIX jolux: <{JOLUX_NS}>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?cca WHERE {{
  GRAPH ?g {{
    ?consol a jolux:Consolidation .
    ?consol jolux:dateApplicability "{iso_date}"^^xsd:date .
    ?consol jolux:isMemberOf ?cca .
    ?consol jolux:isRealizedBy ?expr .
    ?expr jolux:language <{self._language_uri}> .
    ?expr jolux:isEmbodiedBy ?manif .
    ?manif jolux:userFormat <{USER_FORMAT_XML}> .
  }}
  FILTER (CONTAINS(STR(?cca), "/eli/cc/"))
}}"""
        result = client.sparql_query(query)
        seen: set[str] = set()
        for binding in result.get("results", {}).get("bindings", []):
            cca_uri = binding["cca"]["value"]
            norm_id = eli_url_to_norm_id(cca_uri)
            if norm_id not in seen:
                seen.add(norm_id)
                yield norm_id
        logger.info("Daily discovery for %s: %d norms", iso_date, len(seen))
