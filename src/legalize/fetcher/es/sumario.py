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

from legalize.fetcher.es.config import ScopeConfig
from legalize.models import Disposition, Rank

logger = logging.getLogger(__name__)

# BOE sections containing relevant legislative dispositions
_LEGISLATIVE_SECTIONS = {"1", "1A", "T"}  # I. Disposiciones generales, TC


def _infer_rank_from_title(title: str) -> Rank | None:
    """Infers the normative rank from a disposition's title."""
    lower = title.lower()
    if lower.startswith("ley orgánica") or lower.startswith("ley organica"):
        return Rank.LEY_ORGANICA
    if lower.startswith("real decreto legislativo"):
        return Rank.REAL_DECRETO_LEGISLATIVO
    if lower.startswith("real decreto-ley"):
        return Rank.REAL_DECRETO_LEY
    if re.match(r"^ley \d+/\d{4}", lower):
        return Rank.LEY
    return None


def parse_summary(xml_data: bytes, scope: ScopeConfig) -> list[Disposition]:
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
        section_code = seccion.get("codigo", "")

        # Only process legislative sections
        if section_code not in _LEGISLATIVE_SECTIONS:
            continue

        for dept_el in seccion.iter("departamento"):
            dept_name = dept_el.get("nombre", "")

            for item in dept_el.iter("item"):
                disposition = _parse_item(item, dept_name, scope)
                if disposition is not None:
                    dispositions.append(disposition)

    logger.info(
        "Summary: %d dispositions in scope out of %d total items",
        len(dispositions),
        _count_items(root),
    )
    return dispositions


def _parse_item(item: etree._Element, department: str, scope: ScopeConfig) -> Disposition | None:
    """Parses a summary <item> and filters it by scope."""
    id_el = item.find("identificador")
    title_el = item.find("titulo")
    url_xml_el = item.find("url_xml")

    if id_el is None or title_el is None:
        return None

    id_boe = id_el.text.strip() if id_el.text else ""
    title = title_el.text.strip() if title_el.text else ""
    url_xml = url_xml_el.text.strip() if url_xml_el is not None and url_xml_el.text else ""

    if not id_boe or not title:
        return None

    # Infer rank from title
    rank = _infer_rank_from_title(title)

    # Filter by ranks in scope (empty list = accept all)
    if scope.ranks and rank is not None and rank not in scope.ranks:
        return None

    # What the disposition *does* is not decided here. A summary title is prose:
    # "por el que se modifica" and "Reforma del apartado 3 del artículo 69" are the
    # same act described two ways, and reading the word told us the fourth reform of
    # the Constitution was a new law. The pipeline asks the source instead — whether
    # the BOE keeps a consolidated text for it, and which norm stamps each block.
    return Disposition(
        id_boe=id_boe,
        title=title,
        rank=rank,
        department=department,
        url_xml=url_xml,
    )


def _count_items(root: etree._Element) -> int:
    """Counts the total number of items in the summary."""
    return len(list(root.iter("item")))
