"""Tests for the Ireland (IE) daily discovery pagination."""

from datetime import date
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from threading import Event, Lock
from unittest.mock import Mock

import pytest

from legalize.config import Config, CountryConfig
from legalize.fetcher.ie import bootstrap, daily as ie_daily, revised
from legalize.fetcher.ie.history import REVISED_INDEX
from legalize.pipeline import NothingPublished
from legalize.state.store import StateStore


from legalize.fetcher.ie.discovery import ISBDiscovery


def _make_page(acts: list[tuple[int, int]], is_last: bool = False) -> dict:
    """Build a fake Oireachtas API page.

    Each act is (year, number). If is_last is True, the page has fewer
    results than _PAGE_SIZE so the paginator knows to stop.
    """
    results = []
    for year, num in acts:
        results.append(
            {
                "bill": {
                    "act": {
                        "actYear": str(year),
                        "actNo": str(num),
                    }
                }
            }
        )
    return {
        "results": results,
        "head": {"counts": {"billCount": 999}},
    }


class _FakeClient:
    """Fake ISBClient that returns pre-configured pages."""

    def __init__(self, pages: list[dict]):
        self._pages = list(pages)
        self._call_count = 0

    def get_updated_since(self, since_date, *, skip=0, limit=50, **params):
        idx = skip // limit if limit else 0
        if idx >= len(self._pages):
            return {"results": []}
        self._call_count += 1
        return self._pages[idx]


class TestDiscoverDailyPagination:
    """discover_daily must paginate across multiple API pages."""

    def test_two_pages(self):
        """Two full pages of results yields norm IDs from both."""
        # Page 1: 50 acts (full page → continues)
        page1_acts = [(2024, i) for i in range(1, 51)]
        # Page 2: 10 acts (partial page → stops)
        page2_acts = [(2025, i) for i in range(1, 11)]

        client = _FakeClient(
            [
                _make_page(page1_acts),
                _make_page(page2_acts, is_last=True),
            ]
        )

        discovery = ISBDiscovery()
        norm_ids = list(discovery.discover_daily(client, date(2024, 1, 1)))

        assert len(norm_ids) == 60
        # First page
        assert "IE-2024-act-1" in norm_ids
        assert "IE-2024-act-50" in norm_ids
        # Second page
        assert "IE-2025-act-1" in norm_ids
        assert "IE-2025-act-10" in norm_ids

        assert client._call_count == 2

    def test_single_partial_page(self):
        """A single partial page stops after one request."""
        client = _FakeClient(
            [
                _make_page([(2024, 1), (2024, 2)], is_last=True),
            ]
        )

        discovery = ISBDiscovery()
        norm_ids = list(discovery.discover_daily(client, date(2024, 1, 1)))

        assert norm_ids == ["IE-2024-act-1", "IE-2024-act-2"]
        assert client._call_count == 1

    def test_empty_results(self):
        """Empty results returns nothing."""
        client = _FakeClient([{"results": []}])

        discovery = ISBDiscovery()
        norm_ids = list(discovery.discover_daily(client, date(2024, 1, 1)))

        assert norm_ids == []

    def test_skips_bills_without_act(self):
        """Bills without an act record are silently skipped."""
        page = {
            "results": [
                {"bill": {"act": {"actYear": "2024", "actNo": "1"}}},
                {"bill": {}},  # No act
                {"bill": {"act": {"actYear": "2024", "actNo": "3"}}},
            ],
            "head": {},
        }
        client = _FakeClient([page])

        discovery = ISBDiscovery()
        norm_ids = list(discovery.discover_daily(client, date(2024, 1, 1)))

        assert norm_ids == ["IE-2024-act-1", "IE-2024-act-3"]


# The full refresh is deliberately independent of the supplementary API cursor:
# legislative effects and LRC versions may arrive well after their source dates.


CATALOG = b"""<table><tr data-eli="1995/act/2/en">
<td class="updated">1 April 2021</td><td><a
href="https://revisedacts.lawreform.ie/eli/1995/act/2/front/revised/en/html">HTML</a>
</td></tr></table>"""


@pytest.fixture
def daily_config(tmp_path):
    repo, data = tmp_path / "repo", tmp_path / "data"
    repo.mkdir()
    (data / "json").mkdir(parents=True)
    state_path = tmp_path / "state.json"
    state = StateStore(state_path)
    state.last_summary_date = date(2025, 1, 1)
    state.save()
    return Config(
        countries={
            "ie": CountryConfig(repo_path=str(repo), data_dir=str(data), state_path=str(state_path))
        }
    )


def _daily_sources(monkeypatch, *, dates=(), ids=(), catalog=CATALOG):
    client = Mock()
    client._get.return_value = catalog
    monkeypatch.setattr(ie_daily.ISBClient, "create", lambda _: nullcontext(client))
    monkeypatch.setattr(ie_daily.ISBDiscovery, "discover_all", lambda *args: iter(ids))
    monkeypatch.setattr(ie_daily, "resolve_dates_to_process", lambda *args: list(dates))
    return client


def _read_state(config):
    state = StateStore(config.get_country("ie").state_path)
    state.load()
    return state


def test_late_lrc_and_all_act_namespaces_refresh_when_date_cursor_is_current(
    daily_config, monkeypatch
):
    ids = ["IE-1937-constitution", "IE-2024-act-1", "IE-2019-act-C38", "IE-2023-act-P1"]
    client = _daily_sources(monkeypatch, ids=ids)
    cc = daily_config.get_country("ie")
    (Path(cc.data_dir) / "json" / "IE-2024-si-356.json").write_text("{}")
    fetch = Mock(return_value=object())
    commit = Mock(return_value=1)
    monkeypatch.setattr(ie_daily, "generic_fetch_one", fetch)
    monkeypatch.setattr(ie_daily, "commit_one", commit)
    closure = Mock(side_effect=lambda config, ids: [*ids, "IE-2020-si-1"])
    monkeypatch.setattr(bootstrap, "fetch_dependencies", closure)

    assert ie_daily.daily(daily_config) == 7
    expected = set(ids) | {"IE-1995-act-2", "IE-2024-si-356"}
    assert {call.args[2] for call in fetch.call_args_list} == expected
    assert all(call.kwargs == {"force": True} for call in fetch.call_args_list)
    assert {call.args[2] for call in commit.call_args_list} == expected | {"IE-2020-si-1"}
    assert len(commit.call_args_list) == 7
    assert not client.get_updated_since.called
    client._get.assert_called_once_with(REVISED_INDEX)
    assert _read_state(daily_config).last_summary_date == date(2025, 1, 1)


@pytest.mark.parametrize("raise_error", [False, True])
def test_partial_failure_preserves_resume_cursor_and_records_failure(
    daily_config, monkeypatch, raise_error
):
    _daily_sources(monkeypatch, dates=[date(2025, 1, 2)], ids=["IE-2024-act-1"])
    daily_config.get_country("ie").max_workers = 2

    def fetch(config, country, identifier, **kwargs):
        if identifier == "IE-2024-act-1":
            if raise_error:
                raise RuntimeError("source unavailable")
            return None
        return object()

    monkeypatch.setattr(ie_daily, "generic_fetch_one", fetch)
    closure = Mock(side_effect=lambda config, ids: ids)
    monkeypatch.setattr(bootstrap, "fetch_dependencies", closure)
    monkeypatch.setattr(ie_daily, "commit_one", Mock(return_value=1))

    assert ie_daily.daily(daily_config) == 1
    assert closure.call_args.args[1] == ["IE-1995-act-2"]
    state = _read_state(daily_config)
    assert state.last_summary_date == date(2025, 1, 1)
    assert "IE-2024-act-1" in state._runs[-1].errors[0]


def test_parallel_refresh_limits_workers_and_waits_for_fetch_and_dependencies(
    daily_config, monkeypatch
):
    daily_config.get_country("ie").max_workers = 2
    identifiers = [f"IE-2024-act-{number}" for number in range(1, 5)]
    capacity_reached, release_fetch = Event(), Event()
    dependencies_started, release_dependencies = Event(), Event()
    lock = Lock()
    active = peak = 0
    fetched = []

    def fetch(config, country, identifier, *, force):
        nonlocal active, peak
        assert force and country == "ie"
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 2:
                capacity_reached.set()
        assert release_fetch.wait(5), "fetch phase was not released"
        with lock:
            active -= 1
            fetched.append(identifier)
        return object()

    def dependencies(config, ids):
        assert sorted(fetched) == identifiers and active == 0
        assert ids == identifiers
        dependencies_started.set()
        assert release_dependencies.wait(5), "dependency phase was not released"
        return ["IE-2024-si-1", *ids]

    commit = Mock(return_value=1)
    monkeypatch.setattr(ie_daily, "generic_fetch_one", fetch)
    monkeypatch.setattr(bootstrap, "fetch_dependencies", dependencies)
    monkeypatch.setattr(ie_daily, "commit_one", commit)
    with ThreadPoolExecutor(max_workers=1) as driver:
        result = driver.submit(ie_daily.refresh_norms, daily_config, [*identifiers, identifiers[0]])
        try:
            assert capacity_reached.wait(5), "fetches did not run concurrently"
            assert not dependencies_started.is_set()
            commit.assert_not_called()
            release_fetch.set()
            assert dependencies_started.wait(5), "dependency closure did not start"
            commit.assert_not_called()
        finally:
            release_fetch.set()
            release_dependencies.set()
        assert result.result(timeout=5) == (5, [])
    assert peak == 2
    assert [call.args[2] for call in commit.call_args_list] == ["IE-2024-si-1", *identifiers]


def test_missing_dependency_stops_commits_and_does_not_advance_cursor(daily_config, monkeypatch):
    _daily_sources(monkeypatch, dates=[date(2025, 1, 2)])
    monkeypatch.setattr(ie_daily, "generic_fetch_one", Mock(return_value=object()))
    monkeypatch.setattr(
        bootstrap, "fetch_dependencies", Mock(side_effect=ValueError("missing amending SI"))
    )
    commit = Mock()
    monkeypatch.setattr(ie_daily, "commit_one", commit)
    with pytest.raises(NothingPublished, match="missing amending SI"):
        ie_daily.daily(daily_config)
    commit.assert_not_called()
    assert _read_state(daily_config).last_summary_date == date(2025, 1, 1)


def test_refresh_releases_parsed_histories_before_dependency_phase(daily_config, monkeypatch):
    import gc
    import weakref

    class History:
        pass

    references = []
    identifiers = [f"IE-2024-act-{number}" for number in range(1, 51)]
    daily_config.get_country("ie").max_workers = 4

    def fetch(*args, **kwargs):
        history = History()
        references.append(weakref.ref(history))
        return history

    def dependencies(config, ids):
        gc.collect()
        assert len(references) == len(identifiers)
        assert all(reference() is None for reference in references)
        return ids

    monkeypatch.setattr(ie_daily, "generic_fetch_one", fetch)
    monkeypatch.setattr(bootstrap, "fetch_dependencies", dependencies)
    monkeypatch.setattr(ie_daily, "commit_one", lambda *args: 1)
    assert ie_daily.refresh_norms(daily_config, identifiers) == (len(identifiers), [])


def test_failed_catalog_is_not_a_successful_empty_day(daily_config, monkeypatch):
    _daily_sources(monkeypatch, dates=[date(2025, 1, 2)], catalog=b"<html>Maintenance</html>")
    fetch = Mock()
    monkeypatch.setattr(ie_daily, "generic_fetch_one", fetch)
    with pytest.raises(NothingPublished, match="catalogue contains no English Acts"):
        ie_daily.daily(daily_config)
    fetch.assert_not_called()
    assert _read_state(daily_config).last_summary_date == date(2025, 1, 1)


def test_dry_run_preserves_law_data_repository_and_cursor(daily_config, monkeypatch):
    _daily_sources(monkeypatch, dates=[date(2025, 1, 2)])
    fetch, closure, commit = Mock(), Mock(), Mock()
    monkeypatch.setattr(ie_daily, "generic_fetch_one", fetch)
    monkeypatch.setattr(bootstrap, "fetch_dependencies", closure)
    monkeypatch.setattr(ie_daily, "commit_one", commit)
    assert ie_daily.daily(daily_config, dry_run=True) == 0
    for operation in (fetch, closure, commit):
        operation.assert_not_called()
    cc = daily_config.get_country("ie")
    assert list((Path(cc.data_dir) / "json").iterdir()) == []
    assert not (Path(cc.repo_path) / ".git").exists()
    assert _read_state(daily_config).last_summary_date == date(2025, 1, 1)


def test_complete_refresh_advances_cursor_only_after_commits(daily_config, monkeypatch):
    _daily_sources(monkeypatch, dates=[date(2025, 1, 2), date(2025, 1, 3)])
    monkeypatch.setattr(ie_daily, "generic_fetch_one", Mock(return_value=object()))
    monkeypatch.setattr(bootstrap, "fetch_dependencies", lambda config, ids: ids)

    def commit(*args):
        assert _read_state(daily_config).last_summary_date == date(2025, 1, 1)
        return 1

    monkeypatch.setattr(ie_daily, "commit_one", commit)
    assert ie_daily.daily(daily_config) == 1
    assert _read_state(daily_config).last_summary_date == date(2025, 1, 3)


def test_revised_command_uses_complete_shared_histories_and_reports_real_count(
    daily_config, monkeypatch
):
    _daily_sources(monkeypatch)
    refresh = Mock(return_value=(4, []))
    monkeypatch.setattr(revised, "refresh_norms", refresh)
    assert revised.apply_revised_acts(daily_config, limit=1) == 4
    refresh.assert_called_once_with(daily_config, ["IE-1995-act-2"], dry_run=False)
    assert _read_state(daily_config).last_summary_date == date(2025, 1, 1)


def test_revised_command_propagates_missing_catalog(daily_config, monkeypatch):
    _daily_sources(monkeypatch, catalog=b"<html>Maintenance</html>")
    with pytest.raises(NothingPublished, match="Revised Acts catalogue"):
        revised.apply_revised_acts(daily_config)


def test_daily_replay_preserves_source_dates_history_and_idempotency(daily_config, monkeypatch):
    import base64
    import json
    import subprocess

    from legalize.fetcher.ie import history
    from legalize.storage import save_structured_json

    identifier = "IE-2015-act-29"
    raw = (Path(__file__).parent / "fixtures/ie/sample-environment-2015.xml").read_bytes()
    encoded = base64.b64encode(raw).decode()
    current = b"""<div class="frontmatter"><p class="updatedto">Updated to 3 July 2023</p>
    </div><div class="body"><div class="section"><div class="title">Current rule</div>
    <div class="number">1.</div><p>The preserved consolidated body.</p></div></div>"""
    envelope = json.dumps(
        {
            "legalize_ie": 1,
            "identifier": identifier,
            "metadata": encoded,
            "versions": [
                {"format": "enacted", "url": "https://source.test/original", "data": encoded},
                {
                    "format": "revised_html",
                    "url": "https://source.test/current",
                    "catalog_date": "2023-07-03",
                    "data": base64.b64encode(current).decode(),
                },
            ],
            "effects": [],
        }
    ).encode()
    norm = history._parse(envelope)
    _daily_sources(monkeypatch, ids=[identifier])
    monkeypatch.setattr(ie_daily, "_inventory", lambda *args: [identifier])

    def fetch(config, country, norm_id, force=False):
        assert force and country == "ie" and norm_id == identifier
        save_structured_json(config.get_country("ie").data_dir, norm)
        return norm

    monkeypatch.setattr(ie_daily, "generic_fetch_one", fetch)
    assert ie_daily.daily(daily_config) == 2
    cc = daily_config.get_country("ie")
    repo = Path(cc.repo_path)
    path = next((repo / "ie").rglob("*.md"))
    assert "The preserved consolidated body." in path.read_text()
    assert 'text_state: "current"' in path.read_text()
    log = subprocess.check_output(["git", "-C", str(repo), "log", "--format=%B"], text=True)
    assert "IE-DAILY" not in log
    assert "Source-Id: revised-IE-2015-act-29@2023-07-03" in log
    assert "Source-Date: 2015-07-27" in log
    assert "Source-Date: 2023-07-03" not in log
    before = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"])
    assert ie_daily.daily(daily_config) == 0
    assert subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]) == before
    assert "The preserved consolidated body." in path.read_text()
