"""BWB (Basis Wetten Bestand) HTTP client — Netherlands.

Two complementary interfaces:

1. **SRU search API** (`zoekservice.overheid.nl/sru/Search`) — used for discovery.
   Returns metadata records with direct XML download URLs. Supports CQL query
   syntax with operators `=`, `==`, `<`, `>`, `<=`, `>=`.

2. **Repository** (`repository.officiele-overheidspublicaties.nl/bwb/`) — used
   to download the full XML of a law's expressions. The manifest at
   `/bwb/{BWB_ID}/` lists every historical ``<expression>`` with an
   ``_latestItem`` attribute pointing at the current expression.

**Historical versioning** — the BWB repository preserves every expression of
every law, so ``get_text`` returns a **bundled multi-expression envelope** by
default: every expression listed in the manifest is downloaded and wrapped in
a ``<bwb-multi-expression>`` root so the parser can emit multi-``Version``
blocks and the pipeline can generate one git commit per historical reform.
Call ``get_latest_xml`` if you need only the current toestand.

Both services are public, no auth, license CC0. Polite rate default: 2 req/s.

References:
- SRU manual: https://www.overheid.nl/sites/default/files/pdf/Handleiding+SRU+BWB.pdf
- Repository layout guide:
  https://www.overheid.nl/help/wet-en-regelgeving/een-eigen-kopie-van-het-basiswettenbestand-opbouwen
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING
from urllib.parse import quote
from xml.etree import ElementTree as ET

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

DEFAULT_SRU_URL = "https://zoekservice.overheid.nl/sru/Search"
DEFAULT_REPO_URL = "https://repository.officiele-overheidspublicaties.nl/bwb"
DEFAULT_PORTAL_URL = "https://wetten.overheid.nl"

# Upper cap on the number of historical expressions downloaded per law during
# bootstrap. A handful of laws (e.g. the Income Tax Act) have 70+ expressions
# which is fine, but some legacy chains go into the hundreds and mostly reflect
# trivial editorial re-issues. A cap of 200 keeps the worst-case cost bounded.
MAX_EXPRESSIONS_PER_LAW = 200


class BWBClient(HttpClient):
    """Client for the Netherlands BWB corpus via SRU + repository.

    The BWB is exposed as two services:
    - SRU search endpoint for metadata + XML URLs (discovery)
    - HTTPS repository for the raw XML "toestand" files (text + metadata)
    """

    @classmethod
    def create(cls, country_config: CountryConfig) -> BWBClient:
        source = country_config.source or {}
        return cls(
            sru_url=source.get("sru_url", DEFAULT_SRU_URL),
            repo_url=source.get("repo_url", DEFAULT_REPO_URL),
            portal_url=source.get("portal_url", DEFAULT_PORTAL_URL),
            request_timeout=source.get("request_timeout", 30),
            max_retries=source.get("max_retries", 5),
            requests_per_second=source.get("requests_per_second", 2.0),
            include_history=bool(source.get("include_history", True)),
        )

    def __init__(
        self,
        *,
        sru_url: str = DEFAULT_SRU_URL,
        repo_url: str = DEFAULT_REPO_URL,
        portal_url: str = DEFAULT_PORTAL_URL,
        request_timeout: int = 30,
        max_retries: int = 5,
        requests_per_second: float = 2.0,
        include_history: bool = True,
    ) -> None:
        super().__init__(
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
        )
        self._sru_url = sru_url
        self._repo_url = repo_url.rstrip("/")
        self._portal_url = portal_url.rstrip("/")
        self._include_history = include_history
        # Cache of BWB_ID → latest expression path to avoid refetching manifests
        # when get_text and get_metadata are called back-to-back for the same ID.
        self._latest_cache: dict[str, str] = {}
        # Cache of BWB_ID → full multi-expression bundle, keyed per-ID so a
        # single fetch populates both ``get_text`` and ``get_metadata``.
        self._bundle_cache: dict[str, bytes] = {}
        self._bundle_lock = threading.Lock()

    # ─────────────────────────────────────────
    # SRU search API
    # ─────────────────────────────────────────

    def sru_search(
        self,
        query: str,
        *,
        start_record: int = 1,
        maximum_records: int = 100,
    ) -> bytes:
        """Run a SRU searchRetrieve query against the BWB collection.

        Args:
            query: CQL query string (e.g. ``dcterms.type=wet``).
            start_record: 1-indexed start position.
            maximum_records: page size (default 100, max 1000 in practice).

        Returns raw response bytes (SRU XML).

        **Quirky server behaviour:** the KOOP SRU server returns HTTP 406
        responses that still carry a valid ``<searchRetrieveResponse>`` body
        (the status code reflects an unrelated content-negotiation quirk).
        We treat any 2xx *or* 406 response with an XML body as a success.
        """
        encoded_query = quote(query, safe="=<>!.:/-+&")
        url = (
            f"{self._sru_url}"
            f"?operation=searchRetrieve"
            f"&version=2.0"
            f"&x-connection=BWB"
            f"&query={encoded_query}"
            f"&startRecord={start_record}"
            f"&maximumRecords={maximum_records}"
        )
        # We can't use _request() here because it raises on 406. Implement a
        # miniature retry/backoff loop locally.
        import time

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                self._wait_rate_limit()
                resp = self._session.get(url, timeout=self._timeout)
                if resp.status_code in (200, 406) and resp.content.startswith(b"<?xml"):
                    return resp.content
                if resp.status_code in (429, 502, 503, 504):
                    wait = 2**attempt
                    logger.warning(
                        "SRU %d on %s, retrying in %ds (attempt %d/%d)",
                        resp.status_code,
                        url,
                        wait,
                        attempt + 1,
                        self._max_retries,
                    )
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.content
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < self._max_retries - 1:
                    time.sleep(2**attempt)
        raise last_exc or RuntimeError(f"Failed SRU {url}")

    # ─────────────────────────────────────────
    # Repository (full XML)
    # ─────────────────────────────────────────

    def get_manifest(self, bwb_id: str) -> bytes:
        """Fetch the BWB manifest XML for a given law.

        The manifest root element is ``<work>`` with:
        - ``label`` = BWB ID
        - ``_latestItem`` = relative path to the latest expression's XML
        - ``<expression>`` children = all historical versions
        """
        return self._get(f"{self._repo_url}/{bwb_id}/")

    def get_latest_xml_path(self, bwb_id: str) -> str:
        """Resolve the relative path of the latest expression's XML.

        Caches the result per BWB ID so repeated get_text/get_metadata calls
        only hit the manifest once.
        """
        cached = self._latest_cache.get(bwb_id)
        if cached:
            return cached

        manifest_bytes = self.get_manifest(bwb_id)
        try:
            root = ET.fromstring(manifest_bytes)
        except ET.ParseError as exc:
            raise ValueError(f"Invalid manifest XML for {bwb_id}: {exc}") from exc

        latest_item = root.attrib.get("_latestItem")
        if not latest_item:
            raise ValueError(f"Manifest for {bwb_id} has no _latestItem attribute")
        self._latest_cache[bwb_id] = latest_item
        return latest_item

    def list_expressions(self, bwb_id: str) -> list[tuple[str, str]]:
        """List every expression in a law's manifest.

        Returns ``[(effective_date, xml_path), ...]`` in chronological order.
        ``xml_path`` is relative to ``{repo_url}/{bwb_id}/``.
        """
        manifest_bytes = self.get_manifest(bwb_id)
        try:
            root = ET.fromstring(manifest_bytes)
        except ET.ParseError as exc:
            raise ValueError(f"Invalid manifest XML for {bwb_id}: {exc}") from exc

        expressions: list[tuple[str, str]] = []
        for exp in root.findall("expression"):
            label = exp.get("label") or ""
            if not label:
                continue
            meta = exp.find("metadata")
            inw = meta.findtext("datum_inwerkingtreding", "") if meta is not None else ""
            effective_date = inw or label.split("_")[0]
            # The manifestation name is ``{bwb_id}_{label}.xml``
            xml_path = f"{label}/xml/{bwb_id}_{label}.xml"
            # Check if the xml manifestation is actually present — some old
            # expressions only have the "gedrukte tekst" (printed text)
            # variant without XML. Skip those.
            has_xml = False
            for manifestation in exp.findall("manifestation"):
                if manifestation.get("label") == "xml":
                    has_xml = True
                    break
            if has_xml:
                expressions.append((effective_date, xml_path))

        expressions.sort(key=lambda x: x[0])
        return expressions

    def get_text(self, norm_id: str) -> bytes:
        """Fetch the full history of a law as a bundled multi-expression envelope.

        Unless ``include_history`` is disabled, this returns a
        ``<bwb-multi-expression>`` XML document whose children are the
        ``<toestand>`` roots of every historical expression listed in the
        manifest, annotated with an ``effective-date`` attribute. The parser
        detects this envelope and emits multi-``Version`` blocks so the
        pipeline can produce one git commit per reform.

        When ``include_history`` is False (or when a law has only one
        expression) the returned bytes are the raw ``<toestand>`` XML of the
        latest expression, so downstream code still works unchanged.
        """
        with self._bundle_lock:
            cached = self._bundle_cache.get(norm_id)
        if cached is not None:
            return cached

        if not self._include_history:
            path = self.get_latest_xml_path(norm_id)
            data = self._get(f"{self._repo_url}/{norm_id}/{path}")
            with self._bundle_lock:
                self._bundle_cache[norm_id] = data
            return data

        try:
            expressions = self.list_expressions(norm_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Manifest for %s unreadable (%s), falling back", norm_id, exc)
            expressions = []

        if not expressions:
            # Fall back to latest-only
            path = self.get_latest_xml_path(norm_id)
            data = self._get(f"{self._repo_url}/{norm_id}/{path}")
            with self._bundle_lock:
                self._bundle_cache[norm_id] = data
            return data

        # Cap runaway chains (see MAX_EXPRESSIONS_PER_LAW). We keep the most
        # recent entries so the current state of the law is always present.
        if len(expressions) > MAX_EXPRESSIONS_PER_LAW:
            logger.info(
                "%s has %d expressions, truncating to most recent %d",
                norm_id,
                len(expressions),
                MAX_EXPRESSIONS_PER_LAW,
            )
            expressions = expressions[-MAX_EXPRESSIONS_PER_LAW:]

        pieces: list[bytes] = [
            b"<?xml version='1.0' encoding='UTF-8'?>\n<bwb-multi-expression bwb-id='",
            norm_id.encode("utf-8"),
            b"'>\n",
        ]
        for effective_date, xml_path in expressions:
            try:
                xml_bytes = self._get(f"{self._repo_url}/{norm_id}/{xml_path}")
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to download expression %s of %s: %s",
                    effective_date,
                    norm_id,
                    exc,
                )
                continue
            pieces.append(f"<expression effective-date='{effective_date}'>\n".encode("utf-8"))
            # Strip the XML prolog so nesting stays valid
            inner = xml_bytes
            if inner.startswith(b"<?xml"):
                idx = inner.find(b"?>")
                if idx >= 0:
                    inner = inner[idx + 2 :].lstrip()
            pieces.append(inner)
            pieces.append(b"\n</expression>\n")
        pieces.append(b"</bwb-multi-expression>\n")
        bundle = b"".join(pieces)

        with self._bundle_lock:
            self._bundle_cache[norm_id] = bundle
        return bundle

    def get_metadata(self, norm_id: str) -> bytes:
        """Return the same envelope as get_text — metadata is embedded."""
        return self.get_text(norm_id)

    # ─────────────────────────────────────────
    # Portal URL for citations
    # ─────────────────────────────────────────
