"""Daily incremental update for Argentina (InfoLEG).

InfoLEG publishes a new catalog CSV monthly (not daily).
This flow compares last_updated from the catalog against
the JSON data on disk and re-fetches any stale norm.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Optional

from rich.console import Console

from legalize.committer.git_ops import GitRepo
from legalize.committer.message import build_commit_info
from legalize.config import Config
from legalize.models import CommitType, ParsedNorm, Reform
from legalize.pipeline import _extract_reforms_generic, finalize_daily
from legalize.state.store import StateStore
from legalize.storage import load_norma_from_json, save_structured_json
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath

console = Console()
logger = logging.getLogger(__name__)


def daily(
    config: Config,
    target_date: Optional[date] = None,
    dry_run: bool = False,
) -> int:
    """Re-fetch Argentine norms whose catalog last_updated is newer than the local JSON."""
    from legalize.countries import get_metadata_parser, get_text_parser
    from legalize.fetcher.ar.catalog import load_catalog
    from legalize.fetcher.ar.client import InfoLEGClient

    cc = config.get_country("ar")
    state = StateStore(cc.state_path)
    state.load()

    today = target_date or date.today()

    # ── Load catalog to find stale norms ──────────────────────────────────────
    data_dir = Path(cc.data_dir)
    catalog_zip = data_dir / "catalog" / "base-infoleg-normativa-nacional.zip"
    mods_zip = data_dir / "catalog" / "base-complementaria-infoleg-normas-modificadas.zip"

    if not catalog_zip.exists():
        console.print(f"[red]Catalog not found at {catalog_zip}[/red]")
        console.print("Run: legalize fetch -c ar --all  (or download the ZIP manually)")
        return 0

    catalog = load_catalog(
        catalog_zip,
        modifications_path=mods_zip if mods_zip.exists() else None,
    )
    console.print(f"[dim]Catalog loaded: {len(catalog)} norms[/dim]")

    # ── Find norms whose catalog date is newer than the local JSON ────────────
    json_dir = data_dir / "json"
    stale: list[tuple[str, str]] = []  # (norm_id_slug, infoleg_id)

    for row in catalog.by_id.values():
        if not row.has_consolidated_text and not row.has_original_text:
            continue  # skip norms with no text at all

        # Build the slug as the pipeline uses it (tipo_norma + numero_norma)
        norm_slug = f"{row.tipo_norma.upper()}-{row.numero_norma}"
        json_path = json_dir / f"{norm_slug}.json"

        if not json_path.exists():
            continue  # not yet fetched; bootstrap handles initial fetch

        # Compare dates
        edges = catalog.reforms_for(row.id_norma)
        if edges:
            catalog_date = edges[-1].fecha_boletin  # last modification
        else:
            catalog_date = row.fecha_boletin
        if catalog_date is None:
            continue

        try:
            norm = load_norma_from_json(json_path)
            json_date = norm.metadata.last_modified
            if json_date is None or catalog_date > json_date:
                stale.append((norm_slug, row.id_norma))
        except Exception:
            logger.warning("Could not read %s, skipping", json_path, exc_info=True)

    if not stale:
        console.print("[green]AR daily — nothing to update[/green]")
        return finalize_daily(
            GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email),
            state, [today], 0, [],
            dry_run=dry_run, push=config.git.push,
        )

    console.print(f"[bold]AR daily — {len(stale)} stale norm(s) to re-fetch[/bold]")

    if dry_run:
        for norm_slug, infoleg_id in stale[:20]:
            console.print(f"  [dim]{norm_slug} (id={infoleg_id}) — would re-fetch[/dim]")
        if len(stale) > 20:
            console.print(f"  [dim]... and {len(stale) - 20} more[/dim]")
        return len(stale)

    # ── Re-fetch and re-commit each stale norm ────────────────────────────────
    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    text_parser = get_text_parser("ar")
    meta_parser = get_metadata_parser("ar")

    commits_created = 0
    errors: list[str] = []

    with InfoLEGClient.create(cc) as client:
        for norm_slug, infoleg_id in stale:
            try:
                console.print(f"  Processing [bold]{norm_slug}[/bold] (id={infoleg_id})...")

                # 1. Re-fetch metadata + consolidated text from InfoLEG
                meta_data = client.get_metadata(infoleg_id)
                metadata = meta_parser.parse(meta_data, norm_slug)

                text_data = client.get_text(infoleg_id)
                blocks = list(text_parser.parse_text(text_data))

                # 2. Reconstruct historical versions from modificatorias
                reforms = _extract_reforms_generic(
                    text_parser, client, infoleg_id, blocks, text_data
                )

                # 3. Persist updated JSON
                norm = ParsedNorm(
                    metadata=metadata,
                    blocks=tuple(blocks),
                    reforms=tuple(reforms),
                )
                save_structured_json(cc.data_dir, norm)

                # 4. Render markdown at today's date and commit if changed
                file_path = norm_to_filepath(metadata)
                markdown = render_norm_at_date(metadata, blocks, today)
                changed = repo.write_and_add(file_path, markdown)

                if not changed:
                    console.print(
                        f"  [dim]⏭ {norm_slug} — re-fetched but text unchanged[/dim]"
                    )
                    continue

                reform = Reform(
                    date=today,
                    norm_id=f"AR-DAILY-{today.isoformat()}-{norm_slug}",
                    affected_blocks=(),
                )
                info = build_commit_info(
                    CommitType.REFORM, metadata, reform, blocks, file_path, markdown
                )
                sha = repo.commit(info)
                if sha:
                    commits_created += 1
                    console.print(f"  [green]✓[/green] {info.subject}")

            except Exception as e:
                msg = f"Error updating {norm_slug}: {e}"
                logger.error(msg, exc_info=True)
                errors.append(msg)

    return finalize_daily(
        repo, state, [today], commits_created, errors,
        dry_run=dry_run, push=config.git.push,
    )