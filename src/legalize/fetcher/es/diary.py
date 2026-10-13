"""As-enacted BOE Section I text and explicit fidelity exclusions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import re
from urllib.parse import urljoin

from lxml import etree

from legalize.fetcher._text import clean
from legalize.fetcher.es.metadata import _AMENDING_CODES, parse_metadata
from legalize.models import ParsedNorm, Reform, TextState
from legalize.transformer.xml_parser import extract_reforms, parse_text_xml

_EXCLUDED_RANKS = {"1590", "1240", "1250", "63"}
_SIGNATURE = re.compile(
    r"^[^,\n]{2,60},\s*\d{1,2} de [a-záéíóú]+ de \d{4}\.\s*[.–—-]+\s*(?:El|La) (?:Ministr[oa]|President[ea]|Lehendakari|Secretari[oa])\b"
)


class ExcludedDiary(ValueError):
    """An out-of-scope or unreadable act, with a durable exclusion reason."""

    def __init__(self, reason: str, identifier: str, **details):
        super().__init__(f"{identifier}: {reason}")
        self.record = {"identifier": identifier, "reason": reason, **details}


def record_exclusion(data_dir: str | Path, exclusion: ExcludedDiary) -> None:
    """One file per ID avoids lost exclusions when bulk workers finish together."""
    path = Path(data_dir) / "excluded" / f"{exclusion.record['identifier']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(exclusion.record, ensure_ascii=False, indent=2) + "\n")


def diary_xml_from_html(page, identifier: str) -> bytes:
    """Normalize original HTML without ELI into the same BOE element vocabulary."""
    bodies = page.xpath('//*[@id="textoxslt"]')
    analyses = page.xpath('//*[@id="analisis"]')
    titles = page.xpath('//*[@class="documento-tit"]')
    if not bodies or not titles:
        raise ValueError(f"{identifier}: incomplete original HTML without ELI")
    analysis = analyses[0] if analyses else etree.Element("div")
    reference_links = analysis.xpath('.//a[contains(@href, "id=")]')
    # ponytail: only identical republication notes are known here; fail on other references.
    if any(
        not (
            link.getparent().tag == "li"
            and link.getparent().text_content().strip().startswith("Publicada además en el BOE")
            and link.getparent().text_content().strip().endswith("con el mismo contenido.")
            and re.fullmatch(r"/buscar/doc\.php\?id=BOE-A-\d{4}-\d+", link.get("href", ""))
        )
        for link in reference_links
    ):
        raise ValueError(f"{identifier}: HTML-only references need explicit parsing")
    fields = {
        dt.text_content().strip().rstrip(":"): dt.getnext().text_content().strip()
        for dt in page.xpath('//*[@class="metadatos"]//dt')
    }
    if fields.get("Referencia") != identifier:
        raise ValueError(f"{identifier}: HTML identity mismatch")
    if not fields.get("Sección", "").startswith("I."):
        raise ExcludedDiary("outside-section-i", identifier)
    department = fields.get("Departamento", "")
    jurisdiction = {"Comunidad Autónoma de la Región de Murcia": "es-mc"}.get(department)
    if department.startswith(("Comunidad", "Comunitat")) and not jurisdiction:
        raise ValueError(f"{identifier}: HTML-only jurisdiction needs explicit mapping")
    facts = dict(
        item.text_content().split(": ", 1)
        for item in analysis.xpath("./ul[1]/li")
        if ": " in item.text_content()
    )
    title = titles[0].text_content().strip()
    if "Rango" not in facts:
        from legalize.fetcher.es.metadata import _RANK_TEXT_MAP

        facts["Rango"] = next(
            (
                rank
                for rank in sorted(_RANK_TEXT_MAP, key=len, reverse=True)
                if title.lower().startswith(rank + " ")
            ),
            "",
        )
        if not facts["Rango"]:
            raise ValueError(f"{identifier}: original HTML has no explicit rank")
    root = etree.Element("documento", source_format="html")
    if jurisdiction:
        root.set("jurisdiction", jurisdiction)
    meta = etree.SubElement(root, "metadatos")
    values = {
        "identificador": identifier,
        "titulo": title,
        "seccion": "1",
        "departamento": fields.get("Departamento", ""),
        "rango": facts["Rango"],
        "url_html_consolidada": f"https://www.boe.es/buscar/doc.php?id={identifier}",
    }
    pages = re.search(r"páginas (\d+) a (\d+)", fields.get("Publicado en", ""))
    if pages:
        values.update(pagina_inicial=pages[1], pagina_final=pages[2])
    for label, key in (
        ("Fecha de disposición", "fecha_disposicion"),
        ("Fecha de publicación", "fecha_publicacion"),
        ("Fecha de entrada en vigor", "fecha_vigencia"),
    ):
        if facts.get(label):
            values[key] = datetime.strptime(facts[label], "%d/%m/%Y").strftime("%Y%m%d")
    for label, key in (("puntoPDF", "url_pdf"), ("puntoEpub", "url_epub")):
        links = page.xpath(f'//li[@class="{label}"]/a/@href')
        if links:
            values[key] = urljoin("https://www.boe.es", links[0])
    if "fecha_publicacion" not in values:
        published = re.search(r"/boe/dias/(\d{4})/(\d{2})/(\d{2})/pdfs/", values.get("url_pdf", ""))
        if not published:
            raise ValueError(f"{identifier}: original HTML has no publication date")
        values["fecha_publicacion"] = "".join(published.groups())
    for key, value in values.items():
        etree.SubElement(meta, key).text = value
    subjects = etree.SubElement(etree.SubElement(root, "analisis"), "materias")
    for item in analysis.xpath('./h5[normalize-space()="Materias"]/following-sibling::ul[1]/li'):
        etree.SubElement(subjects, "materia").text = item.text_content().strip()
    etree.SubElement(root, "source_html_metadata").text = json.dumps(
        {
            "fields": fields,
            "analysis": "".join(analysis.itertext()).strip(),
            "analysis_links": analysis.xpath(".//a/@href"),
            "format_urls": page.xpath('//ul[@class="enlaces-doc"]//a/@href'),
        },
        ensure_ascii=False,
    )
    text = deepcopy(bodies[0])
    text.tag = "texto"
    for element in text.iter():
        if isinstance(element.tag, str) and re.fullmatch("h[1-6]", element.tag):
            element.tag = "p"
    if any(
        isinstance(child.tag, str)
        and child.tag not in {"p", "table", "ol", "ul", "img", "pre", "blockquote"}
        for child in text
    ):
        raise ValueError(f"{identifier}: unsupported original HTML body element")
    root.append(text)
    return etree.tostring(root)


def fetch_diary(client, identifier: str, *, xml_data: bytes | None = None) -> ParsedNorm:
    """Retain the original body and date each amendment from its official record."""
    raw = xml_data if xml_data is not None else client.get_disposition_xml(identifier)
    norm = parse_diary(raw, identifier)
    root = etree.fromstring(raw)
    reforms = list(norm.reforms)
    seen = {identifier}
    for ref in root.findall("analisis/referencias/posteriores/posterior"):
        word = ref.find("palabra")
        source_id = ref.get("referencia", "")
        if word is None or word.get("codigo") not in _AMENDING_CODES or source_id in seen:
            continue
        if not source_id.startswith("BOE-"):
            continue
        published = client.get_publication_date(source_id)
        reforms.append(
            Reform(
                published,
                source_id,
                (),
                change_note=" ".join(ref.itertext()).strip(),
            )
        )
        seen.add(source_id)
    reforms.sort(key=lambda reform: (reform.date, reform.norm_id))
    return replace(norm, reforms=tuple(reforms))


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
    if root.get("source_format") == "html":
        extra.extend(
            (
                ("source_format", "html"),
                ("source_html_metadata", root.findtext("source_html_metadata", "")),
            )
        )
    metadata = replace(
        metadata,
        text_state=TextState.AS_ENACTED,
        jurisdiction=root.get("jurisdiction") or metadata.jurisdiction,
        extra=tuple(extra),
    )
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
        child = deepcopy(child)
        if child.tag == "p" and _SIGNATURE.match(" ".join("".join(child.itertext()).split())):
            child.set("class", "firma")
        if child.tag == "table" and any(
            img.get("data-pdf", "").lower().startswith("firma_") for img in child.iter("img")
        ):
            for cell in child.iter("td"):
                name = (cell.text or "").strip()
                if len(cell) == 0 and name.isupper() and len(name.split()) >= 2:
                    cell.text = None
                    etree.SubElement(cell, "strong").text = name
        version.append(child)
    blocks = parse_text_xml(etree.tostring(wrapper))
    if not blocks or not any(v.paragraphs for b in blocks for v in b.versions):
        raise ValueError(f"{identifier}: source text produced no paragraphs")
    return ParsedNorm(metadata, tuple(blocks), tuple(extract_reforms(blocks)))
