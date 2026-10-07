"""Read the text layer of CELLAR consolidated PDFs unavailable as HTML."""

from __future__ import annotations

import io
import re
from itertools import groupby

import pdfplumber
from lxml import etree

from legalize.fetcher._tables import render_table
from legalize.fetcher._text import strip_control
from legalize.models import Paragraph

_MARKER = re.compile(r"[►▼]\*{0,3}[A-Z]\d*\*{0,3}|[◄▲]")
_HEADER = re.compile(r"^(?:\d{4}[A-Z]\d{4}\s*[—–-]\s*EN\b|\d+/\d{2}\s*---)")
_ARTICLE = re.compile(r"^Article\s+\d+\w*\s*$")
_LIST = re.compile(r"^(?:\d+\.|\([a-z\d]+\)|[—–])\s")


class UnsupportedPDF(ValueError):
    """The source needs OCR or mathematical/rotated layout recovery."""


def _inline(line: dict) -> str:
    """Preserve font emphasis and the PDF's actual word gaps."""
    runs = []
    previous = None
    for font, chars in groupby(line["chars"], key=lambda c: c["fontname"]):
        text = ""
        for char in chars:
            if previous and char["x0"] - previous["x1"] > 1:
                text += " "
            text += char["text"]
            previous = char
        text = strip_control(text)
        body = text.strip()
        if not body:
            runs.append(text)
            continue
        before = text[: len(text) - len(text.lstrip())]
        after = text[len(text.rstrip()) :]
        if "Bold" in font:
            body = f"**{body}**"
        if "Italic" in font:
            body = f"*{body}*"
        runs.append(before + body + after)
    return _MARKER.sub("", "".join(runs)).strip()


def parse_pdf(data: bytes) -> list[Paragraph]:
    """Skip consolidation covers and running headers, retain the legal body.

    PDF/A and older PDF manifestations use the same CELLAR layout. A missing
    body marker or unreadable text fails the fetch rather than emitting a cover.
    """
    paragraphs: list[Paragraph] = []
    started = False
    legal_text = False
    pending = ""
    previous = None

    def flush() -> None:
        nonlocal pending
        if pending:
            paragraphs.append(Paragraph("abs", pending))
            pending = ""

    def validate_page(page) -> None:
        if any("(cid:" in c["text"] or "\ufffd" in c["text"] for c in page.chars):
            raise UnsupportedPDF("Unreadable CELLAR PDF text layer, including tables")
        if any("AdvP4C4E" in c["fontname"] for c in page.chars):
            raise UnsupportedPDF("CELLAR PDF mathematical glyphs require layout-aware validation")
        text_length = sum(len(c["text"]) for c in page.chars)
        if page.images and text_length < 120:
            raise UnsupportedPDF("CELLAR PDF contains rasterized legal text")

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page_index, page in enumerate(pdf.pages):
            # AdvPi3's old custom CMap exposes triangle glyphs as punctuation.
            for char in page.chars:
                if "AdvPi3" in char["fontname"]:
                    char["text"] = {"!": "▼", '"': "►", "3": "◄"}.get(char["text"], char["text"])
            if started:
                validate_page(page)
            lines = page.extract_text_lines(x_tolerance=1)
            tables = page.find_tables()
            events = [(line["top"], "line", line) for line in lines]
            events.extend((table.bbox[1], "table", table) for table in tables)
            for _, kind, item in sorted(events, key=lambda event: event[0]):
                if kind == "table":
                    if not started:
                        continue
                    flush()
                    element = etree.Element("table")
                    for cells in item.extract(x_tolerance=0.5):
                        row = etree.SubElement(element, "tr")
                        for cell in cells:
                            etree.SubElement(row, "td").text = " ".join((cell or "").split())
                    text = render_table(element, lambda node: "".join(node.itertext()))
                    if text:
                        paragraphs.append(Paragraph("table", text))
                    previous = None
                    continue
                plain = item["text"].strip()
                if not started:
                    if re.fullmatch(r"▼\s*B", plain):
                        validate_page(page)
                        started = True
                        continue
                    # Pre-CELLAR PDFs have a cover, then a body with no markers.
                    if page_index and re.match(r"THE\s|Having regard|Article\s", plain):
                        validate_page(page)
                        started = True
                    else:
                        continue
                if _HEADER.match(plain) or not _MARKER.sub("", plain).strip():
                    continue
                if any(
                    table.bbox[0] <= item["x0"]
                    and item["x1"] <= table.bbox[2] + 1
                    and table.bbox[1] <= item["top"] <= table.bbox[3]
                    for table in tables
                ):
                    continue
                plain = _MARKER.sub("", strip_control(plain)).strip()
                if not legal_text:
                    if re.match(r"THE\s|Having regard|Whereas|HAS ADOPTED|Article\s|ANNEX", plain):
                        legal_text = True
                    else:
                        continue
                if item["top"] > page.height - 35 and re.fullmatch(r"\d+|[IVXLCDM]+", plain):
                    continue
                if "\ufffd" in plain or "(cid:" in plain:
                    raise UnsupportedPDF("Unreadable CELLAR PDF text layer")
                heading = (
                    "h4"
                    if _ARTICLE.fullmatch(plain)
                    else "h2"
                    if re.fullmatch(r"ANNEX(?:\s+[IVX\d]+)?", plain)
                    else "h3"
                    if re.fullmatch(r"(?:CHAPTER|TITLE|SECTION)\s+[IVX\d]+", plain)
                    else ""
                )
                text = plain if heading else _inline(item)
                if heading:
                    flush()
                    paragraphs.append(Paragraph(heading, text))
                else:
                    new_paragraph = (
                        previous is None
                        or _LIST.match(plain)
                        or item["top"] - previous["bottom"] > 5
                        or abs(item["x0"] - previous["x0"]) > 20
                    )
                    if new_paragraph:
                        flush()
                    if pending.endswith("-") and text[:1].islower():
                        pending = pending[:-1] + text
                    else:
                        pending += (" " if pending else "") + text
                    pending = re.sub(r"[ \t]{2,}", " ", pending)
                previous = item
            # A page break can fall inside a paragraph; carry pending text on.
            page.close()
        flush()
    if not started or not paragraphs:
        raise UnsupportedPDF("CELLAR PDF has no readable legal body")
    return paragraphs
