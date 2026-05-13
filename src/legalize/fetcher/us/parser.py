"""USLM XML parser for the US Code.

Parses chapter-level USLM XML (produced by OLRCClient) into the generic
Block / NormMetadata model.  Handles sections, subsections, tables,
bold/italic, footnotes, cross-references, editorial notes, and source
credits.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from xml.etree import ElementTree as ET

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    Rank,
    Version,
)

# Namespace constants.
USLM_NS = "http://xml.house.gov/schemas/uslm/1.0"
DC_NS = "http://purl.org/dc/elements/1.1/"
DCTERMS_NS = "http://purl.org/dc/terms/"
XHTML_NS = "http://www.w3.org/1999/xhtml"

_NS = f"{{{USLM_NS}}}"
_DC = f"{{{DC_NS}}}"
_DCTERMS = f"{{{DCTERMS_NS}}}"
_XHTML = f"{{{XHTML_NS}}}"

# Control characters to strip (C0/C1 minus tab, LF, CR).
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Elements whose text is rendered inline (not as separate paragraphs).
_INLINE_TAGS = frozenset(
    {
        "b",
        "i",
        "em",
        "strong",
        "sup",
        "sub",
        "u",
        "inline",
        "ref",
        "term",
        "shortTitle",
        "date",
        "num",
        "heading",
        "span",
        "a",
    }
)

# Elements to skip entirely (navigation, processing).
_SKIP_TAGS = frozenset(
    {
        "toc",
        "layout",
        "tocItem",
        "referenceItem",
        "page",
        "sidenote",
        "centerRunningHead",
    }
)


def _clean(text: str) -> str:
    """Normalize whitespace and strip control characters."""
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _tag(el: ET.Element) -> str:
    """Return the local tag name without namespace."""
    return el.tag.split("}")[-1] if "}" in el.tag else el.tag


# ---------------------------------------------------------------------------
# Inline text extraction (recursive, preserves bold/italic/refs)
# ---------------------------------------------------------------------------


def _inline_text(el: ET.Element) -> str:
    """Recursively extract text with inline Markdown formatting."""
    parts: list[str] = []

    if el.text:
        parts.append(el.text)

    for child in el:
        tag = _tag(child)

        if tag in _SKIP_TAGS:
            if child.tail:
                parts.append(child.tail)
            continue

        if tag in ("b", "strong"):
            inner = _inline_text(child).strip()
            if inner:
                parts.append(f"**{inner}**")
        elif tag in ("i", "em"):
            inner = _inline_text(child).strip()
            if inner:
                parts.append(f"*{inner}*")
        elif tag == "sup":
            inner = _inline_text(child).strip()
            if inner:
                parts.append(f"^{inner}")
        elif tag == "inline":
            css_class = child.get("class", "")
            inner = _inline_text(child).strip()
            if "smallCaps" in css_class and inner:
                parts.append(inner.upper())
            elif inner:
                parts.append(inner)
        elif tag == "ref":
            inner = _inline_text(child).strip()
            href = child.get("href", "")
            if inner and href:
                parts.append(f"[{inner}]({href})")
            elif inner:
                parts.append(inner)
        elif tag == "term":
            inner = _inline_text(child).strip()
            if inner:
                parts.append(f"**{inner}**")
        elif tag == "quotedText":
            inner = _inline_text(child).strip()
            if inner:
                parts.append(f'"{inner}"')
        elif tag == "date":
            inner = _inline_text(child).strip()
            if inner:
                parts.append(inner)
        elif tag == "footnote":
            # Render footnote inline as [^N].
            fn_id = child.get("id", "")
            parts.append(f"[^{fn_id}]")
        else:
            # Recurse into unknown elements.
            inner = _inline_text(child)
            if inner:
                parts.append(inner)

        if child.tail:
            parts.append(child.tail)

    return "".join(parts)


# ---------------------------------------------------------------------------
# Table parsing (XHTML tables inside USLM)
# ---------------------------------------------------------------------------


def _table_to_markdown(table_el: ET.Element) -> str:
    """Convert an XHTML <table> to a Markdown pipe table."""
    rows: list[list[str]] = []

    for tr in table_el.iter():
        tag = _tag(tr)
        if tag != "tr":
            continue
        cells: list[str] = []
        for cell in tr:
            cell_tag = _tag(cell)
            if cell_tag not in ("td", "th"):
                continue
            text = _clean(_inline_text(cell)).replace("|", "\\|")
            cells.append(text)
        if cells:
            rows.append(cells)

    if not rows:
        return ""

    max_cols = max(len(r) for r in rows)
    for r in rows:
        while len(r) < max_cols:
            r.append("")

    lines = []
    lines.append("| " + " | ".join(rows[0]) + " |")
    lines.append("| " + " | ".join("---" for _ in range(max_cols)) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Section / subsection parsing
# ---------------------------------------------------------------------------

_LEVEL_TAGS = frozenset(
    {
        "subsection",
        "paragraph",
        "subparagraph",
        "clause",
        "subclause",
        "item",
        "subitem",
        "subsubitem",
    }
)


def _parse_level(el: ET.Element, depth: int = 0) -> list[str]:
    """Recursively extract text lines from a subsection/paragraph/clause.

    Returns a flat list of text lines with proper indentation and numbering.
    """
    lines: list[str] = []

    # Number prefix (e.g., "(a)", "(1)", "(A)").
    num_el = el.find(f"{_NS}num")
    num_text = _clean(num_el.text or num_el.get("value", "")) if num_el is not None else ""

    # Heading (some subsections have inline headings).
    heading_el = el.find(f"{_NS}heading")
    heading = ""
    if heading_el is not None:
        heading = _clean(_inline_text(heading_el))

    # Chapeau (introductory text before sub-levels).
    chapeau_el = el.find(f"{_NS}chapeau")
    chapeau = ""
    if chapeau_el is not None:
        chapeau = _clean(_inline_text(chapeau_el))

    # Content (terminal text without sub-levels).
    content_el = el.find(f"{_NS}content")
    content = ""
    if content_el is not None:
        content = _clean(_inline_text(content_el))

    # Text (alternative to content in some elements).
    text_el = el.find(f"{_NS}text")
    text_direct = ""
    if text_el is not None:
        text_direct = _clean(_inline_text(text_el))

    # Build the line for this level.
    prefix = num_text
    body_parts = [p for p in [heading, chapeau, content, text_direct] if p]
    body = " ".join(body_parts)
    if prefix and body:
        line = f"{prefix} {body}"
    elif prefix:
        line = prefix
    elif body:
        line = body
    else:
        line = ""

    if line:
        lines.append(line)

    # Continuation text (after sub-levels).
    for cont in el.findall(f"{_NS}continuation"):
        cont_text = _clean(_inline_text(cont))
        if cont_text:
            lines.append(cont_text)

    # Recurse into sub-levels.
    for child in el:
        child_tag = _tag(child)
        if child_tag in _LEVEL_TAGS:
            lines.extend(_parse_level(child, depth + 1))

    return lines


def _parse_content(content_el: ET.Element) -> list[Paragraph]:
    """Parse a <content> element, respecting <p> children.

    USLM <content> may contain multiple <p> elements (e.g., list items
    with role='listItem').  Each <p> becomes its own Paragraph to
    preserve the original line breaks and list structure.
    """
    paragraphs: list[Paragraph] = []
    p_children = content_el.findall(f"{_NS}p")

    if p_children:
        # Content with explicit <p> elements — one paragraph per <p>.
        # Also capture any leading text before the first <p>.
        lead = _clean(content_el.text or "")
        if lead:
            paragraphs.append(Paragraph(css_class="parrafo", text=lead))

        for p in p_children:
            role = p.get("role", "")
            text = _clean(_inline_text(p))
            if not text:
                continue
            if role == "listItem":
                paragraphs.append(Paragraph(css_class="list_item", text=f"- {text}"))
            else:
                paragraphs.append(Paragraph(css_class="parrafo", text=text))
    else:
        # Simple content without <p> children.
        text = _clean(_inline_text(content_el))
        if text:
            paragraphs.append(Paragraph(css_class="parrafo", text=text))

    return paragraphs


def _parse_section(section_el: ET.Element) -> list[Paragraph]:
    """Parse a <section> element into a list of Paragraphs."""
    paragraphs: list[Paragraph] = []

    # Section number and heading.
    num_el = section_el.find(f"{_NS}num")
    heading_el = section_el.find(f"{_NS}heading")
    num_text = _clean(num_el.text or "") if num_el is not None else ""
    heading_text = _clean(_inline_text(heading_el)) if heading_el is not None else ""
    title = f"{num_text} {heading_text}".strip()

    if title:
        paragraphs.append(Paragraph(css_class="articulo", text=title))

    # Direct content (sections without subsections).
    content_el = section_el.find(f"{_NS}content")
    if content_el is not None:
        paragraphs.extend(_parse_content(content_el))

    # Subsections and deeper levels.
    for child in section_el:
        child_tag = _tag(child)
        if child_tag in _LEVEL_TAGS:
            for line in _parse_level(child):
                paragraphs.append(Paragraph(css_class="parrafo", text=line))

    # Source credit.
    for sc in section_el.findall(f"{_NS}sourceCredit"):
        sc_text = _clean(_inline_text(sc))
        if sc_text:
            paragraphs.append(Paragraph(css_class="parrafo", text=f"*{sc_text}*"))

    # Notes block (statutory notes, editorial notes, amendments).
    for notes_block in section_el.findall(f"{_NS}notes"):
        note_paras = _parse_notes(notes_block)
        paragraphs.extend(note_paras)

    return paragraphs


def _parse_notes(notes_el: ET.Element) -> list[Paragraph]:
    """Parse a <notes> block into paragraphs."""
    paragraphs: list[Paragraph] = []
    for note in notes_el.findall(f"{_NS}note"):
        heading_el = note.find(f"{_NS}heading")
        heading = _clean(_inline_text(heading_el)) if heading_el is not None else ""

        if heading:
            paragraphs.append(Paragraph(css_class="seccion", text=heading))

        for p in note.findall(f"{_NS}p"):
            text = _clean(_inline_text(p))
            if text:
                paragraphs.append(Paragraph(css_class="parrafo", text=text))

        # Tables inside notes.
        for table in note.iter():
            if _tag(table) == "table":
                md = _table_to_markdown(table)
                if md:
                    paragraphs.append(Paragraph(css_class="table", text=md))

    return paragraphs


# ---------------------------------------------------------------------------
# TextParser
# ---------------------------------------------------------------------------


class USTextParser(TextParser):
    """Parses a section-level USLM XML document into Block objects."""

    def parse_text(self, data: bytes) -> list[Any]:
        """Parse section XML into a list of Block objects.

        The uscDoc envelope contains one ``<section>`` element.  That
        section becomes a single Block with its paragraphs, notes, and
        source credits.
        """
        root = ET.fromstring(data)
        pub_date = self._extract_pub_date(root)

        section_el = root.find(f".//{_NS}section")
        if section_el is None:
            return []

        sec_id = section_el.get("identifier", "")
        num_el = section_el.find(f"{_NS}num")
        heading_el = section_el.find(f"{_NS}heading")
        sec_title = _clean(
            f"{(num_el.text or '') if num_el is not None else ''} "
            f"{_inline_text(heading_el) if heading_el is not None else ''}"
        )

        paragraphs = _parse_section(section_el)
        if not paragraphs:
            return []

        version = Version(
            norm_id=sec_id,
            publication_date=pub_date,
            effective_date=pub_date,
            paragraphs=tuple(paragraphs),
        )
        return [
            Block(
                id=sec_id,
                block_type="section",
                title=sec_title,
                versions=(version,),
            )
        ]

    # -- Internal helpers ---------------------------------------------------

    @staticmethod
    def _extract_pub_date(root: ET.Element) -> date:
        """Extract the publication date from <meta> or fall back to today."""
        # Try dcterms:created.
        created = root.find(f".//{_DCTERMS}created")
        if created is not None and created.text:
            try:
                return date.fromisoformat(created.text[:10])
            except ValueError:
                pass

        # Try docPublicationName "Online@{tag}" → look up release date.
        pub_name = root.find(f".//{_NS}docPublicationName")
        if pub_name is not None and pub_name.text:
            tag = pub_name.text.replace("Online@", "")
            from legalize.fetcher.us.client import RELEASE_POINTS

            for rp in RELEASE_POINTS:
                if rp["tag"] == tag:
                    return date.fromisoformat(rp["date"])

        return date.today()


# ---------------------------------------------------------------------------
# MetadataParser
# ---------------------------------------------------------------------------


class USMetadataParser(MetadataParser):
    """Extracts NormMetadata from a section-level USLM document."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        root = ET.fromstring(data)

        from legalize.fetcher.us.client import parse_norm_id

        title_num, section_id = parse_norm_id(norm_id)

        # Title-level metadata from <meta>.
        dc_title = root.find(f".//{_DC}title")
        title_heading = _clean(dc_title.text) if dc_title is not None else f"Title {title_num}"

        is_pos_law = root.find(f".//{_NS}property[@role='is-positive-law']")
        pub_name = root.find(f".//{_NS}docPublicationName")

        # Section-level metadata.
        section_el = root.find(f".//{_NS}section")
        sec_heading = ""
        if section_el is not None:
            num_el = section_el.find(f"{_NS}num")
            heading_el = section_el.find(f"{_NS}heading")
            num = _clean(num_el.text or "") if num_el is not None else ""
            heading = _clean(_inline_text(heading_el)) if heading_el is not None else ""
            sec_heading = f"{num} {heading}".strip()

        full_title = f"{sec_heading}" if sec_heading else f"{title_heading} § {section_id}"

        # Source credit (which Public Laws created/amended this section).
        source_credit = ""
        if section_el is not None:
            sc_el = section_el.find(f"{_NS}sourceCredit")
            if sc_el is not None:
                source_credit = _clean(_inline_text(sc_el))

        # Publication date.
        pub_date = USTextParser._extract_pub_date(root)

        # Source URL.
        source_url = (
            f"https://uscode.house.gov/view.xhtml"
            f"?req=granuleid:USC-prelim-title{title_num}-section{section_id}"
        )

        # Extra metadata.
        extra: list[tuple[str, str]] = []
        if is_pos_law is not None:
            extra.append(("positive_law", _clean(is_pos_law.text or "")))
        if pub_name is not None and pub_name.text:
            extra.append(("release_point", pub_name.text))
        extra.append(("title_number", str(title_num)))
        if source_credit:
            extra.append(("source_credit", source_credit[:500]))

        return NormMetadata(
            title=full_title,
            short_title=sec_heading or full_title,
            identifier=norm_id,
            country="us",
            rank=Rank("statute"),
            publication_date=pub_date,
            status=NormStatus.IN_FORCE,
            department="United States Congress",
            source=source_url,
            extra=tuple(extra),
        )
