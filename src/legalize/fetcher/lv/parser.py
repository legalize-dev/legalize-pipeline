"""Parser for likumi.lv HTML pages (Latvia).

Each law page contains both the consolidated text and metadata sidebar:
- Body text: <div class="doc-body"> with TV{NNN}-classed divs
- Metadata: <div class="pase-container"> with field/value spans

CSS class mapping (validated 2026-04-07 against 5 fixtures):

| TV class | Role                          | Markdown |
|----------|-------------------------------|----------|
| TV206    | Preamble intro (formulaic)    | normal   |
| TV207    | Main title                    | skip     |
| TV208    | Preamble body                 | normal   |
| TV212    | Chapter heading (nodaļa)      | ##       |
| TV213    | Article (pants) — has data-num| #####    |
| TV214    | Transitional provisions head  | ##       |
| TV215    | Entry into force clause       | normal   |
| TV216    | Signatory                     | bold     |
| TV217    | Place/date of signing         | normal   |
| TV218    | Annex header (pielikums)      | ##       |
| TV403    | EU directive references       | normal   |
| TV444    | Container for HTML <TABLE>    | pipe table |
| TV900    | Legal authority basis         | normal   |
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

from lxml import html as lxml_html

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    Rank,
    Version,
)

logger = logging.getLogger(__name__)

# Reusable HTML parser with explicit UTF-8 encoding.
# likumi.lv serves UTF-8 (Content-Type: text/html; charset=utf-8), but
# lxml's auto-detection from raw bytes sometimes misfires on large pages
# and falls back to Latin-1, producing mojibake in the parsed tree
# (e.g. "BeÄ¼Ä£ijas" instead of "Beļģijas" in id=198715).
# Forcing UTF-8 decoding via the parser fixes this.
_HTML_PARSER = lxml_html.HTMLParser(encoding="utf-8")


def _parse_html(data: bytes):
    """Parse HTML bytes into an lxml tree with forced UTF-8 decoding."""
    return lxml_html.fromstring(data, parser=_HTML_PARSER)


# Map likumi.lv "Veids" (act type) to internal rank strings.
# The Veids URL pattern is /ta/veids/{issuer}/{type} — we use the second segment.
VEIDS_TO_RANK: dict[str, str] = {
    "likumi": "likums",
    "konstitucionalais-likums": "konstitucionalais_likums",
    "noteikumi": "noteikumi",
    "saistosie-noteikumi": "saistosie_noteikumi",
    "rikojumi": "rikojums",
    "lemumi": "lemums",
    "instrukcijas": "instrukcija",
    "kartiba": "kartiba",
    "ietikumi": "ietikumi",
    "ligumi": "ligums",
    "starptautiskais-ligums": "starptautiskais_ligums",
    "konvencija": "konvencija",
    "dekreti": "dekrets",
    "pavelnes": "pavelne",
    "noradijumi": "noradijumi",
}

# Special case: Satversme (Constitution) issued by Satversmes Sapulce
# We map this from the URL /ta/veids/satversmes-sapulce/likumi specifically
_SATVERSME_ID = 57980

# Map ico-* CSS class to NormStatus
STATUS_MAP: dict[str, NormStatus] = {
    "ico-speka": NormStatus.IN_FORCE,
    "ico-zspeku": NormStatus.REPEALED,
    "ico-vnav": NormStatus.IN_FORCE,  # Not yet in force — treat as in_force
}

# CSS classes to strip from article content (not part of legal text)
_STRIP_CLASSES = frozenset(
    {
        "labojumu_pamats",  # amendment basis notes
        "panta-doc-npk",  # hidden sequential numbering
        "info-icon-wrapper",  # video links, court icons
        "court",  # court decision markers
        "satura_raditajs",  # TOC anchors
        "p_id",  # paragraph ID anchors
        "panta-piezimite",  # article notes (UI tooltip)
    }
)

# Latvian month names → numbers (for date parsing)
_LV_MONTHS: dict[str, int] = {
    "janvārī": 1,
    "janvāris": 1,
    "janvāra": 1,
    "februārī": 2,
    "februāris": 2,
    "februāra": 2,
    "martā": 3,
    "marts": 3,
    "marta": 3,
    "aprīlī": 4,
    "aprīlis": 4,
    "aprīļa": 4,
    "maijā": 5,
    "maijs": 5,
    "maija": 5,
    "jūnijā": 6,
    "jūnijs": 6,
    "jūnija": 6,
    "jūlijā": 7,
    "jūlijs": 7,
    "jūlija": 7,
    "augustā": 8,
    "augusts": 8,
    "augusta": 8,
    "septembrī": 9,
    "septembris": 9,
    "septembra": 9,
    "oktobrī": 10,
    "oktobris": 10,
    "oktobra": 10,
    "novembrī": 11,
    "novembris": 11,
    "novembra": 11,
    "decembrī": 12,
    "decembris": 12,
    "decembra": 12,
}


def _parse_dotted_date(s: str) -> date | None:
    """Parse DD.MM.YYYY. format used by likumi.lv."""
    if not s:
        return None
    s = s.strip().rstrip(".")
    try:
        return datetime.strptime(s, "%d.%m.%Y").date()
    except ValueError:
        return None


# C0 control chars (except \t, \n, \r) and C1 control chars (0x80-0x9F).
# These are never legitimately in text but occasionally leak from likumi.lv
# source data (e.g. U+009A between "pa" and "švaldības" in id=305766 breaks
# YAML parsing downstream).
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _clean_text(text: str) -> str:
    """Normalize whitespace, strip non-breaking spaces and invalid control chars."""
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = _CONTROL_CHAR_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _element_text(el) -> str:
    """Get cleaned text content from an lxml element."""
    if el is None:
        return ""
    return _clean_text("".join(el.itertext()))


def _get_classes(el) -> set[str]:
    """Get the set of CSS classes on an element."""
    cls = el.get("class") or ""
    return set(cls.split())


def _has_class(el, css_class: str) -> bool:
    """Check if element has a given CSS class."""
    return css_class in _get_classes(el)


def _strip_descendants_with_classes(el, classes: frozenset[str]) -> None:
    """Remove descendant elements that have any of the given classes.

    Preserves the tail text of removed elements so the surrounding text
    flow stays intact (e.g., headings with anchor children).
    """
    # Iterate over a snapshot since we mutate the tree
    targets = []
    for descendant in el.xpath(".//*[@class]"):
        descendant_classes = set((descendant.get("class") or "").split())
        if descendant_classes & classes:
            targets.append(descendant)

    for descendant in targets:
        parent = descendant.getparent()
        if parent is None:
            continue
        # Preserve tail text by appending it to the previous sibling's tail
        # or the parent's text
        tail = descendant.tail or ""
        if tail:
            prev = descendant.getprevious()
            if prev is not None:
                prev.tail = (prev.tail or "") + tail
            else:
                parent.text = (parent.text or "") + tail
        parent.remove(descendant)


# ─────────────────────────────────────────────
# Table → Markdown (adapted from at/parser.py for likumi.lv uppercase TABLE)
# ─────────────────────────────────────────────


def _table_cell_text(td) -> str:
    """Extract clean text from a <TD> cell, escaping pipes for Markdown."""
    text = _element_text(td)
    return text.replace("|", "\\|").strip()


def _table_to_markdown(table_el) -> str:
    """Convert a <TABLE> lxml element to a Markdown pipe table.

    likumi.lv uses uppercase HTML tags (<TABLE>, <TBODY>, <TR>, <TD>).
    Cells may contain <P>, <B>, <center>, <SUP>, etc.
    Handles ROWSPAN and COLSPAN by repeating values.
    """
    # Collect rows: each row is a list of (text, colspan, rowspan)
    raw_rows: list[list[tuple[str, int, int]]] = []
    for tr in table_el.iter():
        tag = (tr.tag or "").lower()
        if tag != "tr":
            continue
        cells: list[tuple[str, int, int]] = []
        for cell in tr:
            cell_tag = (cell.tag or "").lower()
            if cell_tag not in ("td", "th"):
                continue
            text = _table_cell_text(cell)
            colspan = int(cell.get("COLSPAN") or cell.get("colspan") or 1)
            rowspan = int(cell.get("ROWSPAN") or cell.get("rowspan") or 1)
            cells.append((text, colspan, rowspan))
        if cells:
            raw_rows.append(cells)

    if not raw_rows:
        return ""

    # Expand rowspan/colspan into a 2D grid
    # Track pending rowspans: column → (text, remaining_rows)
    expanded: list[list[str]] = []
    pending: dict[int, tuple[str, int]] = {}  # col_index → (text, remaining)

    for row in raw_rows:
        out_row: list[str] = []
        col = 0
        cell_idx = 0
        while cell_idx < len(row) or col in pending:
            if col in pending:
                text, remaining = pending[col]
                out_row.append(text)
                if remaining > 1:
                    pending[col] = (text, remaining - 1)
                else:
                    del pending[col]
                col += 1
                continue
            text, colspan, rowspan = row[cell_idx]
            for _ in range(colspan):
                out_row.append(text)
                if rowspan > 1:
                    pending[col] = (text, rowspan - 1)
                col += 1
            cell_idx += 1
        # Drain any pending columns at end of row
        while pending:
            col = max(pending) + 1
            break
        expanded.append(out_row)

    if not expanded:
        return ""

    # Normalize to max column count
    max_cols = max(len(r) for r in expanded)
    for r in expanded:
        while len(r) < max_cols:
            r.append("")

    lines = []
    lines.append("| " + " | ".join(expanded[0]) + " |")
    lines.append("| " + " | ".join("---" for _ in range(max_cols)) + " |")
    for row in expanded[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


# ─────────────────────────────────────────────
# Article paragraph extraction
# ─────────────────────────────────────────────


def _parse_article_paragraphs(div) -> list[Paragraph]:
    """Parse the <p> children of a TV213 article div into Paragraphs.

    The first <p class='TV213 TVP'> contains the article number in <B> tags.
    Subsequent <p class='TV213'> are continuation paragraphs.
    <p class='TV213 limenis2'> are indented sub-items (numbered lists).
    Strips amendment notes (labojumu_pamats) and UI elements.
    """
    paragraphs: list[Paragraph] = []

    for p in div.iter():
        tag = (p.tag or "").lower()
        if tag != "p":
            continue
        classes = _get_classes(p)
        if classes & _STRIP_CLASSES:
            continue
        if "TV213" not in classes:
            continue
        text = _element_text(p)
        if not text:
            continue
        # Map to internal CSS class for markdown rendering
        if "TVP" in classes:
            css = "articulo"  # first paragraph (with article number)
        elif "limenis2" in classes:
            css = "list_item"
        else:
            css = "parrafo"
        paragraphs.append(Paragraph(css_class=css, text=text))

    return paragraphs


# Pattern to detect old-format article boundaries: "1. text..." or "1.pants ..."
_ARTICLE_PREFIX_RE = re.compile(r"^(\d+)\.(?:\s|pants\b)")


def _split_paragraphs_by_article(
    paragraphs: list[Paragraph],
) -> list[tuple[str, list[Paragraph]]]:
    """Split a flat list of paragraphs into (article_id, paragraphs) groups.

    Used for old-format laws (e.g., 1937 Civil Law) where one TV208 div
    contains many articles as <p class="TV213"> paragraphs starting with
    a numeric prefix like "1. ", "2. ", etc.

    Returns a list of (block_id, paragraph_list) tuples. Paragraphs before
    the first numeric prefix are grouped under "preamble".
    """
    groups: list[tuple[str, list[Paragraph]]] = []
    current_id = "preamble"
    current_paragraphs: list[Paragraph] = []

    for para in paragraphs:
        match = _ARTICLE_PREFIX_RE.match(para.text)
        if match:
            # New article boundary
            if current_paragraphs:
                groups.append((current_id, current_paragraphs))
            current_id = f"p{match.group(1)}"
            # First paragraph of an article gets the "articulo" CSS class
            current_paragraphs = [Paragraph(css_class="articulo", text=para.text)]
        else:
            current_paragraphs.append(para)

    if current_paragraphs:
        groups.append((current_id, current_paragraphs))

    return groups


def _parse_section_paragraphs(div) -> list[Paragraph]:
    """Parse all <p class="TV213"> paragraphs inside a section div (TV208).

    Used for old-format laws where TV208 is a container for many articles.
    Returns a flat list of paragraphs without article splitting.
    """
    paragraphs: list[Paragraph] = []
    for p in div.iter():
        tag = (p.tag or "").lower()
        if tag != "p":
            continue
        classes = _get_classes(p)
        if classes & _STRIP_CLASSES:
            continue
        if "TV213" not in classes:
            continue
        text = _element_text(p)
        if not text:
            continue
        if "limenis2" in classes:
            css = "list_item"
        else:
            css = "parrafo"
        paragraphs.append(Paragraph(css_class=css, text=text))
    return paragraphs


def _parse_simple_div_paragraphs(div, css_class: str = "parrafo") -> list[Paragraph]:
    """Parse a simple TV2xx div (no nested article structure)."""
    # Strip UI noise first by removing those elements
    _strip_descendants_with_classes(div, _STRIP_CLASSES)
    text = _element_text(div)
    if not text:
        return []
    return [Paragraph(css_class=css_class, text=text)]


def _parse_table_div(div) -> list[Paragraph]:
    """Parse a TV444 div containing an HTML table."""
    paragraphs: list[Paragraph] = []

    # Optional title before the TABLE (e.g., "1. Publiskie ezeri")
    for child in div:
        tag = (child.tag or "").lower()
        if tag == "div":
            # Title div like <DIV STYLE="font-weight: bold; text-align: center">
            title_text = _element_text(child)
            if title_text:
                paragraphs.append(Paragraph(css_class="centro_negrita", text=title_text))
        elif tag == "table":
            md_table = _table_to_markdown(child)
            if md_table:
                paragraphs.append(Paragraph(css_class="table", text=md_table))

    return paragraphs


# ─────────────────────────────────────────────
# Text parser
# ─────────────────────────────────────────────


def _make_block(
    block_id: str,
    block_type: str,
    title: str,
    paragraphs: list[Paragraph],
    pub_date: date,
    law_norm_id: str,
) -> Block:
    """Build a Block with a single Version from paragraphs.

    All blocks of the same law share the same Version.norm_id (the law's ID)
    so the reform extractor groups them into a single Reform.
    """
    version = Version(
        norm_id=law_norm_id,
        publication_date=pub_date,
        effective_date=pub_date,
        paragraphs=tuple(paragraphs),
    )
    return Block(
        id=block_id,
        block_type=block_type,
        title=title,
        versions=(version,),
    )


_OG_URL_ID_RE = re.compile(r"id=(\d+)")


def _extract_norm_id_and_pub_date(tree) -> tuple[str, date]:
    """Extract the norm ID and publication date from the HTML page.

    The text parser needs both to build correct Version objects:
    - norm_id: from <meta property="og:url" content="...?id=N">
    - pub_date: from the "Pieņemts" field in the pase-container sidebar
    """
    norm_id = "0"
    og_url = tree.xpath('//meta[@property="og:url"]/@content')
    if og_url:
        match = _OG_URL_ID_RE.search(og_url[0])
        if match:
            norm_id = match.group(1)

    pub_date = date(1900, 1, 1)
    pase_list = tree.xpath('//div[contains(@class, "pase-container")]')
    if pase_list:
        fields = _extract_pase_fields(pase_list[0])
        parsed = _parse_dotted_date(fields.get("Pieņemts", ""))
        if parsed:
            pub_date = parsed

    return norm_id, pub_date


class LikumiTextParser(TextParser):
    """Parses likumi.lv HTML page into Block objects."""

    def parse_text(self, data: bytes) -> list[Any]:
        """Parse the doc-body of a likumi.lv HTML page into Blocks."""
        if not data:
            return []

        try:
            tree = _parse_html(data)
        except Exception as exc:
            logger.warning("Failed to parse HTML: %s", exc)
            return []

        doc_body_list = tree.xpath('//div[@class="doc-body"]')
        if not doc_body_list:
            return []
        doc_body = doc_body_list[0]

        # Extract law-level norm_id and publication date so all blocks
        # share the same Version.norm_id (one reform per law, not per block).
        law_norm_id, pub_date = _extract_norm_id_and_pub_date(tree)

        blocks: list[Block] = []
        block_index = 0

        # Iterate direct children of doc-body that have a TV* class
        for div in doc_body.xpath('./div[contains(@class, "TV")]'):
            classes = _get_classes(div)

            # Determine the primary TV class
            tv_class = next((c for c in classes if c.startswith("TV") and c[2:].isdigit()), None)
            if not tv_class:
                continue

            # TV207 = main title (already in frontmatter, skip)
            if tv_class == "TV207":
                continue

            # TV213 = article
            if tv_class == "TV213":
                _strip_descendants_with_classes(div, _STRIP_CLASSES)
                article_num = div.get("data-num", "").strip()
                paragraphs = _parse_article_paragraphs(div)
                if not paragraphs:
                    continue
                block_id = f"p{article_num}" if article_num else f"art-{block_index}"
                title = paragraphs[0].text if paragraphs else f"{article_num}. pants"
                blocks.append(
                    _make_block(block_id, "article", title, paragraphs, pub_date, law_norm_id)
                )
                block_index += 1
                continue

            # TV212 / TV214 = chapter or transitional provisions heading
            if tv_class in ("TV212", "TV214"):
                _strip_descendants_with_classes(div, _STRIP_CLASSES)
                heading_text = _element_text(div)
                if not heading_text:
                    continue
                paragraphs = [Paragraph(css_class="capitulo_tit", text=heading_text)]
                block_id = f"chapter-{block_index}"
                blocks.append(
                    _make_block(
                        block_id, "chapter", heading_text, paragraphs, pub_date, law_norm_id
                    )
                )
                block_index += 1
                continue

            # TV218 = annex header (pielikums)
            if tv_class == "TV218":
                _strip_descendants_with_classes(div, _STRIP_CLASSES)
                heading_text = _element_text(div)
                if not heading_text:
                    continue
                paragraphs = [Paragraph(css_class="capitulo_tit", text=heading_text)]
                block_id = f"annex-{block_index}"
                blocks.append(
                    _make_block(block_id, "annex", heading_text, paragraphs, pub_date, law_norm_id)
                )
                block_index += 1
                continue

            # TV444 = table container
            if tv_class == "TV444":
                paragraphs = _parse_table_div(div)
                if not paragraphs:
                    continue
                block_id = f"table-{block_index}"
                title = "Table"
                blocks.append(
                    _make_block(block_id, "table", title, paragraphs, pub_date, law_norm_id)
                )
                block_index += 1
                continue

            # TV208 = section container (old-format laws like 1937 Civil Law)
            # May contain many articles as <p class="TV213"> paragraphs.
            if tv_class == "TV208":
                _strip_descendants_with_classes(div, _STRIP_CLASSES)
                section_paragraphs = _parse_section_paragraphs(div)
                if not section_paragraphs:
                    # Fallback: just get the text content as a single block
                    paragraphs = _parse_simple_div_paragraphs(div)
                    if not paragraphs:
                        continue
                    block_id = f"text-{block_index}"
                    blocks.append(
                        _make_block(
                            block_id,
                            "text",
                            paragraphs[0].text[:50],
                            paragraphs,
                            pub_date,
                            law_norm_id,
                        )
                    )
                    block_index += 1
                    continue

                # Try to split by article number prefix
                article_groups = _split_paragraphs_by_article(section_paragraphs)
                if len(article_groups) > 1 or (
                    article_groups and article_groups[0][0] != "preamble"
                ):
                    # Old-format with embedded articles — emit one block per article
                    seen_ids: set[str] = set()
                    for group_id, group_paras in article_groups:
                        # Avoid duplicate IDs across sections
                        unique_id = group_id
                        suffix = 0
                        while unique_id in seen_ids:
                            suffix += 1
                            unique_id = f"{group_id}-{suffix}"
                        seen_ids.add(unique_id)
                        title = group_paras[0].text[:80] if group_paras else group_id
                        block_type = "article" if group_id != "preamble" else "preamble"
                        blocks.append(
                            _make_block(
                                unique_id,
                                block_type,
                                title,
                                group_paras,
                                pub_date,
                                law_norm_id,
                            )
                        )
                        block_index += 1
                else:
                    # Single preamble paragraph (no articles inside)
                    block_id = f"preamble-{block_index}"
                    title = section_paragraphs[0].text[:50]
                    blocks.append(
                        _make_block(
                            block_id,
                            "preamble",
                            title,
                            section_paragraphs,
                            pub_date,
                            law_norm_id,
                        )
                    )
                    block_index += 1
                continue

            # TV206, TV215, TV216, TV217, TV403, TV900 = simple text
            paragraphs = _parse_simple_div_paragraphs(div)
            if not paragraphs:
                continue
            # TV216 (signatory) → bold
            if tv_class == "TV216":
                paragraphs[0] = Paragraph(css_class="firma_rey", text=paragraphs[0].text)

            block_id = f"text-{block_index}"
            blocks.append(
                _make_block(
                    block_id, "text", paragraphs[0].text[:50], paragraphs, pub_date, law_norm_id
                )
            )
            block_index += 1

        return blocks

    def extract_reforms(self, data: bytes) -> list[Any]:
        """likumi.lv historical versions are forbidden by robots.txt.

        We treat each law as a single snapshot — no reform timeline.
        """
        return []


# ─────────────────────────────────────────────
# Metadata parser
# ─────────────────────────────────────────────


_VEIDS_URL_RE = re.compile(r"/ta/veids/([^/]+)/([^/'\"]+)")


def _extract_pase_fields(pase_el) -> dict[str, str]:
    """Extract metadata fields from the pase-container div.

    Each field is a <span> containing a <font class='fclg2'>Label:</font>Value structure.
    Returns a dict mapping label (without trailing colon) to its cleaned value.
    """
    fields: dict[str, str] = {}
    spans = pase_el.xpath('.//div[contains(@class, "wrapper")]/span')
    for span in spans:
        fonts = span.xpath('./font[@class="fclg2"]')
        if not fonts:
            continue
        label_raw = "".join(fonts[0].itertext())
        label = _clean_text(label_raw).rstrip(":").strip()
        if not label:
            continue
        # Value: total text content minus the label part
        full_text = "".join(span.itertext())
        # Remove the label (which includes the colon and possibly trailing space)
        idx = full_text.find(":")
        if idx >= 0:
            value = full_text[idx + 1 :]
        else:
            value = full_text
        fields[label] = _clean_text(value)
    return fields


class LikumiMetadataParser(MetadataParser):
    """Parses likumi.lv HTML page metadata sidebar into NormMetadata."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        """Extract metadata from the pase-container div of a likumi.lv page."""
        if not data:
            raise ValueError(f"Empty data for norm {norm_id}")

        tree = _parse_html(data)

        # Title from <title> or og:title meta
        title = ""
        og_title = tree.xpath('//meta[@property="og:title"]/@content')
        if og_title:
            title = _clean_text(og_title[0])
        if not title:
            title_el = tree.xpath("//title/text()")
            if title_el:
                title = _clean_text(title_el[0])

        # Locate pase-container
        pase_list = tree.xpath('//div[contains(@class, "pase-container")]')
        if not pase_list:
            raise ValueError(f"No pase-container found for norm {norm_id}")
        pase = pase_list[0]

        # Status: from ico-* CSS class on the status div
        status = NormStatus.IN_FORCE
        status_divs = pase.xpath('.//div[contains(@class, "ico-status")]')
        for sd in status_divs:
            for ico_class, mapped in STATUS_MAP.items():
                if _has_class(sd, ico_class):
                    status = mapped
                    break

        # Veids → rank: from /ta/veids/{issuer}/{type} link
        rank_str = "otro"
        veids_links = pase.xpath('.//a[contains(@href, "/ta/veids/")]/@href')
        if veids_links:
            match = _VEIDS_URL_RE.search(veids_links[0])
            if match:
                issuer, type_slug = match.group(1), match.group(2)
                # Special case: Constitution
                if issuer == "satversmes-sapulce" and type_slug == "likumi":
                    rank_str = "satversme"
                else:
                    rank_str = VEIDS_TO_RANK.get(type_slug, type_slug.replace("-", "_"))

        # Extract fields by iterating spans (more reliable than regex on flat text)
        fields = _extract_pase_fields(pase)

        izdevejs = fields.get("Izdevējs", "")
        pienemts = fields.get("Pieņemts", "")
        stajas_speka = fields.get("Stājas spēkā", "")
        zaude_speku = fields.get("Zaudē spēku", "")
        publicets = fields.get("Publicēts", "")
        numurs = fields.get("Numurs", "")
        op_numurs = fields.get("OP numurs", "")
        if not title:
            title = fields.get("Nosaukums", "")

        # Subjects (Tēma) — collect all topic links
        subjects: list[str] = []
        for tema_link in pase.xpath('.//a[contains(@href, "/ta/tema/")]/text()'):
            cleaned = _clean_text(tema_link)
            if cleaned:
                subjects.append(cleaned)

        publication_date = _parse_dotted_date(pienemts) or date(1900, 1, 1)

        # Build extra fields tuple
        extra: list[tuple[str, str]] = []
        if numurs:
            extra.append(("official_number", numurs))
        if stajas_speka:
            extra.append(("entry_into_force", stajas_speka))
        if zaude_speku:
            extra.append(("expiry_date", zaude_speku))
        if publicets:
            # Trim long publication strings
            extra.append(("gazette_reference", publicets[:200]))
        if op_numurs:
            extra.append(("op_number", op_numurs))

        source_url = f"https://likumi.lv/ta/id/{norm_id}"

        return NormMetadata(
            title=title or f"Norm {norm_id}",
            short_title=title or f"Norm {norm_id}",
            identifier=norm_id,
            country="lv",
            rank=Rank(rank_str),
            publication_date=publication_date,
            status=status,
            department=izdevejs,
            source=source_url,
            subjects=tuple(subjects),
            extra=tuple(extra),
        )
