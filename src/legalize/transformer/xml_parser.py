"""Parser for BOE consolidated legislation XML.

Converts the XML from endpoint /api/legislacion-consolidada/id/{id}/texto
into domain data models (Block, Version, Reform).

This parser is Spain-specific (it walks BOE's <bloque>/<version>/<p> schema)
but the module path is kept here so pre-existing callers keep working.
Peer countries use their own fetcher/<cc>/parser.py.

Refactored 2026-04-22 (RESEARCH-ES-v2.md):
- Per-tag dispatch (no more findall("p") that dropped tables/lists/images)
- Rich inline extractor (sup/sub/a-href/br preserved)
- Images linked to BOE CDN as Markdown image references (policy §11)
- nota_pie retained as styled paragraphs (no longer silently dropped)
- UTF-8 + control-char hygiene
- Recover-mode XML parser (BOE occasionally ships ill-formed disposiciones)
"""

from __future__ import annotations

import logging
import re
from datetime import date

from lxml import etree

from legalize.fetcher._tables import render_table
from legalize.fetcher._text import clean as _clean_bytes
from legalize.models import Block, Paragraph, Reform, Version

logger = logging.getLogger(__name__)

BOE_BASE = "https://www.boe.es"

_BOE_ID_RE = re.compile(r"\bBOE-[A-Z]-\d{4}-\d+\b")

# CSS classes that should NEVER appear as standalone paragraphs — they are
# either table-cell fragments (handled by the table renderer) or chrome
# injected by the BOE viewer that has no legal weight.
_STRIP_CLASSES = {
    "cabeza_tabla",
    "cuerpo_tabla_izq",
    "cuerpo_tabla_centro",
    "cuerpo_tabla_der",
    "textoCompleto",
}


def _parse_date(date_str: str) -> date | None:
    """Converts YYYYMMDD → date. Handles BOE's indefinite-validity sentinel 99999999."""
    if not date_str or date_str.strip() in ("", "99999999"):
        return None
    try:
        parsed = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
        if parsed.year > 2100:
            return None
        return parsed
    except ValueError:
        logger.debug("Could not parse date: %s", date_str)
        return None


# ─────────────────────────────────────────────
# Inline text extraction
# ─────────────────────────────────────────────


def _extract_inline(element: etree._Element) -> str:
    """Extract the text of an element preserving inline formatting.

    Handles:
    - <b>, <strong>           -> **text**
    - <i>, <em>               -> *text*
    - <sup>                   -> <sup>text</sup>  (HTML passthrough)
    - <sub>                   -> <sub>text</sub>  (HTML passthrough)
    - <br>                    -> two spaces + newline (Markdown hard break)
    - <a href="...">          -> [text](url)
    - <a class="refPost|refAnt" referencia="BOE-A-...">
                              -> [text](https://www.boe.es/buscar/doc.php?id=BOE-A-...)
    - <span>, <font>, others  -> transparent passthrough
    """
    parts: list[str] = []

    if element.text:
        parts.append(element.text)

    for child in element:
        if not isinstance(child.tag, str):
            continue
        tag = etree.QName(child.tag).localname

        if tag in ("b", "strong"):
            inner = _extract_inline(child).strip()
            if inner:
                parts.append(f"**{inner}**")
        elif tag in ("i", "em"):
            inner = _extract_inline(child).strip()
            if inner:
                parts.append(f"*{inner}*")
        elif tag == "sup":
            inner = _extract_inline(child).strip()
            if inner:
                parts.append(f"<sup>{inner}</sup>")
        elif tag == "sub":
            inner = _extract_inline(child).strip()
            if inner:
                parts.append(f"<sub>{inner}</sub>")
        elif tag == "br":
            parts.append("  \n")
        elif tag == "a":
            inner = _extract_inline(child)
            href = child.get("href") or ""
            ref = child.get("referencia") or ""
            # Normalise relative/anchor hrefs
            if href.startswith("/"):
                href = f"{BOE_BASE}{href}"
            elif href.startswith("#"):
                href = ""
            # Derive href from explicit `referencia` attribute
            if not href and ref.startswith("BOE-"):
                href = f"{BOE_BASE}/buscar/doc.php?id={ref}"
            # Fallback: BOE uses <a class="refPost">Ref. BOE-A-YYYY-NN</a>
            # with NO href and NO referencia attribute — scrape the ID from
            # the anchor text so cross-refs still work.
            if not href:
                m = _BOE_ID_RE.search(inner)
                if m:
                    href = f"{BOE_BASE}/buscar/doc.php?id={m.group(0)}"
            if href:
                parts.append(f"[{inner.strip()}]({href})")
            else:
                parts.append(inner)
        elif tag == "img":
            alt = child.get("alt") or ""
            src = child.get("src") or ""
            if src:
                if src.startswith("/"):
                    src = f"{BOE_BASE}{src}"
                parts.append(f"![{alt}]({src})")
        else:
            inner = _extract_inline(child)
            if inner:
                parts.append(inner)

        if child.tail:
            parts.append(child.tail)

    return "".join(parts)


def _cell_text(cell: etree._Element) -> str:
    """Cell text extractor for the generic table renderer."""
    inner_parts: list[str] = []
    for child in cell:
        if not isinstance(child.tag, str):
            continue
        t = _extract_inline(child).strip()
        if t:
            inner_parts.append(t)
    if not inner_parts and cell.text:
        return cell.text.strip()
    return " ".join(inner_parts)


# ─────────────────────────────────────────────
# Paragraph-level dispatch
# ─────────────────────────────────────────────


def _image_paragraph(img: etree._Element) -> Paragraph | None:
    alt = img.get("alt") or ""
    src = img.get("src") or ""
    if not src:
        return None
    if src.startswith("/"):
        src = f"{BOE_BASE}{src}"
    text = f"![{alt}]({src})"
    return Paragraph(css_class="image", text=text)


def _table_paragraph(table: etree._Element) -> Paragraph | None:
    md = render_table(table, _cell_text)
    if not md:
        return None
    return Paragraph(css_class="table", text=md)


def _list_paragraphs(list_el: etree._Element, ordered: bool) -> list[Paragraph]:
    """Render an <ol>/<ul> into a sequence of list_item paragraphs."""
    out: list[Paragraph] = []
    i = 1
    for li in list_el:
        if not isinstance(li.tag, str):
            continue
        tag = etree.QName(li.tag).localname
        if tag != "li":
            continue
        text = _extract_inline(li).strip()
        if not text:
            continue
        prefix = f"{i}. " if ordered else "- "
        out.append(Paragraph(css_class="list_item", text=prefix + text))
        i += 1
    return out


def _parse_blockquote(bq_el: etree._Element) -> list[Paragraph]:
    """Render a <blockquote> (child of <version>) as a list of Paragraphs.

    BOE uses <blockquote> to wrap two kinds of content:
    - nota_pie footnotes (the legislative audit trail for a given block)
    - quoted amending text (verbatim prior wording of the block being modified)

    For footnotes we let the normal nota_pie CSS mapping (`> <small>`) do its
    thing. For quoted amending text (p class="parrafo" / "parrafo_2" /
    "sangrado*" inside a blockquote) we force a `> ` prefix on the rendered
    text so the quotation marker survives into Markdown.
    """
    WRAP_CLASSES = {
        "parrafo",
        "parrafo_2",
        "parrafo_3",
        "sangrado",
        "sangrado_2",
        "sangrado_articulo",
        "",
    }
    out: list[Paragraph] = []
    for inner_el in bq_el:
        if not isinstance(inner_el.tag, str):
            continue
        inner_tag = etree.QName(inner_el.tag).localname
        if inner_tag == "p":
            p = _parse_p(inner_el)
            if p is None:
                continue
            if p.css_class in WRAP_CLASSES:
                # Prefix with `> ` so it renders as a Markdown blockquote.
                p = Paragraph(css_class="cita", text=p.text)
            out.append(p)
        elif inner_tag == "table":
            t = _table_paragraph(inner_el)
            if t is not None:
                out.append(t)
        elif inner_tag == "blockquote":
            # Nested blockquotes (rare). Flatten.
            out.extend(_parse_blockquote(inner_el))
        elif inner_tag == "ol":
            out.extend(_list_paragraphs(inner_el, ordered=True))
        elif inner_tag == "ul":
            out.extend(_list_paragraphs(inner_el, ordered=False))
    return out


def _parse_p(p_el: etree._Element) -> Paragraph | None:
    """Turn one <p> element into a Paragraph (or None if it should be dropped)."""
    css = (p_el.get("class") or "").strip()

    # Image-only paragraphs — many BOE laws emit <p class="imagen"><img .../></p>
    if css in ("imagen", "imagen_girada"):
        img = p_el.find("img")
        if img is not None:
            return _image_paragraph(img)

    if css in _STRIP_CLASSES:
        return None

    text = _extract_inline(p_el).strip()
    if not text:
        return None

    return Paragraph(css_class=css, text=text)


# ─────────────────────────────────────────────
# Main parse
# ─────────────────────────────────────────────


def parse_text_xml(xml_data: bytes | str) -> list[Block]:
    """Parse the BOE consolidated text XML and return a list of Block."""
    if isinstance(xml_data, str):
        xml_bytes = xml_data.encode("utf-8")
    else:
        xml_bytes = xml_data

    text = _clean_bytes(xml_bytes)
    parser = etree.XMLParser(recover=True, huge_tree=True, remove_blank_text=False)
    root = etree.fromstring(text.encode("utf-8"), parser=parser)

    blocks: list[Block] = []

    for block_el in root.iter("bloque"):
        versions: list[Version] = []

        for version_el in block_el.findall("version"):
            paragraphs: list[Paragraph] = []

            for child in version_el:
                if not isinstance(child.tag, str):
                    continue
                tag = etree.QName(child.tag).localname

                if tag == "p":
                    p = _parse_p(child)
                    if p is not None:
                        paragraphs.append(p)
                elif tag == "table":
                    t = _table_paragraph(child)
                    if t is not None:
                        paragraphs.append(t)
                elif tag == "ol":
                    paragraphs.extend(_list_paragraphs(child, ordered=True))
                elif tag == "ul":
                    paragraphs.extend(_list_paragraphs(child, ordered=False))
                elif tag == "img":
                    ip = _image_paragraph(child)
                    if ip is not None:
                        paragraphs.append(ip)
                elif tag == "pre":
                    paragraphs.append(Paragraph(css_class="pre", text=_extract_inline(child)))
                elif tag == "blockquote":
                    paragraphs.extend(_parse_blockquote(child))
                else:
                    logger.debug(
                        "unhandled element <%s> inside version %s",
                        tag,
                        version_el.get("id_norma", "?"),
                    )

            fecha_pub = version_el.get("fecha_publicacion", "")
            fecha_vig = version_el.get("fecha_vigencia", "")

            if not fecha_pub:
                continue

            parsed_pub = _parse_date(fecha_pub)
            if parsed_pub is None:
                continue

            parsed_vig = _parse_date(fecha_vig) if fecha_vig else parsed_pub

            versions.append(
                Version(
                    norm_id=version_el.get("id_norma", ""),
                    publication_date=parsed_pub,
                    effective_date=parsed_vig if parsed_vig is not None else parsed_pub,
                    paragraphs=tuple(paragraphs),
                )
            )

        blocks.append(
            Block(
                id=block_el.get("id", ""),
                block_type=block_el.get("tipo", ""),
                title=block_el.get("titulo", ""),
                versions=tuple(versions),
            )
        )

    return blocks


# ─────────────────────────────────────────────
# Reform extraction
# ─────────────────────────────────────────────


def extract_reforms(blocks: list[Block]) -> list[Reform]:
    reform_map: dict[tuple[date, str], list[str]] = {}
    for block in blocks:
        for version in block.versions:
            key = (version.publication_date, version.norm_id)
            if key not in reform_map:
                reform_map[key] = []
            reform_map[key].append(block.id)

    return [
        Reform(date=reform_date, norm_id=norm_id, affected_blocks=tuple(block_ids))
        for (reform_date, norm_id), block_ids in sorted(reform_map.items())
    ]


def get_block_at_date(block: Block, target_date: date) -> Version | None:
    applicable = [v for v in block.versions if v.publication_date <= target_date]
    if not applicable:
        return None
    return max(applicable, key=lambda v: v.publication_date)


# ─────────────────────────────────────────────
# Stage B: /diario_boe/xml.php parser
# ─────────────────────────────────────────────


def parse_diario_xml(xml_data: bytes | str) -> list[Block]:
    """Parse a /diario_boe/xml.php?id={id} payload into the same Block model.

    Diario XML (unlike the consolidated endpoint) has NO <bloque>/<version>
    hierarchy — it's the original publication text. We flatten it into a
    single block with a single version dated from <metadatos>
    <fecha_publicacion>, so the same renderer/markdown pipeline works.

    Used for Stage B (non-consolidated norms — Circulares, Resoluciones,
    Órdenes no consolidadas, RDs puntuales). See RESEARCH-ES-v2.md §3.
    """
    if isinstance(xml_data, str):
        xml_bytes = xml_data.encode("utf-8")
    else:
        xml_bytes = xml_data

    text = _clean_bytes(xml_bytes)
    parser = etree.XMLParser(recover=True, huge_tree=True, remove_blank_text=False)
    root = etree.fromstring(text.encode("utf-8"), parser=parser)

    # Root is <documento>; children: metadatos, metadata-eli, analisis, texto.
    meta = root.find("metadatos")
    norm_id = ""
    pub_date_obj: date | None = None
    if meta is not None:
        ident = meta.find("identificador")
        if ident is not None and ident.text:
            norm_id = ident.text.strip()
        fp = meta.find("fecha_publicacion")
        if fp is not None and fp.text:
            pub_date_obj = _parse_date(fp.text.strip())

    if pub_date_obj is None:
        pub_date_obj = date(1960, 1, 1)  # safe fallback; real data always has a date

    texto_el = root.find("texto")
    if texto_el is None:
        return []

    paragraphs: list[Paragraph] = []
    for child in texto_el:
        if not isinstance(child.tag, str):
            continue
        tag = etree.QName(child.tag).localname

        if tag == "p":
            p = _parse_p(child)
            if p is not None:
                paragraphs.append(p)
        elif tag == "table":
            t = _table_paragraph(child)
            if t is not None:
                paragraphs.append(t)
        elif tag == "ol":
            paragraphs.extend(_list_paragraphs(child, ordered=True))
        elif tag == "ul":
            paragraphs.extend(_list_paragraphs(child, ordered=False))
        elif tag == "img":
            ip = _image_paragraph(child)
            if ip is not None:
                paragraphs.append(ip)
        elif tag == "pre":
            paragraphs.append(Paragraph(css_class="pre", text=_extract_inline(child)))
        elif tag == "blockquote":
            paragraphs.extend(_parse_blockquote(child))

    version = Version(
        norm_id=norm_id,
        publication_date=pub_date_obj,
        effective_date=pub_date_obj,
        paragraphs=tuple(paragraphs),
    )
    block = Block(
        id="main",
        block_type="texto",
        title="",
        versions=(version,),
    )
    return [block]
