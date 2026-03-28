"""Legalize pipeline CLI.

Entry point: `legalize <subcommand> [options]`
"""

from __future__ import annotations

import logging
from datetime import date

import click
from rich.console import Console
from rich.logging import RichHandler

from legalize.config import load_config
from legalize.models import EstadoNorma, NormaMetadata, Rango

console = Console()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
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


@cli.command()
@click.argument("boe_ids", nargs=-1)
@click.option("--all", "fetch_all_flag", is_flag=True, help="Download all from config.")
@click.option("--catalog", is_flag=True, help="Download ALL from BOE catalog.")
@click.option("--force", is_flag=True, help="Re-download even if already exists.")
@click.pass_context
def fetch(ctx: click.Context, boe_ids: tuple[str, ...], fetch_all_flag: bool, catalog: bool, force: bool) -> None:
    """Download XML + metadata of laws to data/ (does not touch git)."""
    from legalize.pipeline import fetch_all, fetch_catalog, fetch_one

    config = ctx.obj["config"]

    if catalog:
        fetch_catalog(config, force=force)
    elif fetch_all_flag:
        fetch_all(config, force=force)
    elif boe_ids:
        for boe_id in boe_ids:
            fetch_one(config, boe_id, force=force)
    else:
        console.print("Use --catalog, --all, or pass BOE-IDs.")


@cli.command()
@click.argument("boe_ids", nargs=-1)
@click.option("--all", "commit_all_flag", is_flag=True, help="Commit all from data/json/.")
@click.option("--dry-run", is_flag=True, help="Simulate without creating commits.")
@click.pass_context
def commit(ctx: click.Context, boe_ids: tuple[str, ...], commit_all_flag: bool, dry_run: bool) -> None:
    """Generate git commits from local data in data/ (does not download anything)."""
    from legalize.pipeline import commit_all, commit_one

    config = ctx.obj["config"]

    if commit_all_flag:
        commit_all(config, dry_run=dry_run)
    elif boe_ids:
        for boe_id in boe_ids:
            commit_one(config, boe_id, dry_run=dry_run)
    else:
        console.print("Use --all or pass BOE-IDs. E.g.: legalize commit BOE-A-1978-31229")


@cli.command()
@click.option("--repo-path", default=None, help="Override output repo directory.")
@click.option("--xml", "xml_path", default=None, help="Path to local XML (pilot).")
@click.option("--dry-run", is_flag=True, help="Simulate without creating commits.")
@click.pass_context
def bootstrap(ctx: click.Context, repo_path: str | None, xml_path: str | None, dry_run: bool) -> None:
    """Fetch + commit all norms (shortcut)."""
    from legalize.pipeline import bootstrap as run_bootstrap, bootstrap_from_local_xml

    config = ctx.obj["config"]
    if repo_path:
        config.git.repo_path = repo_path

    console.print("[bold]Bootstrap — fetch + commit[/bold]")
    console.print(f"  Repo: {config.git.repo_path}")

    if xml_path:
        metadata = NormaMetadata(
            titulo="Constitución Española",
            titulo_corto="Constitución Española",
            identificador="BOE-A-1978-31229",
            pais="es",
            rango=Rango.CONSTITUCION,
            fecha_publicacion=date(1978, 12, 29),
            estado=EstadoNorma.VIGENTE,
            departamento="Cortes Generales",
            fuente="https://www.boe.es/eli/es/c/1978/12/27/(1)",
        )
        console.print(f"  XML local: {xml_path}")
        bootstrap_from_local_xml(config, metadata, xml_path, dry_run=dry_run)
    else:
        console.print(f"  Normas: {config.scope.normas_fijas}\n")
        run_bootstrap(config, dry_run=dry_run)


@cli.command()
@click.option("--date", "target_date", default=None, help="Date to process (YYYY-MM-DD).")
@click.option("--push", is_flag=True, help="Push to remote after commits.")
@click.option("--dry-run", is_flag=True, help="Simulate without creating commits.")
@click.pass_context
def daily(ctx: click.Context, target_date: str | None, push: bool, dry_run: bool) -> None:
    """Daily processing: process today's BOE summary."""
    from legalize.pipeline import daily as run_daily

    config = ctx.obj["config"]
    if push:
        config.git.push = True

    parsed_date = date.fromisoformat(target_date) if target_date else None
    run_daily(config, target_date=parsed_date, dry_run=dry_run)


@cli.command()
@click.option("--reason", required=True, help="Reason for reprocessing.")
@click.option("--dry-run", is_flag=True, help="Simulate without creating commits.")
@click.argument("boe_ids", nargs=-1, required=True)
@click.pass_context
def reprocess(ctx: click.Context, reason: str, dry_run: bool, boe_ids: tuple[str, ...]) -> None:
    """Re-download and regenerate specific norms."""
    from legalize.pipeline import reprocess as run_reprocess

    config = ctx.obj["config"]
    run_reprocess(config, list(boe_ids), reason, dry_run=dry_run)


# ─── France (LEGI) ───


@cli.command("fetch-fr")
@click.argument("norm_ids", nargs=-1)
@click.option("--discover", "discover_flag", is_flag=True, help="Discover all codes in force.")
@click.option("--force", is_flag=True, help="Re-process even if already exists.")
@click.option("--legi-dir", default=None, help="Path to extracted LEGI dump.")
@click.option("--data-dir", default=None, help="Override data dir for France.")
@click.pass_context
def fetch_fr(
    ctx: click.Context,
    norm_ids: tuple[str, ...],
    discover_flag: bool,
    force: bool,
    legi_dir: str | None,
    data_dir: str | None,
) -> None:
    """Process texts from the LEGI dump (France). Does not touch git."""
    from legalize.pipeline_fr import fetch_all_fr, fetch_one_fr

    config = ctx.obj["config"]
    if legi_dir:
        config.legi_dir = legi_dir
    if data_dir:
        config.data_dir = data_dir

    if discover_flag:
        fetch_all_fr(config, force=force)
    elif norm_ids:
        for norm_id in norm_ids:
            fetch_one_fr(config, norm_id, force=force)
    else:
        console.print("Use --discover or pass LEGITEXT IDs.")
        console.print("  E.g.: legalize fetch-fr --discover --legi-dir /path/to/legi")
        console.print("  E.g.: legalize fetch-fr LEGITEXT000006069414 --legi-dir /path/to/legi")


@cli.command("bootstrap-fr")
@click.option("--legi-dir", required=True, help="Path to extracted LEGI dump.")
@click.option("--repo-path", default="../fr", help="Output repo (legalize-fr).")
@click.option("--data-dir", default="../data-fr", help="Data directory for France.")
@click.option("--dry-run", is_flag=True, help="Simulate without creating commits.")
@click.pass_context
def bootstrap_fr_cmd(
    ctx: click.Context,
    legi_dir: str,
    repo_path: str,
    data_dir: str,
    dry_run: bool,
) -> None:
    """Full France bootstrap: discover + fetch + commit."""
    from legalize.pipeline_fr import bootstrap_fr

    config = ctx.obj["config"]
    config.country = "fr"
    config.legi_dir = legi_dir
    config.git.repo_path = repo_path
    config.data_dir = data_dir

    bootstrap_fr(config, dry_run=dry_run)


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show pipeline status."""
    from legalize.state.mappings import IdToFilename
    from legalize.state.store import StateStore

    config = ctx.obj["config"]

    state = StateStore(config.state_path)
    state.load()

    mappings = IdToFilename(config.mappings_path)
    mappings.load()

    # Count downloaded JSONs
    from pathlib import Path
    json_dir = Path(config.data_dir) / "json"
    fetched = len(list(json_dir.glob("*.json"))) if json_dir.exists() else 0

    console.print("[bold]Legalize pipeline status[/bold]\n")
    console.print(f"  Downloaded norms (data/): {fetched}")
    console.print(f"  Committed norms: {state.normas_count}")
    console.print(f"  Registered mappings: {len(mappings)}")
    console.print(f"  Last processed summary: {state.ultimo_sumario or '[dim]none[/dim]'}")
