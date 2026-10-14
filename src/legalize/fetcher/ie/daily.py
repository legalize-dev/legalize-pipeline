"""Refresh Ireland's complete source inventory, including late consolidations."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from legalize.committer.git_ops import GitRepo
from legalize.config import Config
from legalize.fetcher.ie.client import ISBClient, refresh_sources
from legalize.fetcher.ie.discovery import ISBDiscovery
from legalize.fetcher.ie.history import REVISED_INDEX, revised_catalog
from legalize.pipeline import commit_one, console, finalize_daily, generic_fetch_one
from legalize.state.store import StateStore, resolve_dates_to_process

logger = logging.getLogger(__name__)


def refresh_norms(
    config: Config, identifiers: list[str], *, dry_run: bool = False
) -> tuple[int, list[str]]:
    """Fetch complete histories and their source instruments before committing."""
    from legalize.fetcher.ie.bootstrap import fetch_dependencies

    identifiers = list(dict.fromkeys(identifiers))
    if dry_run:
        for norm_id in identifiers:
            console.print(f"  [dim]Would refresh {norm_id} and its source instruments[/dim]")
        return 0, []

    cc = config.get_country("ie")
    errors: list[str] = []
    fetched = []
    with ThreadPoolExecutor(max_workers=cc.max_workers or 1) as pool:
        futures = {
            norm_id: pool.submit(
                lambda key: generic_fetch_one(config, "ie", key, force=True) is not None,
                norm_id,
            )
            for norm_id in identifiers
        }
        for norm_id, future in futures.items():
            try:
                if not future.result():
                    raise ValueError("The complete source history could not be fetched")
                fetched.append(norm_id)
            except Exception as exc:
                logger.exception("Failed to refresh %s", norm_id)
                errors.append(f"{norm_id}: {exc}")

    if not fetched:
        return 0, errors
    try:
        dependencies = fetch_dependencies(config, fetched)
    except Exception as exc:
        logger.exception("Failed to fetch amendment source instruments")
        errors.append(f"Amendment source instruments: {exc}")
        return 0, errors

    created = 0
    for norm_id in dict.fromkeys([*dependencies, *fetched]):
        try:
            created += commit_one(config, "ie", norm_id)
        except Exception as exc:
            logger.exception("Failed to commit %s", norm_id)
            errors.append(f"{norm_id}: {exc}")
    return created, errors


def _inventory(client: ISBClient, data_dir: str) -> list[str]:
    """Include all Act namespaces, revised Acts and previously fetched dependencies."""
    identifiers = set(ISBDiscovery().discover_all(client))
    identifiers.update(revised_catalog(client._get(REVISED_INDEX)))
    # Dependency instruments form part of the published corpus too. Refresh their
    # effects even when they no longer occur in another Act's latest directory.
    identifiers.update(path.stem for path in (Path(data_dir) / "json").glob("IE-*.json"))
    return sorted(identifiers)


def daily(config: Config, target_date: date | None = None, dry_run: bool = False) -> int:
    """Replay authentic source histories without manufacturing daily reform events.

    eISB's API does not cover every Act namespace, and its update cursor does not
    describe LRC or Legislation Directory changes. Scan the complete inventory
    once per run, including when the daily date cursor is already current.
    """
    cc = config.get_country("ie")
    state = StateStore(cc.state_path)
    state.load()
    dates = resolve_dates_to_process(state, cc.repo_path, target_date)
    if dates is None:
        console.print("[yellow]No last date found. Use --date or run bootstrap.[/yellow]")
        return 0

    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    created = 0
    errors: list[str] = []
    with refresh_sources():
        try:
            with ISBClient.create(cc) as client:
                identifiers = _inventory(client, cc.data_dir)
            console.print(f"[bold]Ireland — refreshing {len(identifiers)} source histories[/bold]")
            created, errors = refresh_norms(config, identifiers, dry_run=dry_run)
        except Exception as exc:
            logger.exception("Failed to discover the complete Irish source inventory")
            errors.append(f"Source inventory: {exc}")

    if not dry_run:
        for current_date in dates:
            state.finish_day(current_date, errors)
    return finalize_daily(
        repo, state, dates, created, errors, dry_run=dry_run, push=config.git.push
    )
