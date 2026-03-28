"""Legalize pipeline orchestrator.

Incremental flows:
- fetch: download XML+JSON of one or more laws to data/ (does not touch git)
- commit: read JSON from data/ and generate commits for one or more laws (does not download anything)
- bootstrap: fetch --all + commit --all (shortcut)
- daily: process daily summary, incremental
- reprocess: re-download and regenerate a specific law
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from rich.console import Console

from legalize.committer.git_ops import GitRepo
from legalize.committer.message import build_commit_info
from legalize.config import Config
from legalize.models import (
    CommitType,
    NormaCompleta,
    NormaMetadata,
    Reform,
)
from legalize.state.mappings import IdToFilename
from legalize.state.store import StateStore
from legalize.storage import save_raw_xml, save_structured_json
from legalize.transformer.markdown import render_norma_at_date
from legalize.transformer.slug import norma_to_filepath
from legalize.transformer.xml_parser import extract_reforms, parse_texto_xml

console = Console()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# FETCH — download data from the API, does not touch git
# ─────────────────────────────────────────────


def fetch_one(config: Config, boe_id: str, force: bool = False) -> NormaCompleta | None:
    """Download XML + metadata of a law and save to data/.

    If already exists in data/ and force=False, does not re-download.
    Returns NormaCompleta or None on error.
    """
    from legalize.fetcher.cache import FileCache
    from legalize.fetcher.client import BOEClient
    from legalize.transformer.metadata import parse_metadatos

    json_path = Path(config.data_dir) / "json" / f"{boe_id}.json"
    if json_path.exists() and not force:
        console.print(f"  [dim]{boe_id} already downloaded, skipping[/dim]")
        return _load_norma_from_json(json_path)

    cache = FileCache(config.cache_dir)
    with BOEClient(config.boe, cache) as client:
        try:
            console.print(f"  Downloading [bold]{boe_id}[/bold]...")
            meta_xml = client.get_metadatos(boe_id)
            metadata = parse_metadatos(meta_xml, boe_id)
            texto_xml = client.get_texto_consolidado(boe_id, bypass_cache=force)

            bloques = parse_texto_xml(texto_xml)
            reforms = extract_reforms(bloques)

            norma = NormaCompleta(
                metadata=metadata,
                bloques=tuple(bloques),
                reforms=tuple(reforms),
            )

            save_raw_xml(config.data_dir, boe_id, texto_xml)
            save_structured_json(config.data_dir, norma)

            console.print(
                f"  [green]✓[/green] {metadata.titulo_corto}: "
                f"{len(bloques)} bloques, {len(reforms)} versiones"
            )
            return norma

        except Exception:
            logger.error("Error downloading %s", boe_id, exc_info=True)
            console.print(f"  [red]✗ Error downloading {boe_id}[/red]")
            return None


def fetch_all(config: Config, force: bool = False) -> list[str]:
    """Download all norms from config.normas_fijas.

    Returns list of successfully downloaded BOE-IDs.
    """
    console.print("[bold]Fetch — downloading norms from BOE[/bold]\n")
    fetched = []
    for boe_id in config.scope.normas_fijas:
        norma = fetch_one(config, boe_id, force=force)
        if norma is not None:
            fetched.append(boe_id)
    console.print(f"\n[bold green]✓ {len(fetched)} norms downloaded[/bold green]")
    return fetched


def fetch_catalog(config: Config, force: bool = False) -> list[str]:
    """Download ALL state-level norms from the BOE catalog.

    Paginates correctly (the API has a 10,000 per request limit).
    Downloads all state-level norms, regardless of rango.
    Skips those already in data/.
    """
    import requests

    console.print("[bold]Fetch catalog — downloading full BOE catalog[/bold]\n")

    # Paginate full catalog
    base_url = f"{config.boe.base_url}/api/legislacion-consolidada"
    all_items: list[dict] = []
    offset = 0
    batch = 1000

    console.print("  Querying catalog (paginated)...")
    while True:
        resp = requests.get(
            base_url,
            headers={"Accept": "application/json"},
            params={"limit": batch, "offset": offset},
            timeout=60,
        )
        resp.raise_for_status()
        items = resp.json().get("data", [])
        if not items:
            break
        all_items.extend(items)
        offset += batch

    # Filter state-level only
    in_scope = [
        item["identificador"]
        for item in all_items
        if item.get("ambito", {}).get("codigo") == "1"
    ]

    console.print(f"  {len(in_scope)} state-level norms found\n")

    # Download each one (skips those that already exist)
    fetched = []
    errors = 0
    skipped = 0
    for i, boe_id in enumerate(in_scope, 1):
        json_path = Path(config.data_dir) / "json" / f"{boe_id}.json"
        if json_path.exists() and not force:
            skipped += 1
            continue

        norma = fetch_one(config, boe_id, force=force)
        if norma is not None:
            fetched.append(boe_id)
        else:
            errors += 1

        # Progress every 100
        if (len(fetched) + errors) % 100 == 0:
            console.print(
                f"  [{i}/{len(in_scope)}] {len(fetched)} new, "
                f"{skipped} existing, {errors} errors"
            )

    console.print(f"\n[bold green]✓ {len(fetched)} new norms downloaded[/bold green]")
    console.print(f"  {skipped} already existed, {errors} errors")

    total = len(list((Path(config.data_dir) / "json").glob("*.json")))
    console.print(f"  Total in data/: {total} norms")

    return fetched


# ─────────────────────────────────────────────
# COMMIT — generate git commits from local data/
# ─────────────────────────────────────────────


def commit_one(config: Config, boe_id: str, dry_run: bool = False) -> int:
    """Generate commits for ONE law from its JSON in data/.

    Does not download anything. Reads data/json/{boe_id}.json.
    Commits for this law are added to the repo without touching other laws.

    Returns number of commits created.
    """
    json_path = Path(config.data_dir) / "json" / f"{boe_id}.json"
    if not json_path.exists():
        console.print(f"  [red]{json_path} does not exist. Run fetch first.[/red]")
        return 0

    norma = _load_norma_from_json(json_path)
    metadata = norma.metadata
    bloques = norma.bloques
    reforms = norma.reforms

    console.print(
        f"  [bold]{metadata.titulo_corto}[/bold]: "
        f"{len(bloques)} bloques, {len(reforms)} versiones"
    )

    if dry_run:
        for reform in reforms:
            is_first = reform == reforms[0]
            tipo = "bootstrap" if is_first else "reforma"
            console.print(f"    [dim]{reform.fecha} [{tipo}][/dim]")
        return 0

    repo = GitRepo(config.git.repo_path, config.git.committer_name, config.git.committer_email)
    repo.init()

    mappings = IdToFilename(config.mappings_path)
    mappings.load()

    commits_created = 0
    file_path = norma_to_filepath(metadata)

    for reform in reforms:
        # Idempotency: Source-Id + Norm-Id (a single Source-Id can be both its own norm AND a reform of another)
        if repo.has_commit_with_source_id(reform.id_norma, metadata.identificador):
            continue

        is_first = reform == reforms[0]
        commit_type = CommitType.BOOTSTRAP if is_first else CommitType.REFORMA

        markdown = render_norma_at_date(metadata, bloques, reform.fecha)
        changed = repo.write_and_add(file_path, markdown)

        if not changed and not is_first:
            continue

        info = build_commit_info(commit_type, metadata, reform, bloques, file_path, markdown)
        sha = repo.commit(info)

        if sha:
            commits_created += 1
            console.print(f"    [green]✓[/green] {reform.fecha} — {info.subject}")

    mappings.set(metadata.identificador, file_path)
    mappings.save()

    return commits_created


def commit_all(config: Config, dry_run: bool = False) -> int:
    """Generate commits for ALL laws in data/json/.

    Processes each law independently — does not interleave commits.
    """
    json_dir = Path(config.data_dir) / "json"
    if not json_dir.exists():
        console.print("[red]No data in data/json/. Run fetch first.[/red]")
        return 0

    json_files = sorted(json_dir.glob("*.json"))
    console.print(f"[bold]Commit — generating commits for {len(json_files)} laws[/bold]\n")

    state = StateStore(config.state_path)
    state.load()

    total = 0
    errors = 0
    for i, json_file in enumerate(json_files, 1):
        boe_id = json_file.stem
        try:
            commits = commit_one(config, boe_id, dry_run=dry_run)
            total += commits

            if not dry_run and commits > 0:
                norma = _load_norma_from_json(json_file)
                if norma.reforms:
                    state.mark_norma_processed(
                        norma.metadata.identificador,
                        norma.reforms[-1].fecha,
                        len(norma.reforms),
                    )
        except Exception:
            errors += 1
            logger.error("Error committing %s, continuing", boe_id, exc_info=True)
            console.print(f"  [red]✗ {boe_id} — error, continuing[/red]")

        # Save state periodically (every 50 laws)
        if not dry_run and i % 50 == 0:
            state.record_run(commits=total)
            state.save()
            console.print(f"  [dim][{i}/{len(json_files)}] {total} commits, {errors} errors[/dim]")

    if not dry_run:
        state.record_run(commits=total)
        state.save()

    console.print(f"\n[bold green]✓ {total} commits created[/bold green]")

    repo = GitRepo(config.git.repo_path, config.git.committer_name, config.git.committer_email)
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
# BOOTSTRAP — shortcut: fetch all + commit all
# ─────────────────────────────────────────────


def bootstrap(config: Config, dry_run: bool = False) -> int:
    """Fetch + commit all norms in config."""
    fetch_all(config)
    return commit_all(config, dry_run=dry_run)


def bootstrap_from_local_xml(
    config: Config,
    metadata: NormaMetadata,
    xml_path: str | Path,
    dry_run: bool = False,
) -> int:
    """Bootstrap from a local XML (pilot/tests)."""
    xml_bytes = Path(xml_path).read_bytes()
    bloques = parse_texto_xml(xml_bytes)
    reforms = extract_reforms(bloques)

    norma = NormaCompleta(
        metadata=metadata,
        bloques=tuple(bloques),
        reforms=tuple(reforms),
    )

    save_raw_xml(config.data_dir, metadata.identificador, xml_bytes)
    save_structured_json(config.data_dir, norma)

    return commit_one(config, metadata.identificador, dry_run=dry_run)


# ─────────────────────────────────────────────
# DAILY — incremental, new reforms only
# ─────────────────────────────────────────────


def daily(
    config: Config,
    target_date: date | None = None,
    dry_run: bool = False,
) -> int:
    """Daily processing: process BOE summary/summaries."""
    from datetime import timedelta

    from legalize.fetcher.cache import FileCache
    from legalize.fetcher.client import BOEClient
    from legalize.fetcher.sumario import parse_sumario
    from legalize.transformer.metadata import parse_metadatos

    cache = FileCache(config.cache_dir)
    state = StateStore(config.state_path)
    state.load()
    mappings = IdToFilename(config.mappings_path)
    mappings.load()

    if target_date:
        dates_to_process = [target_date]
    else:
        start = state.ultimo_sumario
        if start is None:
            console.print("[yellow]No last summary found. Use --date or run bootstrap.[/yellow]")
            return 0
        start = start + timedelta(days=1)
        end = date.today()
        dates_to_process = []
        current = start
        while current <= end:
            if current.weekday() != 6:
                dates_to_process.append(current)
            current += timedelta(days=1)

    if not dates_to_process:
        console.print("[green]Nothing to process — up to date[/green]")
        return 0

    console.print(f"[bold]Daily — processing {len(dates_to_process)} day(s)[/bold]")

    repo = GitRepo(config.git.repo_path, config.git.committer_name, config.git.committer_email)
    commits_created = 0
    errores: list[str] = []

    with BOEClient(config.boe, cache) as client:
        for fecha in dates_to_process:
            console.print(f"\n  [bold]{fecha}[/bold]")

            try:
                xml_data = client.get_sumario(fecha)
                dispositions = parse_sumario(xml_data, config.scope)
            except Exception:
                msg = f"Error fetching summary for {fecha}"
                logger.error(msg, exc_info=True)
                errores.append(msg)
                continue

            if not dispositions:
                console.print("    No dispositions in scope")
                continue

            console.print(f"    {len(dispositions)} dispositions in scope")

            for disp in dispositions:
                if dry_run:
                    console.print(f"    [dim]{disp.id_boe} — {disp.titulo[:60]}...[/dim]")
                    continue

                try:
                    meta_xml = client.get_metadatos(disp.id_boe)
                    metadata = parse_metadatos(meta_xml, disp.id_boe)
                    texto_xml = client.get_texto_consolidado(metadata.identificador)
                    bloques = parse_texto_xml(texto_xml)

                    file_path = norma_to_filepath(metadata)
                    markdown = render_norma_at_date(metadata, bloques, fecha)

                    if repo.has_commit_with_source_id(disp.id_boe):
                        continue

                    changed = repo.write_and_add(file_path, markdown)
                    if not changed:
                        continue

                    if disp.es_correccion:
                        commit_type = CommitType.CORRECCION
                    elif disp.es_nueva:
                        commit_type = CommitType.NUEVA
                    else:
                        commit_type = CommitType.REFORMA

                    reform = Reform(fecha=fecha, id_norma=disp.id_boe, bloques_afectados=())
                    info = build_commit_info(
                        commit_type, metadata, reform, bloques, file_path, markdown
                    )
                    sha = repo.commit(info)

                    if sha:
                        commits_created += 1
                        console.print(f"    [green]✓[/green] {info.subject}")

                    mappings.set(metadata.identificador, file_path)

                except Exception:
                    msg = f"Error processing {disp.id_boe}"
                    logger.error(msg, exc_info=True)
                    errores.append(msg)

            state.ultimo_sumario = fecha

    if not dry_run and config.git.push and commits_created > 0:
        try:
            repo.push(branch=config.git.branch)
        except Exception:
            logger.error("Error pushing", exc_info=True)
            errores.append("Error pushing")

    state.record_run(
        sumarios=[d.isoformat() for d in dates_to_process],
        commits=commits_created,
        errores=errores,
    )
    state.save()
    mappings.save()

    console.print(f"\n[bold green]✓ {commits_created} commits[/bold green]")
    if errores:
        console.print(f"[yellow]⚠ {len(errores)} errores[/yellow]")

    return commits_created


# ─────────────────────────────────────────────
# REPROCESS — re-download and regenerate a law
# ─────────────────────────────────────────────


def reprocess(
    config: Config,
    boe_ids: list[str],
    reason: str,
    dry_run: bool = False,
) -> int:
    """Re-download and regenerate specific norms as [fix-pipeline]."""
    console.print(f"[bold]Reprocess — {reason}[/bold]\n")
    commits = 0
    for boe_id in boe_ids:
        fetch_one(config, boe_id, force=True)
        # TODO: commit como fix-pipeline en vez de bootstrap/reforma
        commits += commit_one(config, boe_id, dry_run=dry_run)
    return commits


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def _load_norma_from_json(json_path: Path) -> NormaCompleta:
    """Load a NormaCompleta from a JSON in data/."""
    from legalize.models import (
        Bloque,
        EstadoNorma,
        Paragraph,
        Rango,
        Version,
    )

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    meta = data["metadata"]
    metadata = NormaMetadata(
        titulo=meta["titulo"],
        titulo_corto=meta["titulo_corto"],
        identificador=meta["identificador"],
        pais=meta["pais"],
        rango=Rango(meta["rango"]),
        fecha_publicacion=date.fromisoformat(meta["fecha_publicacion"]),
        estado=EstadoNorma(meta["estado"]),
        departamento=meta["departamento"],
        fuente=meta["fuente"],
        fecha_ultima_modificacion=date.fromisoformat(meta["ultima_actualizacion"]),
    )

    bloques = []
    for art in data["articles"]:
        versions = []
        for v in art["versions"]:
            # Reconstruct paragraphs from text
            paragraphs = []
            if v["text"].strip():
                for line in v["text"].split("\n\n"):
                    if line.strip():
                        paragraphs.append(Paragraph(css_class="parrafo", text=line.strip()))
            versions.append(Version(
                id_norma=v["source_id"],
                fecha_publicacion=date.fromisoformat(v["date"]),
                fecha_vigencia=date.fromisoformat(v["date"]),
                paragraphs=tuple(paragraphs),
            ))
        bloques.append(Bloque(
            id=art["block_id"],
            tipo=art["block_type"],
            titulo=art["title"],
            versions=tuple(versions),
        ))

    reforms = []
    for r in data["reforms"]:
        reforms.append(Reform(
            fecha=date.fromisoformat(r["date"]),
            id_norma=r["source_id"],
            bloques_afectados=tuple(
                art["block_id"]
                for art in data["articles"]
                for v in art["versions"]
                if v["source_id"] == r["source_id"]
                and v["date"] == r["date"]
            ),
        ))

    return NormaCompleta(
        metadata=metadata,
        bloques=tuple(bloques),
        reforms=tuple(reforms),
    )
