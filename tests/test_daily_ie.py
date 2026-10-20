"""Tests for the Ireland (IE) daily discovery pagination."""

import json
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock
from unittest.mock import Mock

import pytest

from legalize.config import Config, CountryConfig
from legalize.fetcher.ie import bootstrap, daily as ie_daily, revised
from legalize.fetcher.ie.history import REVISED_INDEX, revised_catalog
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


# The daily is driven by what changed at the source, never by the API's date cursor:
# legislative effects and LRC versions arrive well after their source dates.

CATALOG = b"""<table><tr data-eli="1995/act/2/en">
<td class="updated">1 April 2021</td><td><a
href="https://revisedacts.lawreform.ie/eli/1995/act/2/front/revised/en/html">HTML</a>
</td></tr></table>"""


def _directory(cursor: str, rows: str = "") -> bytes:
    return (
        f'<div class="outline-lead"><h3 class="post2006"><b><span>Updated to {cursor}</span>'
        f"<span>(Act No. 36 of 2026 and S.I. No. 512 of 2026)</span></b></h3></div>"
        f"<table>{rows}</table>"
    ).encode()


class _Source:
    """eISB and the LRC catalogue, by URL; records every page read."""

    def __init__(self, pages: dict[str, bytes], catalog: bytes = CATALOG):
        self._base_url = "https://www.irishstatutebook.ie"
        self.pages, self.catalog, self.read = pages, catalog, []

    def _get(self, url):
        self.read.append(url)
        if url == REVISED_INDEX:
            return self.catalog
        return self.pages[url.rsplit("/isbc/", 1)[-1]]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture(autouse=True)
def _no_baseline(monkeypatch, tmp_path):
    """Each test starts from the state it writes, not the corpus's real baseline."""
    monkeypatch.setattr(ie_daily, "BASELINE", tmp_path / "no-baseline.json")


def test_the_committed_baseline_describes_a_corpus():
    baseline = json.loads(Path(ie_daily.__file__).with_name("daily-baseline.json").read_text())
    assert baseline["cursor"] == "" and not baseline["pending"] and not baseline["rebuild"]
    assert len(baseline["pages"]) > 4000 and "cons" in baseline["pages"]
    assert all(
        len(digest) == 16
        for digest in [*baseline["pages"].values(), *baseline["catalogue"].values()]
    )


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


def _sources_path(config):
    return Path(config.get_country("ie").state_path).with_name("sources.json")


def _daily_sources(monkeypatch, *, dates=(), ids=(), pages=None, catalog=CATALOG, published=()):
    source = _Source(pages if pages is not None else {}, catalog)
    monkeypatch.setattr(ie_daily.ISBClient, "create", lambda _: source)
    monkeypatch.setattr(ie_daily.ISBDiscovery, "discover_all", lambda *args: iter(ids))
    monkeypatch.setattr(ie_daily, "resolve_dates_to_process", lambda *args: list(dates))
    monkeypatch.setattr(ie_daily, "_published", lambda *args: ((), set(published)))
    return source


def _read_state(config):
    state = StateStore(config.get_country("ie").state_path)
    state.load()
    return state


def test_a_directory_page_is_compared_without_the_banner_every_update_rewrites():
    old, new = (
        _directory("17 September 2026", "<tr>x</tr>"),
        _directory("6 October 2026", "<tr>x</tr>"),
    )
    assert old != new and ie_daily.content_digest(old) == ie_daily.content_digest(new)
    assert ie_daily.content_digest(new) != ie_daily.content_digest(_directory("6 October 2026"))
    cursor = ie_daily.directory_cursor(new)
    assert cursor == "6 October 2026 (Act No. 36 of 2026 and S.I. No. 512 of 2026)"
    with pytest.raises(ValueError, match="no 'Updated to' banner"):
        ie_daily.directory_cursor(b"<html>Maintenance</html>")


def test_each_norm_maps_to_the_page_fetch_effects_reads_and_back():
    index = b'<a href="/isbc/si2005_351-400.html">351-400</a>'
    get = {"si2005.html": index, "si1950.html": b"<p>no ranges</p>"}.__getitem__
    assert ie_daily.page_of("IE-2010-act-31", get) == "2010_31.html"
    assert ie_daily.page_of("IE-1929-act-P2", get) == "pa1929.html"
    assert ie_daily.page_of("IE-2001-act-C21", get) is None
    assert ie_daily.page_of("IE-1937-constitution", get) == "cons"
    assert ie_daily.page_of("IE-2005-si-360", get) == "si2005_351-400.html"
    assert ie_daily.page_of("IE-1950-si-12", get) == "si1950.html"

    published = {
        "IE-2010-act-31",
        "IE-1929-act-P2",
        "IE-2005-si-360",
        "IE-2005-si-12",
        "IE-1950-si-12",
    }
    on = ie_daily._Published(published, ["si2005_351-400.html"]).on
    assert on("2010_31.html") == {"IE-2010-act-31"} and on("2011_1.html") == set()
    assert on("pa1929.html") == {"IE-1929-act-P2"}
    assert on("si2005_351-400.html") == {"IE-2005-si-360"}
    assert on("si2005.html") == {"IE-2005-si-12"}  # not covered by a known range page
    assert on("si1950.html") == {"IE-1950-si-12"}


def test_only_what_changed_at_the_source_is_refreshed(daily_config, monkeypatch):
    # Every page carries the same cursor; only 2010/31's effects changed under it.
    unchanged = _directory("17 September 2026", "<tr>a</tr>")
    pages = {
        "1995_2.html": _directory("6 October 2026", "<tr>a</tr>"),
        "2010_31.html": _directory("6 October 2026", "<tr>b</tr>"),
    }
    Sources = ie_daily.Sources
    Sources(
        cursor="17 September 2026 (Act No. 36 of 2026 and S.I. No. 512 of 2026)",
        pages={
            "1995_2.html": ie_daily.content_digest(unchanged),
            "2010_31.html": ie_daily.content_digest(unchanged),
        },
        catalogue={"IE-1995-act-2": "stale"},
        next_status={"IE-2001-act-1": "2020-01-01", "IE-2099-act-1": "2099-01-01"},
    ).save(_sources_path(daily_config))
    published = {
        "IE-1995-act-2",
        "IE-2010-act-31",
        "IE-2001-act-1",
        "IE-2099-act-1",
        "IE-2003-act-9",
    }
    ids = ["IE-1995-act-2", "IE-2026-act-37", "IE-2026-act-38"]
    source = _daily_sources(monkeypatch, ids=ids, pages=pages, published=published)
    (Path(daily_config.get_country("ie").repo_path) / "coverage.json").write_text(
        json.dumps({"excluded": [{"identifier": "IE-2026-act-38", "reason": "Malformed footnote"}]})
    )
    refreshed = []
    monkeypatch.setattr(
        ie_daily,
        "refresh_norms",
        lambda config, batch, **kwargs: (
            refreshed.extend(batch),
            kwargs["outcomes"].update(dict.fromkeys(batch, "ok")),
            (len(batch), []),
        )[-1],
    )
    monkeypatch.setattr(ie_daily, "page_of", lambda norm_id, get: None)

    assert ie_daily.daily(daily_config) == 4
    # The LRC row changed, the directory content changed, a new Act, a status date passed.
    # Not: the unchanged page, the excluded Act, the future status date.
    assert sorted(refreshed) == [
        "IE-1995-act-2",
        "IE-2001-act-1",
        "IE-2010-act-31",
        "IE-2026-act-37",
    ]
    saved = Sources.load(_sources_path(daily_config))
    assert saved.pending == [] and saved.unswept == []
    assert saved.cursor.startswith("6 October 2026")
    assert saved.catalogue["IE-1995-act-2"] == ie_daily.rows_digest(
        revised_catalog(CATALOG)["IE-1995-act-2"]
    )

    # The cursor holds: no directory page is read again, nothing is refreshed.
    refreshed.clear()
    source.read.clear()
    published.add("IE-2026-act-37")  # committed by the first run
    assert ie_daily.daily(daily_config) == 0
    assert refreshed == []
    assert [url for url in source.read if "/isbc/" in url] == [
        "https://www.irishstatutebook.ie/isbc/1995_2.html"
    ]


def test_a_sweep_cut_by_the_budget_resumes_where_it_stopped(daily_config, monkeypatch):
    pages = {f"2000_{n}.html": _directory("6 October 2026", f"<tr>{n}</tr>") for n in range(1, 61)}
    ie_daily.Sources(cursor="old", pages=dict.fromkeys(pages, "x")).save(
        _sources_path(daily_config)
    )
    _daily_sources(monkeypatch, pages=pages, published={f"IE-2000-act-{n}" for n in range(1, 61)})
    daily_config.get_country("ie").max_workers = 1
    sources = ie_daily.Sources.load(_sources_path(daily_config))
    ticks = iter([0, 10**9])  # one batch of 25, then the budget is gone
    monkeypatch.setattr(ie_daily.time, "monotonic", lambda: next(ticks, 10**9))
    ie_daily.find_changes(
        daily_config.get_country("ie"), sources, {f"IE-2000-act-{n}" for n in range(1, 61)}, until=1
    )
    assert len(sources.unswept) == 35 and len(sources.pending) == 25


def test_a_history_that_gains_an_earlier_event_waits_for_a_local_rebuild(daily_config, monkeypatch):
    ie_daily.Sources(pending=["IE-2010-act-31", "IE-2024-act-1", "IE-2024-act-2"]).save(
        _sources_path(daily_config)
    )
    _daily_sources(monkeypatch, pages={"si2026.html": _directory("6 October 2026")})
    record = Path(daily_config.get_country("ie").data_dir) / "failures"

    def refresh(config, batch, *, known, outcomes, **kwargs):
        outcomes.update(
            {
                "IE-2010-act-31": "rebuild: source history gained an earlier event",
                "IE-2024-act-1": "failed",
                "IE-2024-act-2": "failed",
            }
        )
        from legalize.coverage import record_failure
        import requests

        record_failure(
            config.get_country("ie").data_dir, "IE-2024-act-1", requests.ConnectionError("DNS")
        )
        record_failure(
            config.get_country("ie").data_dir, "IE-2024-act-2", ValueError("Malformed footnote")
        )
        return 0, ["IE-2010-act-31: source history gained an earlier event"]

    monkeypatch.setattr(ie_daily, "refresh_norms", refresh)
    daily_config.get_country("ie").max_workers = 3
    with pytest.raises(NothingPublished):
        ie_daily.daily(daily_config)
    saved = ie_daily.Sources.load(_sources_path(daily_config))
    assert saved.rebuild == {"IE-2010-act-31": "source history gained an earlier event"}
    assert saved.pending == ["IE-2024-act-1"]  # a network failure is retried; the other is excluded
    assert record.exists()


def test_failed_catalog_is_not_a_successful_empty_day(daily_config, monkeypatch):
    _daily_sources(monkeypatch, dates=[date(2025, 1, 2)], catalog=b"<html>Maintenance</html>")
    refresh = Mock()
    monkeypatch.setattr(ie_daily, "refresh_norms", refresh)
    with pytest.raises(NothingPublished, match="catalogue contains no English Acts"):
        ie_daily.daily(daily_config)
    refresh.assert_not_called()
    assert _read_state(daily_config).last_summary_date == date(2025, 1, 1)
    assert not _sources_path(daily_config).exists()  # a failed read keeps the last state


def test_dry_run_preserves_law_data_repository_cursor_and_state(daily_config, monkeypatch):
    _daily_sources(
        monkeypatch,
        dates=[date(2025, 1, 2)],
        ids=["IE-2026-act-37"],
        pages={"si2026.html": _directory("6 October 2026")},
    )
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
    assert not _sources_path(daily_config).exists()
    assert _read_state(daily_config).last_summary_date == date(2025, 1, 1)


def test_refresh_does_not_fetch_a_dependency_the_repo_already_holds(daily_config, monkeypatch):
    fetched = []
    monkeypatch.setattr(
        bootstrap, "generic_fetch_one", lambda config, cc, key: fetched.append(key) or object()
    )
    monkeypatch.setattr(
        bootstrap,
        "load_norma_from_json",
        lambda path: (
            Mock(reforms=[Mock(norm_id="IE-2020-si-1"), Mock(norm_id="IE-2020-si-2")])
            if "act" in path.name
            else Mock(reforms=[])
        ),
    )
    assert bootstrap.fetch_dependencies(
        daily_config, ["IE-2024-act-1"], known={"IE-2020-si-1", "IE-2024-act-1"}
    ) == ["IE-2020-si-2", "IE-2024-act-1"]
    assert fetched == ["IE-2020-si-2"]


def test_refresh_reports_each_norms_outcome(daily_config, monkeypatch):
    from legalize.pipeline import HistoryMismatch

    monkeypatch.setattr(
        ie_daily,
        "generic_fetch_one",
        lambda config, cc, key, force: None if key.endswith("-3") else object(),
    )
    monkeypatch.setattr(
        bootstrap, "fetch_dependencies", lambda config, ids, known: ["IE-2020-si-9", *ids]
    )

    def commit(config, country, norm_id):
        if norm_id.endswith("-2"):
            raise HistoryMismatch("gained an earlier event")
        return 1

    monkeypatch.setattr(ie_daily, "commit_one", commit)
    outcomes = {}
    created, errors = ie_daily.refresh_norms(
        daily_config,
        ["IE-2024-act-1", "IE-2024-act-2", "IE-2024-act-3"],
        known={"IE-2024-act-1"},
        outcomes=outcomes,
    )
    assert created == 2 and len(errors) == 2
    assert outcomes == {
        "IE-2024-act-3": "failed",
        "IE-2020-si-9": "ok",
        "IE-2024-act-1": "ok",
        "IE-2024-act-2": "rebuild: gained an earlier event",
    }


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

    def dependencies(config, ids, known):
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

    def dependencies(config, ids, known):
        gc.collect()
        assert len(references) == len(identifiers)
        assert all(reference() is None for reference in references)
        return ids

    monkeypatch.setattr(ie_daily, "generic_fetch_one", fetch)
    monkeypatch.setattr(bootstrap, "fetch_dependencies", dependencies)
    monkeypatch.setattr(ie_daily, "commit_one", lambda *args: 1)
    assert ie_daily.refresh_norms(daily_config, identifiers) == (len(identifiers), [])


def test_missing_dependency_stops_commits_and_keeps_the_norm_queued(daily_config, monkeypatch):
    ie_daily.Sources(pending=["IE-2024-act-1"]).save(_sources_path(daily_config))
    _daily_sources(
        monkeypatch, dates=[date(2025, 1, 2)], pages={"si2026.html": _directory("6 October 2026")}
    )
    monkeypatch.setattr(ie_daily, "generic_fetch_one", Mock(return_value=object()))
    monkeypatch.setattr(
        bootstrap,
        "fetch_dependencies",
        Mock(side_effect=NothingPublished("amendment sources unavailable")),
    )
    commit = Mock()
    monkeypatch.setattr(ie_daily, "commit_one", commit)
    with pytest.raises(NothingPublished, match="amendment sources unavailable"):
        ie_daily.daily(daily_config)
    commit.assert_not_called()
    assert _read_state(daily_config).last_summary_date == date(2025, 1, 1)
    assert ie_daily.Sources.load(_sources_path(daily_config)).pending == ["IE-2024-act-1"]


def test_revised_command_uses_complete_shared_histories_and_reports_real_count(
    daily_config, monkeypatch
):
    monkeypatch.setattr(revised.ISBClient, "create", lambda _: _Source({}))
    refresh = Mock(return_value=(4, []))
    monkeypatch.setattr(revised, "refresh_norms", refresh)
    assert revised.apply_revised_acts(daily_config, limit=1) == 4
    refresh.assert_called_once_with(daily_config, ["IE-1995-act-2"], dry_run=False)
    assert _read_state(daily_config).last_summary_date == date(2025, 1, 1)


def test_revised_command_propagates_missing_catalog(daily_config, monkeypatch):
    monkeypatch.setattr(
        revised.ISBClient, "create", lambda _: _Source({}, b"<html>Maintenance</html>")
    )
    with pytest.raises(NothingPublished, match="Revised Acts catalogue"):
        revised.apply_revised_acts(daily_config)


def test_daily_publishes_a_new_act_once_and_carries_coverage_forward(daily_config, monkeypatch):
    import base64
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
    cc = daily_config.get_country("ie")
    repo = Path(cc.repo_path)
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    previous = {
        "spec_version": "0.5",
        "as_of": "2026-10-19",
        "source_index": "x",
        "discovered": 1,
        "published": 0,
        "excluded": [{"identifier": identifier, "reason": "DNS", "transient": True}],
        "laws_with_version_gaps": 0,
        "version_gaps": 0,
        "laws_with_undated_amendments": 0,
        "undated_amendments": 0,
    }
    (repo / "coverage.json").write_text(json.dumps(previous))
    subprocess.run(["git", "-C", str(repo), "add", "coverage.json"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "-m",
            "meta",
        ],
        check=True,
    )
    pages = {
        "2015_29.html": _directory("6 October 2026"),
        "si2026.html": _directory("6 October 2026"),
    }
    _daily_sources(monkeypatch, ids=["IE-1937-constitution", identifier], pages=pages)
    monkeypatch.setattr(
        ie_daily, "_published", __import__("legalize.pipeline", fromlist=["_published"])._published
    )
    monkeypatch.setattr(ie_daily.ISBDiscovery, "discover_all", lambda *args: iter([identifier]))

    def fetch(config, country, norm_id, force=False):
        assert force and country == "ie" and norm_id == identifier
        save_structured_json(config.get_country("ie").data_dir, norm)
        return norm

    monkeypatch.setattr(ie_daily, "generic_fetch_one", fetch)
    monkeypatch.setattr(bootstrap, "fetch_dependencies", lambda config, ids, known: ids)
    assert ie_daily.daily(daily_config) == 2  # its two versions; coverage.json follows them
    path = next((repo / "ie").rglob("*.md"))
    assert "The preserved consolidated body." in path.read_text()
    log = subprocess.check_output(["git", "-C", str(repo), "log", "--format=%B"], text=True)
    assert "Source-Id: revised-IE-2015-act-29@2023-07-03" in log
    assert "Source-Date: 2015-07-27" in log
    coverage = json.loads((repo / "coverage.json").read_text())
    assert coverage["published"] == 1 and coverage["excluded"] == []
    assert ie_daily.Sources.load(_sources_path(daily_config)).pages["2015_29.html"]

    before = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"])
    assert ie_daily.daily(daily_config) == 0
    assert subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]) == before


def test_the_parser_revision_covers_every_module_a_parse_imports():
    import re as regex

    from legalize.fetcher.ie import history

    directory = Path(history.__file__).parent
    for name in history.PARSE_MODULES:
        imported = regex.findall(
            r"legalize\.fetcher\.ie\.(\w+)", (directory / f"{name}.py").read_text()
        )
        assert set(imported) <= set(history.PARSE_MODULES), (name, imported)


def test_a_refused_directory_page_waits_for_the_next_run(daily_config, monkeypatch):
    import requests

    pages = {f"2000_{n}.html": _directory("6 October 2026", f"<tr>{n}</tr>") for n in range(1, 4)}
    published = {"IE-2000-act-1", "IE-2000-act-2", "IE-2000-act-3"}
    source = _daily_sources(monkeypatch, pages=pages, published=published)
    get, cc = source._get, daily_config.get_country("ie")

    def refuse(url):
        if url.endswith("/2000_2.html"):
            raise requests.HTTPError("403 Client Error: Forbidden")
        return get(url)

    source._get = refuse
    sources = ie_daily.Sources(cursor="old", pages=dict.fromkeys(pages, "x"))
    ie_daily.find_changes(cc, sources, published, until=float("inf"))
    assert sources.unswept == ["2000_2.html"]  # retried alone, refused again, kept
    assert sources.pending == ["IE-2000-act-1", "IE-2000-act-3"]

    calls = []

    def refuse_after_the_probe(url):
        calls.append(url)
        if "/isbc/" in url and len([c for c in calls if "/isbc/" in c]) > 1:
            raise requests.HTTPError("403 Client Error: Forbidden")
        return get(url)

    source._get = refuse_after_the_probe
    sources = ie_daily.Sources(cursor="old", pages=dict.fromkeys(pages, "x"))
    with pytest.raises(RuntimeError, match="refused every directory page"):
        ie_daily.find_changes(cc, sources, published, until=float("inf"))


def test_a_rebuilt_corpus_discards_the_state_of_the_history_it_replaced(
    daily_config, monkeypatch, tmp_path
):
    import subprocess

    repo = Path(daily_config.get_country("ie").repo_path)

    def commit(message):
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "-qm",
                message,
            ],
            check=True,
        )
        return subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip()

    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    (repo / "a.txt").write_text("old")
    old = commit("old history")
    ie_daily.Sources(tip=old, rebuild={"IE-2010-act-31": "gained an earlier event"}).save(
        _sources_path(daily_config)
    )
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--orphan", "rebuilt"], check=True)
    (repo / "a.txt").write_text("new")
    new = commit("rebuilt history")
    baseline = tmp_path / "baseline.json"
    ie_daily.Sources(cursor="6 October 2026 (Act No. 36 of 2026 and S.I. No. 512 of 2026)").save(
        baseline
    )
    monkeypatch.setattr(ie_daily, "BASELINE", baseline)
    _daily_sources(monkeypatch, pages={"si2026.html": _directory("6 October 2026")})
    monkeypatch.setattr(ie_daily, "refresh_norms", Mock(return_value=(0, [])))
    ie_daily.daily(daily_config)
    saved = ie_daily.Sources.load(_sources_path(daily_config))
    assert saved.rebuild == {} and saved.tip == new
