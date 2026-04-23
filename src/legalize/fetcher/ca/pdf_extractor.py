"""Column-aware PDF text extraction for Canada Gazette Part III.

Canada Gazette Part III publishes Public Acts as-enacted in a bilingual,
side-by-side layout: English on the left half of each page, French on the
right. pypdfium2's plain ``get_text_range`` reads the page top-to-bottom,
left-to-right, which interleaves the two languages line by line. Instead,
we use ``get_text_bounded`` with a column-width crop to pull each language
separately in natural reading order.

Pipeline per page:

1. **Column extraction** via ``pypdfium2.PdfTextpage.get_text_bounded``,
   splitting the page at the vertical midline. Modern issues (1998+) have
   remarkably consistent A4 portrait geometry and a clean midline — no
   empirical tuning needed.

2. **Text cleanup** adapted from the reference Greek FEK extractor
   (``fetcher/gr/pdf_extractor.py``, MIT-license lineage):
   - Control-character stripping (C0/C1 minus tab/LF/CR).
   - Invisible-character stripping (U+00AD soft hyphen, U+FFFE, U+FFFD).
   - End-of-line hyphen merging ("consoli-\nated" → "consolidated").
   - Run-of-spaces collapse.
   - Repeated-header detection and removal (the masthead "Canada Gazette
     Part III / Gazette du Canada Partie III" repeats verbatim on every
     continuation page).

Unlike the Greek extractor we do *not* need mojibake recovery — Canada
Gazette PDFs 1998+ use proper Unicode CMaps. Pre-1998 LAC scans are OCR'd
and carry their own errors (``Ottawa`` → ``Orrnwa``) which we tag in
``extract_text_from_pdf``'s return value so downstream commits can surface
an OCR-quality warning.
"""

from __future__ import annotations

import gc
import hashlib
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Union

import pypdfium2 as pdfium

logger = logging.getLogger(__name__)

# Small LRU cache keyed on SHA-1 of the input bytes so calling the
# extractor twice on the same PDF (e.g. segmenter then a metadata pass)
# reads from memory instead of re-rasterising.
_EXTRACT_CACHE_SIZE = 8
_EXTRACT_CACHE: OrderedDict[str, GazetteExtraction] = OrderedDict()


_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_INVISIBLE_RE = re.compile("[­￾�]")
_HYPHENS = ("-", "−")  # ASCII hyphen + U+2212 MINUS SIGN
_A4_WIDTH = 595
_A4_HEIGHT = 842
# Standard US Letter also appears in older issues; both work the same way
# with our midline split, so we don't constrain on page geometry.

# Column split: we take the left 52% for English and right 52% for French
# to absorb column gutter width and any boundary text that straddles.
_COLUMN_LEFT_CUTOFF = 0.52
_COLUMN_RIGHT_CUTOFF = 0.48

# OCR-quality probe thresholds — used only when called on pre-1998 LAC
# scans (not reachable in v1 but stubbed for forward compatibility).
_OCR_WORD_RE = re.compile(r"[A-Za-z]{3,}")
_OCR_JUNK_RE = re.compile(r"[A-Za-z]{3,}[0-9]+[A-Za-z]{1,}|[^\s]{15,}")


@dataclass(frozen=True)
class GazettePage:
    """One page extracted into its two columns."""

    index: int
    width: float
    height: float
    text_en: str
    text_fr: str


@dataclass(frozen=True)
class GazetteExtraction:
    """Full-document extraction result, per-page."""

    pages: tuple[GazettePage, ...]
    ocr_confidence: float  # 0.0-1.0; 1.0 means "native digital text" (1998+)


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────


def extract_text_from_pdf(pdf_path: Union[str, Path, bytes]) -> GazetteExtraction:
    """Extract bilingual text columns from a Canada Gazette Part III PDF.

    ``pdf_path`` can be a filesystem path or raw bytes (for in-memory
    buffers passed by the HTTP fetcher). Repeat calls on the same bytes
    hit an LRU cache so we don't rasterise twice.

    Returns a :class:`GazetteExtraction` with one :class:`GazettePage` per
    source page, each carrying cleaned left-column (EN) and right-column
    (FR) text. Downstream code segments this stream by the "CHAPTER N"
    header in the left column.
    """
    if isinstance(pdf_path, bytes):
        key = hashlib.sha1(pdf_path, usedforsecurity=False).hexdigest()
        cached = _cache_get(key)
        if cached is not None:
            return cached

        import tempfile

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        try:
            tmp.write(pdf_path)
            tmp.close()
            result = _extract_uncached(Path(tmp.name))
        finally:
            try:
                Path(tmp.name).unlink()
            except OSError:
                pass
        _cache_put(key, result)
        return result

    return _extract_uncached(Path(pdf_path))


# ─────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────


def _cache_get(key: str) -> GazetteExtraction | None:
    if key in _EXTRACT_CACHE:
        _EXTRACT_CACHE.move_to_end(key)
        return _EXTRACT_CACHE[key]
    return None


def _cache_put(key: str, value: GazetteExtraction) -> None:
    _EXTRACT_CACHE[key] = value
    _EXTRACT_CACHE.move_to_end(key)
    while len(_EXTRACT_CACHE) > _EXTRACT_CACHE_SIZE:
        _EXTRACT_CACHE.popitem(last=False)


def _normalize(text: str) -> str:
    text = _INVISIBLE_RE.sub("", text)
    text = _CTRL_RE.sub("", text)
    return text


def _split_lines(text: str) -> list[str]:
    return re.split(r"\n|\r\n|\r| | ", text)


def _merge_hyphenated(lines: list[str]) -> list[str]:
    """Glue a line ending in a hyphen to the next line (hyphen removed).

    Canadian typesetters (like Greek) use ``-`` and the longer ``−``
    (U+2212) for word-break hyphens at column boundaries. The
    space-before-dash guard catches legitimate list separators (``2001, -
    c. 5``) that shouldn't glue.
    """
    merged: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        current = lines[i].strip()
        while current and current[-1] in _HYPHENS and len(current) > 1 and current[-2] != " ":
            nxt = lines[i + 1].strip() if i + 1 < n else ""
            current = current[:-1] + nxt
            i += 1
        merged.append(current)
        i += 1
    return merged


def _collect_repeated_headers(texts: list[str]) -> set[str]:
    """Return the set of lines that repeat at the top of multiple pages.

    The Gazette masthead ("Vol. 43, No. 1 / Canada Gazette / Part III /
    OTTAWA, …") reprints verbatim at the top of every continuation page —
    those we want to drop. But structural markers like "CHAPTER 1" also
    appear at the top of a page (the chapter cover) and we MUST keep them
    since the segmenter keys off them. So we only drop lines that appear
    at the top of at least two different pages.
    """
    from collections import Counter

    counter: Counter[str] = Counter()
    for page_text in texts[1:]:  # skip the title page
        for line in page_text.split("\n")[:3]:
            stripped = line.strip()
            if stripped and len(stripped) < 80:
                counter[stripped] += 1

    return {line for line, count in counter.items() if count >= 2}


def _clean_column_text(raw: str, repeated_headers: set[str]) -> str:
    """Normalize a single column's raw text: drop repeats, merge hyphens, collapse spaces."""
    lines = _split_lines(raw)
    # Drop repeated-header lines.
    kept = [line for line in lines if line.strip() not in repeated_headers]
    # Hyphen merge on the kept lines.
    merged = _merge_hyphenated(kept)
    text = "\n".join(merged)
    # Collapse runs of 2+ spaces to 1.
    text = re.sub(r"  +", " ", text)
    # Drop empty lines.
    text = "\n".join(line for line in text.splitlines() if line.strip())
    return text


def _ocr_confidence(text: str) -> float:
    """Rough heuristic for OCR quality: 1.0 = clean digital, 0.0 = garbled.

    Counts the fraction of 3+ letter words that don't match the typical
    OCR-junk pattern (letters+digits mixed, or suspiciously long tokens).
    Not a substitute for real dictionary-based confidence, but sufficient
    to gate "tag this commit as low-OCR-quality" downstream.
    """
    sample = text[:4000]
    words = _OCR_WORD_RE.findall(sample)
    if not words:
        return 1.0
    junk = sum(1 for w in words if _OCR_JUNK_RE.fullmatch(w))
    good = len(words) - junk
    return max(0.0, min(1.0, good / len(words)))


def _extract_uncached(path: Path) -> GazetteExtraction:
    pdf = pdfium.PdfDocument(str(path))
    try:
        raw_pages: list[tuple[str, str, float, float]] = []
        for page in pdf:
            w = page.get_width()
            h = page.get_height()
            tp = page.get_textpage()
            try:
                en = tp.get_text_bounded(left=0, right=w * _COLUMN_LEFT_CUTOFF, bottom=0, top=h)
                fr = tp.get_text_bounded(left=w * _COLUMN_RIGHT_CUTOFF, right=w, bottom=0, top=h)
            finally:
                tp.close()
                page.close()
            raw_pages.append((en or "", fr or "", w, h))
    finally:
        pdf.close()

    if not raw_pages:
        return GazetteExtraction(pages=tuple(), ocr_confidence=1.0)

    # Normalize unicode per column, then collect repeated headers.
    normalized: list[tuple[str, str, float, float]] = [
        (_normalize(en), _normalize(fr), w, h) for en, fr, w, h in raw_pages
    ]
    en_repeats = _collect_repeated_headers([p[0] for p in normalized])
    fr_repeats = _collect_repeated_headers([p[1] for p in normalized])

    pages: list[GazettePage] = []
    for i, (en, fr, w, h) in enumerate(normalized):
        pages.append(
            GazettePage(
                index=i,
                width=w,
                height=h,
                text_en=_clean_column_text(en, en_repeats),
                text_fr=_clean_column_text(fr, fr_repeats),
            )
        )

    # Quality probe on the English column (has more text, more reliable
    # confidence signal than French which shares the same printing).
    all_en = "\n".join(p.text_en for p in pages[1:4])  # skip title page
    confidence = _ocr_confidence(all_en)

    del raw_pages, normalized
    gc.collect()

    return GazetteExtraction(pages=tuple(pages), ocr_confidence=confidence)
