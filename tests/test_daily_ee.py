"""Tests for the Estonia daily update."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

from legalize.fetcher.ee.daily import _build_group_map


class TestBuildGroupMap:
    def test_empty_directory(self, tmp_path: Path):
        empty = tmp_path / "ee"
        empty.mkdir()
        assert _build_group_map(empty) == {}

    def test_nonexistent_directory(self, tmp_path: Path):
        assert _build_group_map(tmp_path / "nope") == {}

    def test_single_file_with_group_id(self, tmp_path: Path):
        ee = tmp_path / "ee"
        ee.mkdir()
        (ee / "115052015002.md").write_text(
            "---\n"
            'title: "Eesti Vabariigi põhiseadus"\n'
            'identifier: "115052015002"\n'
            'country: "ee"\n'
            'group_id: "151381"\n'
            'rank: "seadus"\n'
            "---\n"
            "# Content\n"
        )
        result = _build_group_map(ee)
        assert result == {"151381": "115052015002"}

    def test_multiple_files(self, tmp_path: Path):
        ee = tmp_path / "ee"
        ee.mkdir()
        for filename, gid in [
            ("115052015002.md", "151381"),
            ("122122025002.md", "162500"),
            ("118122025017.md", "160001"),
        ]:
            (ee / filename).write_text(
                f'---\ntitle: "Test"\nidentifier: "{filename[:-3]}"\n'
                f'country: "ee"\ngroup_id: "{gid}"\nrank: "seadus"\n---\n# Content\n'
            )
        result = _build_group_map(ee)
        assert result == {
            "151381": "115052015002",
            "162500": "122122025002",
            "160001": "118122025017",
        }

    def test_file_without_group_id(self, tmp_path: Path):
        ee = tmp_path / "ee"
        ee.mkdir()
        (ee / "nogroup.md").write_text(
            '---\ntitle: "Old law"\nidentifier: "nogroup"\n'
            'country: "ee"\nrank: "seadus"\n---\n# Content\n'
        )
        result = _build_group_map(ee)
        assert result == {}

    def test_group_id_quoted_and_unquoted(self, tmp_path: Path):
        ee = tmp_path / "ee"
        ee.mkdir()
        (ee / "a.md").write_text('---\ngroup_id: "111"\n---\n')
        (ee / "b.md").write_text("---\ngroup_id: 222\n---\n")
        result = _build_group_map(ee)
        assert result == {"111": "a", "222": "b"}


def test_an_empty_group_map_stops_the_run(tmp_path, monkeypatch):
    """The map is read off the working tree, and CI clones it sparsely.

    Empty, every version falls through to the "brand new law" branch of
    _process_version: a duplicate file named after the version id, committed as
    [bootstrap] instead of [reform] — one new wrong law per reform, in green.
    """
    import pytest

    from legalize.config import Config, CountryConfig, GitConfig
    from legalize.fetcher.ee import daily as ee_daily

    repo, data = tmp_path / "repo", tmp_path / "data"
    (repo / "ee").mkdir(parents=True)  # bootstrapped, but nothing visible in the cone
    legi = data / "legi"
    legi.mkdir(parents=True)
    (legi / "one.xml").write_bytes(b"<x/>")

    config = Config(
        git=GitConfig(),
        countries={
            "ee": CountryConfig(
                repo_path=str(repo),
                data_dir=str(data),
                state_path=str(tmp_path / "state.json"),
            )
        },
    )

    discovery = MagicMock()
    discovery.ensure_bulk_dump.side_effect = RuntimeError("no network in tests")
    monkeypatch.setattr(ee_daily.RTDiscovery, "create", lambda cc: discovery)

    widened: list[str] = []
    monkeypatch.setattr(ee_daily.GitRepo, "ensure_visible", lambda self, d: widened.append(d))

    with pytest.raises(RuntimeError, match="published as a new law"):
        ee_daily.daily(config, target_date=date(2026, 4, 1))

    # And the cone is widened before the directory is read, or the map is empty
    # on every CI run by construction.
    assert widened == ["ee"]
