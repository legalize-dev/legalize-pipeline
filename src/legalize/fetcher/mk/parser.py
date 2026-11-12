"""LDBIS metadata and PDF text parsers."""

from __future__ import annotations

import io
import os
import re
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.fetcher.mk.client import canonical_identifier, parse_card
from legalize.models import Block, NormMetadata, NormStatus, Paragraph, Rank, Version


TABLE_ROW = re.compile(r"\| .* \|")
# How a law's lines become paragraphs, as render_body in legalize-mk/tools/build.py built the
# published corpus. A PDF line break is only wrapping, so lines join into one paragraph until a
# paragraph mark, an article heading, a heading in capitals or a line opening a numbered or
# lettered item. Without it every printed line was its own paragraph (5,481 of 5,544 laws).
ARTICLE_HEADING = re.compile(r"^(?:Член|Article|ARTICLE)\s+(\d+[а-я]?|[IVXL]+)\.?$")
ROMAN_HEADING = re.compile(r"^[IVX]+\s*[-.–]\s*\S")
NEW_PARAGRAPH = re.compile(r"^(\(\d+\)|\d+\.|[-–•]|„?[а-я]\)|\d+\))\s")
LOWERCASE = re.compile(r"[а-шa-z]")
UPPERCASE = re.compile(r"[А-ЯA-Z]")
HYPHENATED = re.compile(r"[а-яА-ЯѓЃќЌљЉњЊџЏѕЅa-zA-Z]-$")


def _joined_hyphens(lines: list[str]) -> list[str]:
    """Rejoin a word the typesetter hyphenated at a line end."""
    out: list[str] = []
    for line in lines:
        if out and HYPHENATED.search(out[-1]) and line[:1].islower():
            out[-1] = out[-1][:-1] + line
        else:
            out.append(line)
    return out


def _paragraphs(lines: list[str], paragraph_mark: str) -> list[Paragraph]:
    out: list[Paragraph] = []
    words: list[str] = []
    rows: list[str] = []
    after_heading = False

    def flush() -> None:
        if words:
            out.append(Paragraph(css_class="parrafo", text=" ".join(words)))
            words.clear()

    # A table's rows are one paragraph: the renderer puts a blank line between paragraphs,
    # which would end a pipe table after its first row. A paragraph mark ends a table, so two
    # tables in a row stay two. A row is "| cell | cell |" as with_tables writes it: OCR reads
    # a printed bracket as a bar ("|Option 3" in RM-2008-18-14566), and such a line is text.
    for line in [*_joined_hyphens(lines), paragraph_mark]:
        if TABLE_ROW.fullmatch(line):
            flush()
            rows.append(line)
            after_heading = False
            continue
        if rows:
            out.append(Paragraph(css_class="table", text="\n".join(rows)))
            rows = []
        if line == paragraph_mark:
            flush()
            continue
        capitals = not LOWERCASE.search(line) and UPPERCASE.search(line)
        if article := ARTICLE_HEADING.match(line):
            flush()
            out.append(Paragraph(css_class="articulo", text=article.group(0).rstrip(".")))
        # A title in capitals wraps onto the next line, which continues the heading above.
        elif (
            ROMAN_HEADING.match(line)
            or (capitals and len(line) > 3 and re.search(r"[А-ЯA-Z]{3}", line))
            or (capitals and after_heading)
        ):
            flush()
            if (
                after_heading
                and out
                and out[-1].css_class == "titulo"
                and not ROMAN_HEADING.match(line)
            ):
                out[-1] = Paragraph(css_class="titulo", text=f"{out[-1].text} {line}")
            else:
                out.append(Paragraph(css_class="titulo", text=line))
            after_heading = True
            continue
        else:
            if NEW_PARAGRAPH.match(line):
                flush()
            words.append(line)
        after_heading = False
    return out


def _date(value: str) -> date:
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Invalid LDBIS date: {value!r}")


def _fix_ldbis_ocr_artifacts(text: str) -> str:
    """Apply the shared, vocabulary-checked LDBIS OCR cleanup to extracted text."""
    from legalize.fetcher.mk.ocr import fix_quote_artifacts

    return fix_quote_artifacts(text)


def _table_to_markdown(rows: list[list[str | None]]) -> str:
    """Render a non-empty pdfplumber table as a pipe table."""
    rows = [[re.sub(r"\s+", " ", cell or "").strip() for cell in row] for row in rows]
    rows = [row for row in rows if any(row)]
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    escaped = [[cell.replace("|", "\\|") for cell in row] for row in padded]
    separator = ["---"] * width
    lines = ["| " + " | ".join(escaped[0]) + " |", "| " + " | ".join(separator) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in escaped[1:])
    return "\n".join(lines)


class LDBISMetadataParser(MetadataParser):
    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        card = parse_card(data, norm_id)
        if not card["title"] or not card["publication_date"]:
            raise ValueError(f"LDBIS card {norm_id} lacks title or publication date")
        status = NormStatus.REPEALED if card["inactive"] else NormStatus.IN_FORCE
        identifier = canonical_identifier(card)
        year = card["publication_date"][-4:]
        issue = card["issue"] or ""
        gazette_issue = issue if "/" in issue else f"{issue}/{year}" if issue else ""
        extra_values = {
            "ldbis_id": card["id"],
            "institution": card["institution"],
            "gazette": card["gazette"],
            "gazette_issue": gazette_issue,
            "territory": card["territory"],
            "language": "mk",
            "in_force_date": _date(card["effective_date"]).isoformat()
            if card["effective_date"]
            else "",
            "applies_from": _date(card["applies_from"]).isoformat() if card["applies_from"] else "",
            "expiry_date": _date(card["expiry_date"]).isoformat() if card["expiry_date"] else "",
            "version": card["version"],
        }
        extra = tuple((key, value) for key, value in extra_values.items() if value)
        return NormMetadata(
            title=card["title"],
            short_title=card["title"],
            identifier=identifier,
            country="mk",
            rank=Rank(card["rank"] or "закон"),
            publication_date=_date(card["publication_date"]),
            status=status,
            department=card["institution"],
            source=card["source"],
            last_modified=_date(card["publication_date"]),
            extra=extra,
        )


class LDBISTextParser(TextParser):
    def parse_text(self, data: bytes, metadata: NormMetadata | None = None) -> list[Block]:
        try:
            import pdfplumber
        except ImportError as exc:
            raise RuntimeError("LDBIS PDF parsing requires the pipeline PDF dependencies") from exc
        paragraphs: list[Paragraph] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
                # Keep LF and tab because they carry the PDF's line and cell
                # structure; strip the remaining C0/C1 controls.
                text = re.sub(r"[\x00-\x09\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)
                text = _fix_ldbis_ocr_artifacts(text)
                for line in text.splitlines():
                    line = re.sub(r"\s+", " ", line).strip()
                    if line:
                        css_class = "articulo" if re.match(r"^Член\s+\d+\b", line) else "parrafo"
                        paragraphs.append(Paragraph(css_class=css_class, text=line))
                for table in page.find_tables():
                    table_markdown = _table_to_markdown(table.extract())
                    if table_markdown:
                        paragraphs.append(Paragraph(css_class="table", text=table_markdown))
        return self._blocks(paragraphs, metadata.publication_date if metadata else None)

    def parse_norm_text(self, data: bytes, norm_id: str, metadata: NormMetadata):
        """Run the reviewed full LDBIS OCR and cleanup path for a fetched norm."""
        from legalize.fetcher.mk.ocr import PARAGRAPH, parse_pdf

        cache_dir = Path(
            os.environ.get(
                "LEGALIZE_MK_OCR_CACHE",
                Path.home() / ".cache" / "legalize" / "mk-ocr",
            )
        )
        lines, details = parse_pdf(data, norm_id, metadata.title, cache_dir)
        lines = [_fix_ldbis_ocr_artifacts(line) for line in lines]
        paragraphs = _paragraphs(lines, PARAGRAPH)

        if details["text_source"]:
            extra = dict(metadata.extra)
            extra["text_source"] = details["text_source"]
            if details["doubtful_pages"]:
                extra["ocr_doubtful_pages"] = tuple(details["doubtful_pages"])
            if details["unread_pages"]:
                extra["ocr_unread_pages"] = tuple(details["unread_pages"])
            metadata = replace(metadata, extra=tuple(extra.items()))
        return self._blocks(paragraphs, metadata.publication_date), metadata

    @staticmethod
    def _blocks(paragraphs: list[Paragraph], publication_date: date | None = None) -> list[Block]:
        if not paragraphs:
            return []
        # The version is dated by the card, never by a date read from the body, which may be a
        # deadline later than the act and would empty its commit.
        if publication_date is None:
            raise ValueError("LDBIS text has no card date; pass the card metadata to the parser")
        version = Version(
            norm_id="",
            publication_date=publication_date,
            effective_date=None,
            paragraphs=tuple(paragraphs),
        )
        return [Block(id="body", block_type="article", title="", versions=(version,))]
