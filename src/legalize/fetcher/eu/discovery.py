"""EUR-Lex discovery — European Union.

Uses SPARQL queries against the CELLAR endpoint to discover all EU
regulations in scope (REG, REG_IMPL, REG_DEL, REG_FINANC).

Discovery is paginated via cursor-based filtering to handle Virtuoso's
OFFSET limitations (errors above ~10K offset). Each page fetches 1000
results in ~400ms.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date
from typing import TYPE_CHECKING

from legalize.fetcher.base import NormDiscovery
from legalize.fetcher.eu.client import (
    DEFAULT_REG_TYPES,
    EURLexClient,
    _CDM,
    _LANG_ENG,
    _RTYPE_BASE,
)

if TYPE_CHECKING:
    from legalize.fetcher.base import LegislativeClient

logger = logging.getLogger(__name__)

# SPARQL page size for paginated queries
_PAGE_SIZE = 1000


class EURLexDiscovery(NormDiscovery):
    """Discover EU regulations via SPARQL queries on CELLAR."""

    def __init__(self, reg_types: list[str] | None = None, year_start: int = 0) -> None:
        self._reg_types = reg_types or DEFAULT_REG_TYPES
        self._year_start = year_start

    @classmethod
    def create(cls, source) -> EURLexDiscovery:
        if hasattr(source, "source"):
            source_dict = source.source or {}
        else:
            source_dict = source or {}
        reg_types = source_dict.get("reg_types", DEFAULT_REG_TYPES)
        year_start = int(source_dict.get("year_start", 0))
        return cls(reg_types=reg_types, year_start=year_start)

    def _build_rtype_filter(self) -> str:
        """Build a SPARQL FILTER clause for regulation types."""
        type_uris = ", ".join(f"<{_RTYPE_BASE}{t}>" for t in self._reg_types)
        return f"FILTER (?rtype IN ({type_uris}))"

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Discover all in-force regulation CELEX numbers.

        Uses cursor-based pagination with ``FILTER (?celex > "last")`` to
        avoid Virtuoso timeout errors on large OFFSET values.

        Only returns regulations that are currently in force.
        """
        if not isinstance(client, EURLexClient):
            raise TypeError(f"Expected EURLexClient, got {type(client).__name__}")

        rtype_filter = self._build_rtype_filter()
        total_yielded = 0
        cursor = ""

        while True:
            cursor_filter = f'FILTER (STR(?celex) > "{cursor}")' if cursor else ""
            # Filter by year if configured (CELEX format: 3YYYYR...)
            year_filter = ""
            if self._year_start:
                year_filter = f'FILTER (STR(?celex) >= "3{self._year_start}R")'
            # Only include works that have an HTML or XHTML English expression
            # (skip PDF-only old laws that we can't parse)
            query = f"""PREFIX cdm: <{_CDM}>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?celex WHERE {{
  ?work cdm:work_has_resource-type ?rtype .
  {rtype_filter}
  FILTER NOT EXISTS {{
    ?work cdm:work_has_resource-type <{_RTYPE_BASE}CORRIGENDUM> .
  }}
  FILTER NOT EXISTS {{ ?work cdm:do_not_index "true"^^xsd:boolean . }}
  ?work cdm:resource_legal_in-force "true"^^xsd:boolean .
  ?work cdm:resource_legal_id_celex ?celex .
  ?expr cdm:expression_belongs_to_work ?work .
  ?expr cdm:expression_uses_language <{_LANG_ENG}> .
  ?manifest cdm:manifestation_manifests_expression ?expr .
  ?manifest cdm:manifestation_type ?mtype .
  FILTER(STR(?mtype) IN ("xhtml", "html"))
  {cursor_filter}
  {year_filter}
}}
ORDER BY ?celex
LIMIT {_PAGE_SIZE}"""

            result = client.sparql_query(query)
            bindings = result.get("results", {}).get("bindings", [])

            if not bindings:
                break

            last_celex = ""
            for binding in bindings:
                celex = binding["celex"]["value"]
                last_celex = celex
                yield celex
                total_yielded += 1

            logger.info(
                "Discovery page: %d results (last: %s), %d total",
                len(bindings),
                last_celex,
                total_yielded,
            )

            if len(bindings) < _PAGE_SIZE:
                break
            cursor = last_celex

        logger.info("Discovery complete: %d total regulations found", total_yielded)

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Discover regulations published or amended on a specific date.

        Two queries:
        1. New regulations with ``work_date_document == target_date``
        2. Regulations with new consolidated text dated ``target_date``
           (amendment published that day)
        """
        if not isinstance(client, EURLexClient):
            raise TypeError(f"Expected EURLexClient, got {type(client).__name__}")

        rtype_filter = self._build_rtype_filter()
        iso_date = target_date.isoformat()
        seen: set[str] = set()

        # 1. New regulations published on target_date
        query = f"""PREFIX cdm: <{_CDM}>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?celex WHERE {{
  ?work cdm:work_has_resource-type ?rtype .
  {rtype_filter}
  FILTER NOT EXISTS {{
    ?work cdm:work_has_resource-type <{_RTYPE_BASE}CORRIGENDUM> .
  }}
  ?work cdm:resource_legal_id_celex ?celex .
  ?work cdm:work_date_document "{iso_date}"^^xsd:date .
}}"""
        result = client.sparql_query(query)
        for binding in result.get("results", {}).get("bindings", []):
            celex = binding["celex"]["value"]
            if celex not in seen:
                seen.add(celex)
                yield celex

        # 2. Regulations whose consolidated text was updated on target_date
        #    (a new consolidated version with work_date_document == target_date)
        query = f"""PREFIX cdm: <{_CDM}>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?baseCelex WHERE {{
  ?cons cdm:work_has_resource-type <{_RTYPE_BASE}CONS_TEXT> .
  ?cons cdm:work_date_document "{iso_date}"^^xsd:date .
  ?cons cdm:resource_legal_id_celex ?consCelex .
  FILTER(REGEX(?consCelex, "^0[0-9]{{4}}R"))
  ?cons cdm:act_consolidated_based_on_resource_legal ?baseWork .
  ?baseWork cdm:resource_legal_id_celex ?baseCelex .
}}"""
        result = client.sparql_query(query)
        for binding in result.get("results", {}).get("bindings", []):
            celex = binding["baseCelex"]["value"]
            if celex not in seen:
                seen.add(celex)
                yield celex

        logger.info(
            "Daily discovery for %s: %d regulations found",
            iso_date,
            len(seen),
        )
