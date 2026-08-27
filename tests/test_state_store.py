"""Tests for the generic date-inference logic in ``legalize.state.store``.

These cover the guard against future-dated ``Source-Date`` trailers, which
silently froze seven country dailies (pl, lt, be, ee, fi, gr, it) for
months: the trailer at the tip of a freshly bootstrapped repo is the norm's
entry-into-force date, which can be years away.
"""

from __future__ import annotations

import os
import subprocess
from datetime import date, timedelta

import pytest

from legalize.state.store import (
    MAX_LOOKBACK_DAYS,
    RunRecord,
    StateStore,
    infer_last_date_from_git,
    latest_source_date,
    resolve_dates_to_process,
)

TODAY = date.today()


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=path, capture_output=True)
    return path


def _commit(repo, subject, source_date=None, commit_date=None):
    """Add one commit, optionally with a Source-Date trailer and a fixed date."""
    (repo / "law.md").write_text(subject)
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    message = subject if source_date is None else f"{subject}\n\nSource-Date: {source_date}"
    env = dict(os.environ)
    if commit_date is not None:
        stamp = f"{commit_date} 12:00:00 +0000"
        env |= {"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo,
        capture_output=True,
        check=True,
        env=env,
    )


class TestInferLastDateFromGit:
    def test_uses_tip_trailer_when_not_in_the_future(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit(repo, "older", source_date="2026-03-01")
        _commit(repo, "newest", source_date="2026-03-28")

        assert infer_last_date_from_git(str(repo)) == date(2026, 3, 28)

    def test_walks_past_future_dated_tip_commits(self, tmp_path):
        """The legalize-lt shape: real data, then future entry-into-force norms."""
        repo = _init_repo(tmp_path / "repo")
        _commit(repo, "real data", source_date="2026-04-02")
        _commit(repo, "enters into force in 2030", source_date="2030-01-01")
        _commit(repo, "enters into force in 2034", source_date="2034-01-01")

        assert infer_last_date_from_git(str(repo)) == date(2026, 4, 2)

    def test_ignores_commits_without_a_trailer_while_walking(self, tmp_path):
        """The 2026-06-23 README/LICENSE sweep sits on top of every country repo."""
        repo = _init_repo(tmp_path / "repo")
        _commit(repo, "real data", source_date="2026-04-02")
        _commit(repo, "future norm", source_date="2034-01-01")
        _commit(repo, "Add LICENSE: MIT pipeline code")

        assert infer_last_date_from_git(str(repo)) == date(2026, 4, 2)

    def test_falls_back_to_the_lookback_horizon_when_every_trailer_is_future(self, tmp_path):
        """Never return None here: that is the silent no-op the guard prevents."""
        repo = _init_repo(tmp_path / "repo")
        _commit(repo, "future a", source_date="2029-01-01")
        _commit(repo, "future b", source_date="2034-01-01")

        assert latest_source_date(str(repo)) is None
        assert infer_last_date_from_git(str(repo)) == TODAY - timedelta(days=MAX_LOOKBACK_DAYS)

    def test_fallback_ignores_commit_dates(self, tmp_path):
        """Commit dates carry the norm's own date, so they cannot be trusted.

        committer.git_ops.GitRepo.commit sets GIT_COMMITTER_DATE to the
        norm date, which for these repos is the same future date the
        trailer was just rejected for. Using it would put start beyond
        today and reproduce the empty range.
        """
        repo = _init_repo(tmp_path / "repo")
        _commit(repo, "future norm", source_date="2034-01-01", commit_date=TODAY + timedelta(365))

        assert infer_last_date_from_git(str(repo)) == TODAY - timedelta(days=MAX_LOOKBACK_DAYS)

    def test_malformed_trailer_does_not_abort_the_walk(self, tmp_path):
        """Old code let ValueError escape the loop and returned None for the repo."""
        repo = _init_repo(tmp_path / "repo")
        _commit(repo, "real data", source_date="2026-04-02")
        _commit(repo, "broken", source_date="not-a-date")

        assert infer_last_date_from_git(str(repo)) == date(2026, 4, 2)

    def test_returns_none_without_any_pipeline_commit(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit(repo, "docs: add README")

        assert infer_last_date_from_git(str(repo)) is None

    def test_returns_none_for_empty_repo(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")

        assert infer_last_date_from_git(str(repo)) is None

    def test_returns_none_for_nonexistent_dir(self, tmp_path):
        assert infer_last_date_from_git(str(tmp_path / "nope")) is None


class TestResolveDatesUnblocksFrozenCountries:
    """End-to-end: the user-visible symptom was an empty date range."""

    def _frozen_repo(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit(repo, "real data", source_date=(TODAY - timedelta(days=60)).isoformat())
        _commit(repo, "future norm", source_date="2034-01-01")
        return repo

    def test_produces_a_non_empty_date_range(self, tmp_path):
        state = StateStore(str(tmp_path / "state.json"))
        state.load()

        dates = resolve_dates_to_process(state, str(self._frozen_repo(tmp_path)), target_date=None)

        assert dates, "a future-dated tip must not silence the daily"
        assert dates[-1] == TODAY
        # The 60-day gap is still capped: the guard unblocks the daily going
        # forward, it does not backfill. See MAX_LOOKBACK_DAYS.
        assert dates[0] == TODAY - timedelta(days=MAX_LOOKBACK_DAYS)

    def test_all_future_repo_also_gets_a_date_range(self, tmp_path):
        """The bootstrap-only shape, where the fallback is the only path."""
        repo = _init_repo(tmp_path / "repo")
        _commit(repo, "future a", source_date="2029-01-01")
        _commit(repo, "future b", source_date="2034-01-01")

        state = StateStore(str(tmp_path / "state.json"))
        state.load()

        dates = resolve_dates_to_process(state, str(repo), target_date=None)

        assert dates, "the fallback must produce work, not an empty range"
        assert dates[0] == TODAY - timedelta(days=MAX_LOOKBACK_DAYS) + timedelta(days=1)
        assert dates[-1] == TODAY


def test_a_failed_save_leaves_the_previous_state_readable(tmp_path):
    """state.json is written by rename, never truncated in place.

    A Ctrl-C during a commit run — which saves every 50 laws — used to leave a
    half-written file, and every later daily for that country then died in
    ``json.load`` before it could do anything about it.
    """
    import json

    path = tmp_path / "state.json"
    state = StateStore(path)
    state.last_summary_date = date(2024, 1, 1)
    state.save()

    # A value json.dump chokes on, so the write dies part-way through.
    state._runs.append(RunRecord(timestamp="2024-01-02T00:00:00", errors=[object()]))
    with pytest.raises(TypeError):
        state.save()

    assert json.loads(path.read_text(encoding="utf-8"))["last_summary"] == "2024-01-01"
    assert not list(tmp_path.glob(".state.json.*")), "the temp file was left behind"
