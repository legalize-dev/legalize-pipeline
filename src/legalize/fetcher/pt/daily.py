"""Portugal-specific daily processing.

Fetches new legislation directly from diariodarepublica.pt via HTTP.
No SQLite dump needed — works in CI environments.

Discovery is done via the OutSystems API: list journals by date,
then list documents per journal, then fetch full text per document.
"""

from __future__ import annotations

import logging
from datetime import date

from rich.console import Console

from legalize.committer.git_ops import GitRepo
from legalize.committer.message import build_commit_info
from legalize.config import Config
from legalize.models import CommitType, Reform
from legalize.pipeline import finalize_daily
from legalize.state.store import StateStore, resolve_dates_to_process
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath

console = Console()
logger = logging.getLogger(__name__)

# Series I document types we care about (major legislative acts)
_MAJOR_TYPES = {
    "LEI",
    "LEI CONSTITUCIONAL",
    "LEI ORGÂNICA",
    "DECRETO-LEI",
    "DECRETO LEI",
    "DECRETO REGULAMENTAR",
    "DECRETO LEGISLATIVO REGIONAL",
    "DECRETO REGULAMENTAR REGIONAL",
    "DECRETO",
    "PORTARIA",
    "RESOLUÇÃO",
}


def _discover_daily_http(client, target_date: date) -> list[dict]:
    """Discover documents published on target_date via HTTP.

    Returns list of dicts with 'diploma_id' and basic metadata.
    Filters to Series I major legislative types only.
    """
    date_str = target_date.isoformat()
    documents = []

    journals = client.get_journals_by_date(date_str)
    if not journals:
        return []

    for journal in journals:
        # Filter to Serie I only (skip Serie II, III, and supplements)
        title = journal.get("conteudoTitle", "")
        if title and ("Série I" not in title or "Suplemento" in title):
            continue

        journal_id = journal.get("Id") or journal.get("DiarioId")
        if not journal_id:
            continue

        docs = client.get_documents_by_journal(int(journal_id), is_serie1=True)
        for doc in docs:
            # Handle both old (TipoActo) and new (TipoDiploma) API field names
            doc_type = (
                (doc.get("TipoActo") or doc.get("TipoDiploma") or doc.get("Tipo") or "")
                .strip()
                .upper()
            )
            if doc_type in _MAJOR_TYPES:
                diploma_id = (
                    doc.get("DiplomaLegisId")
                    or doc.get("DiplomaConteudoId")
                    or doc.get("ConteudoId")
                    or doc.get("Id")
                )
                if diploma_id:
                    documents.append(
                        {
                            "diploma_id": str(diploma_id),
                            "doc_type": doc_type,
                            "title": doc.get("Sumario", doc_type),
                        }
                    )

    return documents


def daily(
    config: Config,
    target_date: date | None = None,
    dry_run: bool = False,
) -> int:
    """Daily processing for Portugal via HTTP (no SQLite needed)."""
    from legalize.fetcher.pt.client import DREApiError, DREHttpClient
    from legalize.fetcher.pt.parser import DREMetadataParser, DRETextParser

    cc = config.get_country("pt")
    state = StateStore(cc.state_path)
    state.load()

    dates_to_process = resolve_dates_to_process(
        state,
        cc.repo_path,
        target_date,
        skip_weekdays={5, 6},
    )
    if dates_to_process is None:
        console.print("[yellow]No last date found. Use --date or run bootstrap.[/yellow]")
        return 0
    if not dates_to_process:
        console.print("[green]Nothing to process — up to date[/green]")
        return 0

    console.print(f"[bold]Daily PT — processing {len(dates_to_process)} day(s)[/bold]")

    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    commits_created = 0
    errors: list[str] = []

    text_parser = DRETextParser()
    meta_parser = DREMetadataParser()

    with DREHttpClient.create(cc) as client:
        for current_date in dates_to_process:
            console.print(f"\n  [bold]{current_date}[/bold]")

            try:
                documents = _discover_daily_http(client, current_date)
            except DREApiError:
                # A broken DRE contract is not a bad day, it is a broken
                # client: every remaining date would fail the same way and
                # record itself as "no new norms". Abort loudly instead.
                logger.exception("DRE API contract broken — aborting daily run")
                raise
            except Exception:
                msg = f"Error discovering changes for {current_date}"
                logger.exception(msg)
                errors.append(msg)
                continue

            if not documents:
                console.print("    No new norms found")
                state.last_summary_date = current_date
                continue

            console.print(f"    {len(documents)} norm(s) found")

            for doc_info in documents:
                diploma_id = doc_info["diploma_id"]

                if dry_run:
                    console.print(
                        f"    [dim]{doc_info['doc_type']} — {doc_info['title'][:60]}[/dim]"
                    )
                    continue

                try:
                    meta_data = client.get_metadata(diploma_id)
                    metadata = meta_parser.parse(meta_data, diploma_id)

                    text_data = client.get_text(diploma_id)
                    blocks = text_parser.parse_text_with_date(
                        text_data, metadata.publication_date, metadata.identifier
                    )

                    file_path = norm_to_filepath(metadata)
                    markdown = render_norm_at_date(metadata, blocks, current_date, include_all=True)

                    changed = repo.write_and_add(file_path, markdown)
                    if not changed:
                        console.print(f"    [dim]⏭ {metadata.short_title[:60]} — no changes[/dim]")
                        continue

                    reform = Reform(
                        date=current_date,
                        norm_id=f"DRE-DAILY-{current_date.isoformat()}",
                        affected_blocks=(),
                    )
                    info = build_commit_info(
                        CommitType.NEW,
                        metadata,
                        reform,
                        blocks,
                        file_path,
                        markdown,
                    )
                    sha = repo.commit(info)

                    if sha:
                        commits_created += 1
                        console.print(f"    [green]✓[/green] {info.subject}")

                except Exception as e:
                    msg = f"Error processing diploma_id={diploma_id}: {e}"
                    logger.exception(msg)
                    errors.append(msg)

            state.last_summary_date = current_date

    return finalize_daily(
        repo,
        state,
        dates_to_process,
        commits_created,
        errors,
        dry_run=dry_run,
        push=config.git.push,
    )
