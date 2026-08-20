"""State Store — pipeline state tracking.

Persists in state.json: last summary date and run history.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default safety cap for automatic lookback (no explicit --date)
MAX_LOOKBACK_DAYS = 10

# How far back to walk pipeline commits looking for a usable Source-Date.
# Bootstrap writes one commit per norm in the norms' own chronological
# order, so a repo can open with a long run of future-dated commits at the
# tip: the worst observed is legalize-it with 72 in a row. 500 leaves ample
# headroom without walking 86k commits on every daily run.
MAX_COMMITS_SCANNED = 500


def resolve_dates_to_process(
    state: "StateStore",
    repo_path: str,
    target_date: date | None = None,
    *,
    skip_weekdays: set[int] | None = None,
) -> list[date] | None:
    """Determine which dates need processing for a daily run.

    Centralizes the date resolution logic shared by all country dailies:
    1. If ``target_date`` is given, returns ``[target_date]``.
    2. Otherwise infers start from state or git, applies the safety cap,
       and generates the date range up to today.

    Args:
        state: Loaded StateStore for the country.
        repo_path: Path to the country git repo (for git-based inference).
        target_date: Explicit date from ``--date`` CLI flag, or None.
        skip_weekdays: Set of ``date.weekday()`` values to exclude.
            Common values: ``{6}`` (skip Sunday = Mon-Sat schedule),
            ``{5, 6}`` (skip Sat+Sun = Mon-Fri schedule).
            None means include all days.

    Returns:
        List of dates to process, or None if no start date could be
        determined (caller should print a warning and return 0).
    """
    if target_date:
        return [target_date]

    start = state.last_summary_date
    if start is None:
        start = infer_last_date_from_git(repo_path)
    if start is None:
        return None

    start = start + timedelta(days=1)
    end = date.today()

    # Safety cap: without an explicit --date, limit automatic lookback
    # to avoid processing months of history by accident
    # (e.g., first CI run after setup, or after a long outage).
    max_lookback = end - timedelta(days=MAX_LOOKBACK_DAYS)
    if start < max_lookback:
        logger.warning(
            "Clamping start from %s to %s (max %d days)",
            start,
            max_lookback,
            MAX_LOOKBACK_DAYS,
        )
        start = max_lookback

    skip = skip_weekdays or set()
    dates: list[date] = []
    current = start
    while current <= end:
        if current.weekday() not in skip:
            dates.append(current)
        current += timedelta(days=1)

    return dates


def _parse_iso_date(value: str) -> date | None:
    """Parse an ISO date, returning None instead of raising on garbage."""
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def latest_source_date(repo_path: str) -> date | None:
    """Most recent ``Source-Date`` trailer that is not in the future.

    Walks pipeline commits (the ones carrying the trailer) newest first;
    manual commits such as the README/LICENSE sweeps carry no trailer and
    are filtered out by ``--grep``. Returns None when no such commit is
    found within ``MAX_COMMITS_SCANNED``.

    Future-dated trailers have to be skipped rather than trusted: bootstrap
    writes one commit per norm in the norms' own chronological order, and a
    norm whose entry into force is years away carries that future date, so
    a freshly bootstrapped repo opens with a run of them at the tip (72 in
    a row in legalize-it; up to 2034-01-01 in legalize-lt).

    This is also the corpus freshness signal: git commit dates are useless
    for it, since the committer sets GIT_COMMITTER_DATE to the norm's own
    date (see committer.git_ops.GitRepo.commit).
    """
    today = date.today()
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                f"-{MAX_COMMITS_SCANNED}",
                "--grep=Source-Date:",
                "--format=%B%x1e",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None

    if result.returncode != 0:
        return None

    for body in result.stdout.split("\x1e"):
        for line in body.splitlines():
            if not line.startswith("Source-Date: "):
                continue
            found = _parse_iso_date(line[len("Source-Date: ") :].strip())
            if found is not None and found <= today:
                return found
            # Future-dated (or malformed) trailer: keep walking back.
            break

    return None


def has_pipeline_commits(repo_path: str) -> bool:
    """Whether the repo contains any commit the pipeline produced."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--grep=Source-Date:", "--format=%H"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def infer_last_date_from_git(repo_path: str) -> date | None:
    """Infer the date the daily should resume from.

    Normally the most recent non-future ``Source-Date`` in the repo.

    Reading the tip commit's trailer as-is is what broke: it left ``start``
    beyond today, the date loop produced an empty range, and the daily
    exited 0 having done nothing. Green CI, no output, and self-locking —
    with no commit the trailer never moves. Seven countries sat frozen like
    that for months before anyone noticed.

    Fallback when the repo has pipeline commits but no usable trailer among
    the scanned ones: the lookback horizon, so the daily re-checks the full
    window it is allowed to process automatically. Re-processing that
    window is safe (the committer dedupes by Source-Id + Norm-Id) and it is
    already what the clamp in :func:`resolve_dates_to_process` does for any
    repo further behind. Returning None here instead would reproduce the
    exact silent no-op this guard exists to prevent — and the commit date
    is no help, since the committer sets it to the norm's own date, which
    in this scenario is precisely the future date we just rejected.
    """
    found = latest_source_date(repo_path)
    if found is not None:
        logger.info("Inferred last date from git: %s", found)
        return found

    if not has_pipeline_commits(repo_path):
        return None

    fallback = date.today() - timedelta(days=MAX_LOOKBACK_DAYS)
    logger.warning(
        "No Source-Date <= today in the last %d pipeline commits; resuming "
        "from the %d-day lookback horizon (%s). This repo was most likely "
        "bootstrapped and never updated since.",
        MAX_COMMITS_SCANNED,
        MAX_LOOKBACK_DAYS,
        fallback,
    )
    return fallback


@dataclass
class RunRecord:
    """Record of a pipeline run."""

    timestamp: str  # ISO datetime
    summaries_reviewed: list[str] = field(default_factory=list)
    commits_created: int = 0
    errors: list[str] = field(default_factory=list)


class StateStore:
    """Manages the pipeline's state.json file."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._last_summary: Optional[str] = None
        self._runs: list[RunRecord] = []

    def load(self) -> None:
        """Load state from disk."""
        if not self._path.exists():
            return

        with open(self._path, encoding="utf-8") as f:
            data = json.load(f)

        self._last_summary = data.get("last_summary")

        for r in data.get("runs", []):
            self._runs.append(
                RunRecord(
                    timestamp=r["timestamp"],
                    summaries_reviewed=r.get("summaries_reviewed", []),
                    commits_created=r.get("commits_created", 0),
                    errors=r.get("errors", []),
                )
            )

    def save(self) -> None:
        """Persist state to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "last_summary": self._last_summary,
            "runs": [asdict(r) for r in self._runs],
        }

        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.debug("State saved to %s", self._path)

    @property
    def last_summary_date(self) -> Optional[date]:
        """Date of the last processed summary."""
        if self._last_summary:
            return date.fromisoformat(self._last_summary)
        return None

    @last_summary_date.setter
    def last_summary_date(self, value: date) -> None:
        self._last_summary = value.isoformat()

    def record_run(
        self,
        summaries: list[str] | None = None,
        commits: int = 0,
        errors: list[str] | None = None,
    ) -> None:
        """Record a pipeline run."""
        self._runs.append(
            RunRecord(
                timestamp=datetime.now().isoformat(),
                summaries_reviewed=summaries or [],
                commits_created=commits,
                errors=errors or [],
            )
        )
