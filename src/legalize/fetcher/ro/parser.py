"""Parser for legislatie.just.ro HTML pages (Romania).

Each law page uses semantic CSS classes for all structural elements:

| CSS class   | Role                         | Markdown        |
|-------------|------------------------------|-----------------|
| S_DEN       | Document title/denomination  | metadata        |
| S_EMT*      | Emitent (issuer)             | metadata        |
| S_PUB*      | Publication reference        | metadata        |
| S_TTL*      | Titlu (Title I, II...)       | ## heading      |
| S_CAP*      | Capitol (Chapter)            | ### heading     |
| S_SEC*      | Secțiune (Section)           | #### heading    |
| S_ART*      | Articol (Article)            | ##### heading   |
| S_ALN*      | Alineat (numbered ¶)        | body text       |
| S_LIT*      | Literă (lettered subsec.)    | body text       |
| S_PAR       | Paragraph (generic)          | body text       |
| S_NTA*      | Notă (modification note)     | note text       |

Each class has sub-classes: _TTL (title/label), _BDY (body), _DEN
(denomination). The parser walks the HTML tree and maps these to
Block/Version/Paragraph objects.

Multi-version support: the client.get_suvestine() method returns a JSON
blob with base64-encoded HTML for each consolidated version. The
parse_suvestine() method handles merging multiple versions into blocks
with version tuples, similar to Belgium (be/).
"""

from __future__ import annotations

import base64
import json
import logging
import re
from datetime import date
from typing import Any

from lxml import html as lxml_html

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
from legalize.fetcher._tables import render_table
from legalize.fetcher._text import strip_control

logger = logging.getLogger(__name__)

_HTML_PARSER = lxml_html.HTMLParser(encoding="utf-8")

# UI elements to skip.
_SKIP_CLASSES = {"TAG_COLLAPSED"}

# Romanian month names for date parsing.
_RO_MONTHS = {
    "ianuarie": 1,
    "februarie": 2,
    "martie": 3,
    "aprilie": 4,
    "mai": 5,
    "iunie": 6,
    "iulie": 7,
    "august": 8,
    "septembrie": 9,
    "octombrie": 10,
    "noiembrie": 11,
    "decembrie": 12,
}

_PUB_DATE_RE = re.compile(
    r"nr\.\s*\d+[^d]*?din\s+(\d{1,2})\s+(\w+)\s+(\d{4})",
)

_DEN_DATE_RE = re.compile(
    r"din\s+(\d{1,2})\s+(\w+)\s+(\d{4})",
)

# Article number extraction from S_ART_TTL.
_ART_NUM_RE = re.compile(r"Articolul\s+(\d+(?:\^?\d+)?)", re.IGNORECASE)


def _parse_html(data: bytes):
    """Parse HTML bytes into lxml tree with forced UTF-8."""
    return lxml_html.fromstring(data, parser=_HTML_PARSER)


def _clean_text(text: str) -> str:
    """Clean text: strip control chars, normalize whitespace."""
    text = strip_control(text)
    text = text.replace("\xa0", " ")  # non-breaking space
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _element_text(el) -> str:
    """Extract all text from an element, skipping TAG_COLLAPSED and comments."""
    parts = []
    for node in el.iter():
        css = node.get("class", "")
        if css in _SKIP_CLASSES:
            continue
        if node.text:
            parts.append(node.text)
        if node.tail and node != el:
            parts.append(node.tail)
    return _clean_text(" ".join(parts))


def _normalize_href(href: str) -> str:
    """Normalize relative legislatie.just.ro links to absolute URLs."""
    if "DetaliiDocument" in href:
        # Strip leading ~/../../../ or ../../ prefix.
        href = re.sub(r"^~?(?:/?\.\./)+", "", href)
        if href.startswith("Public/"):
            href = f"https://legislatie.just.ro/{href}"
    return href


def _inline_text(el) -> str:
    """Extract text with inline bold/italic preserved.

    Walks child elements: <b>/<strong> → **text**, <i>/<em> → *text*.
    Cross-reference <a> tags → [text](url).
    """
    parts: list[str] = []

    def _walk(node, depth=0):
        tag = (node.tag or "").lower() if isinstance(node.tag, str) else ""
        css = node.get("class", "") if hasattr(node, "get") else ""

        if css in _SKIP_CLASSES:
            return

        is_bold = tag in ("b", "strong")
        is_italic = tag in ("i", "em")
        is_link = tag == "a"

        if is_bold:
            parts.append("**")
        elif is_italic:
            parts.append("*")

        if node.text:
            text = strip_control(node.text).replace("\xa0", " ")
            if is_link:
                href = _normalize_href(node.get("href", ""))
                parts.append(f"[{text}]({href})")
            else:
                parts.append(text)
        elif is_link and not node.text:
            # Link with no text -- just get text content.
            link_text = _clean_text(node.text_content())
            if link_text:
                href = _normalize_href(node.get("href", ""))
                parts.append(f"[{link_text}]({href})")

        for child in node:
            if isinstance(child.tag, str):
                _walk(child, depth + 1)
            if child.tail:
                tail = strip_control(child.tail).replace("\xa0", " ")
                parts.append(tail)

        if is_bold:
            parts.append("**")
        elif is_italic:
            parts.append("*")

    _walk(el)
    result = "".join(parts)
    return re.sub(r"\s+", " ", result).strip()


def _table_to_markdown(table_el) -> str:
    """Convert a <table> element to a Markdown pipe table."""
    return render_table(table_el, lambda cell: _clean_text(cell.text_content()))


def _parse_ro_date(text: str) -> date | None:
    """Parse 'DD luna YYYY' from Romanian text."""
    m = _DEN_DATE_RE.search(text)
    if m:
        day = int(m.group(1))
        month = _RO_MONTHS.get(m.group(2).lower())
        year = int(m.group(3))
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                pass
    return None


# ─────────────────────────────────────────────
# Block extraction from structured HTML
# ─────────────────────────────────────────────


def _extract_blocks_from_tree(
    tree,
    norm_id: str,
    pub_date: date,
) -> list[Block]:
    """Extract Block objects from a parsed HTML tree.

    Walks the content area looking for S_* CSS-classed elements and
    builds a list of blocks with proper hierarchy.
    """
    blocks: list[Block] = []
    block_idx = 0

    # Find the content container.
    content_el = tree.xpath('//*[@id="infoactinfoact"]')
    if not content_el:
        content_el = tree.xpath('//*[@id="div_Formaconsolidata"]')
    if not content_el:
        content_el = [tree]

    root = content_el[0]

    # Find all articles (S_ART).
    articles = root.xpath('.//span[@class="S_ART"]')

    # Also find top-level structural elements.
    titles = root.xpath('.//span[@class="S_TTL"]')
    chapters = root.xpath('.//span[@class="S_CAP"]')
    sections = root.xpath('.//span[@class="S_SEC"]')
    preamble_pars = root.xpath(
        './/span[@class="S_PAR"][not(ancestor::span[@class="S_ART"])]'
        '[not(ancestor::span[@class="S_NTA"])]'
    )
    notes = root.xpath('.//span[@class="S_NTA"]')

    # Process titles as blocks.
    for ttl_el in titles:
        ttl_text = ""
        ttl_ttl = ttl_el.xpath('.//span[@class="S_TTL_TTL"]')
        ttl_den = ttl_el.xpath('.//span[@class="S_TTL_DEN"]')
        if ttl_ttl:
            ttl_text = _clean_text(ttl_ttl[0].text_content())
        den_text = ""
        if ttl_den:
            den_text = _clean_text(ttl_den[0].text_content())

        heading = f"{ttl_text} {den_text}".strip() if den_text else ttl_text
        if not heading:
            continue

        paragraphs = [Paragraph(css_class="titulo_tit", text=heading)]
        blocks.append(
            Block(
                id=f"title-{block_idx}",
                block_type="title",
                title=heading[:80],
                versions=(
                    Version(
                        norm_id=norm_id,
                        publication_date=pub_date,
                        effective_date=pub_date,
                        paragraphs=tuple(paragraphs),
                    ),
                ),
            )
        )
        block_idx += 1

    # Process chapters as blocks.
    for cap_el in chapters:
        cap_text = ""
        cap_ttl = cap_el.xpath('.//span[@class="S_CAP_TTL"]')
        cap_den = cap_el.xpath('.//span[@class="S_CAP_DEN"]')
        if cap_ttl:
            cap_text = _clean_text(cap_ttl[0].text_content())
        den_text = ""
        if cap_den:
            den_text = _clean_text(cap_den[0].text_content())

        heading = f"{cap_text} {den_text}".strip() if den_text else cap_text
        if not heading:
            continue

        paragraphs = [Paragraph(css_class="capitulo_tit", text=heading)]
        blocks.append(
            Block(
                id=f"chapter-{block_idx}",
                block_type="chapter",
                title=heading[:80],
                versions=(
                    Version(
                        norm_id=norm_id,
                        publication_date=pub_date,
                        effective_date=pub_date,
                        paragraphs=tuple(paragraphs),
                    ),
                ),
            )
        )
        block_idx += 1

    # Process sections as blocks.
    for sec_el in sections:
        sec_text = ""
        sec_ttl = sec_el.xpath('.//span[@class="S_SEC_TTL"]')
        sec_den = sec_el.xpath('.//span[@class="S_SEC_DEN"]')
        if sec_ttl:
            sec_text = _clean_text(sec_ttl[0].text_content())
        den_text = ""
        if sec_den:
            den_text = _clean_text(sec_den[0].text_content())

        heading = f"{sec_text} {den_text}".strip() if den_text else sec_text
        if not heading:
            continue

        paragraphs = [Paragraph(css_class="seccion", text=heading)]
        blocks.append(
            Block(
                id=f"section-{block_idx}",
                block_type="section",
                title=heading[:80],
                versions=(
                    Version(
                        norm_id=norm_id,
                        publication_date=pub_date,
                        effective_date=pub_date,
                        paragraphs=tuple(paragraphs),
                    ),
                ),
            )
        )
        block_idx += 1

    # Process articles as blocks.
    for art_el in articles:
        art_ttl_el = art_el.xpath('.//span[@class="S_ART_TTL"]')
        art_den_el = art_el.xpath('.//span[@class="S_ART_DEN"]')
        art_bdy_el = art_el.xpath('.//span[@class="S_ART_BDY"]')

        art_title = _clean_text(art_ttl_el[0].text_content()) if art_ttl_el else ""
        art_den = _clean_text(art_den_el[0].text_content()) if art_den_el else ""

        # Extract article number for block ID.
        art_num = ""
        m = _ART_NUM_RE.search(art_title)
        if m:
            art_num = m.group(1)

        paragraphs: list[Paragraph] = []

        # Article heading.
        heading_text = art_title
        if art_den:
            heading_text = f"{art_title} {art_den}".strip()
        if heading_text:
            paragraphs.append(Paragraph(css_class="articulo", text=heading_text))

        # Article body.
        if art_bdy_el:
            _extract_body_paragraphs(art_bdy_el[0], paragraphs)

        if not paragraphs:
            continue

        block_id = f"art-{art_num}" if art_num else f"art-{block_idx}"
        blocks.append(
            Block(
                id=block_id,
                block_type="article",
                title=art_title[:80],
                versions=(
                    Version(
                        norm_id=norm_id,
                        publication_date=pub_date,
                        effective_date=pub_date,
                        paragraphs=tuple(paragraphs),
                    ),
                ),
            )
        )
        block_idx += 1

    # Process notes (modification notes) as blocks.
    for nta_el in notes:
        nta_pars = nta_el.xpath('.//span[@class="S_NTA_PAR"]')
        if not nta_pars:
            continue
        paragraphs = []
        for nta_par in nta_pars:
            text = _inline_text(nta_par)
            if text:
                paragraphs.append(Paragraph(css_class="parrafo", text=f"> {text}"))
        if paragraphs:
            blocks.append(
                Block(
                    id=f"note-{block_idx}",
                    block_type="note",
                    title="Notă",
                    versions=(
                        Version(
                            norm_id=norm_id,
                            publication_date=pub_date,
                            effective_date=pub_date,
                            paragraphs=tuple(paragraphs),
                        ),
                    ),
                )
            )
            block_idx += 1

    # If no articles found, parse the entire content as a preamble block.
    if not articles and not titles and not chapters:
        paragraphs = []
        for par_el in preamble_pars:
            text = _inline_text(par_el)
            if text:
                paragraphs.append(Paragraph(css_class="parrafo", text=text))

        # Also check for tables at top level.
        for table_el in root.xpath('.//table[not(@class="S_EMT")]'):
            md = _table_to_markdown(table_el)
            if md:
                paragraphs.append(Paragraph(css_class="table", text=md))

        if paragraphs:
            blocks.append(
                Block(
                    id="preamble",
                    block_type="preamble",
                    title="Preamble",
                    versions=(
                        Version(
                            norm_id=norm_id,
                            publication_date=pub_date,
                            effective_date=pub_date,
                            paragraphs=tuple(paragraphs),
                        ),
                    ),
                )
            )

    # Process standalone tables (not inside articles).
    for table_el in root.xpath(
        './/table[not(@class="S_EMT")][not(ancestor::span[@class="S_ART"])]'
    ):
        md = _table_to_markdown(table_el)
        if md:
            blocks.append(
                Block(
                    id=f"table-{block_idx}",
                    block_type="table",
                    title="Table",
                    versions=(
                        Version(
                            norm_id=norm_id,
                            publication_date=pub_date,
                            effective_date=pub_date,
                            paragraphs=(Paragraph(css_class="table", text=md),),
                        ),
                    ),
                )
            )
            block_idx += 1

    return blocks


def _extract_body_paragraphs(body_el, paragraphs: list[Paragraph]) -> None:
    """Extract paragraphs from an article body (S_ART_BDY).

    Handles S_ALN (alneats), S_LIT (litere), S_PAR (paragraphs),
    and inline tables.
    """
    for child in body_el:
        if not isinstance(child.tag, str):
            continue
        css = child.get("class", "")

        if css == "S_PAR":
            # Article description or generic paragraph.
            text = _inline_text(child)
            if text:
                paragraphs.append(Paragraph(css_class="parrafo", text=text))

        elif css == "S_ALN":
            # Numbered paragraph: (1), (2), etc.
            aln_ttl = child.xpath('.//span[@class="S_ALN_TTL"]')
            aln_bdy = child.xpath('.//span[@class="S_ALN_BDY"]')
            ttl_text = _clean_text(aln_ttl[0].text_content()) if aln_ttl else ""
            bdy_text = _inline_text(aln_bdy[0]) if aln_bdy else ""
            combined = f"{ttl_text} {bdy_text}".strip() if ttl_text else bdy_text
            if combined:
                paragraphs.append(Paragraph(css_class="parrafo", text=combined))

            # Check for nested litere inside this alineat.
            for lit_el in child.xpath('.//span[@class="S_LIT"]'):
                _extract_litera(lit_el, paragraphs)

        elif css == "S_LIT":
            _extract_litera(child, paragraphs)

        elif css == "S_NTA":
            # Inline note inside article body.
            nta_pars = child.xpath('.//span[@class="S_NTA_PAR"]')
            for nta_par in nta_pars:
                text = _inline_text(nta_par)
                if text:
                    paragraphs.append(Paragraph(css_class="parrafo", text=f"> {text}"))

        elif child.tag == "table":
            table_css = child.get("class", "")
            if table_css != "S_EMT":
                md = _table_to_markdown(child)
                if md:
                    paragraphs.append(Paragraph(css_class="table", text=md))

        # Recurse into other spans that might contain content.
        elif css and css.startswith("S_"):
            _extract_body_paragraphs(child, paragraphs)


def _extract_litera(lit_el, paragraphs: list[Paragraph]) -> None:
    """Extract a litera (lettered subsection) as a list item."""
    lit_ttl = lit_el.xpath('.//span[contains(@class, "S_LIT_TTL")]')
    lit_bdy = lit_el.xpath('.//span[contains(@class, "S_LIT_BDY")]')
    ttl_text = _clean_text(lit_ttl[0].text_content()) if lit_ttl else ""
    bdy_text = _inline_text(lit_bdy[0]) if lit_bdy else ""
    combined = f"{ttl_text} {bdy_text}".strip() if ttl_text else bdy_text
    if combined:
        paragraphs.append(Paragraph(css_class="parrafo", text=combined))


# ─────────────────────────────────────────────
# Metadata extraction
# ─────────────────────────────────────────────


def _extract_metadata_from_tree(
    tree,
    norm_id: str,
) -> dict[str, Any]:
    """Extract metadata fields from the HTML tree."""
    meta: dict[str, Any] = {}

    # Title (S_DEN).
    den = tree.xpath('//span[@class="S_DEN"]')
    if den:
        meta["title"] = _clean_text(den[0].text_content())

    # Emitent (issuer).
    emt = tree.xpath('//span[@class="S_EMT_BDY"]//li')
    if not emt:
        emt = tree.xpath('//span[@class="S_EMT_BDY"]')
    if emt:
        meta["department"] = _clean_text(emt[0].text_content())

    # Publication reference.
    pub = tree.xpath('//span[@class="S_PUB_BDY"]')
    if pub:
        pub_text = _clean_text(pub[0].text_content())
        meta["publication_reference"] = pub_text
        # Parse publication date.
        m = _PUB_DATE_RE.search(pub_text)
        if m:
            day = int(m.group(1))
            month = _RO_MONTHS.get(m.group(2).lower())
            year = int(m.group(3))
            if month:
                try:
                    meta["publication_date"] = date(year, month, day)
                except ValueError:
                    pass

    # Fallback date from title.
    if "publication_date" not in meta and "title" in meta:
        d = _parse_ro_date(meta["title"])
        if d:
            meta["publication_date"] = d

    # Act type from title.
    if "title" in meta:
        title = meta["title"].upper().strip()
        for act_type in (
            "CONSTITUȚIE",
            "CODUL CIVIL",
            "CODUL PENAL",
            "CODUL FISCAL",
            "CODUL MUNCII",
            "CODUL DE PROCEDURĂ CIVILĂ",
            "CODUL DE PROCEDURĂ PENALĂ",
            "COD CIVIL",
            "COD PENAL",
            "COD FISCAL",
            "ORDONANȚĂ DE URGENȚĂ",
            "ORDONANȚĂ",
            "HOTĂRÂRE",
            "DECRET-LEGE",
            "DECRET",
            "LEGE CONSTITUȚIONALĂ",
            "LEGE",
            "REGULAMENT",
            "NORMĂ",
            "ORDIN",
            "STATUT",
        ):
            if title.startswith(act_type):
                meta["act_type"] = act_type.lower()
                break

    # Count images dropped.
    imgs = tree.xpath('//img[contains(@src, ".jpg") or contains(@src, ".png")]')
    meta["images_dropped"] = len(imgs)

    return meta


# ─────────────────────────────────────────────
# TextParser and MetadataParser implementations
# ─────────────────────────────────────────────


class RoTextParser(TextParser):
    """Parse legislatie.just.ro HTML into Block objects."""

    def parse_text(self, data: bytes) -> list[Any]:
        """Parse a single version's HTML into blocks."""
        tree = _parse_html(data)
        # Use a placeholder norm_id and date; the pipeline overrides these.
        return _extract_blocks_from_tree(tree, norm_id="RO-0", pub_date=date(1970, 1, 2))

    def extract_reforms(self, data: bytes) -> list[Any]:
        """Extract reforms from text data.

        For Romania, reforms are extracted via parse_suvestine() which uses
        the version history from the detail page. The default implementation
        falls back to generic block-based extraction.
        """
        from legalize.transformer.xml_parser import extract_reforms

        blocks = self.parse_text(data)
        return extract_reforms(blocks)

    def parse_suvestine(
        self,
        suvestine_data: bytes,
        norm_id: str,
    ) -> tuple[list[Block], list[Reform]]:
        """Parse multi-version data into blocks with version tuples.

        suvestine_data is JSON produced by RoClient.get_suvestine().
        Returns (merged_blocks, reforms) where merged_blocks have
        one Version per historical consolidation.
        """
        payload = json.loads(suvestine_data)
        versions_data = payload.get("versions", [])

        if not versions_data:
            return [], []

        # Parse each version's HTML into blocks.
        all_version_blocks: list[tuple[date, str, list[Block]]] = []
        for v in versions_data:
            v_date = date.fromisoformat(v["date"])
            v_id = v["version_id"]
            v_html = base64.b64decode(v["text_b64"])
            blocks = _extract_blocks_from_tree(
                _parse_html(v_html),
                norm_id=v_id,
                pub_date=v_date,
            )
            all_version_blocks.append((v_date, v_id, blocks))

        # Sort oldest first.
        all_version_blocks.sort(key=lambda x: x[0])

        if len(all_version_blocks) == 1:
            # Single version: return as-is.
            v_date, v_id, blocks = all_version_blocks[0]
            reforms = [
                Reform(
                    date=v_date,
                    norm_id=v_id,
                    affected_blocks=(),
                )
            ]
            return blocks, reforms

        # Multiple versions: merge blocks by ID.
        # Use the latest version's block set as the canonical structure,
        # and add version entries from older versions where block IDs match.
        latest_date, latest_id, latest_blocks = all_version_blocks[-1]

        # Build a map of block_id → list of (date, version) across all versions.
        block_versions: dict[str, list[tuple[date, Version]]] = {}
        for v_date, v_id, blocks in all_version_blocks:
            for block in blocks:
                if block.id not in block_versions:
                    block_versions[block.id] = []
                if block.versions:
                    v = block.versions[0]
                    # Update version with correct date.
                    updated_v = Version(
                        norm_id=v_id,
                        publication_date=v_date,
                        effective_date=v_date,
                        paragraphs=v.paragraphs,
                    )
                    block_versions[block.id].append((v_date, updated_v))

        # Merge: each block gets all its historical versions.
        merged_blocks: list[Block] = []
        for block in latest_blocks:
            versions_for_block = block_versions.get(block.id, [])
            versions_for_block.sort(key=lambda x: x[0])
            merged_versions = tuple(v for _, v in versions_for_block)
            if not merged_versions:
                merged_versions = block.versions
            merged_blocks.append(
                Block(
                    id=block.id,
                    block_type=block.block_type,
                    title=block.title,
                    versions=merged_versions,
                )
            )

        # Also add blocks that only exist in older versions (deleted articles).
        latest_ids = {b.id for b in latest_blocks}
        for _, _, blocks in all_version_blocks:
            for block in blocks:
                if block.id not in latest_ids:
                    latest_ids.add(block.id)
                    versions_for_block = block_versions.get(block.id, [])
                    versions_for_block.sort(key=lambda x: x[0])
                    merged_versions = tuple(v for _, v in versions_for_block)
                    if not merged_versions:
                        merged_versions = block.versions
                    merged_blocks.append(
                        Block(
                            id=block.id,
                            block_type=block.block_type,
                            title=block.title,
                            versions=merged_versions,
                        )
                    )

        # Create reforms: one per version date.
        reforms: list[Reform] = []
        for v_date, v_id, _ in all_version_blocks:
            reforms.append(
                Reform(
                    date=v_date,
                    norm_id=v_id,
                    affected_blocks=(),
                )
            )

        return merged_blocks, reforms


class RoMetadataParser(MetadataParser):
    """Parse legislatie.just.ro HTML metadata into NormMetadata."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        """Parse raw metadata HTML into NormMetadata.

        data is the detail page HTML (from get_metadata).
        """
        tree = _parse_html(data)
        meta = _extract_metadata_from_tree(tree, norm_id)

        title = meta.get("title", f"Document {norm_id}")
        pub_date = meta.get("publication_date", date(1970, 1, 2))
        department = meta.get("department", "")
        act_type = meta.get("act_type", "lege")

        identifier = f"RO-{norm_id}"

        # Build extra tuple.
        extra: list[tuple[str, str]] = []
        if "publication_reference" in meta:
            extra.append(("publication_reference", meta["publication_reference"][:500]))
        if meta.get("images_dropped", 0) > 0:
            extra.append(("images_dropped", str(meta["images_dropped"])))

        return NormMetadata(
            title=title,
            short_title=title[:120],
            identifier=identifier,
            country="ro",
            rank=Rank(act_type),
            publication_date=pub_date,
            status=NormStatus.IN_FORCE,
            department=department,
            source=f"https://legislatie.just.ro/Public/DetaliiDocument/{norm_id}",
            extra=tuple(extra),
        )
