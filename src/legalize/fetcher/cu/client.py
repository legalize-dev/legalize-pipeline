"""HTTP client for the Gaceta Oficial de la República de Cuba.

The official source is the Gaceta's own website (Drupal, behind a browser
User-Agent) plus the MINJUS portal for a handful of book editions:

  1. **``https://www.gacetaoficial.gob.cu``** — the official gazette.
     PDFs live under ``/sites/default/files/*.pdf`` and answer 200 to the
     plain ``legalize-bot`` User-Agent (TLS valid, verified 2026-04-xx).
     The catalog landing page
     ``/es/algunas-legislaciones-cubanas`` returns **403 to the default
     requests UA** but 200 to a browser UA, so catalog fetches always send
     the browser UA. The catalog contains **no ``.pdf`` hrefs** — the
     law rows are plain table cells (e.g. ``Decreto-Ley 86/2024 "De la
     Caja de Resarcimientos".``), paginated ``?page=0..2``.

  2. **``https://www.minjus.gob.cu``** — MINJUS hosts two consolidated
     book editions (Ley-109 Código de Seguridad Vial, Decreto-Ley-304
     Contratación Económica) whose URLs are captured in the manifest.

Because the catalog exposes names but not PDF URLs, **the manifest is the
URL map**: ``manifest.json`` (shipped in the ``legalize-cu`` repo and the
source of truth upstream) maps each identifier to its PDF URL plus the
publication metadata. The client loads the manifest from
``source.manifest_url`` (raw GitHub) or ``source.manifest_path`` (local
file — offline bootstrap) and exposes the standard
``LegislativeClient`` interface over it:

* ``get_metadata(norm_id)`` — the manifest entry for the norm as JSON bytes.
* ``get_text(norm_id)`` — a JSON bundle carrying the PDF bytes (base64)
  plus the slicing knobs (``goc``, ``start_index``, ``start_regex``,
  ``end_regex``) and publication date the parser needs to slice a combined
  issue down to the target law and date its ``Version`` correctly.
* ``get_manifest`` / ``get_catalog`` — discovery helpers.

The manifest lives at the repo root of ``legalize-dev/legalize-cu``
(``manifest.json``). Identifiers are the manifest keys, e.g.
``Ley-143-2021-Proceso-Penal``, which match the ``cu/*.md`` filenames.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://www.gacetaoficial.gob.cu"
_DEFAULT_CATALOG_URL = "https://www.gacetaoficial.gob.cu/es/algunas-legislaciones-cubanas"
# The manifest is the URL map. Default points at the raw GitHub file in the
# legalize-cu repo so CI and daily runs always see the latest mapping.
_DEFAULT_MANIFEST_URL = (
    "https://raw.githubusercontent.com/legalize-dev/legalize-cu/main/manifest.json"
)
# The catalog landing page 403s the default legalize-bot UA but 200s a
# browser UA (verified). PDFs themselves answer 200 to any UA.
_DEFAULT_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_DEFAULT_RATE_LIMIT = 1.0  # gentle — Gaceta is a small public site
_DEFAULT_TIMEOUT = 60


class GacetaClient(HttpClient):
    """Fetches Gaceta Oficial PDFs and metadata via the manifest URL map.

    Two-tier interface:

    * **Discovery helpers** — ``get_manifest`` (the identifier → URL/meta
      map), ``get_catalog`` (the crawlable law-name rows for daily diffs).
    * **Standard ``LegislativeClient`` interface** — ``get_text`` and
      ``get_metadata`` keyed by the manifest identifier.

    The manifest is loaded once and cached; a single-slot PDF cache avoids
    re-downloading the same norm during one bootstrap pass.
    """

    @classmethod
    def create(cls, country_config: CountryConfig) -> GacetaClient:
        source = country_config.source or {}
        return cls(
            base_url=source.get("base_url", _DEFAULT_BASE_URL),
            catalog_url=source.get("catalog_url", _DEFAULT_CATALOG_URL),
            manifest_url=source.get("manifest_url", _DEFAULT_MANIFEST_URL),
            manifest_path=source.get("manifest_path", ""),
            browser_ua=source.get("browser_ua", _DEFAULT_BROWSER_UA),
            requests_per_second=source.get("requests_per_second", _DEFAULT_RATE_LIMIT),
            request_timeout=source.get("request_timeout", _DEFAULT_TIMEOUT),
            max_retries=source.get("max_retries", 5),
        )

    def __init__(
        self,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        catalog_url: str = _DEFAULT_CATALOG_URL,
        manifest_url: str = _DEFAULT_MANIFEST_URL,
        manifest_path: str = "",
        browser_ua: str = _DEFAULT_BROWSER_UA,
        requests_per_second: float = _DEFAULT_RATE_LIMIT,
        request_timeout: int = _DEFAULT_TIMEOUT,
        max_retries: int = 5,
        manifest: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
        )
        self._catalog_url = catalog_url
        self._manifest_url = manifest_url
        self._manifest_path = manifest_path
        self._browser_ua = browser_ua
        self._manifest: dict[str, Any] | None = manifest
        self._last_text_norm_id: str | None = None
        self._last_text_bundle: bytes | None = None

    # ── Manifest ──

    def _load_manifest(self) -> dict[str, Any]:
        """Load the manifest from the in-memory copy, local path, or URL."""
        if self._manifest is not None:
            return self._manifest

        if self._manifest_path:
            path = Path(self._manifest_path)
            if not path.exists():
                logger.warning("Manifest path %s does not exist", path)
                return {}
            try:
                with open(path, encoding="utf-8") as f:
                    self._manifest = json.load(f)
                logger.info("Loaded manifest from %s (%d laws)", path, len(self._manifest))
                return self._manifest
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to load manifest %s: %s", path, exc)
                return {}

        if self._manifest_url:
            try:
                raw = self._get(self._manifest_url)
                self._manifest = json.loads(raw.decode("utf-8"))
                logger.info(
                    "Loaded manifest from %s (%d laws)", self._manifest_url, len(self._manifest)
                )
                return self._manifest
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to fetch manifest %s: %s", self._manifest_url, exc)
                return {}

        logger.warning("No manifest source configured for GacetaClient")
        return {}

    def get_manifest(self) -> dict[str, Any]:
        """Return the full identifier → metadata URL map for Cuba."""
        return dict(self._load_manifest())

    def get_manifest_keys(self) -> list[str]:
        """Return the manifest identifiers in stable sorted order."""
        return sorted(self._load_manifest().keys())

    # ── Catalog (discovery) ──

    def get_catalog(self) -> bytes:
        """Fetch the crawlable law-name catalog page with a browser UA."""
        return self._get(self._catalog_url, headers={"User-Agent": self._browser_ua})

    # ── Standard LegislativeClient interface ──

    def get_metadata(self, norm_id: str) -> bytes:
        """Return the manifest entry for a norm as JSON bytes."""
        manifest = self._load_manifest()
        if norm_id not in manifest:
            raise ValueError(
                f"Cuba identifier {norm_id!r} not found in manifest "
                f"(add it to manifest.json upstream, or the URL map is stale)"
            )
        return json.dumps(manifest[norm_id], ensure_ascii=False).encode("utf-8")

    def get_text(self, norm_id: str, meta_data: bytes | None = None) -> bytes:
        """Fetch a law's PDF and bundle it with the slicing knobs it needs.

        Returns a JSON bundle so ``GacetaTextParser`` can slice combined
        issues and date its ``Version`` without a second API call::

            {
              "pdf": "<base64 pdf bytes>",
              "goc": "GOC-2024-440-O78",       # present for combined issues
              "start_index": 0,
              "start_regex": "^LEY NÚMERO 109",  # present for book editions
              "end_regex": "^CONSEJO DE MINISTROS$",
              "publication_date": "2024-08-19",
              "title": "Decreto-Ley 88/2024, ..."
            }

        ``meta_data`` is the manifest entry produced by ``get_metadata``,
        passed by the engine to avoid re-reading the manifest.
        """
        if self._last_text_norm_id == norm_id and self._last_text_bundle is not None:
            return self._last_text_bundle

        if meta_data:
            try:
                entry = json.loads(meta_data)
            except json.JSONDecodeError:
                entry = {}
        else:
            manifest = self._load_manifest()
            entry = manifest.get(norm_id)
            if entry is None:
                raise ValueError(
                    f"Cuba identifier {norm_id!r} not found in manifest — no PDF URL available"
                )

        url = entry.get("url")
        if not url:
            raise ValueError(f"Manifest entry for {norm_id!r} has no 'url' to fetch")
        pdf_bytes = self._get(url)

        bundle = {
            "pdf": base64.b64encode(pdf_bytes).decode("ascii"),
            "goc": entry.get("goc", ""),
            "start_index": entry.get("start_index", 0),
            "start_regex": entry.get("start_regex", ""),
            "end_regex": entry.get("end_regex", ""),
            "publication_date": entry.get("publication_date", ""),
            "title": entry.get("title", ""),
            "journal_issue": entry.get("journal_issue", ""),
        }
        data = json.dumps(bundle, ensure_ascii=False).encode("utf-8")
        self._last_text_norm_id = norm_id
        self._last_text_bundle = data
        return data
