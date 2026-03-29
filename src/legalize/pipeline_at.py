"""Austria pipeline — fetch, parse and bootstrap from the RIS OGD API.

Data source: https://data.bka.gv.at/ris/api/v2.6/
License: CC BY 4.0 (OGD Austria — https://www.data.gv.at)

Flow:
  1. fetch-at --discover     -> RISDiscovery paginates all Gesetzesnummern
  2. fetch-at GESNR          -> RISClient fetches NOR XMLs, parses, saves JSON
  3. commit --all             -> pipeline.commit_all() (generic, reads JSON)
  4. ingest                   -> web.ingest (generic, JSON -> DB)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from rich.console import Console

from legalize.config import Config
from legalize.fetcher.client_ris import RISClient
from legalize.fetcher.discovery_ris import RISDiscovery
from legalize.fetcher.parser_ris import RISMetadataParser, RISTextParser
from legalize.models import NormaCompleta
from legalize.storage import save_structured_json

console = Console()
logger = logging.getLogger(__name__)

_text_parser = RISTextParser()
_meta_parser = RISMetadataParser()


def fetch_one_at(config: Config, gesetzesnummer: str, force: bool = False) -> NormaCompleta | None:
    """Download and parse ONE Austrian law (all its NOR paragraphs).

    Fetches metadata JSON + individual NOR XMLs, parses into NormaCompleta,
    saves to data/json/AT-{gesetzesnummer}.json.
    """
    norm_id = f"AT-{gesetzesnummer}"
    json_path = Path(config.data_dir) / "json" / f"{norm_id}.json"
    if json_path.exists() and not force:
        console.print(f"  [dim]{norm_id} already processed, skipping[/dim]")
        return _load_norma_from_json(json_path)

    with RISClient() as client:
        try:
            console.print(f"  Processing [bold]{norm_id}[/bold]...")

            # Metadata from API (also contains all NOR references)
            meta_json = client.get_metadatos(gesetzesnummer)
            metadata = _meta_parser.parse(meta_json, gesetzesnummer)

            # Fetch individual NOR paragraph XMLs
            api_data = json.loads(meta_json)
            refs = api_data["OgdSearchResult"]["OgdDocumentResults"].get("OgdDocumentReference", [])
            if isinstance(refs, dict):
                refs = [refs]

            all_bloques = []
            all_reforms = []

            for ref in refs:
                brkons = ref["Data"]["Metadaten"]["Bundesrecht"]["BrKons"]
                if brkons.get("Dokumenttyp") == "Norm":
                    continue  # header doc — no content XML
                nor_id = ref["Data"]["Metadaten"]["Technisch"]["ID"]
                try:
                    xml_bytes = client.get_texto(nor_id)
                    bloques = _text_parser.parse_texto(xml_bytes)
                    reforms = _text_parser.extract_reforms(xml_bytes)
                    all_bloques.extend(bloques)
                    all_reforms.extend(reforms)
                except Exception:
                    logger.warning("Failed to fetch NOR %s", nor_id)

            norma = NormaCompleta(
                metadata=metadata,
                bloques=tuple(all_bloques),
                reforms=tuple(all_reforms),
            )

            save_structured_json(config.data_dir, norma)

            console.print(
                f"  [green]✓[/green] {metadata.titulo_corto}: "
                f"{len(all_bloques)} Paragraphen, {len(all_reforms)} Änderungen"
            )
            return norma

        except Exception:
            logger.error("Error processing %s", gesetzesnummer, exc_info=True)
            console.print(f"  [red]✗ Error processing {gesetzesnummer}[/red]")
            return None


def discover_at(config: Config) -> list[str]:
    """Discover all Gesetzesnummern in the RIS Bundesrecht catalog."""
    console.print("[bold]Discover — scanning RIS API[/bold]\n")
    discovery = RISDiscovery()
    with RISClient() as client:
        norm_ids = list(discovery.discover_all(client))
    console.print(f"\n[bold green]✓ {len(norm_ids)} Gesetze discovered[/bold green]")
    return norm_ids


def fetch_all_at(config: Config, force: bool = False) -> list[str]:
    """Discover and fetch all Austrian laws from RIS."""
    norm_ids = discover_at(config)
    if not norm_ids:
        return []

    console.print(f"\n[bold]Fetch — processing {len(norm_ids)} Gesetze[/bold]\n")
    fetched = []
    errors = 0
    for i, gesnr in enumerate(norm_ids, 1):
        norma = fetch_one_at(config, gesnr, force=force)
        if norma is not None:
            fetched.append(gesnr)
        else:
            errors += 1
        if i % 50 == 0:
            console.print(f"  [dim][{i}/{len(norm_ids)}] {len(fetched)} OK, {errors} errors[/dim]")

    console.print(f"\n[bold green]✓ {len(fetched)} Gesetze processed[/bold green]")
    if errors:
        console.print(f"[yellow]⚠ {errors} errors[/yellow]")
    return fetched


def bootstrap_at(config: Config, dry_run: bool = False) -> int:
    """Full Austria bootstrap: discover + fetch + commit.

    1. Discover all Gesetzesnummern from the RIS API
    2. Fetch + parse each law (JSON + NOR XMLs)
    3. Generate commits in the legalize-at repo
    """
    from legalize.pipeline import commit_all

    console.print("[bold]Bootstrap Austria — RIS OGD API[/bold]\n")
    console.print("  API: https://data.bka.gv.at/ris/api/v2.6/")
    console.print(f"  Repo output: {config.git.repo_path}")
    console.print(f"  Data dir: {config.data_dir}\n")

    fetched = fetch_all_at(config, force=False)
    if not fetched:
        console.print("[yellow]No Gesetze fetched.[/yellow]")
        return 0

    console.print("\n[bold]Commit — generating git history[/bold]\n")
    total_commits = commit_all(config, dry_run=dry_run)

    console.print("\n[bold green]✓ Austria bootstrap completed[/bold green]")
    console.print(f"  {len(fetched)} Gesetze processed, {total_commits} commits created")
    return total_commits


def _load_norma_from_json(json_path: Path) -> NormaCompleta:
    from legalize.pipeline import _load_norma_from_json as _load
    return _load(json_path)
