"""Cursor paging of the EUR-Lex bulk catalog.

The catalog exists because per-act metadata SPARQL costs ~2.4 s — eight hours
over a full corpus — while the same rows come back 1,000 at a time in ~1.2 s.

The subtlety it has to survive: one act yields several rows (author × entry
into force × …), so a page boundary can fall inside an act. These tests pin the
boundary behaviour, because getting it wrong drops authors and dates for
whichever acts happen to straddle a cut — silent, and unfindable by eye in an
87,000-act corpus.
"""

from __future__ import annotations

import pytest

from legalize.fetcher.eu import client as eu_client
from legalize.fetcher.eu.client import EURLexClient


@pytest.fixture(autouse=True)
def small_pages(monkeypatch):
    """Shrink the page so fixtures stay readable."""
    monkeypatch.setattr(eu_client, "_CATALOG_PAGE_SIZE", 4)


def _row(celex: str, author: str) -> dict:
    return {"celex": {"value": celex}, "author": {"value": author}}


class _FakeClient(EURLexClient):
    """Serves a fixed row list, honouring the >= cursor the pager sends."""

    def __init__(self, rows):
        super().__init__(requests_per_second=1000.0)
        self._rows = rows
        self.queries = 0

    def sparql_query(self, query: str) -> dict:
        self.queries += 1
        cursor = ""
        if 'STR(?celex) >= "' in query:
            cursor = query.split('STR(?celex) >= "')[1].split('"')[0]
        page = [r for r in self._rows if r["celex"]["value"] >= cursor]
        page = page[: eu_client._CATALOG_PAGE_SIZE]
        return {"results": {"bindings": page}}


def _collect(rows):
    client = _FakeClient(rows)
    got = dict(client._paged(lambda c: f'FILTER(STR(?celex) >= "{c}")' if c else "", "celex"))
    return got, client


def test_single_short_page():
    rows = [_row("A", "x"), _row("B", "y")]
    got, client = _collect(rows)
    assert list(got) == ["A", "B"]
    assert client.queries == 1


def test_act_straddling_a_page_boundary_keeps_all_its_rows():
    """The regression this design exists for: B has 3 rows across a 4-row cut."""
    rows = [
        _row("A", "a1"),
        _row("B", "b1"),
        _row("B", "b2"),
        _row("B", "b3"),
        _row("C", "c1"),
    ]
    got, _ = _collect(rows)
    assert list(got) == ["A", "B", "C"]
    assert [r["author"]["value"] for r in got["B"]] == ["b1", "b2", "b3"]


def test_no_duplicate_rows_across_pages():
    rows = [_row(c, f"{c}1") for c in "ABCDEFGHIJ"]
    got, _ = _collect(rows)
    assert list(got) == list("ABCDEFGHIJ")
    assert all(len(v) == 1 for v in got.values())


def test_one_act_filling_a_whole_page_fails_loudly():
    """It cannot be paged past, so it must raise rather than loop forever."""
    rows = [_row("A", f"a{i}") for i in range(6)]
    with pytest.raises(RuntimeError, match="paging cursor cannot advance"):
        _collect(rows)


def test_empty_catalog():
    got, client = _collect([])
    assert got == {}
    assert client.queries == 1


# ─── Compound cursor (auxiliary queries) ───────────────────────────────────


class _FakePairs(EURLexClient):
    """Serves (celex, value) rows, honouring the compound cursor."""

    def __init__(self, rows):
        super().__init__(requests_per_second=1000.0)
        self._rows = sorted(rows, key=lambda r: (r["celex"]["value"], r["v"]["value"]))
        self.queries = 0

    def sparql_query(self, query: str) -> dict:
        self.queries += 1
        rows = self._rows
        if 'STR(?celex) > "' in query:
            key = query.split('STR(?celex) > "')[1].split('"')[0]
            tie = query.split('STR(?v) > "')[1].split('"')[0]
            rows = [r for r in rows if (r["celex"]["value"], r["v"]["value"]) > (key, tie)]
        return {"results": {"bindings": rows[: eu_client._CATALOG_PAGE_SIZE]}}


def _pair(celex: str, value: str) -> dict:
    return {"celex": {"value": celex}, "v": {"value": value}}


def test_compound_cursor_pages_inside_one_act():
    """The EEA Agreement's Annex I is amended by more than 1,000 acts.

    A cursor on the act alone can never step over it — that is the RuntimeError
    the group pager raises, and why the auxiliary queries order on the pair.
    """
    rows = [_pair("A", f"m{i:03d}") for i in range(9)] + [_pair("B", "m1")]
    client = _FakePairs(rows)
    got = list(
        client._paged_rows(lambda k, t: client._pair_cursor("celex", "v", k, t), "celex", "v")
    )
    assert len(got) == 10
    assert [r["v"]["value"] for r in got if r["celex"]["value"] == "A"] == [
        f"m{i:03d}" for i in range(9)
    ]
    assert client.queries > 1, "fixture too small to exercise paging"


def test_compound_cursor_stops_without_forward_progress():
    """A server that ignores the cursor must not spin forever."""

    class _Stuck(_FakePairs):
        def sparql_query(self, query: str) -> dict:
            self.queries += 1
            if self.queries > 20:
                raise AssertionError("looped")
            return {"results": {"bindings": self._rows[: eu_client._CATALOG_PAGE_SIZE]}}

    client = _Stuck([_pair("A", f"m{i}") for i in range(4)])
    got = list(
        client._paged_rows(lambda k, t: client._pair_cursor("celex", "v", k, t), "celex", "v")
    )
    assert client.queries <= 3
    assert got
