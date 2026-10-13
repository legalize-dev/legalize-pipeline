"""Text and metadata parsers for Irish Statute Book (ISB) legislation.

Parses ISB XML (custom format with <act>, <body>, <part>, <chapter>,
<sect>, <p>) into Block/Version/Paragraph and Oireachtas API JSON
into NormMetadata.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any
from urllib.parse import urljoin, urlsplit
from lxml import etree

from legalize.fetcher._tables import render_table
from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import Block, NormMetadata, NormStatus, Paragraph, Rank, TextState, Version
from legalize.fetcher._text import strip_control

logger = logging.getLogger(__name__)


@dataclass
class _ParseContext:
    """What one document accumulates while it is being parsed.

    This lives on the call stack, deliberately. Footnote definitions started out
    in a module-level list, and ``ie`` bootstraps with ``max_workers: 8``
    (``config.yaml``), so all eight workers appended into the same one: an act
    published another act's footnotes, and one act collected three acts' worth.
    Measured on two fixtures across eight threads, seven of the eight results
    were wrong. State that belongs to a document has to be reachable only from
    the call that parses it.
    """

    footnotes: list[tuple[str, str]] = field(default_factory=list)
    anchors: dict[str, str] = field(default_factory=dict)
    footnote_anchors: dict[str, tuple[str, str]] = field(default_factory=dict)


# The punctuation a Markdown renderer drops when it derives a heading's anchor.
# Mirrors github-slugger: accented letters and existing hyphens survive, which
# matters here because Irish headings carry them —
# "8. **Continuation of An Garda Síochána**" has to anchor at
# "8-continuation-of-an-garda-síochána" both on GitHub and on the site.
_ANCHOR_STRIP = re.compile(r"""[\u2000-\u206f\u2e00-\u2e7f'!"#$%&()*+,./:;<=>?@\[\]^`{|}~\\]""")


def _anchor(heading: str) -> str:
    """The anchor a Markdown renderer derives from a heading we emit.

    The heading is rendered verbatim after the ``#`` marks, so the anchor for a
    section is a pure function of the text ``_section_heading_text`` produced.
    """
    return _ANCHOR_STRIP.sub("", heading.lower().strip()).replace(" ", "-")


def _strip_repeated_marker(body: str, num: str) -> str:
    """Drop the marker ISB repeats at the head of a footnote's own body.

    The number sits twice in the source — once in <marker>, once as a <su> that
    opens the body — so the definition came out as "[^1]: ^1 OJ L2023/2831".
    """
    return body.removeprefix(f"^{num}").lstrip(" ,").strip() or body


def _section_heading_text(sect: etree._Element) -> str:
    """The heading line a <sect> will render as.

    Used both to emit the heading and, in a pre-pass, to work out the anchor a
    cross-reference to that section has to point at. One function so the two
    cannot drift: an anchor computed from a heading we do not actually emit is
    a dead link that no test would notice.
    """
    parts = []
    for tag in ("number", "title"):
        el = sect.find(tag)
        if el is not None:
            text = _inline_text(el)
            if text:
                parts.append(text)
    return " ".join(parts)


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
_SKIP_TAGS = frozenset({"hr1"})


def _image_note(source: str) -> str:
    """Keep content-bearing image omissions visible; the playbook excludes binary assets."""
    name = urlsplit(source).path.rsplit("/", 1)[-1].lower()
    return "" if name in {"harp.jpg", "seal.jpg", "ls"} else "[image omitted]"


# ── Inline text extraction ──────────────────────────────────────────


def _inline_text(elem: etree._Element, ctx: _ParseContext | None = None) -> str:
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
    - Graphics → omission note except decorative seals; hr1 → empty
    """
    parts: list[str] = []

    # Leading text
    if elem.text:
        parts.append(elem.text)

    for child in elem:
        tag = child.tag if isinstance(child.tag, str) else ""
        if not tag:
            if child.tail:
                parts.append(child.tail)
            continue

        if tag == "unicode":
            code = child.get("ch", "")
            if not re.fullmatch(r"[0-9A-Fa-f]{2,6}", code):
                raise ValueError(f"Invalid ISB Unicode character: {code!r}")
            value = int(code, 16)
            if value > 0x10FFFF or 0xD800 <= value <= 0xDFFF:
                raise ValueError(f"Invalid ISB Unicode code point: {code!r}")
            parts.append(chr(value))
            if child.tail:
                parts.append(child.tail)
            continue

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

        if tag == "graphic":
            parts.append(_image_note(child.get("href", "")))
            if child.tail:
                parts.append(child.tail)
            continue

        # Bold
        if tag in ("b", "strong"):
            inner = _inline_text(child, ctx).strip()
            if inner:
                parts.append(f"**{inner}**")
            if child.tail:
                parts.append(child.tail)
            continue

        # Italic
        if tag in ("i", "em"):
            inner = _inline_text(child, ctx).strip()
            if inner:
                parts.append(f"*{inner}*")
            if child.tail:
                parts.append(child.tail)
            continue

        # Superscript
        if tag == "su":
            inner = _inline_text(child, ctx).strip()
            if inner:
                parts.append(f"^{inner}")
            if child.tail:
                parts.append(child.tail)
            continue

        # Subscript (no MD equivalent, keep as-is)
        if tag == "sb":
            parts.append(_inline_text(child, ctx))
            if child.tail:
                parts.append(child.tail)
            continue

        # Cross-references. ISB hrefs are fragments into the act itself
        # ("#SEC4", sometimes a bare "SEC9"), never URLs, so the href cannot be
        # used as a link target directly: nothing in the Markdown answers to
        # "SEC4". It is resolved against the anchors of the headings this
        # document actually emits, and anything unresolvable — a reference into
        # another act, an id we never emitted a heading for — stays plain text.
        # A link that goes nowhere is worse than no link.
        if tag == "xref":
            inner = _inline_text(child, ctx).strip()
            target = None
            if ctx is not None:
                target = ctx.anchors.get(child.get("href", "").lstrip("#"))
            parts.append(f"[{inner}](#{target})" if inner and target else inner)
            if child.tail:
                parts.append(child.tail)
            continue

        # Footnotes: emit the marker inline, collect the definition for the
        # block at the end of the document.
        if tag == "fn":
            marker = child.find(".//marker")
            if marker is not None:
                num = _inline_text(marker).strip().lstrip("^")
                parts.append(f"[^{num}]")
                if ctx is not None:
                    body_parts = [
                        text
                        for fn_child in child
                        if (fn_child.tag if isinstance(fn_child.tag, str) else "")
                        not in ("", "marker")
                        and (text := _inline_text(fn_child, ctx).strip())
                    ]
                    if body_parts:
                        ctx.footnotes.append(
                            (num, _strip_repeated_marker(" ".join(body_parts), num))
                        )
            if child.tail:
                parts.append(child.tail)
            continue

        # Font tags: recurse
        if tag == "font":
            parts.append(_inline_text(child, ctx))
            if child.tail:
                parts.append(child.tail)
            continue

        # Marker (inside fn, handled above; standalone = skip)
        if tag == "marker":
            if child.tail:
                parts.append(child.tail)
            continue

        # Fallback: recurse into unknown tags
        parts.append(_inline_text(child, ctx))
        if child.tail:
            parts.append(child.tail)

    text = "".join(parts)
    text = strip_control(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ── Table conversion ────────────────────────────────────────────────


def _table_to_markdown(table_elem: etree._Element, ctx: _ParseContext | None = None) -> str:
    """Convert an ISB <table> element to a Markdown pipe table.

    The grid itself — colspan, rowspan, ragged rows, unquoted span attributes —
    is resolved by the shared renderer that seven other countries already use.
    Only the part that is actually ISB-specific stays here: a cell is one or
    more <p> children, and the inline formatting inside them is ours.
    """
    signature_table = "Signed" in "".join(table_elem.itertext()) and "Delegation" in "".join(
        table_elem.itertext()
    )

    def cell_text(cell):
        text = _cell_text(cell, ctx)
        plain = re.sub(r"\*+", "", text)
        if signature_table and any(c.isalpha() for c in plain) and plain.isupper():
            return f"**{plain}**"
        return text

    return render_table(table_elem, cell_text)


def _cell_text(td: etree._Element, ctx: _ParseContext | None = None) -> str:
    """Flatten one ISB <td> into the string that goes inside the pipe cell."""
    cell_parts = [text for p in td.findall("p") if (text := _inline_text(p, ctx))]
    if not cell_parts:
        text = _inline_text(td, ctx)
        if text:
            cell_parts.append(text)
    return " ".join(cell_parts).replace("|", "\\|")


# ── Legal paragraph presentation ─────────────────────────────────────


_ENUMERATOR = re.compile(
    r'^(?:F\d+\[)?[“"]?\*{0,2}\((?:\*{0,2})([0-9]+[A-Za-z]*|[A-Za-z]+)'
    r"(?:\*{0,2})\)\*{0,2}(?=\s|$)"
)


def _legal_format(paragraphs: list[Paragraph]) -> list[Paragraph]:
    """Render explicit legal labels and quotation boundaries consistently.

    This pass is shared by XML, HTML and PDF. It does not guess quotation from
    indentation: a block needs an opening quotation delimiter and either its
    closing delimiter or a continuation, or the explicit oath formula. Inline
    word substitutions never start a block. Legal labels remain verbatim; the
    Markdown bullets only expose their existing numeric/letter/roman hierarchy.
    """
    result = []
    lists: list[tuple[str, str]] = []
    quoted_lists: list[tuple[str, str]] = []
    quote_depth = 0
    quote_indent = ""
    for paragraph in paragraphs:
        text = paragraph.text
        if paragraph.css_class not in ("parrafo", "table", "list_item") or text.startswith("[^"):
            lists.clear()
            quoted_lists.clear()
            quote_depth = 0
            result.append(paragraph)
            continue
        plain = re.sub(r"\*+", "", text)
        leading = re.sub(r"^F\d+\[", "", plain)
        delta = plain.count("“") - plain.count("”")
        complete_quote = (
            leading.startswith("“") and bool(re.search(r"”[.,;:\s)\]]*(?:and|or)?$", plain))
        ) or (leading.startswith('"') and bool(re.search(r'"[.,;:\s)\]]*(?:and|or)?$', plain)))
        oath = bool(re.match(r"I\b.{0,100}\b(?:swear|promise and declare)\b", plain, re.I))
        begins = leading.startswith("“") and (delta > 0 or complete_quote)
        quoted = bool(quote_depth or begins or complete_quote or oath)
        if not quote_depth and quoted:
            quoted_lists.clear()
            quote_indent = " " * (4 * (len(lists) - 1) + 2) if lists else ""
        stack = quoted_lists if quoted else lists
        marker = _ENUMERATOR.match(text)
        if marker:
            label = marker[1]
            if label[0].isdigit():
                kind = "number"
            elif re.fullmatch(r"[ivxlcdm]+", label):
                # The letter (i) after (h), and (v) after (u), are alphabetical.
                alphabetic = len(label) == 1 and any(
                    k == "letter" and len(previous) == 1 and ord(label) == ord(previous) + 1
                    for k, previous in stack
                )
                kind = "letter" if alphabetic else "roman"
            elif re.fullmatch(r"[IVXLCDM]+", label):
                kind = "upper_roman"
            else:
                kind = "letter" if label.islower() else "upper_letter"
            kinds = [k for k, _ in stack]
            if kind in kinds:
                del stack[kinds.index(kind) :]
            elif stack:
                rank = {"number": 0, "letter": 1, "roman": 2, "upper_letter": 3, "upper_roman": 4}
                while stack and rank[stack[-1][0]] >= rank[kind]:
                    stack.pop()
            stack.append((kind, label))
            depth = len(stack) - 1
            # A compound source label denotes two nested entries, not one label.
            tail = text[marker.end() :].lstrip()
            inner = _ENUMERATOR.match(tail) if kind == "number" else None
            if inner and inner[1].islower():
                text = (
                    " " * (4 * depth)
                    + "- "
                    + text[: marker.end()]
                    + "\n"
                    + " " * (4 * (depth + 1))
                    + "- "
                    + tail
                )
                stack.append(("letter", inner[1]))
            else:
                text = " " * (4 * depth) + "- " + text
        elif plain.startswith("•"):
            # Preserve the source bullet as well as introducing a Markdown list.
            text = "- " + text
        elif quoted and stack:
            text = "\n".join(" " * (4 * (len(stack) - 1) + 2) + line for line in text.splitlines())
        elif not quoted and plain in ("and", "or") and lists:
            text = " " * (4 * (len(lists) - 1) + 2) + text
        elif not quoted:
            lists.clear()
        if quoted:
            if re.fullmatch(r"“(?:SCHEDULE|PART|CHAPTER)\s+[A-Z0-9]+", leading, re.I):
                text = "### " + text
            text = "\n".join(quote_indent + "> " + line for line in text.splitlines())
            quote_depth = max(0, quote_depth + delta) if (quote_depth or begins) else 0
        result.append(Paragraph("legal_quote" if quoted else paragraph.css_class, text))
    return result


# ── Text parser ─────────────────────────────────────────────────────


def _is_xml_source(data: bytes) -> bool:
    return data.lstrip().startswith((b"<?xml", b"<?version", b"<act", b"<privateact"))


class ISBTextParser(TextParser):
    """Parse ISB XML or HTML into Block objects."""

    def parse_text(self, data: bytes, *, published_on: date | None = None) -> list[Any]:
        """Parse Act text into a list of Blocks.

        Auto-detects XML vs HTML:
        - XML: ISB custom format (<act>, <body>, <part>, <sect>)
        - HTML: ISB print view (<div class="act-content">, <tr>, <td>)

        All content is flattened into a single Block with one Version.
        """
        stripped = data.lstrip()
        if stripped.startswith(b"{") and json.loads(data).get("legalize_ie") == 1:
            from legalize.fetcher.ie.history import parse_text

            return parse_text(data)
        if _is_xml_source(data):
            return self._parse_xml(data, published_on=published_on)
        return self._parse_html(data, published_on=published_on)

    def extract_reforms(self, data: bytes):
        if data.lstrip().startswith(b"{") and json.loads(data).get("legalize_ie") == 1:
            from legalize.fetcher.ie.history import extract_reforms

            return extract_reforms(data)
        from legalize.transformer.xml_parser import extract_reforms

        return extract_reforms(self.parse_text(data))

    def _parse_xml(self, data: bytes, *, published_on: date | None = None) -> list[Any]:
        """Parse the enacted XML, including early acts without section containers."""
        root = etree.fromstring(data)
        paragraphs: list[Paragraph] = []

        # Extract metadata for the Version
        pub_date = _xml_enactment_date(root) or published_on
        if pub_date is None:
            raise ValueError("ISB text has no enactment date")

        # Skip frontmatter (table of contents) — redundant with body
        body = root.find("body")
        if body is None:
            raise ValueError("ISB XML has no legislative body")

        ctx = _ParseContext()

        # A cross-reference can point at a section the walk has not reached yet,
        # so the anchors are collected before anything is emitted. <sect id> is
        # exactly the target ISB's hrefs use.
        #
        # Two sections that render the same heading would share an anchor, and a
        # renderer disambiguates those by appending a suffix — so the link would
        # quietly land on the wrong section. None of the fixtures do it, but the
        # corpus is ~4,000 acts nobody has read: an ambiguous anchor is dropped
        # and the reference falls back to plain text.
        seen: set[str] = set()
        for sect in root.iter("sect"):
            sect_id = sect.get("id")
            if not sect_id:
                continue
            heading = _section_heading_text(sect)
            if not heading:
                continue
            anchor = _anchor(heading)
            if anchor in seen:
                ctx.anchors = {k: v for k, v in ctx.anchors.items() if v != anchor}
                continue
            seen.add(anchor)
            ctx.anchors[sect_id] = anchor

        frontmatter = root.find("frontmatter")
        if frontmatter is not None:
            in_preamble = False
            for paragraph in frontmatter.findall("p"):
                text = _inline_text(paragraph, ctx)
                if re.match(
                    r"(?:An Act\b|Be it enacted\b|WHEREAS\b)", re.sub(r"\*+", "", text), re.I
                ):
                    in_preamble = True
                if in_preamble and text:
                    paragraphs.append(Paragraph(css_class="parrafo", text=text))
        self._parse_body(body, paragraphs, ctx)

        # Parse backmatter (schedules, tables, notes)
        backmatter = root.find("backmatter")
        if backmatter is not None:
            self._parse_backmatter(backmatter, paragraphs, ctx)

        # The definitions for every [^n] marker emitted above. Without this the
        # published corpus carries dangling Markdown references — 35 of them in
        # a single act before this landed.
        if ctx.footnotes:
            paragraphs.append(Paragraph(css_class="h2", text="Footnotes"))
            paragraphs.extend(
                Paragraph(css_class="parrafo", text=f"[^{num}]: {body_text}")
                for num, body_text in ctx.footnotes
            )

        if not paragraphs:
            raise ValueError("ISB XML has no legislative paragraphs")

        block = Block(
            id="full-text",
            block_type="document",
            title="",
            versions=(
                Version(
                    norm_id="",
                    publication_date=pub_date,
                    effective_date=pub_date,
                    paragraphs=tuple(_legal_format(paragraphs)),
                ),
            ),
        )
        return [block]

    def _parse_body(
        self, body: etree._Element, paragraphs: list[Paragraph], ctx: _ParseContext | None = None
    ) -> None:
        """Walk the body element tree and emit paragraphs."""
        for child in body:
            tag = child.tag if isinstance(child.tag, str) else ""

            if tag == "part":
                self._parse_part(child, paragraphs, ctx)
            elif tag == "chapter":
                self._parse_chapter(child, paragraphs, ctx)
            elif tag == "sect":
                self._parse_section(child, paragraphs, ctx)
            elif tag == "schedule":
                self._parse_schedule(child, paragraphs, ctx)
            elif tag == "p":
                self._parse_paragraph(child, paragraphs, ctx)
            elif tag == "table":
                md = _table_to_markdown(child, ctx)
                if md:
                    paragraphs.append(Paragraph(css_class="parrafo", text=md))

    def _parse_part(
        self, part: etree._Element, paragraphs: list[Paragraph], ctx: _ParseContext | None = None
    ) -> None:
        """Parse a <part> element."""
        title_el = part.find("title")
        if title_el is not None:
            title_text = _inline_text(title_el)
            if title_text:
                paragraphs.append(Paragraph(css_class="titulo_tit", text=title_text))

        for child in part:
            tag = child.tag if isinstance(child.tag, str) else ""
            if tag == "chapter":
                self._parse_chapter(child, paragraphs, ctx)
            elif tag == "sect":
                self._parse_section(child, paragraphs, ctx)
            elif tag == "p":
                self._parse_paragraph(child, paragraphs, ctx)
            elif tag == "table":
                md = _table_to_markdown(child, ctx)
                if md:
                    paragraphs.append(Paragraph(css_class="parrafo", text=md))
            elif tag == "schedule":
                self._parse_schedule(child, paragraphs, ctx)

    def _parse_chapter(
        self, chapter: etree._Element, paragraphs: list[Paragraph], ctx: _ParseContext | None = None
    ) -> None:
        """Parse a <chapter> element."""
        title_el = chapter.find("title")
        if title_el is not None:
            title_text = _inline_text(title_el)
            if title_text:
                paragraphs.append(Paragraph(css_class="capitulo_tit", text=title_text))

        for child in chapter:
            tag = child.tag if isinstance(child.tag, str) else ""
            if tag == "sect":
                self._parse_section(child, paragraphs, ctx)
            elif tag == "p":
                self._parse_paragraph(child, paragraphs, ctx)
            elif tag == "table":
                md = _table_to_markdown(child, ctx)
                if md:
                    paragraphs.append(Paragraph(css_class="parrafo", text=md))

    def _parse_section(
        self, sect: etree._Element, paragraphs: list[Paragraph], ctx: _ParseContext | None = None
    ) -> None:
        """Parse a <sect> element (a numbered section/article)."""
        # Same helper that seeded ctx.anchors, so the anchor a cross-reference
        # points at and the heading actually emitted cannot come apart.
        heading = _section_heading_text(sect)
        if heading:
            paragraphs.append(Paragraph(css_class="articulo", text=heading))

        # Section body paragraphs
        for child in sect:
            tag = child.tag if isinstance(child.tag, str) else ""
            if tag in ("number", "title"):
                continue  # Already handled
            if tag == "p":
                self._parse_paragraph(child, paragraphs, ctx)
            elif tag == "table":
                md = _table_to_markdown(child, ctx)
                if md:
                    paragraphs.append(Paragraph(css_class="parrafo", text=md))
            elif tag == "sect":
                # Nested subsections (rare but possible)
                self._parse_section(child, paragraphs, ctx)

    def _parse_schedule(
        self,
        schedule: etree._Element,
        paragraphs: list[Paragraph],
        ctx: _ParseContext | None = None,
    ) -> None:
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
                self._parse_paragraph(child, paragraphs, ctx)
            elif tag == "table":
                md = _table_to_markdown(child, ctx)
                if md:
                    paragraphs.append(Paragraph(css_class="parrafo", text=md))
            elif tag == "part":
                self._parse_part(child, paragraphs, ctx)
            elif tag == "sect":
                self._parse_section(child, paragraphs, ctx)

    def _parse_backmatter(
        self,
        backmatter: etree._Element,
        paragraphs: list[Paragraph],
        ctx: _ParseContext | None = None,
    ) -> None:
        """Parse <backmatter> which contains schedules, tables, and notes."""
        for child in backmatter:
            tag = child.tag if isinstance(child.tag, str) else ""
            if tag == "schedule":
                self._parse_schedule(child, paragraphs, ctx)
            elif tag == "p":
                text = _inline_text(child, ctx)
                if text:
                    paragraphs.append(Paragraph(css_class="firma_rey", text=text))
            elif tag == "table":
                md = _table_to_markdown(child, ctx)
                if md:
                    paragraphs.append(Paragraph(css_class="parrafo", text=md))

    def _parse_paragraph(
        self, p: etree._Element, paragraphs: list[Paragraph], ctx: _ParseContext | None = None
    ) -> None:
        """Parse a <p> element into a Paragraph."""
        text = _inline_text(p, ctx)
        if not text:
            return

        plain = re.sub(r"\*+", "", text)
        centered = "center" in p.get("class", "").split()
        if centered and re.fullmatch(r"ANNEX\.?", plain, re.I):
            paragraphs.append(Paragraph(css_class="anexo_num", text=text))
            return
        if (
            centered
            and plain.isupper()
            and re.fullmatch(r"[A-Z][A-Z ,’'()—-]+\.", plain)
            and any(item.css_class == "anexo_num" for item in paragraphs)
        ):
            paragraphs.append(Paragraph(css_class="seccion_tit", text=text))
            return

        if re.fullmatch(r"(?:\*\*)?Article\s+\d+[A-Z]*\.(?:\*\*)?", text, re.I):
            paragraphs.append(Paragraph(css_class="articulo", text=text))
            return

        # Early XML has numbered body paragraphs instead of <sect> containers.
        parent = p.getparent()
        if parent is not None and parent.tag == "body" and not parent.findall(".//sect"):
            marker = re.match(r"(?:\*\*)?(\d+[A-Z]?)\.(?:\*\*)?(?=\s|—)", text)
            if marker:
                paragraphs.append(Paragraph(css_class="articulo", text=f"{marker[1]}."))

        paragraphs.append(Paragraph(css_class="parrafo", text=text))

    # ── HTML parser (print view) ────────────────────────────────────

    def _parse_html(self, data: bytes, *, published_on: date | None = None) -> list[Any]:
        """Read the act's layout table, rendering only nested data tables as tables."""
        from lxml import html as lxml_html

        doc = lxml_html.fromstring(data)
        act = doc.find('.//div[@id="act"]')
        if act is None:
            act = doc.find('.//div[@id="si"]')
        if act is None:
            if doc.xpath('.//a[@id="article1" or @name="article1"]'):
                return self._parse_constitution_html(data)
            raise ValueError("ISB HTML has no legislative body")
        is_instrument = bool(
            re.match(r"(?:S\.\s*I\.|I\.\s*R\.)", doc.findtext(".//title") or "", re.I)
        )
        source_text = _html_text(act)
        pub_date = (
            _instrument_date(source_text, doc.findtext(".//title") or "")
            if is_instrument
            else _enactment_date(source_text)
        ) or published_on
        if pub_date is None:
            raise ValueError("ISB text has no enactment date")

        titles: dict[str, str] = {}
        for anchor in act.xpath(".//a[@name]"):
            name = anchor.get("name", "")
            if not re.fullmatch(r"sec\d+[A-Z]*", name, re.I):
                continue
            cell = anchor.getparent()
            row = cell.getparent()
            small = cell.find(".//small")
            if small is not None:
                titles[name[3:]] = _html_inline_text(small)
            elif row is not None:
                for sibling in row.findall("td"):
                    bold = sibling.find(".//b")
                    if bold is not None and not re.fullmatch(r"\d+[A-Z]*\.", _html_text(bold)):
                        titles[name[3:]] = _html_inline_text(bold)
                        break
        ctx = _ParseContext(
            anchors={f"sec{num}": _anchor(f"{num}. **{title}**") for num, title in titles.items()}
        )
        # Print views repeat definitions when a cited Directive occurs twice.
        # Match the source's footnote anchors, not arbitrary numbered paragraphs.
        footnote_nodes = set()
        definitions: dict[str, str] = {}
        for node in act.iter("p"):
            if not any(
                re.fullmatch(r"fn_\d+", a.get("name", a.get("id", ""))) for a in node.iter("a")
            ):
                continue
            match = re.match(r"\^?(\d+|\*+)\s+(.+)", _html_inline_text(node))
            if not match:
                match = re.match(r"\*\*Note \((\d+)\):\*\* (.+)", _html_inline_text(node))
            if not match:
                match = re.match(r"\((\d+)\)\s+(.+)", _html_inline_text(node))
                if match:
                    # A trailing schedule footnote continues through its indented bullet paragraphs.
                    for sibling in node.itersiblings():
                        if sibling.tag != "p" or not _html_text(sibling).startswith("—"):
                            break
                        footnote_nodes.add(sibling)
                elif node.find(".//sup") is not None:
                    match = re.match(r"\^?(\d+)([^\d\s].+)", _html_inline_text(node))
            if not match:
                raise ValueError("Malformed ISB HTML footnote definition")
            marker, body_text = match.groups()
            if _html_inline_text(node).startswith(f"({marker})"):
                for sibling in node.itersiblings():
                    if sibling not in footnote_nodes:
                        break
                    body_text += " " + _html_inline_text(sibling)
            number = marker if marker.isdigit() else f"star{len(marker)}"
            names = [
                anchor.get("name", anchor.get("id", ""))
                for anchor in node.iter("a")
                if re.fullmatch(r"fn_\d+", anchor.get("name", anchor.get("id", "")))
            ]
            existing = {
                ctx.footnote_anchors[f"ret_{name}"][0]
                for name in names
                if f"ret_{name}" in ctx.footnote_anchors
            }
            if existing:
                if len(existing) != 1 or definitions[next(iter(existing))] != body_text:
                    raise ValueError(f"Conflicting ISB HTML footnote {number}")
                number = next(iter(existing))
            elif number in definitions and definitions[number] != body_text:
                # Forms restart their visible numbering; the source anchors remain unique.
                number = f"{number}-{names[0]}"
            for anchor in node.iter("a"):
                name = anchor.get("name", anchor.get("id", ""))
                if re.fullmatch(r"fn_\d+", name):
                    source_marker = marker
                    if (
                        re.match(r"S\.I\. No\. 497/2003\b", doc.findtext(".//title") or "")
                        and name == "fn_5"
                        and marker == "6"
                        and body_text == "O.J. L 141/27 of 11/6/1993"
                    ):
                        # This source's sixth explicit return anchor is mislabelled "1".
                        source_marker = "1"
                    ctx.footnote_anchors[f"ret_{name}"] = (number, source_marker)
            definitions[number] = body_text
            footnote_nodes.add(node)
        ctx.footnotes.extend(definitions.items())
        sidebar_titles = {re.sub(r"\*+", "", value) for value in titles.values()}
        paragraphs: list[Paragraph] = []
        in_body = is_instrument
        current_section = ""
        emitted: set[str] = set()
        pending: tuple[str, str] | None = None
        in_schedule = False
        in_signature = False

        def flush() -> None:
            nonlocal pending
            if pending:
                paragraphs.append(Paragraph(css_class=pending[0], text=pending[1]))
                pending = None

        def walk(node):
            # ISB wraps the document in a layout table; its nested tables are data.
            if node.tag == "table" and node is not act.find("table"):
                yield node
                return
            if node.tag in ("p", "a"):
                yield node
                return
            for child in node:
                if isinstance(child.tag, str):
                    yield from walk(child)

        for node in walk(act):
            if node in footnote_nodes:
                continue
            if node.tag == "a":
                name = node.get("name", "")
                if re.fullmatch(r"sec\d+[A-Z]*", name, re.I):
                    current_section = name[3:]
                continue
            if node.tag == "table":
                if in_body:
                    flush()
                    text = render_table(node, lambda cell: _html_inline_text(cell, ctx))
                    if text:
                        paragraphs.append(Paragraph(css_class="table", text=text))
                continue
            plain = _html_text(node)
            text = _html_inline_text(node, ctx)
            if not plain:
                continue
            if not in_body:
                # The enactment formula is present even when an early act has no TOC.
                if re.match(r"(?:An Act\b|Be it enacted\b|WHEREAS\b)", plain, re.I):
                    in_body = True
                else:
                    continue
            if plain in sidebar_titles:
                continue
            style = re.sub(r"\s+", "", node.get("style", ""))
            if "text-align:center" in style:
                heading = re.match(
                    r"^(PART\s+\S+|Chapter\s+\S+|SCHEDULE(?:\s+\S+)?)\.?$", plain, re.I
                )
                if heading:
                    flush()
                    label = heading[1]
                    css = "capitulo_tit" if label.lower().startswith("chapter") else "titulo_tit"
                    pending = (css, text)
                    in_schedule = in_schedule or label.upper().startswith("SCHEDULE")
                    continue
                if pending and not plain.startswith(("“", '"')):
                    paragraphs.append(Paragraph(css_class=pending[0], text=f"{pending[1]} {text}"))
                    pending = None
                    continue
                # A centred formula or schedule caption is content, not decoration.
            flush()
            marker = re.match(r"(?:\*\*)?(\d+[A-Z]?)\.(?:\*\*)?(?=\s|—)", text)
            if marker and not in_schedule:
                num = marker[1]
                is_section = current_section == num if titles else num == str(len(emitted) + 1)
                if is_section and num not in emitted:
                    heading = f"{num}. **{titles[num]}**" if num in titles else f"{num}."
                    paragraphs.append(Paragraph(css_class="articulo", text=heading))
                    emitted.add(num)
            if re.match(r"GIVEN under.{0,100}\bSeal\b", plain, re.I):
                in_signature = True
            elif plain == "EXPLANATORY NOTE":
                in_signature = False
            css = (
                "firma"
                if in_signature
                and plain.isupper()
                and len(plain.split()) <= 8
                and not any(c.isdigit() for c in plain)
                else "parrafo"
            )
            paragraphs.append(Paragraph(css_class=css, text=text))
        flush()
        if ctx.footnotes:
            paragraphs.append(Paragraph(css_class="h2", text="Footnotes"))
            paragraphs.extend(
                Paragraph(css_class="parrafo", text=f"[^{number}]: {body_text}")
                for number, body_text in ctx.footnotes
            )
        if not paragraphs:
            raise ValueError("ISB HTML has no legislative paragraphs")
        return [
            Block(
                id="full-text",
                block_type="document",
                title="",
                versions=(
                    Version(
                        norm_id="",
                        publication_date=pub_date,
                        effective_date=pub_date,
                        paragraphs=tuple(_legal_format(paragraphs)),
                    ),
                ),
            )
        ]

    def _parse_constitution_html(self, data: bytes) -> list[Any]:
        """Read the visible English text, excluding the amendment-history preface."""
        from lxml import html as lxml_html

        doc = lxml_html.fromstring(data)
        content = doc.find('.//div[@class="col-md-8 col-md-offset-2 col-sm-12"]')
        if content is None:
            raise ValueError("Constitution HTML has no content wrapper")
        paragraphs: list[Paragraph] = []
        in_body = False
        for element in content.iter():
            if element.tag != "p" and not (
                element.tag in ("h3", "h4", "h5") and not element.findall(".//p")
            ):
                continue
            if any(
                "display:none" in re.sub(r"\s+", "", e.get("style", ""))
                or "irish_language" in e.get("class", "").split()
                for e in (element, *element.iterancestors())
            ):
                continue
            text = _html_inline_text(element)
            plain = _html_text(element)
            if in_body and plain == "INDEX":
                break
            if "In the Name of the Most Holy Trinity" in text:
                in_body = True
                paragraphs.append(Paragraph(css_class="titulo_tit", text="Preamble"))
            if not in_body or not text:
                continue
            previous = element.getprevious()
            anchor = (
                previous.find(".//a[@name]")
                if previous is not None and previous.tag in ("h3", "h4", "h5")
                else None
            )
            if re.fullmatch(r"ARTICLE\s+\d+[A-Z]*", plain):
                paragraphs.append(Paragraph(css_class="articulo", text=plain))
            elif anchor is not None:
                name = anchor.get("name", "")
                css = (
                    "articulo"
                    if name.startswith("article")
                    else "titulo_tit"
                    if name.startswith("part")
                    else "capitulo_tit"
                )
                paragraphs.append(Paragraph(css_class=css, text=_html_text(element)))
            else:
                paragraphs.append(Paragraph(css_class="parrafo", text=text))
        if not paragraphs:
            raise ValueError("Constitution HTML has no English legislative text")
        # The metadata declares CURRENT: this publication date never claims a 1937 snapshot.
        published = date(1937, 7, 1)
        return [
            Block(
                id="full-text",
                block_type="document",
                title="",
                versions=(
                    Version(
                        norm_id="",
                        publication_date=published,
                        effective_date=None,
                        paragraphs=tuple(_legal_format(paragraphs)),
                        text_state=TextState.CURRENT,
                    ),
                ),
            )
        ]


# ── Revised Acts parser ──────────────────────────────────────────────


# Revised Acts fills <div class="number"> with the section's anchor instead of
# its number for a handful of sections inserted by amendment — "SEC30N" where
# the section is 30N, ">257E" where it is 257E. Eight headings across two of the
# ~560 revised acts, which published as "##### SEC30N. **…**": not addressable
# by the number the section actually has.
_SECTION_NUMBER_JUNK = re.compile(r"^(?:SEC|>)+", re.IGNORECASE)


def _clean_section_number(raw: str) -> str:
    """The section number, with the anchor the source sometimes sends instead.

    Only rewrites when what is left is a section number. Anything else is
    returned untouched: a heading that reads oddly is better than one carrying
    a number we invented.
    """
    cleaned = _SECTION_NUMBER_JUNK.sub("", raw.strip())
    return cleaned if re.fullmatch(r"\d+[A-Z]*", cleaned) else raw


def parse_revised_html(data: bytes) -> tuple[list[Paragraph], date | None]:
    """Read a Revised Act once in source order, including schedules and tables."""
    from lxml import html as lxml_html

    doc = lxml_html.fromstring(data)
    # Some inserted Part titles contain their editorial annotation subtree.
    for annotation in doc.xpath(
        './/div[contains(concat(" ", normalize-space(@class), " "), " annotations ")]'
    ):
        annotation.drop_tree()
    updated_to = None
    for element in doc.iter("p"):
        match = re.match(r"Updated to (\d{1,2}) (\w+) (\d{4})", _html_text(element))
        if match:
            updated_to = _parse_date_from_parts(int(match[1]), match[2], int(match[3]))
            break
    body = doc.find('.//div[@class="body"]')
    if body is None:
        raise ValueError("Revised Act HTML has no legislative body")
    roots = [body]
    backmatter = doc.find('.//div[@class="backmatter"]')
    if backmatter is not None:
        roots.append(backmatter)
    headings: dict[etree._Element, tuple[str, str]] = {}
    ctx = _ParseContext()
    for root in roots:
        for footer in root.iter("footer"):
            for paragraph in footer.iter("p"):
                marker = paragraph.find(".//sup")
                if marker is not None and (number := _html_text(marker)).isdigit():
                    text = _html_inline_text(paragraph, base_url=_REVISED_BASE)
                    ctx.footnotes.append((number, _strip_repeated_marker(text, number)))
    seen: set[str] = set()
    for root in roots:
        for section in root.iter("section"):
            if any(e.get("class") == "annotations" for e in section.iterancestors()):
                continue
            kind = section.get("class", "")
            title_el = section.find("div[@class='title']")
            number_el = section.find("div[@class='number']")
            title = _html_text(title_el) if title_el is not None else ""
            number = (
                _clean_section_number(_html_text(number_el)).rstrip(".")
                if number_el is not None
                else ""
            )
            if kind == "sect":
                heading = (
                    f"{number}. **{title}**"
                    if number and title
                    else f"{number}."
                    if number
                    else title
                )
                css = "articulo"
            elif kind in ("part", "chapter", "schedule"):
                heading = title or number
                css = "capitulo_tit" if kind == "chapter" else "titulo_tit"
            else:
                continue
            if heading:
                headings[section] = (css, heading)
                anchor = _anchor(heading)
                if anchor in seen:
                    ctx.anchors = {k: v for k, v in ctx.anchors.items() if v != anchor}
                elif section.get("id"):
                    ctx.anchors[section.get("id")] = anchor
                seen.add(anchor)
    paragraphs: list[Paragraph] = []
    frontmatter = doc.find('.//div[@class="frontmatter"]')
    if frontmatter is not None:
        in_preamble = False
        for paragraph in frontmatter.findall("p"):
            plain = _html_text(paragraph)
            if re.match(r"(?:An Act\b|Be it enacted\b|WHEREAS\b)", plain, re.I):
                in_preamble = True
            if in_preamble and plain:
                paragraphs.append(
                    Paragraph(
                        css_class="parrafo", text=_html_inline_text(paragraph, ctx, _REVISED_BASE)
                    )
                )

    def walk(element):
        kind = element.get("class", "")
        if kind in ("annotations", "actsreferredto", "narrative") or element.tag == "footer":
            return
        if element in headings:
            css, heading = headings[element]
            paragraphs.append(Paragraph(css_class=css, text=heading))
        if element.tag == "table":
            text = render_table(element, lambda cell: _html_inline_text(cell, ctx, _REVISED_BASE))
            if text:
                paragraphs.append(Paragraph(css_class="table", text=text))
            return
        if element.tag == "p":
            text = _html_inline_text(element, ctx, _REVISED_BASE)
            if text:
                paragraphs.append(Paragraph(css_class="parrafo", text=text))
            return
        for child in element:
            if not isinstance(child.tag, str):
                continue
            if element in headings and child.get("class") in ("title", "number"):
                continue
            walk(child)

    for root in roots:
        walk(root)
    if ctx.footnotes:
        paragraphs.append(Paragraph(css_class="h2", text="Footnotes"))
        paragraphs.extend(
            Paragraph(css_class="parrafo", text=f"[^{number}]: {text}")
            for number, text in ctx.footnotes
        )
    if not paragraphs:
        raise ValueError("Revised Act HTML has no legislative paragraphs")
    return _legal_format(paragraphs), updated_to


_REVISED_BASE = "https://revisedacts.lawreform.ie"


def _html_text(elem) -> str:
    """Extract plain text from an lxml.html element."""
    try:
        text = elem.text_content()
    except (ValueError, AttributeError):
        return ""
    text = strip_control(text)
    return re.sub(r"\s+", " ", text).strip()


def _html_inline_text(
    elem,
    ctx: _ParseContext | None = None,
    base_url: str = "https://www.irishstatutebook.ie",
) -> str:
    """Preserve nested emphasis, links and separators without dropping text tails."""

    def inline(node):
        parts = [node.text or ""]
        for child in node:
            tag = child.tag if isinstance(child.tag, str) else ""
            if tag in ("", "script", "style"):
                text = ""
            elif (
                tag == "a"
                and ctx
                and child.get("name", child.get("id", "")) in ctx.footnote_anchors
            ):
                number, marker = ctx.footnote_anchors[child.get("name", child.get("id", ""))]
                # Older print views put an asterisk immediately before an empty
                # return anchor instead of using a superscript element.
                if marker.startswith("*") and parts[-1].rstrip().endswith(marker):
                    parts[-1] = parts[-1].rstrip()[: -len(marker)] + f"[^{number}]"
                elif marker.isdigit() and parts[-1].rstrip().endswith(f"({marker})"):
                    parts[-1] = parts[-1].rstrip()[: -len(marker) - 2] + f"[^{number}]"
                text = ""
                if re.search(rf"Note \({re.escape(marker)}\)\*\*\s*$", "".join(parts)):
                    text = f"[^{number}]"
            elif tag == "br":
                text = " "
            elif tag == "img":
                text = _image_note(child.get("src", ""))
            else:
                text = inline(child)
                if tag in ("b", "strong", "i", "em") and text.strip():
                    marker = "**" if tag in ("b", "strong") else "*"
                    text = (
                        (" " if text[:1].isspace() else "")
                        + marker
                        + text.strip()
                        + marker
                        + (" " if text[-1:].isspace() else "")
                    )
                elif tag == "sup" and text.strip():
                    number = text.strip()
                    following = child.getnext()
                    target = (
                        ctx.footnote_anchors.get(following.get("name", following.get("id", "")))
                        if ctx and following is not None and following.tag == "a"
                        else None
                    )
                    if target:
                        if target[1] != number:
                            raise ValueError(
                                f"ISB HTML footnote marker disagrees with its anchor: {number}"
                            )
                        number = target[0]
                    text = (
                        f"[^{number}]"
                        if ctx and any(n == number for n, _ in ctx.footnotes)
                        else f"^{number}"
                    )
                elif tag == "a" and text.strip():
                    href = child.get("href", "")
                    if href.startswith("#"):
                        anchor = ctx.anchors.get(href[1:]) if ctx else None
                        href = f"#{anchor}" if anchor else ""
                    elif href:
                        href = urljoin(base_url, href)
                        if urlsplit(href).scheme not in ("http", "https"):
                            href = ""
                    if href:
                        text = f"[{text.strip()}]({href})"
                elif tag in ("p", "div", "li"):
                    text += " "
            parts.append(text)
            parts.append(child.tail or "")
        return "".join(parts)

    return re.sub(r"\s+", " ", strip_control(inline(elem))).strip()


def _gazette_date(text: str) -> date | None:
    """Read an explicit Iris Oifigiúil notice date."""
    match = re.search(
        r"Iris Oifigiúil[’”\"]?\s+of\s+(\d{1,2})(?:st|nd|rd|th)?\s+(\w+),?\s+(\d{4})",
        text,
        re.I,
    )
    return _parse_date_from_parts(int(match[1]), match[2], int(match[3])) if match else None


# Only these conflicting XML dates have been corroborated against official source documents.
_XML_ENACTMENT_CORRECTIONS = {
    ("5", "1922"): ("19221202", "1922-12-21", "/isbc/1922_5.html"),
    ("24", "1924"): ("19240610", "1924-07-10", "/isbc/1924_24.html"),
    ("21", "1925"): ("19250621", "1925-06-27", "/isbc/1925_21.html"),
    ("22", "1925"): ("19250621", "1925-06-27", "/isbc/1925_22.html"),
    ("10", "1926"): ("19260301", "1926-03-11", "/isbc/1926_10.html"),
    ("17", "1926"): ("19260521", "1926-05-27", "/eli/1926/act/17/enacted/en/html"),
    ("33", "1926"): ("19260711", "1926-07-17", "/isbc/1926_33.html"),
    ("15", "1931"): ("19310521", "1931-05-27", "/isbc/1931_15.html"),
    ("5", "1931"): ("19310321", "1931-03-27", "/isbc/1931_5.html"),
    ("18", "1933"): ("19330721", "1933-07-27", "/isbc/1933_18.html"),
    ("P2", "1933"): ("19330711", "1933-07-17", "/eli/1933/prv/2/enacted/en/html"),
    ("23", "1934"): ("19340605", "1934-06-06", "/isbc/1934_23.html"),
    ("5", "1935"): ("19350219", "1935-02-27", "/eli/1935/act/5/enacted/en/html"),
    ("34", "1936"): ("19360624", "1936-07-24", "/isbc/1936_34.html"),
    ("20", "1938"): ("19380721", "1938-07-27", "/isbc/1938_20.html"),
    ("21", "1941"): ("19410801", "1941-08-07", "/isbc/1941_21.html"),
    ("19", "1947"): ("19470619", "1947-07-19", "/eli/1947/act/19/enacted/en/html"),
    ("10", "1956"): ("19560321", "1956-03-27", "/isbc/1956_10.html"),
    ("26", "1958"): ("19581125", "1958-07-30", "/isbc/1958_26.html"),
    ("21", "1959"): ("19590719", "1959-07-29", "/isbc/1959_21.html"),
    ("13", "1960"): ("19600502", "1960-05-24", "/isbc/1960_13.html"),
    ("12", "1966"): ("19660531", "1966-06-01", "/isbc/1966_12.html"),
    ("5", "1967"): ("19670767", "1967-03-07", "/isbc/1967_5.html"),
    ("25", "1972"): ("19721102", "1972-11-29", "/isbc/1972_25.html"),
    ("14", "1974"): ("19740621", "1974-06-27", "/isbc/1974_14.html"),
    ("7", "1979"): ("19790310", "1979-03-20", "/eli/1979/act/7/enacted/en/html"),
    ("4", "1992"): ("19920308", "1992-03-18", "/isbc/1992_4.html"),
    ("5", "1996"): ("19960306", "1996-03-16", "/isbc/1996_5.html"),
    ("13", "2004"): ("20040005", "2004-05-05", "/pdf/2004/en.act.2004.0013.pdf"),
    ("16", "2005"): ("20050719", "2005-07-09", "/pdf/2005/en.act.2005.0016.pdf"),
    ("26", "2005"): ("20051017", "2005-11-27", "/pdf/2005/en.act.2005.0026.pdf"),
    ("31", "2006"): ("2006", "2006-12-11", "/pdf/2006/en.act.2006.0031.pdf"),
    ("39", "2006"): ("2006", "2006-12-23", "/pdf/2006/en.act.2006.0039.pdf"),
    ("22", "2013"): ("20130604", "2013-07-02", "/isbc/2013_22.html"),
    ("27", "2013"): ("20130724", "2013-07-22", "/pdf/2013/en.act.2013.0027.pdf"),
    ("5", "2013"): ("20130205", "2013-03-13", "/pdf/2013/en.act.2013.0005.pdf"),
    ("21", "2014"): ("20140726", "2014-07-28", "/pdf/2014/en.act.2014.0021.pdf"),
    ("5", "2015"): ("20141119", "2015-03-11", "/pdf/2015/en.act.2015.0005.pdf"),
    ("24", "2019"): ("20190724", "2019-07-11", "/pdf/2019/en.act.2019.0024.pdf"),
    ("44", "2021"): ("20211215", "2021-12-18", "/pdf/2021/en.act.2021.0044.pdf"),
    ("46", "2021"): ("20211231", "2021-12-21", "/pdf/2021/en.act.2021.0046.pdf"),
}


def _xml_printed_identities(root) -> set[tuple[str, str]]:
    return {
        (f"{'P' if match[2] else ''}{match[1]}", match[3])
        for node in root.findall("frontmatter/actnumber")
        if (
            match := re.fullmatch(
                r"Number\s+(\d+)(?:\s+\(\s*(Private)\s*\))?\s+of\s+(\d{4})\.?",
                " ".join(" ".join(node.itertext()).split()),
                re.I,
            )
        )
    }


def _xml_date_correction(root):
    identities = _xml_printed_identities(root)
    if len(identities) == 1:
        correction = _XML_ENACTMENT_CORRECTIONS.get(next(iter(identities)))
        if correction and root.findtext("metadata/dateofenactment") == correction[0]:
            return correction
    return None


def _xml_enactment_date(root) -> date | None:
    raw = root.findtext("metadata/dateofenactment") or ""
    if not raw:
        return None
    front = root.find("frontmatter")
    if (re.fullmatch(r"\d{7,9}", raw) or _xml_date_correction(root)) and front is not None:
        printed = _enactment_date("".join(front.itertext()))
        if printed is not None:
            if not any(
                re.fullmatch(rf"{printed.year}0*{first}0*{second}", raw)
                for first, second in ((printed.month, printed.day), (printed.day, printed.month))
            ):
                correction = _xml_date_correction(root)
                if not correction or correction[1] != printed.isoformat():
                    raise ValueError(f"Conflicting ISB enactment dates: {raw!r}, {printed}")
            return printed
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid ISB enactment date: {raw!r}") from exc


def _enactment_date(text: str) -> date | None:
    match = re.search(r"\[(\d{1,2})\s*(?:st|nd|rd|th)?\s+(\w+)\s*,?\s+(\d{4})\.?\]", text, re.I)
    if match:
        return _parse_date_from_parts(int(match[1]), match[2], int(match[3]))
    return _gazette_date(text) or _made_date(text)


# Independently verified official copies fill dates omitted by these eISB transcriptions.
_INSTRUMENT_DATE_EVIDENCE = {
    ("575", "2002"): (
        "2002-12-17",
        "gazette_notice",
        "https://www.irisoifigiuil.ie/archive/2002/december/2002%2012%2017%20IO%20Issue.PDF#page=3",
        (),
    ),
    ("79", "2003"): (
        "2003-02-28",
        "final_signature",
        "https://www.comreg.ie/media/2024/12/SI-79-of-2003-Govt-Publications.pdf#page=20",
        ("2003-02-18", "2003-02-28"),
    ),
    ("497", "2003"): (
        "2003-11-07",
        "gazette_notice",
        "https://www.irisoifigiuil.ie/archive/2003/november/2003%2011%2007%20IO%20Issue.PDF#page=2",
        ("2003-10-21",),
    ),
}


def _instrument_date_evidence(title: str):
    match = re.match(r"S\.\s*I\.\s*No\.\s*(\d+)/(\d{4})\b", title, re.I)
    return _INSTRUMENT_DATE_EVIDENCE.get(match.groups()) if match else None


def _instrument_date(text: str, title: str) -> date | None:
    if published := _gazette_date(text) or _made_date(text):
        return published
    if evidence := _instrument_date_evidence(title):
        return date.fromisoformat(evidence[0])
    return None


def _signature_dates(text: str) -> list[date]:
    """Read explicit signature and concurrence dates, never commencement clauses."""
    ordinals = (
        "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth "
        "thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth"
    ).split()
    ordinals += [f"twenty-{word}" for word in ordinals[:9]] + ["thirtieth", "thirty-first"]
    for day, word in sorted(enumerate(ordinals, 1), key=lambda item: len(item[1]), reverse=True):
        text = re.sub(
            rf"\b{word.replace('-', '[- ]')}\b(?=\s+day\s*of)", str(day), text, flags=re.I
        )
    units = "one two three four five six seven eight nine".split()
    numbers = (
        [""]
        + units
        + "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
    )
    for tens in "twenty thirty forty fifty sixty seventy eighty ninety".split():
        numbers += [tens] + [f"{tens}-{unit}" for unit in units]
    written_year = (
        r"\bone thousand,? nine hundred(?: and)?[ -]+("
        + "|".join(word.replace("-", "[- ]") for word in sorted(numbers[1:], key=len, reverse=True))
        + r")\b"
    )
    text = re.sub(
        written_year,
        lambda match: str(1900 + numbers.index(match[1].lower().replace(" ", "-"))),
        text,
        flags=re.I,
    ).replace("_", " ")
    matches = re.finditer(
        r"(?:(?:GIVEN under|SEALED with).{0,180}?\b(?:Seal|hand)\b[^0-9]{0,180}?|GIVEN\s+(?:this|on),?\s+|"
        r"PRESENT when the Common Seal.{0,180}?this\s+|GIVEN under the official of the Minister[^0-9]{0,180}?|"
        r"ARNA THABHAIRT.{0,180}?Shéala Oifigiúil,\s*|"
        r"Dated\s*,?\s*(?:(?:this|the)\s+)?|Made\s+|SIGNED[^0-9]{0,180}?\bthis\s+(?:the\s+)?|DUBLIN\.\s+This\s+)"
        r"(\d{1,2})\s*(?:st|nd|rd|th|h)?[.,]?(?:\s*(?:day\s*)?of)?\s*"
        r"([A-Za-z]+|\d{1,2}(?:st|nd|rd|th)?)\s*[, .]?\s+(?:day of\s+)?(\d{4})",
        text,
        re.I,
    )
    irish_matches = re.finditer(
        r"ARNA THABHAIRT.{0,180}?Shéala Oifigiúil,?\s+an\s+(\d{1,2})ú?\s+lá seo de\s+(\w+),?\s+(\d{4})",
        text,
        re.I,
    )
    reversed_matches = re.finditer(
        r"Social Welfare this (\d{1,2})(?:st|nd|rd|th)? day of (\w+), (\d{4})\. "
        r"BRENDAN CORISH, Minister for Social Welfare\. GIVEN under the Official Seal of the Minister for",
        text,
        re.I,
    )
    return sorted(
        {
            _parse_date_from_parts(int(match[1]), match[2], int(match[3]))
            for match in [*matches, *irish_matches, *reversed_matches]
        }
    )


def _made_date(text: str) -> date | None:
    """Use the final required signature, including ministerial concurrence."""
    dates = _signature_dates(text)
    return dates[-1] if dates else None


def _parse_date_from_parts(day: int, month_str: str, year: int) -> date:
    """Parse date from day + month name + year."""
    months = {
        "january": 1,
        "february": 2,
        "march": 3,
        "marcg": 3,  # The enacted 2021 Act 3 XML mistypes March.
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
        "decembe": 12,  # The enacted 2017 Act 33 XML truncates December.
        "feabhra": 2,
    }
    months.update({name[:3]: value for name, value in list(months.items())})
    month = months.get(month_str.lower())
    if re.fullmatch(r"\d{1,2}(?:st|nd|rd|th)?", month_str, re.I):
        month = int(re.match(r"\d+", month_str)[0])
    if month is None:
        raise ValueError(f"Unknown month in Irish source: {month_str!r}")
    return date(year, month, day)


# ── Metadata parser ─────────────────────────────────────────────────


class ISBMetadataParser(MetadataParser):
    """Parse Oireachtas API JSON into NormMetadata."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        """Parse metadata JSON from Oireachtas API.

        The data is the raw response from /v1/legislation.
        norm_id is 'IE-{year}-act-{number}' or 'IE-1937-constitution'.
        """
        # Constitution: not in the Oireachtas API. Return hardcoded
        # metadata to avoid a wasted round-trip.
        if norm_id == "IE-1937-constitution":
            # publication_date: enacted by plebiscite 1 July 1937.
            # The Constitution came into operation on 29 December 1937.
            # We use the plebiscite date because that is when the text
            # was adopted. The operation date is administrative.
            extra = [("title_ga", "Bunreacht na hÉireann"), ("operation_date", "1937-12-29")]
            if data.lstrip().startswith(b"<"):
                from lxml import html as lxml_html

                text = _html_text(lxml_html.fromstring(data))
                enrolled = re.search(r"text enrolled on (\d{1,2}) (\w+),? (\d{4})", text)
                if enrolled:
                    value = _parse_date_from_parts(int(enrolled[1]), enrolled[2], int(enrolled[3]))
                    extra.append(("enrollment_date", value.isoformat()))
            return NormMetadata(
                title="Bunreacht na hÉireann / Constitution of Ireland",
                short_title="Constitution of Ireland",
                identifier="IE-1937-constitution",
                country="ie",
                rank=Rank("constitution"),
                publication_date=date(1937, 7, 1),
                status=NormStatus.IN_FORCE,
                department="",
                source="https://www.irishstatutebook.ie/eli/cons/en/html",
                extra=tuple(extra),
                text_state=TextState.CURRENT,
            )

        if data.lstrip().startswith(b"<"):
            return self._from_source(data, norm_id)
        response = json.loads(data)

        if response.get("legalize_ie_metadata") == 1:
            source = self._from_source(
                base64.b64decode(response["enacted"], validate=True), norm_id
            )
            bill = self._parliament_bill(response["parliament"], norm_id)
            extra, summary, pdf_url = self._parliament_fields(bill)
            return replace(
                source,
                extra=source.extra + tuple(extra.items()),
                summary=summary,
                pdf_url=pdf_url,
            )

        # Retain compatibility with saved parliamentary responses. New downloads
        # always reconcile these supplementary records with the enacted source.
        bill = self._parliament_bill(response, norm_id)
        act = bill["act"]
        title = act.get("shortTitleEn", "")
        if not title:
            raise ValueError(f"{norm_id}: source does not state a title")
        pub_date = _parse_date_str(act.get("dateSigned", ""))
        if not pub_date:
            raise ValueError(f"{norm_id}: source does not state an enactment date")
        extra, summary, pdf_url = self._parliament_fields(bill)
        extra = {
            "official_number": str(act["actNo"]),
            "year": str(act["actYear"]),
            "enactment_date": pub_date.isoformat(),
            "publication_date_basis": "parliament_date_signed",
            **extra,
        }
        return NormMetadata(
            title=title,
            short_title=title,
            identifier=norm_id,
            country="ie",
            rank=Rank("act"),
            publication_date=pub_date,
            status=NormStatus.IN_FORCE,
            department="",
            source=_source_url(norm_id),
            pdf_url=pdf_url,
            summary=summary,
            extra=tuple(extra.items()),
        )

    @staticmethod
    def _parliament_bill(response: dict, norm_id: str) -> dict:
        """Validate the full Act identity before using parliamentary enrichment."""
        results = response.get("results", [])
        if not results:
            raise ValueError(f"{norm_id}: no Oireachtas metadata; ISB source metadata required")
        bill = results[0].get("bill", {})
        act = bill.get("act", {})
        expected = norm_id.split("-")
        if str(act.get("actYear")) != expected[1] or str(act.get("actNo")) != expected[3]:
            raise ValueError(f"{norm_id}: Oireachtas metadata identifies a different Act")
        return bill

    @staticmethod
    def _parliament_fields(bill: dict) -> tuple[dict[str, str], str, str | None]:
        """Preserve API fields under their source label, without claiming language accuracy."""
        act = bill["act"]
        extra = {"parliament_metadata": json.dumps(bill, sort_keys=True, ensure_ascii=False)}
        for field_name, key in (
            ("shortTitleEn", "parliament_title_en"),
            ("shortTitleGa", "parliament_title_ga"),
            ("longTitleEn", "parliament_long_title_en"),
            ("longTitleGa", "parliament_long_title_ga"),
            ("dateSigned", "parliament_date_signed"),
        ):
            if value := act.get(field_name):
                extra[key] = str(value)
        if act.get("uri"):
            extra["oireachtas_uri"] = act["uri"]
        related = [
            doc.get("relatedDoc", doc).get("docType", "") for doc in bill.get("relatedDocs", [])
        ]
        if any(related):
            extra["related_docs"] = ", ".join(value for value in related if value)
        pdf_url = None
        for record in act.get("versions") or bill.get("versions") or []:
            version = record.get("version", record)
            if version.get("docType") != "act" or version.get("lang", "eng") not in {"en", "eng"}:
                continue
            pdf = (version.get("formats") or {}).get("pdf") or {}
            if pdf.get("uri"):
                pdf_url = pdf["uri"]
                break
        summary = re.sub(r"<[^>]+>", "", act.get("longTitleEn") or "").strip()
        return extra, summary, pdf_url

    def _from_source(self, data: bytes, norm_id: str) -> NormMetadata:
        """Use an ISB document when the parliamentary catalogue has no matching Act."""
        from lxml import html as lxml_html

        source_url = _source_url(norm_id)
        if _is_xml_source(data):
            root = etree.fromstring(data)
            meta = root.find("metadata")
            if meta is None:
                raise ValueError(f"{norm_id}: ISB XML has no metadata")
            expected = norm_id.split("-")
            expected_identity = (expected[3].lstrip("CP"), expected[1])
            expected_printed = (expected[3].lstrip("C"), expected[1])
            printed_identities = _xml_printed_identities(root)
            if not any(number.startswith("P") for number, _ in printed_identities):
                expected_printed = expected_identity
            source_identity = (meta.findtext("number", ""), meta.findtext("year", ""))
            verified_printed = {
                "IE-2017-act-14": (
                    {("12", "2017"), ("14", "2017")},
                    "CRIMINAL JUSTICE ACT 2017",
                    source_url,
                ),
                "IE-2022-act-38": (
                    {("38", "2022"), ("39", "2022")},
                    "Credit Guarantee (Amendment) Act 2022",
                    "https://www.irishstatutebook.ie/pdf/2022/en.act.2022.0038.pdf",
                ),
                "IE-2024-act-24": (
                    {("5", "2024"), ("24", "2024")},
                    "SOCIAL WELFARE (MISCELLANEOUS PROVISIONS) ACT 2024",
                    source_url,
                ),
            }.get(norm_id)
            corrected_printed_identity = (
                verified_printed
                and source_identity == expected_identity
                and printed_identities == verified_printed[0]
                and meta.findtext("title") == verified_printed[1]
            )
            if corrected_printed_identity:
                original_printed_numbers = ", ".join(
                    sorted((n for n, _ in printed_identities), key=int)
                )
                printed_identities = {expected_printed}
            if (printed_identities and printed_identities != {expected_printed}) or (
                source_identity != expected_identity and printed_identities != {expected_printed}
            ):
                raise ValueError(f"{norm_id}: ISB XML metadata identifies a different Act")
            title_el = meta.find("title")
            title = _inline_text(title_el) if title_el is not None else ""
            raw_date = meta.findtext("dateofenactment", "")
            published = _xml_enactment_date(root)
            source_fields = []
            if corrected_printed_identity:
                source_fields.extend(
                    (
                        ("identity_source_printed_numbers", original_printed_numbers),
                        (
                            "identity_correction_source",
                            verified_printed[2],
                        ),
                    )
                )
            if source_identity != expected_identity:
                source_fields.extend(
                    (
                        ("identity_source_number", source_identity[0]),
                        ("identity_source_year", source_identity[1]),
                        ("identity_basis", "isb_frontmatter_actnumber"),
                    )
                )
            for child in meta:
                if not isinstance(child.tag, str) or child.tag == "title":
                    continue
                key = {"number": "official_number", "dateofenactment": "enactment_date"}.get(
                    child.tag,
                    re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", child.tag).lower(),
                )
                value = (
                    published.isoformat()
                    if key == "enactment_date" and published is not None
                    else _inline_text(child)
                )
                if child.tag in ("number", "year"):
                    value = expected_identity[0 if child.tag == "number" else 1]
                source_fields.append((key, value))
            basis = "isb_enactment_date"
            if (
                published
                and re.fullmatch(r"\d{4}|\d{7,9}", raw_date)
                and raw_date != published.strftime("%Y%m%d")
            ):
                source_fields.append(("enactment_date_source_value", raw_date))
                basis = "isb_frontmatter_enactment_date"
            if correction := _xml_date_correction(root):
                source_fields.append(
                    (
                        "enactment_date_correction_source",
                        "https://www.irishstatutebook.ie" + correction[2],
                    )
                )
            extra = tuple(source_fields) + (("publication_date_basis", basis),)
        else:
            root = lxml_html.fromstring(data)
            title = (root.findtext(".//title") or "").strip()
            act = root.find('.//div[@id="act"]')
            if act is None:
                act = root.find('.//div[@id="si"]')
            if act is None:
                raise ValueError(f"{norm_id}: ISB HTML has no act")
            source_text = _html_text(act)
            published = (
                _instrument_date(source_text, title)
                if "-si-" in norm_id
                else _enactment_date(source_text)
            )
            extra = (
                ("official_number", norm_id.rsplit("-", 1)[1]),
                ("year", norm_id.split("-")[1]),
            )
            if re.match(r"I\.\s*R\.\s*Uimh\.", title):
                identity = re.search(r"(\d+)/(\d{4})", title)
                if not identity or norm_id != f"IE-{identity[2]}-si-{identity[1]}":
                    raise ValueError(f"{norm_id}: Irish source identifies a different instrument")
                extra += (("language", "ga"),)
                source_url = source_url.replace("/en/", "/ga/")
            if "-si-" in norm_id:
                identity = re.match(r"S\.\s*I\.\s*No\.\s*(\d+)/(\d{4})\b", title, re.I)
                if identity and norm_id != f"IE-{identity[2]}-si-{int(identity[1])}":
                    raise ValueError(f"{norm_id}: source identifies a different instrument")
                evidence = _instrument_date_evidence(title) if not _made_date(source_text) else None
                basis = "gazette_notice" if _gazette_date(source_text) else "final_signature"
                if evidence:
                    basis = "gazette_notice" if _gazette_date(source_text) else evidence[1]
                    extra += (("publication_date_source", evidence[2]),)
                    if evidence[3]:
                        extra += (("signature_date_source", evidence[2]),)
                    else:
                        extra += (("signature_date_unknown", "true"),)
                extra += (("publication_date_basis", basis),)
            elif published is not None:
                extra += (
                    ("enactment_date", published.isoformat()),
                    ("publication_date_basis", "isb_enactment_date"),
                )
            signature_dates = _signature_dates(source_text)
            if "-si-" in norm_id and not signature_dates and evidence:
                signature_dates = [date.fromisoformat(value) for value in evidence[3]]
            if signature_dates:
                extra += (("made_date", signature_dates[-1].isoformat()),)
                if len(signature_dates) > 1:
                    extra += (
                        ("signature_dates", json.dumps([d.isoformat() for d in signature_dates])),
                    )
        if not title or published is None:
            raise ValueError(f"{norm_id}: ISB source lacks its title or enactment date")
        return NormMetadata(
            title=title,
            short_title=title,
            identifier=norm_id,
            country="ie",
            rank=Rank("statutory_instrument" if "-si-" in norm_id else "act"),
            publication_date=published,
            status=NormStatus.IN_FORCE,
            department="",
            source=source_url,
            extra=extra,
        )


def _source_url(norm_id: str) -> str:
    match = re.fullmatch(r"IE-(\d{4})-(act|si)-([CP]?)(\d+)", norm_id)
    if match is None:
        raise ValueError(f"Invalid Irish norm identifier: {norm_id}")
    year, kind, prefix, number = match.groups()
    kind = {"C": "ca", "P": "prv"}.get(prefix, kind)
    expression = "made" if kind == "si" else "enacted"
    return f"https://www.irishstatutebook.ie/eli/{year}/{kind}/{number}/{expression}/en/html"


def _parse_date_str(value: str) -> date | None:
    """Parse ISO date string 'YYYY-MM-DD'."""
    if not value or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
