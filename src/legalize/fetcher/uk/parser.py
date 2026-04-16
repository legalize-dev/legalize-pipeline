"""CLML (Crown Legislation Markup Language) parser for legislation.gov.uk.

Input:
- MetadataParser receives ``/data.xml`` bytes and reads the ``<ukm:Metadata>``
  block plus the root element's attributes.
- TextParser receives either a single CLML XML blob (for one point-in-time
  snapshot) or the JSON blob produced by ``LegislationGovUkClient.get_suvestine``
  (for multi-version bootstrapping).

Output:
- NormMetadata with every field the source exposes, as required by
  ADDING_A_COUNTRY.md §0.3.
- A list of Blocks, one per ``<P1>`` section and one per ``<Schedule>``.
  Each Block has one Version per point-in-time snapshot the blob contained.
  Paragraphs inside a Version use css_class values that the generic
  Markdown renderer already knows about ("articulo", "h2", "h3", "list_item",
  "firma_rey", passthrough for unknown).

Design notes:

* CLML is deeply nested (``Part > Chapter > P1group > P1 > P2 > P3 > P4``).
  We flatten that into a sequence of sections where Part/Chapter headings
  ride on the first section that follows them — this matches how the
  generic renderer handles headings as plain paragraphs.
* XHTML tables (inside ``<Tabular>`` wrappers) are pre-rendered to Markdown
  pipe tables and emitted as a single opaque paragraph so the renderer's
  CSS map passes them through untouched.
* MathML is flattened to text between ``$…$`` delimiters. A proper LaTeX
  conversion is deferred to a follow-up; keeping the raw MathML content
  prevents silent data loss in the meantime.
* Images (``<Figure>`` / ``<Image>``) are dropped per project-wide policy
  and counted into ``extra.images_dropped``.
* Control characters (C0/C1) are stripped at the paragraph boundary to
  keep the output UTF-8-clean even if a stray byte slips in.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
from base64 import b64decode
from collections import Counter
from datetime import date
from typing import Any

from lxml import etree

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.fetcher.uk.client import NS, split_norm_id
from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    Rank,
    Reform,
    Version,
)

logger = logging.getLogger(__name__)

# ─── Jurisdictions and rank slugs ──────────────────────────────

# ``DocumentMainType@Value`` → (jurisdiction, rank slug).
# Jurisdiction follows the ELI-inspired convention: "uk" is the default,
# sub-jurisdictions carry an "uk-XX" tail. ``None`` keeps the state-level
# repo directory ("uk/").
TYPE_TO_JURISDICTION_RANK: dict[str, tuple[str | None, str]] = {
    "UnitedKingdomPublicGeneralAct": (None, "public-general-act"),
    "UnitedKingdomLocalAct": (None, "local-act"),
    "UnitedKingdomChurchMeasure": (None, "church-measure"),
    "UnitedKingdomChurchInstrument": (None, "church-instrument"),
    "ScottishAct": ("uk-sct", "act-of-scottish-parliament"),
    "ScottishOldAct": ("uk-sct", "act-of-scottish-parliament-old"),
    "WelshNationalAssemblyAct": ("uk-wls", "act-of-senedd-cymru"),
    "WelshParliamentAct": ("uk-wls", "act-of-senedd-cymru"),
    "WelshNationalAssemblyMeasure": ("uk-wls", "measure-of-senedd-cymru"),
    "NorthernIrelandAct": ("uk-nir", "act-of-northern-ireland-assembly"),
    "NorthernIrelandOldAct": ("uk-nir", "act-of-northern-ireland-assembly-old"),
    # Secondary legislation (phase 2 — carried here for completeness):
    "UnitedKingdomStatutoryInstrument": (None, "statutory-instrument"),
    "ScottishStatutoryInstrument": ("uk-sct", "scottish-statutory-instrument"),
    "WelshStatutoryInstrument": ("uk-wls", "welsh-statutory-instrument"),
    "NorthernIrelandStatutoryRule": ("uk-nir", "ni-statutory-rule"),
}

# Type-code fallback when DocumentMainType is missing (defensive — all real
# CLML carries it, but some historical PIT renderings drop the field).
TYPE_CODE_TO_JURISDICTION_RANK: dict[str, tuple[str | None, str]] = {
    "ukpga": (None, "public-general-act"),
    "ukla": (None, "local-act"),
    "ukppa": (None, "private-personal-act"),
    "ukcm": (None, "church-measure"),
    "asp": ("uk-sct", "act-of-scottish-parliament"),
    "asc": ("uk-wls", "act-of-senedd-cymru"),
    "anaw": ("uk-wls", "act-of-senedd-cymru"),
    "mwa": ("uk-wls", "measure-of-senedd-cymru"),
    "nia": ("uk-nir", "act-of-northern-ireland-assembly"),
}

# Strip C0 and C1 control characters. We do this at paragraph boundaries
# because CLML itself is clean, but non-breaking-space noise from copy-paste
# in tribunal transcripts has slipped in before.
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Collapses any whitespace run (including NBSPs and newlines) to a single
# space, used after pre-wrapping inline bold/italic.
_WS_RE = re.compile(r"\s+")


# ─── Encoding helpers ───────────────────────────────────────────


def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    # Replace U+00A0 (NBSP) with a regular space unless it's meaningful.
    # In UK legal text NBSPs appear between "s." and the section number;
    # collapsing them is fine for the Markdown output.
    text = text.replace("\u00a0", " ")
    text = _CTRL_RE.sub("", text)
    return _WS_RE.sub(" ", text).strip()


def _decode_maybe_gzipped(data: bytes) -> bytes:
    """Return decompressed bytes if ``data`` is a gzip stream, else as-is.

    Test fixtures are stored gzipped to keep the repo lean; the parser
    transparently handles both forms so call sites don't need to care.
    """
    if data[:2] == b"\x1f\x8b":
        return gzip.decompress(data)
    return data


# ─── Inline rendering ──────────────────────────────────────────


def _inline_text(element: etree._Element) -> str:
    """Flatten an inline CLML element to a string with Markdown markers.

    Handles Strong/Emphasis/Inferior/Superior/Citation/CitationSubRef/
    InternalLink/InlineAmendment/Substitution/Addition. MathML nodes are
    folded to ``$<flattened-text>$`` so the content survives even without
    a LaTeX converter in place.
    """
    parts: list[str] = []
    if element.text:
        parts.append(element.text)

    for child in element:
        localname = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
        ns = etree.QName(child.tag).namespace if isinstance(child.tag, str) else None

        if ns == NS["m"]:
            flat = "".join(child.itertext()).strip()
            flat = _WS_RE.sub(" ", flat)
            if flat:
                parts.append(f"${flat}$")
        elif localname in ("Strong",):
            inner = _inline_text(child).strip()
            if inner:
                parts.append(f"**{inner}**")
        elif localname in ("Emphasis", "Term"):
            inner = _inline_text(child).strip()
            if inner:
                parts.append(f"*{inner}*")
        elif localname == "Inferior":
            inner = _inline_text(child)
            parts.append(_unicode_subscript(inner))
        elif localname == "Superior":
            inner = _inline_text(child)
            parts.append(_unicode_superscript(inner))
        elif localname in ("Citation", "CitationSubRef", "InternalLink"):
            inner = _inline_text(child).strip()
            href = _citation_href(child)
            if inner and href:
                parts.append(f"[{inner}]({href})")
            elif inner:
                parts.append(inner)
        elif localname in ("InlineAmendment", "Quotation"):
            inner = _inline_text(child).strip()
            if inner:
                parts.append(f'"{inner}"')
        elif localname in ("Substitution", "Addition", "AppendText", "Repeal"):
            # Amendment provenance markers — render content inline; the
            # amendment history is captured in the reform timeline, not in
            # visual decoration.
            parts.append(_inline_text(child))
        elif localname in ("Figure", "Image"):
            parts.append("[image omitted]")
        else:
            parts.append(_inline_text(child))

        if child.tail:
            parts.append(child.tail)

    return "".join(parts)


def _citation_href(element: etree._Element) -> str | None:
    """Turn CLML citation attributes into a legislation.gov.uk URL."""
    for attr in ("URI", "DocumentURI", "IdURI", "href"):
        val = element.get(attr)
        if val:
            if val.startswith("http://www.legislation.gov.uk/id/"):
                return val.replace(
                    "http://www.legislation.gov.uk/id/",
                    "https://www.legislation.gov.uk/",
                    1,
                )
            if val.startswith("http://www.legislation.gov.uk/"):
                return val.replace(
                    "http://www.legislation.gov.uk/",
                    "https://www.legislation.gov.uk/",
                    1,
                )
            return val
    # Internal anchor: use the Ref attribute as a hash link.
    ref = element.get("Ref")
    if ref:
        return f"#{ref}"
    return None


_SUBSCRIPT = str.maketrans("0123456789+-=()n", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₙ")
_SUPERSCRIPT = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")


def _unicode_subscript(text: str) -> str:
    """Best-effort Unicode subscript for digits/operators; passthrough otherwise."""
    return text.translate(_SUBSCRIPT)


def _unicode_superscript(text: str) -> str:
    return text.translate(_SUPERSCRIPT)


# ─── Tables (XHTML inside CLML) ────────────────────────────────


def _xhtml_table_to_markdown(tabular: etree._Element) -> str:
    """Render a ``<Tabular>`` wrapper containing XHTML ``<tbody>`` to MD.

    Handles colspan / rowspan by repeating values. CLML wraps real HTML
    tables inside ``<Tabular>``; the inner ``<tbody>``/``<tr>``/``<td>``
    nodes live in the XHTML namespace.
    """
    # Collect rows — can be inside <thead>, <tbody>, or directly under <table>.
    rows: list[list[tuple[str, int, int]]] = []
    for tr in tabular.iter(f"{{{NS['xhtml']}}}tr"):
        cells: list[tuple[str, int, int]] = []
        for cell in tr:
            local = etree.QName(cell.tag).localname if isinstance(cell.tag, str) else ""
            if local not in ("td", "th"):
                continue
            text = _clean_text(_inline_text(cell)).replace("\n", " ").replace("|", "\\|")
            colspan = _int_attr(cell, "colspan", 1)
            rowspan = _int_attr(cell, "rowspan", 1)
            cells.append((text, colspan, rowspan))
        if cells:
            rows.append(cells)

    if not rows:
        return ""

    expanded: list[list[str]] = []
    pending: dict[int, tuple[str, int]] = {}
    for row in rows:
        out: list[str] = []
        col = 0
        idx = 0
        while idx < len(row) or col in pending:
            if col in pending:
                text, remaining = pending[col]
                out.append(text)
                if remaining > 1:
                    pending[col] = (text, remaining - 1)
                else:
                    del pending[col]
                col += 1
                continue
            text, colspan, rowspan = row[idx]
            for _ in range(colspan):
                out.append(text)
                if rowspan > 1:
                    pending[col] = (text, rowspan - 1)
                col += 1
            idx += 1
        expanded.append(out)

    max_cols = max(len(r) for r in expanded)
    for r in expanded:
        while len(r) < max_cols:
            r.append("")

    header = expanded[0]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in range(max_cols)) + " |",
    ]
    for r in expanded[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def _int_attr(element: etree._Element, name: str, default: int) -> int:
    val = element.get(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


# ─── Structural walk ────────────────────────────────────────────


class _BlockBuilder:
    """Accumulates paragraphs for a single Block across a CLML section."""

    def __init__(self, block_id: str, block_type: str, title: str) -> None:
        self.block_id = block_id
        self.block_type = block_type
        self.title = title
        self.paragraphs: list[Paragraph] = []
        self.images_dropped = 0

    def add(self, css_class: str, text: str) -> None:
        cleaned = _clean_text(text)
        if not cleaned:
            return
        self.paragraphs.append(Paragraph(css_class=css_class, text=cleaned))

    def add_pre(self, css_class: str, text: str) -> None:
        """Add a pre-formatted paragraph (tables, blockquotes) without collapsing whitespace."""
        if not text.strip():
            return
        self.paragraphs.append(Paragraph(css_class=css_class, text=text))


def _gather_section_blocks(
    root: etree._Element,
) -> list[tuple[str, str, str, list[Paragraph], int]]:
    """Walk a CLML root and emit (block_id, block_type, title, paragraphs, images_dropped).

    Each ``<P1>`` and each ``<Schedule>`` becomes one block. Enclosing
    Part/Chapter/P1group headings ride on the first block that follows
    them. Anything in ``<PrimaryPrelims>`` goes into a synthetic
    "preamble" block at index 0.
    """
    results: list[tuple[str, str, str, list[Paragraph], int]] = []

    # 1. Preamble / long title.
    prelims = root.find(".//leg:PrimaryPrelims", NS)
    if prelims is None:
        prelims = root.find(".//leg:SecondaryPrelims", NS)
    if prelims is not None:
        builder = _BlockBuilder(block_id="preamble", block_type="preamble", title="")
        long_title = prelims.find(".//leg:LongTitle", NS)
        if long_title is not None:
            for para in long_title.findall("leg:Para", NS):
                builder.add("parrafo", _inline_text(para))
        preamble = prelims.find(".//leg:Preamble", NS)
        if preamble is not None:
            for para in preamble.findall(".//leg:Para", NS):
                builder.add("parrafo", _inline_text(para))
        intro = prelims.find(".//leg:IntroductoryText", NS)
        if intro is not None:
            for child in intro:
                local = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
                if local == "Para":
                    builder.add("parrafo", _inline_text(child))
        if builder.paragraphs:
            results.append(
                (builder.block_id, builder.block_type, builder.title, builder.paragraphs, 0)
            )

    # 2. Body sections — walk with ancestor Part/Chapter headings rolled in.
    body = root.find(".//leg:Body", NS)
    if body is not None:
        results.extend(_walk_body_with_headings(body))

    # 3. Schedules.
    schedules = root.find(".//leg:Schedules", NS)
    if schedules is not None:
        for sched in schedules.findall("leg:Schedule", NS):
            block_id = sched.get("id") or "schedule"
            builder = _BlockBuilder(block_id=block_id, block_type="schedule", title="")
            _render_schedule(sched, builder)
            if builder.paragraphs:
                results.append(
                    (
                        builder.block_id,
                        builder.block_type,
                        builder.title,
                        builder.paragraphs,
                        builder.images_dropped,
                    )
                )

    return results


def _walk_body_with_headings(body: etree._Element):
    """Walk the body preserving Part/Chapter headings as leading paragraphs.

    Emits one tuple per ``<P1>``; headings accumulated from ancestor Parts
    that are new-to-this-block are prepended in hierarchy order.
    """
    out: list[tuple[str, str, str, list[Paragraph], int]] = []
    seen_headings: set[int] = set()

    for p1 in body.iter(f"{{{NS['leg']}}}P1"):
        # Collect ancestor Part / Chapter / P1group titles not yet emitted.
        pending: list[tuple[str, str]] = []
        for ancestor in reversed(list(p1.iterancestors())):
            local = etree.QName(ancestor.tag).localname if isinstance(ancestor.tag, str) else ""
            if local not in ("Part", "Chapter", "P1group", "Pblock", "Group"):
                continue
            ident = id(ancestor)
            if ident in seen_headings:
                continue
            seen_headings.add(ident)
            css = {"Part": "h2", "Chapter": "h3", "P1group": "h4", "Pblock": "h4", "Group": "h4"}[
                local
            ]
            text = _render_heading_text(ancestor)
            if text:
                pending.append((css, text))

        block_id = p1.get("id") or _synthesize_block_id(p1)
        builder = _BlockBuilder(block_id=block_id, block_type="section", title="")
        for css, text in pending:
            builder.add(css, text)
        _render_section(p1, builder)
        if builder.paragraphs:
            out.append(
                (
                    builder.block_id,
                    builder.block_type,
                    builder.title,
                    builder.paragraphs,
                    builder.images_dropped,
                )
            )
    return out


def _synthesize_block_id(p1: etree._Element) -> str:
    number = p1.find("leg:Pnumber", NS)
    if number is not None and number.text:
        return f"section-{_clean_text(number.text).replace(' ', '-')}"
    return "section"


def _render_heading_text(element: etree._Element) -> str:
    """Render the heading of a Part/Chapter/P1group element.

    Combines ``<Number>`` and ``<Title>`` if present; falls back to the
    first text-bearing child.
    """
    num = element.find("leg:Number", NS)
    title = element.find("leg:Title", NS)
    pieces: list[str] = []
    if num is not None:
        piece = _clean_text(_inline_text(num))
        if piece:
            pieces.append(piece)
    if title is not None:
        piece = _clean_text(_inline_text(title))
        if piece:
            pieces.append(piece)
    if pieces:
        return " — ".join(pieces)
    # Fall back: first <Text> descendant
    text = element.find(".//leg:Text", NS)
    if text is not None:
        return _clean_text(_inline_text(text))
    return ""


def _render_section(p1: etree._Element, builder: _BlockBuilder) -> None:
    """Emit paragraphs for a ``<P1>`` section into the builder."""
    # Section heading: number + optional title.
    num_el = p1.find("leg:Pnumber", NS)
    title_el = p1.find("leg:Title", NS)
    num = _clean_text(_inline_text(num_el)) if num_el is not None else ""
    title = _clean_text(_inline_text(title_el)) if title_el is not None else ""
    if num or title:
        heading = " ".join(piece for piece in (num, title) if piece)
        builder.add("articulo", heading)

    # Section body: <P1para> contains the statement text (and nested P2/P3/P4).
    body = p1.find("leg:P1para", NS)
    if body is not None:
        _render_p_body(body, builder, depth=0)
    else:
        # Some sections wrap content directly in <Text>.
        for text_el in p1.findall("leg:Text", NS):
            builder.add("parrafo", _inline_text(text_el))


def _render_p_body(parent: etree._Element, builder: _BlockBuilder, *, depth: int) -> None:
    """Recursively render CLML paragraph containers (P1para/P2para/P3para/P4para).

    The depth controls indentation for nested sub-paragraphs (P2, P3, P4).
    """
    for child in parent:
        local = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""

        if local == "Text":
            builder.add("parrafo", _inline_text(child))
        elif local == "Para":
            # <Para> wraps <Text>, sometimes lists.
            for sub in child:
                sub_local = etree.QName(sub.tag).localname if isinstance(sub.tag, str) else ""
                if sub_local == "Text":
                    builder.add("parrafo", _inline_text(sub))
                elif sub_local == "UnorderedList":
                    _render_list(sub, builder, ordered=False, depth=depth)
                elif sub_local == "OrderedList":
                    _render_list(sub, builder, ordered=True, depth=depth)
                elif sub_local == "Tabular":
                    _render_table(sub, builder)
                elif sub_local == "BlockAmendment":
                    _render_block_amendment(sub, builder, depth=depth)
                elif sub_local == "Formula":
                    builder.add("parrafo", _inline_text(sub))
        elif local in ("P2", "P3", "P4", "P5"):
            _render_sub_paragraph(child, builder, depth=depth + 1)
        elif local == "UnorderedList":
            _render_list(child, builder, ordered=False, depth=depth)
        elif local == "OrderedList":
            _render_list(child, builder, ordered=True, depth=depth)
        elif local == "Tabular":
            _render_table(child, builder)
        elif local == "BlockAmendment":
            _render_block_amendment(child, builder, depth=depth)
        elif local == "BlockText":
            for text_el in child.findall("leg:Text", NS):
                builder.add("parrafo", _inline_text(text_el))
        elif local == "Figure" or local == "Image":
            builder.images_dropped += 1
        elif local == "Commentary" or local == "CommentaryRef":
            # Editorial amendment notes — keep as a footnote-style line.
            text = _clean_text(_inline_text(child))
            if text:
                builder.add("parrafo", f"[^cm]: {text}")
        # Anything else (Subheading, Formula in deep positions, …) — flatten.
        else:
            text = _inline_text(child)
            if text.strip():
                builder.add("parrafo", _clean_text(text))


def _render_sub_paragraph(element: etree._Element, builder: _BlockBuilder, *, depth: int) -> None:
    """Render a ``<P2>``/``<P3>``/``<P4>`` with its number prefix."""
    num_el = element.find("leg:Pnumber", NS)
    num = _clean_text(_inline_text(num_el)) if num_el is not None else ""
    indent_prefix = "    " * max(depth - 1, 0)
    # Get the *para container child (P2para, P3para, etc.)
    inner = None
    for child in element:
        local = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
        if local.endswith("para") and local.startswith("P"):
            inner = child
            break

    first_text = ""
    if inner is not None:
        # Find the first <Text> at this level for the number+text line.
        text_el = inner.find("leg:Text", NS)
        if text_el is not None:
            first_text = _inline_text(text_el)

    if num and first_text:
        builder.add("list_item", f"{indent_prefix}- ({num}) {_clean_text(first_text)}")
    elif first_text:
        builder.add("list_item", f"{indent_prefix}- {_clean_text(first_text)}")
    elif num:
        builder.add("list_item", f"{indent_prefix}- ({num})")

    # Render the rest of the sub-paragraph body. The first <Text> child has
    # already been folded into the "- (N) …" line above, so skip it.
    if inner is not None:
        skipped = False
        for child in inner:
            local = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
            if local == "Text":
                if not skipped:
                    skipped = True
                    continue
                builder.add("parrafo", _inline_text(child))
                continue
            if local in ("P2", "P3", "P4", "P5"):
                _render_sub_paragraph(child, builder, depth=depth + 1)
            elif local == "UnorderedList":
                _render_list(child, builder, ordered=False, depth=depth)
            elif local == "OrderedList":
                _render_list(child, builder, ordered=True, depth=depth)
            elif local == "Tabular":
                _render_table(child, builder)
            elif local == "BlockAmendment":
                _render_block_amendment(child, builder, depth=depth)
            elif local in ("Figure", "Image"):
                builder.images_dropped += 1


def _render_list(
    element: etree._Element, builder: _BlockBuilder, *, ordered: bool, depth: int
) -> None:
    indent = "    " * depth
    for idx, item in enumerate(element.findall("leg:ListItem", NS), start=1):
        text = _clean_text(_inline_text(item))
        if not text:
            continue
        bullet = f"{idx}." if ordered else "-"
        builder.add("list_item", f"{indent}{bullet} {text}")


def _render_table(element: etree._Element, builder: _BlockBuilder) -> None:
    md = _xhtml_table_to_markdown(element)
    if md:
        builder.add_pre("table", md)


def _render_block_amendment(element: etree._Element, builder: _BlockBuilder, *, depth: int) -> None:
    """Render a ``<BlockAmendment>`` — a chunk of amending legislation.

    Walks the subtree in document order, emitting blockquoted lines for
    running text and separate pre-formatted paragraphs for tables. This
    preserves tables that amendments insert into other Acts (common in
    Finance Acts, which is where most of the formulas and tables live).
    """
    buffer: list[str] = []

    def flush_buffer() -> None:
        if buffer:
            builder.add_pre("quote", "\n".join(buffer))
            buffer.clear()

    for node in element.iter():
        localname = etree.QName(node.tag).localname if isinstance(node.tag, str) else ""
        if localname == "Tabular":
            flush_buffer()
            md = _xhtml_table_to_markdown(node)
            if md:
                builder.add_pre("table", md)
        elif localname == "Text":
            piece = _clean_text(_inline_text(node))
            if piece:
                buffer.append(f"> {piece}")
        elif localname in ("Figure", "Image"):
            builder.images_dropped += 1
    flush_buffer()


def _render_schedule(sched: etree._Element, builder: _BlockBuilder) -> None:
    """Render an entire Schedule as a block."""
    num_el = sched.find("leg:Number", NS)
    title_el = sched.find("leg:Title", NS)
    num = _clean_text(_inline_text(num_el)) if num_el is not None else ""
    title = _clean_text(_inline_text(title_el)) if title_el is not None else ""
    heading = " — ".join(piece for piece in (num, title) if piece) or "SCHEDULE"
    builder.add("h2", heading)

    body = sched.find("leg:ScheduleBody", NS)
    if body is None:
        return
    _render_p_body(body, builder, depth=0)


# ─── MetadataParser ────────────────────────────────────────────


class UKMetadataParser(MetadataParser):
    """Parse ``<ukm:Metadata>`` from a CLML document into NormMetadata."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        data = _decode_maybe_gzipped(data)
        # Multi-version blobs are produced by the client.get_suvestine path;
        # we pick the first (earliest) version's XML for metadata, since
        # static fields like title and rank don't change across versions.
        if data.lstrip().startswith(b"{"):
            blob = json.loads(data)
            versions = blob.get("versions") or []
            if not versions:
                raise ValueError(f"{norm_id}: suvestine blob has no versions")
            data = b64decode(versions[0]["xml_b64"])

        root = etree.fromstring(data)
        meta = root.find("ukm:Metadata", NS)
        if meta is None:
            raise ValueError(f"{norm_id}: missing <ukm:Metadata>")

        type_code, year, number = split_norm_id(norm_id)

        # DC / DCT bibliographic fields.
        title = _clean_text(_text_of(meta, "dc:title")) or f"{type_code} {year}/{number}"
        description = _text_of(meta, "dc:description") or ""
        language = _text_of(meta, "dc:language") or "en"
        publisher = _text_of(meta, "dc:publisher") or "The National Archives"
        modified_raw = _text_of(meta, "dc:modified")
        modified = _parse_iso_date(modified_raw) if modified_raw else None

        # UKM primary metadata.
        doc_type_el = meta.find(".//ukm:DocumentMainType", NS)
        doc_type = doc_type_el.get("Value") if doc_type_el is not None else None
        doc_category_el = meta.find(".//ukm:DocumentCategory", NS)
        doc_category = doc_category_el.get("Value") if doc_category_el is not None else ""
        doc_status_el = meta.find(".//ukm:DocumentStatus", NS)
        doc_status = doc_status_el.get("Value") if doc_status_el is not None else ""

        jurisdiction, rank_slug = TYPE_TO_JURISDICTION_RANK.get(
            doc_type or ""
        ) or TYPE_CODE_TO_JURISDICTION_RANK.get(type_code, (None, "act"))

        enactment_date_el = meta.find(".//ukm:EnactmentDate", NS)
        enactment_date_raw = (
            enactment_date_el.get("Date") if enactment_date_el is not None else None
        )
        publication_date = _parse_iso_date(enactment_date_raw) if enactment_date_raw else None
        # Fallback: root/@RestrictStartDate or dct:valid.
        if publication_date is None:
            valid = _text_of(meta, "dct:valid")
            if valid:
                publication_date = _parse_iso_date(valid)
        if publication_date is None:
            rsd = root.get("RestrictStartDate")
            if rsd:
                publication_date = _parse_iso_date(rsd)
        if publication_date is None:
            publication_date = date(year, 1, 1)  # conservative fallback

        # Status: In-force by default; mark repealed if every provision is.
        status = _infer_status(doc_status, root)

        # Correction slips — flatten to "Title (YYYY-MM-DD): URL; …".
        correction_slips: list[str] = []
        for slip in meta.findall(".//ukm:CorrectionSlip", NS):
            pieces = [
                slip.get("Title") or "Correction Slip",
                slip.get("Date") or "",
                slip.get("URI") or "",
            ]
            correction_slips.append(" | ".join(p for p in pieces if p))

        isbn_el = meta.find(".//ukm:ISBN", NS)
        isbn = isbn_el.get("Value") if isbn_el is not None else ""

        # Statistics block (paragraph counts) — handy for the web UI.
        stats = meta.find(".//ukm:Statistics", NS)
        stats_pairs: list[tuple[str, str]] = []
        if stats is not None:
            for field in (
                "TotalParagraphs",
                "BodyParagraphs",
                "ScheduleParagraphs",
                "AttachmentParagraphs",
                "TotalImages",
            ):
                el = stats.find(f"ukm:{field}", NS)
                if el is not None and el.get("Value"):
                    key = _camel_to_snake(field)
                    stats_pairs.append((f"stats_{key}", el.get("Value")))

        extra: list[tuple[str, str]] = []
        for key, value in (
            ("type_code", type_code),
            ("year", str(year)),
            ("number", str(number)),
            ("document_main_type", doc_type or ""),
            ("document_category", doc_category),
            ("document_status", doc_status),
            ("language", language),
            ("publisher", publisher),
            ("isbn", isbn),
            ("restrict_extent", root.get("RestrictExtent") or ""),
            ("restrict_start_date", root.get("RestrictStartDate") or ""),
            ("number_of_provisions", root.get("NumberOfProvisions") or ""),
        ):
            if value:
                extra.append((key, value[:500]))

        extra.extend(stats_pairs)

        if correction_slips:
            extra.append(("correction_slips", " ; ".join(correction_slips)[:2000]))

        # Subjects: TNA doesn't publish topic tags in CLML itself, but the
        # DocumentMainType Value is the one classification that matters.
        subjects: tuple[str, ...] = (doc_type,) if doc_type else ()

        return NormMetadata(
            title=title,
            short_title=title,
            identifier=norm_id,
            country="uk",
            rank=Rank(rank_slug),
            publication_date=publication_date,
            status=status,
            department=publisher,
            source=f"https://www.legislation.gov.uk/{type_code}/{year}/{number}",
            jurisdiction=jurisdiction,
            last_modified=modified,
            pdf_url=f"https://www.legislation.gov.uk/{type_code}/{year}/{number}/pdfs/{type_code}_{year:04d}{number:04d}_en.pdf",
            subjects=subjects,
            summary=_clean_text(description),
            extra=tuple(extra),
        )


# ─── TextParser ────────────────────────────────────────────────


class UKTextParser(TextParser):
    """Parse CLML text into Block/Version/Paragraph objects.

    Accepts either a single CLML XML (one snapshot) or the JSON blob
    produced by ``LegislationGovUkClient.get_suvestine`` (multi-version).
    """

    def parse_text(self, data: bytes) -> list[Block]:
        data = _decode_maybe_gzipped(data)
        if data.lstrip().startswith(b"{"):
            return _parse_multiversion(json.loads(data))
        return _parse_single_snapshot(data)

    def extract_reforms(self, data: bytes) -> list[Reform]:
        """Extract one Reform per distinct effective date in the blob.

        For single-snapshot XMLs this collapses to one Reform (the
        RestrictStartDate or EnactmentDate).
        """
        blocks = self.parse_text(data)
        from legalize.transformer.xml_parser import extract_reforms as _generic_extract

        return _generic_extract(blocks)


def _parse_single_snapshot(xml_bytes: bytes) -> list[Block]:
    """Parse one CLML XML into Blocks, each with a single Version."""
    root = etree.fromstring(xml_bytes)
    norm_id = _norm_id_from_root(root) or "uk"
    eff_date = _effective_date_from_root(root)
    entries = _gather_section_blocks(root)

    total_images_dropped = sum(img for *_, img in entries)
    if total_images_dropped:
        logger.debug("%s: dropped %d image(s)", norm_id, total_images_dropped)

    blocks: list[Block] = []
    for block_id, block_type, title, paragraphs, _ in entries:
        version = Version(
            norm_id=norm_id,
            publication_date=eff_date,
            effective_date=eff_date,
            paragraphs=tuple(paragraphs),
        )
        blocks.append(Block(id=block_id, block_type=block_type, title=title, versions=(version,)))
    return blocks


def _parse_multiversion(blob: dict[str, Any]) -> list[Block]:
    """Parse a suvestine blob (multi-version timeline) into Blocks.

    Each distinct block_id across the versions becomes one Block; the
    versions inside it are the per-effective-date snapshots.
    """
    versions_blob = blob.get("versions") or []
    if not versions_blob:
        return []

    # per-block-id → list[(eff_date, norm_id, paragraphs)]
    per_block: dict[str, list[tuple[date, str, tuple[Paragraph, ...], str, str]]] = {}
    block_order: list[str] = []
    block_metadata: dict[str, tuple[str, str]] = {}  # block_type, title

    for v in versions_blob:
        xml_bytes = b64decode(v["xml_b64"])
        try:
            root = etree.fromstring(xml_bytes)
        except etree.XMLSyntaxError as exc:
            logger.warning("Skipping unparseable version for %s: %s", blob.get("norm_id"), exc)
            continue
        eff_raw = v.get("effective_date")
        eff_date = _parse_iso_date(eff_raw) or _effective_date_from_root(root)
        affecting = v.get("affecting_uri") or ""
        # If no explicit affecting_uri (enacted commit), attribute the change
        # to the law itself — the generic extract_reforms groups by
        # (date, norm_id) so giving the law's own URI keeps the first
        # commit distinct from subsequent ones.
        source_norm = affecting or (_norm_id_from_root(root) or "")

        for block_id, block_type, title, paragraphs, _ in _gather_section_blocks(root):
            if block_id not in block_metadata:
                block_metadata[block_id] = (block_type, title)
                block_order.append(block_id)
            per_block.setdefault(block_id, []).append(
                (eff_date, source_norm, tuple(paragraphs), block_type, title)
            )

    blocks: list[Block] = []
    for block_id in block_order:
        versions: list[Version] = []
        seen_signatures: set[tuple[date, str]] = set()
        # De-duplicate: consecutive versions with identical paragraphs collapse.
        prev_paragraphs: tuple[Paragraph, ...] | None = None
        for eff_date, source_norm, paragraphs, _bt, _t in sorted(
            per_block[block_id], key=lambda t: t[0]
        ):
            if paragraphs == prev_paragraphs:
                continue
            key = (eff_date, source_norm)
            if key in seen_signatures:
                continue
            seen_signatures.add(key)
            versions.append(
                Version(
                    norm_id=source_norm,
                    publication_date=eff_date,
                    effective_date=eff_date,
                    paragraphs=paragraphs,
                )
            )
            prev_paragraphs = paragraphs
        block_type, title = block_metadata[block_id]
        blocks.append(
            Block(id=block_id, block_type=block_type, title=title, versions=tuple(versions))
        )

    return blocks


# ─── Small helpers ─────────────────────────────────────────────


def _text_of(parent: etree._Element, xpath: str) -> str:
    el = parent.find(xpath, NS)
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _effective_date_from_root(root: etree._Element) -> date:
    rsd = root.get("RestrictStartDate")
    parsed = _parse_iso_date(rsd)
    if parsed is not None:
        return parsed
    enact = root.find(".//ukm:EnactmentDate", NS)
    if enact is not None:
        parsed = _parse_iso_date(enact.get("Date"))
        if parsed is not None:
            return parsed
    # Last resort: dct:valid on metadata
    valid = root.find(".//dct:valid", NS)
    if valid is not None:
        parsed = _parse_iso_date(valid.text)
        if parsed is not None:
            return parsed
    return date.today()


def _norm_id_from_root(root: etree._Element) -> str | None:
    uri = root.get("DocumentURI") or root.get("IdURI") or ""
    m = re.search(r"/(?:id/)?([a-z]+)/(\d{4})/(\d+)", uri)
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2))}-{int(m.group(3))}"


def _infer_status(doc_status: str, root: etree._Element) -> NormStatus:
    """Best-effort status inference.

    CLML does not carry a single "repealed" flag; partial repeals are
    annotated on individual provisions. A Status attribute of "revoked"
    or "repealed" on the root is the strongest signal; otherwise we
    check whether every top-level Pblock/P1 carries a Status="repealed".
    """
    if doc_status in ("Revoked", "Repealed"):
        return NormStatus.REPEALED
    statuses = [p.get("Status", "") for p in root.iter(f"{{{NS['leg']}}}P1")]
    if statuses and all(s in ("repealed", "revoked") for s in statuses if s):
        repealed = sum(1 for s in statuses if s in ("repealed", "revoked"))
        if repealed and repealed == len(statuses):
            return NormStatus.REPEALED
        if repealed > len(statuses) * 0.5:
            return NormStatus.PARTIALLY_REPEALED
    return NormStatus.IN_FORCE


def _camel_to_snake(name: str) -> str:
    out: list[str] = []
    for ch in name:
        if ch.isupper() and out:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


# A Counter kept alive to make quick counts visible in tests if someone asks.
# Not used in normal operation, but useful when diagnosing fixture coverage.
_DEBUG_TAG_COUNTER: Counter[str] = Counter()
