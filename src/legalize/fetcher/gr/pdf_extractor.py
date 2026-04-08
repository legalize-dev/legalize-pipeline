"""PDF text extraction for Greek Government Gazette (ΦΕΚ) Issue A' documents.

Three-stage pipeline:

  1. Layout-aware text extraction with **pypdfium2** (BSD-3-Clause). Greek FEK
     issues use a 2-column body with a centered masthead; pdfplumber's default
     line-by-line extractor interleaves columns, while PDFium reads them in
     natural order.

  2. **Table detection with pdfplumber** (MIT). Greek tax codes, tariff laws,
     and salary scales contain inline tables (income brackets, depreciation
     schedules, fees) that pypdfium2 flattens into space-separated text. We
     run pdfplumber's ``find_tables()`` per page to detect them and emit
     each as a Markdown pipe table via the ``GR_TABLE_OPEN``/``GR_TABLE_CLOSE``
     sentinel. The parser layer converts the sentinel into
     ``Paragraph(css_class="table_row", ...)`` which the engine renderer
     already knows how to handle (mirrors Andorra and Latvia).

  3. Text cleanup adapted from Lampros Kafidas's reference implementation
     ``fekpdf2text_2024.py`` (Harvard Dataverse, doi:10.7910/DVN/F1CNFC, MIT
     License). The cleanup logic is the canonical solution for FEK A' issues
     and we want to stay byte-compatible with the 415 ground-truth ``.txt``
     files in his dataset (Greek laws Ν. 4765–5134, years 2021–2024).

Algorithm credit:
    Lampros Kafidas, "Greek Laws in text format", Harvard Dataverse V2,
    doi:10.7910/DVN/F1CNFC, 2024 — MIT License.

The cleanup steps, in order:

* **First-page header strip** — between the masthead line ("ΕΦΗΜΕΡΙΔΑ" /
  "ΕΦΗΜΕΡΙ∆Α" / "Digitally") and the first occurrence of "ΝΟΜΟΣ" / "ΝΟΜOΣ"
  / "Verified" / line index 11, we drop the gazette boilerplate so the
  output starts at the actual law text.
* **Repeated header strip** — for pages 2..N we collect the first 3 lines
  of each page into a set, then on a second pass we drop any line that
  matches an entry in that set. This catches the page-number + masthead
  repetition that appears verbatim on every continuation page.
* **Hyphen-merge** — when a line ends with ``-`` or ``−`` (U+2212, the
  longer minus sign Greek typesetters use for line-end breaks) and the
  preceding character is not a space, we glue it to the next line. This
  un-breaks words split across line boundaries.
* **"Verified" cleanup** — drop any line that begins with "Verified" (the
  digital-signature footer added by the National Printing House).
* **Whitespace normalization** — collapse runs of two spaces into one.
* **Last-page trim** — drop the first 3 lines (page header) and last 4
  lines (postal address footer) of the last page only when the 4th line
  is real content (not a separator like ``*...*`` or starting with
  "Ταχυδρομική").
* **Blank-line removal** — drop empty lines from the final output.

The function returns three values for diagnostic parity with Kafidas's
script:

    text          — the cleaned body text
    clipped_text  — everything we removed (for debugging)
    last_page     — the raw last page (for debugging)
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import OrderedDict
from pathlib import Path
from typing import Union

import pdfplumber
import pypdfium2 as pdfium

logger = logging.getLogger(__name__)

# Small LRU cache for ``extract_text_from_pdf`` keyed on a SHA-1 of the
# input bytes. The pipeline typically calls ``parse_text`` and ``parse``
# (metadata) back-to-back on the same PDF, and pytest reorders tests so
# the same fixture may be re-requested several times — both cases benefit
# from caching. We cap at 16 entries (≈ 16-32 MB of text + tables) so the
# memory footprint stays bounded during long bootstraps.
_EXTRACT_CACHE_SIZE = 16
_EXTRACT_CACHE: OrderedDict[str, tuple[str, str, str]] = OrderedDict()


def _bytes_key(data: bytes) -> str:
    return hashlib.sha1(data, usedforsecurity=False).hexdigest()


def _cache_get(key: str) -> tuple[str, str, str] | None:
    if key in _EXTRACT_CACHE:
        _EXTRACT_CACHE.move_to_end(key)
        return _EXTRACT_CACHE[key]
    return None


def _cache_put(key: str, value: tuple[str, str, str]) -> None:
    _EXTRACT_CACHE[key] = value
    _EXTRACT_CACHE.move_to_end(key)
    while len(_EXTRACT_CACHE) > _EXTRACT_CACHE_SIZE:
        _EXTRACT_CACHE.popitem(last=False)


# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

# Standard A4 portrait dimensions in PDF points (72 dpi)
_A4_WIDTH = 595
_A4_HEIGHT = 842
_A4_TOLERANCE = 2  # points

# Hyphenation characters used by Greek typesetters at line breaks
_HYPHENS = ("-", "\u2212")  # ASCII hyphen + U+2212 MINUS SIGN

# Markers that delimit the gazette masthead block on the first page
_HEADER_START_MARKERS = ("ΕΦΗΜΕΡΙΔΑ", "ΕΦΗΜΕΡΙ∆Α", "Digitally")
_HEADER_END_MARKERS = ("Verified", "NOMOΣ", "ΝΟΜΟΣ")
# Hard cap on first-page header lines as a fallback if no end marker is found
_HEADER_MAX_LINES = 11

# Last-page postal address footer signature
_LAST_PAGE_FOOTER_PREFIX = "Ταχυδρομική"

# Sentinels used to mark a Markdown table block embedded inside the cleaned
# text stream. The parser layer (``parser.py``) splits the text on these
# sentinels and emits any block between them as a single
# ``Paragraph(css_class="table_row", text=<md table>)``.
GR_TABLE_OPEN = "\n<<<GR_TABLE>>>\n"
GR_TABLE_CLOSE = "\n<<</GR_TABLE>>>\n"

# Tables with fewer rows or columns than this are usually layout artifacts
# (two-line headers, decorative dividers) rather than real data tables. We
# drop them to avoid noise in the output.
_MIN_TABLE_ROWS = 2
_MIN_TABLE_COLS = 2

# C0/C1 control characters that must never appear in legislative text.
# Mirrors fetcher/lv/parser.py to keep encoding hygiene consistent.
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Soft hyphen (U+00AD) and PDFium's stand-in (U+FFFE) appear mid-word when
# the original PDF used a soft-hyphen as a hyphenation hint. They are not
# hyphenation markers we should preserve — they should disappear so the
# word reads cleanly. U+FFFD (REPLACEMENT CHARACTER) is also stripped
# defensively (it's always an encoding error).
_INVISIBLE_RE = re.compile("[\u00ad\ufffe\ufffd]")

# Mojibake detection thresholds. Pre-2005 Greek FEK PDFs commonly use a
# Windows-1253 (Greek codepage) custom CMap that pypdfium2 cannot decode
# via Unicode — instead it returns each glyph code as a Latin-1
# Supplement codepoint (U+0080-U+00FF). The result looks like
# "ÅÖÇÌÅÑÉÓ" instead of "ΕΦΗΜΕΡΙΣ". We detect this by counting Latin-1
# Supplement chars vs proper Greek codepoints in the first ~2000 chars,
# and recover the original by ``encode("latin-1").decode("windows-1253")``.
# The thresholds err on the safe side: we only flag if the Greek count
# is essentially zero AND the Latin-1 count is significant.
_MOJIBAKE_SAMPLE_SIZE = 2000
_MOJIBAKE_MIN_LATIN1 = 50  # at least this many U+0080-U+00FF chars
_MOJIBAKE_MAX_GREEK = 5  # if more than this many proper Greek chars exist, NOT mojibake


# ─────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────


def _normalize_unicode(text: str) -> str:
    """Strip control chars and invisible/error characters from extracted text.

    Run *before* line splitting and hyphen merging so the rest of the
    pipeline operates on clean codepoints.
    """
    text = _INVISIBLE_RE.sub("", text)
    text = _CTRL_RE.sub("", text)
    return text


def _looks_like_win1253_mojibake(text: str) -> bool:
    """Detect Windows-1253 → Latin-1 mojibake in extracted Greek text.

    Pre-2005 Greek FEK PDFs use a custom font CMap that pypdfium2 can't
    convert to Unicode; the bytes come out as Latin-1 codepoints. The
    visual cue is text full of "ÅÖÇÌÅÑÉÓ"-style sequences with no proper
    Greek characters at all.
    """
    sample = text[:_MOJIBAKE_SAMPLE_SIZE]
    n_latin1 = sum(1 for c in sample if 0x0080 <= ord(c) <= 0x00FF)
    n_greek = sum(1 for c in sample if 0x0370 <= ord(c) <= 0x03FF)
    return n_latin1 >= _MOJIBAKE_MIN_LATIN1 and n_greek <= _MOJIBAKE_MAX_GREEK


def _recover_win1253(text: str) -> str:
    """Apply the Latin-1 → Windows-1253 round-trip to recover Greek.

    The PDF originally encoded each glyph as a Windows-1253 byte; pdfium
    interpreted those bytes as Latin-1 codepoints. We undo the wrong
    decoding by re-encoding to Latin-1 (which is reversible because
    Latin-1 covers U+0000-U+00FF exactly) and then decoding as
    Windows-1253. Codepoints outside U+0000-U+00FF (which shouldn't
    appear in genuine mojibake) are passed through verbatim — the
    ``replace`` error handler protects us if they do.
    """
    try:
        return text.encode("latin-1", errors="replace").decode("windows-1253", errors="replace")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text


def _split_lines(text: str) -> list[str]:
    """Split on every kind of line terminator we have seen in FEK PDFs."""
    return re.split(r"\n|\r\n|\r|\u2028|\u2029", text)


def _merge_hyphenated(lines: list[str]) -> list[str]:
    """Glue lines that end with a hyphen-without-preceding-space to the next line.

    Greek typesetters use ``-`` and the longer ``−`` (U+2212). The space
    test catches the legitimate case "ν. 4046/2012, " where the dash is
    a list separator, not a hyphenation marker.
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


def _strip_blank_lines(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if line.strip())


def _table_to_markdown(rows: list[list[str | None]]) -> str:
    """Convert a pdfplumber-extracted table (list of rows) to a Markdown pipe table.

    pdfplumber returns ``None`` for empty cells and may insert literal
    newlines inside cells (for multi-line headers like "Φορολογικός\\n
    συντελεστής"). We collapse cell whitespace, escape any literal pipe
    characters, and pad rows to a uniform column count.
    """
    if not rows or not rows[0]:
        return ""

    cleaned: list[list[str]] = []
    for row in rows:
        out_row: list[str] = []
        for cell in row:
            if cell is None:
                out_row.append("")
                continue
            text = _normalize_unicode(cell)
            text = re.sub(r"\s+", " ", text).strip()
            text = text.replace("|", "\\|")
            out_row.append(text)
        cleaned.append(out_row)

    if not cleaned:
        return ""

    # Drop trailing empty rows (pdfplumber sometimes adds them)
    while cleaned and not any(c for c in cleaned[-1]):
        cleaned.pop()
    if not cleaned:
        return ""

    max_cols = max(len(r) for r in cleaned)
    if max_cols < _MIN_TABLE_COLS or len(cleaned) < _MIN_TABLE_ROWS:
        return ""

    for r in cleaned:
        while len(r) < max_cols:
            r.append("")

    lines: list[str] = []
    lines.append("| " + " | ".join(cleaned[0]) + " |")
    lines.append("| " + " | ".join("---" for _ in range(max_cols)) + " |")
    for row in cleaned[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _extract_page_tables(pdf_path: Path) -> dict[int, list[str]]:
    """Use pdfplumber to detect tables on every page.

    Returns a dict mapping page index (0-based) to a list of Markdown
    pipe table strings. Pages with no detected tables are absent from
    the dict (NOT mapped to an empty list — callers should use
    ``.get(idx, [])`` defensively).

    pdfplumber's default table-finding heuristic uses ruling lines, which
    works well on Greek FEK A' tax tables (they almost always have visible
    borders). For tables without borders we'd need a custom detection
    strategy — out of scope for v1.
    """
    out: dict[int, list[str]] = {}
    try:
        with pdfplumber.open(str(pdf_path)) as plumb:
            for i, page in enumerate(plumb.pages):
                try:
                    raw_tables = page.find_tables()
                except Exception as exc:  # noqa: BLE001 — table detection is best-effort
                    logger.debug("pdfplumber.find_tables failed on page %d: %s", i, exc)
                    continue
                md_tables: list[str] = []
                for t in raw_tables:
                    try:
                        rows = t.extract()
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("pdfplumber table.extract failed on page %d: %s", i, exc)
                        continue
                    md = _table_to_markdown(rows)
                    if md:
                        md_tables.append(md)
                if md_tables:
                    out[i] = md_tables
    except Exception as exc:  # noqa: BLE001 — never crash the extractor on table errors
        logger.warning("pdfplumber failed to open %s: %s", pdf_path, exc)
    return out


def _read_pages(pdf_path: Path) -> list[tuple[str, float, float]]:
    """Return a list of ``(page_text, width, height)`` for every page.

    Page text is Unicode-normalized at the boundary so callers never see
    control characters or PDFium's soft-hyphen stand-in (U+FFFE). When
    pre-2005 Greek PDFs come back as Windows-1253 mojibake, we apply a
    Latin-1 → Windows-1253 round-trip on every page to recover proper
    Greek.

    The mojibake check is per-document (sampled from page 1) — if the
    first page is mojibake'd, every page in the same PDF is. Per-page
    re-checking would just waste cycles.
    """
    out: list[tuple[str, float, float]] = []
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        # Pull all pages first so we can sample the first one for mojibake
        raw_pages: list[tuple[str, float, float]] = []
        for page in pdf:
            text = page.get_textpage().get_text_range()
            raw_pages.append((text, page.get_width(), page.get_height()))
    finally:
        pdf.close()

    if not raw_pages:
        return []

    # Sample the first page (or the first non-empty one) to decide
    needs_recovery = False
    for text, _, _ in raw_pages:
        if text and text.strip():
            if _looks_like_win1253_mojibake(text):
                needs_recovery = True
                logger.info(
                    "%s: Win-1253 mojibake detected, applying recovery",
                    pdf_path.name,
                )
            break

    for text, w, h in raw_pages:
        if needs_recovery:
            text = _recover_win1253(text)
        text = _normalize_unicode(text)
        out.append((text, w, h))
    return out


def _is_a4(width: float, height: float) -> bool:
    return abs(width - _A4_WIDTH) <= _A4_TOLERANCE and abs(height - _A4_HEIGHT) <= _A4_TOLERANCE


def _strip_first_page_header(lines: list[str]) -> tuple[list[str], list[str]]:
    """Drop the gazette masthead from the first page.

    Returns ``(kept_lines, clipped_lines)``.
    """
    kept: list[str] = []
    clipped: list[str] = []
    inside_header = False
    line_count = 0

    for line in lines:
        if any(m in line for m in _HEADER_START_MARKERS):
            inside_header = True
        if any(m in line for m in _HEADER_END_MARKERS) or line_count == _HEADER_MAX_LINES:
            inside_header = False

        if inside_header:
            clipped.append(line)
        else:
            kept.append(line)
        line_count += 1

    return kept, clipped


def _collect_repeated_headers(pages: list[tuple[str, float, float]]) -> set[str]:
    """Collect the first 3 lines of pages 2..N as candidate repeated headers.

    These typically include the page number and the gazette masthead which
    repeat verbatim on every continuation page.
    """
    headers: set[str] = set()
    for page_text, _, _ in pages[1:]:  # skip the first page
        for line in page_text.split("\n")[:3]:
            stripped = line.strip()
            if stripped:
                headers.add(stripped)
    return headers


def _process_continuation_page(
    page_text: str,
    repeated_headers: set[str],
) -> tuple[str, str]:
    """Strip repeated headers + 'Verified' lines from a continuation page.

    Returns ``(kept_text, clipped_text)``.
    """
    lines = _split_lines(page_text)
    kept = [line for line in lines if line.strip() not in repeated_headers]
    clipped = [line for line in lines if line.strip() in repeated_headers]

    # Drop "Verified" lines (digital signature footer)
    kept_no_verified: list[str] = []
    for line in kept:
        if line.strip().startswith("Verified"):
            clipped.append(line.strip())
        else:
            kept_no_verified.append(line)

    text = "\n".join(_merge_hyphenated(kept_no_verified))
    text = re.sub(r"  +", " ", text)
    return text, "\n".join(clipped)


def _process_last_page(
    page_text: str,
) -> tuple[str, list[str]]:
    """Trim postal address boilerplate from the last page.

    The official footer pattern is: 3 header lines, body content,
    4 trailing footer lines (postal address). We only trim if the 4th
    line is recognisably real content — defensive against laws whose
    last page is *all* footer (e.g. one-paragraph corrigenda).

    Returns ``(kept_text, clipped_lines)``.
    """
    lines = page_text.splitlines()
    if len(lines) < 4:
        return "", []

    fourth = lines[3].strip()
    looks_like_separator = fourth.startswith("*") and fourth.endswith("*")
    looks_like_footer_start = fourth.startswith(_LAST_PAGE_FOOTER_PREFIX)

    if looks_like_separator or looks_like_footer_start:
        # Pure boilerplate — drop the whole last page
        return "", lines

    body = "\n".join(lines[3:-4]) if len(lines) > 7 else ""
    clipped = lines[0:3] + (lines[-4:] if len(lines) > 7 else [])
    return body, clipped


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────


def extract_text_from_pdf(
    pdf_path: Union[str, Path, bytes],
) -> tuple[str, str, str]:
    """Extract clean Greek body text from a ΦΕΚ Issue A' PDF.

    Accepts either a path-like (file on disk) or raw bytes (in-memory
    buffer). When called twice with the same bytes (e.g. parser then
    metadata parser on the same document) the second call returns
    a cached result instead of redoing pdfplumber table detection.

    Returns:
        ``(text, clipped_text, last_page_raw)``

        * ``text`` — the cleaned body text suitable for parsing
        * ``clipped_text`` — everything that was stripped, for debugging
        * ``last_page_raw`` — raw last-page text, for debugging
    """
    if isinstance(pdf_path, bytes):
        key = _bytes_key(pdf_path)
        cached = _cache_get(key)
        if cached is not None:
            return cached
        # Materialise to a temp file so pdfplumber + pypdfium2 can both
        # open it as a path. Both libraries can read from BytesIO too
        # but the path interface is more reliable on macOS.
        import tempfile

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        try:
            tmp.write(pdf_path)
            tmp.close()
            result = _extract_text_uncached(Path(tmp.name))
        finally:
            try:
                Path(tmp.name).unlink()
            except OSError:
                pass
        _cache_put(key, result)
        return result

    path = Path(pdf_path)
    return _extract_text_uncached(path)


def _extract_text_uncached(path: Path) -> tuple[str, str, str]:
    pages = _read_pages(path)
    if not pages:
        return "", "", ""

    # Sanity check page geometry — non-A4 pages signal a non-standard issue
    # (e.g. landscape annexes, certain old scanned documents). We don't
    # raise; we just collect the warning so the caller can decide.
    for i, (_, w, h) in enumerate(pages):
        if not _is_a4(w, h):
            # Quietly noted; the caller can re-run with logging on if needed.
            pass

    repeated_headers = _collect_repeated_headers(pages)
    page_tables = _extract_page_tables(path)

    body_parts: list[str] = []
    clipped_parts: list[str] = []
    last_page_raw = ""

    def _append_page_tables(idx: int) -> None:
        """Append any tables detected on page ``idx`` to body_parts.

        Each table is wrapped in the GR_TABLE sentinel pair so the parser
        layer can detect it and emit a single ``Paragraph(css_class=
        "table_row", ...)``. Tables are appended at the END of the page's
        text, which is approximate but acceptable for v1 — Greek tax
        tables almost always follow an introducing line like
        "σύμφωνα με την ακόλουθη κλίμακα:".
        """
        for md_table in page_tables.get(idx, []):
            body_parts.append(GR_TABLE_OPEN + md_table + GR_TABLE_CLOSE)

    n_pages = len(pages)
    # Process pages 0..n-2 (we handle the last page separately for footer trim)
    for i in range(n_pages - 1):
        page_text, _, _ = pages[i]

        if i == 0:
            kept, clipped = _strip_first_page_header(_split_lines(page_text))
            kept_text = "\n".join(kept)
            clipped_parts.append("\n".join(clipped))
        else:
            kept_text, clipped = _process_continuation_page(page_text, repeated_headers)
            clipped_parts.append(clipped)

        # Hyphen merge + space normalize again on the merged result
        merged = _merge_hyphenated(kept_text.split("\n"))
        merged_text = "\n".join(merged)
        merged_text = re.sub(r"^Verified.*$", "", merged_text, flags=re.MULTILINE)
        merged_text = re.sub(r"  +", " ", merged_text)

        body_parts.append(merged_text)
        _append_page_tables(i)

    # Last page
    if n_pages > 1:
        last_page_raw, _, _ = pages[-1]
        kept_text, clipped = _process_last_page(last_page_raw)
        if kept_text:
            merged = _merge_hyphenated(kept_text.split("\n"))
            kept_text = re.sub(r"  +", " ", "\n".join(merged))
            body_parts.append(kept_text)
        clipped_parts.append("\n".join(clipped))
        _append_page_tables(n_pages - 1)
    elif n_pages == 1:
        # Single-page document — first-page processing already covers it
        last_page_raw = pages[0][0]
        _append_page_tables(0)

    # Strip blank lines but preserve the table sentinels intact
    raw = "\n".join(body_parts)
    full_text = _strip_blank_lines_preserving_tables(raw)
    clipped_text = "\n".join(part for part in clipped_parts if part)
    return full_text, clipped_text, last_page_raw


def _strip_blank_lines_preserving_tables(text: str) -> str:
    """Like ``_strip_blank_lines`` but never touches GR_TABLE blocks.

    A naive line-by-line filter would corrupt the multi-line Markdown
    pipe tables emitted between ``GR_TABLE_OPEN`` and ``GR_TABLE_CLOSE``
    (their separator row ``| --- | --- |`` does have content but the
    surrounding blank-line collapse can break visual parsing). We split
    on the open sentinel, strip blanks in the non-table chunks, and
    re-join.
    """
    open_marker = GR_TABLE_OPEN.strip("\n")
    close_marker = GR_TABLE_CLOSE.strip("\n")
    parts = re.split(
        f"({re.escape(open_marker)}.*?{re.escape(close_marker)})", text, flags=re.DOTALL
    )
    out: list[str] = []
    for part in parts:
        if part.startswith(open_marker):
            out.append(part)
        else:
            out.append(_strip_blank_lines(part))
    return "\n".join(p for p in out if p)
