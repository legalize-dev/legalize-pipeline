"""Parser for Austrian RIS XML documents and API metadata.

The RIS XML format uses the BKA namespace: http://www.bka.gv.at
Each NOR document represents one paragraph/article.
The API JSON metadata groups NOR entries by Gesetzesnummer.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any
from xml.etree import ElementTree as ET

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import (
    Bloque,
    EstadoNorma,
    NormaMetadata,
    Paragraph,
    Rango,
    Version,
)

NS = {"r": "http://www.bka.gv.at"}

# Map RIS Typ codes to Rango values
RIS_TYP_TO_RANGO: dict[str, str] = {
    "BVG": "bundesverfassungsgesetz",
    "G": "bundesgesetz",
    "V": "verordnung",
    "K": "kundmachung",
    "E": "erlass",
    "Vertrag": "staatsvertrag",
}

_SKIP_CT = frozenset({
    "kurztitel", "kundmachungsorgan", "typ", "artikel_anlage",
    "ikra", "akra", "index", "schlagworte", "geaendert",
    "gesnr", "doknr", "adoknr",
})


def _parse_date(s: str) -> date | None:
    """Parse YYYY-MM-DD or DD.MM.YYYY date strings."""
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


def _elem_to_paragraphs(nutzdaten: ET.Element) -> list[Paragraph]:
    """Convert RIS XML nutzdaten into a list of Paragraph objects."""
    paragraphs: list[Paragraph] = []

    for el in nutzdaten.iter():
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        ct = el.get("ct", "")

        if tag == "absatz" and ct not in _SKIP_CT:
            text = "".join(el.itertext()).strip()
            if text:
                typ = el.get("typ", "abs")
                paragraphs.append(Paragraph(css_class=typ, text=text))

        elif tag == "listelem" and ct == "text":
            sym_el = el.find("r:symbol", NS)
            sym = ("".join(sym_el.itertext()).strip() + " ") if sym_el is not None else ""
            parts: list[str] = []
            if el.text and el.text.strip():
                parts.append(el.text.strip())
            for child in el:
                ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if ctag != "symbol":
                    parts.append("".join(child.itertext()).strip())
            body = " ".join(p for p in parts if p)
            if body:
                paragraphs.append(Paragraph(css_class="listelem", text=f"{sym}{body}"))

        elif tag == "schlussteil":
            text = "".join(el.itertext()).strip()
            if text:
                paragraphs.append(Paragraph(css_class="schlussteil", text=text))

    return paragraphs


class RISTextParser(TextParser):
    """Parses a single RIS XML document (one NOR = one paragraph) into Bloque objects."""

    def parse_texto(self, data: bytes) -> list[Any]:
        """Parse a NOR XML into a single Bloque with one Version."""
        root = ET.fromstring(data)
        nutzdaten = root.find(".//r:nutzdaten", NS)
        if nutzdaten is None:
            return []

        nor_id = self._extract_ct(nutzdaten, "doknr") or "unknown"
        para_label = self._extract_ct(nutzdaten, "artikel_anlage") or nor_id
        ikra_str = self._extract_ct(nutzdaten, "ikra")
        pub_date = _parse_date(ikra_str) or date(1900, 1, 1)

        paragraphs = _elem_to_paragraphs(nutzdaten)

        version = Version(
            id_norma=nor_id,
            fecha_publicacion=pub_date,
            fecha_vigencia=pub_date,
            paragraphs=tuple(paragraphs),
        )

        bloque = Bloque(
            id=nor_id,
            tipo="paragraph",
            titulo=para_label,
            versions=(version,),
        )
        return [bloque]

    def extract_reforms(self, data: bytes) -> list[Any]:
        """Extract reform points from RIS XML.

        Full reform history requires cross-referencing the Novellen endpoint
        (a separate API call per Gesetz). Returns empty list for now.
        """
        root = ET.fromstring(data)
        nutzdaten = root.find(".//r:nutzdaten", NS)
        if nutzdaten is None:
            return []
        return []

    @staticmethod
    def _extract_ct(nutzdaten: ET.Element, ct_value: str) -> str:
        """Extract text of an absatz with a specific ct attribute."""
        for el in nutzdaten.findall(".//r:absatz", NS):
            if el.get("ct") == ct_value:
                return "".join(el.itertext()).strip()
        return ""


class RISMetadataParser(MetadataParser):
    """Parses RIS API JSON metadata into NormaMetadata."""

    def parse(self, data: bytes, norm_id: str) -> NormaMetadata:
        """Parse the JSON API response for a Gesetzesnummer into NormaMetadata.

        norm_id is the Gesetzesnummer (e.g. '10002333').
        """
        api_data = json.loads(data)
        refs = api_data["OgdSearchResult"]["OgdDocumentResults"].get("OgdDocumentReference", [])
        if isinstance(refs, dict):
            refs = [refs]

        # Prefer the Norm (header) entry; fall back to first entry
        norm_ref = next(
            (
                r for r in refs
                if r["Data"]["Metadaten"]["Bundesrecht"]["BrKons"].get("Dokumenttyp") == "Norm"
            ),
            refs[0] if refs else None,
        )
        if not norm_ref:
            raise ValueError(f"No metadata found for Gesetzesnummer {norm_id}")

        br = norm_ref["Data"]["Metadaten"]["Bundesrecht"]
        brkons = br["BrKons"]
        allgemein = norm_ref["Data"]["Metadaten"].get("Allgemein", {})

        kurztitel = br.get("Kurztitel", "").strip()
        titel = _strip_html(br.get("Titel", kurztitel))

        # Normalize Typ — handle compound types like "Vertrag – Schweiz"
        typ_raw = brkons.get("Typ", "")
        typ_key = typ_raw.split("\u2013")[0].split("-")[0].strip()
        rango_str = RIS_TYP_TO_RANGO.get(typ_key, "sonstige")

        ikra = _parse_date(brkons.get("Inkrafttretensdatum", ""))
        akra = _parse_date(brkons.get("Ausserkrafttretensdatum", ""))
        estado = EstadoNorma.DEROGADA if akra else EstadoNorma.VIGENTE

        geaendert = _parse_date(allgemein.get("Geaendert", ""))
        eli_url = br.get("Eli", "") or brkons.get("GesamteRechtsvorschriftUrl", "")
        bgbl = brkons.get("Kundmachungsorgan", "")

        indizes = brkons.get("Indizes", {})
        if isinstance(indizes, dict):
            items = indizes.get("item", [])
            materias: tuple[str, ...] = (items,) if isinstance(items, str) else tuple(items)
        else:
            materias = ()

        return NormaMetadata(
            titulo=titel,
            titulo_corto=kurztitel,
            identificador=f"AT-{norm_id}",
            pais="at",
            rango=Rango(rango_str),
            fecha_publicacion=ikra or date(1900, 1, 1),
            estado=estado,
            departamento="BKA (Bundeskanzleramt)",
            fuente=eli_url,
            fecha_ultima_modificacion=geaendert,
            materias=materias,
            notas=bgbl,
        )
