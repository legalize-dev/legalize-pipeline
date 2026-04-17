"""Fedlex HTTP client — Switzerland.

Two complementary interfaces, same host:

1. **SPARQL endpoint** (``fedlex.data.admin.ch/sparqlendpoint``) — Virtuoso.
   Used for discovery, consolidation listing, manifestation URL resolution
   and controlled-vocabulary label lookup. GET only, requires
   ``Accept: application/json``.

2. **Filestore** (``fedlex.data.admin.ch/filestore/...``) — plain HTTPS.
   Serves the Akoma Ntoso 3.0 XML files. Paths are NOT fully deterministic
   (include a build-version suffix like ``-xml-10.xml``) so we must ask
   SPARQL for each URL.

**Historical versioning** — Fedlex reuses the Luxembourg JOLux data model.
Each ``jolux:ConsolidationAbstract`` (cc/YYYY/N) groups all point-in-time
``jolux:Consolidation`` nodes (cc/YYYY/N/YYYYMMDD). Each Consolidation has
``jolux:dateApplicability`` — the version's effective date that drives
``GIT_AUTHOR_DATE``. ``get_text`` bundles every DE XML consolidation into
a ``<fedlex-multi-version>`` envelope so the parser emits one ``Version``
per historical state and the pipeline writes one git commit per reform.

**Known limitation** — Akoma Ntoso XML only covers ~5,139 of 17,258 cc
laws (earliest XML consolidations start around 2011; pre-2021 coverage is
patchy). We silently skip laws with no DE XML and record
``extra.history_from`` per law so a reader can tell v1 history is
truncated. A DOCX-fallback pass is a documented v2 follow-up.

No authentication. Licensing: Swiss federal law texts are in the public
domain under URG Art. 5.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
from typing import TYPE_CHECKING
from urllib.parse import quote

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

DEFAULT_SPARQL_URL = "https://fedlex.data.admin.ch/sparqlendpoint"
DEFAULT_FILESTORE_URL = "https://fedlex.data.admin.ch/filestore"
DEFAULT_LANGUAGE = "de"

# JOLux ontology (reused verbatim from Luxembourg)
JOLUX_NS = "http://data.legilux.public.lu/resource/ontology/jolux#"
SKOS_NS = "http://www.w3.org/2004/02/skos/core#"

# Fedlex-specific controlled-vocabulary roots
VOCAB_BASE = "https://fedlex.data.admin.ch/vocabulary"
ELI_BASE = "https://fedlex.data.admin.ch/eli/"

# publications.europa.eu language authority (shared with CELLAR)
EU_LANG_BASE = "http://publications.europa.eu/resource/authority/language"
EU_LANG = {
    "de": "DEU",
    "fr": "FRA",
    "it": "ITA",
    "en": "ENG",
    "rm": "ROH",
}

# User-format vocabulary
USER_FORMAT_XML = f"{VOCAB_BASE}/user-format/xml"
USER_FORMAT_PDF = f"{VOCAB_BASE}/user-format/pdf-a"

# Cap historical versions per law to bound bootstrap cost. Most laws have
# 0-5 XML consolidations; a very few may have 50+ once back-fill catches up.
MAX_VERSIONS_PER_LAW = 200

# Cursor pagination page size — Virtuoso 10K sort-window cap limits us to
# 5000/page when combined with the cursor filter.
SPARQL_PAGE_SIZE = 5000


def eli_url_to_norm_id(eli_uri: str) -> str:
    """Convert a Fedlex ELI URI to a filesystem-safe norm ID.

    Keeps underscores (legacy IDs like ``cc/24/233_245_233``). Only ``/``
    and protocol prefix are stripped.

    ``https://fedlex.data.admin.ch/eli/cc/1999/404``
    → ``cc-1999-404``

    ``https://fedlex.data.admin.ch/eli/cc/24/233_245_233``
    → ``cc-24-233_245_233``
    """
    path = eli_uri.removeprefix("https://").removeprefix("http://")
    path = path.removeprefix("fedlex.data.admin.ch/")
    path = path.removeprefix("eli/")
    # Strip an optional trailing "_cc" marker that appears on a handful of
    # URIs where the CCA ELI is written as "cc/2020/0937_cc" by Fedlex.
    if path.endswith("_cc"):
        path = path[:-3]
    return path.replace("/", "-")


def norm_id_to_eli_url(norm_id: str) -> str:
    """Reverse of ``eli_url_to_norm_id`` — reconstruct the CCA ELI URI.

    ``cc-1999-404`` → ``https://fedlex.data.admin.ch/eli/cc/1999/404``

    Only the first TWO ``-`` after the branch prefix are split: the rest of
    the identifier keeps its underscores and the original numeric shape.
    """
    if not norm_id:
        return ""
    parts = norm_id.split("-", 2)
    if len(parts) < 3:
        return f"{ELI_BASE}{norm_id.replace('-', '/')}"
    branch, year, rest = parts
    return f"{ELI_BASE}{branch}/{year}/{rest}"


class FedlexClient(HttpClient):
    """Client for Switzerland's Fedlex corpus via SPARQL + filestore."""

    @classmethod
    def create(cls, country_config: CountryConfig) -> FedlexClient:
        source = country_config.source or {}
        return cls(
            sparql_url=source.get("sparql_url", DEFAULT_SPARQL_URL),
            filestore_url=source.get("filestore_url", DEFAULT_FILESTORE_URL),
            language=source.get("language", DEFAULT_LANGUAGE),
            request_timeout=int(source.get("request_timeout", 30)),
            max_retries=int(source.get("max_retries", 5)),
            requests_per_second=float(source.get("requests_per_second", 2.0)),
        )

    def __init__(
        self,
        *,
        sparql_url: str = DEFAULT_SPARQL_URL,
        filestore_url: str = DEFAULT_FILESTORE_URL,
        language: str = DEFAULT_LANGUAGE,
        request_timeout: int = 30,
        max_retries: int = 5,
        requests_per_second: float = 2.0,
    ) -> None:
        super().__init__(
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
            extra_headers={"Accept": "application/json"},
        )
        self._sparql_url = sparql_url
        self._filestore_url = filestore_url.rstrip("/")
        if language not in EU_LANG:
            raise ValueError(
                f"Unsupported Fedlex language {language!r}; expected one of {sorted(EU_LANG)}"
            )
        self._language = language
        self._language_uri = f"{EU_LANG_BASE}/{EU_LANG[language]}"

        # norm_id → bundled multi-version XML bytes
        self._bundle_cache: dict[str, bytes] = {}
        self._bundle_lock = threading.Lock()

        # Lazy-loaded controlled-vocabulary labels
        self._rank_labels: dict[str, str] | None = None
        self._institution_labels: dict[str, str] | None = None
        self._vocab_lock = threading.Lock()

    # ─────────────────────────────────────────
    # SPARQL
    # ─────────────────────────────────────────

    def sparql_query(self, query: str) -> dict:
        """Execute a SPARQL SELECT and return parsed JSON results.

        The Fedlex endpoint accepts GET only. The ``Accept`` header is set
        once on the session; the ``format`` query-param is ignored by
        Virtuoso. Keeping the query in the URL (not POST) also plays well
        with the shared retry/rate-limit logic on ``HttpClient``.
        """
        url = f"{self._sparql_url}?query={quote(query)}"
        data = self._get(url)
        return json.loads(data)

    def get_consolidations(self, cca_uri: str) -> list[dict]:
        """Return all consolidations of one law with the best-format URL.

        Each result is
        ``{uri, date_applicability, date_end, url, format}``, ordered
        oldest → newest. Format is ``"xml"`` when an Akoma Ntoso
        manifestation exists in the requested language for that
        consolidation, otherwise ``"pdf"`` when only a PDF-A exists.
        Consolidations that have NEITHER XML nor PDF-A in the requested
        language are filtered out.

        A single SPARQL query pulls both formats per version with
        ``OPTIONAL`` clauses; we pick XML at aggregation time so the
        client only does one round-trip per law.
        """
        query = f"""PREFIX jolux: <{JOLUX_NS}>
SELECT DISTINCT ?consol ?dateAppl ?dateEnd ?xmlUrl ?pdfUrl WHERE {{
  GRAPH ?g {{
    ?consol a jolux:Consolidation .
    ?consol jolux:isMemberOf <{cca_uri}> .
    OPTIONAL {{ ?consol jolux:dateApplicability ?dateAppl }}
    OPTIONAL {{ ?consol jolux:dateEndApplicability ?dateEnd }}
    ?consol jolux:isRealizedBy ?expr .
    ?expr jolux:language <{self._language_uri}> .
    OPTIONAL {{
      ?expr jolux:isEmbodiedBy ?xmlManif .
      ?xmlManif jolux:userFormat <{USER_FORMAT_XML}> .
      ?xmlManif jolux:isExemplifiedBy ?xmlUrl .
    }}
    OPTIONAL {{
      ?expr jolux:isEmbodiedBy ?pdfManif .
      ?pdfManif jolux:userFormat <{USER_FORMAT_PDF}> .
      ?pdfManif jolux:isExemplifiedBy ?pdfUrl .
    }}
  }}
}}
ORDER BY ?dateAppl"""
        result = self.sparql_query(query)
        out: list[dict] = []
        for binding in result.get("results", {}).get("bindings", []):
            xml_url = binding.get("xmlUrl", {}).get("value")
            pdf_url = binding.get("pdfUrl", {}).get("value")
            # Prefer XML; fall back to PDF-A; skip versions with neither.
            if xml_url:
                url, fmt = xml_url, "xml"
            elif pdf_url:
                url, fmt = pdf_url, "pdf"
            else:
                continue
            out.append(
                {
                    "uri": binding["consol"]["value"],
                    "date_applicability": binding.get("dateAppl", {}).get("value"),
                    "date_end_applicability": binding.get("dateEnd", {}).get("value"),
                    "url": url,
                    "format": fmt,
                }
            )
        return out

    def get_cca_metadata(self, cca_uri: str) -> dict:
        """Fetch all JOLux predicates on the ConsolidationAbstract level.

        Also includes the DE Expression's ``title`` / ``titleShort`` and the
        ``basicAct``'s publication info. Returns a dict of
        ``predicate_local_name → [values]`` (values are strings).
        """
        # 1. Predicates on the CCA itself
        cca_q = f"""SELECT ?p ?o WHERE {{
  GRAPH ?g {{
    <{cca_uri}> ?p ?o .
  }}
}}"""
        cca_rows = self.sparql_query(cca_q).get("results", {}).get("bindings", [])

        # 2. Predicates on the language expression of the CCA (title, titleShort)
        expr_uri = f"{cca_uri}/{self._language}"
        expr_q = f"""SELECT ?p ?o WHERE {{
  GRAPH ?g {{
    <{expr_uri}> ?p ?o .
  }}
}}"""
        expr_rows = self.sparql_query(expr_q).get("results", {}).get("bindings", [])

        out: dict[str, list[str]] = {}
        for row in cca_rows + expr_rows:
            pred = row["p"]["value"]
            key = pred.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
            out.setdefault(key, []).append(row["o"]["value"])

        # 3. Follow basicAct one hop to get the original publication metadata
        basic_acts = out.get("basicAct", [])
        if basic_acts:
            ba_uri = basic_acts[0]
            ba_q = f"""SELECT ?p ?o WHERE {{
  GRAPH ?g {{
    <{ba_uri}> ?p ?o .
  }}
}}"""
            for row in self.sparql_query(ba_q).get("results", {}).get("bindings", []):
                pred = row["p"]["value"]
                key = "basicAct_" + pred.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                out.setdefault(key, []).append(row["o"]["value"])

        return out

    # ─────────────────────────────────────────
    # Vocabulary label caches (lazy, thread-safe)
    # ─────────────────────────────────────────

    def _load_labels(self, vocab_segment: str) -> dict[str, str]:
        """SKOS-prefLabel lookup for a controlled-vocabulary segment."""
        prefix = f"{VOCAB_BASE}/{vocab_segment}/"
        query = f"""PREFIX skos: <{SKOS_NS}>
SELECT ?s ?label WHERE {{
  ?s skos:prefLabel ?label .
  FILTER (STRSTARTS(STR(?s), "{prefix}"))
  FILTER (LANG(?label) = "{self._language}")
}}"""
        out: dict[str, str] = {}
        for row in self.sparql_query(query).get("results", {}).get("bindings", []):
            uri = row["s"]["value"]
            out[uri] = row["label"]["value"]
        return out

    def rank_label(self, type_uri: str) -> str:
        """Human-readable label for a ``jolux:typeDocument`` URI.

        Returns the DE prefLabel (e.g. ``Bundesgesetz``, ``Verordnung des
        Bundesrates``). Falls back to the URI's trailing segment if the
        label cache doesn't know it.
        """
        with self._vocab_lock:
            if self._rank_labels is None:
                self._rank_labels = self._load_labels("resource-type")
        return self._rank_labels.get(type_uri, type_uri.rsplit("/", 1)[-1])

    def institution_label(self, inst_uri: str) -> str:
        """Human-readable label for a ``jolux:responsibilityOf`` URI."""
        with self._vocab_lock:
            if self._institution_labels is None:
                self._institution_labels = self._load_labels("legal-institution")
        return self._institution_labels.get(inst_uri, inst_uri.rsplit("/", 1)[-1])

    # ─────────────────────────────────────────
    # Filestore
    # ─────────────────────────────────────────

    def download_xml(self, file_url: str) -> bytes:
        """Download an XML manifestation from the Fedlex filestore."""
        url = file_url.replace("http://", "https://")
        return self._get(url, headers={"Accept": "application/xml, */*"})

    def download_pdf(self, file_url: str) -> bytes:
        """Download a PDF-A manifestation from the Fedlex filestore."""
        url = file_url.replace("http://", "https://")
        return self._get(url, headers={"Accept": "application/pdf, */*"})

    # ─────────────────────────────────────────
    # LegislativeClient interface
    # ─────────────────────────────────────────

    def get_text(self, norm_id: str) -> bytes:
        """Fetch the full history of a law as a multi-version envelope.

        Returns a ``<fedlex-multi-version>`` XML document. Each child
        ``<version>`` carries:

        - ``format="xml"`` or ``format="pdf"`` — the underlying
          manifestation for that consolidation.
        - ``effective-date="YYYY-MM-DD"`` — ``jolux:dateApplicability``.
        - ``end-date="YYYY-MM-DD"`` (optional) — ``jolux:dateEndApplicability``.

        For ``format="xml"`` versions the Akoma Ntoso root is inlined
        directly. For ``format="pdf"`` versions the raw PDF bytes are
        base64-encoded inside the ``<version>`` element (PDFs are
        binary and cannot be inlined as XML text). The parser decodes
        them and hands them to the pdfplumber-based PDF parser.

        Versions are ordered oldest → newest. We mix XML and PDF freely
        so the git history of a single law walks seamlessly across
        format boundaries.

        If the law has NO consolidation with either format we raise
        ``ValueError`` — the pipeline catches it and skips the norm.
        """
        with self._bundle_lock:
            cached = self._bundle_cache.get(norm_id)
        if cached is not None:
            return cached

        cca_uri = norm_id_to_eli_url(norm_id)
        consolidations = self.get_consolidations(cca_uri)

        if not consolidations:
            raise ValueError(f"No DE XML or PDF consolidations for {norm_id} ({cca_uri})")

        if len(consolidations) > MAX_VERSIONS_PER_LAW:
            logger.info(
                "%s has %d consolidation versions, truncating to most recent %d",
                norm_id,
                len(consolidations),
                MAX_VERSIONS_PER_LAW,
            )
            consolidations = consolidations[-MAX_VERSIONS_PER_LAW:]

        pieces: list[bytes] = [
            b"<?xml version='1.0' encoding='UTF-8'?>\n<fedlex-multi-version norm-id='",
            norm_id.encode("utf-8"),
            b"' language='",
            self._language.encode("utf-8"),
            b"'>\n",
        ]
        for consol in consolidations:
            date_str = consol.get("date_applicability") or "unknown"
            fmt = consol.get("format") or "xml"
            url = consol.get("url")
            if not url:
                continue
            try:
                if fmt == "pdf":
                    payload = self.download_pdf(url)
                else:
                    payload = self.download_xml(url)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to download %s consolidation %s of %s: %s",
                    fmt,
                    date_str,
                    norm_id,
                    exc,
                )
                continue
            end_attr = ""
            if consol.get("date_end_applicability"):
                end_attr = f" end-date='{consol['date_end_applicability']}'"
            pieces.append(
                f"<version type='consolidation' effective-date='{date_str}'"
                f" format='{fmt}'{end_attr}>\n".encode("utf-8")
            )
            if fmt == "pdf":
                # Wrap binary PDFs in a base64 element. The parser
                # decodes this back to raw bytes and feeds it to
                # pdfplumber. Non-base64 elements in the envelope are
                # XML content inlined verbatim.
                pieces.append(b"<pdf-base64>")
                pieces.append(base64.b64encode(payload))
                pieces.append(b"</pdf-base64>")
            else:
                inner = payload
                if inner.startswith(b"<?xml"):
                    idx = inner.find(b"?>")
                    if idx >= 0:
                        inner = inner[idx + 2 :].lstrip()
                pieces.append(inner)
            pieces.append(b"\n</version>\n")
        pieces.append(b"</fedlex-multi-version>\n")
        data = b"".join(pieces)

        with self._bundle_lock:
            self._bundle_cache[norm_id] = data
        return data

    def get_metadata(self, norm_id: str) -> bytes:
        """Fetch metadata for a norm.

        The Akoma Ntoso manifestation is self-contained for FRBR metadata
        (titles, dates, language, country, SR-number). We return the bundle
        and let ``FedlexMetadataParser`` enrich from the SPARQL side when it
        needs ``rank`` labels, institution, taxonomy subjects, basicAct.
        """
        return self.get_text(norm_id)

    def evict_cache(self, norm_id: str) -> None:
        """Drop a norm from the bundle cache to free memory."""
        with self._bundle_lock:
            self._bundle_cache.pop(norm_id, None)
