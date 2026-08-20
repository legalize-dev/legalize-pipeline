"""Tests for the stall alert: a daily that produces nothing must go red.

Seven country dailies exited 0 every morning for two months while their
repos stood still. A quiet source and a broken fetcher produced byte-for-byte
identical output, so nothing ever surfaced. These tests pin the signal that
tells them apart.
"""

from __future__ import annotations

import os
import subprocess
from datetime import date, timedelta

import pytest

from legalize.cli import _report_freshness
from legalize.config import CountryConfig, load_config
from legalize.config import Config as PipelineConfig
from legalize.pipeline import days_since_last_norm

TODAY = date.today()


def _repo_with(tmp_path, *source_dates, trailerless_tip: bool = False):
    """Build a country repo whose pipeline commits carry the given trailers."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Legalize"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "b@t.dev"], cwd=repo, capture_output=True)

    for source_date in source_dates:
        (repo / "law.md").write_text(str(source_date))
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        # The committer stamps the norm's own date, not wall-clock time.
        stamp = f"{source_date} 00:00:00 +0000"
        subprocess.run(
            ["git", "commit", "-m", f"[reform] x\n\nSource-Date: {source_date}"],
            cwd=repo,
            capture_output=True,
            check=True,
            env={**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp},
        )

    if trailerless_tip:
        (repo / "LICENSE").write_text("MIT")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Add LICENSE: MIT pipeline code"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
    return repo


def _config(repo, *, stall_alert_days: int = 14) -> PipelineConfig:
    return PipelineConfig(
        countries={"xx": CountryConfig(repo_path=str(repo), stall_alert_days=stall_alert_days)}
    )


class TestDaysSinceLastNorm:
    def test_counts_from_the_newest_captured_norm(self, tmp_path):
        repo = _repo_with(tmp_path, TODAY - timedelta(days=40), TODAY - timedelta(days=3))

        assert days_since_last_norm(_config(repo), "xx") == 3

    def test_a_docs_sweep_cannot_make_a_stale_repo_look_fresh(self, tmp_path):
        """The 2026-06-23 LICENSE sweep touched all 23 repos and hid this."""
        repo = _repo_with(tmp_path, TODAY - timedelta(days=60), trailerless_tip=True)

        assert days_since_last_norm(_config(repo), "xx") == 60

    def test_future_dated_trailers_are_not_counted_as_fresh(self, tmp_path):
        """A bootstrap-only repo is stale, however far in the future its tip is."""
        repo = _repo_with(tmp_path, TODAY - timedelta(days=90), date(2034, 1, 1))

        assert days_since_last_norm(_config(repo), "xx") == 90

    def test_none_when_the_repo_has_no_pipeline_commits(self, tmp_path):
        repo = _repo_with(tmp_path, trailerless_tip=True)

        assert days_since_last_norm(_config(repo), "xx") is None


class TestReportFreshness:
    def test_fails_the_run_once_past_the_threshold(self, tmp_path):
        config = _config(_repo_with(tmp_path, TODAY - timedelta(days=20)), stall_alert_days=14)

        with pytest.raises(SystemExit) as exc:
            _report_freshness(config, "xx", enforce=True)
        assert exc.value.code == 1

    def test_fails_when_there_is_nothing_to_measure(self, tmp_path):
        config = _config(_repo_with(tmp_path, trailerless_tip=True))

        with pytest.raises(SystemExit):
            _report_freshness(config, "xx", enforce=True)

    def test_quiet_but_within_threshold_passes(self, tmp_path):
        config = _config(_repo_with(tmp_path, TODAY - timedelta(days=13)), stall_alert_days=14)

        _report_freshness(config, "xx", enforce=True)

    def test_a_longer_per_country_threshold_is_honoured(self, tmp_path):
        """Sparse jurisdictions (ad, lu) must not cry wolf every fortnight."""
        config = _config(_repo_with(tmp_path, TODAY - timedelta(days=45)), stall_alert_days=90)

        _report_freshness(config, "xx", enforce=True)

    def test_reports_without_failing_when_not_enforcing(self, tmp_path):
        """--dry-run and --date backfills must not abort on the gap they close."""
        config = _config(_repo_with(tmp_path, TODAY - timedelta(days=200)))

        _report_freshness(config, "xx", enforce=False)


class TestStallAlertDaysConfig:
    def test_defaults_to_two_weeks(self):
        assert CountryConfig().stall_alert_days == 14

    def test_is_read_from_config_yaml(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "countries:\n"
            "  xx:\n"
            '    repo_path: "/tmp/xx"\n'
            "    stall_alert_days: 90\n"
            "  yy:\n"
            '    repo_path: "/tmp/yy"\n'
        )

        config = load_config(str(cfg))

        assert config.get_country("xx").stall_alert_days == 90
        assert config.get_country("yy").stall_alert_days == 14
