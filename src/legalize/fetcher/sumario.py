"""Parser for BOE daily summaries.

Converts the response from endpoint /api/boe/sumario/{YYYYMMDD}
into a list of Disposition filtered by project scope.

Actual XML structure:
    <response>
      <data>
        <sumario>
          <metadatos>
            <fecha_publicacion>20260326</fecha_publicacion>
          </metadatos>
          <diario numero="75">
            <seccion codigo="1" nombre="I. Disposiciones generales">
              <departamento codigo="4335" nombre="MINISTERIO DE SANIDAD">
                <epigrafe nombre="Establecimientos sanitarios">
                  <item>
                    <identificador>BOE-A-2026-6975</identificador>
                    <titulo>Real Decreto 239/2026, de 25 de marzo, por el que...</titulo>
                    <url_xml>https://www.boe.es/diario_boe/xml.php?id=BOE-A-2026-6975</url_xml>
                  </item>
                </epigrafe>
              </departamento>
            </seccion>
          </diario>
        </sumario>
      </data>
    </response>
"""

from __future__ import annotations

import logging
import re

from lxml import etree

from legalize.config import ScopeConfig
from legalize.models import Disposition, Rango

logger = logging.getLogger(__name__)

# BOE sections containing relevant legislative dispositions
_SECCIONES_LEGISLATIVAS = {"1", "1A", "T"}  # I. Disposiciones generales, TC


def _infer_rango_from_titulo(titulo: str) -> Rango | None:
    """Infers the normative rank from a disposition's title."""
    lower = titulo.lower()
    if lower.startswith("ley orgánica") or lower.startswith("ley organica"):
        return Rango.LEY_ORGANICA
    if lower.startswith("real decreto legislativo"):
        return Rango.REAL_DECRETO_LEGISLATIVO
    if lower.startswith("real decreto-ley"):
        return Rango.REAL_DECRETO_LEY
    if re.match(r"^ley \d+/\d{4}", lower):
        return Rango.LEY
    return None


def _is_correccion(titulo: str) -> bool:
    """Detects whether this is an error correction."""
    lower = titulo.lower()
    return "corrección de errores" in lower or "correccion de errores" in lower


def _extract_norma_afectada(titulo: str) -> list[str]:
    """Attempts to extract BOE-IDs of affected norms from the title.

    Looks for patterns like 'por el que se modifica la Ley...' but
    cannot resolve the BOE-ID from the title alone — this requires
    querying the API. Returns an empty list for now.
    """
    # Summary titles do not contain BOE-IDs directly.
    # Affected norm resolution is done in the pipeline when
    # downloading the consolidated text.
    return []


def parse_sumario(xml_data: bytes, scope: ScopeConfig) -> list[Disposition]:
    """Parses a BOE daily summary and filters by scope.

    Args:
        xml_data: Raw XML from endpoint /api/boe/sumario/{fecha}.
        scope: Scope configuration (included ranks, etc.).

    Returns:
        List of Disposition within scope.
    """
    root = etree.fromstring(xml_data)
    dispositions: list[Disposition] = []

    # Iterate sections → departments → headings → items
    for seccion in root.iter("seccion"):
        seccion_code = seccion.get("codigo", "")

        # Only process legislative sections
        if seccion_code not in _SECCIONES_LEGISLATIVAS:
            continue

        for departamento in seccion.iter("departamento"):
            dept_nombre = departamento.get("nombre", "")

            for item in departamento.iter("item"):
                disposition = _parse_item(item, dept_nombre, scope)
                if disposition is not None:
                    dispositions.append(disposition)

    logger.info("Summary: %d dispositions in scope out of %d total items",
                len(dispositions), _count_items(root))
    return dispositions


def _parse_item(item: etree._Element, departamento: str, scope: ScopeConfig) -> Disposition | None:
    """Parses a summary <item> and filters it by scope."""
    id_el = item.find("identificador")
    titulo_el = item.find("titulo")
    url_xml_el = item.find("url_xml")

    if id_el is None or titulo_el is None:
        return None

    id_boe = id_el.text.strip() if id_el.text else ""
    titulo = titulo_el.text.strip() if titulo_el.text else ""
    url_xml = url_xml_el.text.strip() if url_xml_el is not None and url_xml_el.text else ""

    if not id_boe or not titulo:
        return None

    # Infer rank from title
    rango = _infer_rango_from_titulo(titulo)

    # Filter by ranks in scope (empty list = accept all)
    if scope.rangos and rango is not None and rango not in scope.rangos:
        return None

    # If we cannot infer the rank, include it only if it's section 1
    # (general dispositions) — we'll filter later when downloading metadata
    es_correccion = _is_correccion(titulo)
    es_nueva = not es_correccion and "modifica" not in titulo.lower()

    return Disposition(
        id_boe=id_boe,
        titulo=titulo,
        rango=rango,
        departamento=departamento,
        url_xml=url_xml,
        normas_afectadas=tuple(_extract_norma_afectada(titulo)),
        es_nueva=es_nueva,
        es_correccion=es_correccion,
    )


def _count_items(root: etree._Element) -> int:
    """Counts the total number of items in the summary."""
    return len(list(root.iter("item")))
