"""Daily LDBIS updates using dated publications and the source reform timeline."""

from __future__ import annotations

import logging
from datetime import date

from rich.console import Console

from legalize.committer.git_ops import GitRepo
from legalize.config import Config
from legalize.pipeline import (
    SKIP_WEEKDAYS,
    commit_one,
    finalize_daily,
    generic_fetch_one,
)
from legalize.state.store import StateStore, resolve_dates_to_process

console = Console()
logger = logging.getLogger(__name__)


def daily(config: Config, target_date: date | None = None, dry_run: bool = False) -> int:
    """Process only newly published LDBIS records and their linked law histories."""
    from legalize.countries import get_client_class, get_discovery_class

    cc = config.get_country("mk")
    state = StateStore(cc.state_path)
    state.load()
    dates = resolve_dates_to_process(
        state,
        cc.repo_path,
        target_date,
        skip_weekdays=SKIP_WEEKDAYS.get("mk", set()),
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
