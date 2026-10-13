"""BOE-specific text and metadata parsers.

Wraps the existing xml_parser.py and metadata.py modules
behind the abstract TextParser and MetadataParser interfaces.
"""

from __future__ import annotations

from typing import Any
from dataclasses import replace
from datetime import date
import re

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import Block, NormMetadata, Reform

_MONTHS = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()
_PLANNED = re.compile(r"entra en vigor el (\d{1,2}) de (" + "|".join(_MONTHS) + r") de (\d{4})")


def _mark_superseded_wording(block: Block) -> Block:
    """Require the BOE's later expired quotation to prove which wording stayed operative."""
    versions = list(block.versions)
    for index in range(1, len(versions) - 1):
        previous, projected, successor = versions[index - 1 : index + 2]
        if (
            projected.effective_date is not None
            or not previous.effective_date
            or not successor.effective_date
        ):
            continue
        planned = {
            date(int(year), _MONTHS.index(month) + 1, int(day))
            for paragraph in projected.paragraphs
            if projected.norm_id in paragraph.text
            and "redacción de este artículo" in paragraph.text
            for day, month, year in _PLANNED.findall(paragraph.text)
        }
        if len(planned) != 1 or successor.publication_date >= next(iter(planned)):
            continue
        notes = " ".join(p.text for p in successor.paragraphs)
        if projected.norm_id not in notes or "en la redacción dada" not in notes:
            continue
        quoted = []
        copying = False
        for paragraph in successor.paragraphs:
            if paragraph.expiry_date != successor.effective_date:
                continue
            if paragraph.text.strip() == "Redacción anterior:":
                copying = True
            elif copying:
                quoted.append(paragraph.text)
        old = " ".join(p.text for p in previous.paragraphs if p.css_class.startswith("parrafo"))
        quoted_text = " ".join(" ".join(quoted).split()).strip(' "“”«»')
        if old and quoted_text == " ".join(old.split()):
            versions[index] = replace(projected, superseded_before_commencement=True)
    return replace(block, versions=tuple(versions))


def extract_reforms(blocks: list[Block] | tuple[Block, ...]) -> list[Reform]:
    """Keep each commencement stage without changing the official publication date."""
    stages = {}
    superseded = set()
    for block in blocks:
        for version in block.versions:
            key = (version.publication_date, version.norm_id, version.effective_date)
            stages.setdefault(key, set()).add(block.id)
            if version.superseded_before_commencement:
                superseded.add(key)
    return [
        Reform(
            published,
            source,
            tuple(sorted(ids)),
            effective_date=effective,
            change_note=(
                "The BOE's later version confirms that projected wording was superseded before commencement; the preceding operative wording is retained."
                if (published, source, effective) in superseded
                else ""
            ),
        )
        for (published, source, effective), ids in sorted(
            stages.items(),
            key=lambda item: (
                max(item[0][0], item[0][2] or item[0][0]),
                item[0][0],
                item[0][1],
                item[0][2] or item[0][0],
            ),
        )
    ]


class BOETextParser(TextParser):
    """Parse BOE consolidated text XML into Block objects."""

    def parse_text(self, data: bytes) -> list[Any]:
        from legalize.transformer.xml_parser import parse_text_xml

        return [_mark_superseded_wording(block) for block in parse_text_xml(data)]

    def extract_reforms(self, data: bytes) -> list[Reform]:
        return extract_reforms(self.parse_text(data))


class BOEMetadataParser(MetadataParser):
    """Parse BOE metadata XML into NormMetadata."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        from legalize.fetcher.es.metadata import parse_metadata

        return parse_metadata(data, norm_id)
