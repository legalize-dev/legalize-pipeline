"""Parser for German gesetze-im-internet.de gii-norm XML.

Format: Custom XML (gii-norm DTD v1.01)
Each ZIP contains one XML file with all <norm> elements for a law.
First <norm> = law-level metadata. Subsequent <norm>s = articles/sections.

Structure per <norm>:
  <metadaten>
    <jurabk>GG</jurabk>
    <enbez>Art 1</enbez>           ← article number
    <titel>Menschenwürde</titel>   ← article title (optional)
    <gliederungseinheit>...</>     ← section heading (if structural)
  </metadaten>
  <textdaten>
    <text format="XML">
      <Content>
        <P>(1) Die Würde...</P>
        <P>(2) Das Deutsche Volk...</P>
      </Content>
    </text>
  </textdaten>
"""

from __future__ import annotations

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

# Map common law type patterns to rank
_RANK_PATTERNS: list[tuple[str, str]] = [
    ("grundgesetz", "grundgesetz"),
    ("verordnung", "rechtsverordnung"),
    ("bekanntmachung", "bekanntmachung"),
    ("satzung", "satzung"),
]


def _parse_gii_date(s: str | None) -> date | None:
    """Parse GII date format (YYYYMMDD or YYYY-MM-DD)."""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _text_content(el: ET.Element) -> str:
    """Extract all text, collapsing whitespace (simple fallback)."""
    return " ".join("".join(el.itertext()).split())


def _extract_inline(el: ET.Element) -> str:
    """Recursively extract text with inline formatting (like FR's _extract_text_legi).

    Handles SP (emphasis), B (bold), I (italic), BR (newline),
    FnR (footnote ref, skipped), and other inline elements.
    """
    parts: list[str] = []

    if el.text:
        parts.append(el.text)

    for child in el:
        tag = child.tag

        if tag in ("B", "b", "strong"):
            inner = _extract_inline(child)
            if inner.strip():
                parts.append(f"**{inner.strip()}**")
        elif tag in ("I", "i", "em"):
            inner = _extract_inline(child)
            if inner.strip():
                parts.append(f"*{inner.strip()}*")
        elif tag == "SP":
            inner = _extract_inline(child)
            if inner.strip():
                parts.append(f"*{inner.strip()}*")
        elif tag == "BR":
            parts.append("\n")
        elif tag == "FnR":
            pass  # footnote references have no visible text
        elif tag in ("NB", "ABWFORMAT", "noindex", "kommentar", "FILE"):
            inner = _extract_inline(child)
            if inner:
                parts.append(inner)
        else:
            # LA, SUP, SUB, other containers — recurse
            inner = _extract_inline(child)
            if inner:
                parts.append(inner)

        if child.tail:
            parts.append(child.tail)

    return "".join(parts)


def _parse_dl(dl_el: ET.Element) -> list[Paragraph]:
    """Parse a <DL> definition list into numbered/lettered list paragraphs.

    Each DT/DD pair becomes a paragraph like "1. item text".
    Handles nested DLs recursively.
    """
    paragraphs: list[Paragraph] = []
    dt_text = ""

    for child in dl_el:
        tag = child.tag
        if tag == "DT":
            dt_text = _extract_inline(child).strip()
        elif tag == "DD":
            # DD may contain LA (list item text) and nested DL
            parts: list[str] = []

            # Collect inline text from DD (and its LA children)
            for dd_child in child:
                if dd_child.tag == "DL":
                    pass
                elif dd_child.tag == "LA":
                    # LA may itself contain nested DL
                    la_has_dl = dd_child.find("DL") is not None
                    if la_has_dl:
                        # Text before nested DL
                        la_text = dd_child.text or ""
                        if la_text.strip():
                            parts.append(la_text.strip())
                    else:
                        inner = _extract_inline(dd_child)
                        if inner.strip():
                            parts.append(inner.strip())
                else:
                    inner = _extract_inline(dd_child)
                    if inner.strip():
                        parts.append(inner.strip())

            # Direct text in DD
            if child.text and child.text.strip():
                parts.insert(0, child.text.strip())

            item_text = " ".join(parts)
            if dt_text and item_text:
                full_text = f"{dt_text} {item_text}"
            elif dt_text:
                full_text = dt_text
            elif item_text:
                full_text = item_text
            else:
                continue

            paragraphs.append(Paragraph(css_class="list_item", text=full_text))

            # Handle nested DLs (sub-items like a), b), c))
            for dd_child in child:
                if dd_child.tag == "DL":
                    paragraphs.extend(_parse_dl(dd_child))
                elif dd_child.tag == "LA":
                    for la_child in dd_child:
                        if la_child.tag == "DL":
                            paragraphs.extend(_parse_dl(la_child))

            dt_text = ""

    return paragraphs


def _parse_p(p_el: ET.Element) -> list[Paragraph]:
    """Parse a <P> element, handling embedded DL lists.

    If the P has no DL children, returns a single paragraph.
    If the P has DL children, splits into intro text + list items + trailing text.
    """
    has_dl = p_el.find(".//DL") is not None

    if not has_dl:
        text = _extract_inline(p_el)
        clean = " ".join(text.split()) if "\n" not in text else text.strip()
        if clean.strip():
            return [Paragraph(css_class="abs", text=clean.strip())]
        return []

    # P with embedded DL — walk through mixed content
    paragraphs: list[Paragraph] = []
    accumulated: list[str] = []

    def flush_text():
        joined = " ".join(accumulated).strip()
        if joined:
            paragraphs.append(Paragraph(css_class="abs", text=joined))
        accumulated.clear()

    # Intro text
    if p_el.text and p_el.text.strip():
        accumulated.append(p_el.text.strip())

    for child in p_el:
        tag = child.tag
        if tag == "DL":
            flush_text()
            paragraphs.extend(_parse_dl(child))
        elif tag == "BR":
            # Line break — flush current text
            flush_text()
        else:
            inner = _extract_inline(child)
            if inner.strip():
                accumulated.append(inner.strip())

        if child.tail and child.tail.strip():
            accumulated.append(child.tail.strip())

    flush_text()
    return paragraphs


def _infer_rank(title: str, jurabk: str) -> str:
    """Infer normative rank from law title and abbreviation."""
    if jurabk.upper() == "GG" or title.lower().startswith("grundgesetz"):
        return "grundgesetz"
    lower = (title + " " + jurabk).lower()
    for pattern, rank in _RANK_PATTERNS:
        if pattern in lower:
            return rank
    return "bundesgesetz"


class GIITextParser(TextParser):
    """Parses gii-norm XML into Block objects."""

    def parse_text(self, data: bytes) -> list[Any]:
        """Parse the full gii-norm XML into Blocks.

        First <norm> is law-level metadata (skipped here — handled by metadata parser).
        Structural <norm>s (with gliederungseinheit) become section headings.
        Article <norm>s (with enbez) become article blocks.
        """
        root = ET.fromstring(data)
        norms = root.findall(".//norm")
        blocks: list[Block] = []

        # Version dating: builddate is a timestamp, "20260928220002", and its
        # date is the first eight digits. Read whole it parsed as nothing, every
        # block was dated the day the pipeline ran, and a daily rendering an
        # earlier day found no block in force and committed the law empty.
        builddate = root.get("builddate", "")
        pub_date = _parse_gii_date(builddate[:8]) or date.today()

        for norm in norms[1:]:  # Skip first norm (law-level metadata)
            meta = norm.find("metadaten")
            if meta is None:
                continue

            gliederung = meta.find("gliederungseinheit")
            enbez = meta.find("enbez")

            if gliederung is not None:
                block = self._parse_section(gliederung, norm, pub_date)
                if block:
                    blocks.append(block)
            elif enbez is not None:
                block = self._parse_article(meta, norm, pub_date)
                if block:
                    blocks.append(block)

        return blocks

    def extract_reforms(self, data: bytes) -> list[Any]:
        """Extract reform info from standangabe metadata."""
        root = ET.fromstring(data)
        norms = root.findall(".//norm")
        reforms = []

        if norms:
            meta = norms[0].find("metadaten")
            if meta is not None:
                for stand in meta.findall("standangabe"):
                    kommentar = stand.find("standkommentar")
                    if kommentar is not None and kommentar.text:
                        reforms.append({"note": kommentar.text.strip()})

        return reforms

    def _parse_section(
        self, gliederung: ET.Element, norm: ET.Element, pub_date: date
    ) -> Block | None:
        """Parse a structural heading norm into a Block."""
        bez = gliederung.find("gliederungsbez")
        titel = gliederung.find("gliederungstitel")
        bez_text = bez.text.strip() if bez is not None and bez.text else ""
        titel_text = titel.text.strip() if titel is not None and titel.text else ""
        title = f"{bez_text} {titel_text}".strip() if bez_text else titel_text

        if not title:
            return None

        doknr = norm.get("doknr", "")
        heading_para = Paragraph(css_class="titulo", text=title)
        version = Version(
            norm_id=doknr,
            publication_date=pub_date,
            effective_date=pub_date,
            paragraphs=(heading_para,),
        )
        return Block(id=doknr, block_type="section", title=title, versions=(version,))

    def _parse_article(self, meta: ET.Element, norm: ET.Element, pub_date: date) -> Block | None:
        """Parse an article norm into a Block."""
        enbez = meta.find("enbez")
        titel = meta.find("titel")
        enbez_text = enbez.text.strip() if enbez is not None and enbez.text else ""
        titel_text = _text_content(titel) if titel is not None else ""
        title = f"{enbez_text} {titel_text}".strip() if enbez_text else titel_text

        doknr = norm.get("doknr", "")

        # Parse text content
        paragraphs: list[Paragraph] = []
        if title:
            paragraphs.append(Paragraph(css_class="articulo", text=title))

        content = norm.find(".//Content")
        if content is not None:
            paragraphs.extend(self._parse_content(content))

        if not paragraphs:
            return None

        version = Version(
            norm_id=doknr,
            publication_date=pub_date,
            effective_date=pub_date,
            paragraphs=tuple(paragraphs),
        )
        return Block(id=doknr, block_type="article", title=title, versions=(version,))

    def _parse_content(self, content: ET.Element) -> list[Paragraph]:
        """Parse <Content> children into Paragraph objects.

        Handles P (with embedded DL lists), standalone DL, tables, pre.
        Uses recursive inline extraction for formatting (bold, italic, etc.).
        """
        paragraphs: list[Paragraph] = []

        for child in content:
            tag = child.tag

            if tag == "P":
                paragraphs.extend(_parse_p(child))
            elif tag == "DL":
                paragraphs.extend(_parse_dl(child))
            elif tag in ("DT", "DD"):
                text = _extract_inline(child).strip()
                if text:
                    paragraphs.append(Paragraph(css_class="list_item", text=text))
            elif tag == "table":
                for row in child.findall(".//row"):
                    row_text = _text_content(row)
                    if row_text:
                        paragraphs.append(Paragraph(css_class="table_row", text=row_text))
            elif tag == "pre":
                text = _extract_inline(child).strip()
                if text:
                    paragraphs.append(Paragraph(css_class="pre", text=text))
            elif tag == "BR":
                pass  # top-level BR between content blocks
            else:
                text = _extract_inline(child).strip()
                if text:
                    paragraphs.append(Paragraph(css_class="abs", text=text))

        return paragraphs


class GIIMetadataParser(MetadataParser):
    """Parses gii-norm XML first <norm> into NormMetadata."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        """Parse the law-level metadata from the first <norm>.

        norm_id is the URL slug (e.g., "gg", "bgb").

        Extracts enriched metadata from the GII XML:
        - Core fields: title, identifier, country, rank, dates, source
        - Extra fields: doknr, slug, bgbl_reference, amtabk,
          stand (current amendment), neufassung (recast), hinweis (pending)
        """
        root = ET.fromstring(data)
        norms = root.findall(".//norm")
        if not norms:
            raise ValueError(f"No norms found for {norm_id}")

        meta = norms[0].find("metadaten")
        if meta is None:
            raise ValueError(f"No metadata in first norm for {norm_id}")

        jurabk = (meta.findtext("jurabk") or norm_id).strip()
        langue = (meta.findtext("langue") or meta.findtext("kurzue") or jurabk).strip()
        kurzue = (meta.findtext("kurzue") or "").strip()
        amtabk = (meta.findtext("amtabk") or "").strip()

        # Date
        ausfertigung = meta.find("ausfertigung-datum")
        date_str = ausfertigung.text if ausfertigung is not None else None
        publication_date = _parse_gii_date(date_str) or date(1900, 1, 1)

        # Fundstelle (gazette reference)
        periodikum = meta.findtext("fundstelle/periodikum") or ""
        zitstelle = meta.findtext("fundstelle/zitstelle") or ""
        bgbl_ref = f"{periodikum} {zitstelle}".strip()

        # Standangabe — extract by type (Stand, Neuf, Hinweis, Sonst)
        stand_by_type: dict[str, str] = {}
        for stand in meta.findall("standangabe"):
            standtyp = (stand.findtext("standtyp") or "").strip()
            kommentar = (stand.findtext("standkommentar") or "").strip()
            if kommentar:
                stand_by_type[standtyp] = kommentar

        # Document number (BJNR...)
        doknr = root.get("doknr", "")

        rank_str = _infer_rank(langue, jurabk)

        # Build identifier: use jurabk (abbreviation) as it's unique and stable
        identifier = jurabk.upper().replace(" ", "-")

        # Extra fields — enriched metadata
        extra: list[tuple[str, str]] = []
        if doknr:
            extra.append(("doknr", doknr))
        extra.append(("slug", norm_id))
        if bgbl_ref:
            extra.append(("bgbl_reference", bgbl_ref))
        if amtabk and amtabk != jurabk:
            extra.append(("amtabk", amtabk))
        if stand_by_type.get("Stand"):
            extra.append(("stand", stand_by_type["Stand"]))
        if stand_by_type.get("Neuf"):
            extra.append(("neufassung", stand_by_type["Neuf"]))
        if stand_by_type.get("Hinweis"):
            extra.append(("hinweis", stand_by_type["Hinweis"]))

        return NormMetadata(
            title=langue,
            short_title=kurzue or jurabk,
            identifier=identifier,
            country="de",
            rank=Rank(rank_str),
            publication_date=publication_date,
            status=NormStatus.IN_FORCE,
            department="BMJ (Bundesministerium der Justiz)",
            source=f"https://www.gesetze-im-internet.de/{norm_id}/",
            extra=tuple(extra),
        )
