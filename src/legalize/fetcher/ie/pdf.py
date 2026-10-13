"""Recover selectable, unannotated LRC Revised Act PDF snapshots.

The archive contains two XEP layouts: older marginal section titles and newer
headings above the text. Geometry is necessary because these PDFs are untagged.
Unsupported/scanned documents fail rather than yielding an apparently valid
partial statute. Snapshot dates come from the cover, never PDF creation metadata.
"""

from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from hashlib import sha256
from itertools import groupby
from threading import Lock
from urllib.parse import urlsplit

import pdfplumber
from lxml import etree
from pdfplumber.utils import extract_text

from legalize.fetcher._tables import render_table
from legalize.fetcher._text import strip_control
from legalize.fetcher.ie.parser import _legal_format
from legalize.models import Paragraph

_SECTION = re.compile(r"^(?:(?:F\d+)?\[\s*)?(\d+[A-Z]*)\s*\.")
_DIVISION = re.compile(
    r"^(?:(?:F\d+)?\[)?(?:(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH) )?"
    r"(PART|CHAPTER|SCHEDULE)\s*(?:[\dIVXLCDM]+[A-Z]*)?$",
    re.I,
)
_DATE = re.compile(r"Updated to\s+(\d{1,2})\s+(\w+)\s+(\d{4})", re.I)
_MONTHS = (
    "january february march april may june july august september october november december"
).split()


_PDF_PARSE_LOCK = Lock()

# These exact official files omit an in-force provision from their bodies while
# retaining its contents entry. Preserve the source, with an explicit warning;
# never extend this exception to other bytes or other missing provisions.
# Evidence: tests/fixtures/ie/archive-companies-2020-source-gaps.json.
_KNOWN_SOURCE_OMISSIONS = {
    digest: frozenset({"1384A"})
    for digest in (
        "d487045605971cca95feddf6dbd824188edd95e9f1e0f1d62c191cdd083e777d",
        "c056a097cf75e05af4f180de51d3be8623292dc0e9deff789430116d8c5a21bd",
        "1e6a866df584baa5f2048e81344e8944d01d4f4aed47ea6430403b9309d2bcdc",
        "a02cbaf5440607a30604171a50a483e4b8a8db5a7f742ad7e10fdde34e937947",
    )
}


def source_warning(data: bytes) -> str | None:
    """Return the verified limitation for an exact incomplete official PDF."""
    if sha256(data).hexdigest() in _KNOWN_SOURCE_OMISSIONS:
        return (
            "This official Companies Act 2014 consolidated PDF is incomplete: section 1384A "
            "is listed in its contents but absent from the body. Its text has not been "
            "reconstructed. Check the original amending legislation before relying on this snapshot."
        )
    return None


class UnsupportedPDF(ValueError):
    """The PDF cannot be converted without risking lost or misassigned text."""


@dataclass
class _Line:
    chars: list[dict]
    page: int
    links: list[dict]

    @cached_property
    def text(self) -> str:
        return extract_text(self.chars, x_tolerance=0.75, y_tolerance=3).strip()

    @cached_property
    def top(self) -> float:
        return min(c["top"] for c in self.chars)

    @cached_property
    def bottom(self) -> float:
        return max(c["bottom"] for c in self.chars)

    @cached_property
    def x0(self) -> float:
        return min(c["x0"] for c in self.chars)

    @cached_property
    def x1(self) -> float:
        return max(c["x1"] for c in self.chars)


def _inline(line: _Line, *, emphasis: bool = True) -> str:
    """Keep font emphasis, superscripts, small caps and explicit URI links."""
    chars = sorted(line.chars, key=lambda c: c["x0"])
    size = Counter(round(c["size"], 1) for c in chars).most_common(1)[0][0]
    baseline = max(c["bottom"] for c in chars)
    largest = max(c["size"] for c in chars)

    def style(char):
        font = char["fontname"]
        sup = char["size"] < size * 0.8 and char["bottom"] < baseline - 2
        href = next(
            (
                link["uri"]
                for link in line.links
                if link["x0"] - 0.5 <= (char["x0"] + char["x1"]) / 2 <= link["x1"] + 0.5
                and link["top"] - 1 <= (char["top"] + char["bottom"]) / 2 <= link["bottom"] + 1
                and urlsplit(link.get("uri") or "").scheme in ("http", "https")
            ),
            "",
        )
        return "Bold" in font, "Italic" in font, sup, href

    result = []
    previous = None
    for (bold, italic, sup, href), run in groupby(chars, key=style):
        text = ""
        for char in run:
            if (
                previous
                and char["x0"] - previous["x1"] > 0.75
                and char["text"] not in ",;:.!?)]}’”"
            ):
                text += " "
            value = char["text"]
            # XEP renders small caps as smaller upper-case glyphs on the baseline.
            if not sup and char["size"] < largest * 0.8 and value.isalpha():
                value = value.lower()
            text += value
            previous = char
        text = strip_control(text)
        body = text.strip()
        if not body:
            result.append(text)
            continue
        if emphasis:
            if bold and body not in ("[", "]"):
                body = f"**{body}**"
            if italic:
                body = f"*{body}*"
            if sup:
                body = f"^{body}"
            if href:
                body = f"[{body}]({href})"
        result.append(
            (" " if text[:1].isspace() else "") + body + (" " if text[-1:].isspace() else "")
        )
    return "".join(result).strip()


def _section_match(line: _Line, *, allow_plain: bool = False):
    """Captioned labels can be plain; an italic citation can also wrap as ``366.``."""
    match = _SECTION.match(line.text)
    if match is None:
        return None
    chars = sorted(line.chars, key=lambda char: char["x0"])
    prefix = "".join(char["text"] for char in chars).split(".", 1)[0]
    number = re.search(r"(\d+[A-Z]*)$", prefix)
    if number is None:
        return None
    offset = 0
    for char in chars:
        if number.start() <= offset < number.end() and (
            "Italic" in char["fontname"] or (not allow_plain and "Bold" not in char["fontname"])
        ):
            return None
        offset += len(char["text"])
        if offset >= number.end():
            break
    return match


def _join(left: str, right: str) -> str:
    # Only an explicit discretionary hyphen can be removed without guessing
    # whether the source word was a hyphenated compound.
    if left.endswith("\u00ad"):
        return left[:-1] + right
    if left.endswith("-") and right[:1].islower():
        return left + right
    text = left + (" " if left else "") + right
    # A URI or emphasis run can span physical lines. Rejoin only adjacent
    # identical markup, preserving all of the underlying source characters.
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\) \[([^\]]+)\]\(\2\)", r"[\1 \3](\2)", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\* \*([^*]+)\*(?!\*)", r"*\1 \2*", text)
    text = re.sub(r"\*\*([^*]+)\*\* \*\*([^*]+)\*\*", r"**\1 \2**", text)
    return text


def _inside(char: dict, box: tuple) -> bool:
    return (
        box[0] - 0.1 <= (char["x0"] + char["x1"]) / 2 <= box[2] + 0.1
        and box[1] - 0.1 <= (char["top"] + char["bottom"]) / 2 <= box[3] + 0.1
    )


def _table(page, table, number: int) -> str:
    """Recover ruled cells and paragraph-separated rows within open columns."""
    element = etree.Element("table")
    for row in table.rows:
        cells = row.cells
        boxes = [box for box in cells if box is not None]
        if not boxes:
            continue
        top, bottom = min(b[1] for b in boxes), max(b[3] for b in boxes)
        first = next(box for box in cells if box is not None)
        first_lines = page.crop(first).extract_text_lines(x_tolerance=0.75)
        # Many statutory tables rule columns, but omit horizontal row borders.
        # A paragraph break in the first column then identifies each source row.
        cuts = [top]
        previous = None
        for line in first_lines:
            if previous and line["top"] - previous["bottom"] > 4:
                cuts.append(line["top"] - 0.5)
            previous = line
        cuts.append(bottom)
        for cut in cuts[1:-1]:
            if any(
                _inside(c, table.bbox) and c["top"] + 0.1 < cut < c["bottom"] - 0.1
                for c in page.chars
            ):
                raise UnsupportedPDF("Ambiguous row boundaries in Revised Act PDF table")
        for start, end in zip(cuts, cuts[1:], strict=False):
            tr = etree.SubElement(element, "tr")
            for box in cells:
                td = etree.SubElement(tr, "td")
                if box is None:
                    continue
                cropped = page.crop((box[0], start, box[2], end))
                lines = [
                    _Line(line["chars"], number, page.hyperlinks)
                    for line in cropped.extract_text_lines(x_tolerance=0.75)
                ]
                td.text = " ".join(_inline(line).replace("|", "\\|") for line in lines)
    return render_table(element, lambda cell: cell.text or "")


def _read(data: bytes) -> tuple[list[_Line | Paragraph], date | None, set[str]]:
    events: list[_Line | Paragraph] = []
    updated = None
    started = False
    contents = False
    expected: set[str] = set()
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for number, page in enumerate(pdf.pages):
            lines = page.extract_text_lines(x_tolerance=0.75)
            plain = [line["text"] for line in lines]
            if (
                started
                and any(text == "About this Revised Act" for text in plain)
                and plain
                and re.match(r"Number \d+ of \d{4}", plain[0])
            ):
                break
            start = 0
            if not started:
                for i, text in enumerate(plain):
                    match = _DATE.search(text)
                    if match:
                        try:
                            found = date(
                                int(match[3]), _MONTHS.index(match[2].lower()) + 1, int(match[1])
                            )
                        except ValueError as exc:
                            raise UnsupportedPDF("Invalid Revised Act PDF cover date") from exc
                        if updated and found != updated:
                            raise UnsupportedPDF("Conflicting Revised Act PDF cover dates")
                        updated = found
                    if re.match(r"^(?:F\d+\[)?AN ACT\b", text, re.I):
                        start = i
                        started = True
                        break
                    if text in ("ARRANGEMENT OF SECTIONS", "CONTENTS"):
                        contents = True
                    if text == "ACTS REFERRED TO":
                        contents = False
                    if contents and (match := re.match(r"^(\d+[A-Z]*)\.\s+", text)):
                        next_number = (
                            max((int(re.match(r"\d+", n)[0]) for n in expected), default=0) + 1
                        )
                        if int(re.match(r"\d+", match[1])[0]) <= next_number:
                            expected.add(match[1])
                if not started:
                    page.close()
                    continue
            body_top = lines[start]["top"] if start else 78
            active = [
                c for c in page.chars if c["top"] >= body_top - 0.1 and c["top"] < page.height - 36
            ]
            if any(
                "(cid:" in c["text"] or "\ufffd" in c["text"] or not c["upright"] for c in active
            ):
                raise UnsupportedPDF(
                    f"Unreadable or rotated Revised Act PDF text on page {number + 1}"
                )
            body_images = [
                image
                for image in page.images
                if image["bottom"] > body_top and image["top"] < page.height - 36
            ]
            if body_images and not active:
                raise UnsupportedPDF(f"Image-only Revised Act PDF body page: {number + 1}")
            if not active and number != len(pdf.pages) - 1:
                raise UnsupportedPDF(f"Empty page inside Revised Act PDF body: {number + 1}")
            if any(
                text in ("Annotations", "Amendments:", "Modifications (not altering text):")
                for text in plain
            ):
                raise UnsupportedPDF(
                    "Annotated Revised Act PDF supplied; an unannotated snapshot is required"
                )
            # White background rectangles describe XEP's page region, not cells.
            table_page = page.filter(lambda o: o["object_type"] != "rect" or o.get("stroke"))
            tables = [table for table in table_page.find_tables() if table.bbox[1] >= body_top]
            # A raster figure is omitted in source position under the country
            # playbook; readable text on the same page must still be retained.
            # A paragraph marker also remains inside any enclosing legal quote.
            page_events = [
                (image["top"], Paragraph("parrafo", "[image omitted]")) for image in body_images
            ]
            for table in tables:
                text = _table(page, table, number)
                if not text:
                    raise UnsupportedPDF("Empty Revised Act PDF table")
                page_events.append((table.bbox[1], Paragraph("table", text)))
            active_ids = {id(c) for c in active}
            for item in lines[start:]:
                chars = [
                    c
                    for c in item["chars"]
                    if id(c) in active_ids and not any(_inside(c, t.bbox) for t in tables)
                ]
                if chars:
                    line = _Line(chars, number, page.hyperlinks)
                    if line.text in ("ACTS REFERRED TO", "About this Revised Act"):
                        events.extend(
                            event
                            for top, event in sorted(page_events, key=lambda event: event[0])
                            if top < line.top
                        )
                        page.close()
                        return events, updated, expected
                    page_events.append((line.top, line))
            events.extend(event for _, event in sorted(page_events, key=lambda event: event[0]))
            page.close()
    if not started or not events:
        raise UnsupportedPDF("Revised Act PDF has no readable legislative body")
    return events, updated, expected


def parse_revised_pdf(data: bytes) -> tuple[list[Paragraph], date | None]:
    """Serialize glyph-heavy extraction while fetch workers can continue their I/O.

    This bounds concurrent PDF glyph collections, not the surrounding envelopes.
    """
    with _PDF_PARSE_LOCK:
        return _parse_revised_pdf(data)


def _parse_revised_pdf(data: bytes) -> tuple[list[Paragraph], date | None]:
    """Extract the actual dated legal text, preserving marginal section titles."""
    events, updated, expected = _read(data)
    footnotes = []
    body_events = []
    previous_note = None
    for event in events:
        if isinstance(event, _Line) and event.top > 700 and max(c["size"] for c in event.chars) < 9:
            match = re.match(r"^(\d+)\s+(.+)", event.text)
            if (
                match
                and min(c["size"] for c in event.chars) < max(c["size"] for c in event.chars) * 0.8
            ):
                rendered = re.sub(r"^\^?\d+\s*", "", _inline(event))
                footnotes.append(Paragraph("parrafo", f"[^{match[1]}]: {rendered}"))
                previous_note = event
                continue
            if (
                previous_note
                and previous_note.page == event.page
                and event.top - previous_note.bottom < 5
            ):
                footnotes[-1] = Paragraph("parrafo", _join(footnotes[-1].text, _inline(event)))
                previous_note = event
                continue
        previous_note = None
        body_events.append(event)
    events = body_events
    first = next(
        (
            event
            for event in events
            if isinstance(event, _Line) and re.search(r"\b1\.(?=[—\s(\[]|F\d+\[)", event.text)
        ),
        None,
    )
    if first is None:
        raise UnsupportedPDF("Revised Act PDF has no first section")
    first_label = None
    for char in first.chars:
        if char["text"] != "1" or "Italic" in char["fontname"]:
            continue
        candidate = _Line(
            [c for c in first.chars if c["x0"] >= char["x0"]], first.page, first.links
        )
        if (match := _section_match(candidate, allow_plain=True)) and match[1] == "1":
            first_label = candidate
            break
    if first_label is None:
        raise UnsupportedPDF("Revised Act PDF has no first section label")
    marginal = first.x0 < first_label.x0 - 30
    margin_edge = first_label.x0 - 8.74
    first_index = events.index(first)
    first_title = events[first_index - 1] if first_index else None
    title_x = (
        first_title.x0
        if isinstance(first_title, _Line)
        and first_title.page == first.page
        and first.top - first_title.bottom < 25
        and sum("Bold" in c["fontname"] for c in first_title.chars) / len(first_title.chars) > 0.8
        else first_label.x0
    )
    lines: list[_Line | Paragraph] = []
    margins: list[_Line] = []
    captions: list[list[_Line]] = []
    for event in events:
        if not isinstance(event, _Line) or not marginal or event.x0 >= first_label.x0 - 52.64:
            lines.append(event)
            continue
        # XEP's caption column moves with the body margin; smaller glyphs can hang into the gutter.
        caption_fonts = {
            (round(c["top"], 2), round(c["bottom"], 2), c["fontname"])
            for c in event.chars
            if c["x0"] < first_label.x0 - 52.64
        }
        side = [
            c
            for c in event.chars
            if (c["x0"] < margin_edge or (c["x0"] < margin_edge + 4 and c["size"] < 9.5))
            and (
                not all("Bold" in font for _, _, font in caption_fonts)
                or (round(c["top"], 2), round(c["bottom"], 2), c["fontname"]) in caption_fonts
            )
        ]
        body = [c for c in event.chars if c not in side]
        caption_rows = {
            (round(c["top"], 2), round(c["bottom"], 2))
            for c in event.chars
            if c["x0"] < first_label.x0 - 52.64
        }
        recovered_body = [
            c
            for c in event.chars
            if (round(c["top"], 2), round(c["bottom"], 2)) not in caption_rows
        ]
        if recovered_body:
            recovered = _Line(recovered_body, event.page, event.links)
            if abs(recovered.x0 - first_label.x0) < 27 and _section_match(recovered):
                body = recovered_body
                side = [c for c in event.chars if c not in body]
        if side and body and _section_match(_Line(body, event.page, event.links)) is None:
            # Some XEP captions overlap the opening number horizontally. Their
            # glyph baselines remain distinct (even when the font sizes match).
            # Extend a caption only when this recovers a bold primary label at
            # the body column; all recovered glyphs remain in the source title.
            caption_rows = {
                (round(c["top"], 2), round(c["bottom"], 2), c["fontname"]) for c in side
            }
            overflow = [
                c
                for c in body
                if (round(c["top"], 2), round(c["bottom"], 2), c["fontname"]) in caption_rows
            ]
            candidate = [c for c in body if c not in overflow]
            if (
                overflow
                and all(c["x0"] < first_label.x0 + 10 for c in overflow)
                and (not candidate or min(c["x0"] for c in candidate) >= first_label.x0 - 10)
            ):
                side.extend(overflow)
                body = candidate
            elif candidate:
                recovered = _Line(candidate, event.page, event.links)
                if abs(recovered.x0 - first_label.x0) < 10 and _section_match(recovered):
                    side.extend(overflow)
                    body = candidate
        if side:
            side_line = _Line(side, event.page, event.links)
            # Classify complete captions below: a wrapped title can itself
            # contain a line such as "section 1517", not a schedule locator.
            margins.append(side_line)
        if body:
            lines.append(_Line(body, event.page, event.links))
    if marginal:
        margin_x = first.x0
        preserved = []
        i = 0
        while i < len(margins):
            start = margins[i]
            group = [start]
            i += 1
            while (
                i < len(margins)
                and margins[i].page == start.page
                and -2 < margins[i].top - group[-1].bottom < 4
            ):
                group.append(margins[i])
                i += 1
            # A schedule locator can wrap through a definition or subsection.
            # Inserted legislation can also have its own indented marginal
            # captions; they are quoted content, never primary section titles.
            locator = re.match(r"^Sections?\s+\d", start.text, re.I) and not any(
                isinstance(line, _Line)
                and line.page == start.page
                and abs(line.top - start.top) < 6
                and _section_match(line)
                for line in lines
            )
            # Companies captions indent their first line by 8.64pt. A quoted
            # marginal column is displaced by 25.92pt (Credit Union Act 2012).
            aligned_label = any(
                isinstance(line, _Line)
                and line.page == start.page
                and abs(line.top - start.top) < 6
                and abs(line.x0 - first_label.x0) < 2
                and _section_match(line)
                for line in lines
            )
            if (
                locator
                or re.match(r"^\[(?:New\b|Cf\. \d{4}\b|\d{4}\b|R\.S\.C\.)", start.text)
                or re.match(r"^S\.R\. & O\. No\. \d+", start.text)
                or (min(line.x0 for line in group) > margin_x + 12 and not aligned_label)
            ):
                text = ""
                for line in group:
                    text = _join(text, _inline(line))
                position = next(
                    (
                        n
                        for n, line in enumerate(lines)
                        if isinstance(line, _Line)
                        and (line.page, line.top) >= (start.page, start.top)
                    ),
                    len(lines),
                )
                lines.insert(position, Paragraph("parrafo", text))
            else:
                preserved.extend(group)
                captions.append(group)
        margins = preserved

    paragraphs: list[Paragraph] = []
    pending = ""
    pending_title = False
    pending_x = None
    previous: _Line | None = None
    seen: set[str] = set()
    schedule = False
    schedule_start = None
    primary_x = first_label.x0
    division_center = None
    quote_depth = 0

    def flush():
        nonlocal pending, pending_title
        if pending:
            paragraphs.append(Paragraph("parrafo", pending))
            pending = ""
        pending_title = False

    i = 0
    while i < len(lines):
        item = lines[i]
        i += 1
        quoted = quote_depth > 0
        if quote_depth or re.match(r"^(?:F\d+\[)?“", item.text):
            quote_depth = max(
                0, quote_depth + item.text.count("“") - len(re.findall(r"”|’’(?=\W|$)", item.text))
            )
        if isinstance(item, Paragraph):
            flush()
            paragraphs.append(item)
            previous = None
            continue
        if schedule:
            # Schedule captions describe their own clauses, never primary Act sections.
            remaining = [m for m in margins if (m.page, m.top) >= schedule_start]
            while remaining and (remaining[0].page, remaining[0].top) <= (item.page, item.top + 6):
                group = [remaining.pop(0)]
                while (
                    remaining
                    and remaining[0].page == group[-1].page
                    and -2 < remaining[0].top - group[-1].bottom < 4
                ):
                    group.append(remaining.pop(0))
                margins = [m for m in margins if m not in group]
                flush()
                paragraphs.append(Paragraph("parrafo", " ".join(_inline(m) for m in group)))
        text = item.text
        division = _DIVISION.fullmatch(text) if not quoted else None
        if division and division[1].upper() == "CHAPTER" and division_center is not None:
            if item.text.isupper() and abs((item.x0 + item.x1) / 2 - division_center) > 15:
                division = None
        if division:
            flush()
            kind = division[1].upper()
            division_center = (item.x0 + item.x1) / 2
            if kind == "SCHEDULE" and not schedule:
                schedule = True
                schedule_start = (item.page, item.top)
            heading = _inline(item, emphasis=False)
            # A division title is centered and may wrap, or begin on the next
            # page. A later centered paragraph is a subheading, not its title.
            last_title = None
            while i < len(lines) and isinstance(lines[i], _Line):
                following = lines[i]
                if (
                    abs((following.x0 + following.x1) / 2 - division_center) > 35
                    or _SECTION.match(following.text)
                    or _DIVISION.fullmatch(following.text)
                    or sum("Bold" in c["fontname"] for c in following.chars) / len(following.chars)
                    > 0.8
                    or (
                        last_title is not None
                        and (
                            following.page != last_title.page
                            or following.top - last_title.bottom > 5
                        )
                    )
                ):
                    break
                heading = _join(heading, _inline(following, emphasis=False))
                last_title = following
                i += 1
            paragraphs.append(
                Paragraph("capitulo_tit" if kind == "CHAPTER" else "titulo_tit", heading)
            )
            previous = None
            continue
        match = _section_match(item, allow_plain=marginal and abs(item.x0 - primary_x) < 10)
        caption = (
            next(
                (
                    group
                    for group in captions
                    if group[0].page == item.page and abs(group[0].top - item.top) < 6
                ),
                [],
            )
            if match and not schedule
            else []
        )
        marginal_title = bool(caption)
        # A primary marginal caption ends a preceding quote even when the source omits its delimiter.
        if match and marginal_title:
            quote_depth = 0
        primary = match and not schedule and (not quoted or marginal_title)
        if marginal:
            # A compound opening label can hang farther right. Some otherwise
            # marginal PDFs also put individual bold titles above the text.
            title_above = (
                previous is not None
                and previous.page == item.page
                and pending_title
                and pending
                and abs(item.x0 - primary_x) < 10
                and item.top - previous.bottom < 25
            )
            primary = primary and (marginal_title or title_above)
        else:
            # Source labels can shift by two paragraph indents beneath an aligned title.
            indented_label = (
                previous is not None
                and previous.page == item.page
                and pending_title
                and pending
                and pending_x is not None
                and abs(pending_x - title_x) < 2
                and abs(item.x0 - title_x) < 27
                and (not expected or match and match[1] in expected)
                and item.top - previous.bottom < 25
            )
            primary = primary and (abs(item.x0 - primary_x) < 2 or indented_label)
        if primary:
            number = match[1]
            if number in seen:
                raise UnsupportedPDF(f"Duplicate primary section {number} in Revised Act PDF")
            seen.add(number)
            title = ""
            if marginal_title:
                # Wrapped caption lines cannot become headings for quoted or numbered body text.
                title = " ".join(_inline(m, emphasis=False) for m in caption)
                margins = [m for m in margins if m not in caption]
                captions.remove(caption)
            else:
                # The preceding bold title was buffered as a paragraph.
                if previous and previous.page == item.page and pending_title and pending:
                    title, pending = re.sub(r"\*+", "", pending), ""
            flush()
            paragraphs.append(
                Paragraph("articulo", f"{number}. **{title}**" if title else f"{number}.")
            )
            previous = None
        new_paragraph = (
            previous is None
            or (previous.page == item.page and item.top - previous.bottom > 5)
            or (
                previous.page != item.page
                and (
                    re.match(r"^(?:F\d+\[)?[“\"(]", text)
                    or previous.x1 < 515
                    or sum("Bold" in c["fontname"] for c in item.chars) / len(item.chars) > 0.8
                )
            )
        )
        if new_paragraph:
            flush()
        if not pending:
            pending_title = sum("Bold" in c["fontname"] for c in item.chars) / len(item.chars) > 0.8
            pending_x = item.x0
        pending = _join(pending, _inline(item))
        previous = item
    flush()
    missing = expected - seen
    if missing and missing != _KNOWN_SOURCE_OMISSIONS.get(sha256(data).hexdigest()):
        raise UnsupportedPDF(
            f"Revised Act PDF is missing sections listed in its contents: {', '.join(sorted(missing))}"
        )
    if not seen:
        raise UnsupportedPDF("Revised Act PDF has no legal sections")
    if margins:
        # Schedule cross-references are legal text, unlike running headers.
        # An orphan marginal section title indicates a structural extraction error.
        if any(
            not re.fullmatch(r"Sections?\s+\d+[A-Z]*(?:\s*(?:,|and)\s*\d+[A-Z]*)*\.?", m.text, re.I)
            for m in margins
        ):
            raise UnsupportedPDF("Unassigned marginal text in Revised Act PDF")
        paragraphs.extend(Paragraph("parrafo", _inline(m)) for m in margins)
    if footnotes:
        identifiers = {re.match(r"\[\^(\d+)\]", p.text)[1] for p in footnotes}
        paragraphs = [
            Paragraph(
                p.css_class,
                re.sub(
                    r"\^(\d+)\b", lambda m: f"[^{m[1]}]" if m[1] in identifiers else m[0], p.text
                ),
            )
            for p in paragraphs
        ]
        paragraphs.append(Paragraph("h2", "Footnotes"))
        paragraphs.extend(footnotes)
    return _legal_format(paragraphs), updated
