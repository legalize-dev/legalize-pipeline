"""Germany's daily discovery: one Last-Modified scan per run, each law on its own day."""

from __future__ import annotations

from datetime import date

from legalize.fetcher.de.client import GIIClient
from legalize.fetcher.de.discovery import GIIDiscovery


class _HeadOnly(GIIClient):
    def __init__(self, modified: dict[str, str]):
        super().__init__()
        self.modified, self.heads = modified, 0

    def head_zip(self, norm_id: str) -> dict[str, str]:
        self.heads += 1
        return {"Last-Modified": self.modified[norm_id]}


def test_each_law_is_found_on_its_own_day_from_a_single_scan():
    client = _HeadOnly(
        {
            "stgb": "Mon, 28 Sep 2026 20:00:02 GMT",
            "bgb": "Thu, 24 Sep 2026 20:00:02 GMT",
            "gg": "Fri, 03 Apr 2026 20:00:02 GMT",
        }
    )
    discovery = GIIDiscovery()
    slugs = list(client.modified)
    days = {
        d: list(discovery.discover_daily(client, d, slugs=slugs))
        for d in (date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 28))
    }
    # Not ">=": the StGB was committed on every day of a catch-up for one change.
    assert days == {date(2026, 9, 24): ["bgb"], date(2026, 9, 25): [], date(2026, 9, 28): ["stgb"]}
    # Not one scan per day: that was ~42,000 requests for a seven-day catch-up.
    assert client.heads == 3


def test_monday_takes_what_changed_on_the_weekend():
    """Germany runs Mon-Fri. An exact-day match never asks about Saturday or
    Sunday, so a law rebuilt on the weekend would never be committed."""
    client = _HeadOnly(
        {
            "a": "Fri, 02 Oct 2026 20:00:00 GMT",
            "b": "Sat, 03 Oct 2026 20:00:00 GMT",
            "c": "Sun, 04 Oct 2026 20:00:00 GMT",
            "d": "Mon, 05 Oct 2026 20:00:00 GMT",
        }
    )
    discovery = GIIDiscovery()
    slugs = list(client.modified)
    assert list(discovery.discover_daily(client, date(2026, 10, 2), slugs=slugs)) == ["a"]
    assert list(discovery.discover_daily(client, date(2026, 10, 5), slugs=slugs)) == ["b", "c", "d"]
