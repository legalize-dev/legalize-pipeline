"""Legislative domain data model.

Designed to be multi-country. Spain-specific concepts (Rank, BOE)
are encapsulated but the core model is generic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional


# ─────────────────────────────────────────────
# Normative rank — free-form string, extensible per country
# ─────────────────────────────────────────────


class Rank(str):
    """Normative rank of a legal provision.

    Free-form string — each country defines its own values.
    transformer/slug.py maps each rank to its folder in the repo.

    Spain: constitucion, ley_organica, ley, real_decreto_ley, ...
    France: code, loi, loi_organique, ordonnance, decret, constitution_fr, ...
    UK: act, statutory_instrument, ...
    """

    # Predefined constants for autocompletion and consistency.
    # Not restrictive — any string is valid as a Rank.

    # Spain — state level
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

    # Spain — autonomous communities (foral/regional equivalents)
    LEY_FORAL = "ley_foral"
    DECRETO_LEGISLATIVO = "decreto_legislativo"
    DECRETO_LEY_FORAL = "decreto_ley_foral"
    DECRETO_FORAL_LEGISLATIVO = "decreto_foral_legislativo"
    DECRETO_LEY = "decreto_ley"

    # France
    CODE = "code"
    LOI_ORGANIQUE = "loi_organique"
    LOI = "loi"
    ORDONNANCE = "ordonnance"
    DECRET = "decret"
    CONSTITUTION_FR = "constitution_fr"

    # Argentina — national
    DECRETO_NECESIDAD_URGENCIA = "decreto_necesidad_urgencia"
    DECISION_ADMINISTRATIVA = "decision_administrativa"
    COMUNICACION = "comunicacion"
    ACORDADA = "acordada"

    OTRO = "otro"


class CommitType(str, Enum):
    """Commit type in the legislative history (generic, multi-country)."""

    NEW = "new"
    REFORM = "reform"
    REPEAL = "repeal"
    CORRECTION = "correction"
    BOOTSTRAP = "bootstrap"
    FIX_PIPELINE = "fix-pipeline"


class NormStatus(str, Enum):
    """Validity status of a norm (generic, multi-country)."""

    IN_FORCE = "in_force"
    REPEALED = "repealed"
    PARTIALLY_REPEALED = "partially_repealed"
    ANNULLED = "annulled"
    EXPIRED = "expired"


class TextState(str, Enum):
    """What a file's body actually is (Legalize Format Spec v0.3).

    Two different questions decide this: are the amendments incorporated into
    the text, and does the text correspond to the date the file claims. A body
    can be consolidated and still not be the law as it stood at that date.

    POINT_IN_TIME is the default and is never written to the frontmatter — a
    file without the field is the law as in force on its ``last_updated``.
    """

    POINT_IN_TIME = "point_in_time"  # the law as in force on last_updated
    CURRENT = "current"  # the latest text the source publishes, whatever the date
    AS_ENACTED = "as_enacted"  # the act as published; amendments not incorporated


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

    norm_id: str
    publication_date: date
    effective_date: date
    paragraphs: tuple[Paragraph, ...]


@dataclass(frozen=True)
class Block:
    """Structural unit of a norm (article, title, chapter, etc.)."""

    id: str
    block_type: str
    title: str
    versions: tuple[Version, ...]


# ─────────────────────────────────────────────
# Norm metadata (generic, multi-country)
# ─────────────────────────────────────────────


@dataclass(frozen=True)
class NormMetadata:
    """Complete metadata of a legislative norm.

    Generic fields applicable to any country:
    - identifier: unique official ID (BOE-A-1978-31229 in Spain, JORF... in France)
    - country: ISO 3166-1 alpha-2 code
    - rank: norm type/rank (country-specific enum)
    - source: official URL of the norm
    """

    title: str
    short_title: str
    identifier: str  # Official ID: BOE-A-..., JORF-..., etc.
    country: str  # ISO 3166-1 alpha-2: "es", "fr", "de"
    rank: Rank
    publication_date: date
    status: NormStatus
    department: str
    source: str  # Official URL
    jurisdiction: Optional[str] = None  # ELI code: "es-pv", "es-ct", None=state-level
    last_modified: Optional[date] = None
    pdf_url: Optional[str] = None
    subjects: tuple[str, ...] = ()
    summary: str = ""
    extra: tuple[tuple[str, str], ...] = ()  # Country-specific key-value pairs for frontmatter
    # None → the country default from countries.TEXT_STATE. Set explicitly only
    # to override one norm: inside a consolidated country there are individual
    # norms the source never consolidated (ar tier 2, eu, lu, ch).
    text_state: Optional[TextState] = None
    last_amendment: Optional[str] = None  # official ID of the most recent amending act


# ─────────────────────────────────────────────
# Reform timeline
# ─────────────────────────────────────────────


@dataclass(frozen=True)
class Reform:
    """A point in time where the norm changed."""

    date: date
    norm_id: str
    affected_blocks: tuple[str, ...]


# ─────────────────────────────────────────────
# Aggregates
# ─────────────────────────────────────────────


@dataclass(frozen=True)
class ParsedNorm:
    """Fully parsed norm: metadata + structure + timeline."""

    metadata: NormMetadata
    blocks: tuple[Block, ...]
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
    title: str
    rank: Optional[Rank]
    department: str
    url_xml: str
    affected_norms: tuple[str, ...]
    is_new: bool = False
    is_correction: bool = False
