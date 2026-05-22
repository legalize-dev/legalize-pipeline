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
    # Secondary legislation (Statutory Instruments):
    "UnitedKingdomStatutoryInstrument": (None, "statutory-instrument"),
    "ScottishStatutoryInstrument": ("uk-sct", "scottish-statutory-instrument"),
    "WelshStatutoryInstrument": ("uk-wls", "welsh-statutory-instrument"),
    "NorthernIrelandStatutoryRule": ("uk-nir", "ni-statutory-rule"),
    "NorthernIrelandStatutoryRuleOrOrder": ("uk-nir", "ni-statutory-rule-or-order"),
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
    # Secondary legislation type-code fallbacks:
    "uksi": (None, "statutory-instrument"),
    "ssi": ("uk-sct", "scottish-statutory-instrument"),
    "wsi": ("uk-wls", "welsh-statutory-instrument"),
    "nisr": ("uk-nir", "ni-statutory-rule"),
    "nisro": ("uk-nir", "ni-statutory-rule-or-order"),
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
            # CLML overloads <Inferior> for (a) real subscripts like CO₂
            # and (b) stylistic highlighting of entire table cells. Only
            # translate when the inner text is short AND made of digits /
            # operator glyphs — otherwise emit as plain text.
            inner = _inline_text(child)
            parts.append(_maybe_subscript(inner))
        elif localname == "Superior":
            inner = _inline_text(child)
            parts.append(_maybe_superscript(inner))
        elif localname in ("Citation", "CitationSubRef", "InternalLink"):
            inner = _inline_text(child).strip()
            href = _citation_href(child)
            if inner and href:
                parts.append(f"[{inner}]({href})")
            elif inner:
                parts.append(inner)
        elif localname == "InlineAmendment":
            # Amending text inline — do NOT wrap in quotes here. The
            # source almost always contains a nested <Quotation> or
            # curly quotes that carry the quoting semantics; double-
            # wrapping produced `"“…”"` artifacts in the review.
            parts.append(_inline_text(child))
        elif localname == "Quotation":
            inner = _inline_text(child).strip()
            if inner:
                # Only add straight quotes if the source did not already
                # use curly ones — otherwise the reader ends up with
                # `"“…”"`.
                if inner.startswith(("\u201c", "\u2018", '"')) and inner.endswith(
                    ("\u201d", "\u2019", '"')
                ):
                    parts.append(inner)
                else:
                    parts.append(f'"{inner}"')
        elif localname in ("Substitution", "Addition", "AppendText", "Repeal"):
            # Amendment provenance markers — render content inline; the
            # amendment history is captured in the reform timeline, not in
            # visual decoration.
            parts.append(_inline_text(child))
        elif localname == "FootnoteRef":
            # Emit a GitHub-style footnote marker so the body text links
            # back to the corresponding definition in the document-level
            # <Footnotes> block (rendered as `[^id]: …` by
            # ``_render_footnotes``). Without this branch the body would
            # silently drop the reference and leave the definitions
            # dangling at the end of the document.
            ref = child.get("Ref")
            if ref:
                parts.append(f"[^{ref}]")
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

# A real subscript (H₂O, CO₂, xⁿ) is 1-3 chars drawn from digits, basic
# operators, parentheses, and the letter n. Anything else is likely
# stylistic highlighting and must be passed through plain — CLML reuses
# <Inferior>/<Superior> for visual emphasis in tax tables (Finance Act
# 2020), not just for scientific notation.
_SUB_SUP_ELIGIBLE = frozenset("0123456789+-=()n ")


def _eligible_for_translation(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 3:
        return False
    return all(ch in _SUB_SUP_ELIGIBLE for ch in stripped)


def _maybe_subscript(text: str) -> str:
    """Best-effort Unicode subscript for short digit/operator runs; plain otherwise."""
    if _eligible_for_translation(text):
        return text.translate(_SUBSCRIPT)
    return text


def _maybe_superscript(text: str) -> str:
    if _eligible_for_translation(text):
        return text.translate(_SUPERSCRIPT)
    return text


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
        # SI prelim dates: MadeDate / LaidDate / ComingIntoForce. Primary
        # legislation has no equivalents, so this loop is a no-op for ukpga.
        for date_tag in ("MadeDate", "LaidDate", "ComingIntoForce"):
            for el in prelims.findall(f"leg:{date_tag}", NS):
                _emit_si_date_paragraph(el, builder)
        preamble = prelims.find(".//leg:Preamble", NS)
        if preamble is not None:
            for para in preamble.findall(".//leg:Para", NS):
                builder.add("parrafo", _inline_text(para))
        # SIs use <SecondaryPreamble> wrapping <EnactingText> / <Resolution>
        # rather than the primary-legislation <Preamble> element. Without
        # this lookup, SI preambles silently disappear from the rendered MD.
        sec_preamble = prelims.find(".//leg:SecondaryPreamble", NS)
        if sec_preamble is not None:
            for para in sec_preamble.findall(".//leg:Para", NS):
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

    # 2. Body sections — walk in document order, emitting Part/Chapter
    # headings as their own single-paragraph blocks exactly once.
    body = root.find(".//leg:Body", NS)
    if body is not None:
        _walk_recursive(body, results)

    # 3. Schedules — each Schedule gets its own heading block, then its
    # internal Part/Chapter/P1 structure is walked with the same recursion
    # as the main body so sub-Parts get their own headings and sub-sections
    # are individual blocks.
    schedules = root.find(".//leg:Schedules", NS)
    if schedules is not None:
        for sched in schedules.findall("leg:Schedule", NS):
            sched_heading = _schedule_heading_paragraph(sched)
            if sched_heading is not None:
                results.append(
                    (
                        sched.get("id") or f"schedule-{sched.sourceline or 0}",
                        "schedule-heading",
                        "",
                        [sched_heading],
                        0,
                    )
                )
            sched_body = sched.find("leg:ScheduleBody", NS)
            if sched_body is not None:
                _walk_recursive(sched_body, results)
            # Schedules sometimes put their introductory <Para> outside P1s.
            intro_paras = _schedule_introductory_paragraphs(sched_body)
            if intro_paras:
                results.insert(
                    -1 if sched_body is not None else len(results),
                    (
                        (sched.get("id") or "schedule") + "-intro",
                        "schedule-intro",
                        "",
                        intro_paras,
                        0,
                    ),
                )

    # 4. Signed section — SIs end with one or more Signatory blocks
    # ("Made by the Secretary of State for X on Y"). Sits inside <Body>
    # for SIs, but the body walker doesn't know its shape, so render it
    # separately. No-op for primary legislation (Acts don't use this).
    signed_block = _render_signed_section(root)
    if signed_block is not None:
        results.append(signed_block)

    # 5. Commentaries — editorial notes attached to provisions. Render as a
    # footnote block at the end of the document so the text has context but
    # the main body stays clean.
    commentaries_block = _render_commentaries(root)
    if commentaries_block is not None:
        results.append(commentaries_block)

    # 6. Explanatory notes — SI prose appended after the operative
    # provisions ("(This note is not part of the Regulations)"). Sibling
    # of <Body> inside <Secondary>; missed by the body walker. No-op for
    # primary legislation.
    notes_block = _render_explanatory_notes(root)
    if notes_block is not None:
        results.append(notes_block)

    # 7. Footnotes — document-level citation references. Both primary
    # and secondary legislation put them in a top-level <Footnotes>
    # sibling of <Primary>/<Secondary>. Without this block the
    # <FootnoteRef> markers in the body have nothing to resolve to.
    footnotes_block = _render_footnotes(root)
    if footnotes_block is not None:
        results.append(footnotes_block)

    return results


def _emit_si_date_paragraph(date_el: etree._Element, builder: _BlockBuilder) -> None:
    """Render an SI prelim date element (MadeDate / LaidDate / ComingIntoForce).

    Two shapes occur:

    * ``<X><Text>Label</Text><DateText>2nd Jan 2024</DateText></X>`` —
      label plus formatted date.
    * ``<X><Text>Coming into force in accordance with…</Text></X>`` —
      conditional commencement, no DateText. The Text *is* the value.
    """
    label_el = date_el.find("leg:Text", NS)
    date_text_el = date_el.find("leg:DateText", NS)
    label = _clean_text(label_el.text) if label_el is not None and label_el.text else ""
    date_text = (
        _clean_text(date_text_el.text) if date_text_el is not None and date_text_el.text else ""
    )
    if label and date_text:
        builder.add("parrafo", f"{label}: {date_text}")
    elif label:
        builder.add("parrafo", label)


def _schedule_heading_paragraph(sched: etree._Element) -> Paragraph | None:
    """Render the schedule heading from either flat or TitleBlock layout.

    Newer CLML nests Number/Title under ``<TitleBlock>`` (uksi-2013-488
    is the canonical case — ``<Schedule><TitleBlock><Title>Designated
    Bodies</Title></TitleBlock>…``). Older documents put Number/Title
    directly on the Schedule. Check both so the schedule subtitle is
    never silently dropped.
    """
    num_el = sched.find("leg:Number", NS)
    title_el = sched.find("leg:Title", NS)
    title_block = sched.find("leg:TitleBlock", NS)
    if title_block is not None:
        if num_el is None:
            num_el = title_block.find("leg:Number", NS)
        if title_el is None:
            title_el = title_block.find("leg:Title", NS)
    num = _clean_text(_inline_text(num_el)) if num_el is not None else ""
    title = _clean_text(_inline_text(title_el)) if title_el is not None else ""
    text = " — ".join(p for p in (num, title) if p)
    if not text:
        text = "SCHEDULE"
    return Paragraph(css_class="h2", text=text)


def _schedule_introductory_paragraphs(
    sched_body: etree._Element | None,
) -> list[Paragraph]:
    """Schedule prose that sits outside any P1/Part (typical pattern)."""
    if sched_body is None:
        return []
    out: list[Paragraph] = []
    for para in sched_body.findall("leg:IntroductoryText/leg:Para", NS):
        text = _clean_text(_inline_text(para))
        if text:
            out.append(Paragraph(css_class="parrafo", text=text))
    return out


def _render_commentaries(
    root: etree._Element,
) -> tuple[str, str, str, list[Paragraph], int] | None:
    """Render the ``<Commentaries>`` block as footnote-style paragraphs."""
    comm_root = root.find(".//leg:Commentaries", NS)
    if comm_root is None:
        return None
    paragraphs: list[Paragraph] = []
    for commentary in comm_root.findall("leg:Commentary", NS):
        comm_id = commentary.get("id") or ""
        body_pieces: list[str] = []
        for text_el in commentary.iter(f"{{{NS['leg']}}}Text"):
            piece = _clean_text(_inline_text(text_el))
            if piece:
                body_pieces.append(piece)
        body = " ".join(body_pieces)
        if not body:
            continue
        paragraphs.append(Paragraph(css_class="parrafo", text=f"[^{comm_id}]: {body}"))
    if not paragraphs:
        return None
    # Heading ahead of the footnotes.
    heading = Paragraph(css_class="h2", text="Editorial notes")
    return ("commentaries", "commentaries", "", [heading, *paragraphs], 0)


def _render_signed_section(
    root: etree._Element,
) -> tuple[str, str, str, list[Paragraph], int] | None:
    """Render the ``<SignedSection>`` of an SI as a free-standing block.

    SIs end with one or more ``<Signatory>`` entries naming who made the
    instrument (Minister, Lord Commissioner, …) and when. Each Signatory
    optionally carries a lead-in ``<Para>`` (e.g., "We consent,") plus
    one or more ``<Signee>`` records with PersonName / JobTitle /
    Department / DateSigned. Without this rendering, the legal
    provenance is silently dropped — the body walker doesn't recognise
    the SignedSection shape and produces no output from it.
    """
    signed = root.find(".//leg:SignedSection", NS)
    if signed is None:
        return None
    paragraphs: list[Paragraph] = []
    for sig in signed.findall("leg:Signatory", NS):
        for para in sig.findall("leg:Para", NS):
            text = _clean_text(_inline_text(para))
            if text:
                paragraphs.append(Paragraph(css_class="parrafo", text=text))
        for signee in sig.findall("leg:Signee", NS):
            pieces: list[str] = []
            for tag in ("PersonName", "JobTitle", "Department"):
                for el in signee.findall(f"leg:{tag}", NS):
                    text = _clean_text(_inline_text(el))
                    if text:
                        pieces.append(text)
            date_el = signee.find("leg:DateSigned", NS)
            if date_el is not None:
                date_text_el = date_el.find("leg:DateText", NS)
                if date_text_el is not None and date_text_el.text:
                    pieces.append(_clean_text(date_text_el.text))
                else:
                    # Attribute-only form: <DateSigned Date="2012-03-26"/>.
                    # Fall back to the ISO date so the signature stamp
                    # isn't silently dropped.
                    date_attr = date_el.get("Date")
                    if date_attr:
                        pieces.append(date_attr)
            if pieces:
                paragraphs.append(Paragraph(css_class="parrafo", text=" — ".join(pieces)))
    if not paragraphs:
        return None
    heading = Paragraph(css_class="h2", text="Signed")
    return ("signed-section", "signatory", "", [heading, *paragraphs], 0)


def _render_explanatory_notes(
    root: etree._Element,
) -> tuple[str, str, str, list[Paragraph], int] | None:
    """Render the ``<ExplanatoryNotes>`` element of an SI as a block.

    SIs publish a plain-English summary of what the regulations do,
    prefixed by the disclaimer "(This note is not part of the
    Regulations)" inside a ``<Comment>`` element. The notes sit as a
    sibling of ``<Body>`` inside ``<Secondary>`` so the body walker
    never sees them. Capture the comment + the substantive body of the
    notes (``<P>`` / ``<P2>`` children) as a dedicated block so the
    editorial summary survives in the rendered Markdown.
    """
    notes = root.find(".//leg:ExplanatoryNotes", NS)
    if notes is None:
        return None
    builder = _BlockBuilder(block_id="explanatory-notes", block_type="explanatory-notes", title="")
    # Disclaimer comment(s) first so the "(not part of the Regulations)"
    # warning lands at the top of the rendered note.
    for comment in notes.findall("leg:Comment", NS):
        for para in comment.findall("leg:Para", NS):
            text = _clean_text(_inline_text(para))
            if text:
                builder.add("parrafo", text)
    for child in notes:
        local = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
        if not local or local == "Comment":
            continue
        if local == "P":
            _render_plain_paragraph(child, builder)
        elif local in ("P1", "P2", "P3", "P4", "P5"):
            _render_inline_child(child, builder, depth=0)
        else:
            text = _clean_text(_inline_text(child))
            if text:
                builder.add("parrafo", text)
    if not builder.paragraphs:
        return None
    heading = Paragraph(css_class="h2", text="Explanatory note")
    return (
        "explanatory-notes",
        "explanatory-notes",
        "",
        [heading, *builder.paragraphs],
        builder.images_dropped,
    )


def _render_footnotes(
    root: etree._Element,
) -> tuple[str, str, str, list[Paragraph], int] | None:
    """Render the document-level ``<Footnotes>`` as a footnote block.

    Both primary legislation and SIs put citation references in a
    top-level ``<Footnotes>`` sibling of ``<Primary>`` / ``<Secondary>``.
    Each ``<Footnote id="…">`` holds a ``<FootnoteText>`` with one or
    more ``<Para><Text>`` entries. Rendered as GitHub-style footnote
    definitions (``[^id]: text``) so MD renderers can link them back
    to the ``<FootnoteRef Ref="…">`` markers in the body.
    """
    fns = root.find(".//leg:Footnotes", NS)
    if fns is None:
        return None
    paragraphs: list[Paragraph] = []
    for fn in fns.findall("leg:Footnote", NS):
        fn_id = fn.get("id") or ""
        body_pieces: list[str] = []
        for text_el in fn.iter(f"{{{NS['leg']}}}Text"):
            piece = _clean_text(_inline_text(text_el))
            if piece:
                body_pieces.append(piece)
        body = " ".join(body_pieces)
        if not body:
            continue
        paragraphs.append(Paragraph(css_class="parrafo", text=f"[^{fn_id}]: {body}"))
    if not paragraphs:
        return None
    heading = Paragraph(css_class="h2", text="Footnotes")
    return ("footnotes", "footnotes", "", [heading, *paragraphs], 0)


_HEADING_CSS = {
    "Part": "h2",
    "Chapter": "h3",
    "Pblock": "h3",
    "P1group": "h4",
    "Group": "h4",
}

# Containers we MUST NOT descend into when walking structure: their contents
# belong to an amending block already rendered by the parent section.
_AMENDMENT_CONTAINERS = frozenset(
    {"BlockAmendment", "InlineAmendment", "Substitution", "Addition", "Repeal", "AppendText"}
)

# Trailing-connector punctuation suppressed inside <AppendText>. ASCII forms
# (`. , ; : ( ) -`) plus typographic dashes / ellipsis / brackets that
# legislation.gov.uk uses around amendment quotations. Curly quotes are
# excluded — they wrap quoted prose worth keeping.
_APPEND_TEXT_PUNCT = frozenset(".,;:()-—–…[]{}")


def _has_sectional_content(element: etree._Element) -> bool:
    """True when an element contains nested section/prose content.

    CLML occasionally uses ``<Tabular>`` or ``<Form>`` as layout
    containers wrapping sectional content (``<P1>``) or stand-alone
    prose paragraphs (``<P>``). When that's the case the container
    is not really a table or form template; descending preserves
    the inner sections instead of collapsing them into a single
    flattened block.
    """
    return element.find(".//leg:P1", NS) is not None or element.find(".//leg:P", NS) is not None


def _stable_block_id_for(element: etree._Element, kind: str, *, text: str | None = None) -> str:
    """Build a fallback block id that stays stable across multi-version snapshots.

    Multi-version SIs replay the same structural element across many
    point-in-time XMLs. A fallback id derived from ``sourceline`` drifts
    when the surrounding markup shifts, so the same logical element ends
    up under different block ids and the version timeline splinters.

    Use the nearest ancestor's ``id`` attribute plus this element's
    position among same-named siblings — both invariant across versions
    when the structure itself doesn't change. A text-derived suffix
    disambiguates anonymous headings that share a parent.
    """
    parent = element.getparent()
    anchor = ""
    while parent is not None:
        pid = parent.get("id") if isinstance(parent.tag, str) else None
        if pid:
            anchor = pid
            break
        parent = parent.getparent()
    direct = element.getparent()
    idx = 1
    if direct is not None:
        local = etree.QName(element.tag).localname
        siblings = [
            c for c in direct if isinstance(c.tag, str) and etree.QName(c.tag).localname == local
        ]
        if element in siblings:
            idx = siblings.index(element) + 1
    suffix = ""
    if text:
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]
        if slug:
            suffix = f"-{slug}"
    prefix = anchor or "root"
    return f"{prefix}-{kind}-{idx}{suffix}"


def _render_form(form: etree._Element, block_id: str) -> _BlockBuilder:
    """Render a ``<Form>`` template (standalone schedule attachment).

    Forms appear in procedural SIs (court rules, regulatory templates)
    as figure-backed standalone pages: a Number heading, one or more
    Title lines wrapped in a TitleBlock, an optional Reference to the
    rule they accompany, and a Figure with the printed-form image.
    Without explicit handling they fell through ``_walk_recursive``'s
    descend path and emitted nothing — nisro-1968-218's 21 forms
    disappeared on the first bootstrap attempt.
    """
    number_el = form.find("leg:Number", NS)
    number_text = _clean_text(_inline_text(number_el)) if number_el is not None else ""
    builder = _BlockBuilder(block_id=block_id, block_type="form", title=number_text)
    if number_text:
        builder.add("h3", number_text)
    title_block = form.find("leg:TitleBlock", NS)
    if title_block is not None:
        for title_el in title_block.findall("leg:Title", NS):
            piece = _clean_text(_inline_text(title_el))
            if piece:
                builder.add("h4", piece)
    direct_title = form.find("leg:Title", NS)
    if direct_title is not None and title_block is None:
        piece = _clean_text(_inline_text(direct_title))
        if piece:
            builder.add("h4", piece)
    reference_el = form.find("leg:Reference", NS)
    if reference_el is not None:
        piece = _clean_text(_inline_text(reference_el))
        if piece:
            builder.add("parrafo", piece)
    for child in form:
        if not isinstance(child.tag, str):
            continue
        local = etree.QName(child.tag).localname
        if local in ("Number", "TitleBlock", "Title", "Reference"):
            continue
        if local == "Figure":
            builder.images_dropped += 1
            continue
        if local == "P":
            _render_plain_paragraph(child, builder)
        else:
            _render_inline_child(child, builder, depth=0)
    return builder


def _walk_recursive(
    element: etree._Element,
    out: list[tuple[str, str, str, list[Paragraph], int]],
) -> None:
    """Depth-first walk of body/schedule contents.

    Each ``<Part>``/``<Chapter>``/``<P1group>``/``<Pblock>`` emits a single
    heading block the first time it's encountered (by virtue of the document
    walk hitting it exactly once). ``<P1>`` nodes become section blocks.
    ``BlockAmendment`` and friends are skipped — their content is already
    handled by the enclosing ``<P1>`` renderer, and emitting their nested
    ``<P1>`` would duplicate text.
    """
    for child in element:
        local = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
        if not local:
            continue
        if local in _AMENDMENT_CONTAINERS:
            # Do not descend — parent section already quoted this.
            continue
        if local in _HEADING_CSS:
            text = _render_heading_text(child)
            if text:
                heading_id = child.get("id") or _stable_block_id_for(
                    child, f"heading-{local.lower()}", text=text
                )
                css = _HEADING_CSS[local]
                out.append(
                    (
                        heading_id,
                        "heading",
                        "",
                        [Paragraph(css_class=css, text=text)],
                        0,
                    )
                )
            _walk_recursive(child, out)
        elif local == "P1":
            block_id = child.get("id") or _synthesize_block_id(child)
            builder = _BlockBuilder(block_id=block_id, block_type="section", title="")
            _render_section(child, builder)
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
        elif local == "P":
            # Unnumbered paragraph inside a grouping container (usually a
            # P1group with an empty Title — common in schedule-nested
            # Protocols of the Human Rights Act). Emit the body text as a
            # standalone prose block so it lands in the Markdown output.
            block_id = child.get("id") or _stable_block_id_for(child, "p")
            builder = _BlockBuilder(block_id=block_id, block_type="prose", title="")
            _render_plain_paragraph(child, builder)
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
        elif local == "Tabular":
            # Bare table inside a ScheduleBody (or other container) that
            # carries no enclosing <P1>. Uksi-2013-488 has 20 such tables;
            # without this branch _walk_recursive's else clause descended
            # into the table looking for sections, found none, and the
            # table never reached _render_table.
            #
            # Exception: CLML occasionally uses ``<Tabular>`` as a layout
            # container for nested ``<P1>`` sections (uksi-2005-250 has
            # 593 such sections inside one Tabular). When the table
            # contains sectional content, fall through to the recursive
            # walk so the inner sections still emit.
            if _has_sectional_content(child):
                _walk_recursive(child, out)
            else:
                block_id = child.get("id") or _stable_block_id_for(child, "table")
                builder = _BlockBuilder(block_id=block_id, block_type="schedule-table", title="")
                _render_table(child, builder)
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
        elif local == "Form":
            # Standalone form template inside a ScheduleBody (typically a
            # judicial-procedure form attached to a procedural SI).
            # Nisro-1968-218 carries 21 such forms — without this branch
            # they fell through to the else descend, which had nothing
            # to do with their Number/Title/Reference/Figure children
            # so the forms disappeared entirely.
            #
            # Same caveat as Tabular: if a Form wraps sectional content
            # (rare but possible for form templates with embedded
            # regulations), descend instead of collapsing.
            if _has_sectional_content(child):
                _walk_recursive(child, out)
            else:
                block_id = child.get("id") or _stable_block_id_for(child, "form")
                builder = _render_form(child, block_id)
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
        else:
            # Anonymous wrapper (Body, Primary, Secondary, Tabular container…) — descend.
            _walk_recursive(child, out)


def _render_plain_paragraph(p_el: etree._Element, builder: _BlockBuilder) -> None:
    """Render a body-level ``<P>`` element.

    Three shapes occur in practice:

    1. **Prose paragraph** — ``<P><Text>…</Text></P>``. Common in
       schedule narrative (HRA Protocols nested in schedule containers
       are the canonical case). Render the direct ``<Text>`` children
       as ``parrafo`` paragraphs.
    2. **Section-like envelope** — ``<P><P2>…</P2>+</P>`` or
       ``<P><BlockAmendment>…</BlockAmendment><AppendText>.</AppendText></P>``.
       Common in SI bodies that omit the ``<P1>`` envelope around
       regulations (fee amendments like uksi-1996-690, House of Commons
       resolutions like uksi-2012-1866, single-purpose block-amender
       SIs). The ``<P>`` itself carries no own prose; its children are
       the substantive content.
    3. **Mixed lead-in + envelope** —
       ``<P><Text>lead-in</Text><P2>…</P2><P2>…</P2></P>``. Common in
       SI explanatory notes whose first sentence introduces the fee
       table that follows (uksi-1996-690 is the canonical case).

    Decide structurally per-``<P>``: if any non-``<Text>`` content
    child is present (``P{N}``, ``P{N}group``, ``BlockAmendment``,
    ``Tabular``, ``Formula``, list, ``BlockText``, …), walk all
    children in document order via the same inline renderer used
    inside ``<P1para>``. Otherwise emit only ``<Text>`` children.

    The structural decision is local to this element — it must not
    consult ``builder.paragraphs`` because the builder is shared across
    every sibling ``<P>`` in containers like ``<ExplanatoryNotes>``.
    """
    has_structural = False
    for child in p_el:
        if not isinstance(child.tag, str):
            continue
        local = etree.QName(child.tag).localname
        if local not in ("Text", "Pnumber"):
            has_structural = True
            break
    if has_structural:
        for child in p_el:
            _render_inline_child(child, builder, depth=0)
        return
    for text_el in p_el.findall("leg:Text", NS):
        piece = _clean_text(_inline_text(text_el))
        if piece:
            builder.add("parrafo", piece)


def _synthesize_block_id(p1: etree._Element) -> str:
    number = p1.find("leg:Pnumber", NS)
    if number is not None and number.text:
        return f"section-{_clean_text(number.text).replace(' ', '-')}"
    return "section"


def _render_heading_text(element: etree._Element) -> str:
    """Render the heading of a Part/Chapter/Pblock/P1group element as plain text.

    Headings must be inline-markdown-free: embedded ``<Strong>`` or
    ``<Emphasis>`` would bleed ``**...**`` / ``*...*`` into the heading,
    and ``<Substitution>`` / amendment markers would add braces the
    reader has no context for. We therefore flatten via ``itertext``
    rather than ``_inline_text``.
    """
    num = element.find("leg:Number", NS)
    title = element.find("leg:Title", NS)
    pieces: list[str] = []
    if num is not None:
        piece = _clean_text("".join(num.itertext()))
        if piece:
            pieces.append(piece)
    if title is not None:
        piece = _clean_text("".join(title.itertext()))
        if piece:
            pieces.append(piece)
    if pieces:
        return " — ".join(pieces)
    # No explicit heading — the grouping is anonymous (empty <Title/>).
    # Returning "" signals the caller to skip emitting a heading block;
    # the body text (usually a <P><Text>…) is picked up by the normal
    # body walk instead.
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
    """Render a P{N}para container's children.

    All the real work lives in ``_render_inline_child`` so Formulas,
    BlockAmendments, lists and nested P{N} sub-paragraphs are handled the
    same way at every depth.
    """
    for child in parent:
        _render_inline_child(child, builder, depth=depth)


def _render_sub_paragraph(element: etree._Element, builder: _BlockBuilder, *, depth: int) -> None:
    """Render a ``<P2>``/``<P3>``/``<P4>`` with its number prefix.

    Walks **all** children of the P{N} element (Pnumber, P{N}para, Formula,
    nested P2/P3) in document order so that ``<Formula>`` siblings of
    ``<P2para>`` — used in Finance Acts to insert tax equations between
    narrative paragraphs — are not dropped. Likewise a P{N} element can
    have multiple P{N}para children (quite common after repeals), and we
    process each in order instead of stopping at the first one.
    """
    num_el = element.find("leg:Pnumber", NS)
    num = _clean_text(_inline_text(num_el)) if num_el is not None else ""
    indent_prefix = "    " * max(depth - 1, 0)

    # Find the first <Text> at the head of the first *para so the opening
    # bullet can carry the "(N) body" shape readers expect.
    first_para = None
    for child in element:
        local = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
        if local and local.startswith("P") and local.endswith("para"):
            first_para = child
            break

    first_text = ""
    first_text_el = None
    if first_para is not None:
        first_text_el = first_para.find("leg:Text", NS)
        if first_text_el is not None:
            first_text = _inline_text(first_text_el)

    if num and first_text:
        builder.add("list_item", f"{indent_prefix}- ({num}) {_clean_text(first_text)}")
    elif first_text:
        builder.add("list_item", f"{indent_prefix}- {_clean_text(first_text)}")
    elif num:
        builder.add("list_item", f"{indent_prefix}- ({num})")

    # Walk the rest of the P{N} in document order: every *para, Formula,
    # BlockAmendment, Table at this level becomes its own rendered piece.
    first_text_used = first_text_el is not None
    for child in element:
        local = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
        if not local or local == "Pnumber":
            continue
        if local and local.startswith("P") and local.endswith("para"):
            # Skip only the single <Text> already consumed for the header.
            for sub in child:
                slocal = etree.QName(sub.tag).localname if isinstance(sub.tag, str) else ""
                if slocal == "Text" and first_text_used and sub is first_text_el:
                    first_text_used = False
                    continue
                _render_inline_child(sub, builder, depth=depth)
        else:
            _render_inline_child(child, builder, depth=depth)


def _render_inline_child(child: etree._Element, builder: _BlockBuilder, *, depth: int) -> None:
    """Render one content-bearing child of a P{N} or P{N}para.

    Shared by ``_render_sub_paragraph`` and ``_render_p_body`` so that the
    same tag coverage — including Formula — applies at every depth.
    """
    local = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
    if not local:
        return
    if local == "Text":
        piece = _inline_text(child)
        if _clean_text(piece):
            builder.add("parrafo", piece)
    elif local == "Formula":
        piece = _clean_text(_inline_text(child))
        if piece:
            # Wrap in $ … $ so Markdown math renderers pick it up; the
            # fallback still reads naturally as plain text.
            if not (piece.startswith("$") and piece.endswith("$")):
                piece = f"${piece}$"
            builder.add("parrafo", piece)
    elif local in ("P2", "P3", "P4", "P5"):
        _render_sub_paragraph(child, builder, depth=depth + 1)
    elif local == "Para":
        # Plain <Para> wrapper — treat its children as inline content.
        for sub in child:
            _render_inline_child(sub, builder, depth=depth)
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
    elif local in ("Figure", "Image"):
        if local == "Figure":
            builder.images_dropped += 1
    elif local in ("Commentary", "CommentaryRef"):
        piece = _clean_text(_inline_text(child))
        if piece:
            builder.add("parrafo", f"[^cm]: {piece}")
    elif local == "AppendText":
        # Trailing connector that finishes the sentence after a sibling
        # <BlockAmendment>/<Substitution>. Typically just "." or ",".
        # Emit only when it carries substantive prose, not when it's
        # pure punctuation — the amendment quote already captures the
        # substance and a "." paragraph after it reads as noise.
        piece = _clean_text(_inline_text(child))
        if piece and not all(c in _APPEND_TEXT_PUNCT for c in piece):
            builder.add("parrafo", piece)
    else:
        piece = _clean_text(_inline_text(child))
        if piece:
            builder.add("parrafo", piece)


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
    """Render a ``<BlockAmendment>`` preserving P1/P2/P3 numbering and tables.

    The amending text is shown as a blockquote whose internal structure
    mirrors the amended Act: section numbers on their own opening line,
    nested sub-paragraphs indented with two extra spaces per level, and
    tables (which often sit inside amendment packages in Finance Acts)
    broken out into real pipe tables flanked by the blockquote.
    """
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            builder.add_pre("quote", "\n".join(buffer))
            buffer.clear()

    def quote_prefix(level: int) -> str:
        return "> " + ("  " * level)

    def emit_numbered(numbered_el: etree._Element, level: int) -> None:
        """Render a single ``<P1>``/``<P2>``/... element as a numbered
        blockquote item, recursing into all children (including siblings of
        the *para container: Formula, Tabular, nested P{N}, lists)."""
        num_el = numbered_el.find("leg:Pnumber", NS)
        num = _clean_text(_inline_text(num_el)) if num_el is not None else ""
        para_el = _first_pseudo_para_child(numbered_el)
        first_text_el = None
        first_text = ""
        if para_el is not None:
            first_text_el = para_el.find("leg:Text", NS)
            if first_text_el is not None:
                first_text = _clean_text(_inline_text(first_text_el))
        prefix = quote_prefix(level)
        if num and first_text:
            buffer.append(f"{prefix}({num}) {first_text}")
        elif first_text:
            buffer.append(f"{prefix}{first_text}")
        elif num:
            buffer.append(f"{prefix}({num})")

        def render_sub(sub: etree._Element, sub_level: int) -> None:
            slocal = etree.QName(sub.tag).localname if isinstance(sub.tag, str) else ""
            if not slocal or slocal == "Pnumber":
                return
            if slocal == "Text":
                piece = _clean_text(_inline_text(sub))
                if piece:
                    buffer.append(f"{quote_prefix(sub_level)}{piece}")
            elif slocal == "Formula":
                piece = _clean_text(_inline_text(sub))
                if piece:
                    if not (piece.startswith("$") and piece.endswith("$")):
                        piece = f"${piece}$"
                    buffer.append(f"{quote_prefix(sub_level)}{piece}")
            elif slocal == "Tabular":
                flush()
                md = _xhtml_table_to_markdown(sub)
                if md:
                    builder.add_pre("table", md)
            elif slocal in ("P1", "P2", "P3", "P4", "P5"):
                emit_numbered(sub, sub_level + 1)
            elif slocal in ("UnorderedList", "OrderedList"):
                emit_list(sub, sub_level + 1, ordered=slocal == "OrderedList")
            elif slocal in ("Figure", "Image"):
                if slocal == "Figure":
                    builder.images_dropped += 1
            else:
                walk(sub, sub_level + 1)

        # Walk every child of the P{N} in document order so siblings of
        # the *para container (Formula, Tabular, other P{N}) are visited.
        for sibling in numbered_el:
            sib_local = etree.QName(sibling.tag).localname if isinstance(sibling.tag, str) else ""
            if not sib_local or sib_local == "Pnumber":
                continue
            if sibling is para_el:
                # Expand the *para container inline so that its own
                # children (after the already-consumed first Text) are
                # rendered at the SAME indent level as the header line.
                seen_first = first_text_el is None
                for sub in para_el:
                    slocal = etree.QName(sub.tag).localname if isinstance(sub.tag, str) else ""
                    if slocal == "Text" and not seen_first and sub is first_text_el:
                        seen_first = True
                        continue
                    render_sub(sub, level)
            else:
                render_sub(sibling, level)

    def emit_list(list_el: etree._Element, level: int, *, ordered: bool) -> None:
        """Render a ``<OrderedList>``/``<UnorderedList>`` inside an amendment,
        one line per item, preserving nested lists."""
        prefix = quote_prefix(level)
        for idx, item in enumerate(list_el.findall("leg:ListItem", NS), start=1):
            # Gather the item's leading text (before any nested list).
            leading_bits: list[str] = []
            for sub in item:
                slocal = etree.QName(sub.tag).localname if isinstance(sub.tag, str) else ""
                if slocal in ("UnorderedList", "OrderedList"):
                    break
                leading_bits.append(_inline_text(sub))
            head = _clean_text((item.text or "") + "".join(leading_bits))
            bullet = f"{idx}." if ordered else "-"
            if head:
                buffer.append(f"{prefix}{bullet} {head}")
            # Recurse into nested lists with a deeper indent.
            for sub in item:
                slocal = etree.QName(sub.tag).localname if isinstance(sub.tag, str) else ""
                if slocal == "UnorderedList":
                    emit_list(sub, level + 1, ordered=False)
                elif slocal == "OrderedList":
                    emit_list(sub, level + 1, ordered=True)

    def walk(node: etree._Element, level: int) -> None:
        for child in node:
            local = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
            if not local:
                continue
            if local == "Tabular":
                flush()
                md = _xhtml_table_to_markdown(child)
                if md:
                    builder.add_pre("table", md)
            elif local in ("P1", "P2", "P3", "P4", "P5"):
                emit_numbered(child, level)
            elif local in ("UnorderedList", "OrderedList"):
                emit_list(child, level, ordered=local == "OrderedList")
            elif local == "Text":
                piece = _clean_text(_inline_text(child))
                if piece:
                    buffer.append(f"{quote_prefix(level)}{piece}")
            elif local == "Schedule":
                # A whole Schedule inserted wholesale (e.g. "SCHEDULE 4B"
                # in Finance Act amendments). Emit its label first so the
                # reader sees what is being inserted, then walk its body.
                num_el = child.find("leg:Number", NS)
                title_el = child.find("leg:Title", NS)
                num = _clean_text("".join(num_el.itertext())) if num_el is not None else ""
                title = _clean_text("".join(title_el.itertext())) if title_el is not None else ""
                label = " — ".join(p for p in (num, title) if p)
                if label:
                    buffer.append(f"{quote_prefix(level)}**{label}**")
                body = child.find("leg:ScheduleBody", NS)
                if body is not None:
                    walk(body, level + 1)
            elif local == "Formula":
                piece = _clean_text(_inline_text(child))
                if piece:
                    if not (piece.startswith("$") and piece.endswith("$")):
                        piece = f"${piece}$"
                    buffer.append(f"{quote_prefix(level)}{piece}")
            elif local in ("Figure", "Image"):
                if local == "Figure":
                    builder.images_dropped += 1
            else:
                walk(child, level)

    walk(element, 0)
    flush()


def _first_pseudo_para_child(element: etree._Element) -> etree._Element | None:
    """Return the ``<P{N}para>`` child of a ``<P{N}>`` element, if any."""
    for c in element:
        local = etree.QName(c.tag).localname if isinstance(c.tag, str) else ""
        if local and local.startswith("P") and local.endswith("para"):
            return c
    return None


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
        if enactment_date_el is None:
            # Statutory instruments use <ukm:Made Date="..."> instead.
            enactment_date_el = meta.find(".//ukm:Made", NS)
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

        images_dropped = _count_images(root)
        long_title = _clean_text(description)
        pdf_url = (
            f"https://www.legislation.gov.uk/{type_code}/{year}/{number}"
            f"/pdfs/{type_code}_{year:04d}{number:04d}_en.pdf"
        )
        modified_iso = modified.isoformat() if modified else ""

        # The frontmatter renderer emits the generic dataclass fields plus
        # whatever lives in ``extra``. Fields like long_title, pdf_url,
        # last_modified_tna and images_dropped are not part of the generic
        # dataclass output yet, so we surface them here so nothing the
        # source publishes gets lost.
        extra: list[tuple[str, str]] = []
        for key, value in (
            ("long_title", long_title),
            ("pdf_url", pdf_url),
            ("last_modified_tna", modified_iso),
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
            ("images_dropped", str(images_dropped) if images_dropped else ""),
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

    def parse_suvestine(
        self, suvestine_data: bytes, norm_id: str
    ) -> tuple[list[Block], list[Reform]]:
        """Parse a multi-version UK suvestine blob into versioned Blocks + Reforms.

        The pipeline detects ``hasattr(text_parser, "parse_suvestine")`` and
        uses this method to override the single-snapshot parse with the
        full per-effective-date history captured by
        ``LegislationGovUkClient.get_suvestine``. Without this method the
        pipeline silently falls back to the latest-revised text only.

        Returns ``(blocks, reforms)``:

        * ``blocks`` have one ``Version`` per distinct snapshot date the
          blob contained; dedup of identical consecutive versions happens
          inside ``_parse_multiversion``.
        * ``reforms`` is a sorted list of ``Reform`` records, one per
          distinct effective date across the blob (bootstrap date first,
          followed by every applied amendment in chronological order).
        """
        data = _decode_maybe_gzipped(suvestine_data)
        if not data or not data.lstrip().startswith(b"{"):
            return [], []
        try:
            blob = json.loads(data)
        except json.JSONDecodeError as exc:
            logger.warning("parse_suvestine: %s has malformed blob (%s)", norm_id, exc)
            return [], []
        blocks = _parse_multiversion(blob)
        from legalize.transformer.xml_parser import extract_reforms as _generic_extract

        reforms = _generic_extract(blocks)
        return blocks, reforms


def _parse_single_snapshot(xml_bytes: bytes) -> list[Block]:
    """Parse one CLML XML into Blocks, each with a single Version.

    Pre-1988 Acts often expose a **metadata-only** CLML document (no
    ``<Body>``, ``NumberOfProvisions="0"``). TNA hosts the full text as
    an original PDF only — the XML exists to surface title, dates and
    publisher info. For those we synthesise a single placeholder Block
    containing a link to the PDF so the law is still represented in git
    with its enactment date, title, and a pointer the reader can follow.
    """
    root = etree.fromstring(xml_bytes)
    norm_id = _norm_id_from_root(root) or "uk"
    eff_date = _effective_date_from_root(root)
    entries = _gather_section_blocks(root)

    if not entries and _is_metadata_only(root):
        entries = [_pdf_only_placeholder_block(root, norm_id)]

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


def _is_metadata_only(root: etree._Element) -> bool:
    """True when the CLML document has no renderable body / schedules.

    TNA uses this shape for pre-1988 Acts whose consolidated text has
    never been digitally typed — the XML carries `<ukm:Metadata>` and
    nothing else, usually with ``NumberOfProvisions="0"``.
    """
    has_body = root.find(".//leg:Body", NS) is not None
    has_schedules = root.find(".//leg:Schedules", NS) is not None
    has_prelims = root.find(".//leg:PrimaryPrelims", NS) is not None
    if has_body or has_schedules or has_prelims:
        return False
    provisions = root.get("NumberOfProvisions")
    return provisions is None or provisions == "0"


def _pdf_only_placeholder_block(
    root: etree._Element, norm_id: str
) -> tuple[str, str, str, list[Paragraph], int]:
    """Build a synthetic Block pointing at the PDF for metadata-only Acts."""
    type_code, year, number = (None, None, None)
    try:
        type_code, year, number = split_norm_id(norm_id)
    except ValueError:
        pass
    pdf_url = None
    for link in root.findall(".//atom:link", NS):
        href = link.get("href") or ""
        if href.endswith(".pdf"):
            pdf_url = href.replace(
                "http://www.legislation.gov.uk/",
                "https://www.legislation.gov.uk/",
                1,
            )
            break
    if pdf_url is None and type_code and year is not None and number is not None:
        pdf_url = (
            f"https://www.legislation.gov.uk/{type_code}/{year}/{number}/pdfs/"
            f"{type_code}_{year:04d}{number:04d}_en.pdf"
        )

    title_el = root.find(".//dc:title", NS)
    title = _clean_text(title_el.text) if title_el is not None and title_el.text else ""

    paragraphs: list[Paragraph] = [
        Paragraph(
            css_class="parrafo",
            text=(
                "The full text of this Act has not been digitally typed by The "
                "National Archives and is available only as the original PDF. "
                "legislation.gov.uk serves a metadata-only CLML document for "
                "Acts of this vintage, so the body could not be rendered here."
            ),
        ),
    ]
    if pdf_url:
        paragraphs.append(
            Paragraph(
                css_class="parrafo",
                text=f"Original Act (PDF): [{title or norm_id}]({pdf_url})",
            )
        )
    return ("enacted-text", "enacted-pdf-only", title, paragraphs, 0)


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
    if enact is None:
        # Statutory instruments use <ukm:Made Date="..."> instead.
        enact = root.find(".//ukm:Made", NS)
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
    # Pre-1988 SIs published only as PDF carry <ukm:Year Value="…"/> with
    # no Made/Laid/EnactmentDate. Falling through to date.today() stamps
    # "last updated" as today across the whole pre-1988 SI corpus, which
    # leaks build-time into the git history. January 1st of the recorded
    # year is at least within the right ballpark.
    year_el = root.find(".//ukm:Year", NS)
    if year_el is not None:
        try:
            year_value = int(year_el.get("Value") or "")
            return date(year_value, 1, 1)
        except (TypeError, ValueError):
            pass
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


def _count_images(root: etree._Element) -> int:
    """Count Figure elements we will drop from the output.

    In CLML every Figure contains exactly one Image, so counting only
    Figures avoids double-counting while still being accurate.
    """
    return sum(
        1
        for el in root.iter()
        if isinstance(el.tag, str) and etree.QName(el.tag).localname == "Figure"
    )


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
