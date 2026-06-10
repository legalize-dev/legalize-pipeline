"""Israeli legislation parser (il) for metadata and text."""

from __future__ import annotations

import json
import logging
import re
from datetime import date

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    Rank,
    Version,
)
from legalize.fetcher.il.dates_il import parse_gregorian_date

logger = logging.getLogger(__name__)


def clean_title(title: str) -> str:
    """Cleans a Hebrew law title to produce a short title.

    Removes Hebrew calendar years and Gregorian year suffixes.
    Example:
        חוק רשות הפיתוח (העברת נכסים), התש"י-1950 -> חוק רשות הפיתוח (העברת נכסים)
    """
    if not title:
        return ""
    # Strip everything after ', התש...' or ', התש...' or similar
    title = title.strip()
    match = re.search(r",\s*התש[א-ת\"\'׳״]+-\d+", title)
    if match:
        return title[: match.start()].strip()

    # Fallback to general year pattern
    match = re.search(r",\s*התש[א-ת\"\'׳״]+", title)
    if match:
        return title[: match.start()].strip()

    return title


# Article/section markers. Hebrew laws number sections as "N." (logical order) or, in
# visual-order legacy PDFs, as ".N" / ",N" optionally preceded by a short marginal heading
# (the side-note title of the section). Subsections like "(א)" / "(2)" are NOT markers.
_ARTICLE_SEIF = re.compile(r"^סעיף\s+(\d{1,3})")
_ARTICLE_NUM_DOT = re.compile(r"^(\d{1,3})[.)]\s")
_ARTICLE_MARGIN = re.compile(r"^([\u05d0-\u05ea\"'’״׳\- ]{0,40}?)\s*[.,](\d{1,3})(?=[\s(])")


def _detect_marker(line: str) -> tuple[str, str, str, str] | None:
    """Detect a chapter/article marker in a line.

    Returns ``(kind, marker, title, remainder)`` where ``kind`` is ``"chapter"`` or
    ``"article"``, ``marker`` is the section number, ``title`` is the heading to use, and
    ``remainder`` is the body text after the marker. Returns ``None`` for ordinary lines.
    """
    if line.startswith("פרק "):
        return ("chapter", "", line, "")

    m = _ARTICLE_SEIF.match(line) or _ARTICLE_NUM_DOT.match(line)
    if m:
        return ("article", m.group(1), f"סעיף {m.group(1)}", line[m.end() :].strip())

    m = _ARTICLE_MARGIN.match(line)
    if m:
        head, num = m.group(1).strip(), m.group(2)
        return ("article", num, head or f"סעיף {num}", line[m.end() :].strip())

    return None


class IsraelMetadataParser(MetadataParser):
    """Parses Israel law metadata from compiled OData JSON."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        """Parses the JSON package returned by get_metadata."""
        pkg = json.loads(data.decode("utf-8"))
        law = pkg.get("law", {})
        names = pkg.get("names", [])
        classifications = pkg.get("classifications", [])
        ministries = pkg.get("ministries", [])

        # Get latest title from names, or fallback to main Name
        title = law.get("Name", "")
        if names:
            sorted_names = sorted(names, key=lambda x: x.get("LastUpdatedDate", ""), reverse=True)
            title = sorted_names[0].get("Name", title) or title

        short_title = clean_title(title)

        # Rank determination
        is_basic = law.get("IsBasicLaw", False)
        if is_basic or "חוק-יסוד" in title or "חוק יסוד" in title:
            rank = Rank("basic_law")
        elif "פקודת" in title:
            rank = Rank("ordinance")
        elif "תקנות" in title:
            rank = Rank("regulation")
        else:
            rank = Rank("law")

        # Dates
        pub_date = parse_gregorian_date(law.get("PublicationDate"))
        if not pub_date:
            pub_date = parse_gregorian_date(law.get("LastUpdatedDate")) or date.today()

        last_mod = parse_gregorian_date(law.get("LatestPublicationDate")) or parse_gregorian_date(
            law.get("LastUpdatedDate")
        )

        # Status
        validity = law.get("LawValidityDesc")
        if validity == "תקף":
            status = NormStatus.IN_FORCE
        elif validity == "בטל":
            status = NormStatus.REPEALED
        else:
            status = NormStatus.IN_FORCE

        # Department / Ministry
        dept_list = [
            m.get("MinistryCategoryDesc", "") for m in ministries if m.get("MinistryCategoryDesc")
        ]
        department = ", ".join(sorted(set(dept_list))) if dept_list else "Knesset"

        # Source URL
        source_url = f"https://main.knesset.gov.il/Activity/Legislation/Laws/Pages/LawBill.aspx?lawitemid={norm_id}"

        # Subjects
        subjects = tuple(
            sorted(
                set(
                    c.get("ClassificiationDesc")
                    for c in classifications
                    if c.get("ClassificiationDesc")
                )
            )
        )

        # Extra metadata
        extra = [
            ("knesset_num", str(law.get("KnessetNum") or "")),
            ("is_budget_law", str(law.get("IsBudgetLaw") or "False")),
            ("is_favorite_law", str(law.get("IsFavoriteLaw") or "False")),
        ]

        return NormMetadata(
            title=title,
            short_title=short_title,
            identifier=norm_id,
            country="il",
            rank=rank,
            publication_date=pub_date,
            status=status,
            department=department,
            source=source_url,
            last_modified=last_mod,
            subjects=subjects,
            extra=tuple(extra),
        )


class IsraelTextParser(TextParser):
    """Parses Knesset law text and reforms."""

    def parse_text(self, data: bytes) -> list[Block]:
        """Parses the text package into sequential Blocks with version history."""
        # Retrieve the metadata first to know the publication date
        pkg = json.loads(data.decode("utf-8"))
        original_text = pkg.get("original_text", "")
        reforms_text = pkg.get("reforms_text", [])

        pub_date = parse_gregorian_date(pkg.get("publication_date")) or date(1950, 1, 1)

        blocks: list[Block] = []

        if not original_text:
            return blocks

        # Parse original text into blocks
        lines = [line.strip() for line in original_text.splitlines() if line.strip()]

        current_block_paragraphs: list[str] = []
        current_block_id = "preamble"
        current_block_title = "Preamble"
        current_block_type = "preamble"

        for p in lines:
            marker = _detect_marker(p)

            if marker:
                if current_block_paragraphs or current_block_type != "preamble":
                    blocks.append(
                        Block(
                            id=current_block_id,
                            block_type=current_block_type,
                            title=current_block_title,
                            versions=(
                                Version(
                                    norm_id="",
                                    publication_date=pub_date,
                                    effective_date=pub_date,
                                    paragraphs=tuple(
                                        Paragraph(css_class="parrafo", text=txt)
                                        for txt in current_block_paragraphs
                                    ),
                                ),
                            ),
                        )
                    )
                    current_block_paragraphs = []

                kind, num, title, remainder = marker
                if kind == "chapter":
                    current_block_id = f"chapter_{len(blocks)}"
                    current_block_title = title
                    current_block_type = "section"
                else:
                    current_block_id = f"article_{num}_{len(blocks)}"
                    current_block_title = title[:50]
                    current_block_type = "article"
                if remainder:
                    current_block_paragraphs.append(remainder)
            else:
                current_block_paragraphs.append(p)

        if current_block_paragraphs or current_block_type != "preamble":
            blocks.append(
                Block(
                    id=current_block_id,
                    block_type=current_block_type,
                    title=current_block_title,
                    versions=(
                        Version(
                            norm_id="",
                            publication_date=pub_date,
                            effective_date=pub_date,
                            paragraphs=tuple(
                                Paragraph(css_class="parrafo", text=txt)
                                for txt in current_block_paragraphs
                            ),
                        ),
                    ),
                )
            )

        # Append amending blocks from reforms_text, dated to their real effective date.
        # Sort chronologically so each law's commits are written oldest-first.
        dated_reforms = sorted(
            (
                (parse_gregorian_date(reform.get("date")) or pub_date, reform)
                for reform in reforms_text
            ),
            key=lambda item: item[0],
        )

        for ref_date, reform in dated_reforms:
            ref_text = reform.get("text", "")
            ref_bill_id = str(reform.get("bill_id", ""))

            ref_lines = [line.strip() for line in ref_text.splitlines() if line.strip()]
            if ref_lines:
                blocks.append(
                    Block(
                        id=f"amendment_{ref_bill_id}",
                        block_type="amendment",
                        title=f"Amendment {ref_bill_id}",
                        versions=(
                            Version(
                                norm_id=ref_bill_id,
                                publication_date=ref_date,
                                effective_date=ref_date,
                                paragraphs=tuple(
                                    Paragraph(css_class="parrafo", text=txt) for txt in ref_lines
                                ),
                            ),
                        ),
                    )
                )

        return blocks
