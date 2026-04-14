"""Slovakia bootstrap with full version history.

The Slov-Lex static portal provides point-in-time access to every law
version via the history page + .portal endpoint. This bootstrap:

  1. Discovers all laws via the API gateway catalog (paginated JSON).
  2. For each law (parallelized), fetches the version history page,
     then downloads all version texts as HTML portal fragments.
     Saves to data-sk/json/{id}.json. **Skips laws already on disk.**
  3. Reads JSON files from disk, commits versions sequentially (oldest
     first per law) with GIT_AUTHOR_DATE = effective date.

Phases 1+2 are resumable: if the process crashes, rerunning skips
already-fetched laws. Phase 3 is also crash-safe.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import requests
from rich.console import Console

from legalize.committer.git_ops import GitRepo
from legalize.committer.message import build_commit_info
from legalize.config import Config
from legalize.fetcher.sk.client import SlovLexClient
from legalize.fetcher.sk.parser import (
    SlovLexMetadataParser,
    SlovLexTextParser,
    parse_version_history,
)
from legalize.models import CommitType, NormMetadata, Reform
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath

console = Console()
logger = logging.getLogger(__name__)


def bootstrap(
    config: Config,
    dry_run: bool = False,
    limit: int | None = None,
    workers: int | None = None,
) -> int:
    """SK bootstrap: discover → parallel fetch to disk → sequential commits."""
    cc = config.get_country("sk")
    if workers is None:
        workers = getattr(cc, "max_workers", 4) or 4

    json_dir = Path(cc.data_dir) / "json"
    json_dir.mkdir(parents=True, exist_ok=True)

    console.print("[bold]Bootstrap SK — Slov-Lex with version history[/bold]\n")
    console.print(f"  Repo: {cc.repo_path}")
    console.print(f"  Data: {json_dir}")
    console.print(f"  Workers: {workers}\n")

    # ── Phase 1: Discovery ──
    console.print("[bold]Phase 1: Discovery (API catalog)[/bold]")
    disc_start = time.monotonic()
    all_ids = _discover(cc, limit=limit)
    console.print(f"  Found {len(all_ids)} laws in {time.monotonic() - disc_start:.0f}s\n")

    if not all_ids:
        return 0

    # ── Phase 2: Fetch to disk (resumable) ──
    already = sum(1 for nid in all_ids if _json_path(json_dir, nid).exists())
    to_fetch = len(all_ids) - already
    console.print(
        f"[bold]Phase 2: Fetch versions ({workers} workers)[/bold]\n"
        f"  {already} already on disk, {to_fetch} to fetch"
    )

    fetch_start = time.monotonic()
    errors = 0
    fetched = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_and_save, cc, json_dir, nid): nid
            for nid in all_ids
            if not _json_path(json_dir, nid).exists()
        }

        for future in as_completed(futures):
            try:
                ok = future.result()
                if ok:
                    fetched += 1
                else:
                    errors += 1
            except Exception as e:
                errors += 1
                logger.error("Fetch error: %s", e)

            done = fetched + errors
            if done % 100 == 0:
                elapsed = time.monotonic() - fetch_start
                rate = done / elapsed if elapsed > 0 else 0
                console.print(f"  {done}/{to_fetch} ({rate:.1f}/s), {errors} errors")

    console.print(
        f"\n  Fetched {fetched} laws in {time.monotonic() - fetch_start:.0f}s ({errors} errors)\n"
    )

    if dry_run:
        console.print("[yellow]Dry run — no commits created[/yellow]")
        return 0

    # ── Phase 3: Commit from disk ──
    console.print("[bold]Phase 3: Commit versions from disk[/bold]")
    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    total_commits = 0

    json_files = sorted(json_dir.glob("*.json"))
    for i, jf in enumerate(json_files, 1):
        try:
            commits = _commit_from_json(repo, jf)
            total_commits += commits
        except Exception as e:
            logger.error("Commit error for %s: %s", jf.name, e)

        if i % 500 == 0:
            console.print(f"  {i}/{len(json_files)} files, {total_commits} commits")

    console.print(
        f"\n[bold green]Bootstrap SK complete[/bold green]\n"
        f"  {len(json_files)} laws, {total_commits} commits"
    )
    return total_commits


# ─────────────────────────────────────────────
# Phase 1: Discovery
# ─────────────────────────────────────────────


def _discover(cc, limit: int | None = None) -> list[str]:
    """Discover all law IDs from the API catalog."""
    from legalize.fetcher.sk.discovery import SlovLexDiscovery

    all_ids: list[str] = []
    with SlovLexClient.create(cc) as client:
        discovery = SlovLexDiscovery()
        for norm_id in discovery.discover_all(client):
            all_ids.append(norm_id)
            if limit and len(all_ids) >= limit:
                break

    return all_ids


# ─────────────────────────────────────────────
# Phase 2: Fetch + save to disk
# ─────────────────────────────────────────────


def _json_path(json_dir: Path, norm_id: str) -> Path:
    """Get the JSON file path for a law. norm_id is "year/number"."""
    safe = norm_id.replace("/", "-")
    return json_dir / f"{safe}.json"


def _fetch_and_save(cc, json_dir: Path, norm_id: str) -> bool:
    """Fetch all versions of a law and save to JSON file."""
    meta_parser = SlovLexMetadataParser()
    text_parser = SlovLexTextParser()
    year, number = norm_id.split("/", 1)

    with SlovLexClient.create(cc) as client:
        # Fetch metadata from API catalog
        try:
            meta_bytes = client.get_metadata(norm_id)
            metadata = meta_parser.parse(meta_bytes, norm_id)
        except Exception as e:
            logger.warning("Metadata error for %s: %s", norm_id, e)
            return False

        # Fetch version history page
        try:
            history_bytes = client.get_version_history(year, number)
        except Exception as e:
            logger.warning("History page error for %s: %s", norm_id, e)
            return False

        # Parse version history
        versions_info = parse_version_history(history_bytes)
        if not versions_info:
            logger.debug("No versions found for %s", norm_id)
            return False

        # Fetch + render each version
        file_path = norm_to_filepath(metadata)
        versions: list[dict] = []

        for v in versions_info:
            # Skip the proclaimed text (vyhlasene_znenie) — it's the
            # original text before the first consolidation, and its
            # portal URL often 404s for older laws.
            if v["is_proclaimed"]:
                continue

            date_suffix = v["date_suffix"]
            effective_from = v["effective_from"]

            if not effective_from or not date_suffix:
                continue

            try:
                text_bytes = client.get_text_at_version(year, number, date_suffix)
                blocks = text_parser.parse_text(text_bytes)
                md = render_norm_at_date(metadata, blocks, effective_from)
                versions.append(
                    {
                        "date": effective_from.isoformat(),
                        "source": v["amendment"] or "original",
                        "markdown": md,
                    }
                )
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else 0
                if status in (404, 403):
                    logger.debug("Version %s/%s at %s not available", year, number, date_suffix)
                else:
                    logger.warning("HTTP error for %s/%s at %s: %s", year, number, date_suffix, e)
            except Exception as e:
                logger.warning("Error processing %s/%s at %s: %s", year, number, date_suffix, e)

    if not versions:
        return False

    record = {
        "norm_id": norm_id,
        "identifier": metadata.identifier,
        "title": metadata.title,
        "short_title": metadata.short_title,
        "file_path": file_path,
        "versions": versions,
    }
    out = _json_path(json_dir, norm_id)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


# ─────────────────────────────────────────────
# Phase 3: Commit from JSON files on disk
# ─────────────────────────────────────────────


def _commit_from_json(repo: GitRepo, json_file: Path) -> int:
    """Read a saved law JSON and create git commits for all versions."""
    record = json.loads(json_file.read_text(encoding="utf-8"))
    file_path = record["file_path"]
    versions = record.get("versions", [])

    if not versions or not file_path:
        return 0

    commits = 0
    for i, v in enumerate(versions):
        md = v["markdown"]
        v_date = date.fromisoformat(v["date"])
        source = v["source"]

        changed = repo.write_and_add(file_path, md)
        if not changed:
            continue

        commit_type = CommitType.BOOTSTRAP if i == 0 else CommitType.REFORM
        reform = Reform(date=v_date, norm_id=source, affected_blocks=())

        metadata = NormMetadata(
            title=record.get("title", ""),
            short_title=record.get("short_title", ""),
            identifier=record.get("identifier", ""),
            country="sk",
            rank="unknown",
            publication_date=v_date,
            status="unknown",
            department="",
            source="",
        )

        info = build_commit_info(commit_type, metadata, reform, [], file_path, md)
        try:
            sha = repo.commit(info)
            if sha:
                commits += 1
        except subprocess.CalledProcessError:
            logger.debug("Commit skipped for %s (nothing to commit)", file_path)

    return commits
