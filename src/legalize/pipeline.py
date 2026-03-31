"""Legalize pipeline orchestrator.

Generic (country-agnostic) flows:
- generic_fetch_one: fetch one norm for any country via dispatch
- generic_fetch_all: fetch all norms for any country via discovery
- generic_bootstrap: full bootstrap for any country
- commit_one: generate commits for one law from local data
- commit_all: generate commits for all laws in data/
- reprocess: re-download and regenerate specific norms
- bootstrap_from_local_xml: bootstrap from local XML (tests/pilot)
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import requests

from rich.console import Console

from legalize.committer.git_ops import GitRepo
from legalize.committer.message import build_commit_info
from legalize.config import Config
from legalize.models import (
    CommitType,
    NormaCompleta,
    NormaMetadata,
)
from legalize.state.mappings import IdToFilename
from legalize.state.store import StateStore
from legalize.storage import load_norma_from_json, save_raw_xml, save_structured_json
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath
from legalize.transformer.xml_parser import extract_reforms, parse_text_xml

console = Console()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# GENERIC FETCH — works for any country via dispatch
# ─────────────────────────────────────────────


def generic_fetch_one(
    config: Config,
    country: str,
    norm_id: str,
    force: bool = False,
) -> NormaCompleta | None:
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

            text_data = client.get_text(norm_id)
            blocks = text_parser.parse_text(text_data)
            reforms = _extract_reforms_generic(text_parser, client, norm_id, blocks)

            norm = NormaCompleta(
                metadata=metadata,
                bloques=tuple(blocks),
                reforms=tuple(reforms),
            )

            save_structured_json(cc.data_dir, norm)

            console.print(
                f"  [green]✓[/green] {metadata.titulo_corto}: "
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
    """
    from legalize.countries import get_client_class, get_discovery_class

    cc = config.get_country(country)
    client_cls = get_client_class(country)
    discovery_cls = get_discovery_class(country)

    # Discover all norm IDs
    with client_cls.create(cc) as client:
        discovery = discovery_cls(cc.source["legi_dir"])
        norm_ids = list(discovery.discover_all(client))

    if limit:
        norm_ids = norm_ids[:limit]

    console.print(f"[bold]Fetch — {len(norm_ids)} norms for {country.upper()}[/bold]\n")

    fetched = []
    errors = 0
    for i, norm_id in enumerate(norm_ids, 1):
        norm = generic_fetch_one(config, country, norm_id, force=force)
        if norm is not None:
            fetched.append(norm_id)
        else:
            errors += 1

        if i % 50 == 0:
            console.print(f"  [dim][{i}/{len(norm_ids)}] {len(fetched)} OK, {errors} errors[/dim]")

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
    """Full bootstrap for any country: discover + fetch + commit."""
    cc = config.get_country(country)

    console.print(f"[bold]Bootstrap {country.upper()}[/bold]\n")
    console.print(f"  Data dir: {cc.data_dir}")
    console.print(f"  Repo output: {cc.repo_path}\n")

    fetched = generic_fetch_all(config, country, force=False, limit=limit)
    if not fetched:
        console.print("[yellow]No norms found.[/yellow]")
        return 0

    console.print("\n[bold]Commit — generating git history[/bold]\n")
    total_commits = commit_all(config, country, dry_run=dry_run)

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
    blocks = norm.bloques
    reforms = norm.reforms

    logger.info("Committing %s: %d reforms", norm_id, len(reforms))
    console.print(
        f"  [bold]{metadata.titulo_corto}[/bold]: {len(blocks)} blocks, {len(reforms)} versions"
    )

    if dry_run:
        for reform in reforms:
            is_first = reform == reforms[0]
            label = "bootstrap" if is_first else "reforma"
            console.print(f"    [dim]{reform.fecha} [{label}][/dim]")
        return 0

    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    repo.init()

    mappings = IdToFilename(cc.mappings_path)
    mappings.load()

    commits_created = 0
    file_path = norm_to_filepath(metadata)

    for reform in reforms:
        # Idempotency check: Source-Id + Norm-Id (a single Source-Id can be both its own norm AND a reform of another)
        if repo.has_commit_with_source_id(reform.id_norma, metadata.identificador):
            continue

        is_first = reform == reforms[0]
        commit_type = CommitType.BOOTSTRAP if is_first else CommitType.REFORMA

        markdown = render_norm_at_date(metadata, blocks, reform.fecha, include_all=is_first)
        changed = repo.write_and_add(file_path, markdown)

        if not changed and not is_first:
            continue

        info = build_commit_info(commit_type, metadata, reform, blocks, file_path, markdown)
        sha = repo.commit(info)

        if sha:
            commits_created += 1
            console.print(f"    [green]✓[/green] {reform.fecha} — {info.subject}")

    mappings.set(metadata.identificador, file_path)
    mappings.save()

    return commits_created


def commit_all(config: Config, country: str, dry_run: bool = False) -> int:
    """Generate commits for ALL laws in data/json/.

    Processes each law independently — does not interleave commits.
    """
    cc = config.get_country(country)
    json_dir = Path(cc.data_dir) / "json"
    if not json_dir.exists():
        console.print("[red]No data in data/json/. Run fetch first.[/red]")
        return 0

    json_files = sorted(json_dir.glob("*.json"))
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

            if not dry_run and commits > 0:
                norm = load_norma_from_json(json_file)
                if norm.reforms:
                    state.mark_norma_processed(
                        norm.metadata.identificador,
                        norm.reforms[-1].fecha,
                        len(norm.reforms),
                    )
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
    metadata: NormaMetadata,
    xml_path: str | Path,
    country: str = "es",
    dry_run: bool = False,
) -> int:
    """Bootstrap from a local XML (pilot/tests)."""
    cc = config.get_country(country)
    xml_bytes = Path(xml_path).read_bytes()
    blocks = parse_text_xml(xml_bytes)
    reforms = extract_reforms(blocks)

    norm = NormaCompleta(
        metadata=metadata,
        bloques=tuple(blocks),
        reforms=tuple(reforms),
    )

    save_raw_xml(cc.data_dir, metadata.identificador, xml_bytes)
    save_structured_json(cc.data_dir, norm)

    return commit_one(config, country, metadata.identificador, dry_run=dry_run)
