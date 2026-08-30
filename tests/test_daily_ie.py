"""Tests for the Ireland (IE) daily discovery pagination."""

from datetime import date

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
