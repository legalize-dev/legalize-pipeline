"""A dead fast-import must stop the run, not be logged 87,000 times.

Portugal's rebuild lost five hours to this: fast-import went away at commit
~85,000 of 174,744, every later write raised BrokenPipeError inside the loop's
``except Exception``, and the log filled with identical tracebacks while the
repo quietly stayed half-built.
"""

from __future__ import annotations

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
