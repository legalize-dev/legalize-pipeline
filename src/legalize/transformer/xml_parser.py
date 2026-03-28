"""Parser for BOE consolidated legislation XML.

Converts the XML from endpoint /api/legislacion-consolidada/id/{id}/texto
into domain data models (Bloque, Version, Reform).

Generalized from scripts/parser.py — works with any norm,
not just the Constitution.
"""

from __future__ import annotations

from datetime import date

from lxml import etree

from legalize.models import Bloque, Paragraph, Reform, Version


def _parse_date(fecha_str: str) -> date | None:
    """Converts YYYYMMDD → date. Handles invalid BOE dates (e.g.: 99999999).

    Returns None for sentinel values like 99999999 (indefinite validity).
    """
    if not fecha_str or fecha_str.strip() in ("", "99999999"):
        return None
    try:
        parsed = date(int(fecha_str[:4]), int(fecha_str[4:6]), int(fecha_str[6:8]))
        # Reject dates in the future beyond a reasonable margin (BOE data quality issue)
        if parsed.year > 2100:
            return None
        return parsed
    except ValueError:
        return None


def _extract_text(element: etree._Element) -> str:
    """Extracts all text from an element, including sub-elements.

    Handles <a>, <b>, <i>, <em>, <strong>, <span> and other inline elements.
    Preserves bold/italic formatting with Markdown markers.
    """
    parts: list[str] = []

    if element.text:
        parts.append(element.text)

    for child in element:
        tag = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""

        # Inline formatting → Markdown
        if tag in ("b", "strong"):
            inner = _extract_text(child)
            if inner.strip():
                parts.append(f"**{inner.strip()}**")
        elif tag in ("i", "em"):
            inner = _extract_text(child)
            if inner.strip():
                parts.append(f"*{inner.strip()}*")
        else:
            # <a>, <span>, etc. → just extract text
            inner = _extract_text(child)
            if inner:
                parts.append(inner)

        if child.tail:
            parts.append(child.tail)

    return "".join(parts)


def parse_texto_xml(xml_data: bytes | str) -> list[Bloque]:
    """Parses the BOE consolidated text XML and returns a list of Bloque.

    Args:
        xml_data: Raw XML from the /texto endpoint (bytes or string).

    Returns:
        List of Bloque with their historical versions.
    """
    if isinstance(xml_data, str):
        xml_data = xml_data.encode("utf-8")

    root = etree.fromstring(xml_data)
    bloques: list[Bloque] = []

    for bloque_el in root.iter("bloque"):
        versions: list[Version] = []

        for version_el in bloque_el.findall("version"):
            paragraphs: list[Paragraph] = []

            for p_el in version_el.findall("p"):
                css_class = p_el.get("class", "")

                # Skip footnotes (reform metadata, not legal text)
                if "nota_pie" in css_class:
                    continue

                text = _extract_text(p_el)
                if text.strip():
                    paragraphs.append(Paragraph(css_class=css_class, text=text.strip()))

            fecha_pub = version_el.get("fecha_publicacion", "")
            fecha_vig = version_el.get("fecha_vigencia", "")

            if not fecha_pub:
                continue

            parsed_pub = _parse_date(fecha_pub)
            if parsed_pub is None:
                continue

            parsed_vig = _parse_date(fecha_vig) if fecha_vig else parsed_pub

            versions.append(Version(
                id_norma=version_el.get("id_norma", ""),
                fecha_publicacion=parsed_pub,
                fecha_vigencia=parsed_vig if parsed_vig is not None else parsed_pub,
                paragraphs=tuple(paragraphs),
            ))

        bloques.append(Bloque(
            id=bloque_el.get("id", ""),
            tipo=bloque_el.get("tipo", ""),
            titulo=bloque_el.get("titulo", ""),
            versions=tuple(versions),
        ))

    return bloques


def extract_reforms(bloques: list[Bloque]) -> list[Reform]:
    """Extracts the list of unique reforms sorted chronologically.

    Each reform is a point in time where at least one block changed.
    The first "reform" is always the original publication.
    """
    reform_map: dict[tuple[date, str], list[str]] = {}

    for bloque in bloques:
        for version in bloque.versions:
            key = (version.fecha_publicacion, version.id_norma)
            if key not in reform_map:
                reform_map[key] = []
            reform_map[key].append(bloque.id)

    reforms = [
        Reform(
            fecha=fecha,
            id_norma=id_norma,
            bloques_afectados=tuple(bloque_ids),
        )
        for (fecha, id_norma), bloque_ids in sorted(reform_map.items())
    ]

    return reforms


def get_bloque_at_date(bloque: Bloque, target_date: date) -> Version | None:
    """Returns the version of a block in effect at target_date."""
    applicable = [v for v in bloque.versions if v.fecha_publicacion <= target_date]
    if not applicable:
        return None
    return max(applicable, key=lambda v: v.fecha_publicacion)
