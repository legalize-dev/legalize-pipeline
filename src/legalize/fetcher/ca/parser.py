"""Justice Canada XML parser for federal acts and regulations.

Parses the custom Justice Canada XML format (Statute/Regulation DTD) into
the generic Block / NormMetadata model. Handles sections, subsections,
paragraphs, tables, definitions, formulas, schedules, and preambles.

Adapted from legalize-ca-pipeline/legalize_ca/fetchers/federal.py.
"""

from __future__ import annotations

import base64
import gc
import json
import logging
import re
from contextvars import ContextVar
from datetime import date
from typing import Any, Iterable

from lxml import etree

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import Block, NormMetadata, NormStatus, Paragraph, Rank, Reform, Version

logger = logging.getLogger(__name__)

# Namespace for lims attributes.
LIMS_NS = "http://justice.gc.ca/lims"
XML_NS = "http://www.w3.org/XML/1998/namespace"

# Base URL for the official Justice Laws Website. Used to build absolute links
# for XRefExternal cross-references — matching the convention used by CH, LI,
# EU, etc. Absolute URLs resolve correctly anywhere the MD is rendered
# (GitHub, static site generators, legalize.dev, local viewers).
JUSTICE_BASE = "https://laws-lois.justice.gc.ca"

# Language context for the current document being parsed. Set at the entry of
# ``CATextParser.parse_text`` and read by ``_inline_text`` to build
# XRefExternal URLs in the correct language. Defaults to English.
_current_lang: ContextVar[str] = ContextVar("_ca_current_lang", default="en")


def _xref_url(ref_type: str, link: str, lang: str) -> str:
    """Build an absolute Justice Laws Website URL for an XRefExternal target.

    ``ref_type`` is the ``reference-type`` attribute on XRefExternal
    (``"act"`` or ``"regulation"``). ``link`` is the target identifier
    (``"A-1"``, ``"SOR-99-129"``, etc.). ``lang`` is ``"en"`` or ``"fr"``.
    Unknown reference types fall back to acts (the most common).
    """
    if lang == "fr":
        url_lang = "fra"
        category = "reglements" if ref_type == "regulation" else "lois"
    else:
        url_lang = "eng"
        category = "regulations" if ref_type == "regulation" else "acts"
    return f"{JUSTICE_BASE}/{url_lang}/{category}/{link}/"


# Control characters to strip (C0/C1 minus tab, LF, CR).
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Tags we see in Justice Canada XML but do not need to render:
# - Identification / Chapter / AnnualStatuteId / BillHistory → parsed by the
#   MetadataParser, not body content.
# - MarginalNote / Label → inlined into their parent (Section/Subsection/etc.).
#
# Tracked here so _warn_unknown_tag does not spam the log with expected skips.
_KNOWN_SKIPPED_TAGS = frozenset(
    {
        "Identification",
        "Chapter",
        "LongTitle",
        "ShortTitle",
        "RunningHead",
        "BillHistory",
        "Stages",
        "Date",
        "ConsolidatedNumber",
        "InstrumentNumber",
        "AnnualStatuteId",
        "AnnualStatuteNumber",
        "YYYY",
        "MM",
        "DD",
        "Label",
        "MarginalNote",
        "TitleText",
        "ScheduleFormHeading",
        "OriginatingRef",
        "HistoricalNote",
        "HistoricalNoteSubItem",
    }
)

# Module-level registry of unknown tags seen at runtime. Populated by
# _warn_unknown_tag so we can surface them in logs and (optionally) in the
# per-document metadata for later review.
_unknown_tags_seen: set[str] = set()


def _warn_unknown_tag(tag: str, where: str) -> None:
    """Log and track the first occurrence of an unknown tag.

    We still drop the tag's structured content (it is not rendered), but the
    warning lets us notice schema additions instead of silently missing data.
    Inline text is recovered separately by ``_fallback_unknown_block``.
    """
    if tag in _KNOWN_SKIPPED_TAGS or tag in _unknown_tags_seen:
        return
    _unknown_tags_seen.add(tag)
    logger.warning("CA parser: unknown %s tag <%s> — emitting as plain text", where, tag)


def _fallback_unknown_block(el: etree._Element) -> list[Paragraph]:
    """Last-resort renderer for an unknown block element.

    We recurse for text content (so nothing is silently dropped) and emit it
    as a single paragraph. Structure is lost, but the legal text survives.
    """
    txt = _clean(_inline_text(el))
    if txt:
        return [Paragraph(css_class="parrafo", text=txt)]
    return []


def _clean(text: str) -> str:
    """Normalize whitespace and strip control characters."""
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_date(date_str: str) -> date | None:
    """Parse dates in YYYY-MM-DD or YYYYMMDD format."""
    if not date_str:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", date_str)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.match(r"(\d{4})(\d{2})(\d{2})", date_str)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Inline text extraction (recursive, preserves emphasis/definitions/refs)
# ---------------------------------------------------------------------------


def _inline_text(el: etree._Element) -> str:
    """Recursively extract text with inline Markdown formatting.

    Preserves:
    - ``Emphasis``, ``DefinedTermEn/Fr``, ``DefinitionRef`` → ``*italic*``
    - ``XRefExternal`` with ``link`` → ``[text](https://laws-lois.justice.gc.ca/...)``
      (absolute URL to the official Justice Laws Website, matching CH/LI/EU
      convention so links work in any MD renderer, not just legalize.dev)
    - ``XRefExternal`` without ``link`` → plain text
    - ``Repealed`` → ``*[Repealed, ...]*`` (italicized as a repeal marker)
    """
    parts: list[str] = []

    if el.text:
        parts.append(el.text)

    for child in el:
        if not isinstance(child.tag, str):
            continue  # lxml comments and processing instructions — skip silently
        tag = etree.QName(child).localname
        child_text = _inline_text(child)
        stripped = child_text.strip()

        if tag in ("Emphasis", "DefinedTermEn", "DefinedTermFr", "DefinitionRef"):
            if stripped:
                parts.append(f"*{stripped}*")
        elif tag == "XRefExternal":
            link = child.get("link", "").strip()
            if stripped and link:
                ref_type = child.get("reference-type", "act")
                url = _xref_url(ref_type, link, _current_lang.get())
                parts.append(f"[{stripped}]({url})")
            elif stripped:
                parts.append(stripped)
        elif tag == "a":
            # Anchor links in older pre-2016 XML variants. Render as plain text
            # unless an href is present, in which case preserve it as a
            # Markdown link. The URLs point at the active Justice Canada
            # site so they remain live.
            href = child.get("href", "").strip()
            if stripped and href:
                parts.append(f"[{stripped}]({href})")
            elif stripped:
                parts.append(stripped)
        elif tag == "Repealed":
            if stripped:
                parts.append(f"*{stripped}*")
        elif tag in ("AmendedText",):
            parts.append(child_text)
        elif tag in ("FormulaTerm", "FormulaText", "FormulaDefinition", "FormulaConnector"):
            parts.append(child_text)
        else:
            parts.append(child_text)

        if child.tail:
            parts.append(child.tail)

    return "".join(parts).strip()


def _plain_text(el: etree._Element) -> str:
    """Extract plain text from an element, ignoring inline markup.

    Used for metadata fields (title, long_title, department) where Markdown
    links inside a YAML string would be ugly and hard for consumers to parse.
    The structured link target is captured separately as an ``extra`` field
    when needed (e.g. ``enabling_authority_id`` for regulations).
    """
    return _clean("".join(el.itertext()))


# ---------------------------------------------------------------------------
# Table parsing
# ---------------------------------------------------------------------------


def _table_to_markdown(table_group: etree._Element) -> str:
    """Convert a <TableGroup> containing XHTML-like table to Markdown pipe table."""
    rows: list[list[str]] = []

    for tr in table_group.iter():
        tag = etree.QName(tr).localname if isinstance(tr.tag, str) else ""
        if tag != "row":
            continue
        cells: list[str] = []
        for entry in tr:
            entry_tag = etree.QName(entry).localname if isinstance(entry.tag, str) else ""
            if entry_tag != "entry":
                continue
            text = _clean(_inline_text(entry)).replace("|", "\\|")
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


def _parse_section(section: etree._Element) -> list[Paragraph]:
    """Parse a <Section> element into a list of Paragraphs.

    Iterates children in document order so unknown elements fall through
    to ``_fallback_unknown_block`` instead of being silently dropped.
    """
    paragraphs: list[Paragraph] = []

    # Section heading: Label + first MarginalNote (section-level).
    label = section.find("Label")
    marginal = section.find("MarginalNote")
    heading_parts: list[str] = []
    if label is not None and label.text:
        heading_parts.append(label.text.strip())
    if marginal is not None:
        heading_parts.append(_clean(_inline_text(marginal)))
    if heading_parts:
        paragraphs.append(Paragraph(css_class="articulo", text=" ".join(heading_parts)))

    # Iterate children in document order.
    for child in section:
        if not isinstance(child.tag, str):
            continue  # lxml comments and processing instructions — skip silently
        tag = etree.QName(child).localname
        if tag == "Text":
            txt = _clean(_inline_text(child))
            if txt:
                paragraphs.append(Paragraph(css_class="parrafo", text=txt))
        elif tag == "Subsection":
            paragraphs.extend(_parse_subsection(child))
        elif tag == "Introduction":
            for text_el in child.findall("./Text"):
                txt = _clean(_inline_text(text_el))
                if txt:
                    paragraphs.append(Paragraph(css_class="parrafo", text=txt))
        elif tag == "Paragraph":
            paragraphs.extend(_parse_paragraph(child))
        elif tag == "Item":
            paragraphs.extend(_parse_item(child, indent=0))
        elif tag == "Formula":
            formula_text = _parse_formula(child)
            if formula_text:
                paragraphs.append(Paragraph(css_class="pre", text=formula_text))
        elif tag == "FormulaGroup":
            for f_el in child.findall("./Formula"):
                f_text = _parse_formula(f_el)
                if f_text:
                    paragraphs.append(Paragraph(css_class="pre", text=f_text))
        elif tag == "Definition":
            paragraphs.extend(_parse_definition(child))
        elif tag in ("AmendedText", "ReadAsText"):
            # Bill constructs: the replacement/insertion text for an amendment.
            # Render as a blockquote so readers can visually separate "the
            # amendment says: replace X with Y" — the Y being quoted content
            # of the new statute — from the amendment instruction itself.
            paragraphs.extend(_parse_amended_text(child))
        elif tag == "ContinuedParagraph":
            for text_el in child.findall("./Text"):
                txt = _clean(_inline_text(text_el))
                if txt:
                    paragraphs.append(Paragraph(css_class="parrafo", text=txt))
        elif tag == "ContinuedSectionSubsection":
            for text_el in child.findall("./Text"):
                t = _clean(_inline_text(text_el))
                if t:
                    paragraphs.append(Paragraph(css_class="parrafo", text=t))
        elif tag == "SectionPiece":
            for sub in child:
                sub_tag = etree.QName(sub).localname if isinstance(sub.tag, str) else ""
                if sub_tag == "Text":
                    t = _clean(_inline_text(sub))
                    if t:
                        paragraphs.append(Paragraph(css_class="parrafo", text=t))
                elif sub_tag == "Formula":
                    f = _parse_formula(sub)
                    if f:
                        paragraphs.append(Paragraph(css_class="pre", text=f))
        elif tag == "a":
            # Anchor element appearing as direct Section child in pre-2016
            # pre-2016 XMLs — typically a bookmark target with no rendered
            # content. Preserve any text via the inline helper and move on.
            t = _clean(_inline_text(child))
            if t:
                href = child.get("href", "").strip()
                paragraphs.append(
                    Paragraph(css_class="parrafo", text=f"[{t}]({href})" if href else t)
                )
        elif tag == "Note":
            status = child.get("status", "")
            txt = _clean(_inline_text(child))
            if txt:
                marker = f"*[{status}]* " if status else ""
                paragraphs.append(Paragraph(css_class="parrafo", text=f"> {marker}{txt}"))
        elif tag == "Provision":
            paragraphs.extend(_parse_provision(child))
        elif tag == "Oath":
            txt = _clean(_inline_text(child))
            if txt:
                paragraphs.append(Paragraph(css_class="parrafo", text=f"> *{txt}*"))
        elif tag == "HistoricalNote":
            items = []
            for sub in child.findall("./HistoricalNoteSubItem"):
                txt = _clean(_inline_text(sub))
                if txt:
                    items.append(txt)
            if items:
                paragraphs.append(Paragraph(css_class="parrafo", text=f"> *{'; '.join(items)}*"))
        elif tag == "TableGroup":
            md_table = _table_to_markdown(child)
            if md_table:
                paragraphs.append(Paragraph(css_class="table", text=md_table))
        elif tag in _KNOWN_SKIPPED_TAGS:
            continue
        else:
            _warn_unknown_tag(tag, "section")
            paragraphs.extend(_fallback_unknown_block(child))

    return paragraphs


def _parse_subsection(subsec: etree._Element) -> list[Paragraph]:
    """Parse a <Subsection> element, including its MarginalNote title.

    Iterates children in document order so unknown elements fall through
    to ``_fallback_unknown_block`` instead of being silently dropped.
    """
    paragraphs: list[Paragraph] = []
    label = subsec.find("Label")
    label_text = _clean(label.text or "") if label is not None else ""

    # MarginalNote on the subsection (a short title for the (N) block).
    marginal = subsec.find("MarginalNote")
    marginal_text = _clean(_inline_text(marginal)) if marginal is not None else ""

    first_text_emitted = False

    for child in subsec:
        if not isinstance(child.tag, str):
            continue  # lxml comments and processing instructions — skip silently
        tag = etree.QName(child).localname
        if tag == "Text":
            txt = _clean(_inline_text(child))
            if not txt:
                continue
            if not first_text_emitted:
                prefix_parts = []
                if label_text:
                    prefix_parts.append(f"**{label_text}**")
                if marginal_text:
                    prefix_parts.append(f"*{marginal_text}*")
                prefix = " ".join(prefix_parts)
                body = f"{prefix} {txt}" if prefix else txt
                paragraphs.append(Paragraph(css_class="parrafo", text=body))
                first_text_emitted = True
            else:
                paragraphs.append(Paragraph(css_class="parrafo", text=txt))
        elif tag == "Paragraph":
            paragraphs.extend(_parse_paragraph(child))
        elif tag == "ContinuedParagraph":
            for text_el in child.findall("./Text"):
                t = _clean(_inline_text(text_el))
                if t:
                    paragraphs.append(Paragraph(css_class="parrafo", text=t))
        elif tag == "ContinuedSubparagraph":
            for text_el in child.findall("./Text"):
                t = _clean(_inline_text(text_el))
                if t:
                    paragraphs.append(Paragraph(css_class="parrafo", text=t))
        elif tag == "ContinuedSectionSubsection":
            # Pre-2016 XML idiom (and still in some bills): a continuation
            # clause at the subsection level. Text children only — same
            # rendering as ContinuedParagraph.
            for text_el in child.findall("./Text"):
                t = _clean(_inline_text(text_el))
                if t:
                    paragraphs.append(Paragraph(css_class="parrafo", text=t))
        elif tag == "SectionPiece":
            # A grouping of Text + Formula + ContinuedSectionSubsection
            # used mid-section when a formula splits the prose in two.
            # Recurse over its children rather than special-case each kind.
            for sub in child:
                sub_tag = etree.QName(sub).localname if isinstance(sub.tag, str) else ""
                if sub_tag == "Text":
                    t = _clean(_inline_text(sub))
                    if t:
                        paragraphs.append(Paragraph(css_class="parrafo", text=t))
                elif sub_tag == "Formula":
                    f = _parse_formula(sub)
                    if f:
                        paragraphs.append(Paragraph(css_class="pre", text=f))
                elif sub_tag == "ContinuedSectionSubsection":
                    for text_el in sub.findall("./Text"):
                        t = _clean(_inline_text(text_el))
                        if t:
                            paragraphs.append(Paragraph(css_class="parrafo", text=t))
        elif tag == "Item":
            paragraphs.extend(_parse_item(child, indent=0))
        elif tag == "Formula":
            formula_text = _parse_formula(child)
            if formula_text:
                paragraphs.append(Paragraph(css_class="pre", text=formula_text))
        elif tag == "FormulaGroup":
            # Wrapper used by tax and benefits legislation when multiple
            # formulas live adjacent. Walk the contained Formula elements.
            for f_el in child.findall("./Formula"):
                f_text = _parse_formula(f_el)
                if f_text:
                    paragraphs.append(Paragraph(css_class="pre", text=f_text))
        elif tag == "FormulaDefinition":
            # Variable definition stub that some bill XMLs place directly
            # under a Subsection rather than inside the Formula element.
            txt = _clean(_inline_text(child))
            if txt:
                paragraphs.append(Paragraph(css_class="parrafo", text=f"`{txt}`"))
        elif tag == "Definition":
            paragraphs.extend(_parse_definition(child))
        elif tag in ("AmendedText", "ReadAsText"):
            paragraphs.extend(_parse_amended_text(child))
        elif tag == "Note":
            status = child.get("status", "")
            txt = _clean(_inline_text(child))
            if txt:
                marker = f"*[{status}]* " if status else ""
                paragraphs.append(Paragraph(css_class="parrafo", text=f"> {marker}{txt}"))
        elif tag == "Provision":
            paragraphs.extend(_parse_provision(child))
        elif tag == "Oath":
            txt = _clean(_inline_text(child))
            if txt:
                paragraphs.append(Paragraph(css_class="parrafo", text=f"> *{txt}*"))
        elif tag == "TableGroup":
            md_table = _table_to_markdown(child)
            if md_table:
                paragraphs.append(Paragraph(css_class="table", text=md_table))
        elif tag in _KNOWN_SKIPPED_TAGS:
            continue
        else:
            _warn_unknown_tag(tag, "subsection")
            paragraphs.extend(_fallback_unknown_block(child))

    return paragraphs


def _parse_amended_text(el: etree._Element) -> list[Paragraph]:
    """Render a Bill's ``<AmendedText>`` or ``<ReadAsText>`` as blockquoted text.

    These elements wrap the NEW statute text being inserted/replaced by an
    amendment. The surrounding sentence reads "Subsection X(2) of the Act is
    replaced by the following:" and the AmendedText is what follows the
    colon. Rendering it as a blockquote signals "this is the post-amendment
    statute text" and keeps it visually distinct from the amendment
    instruction prose.
    """
    paragraphs: list[Paragraph] = []
    for child in el:
        if not isinstance(child.tag, str):
            continue  # lxml comments and processing instructions — skip silently
        tag = etree.QName(child).localname
        if tag == "Section":
            nested = _parse_section(child)
            for p in nested:
                paragraphs.append(Paragraph(css_class=p.css_class, text=f"> {p.text}"))
        elif tag == "Subsection":
            nested = _parse_subsection(child)
            for p in nested:
                paragraphs.append(Paragraph(css_class=p.css_class, text=f"> {p.text}"))
        elif tag == "Paragraph":
            nested = _parse_paragraph(child)
            for p in nested:
                paragraphs.append(Paragraph(css_class=p.css_class, text=f"> {p.text}"))
        elif tag == "Text":
            txt = _clean(_inline_text(child))
            if txt:
                paragraphs.append(Paragraph(css_class="parrafo", text=f"> {txt}"))
        elif tag == "TableGroup":
            md_table = _table_to_markdown(child)
            if md_table:
                # Prefix each row line so the whole table sits in the quote.
                quoted = "\n".join(f"> {line}" for line in md_table.splitlines() if line)
                paragraphs.append(Paragraph(css_class="table", text=quoted))
        elif tag == "Formula":
            f = _parse_formula(child)
            if f:
                paragraphs.append(Paragraph(css_class="pre", text=f"> {f}"))
        else:
            # Last resort: flatten to plain text so nothing is silently dropped.
            txt = _clean(_inline_text(child))
            if txt:
                paragraphs.append(Paragraph(css_class="parrafo", text=f"> {txt}"))
    return paragraphs


def _parse_paragraph(para: etree._Element) -> list[Paragraph]:
    """Parse a <Paragraph> element (level below subsection)."""
    paragraphs: list[Paragraph] = []
    label = para.find("Label")
    label_text = _clean(label.text or "") if label is not None else ""

    for text_el in para.findall("./Text"):
        txt = _clean(_inline_text(text_el))
        if txt:
            prefix = f"**{label_text}** " if label_text else ""
            paragraphs.append(Paragraph(css_class="parrafo", text=f"{prefix}{txt}"))

    # Subparagraphs.
    for subpara in para.findall("./Subparagraph"):
        paragraphs.extend(_parse_subparagraph(subpara))

    # ContinuedSubparagraph within paragraph.
    for csp in para.findall("./ContinuedSubparagraph"):
        for text_el in csp.findall("./Text"):
            txt = _clean(_inline_text(text_el))
            if txt:
                paragraphs.append(Paragraph(css_class="parrafo", text=txt))

    return paragraphs


def _parse_subparagraph(subpara: etree._Element) -> list[Paragraph]:
    """Parse a <Subparagraph> element."""
    paragraphs: list[Paragraph] = []
    label = subpara.find("Label")
    label_text = _clean(label.text or "") if label is not None else ""

    for text_el in subpara.findall("./Text"):
        txt = _clean(_inline_text(text_el))
        if txt:
            prefix = f"**{label_text}** " if label_text else ""
            paragraphs.append(Paragraph(css_class="parrafo", text=f"{prefix}{txt}"))

    # Clauses.
    for clause in subpara.findall("./Clause"):
        paragraphs.extend(_parse_clause(clause))

    # ContinuedSubparagraph within subparagraph.
    for csp in subpara.findall("./ContinuedSubparagraph"):
        for text_el in csp.findall("./Text"):
            txt = _clean(_inline_text(text_el))
            if txt:
                paragraphs.append(Paragraph(css_class="parrafo", text=txt))

    return paragraphs


def _parse_clause(clause: etree._Element) -> list[Paragraph]:
    """Parse a <Clause> element."""
    paragraphs: list[Paragraph] = []
    label = clause.find("Label")
    label_text = _clean(label.text or "") if label is not None else ""

    for text_el in clause.findall("./Text"):
        txt = _clean(_inline_text(text_el))
        if txt:
            prefix = f"**{label_text}** " if label_text else ""
            paragraphs.append(Paragraph(css_class="parrafo", text=f"{prefix}{txt}"))

    # Subclauses.
    for subclause in clause.findall("./Subclause"):
        sc_label = subclause.find("Label")
        sc_label_text = _clean(sc_label.text or "") if sc_label is not None else ""
        for text_el in subclause.findall("./Text"):
            txt = _clean(_inline_text(text_el))
            if txt:
                prefix = f"**{sc_label_text}** " if sc_label_text else ""
                paragraphs.append(Paragraph(css_class="parrafo", text=f"{prefix}{txt}"))

    return paragraphs


def _parse_item(item: etree._Element, indent: int = 0) -> list[Paragraph]:
    """Parse an <Item> (list item)."""
    paragraphs: list[Paragraph] = []
    label = item.find("Label")
    label_text = _clean(label.text or "") if label is not None else ""

    for text_el in item.findall("./Text"):
        txt = _clean(_inline_text(text_el))
        if txt:
            prefix = f"**{label_text}** " if label_text else "- "
            paragraphs.append(Paragraph(css_class="list_item", text=f"{prefix}{txt}"))

    return paragraphs


def _parse_formula(formula: etree._Element) -> str:
    """Parse a <Formula> element into code-formatted text."""
    parts: list[str] = []
    for child in formula:
        if not isinstance(child.tag, str):
            continue  # lxml comments and processing instructions — skip silently
        tag = etree.QName(child).localname
        if tag in ("FormulaTerm", "FormulaText", "FormulaDefinition", "FormulaConnector"):
            txt = _clean(_inline_text(child))
            if txt:
                parts.append(txt)
    return "`" + " ".join(parts) + "`" if parts else ""


def _parse_definition(defn: etree._Element) -> list[Paragraph]:
    """Parse a <Definition> block.

    The defined term is rendered as italic (Markdown convention for legal
    definitions, matching how the term appears in the official HTML). We
    pre-wrap with ``*...*`` rather than using ``firma_rey`` -- that class is
    reserved for signature blocks across the codebase and would render the
    term as bold, which is misleading.
    """
    paragraphs: list[Paragraph] = []
    term_el = defn.find("DefinedTermEn") or defn.find("DefinedTermFr")
    if term_el is not None:
        term_text = _clean(_inline_text(term_el))
        if term_text:
            paragraphs.append(Paragraph(css_class="parrafo", text=f"*{term_text}*"))
    for text_el in defn.findall("./Text"):
        txt = _clean(_inline_text(text_el))
        if txt:
            paragraphs.append(Paragraph(css_class="parrafo", text=txt))
    return paragraphs


# ---------------------------------------------------------------------------
# Body-level parsing (Parts, Divisions, Headings, Schedules)
# ---------------------------------------------------------------------------


def _parse_heading_block(child: etree._Element, top_css: str, sub_css: str) -> list[Paragraph]:
    """Render a Part/Division heading: Label + TitleText joined with ' - '."""
    paragraphs: list[Paragraph] = []
    plabel = child.find("Label")
    ptitle = child.find("TitleText")
    heading_parts: list[str] = []
    if plabel is not None and plabel.text:
        heading_parts.append(plabel.text.strip())
    if ptitle is not None:
        heading_parts.append(_clean(_inline_text(ptitle)))
    if heading_parts:
        paragraphs.append(Paragraph(css_class=top_css, text=" - ".join(heading_parts)))
    paragraphs.extend(_parse_body(child))
    return paragraphs


def _render_gazette_body(entry: dict) -> tuple[Paragraph, ...]:
    """Turn a Gazette-PDF entry's extracted text into amendment paragraphs.

    The text comes from :class:`GazetteSegmenter` after column-aware
    extraction — one chapter's bilingual body, double-newline-separated
    per source page. We render it as:

    - A ``> **Amendment bill**`` lead-in quote block naming the bill
      and assent date (visual cue for amendment-event commits, mirroring
      the ``> **Summary.**`` block emitted by annual-statute entries).
    - The body text split on paragraph boundaries, each paragraph kept
      as plain prose. No numbered sections are re-synthesized — Gazette
      PDFs use prose-style legal drafting without the tight XML-style
      structure that annual-statute bills provide.

    An OCR-quality disclaimer is prepended as a blockquote when the
    confidence probe tripped below 0.85 (OCR'd pre-1998 scans).
    """
    body_text = entry.get("body_text", "")
    if not body_text:
        return ()

    lead: list[str] = []
    amending_title = entry.get("amending_title", "").strip()
    bill_number = entry.get("bill_number", "").strip()
    assent = entry.get("date", "")

    if amending_title:
        if bill_number:
            lead.append(
                f"> **Amendment bill.** *{amending_title}* "
                f"(Bill {bill_number}, assented to {assent})."
            )
        else:
            lead.append(f"> **Amendment bill.** *{amending_title}* (assented to {assent}).")

    ocr = entry.get("ocr_confidence", 1.0)
    if isinstance(ocr, (int, float)) and ocr < 0.85:
        lead.append(
            f"> **OCR quality {ocr:.0%}** — this text is reconstructed from a "
            "scanned Gazette issue and may contain optical recognition errors."
        )

    paragraphs: list[Paragraph] = [Paragraph(css_class="parrafo", text=line) for line in lead]

    # Body: split on blank lines, emit each paragraph cleaned of control chars.
    for chunk in re.split(r"\n\s*\n", body_text):
        cleaned = _clean(chunk)
        if cleaned:
            paragraphs.append(Paragraph(css_class="parrafo", text=cleaned))

    return tuple(paragraphs)


def _parse_bill_introduction(intro: etree._Element) -> list[Paragraph]:
    """Render a ``<Bill>``'s Introduction (Recommendation + Summary).

    Annual-statute bills carry two pre-enactment blocks:

    - ``Recommendation`` — the Governor General's recommendation line naming
      the appropriation authority. Short (1-2 sentences).
    - ``Summary`` — a plain-English paragraph explaining what the bill does.
      Often multiple Provisions, each a paragraph of the summary.

    We render both as blockquote lead-ins so the amendment commit's body
    starts with the same structural cue as a consolidated commit's
    Preamble — one "> " prefix, leading the reader in before the numbered
    section body begins.
    """
    paragraphs: list[Paragraph] = []

    rec_el = intro.find("Recommendation")
    if rec_el is not None:
        rec_paragraphs: list[str] = []
        for prov in rec_el.findall("./Provision"):
            for child in prov:
                if not isinstance(child.tag, str):
                    continue
                tag = etree.QName(child).localname
                if tag == "Text":
                    txt = _clean(_inline_text(child))
                    if txt:
                        rec_paragraphs.append(txt)
        if rec_paragraphs:
            joined = " ".join(rec_paragraphs)
            paragraphs.append(
                Paragraph(css_class="parrafo", text=f"> **Recommendation.** {joined}")
            )

    summary_el = intro.find("Summary")
    if summary_el is not None:
        summary_paragraphs: list[str] = []
        for prov in summary_el.findall("./Provision"):
            for child in prov:
                if not isinstance(child.tag, str):
                    continue
                tag = etree.QName(child).localname
                if tag == "Text":
                    txt = _clean(_inline_text(child))
                    if txt:
                        summary_paragraphs.append(txt)
                elif tag in ("DocumentInternal", "Group"):
                    for sub in child.iter("Text"):
                        t = _clean(_inline_text(sub))
                        if t:
                            summary_paragraphs.append(t)
        if summary_paragraphs:
            # Split across multiple blockquote paragraphs so long summaries
            # stay readable. The first carries the "Summary." label.
            first = summary_paragraphs[0]
            paragraphs.append(Paragraph(css_class="parrafo", text=f"> **Summary.** {first}"))
            for para in summary_paragraphs[1:]:
                paragraphs.append(Paragraph(css_class="parrafo", text=f"> {para}"))

    return paragraphs


def _parse_provision(provision: etree._Element) -> list[Paragraph]:
    """Render a <Provision> (used inside Introduction/Enacts and Schedules).

    Provisions can carry text, tables, or further nested structures
    (DocumentInternal/Group). Iterating children in order keeps the output
    aligned with the source document flow.
    """
    paragraphs: list[Paragraph] = []
    for child in provision:
        if not isinstance(child.tag, str):
            continue  # lxml comments and processing instructions — skip silently
        tag = etree.QName(child).localname
        if tag == "Text":
            txt = _clean(_inline_text(child))
            if txt:
                paragraphs.append(Paragraph(css_class="parrafo", text=txt))
        elif tag == "TableGroup":
            md_table = _table_to_markdown(child)
            if md_table:
                paragraphs.append(Paragraph(css_class="table", text=md_table))
        elif tag == "Formula":
            f_text = _parse_formula(child)
            if f_text:
                paragraphs.append(Paragraph(css_class="pre", text=f_text))
        elif tag in ("DocumentInternal", "Group"):
            # Wrapper containers: recurse one level in.
            for sub in child:
                sub_tag = etree.QName(sub).localname if isinstance(sub.tag, str) else ""
                if sub_tag == "Provision":
                    paragraphs.extend(_parse_provision(sub))
                elif sub_tag == "TableGroup":
                    md_table = _table_to_markdown(sub)
                    if md_table:
                        paragraphs.append(Paragraph(css_class="table", text=md_table))
                elif sub_tag == "Text":
                    txt = _clean(_inline_text(sub))
                    if txt:
                        paragraphs.append(Paragraph(css_class="parrafo", text=txt))
    return paragraphs


def _parse_body(body: etree._Element) -> list[Paragraph]:
    """Parse the <Body> of an Act/Regulation into paragraphs."""
    paragraphs: list[Paragraph] = []

    for child in body:
        if not isinstance(child.tag, str):
            continue  # lxml comments and processing instructions — skip silently
        tag = etree.QName(child).localname

        if tag == "Heading":
            title_text = child.find("TitleText")
            if title_text is not None:
                txt = _clean(_inline_text(title_text))
                if txt:
                    level = child.get("level", "1")
                    css = "titulo_tit" if level == "1" else "capitulo_tit"
                    # Some headings include a Label ("PART III") alongside TitleText.
                    label_el = child.find("Label")
                    if label_el is not None and label_el.text:
                        txt = f"{label_el.text.strip()} - {txt}"
                    paragraphs.append(Paragraph(css_class=css, text=txt))

        elif tag == "Section":
            paragraphs.extend(_parse_section(child))

        elif tag == "Part":
            paragraphs.extend(_parse_heading_block(child, "titulo_tit", "capitulo_tit"))

        elif tag == "Division":
            paragraphs.extend(_parse_heading_block(child, "capitulo_tit", "seccion"))

        elif tag == "Subdivision":
            paragraphs.extend(_parse_heading_block(child, "seccion", "seccion"))

        elif tag == "Oath":
            oath_text = _clean(_inline_text(child))
            if oath_text:
                paragraphs.append(Paragraph(css_class="parrafo", text=f"> *{oath_text}*"))

        elif tag == "List":
            for item in child.findall(".//Item"):
                paragraphs.extend(_parse_item(item))

        elif tag == "Schedule":
            paragraphs.extend(_parse_schedule(child))

        elif tag == "TableGroup":
            md_table = _table_to_markdown(child)
            if md_table:
                paragraphs.append(Paragraph(css_class="table", text=md_table))

        elif tag == "Provision":
            paragraphs.extend(_parse_provision(child))

        elif tag == "Introduction":
            # Body-level Introduction (enacting clauses and the like).
            for sub in child:
                sub_tag = etree.QName(sub).localname if isinstance(sub.tag, str) else ""
                if sub_tag == "Enacts":
                    for prov in sub.findall("./Provision"):
                        paragraphs.extend(_parse_provision(prov))
                elif sub_tag == "Text":
                    txt = _clean(_inline_text(sub))
                    if txt:
                        paragraphs.append(Paragraph(css_class="parrafo", text=txt))
                elif sub_tag == "Provision":
                    paragraphs.extend(_parse_provision(sub))

        elif tag == "Note":
            # Editorial notes, renvoi-only notes, etc. Render as blockquote so
            # they are visually separated from operative legislative text.
            status = child.get("status", "")
            txt = _clean(_inline_text(child))
            if txt:
                marker = f"*[{status}]* " if status else ""
                paragraphs.append(Paragraph(css_class="parrafo", text=f"> {marker}{txt}"))

        elif tag in _KNOWN_SKIPPED_TAGS:
            # Metadata-only tag; not rendered in the body.
            continue

        else:
            # Unknown block-level element — fall back to plain-text rendering
            # rather than silently dropping. Losing structure is recoverable;
            # losing text is not.
            _warn_unknown_tag(tag, "body")
            paragraphs.extend(_fallback_unknown_block(child))

    return paragraphs


def _parse_schedule(sched: etree._Element) -> list[Paragraph]:
    """Parse a <Schedule> element (Label, OriginatingRef, Notes, body content)."""
    paragraphs: list[Paragraph] = []

    # Heading block: ScheduleFormHeading holds Label + OriginatingRef + optional TitleText.
    form_heading = sched.find("ScheduleFormHeading")
    if form_heading is not None:
        label_el = form_heading.find("Label")
        orig_ref = form_heading.find("OriginatingRef")
        heading_parts: list[str] = []
        if label_el is not None and label_el.text:
            heading_parts.append(label_el.text.strip())
        if orig_ref is not None:
            ref_text = _clean(_inline_text(orig_ref))
            if ref_text:
                heading_parts.append(ref_text)
        if heading_parts:
            paragraphs.append(Paragraph(css_class="titulo_tit", text=" ".join(heading_parts)))
        # Optional TitleText inside the form heading.
        for fh_child in form_heading:
            fh_tag = etree.QName(fh_child).localname if isinstance(fh_child.tag, str) else ""
            if fh_tag == "TitleText":
                txt = _clean(_inline_text(fh_child))
                if txt:
                    paragraphs.append(Paragraph(css_class="capitulo_tit", text=txt))
    else:
        # Legacy: plain Label at top of Schedule.
        label_el = sched.find("Label")
        if label_el is not None and label_el.text:
            paragraphs.append(Paragraph(css_class="titulo_tit", text=label_el.text.strip()))

    # Body content: iterate children once, handling each tag inline (not via
    # _parse_body, which would re-enter the full list and risk double-emission).
    for child in sched:
        if not isinstance(child.tag, str):
            continue  # lxml comments and processing instructions — skip silently
        tag = etree.QName(child).localname
        if tag in ("ScheduleFormHeading", "Label"):
            continue  # Handled in the header block above.
        if tag == "Provision":
            paragraphs.extend(_parse_provision(child))
        elif tag == "Note":
            status = child.get("status", "")
            txt = _clean(_inline_text(child))
            if txt:
                marker = f"*[{status}]* " if status else ""
                paragraphs.append(Paragraph(css_class="parrafo", text=f"> {marker}{txt}"))
        elif tag == "TableGroup":
            md_table = _table_to_markdown(child)
            if md_table:
                paragraphs.append(Paragraph(css_class="table", text=md_table))
        elif tag == "Section":
            paragraphs.extend(_parse_section(child))
        elif tag == "Part":
            paragraphs.extend(_parse_heading_block(child, "titulo_tit", "capitulo_tit"))
        elif tag == "Division":
            paragraphs.extend(_parse_heading_block(child, "capitulo_tit", "seccion"))
        elif tag == "Heading":
            title_text = child.find("TitleText")
            if title_text is not None:
                txt = _clean(_inline_text(title_text))
                if txt:
                    level = child.get("level", "1")
                    css = "titulo_tit" if level == "1" else "capitulo_tit"
                    label_el = child.find("Label")
                    if label_el is not None and label_el.text:
                        txt = f"{label_el.text.strip()} - {txt}"
                    paragraphs.append(Paragraph(css_class=css, text=txt))
        elif tag == "Text":
            txt = _clean(_inline_text(child))
            if txt:
                paragraphs.append(Paragraph(css_class="parrafo", text=txt))
        elif tag in ("DocumentInternal", "Group"):
            # Schedule wrapper container — recurse in and emit provisions/tables.
            for sub in child.iter():
                sub_tag = etree.QName(sub).localname if isinstance(sub.tag, str) else ""
                if sub_tag == "Provision" and sub is not child:
                    paragraphs.extend(_parse_provision(sub))
                elif sub_tag == "TableGroup" and sub is not child:
                    # Skip tables nested inside Provisions (already emitted above).
                    parent = sub.getparent()
                    parent_tag = (
                        etree.QName(parent).localname
                        if parent is not None and isinstance(parent.tag, str)
                        else ""
                    )
                    if parent_tag != "Provision":
                        md_table = _table_to_markdown(sub)
                        if md_table:
                            paragraphs.append(Paragraph(css_class="table", text=md_table))
        elif tag == "Schedule":
            # Nested schedule (rare — some amendment bills enact a Schedule
            # that itself contains a Schedule). Recurse.
            paragraphs.extend(_parse_schedule(child))
        elif tag == "FormGroup":
            # Schedule form grouping (multiple <Form> elements sharing a
            # heading). Walk children and emit each Form's text content.
            for sub in child:
                sub_tag = etree.QName(sub).localname if isinstance(sub.tag, str) else ""
                if sub_tag in ("Provision", "Form"):
                    paragraphs.extend(_parse_provision(sub))
                elif sub_tag == "Text":
                    t = _clean(_inline_text(sub))
                    if t:
                        paragraphs.append(Paragraph(css_class="parrafo", text=t))
        elif tag == "Repealed":
            # Legacy schedule item marked as repealed (the item text is kept
            # for historical accuracy but flagged).
            txt = _clean(_inline_text(child))
            if txt:
                paragraphs.append(Paragraph(css_class="parrafo", text=f"> *[Repealed]* {txt}"))
        elif tag == "BillPiece":
            # Amendment-bill schedule fragment: the "Schedule appended to
            # this Act is amended by replacing …". Typically wraps Provisions
            # or Text children — treat as a flat provision walker.
            paragraphs.extend(_parse_provision(child))
        elif tag in ("AmendedText", "ReadAsText"):
            paragraphs.extend(_parse_amended_text(child))
        elif tag == "BilingualGroup":
            # Appears in pre-2016 XML variants for side-by-side EN/FR
            # listing of schedule items. Extract the plain text — in the
            # language-specific file we receive, only the relevant language
            # is present anyway.
            txt = _clean(_inline_text(child))
            if txt:
                paragraphs.append(Paragraph(css_class="parrafo", text=txt))

        elif tag in _KNOWN_SKIPPED_TAGS:
            continue

        else:
            # Unknown schedule element — preserve its text content.
            _warn_unknown_tag(tag, "schedule")
            paragraphs.extend(_fallback_unknown_block(child))

    return paragraphs


# ---------------------------------------------------------------------------
# TextParser
# ---------------------------------------------------------------------------


class CATextParser(TextParser):
    """Parses Justice Canada XML into Block objects.

    Full-document order preserved: Preamble → root Introduction (enacting
    clauses) → Body → root-level Schedules. Each section (and its Historical
    Notes) is emitted inline.
    """

    def parse_text(self, data: bytes) -> list[Any]:
        """Parse the full act/regulation XML into a list of Block objects.

        Each act/regulation becomes a single Block with one Version. The
        document's ``xml:lang`` is pushed into a contextvar so any
        XRefExternal resolved deep in the recursion builds URLs in the
        correct language without having to thread the parameter through
        every helper.
        """
        root = etree.fromstring(data)

        # Scope language context to this parse call.
        xml_lang = root.get(f"{{{XML_NS}}}lang", "en")
        lang = "fr" if xml_lang.startswith("fr") else "en"
        lang_token = _current_lang.set(lang)
        try:
            return self._parse_root(root)
        finally:
            _current_lang.reset(lang_token)

    def _parse_root(self, root: etree._Element) -> list[Any]:
        """Actual body parsing, run inside the language context.

        Handles three root element types:
        - ``Statute``/``Act`` — consolidated act (pit-date present)
        - ``Regulation`` — consolidated regulation
        - ``Bill`` — annual-statute amendment bill (BillHistory provides date;
          Introduction carries RECOMMENDATION/SUMMARY which we render as
          preamble-style quote blocks so the output shape stays uniform with
          consolidated commits)
        """
        root_tag = etree.QName(root).localname if isinstance(root.tag, str) else ""
        is_bill = root_tag == "Bill"

        # Publication date:
        # - modern consolidated XML (post-2016 upstream) carries
        #   ``lims:pit-date`` on the root.
        # - pre-2016 XML variants predate the lims namespace; they carry a
        #   ``startdate="YYYYMMDD"`` attribute instead.
        # - Bills carry the assent date in ``BillHistory/Stages[assented-to]``.
        pub_date = _parse_date(root.get(f"{{{LIMS_NS}}}pit-date", ""))
        if pub_date is None:
            startdate = root.get("startdate", "")
            if startdate and len(startdate) == 8:
                pub_date = _parse_date(f"{startdate[0:4]}-{startdate[4:6]}-{startdate[6:8]}")
        if pub_date is None and is_bill:
            pub_date = _bill_history_date(root, "assented-to")
        if pub_date is None:
            pub_date = date.today()

        paragraphs: list[Paragraph] = []

        # Preamble (before Body). Most acts use a preamble for enabling recitals.
        preamble_el = root.find("Preamble")
        if preamble_el is not None:
            preamble_text = _clean(_inline_text(preamble_el))
            if preamble_text:
                paragraphs.append(Paragraph(css_class="parrafo", text=f"> {preamble_text}"))

        # Root-level Introduction. For Statute/Regulation: contains <Enacts>
        # ("Her Majesty, by and with the advice…"). For Bill: contains
        # Recommendation + Summary that explain what the bill does.
        intro_el = root.find("Introduction")
        if intro_el is not None:
            if is_bill:
                paragraphs.extend(_parse_bill_introduction(intro_el))
            else:
                enacts_el = intro_el.find("Enacts")
                if enacts_el is not None:
                    for prov in enacts_el.findall("./Provision"):
                        paragraphs.extend(_parse_provision(prov))
                # Direct Text children of Introduction (rare, but defensive).
                for text_el in intro_el.findall("./Text"):
                    txt = _clean(_inline_text(text_el))
                    if txt:
                        paragraphs.append(Paragraph(css_class="parrafo", text=txt))

        # Body.
        body_el = root.find("Body")
        if body_el is not None:
            paragraphs.extend(_parse_body(body_el))

        # Schedules at root level (outside Body).
        for sched in root.findall("Schedule"):
            paragraphs.extend(_parse_schedule(sched))

        if not paragraphs:
            return []

        version = Version(
            norm_id="body",
            publication_date=pub_date,
            effective_date=pub_date,
            paragraphs=tuple(paragraphs),
        )
        return [
            Block(
                id="body",
                block_type="article",
                title="",  # Title comes from metadata, not the body.
                versions=(version,),
            )
        ]

    def parse_suvestine(
        self, suvestine_data: bytes, norm_id: str
    ) -> tuple[list[Block], list[Reform]]:
        """Parse a merged multi-source JSON blob into versioned Block + Reforms.

        Accepts the shape produced by :meth:`JusticeCanadaClient.get_suvestine`:

            {"versions": [
                {"source_type": "...", "source_id": "...",
                 "date": "YYYY-MM-DD", "xml": "<base64>", …},
                …
            ]}

        Each entry is parsed through ``_parse_root`` regardless of its
        ``source_type`` — the renderer already handles the three XML root
        element variants (``Statute``/``Regulation`` from git log and
        annual-statute's ``Bill``) uniformly.

        ``Reform.norm_id`` is set to ``source_id`` so the committer's
        ``(Source-Id, Norm-Id)`` dedupe key remains unique per historical
        event (a commit SHA, an annual-statute citation, a PIT snapshot
        date, or a Gazette PDF locator).

        Backward-compat: entries using the legacy ``sha`` key (from
        pre-merge suvestine blobs cached on disk) are still recognised.
        """
        if not suvestine_data:
            return [], []

        try:
            blob = json.loads(suvestine_data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Failed to decode suvestine blob for %s: %s", norm_id, exc)
            return [], []

        payload = blob.get("versions") or []
        if not payload:
            return [], []

        # Derive language once from norm_id and push it into the context so
        # every inline XRef resolves to the right official URL.
        _, _, url_lang, _ = _lang_info(norm_id)
        lang = "fr" if url_lang == "fra" else "en"
        lang_token = _current_lang.set(lang)

        versions: list[Version] = []
        reforms: list[Reform] = []

        # Memory hygiene: each iteration parses one XML through lxml, which
        # holds native C-level memory until the Element is deallocated. On
        # high-amendment acts (Criminal Code has 100+ versions) the
        # accumulated native memory is what pushes bootstrap peak RAM up —
        # see the Greek PR (commit b2e146e). We mirror the same pattern:
        # drop large intermediates at the end of each iteration, and force
        # a GC cycle every ``_GC_EVERY`` iterations.
        _GC_EVERY = 10
        try:
            for idx, entry in enumerate(payload):
                source_id = entry.get("source_id") or entry.get("sha", "")
                date_str = entry.get("date", "")
                if not (source_id and date_str):
                    continue

                try:
                    commit_date = date.fromisoformat(date_str)
                except ValueError:
                    logger.warning(
                        "Invalid date %r in suvestine for %s (%s); skipping",
                        date_str,
                        norm_id,
                        source_id,
                    )
                    continue

                source_type = entry.get("source_type", "")

                # Gazette-PDF branch: the entry carries pre-extracted plain
                # text (no XML) plus metadata. Wrap as amendment-event
                # paragraphs rather than going through _parse_root.
                if source_type == "gazette-pdf":
                    paragraphs = _render_gazette_body(entry)
                    if not paragraphs:
                        continue
                    versions.append(
                        Version(
                            norm_id=source_id,
                            publication_date=commit_date,
                            effective_date=commit_date,
                            paragraphs=paragraphs,
                        )
                    )
                    reforms.append(
                        Reform(
                            date=commit_date,
                            norm_id=source_id,
                            affected_blocks=("body",),
                        )
                    )
                    continue

                # PIT-HTML branch: Justice Canada's point-in-time HTML.
                # Delegates to pit_parser which emits the same Paragraph
                # shape as the XML parser so downstream rendering is
                # identical across source_types.
                if source_type == "pit-html":
                    from legalize.fetcher.ca.pit_parser import parse_pit_html

                    html_b64 = entry.pop("body_html", "")
                    if not html_b64:
                        continue
                    try:
                        html_bytes = base64.b64decode(html_b64)
                    except (ValueError, TypeError) as exc:
                        logger.warning(
                            "Could not decode PIT HTML for %s (%s): %s",
                            norm_id,
                            source_id,
                            exc,
                        )
                        continue
                    del html_b64
                    pit_paragraphs = tuple(parse_pit_html(html_bytes, lang=lang))
                    del html_bytes
                    if not pit_paragraphs:
                        continue
                    versions.append(
                        Version(
                            norm_id=source_id,
                            publication_date=commit_date,
                            effective_date=commit_date,
                            paragraphs=pit_paragraphs,
                        )
                    )
                    reforms.append(
                        Reform(
                            date=commit_date,
                            norm_id=source_id,
                            affected_blocks=("body",),
                        )
                    )
                    if (idx + 1) % _GC_EVERY == 0:
                        gc.collect()
                    continue

                # XML branch: upstream-git / annual-statute.
                # ``pop`` instead of ``get`` — the base64 string (often
                # MBs per entry on big acts) is released from the dict as
                # soon as we decode it, avoiding a duplicate copy hanging
                # around in ``payload`` for the rest of the loop.
                xml_b64 = entry.pop("xml", "")
                if not xml_b64:
                    continue

                try:
                    xml_bytes = base64.b64decode(xml_b64)
                except (ValueError, TypeError) as exc:
                    logger.warning(
                        "Could not decode base64 XML for %s (%s): %s",
                        norm_id,
                        source_id,
                        exc,
                    )
                    del xml_b64
                    continue
                del xml_b64  # ~MB-scale string — release ASAP

                try:
                    root = etree.fromstring(xml_bytes)
                except etree.XMLSyntaxError as exc:
                    logger.warning(
                        "Invalid XML in suvestine for %s (%s): %s",
                        norm_id,
                        source_id,
                        exc,
                    )
                    del xml_bytes
                    continue
                del xml_bytes  # lxml has copied it into the tree

                blocks = self._parse_root(root)
                if not blocks:
                    # Empty body (minimal/placeholder) — skip this version.
                    del root
                    continue
                paragraphs = blocks[0].versions[0].paragraphs

                # Effective date: prefer XML's pit-date (consolidated, post-
                # 2016) or startdate (pre-2016 XML) or assent date (bill);
                # fall back to the event date itself.
                pit = _parse_date(root.get(f"{{{LIMS_NS}}}pit-date", ""))
                if pit is None:
                    startdate = root.get("startdate", "")
                    if startdate and len(startdate) == 8:
                        pit = _parse_date(f"{startdate[0:4]}-{startdate[4:6]}-{startdate[6:8]}")
                effective = pit or _bill_history_date(root, "assented-to") or commit_date

                versions.append(
                    Version(
                        norm_id=source_id,
                        publication_date=commit_date,
                        effective_date=effective,
                        paragraphs=paragraphs,
                    )
                )
                reforms.append(
                    Reform(
                        date=commit_date,
                        norm_id=source_id,
                        affected_blocks=("body",),
                    )
                )
                # Release the parsed tree + transient block list BEFORE the
                # next iteration allocates its own copies. lxml's native
                # memory is only reclaimed on Python GC; without this
                # sweep the per-law peak scales linearly with version count.
                del root, blocks
                if (idx + 1) % _GC_EVERY == 0:
                    gc.collect()
        finally:
            _current_lang.reset(lang_token)
            # Final sweep to ensure lxml releases every tree before the
            # pipeline moves to the next norm — otherwise a worker thread
            # hands the accumulated native memory to the next law it picks.
            gc.collect()

        if not versions:
            return [], []

        block = Block(
            id="body",
            block_type="article",
            title="",
            versions=tuple(versions),
        )
        return [block], reforms

    def parse_suvestine_stream(
        self, entries: Iterable[dict], norm_id: str
    ) -> tuple[list[Block], list[Reform]]:
        """Streaming counterpart to :meth:`parse_suvestine`.

        Consumes an iterable of entry dicts (the shape produced by
        :meth:`JusticeCanadaClient.iter_suvestine`) and parses each one in
        turn into a Version + Reform pair. Crucially, we never hold more
        than the currently-processed entry's XML in memory — the
        generator yielded by the client is drained lazily and each
        entry's big base64 string / bytes / lxml tree is dropped before
        the next one is loaded.

        The assembled ``versions`` + ``reforms`` lists still accumulate
        for the final Block, but those hold only parsed Paragraph tuples
        (strings) which are 10-20× smaller than the source XMLs they
        came from.

        Memory win vs ``parse_suvestine``:

        - no JSON blob is ever materialised (saves ~272 MB on Criminal
          Code);
        - no intermediate ``all_versions``/``deduped`` list in the
          client (saves ~200 MB);
        - only one entry's XML is resident at a time (saves ~100 MB).

        Dispatch on ``source_type`` matches :meth:`parse_suvestine` —
        ``upstream-git``/``annual-statute`` go through :meth:`_parse_root`,
        ``pit-html`` through :func:`pit_parser.parse_pit_html`, and
        ``gazette-pdf`` through :func:`_render_gazette_body`.
        """
        _, _, url_lang, _ = _lang_info(norm_id)
        lang = "fr" if url_lang == "fra" else "en"
        lang_token = _current_lang.set(lang)

        versions: list[Version] = []
        reforms: list[Reform] = []
        _GC_EVERY = 10

        try:
            for idx, entry in enumerate(entries):
                version, reform = self._parse_suvestine_entry(entry, norm_id)
                if version is not None and reform is not None:
                    versions.append(version)
                    reforms.append(reform)
                del entry
                if (idx + 1) % _GC_EVERY == 0:
                    gc.collect()
        finally:
            _current_lang.reset(lang_token)
            gc.collect()

        if not versions:
            return [], []

        block = Block(
            id="body",
            block_type="article",
            title="",
            versions=tuple(versions),
        )
        return [block], reforms

    def _parse_suvestine_entry(
        self, entry: dict, norm_id: str
    ) -> tuple[Version | None, Reform | None]:
        """Decode + render one suvestine entry.

        Separated from the streaming loop so both parse paths
        (``parse_suvestine`` and ``parse_suvestine_stream``) share the
        same per-entry semantics. Returns ``(None, None)`` when the
        entry is unusable (missing required fields, XML parse error,
        empty body) so the caller can skip it without special-casing.
        """
        source_id = entry.get("source_id") or entry.get("sha", "")
        date_str = entry.get("date", "")
        if not (source_id and date_str):
            return None, None

        try:
            commit_date = date.fromisoformat(date_str)
        except ValueError:
            logger.warning(
                "Invalid date %r in suvestine for %s (%s); skipping",
                date_str,
                norm_id,
                source_id,
            )
            return None, None

        source_type = entry.get("source_type", "")

        if source_type == "gazette-pdf":
            paragraphs = _render_gazette_body(entry)
            if not paragraphs:
                return None, None
            return (
                Version(
                    norm_id=source_id,
                    publication_date=commit_date,
                    effective_date=commit_date,
                    paragraphs=paragraphs,
                ),
                Reform(date=commit_date, norm_id=source_id, affected_blocks=("body",)),
            )

        if source_type == "pit-html":
            from legalize.fetcher.ca.pit_parser import parse_pit_html

            html_b64 = entry.pop("body_html", "")
            if not html_b64:
                return None, None
            try:
                html_bytes = base64.b64decode(html_b64)
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "Could not decode PIT HTML for %s (%s): %s",
                    norm_id,
                    source_id,
                    exc,
                )
                return None, None
            del html_b64
            pit_paragraphs = tuple(parse_pit_html(html_bytes, lang=_current_lang.get()))
            del html_bytes
            if not pit_paragraphs:
                return None, None
            return (
                Version(
                    norm_id=source_id,
                    publication_date=commit_date,
                    effective_date=commit_date,
                    paragraphs=pit_paragraphs,
                ),
                Reform(date=commit_date, norm_id=source_id, affected_blocks=("body",)),
            )

        xml_b64 = entry.pop("xml", "")
        if not xml_b64:
            return None, None

        try:
            xml_bytes = base64.b64decode(xml_b64)
        except (ValueError, TypeError) as exc:
            logger.warning(
                "Could not decode base64 XML for %s (%s): %s",
                norm_id,
                source_id,
                exc,
            )
            return None, None
        del xml_b64

        try:
            root = etree.fromstring(xml_bytes)
        except etree.XMLSyntaxError as exc:
            logger.warning("Invalid XML in suvestine for %s (%s): %s", norm_id, source_id, exc)
            return None, None
        del xml_bytes

        blocks = self._parse_root(root)
        if not blocks:
            del root
            return None, None
        paragraphs = blocks[0].versions[0].paragraphs

        pit = _parse_date(root.get(f"{{{LIMS_NS}}}pit-date", ""))
        if pit is None:
            startdate = root.get("startdate", "")
            if startdate and len(startdate) == 8:
                pit = _parse_date(f"{startdate[0:4]}-{startdate[4:6]}-{startdate[6:8]}")
        effective = pit or _bill_history_date(root, "assented-to") or commit_date

        del root, blocks
        return (
            Version(
                norm_id=source_id,
                publication_date=commit_date,
                effective_date=effective,
                paragraphs=paragraphs,
            ),
            Reform(date=commit_date, norm_id=source_id, affected_blocks=("body",)),
        )


# ---------------------------------------------------------------------------
# MetadataParser
# ---------------------------------------------------------------------------


# norm_id prefix → (language code, jurisdiction, URL path segment, category label)
# Maps the upstream directory layout to the output jurisdiction. Canada's two
# official languages are constitutionally equal, so we treat them symmetrically
# rather than privileging English as ``ca/``.
_LANG_MAP = {
    "eng/acts": ("en", "ca-en", "eng", "acts"),
    "eng/regulations": ("en", "ca-en", "eng", "regulations"),
    "fra/lois": ("fr", "ca-fr", "fra", "lois"),
    "fra/reglements": ("fr", "ca-fr", "fra", "reglements"),
}


def _lang_info(norm_id: str) -> tuple[str, str, str, str]:
    """Return ``(lang_code, jurisdiction, url_lang, category)`` for a norm_id."""
    for prefix, info in _LANG_MAP.items():
        if norm_id.startswith(prefix + "/"):
            return info
    # Fallback: assume English acts. Keeps us from crashing on malformed IDs.
    return _LANG_MAP["eng/acts"]


def _bill_history_date(root: etree._Element, stage: str) -> date | None:
    """Return the date of a specific BillHistory stage (e.g. 'assented-to')."""
    for stages_el in root.findall(".//BillHistory/Stages"):
        if stages_el.get("stage") != stage:
            continue
        date_el = stages_el.find("./Date")
        if date_el is None:
            continue
        yyyy = date_el.findtext("YYYY", "").strip()
        mm = date_el.findtext("MM", "").strip()
        dd = date_el.findtext("DD", "").strip()
        if yyyy and mm and dd:
            try:
                return date(int(yyyy), int(mm), int(dd))
            except ValueError:
                return None
    return None


def _annual_statute_citation(root: etree._Element) -> str:
    """Return the as-enacted citation like '1995, c. 17' from AnnualStatuteId."""
    asid = root.find(".//AnnualStatuteId")
    if asid is None:
        return ""
    year = asid.findtext("YYYY", "").strip()
    chapter = asid.findtext("AnnualStatuteNumber", "").strip()
    if year and chapter:
        return f"{year}, c. {chapter}"
    return ""


class CAMetadataParser(MetadataParser):
    """Extracts NormMetadata from Justice Canada XML.

    Captures every field exposed by the source (see RESEARCH-CA.md §0.3):
    LongTitle → summary, RunningHead → short_title, AnnualStatuteId →
    as-enacted citation, BillHistory stages → assent + consolidation dates,
    ConsolidatedNumber / InstrumentNumber attributes, lims:id / lims:fid, etc.
    """

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        root = etree.fromstring(data)
        root_tag = etree.QName(root).localname if isinstance(root.tag, str) else root.tag

        # Rank from root tag (Statute/Act vs Regulation).
        is_act = root_tag in ("Statute", "Act")
        rank_str = "act" if is_act else "regulation"

        # Language / jurisdiction from the norm_id prefix (eng/... vs fra/...).
        lang_code, jurisdiction, url_lang, _category = _lang_info(norm_id)

        # Titles. ShortTitle is the canonical citation title. RunningHead is
        # the abbreviated form shown in headers (used as short_title). LongTitle
        # is the "An Act to do X..." descriptive title — preserved as summary.
        # Use _plain_text: frontmatter is YAML; markdown links inside title
        # strings would be noisy for downstream consumers.
        short_title_el = root.find(".//ShortTitle")
        long_title_el = root.find(".//LongTitle")
        running_head_el = root.find(".//RunningHead")
        title = _plain_text(short_title_el) if short_title_el is not None else ""
        long_title = _plain_text(long_title_el) if long_title_el is not None else ""
        running_head = _plain_text(running_head_el) if running_head_el is not None else ""
        # Fall back through the chain if ShortTitle is missing.
        if not title:
            title = long_title or running_head

        # short_title prefers RunningHead (compact), then ShortTitle, then title.
        short_title = running_head or title

        # Identifier from norm_id tail. Shared across languages (the French
        # version of A-1 has identifier "A-1"); jurisdiction disambiguates.
        file_id = norm_id.rsplit("/", 1)[-1]
        identifier = file_id.replace("/", "-").replace(" ", "-")

        # Dates.
        pit_date = _parse_date(root.get(f"{{{LIMS_NS}}}pit-date", ""))
        last_amended = _parse_date(root.get(f"{{{LIMS_NS}}}lastAmendedDate", ""))
        inforce_start = _parse_date(root.get(f"{{{LIMS_NS}}}inforce-start-date", ""))
        pub_date = pit_date or last_amended or date.today()

        # Assent date (real-world legal milestone: when the bill was signed).
        assent_date = _bill_history_date(root, "assented-to")

        # Status.
        in_force_attr = root.get("in-force", "yes")
        status = NormStatus.IN_FORCE if in_force_attr == "yes" else NormStatus.REPEALED

        # Department / enabling authority. For regulations, EnablingAuthority
        # names (and may link to) the parent act. We store the human-readable
        # name as ``department`` (plain text — no markdown) and the linked
        # identifier separately in ``extra.enabling_authority_id`` so
        # programmatic consumers can resolve the relationship.
        enabling = root.find(".//EnablingAuthority")
        department = "Parliament of Canada"
        enabling_link_id = ""
        if enabling is not None:
            enabling_text = _plain_text(enabling)
            if enabling_text:
                department = enabling_text
            xref = enabling.find(".//XRefExternal")
            if xref is not None:
                enabling_link_id = xref.get("link", "").strip()

        # Source URL on the official Justice Laws Website, matching language.
        source_category = "acts" if is_act else "regulations"
        if url_lang == "fra":
            source_category = "lois" if is_act else "reglements"
        source_url = f"https://laws-lois.justice.gc.ca/{url_lang}/{source_category}/{file_id}/"

        # Extra metadata (every field the source exposes).
        extra: list[tuple[str, str]] = []
        extra.append(("lang", lang_code))

        if long_title:
            # Capture the "An Act to..." descriptive title even when we used
            # ShortTitle for the main title. Truncate defensively.
            extra.append(("long_title", long_title[:500]))

        if last_amended:
            extra.append(("last_amended", last_amended.isoformat()))
        if inforce_start:
            extra.append(("inforce_start", inforce_start.isoformat()))
        if assent_date:
            extra.append(("assented_to", assent_date.isoformat()))

        current_date = root.get(f"{{{LIMS_NS}}}current-date", "")
        if current_date:
            extra.append(("consolidation_date", current_date))

        has_prev = root.get("hasPreviousVersion", "")
        if has_prev:
            extra.append(("has_previous_version", has_prev))

        bill_origin = root.get("bill-origin", "")
        if bill_origin:
            extra.append(("bill_origin", bill_origin))

        bill_type = root.get("bill-type", "")
        if bill_type:
            extra.append(("bill_type", bill_type))

        fid = root.get(f"{{{LIMS_NS}}}fid", "")
        if fid:
            extra.append(("fid", fid))

        lims_id = root.get(f"{{{LIMS_NS}}}id", "")
        if lims_id:
            extra.append(("lims_id", lims_id))

        # As-enacted citation (year + chapter number from annual statutes).
        annual_cit = _annual_statute_citation(root)
        if annual_cit:
            extra.append(("annual_statute", annual_cit))

        # Consolidated number attributes (e.g., ``official="yes"``).
        consolidated_el = root.find(".//ConsolidatedNumber")
        if consolidated_el is not None and consolidated_el.text:
            cn_text = consolidated_el.text.strip()
            if cn_text and cn_text != file_id:
                extra.append(("consolidated_number", cn_text))
            cn_official = consolidated_el.get("official", "")
            if cn_official:
                extra.append(("consolidated_number_official", cn_official))

        # Regulation-specific: InstrumentNumber (e.g., "SOR/99-129").
        instrument_el = root.find(".//InstrumentNumber")
        if instrument_el is not None:
            inst_text = _plain_text(instrument_el)
            if inst_text:
                extra.append(("instrument_number", inst_text))

        # Enabling act link (regulations only).
        if enabling_link_id:
            extra.append(("enabling_authority_id", enabling_link_id))

        return NormMetadata(
            title=title or identifier,
            short_title=short_title or title or identifier,
            identifier=identifier,
            country="ca",
            rank=Rank(rank_str),
            publication_date=pub_date,
            status=status,
            department=department,
            source=source_url,
            jurisdiction=jurisdiction,
            last_modified=last_amended,
            summary=long_title,
            extra=tuple(extra),
        )
