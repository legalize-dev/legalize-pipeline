"""Parser for Italian Akoma Ntoso 3.0 XML from Normattiva.

Normattiva publishes legislation in Akoma Ntoso 3.0 format. The XML
root is ``<akomaNtoso>`` containing an ``<act>`` element with:

- ``<meta>`` — identification (URN, FRBRWork/Expression/Manifestation),
  publication info, lifecycle events, active/passive modifications
- ``<body>`` — the legislative text, structured as nested elements:
  ``libro`` (book), ``parte`` (part), ``titolo`` (title),
  ``capo`` (chapter), ``sezione`` (section), ``articolo`` (article),
  ``comma`` (numbered paragraph), ``alinea`` (text paragraph)

When ``include_history=True``, the client wraps multiple vigenza
snapshots in a ``<normattiva-multi-vigenza>`` envelope. This parser
detects the envelope and emits multi-``Version`` blocks by diffing
consecutive snapshots.

Inline formatting:
- ``<b>`` / ``<i>`` → bold / italic
- ``<ref>`` → cross-reference links
- ``<mod>`` → amendment markers (text in ``((...))`` double parentheses)
- ``<table>`` → Markdown pipe tables

References:
- Akoma Ntoso 3.0: http://docs.oasis-open.org/legaldocml/akn-core/v1.0/akn-core-v1.0.html
- Normattiva URN: urn:nir:stato:{type}:{date};{number}
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from lxml import etree

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    Rank,
    Version,
)

logger = logging.getLogger(__name__)

AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"
_NS = {"akn": AKN_NS}
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

_RANK_MAP: dict[str, str] = {
    "legge": "legge",
    "decreto.legislativo": "decreto_legislativo",
    "decreto.legge": "decreto_legge",
    "decreto.presidente.repubblica": "decreto_presidente_repubblica",
    "decreto.presidente.consiglio.ministri": "dpcm",
    "regio.decreto": "regio_decreto",
    "regio.decreto.legge": "regio_decreto_legge",
    "legge.costituzionale": "legge_costituzionale",
    "costituzione": "costituzione",
    "decreto.legislativo.del.capo.provvisorio.dello.stato": "decreto_legislativo_cps",
    "decreto.legislativo.luogotenenziale": "decreto_legislativo_luogotenenziale",
    "regolamento": "regolamento",
}

_STATUS_MAP: dict[str, NormStatus] = {
    "in vigore": NormStatus.IN_FORCE,
    "abrogato": NormStatus.REPEALED,
    "decaduto": NormStatus.EXPIRED,
}

_HEADING_TAGS = {
    "book", "part", "title", "chapter", "section", "subSection",
    "libro", "parte", "titolo", "capo", "sezione", "sottoSezione",
}
_ARTICLE_TAGS = {"article", "articolo"}
_COMMA_TAGS = {"paragraph", "comma"}
_PREAMBLE_TAGS = {"preface", "preamble", "conclusions", "preambolo", "formulaIniziale", "formulaFinale", "conclusioni"}


def _clean(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = _CONTROL_CHAR_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    value = value.strip()
    if value in ("", "9999-12-31"):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _extract_text(el: etree._Element) -> str:
    """Recursively extract text from an element, applying inline formatting."""
    parts: list[str] = []
    tag = etree.QName(el.tag).localname if isinstance(el.tag, str) else ""

    if el.text:
        parts.append(_clean(el.text))

    for child in el:
        child_tag = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""

        if child_tag == "b":
            inner = _extract_text(child)
            if inner:
                parts.append(f"**{inner}**")
        elif child_tag == "i":
            inner = _extract_text(child)
            if inner:
                parts.append(f"*{inner}*")
        elif child_tag == "ref":
            inner = _extract_text(child)
            href = child.get("href", "")
            if inner and href:
                parts.append(f"[{inner}]({href})")
            elif inner:
                parts.append(inner)
        elif child_tag == "mod":
            inner = _extract_text(child)
            if inner:
                parts.append(f"(({inner}))")
        elif child_tag == "rref":
            inner = _extract_text(child)
            if inner:
                parts.append(inner)
        elif child_tag == "def":
            inner = _extract_text(child)
            if inner:
                parts.append(inner)
        elif child_tag in ("authorialNote", "note"):
            pass
        elif child_tag == "img":
            pass
        elif child_tag == "table":
            table_md = _render_table(child)
            if table_md:
                parts.append(f"\n\n{table_md}\n\n")
        elif child_tag in ("br", "eol"):
            parts.append("\n")
        else:
            inner = _extract_text(child)
            if inner:
                parts.append(inner)

        if child.tail:
            parts.append(_clean(child.tail))

    return " ".join(p for p in parts if p).strip()


def _render_table(table_el: etree._Element) -> str:
    """Convert an AKN table element to Markdown pipe table."""
    rows: list[list[str]] = []
    for tr in table_el.iter(f"{{{AKN_NS}}}tr"):
        cells: list[str] = []
        for td in tr:
            cell_tag = etree.QName(td.tag).localname if isinstance(td.tag, str) else ""
            if cell_tag in ("th", "td"):
                cells.append(_extract_text(td).replace("|", "\\|"))
        if cells:
            rows.append(cells)

    if not rows:
        return ""

    max_cols = max(len(r) for r in rows)
    for r in rows:
        while len(r) < max_cols:
            r.append("")

    lines: list[str] = []
    lines.append("| " + " | ".join(rows[0]) + " |")
    lines.append("| " + " | ".join("---" for _ in range(max_cols)) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def _parse_single_akn(root: etree._Element) -> tuple[list[Block], dict[str, Any]]:
    """Parse a single AKN document into blocks + raw metadata dict."""
    meta: dict[str, Any] = {}

    meta_el = root.find(f".//{{{AKN_NS}}}meta")
    if meta_el is not None:
        work = meta_el.find(f".//{{{AKN_NS}}}FRBRWork")
        if work is not None:
            uri_el = work.find(f"{{{AKN_NS}}}FRBRuri")
            if uri_el is not None:
                meta["frbr_uri"] = uri_el.get("value", "")
            alias_el = work.find(f"{{{AKN_NS}}}FRBRalias[@name='urn:nir']")
            if alias_el is not None:
                meta["urn_nir"] = alias_el.get("value", "")
            date_el = work.find(f"{{{AKN_NS}}}FRBRdate")
            if date_el is not None:
                meta["enactment_date"] = date_el.get("date", "")
            country_el = work.find(f"{{{AKN_NS}}}FRBRcountry")
            if country_el is not None:
                meta["country"] = country_el.get("value", "it")

        expr = meta_el.find(f".//{{{AKN_NS}}}FRBRExpression")
        if expr is not None:
            expr_date = expr.find(f"{{{AKN_NS}}}FRBRdate")
            if expr_date is not None:
                meta["expression_date"] = expr_date.get("date", "")

        pub_el = meta_el.find(f".//{{{AKN_NS}}}publication")
        if pub_el is not None:
            meta["publication_date"] = pub_el.get("date", "")
            meta["gu_number"] = pub_el.get("number", "")
            meta["gu_name"] = pub_el.get("name", "")

        for nrdfa in meta_el.iter():
            tag = etree.QName(nrdfa.tag).localname if isinstance(nrdfa.tag, str) else ""
            if tag == "span":
                prop = nrdfa.get("property", "")
                if prop == "eli:title":
                    meta["title"] = _clean(nrdfa.get("content", ""))
                elif prop == "eli:id_local":
                    meta["codice_redaz"] = nrdfa.get("content", "")
                elif prop == "eli:type_document":
                    resource = nrdfa.get("resource", "")
                    if "#" in resource:
                        meta["act_type"] = resource.split("#", 1)[1]
                elif prop == "eli:date_document":
                    meta["date_document"] = nrdfa.get("content", "")

    lifecycle_dates: list[str] = []
    for event in root.iter(f"{{{AKN_NS}}}eventRef"):
        d = event.get("date", "")
        if d:
            lifecycle_dates.append(d)
    meta["lifecycle_dates"] = sorted(set(lifecycle_dates))

    body = root.find(f".//{{{AKN_NS}}}body")
    if body is None:
        body = root.find(f".//{{{AKN_NS}}}mainBody")

    blocks: list[Block] = []
    if body is not None:
        _parse_body_recursive(body, blocks, meta)

    if not blocks and body is not None:
        full_text = _extract_text(body)
        if full_text:
            norm_id = meta.get("codice_redaz", "unknown")
            pub_date = _parse_iso_date(meta.get("publication_date")) or date(1970, 1, 2)
            blocks.append(
                Block(
                    id="body",
                    block_type="body",
                    title="",
                    versions=(
                        Version(
                            norm_id=norm_id,
                            publication_date=pub_date,
                            effective_date=pub_date,
                            paragraphs=(Paragraph(css_class="body", text=full_text),),
                        ),
                    ),
                )
            )

    return blocks, meta


def _parse_body_recursive(
    element: etree._Element,
    blocks: list[Block],
    meta: dict[str, Any],
    depth: int = 0,
) -> None:
    """Walk the AKN body tree and emit Block objects for headings and articles."""
    for child in element:
        tag = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""

        if tag in _HEADING_TAGS:
            heading_el = child.find(f"{{{AKN_NS}}}num")
            heading_text = _extract_text(heading_el) if heading_el is not None else ""
            rubrica_el = child.find(f"{{{AKN_NS}}}heading")
            if rubrica_el is not None:
                rubrica = _extract_text(rubrica_el)
                if heading_text and rubrica:
                    heading_text = f"{heading_text} - {rubrica}"
                elif rubrica:
                    heading_text = rubrica

            if heading_text:
                norm_id = meta.get("codice_redaz", "unknown")
                pub_date = _parse_iso_date(meta.get("publication_date")) or date(1970, 1, 2)
                eid = child.get("eId", child.get("id", tag))
                blocks.append(
                    Block(
                        id=eid,
                        block_type=tag,
                        title=heading_text,
                        versions=(
                            Version(
                                norm_id=norm_id,
                                publication_date=pub_date,
                                effective_date=pub_date,
                                paragraphs=(Paragraph(css_class=f"heading_{tag}", text=heading_text),),
                            ),
                        ),
                    )
                )

            _parse_body_recursive(child, blocks, meta, depth + 1)

        elif tag in _ARTICLE_TAGS:
            _parse_article(child, blocks, meta)

        elif tag in _PREAMBLE_TAGS:
            text = _extract_text(child)
            if text:
                norm_id = meta.get("codice_redaz", "unknown")
                pub_date = _parse_iso_date(meta.get("publication_date")) or date(1970, 1, 2)
                eid = child.get("eId", child.get("id", tag))
                blocks.append(
                    Block(
                        id=eid,
                        block_type=tag,
                        title="",
                        versions=(
                            Version(
                                norm_id=norm_id,
                                publication_date=pub_date,
                                effective_date=pub_date,
                                paragraphs=(Paragraph(css_class=tag, text=text),),
                            ),
                        ),
                    )
                )

        else:
            _parse_body_recursive(child, blocks, meta, depth + 1)


def _parse_article(art_el: etree._Element, blocks: list[Block], meta: dict[str, Any]) -> None:
    """Parse a single <articolo> into a Block with paragraphs."""
    num_el = art_el.find(f"{{{AKN_NS}}}num")
    heading_el = art_el.find(f"{{{AKN_NS}}}heading")

    num_text = _extract_text(num_el) if num_el is not None else ""
    heading_text = _extract_text(heading_el) if heading_el is not None else ""
    if num_text and heading_text:
        title = f"{num_text} - {heading_text}"
    elif num_text:
        title = num_text
    elif heading_text:
        title = heading_text
    else:
        title = ""

    paragraphs: list[Paragraph] = []

    for child in art_el:
        child_tag = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""

        if child_tag in _COMMA_TAGS:
            comma_num = child.find(f"{{{AKN_NS}}}num")
            comma_num_text = _extract_text(comma_num) if comma_num is not None else ""
            content_el = child.find(f"{{{AKN_NS}}}content")
            if content_el is None:
                content_el = child.find(f"{{{AKN_NS}}}list")
            if content_el is not None:
                text = _extract_text(content_el)
            else:
                parts = []
                for sub in child:
                    sub_tag = etree.QName(sub.tag).localname if isinstance(sub.tag, str) else ""
                    if sub_tag == "num":
                        continue
                    parts.append(_extract_text(sub))
                text = " ".join(p for p in parts if p)

            if comma_num_text and text:
                full = f"{comma_num_text} {text}"
            elif text:
                full = text
            else:
                full = comma_num_text
            if full:
                paragraphs.append(Paragraph(css_class="comma", text=full))

        elif child_tag in ("num", "heading"):
            continue

        elif child_tag == "content":
            text = _extract_text(child)
            if text:
                paragraphs.append(Paragraph(css_class="content", text=text))

        elif child_tag == "alinea":
            text = _extract_text(child)
            if text:
                paragraphs.append(Paragraph(css_class="alinea", text=text))

        elif child_tag == "table":
            table_md = _render_table(child)
            if table_md:
                paragraphs.append(Paragraph(css_class="table", text=table_md))

        elif child_tag == "lista":
            text = _extract_text(child)
            if text:
                paragraphs.append(Paragraph(css_class="lista", text=text))

    norm_id = meta.get("codice_redaz", "unknown")
    pub_date = _parse_iso_date(meta.get("publication_date")) or date(1970, 1, 2)
    eid = art_el.get("eId", art_el.get("id", "art"))

    blocks.append(
        Block(
            id=eid,
            block_type="articolo",
            title=title,
            versions=(
                Version(
                    norm_id=norm_id,
                    publication_date=pub_date,
                    effective_date=pub_date,
                    paragraphs=tuple(paragraphs) if paragraphs else (Paragraph(css_class="empty", text=""),),
                ),
            ),
        )
    )


class NormativaTextParser(TextParser):
    """Parse Normattiva AKN XML (or multi-vigenza envelope) into Blocks."""

    def parse_text(self, data: bytes) -> list[Any]:
        text = data.decode("utf-8", errors="replace")
        text = _CONTROL_CHAR_RE.sub("", text)
        root = etree.fromstring(text.encode("utf-8"))

        root_tag = etree.QName(root.tag).localname if isinstance(root.tag, str) else ""

        if root_tag == "normattiva-multi-vigenza":
            return self._parse_multi_vigenza(root)

        return self._parse_single(root)

    def _parse_single(self, root: etree._Element) -> list[Block]:
        act = root.find(f"{{{AKN_NS}}}act")
        if act is None:
            act = root.find(f"{{{AKN_NS}}}bill")
        if act is None:
            act = root
        blocks, _ = _parse_single_akn(act)
        return blocks

    def _parse_multi_vigenza(self, root: etree._Element) -> list[Block]:
        """Parse multi-vigenza envelope into blocks with multiple Versions.

        Each <vigenza effective-date="..."> child contains a full AKN document.
        We parse each one and merge blocks by their eId, creating one Version
        per vigenza date.
        """
        vigenze = list(root)
        if not vigenze:
            return []

        all_versions: dict[str, list[tuple[str, list[Block]]]] = {}

        for vig_el in vigenze:
            eff_date = vig_el.get("effective-date", "")
            act = vig_el.find(f"{{{AKN_NS}}}act")
            if act is None:
                for child in vig_el:
                    tag = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
                    if tag in ("act", "bill"):
                        act = child
                        break
            if act is None:
                continue

            blocks, _ = _parse_single_akn(act)
            for block in blocks:
                if block.id not in all_versions:
                    all_versions[block.id] = []
                all_versions[block.id].append((eff_date, [block]))

        merged_blocks: list[Block] = []
        for block_id, version_list in all_versions.items():
            versions: list[Version] = []
            for eff_date_str, blocks in version_list:
                eff_date = _parse_iso_date(eff_date_str) or date(1970, 1, 2)
                for block in blocks:
                    for v in block.versions:
                        versions.append(
                            Version(
                                norm_id=v.norm_id,
                                publication_date=v.publication_date,
                                effective_date=eff_date,
                                paragraphs=v.paragraphs,
                            )
                        )

            if versions:
                first_block = version_list[0][1][0]
                merged_blocks.append(
                    Block(
                        id=first_block.id,
                        block_type=first_block.block_type,
                        title=first_block.title,
                        versions=tuple(versions),
                    )
                )

        return merged_blocks


def _extract_rank_from_urn(urn: str) -> str:
    """Extract the rank slug from a NIR URN.

    urn:nir:stato:decreto.legislativo:2005-03-07;82 → decreto_legislativo
    urn:nir:stato:costituzione → costituzione
    """
    match = re.match(r"urn:nir:[^:]+:([^:]+)(?::|$)", urn)
    if match:
        raw = match.group(1)
        return _RANK_MAP.get(raw, raw.replace(".", "_"))
    return "altro"


class NormativaMetadataParser(MetadataParser):
    """Parse Normattiva AKN XML into NormMetadata."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        text = data.decode("utf-8", errors="replace")
        text = _CONTROL_CHAR_RE.sub("", text)
        root = etree.fromstring(text.encode("utf-8"))

        root_tag = etree.QName(root.tag).localname if isinstance(root.tag, str) else ""
        if root_tag == "normattiva-multi-vigenza":
            vigenze = list(root)
            if vigenze:
                last_vig = vigenze[-1]
                act = last_vig.find(f"{{{AKN_NS}}}act")
                if act is None:
                    for child in last_vig:
                        tag = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
                        if tag in ("act", "bill"):
                            act = child
                            break
                if act is not None:
                    root = act

        act = root.find(f"{{{AKN_NS}}}act")
        if act is None:
            act = root.find(f"{{{AKN_NS}}}bill")
        if act is None:
            act = root

        _, meta = _parse_single_akn(act)

        title = meta.get("title", "")
        if not title:
            preambolo = act.find(f".//{{{AKN_NS}}}preambolo")
            if preambolo is not None:
                title = _clean(preambolo.text or "")[:200]

        urn = meta.get("urn_nir", "")
        rank = Rank(_extract_rank_from_urn(urn)) if urn else Rank("altro")

        pub_date = _parse_iso_date(meta.get("publication_date"))
        if not pub_date:
            pub_date = _parse_iso_date(meta.get("enactment_date"))
        if not pub_date:
            pub_date = _parse_iso_date(meta.get("date_document"))
        if not pub_date:
            pub_date = date(1970, 1, 2)

        codice = meta.get("codice_redaz", norm_id)

        expression_date = _parse_iso_date(meta.get("expression_date"))
        last_modified = expression_date if expression_date and expression_date != pub_date else None

        source_url = f"https://www.normattiva.it/uri-res/N2Ls?{urn}" if urn else ""

        act_type_code = meta.get("act_type", "")

        extra_pairs = [
            ("act_type_code", act_type_code),
            ("urn_nir", urn),
            ("gu_date", meta.get("publication_date", "")),
            ("gu_number", meta.get("gu_number", "")),
            ("codice_redazionale", codice),
            ("enactment_date", meta.get("enactment_date", "")),
        ]

        return NormMetadata(
            title=title,
            short_title="",
            identifier=codice,
            country="it",
            rank=rank,
            publication_date=pub_date,
            status=NormStatus.IN_FORCE,
            department="",
            source=source_url,
            last_modified=last_modified,
            extra=tuple((k, v) for k, v in extra_pairs if v),
        )
