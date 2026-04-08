"""Parser for Chilean BCN XML documents (Ley Chile).

XML schema: http://www.leychile.cl/esquemas/EsquemaIntercambioNorma-v1-0.xsd
Namespace: http://www.leychile.cl/esquemas
Binaries namespace: http://valida.aem.gob.cl

Root structure (validated 2026-04-07 against 5 live fixtures):

  <Norma normaId="..." derogado="..." esTratado="..." fechaVersion="..." SchemaVersion="1.0">
    <Identificador fechaPromulgacion="..." fechaPublicacion="...">
      <TiposNumeros><TipoNumero><Tipo/><Numero/></TipoNumero></TiposNumeros>
      <Organismos><Organismo/>+</Organismos>
    </Identificador>
    <Metadatos>
      <TituloNorma/>
      <Materias><Materia/>+</Materias>
      <NombresUsoComun><NombreUsoComun/>+</NombresUsoComun>
      <IdentificacionFuente/>        e.g. "Diario Oficial"
      <NumeroFuente/>                 gazette issue number
      <FechaDerogacion/>              only if norm fully repealed
    </Metadatos>
    <Encabezado fechaVersion="..." derogado="..."><Texto/></Encabezado>
    <EstructurasFuncionales>
      <EstructuraFuncional tipoParte="Libro|Título|Capítulo|Párrafo|Sección|Artículo|Disposición Transitoria"
                           idParte="..." derogado="..." fechaVersion="..." transitorio="...">
        <Texto/>                                          may contain aem:ArchivoBinario children
        <Metadatos>
          <NombreParte presente="si|no"/>
          <TituloParte presente="si|no"/>
          <FechaDerogacion/>                              per-part repeal date (if any)
          <Materias><Materia/></Materias>                 per-part subjects (rare)
        </Metadatos>
        <EstructurasFuncionales>...</EstructurasFuncionales>  nested recursively
      </EstructuraFuncional>
    </EstructurasFuncionales>
    <Anexos>
      <Anexo idParte="..." fechaVersion="..." derogado="..." transitorio="...">
        <Metadatos><Titulo/></Metadatos>
        <Texto/>
      </Anexo>
    </Anexos>
    <Promulgacion fechaVersion="..." derogado="..."><Texto/></Promulgacion>
  </Norma>

Embedded binary attachments (JPEG/PDF) inside <Texto> are dropped and counted:

  <Texto>
    body before binary
    <aem:ArchivoBinario>
      <aem:Nombre/><aem:Descripcion/><aem:TipoContenido/>
      <aem:CantidadBytes/><aem:DataCodificada/>   <-- base64, skipped
    </aem:ArchivoBinario>
    body after binary                             <-- preserved via .tail
  </Texto>
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from xml.etree import ElementTree as ET

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    Rank,
    Version,
)

NS = "http://www.leychile.cl/esquemas"
AEM_NS = "http://valida.aem.gob.cl"


# Namespaced tag helpers
def _t(name: str) -> str:
    return f"{{{NS}}}{name}"


def _aem(name: str) -> str:
    return f"{{{AEM_NS}}}{name}"


# Strip C0 + C1 control characters (keep \t, \n, \r)
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Collapses any whitespace run (including newlines) to a single space — used
# for YAML-safe title strings.
_WHITESPACE_RUN_RE = re.compile(r"\s+")

# Strips a leading "Artículo N°.- " / "Artículo primero.- " prefix from an
# article body. BCN always embeds the article number in the text itself AS
# WELL as in Metadatos/NombreParte, so we drop it from the body when the
# heading already carries the number.
_ARTICLE_PREFIX_RE = re.compile(
    r"^\s*Artículo\s+[^.\n]+?\.\s*-\s*",
    re.IGNORECASE,
)

# BCN uses "(DEL ART. N)" / "(DEL ART N)" as a disambiguation suffix on
# NombreParte values inside doubly-articulated norms (e.g. the Tax Code lives
# inside Article 1 of DL 830, so every inner article's NombreParte is tagged
# "1 (DEL ART. 1)", "2 (DEL ART 1)", …). The suffix is metadata noise for
# readers so we strip it from the heading.
_DEL_ART_SUFFIX_RE = re.compile(
    r"\s*\(\s*DEL\s+ART\.?\s*\d+\s*\)\s*$",
    re.IGNORECASE,
)

# Margin-annotation detection: a content line followed by 6+ spaces and a
# layout artifact from the Diario Oficial right-column references.
# Covers law-citation tokens (LEY, CPR, D.O., D.L., D.F.L., D.S., Art),
# bare "1°"/"N°"/"Nº" continuations, the word "único", numeric dates,
# and the disposición-transitoria reform-reference vocabulary
# ("DISPOSICION", "TRANSITORIA", "PRIMERA"…"VIGÉSIMA"…) that BCN uses to
# tag amendments to transitory provisions in the right-margin column.
_ORDINAL_WORD = (
    r"PRIMERA|SEGUNDA|TERCERA|CUARTA|QUINTA|SEXTA|S[ÉE]PTIMA|OCTAVA|"
    r"NOVENA|D[ÉE]CIMA|UND[ÉE]CIMA|DUOD[ÉE]CIMA|"
    r"VIG[ÉE]SIMA|TRIG[ÉE]SIMA|CUADRAG[ÉE]SIMA|QUINCUAG[ÉE]SIMA|"
    r"SEXAG[ÉE]SIMA|SEPTUAG[ÉE]SIMA|OCTOG[ÉE]SIMA|NONAG[ÉE]SIMA|CENT[ÉE]SIMA"
)
_MARGIN_TOKEN_RE = re.compile(
    r"(?:CPR\b|\bLEY\b|\bL\.\s*\d|D\.O\.|D\.L\.|D\.F\.L\.|D\.S\.|"
    r"\bArt\.?\b|Nº|N°|\bún ico\b|\búnico\b|\d+°|\d{2}\.\d{2}\.\d{4}|"
    r"\bDISPOSICI[ÓO]N(?:ES)?\b|\bTRANSITORI[OA][SA]?\.?\b|"
    rf"\b(?:{_ORDINAL_WORD})\b)"
)
_MARGIN_SPLIT_RE = re.compile(r"^(.+?)\s{6,}(.+)$")
# Pure continuation of a margin annotation on its own line (no main content).
# Each pattern matches when the WHOLE stripped line is annotation noise.
_CONTINUATION_RE = re.compile(
    r"^(?:"
    r"\d+°(?:\s*[NnLlAaDd][°ºoa]?)*|"  # "1°", "1° N°", "2° N°"
    r"N°|Nº|único|"
    r"L(?:EY)?\b\s*N?[°º]?\s*\d|"
    r"\d{2}\.\d{2}\.\d{4}|D\.O\.|"
    r"Art\.?\s*\d?|"
    r"D\.L\.|D\.F\.L\.|D\.S\.|CPR\b|"
    r"DISPOSICI[ÓO]N(?:ES)?\.?|"
    rf"TRANSITORI[OA][SA]?\.?|(?:{_ORDINAL_WORD})"
    r")"
    r"\s*$"
)


def _parse_date(raw: str) -> date | None:
    """Parse a YYYY-MM-DD BCN date string. Returns None on failure."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _normalize_text(text: str) -> str:
    """UTF-8 hygiene: strip C0/C1 controls and replace NBSP with regular space.

    Called on every text fragment before it is handed back to the caller.
    """
    text = _CTRL_RE.sub("", text)
    text = text.replace("\u00a0", " ")
    return text


def _collapse_title(text: str) -> str:
    """Collapse all whitespace in a title string to single spaces.

    BCN serves some TituloNorma values with hard line breaks for PDF layout
    (e.g. "DECLARA NORMA OFICIAL\nQUE INDICA..."). Those newlines break YAML
    frontmatter, so we flatten titles to a single line at the parser boundary.
    """
    return _WHITESPACE_RUN_RE.sub(" ", _normalize_text(text)).strip()


def _ascii_fold(text: str) -> str:
    """Lossy ASCII fold for accent-insensitive comparisons."""
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).upper()


def _strip_leading_title(body: str, title: str) -> str:
    """Drop the law's title echo from the encabezado preamble.

    BCN repeats the official title verbatim near the top of every <Encabezado>
    block for PDF layout. The H1 already carries the title from the
    frontmatter, so the duplicate is pure noise. The echo is sometimes the
    very first line ("FIJA EL TEXTO REFUNDIDO...") and sometimes preceded by
    the law's official number ("LEY NÚM. 21.180\n\nTRANSFORMACIÓN DIGITAL
    DEL ESTADO"). We split the encabezado into blank-line chunks and drop any
    of the first ~5 chunks that, after ASCII folding, equals the title.
    """
    if not title or not body:
        return body
    target = _WHITESPACE_RUN_RE.sub(" ", _ascii_fold(title)).strip()
    if not target:
        return body

    chunks = re.split(r"\n\s*\n", body)
    head_window = min(len(chunks), 5)
    out_chunks: list[str] = []
    for i, chunk in enumerate(chunks):
        if i < head_window:
            chunk_norm = _WHITESPACE_RUN_RE.sub(" ", _ascii_fold(chunk)).strip()
            if chunk_norm == target:
                continue
            # Some encabezados (e.g. Decreto 29/1978) collapse the title and
            # all the recitals into a single chunk. Try stripping the title as
            # a prefix of the chunk too.
            if chunk_norm.startswith(target + " "):
                # Locate the same prefix in the original (un-folded) chunk and
                # cut it. We approximate by counting words: walk word boundaries
                # in the original until the folded prefix matches.
                stripped = _strip_title_word_prefix(chunk, target)
                if stripped is not None:
                    out_chunks.append(stripped)
                    continue
        out_chunks.append(chunk)
    return "\n\n".join(out_chunks)


def _strip_title_word_prefix(chunk: str, target_folded: str) -> str | None:
    """Strip the title prefix from a chunk by aligning words.

    We walk the chunk word-by-word and rebuild the ASCII-folded prefix until
    it matches the target. When it matches, the remainder of the chunk (after
    the matched words and an optional separator) is returned. If the chunk
    drifts off the target, return None so the caller leaves the chunk alone.
    """
    target_words = target_folded.split()
    chunk_words = chunk.split()
    if len(chunk_words) < len(target_words):
        return None
    # Compare word-by-word in the folded form.
    for idx, t_word in enumerate(target_words):
        if _ascii_fold(chunk_words[idx]).strip(",.;:") != t_word:
            return None
    # All target words matched. Return the remainder, joined back with single
    # spaces (the original chunk's whitespace was lost when we tokenized).
    remainder = " ".join(chunk_words[len(target_words) :]).lstrip(",.;: ")
    return remainder or None


def _clean_body_text(text: str) -> str:
    """Strip Diario Oficial layout artifacts from article body text.

    BCN formats reform references as right-column margin annotations separated
    from the legal text by 6+ spaces. These are layout noise, not legal content,
    and must be dropped. Also strips lines that are pure continuations of a
    margin block (e.g. "Nº1 D.O. 16.06.1999" on its own line).
    """
    text = _normalize_text(text)
    cleaned: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        leading = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        # Right-column-only annotation lines: 30+ leading spaces means the
        # left column is empty and the trailing tokens are pure layout noise.
        if leading >= 30 and stripped:
            continue

        # Indented short margin continuations. BCN's right column starts at
        # varying positions (~10 to 60 chars from the left). When the left
        # column wraps off but the right column still has content, the line
        # has a moderate indent (8+) and a SHORT remainder containing a
        # margin token. Drop those — the corresponding legal text is on the
        # previous line.
        if leading >= 8 and stripped and len(stripped) < 50:
            if _MARGIN_TOKEN_RE.search(stripped):
                continue

        match = _MARGIN_SPLIT_RE.match(line)
        if match:
            main_part = match.group(1).rstrip()
            margin_part = match.group(2).strip()
            # Critical: only treat the line as a margin annotation if there is
            # actual content BEFORE the 6+ space gap. Otherwise an indented
            # bullet item like "       1. Rentas brutas..." would be silently
            # dropped because the empty leading whitespace is considered the
            # "main" content and the bullet body is treated as the margin.
            if main_part and _MARGIN_TOKEN_RE.search(margin_part):
                cleaned.append(main_part.strip())
                continue
        if stripped and _CONTINUATION_RE.match(stripped):
            # Whole-line continuation — drop.
            continue
        cleaned.append(stripped)

    # Collapse runs of empty lines (>2 blanks → 1 blank)
    out: list[str] = []
    blank_run = 0
    for line in cleaned:
        if line == "":
            blank_run += 1
            if blank_run > 1:
                continue
        else:
            blank_run = 0
        out.append(line)
    # Trim leading/trailing blanks
    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def _texto_content(texto_el: ET.Element | None) -> str:
    """Read a <Texto> element's content, skipping any aem:ArchivoBinario subtree.

    BCN embeds image attachments as mixed content: text before the binary lives
    in ``texto_el.text``, text after lives in the binary element's ``tail``.
    We join the surrounding text, drop the base64 payload, and leave an
    ``[imagen omitida]`` marker in its place so the reader can tell a figure
    was here — the ``extra.images_dropped`` counter tracks the global count.
    """
    if texto_el is None:
        return ""

    parts: list[str] = []
    if texto_el.text:
        parts.append(texto_el.text)

    for child in texto_el:
        tag = child.tag
        if tag.startswith(f"{{{AEM_NS}}}"):
            parts.append("\n\n[imagen omitida]\n\n")
            if child.tail:
                parts.append(child.tail)
            continue
        # Unexpected foreign child: include its inline text + tail defensively.
        if child.text:
            parts.append(child.text)
        if child.tail:
            parts.append(child.tail)

    return "".join(parts).strip()


def _count_binaries(root: ET.Element) -> int:
    """Count embedded aem:ArchivoBinario nodes anywhere in the tree."""
    return len(root.findall(f".//{_aem('ArchivoBinario')}"))


def _present_text(meta_el: ET.Element | None, field: str) -> str:
    """Read a Metadatos child that uses the `presente="si"` convention.

    BCN wraps NombreParte / TituloParte with ``presente="si"|"no"``. When absent
    we treat the value as empty without raising. Control characters, NBSPs,
    stray whitespace, and the "(DEL ART. N)" disambiguation suffix are all
    normalized away.
    """
    if meta_el is None:
        return ""
    child = meta_el.find(_t(field))
    if child is None:
        return ""
    if child.get("presente") == "no":
        return ""
    # BCN emits "\xa0" as the text when presente="no" is omitted; collapsing
    # whitespace handles that and any genuine line breaks inside the value.
    raw = _WHITESPACE_RUN_RE.sub(" ", _normalize_text(child.text or "")).strip()
    # Strip the "(DEL ART. N)" disambiguation suffix for doubly-articulated norms.
    return _DEL_ART_SUFFIX_RE.sub("", raw).strip()


# ── Text Parser ──

# BCN tipoParte → (internal block_type, heading css_class, is_container).
# Containers are heading-only nodes that group children (Libro, Título, Capítulo,
# Párrafo, Sección, Disposición Transitoria group). Their <Texto> body is
# always a redundant echo of the heading and is dropped.
# Leaves (Artículo and per-item Disposición Transitoria) carry the legal text
# in their <Texto> element and the article number in Metadatos/NombreParte.
# Chilean legal hierarchy: Libro > Título > Capítulo > Párrafo/Sección > Artículo
_TIPO_PARTE_MAP: dict[str, tuple[str, str, bool]] = {
    "Libro": ("libro", "titulo_tit", True),
    "Título": ("titulo", "titulo_tit", True),
    "Titulo": ("titulo", "titulo_tit", True),
    "Capítulo": ("capitulo", "capitulo_tit", True),
    "Capitulo": ("capitulo", "capitulo_tit", True),
    "Párrafo": ("parrafo_group", "seccion", True),
    "Parrafo": ("parrafo_group", "seccion", True),
    "Sección": ("seccion", "seccion", True),
    "Seccion": ("seccion", "seccion", True),
    # "Otros" is BCN's catch-all container for sub-groupings that don't fit
    # the named hierarchy (e.g. "Presidente de la República", "Ministros de
    # Estado" inside Capítulo IV of the Constitution). They have a TituloParte
    # and act as section dividers — render as headings.
    "Otros": ("otros", "seccion", True),
    # "Doble Articulado" is a BCN grouping wrapper used for norms that contain
    # an embedded code inside a single outer article (e.g. DL 830 → Código
    # Tributario lives inside outer "Artículo 1"). It carries no user-facing
    # heading or body, only a structural marker.
    "Doble Articulado": ("doble_articulado", "seccion", True),
    "Artículo": ("articulo", "articulo", False),
    "Articulo": ("articulo", "articulo", False),
    "Disposición Transitoria": ("transitoria", "articulo", False),
    "Disposicion Transitoria": ("transitoria", "articulo", False),
}

# Heading levels by recursion depth — used for container headings to keep
# child levels strictly deeper than parent levels, even when BCN nests
# Capítulo > Título (e.g. Constitución Capítulo XV).
_DEPTH_TO_HEADING_CSS: tuple[str, ...] = (
    "titulo_tit",  # depth 1 → ##
    "capitulo_tit",  # depth 2 → ###
    "seccion",  # depth 3 → ####
    "seccion",  # depth 4+ → #### (cap)
)


def _heading_css_for_depth(depth: int) -> str:
    """Return the heading CSS class for a container at a given recursion depth."""
    idx = max(0, min(depth - 1, len(_DEPTH_TO_HEADING_CSS) - 1))
    return _DEPTH_TO_HEADING_CSS[idx]


def _body_is_title_echo(body: str, titulo: str) -> bool:
    """Return True when an EstructuraFuncional body is just its title repeated.

    Used to decide whether a leaf node with no NombreParte but a present
    TituloParte should be reclassified as a container. Many BCN section
    headers (e.g. "DISPOSICIONES TRANSITORIAS") have a <Texto> that is
    literally the same string as the TituloParte plus whitespace; promoting
    them to containers avoids printing the heading twice.

    Real article bodies are much longer than their titles. We compare the
    ASCII-folded body length to the title length: if the body is at most
    twice the title length AND its folded text starts with the folded title
    or is a substring of it, it's an echo.
    """
    if not body:
        return True
    body_norm = _WHITESPACE_RUN_RE.sub(" ", _ascii_fold(body)).strip()
    title_norm = _WHITESPACE_RUN_RE.sub(" ", _ascii_fold(titulo)).strip()
    if not title_norm:
        return False
    if len(body_norm) > max(80, len(title_norm) * 2):
        return False
    return title_norm in body_norm or body_norm in title_norm


def _container_heading(tipo_parte: str, titulo: str) -> str:
    """Build the heading for a grouping container.

    When BCN provides a TituloParte we use it verbatim (it already includes
    the roman numeral, e.g. "Capítulo I BASES DE LA INSTITUCIONALIDAD").
    Otherwise we fall back to the tipoParte label.
    """
    return titulo.strip() or tipo_parte


def _article_heading(tipo_parte: str, nombre: str) -> str:
    """Build the heading for an article-level leaf ("Artículo 1", "Artículo primero")."""
    nombre = nombre.strip()
    if tipo_parte in ("Disposición Transitoria", "Disposicion Transitoria"):
        prefix = "Disposición Transitoria"
    else:
        prefix = "Artículo"
    if not nombre:
        return prefix
    # BCN sometimes serves the number as "1" or "primero"; both are valid.
    return f"{prefix} {nombre}"


def _strip_article_prefix(body: str, tipo_parte: str) -> str:
    """Drop a redundant leading "Artículo X°.- " from an article body.

    BCN embeds the article number both in Metadatos/NombreParte AND as the
    first token of the body text. The heading carries the number, so we strip
    it from the body to avoid duplication like:

        ##### Artículo 1
        Artículo 1°.- Las personas nacen libres...

    For Disposición Transitoria leaves, BCN uses "Artículo primero.-" in the
    body so the same pattern applies.
    """
    if not body or tipo_parte not in (
        "Artículo",
        "Articulo",
        "Disposición Transitoria",
        "Disposicion Transitoria",
    ):
        return body
    # Drop a surrounding double-quote that BCN sometimes adds when the whole
    # article is quoted (amending inserts). Keep the closing quote in place
    # if present so the body reads naturally.
    stripped = body.lstrip()
    leading_quote = ""
    if stripped.startswith('"'):
        leading_quote = '"'
        stripped = stripped[1:]
    match = _ARTICLE_PREFIX_RE.match(stripped)
    if match:
        stripped = stripped[match.end() :]
    return (leading_quote + stripped).lstrip()


def _body_paragraphs(body: str) -> list[Paragraph]:
    """Split a cleaned body text into flowing paragraphs for rendering.

    BCN serves <Texto> as PDF-layout text with hard line breaks every ~60
    characters. Those breaks are visual only — in markdown they produce ugly
    narrow columns. We reflow each "natural" paragraph (separated by blank
    lines in the source) into a single flowing line. The markdown renderer
    then wraps to the viewer's width.
    """
    if not body:
        return []
    out: list[Paragraph] = []
    for chunk in re.split(r"\n\s*\n", body):
        chunk = chunk.strip()
        if not chunk:
            continue
        # Reflow: collapse all whitespace (incl. newlines) inside the chunk.
        reflowed = " ".join(chunk.split())
        if reflowed:
            out.append(Paragraph(css_class="parrafo", text=reflowed))
    return out


class CLTextParser(TextParser):
    """Parses BCN XML into Block/Version/Paragraph objects."""

    def parse_text(self, data: bytes) -> list[Any]:
        root = ET.fromstring(data)
        norma_id = root.get("normaId", "unknown")

        # Extract the official title once so we can drop its echo from the
        # encabezado body. We re-read it here (instead of relying on the
        # metadata parser) so the text parser stays self-contained.
        official_title = ""
        meta_root = root.find(_t("Metadatos"))
        if meta_root is not None:
            titulo_el = meta_root.find(_t("TituloNorma"))
            if titulo_el is not None and titulo_el.text:
                official_title = _collapse_title(titulo_el.text)

        blocks: list[Block] = []

        # 1. Encabezado (preamble / recitals)
        encab = root.find(_t("Encabezado"))
        if encab is not None:
            enc_block = self._build_encabezado_block(encab, norma_id, official_title)
            if enc_block is not None:
                blocks.append(enc_block)

        # 2. EstructurasFuncionales (recursive body)
        efs = root.find(_t("EstructurasFuncionales"))
        if efs is not None:
            blocks.extend(self._parse_estructuras(efs, norma_id))

        # 3. Anexos (optional)
        anexos_el = root.find(_t("Anexos"))
        if anexos_el is not None:
            for anexo in anexos_el.findall(_t("Anexo")):
                anexo_block = self._build_anexo_block(anexo, norma_id)
                if anexo_block is not None:
                    blocks.append(anexo_block)

        # 4. Promulgacion (closing formula + signatories)
        prom = root.find(_t("Promulgacion"))
        if prom is not None:
            prom_block = self._build_promulgacion_block(prom, norma_id)
            if prom_block is not None:
                blocks.append(prom_block)

        # 5. Fallback: BCN occasionally publishes "shell" entries with a
        #    TituloNorma but an empty <Encabezado>/<Texto> and no body
        #    (e.g. CL-271766, CL-3903). Emit a placeholder block so the norm
        #    still makes it to the catalog with its metadata instead of being
        #    dropped as an orphan.
        if not blocks:
            fecha = _parse_date(root.get("fechaVersion", "")) or date(1900, 1, 1)
            placeholder_text = (
                "[Texto no disponible en la fuente BCN. "
                "Consulte la ficha original en el enlace `source` del frontmatter.]"
            )
            blocks.append(
                Block(
                    id=f"{norma_id}-placeholder",
                    block_type="placeholder",
                    title=official_title or "Sin texto",
                    versions=(
                        Version(
                            norm_id=norma_id,
                            publication_date=fecha,
                            effective_date=fecha,
                            paragraphs=(Paragraph(css_class="parrafo", text=placeholder_text),),
                        ),
                    ),
                )
            )

        return blocks

    # --- builders ---

    def _build_encabezado_block(
        self,
        element: ET.Element,
        norma_id: str,
        title: str = "",
    ) -> Block | None:
        """Emit the preamble as plain paragraphs with no heading.

        Adding a synthetic "# Encabezado" header would clutter the markdown —
        the recitals usually start with the official law number and title on
        their own lines, which already reads as the document header.

        BCN repeats the law's title at the top of the encabezado for the PDF
        layout (e.g. "FIJA EL TEXTO REFUNDIDO..." appears once as the H1 from
        frontmatter and once again at the start of the encabezado paragraph).
        We drop the leading title echo so it does not show up twice.
        """
        body = _clean_body_text(_texto_content(element.find(_t("Texto"))))
        if not body:
            return None
        if title:
            body = _strip_leading_title(body, title)
        fecha = _parse_date(element.get("fechaVersion", "")) or date(1900, 1, 1)
        paragraphs = _body_paragraphs(body)
        if not paragraphs:
            return None
        version = Version(
            norm_id=norma_id,
            publication_date=fecha,
            effective_date=fecha,
            paragraphs=tuple(paragraphs),
        )
        return Block(
            id=f"{norma_id}-encabezado",
            block_type="encabezado",
            title="Encabezado",
            versions=(version,),
        )

    def _build_anexo_block(self, anexo_el: ET.Element, norma_id: str) -> Block | None:
        id_parte = anexo_el.get("idParte") or f"{norma_id}-anexo"
        fecha = _parse_date(anexo_el.get("fechaVersion", "")) or date(1900, 1, 1)
        meta_el = anexo_el.find(_t("Metadatos"))
        titulo = ""
        if meta_el is not None:
            titulo_el = meta_el.find(_t("Titulo"))
            if titulo_el is not None and titulo_el.text:
                titulo = _normalize_text(titulo_el.text).strip()

        body = _clean_body_text(_texto_content(anexo_el.find(_t("Texto"))))
        heading = titulo or "Anexo"

        paragraphs: list[Paragraph] = [
            Paragraph(css_class="titulo_tit", text=heading),
        ]
        paragraphs.extend(_body_paragraphs(body))
        if len(paragraphs) == 1:
            # Annex with no body text — skip to avoid empty headings.
            return None

        version = Version(
            norm_id=norma_id,
            publication_date=fecha,
            effective_date=fecha,
            paragraphs=tuple(paragraphs),
        )
        return Block(
            id=f"anexo-{id_parte}",
            block_type="anexo",
            title=heading,
            versions=(version,),
        )

    def _build_promulgacion_block(self, prom_el: ET.Element, norma_id: str) -> Block | None:
        body = _clean_body_text(_texto_content(prom_el.find(_t("Texto"))))
        if not body:
            return None
        fecha = _parse_date(prom_el.get("fechaVersion", "")) or date(1900, 1, 1)
        # Promulgacion carries the signatories. We split on blank lines and
        # emit each chunk as its own firma_rey paragraph so the markdown
        # renderer produces a valid **bold** span per chunk (the renderer's
        # wrapper breaks if we hand it a multi-line block with empty lines).
        paragraphs: list[Paragraph] = []
        for chunk in re.split(r"\n\s*\n", body):
            chunk = " ".join(chunk.split())
            if chunk:
                paragraphs.append(Paragraph(css_class="firma_rey", text=chunk))
        if not paragraphs:
            return None
        version = Version(
            norm_id=norma_id,
            publication_date=fecha,
            effective_date=fecha,
            paragraphs=tuple(paragraphs),
        )
        return Block(
            id=f"{norma_id}-promulgacion",
            block_type="promulgacion",
            title="Promulgación",
            versions=(version,),
        )

    def _parse_estructuras(self, parent: ET.Element, norma_id: str, depth: int = 1) -> list[Block]:
        """Recursively walk nested EstructurasFuncionales.

        Containers (Libro/Título/Capítulo/Párrafo/Sección/Otros) become
        heading-only blocks — their <Texto> is a redundant echo and is dropped.
        Heading levels are chosen by recursion depth so a child container can
        never sit at a higher level than its parent (Constitución Capítulo XV
        nests Título inside Capítulo, which would otherwise produce
        ## inside ###).

        Leaves (Artículo + per-item Disposición Transitoria) become a heading
        + body block with the "Artículo X°.- " prefix stripped. When BCN omits
        NombreParte but provides a TituloParte that looks like a heading
        ("DISPOSICIONES TRANSITORIAS"), the leaf is reclassified as a
        container so its body (which is just the heading echo) is dropped.
        """
        blocks: list[Block] = []

        for ef in parent.findall(_t("EstructuraFuncional")):
            tipo_parte = ef.get("tipoParte", "")
            id_parte = ef.get("idParte", "")
            derogado = ef.get("derogado", "no derogado")
            fecha = _parse_date(ef.get("fechaVersion", "")) or date(1900, 1, 1)

            meta_el = ef.find(_t("Metadatos"))
            nombre = _present_text(meta_el, "NombreParte")
            titulo = _present_text(meta_el, "TituloParte")

            block_type, _default_css, is_container = _TIPO_PARTE_MAP.get(
                tipo_parte, ("otro", "articulo", False)
            )

            # Reclassification: an Artículo / Disposición Transitoria with
            # no NombreParte but a TituloParte CAN be a section header (e.g.
            # "DISPOSICIONES TRANSITORIAS") whose <Texto> is just an echo of
            # the title. We only promote to container when the body is also
            # an echo — otherwise the leaf carries real legal content that
            # would be silently lost (e.g. Constitución QUINCUAGÉSIMA PRIMERA
            # has TituloParte="DISPOSICIÓN TRANSITORIA QUINCUAGÉSIMA PRIMERA
            # TRANSITORIO" but its body has 400+ chars of legal text).
            if not is_container and not nombre and titulo:
                preview_body = _clean_body_text(_texto_content(ef.find(_t("Texto"))))
                if _body_is_title_echo(preview_body, titulo):
                    is_container = True
                    block_type = f"{block_type}_group"

            paragraphs: list[Paragraph] = []

            if is_container:
                heading_css = _heading_css_for_depth(depth)
                # "Doble Articulado" is a pure structural wrapper — skip its
                # heading; the children carry all the content.
                if tipo_parte == "Doble Articulado":
                    heading = ""
                else:
                    heading = _container_heading(tipo_parte, titulo)
                if heading:
                    paragraphs.append(Paragraph(css_class=heading_css, text=heading))
            else:
                # Leaf (Artículo / Disposición Transitoria item).
                heading_css = "articulo"
                body = _clean_body_text(_texto_content(ef.find(_t("Texto"))))
                body = _strip_article_prefix(body, tipo_parte)

                # Heading: prefer the explicit number, fall back to the
                # TituloParte when BCN omits NombreParte (some Disposiciones
                # Transitorias only have a TituloParte like "QUINCUAGÉSIMA
                # PRIMERA").
                if nombre:
                    heading = _article_heading(tipo_parte, nombre)
                elif titulo:
                    heading = titulo
                else:
                    heading = ""

                if derogado == "derogado" and not body:
                    if not heading:
                        heading = _article_heading(tipo_parte, nombre or "")
                    paragraphs.append(Paragraph(css_class=heading_css, text=heading))
                    paragraphs.append(Paragraph(css_class="parrafo", text="[derogado]"))
                else:
                    if heading:
                        paragraphs.append(Paragraph(css_class=heading_css, text=heading))
                    paragraphs.extend(_body_paragraphs(body))

            if paragraphs:
                version = Version(
                    norm_id=norma_id,
                    publication_date=fecha,
                    effective_date=fecha,
                    paragraphs=tuple(paragraphs),
                )
                blocks.append(
                    Block(
                        id=id_parte or f"{norma_id}-{block_type}",
                        block_type=block_type,
                        title=heading,
                        versions=(version,),
                    )
                )

            # Recurse into nested EstructurasFuncionales.
            #
            # "Doble Articulado" is a structural wrapper that emits no heading
            # of its own — its children should appear at the same depth as the
            # wrapper article (i.e. as if the wrapper layer didn't exist).
            # Without this, the inner Código Tributario hierarchy gets pushed
            # one level deeper than the wrapping "Artículo 1" of DL 830 and
            # ends up with no top-level headings at all.
            nested = ef.find(_t("EstructurasFuncionales"))
            if nested is not None:
                if tipo_parte == "Doble Articulado":
                    child_depth = max(1, depth - 1)  # transparent layer
                else:
                    child_depth = depth + 1
                blocks.extend(self._parse_estructuras(nested, norma_id, child_depth))

        return blocks


# ── Metadata Parser ──


# BCN "Tipo" → legalize rank. Order matters for the constitution special-case.
RANK_MAP: dict[str, str] = {
    "Ley": "ley",
    "Código": "codigo",
    "Decreto con Fuerza de Ley": "decreto_con_fuerza_de_ley",
    "Decreto Ley": "decreto_ley",
    "Decreto": "decreto",
    "Decreto Supremo": "decreto_supremo",
    "Tratado Internacional": "tratado",
    "Ley Orgánica Constitucional": "ley_organica_constitucional",
    "Ley de Quórum Calificado": "ley_quorum_calificado",
    "Ley Interpretativa": "ley_interpretativa",
    "Resolución": "resolucion",
    "Reglamento": "reglamento",
    "Mensaje": "mensaje",
}

# Known constitutional norm IDs — the official text refundido is stored as a
# Decreto so the generic RANK_MAP would mislabel it.
_CONSTITUCION_NORMAS = {"242302"}


def _collect_extra(root: ET.Element, norm_id: str) -> list[tuple[str, str]]:
    """Build the ordered list of extra (key, value) pairs for frontmatter.

    Every XML-available field the playbook asks us to capture is included
    here with an English snake_case key. Rationale for choices is in
    ``RESEARCH-CHILE.md §7.3``.
    """
    extra: list[tuple[str, str]] = []

    schema_version = root.get("SchemaVersion", "")
    if schema_version:
        extra.append(("bcn_schema_version", schema_version))

    es_tratado = root.get("esTratado", "")
    if es_tratado:
        # Map BCN "tratado"/"no tratado" → yes/no for readability.
        extra.append(("is_treaty", "yes" if es_tratado == "tratado" else "no"))

    ident = root.find(_t("Identificador"))
    if ident is not None:
        promu = ident.get("fechaPromulgacion", "")
        if promu:
            extra.append(("promulgation_date", promu))

        tipo_el = ident.find(f"{_t('TiposNumeros')}/{_t('TipoNumero')}/{_t('Tipo')}")
        if tipo_el is not None and tipo_el.text:
            extra.append(("official_type", tipo_el.text.strip()))
        numero_el = ident.find(f"{_t('TiposNumeros')}/{_t('TipoNumero')}/{_t('Numero')}")
        if numero_el is not None and numero_el.text:
            extra.append(("official_number", numero_el.text.strip()))

    meta = root.find(_t("Metadatos"))
    if meta is not None:
        fuente_el = meta.find(_t("IdentificacionFuente"))
        if fuente_el is not None and fuente_el.text:
            extra.append(("gazette", _normalize_text(fuente_el.text).strip()))
        num_fuente_el = meta.find(_t("NumeroFuente"))
        if num_fuente_el is not None and num_fuente_el.text:
            extra.append(("gazette_issue_number", _normalize_text(num_fuente_el.text).strip()))
        fecha_derog_el = meta.find(_t("FechaDerogacion"))
        if fecha_derog_el is not None and fecha_derog_el.text:
            extra.append(("repeal_date", fecha_derog_el.text.strip()))

        # All NombresUsoComun joined with "|" — short_title is the first one.
        common_names = []
        nuc_container = meta.find(_t("NombresUsoComun"))
        if nuc_container is not None:
            for nuc in nuc_container.findall(_t("NombreUsoComun")):
                if nuc.text:
                    common_names.append(_normalize_text(nuc.text).strip())
        if len(common_names) > 1:
            extra.append(("common_names", " | ".join(common_names)))

    # Structural counters (helpful for later enrichment / reporting)
    images = _count_binaries(root)
    if images:
        extra.append(("images_dropped", str(images)))

    anexos_el = root.find(_t("Anexos"))
    if anexos_el is not None and list(anexos_el):
        extra.append(("has_annex", "yes"))

    parts_repealed = 0
    for ef in root.iter(_t("EstructuraFuncional")):
        if ef.get("derogado") == "derogado":
            parts_repealed += 1
            continue
        meta_ef = ef.find(_t("Metadatos"))
        if meta_ef is not None and meta_ef.find(_t("FechaDerogacion")) is not None:
            parts_repealed += 1
    if parts_repealed:
        extra.append(("parts_repealed", str(parts_repealed)))

    transitory = 0
    for ef in root.iter(_t("EstructuraFuncional")):
        if ef.get("transitorio") == "transitorio":
            transitory += 1
    if transitory:
        extra.append(("transitory_parts", str(transitory)))

    return extra


def _collect_organisms(root: ET.Element) -> str:
    """Join all Organismo entries with '; ' — most norms have exactly one."""
    ident = root.find(_t("Identificador"))
    if ident is None:
        return ""
    orgs_el = ident.find(_t("Organismos"))
    if orgs_el is None:
        return ""
    names: list[str] = []
    for o in orgs_el.findall(_t("Organismo")):
        if o.text:
            names.append(_normalize_text(o.text).strip())
    return "; ".join(n for n in names if n)


def _collect_subjects(root: ET.Element) -> tuple[str, ...]:
    """Collect deduped Materia text from the norm-level Metadatos element only.

    Per-article Materias are noisy (one sampled decreto had every article tagged
    with the same subject). We only index the norm-level block.
    """
    meta = root.find(_t("Metadatos"))
    if meta is None:
        return ()
    materias_el = meta.find(_t("Materias"))
    if materias_el is None:
        return ()
    seen: list[str] = []
    for m in materias_el.findall(_t("Materia")):
        if m.text:
            cleaned = _normalize_text(m.text).strip()
            if cleaned and cleaned not in seen:
                seen.append(cleaned)
    return tuple(seen)


def _resolve_rank(tipo: str, norm_id: str, nombres_uso_comun: list[str]) -> str:
    """Resolve the CL rank for a norm, with a constitution special case."""
    if norm_id in _CONSTITUCION_NORMAS:
        return "constitucion"
    for nombre in nombres_uso_comun:
        if "CONSTITUCION POLITICA DE LA REPUBLICA" in nombre.upper():
            return "constitucion"
    return RANK_MAP.get(tipo, "otro")


class CLMetadataParser(MetadataParser):
    """Parses BCN XML metadata into NormMetadata."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        root = ET.fromstring(data)

        # ── identification ──
        ident = root.find(_t("Identificador"))
        fecha_pub = _parse_date(ident.get("fechaPublicacion", "") if ident is not None else "")
        fecha_prom = _parse_date(ident.get("fechaPromulgacion", "") if ident is not None else "")
        publication_date = fecha_pub or fecha_prom or date(1900, 1, 1)

        tipo = ""
        numero = ""
        if ident is not None:
            tipo_el = ident.find(f"{_t('TiposNumeros')}/{_t('TipoNumero')}/{_t('Tipo')}")
            if tipo_el is not None and tipo_el.text:
                tipo = tipo_el.text.strip()
            numero_el = ident.find(f"{_t('TiposNumeros')}/{_t('TipoNumero')}/{_t('Numero')}")
            if numero_el is not None and numero_el.text:
                numero = numero_el.text.strip()

        # ── title + common names ──
        # BCN sometimes embeds hard line breaks inside TituloNorma for PDF
        # layout ("DECLARA NORMA OFICIAL\nQUE INDICA..."). We collapse any
        # whitespace run so the frontmatter stays YAML-safe.
        meta = root.find(_t("Metadatos"))
        titulo = ""
        if meta is not None:
            titulo_el = meta.find(_t("TituloNorma"))
            if titulo_el is not None and titulo_el.text:
                titulo = _collapse_title(titulo_el.text)

        common_names: list[str] = []
        if meta is not None:
            nuc_container = meta.find(_t("NombresUsoComun"))
            if nuc_container is not None:
                for nuc in nuc_container.findall(_t("NombreUsoComun")):
                    if nuc.text:
                        cleaned = _collapse_title(nuc.text)
                        if cleaned:
                            common_names.append(cleaned)

        short_title = common_names[0] if common_names else titulo
        if not titulo:
            titulo = f"{tipo} {numero}".strip() or f"Norma {norm_id}"
        if not short_title:
            short_title = titulo

        # ── status ──
        derogado = root.get("derogado", "no derogado")
        fecha_derog_el = meta.find(_t("FechaDerogacion")) if meta is not None else None
        has_norm_repeal_date = fecha_derog_el is not None and bool(fecha_derog_el.text)
        if derogado == "derogado" or has_norm_repeal_date:
            status = NormStatus.REPEALED
        else:
            status = NormStatus.IN_FORCE

        # ── rank ──
        rank_str = _resolve_rank(tipo, norm_id, common_names)

        # ── aux ──
        department = _collect_organisms(root)
        subjects = _collect_subjects(root)
        source_url = f"https://www.bcn.cl/leychile/navegar?idNorma={norm_id}"
        last_modified = _parse_date(root.get("fechaVersion", ""))

        extra = _collect_extra(root, norm_id)

        return NormMetadata(
            title=titulo,
            short_title=short_title,
            identifier=f"CL-{norm_id}",
            country="cl",
            rank=Rank(rank_str),
            publication_date=publication_date,
            status=status,
            department=department,
            source=source_url,
            jurisdiction=None,  # Chile is a unitary state.
            last_modified=last_modified,
            pdf_url=None,
            subjects=subjects,
            summary="",
            extra=tuple(extra),
        )
