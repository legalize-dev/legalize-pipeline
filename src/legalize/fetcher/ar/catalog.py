"""In-memory index of the InfoLEG catalog CSV + modifications graph.

The InfoLEG open-data dataset on datos.jus.gob.ar publishes three monthly CSVs:

- ``base-infoleg-normativa-nacional.csv`` — the master catalog (~423K rows,
  17 columns), one row per national norm. Includes ``texto_actualizado`` and
  ``texto_original`` URLs.
- ``base-complementaria-infoleg-normas-modificadas.csv`` — for each norm,
  every modification it received (~376K edges).
- ``base-complementaria-infoleg-normas-modificatorias.csv`` — inverse view.

This module loads the first two and builds two in-memory indices:

1. ``by_id``: id_norma → :class:`InfoLEGRow` (full row data)
2. ``modifications_of``: id_norma → ordered list of (modificatoria_id, fecha)

Memory footprint: ~423K rows × ~600 bytes ≈ 250 MB resident. Acceptable for
the bootstrap. For incremental updates we re-load on each run.
"""

from __future__ import annotations

import csv
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterator, Optional

from legalize.transformer import slug

logger = logging.getLogger(__name__)


def _parse_date(value: str) -> Optional[date]:
    """Parse YYYY-MM-DD; return None for empty/invalid."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_int(value: str) -> int:
    """Parse integer; return 0 for empty/invalid."""
    if not value:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


@dataclass(frozen=True)
class InfoLEGRow:
    """One row from base-infoleg-normativa-nacional.csv.

    Field names match the CSV columns verbatim (Spanish).
    """

    id_norma: str
    tipo_norma: str
    numero_norma: str
    clase_norma: str
    organismo_origen: str
    fecha_sancion: Optional[date]
    numero_boletin: str
    fecha_boletin: Optional[date]
    pagina_boletin: str
    titulo_resumido: str
    titulo_sumario: str
    texto_resumido: str
    observaciones: str
    texto_original: str
    texto_actualizado: str
    modificada_por: int
    modifica_a: int

    @property
    def has_consolidated_text(self) -> bool:
        """True if texto_actualizado is populated (Tier 1)."""
        return bool(self.texto_actualizado)

    @property
    def has_original_text(self) -> bool:
        """True if texto_original is populated (Tier 2)."""
        return bool(self.texto_original)


@dataclass(frozen=True)
class ModificationEdge:
    """One row from base-complementaria-infoleg-normas-modificadas.csv.

    Represents: norm ``id_norma_modificada`` was modified by
    ``id_norma_modificatoria`` on ``fecha_boletin``.
    """

    id_modificada: str
    id_modificatoria: str
    tipo_norma: str
    nro_norma: str
    clase_norma: str
    organismo_origen: str
    fecha_boletin: Optional[date]
    titulo_sumario: str
    titulo_resumido: str


@dataclass
class InfoLEGCatalog:
    """In-memory index of the InfoLEG catalog + modifications graph."""

    by_id: dict[str, InfoLEGRow] = field(default_factory=dict)
    # id_norma → list of edges, sorted by fecha_boletin ascending
    modifications_of: dict[str, list[ModificationEdge]] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.by_id)

    def get(self, id_norma: str) -> Optional[InfoLEGRow]:
        return self.by_id.get(id_norma)

    def filter_tier1(
        self, allowed_types: frozenset[str], extra_whitelist: frozenset[str] = frozenset()
    ) -> Iterator[InfoLEGRow]:
        """Yield rows with consolidated text matching the allowed types,
        plus any norm whose ``id_norma`` is in ``extra_whitelist`` (used to
        force-include the Constitución even though it is Tier 2).
        """
        for row in self.by_id.values():
            if row.id_norma in extra_whitelist:
                yield row
                continue
            if not row.has_consolidated_text and not row.has_original_text:
                continue
            if row.tipo_norma not in allowed_types:
                continue
            yield row

    def reforms_for(self, id_norma: str) -> list[ModificationEdge]:
        """Get the chronologically-ordered list of modifications to a norm."""
        return self.modifications_of.get(id_norma, [])
    
    def get_by_slug(self, slug: str) -> Optional[InfoLEGRow]:
        """Look up a row by its pipeline slug (e.g. 'LEY-24430').

        The slug is built as tipo_norma.upper() + '-' + numero_norma.
        Builds a lazy reverse index on first call.
        """
        if not hasattr(self, "_slug_index"):
            self._slug_index = {
                f"{r.tipo_norma.upper()}-{r.numero_norma}": r
                for r in self.by_id.values()
            }
        return self._slug_index.get(slug)


def _open_csv(path: Path) -> Iterator[dict[str, str]]:
    """Open a UTF-8 CSV (or a single-file ZIP containing one) and yield rows as dicts."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.endswith(".csv")]
            if not names:
                raise ValueError(f"No CSV inside {path}")
            with zf.open(names[0]) as fp:
                # csv.DictReader needs str, not bytes
                import io as _io

                reader = csv.DictReader(_io.TextIOWrapper(fp, encoding="utf-8", newline=""))
                yield from reader
    else:
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            yield from reader


def load_catalog(
    catalog_path: Path,
    modifications_path: Optional[Path] = None,
) -> InfoLEGCatalog:
    """Load the InfoLEG catalog and (optionally) the modifications graph.

    Args:
        catalog_path: path to ``base-infoleg-normativa-nacional.csv`` or .zip.
        modifications_path: path to ``base-complementaria-infoleg-normas-modificadas.csv``
            (or .zip). Optional but required for reform reconstruction.

    Returns:
        :class:`InfoLEGCatalog` ready for filtering and reform lookup.
    """
    catalog = InfoLEGCatalog()

    logger.info("Loading InfoLEG catalog from %s", catalog_path)
    n = 0
    for raw in _open_csv(catalog_path):
        row = InfoLEGRow(
            id_norma=raw.get("id_norma", "").strip(),
            tipo_norma=raw.get("tipo_norma", "").strip(),
            numero_norma=raw.get("numero_norma", "").strip(),
            clase_norma=raw.get("clase_norma", "").strip(),
            organismo_origen=raw.get("organismo_origen", "").strip(),
            fecha_sancion=_parse_date(raw.get("fecha_sancion", "").strip()),
            numero_boletin=raw.get("numero_boletin", "").strip(),
            fecha_boletin=_parse_date(raw.get("fecha_boletin", "").strip()),
            pagina_boletin=raw.get("pagina_boletin", "").strip(),
            titulo_resumido=raw.get("titulo_resumido", "").strip(),
            titulo_sumario=raw.get("titulo_sumario", "").strip(),
            texto_resumido=raw.get("texto_resumido", "").strip(),
            observaciones=raw.get("observaciones", "").strip(),
            texto_original=raw.get("texto_original", "").strip(),
            texto_actualizado=raw.get("texto_actualizado", "").strip(),
            modificada_por=_parse_int(raw.get("modificada_por", "").strip()),
            modifica_a=_parse_int(raw.get("modifica_a", "").strip()),
        )
        if row.id_norma:
            catalog.by_id[row.id_norma] = row
            n += 1
    logger.info("Loaded %d catalog rows", n)

    if modifications_path:
        logger.info("Loading modifications graph from %s", modifications_path)
        edges_n = 0
        for raw in _open_csv(modifications_path):
            id_mod = raw.get("id_norma_modificada", "").strip()
            id_modificatoria = raw.get("id_norma_modificatoria", "").strip()
            if not id_mod or not id_modificatoria:
                continue
            edge = ModificationEdge(
                id_modificada=id_mod,
                id_modificatoria=id_modificatoria,
                tipo_norma=raw.get("tipo_norma", "").strip(),
                nro_norma=raw.get("nro_norma", "").strip(),
                clase_norma=raw.get("clase_norma", "").strip(),
                organismo_origen=raw.get("organismo_origen", "").strip(),
                fecha_boletin=_parse_date(raw.get("fecha_boletin", "").strip()),
                titulo_sumario=raw.get("titulo_sumario", "").strip(),
                titulo_resumido=raw.get("titulo_resumido", "").strip(),
            )
            catalog.modifications_of.setdefault(id_mod, []).append(edge)
            edges_n += 1

        # Sort each norm's modifications chronologically; edges with no date
        # (rare but present) sink to the end
        for edges in catalog.modifications_of.values():
            edges.sort(key=lambda e: e.fecha_boletin or date(9999, 12, 31))
        logger.info(
            "Loaded %d modification edges across %d norms", edges_n, len(catalog.modifications_of)
        )

    return catalog


# ── URL helpers ──


_INFOLEG_BASE = "http://servicios.infoleg.gob.ar/infolegInternet"


def url_for(id_norma: str | int, kind: str = "texact") -> str:
    """Build the canonical InfoLEG URL for a norm.

    Args:
        id_norma: numeric norm ID.
        kind: ``"texact"`` for the consolidated text, ``"norma"`` for the
            original published text.
    """
    nid = int(id_norma)
    range_start = (nid // 5000) * 5000
    range_end = range_start + 4999
    return f"{_INFOLEG_BASE}/anexos/{range_start}-{range_end}/{nid}/{kind}.htm"
