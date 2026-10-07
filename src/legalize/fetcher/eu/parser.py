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
import base64
import logging
import re
from copy import deepcopy
from urllib.parse import urljoin
from dataclasses import replace
from datetime import date
from typing import Any
from xml.etree import ElementTree as ET

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.fetcher._tables import render_table
from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    Rank,
    TextState,
    Version,
)
from legalize.fetcher._text import strip_control

logger = logging.getLogger(__name__)

# XHTML namespace
_XHTML_NS = "http://www.w3.org/1999/xhtml"

# Whitespace normalization
_MULTI_SPACE_RE = re.compile(r"[ \t]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")

# ─── Rank mapping ───
_RTYPE_BASE = "http://publications.europa.eu/resource/authority/resource-type/"
# Every resource type the fetcher may discover. A type missing here used to
# fall back to "regulation", which would have published 4,326 directives and
# 23,390 decisions as regulations the moment the scope widened.
_RANK_MAP: dict[str, str] = {
    "REG": "regulation",
    "REG_IMPL": "implementing_regulation",
    "REG_DEL": "delegated_regulation",
    "REG_FINANC": "financial_regulation",
    "DIR": "directive",
    "DIR_IMPL": "implementing_directive",
    "DIR_DEL": "delegated_directive",
    "DEC": "decision",
    "DEC_IMPL": "implementing_decision",
    "DEC_DEL": "delegated_decision",
    "DEC_ENTSCHEID": "decision_sui_generis",
    "RECO": "recommendation",
    "TREATY": "treaty",
    "AGREE_INTERNATION": "international_agreement",
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


def strip_embedded_image_data(data: bytes) -> bytes:
    """Keep image positions without expanding base64 drawings in version trees.

    Raw cached sources and their hashes retain the complete originals. The
    renderer emits a visible omission/link, so retaining megabytes of image
    data in every intermediate XML tree only wastes memory.
    """
    return re.sub(rb"(\bsrc\s*=\s*['\"])data:image/[^'\"]*(['\"])", rb"\1\2", data)


def _tag(el: ET.Element) -> str:
    """Strip namespace from an element tag."""
    return el.tag.split("}")[-1] if "}" in el.tag else el.tag


# Modification markers inserted by EUR-Lex consolidated text system
_MOD_MARKER_RE = re.compile(r"\[?\*{0,2}[►▼][A-Z]\d*\*{0,2}\]?")
_MOD_END_RE = re.compile(r"\*{0,2}[◄▲]\*{0,2}")


def _is_separator(text: str) -> bool:
    """Pre-2005 CELEX text uses a run of plus signs as a typographic separator.

    The EEC Treaty opens with one. It carries no legal content and would
    otherwise render as a literal ``++++`` paragraph.
    """
    return bool(text) and not text.strip("+ ")


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


def _starts_quotation(text: str) -> bool:
    text = text.removeprefix("- ")
    if not text.startswith(("‘", "“")):
        return False
    return bool(re.match(r"^[‘“](?:\(?\d+[.)]|\([a-z]+\)|Article\s)", text)) or not re.search(
        r"[’”]\s+\w", text
    )


_EEA_SUFFIX_RE = re.compile(r"\s*\(?Text with EEA relevance\)?\s*", re.IGNORECASE)

# EUR-Lex titles lead with the act's own name and then break into the signature
# ("… of 27 April 2016 …") or the subject ("… on the protection of …").
_CUT_WORDS = (" of ", " on ")


def _short_title(title: str) -> str:
    """The act's own name, for commit subjects and listings.

    This used to keep everything *after* the first " on ", which is the subject
    matter — so the act's identity, which sits before it, was thrown away. Real
    commits in legalize-eu read "[reform] product intervention and positions"
    and "[reform] type-approval of motor vehicles", naming no act at all.

    Cutting *before* that word instead yields "Regulation (EU) 2016/679". A cut
    is only taken when what it leaves still carries a number, so old acts whose
    title has none — "Council Decision of 22 July 1993 concerning …" — keep
    their full title: a long subject beats an anonymous one.
    """
    cleaned = _EEA_SUFFIX_RE.sub(" ", title).strip().rstrip(" .,;")
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned)
    for word in _CUT_WORDS:
        head = cleaned.split(word, 1)[0].strip().rstrip(" .,;")
        if head != cleaned and any(ch.isdigit() for ch in head):
            return head
    return cleaned


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

        if (
            ctag in ("b", "strong") or "boldface" in cls or "oj-bold" in cls
        ) and child_text.strip():
            parts.append(f"**{child_text.strip()}**")
        elif (ctag in ("i", "em") or "italics" in cls or "oj-italic" in cls) and child_text.strip():
            parts.append(f"*{child_text.strip()}*")
        elif ctag == "span" and ("superscript" in cls or "oj-super" in cls) and child_text.strip():
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
                has_note_marker = any(
                    _tag(node) == "sup"
                    or "superscript" in node.get("class", "")
                    or "oj-super" in node.get("class", "")
                    for node in child.iter()
                )
                if (
                    href.startswith("#")
                    and has_note_marker
                    and child.get("data-note-available") == "1"
                ):
                    parts.append(f"[^{href[1:]}]")
                elif href:
                    if has_note_marker and href.startswith("#") and child.get("data-source-url"):
                        href = child.get("data-source-url")
                    if href.startswith("/"):
                        href = urljoin("https://eur-lex.europa.eu", href)
                    elif re.fullmatch(r"#art_\d+\w*", href):
                        href = "#article-" + href[5:]
                    parts.append(f"[{child_text.strip()}]({href})")
                else:
                    parts.append(child_text)
        elif ctag == "br":
            parts.append("\n")
        elif ctag == "img":
            parts.append(
                f"[Image omitted; see official source]({child.get('data-source-url', '')})"
            )
        elif ctag == "sup" and child_text.strip():
            parts.append(f"<sup>{child_text.strip()}</sup>")
        else:
            parts.append(child_text)

        if child.tail:
            parts.append(child.tail)

    result = "".join(parts)
    # Sanitise at the source boundary: C0/C1 control characters reach the output
    # from real gazettes and are invisible until something downstream chokes on
    # them. Until now the EU parser imported strip_control but never called it —
    # the only caller was a _clean() helper nothing referenced.
    result = strip_control(result)
    # Strip modification markers and normalize list marker whitespace
    result = _strip_mod_markers(result)
    result = _normalize_list_marker(result)
    style = el.get("style", "")
    if (
        result
        and re.search(r"font-weight\s*:\s*(?:bold|[7-9]00)", style)
        and not (result.startswith("**") and result.endswith("**"))
    ):
        result = f"**{result}**"
    if result and re.search(r"font-style\s*:\s*italic", style):
        result = f"*{result}*"
    return result


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
        first = f"- {marker} {lines[0]}"
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
    # Nested list tables have their own columns; they do not widen this table.
    cols = [child for child in table_el if _tag(child) == "col"]
    for group in table_el:
        if _tag(group) == "colgroup":
            cols.extend(child for child in group if _tag(child) == "col")
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
    rows = [
        row
        for child in table_el
        for row in (child if _tag(child) in ("tbody", "thead", "tfoot") else (child,))
        if _tag(row) == "tr"
    ]
    for tr in rows:
        cells = [c for c in tr if _tag(c) in ("td", "th")]
        if len(cells) < 2:
            continue
        marker = _extract_text(cells[0]).strip()
        # Walk the content once, in order, including paragraphs after sub-lists.
        content: list[Paragraph] = []
        for p in _walk_body(cells[1]):
            # Article labels inside an amending list quote another act.
            content.append(
                replace(p, css_class="abs")
                if p.css_class
                in (
                    "h2",
                    "h3",
                    "h4",
                    "h5",
                    "h6",
                    "_article_subtitle",
                    "_article_subheading",
                    "_division",
                    "_division_title",
                )
                else p
            )
        if marker and content:
            content[0] = replace(content[0], css_class="list", text=f"- {marker} {content[0].text}")
            if marker.startswith(("‘", "“")):
                content = [
                    replace(p, css_class="quote", text=p.text.replace("\n", "\n> "))
                    for p in content
                ]
        paragraphs.extend(content)

    return paragraphs


def _parse_table(table_el: ET.Element) -> str:
    """Convert an HTML data table to a Markdown pipe table."""
    from lxml import etree

    tail, table_el.tail = table_el.tail, None
    try:
        serialized = ET.tostring(table_el)
    finally:
        table_el.tail = tail  # The parent walker emits text after the table.
    table = etree.fromstring(serialized)
    for node in table.iter():
        node.tag = _tag(node)
    for node in list(table.iter()):
        if _is_footnote_definition(node):
            row = next((p for p in node.iterancestors() if _tag(p) == "tr"), None)
            node.getparent().remove(node)
            if row is not None and not "".join(row.itertext()).strip():
                row.getparent().remove(row)
    from legalize.fetcher._tables import _rows_of

    rows = list(_rows_of(table))
    if rows and table.find("thead") is None:
        cells = list(rows[0])
        if len(cells) > 1 and all(
            re.search(r"font-weight\s*:\s*(?:bold|[7-9]00)", c.get("style", ""))
            or any("oj-tbl-hdr" in node.get("class", "") for node in c.iter())
            for c in cells
        ):
            head = etree.Element("thead")
            table.insert(0, head)
            head.append(rows[0])
    return render_table(table, _extract_text)


def _is_footnote_definition(el: ET.Element) -> bool:
    tag, cls = _tag(el), el.get("class", "")
    return (tag == "p" and ("oj-note" in cls or "footnote" in cls)) or (
        tag in ("div", "p")
        and "tbl-norm" in cls
        and any(_tag(c) == "a" and c.get("id") and not c.get("href") for c in el)
    )


def _footnote(el: ET.Element) -> list[Paragraph]:
    """Use the source anchor as a unique Markdown footnote key."""
    text = _extract_text(el).strip()
    anchor = next((a for a in el.iter() if _tag(a) == "a" and a.get("id")), None)
    if anchor is not None:
        text = re.sub(r"^\(?\[\^[^]]+\]\)?\s*", "", text)
        text = f"[^{anchor.get('id')}]: {text}"
    return [Paragraph("abs", text)] if text else []


def _walk_body(el: ET.Element, depth: int = 0) -> list[Paragraph]:
    """Recursively walk the XHTML body and convert to paragraphs.

    Processes the structural hierarchy: eli-container > eli-subdivision >
    articles/chapters/titles, extracting headings, body text, lists, and tables.
    """
    paragraphs: list[Paragraph] = []
    tag = _tag(el)
    cls = el.get("class", "")
    if _is_footnote_definition(el):
        return _footnote(el)

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
            paragraphs.append(Paragraph("_division", text))
        return paragraphs

    if "title-division-2" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("_division_title", text))
        return paragraphs

    # Check stitle BEFORE title (stitle-article-norm contains title-article-norm)
    if "stitle-article-norm" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("_article_subtitle", text))
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

    if any(f"title-gr-seq-level-{n}" in cls for n in (3, 4, 5)):
        text = _extract_text(el).strip()
        if text:
            level = 2 + int(re.search(r"title-gr-seq-level-(\d)", cls).group(1))
            paragraphs.append(
                Paragraph(f"h{level}", text)
                if level <= 6
                else Paragraph("abs", f"**{text.replace('**', '').strip()}**")
            )
        return paragraphs

    if "oj-ti-grseq" in cls:
        text = _extract_text(el).strip()
        if text:
            number = re.match(r"^(\d+(?:\.\d+)*)\.?(?:\s|$)", text)
            level = min(6, 2 + len(number.group(1).split("."))) if number else 3
            paragraphs.append(Paragraph(f"h{level}", text))
        return paragraphs

    if "title-table" in cls or "oj-ti-tbl" in cls:
        text = _extract_text(el).strip()
        return [Paragraph("h5", text)] if text else []

    # Main title block
    if "eli-main-title" in cls:
        # The document's own title. render_norm_at_date already writes
        # "# {title}" from the frontmatter, so emitting it here put the title in
        # every file twice — visible on legalize.dev.
        return paragraphs

    # Lists
    if "grid-container" in cls and "grid-list" in cls:
        text = _parse_list(el)
        if text:
            quoted = _starts_quotation(text)
            paragraphs.append(
                Paragraph(
                    "quote" if quoted else "list", text.replace("\n", "\n> ") if quoted else text
                )
            )
        return paragraphs

    # Tables — detect list-tables vs data tables
    if tag == "table":
        if _is_list_table(el):
            paragraphs.extend(_parse_list_table(el))
        else:
            text = _parse_table(el)
            if text:
                paragraphs.append(Paragraph("table", text))
            for note in el.iter():
                if _is_footnote_definition(note):
                    paragraphs.extend(_footnote(note))
        return paragraphs

    # ─── OJ (Official Journal) format classes ───
    # Original texts use oj-* classes instead of the consolidated-text classes.
    if "oj-ti-section-1" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("_division", text))
        return paragraphs

    if "oj-ti-section-2" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("_division_title", text))
        return paragraphs

    # Check oj-sti-art BEFORE oj-ti-art (same substring issue)
    if "oj-sti-art" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("_article_subtitle", text))
        return paragraphs

    if "oj-ti-art" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("h4", text))
        return paragraphs

    if "oj-doc-ti" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("h2", text))
        return paragraphs

    if "oj-normal" in cls:
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("abs", text))
        return paragraphs

    if "oj-signatory" in cls and tag == "p":
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("signature", text))
        return paragraphs

    # Skip OJ notes (footnotes in OJ format)
    if "oj-note" in cls and tag == "p":
        return _footnote(el)

    # ─── Consolidated text format classes ───
    # Indented divs with margin-left (old consolidated format for list items).
    # Pattern: <div style="margin-left: 30pt; text-indent: -30pt"><p class="norm">(a) ...</p></div>
    if tag == "div" and not cls:
        style = el.get("style", "")
        if "margin-left" in style and "text-indent" in style:
            text = _extract_text(el).strip()
            if text:
                quoted = _starts_quotation(text)
                paragraphs.append(
                    Paragraph(
                        "quote" if quoted else "list",
                        text.replace("\n", "\n> ") if quoted else f"- {text}",
                    )
                )
            return paragraphs

    # <p class="list"> — old consolidated format for list items
    if tag == "p" and cls == "list":
        text = _extract_text(el).strip()
        if text:
            quoted = _starts_quotation(text)
            paragraphs.append(
                Paragraph(
                    "quote" if quoted else "list",
                    text.replace("\n", "\n> ") if quoted else f"- {text}",
                )
            )
        return paragraphs

    # Consolidated provisions can be text-bearing divs, including inline spans.
    # Containers with block children must still be walked so lists stay separate.
    is_text_div = (
        tag == "div"
        and "norm" in cls.split()
        and not any(_tag(child) in ("p", "div", "table") for child in el)
    )
    # Normal text paragraphs (norm, normal, tbl-norm, item-none)
    if is_text_div or (
        tag == "p" and ("norm" in cls or "tbl-norm" in cls or "item-none" in cls or cls == "normal")
    ):
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph("abs", text))
        return paragraphs

    # Footnotes
    if "footnote" in cls and tag == "p":
        return _footnote(el)

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

    # Unknown body classes must not silently discard legal text. Journal
    # running headers are metadata, while plain legacy Article labels are heads.
    if tag == "p":
        if cls.startswith("oj-hd-"):
            return paragraphs
        text = _extract_text(el).strip()
        if text and not _is_separator(text):
            if re.match(r"^Article\s+\d+\w*\s*$", text):
                paragraphs.append(Paragraph("h4", text))
            else:
                paragraphs.append(Paragraph("abs", text))
        return paragraphs

    # <h1> tags in old HTML (CELEX number as title)
    if tag == "h1":
        return paragraphs  # Skip — CELEX is not the title

    # <strong> as title in old HTML — same duplicate as the two above
    if tag == "strong":
        return paragraphs

    # Container divs — recurse.
    # ``txt_te`` is the body wrapper of EUR-Lex's pre-2005 HTML4 documents; every
    # paragraph of those acts hangs off it, so leaving it out stopped the walk at
    # the door and emitted the act as one blob (1,926 published files, see
    # research/RESEARCH-EU.md §3.3). It is listed rather than recursing into any
    # unknown element because <head> is one too.
    if tag in ("div", "body", "html", "txt_te", "td", "th"):
        inline = ET.Element("p", {"class": "norm"})
        inline.text = el.text

        def flush_inline() -> None:
            nonlocal inline
            text = _extract_text(inline).strip()
            if text:
                paragraphs.append(Paragraph("abs", text))
            inline = ET.Element("p", {"class": "norm"})

        for child in el:
            ctag = _tag(child)
            child_cls = child.get("class", "")
            if ctag in ("span", "a", "b", "strong", "i", "em", "sup", "sub", "br", "img"):
                if "arrow" not in child_cls and "no-parag" not in child_cls:
                    inline.append(deepcopy(child))
                continue
            flush_inline()

            # Skip arrow markers
            if "arrow" in child_cls:
                continue
            if "hd-modifiers" in child_cls:
                continue
            if ctag == "table" and _is_amendment_table(child):
                continue

            paragraphs.extend(_walk_body(child, depth + 1))
            inline.text = child.tail
        flush_inline()

        if tag == "txt_te":
            signed = False
            for i, paragraph in enumerate(paragraphs):
                if re.match(r"^Done at .*\b\d{4}\.\s*$", paragraph.text):
                    signed = True
                elif paragraph.css_class.startswith("h") or paragraph.text.startswith("ANNEX"):
                    signed = False
                elif signed:
                    paragraphs[i] = replace(paragraph, css_class="signature")

        # Consolidated numbering is a sibling span, not part of the body leaf.
        if tag == "div" and "norm" in cls.split() and paragraphs:
            marker = next(
                (
                    _extract_text(child)
                    for child in el
                    if "no-parag" in child.get("class", "").split()
                ),
                "",
            )
            if marker:
                if paragraphs[0].css_class in ("table", "list"):
                    paragraphs.insert(0, Paragraph("abs", marker))
                else:
                    paragraphs[0] = replace(paragraphs[0], text=f"{marker} {paragraphs[0].text}")

        # A source subdivision inside an article must not close that article
        # in Markdown (e.g. Article 2's "A. NORMAL VALUE" in 32016R1036).
        if re.fullmatch(r"art_\d+\w*", el.get("id", "")):
            paragraphs = [
                replace(p, css_class="_article_subheading")
                if p.css_class in ("h2", "h3", "_division", "_division_title")
                else p
                for p in paragraphs
            ]

    return paragraphs


def _is_amendment_table(table_el: ET.Element) -> bool:
    """Check if a table is an amendment list table in the header."""
    for p in table_el.iter():
        if _tag(p) != "p":
            continue
        cls = p.get("class", "")
        if "arrow" in cls or "hd-toc" in cls or "title-fam-member" in cls:
            return True
    return False


def _parse_xhtml_to_paragraphs(data: bytes, norm_id: str = "") -> list[Paragraph]:
    """Parse XHTML or HTML bytes into a flat list of Paragraphs.

    Tries strict XML parsing first (for XHTML). Falls back to lxml.html
    for old HTML4 documents that aren't valid XML.
    """
    data = strip_embedded_image_data(data)
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        # Old HTML4 — parse with lxml.html (permissive) and convert to ET
        from lxml import html as lxml_html

        # Remove controls before lxml can turn NUL into a replacement character.
        clean_data = strip_control(data.decode("utf-8")).encode("utf-8")
        doc = lxml_html.fromstring(clean_data, parser=lxml_html.HTMLParser(encoding="utf-8"))
        # lxml.html uses no namespace; _walk_body checks _tag() which strips ns
        # Convert lxml tree to ET tree for uniform processing
        raw_xml = lxml_html.tostring(doc, encoding="unicode", method="xml")
        root = ET.fromstring(raw_xml)

    anchors = {node.get("id") for node in root.iter() if node.get("id")}
    for node in root.iter():
        if _tag(node) == "img":
            # ponytail: drawings stay at the official source until the corpus
            # contract supports publishing image assets alongside law versions.
            node.set(
                "data-source-url",
                f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{norm_id}",
            )
        if _tag(node) == "a" and node.get("href", "").startswith("#"):
            if node.get("href")[1:] in anchors:
                node.set("data-note-available", "1")
            elif norm_id:
                node.set(
                    "data-source-url",
                    f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{norm_id}",
                )

    # Pre-2005 HTML4: the act's body is a <TXT_TE> element, and it sits *inside*
    # a class-less <p>. Walking the document body therefore hits that <p> first,
    # treats it as a leaf, and flattens the whole act into a single paragraph.
    # Name TXT_TE as a content container, the same way eli-container is named.
    container = root.find(f".//{_xh('txt_te')}")
    if container is None:
        container = root.find(".//txt_te")
    if container is not None:
        return _walk_body(container)

    # Fallback: walk the body (with or without namespace)
    body = root.find(f".//{_xh('body')}")
    if body is None:
        body = root.find(".//body")
    if body is not None:
        return _walk_body(body)

    return _walk_body(root)


def _normalize_heading_levels(paragraphs: list[Paragraph]) -> list[Paragraph]:
    """Allocate structural levels above articles without flattening sections."""
    levels = ("TITLE", "CHAPTER", "SECTION", "SUBSECTION")

    def division(p: Paragraph) -> str:
        if p.css_class != "_division":
            return ""
        match = re.match(r"^(TITLE|CHAPTER|SECTION|SUBSECTION)\s", p.text.strip("* ").upper())
        return match.group(1) if match else ""

    present = {division(p) for p in paragraphs}
    heading_levels = {name: i + 2 for i, name in enumerate(n for n in levels if n in present)}
    article_level = max(4, len(heading_levels) + 2)
    result = []
    previous_division = False
    for p in paragraphs:
        kind = division(p)
        if p.css_class == "_division_title":
            if previous_division and result:
                result[-1] = replace(result[-1], text=f"{result[-1].text} {p.text}")
                continue
            p = replace(p, css_class="h3")
        elif p.css_class == "_division":
            p = replace(p, css_class=f"h{heading_levels.get(kind, 2)}")
        elif p.css_class == "h4" and re.match(r"^Article\s", p.text.strip("* ")):
            p = replace(p, css_class=f"h{article_level}", text=p.text.strip("* "))
        elif p.css_class in ("_article_subtitle", "_article_subheading"):
            p = (
                replace(p, css_class=f"h{article_level + 1}")
                if article_level < 6
                else replace(p, css_class="abs", text=f"**{p.text.replace('**', '').strip()}**")
            )
        result.append(p)
        previous_division = bool(kind)
    return result


def _normalize_quotations(paragraphs: list[Paragraph]) -> list[Paragraph]:
    """Keep replacement passages quoted across source paragraph boundaries."""
    quoted = False
    result = []
    for p in paragraphs:
        if p.css_class.startswith("h") or p.css_class.startswith("_"):
            quoted = False
        text = p.text.removeprefix("- ")
        opens = p.css_class == "quote" or _starts_quotation(text)
        quoted = quoted or opens
        if quoted:
            # A layout-list continuation is still part of the replacement.
            if p.css_class == "list" and not re.match(r"^- (?:\(|\d+[.)])", p.text):
                p = replace(p, text=text)
            p = replace(
                p,
                css_class="quote",
                text=p.text if "\n> " in p.text else p.text.replace("\n", "\n> "),
            )
            if re.search(r"[’”][.;,]?\s*$", text):
                quoted = False
        result.append(p)
    return result


class EURLexTextParser(TextParser):
    """Parse EUR-Lex XHTML into Block/Version/Paragraph structures."""

    def parse_text(
        self, data: bytes, *, norm_id: str = "", published_on: date | None = None
    ) -> list[Block]:
        """Parse a dated envelope, or an original with explicit source context.

        Standalone source files may carry a journal/consolidation date in
        their header. Missing or invalid dates never become the run date.
        """
        if b"<eurlex-multi-version" in data[:200]:
            versions = []
            for attrs, inner in self._versions(data):
                when = date.fromisoformat(attrs.get("effective-date", ""))
                published = date.fromisoformat(attrs.get("publication-date", when.isoformat()))
                if attrs.get("format") == "pdf":
                    from legalize.fetcher.eu.parser_pdf import parse_pdf

                    encoded = ET.fromstring(inner).text or ""
                    paragraphs = parse_pdf(base64.b64decode(encoded, validate=True))
                else:
                    paragraphs = _parse_xhtml_to_paragraphs(inner, attrs["source-id"])
                paragraphs = _normalize_quotations(_normalize_heading_levels(paragraphs))
                if not paragraphs:
                    raise ValueError(f"Empty source version: {attrs.get('source-id', '')}")
                versions.append(
                    Version(
                        norm_id=attrs["source-id"],
                        publication_date=published,
                        effective_date=when,
                        paragraphs=tuple(paragraphs),
                    )
                )
            if not versions:
                raise ValueError("Empty EUR-Lex version envelope")
            return [Block(id="main", block_type="content", title="", versions=tuple(versions))]

        if published_on is None:
            header = re.search(
                rb'class=[\'"](?:reference|oj-hd-date)[\'"][^>]*>[^<]*?(\d{1,2})\.(\d{1,2})\.(\d{4})',
                data,
            ) or re.search(
                rb'name="DC.source"[^>]*content="[^"<]*?(\d{1,2})/(\d{1,2})/(\d{4})',
                data,
            )
            if header:
                day, month, year = (int(x) for x in header.groups())
                published_on = date(year, month, day)
        if published_on is None:
            raise ValueError("Raw EUR-Lex text requires its source publication date")
        paragraphs = _normalize_quotations(
            _normalize_heading_levels(_parse_xhtml_to_paragraphs(data, norm_id))
        )
        if not paragraphs:
            return []
        version = Version(
            norm_id=norm_id,
            publication_date=published_on,
            effective_date=published_on,
            paragraphs=tuple(paragraphs),
        )
        return [Block(id="main", block_type="content", title="", versions=(version,))]

    @staticmethod
    def _versions(data: bytes):
        """Read wrappers without reparsing/reserializing entire version trees.

        Each body is validated by its own parser. Legacy HTML may not be XML;
        trade agreements can contain hundreds of megabytes of tariff tables.
        """
        opening = re.search(rb"<eurlex-multi-version\b[^>]*>", data[:200])
        if opening is None:
            raise ValueError("Missing EUR-Lex envelope")
        celex = ET.fromstring(opening.group(0)[:-1] + b"/>").get("celex", "")
        if not celex:
            raise ValueError("EUR-Lex envelope has no CELEX identifier")
        if b"xmlns" in opening.group(0):
            # XML-built envelopes can declare the bodies' prefixes on the wrapper.
            for version in ET.fromstring(data).findall("version"):
                attrs = dict(version.attrib)
                attrs.setdefault("source-id", celex)
                yield attrs, b"".join(ET.tostring(child) for child in version)
            return
        for match in re.finditer(rb"<version\b([^>]*)>(.*?)</version>", data, re.DOTALL):
            attrs = ET.fromstring(b"<version" + match.group(1) + b"/>").attrib
            attrs.setdefault("source-id", celex)
            yield attrs, match.group(2)

    def extract_reforms(self, data: bytes) -> list[Any]:
        """Each original, consolidation or recorded amendment has its own ID."""
        from legalize.models import Reform

        if b"<eurlex-multi-version" not in data[:200]:
            return []
        return [
            Reform(
                date=date.fromisoformat(
                    attrs.get("publication-date", attrs.get("effective-date", ""))
                ),
                norm_id=attrs["source-id"],
                affected_blocks=("main",),
                has_source_date=attrs.get("type") != "consolidation",
            )
            for attrs, _ in self._versions(data)
        ]


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
        source_facts = first.get("sourceFacts", {}).get("value", "")
        facts = json.loads(source_facts) if source_facts else {}

        # Title
        title = first.get("title", {}).get("value", norm_id)
        short_title = _short_title(title)

        # CELEX. 1,394 acts in scope carry a path separator in theirs —
        # "11997D/TXT" is the Treaty of Amsterdam, "11951K/CDT/P01" an ECSC
        # protocol — and spec v0.4 §Directory layout requires a publisher to
        # reject a path value containing "/". Rejecting would drop the founding
        # treaties, so the separator becomes "-" in the identifier and the
        # source's own string is kept in `celex`.
        #
        # Measured over the whole 87,227-act scope: the substitution creates no
        # collision, and no CELEX already contains "-", so it is reversible.
        # These acts have never been published, so no URL breaks.
        source_celex = first.get("celex", {}).get("value", norm_id)
        celex = source_celex.replace("/", "-")

        # ELI
        eli = first.get("eli", {}).get("value", "")

        # Publication belongs to the Official Journal. work_date_document is
        # often the adoption date, and must not silently stand in for it.
        dates = [b["publicationDate"]["value"] for b in bindings if b.get("publicationDate")]
        date_str = min(dates) if dates else ""
        try:
            pub_date = date.fromisoformat(date_str)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"{norm_id}: source states no publication date ({date_str!r})"
            ) from exc

        # Entry into force — an act can have several, take the earliest.
        entry_force_dates: list[date] = []
        for annotation in facts.get("date_annotations", []):
            if not annotation.get("typeOfDate", {}).get("value", "").startswith("{EV|"):
                continue
            ef_str = annotation.get("date", {}).get("value", "")
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

        # Status. "The source does not say" is not "repealed": reading it that
        # way is what marked ~1,900 living Austrian laws dead (#123), and here it
        # would have invented 82,326 repeals that never happened. Those acts are
        # out of scope by decision (RESEARCH-EU.md §4.3), so meeting one means
        # discovery changed and the run should stop, not guess.
        #
        # And within "no longer in force", repealing is an act of the legislature
        # while expiring is a deadline the norm set itself. 9,269 acts in scope
        # have a repealing act; the other ~41,000 simply ran out.
        force_val = first.get("force", {}).get("value", "")
        repealed_by = first.get("repealedBy", {}).get("value", "")
        future_original = False
        if force_val in ("1", "true"):
            status = NormStatus.IN_FORCE
        elif force_val in ("0", "false"):
            if repealed_by:
                status = NormStatus.REPEALED
            elif end_validity and end_validity <= date.today():
                status = NormStatus.EXPIRED
            elif (
                entry_force
                and entry_force > date.today()
                and (not end_validity or end_validity >= entry_force)
                and first.get("hasCons", {}).get("value", "") not in ("1", "true")
                and not first.get("lastAmendment", {}).get("value")
                and not json.loads(first.get("amendments", {}).get("value", "[]"))
            ):
                # This unamended original is a point-in-time text on its known
                # future commencement date, not an expired law as of publication.
                future_original = True
                status = NormStatus.IN_FORCE
            else:
                raise ValueError(
                    f"{norm_id}: source states not in force but no repeal or finite end of validity; "
                    f"cannot infer expiration (qualified entry into force: {entry_force})"
                )
        else:
            raise ValueError(
                f"{norm_id}: EUR-Lex states no in-force status; "
                "such acts are out of scope (see RESEARCH-EU.md §4.3)"
            )

        # Resource type → rank
        rtype_uri = first.get("rtype", {}).get("value", "")
        rtype_code = rtype_uri.replace(_RTYPE_BASE, "")
        if rtype_code not in _RANK_MAP:
            raise ValueError(
                f"{norm_id}: unmapped resource type {rtype_code!r} — add it to _RANK_MAP"
            )
        rank = Rank(_RANK_MAP[rtype_code])

        # Authors. GROUP_CONCAT joins the distinct ones with "|", so an act
        # with 30 signatory states is one row rather than 30.
        authors: list[str] = []
        seen_authors: set[str] = set()
        for author_uri in first.get("authors", {}).get("value", "").split("|"):
            if not author_uri:
                continue
            author_code = author_uri.replace(_AUTHOR_BASE, "")
            author_name = _AUTHOR_MAP.get(author_code, author_code)
            if author_name not in seen_authors:
                seen_authors.add(author_name)
                authors.append(author_name)
        department = ", ".join(authors) if authors else "European Union"

        # Source URL
        source = (
            eli
            if eli
            else f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{source_celex}"
        )

        # Text state. EUR-Lex consolidates 9 % of the corpus and publishes the
        # rest as adopted, so the country default is as_enacted (countries.py)
        # and the consolidated ones are overridden back here — the same shape
        # Portugal uses. When a consolidation exists the pipeline commits one
        # version per consolidation, and each of those bodies really is the law
        # as it stood on that date.
        has_cons = first.get("hasCons", {}).get("value", "") in ("1", "true")
        text_state = TextState.POINT_IN_TIME if has_cons or future_original else None

        # An as-enacted file that has been amended must name its most recent
        # amending act; one nobody has touched must not (spec v0.4 §Text state).
        last_amendment = first.get("lastAmendment", {}).get("value", "") or None
        if has_cons:
            last_amendment = None

        subjects_raw = first.get("subjects", {}).get("value", "")
        subjects = tuple(x for x in subjects_raw.split("|") if x)

        # Extra metadata
        extra_fields: list[tuple[str, str]] = []
        if source_facts:
            # Full RDF bindings retain source values, datatypes, language and
            # multiplicity; the selected generic fields are a convenience view.
            extra_fields.append(("source_metadata", strip_control(source_facts)))
        if eli:
            extra_fields.append(("eli", eli))
        document_date = first.get("date", {}).get("value", "")
        if document_date:
            extra_fields.append(("document_date", document_date))
        journals = sorted({b["journal"]["value"] for b in bindings if b.get("journal")})
        if journals:
            extra_fields.append(("official_journal", "|".join(journals)))
        if entry_force:
            extra_fields.append(("entry_into_force", entry_force.isoformat()))
        if future_original:
            extra_fields.append(("initial_effective_date", entry_force.isoformat()))
        end_values = {b["endValidity"]["value"] for b in bindings if b.get("endValidity")}
        # Multiple end dates may apply to different provisions; keep them raw.
        if end_validity and len(end_values) == 1:
            extra_fields.append(("end_of_validity", end_validity.isoformat()))
        signature = first.get("signature", {}).get("value", "")
        if signature:
            extra_fields.append(("signature_date", signature))
        eea = first.get("eea", {}).get("value", "")
        if eea:
            extra_fields.append(("eea_relevance", "true" if eea in ("1", "true") else "false"))
        if status is NormStatus.REPEALED and repealed_by:
            extra_fields.append(("repealed_by", repealed_by))
        # `celex` is only emitted where it differs from the identifier, which is
        # exactly the acts sanitised above. Everywhere else it was the identifier
        # a second time, byte for byte.
        if celex != source_celex:
            extra_fields.append(("celex", source_celex))
        # `regulation_type` was the name when only regulations existed.
        extra_fields.append(("resource_type", rtype_code))

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
            subjects=subjects,
            extra=tuple(extra_fields),
            text_state=text_state,
            last_amendment=last_amendment,
        )
