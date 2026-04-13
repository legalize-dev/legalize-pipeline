"""Legilux discovery — Luxembourg.

Uses SPARQL queries against the Legilux open data endpoint to discover
all Acts in scope (LOI, RGD, Constitution) and their identifiers.

Discovery is fast (~10-15 seconds for a full catalog of ~25K acts) because
it's a single SPARQL query.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date
from typing import TYPE_CHECKING

from legalize.fetcher.base import NormDiscovery
from legalize.fetcher.lu.client import LegiluxClient, _eli_to_norm_id

if TYPE_CHECKING:
    from legalize.fetcher.base import LegislativeClient

logger = logging.getLogger(__name__)

# Resource type URIs for document type filtering
_TYPE_BASE = "http://data.legilux.public.lu/resource/authority/resource-type/"

# SPARQL page size for paginated queries
_PAGE_SIZE = 5000


class LegiluxDiscovery(NormDiscovery):
    """Discover Luxembourg legislation via SPARQL queries on Legilux."""

    def __init__(self, doc_types: list[str] | None = None) -> None:
        self._doc_types = doc_types or ["LOI", "RGD", "Constitution"]

    @classmethod
    def create(cls, source) -> LegiluxDiscovery:
        if hasattr(source, "source"):
            source_dict = source.source or {}
        else:
            source_dict = source or {}
        doc_types = source_dict.get("doc_types", ["LOI", "RGD", "Constitution"])
        return cls(doc_types=doc_types)

    def _build_type_filter(self) -> str:
        """Build a SPARQL FILTER clause for document types."""
        type_uris = ", ".join(f"<{_TYPE_BASE}{t}>" for t in self._doc_types)
        return f"FILTER (?type IN ({type_uris}))"

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Discover all norm IDs in the Luxembourg catalog.

        Queries the SPARQL endpoint for all Acts of the configured document
        types. Paginates with LIMIT/OFFSET to handle large result sets.
        """
        if not isinstance(client, LegiluxClient):
            raise TypeError(f"Expected LegiluxClient, got {type(client).__name__}")

        type_filter = self._build_type_filter()
        offset = 0
        total_yielded = 0
        seen: set[str] = set()

        while True:
            query = f"""PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
SELECT DISTINCT ?act WHERE {{
  GRAPH ?g {{
    ?act a jolux:Act .
    ?act jolux:typeDocument ?type .
    {type_filter}
  }}
}}
ORDER BY ?act
LIMIT {_PAGE_SIZE}
OFFSET {offset}"""

            result = client.sparql_query(query)
            bindings = result.get("results", {}).get("bindings", [])

            if not bindings:
                break

            for binding in bindings:
                act_uri = binding["act"]["value"]
                norm_id = _eli_to_norm_id(act_uri)
                if norm_id not in seen:
                    seen.add(norm_id)
                    yield norm_id
                    total_yielded += 1

            logger.info(
                "Discovery page %d: %d results, %d total unique",
                offset // _PAGE_SIZE + 1,
                len(bindings),
                total_yielded,
            )

            if len(bindings) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

        logger.info("Discovery complete: %d total norms found", total_yielded)

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Discover norms published/updated on a specific date.

        Queries for Acts with ``jolux:publicationDate`` matching the target
        date. Also checks for new consolidations with ``dateApplicability``
        matching the target date, since a reform might create a new
        consolidation version without publishing a new Act.
        """
        if not isinstance(client, LegiluxClient):
            raise TypeError(f"Expected LegiluxClient, got {type(client).__name__}")

        type_filter = self._build_type_filter()
        iso_date = target_date.isoformat()
        seen: set[str] = set()

        # 1. New Acts published on target_date
        query = f"""PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?act WHERE {{
  GRAPH ?g {{
    ?act a jolux:Act .
    ?act jolux:typeDocument ?type .
    {type_filter}
    ?act jolux:publicationDate "{iso_date}"^^xsd:date .
  }}
}}"""
        result = client.sparql_query(query)
        for binding in result.get("results", {}).get("bindings", []):
            act_uri = binding["act"]["value"]
            norm_id = _eli_to_norm_id(act_uri)
            if norm_id not in seen:
                seen.add(norm_id)
                yield norm_id

        # 2. Acts whose consolidation was updated (new consolidation version
        #    with dateApplicability == target_date)
        query = f"""PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?act WHERE {{
  GRAPH ?g {{
    ?consol a jolux:Consolidation .
    ?consol jolux:dateApplicability "{iso_date}"^^xsd:date .
    ?consol jolux:isMemberOf ?complexWork .
  }}
  GRAPH ?g2 {{
    ?act a jolux:Act .
    ?act jolux:isMemberOf ?complexWork .
    ?act jolux:typeDocument ?type .
    {type_filter}
  }}
}}"""
        result = client.sparql_query(query)
        for binding in result.get("results", {}).get("bindings", []):
            act_uri = binding["act"]["value"]
            norm_id = _eli_to_norm_id(act_uri)
            if norm_id not in seen:
                seen.add(norm_id)
                yield norm_id

        logger.info(
            "Daily discovery for %s: %d norms found",
            iso_date,
            len(seen),
        )
