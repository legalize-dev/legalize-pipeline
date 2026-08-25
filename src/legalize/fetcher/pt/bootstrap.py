"""Portugal bootstrap: two surfaces, and the order between them is the corpus.

DRE publishes the same diploma twice. ``pub:`` is the act as it appeared in the
Diário — one snapshot, no history. ``cons:`` is the consolidated text, one
version per effective date. Both resolve to the same identifier, so both write
the same file, and the one written last is the one the repository keeps.

Letting the as-published side land last cost the Código Civil its 2,930 blocks
and 54 reforms: it shipped as a one-block stub of a law with a century of
amendments. So the consolidated side goes last, and there is a barrier between
the two phases rather than a sort — with eight workers, submission order is not
completion order, and a sort would only make the race look handled.

This lives here, and not in a script beside the repo, because a rule that
decides what the corpus contains has to be reachable from everything that
writes to it. ``daily.py`` cannot import from ``scripts/``, which is how a
Portuguese regression stayed hidden once already.

Discovered automatically by :func:`legalize.pipeline.generic_bootstrap` through
the optional ``fetcher/{country}/bootstrap.py`` hook.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rich.console import Console

from legalize.config import Config
from legalize.fetcher.pt import analise_juridica
from legalize.fetcher.pt.amendments import build_index
from legalize.storage import overwritten_identifiers, reset_write_tracking

logger = logging.getLogger(__name__)
console = Console()

CONSOLIDATED_PREFIX = "cons:"


def bootstrap(config: Config, dry_run: bool = False, limit: int | None = None) -> int:
    """Fetch every Portuguese diploma in phase order, then commit the history."""
    from legalize.pipeline import (
        commit_all_fast,
        discover_norm_ids,
        write_country_meta,
        write_repo_meta,
    )

    cc = config.get_country("pt")
    console.print("[bold]Bootstrap PT[/bold]\n")
    console.print(f"  Data dir: {cc.data_dir}")
    console.print(f"  Repo output: {cc.repo_path}\n")

    # Before the parse, because the parse consumes it: last_amendment is what
    # turns an as-enacted file from a silent 1994 text into one that names the
    # act that changed it.
    console.print("[bold]Amendment index[/bold]")
    build_index(config)
    loaded = analise_juridica.install(cc.data_dir)
    console.print(f"análise jurídica: {loaded or 'no maps found'}\n")

    norm_ids = discover_norm_ids(config, "pt", limit=limit)
    published = [n for n in norm_ids if not n.startswith(CONSOLIDATED_PREFIX)]
    consolidated = [n for n in norm_ids if n.startswith(CONSOLIDATED_PREFIX)]
    console.print(
        f"[bold]Fetch — {len(norm_ids)} norms "
        f"({len(published)} as-published, {len(consolidated)} consolidated)[/bold]\n"
    )

    fetched = 0
    for phase, batch in (("as-published", published), ("consolidated", consolidated)):
        if not batch:
            continue
        console.print(f"  [dim]-- {phase}: {len(batch)}[/dim]")
        # Per phase, so the consolidated pass is judged on its own: a consolidated
        # diploma landing on its as-published twin is the point of the ordering
        # and must not be counted as a clash. Two norms clashing inside one phase
        # is the thing worth knowing — that is one law shadowing another.
        reset_write_tracking()
        fetched += _fetch_phase(config, batch, cc.max_workers or 1)
        clashes = overwritten_identifiers()
        if clashes:
            sample = ", ".join(sorted(clashes)[:5])
            console.print(
                f"  [yellow]⚠ {len(clashes)} identifier(s) claimed by two {phase} norms; "
                f"each extra one saved under a suffixed name: {sample}"
                f"{' …' if len(clashes) > 5 else ''}[/yellow]"
            )

    console.print(f"\n[bold green]✓ {fetched} norms fetched[/bold green]")
    _check_consolidated_survived(Path(cc.data_dir), consolidated)

    console.print("\n[bold]Commit — generating git history[/bold]\n")
    try:
        total_commits = commit_all_fast(config, "pt", dry_run=dry_run)
    finally:
        write_country_meta(config, "pt")
        if not dry_run:
            write_repo_meta(config, "pt")

    console.print("\n[bold green]✓ Bootstrap PT completed[/bold green]")
    console.print(f"  {fetched} norms fetched, {total_commits} commits created")
    return total_commits


def _fetch_phase(config: Config, norm_ids: list[str], workers: int) -> int:
    """Fetch one phase to completion. Returns how many norms produced data."""
    from legalize.pipeline import generic_fetch_one

    done = ok = 0

    def one(norm_id: str) -> bool:
        try:
            return generic_fetch_one(config, "pt", norm_id, force=True) is not None
        except Exception:
            logger.error("Fetch failed for %s", norm_id, exc_info=True)
            return False

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for produced in pool.map(one, norm_ids):
            done += 1
            ok += bool(produced)
            if done % 2000 == 0:
                console.print(f"     [dim][{done}/{len(norm_ids)}] {ok} with data[/dim]")
    return ok


def _check_consolidated_survived(data_dir: Path, consolidated: list[str]) -> None:
    """The ordering's own check: a consolidated diploma must still be on disk.

    Almost every consolidated diploma is also reachable as-published, both write
    the same file, and if the wrong one lands last the law silently loses its
    whole history. Counting what survived is what makes the phase order a claim
    that can fail rather than a comment that can rot.
    """
    json_dir = data_dir / "json"
    if not json_dir.exists() or not consolidated:
        return
    import json as _json

    survived = 0
    for path in json_dir.glob("*.json"):
        try:
            with open(path, encoding="utf-8") as handle:
                if len(_json.load(handle).get("reforms") or []) > 1:
                    survived += 1
        except Exception:
            continue
    console.print(
        f"  consolidated diplomas with a version history on disk: {survived} "
        f"(of {len(consolidated)} fetched)"
    )
