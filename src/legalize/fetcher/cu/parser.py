"""Parsers for Gaceta Oficial de la República de Cuba documents.

The text parser ingests the JSON bundle produced by ``GacetaClient.get_text``
(PDF bytes + manifest slicing knobs + publication date) and emits a single
``Block`` of engine-CSS-tagged paragraphs, mirroring the Greece/Andorra
single-Block "as enacted" pattern:

* The whole law is one ``Block`` with one ``Version``.
* Consolidated *book* editions (e.g. Ley-59, Ley-116, DL-226, DL-252) carry
  their consolidation in ``manifest.json`` ``notes``/``publication_date`` —
  they are not modelled as reform-graph Versions.

The metadata parser ingests the manifest entry produced by
``GacetaClient.get_metadata`` and builds a ``NormMetadata`` whose fields
map 1:1 onto the stable frontmatter schema documented in the country repo's
``AGENTS.md``: the 8 core fields plus ``journal_issue``, ``goc`` and
``notes`` when present in the manifest.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.fetcher.cu.pdf_extractor import convert_text, unwrap_bundle
from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Rank,
    Version,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Cuban normative ranks (Rank is a free-form str subclass)
# ─────────────────────────────────────────────

RANK_CONSTITUCION = Rank("constitucion")
RANK_LEY = Rank("ley")
RANK_CODIGO = Rank("codigo")
RANK_DECRETO_LEY = Rank("decreto_ley")
RANK_DECRETO = Rank("decreto")

_PLACEHOLDER_DATE = date(1900, 1, 1)


def _parse_iso_date(value: str | None) -> date | None:
    """Parse an ISO-8601 date (``YYYY-MM-DD``) from the manifest."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


# ─────────────────────────────────────────────
# Public TextParser
# ─────────────────────────────────────────────


class GacetaTextParser(TextParser):
    """Parses a Gaceta Oficial PDF into a single Block of legal text.

    Input format
    ------------
    ``data`` is the JSON bundle produced by ``GacetaClient.get_text``::

        {
          "pdf": "<base64 pdf bytes>",
          "goc": "GOC-2024-440-O78",
          "start_index": 0,
          "start_regex": "^LEY NÚMERO 109",
          "end_regex": "^CONSEJO DE MINISTROS$",
          "publication_date": "2024-08-19",
          "title": "Decreto-Ley 88/2024, ..."
        }

    For backwards compatibility (and simpler tests) raw PDF bytes are also
    accepted — in that case the ``Version`` uses a 1900-01-01 placeholder
    date which the engine corrects via metadata downstream.
    """

    def parse_text(self, data: bytes) -> list[Any]:
        if not data:
            logger.warning("GacetaTextParser.parse_text called with empty data")
            return []

        bundle = unwrap_bundle(data)
        if bundle.get("pdf_bytes"):
            pdf_bytes = bundle["pdf_bytes"]
            pub_date = _parse_iso_date(bundle.get("publication_date")) or _PLACEHOLDER_DATE
        else:
            pdf_bytes = data
            pub_date = _PLACEHOLDER_DATE

        paragraphs = convert_text(
            pdf_bytes,
            goc=bundle.get("goc") or None,
            start_index=int(bundle.get("start_index") or 0),
            start_regex=bundle.get("start_regex") or None,
            end_regex=bundle.get("end_regex") or None,
        )
        if not paragraphs:
            # Documented genuine gap: the PDF is scanned with no usable text
            # layer (e.g. Constitucion-2019). Emit a single empty Block so the
            # norm still commits (commit_all_fast requires non-empty blocks)
            # and renders as clean frontmatter + an empty body, matching the
            # ground-truth file in the country repo.
            logger.warning(
                "PDF extraction produced no paragraphs — likely a scanned "
                "PDF without a text layer. Emitting an empty Block; consider "
                "Phase 3 OCR for a future text version."
            )
            version = Version(
                norm_id="",
                publication_date=pub_date,
                effective_date=pub_date,
                paragraphs=(),
            )
            return [
                Block(
                    id="body",
                    block_type="article",
                    title="",
                    versions=(version,),
                )
            ]

        version = Version(
            norm_id="",
            publication_date=pub_date,
            effective_date=pub_date,
            paragraphs=tuple(paragraphs),
        )
        block = Block(
            id="body",
            block_type="article",
            title="",
            versions=(version,),
        )
        return [block]


# ─────────────────────────────────────────────
# MetadataParser
# ─────────────────────────────────────────────


class GacetaMetadataParser(MetadataParser):
    """Builds ``NormMetadata`` from the manifest entry for a law.

    Input is the JSON bytes produced by ``GacetaClient.get_metadata`` (the
    entry from ``manifest.json``)::

        {
          "url": "https://www.gacetaoficial.gob.cu/sites/default/files/goc-2021-o140_0.pdf",
          "title": "Ley No. 143 de 2021, Del Proceso Penal",
          "rank": "ley",
          "publication_date": "2021-12-07",
          "journal_issue": "No. 140 Ordinaria de 2021",
          "source": "https://www.gacetaoficial.gob.cu/es/algunas-legislaciones-cubanas",
          "goc": "GOC-2021-....-O140",     # optional
          "notes": "...",                   # optional
          "start_regex": "...",             # optional (book editions)
          "end_regex": "..."                # optional (book editions)
        }

    ``department`` is left empty so the rendered frontmatter matches the
    country repo's documented schema exactly (no extra fields beyond the
    core eight + ``journal_issue``/``goc``/``notes``).
    """

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        if not data:
            raise ValueError("GacetaMetadataParser.parse called with empty data")

        try:
            entry = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid manifest entry for {norm_id!r}") from exc

        title = entry.get("title") or norm_id
        rank = Rank(entry.get("rank") or "ley")

        pub_date = _parse_iso_date(entry.get("publication_date"))
        if pub_date is None:
            raise ValueError(f"No valid publication_date in manifest entry for {norm_id!r}")

        extra: list[tuple[str, str]] = []
        if entry.get("journal_issue"):
            extra.append(("journal_issue", str(entry["journal_issue"])))
        if entry.get("goc"):
            extra.append(("goc", str(entry["goc"])))
        if entry.get("notes"):
            extra.append(("notes", str(entry["notes"])))

        return NormMetadata(
            title=title,
            short_title=title,
            identifier=norm_id,
            country="cu",
            rank=rank,
            publication_date=pub_date,
            status=NormStatus.IN_FORCE,
            department="",
            source=entry.get("source") or "",
            jurisdiction=None,
            extra=tuple(extra),
        )
