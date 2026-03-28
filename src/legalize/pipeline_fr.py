"""France pipeline — fetch, commit and bootstrap from the LEGI database.

Uses the LEGI Open Data XML dump (ftp://echanges.dila.gouv.fr/LEGI/).
Commit and ingest reuse pipeline.py (already generic).

Flow:
  1. fetch-fr --discover     -> LEGIDiscovery scans 77 codes in force
  2. fetch-fr LEGITEXTXXX    -> LEGIClient builds combined XML, parses, saves JSON
  3. commit --all             -> pipeline.commit_all() (generic, reads JSON)
  4. ingest                   -> web.ingest (generic, JSON -> SQLite)
"""

from __future__ import annotations

import logging
from pathlib import Path

from rich.console import Console

from legalize.config import Config
from legalize.fetcher.client_legi import LEGIClient
from legalize.fetcher.discovery_legi import LEGIDiscovery
from legalize.fetcher.parser_legi import LEGIMetadataParser, LEGITextParser
from legalize.models import NormaCompleta
from legalize.storage import save_raw_xml, save_structured_json
from legalize.transformer.xml_parser import extract_reforms

console = Console()
logger = logging.getLogger(__name__)

_text_parser = LEGITextParser()
_meta_parser = LEGIMetadataParser()


def fetch_one_fr(config: Config, norm_id: str, force: bool = False) -> NormaCompleta | None:
    """Download and parse ONE LEGI text (code, constitution, law).

    Reads from local dump, builds combined XML, parses to NormaCompleta,
    saves to data/json/{norm_id}.json.
    """
    json_path = Path(config.data_dir) / "json" / f"{norm_id}.json"
    if json_path.exists() and not force:
        console.print(f"  [dim]{norm_id} already processed, skipping[/dim]")
        return _load_norma_from_json(json_path)

    legi_dir = config.legi_dir
    if not legi_dir:
        console.print("[red]Error: legi_dir not configured. Specify the path to the LEGI dump.[/red]")
        return None

    with LEGIClient(legi_dir) as client:
        try:
            console.print(f"  Processing [bold]{norm_id}[/bold]...")

            # Metadata (from structure file)
            meta_xml = client.get_metadatos(norm_id)
            metadata = _meta_parser.parse(meta_xml, norm_id)

            # Combined text (structure + inline articles)
            texto_xml = client.get_texto(norm_id)

            # Parse blocks and reforms
            bloques = _text_parser.parse_texto(texto_xml)
            reforms = extract_reforms(bloques)

            norma = NormaCompleta(
                metadata=metadata,
                bloques=tuple(bloques),
                reforms=tuple(reforms),
            )

            # Save combined XML and structured JSON
            save_raw_xml(config.data_dir, norm_id, texto_xml)
            save_structured_json(config.data_dir, norma)

            console.print(
                f"  [green]✓[/green] {metadata.titulo_corto}: "
                f"{len(bloques)} bloques, {len(reforms)} versiones"
            )
            return norma

        except FileNotFoundError:
            logger.error("File not found for %s in %s", norm_id, legi_dir)
            console.print(f"  [red]✗ {norm_id} — file not found in dump[/red]")
            return None
        except Exception:
            logger.error("Error processing %s", norm_id, exc_info=True)
            console.print(f"  [red]✗ Error processing {norm_id}[/red]")
            return None


def discover_fr(config: Config) -> list[str]:
    """Discover all codes in force from the LEGI dump.

    Scans texte/struct/ looking for LEGITEXT with NATURE=CODE|CONSTITUTION
    and ETAT=VIGUEUR.
    """
    legi_dir = config.legi_dir
    if not legi_dir:
        console.print("[red]Error: legi_dir not configured.[/red]")
        return []

    console.print("[bold]Discover — scanning LEGI dump[/bold]\n")
    discovery = LEGIDiscovery(legi_dir)

    # The client is not actually used (local read), but the interface requires it
    with LEGIClient(legi_dir) as client:
        norm_ids = list(discovery.discover_all(client))

    console.print(f"\n[bold green]✓ {len(norm_ids)} texts discovered[/bold green]")
    return norm_ids


def fetch_all_fr(config: Config, force: bool = False) -> list[str]:
    """Discover and process all codes in force from the LEGI dump."""
    norm_ids = discover_fr(config)
    if not norm_ids:
        return []

    console.print(f"\n[bold]Fetch — processing {len(norm_ids)} LEGI texts[/bold]\n")

    fetched = []
    errors = 0
    for i, norm_id in enumerate(norm_ids, 1):
        norma = fetch_one_fr(config, norm_id, force=force)
        if norma is not None:
            fetched.append(norm_id)
        else:
            errors += 1

        if i % 10 == 0:
            console.print(
                f"  [dim][{i}/{len(norm_ids)}] {len(fetched)} OK, {errors} errors[/dim]"
            )

    console.print(f"\n[bold green]✓ {len(fetched)} texts processed[/bold green]")
    if errors:
        console.print(f"[yellow]⚠ {errors} errors[/yellow]")

    return fetched


def bootstrap_fr(config: Config, dry_run: bool = False) -> int:
    """Full France bootstrap: discover + fetch + commit.

    1. Discover the 77 codes in force from the LEGI dump
    2. Process each one (XML -> JSON)
    3. Generate commits in the legalize-fr repo
    """
    from legalize.pipeline import commit_all

    console.print("[bold]Bootstrap France — LEGI Open Data[/bold]\n")
    console.print(f"  Dump LEGI: {config.legi_dir}")
    console.print(f"  Repo output: {config.git.repo_path}")
    console.print(f"  Data dir: {config.data_dir}\n")

    # Phase 1: Fetch
    fetched = fetch_all_fr(config, force=False)
    if not fetched:
        console.print("[yellow]No texts found. Is the LEGI dump extracted?[/yellow]")
        return 0

    # Phase 2: Commit (reuses generic pipeline)
    console.print("\n[bold]Commit — generating git history[/bold]\n")
    total_commits = commit_all(config, dry_run=dry_run)

    console.print("\n[bold green]✓ France bootstrap completed[/bold green]")
    console.print(f"  {len(fetched)} texts processed, {total_commits} commits created")

    return total_commits


# ─────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────


def _load_norma_from_json(json_path: Path) -> NormaCompleta:
    """Reuses the generic loader from pipeline.py."""
    from legalize.pipeline import _load_norma_from_json as _load
    return _load(json_path)
