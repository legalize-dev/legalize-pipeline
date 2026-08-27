"""A dead fast-import must stop the run, not be logged 87,000 times.

Portugal's rebuild lost five hours to this: fast-import went away at commit
~85,000 of 174,744, every later write raised BrokenPipeError inside the loop's
``except Exception``, and the log filled with identical tracebacks while the
repo quietly stayed half-built.
"""

from __future__ import annotations

import subprocess
from datetime import date

import pytest

from legalize.committer.git_ops import FastImportDied, FastImporter
from legalize.models import CommitInfo, CommitType


def _info() -> CommitInfo:
    return CommitInfo(
        commit_type=CommitType.BOOTSTRAP,
        subject="[new] Test",
        body="",
        trailers={},
        author_name="Legalize",
        author_email="bot@legalize.dev",
        author_date=date(2020, 1, 1),
        file_path="pt/one.md",
        content="# one\n",
    )


def test_broken_pipe_aborts_the_import(tmp_path):
    with pytest.raises(FastImportDied):
        with FastImporter(tmp_path / "repo", "Legalize", "bot@legalize.dev") as fi:
            fi.commit("pt/one.md", "# one\n", _info())
            fi._proc.kill()
            fi._proc.wait()
            # Enough payload that the write reaches the closed pipe rather than
            # sitting in the buffer.
            for i in range(200):
                fi.commit(f"pt/{i}.md", "x" * 10_000, _info())


def test_a_failed_import_is_not_reported_as_success(tmp_path):
    """fast-import exiting non-zero left the ref where it was — and said nothing.

    The returncode was logged, never raised, and the message it logged was
    always empty because the Popen does not capture stderr. ``commit_all_fast``
    counts *queued* commits, so the chunk that never landed was reported as
    imported and the next chunk carried on from the previous tip: a permanent
    hole in the middle of the history that a rerun does not backfill.
    """
    repo = tmp_path / "repo"
    with pytest.raises(FastImportDied, match="did not move"):
        with FastImporter(repo, "Legalize", "bot@legalize.dev") as fi:
            fi.commit("pt/one.md", "# one\n", _info())
            # Killed after the last write: nothing raises inside the block, so
            # only __exit__ can notice.
            fi._proc.kill()

    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "refs/heads/main"],
        capture_output=True,
    )
    assert head.returncode != 0, "the ref moved, so this is no longer the failure under test"
