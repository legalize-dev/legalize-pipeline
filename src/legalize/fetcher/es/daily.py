"""Spain-specific daily processing.

Processes BOE daily summaries (sumarios) and generates commits for new legislation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import date, timedelta

import requests
from lxml import etree

from rich.console import Console

from legalize.committer.git_ops import GitRepo
from legalize.committer.message import build_commit_info
from legalize.config import Config
from legalize.models import CommitType, ParsedNorm, TextState
from legalize.pipeline import SKIP_WEEKDAYS, _with_last_amendment, finalize_daily
from legalize.state.store import StateStore, resolve_dates_to_process
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath

console = Console()
logger = logging.getLogger(__name__)


def _parse_updated_ids(xml_data: bytes) -> list[str]:
    """BOE-IDs from the consolidated-updates listing, newest update first."""
    root = etree.fromstring(xml_data)
    if root.findtext("status/code") != "200":
        raise ValueError("BOE update index did not return status 200")
    ids: list[str] = []
    for item in root.iter("item"):
        ref = (item.findtext("identificador") or "").strip()
        if ref and not ref.startswith("DOUE-"):
            ids.append(ref)
    return ids


def _updated_norms(client, start: date, end: date) -> list[str]:
    """Fail a day whose update index could not be read instead of losing reforms."""
    return _parse_updated_ids(client.get_updated(start, end))


def _commit_norm(repo: GitRepo, norm: ParsedNorm, current_date: date) -> int:
    """Append source versions; an older backfill must never replace a newer HEAD."""
    metadata = norm.metadata
    path = norm_to_filepath(metadata)
    existing = repo.has_file(path)
    history = repo._run(
        [
            "log",
            "--format=%(trailers:key=Source-Id,valueonly,separator=)%x09%(trailers:key=Source-Date,valueonly,separator=)%x09%(trailers:key=Effective-Date,valueonly,separator=)%x00",
            f"--grep=^Norm-Id: {re.escape(metadata.identifier)}$",
        ],
        check=False,
    )
    stages = {
        tuple(line.strip("\n").split("\t")) for line in history.split("\0") if line.count("\t") == 2
    }
    published = [date.fromisoformat(day) for _, day, _ in stages if day]
    head_date = max(published, default=date.min)
    previous = repo._run(["show", f"HEAD:{path}"], check=False) if existing else ""
    promoting = (
        'text_state: "as_enacted"' in previous and metadata.text_state is TextState.POINT_IN_TIME
    )
    applicable = [reform for reform in norm.reforms if reform.date <= current_date]
    if promoting:
        # Earlier commits truthfully retain the original gazette body they published.
        applicable = applicable[-1:]
    blocks = tuple(
        replace(
            block, versions=tuple(v for v in block.versions if v.publication_date <= current_date)
        )
        for block in norm.blocks
    )
    commits = 0
    for reform in applicable:
        key = (
            reform.norm_id,
            reform.date.isoformat(),
            reform.effective_date.isoformat() if reform.effective_date else "",
        )
        legacy = (key[0], key[1], "") in stages
        if key in stages or (legacy and not promoting):
            continue
        if head_date > current_date or (reform.date < head_date and not promoting):
            raise ValueError(
                f"{metadata.identifier}: historical gap before published HEAD; reprocess this law before backfilling"
            )
        markdown = render_norm_at_date(
            _with_last_amendment(metadata, reform),
            blocks,
            reform.date,
            include_all=not existing,
            source_id=reform.norm_id,
            effective_date=reform.effective_date or reform.date,
        )
        changed = repo.write_and_add(path, markdown)
        if not changed and promoting:
            continue
        commit_type = (
            CommitType.CORRECTION
            if promoting
            else (CommitType.REFORM if existing else CommitType.NEW)
        )
        info = build_commit_info(commit_type, metadata, reform, blocks, path, markdown)
        if repo.commit(info, allow_empty=True):
            commits += 1
            existing = True
            stages.add(key)
            console.print(f"    [green]✓[/green] {info.subject}")
    return commits


def _commit_reforms(
    client, repo: GitRepo, start: date, current_date: date, errors: list[str]
) -> int:
    """Consolidation can both update a law and introduce one missing from the corpus."""
    from legalize.fetcher.es.fetch import fetch_norm

    try:
        identifiers = _updated_norms(client, start, current_date)
    except (requests.RequestException, etree.XMLSyntaxError, ValueError):
        errors.append(f"Error listing updated norms for {current_date}")
        logger.error(errors[-1], exc_info=True)
        return 0
    commits = 0
    for norm_id in identifiers:
        try:
            commits += _commit_norm(repo, fetch_norm(client, norm_id, force=True), current_date)
        except (requests.RequestException, ValueError, OSError):
            errors.append(f"Error processing updated norm {norm_id}")
            logger.error(errors[-1], exc_info=True)
    return commits


def daily(
    config: Config,
    target_date: date | None = None,
    dry_run: bool = False,
) -> int:
    """Daily processing: process BOE summary/summaries."""
    from legalize.fetcher.cache import FileCache
    from legalize.fetcher.es.client import BOEClient
    from legalize.fetcher.es.config import BOEConfig, ScopeConfig
    from legalize.fetcher.es.fetch import fetch_norm
    from legalize.fetcher.es.diary import ExcludedDiary, record_exclusion
    from legalize.storage import save_structured_json
    from legalize.fetcher.es.sumario import parse_summary

    cc = config.get_country("es")
    source = cc.source
    boe_config = BOEConfig(
        base_url=source.get("base_url", BOEConfig.base_url),
        requests_per_second=source.get("requests_per_second", BOEConfig.requests_per_second),
        request_timeout=source.get("request_timeout", BOEConfig.request_timeout),
        max_retries=source.get("max_retries", BOEConfig.max_retries),
    )
    scope = ScopeConfig(
        ranks=source.get("rangos", []),
        fixed_norms=source.get("normas_fijas", []),
    )
    cache = FileCache(cc.cache_dir)
    state = StateStore(cc.state_path)
    state.load()

    dates_to_process = resolve_dates_to_process(
        state,
        cc.repo_path,
        target_date,
        skip_weekdays=SKIP_WEEKDAYS["es"],
    )
    if dates_to_process is None:
        console.print("[yellow]No last summary found. Use --date or run bootstrap.[/yellow]")
        return 0
    if not dates_to_process:
        console.print("[green]Nothing to process — up to date[/green]")
        return 0

    console.print(f"[bold]Daily — processing {len(dates_to_process)} day(s)[/bold]")

    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    commits_created = 0
    errors: list[str] = []

    with BOEClient(boe_config, cache) as client:
        for current_date in dates_to_process:
            console.print(f"\n  [bold]{current_date}[/bold]")

            # Amendments first, and before the summary is even fetched: they are the
            # source's own list of what changed, so a day with no summary (or a failed
            # one) must not skip them. The window reaches back one day to cover the
            # Sunday the BOE consolidates on and this schedule never runs; re-seeing a
            # norm is a no-op, the Source-Id guard drops it.
            if not dry_run:
                commits_created += _commit_reforms(
                    client,
                    repo,
                    current_date - timedelta(days=1),
                    current_date,
                    errors,
                )

            try:
                xml_data = client.get_sumario(current_date)
                dispositions = parse_summary(xml_data, scope)
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    state.finish_day(current_date, errors)
                    continue
                msg = f"Error fetching summary for {current_date}"
                logger.error(msg, exc_info=True)
                errors.append(msg)
                continue
            except (requests.RequestException, etree.XMLSyntaxError, ValueError):
                msg = f"Error fetching summary for {current_date}"
                logger.error(msg, exc_info=True)
                errors.append(msg)
                continue

            if not dispositions:
                console.print("    No dispositions in scope")
                state.finish_day(current_date, errors)
                continue

            console.print(f"    {len(dispositions)} dispositions in scope")

            for disp in dispositions:
                if dry_run:
                    console.print(f"    [dim]{disp.id_boe} — {disp.title[:60]}...[/dim]")
                    continue

                try:
                    norm = fetch_norm(client, disp.id_boe)
                    save_structured_json(cc.data_dir, norm)
                    commits_created += _commit_norm(repo, norm, current_date)
                except ExcludedDiary as exc:
                    record_exclusion(cc.data_dir, exc)
                    console.print(f"    [dim]{exc}[/dim]")
                except (requests.RequestException, ValueError, OSError):
                    msg = f"Error processing {disp.id_boe}"
                    logger.error(msg, exc_info=True)
                    errors.append(msg)

            state.finish_day(current_date, errors)

    return finalize_daily(
        repo,
        state,
        dates_to_process,
        commits_created,
        errors,
        dry_run=dry_run,
        push=config.git.push,
    )
