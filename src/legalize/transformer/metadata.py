"""Parser for BOE norm metadata.

Converts the response from endpoint /api/legislacion-consolidada/id/{id}/metadatos
into a domain NormaMetadata.

Actual API structure (XML):
    <response>
      <status><code>200</code></status>
      <data>
        <metadatos>
          <identificador>BOE-A-1978-31229</identificador>
          <departamento codigo="1220">Cortes Generales</departamento>
          <rango codigo="1070">Constitución</rango>
          <fecha_disposicion>19781227</fecha_disposicion>
          <titulo>Constitución Española.</titulo>
          <fecha_publicacion>19781229</fecha_publicacion>
          <fecha_vigencia>19781229</fecha_vigencia>
          <estatus_derogacion>N</estatus_derogacion>
          <estado_consolidacion codigo="3">Finalizado</estado_consolidacion>
          <url_eli>https://www.boe.es/eli/es/c/1978/12/27/(1)</url_eli>
          <url_html_consolidada>https://www.boe.es/buscar/act.php?id=BOE-A-1978-31229</url_html_consolidada>
        </metadatos>
      </data>
    </response>
"""

from __future__ import annotations

import logging
from datetime import date

from lxml import etree

from legalize.models import EstadoNorma, NormaMetadata, Rango
from legalize.transformer.titulos import get_titulo_corto

logger = logging.getLogger(__name__)

# Mapping of BOE rank texts (case-insensitive) to our enum
_RANGO_MAP: dict[str, Rango] = {
    "constitución": Rango.CONSTITUCION,
    "constitucion": Rango.CONSTITUCION,
    "ley orgánica": Rango.LEY_ORGANICA,
    "ley organica": Rango.LEY_ORGANICA,
    "ley": Rango.LEY,
    "real decreto-ley": Rango.REAL_DECRETO_LEY,
    "real decreto legislativo": Rango.REAL_DECRETO_LEGISLATIVO,
    "real decreto": Rango.REAL_DECRETO,
    "orden": Rango.ORDEN,
    "resolución": Rango.RESOLUCION,
    "resolucion": Rango.RESOLUCION,
    "acuerdo internacional": Rango.ACUERDO_INTERNACIONAL,
    "circular": Rango.CIRCULAR,
    "instrucción": Rango.INSTRUCCION,
    "instruccion": Rango.INSTRUCCION,
    "decreto": Rango.DECRETO,
    "acuerdo": Rango.ACUERDO,
    "reglamento": Rango.REGLAMENTO,
    "decreto-ley": Rango.REAL_DECRETO_LEY,
}

# Mapping of BOE rank codes to our enum
_RANGO_CODE_MAP: dict[str, Rango] = {
    "1070": Rango.CONSTITUCION,
    "1010": Rango.LEY_ORGANICA,
    "1020": Rango.LEY,
    "1040": Rango.REAL_DECRETO_LEY,
    "1050": Rango.REAL_DECRETO_LEGISLATIVO,
    "1290": Rango.LEY_ORGANICA,  # alternate code
    "1300": Rango.LEY,  # alternate code
    "1060": Rango.REAL_DECRETO,
    "1080": Rango.ORDEN,
    "1130": Rango.RESOLUCION,
    "1170": Rango.ACUERDO_INTERNACIONAL,
    "1190": Rango.CIRCULAR,
    "1200": Rango.INSTRUCCION,
    "1030": Rango.DECRETO,
    "1160": Rango.ACUERDO,
}


def _text_of(parent: etree._Element, tag: str) -> str:
    """Extracts the text of a sub-element, or '' if it does not exist."""
    el = parent.find(tag)
    if el is not None and el.text:
        return el.text.strip()
    return ""


def _code_of(parent: etree._Element, tag: str) -> str:
    """Extracts the 'codigo' attribute of a sub-element."""
    el = parent.find(tag)
    if el is not None:
        return el.get("codigo", "")
    return ""


def _parse_date_boe(text: str) -> date | None:
    """Parses BOE date: YYYYMMDD → date. Returns None for 99999999 (indefinite)."""
    if not text or len(text) < 8 or text.strip() == "99999999":
        return None
    try:
        parsed = date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        if parsed.year > 2100:
            return None
        return parsed
    except (ValueError, IndexError):
        logger.warning("Unparseable date: %s", text)
        return None


def _parse_rango(meta: etree._Element) -> Rango | None:
    """Resolves the rank from code or text."""
    code = _code_of(meta, "rango")
    if code and code in _RANGO_CODE_MAP:
        return _RANGO_CODE_MAP[code]

    text = _text_of(meta, "rango").lower()
    return _RANGO_MAP.get(text)


def _parse_estado(meta: etree._Element) -> EstadoNorma:
    """Determines the validity status from BOE flags."""
    derogacion = _text_of(meta, "estatus_derogacion")
    if derogacion == "T":
        return EstadoNorma.DEROGADA
    if derogacion == "P":
        return EstadoNorma.PARCIALMENTE_DEROGADA
    return EstadoNorma.VIGENTE


def _infer_rango_from_titulo(titulo: str) -> Rango | None:
    """Attempts to infer the rank from the title."""
    lower = titulo.lower()
    if "constitución" in lower or "constitucion" in lower:
        return Rango.CONSTITUCION
    if "ley orgánica" in lower or "ley organica" in lower:
        return Rango.LEY_ORGANICA
    if "real decreto legislativo" in lower:
        return Rango.REAL_DECRETO_LEGISLATIVO
    if "real decreto-ley" in lower:
        return Rango.REAL_DECRETO_LEY
    if lower.startswith("ley "):
        return Rango.LEY
    if "real decreto" in lower and "ley" not in lower and "legislativo" not in lower:
        return Rango.REAL_DECRETO
    if lower.startswith("orden"):
        return Rango.ORDEN
    if lower.startswith("resolución") or lower.startswith("resolucion"):
        return Rango.RESOLUCION
    return None


def parse_metadatos(xml_data: bytes, id_boe: str) -> NormaMetadata:
    """Parses the XML response from the BOE /metadatos endpoint.

    Args:
        xml_data: Raw XML from the endpoint.
        id_boe: BOE identifier (fallback if not in XML).

    Returns:
        Parsed NormaMetadata.

    Raises:
        ValueError: If minimum information cannot be extracted.
    """
    root = etree.fromstring(xml_data)

    # Navigate to <metadatos> inside <response><data>
    meta = root.find(".//metadatos")
    if meta is None:
        raise ValueError(f"<metadatos> not found in response for {id_boe}")

    identificador = _text_of(meta, "identificador") or id_boe
    titulo = _text_of(meta, "titulo") or id_boe
    titulo_corto = get_titulo_corto(identificador, titulo)
    departamento = _text_of(meta, "departamento")

    rango = _parse_rango(meta)
    if rango is None:
        rango = _infer_rango_from_titulo(titulo)
    if rango is None:
        logger.warning("Unrecognized rank for %s, using OTRO as fallback", id_boe)
        rango = Rango.OTRO

    fecha_pub = _parse_date_boe(_text_of(meta, "fecha_publicacion"))
    if fecha_pub is None:
        raise ValueError(f"Could not extract publication date for {id_boe}")

    fecha_vigencia = _parse_date_boe(_text_of(meta, "fecha_vigencia"))
    estado = _parse_estado(meta)

    fuente = (
        _text_of(meta, "url_eli")
        or _text_of(meta, "url_html_consolidada")
        or f"https://www.boe.es/buscar/act.php?id={identificador}"
    )

    return NormaMetadata(
        titulo=titulo,
        titulo_corto=titulo_corto,
        identificador=identificador,
        pais="es",
        rango=rango,
        fecha_publicacion=fecha_pub,
        estado=estado,
        departamento=departamento,
        fuente=fuente,
        fecha_ultima_modificacion=fecha_vigencia,
    )
