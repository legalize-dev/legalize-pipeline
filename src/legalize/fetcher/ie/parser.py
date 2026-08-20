"""Text and metadata parsers for Irish Statute Book (ISB) legislation.

Parses ISB XML (custom format with <act>, <body>, <part>, <chapter>,
<sect>, <p>) into Block/Version/Paragraph and Oireachtas API JSON
into NormMetadata.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any
from lxml import etree

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import Block, NormMetadata, NormStatus, Paragraph, Rank, Version
from legalize.fetcher._text import strip_control

logger = logging.getLogger(__name__)

# Module-level accumulator for footnote definitions collected during
# _inline_text() calls.  Cleared by the parser after each act.
_footnote_defs: list[tuple[str, str]] = []

# ISB special entity elements → Unicode replacements.
_ENTITY_MAP: dict[str, str] = {
    "ifada": "\u00ed",  # í
    "afada": "\u00e1",  # á
    "ufada": "\u00fa",  # ú
    "ofada": "\u00f3",  # ó
    "efada": "\u00e9",  # é
    "Ifada": "\u00cd",  # Í
    "Afada": "\u00c1",  # Á
    "Ufada": "\u00da",  # Ú
    "Ofada": "\u00d3",  # Ó
    "Efada": "\u00c9",  # É
    "emdash": "\u2014",  # —
    "euro": "\u20ac",  # €
    "pound": "\u00a3",  # £
    "odq": "\u201c",  # "
    "cdq": "\u201d",  # "
    "osq": "\u2018",  # '
    "csq": "\u2019",  # '
    "bull": "\u2022",  # •
}

# Tags to skip entirely (decorative or binary).
_SKIP_TAGS = frozenset({"graphic", "hr1"})


# ── Inline text extraction ──────────────────────────────────────────


def _inline_text(elem: etree._Element) -> str:
    """Extract text from an element, resolving ISB entities and inline formatting.

    Walks child nodes recursively:
    - <b>/<strong> → **text**
    - <i>/<em> → *text*
    - <su> → ^text (superscript)
    - <sb> → text (subscript, no MD equivalent)
    - <font> → recurse into children
    - <xref> → [text](#href) or just text
    - <fn> → [^N] footnote marker
    - Entity tags (ifada, emdash, etc.) → Unicode char
    - Skip tags (graphic, hr1) → empty
    """
    parts: list[str] = []

    # Leading text
    if elem.text:
        parts.append(elem.text)

    for child in elem:
        tag = child.tag if isinstance(child.tag, str) else ""

        # Entity replacements
        if tag in _ENTITY_MAP:
            parts.append(_ENTITY_MAP[tag])
            if child.tail:
                parts.append(child.tail)
            continue

        # Skip decorative tags
        if tag in _SKIP_TAGS:
            if child.tail:
                parts.append(child.tail)
            continue

        # Bold
        if tag in ("b", "strong"):
            inner = _inline_text(child).strip()
            if inner:
                parts.append(f"**{inner}**")
            if child.tail:
                parts.append(child.tail)
            continue

        # Italic
        if tag in ("i", "em"):
            inner = _inline_text(child).strip()
            if inner:
                parts.append(f"*{inner}*")
            if child.tail:
                parts.append(child.tail)
            continue

        # Superscript
        if tag == "su":
            inner = _inline_text(child).strip()
            if inner:
                parts.append(f"^{inner}")
            if child.tail:
                parts.append(child.tail)
            continue

        # Subscript (no MD equivalent, keep as-is)
        if tag == "sb":
            parts.append(_inline_text(child))
            if child.tail:
                parts.append(child.tail)
            continue

        # Cross-references — preserve href as markdown link
        if tag == "xref":
            inner = _inline_text(child).strip()
            href = child.get("href", "")
            if inner and href:
                parts.append(f"[{inner}]({href})")
            else:
                parts.append(inner)
            if child.tail:
                parts.append(child.tail)
            continue

        # Footnotes: extract marker number and collect body text
        if tag == "fn":
            marker = child.find(".//marker")
            if marker is not None:
                num = _inline_text(marker).strip().lstrip("^")
                parts.append(f"[^{num}]")
                # Collect footnote body text for definitions block
                body_parts = []
                for fn_child in child:
                    fn_tag = fn_child.tag if isinstance(fn_child.tag, str) else ""
                    if fn_tag == "marker":
                        continue  # Already handled above
                    if fn_tag == "p":
                        fn_text = _inline_text(fn_child).strip()
                        if fn_text:
                            body_parts.append(fn_text)
                    elif fn_tag:
                        fn_text = _inline_text(fn_child).strip()
                        if fn_text:
                            body_parts.append(fn_text)
                if body_parts:
                    _footnote_defs.append((num, " ".join(body_parts)))
            if child.tail:
                parts.append(child.tail)
            continue

        # Font tags: recurse
        if tag == "font":
            parts.append(_inline_text(child))
            if child.tail:
                parts.append(child.tail)
            continue

        # Marker (inside fn, handled above; standalone = skip)
        if tag == "marker":
            if child.tail:
                parts.append(child.tail)
            continue

        # Fallback: recurse into unknown tags
        parts.append(_inline_text(child))
        if child.tail:
            parts.append(child.tail)

    text = "".join(parts)
    text = strip_control(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ── Table conversion ────────────────────────────────────────────────


def _table_to_markdown(table_elem: etree._Element) -> str:
    """Convert an ISB <table> element to a Markdown pipe table.

    Handles:
    - Multi-paragraph cells (joined with space)
    - colspan (cell text repeated across spanned columns)
    - rowspan (cell text propagated to subsequent rows)
    - Bold headers

    Uses a pending-cell dict for rowspan, following the LV parser pattern.
    """
    # First pass: collect raw cell data with colspan/rowspan info
    raw_rows: list[list[tuple[str, int, int]]] = []  # [(text, colspan, rowspan), ...]

    for tr in table_elem.findall(".//tr"):
        row_cells: list[tuple[str, int, int]] = []
        for td in tr.findall("td"):
            # Cell may contain multiple <p> elements
            cell_parts = []
            for p in td.findall("p"):
                text = _inline_text(p)
                if text:
                    cell_parts.append(text)

            # If no <p> children, try direct text
            if not cell_parts:
                text = _inline_text(td)
                if text:
                    cell_parts.append(text)

            cell_text = " ".join(cell_parts)
            # Escape pipes in cell content
            cell_text = cell_text.replace("|", "\\|")

            colspan = int(td.get("colspan", "1"))
            rowspan = int(td.get("rowspan", "1"))
            row_cells.append((cell_text, colspan, rowspan))

        if row_cells:
            raw_rows.append(row_cells)

    if not raw_rows:
        return ""

    # Second pass: resolve colspan and rowspan into a regular grid
    rows: list[list[str]] = []
    pending: dict[int, tuple[str, int]] = {}  # col -> (text, rows_remaining)

    for raw_row in raw_rows:
        out_row: list[str] = []
        col = 0
        cell_idx = 0

        while cell_idx < len(raw_row) or col in pending:
            if col in pending:
                text, remaining = pending[col]
                out_row.append(text)
                if remaining > 1:
                    pending[col] = (text, remaining - 1)
                else:
                    del pending[col]
                col += 1
            elif cell_idx < len(raw_row):
                text, colspan, rowspan = raw_row[cell_idx]
                for _ in range(colspan):
                    out_row.append(text)
                    if rowspan > 1:
                        pending[col] = (text, rowspan - 1)
                    col += 1
                cell_idx += 1
            else:
                break

        rows.append(out_row)

    # Normalize column count
    max_cols = max(len(r) for r in rows)
    for row in rows:
        while len(row) < max_cols:
            row.append("")

    lines = []
    for i, row in enumerate(rows):
        lines.append("| " + " | ".join(row) + " |")
        # Add separator after first row (header)
        if i == 0:
            lines.append("| " + " | ".join("---" for _ in row) + " |")

    return "\n".join(lines)


# ── Paragraph class → css_class mapping ─────────────────────────────

# ISB uses a numeric class: "-3 11 0 left 1 0" where the second
# number is the indentation level. Higher = deeper nesting.
# We don't use this for heading detection; instead we use
# structural XML tags (<part>, <chapter>, <sect>).


# ── Text parser ─────────────────────────────────────────────────────


class ISBTextParser(TextParser):
    """Parse ISB XML or HTML into Block objects."""

    def parse_text(self, data: bytes) -> list[Any]:
        """Parse Act text into a list of Blocks.

        Auto-detects XML vs HTML:
        - XML: ISB custom format (<act>, <body>, <part>, <sect>)
        - HTML: ISB print view (<div class="act-content">, <tr>, <td>)

        All content is flattened into a single Block with one Version.
        """
        # Detect format: XML starts with <?xml or <act, HTML with <!DOCTYPE or <html
        stripped = data.lstrip()
        if stripped.startswith(b"<?xml") or stripped.startswith(b"<act"):
            return self._parse_xml(data)
        return self._parse_html(data)

    def _parse_xml(self, data: bytes) -> list[Any]:
        """Parse ISB XML format (acts with XML available, ~1995+)."""
        root = etree.fromstring(data)
        paragraphs: list[Paragraph] = []

        # Extract metadata for the Version
        meta_el = root.find("metadata")
        pub_date = date(1970, 1, 1)
        if meta_el is not None:
            doe = meta_el.findtext("dateofenactment") or ""
            if len(doe) == 8:
                try:
                    pub_date = date(int(doe[:4]), int(doe[4:6]), int(doe[6:8]))
                except ValueError:
                    pass

        # Skip frontmatter (table of contents) — redundant with body
        body = root.find("body")
        if body is None:
            return []

        self._parse_body(body, paragraphs)

        # Parse backmatter (schedules, tables, notes)
        backmatter = root.find("backmatter")
        if backmatter is not None:
            self._parse_backmatter(backmatter, paragraphs)

        # Flush collected footnote definitions (pattern: UK parser)
        if _footnote_defs:
            paragraphs.append(Paragraph(css_class="h2", text="Footnotes"))
            for fn_num, fn_body in _footnote_defs:
                paragraphs.append(Paragraph(css_class="parrafo", text=f"[^{fn_num}]: {fn_body}"))
            _footnote_defs.clear()

        if not paragraphs:
            return []

        block = Block(
            id="full-text",
            block_type="document",
            title="",
            versions=(
                Version(
                    norm_id="",
                    publication_date=pub_date,
                    effective_date=pub_date,
                    paragraphs=tuple(paragraphs),
                ),
            ),
        )
        return [block]

    def _parse_body(self, body: etree._Element, paragraphs: list[Paragraph]) -> None:
        """Walk the body element tree and emit paragraphs."""
        for child in body:
            tag = child.tag if isinstance(child.tag, str) else ""

            if tag == "part":
                self._parse_part(child, paragraphs)
            elif tag == "chapter":
                self._parse_chapter(child, paragraphs)
            elif tag == "sect":
                self._parse_section(child, paragraphs)
            elif tag == "schedule":
                self._parse_schedule(child, paragraphs)
            elif tag == "p":
                self._parse_paragraph(child, paragraphs)
            elif tag == "table":
                md = _table_to_markdown(child)
                if md:
                    paragraphs.append(Paragraph(css_class="parrafo", text=md))

    def _parse_part(self, part: etree._Element, paragraphs: list[Paragraph]) -> None:
        """Parse a <part> element."""
        title_el = part.find("title")
        if title_el is not None:
            title_text = _inline_text(title_el)
            if title_text:
                paragraphs.append(Paragraph(css_class="titulo_tit", text=title_text))

        for child in part:
            tag = child.tag if isinstance(child.tag, str) else ""
            if tag == "chapter":
                self._parse_chapter(child, paragraphs)
            elif tag == "sect":
                self._parse_section(child, paragraphs)
            elif tag == "p":
                self._parse_paragraph(child, paragraphs)
            elif tag == "table":
                md = _table_to_markdown(child)
                if md:
                    paragraphs.append(Paragraph(css_class="parrafo", text=md))
            elif tag == "schedule":
                self._parse_schedule(child, paragraphs)

    def _parse_chapter(self, chapter: etree._Element, paragraphs: list[Paragraph]) -> None:
        """Parse a <chapter> element."""
        title_el = chapter.find("title")
        if title_el is not None:
            title_text = _inline_text(title_el)
            if title_text:
                paragraphs.append(Paragraph(css_class="capitulo_tit", text=title_text))

        for child in chapter:
            tag = child.tag if isinstance(child.tag, str) else ""
            if tag == "sect":
                self._parse_section(child, paragraphs)
            elif tag == "p":
                self._parse_paragraph(child, paragraphs)
            elif tag == "table":
                md = _table_to_markdown(child)
                if md:
                    paragraphs.append(Paragraph(css_class="parrafo", text=md))

    def _parse_section(self, sect: etree._Element, paragraphs: list[Paragraph]) -> None:
        """Parse a <sect> element (a numbered section/article)."""
        # Section heading: number + title
        number_el = sect.find("number")
        title_el = sect.find("title")

        heading_parts = []
        if number_el is not None:
            num_text = _inline_text(number_el)
            if num_text:
                heading_parts.append(num_text)
        if title_el is not None:
            title_text = _inline_text(title_el)
            if title_text:
                heading_parts.append(title_text)

        if heading_parts:
            paragraphs.append(Paragraph(css_class="articulo", text=" ".join(heading_parts)))

        # Section body paragraphs
        for child in sect:
            tag = child.tag if isinstance(child.tag, str) else ""
            if tag in ("number", "title"):
                continue  # Already handled
            if tag == "p":
                self._parse_paragraph(child, paragraphs)
            elif tag == "table":
                md = _table_to_markdown(child)
                if md:
                    paragraphs.append(Paragraph(css_class="parrafo", text=md))
            elif tag == "sect":
                # Nested subsections (rare but possible)
                self._parse_section(child, paragraphs)

    def _parse_schedule(self, schedule: etree._Element, paragraphs: list[Paragraph]) -> None:
        """Parse a <schedule> element (annex/appendix)."""
        # Schedule heading
        title_el = schedule.find("title")
        if title_el is not None:
            title_text = _inline_text(title_el)
            if title_text:
                paragraphs.append(Paragraph(css_class="titulo_tit", text=title_text))

        for child in schedule:
            tag = child.tag if isinstance(child.tag, str) else ""
            if tag == "title":
                continue
            if tag == "p":
                self._parse_paragraph(child, paragraphs)
            elif tag == "table":
                md = _table_to_markdown(child)
                if md:
                    paragraphs.append(Paragraph(css_class="parrafo", text=md))
            elif tag == "part":
                self._parse_part(child, paragraphs)
            elif tag == "sect":
                self._parse_section(child, paragraphs)

    def _parse_backmatter(self, backmatter: etree._Element, paragraphs: list[Paragraph]) -> None:
        """Parse <backmatter> which contains schedules, tables, and notes."""
        for child in backmatter:
            tag = child.tag if isinstance(child.tag, str) else ""
            if tag == "schedule":
                self._parse_schedule(child, paragraphs)
            elif tag == "p":
                text = _inline_text(child)
                if text:
                    paragraphs.append(Paragraph(css_class="firma_rey", text=text))
            elif tag == "table":
                md = _table_to_markdown(child)
                if md:
                    paragraphs.append(Paragraph(css_class="parrafo", text=md))

    def _parse_paragraph(self, p: etree._Element, paragraphs: list[Paragraph]) -> None:
        """Parse a <p> element into a Paragraph."""
        text = _inline_text(p)
        if not text:
            return

        # Detect centered text (part/chapter titles in ToC or body)
        cls = p.get("class", "")
        just = p.get("just", "")

        if "center" in cls or just == "center":
            # Check if it's a font-smallcaps heading (already captured
            # by structural parsing). Skip standalone centered text that
            # looks like a redundant heading from ToC.
            font = p.find("font")
            if font is not None and font.get("smallcaps") == "yes":
                # This is a structural heading — handled by part/chapter
                return

        paragraphs.append(Paragraph(css_class="parrafo", text=text))

    # ── HTML parser (print view) ────────────────────────────────────

    def _parse_html(self, data: bytes) -> list[Any]:
        """Parse ISB HTML print view for acts without XML (pre-1995).

        Strategy: collect all <p> elements from the act-content div,
        classify each as heading/section/body based on style + context,
        and emit paragraphs matching the XML parser's output structure.
        """
        from lxml import html as lxml_html

        doc = lxml_html.fromstring(data)
        act_div = doc.find('.//div[@id="act"]')
        if act_div is None:
            return []

        pub_date = date(1970, 1, 1)

        # Extract date from enactment line: "[26th July, 1960.]"
        all_text_content = act_div.text_content()
        date_match = re.search(r"\[(\d{1,2})\w*\s+(\w+),?\s+(\d{4})\.\]", all_text_content)
        if date_match:
            day, month_str, year = date_match.groups()
            pub_date = _parse_date_from_parts(int(day), month_str, int(year))

        # Build sec_number → title map AND a set of title texts to suppress.
        section_num_to_title: dict[str, str] = {}  # "1" → "Short title..."
        section_title_texts: set[str] = set()  # lowercase titles to suppress
        for a_tag in act_div.findall(".//a[@name]"):
            name = a_tag.get("name", "")
            if not name.startswith("sec"):
                continue
            sec_num = name[3:]  # "sec1" → "1"
            parent = a_tag.getparent()
            if parent is None:
                continue
            title = ""
            # <small> in same td (older acts)
            small = parent.find(".//small")
            if small is not None:
                title = _html_text(small).strip()
            else:
                # <b> in sibling td of same row (newer acts)
                parent_tr = parent.getparent()
                if parent_tr is not None:
                    for td in parent_tr.findall("td"):
                        b = td.find(".//b")
                        if b is not None:
                            bt = _html_text(b).strip()
                            if bt and not re.match(r"^\d+[A-Z]?\.$", bt):
                                title = bt
                                break
            if title:
                section_num_to_title[sec_num] = title
                section_title_texts.add(title.lower())

        # Walk all <p> in document order. Detect body start after
        # the second bold ACT title, then classify each <p>.
        paragraphs: list[Paragraph] = []
        title_count = 0
        in_body = False
        _pending_heading: str | None = None
        _pending_css: str | None = None
        for p in act_div.iter("p"):
            style = p.get("style", "")
            text = _html_inline_text(p)
            if not text:
                continue

            # Detect body start: second bold ACT title
            if not in_body:
                b_el = p.find(".//b")
                if b_el is not None:
                    b_text = _html_text(b_el).strip()
                    if b_text and "ACT" in b_text.upper():
                        title_count += 1
                        if title_count >= 2:
                            in_body = True
                continue

            # Skip redundant section title that appears as bold-only <p>
            # (these are the sidebar titles duplicated in the body)
            plain = re.sub(r"\*+", "", text).strip()
            if plain.lower() in section_title_texts:
                _last_was_section_heading = False
                continue

            # Centered text → structural headings
            if "text-align:center" in style:
                part_match = re.match(r"^(PART\s+\S+)$", text.strip())
                if part_match:
                    _flush_heading(paragraphs, _pending_heading, _pending_css)
                    _pending_heading = text.strip()
                    _pending_css = "titulo_tit"
                    continue
                chapter_match = re.match(r"^(Chapter\s+\d+)$", text.strip())
                if chapter_match:
                    _flush_heading(paragraphs, _pending_heading, _pending_css)
                    _pending_heading = text.strip()
                    _pending_css = "capitulo_tit"
                    continue
                if _pending_heading:
                    paragraphs.append(
                        Paragraph(
                            css_class=_pending_css or "titulo_tit",
                            text=f"{_pending_heading} {text.strip()}",
                        )
                    )
                    _pending_heading = None
                    _pending_css = None
                    continue
                # Skip decorative centered text
                stripped = text.strip()
                if stripped in ("CONTENTS", "ARRANGEMENT OF SECTIONS", "Section", "Sections"):
                    continue
                # Skip smallcaps centered titles in TOC area
                continue

            # Flush pending heading before body text
            if _pending_heading:
                paragraphs.append(
                    Paragraph(css_class=_pending_css or "titulo_tit", text=_pending_heading)
                )
                _pending_heading = None
                _pending_css = None

            # Detect section start: "**N.**—text" or "**N.** (1) text"
            sec_match = re.match(r"\*\*(\d+[A-Z]?)\.\*\*", text)
            if sec_match:
                sec_num = sec_match.group(1)
                sec_title = section_num_to_title.get(sec_num, "")
                if sec_title:
                    heading = f"{sec_num}. **{sec_title}**"
                    paragraphs.append(Paragraph(css_class="articulo", text=heading))
                else:
                    paragraphs.append(Paragraph(css_class="articulo", text=f"{sec_num}."))

            # Fix trailing space before punctuation
            text = re.sub(r"\s+([;:.,])", r"\1", text)
            paragraphs.append(Paragraph(css_class="parrafo", text=text))

        if _pending_heading:
            paragraphs.append(
                Paragraph(css_class=_pending_css or "titulo_tit", text=_pending_heading)
            )

        if not paragraphs:
            return []

        block = Block(
            id="full-text",
            block_type="document",
            title="",
            versions=(
                Version(
                    norm_id="",
                    publication_date=pub_date,
                    effective_date=pub_date,
                    paragraphs=tuple(paragraphs),
                ),
            ),
        )
        return [block]


# ── Revised Acts parser ──────────────────────────────────────────────


def parse_revised_html(data: bytes) -> tuple[list[Paragraph], date | None]:
    """Parse Revised Acts HTML into paragraphs + updated_to date.

    The Revised Acts HTML has a clean structure:
    <div class="body"> → <section class="part"> → <section class="sect">
    Each sect has <div class="number">, <div class="title">, <p> body.
    Annotations (<div class="annotations">) are skipped.

    Returns (paragraphs, updated_to_date) or ([], None) on failure.
    """
    from lxml import html as lxml_html

    doc = lxml_html.fromstring(data)

    # Extract "Updated to" date
    updated_to = None
    for p in doc.iter("p"):
        try:
            text = p.text_content().strip()
        except (ValueError, AttributeError):
            continue
        m = re.match(r"Updated to (\d{1,2}) (\w+) (\d{4})", text)
        if m:
            updated_to = _parse_date_from_parts(int(m.group(1)), m.group(2), int(m.group(3)))
            break

    # Find body div
    body = doc.find('.//div[@class="body"]')
    if body is None:
        return [], None

    paragraphs: list[Paragraph] = []

    for section in body.iter():
        if not isinstance(section.tag, str):
            continue
        cls = section.get("class", "")

        # Part heading
        if section.tag == "section" and cls == "part":
            title_div = section.find("div[@class='title']")
            if title_div is not None:
                text = _html_text(title_div)
                if text:
                    paragraphs.append(Paragraph(css_class="titulo_tit", text=text))

        # Chapter heading
        elif section.tag == "section" and cls == "chapter":
            try:
                text = section.text_content().strip()[:80]
            except (ValueError, AttributeError):
                text = ""
            # Only take the first line (chapter title)
            first_line = text.split("\n")[0].strip() if text else ""
            if first_line:
                paragraphs.append(Paragraph(css_class="capitulo_tit", text=first_line))

        # Section
        elif section.tag == "section" and cls == "sect":
            num_div = section.find("div[@class='number']")
            title_div = section.find("div[@class='title']")

            sec_num = _html_text(num_div) if num_div is not None else ""
            sec_title = ""
            if title_div is not None:
                # Title is in <b> inside <p> inside the title div
                b = title_div.find(".//b")
                if b is not None:
                    sec_title = _html_text(b)
                else:
                    sec_title = _html_text(title_div)

            if sec_num and sec_title:
                paragraphs.append(
                    Paragraph(css_class="articulo", text=f"{sec_num}. **{sec_title}**")
                )
            elif sec_num:
                paragraphs.append(Paragraph(css_class="articulo", text=f"{sec_num}."))

            # Body paragraphs (skip annotations)
            for child in section:
                if not isinstance(child.tag, str):
                    continue
                if child.get("class", "") == "annotations":
                    continue
                if child.tag == "p":
                    text = _revised_inline_text(child)
                    if text:
                        paragraphs.append(Paragraph(css_class="parrafo", text=text))

    return paragraphs, updated_to


def _revised_inline_text(elem) -> str:
    """Extract text from a Revised Acts <p> with bold/italic/link preservation."""
    parts: list[str] = []

    if elem.text:
        parts.append(elem.text)

    for child in elem:
        tag = child.tag if isinstance(child.tag, str) else ""

        if tag in ("b", "strong"):
            inner = _html_text(child)
            if inner:
                parts.append(f"**{inner}**")
        elif tag in ("i", "em"):
            inner = _html_text(child)
            if inner:
                parts.append(f"*{inner}*")
        elif tag == "a":
            inner = _html_text(child)
            if inner:
                parts.append(inner)
        elif tag == "sup":
            inner = _html_text(child)
            if inner:
                parts.append(f"^{inner}")
        elif tag in ("br", "img", "hr"):
            pass
        elif tag == "span":
            # F-annotations inline markers — skip
            cls = child.get("class", "")
            if "annotation" in cls.lower() or "fn" in cls.lower():
                pass
            else:
                parts.append(_html_text(child))
        else:
            parts.append(_html_text(child))

        if child.tail:
            parts.append(child.tail)

    text = "".join(parts)
    text = strip_control(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _flush_heading(
    paragraphs: list[Paragraph],
    heading: str | None,
    css: str | None,
) -> None:
    """Emit a buffered heading if present."""
    if heading:
        paragraphs.append(Paragraph(css_class=css or "titulo_tit", text=heading))


def _html_text(elem) -> str:
    """Extract plain text from an lxml.html element."""
    try:
        text = elem.text_content()
    except (ValueError, AttributeError):
        return ""
    text = strip_control(text)
    return re.sub(r"\s+", " ", text).strip()


def _html_inline_text(elem) -> str:
    """Extract text from an HTML <p> with bold/italic/link preservation."""
    parts: list[str] = []

    if elem.text:
        parts.append(elem.text)

    for child in elem:
        tag = child.tag if isinstance(child.tag, str) else ""

        if tag in ("b", "strong"):
            inner = _html_text(child)
            if inner:
                parts.append(f"**{inner}**")
        elif tag in ("i", "em"):
            inner = _html_text(child)
            if inner:
                parts.append(f"*{inner}*")
        elif tag == "a":
            inner = _html_text(child)
            if inner:
                parts.append(inner)
        elif tag == "small":
            inner = _html_text(child)
            if inner:
                parts.append(inner)
        elif tag == "sup":
            inner = _html_text(child)
            if inner:
                parts.append(f"^{inner}")
        elif tag == "br":
            pass  # skip line breaks
        elif tag == "img":
            pass  # skip images
        elif tag == "hr":
            pass  # skip horizontal rules
        else:
            parts.append(_html_text(child))

        if child.tail:
            parts.append(child.tail)

    text = "".join(parts)
    text = strip_control(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_date_from_parts(day: int, month_str: str, year: int) -> date:
    """Parse date from day + month name + year."""
    months = {
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
    month = months.get(month_str.lower(), 1)
    try:
        return date(year, month, day)
    except ValueError:
        return date(year, month, 1)


# ── Metadata parser ─────────────────────────────────────────────────


class ISBMetadataParser(MetadataParser):
    """Parse Oireachtas API JSON into NormMetadata."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        """Parse metadata JSON from Oireachtas API.

        The data is the raw response from /v1/legislation.
        norm_id is 'IE-{year}-act-{number}'.
        """
        response = json.loads(data)

        results = response.get("results", [])
        if not results:
            # Fallback: construct minimal metadata from norm_id
            return self._fallback_metadata(norm_id)

        bill = results[0].get("bill", {})
        act = bill.get("act", {})

        # Title: prefer shortTitleEn, fall back to act title
        title = act.get("shortTitleEn", "")
        if not title:
            title = norm_id

        # Irish language title
        title_ga = act.get("shortTitleGa") or ""

        # Long title (summary)
        long_title = act.get("longTitleEn") or ""
        # Strip HTML from long title
        long_title = re.sub(r"<[^>]+>", "", long_title).strip()

        # Date signed
        date_signed = act.get("dateSigned", "")
        pub_date = _parse_date_str(date_signed)
        if not pub_date:
            pub_date = date(1970, 1, 1)

        # Source URL
        source = act.get("statutebookURI", "")

        # PDF URL from versions
        pdf_url = ""
        versions = act.get("versions") or bill.get("versions", [])
        for v in versions:
            ver = v.get("version", v)
            formats = ver.get("formats", {})
            if "pdf" in formats:
                pdf_url = formats["pdf"].get("uri", "")
                break
            # Direct URI in version
            uri = ver.get("uri", "")
            if uri and uri.endswith("/enacted"):
                pdf_url = uri

        # Extra metadata
        extra: list[tuple[str, str]] = []
        if title_ga:
            extra.append(("title_ga", title_ga))

        long_title_ga = act.get("longTitleGa", "")
        if long_title_ga:
            long_title_ga = re.sub(r"<[^>]+>", "", long_title_ga).strip()
            extra.append(("long_title_ga", long_title_ga[:500]))

        oireachtas_uri = act.get("uri", "")
        if oireachtas_uri:
            extra.append(("oireachtas_uri", oireachtas_uri))

        # Related docs
        related = bill.get("relatedDocs", [])
        if related:
            doc_types = [
                d.get("relatedDoc", d).get("docType", "")
                for d in related
                if d.get("relatedDoc", d).get("docType")
            ]
            if doc_types:
                extra.append(("related_docs", ", ".join(doc_types)))

        return NormMetadata(
            title=title,
            short_title=title,
            identifier=norm_id,
            country="ie",
            rank=Rank("act"),
            publication_date=pub_date,
            status=NormStatus.IN_FORCE,
            # TODO(phase-3): detect REPEALED/PARTIALLY_REPEALED from Revised Acts
            # F-annotations (e.g. "F1 Repealed (31.07.2024) by ...")
            department="",
            source=source,
            pdf_url=pdf_url or None,
            summary=long_title[:500] if long_title else "",
            extra=tuple(extra),
        )

    def _fallback_metadata(self, norm_id: str) -> NormMetadata:
        """Create minimal metadata when API returns no results."""
        parts = norm_id.split("-")
        year = int(parts[1]) if len(parts) > 1 else 1970
        return NormMetadata(
            title=norm_id,
            short_title=norm_id,
            identifier=norm_id,
            country="ie",
            rank=Rank("act"),
            publication_date=date(year, 1, 1),
            status=NormStatus.IN_FORCE,
            # TODO(phase-3): detect REPEALED/PARTIALLY_REPEALED from Revised Acts
            # F-annotations (e.g. "F1 Repealed (31.07.2024) by ...")
            department="",
            source="",
        )


def _parse_date_str(value: str) -> date | None:
    """Parse ISO date string 'YYYY-MM-DD'."""
    if not value or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
