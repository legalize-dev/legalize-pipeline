"""Tests for the Finnish Finlex daily discovery.

Finlex answers 400 to a naive ``publishedSince``. The daily sent one for
months, so every day of every run raised and Finland captured nothing while
the job still reported success.
"""

from __future__ import annotations

from datetime import date, datetime

from legalize.fetcher.fi.client import FinlexClient
from legalize.fetcher.fi.discovery import FinlexDiscovery

_URI = "https://opendata.finlex.fi/finlex/avoindata/v1/akn/fi/act/statute-consolidated"


class _RecordingClient(FinlexClient):
    """Captures the query the discovery builds; serves one page of results."""

    def __init__(self, pages: list[list[dict]] | None = None) -> None:
        super().__init__()
        self.asked: list[str | None] = []
        self._pages = pages if pages is not None else [[{"akn_uri": f"{_URI}/2019/469/fin@"}]]

    def list_statutes(self, page: int = 1, limit: int = 10, **kwargs) -> list[dict]:
        self.asked.append(kwargs.get("published_since"))
        return self._pages[page - 1] if page <= len(self._pages) else []


class TestPublishedSinceFormat:
    def test_is_a_timezone_qualified_instant(self):
        """The offset is what the API validates; a naive value is a 400."""
        client = _RecordingClient()

        list(FinlexDiscovery().discover_daily(client, date(2026, 8, 10)))

        assert client.asked, "discovery never queried the API"
        for asked in client.asked:
            parsed = datetime.fromisoformat(asked)
            assert parsed.tzinfo is not None, f"{asked!r} has no offset — Finlex answers 400"
            assert parsed.utcoffset().total_seconds() == 0
            assert parsed.date() == date(2026, 8, 10)
            assert (parsed.hour, parsed.minute, parsed.second) == (0, 0, 0)

    def test_every_page_uses_the_same_instant(self):
        """Paging must not drift the cursor mid-walk."""
        page = [{"akn_uri": f"{_URI}/2019/{n}/fin@"} for n in range(10)]
        client = _RecordingClient(pages=[page, page[:2]])

        list(FinlexDiscovery().discover_daily(client, date(2026, 8, 10)))

        assert len(client.asked) == 2
        assert len(set(client.asked)) == 1


class TestDiscoverDaily:
    def test_yields_deduplicated_norm_ids(self):
        """The same statute appears once per language expression."""
        client = _RecordingClient(
            pages=[
                [
                    {"akn_uri": f"{_URI}/2019/469/fin@"},
                    {"akn_uri": f"{_URI}/2019/469/swe@"},
                    {"akn_uri": f"{_URI}/1989/415/fin@20221099"},
                ]
            ]
        )

        got = list(FinlexDiscovery().discover_daily(client, date(2026, 8, 10)))

        assert got == ["2019/469", "1989/415"]

    def test_empty_page_ends_the_walk(self):
        client = _RecordingClient(pages=[[]])

        assert list(FinlexDiscovery().discover_daily(client, date(2026, 8, 10))) == []
