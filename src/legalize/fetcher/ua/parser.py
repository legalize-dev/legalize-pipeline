"""Ukraine text and metadata parsers.

Text parser:  splits ``.txt`` plain text into Block objects using regex
              to detect articles (Стаття), chapters (Розділ/Глава), etc.
Metadata parser:  extracts structured metadata from ``.xml`` endpoint
              which returns HTML with ``<meta>`` tags.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

import lxml.html

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.fetcher.ua.discovery import nreg_to_identifier
from legalize.models import Block, NormMetadata, NormStatus, Paragraph, Rank, Version

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Rank mapping  (Ukrainian type → legalize rank)
# ─────────────────────────────────────────────

RANK_MAP: dict[str, str] = {
    "Конституція": "konstytutsiia",
    "Конституція України": "konstytutsiia",
    "Закон": "zakon",
    "Кодекс": "kodeks",
    "Кодекс України": "kodeks",
    "Указ": "ukaz",
    "Декрет": "dekret",
    "Постанова": "postanova",
    "Розпорядження": "rozporiadzhennia",
}

STAN_MAP: dict[str, NormStatus] = {
    "Чинний": NormStatus.IN_FORCE,
    "Нечинний": NormStatus.REPEALED,
    "Втратив чинність": NormStatus.REPEALED,
    "Не набрав чинності": NormStatus.IN_FORCE,
}

# ─────────────────────────────────────────────
# Text parsing helpers
# ─────────────────────────────────────────────

# Article heading: "Стаття 1." or "Стаття 361-1. Title text"
_ARTICLE_RE = re.compile(r"^Стаття\s+(\d+(?:[-‑‒–—]\d+)*)\s*\.?\s*(.*)$", re.UNICODE)

# Chapter/section heading: "Розділ I", "Розділ XIV", "Розділ 1"
_ROZDIL_RE = re.compile(r"^Розділ\s+([IVXLCDM\d]+)", re.UNICODE)

# Sub-chapter: "Глава 1", "Глава 12"
_HLAVA_RE = re.compile(r"^Глава\s+(\d+)", re.UNICODE)

# Annex: "Додаток" (possibly followed by number/letter)
_DODATOK_RE = re.compile(r"^Додаток", re.UNICODE)

# Editorial annotation: lines fully enclosed in {braces}
_ANNOTATION_RE = re.compile(r"^\{.*\}$", re.UNICODE)

# Signature block indicators
_SIGNATURE_PREFIXES = (
    "Президент України",
    "Голова Верховної Ради",
    "Прем'єр-міністр",
    "м. Київ",
)

# Date from Vidomosti line: (Відомості ... (ВВР), 2007, № 35, ст.484)
_VIDOMOSTI_RE = re.compile(r"\(Відомості.*?,\s*(\d{4})\s*,", re.UNICODE)

# Ukrainian month names for date parsing
_UA_MONTHS: dict[str, int] = {
    "січня": 1,
    "лютого": 2,
    "березня": 3,
    "квітня": 4,
    "травня": 5,
    "червня": 6,
    "липня": 7,
    "серпня": 8,
    "вересня": 9,
    "жовтня": 10,
    "листопада": 11,
    "грудня": 12,
}

# Full date: "31 травня 2007 року" or "28 червня 1996 року"
_FULL_DATE_RE = re.compile(r"(\d{1,2})\s+(\w+)\s+(\d{4})\s+року", re.UNICODE)

# Short date in rozporiadzhennia/postanova: "від 6 червня 2007 р."
_VID_DATE_RE = re.compile(r"від\s+(\d{1,2})\s+(\w+)\s+(\d{4})\s+р\b", re.UNICODE)

# Dotted date in text: "12.08.1987"
_DOTTED_DATE_IN_TEXT_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")


def _try_ua_date(day: int, month_name: str, year: int) -> date | None:
    """Try to build a date from day, Ukrainian month name, and year."""
    month = _UA_MONTHS.get(month_name.lower())
    if month:
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def _extract_date_from_text(text: str) -> date | None:
    """Try to extract publication date from law text content."""
    # First try: Vidomosti line (most common)
    m = _VIDOMOSTI_RE.search(text)
    if m:
        year = int(m.group(1))
        return date(year, 1, 1)

    # Second try: full date with "року" suffix (signature block)
    for m in _FULL_DATE_RE.finditer(text):
        result = _try_ua_date(int(m.group(1)), m.group(2), int(m.group(3)))
        if result:
            return result

    # Third try: "від DD month YYYY р." (CMU rozporiadzhennia/postanova)
    m = _VID_DATE_RE.search(text)
    if m:
        result = _try_ua_date(int(m.group(1)), m.group(2), int(m.group(3)))
        if result:
            return result

    # Fourth try: dotted date DD.MM.YYYY in text
    m = _DOTTED_DATE_IN_TEXT_RE.search(text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    return None


def _is_annotation(line: str) -> bool:
    """Check if a line is an editorial annotation ``{...}``."""
    return line.startswith("{") and line.endswith("}")


def _is_signature(line: str) -> bool:
    """Check if a line is part of a signature block."""
    stripped = line.strip()
    if any(stripped.startswith(p) for p in _SIGNATURE_PREFIXES):
        return True
    # Standalone number like "№ 1103-V" at end of document
    if re.match(r"^№\s+\S+$", stripped):
        return True
    # Standalone date like "31 травня 2007 року"
    if re.match(r"^\d{1,2}\s+\w+\s+\d{4}\s+року$", stripped):
        return True
    return False


def _make_block(
    block_id: str,
    block_type: str,
    title: str,
    paragraphs: list[Paragraph],
    pub_date: date,
    norm_id: str,
) -> Block:
    version = Version(
        norm_id=norm_id,
        publication_date=pub_date,
        effective_date=pub_date,
        paragraphs=tuple(paragraphs),
    )
    return Block(id=block_id, block_type=block_type, title=title, versions=(version,))


def _flush_article(
    article_num: str,
    article_title: str,
    body_lines: list[str],
    pub_date: date,
    norm_id: str,
    block_index: int,
) -> Block:
    """Build an article Block from accumulated lines."""
    heading = f"Стаття {article_num}"
    if article_title:
        heading = f"Стаття {article_num}. {article_title}"

    paragraphs: list[Paragraph] = [Paragraph(css_class="articulo", text=heading)]

    for line in body_lines:
        if _is_annotation(line):
            continue
        paragraphs.append(Paragraph(css_class="parrafo", text=line))

    block_id = f"st{article_num}"
    return _make_block(block_id, "article", heading, paragraphs, pub_date, norm_id)


# ─────────────────────────────────────────────
# RadaTextParser
# ─────────────────────────────────────────────


class RadaTextParser(TextParser):
    """Parse Ukrainian law plain text into Block objects."""

    def parse_text(self, data: bytes) -> list[Any]:
        """Parse ``.txt`` content into a list of Block objects."""
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("cp1251", errors="replace")

        lines = text.splitlines()
        if not lines:
            return []

        blocks: list[Block] = []
        block_index = 0

        # Preamble lines (before any structural element)
        preamble_lines: list[str] = []
        in_preamble = True

        # Current article state
        cur_article_num: str | None = None
        cur_article_title: str = ""
        cur_body: list[str] = []

        # Extract publication date from text content.  The pipeline uses the
        # Version.publication_date from blocks for commit author dates, so this
        # must be as accurate as possible.  Falls back to 1991-08-24 for ~782
        # docs (short decrees, appendix-only, Soviet-era) whose text has no
        # parseable date.  A pipeline-level hook passing metadata.publication_date
        # would fix these (see Portugal's parse_text_with_date pattern).
        pub_date = _extract_date_from_text(text) or date(1991, 8, 24)
        norm_id = ""

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Check structural patterns
            m_article = _ARTICLE_RE.match(stripped)
            m_rozdil = _ROZDIL_RE.match(stripped)
            m_hlava = _HLAVA_RE.match(stripped)
            m_dodatok = _DODATOK_RE.match(stripped)

            if m_article:
                # Flush previous article
                if cur_article_num is not None:
                    blocks.append(
                        _flush_article(
                            cur_article_num,
                            cur_article_title,
                            cur_body,
                            pub_date,
                            norm_id,
                            block_index,
                        )
                    )
                    block_index += 1
                elif in_preamble and preamble_lines:
                    # Flush preamble
                    paras = [
                        Paragraph(css_class="parrafo", text=ln)
                        for ln in preamble_lines
                        if not _is_annotation(ln)
                    ]
                    if paras:
                        blocks.append(
                            _make_block(
                                "preamble",
                                "preamble",
                                "Преамбула",
                                paras,
                                pub_date,
                                norm_id,
                            )
                        )
                        block_index += 1
                    in_preamble = False

                cur_article_num = m_article.group(1)
                cur_article_title = m_article.group(2).strip()
                cur_body = []
                in_preamble = False

            elif m_rozdil:
                # Flush current article first
                if cur_article_num is not None:
                    blocks.append(
                        _flush_article(
                            cur_article_num,
                            cur_article_title,
                            cur_body,
                            pub_date,
                            norm_id,
                            block_index,
                        )
                    )
                    block_index += 1
                    cur_article_num = None
                    cur_body = []
                elif in_preamble and preamble_lines:
                    paras = [
                        Paragraph(css_class="parrafo", text=ln)
                        for ln in preamble_lines
                        if not _is_annotation(ln)
                    ]
                    if paras:
                        blocks.append(
                            _make_block(
                                "preamble",
                                "preamble",
                                "Преамбула",
                                paras,
                                pub_date,
                                norm_id,
                            )
                        )
                        block_index += 1
                    in_preamble = False

                # The next line may be the chapter title in UPPERCASE
                heading = stripped
                paras = [Paragraph(css_class="titulo_tit", text=heading)]
                blocks.append(
                    _make_block(
                        f"rozdil-{block_index}",
                        "chapter",
                        heading,
                        paras,
                        pub_date,
                        norm_id,
                    )
                )
                block_index += 1

            elif m_hlava:
                if cur_article_num is not None:
                    blocks.append(
                        _flush_article(
                            cur_article_num,
                            cur_article_title,
                            cur_body,
                            pub_date,
                            norm_id,
                            block_index,
                        )
                    )
                    block_index += 1
                    cur_article_num = None
                    cur_body = []

                heading = stripped
                paras = [Paragraph(css_class="capitulo_tit", text=heading)]
                blocks.append(
                    _make_block(
                        f"hlava-{block_index}",
                        "chapter",
                        heading,
                        paras,
                        pub_date,
                        norm_id,
                    )
                )
                block_index += 1

            elif m_dodatok:
                if cur_article_num is not None:
                    blocks.append(
                        _flush_article(
                            cur_article_num,
                            cur_article_title,
                            cur_body,
                            pub_date,
                            norm_id,
                            block_index,
                        )
                    )
                    block_index += 1
                    cur_article_num = None
                    cur_body = []

                heading = stripped
                paras = [Paragraph(css_class="capitulo_tit", text=heading)]
                blocks.append(
                    _make_block(
                        f"dodatok-{block_index}",
                        "annex",
                        heading,
                        paras,
                        pub_date,
                        norm_id,
                    )
                )
                block_index += 1

            elif _is_signature(stripped):
                # Skip signature lines at end of document
                continue

            elif cur_article_num is not None:
                # Inside an article — accumulate body lines
                cur_body.append(stripped)

            elif in_preamble:
                preamble_lines.append(stripped)

        # Flush final article
        if cur_article_num is not None:
            blocks.append(
                _flush_article(
                    cur_article_num,
                    cur_article_title,
                    cur_body,
                    pub_date,
                    norm_id,
                    block_index,
                )
            )

        # If no structural elements found at all, make a single text block
        if not blocks and preamble_lines:
            paras = [
                Paragraph(css_class="parrafo", text=ln)
                for ln in preamble_lines
                if not _is_annotation(ln)
            ]
            if paras:
                blocks.append(_make_block("text-0", "text", "Текст", paras, pub_date, norm_id))

        return blocks

    def extract_reforms(self, data: bytes) -> list[Any]:
        """No amendment history in v1 — single snapshot."""
        return []


# ─────────────────────────────────────────────
# RadaMetadataParser
# ─────────────────────────────────────────────

_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


def _parse_dotted_date(text: str) -> date | None:
    """Parse ``DD.MM.YYYY`` → date."""
    m = _DATE_RE.search(text)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def _parse_rfc2822_date(text: str) -> date | None:
    """Parse RFC 2822 date like ``Fri, 28 Jun 1996 06:45:00 GMT`` → date."""
    try:
        dt = datetime.strptime(text.strip(), "%a, %d %b %Y %H:%M:%S %Z")
        return dt.date()
    except (ValueError, TypeError):
        return None


def _resolve_rank(types_str: str) -> Rank:
    """Determine the rank from the Types meta content.

    Types is comma-separated, e.g. ``"Конституція України, Конституція, Закон"``.
    We try each type against RANK_MAP and return the first match.
    """
    for raw_type in types_str.split(","):
        t = raw_type.strip()
        if t in RANK_MAP:
            return Rank(RANK_MAP[t])
    return Rank("zakon")


class RadaMetadataParser(MetadataParser):
    """Parse metadata from the ``.xml`` endpoint (HTML with ``<meta>`` tags)."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        doc = lxml.html.fromstring(data)

        def meta(name: str) -> str:
            els = doc.xpath(f'//meta[@name="{name}"]/@content')
            return els[0] if els else ""

        title_el = doc.xpath("//title/text()")
        title = title_el[0].strip() if title_el else ""

        types = meta("Types")
        organs = meta("Organs")
        stan = meta("Stan")
        dates = meta("Dates")
        numbers = meta("Numbers")
        doc_date = meta("DocumentDate")

        # Publication date from Dates field (DD.MM.YYYY)
        pub_date = _parse_dotted_date(dates)
        if pub_date is None:
            # Fallback to Created meta
            pub_date = _parse_rfc2822_date(meta("Created")) or date(2000, 1, 1)

        # Last modified from DocumentDate
        last_modified = _parse_rfc2822_date(doc_date)

        # Status
        status = STAN_MAP.get(stan.strip(), NormStatus.IN_FORCE)

        # Rank
        rank = _resolve_rank(types)

        # Build source URL
        source = f"https://zakon.rada.gov.ua/laws/show/{norm_id}"

        # Extra fields
        extra: list[tuple[str, str]] = []
        if numbers:
            extra.append(("official_number", numbers))

        identifier = nreg_to_identifier(norm_id)

        return NormMetadata(
            title=title,
            short_title=title,
            identifier=identifier,
            country="ua",
            rank=rank,
            publication_date=pub_date,
            status=status,
            department=organs,
            source=source,
            last_modified=last_modified,
            extra=tuple(extra),
        )
