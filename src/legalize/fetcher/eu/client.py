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
import re
import threading
from collections.abc import Iterator
from pathlib import Path
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

# Rows per bulk-catalog page. Virtuoso answers 1,000 in ~1.2 s; the same rows
# fetched one act at a time cost ~2.4 s each.
_CATALOG_PAGE_SIZE = 1000

# A well-formed CELEX: sector digit, 4-digit year, document-type letter, number.
# CELLAR hands back fragments of consolidated texts under this property too.
_CELEX_RE = re.compile(r"^[0-9]{5}[A-Z]{1,2}[0-9]{4}")

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
            cache_dir=country_config.cache_dir or source.get("cache_dir", ""),
        )

    def __init__(
        self,
        *,
        sparql_url: str = DEFAULT_SPARQL_URL,
        request_timeout: int = 30,
        max_retries: int = 5,
        requests_per_second: float = 2.0,
        reg_types: list[str] | None = None,
        cache_dir: str = "",
    ) -> None:
        super().__init__(
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
        )
        self._sparql_url = sparql_url
        self._reg_types = reg_types or DEFAULT_REG_TYPES

        self._cache_dir = cache_dir

        # Cache: celex → bundled XHTML bytes
        self._bundle_cache: dict[str, bytes] = {}
        self._bundle_lock = threading.Lock()

        # Bulk catalog: celex → SPARQL binding rows. Built once, on first use.
        self._catalog_data: dict[str, list[dict]] | None = None
        self._catalog_lock = threading.RLock()

    # ─────────────────────────────────────────
    # SPARQL queries
    # ─────────────────────────────────────────

    def sparql_query(self, query: str) -> dict:
        """Execute a SPARQL SELECT query and return parsed JSON results."""
        url = f"{self._sparql_url}?query={quote(query)}"
        data = self._get(url, headers={"Accept": "application/sparql-results+json"})
        return json.loads(data)

    # ─────────────────────────────────────────
    # Bulk catalog
    # ─────────────────────────────────────────

    def _rtype_uris(self) -> str:
        return ", ".join(f"<{_RTYPE_BASE}{t}>" for t in self._reg_types)

    def _paged(self, build_query, key: str) -> Iterator[tuple[str, list[dict]]]:
        """Run a cursor-paged SPARQL query and yield ``(key, rows)`` groups.

        Virtuoso errors out on OFFSET beyond ~10K rows, so pages are cut with
        ``FILTER(STR(?key) >= "cursor")`` over an ordered result instead.

        One act produces several rows (author × entry-into-force date × …), so
        a page boundary can fall in the middle of an act. The trailing group of
        a full page is therefore *not* emitted: the next page re-fetches it from
        its first row with ``>=``. Cutting on ``>`` instead would silently drop
        whichever authors and dates happened to land after the cut — invisible
        in the output and impossible to spot in an 87K-act corpus.
        """
        cursor = ""
        while True:
            result = self.sparql_query(build_query(cursor))
            bindings = result.get("results", {}).get("bindings", [])
            if not bindings:
                return

            groups: dict[str, list[dict]] = {}
            for b in bindings:
                value = b.get(key, {}).get("value", "")
                if value:
                    groups.setdefault(value, []).append(b)
            if not groups:
                return

            last_key = list(groups)[-1]
            full_page = len(bindings) >= _CATALOG_PAGE_SIZE

            if full_page and len(groups) > 1:
                # Hold back the trailing group; the next page starts at it.
                del groups[last_key]
            for value, rows in groups.items():
                yield value, rows

            if not full_page:
                return
            if len(groups) == 1 and last_key in groups:
                # A single key filled the whole page. Nothing to hold back, and
                # >= would re-fetch it forever, so step past it.
                raise RuntimeError(
                    f"{key}={last_key!r} has more than {_CATALOG_PAGE_SIZE} rows; "
                    "the paging cursor cannot advance"
                )
            cursor = last_key

    def _fetch_catalog(self) -> dict[str, list[dict]]:
        """Every in-scope act with its metadata, keyed by CELEX.

        One row per (act × author × entry-into-force date …), exactly as the
        per-act query returns them, so the parser cannot tell the two apart.
        """

        def build(cursor: str) -> str:
            cursor_filter = f'FILTER(STR(?celex) >= "{cursor}")' if cursor else ""
            return f"""PREFIX cdm: <{_CDM}>
SELECT ?celex ?eli ?title ?date ?entryForce ?endValidity ?force ?rtype ?author ?repealedBy
       ?hasCons ?eea ?signature
WHERE {{
  ?work cdm:work_has_resource-type ?rtype .
  FILTER(?rtype IN ({self._rtype_uris()}))
  FILTER NOT EXISTS {{ ?work cdm:work_has_resource-type <{_RTYPE_BASE}CORRIGENDUM> . }}
  FILTER NOT EXISTS {{ ?work cdm:do_not_index "true"^^<http://www.w3.org/2001/XMLSchema#boolean> . }}
  ?work cdm:resource_legal_id_celex ?celex .
  ?work cdm:resource_legal_in-force ?force .
  ?work cdm:work_date_document ?date .
  ?expr cdm:expression_belongs_to_work ?work .
  ?expr cdm:expression_uses_language <{_LANG_ENG}> .
  ?expr cdm:expression_title ?title .
  ?manifest cdm:manifestation_manifests_expression ?expr .
  ?manifest cdm:manifestation_type ?mtype .
  FILTER(STR(?mtype) IN ("xhtml", "html"))
  OPTIONAL {{ ?work cdm:resource_legal_eli ?eli . }}
  OPTIONAL {{ ?work cdm:resource_legal_date_entry-into-force ?entryForce . }}
  OPTIONAL {{ ?work cdm:resource_legal_date_end-of-validity ?endValidity . }}
  OPTIONAL {{ ?work cdm:work_created_by_agent ?author . }}
  OPTIONAL {{
    ?repealer cdm:resource_legal_repeals_resource_legal ?work .
    ?repealer cdm:resource_legal_id_celex ?repealedBy .
  }}
  OPTIONAL {{ ?work cdm:resource_legal_eea ?eea . }}
  OPTIONAL {{ ?work cdm:resource_legal_date_signature ?signature . }}
  # Whether a consolidated text exists decides the file's text_state, and it is
  # asked as EXISTS rather than joined so one act stays one row per author
  # instead of one per consolidation.
  BIND(EXISTS {{ ?cons cdm:act_consolidated_based_on_resource_legal ?work }} AS ?hasCons)
  {cursor_filter}
}}
ORDER BY ?celex
LIMIT {_CATALOG_PAGE_SIZE}"""

        catalog: dict[str, list[dict]] = {}
        for celex, rows in self._paged(build, "celex"):
            catalog[celex] = rows
        logger.info("Catalog: %d acts", len(catalog))

        # Multi-valued facts ride in their own queries and are merged onto the
        # act's first row, so the parser reads them the same way either route.
        for celex, amender in self._fetch_amendments().items():
            if celex in catalog:
                catalog[celex][0]["lastAmendment"] = {"value": amender}
        for celex, labels in self._fetch_subjects().items():
            if celex in catalog:
                catalog[celex][0]["subjects"] = {"value": "|".join(labels)}
        return catalog

    def _fetch_amendments(self) -> dict[str, str]:
        """CELEX → CELEX of the most recent act amending it.

        Only acts with no consolidated text need this: those are published as
        enacted, and spec v0.4 §Text state requires ``last_amendment`` on an
        as-enacted file that has been amended. 4,457 acts in scope are in that
        position — amended, but never consolidated by EUR-Lex — so without this
        they would claim to have never been touched.
        """

        def build(cursor: str) -> str:
            cursor_filter = f'FILTER(STR(?celex) >= "{cursor}")' if cursor else ""
            return f"""PREFIX cdm: <{_CDM}>
SELECT ?celex ?amenderCelex ?amenderDate WHERE {{
  ?work cdm:work_has_resource-type ?rtype .
  FILTER(?rtype IN ({self._rtype_uris()}))
  ?work cdm:resource_legal_id_celex ?celex .
  ?work cdm:resource_legal_in-force ?force .
  FILTER NOT EXISTS {{ ?c cdm:act_consolidated_based_on_resource_legal ?work . }}
  ?amender cdm:resource_legal_amends_resource_legal ?work .
  ?amender cdm:resource_legal_id_celex ?amenderCelex .
  ?amender cdm:work_date_document ?amenderDate .
  {cursor_filter}
}}
ORDER BY ?celex
LIMIT {_CATALOG_PAGE_SIZE}"""

        latest: dict[str, str] = {}
        for celex, rows in self._paged(build, "celex"):
            best = max(rows, key=lambda r: r.get("amenderDate", {}).get("value", ""))
            amender = best.get("amenderCelex", {}).get("value", "")
            # CELLAR returns junk CELEX values for consolidated-text fragments
            # ("04", "B", "05" all came back for Regulation 1017/68), and the
            # spec is explicit that this field names an act in this repo.
            if _CELEX_RE.match(amender):
                latest[celex] = amender
        logger.info("Amendments: %d acts carry a last_amendment", len(latest))
        return latest

    def _fetch_subjects(self) -> dict[str, list[str]]:
        """CELEX → EuroVoc concept labels, the source's own subject vocabulary.

        Multi-valued, so it is its own query: joined into the catalog it would
        multiply every act's rows by its number of concepts.
        """

        def build(cursor: str) -> str:
            cursor_filter = f'FILTER(STR(?celex) >= "{cursor}")' if cursor else ""
            return f"""PREFIX cdm: <{_CDM}>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?celex ?label WHERE {{
  ?work cdm:work_has_resource-type ?rtype .
  FILTER(?rtype IN ({self._rtype_uris()}))
  ?work cdm:resource_legal_id_celex ?celex .
  ?work cdm:resource_legal_in-force ?force .
  ?work cdm:work_is_about_concept_eurovoc ?concept .
  ?concept skos:prefLabel ?label .
  FILTER(LANG(?label) = "en")
  {cursor_filter}
}}
ORDER BY ?celex
LIMIT {_CATALOG_PAGE_SIZE}"""

        subjects: dict[str, list[str]] = {}
        for celex, rows in self._paged(build, "celex"):
            labels = sorted({r.get("label", {}).get("value", "") for r in rows} - {""})
            if labels:
                subjects[celex] = labels
        logger.info("Subjects: %d acts carry EuroVoc concepts", len(subjects))
        return subjects

    def _catalog(self) -> dict[str, list[dict]]:
        """Lazily build (or load) the bulk catalog. Thread-safe."""
        with self._catalog_lock:
            if self._catalog_data is not None:
                return self._catalog_data
            cached = self._catalog_path()
            if cached is not None and cached.exists():
                logger.info("Loading catalog from %s", cached)
                self._catalog_data = json.loads(cached.read_text(encoding="utf-8"))
                return self._catalog_data
            self._catalog_data = self._fetch_catalog()
            if cached is not None:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps(self._catalog_data), encoding="utf-8")
            return self._catalog_data

    def _catalog_path(self) -> Path | None:
        if not self._cache_dir:
            return None
        return Path(self._cache_dir) / "eu-catalog.json"

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
        """Fetch metadata for one act, from the bulk catalog where possible.

        Returns SPARQL JSON results as bytes, the shape the metadata parser
        expects, whichever route produced them.

        The per-act SPARQL costs ~2.4 s. Over a full corpus that is ~8 h of
        nothing but metadata, which is why the catalog exists: the same rows
        come back 1,000 at a time in ~1.2 s. The per-act query stays as the
        fallback for an act the catalog does not know — a norm published since
        the catalog was built, which is the daily's normal case.
        """
        rows = self._catalog().get(norm_id)
        if rows is None:
            logger.debug("%s not in catalog — falling back to per-act SPARQL", norm_id)
            result = self.get_metadata_sparql(norm_id)
        else:
            result = {"results": {"bindings": rows}}
        return json.dumps(result).encode("utf-8")

    def evict_cache(self, norm_id: str) -> None:
        """Remove a norm from the bundle cache to free memory."""
        with self._bundle_lock:
            self._bundle_cache.pop(norm_id, None)
