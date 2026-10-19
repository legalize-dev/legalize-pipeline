"""Build the Act corpus and the source instruments its amendment history cites."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from legalize.config import Config
from legalize.coverage import unresolved
from legalize.pipeline import (
    NothingPublished,
    commit_all_fast,
    console,
    discover_norm_ids,
    generic_fetch_all,
    generic_fetch_one,
    write_country_meta,
    write_repo_meta,
)
from legalize.storage import load_norma_from_json


def fetch_dependencies(config: Config, identifiers: list[str]) -> list[str]:
    """Close amendment references transitively; return the instruments that loaded.

    The walk goes on from every instrument that did load, so one run names every
    failure at every depth. Spec v0.5 §Coverage: an instrument that cannot be read
    is recorded with its reason (coverage.json lists it) and the corpus is published
    without it; a network failure stops the run instead, because a retry may succeed
    and a gap must never stand in for one.
    """
    cc = config.get_country("ie")
    json_dir = Path(cc.data_dir) / "json"
    seen = set(identifiers)
    loaded = list(identifiers)
    failed = []
    with ThreadPoolExecutor(max_workers=cc.max_workers or 1) as pool:
        while loaded:
            references = set()
            for identifier in loaded:
                norm = load_norma_from_json(json_dir / f"{identifier}.json")
                references.update(
                    reform.norm_id for reform in norm.reforms if reform.norm_id.startswith("IE-")
                )
            pending = sorted(references - seen)
            results = list(
                pool.map(lambda key: generic_fetch_one(config, "ie", key) is not None, pending)
            )
            seen.update(pending)
            failed += [
                key for key, succeeded in zip(pending, results, strict=True) if not succeeded
            ]
            loaded = [key for key, succeeded in zip(pending, results, strict=True) if succeeded]
    if retry := unresolved(cc.data_dir, failed):
        raise NothingPublished(f"Ireland amendment sources unavailable: {', '.join(sorted(retry))}")
    if failed:
        console.print(
            f"[yellow]{len(failed)} cited instrument(s) unreadable; listed in coverage.json[/yellow]"
        )
    return sorted(seen - set(failed))


def bootstrap(config: Config, dry_run: bool = False, limit: int | None = None) -> int:
    """Use the shared fetch/commit pipeline with a complete, verified source closure."""
    cc = config.get_country("ie")
    expected = set(discover_norm_ids(config, "ie", limit=limit))
    fetched = generic_fetch_all(config, "ie", limit=limit)
    missing = expected - set(fetched)
    if retry := unresolved(cc.data_dir, missing):
        raise NothingPublished(f"Ireland Acts unavailable: {', '.join(sorted(retry))}")
    closure = fetch_dependencies(config, fetched)
    total = commit_all_fast(config, "ie", dry_run=dry_run, norm_ids=set(closure))
    if not dry_run:
        write_country_meta(config, "ie")
        write_repo_meta(config, "ie")
    return total
