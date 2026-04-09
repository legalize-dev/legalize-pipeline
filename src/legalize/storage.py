"""Local storage for structured data.

Saves intermediate data for the pipeline:
- data/json/{id}.json   — Structured data for downstream consumers

The JSON contains all information needed to generate commits
without re-downloading or re-parsing anything.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    ParsedNorm,
    Rank,
    Reform,
    Version,
)

logger = logging.getLogger(__name__)


def save_structured_json(data_dir: str | Path, norm: ParsedNorm) -> Path:
    """Save structured data as DB-ready JSON.

    JSON structure:
    {
        "metadata": { title, identifier, country, rank, ... },
        "articles": [
            {
                "block_id": "a135",
                "block_type": "precepto",
                "title": "Artículo 135",
                "position": 42,
                "current_text": "...",
                "versions": [
                    {
                        "date": "1978-12-29",
                        "source_id": "BOE-A-1978-31229",
                        "text": "..."
                    },
                    ...
                ]
            }
        ],
        "reforms": [
            {
                "date": "1992-08-28",
                "source_id": "BOE-A-1992-20403",
                "articles_affected": ["Artículo 13"]
            },
            ...
        ]
    }
    """
    data = _norm_to_dict(norm)
    path = Path(data_dir) / "json" / f"{norm.metadata.identifier}.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.debug("JSON saved: %s", path)
    return path


def _norm_to_dict(norm: ParsedNorm) -> dict:
    """Convert a ParsedNorm to a serializable dict."""
    meta = norm.metadata

    # Core fields (same for all countries, match frontmatter)
    metadata_dict: dict = {
        "title": meta.title.rstrip(". "),
        "short_title": meta.short_title,
        "identifier": meta.identifier,
        "country": meta.country,
        "rank": str(meta.rank),
        "publication_date": meta.publication_date.isoformat(),
        "last_updated": (
            meta.last_modified.isoformat()
            if meta.last_modified
            else meta.publication_date.isoformat()
        ),
        "status": meta.status.value,
        "source": meta.source,
    }

    if meta.jurisdiction:
        metadata_dict["jurisdiction"] = meta.jurisdiction

    # Extra: country-specific fields (department, summary, pdf_url, etc.)
    # These go into a single dict for the extra JSONB column downstream.
    extra_dict: dict[str, str] = {}
    if meta.department:
        extra_dict["department"] = meta.department
    if meta.summary:
        extra_dict["summary"] = meta.summary
    if meta.pdf_url:
        extra_dict["pdf_url"] = meta.pdf_url
    if meta.subjects:
        extra_dict["subjects"] = ", ".join(meta.subjects)
    for key, value in meta.extra:
        if value and key not in extra_dict:
            extra_dict[key] = value
    if extra_dict:
        metadata_dict["extra"] = extra_dict

    # Articles with all their versions
    articles = []
    for i, block in enumerate(norm.blocks):
        article = {
            "block_id": block.id,
            "block_type": block.block_type,
            "title": block.title,
            "position": i,
            "versions": [],
        }

        for version in block.versions:
            text = "\n\n".join(p.text for p in version.paragraphs)
            version_dict: dict = {
                "date": version.publication_date.isoformat(),
                "source_id": version.norm_id,
                "text": text,
            }
            # Preserve CSS classes for lossless round-trip
            css_classes = [p.css_class for p in version.paragraphs]
            if css_classes and any(c != "parrafo" for c in css_classes):
                version_dict["css_classes"] = css_classes
            article["versions"].append(version_dict)

        # current_text = latest version
        if block.versions:
            last = max(block.versions, key=lambda v: v.publication_date)
            article["current_text"] = "\n\n".join(p.text for p in last.paragraphs)
        else:
            article["current_text"] = ""

        articles.append(article)

    # Reforms
    block_map = {b.id: b for b in norm.blocks}
    reforms = []
    for reform in norm.reforms:
        affected = []
        for bid in reform.affected_blocks:
            b = block_map.get(bid)
            if b and b.title:
                affected.append(b.title)

        reforms.append(
            {
                "date": reform.date.isoformat(),
                "source_id": reform.norm_id,
                "articles_affected": affected,
                "affected_block_ids": list(reform.affected_blocks),
            }
        )

    return {
        "metadata": metadata_dict,
        "articles": articles,
        "reforms": reforms,
    }


def load_norma_from_json(json_path: Path) -> ParsedNorm:
    """Load a ParsedNorm from a structured JSON file.

    Inverse of save_structured_json(). Falls back to "parrafo" css_class
    when not present in JSON (most norms use only parrafo).
    """
    logger.info("Loading norm from %s", json_path)
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    meta = data["metadata"]

    # Reconstruct from extra dict (department, summary, pdf_url, etc.)
    extra_dict = dict(meta.get("extra", {}))
    department = extra_dict.pop("department", meta.get("department", ""))
    summary = extra_dict.pop("summary", "")
    pdf_url = extra_dict.pop("pdf_url", None)
    subjects_str = extra_dict.pop("subjects", "")
    subjects = (
        tuple(s.strip() for s in subjects_str.split(",") if s.strip()) if subjects_str else ()
    )
    extra = tuple(extra_dict.items())

    metadata = NormMetadata(
        title=meta["title"],
        short_title=meta["short_title"],
        identifier=meta["identifier"],
        country=meta["country"],
        rank=Rank(meta["rank"]),
        publication_date=date.fromisoformat(meta["publication_date"]),
        status=NormStatus(meta["status"]),
        department=department,
        source=meta["source"],
        jurisdiction=meta.get("jurisdiction"),
        last_modified=date.fromisoformat(meta["last_updated"]),
        summary=summary,
        pdf_url=pdf_url,
        subjects=subjects,
        extra=extra,
    )

    blocks = []
    for art in data["articles"]:
        versions = []
        for v in art["versions"]:
            paragraphs = []
            css_classes = v.get("css_classes")
            if v["text"].strip():
                lines = [line.strip() for line in v["text"].split("\n\n") if line.strip()]
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

    reforms = []
    for r in data["reforms"]:
        # Prefer explicit block IDs (Suvestine-aware) over source_id matching
        if "affected_block_ids" in r:
            affected = tuple(r["affected_block_ids"])
        else:
            # Legacy: reconstruct from version source_id matching
            affected = tuple(
                art["block_id"]
                for art in data["articles"]
                for v in art["versions"]
                if v["source_id"] == r["source_id"] and v["date"] == r["date"]
            )
        reforms.append(
            Reform(
                date=date.fromisoformat(r["date"]),
                norm_id=r["source_id"],
                affected_blocks=affected,
            )
        )

    result = ParsedNorm(
        metadata=metadata,
        blocks=tuple(blocks),
        reforms=tuple(reforms),
    )
    logger.debug(
        "Loaded %s: %d blocks, %d reforms",
        metadata.identifier,
        len(blocks),
        len(reforms),
    )
    return result
