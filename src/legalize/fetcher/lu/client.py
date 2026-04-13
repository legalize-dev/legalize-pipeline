"""Legilux HTTP client — Luxembourg.

Two complementary interfaces:

1. **SPARQL endpoint** (`data.legilux.public.lu/sparqlendpoint`) — used for
   discovery and metadata queries. Returns JSON (application/json). GET only.

2. **Filestore** (`data.legilux.public.lu/filestore/...`) — hosts the actual
   XML files (Akoma Ntoso) for each Act and Consolidation. Direct HTTPS GET.

**Historical versioning** — Luxembourg's JOLux data model groups an original
Act and all its Consolidations under a shared Complex Work URI. Each
Consolidation has a ``dateApplicability`` field that serves as the version's
effective date. ``get_text`` bundles the original Act XML + all Consolidation
XMLs into a ``<legilux-multi-version>`` envelope so the parser can emit
multi-``Version`` blocks and the pipeline generates one git commit per reform.

The SPARQL endpoint and filestore are both public, no auth, license CC BY 4.0.
No documented rate limits.
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

DEFAULT_SPARQL_URL = "https://data.legilux.public.lu/sparqlendpoint"
DEFAULT_FILESTORE_URL = "https://data.legilux.public.lu/filestore"

# Cap historical versions per law to bound bootstrap cost. Most laws have
# 0-5 consolidation versions; a few codes have 50+.
MAX_VERSIONS_PER_LAW = 200

# Types of Acts to include in discovery (primary legislation scope v1)
DEFAULT_DOC_TYPES = [
    "LOI",
    "RGD",
    "Constitution",
]

_ELI_BASE = "http://data.legilux.public.lu/eli/etat/"
_FILESTORE_BASE = "https://data.legilux.public.lu/filestore"


def _eli_to_xml_url(eli_uri: str) -> str:
    """Deterministically construct the filestore XML URL from an ELI URI.

    The Legilux filestore follows a fixed pattern:
    ``{filestore}/{eli_path}/fr/xml/{eli_path_dashed}-fr-xml.xml``

    This avoids a SPARQL query per norm to resolve the XML URL.
    """
    eli_path = eli_uri.replace("http://data.legilux.public.lu/", "")
    filename = eli_path.replace("/", "-") + "-fr-xml.xml"
    return f"{_FILESTORE_BASE}/{eli_path}/fr/xml/{filename}"


def _eli_to_complex_work(eli_uri: str) -> str:
    """Derive the Complex Work URI from an Act ELI URI.

    The Complex Work is the Act URI without the trailing ``/jo``.
    ``eli/etat/leg/loi/2022/05/27/a250/jo`` → ``eli/etat/leg/loi/2022/05/27/a250``
    """
    if eli_uri.endswith("/jo"):
        return eli_uri[:-3]
    return eli_uri


def _eli_to_norm_id(eli_uri: str) -> str:
    """Convert an ELI URI to a filesystem-safe norm ID.

    ``http://data.legilux.public.lu/eli/etat/leg/loi/2022/05/27/a250/jo``
    → ``leg-loi-2022-05-27-a250``
    """
    # Strip base and trailing /jo
    path = eli_uri
    prefix = "http://data.legilux.public.lu/eli/etat/"
    if path.startswith(prefix):
        path = path[len(prefix) :]
    if path.endswith("/jo"):
        path = path[:-3]
    return path.replace("/", "-")


def _norm_id_to_eli(norm_id: str) -> str:
    """Reverse of _eli_to_norm_id — reconstruct the ELI URI.

    ``leg-loi-2022-05-27-a250``
    → ``http://data.legilux.public.lu/eli/etat/leg/loi/2022/05/27/a250/jo``
    """
    # The norm_id encodes: branch-type-YYYY-MM-DD-memorial
    # We need to reconstruct: eli/etat/branch/type/YYYY/MM/DD/memorial/jo
    parts = norm_id.split("-")
    # branch is first part (leg or adm)
    # type is second part (loi, rgd, constitution, etc.)
    # date is parts[2:5] (YYYY, MM, DD)
    # memorial is parts[5] (a250, n1, etc.)
    # But type may contain multiple words... "constitution" has no date parts
    # Need a smarter approach: reconstruct by position

    # For Constitution: leg-constitution-1868-10-17-n1
    # For LOI: leg-loi-2022-05-27-a250
    # For RGD: leg-rgd-2026-04-02-a185
    # Pattern: branch-type-YYYY-MM-DD-memorial (6+ parts)

    # Handle the general case: find the date (4-digit year)
    branch = parts[0]
    # Find where the date starts (first 4-digit part)
    date_idx = None
    for i in range(1, len(parts)):
        if len(parts[i]) == 4 and parts[i].isdigit():
            date_idx = i
            break

    if date_idx is None:
        raise ValueError(f"Cannot reconstruct ELI from norm_id: {norm_id}")

    doc_type = "-".join(parts[1:date_idx])  # could be multi-word like "constitution"
    # The ELI uses underscores for multi-word types, not hyphens
    # Actually, looking at real ELIs: constitution uses no separator
    # leg/constitution/1868/10/17/n1/jo
    # But in our norm_id it's leg-constitution-1868-10-17-n1

    year = parts[date_idx]
    month = parts[date_idx + 1]
    day = parts[date_idx + 2]
    memorial = "-".join(parts[date_idx + 3 :])  # usually just one part like "a250"

    path = f"eli/etat/{branch}/{doc_type}/{year}/{month}/{day}/{memorial}/jo"
    return f"http://data.legilux.public.lu/{path}"


class LegiluxClient(HttpClient):
    """Client for Luxembourg's Legilux corpus via SPARQL + filestore.

    The Legilux open data platform (Casemates) exposes:
    - A SPARQL endpoint (Virtuoso) for structured queries over the JOLux ontology
    - An HTTPS filestore for downloading Akoma Ntoso XML files
    """

    @classmethod
    def create(cls, country_config: CountryConfig) -> LegiluxClient:
        source = country_config.source or {}
        return cls(
            sparql_url=source.get("sparql_url", DEFAULT_SPARQL_URL),
            filestore_url=source.get("filestore_url", DEFAULT_FILESTORE_URL),
            request_timeout=int(source.get("request_timeout", 30)),
            max_retries=int(source.get("max_retries", 5)),
            requests_per_second=float(source.get("requests_per_second", 2.0)),
            doc_types=source.get("doc_types", DEFAULT_DOC_TYPES),
        )

    def __init__(
        self,
        *,
        sparql_url: str = DEFAULT_SPARQL_URL,
        filestore_url: str = DEFAULT_FILESTORE_URL,
        request_timeout: int = 30,
        max_retries: int = 5,
        requests_per_second: float = 2.0,
        doc_types: list[str] | None = None,
    ) -> None:
        super().__init__(
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
        )
        self._sparql_url = sparql_url
        self._filestore_url = filestore_url.rstrip("/")
        self._doc_types = doc_types or DEFAULT_DOC_TYPES

        # Cache: norm_id → bundled XML bytes
        self._bundle_cache: dict[str, bytes] = {}
        self._bundle_lock = threading.Lock()

    # ─────────────────────────────────────────
    # SPARQL queries
    # ─────────────────────────────────────────

    def sparql_query(self, query: str) -> dict:
        """Execute a SPARQL SELECT query and return parsed JSON results.

        The endpoint only accepts GET requests. The query is URL-encoded
        and passed as the ``query`` parameter.
        """
        url = f"{self._sparql_url}?query={quote(query)}&format=application/json"
        data = self._get(url)
        return json.loads(data)

    def get_xml_url(self, act_uri: str) -> str | None:
        """Get the filestore XML download URL for an Act or Consolidation.

        Queries the SPARQL endpoint for the XML manifestation's exemplified URL.
        """
        graph_uri = f"{act_uri}/graph"
        query = f"""PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
SELECT ?fileUrl WHERE {{
  GRAPH <{graph_uri}> {{
    <{act_uri}> jolux:isRealizedBy ?expr .
    ?expr jolux:isEmbodiedBy ?manif .
    ?manif jolux:format <http://publications.europa.eu/resource/authority/file-type/XML> .
    ?manif jolux:isExemplifiedBy ?fileUrl .
  }}
}}
LIMIT 1"""
        result = self.sparql_query(query)
        bindings = result.get("results", {}).get("bindings", [])
        if bindings:
            return bindings[0]["fileUrl"]["value"]
        return None

    def get_consolidations(self, complex_work_uri: str) -> list[dict]:
        """Get all consolidation versions for a Complex Work.

        Returns a list of dicts with keys:
        - ``uri``: consolidation ELI URI
        - ``date_applicability``: effective date string (YYYY-MM-DD)
        - ``date_end_applicability``: end date string or None
        - ``xml_url``: filestore XML URL
        """
        query = f"""PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
SELECT ?consol ?dateApplicability ?dateEndApplicability ?xmlUrl WHERE {{
  GRAPH ?g {{
    ?consol a jolux:Consolidation .
    ?consol jolux:isMemberOf <{complex_work_uri}> .
    OPTIONAL {{ ?consol jolux:dateApplicability ?dateApplicability }}
    OPTIONAL {{ ?consol jolux:dateEndApplicability ?dateEndApplicability }}
    ?consol jolux:isRealizedBy ?expr .
    ?expr jolux:isEmbodiedBy ?manif .
    ?manif jolux:format <http://publications.europa.eu/resource/authority/file-type/XML> .
    ?manif jolux:isExemplifiedBy ?xmlUrl .
  }}
}}
ORDER BY ?dateApplicability"""
        result = self.sparql_query(query)
        consolidations = []
        for binding in result.get("results", {}).get("bindings", []):
            consol = {
                "uri": binding["consol"]["value"],
                "date_applicability": binding.get("dateApplicability", {}).get("value"),
                "date_end_applicability": binding.get("dateEndApplicability", {}).get("value"),
                "xml_url": binding.get("xmlUrl", {}).get("value"),
            }
            if consol["xml_url"]:
                consolidations.append(consol)
        return consolidations

    def get_complex_work_uri(self, act_uri: str) -> str | None:
        """Get the Complex Work URI for an Act via its graph."""
        graph_uri = f"{act_uri}/graph"
        query = f"""PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
SELECT ?complexWork WHERE {{
  GRAPH <{graph_uri}> {{
    <{act_uri}> jolux:isMemberOf ?complexWork .
  }}
}}
LIMIT 1"""
        result = self.sparql_query(query)
        bindings = result.get("results", {}).get("bindings", [])
        if bindings:
            return bindings[0]["complexWork"]["value"]
        return None

    # ─────────────────────────────────────────
    # Filestore downloads
    # ─────────────────────────────────────────

    def download_xml(self, file_url: str) -> bytes:
        """Download an XML file from the Legilux filestore.

        Follows HTTP→HTTPS redirects (the SPARQL endpoint returns http:// URLs
        but the filestore requires https://).
        """
        # Ensure HTTPS
        url = file_url.replace("http://", "https://")
        return self._get(url)

    # ─────────────────────────────────────────
    # LegislativeClient interface
    # ─────────────────────────────────────────

    def get_text(self, norm_id: str) -> bytes:
        """Fetch the full history of a law as a bundled multi-version envelope.

        Returns a ``<legilux-multi-version>`` XML document whose children are
        ``<version>`` elements wrapping the Akoma Ntoso root of each historical
        version, annotated with ``effective-date`` and ``type`` attributes.

        If the law has no consolidation history, returns the raw Akoma Ntoso
        XML of the original Act.

        **Optimization:** the XML URL and Complex Work URI are derived
        deterministically from the ELI URI, avoiding 2 SPARQL queries per norm.
        Only the consolidation query (when applicable) hits SPARQL.
        """
        with self._bundle_lock:
            cached = self._bundle_cache.get(norm_id)
        if cached is not None:
            return cached

        act_uri = _norm_id_to_eli(norm_id)

        # 1. Get the original Act XML (deterministic URL — no SPARQL needed)
        xml_url = _eli_to_xml_url(act_uri)
        original_xml = self.download_xml(xml_url)

        # 2. Look for consolidation versions (Complex Work derived from ELI)
        complex_work_uri = _eli_to_complex_work(act_uri)
        consolidations = self.get_consolidations(complex_work_uri)

        if not consolidations:
            # No history — return raw XML
            with self._bundle_lock:
                self._bundle_cache[norm_id] = original_xml
            return original_xml

        # 3. Cap runaway version chains
        if len(consolidations) > MAX_VERSIONS_PER_LAW:
            logger.info(
                "%s has %d consolidation versions, truncating to most recent %d",
                norm_id,
                len(consolidations),
                MAX_VERSIONS_PER_LAW,
            )
            consolidations = consolidations[-MAX_VERSIONS_PER_LAW:]

        # 4. Bundle into multi-version envelope
        pieces: list[bytes] = [
            b"<?xml version='1.0' encoding='UTF-8'?>\n<legilux-multi-version norm-id='",
            norm_id.encode("utf-8"),
            b"'>\n",
        ]

        # Add original as first version (type=original)
        pieces.append(b"<version type='original'>\n")
        inner = original_xml
        if inner.startswith(b"<?xml"):
            idx = inner.find(b"?>")
            if idx >= 0:
                inner = inner[idx + 2 :].lstrip()
        pieces.append(inner)
        pieces.append(b"\n</version>\n")

        # Add each consolidation version
        for consol in consolidations:
            date_str = consol["date_applicability"] or "unknown"
            try:
                consol_xml = self.download_xml(consol["xml_url"])
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to download consolidation %s of %s: %s",
                    date_str,
                    norm_id,
                    exc,
                )
                continue

            pieces.append(
                f"<version type='consolidation' effective-date='{date_str}'>\n".encode("utf-8")
            )
            inner = consol_xml
            if inner.startswith(b"<?xml"):
                idx = inner.find(b"?>")
                if idx >= 0:
                    inner = inner[idx + 2 :].lstrip()
            pieces.append(inner)
            pieces.append(b"\n</version>\n")

        pieces.append(b"</legilux-multi-version>\n")
        data = b"".join(pieces)

        with self._bundle_lock:
            self._bundle_cache[norm_id] = data
        return data

    def get_metadata(self, norm_id: str) -> bytes:
        """Fetch metadata for a norm.

        In Legilux, metadata is embedded in the same Akoma Ntoso XML as the
        text. We return the bundled XML (same as get_text) so the metadata
        parser can extract from it.
        """
        return self.get_text(norm_id)

    def evict_cache(self, norm_id: str) -> None:
        """Remove a norm from the bundle cache to free memory."""
        with self._bundle_lock:
            self._bundle_cache.pop(norm_id, None)
