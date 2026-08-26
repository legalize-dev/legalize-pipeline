"""HTTP client for BOPA (Andorra) — Azure Functions API + blob storage.

The Butlletí Oficial del Principat d'Andorra is served from two endpoints:

  1. Azure Functions API at https://bopaazurefunctions.azurewebsites.net/api/
     Provides discovery (newsletter list, per-butlletí documents, taxonomies).

  2. Azure Blob storage at https://bopadocuments.blob.core.windows.net/
     Hosts the actual document HTML files with metadata in HTTP headers.

Quirks worth knowing about:

  * `metadata_storage_path` returned by the API sometimes includes a leading
    numeric prefix like ``1_CGL_2025_01_08_10_50_58.html`` — those are paginated
    UTF-8 fragments for the website frontend that start mid-sentence and are
    useless for ingestion. The canonical full document is at the same path
    without the prefix. The client always strips ``^\\d+_``.
  * Blob files come in either UTF-16-LE (with BOM) or UTF-8 (no BOM). The
    encoding is per-blob, not per-era. Always detect via BOM.
  * ``GetDocumentsByBOPA`` is hard-capped at 132 results regardless of
    ``totalCount``; pagination params are silently ignored. Target organismes
    (02 Consell General, 03 Govern) sit at the top of the org order so target
    docs are practically never truncated.
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

_DEFAULT_API_BASE = "https://bopaazurefunctions.azurewebsites.net/api"
_DEFAULT_BLOB_BASE = "https://bopadocuments.blob.core.windows.net/bopa-documents"
_DEFAULT_RATE_LIMIT = 4.0  # 250ms between requests — gentle on the public Azure Function

# Filenames sometimes arrive prefixed with a sequence number (e.g. "1_CGL_...html").
# Those are paginated fragments. We strip the prefix to get the canonical document.
_PREFIX_RE = re.compile(r"^(\d+_)+")


class BOPAClient(HttpClient):
    """Fetches BOPA documents from the Azure Functions API and blob storage.

    Two-tier interface:

    * High-level API helpers (``get_paginated_newsletter``, ``get_butlleti_documents``)
      used by the discovery layer.
    * Standard ``LegislativeClient`` interface (``get_text``, ``get_metadata``)
      used by the pipeline. ``norm_id`` follows the format
      ``"{anyButlleti}/{numButlleti}/{nomDocument}"`` so a single string carries
      all the coordinates needed to fetch text + metadata independently.
    """

    @classmethod
    def create(cls, country_config: CountryConfig) -> BOPAClient:
        source = country_config.source or {}
        return cls(
            api_base=source.get("api_base", _DEFAULT_API_BASE),
            blob_base=source.get("blob_base", _DEFAULT_BLOB_BASE),
            requests_per_second=source.get("requests_per_second", _DEFAULT_RATE_LIMIT),
            request_timeout=source.get("request_timeout", 30),
            max_retries=source.get("max_retries", 5),
        )

    def __init__(
        self,
        *,
        api_base: str = _DEFAULT_API_BASE,
        blob_base: str = _DEFAULT_BLOB_BASE,
        requests_per_second: float = _DEFAULT_RATE_LIMIT,
        request_timeout: int = 30,
        max_retries: int = 5,
    ) -> None:
        super().__init__(
            base_url="",  # we use absolute URLs everywhere
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
        )
        self._api_base = api_base.rstrip("/")
        self._blob_base = blob_base.rstrip("/")
        # In-memory cache: (year, num) -> list of document dicts.
        # Populated by discovery and reused by metadata parser to avoid
        # double-fetching the same butlletí for the same run.
        self._butlleti_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}

    # ── High-level API helpers ──

    def get_paginated_newsletter(self) -> list[dict[str, Any]]:
        """Fetch the full list of butlletins (3,464+ entries since 1989).

        Returns the ``bopaList`` field of the API response, which is a list
        of ``{numBOPA, dataPublicacio, isExtra, num}`` dicts sorted by
        publication date.
        """
        url = f"{self._api_base}/GetPaginatedNewsletter"
        logger.debug("Fetching BOPA newsletter index")
        raw = self._get(url)
        data = json.loads(raw)
        bopa_list = data.get("bopaList", [])
        logger.info("Fetched BOPA newsletter index: %d butlletins", len(bopa_list))
        return bopa_list

    def get_butlleti_documents(
        self,
        *,
        num: str,
        year: str,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetch all documents in a specific butlletí.

        Returns the ``paginatedDocuments[].document`` list (the wrapper score
        and highlights are stripped). Cached in-memory by ``(year, num)``.

        ``GetDocumentsByBOPA`` is hard-capped at 132 results — see the module
        docstring for details.
        """
        key = (str(year), str(num))
        if use_cache and key in self._butlleti_cache:
            return self._butlleti_cache[key]

        url = f"{self._api_base}/GetDocumentsByBOPA"
        params = {"numBOPA": str(num), "year": str(year)}
        logger.debug("Fetching butlletí %s/%s", year, num)
        resp = self._request("GET", url, params=params)
        data = json.loads(resp.content)

        total = data.get("totalCount", 0)
        wrappers = data.get("paginatedDocuments", []) or []
        docs = [w["document"] for w in wrappers if "document" in w]
        if total > len(docs):
            logger.warning(
                "Butlletí %s/%s: API returned %d of %d documents (132-cap reached)",
                year,
                num,
                len(docs),
                total,
            )
        self._butlleti_cache[key] = docs
        return docs

    def get_blob(self, doc_path_or_url: str) -> tuple[bytes, dict[str, str]]:
        """Fetch a document blob (HTML file) and return ``(bytes, headers)``.

        ``doc_path_or_url`` may be a full URL (as returned in
        ``metadata_storage_path``) or a relative path under the blob container.
        Any leading ``\\d+_`` prefix on the filename is stripped — those are
        paginated fragments, the canonical full document lives at the same
        path without the prefix.
        """
        url = self._normalize_blob_url(doc_path_or_url)
        logger.debug("Fetching blob: %s", url)
        resp = self._request("GET", url)
        return resp.content, dict(resp.headers)

    # ── LegislativeClient interface ──

    def get_text(self, norm_id: str, meta_data: bytes | None = None) -> bytes:
        """Fetch the HTML body of a BOPA document, bundled with metadata.

        ``norm_id`` follows the format ``"{anyButlleti}/{numButlleti}/{nomDocument}"``,
        e.g. ``"2025/4/CGL_2025_01_08_10_50_58"``. The blob URL is constructed
        from the year offset (1989 = 001) and the issue number, both zero-padded
        to three digits.

        Returns a JSON-encoded bundle so the parser can build a ``Version`` with
        the real publication date instead of a placeholder. The bundle has the
        shape::

            {
              "html": "<utf-8 string of the document HTML>",
              "publication_date": "2025-01-14",
              "article_date": "2024-12-19"
            }

        The optional ``meta_data`` parameter is the document metadata bytes
        produced by ``get_metadata``, passed by the engine to avoid a redundant
        API call. Recognised by ``generic_fetch_one`` via introspection.
        """
        from legalize.fetcher.ad.parser import _decode_html

        year, num, nom = self._split_norm_id(norm_id)
        url = self._build_blob_url(year, num, f"{nom}.html")
        raw_bytes, _headers = self.get_blob(url)
        # Decode the HTML to a text string we can put in JSON. The blob may be
        # UTF-16 (with BOM) or UTF-8 (no BOM); _decode_html handles both.
        html_str = _decode_html(raw_bytes)

        publication_date = ""
        article_date = ""
        if meta_data:
            try:
                doc_meta = json.loads(meta_data)
                publication_date = (doc_meta.get("dataPublicacioButlleti") or "")[:10]
                article_date = (doc_meta.get("dataArticle") or "")[:10]
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass

        bundle = {
            "html": html_str,
            "publication_date": publication_date,
            "article_date": article_date,
        }
        return json.dumps(bundle, ensure_ascii=False).encode("utf-8")

    def get_metadata(self, norm_id: str) -> bytes:
        """Fetch the API document metadata for a norm.

        Returns the document dict (from ``GetDocumentsByBOPA``) as JSON bytes.
        Reuses the per-butlletí in-memory cache when populated by discovery.
        """
        year, num, nom = self._split_norm_id(norm_id)
        docs = self.get_butlleti_documents(num=num, year=year)
        for doc in docs:
            if doc.get("nomDocument") == nom:
                return json.dumps(doc, ensure_ascii=False).encode("utf-8")
        raise ValueError(
            f"Document {nom!r} not found in butlletí {year}/{num}. "
            "The 132-cap may have dropped it, or it was unpublished."
        )

    # ── URL helpers ──

    def _normalize_blob_url(self, doc_path_or_url: str) -> str:
        """Resolve a relative path to a full blob URL and strip page prefixes.

        Examples
        --------
        >>> c = BOPAClient()
        >>> c._normalize_blob_url("https://bopadocuments.blob.core.windows.net/bopa-documents/037004/html/1_CGL_x.html")
        'https://bopadocuments.blob.core.windows.net/bopa-documents/037004/html/CGL_x.html'
        >>> c._normalize_blob_url("037004/html/3_GR_x.html")
        'https://bopadocuments.blob.core.windows.net/bopa-documents/037004/html/GR_x.html'
        """
        if doc_path_or_url.startswith("http://") or doc_path_or_url.startswith("https://"):
            url = doc_path_or_url
        else:
            url = f"{self._blob_base}/{doc_path_or_url.lstrip('/')}"
        # Strip leading "N_" page prefix from the filename only
        head, _, filename = url.rpartition("/")
        clean = _PREFIX_RE.sub("", filename)
        return f"{head}/{clean}"

    def _build_blob_url(self, year: str, num: str, filename: str) -> str:
        """Construct a blob URL from butlletí coordinates and filename.

        Path format: ``bopa-documents/{year_offset:03d}{num:03d}/html/{filename}``
        where ``year_offset = year - 1989 + 1`` (1989 → 001, 2025 → 037).
        """
        year_int = int(year)
        num_int = int(num)
        offset = year_int - 1988  # 1989 → 1, 2026 → 38
        bucket = f"{offset:03d}{num_int:03d}"
        return f"{self._blob_base}/{bucket}/html/{filename}"

    @staticmethod
    def _split_norm_id(norm_id: str) -> tuple[str, str, str]:
        """Split ``"{year}/{num}/{nomDocument}"`` into its three parts."""
        parts = norm_id.split("/", 2)
        if len(parts) != 3:
            raise ValueError(f"Invalid AD norm_id {norm_id!r}: expected 'year/num/nomDocument'")
        year, num, nom = parts
        return year, num, nom
