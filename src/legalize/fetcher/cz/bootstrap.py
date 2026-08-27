"""Czech Republic bootstrap with full version history.

The e-Sbírka API provides point-in-time access to every law version:
each version is accessible by appending the effective date to the
staleUrl (/sb/{year}/{number}/{date}). This bootstrap:

  1. Discovers all laws via parallel year probing.
  2. For each law (parallelized), fetches metadata + all version texts,
     saves to data-cz/json/{id}.json. **Skips laws already on disk.**
  3. Reads JSON files from disk, commits versions sequentially (oldest
     first per law) with GIT_AUTHOR_DATE = effective date.

Phases 1+2 are resumable: if the process crashes, rerunning skips
already-fetched laws. Phase 3 is also crash-safe: write_and_add
detects unchanged files.

This module is discovered automatically by
:func:`legalize.pipeline.generic_bootstrap` via the optional
``fetcher/{country}/bootstrap.py`` hook.
"""

from __future__ import annotations

import json
import logging
import re
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
from legalize.fetcher.cz.client import ESbirkaClient
from legalize.fetcher.cz.parser import ESbirkaMetadataParser, ESbirkaTextParser
from legalize.models import CommitType, NormMetadata, Reform
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath

console = Console()
logger = logging.getLogger(__name__)

_AMENDMENT_RE = re.compile(r"č\.\s*(\d+)/(\d+)\s*Sb\.")
_MIN_YEAR = 1945
_MAX_LAW_NUMBER = 800


def bootstrap(
    config: Config,
    dry_run: bool = False,
    limit: int | None = None,
    workers: int | None = None,
) -> int:
    """CZ bootstrap: discover → parallel fetch to disk → sequential commits."""
    cc = config.get_country("cz")
    if workers is None:
        workers = getattr(cc, "max_workers", 4) or 4

    # Not data_dir/json/ — that is the generic pipeline's own store, and these
    # per-version records have a different shape. `legalize commit` reads it and
    # would abort on the first file.
    json_dir = Path(cc.data_dir) / "versions"
    json_dir.mkdir(parents=True, exist_ok=True)

    console.print("[bold]Bootstrap CZ — e-Sbírka with version history[/bold]\n")
    console.print(f"  Repo: {cc.repo_path}")
    console.print(f"  Data: {json_dir}")
    console.print(f"  Workers: {workers}\n")

    # ── Phase 1: Discovery ──
    console.print("[bold]Phase 1: Discovery (parallel by year)[/bold]")
    disc_start = time.monotonic()
    all_ids = _discover_parallel(cc, workers=workers, limit=limit)
    console.print(f"  Found {len(all_ids)} laws in {time.monotonic() - disc_start:.0f}s\n")

    if not all_ids:
        return 0

    # ── Phase 2: Fetch to disk (resumable) ──
    already = sum(1 for sid in all_ids if _json_path(json_dir, sid).exists())
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
            pool.submit(_fetch_and_save, cc, json_dir, sid): sid
            for sid in all_ids
            if not _json_path(json_dir, sid).exists()
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
        f"\n[bold green]✓ Bootstrap CZ complete[/bold green]\n"
        f"  {len(json_files)} laws, {total_commits} commits"
    )
    return total_commits


# ─────────────────────────────────────────────
# Phase 1: Parallel discovery
# ─────────────────────────────────────────────


def _discover_year(cc, year: int) -> list[str]:
    """Probe all law numbers for a single year."""
    found: list[str] = []
    consecutive_misses = 0

    with ESbirkaClient.create(cc) as client:
        for n in range(1, _MAX_LAW_NUMBER + 1):
            stale_url = f"/sb/{year}/{n}"
            try:
                client.get_metadata(stale_url)
                consecutive_misses = 0
                found.append(stale_url)
            except requests.HTTPError:
                consecutive_misses += 1
                if consecutive_misses >= 5:
                    break

    return found


def _discover_parallel(cc, workers: int = 4, limit: int | None = None) -> list[str]:
    """Discover all laws by probing years in parallel."""
    current_year = date.today().year
    years = list(range(current_year, _MIN_YEAR - 1, -1))
    all_ids: list[str] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_discover_year, cc, y): y for y in years}

        for future in as_completed(futures):
            year = futures[future]
            try:
                ids = future.result()
                all_ids.extend(ids)
                if ids:
                    console.print(f"  {year}: {len(ids)} laws (total: {len(all_ids)})")
            except Exception as e:
                logger.error("Discovery error for %d: %s", year, e)

            if limit and len(all_ids) >= limit:
                for f in futures:
                    f.cancel()
                all_ids = all_ids[:limit]
                break

    return all_ids


# ─────────────────────────────────────────────
# Phase 2: Fetch + save to disk
# ─────────────────────────────────────────────


def _json_path(json_dir: Path, stale_url: str) -> Path:
    """Get the JSON file path for a law."""
    safe = stale_url.strip("/").replace("/", "-")
    return json_dir / f"{safe}.json"


def _fetch_and_save(cc, json_dir: Path, stale_url: str) -> bool:
    """Fetch all versions of a law and save to JSON file."""
    meta_parser = ESbirkaMetadataParser()
    text_parser = ESbirkaTextParser()

    with ESbirkaClient.create(cc) as client:
        try:
            meta_bytes = client.get_metadata(stale_url)
            metadata = meta_parser.parse(meta_bytes, stale_url)
            meta_json = json.loads(meta_bytes)
        except Exception as e:
            logger.warning("Metadata error for %s: %s", stale_url, e)
            return False

        # Build version timeline
        timeline = _build_version_timeline(client, meta_json, stale_url)

        # Fetch + render each version
        versions = []
        for v_date, source in timeline:
            try:
                text_bytes = client.get_text(f"{stale_url}/{v_date.isoformat()}")
                blocks = text_parser.parse_text(text_bytes)
                md = render_norm_at_date(metadata, blocks, v_date)
                versions.append(
                    {
                        "date": v_date.isoformat(),
                        "source": source,
                        "markdown": md,
                    }
                )
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code in (400, 404):
                    logger.debug("Version %s at %s not available", stale_url, v_date)
                else:
                    logger.warning("Error fetching %s at %s: %s", stale_url, v_date, e)
            except Exception as e:
                logger.warning("Error processing %s at %s: %s", stale_url, v_date, e)

    if not versions:
        return False

    # Save to disk
    record = {
        "stale_url": stale_url,
        "identifier": metadata.identifier,
        "title": metadata.title,
        "short_title": metadata.short_title,
        "file_path": norm_to_filepath(metadata),
        "versions": versions,
    }
    out = _json_path(json_dir, stale_url)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def _build_version_timeline(
    client: ESbirkaClient,
    meta: dict,
    stale_url: str,
) -> list[tuple[date, str]]:
    """Build chronological list of (effective_date, source) for all versions."""
    original_date_str = meta.get("datumUcinnostiOd", "")
    if not original_date_str:
        return []

    original_date = date.fromisoformat(original_date_str[:10])
    timeline: list[tuple[date, str]] = [(original_date, "original")]

    citation = meta.get("uplnaCitaceSNovelami", "")
    amendments = _AMENDMENT_RE.findall(citation)

    for num, year in amendments:
        if f"/{year}/{num}" in stale_url:
            continue
        try:
            amend_bytes = client.get_metadata(f"/sb/{year}/{num}")
            amend_meta = json.loads(amend_bytes)
            eff_date_str = amend_meta.get("datumUcinnostiOd", "")
            if eff_date_str:
                eff_date = date.fromisoformat(eff_date_str[:10])
                timeline.append((eff_date, f"{num}/{year} Sb."))
        except Exception:
            logger.debug("Could not fetch amendment %s/%s metadata", num, year)

    timeline.sort(key=lambda x: x[0])
    seen: set[date] = set()
    unique: list[tuple[date, str]] = []
    for d, s in timeline:
        if d not in seen:
            seen.add(d)
            unique.append((d, s))

    return unique


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

        # Minimal metadata for commit message
        metadata = NormMetadata(
            title=record.get("title", ""),
            short_title=record.get("short_title", ""),
            identifier=record.get("identifier", ""),
            country="cz",
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
