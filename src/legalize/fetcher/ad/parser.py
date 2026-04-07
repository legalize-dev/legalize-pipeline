"""Parser for Andorran legislation JSON files.

The JSON files follow the legalize-pipeline storage.py format exactly,
so parsing is straightforward deserialization.
"""

from __future__ import annotations

import json
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
    Version,
)


class ADTextParser(TextParser):
    """Parses Andorra JSON into Block objects."""

    def parse_text(self, data: bytes) -> list[Any]:
        """Parse JSON into Blocks with versioned content."""
        parsed = json.loads(data)
        blocks: list[Block] = []

        for art in parsed["articles"]:
            versions = []
            for v in art["versions"]:
                paragraphs = []
                css_classes = v.get("css_classes")
                if v["text"].strip():
                    lines = [ln.strip() for ln in v["text"].split("\n\n") if ln.strip()]
                    for i, line in enumerate(lines):
                        css = css_classes[i] if css_classes and i < len(css_classes) else "parrafo"
                        paragraphs.append(Paragraph(css_class=css, text=line))
                versions.append(
                    Version(
                        norm_id=v["source_id"],
                        publication_date=date.fromisoformat(v["date"]),
                        effective_date=date.fromisoformat(v["date"]),
                        paragraphs=tuple(paragraphs),
                    )
                )

            blocks.append(
                Block(
                    id=art["block_id"],
                    block_type=art["block_type"],
                    title=art["title"],
                    versions=tuple(versions),
                )
            )

        return blocks


class ADMetadataParser(MetadataParser):
    """Parses Andorra JSON metadata into NormMetadata."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        """Parse JSON metadata."""
        parsed = json.loads(data)
        meta = parsed["metadata"]

        return NormMetadata(
            title=meta["title"],
            short_title=meta["title"],
            identifier=meta["identifier"],
            country="ad",
            rank=Rank(meta["rank"]),
            publication_date=date.fromisoformat(meta["publication_date"]),
            status=NormStatus(meta["status"]),
            department="Govern del Principat d'Andorra",
            source=meta["source"],
            last_modified=date.fromisoformat(meta["last_updated"]),
        )
