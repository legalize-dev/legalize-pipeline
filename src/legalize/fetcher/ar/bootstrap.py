"""Argentina-specific bootstrap: full history via reform reconstruction.

Unlike the generic bootstrap (which emits one canonical snapshot per norm
plus whatever reforms the parser extracts from a single XML payload),
Argentina's bootstrap:

  1. Downloads the monthly InfoLEG catalog ZIPs (catalog + modifications graph).
  2. For each Tier 1 norm (Ley / Decreto / DNU with ``texto_actualizado``,
     plus the Constitución whitelist):
     - Parses ``norma.htm`` → bootstrap version (v0).
     - For each modificatoria in chronological order: fetches its
       ``norma.htm``, extracts substitutions/repeals/insertions via
       :mod:`legalize.fetcher.ar.reforms`, and applies them.
     - Verifies the final reconstructed state against ``texact.htm`` and
       appends a ``[consolidacion]`` commit if they differ.
  3. Commits every snapshot with ``GIT_AUTHOR_DATE`` = B.O. date of the
     modificatoria that produced it.

Parallelism: network-bound stage runs in a ThreadPoolExecutor (each worker
owns its own :class:`InfoLEGClient`). Commits run sequentially on the main
thread because :class:`GitRepo` is not thread-safe. 8 workers (``max_workers``
in config.yaml) is the benchmarked sweet spot: servicios.infoleg.gob.ar
advertises no rate limits to negotiate with, so the ceiling had to be measured
rather than read, and the only signal that it has been crossed is fetches that
start failing.

This module is discovered automatically by
:func:`legalize.pipeline.generic_bootstrap` via the optional
``fetcher/{country}/bootstrap.py`` hook.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from rich.console import Console

from legalize.committer.git_ops import GitRepo
from legalize.committer.message import build_commit_info
from legalize.config import Config
from legalize.fetcher.ar.catalog import InfoLEGCatalog, InfoLEGRow
from legalize.fetcher.ar.client import InfoLEGClient
from legalize.fetcher.ar.discovery import InfoLEGDiscovery
from legalize.fetcher.ar.parser import (
    InfoLEGMetadataParser,
    InfoLEGTextParser,
    count_content_images,
)
from legalize.fetcher.ar.reconstructor import (
    ReconstructionQuality,
    ReconstructionResult,
    reconstruct,
)
from legalize.models import CommitType, NormMetadata, Reform
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath

console = Console()
logger = logging.getLogger(__name__)


_DEFAULT_WORKERS = 8


@dataclass
class _PreparedLaw:
    """A norm with its reconstructed timeline, ready for sequential commit."""

    row: InfoLEGRow
    metadata: NormMetadata
    result: ReconstructionResult
    file_path: str
    # Pre-rendered markdown per snapshot (index-aligned with result.snapshots)
    rendered: list[str]
    error: str | None = None


def bootstrap(
    config: Config,
    dry_run: bool = False,
    limit: int | None = None,
    workers: int | None = None,
) -> int:
    """Argentina bootstrap: discovery → parallel reconstruct → sequential commits.

    Args:
        config: loaded :class:`Config`.
        dry_run: if True, print actions without committing.
        limit: only process the first N Tier 1 norms (useful for testing).
        workers: parallel HTTP workers. Defaults to ``max_workers`` in
            config.yaml; 8 was benchmarked safe on servicios.infoleg.gob.ar.

    Returns the total number of commits created.
    """
    cc = config.get_country("ar")
    if workers is None:
        workers = getattr(cc, "max_workers", _DEFAULT_WORKERS) or _DEFAULT_WORKERS

    console.print("[bold]Bootstrap AR — InfoLEG + per-modificatoria reconstruction[/bold]\n")
    console.print(f"  Data dir: {cc.data_dir}")
    console.print(f"  Repo output: {cc.repo_path}")
    console.print(f"  Parallel workers: {workers}\n")

    # 1. Discovery — load catalog and enumerate Tier 1
    console.print("  Loading InfoLEG catalog (downloads on first run)...")
    t0 = time.monotonic()
    with InfoLEGClient.create(cc) as client:
        catalog = client.ensure_catalog()
    console.print(
        f"  Loaded {len(catalog)} catalog rows "
        f"({sum(len(v) for v in catalog.modifications_of.values())} modification edges) "
        f"in {time.monotonic() - t0:.1f}s\n"
    )

    discovery = InfoLEGDiscovery.create(cc.source or {})
    target_ids: list[str] = []
    with InfoLEGClient.create(cc) as discovery_client:
        discovery_client._catalog = catalog  # reuse cached catalog
        target_ids = list(discovery.discover_all(discovery_client))

    if limit:
        target_ids = target_ids[:limit]
    console.print(f"  Tier 1 target norms: {len(target_ids)}\n")

    if not target_ids:
        console.print("[yellow]No Tier 1 norms found. Check the catalog filter.[/yellow]")
        return 0

    # 2. Initialize repo
    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    if not dry_run:
        repo.init()
        console.print("  Loading existing commits for idempotency...")
        t0 = time.monotonic()
        repo.load_existing_commits()
        existing = getattr(repo, "_existing_commits", set())
        console.print(
            f"  Loaded {len(existing)} existing (Source-Id, Norm-Id) pairs "
            f"in {time.monotonic() - t0:.1f}s\n"
        )

    # 3. Parallel reconstruction + sequential commit
    total_commits = 0
    quality_tally: dict[str, int] = {"clean": 0, "partial": 0, "bootstrap-only": 0}
    errors: list[str] = []
    processed = 0

    t0 = time.monotonic()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_prepare_one_law, cc, catalog, norm_id): norm_id for norm_id in target_ids
        }

        for future in as_completed(futures):
            norm_id = futures[future]
            processed += 1
            try:
                prepared = future.result()
            except Exception as exc:
                msg = f"{norm_id}: prepare failed: {type(exc).__name__}: {exc}"
                logger.error(msg, exc_info=True)
                errors.append(msg)
                continue

            if prepared.error:
                errors.append(f"{norm_id}: {prepared.error}")
                continue

            quality_tally[prepared.result.quality.value] += 1

            try:
                commits = _commit_prepared_law(repo, prepared, dry_run=dry_run)
                total_commits += commits
            except Exception as exc:
                msg = f"{norm_id}: commit failed: {type(exc).__name__}: {exc}"
                logger.error(msg, exc_info=True)
                errors.append(msg)

            if processed % 25 == 0:
                elapsed = time.monotonic() - t0
                rate = processed / elapsed
                eta = (len(target_ids) - processed) / rate if rate > 0 else 0
                console.print(
                    f"  [dim][{processed}/{len(target_ids)}] {total_commits} commits, "
                    f"{len(errors)} errors, {rate:.1f} laws/s, ETA {eta / 60:.0f} min[/dim]"
                )

    elapsed = time.monotonic() - t0
    console.print(
        f"\n[bold green]✓ Bootstrap AR finished[/bold green]\n"
        f"  {len(target_ids)} Tier 1 norms processed in {elapsed / 60:.1f} min\n"
        f"  {total_commits} commits created\n"
        f"  Reform quality: clean={quality_tally['clean']}  "
        f"partial={quality_tally['partial']}  "
        f"bootstrap-only={quality_tally['bootstrap-only']}\n"
        f"  {len(errors)} errors"
    )
    if errors:
        for e in errors[:5]:
            console.print(f"  [red]✗ {e}[/red]")
        if len(errors) > 5:
            console.print(f"  [red]... and {len(errors) - 5} more[/red]")
    return total_commits


def _prepare_one_law(cc, catalog: InfoLEGCatalog, norm_id: str) -> _PreparedLaw:
    """Runs in a worker thread: reconstructs the full timeline and pre-renders
    every snapshot's markdown. Does NOT touch git.

    Each worker owns its own :class:`InfoLEGClient` because ``requests.Session``
    is not thread-safe. The catalog is shared read-only.
    """
    text_parser = InfoLEGTextParser()
    meta_parser = InfoLEGMetadataParser()

    try:
        with InfoLEGClient.create(cc) as client:
            # Reuse the shared catalog cache (avoid re-parsing 241 MB per worker)
            client._catalog = catalog

            row = catalog.get(norm_id)
            if row is None:
                return _PreparedLaw(
                    row=None,  # type: ignore[arg-type]
                    metadata=None,  # type: ignore[arg-type]
                    result=ReconstructionResult(
                        quality=ReconstructionQuality.BOOTSTRAP_ONLY, snapshots=[]
                    ),
                    file_path="",
                    rendered=[],
                    error=f"norm {norm_id} not in catalog",
                )

            # Metadata from the catalog row (no HTTP)
            try:
                metadata_bytes = client.get_metadata(norm_id)
                metadata = meta_parser.parse(metadata_bytes, norm_id)
            except Exception as exc:
                return _PreparedLaw(
                    row=row,
                    metadata=None,  # type: ignore[arg-type]
                    result=ReconstructionResult(
                        quality=ReconstructionQuality.BOOTSTRAP_ONLY, snapshots=[]
                    ),
                    file_path="",
                    rendered=[],
                    error=f"metadata parse failed: {exc}",
                )

            # Reconstruction
            result = reconstruct(client, row, catalog, text_parser)

            # Enrich metadata with reconstruction quality + images_dropped flag.
            # We copy `extra` and dataclass-replace to stay immutable.
            try:
                img_count = count_content_images(client.get_text(norm_id))
            except Exception:
                img_count = 0
            extra = list(metadata.extra)
            extra.append(("reform_quality", result.quality.value))
            if result.skipped:
                extra.append(("reforms_skipped", str(result.skipped)))
            if result.applied:
                extra.append(("reforms_applied", str(result.applied)))
            if img_count > 0:
                extra.append(("images_dropped", str(img_count)))
                extra.append(("has_scanned_tables", "true"))
            from dataclasses import replace as dc_replace

            metadata = dc_replace(metadata, extra=tuple(extra))
            if not result.snapshots:
                return _PreparedLaw(
                    row=row,
                    metadata=metadata,
                    result=result,
                    file_path="",
                    rendered=[],
                    error="reconstruction produced zero snapshots",
                )

            file_path = norm_to_filepath(metadata)

            # Pre-render markdown per snapshot (worker thread, no git)
            rendered: list[str] = []
            for snap in result.snapshots:
                try:
                    md = render_norm_at_date(
                        metadata,
                        list(snap.blocks),
                        snap.commit_date,
                        include_all=True,
                    )
                    rendered.append(md)
                except Exception as exc:
                    logger.warning("render failed for %s @ %s: %s", norm_id, snap.commit_date, exc)
                    rendered.append("")

            return _PreparedLaw(
                row=row,
                metadata=metadata,
                result=result,
                file_path=file_path,
                rendered=rendered,
            )

    except Exception as exc:
        logger.error("Worker failed on %s", norm_id, exc_info=True)
        return _PreparedLaw(
            row=None,  # type: ignore[arg-type]
            metadata=None,  # type: ignore[arg-type]
            result=ReconstructionResult(quality=ReconstructionQuality.BOOTSTRAP_ONLY, snapshots=[]),
            file_path="",
            rendered=[],
            error=f"{type(exc).__name__}: {exc}",
        )


def _commit_prepared_law(
    repo: GitRepo,
    law: _PreparedLaw,
    *,
    dry_run: bool,
) -> int:
    """Commit all prepared snapshots of one norm. Main thread only."""
    if not law.result.snapshots or not law.metadata:
        return 0

    commits_created = 0

    # strict: a short `rendered` used to truncate silently, which drops a
    # version from a law's history and can only be repaired by reprocess.
    pairs = zip(law.result.snapshots, law.rendered, strict=True)
    for idx, (snap, markdown) in enumerate(pairs):
        if not markdown:
            continue

        is_first = idx == 0
        is_consolidation = snap.source_label == "consolidacion"

        if dry_run:
            label = "bootstrap" if is_first else "consolidacion" if is_consolidation else "reforma"
            console.print(
                f"    [dim]{snap.commit_date} [{label}] {snap.source_label} "
                f"({len(snap.blocks)} blocks)[/dim]"
            )
            continue

        # Idempotency: skip if we already have this (Source-Id, Norm-Id) pair
        if repo.has_commit_with_source_id(snap.source_id, law.metadata.identifier):
            continue

        changed = repo.write_and_add(law.file_path, markdown)
        if not changed and not is_first:
            continue

        if is_first:
            commit_type = CommitType.BOOTSTRAP
        elif is_consolidation:
            commit_type = CommitType.FIX_PIPELINE  # closest fit; "[consolidacion]"
        else:
            commit_type = CommitType.REFORM

        reform = Reform(
            date=snap.commit_date,
            norm_id=snap.source_id,
            affected_blocks=snap.affected_article_ids,
        )
        info = build_commit_info(
            commit_type,
            law.metadata,
            reform,
            list(snap.blocks),
            law.file_path,
            markdown,
        )
        sha = repo.commit(info)
        if sha:
            commits_created += 1

    return commits_created


__all__ = ["bootstrap"]
