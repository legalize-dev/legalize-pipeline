"""Generic HTML/XML table → Markdown pipe-table renderer.

Shared across country parsers. Accepts any <table>/<tr>/<td>/<th> subtree
(lowercase OR uppercase tags) and emits a well-formed Markdown pipe table.
Handles rowspan/colspan by repeating cell content into the expanded grid.

Cell content is extracted via a caller-supplied inline extractor so that
sup/sub/bold/italic/links survive into the cell text.
"""

from __future__ import annotations

import re
from typing import Callable

from lxml import etree

_LEADING_DIGITS = re.compile(r"\d+")


def _span(element, name: str) -> int:
    """A span attribute, from sources that do not always quote it.

    An unquoted ``rowspan=2>`` leaves lxml recovering the rest of the row as the
    attribute value — "2></td><td style='" — and a bare int() on that raised, which
    lost the whole norm rather than one table. Read the leading digits and move on.
    """
    raw = element.get(name) or element.get(name.upper()) or ""
    match = _LEADING_DIGITS.match(raw.strip())
    if not match:
        return 1
    return max(1, min(int(match.group()), 1000))


def _cells_of(tr) -> list[tuple[etree._Element, int, int]]:
    out: list[tuple[etree._Element, int, int]] = []
    for child in tr:
        tag = (child.tag or "").lower() if isinstance(child.tag, str) else ""
        if tag not in ("td", "th"):
            continue
        out.append((child, _span(child, "colspan"), _span(child, "rowspan")))
    return out


def render_table(
    table_el: etree._Element,
    cell_extractor: Callable[[etree._Element], str],
) -> str:
    """Render a table subtree to a Markdown pipe table.

    Args:
        table_el: lxml element whose local-name is 'table' (any case).
        cell_extractor: function that turns a <td>/<th> element into the
            flat string that should appear inside the pipe cell. Must
            already handle inline formatting (bold/italic/sup/sub) and
            escape `|` characters.

    Returns:
        Markdown pipe table as a single string (no trailing newline) —
        empty string if the table has no cells.
    """
    # Detect <thead> for header row — fall back to first row otherwise
    head_row_idx = -1
    raw_rows: list[list[tuple[str, int, int]]] = []
    for tr in _rows_of(table_el):
        tag = (tr.tag or "").lower() if isinstance(tr.tag, str) else ""
        if tag != "tr":
            continue
        cells = _cells_of(tr)
        if not cells:
            continue
        # Is this row under a <thead>?
        anc = tr.getparent()
        while anc is not None and isinstance(anc.tag, str):
            if anc.tag.lower() == "thead":
                head_row_idx = len(raw_rows)
                break
            anc = anc.getparent()
        raw_rows.append([(cell_extractor(cell), cs, rs) for cell, cs, rs in cells])

    if not raw_rows:
        return ""

    # Expand rowspan/colspan into a 2D grid
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

    # Pad to max width
    width = max(len(r) for r in expanded)
    for r in expanded:
        while len(r) < width:
            r.append("")

    # Markdown pipe tables require a header row; the source often has none.
    # Promoting the first row of data was losing it as data — 250 of 543
    # sampled tables — and a borderless layout table (the BOE uses them for
    # side-by-side signature blocks) has no header by definition.
    if head_row_idx < 0:
        header = [""] * width
        body = expanded
    else:
        header = expanded[head_row_idx]
        body = [r for r in expanded if r is not header]

    lines = ["| " + " | ".join(_clean(c) for c in header) + " |"]
    lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
    for r in body:
        lines.append("| " + " | ".join(_clean(c) for c in r) + " |")

    caption = _caption_of(table_el, cell_extractor)
    if caption:
        return f"{caption}\n\n" + "\n".join(lines)
    return "\n".join(lines)


def _rows_of(table_el: etree._Element):
    """Every <tr> of *this* table, not of the tables inside its cells.

    ``iter()`` walked the whole subtree, so a nested table's rows were spliced
    into the outer grid and padded to the wider of the two.
    """
    for child in table_el:
        if not isinstance(child.tag, str):
            continue
        tag = child.tag.lower()
        if tag == "tr":
            yield child
        elif tag in ("thead", "tbody", "tfoot"):
            for tr in child:
                if isinstance(tr.tag, str) and tr.tag.lower() == "tr":
                    yield tr


def _caption_of(
    table_el: etree._Element,
    cell_extractor: Callable[[etree._Element], str],
) -> str:
    """The table's own title, emitted as the paragraph above it."""
    for child in table_el:
        if isinstance(child.tag, str) and child.tag.lower() == "caption":
            return _clean(cell_extractor(child))
    return ""


def _clean(text: str) -> str:
    """Cell text cleanup — single-line, pipe-escaped."""
    text = text.replace("\r", " ").replace("\n", " ").strip()
    text = text.replace("|", "\\|")
    while "  " in text:
        text = text.replace("  ", " ")
    return text
