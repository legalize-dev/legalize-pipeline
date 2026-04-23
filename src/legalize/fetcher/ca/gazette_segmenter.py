"""Segment an extracted Canada Gazette Part III PDF into per-chapter events.

A Gazette Part III issue bundles multiple Acts (each a "chapter") into a
single PDF. Each chapter starts on a dedicated cover page that carries,
in a predictable layout:

    STATUTES OF CANADA {YEAR}

    CHAPTER {N}

    {Title of the Act — typically starting "An Act to …"}

    ASSENTED TO
    {MONTH DAY, YEAR}

    BILL {C- or S-number}

After the cover page the full bill text follows, section by section,
until the next CHAPTER cover. Our segmenter walks the per-page text
stream from :class:`GazetteExtraction`, detects cover pages, extracts
their metadata, and emits a :class:`ChapterSegment` per chapter with
``(metadata, body_en, body_fr)``.

The segmenter is tolerant of:

- Whitespace variance ("CHAPTER  1" vs "CHAPTER 1\n"): normalized before
  matching.
- Assent date format variance: "ASSENTED TO MARCH 13, 2020" vs
  "ASSENTED TO 13 MARCH 2020" (older issues). Both map to a ``date``.
- Missing bill number: older chapters occasionally lack the "BILL C-N"
  line (it's optional). We leave the field empty and move on.

What it does NOT do:

- Match the same chapter across EN and FR columns. Both are segmented
  independently using the same page indices because the cover layout is
  parallel — if the EN column says CHAPTER 3 on page 72, the FR column
  agrees on page 72. We return both columns' text for the same page-range,
  trusting the bilingual layout's structural alignment.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date

from legalize.fetcher.ca.pdf_extractor import GazetteExtraction

logger = logging.getLogger(__name__)


# "CHAPTER 1" / "CHAPTER  12" — must be on its own line for the cover
# detection to fire. We guard with a max chapter cap of 999 to avoid
# false positives from mid-body references ("chapter 5 of the Act").
_COVER_CHAPTER_RE = re.compile(r"^\s*CHAPTER\s+(\d{1,3})\s*$", re.MULTILINE)

# Issue cover statement: "Chapters 1 to 4" / "Chapter 1" — used to
# discover the *first* chapter number when the PDF omits an explicit
# "CHAPTER 1" marker (older issues structured the first chapter to flow
# directly from the TOC without a separator page).
_ISSUE_CHAPTERS_RE = re.compile(r"Chapters?\s+(\d{1,3})(?:\s+to\s+(\d{1,3}))?", re.IGNORECASE)

# Assent date line. Modern (1998+) issues print the cover page as
# "ASSENTED TO MARCH 13, 2020" (all caps, month-day-year, no brackets).
# Older issues and the body of each chapter use the typeset
# "[Assented to 31st March, 1998]" form (mixed case, ordinal, brackets,
# day-month-year). We match both. The ordinal suffix (st/nd/rd/th) is
# optional so "[Assented to 1 April 1999]" works too.
_ASSENT_RE_LONG = re.compile(
    r"ASSENTED\s+TO\s+(?P<month>[A-Z]+)\s+(?P<day>\d{1,2})\s*,?\s*(?P<year>\d{4})",
    re.IGNORECASE,
)
_ASSENT_RE_SHORT = re.compile(
    r"ASSENTED\s+TO\s+(?P<day>\d{1,2})\s+(?P<month>[A-Z]+)\s+(?P<year>\d{4})",
    re.IGNORECASE,
)
_ASSENT_RE_BRACKETED = re.compile(
    r"\[\s*Assented\s+to\s+(?P<day>\d{1,2})\s*(?:st|nd|rd|th)?\s+"
    r"(?P<month>[A-Za-z]+)\s*,?\s*(?P<year>\d{4})\s*\]",
    re.IGNORECASE,
)

# Bill number: "BILL C-4", "BILL S-17", tolerant of interior whitespace
# ("BILL C - 4") and en/em dashes printed in older issues.
_BILL_RE = re.compile(r"BILL\s+([CS])\s*[-–—]\s*(\d+[A-Z]?)", re.IGNORECASE)

# Month name → number, English (Gazette's standard).
_MONTHS: dict[str, int] = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


@dataclass(frozen=True)
class ChapterSegment:
    """One Act within a Gazette issue, with its bilingual text and metadata."""

    chapter: int
    year: int
    assent_date: date
    bill_number: str
    title_en: str
    title_fr: str
    body_en: str
    body_fr: str
    first_page: int
    last_page: int


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def _parse_assent(text: str) -> date | None:
    """Return the assent date from a chapter's text, or None.

    Tries the three observed formats: all-caps cover ("ASSENTED TO MARCH
    13, 2020"), all-caps day-month ("ASSENTED TO 13 MARCH 2020"), and the
    typeset bracketed form ("[Assented to 31st March, 1998]") that
    appears both on older covers and inside modern chapter bodies.
    """
    m = (
        _ASSENT_RE_BRACKETED.search(text)
        or _ASSENT_RE_LONG.search(text)
        or _ASSENT_RE_SHORT.search(text)
    )
    if not m:
        return None
    month = _MONTHS.get(m.group("month").lower())
    if not month:
        return None
    try:
        return date(int(m.group("year")), month, int(m.group("day")))
    except ValueError:
        return None


def _first_chapter_from_issue(text: str) -> int | None:
    """Return the first chapter number in the issue, from the cover line.

    The cover page usually reads ``Chapters 1 to 4`` — we want the ``1``
    so we can prepend an implicit chapter 1 segment when the body flows
    directly from the TOC without its own ``CHAPTER 1`` marker.
    """
    m = _ISSUE_CHAPTERS_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _parse_bill(text: str) -> str:
    m = _BILL_RE.search(text)
    if not m:
        return ""
    # Normalize to a tight "C-4" / "S-17" form regardless of printed whitespace.
    return f"{m.group(1).upper()}-{m.group(2).upper()}"


def _extract_title(cover_text: str, lang: str) -> str:
    """Pick the title line(s) from a cover page.

    The title sits between the "CHAPTER N" line and the "ASSENTED TO" line
    (or "BILL" line if assent is absent). Old issues run the title across
    2-3 lines; modern ones occasionally pack it onto one. We join those
    lines with single spaces and trim.
    """
    lines = [line.strip() for line in cover_text.splitlines() if line.strip()]
    try:
        # Find the CHAPTER line index.
        chap_idx = next(
            i
            for i, line in enumerate(lines)
            if re.match(r"^CHAPTER\s+\d", line, re.IGNORECASE)
            or re.match(r"^CHAPITRE\s+\d", line, re.IGNORECASE)
        )
    except StopIteration:
        return ""

    # Title starts after CHAPTER (and optionally after a "STATUTES OF…"
    # header that appears before the chapter number).
    title_lines: list[str] = []
    for line in lines[chap_idx + 1 :]:
        # Stop at the assent marker or the bill marker. Handles both the
        # modern "ASSENTED TO" cover format and the older "[Assented to …]"
        # bracketed form that appears directly under the title.
        upper = line.upper()
        if upper.startswith(("ASSENTED TO", "[ASSENTED TO", "SANCTIONNÉE", "SANCTIONNEE")):
            break
        if upper.startswith("BILL ") or upper.startswith("PROJET DE LOI"):
            break
        # Skip the regnal-year line ("68-69 Elizabeth II, 2019-2020") if it
        # appears between CHAPTER and the title — some issues interleave it.
        if re.match(r"^\d+[- ]\d+\s+[A-Z][a-z]+\s+[IVX]+,\s+\d{4}", line):
            continue
        title_lines.append(line)

    title = " ".join(title_lines).strip()
    # Trim trailing punctuation noise that sometimes appears on cover
    # pages (single dots, en-dashes).
    title = re.sub(r"\s*[-–—.]\s*$", "", title).strip()
    return title


# ─────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────


def segment(
    extraction: GazetteExtraction,
    *,
    issue_year: int | None = None,
) -> list[ChapterSegment]:
    """Split ``extraction`` into per-chapter segments.

    Parameters
    ----------
    extraction:
        The :class:`GazetteExtraction` produced by
        :func:`pdf_extractor.extract_text_from_pdf`.
    issue_year:
        The year stamped on the issue cover (``Statutes of Canada, 2020``).
        Used as a fallback when a chapter's cover page lacks an explicit
        assent year — rare but observed in older issues. Callers usually
        know the year from the filename they downloaded.
    """
    pages = extraction.pages
    if not pages:
        return []

    # 1. Find page indices where "CHAPTER N" opens a new cover.
    #    Modern issues (2005+) print "CHAPTER N" as a running header on
    #    every body page of that chapter, so we dedupe by chapter number:
    #    the FIRST occurrence is the cover, subsequent hits are running
    #    headers and should be ignored.
    cover_pages: list[tuple[int, int]] = []  # (page_idx, chapter_number)
    seen_chapters: set[int] = set()
    for page in pages:
        m = _COVER_CHAPTER_RE.search(page.text_en)
        if m:
            num = int(m.group(1))
            if num in seen_chapters:
                continue
            seen_chapters.add(num)
            cover_pages.append((page.index, num))

    # 2. Synthesize an implicit chapter 1 cover if the first explicit
    #    cover isn't the lowest chapter stated on the issue's title page.
    #    Older issues (pre-2005 roughly) flow chapter 1 directly from the
    #    TOC with no separator page.
    first_chapter_declared = _first_chapter_from_issue(pages[0].text_en)
    if first_chapter_declared is not None and (
        not cover_pages or cover_pages[0][1] > first_chapter_declared
    ):
        # Find the first body page: skip the title page + TOC page (usually 0-1).
        # A "body" page is one that contains the first chapter's content —
        # typically carrying "SUMMARY" or "TABLE OF PROVISIONS" as its
        # first headline. We use the first page after the title that
        # contains a recognised SUMMARY token as the synthetic cover.
        for p in pages[1:]:
            head = p.text_en.split("\n", 1)[0].strip().upper()
            if head.startswith(("SUMMARY", "TABLE OF PROVISIONS", "PREAMBLE")):
                cover_pages.insert(0, (p.index, first_chapter_declared))
                break
        else:
            # Fallback: assume body starts at page 2.
            if len(pages) > 2:
                cover_pages.insert(0, (2, first_chapter_declared))

    if not cover_pages:
        return []

    # 2. Walk adjacent covers to define each chapter's page range.
    segments: list[ChapterSegment] = []
    for i, (start, chapter_num) in enumerate(cover_pages):
        end = cover_pages[i + 1][0] - 1 if i + 1 < len(cover_pages) else len(pages) - 1

        cover_en = pages[start].text_en
        cover_fr = pages[start].text_fr

        assent = _parse_assent(cover_en) or _parse_assent(cover_fr)
        if assent is None:
            if issue_year is None:
                logger.debug(
                    "Chapter %d: no assent date found and no issue_year fallback",
                    chapter_num,
                )
                continue
            # Fall back to Jan 1 of the issue year — a rough but valid date
            # so the event can still be committed.
            assent = date(issue_year, 1, 1)

        bill = _parse_bill(cover_en) or _parse_bill(cover_fr)
        title_en = _extract_title(cover_en, "en")
        title_fr = _extract_title(cover_fr, "fr")

        body_en = "\n\n".join(p.text_en for p in pages[start : end + 1] if p.text_en)
        body_fr = "\n\n".join(p.text_fr for p in pages[start : end + 1] if p.text_fr)

        segments.append(
            ChapterSegment(
                chapter=chapter_num,
                year=assent.year,
                assent_date=assent,
                bill_number=bill,
                title_en=title_en,
                title_fr=title_fr,
                body_en=body_en,
                body_fr=body_fr,
                first_page=start,
                last_page=end,
            )
        )

    return segments
