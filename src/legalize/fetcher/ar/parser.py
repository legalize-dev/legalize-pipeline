"""Parser for InfoLEG HTML pages (Argentina).

InfoLEG serves two flavors per norm:

- ``texact.htm`` — current consolidated text with inline reform annotations
- ``norma.htm`` — original text as published in the B.O.

Both are HTML 4.01 with no semantic structure: articles are bold spans
followed by ``<br>`` and free-form paragraphs. The encoding is **windows-1252**
even when the meta tag declares ``ISO-8859-1`` (see RESEARCH-AR.md §5).

The parser handles:

- Article boundaries (``ARTICULO N°`` / ``Artículo N°`` / ``Art. N°``)
- Structural headings (TITULO / CAPITULO / SECCION) that appear inside ``<a name>``
- HTML tables → Markdown pipe tables (Código Civil y Comercial uses 8 of them)
- Inline ``<b>`` / ``<strong>`` / ``<i>`` / ``<em>`` → Markdown
- Reform annotations like ``(Artículo sustituido por art. X de la Ley YYYY B.O. DD/MM/YYYY)``
- Cross-reference ``<a href="verNorma.do?id=...">`` → Markdown links
- Decorative ``imagenes/left.png`` banner → dropped
- Tables-as-images (``ley27430-1.jpg``, etc.) → dropped, counted in ``extra.images_dropped``
- Anexo markers
- Em dashes ``&#8212;``, smart quotes, ``°``/``º``, ``&nbsp;`` runs

The metadata parser consumes the JSON-encoded catalog row produced by
:meth:`legalize.fetcher.ar.client.InfoLEGClient.get_metadata`.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from html import unescape
from typing import Any

from lxml import html as lxml_html

from legalize.fetcher.ar.reforms import INFOLEG_ENCODING
from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import Block, NormMetadata, NormStatus, Paragraph, Rank, Version

logger = logging.getLogger(__name__)


# ── Text cleaning ──

# C0 control chars (except \t \n \r) and C1 control chars (0x80–0x9F)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_WS_RUNS_RE = re.compile(r"[ \t]+")
_HTML_PARSER = lxml_html.HTMLParser(encoding=INFOLEG_ENCODING)


def _parse_html(data: bytes):
    """Parse InfoLEG HTML bytes into an lxml tree (cp1252 forced)."""
    if not data:
        return lxml_html.fromstring("<html><body></body></html>", parser=_HTML_PARSER)
    return lxml_html.fromstring(data, parser=_HTML_PARSER)


def _clean(text: str) -> str:
    """Normalize whitespace, strip control chars, decode HTML entities."""
    if not text:
        return ""
    text = unescape(text)
    text = text.replace("\xa0", " ")
    text = _CONTROL_CHAR_RE.sub("", text)
    text = _WS_RUNS_RE.sub(" ", text)
    text = text.replace("\r", "")
    return text.strip()


# ── Image classification ──

# The InfoLEG site banner: every page has it, drop without counting
_DECORATIVE_IMG_RE = re.compile(r"imagenes/(left|right|top|logo)\.(png|gif|jpg)", re.IGNORECASE)
# Content image filename heuristic: lowercase letters + digits + extension
_CONTENT_IMG_RE = re.compile(r"^[a-z0-9_-]+\d+\.(jpg|jpeg|png|gif)$", re.IGNORECASE)


def _classify_image(src: str) -> str:
    """Return one of: 'decorative', 'content', 'unknown'."""
    if not src:
        return "unknown"
    if _DECORATIVE_IMG_RE.search(src):
        return "decorative"
    fname = src.rsplit("/", 1)[-1]
    if _CONTENT_IMG_RE.match(fname):
        return "content"
    return "unknown"


def count_content_images(data: bytes) -> int:
    """Count non-decorative images in an InfoLEG HTML payload.

    Used to populate ``extra.images_dropped`` on the norm's metadata so
    downstream consumers know which norms lost content (e.g. tariff
    schedules published as scanned JPGs — see Ley 27.430 fixtures).
    """
    if not data:
        return 0
    try:
        tree = _parse_html(data)
    except Exception:  # pragma: no cover - defensive
        return 0
    n = 0
    for img in tree.iter("img"):
        src = img.get("src", "")
        if _classify_image(src) == "content":
            n += 1
    return n


# ── Inline → Markdown ──


def _inline_text(el) -> str:
    """Recursively extract inline text from an lxml element, mapping
    bold/italic/links to Markdown.

    Skips ``<script>``, ``<style>``, and decorative images.
    """
    parts: list[str] = []

    if el.text:
        parts.append(el.text)

    for child in el:
        tag = (child.tag if isinstance(child.tag, str) else "").lower()

        if tag in ("script", "style"):
            pass  # drop entirely
        elif tag == "br":
            parts.append("\n")
        elif tag in ("b", "strong"):
            inner = _inline_text(child)
            stripped = inner.strip()
            if stripped:
                parts.append(f"**{stripped}**")
        elif tag in ("i", "em"):
            inner = _inline_text(child)
            stripped = inner.strip()
            if stripped:
                parts.append(f"*{stripped}*")
        elif tag == "u":
            parts.append(_inline_text(child))
        elif tag == "a":
            inner = _inline_text(child)
            href = child.get("href", "")
            if href and inner.strip():
                # Normalize protocol-relative and root-relative links
                if href.startswith("//"):
                    href = "http:" + href
                elif href.startswith("/"):
                    href = "http://servicios.infoleg.gob.ar" + href
                parts.append(f"[{inner.strip()}]({href})")
            else:
                parts.append(inner)
        elif tag == "img":
            src = child.get("src", "")
            kind = _classify_image(src)
            if kind == "decorative":
                pass  # drop silently
            else:
                # Mark as a placeholder so the calling code can detect it.
                # The actual count is tracked at parse_text level.
                parts.append("[IMG]")
        elif tag == "span":
            classes = (child.get("class") or "") + " " + (child.get("style") or "")
            inner = _inline_text(child)
            stripped = inner.strip()
            if stripped:
                if "font-weight: bold" in (child.get("style") or "") or "bold" in classes.lower():
                    parts.append(f"**{stripped}**")
                elif "font-style: italic" in (child.get("style") or ""):
                    parts.append(f"*{stripped}*")
                else:
                    parts.append(stripped)
        elif tag in ("font", "small", "div"):
            parts.append(_inline_text(child))
        else:
            parts.append(_inline_text(child))

        if child.tail:
            parts.append(child.tail)

    return "".join(parts)


# ── Tables ──


def _table_to_markdown(table_el) -> str:
    """Convert an HTML ``<table>`` to a Markdown pipe table."""
    rows: list[list[str]] = []
    for tr in table_el.iter():
        tag = (tr.tag if isinstance(tr.tag, str) else "").lower()
        if tag != "tr":
            continue
        cells: list[str] = []
        for cell in tr:
            cell_tag = (cell.tag if isinstance(cell.tag, str) else "").lower()
            if cell_tag not in ("td", "th"):
                continue
            text = _clean(_inline_text(cell))
            cells.append(text.replace("|", "\\|"))
        if cells:
            rows.append(cells)
    if not rows:
        return ""

    max_cols = max(len(r) for r in rows)
    for r in rows:
        while len(r) < max_cols:
            r.append("")

    lines = []
    lines.append("| " + " | ".join(rows[0]) + " |")
    lines.append("| " + " | ".join("---" for _ in range(max_cols)) + " |")
    for r in rows[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


# ── Article extraction ──


# ARTICULO 1° / Artículo 1° / Art. 1° / ARTICULO 1.- / Artículo 1.- ...
_ARTICLE_MARKER_RE = re.compile(
    r"^\s*(?:ART[ÍI]?CULO|Art[íi]?culo|ART\.?|Art\.?)\s+"
    r"(\d+(?:\s*bis|\s*ter|\s*qu[áa]ter)?)\s*[°º\.]?",
    re.IGNORECASE,
)

# Heading markers TITULO/CAPITULO/SECCION
_HEADING_RE = re.compile(
    r"^\s*(LIBRO|T[ÍI]TULO|TITULO|CAP[ÍI]TULO|CAPITULO|SECCI[ÓO]N|SECCION|PAR[ÁA]GRAFO|PARAGRAFO|ANEXO)\s+",
    re.IGNORECASE,
)

# Reform annotation pattern (preserve as Markdown blockquote)
_REFORM_NOTE_RE = re.compile(
    r"\((Art[íi]culo[^)]{1,400}por\s+(?:art|el\s+art|la\s+ley|el\s+decreto|el\s+anexo)[^)]{1,400})\)",
    re.IGNORECASE,
)


def _extract_lines(html_root) -> list[tuple[str, str]]:
    """Walk the HTML root and yield (kind, text) lines.

    ``kind`` is one of:
        - 'heading'  — TITULO/CAPITULO/SECCION/LIBRO/PARAGRAFO/ANEXO marker
        - 'article'  — ARTICULO N marker (text starts with "ARTICULO N° ...")
        - 'note'     — reform annotation (already in parentheses)
        - 'paragraph' — regular text
        - 'table'    — Markdown pipe table
    """
    body = html_root.find(".//body")
    if body is None:
        body = html_root

    lines: list[tuple[str, str]] = []

    # We do a single inline pass over the entire body, then split by lines.
    full = _inline_text(body)

    # Insert table placeholders so we can re-stitch them in order.
    table_md: list[str] = []
    for table in body.iter():
        tag = (table.tag if isinstance(table.tag, str) else "").lower()
        if tag == "table":
            md = _table_to_markdown(table)
            if md:
                table_md.append(md)

    # Replace inline newlines run with single \n, then split
    for raw_line in full.split("\n"):
        line = _clean(raw_line)
        if not line:
            continue
        if _HEADING_RE.match(line):
            lines.append(("heading", line))
        elif _ARTICLE_MARKER_RE.match(line):
            lines.append(("article", line))
        elif _REFORM_NOTE_RE.match(line.lstrip()):
            lines.append(("note", line))
        else:
            lines.append(("paragraph", line))

    # Append tables at the end (we lose positional info but tables in
    # InfoLEG are usually annexes anyway). The downstream renderer can
    # surface them as a separate block.
    for md in table_md:
        lines.append(("table", md))

    return lines


def _split_into_blocks(
    lines: list[tuple[str, str]], pub_date: date, law_norm_id: str
) -> list[Block]:
    """Group lines into Blocks (preamble + one per article + tables/annexes).

    The first lines before the first article marker form a preamble block.
    Each article marker starts a new block; following paragraphs and notes
    accrue under the current article. Tables become standalone blocks.
    """
    blocks: list[Block] = []
    current_id: str | None = None
    current_title: str | None = None
    current_paragraphs: list[Paragraph] = []
    block_index = 0

    def _emit(block_type: str) -> None:
        nonlocal block_index, current_id, current_title, current_paragraphs
        if not current_paragraphs:
            return
        bid = current_id or f"{block_type}-{block_index}"
        title = current_title or current_paragraphs[0].text[:80]
        version = Version(
            norm_id=law_norm_id,
            publication_date=pub_date,
            effective_date=pub_date,
            paragraphs=tuple(current_paragraphs),
        )
        blocks.append(Block(id=bid, block_type=block_type, title=title, versions=(version,)))
        block_index += 1
        current_id = None
        current_title = None
        current_paragraphs = []

    in_preamble = True

    for kind, text in lines:
        if kind == "heading":
            # Headings become standalone blocks (chapter/title/section)
            if current_paragraphs:
                _emit("preamble" if in_preamble else "article")
            current_id = f"heading-{block_index}"
            current_title = text
            current_paragraphs = [Paragraph(css_class="capitulo_tit", text=text)]
            _emit("chapter")
            continue

        if kind == "article":
            if current_paragraphs:
                _emit("preamble" if in_preamble else "article")
            in_preamble = False
            m = _ARTICLE_MARKER_RE.match(text)
            art_num = m.group(1).replace(" ", "") if m else str(block_index)
            current_id = f"art{art_num}"
            current_title = text[:120]
            # First paragraph carries the article header for rendering
            current_paragraphs = [Paragraph(css_class="articulo", text=text)]
            continue

        if kind == "note":
            # Reform annotation — preserve as a quoted paragraph attached
            # to the current article
            current_paragraphs.append(Paragraph(css_class="cita", text=text))
            continue

        if kind == "table":
            # Tables become standalone blocks so they don't get tangled
            # with article paragraphs
            if current_paragraphs:
                _emit("preamble" if in_preamble else "article")
            current_id = f"table-{block_index}"
            current_title = "Tabla"
            current_paragraphs = [Paragraph(css_class="table", text=text)]
            _emit("table")
            continue

        # Regular paragraph
        current_paragraphs.append(Paragraph(css_class="parrafo", text=text))

    if current_paragraphs:
        _emit("preamble" if in_preamble else "article")

    return blocks


# ── Text parser ──


class InfoLEGTextParser(TextParser):
    """Parses InfoLEG HTML (texact.htm or norma.htm) into Block objects.

    The parser is encoding-strict (cp1252) and content-only: scripts, styles,
    decorative images, and the InfoLEG header banner are dropped.

    Reform annotations are extracted as ``cita`` paragraphs attached to the
    article they refer to. The actual reform timeline is reconstructed by
    :mod:`legalize.fetcher.ar.reforms`, not by this parser.
    """

    def parse_text(self, data: bytes) -> list[Any]:
        if not data:
            return []
        try:
            tree = _parse_html(data)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to parse InfoLEG HTML: %s", exc)
            return []

        # Pub date and norm_id are not in the HTML — they come from the
        # catalog metadata, which the pipeline merges later. Use placeholders
        # that the pipeline overrides via NormMetadata.
        pub_date = date(1900, 1, 1)
        law_norm_id = "0"

        lines = _extract_lines(tree)
        blocks = _split_into_blocks(lines, pub_date, law_norm_id)
        return blocks

    def extract_reforms(self, data: bytes) -> list[Any]:
        """Reform timeline reconstruction is handled outside this parser.

        InfoLEG inline annotations only show the **last** reform that
        touched each article (and only as text), so we cannot derive a
        complete timeline from a single texact.htm. The full timeline is
        built by the pipeline using :class:`InfoLEGCatalog.modifications_of`
        plus per-modificatoria text via :mod:`legalize.fetcher.ar.reforms`.
        """
        return []


# ── Metadata parser ──


# tipo_norma → Rank string mapping (lowercase snake_case for filesystem)
_RANK_MAP: dict[str, str] = {
    "Ley": "ley",
    "Decreto": "decreto",
    "Decreto/Ley": "decreto_ley",
    "Decisión Administrativa": "decision_administrativa",
    "Resolución": "resolucion",
    "Disposición": "disposicion",
    "Comunicación": "comunicacion",
    "Acordada": "acordada",
    "Directiva": "directiva",
    "Decisión": "decision",
    "Instrucción": "instruccion",
    "Nota Externa": "nota_externa",
    "Nota": "nota",
    "Circular": "circular",
    "Acta": "acta",
    "Recomendación": "recomendacion",
    "Laudo": "laudo",
    "Convenio": "convenio",
    "Acuerdo": "acuerdo",
    "Providencia": "providencia",
    "Protocolo": "protocolo",
    "Ordenanza": "ordenanza",
    "Interpretación": "interpretacion",
    "Actuacion": "actuacion",
}

# Special-case rank for tipo=Decreto + clase=DNU
_DNU_RANK = "decreto_necesidad_urgencia"


def _make_identifier(
    tipo_norma: str,
    numero_norma: str,
    clase_norma: str,
    fecha_boletin: str,
    id_norma: str = "",
    fecha_sancion: str = "",
) -> str:
    """Build the filesystem-safe identifier (e.g. ``LEY-26994``, ``DNU-70-2023``).

    Rules:
    - Leyes: ``LEY-{number}`` (sequential, no year)
    - Decretos with DNU class: ``DNU-{number}-{year}``
    - Decretos: ``DEC-{number}-{year}``
    - Decreto/Ley: ``DL-{number}-{year}``
    - Other types: ``{PREFIX}-{number}-{year}``
    - Norms without ``numero_norma`` (``S/N`` = sin número): fall back to
      ``{PREFIX}-SN-{id_norma}`` so unnumbered norms never collide.
    """
    prefix_map = {
        "Ley": "LEY",
        "Decreto": "DEC",
        "Decreto/Ley": "DL",
        "Decisión Administrativa": "DA",
        "Resolución": "RES",
        "Disposición": "DISP",
        "Comunicación": "COM",
    }
    prefix = prefix_map.get(tipo_norma, "NORMA")
    if tipo_norma == "Decreto" and clase_norma == "DNU":
        prefix = "DNU"

    safe_number = numero_norma.replace(".", "").replace("/", "-").replace(" ", "")
    # InfoLEG uses "S/N" (sin número) for unnumbered norms — fall back to
    # the opaque id_norma so filenames never collide across 150+ such norms.
    if not safe_number or safe_number.upper() in ("SN", "S-N"):
        return f"{prefix}-SN-{id_norma}" if id_norma else f"{prefix}-SN"

    if tipo_norma == "Ley":
        return f"{prefix}-{safe_number}"

    # Year comes from fecha_boletin first, fecha_sancion as fallback
    year = ""
    if fecha_boletin and len(fecha_boletin) >= 4 and fecha_boletin[:4].isdigit():
        year = fecha_boletin[:4]
    elif fecha_sancion and len(fecha_sancion) >= 4 and fecha_sancion[:4].isdigit():
        year = fecha_sancion[:4]

    if year:
        return f"{prefix}-{safe_number}-{year}"
    return f"{prefix}-{safe_number}"


def _parse_iso_date(s: str) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


class InfoLEGMetadataParser(MetadataParser):
    """Parses an InfoLEG catalog row (JSON) into :class:`NormMetadata`.

    The input is the JSON blob produced by
    :meth:`legalize.fetcher.ar.client.InfoLEGClient.get_metadata` — a
    serialized :class:`InfoLEGRow`. We deliberately don't try to parse
    the HTML for metadata: the catalog is the authoritative source.
    """

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        if not data:
            raise ValueError(f"Empty metadata for norm {norm_id}")

        row = json.loads(data.decode("utf-8"))

        tipo_norma = row.get("tipo_norma", "")
        numero_norma = row.get("numero_norma", "")
        clase_norma = row.get("clase_norma", "")
        fecha_boletin_s = row.get("fecha_boletin", "")
        fecha_sancion_s = row.get("fecha_sancion", "")

        # Rank
        rank_str = _RANK_MAP.get(tipo_norma, "otro")
        if tipo_norma == "Decreto" and clase_norma == "DNU":
            rank_str = _DNU_RANK

        # Identifier
        identifier = _make_identifier(
            tipo_norma,
            numero_norma,
            clase_norma,
            fecha_boletin_s,
            id_norma=str(row.get("id_norma", "")),
            fecha_sancion=fecha_sancion_s,
        )

        # Title and short title
        full_title = row.get("titulo_sumario", "") or row.get("titulo_resumido", "") or identifier
        short_title = row.get("titulo_resumido", "") or full_title

        # Dates: prefer fecha_boletin, fall back to fecha_sancion, then to
        # a sentinel. Many pre-1997 catalog rows only have fecha_sancion.
        pub_date = (
            _parse_iso_date(fecha_boletin_s) or _parse_iso_date(fecha_sancion_s) or date(1900, 1, 1)
        )

        # Status: InfoLEG catalog does not encode "derogada" explicitly in
        # this CSV. We default to IN_FORCE; the reform pipeline can flip
        # to REPEALED based on inline annotations or the modifications graph.
        status = NormStatus.IN_FORCE

        # Source URL: prefer texto_actualizado, fall back to texto_original
        source = row.get("texto_actualizado") or row.get("texto_original") or ""

        # Extra fields — capture EVERYTHING InfoLEG gives us, English snake_case keys
        extra: list[tuple[str, str]] = []
        if row.get("id_norma"):
            extra.append(("infoleg_id", str(row["id_norma"])))
        if clase_norma:
            extra.append(("norm_class", clase_norma))
        if fecha_sancion_s:
            extra.append(("enactment_date", fecha_sancion_s))
        if row.get("numero_boletin"):
            extra.append(("gazette_number", str(row["numero_boletin"])))
        if row.get("pagina_boletin"):
            extra.append(("gazette_page", str(row["pagina_boletin"])))
        if row.get("texto_resumido"):
            # Trim to keep frontmatter readable
            extra.append(("texto_resumido", row["texto_resumido"][:1000]))
        if row.get("observaciones"):
            extra.append(("observaciones", row["observaciones"][:1000]))
        if row.get("texto_original"):
            extra.append(("original_text_url", row["texto_original"]))
        if row.get("modificada_por"):
            extra.append(("times_modified", str(row["modificada_por"])))
        if row.get("modifica_a"):
            extra.append(("modifies_count", str(row["modifica_a"])))

        return NormMetadata(
            title=full_title,
            short_title=short_title,
            identifier=identifier,
            country="ar",
            rank=Rank(rank_str),
            publication_date=pub_date,
            status=status,
            department=row.get("organismo_origen", ""),
            source=source,
            summary=row.get("texto_resumido", "")[:500],
            extra=tuple(extra),
        )
