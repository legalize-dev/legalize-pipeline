"""Parsers for Portuguese legislation from the Diário da República.

Two input shapes, one output model:

**Consolidated fragments** (surface A) arrive already structured. Every fragment
declares its own ``TipoFragmentoId``, so the heading level is read, never guessed —
the old parser reconstructed a 3-level approximation from line regexes and left
52.9 % of the corpus with no heading at all.

**As-published HTML** (surface B) is a flat run of ``<p class="paragraph-*">`` with
tables, images and cross-reference links. The class says *whether* a line is a
heading; the text pattern says which level.
"""

from __future__ import annotations

import html
import json
import logging
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

from lxml import html as lxml_html

from legalize.fetcher._tables import render_table
from legalize.fetcher._text import clean, collapse_inline_whitespace
from legalize.fetcher.base import MetadataParser, TextParser
from legalize.fetcher.pt.client import CONSOLIDATED, PUBLISHED, unpack
from legalize.fetcher.pt.identifier import build_identifier, jurisdiction_from_eli
from legalize.models import Block, NormMetadata, NormStatus, Paragraph, Rank, Reform, Version

logger = logging.getLogger(__name__)

DRE_BASE = "https://diariodarepublica.pt"

# lxml's encoding autodetection falls back to Latin-1 on large pages and produces
# mojibake; force UTF-8 once, module-wide (see memory feedback_engine_gotchas).
_HTML_PARSER = lxml_html.HTMLParser(encoding="utf-8")

# TipoFragmentoId -> (name, css_class). Taken from DRE's own static entity
# TipoFragmento (19 values, read out of the app manifest — see
# docs/pt-metadata-inventory.md §6), cross-checked against 20,843 fragments in 222
# diplomas (docs/pt-formatting-inventory.md §1). The manifest is authoritative: id 10
# is *subcapítulo*, which the frequency sweep had guessed as "Tabela" from three
# fragments in one diploma.
#
# Four levels collapse because Markdown has six heading levels, `#` is spent on the
# law title, and the Portuguese hierarchy has ten tiers. The heading *text* keeps the
# Portuguese type word, so a reader loses depth, not content.
FRAGMENT_TYPES: dict[int, tuple[str, str]] = {
    4: ("Parte", "parte_num"),
    12: ("Livro", "libro_num"),
    13: ("Título", "titulo_tit"),
    5: ("Subtítulo", "titulo_tit"),  # collapses with Título
    14: ("Anexo", "anexo_num"),
    1: ("Capítulo", "capitulo_tit"),
    10: ("Subcapítulo", "capitulo_tit"),  # collapses with Capítulo
    8: ("Secção", "seccion_tit"),
    3: ("Subsecção", "subseccion_tit"),
    9: ("Divisão", "subseccion_tit"),  # collapses
    6: ("Subdivisão", "subseccion_tit"),  # collapses
    11: ("Artigo", "articulo"),
    2: ("Base", "articulo"),  # leis de bases article-equivalent
    7: ("Assinatura", "firma"),
    15: ("Diploma", "parrafo"),  # the preamble; body text, no heading
    # Sub-article levels. They did not occur in a 222-diploma sweep of the
    # consolidated corpus, but they are in DRE's vocabulary, so render them as body
    # text rather than inventing a seventh heading level.
    16: ("Número", "parrafo"),
    17: ("Alínea", "parrafo"),
    18: ("Subalínea", "parrafo"),
    0: ("", "parrafo"),
}
# Types that emit a heading paragraph. 7 is the signature block, 15 the preamble,
# and 0/16/17/18 are body text.
_HEADING_TYPES = frozenset(FRAGMENT_TYPES) - {0, 7, 15, 16, 17, 18}

# DRE's own marker for content it did not digitise. Present in 27,954 files of the
# old repo as a bare string. Nothing recovers it: 0/42 consolidated twins and 1/71
# as-published records have the content, and 64.7 % of the PDFs are scans with no
# text layer (docs/pt-formatting-inventory.md §3). Link the PDF instead of lying.
_VER_DOC_ORIGINAL = re.compile(r"\(\s*ver\s+documento\s+original\s*\)", re.IGNORECASE)

# DRE publishes subject descriptors as numeric ids in eli:is_about and their labels
# only through the AnaliseJuridica thesaurus (docs/pt-metadata-inventory.md §3).
# Build the map once with scripts/pt_build_thesaurus.py and inject it before a
# reparse; without it `subjects` stays empty rather than shipping opaque numbers.
_THESAURUS: dict[str, str] = {}


def set_thesaurus(mapping: dict[str, str]) -> None:
    """Install the descriptor id -> Portuguese label map."""
    _THESAURUS.clear()
    _THESAURUS.update({str(k): v for k, v in (mapping or {}).items() if v})


_RANK_FROM_ELI = {
    "lei": "lei",
    "lei-constitucional": "lei-constitucional",
    "leiorg": "lei-organica",
    "dec-lei": "decreto-lei",
    "dec": "decreto",
    "decregul": "decreto-regulamentar",
    "declegreg": "decreto-legislativo-regional",
    "decregulreg": "decreto-regulamentar-regional",
    "port": "portaria",
    "resol": "resolucao",
    "resolconsmin": "resolucao-conselho-ministros",
    "resolassrep": "resolucao-assembleia-republica",
    "despnorm": "despacho-normativo",
    "decpresrep": "decreto-presidente-republica",
    "declrectif": "declaracao-rectificacao",
    "declretif": "declaracao-retificacao",
    "actconst": "acordao-tribunal-constitucional",
    "acstj": "acordao-supremo-tribunal-justica",
    "rgtassrep": "regimento-assembleia-republica",
}

# DRE's Vigencia -> NormStatus. The old parser collapsed everything to a boolean and
# marked 99.89 % of the corpus in_force, including 13,798 acts from the 1960s.
# DRE's complete TipoVigencia vocabulary (static entity, 6 values, no sixth hiding
# in the corpus): 0 NULL · 1 Vigência Condicionada · 2 Omisso · 3 Vigente ·
# 4 Não Vigente · 5 Caducado. Surface B exposes it as the screaming-snake string.
_STATUS = {
    "VIGENTE": NormStatus.IN_FORCE,
    "NAO_VIGENTE": NormStatus.REPEALED,
    # "revoked, but without prejudice to article N" — the law is partly alive.
    "VIGENCIA_CONDICIONADA": NormStatus.PARTIALLY_REPEALED,
    "CADUCADO": NormStatus.EXPIRED,
    "OMISSO": NormStatus.IN_FORCE,
}


def _parse_date(value: str | None) -> date | None:
    text = (value or "").strip()[:10]
    if not text or text.startswith("1900-01-01"):
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _cut(text: str, limit: int) -> str:
    """Truncate on a word boundary, never mid-word."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"


# ─────────────────────────────────────────────────────────────── HTML → paragraphs


def _inline(el: Any, pdf_url: str = "") -> str:
    """Flatten an element to text, pre-wrapping the inline markup Markdown needs.

    The CSS→Markdown map is paragraph-level, so links, superscripts and emphasis
    have to be baked into the string here.
    """
    parts: list[str] = []

    def walk(node: Any) -> None:
        tag = str(getattr(node, "tag", "")).lower()
        if tag == "style":
            return
        if tag == "a":
            href = (node.get("href") or "").strip()
            label = " ".join(node.itertext()).strip()
            if label:
                # DRE writes site-relative hrefs both ways: "/dr/detalhe/…" and the
                # bare "eurlex.asp?ano=2009&id=309L0049" its headings use, which
                # 301s to the EUR-Lex CELEX record. Either is a dead link in a
                # Markdown file, so both get resolved against the site root.
                if href and not href.lower().startswith(("http:", "https:", "mailto:")):
                    href = urljoin(DRE_BASE + "/", href)
                parts.append(f"[{label}]({href})" if href else label)
            if node.tail:
                parts.append(node.tail)
            return
        if tag in ("sup", "sub"):
            inner = " ".join(node.itertext()).strip()
            if inner:
                parts.append(f"<{tag}>{inner}</{tag}>")
            if node.tail:
                parts.append(node.tail)
            return
        if tag == "br":
            parts.append("  \n")
            if node.tail:
                parts.append(node.tail)
            return
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
        if node is not el and node.tail:
            parts.append(node.tail)

    walk(el)
    text = collapse_inline_whitespace(clean("".join(parts)))
    # Consecutive <br> would leave a blank line inside one paragraph, and
    # storage.py joins paragraphs with "\n\n" and splits on it — a blank line
    # here desyncs the parallel css_classes list on the way back in.
    text = re.sub(r"(?:[ \t]*\n){2,}", "  \n", text).strip()
    return _link_ver_documento(text, pdf_url)


def _rich_text(value: str, pdf_url: str = "") -> str:
    """Flatten a DRE field that may carry inline markup.

    ``Epigrafe`` and ``Tituo`` are documented as plain strings but hold anchors for
    every EU act a heading cites — "Transposição da Directiva n.º <a href=…>2009/49/
    CE</a>" reached the Markdown as literal tag soup. Same path as the body text, so
    a link in a heading becomes a link and an entity becomes its character.
    """
    if not value:
        return ""
    return _inline(lxml_html.fromstring(f"<div>{clean(value)}</div>", parser=_HTML_PARSER), pdf_url)


def _link_ver_documento(text: str, pdf_url: str) -> str:
    """Turn DRE's dead "(ver documento original)" string into a working link."""
    if not pdf_url or not _VER_DOC_ORIGINAL.search(text):
        return text
    return _VER_DOC_ORIGINAL.sub(f"([ver documento original]({pdf_url}))", text)


def _cell_text(el: Any) -> str:
    return _inline(el).replace("|", "\\|")


def _is_image_wrapper(table_el: Any) -> bool:
    """A one-cell table whose only content is an image.

    109 of 129 surface-B "tables" and 113 of 168 surface-A ones are these wrappers.
    Rendering them as pipe tables is the single biggest source of wrong output.
    """
    cells = table_el.xpath(".//*[local-name()='td' or local-name()='th']")
    if len(cells) > 1:
        return False
    images = table_el.xpath(".//*[local-name()='img']")
    if not images:
        return False
    return not "".join(table_el.itertext()).strip()


def _images(el: Any) -> list[str]:
    out = []
    for img in el.xpath(".//*[local-name()='img']"):
        src = (img.get("src") or "").strip()
        if not src:
            continue
        if src.startswith("/"):
            src = DRE_BASE + src
        alt = (img.get("alt") or "").strip()
        # DRE's placeholder alt text says nothing; an empty alt reads better.
        if alt.lower().startswith("a imagem não se encontra"):
            alt = ""
        out.append(f"![{alt}]({src})")
    return out


# surface-B paragraph classes, measured over 128 diplomas
# (docs/pt-formatting-inventory.md §2.3)
_HEADING_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^\s*PARTE\b", re.IGNORECASE), "parte_num"),
    (re.compile(r"^\s*LIVRO\b", re.IGNORECASE), "libro_num"),
    (re.compile(r"^\s*T[ÍI]TULO\b", re.IGNORECASE), "titulo_tit"),
    (re.compile(r"^\s*SUBT[ÍI]TULO\b", re.IGNORECASE), "titulo_tit"),
    (re.compile(r"^\s*ANEXO\b", re.IGNORECASE), "anexo_num"),
    (re.compile(r"^\s*AP[ÊE]NDICE\b", re.IGNORECASE), "apendice_num"),
    (re.compile(r"^\s*CAP[ÍI]TULO\b", re.IGNORECASE), "capitulo_tit"),
    (re.compile(r"^\s*SEC[ÇC][ÃA]O\b", re.IGNORECASE), "seccion_tit"),
    (re.compile(r"^\s*SUBSEC[ÇC][ÃA]O\b", re.IGNORECASE), "subseccion_tit"),
    (re.compile(r"^\s*DIVIS[ÃA]O\b", re.IGNORECASE), "subseccion_tit"),
    (re.compile(r"^\s*SUBDIVIS[ÃA]O\b", re.IGNORECASE), "subseccion_tit"),
    # "Artigo 1.º", "Art. 2.º", "Artigo único", "Base I" — the abbreviated form is
    # what the old parser missed in 20,332 files (18.5 % of the corpus).
    (
        re.compile(r"^\s*(?:Artigo|Art\.)\s+(?:\d+\.?[ºo]?(?:-[A-Z]+)?|[úu]nico)\b", re.IGNORECASE),
        "articulo",
    ),
    (re.compile(r"^\s*Base\s+[IVXLC]+\b"), "articulo"),
)

_SIGNATURE = re.compile(
    r"^\s*(?:O|A)\s+(?:Presidente|Primeiro-Ministro|Ministr[oa]|Secretári[oa]|"
    r"Vice-Primeiro|Chefe)\b|^\s*Promulgad[oa]\b|^\s*Referendad[oa]\b|"
    r"^\s*Assinad[oa]\b|^\s*Publique-se\b",
    re.IGNORECASE,
)
_INTERNAL_ID = re.compile(r"^\s*\d{6,12}\s*$")


def _classify_published(text: str, css: str, previous: str) -> str | None:
    """Map one surface-B paragraph to a css_class, or None to drop it."""
    if not text:
        return None
    # The renderer already emits "# {title}"; keeping DRE's own title paragraph is
    # what put the title twice in 98.1 % of the old files.
    if "paragraph-title" in css:
        return None
    # p.paragraph-italic-right is always DRE's internal content id, never a
    # signature — this is the stray "114808797" that leaked into 7,573 old files.
    if "paragraph-italic-right" in css or _INTERNAL_ID.match(text):
        return None
    if "paragraph-center" in css or "bold-center" in css:
        for pattern, klass in _HEADING_PATTERNS:
            if pattern.match(text):
                return klass
        return "parrafo"
    for pattern, klass in _HEADING_PATTERNS:
        if pattern.match(text):
            return klass
    if _SIGNATURE.match(text):
        return "firma"
    return "parrafo"


def _parse_published_html(raw: str, pdf_url: str = "") -> list[Paragraph]:
    """Turn one as-published document's HTML into ordered Paragraphs."""
    text = clean(raw)
    if not text.strip():
        return []
    root = lxml_html.fromstring(f"<div>{text}</div>", parser=_HTML_PARSER)
    for style in root.xpath(".//*[local-name()='style']"):
        style.getparent().remove(style)

    out: list[Paragraph] = []
    previous = ""
    pending_heading: Paragraph | None = None

    def flush() -> None:
        nonlocal pending_heading
        if pending_heading is not None:
            out.append(pending_heading)
            pending_heading = None

    for el in root.xpath(".//*[local-name()='p' or local-name()='table' or local-name()='img']"):
        tag = str(el.tag).lower()
        if tag == "table":
            if _is_image_wrapper(el):
                flush()
                for ref in _images(el):
                    out.append(Paragraph(css_class="image", text=ref))
                continue
            flush()
            rendered = render_table(el, _cell_text)
            if rendered.strip():
                out.append(Paragraph(css_class="table", text=rendered))
            continue
        if tag == "img":
            if el.getparent() is not None and el.getparent().xpath(
                "ancestor-or-self::*[local-name()='table']"
            ):
                continue
            flush()
            for ref in _images(el):
                out.append(Paragraph(css_class="image", text=ref))
            continue
        if el.xpath("ancestor::*[local-name()='table']"):
            continue

        body = _inline(el, pdf_url)
        css = el.get("class") or ""
        klass = _classify_published(body, css, previous)
        if klass is None:
            continue
        if pending_heading is not None and "bold-center" in css:
            # epígrafe: fold it into the heading we are holding
            out.append(
                Paragraph(
                    css_class=pending_heading.css_class, text=f"{pending_heading.text} — {body}"
                )
            )
            pending_heading = None
            previous = klass
            continue
        flush()
        if klass in {c for _, c in _HEADING_PATTERNS}:
            pending_heading = Paragraph(css_class=klass, text=body)
        else:
            out.append(Paragraph(css_class=klass, text=body))
        previous = klass

    flush()
    return out


# ────────────────────────────────────────────────────── consolidated fragments


def _fragment_paragraphs(entry: dict, pdf_url: str) -> tuple[str, list[Paragraph]]:
    """One consolidated fragment -> (heading text, paragraphs)."""
    version = entry.get("version") or {}
    type_id = version.get("TipoFragmentoId")
    name, css = FRAGMENT_TYPES.get(type_id, ("", "parrafo"))

    # Tituo already carries the type word plus Identificacao, and only the bare
    # label when OmitTipo is set. Take it verbatim.
    heading = _rich_text(version.get("Tituo") or (entry.get("frag") or {}).get("Name") or "")
    epigrafe = _rich_text(version.get("Epigrafe") or "")
    if heading and epigrafe:
        heading = f"{heading} — {epigrafe}"

    paragraphs: list[Paragraph] = []
    if type_id in _HEADING_TYPES and heading:
        paragraphs.append(Paragraph(css_class=css, text=heading))

    body = version.get("Texto") or ""
    if body:
        if "<" in body:
            paragraphs.extend(_parse_published_html(body, pdf_url))
        else:
            # No tag in the body, but DRE still escapes its angle brackets there:
            # "lotes &lt;15 t" shipped verbatim. Unescape here and not before the
            # branch above, or "&lt;15 t" would look like a tag to the HTML parser.
            for line in clean(body).split("\n"):
                line = collapse_inline_whitespace(html.unescape(line)).strip()
                if line:
                    paragraphs.append(
                        Paragraph(
                            css_class="firma" if type_id == 7 else "parrafo",
                            text=_link_ver_documento(line, pdf_url),
                        )
                    )

    for note in entry.get("nota") or []:
        text = _inline(lxml_html.fromstring(f"<div>{clean(note)}</div>", parser=_HTML_PARSER))
        if text:
            paragraphs.append(Paragraph(css_class="nota_pie", text=text))

    return heading or name, paragraphs


# ─────────────────────────────────────────────────────────────────── the parsers


class DRETextParser(TextParser):
    """Parses DRE text into versioned Blocks."""

    def parse_text(self, data: bytes) -> list[Any]:
        """Single-version parse. Real history comes from ``parse_suvestine``."""
        raw = clean(data)
        if not raw.strip() or raw.strip() == "{}":
            return []
        paragraphs = _parse_published_html(raw)
        if not paragraphs:
            return []
        return [
            Block(
                id="texto",
                block_type="texto",
                title="",
                versions=(
                    Version(
                        norm_id="",
                        publication_date=date(1900, 1, 1),
                        effective_date=date(1900, 1, 1),
                        paragraphs=tuple(paragraphs),
                    ),
                ),
            )
        ]

    def parse_suvestine(
        self, suvestine_data: bytes, norm_id: str
    ) -> tuple[list[Block], list[Reform]]:
        """Turn the version blob into merged Blocks and one Reform per version.

        Blocks are keyed by the consolidated fragment id so the same article across
        snapshots collapses into one Block with one Version per snapshot. A snapshot
        whose rendered text is identical to the previous one produces no Reform:
        ``commit_all_fast`` streams every Reform to git without checking, so the
        parser is the only thing standing between us and empty commits.
        """
        if not suvestine_data:
            return [], []
        blob = json.loads(suvestine_data.decode("utf-8"))
        versions = blob.get("versions") or []
        if not versions:
            return [], []

        if blob.get("surface") == PUBLISHED:
            return self._published_blocks(blob, norm_id)
        return self._consolidated_blocks(blob, norm_id)

    # -- surface B: a published text has exactly one version -----------------

    def _published_blocks(self, blob: dict, norm_id: str) -> tuple[list[Block], list[Reform]]:
        entry = blob["versions"][0]
        when = _parse_date(entry.get("date")) or date(1900, 1, 1)
        pdf_url = blob.get("pdf_url", "")
        paragraphs = _parse_published_html(unpack(entry["html_b64"]), pdf_url)
        if not paragraphs:
            if not pdf_url:
                return [], []
            # DRE never digitised this one — it exists only as a scan. Say so, and
            # link it, rather than dropping the diploma from the corpus.
            paragraphs = [
                Paragraph(
                    css_class="nota_pie",
                    text=(
                        "O texto deste diploma não se encontra disponível em formato "
                        f"eletrónico no Diário da República. [Ver documento original]({pdf_url})"
                    ),
                )
            ]
        version = Version(
            norm_id=norm_id,
            publication_date=when,
            effective_date=when,
            paragraphs=tuple(paragraphs),
        )
        block = Block(id="texto", block_type="texto", title="", versions=(version,))
        return [block], [Reform(date=when, norm_id=norm_id, affected_blocks=())]

    # -- surface A: one snapshot per effective date --------------------------

    def _consolidated_blocks(self, blob: dict, norm_id: str) -> tuple[list[Block], list[Reform]]:
        pdf_url = blob.get("pdf_url", "")
        ordered: list[str] = []
        by_block: dict[str, list[Version]] = {}
        previous_text: dict[str, str] = {}
        reforms: list[Reform] = []

        for entry in blob["versions"]:
            when = _parse_date(entry.get("date"))
            if when is None:
                continue
            fragments = unpack(entry["fragments_b64"])
            amending = entry.get("amending") or {}
            source_id = _reform_source_id(blob, entry, amending)
            changed: list[str] = []

            for item in fragments:
                version_row = item.get("version") or {}
                # Key on FragmentoId, the article's identity across consolidations —
                # not on ConsolidacaoFragmento.Id, which is per-consolidation.
                block_id = str(
                    version_row.get("FragmentoId") or (item.get("frag") or {}).get("Id") or ""
                )
                if not block_id:
                    continue
                title, paragraphs = _fragment_paragraphs(item, pdf_url)
                if not paragraphs:
                    continue
                rendered = "\n".join(p.text for p in paragraphs)
                if previous_text.get(block_id) == rendered:
                    continue
                previous_text[block_id] = rendered
                if block_id not in by_block:
                    by_block[block_id] = []
                    ordered.append(block_id)
                else:
                    changed.append(title)
                by_block[block_id].append(
                    Version(
                        norm_id=source_id,
                        publication_date=when,
                        effective_date=when,
                        paragraphs=tuple(paragraphs),
                    )
                )

            is_first = not reforms
            if not is_first and not changed:
                # Nothing this diploma says actually changed on that date.
                continue
            reforms.append(
                Reform(
                    date=when,
                    norm_id=source_id,
                    affected_blocks=tuple(changed[:40]),
                )
            )

        blocks = [
            Block(
                id=block_id,
                block_type="fragmento",
                title=(
                    by_block[block_id][0].paragraphs[0].text
                    if by_block[block_id][0].paragraphs
                    else ""
                ),
                versions=tuple(sorted(by_block[block_id], key=lambda v: v.publication_date)),
            )
            for block_id in ordered
        ]
        return blocks, reforms


def _reform_source_id(blob: dict, entry: dict, amending: dict) -> str:
    """A stable, unique dedupe key per reform.

    It becomes the ``Source-Id`` trailer and the idempotency key, so it must be
    reproducible across runs — no timestamps, no randomness.
    """
    when = (entry.get("date") or "")[:10]
    if amending.get("legis_id"):
        return f"DRE-{amending['legis_id']}@{when}"
    return f"{blob.get('diploma_frag_id', 'PT')}@{when}"


class DREMetadataParser(MetadataParser):
    """Builds NormMetadata from the client's merged bundle."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        bundle = json.loads(data.decode("utf-8"))
        published: dict = bundle.get("published") or {}
        header: dict = bundle.get("header") or {}
        frag: dict = header.get("DiplomaFrag") or {}
        legis: dict = header.get("DiplomaLegis") or {}
        consolidation: dict = bundle.get("consolidation") or {}

        eli = (frag.get("ELI") or published.get("ELI") or "").strip()
        numero = (legis.get("Numero") or published.get("Numero") or "").strip()
        tipo_slug = bundle.get("tipo", "")
        pub_date = (
            _parse_date(published.get("DataPublicacao"))
            or _parse_date(legis.get("DataPublicacao"))
            or date(1900, 1, 1)
        )

        acronimo = (
            published.get("TipoDiplomaAcronimo")
            or (header.get("TipoDiploma") or {}).get("Acronimo")
            or ""
        ).strip()
        dre_id = str(published.get("Id") or legis.get("Id") or "").strip()
        identifier = build_identifier(eli, numero, tipo_slug, pub_date.year, acronimo, dre_id)
        emissor = (published.get("Emissor") or legis.get("Emissor") or "").strip()
        jurisdiction = jurisdiction_from_eli(eli, numero, emissor)

        # Portuguese diplomas are cited by number; the descriptive text lives in
        # Designacao and Sumario, and the search index only reads title and
        # short_title. See RESEARCH-PT-v2 §12b.
        tipo_display = (published.get("TipoDiploma") or "").strip() or tipo_slug.replace(
            "-", " "
        ).title()
        citation = f"{tipo_display} n.º {numero}" if numero else tipo_display
        designacao = " ".join((frag.get("Designacao") or "").split())
        sumario = " ".join((published.get("Sumario") or legis.get("Sumario") or "").split())
        descriptive = designacao or sumario
        title = f"{citation} — {_cut(descriptive, 120)}" if descriptive else citation
        short_title = _cut(descriptive, 80) or citation

        eli_meta = _parse_eli_rdfa(published.get("ELIMetadataHTML") or "")
        pdf_url = (published.get("URL_PDF") or consolidation.get("URLPDF") or "").strip()

        extra: list[tuple[str, str]] = []

        def add(key: str, value: Any) -> None:
            text = str(value or "").strip()
            if text and text not in ("1900-01-01", "0", "False"):
                extra.append((key, text[:500]))

        add("short_title", short_title)
        add("summary", sumario)
        add("designation", designacao if designacao and designacao != short_title else "")
        add("official_number", numero)
        add("eli", eli)
        add("eli_type", (eli_meta.get("type_document") or "").rsplit("/", 1)[-1])
        add("surface", bundle.get("surface"))
        add("series", published.get("Serie"))
        add("part", published.get("Parte"))
        # Suplemento is 0 % filled even for diplomas that are in one; the only
        # place it appears is the Publicacao string.
        supplement = re.search(r"(\d+\.?[ºo]?\s*Suplemento)", published.get("Publicacao") or "")
        add(
            "supplement", published.get("Suplemento") or (supplement.group(1) if supplement else "")
        )
        add("gazette_reference", published.get("Publicacao"))
        add("gazette_number", (published.get("DiarioRepublica") or {}).get("Numero"))
        add("pages", published.get("Pagina"))
        add("signature_date", published.get("DataAssinatura"))
        add("distribution_date", published.get("DataDistribuicao"))
        add("availability_date", published.get("DataDisponibilizacao"))
        add("issuer_acronym", published.get("EmissorAcronimo") or legis.get("EmissorAcronimo"))
        add("proposing_entity", (published.get("DiplomaLegis") or {}).get("EntidadeProponente"))
        add("descriptors", (published.get("DiplomaExterno") or {}).get("Descritores"))
        add("note", (published.get("Notas") or frag.get("Nota") or ""))
        add("in_force_raw", published.get("Vigencia"))
        add("dre_id", published.get("Id") or legis.get("Id"))
        add("dre_link", (published.get("LinkSitemap") or legis.get("LinkSitemap") or ""))
        if bundle.get("surface") == CONSOLIDATED:
            add("consolidated_at", consolidation.get("DataUltimaConsolidada"))
            add("consolidation_id", consolidation.get("CurrentConsolidacaoId"))
            add("is_initial_version", consolidation.get("IsVersaoInicial"))
            add("has_case_law", consolidation.get("HasJurisprudenciaAssociada"))
            add(
                "consolidated_url",
                f"{DRE_BASE}/dr/legislacao-consolidada/{tipo_slug}/{bundle.get('key', '')}",
            )
        for key in ("in_force", "legal_value", "licence", "publisher", "language"):
            add(f"eli_{key}", eli_meta.get(key))
        if eli_meta.get("subjects"):
            add("subject_ids", " ".join(eli_meta["subjects"]))
        if eli_meta.get("cites"):
            add("cites", "; ".join(eli_meta["cites"][:20]))
            add("cites_count", len(eli_meta["cites"]))
        if eli_meta.get("cites_eu"):
            add("cites_eu", "; ".join(eli_meta["cites_eu"][:20]))

        status = _STATUS.get((published.get("Vigencia") or "").strip().upper(), NormStatus.IN_FORCE)
        rank_token = (eli_meta.get("type_document") or eli or "").rsplit("/", 1)[-1] or acronimo
        rank = _RANK_FROM_ELI.get(rank_token, tipo_slug or "outro")

        return NormMetadata(
            title=title,
            short_title=short_title,
            identifier=identifier,
            country="pt",
            rank=Rank(rank),
            publication_date=pub_date,
            status=status,
            department=emissor or "Diário da República",
            source=eli or f"{DRE_BASE}{published.get('LinkSitemap') or ''}",
            jurisdiction=jurisdiction,
            last_modified=_parse_date(consolidation.get("DataUltimaConsolidada")),
            pdf_url=pdf_url or None,
            subjects=tuple(
                label
                for sid in (eli_meta.get("subjects") or ())
                if (label := _THESAURUS.get(str(sid)))
            ),
            summary=sumario,
            extra=tuple(extra),
        )


_RDFA = re.compile(r'property="eli:([^"]+)"[^>]*?(?:resource="([^"]*)"|content="([^"]*)")')


def _parse_eli_rdfa(markup: str) -> dict[str, Any]:
    """Read the ELI RDFa block DRE ships with every diploma.

    It carries the subject descriptors, the citations to national and EU law, the
    in-force status and the licence — none of which the old parser captured.
    """
    if not markup:
        return {}
    out: dict[str, Any] = {"subjects": [], "cites": [], "cites_eu": []}
    for prop, resource, content in _RDFA.findall(markup):
        value = (resource or content or "").strip()
        if not value:
            continue
        if prop == "is_about":
            out["subjects"].append(value.rsplit("/", 1)[-1])
        elif prop == "cites":
            (out["cites_eu"] if "data.europa.eu" in value else out["cites"]).append(value)
        elif prop in (
            "in_force",
            "legal_value",
            "licence",
            "publisher",
            "language",
            "type_document",
        ):
            out.setdefault(prop, value.rsplit("#", 1)[-1] if "#" in value else value)
    return out
