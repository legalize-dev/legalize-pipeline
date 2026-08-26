"""Estonia-specific daily update.

Unlike the generic daily (one commit per norm_id from discover_daily),
Estonia's daily preserves the historical-chain model:

  1. Re-download the current-year bulk zip (regenerated daily by
     Riigi Teataja) and extract any new/changed XMLs.
  2. Find XMLs whose ``kehtivuseAlgus`` matches the target date.
  3. Filter by document_types and text_types.
  4. For each new version, look up the canonical filename by its
     ``terviktekstiGrupiID`` (the existing file in the repo under which
     we appended all previous versions of the same law).
  5. Render the new version's markdown and commit it with
     ``GIT_AUTHOR_DATE = kehtivuseAlgus``. If the law is brand new
     (no existing file for its group_id), the commit uses its own
     globaalID as the filename.

This keeps the "one file per law, one commit per historical version"
model stable across daily runs.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

from rich.console import Console

from legalize.committer.git_ops import GitRepo
from legalize.committer.message import build_commit_info
from legalize.config import Config
from legalize.fetcher.ee.client import RTClient
from legalize.fetcher.ee.discovery import RTDiscovery
from legalize.fetcher.ee.parser import RTMetadataParser, RTTextParser
from legalize.models import CommitType, Reform
from legalize.pipeline import finalize_daily
from legalize.state.store import StateStore, resolve_dates_to_process
from legalize.transformer.markdown import render_norm_at_date

console = Console()
logger = logging.getLogger(__name__)


# Frontmatter line to grep for when building the group_id → filename map
_GROUP_ID_RE = re.compile(r'^group_id:\s*"?(\d+)"?\s*$', re.MULTILINE)


def daily(
    config: Config,
    target_date: date | None = None,
    dry_run: bool = False,
) -> int:
    """Daily incremental update for Estonia.

    Returns the number of commits created.
    """
    cc = config.get_country("ee")
    state = StateStore(cc.state_path)
    state.load()

    # Skip weekdays: Riigi Teataja publishes Mon-Fri, but we process all
    # days to be safe (the bulk zip is regenerated daily anyway).
    dates_to_process = resolve_dates_to_process(
        state,
        cc.repo_path,
        target_date,
        skip_weekdays={5, 6},  # skip Sat+Sun
    )
    if dates_to_process is None:
        console.print("[yellow]No last date found. Use --date or run bootstrap.[/yellow]")
        return 0
    if not dates_to_process:
        console.print("[green]Nothing to process — up to date[/green]")
        return 0

    console.print(f"[bold]Daily EE — processing {len(dates_to_process)} day(s)[/bold]")

    # Refresh the current-year bulk zip so we pick up today's new XMLs.
    # Skip download if the local copy is already fresh (mtime >= today).
    #
    # The zip is not small and it is not the 1.1 GB this comment used to
    # claim: that was xml.2026.en.zip, the English subset. The Estonian
    # xml.{year}.zip measured 42.3 GB on 2026-08-26 (344 MB for 2024,
    # 2.8 GB for 2025 — it is growing by an order of magnitude a year),
    # which is why the CI daily never finishes. See #100.
    #
    # If the download fails (slow server, network issue) we fall back to
    # whatever is already extracted in legi/ — the daily will still run
    # against known data, just not the absolute freshest. That fallback
    # does NOT cover a download that is merely too slow: requests' timeout
    # is per-chunk, so the runner kills the job instead of raising here.
    discovery = RTDiscovery.create(cc)
    current_year = max(d.year for d in dates_to_process)
    zip_path = Path(cc.data_dir) / "bulk" / f"xml.{current_year}.zip"
    legi_dir = Path(cc.source.get("legi_dir") or (Path(cc.data_dir) / "legi"))

    try:
        needs_download = True
        if zip_path.exists():
            import os
            from datetime import datetime

            mtime = datetime.fromtimestamp(os.path.getmtime(zip_path)).date()
            if mtime >= date.today():
                needs_download = False
                console.print(
                    f"  Bulk dump xml.{current_year}.zip is fresh "
                    f"(mtime {mtime}), skipping download"
                )
        if needs_download:
            console.print(f"  Refreshing bulk dump for {current_year}...")
            discovery.ensure_bulk_dump(years=[current_year], force_download=True)
        else:
            console.print("  Extracting fresh XMLs from existing zip...")
            discovery.ensure_bulk_dump(years=[current_year], force_download=False)
    except Exception as e:
        console.print(
            f"  [yellow]Bulk dump refresh failed ({e}), "
            f"falling back to already-extracted XMLs in {legi_dir}[/yellow]"
        )
        logger.warning("ensure_bulk_dump failed, using existing XMLs", exc_info=True)
        # Verify we have at least something to work with
        if not legi_dir.is_dir() or not any(legi_dir.glob("*.xml")):
            console.print("  [red]No XMLs available. Aborting.[/red]")
            return 0

    # Build group_id → canonical filename map from the existing repo
    repo_ee_dir = Path(cc.repo_path) / "ee"
    group_to_filename = _build_group_map(repo_ee_dir)
    console.print(f"  Loaded {len(group_to_filename)} existing law groups from repo")

    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    if not dry_run:
        repo.init()
        repo.load_existing_commits()

    text_parser = RTTextParser()
    meta_parser = RTMetadataParser()

    commits_created = 0
    errors: list[str] = []

    with RTClient.create(cc) as client:
        for current_date in dates_to_process:
            console.print(f"\n  [bold]{current_date}[/bold]")

            # discover_daily re-walks every XML in legi_dir once per day, so
            # the scan time is per-day and grows with the corpus. Print it:
            # without it, a run that goes quiet gives no way to tell a slow
            # scan from a stuck fetch (see #100).
            scan_started = time.monotonic()
            try:
                norm_ids = list(discovery.discover_daily(client, current_date))
            except Exception as e:
                msg = f"discover_daily failed for {current_date}: {e}"
                logger.error(msg, exc_info=True)
                errors.append(msg)
                continue
            scan_secs = time.monotonic() - scan_started

            if not norm_ids:
                console.print(f"    No changes (scanned in {scan_secs:.0f}s)")
                state.last_summary_date = current_date
                continue

            console.print(
                f"    {len(norm_ids)} version(s) effective on {current_date} "
                f"(scanned in {scan_secs:.0f}s)"
            )

            for gid in norm_ids:
                try:
                    commits = _process_version(
                        client,
                        text_parser,
                        meta_parser,
                        repo,
                        gid,
                        current_date,
                        group_to_filename,
                        dry_run=dry_run,
                    )
                    commits_created += commits
                except Exception as e:
                    msg = f"{gid}: {type(e).__name__}: {e}"
                    logger.error(msg, exc_info=True)
                    errors.append(msg)
                    console.print(f"    [red]✗ {msg}[/red]")

            state.last_summary_date = current_date
            console.print(
                f"    [dim]{current_date} done in {time.monotonic() - scan_started:.0f}s[/dim]"
            )

    return finalize_daily(
        repo,
        state,
        dates_to_process,
        commits_created,
        errors,
        dry_run=dry_run,
        push=config.git.push,
    )


def _process_version(
    client: RTClient,
    text_parser: RTTextParser,
    meta_parser: RTMetadataParser,
    repo: GitRepo,
    gid: str,
    current_date: date,
    group_to_filename: dict[str, str],
    *,
    dry_run: bool,
) -> int:
    """Fetch one version, resolve its canonical filename, commit it."""
    xml_bytes = client.get_text(gid)
    metadata = meta_parser.parse(xml_bytes, gid)
    blocks = text_parser.parse_text(xml_bytes)

    # Resolve the canonical filename via terviktekstiGrupiID
    extra = dict(metadata.extra)
    group_id = extra.get("group_id", "")
    if group_id and group_id in group_to_filename:
        # Existing law → append as a new reform commit to the same file
        filename_id = group_to_filename[group_id]
        commit_type = CommitType.REFORM
    else:
        # Brand new law → this version becomes the bootstrap of a new file
        filename_id = gid
        commit_type = CommitType.BOOTSTRAP
        if group_id:
            group_to_filename[group_id] = filename_id  # update local map

    canonical_meta = replace(metadata, identifier=filename_id)
    file_path = f"ee/{filename_id}.md"
    markdown = render_norm_at_date(canonical_meta, blocks, current_date, include_all=True)

    if dry_run:
        console.print(f"    [dim]{current_date} {gid} → {file_path} ({commit_type.value})[/dim]")
        return 0

    # Idempotency
    if repo.has_commit_with_source_id(gid, filename_id):
        return 0

    changed = repo.write_and_add(file_path, markdown)
    if not changed and commit_type == CommitType.REFORM:
        # The rendered markdown is identical to what's already in the file.
        # This can happen when the XML was regenerated with no actual changes.
        return 0

    reform = Reform(date=current_date, norm_id=gid, affected_blocks=())
    info = build_commit_info(commit_type, canonical_meta, reform, list(blocks), file_path, markdown)
    sha = repo.commit(info)
    if sha:
        console.print(f"    [green]✓[/green] {gid} — {info.subject}")
        return 1
    return 0


def _build_group_map(ee_dir: Path) -> dict[str, str]:
    """Walk every .md in ``ee/`` and build ``{group_id: canonical_filename_id}``.

    Reads only the YAML frontmatter (first ~2KB) of each file for speed.
    """
    group_map: dict[str, str] = {}
    if not ee_dir.is_dir():
        return group_map
    for md_path in ee_dir.glob("*.md"):
        try:
            with md_path.open("rb") as f:
                # The frontmatter is always the first ~1.5 KB
                head = f.read(4096).decode("utf-8", errors="replace")
        except OSError:
            continue
        m = _GROUP_ID_RE.search(head)
        if m:
            group_map[m.group(1)] = md_path.stem
    return group_map
