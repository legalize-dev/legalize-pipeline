"""``commit_all_fast`` in chunks, so a death costs a chunk and not the history.

``git fast-import`` moves the branch when its stdin closes and not before, so a
single session is all-or-nothing: Portugal's commit phase was killed three times
in one evening, at 35,000, 10,000 and 85,000 of 302,333 commits, and each time
the branch was still empty and the next run started from zero.

The chunks are slices of the reform list *after* it is sorted by date, never of
the laws, so the history stays chronological across a resume — slicing the laws
would restart the timeline at every seam.
"""

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import pytest

from legalize.config import load_config
from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    ParsedNorm,
    Rank,
    Reform,
    Version,
)
from legalize.pipeline import HistoryMismatch, commit_all_fast
from legalize.storage import save_structured_json


def _norm(identifier: str, dates: list[date]) -> ParsedNorm:
    """A law with one reform per date. `year` is what pt's path template needs."""
    first = dates[0]
    return ParsedNorm(
        metadata=NormMetadata(
            title=f"t {identifier}",
            short_title="t",
            identifier=identifier,
            country="pt",
            rank=Rank.LEY,
            publication_date=first,
            status=NormStatus.IN_FORCE,
            department="Test",
            source=f"https://example.com/{identifier}",
            extra=(("year", str(first.year)),),
        ),
        blocks=(
            Block(
                id="a1",
                block_type="precepto",
                title="Artigo 1",
                versions=tuple(
                    Version(
                        norm_id=identifier,
                        publication_date=when,
                        effective_date=when,
                        paragraphs=(Paragraph(css_class="parrafo", text=f"x {when}"),),
                    )
                    for when in dates
                ),
            ),
        ),
        reforms=tuple(
            Reform(date=when, norm_id=identifier, affected_blocks=("a1",)) for when in dates
        ),
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def corpus(tmp_path):
    """Four laws, twelve reforms, interleaved in time so order is observable."""
    data, repo = tmp_path / "data", tmp_path / "repo"
    for identifier, years in (
        ("DRE-1990-1-100", [1990, 1995, 2005, 2020]),
        ("DRE-1992-2-200", [1992, 2001, 2019]),
        ("DRE-2000-3-300", [2000, 2010]),
        ("DRE-2003-4-400", [2003, 2012, 2021]),
    ):
        save_structured_json(data, _norm(identifier, [date(y, 6, 1) for y in years]))
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)

    config = tmp_path / "config.yaml"
    config.write_text(f'countries:\n  pt:\n    repo_path: "{repo}"\n    data_dir: "{data}"\n')
    return load_config(str(config)), repo


def _dates(repo: Path) -> list[str]:
    return _git(repo, "log", "--reverse", "--format=%ad", "--date=short", "main").splitlines()


def test_the_history_is_chronological_across_chunk_seams(corpus, monkeypatch):
    config, repo = corpus
    monkeypatch.setattr("legalize.pipeline._IMPORT_CHUNK", 3)

    assert commit_all_fast(config, "pt") == 12
    dates = _dates(repo)
    assert len(dates) == 12
    assert dates == sorted(dates), "a chunk seam restarted the timeline"


def test_a_run_that_died_mid_history_continues_where_it_stopped(corpus, monkeypatch):
    config, repo = corpus
    monkeypatch.setattr("legalize.pipeline._IMPORT_CHUNK", 3)
    commit_all_fast(config, "pt")
    whole = _dates(repo)

    # What a killed run leaves: the chunks that finished, and nothing of the one
    # that did not.
    sixth = _git(repo, "rev-list", "--reverse", "main").splitlines()[5]
    _git(repo, "reset", "--hard", sixth)
    assert len(_dates(repo)) == 6

    assert commit_all_fast(config, "pt") == 12
    assert _dates(repo) == whole, "resuming produced a different history"


def test_resuming_does_not_commit_the_same_reform_twice(corpus, monkeypatch):
    config, repo = corpus
    monkeypatch.setattr("legalize.pipeline._IMPORT_CHUNK", 5)
    commit_all_fast(config, "pt")

    _git(repo, "reset", "--hard", _git(repo, "rev-list", "--reverse", "main").splitlines()[3])
    commit_all_fast(config, "pt")

    # Each law must carry exactly the reforms it has, not the ones the first run
    # already wrote plus the ones the second run wrote again.
    body = _git(repo, "log", "--format=%b", "main")
    for identifier, expected in (("DRE-1990-1-100", 4), ("DRE-2003-4-400", 3)):
        named = [ln for ln in body.splitlines() if ln.strip() == f"Norm-Id: {identifier}"]
        assert len(named) == expected, f"{identifier} committed {len(named)} times"
    assert len(_dates(repo)) == 12


def test_a_second_run_over_a_finished_history_adds_nothing(corpus, monkeypatch):
    config, repo = corpus
    monkeypatch.setattr("legalize.pipeline._IMPORT_CHUNK", 4)
    commit_all_fast(config, "pt")

    assert commit_all_fast(config, "pt") == 12
    assert len(_dates(repo)) == 12


def test_it_refuses_a_branch_it_cannot_continue_from(corpus):
    """Stacking a second history on an unrelated first is the failure to avoid."""
    config, repo = corpus
    (repo / "other.md").write_text("not ours\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-qm",
            "someone else's work\n\nSource-Date: 1066-10-14\nNorm-Id: NOT-OURS-1",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    with pytest.raises(HistoryMismatch):
        commit_all_fast(config, "pt")


def test_a_repo_the_daily_has_extended_is_not_rebuilt_on_top_of_itself(corpus):
    """The failure this cost us on legalize-es, in miniature.

    A country repo is not only ever written by the bootstrap: the daily adds
    `[new]` and `[reform]` commits to it for months afterwards. Resuming by
    *position* assumed the branch was a prefix of the bootstrap stream, so a tip
    the daily had put there — whose (Source-Date, Norm-Id) pair still appears in
    the stream, at a low index — made the run resume from that index and re-emit
    everything after it onto laws that already had their commits. It produced
    18 `[bootstrap]` commits for already-published laws, 10 more with an empty
    diff, ~95 duplicate versions, and 9 laws whose commits stopped being in
    Source-Date order. Skipping by version instead of by position cannot do it.
    """
    config, repo = corpus
    assert commit_all_fast(config, "pt") == 12

    # What the daily leaves on the tip: a commit for a law the stream also
    # builds, carrying a pair the stream already used at index 0.
    first = _git(repo, "log", "--reverse", "--format=%b", "main").splitlines()
    trailers = {
        k.strip(): v.strip() for k, _, v in (ln.partition(":") for ln in first if ":" in ln)
    }
    (repo / "pt" / "1990" / "extra.md").write_text("daily\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-qm",
            f"[reform] something the daily found\n\n"
            f"Source-Id: {trailers['Source-Id']}\n"
            f"Source-Date: {trailers['Source-Date']}\n"
            f"Norm-Id: {trailers['Norm-Id']}",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    before = _git(repo, "rev-list", "--count", "main")

    assert commit_all_fast(config, "pt") == 12, "it re-emitted a history the repo already had"
    assert _git(repo, "rev-list", "--count", "main") == before, "the second run added commits"
    body = _git(repo, "log", "--format=%b", "main")
    for identifier, expected in (("DRE-1990-1-100", 4), ("DRE-2003-4-400", 3)):
        named = [ln for ln in body.splitlines() if ln.strip() == f"Norm-Id: {identifier}"]
        # The daily's own commit names one of them a second time; nothing else may.
        assert len(named) <= expected + 1, f"{identifier} committed {len(named)} times"
