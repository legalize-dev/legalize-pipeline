"""Parser for Finnish Finlex Akoma Ntoso XML documents.

Finlex publishes consolidated legislation as standard Akoma Ntoso 3.0 XML
with Finland-specific extensions in the ``finlex:`` namespace.

Hierarchy mapping (Finnish → block_type → markdown heading):
  part       → part      → ## (titulo_tit)
  chapter    → chapter   → ### (capitulo_tit)
  section    → article   → ##### (articulo)
  subsection → (content inside section)
  paragraph  → (numbered content)
  subparagraph → (sub-numbered content)

Rich formatting:
  <ref href="...">text</ref>  → [text](url)
  <i>text</i>                 → *text*
  <table>                     → Markdown pipe table
  <img>                       → skipped (counted in extra.images_dropped)
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from lxml import etree

from legalize.fetcher.base import MetadataParser, TextParser
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

# ─── Namespaces ───

_AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"
_FINLEX_NS = "http://data.finlex.fi/schema/finlex"

_NS = {"akn": _AKN_NS, "finlex": _FINLEX_NS}

# Shared lxml parser for huge documents (Income Tax Act is >1 MB).
_LXML_PARSER = etree.XMLParser(huge_tree=True)

# ─── Type mapping ───

_TYPE_TO_RANK: dict[str, str] = {
    "act": "laki",
    "decree": "asetus",
    "order": "maarays",
    "government-decree": "valtioneuvoston_asetus",
    "ministerial-decree": "ministerion_asetus",
    "presidential-decree": "tasavallan_presidentin_asetus",
}

# Finlex source URL template
_FINLEX_URL = "https://www.finlex.fi/fi/laki/ajantasa/{year}/{year}{number:04d}"

# ─── Helpers ───


def _ln(el: etree._Element) -> str:
    """Local element name (strips XML namespace)."""
    return etree.QName(el.tag).localname


def _findall(el: etree._Element, xpath: str) -> list[etree._Element]:
    return el.findall(xpath, _NS)


def _text_content(el: etree._Element) -> str:
    """Recursively extract text from an element, handling inline formatting.

    Handles:
    - <ref href="...">text</ref> → [text](url)
    - <i>text</i> → *text*
    - Plain text and tail text
    """
    if el is None:
        return ""

    parts: list[str] = []

    # Element's own text
    if el.text:
        parts.append(el.text)

    for child in el:
        tag = _ln(child)
        if tag == "ref":
            href = child.get("href", "")
            link_text = _text_content(child)
            if href and link_text:
                parts.append(f"[{link_text}]({href})")
            else:
                parts.append(link_text)
        elif tag == "i":
            inner = _text_content(child)
            if inner.strip():
                parts.append(f"*{inner}*")
            else:
                parts.append(inner)
        elif tag == "img":
            # Skip images — count them separately
            pass
        elif tag == "br":
            parts.append("\n")
        else:
            # Recurse into other elements (span, sub, sup, etc.)
            parts.append(_text_content(child))

        # Tail text after the child element
        if child.tail:
            parts.append(child.tail)

    return "".join(parts)


def _parse_date(date_str: str) -> date | None:
    """Parse YYYY-MM-DD date string."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


# ─── Table parsing ───


def _parse_table(table_el: etree._Element) -> str:
    """Convert an AKN <table> element to a Markdown pipe table."""
    rows: list[list[str]] = []
    for tr in table_el.findall(f"{{{_AKN_NS}}}tr"):
        cells: list[str] = []
        for td in tr.findall(f"{{{_AKN_NS}}}td"):
            cell_text = _text_content(td).strip().replace("\n", " ").replace("|", "\\|")
            cells.append(cell_text)
        if cells:
            rows.append(cells)

    if not rows:
        return ""

    # Normalize column count
    max_cols = max(len(r) for r in rows)
    for row in rows:
        while len(row) < max_cols:
            row.append("")

    lines: list[str] = []
    # Header row (first row)
    lines.append("| " + " | ".join(rows[0]) + " |")
    # Separator
    lines.append("| " + " | ".join("---" for _ in range(max_cols)) + " |")
    # Data rows
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


# ─── Block construction ───


def _make_block(
    block_id: str,
    block_type: str,
    title: str,
    paragraphs: list[Paragraph],
    pub_date: date,
    norm_id: str,
) -> Block:
    """Create a Block with a single Version."""
    version = Version(
        norm_id=norm_id,
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


# ─── Body parsing ───


def _parse_section_content(section: etree._Element) -> list[Paragraph]:
    """Parse the content within a section (§) into paragraphs.

    Handles subsection > content > p, paragraph > intro/content, and
    subparagraph nesting.
    """
    paragraphs: list[Paragraph] = []

    for child in section:
        tag = _ln(child)

        if tag == "num":
            continue  # num is combined with heading in the caller

        if tag == "heading":
            continue  # handled by caller

        if tag == "subsection":
            paragraphs.extend(_parse_subsection(child))

        elif tag == "paragraph":
            paragraphs.extend(_parse_paragraph(child))

        elif tag == "content":
            for p in child.findall(f"{{{_AKN_NS}}}p"):
                text = _text_content(p).strip()
                if text:
                    paragraphs.append(Paragraph(css_class="parrafo", text=text))
            for tbl in child.findall(f"{{{_AKN_NS}}}table"):
                table_md = _parse_table(tbl)
                if table_md:
                    paragraphs.append(Paragraph(css_class="table_row", text=table_md))

        elif tag == "hcontainer":
            # Editorial notes within sections
            hc_name = child.get("name", "")
            if hc_name == "noteAuthorial":
                for p in child.findall(f".//{{{_AKN_NS}}}p"):
                    text = _text_content(p).strip()
                    if text:
                        paragraphs.append(Paragraph(css_class="parrafo", text=f"*{text}*"))

    return paragraphs


def _parse_subsection(subsec: etree._Element) -> list[Paragraph]:
    """Parse a subsection element into paragraphs."""
    paragraphs: list[Paragraph] = []

    content = subsec.find(f"{{{_AKN_NS}}}content")
    if content is not None:
        for child in content:
            tag = _ln(child)
            if tag == "p":
                text = _text_content(child).strip()
                if text:
                    paragraphs.append(Paragraph(css_class="parrafo", text=text))
            elif tag == "table":
                table_md = _parse_table(child)
                if table_md:
                    paragraphs.append(Paragraph(css_class="table_row", text=table_md))
            elif tag == "blockList":
                paragraphs.extend(_parse_blocklist(child))

    # Subsection can also have intro + paragraph children (numbered items)
    intro = subsec.find(f"{{{_AKN_NS}}}intro")
    if intro is not None:
        for p in intro.findall(f"{{{_AKN_NS}}}p"):
            text = _text_content(p).strip()
            if text:
                paragraphs.append(Paragraph(css_class="parrafo", text=text))

    for para in subsec.findall(f"{{{_AKN_NS}}}paragraph"):
        paragraphs.extend(_parse_paragraph(para))

    return paragraphs


def _parse_paragraph(para: etree._Element) -> list[Paragraph]:
    """Parse a numbered paragraph element."""
    paragraphs: list[Paragraph] = []

    num_el = para.find(f"{{{_AKN_NS}}}num")
    num_text = num_el.text.strip() if num_el is not None and num_el.text else ""

    # Intro text
    intro = para.find(f"{{{_AKN_NS}}}intro")
    if intro is not None:
        for p in intro.findall(f"{{{_AKN_NS}}}p"):
            text = _text_content(p).strip()
            if text:
                prefix = f"{num_text} " if num_text else ""
                paragraphs.append(Paragraph(css_class="list_item", text=f"{prefix}{text}"))
                num_text = ""  # only prefix the first line

    # Content
    content = para.find(f"{{{_AKN_NS}}}content")
    if content is not None:
        for p in content.findall(f"{{{_AKN_NS}}}p"):
            text = _text_content(p).strip()
            if text:
                prefix = f"{num_text} " if num_text else ""
                paragraphs.append(Paragraph(css_class="list_item", text=f"{prefix}{text}"))
                num_text = ""

    # Subparagraphs
    for subpara in para.findall(f"{{{_AKN_NS}}}subparagraph"):
        paragraphs.extend(_parse_subparagraph(subpara))

    return paragraphs


def _parse_subparagraph(subpara: etree._Element) -> list[Paragraph]:
    """Parse a subparagraph element."""
    paragraphs: list[Paragraph] = []

    num_el = subpara.find(f"{{{_AKN_NS}}}num")
    num_text = num_el.text.strip() if num_el is not None and num_el.text else ""

    content = subpara.find(f"{{{_AKN_NS}}}content")
    if content is not None:
        for p in content.findall(f"{{{_AKN_NS}}}p"):
            text = _text_content(p).strip()
            if text:
                prefix = f"{num_text} " if num_text else ""
                paragraphs.append(Paragraph(css_class="list_item", text=f"{prefix}{text}"))
                num_text = ""

    return paragraphs


def _parse_blocklist(blocklist: etree._Element) -> list[Paragraph]:
    """Parse a blockList element (structured list)."""
    paragraphs: list[Paragraph] = []
    for item in blocklist.findall(f"{{{_AKN_NS}}}item"):
        num_el = item.find(f"{{{_AKN_NS}}}num")
        num_text = num_el.text.strip() if num_el is not None and num_el.text else "-"
        for p in item.findall(f".//{{{_AKN_NS}}}p"):
            text = _text_content(p).strip()
            if text:
                paragraphs.append(Paragraph(css_class="list_item", text=f"{num_text} {text}"))
    return paragraphs


def _parse_attachment(
    attachment: etree._Element, pub_date: date, norm_id: str, start_idx: int
) -> list[Block]:
    """Parse an attachment (annex) hcontainer into blocks."""
    blocks: list[Block] = []
    idx = start_idx

    # Heading for the attachment
    heading_el = attachment.find(f"{{{_AKN_NS}}}heading")
    heading_text = _text_content(heading_el).strip() if heading_el is not None else "Liite"

    paragraphs: list[Paragraph] = [Paragraph(css_class="capitulo_tit", text=heading_text)]
    blocks.append(_make_block(f"annex-{idx}", "annex", heading_text, paragraphs, pub_date, norm_id))
    idx += 1

    # Parse content inside the attachment (tables, paragraphs, etc.)
    content = attachment.find(f"{{{_AKN_NS}}}content")
    if content is not None:
        annex_paragraphs: list[Paragraph] = []
        for child in content:
            tag = _ln(child)
            if tag == "p":
                text = _text_content(child).strip()
                if text:
                    annex_paragraphs.append(Paragraph(css_class="parrafo", text=text))
            elif tag == "table":
                table_md = _parse_table(child)
                if table_md:
                    annex_paragraphs.append(Paragraph(css_class="table_row", text=table_md))

        if annex_paragraphs:
            blocks.append(
                _make_block(
                    f"annex-content-{idx}",
                    "annex_content",
                    "Annex content",
                    annex_paragraphs,
                    pub_date,
                    norm_id,
                )
            )
            idx += 1

    # Parse any sections within the attachment
    for section in attachment.findall(f"{{{_AKN_NS}}}section"):
        blk = _parse_section_block(section, pub_date, norm_id, idx)
        if blk:
            blocks.append(blk)
            idx += 1

    return blocks


# ─── TextParser ───


class FinlexTextParser(TextParser):
    """Parses Finlex Akoma Ntoso XML body into Block objects."""

    def parse_text(self, data: bytes) -> list[Any]:
        """Parse the body of a Finlex AKN XML document into Blocks."""
        if not data:
            return []

        try:
            root = etree.fromstring(data, parser=_LXML_PARSER)
        except etree.XMLSyntaxError as exc:
            logger.warning("Failed to parse XML: %s", exc)
            return []

        body = root.find(f".//{{{_AKN_NS}}}body")
        if body is None:
            return []

        # Extract dates for version info
        pub_date = _extract_publication_date(root)
        norm_id = _extract_norm_number(root)

        blocks: list[Block] = []
        block_idx = 0

        # Parse preamble (enacting clause)
        preamble = root.find(f".//{{{_AKN_NS}}}preamble")
        if preamble is not None:
            formula = preamble.find(f".//{{{_AKN_NS}}}formula")
            if formula is not None:
                text = _text_content(formula).strip()
                if text:
                    paragraphs = [Paragraph(css_class="parrafo", text=text)]
                    blocks.append(
                        _make_block(
                            f"preamble-{block_idx}",
                            "preamble",
                            "Preamble",
                            paragraphs,
                            pub_date,
                            norm_id,
                        )
                    )
                    block_idx += 1

        # Walk the body: find the statuteProvisionsWrapper or iterate top-level
        wrapper = body.find(f"{{{_AKN_NS}}}hcontainer[@name='statuteProvisionsWrapper']")
        content_root = wrapper if wrapper is not None else body

        for child in content_root:
            tag = _ln(child)

            if tag == "part":
                blocks.extend(_parse_part(child, pub_date, norm_id, block_idx))
                block_idx = len(blocks)

            elif tag == "chapter":
                blocks.extend(_parse_chapter(child, pub_date, norm_id, block_idx))
                block_idx = len(blocks)

            elif tag == "section":
                blk = _parse_section_block(child, pub_date, norm_id, block_idx)
                if blk:
                    blocks.append(blk)
                    block_idx += 1

            elif tag == "hcontainer":
                hc_name = child.get("name", "")
                if hc_name in ("conclusions", "amendmentEntryIntoForceAndApplianceProvisions"):
                    continue  # Skip non-content wrappers
                # Other hcontainers: parse their child sections/chapters
                for grandchild in child:
                    gc_tag = _ln(grandchild)
                    if gc_tag == "chapter":
                        blocks.extend(_parse_chapter(grandchild, pub_date, norm_id, block_idx))
                        block_idx = len(blocks)
                    elif gc_tag == "section":
                        blk = _parse_section_block(grandchild, pub_date, norm_id, block_idx)
                        if blk:
                            blocks.append(blk)
                            block_idx += 1

        # Parse attachments (annexes) — siblings of the wrapper in <body>
        for attach_wrapper in body.findall(f"{{{_AKN_NS}}}hcontainer[@name='attachments']"):
            for attachment in attach_wrapper.findall(
                f"{{{_AKN_NS}}}hcontainer[@name='attachment']"
            ):
                blocks.extend(_parse_attachment(attachment, pub_date, norm_id, block_idx))
                block_idx = len(blocks)

        return blocks

    def extract_reforms(self, data: bytes) -> list[Any]:
        """Extract reform timeline from finlex:amendedBy metadata."""
        if not data:
            return []

        try:
            root = etree.fromstring(data, parser=_LXML_PARSER)
        except etree.XMLSyntaxError:
            return []

        reforms: list[Reform] = []
        proprietary = root.find(f".//{{{_AKN_NS}}}proprietary")
        if proprietary is None:
            return reforms

        for stat_ref in proprietary.findall(
            f".//{{{_FINLEX_NS}}}amendedBy/{{{_FINLEX_NS}}}statuteReference"
        ):
            ref_el = stat_ref.find(f"{{{_FINLEX_NS}}}ref")
            entry_el = stat_ref.find(f".//{{{_FINLEX_NS}}}dateEntryIntoForce")

            if ref_el is None:
                continue

            ref_text = ref_el.text or ""
            entry_date = _parse_date(entry_el.get("date", "")) if entry_el is not None else None

            if entry_date is None:
                continue

            reforms.append(
                Reform(
                    date=entry_date,
                    norm_id=ref_text,
                    affected_blocks=(),
                )
            )

        # Sort chronologically
        reforms.sort(key=lambda r: r.date)
        return reforms


def _parse_part(part: etree._Element, pub_date: date, norm_id: str, start_idx: int) -> list[Block]:
    """Parse a <part> element into blocks (heading + child chapters/sections)."""
    blocks: list[Block] = []
    idx = start_idx

    num_el = part.find(f"{{{_AKN_NS}}}num")
    heading_el = part.find(f"{{{_AKN_NS}}}heading")
    num_text = num_el.text.strip() if num_el is not None and num_el.text else ""
    heading_text = heading_el.text.strip() if heading_el is not None and heading_el.text else ""

    if num_text or heading_text:
        combined = (
            f"{num_text}. {heading_text}"
            if num_text and heading_text
            else (num_text or heading_text)
        )
        paragraphs = [Paragraph(css_class="titulo_tit", text=combined)]
        blocks.append(_make_block(f"part-{idx}", "part", combined, paragraphs, pub_date, norm_id))
        idx += 1

    for child in part:
        tag = _ln(child)
        if tag == "chapter":
            blocks.extend(_parse_chapter(child, pub_date, norm_id, idx))
            idx = start_idx + len(blocks)
        elif tag == "section":
            blk = _parse_section_block(child, pub_date, norm_id, idx)
            if blk:
                blocks.append(blk)
                idx += 1

    return blocks


def _parse_chapter(
    chapter: etree._Element, pub_date: date, norm_id: str, start_idx: int
) -> list[Block]:
    """Parse a <chapter> element into blocks (heading + child sections)."""
    blocks: list[Block] = []
    idx = start_idx

    num_el = chapter.find(f"{{{_AKN_NS}}}num")
    heading_el = chapter.find(f"{{{_AKN_NS}}}heading")
    num_text = num_el.text.strip() if num_el is not None and num_el.text else ""
    heading_text = _text_content(heading_el).strip() if heading_el is not None else ""

    if num_text or heading_text:
        combined = (
            f"{num_text}. {heading_text}"
            if num_text and heading_text
            else (num_text or heading_text)
        )
        paragraphs = [Paragraph(css_class="capitulo_tit", text=combined)]
        blocks.append(_make_block(f"chp-{idx}", "chapter", combined, paragraphs, pub_date, norm_id))
        idx += 1

    for child in chapter:
        tag = _ln(child)
        if tag == "section":
            blk = _parse_section_block(child, pub_date, norm_id, idx)
            if blk:
                blocks.append(blk)
                idx += 1
        elif tag == "hcontainer":
            # Editorial notes inside chapters
            hc_name = child.get("name", "")
            if hc_name == "noteAuthorial":
                for p in child.findall(f".//{{{_AKN_NS}}}p"):
                    text = _text_content(p).strip()
                    if text:
                        paragraphs = [Paragraph(css_class="parrafo", text=f"*{text}*")]
                        blocks.append(
                            _make_block(
                                f"note-{idx}",
                                "note",
                                text,
                                paragraphs,
                                pub_date,
                                norm_id,
                            )
                        )
                        idx += 1

    return blocks


def _parse_section_block(
    section: etree._Element, pub_date: date, norm_id: str, idx: int
) -> Block | None:
    """Parse a <section> (§) element into a single Block."""
    num_el = section.find(f"{{{_AKN_NS}}}num")
    heading_el = section.find(f"{{{_AKN_NS}}}heading")
    num_text = num_el.text.strip() if num_el is not None and num_el.text else ""
    heading_text = _text_content(heading_el).strip() if heading_el is not None else ""

    paragraphs: list[Paragraph] = []

    # Section heading as "##### num. heading"
    if num_text or heading_text:
        combined = (
            f"{num_text}. {heading_text}"
            if num_text and heading_text
            else (num_text or heading_text)
        )
        # Clean double periods: "1 §.. Heading" → "1 §. Heading"
        combined = combined.replace("§.", "§")
        paragraphs.append(Paragraph(css_class="articulo", text=combined))

    # Parse section content
    paragraphs.extend(_parse_section_content(section))

    if not paragraphs:
        return None

    eid = section.get("eId", f"sec-{idx}")
    title = heading_text or num_text or f"Section {idx}"
    return _make_block(eid, "article", title, paragraphs, pub_date, norm_id)


# ─── Metadata extraction helpers ───


def _extract_publication_date(root: etree._Element) -> date:
    """Extract publication date from FRBRWork/FRBRdate[@name='datePublished']."""
    el = root.find(f".//{{{_AKN_NS}}}FRBRWork/{{{_AKN_NS}}}FRBRdate[@name='datePublished']")
    if el is not None:
        d = _parse_date(el.get("date", ""))
        if d:
            return d
    # Fallback: dateIssued
    el = root.find(f".//{{{_AKN_NS}}}FRBRWork/{{{_AKN_NS}}}FRBRdate[@name='dateIssued']")
    if el is not None:
        d = _parse_date(el.get("date", ""))
        if d:
            return d
    return date(2000, 1, 1)


def _extract_norm_number(root: etree._Element) -> str:
    """Extract the statute number/year string (e.g. '731/1999')."""
    # Try docNumber in preface
    doc_num = root.find(f".//{{{_AKN_NS}}}docNumber")
    if doc_num is not None and doc_num.text:
        return doc_num.text.strip()
    # Fallback from FRBRWork
    num_el = root.find(f".//{{{_AKN_NS}}}FRBRWork/{{{_AKN_NS}}}FRBRnumber")
    year_el = root.find(f".//{{{_AKN_NS}}}proprietary/{{{_FINLEX_NS}}}documentYear")
    if num_el is not None and year_el is not None:
        return f"{num_el.get('value', '')}/{year_el.text or ''}"
    return ""


# ─── MetadataParser ───


class FinlexMetadataParser(MetadataParser):
    """Extracts NormMetadata from Finlex Akoma Ntoso XML."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        root = etree.fromstring(data, parser=_LXML_PARSER)

        # ── FRBR identification ──
        work = root.find(f".//{{{_AKN_NS}}}FRBRWork")
        expr = root.find(f".//{{{_AKN_NS}}}FRBRExpression")

        frbr_number = ""
        frbr_year = ""
        if work is not None:
            num_el = work.find(f"{{{_AKN_NS}}}FRBRnumber")
            frbr_number = num_el.get("value", "") if num_el is not None else ""

        # ── Proprietary (Finlex-specific) ──
        prop = root.find(f".//{{{_AKN_NS}}}proprietary")

        doc_year_el = prop.find(f"{{{_FINLEX_NS}}}documentYear") if prop is not None else None
        frbr_year = doc_year_el.text if doc_year_el is not None and doc_year_el.text else ""

        # Identifier: {year}-{number} (filesystem-safe)
        identifier = (
            f"{frbr_year}-{frbr_number}" if frbr_year and frbr_number else norm_id.replace("/", "-")
        )

        # Type/rank
        type_el = prop.find(f"{{{_FINLEX_NS}}}typeStatute") if prop is not None else None
        type_ref = ""
        if type_el is not None:
            ref_to = type_el.get("refersTo", "")
            # refersTo="#act" or "#decree"
            type_ref = ref_to.lstrip("#")
        rank = Rank(_TYPE_TO_RANK.get(type_ref, type_ref or "unknown"))

        # Status
        in_force_el = prop.find(f"{{{_FINLEX_NS}}}isInForce") if prop is not None else None
        is_in_force = in_force_el is not None and in_force_el.get("value", "").lower() == "true"
        status = NormStatus.IN_FORCE if is_in_force else NormStatus.REPEALED

        # Title
        doc_title = root.find(f".//{{{_AKN_NS}}}docTitle")
        title = doc_title.text.strip() if doc_title is not None and doc_title.text else ""

        # Short title (truncated)
        short_title = title[:80] + "..." if len(title) > 80 else title

        # Dates
        pub_date = _extract_publication_date(root)

        date_issued_el = (
            work.find(f"{{{_AKN_NS}}}FRBRdate[@name='dateIssued']") if work is not None else None
        )
        date_issued = (
            _parse_date(date_issued_el.get("date", "")) if date_issued_el is not None else pub_date
        )

        # Last modified (dateConsolidated from expression)
        last_modified = None
        if expr is not None:
            cons_el = expr.find(f"{{{_AKN_NS}}}FRBRdate[@name='dateConsolidated']")
            if cons_el is not None:
                last_modified = _parse_date(cons_el.get("date", ""))

        # Department (administrative branch)
        branch_el = prop.find(f"{{{_FINLEX_NS}}}administrativeBranch") if prop is not None else None
        department = ""
        if branch_el is not None:
            ref_to = branch_el.get("refersTo", "")
            # Resolve from TLCOrganization references
            if ref_to.startswith("#"):
                org_id = ref_to[1:]
                org_el = root.find(f".//{{{_AKN_NS}}}TLCOrganization[@eId='{org_id}']")
                if org_el is not None:
                    department = org_el.get("showAs", "")

        # Keywords/subjects
        subjects: list[str] = []
        for kw in _findall(root, ".//akn:classification/akn:keyword"):
            show_as = kw.get("showAs", "")
            if show_as:
                subjects.append(show_as)

        # Source URL
        year = int(frbr_year) if frbr_year.isdigit() else 0
        number = int(frbr_number) if frbr_number.isdigit() else 0
        source = _FINLEX_URL.format(year=year, number=number) if year and number else ""

        # ELI
        eli_el = work.find(f"{{{_AKN_NS}}}FRBRalias[@name='eli']") if work is not None else None
        eli = eli_el.get("value", "") if eli_el is not None else ""

        # Entry into force
        entry_force_el = (
            prop.find(f".//{{{_FINLEX_NS}}}dateEntryIntoForce") if prop is not None else None
        )
        entry_into_force = ""
        if entry_force_el is not None:
            entry_into_force = entry_force_el.get("date", "")

        # Amendments count
        amend_refs = (
            prop.findall(f".//{{{_FINLEX_NS}}}amendedBy/{{{_FINLEX_NS}}}statuteReference")
            if prop is not None
            else []
        )

        # Finnish citation format
        citation = f"{frbr_number}/{frbr_year}" if frbr_number and frbr_year else ""

        # Category
        cat_el = prop.find(f"{{{_FINLEX_NS}}}categoryStatute") if prop is not None else None
        category = ""
        if cat_el is not None:
            cat_ref = cat_el.get("refersTo", "").lstrip("#")
            category = cat_ref

        # Extra fields
        extra: list[tuple[str, str]] = []
        if eli:
            extra.append(("eli", eli))
        if entry_into_force:
            extra.append(("entry_into_force", entry_into_force))
        if citation:
            extra.append(("citation", citation))
        if category:
            extra.append(("category", category))
        if len(amend_refs) > 0:
            extra.append(("amendments_count", str(len(amend_refs))))

        # Images dropped count
        img_count = len(root.findall(f".//{{{_AKN_NS}}}img"))
        if img_count:
            extra.append(("images_dropped", str(img_count)))

        return NormMetadata(
            title=title,
            short_title=short_title,
            identifier=identifier,
            country="fi",
            rank=rank,
            publication_date=date_issued or pub_date,
            status=status,
            department=department,
            source=source,
            last_modified=last_modified,
            subjects=tuple(subjects),
            extra=tuple(extra),
        )
