"""Fedlex parser — Switzerland.

Parses Fedlex Akoma Ntoso 3.0 XML into Block/Version/Paragraph structures
for the generic pipeline.

Two input shapes are handled:

1. Raw ``<akomaNtoso>`` XML — a single consolidation.
2. ``<fedlex-multi-version>`` envelope — many consolidations bundled by the
   client, each wrapped in a ``<version>`` element carrying the
   ``effective-date`` / ``end-date`` attributes.

Metadata lives in the Akoma Ntoso ``<meta>`` block using standard FRBR
elements (``FRBRWork``, ``FRBRExpression``, ``FRBRManifestation``,
``FRBRname``, ``FRBRnumber``, ``FRBRdate``). Fedlex does NOT use the SCL
JOLux embedding that Luxembourg uses — instead, JOLux is the name of the
``FRBRdate`` semantics. The Fedlex namespace
(``xmlns:fedlex="http://fedlex.admin.ch/"``) carries only minor generator
attributes.

Rich content in the body that this parser handles:

- ``<table>`` / ``<tr>`` / ``<td>`` — rendered as Markdown pipe tables with
  rowspan/colspan expansion (same algorithm as ``fetcher/lv/parser.py``).
- ``<blockList>`` / ``<item>`` / ``<num>`` / ``<listIntroduction>`` —
  rendered as Markdown unordered lists; the ``<num>`` carries the
  letter/number marker (``a.``, ``1.``, ``1bis.``), which we keep inline so
  no semantics are lost.
- ``<authorialNote>`` — footnotes. Rendered as inline ``[^n]`` anchors plus
  a ``[^n]: ...`` block at the end of the article. Losing these would mean
  losing legal cross-references, which are core content.
- Inline: ``<b>`` → ``**``, ``<i>`` → ``*``, ``<sup>`` → ``<sup>...</sup>``,
  ``<br/>`` → newline, ``<ref>`` → ``[text](href)``, ``<inline>`` and
  ``<span>`` → passthrough.
- ``<placeholder>`` — Fedlex conversion artefact for elements that could
  not be rendered structurally. We strip the element entirely (its text is
  "[tab]" or similar filler with no semantic value in Markdown).
- ``<img>`` — always dropped (no binary assets in the repo); count tracked
  in ``extra.images_dropped``.
- ``<eol/>`` — soft line-end, skipped silently.

Structural hierarchy walked:
``body → book → part → title → chapter → section → subdivision → level →
article → paragraph → content → p`` plus ``<preface>``, ``<preamble>``,
``<conclusions>``, ``<proviso>``.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any
from xml.etree import ElementTree as ET

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.fetcher.ch.client import eli_url_to_norm_id
from legalize.models import Block, NormMetadata, NormStatus, Paragraph, Rank, Version

logger = logging.getLogger(__name__)

# ─── Namespaces ───
_AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"
_XML_NS = "http://www.w3.org/XML/1998/namespace"

# ─── Cleanup regexes ───
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_WS_RE = re.compile(r"[ \t]+")

# ─── Rank mapping ───
# Fedlex resource-type SKOS label (DE) → internal rank string. The labels
# come from ``jolux:typeDocument`` URIs like
# ``fedlex.data.admin.ch/vocabulary/resource-type/21``. Unknown labels fall
# through to a lowercased, snake_cased version of the label.
_RANK_LABEL_MAP: dict[str, str] = {
    "Bundesverfassung": "bundesverfassung",
    "Bundesgesetz": "bundesgesetz",
    "Bundesbeschluss": "bundesbeschluss",
    "Bundesbeschluss, der dem fakultativen Referendum untersteht": "bundesbeschluss_fak_referendum",
    "Bundesbeschluss, der dem obligatorischen Referendum untersteht": "bundesbeschluss_obl_referendum",
    "Verordnung": "verordnung",
    "Verordnung der Bundesversammlung": "verordnung_bundesversammlung",
    "Verordnung des Bundesrates": "verordnung_bundesrat",
    "Verordnung des Departements": "verordnung_departement",
    "Verordnung eines Amtes": "verordnung_amt",
    "Kantonsverfassung": "kantonsverfassung",
    "Internationaler Rechtstext bilateral": "bilateral_treaty",
    "Internationaler Rechtstext multilateral": "multilateral_treaty",
    "Reglement": "reglement",
    "Beschluss": "beschluss",
    "Richtlinie": "richtlinie",
    "Weisung": "weisung",
    "Botschaft": "botschaft",
    "Notiz": "notiz",
}

# Fallback rank when the type URI is missing — infers from the title. The
# title is the only source of rank info in the XML manifestation (Fedlex
# keeps ``jolux:typeDocument`` in SPARQL, not in the Akoma Ntoso body).
# Swiss federal codes (ZGB, OR, StGB, ...) are formally ``Bundesgesetz``
# instances; the Zivilgesetzbuch / Strafgesetzbuch patterns are there so
# the Codes land under the same rank as ordinary federal laws.
_TITLE_RANK_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^Bundesverfassung\b", re.IGNORECASE), "bundesverfassung"),
    (re.compile(r"\bKantonsverfassung\b", re.IGNORECASE), "kantonsverfassung"),
    (
        re.compile(
            r"^(?:Schweizerisches\s+)?(?:Zivil|Straf|Militärstraf)gesetzbuch\b",
            re.IGNORECASE,
        ),
        "bundesgesetz",
    ),
    (
        re.compile(
            r"\b(?:Zivil|Straf|Jugendstraf)prozessordnung\b",
            re.IGNORECASE,
        ),
        "bundesgesetz",
    ),
    (re.compile(r"^Obligationenrecht\b", re.IGNORECASE), "bundesgesetz"),
    (
        re.compile(r"^Bundesbeschluss\b", re.IGNORECASE),
        "bundesbeschluss",
    ),
    (re.compile(r"^Bundesgesetz\b", re.IGNORECASE), "bundesgesetz"),
    (re.compile(r"^Verordnung\b", re.IGNORECASE), "verordnung"),
    (re.compile(r"^Reglement\b", re.IGNORECASE), "reglement"),
    # Generic fallback — any title ending in "gesetz" is a federal law.
    (re.compile(r"gesetz\b", re.IGNORECASE), "bundesgesetz"),
]

_DEFAULT_RANK = "andere"


def _tag(el: ET.Element) -> str:
    """Strip namespace from an element tag."""
    return el.tag.split("}")[-1] if "}" in el.tag else el.tag


def _akn(tag: str) -> str:
    return f"{{{_AKN_NS}}}{tag}"


def _clean_ws(text: str) -> str:
    """Strip control chars, NBSP → space, collapse internal runs of spaces.

    Also removes trailing spaces immediately before an internal newline
    (otherwise paragraphs that cross ``<br/>`` keep a stray space at the
    end of each intermediate line, which fails the engine's hygiene check
    ``grep -n ' $' file``).
    """
    if not text:
        return ""
    text = _CONTROL_RE.sub("", text)
    text = text.replace("\xa0", " ")
    text = _WS_RE.sub(" ", text)
    text = re.sub(r" +\n", "\n", text)
    return text


def _parse_date(s: str | None) -> date | None:
    """Parse an ISO ``YYYY-MM-DD`` string, returning ``None`` on failure."""
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


# ─────────────────────────────────────────────
# Inline text extraction — walks children, pre-wraps inline formatting.
# Per-version footnote collector is threaded through via ``notes``.
# ─────────────────────────────────────────────


class _NoteCollector:
    """Collects authorialNote bodies so footnote markers can be rendered.

    A fresh instance is created per Version so note numbers are local to
    each point-in-time text and stable across re-renders.
    """

    __slots__ = ("counter", "notes")

    def __init__(self) -> None:
        self.counter = 0
        self.notes: list[tuple[int, str]] = []

    def add(self, body: str) -> int:
        body = body.strip()
        if not body:
            return 0
        self.counter += 1
        self.notes.append((self.counter, body))
        return self.counter


def _extract_inline(el: ET.Element, notes: _NoteCollector | None) -> str:
    """Recursively extract inline text, pre-wrapping formatting as Markdown.

    Handles: ``<b>``, ``<i>``, ``<sup>``, ``<br/>``, ``<ref>``, ``<inline>``,
    ``<span>``, ``<em>``, ``<u>``, ``<eol/>``, ``<placeholder>`` (strip),
    ``<img>`` (drop), ``<authorialNote>`` (emit ``[^n]`` marker), nested
    structure elements (passthrough text only).
    """
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        ctag = _tag(child)

        if ctag == "placeholder":
            # Fedlex conversion artefact — drop the element entirely, keep tail.
            if child.tail:
                parts.append(child.tail)
            continue
        if ctag == "img":
            # Binary assets are never included in the repo.
            if child.tail:
                parts.append(child.tail)
            continue
        if ctag == "eol":
            if child.tail:
                parts.append(child.tail)
            continue
        if ctag == "authorialNote":
            body = _extract_block_text(child, notes).strip()
            if notes is not None:
                n = notes.add(body)
                if n:
                    parts.append(f"[^{n}]")
            elif body:
                parts.append(f"({body})")
            if child.tail:
                parts.append(child.tail)
            continue

        child_text = _extract_inline(child, notes)

        if ctag == "b" and child_text:
            parts.append(f"**{child_text}**")
        elif ctag in ("i", "em") and child_text:
            parts.append(f"*{child_text}*")
        elif ctag == "u" and child_text:
            parts.append(child_text)  # underline has no clean Markdown; keep plain
        elif ctag == "sup" and child_text:
            parts.append(f"<sup>{child_text}</sup>")
        elif ctag == "sub" and child_text:
            parts.append(f"<sub>{child_text}</sub>")
        elif ctag == "br":
            parts.append("\n")
        elif ctag == "ref":
            href = child.get("href", "")
            if child_text.strip() and href:
                parts.append(f"[{child_text}]({href})")
            else:
                parts.append(child_text)
        else:
            # inline, span, num (inline uses), docNumber, docTitle, and any
            # unknown element: pass through the child's text.
            parts.append(child_text)

        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _extract_block_text(el: ET.Element, notes: _NoteCollector | None) -> str:
    """Inline extraction + whitespace normalisation for block content."""
    return _clean_ws(_extract_inline(el, notes))


# ─────────────────────────────────────────────
# Table rendering — Akoma Ntoso uses standard <table>/<tr>/<td>/<th>.
# Handles colspan / rowspan via a 2-D expansion grid.
# ─────────────────────────────────────────────


def _cell_markdown(cell: ET.Element, notes: _NoteCollector | None) -> str:
    """Render a table cell to a single-line Markdown chunk.

    Cells may contain ``<p>``, ``<blockList>``, nested inline formatting,
    even a ``<table>`` in rare schedules. We flatten everything into one
    line; newlines within cells confuse pipe tables. Block separators
    become `` / ``.
    """
    chunks: list[str] = []
    for p in cell.iter():
        ptag = _tag(p)
        if ptag == "p":
            text = _extract_block_text(p, notes).strip()
            if text:
                chunks.append(text)
    if not chunks:
        text = _extract_block_text(cell, notes).strip()
        if text:
            chunks.append(text)
    joined = " / ".join(chunks)
    # Escape pipe characters so they don't break column alignment
    return joined.replace("|", "\\|")


def _table_to_markdown(table_el: ET.Element, notes: _NoteCollector | None) -> str:
    """Convert an Akoma Ntoso ``<table>`` into a Markdown pipe table."""
    raw_rows: list[list[tuple[str, int, int]]] = []
    for row in table_el.iter():
        if _tag(row) != "tr":
            continue
        cells: list[tuple[str, int, int]] = []
        for cell in row:
            if _tag(cell) not in ("td", "th"):
                continue
            text = _cell_markdown(cell, notes)
            try:
                colspan = int(cell.get("colspan") or 1)
            except ValueError:
                colspan = 1
            try:
                rowspan = int(cell.get("rowspan") or 1)
            except ValueError:
                rowspan = 1
            cells.append((text, colspan, rowspan))
        if cells:
            raw_rows.append(cells)

    if not raw_rows:
        return ""

    # Expand spans into a dense grid
    expanded: list[list[str]] = []
    pending: dict[int, tuple[str, int]] = {}
    for row in raw_rows:
        out_row: list[str] = []
        col = 0
        idx = 0
        while idx < len(row) or col in pending:
            if col in pending:
                text, remaining = pending[col]
                out_row.append(text)
                if remaining > 1:
                    pending[col] = (text, remaining - 1)
                else:
                    del pending[col]
                col += 1
                continue
            text, colspan, rowspan = row[idx]
            for _ in range(colspan):
                out_row.append(text)
                if rowspan > 1:
                    pending[col] = (text, rowspan - 1)
                col += 1
            idx += 1
        expanded.append(out_row)

    if not expanded:
        return ""
    max_cols = max(len(r) for r in expanded)
    for r in expanded:
        while len(r) < max_cols:
            r.append("")

    lines = ["| " + " | ".join(expanded[0]) + " |"]
    lines.append("| " + " | ".join("---" for _ in range(max_cols)) + " |")
    for row in expanded[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


# ─────────────────────────────────────────────
# Body walker — emits flat Paragraph objects with generic heading CSS
# classes (h1..h6) plus a few helpers the Markdown renderer understands.
# ─────────────────────────────────────────────


_STRUCT_LEVELS = {
    "book": 2,
    "part": 2,
    "title": 2,
    "chapter": 3,
    "section": 4,
    "subdivision": 5,
    "level": 6,
}


def _heading_text(el: ET.Element, notes: _NoteCollector | None) -> str:
    num = el.find(_akn("num"))
    heading = el.find(_akn("heading"))
    parts: list[str] = []
    if num is not None:
        t = _extract_block_text(num, notes).strip()
        if t:
            parts.append(t)
    if heading is not None:
        t = _extract_block_text(heading, notes).strip()
        if t:
            parts.append(t)
    return " ".join(parts).strip()


def _article_heading(el: ET.Element, notes: _NoteCollector | None) -> str:
    """Article heading: ``<num>``, optional ``<heading>``."""
    return _heading_text(el, notes)


def _walk_list(
    el: ET.Element,
    paragraphs: list[Paragraph],
    notes: _NoteCollector | None,
    indent: int = 0,
) -> None:
    """Render a ``<blockList>`` as Markdown unordered list.

    Akoma Ntoso shape:

        <blockList>
          <listIntroduction>...</listIntroduction>   (optional)
          <item>
            <num>a.</num>
            <p>...</p>
          </item>
          ...
        </blockList>
    """
    intro = el.find(_akn("listIntroduction"))
    if intro is not None:
        intro_text = _extract_block_text(intro, notes).strip()
        if intro_text:
            paragraphs.append(Paragraph(css_class="abs", text=intro_text))

    prefix = "  " * indent
    for item in el:
        if _tag(item) != "item":
            continue
        num_el = item.find(_akn("num"))
        marker = _extract_block_text(num_el, notes).strip() if num_el is not None else ""
        # Collect all block children of the item (p, blockList)
        chunks: list[str] = []
        for child in item:
            ctag = _tag(child)
            if ctag == "num":
                continue
            if ctag == "p":
                text = _extract_block_text(child, notes).strip()
                if text:
                    chunks.append(text)
            elif ctag == "blockList":
                # Emit the current item first, then recurse for the nested list
                if chunks:
                    marker_sep = f"{marker} " if marker else ""
                    paragraphs.append(
                        Paragraph(
                            css_class="list_item",
                            text=f"{prefix}- {marker_sep}{' '.join(chunks)}",
                        )
                    )
                    chunks = []
                    marker = ""
                _walk_list(child, paragraphs, notes, indent=indent + 1)
            elif ctag == "authorialNote":
                body = _extract_block_text(child, notes).strip()
                if notes is not None and body:
                    n = notes.add(body)
                    if n:
                        chunks.append(f"[^{n}]")
            else:
                text = _extract_block_text(child, notes).strip()
                if text:
                    chunks.append(text)
        if chunks or marker:
            marker_sep = f"{marker} " if marker else ""
            paragraphs.append(
                Paragraph(
                    css_class="list_item",
                    text=f"{prefix}- {marker_sep}{' '.join(chunks)}".rstrip(),
                )
            )


def _walk_metadata_section(
    el: ET.Element,
    paragraphs: list[Paragraph],
    notes: _NoteCollector,
    css_class: str,
) -> None:
    """Walk ``<preamble>`` / ``<conclusions>``, skipping footnote subtrees.

    Using a plain ``el.iter(_akn("p"))`` here would descend into the ``<p>``
    children of each ``<authorialNote>`` and emit the note body as a
    free-floating preamble paragraph alongside the ``[^n]`` marker that
    ``_extract_inline`` already placed. The notes also get rendered again
    from the ``_NoteCollector`` at the end of the article — triple-emission.

    We recurse manually, shallow-copying the walk but pruning at
    ``authorialNote`` nodes: inline handling owns those.
    """
    tag = _tag(el)
    if tag == "authorialNote":
        return
    if tag == "p":
        text = _extract_block_text(el, notes).strip()
        if text:
            paragraphs.append(Paragraph(css_class=css_class, text=text))
        return
    for child in el:
        _walk_metadata_section(child, paragraphs, notes, css_class)


def _walk(
    el: ET.Element,
    paragraphs: list[Paragraph],
    notes: _NoteCollector,
    depth: int = 0,
) -> None:
    """Recursive Akoma Ntoso body walker."""
    tag = _tag(el)

    # Structural headings (book → level)
    if tag in _STRUCT_LEVELS:
        level = _STRUCT_LEVELS[tag]
        heading = _heading_text(el, notes)
        if heading:
            paragraphs.append(Paragraph(css_class=f"h{level}", text=heading))
        for child in el:
            if _tag(child) in ("num", "heading"):
                continue
            _walk(child, paragraphs, notes, depth + 1)
        return

    if tag == "article":
        heading = _article_heading(el, notes)
        if heading:
            paragraphs.append(Paragraph(css_class="h5", text=heading))
        for child in el:
            if _tag(child) in ("num", "heading"):
                continue
            _walk(child, paragraphs, notes, depth + 1)
        return

    if tag == "paragraph":
        num_el = el.find(_akn("num"))
        num_text = ""
        if num_el is not None:
            num_text = _extract_block_text(num_el, notes).strip()
        # Collect all sub-paragraphs of this <paragraph>; prepend num to the
        # first non-empty one so we don't drop the numbering.
        buffer: list[Paragraph] = []
        for child in el:
            ctag = _tag(child)
            if ctag == "num":
                continue
            _walk(child, buffer, notes, depth)
        if num_text and buffer:
            first = buffer[0]
            buffer[0] = Paragraph(
                css_class=first.css_class,
                text=f"<sup>{num_text}</sup> {first.text}",
            )
        elif num_text:
            buffer.append(Paragraph(css_class="abs", text=f"<sup>{num_text}</sup>"))
        paragraphs.extend(buffer)
        return

    if tag in ("content", "intro", "wrapUp", "alinea", "interstitial", "proviso"):
        for child in el:
            _walk(child, paragraphs, notes, depth)
        return

    if tag == "p":
        text = _extract_block_text(el, notes).strip()
        if text:
            paragraphs.append(Paragraph(css_class="abs", text=text))
        return

    if tag == "blockList":
        _walk_list(el, paragraphs, notes, indent=0)
        return

    if tag == "table":
        md = _table_to_markdown(el, notes)
        if md:
            paragraphs.append(Paragraph(css_class="table", text=md))
        return

    if tag == "img":
        # Counted centrally in parse_text via a separate scan; nothing here.
        return

    if tag in ("preface",):
        # docNumber + docTitle already captured as metadata.title. Skip.
        return

    if tag == "preamble":
        _walk_metadata_section(el, paragraphs, notes, css_class="preamble")
        return

    if tag == "conclusions":
        _walk_metadata_section(el, paragraphs, notes, css_class="signature")
        return

    if tag == "quotedStructure" or tag == "embeddedStructure":
        text = _extract_block_text(el, notes).strip()
        if text:
            quoted = "\n".join(f"> {line}" for line in text.splitlines())
            paragraphs.append(Paragraph(css_class="quote", text=quoted))
        return

    # Akoma Ntoso schema has a handful of analysis / metadata wrappers we
    # don't want in the rendered body.
    if tag in (
        "references",
        "meta",
        "identification",
        "lifecycle",
        "analysis",
        "temporalData",
        "classification",
        "notes",
    ):
        return

    # Default: recurse into children
    for child in el:
        _walk(child, paragraphs, notes, depth)


def _append_footnotes(paragraphs: list[Paragraph], notes: _NoteCollector) -> None:
    """Render collected footnotes as a Markdown ``[^n]: ...`` block."""
    if not notes.notes:
        return
    paragraphs.append(Paragraph(css_class="h6", text="Fussnoten"))
    for n, body in notes.notes:
        paragraphs.append(Paragraph(css_class="abs", text=f"[^{n}]: {body}"))


def _count_images(act: ET.Element) -> int:
    return sum(1 for _ in act.iter(_akn("img")))


# ─────────────────────────────────────────────
# TextParser
# ─────────────────────────────────────────────


class FedlexTextParser(TextParser):
    """Parse Fedlex Akoma Ntoso XML into Block/Version/Paragraph."""

    def parse_text(self, data: bytes) -> list[Any]:
        xml = data.decode("utf-8", errors="replace")
        xml = _CONTROL_RE.sub("", xml)
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            logger.warning("Parse error: %s (data len=%d)", exc, len(xml))
            return []

        if _tag(root) == "fedlex-multi-version":
            versions = []
            norm_id = root.get("norm-id", "")
            for vel in root:
                if _tag(vel) != "version":
                    continue
                effective = _parse_date(vel.get("effective-date"))
                pub = _parse_date(vel.get("publication-date")) or effective
                fmt = vel.get("format", "xml")

                if fmt == "pdf":
                    version = self._parse_pdf_inline(
                        vel,
                        norm_id=norm_id,
                        publication_date=pub,
                        effective_date=effective,
                    )
                else:
                    akn = vel.find(_akn("akomaNtoso"))
                    if akn is None:
                        akn = vel.find("akomaNtoso")
                    if akn is None:
                        continue
                    version = self._parse_single(akn, norm_id=norm_id, effective=effective)

                if version is not None:
                    versions.append(version)
            if not versions:
                return []
            return [Block(id="main", block_type="content", title="", versions=tuple(versions))]

        if _tag(root) == "akomaNtoso":
            version = self._parse_single(root, norm_id="", effective=None)
            if version is None:
                return []
            return [Block(id="main", block_type="content", title="", versions=(version,))]

        logger.warning("Unexpected root element: %s", _tag(root))
        return []

    def _parse_single(
        self,
        akn_root: ET.Element,
        norm_id: str,
        effective: date | None,
    ) -> Version | None:
        act = akn_root.find(_akn("act"))
        if act is None:
            act = akn_root.find("act")
        if act is None:
            return None

        meta = act.find(_akn("meta"))
        pub_date: date | None = None
        eff_date: date | None = effective
        if meta is not None:
            for d in meta.iter(_akn("FRBRdate")):
                name = d.get("name", "")
                val = _parse_date(d.get("date"))
                if val is None:
                    continue
                if name == "jolux:dateDocument" and pub_date is None:
                    pub_date = val
                elif name == "jolux:dateApplicability" and eff_date is None:
                    eff_date = val
            if not norm_id:
                frbr_work_this = meta.find(
                    f"{_akn('identification')}/{_akn('FRBRWork')}/{_akn('FRBRthis')}"
                )
                if frbr_work_this is not None:
                    val = frbr_work_this.get("value", "")
                    # Strip trailing "/main-text" used by Fedlex's FRBRthis
                    for suffix in ("/main-text", "/main"):
                        if val.endswith(suffix):
                            val = val[: -len(suffix)]
                    # Strip a trailing version segment (YYYYMMDD) to get the CCA
                    parts = val.rstrip("/").split("/")
                    if parts and parts[-1].isdigit() and len(parts[-1]) == 8:
                        val = "/".join(parts[:-1])
                    norm_id = eli_url_to_norm_id(val)

        if pub_date is None:
            pub_date = eff_date or date(1900, 1, 1)
        if eff_date is None:
            eff_date = pub_date

        notes = _NoteCollector()
        paragraphs: list[Paragraph] = []

        preamble = act.find(_akn("preamble"))
        if preamble is not None:
            _walk(preamble, paragraphs, notes)

        body = act.find(_akn("body"))
        if body is not None:
            _walk(body, paragraphs, notes)

        conclusions = act.find(_akn("conclusions"))
        if conclusions is not None:
            _walk(conclusions, paragraphs, notes)

        _append_footnotes(paragraphs, notes)

        if not paragraphs:
            return None

        return Version(
            norm_id=norm_id,
            publication_date=pub_date,
            effective_date=eff_date,
            paragraphs=tuple(paragraphs),
        )

    def _parse_pdf_inline(
        self,
        version_el: ET.Element,
        norm_id: str,
        publication_date: date | None,
        effective_date: date | None,
    ) -> Version | None:
        """Decode a base64-wrapped PDF version and parse it.

        The client bundles PDF manifestations inside ``<pdf-base64>`` so
        the envelope stays valid XML. We decode the bytes and hand them
        to ``parser_pdf.parse_pdf_version`` which produces the same
        ``Block/Version/Paragraph`` shape the XML parser emits.
        """
        import base64

        # Locate the base64 payload.
        pdf_node = version_el.find("pdf-base64")
        if pdf_node is None:
            logger.warning("PDF version for %s missing <pdf-base64>", norm_id)
            return None
        encoded = (pdf_node.text or "").strip()
        if not encoded:
            return None
        try:
            pdf_bytes = base64.b64decode(encoded)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Invalid base64 PDF payload for %s: %s", norm_id, exc)
            return None

        eff = effective_date or date(1900, 1, 1)
        pub = publication_date or eff

        # Delayed import — parser_pdf pulls in pdfplumber which is
        # heavier than the XML path.
        from legalize.fetcher.ch.parser_pdf import parse_pdf_version

        return parse_pdf_version(
            pdf_bytes,
            norm_id=norm_id,
            publication_date=pub,
            effective_date=eff,
        )


# ─────────────────────────────────────────────
# MetadataParser
# ─────────────────────────────────────────────


def _first_frbr_name(meta: ET.Element, lang: str) -> tuple[str, str]:
    """Return ``(title, short_title)`` for a given language, or ``("", "")``."""
    lang_attr = f"{{{_XML_NS}}}lang"
    for name in meta.iter(_akn("FRBRname")):
        if name.get(lang_attr) == lang:
            return name.get("value", ""), name.get("shortForm", "")
    return "", ""


def _first_frbr_date(meta: ET.Element, name: str) -> date | None:
    for d in meta.iter(_akn("FRBRdate")):
        if d.get("name") == name:
            return _parse_date(d.get("date"))
    return None


def _first_frbr_number(meta: ET.Element) -> str:
    num = meta.find(f"{_akn('identification')}/{_akn('FRBRWork')}/{_akn('FRBRnumber')}")
    return num.get("value", "").strip() if num is not None else ""


def _docnumber_from_preface(act: ET.Element) -> str:
    """Fallback SR-number extraction from ``<preface>/<docNumber>``.

    ``FRBRnumber`` is sometimes empty in the manifestation (e.g. the BVVG
    ordinary law ``cc/2024/620``) even though the top-of-document printed
    label is ``311.6``. The Fedlex HTML viewer shows the preface's
    ``<docNumber>`` as the authoritative shelfmark, so we use it as a
    fallback whenever ``FRBRnumber`` is blank.
    """
    preface = act.find(_akn("preface"))
    if preface is None:
        return ""
    # <docNumber> is typically nested inside a <p>; use descendant search.
    num = preface.find(f".//{_akn('docNumber')}")
    if num is None:
        return ""
    text = "".join(num.itertext()).strip()
    # Guard against non-numeric / multi-paragraph docNumbers (rare).
    return _clean_ws(text).strip()


def _rank_from_title(title: str) -> str:
    for pattern, rank in _TITLE_RANK_PATTERNS:
        if pattern.search(title):
            return rank
    return _DEFAULT_RANK


def _titles_by_lang(meta: ET.Element) -> dict[str, str]:
    lang_attr = f"{{{_XML_NS}}}lang"
    out: dict[str, str] = {}
    for name in meta.iter(_akn("FRBRname")):
        lang = name.get(lang_attr, "")
        value = name.get("value", "")
        if lang and value and lang not in out:
            out[lang] = value
    return out


def _short_titles_by_lang(meta: ET.Element) -> dict[str, str]:
    lang_attr = f"{{{_XML_NS}}}lang"
    out: dict[str, str] = {}
    for name in meta.iter(_akn("FRBRname")):
        lang = name.get(lang_attr, "")
        short = name.get("shortForm", "")
        if lang and short and lang not in out:
            out[lang] = short
    return out


def _count_total_images(root: ET.Element) -> int:
    return sum(1 for _ in root.iter(_akn("img")))


class FedlexMetadataParser(MetadataParser):
    """Parse Fedlex Akoma Ntoso XML metadata into ``NormMetadata``.

    Fedlex keeps FRBR metadata in the standard Akoma Ntoso ``<meta>`` block.
    We extract from the LATEST version inside a multi-version envelope so
    that ``publication_date`` always reflects the current state's dates
    (matters for ``status`` derivations added later).
    """

    def __init__(self, language: str = "de") -> None:
        self._language = language

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        xml = data.decode("utf-8", errors="replace")
        xml = _CONTROL_RE.sub("", xml)
        root = ET.fromstring(xml)

        # Track history_from (earliest version date) and images across all versions
        history_from: date | None = None
        total_images = 0

        if _tag(root) == "fedlex-multi-version":
            envelope_norm_id = root.get("norm-id", "")
            version_els = [v for v in root if _tag(v) == "version"]
            for vel in version_els:
                d = _parse_date(vel.get("effective-date"))
                if d and (history_from is None or d < history_from):
                    history_from = d
            # Use the LATEST version for the canonical title/status
            if not version_els:
                raise ValueError(f"Empty multi-version envelope for {norm_id}")
            latest = version_els[-1]
            akn = latest.find(_akn("akomaNtoso"))
            if akn is None:
                akn = latest.find("akomaNtoso")
            if akn is None:
                raise ValueError(f"No akomaNtoso inside envelope for {norm_id}")
            total_images = sum(_count_total_images(v) for v in version_els)
            if not norm_id:
                norm_id = envelope_norm_id
            root_for_meta = akn
        else:
            root_for_meta = root

        act = root_for_meta.find(_akn("act"))
        if act is None:
            act = root_for_meta.find("act")
        if act is None:
            raise ValueError(f"No <act> element in metadata for {norm_id}")
        meta = act.find(_akn("meta"))
        if meta is None:
            raise ValueError(f"No <meta> element in metadata for {norm_id}")
        if not total_images:
            total_images = _count_total_images(root_for_meta)

        # ── Titles ────────────────────────────────────────────
        title_de, short_de = _first_frbr_name(meta, self._language)
        if not title_de:
            # Any language is better than none
            fallback_titles = _titles_by_lang(meta)
            title_de = next(iter(fallback_titles.values()), f"[Untitled: {norm_id}]")
        title_de = _clean_ws(title_de)
        short_de = _clean_ws(short_de)

        titles = _titles_by_lang(meta)
        shorts = _short_titles_by_lang(meta)

        # ── Dates ────────────────────────────────────────────
        pub_date = (
            _first_frbr_date(meta, "jolux:dateDocument")
            or _first_frbr_date(meta, "jolux:dateEntryInForce")
            or _first_frbr_date(meta, "jolux:dateApplicability")
            or date(1900, 1, 1)
        )
        entry_in_force = _first_frbr_date(meta, "jolux:dateEntryInForce")
        latest_applicability = _first_frbr_date(meta, "jolux:dateApplicability")

        # ── SR number and country ────────────────────────────
        sr_number = _first_frbr_number(meta) or _docnumber_from_preface(act)
        country = "ch"
        frbr_country = meta.find(
            f"{_akn('identification')}/{_akn('FRBRWork')}/{_akn('FRBRcountry')}"
        )
        if frbr_country is not None:
            country = frbr_country.get("value", "ch").lower()

        # ── Rank ─────────────────────────────────────────────
        # No direct typeDocument in the XML manifestation — we only have the
        # title (rich enough for the main cases) and the TLCOrganization
        # showAs. Use title heuristics.
        rank_key = _rank_from_title(title_de)
        rank = Rank(rank_key)

        # ── Department (publisher) ───────────────────────────
        department = ""
        for org in meta.iter(_akn("TLCOrganization")):
            show = org.get("showAs", "").strip()
            if show:
                department = show
                break

        # ── Source URL ───────────────────────────────────────
        # FRBRuri points to the Expression (version-specific); strip the
        # date segment to get the canonical CCA URL.
        source = ""
        for uri in meta.iter(_akn("FRBRuri")):
            val = uri.get("value", "")
            if val and "/eli/cc/" in val:
                parts = val.rstrip("/").split("/")
                # Remove trailing: language code, version date, manifestation segment
                trimmed = [p for p in parts]
                # Drop single-language code suffix if present
                if trimmed and len(trimmed[-1]) == 2 and trimmed[-1].isalpha():
                    trimmed = trimmed[:-1]
                # Drop YYYYMMDD suffix if present
                if trimmed and len(trimmed[-1]) == 8 and trimmed[-1].isdigit():
                    trimmed = trimmed[:-1]
                source = "/".join(trimmed)
                break
        if not source:
            source = f"https://fedlex.data.admin.ch/eli/{norm_id.replace('-', '/', 2)}"

        # ── Extra ────────────────────────────────────────────
        extra: list[tuple[str, str]] = []
        if short_de:
            extra.append(("short_title", short_de))
        if sr_number:
            extra.append(("sr_number", sr_number))
        if entry_in_force:
            extra.append(("entry_into_force", entry_in_force.isoformat()))
        if latest_applicability:
            extra.append(("applicability_date", latest_applicability.isoformat()))
        if history_from:
            extra.append(("history_from", history_from.isoformat()))
        if titles:
            for lang, value in titles.items():
                if lang != self._language:
                    extra.append((f"title_{lang}", _clean_ws(value).strip()))
        if shorts:
            for lang, value in shorts.items():
                if lang != self._language:
                    extra.append((f"short_title_{lang}", _clean_ws(value).strip()))
        if total_images:
            extra.append(("images_dropped", str(total_images)))

        authoritative = meta.find(
            f"{_akn('identification')}/{_akn('FRBRWork')}/{_akn('FRBRauthoritative')}"
        )
        if authoritative is not None:
            extra.append(("authoritative", authoritative.get("value", "").lower()))

        fedlex_gen = None
        for fmt in meta.iter(_akn("FRBRformat")):
            fedlex_gen = fmt.get("{http://fedlex.admin.ch/}generator")
            if fedlex_gen:
                extra.append(("xml_generator", fedlex_gen))
                break

        return NormMetadata(
            title=title_de,
            short_title=short_de,
            identifier=norm_id,
            country=country,
            rank=rank,
            publication_date=pub_date,
            status=NormStatus.IN_FORCE,
            department=department,
            source=source,
            last_modified=latest_applicability,
            subjects=(),
            extra=tuple(extra),
        )
