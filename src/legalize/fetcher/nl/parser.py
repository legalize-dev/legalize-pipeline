"""Parser for Dutch BWB "toestand" XML files.

The Basis Wetten Bestand publishes each regulation as an XML "toestand"
(state) that mirrors a single point-in-time version. The toestand root
contains a ``<wetgeving>`` element with:

- ``<intitule>`` — the long official title
- ``<citeertitel>`` — the short citation title
- ``<wet-besluit>/<wettekst>`` — for laws (``wet``)
- ``<regeling>`` — for regulations (``ministeriele-regeling``, ``AMvB`` etc.)
- ``<slotformulering>`` — signatories at the end

Structural elements inside ``wettekst`` / ``regeling``:
- ``hoofdstuk`` (chapter), ``titeldeel`` (title), ``afdeling`` (division),
  ``paragraaf`` (section), ``artikel`` (article)
- ``lid`` (numbered subsection) with ``lidnr`` + ``al``
- ``lijst`` (list) with ``li`` items (each has ``li.nr``)
- ``al`` (alinea = paragraph of running text)
- ``table`` (CALS format with ``tgroup``/``thead``/``tbody``/``row``/``entry``)
- ``bijlage`` (annex)

Inline formatting:
- ``<nadruk type="halfvet">`` → bold
- ``<nadruk type="cursief">`` → italic
- ``<intref>`` / ``<extref>`` → hyperlinks

Reform metadata sits on every structural element as attributes:
``bron`` (gazette ref), ``inwerking`` (effective date), ``effect`` (type
of change), ``ondertekening_bron``, ``publicatie_bron``, ``publicatie_iwt``,
``status``. Only the current expression is downloaded; all historical text
is derived from the per-element ``bron``/``inwerking`` pair.
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
from legalize.fetcher._text import strip_control

logger = logging.getLogger(__name__)


def _clean(text: str | None) -> str:
    """Normalize whitespace, replace NBSP, strip control chars."""
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = strip_control(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_iso_date(value: str | None) -> date | None:
    """Parse YYYY-MM-DD from attribute. Returns None for empty / 9999-12-31."""
    if not value:
        return None
    value = value.strip()
    if value in ("", "9999-12-31"):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


# ─────────────────────────────────────────────
# Inline text extraction (nadruk, intref, extref, ...)
# ─────────────────────────────────────────────


def _inline_text(el: etree._Element) -> str:
    """Flatten an element into a single text string with inline Markdown markers.

    Handles:
        - <nadruk type="halfvet">   → **...**
        - <nadruk type="cursief">   → *...*
        - <intref doc="...">        → [text](https://wetten.overheid.nl/...)
        - <extref doc="..." href="...">  → [text](href or doc)
        - <redactie>                → inline text (editorial note)
        - all other inline children → recursive

    Preserves surrounding text and tail, collapses whitespace at the end.
    """
    parts: list[str] = []
    if el.text:
        parts.append(el.text)

    for child in el:
        tag = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
        inner = _inline_text(child).strip()

        if tag == "nadruk":
            if not inner:
                pass
            elif child.get("type") == "cursief":
                parts.append(f"*{inner}*")
            else:
                # halfvet or default → bold
                parts.append(f"**{inner}**")
        elif tag in ("intref", "extref"):
            # BWB cross-references. ``intref`` stays inside the current law,
            # ``extref`` can point either at another BWB document (via
            # ``doc="jci1.3:..."``) or at a truly external URL (via ``href``).
            # We always prefix JCI URNs with the wetten.overheid.nl portal so
            # the resulting link is clickable in any Markdown renderer.
            href = child.get("href") or ""
            doc = child.get("doc") or ""
            if href:
                url = href
            elif doc.startswith(("jci", "1.0:", "1.3:")):
                url = f"https://wetten.overheid.nl/{doc}"
            else:
                url = doc
            if inner and url:
                parts.append(f"[{inner}]({url})")
            else:
                parts.append(inner)
        elif tag in ("redactie", "redactionele-correctie"):
            # Editorial note — keep the text inline
            if inner:
                parts.append(inner)
        elif tag == "meta-data":
            # Skip per-element metadata blocks (they are harvested separately)
            continue
        elif tag in ("noot", "specificatielijst"):
            # Footnotes and specification lists are rare; keep the text inline
            if inner:
                parts.append(inner)
        else:
            # Unknown inline element — just keep its text content
            if inner:
                parts.append(inner)

        if child.tail:
            parts.append(child.tail)

    return _clean("".join(parts))


# ─────────────────────────────────────────────
# CALS tables → Markdown pipe tables
# ─────────────────────────────────────────────


def _cals_table_to_markdown(table_el: etree._Element) -> str:
    """Convert a CALS <table> element into a Markdown pipe table.

    CALS structure::

        <table>
          <tgroup cols="N">
            <colspec colname="col1" colnum="1" .../>
            ...
            <thead><row><entry>...</entry>...</row></thead>
            <tbody><row><entry>...</entry>...</row>...</tbody>
          </tgroup>
        </table>

    Each ``<entry>`` may span columns via ``namest``/``nameend`` and rows via
    ``morerows``. Cell content lives in ``<al>`` children.
    """
    tgroup = table_el.find("tgroup")
    if tgroup is None:
        return ""

    cols_attr = tgroup.get("cols") or "1"
    try:
        n_cols = max(1, int(cols_attr))
    except ValueError:
        n_cols = 1

    # Map colname → 1-indexed position
    col_index: dict[str, int] = {}
    for i, spec in enumerate(tgroup.findall("colspec"), start=1):
        name = spec.get("colname")
        if name:
            col_index[name] = i

    def _cell_text(entry: etree._Element) -> str:
        """Extract the Markdown text of a single <entry> cell."""
        chunks: list[str] = []
        for al in entry.findall("al"):
            chunks.append(_inline_text(al))
        if not chunks:
            chunks.append(_inline_text(entry))
        cell = " ".join(c for c in chunks if c)
        return cell.replace("|", "\\|").replace("\n", " ").strip()

    # Build rows: list of (cells, is_header). Handle rowspan via pending map.
    raw_rows: list[tuple[list[tuple[int, int, int, str]], bool]] = []
    # Each cell tuple: (start_col, end_col, rowspan, text)
    for section, is_header in (("thead", True), ("tbody", False)):
        for section_el in tgroup.findall(section):
            for row in section_el.findall("row"):
                cells: list[tuple[int, int, int, str]] = []
                for entry in row.findall("entry"):
                    namest = entry.get("namest")
                    nameend = entry.get("nameend")
                    colname = entry.get("colname")
                    start = col_index.get(namest or colname or "", 0)
                    end = col_index.get(nameend or colname or "", start)
                    if start == 0:
                        # Fallback: pack sequentially if column names are missing
                        start = 1 if not cells else cells[-1][1] + 1
                        end = start
                    try:
                        rowspan = int(entry.get("morerows") or "0") + 1
                    except ValueError:
                        rowspan = 1
                    text = _cell_text(entry)
                    cells.append((start, end, rowspan, text))
                raw_rows.append((cells, is_header))

    if not raw_rows:
        return ""

    # Expand rowspan/colspan into a 2D grid
    grid: list[list[str]] = []
    header_rows: list[int] = []
    pending: dict[int, tuple[str, int]] = {}  # col → (text, remaining)

    for cells, is_header in raw_rows:
        row: list[str] = [""] * n_cols
        # First fill in pending rowspans from previous rows
        for col, (text, remaining) in list(pending.items()):
            if 1 <= col <= n_cols:
                row[col - 1] = text
            if remaining > 1:
                pending[col] = (text, remaining - 1)
            else:
                del pending[col]
        # Now place this row's cells
        for start, end, rowspan, text in cells:
            for c in range(start, end + 1):
                if 1 <= c <= n_cols:
                    row[c - 1] = text
                if rowspan > 1:
                    pending[c] = (text, rowspan - 1)
        grid.append(row)
        if is_header:
            header_rows.append(len(grid) - 1)

    if not grid:
        return ""

    # Build Markdown output
    lines: list[str] = []
    header_idx = header_rows[0] if header_rows else 0
    header = grid[header_idx]
    lines.append("| " + " | ".join(c or " " for c in header) + " |")
    lines.append("| " + " | ".join("---" for _ in range(n_cols)) + " |")
    for i, row in enumerate(grid):
        if i == header_idx:
            continue
        lines.append("| " + " | ".join(c or " " for c in row) + " |")
    return "\n".join(lines)


# ─────────────────────────────────────────────
# Heading / paragraph helpers
# ─────────────────────────────────────────────


def _kop_text(kop: etree._Element | None) -> tuple[str, str, str]:
    """Extract (label, number, title) from a <kop> element.

    Returns empty strings for missing parts.
    """
    if kop is None:
        return "", "", ""
    label = ""
    number = ""
    title = ""
    label_el = kop.find("label")
    if label_el is not None:
        label = _inline_text(label_el)
    nr_el = kop.find("nr")
    if nr_el is not None:
        number = _inline_text(nr_el)
    titel_el = kop.find("titel")
    if titel_el is not None:
        title = _inline_text(titel_el)
    return label, number, title


def _format_heading(kop: etree._Element | None, fallback: str = "") -> str:
    """Compose a heading string like ``Hoofdstuk 1. Grondrechten``."""
    label, number, title = _kop_text(kop)
    pieces = [p for p in (label, number) if p]
    head = " ".join(pieces)
    if head and title:
        return f"{head}. {title}"
    return head or title or fallback


def _lid_paragraphs(lid: etree._Element) -> list[Paragraph]:
    """Convert a <lid> element into a list of Markdown-ready paragraphs.

    A lid (numbered subsection) contains one or more <al> blocks and
    optionally <lijst>, <table>, <bijlage-sub> children. The first <al>
    is prefixed with the lid number for readability.
    """
    out: list[Paragraph] = []
    lidnr_el = lid.find("lidnr")
    prefix = ""
    if lidnr_el is not None:
        nr = _inline_text(lidnr_el).strip().rstrip(".")
        if nr:
            prefix = f"{nr}. "

    first = True
    for child in lid:
        tag = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
        if tag == "lidnr":
            continue
        if tag == "meta-data":
            continue
        if tag == "al":
            text = _inline_text(child)
            if not text:
                continue
            if first and prefix:
                text = prefix + text
                first = False
            out.append(Paragraph(css_class="parrafo", text=text))
        elif tag == "lijst":
            out.extend(_lijst_paragraphs(child))
        elif tag == "table":
            md = _cals_table_to_markdown(child)
            if md:
                out.append(Paragraph(css_class="table", text=md))
        elif tag == "figuur":
            # Skipped — counted at the parser level
            continue
        else:
            text = _inline_text(child)
            if text:
                out.append(Paragraph(css_class="parrafo", text=text))
    # If the lid had no <al> children but a prefix, still emit the number
    if first and prefix and not out:
        out.append(Paragraph(css_class="parrafo", text=prefix.strip()))
    return out


def _lijst_paragraphs(lijst: etree._Element, depth: int = 0) -> list[Paragraph]:
    """Convert a <lijst> element into Markdown list-item paragraphs.

    Supports nested lists (depth becomes leading-space indent).
    """
    out: list[Paragraph] = []
    indent = "  " * depth
    for li in lijst.findall("li"):
        li_nr_el = li.find("li.nr")
        li_nr = _inline_text(li_nr_el).strip() if li_nr_el is not None else ""
        li_nr = li_nr.rstrip(".")

        # Gather the item's text from its <al> children (flattening nested lists)
        item_chunks: list[str] = []
        nested_lists: list[etree._Element] = []
        nested_tables: list[etree._Element] = []
        for child in li:
            tag = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
            if tag == "li.nr":
                continue
            if tag == "meta-data":
                continue
            if tag == "al":
                chunk = _inline_text(child)
                if chunk:
                    item_chunks.append(chunk)
            elif tag == "lijst":
                nested_lists.append(child)
            elif tag == "table":
                nested_tables.append(child)
            elif tag == "figuur":
                continue
            else:
                chunk = _inline_text(child)
                if chunk:
                    item_chunks.append(chunk)

        body = " ".join(c for c in item_chunks if c).strip()
        prefix = f"- {li_nr}. " if li_nr else "- "
        line = f"{indent}{prefix}{body}" if body else f"{indent}{prefix}".rstrip()
        if body or li_nr:
            out.append(Paragraph(css_class="list_item", text=line))

        for nested in nested_lists:
            out.extend(_lijst_paragraphs(nested, depth=depth + 1))
        for table in nested_tables:
            md = _cals_table_to_markdown(table)
            if md:
                out.append(Paragraph(css_class="table", text=md))
    return out


def _article_paragraphs(artikel: etree._Element, images_dropped: list[int]) -> list[Paragraph]:
    """Convert an <artikel> element into a list of Paragraphs.

    The <kop> becomes an "articulo" heading; children (<al>, <lid>, <lijst>,
    <table>) become body paragraphs. Figures are dropped and counted.
    """
    out: list[Paragraph] = []
    kop = artikel.find("kop")
    heading = _format_heading(kop)
    if heading:
        out.append(Paragraph(css_class="articulo", text=heading))

    for child in artikel:
        tag = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
        if tag in ("kop", "meta-data"):
            continue
        if tag == "al":
            text = _inline_text(child)
            if text:
                out.append(Paragraph(css_class="parrafo", text=text))
        elif tag == "lid":
            out.extend(_lid_paragraphs(child))
        elif tag == "lijst":
            out.extend(_lijst_paragraphs(child))
        elif tag == "table":
            md = _cals_table_to_markdown(child)
            if md:
                out.append(Paragraph(css_class="table", text=md))
        elif tag == "figuur":
            images_dropped[0] += 1
            out.append(Paragraph(css_class="parrafo", text="[image omitted]"))
        elif tag == "bijlage-sub":
            # Sub-annex inside article — render as plain text
            sub_text = _inline_text(child)
            if sub_text:
                out.append(Paragraph(css_class="parrafo", text=sub_text))
    return out


# Map XML structural element name → (css_class for heading, heading kind)
# The heading level is implicit from the css_class (see transformer/markdown.py).
_STRUCT_ELEMENTS = {
    "boek": "titulo_tit",
    "deel": "titulo_tit",
    "titeldeel": "titulo_tit",
    "hoofdstuk": "capitulo_tit",
    "afdeling": "capitulo_tit",
    "paragraaf": "seccion",
    "subparagraaf": "seccion",
    "sub-paragraaf": "seccion",
    "sub-sub-paragraaf": "seccion",
    "sub-afdeling": "seccion",
    # Circulaire structural divisions
    "circulaire.divisie": "capitulo_tit",
    "circulaire-divisie": "capitulo_tit",
    "circulaire.sub-divisie": "seccion",
    # Beleidsregel / besluit structural divisions
    "beleidsregel.divisie": "capitulo_tit",
    "beleidsregel-divisie": "capitulo_tit",
    # Treaty articles are wrapped in "verdragtekst" (similar to wettekst)
    # Some verdragen use divisies
    "divisie": "capitulo_tit",
    "sub-divisie": "seccion",
}

# Containers that simply hold body content and should be walked transparently.
# These are NOT emitted as blocks themselves.
_TRANSPARENT_CONTAINERS = frozenset(
    {
        "wet-besluit",
        "wettekst",
        "regeling",
        "regeling-tekst",
        "besluit",
        "besluit-tekst",
        "beleidsregel",
        "beleidsregel-tekst",
        "circulaire",
        "circulaire-tekst",
        "reglement",
        "reglement-tekst",
        "verdrag",
        "verdragtekst",
        "bijlagen",
        "tekst",
    }
)

# Aanhef/preamble-like elements — emit their text as preamble paragraphs.
_PREAMBLE_ELEMENTS = frozenset(
    {
        "aanhef",
        "circulaire.aanhef",
        "beleidsregel.aanhef",
        "context",
        "wie",
        "considerans",
        "afkondiging",
    }
)


def _walk_structure(
    el: etree._Element,
    blocks: list[Block],
    pub_date: date,
    law_id: str,
    images_dropped: list[int],
    block_counter: list[int],
    seen_ids: set[str],
) -> None:
    """Recursively walk a structural container emitting Blocks.

    Each ``<artikel>`` becomes its own Block. Each intermediate container
    (hoofdstuk, afdeling, ...) produces a single-paragraph heading Block so
    the Markdown renderer emits the correct heading levels.

    ``seen_ids`` is a shared set used to dedupe block IDs — when the same
    article number appears twice (e.g. the Constitution's "Algemene bepaling"
    collides with the counter-generated ``art-1``, or Books 1..N of a code
    re-use article numbers) we append a positional suffix so every block
    lands at a unique path.
    """
    for child in el:
        if not isinstance(child.tag, str):
            continue
        tag = etree.QName(child.tag).localname

        if tag in ("artikel", "enig-artikel"):
            article_num = ""
            article_title = ""
            kop = child.find("kop")
            if kop is not None:
                _, article_num, article_title = _kop_text(kop)
            if tag == "enig-artikel" and not article_num:
                article_num = "enig"
                article_title = article_title or "Enig artikel"
            paragraphs = _article_paragraphs(child, images_dropped)
            if not paragraphs:
                # ``enig-artikel`` often has no kop but direct <al> children.
                # Emit a synthetic heading so it's discoverable in the MD.
                if tag == "enig-artikel":
                    paragraphs = [Paragraph(css_class="articulo", text="Enig artikel")]
                    for sub in child:
                        sub_tag = etree.QName(sub.tag).localname if isinstance(sub.tag, str) else ""
                        if sub_tag == "al":
                            text = _inline_text(sub)
                            if text:
                                paragraphs.append(Paragraph(css_class="parrafo", text=text))
                if not paragraphs:
                    continue
            block_counter[0] += 1
            # Numbered articles get a stable ``art-{N}`` path so cross-links
            # remain predictable. Unnumbered articles (e.g. the Constitution's
            # "Algemene bepaling") fall back to a slug of their title so they
            # don't collide with any real number.
            if article_num:
                raw_id = f"art-{_safe_id(article_num)}"
            elif article_title:
                raw_id = f"art-{_slug(article_title)}"
            else:
                raw_id = f"art-{block_counter[0]}"
            block_id = raw_id
            if block_id in seen_ids:
                block_id = f"{raw_id}-{block_counter[0]}"
            seen_ids.add(block_id)
            title = paragraphs[0].text if paragraphs else f"Artikel {article_num}"
            # Reform tracking attributes — ``bron`` + ``inwerking`` drive the
            # reform timeline. When present they become the Version.norm_id +
            # publication_date. When absent we fall back to the law-level dates.
            v_norm_id, v_date = _version_coords(child, fallback_id=law_id, fallback_date=pub_date)
            blocks.append(_make_block(block_id, "article", title, paragraphs, v_norm_id, v_date))
            continue

        if tag == "bijlage":
            _append_annex(child, blocks, pub_date, law_id, images_dropped, block_counter, seen_ids)
            continue

        if tag in _STRUCT_ELEMENTS:
            css = _STRUCT_ELEMENTS[tag]
            kop = child.find("kop")
            heading = _format_heading(kop)
            if heading:
                block_counter[0] += 1
                heading_id = f"{tag}-{block_counter[0]}"
                seen_ids.add(heading_id)
                v_norm_id, v_date = _version_coords(
                    child, fallback_id=law_id, fallback_date=pub_date
                )
                blocks.append(
                    _make_block(
                        heading_id,
                        tag,
                        heading,
                        [Paragraph(css_class=css, text=heading)],
                        v_norm_id,
                        v_date,
                    )
                )
            _walk_structure(
                child, blocks, pub_date, law_id, images_dropped, block_counter, seen_ids
            )
            continue

        # Transparent wrappers: descend but emit nothing of their own.
        if tag in _TRANSPARENT_CONTAINERS:
            # For treaties with multiple language variants, prefer the Dutch
            # one (``xml:lang='nl'`` / ``tekst='vertaling'``). Walking both
            # would duplicate the whole body.
            if tag == "verdrag":
                lang = child.get("{http://www.w3.org/XML/1998/namespace}lang", "")
                tekst = child.get("tekst", "")
                siblings = [
                    s
                    for s in el
                    if isinstance(s.tag, str) and etree.QName(s.tag).localname == "verdrag"
                ]
                if len(siblings) > 1 and lang not in ("nl", "") and tekst != "vertaling":
                    continue  # skip non-Dutch language variants
            _walk_structure(
                child, blocks, pub_date, law_id, images_dropped, block_counter, seen_ids
            )
            continue

        # Preamble-like elements (aanhef, considerans, wie, afkondiging, ...)
        # Render their <al> children as plain paragraphs so no content is lost.
        if tag in _PREAMBLE_ELEMENTS:
            preamble_paragraphs: list[Paragraph] = []
            for sub in child.iter():
                if not isinstance(sub.tag, str):
                    continue
                sub_tag = etree.QName(sub.tag).localname
                if sub_tag == "al":
                    text = _inline_text(sub)
                    if text:
                        preamble_paragraphs.append(Paragraph(css_class="parrafo", text=text))
                elif sub_tag in ("considerans.al", "context.al"):
                    text = _inline_text(sub)
                    if text:
                        preamble_paragraphs.append(Paragraph(css_class="parrafo", text=text))
            if preamble_paragraphs:
                block_counter[0] += 1
                preamble_id = f"preamble-{block_counter[0]}"
                seen_ids.add(preamble_id)
                v_norm_id, v_date = _version_coords(
                    child, fallback_id=law_id, fallback_date=pub_date
                )
                blocks.append(
                    _make_block(
                        preamble_id,
                        "preamble",
                        preamble_paragraphs[0].text[:80],
                        preamble_paragraphs,
                        v_norm_id,
                        v_date,
                    )
                )
            continue

        # Stray <al> directly inside a structural container (preamble text)
        if tag == "al":
            text = _inline_text(child)
            if text:
                block_counter[0] += 1
                text_id = f"text-{block_counter[0]}"
                seen_ids.add(text_id)
                v_norm_id, v_date = _version_coords(
                    child, fallback_id=law_id, fallback_date=pub_date
                )
                blocks.append(
                    _make_block(
                        text_id,
                        "text",
                        text[:50],
                        [Paragraph(css_class="parrafo", text=text)],
                        v_norm_id,
                        v_date,
                    )
                )


def _append_annex(
    bijlage: etree._Element,
    blocks: list[Block],
    pub_date: date,
    law_id: str,
    images_dropped: list[int],
    block_counter: list[int],
    seen_ids: set[str],
) -> None:
    """Emit a Block for a <bijlage> (annex)."""
    kop = bijlage.find("kop")
    heading = _format_heading(kop, fallback="Bijlage")
    block_counter[0] += 1

    # If the annex contains its own structured content (artikel, hoofdstuk,
    # ...) we walk into it recursively so every article becomes its own block.
    has_nested_structure = any(
        isinstance(c.tag, str)
        and etree.QName(c.tag).localname in ({"artikel"} | set(_STRUCT_ELEMENTS))
        for c in bijlage
    )
    if has_nested_structure:
        # Emit the annex heading as a title block, then walk the body
        if heading:
            heading_id = f"annex-{block_counter[0]}"
            seen_ids.add(heading_id)
            v_norm_id, v_date = _version_coords(bijlage, fallback_id=law_id, fallback_date=pub_date)
            blocks.append(
                _make_block(
                    heading_id,
                    "annex",
                    heading,
                    [Paragraph(css_class="titulo_tit", text=heading)],
                    v_norm_id,
                    v_date,
                )
            )
        _walk_structure(bijlage, blocks, pub_date, law_id, images_dropped, block_counter, seen_ids)
        return

    paragraphs: list[Paragraph] = [Paragraph(css_class="titulo_tit", text=heading or "Bijlage")]
    for child in bijlage:
        tag = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
        if tag in ("kop", "meta-data"):
            continue
        if tag == "al":
            text = _inline_text(child)
            if text:
                paragraphs.append(Paragraph(css_class="parrafo", text=text))
        elif tag == "lid":
            paragraphs.extend(_lid_paragraphs(child))
        elif tag == "lijst":
            paragraphs.extend(_lijst_paragraphs(child))
        elif tag == "table":
            md = _cals_table_to_markdown(child)
            if md:
                paragraphs.append(Paragraph(css_class="table", text=md))
        elif tag == "figuur":
            images_dropped[0] += 1
            paragraphs.append(Paragraph(css_class="parrafo", text="[image omitted]"))

    annex_id = f"annex-{block_counter[0]}"
    seen_ids.add(annex_id)
    v_norm_id, v_date = _version_coords(bijlage, fallback_id=law_id, fallback_date=pub_date)
    blocks.append(
        _make_block(
            annex_id,
            "annex",
            heading or f"Bijlage {block_counter[0]}",
            paragraphs,
            v_norm_id,
            v_date,
        )
    )


def _version_coords(
    el: etree._Element, *, fallback_id: str, fallback_date: date
) -> tuple[str, date]:
    """Return (norm_id, publication_date) for the reform version of an element.

    Reads the ``bron`` and ``inwerking`` attributes; falls back to the law's
    bootstrap coordinates when they are missing.
    """
    bron = el.get("bron") or fallback_id
    inwerking = _parse_iso_date(el.get("inwerking")) or fallback_date
    return bron, inwerking


def _safe_id(raw: str) -> str:
    """Normalize an article number (e.g. ``"1a"``, ``"3.30"``) into an ID suffix."""
    s = raw.strip().replace(" ", "-").replace("/", "-")
    return re.sub(r"[^A-Za-z0-9._-]", "", s) or "0"


def _slug(raw: str, max_len: int = 48) -> str:
    """Build a filesystem-safe kebab-case slug from arbitrary title text.

    Used to give unnumbered articles ("Algemene bepaling") a stable ID that
    cannot collide with a numbered ``art-N`` block.
    """
    s = raw.strip().lower()
    s = re.sub(r"[\s\u00a0]+", "-", s)
    s = re.sub(r"[^a-z0-9._-]", "", s)
    s = s.strip("-_.") or "x"
    return s[:max_len]


def _make_block(
    block_id: str,
    block_type: str,
    title: str,
    paragraphs: list[Paragraph],
    norm_id: str,
    pub_date: date,
) -> Block:
    """Build a single-Version Block."""
    version = Version(
        norm_id=norm_id,
        publication_date=pub_date,
        effective_date=pub_date,
        paragraphs=tuple(paragraphs),
    )
    return Block(
        id=block_id,
        block_type=block_type,
        title=title,
        versions=(version,),
    )


def _append_signatories(
    slot: etree._Element, blocks: list[Block], pub_date: date, law_id: str, block_counter: list[int]
) -> None:
    """Emit a Block for the <slotformulering> section (enactment / signing text).

    BWB laws close with a ``slotformulering`` element containing either:
    - free-form enactment text inside ``<al>`` children ("Lasten en bevelen..."),
    - formal signing blocks (``dagtekening``, ``ondertekening``, ``plaats``,
      ``naam``), or both.
    We emit any ``<al>`` as normal paragraphs and the signing blocks as
    ``firma_rey`` (bold), matching the convention used by other countries.
    """
    paragraphs: list[Paragraph] = []
    for child in slot:
        tag = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
        if tag == "meta-data":
            continue
        if tag == "al":
            text = _inline_text(child)
            if text:
                paragraphs.append(Paragraph(css_class="parrafo", text=text))
        elif tag in ("dagtekening", "ondertekening", "plaats", "naam"):
            text = _inline_text(child)
            if text:
                paragraphs.append(Paragraph(css_class="firma_rey", text=text))
        else:
            # Nested signing blocks — recurse via iter() to collect text
            for sub in child.iter():
                sub_tag = etree.QName(sub.tag).localname if isinstance(sub.tag, str) else ""
                if sub_tag in ("dagtekening", "ondertekening", "plaats", "naam"):
                    text = _inline_text(sub)
                    if text:
                        paragraphs.append(Paragraph(css_class="firma_rey", text=text))
                elif sub_tag == "al" and sub.getparent() is child:
                    text = _inline_text(sub)
                    if text:
                        paragraphs.append(Paragraph(css_class="parrafo", text=text))
    if not paragraphs:
        return
    block_counter[0] += 1
    blocks.append(
        _make_block(
            f"signatories-{block_counter[0]}",
            "signatories",
            "Ondertekening",
            paragraphs,
            law_id,
            pub_date,
        )
    )


# ─────────────────────────────────────────────
# Root XML parsing
# ─────────────────────────────────────────────

_XML_PARSER = etree.XMLParser(recover=True, remove_blank_text=False, huge_tree=True)


def _parse_xml(data: bytes) -> etree._Element | None:
    """Parse BWB XML bytes defensively, returning the root or None on failure."""
    if not data:
        return None
    try:
        return etree.fromstring(data, parser=_XML_PARSER)
    except etree.XMLSyntaxError as exc:
        logger.warning("XML syntax error: %s", exc)
        return None


def _root_pub_date(root: etree._Element) -> date:
    """Derive the top-level publication date from the toestand/wetgeving attrs."""
    iso = root.get("inwerkingtreding")
    d = _parse_iso_date(iso)
    if d:
        return d
    wet = root.find("wetgeving")
    if wet is not None:
        d = _parse_iso_date(wet.get("inwerkingtredingsdatum"))
        if d:
            return d
    return date(1900, 1, 1)


# ─────────────────────────────────────────────
# Public parsers
# ─────────────────────────────────────────────


def _parse_single_toestand(
    root: etree._Element,
) -> tuple[list[Block], str, date]:
    """Parse one ``<toestand>`` root into a list of Blocks.

    Returns (blocks, bwb_id, publication_date). The blocks each carry a
    single Version whose ``publication_date`` matches the expression's
    effective date (so the generic :func:`extract_reforms` can later group
    them across expressions).
    """
    bwb_id = root.get("bwb-id") or ""
    pub_date = _root_pub_date(root)
    wet = root.find("wetgeving")
    if wet is None:
        return [], bwb_id, pub_date

    blocks: list[Block] = []
    images_dropped = [0]
    block_counter = [0]
    seen_ids: set[str] = set()

    # Treaties sometimes ship multiple language variants as sibling
    # ``<verdrag>`` elements (e.g. the authentic English text and its Dutch
    # translation). Pick the Dutch one so the repo stays monolingual.
    verdragen = [
        c for c in wet if isinstance(c.tag, str) and etree.QName(c.tag).localname == "verdrag"
    ]
    chosen_verdrag: etree._Element | None = None
    if len(verdragen) > 1:
        for v in verdragen:
            lang = v.get("{http://www.w3.org/XML/1998/namespace}lang", "")
            tekst = v.get("tekst", "")
            if lang == "nl" or tekst == "vertaling":
                chosen_verdrag = v
                break
        if chosen_verdrag is None:
            chosen_verdrag = verdragen[0]

    # Walk every direct child of <wetgeving> that might carry body content.
    # ``intitule`` and ``citeertitel`` are already harvested as metadata so
    # we skip them; every remaining container goes through _walk_structure,
    # which handles transparent wrappers and structural elements uniformly.
    for child in wet:
        if not isinstance(child.tag, str):
            continue
        tag = etree.QName(child.tag).localname
        if tag in ("intitule", "citeertitel", "meta-data"):
            continue
        if tag == "verdrag" and chosen_verdrag is not None and child is not chosen_verdrag:
            continue
        if tag == "bijlage":
            _append_annex(child, blocks, pub_date, bwb_id, images_dropped, block_counter, seen_ids)
            continue
        # Everything else: body container. Walk it transparently.
        _walk_structure(child, blocks, pub_date, bwb_id, images_dropped, block_counter, seen_ids)

    # (top-level bijlagen are handled inline in the loop above)

    for slot in wet.iter("slotformulering"):
        _append_signatories(slot, blocks, pub_date, bwb_id, block_counter)
        break

    if images_dropped[0]:
        logger.debug("Dropped %d <figuur> elements for %s", images_dropped[0], bwb_id)
    return blocks, bwb_id, pub_date


def _hash_paragraphs(paragraphs: tuple[Paragraph, ...]) -> str:
    """Cheap content hash to detect when a block's text has actually changed."""
    import hashlib

    h = hashlib.sha1()
    for p in paragraphs:
        h.update(p.css_class.encode("utf-8"))
        h.update(b"\x00")
        h.update(p.text.encode("utf-8"))
        h.update(b"\x01")
    return h.hexdigest()


class BWBTextParser(TextParser):
    """Parses BWB XML (single expression or multi-expression envelope) into Blocks.

    The input bytes may be either:
    - a single ``<toestand>`` root (the raw repository XML), or
    - a ``<bwb-multi-expression>`` envelope whose children are ``<expression
      effective-date="YYYY-MM-DD">`` wrappers around historical ``<toestand>``
      roots.

    For the multi-expression case we parse every expression, keep each
    article as a separate Block identified by its stable ID, and attach one
    ``Version`` per distinct content snapshot. The generic
    :func:`extract_reforms` then groups versions into chronologically sorted
    reforms which the pipeline commits to git.
    """

    def parse_text(self, data: bytes) -> list[Any]:
        root = _parse_xml(data)
        if root is None:
            return []

        tag = etree.QName(root.tag).localname if isinstance(root.tag, str) else ""
        if tag == "bwb-multi-expression":
            return self._parse_multi_expression(root)

        blocks, _, _ = _parse_single_toestand(root)
        return blocks

    def _parse_multi_expression(self, envelope: etree._Element) -> list[Block]:
        """Parse a multi-expression envelope into multi-Version Blocks.

        Each historical expression contributes one Version per block, keyed
        by the block's stable ID. A Version is only kept if its content
        differs from the previous one (same-text reissues are noise).
        """
        # Per-block accumulators: block_id → {
        #   "block_type", "title", "versions": list[Version], "last_hash": str
        # }
        accum: dict[str, dict[str, Any]] = {}
        # Preserve the order blocks first appear in the earliest expression
        # that contains them so the final Markdown renders consistently.
        first_seen: dict[str, int] = {}
        first_seen_counter = 0

        for expression in envelope.findall("expression"):
            effective_iso = expression.get("effective-date") or ""
            effective = _parse_iso_date(effective_iso) or date(1900, 1, 1)
            toestand = expression.find("toestand")
            if toestand is None:
                continue
            blocks, _, _ = _parse_single_toestand(toestand)
            for block in blocks:
                # Each block from _parse_single_toestand has exactly one Version
                if not block.versions:
                    continue
                source_version = block.versions[0]
                # Rebuild the Version's publication_date to the expression's
                # effective date so multiple expressions don't collapse into
                # the same (date, norm_id) key.
                rebuilt = Version(
                    norm_id=source_version.norm_id,
                    publication_date=effective,
                    effective_date=effective,
                    paragraphs=source_version.paragraphs,
                )
                state = accum.get(block.id)
                content_hash = _hash_paragraphs(rebuilt.paragraphs)
                if state is None:
                    if block.id not in first_seen:
                        first_seen[block.id] = first_seen_counter
                        first_seen_counter += 1
                    accum[block.id] = {
                        "block_type": block.block_type,
                        "title": block.title,
                        "versions": [rebuilt],
                        "last_hash": content_hash,
                    }
                    continue
                if state["last_hash"] == content_hash:
                    # Same content as previous expression — skip to avoid
                    # creating a no-op commit downstream.
                    continue
                state["versions"].append(rebuilt)
                state["last_hash"] = content_hash
                # Refresh display title with the newest non-empty heading
                if block.title and block.title.strip():
                    state["title"] = block.title

        # Emit blocks in the order they were first seen
        ordered_ids = sorted(first_seen, key=first_seen.get)
        merged: list[Block] = []
        for bid in ordered_ids:
            state = accum[bid]
            merged.append(
                Block(
                    id=bid,
                    block_type=state["block_type"],
                    title=state["title"],
                    versions=tuple(state["versions"]),
                )
            )
        return merged

    def extract_reforms(self, data: bytes) -> list[Any]:
        """Derive reforms from the merged Version list of every block.

        The multi-expression path builds multi-Version blocks, so the default
        :func:`legalize.transformer.xml_parser.extract_reforms` groups them
        into one :class:`Reform` per unique ``(date, norm_id)`` pair.
        """
        return super().extract_reforms(data)


# ─────────────────────────────────────────────
# Metadata parser
# ─────────────────────────────────────────────


# Map ``wetgeving/@soort`` to internal rank strings.
_SOORT_TO_RANK: dict[str, str] = {
    "wet": "wet",
    "rijkswet": "rijkswet",
    "AMvB": "amvb",
    "rijksAMvB": "rijks_amvb",
    "ministeriele-regeling": "ministeriele_regeling",
    "ministeriele-regeling-archiefselectielijst": "archiefselectielijst",
    "ministeriele-regeling-BES": "ministeriele_regeling_bes",
    "KB": "kb",
    "rijksKB": "rijks_kb",
    "verdrag": "verdrag",
    "zbo": "zbo",
    "pbo": "pbo",
    "beleidsregel": "beleidsregel",
    "beleidsregel-BES": "beleidsregel_bes",
    "circulaire": "circulaire",
    "circulaire-BES": "circulaire_bes",
    "reglement": "reglement",
    "wet-BES": "wet_bes",
    "AMvB-BES": "amvb_bes",
}

# Rank override for well-known constitutional document identifiers
_SPECIAL_RANKS: dict[str, str] = {
    "BWBR0001840": "grondwet",  # Grondwet
}


DEFAULT_PORTAL_URL = "https://wetten.overheid.nl"


def _extract_publication(pub_el: etree._Element | None) -> dict[str, str]:
    """Extract a ``<publicatie>`` child block into a flat dict."""
    if pub_el is None:
        return {}
    out: dict[str, str] = {}
    for attr in ("effect", "soort", "urlidentifier"):
        v = pub_el.get(attr)
        if v:
            out[attr] = v
    for tag in ("publicatiejaar", "publicatienr", "uitgiftedatum", "ondertekeningsdatum"):
        el = pub_el.find(tag)
        if el is not None:
            if el.get("isodatum"):
                out[tag] = el.get("isodatum", "")
            elif el.text:
                out[tag] = el.text.strip()
    dossier = pub_el.find("dossierref")
    if dossier is not None:
        out["dossier"] = dossier.get("dossier") or (dossier.text or "").strip()
    return out


def _format_publication(d: dict[str, str]) -> str:
    """Format a publicatie dict as ``Stb.YYYY/NNN`` style reference."""
    soort = d.get("soort") or "Stb"
    jaar = d.get("publicatiejaar") or ""
    nr = d.get("publicatienr") or ""
    if jaar and nr:
        return f"{soort}.{jaar}-{nr}"
    return d.get("urlidentifier") or ""


class BWBMetadataParser(MetadataParser):
    """Parses a BWB toestand XML into NormMetadata.

    Captures every metadata field the source exposes:
    - ``toestand`` root attributes (identifier, current expression date)
    - ``wetgeving`` attributes (type, version IDs, original entry-into-force)
    - ``intitule`` full title + per-element reform tracking (bron, effect, signatures)
    - ``citeertitel`` short title + its reform tracking
    - ``wetgeving/meta-data/brondata`` publication history (original gazette
      reference, signing date, entry into force, dossier number)
    - JCI canonical URIs (versie 1.0 and 1.3)

    Everything that does not fit :class:`NormMetadata`'s dataclass fields is
    pushed into ``extra`` with English snake_case keys.
    """

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        envelope = _parse_xml(data)
        if envelope is None:
            raise ValueError(f"Cannot parse BWB XML for {norm_id}")

        # When the envelope is a multi-expression bundle, always use the
        # *latest* expression for the norm metadata so the frontmatter
        # reflects the current title/short_title/status.
        tag = etree.QName(envelope.tag).localname if isinstance(envelope.tag, str) else ""
        if tag == "bwb-multi-expression":
            expressions = envelope.findall("expression")
            if not expressions:
                raise ValueError(f"Empty multi-expression envelope for {norm_id}")
            last_exp = expressions[-1]
            toestand = last_exp.find("toestand")
            if toestand is None:
                raise ValueError(f"No toestand in latest expression for {norm_id}")
            root = toestand
        else:
            root = envelope

        wet = root.find("wetgeving")
        if wet is None:
            raise ValueError(f"No <wetgeving> element in {norm_id}")

        # Identifier: prefer the top-level bwb-id attribute; fall back to arg
        identifier = root.get("bwb-id") or norm_id

        # Titles
        intitule = wet.find("intitule")
        citeertitels = wet.findall("citeertitel")
        primary_cite: etree._Element | None = None
        for c in citeertitels:
            if c.get("status") == "officieel":
                primary_cite = c
                break
        if primary_cite is None and citeertitels:
            primary_cite = citeertitels[0]

        title = _inline_text(intitule).rstrip(".") if intitule is not None else ""
        short_title = _inline_text(primary_cite) if primary_cite is not None else ""
        if not title:
            title = short_title or identifier
        if not short_title:
            short_title = title

        # Alternative citation titles (non-official forms)
        alt_titles = [_inline_text(c) for c in citeertitels if c is not primary_cite]
        alt_titles = [t for t in alt_titles if t and t != short_title]

        # Rank (source-native "soort" first, then special-case overrides)
        soort = wet.get("soort") or ""
        rank_str = _SPECIAL_RANKS.get(identifier) or _SOORT_TO_RANK.get(
            soort, soort.replace("-", "_") if soort else "otro"
        )

        # Publication date — effective date of the current expression
        pub_date = _root_pub_date(root)

        # Status: the toestand alone does not tell us if a future expression
        # repeals the law, so we default to in_force. The daily SRU sweep and
        # ``legalize health`` will correct stale statuses over time.
        status = NormStatus.IN_FORCE

        # ── Original publication block (from wetgeving/meta-data/brondata) ──
        original_pub = _extract_publication(
            wet.find("meta-data/brondata/oorspronkelijk/publicatie")
        )
        iw_pub = _extract_publication(wet.find("meta-data/brondata/inwerkingtreding/publicatie"))
        iw_datum_el = wet.find("meta-data/brondata/inwerkingtreding/inwerkingtreding.datum")
        iw_datum = iw_datum_el.get("isodatum") if iw_datum_el is not None else ""

        # JCI canonical URIs
        jcis = wet.findall("meta-data/jcis/jci")
        jci_13 = next((j for j in jcis if j.get("versie") == "1.3"), None)
        jci_10 = next((j for j in jcis if j.get("versie") == "1.0"), None)

        # ── Build the extra tuple: every remaining field goes here ──
        extra: list[tuple[str, str]] = []

        def _push(key: str, value: str | None) -> None:
            if value:
                extra.append((key, str(value).strip()[:500]))

        # wetgeving / toestand attributes
        _push("soort", soort)
        _push("stam_id", wet.get("stam-id"))
        _push("version_id", wet.get("versie-id"))
        _push("internal_id", wet.get("id"))
        _push("label_id", wet.get("label-id"))
        _push("dtd_version", wet.get("dtdversie"))
        _push("original_entry_into_force", wet.get("inwerkingtredingsdatum"))
        _push("toestand_uri", root.get("bwb-ng-vast-deel"))

        # intitule attributes
        if intitule is not None:
            _push("intitule_bron", intitule.get("bron"))
            _push("intitule_effect", intitule.get("effect"))
            _push("intitule_signed", intitule.get("ondertekening_bron"))
            _push("intitule_published", intitule.get("publicatie_bron"))
            _push("intitule_in_force", intitule.get("publicatie_iwt"))
            _push("intitule_status", intitule.get("status"))

        # Original publication (from the top-level brondata)
        orig_ref = _format_publication(original_pub)
        _push("original_publication", orig_ref)
        _push("original_signed_date", original_pub.get("ondertekeningsdatum"))
        _push("original_published_date", original_pub.get("uitgiftedatum"))
        _push("original_effect", original_pub.get("effect"))
        _push("original_dossier", original_pub.get("dossier"))
        _push("original_url_id", original_pub.get("urlidentifier"))
        _push("entry_into_force_date", iw_datum)
        _push("entry_into_force_dossier", iw_pub.get("dossier"))

        # Canonical JCI URIs
        if jci_13 is not None:
            _push("jci_1_3", jci_13.get("verwijzing"))
        if jci_10 is not None:
            _push("jci_1_0", jci_10.get("verwijzing"))

        # Citation title metadata
        if primary_cite is not None:
            _push("citeertitel_status", primary_cite.get("status"))
        if alt_titles:
            _push("alternative_titles", " | ".join(alt_titles)[:500])

        # Short title exposed as a dedicated frontmatter field when it differs
        if short_title and short_title != title:
            _push("short_title", short_title)

        # Legacy/compat field names (to make web sync happy without extra code)
        _push("signed_date", original_pub.get("ondertekeningsdatum"))
        _push("entry_into_force", iw_datum or original_pub.get("uitgiftedatum") or "")

        # Source URL: canonical portal link
        source_url = f"{DEFAULT_PORTAL_URL}/{identifier}"

        last_modified = _parse_iso_date(iw_datum) or _parse_iso_date(
            original_pub.get("uitgiftedatum")
        )

        return NormMetadata(
            title=title,
            short_title=short_title or title,
            identifier=identifier,
            country="nl",
            rank=Rank(rank_str),
            publication_date=pub_date,
            status=status,
            department="",  # populated by the discovery layer via SRU
            source=source_url,
            last_modified=last_modified,
            pdf_url=None,
            subjects=(),
            summary="",
            extra=tuple(extra),
        )
