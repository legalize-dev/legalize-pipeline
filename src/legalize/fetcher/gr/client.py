"""HTTP client for the official Greek Government Gazette (ΦΕΚ) backend.

The National Printing House (Εθνικό Τυπογραφείο) operates the public
search portal at ``https://search.et.gr/`` whose React frontend talks
to two backends:

  1. **``https://searchetv99.azurewebsites.net/api``** — Azure Functions
     REST API that powers discovery, metadata, taxonomies, timelines,
     tags, and named-entity extraction. **Public, no authentication,
     CORS-open.** Verified 2026-04-08 by reverse-engineering the React
     bundle and comparing browser-captured cURLs.

  2. **``https://ia37rg02wpsa01.blob.core.windows.net/fek/``** — Azure
     Blob storage that holds the canonical born-digital ΦΕΚ PDFs. The
     URL pattern is documented in ``getFekLink`` inside the React bundle::

         {storage}/fek/{IIpadded2}/{YYYY}/{YYYY}{IIpadded2}{NNNNNpadded5}.pdf

     where ``II`` is the issue group ID (1=Α', 2=Β', ...) and ``NNNNN``
     is the document number within the issue.

     The blobs serve ``Access-Control-Allow-Origin: *`` and a
     ``Content-MD5`` header so we can verify byte-identical fidelity
     against the original publication. Verified 2026-04-08: the
     official PDF for ΦΕΚ Α' 167/2013 (Income Tax Code) MD5-matches
     the same file we previously had via the IA mirror — confirming
     that the IA upload was a faithful byte-for-byte copy of these
     same official blobs.

This client gives us:

* **Official source attribution** — direct from the Εθνικό Τυπογραφείο,
  not a third-party mirror.
* **Coverage from 2000 to today** — the simpleSearch API returns items
  for every published year (verified through 2026).
* **Rich official metadata** — topics, subjects, named entities,
  protocol numbers, and **modification timeline** per document.
* **Phase 2 reforms via the timeline endpoint** — the publisher itself
  exposes the modification graph between documents (which laws modify
  which), so we don't need to parse Greek legalese with regex.

The legacy Internet Archive ``greekgovernmentgazette`` collection is
no longer used as a source.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

_DEFAULT_API_BASE = "https://searchetv99.azurewebsites.net/api"
_DEFAULT_BLOB_BASE = "https://ia37rg02wpsa01.blob.core.windows.net/fek"
_DEFAULT_RATE_LIMIT = 4.0  # 250ms between requests — gentle on the public API
_DEFAULT_TIMEOUT = 60

# CORS-required headers — without ``Origin`` the API still responds, but
# matching the browser exactly avoids any future server-side tightening.
_CORS_HEADERS = {
    "Origin": "https://search.et.gr",
    "Referer": "https://search.et.gr/",
}

# Issue group IDs (`IssueGroupID` in API responses) → letter shorthand.
# Source: ``issueTypeToNameMap`` in the React bundle.
ISSUE_GROUPS: dict[int, str] = {
    1: "Α",  # Νόμοι, Π.Δ., ΠΝΠ — our scope
    2: "Β",  # Υπουργικές Αποφάσεις
    3: "Γ",  # Διορισμοί
    4: "Δ",  # Πολεοδομικά
    5: "Ν.Π.Δ.Δ.",
    6: "Α.Π.Σ.",
    7: "ΠΑΡΑΡΤΗΜΑ",
    8: "Δ.Ε.Β.Ι.",
    9: "Α.ΕΙ.Δ.",
    10: "Α.Σ.Ε.Π.",
    11: "ΑΕ-EΠΕ",  # also "ΠΡΑ.Δ.Ι.Τ." since 2015
    12: "Δ.Δ.Σ.",
    13: "Ο.Π.Κ.",
    14: "Υ.Ο.Δ.Δ.",
    15: "Α.Α.Π.",
}

# Latin transliteration of the Greek issue group letters for filesystem-safe IDs.
ISSUE_GROUP_TO_LATIN: dict[int, str] = {
    1: "A",
    2: "B",
    3: "G",
    4: "D",
}

# norm_id format used by this country: ``FEK-A-{NUMBER}-{YEAR}``
# Stable, citable, filesystem-safe. Example: ``FEK-A-167-2013``.
_NORM_ID_RE = re.compile(r"^FEK-([A-Z])-(\d+)-(\d{4})$")


def make_norm_id(year: int, issue_group: int, doc_number: int) -> str:
    """Build the canonical norm_id for a Greek FEK document."""
    letter = ISSUE_GROUP_TO_LATIN.get(issue_group)
    if letter is None:
        raise ValueError(f"Unsupported issue group {issue_group}")
    return f"FEK-{letter}-{doc_number}-{year}"


def parse_norm_id(norm_id: str) -> tuple[int, int, int]:
    """Return ``(year, issue_group_id, doc_number)`` for a norm_id.

    Raises ``ValueError`` for malformed inputs.
    """
    m = _NORM_ID_RE.match(norm_id)
    if not m:
        raise ValueError(f"Invalid Greek norm_id format: {norm_id!r}")
    letter, doc_str, year_str = m.group(1), m.group(2), m.group(3)
    issue_group = next(
        (gid for gid, ltr in ISSUE_GROUP_TO_LATIN.items() if ltr == letter),
        None,
    )
    if issue_group is None:
        raise ValueError(f"Unknown issue group letter {letter!r} in {norm_id!r}")
    return int(year_str), issue_group, int(doc_str)


class GreekClient(HttpClient):
    """Fetches ΦΕΚ documents from the official Εθνικό Τυπογραφείο backend.

    Two-tier interface:

    * **Country-specific helpers** for searchetv99 endpoints
      (``simple_search``, ``get_document_metadata_by_id``,
      ``get_timeline``, ``get_pdf_bytes``).
    * **Standard ``LegislativeClient`` interface** (``get_text``,
      ``get_metadata``) used by the generic pipeline. norm_id format is
      ``FEK-A-{N}-{Y}``.

    The client maintains an in-process LRU cache so repeated calls
    against the same norm during one bootstrap pass don't redownload.
    """

    @classmethod
    def create(cls, country_config: CountryConfig) -> GreekClient:
        source = country_config.source or {}
        return cls(
            api_base=source.get("api_base", _DEFAULT_API_BASE),
            blob_base=source.get("blob_base", _DEFAULT_BLOB_BASE),
            requests_per_second=source.get("requests_per_second", _DEFAULT_RATE_LIMIT),
            request_timeout=source.get("request_timeout", _DEFAULT_TIMEOUT),
            max_retries=source.get("max_retries", 5),
        )

    def __init__(
        self,
        *,
        api_base: str = _DEFAULT_API_BASE,
        blob_base: str = _DEFAULT_BLOB_BASE,
        requests_per_second: float = _DEFAULT_RATE_LIMIT,
        request_timeout: int = _DEFAULT_TIMEOUT,
        max_retries: int = 5,
    ) -> None:
        super().__init__(
            base_url="",  # absolute URLs everywhere
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
            extra_headers=_CORS_HEADERS,
        )
        self._api_base = api_base.rstrip("/")
        self._blob_base = blob_base.rstrip("/")
        # Single-slot caches keyed on norm_id so the standard pipeline's
        # back-to-back ``get_metadata`` and ``get_text`` calls only hit
        # the wire once each per norm.
        self._last_meta_norm_id: str | None = None
        self._last_meta_bundle: bytes | None = None
        self._last_pdf_norm_id: str | None = None
        self._last_pdf_bytes: bytes | None = None

    # ── Internal helpers ──

    @staticmethod
    def _parse_data(resp_text: str) -> Any:
        """Decode the doubly-wrapped ``data`` field of a searchetv99 response.

        The API returns ``{"status":"ok","message":"...","data":"<json string>"}``
        where ``data`` is itself a JSON-encoded string. We parse both layers.
        """
        wrapper = json.loads(resp_text)
        if wrapper.get("status") != "ok":
            raise ValueError(
                f"searchetv99 returned status={wrapper.get('status')!r}: {wrapper.get('message')!r}"
            )
        data = wrapper.get("data", "")
        if isinstance(data, str):
            if not data or data == "[]":
                return []
            return json.loads(data)
        return data

    def _api_get(self, path: str) -> Any:
        url = f"{self._api_base}/{path.lstrip('/')}"
        body = self._get(url)
        return self._parse_data(body.decode("utf-8"))

    def _api_post_json(self, path: str, body: dict[str, Any]) -> Any:
        url = f"{self._api_base}/{path.lstrip('/')}"
        resp = self._request(
            "POST",
            url,
            json=body,
            headers={"Content-Type": "application/json"},
        )
        return self._parse_data(resp.text)

    # ── High-level helpers (the country-specific layer) ──

    def simple_search(
        self,
        *,
        year: int | None = None,
        issue_group: int | None = None,
        document_number: int | None = None,
        search_text: str = "",
    ) -> list[dict[str, Any]]:
        """Run the official ``/api/simplesearch`` query.

        Returns a list of search hits with the ``search_*`` fields:
        ``search_ID``, ``search_DocumentNumber``, ``search_IssueGroupID``,
        ``search_IssueDate``, ``search_PublicationDate``, ``search_Pages``,
        ``search_PrimaryLabel`` (e.g. ``"Α 167/2013"``), ``search_Score``.

        At least one filter must be provided — an empty body returns
        no results (silently).
        """
        body: dict[str, Any] = {
            "selectYear": [str(year)] if year is not None else [],
            "selectIssue": [str(issue_group)] if issue_group is not None else [],
            "documentNumber": str(document_number) if document_number is not None else "",
            "searchText": search_text,
            "datePublished": "",
            "dateReleased": "",
        }
        return self._api_post_json("/simplesearch", body)

    def get_document_metadata_by_id(self, search_id: int | str) -> list[dict[str, Any]]:
        """Fetch the full official metadata for one document.

        The response is an *array of fragments* (one per topic/subject/
        protocol-number/etc.). Use ``flatten_document_metadata`` to
        coalesce them into a single dict.
        """
        return self._api_get(f"documententitybyid/{search_id}")

    def get_timeline(self, search_id: int | str) -> list[dict[str, Any]]:
        """Fetch the official modification graph for one document.

        Each edge has ``timeline_OtherDocumentID``, ``timeline_PrimaryLabel``,
        ``timeline_RelationshipTypeID``, ``timeline_GreekLabel``,
        ``timeline_EnglishLabel``, ``timeline_Direction``.

        Relationship types (from the React bundle):
            0 = modification
            1 = expansion
            2 = reference
            3 = invalidation
            4 = identity
            5 = replacement
            6 = reinstatement

        Direction: ``-1`` = incoming (the OTHER document modifies *us*),
                    ``1`` = outgoing (we modify the OTHER document).
        """
        return self._api_get(f"timeline/{search_id}/0")

    def get_tags(self, search_id: int | str) -> list[dict[str, Any]]:
        """Subject tags from the controlled vocabulary."""
        return self._api_get(f"tagsbydocumententity/{search_id}")

    def get_named_entities(self, search_id: int | str) -> list[dict[str, Any]]:
        """Named-entity recognition output (people, organisations, places)."""
        return self._api_get(f"namedentity/{search_id}")

    # ── PDF download from Azure Blob ──

    @staticmethod
    def build_blob_path(year: int, issue_group: int, doc_number: int) -> str:
        """Build the canonical blob path for a FEK document.

        Mirrors ``getFekLink`` from the React bundle::

            /{II}/{YYYY}/{YYYY}{II}{NNNNN}.pdf
        """
        ig = f"{issue_group:02d}"
        nn = f"{doc_number:05d}"
        filename = f"{year}{ig}{nn}"
        return f"{ig}/{year}/{filename}.pdf"

    def get_pdf_bytes(self, year: int, issue_group: int, doc_number: int) -> bytes:
        """Download a FEK PDF directly from the Azure Blob storage."""
        path = self.build_blob_path(year, issue_group, doc_number)
        url = f"{self._blob_base}/{path}"
        logger.debug("FEK blob fetch: %s", url)
        return self._get(url)

    # ── Standard LegislativeClient interface ──

    def get_text(self, norm_id: str, meta_data: bytes | None = None) -> bytes:
        """Fetch the PDF bytes of a ΦΕΚ document.

        ``norm_id`` follows the canonical ``FEK-A-{N}-{Y}`` format.
        """
        if self._last_pdf_norm_id == norm_id and self._last_pdf_bytes is not None:
            return self._last_pdf_bytes

        year, issue_group, doc_number = parse_norm_id(norm_id)
        data = self.get_pdf_bytes(year, issue_group, doc_number)
        self._last_pdf_norm_id = norm_id
        self._last_pdf_bytes = data
        return data

    def get_metadata(self, norm_id: str) -> bytes:
        """Fetch the full official metadata bundle for a norm.

        Combines:

        * ``simple_search`` (to find the search_ID for the norm)
        * ``get_document_metadata_by_id`` (topics, subjects, protocol)
        * ``get_timeline`` (modification graph — Phase 2 reforms)
        * ``get_tags`` (controlled-vocabulary subject tags)
        * ``get_named_entities`` (people, organisations, places)

        Returns a JSON-encoded bundle so the metadata parser can pull
        whatever it needs in a single byte payload.
        """
        if self._last_meta_norm_id == norm_id and self._last_meta_bundle is not None:
            return self._last_meta_bundle

        year, issue_group, doc_number = parse_norm_id(norm_id)
        hits = self.simple_search(year=year, issue_group=issue_group, document_number=doc_number)
        if not hits:
            logger.warning(
                "No simpleSearch result for %s (year=%d, issue=%d, doc=%d)",
                norm_id,
                year,
                issue_group,
                doc_number,
            )
            empty: dict[str, Any] = {
                "norm_id": norm_id,
                "year": year,
                "issue_group": issue_group,
                "doc_number": doc_number,
                "search": None,
                "metadata": [],
                "timeline": [],
                "tags": [],
                "named_entities": [],
            }
            data = json.dumps(empty, ensure_ascii=False).encode("utf-8")
        else:
            hit = hits[0]
            search_id = hit["search_ID"]
            try:
                metadata = self.get_document_metadata_by_id(search_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("documententitybyid failed for %s: %s", norm_id, exc)
                metadata = []
            try:
                timeline = self.get_timeline(search_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("timeline failed for %s: %s", norm_id, exc)
                timeline = []
            try:
                tags = self.get_tags(search_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("tags failed for %s: %s", norm_id, exc)
                tags = []
            try:
                ner = self.get_named_entities(search_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("namedentity failed for %s: %s", norm_id, exc)
                ner = []
            bundle = {
                "norm_id": norm_id,
                "year": year,
                "issue_group": issue_group,
                "doc_number": doc_number,
                "search": hit,
                "metadata": metadata,
                "timeline": timeline,
                "tags": tags,
                "named_entities": ner,
            }
            data = json.dumps(bundle, ensure_ascii=False).encode("utf-8")

        self._last_meta_norm_id = norm_id
        self._last_meta_bundle = data
        return data
