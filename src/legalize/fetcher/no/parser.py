"""Parser for Lovdata XML-HTML pages (Norway).

Each law file contains both metadata and text in a single HTML document:
- Metadata: <header class="documentHeader"> with <dl class="data-document-key-info">
- Body: <main class="documentBody"> with nested <section> and <article> elements

HTML structure (verified 2026-04-13 against 5 fixtures):

| Element / class             | Role                        | Markdown       |
|-----------------------------|-----------------------------|----------------|
| h1                          | Law title                   | # (skip—in FM) |
| section.section > h2        | Part heading (del)          | ##             |
| section.section > h3        | Chapter heading (kapittel)  | ###            |
| article.legalArticle > h*   | Article heading (§ N)       | #####          |
| article.legalP              | Paragraph (ledd)            | normal         |
| article.changesToParent     | Amendment history           | SKIP           |
| table                       | HTML table                  | pipe table     |
| ul / ol                     | List                        | list items     |
| b, strong                   | Bold                        | **text**       |
| i, em                       | Italic                      | *text*         |
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
from legalize.fetcher._text import strip_control

logger = logging.getLogger(__name__)

# Force UTF-8 — Lovdata serves UTF-8 but lxml auto-detection can misfire.
_HTML_PARSER = lxml_html.HTMLParser(encoding="utf-8")

# Heading tag → CSS class for the transformer's markdown renderer.
_HEADING_CSS = {
    "h2": "titulo_tit",  # ## Part heading
    "h3": "capitulo_tit",  # ### Chapter heading
    "h4": "seccion",  # #### Sub-section heading
}

# Classes to skip entirely (not part of the legal text).
_SKIP_CLASSES = frozenset(
    {
        "changesToParent",  # amendment history annotations
        "document-change",  # Lovtidend amendment text
    }
)


# ─── Text utilities ───


def _clean_text(text: str) -> str:
    """Normalize whitespace, strip NBSP and control chars."""
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = strip_control(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_inline_text(el) -> str:
    """Extract text from an element, converting inline HTML to Markdown.

    Handles <b>/<strong> → **bold**, <i>/<em> → *italic*.
    All other tags (including <a>) are reduced to their text content.
    """
    parts: list[str] = []

    def _walk(node, depth: int = 0) -> None:
        tag = node.tag if isinstance(node.tag, str) else ""

        # Opening markup
        if tag in ("b", "strong"):
            parts.append("**")
        elif tag in ("i", "em"):
            parts.append("*")
        elif tag == "br":
            parts.append("\n")

        # Own text
        if node.text:
            parts.append(node.text)

        # Children
        for child in node:
            _walk(child, depth + 1)

        # Closing markup
        if tag in ("b", "strong"):
            parts.append("**")
        elif tag in ("i", "em"):
            parts.append("*")

        # Tail text (text after closing tag, belongs to parent)
        if depth > 0 and node.tail:
            parts.append(node.tail)

    _walk(el)
    return _clean_text("".join(parts))


def _has_class(el, css_class: str) -> bool:
    """Check if element has a given CSS class."""
    return css_class in (el.get("class") or "").split()


def _get_dd_text(dl, dt_class: str) -> str:
    """Extract text from a <dd> following a <dt> with the given class."""
    for dt in dl.iter("dt"):
        if _has_class(dt, dt_class):
            dd = dt.getnext()
            if dd is not None and dd.tag == "dd":
                return _clean_text("".join(dd.itertext()))
    return ""


def _get_dd_list(dl, dt_class: str) -> list[str]:
    """Extract a list of text items from a <dd> with <li> children."""
    for dt in dl.iter("dt"):
        if _has_class(dt, dt_class):
            dd = dt.getnext()
            if dd is not None and dd.tag == "dd":
                items = []
                for li in dd.iter("li"):
                    text = _clean_text("".join(li.itertext()))
                    if text:
                        items.append(text)
                return items
    return []


def _get_dd_links(dl, dt_class: str) -> list[str]:
    """Extract href values from <a> tags inside a <dd>."""
    for dt in dl.iter("dt"):
        if _has_class(dt, dt_class):
            dd = dt.getnext()
            if dd is not None and dd.tag == "dd":
                return [a.get("href", "") for a in dd.iter("a") if a.get("href")]
    return []


def _parse_date_no(s: str) -> date | None:
    """Parse a date string from Lovdata (YYYY-MM-DD or YYYY-MM-DD HH:MM)."""
    if not s:
        return None
    s = s.strip().split()[0]  # Drop time part if present
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _filename_to_date(norm_id: str) -> date | None:
    """Extract date from norm_id like 'nl-20050520-028'."""
    m = re.match(r"nl-(\d{4})(\d{2})(\d{2})-\d+", norm_id)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _legacy_id_to_date(legacy_id: str) -> date | None:
    """Extract date from legacyID like 'LOV-2005-05-20-28' or 'LOV-1814-05-17'."""
    m = re.match(r"[A-Z]+-(\d{4})-(\d{2})-(\d{2})", legacy_id)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


# ─── Table conversion ───


def _table_to_markdown(table_el) -> str:
    """Convert an HTML <table> to a Markdown pipe table."""
    rows: list[list[str]] = []
    for tr in table_el.iter("tr"):
        cells = []
        for cell in tr:
            if cell.tag in ("td", "th"):
                cells.append(_clean_text("".join(cell.itertext())))
        if cells:
            rows.append(cells)

    if not rows:
        return ""

    # Normalize column count
    max_cols = max(len(r) for r in rows)
    for row in rows:
        while len(row) < max_cols:
            row.append("")

    lines = []
    # First row as header
    lines.append("| " + " | ".join(rows[0]) + " |")
    lines.append("| " + " | ".join("---" for _ in rows[0]) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


# ─── Block construction helpers ───


def _make_block(
    block_id: str,
    block_type: str,
    title: str,
    paragraphs: tuple[Paragraph, ...],
    pub_date: date,
    norm_id: str,
) -> Block:
    """Create a Block with a single Version (current snapshot)."""
    return Block(
        id=block_id,
        block_type=block_type,
        title=title,
        versions=(
            Version(
                norm_id=norm_id,
                publication_date=pub_date,
                effective_date=pub_date,
                paragraphs=paragraphs,
            ),
        ),
    )


# ─── TextParser ───


class LovdataTextParser(TextParser):
    """Parse Lovdata XML-HTML into Block objects."""

    def parse_text(self, data: bytes) -> list[Any]:
        tree = lxml_html.fromstring(data, parser=_HTML_PARSER)
        main = tree.find(".//main")
        if main is None:
            logger.warning("No <main> element found")
            return []

        # Extract norm_id and publication date for Version objects
        dl = tree.find('.//dl[@class="data-document-key-info"]')
        norm_id = ""
        pub_date = date(2000, 1, 1)
        if dl is not None:
            norm_id = _get_dd_text(dl, "legacyID")
            pub_date = (
                _parse_date_no(_get_dd_text(dl, "dateOfPublication"))
                or _parse_date_no(_get_dd_text(dl, "dateInForce"))
                or _legacy_id_to_date(norm_id)
                or pub_date
            )

        blocks: list[Block] = []
        self._walk(main, blocks, norm_id, pub_date)
        return blocks

    def _walk(
        self,
        parent,
        blocks: list[Block],
        norm_id: str,
        pub_date: date,
    ) -> None:
        """Recursively walk the document tree emitting Blocks."""
        for child in parent:
            tag = child.tag if isinstance(child.tag, str) else ""
            cls = child.get("class") or ""

            # Skip amendment history and non-legal annotations
            if any(_has_class(child, skip) for skip in _SKIP_CLASSES):
                continue

            # Section (part or chapter) — emit heading, then recurse
            if tag == "section" and "section" in cls:
                self._parse_section(child, blocks, norm_id, pub_date)

            # Article (§) — emit as a block with paragraphs
            elif tag == "article" and "legalArticle" in cls:
                self._parse_article(child, blocks, norm_id, pub_date)

            # Standalone paragraph outside article structure
            elif tag == "article" and ("legalP" in cls or "defaultP" in cls):
                # Check for nested tables first
                for sub in child.iter("table"):
                    md = _table_to_markdown(sub)
                    if md:
                        block_id = sub.get("id") or f"table-{len(blocks)}"
                        blocks.append(
                            _make_block(
                                block_id,
                                "table",
                                "",
                                (Paragraph(css_class="table_row", text=md),),
                                pub_date,
                                norm_id,
                            )
                        )
                text = _extract_inline_text(child)
                if text:
                    block_id = child.get("id") or f"p-{len(blocks)}"
                    blocks.append(
                        _make_block(
                            block_id,
                            "paragraph",
                            "",
                            (Paragraph(css_class="parrafo", text=text),),
                            pub_date,
                            norm_id,
                        )
                    )

            # Lists outside articles
            elif tag in ("ul", "ol"):
                self._parse_list(child, blocks, norm_id, pub_date)

            # Table
            elif tag == "table":
                md = _table_to_markdown(child)
                if md:
                    block_id = child.get("id") or f"table-{len(blocks)}"
                    blocks.append(
                        _make_block(
                            block_id,
                            "table",
                            "",
                            (Paragraph(css_class="table_row", text=md),),
                            pub_date,
                            norm_id,
                        )
                    )

    def _parse_section(
        self,
        section,
        blocks: list[Block],
        norm_id: str,
        pub_date: date,
    ) -> None:
        """Parse a <section class="section"> into heading block + recurse."""
        section_id = section.get("id") or section.get("data-name") or f"sec-{len(blocks)}"

        # Find the heading element (h2, h3, or h4)
        heading_el = None
        for htag in ("h2", "h3", "h4", "h5"):
            heading_el = section.find(htag)
            if heading_el is not None:
                break

        if heading_el is not None:
            heading_text = _clean_text("".join(heading_el.itertext()))
            css = _HEADING_CSS.get(heading_el.tag, "capitulo_tit")
            blocks.append(
                _make_block(
                    section_id,
                    "section",
                    heading_text,
                    (Paragraph(css_class=css, text=heading_text),),
                    pub_date,
                    norm_id,
                )
            )

        # Recurse into children (skipping the heading we already processed)
        self._walk(section, blocks, norm_id, pub_date)

    def _parse_article(
        self,
        article,
        blocks: list[Block],
        norm_id: str,
        pub_date: date,
    ) -> None:
        """Parse an <article class="legalArticle"> into a Block."""
        article_id = article.get("id") or article.get("data-name") or f"art-{len(blocks)}"

        paragraphs: list[Paragraph] = []

        # Article heading (§ N. Title)
        header = article.find('.//*[@class="legalArticleHeader"]')
        if header is not None:
            header_text = _clean_text("".join(header.itertext()))
            if header_text:
                paragraphs.append(Paragraph(css_class="articulo", text=header_text))

        # Article body paragraphs and nested content
        for child in article:
            tag = child.tag if isinstance(child.tag, str) else ""
            cls = child.get("class") or ""

            # Skip heading (already processed) and amendment history
            if "legalArticleHeader" in cls:
                continue
            if any(_has_class(child, skip) for skip in _SKIP_CLASSES):
                continue

            if tag == "article" and ("legalP" in cls or "defaultP" in cls):
                text = _extract_inline_text(child)
                if text:
                    paragraphs.append(Paragraph(css_class="parrafo", text=text))

                # Check for nested lists inside the paragraph
                for sub in child:
                    if sub.tag in ("ul", "ol"):
                        for li in sub.iter("li"):
                            li_text = _extract_inline_text(li)
                            if li_text:
                                paragraphs.append(Paragraph(css_class="list_item", text=li_text))

            elif tag in ("ul", "ol"):
                for li in child.iter("li"):
                    li_text = _extract_inline_text(li)
                    if li_text:
                        paragraphs.append(Paragraph(css_class="list_item", text=li_text))

            elif tag == "table":
                md = _table_to_markdown(child)
                if md:
                    paragraphs.append(Paragraph(css_class="table_row", text=md))

        if paragraphs:
            title = paragraphs[0].text if paragraphs else ""
            blocks.append(
                _make_block(
                    article_id,
                    "article",
                    title,
                    tuple(paragraphs),
                    pub_date,
                    norm_id,
                )
            )

    def _parse_list(
        self,
        list_el,
        blocks: list[Block],
        norm_id: str,
        pub_date: date,
    ) -> None:
        """Parse a standalone <ul>/<ol> into a Block."""
        paragraphs: list[Paragraph] = []
        for li in list_el.iter("li"):
            text = _extract_inline_text(li)
            if text:
                paragraphs.append(Paragraph(css_class="list_item", text=text))

        if paragraphs:
            block_id = list_el.get("id") or f"list-{len(blocks)}"
            blocks.append(
                _make_block(
                    block_id,
                    "list",
                    "",
                    tuple(paragraphs),
                    pub_date,
                    norm_id,
                )
            )

    def extract_reforms(self, data: bytes) -> list[Any]:
        """No historical versions from public data dump.

        When the authenticated API becomes available, this method will
        parse changesToParent entries for reform dates.
        """
        return []


# ─── MetadataParser ───


# Map Lovdata legacy ID prefix to rank string.
_PREFIX_TO_RANK: dict[str, str] = {
    "LOV": "lov",
    "FOR": "forskrift",
}


class LovdataMetadataParser(MetadataParser):
    """Parse metadata from Lovdata XML-HTML header."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        tree = lxml_html.fromstring(data, parser=_HTML_PARSER)
        dl = tree.find('.//dl[@class="data-document-key-info"]')
        if dl is None:
            raise ValueError(f"No metadata <dl> found for {norm_id}")

        # Core fields
        legacy_id = _get_dd_text(dl, "legacyID")
        title = _get_dd_text(dl, "title")
        short_title = _get_dd_text(dl, "titleShort") or title
        department = _get_dd_text(dl, "ministry")

        # Identifier: use legacyID (e.g. LOV-2005-05-20-28)
        identifier = legacy_id or norm_id

        # Rank from legacy ID prefix
        prefix = identifier.split("-")[0] if "-" in identifier else ""
        rank = Rank(_PREFIX_TO_RANK.get(prefix, "lov"))

        # Special case: Constitution
        if identifier == "LOV-1814-05-17":
            rank = Rank("grunnlov")

        # Dates — cascade: dateOfPublication → dateInForce → legacyID → filename
        pub_date_str = _get_dd_text(dl, "dateOfPublication")
        pub_date = _parse_date_no(pub_date_str)
        if not pub_date:
            pub_date = _parse_date_no(_get_dd_text(dl, "dateInForce"))
        if not pub_date:
            pub_date = _legacy_id_to_date(identifier)
        if not pub_date:
            pub_date = _filename_to_date(norm_id) or date(1900, 1, 1)

        last_mod_str = _get_dd_text(dl, "lastChangeInForce")
        last_modified = _parse_date_no(last_mod_str)

        # Status: all laws in gjeldende-lover are in force by definition
        status = NormStatus.IN_FORCE

        # Subjects from legalArea
        subjects = tuple(_get_dd_list(dl, "legalArea"))

        # Source URL
        source = f"https://lovdata.no/dokument/NL/{_get_dd_text(dl, 'refid')}"

        # Extra fields — capture everything the source provides
        extra: list[tuple[str, str]] = []

        dokid = _get_dd_text(dl, "dokid")
        if dokid:
            extra.append(("dokid", dokid))

        refid = _get_dd_text(dl, "refid")
        if refid:
            extra.append(("refid", refid))

        date_in_force = _get_dd_text(dl, "dateInForce")
        if date_in_force:
            extra.append(("date_in_force", date_in_force))

        last_changed_by = _get_dd_text(dl, "lastChangedBy")
        if last_changed_by:
            extra.append(("last_changed_by", last_changed_by[:500]))

        changes_to = _get_dd_links(dl, "changesToDocuments")
        if changes_to:
            extra.append(("changes_to", ", ".join(changes_to)[:500]))

        eea_refs = _get_dd_text(dl, "eeaReferences")
        if eea_refs:
            extra.append(("eea_references", eea_refs[:500]))

        misc = _get_dd_text(dl, "miscInformation")
        if misc:
            extra.append(("misc_information", misc[:500]))

        based_on = _get_dd_text(dl, "basedOn")
        if based_on:
            extra.append(("based_on", based_on[:500]))

        return NormMetadata(
            title=title,
            short_title=short_title,
            identifier=identifier,
            country="no",
            rank=rank,
            publication_date=pub_date,
            status=status,
            department=department,
            source=source,
            last_modified=last_modified,
            subjects=subjects,
            extra=tuple(extra),
        )
