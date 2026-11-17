"""Daily discovery for the UK: the legislation.gov.uk publication log."""

from __future__ import annotations

import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
from lxml import etree

from legalize.fetcher.uk.client import LegislationGovUkClient
from legalize.fetcher.uk.discovery import LegislationGovUkDiscovery
from legalize.pipeline import generic_daily

BASE = "http://www.legislation.gov.uk"


def _page(number: int, entries: list[tuple[str, str]], *, served: int | None = None) -> bytes:
    """One page of /update/data.feed: (atom:id path, atom:updated) per entry."""
    body = "".join(
        f"<entry><id>{BASE}/{path}</id><updated>{updated}</updated></entry>"
        for path, updated in entries
    )
    return (
        '<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:leg="http://www.legislation.gov.uk/namespaces/legislation">'
        f"<leg:page>{served or number}</leg:page>{body}</feed>"
    ).encode()


class FakeLog:
    """The publication log, paged by 20 like the real one (here: by the list)."""

    def __init__(self, pages: list[bytes]) -> None:
        self.pages = pages
        self.asked: list[int] = []

    def get_update_feed(self, page: int = 1) -> bytes:
        self.asked.append(page)
        return self.pages[page - 1] if page <= len(self.pages) else _page(page, [])


# Newest first, as the site serves it. 17 Nov is the run's "after", 16 Nov the day.
LOG = FakeLog(
    [
        _page(
            1,
            [
                ("uksi/2008/1883/2008-07-15/data.xml/published/x", "2026-11-17T10:48:26.01158Z"),
                ("changes/affecting/uksi/2008/1909/published/x", "2026-11-17T10:41:58.128707Z"),
                # 00:30 in London summer time is still the 16th in UTC.
                ("ssi/2026/400/made/data.xml/published/x", "2026-11-17T00:30:00+01:00"),
            ],
        ),
        _page(
            2,
            [
                ("ukpga/2023/55/2026-11-13/data.xml/published/x", "2026-11-16T15:57:46Z"),
                ("ukpga/2023/55/2024-02-12/data.xml/published/x", "2026-11-16T15:57:46Z"),
                ("uksi/2008/1883/2008-07-01/data.xml/published/x", "2026-11-16T09:00:00Z"),
                ("eudr/2019/1/data.xml/published/x", "2026-11-16T08:00:00Z"),
            ],
        ),
        _page(3, [("wsi/2026/1/made/data.xml/published/x", "2026-11-15T23:59:59Z")]),
        _page(4, [("nisr/2026/2/made/data.xml/published/x", "2026-11-14T12:00:00Z")]),
    ]
)


def _discover(log: FakeLog, *days: date) -> list[list[str]]:
    discovery = LegislationGovUkDiscovery()
    return [list(discovery.discover_daily(log, day)) for day in days]


class TestDiscoverDaily:
    def setup_method(self):
        LOG.asked.clear()

    def test_keeps_the_laws_last_published_on_the_day(self):
        (found,) = _discover(LOG, date(2026, 11, 16))
        # Not uksi-2008-1883: it was published again on the 17th, and the text
        # the daily fetches is that one. Not the changes-only event or eudr.
        assert found == ["ssi-2026-400", "ukpga-2023-55"]

    def test_pages_back_until_the_day_is_behind_it(self):
        _discover(LOG, date(2026, 11, 16))
        assert LOG.asked == [1, 2, 3]

    def test_a_later_publication_waits_for_its_own_day(self):
        found = _discover(LOG, date(2026, 11, 15), date(2026, 11, 16), date(2026, 11, 17))
        assert found == [["wsi-2026-1"], ["ssi-2026-400", "ukpga-2023-55"], ["uksi-2008-1883"]]

    def test_the_log_is_read_once_for_the_whole_run(self):
        """generic_daily asks oldest first, one day at a time: one pass serves all."""
        _discover(LOG, *(date(2026, 11, 14) + timedelta(days=n) for n in range(4)))
        assert LOG.asked == [1, 2, 3, 4, 5]  # page 5 is the empty end of the log

    def test_a_failed_fetch_raises(self):
        """Not an empty day: the cursor must not move over what was never read."""
        client = MagicMock()
        client.get_update_feed.side_effect = requests.ConnectionError("down")
        with pytest.raises(requests.ConnectionError):
            _discover(client, date(2026, 11, 16))

    def test_a_broken_page_raises(self):
        with pytest.raises(etree.XMLSyntaxError):
            _discover(FakeLog([b"<html>maintenance"]), date(2026, 11, 16))

    def test_a_log_that_ignores_the_page_raises(self):
        """Otherwise it serves page 1 forever and the walk never reaches the day."""
        page_one = _page(1, [("uksi/2026/1/made/data.xml/x", "2026-11-17T10:00:00Z")])
        log = FakeLog([page_one, _page(2, [], served=1)])
        with pytest.raises(ValueError, match="page '1' when asked for page 2"):
            _discover(log, date(2026, 11, 16))

    def test_the_url_asks_only_for_the_page(self):
        assert LegislationGovUkClient().update_feed_url(3) == (
            "https://www.legislation.gov.uk/update/data.feed?page=3"
        )


class TestDailyWaitsForTheDayToEnd:
    """The log fills all day: today is processed tomorrow, once it is over."""

    def _run(self, tmp_path: Path, target_date: date | None = None) -> list[date]:
        from legalize.config import Config, CountryConfig, GitConfig
        from legalize.state.store import StateStore

        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        state_path = tmp_path / "state.json"
        state = StateStore(str(state_path))
        state.last_summary_date = datetime.now(UTC).date() - timedelta(days=3)
        state.save()
        config = Config(
            git=GitConfig(committer_name="Legalize", committer_email="test@test.com"),
            countries={
                "uk": CountryConfig(
                    repo_path=str(repo),
                    data_dir=str(tmp_path / "data"),
                    state_path=str(state_path),
                    source={},
                )
            },
        )
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client_cls = MagicMock()
        client_cls.create.return_value = client
        discovery = MagicMock()
        discovery.discover_daily.return_value = iter([])
        discovery_cls = MagicMock()
        discovery_cls.create.return_value = discovery
        with (
            patch("legalize.countries.get_client_class", return_value=client_cls),
            patch("legalize.countries.get_discovery_class", return_value=discovery_cls),
        ):
            generic_daily(config, "uk", target_date=target_date)
        return [call.args[1] for call in discovery.discover_daily.call_args_list]

    def test_the_automatic_range_stops_at_yesterday(self, tmp_path):
        today = datetime.now(UTC).date()
        assert self._run(tmp_path) == [today - timedelta(days=2), today - timedelta(days=1)]

    def test_an_explicit_date_is_still_processed(self, tmp_path):
        today = datetime.now(UTC).date()
        assert self._run(tmp_path, target_date=today) == [today]


def test_the_daily_downloads_a_law_once():
    """generic_daily calls get_metadata, then get_text: both are the same /data.xml."""
    client = LegislationGovUkClient()
    with patch.object(client, "_get", return_value=b"<Legislation/>") as get:
        assert client.get_metadata("uksi-2000-2853") == client.get_text("uksi-2000-2853")
        client.get_text("uksi-2000-2854")
    assert [call.args[0].rsplit("/", 2)[-2] for call in get.call_args_list] == ["2853", "2854"]


FIXTURES = Path(__file__).parent / "fixtures" / "uk"


def _source(documents: dict[str, str]):
    """legislation.gov.uk serving fixture files by URL path; anything else is a 404."""

    def get(_client, url: str) -> bytes:
        path = url.removeprefix("https://www.legislation.gov.uk/")
        if path not in documents:
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError("404", response=response)
        return (FIXTURES / documents[path]).read_bytes()

    return patch.object(LegislationGovUkClient, "_get", get)


def _daily(tmp_path: Path, day: date, norm_id: str):
    """generic_daily for one day on a fresh repo, with the real UK client and parsers."""
    from legalize.config import Config, CountryConfig, GitConfig

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    config = Config(
        git=GitConfig(committer_name="Legalize", committer_email="test@test.com"),
        countries={
            "uk": CountryConfig(
                repo_path=str(repo),
                data_dir=str(tmp_path / "data"),
                state_path=str(tmp_path / "state.json"),
                source={},
            )
        },
    )
    discovery = MagicMock()
    discovery.discover_daily.side_effect = lambda _c, d: iter([norm_id] if d == day else [])
    with patch("legalize.countries.get_discovery_class") as discovery_cls:
        discovery_cls.return_value.create.return_value = discovery
        commits = generic_daily(config, "uk", target_date=day)
    return commits, repo, config


class TestAVersionPublishedBeforeItTakesEffect:
    """nisr/2026/186: made on 9 November, in the log on the 13th, in operation on the 30th.

    Rendered on the 13th no block was in force, and the daily refused the law as
    empty, every run, until the lookback dropped the day.
    """

    def test_it_is_published_as_the_text_in_force_from_its_start(self, tmp_path):
        from legalize.state.store import StateStore, latest_source_date

        documents = {"nisr/2026/186/data.xml": "sample-si-nisr-2026-186-not-yet-in-force.xml"}
        with _source(documents):
            commits, repo, config = _daily(tmp_path, date(2026, 11, 13), "nisr-2026-186")

        assert commits == 1
        text = (repo / "uk-nir" / "nisr-2026-186.md").read_text()
        assert 'publication_date: "2026-11-09"' in text
        assert 'last_updated: "2026-11-30"' in text  # never in force before it was
        assert "These Regulations may be cited as" in text
        # Dated the day it was published, so the cursor cannot run past the days
        # between publication and commencement, with or without the state file.
        message = subprocess.run(
            ["git", "log", "-1", "--format=%B"], cwd=repo, capture_output=True, text=True
        ).stdout
        assert "Source-Date: 2026-11-13" in message
        assert latest_source_date(str(repo)) == date(2026, 11, 13)
        state = StateStore(config.countries["uk"].state_path)
        state.load()
        assert state.last_summary_date == date(2026, 11, 13)  # the day closed clean
