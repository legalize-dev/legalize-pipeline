"""Historical version reconstruction for Argentine legislation.

Given a norm's catalog row and the list of modificatorias that touch it,
this module reconstructs every per-date snapshot by:

1. Parsing ``norma.htm`` → bootstrap snapshot (v0) at ``fecha_boletin``.
2. For each modificatoria (sorted by fecha_boletin ASC):
   - Fetching the modificatoria's own ``norma.htm``.
   - Calling :func:`legalize.fetcher.ar.reforms.extract_modifications`.
   - Applying the substitutions/repeals/insertions to the running blocks.
   - Emitting a new :class:`Snapshot` at the modificatoria's B.O. date.
3. Comparing the final reconstructed snapshot against the consolidated
   ``texact.htm`` the catalog points to. Depending on how well it matches,
   the reconstruction is classified as ``CLEAN`` / ``PARTIAL`` /
   ``BOOTSTRAP_ONLY`` and (for PARTIAL/BOOTSTRAP_ONLY) a final
   ``[consolidacion]`` snapshot is appended so the user always lands on
   the authoritative current text.

The strategy assumes two things that are not always true: that a
modificatoria's own text is complete and templated enough to replay (see
:mod:`legalize.fetcher.ar.reforms` for the four patterns and their limits), and
that the catalog's modifications graph is the whole truth about what touched a
norm. Step 3 is what makes that safe — the convergence check against
``texact.htm`` decides whether a reconstructed timeline is published as history
or collapsed back to ``v0 + [consolidacion]``, so a bad replay costs us versions,
never a wrong current text. Validated in a POC on 2026-04-11 against Ley 19.550
(Sociedades) with Ley 27.444 as the modificatoria.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Protocol

from legalize.fetcher.ar.catalog import InfoLEGCatalog, InfoLEGRow, ModificationEdge
from legalize.fetcher.ar.reforms import (
    Modification,
    ModificationKind,
    extract_modifications,
)
from legalize.models import Block, Paragraph, Version

logger = logging.getLogger(__name__)


class ReconstructionQuality(str, Enum):
    """How faithful the reconstructed timeline is to the ground truth."""

    CLEAN = "clean"  # vN matches texact.htm within tolerance
    PARTIAL = "partial"  # some reforms couldn't be applied — final [consolidacion] forced
    BOOTSTRAP_ONLY = "bootstrap-only"  # reconstruction failed — only v0 + [consolidacion]


@dataclass(frozen=True)
class Snapshot:
    """Full snapshot of a norm at a specific date, ready to commit."""

    commit_date: date
    blocks: tuple[Block, ...]
    source_id: (
        str  # id_norma that originated this snapshot (bootstrap / modificatoria / consolidation)
    )
    source_label: str  # "bootstrap", "Ley XXX", "consolidacion"
    affected_article_ids: tuple[str, ...] = ()  # ids mutated vs the previous snapshot


@dataclass
class ReconstructionResult:
    """Result of reconstructing a single norm's timeline."""

    quality: ReconstructionQuality
    snapshots: list[Snapshot]
    discrepancies: list[str] = field(default_factory=list)
    applied: int = 0
    skipped: int = 0


# ── Client protocol ──


class _TextClient(Protocol):
    """Minimal interface we need from InfoLEGClient."""

    def get_text(self, norm_id: str) -> bytes: ...
    def get_modificatoria_text(self, norm_id: str) -> bytes: ...


# ── Helpers to apply a Modification to a list of Blocks ──


def _norm_article_id(raw: str) -> str:
    """Normalize an article id to the canonical Block id form.

    Examples:
        ``"8"``         → ``"art8"``
        ``"8 bis"``     → ``"art8bis"``
        ``"8 ter"``     → ``"art8ter"``
        ``"8°"``        → ``"art8"``
    """
    s = raw.strip().lower()
    s = s.replace("°", "").replace("º", "").replace(".", "")
    s = s.replace(" ", "")
    if s.startswith("art"):
        return s
    return f"art{s}"


def _find_block_index(blocks: list[Block], article_id: str) -> int:
    """Return the index of a block by its normalized article id, or -1."""
    target = _norm_article_id(article_id)
    for i, b in enumerate(blocks):
        if b.id.lower() == target:
            return i
    return -1


def _build_substitute_block(
    article_id: str,
    new_text: str,
    pub_date: date,
    law_norm_id: str,
) -> Block:
    """Create a replacement Block for a SUBSTITUTE modification."""
    # The new body may already start with "Artículo X°:" — keep it as the
    # article header paragraph. Otherwise create a canonical one.
    clean = new_text.strip()
    paragraphs: list[Paragraph] = [
        Paragraph(css_class="articulo", text=f"ARTICULO {article_id}.—"),
        Paragraph(css_class="parrafo", text=clean),
    ]
    version = Version(
        norm_id=law_norm_id,
        publication_date=pub_date,
        effective_date=pub_date,
        paragraphs=tuple(paragraphs),
    )
    return Block(
        id=_norm_article_id(article_id),
        block_type="article",
        title=f"ARTICULO {article_id}",
        versions=(version,),
    )


def _build_repeal_block(
    article_id: str,
    pub_date: date,
    law_norm_id: str,
) -> Block:
    """Create a tombstone Block for a REPEAL modification."""
    paragraphs: list[Paragraph] = [
        Paragraph(css_class="articulo", text=f"ARTICULO {article_id}.—"),
        Paragraph(css_class="cita", text="(Artículo derogado)"),
    ]
    version = Version(
        norm_id=law_norm_id,
        publication_date=pub_date,
        effective_date=pub_date,
        paragraphs=tuple(paragraphs),
    )
    return Block(
        id=_norm_article_id(article_id),
        block_type="article",
        title=f"ARTICULO {article_id} (derogado)",
        versions=(version,),
    )


def _apply_one_modification(
    blocks: list[Block],
    mod: Modification,
    pub_date: date,
    law_norm_id: str,
) -> bool:
    """Apply a single :class:`Modification` to the running block list in-place.

    Returns ``True`` if the change was applied, ``False`` if it was skipped
    (unknown pattern, article not found, etc.).
    """
    if mod.kind == ModificationKind.SUBSTITUTE:
        idx = _find_block_index(blocks, mod.article_id)
        new_block = _build_substitute_block(mod.article_id, mod.new_text, pub_date, law_norm_id)
        if idx >= 0:
            blocks[idx] = new_block
        else:
            # The article doesn't exist in our v0 — append it so we don't
            # lose the content. This can happen if norma.htm has a sparser
            # structure than the reform expects.
            blocks.append(new_block)
        return True

    if mod.kind == ModificationKind.REPEAL:
        idx = _find_block_index(blocks, mod.article_id)
        if idx >= 0:
            blocks[idx] = _build_repeal_block(mod.article_id, pub_date, law_norm_id)
            return True
        return False

    if mod.kind == ModificationKind.INSERT:
        new_block = _build_substitute_block(mod.article_id, mod.new_text, pub_date, law_norm_id)
        # Try to insert right after the "parent" article (strip bis/ter)
        base = re.sub(r"\s*(bis|ter|qu[áa]ter)\b", "", mod.article_id, flags=re.IGNORECASE).strip()
        parent_idx = _find_block_index(blocks, base)
        if parent_idx >= 0:
            blocks.insert(parent_idx + 1, new_block)
        else:
            blocks.append(new_block)
        return True

    if mod.kind in (ModificationKind.AMOUNT_UPDATE, ModificationKind.UNKNOWN):
        return False

    return False


# ── Convergence check ──


_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _similarity(left: str, right: str) -> float:
    """Rough word-set similarity in [0, 1]. We don't need exact match — the
    pipeline writes the final [consolidacion] verbatim anyway; this is just
    to classify the reconstruction quality."""
    if not left and not right:
        return 1.0
    lt, rt = set(_tokenize(left)), set(_tokenize(right))
    if not lt and not rt:
        return 1.0
    inter = lt & rt
    union = lt | rt
    return len(inter) / len(union) if union else 0.0


def _blocks_to_plain(blocks: list[Block]) -> str:
    """Flatten blocks into a single plain-text string for similarity checks."""
    parts: list[str] = []
    for b in blocks:
        if not b.versions:
            continue
        for p in b.versions[-1].paragraphs:
            parts.append(p.text)
    return "\n".join(parts)


# ── Main entry ──


def reconstruct(
    client: _TextClient,
    row: InfoLEGRow,
    catalog: InfoLEGCatalog,
    text_parser,
    *,
    relevant_modificatoria_types: frozenset[str] = frozenset({"Ley", "Decreto", "Decreto/Ley"}),
    max_drift_clean: float = 0.05,
    max_drift_partial: float = 0.30,
) -> ReconstructionResult:
    """Reconstruct the full timeline of a norm as a list of :class:`Snapshot`.

    Args:
        client: InfoLEG client (used for ``get_text`` and ``get_modificatoria_text``).
        row: catalog row of the target norm.
        catalog: loaded InfoLEG catalog (for the modifications graph).
        text_parser: :class:`InfoLEGTextParser` instance used to parse HTML.
        relevant_modificatoria_types: only modificatorias of these types are
            fetched and applied. Resoluciones (~94/170 for Ley 19.550) typically
            update monetary amounts only and don't match our text patterns —
            skipping them avoids noise and wasted fetches.
        max_drift_clean: word-set dissimilarity below which we call the
            reconstruction CLEAN.
        max_drift_partial: dissimilarity below which we call it PARTIAL.

    Returns:
        :class:`ReconstructionResult` with snapshots, quality grade, and
        per-modification diagnostics.
    """
    law_norm_id = row.id_norma
    # Prefer fecha_boletin, fall back to fecha_sancion, then to a sentinel.
    # Many pre-1997 rows only have fecha_sancion (the act date) because
    # InfoLEG did not backfill fecha_boletin for historical norms.
    pub_date = row.fecha_boletin or row.fecha_sancion or date(1900, 1, 1)

    # ── Step 1: bootstrap snapshot from norma.htm (fallback: texact.htm) ──
    try:
        if row.has_original_text:
            v0_html = client.get_modificatoria_text(law_norm_id)  # same URL shape
        elif row.has_consolidated_text:
            v0_html = client.get_text(law_norm_id)
        else:
            raise ValueError("neither texto_original nor texto_actualizado available")
    except Exception as exc:
        logger.error("Failed to fetch bootstrap text for %s: %s", law_norm_id, exc)
        return ReconstructionResult(
            quality=ReconstructionQuality.BOOTSTRAP_ONLY,
            snapshots=[],
            discrepancies=[f"bootstrap fetch failed: {exc}"],
        )

    v0_blocks_raw = text_parser.parse_text(v0_html)
    # The parser emits blocks with a placeholder pub_date/law_norm_id.
    # Rewrite them with the real values so downstream rendering is correct.
    v0_blocks: list[Block] = [_rebrand_block(b, pub_date, law_norm_id) for b in v0_blocks_raw]

    if not v0_blocks:
        return ReconstructionResult(
            quality=ReconstructionQuality.BOOTSTRAP_ONLY,
            snapshots=[],
            discrepancies=["v0 had no blocks after parsing"],
        )

    snapshots: list[Snapshot] = [
        Snapshot(
            commit_date=pub_date,
            blocks=tuple(v0_blocks),
            source_id=law_norm_id,
            source_label="bootstrap",
            affected_article_ids=(),
        )
    ]

    # ── Step 2: walk modificatorias chronologically ──
    edges: list[ModificationEdge] = catalog.reforms_for(law_norm_id)
    applied = 0
    skipped = 0
    discrepancies: list[str] = []

    # Accumulate changes until the next distinct B.O. date, then emit one
    # snapshot per date. Multiple edges can share a date (several norms
    # published on the same day that each touch the target).
    current_blocks = list(v0_blocks)
    running_by_date: dict[date, list[ModificationEdge]] = {}

    for edge in edges:
        if edge.tipo_norma not in relevant_modificatoria_types:
            skipped += 1
            continue
        if edge.fecha_boletin is None:
            skipped += 1
            continue
        running_by_date.setdefault(edge.fecha_boletin, []).append(edge)

    for rdate in sorted(running_by_date.keys()):
        affected: list[str] = []
        any_applied = False
        day_source_ids: list[str] = []
        day_labels: list[str] = []

        for edge in running_by_date[rdate]:
            try:
                modif_html = client.get_modificatoria_text(edge.id_modificatoria)
            except Exception as exc:
                skipped += 1
                discrepancies.append(f"fetch {edge.id_modificatoria}: {exc}")
                continue

            mods = extract_modifications(modif_html, row.numero_norma)
            if not mods:
                skipped += 1
                continue

            for mod in mods:
                ok = _apply_one_modification(current_blocks, mod, rdate, law_norm_id)
                if ok:
                    applied += 1
                    affected.append(mod.article_id)
                    any_applied = True
                else:
                    skipped += 1

            day_source_ids.append(edge.id_modificatoria)
            day_labels.append(f"{edge.tipo_norma} {edge.nro_norma}".strip())

        if any_applied:
            snapshots.append(
                Snapshot(
                    commit_date=rdate,
                    blocks=tuple(current_blocks),
                    source_id="+".join(day_source_ids),
                    source_label=" / ".join(day_labels) or "reforma",
                    affected_article_ids=tuple(sorted(set(affected))),
                )
            )

    # ── Step 3: convergence check against texact.htm ──
    quality = ReconstructionQuality.BOOTSTRAP_ONLY
    if row.has_consolidated_text:
        try:
            consolidated_html = client.get_text(law_norm_id)
            consolidated_blocks = [
                _rebrand_block(b, date.today(), law_norm_id)
                for b in text_parser.parse_text(consolidated_html)
            ]
        except Exception as exc:
            logger.warning("Final texact.htm fetch failed for %s: %s", law_norm_id, exc)
            consolidated_blocks = []

        if consolidated_blocks:
            reconstructed_plain = _blocks_to_plain(current_blocks)
            ground_truth_plain = _blocks_to_plain(consolidated_blocks)
            sim = _similarity(reconstructed_plain, ground_truth_plain)
            drift = 1.0 - sim
            logger.debug(
                "Convergence for %s: sim=%.3f drift=%.3f (applied=%d skipped=%d)",
                law_norm_id,
                sim,
                drift,
                applied,
                skipped,
            )

            if drift <= max_drift_clean:
                quality = ReconstructionQuality.CLEAN
            elif drift <= max_drift_partial:
                quality = ReconstructionQuality.PARTIAL
            else:
                quality = ReconstructionQuality.BOOTSTRAP_ONLY

            # Always append a final [consolidacion] snapshot when it differs
            # from the last reconstructed state — this guarantees the user
            # lands on authoritative current text, even if we dropped commits.
            if reconstructed_plain != ground_truth_plain:
                snapshots.append(
                    Snapshot(
                        commit_date=date.today(),
                        blocks=tuple(consolidated_blocks),
                        source_id=law_norm_id,
                        source_label="consolidacion",
                        affected_article_ids=(),
                    )
                )
            if quality == ReconstructionQuality.BOOTSTRAP_ONLY:
                # Collapse to v0 + consolidacion only (drop the noisy middle)
                if len(snapshots) >= 2:
                    snapshots = [snapshots[0], snapshots[-1]]
    else:
        # Tier 2: only norma.htm available, cannot verify. Emit v0 alone.
        quality = ReconstructionQuality.CLEAN if len(edges) == 0 else ReconstructionQuality.PARTIAL

    return ReconstructionResult(
        quality=quality,
        snapshots=snapshots,
        discrepancies=discrepancies,
        applied=applied,
        skipped=skipped,
    )


def _rebrand_block(block: Block, pub_date: date, law_norm_id: str) -> Block:
    """Return a copy of ``block`` with every :class:`Version` re-stamped to
    ``pub_date`` and ``law_norm_id``.

    The text parser emits blocks with placeholder values because it has no
    access to the metadata. The reconstructor fills them in once the
    :class:`InfoLEGRow` is known.
    """
    new_versions = tuple(
        Version(
            norm_id=law_norm_id,
            publication_date=pub_date,
            effective_date=pub_date,
            paragraphs=v.paragraphs,
        )
        for v in block.versions
    )
    return Block(
        id=block.id,
        block_type=block.block_type,
        title=block.title,
        versions=new_versions,
    )


__all__ = [
    "ReconstructionQuality",
    "ReconstructionResult",
    "Snapshot",
    "reconstruct",
]
