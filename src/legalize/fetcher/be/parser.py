"""Parser for Justel HTML pages (Belgium).

Each Justel page contains both the consolidated text and metadata for a single
law, arrêté, decree, ordinance, or constitution. The page is structured into
three main boxes:

    div#list-title-1 (class="box")           -- Title + metadata card
    div#list-title-2 (class="box plain-text") -- Table of contents (skipped)
    div#list-title-3 (class="box plain-text") -- Legal text body

The body is mostly plain text separated by <br> tags, with two kinds of
anchor markers:

    <a name="LNKxxxx">TITRE I.</a>   -- Title/chapter/section headings
    <a name="Art.N">Article</a>      -- Article boundaries

Inline amendment annotations appear as:

    <sup><font color="red"><a href="#t" title="<L date, art. X; En vigueur: date>">N</a></font></sup>

These are stripped (the footer section at the end of each amended article
already describes the amendment in plain text). Tables are present only in
annexes and tariff schedules -- they use standard <table>/<tr>/<td> markup
and are converted to Markdown pipe tables.

Justel serves ISO-8859-1 encoded HTML; we decode at the parser boundary to
produce clean UTF-8 output.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from datetime import date, datetime
from typing import Any

from lxml import html as lxml_html

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
from legalize.fetcher._tables import render_table
from legalize.fetcher._text import strip_control

logger = logging.getLogger(__name__)

# Justel serves Latin-1. Force the lxml HTML parser to decode as ISO-8859-1
# so we never inherit mojibake from auto-detection.
_HTML_PARSER = lxml_html.HTMLParser(encoding="iso-8859-1")


def _parse_html(data: bytes):
    """Parse Justel HTML bytes into an lxml tree with forced Latin-1 decoding."""
    return lxml_html.fromstring(data, parser=_HTML_PARSER)


# ─────────────────────────────────────────────
# Text hygiene
# ─────────────────────────────────────────────


def _clean_text(text: str) -> str:
    """Normalize whitespace, strip non-breaking spaces and invalid control chars."""
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = strip_control(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _element_text(el) -> str:
    """Get cleaned text content from an lxml element."""
    if el is None:
        return ""
    return _clean_text("".join(el.itertext()))


# ─────────────────────────────────────────────
# Rank mapping
# ─────────────────────────────────────────────

# Justel document type -> internal rank string. The document type is
# derived from the ELI URL that discovery puts in the composite norm_id.
DT_TO_RANK: dict[str, str] = {
    "constitution": "constitution",
    "loi": "loi",
    "decret": "decret",
    "ordonnance": "ordonnance",
    "arrete": "arrete_royal",
}


# ─────────────────────────────────────────────
# Date parsing
# ─────────────────────────────────────────────

# French month names (no accents, lowercase) to month numbers.
_FR_MONTHS: dict[str, int] = {
    "janvier": 1,
    "fevrier": 2,
    "fev": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
}

# Accent stripping helper for month names. We only need to normalise é/û/ç.
_ACCENT_MAP = str.maketrans("éèêëàâäôöùûüç", "eeeeaaaoouuuc")


def _parse_french_date(s: str) -> date | None:
    """Parse French date strings like '17 février 1994' or '1er janvier 2024'.

    Handles 'NNer' (first) and 'N' day forms. Returns None on failure.
    """
    if not s:
        return None
    text = _clean_text(s).lower().translate(_ACCENT_MAP)
    # "1er" -> "1", "23" -> "23"
    text = re.sub(r"(\d+)er\b", r"\1", text)
    match = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", text)
    if not match:
        return None
    day = int(match.group(1))
    month_name = match.group(2)
    year = int(match.group(3))
    month = _FR_MONTHS.get(month_name)
    if not month:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


# ─────────────────────────────────────────────
# Metadata extraction from list-title-1
# ─────────────────────────────────────────────

# Label -> key. Labels are matched case-insensitively on normalised text.
_META_LABELS: dict[str, str] = {
    "source": "source",
    "publication": "publication",
    "numero": "numero",
    "page": "page",
    "dossier numero": "dossier",
    "entree en vigueur": "entry_into_force",
}


def _extract_metadata_fields(title_box) -> dict[str, str]:
    """Extract labelled fields from the plain-text block inside list-title-1.

    Each field is a <p><strong>Label:</strong> Value</p> pair. We normalise
    the label (strip accents, lowercase, remove colon) and return a dict of
    string values indexed by stable keys defined in _META_LABELS.
    """
    out: dict[str, str] = {}
    for strong in title_box.xpath('.//div[contains(@class, "plain-text")]//strong'):
        label_raw = _element_text(strong)
        if not label_raw:
            continue
        label = label_raw.rstrip(":").strip().lower().translate(_ACCENT_MAP)
        key = _META_LABELS.get(label)
        if not key:
            continue
        # Value = the tail text of the <strong>, plus any trailing text
        # nodes up to the end of the enclosing <p>.
        value_parts: list[str] = []
        if strong.tail:
            value_parts.append(strong.tail)
        parent = strong.getparent()
        if parent is not None:
            # Append text from following siblings within the same <p>
            for sibling in strong.itersiblings():
                value_parts.append("".join(sibling.itertext()))
                if sibling.tail:
                    value_parts.append(sibling.tail)
        value = _clean_text(" ".join(value_parts))
        if value:
            out[key] = value
    return out


def _extract_modifies_list(title_box) -> list[str]:
    """Extract the list of NUMACs this law modifies.

    Rendered as '<p><strong>Ce texte modifie le texte suivant:</strong></p>'
    followed by one or more '<span class="tag-small"><a>NUMAC</a></span>' siblings.
    """
    out: list[str] = []
    for a in title_box.xpath('.//span[contains(@class, "tag-small")]//a'):
        text = _element_text(a)
        if text and text.isdigit():
            out.append(text)
    return out


def _extract_counts(title_box) -> dict[str, int]:
    """Extract the 'N versions archivées' and 'N arrêtés d'exécution' counts.

    Both appear as plain text inside <a> tags matching a numeric prefix.
    """
    counts: dict[str, int] = {}
    for a in title_box.xpath(".//a"):
        href = a.get("href", "") or ""
        text = _element_text(a)
        num_match = re.match(r"(\d+)\s", text)
        if not num_match:
            continue
        n = int(num_match.group(1))
        if "arch=" in href and "versions archivees" in text.translate(_ACCENT_MAP).lower():
            counts["archived_versions"] = n
        elif "arrexec=" in href and "arretes" in text.translate(_ACCENT_MAP).lower():
            counts["execution_orders"] = n
    return counts


# ─────────────────────────────────────────────
# Text body parsing
# ─────────────────────────────────────────────

# Article anchor regex: matches name="Art.1", name="Art.1er", name="Art.12bis", etc.
_ART_ANCHOR_RE = re.compile(r"^Art\.(.+)$")

# Chapter/title/section detection inside LNK-anchored headings.
_HEADING_PREFIX_RE = re.compile(
    r"^(LIVRE|TITRE|CHAPITRE|SECTION|SOUS-SECTION|PARTIE|ANNEXE)(\s|\.|$)",
    re.IGNORECASE,
)


# Unicode superscript digits for converting <sup>N</sup> → "ⁿ".
_SUPERSCRIPT_DIGITS = str.maketrans(
    "0123456789",
    "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079",
)


def _digits_to_superscript(text: str) -> str:
    """Map ASCII digits in ``text`` to their Unicode superscript equivalents."""
    return text.translate(_SUPERSCRIPT_DIGITS)


def _convert_sup_markers(el) -> None:
    """Convert <sup>N</sup> elements to Unicode superscript text.

    Justel uses '[<sup>N</sup> ... ]<sup>N</sup>' to bracket text added or
    modified by amendment #N. The matching footer '(N)<L date, art. X; ...>'
    gives the full amendment reference. Preserving the N markers keeps the
    track-change convention visible in Markdown output; dropping them would
    lose the association between the bracketed text and the footer.

    We replace each <sup> with a text node containing the Unicode superscript
    equivalent (so "[<sup>1</sup> text ]<sup>1</sup>" → "[¹ text ]¹").
    """
    for sup in el.xpath(".//sup"):
        parent = sup.getparent()
        if parent is None:
            continue
        # Build the replacement text from the sup's inner text content.
        inner = "".join(sup.itertext())
        replacement = _digits_to_superscript(inner.strip()) if inner else ""
        tail = sup.tail or ""
        combined = replacement + tail
        prev = sup.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + combined
        else:
            parent.text = (parent.text or "") + combined
        parent.remove(sup)


def _strip_red_spans(el) -> None:
    """Flatten inline red spans left over from amendment styling.

    After converting <sup> markers, Justel may still leave '<font color="red">(N)</font>'
    (in footer lines) and '<span style="color:red;">N</span>' (inside brackets).
    We keep their text content but remove the wrapping element so the output is
    plain Markdown without color attributes.
    """
    for node in el.xpath('.//font[@color="red"] | .//span[contains(@style, "color:red")]'):
        parent = node.getparent()
        if parent is None:
            continue
        # Preserve both inner text and tail
        inner = "".join(node.itertext())
        tail = node.tail or ""
        combined = inner + tail
        prev = node.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + combined
        else:
            parent.text = (parent.text or "") + combined
        parent.remove(node)


def _table_cell_text(td) -> str:
    """Extract clean text from a <td>, preserving <br> line breaks.

    Line breaks inside table cells are rendered as '<br>' (HTML inline)
    because Markdown's pipe-table syntax has no native multi-line cell
    support. Most Markdown renderers (GitHub, CommonMark, Pandoc) accept
    inline HTML <br> inside table cells.

    Pipes are escaped so they do not break the row boundary.
    """
    parts: list[str] = []

    def walk(el, parent_text: str = "") -> None:
        # Emit element.text before recursing
        if el.text:
            parts.append(el.text)
        for child in el:
            tag = (child.tag or "").lower()
            if tag == "br":
                parts.append("<br>")
            elif tag in ("b", "strong"):
                inner = "".join(child.itertext())
                if inner:
                    parts.append(f"**{inner}**")
            elif tag in ("i", "em"):
                inner = "".join(child.itertext())
                if inner:
                    parts.append(f"*{inner}*")
            else:
                walk(child)
            if child.tail:
                parts.append(child.tail)

    walk(td)
    raw = "".join(parts)
    # Normalize whitespace around <br> but keep the tag intact.
    raw = re.sub(r"\s*<br>\s*", "<br>", raw)
    raw = strip_control(raw)
    raw = raw.replace("\xa0", " ")
    raw = re.sub(r"[ \t]+", " ", raw)
    # No pipe escaping here — render_table escapes cell text itself.
    return raw.strip()


def _table_to_markdown(table_el) -> str:
    """Convert a Justel <table> to a Markdown pipe table."""
    return render_table(table_el, _table_cell_text)


def _serialise_children_to_segments(el) -> list[tuple[str, Any]]:
    """Walk the children of a text-body element and yield typed segments.

    Each segment is a (kind, payload) tuple:
        ("text",    str)                 Plain text / inline content
        ("br",      None)                Line break
        ("heading", text)                A structural heading (TITRE/CHAPITRE/...)
        ("article", art_id)              An Art.N anchor starting a new article
        ("table",   md_string)           A converted table

    The caller groups segments into Block objects. Order is preserved.

    Headings absorb their anchor's tail text up to the next <br>, so
    '<a name="LNK01">TITRE I.</a> - DE LA BELGIQUE<br><br>' becomes a single
    heading segment "TITRE I. - DE LA BELGIQUE".
    """
    segments: list[tuple[str, Any]] = []
    # Running buffer used to absorb the tail of a heading anchor up to the
    # next <br>. None means "not absorbing".
    heading_buffer: list[str] | None = None
    heading_br_count = 0

    def emit_text(text: str) -> None:
        nonlocal heading_buffer, heading_br_count
        if not text:
            return
        if heading_buffer is not None:
            heading_buffer.append(text)
            return
        segments.append(("text", text))

    def emit_br() -> None:
        nonlocal heading_buffer, heading_br_count
        if heading_buffer is not None:
            heading_br_count += 1
            # Any <br> closes the heading capture -- Justel always follows
            # LNK anchors with a trailing description on the same line and
            # ends the whole heading with <br><br>.
            heading_text = _clean_text(" ".join(heading_buffer))
            segments.append(("heading", heading_text))
            heading_buffer = None
            heading_br_count = 0
            # The <br> that closed the heading is not emitted separately,
            # but any leftover consecutive <br>s would become paragraph
            # breaks in the body that follows -- we ignore those because
            # the _segments_to_blocks flush logic handles block boundaries.
            return
        segments.append(("br", None))

    def open_heading(initial_text: str) -> None:
        nonlocal heading_buffer, heading_br_count
        heading_buffer = [initial_text]
        heading_br_count = 0

    if el.text:
        emit_text(el.text)

    for child in el:
        tag = (child.tag or "").lower()

        # Skip the leading "Texte" section header that Justel injects.
        if tag == "h2":
            if child.tail:
                emit_text(child.tail)
            continue

        if tag == "br":
            emit_br()
            if child.tail:
                emit_text(child.tail)
            continue

        if tag == "a":
            name = child.get("name") or ""
            href = child.get("href") or ""
            text = _element_text(child)
            # Article anchor: <a name="Art.N"> starts a new article.
            if name.startswith("Art."):
                article_id = name[4:]
                segments.append(("article", article_id))
                if child.tail:
                    emit_text(child.tail)
                continue
            # Structural heading anchor: <a name="LNKxxxx">TITRE/CHAPITRE/...</a>.
            # LNKRxxxx is the reverse anchor used by the table of contents;
            # skip those as pure navigation markers.
            if name.startswith("LNK") and not name.startswith("LNKR"):
                open_heading(text)
                if child.tail:
                    emit_text(child.tail)
                continue
            # Cross-reference to another law on Justel: convert to a Markdown
            # link pointing at the absolute cgi_loi URL. The link text is
            # typically a dossier number like '2014-01-06/36' -- a stable,
            # human-readable reference.
            if text and "cn_search=" in href and not href.startswith("#"):
                if href.startswith("/"):
                    href = f"https://www.ejustice.just.fgov.be{href}"
                emit_text(f"[{text}]({href})")
                if child.tail:
                    emit_text(child.tail)
                continue
            # Other anchors: inline cross-references, just emit their text.
            emit_text(text)
            if child.tail:
                emit_text(child.tail)
            continue

        if tag == "table":
            # Close any open heading before emitting a table.
            if heading_buffer is not None:
                heading_text = _clean_text(" ".join(heading_buffer))
                segments.append(("heading", heading_text))
                heading_buffer = None
            md = _table_to_markdown(child)
            if md:
                segments.append(("table", md))
            if child.tail:
                emit_text(child.tail)
            continue

        if tag in ("b", "strong"):
            text = _element_text(child)
            if text:
                emit_text(f"**{text}**")
            if child.tail:
                emit_text(child.tail)
            continue

        if tag in ("i", "em"):
            text = _element_text(child)
            if text:
                emit_text(f"*{text}*")
            if child.tail:
                emit_text(child.tail)
            continue

        if tag == "img":
            # Skip images; their tail text may still matter.
            if child.tail:
                emit_text(child.tail)
            continue

        # Generic container: recurse so we pick up nested anchors/brs.
        sub_segments = _serialise_children_to_segments(child)
        segments.extend(sub_segments)
        if child.tail:
            emit_text(child.tail)

    # Flush any pending heading buffer at the end of the element.
    if heading_buffer is not None:
        heading_text = _clean_text(" ".join(heading_buffer))
        if heading_text:
            segments.append(("heading", heading_text))

    return segments


# Patterns used to strip redundant article-marker prefixes from the first
# paragraph of an article body. Justel's HTML repeats the article number
# right before the article text (e.g. '<a name="Art.1">Art.</a> 1. La Belgique...'),
# and after serialisation we end up with "1. La Belgique..." as the first
# paragraph. This regex strips the leading number+period so the body reads
# cleanly starting from "La Belgique...".
_LEADING_ART_PREFIX_RE = re.compile(
    r"^(?:Article\s+|Art\.\s*)?([0-9]+(?:er|bis|ter|quater|quinquies)?)\s*\.?\s*",
    re.IGNORECASE,
)


def _strip_article_prefix(text: str, art_id: str) -> str:
    """Remove '{art_id}.' / 'Article {art_id}.' / 'Art. {art_id}.' from text start.

    The article_id as captured by the anchor is the canonical number (e.g.
    '1', '1er', '12bis'). We compare case-insensitively so 'ART. 1ER' is also
    handled.
    """
    stripped = text.lstrip()
    # Match 'Article X.' or 'Art. X.' or bare 'X.' followed by optional space.
    pattern = re.compile(
        rf"^(?:Article\s+|Art\.?\s*)?{re.escape(art_id)}\.\s*",
        re.IGNORECASE,
    )
    return pattern.sub("", stripped, count=1)


def _segments_to_blocks(
    segments: list[tuple[str, Any]],
    law_norm_id: str,
    pub_date: date,
) -> list[Block]:
    """Group serialised text segments into Block objects.

    Model: there is always exactly one "current block" being accumulated.
    It starts out as an empty preamble and is replaced (not closed) whenever
    a heading or article segment arrives. Text, <br> and table segments
    populate the current block's paragraphs. When a new block starts, the
    current one is committed with everything it accumulated -- including any
    footnote lines that Justel places right after the heading/article
    (e.g. '----------' and '(N)<L date, art X; ...>' amendment footers).

    This design avoids losing content: every paragraph belongs to the
    heading or article that most recently introduced it, which matches the
    legal semantics -- footer lines always describe the preceding block.
    """
    blocks: list[Block] = []
    block_index = 0

    # Current block state
    current_block_type = "preamble"
    current_block_title = "Préambule"
    current_article_id: str | None = None
    current_paragraphs: list[Paragraph] = []
    current_header_paragraph: Paragraph | None = None
    first_body_paragraph = False
    current_line_parts: list[str] = []

    def flush_line() -> None:
        nonlocal current_line_parts, first_body_paragraph
        text = _clean_text("".join(current_line_parts))
        current_line_parts = []
        if not text:
            return
        if first_body_paragraph and current_article_id is not None:
            # Strip "Article N." / "Art. N." / bare "N." that duplicates the
            # article number, then emit the article header paragraph.
            cleaned = _strip_article_prefix(text, current_article_id)
            first_body_paragraph = False
            header_text = f"Article {current_article_id}."
            if cleaned:
                header_text = f"{header_text} {cleaned}"
            current_paragraphs.append(Paragraph(css_class="articulo", text=header_text.strip()))
            return
        current_paragraphs.append(Paragraph(css_class="parrafo", text=text))

    def commit_current_block() -> None:
        nonlocal current_paragraphs, current_header_paragraph, block_index
        nonlocal current_article_id
        flush_line()
        paragraphs: list[Paragraph] = []
        if current_header_paragraph is not None:
            paragraphs.append(current_header_paragraph)
        paragraphs.extend(current_paragraphs)
        # Skip empty preamble blocks (first block with no content at all).
        if not paragraphs and current_block_type == "preamble":
            current_paragraphs = []
            current_header_paragraph = None
            return
        # Ensure an article always has a header line (for stubs).
        if current_article_id is not None and not any(
            p.css_class == "articulo" for p in paragraphs
        ):
            paragraphs.insert(
                0,
                Paragraph(
                    css_class="articulo",
                    text=f"Article {current_article_id}.",
                ),
            )
        if current_article_id is not None:
            block_id = f"art-{current_article_id}".replace(" ", "_")
        elif current_block_type == "preamble":
            block_id = "preamble"
        elif current_block_type == "title":
            block_id = f"title-{block_index}"
        elif current_block_type == "annex":
            block_id = f"annex-{block_index}"
        else:
            block_id = f"chapter-{block_index}"
        version = Version(
            norm_id=law_norm_id,
            publication_date=pub_date,
            effective_date=pub_date,
            paragraphs=tuple(paragraphs),
        )
        blocks.append(
            Block(
                id=block_id,
                block_type=current_block_type,
                title=current_block_title,
                versions=(version,),
            )
        )
        block_index += 1
        current_paragraphs = []
        current_header_paragraph = None

    def start_heading_block(heading_text: str) -> None:
        nonlocal current_block_type, current_block_title
        nonlocal current_header_paragraph, current_article_id
        nonlocal first_body_paragraph
        commit_current_block()
        upper = heading_text.upper()
        is_annex = upper.startswith("ANNEXE") or upper.startswith("BIJLAGE")
        has_structural_prefix = bool(_HEADING_PREFIX_RE.match(heading_text))
        if is_annex:
            current_block_type = "annex"
            css = "capitulo_tit"
        elif has_structural_prefix:
            current_block_type = "chapter"
            css = "capitulo_tit"
        else:
            current_block_type = "title"
            css = "titulo_tit"
        current_block_title = heading_text
        current_header_paragraph = Paragraph(css_class=css, text=heading_text)
        current_article_id = None
        first_body_paragraph = False

    def start_article_block(art_id: str) -> None:
        nonlocal current_block_type, current_block_title
        nonlocal current_header_paragraph, current_article_id
        nonlocal first_body_paragraph
        commit_current_block()
        art_id_clean = _clean_text(art_id).replace(" ", "_") or f"auto-{block_index}"
        current_block_type = "article"
        current_block_title = f"Article {art_id_clean}".strip()
        current_header_paragraph = None
        current_article_id = art_id_clean
        first_body_paragraph = True

    for kind, payload in segments:
        if kind == "text":
            current_line_parts.append(payload)
            continue

        if kind == "br":
            flush_line()
            continue

        if kind == "heading":
            heading_text_clean = _clean_text(payload)
            if not heading_text_clean:
                continue
            start_heading_block(heading_text_clean)
            continue

        if kind == "article":
            start_article_block(payload)
            continue

        if kind == "table":
            flush_line()
            current_paragraphs.append(Paragraph(css_class="table", text=payload))
            continue

    commit_current_block()
    return blocks


# ─────────────────────────────────────────────
# Text parser
# ─────────────────────────────────────────────


def _parse_iso_date(text: str | None) -> date | None:
    """Parse ``'YYYY-MM-DD'`` into a :class:`date`, or return None on failure."""
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _parse_text_to_blocks(html_bytes: bytes, norm_id: str) -> list[Block]:
    """Shared helper: parse a Justel HTML page into Block objects.

    Used by both ``JustelTextParser.parse_text`` (single snapshot) and
    ``JustelTextParser.parse_suvestine`` (per-version walk).
    """
    if not html_bytes:
        return []
    try:
        tree = _parse_html(html_bytes)
    except Exception as exc:
        logger.warning("Failed to parse Justel HTML: %s", exc)
        return []
    text_box = tree.xpath('//div[@id="list-title-3"]')
    if not text_box:
        return []
    body = text_box[0]
    _convert_sup_markers(body)
    _strip_red_spans(body)
    pub_date = _extract_pub_date_from_tree(tree) or date(1900, 1, 1)
    law_norm_id = _extract_numac(tree) or norm_id
    segments = _serialise_children_to_segments(body)
    return _segments_to_blocks(segments, law_norm_id, pub_date)


class JustelTextParser(TextParser):
    """Parses Justel HTML into Block objects."""

    def parse_text(self, data: bytes) -> list[Any]:
        return _parse_text_to_blocks(data, norm_id="unknown")

    def extract_reforms(self, data: bytes) -> list[Any]:
        """Snapshot-only reform extraction.

        The main /justel page only shows the latest consolidated text, so
        walking its blocks produces at most one Reform (the current
        snapshot). The pipeline instead calls ``parse_suvestine`` below
        with a multi-version blob that builds the full reform timeline
        from Justel's ``arch=N`` endpoints.
        """
        return []

    def parse_suvestine(
        self, suvestine_data: bytes, norm_id: str
    ) -> tuple[list[Block], list[Reform]]:
        """Parse a multi-version Justel blob into versioned Blocks + Reforms.

        ``suvestine_data`` is the JSON blob produced by
        ``JustelClient.get_suvestine``. It contains one entry per archived
        version, each with the HTML text of that version and the
        transition metadata (effective date, amending-law publication
        date, affected articles) extracted from the sidebar of the newest
        archive page.

        Output shape matches ``fetcher.lt.parser.LithuanianTextParser``:

        - ``blocks`` is a merged list where each Block has one ``Version``
          per archived snapshot. Blocks with identical ``id`` across
          snapshots are collapsed into a single Block with multiple
          Versions ordered by publication_date.
        - ``reforms`` is a chronological list of Reform records, one per
          archived version. ``Reform.date`` is the version's effective
          date; ``Reform.norm_id`` embeds the amending-law publication
          date so the committer's dedupe key is unique per reform;
          ``Reform.affected_blocks`` lists the article IDs reported by
          the sidebar (or is empty for the bootstrap version).
        """
        if not suvestine_data:
            return [], []

        try:
            blob = json.loads(suvestine_data.decode("utf-8"))
        except Exception as exc:
            logger.warning("Failed to decode suvestine blob for %s: %s", norm_id, exc)
            return [], []

        versions_payload = blob.get("versions") or []
        if not versions_payload:
            return [], []

        # The main page is our source of truth for the base publication date
        # (used for v1 when the sidebar has no predecessor).
        base_pub_date: date | None = None
        main_b64 = blob.get("main_text_b64")
        if main_b64:
            try:
                main_bytes = base64.b64decode(main_b64)
                base_pub_date = _extract_pub_date_from_tree(_parse_html(main_bytes))
            except Exception:
                base_pub_date = None

        snapshots: list[tuple[int, date, str | None, list[str], list[Block]]] = []
        for entry in versions_payload:
            v_num = int(entry.get("version_num") or 0)
            effective_iso = entry.get("effective_date")
            amend_pub_iso = entry.get("amending_law_pub_date")
            affected = list(entry.get("affected_articles") or [])
            text_b64 = entry.get("text_b64")
            if not text_b64:
                continue
            html_bytes = base64.b64decode(text_b64)

            # Parse this version's HTML into blocks (reuse the single-text parser)
            blocks_this_version = _parse_text_to_blocks(html_bytes, norm_id)
            if not blocks_this_version:
                continue

            # Pick the effective date: explicit from sidebar, or the base
            # publication date for v1, or this page's own pub_date as a
            # last resort.
            eff_date: date | None = _parse_iso_date(effective_iso)
            if eff_date is None and v_num == 1:
                eff_date = base_pub_date
            if eff_date is None:
                # Fall back to the version page's own metadata
                try:
                    eff_date = _extract_pub_date_from_tree(_parse_html(html_bytes))
                except Exception:
                    eff_date = None
            if eff_date is None:
                # Ultimate fallback: 1900-01-01 so the Version object stays
                # valid even if we could not resolve the date.
                eff_date = date(1900, 1, 1)

            snapshots.append((v_num, eff_date, amend_pub_iso, affected, blocks_this_version))

        if not snapshots:
            return [], []

        # Sort by version_num ascending so reforms are chronological.
        snapshots.sort(key=lambda s: s[0])

        # Merge blocks across snapshots so each Block has one Version per snapshot.
        block_order: list[str] = []
        seen_block_ids: set[str] = set()
        per_snapshot_block_map: list[dict[str, Block]] = []

        for _, _, _, _, snap_blocks in snapshots:
            snap_map: dict[str, Block] = {}
            for b in snap_blocks:
                snap_map[b.id] = b
                if b.id not in seen_block_ids:
                    seen_block_ids.add(b.id)
                    block_order.append(b.id)
            per_snapshot_block_map.append(snap_map)

        merged_blocks: list[Block] = []
        for block_id in block_order:
            versions_list: list[Version] = []
            chosen_title = ""
            chosen_type = "article"
            for (v_num, eff_date, _, _, _), snap_map in zip(snapshots, per_snapshot_block_map):
                block = snap_map.get(block_id)
                if block is None:
                    continue
                if not chosen_title:
                    chosen_title = block.title
                chosen_type = block.block_type
                # Clone the Version with the correct effective date
                original = block.versions[0]
                versions_list.append(
                    Version(
                        norm_id=f"{norm_id}:v{v_num:03d}",
                        publication_date=eff_date,
                        effective_date=eff_date,
                        paragraphs=original.paragraphs,
                    )
                )
            if versions_list:
                merged_blocks.append(
                    Block(
                        id=block_id,
                        block_type=chosen_type,
                        title=chosen_title,
                        versions=tuple(versions_list),
                    )
                )

        # Build the reform timeline. One Reform per snapshot. The first
        # snapshot (v1) gets affected_blocks = () so the committer tags it
        # as the bootstrap.
        reforms: list[Reform] = []
        prev_texts: dict[str, str] = {}
        for i, (v_num, eff_date, amend_pub_iso, affected, snap_blocks) in enumerate(snapshots):
            # Compute which blocks changed versus the previous snapshot so
            # the commit affected-blocks list is accurate (the sidebar's
            # "affected_articles" only lists the article numbers the legal
            # editors labelled, not every touched block).
            current_texts = {
                b.id: "\n".join(p.text for p in b.versions[0].paragraphs) for b in snap_blocks
            }
            if i == 0:
                affected_tuple: tuple[str, ...] = ()
            else:
                changed: list[str] = []
                for bid, txt in current_texts.items():
                    if prev_texts.get(bid) != txt:
                        changed.append(bid)
                # Use the diff if non-empty; fall back to the sidebar hints
                if changed:
                    affected_tuple = tuple(changed)
                else:
                    affected_tuple = tuple(f"art-{a}" for a in affected)
            prev_texts = current_texts

            # Build a stable Source-Id for the commit dedupe key. For v1
            # we use the norm identifier; for later versions we encode the
            # amending-law publication date so each commit is unique.
            bare_numac = blob.get("numac") or norm_id.split(":")[-1]
            if i == 0:
                reform_norm_id = bare_numac
            else:
                suffix = amend_pub_iso or eff_date.isoformat()
                reform_norm_id = f"{bare_numac}@v{v_num:03d}:{suffix}"

            reforms.append(
                Reform(
                    date=eff_date,
                    norm_id=reform_norm_id,
                    affected_blocks=affected_tuple,
                )
            )

        return merged_blocks, reforms


# ─────────────────────────────────────────────
# Metadata parser
# ─────────────────────────────────────────────


def _extract_numac(tree) -> str:
    """Extract the NUMAC from <span class="tag"> inside list-title-1."""
    spans = tree.xpath('//div[@id="list-title-1"]//span[contains(@class, "tag")]')
    for sp in spans:
        text = _element_text(sp)
        if text and text.isdigit() and len(text) == 10:
            return text
    return ""


def _extract_pub_date_from_tree(tree) -> date | None:
    """Extract the publication date from the metadata box."""
    title_box = tree.xpath('//div[@id="list-title-1"]')
    if not title_box:
        return None
    fields = _extract_metadata_fields(title_box[0])
    return _parse_french_date(fields.get("publication", ""))


def _infer_status(title: str) -> NormStatus:
    """Infer status from the title. Justel has no explicit status field."""
    lowered = title.lower()
    if "abrog" in lowered or "[abrogé]" in lowered or "[abroge]" in lowered:
        return NormStatus.REPEALED
    return NormStatus.IN_FORCE


class JustelMetadataParser(MetadataParser):
    """Parses Justel HTML metadata into NormMetadata."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        if not data:
            raise ValueError(f"Empty data for norm {norm_id}")

        tree = _parse_html(data)

        title_box_list = tree.xpath('//div[@id="list-title-1"]')
        if not title_box_list:
            raise ValueError(f"No list-title-1 found for norm {norm_id}")
        title_box = title_box_list[0]

        # Title from <p class="list-item--title">
        title_nodes = title_box.xpath('.//p[contains(@class, "list-item--title")]')
        title = _element_text(title_nodes[0]) if title_nodes else ""

        # NUMAC from <span class="tag">
        numac = _extract_numac(tree)

        # Structured metadata fields (Source, Publication, Numéro, Dossier, ...)
        fields = _extract_metadata_fields(title_box)
        modifies_list = _extract_modifies_list(title_box)
        counts = _extract_counts(title_box)

        publication_str = fields.get("publication", "")
        publication_date = _parse_french_date(publication_str) or date(1900, 1, 1)
        entry_into_force = fields.get("entry_into_force", "")
        department = fields.get("source", "")
        dossier = fields.get("dossier", "")
        gazette_page = fields.get("page", "").strip()

        # Derive document type from the composite norm_id 'dt:yyyy:mm:dd:numac'.
        # Fall back to 'loi' if the norm_id is a bare NUMAC (e.g. during tests).
        dt = "loi"
        parts = norm_id.split(":")
        if len(parts) == 5:
            dt = parts[0]
        rank_str = DT_TO_RANK.get(dt, "loi")

        status = _infer_status(title)

        # The filesystem identifier is the bare NUMAC. Discovery provides
        # composite IDs ("dt:yyyy:...") but the committer wants stable,
        # filesystem-safe names. If the caller passed the composite form,
        # we store the NUMAC alone.
        identifier = numac or (parts[4] if len(parts) == 5 else norm_id)

        source_url = (
            f"https://www.ejustice.just.fgov.be/eli/"
            f"{parts[0]}/{parts[1]}/{parts[2]}/{parts[3]}/{parts[4]}/justel"
            if len(parts) == 5
            else f"https://www.ejustice.just.fgov.be/cgi_loi/article.pl?numac={identifier}"
        )

        pdf_url = None
        consolidated_pdf = None
        if len(parts) == 5:
            _, yyyy, mm, dd, nn = parts
            pdf_url = f"https://www.ejustice.just.fgov.be/mopdf/{yyyy}/{mm}/{dd}_N.pdf"
            consolidated_pdf = (
                f"https://www.ejustice.just.fgov.be/img_l/pdf/{yyyy}/{mm}/{dd}/{nn}_F.pdf"
            )

        extra: list[tuple[str, str]] = []
        if dossier:
            extra.append(("dossier_number", dossier))
        if entry_into_force:
            extra.append(("entry_into_force", entry_into_force))
        if gazette_page:
            extra.append(("gazette_page", gazette_page))
        if modifies_list:
            extra.append(("modifies", ",".join(modifies_list)))
        if counts.get("archived_versions"):
            extra.append(("archived_versions", str(counts["archived_versions"])))
        if counts.get("execution_orders"):
            extra.append(("execution_orders", str(counts["execution_orders"])))
        if consolidated_pdf:
            extra.append(("consolidated_pdf", consolidated_pdf))
        extra.append(("document_type", dt))
        extra.append(("language", "fr"))

        return NormMetadata(
            title=title or f"Norm {identifier}",
            short_title=title or f"Norm {identifier}",
            identifier=identifier,
            country="be",
            rank=Rank(rank_str),
            publication_date=publication_date,
            status=status,
            department=department,
            source=source_url,
            pdf_url=pdf_url,
            subjects=(),
            extra=tuple(extra),
        )
