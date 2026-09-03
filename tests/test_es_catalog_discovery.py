"""`legalize bootstrap -c es` could not run: `BOEDiscovery.discover_all` imported
`iter_norms_from_catalog` from a module that never defined it, so a rebuild
raised an ImportError before fetching anything (#99).

The module's own docstring said "the BOE API does not expose a directly
filterable catalog endpoint". It does: `?limit=&offset=` returns the whole
consolidated catalogue — 12,387 norms — in two requests, because a page caps at
10,000. The sweep it replaces walked 14,926 daily summaries for the same list.
"""

from __future__ import annotations

import pytest

from legalize.fetcher.es.catalogo import _PAGE_SIZE, iter_norms_from_catalog


def _page(identifiers: list[str], code: str = "200", text: str = "ok") -> bytes:
    items = "".join(f"<item><identificador>{i}</identificador></item>" for i in identifiers)
    return (
        '<?xml version="1.0" encoding="utf-8"?><response>'
        f"<status><code>{code}</code><text>{text}</text></status>"
        f"<data>{items}</data></response>"
    ).encode()


class _Client:
    """Records what was asked for, so the request count is a fact of the test."""

    def __init__(self, pages: list[bytes]):
        self._pages = pages
        self.calls: list[tuple[int, int]] = []

    def get_catalog(self, limit: int, offset: int) -> bytes:
        self.calls.append((limit, offset))
        return self._pages[len(self.calls) - 1]


class TestTheWholeCatalogueInTwoRequests:
    def test_a_full_page_is_followed_by_the_next(self):
        client = _Client(
            [_page([f"BOE-A-2020-{n}" for n in range(_PAGE_SIZE)]), _page(["BOE-A-2021-1"])]
        )
        found = list(iter_norms_from_catalog(client))
        assert len(found) == _PAGE_SIZE + 1
        assert client.calls == [(_PAGE_SIZE, 0), (_PAGE_SIZE, _PAGE_SIZE)]

    def test_a_short_page_ends_the_sweep(self):
        """12,387 norms is one full page and one short one — two requests, and
        no third that would cost a round-trip to learn nothing."""
        client = _Client([_page(["BOE-A-2020-1", "BOE-A-2020-2"])])
        assert list(iter_norms_from_catalog(client)) == ["BOE-A-2020-1", "BOE-A-2020-2"]
        assert len(client.calls) == 1

    def test_an_identifier_seen_twice_is_yielded_once(self):
        """The source orders by `fecha_actualizacion`, which shifts while the
        sweep runs: a norm consolidated between two requests slides across the
        page boundary and would otherwise be fetched and committed twice."""
        client = _Client(
            [
                _page([f"BOE-A-2020-{n}" for n in range(_PAGE_SIZE)]),
                _page([f"BOE-A-2020-{n}" for n in range(_PAGE_SIZE - 2, _PAGE_SIZE + 1)]),
            ]
        )
        found = list(iter_norms_from_catalog(client))
        assert len(found) == len(set(found)) == _PAGE_SIZE + 1

    def test_an_empty_page_ends_it_too(self):
        assert list(iter_norms_from_catalog(_Client([_page([])]))) == []

    def test_an_error_stops_rather_than_returning_an_empty_corpus(self):
        """A 400 with an empty `<data/>` is what the API answers to a bad
        Accept header, and reading it as "no norms" would bootstrap a country
        into an empty repo without failing."""
        client = _Client([_page([], code="400", text="No soportado ningún mime type")])
        with pytest.raises(ValueError, match="400"):
            list(iter_norms_from_catalog(client))
