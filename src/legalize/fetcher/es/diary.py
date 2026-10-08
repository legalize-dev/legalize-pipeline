"""As-enacted BOE Section I text and explicit fidelity exclusions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import re

from lxml import etree

from legalize.fetcher._text import clean
from legalize.fetcher.es.metadata import parse_metadata
from legalize.models import ParsedNorm, TextState
from legalize.transformer.xml_parser import extract_reforms, parse_text_xml

_EXCLUDED_RANKS = {"1590", "1240", "1250", "63"}


class ExcludedDiary(ValueError):
    """An out-of-scope or unreadable act, with a durable exclusion reason."""

    def __init__(self, reason: str, identifier: str, **details):
        super().__init__(f"{identifier}: {reason}")
        self.record = {"identifier": identifier, "reason": reason, **details}


def parse_diary(xml_data: bytes, identifier: str) -> ParsedNorm:
    """Parse the original publication without claiming the text is consolidated."""
    root = etree.fromstring(clean(xml_data).encode("utf-8"))
    meta = root.find("metadatos")
    if meta is None:
        raise ValueError(f"{identifier}: diary metadata missing")
    source_id = meta.findtext("identificador")
    if source_id and source_id != identifier:
        raise ValueError(f"{identifier}: diary returned {source_id}")
    if meta.findtext("seccion") != "1":
        raise ExcludedDiary("outside-section-i", identifier)
    rank = meta.find("rango")
    rank_code = rank.get("codigo", "") if rank is not None else ""
    words = root.findall("analisis/referencias/anteriores/anterior/palabra")
    correction = any(
        (word.text or "").strip().upper().startswith(("CORRECCIÓN", "CORRIGE")) for word in words
    )
    if rank_code in _EXCLUDED_RANKS or correction:
        raise ExcludedDiary("judicial-or-correction", identifier, rank_code=rank_code)

    # References also contain <texto>; only the direct child is the act itself.
    text = root.find("texto")
    if text is None or not "".join(text.itertext()).strip():
        raise ExcludedDiary("empty-text", identifier)
    chars = len(" ".join("".join(text.itertext()).split()))
    images = len(text.findall(".//img"))
    first, last = meta.findtext("pagina_inicial", ""), meta.findtext("pagina_final", "")
    pages = int(last) - int(first) + 1 if first.isdigit() and last.isdigit() else 0
    if pages > 0 and images >= 5 and chars / pages < 600:
        raise ExcludedDiary(
            "low-density",
            identifier,
            pages=pages,
            chars=chars,
            chars_per_page=round(chars / pages, 2),
            images=images,
            rank_code=rank_code,
            title=meta.findtext("titulo"),
            publication_date=meta.findtext("fecha_publicacion"),
        )

    metadata = parse_metadata(xml_data, identifier, diario_xml=xml_data)
    has_articles = bool(text.xpath('.//p[@class="articulo"]')) or bool(
        re.search(r"(?im)^\s*Art[ií]culo\s+(?:\d+|[uú]nico)", "\n".join(text.itertext()))
    )
    extra = [(key, value) for key, value in metadata.extra if key != "source_notice"]
    extra.append(("has_articles", "true" if has_articles else "false"))
    metadata = replace(metadata, text_state=TextState.AS_ENACTED, extra=tuple(extra))
    # Reuse the complete BOE element dispatcher, including tables and quotations.
    wrapper = etree.Element("texto")
    block = etree.SubElement(wrapper, "bloque", id="original", tipo="texto", titulo="")
    version = etree.SubElement(
        block,
        "version",
        id_norma=identifier,
        fecha_publicacion=metadata.publication_date.strftime("%Y%m%d"),
    )
    for child in text:
        version.append(deepcopy(child))
    blocks = parse_text_xml(etree.tostring(wrapper))
    if not blocks or not any(v.paragraphs for b in blocks for v in b.versions):
        raise ValueError(f"{identifier}: source text produced no paragraphs")
    return ParsedNorm(metadata, tuple(blocks), tuple(extract_reforms(blocks)))
