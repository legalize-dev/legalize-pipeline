"""Parser for Normattiva Akoma Ntoso XML (Italy).

Italian legislation is published in Akoma Ntoso (AKN) XML format,
an OASIS LegalDocML standard. The XML contains:

- meta/identification: URN, ELI, dates, country
- meta/lifecycle: events (publication, amendments)
- meta/publication: GU date and number
- meta/references: cross-references, parliamentary refs
- preface: act type, number, date, title
- preamble: promulgation formula
- body: articles with numbered paragraphs (commi)

AKN article structure:
  <article eId="art_1">
    <num>Art. 1.</num>
    <heading>Title of article</heading>
    <paragraph eId="art_1__para_1">
      <num>1.</num>
      <content><p>Text of comma 1...</p></content>
    </paragraph>
  </article>

Inline elements:
  <ref> - cross-references to other laws
  <ins> - legislative amendment markers ((1)), ((2))
  <del> - deleted text markers
  <mod> - modification containers
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from lxml import etree

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    Rank,
    Version,
)

logger = logging.getLogger(__name__)

_AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"
_NS = {"akn": _AKN_NS}

# Strip C0/C1 control characters (except tab, newline, carriage return)
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Map of act type codes to Rank values
_ACT_TYPE_TO_RANK: dict[str, str] = {
    "legge": "legge",
    "decreto.legislativo": "decreto_legislativo",
    "decreto-legge": "decreto_legge",
    "decreto.del.presidente.della.repubblica": "decreto_presidente_repubblica",
    "regio.decreto": "regio_decreto",
    "legge.costituzionale": "legge_costituzionale",
    "costituzione": "costituzione",
    "decreto.del.presidente.del.consiglio.dei.ministri": "dpcm",
    "decreto.ministeriale": "decreto_ministeriale",
    "regolamento": "regolamento",
    "regio.decreto-legge": "regio_decreto_legge",
    "decreto.legislativo.luogotenenziale": "decreto_legislativo_luogotenenziale",
    "decreto": "decreto",
}

# API type descriptions to rank mapping (from search results)
_DENOM_TO_RANK: dict[str, str] = {
    "LEGGE": "legge",
    "DECRETO LEGISLATIVO": "decreto_legislativo",
    "DECRETO-LEGGE": "decreto_legge",
    "DECRETO DEL PRESIDENTE DELLA REPUBBLICA": "decreto_presidente_repubblica",
    "REGIO DECRETO": "regio_decreto",
    "LEGGE COSTITUZIONALE": "legge_costituzionale",
    "COSTITUZIONE": "costituzione",
    "DECRETO DEL PRESIDENTE DEL CONSIGLIO DEI MINISTRI": "dpcm",
    "DECRETO MINISTERIALE": "decreto_ministeriale",
    "REGOLAMENTO": "regolamento",
    "REGIO DECRETO-LEGGE": "regio_decreto_legge",
    "DECRETO LEGISLATIVO LUOGOTENENZIALE": "decreto_legislativo_luogotenenziale",
    "DECRETO": "decreto",
    "DECRETO LEGISLATIVO DEL CAPO PROVVISORIO DELLO STATO": "decreto_legislativo_capo_provvisorio",
    "DECRETO REALE": "decreto_reale",
    "ORDINANZA": "ordinanza",
}


def _clean_text(text: str) -> str:
    """Normalize text: strip control chars, collapse whitespace."""
    text = _CTRL.sub("", text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_text(element: etree._Element) -> str:
    """Extract all text from an element and its children, excluding the element's own tail."""
    return _clean_text(
        etree.tostring(element, method="text", encoding="unicode", with_tail=False)
    )


def _find(element: etree._Element, xpath: str) -> etree._Element | None:
    """Find first element matching XPath with AKN namespace."""
    return element.find(xpath, namespaces=_NS)


def _findall(element: etree._Element, xpath: str) -> list[etree._Element]:
    """Find all elements matching XPath with AKN namespace."""
    return element.findall(xpath, namespaces=_NS)


def _parse_date_str(date_str: str) -> date | None:
    """Parse a date string in YYYY-MM-DD or YYYYMMDD format."""
    if not date_str:
        return None
    date_str = date_str.strip()
    try:
        if "-" in date_str:
            parts = date_str.split("-")
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(date_str) == 8:
            return date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
    except (ValueError, IndexError):
        logger.debug("Unparseable date: %s", date_str)
    return None


def _table_to_markdown(table_el: etree._Element) -> str:
    """Convert an AKN <table> element to Markdown.

    Italian AKN tables are often pre-formatted ASCII art inside a <td><p>
    element, so we extract the text preserving line breaks.
    """
    text = etree.tostring(table_el, method="text", encoding="unicode")
    lines = [_clean_text(line) for line in text.split("\n") if _clean_text(line)]
    if not lines:
        return ""

    # Check if it's already ASCII-art formatted (has pipe chars or dashes)
    has_pipes = any("|" in line for line in lines)
    if has_pipes:
        return "\n".join(lines)

    # Otherwise try to build a markdown table from <tr>/<td> structure
    rows: list[list[str]] = []
    for tr in table_el.iter():
        tag = tr.tag.split("}")[-1] if "}" in tr.tag else tr.tag
        if tag == "tr":
            cells: list[str] = []
            for cell in tr:
                cell_tag = cell.tag.split("}")[-1] if "}" in cell.tag else cell.tag
                if cell_tag in ("td", "th"):
                    cells.append(_extract_text(cell))
            if cells:
                rows.append(cells)

    if not rows:
        return "\n".join(lines)

    # Build markdown pipe table
    max_cols = max(len(r) for r in rows)
    for r in rows:
        r.extend([""] * (max_cols - len(r)))

    md_lines = []
    md_lines.append("| " + " | ".join(rows[0]) + " |")
    md_lines.append("| " + " | ".join(["---"] * max_cols) + " |")
    for row in rows[1:]:
        md_lines.append("| " + " | ".join(row) + " |")

    return "\n".join(md_lines)


def _inline_text(element: etree._Element) -> str:
    """Extract text from an element, formatting <ref> as Markdown links."""
    parts: list[str] = []
    if element.text:
        parts.append(element.text)

    for child in element:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag == "ref":
            href = child.get("href", "")
            ref_text = _extract_text(child)
            if href and ref_text:
                # Convert normattiva URN refs to normattiva URLs
                if href.startswith("/akn/"):
                    href = f"https://www.normattiva.it{href}"
                parts.append(f"[{ref_text}]({href})")
            elif ref_text:
                parts.append(ref_text)
        elif tag == "ins":
            # Amendment markers like ((1))
            ins_text = _extract_text(child)
            if ins_text:
                parts.append(ins_text)
        elif tag in ("mod", "quotedStructure", "quotedText"):
            parts.append(_extract_text(child))
        elif tag == "authorialNote":
            note_text = _extract_text(child)
            if note_text:
                parts.append(f" [{note_text}]")
        else:
            parts.append(_extract_text(child))

        if child.tail:
            parts.append(child.tail)

    return _clean_text("".join(parts))


def _parse_paragraph(para_el: etree._Element) -> list[Paragraph]:
    """Parse an AKN <paragraph> element into Paragraph objects.

    Each paragraph has a <num> (comma number) and <content>/<list> with text.
    """
    paragraphs: list[Paragraph] = []

    num_el = _find(para_el, "akn:num")
    num_text = _extract_text(num_el) if num_el is not None else ""

    # Content can be in <content> or <list>
    content_el = _find(para_el, "akn:content")
    list_el = _find(para_el, "akn:list")

    source = content_el if content_el is not None else list_el

    if source is None:
        # Fallback: extract text directly from paragraph
        text = _inline_text(para_el)
        if text and text != num_text:
            paragraphs.append(Paragraph(css_class="parrafo", text=f"{num_text} {text}".strip()))
        return paragraphs

    # Process direct children of content (p, table, blockList, etc.)
    children = list(source)
    if not children:
        return paragraphs

    for p_el in children:
        tag = p_el.tag.split("}")[-1] if "}" in p_el.tag else p_el.tag

        if tag == "table":
            table_md = _table_to_markdown(p_el)
            if table_md:
                paragraphs.append(Paragraph(css_class="table", text=table_md))
            continue

        if tag == "blockList":
            # Ordered/unordered lists
            for item in _findall(p_el, "akn:item"):
                item_text = _inline_text(item)
                if item_text:
                    paragraphs.append(Paragraph(css_class="list_item", text=f"- {item_text}"))
            continue

        text = _inline_text(p_el)
        if not text:
            continue

        # First <p> in first paragraph gets the comma number prepended
        if num_text and p_el is children[0] and not text.startswith(num_text):
            text = f"{num_text} {text}"
            num_text = ""  # only prepend once

        paragraphs.append(Paragraph(css_class="parrafo", text=text))

    return paragraphs


class NormattivaTextParser(TextParser):
    """Parses Akoma Ntoso XML into Block objects for Italy."""

    def parse_text(self, data: bytes) -> list[Any]:
        """Parse AKN XML into a list of Block objects.

        Each <article> becomes a Block with block_type="article".
        The preamble becomes a Block with block_type="preamble".
        """
        tree = etree.fromstring(data)
        act = tree.find("akn:act", namespaces=_NS)
        if act is None:
            act = tree.find("act")
        if act is None:
            logger.warning("No <act> element found in AKN XML")
            return []

        blocks: list[Block] = []

        # Extract metadata for version info
        meta = _find(act, "akn:meta")
        pub_date = self._extract_publication_date(meta) if meta is not None else date.today()
        norm_id = self._extract_norm_id(meta) if meta is not None else ""

        # Parse preamble
        preamble = _find(act, "akn:preamble")
        if preamble is not None:
            preamble_block = self._parse_preamble(preamble, norm_id, pub_date)
            if preamble_block:
                blocks.append(preamble_block)

        # Parse preface (act type + title)
        preface = _find(act, "akn:preface")
        if preface is not None:
            preface_block = self._parse_preface(preface, norm_id, pub_date)
            if preface_block:
                blocks.insert(0, preface_block)

        # Parse body articles (may be nested in chapters/parts/titles/sections)
        body = _find(act, "akn:body")
        if body is not None:
            self._parse_body(body, blocks, norm_id, pub_date)

        # Parse conclusions (signatures)
        conclusions = _find(act, "akn:conclusions")
        if conclusions is not None:
            concl_block = self._parse_conclusions(conclusions, norm_id, pub_date)
            if concl_block:
                blocks.append(concl_block)

        # Parse attachments (appendices with tables, annexes)
        attachments = _find(act, "akn:attachments")
        if attachments is not None:
            for i, att in enumerate(_findall(attachments, "akn:attachment")):
                att_block = self._parse_attachment(att, norm_id, pub_date, i)
                if att_block:
                    blocks.append(att_block)

        return blocks

    def _extract_publication_date(self, meta: etree._Element) -> date:
        pub = _find(meta, ".//akn:publication")
        if pub is not None:
            d = _parse_date_str(pub.get("date", ""))
            if d:
                return d

        work_date = _find(meta, ".//akn:FRBRWork/akn:FRBRdate")
        if work_date is not None:
            d = _parse_date_str(work_date.get("date", ""))
            if d:
                return d

        return date.today()

    def _extract_norm_id(self, meta: etree._Element) -> str:
        alias = _find(meta, ".//akn:FRBRWork/akn:FRBRalias[@name='urn:nir']")
        if alias is not None:
            return alias.get("value", "")

        this = _find(meta, ".//akn:FRBRWork/akn:FRBRthis")
        if this is not None:
            return this.get("value", "")

        return ""

    def _parse_body(
        self,
        body: etree._Element,
        blocks: list[Block],
        norm_id: str,
        pub_date: date,
    ) -> None:
        """Recursively parse body, handling chapters/parts/titles/sections."""
        _STRUCTURAL = {"book", "part", "title", "chapter", "section"}
        _TAG_TO_CSS = {
            "book": "titulo_tit",       # ## (top-level)
            "part": "titulo_tit",       # ## (top-level)
            "title": "titulo_tit",      # ## (top-level)
            "chapter": "capitulo_tit",  # ###
            "section": "seccion",       # ####
        }

        for child in body:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

            if tag == "article":
                block = self._parse_article(child, norm_id, pub_date)
                if block:
                    blocks.append(block)
            elif tag in _STRUCTURAL:
                # Emit a heading block for the structural element
                num_el = _find(child, "akn:num")
                heading_el = _find(child, "akn:heading")
                num_text = _extract_text(num_el) if num_el is not None else ""
                heading_text = _extract_text(heading_el) if heading_el is not None else ""
                section_title = f"{num_text} {heading_text}".strip()

                if section_title:
                    css_class = _TAG_TO_CSS.get(tag, "titulo_tit")
                    eid = child.get("eId", f"{tag}-{num_text}")
                    blocks.append(
                        Block(
                            id=eid,
                            block_type=tag,
                            title=section_title,
                            versions=(
                                Version(
                                    norm_id=norm_id,
                                    publication_date=pub_date,
                                    effective_date=pub_date,
                                    paragraphs=(
                                        Paragraph(
                                            css_class=css_class,
                                            text=section_title,
                                        ),
                                    ),
                                ),
                            ),
                        )
                    )

                # Recurse into structural elements
                self._parse_body(child, blocks, norm_id, pub_date)

    def _parse_preface(
        self, preface: etree._Element, norm_id: str, pub_date: date
    ) -> Block | None:
        paragraphs: list[Paragraph] = []
        text = _extract_text(preface)
        if text:
            # Use parrafo: the markdown renderer already emits # {title} from metadata
            paragraphs.append(Paragraph(css_class="parrafo", text=text))

        if not paragraphs:
            return None

        return Block(
            id="preface",
            block_type="preamble",
            title="",
            versions=(
                Version(
                    norm_id=norm_id,
                    publication_date=pub_date,
                    effective_date=pub_date,
                    paragraphs=tuple(paragraphs),
                ),
            ),
        )

    def _parse_preamble(
        self, preamble: etree._Element, norm_id: str, pub_date: date
    ) -> Block | None:
        paragraphs: list[Paragraph] = []

        for child in preamble:
            text = _extract_text(child)
            if not text:
                continue

            paragraphs.append(Paragraph(css_class="parrafo", text=text))

        if not paragraphs:
            return None

        return Block(
            id="preamble",
            block_type="preamble",
            title="",
            versions=(
                Version(
                    norm_id=norm_id,
                    publication_date=pub_date,
                    effective_date=pub_date,
                    paragraphs=tuple(paragraphs),
                ),
            ),
        )

    def _parse_article(
        self, article: etree._Element, norm_id: str, pub_date: date
    ) -> Block | None:
        eid = article.get("eId", "")
        num_el = _find(article, "akn:num")
        heading_el = _find(article, "akn:heading")

        num_text = _extract_text(num_el) if num_el is not None else ""
        heading_text = _extract_text(heading_el) if heading_el is not None else ""

        title = num_text
        if heading_text:
            title = f"{num_text} {heading_text}".strip()

        paragraphs: list[Paragraph] = []

        # Article heading
        if title:
            paragraphs.append(Paragraph(css_class="articulo", text=title))

        # Parse numbered paragraphs (commi)
        for para in _findall(article, "akn:paragraph"):
            paragraphs.extend(_parse_paragraph(para))

        if not paragraphs:
            return None

        return Block(
            id=eid or f"art-{num_text}",
            block_type="article",
            title=title,
            versions=(
                Version(
                    norm_id=norm_id,
                    publication_date=pub_date,
                    effective_date=pub_date,
                    paragraphs=tuple(paragraphs),
                ),
            ),
        )

    def _parse_conclusions(
        self, conclusions: etree._Element, norm_id: str, pub_date: date
    ) -> Block | None:
        paragraphs: list[Paragraph] = []

        for child in conclusions:
            text = _extract_text(child)
            if text:
                paragraphs.append(Paragraph(css_class="firma_rey", text=text))

        if not paragraphs:
            return None

        return Block(
            id="conclusions",
            block_type="text",
            title="",
            versions=(
                Version(
                    norm_id=norm_id,
                    publication_date=pub_date,
                    effective_date=pub_date,
                    paragraphs=tuple(paragraphs),
                ),
            ),
        )

    def _parse_attachment(
        self,
        attachment: etree._Element,
        norm_id: str,
        pub_date: date,
        index: int,
    ) -> Block | None:
        """Parse an AKN <attachment> element (appendix/annex) into a Block."""
        paragraphs: list[Paragraph] = []

        doc = _find(attachment, "akn:doc")
        if doc is None:
            text = _extract_text(attachment)
            if text:
                paragraphs.append(Paragraph(css_class="parrafo", text=text))
        else:
            doc_preface = _find(doc, "akn:preface")
            if doc_preface is not None:
                text = _extract_text(doc_preface)
                if text:
                    paragraphs.append(Paragraph(css_class="centro_negrita", text=text))

            main_body = _find(doc, "akn:mainBody")
            if main_body is not None:
                for child in main_body:
                    tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

                    if tag == "paragraph":
                        paragraphs.extend(_parse_paragraph(child))
                    elif tag == "article":
                        block = self._parse_article(child, norm_id, pub_date)
                        if block:
                            for v in block.versions:
                                paragraphs.extend(v.paragraphs)
                    elif tag == "table":
                        table_md = _table_to_markdown(child)
                        if table_md:
                            paragraphs.append(
                                Paragraph(css_class="table", text=table_md)
                            )
                    else:
                        text = _extract_text(child)
                        if text:
                            paragraphs.append(
                                Paragraph(css_class="parrafo", text=text)
                            )

        if not paragraphs:
            return None

        return Block(
            id=f"attachment_{index}",
            block_type="attachment",
            title=f"Allegato {index + 1}",
            versions=(
                Version(
                    norm_id=norm_id,
                    publication_date=pub_date,
                    effective_date=pub_date,
                    paragraphs=tuple(paragraphs),
                ),
            ),
        )


class NormattivaMetadataParser(MetadataParser):
    """Parses Akoma Ntoso XML metadata into NormMetadata for Italy."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        """Parse AKN XML metadata into NormMetadata.

        Extracts from <meta>, <preface>, and act attributes.
        """
        tree = etree.fromstring(data)
        act = tree.find("akn:act", namespaces=_NS)
        if act is None:
            act = tree.find("act")
        if act is None:
            raise ValueError(f"No <act> element in AKN XML for {norm_id}")

        meta = _find(act, "akn:meta")
        preface = _find(act, "akn:preface")

        # Title from preface
        title = self._extract_title(preface, meta)

        # Dates
        pub_date = self._extract_publication_date(meta)

        # Identifier (codiceRedazionale or URN-derived)
        identifier = self._make_identifier(norm_id, meta)

        # Rank from act type in FRBRWork URI
        rank = self._extract_rank(meta)

        # Status (always IN_FORCE for vigente text; the API only returns vigente)
        status = NormStatus.IN_FORCE

        # Source URL
        source_url = self._extract_source_url(meta)

        # Extra metadata
        extra = self._extract_extra(meta, preface)

        department = ""
        # Try to get department from references
        if meta is not None:
            author = _find(meta, ".//akn:FRBRWork/akn:FRBRauthor")
            if author is not None:
                department = author.get("showAs", "") or author.get("href", "")

        return NormMetadata(
            title=title,
            short_title=title,
            identifier=identifier,
            country="it",
            rank=Rank(rank),
            publication_date=pub_date,
            status=status,
            department=department,
            source=source_url,
            subjects=(),
            extra=tuple(extra),
        )

    def _extract_title(
        self,
        preface: etree._Element | None,
        meta: etree._Element | None,
    ) -> str:
        if preface is not None:
            text = _extract_text(preface)
            if text:
                return text

        # Fallback to FRBRWork URI
        if meta is not None:
            this = _find(meta, ".//akn:FRBRWork/akn:FRBRthis")
            if this is not None:
                return this.get("value", "")

        return ""

    def _extract_publication_date(self, meta: etree._Element | None) -> date:
        if meta is None:
            return date.today()

        pub = _find(meta, ".//akn:publication")
        if pub is not None:
            d = _parse_date_str(pub.get("date", ""))
            if d:
                return d

        work_date = _find(meta, ".//akn:FRBRWork/akn:FRBRdate")
        if work_date is not None:
            d = _parse_date_str(work_date.get("date", ""))
            if d:
                return d

        return date.today()

    def _extract_emanation_date(self, meta: etree._Element | None) -> date | None:
        if meta is None:
            return None

        work_date = _find(meta, ".//akn:FRBRWork/akn:FRBRdate")
        if work_date is not None:
            return _parse_date_str(work_date.get("date", ""))
        return None

    def _extract_rank(self, meta: etree._Element | None) -> str:
        if meta is None:
            return "legge"

        # Extract from FRBRWork URI: /akn/it/act/{type}/stato/{date}/{number}
        this = _find(meta, ".//akn:FRBRWork/akn:FRBRthis")
        if this is not None:
            value = this.get("value", "")
            # Pattern: /akn/it/act/{type}/stato/...
            match = re.search(r"/akn/it/act/([^/]+)/", value)
            if match:
                act_type = match.group(1).lower()
                return _ACT_TYPE_TO_RANK.get(act_type, act_type)

        return "legge"

    def _make_identifier(self, norm_id: str, meta: etree._Element | None) -> str:
        """Create a filesystem-safe identifier."""
        # Strip dataGU/URN suffix from composite norm_id
        # Format: codiceRedaz:dataGU:urn or codiceRedaz:dataGU or codiceRedaz
        base_id = norm_id.split(":")[0] if ":" in norm_id else norm_id

        # If base_id is already a codiceRedazionale, use it
        if base_id and re.match(r"^\w+$", base_id):
            return base_id

        # Try to extract from URN alias
        if meta is not None:
            alias = _find(meta, ".//akn:FRBRWork/akn:FRBRalias[@name='urn:nir']")
            if alias is not None:
                urn = alias.get("value", "")
                # urn:nir:stato:legge:2024-06-26;86 -> stato-legge-2024-06-26-86
                parts = urn.replace("urn:nir:", "").replace(";", "-").replace(":", "-").replace(".", "-")
                return re.sub(r"[^a-zA-Z0-9_-]", "-", parts)

        # Fallback to cleaning norm_id
        return re.sub(r"[^a-zA-Z0-9_-]", "-", base_id)

    def _extract_source_url(self, meta: etree._Element | None) -> str:
        if meta is None:
            return ""

        alias = _find(meta, ".//akn:FRBRWork/akn:FRBRalias[@name='urn:nir']")
        if alias is not None:
            urn = alias.get("value", "")
            return f"https://www.normattiva.it/uri-res/N2Ls?{urn}"

        return "https://www.normattiva.it"

    def _extract_extra(
        self,
        meta: etree._Element | None,
        preface: etree._Element | None,
    ) -> list[tuple[str, str]]:
        """Extract additional metadata fields into extra key-value pairs."""
        extra: list[tuple[str, str]] = []

        if meta is None:
            return extra

        # URN
        alias_nir = _find(meta, ".//akn:FRBRWork/akn:FRBRalias[@name='urn:nir']")
        if alias_nir is not None:
            extra.append(("urn_nir", alias_nir.get("value", "")))

        # ELI
        alias_eli = _find(meta, ".//akn:FRBRWork/akn:FRBRalias[@name='eli']")
        if alias_eli is not None:
            extra.append(("eli", alias_eli.get("value", "")))

        # FRBRWork URI
        this = _find(meta, ".//akn:FRBRWork/akn:FRBRthis")
        if this is not None:
            extra.append(("akn_uri", this.get("value", "")))

        # Expression date (vigenza date)
        expr_date = _find(meta, ".//akn:FRBRExpression/akn:FRBRdate")
        if expr_date is not None:
            d = expr_date.get("date", "")
            if d:
                extra.append(("expression_date", d))

        # GU publication
        pub = _find(meta, ".//akn:publication")
        if pub is not None:
            gu_date = pub.get("date", "")
            gu_number = pub.get("number", "")
            if gu_date:
                extra.append(("gu_date", gu_date))
            if gu_number:
                extra.append(("gu_number", gu_number))

        # Lifecycle events
        lifecycle = _find(meta, "akn:lifecycle")
        if lifecycle is not None:
            events = _findall(lifecycle, "akn:eventRef")
            for i, ev in enumerate(events):
                ev_date = ev.get("date", "")
                ev_source = ev.get("source", "")
                if ev_date:
                    extra.append((f"lifecycle_event_{i}_date", ev_date))
                if ev_source:
                    extra.append((f"lifecycle_event_{i}_source", ev_source))

        # Country
        country = _find(meta, ".//akn:FRBRWork/akn:FRBRcountry")
        if country is not None:
            extra.append(("frbr_country", country.get("value", "")))

        # Language
        lang = _find(meta, ".//akn:FRBRExpression/akn:FRBRlanguage")
        if lang is not None:
            extra.append(("language", lang.get("language", "")))

        # References (parliamentary tracking)
        refs = _find(meta, "akn:references")
        if refs is not None:
            for ref in _findall(refs, "akn:passiveRef"):
                href = ref.get("href", "")
                if href and "parlamento" in href:
                    extra.append(("parliamentary_ref", href[:500]))

        return extra
