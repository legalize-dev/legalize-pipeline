"""Parser for the Polish Sejm ELI API.

Two parsers:
- EliTextParser: walks the semantic HTML returned by /acts/{eli}/text.html.
- EliMetadataParser: parses the JSON returned by /acts/{eli}.

The HTML uses a stable ``unit unit_XXXX`` class taxonomy (see RESEARCH-POLAND.md
§6.1 for the full mapping). Top-level content sits inside ``<div class="parts">``.

Structural hierarchy (Polish name → internal block_type):
    part (część), ksga (księga), tytu (tytuł), dzia (dział),
    chpt (rozdział), oddz (oddział)           → heading blocks
    arti (artykuł)                             → article block
    pass (ustęp), pint (punkt),
    lett (litera), tire (tiret)                → nested list items inside articles
    para (§)                                   → rare, treated like arti

Content constructs handled inside article bodies:
    <div data-template="xText" class="pro-text">   → regular paragraph
    <B>, <strong>                                  → bold (pre-wrapped **...**)
    <I>, <em>                                      → italic (pre-wrapped *...*)
    <a class="pro-lexlink" href="...">             → Markdown link
    <span class="pro-lexlink">                     → inline text (no link available)
    <div class="cite-box">                         → blockquote (quoted amending text)
    <TABLE>...</TABLE>                             → Markdown pipe table
    <ul>/<ol>                                      → Markdown list
    <sup>                                          → keep as "^text^" inline
    class="toc"/"tooltip"/"gloss"/"xHidden"        → stripped as UI noise
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
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
    Version,
)
from legalize.fetcher._tables import render_table
from legalize.fetcher._text import strip_control

logger = logging.getLogger(__name__)

_HTML_PARSER = lxml_html.HTMLParser(encoding="utf-8")


# ─────────────────────────────────────────────
# Helpers: text, dates, classes
# ─────────────────────────────────────────────

_WS_RE = re.compile(r"\s+")


def _clean_text(text: str) -> str:
    """Normalize whitespace, replace NBSP, strip control chars."""
    if not text:
        return ""
    text = text.replace("\xa0", " ").replace("\u2003", " ")
    text = strip_control(text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def _get_classes(el) -> set[str]:
    cls = el.get("class") or ""
    return set(cls.split())


def _has_class(el, css_class: str) -> bool:
    return css_class in _get_classes(el)


# CSS classes to strip from the body (UI noise, not legal text)
_STRIP_CLASSES = frozenset(
    {
        "toc",
        "tooltip",
        "tooltip-text",
        "gloss",
        "gloss-section",
        "gloss-link",
        "pro-gloss-inner",
        "xHidden",
        "hidden",
        "show-all",
    }
)


def _strip_descendants_with_classes(el, classes: frozenset[str]) -> None:
    """Remove descendant elements whose class intersects ``classes``.

    Preserves tail text so surrounding prose stays intact.
    """
    targets = []
    for descendant in el.xpath(".//*[@class]"):
        if _get_classes(descendant) & classes:
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


# ─────────────────────────────────────────────
# Norm_id marker (injected by the client)
# ─────────────────────────────────────────────

_MARKER_RE = re.compile(rb"<!--LEGALIZE norm_id=([A-Za-z0-9_-]+) pub_date=(\d{4}-\d{2}-\d{2})?-->")


def _extract_marker(data: bytes) -> tuple[str, date | None]:
    """Read the norm_id + pub_date marker injected by EliClient.get_text().

    Falls back to ("unknown", None) if the marker is missing (e.g., direct
    parser test on a fixture without going through the client).
    """
    m = _MARKER_RE.search(data[:300])
    if not m:
        return "unknown", None
    norm_id = m.group(1).decode()
    pub_date_str = m.group(2)
    pub_date: date | None = None
    if pub_date_str:
        try:
            pub_date = date.fromisoformat(pub_date_str.decode())
        except ValueError:
            pub_date = None
    return norm_id, pub_date


# ─────────────────────────────────────────────
# Rank mapping
# ─────────────────────────────────────────────


def _normalize_rank_name(name: str) -> str:
    """Convert Polish act type ("Rozporządzenie Rady Ministrów") → snake_case ASCII."""
    if not name:
        return "otro"
    # Strip diacritics
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    ascii_only = ascii_only.lower()
    # Drop anything that is not a-z or whitespace
    ascii_only = re.sub(r"[^a-z\s]+", " ", ascii_only)
    tokens = ascii_only.split()
    if not tokens:
        return "otro"
    # Use only the head noun (first token) for the canonical rank.
    return _HEAD_TO_RANK.get(tokens[0], tokens[0])


_HEAD_TO_RANK: dict[str, str] = {
    "konstytucja": "konstytucja",
    "ustawa": "ustawa",
    "rozporzadzenie": "rozporzadzenie",
    "obwieszczenie": "obwieszczenie",
    "uchwala": "uchwala",
    "zarzadzenie": "zarzadzenie",
    "postanowienie": "postanowienie",
    "decyzja": "decyzja",
    "umowa": "umowa_miedzynarodowa",
    "protokol": "umowa_miedzynarodowa",
    "kodeks": "kodeks",
    "dekret": "dekret",
    "orzeczenie": "orzeczenie",
    "wyrok": "wyrok",
    "komunikat": "komunikat",
    "oswiadczenie": "oswiadczenie",
}


_STATUS_MAP: dict[str, NormStatus] = {
    "IN_FORCE": NormStatus.IN_FORCE,
    "REPEALED": NormStatus.REPEALED,
    "PARTIALLY_REPEALED": NormStatus.PARTIALLY_REPEALED,
    "ANNULLED": NormStatus.ANNULLED,
    "EXPIRED": NormStatus.EXPIRED,
    "NOT_IN_FORCE": NormStatus.EXPIRED,
    "UCHYLONY": NormStatus.REPEALED,
}


# ─────────────────────────────────────────────
# Inline text extraction (bold/italic/links)
# ─────────────────────────────────────────────


def _inline_text(el, *, in_bold: bool = False, in_italic: bool = False) -> str:
    """Flatten an element's descendants to a single string, pre-wrapping

    <b>/<strong> in ``**...**`` and <i>/<em> in ``*...*``. Handles both lower
    and uppercase tags (Sejm HTML mixes cases).

    <a class="pro-lexlink"> becomes a Markdown link; bare <span class="pro-lexlink">
    is kept as plain text (the Sejm didn't provide a link target, so nothing to
    render).

    UI classes (tooltip, xHidden, gloss, ...) are skipped entirely.
    """
    if el is None:
        return ""

    parts: list[str] = []

    # Skip stripped UI nodes whole — including their tails, since the caller
    # will handle continuation.
    if _get_classes(el) & _STRIP_CLASSES:
        return ""

    # Handle the element's own text
    if el.text:
        parts.append(el.text)

    for child in el.iterchildren():
        ctag = (child.tag or "").lower() if isinstance(child.tag, str) else ""
        cclasses = _get_classes(child)

        if cclasses & _STRIP_CLASSES:
            # Skip child but preserve the tail text
            if child.tail:
                parts.append(child.tail)
            continue

        inner = _inline_text(child, in_bold=in_bold, in_italic=in_italic)

        if ctag in ("b", "strong"):
            if inner.strip() and not in_bold:
                parts.append(f"**{inner.strip()}**")
            else:
                parts.append(inner)
        elif ctag in ("i", "em"):
            if inner.strip() and not in_italic:
                parts.append(f"*{inner.strip()}*")
            else:
                parts.append(inner)
        elif ctag == "a":
            href = child.get("href") or ""
            text = inner.strip()
            if href and text:
                # Absolutize relative Sejm URLs
                if href.startswith("/"):
                    href = f"https://api.sejm.gov.pl{href}"
                parts.append(f"[{text}]({href})")
            else:
                parts.append(inner)
        elif ctag == "sup":
            if inner.strip():
                parts.append(f"^{inner.strip()}^")
        elif ctag == "br":
            parts.append(" ")
        else:
            parts.append(inner)

        if child.tail:
            parts.append(child.tail)

    return "".join(parts)


def _element_text(el) -> str:
    """Cleaned concatenation of an element's text content."""
    return _clean_text(_inline_text(el))


# ─────────────────────────────────────────────
# Table → Markdown
# ─────────────────────────────────────────────


def _find_real_table(wrapper) -> Any | None:
    """The Sejm wraps real tables in an outer 1-cell layout <TABLE>.

    Given any <TABLE> element, return the innermost table that actually holds
    multiple rows of real content. Returns None if the wrapper has no real
    table inside.
    """

    # A "real" table has at least 1 row with more than 1 cell, or a TBODY.
    def is_real(t) -> bool:
        rows = [r for r in t.iter() if (r.tag or "").lower() == "tr"]
        if not rows:
            return False
        for r in rows:
            cells = [c for c in r if (c.tag or "").lower() in ("td", "th")]
            if len(cells) > 1:
                return True
        return False

    if is_real(wrapper):
        # Check for a nested table that is "more real" (common pattern).
        inner_tables = [
            t for t in wrapper.iter() if (t.tag or "").lower() == "table" and t is not wrapper
        ]
        for inner in inner_tables:
            if is_real(inner):
                return inner
        return wrapper

    inner_tables = [
        t for t in wrapper.iter() if (t.tag or "").lower() == "table" and t is not wrapper
    ]
    for inner in inner_tables:
        if is_real(inner):
            return inner
    return None


def _table_to_markdown(table_el) -> str:
    """Convert a real <TABLE> element to a Markdown pipe table.

    Returns an empty string if the table has no parseable rows.
    """
    return render_table(table_el, lambda cell: _element_text(cell) or "")


# ─────────────────────────────────────────────
# Article body rendering
# ─────────────────────────────────────────────


# unit class → depth prefix inside an article body
_UNIT_DEPTH: dict[str, str] = {
    "unit_pass": "",  # e.g. "1. ..."
    "unit_pint": "  ",  # e.g. "  1) ..."
    "unit_lett": "    ",  # e.g. "    a) ..."
    "unit_tire": "      ",  # e.g. "      – ..."
}


def _unit_marker(unit_class: str, num: str) -> str:
    """Marker for nested units: '1.', '1)', 'a)', '–'."""
    if unit_class == "unit_pass":
        return f"{num}. " if num else ""
    if unit_class == "unit_pint":
        return f"{num}) " if num else ""
    if unit_class == "unit_lett":
        return f"{num}) " if num else ""
    if unit_class == "unit_tire":
        return "– "
    return ""


def _render_article_body(article_el) -> list[Paragraph]:
    """Walk the article's unit-inner and emit paragraphs in reading order.

    Strategy:
    - Direct text children (``<div data-template="xText">``) → parrafo
    - Nested units (pass/pint/lett/tire) → list_item with indent + marker
    - Tables → one table paragraph
    - Cite-boxes → multi-line blockquote paragraph
    """
    paragraphs: list[Paragraph] = []
    # Mark already-emitted xText elements (the "first xText" consumed as
    # the marker line of a nested unit) via an attribute on the element
    # itself. A Python-side ``set[int(id(el))]`` does NOT work here because
    # lxml creates HtmlElement proxies lazily and CPython recycles id()
    # values as proxies are garbage-collected between iterations. That bug
    # silently dropped ~43% of nested list items in Poland v1.
    _CONSUMED_ATTR = "_legalize_consumed"

    def walk(el, marker_prefix: str = "") -> None:
        for child in el.iterchildren():
            if child.get(_CONSUMED_ATTR) == "1":
                continue
            ctag = (child.tag or "").lower() if isinstance(child.tag, str) else ""
            cclasses = _get_classes(child)

            if cclasses & _STRIP_CLASSES:
                continue

            # Cite-box → blockquote (stops recursion inside it)
            if "cite-box" in cclasses:
                cite_body = child.xpath('.//div[contains(@class,"cite-body")]')
                target = cite_body[0] if cite_body else child
                inner_text = _element_text(target)
                if inner_text:
                    quoted = "\n".join(f"> {ln}" for ln in inner_text.split("\n") if ln.strip())
                    paragraphs.append(Paragraph(css_class="parrafo", text=quoted))
                continue

            # Real table (TABLE tag, direct or nested)
            if ctag == "table":
                real = _find_real_table(child)
                if real is not None:
                    md = _table_to_markdown(real)
                    if md:
                        paragraphs.append(Paragraph(css_class="table", text=md))
                continue

            # HTML lists (ul/ol) → list_item paragraphs.
            #
            # The Sejm uses <ul data-template="xEnum"> for "tiret" style
            # lists, where each <li> contains TWO pro-text divs: the first
            # is the marker literal (" - ") and the second is the real
            # content. If we naively take _element_text(li) we end up with
            # the dash prepended to the content — and then our own "- "
            # prefix produces "- - content". We also want cite-boxes
            # inside <li> to render as separate blockquote paragraphs
            # rather than being flattened into the item text. Walk each
            # <li> with the existing recursive walker, indented one level
            # deeper than the parent list.
            if ctag in ("ul", "ol"):
                is_xenum = child.get("data-template") == "xEnum"
                li_indent = marker_prefix + "  "
                for idx, li in enumerate(child.iterchildren(), start=1):
                    if (li.tag or "").lower() != "li":
                        continue
                    # Skip the marker-only div (first pro-text div in xEnum
                    # lists contains only whitespace + dash). We do this by
                    # marking it consumed so the recursive walk ignores it.
                    if is_xenum:
                        for gc in li.iterchildren():
                            gtag = (gc.tag or "").lower()
                            if gtag == "div":
                                # A "marker" div has no nested xText / unit / cite-box
                                # — just a short string like " - ".
                                inner = "".join(gc.itertext()).strip()
                                has_structure = bool(
                                    gc.xpath(
                                        './/div[@data-template="xText"] | '
                                        './/div[contains(@class,"cite-box")] | '
                                        './/div[contains(@class,"unit_")]'
                                    )
                                )
                                if not has_structure and len(inner) <= 3:
                                    gc.set(_CONSUMED_ATTR, "1")
                                    break
                    # Take a snapshot of paragraphs emitted so far; the walk
                    # will append new ones for this <li>. We then rewrite
                    # the first new one to carry the list marker.
                    before = len(paragraphs)
                    walk(li, marker_prefix=li_indent)
                    if len(paragraphs) == before:
                        continue
                    first_new = paragraphs[before]
                    dash_prefix = "- " if ctag == "ul" else f"{idx}. "
                    new_text = re.sub(r"^[–\-]\s+", "", first_new.text.lstrip())
                    paragraphs[before] = Paragraph(
                        css_class="list_item",
                        text=f"{li_indent}{dash_prefix}{new_text}",
                    )
                continue

            # Nested structural unit
            unit_class = next((c for c in cclasses if c.startswith("unit_") and c != "unit"), None)
            if unit_class:
                num = child.get("data-id", "") or ""
                h3_list = child.xpath("./h3")
                if h3_list:
                    h3_text = _clean_text("".join(h3_list[0].itertext())).rstrip(".) ")
                    if h3_text:
                        num = h3_text
                marker = _unit_marker(unit_class, num)
                new_indent = marker_prefix + _UNIT_DEPTH.get(unit_class, "")

                inner_list = child.xpath('./div[contains(@class,"unit-inner")]')
                if inner_list:
                    inner_el = inner_list[0]
                    # Find the first direct xText child — that becomes the
                    # "marker line" of this nested unit.
                    first_xtext = None
                    for g in inner_el.iterchildren():
                        if (g.tag or "").lower() == "div" and (
                            "pro-text" in _get_classes(g) or g.get("data-template") == "xText"
                        ):
                            first_xtext = g
                            break
                    if first_xtext is not None:
                        lead = _clean_text(_inline_text(first_xtext))
                        if lead:
                            paragraphs.append(
                                Paragraph(
                                    css_class="list_item",
                                    text=f"{new_indent}{marker}{lead}",
                                )
                            )
                        first_xtext.set(_CONSUMED_ATTR, "1")
                    elif marker:
                        paragraphs.append(
                            Paragraph(
                                css_class="list_item",
                                text=f"{new_indent}{marker}".rstrip(),
                            )
                        )
                    # Recurse — walk() will skip the first xText
                    walk(inner_el, marker_prefix=new_indent)
                else:
                    text = _element_text(child)
                    if text:
                        paragraphs.append(
                            Paragraph(
                                css_class="list_item",
                                text=f"{new_indent}{marker}{text}",
                            )
                        )
                continue

            # Plain text paragraph at this level
            if ctag == "div" and ("pro-text" in cclasses or child.get("data-template") == "xText"):
                # If the div contains structured children (cite-box,
                # nested units, tables), recurse so those become their
                # own paragraphs instead of being flattened inline. This
                # keeps xEnum <li> content properly separated from its
                # cite-box blockquotes.
                has_structure = bool(
                    child.xpath(
                        './/div[contains(@class,"cite-box")] '
                        '| .//div[contains(@class,"unit_")] '
                        "| .//table"
                    )
                )
                if has_structure:
                    walk(child, marker_prefix=marker_prefix)
                    continue
                text = _element_text(child)
                if text:
                    if marker_prefix:
                        paragraphs.append(
                            Paragraph(css_class="list_item", text=f"{marker_prefix}{text}")
                        )
                    else:
                        paragraphs.append(Paragraph(css_class="parrafo", text=text))
                continue

            # Unknown wrapper: recurse
            if ctag in ("div", "section"):
                walk(child, marker_prefix=marker_prefix)

    # Start walking from unit-inner (if present) or article_el directly.
    inner = article_el.xpath('./div[contains(@class,"unit-inner")]')
    if inner:
        walk(inner[0])
    else:
        walk(article_el)

    return paragraphs


# ─────────────────────────────────────────────
# Block factory
# ─────────────────────────────────────────────


def _make_block(
    block_id: str,
    block_type: str,
    title: str,
    paragraphs: list[Paragraph],
    pub_date: date,
    norm_id: str,
) -> Block:
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


# ─────────────────────────────────────────────
# Text parser
# ─────────────────────────────────────────────


# Map heading unit class → block_type + css_class for the rendered heading
_HEADING_UNITS: dict[str, tuple[str, str]] = {
    "unit_part": ("part", "titulo_tit"),
    "unit_ksga": ("book", "titulo_tit"),
    "unit_tytu": ("title", "titulo_tit"),
    "unit_dzia": ("division", "titulo_tit"),
    "unit_chpt": ("chapter", "capitulo_tit"),
    "unit_oddz": ("subsection", "seccion"),
}


class EliTextParser(TextParser):
    """Parses Sejm ELI /text.html into Block objects."""

    def parse_text(self, data: bytes) -> list[Any]:
        if not data:
            return []

        norm_id, marker_date = _extract_marker(data)
        pub_date = marker_date or date(1900, 1, 1)

        try:
            tree = lxml_html.fromstring(data, parser=_HTML_PARSER)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to parse PL HTML for %s: %s", norm_id, exc)
            return []

        # Strip UI noise upfront
        _strip_descendants_with_classes(tree, _STRIP_CLASSES)

        parts_root = tree.xpath('//div[contains(@class,"parts")]')
        if not parts_root:
            # Fallback: use body
            body = tree.xpath("//body")
            if not body:
                return []
            parts_root = body
        root = parts_root[0]

        blocks: list[Block] = []
        counter = 0

        def _emit_heading(block_type: str, text: str, css_class: str) -> None:
            nonlocal counter
            counter += 1
            blocks.append(
                _make_block(
                    block_id=f"{block_type}-{counter}",
                    block_type=block_type,
                    title=text,
                    paragraphs=[Paragraph(css_class=css_class, text=text)],
                    pub_date=pub_date,
                    norm_id=norm_id,
                )
            )

        def _emit_article(unit_el, unit_class: str) -> None:
            nonlocal counter
            data_id = unit_el.get("data-id") or unit_el.get("id") or f"art-{counter}"
            title_lines: list[str] = []
            for hchild in unit_el.iterchildren():
                htag = (hchild.tag or "").lower() if isinstance(hchild.tag, str) else ""
                if htag == "div" and "unit-inner" in _get_classes(hchild):
                    break
                if htag in ("h1", "h2", "h3", "h4", "h5", "h6", "p"):
                    t = _clean_text("".join(hchild.itertext()))
                    if t:
                        title_lines.append(t)
            title = " ".join(title_lines) if title_lines else data_id

            paras = _render_article_body(unit_el)
            if not paras:
                return
            counter += 1
            blocks.append(
                _make_block(
                    block_id=data_id,
                    block_type="article",
                    title=title,
                    paragraphs=[Paragraph(css_class="articulo", text=title)] + paras,
                    pub_date=pub_date,
                    norm_id=norm_id,
                )
            )

        def _emit_standalone_item(unit_el, unit_class: str) -> None:
            """Emit a top-level unit_pass/unit_pint/unit_lett/unit_tire.

            These appear inside Polish załączniki (annexes): the annex is a
            flat list of numbered items with no surrounding unit_arti. Each
            item becomes its own block so nothing is silently dropped.
            """
            nonlocal counter
            data_id = unit_el.get("data-id") or unit_el.get("id") or f"item-{counter}"
            # Extract the visible marker number from the unit's h3 (e.g. "1.")
            num = ""
            h3 = unit_el.xpath("./h3")
            if h3:
                num = _clean_text("".join(h3[0].itertext())).rstrip(".) ")
            marker = _unit_marker(unit_class, num) or f"{num} "

            paras = _render_article_body(unit_el)
            if not paras:
                return
            # Prepend the marker to the first paragraph so the numbering
            # survives. Subsequent paragraphs keep their original formatting.
            first = paras[0]
            new_first = Paragraph(css_class="list_item", text=f"{marker}{first.text}")
            counter += 1
            blocks.append(
                _make_block(
                    block_id=data_id,
                    block_type="item",
                    title=new_first.text[:120],
                    paragraphs=[new_first] + paras[1:],
                    pub_date=pub_date,
                    norm_id=norm_id,
                )
            )

        def _emit_standalone_xtext(xtext_el) -> None:
            """Emit an xText that lives directly inside div.block or div.part.

            These hold things like the ``podstawa prawna`` introductory
            sentence ("Na podstawie art. 48 ust. 2 ustawy..."), which is
            part of the legal record but not wrapped in any structural unit.
            """
            nonlocal counter
            text = _element_text(xtext_el)
            if not text:
                return
            counter += 1
            blocks.append(
                _make_block(
                    block_id=f"preamble-{counter}",
                    block_type="preamble",
                    title=text[:80],
                    paragraphs=[Paragraph(css_class="parrafo", text=text)],
                    pub_date=pub_date,
                    norm_id=norm_id,
                )
            )

        def _emit_part_heading(part_el) -> None:
            """If a <div class="part"> carries an <h2>, emit it as a heading.

            Polish documents use part_1/part_2/part_3 as the top-level
            sectioning with an <h2> title ("Treść ustawy", "Załącznik nr 1
            - Wykaz inwestycji", etc.). Without this, annex titles are lost.
            """
            h2s = part_el.xpath("./h2")
            if not h2s:
                return
            text = _clean_text("".join(h2s[0].itertext()))
            if text:
                _emit_heading("part", text, "titulo_tit")

        def process_unit(el, parent_title: str = "") -> None:
            classes = _get_classes(el)
            unit_class = next((c for c in classes if c.startswith("unit_") and c != "unit"), None)

            if not unit_class:
                # Non-unit container (section / div.part / div.block).
                # Emit an h2 title if present (part_1/part_2/... annex headers)
                # before recursing.
                if el.tag == "div" and "part" in classes and "block" not in classes:
                    _emit_part_heading(el)

                for child in el.iterchildren():
                    ctag = (child.tag or "").lower() if isinstance(child.tag, str) else ""
                    if ctag not in ("div", "section"):
                        continue
                    cclasses = _get_classes(child)
                    # xText directly inside a block container (e.g. podstawa prawna)
                    if child.get("data-template") == "xText" and "pro-text" in cclasses:
                        _emit_standalone_xtext(child)
                        continue
                    process_unit(child)
                return

            # Article (unit_arti) or § (unit_para)
            if unit_class in ("unit_arti", "unit_para"):
                _emit_article(el, unit_class)
                return

            # Heading units (part/chpt/dzia/tytu/ksga/oddz)
            if unit_class in _HEADING_UNITS:
                block_type, css_class = _HEADING_UNITS[unit_class]
                heading_text = _heading_text_of_unit(el)
                if heading_text:
                    _emit_heading(block_type, heading_text, css_class)
                inner = el.xpath('./div[contains(@class,"unit-inner")]')
                if inner:
                    for child in inner[0].iterchildren():
                        if (child.tag or "").lower() in ("div", "section"):
                            process_unit(child)
                return

            # Top-level list-like units (inside annexes, not articles)
            if unit_class in ("unit_pass", "unit_pint", "unit_lett", "unit_tire"):
                _emit_standalone_item(el, unit_class)
                return

            # Unknown unit_* — recurse into inner
            inner = el.xpath('./div[contains(@class,"unit-inner")]')
            if inner:
                for child in inner[0].iterchildren():
                    if (child.tag or "").lower() in ("div", "section"):
                        process_unit(child)

        # Walk the top level (<section> wrappers under div.parts)
        for section in root.iterchildren():
            if (section.tag or "").lower() == "section":
                for child in section.iterchildren():
                    if (child.tag or "").lower() in ("div", "section"):
                        process_unit(child)
            elif (section.tag or "").lower() == "div":
                process_unit(section)

        # Second pass: annex tables.
        #
        # Polish regulations often carry their tables in an annex part
        # ("Załącznik") which contains a malformed <TABLE> wrapper (without
        # a parent <table>, sometimes as bare <TR>/<TD>). lxml re-parents
        # these, so the tables end up as top-level nodes outside any unit.
        # We collect every non-nested <table> that is NOT already inside a
        # unit we processed and emit it as an annex block.
        processed_tables: set[int] = set()
        # Mark tables inside cite-boxes / units as already processed
        for t in root.iter():
            if (t.tag or "").lower() != "table":
                continue
            anc = t.getparent()
            while anc is not None:
                if _get_classes(anc) & {"cite-box", "cite-body"}:
                    processed_tables.add(id(t))
                    break
                anc = anc.getparent()

        annex_counter = 0
        for t in root.iter():
            if (t.tag or "").lower() != "table":
                continue
            if id(t) in processed_tables:
                continue
            # Only keep the outermost table of a nested chain
            anc = t.getparent()
            nested_in_table = False
            while anc is not None:
                if (anc.tag or "").lower() == "table":
                    nested_in_table = True
                    break
                anc = anc.getparent()
            if nested_in_table:
                continue

            # Find the innermost "real" table and convert it
            real = _find_real_table(t)
            if real is None:
                continue
            md = _table_to_markdown(real)
            if not md:
                continue
            annex_counter += 1
            counter += 1
            # Try to pick up a nearby <h2> as the annex title
            annex_title = "Załącznik"
            prev = t.getparent()
            if prev is not None:
                h2s = prev.xpath("./preceding::h2[1]")
                if h2s:
                    h2_text = _clean_text("".join(h2s[0].itertext()))
                    if h2_text:
                        annex_title = h2_text
            blocks.append(
                _make_block(
                    block_id=f"annex-{annex_counter}",
                    block_type="annex",
                    title=annex_title,
                    paragraphs=[
                        Paragraph(css_class="titulo_tit", text=annex_title),
                        Paragraph(css_class="table", text=md),
                    ],
                    pub_date=pub_date,
                    norm_id=norm_id,
                )
            )
            # Mark all descendants as processed so inner tables don't get double-emitted
            for desc in t.iter():
                processed_tables.add(id(desc))

        return blocks

    def extract_reforms(self, data: bytes) -> list[Any]:
        """Poland v1 does not track per-law reforms (see RESEARCH-POLAND.md §2.4).

        Falls back to the generic extractor which groups by (pub_date, norm_id).
        All blocks emitted by parse_text share the same pub_date + norm_id, so
        the generic extractor returns a single Reform representing the bootstrap.
        """
        from legalize.transformer.xml_parser import extract_reforms as generic

        return generic(self.parse_text(data))


def _heading_text_of_unit(unit_el) -> str:
    """Extract the visible heading text of a heading unit (part/chpt/dzia/…).

    The Sejm serves HTML like:
        <h3>
          <P ALIGN="center">Rozdział 1</P>
          <P ALIGN="center"><B>Przepisy ogólne</B></P>
        </h3>

    But HTML5 parsers (lxml) close <h3> on the first encountered <p>, leaving
    the <p> elements as siblings of the (now empty) <h3>. So we walk the
    direct children of the unit and collect text until we hit the
    ``unit-inner`` div.
    """
    lines: list[str] = []
    for child in unit_el.iterchildren():
        ctag = (child.tag or "").lower() if isinstance(child.tag, str) else ""
        if ctag == "div" and "unit-inner" in _get_classes(child):
            break
        if ctag in ("h1", "h2", "h3", "h4", "h5", "h6", "p"):
            # Strip markdown markers from heading text so the rendered
            # heading is plain.
            raw = "".join(child.itertext())
            t = _clean_text(raw)
            if t:
                lines.append(t)
    return ". ".join(lines)


# ─────────────────────────────────────────────
# Metadata parser
# ─────────────────────────────────────────────


def _parse_iso_date(s: Any) -> date | None:
    if not s or not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _parse_iso_datetime(s: Any) -> date | None:
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


class EliMetadataParser(MetadataParser):
    """Parses the JSON returned by /acts/{eli} into NormMetadata."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        if not data:
            raise ValueError(f"Empty metadata for {norm_id}")

        try:
            meta = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid metadata JSON for {norm_id}: {exc}") from exc

        title = _clean_text(str(meta.get("title") or ""))
        if not title:
            title = f"Norm {norm_id}"

        # Rank
        type_name = str(meta.get("type") or "").strip()
        rank_str = _normalize_rank_name(type_name)
        # Special case: the Konstytucja is filed as "Ustawa" in the API
        if str(meta.get("ELI") or "") == "DU/1997/483":
            rank_str = "konstytucja"

        # Status
        in_force = str(meta.get("inForce") or "").strip().upper()
        status = _STATUS_MAP.get(in_force, NormStatus.IN_FORCE)

        # Dates
        pub_date = _parse_iso_date(meta.get("announcementDate")) or date(1900, 1, 1)
        last_modified = _parse_iso_datetime(meta.get("changeDate"))

        # Department (releasedBy is a list)
        released_by = meta.get("releasedBy") or []
        department = ", ".join(str(x) for x in released_by) if released_by else ""

        # Subjects from keywords
        keywords = meta.get("keywords") or []
        subjects = tuple(_clean_text(str(k)) for k in keywords if k)

        # Source / pdf url
        eli = str(meta.get("ELI") or norm_id.replace("-", "/"))
        source_url = f"https://api.sejm.gov.pl/eli/acts/{eli}"
        pdf_url = (
            f"https://api.sejm.gov.pl/eli/acts/{eli}/text.pdf" if meta.get("textPDF") else None
        )

        # Build extra (every field the API exposes that we didn't store above)
        extra: list[tuple[str, str]] = []

        def add(key: str, value: Any, *, cap: int = 500) -> None:
            if value is None:
                return
            if isinstance(value, bool):
                # Serialize as YAML-canonical lowercase so downstream
                # consumers get a real boolean, not the Python repr "True".
                extra.append((key, "true" if value else "false"))
            elif isinstance(value, str):
                cleaned = _clean_text(value)
                if cleaned:
                    extra.append((key, cleaned[:cap]))
            elif isinstance(value, (int, float)):
                extra.append((key, str(value)))
            elif isinstance(value, list):
                if not value:
                    return
                if all(isinstance(v, str) for v in value):
                    joined = ", ".join(_clean_text(v) for v in value if v)
                    if joined:
                        extra.append((key, joined[:cap]))
                else:
                    # List of dicts — store count and a compact summary
                    extra.append((f"{key}_count", str(len(value))))
            elif isinstance(value, dict):
                if value:
                    extra.append((f"{key}_count", str(len(value))))

        add("eli", eli)
        add("display_address", meta.get("displayAddress"))
        add("internal_address", meta.get("address"))
        add("publisher", meta.get("publisher"))
        add("volume", meta.get("volume"))
        add("position", meta.get("pos"))
        add("status_pl", meta.get("status"))
        add("promulgation_date", meta.get("promulgation"))
        add("entry_into_force", meta.get("entryIntoForce"))
        add("valid_from", meta.get("validFrom"))
        add("legal_status_date", meta.get("legalStatusDate"))
        add("authorized_body", meta.get("authorizedBody"))
        add("obligated_bodies", meta.get("obligated"))
        add("named_entities", meta.get("keywordsNames"))
        add("previous_titles", meta.get("previousTitle"))
        add("effective_date_notes", meta.get("comments"), cap=1000)
        add("eu_directives", meta.get("directives"))
        add("parliamentary_prints", meta.get("prints"))
        add("references", meta.get("references"))
        add("text_variants", meta.get("texts"))
        add("has_pdf", meta.get("textPDF"))

        # Mirror fields that the generic transformer/frontmatter.py
        # renderer does NOT serialize (subjects, pdf_url, summary) into
        # ``extra`` so they still reach the final YAML. Without this,
        # ~24 keywords on the Civil Protection Act were silently dropped
        # in the first quality gate.
        if subjects:
            joined_subjects = ", ".join(subjects)
            if joined_subjects:
                extra.append(("keywords", joined_subjects[:500]))
        if pdf_url:
            extra.append(("pdf_url", pdf_url))

        return NormMetadata(
            title=title,
            short_title=title,
            identifier=norm_id,
            country="pl",
            rank=Rank(rank_str),
            publication_date=pub_date,
            status=status,
            department=department,
            source=source_url,
            last_modified=last_modified,
            pdf_url=pdf_url,
            subjects=subjects,
            extra=tuple(extra),
        )
