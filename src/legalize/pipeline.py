"""Legalize pipeline orchestrator.

Generic (country-agnostic) flows:
- generic_daily: daily incremental update for any country via dispatch
- generic_fetch_one: fetch one norm for any country via dispatch
- generic_fetch_all: fetch all norms for any country via discovery
- generic_bootstrap: full bootstrap for any country
- commit_one: generate commits for one law from local data
- commit_all: generate commits for all laws in data/
- reprocess: re-download and regenerate specific norms
- bootstrap_from_local_xml: bootstrap from local XML (tests/pilot)
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import date
from pathlib import Path

import requests

from rich.console import Console

from legalize.committer.git_ops import FastImporter, GitRepo
from legalize.committer.message import build_commit_info
from legalize.config import Config
from legalize.models import (
    CommitType,
    NormMetadata,
    ParsedNorm,
    Reform,
)
from legalize.state.store import StateStore, resolve_dates_to_process
from legalize.storage import load_norma_from_json, save_structured_json
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath
from legalize.transformer.xml_parser import extract_reforms, parse_text_xml

console = Console()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# GENERIC DAILY — works for any country via dispatch
# ─────────────────────────────────────────────

# Weekday schedule per country (skip these weekdays).
# Defined here so config.yaml stays declarative. Override in country daily.py
# only if the country needs a fully custom flow (ES, FR).
_SKIP_WEEKDAYS: dict[str, set[int]] = {
    "es": {6},  # Mon-Sat (BOE)
    "fr": {6},  # Mon-Sat (DILA)
    "se": {5, 6},  # Mon-Fri (Riksdagen)
    "at": {5, 6},  # Mon-Fri (RIS)
    "pt": {5, 6},  # Mon-Fri (DRE)
    "cl": {6},  # Mon-Sat (BCN)
    "lt": set(),  # Every day
    "de": {5, 6},  # Mon-Fri (GII)
    "uy": {6},  # Mon-Sat (IMPO)
}


def finalize_daily(
    repo: GitRepo,
    state: StateStore,
    dates_to_process: list[date],
    commits_created: int,
    errors: list[str],
    *,
    dry_run: bool = False,
    push: bool = False,
) -> int:
    """Shared tail for all daily pipelines: push, record run, print summary.

    Call this at the end of any daily() function (generic or custom).
    """
    if not dry_run and push and commits_created > 0:
        try:
            repo.push()
        except subprocess.CalledProcessError:
            logger.error("Error pushing", exc_info=True)
            errors.append("Error pushing")

    state.record_run(
        summaries=[d.isoformat() for d in dates_to_process],
        commits=commits_created,
        errors=errors,
    )
    state.save()

    console.print(f"\n[bold green]✓ {commits_created} commits[/bold green]")
    if errors:
        console.print(f"[yellow]⚠ {len(errors)} errors[/yellow]")

    return commits_created


def generic_daily(
    config: Config,
    country: str,
    target_date: date | None = None,
    dry_run: bool = False,
) -> int:
    """Daily incremental update for any country using the standard interfaces.

    Works for countries whose daily flow is: discover → fetch → parse → commit.
    Countries with custom flows (ES: reform resolution, FR: tar.gz increments)
    keep their own daily.py and call finalize_daily() for the shared tail.
    """
    from legalize.countries import (
        get_client_class,
        get_discovery_class,
        get_metadata_parser,
        get_text_parser,
    )

    cc = config.get_country(country)
    state = StateStore(cc.state_path)
    state.load()

    skip = _SKIP_WEEKDAYS.get(country, set())
    dates_to_process = resolve_dates_to_process(
        state,
        cc.repo_path,
        target_date,
        skip_weekdays=skip,
    )
    if dates_to_process is None:
        console.print("[yellow]No last date found. Use --date or run bootstrap.[/yellow]")
        return 0
    if not dates_to_process:
        console.print("[green]Nothing to process — up to date[/green]")
        return 0

    console.print(
        f"[bold]Daily {country.upper()} — processing {len(dates_to_process)} day(s)[/bold]"
    )

    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    commits_created = 0
    errors: list[str] = []

    text_parser = get_text_parser(country)
    meta_parser = get_metadata_parser(country)
    discovery_cls = get_discovery_class(country)
    discovery = discovery_cls.create(cc.source or {})
    client_cls = get_client_class(country)

    with client_cls.create(cc) as client:
        for current_date in dates_to_process:
            console.print(f"\n  [bold]{current_date}[/bold]")

            try:
                modified_ids = list(discovery.discover_daily(client, current_date))
            except Exception:
                msg = f"Error discovering changes for {current_date}"
                logger.error(msg, exc_info=True)
                errors.append(msg)
                continue

            if not modified_ids:
                console.print("    No changes found")
                state.last_summary_date = current_date
                continue

            console.print(f"    {len(modified_ids)} norm(s) modified")

            for norm_id in modified_ids:
                if dry_run:
                    console.print(f"    [dim]{norm_id} — would process[/dim]")
                    continue

                try:
                    meta_data = client.get_metadata(norm_id)
                    metadata = meta_parser.parse(meta_data, norm_id)

                    text_data = client.get_text(norm_id)
                    blocks = text_parser.parse_text(text_data)

                    file_path = norm_to_filepath(metadata)
                    markdown = render_norm_at_date(metadata, blocks, current_date)

                    changed = repo.write_and_add(file_path, markdown)
                    if not changed:
                        console.print(f"    [dim]⏭ {metadata.short_title} — no changes[/dim]")
                        continue

                    reform = Reform(
                        date=current_date,
                        norm_id=f"{country.upper()}-DAILY-{current_date.isoformat()}",
                        affected_blocks=(),
                    )
                    info = build_commit_info(
                        CommitType.REFORM,
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
                    msg = f"Error processing {norm_id}: {e}"
                    logger.error(msg, exc_info=True)
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


# ─────────────────────────────────────────────
# GENERIC FETCH — works for any country via dispatch
# ─────────────────────────────────────────────


def generic_fetch_one(
    config: Config,
    country: str,
    norm_id: str,
    force: bool = False,
) -> ParsedNorm | None:
    """Fetch one norm for any country using countries.py dispatch.

    Uses the country's client, text_parser, and metadata_parser.
    Saves structured JSON to data_dir.
    """
    from legalize.countries import get_client_class, get_metadata_parser, get_text_parser

    cc = config.get_country(country)
    safe_id = norm_id.replace(":", "-").replace("/", "-")
    json_path = Path(cc.data_dir) / "json" / f"{safe_id}.json"

    if json_path.exists() and not force:
        console.print(f"  [dim]{norm_id} already processed, skipping[/dim]")
        return load_norma_from_json(json_path)

    client_cls = get_client_class(country)
    text_parser = get_text_parser(country)
    meta_parser = get_metadata_parser(country)

    with client_cls.create(cc) as client:
        try:
            console.print(f"  Processing [bold]{norm_id}[/bold]...")

            meta_data = client.get_metadata(norm_id)
            metadata = meta_parser.parse(meta_data, norm_id)

            # Pass pre-fetched metadata to avoid redundant API call
            get_text_kwargs = {}
            if hasattr(client, "get_text") and "meta_data" in client.get_text.__code__.co_varnames:
                get_text_kwargs["meta_data"] = meta_data
            text_data = client.get_text(norm_id, **get_text_kwargs)
            blocks = text_parser.parse_text(text_data)
            reforms = _extract_reforms_generic(text_parser, client, norm_id, blocks)

            # Suvestine: replace blocks + reforms with versioned historical data
            if hasattr(text_parser, "parse_suvestine") and hasattr(client, "get_suvestine"):
                try:
                    suvestine_data = client.get_suvestine(norm_id)
                    sv_blocks, sv_reforms = text_parser.parse_suvestine(suvestine_data, norm_id)
                    if sv_reforms:
                        blocks = sv_blocks
                        reforms = sv_reforms
                        console.print(f"    [dim]Suvestine: {len(sv_reforms)} versions[/dim]")
                except Exception:
                    logger.warning(
                        "Suvestine unavailable for %s, using consolidated text",
                        norm_id,
                    )

            norm = ParsedNorm(
                metadata=metadata,
                blocks=tuple(blocks),
                reforms=tuple(reforms),
            )

            save_structured_json(cc.data_dir, norm)

            console.print(
                f"  [green]✓[/green] {metadata.short_title}: "
                f"{len(blocks)} blocks, {len(reforms)} versions"
            )
            return norm

        except (requests.RequestException, ValueError, FileNotFoundError, OSError):
            logger.error("Error processing %s", norm_id, exc_info=True)
            console.print(f"  [red]✗ Error processing {norm_id}[/red]")
            return None


def generic_fetch_all(
    config: Config,
    country: str,
    force: bool = False,
    limit: int | None = None,
) -> list[str]:
    """Fetch all norms for any country using discovery + dispatch.

    Uses NormDiscovery.discover_all() then fetches each norm.
    Supports --limit for testing (fetch only N norms).
    Uses max_workers from config for parallel fetching.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from legalize.countries import get_client_class, get_discovery_class

    cc = config.get_country(country)
    client_cls = get_client_class(country)
    discovery_cls = get_discovery_class(country)

    # Discover all norm IDs (pass data_dir for discovery cache)
    source_with_cache = {**cc.source, "cache_dir": cc.data_dir}
    with client_cls.create(cc) as client:
        discovery = discovery_cls.create(source_with_cache)
        norm_ids = list(discovery.discover_all(client))

    if limit:
        norm_ids = norm_ids[:limit]

    console.print(f"[bold]Fetch — {len(norm_ids)} norms for {country.upper()}[/bold]\n")

    workers = getattr(cc, "max_workers", 1) or 1

    if workers <= 1:
        # Sequential (original behavior)
        fetched = []
        errors = 0
        for i, norm_id in enumerate(norm_ids, 1):
            norm = generic_fetch_one(config, country, norm_id, force=force)
            if norm is not None:
                fetched.append(norm_id)
            else:
                errors += 1
            if i % 50 == 0:
                console.print(
                    f"  [dim][{i}/{len(norm_ids)}] {len(fetched)} OK, {errors} errors[/dim]"
                )
    else:
        # Parallel fetch with N workers
        console.print(f"  [dim]Using {workers} parallel workers[/dim]\n")
        fetched = []
        errors = 0
        done = 0

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(generic_fetch_one, config, country, nid, force): nid for nid in norm_ids
            }
            for future in as_completed(futures):
                done += 1
                try:
                    norm = future.result()
                    if norm is not None:
                        fetched.append(futures[future])
                    else:
                        errors += 1
                except Exception:
                    errors += 1
                if done % 50 == 0:
                    console.print(
                        f"  [dim][{done}/{len(norm_ids)}] {len(fetched)} OK, {errors} errors[/dim]"
                    )

    console.print(f"\n[bold green]✓ {len(fetched)} norms fetched[/bold green]")
    if errors:
        console.print(f"[yellow]⚠ {errors} errors[/yellow]")

    return fetched


def generic_bootstrap(
    config: Config,
    country: str,
    dry_run: bool = False,
    limit: int | None = None,
) -> int:
    """Full bootstrap for any country: discover + fetch + commit.

    Countries with a non-standard history model (e.g. Estonia, which
    reconstructs the timeline by walking an ``Eelmine`` HTML chain rather
    than by extracting reforms from the XML body) can provide a custom
    ``fetcher/{country}/bootstrap.py`` module exposing a ``bootstrap()``
    function. If present, it is called instead of the standard flow.
    """
    # Country-specific hook
    try:
        from importlib import import_module

        custom = import_module(f"legalize.fetcher.{country}.bootstrap")
    except ImportError:
        custom = None

    if custom is not None and hasattr(custom, "bootstrap"):
        return custom.bootstrap(config, dry_run=dry_run, limit=limit)

    cc = config.get_country(country)

    console.print(f"[bold]Bootstrap {country.upper()}[/bold]\n")
    console.print(f"  Data dir: {cc.data_dir}")
    console.print(f"  Repo output: {cc.repo_path}\n")

    fetched = generic_fetch_all(config, country, force=False, limit=limit)
    if not fetched:
        console.print("[yellow]No norms found.[/yellow]")
        return 0

    console.print("\n[bold]Commit — generating git history[/bold]\n")
    # Use fast-import for bootstrap: 10-50x faster than commit_all() and,
    # critically, sorts commits by publication date so the resulting git
    # history is chronological. The slow commit_all() walks json files in
    # filename order, which for countries with mixed pre/post-1970 laws
    # leaves clamped 1970-01-02 commits at HEAD and breaks downstream
    # incremental sync (committer-date filter returns 0).
    total_commits = commit_all_fast(config, country, dry_run=dry_run)

    write_country_meta(config, country)

    console.print(f"\n[bold green]✓ Bootstrap {country.upper()} completed[/bold green]")
    console.print(f"  {len(fetched)} norms fetched, {total_commits} commits created")

    return total_commits


def _extract_reforms_generic(text_parser, client, norm_id, blocks):
    """Extract reforms, with country-specific hooks.

    Swedish parser has extract_reforms_from_sfsr for the SFSR amendment register.
    Falls back to generic extract_reforms() from blocks.
    """
    if hasattr(text_parser, "extract_reforms_from_sfsr") and hasattr(
        client, "get_amendment_register"
    ):
        try:
            sfsr_html = client.get_amendment_register(norm_id)
            return text_parser.extract_reforms_from_sfsr(sfsr_html)
        except Exception:
            logger.warning(
                "Amendment register unavailable for %s, using text-based reforms",
                norm_id,
            )
    return extract_reforms(blocks)


# ─────────────────────────────────────────────
# COMMIT — generate git commits from local data/
# ─────────────────────────────────────────────


def commit_one(config: Config, country: str, norm_id: str, dry_run: bool = False) -> int:
    """Generate commits for ONE law from its JSON in data/.

    Does not download anything. Reads data/json/{norm_id}.json.
    Commits for this law are added to the repo without touching other laws.

    Returns number of commits created.
    """
    cc = config.get_country(country)
    json_path = Path(cc.data_dir) / "json" / f"{norm_id}.json"
    if not json_path.exists():
        console.print(f"  [red]{json_path} does not exist. Run fetch first.[/red]")
        return 0

    norm = load_norma_from_json(json_path)
    metadata = norm.metadata
    blocks = norm.blocks
    reforms = norm.reforms

    logger.info("Committing %s: %d reforms", norm_id, len(reforms))
    console.print(
        f"  [bold]{metadata.short_title}[/bold]: {len(blocks)} blocks, {len(reforms)} versions"
    )

    if dry_run:
        for reform in reforms:
            is_first = reform == reforms[0]
            label = "bootstrap" if is_first else "reform"
            console.print(f"    [dim]{reform.date} [{label}][/dim]")
        return 0

    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    repo.init()

    commits_created = 0
    file_path = norm_to_filepath(metadata)

    for reform in reforms:
        # Idempotency check: Source-Id + Norm-Id (a single Source-Id can be both its own norm AND a reform of another)
        if repo.has_commit_with_source_id(reform.norm_id, metadata.identifier):
            continue

        is_first = reform == reforms[0]
        commit_type = CommitType.BOOTSTRAP if is_first else CommitType.REFORM

        markdown = render_norm_at_date(metadata, blocks, reform.date, include_all=is_first)
        changed = repo.write_and_add(file_path, markdown)

        if not changed and not is_first:
            continue

        info = build_commit_info(commit_type, metadata, reform, blocks, file_path, markdown)
        sha = repo.commit(info)

        if sha:
            commits_created += 1
            console.print(f"    [green]✓[/green] {reform.date} — {info.subject}")

    return commits_created


def commit_all(
    config: Config,
    country: str,
    dry_run: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> int:
    """Generate commits for ALL laws in data/json/.

    Processes each law independently — does not interleave commits.
    Supports --limit and --offset for batching large bootstraps.
    """
    cc = config.get_country(country)
    json_dir = Path(cc.data_dir) / "json"
    if not json_dir.exists():
        console.print("[red]No data in data/json/. Run fetch first.[/red]")
        return 0

    json_files = sorted(json_dir.glob("*.json"))
    total_available = len(json_files)
    json_files = json_files[offset:]
    if limit:
        json_files = json_files[:limit]
    if offset or limit:
        console.print(
            f"[bold]Commit — {len(json_files)} laws "
            f"(of {total_available}, offset={offset})[/bold]\n"
        )
    else:
        console.print(f"[bold]Commit — generating commits for {len(json_files)} laws[/bold]\n")

    state = StateStore(cc.state_path)
    state.load()

    total = 0
    errors = 0
    for i, json_file in enumerate(json_files, 1):
        norm_id = json_file.stem
        try:
            commits = commit_one(config, country, norm_id, dry_run=dry_run)
            total += commits
        except (OSError, ValueError, subprocess.CalledProcessError):
            errors += 1
            logger.error("Error committing %s, continuing", norm_id, exc_info=True)
            console.print(f"  [red]✗ {norm_id} — error, continuing[/red]")

        # Save state periodically (every 50 laws)
        if not dry_run and i % 50 == 0:
            state.record_run(commits=total)
            state.save()
            console.print(f"  [dim][{i}/{len(json_files)}] {total} commits, {errors} errors[/dim]")

    if not dry_run:
        state.record_run(commits=total)
        state.save()

    console.print(f"\n[bold green]✓ {total} commits created[/bold green]")

    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    log_output = repo.log()
    if log_output and not dry_run:
        lines = log_output.strip().splitlines()
        console.print(f"\n[bold]Git log ({len(lines)} commits):[/bold]")
        for line in lines[-10:]:
            console.print(f"  {line}")
        if len(lines) > 10:
            console.print(f"  ... ({len(lines) - 10} more)")

    return total


# ─────────────────────────────────────────────
# FAST COMMIT — git fast-import for bulk bootstrap
# ─────────────────────────────────────────────


def commit_all_fast(
    config: Config,
    country: str,
    limit: int | None = None,
    offset: int = 0,
    dry_run: bool = False,
) -> int:
    """Generate commits for ALL laws using git fast-import.

    10-50x faster than commit_all() for bootstrap. Generates a single
    fast-import stream with all commits in chronological order.

    Does NOT support idempotency (skipping existing commits) — use only
    for fresh bootstrap on an empty repo.
    """
    cc = config.get_country(country)
    json_dir = Path(cc.data_dir) / "json"
    if not json_dir.exists():
        console.print("[red]No data in data/json/. Run fetch first.[/red]")
        return 0

    json_files = sorted(json_dir.glob("*.json"))
    total_available = len(json_files)
    json_files = json_files[offset:]
    if limit:
        json_files = json_files[:limit]

    console.print(
        f"[bold]Fast commit — {len(json_files)} laws "
        f"(of {total_available}) for {country.upper()}[/bold]\n"
    )

    # Collect all (date, norm_id, reform_index, json_file) tuples, then sort by date
    # so the git history is chronological across all laws.
    all_reforms: list[tuple[date, str, int, Path]] = []

    for json_file in json_files:
        try:
            norm = load_norma_from_json(json_file)
        except (OSError, ValueError):
            logger.error("Error loading %s, skipping", json_file, exc_info=True)
            continue

        for i, reform in enumerate(norm.reforms):
            all_reforms.append((reform.date, json_file.stem, i, json_file))

    all_reforms.sort(key=lambda x: x[0])

    console.print(f"  {len(all_reforms)} total commits to generate (sorted by date)\n")

    if dry_run:
        console.print("[yellow]dry-run: skipping fast-import[/yellow]")
        return len(all_reforms)

    # Cache loaded norms to avoid re-reading JSON
    norm_cache: dict[str, ParsedNorm] = {}
    errors = 0

    with FastImporter(cc.repo_path, config.git.committer_name, config.git.committer_email) as fi:
        for idx, (reform_date, norm_id, reform_idx, json_file) in enumerate(all_reforms):
            try:
                if norm_id not in norm_cache:
                    norm_cache[norm_id] = load_norma_from_json(json_file)

                norm = norm_cache[norm_id]
                metadata = norm.metadata
                blocks = norm.blocks
                reform = norm.reforms[reform_idx]

                is_first = reform_idx == 0
                commit_type = CommitType.BOOTSTRAP if is_first else CommitType.REFORM

                markdown = render_norm_at_date(metadata, blocks, reform.date, include_all=is_first)
                file_path = norm_to_filepath(metadata)

                info = build_commit_info(commit_type, metadata, reform, blocks, file_path, markdown)
                fi.commit(file_path, markdown, info)

            except Exception:
                errors += 1
                logger.error("Error processing %s reform %d", norm_id, reform_idx, exc_info=True)

            if (idx + 1) % 5000 == 0:
                console.print(
                    f"  [dim][{idx + 1}/{len(all_reforms)}] queued, {errors} errors[/dim]"
                )

            # Free norm from cache once all its reforms are queued
            if norm_id in norm_cache:
                remaining = sum(1 for _, nid, _, _ in all_reforms[idx + 1 :] if nid == norm_id)
                if remaining == 0:
                    del norm_cache[norm_id]

    console.print(f"\n[bold green]✓ {fi.commit_count} commits created (fast-import)[/bold green]")
    if errors:
        console.print(f"[yellow]⚠ {errors} errors[/yellow]")

    return fi.commit_count


# ─────────────────────────────────────────────
# REPROCESS — re-download and regenerate norms
# ─────────────────────────────────────────────


def reprocess(
    config: Config,
    country: str,
    norm_ids: list[str],
    reason: str,
    dry_run: bool = False,
) -> int:
    """Re-download and regenerate specific norms."""
    console.print(f"[bold]Reprocess — {reason}[/bold]\n")
    commits = 0
    for norm_id in norm_ids:
        generic_fetch_one(config, country, norm_id, force=True)
        commits += commit_one(config, country, norm_id, dry_run=dry_run)
    return commits


# ─────────────────────────────────────────────
# BOOTSTRAP FROM LOCAL XML — used by tests/pilot
# ─────────────────────────────────────────────


def bootstrap_from_local_xml(
    config: Config,
    metadata: NormMetadata,
    xml_path: str | Path,
    country: str = "es",
    dry_run: bool = False,
) -> int:
    """Bootstrap from a local XML (pilot/tests)."""
    cc = config.get_country(country)
    xml_bytes = Path(xml_path).read_bytes()
    blocks = parse_text_xml(xml_bytes)
    reforms = extract_reforms(blocks)

    norm = ParsedNorm(
        metadata=metadata,
        blocks=tuple(blocks),
        reforms=tuple(reforms),
    )

    save_structured_json(cc.data_dir, norm)

    return commit_one(config, country, metadata.identifier, dry_run=dry_run)


# ─────────────────────────────────────────────
# COUNTRY META — metadata for web/seed tooling
# ─────────────────────────────────────────────


def write_country_meta(config: Config, country: str) -> None:
    """Write country_meta.yaml alongside the JSON data.

    This file helps downstream tooling auto-detect countries
    and suggest configuration for new ones.
    """
    import yaml

    cc = config.get_country(country)
    json_dir = Path(cc.data_dir) / "json"
    if not json_dir.exists():
        return

    json_files = list(json_dir.glob("*.json"))
    if not json_files:
        return

    # Discover ranks from the actual data (sample first 200 files)
    ranks_found: set[str] = set()
    for jf in json_files[:200]:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
            rank = data.get("metadata", {}).get("rank", "")
            if rank:
                ranks_found.add(rank)
        except (json.JSONDecodeError, OSError):
            continue

    meta = {
        "code": country,
        "law_count": len(json_files),
        "ranks_found": sorted(ranks_found),
        "last_updated": date.today().isoformat(),
    }

    meta_path = Path(cc.data_dir) / "country_meta.yaml"
    with open(meta_path, "w", encoding="utf-8") as f:
        yaml.dump(meta, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    console.print(f"  [dim]Wrote {meta_path}[/dim]")
