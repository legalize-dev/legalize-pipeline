"""Build a norm_id → Gazette Part III chapter event index.

Complements :class:`AnnualStatuteIndex` (which covers 2001+) by walking
every Gazette Part III PDF in the ``{data_dir}/gazette-pdf/`` cache and
attributing each chapter to the federal act it creates or amends via
:class:`TitleIndex`.

This fills the 1998-2000 gap between the LAC archive (pre-1998, deferred)
and annual-statutes (2001+). Output shape matches the amendment refs
used by the main merger in :meth:`JusticeCanadaClient.get_suvestine`.

**Known limitations.** Older issues (pre-2005 roughly) occasionally omit
the explicit ``CHAPTER N`` cover for the first or last chapter in an
issue — those chapters are missed by the current segmenter and recorded
in ``unresolved_events`` for inspection. Modern issues segment cleanly.
"""

from __future__ import annotations

import gc
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from legalize.fetcher.ca.gazette_segmenter import ChapterSegment, segment
from legalize.fetcher.ca.pdf_extractor import extract_text_from_pdf
from legalize.fetcher.ca.title_index import TitleIndex

logger = logging.getLogger(__name__)


INDEX_FILENAME = "gazette-index.json"


@dataclass(frozen=True)
class GazetteRef:
    """One Gazette chapter's attribution to a consolidated act."""

    year: int
    chapter: int
    assent_date: str  # ISO YYYY-MM-DD
    pdf_path: str  # relative to data_dir
    first_page: int
    last_page: int
    bill_number: str
    title_en: str
    title_fr: str
    ocr_confidence: float

    def as_date(self) -> date:
        return date.fromisoformat(self.assent_date)


@dataclass
class GazetteIndex:
    """Map of full norm_id → sorted list of Gazette chapter refs."""

    by_norm: dict[str, list[GazetteRef]] = field(default_factory=dict)
    unresolved: list[tuple[int, int, str]] = field(default_factory=list)

    def refs_for(self, norm_id: str) -> list[GazetteRef]:
        return list(self.by_norm.get(norm_id, ()))

    def to_json(self) -> str:
        return json.dumps(
            {
                "by_norm": {k: [asdict(r) for r in v] for k, v in sorted(self.by_norm.items())},
                "unresolved": list(self.unresolved),
            },
            sort_keys=True,
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, data: str) -> GazetteIndex:
        payload = json.loads(data)
        by_norm: dict[str, list[GazetteRef]] = {}
        for k, v in payload.get("by_norm", {}).items():
            by_norm[k] = [GazetteRef(**r) for r in v]
        unresolved = [tuple(t) for t in payload.get("unresolved", [])]
        return cls(by_norm=by_norm, unresolved=unresolved)


def _classify_title(title: str, lang: str) -> str:
    """Reduce a chapter title to the primary target act's name.

    Shares intent with
    :func:`annual_statute_index._classify_primary_target` but is simpler:
    Gazette cover titles are always single-sentence and formatted cleanly,
    so we strip an "An Act to amend the " / "Loi modifiant la " prefix
    if present and otherwise return the title as-is (creation-type bills
    name the act they enact).
    """
    import re

    t = title.strip()
    if not t:
        return ""

    if lang == "en":
        m = re.match(r"^An Act to amend\s+(?:the\s+)?(.+?)\s*$", t, re.IGNORECASE)
    else:
        m = re.match(
            r"^Loi\s+modifiant\s+(?:la\s+|le\s+|les\s+|l['’]\s*)?(.+?)\s*$",
            t,
            re.IGNORECASE,
        )
    if m:
        captured = m.group(1).strip()
        # Drop trailing " and the X Act" / "et la X" — primary only.
        if lang == "en":
            captured = re.sub(r"\s+and\s+(?:the\s+|to\s+).*$", "", captured, flags=re.IGNORECASE)
            captured = re.sub(r",\s+the\s+.*$", "", captured, flags=re.IGNORECASE)
        else:
            captured = re.sub(
                r"\s+et\s+(?:la\s+|le\s+|les\s+|à\s+).*$",
                "",
                captured,
                flags=re.IGNORECASE,
            )
        # Strip trailing parenthetical theme.
        captured = re.sub(r"\s*\([^)]*\)\s*$", "", captured).strip()
        return captured

    return t


def build_gazette_index(
    pdf_root: Path,
    title_index: TitleIndex,
) -> GazetteIndex:
    """Walk every PDF under ``pdf_root`` and emit a consolidated index.

    ``pdf_root`` is typically ``{data_dir}/gazette-pdf/{year}/*.pdf``.
    Missing directory is tolerated — empty index is returned.
    """
    result = GazetteIndex()
    if not pdf_root.is_dir():
        logger.info("No Gazette PDFs at %s (skipping index build)", pdf_root)
        return result

    pdf_paths = sorted(pdf_root.rglob("*.pdf"))
    if not pdf_paths:
        return result

    for pdf_path in pdf_paths:
        rel = pdf_path.relative_to(pdf_root.parent).as_posix()
        logger.info("Segmenting %s", rel)
        try:
            extraction = extract_text_from_pdf(pdf_path)
        except Exception as exc:  # noqa: BLE001 — best-effort, continue on any single failure
            logger.warning("Failed to extract %s: %s", pdf_path, exc)
            continue

        segments = segment(extraction)
        if not segments:
            logger.info("No chapters segmented in %s", rel)
            # Still release the extraction before moving on — a 400-page
            # issue holds several MB of per-column text that the next PDF
            # doesn't need.
            del extraction
            gc.collect()
            continue

        ocr_confidence = extraction.ocr_confidence
        for seg in segments:
            _attribute_segment(seg, rel, ocr_confidence, title_index, result)

        # Drop the heavy per-PDF objects (each extraction can hold 5-20 MB
        # of text across EN + FR columns for a full issue; segments retain
        # most of that via body strings). Explicit del + gc ensures the
        # next PDF starts from a cold memory state rather than piling on.
        del extraction, segments
        gc.collect()

    # Sort each norm's timeline chronologically.
    for refs in result.by_norm.values():
        refs.sort(key=lambda r: (r.assent_date, r.year, r.chapter))

    logger.info(
        "Gazette index: %d norms with chapters, %d unresolved",
        len(result.by_norm),
        len(result.unresolved),
    )
    return result


def _attribute_segment(
    seg: ChapterSegment,
    pdf_rel_path: str,
    ocr_confidence: float,
    title_index: TitleIndex,
    result: GazetteIndex,
) -> None:
    """Resolve a single chapter to its target norm(s) and append refs.

    Creates refs in both EN and FR jurisdictions when the respective title
    resolves. A missing resolution on one side doesn't block the other —
    the English-side resolve might succeed while the French-side fails if
    the French title drifted across the years.
    """
    ref_template: dict = {
        "year": seg.year,
        "chapter": seg.chapter,
        "assent_date": seg.assent_date.isoformat(),
        "pdf_path": pdf_rel_path,
        "first_page": seg.first_page,
        "last_page": seg.last_page,
        "bill_number": seg.bill_number,
        "title_en": seg.title_en,
        "title_fr": seg.title_fr,
        "ocr_confidence": ocr_confidence,
    }

    any_resolved = False
    for lang_code, title in (("en", seg.title_en), ("fr", seg.title_fr)):
        target = _classify_title(title, lang_code)
        if not target:
            continue
        norm_id = title_index.lookup(target, lang_code)
        if norm_id is None:
            # Try stripping a terminal parenthetical theme as a last resort.
            import re

            stripped = re.sub(r"\s*\([^)]*\)\s*$", "", target).strip()
            if stripped and stripped != target:
                norm_id = title_index.lookup(stripped, lang_code)
        if norm_id is None:
            continue
        any_resolved = True
        result.by_norm.setdefault(norm_id, []).append(GazetteRef(**ref_template))

    if not any_resolved:
        # Log at the year-chapter level so operators can trace what we missed.
        result.unresolved.append((seg.year, seg.chapter, seg.title_en or seg.title_fr))


def load_or_build_gazette_index(
    pdf_root: Path,
    title_index: TitleIndex,
    data_dir: Path,
    *,
    force_rebuild: bool = False,
) -> GazetteIndex:
    """Load the cached index or rebuild. Mirrors TitleIndex's cache pattern."""
    cache_path = data_dir / INDEX_FILENAME
    if cache_path.exists() and not force_rebuild:
        try:
            return GazetteIndex.from_json(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("Gazette index cache invalid (%s); rebuilding", exc)

    index = build_gazette_index(pdf_root, title_index)
    data_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(index.to_json(), encoding="utf-8")
    return index
