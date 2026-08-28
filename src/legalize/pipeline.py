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
import os
import re
import subprocess
import sys
import threading
import time
from collections import Counter
from dataclasses import replace
from datetime import date
from pathlib import Path

import requests

from rich.console import Console

from legalize.committer.git_ops import FastImportDied, FastImporter, GitRepo
from legalize.committer.message import build_commit_info
from legalize.config import Config
from legalize.models import (
    CommitInfo,
    CommitType,
    NormMetadata,
    ParsedNorm,
    Reform,
    TextState,
)
from legalize.state.store import StateStore, resolve_dates_to_process
from legalize.storage import (
    load_norma_from_json,
    overwritten_identifiers,
    save_structured_json,
)
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath
from legalize.transformer.xml_parser import extract_reforms, parse_text_xml

# Line-buffered on purpose: piped to a log or a tee, block buffering makes the
# progress lines land minutes late and out of order against git's own output,
# which goes to stderr unbuffered. A push log you cannot trust the timing of is
# how a healthy push got read as a hang and killed.
console = Console(soft_wrap=True)
console.file.reconfigure(line_buffering=True)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# GENERIC DAILY — works for any country via dispatch
# ─────────────────────────────────────────────

# Weekday schedule per country (skip these weekdays).
# Defined here so config.yaml stays declarative. The one copy: a country with
# its own daily.py reads this table too, because four of them used to hold a
# hand-rolled duplicate — which made the rows below unreachable for exactly the
# countries that had one, and left ee out of the table altogether.
SKIP_WEEKDAYS: dict[str, set[int]] = {
    "es": {6},  # Mon-Sat (BOE)
    "fr": {6},  # Mon-Sat (DILA)
    "se": {5, 6},  # Mon-Fri (Riksdagen)
    "at": {5, 6},  # Mon-Fri (RIS)
    "pt": {5, 6},  # Mon-Fri (DRE)
    "cl": {6},  # Mon-Sat (BCN)
    "lt": set(),  # Every day
    "de": {5, 6},  # Mon-Fri (GII)
    "uy": {6},  # Mon-Sat (IMPO)
    "be": {5, 6},  # Mon-Fri (Moniteur Belge — consolidations published on business days)
    "ar": {0, 1, 2, 3, 4, 5, 6},  # InfoLEG catalog refreshes monthly; daily runs are no-ops
    "fi": {5, 6},  # Mon-Fri (Finlex updates on business days)
    "ua": {6},  # Mon-Sat (Rada publishes on business days)
    "dk": {5, 6},  # Mon-Fri (Retsinformation harvest API, business days)
    "ee": {5, 6},  # Mon-Fri (Riigi Teataja)
}


class ShadowedLaw(RuntimeError):
    """A law could not be published because another act holds its file name."""


class UnwritableLaw(RuntimeError):
    """A law had data and could not be written into the repo."""


class HistoryMismatch(RuntimeError):
    """The branch holds commits this run cannot continue from."""


class NothingPublished(RuntimeError):
    """The run had errors and published nothing, so it must not exit green."""


# One fast-import session per chunk. The session is the unit of durability: the
# ref only moves when it ends, so a run killed mid-session loses that session and
# nothing before it. Portugal died three times in one evening at 35,000, 10,000
# and 85,000 of 302,333 commits, and each time restarted from zero.
_IMPORT_CHUNK = 25_000


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
    # A refusal means a real act was not published because another one already
    # holds its file name.
    refused = list(getattr(repo, "refused", []))
    for rel_path in refused:
        errors.append(f"{rel_path}: another act already holds this file name, not written")

    if not dry_run and push and commits_created > 0:
        repo.push()

    state.record_run(
        summaries=[d.isoformat() for d in dates_to_process],
        commits=commits_created,
        errors=errors,
    )
    state.save()

    console.print(f"\n[bold green]✓ {commits_created} commits[/bold green]")
    if errors:
        console.print(f"[yellow]⚠ {len(errors)} errors[/yellow]")

    # Everything that could be published is committed, pushed and recorded before
    # this: the day's work is not lost. But a law that exists and cannot be
    # written because another act holds its file name is a defect in the
    # country's identifier rule, and the only way that gets fixed is if the run
    # ends red instead of leaving a line in a log nobody reads.
    if refused:
        raise ShadowedLaw(
            f"{len(refused)} act(s) could not be published — another act already holds "
            f"the same file name: {', '.join(refused[:5])}"
            f"{' …' if len(refused) > 5 else ''}"
        )

    # Same principle, applied to the error list. A source that changes its HTML
    # gives "12 errors, 0 commits" every morning and the leg still goes green,
    # so nobody looks. Errors alongside published laws stay a warning — the day's
    # work landed — but a day that produced only errors has to end red.
    if errors and commits_created == 0:
        raise NothingPublished(
            f"{len(errors)} error(s) and no commits: nothing was published. First: {errors[0]}"
        )

    return commits_created


def _with_last_amendment(metadata: NormMetadata, reform: Reform) -> NormMetadata:
    """Name the amending act on a body that does not change when one lands.

    Only for AS_ENACTED. On a point-in-time norm the amendments *are* the versions,
    so putting one in the frontmatter states the timeline twice and contradicts the
    body. And a parser that already knows the official ID keeps it: reform.norm_id
    is an internal dedupe key on some countries — Portugal's is
    "DRE-133879986@2020-05-17" — while the field is documented as the official ID.
    """
    from legalize.countries import text_state_for

    state = metadata.text_state or text_state_for(metadata.country)
    if state is not TextState.AS_ENACTED or metadata.last_amendment:
        return metadata
    return replace(metadata, last_amendment=reform.norm_id)


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

    skip = SKIP_WEEKDAYS.get(country, set())
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
    pushed = 0  # commits already pushed to the remote (checkpoint tracker)
    errors: list[str] = []

    text_parser = get_text_parser(country)
    meta_parser = get_metadata_parser(country)
    discovery_cls = get_discovery_class(country)
    discovery = discovery_cls.create(cc.source or {})
    client_cls = get_client_class(country)

    with client_cls.create(cc) as client:
        for current_date in dates_to_process:
            console.print(f"\n  [bold]{current_date}[/bold]")
            client.set_as_of(current_date)

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

            # Checkpoint: push after each completed day so a mid-run failure
            # keeps the days already finished. Only push at day boundaries —
            # the next run resumes from the newest Source-Date, so pushing
            # mid-day would make it skip that day's remaining norms.
            if not dry_run and config.git.push and commits_created > pushed:
                try:
                    repo.push()
                    pushed = commits_created
                except Exception:
                    logger.warning(
                        "Checkpoint push failed after %s; commits stay local "
                        "and retry at the next day boundary or finalize",
                        current_date,
                        exc_info=True,
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
    safe_id = norm_id.replace(":", "-").replace("/", "-").replace(" ", "")
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
            reforms = _extract_reforms_generic(text_parser, client, norm_id, blocks, text_data)

            # Suvestine: replace blocks + reforms with versioned historical data.
            # For a suvestine-capable country a fetch/parse failure is a hard
            # skip: falling through to the consolidated text would commit it as
            # a fabricated "original version" (wrong label + date), violating the
            # commit-integrity rule. Skip the norm and log — the next run retries.
            if hasattr(text_parser, "parse_suvestine") and hasattr(client, "get_suvestine"):
                try:
                    suvestine_data = client.get_suvestine(norm_id)
                    # A parser that can take the resolved publication date gets it,
                    # the same way get_text is handed the metadata above. A source
                    # that leaves a version undated is not a law published on some
                    # floor date; it is this law, published when the metadata says.
                    sv_kwargs = {}
                    if "published_on" in text_parser.parse_suvestine.__code__.co_varnames:
                        sv_kwargs["published_on"] = metadata.publication_date
                    sv_blocks, sv_reforms = text_parser.parse_suvestine(
                        suvestine_data, norm_id, **sv_kwargs
                    )
                except Exception:
                    logger.error(
                        "Suvestine fetch/parse failed for %s; skipping norm "
                        "(will retry next run) rather than committing consolidated "
                        "text as a fabricated version",
                        norm_id,
                        exc_info=True,
                    )
                    console.print(f"  [red]✗ Suvestine failed for {norm_id}, skipping[/red]")
                    return None
                if sv_reforms:
                    blocks = sv_blocks
                    reforms = sv_reforms
                    console.print(f"    [dim]Suvestine: {len(sv_reforms)} versions[/dim]")

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


def discover_norm_ids(
    config: Config,
    country: str,
    limit: int | None = None,
    offset: int = 0,
    rediscover: bool = False,
) -> list[str]:
    """Every norm id a country's discovery yields, cached to disk.

    Separate from the fetching so that a country whose surfaces must be fetched
    in a particular order can ask for the list and fetch it in phases, without
    a second copy of the cache handling. Portugal does; see
    ``fetcher/pt/bootstrap.py``.
    """
    from legalize.countries import get_client_class, get_discovery_class

    cc = config.get_country(country)
    cache = Path(cc.data_dir) / "discovery_ids.txt"

    if cache.exists() and not rediscover:
        norm_ids = [line.strip() for line in cache.read_text().splitlines() if line.strip()]
        console.print(f"[dim]Loaded {len(norm_ids)} IDs from discovery cache[/dim]")
    else:
        with get_client_class(country).create(cc) as client:
            discovery = get_discovery_class(country).create({**cc.source, "cache_dir": cc.data_dir})
            norm_ids = list(discovery.discover_all(client))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text("\n".join(norm_ids) + "\n")
        console.print(f"[dim]Saved {len(norm_ids)} IDs to discovery cache[/dim]")

    if offset:
        norm_ids = norm_ids[offset:]
    if limit:
        norm_ids = norm_ids[:limit]
    return norm_ids


def generic_fetch_all(
    config: Config,
    country: str,
    force: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> list[str]:
    """Fetch all norms for any country using discovery + dispatch.

    Uses NormDiscovery.discover_all() then fetches each norm.
    Supports --limit and --offset for splitting across multiple VMs.
    Uses max_workers from config for parallel fetching.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    cc = config.get_country(country)
    norm_ids = discover_norm_ids(config, country, limit=limit, offset=offset, rediscover=force)

    console.print(f"[bold]Fetch — {len(norm_ids)} norms for {country.upper()}[/bold]")
    if offset:
        console.print(
            f"  [dim](offset={offset}, processing IDs {offset}–{offset + len(norm_ids)})[/dim]"
        )
    console.print()

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

    # Two norms claiming one identifier used to be invisible: the second write
    # replaced the first and the law left the corpus without a word. Nothing is
    # lost now, but a suffixed file name is not the name the country's rule
    # promised, so the count belongs on screen next to the errors.
    clashes = overwritten_identifiers()
    if clashes:
        sample = ", ".join(sorted(clashes)[:5])
        console.print(
            f"[yellow]⚠ {len(clashes)} identifier(s) claimed by more than one norm; "
            f"each extra one saved under a suffixed name: {sample}"
            f"{' …' if len(clashes) > 5 else ''}[/yellow]"
        )

    # A discovery that yields nothing, or a source that fails on every norm, used
    # to be a green run with an empty cache behind it — and the bootstrap that
    # follows then reports "No norms found" and exits 0 too. Switzerland goes
    # exactly down this path.
    if not fetched:
        raise NothingPublished(
            f"{country}: {len(norm_ids)} norm(s) discovered and none fetched — "
            f"{errors} error(s). Nothing was written to {cc.data_dir}."
        )

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

    # generic_fetch_all raises NothingPublished when it fetched nothing, which is
    # what "No norms found." used to print before returning 0.
    fetched = generic_fetch_all(config, country, force=False, limit=limit)

    console.print("\n[bold]Commit — generating git history[/bold]\n")
    # Use fast-import for bootstrap: 10-50x faster than commit_all() and,
    # critically, sorts commits by publication date so the resulting git
    # history is chronological. The slow commit_all() walks json files in
    # filename order, which for countries with mixed pre/post-1970 laws
    # leaves clamped 1970-01-02 commits at HEAD and breaks downstream
    # incremental sync (committer-date filter returns 0).
    try:
        total_commits = commit_all_fast(config, country, dry_run=dry_run)
    finally:
        # A repo that is going red still declares its layout: without the
        # manifest there is no way to see whether the paths were the problem.
        write_country_meta(config, country)
        if not dry_run:
            write_repo_meta(config, country)

    console.print(f"\n[bold green]✓ Bootstrap {country.upper()} completed[/bold green]")
    console.print(f"  {len(fetched)} norms fetched, {total_commits} commits created")

    return total_commits


def _extract_reforms_generic(text_parser, client, norm_id, blocks, text_data=None):
    """Extract reforms, with country-specific hooks.

    Priority order:
    1. Swedish SFSR amendment register (extract_reforms_from_sfsr)
    2. Parser-level extract_reforms(text_data) — e.g. UA amendment annotations
    3. Generic block-based extract_reforms(blocks) from transformer
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

    # Argentine hook: reconstruct versions from per-modificatoria text.
    # Adds Versions to existing blocks and returns Reform objects, making AR
    # compatible with the standard fetch → commit_all_fast pipeline.
    if hasattr(client, "reconstruct_reforms"):
        try:
            new_blocks, reforms = client.reconstruct_reforms(norm_id, blocks)
            if reforms:
                blocks.clear()
                blocks.extend(new_blocks)
                return reforms
        except Exception:
            logger.warning(
                "Version reconstruction unavailable for %s, using text-based reforms",
                norm_id,
            )

    # Try parser-level reform extraction from raw text (e.g. UA annotations).
    # `hasattr` was always true — TextParser defines it — and the base
    # implementation parses the text a second time to get the blocks this
    # function was already handed. The 12 countries that do not override it paid
    # for two full parses of every norm, Portugal's 171,740 included.
    from legalize.fetcher.base import TextParser

    own_extract = getattr(type(text_parser), "extract_reforms", None)
    overrides_it = own_extract is not None and own_extract is not TextParser.extract_reforms
    if text_data is not None and overrides_it:
        parser_reforms = text_parser.extract_reforms(text_data)
        if parser_reforms:
            return parser_reforms

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

    # Ensure at least one bootstrap reform so the law gets committed.
    # Some sources (e.g. old Swedish SFS) have no amendment register entries.
    if not reforms and blocks:
        reforms = (
            Reform(
                date=metadata.publication_date,
                norm_id=metadata.identifier,
                affected_blocks=(),
            ),
        )

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

        norm_meta = metadata if is_first else _with_last_amendment(metadata, reform)
        markdown = render_norm_at_date(norm_meta, blocks, reform.date, include_all=is_first)
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

    # Same rule as commit_all_fast: a law with data and no file is data loss, and
    # this is the path the playbook prescribes for every country over ~20K laws
    # (--no-fast and --batch). It counted the failures and printed a green line.
    if errors:
        raise UnwritableLaw(
            f"{errors} law(s) had data and could not be committed — "
            f"{total} commit(s) were created. See the logged tracebacks."
        )

    return total


# ─────────────────────────────────────────────
# FAST COMMIT — git fast-import for bulk bootstrap
# ─────────────────────────────────────────────


def _published(repo_path: str | Path) -> tuple[Counter, set[str]]:
    """What the repo already carries, keyed by version, and the laws it names.

    The key is ``(Source-Id, Norm-Id, Source-Date)`` and it is *counted*, not a
    set. Both halves of that matter and both were learned by getting it wrong:

    * The date has to be in the key. Not every country gives a reform its own
      ``Source-Id`` — where the source publishes no amending act, ``norm_id``
      is the law's own identifier and every version of one law shares the pair.
      Keying on the pair alone then treats a law's second version as already
      published and drops it, which loses history silently. Spain's acts do
      carry their own ids (44,116 distinct pairs over 44,295 commits), so the
      defect is invisible exactly where it is cheapest to miss.
    * Counted, because one law can legitimately carry two reforms on one date,
      and skipping "the key is present" would drop the second forever. Skipping
      *as many as are published* emits the rest.

    The bare ``Norm-Id`` set is the second answer, and it is not redundant: it
    tells a run pointed at the wrong repository from a run continuing its own,
    and it survives a commit that names the law without naming the act.

    One act's change to one law is one commit, and that pair names it — which
    makes it the key for "has this already been published?". Read in a single
    pass and never per reform: walking commits is cheap, and this must not turn
    a bootstrap into one subprocess per law.

    No trees are opened. ``--name-only`` would say which file each commit
    touched and costs a tree diff per commit — 74 minutes on a real corpus
    where the log alone takes seconds — and it is not needed, because the
    trailer names the law.

    Empty sets are the honest answer for a repo that does not exist yet, has no
    branch, or holds nothing: all three mean nothing has been published, and a
    first run then behaves exactly as it always did.
    """
    import subprocess

    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(repo_path),
                "log",
                "--format=%x1e%B",
                "--grep=^Norm-Id: ",
                "refs/heads/main",
            ],
            capture_output=True,
            text=True,
        )
    except OSError:
        return Counter(), set()
    if out.returncode != 0:
        return Counter(), set()

    versions: Counter = Counter()
    norms: set[str] = set()
    for body in out.stdout.split("\x1e"):
        trailers = dict(re.findall(r"^([A-Z][\w-]*): *(.+?)\s*$", body, re.M))
        source, norm = trailers.get("Source-Id"), trailers.get("Norm-Id")
        if norm:
            norms.add(norm)
        if source and norm:
            versions[(source, norm, trailers.get("Source-Date", ""))] += 1
    return versions, norms


def commit_all_fast(
    config: Config,
    country: str,
    limit: int | None = None,
    offset: int = 0,
    dry_run: bool = False,
) -> int:
    """Generate commits for ALL laws using git fast-import.

    10-50x faster than commit_all() for bootstrap. Commits go out in
    chronological order across every law, in chunks of _IMPORT_CHUNK.

    Resumable, and only in the one direction that is safe: a branch holding a
    prefix of this exact stream is continued from where it stops, and a branch
    holding anything else raises HistoryMismatch rather than stacking a second
    history on the first. It still does not skip individual commits — the unit
    is the prefix, not the file.
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

    # What the repo already publishes, by (Source-Id, Norm-Id) — the pair that
    # identifies one act's change to one law, which is what a commit records.
    #
    # ``_resume_index`` below also skips work, but on a different premise: that
    # the branch is a *prefix* of this stream. That holds for a run resuming
    # itself and not for a repo the daily has been extending, where the tip is a
    # ``[new]``/``[reform]`` commit whose (date, Norm-Id) pair still appears in
    # the stream at a low index. It then resumed there and re-emitted everything
    # after it on top of laws that already had their commits. Measured on
    # legalize-es before this guard: 18 ``[bootstrap]`` commits for laws already
    # published, 10 more with an empty diff, ~95 duplicate (Source-Id, Norm-Id)
    # pairs, and 9 laws whose commits stopped being in Source-Date order —
    # spec v0.4 §History, on a repo whose published history was correct.
    #
    # Matching by pair rather than by position makes the run idempotent whatever
    # produced the existing history. It is the check the daily already does per
    # reform (``fetcher/es/daily.py``, ``has_commit_with_source_id``); the
    # bootstrap path simply never had it. ``bootstrap --fresh`` empties the repo
    # first, so a deliberate rebuild sees nothing here and re-emits everything.
    already, published_norms = _published(cc.repo_path)
    skipped = 0
    seen_identifiers: set[str] = set()

    for json_file in json_files:
        try:
            norm = load_norma_from_json(json_file)
        except (OSError, ValueError):
            logger.error("Error loading %s, skipping", json_file, exc_info=True)
            continue

        reforms = norm.reforms
        # Ensure at least one bootstrap reform so the law gets committed.
        if not reforms and norm.blocks:
            reforms = (
                Reform(
                    date=norm.metadata.publication_date,
                    norm_id=norm.metadata.identifier,
                    affected_blocks=(),
                ),
            )

        seen_identifiers.add(norm.metadata.identifier)
        for i, reform in enumerate(reforms):
            key = (reform.norm_id, norm.metadata.identifier, reform.date.isoformat())
            if already[key] > 0:
                already[key] -= 1
                skipped += 1
                continue
            all_reforms.append((reform.date, json_file.stem, i, json_file))

    all_reforms.sort(key=lambda x: x[0])

    # Stacking a second history on an unrelated first is the failure this
    # guards, and it is the one thing the pair filter cannot see: a repo full of
    # someone else's laws shares no pair with this stream, which looks exactly
    # like an empty repo. Overlap of laws is the signal, checked only on a full
    # scan — with --limit or --offset the run deliberately sees a slice, and a
    # slice that happens to miss every published law is not a wrong repository.
    if (
        limit is None
        and offset == 0
        and published_norms
        and not (published_norms & seen_identifiers)
    ):
        raise HistoryMismatch(
            f"refs/heads/main holds {len(published_norms)} law(s), none of which this run "
            f"would build (e.g. {sorted(published_norms)[0]}). Committing on top would "
            f"stack a second history on the first. Start from an empty repo "
            f"(`bootstrap --fresh`) or point --repo-path somewhere else."
        )

    if skipped:
        console.print(
            f"  [dim]{skipped} reform(s) already committed in this repo — skipped. "
            f"Use `bootstrap --fresh` to rebuild them.[/dim]"
        )
    console.print(f"  {len(all_reforms)} total commits to generate (sorted by date)\n")

    if dry_run:
        console.print("[yellow]dry-run: skipping fast-import[/yellow]")
        return len(all_reforms)

    # Cache loaded norms to avoid re-reading JSON, and drop each one the moment its
    # last reform has been queued. Where that last one is has to be worked out up
    # front: scanning the remaining list per iteration is quadratic, which is free at
    # a thousand reforms and about nine minutes of pure waste at Portugal's 230,000.
    norm_cache: dict[str, ParsedNorm] = {}
    last_reform_index = {norm_id: idx for idx, (_, norm_id, _, _) in enumerate(all_reforms)}
    errors = 0
    # The commits this run skipped are part of the history it produced, so the
    # count it returns is the whole thing and not the increment — a resumed run
    # and a fresh one report the same corpus.
    imported = skipped

    # One import is one all-or-nothing session: fast-import moves the ref when its
    # stdin closes, so a run killed before that leaves an empty branch however far
    # it got. Chunking makes the ref advance every _IMPORT_CHUNK commits, so a
    # death costs the current chunk instead of the whole history — and the next
    # run picks up from there because the pair filter above has already dropped
    # everything the finished chunks wrote. The stream stays chronological
    # because the chunks are slices of the already-sorted list, not of the laws.
    for chunk_start in range(0, len(all_reforms), _IMPORT_CHUNK):
        chunk_end = min(chunk_start + _IMPORT_CHUNK, len(all_reforms))
        with FastImporter(
            cc.repo_path,
            config.git.committer_name,
            config.git.committer_email,
            checkout=chunk_end == len(all_reforms),
        ) as fi:
            for idx in range(chunk_start, chunk_end):
                reform_date, norm_id, reform_idx, json_file = all_reforms[idx]
                try:
                    if norm_id not in norm_cache:
                        loaded = load_norma_from_json(json_file)
                        r = loaded.reforms
                        if not r and loaded.blocks:
                            r = (
                                Reform(
                                    date=loaded.metadata.publication_date,
                                    norm_id=loaded.metadata.identifier,
                                    affected_blocks=(),
                                ),
                            )
                        norm_cache[norm_id] = (loaded, r)

                    norm, reforms_cached = norm_cache[norm_id]
                    metadata = norm.metadata
                    blocks = norm.blocks
                    reform = reforms_cached[reform_idx]

                    is_first = reform_idx == 0
                    commit_type = CommitType.BOOTSTRAP if is_first else CommitType.REFORM

                    norm_meta = metadata if is_first else _with_last_amendment(metadata, reform)
                    markdown = render_norm_at_date(
                        norm_meta, blocks, reform.date, include_all=is_first
                    )
                    file_path = norm_to_filepath(metadata)

                    info = build_commit_info(
                        commit_type, metadata, reform, blocks, file_path, markdown
                    )
                    fi.commit(file_path, markdown, info)

                except FastImportDied:
                    raise
                except Exception:
                    errors += 1
                    logger.error(
                        "Error processing %s reform %d", norm_id, reform_idx, exc_info=True
                    )

                if (idx + 1) % 5000 == 0:
                    console.print(
                        f"  [dim][{idx + 1}/{len(all_reforms)}] queued, {errors} errors[/dim]"
                    )

                # Free norm from cache once all its reforms are queued
                if last_reform_index.get(norm_id) == idx:
                    norm_cache.pop(norm_id, None)

        imported += fi.commit_count

    console.print(f"\n[bold green]✓ {imported} commits created (fast-import)[/bold green]")

    # Every law that could be written is in the repo before this line, the same
    # order finalize_daily uses for a shadowed act: the run's work is not thrown
    # away because part of it failed. But a law that has data and no file is data
    # loss, and a green run with a traceback somewhere in the scrollback is how it
    # ships unnoticed. Measured on Portugal: a stale corpus missing the field the
    # layout template needs produced 171,737 errors, zero laws, and success.
    if errors:
        raise UnwritableLaw(
            f"{errors} law(s) had data and could not be written to the repo — "
            f"{fi.commit_count} commit(s) were created. See the logged tracebacks."
        )

    # imported, not fi.commit_count: that is the last chunk's tally, and it does
    # not exist at all on a run that had nothing left to do.
    return imported


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
        # The re-download decides what gets committed. When it fails it returns
        # None and leaves the old JSON in place, so commit_one re-renders exactly
        # the text that is being repaired, produces 0 commits and says nothing —
        # on the only repair path the commit-integrity rule allows.
        if generic_fetch_one(config, country, norm_id, force=True) is None:
            raise NothingPublished(
                f"{norm_id}: re-download failed, so there is nothing new to commit. "
                f"The law in the repo is unchanged."
            )
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


def write_repo_meta(config: Config, country: str) -> None:
    """Write repo-level meta files (.github/FUNDING.yml, ...) into the country repo.

    These are project metadata, not legislative records. They are committed as a
    single ``[fix-pipeline]`` meta commit with no ``Source-Date`` trailer, so the
    reform-history sync ignores them (see ``state/store.py``). The commit is only
    created when a file actually changed, so re-running is idempotent.
    """
    from legalize.committer.repo_meta import repo_meta_files

    cc = config.get_country(country)
    repo_dir = Path(cc.repo_path)
    if not repo_dir.exists():
        return

    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    repo.init()
    # The commit below is a plain `git commit`, and its tree comes from the
    # index. fast-import never touches the index, and it only resets the working
    # tree on the last chunk — so on the failure path, where this runs from a
    # `finally`, the meta commit was built from an index that predates the whole
    # import and deleted the corpus from the tip.
    repo.sync_index()

    changed = [
        rel_path
        for rel_path, content in repo_meta_files(country).items()
        if repo.write_and_add(rel_path, content)
    ]
    if not changed:
        return

    info = CommitInfo(
        commit_type=CommitType.FIX_PIPELINE,
        subject="[fix-pipeline] Update repository metadata",
        body="Refresh project meta files: " + ", ".join(changed) + ".",
        trailers={},
        author_name=config.git.committer_name,
        author_email=config.git.committer_email,
        author_date=date.today(),
        file_path=changed[0],
        content="",
    )
    repo.commit(info)
    console.print(f"  [dim]Committed repo meta: {', '.join(changed)}[/dim]")


# ─────────────────────────────────────────────
# PUSH
# ─────────────────────────────────────────────

# GitHub refuses any pack over 2.00 GiB. What you see instead is "the remote end
# hung up unexpectedly", because pack-objects computes deltas for many minutes in
# silence and the remote closes the idle connection first — a message that
# describes the socket, not the pack. Portugal cost an afternoon to that in
# August 2026: 1.2M objects, 2.86 GiB in one push.
#
# Slice size is close to linear in every phase, measured on that repo: 2000
# commits pack in 81s and 16.6 MB, 25000 in ~19min and ~207 MB. So a bigger
# slice buys no efficiency — it only raises what a failure costs. At 25000 a
# dropped connection threw away 19 minutes of compression twice in one evening.
#
# 5000 keeps a failure under five minutes and stays orders of magnitude below
# the limit. Raise it only if the per-push overhead starts to dominate, which
# means many slices of very few objects.
DEFAULT_SLICE = 5000

# pack-objects goes quiet for minutes; without keepalives the connection dies
# mid-computation and the real error never arrives.
_SSH_KEEPALIVE = "ssh -o ServerAliveInterval=15 -o ServerAliveCountMax=20 -o TCPKeepAlive=yes"

# A push can hang with the connection alive and the remote never answering —
# 1h27m of nothing, observed. But an idle client is NOT proof of a hang: after
# the pack is sent, the server spends a long quiet stretch on `Resolving
# deltas`, and during it the client burns no CPU, holds no pack-objects child
# and moves almost no traffic. Those signals look identical to a hang, and
# acting on them killed a healthy push at 46% of a server-side resolve.
#
# The one signal that does separate them is git's own progress: --progress
# streams while it counts, compresses and writes, and the server's resolve
# progress arrives over the sideband too. A truly stuck push prints nothing at
# all. So the guard is silence, not duration, not CPU, and not traffic.
#
# Generous on purpose: the server can also go quiet between the end of the
# resolve and the ref update. This only has to catch a push that has genuinely
# stopped talking, not one that is merely slow.
STALL_TIMEOUT_S = 900

# Waits between attempts. A slice spends 15-25 minutes compressing before it
# sends a byte, and a failure throws all of that away — so the retry has to
# outlast an ordinary connection drop, not just a blip. Portugal lost a 19-minute
# compression to a home connection going down, then burned its only retry 30
# seconds later against a DNS that had not come back yet.
RETRY_WAITS_S = (30, 300)


def slice_boundaries(commits: list[str], slice_size: int) -> list[str]:
    """Every slice_size-th commit, oldest first, then the remainder as HEAD.

    ``commits`` is the full history oldest-first. Each boundary is pushed as an
    intermediate advance of the branch, so the pack only ever holds one slice.
    """
    if slice_size < 1:
        raise ValueError("slice_size must be >= 1")
    return [commits[i - 1] for i in range(slice_size, len(commits) + 1, slice_size)] + ["HEAD"]


def _push_until_stalled(repo: Path, args: list[str], env: dict) -> tuple[bool, str]:
    """Run a git push, killing it if it goes silent for STALL_TIMEOUT_S.

    git's progress goes to stderr and is echoed through so a long compression is
    visible. Progress uses carriage returns, so this reads chunks, not lines.
    """
    proc = subprocess.Popen(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=env,
    )
    last_output = time.monotonic()
    last_line = "no output from git"

    def pump() -> None:
        nonlocal last_output, last_line
        assert proc.stderr is not None
        while chunk := proc.stderr.read(4096):
            last_output = time.monotonic()
            text = chunk.decode("utf-8", "replace")
            sys.stderr.write(text)
            sys.stderr.flush()
            if line := text.replace("\r", "\n").strip().splitlines()[-1:]:
                last_line = line[0]

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()

    while proc.poll() is None:
        if time.monotonic() - last_output > STALL_TIMEOUT_S:
            proc.kill()
            reader.join(timeout=5)
            return False, f"no progress for {STALL_TIMEOUT_S}s — killed"
        time.sleep(1)

    reader.join(timeout=5)
    return proc.returncode == 0, last_line


def push_all(
    config: Config,
    country: str,
    slice_size: int = DEFAULT_SLICE,
    start: int = 1,
    branch: str = "main",
    dry_run: bool = False,
    force: bool = False,
) -> int:
    """Push a country repo's history in slices. Returns slices pushed."""
    cc = config.get_country(country)
    repo = Path(cc.repo_path)
    if not (repo / ".git").exists():
        console.print(f"[red]{repo} is not a git repository.[/red]")
        return 0

    def git(*args: str, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, **kwargs
        )

    commits = git("rev-list", "--reverse", "HEAD").stdout.split()
    if not commits:
        console.print("[red]No commits to push.[/red]")
        return 0
    boundaries = slice_boundaries(commits, slice_size)

    # Refresh the remote-tracking ref before deciding what to skip. A stale ref
    # makes every skip decision wrong: a resumed run once recomputed its start
    # from a ref 75k commits behind and pushed a tip the remote was already
    # past, which git reports as "non-fast-forward" — again, the wrong noun.
    if not dry_run and git("fetch", "--quiet", "origin").returncode != 0:
        console.print("[yellow]fetch failed — skip detection may be stale[/yellow]")

    env = {**os.environ, "GIT_SSH_COMMAND": _SSH_KEEPALIVE}
    flags = ["--progress"] + (["--force"] if force else [])
    total = len(boundaries)
    pushed = 0

    for n, sha in enumerate(boundaries, 1):
        label = f"slice {n}/{total} -> {sha[:12]}"
        if n < start:
            continue
        if (
            sha != "HEAD"
            and git("merge-base", "--is-ancestor", sha, f"origin/{branch}").returncode == 0
        ):
            console.print(f"  [dim]{label} already on remote, skipping[/dim]")
            continue
        if dry_run:
            console.print(f"  {label}")
            continue

        console.print(f"[bold]{label}[/bold]")
        refspec = f"{sha}:refs/heads/{branch}"
        for attempt in range(len(RETRY_WAITS_S) + 1):
            started = time.monotonic()
            ok, last_line = _push_until_stalled(repo, ["push", *flags, "origin", refspec], env)
            elapsed = int(time.monotonic() - started)
            if ok:
                console.print(
                    f"  [green]slice {n}/{total} ok ({elapsed // 60}m {elapsed % 60}s)[/green]"
                )
                pushed += 1
                break
            console.print(
                f"  [yellow]{last_line} (after {elapsed // 60}m {elapsed % 60}s)[/yellow]"
            )
            if attempt == len(RETRY_WAITS_S):
                console.print(
                    f"[red]slice {n} failed {attempt + 1} times — resume with --start {n}[/red]"
                )
                return pushed
            wait = RETRY_WAITS_S[attempt]
            console.print(f"  [dim]retrying in {wait}s[/dim]")
            time.sleep(wait)

    console.print(f"[bold green]{pushed} slice(s) pushed.[/bold green]")
    return pushed
