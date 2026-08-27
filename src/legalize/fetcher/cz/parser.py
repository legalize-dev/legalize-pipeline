"""Text and metadata parsers for Czech e-Sbírka legislation.

Parses JSON fragment responses into Block/Version/Paragraph and
JSON metadata into NormMetadata.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import Block, NormMetadata, NormStatus, Paragraph, Rank, Version
from legalize.fetcher._text import strip_control

logger = logging.getLogger(__name__)

# Regex for extracting amendment numbers from full citation text.
_AMENDMENT_RE = re.compile(r"č\.\s*(\d+)/(\d+)\s*Sb\.")

# Fragment types to skip (structural containers + prefix metadata).
# Prefix fragments (law number, type, author, date) are redundant with
# frontmatter. The body should start with the actual legal text.
_SKIP_TYPES = frozenset(
    {
        "Virtual_Document",
        "Virtual_Prefix",
        "Virtual_Norma",
        "Virtual_Postfix",
        "Virtual_PPC",
        "Block_Ucinnostni_Ustanoveni",
        "Prefix_Number",
        "Prefix_Type",
        "Prefix_Author",
        "Prefix_Date",
        "Prefix",
        "Prefix_Title",
    }
)

# Fragment type → (css_class, heading_level or None).
# heading_level: 1=h1, 2=h2, etc. None=body paragraph.
#
# Czech legislative hierarchy (top → bottom):
#   Cast (Part) > Hlava (Title) > Dil (Division) > Oddil (Section)
#   > Clanek/Paragraf (Article/§) > Odstavec (Paragraph) > Pismeno (Letter)
_FRAGMENT_TYPE_MAP: dict[str, tuple[str, int | None]] = {
    "Preambule": ("parrafo", None),
    "Cast": ("titulo_tit", 2),  # ## ČÁST — Part (highest structural)
    "Hlava": ("capitulo_tit", 3),  # ### HLAVA — Title
    "Dil": ("seccion", 4),  # #### Díl — Division
    "Oddil": ("seccion", 4),  # #### Oddíl — Section
    "Nadpis_pod": ("seccion", 4),  # #### subtitle below heading
    "Nadpis_nad": ("seccion", 4),  # #### subtitle above article
    "Clanek": ("articulo", 5),
    "Paragraf": ("articulo", 5),
    "Odstavec_Dc": ("parrafo", None),
    "Pismeno_Lb": ("list_item", None),
    "Bod_Dd": ("list_item", None),
    "Pokracovani_Text": ("parrafo", None),
    "Tabulka": ("table", None),
    "Postfix": ("firma_rey", None),
}


def _html_table_to_markdown(html: str) -> str:
    """Convert an HTML <table> to a Markdown pipe table.

    Handles <th> (header) and <td> (data) cells. Multi-line cell
    content (from <br/>) is joined with spaces. Returns a complete
    Markdown table string.
    """
    # Extract rows
    rows: list[list[str]] = []
    is_header: list[bool] = []

    for row_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL):
        row_html = row_match.group(1)
        cells = []
        row_is_header = False

        for cell_match in re.finditer(r"<(th|td)[^>]*>(.*?)</\1>", row_html, re.DOTALL):
            tag = cell_match.group(1)
            content = cell_match.group(2)
            if tag == "th":
                row_is_header = True
            # Clean cell content
            content = re.sub(r"<br\s*/?>", " ", content)
            content = re.sub(r"<[^>]+>", "", content)
            content = content.replace("&amp;", "&")
            content = content.replace("&nbsp;", " ")
            content = strip_control(content)
            content = re.sub(r"\s+", " ", content).strip()
            # Escape pipe chars inside cells
            content = content.replace("|", "\\|")
            cells.append(content)

        if cells:
            rows.append(cells)
            is_header.append(row_is_header)

    if not rows:
        return ""

    # Normalize column count
    max_cols = max(len(r) for r in rows)
    for row in rows:
        while len(row) < max_cols:
            row.append("")

    lines = []
    for i, row in enumerate(rows):
        lines.append("| " + " | ".join(row) + " |")
        # Add separator after header row
        if is_header[i] and (i + 1 >= len(rows) or not is_header[i + 1]):
            lines.append("| " + " | ".join("---" for _ in row) + " |")

    # If no header row found, add separator after first row
    if not any(is_header):
        lines.insert(1, "| " + " | ".join("---" for _ in rows[0]) + " |")

    return "\n".join(lines)


def _clean_text(text: str) -> str:
    """Clean XHTML fragment text into plain Markdown-ready text.

    - Strips <var> tags (used for numbering: <var>Čl. 1</var>)
    - Converts <em> to *italic*
    - Converts <strong> to **bold**
    - Converts <sup> to ^superscript
    - Converts <br/> to space
    - Strips remaining HTML tags
    - Removes C0/C1 control characters
    - Normalizes whitespace
    """
    if not text:
        return ""

    # Bold: <strong>, <b>
    text = re.sub(r"<(?:strong|b)>(.*?)</(?:strong|b)>", r"**\1**", text, flags=re.DOTALL)
    # Italic: <em>, <i>
    text = re.sub(r"<(?:em|i)>(.*?)</(?:em|i)>", r"*\1*", text, flags=re.DOTALL)
    # Superscript: <sup>
    text = re.sub(r"<sup>(.*?)</sup>", r"^\1", text, flags=re.DOTALL)
    # Subscript: <sub> — keep content, no MD equivalent
    text = re.sub(r"</?sub>", "", text)
    # Underline: <u> — strip (no MD equivalent)
    text = re.sub(r"</?u>", "", text)

    # Links: <a ...>text</a> — keep link text only
    text = re.sub(r"<a[^>]*>(.*?)</a>", r"\1", text, flags=re.DOTALL)

    # Line breaks → space
    text = re.sub(r"<br\s*/?>", " ", text)

    # MathML: strip all MathML tags, keep text content
    text = re.sub(
        r"</?(?:math|mrow|mfrac|msub|msup|msubsup|munder|munderover"
        r"|mfenced|mo|mi|mn)[^>]*>",
        "",
        text,
    )

    # Images: drop entirely (project policy: no binary assets)
    text = re.sub(r"<img[^>]*>", "[image omitted]", text)

    # Strip <var> tags (keep content)
    text = re.sub(r"</?var>", "", text)

    # Strip <czechvoc-termin ...>...</czechvoc-termin> and <czechvoc...> (keep content)
    text = re.sub(r"</?czechvoc[^>]*>", "", text)

    # Strip any remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Unescape HTML entities
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = text.replace("&nbsp;", " ")

    # Remove control characters
    text = strip_control(text)

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


def _parse_date(value: str | None) -> date | None:
    """Parse a date string from the API (ISO date or ISO datetime)."""
    if not value:
        return None
    # Try plain date first: "2024-01-01"
    if len(value) == 10:
        return date.fromisoformat(value)
    # ISO datetime: "1992-12-28T00:00:00.000+01:00"
    # Truncate to date portion
    return date.fromisoformat(value[:10])


def _stale_url_to_identifier(stale_url: str) -> str:
    """Convert a staleUrl to a filesystem-safe identifier.

    "/sb/1993/1" → "SB-1993-1"
    "/sb/2009/40" → "SB-2009-40"
    """
    parts = stale_url.strip("/").split("/")
    return "-".join(p.upper() if i == 0 else p for i, p in enumerate(parts))


class ESbirkaTextParser(TextParser):
    """Parse e-Sbírka JSON fragments into Block objects."""

    def parse_text(self, data: bytes) -> list[Any]:
        """Parse fragment JSON into a list of Blocks.

        Each fragment becomes a Paragraph inside a single Block. Since
        the e-Sbírka API returns one flat list of fragments per law
        (not nested XML), we group all fragments into one Block with
        one Version.

        The data argument is the raw JSON bytes from the fragments
        endpoint (potentially merged across multiple pages).
        """
        payload = json.loads(data)

        # Handle both single-page {seznam, pocetStranek} and
        # pre-merged list formats.
        if isinstance(payload, list):
            fragments = payload
        else:
            fragments = payload.get("seznam", [])

        paragraphs: list[Paragraph] = []

        for frag in fragments:
            frag_type = frag.get("kodTypuFragmentu", "")

            # Skip structural containers and prefix metadata
            if frag_type in _SKIP_TYPES:
                continue

            # Skip fragments with no text
            xhtml = frag.get("xhtml") or ""
            if not xhtml.strip():
                continue

            text = _clean_text(xhtml)
            if not text:
                continue

            # Determine CSS class from fragment type
            mapping = _FRAGMENT_TYPE_MAP.get(frag_type)
            if mapping:
                css_class = mapping[0]
            else:
                css_class = "parrafo"

            # Tables: convert HTML to Markdown pipe table
            if css_class == "table":
                md_table = _html_table_to_markdown(xhtml)
                if md_table:
                    paragraphs.append(Paragraph(css_class="parrafo", text=md_table))
                continue

            # Prefix lettered/numbered points with "- " for Markdown lists
            if css_class == "list_item":
                text = f"- {text}"

            paragraphs.append(Paragraph(css_class=css_class, text=text))

        if not paragraphs:
            return []

        # Single block containing all paragraphs as one version.
        # The pipeline's commit logic handles version-per-date externally.
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

    def extract_reforms(self, data: bytes) -> list[Any]:
        """Extract reform timeline from metadata.

        For CZ, reforms are extracted from the metadata (amendment list),
        not from the text. This method parses the metadata JSON and
        returns Reform-compatible dicts.
        """
        try:
            meta = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return []

        citation = meta.get("uplnaCitaceSNovelami", "")
        amendments = _AMENDMENT_RE.findall(citation)

        reforms = []
        for num, year in amendments:
            # Skip the law itself (first match in the citation)
            stale_url = meta.get("staleUrl", "")
            if f"/{year}/{num}" in stale_url:
                continue
            reforms.append(
                {
                    "norm_id": f"/sb/{year}/{num}",
                    "kodDokumentuSbirky": f"{num}/{year} Sb.",
                }
            )
        return reforms


class ESbirkaMetadataParser(MetadataParser):
    """Parse e-Sbírka metadata JSON into NormMetadata."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        """Parse metadata JSON into NormMetadata.

        norm_id is the staleUrl, e.g. "/sb/1993/1".
        """
        meta = json.loads(data)

        identifier = _stale_url_to_identifier(norm_id)
        title = meta.get("nazev", "")
        short_title = meta.get("zkracenaCitace", "") or title

        pub_date = _parse_date(meta.get("datumCasVyhlaseni"))
        if not pub_date:
            pub_date = _parse_date(meta.get("datumUcinnostiOd"))
        if not pub_date:
            pub_date = date(1970, 1, 1)

        last_modified = _parse_date(meta.get("datumUcinnostiZneniOd"))

        # Determine status
        status = NormStatus.IN_FORCE
        stav = meta.get("stavDokumentuSbirky") or meta.get("typZneni", "")
        if stav == "ZRUSENY":
            status = NormStatus.REPEALED

        # Determine rank from hierarchy template + act type codes
        template = meta.get("sablonaHierarchieKod", "")
        act_type = meta.get("druhPravnihoAktuKod", "")
        rank_str = _determine_rank(template, act_type)

        # Source URL
        eli = meta.get("eli", "")
        source_url = f"https://e-sbirka.gov.cz{eli}" if eli else ""

        # Extra metadata — capture everything the source exposes
        extra: list[tuple[str, str]] = []
        _add_extra(extra, "official_code", meta.get("kodDokumentuSbirky"))
        _add_extra(extra, "full_citation", meta.get("uplnaCitace"))
        _add_extra(extra, "full_citation_with_amendments", meta.get("uplnaCitaceSNovelami"))
        _add_extra(extra, "eli", eli)
        _add_extra(extra, "collection_code", meta.get("sbirkaKod"))
        _add_extra(extra, "document_set_code", meta.get("sadaDokumentuKod"))
        _add_extra(extra, "effectiveness_date", meta.get("datumUcinnostiOd"))
        _add_extra(extra, "version_type", meta.get("typZneni"))
        _add_extra(extra, "act_type_code", meta.get("typAktuKod"))
        _add_extra(extra, "legal_act_kind_code", act_type)
        _add_extra(extra, "hierarchy_template", meta.get("sablonaHierarchieKod"))
        _add_extra(extra, "base_document_id", meta.get("dokumentBaseId"))
        _add_extra(extra, "gazette_issue_number", meta.get("cisloCastky"))
        _add_extra(extra, "gazette_issue_year", meta.get("rokCastky"))
        # Boolean fields — capture even when false per project rules
        _add_bool(extra, "is_international_treaty", meta.get("jeMezinarodniSmlouva"))
        _add_bool(extra, "has_editorial_correction", meta.get("poRedakcniOprave"))
        _add_bool(extra, "never_effective", meta.get("nikdyNebylUcinny"))
        _add_bool(extra, "provisions_never_effective", meta.get("ustanoveniNikdyNebylaUcinna"))
        _add_bool(extra, "has_explanatory_report", meta.get("maOduvodneni"))
        _add_bool(extra, "inactive_temporal_version", meta.get("neucinnaCasovaVerze"))

        # Amendments list
        novely = meta.get("novely", [])
        if novely:
            amendment_strs = [
                n.get("kodDokumentuSbirky", "") for n in novely if n.get("kodDokumentuSbirky")
            ]
            if amendment_strs:
                _add_extra(extra, "amendments", "; ".join(amendment_strs))

        return NormMetadata(
            title=title,
            short_title=short_title,
            identifier=identifier,
            country="cz",
            rank=Rank(rank_str),
            publication_date=pub_date,
            status=status,
            department="",
            source=source_url,
            last_modified=last_modified,
            extra=tuple(extra),
        )


def _determine_rank(template: str, act_type: str) -> str:
    """Determine rank from hierarchy template and act type code.

    The sablonaHierarchieKod (hierarchy template) is the most reliable
    indicator of rank. druhPravnihoAktuKod (act type) is a fallback.

    Template patterns:
    - *_UST → constitutional law (ústavní zákon)
    - *_ZAKON → law (zákon)
    - *_NARIZENI → regulation (nařízení)
    - *_VYHLASKA → ordinance (vyhláška)
    - *_NOVELA_* → amendment (čistá novela)
    """
    tpl = template.upper()
    if "_UST" in tpl:
        return "constitutional_law"
    if "_ZAKON" in tpl:
        return "law"
    if "_NARIZENI" in tpl:
        return "regulation"
    if "_VYHLASKA" in tpl:
        return "ordinance"
    if "_DEKRET" in tpl:
        return "decree"

    # Fallback to act type code
    return {
        "ZAKONUST": "constitutional_law",
        "ZAKON": "law",
        "OPATRSEN": "senate_measure",
        "NARIZENI": "regulation",
        "VYHLASKA": "ordinance",
        "DEKRETUST": "constitutional_decree",
        "DEKRET": "decree",
    }.get(act_type, act_type.lower() if act_type else "unknown")


def _add_extra(extra: list[tuple[str, str]], key: str, value: Any) -> None:
    """Append a key-value pair to extra if value is truthy."""
    if value is not None and value != "" and value is not False:
        extra.append((key, str(value)))


def _add_bool(extra: list[tuple[str, str]], key: str, value: Any) -> None:
    """Append a boolean field to extra (captures both true and false)."""
    if value is not None:
        extra.append((key, str(value).lower()))
