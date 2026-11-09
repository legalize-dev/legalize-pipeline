"""Write the as-published Portuguese acts that never reached the corpus, oldest first.

The August 2026 bootstrap discovered Portugal from DRE's sitemaps alone, and those
list a fraction of some years: 95 portaria pages for 2017 against ~1,500 a year from
2022 (see ``discovery.py``). The daily only ever looks forward, so nothing brought
them back. This walks the journal over a range of days and writes each in-scope act
whose identifier the repository does not hold, through the daily's own
``commit_new``: the same file and the same ``[new]`` commit, dated on publication.

It writes nothing else. The daily's other two steps stay out on purpose: the
re-consolidation pass is a diff against yesterday's sitemap, not a property of a past
day, and the amendment refresh commits a law's missing versions at the tip, which
replayed for an old act can leave an earlier text above a later one.

Days are walked oldest first, so every file's history stays in date order. The tip
of the repository ends up dated on the last day written: the daily copes (its state
cursor and lookback cap), and the database sync needs its walk-to-a-known-sha mode
rather than a ``--since`` window.

The identifiers already published are read with one ``git ls-tree`` over HEAD, so the
clone needs its trees: ``--filter=blob:none``, not the daily's ``tree:0``.

    python -m legalize.fetcher.pt.backfill --since 2014-01-01 --until 2021-12-31 \\
        --repo-path ../countries/pt [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Iterator
from datetime import date
from pathlib import PurePosixPath

from legalize.committer.git_ops import GitRepo
from legalize.config import load_config
from legalize.fetcher.pt.identifier import build_identifier

logger = logging.getLogger(__name__)


def published_identifiers(repo: GitRepo) -> set[str]:
    """Every identifier HEAD holds a law file for, in any directory (root files are not laws)."""
    listed = repo._run(["ls-tree", "-r", "--name-only", "HEAD"], check=False) or ""
    return {PurePosixPath(p).stem for p in listed.splitlines() if p.endswith(".md") and "/" in p}


def missing(
    discovery, client, present: set[str], since: date, until: date
) -> Iterator[tuple[date, str, str]]:
    """``(day, norm_id, identifier)`` for each act the journal lists and HEAD lacks."""
    for day, norm_id in discovery.journal_ids(client, since, until):
        _surface, tipo, key = norm_id.split(":", 2)
        identifier = build_identifier(f"/dr/detalhe/{tipo}/{key}", "")
        if identifier in present:
            continue
        present.add(identifier)
        yield day, norm_id, identifier


def backfill(config, since: date, until: date, *, dry_run: bool = False) -> tuple[int, list[str]]:
    """Commit what is missing between two days. Returns (commits, failed norm ids)."""
    from legalize.fetcher.pt import analise_juridica
    from legalize.fetcher.pt.client import DREClient
    from legalize.fetcher.pt.daily import commit_new
    from legalize.fetcher.pt.discovery import DREDiscovery
    from legalize.fetcher.pt.dre_api import DREApiError
    from legalize.fetcher.pt.parser import DREMetadataParser
    from legalize.pipeline import generic_fetch_one

    cc = config.get_country("pt")
    analise_juridica.install(cc.data_dir)
    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    present = published_identifiers(repo)
    if not present:
        raise RuntimeError(f"{cc.repo_path} lists no laws at HEAD; is it a legalize-pt clone?")
    discovery = DREDiscovery.create({**cc.source, "cache_dir": cc.data_dir})
    meta_parser = DREMetadataParser()

    written, failed = 0, []
    with DREClient.create(cc) as client:
        for day, norm_id, identifier in missing(discovery, client, present, since, until):
            if dry_run:
                print(f"{day}\t{norm_id}\t{identifier}", flush=True)
                continue
            try:
                if commit_new(config, repo, client, meta_parser, norm_id, generic_fetch_one):
                    written += 1
            except DREApiError:
                logger.exception("DRE API contract broken at %s — stopping", norm_id)
                raise
            except Exception:
                logger.exception("Could not write %s (%s)", norm_id, identifier)
                failed.append(norm_id)
    for path in repo.refused:
        failed.append(f"refused: {path} belongs to another act")
    return written, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--since", required=True, type=date.fromisoformat)
    parser.add_argument("--until", type=date.fromisoformat, default=date.today())
    parser.add_argument("--repo-path", default=None)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    config = load_config(args.config)
    cc = config.get_country("pt")
    if args.repo_path:
        cc.repo_path = args.repo_path
    if args.data_dir:
        cc.data_dir = args.data_dir
    written, failed = backfill(config, args.since, args.until, dry_run=args.dry_run)
    print(f"{written} commits written, {len(failed)} failed")
    for line in failed[:50]:
        print(f"  {line}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
