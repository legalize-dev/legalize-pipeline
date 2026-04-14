"""Text and metadata parsers for Slovak Slov-Lex legislation.

Parses semantic HTML from the static.slov-lex.sk portal into
Block/Version/Paragraph and NormMetadata.

The HTML uses CSS classes to denote legislative structure:
  predpis > hlava > oddiel > paragraf/clanok/ustavnyclanok > odsek > pismeno > bod
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from lxml import etree

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import Block, NormMetadata, NormStatus, Paragraph, Rank, Version

logger = logging.getLogger(__name__)

# C0/C1 control characters to strip (keep \n, \r, \t).
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Non-breaking space → regular space
_NBSP = re.compile(r"\xa0|&nbsp;")

# ─── CSS class → Markdown rendering ───
# The markdown renderer in transformer/markdown.py maps css_class to output.
# We use the same class names already defined there.
_ELEMENT_MAP: dict[str, str] = {
    # Structural headings
    "predpisTyp": "h1",
    "predpisPodnadpis": "h2",
    "hlavaOznacenie": "h2",
    "hlavaNadpis": "h2",
    "oddielOznacenie": "h3",
    "oddielNadpis": "h3",
    "dielOznacenie": "h4",
    "dielNadpis": "h4",
    "pododdielOznacenie": "h4",
    "pododdielNadpis": "h4",
    # Article-level (Constitution uses ustavnyclanok, regular laws use paragraf/clanok)
    "ustavnyclanokOznacenie": "h5",
    "ustavnyclanokNadpis": "h5",
    "paragrafOznacenie": "h5",
    "paragrafNadpis": "h5",
    "clanokOznacenie": "h5",
    "clanokNadpis": "h5",
    # Body text
    "odsekOznacenie": "num",
    "text": "parrafo",
    "text2": "parrafo",
    "blokTextu": "parrafo",
    # List items
    "pismenoOznacenie": "num",
    "bodOznacenie": "num",
    # Special
    "predpisDatum": "parrafo",
    "citat": "quote",
}

# Classes that are purely structural containers (no text to emit)
_SKIP_CLASSES = frozenset(
    {
        "predpis",
        "hlava",
        "oddiel",
        "diel",
        "pododdiel",
        "ustavnyclanok",
        "paragraf",
        "clanok",
        "odsek",
        "pismeno",
        "bod",
        "Skupina",
        "obsah",
        "NADPIS",
    }
)


def _clean_text(text: str) -> str:
    """Clean raw text extracted from HTML into Markdown-ready text."""
    if not text:
        return ""

    text = _NBSP.sub(" ", text)
    text = _CTRL.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _html_to_text(el: etree._Element) -> str:
    """Extract text from an element, converting inline HTML to Markdown.

    Handles: <b>, <strong> → **bold**
             <a class="citacnyOdkazJednoduchy"> → [text](href)
             <br> → newline
             <table> → Markdown pipe table
    """
    parts: list[str] = []

    def _walk(node: etree._Element, depth: int = 0) -> None:
        tag = etree.QName(node.tag).localname if isinstance(node.tag, str) else ""

        # Tables: convert to Markdown pipe table
        if tag == "table":
            md_table = _html_table_to_markdown(node)
            if md_table:
                parts.append(f"\n\n{md_table}\n\n")
            return

        # Inline formatting
        prefix = ""
        suffix = ""
        if tag in ("b", "strong"):
            prefix = "**"
            suffix = "**"
        elif tag in ("i", "em"):
            prefix = "*"
            suffix = "*"
        elif tag == "a":
            href = node.get("href", "")
            cls = node.get("class", "")
            if "citacnyOdkaz" in cls and href:
                # Cross-reference link
                link_text = (node.text or "") + "".join(
                    etree.tostring(c, method="text", encoding="unicode") for c in node
                )
                link_text = _clean_text(link_text)
                if link_text:
                    parts.append(f"[{link_text}]({href})")
                    if node.tail:
                        parts.append(node.tail)
                    return
        elif tag == "br":
            parts.append("\n")
            if node.tail:
                parts.append(node.tail)
            return
        elif tag == "sup":
            prefix = "^"
            suffix = ""

        if prefix:
            parts.append(prefix)

        if node.text:
            parts.append(node.text)

        for child in node:
            _walk(child, depth + 1)

        if suffix:
            parts.append(suffix)

        if node.tail:
            parts.append(node.tail)

    # Process the element's content
    if el.text:
        parts.append(el.text)
    for child in el:
        _walk(child)

    return "".join(parts)


def _html_table_to_markdown(table_el: etree._Element) -> str:
    """Convert an lxml <table> element to a Markdown pipe table."""
    rows: list[list[str]] = []
    is_header: list[bool] = []

    for tr in table_el.iter("tr"):
        cells: list[str] = []
        row_is_header = False
        for cell in tr:
            tag = etree.QName(cell.tag).localname if isinstance(cell.tag, str) else ""
            if tag == "th":
                row_is_header = True
            content = etree.tostring(cell, method="text", encoding="unicode") or ""
            content = _NBSP.sub(" ", content)
            content = _CTRL.sub("", content)
            content = re.sub(r"\s+", " ", content).strip()
            content = content.replace("|", "\\|")
            cells.append(content)

        if cells:
            rows.append(cells)
            is_header.append(row_is_header)

    if not rows:
        return ""

    max_cols = max(len(r) for r in rows)
    for row in rows:
        while len(row) < max_cols:
            row.append("")

    lines = []
    for i, row in enumerate(rows):
        lines.append("| " + " | ".join(row) + " |")
        if is_header[i] and (i + 1 >= len(rows) or not is_header[i + 1]):
            lines.append("| " + " | ".join("---" for _ in row) + " |")

    if not any(is_header):
        lines.insert(1, "| " + " | ".join("---" for _ in rows[0]) + " |")

    return "\n".join(lines)


def _get_css_class(el: etree._Element) -> str:
    """Extract the primary CSS class from an element.

    Elements have classes like "hlava Skupina" or "odsek Skupina modified".
    We want the first meaningful class (not Skupina, NADPIS, modified, etc.).
    """
    raw = el.get("class", "").strip()
    if not raw:
        return ""
    for cls in raw.split():
        if cls not in _SKIP_CLASSES and cls not in ("modified", "toBeModified", "index_element"):
            return cls
    return ""


class SlovLexTextParser(TextParser):
    """Parse Slov-Lex HTML portal fragments into Block objects."""

    def parse_text(self, data: bytes) -> list[Any]:
        """Parse a .portal HTML fragment into a list of Blocks.

        The portal fragment contains the full law text with semantic CSS
        classes. We walk the DOM tree and extract paragraphs with their
        CSS class mapped to Markdown formatting.

        Returns a single Block with one Version containing all paragraphs.
        """
        # Find the predpis (law) root element
        # The portal fragment starts with <div class="predpisFullWidth">
        parser = etree.HTMLParser(encoding="utf-8")
        tree = etree.fromstring(data, parser)

        paragraphs: list[Paragraph] = []

        # Find the main content div (predpis Skupina)
        predpis = tree.xpath('//div[contains(@class, "predpis") and contains(@class, "Skupina")]')
        if not predpis:
            # Try the whole document as fallback
            predpis = [tree]

        root = predpis[0]
        self._walk_element(root, paragraphs, in_toc=False)

        if not paragraphs:
            return []

        block = Block(
            id="full-text",
            block_type="document",
            title="",
            versions=(
                Version(
                    norm_id="",
                    publication_date=date(1970, 1, 1),
                    effective_date=date(1970, 1, 1),
                    paragraphs=tuple(paragraphs),
                ),
            ),
        )
        return [block]

    def _walk_element(
        self,
        el: etree._Element,
        paragraphs: list[Paragraph],
        in_toc: bool,
    ) -> None:
        """Recursively walk the DOM tree extracting paragraphs."""
        tag = etree.QName(el.tag).localname if isinstance(el.tag, str) else ""

        # Skip non-content sections
        el_id = el.get("id", "")
        el_class = el.get("class", "")

        # Skip the table of contents, history table, info table, sidebar
        if el_id in ("Historia", "HistoriaContent", "Content", "infosky"):
            return
        if "obsah" in el_class or "InfoTable" in el_class:
            return
        if "sidebar" in el_class or "toolbar" in el_class:
            return
        if "index_element" in el_class:
            return
        if el_id == "HistoriaTable" or tag == "script" or tag == "style":
            return
        # Skip navigation and header chrome
        if el_id in ("banner", "heading", "navigation", "skip-to-content"):
            return
        if "ucinnost_header" in el_class or "grid-zavaznost" in el_class:
            return
        # Skip the accordion sections (relationships, info panels)
        if "accordion" in el_class or "panel_relations" in el_class:
            return
        if "InformacieContent" in el_class:
            return

        css_class = _get_css_class(el)
        mapped = _ELEMENT_MAP.get(css_class)

        if mapped:
            # Check if this element contains tables — extract them separately
            tables = el.findall(".//table")
            if tables:
                # Mixed content: extract text before/between/after tables
                self._extract_mixed_content(el, mapped, paragraphs)
            else:
                text = _html_to_text(el)
                text = _clean_text(text)

                if text:
                    if mapped == "quote":
                        lines = text.split("\n")
                        text = "\n".join(f"> {line}" for line in lines if line.strip())

                    paragraphs.append(Paragraph(css_class=mapped, text=text))
            return  # Don't recurse into children — we already extracted text

        # For structural containers, recurse into children
        for child in el:
            if isinstance(child.tag, str):
                self._walk_element(child, paragraphs, in_toc)

    def _extract_mixed_content(
        self,
        el: etree._Element,
        css_class: str,
        paragraphs: list[Paragraph],
    ) -> None:
        """Extract content from an element that contains inline tables.

        Splits the content around <table> elements so that tables get
        their own paragraphs with preserved newlines (pipe tables).
        """
        # Collect text and child elements in order
        if el.text:
            text = _clean_text(el.text)
            if text:
                paragraphs.append(Paragraph(css_class=css_class, text=text))

        for child in el:
            tag = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""

            if tag == "table":
                md_table = _html_table_to_markdown(child)
                if md_table:
                    paragraphs.append(Paragraph(css_class="parrafo", text=md_table))
            else:
                # Non-table child: extract its text inline
                child_text = _html_to_text(child)
                child_text = _clean_text(child_text)
                if child_text:
                    paragraphs.append(Paragraph(css_class=css_class, text=child_text))

            # Tail text (after the child element)
            if child.tail:
                tail = _clean_text(child.tail)
                if tail:
                    paragraphs.append(Paragraph(css_class=css_class, text=tail))

    def extract_reforms(self, data: bytes) -> list[Any]:
        """Extract reform timeline from the version history HTML.

        For SK, the history is embedded in the portal page as
        effectivenessHistoryItem rows.
        """
        versions = parse_version_history(data)
        reforms = []
        for v in versions:
            if v.get("effective_from") and not v.get("is_proclaimed"):
                reforms.append(
                    {
                        "norm_id": v.get("amendment", "original"),
                        "date": v["effective_from"],
                    }
                )
        return reforms


class SlovLexMetadataParser(MetadataParser):
    """Parse Slov-Lex API catalog JSON into NormMetadata.

    The API returns JSON from the catalog search. For the portal page
    (HTML with InfoTable), use parse_metadata_from_portal() instead.
    """

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        """Parse metadata from API catalog JSON.

        norm_id is "{year}/{number}" e.g. "1992/460".
        data is the JSON response from search_catalog.
        """
        import json

        year, number = norm_id.split("/", 1)
        identifier = f"ZZ-{year}-{number}"

        payload = json.loads(data)
        docs = payload.get("docs", [])
        doc = docs[0] if docs else {}

        title = doc.get("nazov", "")
        cislo = doc.get("cislo", f"{number}/{year} Z. z.")
        typ_code = doc.get("typPredp", "")
        typ_display = doc.get("typPredp_value", "")

        # Parse dates — API uses ISO datetime "2024-12-27T00:00:00Z"
        pub_date = _parse_iso_date((doc.get("vyhlaseny") or "")[:10])
        effective_from = _parse_iso_date((doc.get("ucinnyOd") or "")[:10])
        effective_to = _parse_iso_date((doc.get("ucinnyDo") or "")[:10])

        if not pub_date:
            pub_date = effective_from or date(1970, 1, 1)

        # Determine rank from type code
        rank_str = _type_code_to_rank(typ_code)

        # Determine status
        status = NormStatus.IN_FORCE
        if effective_to and effective_to < date.today():
            status = NormStatus.EXPIRED

        # Build source URL
        source_url = f"https://www.slov-lex.sk/pravne-predpisy/SK/ZZ/{year}/{number}/"

        # Extra metadata — capture everything the API exposes
        extra: list[tuple[str, str]] = []
        _add_extra(extra, "official_citation", cislo)
        _add_extra(extra, "type_code", typ_code)
        _add_extra(extra, "type_display", typ_display)
        _add_extra(extra, "year", doc.get("rocnik"))
        if effective_from:
            _add_extra(extra, "effective_from", effective_from.isoformat())
        if effective_to:
            _add_extra(extra, "effective_to", effective_to.isoformat())
        # Headings (section names from nadpisy array)
        nadpisy = doc.get("nadpisy", [])
        if nadpisy:
            _add_extra(extra, "headings", "; ".join(nadpisy[:10]))

        return NormMetadata(
            title=title,
            short_title=title,
            identifier=identifier,
            country="sk",
            rank=Rank(rank_str),
            publication_date=pub_date,
            status=status,
            department="",
            source=source_url,
            last_modified=effective_from,
            pdf_url=None,
            subjects=(),
            extra=tuple(extra),
        )


# ─── Version history parsing (used by client, parser, and bootstrap) ───


def parse_version_history(data: bytes) -> list[dict[str, Any]]:
    """Parse the version history page to extract all versions.

    Returns a list of dicts, each with:
    - iri: full IRI path
    - date_suffix: YYYYMMDD string for .portal URL
    - effective_from: date or None
    - effective_to: date or None
    - is_proclaimed: True if this is the proclaimed text (vyhlasene_znenie)
    - amendment: amendment citation string or ""
    """
    parser = etree.HTMLParser(encoding="utf-8")
    tree = etree.fromstring(data, parser)

    versions: list[dict[str, Any]] = []

    for tr in tree.xpath('//tr[contains(@class, "effectivenessHistoryItem")]'):
        iri = tr.get("data-iri", "")
        is_proclaimed = tr.get("data-vyhlasene") == "1"
        effective_from_str = tr.get("data-ucinnostod", "")
        effective_to_str = tr.get("data-ucinnostdo", "")

        # Extract date suffix from IRI
        # /SK/ZZ/1992/460/19921001 → 19921001
        # /SK/ZZ/1992/460/vyhlasene_znenie → vyhlasene_znenie
        date_suffix = iri.rsplit("/", 1)[-1] if iri else ""

        # Parse dates
        effective_from = _parse_iso_date(effective_from_str) if effective_from_str else None
        effective_to = _parse_iso_date(effective_to_str) if effective_to_str else None

        # Extract amendment reference from the third <td>
        tds = list(tr.iter("td"))
        amendment = ""
        if len(tds) >= 3:
            amendment_text = etree.tostring(tds[2], method="text", encoding="unicode") or ""
            amendment = _clean_text(amendment_text)

        versions.append(
            {
                "iri": iri,
                "date_suffix": date_suffix,
                "effective_from": effective_from,
                "effective_to": effective_to,
                "is_proclaimed": is_proclaimed,
                "amendment": amendment,
            }
        )

    return versions


# ─── Helpers ───


def _parse_sk_date(text: str | None) -> date | None:
    """Parse a Slovak date string (DD.MM.YYYY) into a date object."""
    if not text or not text.strip():
        return None
    text = text.strip()
    # Try DD.MM.YYYY
    m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    # Try ISO format as fallback
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_iso_date(text: str) -> date | None:
    """Parse an ISO date string (YYYY-MM-DD)."""
    try:
        return date.fromisoformat(text[:10])
    except (ValueError, IndexError):
        return None


def _type_to_rank(typ: str) -> str:
    """Map Slovak law type (display name) to a rank string."""
    typ_lower = typ.lower().strip()
    return {
        "ústavný zákon": "constitutional_law",
        "zákon": "law",
        "nariadenie vlády": "government_regulation",
        "vyhláška": "ordinance",
        "oznámenie": "notification",
        "nález": "finding",
        "opatrenie": "measure",
        "rozhodnutie": "decision",
        "uznesenie": "resolution",
        "zákonné opatrenie": "legal_measure",
        "zákon (celé znenie)": "law",
        "redakčné oznámenie": "editorial_notification",
    }.get(typ_lower, typ_lower.replace(" ", "_") if typ_lower else "unknown")


def _type_code_to_rank(typ_code: str) -> str:
    """Map Slovak law type code (API field typPredp) to a rank string."""
    return {
        "UstavnyZakon": "constitutional_law",
        "Zakon": "law",
        "NariadenieVlady": "government_regulation",
        "Vyhlaska": "ordinance",
        "Oznamenie": "notification",
        "Nalez": "finding",
        "Opatrenie": "measure",
        "Rozhodnutie": "decision",
        "Uznesenie": "resolution",
        "ZakonneOpatrenie": "legal_measure",
        "RedakcneOznamenie": "editorial_notification",
        "ZakonCeleZnenie": "law",
    }.get(typ_code, typ_code.lower() if typ_code else "unknown")


def _add_extra(extra: list[tuple[str, str]], key: str, value: Any) -> None:
    """Append a key-value pair to extra if value is truthy."""
    if value is not None and value != "":
        extra.append((key, str(value)[:500]))
