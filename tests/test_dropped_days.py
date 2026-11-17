"""A day the lookback cap drops before it ever finished must end the run red.

The state's cursor only advances over days that finished clean, so a cursor past
the cap means those days held an error until they fell out of the window. That was
a warning and nothing else: es lost BOE-A-2026-22008 and eu nine new acts in
October 2026.
"""

from __future__ import annotations

import subprocess
from datetime import date, timedelta

import pytest

from legalize.pipeline import DaysDropped, finalize_daily
from legalize.state.store import MAX_LOOKBACK_DAYS, StateStore, resolve_dates_to_process


def _repo(tmp_path, source_date: date | None = None):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    if source_date:
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=T",
                "-c",
                "user.email=t@t.t",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                f"[reform] x\n\nSource-Date: {source_date}\nNorm-Id: X",
            ],
            cwd=repo,
            check=True,
        )
    return repo


def _state(tmp_path, cursor: date | None) -> StateStore:
    state = StateStore(tmp_path / "state.json")
    state.load()
    if cursor:
        state.last_summary_date = cursor
    return state


def test_an_unfinished_state_cursor_past_the_cap_is_reported(tmp_path):
    cursor = date.today() - timedelta(days=30)
    state = _state(tmp_path, cursor)

    dates = resolve_dates_to_process(state, str(_repo(tmp_path)))

    window_start = date.today() - timedelta(days=MAX_LOOKBACK_DAYS)
    assert dates[0] == window_start
    assert state.dropped == (cursor + timedelta(days=1), window_start - timedelta(days=1))


def test_a_quiet_source_is_not_lost_work(tmp_path):
    """Only git is old: nothing happened at the source, the state finished recently."""
    state = _state(tmp_path, date.today() - timedelta(days=2))

    resolve_dates_to_process(state, str(_repo(tmp_path, date.today() - timedelta(days=60))))

    assert state.dropped is None


def test_since_and_date_drop_nothing(tmp_path):
    state = _state(tmp_path, date.today() - timedelta(days=30))
    repo = str(_repo(tmp_path))

    resolve_dates_to_process(state, repo, since=date.today() - timedelta(days=30))
    resolve_dates_to_process(state, repo, target_date=date.today() - timedelta(days=30))

    assert state.dropped is None


class _Repo:
    refused: list[str] = []

    def __init__(self):
        self.pushed = False

    def push(self):
        self.pushed = True


def test_finalize_publishes_first_then_ends_red(tmp_path):
    state = _state(tmp_path, None)
    state.dropped = (date(2026, 10, 1), date(2026, 10, 6))
    repo = _Repo()

    with pytest.raises(DaysDropped, match="--since 2026-10-01"):
        finalize_daily(repo, state, [date(2026, 10, 7)], 3, [], push=True)

    assert repo.pushed
    assert (tmp_path / "state.json").exists()


def test_finalize_without_dropped_days_is_unchanged(tmp_path):
    assert finalize_daily(_Repo(), _state(tmp_path, None), [date(2026, 10, 7)], 2, []) == 2
