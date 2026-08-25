"""Legalize pipeline CLI.

Entry point: `legalize <subcommand> [options]`

Unified CLI with --country flag for all operations.
"""

from __future__ import annotations

import logging
from datetime import date

import click
from rich.console import Console
from rich.logging import RichHandler

from legalize.config import load_config
from legalize.countries import supported_countries
from legalize.models import NormMetadata, NormStatus, Rank

console = Console(soft_wrap=True)
console.file.reconfigure(line_buffering=True)


def _get_jurisdiction_codes(country: str) -> list[str]:
    """Return the list of subnational jurisdiction codes for a country.

    Derived from the country's metadata mappings (e.g., _DEPT_TO_JURISDICTION
    for Spain). Returns an empty list if no subnational jurisdictions exist.
    """
    if country == "es":
        from legalize.fetcher.es.metadata import _DEPT_TO_JURISDICTION

        return sorted(set(_DEPT_TO_JURISDICTION.values()))
    return []


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )


def _country_option(default: str = "es"):
    """Shared --country option for all commands."""
    return click.option(
        "--country",
        "-c",
        default=default,
        type=click.Choice(supported_countries(), case_sensitive=False),
        help="Country code (e.g., es, fr, se).",
    )


@click.group()
@click.option("--config", "config_path", default="config.yaml", help="Path to config file.")
@click.option(
    "--set",
    "-o",
    "overrides",
    multiple=True,
    metavar="KEY=VALUE",
    help="Override a config value, dotted: -o countries.pt.data_dir=/tmp/slice. Repeatable.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logs.")
@click.pass_context
def cli(ctx: click.Context, config_path: str, overrides: tuple[str, ...], verbose: bool) -> None:
    """Legalize — Version-controlled legislation in Git."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(config_path, _parse_overrides(overrides))


def _parse_overrides(pairs: tuple[str, ...]) -> dict[str, str]:
    """``KEY=VALUE`` pairs for ``load_config``, which has taken them all along.

    Pointing a run at a throwaway data directory and repo is what makes a
    rehearsal on a slice of the cache possible without copying config.yaml and
    editing it — a copy that then goes stale against the real one. The value is
    left a string: everything worth overriding from a shell is a path.
    """
    out: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise click.BadParameter(f"{pair!r} is not KEY=VALUE")
        out[key.strip()] = value
    return out


# ─────────────────────────────────────────────
# FETCH
# ─────────────────────────────────────────────


@cli.command()
@click.argument("norm_ids", nargs=-1)
@_country_option()
@click.option("--all", "fetch_all_flag", is_flag=True, help="Download all from catalog/config.")
@click.option("--catalog", is_flag=True, help="Spain only: download ALL from BOE catalog.")
@click.option("--force", is_flag=True, help="Re-download even if already exists.")
@click.option("--data-dir", default=None, help="Override data directory.")
@click.option("--legi-dir", default=None, help="France only: path to extracted LEGI dump.")
@click.option("--limit", default=None, type=int, help="Max norms to fetch.")
@click.option(
    "--offset", default=0, type=int, help="Skip first N norms (for splitting across VMs)."
)
@click.pass_context
def fetch(
    ctx: click.Context,
    norm_ids: tuple[str, ...],
    country: str,
    fetch_all_flag: bool,
    catalog: bool,
    force: bool,
    data_dir: str | None,
    legi_dir: str | None,
    limit: int | None,
    offset: int,
) -> None:
    """Download laws to data/ (does not touch git).

    Examples:
        legalize fetch -c ar --all                          # All Argentine norms
        legalize fetch -c ar --all --limit 10000            # First 10K only
        legalize fetch -c ar --all --offset 10000           # Skip first 10K
        legalize fetch -c ar --all --offset 10000 --limit 10000  # Norms 10K-20K
    """
    from legalize.pipeline import generic_fetch_all, generic_fetch_one

    config = ctx.obj["config"]
    if data_dir:
        cc = config.get_country(country)
        cc.data_dir = data_dir
    if legi_dir:
        cc = config.get_country(country)
        cc.source["legi_dir"] = legi_dir

    if catalog and country == "es":
        from legalize.fetcher.es.fetch import fetch_catalog

        fetch_catalog(config, force=force)
    elif fetch_all_flag:
        generic_fetch_all(config, country, force=force, limit=limit, offset=offset)
    elif norm_ids:
        for norm_id in norm_ids:
            generic_fetch_one(config, country, norm_id, force=force)
    else:
        console.print("Use --all, --catalog (ES only), or pass norm IDs.")


# ─────────────────────────────────────────────
# COMMIT
# ─────────────────────────────────────────────


@cli.command()
@click.argument("norm_ids", nargs=-1)
@_country_option()
@click.option("--all", "commit_all_flag", is_flag=True, help="Commit all from data/json/.")
@click.option(
    "--fast/--no-fast",
    default=True,
    help="Use git fast-import (default). --no-fast for incremental.",
)
@click.option("--limit", default=None, type=int, help="Max norms to process.")
@click.option("--offset", default=0, type=int, help="Skip first N norms.")
@click.option(
    "--batch", default=None, type=int, help="Process N norms at a time (incremental, resumable)."
)
@click.option("--dry-run", is_flag=True, help="Simulate without creating commits.")
@click.option("--repo-path", default=None, type=str, help="Override output repo directory.")
@click.option("--data-dir", default=None, type=str, help="Override data directory.")
@click.pass_context
def commit(
    ctx: click.Context,
    norm_ids: tuple[str, ...],
    country: str,
    commit_all_flag: bool,
    fast: bool,
    limit: int | None,
    offset: int,
    batch: int | None,
    dry_run: bool,
    repo_path: str | None,
    data_dir: str | None,
) -> None:
    """Generate git commits from local data in data/ (does not download anything).

    Examples:
        legalize commit -c fr --all                    # Fast bootstrap (default)
        legalize commit -c fr --all --no-fast          # Incremental (skips existing)
        legalize commit -c fr --all --batch 10         # 10 at a time, resumable
        legalize commit -c fr --all --limit 10         # Only first 10
        legalize commit -c fr --all --offset 10 --limit 10  # Norms 11-20
    """
    from legalize.pipeline import (
        UnwritableLaw,
        commit_all,
        commit_all_fast,
        commit_one,
        write_country_meta,
        write_repo_meta,
    )

    config = ctx.obj["config"]
    if repo_path or data_dir:
        cc = config.get_country(country)
        if repo_path:
            cc.repo_path = repo_path
        if data_dir:
            cc.data_dir = data_dir

    if commit_all_flag:
        # The manifest is not decoration: it is how a consumer knows where the
        # bodies are, so a repo without one is not conformant. `bootstrap` has
        # always written it, but §9.2 sends every country over ~20K laws down
        # this path instead, and that repo went out with no .legalize.yml and no
        # README unless somebody remembered to add them by hand.
        #
        # In a `finally` so that it still lands when the run ends red: a repo
        # that lost laws is the one you most need to be able to inspect.
        lost = None
        try:
            if batch:
                _commit_in_batches(config, country, batch, offset, limit, dry_run)
            elif fast:
                commit_all_fast(config, country, limit=limit, offset=offset)
            else:
                commit_all(config, country, dry_run=dry_run, limit=limit, offset=offset)
        except UnwritableLaw as exc:
            lost = exc
        finally:
            if not dry_run:
                write_country_meta(config, country)
                write_repo_meta(config, country)
        if lost:
            console.print(f"\n[red]{lost}[/red]")
            raise SystemExit(1)
    elif norm_ids:
        for norm_id in norm_ids:
            commit_one(config, country, norm_id, dry_run=dry_run)
    else:
        console.print("Use --all or pass norm IDs.")


def _commit_in_batches(
    config,
    country: str,
    batch_size: int,
    offset: int,
    limit: int | None,
    dry_run: bool,
) -> None:
    """Process norms in batches, so a long run reports progress and can resume.

    This used to push after every batch, which is how a flag named --batch came
    to move a public branch. Pushing is `legalize push` now: it slices by commit
    rather than by norm, targets the branch you name instead of whatever HEAD
    happens to be, and skips what the remote already has.
    """
    from pathlib import Path

    from legalize.pipeline import commit_all

    cc = config.get_country(country)
    json_dir = Path(cc.data_dir) / "json"
    total = len(sorted(json_dir.glob("*.json")))

    if limit:
        total = min(total - offset, limit)
    else:
        total = total - offset

    current_offset = offset
    remaining = total
    batch_num = 0

    while remaining > 0:
        batch_num += 1
        size = min(batch_size, remaining)
        console.print(f"\n[bold]{'=' * 50}[/bold]")
        console.print(
            f"[bold]  Batch {batch_num}: norms {current_offset + 1}–{current_offset + size} of {offset + total}[/bold]"
        )
        console.print(f"[bold]{'=' * 50}[/bold]\n")

        commit_all(config, country, dry_run=dry_run, limit=size, offset=current_offset)

        current_offset += size
        remaining -= size

    console.print(f"\n[bold green]All {batch_num} batches completed.[/bold green]")


# ─────────────────────────────────────────────
# BOOTSTRAP
# ─────────────────────────────────────────────


def _start_fresh(cc, country: str) -> None:
    """Empty the repo and the derived JSON, for a history that is being rebuilt.

    Two things, and both are required rather than tidy:

    ``json/`` is named by identifier and carries it inside. When a country's
    identifier rule changes, a stale file is not overwritten by the new run — it
    is left behind, and the commit phase reads the directory rather than the id
    list, so every one of them ships as a law that no longer exists.

    The repo is re-initialised because ``commit_all_fast`` streams a whole
    history through ``fast-import`` and does not skip what is already committed:
    run it over an existing repo and the result is the old history with a second
    one stacked on top. ``raw/`` is the source of truth and is never touched.

    The remote is carried over, because the point of rebuilding a history is to
    push it, and re-adding it by hand is the step someone forgets.
    """
    import shutil
    import subprocess
    from pathlib import Path

    repo = Path(cc.repo_path)
    if repo.exists() and not (repo / ".git").exists():
        # A repo_path typo should not delete somebody's directory.
        raise click.ClickException(f"--fresh: {repo} exists and is not a git repo, refusing")

    remote = ""
    if repo.exists():
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo,
            capture_output=True,
            text=True,
        ).stdout.strip()
        commits = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"], cwd=repo, capture_output=True, text=True
        ).stdout.strip()
        console.print(f"[yellow]--fresh: discarding {repo} ({commits or 0} commits)[/yellow]")
        shutil.rmtree(repo)

    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", f"[bootstrap] Init legalize-{country}"],
        cwd=repo,
        check=True,
    )
    if remote:
        subprocess.run(["git", "remote", "add", "origin", remote], cwd=repo, check=True)
        console.print(f"  [dim]remote kept: {remote}[/dim]")

    json_dir = Path(cc.data_dir) / "json"
    stale = sum(1 for _ in json_dir.glob("*.json")) if json_dir.exists() else 0
    console.print(f"[yellow]--fresh: removing {stale} derived file(s) from {json_dir}[/yellow]")
    shutil.rmtree(json_dir, ignore_errors=True)
    json_dir.mkdir(parents=True, exist_ok=True)

    # The discovery cache is derived too, and it is the one that goes stale
    # invisibly: a scope rule is corrected in the code, the list on disk still
    # holds what the old rule let through, and the run trusts the list. Portugal
    # had 6,056 pre-1960 scan-only diplomas sitting in a cache written seven
    # hours before `earliest_year` was fixed — enough to put every one of them
    # back into the corpus. Rediscovery reads the cached sitemaps, so it costs
    # no network.
    ids = Path(cc.data_dir) / "discovery_ids.txt"
    if ids.exists():
        console.print(f"[yellow]--fresh: discarding the discovery cache {ids}[/yellow]")
        ids.unlink()


@cli.command()
@_country_option()
@click.option("--repo-path", default=None, help="Override output repo directory.")
@click.option("--data-dir", default=None, help="Override data directory.")
@click.option("--legi-dir", default=None, help="France only: path to extracted LEGI dump.")
@click.option("--xml", "xml_path", default=None, help="Path to local XML (pilot, ES only).")
@click.option("--limit", default=None, type=int, help="Process only the first N norms.")
@click.option(
    "--fresh",
    is_flag=True,
    help="Re-init the repo and delete data/json/ first. For a rebuilt history.",
)
@click.option("--dry-run", is_flag=True, help="Simulate without creating commits.")
@click.pass_context
def bootstrap(
    ctx: click.Context,
    country: str,
    repo_path: str | None,
    data_dir: str | None,
    legi_dir: str | None,
    xml_path: str | None,
    limit: int | None,
    fresh: bool,
    dry_run: bool,
) -> None:
    """Fetch + commit all norms for a country.

    Examples:
        legalize bootstrap -c ar                    # Argentina (32K norms)
        legalize bootstrap -c ar --limit 50         # Quick test
        legalize bootstrap -c pt --fresh            # Identifier rule changed
        legalize bootstrap -c fr --legi-dir /path   # France
    """
    from legalize.pipeline import generic_bootstrap

    config = ctx.obj["config"]
    if repo_path:
        cc = config.get_country(country)
        cc.repo_path = repo_path
    if data_dir:
        cc = config.get_country(country)
        cc.data_dir = data_dir
    if legi_dir:
        cc = config.get_country(country)
        cc.source["legi_dir"] = legi_dir

    if fresh:
        _start_fresh(config.get_country(country), country)

    # Special case: bootstrap from local XML (ES pilot/tests)
    if xml_path and country == "es":
        from legalize.pipeline import bootstrap_from_local_xml

        metadata = NormMetadata(
            title="Constitución Española",
            short_title="Constitución Española",
            identifier="BOE-A-1978-31229",
            country="es",
            rank=Rank.CONSTITUCION,
            publication_date=date(1978, 12, 29),
            status=NormStatus.IN_FORCE,
            department="Cortes Generales",
            source="https://www.boe.es/eli/es/c/1978/12/27/(1)",
        )
        bootstrap_from_local_xml(config, metadata, xml_path, dry_run=dry_run)
    else:
        generic_bootstrap(config, country, dry_run=dry_run, limit=limit)


# ─────────────────────────────────────────────
# DAILY
# ─────────────────────────────────────────────


@cli.command()
@_country_option()
@click.option("--date", "target_date", default=None, help="Date to process (YYYY-MM-DD).")
@click.option("--repo-path", default=None, help="Override output repo directory.")
@click.option("--data-dir", default=None, help="Override data directory.")
@click.option("--legi-dir", default=None, help="France only: path to LEGI dump directory.")
@click.option("--push", is_flag=True, help="Push to remote after commits.")
@click.option("--dry-run", is_flag=True, help="Simulate without creating commits.")
@click.pass_context
def daily(
    ctx: click.Context,
    country: str,
    target_date: str | None,
    repo_path: str | None,
    data_dir: str | None,
    legi_dir: str | None,
    push: bool,
    dry_run: bool,
) -> None:
    """Daily processing: process today's new legislation.

    Examples:
        legalize daily                              # Spain, today
        legalize daily -c es --date 2026-03-28      # Spain, specific date
        legalize daily -c fr --date 2026-04-01      # France, specific date
    """
    config = ctx.obj["config"]
    if repo_path:
        cc = config.get_country(country)
        cc.repo_path = repo_path
    if data_dir:
        cc = config.get_country(country)
        cc.data_dir = data_dir
    if legi_dir:
        cc = config.get_country(country)
        cc.source["legi_dir"] = legi_dir
    if push:
        config.git.push = True

    parsed_date = date.fromisoformat(target_date) if target_date else None

    # Country-specific daily.py takes priority (ES, FR have custom flows).
    # Falls back to generic_daily for countries using the standard interfaces.
    try:
        module = __import__(f"legalize.fetcher.{country}.daily", fromlist=["daily"])
        run_daily = module.daily
        run_daily(config, target_date=parsed_date, dry_run=dry_run)
    except (ImportError, AttributeError):
        from legalize.pipeline import generic_daily

        generic_daily(config, country, target_date=parsed_date, dry_run=dry_run)


# ─────────────────────────────────────────────
# REPROCESS
# ─────────────────────────────────────────────


@cli.command()
@_country_option()
@click.option("--reason", required=True, help="Reason for reprocessing.")
@click.option("--dry-run", is_flag=True, help="Simulate without creating commits.")
@click.argument("norm_ids", nargs=-1, required=True)
@click.pass_context
def reprocess(
    ctx: click.Context,
    country: str,
    reason: str,
    dry_run: bool,
    norm_ids: tuple[str, ...],
) -> None:
    """Re-download and regenerate specific norms."""
    from legalize.pipeline import reprocess as run_reprocess

    config = ctx.obj["config"]
    run_reprocess(config, country, list(norm_ids), reason, dry_run=dry_run)


# ─────────────────────────────────────────────
# CCAA (Spain subnational — kept separate)
# ─────────────────────────────────────────────


@cli.command("fetch-jurisdiction")
@click.argument("jurisdiction", required=False)
@click.option("--all", "all_flag", is_flag=True, help="Fetch all subnational jurisdictions.")
@click.option("--force", is_flag=True, help="Re-download even if already exists.")
@_country_option()
@click.pass_context
def fetch_jurisdiction(
    ctx: click.Context, jurisdiction: str | None, all_flag: bool, force: bool, country: str
) -> None:
    """Download subnational jurisdiction legislation.

    Examples:
        legalize fetch-jurisdiction es-pv          # País Vasco only
        legalize fetch-jurisdiction --all           # All jurisdictions
        legalize fetch-jurisdiction --all -c es     # Explicit country
    """
    from legalize.fetcher.es.fetch import fetch_catalog_ccaa

    config = ctx.obj["config"]
    codes = _get_jurisdiction_codes(country)

    if not codes:
        console.print(f"[red]No subnational jurisdictions defined for {country}[/red]")
        return

    if all_flag:
        for jur in codes:
            fetch_catalog_ccaa(config, jur, force=force)
    elif jurisdiction:
        if jurisdiction not in codes:
            console.print(f"[red]Unknown: {jurisdiction}. Valid: {', '.join(codes)}[/red]")
            return
        fetch_catalog_ccaa(config, jurisdiction, force=force)
    else:
        console.print("Use --all or pass a jurisdiction code.")
        console.print(f"  Available: {', '.join(codes)}")


@cli.command("bootstrap-jurisdiction")
@click.argument("jurisdiction", required=False)
@click.option("--all", "all_flag", is_flag=True, help="Bootstrap all subnational jurisdictions.")
@click.option("--force", is_flag=True, help="Re-download even if already exists.")
@click.option("--dry-run", is_flag=True, help="Simulate without creating commits.")
@_country_option()
@click.pass_context
def bootstrap_jurisdiction(
    ctx: click.Context,
    jurisdiction: str | None,
    all_flag: bool,
    force: bool,
    dry_run: bool,
    country: str,
) -> None:
    """Full subnational bootstrap: fetch + commit.

    Examples:
        legalize bootstrap-jurisdiction es-pv          # País Vasco only
        legalize bootstrap-jurisdiction --all           # All jurisdictions
        legalize bootstrap-jurisdiction --all -c es     # Explicit country
    """
    import json
    from pathlib import Path

    from legalize.fetcher.es.fetch import fetch_catalog_ccaa
    from legalize.pipeline import commit_one

    config = ctx.obj["config"]
    codes = _get_jurisdiction_codes(country)

    if not codes:
        console.print(f"[red]No subnational jurisdictions defined for {country}[/red]")
        return

    targets = codes if all_flag else ([jurisdiction] if jurisdiction else [])
    if not targets:
        console.print("Use --all or pass a jurisdiction code.")
        console.print(f"  Available: {', '.join(codes)}")
        return

    if jurisdiction and jurisdiction not in codes:
        console.print(f"[red]Unknown: {jurisdiction}. Valid: {', '.join(codes)}[/red]")
        return

    _JUR_TO_NAME = {
        "es-an": "Andalucía",
        "es-ar": "Aragón",
        "es-as": "Asturias",
        "es-cb": "Cantabria",
        "es-cl": "Castilla y León",
        "es-cm": "Castilla-La Mancha",
        "es-cn": "Canarias",
        "es-ct": "Cataluña",
        "es-ex": "Extremadura",
        "es-ga": "Galicia",
        "es-ib": "Balears",
        "es-mc": "Murcia",
        "es-md": "Madrid",
        "es-nc": "Navarra",
        "es-pv": "País Vasco",
        "es-ri": "Rioja",
        "es-vc": "Valenciana",
    }

    grand_total = 0
    for jur in targets:
        name = _JUR_TO_NAME.get(jur, jur)
        console.print(f"\n[bold]{'=' * 50}[/bold]")
        console.print(f"[bold]  {jur.upper()} ({name})[/bold]")
        console.print(f"[bold]{'=' * 50}[/bold]")

        fetch_catalog_ccaa(config, jur, force=force)

        cc = config.get_country(country)
        json_dir = Path(cc.data_dir) / "json"
        jur_files = []
        for jf in sorted(json_dir.glob("*.json")):
            with open(jf) as f:
                data = json.load(f)
            jur_code = data.get("metadata", {}).get("jurisdiccion")
            dept = data.get("metadata", {}).get("departamento", "")
            if jur_code == jur or (not jur_code and name in dept):
                jur_files.append(jf)
        jur_files = list(dict.fromkeys(jur_files))

        console.print(f"  {len(jur_files)} norms to commit")

        commits = 0
        errors = 0
        for i, jf in enumerate(jur_files, 1):
            try:
                c = commit_one(config, country, jf.stem, dry_run=dry_run)
                commits += c
            except (OSError, ValueError):
                errors += 1
            if i % 100 == 0:
                console.print(f"  [{i}/{len(jur_files)}] {commits} commits")

        grand_total += commits
        repo_dir = Path(cc.repo_path) / jur
        actual = len(list(repo_dir.glob("*.md"))) if repo_dir.exists() else 0
        console.print(f"  [green]=> {actual} files, {commits} new commits, {errors} errors[/green]")

    console.print(f"\n[bold green]Total: {grand_total} new commits[/bold green]")


# ─────────────────────────────────────────────
# HEALTH
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# PUSH
# ─────────────────────────────────────────────


@cli.command()
@_country_option()
@click.option("--slice", "slice_size", default=None, type=int, help="Commits per slice.")
@click.option("--start", default=1, type=int, help="Resume at slice N.")
@click.option("--branch", default="main", help="Remote branch to advance.")
@click.option("--dry-run", is_flag=True, help="List the slices without pushing.")
@click.option("--force", is_flag=True, help="Push with --force. Rewrites the public repo.")
@click.pass_context
def push(
    ctx: click.Context,
    country: str,
    slice_size: int | None,
    start: int,
    branch: str,
    dry_run: bool,
    force: bool,
) -> None:
    """Push a country repo's history to origin in slices.

    GitHub refuses any pack over 2.00 GiB, and a first bootstrap of a large
    country exceeds it. Each slice is a separate push and a short-lived
    connection, so the pack never approaches the limit. Already-pushed slices
    are detected and skipped, so this is safe to re-run.

    Examples:
        legalize push -c pt --dry-run       # list the slices first
        legalize push -c pt                 # 25000 commits per slice
        legalize push -c pt --slice 10000   # smaller slices
        legalize push -c pt --start 7       # resume at slice 7
    """
    from legalize.pipeline import DEFAULT_SLICE, push_all

    push_all(
        ctx.obj["config"],
        country,
        slice_size=slice_size or DEFAULT_SLICE,
        start=start,
        branch=branch,
        dry_run=dry_run,
        force=force,
    )


def _read_frontmatter(path) -> dict | None:
    """The YAML block at the top of a law file, or None if there is not one.

    Read line by line and stopped at the closing fence: a law's body runs to
    hundreds of kilobytes and none of it is needed here.
    """
    import yaml

    lines: list[str] = []
    try:
        with open(path, encoding="utf-8") as handle:
            if handle.readline().rstrip("\n") != "---":
                return None
            for line in handle:
                if line.rstrip("\n") == "---":
                    break
                lines.append(line)
            else:
                return None
    except OSError:
        return None
    try:
        parsed = yaml.safe_load("".join(lines))
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalised(value) -> str:
    """One value, in the shape two layers of the pipeline can be compared on.

    Matching source fields to published ones by *name* does not work — the
    source calls it ``Titulo`` and the file calls it ``title`` — so they are
    matched by value instead, which needs the spellings reconciled: a source
    writes ``2025-02-14T00:00:00`` where a file writes ``2025-02-14``, and
    ``Portaria`` where a file writes ``portaria``.
    """
    text = " ".join(str(value).split()).lower()
    if len(text) >= 19 and text[10] == "t" and text[4] == "-":
        text = text[:10]
    return text


def _published_values(path) -> set:
    """Every value a published file states, hashed to keep the corpus in memory."""
    front = _read_frontmatter(path)
    if not front:
        return set()
    out = set()
    for value in front.values():
        for item in value if isinstance(value, list) else [value]:
            text = _normalised(item)
            if text:
                out.add(hash(text))
    return out


def _source_fields(path) -> dict:
    """What the source actually stated on one cached record, by dotted path.

    Nulls, empty strings and empty containers do not count as stated: a source
    returns its whole schema on every record and most of it is holes.
    """
    import gzip
    import json

    def walk(node, prefix=""):
        found = {}
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, dict):
                    found.update(walk(value, f"{prefix}{key}."))
                elif isinstance(value, bool):
                    continue  # a flag is structure, not content
                elif isinstance(value, (str, int, float)) and str(value).strip():
                    # A body is transformed on its way into the file — HTML to
                    # Markdown — so comparing it by value says nothing. Only
                    # field-sized values can be looked for verbatim.
                    if len(str(value)) <= 200:
                        found[f"{prefix}{key}"] = value
        return found

    try:
        opener = gzip.open if str(path).endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as handle:
            return walk(json.load(handle))
    except (OSError, ValueError):
        return {}


@cli.command()
@_country_option()
@click.option("--sample", default=500, type=int, help="Number of recent commits to sample.")
@click.option(
    "--deep",
    is_flag=True,
    help="Also read file contents: layout conformance and unpublished source fields. Minutes, not seconds.",
)
@click.pass_context
def health(ctx: click.Context, country: str, sample: int, deep: bool) -> None:
    """Run health checks on a country repo. Exits non-zero on any error.

    Two costs. By default it reads names — counts per stage, laws that lost
    their data or never reached the repo, duplicate identifiers, empty files,
    anomalous dates — and takes seconds. ``--deep`` also reads contents: whether
    every file is where the manifest promises, and which fields the source fills
    that no published file carries. That one walks the whole cache.

    Examples:
        legalize health -c es
        legalize health -c pt --deep
        legalize health -c se --sample 1000
    """
    import subprocess
    from collections import Counter
    from datetime import date
    from pathlib import Path

    config = ctx.obj["config"]
    cc = config.get_country(country)
    repo = Path(cc.repo_path)
    data_dir = Path(cc.data_dir) if cc.data_dir else None

    issues: list[tuple[str, str]] = []  # (severity, message)

    console.print(f"[bold]Health check — {country.upper()}[/bold]\n")

    # ── 1. Repo exists? ──
    if not (repo / ".git").exists():
        console.print(f"  [red]No git repo at {repo}[/red]")
        return

    def _git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)

    # ── 2. Basic stats ──
    # The repo's own README is Markdown too, and it is not a law: it has no
    # frontmatter, so every check below that reads one would report it as broken.
    # Taken from the writer's own list rather than a second one here, which would
    # go stale the day a meta file is added.
    from legalize.committer.repo_meta import repo_meta_files

    meta_paths = {repo / name for name in repo_meta_files(country)}
    md_files = list(repo.rglob("*.md"))
    md_files = [f for f in md_files if ".git" not in f.parts and f not in meta_paths]
    commit_count = _git("rev-list", "--count", "HEAD").stdout.strip()
    console.print(f"  Markdown files: {len(md_files)}")
    console.print(f"  Git commits:    {commit_count}")

    # Every law is a file named after its identifier, so two files with one stem
    # means two laws answer to one name — the failure that cost 6,862 Portuguese
    # laws, where the second write replaced the first and left no trace.
    stems: dict[str, list[Path]] = {}
    for f in md_files:
        stems.setdefault(f.stem, []).append(f)
    clashes = {k: v for k, v in stems.items() if len(v) > 1}
    if clashes:
        issues.append(("ERROR", f"{len(clashes)} identifier(s) claimed by more than one file"))
        for name, paths in list(clashes.items())[:5]:
            issues.append(
                ("ERROR", f"  {name}: {', '.join(str(x.relative_to(repo)) for x in paths)}")
            )

    if data_dir:
        json_dir = data_dir / "json"
        json_stems = {f.stem for f in json_dir.glob("*.json")} if json_dir.exists() else set()
        console.print(f"  JSON data:      {len(json_stems)}")

        raw_dir = data_dir / "raw"
        if raw_dir.exists():
            raw_count = sum(1 for _ in raw_dir.glob("*.meta.json*"))
            console.print(f"  Raw envelopes:  {raw_count}")

        # A law with data but no file never reached the repo, and nothing else
        # says so: it is dropped in silence somewhere between parse and commit.
        # A law with a file but no data is the reverse — a file the pipeline can
        # no longer rebuild, which is what a stale identifier scheme leaves behind.
        if json_stems and md_files:
            md_stems = {f.stem for f in md_files}
            for missing, label in (
                (json_stems - md_stems, "have data but never reached the repo"),
                (md_stems - json_stems - {"README"}, "are in the repo with no data behind them"),
            ):
                if missing:
                    issues.append(("ERROR", f"{len(missing)} law(s) {label}"))
                    for name in sorted(missing)[:5]:
                        issues.append(("ERROR", f"  {name}"))
        elif json_stems and not md_files:
            issues.append(
                ("ERROR", f"{len(json_stems)} JSON files but 0 Markdown — commit never ran?")
            )

    # ── 3. Working tree ──
    status_out = _git("status", "--porcelain").stdout.strip()
    if status_out:
        changed = len(status_out.splitlines())
        issues.append(("WARN", f"Working tree dirty: {changed} uncommitted change(s)"))

    # ── 4. Remote ──
    remote_out = _git("remote", "-v").stdout.strip()
    if not remote_out:
        issues.append(("ERROR", "No git remote configured"))
    else:
        # Check if local is ahead of remote
        fetch_result = _git("rev-list", "--count", "HEAD", "--not", "--remotes")
        ahead = fetch_result.stdout.strip()
        if ahead and int(ahead) > 0:
            issues.append(("WARN", f"{ahead} commit(s) not pushed to remote"))

    # ── 5. Empty / tiny files ──
    empty = [f for f in md_files if f.stat().st_size == 0]
    tiny = [f for f in md_files if 0 < f.stat().st_size < 50]
    if empty:
        issues.append(("ERROR", f"{len(empty)} empty Markdown file(s)"))
        for f in empty[:5]:
            issues.append(("ERROR", f"  empty: {f.relative_to(repo)}"))
    if tiny:
        issues.append(("WARN", f"{len(tiny)} Markdown file(s) under 50 bytes"))
        for f in tiny[:5]:
            issues.append(("WARN", f"  tiny: {f.relative_to(repo)}"))

    # ── 6. Deep: read the files, not just their names ──
    if deep:
        from concurrent.futures import ThreadPoolExecutor

        from legalize.layout import TemplateError, layout_for, path_from_frontmatter

        workers = getattr(cc, "max_workers", 1) or 1
        template = layout_for(country)
        console.print(f"\n  Reading {len(md_files)} files with {workers} workers...")

        def _placed(path: Path) -> tuple[str, str] | None:
            """The file's own answer to where it should be, against where it is."""
            front = _read_frontmatter(path)
            if front is None:
                return (str(path.relative_to(repo)), "no frontmatter")
            try:
                want = path_from_frontmatter(front, template)
            except TemplateError as exc:
                return (str(path.relative_to(repo)), str(exc).split(": ", 1)[-1])
            have = path.relative_to(repo).as_posix()
            return None if want == have else (have, f"belongs at {want}")

        def _references(path: Path) -> tuple[str, list[tuple[str, str]]]:
            """The identifiers this file names, and the identifier it goes by."""
            front = _read_frontmatter(path) or {}
            out: list[tuple[str, str]] = []
            if front.get("last_amendment"):
                out.append(("last_amendment", str(front["last_amendment"])))
            amends = front.get("amends")
            if isinstance(amends, list):
                out.extend(("amends", str(a)) for a in amends)
            elif amends:
                out.append(("amends", str(amends)))
            return str(front.get("identifier") or ""), out

        with ThreadPoolExecutor(max_workers=workers) as pool:
            misplaced = [r for r in pool.map(_placed, md_files) if r]
            published: set[int] = set()
            for values in pool.map(_published_values, md_files):
                published |= values
            identifiers: set[str] = set()
            references: list[tuple[str, str]] = []
            for own, refs in pool.map(_references, md_files):
                if own:
                    identifiers.add(own)
                references.extend(refs)

        # The manifest is a promise: fill in what it declares and you get the
        # file. A repo that breaks it resolves every law's metadata and 404s
        # every body — 171,735 pages that look fine and are empty.
        if misplaced:
            issues.append(("ERROR", f"{len(misplaced)} file(s) not where the manifest says"))
            for where, why in misplaced[:10]:
                issues.append(("ERROR", f"  {where} — {why}"))

        # ── Cross-references: a name that names nothing ──
        #
        # `amends` and `last_amendment` hold identifiers of other laws in this
        # same repo, and nothing until now checked that they resolve. That is how
        # Portugal came within one command of publishing 46,750 laws whose
        # `last_amendment` named a diploma in an identifier scheme the corpus had
        # left months earlier: every file valid, every path right, every date
        # sane, and every cross-reference pointing at nothing.
        #
        # Not every miss is a fault. An amending act can be genuinely outside the
        # corpus — an out-of-scope type, a regional gazette a country does not
        # publish — and Portugal's real rate is 1.7 %. What is never ordinary is
        # most of them missing at once: that is not scope, that is a scheme that
        # moved without its references. So the rate is always reported and the
        # majority is where it turns red.
        for field, expected in (("amends", True), ("last_amendment", False)):
            refs = [ident for name, ident in references if name == field]
            if not refs:
                continue
            missing = [ident for ident in refs if ident not in identifiers]
            if not missing:
                continue
            rate = len(missing) / len(refs)
            sample = ", ".join(sorted(set(missing))[:5])
            # The spec makes `amends` resolvable by definition: it is a list of
            # identifiers "as this repo names them", for a consumer that has the
            # file and not the history. One that does not resolve is a broken
            # promise, not a law out of scope.
            level = "ERROR" if expected or rate > 0.5 else "WARN"
            issues.append(
                (
                    level,
                    f"{len(missing)} of {len(refs)} {field} reference(s) "
                    f"name no law in this repo ({rate:.1%}): {sample}"
                    f"{' …' if len(set(missing)) > 5 else ''}",
                )
            )

        # A value the source states that no published file anywhere repeats is a
        # value the pipeline drops on the floor. Portugal's `Resumo` was one:
        # filled on 12.9 % of records, and on 11.8 % it was the only prose
        # description of the law there was. Compared by value and not by name,
        # because the two layers do not agree on names and never will.
        raw_dir = data_dir / "raw" if data_dir else None
        if raw_dir and raw_dir.exists() and published:
            # Sampled: the answer is a rate, and a few thousand records settle
            # it as well as two hundred thousand do. Evenly spaced rather than
            # taken off the front, because the cache is ordered by type.
            cached = sorted(raw_dir.glob("*.meta.json*"))
            envelopes = cached[:: max(1, len(cached) // 4000)]
            console.print(f"  Sampling {len(envelopes)} of {len(cached)} source envelopes...")
            seen: Counter = Counter()
            dropped: Counter = Counter()
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for fields in pool.map(_source_fields, envelopes):
                    for key, value in fields.items():
                        seen[key] += 1
                        if hash(_normalised(value)) not in published:
                            dropped[key] += 1

            # Reported only where the field is both common and consistently
            # absent: a value that reaches the file in most records and not in a
            # handful is the source being irregular, not the pipeline losing it.
            lost = [
                (k, n, seen[k])
                for k, n in dropped.most_common()
                if n / (seen[k] or 1) > 0.9 and seen[k] / len(envelopes) >= 0.01
            ]
            if lost:
                issues.append(
                    (
                        "WARN",
                        f"{len(lost)} source field(s) never appear verbatim in a published file "
                        f"(sampled; a field the pipeline reshapes rather than copies shows up here too)",
                    )
                )
                for key, n, total in lost[:15]:
                    issues.append(
                        (
                            "WARN",
                            f"  {key} — stated on {100 * total / len(envelopes):.1f}% of records, none published",
                        )
                    )

    # ── 6. Anomalous commit dates ──
    console.print(f"\n  Sampling {sample} recent commits for date anomalies...")
    log_out = _git("log", f"-{sample}", "--format=%H %aI", "--reverse").stdout.strip()

    epoch_count = 0
    future_count = 0
    far_future = []
    today = date.today()

    for line in log_out.splitlines():
        if not line.strip():
            continue
        parts = line.split(" ", 1)
        if len(parts) < 2:
            continue
        sha, date_str = parts
        try:
            commit_date = date.fromisoformat(date_str[:10])
        except ValueError:
            continue

        if commit_date.year == 1970:
            epoch_count += 1
        elif commit_date > today and commit_date.year > today.year + 1:
            far_future.append((sha[:10], commit_date.isoformat()))
        elif commit_date > today:
            future_count += 1

    if epoch_count:
        issues.append(("WARN", f"{epoch_count} commit(s) with epoch date (1970)"))
    if future_count:
        issues.append(
            ("INFO", f"{future_count} commit(s) with near-future date (next year) — likely valid")
        )
    if far_future:
        issues.append(("ERROR", f"{len(far_future)} commit(s) with far-future date (bug)"))
        for sha, d in far_future:
            subject = _git("log", "-1", "--format=%s", sha).stdout.strip()
            issues.append(("ERROR", f"  {sha} {d} — {subject}"))

    # ── 7. Report ──
    console.print()
    if not issues:
        console.print("  [bold green]All checks passed.[/bold green]")
    else:
        errors = [i for i in issues if i[0] == "ERROR"]
        warns = [i for i in issues if i[0] == "WARN"]
        infos = [i for i in issues if i[0] == "INFO"]

        for severity, msg in issues:
            if severity == "ERROR":
                console.print(f"  [red]ERROR[/red] {msg}")
            elif severity == "WARN":
                console.print(f"  [yellow]WARN[/yellow]  {msg}")
            else:
                console.print(f"  [dim]INFO[/dim]  {msg}")

        console.print()
        console.print(
            f"  [bold]{len(errors)} error(s), {len(warns)} warning(s), {len(infos)} info(s)[/bold]"
        )
        # A bootstrap runs for hours and nobody reads the scroll. Printing the
        # problem and exiting 0 is how three Portuguese laws vanished from the
        # corpus with a warning on screen that said so.
        if errors:
            raise SystemExit(1)


# ─────────────────────────────────────────────
# REFORMS
# ─────────────────────────────────────────────


@cli.command()
@_country_option()
@click.argument("law_id")
@click.option("--diff", is_flag=True, help="Show what each commit changed in the text.")
@click.pass_context
def reforms(ctx: click.Context, country: str, law_id: str, diff: bool) -> None:
    """Every change a law has been through, from the repo's own history.

    Found by the ``Norm-Id`` trailer rather than by path, which costs a walk of
    the commit messages and no tree reads at all: 0.8 s against 73 minutes for
    ``git log --name-only`` on a 300,000-commit repo. It also survives the law
    moving, which a path-based lookup does not.

    What is worth looking at depends on what the file holds, so this reads the
    law's ``text_state`` and says so: where the body is the law as enacted, the
    text never changes and each commit's amending act is the whole story.

    Examples:
        legalize reforms -c pt DRE-2001-3-1331261
        legalize reforms -c es BOE-A-1978-31229 --diff
    """
    import subprocess
    from pathlib import Path

    from rich.markup import escape

    config = ctx.obj["config"]
    repo = Path(config.get_country(country).repo_path)
    if not (repo / ".git").exists():
        console.print(f"  [red]No git repo at {repo}[/red]")
        raise SystemExit(1)

    def _git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True
        ).stdout.rstrip()

    # A trailer is a whole line, so the grep is anchored: `Norm-Id: ES-1` must
    # not also answer for `ES-10`.
    log = _git(
        "log",
        f"--grep=^Norm-Id: {law_id}$",
        "--extended-regexp",
        "--format=%H|%ad|%s",
        "--date=short",
    )
    if not log:
        console.print(f"  [yellow]No commits carry Norm-Id: {law_id}[/yellow]")
        raise SystemExit(1)

    entries = [line.split("|", 2) for line in log.splitlines()]
    path = _git("log", "-1", "--name-only", "--format=", entries[0][0])
    state = "point_in_time"
    if path:
        front = _read_frontmatter(repo / path.splitlines()[0])
        state = (front or {}).get("text_state") or "point_in_time"

    console.print(
        f"\n[bold]{escape(law_id)}[/bold]  ·  {len(entries)} commit(s)  ·  {escape(str(state))}\n"
    )
    if state == "as_enacted":
        console.print(
            "  [dim]The body is the act as published and does not change. Each commit\n"
            "  records an amendment; the amending act is a file of its own.[/dim]\n"
        )

    for sha, when, subject in entries:
        body = _git("log", "-1", "--format=%b", sha)
        source = next(
            (
                ln.split(":", 1)[1].strip()
                for ln in body.splitlines()
                if ln.startswith("Disposition:")
            ),
            "",
        )
        console.print(f"  {when}  {sha[:10]}  {escape(subject[:76])}")
        if source:
            console.print(f"              [dim]by {escape(source)}[/dim]")
        if diff:
            # The bootstrap commit is the one that wrote the body, whatever the
            # text state — only the amendments after it leave it untouched.
            if state == "as_enacted" and not subject.startswith("[bootstrap]"):
                console.print(
                    "              [dim](body unchanged — this amendment is not incorporated)[/dim]"
                )
            else:
                stat = _git("show", "--stat", "--format=", sha)
                for line in stat.splitlines():
                    console.print(f"              [dim]{escape(line.strip())}[/dim]")

    console.print()


# ─────────────────────────────────────────────
# STATUS
# ─────────────────────────────────────────────


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show pipeline status."""
    from pathlib import Path

    from legalize.state.store import StateStore

    config = ctx.obj["config"]

    console.print("[bold]Legalize pipeline status[/bold]\n")

    if not config.countries:
        console.print("  [dim]No countries configured.[/dim]")
        return

    # Show per-country stats
    if config.countries:
        console.print("[bold]Per-country:[/bold]")
        for code in config.countries:
            cc = config.get_country(code)
            jdir = Path(cc.data_dir) / "json" if cc.data_dir else None
            count = len(list(jdir.glob("*.json"))) if jdir and jdir.exists() else 0

            state = StateStore(cc.state_path)
            state.load()

            console.print(f"\n  [bold]{code.upper()}[/bold]")
            console.print(f"    Downloaded norms: {count}")
            console.print(f"    Last summary: {state.last_summary_date or '[dim]none[/dim]'}")
