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

# What the catalog asks for per act.
#
# Deliberately *not* aggregated, and deliberately without the list-valued facts.
# Two roads were measured on the EEA Agreement's Annex I (21994A0103(51)):
#
#   plain columns for author + entryForce + repealedBy → >1,000 rows for that
#     one act, a whole page nothing can page past;
#   GROUP BY with GROUP_CONCAT → one row, but the grouping runs over the whole
#     87K corpus on every page and Virtuoso times out at 30 s.
#
# So the list-valued facts (authors, repealing act, subjects, last amendment)
# each get their own small query and are merged onto the act afterwards, which
# leaves this one cheap and its rows per act in the low single digits.
_CATALOG_SELECT = """SELECT ?celex ?eli ?title ?date ?entryForce ?endValidity ?force ?rtype
       ?hasCons ?eea ?signature"""

# The act itself, shared by the bulk catalog and the per-act fallback so the two
# can never drift into returning different shapes.
_ACT_PATTERN = """  ?work cdm:work_has_resource-type ?rtype .
  FILTER(?rtype IN ({types}))
  FILTER NOT EXISTS {{ ?work cdm:work_has_resource-type <RTYPE_BASECORRIGENDUM> . }}
  FILTER NOT EXISTS {{ ?work cdm:do_not_index "true"^^xsd:boolean . }}
  ?work cdm:resource_legal_id_celex ?celex .
  ?work cdm:resource_legal_in-force ?force .
  ?work cdm:work_date_document ?date .
  ?expr cdm:expression_belongs_to_work ?work .
  ?expr cdm:expression_uses_language <LANG_ENG> .
  ?expr cdm:expression_title ?title .
  ?manifest cdm:manifestation_manifests_expression ?expr .
  ?manifest cdm:manifestation_type ?mtype .
  FILTER(STR(?mtype) IN ("xhtml", "html"))
  OPTIONAL {{ ?work cdm:resource_legal_eli ?eli . }}
  OPTIONAL {{ ?work cdm:resource_legal_date_entry-into-force ?entryForce . }}
  OPTIONAL {{ ?work cdm:resource_legal_date_end-of-validity ?endValidity . }}
  OPTIONAL {{ ?work cdm:resource_legal_eea ?eea . }}
  OPTIONAL {{ ?work cdm:resource_legal_date_signature ?signature . }}
  BIND(EXISTS {{ ?cons cdm:act_consolidated_based_on_resource_legal ?work }} AS ?hasCons)""".replace(
    "RTYPE_BASE", _RTYPE_BASE
).replace("LANG_ENG", _LANG_ENG)


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
            # data_dir, not cache_dir: cache_dir is the shared HTTP response
            # cache (52,000 files and counting) and the catalog is derived data
            # about the corpus, which is what data_dir is for.
            data_dir=country_config.data_dir or "",
        )

    def __init__(
        self,
        *,
        sparql_url: str = DEFAULT_SPARQL_URL,
        request_timeout: int = 30,
        max_retries: int = 5,
        requests_per_second: float = 2.0,
        reg_types: list[str] | None = None,
        data_dir: str = "",
    ) -> None:
        super().__init__(
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
        )
        self._sparql_url = sparql_url
        self._reg_types = reg_types or DEFAULT_REG_TYPES

        self._data_dir = data_dir

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

    def _fetch_catalog(self, cache_path: Path | None = None) -> dict[str, list[dict]]:
        """Every in-scope act with its metadata, keyed by CELEX.

        One row per (act × author × entry-into-force date …), exactly as the
        per-act query returns them, so the parser cannot tell the two apart.
        """

        def build(cursor: str) -> str:
            cursor_filter = f'FILTER(STR(?celex) >= "{cursor}")' if cursor else ""
            return f"""PREFIX cdm: <{_CDM}>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
{_CATALOG_SELECT}
WHERE {{
{_ACT_PATTERN.format(types=self._rtype_uris())}
  {cursor_filter}
}}
ORDER BY ?celex
LIMIT {_CATALOG_PAGE_SIZE}"""

        catalog: dict[str, list[dict]] = {}
        for celex, rows in self._paged(build, "celex"):
            catalog[celex] = rows
        logger.info("Catalog: %d acts", len(catalog))

        # Checkpoint before enrichment. The core listing costs ~4 minutes and
        # CELLAR is intermittent — 503s and read timeouts under sustained load —
        # so a failure in one of the four enrichment queries below should not
        # throw that away. None of them is optional: authors become the
        # department, and the repealing act is what separates `repealed` from
        # `expired`, so a run that loses one must fail rather than publish
        # without it.
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            (cache_path.parent / "catalog.core.json").write_text(
                json.dumps(catalog), encoding="utf-8"
            )

        # Multi-valued facts ride in their own queries and are merged onto the
        # act's first row, so the parser reads them the same way either route.
        for celex, authors in self._fetch_authors().items():
            if celex in catalog:
                catalog[celex][0]["authors"] = {"value": "|".join(authors)}
        for celex, repealers in self._fetch_repealers().items():
            if celex in catalog:
                catalog[celex][0]["repealedBy"] = {"value": repealers[0]}
        for celex, amender in self._fetch_amendments().items():
            if celex in catalog:
                catalog[celex][0]["lastAmendment"] = {"value": amender}
        for celex, labels in self._fetch_subjects().items():
            if celex in catalog:
                catalog[celex][0]["subjects"] = {"value": "|".join(labels)}
        return catalog

    def _paged_rows(self, build_query, key: str, tiebreak: str):
        """Cursor-paged SPARQL over ``(key, tiebreak)``, yielding raw rows.

        The auxiliary queries fold their rows per act anyway, so they do not
        need the group-at-a-time guarantee ``_paged`` gives — and they do need
        to survive an act whose rows outnumber a page. The EEA Agreement's
        Annex I (21994A0103(51)) is amended by more than 1,000 acts, which a
        cursor on the act alone can never step over.

        Ordering on the pair and cutting on it lexicographically lets the
        cursor advance *inside* an act as well as between acts.
        """
        last_key = last_tie = ""
        while True:
            result = self.sparql_query(build_query(last_key, last_tie))
            bindings = result.get("results", {}).get("bindings", [])
            if not bindings:
                return
            for b in bindings:
                yield b
            if len(bindings) < _CATALOG_PAGE_SIZE:
                return
            tail = bindings[-1]
            new_key = tail.get(key, {}).get("value", "")
            new_tie = tail.get(tiebreak, {}).get("value", "")
            if (new_key, new_tie) <= (last_key, last_tie):
                return  # no forward progress; stop rather than loop
            last_key, last_tie = new_key, new_tie

    @staticmethod
    def _pair_cursor(key: str, tiebreak: str, last_key: str, last_tie: str) -> str:
        """SPARQL filter for "ordered pair strictly after (last_key, last_tie)"."""
        if not last_key:
            return ""
        return (
            f'FILTER(STR(?{key}) > "{last_key}" || '
            f'(STR(?{key}) = "{last_key}" && STR(?{tiebreak}) > "{last_tie}"))'
        )

    def _fetch_amendments(self) -> dict[str, str]:
        """CELEX → CELEX of the most recent act amending it.

        Only acts with no consolidated text need this: those are published as
        enacted, and spec v0.4 §Text state requires ``last_amendment`` on an
        as-enacted file that has been amended. 4,457 acts in scope are in that
        position — amended, but never consolidated by EUR-Lex — so without this
        they would claim to have never been touched.
        """

        def build(last_key: str, last_tie: str) -> str:
            cursor_filter = self._pair_cursor("celex", "amenderCelex", last_key, last_tie)
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
ORDER BY ?celex ?amenderCelex
LIMIT {_CATALOG_PAGE_SIZE}"""

        best_date: dict[str, str] = {}
        latest: dict[str, str] = {}
        for row in self._paged_rows(build, "celex", "amenderCelex"):
            celex = row.get("celex", {}).get("value", "")
            amender = row.get("amenderCelex", {}).get("value", "")
            when = row.get("amenderDate", {}).get("value", "")
            # CELLAR returns junk CELEX values for consolidated-text fragments
            # ("04", "B", "05" all came back for Regulation 1017/68), and the
            # spec is explicit that this field names an act in this repo.
            if not celex or not _CELEX_RE.match(amender):
                continue
            if when > best_date.get(celex, ""):
                best_date[celex] = when
                latest[celex] = amender
        logger.info("Amendments: %d acts carry a last_amendment", len(latest))
        return latest

    def _simple_pairs(self, predicate_block: str, value_var: str) -> dict[str, list[str]]:
        """CELEX → the values of one list-valued fact, in bulk.

        Every list-valued fact is fetched this way — two columns, no OPTIONALs —
        because joining them into the catalog multiplies its rows by their
        product. See the comment on _CATALOG_SELECT.
        """

        def build(last_key: str, last_tie: str) -> str:
            cursor_filter = self._pair_cursor("celex", value_var, last_key, last_tie)
            return f"""PREFIX cdm: <{_CDM}>
SELECT ?celex ?{value_var} WHERE {{
  ?work cdm:work_has_resource-type ?rtype .
  FILTER(?rtype IN ({self._rtype_uris()}))
  ?work cdm:resource_legal_id_celex ?celex .
  ?work cdm:resource_legal_in-force ?force .
{predicate_block}
  {cursor_filter}
}}
ORDER BY ?celex ?{value_var}
LIMIT {_CATALOG_PAGE_SIZE}"""

        out: dict[str, set[str]] = {}
        for row in self._paged_rows(build, "celex", value_var):
            celex = row.get("celex", {}).get("value", "")
            value = row.get(value_var, {}).get("value", "")
            if celex and value:
                out.setdefault(celex, set()).add(value)
        return {k: sorted(v) for k, v in out.items()}

    def _fetch_authors(self) -> dict[str, list[str]]:
        """CELEX → the corporate bodies that adopted it.

        An international agreement can carry one per signatory state — 21 rows
        for the EEA Agreement's Annex I on its own.
        """
        authors = self._simple_pairs("  ?work cdm:work_created_by_agent ?author .", "author")
        logger.info("Authors: %d acts", len(authors))
        return authors

    def _fetch_repealers(self) -> dict[str, list[str]]:
        """CELEX → CELEX of the acts that repeal it.

        What separates `repealed` from `expired`: 9,269 acts in scope have one.
        """
        block = (
            "  ?repealer cdm:resource_legal_repeals_resource_legal ?work .\n"
            "  ?repealer cdm:resource_legal_id_celex ?repealedBy ."
        )
        repealers = self._simple_pairs(block, "repealedBy")
        logger.info("Repealers: %d acts have one", len(repealers))
        return repealers

    def _merge_list_facts(self, celex: str, result: dict) -> None:
        """Attach the list-valued facts to a per-act result.

        The fallback path has to end up with the same fields the catalog path
        produces, or an act served by one route would silently lose its authors
        and its repealing act.
        """
        bindings = result.get("results", {}).get("bindings", [])
        if not bindings:
            return
        authors = self._simple_pairs(
            f'  ?work cdm:work_created_by_agent ?author .\n  FILTER(STR(?celex) = "{celex}")',
            "author",
        ).get(celex, [])
        if authors:
            bindings[0]["authors"] = {"value": "|".join(authors)}

    def _fetch_eurovoc_labels(self) -> dict[str, str]:
        """EuroVoc concept URI → its English label.

        Fetched once for the whole vocabulary (~7,000 concepts) rather than
        joined per act: asking for the label alongside every (act, concept) pair
        made Virtuoso answer 503, because the language filter then runs over
        hundreds of thousands of rows instead of the concept list.
        """

        def build(last_key: str, last_tie: str) -> str:
            cursor_filter = self._pair_cursor("concept", "label", last_key, last_tie)
            return f"""PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?concept ?label WHERE {{
  ?concept skos:inScheme <http://eurovoc.europa.eu/100141> .
  ?concept skos:prefLabel ?label .
  FILTER(LANG(?label) = "en")
  {cursor_filter}
}}
ORDER BY ?concept ?label
LIMIT {_CATALOG_PAGE_SIZE}"""

        labels: dict[str, str] = {}
        for row in self._paged_rows(build, "concept", "label"):
            concept = row.get("concept", {}).get("value", "")
            label = row.get("label", {}).get("value", "")
            if concept and label:
                labels.setdefault(concept, label)
        logger.info("EuroVoc: %d concept labels", len(labels))
        return labels

    def _fetch_subjects(self) -> dict[str, list[str]]:
        """CELEX → EuroVoc labels, the source's own subject vocabulary."""
        concepts = self._simple_pairs(
            "  ?work cdm:work_is_about_concept_eurovoc ?concept .", "concept"
        )
        if not concepts:
            return {}
        labels = self._fetch_eurovoc_labels()
        subjects = {
            celex: sorted({labels[c] for c in uris if c in labels})
            for celex, uris in concepts.items()
        }
        subjects = {k: v for k, v in subjects.items() if v}
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
            self._catalog_data = self._fetch_catalog(cache_path=cached)
            if cached is not None:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps(self._catalog_data), encoding="utf-8")
            return self._catalog_data

    def _catalog_path(self) -> Path | None:
        if not self._data_dir:
            return None
        return Path(self._data_dir) / "catalog.json"

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
        """Metadata for one act, straight from SPARQL.

        Shares _ACT_PATTERN and _AGGREGATED_SELECT with the bulk catalog so both
        routes return the identical shape — the parser must not be able to tell
        which one served it.
        """
        query = f"""PREFIX cdm: <{_CDM}>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
{_CATALOG_SELECT}
WHERE {{
{_ACT_PATTERN.format(types=self._rtype_uris())}
  FILTER(STR(?celex) = "{celex}")
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
            self._merge_list_facts(norm_id, result)
        else:
            result = {"results": {"bindings": rows}}
        return json.dumps(result).encode("utf-8")

    def evict_cache(self, norm_id: str) -> None:
        """Remove a norm from the bundle cache to free memory."""
        with self._bundle_lock:
            self._bundle_cache.pop(norm_id, None)
