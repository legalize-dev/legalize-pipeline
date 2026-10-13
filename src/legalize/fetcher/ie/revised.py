"""Refresh Revised Acts through the same complete history pipeline as bootstrap."""

from __future__ import annotations

import logging
from pathlib import Path

from legalize.committer.git_ops import GitRepo
from legalize.config import Config
from legalize.fetcher.ie.client import ISBClient, refresh_sources
from legalize.fetcher.ie.daily import refresh_norms
from legalize.fetcher.ie.history import REVISED_INDEX, revised_catalog
from legalize.pipeline import console, finalize_daily
from legalize.state.store import StateStore

logger = logging.getLogger(__name__)


def apply_revised_acts(
    config: Config,
    *,
    dry_run: bool = False,
    limit: int | None = None,
) -> int:
    """Fetch enactments, effects and all LRC snapshots, then commit missing events."""
    cc = config.get_country("ie")
    if not Path(cc.repo_path).exists():
        raise FileNotFoundError("Ireland repository not found. Run bootstrap first.")
    if limit is not None and limit < 1:
        raise ValueError("The Revised Acts limit must be positive")

    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    state = StateStore(cc.state_path)
    state.load()
    created = 0
    errors: list[str] = []
    with refresh_sources():
        try:
            with ISBClient.create(cc) as client:
                identifiers = _discover_revised_ids(client)
            if limit is not None:
                identifiers = identifiers[:limit]
            console.print(f"[bold]Revised Acts — refreshing {len(identifiers)} histories[/bold]")
            created, errors = refresh_norms(config, identifiers, dry_run=dry_run)
        except Exception as exc:
            logger.exception("Failed to discover the Revised Acts catalogue")
            errors.append(f"Revised Acts catalogue: {exc}")

    return finalize_daily(repo, state, [], created, errors, dry_run=dry_run, push=config.git.push)


def _discover_revised_ids(client: ISBClient) -> list[str]:
    """Use the canonical archive catalogue; a missing catalogue is an error."""
    return sorted(revised_catalog(client._get(REVISED_INDEX)))
