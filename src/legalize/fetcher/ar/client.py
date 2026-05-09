"""InfoLEG HTTP client for Argentine legislation.

Two responsibilities:

1. **Catalog**: download the monthly ZIP from datos.jus.gob.ar (one CSV per
   ZIP, ~47 MB → 241 MB) and the modifications-graph ZIP, save to ``data_dir``
   and load them into an :class:`InfoLEGCatalog`.

2. **Per-norm text**: GET ``texact.htm`` (consolidated) and ``norma.htm``
   (original) from the legacy host ``servicios.infoleg.gob.ar``. The host
   is Apache 2.2.22 (no robots.txt, no rate-limit headers, mixed
   ISO-8859-1/windows-1252 declarations). We always decode as **cp1252**
   regardless of the declared charset — see RESEARCH-AR.md §5.

There is no per-norm metadata API: metadata comes from the catalog row
(``InfoLEGRow`` from :mod:`legalize.fetcher.ar.catalog`). The metadata
parser receives a serialized row, not an HTTP response.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from legalize.fetcher.ar.catalog import (
    InfoLEGCatalog,
    InfoLEGRow,
    load_catalog,
    url_for,
)
from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

DEFAULT_CATALOG_URL = (
    "https://datos.jus.gob.ar/dataset/d9a963ea-8b1d-4ca3-9dd9-07a4773e8c23"
    "/resource/bf0ec116-ad4e-4572-a476-e57167a84403"
    "/download/base-infoleg-normativa-nacional.zip"
)
DEFAULT_MODIFICATIONS_URL = (
    "https://datos.jus.gob.ar/dataset/d9a963ea-8b1d-4ca3-9dd9-07a4773e8c23"
    "/resource/0c4fdafe-f4e8-4ac2-bc2e-acf50c27066d"
    "/download/base-complementaria-infoleg-normas-modificadas.zip"
)
DEFAULT_BASE_URL = "http://servicios.infoleg.gob.ar/infolegInternet"

# Module-level catalog cache — loaded once, shared across all client instances
# (threads). Avoids re-reading the 241 MB CSV per worker thread.
_CATALOG_CACHE: Optional[InfoLEGCatalog] = None
_CATALOG_CACHE_LOADED = False


class InfoLEGClient(HttpClient):
    """HTTP client for Argentine legislation via InfoLEG.

    The client wraps two distinct sources:
    - ``servicios.infoleg.gob.ar`` (per-norm HTML, charset cp1252)
    - ``datos.jus.gob.ar`` (monthly catalog ZIPs)
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        catalog_url: str = DEFAULT_CATALOG_URL,
        modifications_url: str = DEFAULT_MODIFICATIONS_URL,
        data_dir: str = "",
        request_timeout: int = 30,
        max_retries: int = 5,
        requests_per_second: float = 1.0,
    ) -> None:
        super().__init__(
            base_url=base_url,
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
        )
        self._catalog_url = catalog_url
        self._modifications_url = modifications_url
        self._data_dir = Path(data_dir) if data_dir else Path()
        self._catalog: Optional[InfoLEGCatalog] = None

    @classmethod
    def create(cls, country_config: CountryConfig) -> InfoLEGClient:
        source = country_config.source or {}
        return cls(
            base_url=source.get("base_url", DEFAULT_BASE_URL),
            catalog_url=source.get("catalog_url", DEFAULT_CATALOG_URL),
            modifications_url=source.get("modifications_url", DEFAULT_MODIFICATIONS_URL),
            data_dir=country_config.data_dir,
            request_timeout=source.get("request_timeout", 30),
            max_retries=source.get("max_retries", 5),
            requests_per_second=source.get("requests_per_second", 1.0),
        )

    # ── Catalog management ──

    def ensure_catalog(self, *, refresh: bool = False) -> InfoLEGCatalog:
        """Download (if needed) and load the InfoLEG catalog.

        Uses a module-level cache so all worker threads share one copy
        (~250 MB resident instead of N × 250 MB).
        """
        global _CATALOG_CACHE, _CATALOG_CACHE_LOADED  # noqa: PLW0603
        if not refresh and _CATALOG_CACHE_LOADED and _CATALOG_CACHE is not None:
            self._catalog = _CATALOG_CACHE
            return _CATALOG_CACHE
        if self._catalog is not None and not refresh:
            return self._catalog

        catalog_dir = self._data_dir / "catalog"
        catalog_dir.mkdir(parents=True, exist_ok=True)

        catalog_zip = catalog_dir / "base-infoleg-normativa-nacional.zip"
        mods_zip = catalog_dir / "base-complementaria-infoleg-normas-modificadas.zip"

        if refresh or not catalog_zip.exists():
            logger.info("Downloading InfoLEG catalog ZIP from %s", self._catalog_url)
            data = self._get(self._catalog_url)
            catalog_zip.write_bytes(data)
            logger.info("Saved catalog ZIP (%d bytes)", len(data))

        if refresh or not mods_zip.exists():
            logger.info("Downloading InfoLEG modifications ZIP from %s", self._modifications_url)
            data = self._get(self._modifications_url)
            mods_zip.write_bytes(data)
            logger.info("Saved modifications ZIP (%d bytes)", len(data))

        self._catalog = load_catalog(catalog_zip, mods_zip)
        _CATALOG_CACHE = self._catalog
        _CATALOG_CACHE_LOADED = True
        return self._catalog

    @property
    def catalog(self) -> InfoLEGCatalog:
        """Return the loaded catalog, loading it if necessary."""
        return self.ensure_catalog()

    # ── Per-norm fetch ──

    def get_text(self, norm_id: str) -> bytes:
        """Fetch the consolidated text for a norm.

        Tries ``texact.htm`` first; falls back to ``norma.htm`` if the
        norm has no consolidated version (Tier 2). Returns raw bytes
        with the original encoding intact — the parser is responsible
        for decoding via cp1252.
        """
        row = self.catalog.get(norm_id) or self.catalog.get_by_slug(norm_id)
        if row is None:
            # Catalog miss — try texact directly anyway
            return self._get(url_for(norm_id, "texact"))

        if row.has_consolidated_text:
            return self._get(url_for(norm_id, "texact"))
        if row.has_original_text:
            return self._get(url_for(norm_id, "norma"))

        raise ValueError(
            f"Norm {norm_id} has neither texto_actualizado nor texto_original in InfoLEG"
        )

    def get_modificatoria_text(self, norm_id: str) -> bytes:
        """Fetch the original text of a modificatoria for reform extraction.

        Always uses ``norma.htm`` because we want what was actually published
        on the B.O. date — the consolidated text could itself have been
        modified later, which would corrupt the diff calculation.
        """
        return self._get(url_for(norm_id, "norma"))

    def get_metadata(self, norm_id: str) -> bytes:
        """Return the catalog row as JSON-encoded bytes.

        Argentina has no per-norm metadata endpoint — metadata lives in the
        catalog CSV. We serialize the matching row so the
        :class:`InfoLEGMetadataParser` can consume it.
        """
        row = self.catalog.get(norm_id) or self.catalog.get_by_slug(norm_id)
        if row is None:
            raise ValueError(f"Norm {norm_id} not found in InfoLEG catalog")
        payload = {
            "id_norma": row.id_norma,
            "tipo_norma": row.tipo_norma,
            "numero_norma": row.numero_norma,
            "clase_norma": row.clase_norma,
            "organismo_origen": row.organismo_origen,
            "fecha_sancion": row.fecha_sancion.isoformat() if row.fecha_sancion else "",
            "numero_boletin": row.numero_boletin,
            "fecha_boletin": row.fecha_boletin.isoformat() if row.fecha_boletin else "",
            "pagina_boletin": row.pagina_boletin,
            "titulo_resumido": row.titulo_resumido,
            "titulo_sumario": row.titulo_sumario,
            "texto_resumido": row.texto_resumido,
            "observaciones": row.observaciones,
            "texto_original": row.texto_original,
            "texto_actualizado": row.texto_actualizado,
            "modificada_por": row.modificada_por,
            "modifica_a": row.modifica_a,
        }
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    # ── Version reconstruction hook (called by pipeline._extract_reforms_generic) ──

    def reconstruct_reforms(self, norm_id: str, initial_blocks: list) -> tuple[list, list]:
        """Reconstruct multi-version blocks from the modifications graph.

        Called by the generic pipeline during ``fetch``. Walks the catalog's
        modification edges, downloads each modificatoria's ``norma.htm``,
        extracts substitutions/repeals/insertions, and adds new
        :class:`Version` objects to the affected blocks. Returns
        ``(blocks, reforms)`` compatible with the standard
        ``commit_one`` / ``commit_all_fast`` flow.
        """
        from legalize.fetcher.ar.reforms import ModificationKind, extract_modifications
        from legalize.models import Block, Paragraph, Reform, Version

        row = self.catalog.get(norm_id) or self.catalog.get_by_slug(norm_id)
        if row is None:
            return initial_blocks, []

        edges = self.catalog.reforms_for(norm_id)
        if not edges:
            return initial_blocks, []

        relevant_types = frozenset({"Ley", "Decreto", "Decreto/Ley"})
        blocks = list(initial_blocks)
        reforms: list[Reform] = []
        seen_dates: set = set()

        for edge in edges:
            if edge.tipo_norma not in relevant_types:
                continue
            if edge.fecha_boletin is None:
                continue

            try:
                modif_html = self.get_modificatoria_text(edge.id_modificatoria)
            except Exception:
                continue

            mods = extract_modifications(modif_html, row.numero_norma)
            if not mods:
                continue

            affected: list[str] = []
            for mod in mods:
                idx = self._find_block_index(blocks, mod.article_id)
                if mod.kind == ModificationKind.SUBSTITUTE and mod.new_text:
                    new_version = Version(
                        norm_id=norm_id,
                        publication_date=edge.fecha_boletin,
                        effective_date=edge.fecha_boletin,
                        paragraphs=(
                            Paragraph(
                                css_class="articulo",
                                text=f"ARTICULO {mod.article_id}.—",
                            ),
                            Paragraph(css_class="parrafo", text=mod.new_text.strip()),
                        ),
                    )
                    if idx >= 0:
                        old = blocks[idx]
                        blocks[idx] = Block(
                            id=old.id,
                            block_type=old.block_type,
                            title=old.title,
                            versions=old.versions + (new_version,),
                        )
                    affected.append(mod.article_id)
                elif mod.kind == ModificationKind.REPEAL:
                    if idx >= 0:
                        old = blocks[idx]
                        tombstone = Version(
                            norm_id=norm_id,
                            publication_date=edge.fecha_boletin,
                            effective_date=edge.fecha_boletin,
                            paragraphs=(Paragraph(css_class="cita", text="(Artículo derogado)"),),
                        )
                        blocks[idx] = Block(
                            id=old.id,
                            block_type=old.block_type,
                            title=old.title,
                            versions=old.versions + (tombstone,),
                        )
                    affected.append(mod.article_id)

            if affected and edge.fecha_boletin not in seen_dates:
                reforms.append(
                    Reform(
                        date=edge.fecha_boletin,
                        norm_id=edge.id_modificatoria,
                        affected_blocks=tuple(sorted(set(affected))),
                    )
                )
                seen_dates.add(edge.fecha_boletin)

        reforms.sort(key=lambda r: r.date)
        return blocks, reforms

    @staticmethod
    def _find_block_index(blocks: list, article_id: str) -> int:
        target = article_id.strip().lower().replace("°", "").replace("º", "").replace(" ", "")
        if not target.startswith("art"):
            target = f"art{target}"
        for i, b in enumerate(blocks):
            if b.id.lower() == target:
                return i
        return -1

    # ── Helpers exposed to discovery / parser ──

    def get_row(self, norm_id: str) -> Optional[InfoLEGRow]:
        """Return the catalog row for a norm, loading the catalog if needed."""
        return self.catalog.get(norm_id)
