"""EUR-Lex parser — European Union.

Parses consolidated XHTML from EUR-Lex / CELLAR into Block/Version/Paragraph
structures for the generic pipeline.

Handles two input formats:
1. Raw XHTML — single version (original or consolidated text)
2. ``<eurlex-multi-version>`` envelope — multiple versions bundled by the
   client, each wrapped in a ``<version>`` element with metadata attributes.

The XHTML uses CSS classes for semantic markup:
- ``eli-subdivision`` — structural container (article, chapter, title, annex)
- ``eli-container`` — main content wrapper
- ``title-article-norm`` / ``stitle-article-norm`` — article headings
- ``title-division-1`` / ``title-division-2`` — chapter/title headings
- ``title-annex-1`` — annex headings
- ``norm`` — body text paragraphs
- ``grid-container grid-list`` — lists (marker in column-1, content in column-2)
- ``boldface`` / ``italics`` / ``superscript`` — inline formatting spans
- ``arrow`` — modification markers (►B, ►M1, etc.)
- ``tbl-norm`` — table cell content
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any
from xml.etree import ElementTree as ET

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import Block, NormMetadata, NormStatus, Paragraph, Rank, Version

logger = logging.getLogger(__name__)

# XHTML namespace
_XHTML_NS = "http://www.w3.org/1999/xhtml"

# C0/C1 control characters to strip (keeps \n, \r, \t)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Whitespace normalization
_MULTI_SPACE_RE = re.compile(r"[ \t]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")

# ─── Rank mapping ───
_RTYPE_BASE = "http://publications.europa.eu/resource/authority/resource-type/"
_RANK_MAP: dict[str, str] = {
    "REG": "regulation",
    "REG_IMPL": "implementing_regulation",
    "REG_DEL": "delegated_regulation",
    "REG_FINANC": "financial_regulation",
}

# ─── Author mapping ───
_AUTHOR_BASE = "http://publications.europa.eu/resource/authority/corporate-body/"
_AUTHOR_MAP: dict[str, str] = {
    "EP": "European Parliament",
    "CONSIL": "Council of the European Union",
    "COM": "European Commission",
    "ECB": "European Central Bank",
}


def _xh(tag: str) -> str:
    """Build a fully-qualified XHTML tag name."""
    return f"{{{_XHTML_NS}}}{tag}"


def _tag(el: ET.Element) -> str:
    """Strip namespace from an element tag."""
    return el.tag.split("}")[-1] if "}" in el.tag else el.tag


# Modification markers inserted by EUR-Lex consolidated text system
_MOD_MARKER_RE = re.compile(r"\[?\*{0,2}[►▼][A-Z]\d*\*{0,2}\]?")
_MOD_END_RE = re.compile(r"\*{0,2}[◄▲]\*{0,2}")


def _clean(text: str) -> str:
    """Clean text: strip control chars, normalize whitespace."""
    text = _CONTROL_RE.sub("", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    return text.strip()


# Normalize list markers: ensure "(a) text" has exactly one space after marker.
# OJ format has "(a) " with HTML space, consolidated has "(a)" with no space.
# Also normalizes "1.   text" to "1. text".
_LIST_MARKER_RE = re.compile(r"^(\(?(?:\d+|[a-z]+|[ivxlcdm]+|[A-Z])\)?[.):]?)\s+")


def _strip_mod_markers(text: str) -> str:
    """Remove EUR-Lex modification markers (►M1, ◄, etc.) from text."""
    text = _MOD_MARKER_RE.sub("", text)
    text = _MOD_END_RE.sub("", text)
    # Clean up leftover formatting artifacts
    text = text.replace("****", "").replace("** **", " ")
    text = _MULTI_SPACE_RE.sub(" ", text)
    return text.strip()


def _normalize_list_marker(text: str) -> str:
    """Normalize whitespace after list markers for cross-format consistency.

    Ensures "(a) text", "(1) text", "1. text" always have exactly one space
    after the marker regardless of source format.
    """
    return _LIST_MARKER_RE.sub(r"\1 ", text)


def _extract_text(el: ET.Element) -> str:
    """Extract text from an element, preserving inline formatting as Markdown.

    Handles: <span class="boldface"> → **bold**, <span class="italics"> → *italic*,
    <span class="superscript"> → <sup>...</sup>, <a> → [text](href),
    <span class="no-parag"> → paragraph numbering.
    """
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        ctag = _tag(child)
        cls = child.get("class", "")
        child_text = _extract_text(child)

        if ctag == "span" and "boldface" in cls and child_text.strip():
            parts.append(f"**{child_text.strip()}**")
        elif ctag == "span" and "italics" in cls and child_text.strip():
            parts.append(f"*{child_text.strip()}*")
        elif ctag == "span" and "superscript" in cls and child_text.strip():
            parts.append(f"<sup>{child_text.strip()}</sup>")
        elif ctag == "span" and "no-parag" in cls:
            parts.append(child_text)
        elif ctag == "a" and child_text.strip():
            # Skip modification marker links (►M1, ►B, ◄)
            stripped = child_text.strip().replace("*", "")
            if "►" in stripped or "◄" in stripped or "▼" in stripped or "▲" in stripped:
                pass  # Skip
            else:
                href = child.get("href", "")
                if href and not href.startswith("#"):
                    parts.append(f"[{child_text.strip()}]({href})")
                else:
                    parts.append(child_text)
        elif ctag == "br":
            parts.append("\n")
        elif ctag == "sup" and child_text.strip():
            parts.append(f"<sup>{child_text.strip()}</sup>")
        else:
            parts.append(child_text)

        if child.tail:
            parts.append(child.tail)

    result = "".join(parts)
    # Strip modification markers and normalize list marker whitespace
    result = _strip_mod_markers(result)
    return _normalize_list_marker(result)


def _parse_list(el: ET.Element) -> str:
    """Parse a grid-container grid-list into Markdown list format."""
    marker = ""
    content = ""
    for child in el:
        cls = child.get("class", "")
        if "grid-list-column-1" in cls:
            # Extract the list marker (e.g., "(a)", "1.", "—")
            marker = _extract_text(child).strip()
        elif "grid-list-column-2" in cls:
            # Extract content — may contain nested lists
            sub_parts: list[str] = []
            for sub in child:
                sub_cls = sub.get("class", "")
                if "grid-container" in sub_cls and "grid-list" in sub_cls:
                    sub_parts.append(_parse_list(sub))
                else:
                    text = _extract_text(sub).strip()
                    if text:
                        sub_parts.append(text)
            content = "\n".join(sub_parts)
    if marker and content:
        # Indent continuation lines for nested lists
        lines = content.split("\n")
        first = f"{marker} {lines[0]}"
        rest = [f"   {line}" if line.strip() else "" for line in lines[1:]]
        return "\n".join([first] + rest)
    return content


def _is_list_table(table_el: ET.Element) -> bool:
    """Detect if a table is actually a layout-table used for lists (OJ format).

    OJ texts use ``<table border="0">`` with 2 columns (narrow marker + wide
    content) to lay out numbered lists and definitions. These should be parsed
    as list items, not as Markdown pipe tables.
    """
    if table_el.get("border") != "0":
        return False
    cols = list(table_el.iter(_xh("col")))
    if len(cols) != 2:
        return False
    # Check column widths: first column narrow (≤10%), second wide
    first_width = cols[0].get("width", "")
    if not first_width:
        return False
    try:
        w = int(first_width.rstrip("%"))
        return w <= 10
    except ValueError:
        return False


def _parse_list_table(table_el: ET.Element) -> list[Paragraph]:
    """Parse an OJ list-table into list Paragraphs.

    Each row is one list item: first cell is the marker, second is the content.
    The content cell may contain nested list-tables (sub-lists).
    """
    paragraphs: list[Paragraph] = []
    for tr in table_el.iter(_xh("tr")):
        cells = [c for c in tr if _tag(c) in ("td", "th")]
        if len(cells) < 2:
            continue
        marker = _extract_text(cells[0]).strip()
        # Process content cell — may have nested list-tables
        content_parts: list[str] = []
        nested_paras: list[Paragraph] = []
        for child in cells[1]:
            ctag = _tag(child)
            if ctag == "table" and _is_list_table(child):
                nested_paras.extend(_parse_list_table(child))
            elif ctag == "p":
                text = _extract_text(child).strip()
                if text:
                    content_parts.append(text)
            elif ctag == "div":
                # May contain nested structures
                for sub in child:
                    stag = _tag(sub)
                    if stag == "table" and _is_list_table(sub):
                        nested_paras.extend(_parse_list_table(sub))
                    elif stag == "p":
                        text = _extract_text(sub).strip()
                        if text:
                            content_parts.append(text)

        content = "\n".join(content_parts)
        if marker and content:
            lines = content.split("\n")
            first = f"{marker} {lines[0]}"
            rest = [f"   {line}" if line.strip() else "" for line in lines[1:]]
            text = "\n".join([first] + rest)
            paragraphs.append(Paragraph("list", text))
        elif content:
            paragraphs.append(Paragraph("abs", content))

        # Add nested list items
        paragraphs.extend(nested_paras)

    return paragraphs


def _parse_table(table_el: ET.Element) -> str:
    """Convert an HTML data table to a Markdown pipe table."""
    rows: list[list[str]] = []
    for tr in table_el.iter(_xh("tr")):
        cells: list[str] = []
        for cell in tr:
            ctag = _tag(cell)
            if ctag in ("td", "th"):
                text = _extract_text(cell).strip()
                # Clean up multi-line content in cells
                text = text.replace("\n", " ").strip()
                text = _MULTI_SPACE_RE.sub(" ", text)
                cells.append(text)
        if cells:
            rows.append(cells)

    if not rows:
        return ""

    # Normalize column count
    max_cols = max(len(r) for r in rows)
    for row in rows:
        while len(row) < max_cols:
            row.append("")

    # Build pipe table
    lines: list[str] = []
    # Header row
    lines.append("| " + " | ".join(rows[0]) + " |")
    # Separator
    lines.append("| " + " | ".join("---" for _ in range(max_cols)) + " |")
    # Data rows
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def _walk_body(el: ET.Element, depth: int = 0) -> list[Paragraph]:
    """Recursively walk the XHTML body and convert to paragraphs.

    Processes the structural hierarchy: eli-container > eli-subdivision >
    articles/chapters/titles, extracting headings, body text, lists, and tables.
    """
    paragraphs: list[Paragraph] = []
    tag = _tag(el)
    cls = el.get("class", "")

    # Skip arrow/modification markers and disclaimers
    if "arrow" in cls or "disclaimer" in cls or "modref" in cls:
        return paragraphs

    # Skip header tables (amendment lists before the content)
    if "hd-modifiers" in cls or "hd-toc" in cls:
        return paragraphs

    # Headings
    if "title-division-1" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("h2", text))
        return paragraphs

    if "title-division-2" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("h3", text))
        return paragraphs

    # Check stitle BEFORE title (stitle-article-norm contains title-article-norm)
    if "stitle-article-norm" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("h5", text))
        return paragraphs

    if "title-article-norm" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("h4", text))
        return paragraphs

    if "title-annex-1" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("h2", text))
        return paragraphs

    if "title-gr-seq-level-1" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("h3", text))
        return paragraphs

    if "title-gr-seq-level-2" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("h4", text))
        return paragraphs

    # Main title block
    if "eli-main-title" in cls:
        parts: list[str] = []
        for child in el:
            text = _extract_text(child).strip()
            if text:
                parts.append(text)
        if parts:
            paragraphs.append(Paragraph("h1", " ".join(parts)))
        return paragraphs

    # Lists
    if "grid-container" in cls and "grid-list" in cls:
        text = _parse_list(el)
        if text:
            paragraphs.append(Paragraph("list", text))
        return paragraphs

    # Tables — detect list-tables vs data tables
    if tag == "table":
        if _is_list_table(el):
            paragraphs.extend(_parse_list_table(el))
        else:
            text = _parse_table(el)
            if text:
                paragraphs.append(Paragraph("table", text))
        return paragraphs

    # ─── OJ (Official Journal) format classes ───
    # Original texts use oj-* classes instead of the consolidated-text classes.
    if "oj-ti-section-1" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("h2", text))
        return paragraphs

    if "oj-ti-section-2" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("h3", text))
        return paragraphs

    # Check oj-sti-art BEFORE oj-ti-art (same substring issue)
    if "oj-sti-art" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("h5", text))
        return paragraphs

    if "oj-ti-art" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("h4", text))
        return paragraphs

    if "oj-doc-ti" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("h1", text))
        return paragraphs

    if "oj-normal" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("abs", text))
        return paragraphs

    if "oj-signatory" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("signature", text))
        return paragraphs

    # Skip OJ notes (footnotes in OJ format)
    if "oj-note" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("footnote", text))
        return paragraphs

    # ─── Consolidated text format classes ───
    # Indented divs with margin-left (old consolidated format for list items).
    # Pattern: <div style="margin-left: 30pt; text-indent: -30pt"><p class="norm">(a) ...</p></div>
    if tag == "div" and not cls:
        style = el.get("style", "")
        if "margin-left" in style and "text-indent" in style:
            text = _extract_text(el).strip()
            if text:
                paragraphs.append(Paragraph("list", text))
            return paragraphs

    # <p class="list"> — old consolidated format for list items
    if tag == "p" and cls == "list":
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("list", text))
        return paragraphs

    # Normal text paragraphs (norm, normal, tbl-norm, item-none)
    if tag == "p" and ("norm" in cls or "tbl-norm" in cls or "item-none" in cls or cls == "normal"):
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("abs", text))
        return paragraphs

    # Footnotes
    if "footnote" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("footnote", text))
        return paragraphs

    # Title doc paragraphs (in preamble area)
    if "title-doc-first" in cls or "title-doc-last" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("preamble", text))
        return paragraphs

    # OJ reference
    if "title-doc-oj-reference" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("preamble", text))
        return paragraphs

    # Separator — skip
    if tag == "hr":
        return paragraphs

    # Reference line at top
    if "reference" in cls:
        return paragraphs

    # Plain paragraphs (no CSS class) — common in old HTML4 format.
    # Detect "Article N" as headings for structural consistency.
    if tag == "p" and not cls:
        text = _extract_text(el).strip()
        if text:
            if re.match(r"^Article\s+\d+\w*\s*$", text):
                paragraphs.append(Paragraph("h4", text))
            else:
                paragraphs.append(Paragraph("abs", text))
        return paragraphs

    # <h1> tags in old HTML (CELEX number as title)
    if tag == "h1":
        return paragraphs  # Skip — CELEX is not the title

    # <strong> as title in old HTML
    if tag == "strong":
        text = _extract_text(el).strip()
        if text and len(text) > 20:
            paragraphs.append(Paragraph("h1", text))
        return paragraphs

    # Container divs — recurse
    if tag in ("div", "body", "html"):
        for child in el:
            ctag = _tag(child)
            child_cls = child.get("class", "")

            # Skip amendment header tables (but keep list-tables and data tables)
            if ctag == "table" and not _is_content_table(child) and not _is_list_table(child):
                continue

            # Skip arrow markers
            if "arrow" in child_cls:
                continue
            if "hd-modifiers" in child_cls:
                continue
            if ctag == "table" and _is_amendment_table(child):
                continue

            paragraphs.extend(_walk_body(child, depth + 1))

    return paragraphs


def _is_content_table(table_el: ET.Element) -> bool:
    """Check if a table is content (vs. header/amendment metadata)."""
    # Content tables have border="1" or tbl-norm cells
    if table_el.get("border") == "1":
        return True
    for p in table_el.iter(_xh("p")):
        if "tbl-norm" in (p.get("class", "")):
            return True
    return False


def _is_amendment_table(table_el: ET.Element) -> bool:
    """Check if a table is an amendment list table in the header."""
    for p in table_el.iter(_xh("p")):
        cls = p.get("class", "")
        if "arrow" in cls or "hd-toc" in cls or "title-fam-member" in cls:
            return True
    return False


def _parse_xhtml_to_paragraphs(data: bytes) -> list[Paragraph]:
    """Parse XHTML or HTML bytes into a flat list of Paragraphs.

    Tries strict XML parsing first (for XHTML). Falls back to lxml.html
    for old HTML4 documents that aren't valid XML.
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        # Old HTML4 — parse with lxml.html (permissive) and convert to ET
        from lxml import html as lxml_html

        doc = lxml_html.fromstring(data)
        # lxml.html uses no namespace; _walk_body checks _tag() which strips ns
        # Convert lxml tree to ET tree for uniform processing
        raw_xml = lxml_html.tostring(doc, encoding="unicode", method="xml")
        root = ET.fromstring(raw_xml)

    # Find the eli-container (main content area)
    container = root.find(f".//{_xh('div')}[@class='eli-container']")
    if container is not None:
        return _walk_body(container)

    # Fallback for old HTML: no namespace, look for plain tags
    container = root.find(".//div[@class='eli-container']")
    if container is not None:
        return _walk_body(container)

    # Fallback: walk the body (with or without namespace)
    body = root.find(f".//{_xh('body')}")
    if body is None:
        body = root.find(".//body")
    if body is not None:
        return _walk_body(body)

    return _walk_body(root)


class EURLexTextParser(TextParser):
    """Parse EUR-Lex XHTML into Block/Version/Paragraph structures."""

    def parse_text(self, data: bytes) -> list[Any]:
        """Parse consolidated XHTML into a list of Block objects.

        Handles both raw XHTML (single version) and the
        ``<eurlex-multi-version>`` envelope (multiple versions).
        """
        # Check if this is a multi-version envelope
        if b"<eurlex-multi-version" in data[:200]:
            return self._parse_multi_version(data)

        # Single version — parse as-is
        paragraphs = _parse_xhtml_to_paragraphs(data)
        if not paragraphs:
            return []

        today = date.today()
        version = Version(
            norm_id="",
            publication_date=today,
            effective_date=today,
            paragraphs=tuple(paragraphs),
        )
        return [Block(id="main", block_type="content", title="", versions=(version,))]

    def _parse_multi_version(self, data: bytes) -> list[Block]:
        """Parse a multi-version envelope into blocks with version history."""
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            # Envelope contains old HTML (not valid XML) inside <version> tags.
            # Extract each <version>...</version> block as raw bytes and parse
            # them individually with the tolerant HTML parser.
            return self._parse_multi_version_html_fallback(data)
        celex = root.get("celex", "")

        versions: list[Version] = []
        for version_el in root:
            if not version_el.tag.endswith("version") and version_el.tag != "version":
                continue

            effective_date_str = version_el.get("effective-date", "")
            try:
                effective_date = date.fromisoformat(effective_date_str)
            except (ValueError, TypeError):
                effective_date = date.today()

            # Find the XHTML content inside this version element
            # It could be a full <html> document or just elements
            xhtml_root = version_el.find(f"{_xh('html')}")
            if xhtml_root is None:
                # Try without namespace
                xhtml_root = version_el.find("html")
            if xhtml_root is None:
                # The content might be directly inside <version>
                xhtml_root = version_el

            container = xhtml_root.find(f".//{_xh('div')}[@class='eli-container']")
            if container is not None:
                paragraphs = _walk_body(container)
            else:
                body = xhtml_root.find(f".//{_xh('body')}")
                if body is not None:
                    paragraphs = _walk_body(body)
                else:
                    paragraphs = _walk_body(xhtml_root)

            if paragraphs:
                versions.append(
                    Version(
                        norm_id=celex,
                        publication_date=effective_date,
                        effective_date=effective_date,
                        paragraphs=tuple(paragraphs),
                    )
                )

        if not versions:
            return []

        return [Block(id="main", block_type="content", title="", versions=tuple(versions))]

    def _parse_multi_version_html_fallback(self, data: bytes) -> list[Block]:
        """Fallback for multi-version envelopes containing old HTML.

        Extracts each ``<version ...>...</version>`` block via regex,
        parses the inner content with the tolerant HTML parser.
        """
        celex_match = re.search(rb"celex='([^']+)'", data[:200])
        celex = celex_match.group(1).decode() if celex_match else ""

        versions: list[Version] = []
        # Split on <version> tags
        for m in re.finditer(
            rb"<version\s+type='(\w+)'\s*(?:effective-date='([^']*)')?\s*>(.*?)</version>",
            data,
            re.DOTALL,
        ):
            date_str = m.group(2).decode() if m.group(2) else ""
            inner = m.group(3)

            try:
                effective_date = date.fromisoformat(date_str)
            except (ValueError, TypeError):
                effective_date = date.today()

            paragraphs = _parse_xhtml_to_paragraphs(inner)

            if paragraphs:
                versions.append(
                    Version(
                        norm_id=celex,
                        publication_date=effective_date,
                        effective_date=effective_date,
                        paragraphs=tuple(paragraphs),
                    )
                )

        if not versions:
            return []

        return [Block(id="main", block_type="content", title="", versions=tuple(versions))]

    def extract_reforms(self, data: bytes) -> list[Any]:
        """Extract reform timeline from the multi-version envelope.

        Each consolidated version corresponds to a reform event.
        """
        from legalize.models import Reform

        if b"<eurlex-multi-version" not in data[:200]:
            return []

        # Extract version dates via regex (works for both valid XML and
        # envelopes containing old HTML that isn't valid XML).
        celex_match = re.search(rb"celex='([^']+)'", data[:200])
        celex = celex_match.group(1).decode() if celex_match else ""
        reforms: list[Reform] = []

        for m in re.finditer(rb"<version\s+[^>]*effective-date='([^']+)'", data):
            date_str = m.group(1).decode()
            try:
                effective_date = date.fromisoformat(date_str)
            except (ValueError, TypeError):
                continue

            reforms.append(
                Reform(
                    date=effective_date,
                    norm_id=celex,
                    affected_blocks=("main",),
                )
            )

        return reforms


class EURLexMetadataParser(MetadataParser):
    """Parse EUR-Lex SPARQL metadata JSON into NormMetadata."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        """Parse SPARQL JSON results into NormMetadata."""
        result = json.loads(data)
        bindings = result.get("results", {}).get("bindings", [])

        if not bindings:
            raise ValueError(f"No metadata found for {norm_id}")

        # Take the first binding (may be duplicated due to multiple authors/dates)
        first = bindings[0]

        # Title
        title = first.get("title", {}).get("value", norm_id)
        # Clean up title — remove "(Text with EEA relevance)" suffix
        short_title = title
        for suffix in ["(Text with EEA relevance)", "(Text with EEA relevance) "]:
            short_title = short_title.replace(suffix, "").strip()
        # Extract a shorter title if possible (after "on ..." part)
        on_match = re.search(r"\bon\b\s+(.+?)(?:\s*\(|$)", short_title)
        if on_match:
            short_title = on_match.group(1).rstrip(" .,")

        # CELEX
        celex = first.get("celex", {}).get("value", norm_id)

        # ELI
        eli = first.get("eli", {}).get("value", "")

        # Date
        date_str = first.get("date", {}).get("value", "")
        try:
            pub_date = date.fromisoformat(date_str)
        except (ValueError, TypeError):
            pub_date = date.today()

        # Entry into force — may have multiple values, take the earliest
        entry_force_dates: list[date] = []
        for b in bindings:
            ef_str = b.get("entryForce", {}).get("value", "")
            if ef_str:
                try:
                    entry_force_dates.append(date.fromisoformat(ef_str))
                except ValueError:
                    pass
        entry_force = min(entry_force_dates) if entry_force_dates else None

        # End of validity
        end_validity_str = first.get("endValidity", {}).get("value", "")
        end_validity = None
        if end_validity_str and end_validity_str != "9999-12-31":
            try:
                end_validity = date.fromisoformat(end_validity_str)
            except ValueError:
                pass

        # In-force status
        force_val = first.get("force", {}).get("value", "")
        if force_val in ("1", "true"):
            status = NormStatus.IN_FORCE
        else:
            status = NormStatus.REPEALED

        # Resource type → rank
        rtype_uri = first.get("rtype", {}).get("value", "")
        rtype_code = rtype_uri.replace(_RTYPE_BASE, "")
        rank = Rank(_RANK_MAP.get(rtype_code, "regulation"))

        # Authors — collect all unique
        authors: list[str] = []
        seen_authors: set[str] = set()
        for b in bindings:
            author_uri = b.get("author", {}).get("value", "")
            if author_uri:
                author_code = author_uri.replace(_AUTHOR_BASE, "")
                author_name = _AUTHOR_MAP.get(author_code, author_code)
                if author_name not in seen_authors:
                    seen_authors.add(author_name)
                    authors.append(author_name)
        department = ", ".join(authors) if authors else "European Union"

        # Source URL
        source = (
            eli if eli else f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"
        )

        # Extra metadata
        extra_fields: list[tuple[str, str]] = []
        if eli:
            extra_fields.append(("eli", eli))
        if entry_force:
            extra_fields.append(("entry_into_force", entry_force.isoformat()))
        if end_validity:
            extra_fields.append(("end_of_validity", end_validity.isoformat()))
        extra_fields.append(("celex", celex))
        extra_fields.append(("regulation_type", rtype_code))

        return NormMetadata(
            title=title,
            short_title=short_title,
            identifier=celex,
            country="eu",
            rank=rank,
            publication_date=pub_date,
            status=status,
            department=department,
            source=source,
            extra=tuple(extra_fields),
        )
