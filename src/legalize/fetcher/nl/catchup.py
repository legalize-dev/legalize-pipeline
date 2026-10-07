"""Write the versions of Dutch laws the daily never recorded, in date order per law.

``legalize daily --date D`` cannot do this. Its discovery asks the SRU for every law
modified on *or after* D and renders each one as it stood on D, so a catch-up over
a range re-renders the same few hundred laws once per day, rolling newer text back
to older text and stamping ``last_updated`` with the processing day (a 44-day run
would have written ~17,000 commits, 1,910 of them published before it was stopped).

What a catch-up has to produce is what the daily would have written had it never
missed a day: for each law, one commit per version that took effect after the file's
last commit, in order, each dated on the day the version took effect and holding the
text in force that day. Dated that way, the commits of every file stay in date order,
which is the only ordering the format promises (spec, History).

    python -m legalize.fetcher.nl.catchup --since 2026-08-24 --repo-path REPO [--push]
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path

from legalize.committer.git_ops import GitRepo
from legalize.committer.message import build_commit_info
from legalize.config import load_config
from legalize.models import CommitType, Reform
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath

logger = logging.getLogger(__name__)

_LAST_UPDATED = re.compile(r'^last_updated:\s*"?(\d{4}-\d{2}-\d{2})', re.MULTILINE)


def last_updated(repo: GitRepo, law_id: str) -> str | None:
    """The date in the frontmatter of the law as HEAD holds it, or None if absent."""
    text = repo._run(["show", f"HEAD:nl/{law_id}.md"], check=False)
    found = _LAST_UPDATED.search(text or "")
    return found.group(1) if found else None


def plan(
    repo: GitRepo, client, law_ids: Iterable[str], until: date
) -> tuple[list[tuple[str, str]], list[str]]:
    """Which (effective_date, law_id) versions are missing, oldest first.

    A version is missing when it took effect after the law's file was last written
    and not after ``until``. Anything at or before ``last_updated`` is already in the
    file or older than it, and writing it would put an earlier date after a later one
    in that file's history. Laws with no file are returned apart: they are new laws,
    not a missed version.
    """
    missing: list[tuple[str, str]] = []
    without_file: list[str] = []
    for law_id in sorted(set(law_ids)):
        written = last_updated(repo, law_id)
        if written is None:
            without_file.append(law_id)
            continue
        for effective, _path in client.list_expressions(law_id):
            if written < effective <= until.isoformat():
                missing.append((effective, law_id))
    missing.sort()
    return missing, without_file


def write_version(repo: GitRepo, client, meta_parser, text_parser, law_id: str, day: date) -> bool:
    """Render ``law_id`` as in force on ``day`` and commit it dated ``day``."""
    client.set_as_of(day)
    metadata = meta_parser.parse(client.get_metadata(law_id), law_id)
    blocks = text_parser.parse_text(client.get_text(law_id))
    file_path = norm_to_filepath(metadata)
    markdown = render_norm_at_date(metadata, blocks, day)
    if not repo.write_and_add(file_path, markdown):
        return False
    reform = Reform(date=day, norm_id=f"NL-DAILY-{day.isoformat()}", affected_blocks=())
    info = build_commit_info(CommitType.REFORM, metadata, reform, blocks, file_path, markdown)
    return bool(repo.commit(info))


def catch_up(
    repo: GitRepo,
    client,
    discovery,
    meta_parser,
    text_parser,
    since: date,
    until: date,
    write: Callable = write_version,
) -> tuple[int, list[str], list[str]]:
    """Returns (commits written, errors, laws without a file)."""
    law_ids = list(discovery.discover_daily(client, since))
    missing, without_file = plan(repo, client, law_ids, until)
    logger.info(
        "%d laws modified since %s, %d versions to write, %d laws with no file",
        len(law_ids),
        since,
        len(missing),
        len(without_file),
    )

    written = 0
    errors: list[str] = []
    failed: set[str] = set()
    for effective, law_id in missing:
        if law_id in failed:
            # An earlier version of this law did not land. Writing a later one now
            # would leave the file's history with a gap it cannot be filled into.
            errors.append(f"{law_id} {effective}: skipped, an earlier version failed")
            continue
        try:
            if write(repo, client, meta_parser, text_parser, law_id, date.fromisoformat(effective)):
                written += 1
        except Exception as exc:  # noqa: BLE001 - one law must not stop the others
            logger.exception("%s %s", law_id, effective)
            errors.append(f"{law_id} {effective}: {exc}")
            failed.add(law_id)
    return written, errors, without_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--since", required=True, type=date.fromisoformat)
    parser.add_argument("--until", type=date.fromisoformat, default=date.today())
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args(argv)

    from legalize.countries import (
        get_client_class,
        get_discovery_class,
        get_metadata_parser,
        get_text_parser,
    )

    config = load_config(args.config)
    cc = config.get_country("nl")
    repo = GitRepo(Path(args.repo_path), config.git.committer_name, config.git.committer_email)
    discovery = get_discovery_class("nl").create(cc.source or {})
    with get_client_class("nl").create(cc) as client:
        written, errors, without_file = catch_up(
            repo,
            client,
            discovery,
            get_metadata_parser("nl"),
            get_text_parser("nl"),
            args.since,
            args.until,
        )
    if without_file:
        print(f"laws with no file (new laws, not written): {', '.join(without_file)}")
    print(f"{written} commits written, {len(errors)} errors")
    for line in errors[:20]:
        print(f"  {line}")
    if args.push and written and not errors:
        repo.push()
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
