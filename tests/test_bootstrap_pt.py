"""The order the two DRE surfaces are fetched in decides what the corpus holds.

A diploma DRE consolidates is reachable as ``pub:`` and as ``cons:``, both
resolve to one identifier, both write one file, and the last one wins. The
as-published side is a single snapshot; the consolidated side carries the
version history. Letting as-published land last cost the Código Civil its
2,930 blocks and 54 reforms.

The rule lived in a shell script beside the repo until this module existed,
where neither the daily nor any test could reach it.
"""

from __future__ import annotations

import pytest

from legalize.fetcher.pt import bootstrap as pt_bootstrap


@pytest.fixture
def fetch_order(monkeypatch, tmp_path):
    """Record the order norms are fetched in, without touching DRE or git."""
    order: list[str] = []

    def fake_fetch_one(config, country, norm_id, force=False):
        order.append(norm_id)
        return object()

    ids = [
        "cons:lei:1985-34475275",
        "pub:regimento:1984-264280",
        "cons:dec-lei:2011-586",
        "pub:lei:1-2020-9",
    ]

    monkeypatch.setattr("legalize.pipeline.generic_fetch_one", fake_fetch_one)
    monkeypatch.setattr("legalize.pipeline.discover_norm_ids", lambda *a, **k: list(ids))
    monkeypatch.setattr("legalize.pipeline.commit_all_fast", lambda *a, **k: 0)
    monkeypatch.setattr("legalize.pipeline.write_country_meta", lambda *a, **k: None)
    monkeypatch.setattr("legalize.pipeline.write_repo_meta", lambda *a, **k: None)
    monkeypatch.setattr(pt_bootstrap, "build_index", lambda *a, **k: None)
    monkeypatch.setattr(pt_bootstrap.analise_juridica, "install", lambda *a, **k: {})
    return order


def test_consolidated_is_fetched_last(fetch_order, tmp_path):
    """Every as-published norm before every consolidated one. Not interleaved."""
    from legalize.config import Config, CountryConfig, GitConfig

    config = Config(
        git=GitConfig(),
        countries={
            "pt": CountryConfig(
                repo_path=str(tmp_path / "repo"),
                data_dir=str(tmp_path / "data"),
                max_workers=1,
            )
        },
    )
    pt_bootstrap.bootstrap(config)

    surfaces = ["cons" if n.startswith("cons:") else "pub" for n in fetch_order]
    assert surfaces == ["pub", "pub", "cons", "cons"], fetch_order
