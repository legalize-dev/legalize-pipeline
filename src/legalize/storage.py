"""Local storage for structured data.

Saves intermediate data for the pipeline:
- data/json/{id}.json   — Structured data for downstream consumers

The JSON contains all information needed to generate commits
without re-downloading or re-parsing anything.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
from collections import Counter
from dataclasses import replace
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
    TextState,
    Version,
)

logger = logging.getLogger(__name__)

# Which identifiers this process has written and which norm owns each one. Two
# norms resolving to one identifier is a real thing — a diploma reachable from both
# DRE surfaces, two acts sharing a number — and a file can only hold one of them.
# The owner is the norm's official URL, so re-saving the same norm (a retry, a
# duplicate discovery entry) is not mistaken for a second law.
_written_identifiers: dict[str, str] = {}
_overwrites: Counter[str] = Counter()
_write_lock = threading.Lock()


def _claim(identifier: str, owner: str = "") -> bool:
    """Register a write. True if a *different* norm already wrote this identifier."""
    with _write_lock:
        current = _written_identifiers.get(identifier)
        if current is None:
            _written_identifiers[identifier] = owner
            return False
        if current == owner:
            return False
        _overwrites[identifier] += 1
        return True


def overwritten_identifiers() -> dict[str, int]:
    """Identifiers more than one norm of this phase claimed, and how many times.

    Nothing is lost any more — the second norm is written beside the first (see
    ``_disambiguated``) — but every entry here is a law whose file name is not the
    one its country's rule promised, so it is a number to explain rather than
    silence. A consolidated diploma landing on its as-published twin does not
    appear: the pipeline resets the tracking between phases.
    """
    with _write_lock:
        return dict(_overwrites)


def reset_write_tracking() -> None:
    """Forget what has been written. For tests and for per-phase snapshots."""
    with _write_lock:
        _written_identifiers.clear()
        _overwrites.clear()


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
    directory = Path(data_dir) / "json"
    directory.mkdir(parents=True, exist_ok=True)
    norm = _disambiguated(norm)
    data = _norm_to_dict(norm)
    path = directory / f"{norm.metadata.identifier}.json"

    # Write somewhere private and rename into place. Where two norms share an
    # identifier — and Portugal has 128 such pairs — eight workers otherwise open
    # the same file at once, both truncate it, both write from their own offset, and
    # what lands is neither of them: a JSON document with another one's tail stuck to
    # it, which every later reader skips. The rename is atomic, so the loser is
    # replaced whole instead of interleaved.
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise

    logger.debug("JSON saved: %s", path)
    return path


def _disambiguated(norm: ParsedNorm) -> ParsedNorm:
    """Give the norm a free identifier when another one already took its own.

    Two norms of the same phase resolving to one identifier is one law shadowing
    another — Portugal lost 6,862 of them without a word, because the second write
    simply replaced the first and the file name is also the Markdown name, so both
    the data and the published law went. A norm that arrives second is written
    beside the first instead: an ugly file name is visible and fixable, a missing
    law is neither. The country's own identifier rule is still the real fix (pt
    tells the two apart by the série of the Diário da República).

    The suffix is the publication date, which is a property of the act and does not
    change between runs. A consolidated norm landing on its as-published twin is
    not this: it is the same law from a richer surface, and the pipeline keeps the
    two apart by resetting the tracking between phases.

    Only what this process wrote is known here, so it does not catch a daily run
    where a new act lands on a law written months ago; GitRepo.write_and_add
    refuses that one.
    """
    identifier = norm.metadata.identifier
    owner = norm.metadata.source
    if not _claim(identifier, owner):
        return norm

    candidate = f"{identifier}-{norm.metadata.publication_date:%Y%m%d}"
    if _claim(candidate, owner):
        digest = hashlib.sha1(owner.encode("utf-8")).hexdigest()[:8]
        candidate = f"{identifier}-{digest}"
        _claim(candidate, owner)
    logger.warning(
        "identifier %s was already written by another norm in this run; "
        "saving this one as %s — the country's identifier rule needs a discriminator",
        identifier,
        candidate,
    )
    return replace(norm, metadata=replace(norm.metadata, identifier=candidate))


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

    # Spec v0.3. Both are per-norm overrides of a country-level default, so they
    # have to survive the round-trip: commit_all_fast renders from the JSON, not
    # from the parser's output, and a dropped override silently republishes the
    # country default — which is the opposite claim on every consolidated norm
    # inside an as_enacted country.
    if meta.text_state is not None:
        metadata_dict["text_state"] = meta.text_state.value
    if meta.last_amendment:
        metadata_dict["last_amendment"] = meta.last_amendment

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

        row = {
            "date": reform.date.isoformat(),
            "source_id": reform.norm_id,
            "articles_affected": affected,
            "affected_block_ids": list(reform.affected_blocks),
        }
        # Same reason text_state is written here: commit_all_fast renders from this
        # file, not from the parser's output, so anything the parser resolved and
        # this drops is simply lost on the way to the commit.
        if reform.change_note:
            row["change_note"] = reform.change_note
        reforms.append(row)

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
        text_state=TextState(meta["text_state"]) if meta.get("text_state") else None,
        last_amendment=meta.get("last_amendment"),
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
                change_note=r.get("change_note", ""),
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
