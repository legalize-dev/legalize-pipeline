"""Structured commit message construction.

Generic multi-country format:
    [type] Title — affected articles

    Norm: BOE-A-1978-31229
    Disposition: BOE-A-2024-3099
    Date: 2024-02-17
    Source: https://www.boe.es/...
    Affected articles: art. 49

    Source-Id: BOE-A-2024-3099
    Source-Date: 2024-02-17
    Norm-Id: BOE-A-1978-31229
"""

from __future__ import annotations

import re

from legalize.committer.author import resolve_author
from legalize.models import (
    Block,
    CommitInfo,
    CommitType,
    NormMetadata,
    Reform,
)


def build_commit_info(
    commit_type: CommitType,
    norm_metadata: NormMetadata,
    reform: Reform,
    blocks: list[Block] | tuple[Block, ...],
    file_path: str,
    content: str,
) -> CommitInfo:
    """Build a complete CommitInfo from domain data."""
    affected = _get_affected_articles(reform, blocks)
    affected_str = ", ".join(affected) if affected else "N/A"

    subject = _build_subject(commit_type, norm_metadata, reform, affected)
    body = _build_body(commit_type, norm_metadata, reform, affected_str)

    trailers = {
        "Source-Id": reform.norm_id,
        "Source-Date": reform.date.isoformat(),
        "Norm-Id": norm_metadata.identifier,
    }

    author_name, author_email = resolve_author()

    return CommitInfo(
        commit_type=commit_type,
        subject=subject,
        body=body,
        trailers=trailers,
        author_name=author_name,
        author_email=author_email,
        author_date=reform.date,
        file_path=file_path,
        content=content,
    )


def format_commit_message(info: CommitInfo) -> str:
    """Format CommitInfo as a complete git commit message."""
    parts = [info.subject, "", info.body]

    if info.trailers:
        parts.append("")
        for key, value in info.trailers.items():
            parts.append(f"{key}: {value}")

    return "\n".join(parts)


def _build_subject(
    commit_type: CommitType,
    metadata: NormMetadata,
    reform: Reform,
    affected: list[str] | None = None,
) -> str:
    """Build the first line of the commit message.

    [reform] Constitución Española — art. 49
    """
    prefix = f"[{commit_type.value}]"
    title = metadata.short_title

    if commit_type == CommitType.BOOTSTRAP:
        return f"{prefix} {title} — original version {reform.date.year}"

    if commit_type == CommitType.FIX_PIPELINE:
        return f"{prefix} Regenerate {title}"

    if affected:
        arts_brief = _abbreviate_articles(affected)
        if arts_brief:
            return f"{prefix} {title} — {arts_brief}"

    return f"{prefix} {title}"


def _build_body(
    commit_type: CommitType,
    metadata: NormMetadata,
    reform: Reform,
    affected_str: str,
) -> str:
    """Build the commit message body."""
    date_str = reform.date.isoformat()

    if commit_type == CommitType.BOOTSTRAP:
        return (
            f"Original publication of {metadata.short_title}.\n"
            f"\n"
            f"Norm: {metadata.identifier}\n"
            f"Date: {date_str}\n"
            f"Source: {metadata.source}"
        )

    body = (
        f"Norm: {metadata.identifier}\n"
        f"Disposition: {reform.norm_id}\n"
        f"Date: {date_str}\n"
        f"Source: {metadata.source}\n"
        f"\n"
        f"Affected articles: {affected_str}"
    )
    # Its own line, not folded into "Affected articles", because it answers a
    # different question and often is not about articles at all — half of DRE's
    # notes read "Revogado a partir de 10.10.2007". Emitted only when the source
    # said something, so no country's output changes until its fetcher fills it.
    if reform.change_note:
        body += f"\nChange: {reform.change_note}"
    return body


def _abbreviate_articles(articles: list[str]) -> str:
    """Abbreviate list of articles for the commit subject.

    ['Article 49'] → 'art. 49'
    ['Article 13', 'Article 14'] → 'arts. 13, 14'
    """
    nums = []
    for art in articles:
        match = re.search(r"(\d+)", art)
        if match:
            nums.append(match.group(1))

    if not nums:
        return ""

    if len(nums) == 1:
        return f"art. {nums[0]}"

    if len(nums) <= 4:
        return f"arts. {', '.join(nums)}"

    shown = ", ".join(nums[:3])
    return f"arts. {shown} and {len(nums) - 3} more"


def _get_affected_articles(reform: Reform, blocks: list[Block] | tuple[Block, ...]) -> list[str]:
    """Get titles of articles affected by a reform."""
    titles = []
    block_map = {b.id: b for b in blocks}
    for bid in reform.affected_blocks:
        block = block_map.get(bid)
        if block and block.title:
            titles.append(block.title)
    return titles
