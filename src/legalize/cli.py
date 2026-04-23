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

console = Console()


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
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logs.")
@click.pass_context
def cli(ctx: click.Context, config_path: str, verbose: bool) -> None:
    """Legalize — Version-controlled legislation in Git."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(config_path)


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
    "--batch", default=None, type=int, help="Process N norms at a time, push after each batch."
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
        legalize commit -c fr --all --batch 10         # 10 at a time, push after each
        legalize commit -c fr --all --limit 10         # Only first 10
        legalize commit -c fr --all --offset 10 --limit 10  # Norms 11-20
    """
    from legalize.pipeline import commit_all, commit_all_fast, commit_one

    config = ctx.obj["config"]
    if repo_path or data_dir:
        cc = config.get_country(country)
        if repo_path:
            cc.repo_path = repo_path
        if data_dir:
            cc.data_dir = data_dir

    if commit_all_flag:
        if batch:
            _commit_in_batches(config, country, batch, offset, limit, dry_run)
        elif fast:
            commit_all_fast(config, country, limit=limit, offset=offset)
        else:
            commit_all(config, country, dry_run=dry_run, limit=limit, offset=offset)
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
    """Process norms in batches, pushing after each one."""
    import subprocess
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

        commits = commit_all(config, country, dry_run=dry_run, limit=size, offset=current_offset)

        if not dry_run and commits > 0:
            console.print(f"\n  [dim]Pushing batch {batch_num} ({commits} commits)...[/dim]")
            try:
                subprocess.run(
                    ["git", "push", "origin", "HEAD"],
                    cwd=cc.repo_path,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                console.print(f"  [green]Batch {batch_num} pushed.[/green]")
            except subprocess.CalledProcessError as e:
                console.print(f"  [red]Push failed: {e.stderr}[/red]")

        current_offset += size
        remaining -= size

    console.print(f"\n[bold green]All {batch_num} batches completed.[/bold green]")


# ─────────────────────────────────────────────
# BOOTSTRAP
# ─────────────────────────────────────────────


@cli.command()
@_country_option()
@click.option("--repo-path", default=None, help="Override output repo directory.")
@click.option("--data-dir", default=None, help="Override data directory.")
@click.option("--legi-dir", default=None, help="France only: path to extracted LEGI dump.")
@click.option("--xml", "xml_path", default=None, help="Path to local XML (pilot, ES only).")
@click.option("--limit", default=None, type=int, help="Process only the first N norms.")
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
    dry_run: bool,
) -> None:
    """Fetch + commit all norms for a country.

    Examples:
        legalize bootstrap -c ar                    # Argentina (32K norms)
        legalize bootstrap -c ar --limit 50         # Quick test
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


@cli.command()
@_country_option()
@click.option("--sample", default=500, type=int, help="Number of recent commits to sample.")
@click.pass_context
def health(ctx: click.Context, country: str, sample: int) -> None:
    """Run health checks on a country repo.

    Checks for: anomalous commit dates, empty/tiny files,
    dirty working tree, missing remote, orphan JSON data.

    Examples:
        legalize health -c es
        legalize health -c se --sample 1000
    """
    import subprocess
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
    md_files = list(repo.rglob("*.md"))
    md_files = [f for f in md_files if ".git" not in f.parts]
    commit_count = _git("rev-list", "--count", "HEAD").stdout.strip()
    console.print(f"  Markdown files: {len(md_files)}")
    console.print(f"  Git commits:    {commit_count}")

    if data_dir:
        json_dir = data_dir / "json"
        json_count = len(list(json_dir.glob("*.json"))) if json_dir.exists() else 0
        console.print(f"  JSON data:      {json_count}")

        # Orphan JSONs (have data but no markdown)
        if json_count > 0 and len(md_files) > 0:
            md_stems = {f.stem for f in md_files}
            json_stems = {f.stem for f in json_dir.glob("*.json")}
            orphans = json_stems - md_stems
            if orphans:
                issues.append(("WARN", f"{len(orphans)} JSON files without corresponding Markdown"))
                if len(orphans) <= 5:
                    for o in sorted(orphans):
                        issues.append(("WARN", f"  orphan: {o}"))
        elif json_count > 0 and len(md_files) == 0:
            issues.append(("WARN", f"{json_count} JSON files but 0 Markdown — commit never ran?"))

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
