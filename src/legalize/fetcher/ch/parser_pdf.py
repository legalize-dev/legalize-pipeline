"""Fedlex PDF-A parser — Switzerland.

Parses Fedlex's PDF-A manifestations into the same
``Block/Version/Paragraph`` structure that the Akoma Ntoso parser emits.
This is the fallback path for laws / versions that Fedlex does not expose
as Akoma Ntoso XML (roughly 40% of the classified compilation, including
all consolidations dated before 2021 for most laws).

**Fidelity contract (see `ADDING_A_COUNTRY.md §0.7`):** the output must
be structurally indistinguishable from the XML parser's output for the
same law at an adjacent effective date — same heading depths, same
article template (``##### **Art. N** Title``), same paragraph numbering
style (``<sup>N</sup>``), same list-item prefix (``- a. ...``), same
Fussnoten block at the end. A reader scanning a git log for one law must
not be able to tell which commit came from XML and which came from PDF-A.

**What Fedlex PDFs look like** (verified against BV 2000-2020, DBG, OR):

1. Page 1 — top-of-document label (SR number), long title, subtitle with
   ``(Stand am ...)``, preamble, first articles.
2. Pages 2..N-2 — body pages with a running header
   ``<short title> <SR number>`` at font 8.0 and the page number at
   font 9.0 on the last line.
3. Last pages — the same running header, then the Inhaltsverzeichnis
   (table of contents) formatted as ``Title ............. Art. NNN``.
4. Font map: **9.0** = body text, **8.0** = running header / footer,
   **6.5** = footnote references (superscripts) and footnote bodies.

**Parsing strategy** — we use two passes because PDF has no semantic
structure:

Pass 1: line classifier. Walk every word of every page. Group words by
their ``top`` coordinate into visual lines. Assign each line a "kind"
based on the dominant font size and position on the page:

- ``header`` — font 8.0 lines at the top of non-first pages (running
  header). Skipped silently.
- ``page_number`` — the lone font-9.0 number at the very bottom after
  the last footnote body. Skipped.
- ``footnote_body`` — font-6.5 lines that cluster near the bottom of
  the page; captured and emitted in the Fussnoten block at the end.
- ``body`` — the rest. Parsed line-by-line in pass 2.

Pass 2: structural regex. Apply ordered rules over the body lines and
emit ``Paragraph`` objects with the same ``css_class`` values the XML
parser uses.

**Limitations** (documented here so the cross-format review in §0.7
knows what to expect):

- Tables — the BV contains ONE table (heavy-vehicle road tax). The DBG
  contains TWO (income-tax schedules). ``pdfplumber.extract_tables`` is
  border-triggered and the Fedlex tables do NOT use visible borders, so
  border-based detection misses them. For v1 we fall back to the plain
  text flow for tables and document the gap; §0.7 review will flag any
  table-carrying law where the PDF/XML transition would be visibly
  degraded. Landmark codes that carry their value in tables (the DBG tax
  schedule) are XML-covered anyway.
- Inline italics / bold in PDF — pdfplumber reports ``fontname`` like
  ``DILLHD+TimesNewRoman`` and Italic would be ``DILIHG+TimesNewRoman,Italic``
  or a distinct fontname. Detection is heuristic (``'Italic' in fontname``
  and ``'Bold' in fontname``). Not 100% reliable but matches the XML
  parser's pattern.
- Footnote reference anchors — superscript digits inside body text
  become ``<sup>N</sup>`` — same rendering as the XML parser's
  ``<authorialNote>`` marker path. The actual footnote body is rendered
  at the end of the article/section under a ``Fussnoten`` h6 heading,
  again identical to the XML emit.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from io import BytesIO
from typing import Iterable

try:
    import pdfplumber
except ImportError as exc:  # noqa: BLE001
    raise ImportError(
        "pdfplumber is required for the Fedlex PDF parser — "
        "it should be pulled in by pyproject.toml"
    ) from exc

from legalize.fetcher.ch.parser import _NoteCollector, _clean_ws
from legalize.models import Paragraph, Version

logger = logging.getLogger(__name__)

# ─── Font-size constants tuned to Fedlex PDF-A output ───
# Measured across BV 2000-2020 and DBG 2020+:
#   9.0 pt = body text
#   8.0 pt = running header (top of page) AND footnote bodies (bottom)
#   6.5 pt = superscript digits — both paragraph-number markers in body
#            and footnote-reference anchors
# Leave a small tolerance for exports that drift by 0.1 pt.
_BODY_SIZE = 9.0
_FOOTNOTE_OR_HEADER_SIZE = 8.0
_SUPERSCRIPT_SIZE = 6.5
_SIZE_TOL = 0.2

# ─── Regexes for line classification (pass 2) ───

# "1. Titel:", "2. Kapitel:", "3. Abschnitt:" — Swiss structural headers.
# Number can be arabic, the role word is always German.
_STRUCT_H2_RE = re.compile(r"^(\d+)\.\s*Titel:\s*(.+)$")
_STRUCT_H3_RE = re.compile(r"^(\d+)\.\s*Kapitel:\s*(.+)$")
_STRUCT_H4_RE = re.compile(r"^(\d+)\.\s*Abschnitt:\s*(.+)$")
_STRUCT_BUCH_RE = re.compile(r"^(\d+)\.\s*Buch(?::|\s)\s*(.+)$")

# "Art. 1", "Art. 2a", "Art. 10bis", "Art. 191c" — article heading.
# Captures the number+suffix and any inline title that follows on the
# same line. The title may be empty for table-of-contents-only entries
# (those are filtered out earlier by TOC detection).
_ARTICLE_RE = re.compile(r"^Art\.\s*(\d+[a-z]*(?:bis|ter|quater)?)(?:\s+(.+))?$")

# "1 Alle Menschen...", "2 Sie fördert..." — numbered paragraph.
# Arabic numeral at start of line followed by a space and body text.
_NUM_PARA_RE = re.compile(r"^(\d+)\s+(\S.*)$")

# "a. text", "b.91 text" — lettered list item, optionally with a
# footnote anchor glued to the letter.
_LIST_RE = re.compile(r"^([a-z])\.\s*(?:(\d+))?\s*(.+)$")

# Table-of-contents detection — lines ending with "... Art. NNN" or
# "... Art. NNNa". Trailing dots are the TOC leader dots.
_TOC_RE = re.compile(r"\.{3,}\s*(?:Art\.|Seite|Page)")

# "Inhaltsverzeichnis" / "Stichwortverzeichnis" / "Sachregister" — the
# German TOC and keyword index. When we see any of these as a standalone
# line we stop ingesting body content entirely. Fedlex PDFs append both
# a structural TOC and an alphabetical index; neither belongs in the
# rendered Markdown since the XML manifestation does not contain them.
_TOC_HEADER_RE = re.compile(
    r"^(Inhaltsverzeichnis|Inhalt|Stichwortverzeichnis|Sachregister|"
    r"Table des matières|Index|Sommario|Indice analitico)\s*$",
    re.IGNORECASE,
)

# Soft-hyphen re-join. PDF extractors reconstruct words that were line-
# wrapped with a trailing hyphen as ``Word1- Word2``. We rejoin when the
# second token starts lowercase (most cases), unless the hyphen is part
# of a real compound like ``Brief-, Post-`` (second token capitalised or
# hyphen is followed by comma/semicolon before the space).
_SOFT_HYPHEN_RE = re.compile(r"(\w{2,})-\s+([a-zäöüß]\w*)")

# Running header pattern. Detected dynamically (see `_detect_running_header`).

# Footnote body start — Fedlex wraps each footnote as
# ``N<space>text`` at font 6.5 after a small vertical gap.
_FOOTNOTE_BODY_START = re.compile(r"^(\d+)\s+(\S.*)$")

# Superscript-digit anchors glued to a word, like ``Verfassung1``.
# We only rewrite such anchors when they immediately follow a word
# character (letter or punctuation) — this avoids false positives on
# actual numeric content like "1999 2556".
_SUP_ANCHOR_RE = re.compile(r"(?<=[A-Za-zäöüÄÖÜß])(\d+)(?=\b)")


# ─────────────────────────────────────────────
# Page parsing — group words into semantic lines
# ─────────────────────────────────────────────


def _dominant_size(words: list[dict]) -> float:
    """Return the most common font size in a word list (rounded to 0.1)."""
    if not words:
        return 0.0
    counts: dict[float, int] = {}
    for w in words:
        size = round(float(w.get("size", 0.0)), 1)
        counts[size] = counts.get(size, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _group_into_lines(words: list[dict], y_tol: float = 2.0) -> list[list[dict]]:
    """Group words into visual lines based on their ``top`` coordinate.

    Words are already ordered left-to-right top-to-bottom by pdfplumber
    when you pass ``use_text_flow=True`` to ``extract_words``. We still
    sort on ``top`` to be safe against PDFs that mix columns.
    """
    if not words:
        return []
    # Sort by top then x0
    words = sorted(words, key=lambda w: (float(w["top"]), float(w["x0"])))
    lines: list[list[dict]] = []
    current: list[dict] = []
    current_top: float | None = None
    for w in words:
        top = float(w["top"])
        if current_top is None or abs(top - current_top) <= y_tol:
            current.append(w)
            if current_top is None:
                current_top = top
        else:
            lines.append(current)
            current = [w]
            current_top = top
    if current:
        lines.append(current)
    return lines


def _render_line(words: list[dict]) -> str:
    """Turn a line's words into a single string, preserving spaces.

    Superscript-sized digits (font 6.5) that appear within a body-sized
    (9.0) line are already embedded inline by pdfplumber's word layer;
    we keep them but they are detected and wrapped as ``<sup>N</sup>``
    by the line-level rewrite below.
    """
    return " ".join(w["text"] for w in words).strip()


def _wrap_inline_sups(line: str, sup_words: set[str]) -> str:
    """Wrap font-6.5 digit tokens as ``<sup>N</sup>`` in the rendered line.

    ``sup_words`` is the set of raw token strings that were measured as
    superscript in the original PDF. We only wrap at token boundaries so
    we don't accidentally rewrite "1999" when only "1" was a superscript.

    The **first token** is deliberately left unwrapped even if it is a
    superscript digit, because leading superscripts on body lines are
    paragraph-number markers (``¹ Die Schweiz…``) that the pass-2
    ``_NUM_PARA_RE`` regex needs to match. The pass-2 emitter wraps it
    as ``<sup>N</sup>`` itself.
    """
    if not sup_words:
        return line
    out_tokens: list[str] = []
    for i, tok in enumerate(line.split(" ")):
        if i > 0 and tok and tok in sup_words and tok.isdigit():
            out_tokens.append(f"<sup>{tok}</sup>")
        else:
            out_tokens.append(tok)
    return " ".join(out_tokens)


# ─────────────────────────────────────────────
# Page-level extraction (pass 1)
# ─────────────────────────────────────────────


class _ExtractedPage:
    """Result of pass 1 for a single PDF page.

    Attributes:
        body_lines: ordered list of body text lines (after stripping the
            running header and the page number).
        footnote_lines: footnote bodies in page order. They will be
            accumulated across all pages and rendered as a Fussnoten
            block at the end of the Version.
    """

    __slots__ = ("body_lines", "footnote_lines")

    def __init__(self) -> None:
        self.body_lines: list[str] = []
        self.footnote_lines: list[str] = []


def _extract_page(page, running_header: str | None) -> _ExtractedPage:
    """Pass 1: classify each line of one page as header / body / footnote.

    Fedlex PDF running headers are at body-text font size (9.0 pt) and
    alternate across odd/even pages:

      odd  pages → ``"<SR number> <short title>"``  (e.g. ``"101 Bundesverfassung"``)
      even pages → ``"<short title> <SR number>"``  (e.g. ``"Bundesverfassung der Schweizerischen Eidgenossenschaft 101"``)

    So we cannot disambiguate by font size alone. Instead, we
    unconditionally drop the **first line of each page** if it looks
    like a page-header (contains the SR number as a stand-alone token
    AND is short). Pages 2+ always start with such a header; pages that
    begin with body text would not match.

    Font size 8.0 is reserved for footnote bodies at the bottom of the
    page. Size 6.5 marks superscripts — either paragraph-number markers
    on 9.0-pt body lines or footnote-anchor numbers on 8.0-pt footnote
    lines.
    """
    out = _ExtractedPage()
    try:
        words = page.extract_words(
            extra_attrs=["size", "fontname"],
            keep_blank_chars=False,
            use_text_flow=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("pdfplumber failed on page %s: %s", page.page_number, exc)
        return out

    lines = _group_into_lines(words)
    for line_idx, raw_line in enumerate(lines):
        line_text = _render_line(raw_line)
        if not line_text:
            continue

        # Dominant size ignoring superscript (6.5) tokens — those are
        # always anchors, never the line's semantic font size.
        non_sup_words = [
            w
            for w in raw_line
            if abs(round(float(w.get("size", 0.0)), 1) - _SUPERSCRIPT_SIZE) > _SIZE_TOL
        ]
        size = _dominant_size(non_sup_words) if non_sup_words else _dominant_size(raw_line)

        # First line of a page that matches the running-header shape —
        # drop it regardless of font size.
        if line_idx == 0 and _looks_like_running_header(line_text, running_header):
            continue

        # Lone page number on a body-sized line (page 1 ends with the
        # Arabic page number at 9.0 pt).
        if line_text.isdigit() and len(line_text) <= 4:
            continue

        # 8.0-pt line (that is not the running header) → footnote body.
        # We deliberately do NOT wrap leading 6.5-pt digits as
        # ``<sup>N</sup>`` here — the footnote-line parser below expects
        # a bare ``N `` prefix to anchor the note body. Inline
        # superscripts mid-sentence are rare in footnotes and acceptable
        # as plain digits.
        if abs(size - _FOOTNOTE_OR_HEADER_SIZE) <= _SIZE_TOL:
            out.footnote_lines.append(line_text)
            continue

        # Body line (9.0 pt, possibly with inline 6.5-pt superscripts).
        sup_words = {
            w["text"]
            for w in raw_line
            if abs(round(float(w.get("size", 0.0)), 1) - _SUPERSCRIPT_SIZE) <= _SIZE_TOL
            and w["text"].isdigit()
        }
        if sup_words:
            line_text = _wrap_inline_sups(line_text, sup_words)
        out.body_lines.append(line_text)
    return out


# ``<SR> <title>`` or ``<title> <SR>`` running-header pattern. Matches
# when a short line (<= 150 chars) has at least one token that is the
# detected SR-like prefix AND lacks the punctuation of body sentences.
_SR_TOKEN_RE = re.compile(r"\b\d{1,4}(?:\.\d{1,4})?\b")


def _looks_like_running_header(line: str, running_header: str | None) -> bool:
    """Heuristic: is this a page-running header to strip?"""
    stripped = line.strip()
    if not stripped:
        return False
    if len(stripped) > 150:
        return False
    # Running headers never end with a sentence terminator or comma.
    if stripped[-1] in ".,;:":
        return False
    # Must have at least one SR-number-looking token.
    if not _SR_TOKEN_RE.search(stripped):
        return False
    # If we detected a reference header on page 2, accept any line that
    # shares at least 3 words with it (handles even/odd mirroring).
    if running_header:
        ref_words = set(w for w in running_header.split() if len(w) > 2)
        line_words = set(w for w in stripped.split() if len(w) > 2)
        if len(ref_words & line_words) >= 2:
            return True
    # Fallback: short line with no verb-ish word and an SR token.
    tokens = stripped.split()
    if len(tokens) <= 12:
        return True
    return False


def _detect_running_header(pages: list[_ExtractedPage]) -> str | None:
    """Heuristic: the running header is the line that appears verbatim
    at the top of most pages at font size 8.0.

    Not used anymore (kept for reference) — we detect the running header
    per-page in the main flow via font size, but this function is still
    handy if we need to guard against export drift.
    """
    return None  # placeholder; real detection is inside _parse_pdf_pages


# ─────────────────────────────────────────────
# Body line → Paragraph (pass 2)
# ─────────────────────────────────────────────


def _emit_structural(match: re.Match, level: int, prefix: str | None) -> Paragraph:
    num = match.group(1).strip()
    title = match.group(2).strip()
    text = f"{num}. {prefix}: {title}" if prefix else f"{num} {title}"
    return Paragraph(css_class=f"h{level}", text=_clean_ws(text).strip())


def _parse_body_lines(
    body_lines: Iterable[str],
    notes: _NoteCollector,
) -> list[Paragraph]:
    """Pass 2: classify each body line and emit Paragraphs."""
    paragraphs: list[Paragraph] = []
    in_toc = False
    current_buffer: list[str] = []
    current_css = "preamble"  # before the first article we are in preamble

    def flush() -> None:
        if current_buffer:
            text = _clean_ws(" ".join(current_buffer)).strip()
            # Re-join words broken across line-wraps with a trailing
            # hyphen (``Verfas- sung`` → ``Verfassung``).
            text = _SOFT_HYPHEN_RE.sub(r"\1\2", text)
            if text:
                paragraphs.append(Paragraph(css_class=current_css, text=text))
            current_buffer.clear()

    for raw in body_lines:
        line = _clean_ws(raw).strip()
        if not line:
            continue
        # Soft-hyphen join within a single line (inherits from page-wrap
        # when two wrapped tokens end up on the same body line).
        line = _SOFT_HYPHEN_RE.sub(r"\1\2", line)

        # Stop at Inhaltsverzeichnis — everything after is a TOC that is
        # already represented by the body's article headers.
        if _TOC_HEADER_RE.match(line) or in_toc:
            in_toc = True
            continue
        # A run of "............. Art. NNN" is also a TOC entry; skip.
        if _TOC_RE.search(line):
            continue

        # Structural headings.
        m = _STRUCT_H2_RE.match(line)
        if m:
            flush()
            paragraphs.append(_emit_structural(m, 2, "Titel"))
            current_css = "abs"
            continue
        m = _STRUCT_H3_RE.match(line)
        if m:
            flush()
            paragraphs.append(_emit_structural(m, 3, "Kapitel"))
            current_css = "abs"
            continue
        m = _STRUCT_H4_RE.match(line)
        if m:
            flush()
            paragraphs.append(_emit_structural(m, 4, "Abschnitt"))
            current_css = "abs"
            continue
        m = _STRUCT_BUCH_RE.match(line)
        if m:
            flush()
            paragraphs.append(_emit_structural(m, 2, "Buch"))
            current_css = "abs"
            continue

        # Preamble marker — the Swiss Constitution starts the preamble
        # with the literal line ``Präambel``; we treat everything between
        # that and the first structural heading as preamble body.
        if line == "Präambel":
            flush()
            current_css = "preamble"
            continue

        # Article header.
        m = _ARTICLE_RE.match(line)
        if m:
            flush()
            num, title = m.group(1), (m.group(2) or "").strip()
            header = f"**Art. {num}** {title}".rstrip()
            paragraphs.append(Paragraph(css_class="h5", text=header))
            current_css = "abs"
            continue

        # Lettered list item (with optional footnote anchor glued).
        # Buffered so subsequent non-matching lines are continuations of
        # the same item rather than new paragraphs.
        m = _LIST_RE.match(line)
        if m:
            flush()
            letter, note_ref, body = m.group(1), m.group(2), m.group(3).strip()
            marker = f"- {letter}."
            if note_ref:
                marker += f"[^{note_ref}]"
            current_buffer.append(f"{marker} {body}")
            current_css = "list_item"
            continue

        # Numbered paragraph — e.g. "1 Alle Menschen sind vor dem Gesetz gleich."
        # Buffered so wrap-around lines accumulate into the same Paragraph.
        m = _NUM_PARA_RE.match(line)
        if m and len(m.group(1)) <= 2:
            flush()
            num, body = m.group(1), m.group(2).strip()
            current_buffer.append(f"<sup>{num}</sup> {body}")
            current_css = "abs"
            continue

        # Default — append to the current buffer. The buffer is flushed
        # whenever we hit a heading / list item / numbered paragraph, so
        # multi-line continuations of the prior block accumulate here.
        current_buffer.append(line)

    flush()
    return paragraphs


def _parse_footnote_lines(
    footnote_lines: Iterable[str],
    notes: _NoteCollector,
) -> list[Paragraph]:
    """Combine footnote-sized lines into Fussnoten-block paragraphs.

    Each footnote body in Fedlex PDFs starts with a small number followed
    by the note text. Continuations (wrapped lines of the same footnote)
    have no leading number. We group them and emit as ``[^N]: body``
    paragraphs under a ``Fussnoten`` h6 heading so the structure matches
    the XML parser's output exactly.
    """
    current_num: int | None = None
    current_body: list[str] = []
    collected: list[tuple[int, str]] = []

    def close_current() -> None:
        if current_num is None:
            return
        body = _clean_ws(" ".join(current_body)).strip()
        if body:
            collected.append((current_num, body))

    for raw in footnote_lines:
        line = _clean_ws(raw).strip()
        if not line:
            continue
        m = _FOOTNOTE_BODY_START.match(line)
        if m and len(m.group(1)) <= 3 and int(m.group(1)) > 0:
            close_current()
            current_num = int(m.group(1))
            current_body = [m.group(2)]
        else:
            if current_num is not None:
                current_body.append(line)
    close_current()

    paragraphs: list[Paragraph] = []
    if collected:
        paragraphs.append(Paragraph(css_class="h6", text="Fussnoten"))
        for num, body in collected:
            paragraphs.append(Paragraph(css_class="abs", text=f"[^{num}]: {body}"))
    return paragraphs


# ─────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────


def parse_pdf_version(
    pdf_bytes: bytes,
    norm_id: str,
    publication_date: date,
    effective_date: date,
) -> Version | None:
    """Parse one PDF-A manifestation into a ``Version``.

    Returns ``None`` if pdfplumber cannot open the bytes or the document
    yields no body text — the caller then silently drops the version.
    """
    try:
        pdf = pdfplumber.open(BytesIO(pdf_bytes))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cannot open PDF for %s: %s", norm_id, exc)
        return None

    try:
        # First pass: detect a running header by looking at page 2+.
        running_header: str | None = None
        if len(pdf.pages) >= 2:
            try:
                p2_words = pdf.pages[1].extract_words(extra_attrs=["size"])
                p2_lines = _group_into_lines(p2_words)
                if p2_lines:
                    first_line = p2_lines[0]
                    if (
                        first_line
                        and abs(
                            round(float(first_line[0].get("size", 0.0)), 1)
                            - _FOOTNOTE_OR_HEADER_SIZE
                        )
                        <= _SIZE_TOL
                    ):
                        candidate = _render_line(first_line)
                        # Running header is usually "<short title> <sr_number>"
                        # possibly followed by the page number. Strip a
                        # trailing numeric page-number token to get the
                        # stable header string.
                        tokens = candidate.split()
                        if tokens and tokens[-1].isdigit() and len(tokens[-1]) <= 4:
                            candidate = " ".join(tokens[:-1]).strip()
                        running_header = candidate or None
            except Exception as exc:  # noqa: BLE001
                logger.debug("Could not detect running header: %s", exc)

        # Boilerplate detection — drop everything from the first page
        # that no longer looks like body content. Two independent signals:
        #   (a) explicit "Inhaltsverzeichnis" / "Stichwortverzeichnis" /
        #       "Sachregister" headers — matches ``_TOC_HEADER_RE``;
        #   (b) the Stichwortverzeichnis has NO explicit header and is
        #       detected structurally: once at least one page has
        #       emitted an ``Art. NNN`` body-line, any subsequent page
        #       that does NOT contain such a line is boilerplate.
        cutoff_idx: int | None = None
        has_seen_body = False
        article_start_re = re.compile(r"^Art\.\s*\d+[a-z]*", re.MULTILINE)
        for idx, p in enumerate(pdf.pages):
            try:
                text = p.extract_text() or ""
            except Exception:  # noqa: BLE001
                continue

            # Signal (a) — any TOC/index header on this page.
            if any(_TOC_HEADER_RE.match(line.strip()) for line in text.split("\n")):
                cutoff_idx = idx
                break

            # Signal (b) — body page or not.
            page_has_article = bool(article_start_re.search(text))
            if page_has_article:
                has_seen_body = True
                continue
            if has_seen_body:
                # We were in body and this page no longer is — cut here.
                cutoff_idx = idx
                break

        body_pages = pdf.pages[:cutoff_idx] if cutoff_idx is not None else pdf.pages
        extracted: list[_ExtractedPage] = [_extract_page(p, running_header) for p in body_pages]
    finally:
        pdf.close()

    body_lines: list[str] = []
    footnote_lines: list[str] = []
    for ep in extracted:
        body_lines.extend(ep.body_lines)
        footnote_lines.extend(ep.footnote_lines)

    if not body_lines:
        return None

    # Drop the first few lines if they are the top-of-document SR label /
    # main title / subtitle — already present in metadata.title.
    body_lines = _strip_frontmatter_lines(body_lines)

    notes = _NoteCollector()
    body_paragraphs = _parse_body_lines(body_lines, notes)
    footnote_paragraphs = _parse_footnote_lines(footnote_lines, notes)

    paragraphs = tuple(body_paragraphs + footnote_paragraphs)
    if not paragraphs:
        return None

    return Version(
        norm_id=norm_id,
        publication_date=publication_date,
        effective_date=effective_date,
        paragraphs=paragraphs,
    )


def _strip_frontmatter_lines(lines: list[str]) -> list[str]:
    """Drop the cover-page lines that duplicate ``metadata.title``.

    Fedlex PDFs start with:

        SR-number (standalone line, e.g. ``101``)
        <Long title first part>
        <Long title second part>
        vom <date> (Stand am <date>)

    These are rebuilt by the pipeline from ``NormMetadata.title`` and the
    H1 heading, so we remove them here to avoid duplication at the top of
    the Markdown.
    """
    out = list(lines)
    # Allow up to 10 lines of frontmatter.
    for _ in range(10):
        if not out:
            break
        first = out[0].strip()
        if not first:
            out.pop(0)
            continue
        # SR-number alone.
        if re.fullmatch(r"\d+(\.\d+)*", first):
            out.pop(0)
            continue
        # Long-title fragments (heuristic: don't contain "Art." and
        # appear before the first "Präambel" or "Art. " line).
        if first.startswith("Art.") or first == "Präambel":
            break
        # "vom ... (Stand am ...)" tail of the cover page.
        if re.match(r"^vom\s+\d+\.\s+\w+\s+\d{4}", first):
            out.pop(0)
            continue
        # Subtitle like "Bundesverfassung" or "der Schweizerischen
        # Eidgenossenschaft" — strip.
        if not any(ch.isdigit() for ch in first) and len(first) < 120:
            out.pop(0)
            continue
        break
    return out
