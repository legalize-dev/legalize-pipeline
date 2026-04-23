"""Parser for SUIN-Juriscol HTML pages (Colombia).

Validated against fixtures captured from https://www.suin-juriscol.gov.co:
- Metadata: hidden spans under ``span[field]``.
- Title: ``div#titulotipo h1`` / ``h1``.
- Text body: ``div[style*="padding: 15px"]``.
- Articles: body descendants ``div[id^="toggle_"]``.
- Modification summary: ``div[id$="ResumenNotasVigencia"] li.referencia``.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime
from typing import Any

from lxml import html as lxml_html

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import Block, NormMetadata, NormStatus, Paragraph, Rank, Version

logger = logging.getLogger(__name__)

_CHARSET_RE = re.compile(rb"<meta[^>]+charset=[\"']?([A-Za-z0-9._-]+)", re.I)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_ARTICLE_RE = re.compile(
    r"^\s*(?:ART[IÍ]CULO|Art\.?)\s+([0-9]+|[a-záéíóúñ]+|[úu]nico)[°ºo.]?",
    re.I,
)
_TITULO_RE = re.compile(r"^\s*(?:T[IÍ]TULO|LIBRO|PARTE\s+[IVXLC]+)\b", re.I)
_CAPITULO_RE = re.compile(r"^\s*CAP[IÍ]TULO\b", re.I)
_SECCION_RE = re.compile(r"^\s*(?:SECCI[OÓ]N|PARTE)\b", re.I)
_LIST_ITEM_RE = re.compile(
    r"^\s*(?:\d+[°ºo.]|\d+\.\d+\.|\([a-z]\)|[a-z]\)|[ivxlcdm]+[.)])\s+",
    re.I,
)
_NOTE_HEADING_RE = re.compile(
    r"^\s*(?:TEXTO CORRESPONDIENTE A|LEGISLACI[OÓ]N ANTERIOR|"
    r"Afecta la vigencia de:|JURISPRUDENCIA)",
    re.I,
)
_METADATA_CARD_RE = re.compile(r"^\s*Subtipo\s*:", re.I)
_NOISE_CLASSES = frozenset({"toctoggle", "resumenvigencias"})

# Every span[field] key SUIN exposes that isn't already represented in the
# top-level NormMetadata fields. English snake_case per the project rule
# "Metadata completeness: every field the source exposes must be captured".
_EXTRA_TEXT_FIELDS: tuple[tuple[str, str], ...] = (
    ("documento_fuente", "gazette_reference"),
    ("numero_diario_oficial", "gazette_number"),
    ("pagina_diario_oficial", "gazette_page"),
    ("pagina_diario_oficial_pdf", "gazette_pdf_page"),
    ("documento_fuente2", "gazette_reference_secondary"),
    ("numero_diario_oficial2", "gazette_number_secondary"),
    ("pagina_diario_oficial2", "gazette_page_secondary"),
    ("subtipo", "subtype"),
    ("sector", "sector"),
    ("comentarios", "comments"),
    ("descriptores", "descriptors"),
    ("tema", "theme"),
    ("titulo_uniforme", "uniform_title"),
    ("Estatutos", "statute_text"),
    ("asunto", "subject_matter"),
    ("de", "sender"),
    ("para", "addressee"),
    ("fe_de_erratas", "errata"),
    ("lugar_fecha", "place_date"),
    ("nombre_codigo", "code_name"),
    ("notas_vigencias", "validity_notes"),
    ("observaciones", "observations"),
    ("observaciones_internas", "internal_observations"),
    ("separacion_numero", "number_separator"),
    ("juris_estado_excepcion", "emergency_state_case_law"),
)
_EXTRA_DATE_FIELDS: tuple[tuple[str, str], ...] = (
    ("fecha_vigencia", "entry_into_force"),
    ("fecha_fin_vigencia", "expiry_date"),
    ("fecha_expedicion", "issued_date"),
    ("fecha_diario_oficial2", "gazette_date_secondary"),
)
_EXTRA_BOOL_FIELDS: tuple[tuple[str, str], ...] = (
    ("division_documento", "has_divisions"),
    ("en_estudio_depuracion", "under_purge_review"),
    ("es_codigo", "is_code"),
    ("es_estatuto", "is_statute"),
    ("es_reglamento", "is_regulation"),
    ("estado_excepcion", "is_emergency_state"),
    ("marco_regulatorio", "is_regulatory_framework"),
)
_DATE_IN_SCRIPT_RE = re.compile(r"new Date\((\d{2}/\d{2}/\d{4})\)")
_LEG_ANT_RANGE_RE = re.compile(
    r"Vigente\s+desde:\s*(\d{1,2}/\d{1,2}/\d{4})\s+y\s+hasta\s+el:\s*(\d{1,2}/\d{1,2}/\d{4})",
    re.I,
)
_BASE_URL = "https://www.suin-juriscol.gov.co"

_ES_MONTHS: dict[str, int] = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


def _detect_encoding(data: bytes) -> str:
    """Detect declared HTML charset, defaulting to UTF-8."""
    head = data[:4096]
    match = _CHARSET_RE.search(head)
    if match:
        return match.group(1).decode("ascii", errors="ignore") or "utf-8"
    return "utf-8"


def _parse_html(data: bytes):
    """Parse HTML bytes into an lxml tree with explicit charset decoding."""
    encoding = _detect_encoding(data)
    text = data.decode(encoding, errors="replace")
    if "<html" not in text[:500].lower():
        # SUIN fixtures declare charset=utf-16 in the Content-Type meta while
        # the captured bytes are UTF-8. Fall back when the declared charset
        # produces mojibake instead of markup.
        text = data.decode("utf-8", errors="replace")
    text = re.sub(r"^\s*<\?xml[^>]*>\s*", "", text, flags=re.I)
    return lxml_html.fromstring(text)


def _clean_text(text: str) -> str:
    """Normalize whitespace, strip non-breaking spaces and invalid control chars."""
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = _CONTROL_CHAR_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _element_text(el) -> str:
    """Get cleaned text content from an lxml element."""
    if el is None:
        return ""
    return _clean_text("".join(el.itertext()))


def _normalize_href(href: str) -> str:
    """Normalize SUIN relative cross-reference links to absolute URLs."""
    if not href:
        return ""
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return _BASE_URL + href
    return href


def _inline_text(el) -> str:
    """Extract body text while preserving basic inline Markdown.

    Maps ``<b>/<strong>`` to ``**...**``, ``<i>/<em>`` to ``*...*``,
    and SUIN cross-reference anchors to Markdown links.
    """
    if el is None:
        return ""

    def walk(node) -> str:
        parts: list[str] = []
        if node.text:
            parts.append(node.text)

        for child in node:
            tag = (child.tag or "").lower()
            inner = walk(child)
            if tag in ("b", "strong"):
                stripped = inner.strip()
                if stripped:
                    lead = " " if inner[:1].isspace() else ""
                    trail = " " if inner[-1:].isspace() else ""
                    if not trail and (child.tail or "")[:1].isalpha():
                        trail = " "
                    parts.append(f"{lead}**{stripped}**{trail}")
            elif tag in ("i", "em"):
                stripped = inner.strip()
                if stripped:
                    lead = " " if inner[:1].isspace() else ""
                    trail = " " if inner[-1:].isspace() else ""
                    if not trail and (child.tail or "")[:1].isalpha():
                        trail = " "
                    parts.append(f"{lead}*{stripped}*{trail}")
            elif tag == "a":
                text = inner.strip()
                href = _normalize_href(child.get("href") or "")
                if text and href and not href.startswith("#"):
                    parts.append(f"[{text}]({href})")
                else:
                    parts.append(inner)
            elif tag == "br":
                parts.append(" ")
            elif tag in ("p", "div") and inner:
                sep = "" if not parts or not parts[-1] or parts[-1][-1:].isspace() else " "
                parts.append(f"{sep}{inner}")
            else:
                parts.append(inner)

            if child.tail:
                parts.append(child.tail)

        return "".join(parts)

    text = walk(el)

    def _join(left: str, right: str) -> str:
        # When the HTML concatenates two adjacent emphasis runs without any
        # whitespace, reinsert a single space at the join when the boundary
        # would glue two words together (lowercase letter → uppercase letter).
        if left and right and left[-1].islower() and right[0].isupper():
            return " "
        return ""

    prev = ""
    while prev != text:
        prev = text
        text = re.sub(
            r"\*\*([^*\n]*)\*\*\*\*([^*\n]*)\*\*",
            lambda m: f"**{m.group(1)}{_join(m.group(1), m.group(2))}{m.group(2)}**",
            text,
        )
        text = re.sub(
            r"\*\*\*([^*\n]*)\*\*\*\*\*([^*\n]*)\*\*",
            lambda m: f"***{m.group(1)}{_join(m.group(1), m.group(2))}{m.group(2)}***",
            text,
        )
        text = re.sub(
            r"\*\*([^*\n]*)\*\*\*\*\*([^*\n]*)\*\*\*",
            lambda m: f"***{m.group(1)}{_join(m.group(1), m.group(2))}{m.group(2)}***",
            text,
        )
    return _clean_text(text)


def _get_classes(el) -> set[str]:
    """Get the set of CSS classes on an element."""
    cls = el.get("class") or ""
    return set(cls.split())


def _has_class(el, css_class: str) -> bool:
    """Check if element has a given CSS class."""
    return css_class in _get_classes(el)


def _strip_descendants_with_classes(el, classes: frozenset[str]) -> None:
    """Remove descendant elements that have any of the given classes."""
    targets = []
    for descendant in el.xpath(".//*[@class]"):
        descendant_classes = set((descendant.get("class") or "").split())
        if descendant_classes & classes:
            targets.append(descendant)

    for descendant in targets:
        parent = descendant.getparent()
        if parent is None:
            continue
        tail = descendant.tail or ""
        if tail:
            prev = descendant.getprevious()
            if prev is not None:
                prev.tail = (prev.tail or "") + tail
            else:
                parent.text = (parent.text or "") + tail
        parent.remove(descendant)


def _table_cell_text(td) -> str:
    """Extract clean text from a table cell, escaping pipes for Markdown."""
    text = _inline_text(td)
    return text.replace("|", "\\|").strip()


def _table_to_markdown(table_el) -> str:
    """Convert an HTML table to a Markdown pipe table."""
    raw_rows: list[list[tuple[str, int, int]]] = []
    for tr in table_el.iter():
        if (tr.tag or "").lower() != "tr":
            continue
        cells: list[tuple[str, int, int]] = []
        for cell in tr:
            if (cell.tag or "").lower() not in ("td", "th"):
                continue
            text = _table_cell_text(cell)
            colspan = int(cell.get("COLSPAN") or cell.get("colspan") or 1)
            rowspan = int(cell.get("ROWSPAN") or cell.get("rowspan") or 1)
            cells.append((text, colspan, rowspan))
        if cells:
            raw_rows.append(cells)

    if not raw_rows:
        return ""

    expanded: list[list[str]] = []
    pending: dict[int, tuple[str, int]] = {}
    for row in raw_rows:
        out_row: list[str] = []
        col = 0
        cell_idx = 0
        while cell_idx < len(row) or col in pending:
            if col in pending:
                text, remaining = pending[col]
                out_row.append(text)
                if remaining > 1:
                    pending[col] = (text, remaining - 1)
                else:
                    del pending[col]
                col += 1
                continue
            text, colspan, rowspan = row[cell_idx]
            for _ in range(colspan):
                out_row.append(text)
                if rowspan > 1:
                    pending[col] = (text, rowspan - 1)
                col += 1
            cell_idx += 1
        expanded.append(out_row)

    max_cols = max(len(row) for row in expanded)
    for row in expanded:
        while len(row) < max_cols:
            row.append("")

    lines = ["| " + " | ".join(expanded[0]) + " |"]
    lines.append("| " + " | ".join("---" for _ in range(max_cols)) + " |")
    for row in expanded[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _make_block(
    block_id: str,
    block_type: str,
    title: str,
    paragraphs: list[Paragraph],
    pub_date: date,
    law_norm_id: str,
    prior_paragraphs: list[Paragraph] | None = None,
    prior_from: date | None = None,
    prior_until: date | None = None,
) -> Block:
    """Build a Block from one or two Versions.

    When ``prior_paragraphs`` is provided, the Block gets two Versions:
    the prior text valid from ``prior_from`` until ``prior_until``, then
    the current ``paragraphs`` valid from ``prior_until`` onward. Otherwise
    the Block gets a single Version at ``pub_date``.
    """
    if prior_paragraphs and prior_from and prior_until:
        v_old = Version(
            norm_id=law_norm_id,
            publication_date=prior_from,
            effective_date=prior_from,
            paragraphs=tuple(prior_paragraphs),
        )
        v_new = Version(
            norm_id=law_norm_id,
            publication_date=prior_until,
            effective_date=prior_until,
            paragraphs=tuple(paragraphs),
        )
        return Block(id=block_id, block_type=block_type, title=title, versions=(v_old, v_new))
    version = Version(
        norm_id=law_norm_id,
        publication_date=pub_date,
        effective_date=pub_date,
        paragraphs=tuple(paragraphs),
    )
    return Block(id=block_id, block_type=block_type, title=title, versions=(version,))


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _normalize_rango(value: str) -> str:
    value = _strip_accents(value).upper()
    value = re.sub(r"[^A-Z0-9]+", "-", value)
    return value.strip("-")


def _rank_from_rango(value: str) -> str:
    rango = _normalize_rango(value)
    return rango.lower().replace("-", "_") or Rank.OTRO


def _parse_date(value: str) -> date | None:
    """Parse SUIN date formats."""
    value = _clean_text(value)
    if not value:
        return None

    script_match = _DATE_IN_SCRIPT_RE.search(value)
    if script_match:
        value = script_match.group(1)

    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass

    match = re.search(r"(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})", value, re.I)
    if match:
        day = int(match.group(1))
        month_name = _strip_accents(match.group(2).lower())
        month = _ES_MONTHS.get(month_name)
        if month:
            return date(int(match.group(3)), month, day)

    return None


def _normalize_extra_date(val: str) -> str:
    """Convert DD/MM/YYYY to YYYY-MM-DD. Return val unchanged if not that format."""
    match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", val.strip())
    if match:
        return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
    return val


def _extract_fields(tree) -> dict[str, str]:
    """Extract hidden SUIN metadata fields from span[field] elements."""
    fields: dict[str, str] = {}
    for span in tree.xpath("//span[@field]"):
        key = span.get("field")
        if key:
            fields[key] = _element_text(span)
    return fields


def _normalize_identifier(fields: dict[str, str], title: str, norm_id: str) -> str:
    rango = fields.get("tipo", "")
    number = fields.get("numero", "")
    year = fields.get("anio", "")

    if not (rango and number and year):
        match = re.search(
            r"\b([A-ZÁÉÍÓÚÑ ]+?)\s+([0-9]+)\s+DE\s+([0-9]{4})\b",
            _strip_accents(title).upper(),
        )
        if match:
            rango, number, year = match.group(1), match.group(2), match.group(3)

    if not (rango and number and year):
        return norm_id

    return f"{_normalize_rango(rango)}-{number.strip()}-{year.strip()}"


def _status_from_text(value: str) -> tuple[NormStatus, tuple[tuple[str, str], ...]]:
    status_text = _strip_accents(value).lower()
    if "parcial" in status_text and "derog" in status_text:
        return NormStatus.PARTIALLY_REPEALED, ()
    if "derog" in status_text or "no vigente" in status_text:
        return NormStatus.REPEALED, ()
    return NormStatus.IN_FORCE, ()


def _pick_publication_date(fields: dict[str, str]) -> date:
    """Pick the first plausible publication date from SUIN fields.

    SUIN's `fecha_diario_oficial` is usually correct, but the field is
    hand-typed by editors and occasionally contains future years (e.g.
    `29/12/2029` for a 2010 decree). When the primary candidate sits in
    the implausibly far future, fall back to other date fields.
    """
    future_ceiling = date.today().replace(year=date.today().year + 1)
    for key in ("fecha_diario_oficial", "fecha_vigencia", "fecha_expedicion", "fecha"):
        candidate = _parse_date(fields.get(key, ""))
        if candidate and candidate <= future_ceiling:
            return candidate
    return date(1900, 1, 1)


def _extract_norm_id_and_pub_date(tree) -> tuple[str, date]:
    fields = _extract_fields(tree)
    norm_id = "0"
    source_links = tree.xpath('//link[@rel="canonical"]/@href|//meta[@property="og:url"]/@content')
    for source_link in source_links:
        match = re.search(r"id=(\d+)", source_link)
        if match:
            norm_id = match.group(1)
            break

    return norm_id, _pick_publication_date(fields)


def _is_hidden_or_note(el) -> bool:
    for ancestor in [el, *el.iterancestors()]:
        style = (ancestor.get("style") or "").lower().replace(" ", "")
        if "display:none" in style or "visibility:hidden" in style:
            return True
        if _has_class(ancestor, "resumenvigencias") or _has_class(ancestor, "toctoggle"):
            return True
        element_id = ancestor.get("id") or ""
        if "Notas" in element_id or "leg_ant" in element_id:
            return True
    return False


def _heading_type_and_css(text: str) -> tuple[str, str] | None:
    """Map SUIN heading text to pipeline block type and markdown CSS class."""
    if _TITULO_RE.match(text):
        return ("title", "titulo_tit")
    if _CAPITULO_RE.match(text):
        return ("chapter", "capitulo_tit")
    if _SECCION_RE.match(text):
        return ("section", "seccion")
    return None


def _paragraphs_from_element(
    el,
    default_css: str,
    *,
    promote_first_article: bool = False,
) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    seen_tables: set[int] = set()

    for node in el.xpath(".//p|.//table[not(contains(@class, 'toc'))]"):
        if _is_hidden_or_note(node):
            continue
        if (node.tag or "").lower() == "table":
            table_id = id(node)
            if table_id in seen_tables:
                continue
            seen_tables.add(table_id)
            table_text = _table_to_markdown(node)
            if table_text:
                paragraphs.append(Paragraph(css_class="table", text=table_text))
            continue

        if node.xpath("ancestor::table"):
            continue

        _strip_descendants_with_classes(node, _NOISE_CLASSES)
        plain_text = _element_text(node)
        text = _inline_text(node)
        if not text or _NOTE_HEADING_RE.match(text) or _METADATA_CARD_RE.match(plain_text):
            continue
        css_class = default_css
        if promote_first_article and not paragraphs and _ARTICLE_RE.match(plain_text):
            css_class = "articulo"
        elif heading := _heading_type_and_css(plain_text):
            css_class = heading[1]
        elif _LIST_ITEM_RE.match(plain_text):
            css_class = "list_item"
            text = f"- {text}"
        if css_class == "firma_rey":
            # The transformer wraps firma_rey in **...**; feeding it text that
            # already contains **...** runs from <strong>/<em> produces broken
            # ****NAME**** or *****NAME***** in the output. Use plain text so
            # the transformer is the only source of bold.
            text = plain_text
        paragraphs.append(Paragraph(css_class=css_class, text=text))

    if paragraphs:
        return paragraphs

    text = _inline_text(el)
    if text and not _NOTE_HEADING_RE.match(text):
        return [Paragraph(css_class=default_css, text=text)]
    return []


def _extract_prior_version(
    toggle_div,
) -> tuple[list[Paragraph], date, date] | None:
    """Extract prior article text + validity range from a nested leg_ant div.

    SUIN embeds a "LEGISLACIÓN ANTERIOR" block inside each toggle_ article
    whose text was modified at least once. The block has:
      - A content container with the previous article text (paragraphs).
      - A footer `<font color="#336600">Vigente desde: X y hasta el: Y`.
    Returns (prior_paragraphs, desde, hasta) or ``None`` if unavailable.
    """
    legants = toggle_div.xpath('.//div[starts-with(@id, "div") and contains(@id, "leg_ant")]')
    if not legants:
        return None
    container = legants[0]

    range_match = _LEG_ANT_RANGE_RE.search(" ".join(container.itertext()))
    if not range_match:
        return None
    desde = _parse_date(range_match.group(1))
    hasta = _parse_date(range_match.group(2))
    if not desde or not hasta or desde >= hasta:
        return None

    import copy

    clone = copy.deepcopy(container)
    # Un-hide so _paragraphs_from_element doesn't drop it.
    clone.attrib.pop("style", None)
    clone.attrib.pop("id", None)
    for desc in clone.xpath('.//font[@color="#336600"]'):
        parent = desc.getparent()
        if parent is not None:
            parent.remove(desc)

    paragraphs = _paragraphs_from_element(clone, "parrafo", promote_first_article=True)
    if not paragraphs:
        return None
    return paragraphs, desde, hasta


def _is_signature_block(el) -> bool:
    text = _element_text(el)
    if re.search(r"\b(Dado en|Publ[ií]quese|Presidente|Ministro|Secretario)\b", text, re.I):
        return True
    return bool(el.xpath('.//p[contains(translate(@style, "RIGHT", "right"), "right")]'))


class SuinTextParser(TextParser):
    """Parses SUIN-Juriscol HTML page into Block objects."""

    def parse_text(self, data: bytes) -> list[Any]:
        """Parse the SUIN body container into Blocks."""
        if not data:
            return []

        try:
            tree = _parse_html(data)
        except Exception as exc:
            logger.warning("Failed to parse SUIN HTML: %s", exc)
            return []

        body_list = tree.xpath('//div[contains(@style, "padding: 15px")]')
        if not body_list:
            return []

        law_norm_id, pub_date = _extract_norm_id_and_pub_date(tree)
        body = body_list[0]
        blocks: list[Block] = []
        block_index = 0
        seen_article = False

        for child in body:
            tag = (child.tag or "").lower()
            if tag == "a" or _is_hidden_or_note(child):
                continue

            if tag == "p" and _METADATA_CARD_RE.match(_element_text(child)):
                continue

            child_id = child.get("id") or ""
            if child_id.startswith("toggle_"):
                prior = _extract_prior_version(child)
                paragraphs = _paragraphs_from_element(
                    child,
                    "parrafo",
                    promote_first_article=True,
                )
                if not paragraphs:
                    continue
                title = paragraphs[0].text
                match = _ARTICLE_RE.match(_element_text(child))
                article_id = match.group(1).lower() if match else str(block_index)
                block_id = f"p{article_id}"
                if prior:
                    prior_paragraphs, prior_from, prior_until = prior
                    blocks.append(
                        _make_block(
                            block_id,
                            "article",
                            title,
                            paragraphs,
                            pub_date,
                            law_norm_id,
                            prior_paragraphs=prior_paragraphs,
                            prior_from=prior_from,
                            prior_until=prior_until,
                        )
                    )
                else:
                    blocks.append(
                        _make_block(block_id, "article", title, paragraphs, pub_date, law_norm_id)
                    )
                seen_article = True
                block_index += 1
                continue

            paragraphs = _paragraphs_from_element(
                child,
                "firma_rey" if seen_article and _is_signature_block(child) else "parrafo",
            )
            if not paragraphs:
                continue

            first_text = paragraphs[0].text
            if any(para.css_class == "table" for para in paragraphs):
                block_type = "table"
                block_id = f"table-{block_index}"
                title = "Table"
            elif paragraphs[0].css_class in {"titulo_tit", "capitulo_tit", "seccion"}:
                block_type = {
                    "titulo_tit": "title",
                    "capitulo_tit": "chapter",
                    "seccion": "section",
                }[paragraphs[0].css_class]
                block_id = f"{block_type}-{block_index}"
                title = first_text
            elif paragraphs[0].css_class == "firma_rey":
                block_type = "signature"
                block_id = f"signature-{block_index}"
                title = first_text[:80]
            else:
                block_type = "text"
                block_id = f"text-{block_index}"
                title = first_text[:80]

            blocks.append(
                _make_block(block_id, block_type, title, paragraphs, pub_date, law_norm_id)
            )
            block_index += 1

        return blocks

    def extract_reforms(self, data: bytes) -> list[Any]:
        """Return reform points reconstructed from per-article leg_ant blocks.

        SUIN embeds one previous version per modified article
        (``LEGISLACIÓN ANTERIOR``) with its validity range. Parsing those
        yields a Version chain per article, and the generic block-based
        reform extractor turns each unique transition date into a Reform.
        """
        from legalize.transformer.xml_parser import extract_reforms

        return extract_reforms(self.parse_text(data))


class SuinMetadataParser(MetadataParser):
    """Parses SUIN-Juriscol HTML page metadata into NormMetadata."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        """Extract metadata from the hidden SUIN span[field] inventory."""
        if not data:
            raise ValueError(f"Empty data for norm {norm_id}")

        tree = _parse_html(data)
        fields = _extract_fields(tree)
        if not fields:
            raise ValueError(f"No SUIN metadata fields found for norm {norm_id}")

        title = (
            _element_text(tree.xpath('//div[@id="titulotipo"]//h1')[0])
            if tree.xpath('//div[@id="titulotipo"]//h1')
            else ""
        )
        if not title:
            h1 = tree.xpath("//h1")
            title = _element_text(h1[0]) if h1 else ""
        if not title:
            title = _clean_text(tree.xpath("string(//title)"))

        identifier = _normalize_identifier(fields, title, norm_id)
        status, status_extra = _status_from_text(fields.get("estado_documento", ""))
        subjects = tuple(
            subject.strip() for subject in fields.get("materia", "").split("|") if subject.strip()
        )
        publication_date = _pick_publication_date(fields)

        modification_items = tree.xpath(
            '//div[contains(@id, "ResumenNotasVigencia")]//li[contains(@class, "referencia")]'
        )

        extra: list[tuple[str, str]] = list(status_extra)
        raw_status = fields.get("estado_documento", "").strip()
        if raw_status:
            extra.append(("document_status_raw", raw_status))
        for field_name, extra_name in _EXTRA_TEXT_FIELDS:
            value = fields.get(field_name, "")
            if value:
                extra.append((extra_name, value[:1000]))
        for field_name, extra_name in _EXTRA_DATE_FIELDS:
            value = fields.get(field_name, "")
            if value:
                extra.append((extra_name, _normalize_extra_date(value)[:1000]))
        for field_name, extra_name in _EXTRA_BOOL_FIELDS:
            if fields.get(field_name, "").strip().lower() == "true":
                extra.append((extra_name, "true"))
        if subjects:
            extra.append(("subjects", " | ".join(subjects)))
        if modification_items:
            extra.append(("modification_count", str(len(modification_items))))
            seen: set[str] = set()
            unique: list[str] = []
            for item in modification_items:
                entry = _clean_text(_inline_text(item))
                if entry and entry not in seen:
                    seen.add(entry)
                    unique.append(entry)
            summary = " · ".join(unique)
            if len(summary) > 5000:
                boundary = summary[:5000].rfind(" · ")
                summary = summary[:boundary] if boundary > 0 else summary[:5000]
            if summary:
                extra.append(("modification_summary", summary))

        source_url = f"https://www.suin-juriscol.gov.co/viewDocument.asp?id={norm_id}"

        return NormMetadata(
            title=fields.get("epigrafe") or title or f"Norm {norm_id}",
            short_title=title or identifier,
            identifier=identifier,
            country="co",
            rank=Rank(_rank_from_rango(fields.get("tipo", ""))),
            publication_date=publication_date,
            status=status,
            department=fields.get("entidad_emisora", ""),
            source=source_url,
            subjects=subjects,
            summary=fields.get("epigrafe", ""),
            extra=tuple(extra),
        )
