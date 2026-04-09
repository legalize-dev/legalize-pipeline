"""Parsers for Greek Government Gazette (ΦΕΚ) Issue A' documents.

The text parser ingests PDF bytes and emits a single Block of
paragraphs. The metadata parser ingests a JSON bundle produced by
``GreekClient.get_metadata`` containing the official taxonomy from the
Εθνικό Τυπογραφείο: simpleSearch hit + documententitybyid + timeline +
tags + namedentity. Falling back to PDF text parsing only when the
bundle is empty.

ΦΕΚ Α' is the volume of the Greek Government Gazette that contains:

* Νόμοι (laws passed by Parliament)
* Πράξεις Νομοθετικού Περιεχομένου / ΠΝΠ (acts of legislative content,
  Constitution art. 44 §1)
* Προεδρικά Διατάγματα / Π.Δ. (presidential decrees)
* Constitutional revisions (Ψηφίσματα Αναθεωρητικής Βουλής)
* International treaty ratifications

The source is always a born-digital PDF (post-2000) — there is no XML, no
HTML, no JSON full-text. The two-stage pipeline is:

  1. ``pdf_extractor.extract_text_from_pdf(bytes)`` returns clean Greek
     body text with masthead and footer stripped, hyphenations merged, and
     PDFium artifacts (U+FFFE soft-hyphens, control chars) normalised.
  2. ``GreekTextParser`` walks the cleaned text line by line and tags each
     line with the engine's CSS class vocabulary (``titulo_tit``,
     ``capitulo_tit``, ``seccion``, ``articulo``, ``parrafo``, ...) so the
     generic ``transformer/markdown.py`` renders the Markdown headings.

The whole law is wrapped in a single ``Block`` with a single ``Version``,
mirroring Andorra's pattern: each ΦΕΚ Α' issue is treated as an atomic
"as enacted" document. We do **not** apply amendments to existing files
in v1; cross-references to amended laws are captured separately in
``MetadataParser`` and surfaced via ``extra.amends``.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import Any

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.fetcher.gr.client import (
    ISSUE_GROUP_TO_LATIN,
    parse_norm_id,
)
from legalize.fetcher.gr.pdf_extractor import (
    GR_TABLE_CLOSE,
    GR_TABLE_OPEN,
    extract_text_from_pdf,
)
from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    Rank,
    Version,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Greek normative ranks (Rank is a free-form str subclass)
# ─────────────────────────────────────────────

RANK_NOMOS = Rank("nomos")  # Νόμος — Law passed by Parliament
RANK_PNP = Rank("pnp")  # Πράξη Νομοθετικού Περιεχομένου — Act of Legislative Content
RANK_PD = Rank("proedriko_diatagma")  # Προεδρικό Διάταγμα — Presidential Decree
RANK_SYNTAGMA = Rank("syntagma")  # Σύνταγμα — Constitution (and revision resolutions)
RANK_DIETHNIS = Rank("diethnis_symvasi")  # Διεθνής Σύμβαση — International treaty
# ΥΑ / ΚΥΑ that *do* appear in Τεύχος Α' — typically international
# treaty ratifications or special acts. Distinct from the bulk of Υ.Α.
# which live in Τεύχος Β' (out of scope for v1).
RANK_APOFASI = Rank("apofasi")  # Απόφαση — Ministerial / Joint Ministerial decision in FEK Α'
# Acts of the Plenary of the Hellenic Parliament (Αποφάσεις Ολομέλειας
# της Βουλής), e.g. parliament regulation amendments. They live in
# Τεύχος Α' but follow their own format.
RANK_APOFASI_VOULIS = Rank("apofasi_vouli")  # Απόφαση Ολομέλειας Βουλής
# Πράξη Υπουργικού Συμβουλίου — Cabinet Acts. Issued by the Council
# of Ministers when no individual signing minister is named. The first
# line of the body is "ΠΡΑΞΕΙΣ ΥΠΟΥΡΓΙΚΟΥ ΣΥΜΒΟΥΛΙΟΥ" followed by
# "Πράξη N της DD.MM.YYYY".
RANK_PYS = Rank("praxi_ypourgikou_symvouliou")
# Κανονισμός — Regulation. Used for Holy Synod regulations of the
# Greek Orthodox Church (which are published in FEK Α' by virtue of
# the church's special legal status), and for some Parliament
# internal regulations.
RANK_KANONISMOS = Rank("kanonismos")
RANK_OTRO = Rank("otro")


# ─────────────────────────────────────────────
# Structural marker regexes
#
# Greek FEK Α' uses a hierarchy of headings that we map to engine CSS
# classes (which the generic Markdown transformer renders as `##`-`#####`):
#
#   ΜΕΡΟΣ N            → titulo_tit  (## H2)        Major part
#   ΤΜΗΜΑ N            → capitulo_tit (### H3)      Section
#   ΚΕΦΑΛΑΙΟ N         → seccion (#### H4)          Chapter
#   Άρθρο N            → articulo (##### H5)        Article
#   ΠΑΡΑΡΤΗΜΑ X        → seccion (#### H4)          Annex
#
# These are tested against trimmed lines (whitespace already stripped).
# ─────────────────────────────────────────────

# Greek capital letters that may appear as Article suffixes (Άρθρο 152Α etc.)
# Listed explicitly so we don't accidentally match Latin look-alikes.
_GREEK_CAPS = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"

_RE_MEROS = re.compile(rf"^ΜΕΡΟΣ\s+([A-Z{_GREEK_CAPS}]+|\d+)\b")
_RE_TMIMA = re.compile(rf"^ΤΜΗΜΑ\s+([A-Z{_GREEK_CAPS}]+|\d+)\b")
_RE_KEFALAIO = re.compile(rf"^ΚΕΦΑΛΑΙΟ\s+([A-Z{_GREEK_CAPS}]+|\d+)\b")
_RE_ARTICLE = re.compile(rf"^Άρθρο\s+(\d+[{_GREEK_CAPS}]?)\b")
_RE_ANNEX = re.compile(rf"^ΠΑΡΑΡΤΗΜΑ\s+([A-Z{_GREEK_CAPS}]+|\d+)?\b")
_RE_DISP_TRANS = re.compile(r"^ΜΕΤΑΒΑΤΙΚΕΣ ΔΙΑΤΑΞΕΙΣ\b")
_RE_DISP_FINAL = re.compile(r"^ΤΕΛΙΚΕΣ ΔΙΑΤΑΞΕΙΣ\b")

# The first body line of every FEK Α' law is one of these patterns:
#   "ΝΟΜΟΣ ΥΠ' ΑΡΙΘ. NNNN"          (ordinary law)
#   "ΠΡΟΕΔΡΙΚΟ ΔΙΑΤΑΓΜΑ ΥΠ' ΑΡΙΘΜ. NNN"  (presidential decree)
#   "ΨΗΦΙΣΜΑ ΤΗΣ ... ΑΝΑΘΕΩΡΗΤΙΚΗΣ ΒΟΥΛΗΣ ..."  (constitutional revision)
#   "ΠΡΑΞΗ ΝΟΜΟΘΕΤΙΚΟΥ ΠΕΡΙΕΧΟΜΕΝΟΥ"  (act of legislative content)
#
# Greek typesetters use four different "apostrophe" characters in the
# "ΥΠ' ΑΡΙΘ" sequence depending on the publication era and the font:
#   U+0027 ASCII APOSTROPHE         '
#   U+2019 RIGHT SINGLE QUOTE       ’ (most common in modern PDFs)
#   U+02BC MODIFIER LETTER APOSTR.  ʼ
#   U+0384 GREEK TONOS              ΄ (rare, but appears in some old laws)
# We accept any of them via an explicit Unicode character class so the
# regex is robust across the whole 2000-2019 fixture spectrum.
_APOS_CLASS = "[\u0027\u2019\u02bc\u0384]"

# Some old Greek PDFs (2006, 2010 fixtures) encode the Greek capital
# letters Ν, Μ, Ο, Α, Β, Ε etc. using their Latin look-alikes (U+004E,
# U+004D, U+004F, U+0041, U+0042, U+0045) because of font subsetting
# issues at the typesetter. The visible result is identical but a regex
# searching for "ΝΟΜΟΣ" won't match "NOMOΣ" because N (U+004E) ≠ Ν
# (U+039D). We define a translation table that we apply only when
# *matching* the title — never to the rendered body — so the original
# spelling is preserved in the output but our title detection is robust.
_LATIN_TO_GREEK_CAPS = str.maketrans(
    {
        "A": "Α",
        "B": "Β",
        "E": "Ε",
        "Z": "Ζ",
        "H": "Η",
        "I": "Ι",
        "K": "Κ",
        "M": "Μ",
        "N": "Ν",
        "O": "Ο",
        "P": "Ρ",
        "T": "Τ",
        "Y": "Υ",
        "X": "Χ",
    }
)


def _normalize_title_chars(line: str) -> str:
    """Latin → Greek look-alike normalisation for title detection only."""
    return line.translate(_LATIN_TO_GREEK_CAPS)


_RE_NOMOS_TITLE = re.compile(rf"ΝΟΜΟΣ\s+ΥΠ{_APOS_CLASS}?\s*ΑΡΙΘ[ΜM]?\.?\s*(\d+)")
_RE_PD_TITLE = re.compile(rf"ΠΡΟΕΔΡΙΚΟ\s+ΔΙΑΤΑΓΜΑ\s+ΥΠ{_APOS_CLASS}?\s*ΑΡΙΘ[ΜM]?\.?\s*(\d+)")
_RE_PNP_TITLE = re.compile(r"ΠΡΑΞΗ\s+ΝΟΜΟΘΕΤΙΚΟΥ\s+ΠΕΡΙΕΧΟΜΕΝΟΥ")
_RE_SYNTAGMA_TITLE = re.compile(r"(ΣΥΝΤΑΓΜΑ|ΑΝΑΘΕΩΡΗΤΙΚΗΣ\s+ΒΟΥΛΗΣ)")
# Apofasis variants in Τεύχος Α' — these are acts whose first
# meaningful line is "ΑΠΟΦΑΣΕΙΣ" or "ΑΠΟΦΑΣΗ" (sometimes followed
# by a number/code), and which lack a "ΝΟΜΟΣ" / "ΠΡΟΕΔΡΙΚΟ ΔΙΑΤΑΓΜΑ"
# preamble. Examples observed in the 50-norm trial:
#   * Treaty ratifications (FEK A 107/2016, "ΑΠΟΦΑΣΕΙΣ" + UN code)
#   * Decisions of the Plenary of Parliament (FEK A 89/2010)
#   * Joint ministerial decisions about church metropolitan boundaries
_RE_APOFASI_VOULIS = re.compile(r"ΑΠΟΦΑΣΕΙΣ?\s+(?:ΤΗΣ\s+)?ΟΛΟΜΕΛΕΙΑΣ\s+(?:ΤΗΣ\s+)?ΒΟΥΛΗΣ")
_RE_APOFASI_HEAD = re.compile(r"^ΑΠΟΦΑΣΕΙΣ?\b")
# Cabinet acts always carry the section header "ΠΡΑΞΕΙΣ ΥΠΟΥΡΓΙΚΟΥ
# ΣΥΜΒΟΥΛΙΟΥ" plus a per-act line "Πράξη N της DD.MM.YYYY". We anchor
# on the section header because the per-act line is too generic.
_RE_PYS_TITLE = re.compile(r"ΠΡΑΞΕΙΣ?\s+ΥΠΟΥΡΓΙΚΟΥ\s+ΣΥΜΒΟΥΛΙΟΥ")
# Holy Synod and Parliament regulations. The body always opens with
# "ΚΑΝΟΝΙΣΜΟΣ ΥΠ' ΑΡΙΘ. NN/YYYY" — same shape as ΝΟΜΟΣ ΥΠ' ΑΡΙΘ.
_RE_KANONISMOS_TITLE = re.compile(rf"ΚΑΝΟΝΙΣΜ(?:ΟΣ|ΟΙ)\s+ΥΠ{_APOS_CLASS}?\s*ΑΡΙΘ[ΜM]?\.?\s*(\d+)")
# Plural section header for compound FEK Α' issues that contain
# multiple individual decrees. We map to the same rank as the singular
# form, because the issue's primary content type IS presidential
# decrees even if it lists several.
_RE_PD_PLURAL = re.compile(r"ΠΡΟΕΔΡΙΚ[ΑO]Σ?\s+ΔΙΑΤΑΓΜΑΤΑ")


# ─────────────────────────────────────────────
# Official taxonomy: documententitybyid_topics_Name → Rank
#
# These are the topic strings the Εθνικό Τυπογραφείο returns in the
# ``documententitybyid_topics_Name`` field. Mapping is canonical so the
# rank in our frontmatter matches the official classification.
# ─────────────────────────────────────────────
_OFFICIAL_TOPIC_TO_RANK: dict[str, Rank] = {
    "Νόμος": RANK_NOMOS,
    "Νόμοι": RANK_NOMOS,
    "Προεδρικό Διάταγμα": RANK_PD,
    "Προεδρικά Διατάγματα": RANK_PD,
    "Πράξη Νομοθετικού Περιεχομένου": RANK_PNP,
    "Πράξεις Νομοθετικού Περιεχομένου": RANK_PNP,
    "Νομοθετικό Διάταγμα": Rank("nomothetiko_diatagma"),
    "Νομοθετικά Διατάγματα": Rank("nomothetiko_diatagma"),
    "Αναγκαστικός Νόμος": Rank("anagastikos_nomos"),
    "Βασιλικό Διάταγμα": Rank("vasiliko_diatagma"),
    "Βασιλικά Διατάγματα": Rank("vasiliko_diatagma"),
    "Σύνταγμα": RANK_SYNTAGMA,
    "Πράξη Υπουργικού Συμβουλίου": RANK_PYS,
    "Πράξεις Υπουργικού Συμβουλίου": RANK_PYS,
    "Κανονισμός": RANK_KANONISMOS,
    "Κανονισμοί": RANK_KANONISMOS,
    "Απόφαση": RANK_APOFASI,
    "Αποφάσεις": RANK_APOFASI,
    "Απόφαση Ολομέλειας Βουλής": RANK_APOFASI_VOULIS,
    "Αποφάσεις Ολομέλειας Βουλής": RANK_APOFASI_VOULIS,
}

# Preamble lines that appear right after the title block — they should be
# rendered as bold/centered, not body text.
_PREAMBLE_LINES = (
    "Ο ΠΡΟΕΔΡΟΣ",
    "Η ΠΡΟΕΔΡΟΣ",
    "ΤΗΣ ΕΛΛΗΝΙΚΗΣ ΔΗΜΟΚΡΑΤΙΑΣ",
    "ΤΗΣ ΒΟΥΛΗΣ ΤΩΝ ΕΛΛΗΝΩΝ",
)

# Greek lettered list markers — these should become Markdown list items.
# We match α/β/γ/δ/ε/ζ/η/θ/ι/κ/λ/μ/ν/ξ/ο/π/ρ/σ/τ/υ/φ/χ/ψ/ω followed by ")".
_RE_GREEK_LIST_ITEM = re.compile(r"^([α-ω]{1,3})\)\s+")
# Numbered paragraphs: "1. ...", "2. ...", "10. ...", etc.
_RE_NUMBERED_PARA = re.compile(r"^(\d+)\.\s+")

# Cross-reference regex (for metadata.extra.amends — picked up later)
_RE_LAW_REF = re.compile(r"[Νν]\.\s?(\d{3,5})/(\d{4})")
_RE_PD_REF = re.compile(r"π\.δ\.\s?(\d{1,4})/(\d{4})", re.IGNORECASE)

# Greek month names (genitive case, as they appear in dated lines like
# "23 Ιουλίου 2013"). Lowercased for case-insensitive matching.
_GREEK_MONTHS = {
    "ιανουαρίου": 1,
    "φεβρουαρίου": 2,
    "μαρτίου": 3,
    "απριλίου": 4,
    "μαΐου": 5,
    "μαϊου": 5,  # variant without modifier
    "ιουνίου": 6,
    "ιουλίου": 7,
    "αυγούστου": 8,
    "σεπτεμβρίου": 9,
    "οκτωβρίου": 10,
    "νοεμβρίου": 11,
    "δεκεμβρίου": 12,
}
_RE_GREEK_DATE = re.compile(r"\b(\d{1,2})\s+([Α-Ωα-ωΆ-Ώά-ώ]+)\s+(\d{4})\b", re.UNICODE)


# ─────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────


def _classify_line(line: str) -> str:
    """Map a Greek FEK A' line to an engine CSS class.

    Decision order matters — most specific patterns are checked first so
    "ΜΕΡΟΣ A — Άρθρο 1" doesn't get classified as an article.
    """
    stripped = line.strip()
    if not stripped:
        return "parrafo"

    # Latin/Greek look-alike normalisation for matching only — the
    # original line is what we emit downstream.
    norm = _normalize_title_chars(stripped)

    # Top-level structural markers
    if _RE_MEROS.match(norm):
        return "titulo_tit"
    if _RE_TMIMA.match(norm):
        return "capitulo_tit"
    if _RE_KEFALAIO.match(norm):
        return "seccion"
    if _RE_ANNEX.match(norm):
        return "seccion"
    if _RE_DISP_TRANS.match(norm) or _RE_DISP_FINAL.match(norm):
        return "seccion"

    # Article heading
    if _RE_ARTICLE.match(stripped):
        return "articulo"

    # Title block (only the very top of the document)
    if _RE_NOMOS_TITLE.search(norm):
        return "centro_negrita"
    if _RE_PD_TITLE.search(norm):
        return "centro_negrita"
    if _RE_PNP_TITLE.search(norm):
        return "centro_negrita"
    if _RE_SYNTAGMA_TITLE.search(norm):
        return "centro_negrita"

    # Preamble (executive signature lines)
    if any(stripped.startswith(p) for p in _PREAMBLE_LINES):
        return "firma_rey"

    # Greek lettered list items
    if _RE_GREEK_LIST_ITEM.match(stripped):
        return "list_item"

    # Default: body paragraph (also catches numbered paragraphs like "1. ...")
    return "parrafo"


def _split_text_around_tables(text: str) -> list[tuple[str, str]]:
    """Split the cleaned PDF text into ``(kind, content)`` segments.

    ``kind`` is either ``"text"`` (regular body text to be processed
    line-by-line) or ``"table"`` (a pre-rendered Markdown pipe table to
    be emitted as a single ``Paragraph(css_class="table_row")``). Splits
    on the ``GR_TABLE_OPEN`` / ``GR_TABLE_CLOSE`` sentinels emitted by
    ``pdf_extractor._append_page_tables``.
    """
    open_marker = GR_TABLE_OPEN.strip("\n")
    close_marker = GR_TABLE_CLOSE.strip("\n")
    pattern = re.compile(
        f"{re.escape(open_marker)}(.*?){re.escape(close_marker)}",
        re.DOTALL,
    )
    out: list[tuple[str, str]] = []
    cursor = 0
    for m in pattern.finditer(text):
        if m.start() > cursor:
            out.append(("text", text[cursor : m.start()]))
        out.append(("table", m.group(1).strip("\n")))
        cursor = m.end()
    if cursor < len(text):
        out.append(("text", text[cursor:]))
    return out


def _text_to_paragraphs(text: str) -> list[Paragraph]:
    """Walk the cleaned PDF text segment-by-segment and emit Paragraphs.

    Body text segments are walked line-by-line: adjacent body lines that
    don't end with sentence punctuation are re-flowed into a single
    paragraph (PDF text comes line-wrapped from typesetting; the legal
    "paragraph" is logical, not physical). Heading lines (article,
    chapter, etc.) are always emitted as standalone. Table segments
    (pre-rendered Markdown pipe tables, marked by ``GR_TABLE`` sentinels)
    are emitted as a single ``Paragraph(css_class="table_row", ...)``
    which the engine renderer passes through verbatim.
    """
    paragraphs: list[Paragraph] = []
    buffer: list[str] = []
    buffer_class = "parrafo"

    def flush() -> None:
        if buffer:
            joined = " ".join(buffer).strip()
            if joined:
                paragraphs.append(Paragraph(css_class=buffer_class, text=joined))
            buffer.clear()

    for kind, content in _split_text_around_tables(text):
        if kind == "table":
            flush()
            paragraphs.append(Paragraph(css_class="table_row", text=content))
            buffer_class = "parrafo"
            continue

        for raw in content.splitlines():
            line = raw.strip()
            if not line:
                flush()
                continue

            css = _classify_line(line)

            # Headings: flush current buffer, emit heading as its own paragraph
            if css in ("titulo_tit", "capitulo_tit", "seccion", "articulo", "centro_negrita"):
                flush()
                paragraphs.append(Paragraph(css_class=css, text=line))
                buffer_class = "parrafo"
                continue

            # Signature lines: flush, emit as own paragraph
            if css == "firma_rey":
                flush()
                paragraphs.append(Paragraph(css_class=css, text=line))
                buffer_class = "parrafo"
                continue

            # List items: flush prior, then emit each list item as standalone
            # paragraph (so the Markdown renderer can handle them as a list).
            if css == "list_item":
                flush()
                paragraphs.append(Paragraph(css_class=css, text=f"- {line}"))
                buffer_class = "parrafo"
                continue

            # Body line — accumulate. If the line starts with a number followed
            # by a dot (e.g. "1. ..."), it's the start of a new logical paragraph,
            # so flush the previous buffer first.
            if _RE_NUMBERED_PARA.match(line) and buffer:
                flush()

            buffer.append(line)
            buffer_class = "parrafo"

        flush()

    flush()
    return paragraphs


def _detect_rank_from_text(text: str) -> Rank:
    """Detect the law's rank from the title line of the cleaned text.

    Decision order: most specific patterns first (PNP, PD, Syntagma,
    Nomos), then the broader Απόφαση patterns. We check the Plenary of
    Parliament marker before the generic ``^ΑΠΟΦΑΣΕΙΣ`` so a parliament
    decision is correctly tagged as ``apofasi_vouli`` rather than the
    catch-all ``apofasi``.
    """
    # Inspect only the first ~50 lines so very long laws don't waste time.
    # Latin/Greek normalisation is essential — older PDFs (2006, 2010)
    # encode "ΝΟΜΟΣ" with Latin "N", "O", "M" look-alikes.
    lines = text.splitlines()[:50]
    head = _normalize_title_chars("\n".join(lines))
    if _RE_PNP_TITLE.search(head):
        return RANK_PNP
    if _RE_PD_TITLE.search(head):
        return RANK_PD
    if _RE_SYNTAGMA_TITLE.search(head):
        return RANK_SYNTAGMA
    if _RE_NOMOS_TITLE.search(head):
        return RANK_NOMOS
    if _RE_KANONISMOS_TITLE.search(head):
        return RANK_KANONISMOS
    if _RE_PYS_TITLE.search(head):
        return RANK_PYS
    if _RE_APOFASI_VOULIS.search(head):
        return RANK_APOFASI_VOULIS
    # Plural PD section header (compound FEK Α' issue)
    if _RE_PD_PLURAL.search(head):
        return RANK_PD
    # Generic Απόφαση: must appear within the first ~8 non-empty lines.
    # The 8-line window covers the case where the gazette masthead
    # ("ΕΦΗΜΕΡΙΣ ΤΗΣ ΚΥΒΕΡΝΗΣΕΩΣ" + 3 more lines) is still in the
    # extracted text and the actual rank line ("ΑΠΟΦΑΣΕΙΣ") sits at
    # line 4-5. We don't widen further so a random later "ΑΠΟΦΑΣΕΙΣ"
    # mention in the body of a Νόμος doesn't override the proper rank.
    n_seen = 0
    for line in lines:
        stripped = _normalize_title_chars(line.strip())
        if not stripped:
            continue
        if _RE_APOFASI_HEAD.match(stripped):
            return RANK_APOFASI
        n_seen += 1
        if n_seen >= 8:
            break
    return RANK_OTRO


def _extract_law_number(text: str) -> tuple[str, str] | None:
    """Pull (number, year) from the title line, if present.

    Returns ``(number, year)`` or ``None``. Year is taken from the document
    date elsewhere; this function only finds the law number itself.
    """
    head = "\n".join(text.splitlines()[:20])
    m = _RE_NOMOS_TITLE.search(head)
    if m:
        return m.group(1), ""
    m = _RE_PD_TITLE.search(head)
    if m:
        return m.group(1), ""
    return None


def _extract_cached(data: bytes) -> tuple[str, str, str]:
    """Run the extractor on PDF bytes; the extractor caches the result so
    parse_text + parse on the same document only do real work once.

    Note: this helper assumes ``data`` is the raw PDF bytes. The text
    parser is the only caller — the metadata parser now uses the JSON
    bundle path and only falls back here when invoked with raw PDF
    bytes by older test code.
    """
    return extract_text_from_pdf(data)


# ─────────────────────────────────────────────
# Public TextParser
# ─────────────────────────────────────────────


class GreekTextParser(TextParser):
    """Parses a ΦΕΚ Α' PDF into a single Block of Greek legal text.

    Each FEK A' issue is one atomic "as enacted" document. We do not split
    into per-article Blocks because the engine treats one Block + one
    Version as the canonical "single document" shape (matching Andorra,
    Latvia, Estonia, Uruguay).

    Input format
    ------------
    ``data`` is the raw PDF bytes — exactly what you get from downloading
    a file from the official ``ia37rg02wpsa01.blob.core.windows.net/fek/``
    Azure Blob storage that backs ``search.et.gr``.
    """

    def parse_text(self, data: bytes) -> list[Any]:
        if not data:
            logger.warning("GreekTextParser.parse_text called with empty data")
            return []

        text, _, _ = _extract_cached(data)

        if not text:
            # Most likely a scanned PDF without a text layer. Pre-2003 FEK
            # PDFs are sometimes still scans even though the year is past
            # our text-layer cutoff. The pipeline should treat this as a
            # SKIP (not a failure) — Phase 3 will OCR them.
            logger.warning(
                "PDF extraction produced no text — likely a scanned PDF "
                "(no text layer). Skipping; consider Phase 3 OCR."
            )
            return []

        paragraphs = _text_to_paragraphs(text)
        if not paragraphs:
            logger.warning("Parsed Greek FEK but produced no paragraphs")
            return []

        # Pull the publication date from the PDF body so the Version
        # carries the right timestamp. The pdf_extractor cache means
        # this re-extraction is essentially free (same bytes already
        # extracted by the pipeline's earlier metadata-parse call).
        pub_date = GreekMetadataParser._extract_publication_date(text) or date(1900, 1, 1)

        # Wrap in single Block — Greek FEK A' issues are atomic.
        version = Version(
            norm_id="",
            publication_date=pub_date,
            effective_date=pub_date,
            paragraphs=tuple(paragraphs),
        )
        block = Block(
            id="body",
            block_type="article",
            title="",
            versions=(version,),
        )
        return [block]


# ─────────────────────────────────────────────
# MetadataParser — placeholder for Phase 1
# ─────────────────────────────────────────────


class GreekMetadataParser(MetadataParser):
    """Builds NormMetadata from the official metadata bundle.

    Input is a JSON bundle produced by ``GreekClient.get_metadata`` with::

        {
          "norm_id": "FEK-A-167-2013",
          "year": 2013,
          "issue_group": 1,
          "doc_number": 167,
          "search": {...},          // simpleSearch hit
          "metadata": [...],        // documententitybyid fragments
          "timeline": [...],        // modification graph
          "tags": [...],            // controlled-vocabulary subject tags
          "named_entities": [...]   // NER output
        }

    All fields come from the Εθνικό Τυπογραφείο so we don't need to
    infer rank, title, or date from the PDF text. The PDF body is
    still parsed by ``GreekTextParser`` for the actual content.

    For backward compatibility (and as a safety net) the parser also
    accepts raw PDF bytes and falls back to the regex-based extraction
    described in the previous Phase 1 implementation.
    """

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        if not data:
            raise ValueError("GreekMetadataParser.parse called with empty data")

        # Distinguish between JSON bundle (new path) and raw PDF (legacy)
        if data.startswith(b"{"):
            return self._parse_bundle(data, norm_id)
        return self._parse_pdf_legacy(data, norm_id)

    # ── New bundle-based path (preferred) ──

    def _parse_bundle(self, data: bytes, norm_id: str) -> NormMetadata:
        try:
            bundle = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON metadata bundle for {norm_id}: {exc}") from exc

        flat = self._flatten_metadata(bundle.get("metadata") or [])
        search_hit = bundle.get("search") or {}
        timeline = bundle.get("timeline") or []
        tags = bundle.get("tags") or []
        ner = bundle.get("named_entities") or []

        # Use bundle-provided coordinates as authoritative
        try:
            year = int(bundle.get("year") or parse_norm_id(norm_id)[0])
            issue_group = int(bundle.get("issue_group") or parse_norm_id(norm_id)[1])
            doc_number = int(bundle.get("doc_number") or parse_norm_id(norm_id)[2])
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Bundle for {norm_id} missing coordinates: {exc}") from exc

        rank = self._rank_from_bundle(flat, search_hit)
        title = self._title_from_bundle(flat, search_hit, year, issue_group, doc_number)
        short_title = self._short_title(year, issue_group, doc_number)
        pub_date = self._publication_date_from_bundle(flat, search_hit) or date(year, 1, 1)
        source_url = self._build_source_url(year, issue_group, doc_number)

        extra = self._build_extra_fields(
            flat=flat,
            search_hit=search_hit,
            timeline=timeline,
            tags=tags,
            ner=ner,
        )
        # Subjects: official subjects + tags, deduplicated and capped
        subjects = self._collect_subjects(flat, tags)

        return NormMetadata(
            title=title or short_title,
            short_title=short_title,
            identifier=norm_id,
            country="gr",
            rank=rank,
            publication_date=pub_date,
            status=NormStatus.IN_FORCE,
            department="",
            source=source_url,
            jurisdiction=None,
            subjects=tuple(subjects),
            extra=tuple(extra),
        )

    @staticmethod
    def _flatten_metadata(items: list[dict[str, Any]]) -> dict[str, Any]:
        """Coalesce a documententitybyid response array into one dict.

        The API returns multiple fragments per document (one per topic,
        subject, protocol number, etc.). For scalar fields we keep the
        last value seen; for list-like fields (topics, subjects) we
        accumulate.
        """
        flat: dict[str, Any] = {}
        topics: list[dict[str, Any]] = []
        subjects: list[dict[str, Any]] = []
        protocol_publishers: list[str] = []
        for item in items:
            for k, v in item.items():
                if k.endswith("_topics_ID") or k.endswith("_topics_Name"):
                    # accumulate topic dicts
                    pass
                elif k.endswith("_subjects_ID") or k.endswith("_subjects_Value"):
                    pass
                elif k == "documententitybyid_protocolnumber_PublisherID":
                    protocol_publishers.append(str(v))
                else:
                    flat[k] = v
            # Build the topic/subject objects from each fragment
            if "documententitybyid_topics_Name" in item:
                topics.append(
                    {
                        "id": str(item.get("documententitybyid_topics_ID") or ""),
                        "name": str(item.get("documententitybyid_topics_Name") or ""),
                    }
                )
            if "documententitybyid_subjects_Value" in item:
                subjects.append(
                    {
                        "id": str(item.get("documententitybyid_subjects_ID") or ""),
                        "value": str(item.get("documententitybyid_subjects_Value") or ""),
                    }
                )
        flat["_topics"] = topics
        flat["_subjects"] = subjects
        flat["_protocol_publishers"] = protocol_publishers
        return flat

    @staticmethod
    def _rank_from_bundle(flat: dict[str, Any], search_hit: dict[str, Any]) -> Rank:
        """Map the official topics_Name field to our internal Rank."""
        topics = flat.get("_topics") or []
        # First topic is usually the most specific
        for topic in topics:
            name = (topic.get("name") or "").strip()
            if name in _OFFICIAL_TOPIC_TO_RANK:
                return _OFFICIAL_TOPIC_TO_RANK[name]
        # Fall back to substring matching for plural / variant forms
        for topic in topics:
            name = (topic.get("name") or "").strip()
            for needle, rank in _OFFICIAL_TOPIC_TO_RANK.items():
                if needle and (needle in name or name in needle):
                    return rank
        # If no topics match, fall back to "otro" — this may happen for
        # rare document types we haven't mapped yet.
        return RANK_OTRO

    @staticmethod
    def _title_from_bundle(
        flat: dict[str, Any],
        search_hit: dict[str, Any],
        year: int,
        issue_group: int,
        doc_number: int,
    ) -> str:
        """Build a human-readable title from the bundle.

        Format: ``"<topic name> — ΦΕΚ <Α'> <num>/<year>"`` (e.g.
        ``"Νόμοι — ΦΕΚ Α' 167/2013"``). The official API doesn't expose
        the per-act subtitle in this endpoint — for the legal subtitle
        we'd need to parse the PDF body. For now the structured title
        is always meaningful and human-readable.
        """
        topics = flat.get("_topics") or []
        primary = (search_hit.get("search_PrimaryLabel") or "").strip()
        topic_name = (topics[0].get("name") if topics else "") or ""
        letter = ISSUE_GROUP_TO_LATIN.get(issue_group, "?")
        if topic_name:
            base = f"{topic_name} — ΦΕΚ {letter}' {doc_number}/{year}"
        elif primary:
            base = primary
        else:
            base = f"ΦΕΚ {letter}' {doc_number}/{year}"
        return base

    @staticmethod
    def _short_title(year: int, issue_group: int, doc_number: int) -> str:
        letter = ISSUE_GROUP_TO_LATIN.get(issue_group, "?")
        return f"ΦΕΚ {letter}' {doc_number}/{year}"

    @staticmethod
    def _publication_date_from_bundle(
        flat: dict[str, Any],
        search_hit: dict[str, Any],
    ) -> date | None:
        """Parse the official publication date.

        The API returns dates in ``MM/DD/YYYY HH:MM:SS`` format in
        ``documententitybyid_PublicationDate`` and
        ``search_PublicationDate``.
        """
        for key, source in [
            ("documententitybyid_PublicationDate", flat),
            ("documententitybyid_IssueDate", flat),
            ("search_PublicationDate", search_hit),
            ("search_IssueDate", search_hit),
        ]:
            raw = (source.get(key) or "").strip() if isinstance(source, dict) else ""
            if not raw:
                continue
            for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%Y-%m-%d"):
                try:
                    return datetime.strptime(raw, fmt).date()
                except ValueError:
                    continue
        return None

    @staticmethod
    def _build_source_url(year: int, issue_group: int, doc_number: int) -> str:
        """Build the canonical official source URL.

        Points at the Azure Blob URL where the PDF lives. This is the
        same URL the search.et.gr UI ultimately fetches when a logged-in
        user clicks "download" on a result row, just exposed directly.
        """
        ig = f"{issue_group:02d}"
        nn = f"{doc_number:05d}"
        filename = f"{year}{ig}{nn}"
        return f"https://ia37rg02wpsa01.blob.core.windows.net/fek/{ig}/{year}/{filename}.pdf"

    @staticmethod
    def _collect_subjects(flat: dict[str, Any], tags: list[dict[str, Any]]) -> list[str]:
        """Collect official subjects + controlled-vocabulary tags."""
        out: list[str] = []
        seen: set[str] = set()
        for subj in flat.get("_subjects") or []:
            v = (subj.get("value") or "").strip()
            if v and v not in seen:
                seen.add(v)
                out.append(v)
        for tag in tags:
            for k in (
                "tagsbydocumententity_Value",
                "tagsbyissue_Value",
                "tags_Value",
            ):
                v = (tag.get(k) or "").strip() if isinstance(tag, dict) else ""
                if v and v not in seen:
                    seen.add(v)
                    out.append(v)
                    break
        return out[:50]  # cap for frontmatter readability

    @staticmethod
    def _build_extra_fields(
        *,
        flat: dict[str, Any],
        search_hit: dict[str, Any],
        timeline: list[dict[str, Any]],
        tags: list[dict[str, Any]],
        ner: list[dict[str, Any]],
    ) -> list[tuple[str, str]]:
        """Assemble the country-specific ``extra`` frontmatter fields."""
        extra: list[tuple[str, str]] = []

        # Pages, document number, search ID — useful for cross-linking
        for src_key, frontmatter_key in [
            ("documententitybyid_DocumentNumber", "fek_number"),
            ("documententitybyid_IssueGroupID", "fek_issue_group"),
            ("documententitybyid_Pages", "pages"),
            ("documententitybyid_PrimaryLabel", "fek_label"),
            ("documententitybyid_ReReleaseDate", "rerelease_date"),
        ]:
            v = (
                (flat.get(src_key) or "").strip()
                if isinstance(flat.get(src_key), str)
                else flat.get(src_key)
            )
            if v:
                extra.append((frontmatter_key, str(v)[:200]))

        if search_hit.get("search_ID"):
            extra.append(("search_id", str(search_hit["search_ID"])))

        # Modification graph from timeline endpoint.
        # Direction "-1" = OTHER document modifies us (incoming reform)
        # We summarise the count + the first 50 most-recent modifications.
        modifications_in: list[str] = []
        modifications_out: list[str] = []
        references: list[str] = []
        for edge in timeline:
            if not isinstance(edge, dict):
                continue
            rel_type = (edge.get("timeline_RelationshipTypeID") or "").strip()
            label = (edge.get("timeline_PrimaryLabel") or "").strip()
            direction = (edge.get("timeline_Direction") or "").strip()
            if not label:
                continue
            if rel_type == "0":  # modification
                if direction == "-1":
                    modifications_in.append(label)
                else:
                    modifications_out.append(label)
            elif rel_type == "2":  # reference
                references.append(label)

        if modifications_in:
            extra.append(("amended_by_count", str(len(modifications_in))))
            extra.append(("amended_by", ",".join(modifications_in[:50])))
        if modifications_out:
            extra.append(("amends_count", str(len(modifications_out))))
            extra.append(("amends", ",".join(modifications_out[:50])))
        if references:
            extra.append(("references_count", str(len(references))))

        return extra

    # ── Legacy PDF-based path (fallback) ──

    def _parse_pdf_legacy(self, data: bytes, norm_id: str) -> NormMetadata:
        """Fallback path for callers that pass raw PDF bytes (older tests)."""
        text, _, _ = _extract_cached(data)

        rank = _detect_rank_from_text(text)
        title = self._extract_title(text)
        amends = self._collect_amend_refs(text)
        pub_date = self._extract_publication_date(text)
        source_url = self._legacy_source_url(norm_id)

        return NormMetadata(
            title=title or norm_id,
            short_title=title or norm_id,
            identifier=norm_id,
            country="gr",
            rank=rank,
            publication_date=pub_date or date(1900, 1, 1),
            status=NormStatus.IN_FORCE,
            department="",
            source=source_url,
            jurisdiction=None,
            extra=tuple(amends),
        )

    @staticmethod
    def _legacy_source_url(norm_id: str) -> str:
        """Best-effort source URL when no bundle is available."""
        try:
            year, issue_group, doc_number = parse_norm_id(norm_id)
        except ValueError:
            return ""
        return GreekMetadataParser._build_source_url(year, issue_group, doc_number)

    @staticmethod
    def _extract_publication_date(text: str) -> date | None:
        """Pull a ``dd Month yyyy`` Greek date from the document.

        Two-tier search:

        1. First try the first ~15 lines — most ΦΕΚ Α' laws (Νόμος) carry
           the issue date in the gazette masthead, e.g. "23 Ιουλίου 2013".
        2. If that fails (Π.Δ. tend to start directly with the rank line
           and have no masthead), search the **whole document** for the
           signature date format "Αθήνα, dd Month yyyy" and use the
           **last** occurrence — PDs are signed immediately before
           publication so the signature date approximates the issue date.

        Returns ``None`` if no Greek date is found anywhere; the client
        layer should fall back to the IA item metadata date.
        """

        def parse_match(m: re.Match[str]) -> date | None:
            day_str, month_word, year_str = m.group(1), m.group(2).lower(), m.group(3)
            month = _GREEK_MONTHS.get(month_word)
            if not month:
                return None
            try:
                return date(int(year_str), month, int(day_str))
            except ValueError:
                return None

        # 1. Masthead scan
        head_lines = text.splitlines()[:15]
        for line in head_lines:
            for m in _RE_GREEK_DATE.finditer(line):
                d = parse_match(m)
                if d is not None:
                    return d

        # 2. Whole-document signature scan — last hit wins
        last: date | None = None
        for m in _RE_GREEK_DATE.finditer(text):
            d = parse_match(m)
            if d is not None:
                last = d
        return last

    @staticmethod
    def _extract_title(text: str) -> str:
        """Pull a human title from the first ~30 lines of the law.

        FEK A' lays out the title across multiple lines: the rank line
        ("ΝΟΜΟΣ ΥΠ' ΑΡΙΘ. 4172"), then a subtitle paragraph describing
        what the law does. We concatenate the rank line + the next
        non-structural lines until we hit "Ο ΠΡΟΕΔΡΟΣ" or similar.

        For Απόφαση-type acts (treaty ratifications, parliament plenary
        decisions) the rank line is "ΑΠΟΦΑΣΕΙΣ" or similar; we use the
        same capturing logic so the subtitle still ends up in the title.

        Latin/Greek look-alike normalisation is applied during matching
        only — the captured title preserves the original characters.
        """
        lines = [ln.strip() for ln in text.splitlines()[:30] if ln.strip()]
        title_parts: list[str] = []
        capturing = False
        for line in lines:
            norm = _normalize_title_chars(line)
            if (
                _RE_NOMOS_TITLE.search(norm)
                or _RE_PD_TITLE.search(norm)
                or _RE_PNP_TITLE.search(norm)
                or _RE_SYNTAGMA_TITLE.search(norm)
                or _RE_KANONISMOS_TITLE.search(norm)
                or _RE_PYS_TITLE.search(norm)
                or _RE_APOFASI_VOULIS.search(norm)
                or (not capturing and _RE_PD_PLURAL.search(norm))
                or (not capturing and _RE_APOFASI_HEAD.match(norm))
            ):
                capturing = True
                title_parts.append(line)
                continue
            if not capturing:
                continue
            if any(line.startswith(p) for p in _PREAMBLE_LINES):
                break
            if _RE_ARTICLE.match(line) or _RE_KEFALAIO.match(_normalize_title_chars(line)):
                break
            title_parts.append(line)
            # Stop after we've collected a reasonable subtitle (~3 lines)
            if len(title_parts) >= 4:
                break
        return " ".join(title_parts).strip()

    @staticmethod
    def _collect_amend_refs(text: str) -> list[tuple[str, str]]:
        """Collect cross-references to other laws and decrees.

        Stored under ``extra.amends`` so downstream consumers can render
        an "amends/amended-by" backlink section without having to re-scan
        the Markdown body.

        Sort order: by **year descending then number descending** so the
        most recent references survive the per-field length cap. This
        matters because amendment chains tend to reference the latest
        legislation; alphabetical sort would lose 2012-2020 refs first.
        """
        # Collect (kind, number, year) so we can sort numerically
        triples: set[tuple[str, int, int]] = set()
        for m in _RE_LAW_REF.finditer(text):
            try:
                triples.add(("nomos", int(m.group(1)), int(m.group(2))))
            except ValueError:
                continue
        for m in _RE_PD_REF.finditer(text):
            try:
                triples.add(("pd", int(m.group(1)), int(m.group(2))))
            except ValueError:
                continue
        if not triples:
            return []

        # Year DESC, kind ASC (laws before PDs), number DESC
        ordered = sorted(triples, key=lambda t: (-t[2], t[0], -t[1]))
        # Frontmatter cap: ~600 chars worth of refs (≈ 35-40 entries).
        # The full list lives in the body — this is a quick-access index.
        formatted = [f"{kind}:{num}/{year}" for kind, num, year in ordered]
        capped: list[str] = []
        running_len = 0
        for ref in formatted:
            if running_len + len(ref) + 1 > 600:
                break
            capped.append(ref)
            running_len += len(ref) + 1
        return [("amends", ",".join(capped))]
