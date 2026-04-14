"""EUR-Lex HTTP client — European Union.

Two complementary interfaces:

1. **CELLAR SPARQL endpoint** (``publications.europa.eu/webapi/rdf/sparql``)
   — used for discovery, metadata queries, and resolving XHTML manifest URIs.
   Public, no auth, Virtuoso backend with 60-second query timeout.

2. **CELLAR REST** (``publications.europa.eu/resource/cellar/{uuid}``)
   — hosts the actual XHTML files for consolidated and original texts.
   Content negotiation via Accept header. Public, no auth.

**Historical versioning** — EUR-Lex publishes consolidated texts (CONS_TEXT)
as separate works linked to the base regulation via
``cdm:act_consolidated_based_on_resource_legal``. Each consolidated text has
a ``work_date_document`` that serves as the version's effective date.
``get_text`` bundles the original + all consolidated versions into a
``<eurlex-multi-version>`` envelope so the parser can emit multi-Version
blocks and the pipeline generates one git commit per reform.

The CELLAR endpoint and REST API are both public, no auth required.
License: reuse under Commission Decision 2011/833/EU.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import TYPE_CHECKING
from urllib.parse import quote

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

DEFAULT_SPARQL_URL = "https://publications.europa.eu/webapi/rdf/sparql"

# Cap historical versions per regulation to bound bootstrap cost.
# Most regulations have 0-5 consolidated versions; a few codes have 20+.
MAX_VERSIONS_PER_REGULATION = 200

# CDM ontology prefix
_CDM = "http://publications.europa.eu/ontology/cdm#"

# Authority table URIs
_RTYPE_BASE = "http://publications.europa.eu/resource/authority/resource-type/"
_LANG_ENG = "http://publications.europa.eu/resource/authority/language/ENG"

# Regulation types to include in discovery (v1 scope)
DEFAULT_REG_TYPES = ["REG", "REG_IMPL", "REG_DEL", "REG_FINANC"]


class EURLexClient(HttpClient):
    """Client for EU legislation via CELLAR SPARQL + REST.

    The CELLAR platform (publications.europa.eu) exposes:
    - A SPARQL endpoint (Virtuoso) for structured queries over the CDM ontology
    - A REST API for downloading XHTML/PDF/Formex files via content negotiation
    """

    @classmethod
    def create(cls, country_config: CountryConfig) -> EURLexClient:
        source = country_config.source or {}
        return cls(
            sparql_url=source.get("sparql_url", DEFAULT_SPARQL_URL),
            request_timeout=int(source.get("request_timeout", 30)),
            max_retries=int(source.get("max_retries", 5)),
            requests_per_second=float(source.get("requests_per_second", 2.0)),
            reg_types=source.get("reg_types", DEFAULT_REG_TYPES),
        )

    def __init__(
        self,
        *,
        sparql_url: str = DEFAULT_SPARQL_URL,
        request_timeout: int = 30,
        max_retries: int = 5,
        requests_per_second: float = 2.0,
        reg_types: list[str] | None = None,
    ) -> None:
        super().__init__(
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
        )
        self._sparql_url = sparql_url
        self._reg_types = reg_types or DEFAULT_REG_TYPES

        # Cache: celex → bundled XHTML bytes
        self._bundle_cache: dict[str, bytes] = {}
        self._bundle_lock = threading.Lock()

    # ─────────────────────────────────────────
    # SPARQL queries
    # ─────────────────────────────────────────

    def sparql_query(self, query: str) -> dict:
        """Execute a SPARQL SELECT query and return parsed JSON results."""
        url = f"{self._sparql_url}?query={quote(query)}"
        data = self._get(url, headers={"Accept": "application/sparql-results+json"})
        return json.loads(data)

    def get_consolidated_versions(self, celex: str) -> list[dict]:
        """Get all consolidated text versions for a base regulation.

        Returns a list of dicts sorted by date with keys:
        - ``celex``: consolidated text CELEX (e.g., 02016R0679-20160504)
        - ``date``: effective date string (YYYY-MM-DD)
        - ``manifest_uri``: URI of the XHTML manifestation

        Uses ``FILTER(STR(...))`` for CELEX matching because older records
        store CELEX as plain literals (no ``xsd:string`` type), and typed
        equality fails silently for those.
        """
        query = f"""PREFIX cdm: <{_CDM}>
SELECT DISTINCT ?consCelex ?consDate ?manifest WHERE {{
  ?baseWork cdm:resource_legal_id_celex ?bcelex .
  FILTER(STR(?bcelex) = "{celex}")
  ?cons cdm:act_consolidated_based_on_resource_legal ?baseWork .
  ?cons cdm:resource_legal_id_celex ?consCelex .
  ?cons cdm:work_date_document ?consDate .
  ?expr cdm:expression_belongs_to_work ?cons .
  ?expr cdm:expression_uses_language <{_LANG_ENG}> .
  ?manifest cdm:manifestation_manifests_expression ?expr .
  ?manifest cdm:manifestation_type ?mtype .
  FILTER(STR(?mtype) IN ("xhtml", "html"))
}}
ORDER BY ?consDate"""
        result = self.sparql_query(query)
        versions = []
        seen_dates: set[str] = set()
        for binding in result.get("results", {}).get("bindings", []):
            date_str = binding.get("consDate", {}).get("value", "")
            # Deduplicate by date (multiple manifestations for same version)
            if date_str in seen_dates:
                continue
            seen_dates.add(date_str)
            versions.append(
                {
                    "celex": binding.get("consCelex", {}).get("value", ""),
                    "date": date_str,
                    "manifest_uri": binding.get("manifest", {}).get("value", ""),
                }
            )
        return versions

    def get_html_manifest_uri(self, celex: str) -> str | None:
        """Get the XHTML or HTML manifest URI for a regulation's original text.

        Uses FILTER IN for manifestation type matching — plain literal
        equality (``?manifest cdm:manifestation_type "xhtml"``) fails on
        some old records where the type is stored with a different RDF literal
        form. FILTER with STR() is more robust.
        """
        query = f"""PREFIX cdm: <{_CDM}>
SELECT ?manifest WHERE {{
  ?work cdm:resource_legal_id_celex ?celex .
  FILTER(STR(?celex) = "{celex}")
  ?expr cdm:expression_belongs_to_work ?work .
  ?expr cdm:expression_uses_language <{_LANG_ENG}> .
  ?manifest cdm:manifestation_manifests_expression ?expr .
  ?manifest cdm:manifestation_type ?mtype .
  FILTER(STR(?mtype) IN ("xhtml", "html"))
}}
LIMIT 1"""
        result = self.sparql_query(query)
        bindings = result.get("results", {}).get("bindings", [])
        if bindings:
            return bindings[0]["manifest"]["value"]
        return None

    def get_metadata_sparql(self, celex: str) -> dict:
        """Fetch full metadata for a regulation via SPARQL.

        Returns the raw SPARQL JSON result with fields: celex, eli, title,
        date, entryForce, endValidity, force, rtype, author.
        """
        rtype_values = ", ".join(f"<{_RTYPE_BASE}{t}>" for t in self._reg_types)
        query = f"""PREFIX cdm: <{_CDM}>
SELECT DISTINCT ?celex ?eli ?title ?date ?entryForce ?endValidity ?force ?rtype ?author WHERE {{
  ?work cdm:resource_legal_id_celex ?celex .
  FILTER(STR(?celex) = "{celex}")
  ?work cdm:work_has_resource-type ?rtype .
  FILTER(?rtype IN ({rtype_values}))
  FILTER NOT EXISTS {{
    ?work cdm:work_has_resource-type <{_RTYPE_BASE}CORRIGENDUM> .
  }}
  OPTIONAL {{ ?work cdm:resource_legal_eli ?eli . }}
  OPTIONAL {{ ?work cdm:work_date_document ?date . }}
  OPTIONAL {{ ?work cdm:resource_legal_date_entry-into-force ?entryForce . }}
  OPTIONAL {{ ?work cdm:resource_legal_date_end-of-validity ?endValidity . }}
  OPTIONAL {{ ?work cdm:resource_legal_in-force ?force . }}
  OPTIONAL {{
    ?expr cdm:expression_belongs_to_work ?work .
    ?expr cdm:expression_uses_language <{_LANG_ENG}> .
    ?expr cdm:expression_title ?title .
  }}
  OPTIONAL {{ ?work cdm:work_created_by_agent ?author . }}
}}"""
        return self.sparql_query(query)

    # ─────────────────────────────────────────
    # XHTML downloads
    # ─────────────────────────────────────────

    def download_xhtml(self, manifest_uri: str) -> bytes:
        """Download XHTML from a CELLAR manifest URI.

        Uses content negotiation to request XHTML format.
        """
        return self._get(
            manifest_uri,
            headers={"Accept": "application/xhtml+xml;q=1, text/html;q=0.5"},
        )

    # ─────────────────────────────────────────
    # LegislativeClient interface
    # ─────────────────────────────────────────

    def get_text(self, norm_id: str) -> bytes:
        """Fetch the full history of a regulation as a bundled multi-version envelope.

        Returns a ``<eurlex-multi-version>`` XHTML document whose children are
        ``<version>`` elements wrapping the full XHTML of each historical
        version, annotated with ``effective-date`` and ``type`` attributes.

        If the regulation has no consolidated versions, returns the raw XHTML
        of the original text.
        """
        with self._bundle_lock:
            cached = self._bundle_cache.get(norm_id)
        if cached is not None:
            return cached

        celex = norm_id  # norm_id IS the CELEX for EU

        # 1. Get consolidated versions
        consolidations = self.get_consolidated_versions(celex)

        # 2. If we have consolidated versions, use the latest one as the text
        #    and bundle all versions for history
        if consolidations:
            # Cap runaway version chains
            if len(consolidations) > MAX_VERSIONS_PER_REGULATION:
                logger.info(
                    "%s has %d consolidated versions, truncating to most recent %d",
                    celex,
                    len(consolidations),
                    MAX_VERSIONS_PER_REGULATION,
                )
                consolidations = consolidations[-MAX_VERSIONS_PER_REGULATION:]

            # Build multi-version envelope
            pieces: list[bytes] = [
                b"<?xml version='1.0' encoding='UTF-8'?>\n",
                b"<eurlex-multi-version celex='",
                celex.encode("utf-8"),
                b"'>\n",
            ]

            for consol in consolidations:
                date_str = consol["date"] or "unknown"
                try:
                    xhtml = self.download_xhtml(consol["manifest_uri"])
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to download consolidation %s of %s: %s",
                        date_str,
                        celex,
                        exc,
                    )
                    continue

                pieces.append(
                    f"<version type='consolidation' effective-date='{date_str}'>\n".encode()
                )
                # Strip XML declaration if present
                inner = xhtml
                if inner.startswith(b"<?xml"):
                    idx = inner.find(b"?>")
                    if idx >= 0:
                        inner = inner[idx + 2 :].lstrip()
                # Strip DOCTYPE if present
                if inner.startswith(b"<!DOCTYPE"):
                    idx = inner.find(b">")
                    if idx >= 0:
                        inner = inner[idx + 1 :].lstrip()
                pieces.append(inner)
                pieces.append(b"\n</version>\n")

            pieces.append(b"</eurlex-multi-version>\n")
            data = b"".join(pieces)
        else:
            # No consolidated versions — download the original text
            manifest_uri = self.get_html_manifest_uri(celex)
            if not manifest_uri:
                raise ValueError(f"No XHTML available for {celex}")
            data = self.download_xhtml(manifest_uri)

        with self._bundle_lock:
            self._bundle_cache[norm_id] = data
        return data

    def get_metadata(self, norm_id: str) -> bytes:
        """Fetch metadata for a regulation.

        Returns SPARQL JSON results as bytes for the metadata parser.
        """
        result = self.get_metadata_sparql(norm_id)
        return json.dumps(result).encode("utf-8")

    def evict_cache(self, norm_id: str) -> None:
        """Remove a norm from the bundle cache to free memory."""
        with self._bundle_lock:
            self._bundle_cache.pop(norm_id, None)
