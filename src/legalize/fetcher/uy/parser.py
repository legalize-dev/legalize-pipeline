"""Parser for IMPO JSON documents (Uruguay).

IMPO returns `application/json; charset=ISO-8859-1` — responses must be
decoded as Latin-1, never via `requests` auto-detection.

Schema (validated 2026-04-07 against 5 live fixtures in
engine/tests/fixtures/uy/ — see RESEARCH-URUGUAY.md §4.8 for the full
metadata and formatting inventory):

Top-level fields (union across the 5 fixtures):
    tipoNorma, nroNorma, anioNorma, nombreNorma, leyenda,
    urlVerImagen, fechaPromulgacion, fechaPublicacion,
    urlReferenciasTodaLaNorma, vistos, firmantes, articulos,
    referenciasNorma, obsPublicacion, RNLD

Article-level fields:
    nroArticulo, tituloArticulo, titulosArticulo, textoArticulo,
    notasArticulo, urlArticulo, urlReferenciasArticulo, secArticulo

IMPO embeds rich formatting (tables, bold, italic, links, font colors)
as HTML fragments inside text fields. The parser preserves every
construct that reaches the output Markdown:
    <TABLE>         → Markdown pipe table
    <b> / <strong>  → **bold**
    <i> / <em>      → *italic*
    <a href="...">  → [text](absolute URL)
    <font color=…>  → inner text only
    <br>            → paragraph split
    <pre> in cells  → cell text only
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import Any

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    Rank,
    Reform,
    Version,
)
from legalize.fetcher._text import strip_control

logger = logging.getLogger(__name__)

IMPO_BASE_URL = "https://www.impo.com.uy"

# Map IMPO tipoNorma (lowercased) to internal rank strings.
TIPO_TO_RANK: dict[str, str] = {
    "ley": "ley",
    "decreto ley": "decreto_ley",
    "decreto-ley": "decreto_ley",
    "decreto": "decreto",
    "constitucion": "constitucion",
    "constitucion de la republica": "constitucion",
    "constitución": "constitucion",
    "constitución de la república": "constitucion",
    "codigo": "codigo",
    "código": "codigo",
    "codigo civil": "codigo",
    "código civil": "codigo",
    "codigo penal": "codigo",
    "código penal": "codigo",
    "codigo tributario": "codigo",
    "código tributario": "codigo",
    "codigo de comercio": "codigo",
    "código de comercio": "codigo",
    "codigo rural": "codigo",
    "código rural": "codigo",
    "codigo del nino": "codigo",
    "código del niño": "codigo",
    "codigo aduanero": "codigo",
    "código aduanero": "codigo",
    "codigo procesal penal": "codigo",
    "código procesal penal": "codigo",
    "codigo general del proceso": "codigo",
    "código general del proceso": "codigo",
    "codigo de aguas": "codigo",
    "código de aguas": "codigo",
    "resolucion": "resolucion",
    "resolución": "resolucion",
    "reglamento": "reglamento",
    "ordenanza departamental": "ordenanza_departamental",
}

# Match a whole <TABLE>…</TABLE> block. Case-insensitive, dot matches newline.
_TABLE_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.IGNORECASE | re.DOTALL)

# Match a row inside a table.
_TR_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)

# Match a cell (td or th) inside a row.
_CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)

# Inline HTML patterns handled by _inline_html_to_markdown.
_A_RE = re.compile(
    r"<a\b[^>]*\bhref\s*=\s*[\"']([^\"']*)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL
)
_BOLD_RE = re.compile(r"<(?:b|strong)\b[^>]*>(.*?)</(?:b|strong)>", re.IGNORECASE | re.DOTALL)
_ITALIC_RE = re.compile(r"<(?:i|em)\b[^>]*>(.*?)</(?:i|em)>", re.IGNORECASE | re.DOTALL)
_FONT_RE = re.compile(r"<font\b[^>]*>(.*?)</font>", re.IGNORECASE | re.DOTALL)
_PRE_RE = re.compile(r"<pre\b[^>]*>(.*?)</pre>", re.IGNORECASE | re.DOTALL)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_ANY_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")

# HTML entities we want to decode by hand (html.unescape covers the rest).
_ENTITIES = {
    "&nbsp;": "\u00a0",
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&apos;": "'",
}


def _decode_json(data: bytes) -> dict:
    """Decode IMPO JSON.

    IMPO responses are Latin-1 (`charset=ISO-8859-1`). Attempt Latin-1
    first, then UTF-8 as a fallback for synthetic test data.
    """
    for encoding in ("latin-1", "utf-8"):
        try:
            return json.loads(data.decode(encoding))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    raise ValueError("Could not decode IMPO JSON response")


def _parse_date(s: str | None) -> date | None:
    """Parse IMPO date strings.

    IMPO uses `dd/mm/yyyy`. Also accepts `yyyy-mm-dd` for robustness.
    Returns None for empty/invalid input.
    """
    if not s or not s.strip():
        return None
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _format_date(d: date | None) -> str:
    return d.isoformat() if d else ""


def _strip_control_chars(text: str) -> str:
    return strip_control(text)


def _normalize_whitespace(text: str) -> str:
    """Normalize whitespace inside a paragraph run.

    - CRLF → LF
    - Collapse runs of spaces/tabs to a single space
    - Trim trailing spaces on each line
    - Collapse 3+ blank lines to 2 (paragraph separator)
    - Strip leading and trailing whitespace from the whole run
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_WS_RE.sub(" ", line).rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    return text.strip()


def _decode_entities(text: str) -> str:
    import html as _html

    for entity, char in _ENTITIES.items():
        text = text.replace(entity, char)
    return _html.unescape(text)


def _absolute_url(href: str) -> str:
    """Turn an IMPO relative href into an absolute URL."""
    href = href.strip()
    if not href:
        return href
    if href.startswith(("http://", "https://", "mailto:")):
        return href
    if href.startswith("//"):
        return f"https:{href}"
    if not href.startswith("/"):
        href = f"/{href}"
    return f"{IMPO_BASE_URL}{href}"


def _inline_html_to_markdown(text: str) -> str:
    """Convert IMPO inline HTML to Markdown, preserving bold/italic/links.

    Runs in a fixed order:
        1. <pre>…</pre>        → inner text (IMPO uses <pre> only as a
                                 monospace cell wrapper inside tables)
        2. <font …>…</font>    → inner text
        3. <a href="…">…</a>   → [text](absolute URL)
        4. <b>/<strong>        → **text**
        5. <i>/<em>            → *text*
        6. Any remaining tag   → stripped
        7. HTML entities       → unicode
        8. Whitespace normalize
    """
    if not text:
        return ""

    text = _PRE_RE.sub(lambda m: m.group(1), text)
    text = _FONT_RE.sub(lambda m: m.group(1), text)

    def _a_sub(m: re.Match) -> str:
        href = _absolute_url(m.group(1))
        inner = _inline_html_to_markdown(m.group(2))
        inner = inner.replace("[", "(").replace("]", ")").strip()
        if not inner:
            inner = href
        return f"[{inner}]({href})"

    text = _A_RE.sub(_a_sub, text)

    def _bold_sub(m: re.Match) -> str:
        inner = _inline_html_to_markdown(m.group(1)).strip()
        return f"**{inner}**" if inner else ""

    text = _BOLD_RE.sub(_bold_sub, text)

    def _italic_sub(m: re.Match) -> str:
        inner = _inline_html_to_markdown(m.group(1)).strip()
        return f"*{inner}*" if inner else ""

    text = _ITALIC_RE.sub(_italic_sub, text)

    text = _ANY_TAG_RE.sub("", text)
    text = _decode_entities(text)
    text = _strip_control_chars(text)
    return _normalize_whitespace(text)


def _cell_to_markdown(cell_html: str) -> str:
    """Convert a single table cell's HTML to a single Markdown-safe line."""
    text = _inline_html_to_markdown(cell_html)
    # Markdown pipe tables cannot contain newlines or pipes in cells.
    text = text.replace("\n", " ").replace("|", "\\|")
    return text.strip() or " "


def _table_to_markdown(table_html: str) -> str:
    """Convert an IMPO <TABLE> HTML block to a Markdown pipe table."""
    rows: list[list[str]] = []
    for row_match in _TR_RE.finditer(table_html):
        cells = [_cell_to_markdown(c.group(1)) for c in _CELL_RE.finditer(row_match.group(1))]
        if cells:
            rows.append(cells)

    if not rows:
        return ""

    # Normalize to the widest row.
    width = max(len(r) for r in rows)
    for row in rows:
        while len(row) < width:
            row.append(" ")

    header = rows[0]
    body = rows[1:]
    sep = ["---"] * width

    def fmt(row: list[str]) -> str:
        return "| " + " | ".join(row) + " |"

    lines = [fmt(header), fmt(sep)]
    for row in body:
        lines.append(fmt(row))
    return "\n".join(lines)


def _split_text_by_tables(html: str) -> list[tuple[str, str]]:
    """Split a text fragment into alternating ('text', ...) and ('table', ...).

    Returns a list of (kind, content) pairs in original order.
    """
    pieces: list[tuple[str, str]] = []
    last = 0
    for m in _TABLE_RE.finditer(html):
        if m.start() > last:
            pieces.append(("text", html[last : m.start()]))
        pieces.append(("table", m.group(0)))
        last = m.end()
    if last < len(html):
        pieces.append(("text", html[last:]))
    return pieces


def _split_titulos(raw: str) -> list[str]:
    """Split a `titulosArticulo` value into its heading segments.

    IMPO separates nested headings with `<br>`. Returns a list of clean
    heading strings, with runs of whitespace collapsed.
    """
    if not raw:
        return []
    parts = _BR_RE.split(raw)
    out: list[str] = []
    for part in parts:
        cleaned = _inline_html_to_markdown(part)
        if cleaned:
            out.append(cleaned)
    return out


def _heading_css_class(title: str) -> str:
    """Map an IMPO section/chapter heading to a css class the renderer knows."""
    upper = title.upper()
    if upper.startswith(("TITULO", "TÍTULO", "LIBRO", "PARTE")):
        return "titulo"
    if upper.startswith(("CAPITULO", "CAPÍTULO")):
        return "capitulo_tit"
    # SECCION, SUBSECCION, ANEXO, and anything else
    return "seccion"


def _make_identifier(doc: dict, collection_path: str) -> str:
    """Build the filesystem-safe identifier for a norm.

    Examples:
        UY-ley-19996
        UY-decreto-ley-14261
        UY-decreto-122-2021       (decree numbers reset each year)
        UY-codigo-tributario-14306
        UY-constitucion-1967
    """
    tipo = (doc.get("tipoNorma") or "").strip().lower()
    nro = (doc.get("nroNorma") or "").strip()
    anio = doc.get("anioNorma")
    coll_prefix = collection_path.split("/", 1)[0] if collection_path else ""

    if "constitucion" in coll_prefix or "constitucion" in tipo or "constitución" in tipo:
        year = anio or _extract_year_from_path(collection_path)
        return f"UY-constitucion-{year}"

    if coll_prefix == "decretos-ley" or ("decreto" in tipo and "ley" in tipo):
        return f"UY-decreto-ley-{nro}" if nro else "UY-decreto-ley-unknown"

    if coll_prefix.startswith("codigo-") or "código" in tipo or (tipo.startswith("codigo")):
        # Use the collection slug (codigo-civil) when available; fall back to tipoNorma.
        slug = coll_prefix if coll_prefix.startswith("codigo-") else _slugify(tipo)
        return f"UY-{slug}-{nro}" if nro else f"UY-{slug}"

    if coll_prefix == "leyes" or (tipo == "ley" and not coll_prefix.startswith("decreto")):
        return f"UY-ley-{nro}" if nro else "UY-ley-unknown"

    if coll_prefix == "decretos" or tipo == "decreto":
        suffix = f"-{anio}" if anio else ""
        return f"UY-decreto-{nro}{suffix}" if nro else "UY-decreto-unknown"

    slug = _slugify(tipo) or "otro"
    return f"UY-{slug}-{nro}" if nro else f"UY-{slug}"


def _slugify(text: str) -> str:
    """Lowercase, strip accents, keep a-z0-9-."""
    import unicodedata

    nf = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in nf if not unicodedata.combining(c))
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return ascii_text


def _extract_year_from_path(collection_path: str) -> str:
    match = re.search(r"(\d{4})", collection_path)
    return match.group(1) if match else "unknown"


# Frontmatter values are emitted as YAML double-quoted strings, which do not
# support embedded newlines safely with our minimal renderer — collapse them.
def _flatten(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _cap(value: str, limit: int = 500) -> str:
    value = _flatten(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _build_extra(
    doc: dict,
    collection_path: str,
    article_count: int,
    images_dropped: int,
    editorial_notes_count: int,
) -> tuple[tuple[str, str], ...]:
    """Capture every top-level IMPO field in extra with English keys.

    Rule: if IMPO exposes it, we capture it. Long HTML fields are cleaned
    and capped (500 chars by default; 2000 for narrative fields like
    vistos and references_html where the full text is informative).
    Internal whitespace is collapsed so the YAML frontmatter renderer
    (single-line double-quoted strings) handles every value safely.
    """
    extras: list[tuple[str, str]] = []
    coll_prefix = collection_path.split("/", 1)[0] if collection_path else ""

    def add(key: str, value: Any, *, limit: int = 500) -> None:
        if value is None:
            return
        text = value if isinstance(value, str) else str(value)
        cleaned = _strip_control_chars(text).strip()
        if not cleaned:
            return
        extras.append((key, _cap(cleaned, limit=limit)))

    add("official_type", doc.get("tipoNorma"))
    add("official_number", doc.get("nroNorma"))
    add("year", doc.get("anioNorma"))
    add("promulgation_date", _format_date(_parse_date(doc.get("fechaPromulgacion"))))
    add("update_label", doc.get("leyenda"))

    if doc.get("urlVerImagen"):
        add("gazette_scan_url", _absolute_url(doc["urlVerImagen"]))
    if doc.get("urlReferenciasTodaLaNorma"):
        add("references_url", _absolute_url(doc["urlReferenciasTodaLaNorma"]))

    if doc.get("referenciasNorma"):
        add("references_html", _inline_html_to_markdown(doc["referenciasNorma"]), limit=2000)
    if doc.get("obsPublicacion"):
        add("publication_section", _inline_html_to_markdown(doc["obsPublicacion"]))

    rnld = doc.get("RNLD")
    if isinstance(rnld, dict) and rnld:
        parts = []
        if rnld.get("tomo"):
            parts.append(f"tomo {rnld['tomo']}")
        if rnld.get("semestre"):
            parts.append(f"semestre {rnld['semestre']}")
        if rnld.get("anio"):
            parts.append(str(rnld["anio"]))
        if rnld.get("pagina"):
            parts.append(f"p. {rnld['pagina']}")
        if parts:
            extras.append(("rnld_citation", ", ".join(parts)))

    if doc.get("vistos"):
        add("vistos", _inline_html_to_markdown(doc["vistos"]), limit=2000)
    if doc.get("firmantes"):
        add("signatories", _inline_html_to_markdown(doc["firmantes"]))

    add("article_count", article_count)
    if coll_prefix:
        add("collection", coll_prefix)
    add("source_encoding", "ISO-8859-1")
    add("images_dropped", images_dropped)
    # IMPO replicates the same editorial note across consecutive articles
    # (e.g. "Ver en esta norma, artículo: 80" sits on 51 of the
    # Constitution's 332 articles). The notes are IMPO editorial content,
    # not legal text approved by the parliament, so they are NOT rendered
    # in the body — only the count is captured here, so a downstream
    # consumer can refetch the IMPO page if it needs the full notes.
    add("editorial_notes_count", editorial_notes_count)

    return tuple(extras)


# ─────────────────────────────────────────────
# TextParser
# ─────────────────────────────────────────────


def _text_to_paragraphs(html: str, pub_date: date, norm_id: str) -> list[Paragraph]:
    """Convert an article's textoArticulo HTML into a list of Paragraphs.

    Splits the HTML around <TABLE> blocks and emits:
        - ('text', fragment)   → one or more `parrafo` Paragraphs
                                 (split on blank lines inside the text)
        - ('table', fragment)  → a single `table_md` Paragraph whose text
                                 is the full Markdown pipe table — the
                                 renderer passes unknown css_classes
                                 through unchanged, so the pipe table
                                 reaches the file verbatim
    """
    paragraphs: list[Paragraph] = []
    for kind, chunk in _split_text_by_tables(html):
        if kind == "table":
            md = _table_to_markdown(chunk)
            if md:
                paragraphs.append(Paragraph(css_class="table_md", text=md))
            continue

        text = _inline_html_to_markdown(chunk)
        if not text:
            continue
        # Split on blank lines so paragraph breaks survive the round-trip.
        for para in re.split(r"\n\s*\n", text):
            para = para.strip()
            if para:
                paragraphs.append(Paragraph(css_class="parrafo", text=para))
    return paragraphs


class IMPOTextParser(TextParser):
    """Parses IMPO JSON into Block objects."""

    def parse_text(self, data: bytes) -> list[Any]:
        if not data:
            return []

        doc = _decode_json(data)
        articulos = doc.get("articulos") or []
        if not articulos:
            return []

        pub_date = _parse_date(doc.get("fechaPublicacion")) or date(1900, 1, 1)
        norm_identifier = (doc.get("nroNorma") or "").strip() or "unknown"

        blocks: list[Block] = []
        last_headings: list[str] = []

        for art in articulos:
            nro = (art.get("nroArticulo") or "").strip()
            titulo_raw = art.get("tituloArticulo") or ""
            titulo = _inline_html_to_markdown(titulo_raw) or (
                f"Artículo {nro}" if nro else "Artículo"
            )
            titulos_raw = art.get("titulosArticulo") or ""
            texto_raw = art.get("textoArticulo") or ""

            # Emit heading blocks for any NEW titulosArticulo segments.
            segments = _split_titulos(titulos_raw)
            for i, segment in enumerate(segments):
                if i < len(last_headings) and last_headings[i] == segment:
                    continue  # same heading as previous article at this level
                css = _heading_css_class(segment)
                heading_id = f"heading-{_slugify(segment) or nro or len(blocks)}"
                heading_version = Version(
                    norm_id=norm_identifier,
                    publication_date=pub_date,
                    effective_date=pub_date,
                    paragraphs=(Paragraph(css_class=css, text=segment),),
                )
                blocks.append(
                    Block(
                        id=heading_id,
                        block_type="heading",
                        title=segment,
                        versions=(heading_version,),
                    )
                )
            if segments:
                last_headings = segments

            # Build the paragraph list for this article. The body contains
            # ONLY the legal text (textoArticulo); notasArticulo is IMPO
            # editorial content (cross-references and amendment history)
            # and is intentionally excluded — its count is captured in
            # extra.editorial_notes_count.
            paragraphs: list[Paragraph] = [Paragraph(css_class="articulo", text=titulo)]
            body_text = texto_raw.strip()
            if body_text == "(*)":
                paragraphs.append(Paragraph(css_class="parrafo", text="(*)"))
            else:
                paragraphs.extend(_text_to_paragraphs(texto_raw, pub_date, norm_identifier))

            art_id = f"art-{nro}" if nro else f"art-{len(blocks)}"
            version = Version(
                norm_id=norm_identifier,
                publication_date=pub_date,
                effective_date=pub_date,
                paragraphs=tuple(paragraphs),
            )
            blocks.append(
                Block(
                    id=art_id,
                    block_type="articulo",
                    title=titulo,
                    versions=(version,),
                )
            )

        # Trailing signatories block (firmantes) rendered in bold.
        firmantes = _inline_html_to_markdown(doc.get("firmantes") or "")
        if firmantes:
            sig_version = Version(
                norm_id=norm_identifier,
                publication_date=pub_date,
                effective_date=pub_date,
                paragraphs=(Paragraph(css_class="firma_rey", text=firmantes),),
            )
            blocks.append(
                Block(
                    id="firmantes",
                    block_type="firma",
                    title="Firmantes",
                    versions=(sig_version,),
                )
            )

        return blocks

    def extract_reforms(self, data: bytes) -> list[Any]:
        """IMPO publishes consolidated text only → single bootstrap point."""
        if not data:
            return []
        doc = _decode_json(data)
        pub_date = _parse_date(doc.get("fechaPublicacion"))
        if not pub_date:
            return []
        block_ids = tuple(
            f"art-{(a.get('nroArticulo') or '').strip()}" for a in (doc.get("articulos") or [])
        )
        return [Reform(date=pub_date, norm_id="bootstrap", affected_blocks=block_ids)]


# ─────────────────────────────────────────────
# MetadataParser
# ─────────────────────────────────────────────


class IMPOMetadataParser(MetadataParser):
    """Parses IMPO JSON metadata into NormMetadata."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        if not data:
            raise ValueError(f"Empty data for {norm_id}")

        doc = _decode_json(data)

        tipo_raw = _strip_control_chars((doc.get("tipoNorma") or "").strip())
        nombre_raw = _strip_control_chars((doc.get("nombreNorma") or "").strip())
        nro = _strip_control_chars((doc.get("nroNorma") or "").strip())

        # Title construction: "Ley Nº 19996 - Nombre de la Ley"
        if nombre_raw and nro:
            title = (
                f"{tipo_raw} Nº {nro} - {nombre_raw}" if tipo_raw else f"Nº {nro} - {nombre_raw}"
            )
        elif nombre_raw:
            title = f"{tipo_raw} - {nombre_raw}" if tipo_raw else nombre_raw
        elif nro and tipo_raw:
            title = f"{tipo_raw} Nº {nro}"
        else:
            title = tipo_raw or norm_id

        short_title = nombre_raw or title

        identifier = _make_identifier(doc, norm_id)
        rank_str = TIPO_TO_RANK.get(tipo_raw.lower(), "otro")
        pub_date = _parse_date(doc.get("fechaPublicacion")) or date(1900, 1, 1)
        firmantes_clean = _inline_html_to_markdown(doc.get("firmantes") or "")
        department = firmantes_clean  # top-level signatory body acts as issuing authority
        source_url = f"{IMPO_BASE_URL}/bases/{norm_id}"

        articulos = doc.get("articulos") or []
        editorial_notes_count = sum(1 for a in articulos if (a.get("notasArticulo") or "").strip())
        extras = _build_extra(
            doc,
            collection_path=norm_id,
            article_count=len(articulos),
            images_dropped=0,
            editorial_notes_count=editorial_notes_count,
        )

        return NormMetadata(
            title=title,
            short_title=short_title,
            identifier=identifier,
            country="uy",
            rank=Rank(rank_str),
            publication_date=pub_date,
            status=NormStatus.IN_FORCE,
            department=department,
            source=source_url,
            last_modified=_parse_date(doc.get("fechaPromulgacion")),
            pdf_url=_absolute_url(doc["urlVerImagen"]) if doc.get("urlVerImagen") else None,
            subjects=(),
            summary="",
            extra=extras,
        )


# Helpers exported for the test suite.
__all__ = [
    "IMPOTextParser",
    "IMPOMetadataParser",
    "_absolute_url",
    "_build_extra",
    "_decode_json",
    "_flatten",
    "_inline_html_to_markdown",
    "_make_identifier",
    "_normalize_whitespace",
    "_parse_date",
    "_slugify",
    "_split_text_by_tables",
    "_split_titulos",
    "_strip_control_chars",
    "_table_to_markdown",
]
