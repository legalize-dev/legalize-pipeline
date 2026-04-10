"""Parsers for Swedish legislation from the Riksdagen API.

Parses the JSON document format from Riksdagen's open data API
into structured Block objects and NormMetadata.

Text parsing ported from the TypeScript riksdagen-provision-parser.ts,
adapted for the legalize pipeline data model.

References:
  - https://data.riksdagen.se/
  - https://rkrattsbaser.gov.se/sfsr (amendment register)
"""

from __future__ import annotations

import html as html_module
import json
import logging
import re
from datetime import date
from typing import Any

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

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Swedish Rank constants
# ─────────────────────────────────────────────

# Defined as Rank strings — consistent with how Spain/France do it.
# Rank is a free-form str subclass, so any string is valid.
_RANK_GRUNDLAG = Rank("grundlag")  # Fundamental law (constitution)
_RANK_BALK = Rank("balk")  # Code (e.g. Brottsbalken)
_RANK_LAG = Rank("lag")  # Act/Law
_RANK_FORORDNING = Rank("forordning")  # Ordinance/Regulation

# ─────────────────────────────────────────────
# Title → Rank detection
# ─────────────────────────────────────────────

# Known fundamental laws (grundlag) by keyword in title
_GRUNDLAG_KEYWORDS = (
    "grundlag",
    "regeringsform",
    "tryckfrihetsförordning",
    "yttrandefrihetsgrundlag",
    "successionsordning",
)


def _detect_rank(title: str) -> Rank:
    """Detect the normative rank from a Swedish statute title.

    Uses the leading word(s) of the title to determine the type,
    not substring search (which gives false positives, e.g.
    "Lag ... EU:s dataskyddsförordning" would match "förordning").

    Detection order (most specific first):
    1. Known fundamental law keywords -> grundlag
    2. Title starts with Xxxbalk or contains standalone "balk" -> balk
    3. Title starts with "Förordning" -> forordning
    4. Everything else -> lag (default for most statutes)
    """
    title_lower = title.lower()

    for keyword in _GRUNDLAG_KEYWORDS:
        if keyword in title_lower:
            return _RANK_GRUNDLAG

    # Match "Brottsbalk", "Jordabalk", "Handelsbalk", etc.
    if re.match(r"^[a-zåäö]*balk\b", title_lower):
        return _RANK_BALK

    # Match only if title STARTS with "Förordning"
    if re.match(r"^förordning\b", title_lower):
        return _RANK_FORORDNING

    # Default: lag (act) — most Swedish SFS entries are laws
    return _RANK_LAG


# ─────────────────────────────────────────────
# Date helpers
# ─────────────────────────────────────────────


def _parse_date_se(date_str: str | None) -> date | None:
    """Parse a date string from Riksdagen JSON.

    Expected format: YYYY-MM-DD. Returns None for empty/invalid.
    """
    if not date_str:
        return None
    date_str = date_str.strip()
    if not date_str:
        return None
    try:
        # Extract YYYY-MM-DD from possibly longer strings
        match = re.match(r"(\d{4}-\d{2}-\d{2})", date_str)
        if match:
            return date.fromisoformat(match.group(1))
        return None
    except ValueError:
        logger.debug("Could not parse date: %s", date_str)
        return None


# ─────────────────────────────────────────────
# Text parsing — chapter/section regex
# ─────────────────────────────────────────────

_CHAPTER_PATTERN = re.compile(r"^(\d+)\s*kap\.\s*(.*)$", re.UNICODE)
_SECTION_PATTERN = re.compile(r"^(\d+\s*[a-z]?)\s*§\s*(.*)$", re.IGNORECASE | re.UNICODE)
_LAW_NOTE_PATTERN = re.compile(r"^Lag\s+\(\d{4}:\d+\)\.?$", re.UNICODE)


def _normalize_section_ref(section: str) -> str:
    """Normalize a section reference: strip whitespace, lowercase."""
    return re.sub(r"\s+", " ", section).strip().lower()


def _section_ordinal(section: str) -> int | None:
    """Convert a section ref like '3 a' to an ordinal (300 + 1 = 301).

    Used for monotonicity checks to detect out-of-order sections.
    """
    match = re.match(r"^(\d+)(?:\s*([a-z]))?$", section, re.IGNORECASE)
    if not match:
        return None
    base = int(match.group(1))
    suffix = (match.group(2) or "").lower()
    if not suffix:
        return base * 100
    offset = ord(suffix) - 96  # a=1, b=2, ...
    return base * 100 + max(offset, 0)


def _is_likely_title(line: str) -> bool:
    """Check if a line looks like a section title (not a provision start)."""
    return (
        0 < len(line) < 100
        and bool(re.match(r"^[A-ZÅÄÖ]", line))
        and not re.match(r"^\d+\s*(kap\.|§)", line)
        and not _LAW_NOTE_PATTERN.match(line)
    )


def _parse_provisions(text: str) -> list[dict[str, Any]]:
    """Parse Swedish statute text into provisions.

    Ported from riksdagen-provision-parser.ts with the same
    chapter activation and section monotonicity checks.

    Returns a list of dicts with keys:
        provision_ref, chapter, section, title, content
    """
    lines = text.split("\n")
    provisions: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    last_ordinal_by_chapter: dict[str, int] = {}

    current_chapter: str | None = None
    pending_chapter: str | None = None
    current_section: str | None = None
    current_title: str | None = None
    pending_title: str | None = None
    current_content: list[str] = []

    def flush_current_section() -> None:
        nonlocal current_section, current_title
        if not current_section or not current_content:
            current_section = None
            current_title = None
            current_content.clear()
            return

        section = _normalize_section_ref(current_section)
        provision_ref = f"{current_chapter}:{section}" if current_chapter else section

        provisions.append(
            {
                "provision_ref": provision_ref,
                "chapter": current_chapter,
                "section": section,
                "title": current_title,
                "content": " ".join(current_content).strip(),
            }
        )

        seen_refs.add(provision_ref)

        if current_chapter:
            ordinal = _section_ordinal(section)
            if ordinal is not None:
                last_ordinal_by_chapter[current_chapter] = ordinal

        current_section = None
        current_title = None
        current_content.clear()

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # Check for chapter marker
        chapter_match = _CHAPTER_PATTERN.match(line)
        if chapter_match:
            flush_current_section()
            pending_chapter = chapter_match.group(1)
            pending_title = None
            continue

        # Check for section marker
        section_match = _SECTION_PATTERN.match(line)
        if section_match:
            normalized_section = _normalize_section_ref(section_match.group(1))
            section_num_match = re.match(r"^(\d+)", normalized_section)
            section_num = int(section_num_match.group(1)) if section_num_match else None
            remainder = section_match.group(2).strip()

            chapter_for_section = current_chapter
            chapter_activated = False

            if pending_chapter:
                if not current_chapter or section_num == 1:
                    chapter_for_section = pending_chapter
                    chapter_activated = chapter_for_section != current_chapter
                pending_chapter = None

            provision_ref = (
                f"{chapter_for_section}:{normalized_section}"
                if chapter_for_section
                else normalized_section
            )

            candidate_ordinal = _section_ordinal(normalized_section)
            current_ordinal = _section_ordinal(current_section) if current_section else None
            last_ordinal = (
                last_ordinal_by_chapter.get(chapter_for_section) if chapter_for_section else None
            )

            # Suppression checks (same as TypeScript parser)
            is_duplicate = provision_ref in seen_refs
            is_out_of_order_current = (
                current_ordinal is not None
                and candidate_ordinal is not None
                and candidate_ordinal <= current_ordinal
            )
            is_out_of_order_history = (
                not chapter_activated
                and last_ordinal is not None
                and candidate_ordinal is not None
                and candidate_ordinal <= last_ordinal
            )
            is_inline_ref = (
                not chapter_activated
                and current_section is not None
                and len(current_content) > 0
                and remainder
                and bool(re.match(r"^[a-zåäö]", remainder))
                # "har upphävts" = repealed section, not an inline reference
                and not remainder.startswith("har upphävts")
            )

            if is_duplicate or is_out_of_order_current or is_out_of_order_history or is_inline_ref:
                if current_section:
                    current_content.append(line)
                continue

            title_for_section = pending_title
            pending_title = None
            flush_current_section()

            current_chapter = chapter_for_section
            current_section = normalized_section
            current_title = title_for_section

            if remainder:
                current_content.append(remainder)
            continue

        # Check for title line
        if not current_section and _is_likely_title(line):
            pending_title = line
            continue

        if current_section and not current_content and _is_likely_title(line):
            current_title = line
            continue

        # Content line
        if current_section:
            current_content.append(line)

    flush_current_section()
    return provisions


# ─────────────────────────────────────────────
# JSON extraction helpers
# ─────────────────────────────────────────────


def _extract_text_from_json(data: bytes) -> str:
    """Extract the plain text field from Riksdagen document JSON.

    Expected structure: {"dokumentstatus": {"dokument": {"text": "..."}}}
    """
    doc_json = json.loads(data)
    doc = doc_json.get("dokumentstatus", {}).get("dokument", {})
    return doc.get("text", "")


def _extract_html_from_json(data: bytes) -> str:
    """Extract the HTML field from Riksdagen document JSON.

    Expected structure: {"dokumentstatus": {"dokument": {"html": "..."}}}
    """
    doc_json = json.loads(data)
    doc = doc_json.get("dokumentstatus", {}).get("dokument", {})
    return doc.get("html", "")


def _extract_dokuppgift(data: bytes) -> dict[str, str]:
    """Extract key-value metadata from dokuppgift in Riksdagen JSON.

    The dokuppgift field contains a list of {uppgift, text} dicts.
    Returns them as a flat dict keyed by uppgift name.
    """
    doc_json = json.loads(data)
    uppgifter = doc_json.get("dokumentstatus", {}).get("dokuppgift", {}).get("uppgift") or []

    result: dict[str, str] = {}
    for item in uppgifter:
        key = item.get("uppgift", "")
        value = item.get("text", "")
        if key:
            result[key] = value
    return result


def _extract_html_metadata(html: str) -> dict[str, str]:
    """Extract metadata from the HTML header of a Riksdagen document.

    Searches for patterns like <b>Key</b>: Value in the first 3000 chars.
    """
    if not html:
        return {}

    header = html[:3000]
    pairs = re.findall(
        r"<b>\s*([^<:]+?)\s*</b>\s*:\s*([^<]+)\s*(?:<br|$)",
        header,
        re.IGNORECASE,
    )

    metadata: dict[str, str] = {}
    for key, value in pairs:
        key = " ".join(key.split()).strip()
        value = " ".join(value.split()).strip()
        if key and value:
            metadata[key] = value
    return metadata


# ─────────────────────────────────────────────
# HTML-based text parsing (improved formatting)
# ─────────────────────────────────────────────

# Chapter headings: <h3 name="K1"><a name="K1">1 kap. Title</a></h3>
_HTML_CHAPTER_RE = re.compile(
    r'<a\s+name="K(\d+)"[^>]*>\s*(\d+)\s*kap\.\s*(.*?)\s*</a>',
    re.IGNORECASE | re.DOTALL,
)

# Section anchors: <a class="paragraf" name="K1P3"><b>3 §</b></a>
_HTML_SECTION_RE = re.compile(
    r'<a\s+class="paragraf"\s+name="K(\d+)P(\d+[a-z]?)"[^>]*>'
    r"\s*<b>\s*(\d+\s*[a-z]?)\s*§\s*</b>\s*</a>",
    re.IGNORECASE,
)

# Sub-headings: <h4 ...><a name="...">Title</a></h4>
_HTML_SUBHEADING_RE = re.compile(
    r"<h4[^>]*>\s*<a[^>]*>\s*(.*?)\s*</a>\s*</h4>",
    re.IGNORECASE | re.DOTALL,
)


def _inline_html_to_md(chunk: str) -> str:
    """Convert inline HTML formatting to Markdown.

    Handles <i>, <b>, <br>, <p> and strips remaining tags.
    Decodes HTML entities.
    """
    text = chunk
    # Italic: law refs <i>Lag (1994:458)</i> and version markers
    text = re.sub(r"<i>\s*(.*?)\s*</i>", r"*\1*", text, flags=re.DOTALL)
    # Bold in body text
    text = re.sub(r"<b>\s*(.*?)\s*</b>", r"**\1**", text, flags=re.DOTALL)
    # <br> → newline
    text = re.sub(r"<br\s*/?>", "\n", text)
    # <p> → paragraph break
    text = re.sub(r"<p[^>]*>", "\n\n", text)
    text = text.replace("</p>", "")
    # Sub-headings → bold line (before stripping tags)
    text = _HTML_SUBHEADING_RE.sub(r"\n\n**\1**\n\n", text)
    # Strip remaining tags (anchors, style, div, etc.)
    text = re.sub(r"<[^>]+>", "", text)
    # Decode HTML entities
    text = html_module.unescape(text)
    # Normalize whitespace within lines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    # Collapse 3+ newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_html_provisions(html: str) -> list[dict[str, Any]]:
    """Parse Riksdagen HTML body into provisions with Markdown formatting.

    Uses HTML structure for section boundaries instead of regex on
    plain text. Properly separates version variants (/Upphör att gälla/,
    /Träder i kraft/) that share the same section anchor.

    Returns the same provision dict format as _parse_provisions().
    """
    # Find body after <hr>
    hr_match = re.search(r"<hr\s*/?>", html)
    if not hr_match:
        return []
    body = html[hr_match.end() :]

    # Strip TOC and style blocks
    body = re.sub(r"<div\s+class=\"sfstoc\">.*?</div>", "", body, flags=re.DOTALL)
    body = re.sub(r"<style[^>]*>.*?</style>", "", body, flags=re.DOTALL)

    # Find all structural markers with positions
    markers: list[tuple[str, int, int, str, str, str]] = []

    for m in _HTML_CHAPTER_RE.finditer(body):
        # Strip HTML from title text (may contain tags)
        title = re.sub(r"<[^>]+>", "", m.group(3)).strip()
        markers.append(("chapter", m.start(), m.end(), m.group(1), m.group(2), title))

    for m in _HTML_SECTION_RE.finditer(body):
        markers.append(("section", m.start(), m.end(), m.group(1), m.group(2), m.group(3)))

    markers.sort(key=lambda x: x[1])

    if not markers:
        return []

    # Build provisions
    provisions: list[dict[str, Any]] = []
    current_chapter: str | None = None
    pending_chapter_title: str | None = None
    seen_keys: set[str] = set()

    for i, marker in enumerate(markers):
        marker_type, _start, end = marker[0], marker[1], marker[2]

        # Content: from end of this marker to start of next marker
        next_start = markers[i + 1][1] if i + 1 < len(markers) else len(body)
        content_html = body[end:next_start]
        content_md = _inline_html_to_md(content_html)

        if marker_type == "chapter":
            current_chapter = marker[3]
            pending_chapter_title = marker[5] or None
            continue

        # Section marker
        sec_num_raw = marker[4]

        # Normalize: "3a" → "3 a", "3" → "3"
        section_ref = re.sub(r"(\d+)([a-z])", r"\1 \2", sec_num_raw).strip()

        key = f"{current_chapter}:{section_ref}" if current_chapter else section_ref

        if key in seen_keys:
            # Version variant (duplicate anchor) — merge into existing provision
            for prov in reversed(provisions):
                if prov.get("_key") == key:
                    prov["content"] += f"\n\n{content_md}"
                    break
        else:
            seen_keys.add(key)
            provision_ref = f"{current_chapter}:{section_ref}" if current_chapter else section_ref

            title = pending_chapter_title
            pending_chapter_title = None

            provisions.append(
                {
                    "provision_ref": provision_ref,
                    "chapter": current_chapter,
                    "section": section_ref,
                    "title": title,
                    "content": content_md,
                    "_key": key,
                }
            )

    # Clean up internal tracking key
    for prov in provisions:
        prov.pop("_key", None)

    return provisions


# ─────────────────────────────────────────────
# SFSR amendment register parsing
# ─────────────────────────────────────────────

_SFSR_AMENDMENT_PATTERN = re.compile(r"Ändring,\s*SFS\s+(\d{4}:\d+)")
_SFSR_OMFATTNING_PATTERN = re.compile(r"Omfattning:\s*([^\n<]+)")
_SFSR_SECTION_PATTERN = re.compile(
    r"(?:ändr?\.?|ny|nya|upph\.?)\s+([\d\s,]+)\s*kap\.\s*([\d\s,a-z§]+)",
    re.IGNORECASE,
)
_SFSR_SIMPLE_SECTION_PATTERN = re.compile(
    r"(?:ändr?\.?|ny|nya|upph\.?)\s+([\d\s,a-z]+)\s*§§?",
    re.IGNORECASE,
)


def _parse_affected_sections(omfattning: str) -> tuple[str, ...]:
    """Parse the Omfattning field to extract affected section references.

    Examples:
        "ändr. 1 kap. 3, 5 §§" -> ("1:3", "1:5")
        "ändr. 3, 5 §§" -> ("3", "5")
        "ny 2 kap. 4 a §" -> ("2:4 a",)
    """
    sections: list[str] = []

    # Match chapter-qualified sections: "1 kap. 3, 5 §§"
    for match in _SFSR_SECTION_PATTERN.finditer(omfattning):
        chapters_str = match.group(1).strip()
        sections_str = match.group(2).strip()

        # Parse chapter numbers (usually just one)
        chapters = [c.strip() for c in re.split(r"[,\s]+", chapters_str) if c.strip()]

        # Parse section numbers: "3, 5" or "4 a"
        # Split on commas, then clean up
        section_parts = [s.strip().rstrip("§ ") for s in sections_str.split(",")]
        section_parts = [s.strip() for s in section_parts if s.strip()]

        for chapter in chapters:
            for section in section_parts:
                if section and re.match(r"^\d+", section):
                    sections.append(f"{chapter}:{section}")

    # Match non-chapter sections: "ändr. 3, 5 §§"
    if not sections:
        for match in _SFSR_SIMPLE_SECTION_PATTERN.finditer(omfattning):
            sections_str = match.group(1).strip()
            section_parts = [s.strip() for s in sections_str.split(",")]
            for section in section_parts:
                section = section.strip()
                if section and re.match(r"^\d+", section):
                    sections.append(section)

    return tuple(sections)


def _parse_sfsr_html(html: str) -> list[Reform]:
    """Parse the SFSR HTML to extract amendment history.

    Looks for entries like "Ändring, SFS YYYY:NNN" followed by
    "Omfattning:" fields describing affected sections.

    Returns a list of Reform objects.
    """
    reforms: list[Reform] = []

    # Split by amendment entries
    entries = _SFSR_AMENDMENT_PATTERN.split(html)

    # entries[0] is before the first match, then alternating: sfs_number, content
    for i in range(1, len(entries), 2):
        sfs_number = entries[i]
        content = entries[i + 1] if i + 1 < len(entries) else ""

        # Extract Omfattning
        omfattning_match = _SFSR_OMFATTNING_PATTERN.search(content)
        affected = ()
        if omfattning_match:
            affected = _parse_affected_sections(omfattning_match.group(1))

        # Extract date from the SFS number (year part)
        year_match = re.match(r"(\d{4})", sfs_number)
        if year_match:
            year = int(year_match.group(1))
            # Use January 1 of the year as approximate date
            # (exact date would require additional lookup)
            reform_date = date(year, 1, 1)
        else:
            continue

        reforms.append(
            Reform(
                date=reform_date,
                norm_id=f"SFS {sfs_number}",
                affected_blocks=affected,
            )
        )

    return reforms


# ─────────────────────────────────────────────
# Public classes — TextParser / MetadataParser
# ─────────────────────────────────────────────


class SwedishTextParser(TextParser):
    """Parses Riksdagen JSON document text into Block objects."""

    def parse_text(self, data: bytes) -> list[Any]:
        """Parse the Riksdagen JSON into a list of Block objects.

        Prefers the HTML field (preserves formatting and separates
        version variants). Falls back to plain text if no usable
        HTML structure is found.

        Args:
            data: Full Riksdagen document JSON as bytes.

        Returns:
            List of Block objects (sections and articles).
        """
        # Try HTML first — better formatting and version separation
        html = _extract_html_from_json(data)
        if html and '<a class="paragraf"' in html:
            provisions = _parse_html_provisions(html)
            if provisions:
                return _provisions_to_blocks(provisions)

        # Fallback: plain text
        text = _extract_text_from_json(data)
        if not text:
            logger.warning("No text content in Riksdagen document")
            return []

        provisions = _parse_provisions(text)
        return _provisions_to_blocks(provisions)

    def extract_reforms(self, data: bytes) -> list[Any]:
        """Extract amendment history from SFSR HTML embedded in data.

        The data bytes are expected to contain a combined JSON with
        both the document text AND the SFSR HTML. If no SFSR data
        is available, extracts what reform info is possible from
        the document metadata.

        Args:
            data: Combined JSON bytes with optional SFSR HTML.

        Returns:
            List of Reform objects.
        """
        try:
            combined = json.loads(data)
        except json.JSONDecodeError:
            logger.warning("Failed to parse reform data as JSON")
            return []

        # Check for SFSR HTML in the combined data
        sfsr_html = combined.get("sfsr_html", "")
        if sfsr_html:
            return _parse_sfsr_html(sfsr_html)

        # Fallback: try to extract from document HTML metadata
        doc = combined.get("dokumentstatus", {}).get("dokument", {})
        html = doc.get("html", "")
        if html:
            html_meta = _extract_html_metadata(html)
            amended_through = html_meta.get("Ändrad t.o.m.", "")
            if amended_through:
                sfs_match = re.match(r"SFS\s+(\d{4}:\d+)", amended_through)
                if sfs_match:
                    sfs = sfs_match.group(1)
                    year = int(sfs[:4])
                    return [
                        Reform(
                            date=date(year, 1, 1),
                            norm_id=f"SFS {sfs}",
                            affected_blocks=(),
                        )
                    ]

        return []

    def extract_reforms_from_sfsr(self, sfsr_html: bytes | str) -> list[Reform]:
        """Parse raw SFSR HTML into Reform objects.

        Called directly when SFSR HTML is fetched separately (not embedded in JSON).
        """
        if isinstance(sfsr_html, bytes):
            sfsr_html = sfsr_html.decode("utf-8", errors="replace")
        return _parse_sfsr_html(sfsr_html)


class SwedishMetadataParser(MetadataParser):
    """Parses metadata from Riksdagen document JSON."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        """Parse Riksdagen JSON into NormMetadata.

        Extracts metadata from the dokumentstatus.dokument and
        dokumentstatus.dokuppgift fields.

        Args:
            data: Full Riksdagen document JSON as bytes.
            norm_id: The SFS number, e.g. "1962:700".

        Returns:
            NormMetadata with Swedish-specific fields.

        Raises:
            ValueError: If essential metadata cannot be extracted.
        """
        try:
            doc_json = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON for SFS {norm_id}") from exc

        doc = doc_json.get("dokumentstatus", {}).get("dokument", {})
        dokuppgift = _extract_dokuppgift(data)

        # Title
        title = doc.get("titel", "") or dokuppgift.get("titel", "") or f"SFS {norm_id}"
        title = " ".join(title.split()).strip()

        # Short title
        short_title = _short_title_se(title, norm_id)

        # Department (organ)
        department = doc.get("organ", "").strip()

        # Dates
        html = doc.get("html", "")
        html_meta = _extract_html_metadata(html)

        issued_date_str = html_meta.get("Utfärdad") or doc.get("datum", "")
        pub_date = _parse_date_se(issued_date_str)
        if pub_date is None:
            # Fallback: use the year from the SFS number
            year_match = re.match(r"(\d{4})", norm_id)
            if year_match:
                pub_date = date(int(year_match.group(1)), 1, 1)
            else:
                raise ValueError(f"Could not extract publication date for SFS {norm_id}")

        amended_through_raw = html_meta.get("Ändrad t.o.m.", "") or html_meta.get("Ändrad", "")
        modif_date = _parse_date_se(amended_through_raw)

        # Status + repeal info
        status = NormStatus.IN_FORCE
        repeal_date_str = html_meta.get("Upphävd", "")
        if repeal_date_str:
            status = NormStatus.REPEALED

        # Rank
        rank = _detect_rank(title)

        # Identifier
        # Normalize for filesystem: "1962:700" → "SFS-1962-700"
        # Also strip spaces from old SFS numbers like "1851-55 s.4" → "SFS-1851-55s.4"
        safe_norm = norm_id.replace(":", "-").replace(" ", "")
        identifier = f"SFS-{safe_norm}"

        # Source URL
        sfs_slug = norm_id.replace(":", "-")
        source_url = (
            f"https://www.riksdagen.se/sv/dokument-och-lagar/"
            f"dokument/svensk-forfattningssamling/sfs-{sfs_slug}"
        )

        # Extra fields (country-specific, rendered in frontmatter)
        extra: list[tuple[str, str]] = []

        # Amended through: latest SFS amendment
        amended_through = amended_through_raw.strip()
        if amended_through:
            # Clean "t.o.m. SFS 2026:253" → "SFS 2026:253"
            cleaned = re.sub(r"^t\.o\.m\.\s*", "", amended_through)
            extra.append(("amended_through", cleaned))

        # Repeal info
        if repeal_date_str:
            extra.append(("repeal_date", repeal_date_str.strip()))
        repealed_by = html_meta.get("Författningen har upphävts genom", "").strip()
        if repealed_by:
            extra.append(("repealed_by", repealed_by))

        # Reprints (Omtryck)
        reprints = html_meta.get("Omtryck", "").strip()
        if reprints:
            extra.append(("reprints", reprints))

        # Notes (Övrig text — errata, corrections)
        notes = html_meta.get("Övrig text", "").strip()
        if notes:
            extra.append(("notes", notes))

        return NormMetadata(
            title=title,
            short_title=short_title,
            identifier=identifier,
            country="se",
            rank=rank,
            publication_date=pub_date,
            status=status,
            department=department,
            source=source_url,
            last_modified=modif_date,
            extra=tuple(extra),
        )


# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────


def _short_title_se(raw_title: str, norm_id: str) -> str:
    """Generate a short title for a Swedish statute.

    Examples:
        "Brottsbalk (1962:700)" -> "Brottsbalken"
        "Lag (2018:218) med kompletterande..." -> "Lag (2018:218)"
        "Tryckfrihetsförordningen (1949:105)" -> "Tryckfrihetsförordningen"
    """
    if not raw_title:
        return f"SFS {norm_id}"

    # If title starts with a known short form, extract it
    # Pattern: "Name (YYYY:NNN) rest..." -> "Name"
    match = re.match(r"^([^(]+?)\s*\(\d{4}:\d+\)", raw_title)
    if match:
        short = match.group(1).strip()
        # For "Lag" or "Förordning" alone, include the SFS number
        if short.lower() in ("lag", "förordning"):
            sfs_match = re.search(r"\((\d{4}:\d+)\)", raw_title)
            if sfs_match:
                return f"{short} ({sfs_match.group(1)})"
        return short

    # Truncate at first parenthesis
    paren_idx = raw_title.find("(")
    if paren_idx > 0:
        return raw_title[:paren_idx].strip()

    return raw_title


def _provisions_to_blocks(provisions: list[dict[str, Any]]) -> list[Block]:
    """Convert parsed provisions to Block objects.

    Groups provisions by chapter, creating section Blocks for
    chapter headings and article Blocks for individual sections.
    """
    blocks: list[Block] = []
    current_chapter: str | None = None

    for prov in provisions:
        chapter = prov.get("chapter")
        section = prov.get("section", "")
        provision_ref = prov.get("provision_ref", "")
        title = prov.get("title")
        content = prov.get("content", "")

        # Emit chapter heading when chapter changes
        if chapter and chapter != current_chapter:
            current_chapter = chapter
            chapter_title = f"{chapter} kap."
            if title:
                chapter_title = f"{chapter} kap. {title}"

            blocks.append(
                Block(
                    id=f"kap_{chapter}",
                    block_type="section",
                    title=chapter_title,
                    versions=(
                        Version(
                            norm_id="",
                            publication_date=date(1900, 1, 1),
                            effective_date=date(1900, 1, 1),
                            paragraphs=(
                                Paragraph(
                                    css_class="titulo_tit",
                                    text=chapter_title,
                                ),
                            ),
                        ),
                    ),
                )
            )

        # Build paragraphs for the section/article
        paragraphs: list[Paragraph] = []

        # Section number as heading
        if section:
            section_label = f"{section} §"
            paragraphs.append(Paragraph(css_class="articulo", text=section_label))

        # Section title if present
        if title and chapter == current_chapter:
            # Only add title if it was not already used as chapter title
            pass

        # Content paragraphs — split on double newlines for version markers
        if content:
            for para_text in content.split("\n\n"):
                para_text = para_text.strip()
                if para_text:
                    paragraphs.append(Paragraph(css_class="parrafo", text=para_text))

        if paragraphs:
            blocks.append(
                Block(
                    id=provision_ref or f"s_{section}",
                    block_type="article",
                    title=f"{section} §" if section else provision_ref,
                    versions=(
                        Version(
                            norm_id="",
                            publication_date=date(1900, 1, 1),
                            effective_date=date(1900, 1, 1),
                            paragraphs=tuple(paragraphs),
                        ),
                    ),
                )
            )

    return blocks
