"""Tests for the Finnish Finlex daily discovery.

Two bugs lived here. Finlex answers 400 to a naive ``publishedSince``, so
every day of every run raised while the job still reported success. And
``publishedSince`` is a *cumulative* lower bound with no upper bound
available, so once the 400 was fixed each day of the window asked for
everything from that day to today — the same statutes over and over.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from legalize.fetcher.fi.client import FinlexClient
from legalize.fetcher.fi.discovery import FinlexDiscovery

_URI = "https://opendata.finlex.fi/finlex/avoindata/v1/akn/fi/act/statute-consolidated"
_PAGE = 10


class _FakeFinlex(FinlexClient):
    """Serves the real API's semantics: publishedSince is cumulative.

    Built from ``{day: [norm_ids modified that day]}``; a query for day D
    returns everything modified on D or later, paginated 10 at a time.
    """

    def __init__(self, by_day: dict[date, list[str]]) -> None:
        super().__init__()
        self._by_day = by_day
        self.asked: list[str] = []

    def list_statutes(self, page: int = 1, limit: int = _PAGE, **kwargs) -> list[dict]:
        stamp = kwargs.get("published_since")
        self.asked.append(stamp)
        since = datetime.fromisoformat(stamp).date()

        ids: list[str] = []
        for day in sorted(self._by_day):
            if day >= since:
                ids += self._by_day[day]

        window = ids[(page - 1) * _PAGE : page * _PAGE]
        return [{"akn_uri": f"{_URI}/{n}/fin@", "status": "MODIFIED"} for n in window]


def _ids(n: int, year: str) -> list[str]:
    """Norm ids in Finlex's ``{year}/{number}`` shape."""
    return [f"{year}/{i}" for i in range(1, n + 1)]


class TestPublishedSinceFormat:
    def test_is_a_timezone_qualified_instant(self):
        """The offset is what the API validates; a naive value is a 400."""
        client = _FakeFinlex({date(2026, 8, 10): ["2019/469"]})

        list(FinlexDiscovery().discover_daily(client, date(2026, 8, 10)))

        assert client.asked, "discovery never queried the API"
        for asked in client.asked:
            parsed = datetime.fromisoformat(asked)
            assert parsed.tzinfo is not None, f"{asked!r} has no offset — Finlex answers 400"
            assert parsed.utcoffset().total_seconds() == 0
            assert (parsed.hour, parsed.minute, parsed.second) == (0, 0, 0)


class TestBoundedToASingleDay:
    def test_yields_only_what_changed_that_day(self):
        """The real shape: 66 statutes on the 10th, 791 on the 17th."""
        client = _FakeFinlex(
            {date(2026, 8, 10): _ids(66, "2019"), date(2026, 8, 17): _ids(791, "2024")}
        )
        discovery = FinlexDiscovery()

        tenth = list(discovery.discover_daily(client, date(2026, 8, 10)))
        seventeenth = list(discovery.discover_daily(client, date(2026, 8, 17)))

        assert len(tenth) == 66
        assert len(seventeenth) == 791
        assert set(tenth).isdisjoint(seventeenth)

    def test_a_quiet_day_inside_the_window_yields_nothing(self):
        """Cumulatively there are 791 pending; on this day, none of them."""
        client = _FakeFinlex({date(2026, 8, 17): _ids(791, "2024")})

        got = list(FinlexDiscovery().discover_daily(client, date(2026, 8, 12)))

        assert got == []

    def test_the_last_day_of_the_window_yields_its_own_changes(self):
        """Nothing after it, so the upper-bound query comes back empty."""
        client = _FakeFinlex({date(2026, 8, 20): ["2026/1", "2026/2"]})

        got = list(FinlexDiscovery().discover_daily(client, date(2026, 8, 20)))

        assert got == ["2026/1", "2026/2"]

    def test_a_statute_touched_twice_lands_on_its_latest_day(self):
        """No statute may be committed twice under two different dates."""
        client = _FakeFinlex({date(2026, 8, 10): ["1999/731"], date(2026, 8, 12): ["1999/731"]})
        discovery = FinlexDiscovery()

        days = [
            list(discovery.discover_daily(client, date(2026, 8, 10) + timedelta(days=i)))
            for i in range(3)
        ]

        assert days == [[], [], ["1999/731"]]

    def test_whole_window_yields_each_statute_exactly_once(self):
        by_day = {
            date(2026, 8, 10): _ids(66, "2019"),
            date(2026, 8, 17): _ids(791, "2024"),
        }
        discovery = FinlexDiscovery()
        client = _FakeFinlex(by_day)

        seen: list[str] = []
        for i in range(11):
            seen += discovery.discover_daily(client, date(2026, 8, 10) + timedelta(days=i))

        assert len(seen) == len(set(seen)) == 857


class TestPaginationCost:
    def test_consecutive_days_reuse_the_previous_upper_bound(self):
        """One new pagination per day, not two — the walk is forward-only."""
        client = _FakeFinlex({date(2026, 8, 17): _ids(20, "2024")})
        discovery = FinlexDiscovery()

        for i in range(3):
            list(discovery.discover_daily(client, date(2026, 8, 10) + timedelta(days=i)))

        assert sorted(set(client.asked)) == [
            "2026-08-10T00:00:00Z",
            "2026-08-11T00:00:00Z",
            "2026-08-12T00:00:00Z",
            "2026-08-13T00:00:00Z",
        ]

    def test_the_cache_does_not_grow_with_the_window(self):
        client = _FakeFinlex({date(2026, 8, 17): _ids(5, "2024")})
        discovery = FinlexDiscovery()

        for i in range(11):
            list(discovery.discover_daily(client, date(2026, 8, 10) + timedelta(days=i)))

        assert len(discovery._since_cache) <= 2
