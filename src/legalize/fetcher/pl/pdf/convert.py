"""PDF of an act of the Dziennik Ustaw -> paragraphs, footnotes, Markdown.

Vendored from eli2md 0.6.17 (eli2md/pdf.py), https://github.com/PolskiAgentW/eli2md, MIT licence.
Changes: OCR left out (no tesseract here), no front matter, ruff rules of this repository
(``l`` -> ``ln``, ``zip(strict=False)``, ruff format). Otherwise the code is eli2md's; fixes belong there first.
"""

# eli2md module docstring:
# Convert a born-digital Dziennik Ustaw PDF into paragraphs + footnotes.
#
# Layout facts this relies on (checked on 2024 acts, see eval/):
# - page 1 starts with the gazette masthead ending with a line "Poz. N";
# - later pages start with a running header "Dziennik Ustaw – N – Poz. N";
# - footnotes sit below a thin horizontal rule (a ~144pt wide rect) in 9pt type;
# - footnote markers are superscripts in ~6pt type;
# - paragraphs are separated by a larger vertical gap than lines within a paragraph.
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field, replace

import pdfplumber
import pdfplumber.page
from pdfplumber.utils import extract_words
from pdfplumber.utils.text import WordExtractor


class _PlacedTags(pdfplumber.page.PDFPageAggregatorWithMarkedContent):
    """pdfplumber keeps no stack of marked content: an EMC resets the tag to None. Word formulas in a placed
    PDF nest "/Span <</ActualText …>> BDC … EMC" inside "/PlacedPDF BDC", so after the first formula the rest
    of the placed page lost its tag and skipped the ink test: its hidden copy went into the output, mixed
    with the visible text (DU/2026/40 p. 2-5: 7860 of 22175 placed chars; 10 of 118 acts with Cambria Math in
    2025-2026, none in a random 300). Here everything inside /PlacedPDF is tagged PlacedPDF; other tags are
    as in pdfplumber."""

    def begin_tag(self, tag, props=None):
        super().begin_tag(tag, props)
        self._stack = getattr(self, "_stack", []) + [self.cur_tag]
        if "PlacedPDF" in self._stack:
            self.cur_tag = "PlacedPDF"

    def end_tag(self):
        self._stack = getattr(self, "_stack", [])[:-1]
        super().end_tag()
        if "PlacedPDF" in self._stack:
            self.cur_tag = "PlacedPDF"


pdfplumber.page.PDFPageAggregatorWithMarkedContent = (
    _PlacedTags  # looked up by Page when it parses a page
)

RUNNING_HEADER = re.compile(
    r"^(?:Dziennik Ustaw|Monitor Polski)\s*[–-]\s*\d+\s*[–-]\s*Poz\.\s*\d+\s*$"
)
# "Pozycja 19": MP 2012 up to poz. 130; ") Poz. 1024*": the last act of a year has a note "*) Ostatnia pozycja"
MASTHEAD_END = re.compile(r"^[*)\s]*Poz(?:\.|ycja)\s*\d+[*)\s]*$")
SUP_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"  # unit numbers may carry them: Art. 41¹., 5²)
# Letters of an index ("Art. 22¹ᵃ."): Unicode modifier letters a-z; there is none for q.
SUP_LETTERS = "ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ"
SUP_CHARS = SUP_DIGITS + SUP_LETTERS
# Lines that start a new unit even without a vertical gap (used at page breaks).
UNIT_START = re.compile(
    rf"^(Art\.\s*\d|§\s*\d|\d+[a-z]*[{SUP_CHARS}]*\.\s|\d+[a-z]*[{SUP_CHARS}]*\)\s|[a-z]{{1,3}}\)\s|–\s|Rozdział\s|DZIAŁ\s|Oddział\s|Załącznik)"
)
UNIT_START_Q = re.compile(
    "^„?" + UNIT_START.pattern[1:]
)  # also a quoted unit of an amendment: „1. Treść
ITEM_START = re.compile(
    rf"^„?(Art\.\s*\d|§\s*\d|\d+[a-z]*[{SUP_CHARS}]*\)\s|[a-z]{{1,3}}\)\s)"
)  # not "1." / "–"
POINT_START = re.compile(rf"^„?(\d+[a-z]*[{SUP_CHARS}]*\)\s|[a-z]{{1,3}}\)\s)")  # "1)", "a)" only
LOWER = "a-ząćęłńóśźż"
ANNEX = re.compile(r"^Załącznik")
ANNEX_UNDER_SIGNATURE = re.compile(r"^„?(?:Załącznik|ZAŁĄCZNIK)")
INK_DPI, INK_LEVEL = 100, 180  # render resolution; gray level above which a box has no ink
DUP_TOL = 0.3  # pt; a char drawn twice repeats within this distance (<= 0.1pt in DU/2025/1095; see _dedupe)
MATH = re.compile("[\U0001d400-\U0001d7ff]")
CID = re.compile(
    r"\(cid:\d+\)"
)  # a glyph the PDF font does not map to Unicode (pdfminer's placeholder)
FOOTNOTE_MARK = re.compile(r"^\d{1,3}\)?[,.;:]?$")
FOOTNOTE_TYPE = 9.5  # pt; footnotes are set in 9pt, body text in 10pt
# Small digits without ")" are not footnote markers but unit numbers (Art. 41¹), units (m²)
# or chemical subscripts (P₂O₅). Kept as Unicode super/subscript digits.
SUPER = str.maketrans("0123456789abcdefghijklmnoprstuvwxyz", SUP_CHARS)
SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
# Index of a unit number in small raised type right after the number: "22" + "1a" (2025 prints: Art. 22¹ᵃ.),
# "479" + "[30f]" (2026 prints use brackets, also for digits: "§ 4[1]", DU/2026/468). Written as superscripts
# without the brackets, so both prints give "Art. 479³⁰ᶠ." ("1" alone is a script digit, see FOOTNOTE_MARK).
INDEX = re.compile(r"^(?:\[(\d{1,3}[a-z]{0,3})\]|(\d{1,3}[a-z]{1,3}))$")
SIGNATURE = re.compile(r"^[A-ZŁŚŻ][\w ]{2,80}: (\w{1,3}\. )+[A-ZŁŚŻ][\w-]+$")
IMAGE_TEXT_CHARS = (
    30  # more text-layer chars than this over an image: the image is a background, not read by OCR
)
# Dz.U. (and M.P.) up to 2011 came out in numbered issues: the page header names the issue ("Dziennik Ustaw Nr 150
# — 9307 — Poz. 1255, 1256 i 1257", DU/2005/1255), the first page of an issue has "Nr 115" under the masthead
# (DU/2002/994). Those years set acts in two columns; from 2012 there are no issues and one column.
OLD_HEADER = re.compile(r"^(?:Dziennik\s*Ustaw|Monitor\s*Polski)\s*Nr\s*\d+")
OLD_MASTHEAD = re.compile(r"^(?:DZIENNIK\s*USTAW|MONITOR\s*POLSKI)")
OLD_ISSUE = re.compile(r"^Nr\s*\d+$")
GUTTER = (
    6.0,
    20.0,
)  # pt; the gap between the columns is 11.3-12 pt in DU 2000-2011 (DU/2005/1255, DU/2011/1134)
DASH_RULE = re.compile(
    r"[—–-]{3,}"
)  # the rule over the footnotes of a QuarkXPress page (DU 2000-2009)
# An act of an issue starts with its position number alone in a row, bold, centred on the page: 14 pt Univers-BoldPL
# (DU 2000-2008: "1255" at x 282-313 above "USTAWA", DU/2005/1255 p. 1), 12 pt in 2009 (DU/2009/1323) and in the
# InDesign issues of 2010-2011 (UniversPro-Bold, DU/2011/1134); body text is 10 pt or less.
ACT_NUMBER = re.compile(r"^\d{1,4}$")
ACT_NUMBER_SIZE = 11.5  # pt
ACT_NUMBER_NEXT = 20  # the next act's number is at most this far above the act's own (an issue's positions run on)


@dataclass
class Line:
    page: int
    top: float
    bottom: float
    x0: float
    size: float
    text: str
    pw: float = 595.0
    ph: float = 842.0
    mark: str = ""  # "notext" | "image": position marker for content that is not text; "ocr": text read by OCR
    x1: float = 0.0
    right: float = 0.0  # right edge of justified text in this frame (0 = unknown)
    lead: float = -1.0  # usual gap between lines in this frame (-1 = unknown)
    band: int = 0  # two-column pages (see _bands): full-width rows are odd bands, the text in columns even ones
    col: int = 0  # 1 = left, 2 = right column of a two-column band; 0 = read across the page
    act: int = 0  # the line is the position number that starts an act on a page of an old issue (ACT_NUMBER)
    old: bool = False  # the line is on a page of an issue of 2011 or earlier (_old_issue)


@dataclass
class Block:
    kind: str  # "p" | "signature" | "annex" (annex header) | "notext" | "image" | "ocr" (see Line.mark)
    text: str
    page: int


@dataclass
class Document:
    masthead: list[str] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    footnotes: list[str] = field(default_factory=list)
    footnote_pages: list[int] = field(
        default_factory=list
    )  # page of each footnote (numbering may restart)
    no_text_pages: list[int] = field(
        default_factory=list
    )  # e.g. scanned pages: their content is lost
    image_pages: list[int] = field(
        default_factory=list
    )  # pages with text and large images (forms, drawings)
    ocr_pages: list[int] = field(
        default_factory=list
    )  # pages without text whose OCR text is included
    unmapped_pages: list[int] = field(
        default_factory=list
    )  # text layer mostly without Unicode, kept without it
    # pages with text whose large image is a scan of text read by OCR (also in image_pages, not in ocr_pages)
    image_ocr_pages: list[int] = field(default_factory=list)
    ocr_engine: str = ""  # e.g. "tesseract 5.5.0"
    ocr_langs: dict[int, str] = field(default_factory=dict)  # page -> tesseract language(s) used

    @property
    def paragraphs(self) -> list[str]:
        return [b.text for b in self.blocks]

    def main_blocks(self) -> list[Block]:
        """Blocks before the first annex header."""
        out = []
        for b in self.blocks:
            if b.kind == "annex":
                break
            out.append(b)
        return out

    def annex_blocks(self) -> list[Block]:
        return self.blocks[len(self.main_blocks()) :]


def _char_angle(c: dict) -> int:
    """Writing direction of a char in degrees (0, 90, 180, 270), from its text matrix."""
    a, b = c["matrix"][0], c["matrix"][1]
    return round(math.degrees(math.atan2(b, a)) / 90) % 4 * 90


def _watermark(c: dict) -> bool:
    """A char of the invisible diagonal stamp "www.rcl.gov.pl" over pages of MP 2012 (MP/2012/596, 988):
    marked as an Artifact and written at ~55 degrees. Its letters landed inside words and paragraphs and
    hid the running header ("l Monitor Polski – 2 – Poz. 596 p"). Text of the act is never diagonal."""
    if c.get("tag") != "Artifact" or "matrix" not in c:
        return False
    deg = math.degrees(math.atan2(c["matrix"][1], c["matrix"][0])) % 90
    return 10 < deg < 80


def _drop_watermark(page):
    if not any(_watermark(c) for c in page.chars):
        return page
    return page.filter(lambda o: not (o.get("object_type") == "char" and _watermark(o)))


def _doubled(c: dict) -> bool:
    """A glyph whose ToUnicode maps to its character twice: Word exports Cambria Math so, one 𝑘 reads "𝑘𝑘"
    (DU/2026/1236 p. 10, "kk" in 0.6.3; poppler reads it doubled too). Only mathematical alphanumerics (also
    math Greek 𝜂) in a font named *Math*: in DU+MP 2025-2026 all 16 991 doubled chars of Cambria Math are such
    (19 acts), while doubled chars of text fonts are ligatures ("ff", "tt"; eval/math_glyphs_0.6.4.dev.md)."""
    t = c["text"]
    return (
        len(t) == 2 and t[0] == t[1] and bool(MATH.match(t)) and "Math" in (c.get("fontname") or "")
    )


def _single_glyphs(page):
    """Chars of `_doubled` glyphs get their one character. Changes the page's char dicts in place (pdfplumber
    caches them, so filtered pages and extract_words see the change)."""
    for c in page.chars:
        if _doubled(c):
            c["text"] = c["text"][0]
    return page


def _to_frame(o: dict, rot: int, w: float, h: float) -> dict:
    """Map an object's bbox into a frame where text written at `rot` degrees runs left-to-right."""
    x0, x1, t, b = o["x0"], o["x1"], o["top"], o["bottom"]
    if rot == 90:  # text runs bottom-to-top; the landscape top is on the left
        x0, x1, t, b = h - b, h - t, x0, x1
    elif rot == 270:
        x0, x1, t, b = t, b, w - x1, w - x0
    elif rot == 180:
        x0, x1, t, b = w - x1, w - x0, h - b, h - t
    out = {
        **o,
        "x0": x0,
        "x1": x1,
        "top": t,
        "bottom": b,
        "doctop": t,
        "width": x1 - x0,
        "height": b - t,
    }
    if "matrix" in o:  # pdfminer's size of a rotated glyph is its advance, not the font size
        out.update(upright=True, size=math.hypot(o["matrix"][0], o["matrix"][1]))
    return out


def _glyph_box(c: dict, mb_x0: float = 0.0) -> tuple[float, float, float, float]:
    """(x0, top, x1, bottom) of a char, with its box moved onto the glyph if the font's descent is implausible.

    pdfminer's box reaches from the baseline down by the font's /Descent. Cambria declares -2464/1000 (the
    FontBBox of its math glyphs), so the box of a 10.8 pt char lies 16-27 pt below the baseline, on the next
    line (MP/2025/1128). A box with more than 3/4 of it below the baseline is moved up to 0.3 below it (usual
    descents are 0.2-0.4; a lowered subscript adds its rise, which the matrix does not show).
    """
    x0, t, x1, b = c["x0"], c["top"], c["x1"], c["bottom"]
    _, _, u, v, e, f = c["matrix"]  # (u, v): the glyph's up direction on the page
    if not (u or v) or (abs(u) > 1e-3 * abs(v) and abs(v) > 1e-3 * abs(u)):
        return x0, t, x1, b  # neither upright nor turned by a multiple of 90 degrees
    if abs(v) > abs(u):
        lo, hi, base, up = c["y0"], c["y1"], f, v > 0
    else:
        lo, hi, base, up = x0 - mb_x0, x1 - mb_x0, e, u > 0
    size = hi - lo
    below = (base - lo if up else hi - base) / size if size > 0 else 0.0
    if below <= 0.75:
        return x0, t, x1, b
    d = (below - 0.3) * size  # shift towards the glyph's top
    if abs(v) > abs(u):
        return (x0, t - d, x1, b - d) if up else (x0, t + d, x1, b + d)
    return (x0 + d, t, x1 + d, b) if up else (x0 - d, t, x1 - d, b)


def _drop_hidden_placed(page):
    """Drop text of a placed PDF (annex) that is not visible on the page.

    Annexes are often placed PDFs; the gazette covers their original heading with its own and
    hides the placed copy (clipping path or white box), which pdfminer ignores (DU/2024/144, 458).
    A placed char is hidden if the rendered page has no ink in its box, or if it lies under
    the gazette's own text (then the ink test cannot tell the two copies apart).
    """
    placed = [c for c in page.chars if c.get("tag") == "PlacedPDF"]
    own = [c for c in page.chars if c.get("tag") != "PlacedPDF"]
    if not placed or not own:
        return page
    own_words = extract_words(own)
    boxes = [(w["x0"] - 3, w["top"] - 3, w["x1"] + 3, w["bottom"] + 3) for w in own_words]
    # the gazette's running header band; a placed page reaching into it is clipped there (DU/2024/1337)
    header_bottom = max(
        (w["bottom"] for w in own_words if w["bottom"] < 0.1 * page.height), default=0
    )
    scale = INK_DPI / 72
    img = page.to_image(resolution=INK_DPI).original.convert("L")
    mb_x0 = page.mediabox[0]

    def hidden(c: dict) -> bool:
        gx0, gt, gx1, gb = _glyph_box(c, mb_x0)
        cx, cy = (gx0 + gx1) / 2, (gt + gb) / 2
        if cy < header_bottom or any(x0 <= cx <= x1 and t <= cy <= b for x0, t, x1, b in boxes):
            return True
        if not c["text"].strip():
            return False
        crop = img.crop(
            (int(gx0 * scale), int(gt * scale), int(gx1 * scale) + 1, int(gb * scale) + 1)
        )
        return crop.getextrema()[0] > INK_LEVEL

    drop = {id(c) for c in placed if hidden(c)}
    return page.filter(lambda o: id(o) not in drop) if drop else page


def _dedupe(chars: list[dict], tol: float = DUP_TOL) -> list[dict]:
    """Drop chars drawn twice (bold is sometimes drawn twice; seen on rotated table pages): the same
    glyph (text, font, size) within `tol` of a kept one in both axes. pdfplumber's dedupe_chars chains
    positions within 1pt across the page, which in small rotated print (3.9pt) merged distinct letters
    and spaces of a line (MP/2025/541: "wyposażnie", "ratownicyi personelsą"). Overlapping text of
    another size is not a copy (MP/2025/1142: "decyzję" over a 'd' of 10.9pt)."""
    kept: dict[tuple, list[dict]] = {}
    out = []
    for c in chars:
        key = (c["text"], c.get("fontname"), round(c["size"], 1), round(c["x0"]), round(c["top"]))
        near = (
            o
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for o in kept.get((*key[:3], key[3] + dx, key[4] + dy), ())
        )
        if not any(abs(o["x0"] - c["x0"]) <= tol and abs(o["top"] - c["top"]) <= tol for o in near):
            kept.setdefault(key, []).append(c)
            out.append(c)
    return out


QUARK_GAP = (
    1.0,
    2.2,
)  # pt; a word ends at a wider gap in a Quark text font, in its bold (see _QuarkWords)


def _quark_gap(c: dict) -> float | None:
    """The word gap of a char of the fonts of the QuarkXPress issues (DU 2000-2009: "Univers-PL", "Univers-BoldPL";
    MAC_PL_FONT), None for other chars."""
    f = c.get("fontname") or ""
    if not MAC_PL_FONT.search(f) or not c.get("upright", True):
        return None
    return QUARK_GAP[1] if "Bold" in f else QUARK_GAP[0]


class _QuarkWords(WordExtractor):
    """Words of a Quark page. The space after a one-letter word ("z dnia", "w art.", "i wywozem") is not a char
    there but a gap of 1.5-3 pt (DU/2009/1323 p. 1), mostly under pdfplumber's x_tolerance of 3 pt: "zdnia",
    "wart.". Measured on the first 6 pages of 11 Quark acts of 2000-2009, gaps between chars of a line without a
    space char: in the text fonts letters of a word are at most 0.3 pt apart, words at least 1.47 pt; in the bold
    letter-spaced titles ("U S T A W A", DU/2005/684) letters are up to 1.5 pt apart, words ("o Służbie", DU/2009/1323)
    at least 2.78 pt."""

    def char_begins_new_word(
        self, prev_char, curr_char, direction, x_tolerance, y_tolerance
    ) -> bool:
        a, b = _quark_gap(prev_char), _quark_gap(curr_char)
        if (
            a
            and b
            and curr_char["x0"] - prev_char["x1"] > max(a, b)
            and abs(curr_char["top"] - prev_char["top"]) <= y_tolerance
        ):
            return True
        return super().char_begins_new_word(
            prev_char, curr_char, direction, x_tolerance, y_tolerance
        )


def _frames(page) -> list[tuple[list[dict], float, float, list[dict]]]:
    """(words, width, height, rects) per writing direction, dominant direction first.

    Landscape tables are printed on portrait pages with text rotated by 90 degrees; such a
    page is read in a rotated frame. Pages with mostly upright text are read as before.
    """
    angles = Counter(_char_angle(c) for c in page.chars)
    # the footnote rule is usually a rect; some PDFs draw it as a line (DU/2024/1346, DU/2024/1018)
    rects = page.rects + [{**x, "line": True} for x in page.lines]
    if not angles or angles.most_common(1)[0][0] == 0:
        words = page.extract_words(extra_attrs=["size"], keep_blank_chars=False)
        if any(_quark_gap(c) for c in page.chars) and _old_issue(_rows(words), float(page.height)):
            words = _QuarkWords(extra_attrs=["size"], keep_blank_chars=False).extract_words(
                page.chars
            )
        return [(words, float(page.width), float(page.height), rects)]
    frames = []
    w, h = float(page.width), float(page.height)
    for rot, _ in angles.most_common():
        chars = _dedupe([_to_frame(c, rot, w, h) for c in page.chars if _char_angle(c) == rot])
        fw, fh = (h, w) if rot in (90, 270) else (w, h)
        words = extract_words(chars, extra_attrs=["size"], keep_blank_chars=False)
        frames.append((words, fw, fh, [_to_frame(r, rot, w, h) for r in rects]))
    return frames


def _unmapped_share(page) -> float:
    chars = page.chars
    return sum(1 for c in chars if c["text"].startswith("(cid:")) / len(chars) if chars else 0.0


def _large_image(page, min_share: float = 0.1) -> float | None:
    """Top of the largest image if images cover at least min_share of the page, else None."""
    area, best = 0.0, None
    for im in page.images:
        w = max(0.0, min(page.width, im["x1"]) - max(0.0, im["x0"]))
        h = max(0.0, min(page.height, im["bottom"]) - max(0.0, im["top"]))
        area += w * h
        if best is None or w * h > best[0]:
            best = (w * h, max(0.0, im["top"]))
    return best[1] if best and area >= min_share * page.width * page.height else None


def _largest_image_box(page) -> tuple[float, float, float, float] | None:
    """(x0, top, x1, bottom) of the largest image, clipped to the page."""
    best = None
    for im in page.images:
        x0, x1 = max(0.0, im["x0"]), min(float(page.width), im["x1"])
        top, bottom = max(0.0, im["top"]), min(float(page.height), im["bottom"])
        if x1 > x0 and bottom > top and (best is None or (x1 - x0) * (bottom - top) > best[0]):
            best = ((x1 - x0) * (bottom - top), (x0, top, x1, bottom))
    return best[1] if best else None


MAC_PL_FONT = re.compile(
    r"PL$"
)  # QuarkXPress fonts of Dz.U. 2000–2010: "Univers-PL", "Univers-BoldPL"
PL_LETTERS = set("ąćęłńśźżĄĆĘŁŃŚŹŻ")


def _mac_pl(page):
    """Dz.U. 2000–2010 (QuarkXPress) set Polish letters in fonts "…PL" with MacCE codes, but the PDF reads the codes
    as MacRoman: "og∏oszenia", "ROZPORZÑDZENIE". Chars of those fonts are decoded again, where that gives a Polish
    letter (the other codes, e.g. "±", may be what the font prints)."""
    for c in page.chars:
        if not c["text"].isascii() and MAC_PL_FONT.search(c.get("fontname", "")):
            try:
                t = c["text"].encode("mac_roman").decode("mac_latin2")
            except UnicodeError:
                continue
            if t in PL_LETTERS:
                c["text"] = t
    return page


def _page_lines(page, pno: int, gut: dict | None = None) -> tuple[list[Line], list[Line]]:
    """Return (body_lines, footnote_lines) for one page."""
    body, notes = [], []
    _mac_pl(page)
    for k, (words, fw, fh, rects) in enumerate(
        _frames(_drop_hidden_placed(_drop_watermark(_single_glyphs(page))))
    ):
        b, n = _frame_lines(words, fw, fh, rects, pno, gut)
        if k > 0:
            b = [ln for ln in b if not RUNNING_HEADER.match(ln.text)]
        body += b
        notes += n
    return body, notes


def _rows(words: list[dict]) -> list[list[dict]]:
    """Group words into lines: vertical overlap with the line's first word and similar size."""
    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        mid = (w["top"] + w["bottom"]) / 2
        for r in rows:
            if r[0]["top"] - 1 <= mid <= r[0]["bottom"] + 1 and abs(r[0]["size"] - w["size"]) < 2:
                r.append(w)
                break
        else:
            rows.append([w])
    return rows


def _old_issue(rows: list[list[dict]], ph: float) -> bool:
    """The page belongs to a gazette issue of 2011 or earlier: its header or masthead names the issue (OLD_HEADER).
    Only such pages are looked at for columns, so the pages of 2012 on are read as before."""
    texts = [
        " ".join(w["text"] for w in sorted(r, key=lambda w: w["x0"]))
        for r in rows
        if r[0]["top"] < 0.2 * ph
    ]
    return any(OLD_HEADER.match(t) for t in texts) or (
        any(OLD_MASTHEAD.match(t) for t in texts) and any(OLD_ISSUE.match(t) for t in texts)
    )


def _gutter(
    rows: list[list[dict]], pw: float, words: list[dict] = (), gut: dict | None = None
) -> tuple[float, float] | None:
    """(gl, gr): the right edge of the left column and the left edge of the right column of a page set in two
    columns, or None.

    The columns are justified: full lines of the left column end at one x left of the middle (292.0 in DU/2005/1255
    p. 1), and in a printed row the right column, if any, starts across the gutter. The margins are symmetric
    (37.9 and 557.4 there), so the right column starts at left margin + right margin - gl (303.3) even where its
    lines are all indented (points of a list, DU/2009/1323 p. 1). The page header spans the margins where both
    columns are indented (amendments, DU/2011/1430 p. 3); otherwise the leftmost right part of a row is the edge
    (DU/2011/1134 p. 2). It takes 3 rows whose left part is a line of text (from the left half's start, no gap
    wider than the type: not cells of a table) ending at gl. A smaller word in a gap fills it: the footnote marker of
    "a)²⁾ zarobkowego" (DU/2008/1342 p. 5, a short column over a page of footnotes).
    gut (see convert): 2 rows do where the gutter is the one of the act's other pages, gut["doc"] (the first page of
    DU/2004/959: 3 lines of columns over a page of footnotes); such a page is noted in gut["cands"] until it is known."""
    rows = [sorted(r, key=lambda w: w["x0"]) for r in rows]

    def filled(x: dict, y: dict) -> bool:
        return any(
            x["x1"] - 1 <= w["x0"]
            and w["x1"] <= y["x0"] + 1
            and w["x1"] - w["x0"] > 0.5 * (y["x0"] - x["x1"])
            and x["top"] - x["size"] < w["top"] < x["bottom"]
            and w["size"] < x["size"] - 0.5
            for w in words
        )

    starts, ends = (
        Counter(round(r[0]["x0"]) for r in rows),
        Counter(round(r[-1]["x1"]) for r in rows),
    )
    head = [r for r in rows if OLD_HEADER.match(" ".join(w["text"] for w in r))]
    lm = [x for x, n in starts.items() if n >= 3] + [round(r[0]["x0"]) for r in head]
    rm = [x for x, n in ends.items() if n >= 3] + [round(r[-1]["x1"]) for r in head]
    if not lm or not rm:
        return None
    left = min(r[0]["x0"] for r in rows if round(r[0]["x0"]) == min(lm))
    right = max(r[-1]["x1"] for r in rows if round(r[-1]["x1"]) == max(rm))
    # the middle of the text, not of the page: pages 576 pt wide keep the text where it is on 595 pt (DU/2000/839:
    # margins 39.3 and 560.3, the left column ends at 293.8)
    mid = max(0.5 * pw, (left + right) / 2)
    edges: dict[
        float, list[tuple[float, float]]
    ] = {}  # gl (0.5 pt) -> (x1 of a left part, x0 of the right part)
    for r in rows:
        for k, a in enumerate(r):
            b = r[k + 1] if k + 1 < len(r) else None
            if not (0.4 * pw < a["x1"] < mid) or (b is not None and b["x0"] - a["x1"] < GUTTER[0]):
                continue
            part = r[: k + 1]
            if (
                part[0]["x0"] > left + 0.5 * (a["x1"] - left)
                or len(part) < 3
                or any(
                    y["x0"] - x["x1"] > a["size"] and not filled(x, y)
                    for x, y in zip(part, part[1:], strict=False)
                )
            ):
                continue
            edges.setdefault(round(a["x1"] * 2) / 2, []).append(
                (a["x1"], b["x0"] if b else math.inf)
            )
    for c in sorted(
        edges, key=lambda c: -sum(len(v) for x, v in edges.items() if abs(x - c) <= 0.5)
    ):
        xs = [x for v in edges.values() for x in v if abs(x[0] - c) <= 0.8]
        gl = max(x for x, _ in xs)
        gr = min(left + right - gl, *(x for _, x in xs))
        if not GUTTER[0] <= gr - gl <= GUTTER[1]:
            continue
        if len(xs) >= 3:
            return gl, gr
        if len(xs) == 2 and gut is not None:
            if (doc := gut.get("doc")) and abs(gl - doc[0]) <= 1 and abs(gr - doc[1]) <= 1:
                return gl, gr
            gut["cands"].append((gl, gr))
    return None


def _bands(words: list[dict], gl: float, gr: float):
    """Function word -> (band, column) on a two-column page.

    Full-width rows (a word crosses the gutter: header, position number, title, footnotes of Quark pages) and the
    runs of column text between them alternate down the page; several acts may share it (DU/2005/1255 p. 1).
    Bands are numbered down the page, full-width rows odd; in an even band the left column (1) is read before the
    right one (2). An even band with no word ending at the left column's edge (a table, short lines) is read row
    by row (column 0). A word crosses the gutter if it reaches 2 pt into it from both sides: a hyphen or quote
    may stick out of a justified column (optical margins)."""
    spans: list[list[float]] = []
    for t, b in sorted(
        (w["top"], w["bottom"]) for w in words if w["x0"] < gr - 2 and w["x1"] > gl + 2
    ):
        if spans and t <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([t, b])

    def band(w: dict) -> int:
        mid = (w["top"] + w["bottom"]) / 2
        for k, (t, b) in enumerate(spans):
            if mid < t:
                return 2 * k
            if mid <= b:
                return 2 * k + 1
        return 2 * len(spans)

    split = {band(w) for w in words if abs(w["x1"] - gl) <= 1} - {
        2 * k + 1 for k in range(len(spans))
    }

    def key(w: dict) -> tuple[int, int]:
        k = band(w)
        return (k, (1 if w["x0"] + w["x1"] < gl + gr else 2) if k in split else 0)

    return key


def _index_words(r: list[dict], big: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split a row of small words into (other words, indices). An index matches INDEX, starts right after a
    normal-size word ending with a letter or digit and sits above that word's middle: "479" + "[30f]".
    Index text is returned without brackets ("30f")."""
    words: list[dict] = []
    for w in sorted(r, key=lambda w: w["x0"]):
        prev = words[-1] if words else None
        if (
            prev
            and re.fullmatch(r"\[\d{1,3}[a-z]{0,3}", prev["text"])
            and w["text"] == "]"
            and w["x0"] - prev["x1"] < 1.0
        ):  # "[92" + "]" in another size (DU/2026/468 p. 103)
            words[-1] = {**prev, "text": prev["text"] + "]", "x1": w["x1"]}
        elif m := re.fullmatch(r"(\[\d{1,3}[a-z]{0,3}\])(\d{1,3}\)[,.;:]?)", w["text"]):
            # index + footnote marker in one word: "ust. 1 i 1[1]10)" (DU/2026/913 p. 44)
            cut = w["x0"] + (w["x1"] - w["x0"]) * len(m.group(1)) / len(w["text"])
            words += [{**w, "text": m.group(1), "x1": cut}, {**w, "text": m.group(2), "x0": cut}]
        else:
            words.append(w)
    rest, idx = [], []
    for w in words:
        m = INDEX.match(w["text"])
        mid = (w["top"] + w["bottom"]) / 2
        if m and any(
            -1.0 < w["x0"] - n["x1"] < 1.5
            and n["top"] - 1 < mid < (n["top"] + n["bottom"]) / 2
            and n["text"][-1:].isalnum()
            for n in big
        ):
            idx.append({**w, "text": m.group(1) or m.group(2)})
        else:
            rest.append(w)
    rest.sort(
        key=lambda w: (w["top"], w["x0"])
    )  # the order of _rows: attach order decides ties (DU/2024/1089)
    return rest, idx


def _frame_lines(
    words: list[dict], pw: float, ph: float, rects: list[dict], pno: int, gut: dict | None = None
) -> tuple[list[Line], list[Line]]:
    if not words:
        return [], []
    sizes = Counter()
    for w in words:
        sizes[round(w["size"], 1)] += len(w["text"])
    body_size = sizes.most_common(1)[0][0]
    # a page of an old issue mostly of footnotes (DU/2004/959 p. 1: 3 lines of text over them, and a table of
    # contents in 9 pt higher up): the body type is the one just above the row of dashes over the footnotes, or the
    # markers in 7.5 pt would be text beside 9 pt footnotes
    for sep in [
        w for w in words if DASH_RULE.fullmatch(w["text"]) and w["x1"] - w["x0"] < 0.3 * pw
    ]:
        above = Counter()
        for w in words:
            if sep["top"] - 100 <= w["top"] and w["bottom"] <= sep["top"]:
                above[round(w["size"], 1)] += len(w["text"])
        if (
            sum(above.values()) >= 60
            and above.most_common(1)[0][0] > body_size
            and _old_issue(_rows(words), ph)
        ):
            body_size = above.most_common(1)[0][0]
            break
    sup_limit = body_size * 0.75
    # markers of 7.5 pt in 10 pt text of an old issue are small (DU/2004/959); figures of 7.5 pt in a table of 2025
    # are not (DU/2025/1057)
    if any(sup_limit <= w["size"] < sup_limit + 0.05 for w in words) and _old_issue(
        _rows(words), ph
    ):
        sup_limit += 0.05

    # Cluster words into lines. Superscripts attach to the line they overlap vertically.
    # Small words: footnote markers ("1)"), whole lines of small print, or sub/superscripts in
    # formulas. Markers and formula scripts are attached to the nearest normal line.
    normal = [w for w in words if w["size"] >= sup_limit]
    big = list(normal)
    attach: list[tuple[dict, dict]] = []  # (small word, flag) to attach to the nearest normal line
    for r in _rows([w for w in words if w["size"] < sup_limit]):
        # indices are scripts even when a line has several: "Art. 479[30f]. … art. 479[30a]–479[30e]"
        r, idx = _index_words(r, big)
        attach += [(w, {"script": True, "index": True}) for w in idx]
        if not r:
            continue
        text = [w for w in r if not FOOTNOTE_MARK.match(w["text"])]
        words_ = [w for w in text if not MATH.search(w["text"])]  # formula scripts are math italic
        if (len(r) >= 3 and words_) or sum(len(w["text"]) for w in words_) >= 15:
            normal += r
            continue
        for w in r:
            if not FOOTNOTE_MARK.match(w["text"]):
                continue
            close = next(
                (x for x in text if x["text"] == ")" and 0 <= x["x0"] - w["x1"] < 1.5), None
            )
            if close is not None and ")" not in w["text"]:  # marker extracted as "1" + ")"
                text.remove(close)
                w = {**w, "text": w["text"] + ")", "x1": close["x1"]}
            attach.append((w, {"sup": True} if ")" in w["text"] else {"script": True}))
        attach += [(w, {}) for w in text]
    rows = _rows(normal)
    old = _old_issue(rows, ph)
    key = None  # word -> (band, column) on a two-column page (DU 2000-2011)
    if old and (gutter := _gutter(rows, pw, words, gut)):
        if gut is not None:
            gut["found"].append(gutter)
        key = _bands(normal, *gutter)
        groups: dict[tuple[int, int], list[dict]] = {}
        for w in normal:
            groups.setdefault(key(w), []).append(w)
        rows = [
            r for k in sorted(groups) for r in _rows(groups[k])
        ]  # the columns' baselines differ (DU/2011/1134)
    # rows (by id, before small words are attached) that are the number of an act starting here: see ACT_NUMBER
    # centred on the text between the columns (a page 576 pt wide has it at 299.8, DU/2000/839), else on the page
    centre2 = gutter[0] + gutter[1] if key else pw
    acts = {
        id(r): int(r[0]["text"])
        for r in rows
        if old
        and len(r) == 1
        and ACT_NUMBER.match(r[0]["text"])
        and r[0]["size"] >= ACT_NUMBER_SIZE
        and abs(r[0]["x0"] + r[0]["x1"] - centre2) < 20
    }
    # where they are in reading order (band, column, top): footnotes of an act lie above the next act's number
    starts = sorted((*(key(r[0]) if key else (0, 0)), r[0]["top"]) for r in rows if id(r) in acts)

    def dist(r: list[dict], s: dict) -> float:
        return abs((r[0]["top"] + r[0]["bottom"]) / 2 - s["bottom"])

    for s, flag in attach:
        best = min(
            rows if key is None else [r for r in rows if key(r[0]) == key(s)],
            key=lambda r: dist(r, s),
            default=None,
        )
        if key is not None and (
            best is None or dist(best, s) >= 12
        ):  # e.g. a marker in a band of its own
            best = min(rows, key=lambda r: dist(r, s), default=None)
        if best is not None and abs((best[0]["top"] + best[0]["bottom"]) / 2 - s["bottom"]) < 12:
            best.append({**s, **flag})
        else:
            rows.append([{**s, **flag}])

    rule_top = None
    for r in rects:
        if r["height"] < 1.5 and 130 < r["width"] < 160 and r["x0"] < pw * 0.2 and _free(r, rects):
            # A rule drawn as a line, or one high on a page of footnotes only (DU/2024/1539 p. 2 at 25%
            # of the page), counts only with nothing but footnote type below it (DU/2024/1346 p. 1).
            below = [w for w in words if w["top"] > r["top"]]
            small = bool(below) and all(w["size"] < FOOTNOTE_TYPE for w in below)
            if (r["top"] > ph * 0.3 and not r.get("line")) or (r["top"] > ph * 0.1 and small):
                rule_top = r["top"] if rule_top is None else min(rule_top, r["top"])
    # Two-column page: footnote rules as ((band, column), top). Under a rule are the lines of its column below it and
    # the bands further down; the other column of its band goes on beside the footnotes.
    col_rules: list[
        tuple[tuple[int, int], float, bool]
    ] = []  # (band, column), top, the bands further down too
    seps = []  # the rows of dashes over the footnotes of a Quark page

    def under(
        k: tuple[int, int], top: float, wk: tuple[int, int], wtop: float, down: bool = True
    ) -> bool:
        # not past the number of the next act: its footnotes sit under its text, above the next act's number
        # (DU/2005/1369 p. 2: "———" at top 331 in the left column, notes, "1370" at 447, its own "———" at 612)
        return (
            wtop > top
            and (wk == k or down and wk[0] > k[0])
            and not any((*k, top) < s <= (*wk, wtop) for s in starts)
        )

    if key is not None:
        for r in rects:
            # InDesign pages (DU 2010-2011): a ~70 pt line at a column's edge, footnotes under it in the column
            # (DU/2011/1170 p. 2), also high on the page (DU/2010/626 p. 3), or across the page (ibid. p. 4)
            # (only its column if the bands further down are text: an annex under it, DU/2010/277 p. 6)
            if r["height"] < 1.5 and 50 < r["width"] < 160 and _free(r, rects):
                for down in (True, False):
                    below = [w for w in words if under(key(r), r["top"], key(w), w["top"], down)]
                    if below and all(w["size"] < FOOTNOTE_TYPE for w in below):
                        col_rules.append((key(r), r["top"], down))
                        break
        for r in rows:
            # QuarkXPress pages (DU 2000-2009): footnotes across the page under a row "———————" in the left
            # column (DU/2009/1323 p. 1)
            if (
                DASH_RULE.fullmatch("".join(w["text"] for w in r))
                and r[0]["x1"] - r[0]["x0"] < 0.3 * pw
            ):
                # only its column if the bands further down are text: an annex under the footnotes of both columns
                # (DU/2005/1468 p. 4)
                for down in (True, False):
                    below = [
                        w for w in words if under(key(r[0]), r[0]["bottom"], key(w), w["top"], down)
                    ]
                    # the dashes are set in body type or, in a column, in footnote type (DU/2005/1468 p. 4: 9 pt)
                    if below and all(w["size"] < max(r[0]["size"], body_size) - 0.5 for w in below):
                        seps.append(r)
                        col_rules.append((key(r[0]), r[0]["top"], down))
                        break

    body, notes = [], []
    head: Line | None = None  # the last line of an annex header of an old issue (see below)
    for r in rows:
        if any(r is s for s in seps):  # a rule, not text
            continue
        r.sort(key=lambda w: w["x0"])
        parts: list[tuple[str, bool]] = []  # (text, glued to the previous word)
        base = [w for w in r if not w.get("sup") and not w.get("script")]
        mid = sum((w["top"] + w["bottom"]) / 2 for w in base) / len(base) if base else None
        for k, w in enumerate(r):
            if w.get("sup"):
                m = re.match(r"^(\d+)\)?(.*)$", w["text"])
                parts.append((f"[^{m.group(1)}]{m.group(2)}", True))
            elif w.get(
                "index"
            ):  # "30f" -> "³⁰ᶠ"; as printed if a char has no superscript form ("[1q]")
                sup = w["text"].translate(SUPER)
                parts.append((sup if all(c in SUP_CHARS for c in sup) else f"[{w['text']}]", True))
            elif w.get("script"):
                up = mid is None or (w["top"] + w["bottom"]) / 2 < mid
                parts.append((w["text"].translate(SUPER if up else SUB), True))
            else:  # "Art. 41¹.", "art. 63[^59]," : punctuation after a script or marker is a separate word
                after_small = (
                    k > 0
                    and (r[k - 1].get("script") or r[k - 1].get("sup"))
                    and w["x0"] - r[k - 1]["x1"] < 1.0
                )
                parts.append((w["text"], bool(after_small)))
        text = ""
        for p, glued in parts:
            text = p if not text else text + p if glued else text + " " + p
        normal_words = [w for w in r if not w.get("sup") and not w.get("script")] or r
        band, col = key(normal_words[0]) if key else (0, 0)
        line = Line(
            page=pno,
            top=min(w["top"] for w in normal_words),
            bottom=max(w["bottom"] for w in normal_words),
            x0=min(w["x0"] for w in r),
            size=Counter(round(w["size"], 1) for w in normal_words).most_common(1)[0][0],
            text=" ".join(_plain_math(CID.sub(" ", text)).split()),
            pw=pw,
            ph=ph,
            x1=max(w["x1"] for w in normal_words),
            band=band,
            col=col,
            act=acts.get(id(r), 0),
            old=old,
        )
        is_note = (
            (rule_top is not None and line.top > rule_top)
            or (rule_top is None and line.size < body_size - 0.5 and line.top > ph * 0.6)
            or any(under(k, t, (band, col), line.top, down) for k, t, down in col_rules)
        )
        # an annex header of an old issue set small in a column, with the line under it, is not a footnote
        # (DU/2002/664 p. 4: "Załącznik do obwieszczenia Marszałka Sejmu Rzeczypospolitej" / "Polskiej z dnia … (poz. 664)"
        # in 8 pt under the signature)
        if old and (
            ANNEX.match(line.text)
            or head is not None
            and (band, col) == (head.band, head.col)
            and abs(line.size - head.size) < 0.5
            and 0 <= line.top - head.bottom < head.size
        ):
            is_note, head = False, line
        else:
            head = None
        if line.text:  # a line of unmapped glyphs only is empty now
            (notes if is_note else body).append(line)
    body.sort(
        key=lambda ln: (ln.band, ln.col, ln.top)
    )  # down the page; a band's left column before its right one
    notes.sort(key=lambda ln: (ln.band, ln.col, ln.top))
    for c in sorted(
        {ln.col for ln in body}
    ):  # each column has its own right edge (292 and 557 in DU/2005/1255)
        lines = [ln for ln in body if ln.col == c]
        ends = Counter(round(ln.x1) for ln in lines if len(ln.text) >= 40)
        gaps = Counter(
            round(2 * (b.top - a.bottom)) / 2
            for a, b in zip(lines, lines[1:], strict=False)
            if abs(a.size - b.size) < 0.5 and 0 <= b.top - a.bottom < a.size
        )
        for ln in lines:
            if ends and ends.most_common(1)[0][1] >= 3:
                ln.right = ends.most_common(1)[0][0]
            if gaps and gaps.most_common(1)[0][1] >= 3:
                ln.lead = gaps.most_common(1)[0][0]
    return body, notes


def _free(r: dict, rects: list[dict]) -> bool:
    """The footnote rule stands alone. A table border of the same size meets other borders at its ends."""
    for x in rects:
        if x is r or not x["top"] - 2 <= r["top"] <= x["bottom"] + 2:
            continue
        if (
            min(
                abs(x["x0"] - r["x1"]),
                abs(x["x1"] - r["x0"]),
                abs(x["x0"] - r["x0"]),
                abs(x["x1"] - r["x1"]),
            )
            < 2
        ):
            return False
    return True


def _plain_math(text: str) -> str:
    """Map Unicode mathematical alphanumerics (e.g. 𝑊𝑌𝐷 in formulas) to plain letters."""
    return "".join(
        unicodedata.normalize("NFKC", c) if "\U0001d400" <= c <= "\U0001d7ff" else c for c in text
    )


def _join(prev: str, nxt: str) -> str:
    if re.search(rf"[{LOWER}]-$", prev) and re.match(rf"[{LOWER}]", nxt):
        return prev[:-1] + nxt
    if re.search(r"\w-$", prev) and re.match(
        r"-\w", nxt
    ):  # "rolno-" "-środowiskowy": the hyphen is repeated
        return prev + nxt[1:]
    return prev + " " + nxt


def _continuation_gaps(body: list[Line]) -> dict[int, float]:
    """Per page: usual gap before a line that continues a paragraph (starts with a lower-case letter and not
    with "a) "), relative to the font size; pages with fewer than 5 such lines are left out. Most pages set
    lines at 0.2 of the size; some at 0.6–0.75 (DU/2024/853, annex of DU/2024/440), which the fixed 0.45 split
    into one block per line. Per page, because forms in annexes are spaced out (DU/2024/1542). The lower
    quartile, not the median: paragraphs may start with a lower-case word too (clauses of a court
    resolution "po rozpoznaniu…", "z udziałem…" in DU/2024/1883), and their gaps are larger."""
    ratios: dict[int, list[float]] = {}
    for a, b in zip(body, body[1:], strict=False):
        if (
            a.page == b.page
            and abs(a.size - b.size) < 0.5
            and 0 <= b.top - a.bottom < a.size
            and re.match(rf"[{LOWER}]", b.text)
            and not UNIT_START.match(b.text)
        ):
            ratios.setdefault(b.page, []).append((b.top - a.bottom) / a.size)
    return {p: sorted(r)[len(r) // 4] for p, r in ratios.items() if len(r) >= 5}


POINT_LABEL = re.compile(r"^„?(\d+|[a-z])\)\s")


def _follows(a: str, b: str) -> bool:
    """Line b starts with the point label right after the one line a starts with: "1)" -> "2)", "a)" -> "b)"."""
    ma, mb = POINT_LABEL.match(a), POINT_LABEL.match(b)
    if not ma or not mb:
        return False
    x, y = ma.group(1), mb.group(1)
    if x.isdigit() and y.isdigit():
        return int(y) == int(x) + 1
    return not x.isdigit() and not y.isdigit() and ord(y) == ord(x) + 1


def _segment(body: list[Line]) -> list[Block]:
    """Group lines into blocks (paragraphs): by the vertical gap (relative to font size and to the usual
    gap on the page), at page breaks by content. Annex headers and signatures always start a block."""
    blocks: list[Block] = []
    # a new block needs a gap above 0.45 of the font size, or clearly above the usual continuation gap
    split = {p: max(0.45, g + 0.1) for p, g in _continuation_gaps(body).items()}
    cur: Block | None = None
    prev: Line | None = None
    for ln in body:
        kind = "p"
        if ln.mark:
            kind = ln.mark
        elif (
            ANNEX.match(ln.text)
            and (ln.x0 > 0.4 * ln.pw and ln.top < 0.2 * ln.ph)
            or ln.old
            and cur is not None
            and cur.kind == "signature"
            and ANNEX_UNDER_SIGNATURE.match(ln.text)
        ):
            # in an old issue the annex (a consolidated text) starts under the signature, mid-page (DU/2010/648 p. 6),
            # also as the new text of an annex of the amended act (DU/2004/895 p. 9: "„ZAŁĄCZNIK — Część I")
            kind = "annex"
        elif SIGNATURE.match(ln.text) and ln.x0 > 0.45 * ln.pw:
            kind = "signature"
        if prev is None or cur is None:
            new = True
        elif kind != "p" or cur.kind in ("signature", "notext", "image", "ocr", "unmapped"):
            new = not (kind == "annex" and cur.kind == "annex" and ln.page == prev.page)
        elif cur.kind == "annex":
            # right-aligned continuation lines of an annex header ("z dnia ... (poz. N)")
            new = not (
                ln.page == prev.page
                and ln.x0 > 0.4 * ln.pw
                and ln.top - prev.bottom < 0.8 * ln.size
            )
        elif ln.page != prev.page or (prev.col == 1 and ln.col == 2 and ln.band == prev.band):
            # a page break, or the break from the bottom of the left column to the top of the right one
            new = bool(UNIT_START.match(ln.text)) or bool(re.search(r"[.:;”]$", prev.text))
        else:
            # Some PDFs set units with little extra space (2 pt over the usual gap between lines, not 6),
            # or none: then a unit starts after a line that ends short of the right margin (the last line
            # of a justified paragraph).
            # On pages set with wide line spacing units and paragraphs often have no more space than other lines
            # (DU/2024/1442, 440): there "1)", "a)", "Art. 1", "§ 1" at a line start begin a unit, "1." and "–" only
            # after a sentence end, and a line that ends short of the right margin ends its paragraph.
            gap, limit = ln.top - prev.bottom, split.get(ln.page, 0.45)
            short = 0 < prev.x1 < prev.right - 2 * prev.size
            # "2)", "b)" after a short line start a point even without ";" before: points in a table cell
            # set with the usual line gap (MP/2025/121). So does "2)" right below a one-line "1)" whose row
            # also holds the next cell ("1) B1.1, B1.3, B2, C   483", ibid.). Not after a hyphen ("impedan-"
            # "cji) i", MP/2025/910), nor after an overlapping line or one of another size: footnote markers
            # read as "1)" in tables (MP/2025/541).
            point = (
                (short or (_follows(prev.text, ln.text) and abs(ln.x0 - prev.x0) < 1))
                and bool(POINT_START.match(ln.text))
                and gap >= 0
                and abs(ln.size - prev.size) < 0.5
                and not prev.text.endswith("-")
            )
            new = (
                gap > limit * ln.size
                or (limit > 0.45 and short)
                or bool(UNIT_START_Q.match(ln.text))
                and (
                    (prev.lead >= 0 and gap > prev.lead + 1.2)
                    or (short and bool(re.search(r"[.:;,”]$", prev.text)))
                    or point
                    or (
                        limit > 0.45
                        and (
                            bool(ITEM_START.match(ln.text))
                            or bool(re.search(r"[.:;,”]$", prev.text))
                        )
                    )
                )
            )
        if new:
            if cur is not None:
                blocks.append(cur)
            cur = Block(kind, ln.text, ln.page)
        else:
            cur.text = _join(cur.text, ln.text)
        prev = ln
    if cur is not None:
        blocks.append(cur)
    return blocks


# The last page of an issue of 2011 or earlier ends with the publisher's colophon ("Wydawca: Kancelaria Prezesa Rady
# Ministrów" … "ISSN 0867-3411", DU/2000/291) or is a publisher's notice ("Szanowni Państwo!" … prices of subscriptions,
# DU/2003/577), above a bare page number "— 4096 —"
# "Szanowni Państwo" also without "!" over an advertisement for Monitor Polski B (DU/2002/933 p. 3)
COLOPHON = re.compile(r"^(?:Wydawca\s*:|Szanowni\s+Państwo(?:!|$))")
ISSN = re.compile(r"\bISSN\s*\d{4}\s*-\s*\d{3}[\dX]\b")
BARE_PAGE_NUMBER = re.compile(r"^[—–-]\s*\d+\s*[—–-]$")


def _drop_colophon(body: list[Line], notes: list[Line]) -> tuple[list[Line], list[Line]]:
    """Body and footnote lines without the colophon of an issue (COLOPHON): it is not text of the act. Only on the
    last page, and only if that page names an ISSN; acts of 2012 on are single PDFs without it. The colophon may be
    set small, under the footnotes (DU/2000/291: "Wydawca: …" read as footnotes, "Cena 3 zł 96 gr" and the ISSN as
    body), so it starts at its first line in reading order, body or footnote."""
    if not body:
        return body, notes
    last = max(ln.page for ln in body + notes)
    lines = [ln for ln in body + notes if ln.page == last]
    starts = [(ln.band, ln.col, ln.top) for ln in lines if COLOPHON.match(ln.text)]
    if not starts or not any(ISSN.search(ln.text) for ln in lines):
        return body, notes
    at = min(starts)

    def keep(ln: Line) -> bool:
        return ln.page != last or (ln.band, ln.col, ln.top) < at

    body = [ln for ln in body if keep(ln)]
    if body and body[-1].page == last and BARE_PAGE_NUMBER.match(body[-1].text):
        body.pop()
    return body, [ln for ln in notes if keep(ln)]


def _own_act(
    body: list[Line], notes: list[Line], position: int
) -> tuple[list[Line], list[Line], int, int] | None:
    """The act numbered `position` out of pages it shares with other acts of its issue (DU 2000-2011): the PDF of
    a position holds whole pages, so also the end of the acts before it and the start of the ones after it
    (DU/2005/1255 p. 1 holds 1255, 1256 and 1257; DU/2005/1369 p. 2 ends 1369 and starts 1370 at top 447). Keeps
    the lines after the act's number (ACT_NUMBER) up to the next act's number, and the footnotes between them in
    reading order: a Quark page sets an act's footnotes under its text, above the next act's number (DU/2005/1369
    p. 2, DU/2007/1322 p. 1). The number itself is dropped: it is the position, as "Poz. N" closing the masthead of
    2012 on, which is not text of the act either. Returns (body, notes, first page, last page), or None if the
    act's number is not found (then nothing is cut)."""
    start = next((i for i, ln in enumerate(body) if ln.act == position), None)
    if start is None:
        return None
    end = next(
        (
            i
            for i in range(start + 1, len(body))
            if position < body[i].act <= position + ACT_NUMBER_NEXT
        ),
        len(body),
    )
    first, last = body[start], body[end] if end < len(body) else None

    def at(ln: Line) -> tuple:
        return ln.page, ln.band, ln.col, ln.top

    notes = [ln for ln in notes if at(first) < at(ln) and (last is None or at(ln) < at(last))]
    return body[start + 1 : end], notes, first.page, last.page if last else math.inf


# an act starting on a page of an old issue read by OCR: its number and type in one paragraph ("56 ROZPORZĄDZENIE
# PREZESA RADY MINISTRÓW z dnia …", DU/2000/56) or the number alone before the type ("57" + "ROZPORZĄDZENIE MINISTRA
# FINANSÓW"); the number is not a line of its own as in the text layer (ACT_NUMBER)
OCR_ACT_TYPE = (
    r"(?:ROZPORZĄDZENIE|USTAWA|OBWIESZCZENIE|UCHWAŁA|POSTANOWIENIE|ZARZĄDZENIE|OŚWIADCZENIE|UMOWA"
    r"|KONWENCJA|PROTOKÓŁ|WYROK|ORZECZENIE|TRAKTAT|POROZUMIENIE|KOMUNIKAT|DEKRET|INFORMACJA|AKT|STATUT"
    r"|REGULAMIN|ZAŁĄCZNIK)\b"
)
OCR_ACT_START = re.compile(rf"^(\d{{1,4}})(?:\s+(?={OCR_ACT_TYPE})|$)")


def convert(
    path: str, position: int | None = None, _doc_gutter: tuple[float, float] | None = None
) -> Document:
    """Pages without a text layer only get a note (this copy has no OCR).
    position: the act's position in the gazette (ELI "DU/2005/1255" -> 1255). On pages of issues of 2011 and
    earlier it cuts the act out of the pages it shares with other acts (see _own_act); None = no cut.
    Two-column pages of those issues: a page with too few full lines to find its gutter (the first page of an act
    over a page of footnotes) takes the gutter of the act's other pages; as it may come first, the PDF is then read
    again (_doc_gutter)."""
    doc = Document()
    gut = {"doc": _doc_gutter, "found": [], "cands": []}
    body: list[Line] = []
    notes: list[Line] = []
    with pdfplumber.open(path) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            b, n = _page_lines(page, pno, gut)
            layer = None  # text layer of a page mostly of glyphs without Unicode (forms, DU/2025/161): OCR first
            if _unmapped_share(page) > 0.1:
                layer, b, n = (b, n), [], []
            if pno == 1:
                for i, ln in enumerate(b):
                    if MASTHEAD_END.match(ln.text):
                        doc.masthead = [x.text for x in b[: i + 1]]
                        b = b[i + 1 :]
                        break
                else:  # an act of 2011 or earlier starts under the running header of its issue (DU/2005/1255)
                    if b and OLD_HEADER.match(b[0].text):
                        doc.masthead, b = [b[0].text], b[1:]
            elif b and (RUNNING_HEADER.match(b[0].text) or OLD_HEADER.match(b[0].text)):
                b = b[1:]
            if not b and not n:
                if layer and (layer[0] or layer[1]):
                    # no OCR or an unreadable one: the text layer without the unmapped glyphs beats a bare note
                    doc.unmapped_pages.append(pno)
                    b, n = layer
                    if b and RUNNING_HEADER.match(b[0].text):
                        b = b[1:]
                    b = [
                        Line(pno, 0.0, 0.0, 0.0, 1.0, "", page.width, page.height, mark="unmapped")
                    ] + b
                else:
                    doc.no_text_pages.append(pno)
                    b = [Line(pno, 0.0, 0.0, 0.0, 1.0, "", page.width, page.height, mark="notext")]
            elif (img := _large_image(page)) is not None:
                doc.image_pages.append(pno)
                m = [Line(pno, img, img, 0.0, 1.0, "", page.width, page.height, mark="image")]
                upright = all(ln.pw == page.width and ln.ph == page.height for ln in b)
                i = (
                    next((k for k, ln in enumerate(b) if ln.top > img), len(b))
                    if upright
                    else len(b)
                )
                b = b[:i] + m + b[i:]
            body.extend(b)
            notes.extend(n)
            page.close()  # pdfplumber caches every parsed page; 867-page acts exhausted 14 GB RAM

    if _doc_gutter is None and gut["cands"] and gut["found"]:
        common = Counter((round(a), round(b)) for a, b in gut["found"]).most_common(1)[0][0]
        g = next(g for g in gut["found"] if (round(g[0]), round(g[1])) == common)
        if any(abs(a - g[0]) <= 1 and abs(b - g[1]) <= 1 for a, b in gut["cands"]):
            return convert(path, position, _doc_gutter=g)
    body, notes = _drop_colophon(body, notes)
    if position is not None and (own := _own_act(body, notes, int(position))):
        body, notes, lo, hi = own
        for f in ("no_text_pages", "image_pages", "ocr_pages", "unmapped_pages", "image_ocr_pages"):
            setattr(
                doc, f, [p for p in getattr(doc, f) if lo <= p <= hi]
            )  # pages of the other acts only
        doc.ocr_langs = {p: v for p, v in doc.ocr_langs.items() if lo <= p <= hi}
    doc.blocks = _segment(body)

    doc.footnotes, doc.footnote_pages = _group_notes(notes)
    return doc


def _group_notes(notes: list[Line]) -> tuple[list[str], list[int]]:
    """Lines under the footnote rule -> footnotes ("[^3] text") and the page each starts on."""
    texts, pages = [], []
    cur, cur_page, item = None, 0, 0
    for ln in notes:
        point = re.match(r"^(\d+)\)\s", ln.text)
        # "Niniejsza ustawa:" + "1) wdraża…" + "2) służy…": points of a footnote (DU/2026/421), a paragraph each;
        # other lines "N) …" start a footnote whose marker is not set as a superscript
        if (
            cur is not None
            and point
            and int(point.group(1)) == item + 1
            and (item or cur.rstrip().endswith(":"))
        ):
            cur, item = cur + "\n\n" + ln.text, item + 1
        elif re.match(r"^\[\^\d+\]", ln.text) or point:
            if cur is not None:
                texts.append(cur)
                pages.append(cur_page)
            cur, cur_page, item = ln.text, ln.page, 0
        else:
            cur = ln.text if cur is None else _join(cur, ln.text)
            cur_page = cur_page or ln.page
    if cur is not None:
        texts.append(cur)
        pages.append(cur_page)
    return texts, pages


UNIT_HEAD = {
    "Art.": re.compile(rf"^(Art\.\s*\d+[a-z]*[{SUP_CHARS}]*\.)\s*(.*)$", re.S),
    "§": re.compile(rf"^(§\s*\d+[a-z]*[{SUP_CHARS}]*\.)\s*(.*)$", re.S),
}
# A quoted unit that opens with its ust. 1 or § 1 (codes): "„Art. 21. 1. Treść" -> "„Art. 21." + "1. Treść",
# "Art. 14t. § 1. Treść" -> "Art. 14t." + "§ 1. Treść"
QUOTED_UNIT = re.compile(
    rf"^(„?(?:Art\.|§)\s*\d+[a-z]*[{SUP_CHARS}]*\.)\s+(„?(?:§\s*)?\d+[a-z]*[{SUP_CHARS}]*\.\s.*)$",
    re.S,
)
# ” after minutes is the seconds sign in coordinates (16°41’56,70”), not a closing quote
SECONDS = re.compile(r"\d[’′']\s?\d+(?:[,.]\d+)?”")
# a quote that opens a block, possibly after the unit number: "„Art. 5.", "Art. 30. „1.", "1) „a)"
QUOTE_HEAD = re.compile(
    rf"^(?:(?:Art\.|§)\s*\d+[a-z]*[{SUP_CHARS}]*\.\s*|\d+[a-z]*[{SUP_CHARS}]*[.)]\s*|[a-z]{{1,3}}\)\s*)?[„“]"
)


ART_NUMBER_AT = re.compile(
    r"^Art\.\s*(\d+[a-z]*)\."
)  # the number of "Art. 2. W ustawie …" (quote_depths)
ART_DIGITS = re.compile(r"\d+")


def quote_depths(blocks: list[Block]) -> list[int]:
    """Quotation depth (opening minus closing marks) at the start of each block. Units inside
    quotes are provisions of another act (amendments, "przepisy nieobjęte tekstem jednolitym"),
    not units of this one. Only the first quoted unit carries the opening „, so the depth has to
    be carried over. Only a quote that opens the block (after an optional unit number) may run
    into the next blocks; one opened mid-sentence and left open is a typo in the source
    („zwany dalej „kodem;”) and ends with its block. Some PDFs close with ˮ (U+02EE);
    “ opens English quotes in forms.
    A quote the source did not close ends at the next article of this act: "Art. N." with N right after the last
    article outside quotes, and not the next of the articles at any depth inside them, unless the block before
    announces a quote (DU/2004/895: pkt 17 of Art. 1 ends "…z późn. zm.)." without "”;", then "Art. 2. W ustawie …")."""
    depths, d = [], 0
    top, inner, announced = (
        None,
        {},
        False,
    )  # last article number outside quotes / at each depth inside them
    for b in blocks:
        if b.kind == "annex":
            d, top, inner = 0, None, {}
        t = SECONDS.sub("", b.text)
        head = QUOTE_HEAD.match(t)
        art = None if head or b.kind == "ocr" else ART_NUMBER_AT.match(t)
        if (
            d
            and art
            and top
            and art.group(1).isdigit()
            and int(art.group(1)) == int(top) + 1
            and not announced
            and not any(
                int(ART_DIGITS.match(v).group()) in (int(top), int(top) + 1) for v in inner.values()
            )
        ):
            d = 0
        depths.append(d)
        if art and d == 0:
            top, inner = art.group(1), {}
        elif art:
            inner = {k: v for k, v in inner.items() if k < d} | {d: art.group(1)}
        elif head and (quoted := ART_NUMBER_AT.match(t[head.end() :])):
            inner = {k: v for k, v in inner.items() if k <= d} | {d + 1: quoted.group(1)}
        announced = t.rstrip().endswith(":")
        if b.kind == "ocr":  # OCR misreads quotes; its text is never a heading anyway
            continue
        carry, local = d, 0  # quotes open from earlier blocks / opened mid-block in this one
        for k, ch in enumerate(t):
            if ch in "„“":
                if head and k == head.end() - 1:
                    carry += 1
                else:
                    local += 1
            elif ch in "”ˮ":
                if local:
                    local -= 1
                else:
                    carry = max(0, carry - 1)
        d = carry
    return depths


def page_ranges(pages: list[int]) -> str:
    """[2, 3, 4, 7] -> 2-4, 7"""
    out: list[list[int]] = []
    for p in pages:
        if out and p == out[-1][1] + 1:
            out[-1][1] = p
        else:
            out.append([p, p])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in out)


def no_text_note(pages: list[int]) -> str:
    if len(pages) == 1:
        return (
            f"> [Strona {pages[0]} PDF nie ma czytelnej warstwy tekstowej (np. skan lub grafika). "
            "Jej treści tu nie ma, jest tylko w PDF.]"
        )
    return (
        f"> [Strony {page_ranges(pages)} PDF nie mają czytelnej warstwy tekstowej (np. skan lub grafika). "
        "Ich treści tu nie ma, jest tylko w PDF.]"
    )


def ocr_note(page: int, engine: str) -> str:
    return (
        f"> [Strona {page} PDF nie ma czytelnej warstwy tekstowej. Tekst poniżej odczytał OCR ({engine}). "
        "Może zawierać błędy i pomija grafikę. Wiążący jest PDF.]"
    )


def image_ocr_note(page: int, engine: str) -> str:
    return (
        f"> [Na stronie {page} PDF jest obraz tekstu (skan). Tekst poniżej odczytał z obrazu OCR ({engine}). "
        "Może zawierać błędy i pomija grafikę. Wiążący jest PDF.]"
    )


def _escape_text(text: str) -> str:
    """A text-layer paragraph that starts with > or # ("> 90 dni" in a table) must not become a quote block
    (the mark of OCR text) or a heading."""
    return "\\" + text if text[:1] in ">#" else text


def _escape_ocr(text: str) -> str:
    """OCR text is plain text: a leading #, >, |, [ or bullet must not become Markdown syntax.
    ("1. Tekst" stays as it is, like ust. in the text layer.)"""
    return "\\" + text if re.match(r"^([#>|\[]|[-*+]\s)", text) else text


FN_LABEL = re.compile(r"^\[\^(\d+)\]\s*(.*)$", re.S)


def _footnote_pages(doc: Document) -> dict[str, list[int]]:
    """Footnote number -> pages on which a footnote with that number is printed, in order."""
    occ: dict[str, list[int]] = {}
    for f, pg in zip(doc.footnotes, doc.footnote_pages or [0] * len(doc.footnotes), strict=False):
        if m := FN_LABEL.match(f):
            occ.setdefault(m.group(1), []).append(pg)
    return occ


def _fn_label(n: str, j: int) -> str:
    return n if j == 0 else f"{n}_{j + 1}"  # the 2nd footnote numbered 1 is [^1_2]


def _fix_refs(text: str, page: int, occ: dict[str, list[int]]) -> str:
    """Footnote numbering restarts in annexes and forms, so one number can label several footnotes.
    A marker refers to the one printed on the page where its block starts, or the nearest later one."""

    def sub(m: re.Match) -> str:
        pages = occ.get(m.group(1), [])
        if len(pages) < 2:
            return m.group(0)
        j = next((k for k, pg in enumerate(pages) if pg >= page), len(pages) - 1)
        return f"[^{_fn_label(m.group(1), j)}]"

    return re.sub(r"\[\^(\d+)\]", sub, text)


# A marker that opens a printed line ("„¹⁾ Niniejsza ustawa…", "¹⁾ Maksymalne zawartości…") labels a note printed
# in the text (explanations under an annex table, a footnote quoted by an amendment); a reference is glued to its word.
BODY_LABEL = re.compile(r"(?:^|(?<=\s))([„“]?)\[\^(\d+)\](?=\s)")
MARKER = re.compile(r"\[\^(\d+)\]")


def _printed(n: str) -> str:
    return n.translate(SUPER) + "⁾"  # "12" -> "¹²⁾", as printed


def _body_notes(doc: Document, occ: dict[str, list[int]]) -> Document:
    """Markers of notes printed in the text are not links to the footnotes: `[^1]` would point to the act's
    footnote 1 (DU/2025/1016: "Arsen[^1]" in an annex table to "Minister … kieruje działem"). They are printed
    as "¹⁾": the labels themselves, and in an annex the markers of the numbers it labels, unless that page has
    a footnote with the number. A marker with no footnote at all stays: its footnote may be lost (DU/2024/127)."""
    part, parts, labels = 0, [], {}
    for b in doc.blocks:
        part += b.kind == "annex"
        parts.append(part)
        if b.kind == "p":
            labels.setdefault(part, set()).update(m.group(2) for m in BODY_LABEL.finditer(b.text))

    def fix(b: Block, part: int) -> Block:
        text = BODY_LABEL.sub(lambda m: m.group(1) + _printed(m.group(2)), b.text)
        own = labels.get(part, set()) if part else set()
        text = MARKER.sub(
            lambda m: (
                _printed(m.group(1))
                if m.group(1) in own and b.page not in occ.get(m.group(1), [])
                else m.group(0)
            ),
            text,
        )
        return replace(b, text=text)

    return replace(
        doc,
        blocks=[
            fix(b, p) if b.kind == "p" and "[^" in b.text else b
            for b, p in zip(doc.blocks, parts, strict=False)
        ],
    )


def to_markdown(doc: Document) -> str:
    """Markdown body: one block per paragraph, top-level units (Art. or, if none, §) as h5."""
    occ = _footnote_pages(doc)
    doc = _body_notes(doc, occ)
    if any(len(v) > 1 for v in occ.values()):
        doc = replace(
            doc, blocks=[replace(b, text=_fix_refs(b.text, b.page, occ)) for b in doc.blocks]
        )
    depths = quote_depths(doc.blocks)
    # Top-level unit per part (main text, each annex): Art. if the part has an "Art. N." at depth 0, else §.
    # A paragraph "Art. 42 ust. 1 ustawy określa…" in an annex does not count (DU/2024/553).
    part, parts = 0, []
    for b in doc.blocks:
        part += b.kind == "annex"
        parts.append(part)
    with_art = {
        p
        for b, d, p in zip(doc.blocks, depths, parts, strict=False)
        if d == 0 and b.kind != "ocr" and UNIT_HEAD["Art."].match(b.text)
    }
    out = []
    run: list[int] = []  # consecutive pages without text get one note
    for i, b in enumerate(doc.blocks):
        if b.kind == "ocr":  # each OCR page (or image of text) starts with its own note
            if i == 0 or doc.blocks[i - 1].kind != "ocr" or doc.blocks[i - 1].page != b.page:
                lang = doc.ocr_langs.get(b.page)
                note = image_ocr_note if b.page in doc.image_ocr_pages else ocr_note
                out.append(note(b.page, f"{doc.ocr_engine}, {lang}" if lang else doc.ocr_engine))
            out.append(
                "> " + _escape_ocr(" ".join(b.text.split()))
            )  # a quote block: not the text layer
        elif b.kind == "notext":
            run.append(b.page)
            nxt = doc.blocks[i + 1] if i + 1 < len(doc.blocks) else None
            if not (nxt and nxt.kind == "notext" and nxt.page == b.page + 1):
                out.append(no_text_note(run))
                run = []
        elif b.kind == "unmapped":
            out.append(
                f"> [Na stronie {b.page} PDF większość znaków nie ma kodów Unicode (np. formularz). "
                "Tekst poniżej jest niepełny, pełna treść jest tylko w PDF.]"
            )
        elif b.kind == "image":
            out.append(
                f"> [Na stronie {b.page} PDF jest obraz (np. wzór, rysunek, skan). "
                "Jego treści tu nie ma, jest tylko w PDF.]"
            )
        elif b.kind == "annex":
            out.append("## " + b.text)
        elif b.kind == "signature":
            out.append("*" + b.text + "*")
        elif (
            depths[i] == 0
            and (m := UNIT_HEAD["Art." if parts[i] in with_art else "§"].match(b.text))
            and not m.group(2).startswith("„")
        ):
            out.append("##### " + m.group(1))
            if m.group(2):
                out.append(_escape_text(m.group(2)))
        elif m := QUOTED_UNIT.match(b.text):
            out += [m.group(1), m.group(2)]
        else:
            out.append(_escape_text(b.text))
    seen: Counter = Counter()
    for f in doc.footnotes:
        if m := FN_LABEL.match(f):
            text = m.group(2).replace(
                "\n\n", "\n\n    "
            )  # later paragraphs of a footnote are indented
            out.append(f"[^{_fn_label(m.group(1), seen[m.group(1)])}]: {text}")
            seen[m.group(1)] += 1
        else:
            out.append(f)
    return "\n\n".join(out) + "\n"
