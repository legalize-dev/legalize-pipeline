"""Parser for Italian legislation from Normattiva API.

Parses the combined JSON produced by NormattivaClient.get_text() into
Block objects and NormMetadata. The HTML uses Akoma Ntoso CSS classes.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from html import unescape
from typing import Any

from lxml import html as lxml_html

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import Block, NormMetadata, NormStatus, Paragraph, Rank, Version

logger = logging.getLogger(__name__)

# ── Text cleaning ──

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_WS_RE = re.compile(r"\s+")
_HTML_PARSER = lxml_html.HTMLParser(encoding="utf-8")


def _clean(text: str) -> str:
    """Normalize whitespace, strip control chars, decode HTML entities."""
    text = unescape(text)
    text = text.replace("\xa0", " ")
    text = _CTRL_RE.sub("", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def _parse_html(html_str: str) -> lxml_html.HtmlElement:
    """Parse an HTML fragment into an lxml tree."""
    if not html_str:
        return lxml_html.fromstring("<div></div>", parser=_HTML_PARSER)
    return lxml_html.fromstring(html_str.encode("utf-8"), parser=_HTML_PARSER)


# ── Inline formatting ──


def _inline_text(el: lxml_html.HtmlElement) -> str:
    """Extract text from an element, preserving inline bold/italic as Markdown."""
    parts: list[str] = []

    if el.text:
        parts.append(el.text)

    for child in el:
        tag = child.tag if isinstance(child.tag, str) else ""
        inner = _inline_text(child)

        if tag in ("b", "strong"):
            parts.append(f"**{inner.strip()}**" if inner.strip() else "")
        elif tag in ("i", "em"):
            parts.append(f"*{inner.strip()}*" if inner.strip() else "")
        elif tag == "a":
            href = child.get("href", "")
            if href and inner.strip():
                parts.append(f"[{inner.strip()}]({href})")
            else:
                parts.append(inner)
        elif tag == "br":
            parts.append("\n")
        elif tag == "table":
            parts.append(_table_to_markdown(child))
        elif tag == "div":
            # Nested divs — check class for special handling
            cls = child.get("class", "")
            if "pointedList" in cls:
                parts.append(f"\n- {inner.strip()}")
            else:
                parts.append(inner)
        else:
            parts.append(inner)

        if child.tail:
            parts.append(child.tail)

    return "".join(parts)


# ── Table conversion ──


def _table_to_markdown(table_el: lxml_html.HtmlElement) -> str:
    """Convert an HTML table to a Markdown pipe table."""
    rows: list[list[str]] = []

    for tr in table_el.iter("tr"):
        cells: list[str] = []
        for td in tr:
            if td.tag not in ("td", "th"):
                continue
            text = _clean(_inline_text(td))
            cells.append(text.replace("|", "\\|"))
        if cells:
            rows.append(cells)

    if not rows:
        return ""

    # Normalize column count
    max_cols = max(len(r) for r in rows)
    for row in rows:
        while len(row) < max_cols:
            row.append("")

    lines: list[str] = []
    # Header row
    lines.append("| " + " | ".join(rows[0]) + " |")
    lines.append("| " + " | ".join("---" for _ in rows[0]) + " |")
    # Data rows
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n" + "\n".join(lines) + "\n"


# ── Article HTML parsing ──


def _parse_article_html(html_str: str) -> list[Paragraph]:
    """Parse a single article's HTML into Paragraph objects."""
    if not html_str:
        return []

    tree = _parse_html(html_str)
    paragraphs: list[Paragraph] = []

    # Find the bodyTesto div
    body_divs = tree.xpath('//div[@class="bodyTesto"]')
    if not body_divs:
        # Try the root element itself
        body = tree
    else:
        body = body_divs[0]

    for el in body:
        tag = el.tag if isinstance(el.tag, str) else ""
        cls = el.get("class", "")

        # Preamble elements
        if "preamble-before-title-akn" in cls:
            text = _clean(_inline_text(el))
            if text:
                paragraphs.append(Paragraph(css_class="parrafo", text=text))

        elif "preamble-title-akn" in cls:
            text = _clean(_inline_text(el))
            if text:
                paragraphs.append(Paragraph(css_class="firma_rey", text=text))

        elif "preamble-end-akn" in cls:
            text = _clean(_inline_text(el))
            if text:
                paragraphs.append(Paragraph(css_class="firma_rey", text=text))

        elif "formula-introduttiva" in cls:
            text = _clean(_inline_text(el))
            if text:
                paragraphs.append(Paragraph(css_class="parrafo", text=text))

        # Article number
        elif "article-num-akn" in cls:
            text = _clean(_inline_text(el))
            if text:
                paragraphs.append(Paragraph(css_class="articulo", text=text))

        # Article heading
        elif "article-heading-akn" in cls:
            text = _clean(_inline_text(el))
            if text:
                paragraphs.append(Paragraph(css_class="seccion", text=text))

        # Article pre-comma text
        elif "article-pre-comma-text-akn" in cls or "art-pre-comma-text-akn" in cls:
            text = _clean(_inline_text(el))
            if text:
                paragraphs.append(Paragraph(css_class="parrafo", text=text))

        # Commas container
        elif "art-commi-div-akn" in cls:
            _parse_commi(el, paragraphs)

        # Amendment notes (skip)
        elif "art_aggiornamento" in cls:
            continue

        # Simple text spans (e.g., art-just-text-akn for the Constitution)
        elif "art-just-text-akn" in cls:
            text = _clean(_inline_text(el))
            if text:
                for line in text.split("\n"):
                    line = line.strip()
                    if line:
                        paragraphs.append(Paragraph(css_class="parrafo", text=line))

        # table-akn — preformatted ASCII pipe tables with <br> line breaks.
        # Normattiva represents tables as ASCII art inside <p class="table-akn">,
        # NOT as HTML <table> elements. Preserve them verbatim.
        elif "table-akn" in cls:
            table_text = _extract_ascii_table(el)
            if table_text:
                paragraphs.append(Paragraph(css_class="pre", text=table_text))

        # Generic div/p/span with text
        elif tag in ("div", "p", "span"):
            text = _clean(_inline_text(el))
            if text and not _is_noise(cls):
                paragraphs.append(Paragraph(css_class="parrafo", text=text))

    return paragraphs


def _parse_commi(commi_div: lxml_html.HtmlElement, paragraphs: list[Paragraph]) -> None:
    """Parse the art-commi-div-akn container into paragraphs."""
    for child in commi_div:
        cls = child.get("class", "")

        if "art-comma-div-akn" in cls:
            _parse_single_comma(child, paragraphs)

        elif "pointedList-first-akn" in cls:
            # Top-level list item with comma number
            _parse_pointed_list_item(child, paragraphs, is_first=True)

        elif "pointedList-rest-akn" in cls:
            # Continuation list item (a, b, c, ...)
            _parse_pointed_list_item(child, paragraphs, is_first=False)

        elif "art-comma-div-akn" not in cls and child.get("class"):
            # Other elements (e.g., nested divs wrapping pointed lists)
            inner_cls = cls
            if "pointedList" in inner_cls:
                _parse_pointed_list_item(child, paragraphs, is_first="first" in inner_cls)
            else:
                # Recursively check for nested commi/lists
                for sub in child:
                    sub_cls = sub.get("class", "")
                    if "art-comma-div-akn" in sub_cls:
                        _parse_single_comma(sub, paragraphs)
                    elif "pointedList" in sub_cls:
                        _parse_pointed_list_item(sub, paragraphs, is_first="first" in sub_cls)


def _parse_single_comma(comma_div: lxml_html.HtmlElement, paragraphs: list[Paragraph]) -> None:
    """Parse a single art-comma-div-akn element."""
    num_text = ""
    body_text = ""

    for child in comma_div:
        child_cls = child.get("class", "")
        if "comma-num-akn" in child_cls:
            num_text = _clean(_inline_text(child))
        elif "art_text_in_comma" in child_cls:
            body_text = _inline_text(child)
        elif "pointedList-first-akn" in child_cls:
            _parse_pointed_list_item(child, paragraphs, is_first=True)
        elif "pointedList-rest-akn" in child_cls:
            _parse_pointed_list_item(child, paragraphs, is_first=False)
        elif child.get("class") and "pointedList" not in child_cls:
            # Nested div — might wrap pointed lists
            for sub in child:
                sub_cls = sub.get("class", "")
                if "pointedList-first-akn" in sub_cls:
                    _parse_pointed_list_item(sub, paragraphs, is_first=True)
                elif "pointedList-rest-akn" in sub_cls:
                    _parse_pointed_list_item(sub, paragraphs, is_first=False)

    # Combine comma number + text
    full_text = ""
    if num_text and body_text:
        full_text = f"{num_text}{_clean(body_text)}"
    elif body_text:
        full_text = _clean(body_text)
    elif num_text:
        full_text = num_text

    if full_text:
        paragraphs.append(Paragraph(css_class="parrafo", text=full_text))


def _parse_pointed_list_item(
    el: lxml_html.HtmlElement, paragraphs: list[Paragraph], *, is_first: bool
) -> None:
    """Parse a pointedList-first-akn or pointedList-rest-akn element."""
    # Check if this is a comma-level item (has comma-num-akn)
    num_text = ""
    body_parts: list[str] = []

    for child in el:
        child_cls = child.get("class", "")
        if "comma-num-akn" in child_cls:
            num_text = _clean(_inline_text(child))
        else:
            t = _inline_text(child)
            if t.strip():
                body_parts.append(t)

    # Also get direct text
    if el.text:
        direct = _clean(el.text)
        if direct:
            body_parts.insert(0, direct)

    body = _clean(" ".join(body_parts))

    if num_text and body:
        text = f"{num_text}{body}"
    elif body:
        text = body
    elif num_text:
        text = num_text
    else:
        return

    if is_first and num_text:
        # This is a numbered comma that starts a list — emit as paragraph
        paragraphs.append(Paragraph(css_class="parrafo", text=text))
    else:
        # This is a lettered sub-item (a, b, c, ...) — emit as list item
        paragraphs.append(Paragraph(css_class="list_item", text=f"- {text}"))


def _extract_ascii_table(el: lxml_html.HtmlElement) -> str:
    """Extract preformatted ASCII table from a table-akn element.

    Normattiva represents tables as ASCII art with pipe characters (|),
    plus signs (+), and equals signs (=) inside <p class="table-akn">
    with <br> line breaks. We preserve them as-is in a code block.
    """
    # Get the raw text content, splitting on <br> to preserve line breaks
    lines: list[str] = []
    # Walk through text nodes and <br> elements
    if el.text:
        lines.append(el.text.rstrip())
    for child in el.iter():
        if child.tag == "br":
            if child.tail:
                text = child.tail.rstrip()
                if text:
                    lines.append(text)
            else:
                lines.append("")
        elif child != el and child.text:
            lines.append(child.text.rstrip())
            if child.tail:
                lines.append(child.tail.rstrip())

    # Clean up: remove empty leading/trailing lines, decode entities
    cleaned: list[str] = []
    for line in lines:
        line = unescape(line).replace("\xa0", " ")
        line = _CTRL_RE.sub("", line)
        # Don't collapse whitespace for table lines — preserve alignment
        cleaned.append(line.rstrip())

    # Strip empty lines from start/end
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()

    if not cleaned:
        return ""

    return "\n".join(cleaned)


def _is_noise(css_class: str) -> bool:
    """Check if a CSS class is UI noise that should be skipped."""
    noise = {
        "art_aggiornamento_title-akn",
        "art_aggiornamento_testo-akn",
        "art_aggiornamento-akn",
    }
    return any(n in css_class for n in noise)


# ── Date parsing ──


def _parse_vigenza_date(s: str) -> date | None:
    """Parse YYYYMMDD vigenza date string."""
    s = (s or "").strip()
    if not s or s == "0" or s == "99999999":
        return None
    if len(s) != 8:
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def _parse_emanation_date(atto: dict) -> date:
    """Parse emanation date from atto metadata fields."""
    # Try dataEmanazione (ISO datetime string)
    de = atto.get("dataEmanazione")
    if de and isinstance(de, str) and len(de) >= 10:
        try:
            return date.fromisoformat(de[:10])
        except ValueError:
            pass

    # Fall back to anno/mese/giorno fields
    anno = atto.get("annoProvvedimento", 0)
    mese = atto.get("meseProvvedimento", 0)
    giorno = atto.get("giornoProvvedimento", 0)
    if anno and mese and giorno:
        try:
            return date(int(anno), int(mese), int(giorno))
        except ValueError:
            pass

    # Fall back to GU date
    anno_gu = atto.get("annoGU", 0)
    mese_gu = atto.get("meseGU", 0)
    giorno_gu = atto.get("giornoGU", 0)
    if anno_gu and mese_gu and giorno_gu:
        try:
            return date(int(anno_gu), int(mese_gu), int(giorno_gu))
        except ValueError:
            pass

    # Last resort
    return date(1900, 1, 1)


# ── Text Parser ──


class NormattivaTextParser(TextParser):
    """Parse Normattiva combined JSON into Block objects."""

    def parse_text(self, data: bytes) -> list[Any]:
        """Parse combined JSON (metadata + articles) into Block list."""
        combined = json.loads(data.decode("utf-8"))

        # Handle both combined format and raw API response
        articles = combined.get("articles", [])
        atto = combined.get("atto_metadata", {})
        codice = combined.get("codiceRedazionale", "")

        if not articles:
            # Raw single-article response from dettaglio-atto-urn
            raw_data = combined.get("data", {})
            raw_atto = raw_data.get("atto")
            raw_lista = raw_data.get("lista")

            if raw_atto:
                html = raw_atto.get("articoloHtml", "")
                articles = [
                    {
                        "article_num": "1",
                        "html": html,
                        "vigenza_inizio": raw_atto.get("articoloDataInizioVigenza", ""),
                        "vigenza_fine": raw_atto.get("articoloDataFineVigenza", ""),
                    }
                ]
                atto = raw_atto
                codice = codice or "unknown"
            elif raw_lista:
                # Ambiguous URN returned multiple results —
                # take the one with the largest HTML (most complete version)
                best = max(raw_lista, key=lambda x: len(x.get("articoloHtml", "") or ""))
                html = best.get("articoloHtml", "")
                articles = [
                    {
                        "article_num": "1",
                        "html": html,
                        "vigenza_inizio": best.get("articoloDataInizioVigenza", ""),
                        "vigenza_fine": best.get("articoloDataFineVigenza", ""),
                    }
                ]
                atto = best
                codice = codice or "unknown"

        if not articles:
            return []

        pub_date = _parse_emanation_date(atto)
        blocks: list[Block] = []

        for art in articles:
            art_num = str(art.get("article_num", "1"))
            html = art.get("html", "")
            vigenza_inizio = _parse_vigenza_date(art.get("vigenza_inizio", ""))

            paragraphs = _parse_article_html(html)
            if not paragraphs:
                continue

            # Use vigenza start date if available, else emanation date
            version_date = vigenza_inizio or pub_date
            title = paragraphs[0].text if paragraphs else f"Art. {art_num}"

            block = Block(
                id=f"art{art_num}",
                block_type="article",
                title=title,
                versions=(
                    Version(
                        norm_id=codice,
                        publication_date=version_date,
                        effective_date=version_date,
                        paragraphs=tuple(paragraphs),
                    ),
                ),
            )
            blocks.append(block)

        return blocks

    def extract_reforms(self, data: bytes) -> list[Any]:
        """Extract reform timeline from version dates.

        Each article in the combined response has articoloDataInizioVigenza
        and articoloDataFineVigenza. We collect unique vigenza start dates
        across all articles — each one represents a reform.

        The actual version-walking (fetching @originale, !vig=date) happens
        in the client layer, which populates the articles list with all
        versions. Here we just extract the Reform objects from what's given.
        """
        from legalize.models import Reform

        combined = json.loads(data.decode("utf-8"))
        articles = combined.get("articles", [])
        codice = combined.get("codiceRedazionale", "")

        if not articles:
            raw_data = combined.get("data", {})
            raw_atto = raw_data.get("atto")
            if raw_atto:
                inizio = raw_atto.get("articoloDataInizioVigenza", "")
                articles = [{"vigenza_inizio": inizio, "article_num": "1"}]
            else:
                raw_lista = raw_data.get("lista", [])
                if raw_lista:
                    best = max(raw_lista, key=lambda x: len(x.get("articoloHtml", "") or ""))
                    inizio = best.get("articoloDataInizioVigenza", "")
                    articles = [{"vigenza_inizio": inizio, "article_num": "1"}]

        # Collect unique reform dates (skip the first version = bootstrap)
        reform_dates: dict[date, list[str]] = {}
        first_date: date | None = None

        for art in articles:
            vig = _parse_vigenza_date(art.get("vigenza_inizio", ""))
            if not vig:
                continue
            if first_date is None or vig < first_date:
                first_date = vig

        # Any vigenza start date AFTER the earliest one is a reform
        for art in articles:
            vig = _parse_vigenza_date(art.get("vigenza_inizio", ""))
            if not vig or vig == first_date:
                continue
            art_id = f"art{art.get('article_num', '?')}"
            if vig not in reform_dates:
                reform_dates[vig] = []
            reform_dates[vig].append(art_id)

        reforms = []
        for reform_date in sorted(reform_dates):
            reforms.append(
                Reform(
                    date=reform_date,
                    norm_id=codice,
                    affected_blocks=tuple(reform_dates[reform_date]),
                )
            )

        return reforms


# ── Metadata Parser ──

# Rank mapping
RANK_MAP: dict[str, str] = {
    "COSTITUZIONE": "costituzione",
    "LEGGE COSTITUZIONALE": "legge_costituzionale",
    "LEGGE": "legge",
    "DECRETO LEGISLATIVO": "decreto_legislativo",
    "DECRETO-LEGGE": "decreto_legge",
    "DECRETO DEL PRESIDENTE DELLA REPUBBLICA": "decreto_presidente_repubblica",
    "DECRETO DEL PRESIDENTE DEL CONSIGLIO DEI MINISTRI": "decreto_presidente_consiglio",
    "DECRETO": "decreto",
    "DECRETO MINISTERIALE": "decreto_ministeriale",
    "ORDINANZA": "ordinanza",
    "DELIBERAZIONE": "deliberazione",
    "REGOLAMENTO": "regolamento",
    "REGIO DECRETO": "regio_decreto",
    "REGIO DECRETO-LEGGE": "regio_decreto_legge",
    "DECRETO LUOGOTENENZIALE": "decreto_luogotenenziale",
    "REGIO DECRETO LEGISLATIVO": "regio_decreto_legislativo",
    "DECRETO LEGISLATIVO LUOGOTENENZIALE": "decreto_legislativo_luogotenenziale",
    "DECRETO LEGISLATIVO DEL CAPO PROVVISORIO DELLO STATO": "decreto_legislativo_capo_provvisorio",
    "DECRETO DEL CAPO PROVVISORIO DELLO STATO": "decreto_capo_provvisorio",
    "DECRETO-LEGGE LUOGOTENENZIALE": "decreto_legge_luogotenenziale",
    "DECRETO LEGISLATIVO PRESIDENZIALE": "decreto_legislativo_presidenziale",
    "DECRETO REALE": "decreto_reale",
    "DECRETO DEL DUCE": "decreto_duce",
    "DECRETO DEL CAPO DEL GOVERNO": "decreto_capo_governo",
    "DECRETO DEL DUCE DEL FASCISMO, CAPO DEL GOVERNO": "decreto_duce_fascismo",
    "DECRETO PRESIDENZIALE": "decreto_presidenziale",
}


class NormattivaMetadataParser(MetadataParser):
    """Parse Normattiva combined JSON into NormMetadata."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        combined = json.loads(data.decode("utf-8"))

        # Handle both combined format and raw API response
        atto = combined.get("atto_metadata", {})
        if not atto:
            raw_data = combined.get("data", {})
            atto = raw_data.get("atto")
            if not atto:
                # lista format — take the most complete result
                lista = raw_data.get("lista", [])
                if lista:
                    atto = max(lista, key=lambda x: len(x.get("articoloHtml", "") or ""))
                else:
                    atto = {}

        # Title
        titolo = _clean(atto.get("titolo", "") or "")
        sotto_titolo = _clean(atto.get("sottoTitolo", "") or "")
        title = titolo or sotto_titolo or f"Act {norm_id}"
        short_title = sotto_titolo or titolo or title

        # Rank
        tipo_desc = atto.get("tipoProvvedimentoDescrizione", "")
        rank_str = RANK_MAP.get(tipo_desc, tipo_desc.lower().replace(" ", "_").replace("-", "_"))

        # Publication date
        pub_date = _parse_emanation_date(atto)

        # GU date
        anno_gu = atto.get("annoGU", 0)
        mese_gu = atto.get("meseGU", 0)
        giorno_gu = atto.get("giornoGU", 0)
        gu_date = ""
        if anno_gu and mese_gu and giorno_gu:
            gu_date = f"{int(anno_gu):04d}-{int(mese_gu):02d}-{int(giorno_gu):02d}"

        # Status — infer from classeProvvedimento if available,
        # otherwise default to in_force
        status = NormStatus.IN_FORCE

        # Source URL (ELI)
        tipo_code = atto.get("tipoProvvedimentoCodice", "")
        numero = atto.get("numeroProvvedimento", 0)
        source_url = f"https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:{RANK_MAP.get(tipo_desc, 'legge')}:{pub_date.isoformat()};{numero}"

        # Extra fields
        extra: list[tuple[str, str]] = []

        if tipo_code:
            extra.append(("act_type_code", tipo_code))

        act_number = str(atto.get("numeroProvvedimento", ""))
        if act_number and act_number != "0":
            extra.append(("act_number", act_number))

        if gu_date:
            extra.append(("gu_date", gu_date))

        gu_number = str(atto.get("numeroGU", ""))
        if gu_number and gu_number != "0":
            extra.append(("gu_number", gu_number))

        supp_type = atto.get("tipoSupplementoCode", "NO")
        if supp_type == "SO":
            supp_num = str(atto.get("numeroSupplemento", ""))
            extra.append(("supplement_type", "SO"))
            if supp_num and supp_num != "0":
                extra.append(("supplement_number", supp_num))

        return NormMetadata(
            title=title,
            short_title=short_title if short_title != title else title,
            identifier=norm_id,
            country="it",
            rank=Rank(rank_str),
            publication_date=pub_date,
            status=status,
            department="",
            source=source_url,
            extra=tuple(extra),
        )
