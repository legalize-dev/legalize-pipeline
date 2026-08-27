"""Portugal-specific daily processing.

Two things happen every day and they are not the same thing:

1. **New diplomas** are published in the Diário da República. Found by walking the
   day's journal issues, committed as ``[new]``.
2. **Existing consolidated diplomas are re-consolidated** because something amended
   them. DRE does this on its own schedule, days or weeks after the amending act
   appears, so watching the day's publications would miss it.

The second is what makes Portugal a versioned corpus rather than a pile of
snapshots, and it is detected for the price of one HTTP request: the consolidated
sitemap carries a ``<lastmod>`` per diploma. Diff it against yesterday's copy and
re-fetch exactly the diplomas whose consolidation moved.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
from datetime import date
from pathlib import Path

from rich.console import Console

from legalize.committer.git_ops import GitRepo
from legalize.committer.message import build_commit_info
from legalize.config import Config
from legalize.models import CommitType, Reform
from legalize.pipeline import SKIP_WEEKDAYS, finalize_daily
from legalize.state.store import StateStore, resolve_dates_to_process
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath

console = Console()
logger = logging.getLogger(__name__)

_URL_ENTRY = re.compile(
    r"<url>\s*<loc>([^<]+)</loc>\s*(?:<lastmod>([^<]*)</lastmod>)?", re.IGNORECASE | re.DOTALL
)
_CONS_URL = re.compile(r"/dr/legislacao-consolidada/([^/]+)/(\d{4})-(\d+)")


def _lastmod_state_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / "consolidated_lastmod.json.gz"


def _read_lastmods(data_dir: str | Path) -> dict[str, str]:
    path = _lastmod_state_path(data_dir)
    if not path.exists():
        return {}
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        logger.warning("Unreadable lastmod state at %s, treating as empty", path)
        return {}


def _write_lastmods(data_dir: str | Path, lastmods: dict[str, str]) -> None:
    path = _lastmod_state_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(lastmods, handle)


def fetch_consolidated_lastmods(client) -> dict[str, str]:
    """``{norm_id: lastmod}`` for every consolidated diploma. One request."""
    from legalize.fetcher.pt.discovery import CONSOLIDATED_SITEMAP, SITEMAP_INDEX

    index = client._api.get_text_body(SITEMAP_INDEX)
    target = next(
        (u for u in re.findall(r"<loc>([^<]+)</loc>", index) if u.endswith(CONSOLIDATED_SITEMAP)),
        None,
    )
    if not target:
        raise RuntimeError("The consolidated sitemap is no longer in the DRE index")

    lastmods: dict[str, str] = {}
    for url, lastmod in _URL_ENTRY.findall(client._api.get_text_body(target)):
        match = _CONS_URL.search(url)
        if match:
            lastmods[f"cons:{match.group(1)}:{match.group(2)}-{match.group(3)}"] = lastmod or ""
    return lastmods


def reconsolidated_since_last_run(client, data_dir: str | Path) -> tuple[list[str], dict[str, str]]:
    """Which consolidated diplomas DRE has touched since we last looked."""
    current = fetch_consolidated_lastmods(client)
    previous = _read_lastmods(data_dir)
    if not previous:
        # First run after the bootstrap: record the baseline, claim nothing changed.
        return [], current
    changed = [nid for nid, stamp in current.items() if previous.get(nid) != stamp]
    return changed, current


def daily(config: Config, target_date: date | None = None, dry_run: bool = False) -> int:
    """Daily processing for Portugal: new diplomas + re-consolidated ones."""
    from legalize.fetcher.pt import analise_juridica
    from legalize.fetcher.pt.client import DREClient
    from legalize.fetcher.pt.discovery import DREDiscovery
    from legalize.fetcher.pt.dre_api import DREApiError
    from legalize.fetcher.pt.parser import DREMetadataParser
    from legalize.pipeline import generic_fetch_one

    cc = config.get_country("pt")
    state = StateStore(cc.state_path)
    state.load()

    # Without these the daily quietly regresses every law it touches: descriptors
    # come back as nothing, and an amendment lands as a new law with no reform
    # recorded against the law it amended. They are corpus-wide maps, so nothing in
    # the per-norm fetch path would load them.
    loaded = analise_juridica.install(cc.data_dir)
    console.print(f"  [dim]análise jurídica: {loaded or 'no maps found'}[/dim]")

    dates_to_process = resolve_dates_to_process(
        # Monday to Friday: the daily has run on 121 of 125 weekdays, and the
        # four misses were Portuguese public holidays.
        state,
        cc.repo_path,
        target_date,
        skip_weekdays=SKIP_WEEKDAYS["pt"],
    )
    if dates_to_process is None:
        console.print("[yellow]No last date found. Use --date or run bootstrap.[/yellow]")
        return 0

    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    meta_parser = DREMetadataParser()
    discovery = DREDiscovery.create({**cc.source, "cache_dir": cc.data_dir})
    commits_created = 0
    errors: list[str] = []
    # Laws today's diplomas say they change. Collected as we go and resolved once at
    # the end, because the record of the amendment lives on the amended law's page,
    # not on the act's, so it has to be looked up per law rather than per act.
    amended_today: set[str] = set()

    with DREClient.create(cc) as client:
        # ---- 1. diplomas DRE re-consolidated: one commit per new reform ----
        try:
            changed, lastmods = reconsolidated_since_last_run(client, cc.data_dir)
        except DREApiError:
            logger.exception("DRE API contract broken while reading the sitemap — aborting")
            raise
        if changed:
            console.print(f"[bold]{len(changed)} diploma(s) re-consolidated[/bold]")
        for norm_id in changed:
            if dry_run:
                console.print(f"  [dim]would refresh {norm_id}[/dim]")
                continue
            try:
                commits_created += _commit_versions(
                    config, repo, client, norm_id, generic_fetch_one
                )
            except DREApiError:
                logger.exception("DRE API contract broken — aborting daily run")
                raise
            except Exception as exc:
                errors.append(f"Error refreshing {norm_id}: {exc}")
                logger.exception("Error refreshing %s", norm_id)

        # ---- 2. diplomas published on each pending date ----
        for current_date in dates_to_process:
            console.print(f"\n  [bold]{current_date}[/bold]")
            try:
                norm_ids = list(discovery.discover_daily(client, current_date))
            except DREApiError:
                # A broken contract is not a quiet day: every remaining date would
                # fail the same way and record itself as "no new norms".
                logger.exception("DRE API contract broken — aborting daily run")
                raise
            except Exception as exc:
                errors.append(f"Error discovering {current_date}: {exc}")
                logger.exception("Error discovering %s", current_date)
                continue

            if not norm_ids:
                console.print("    No new norms found")
                state.last_summary_date = current_date
                continue

            console.print(f"    {len(norm_ids)} norm(s) found")

            for norm_id in norm_ids:
                if dry_run:
                    console.print(f"    [dim]{norm_id}[/dim]")
                    continue
                try:
                    norm = generic_fetch_one(config, "pt", norm_id, force=True)
                    if norm is None:
                        continue
                    metadata = meta_parser.parse(client.get_metadata(norm_id), norm_id)
                    file_path = norm_to_filepath(metadata)
                    markdown = render_norm_at_date(
                        metadata, norm.blocks, metadata.publication_date, include_all=True
                    )
                    if not repo.write_and_add(file_path, markdown):
                        continue
                    reform = Reform(
                        date=metadata.publication_date,
                        norm_id=metadata.identifier,
                        affected_blocks=(),
                    )
                    info = build_commit_info(
                        CommitType.NEW, metadata, reform, norm.blocks, file_path, markdown
                    )
                    if repo.commit(info):
                        commits_created += 1
                        console.print(f"    [green]✓[/green] {info.subject}")
                    amended_today |= analise_juridica.targets_named_by(markdown)
                except DREApiError:
                    logger.exception("DRE API contract broken — aborting daily run")
                    raise
                except Exception as exc:
                    errors.append(f"Error processing {norm_id}: {exc}")
                    logger.exception("Error processing %s", norm_id)

            state.last_summary_date = current_date

        # ---- 3. the laws today's acts amended: one commit each, body unchanged ----
        if amended_today and not dry_run:
            try:
                changed_laws = analise_juridica.refresh_amendments(
                    client._api, cc.data_dir, amended_today
                )
            except Exception as exc:
                errors.append(f"Error refreshing amendments: {exc}")
                logger.exception("Error refreshing amendments")
                changed_laws = set()
            if changed_laws:
                console.print(f"\n[bold]{len(changed_laws)} law(s) amended today[/bold]")
            for law_id in sorted(changed_laws):
                try:
                    commits_created += _commit_versions(
                        config, repo, client, law_id, generic_fetch_one
                    )
                except Exception as exc:
                    errors.append(f"Error recording amendment on {law_id}: {exc}")
                    logger.exception("Error recording amendment on %s", law_id)

        # Only record the sitemap baseline once the run got this far: crashing
        # mid-run must not make us forget the diplomas we had not refreshed yet.
        if not dry_run and not errors:
            _write_lastmods(cc.data_dir, lastmods)

    return finalize_daily(
        repo,
        state,
        dates_to_process,
        commits_created,
        errors,
        dry_run=dry_run,
        push=config.git.push,
    )


def _commit_versions(config, repo, client, norm_id: str, fetch_one) -> int:
    """Re-fetch a consolidated diploma and commit any version it has gained."""
    from legalize.fetcher.pt.parser import DREMetadataParser

    norm = fetch_one(config, "pt", norm_id, force=True)
    if norm is None or not norm.reforms:
        return 0
    metadata = DREMetadataParser().parse(client.get_metadata(norm_id), norm_id)
    file_path = norm_to_filepath(metadata)
    created = 0

    for index, reform in enumerate(norm.reforms):
        # One reform can affect many norms, so the dedupe key is the pair.
        if repo.has_commit_with_source_id(reform.norm_id, metadata.identifier):
            continue
        markdown = render_norm_at_date(metadata, norm.blocks, reform.date, include_all=index == 0)
        if not repo.write_and_add(file_path, markdown):
            continue
        commit_type = CommitType.BOOTSTRAP if index == 0 else CommitType.REFORM
        info = build_commit_info(commit_type, metadata, reform, norm.blocks, file_path, markdown)
        if repo.commit(info):
            created += 1
    return created
