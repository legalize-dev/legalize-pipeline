"""Parsers LEGI — consolidated text and metadata from the LEGI database.

Parses the combined XML built by LEGIClient.get_texto()
(<legi_combined> format) and the metadata from the structure file.

Reference: Archéo-Lex (github.com/Legilibre/Archeo-Lex) for the
XML structure of the LEGI dump.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from lxml import etree

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import (
    Bloque,
    EstadoNorma,
    NormaMetadata,
    Paragraph,
    Rango,
    Version,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# LEGI NATURE → Rango mapping
# ─────────────────────────────────────────────

_NATURE_TO_RANGO: dict[str, Rango] = {
    "CODE": Rango.CODE,
    "CONSTITUTION": Rango.CONSTITUTION_FR,
    "LOI": Rango.LOI,
    "LOI ORGANIQUE": Rango.LOI_ORGANIQUE,
    "LOI_ORGANIQUE": Rango.LOI_ORGANIQUE,
    "ORDONNANCE": Rango.ORDONNANCE,
    "DECRET": Rango.DECRET,
    "DÉCRET": Rango.DECRET,
}

# ─────────────────────────────────────────────
# Section niv → CSS class for markdown mapping
# ─────────────────────────────────────────────

_SECTION_NIV_CSS: dict[str, str] = {
    "1": "titulo_tit",       # ## heading
    "2": "capitulo_tit",     # ### heading
    "3": "seccion",          # #### heading
    "4": "seccion",          # #### heading (sub-section)
}


# ─────────────────────────────────────────────
# Date helpers (same pattern as xml_parser._parse_date)
# ─────────────────────────────────────────────


def _parse_date_legi(fecha_str: str) -> date | None:
    """Parses LEGI dates. Returns None for sentinels and invalid dates.

    Actual format of the LEGI dump (verified with 2026-03-27 data):
    - Dates in YYYY-MM-DD format (ISO 8601), e.g.: "2008-07-24"
    - Sentinel: "2999-01-01" (= indefinite validity) → None
    - Also accepts YYYYMMDD for compatibility with example XML
    - Years > 2100 → None (covers sentinel 2999 and invalid future dates)
    """
    if not fecha_str:
        return None
    fecha_str = fecha_str.strip()
    if not fecha_str or fecha_str in ("99999999", "2999-01-01"):
        return None
    try:
        # Try ISO 8601 first (actual dump format)
        if "-" in fecha_str:
            parsed = date.fromisoformat(fecha_str)
        elif len(fecha_str) >= 8:
            # Fallback YYYYMMDD (just in case)
            parsed = date(int(fecha_str[:4]), int(fecha_str[4:6]), int(fecha_str[6:8]))
        else:
            return None
        if parsed.year > 2100:
            return None
        return parsed
    except ValueError:
        return None


# ─────────────────────────────────────────────
# Text extraction from CONTENU
# ─────────────────────────────────────────────


def _extract_text_legi(element: etree._Element) -> str:
    """Extracts text from a LEGI element, including inline sub-elements.

    Actual format of CONTENU in the LEGI dump (verified):
    - <p> with text and inline elements
    - <b>, <i>, <strong>, <em> → Markdown bold/italic
    - <br/> → newline
    - <blockquote> → indented text (common in articles that modify others)
    - <div> → container (treat as block)
    - <a> → text only (no link)
    - <sup> → plain text (note numbers)
    - <table>, <tr>, <td> → text separated by pipes
    """
    parts: list[str] = []

    if element.text:
        parts.append(element.text)

    for child in element:
        tag = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
        tag_lower = tag.lower()

        if tag_lower in ("b", "strong"):
            inner = _extract_text_legi(child)
            if inner.strip():
                parts.append(f"**{inner.strip()}**")
        elif tag_lower in ("i", "em"):
            inner = _extract_text_legi(child)
            if inner.strip():
                parts.append(f"*{inner.strip()}*")
        elif tag_lower == "br":
            parts.append("\n")
        elif tag_lower == "blockquote":
            inner = _extract_text_legi(child)
            if inner.strip():
                # Indent each line of the blockquote
                quoted = "\n".join(f"> {line}" for line in inner.strip().splitlines())
                parts.append(f"\n{quoted}\n")
        elif tag_lower == "div":
            inner = _extract_text_legi(child)
            if inner.strip():
                parts.append(f"\n{inner.strip()}\n")
        elif tag_lower in ("sup", "sub"):
            inner = _extract_text_legi(child)
            if inner.strip():
                parts.append(inner.strip())
        elif tag_lower == "table":
            # Simplify tables to plain text
            inner = _extract_text_legi(child)
            if inner.strip():
                parts.append(f"\n{inner.strip()}\n")
        else:
            # <a>, <span>, <font>, etc. → extract text only
            inner = _extract_text_legi(child)
            if inner:
                parts.append(inner)

        if child.tail:
            parts.append(child.tail)

    return "".join(parts)


def _extract_contenu_paragraphs(article_el: etree._Element) -> list[Paragraph]:
    """Extracts paragraphs from the CONTENU of a LEGI article.

    Generates a paragraph with class 'articulo' for the article number,
    followed by paragraphs with class 'parrafo' for the content.
    """
    contenu = article_el.find("CONTENU")
    if contenu is None:
        return []

    paragraphs: list[Paragraph] = []
    num = article_el.get("num", "")
    if num:
        paragraphs.append(Paragraph(css_class="articulo", text=f"Article {num}"))

    for p_el in contenu.iter("p"):
        text = _extract_text_legi(p_el)
        if text.strip():
            paragraphs.append(Paragraph(css_class="parrafo", text=text.strip()))

    # If CONTENU has no <p> children, try direct text
    if not paragraphs or (len(paragraphs) == 1 and num):
        direct_text = _extract_text_legi(contenu)
        if direct_text.strip():
            paragraphs.append(Paragraph(css_class="parrafo", text=direct_text.strip()))

    return paragraphs


# ─────────────────────────────────────────────
# Combined text parser → Bloque
# ─────────────────────────────────────────────


def _parse_legi_combined(data: bytes) -> list[Bloque]:
    """Parses the combined XML from LEGIClient.get_texto() into Bloques.

    Input format: <legi_combined id="LEGITEXTXXX">
      <META>...</META>
      <elements>
        <section id="..." titre="..." niv="1" debut="..." fin="..." etat="..."/>
        <article id="..." cid="..." num="..." debut="..." fin="..." etat="...">
          <CONTENU><p>...</p></CONTENU>
          <source_modif id="..." date="..." nature="..."/>
        </article>
        ...
      </elements>
    </legi_combined>
    """
    root = etree.fromstring(data)
    elements = root.find("elements")
    if elements is None:
        return []

    # First pass: group articles by cid
    articles_by_cid: dict[str, list[etree._Element]] = {}
    for el in elements:
        if el.tag == "article":
            cid = el.get("cid") or el.get("id")
            articles_by_cid.setdefault(cid, []).append(el)

    # Second pass: iterate in document order
    bloques: list[Bloque] = []
    seen_cids: set[str] = set()

    for el in elements:
        if el.tag == "section":
            bloque = _parse_section_bloque(el)
            if bloque is not None:
                bloques.append(bloque)

        elif el.tag == "article":
            cid = el.get("cid") or el.get("id")
            if cid in seen_cids:
                continue
            seen_cids.add(cid)

            bloque = _parse_article_bloque(cid, articles_by_cid[cid])
            if bloque is not None:
                bloques.append(bloque)

    return bloques


def _parse_section_bloque(section_el: etree._Element) -> Bloque | None:
    """Creates a section Bloque (heading) from a <section> element."""
    titre = section_el.get("titre", "")
    if not titre:
        return None

    debut = _parse_date_legi(section_el.get("debut", ""))
    if debut is None:
        return None

    niv = section_el.get("niv", "1")
    css_class = _SECTION_NIV_CSS.get(niv, "seccion")

    versions: list[Version] = [
        Version(
            id_norma=section_el.get("id", ""),
            fecha_publicacion=debut,
            fecha_vigencia=debut,
            paragraphs=(Paragraph(css_class=css_class, text=titre),),
        )
    ]

    # If the section was repealed, add an empty version at the end date
    etat = section_el.get("etat", "")
    if etat in ("ABROGE", "ABROGE_DIFF"):
        fin = _parse_date_legi(section_el.get("fin", ""))
        if fin is not None:
            versions.append(
                Version(
                    id_norma=section_el.get("id", ""),
                    fecha_publicacion=fin,
                    fecha_vigencia=fin,
                    paragraphs=(),
                )
            )

    return Bloque(
        id=section_el.get("id", ""),
        tipo="section",
        titulo=titre,
        versions=tuple(versions),
    )


def _parse_article_bloque(cid: str, article_els: list[etree._Element]) -> Bloque | None:
    """Creates an article Bloque with all its historical versions."""
    versions: list[Version] = []
    max_fin: date | None = None
    all_abrogated = True

    for art_el in sorted(article_els, key=lambda e: e.get("debut", "")):
        etat = art_el.get("etat", "")
        debut = _parse_date_legi(art_el.get("debut", ""))
        fin_date = _parse_date_legi(art_el.get("fin", ""))

        if debut is None:
            continue

        if etat == "VIGUEUR":
            all_abrogated = False

        if fin_date is not None:
            max_fin = max(max_fin, fin_date) if max_fin else fin_date

        paragraphs = _extract_contenu_paragraphs(art_el)
        if not paragraphs:
            continue

        # Source of the modification (JORFTEXT of the modifying text)
        source = art_el.find("source_modif")
        id_norma = (source.get("id", "") if source is not None else "") or art_el.get("id", "")

        versions.append(Version(
            id_norma=id_norma,
            fecha_publicacion=debut,
            fecha_vigencia=debut,
            paragraphs=tuple(paragraphs),
        ))

    if not versions:
        return None

    # If all versions are repealed, add an empty version at the end
    if all_abrogated and max_fin is not None:
        versions.append(Version(
            id_norma="",
            fecha_publicacion=max_fin,
            fecha_vigencia=max_fin,
            paragraphs=(),
        ))

    num = article_els[0].get("num", "")
    titulo = f"Article {num}" if num else cid

    return Bloque(
        id=cid,
        tipo="article",
        titulo=titulo,
        versions=tuple(versions),
    )


# ─────────────────────────────────────────────
# LEGI metadata parser → NormaMetadata
# ─────────────────────────────────────────────


def _text_of(parent: etree._Element, tag: str) -> str:
    """Extracts the text of a sub-element, or '' if it does not exist."""
    el = parent.find(f".//{tag}")
    if el is not None and el.text:
        return el.text.strip()
    return ""


def _parse_etat(etat_str: str) -> EstadoNorma:
    """Converts LEGI ETAT to EstadoNorma."""
    etat = etat_str.upper()
    if etat in ("ABROGE", "ABROGE_DIFF"):
        return EstadoNorma.DEROGADA
    if etat == "MODIFIE":
        return EstadoNorma.PARCIALMENTE_DEROGADA
    return EstadoNorma.VIGENTE


def _build_legifrance_url(norm_id: str, nature: str) -> str:
    """Builds the Légifrance URL for a text."""
    if nature == "CODE":
        return f"https://www.legifrance.gouv.fr/codes/texte_lc/{norm_id}"
    return f"https://www.legifrance.gouv.fr/loda/id/{norm_id}"


def _titulo_corto_fr(titulo: str) -> str:
    """Generates a short title for French texts.

    "Code civil" → "Code civil"
    "Constitution du 4 octobre 1958" → "Constitution"
    "Loi n° 2024-123 du 1er mars 2024 relative à..." → "Loi n° 2024-123"
    """
    if not titulo:
        return titulo

    # Constitution → shorten
    if titulo.lower().startswith("constitution"):
        return "Constitution"

    # Laws with number → truncate at "du" (the date)
    for prefix in ("Loi n°", "Loi organique n°", "Ordonnance n°", "Décret n°"):
        if titulo.startswith(prefix):
            # Keep up to the number
            parts = titulo.split(" du ", 1)
            return parts[0].strip()

    # Codes → return as-is (already short)
    return titulo


def _parse_metadatos_legi(xml_data: bytes, norm_id: str) -> NormaMetadata:
    """Parses metadata from a LEGI structure file.

    Extracts information from META/META_COMMUN and META/META_SPEC.
    """
    root = etree.fromstring(xml_data)

    # Extract fields from META
    nature = _text_of(root, "NATURE")
    titulo = (
        _text_of(root, "TITRE_TEXTE")
        or _text_of(root, "TITREFULL")
        or _text_of(root, "TITRE")
        or norm_id
    )
    identificador = _text_of(root, "ID") or norm_id
    etat = _text_of(root, "ETAT")

    # Dates — in the actual dump, DATE_PUBLI for codes is usually 2999-01-01
    # For codes, look for debut of the first VERSION
    fecha_pub_str = _text_of(root, "DATE_PUBLI")
    fecha_pub = _parse_date_legi(fecha_pub_str)
    if fecha_pub is None:
        fecha_pub = _parse_date_legi(_text_of(root, "DATE_TEXTE"))
    if fecha_pub is None:
        # Fallback: debut from LIEN_TXT in VERSIONS
        for lien_txt in root.iter("LIEN_TXT"):
            fecha_pub = _parse_date_legi(lien_txt.get("debut", ""))
            if fecha_pub is not None:
                break
    if fecha_pub is None:
        fecha_pub = _parse_date_legi(_text_of(root, "DATE_DEBUT"))
    if fecha_pub is None:
        raise ValueError(f"Could not extract publication date for {norm_id}")

    fecha_modif_str = _text_of(root, "DERNIERE_MODIFICATION")
    fecha_modif = _parse_date_legi(fecha_modif_str)

    # Rank
    rango = _NATURE_TO_RANGO.get(nature, Rango.OTRO)

    # Autorite / Ministere as department
    departamento = _text_of(root, "AUTORITE") or _text_of(root, "MINISTERE") or ""

    # Source URL
    fuente = _build_legifrance_url(identificador, nature)

    titulo_corto = _titulo_corto_fr(titulo)

    return NormaMetadata(
        titulo=titulo,
        titulo_corto=titulo_corto,
        identificador=identificador,
        pais="fr",
        rango=rango,
        fecha_publicacion=fecha_pub,
        estado=_parse_etat(etat),
        departamento=departamento,
        fuente=fuente,
        fecha_ultima_modificacion=fecha_modif,
    )


# ─────────────────────────────────────────────
# Public classes (TextParser/MetadataParser interface)
# ─────────────────────────────────────────────


class LEGITextParser(TextParser):
    """Parses the combined LEGI XML into Bloque objects."""

    def parse_texto(self, data: bytes) -> list[Any]:
        return _parse_legi_combined(data)

    def extract_reforms(self, data: bytes) -> list[Any]:
        bloques = _parse_legi_combined(data)
        from legalize.transformer.xml_parser import extract_reforms
        return extract_reforms(bloques)


class LEGIMetadataParser(MetadataParser):
    """Parses metadata from a LEGI structure file."""

    def parse(self, data: bytes, norm_id: str) -> NormaMetadata:
        return _parse_metadatos_legi(data, norm_id)
