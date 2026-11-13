"""Daily LDBIS updates using dated publications and the source reform timeline."""

from __future__ import annotations

import functools
import logging
from dataclasses import replace
from datetime import date
from pathlib import Path

from rich.console import Console

from legalize.committer.git_ops import GitRepo
from legalize.config import Config
from legalize.fetcher.mk.client import LDBISClient
from legalize.fetcher.mk.parser import LDBISMetadataParser
from legalize.pipeline import (
    SKIP_WEEKDAYS,
    commit_one,
    finalize_daily,
    generic_fetch_one,
)
from legalize.state.store import StateStore, resolve_dates_to_process
from legalize.storage import load_norma_from_json

console = Console()
logger = logging.getLogger(__name__)

# What a fetch adds to a card's metadata from the PDF and the chain, so a saved norm holds it and
# a card does not.
_FETCH_FIELDS = ("text_source", "ocr_doubtful_pages", "ocr_unread_pages", "amends")


def _unchanged(client: LDBISClient, data_dir: str, norm_id: str) -> bool:
    """Whether a record is saved and its card still gives the saved metadata and reforms.

    A day's discovery returns the whole related chain of every record published that day, 518
    cards on 2026-09-10, and nearly all of them are already in the repository unchanged. Such a
    record needs no PDF, no parse and no commit: its text is as enacted, and the laws a new act
    amends gain the reform through their reforms, which the card's chain gives."""
    card = client.get_metadata(norm_id)
    metadata = LDBISMetadataParser().parse(card, norm_id)
    path = Path(data_dir) / "json" / f"{metadata.identifier}.json"
    saved = load_norma_from_json(path) if path.exists() else None
    if saved is None:
        return False
    card_fields = tuple((k, v) for k, v in saved.metadata.extra if k not in _FETCH_FIELDS)
    return replace(saved.metadata, extra=card_fields) == metadata and tuple(
        client.get_reforms(norm_id, card)
    ) == tuple(saved.reforms)


def daily(
    config: Config,
    target_date: date | None = None,
    dry_run: bool = False,
    since: date | None = None,
) -> int:
    """Process only newly published LDBIS records and their linked law histories, from ``since``
    to today when it is given."""
    from legalize.countries import get_client_class, get_discovery_class

    cc = config.get_country("mk")
    state = StateStore(cc.state_path)
    state.load()
    dates = resolve_dates_to_process(
        state,
        cc.repo_path,
        target_date,
        skip_weekdays=SKIP_WEEKDAYS.get("mk", set()),
        since=since,
    )
    if dates is None:
        console.print("[yellow]No last date found. Use --date or run bootstrap.[/yellow]")
        return 0
    if not dates:
        console.print("[green]Nothing to process — up to date[/green]")
        return 0

    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    discovery = get_discovery_class("mk").create(cc.source or {})
    client_class = get_client_class("mk")
    commits_created = 0
    pushed = 0
    errors: list[str] = []

    with client_class.create(cc) as client:
        # One run reads each card once: discovery, the reform chains and the check for an
        # unchanged record ask for the same cards, and chains repeat from day to day.
        client.get_metadata = functools.cache(client.get_metadata)
        for current_date in dates:
            console.print(f"\n  [bold]{current_date}[/bold]")
            try:
                norm_ids = list(discovery.discover_daily(client, current_date))
            except Exception as exc:
                message = f"Error discovering publications for {current_date}: {exc}"
                errors.append(message)
                logger.exception("LDBIS daily discovery failed for %s", current_date)
                state.finish_day(current_date, errors)
                continue

            console.print(f"    {len(norm_ids)} record(s), including related histories")
            for norm_id in norm_ids:
                if dry_run:
                    console.print(
                        f"    [dim]{norm_id} — would fetch and commit source versions[/dim]"
                    )
                    continue
                try:
                    if _unchanged(client, cc.data_dir, norm_id):
                        continue
                    norm = generic_fetch_one(config, "mk", norm_id, force=True)
                    if norm is not None:
                        commits_created += commit_one(config, "mk", norm.metadata.identifier)
                except Exception as exc:
                    message = f"Error processing {norm_id}: {exc}"
                    errors.append(message)
                    logger.exception("LDBIS daily processing failed for %s", norm_id)

            state.finish_day(current_date, errors)
            if not dry_run and config.git.push and commits_created > pushed:
                try:
                    repo.push()
                    pushed = commits_created
                except Exception:
                    logger.exception("LDBIS checkpoint push failed after %s", current_date)

    return finalize_daily(
        repo,
        state,
        dates,
        commits_created,
        errors,
        dry_run=dry_run,
        push=config.git.push,
    )
