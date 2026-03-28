"""Legislative domain data model.

Designed to be multi-country. Spain-specific concepts (Rango, BOE)
are encapsulated but the core model is generic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional


# ─────────────────────────────────────────────
# Rango normativo — free-form string, extensible per country
# ─────────────────────────────────────────────


class Rango(str):
    """Normative rank of a legal provision.

    Free-form string — each country defines its own values.
    transformer/slug.py maps each rango to its folder in the repo.

    Spain: constitucion, ley_organica, ley, real_decreto_ley, ...
    France: code, loi, loi_organique, ordonnance, decret, constitution_fr, ...
    UK: act, statutory_instrument, ...
    """

    # Predefined constants for autocompletion and consistency.
    # Not restrictive — any string is valid as a Rango.

    # Spain
    CONSTITUCION = "constitucion"
    LEY_ORGANICA = "ley_organica"
    LEY = "ley"
    REAL_DECRETO_LEY = "real_decreto_ley"
    REAL_DECRETO_LEGISLATIVO = "real_decreto_legislativo"
    REAL_DECRETO = "real_decreto"
    ORDEN = "orden"
    RESOLUCION = "resolucion"
    ACUERDO_INTERNACIONAL = "acuerdo_internacional"
    CIRCULAR = "circular"
    INSTRUCCION = "instruccion"
    DECRETO = "decreto"
    ACUERDO = "acuerdo"
    REGLAMENTO = "reglamento"

    # France
    CODE = "code"
    LOI_ORGANIQUE = "loi_organique"
    LOI = "loi"
    ORDONNANCE = "ordonnance"
    DECRET = "decret"
    CONSTITUTION_FR = "constitution_fr"

    OTRO = "otro"


class CommitType(str, Enum):
    """Commit type in the legislative history (generic, multi-country)."""

    NUEVA = "nueva"
    REFORMA = "reforma"
    DEROGACION = "derogacion"
    CORRECCION = "correccion"
    BOOTSTRAP = "bootstrap"
    FIX_PIPELINE = "fix-pipeline"


class EstadoNorma(str, Enum):
    """Validity status of a norm (generic, multi-country)."""

    VIGENTE = "vigente"
    DEROGADA = "derogada"
    PARCIALMENTE_DEROGADA = "parcialmente_derogada"


# ─────────────────────────────────────────────
# XML model (blocks and versions)
# ─────────────────────────────────────────────


@dataclass(frozen=True)
class Paragraph:
    """A paragraph within a block version."""

    css_class: str
    text: str


@dataclass(frozen=True)
class Version:
    """A temporal version of a block, introduced by a legal provision."""

    id_norma: str
    fecha_publicacion: date
    fecha_vigencia: date
    paragraphs: tuple[Paragraph, ...]


@dataclass(frozen=True)
class Bloque:
    """Structural unit of a norm (article, title, chapter, etc.)."""

    id: str
    tipo: str
    titulo: str
    versions: tuple[Version, ...]


# ─────────────────────────────────────────────
# Norm metadata (generic, multi-country)
# ─────────────────────────────────────────────


@dataclass(frozen=True)
class NormaMetadata:
    """Complete metadata of a legislative norm.

    Generic fields applicable to any country:
    - identificador: unique official ID (BOE-A-1978-31229 in Spain, JORF... in France)
    - pais: ISO 3166-1 alpha-2 code
    - rango: norm type/rank (country-specific enum)
    - fuente: official URL of the norm
    """

    titulo: str
    titulo_corto: str
    identificador: str  # Official ID: BOE-A-..., JORF-..., etc.
    pais: str  # ISO 3166-1 alpha-2: "es", "fr", "de"
    rango: Rango
    fecha_publicacion: date
    estado: EstadoNorma
    departamento: str
    fuente: str  # Official URL
    fecha_ultima_modificacion: Optional[date] = None
    url_pdf: Optional[str] = None
    materias: tuple[str, ...] = ()
    notas: str = ""


# ─────────────────────────────────────────────
# Reform timeline
# ─────────────────────────────────────────────


@dataclass(frozen=True)
class Reform:
    """A point in time where the norm changed."""

    fecha: date
    id_norma: str
    bloques_afectados: tuple[str, ...]


# ─────────────────────────────────────────────
# Aggregates
# ─────────────────────────────────────────────


@dataclass(frozen=True)
class NormaCompleta:
    """Fully parsed norm: metadata + structure + timeline."""

    metadata: NormaMetadata
    bloques: tuple[Bloque, ...]
    reforms: tuple[Reform, ...]


@dataclass(frozen=True)
class CommitInfo:
    """Everything needed to create a git commit."""

    commit_type: CommitType
    subject: str
    body: str
    trailers: dict[str, str]
    author_name: str
    author_email: str
    author_date: date
    file_path: str  # e.g.: "leyes/BOE-A-2015-11430.md"
    content: str


# ─────────────────────────────────────────────
# Daily summary dispositions (Spain)
# ─────────────────────────────────────────────


@dataclass(frozen=True)
class Disposition:
    """An individual disposition from a daily BOE summary."""

    id_boe: str
    titulo: str
    rango: Optional[Rango]
    departamento: str
    url_xml: str
    normas_afectadas: tuple[str, ...]
    es_nueva: bool = False
    es_correccion: bool = False
