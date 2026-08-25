"""Portugal daily processing.

The interesting half is not "what was published today" — it is "which consolidated
diploma did DRE re-consolidate", because that is where reform commits come from and
DRE does it days or weeks after the amending act appears.
"""

from __future__ import annotations

import gzip
import json
from unittest.mock import MagicMock, patch

import pytest

from legalize.fetcher.pt.daily import (
    _read_lastmods,
    _write_lastmods,
    fetch_consolidated_lastmods,
    reconsolidated_since_last_run,
)
from legalize.fetcher.pt.dre_api import DREApiError

_INDEX = (
    "<sitemapindex><sitemap><loc>https://files.diariodarepublica.pt/sitemap/"
    "acordao-doutrinario-sitemap-1.xml</loc></sitemap>"
    "<sitemap><loc>https://files.diariodarepublica.pt/sitemap/"
    "legislacao-consolidada-sitemap-1.xml</loc></sitemap></sitemapindex>"
)


def _consolidated_sitemap(entries: dict[str, str]) -> str:
    body = "".join(
        f"<url><loc>https://diariodarepublica.pt/dr/legislacao-consolidada/{path}</loc>"
        f"<lastmod>{stamp}</lastmod></url>"
        for path, stamp in entries.items()
    )
    return f"<urlset>{body}</urlset>"


def _client(sitemap: str) -> MagicMock:
    client = MagicMock()
    client._api.get_text_body.side_effect = lambda url: (
        _INDEX if url.endswith("sitemap/sitemap.xml") else sitemap
    )
    return client


class TestLastmodState:
    def test_roundtrip(self, tmp_path):
        _write_lastmods(tmp_path, {"cons:lei:2020-1": "2026-06-23"})
        assert _read_lastmods(tmp_path) == {"cons:lei:2020-1": "2026-06-23"}

    def test_missing_state_is_empty(self, tmp_path):
        assert _read_lastmods(tmp_path) == {}

    def test_corrupt_state_is_empty_not_an_exception(self, tmp_path):
        path = tmp_path / "consolidated_lastmod.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write("{not json")
        assert _read_lastmods(tmp_path) == {}


class TestConsolidatedLastmods:
    def test_parses_norm_ids_and_stamps(self):
        client = _client(
            _consolidated_sitemap(
                {"decreto-lei/1966-34509075": "2026-06-23", "lei/2019-121352748": "2024-01-02"}
            )
        )
        assert fetch_consolidated_lastmods(client) == {
            "cons:decreto-lei:1966-34509075": "2026-06-23",
            "cons:lei:2019-121352748": "2024-01-02",
        }

    def test_missing_consolidated_sitemap_raises(self):
        client = MagicMock()
        client._api.get_text_body.return_value = "<sitemapindex></sitemapindex>"
        with pytest.raises(RuntimeError, match="consolidated sitemap"):
            fetch_consolidated_lastmods(client)


class TestReconsolidationDetection:
    def test_first_run_records_a_baseline_and_claims_nothing(self, tmp_path):
        """Right after a bootstrap every diploma looks new; committing them all
        again would duplicate the entire history."""
        client = _client(_consolidated_sitemap({"lei/2019-1": "2024-01-02"}))
        changed, current = reconsolidated_since_last_run(client, tmp_path)
        assert changed == []
        assert current == {"cons:lei:2019-1": "2024-01-02"}

    def test_only_moved_stamps_are_returned(self, tmp_path):
        _write_lastmods(
            tmp_path, {"cons:lei:2019-1": "2024-01-02", "cons:lei:2019-2": "2024-01-02"}
        )
        client = _client(
            _consolidated_sitemap({"lei/2019-1": "2026-08-21", "lei/2019-2": "2024-01-02"})
        )
        changed, _ = reconsolidated_since_last_run(client, tmp_path)
        assert changed == ["cons:lei:2019-1"]

    def test_a_newly_consolidated_diploma_counts_as_changed(self, tmp_path):
        _write_lastmods(tmp_path, {"cons:lei:2019-1": "2024-01-02"})
        client = _client(
            _consolidated_sitemap({"lei/2019-1": "2024-01-02", "lei/2026-9": "2026-08-21"})
        )
        changed, _ = reconsolidated_since_last_run(client, tmp_path)
        assert changed == ["cons:lei:2026-9"]


class TestApiBreakAborts:
    def test_sitemap_failure_propagates(self, tmp_path):
        """A broken contract is not a quiet day. Swallowing it would advance the
        state past legislation we never saw."""
        client = MagicMock()
        client._api.get_text_body.side_effect = DREApiError("contract broken")
        with pytest.raises(DREApiError):
            reconsolidated_since_last_run(client, tmp_path)

    def test_baseline_is_not_written_on_failure(self, tmp_path):
        client = MagicMock()
        client._api.get_text_body.side_effect = DREApiError("contract broken")
        with pytest.raises(DREApiError):
            reconsolidated_since_last_run(client, tmp_path)
        assert _read_lastmods(tmp_path) == {}


class TestSerialisation:
    def test_state_file_is_gzipped_json(self, tmp_path):
        _write_lastmods(tmp_path, {"cons:lei:2020-1": "x"})
        with gzip.open(tmp_path / "consolidated_lastmod.json.gz", "rt", encoding="utf-8") as handle:
            assert json.load(handle) == {"cons:lei:2020-1": "x"}


class TestDailyWiring:
    def test_daily_is_importable_and_takes_the_pipeline_signature(self):
        from legalize.fetcher.pt.daily import daily

        with patch("legalize.fetcher.pt.daily.StateStore"):
            assert callable(daily)
        assert daily.__doc__ and "re-consolidated" in daily.__doc__


class TestAnaliseJuridicaMaps:
    """The maps are corpus-wide, so nothing in the per-norm fetch path loads them.
    A daily that skips them republishes every law it touches with no subjects and
    records no reform against a law that was just amended."""

    def test_install_loads_all_three(self, tmp_path):
        import json as _json

        from legalize.fetcher.pt import analise_juridica, parser as pt_parser

        (tmp_path / "thesaurus.json").write_text(_json.dumps({"1": "Código Civil"}))
        (tmp_path / "subjects.json").write_text(_json.dumps({"/dr/detalhe/lei/1-2020-1": ["X"]}))
        (tmp_path / "amendments.json").write_text(
            _json.dumps({"pub:lei:1-2020-1": [["2021-01-01", "DRE-LEI-9-2021", "arts. 3.º"]]})
        )
        try:
            loaded = analise_juridica.install(tmp_path)
            assert loaded == {"thesaurus": 1, "subject_overrides": 1, "amendments": 1}
            assert pt_parser._THESAURUS["1"] == "Código Civil"
            assert pt_parser._AMENDMENTS["pub:lei:1-2020-1"][0][1] == "DRE-LEI-9-2021"
        finally:
            pt_parser.set_thesaurus({})
            pt_parser.set_subject_overrides({})
            pt_parser.set_amendments({})

    def test_absent_maps_are_not_an_error(self, tmp_path):
        """A fresh checkout has none of them; the fetch must still run."""
        from legalize.fetcher.pt import analise_juridica

        assert analise_juridica.install(tmp_path) == {}

    def test_the_daily_installs_them(self):
        """Pins the wiring, not the loader: this is the call that was missing."""
        import inspect

        from legalize.fetcher.pt import daily as pt_daily

        assert "analise_juridica.install" in inspect.getsource(pt_daily.daily)


class TestAmendmentPropagation:
    """A bootstrap-time index freezes on the day it was built. The act published
    this morning names the law it changes, but the resolvable record of that change
    lives on the amended law's page — DiretasList has no resolvable target on any
    row — so the daily has to ask DRE about the law, not about the act."""

    def test_targets_are_read_off_the_rendered_act(self):
        from legalize.fetcher.pt import analise_juridica

        markdown = (
            "Altera o [Decreto-Lei n.º 16/94]"
            "(https://diariodarepublica.pt/dr/detalhe/decreto-lei/16-1994-512030), "
            "e a [Portaria n.º 5/99]"
            "(https://diariodarepublica.pt/dr/detalhe/portaria/5-1999-661750)."
        )
        assert analise_juridica.targets_named_by(markdown) == {
            "pub:decreto-lei:16-1994-512030",
            "pub:portaria:5-1999-661750",
        }

    def test_refresh_folds_a_new_amendment_into_the_index(self, tmp_path, monkeypatch):
        import gzip as _gzip
        import json as _json

        from legalize.fetcher.pt import analise_juridica, parser as pt_parser

        raw = tmp_path / "raw"
        raw.mkdir()
        with _gzip.open(raw / "pub-lei-37-1994-533820.meta.json.gz", "wt", encoding="utf-8") as fh:
            _json.dump(
                {
                    "tipo": "lei",
                    "key": "37-1994-533820",
                    "published": {
                        "Id": "533820",
                        "Numero": "37/94",
                        "TipoDiplomaAcronimo": "lei",
                        "DataPublicacao": "1994-11-11",
                        "LinkSitemap": "/dr/detalhe/lei/37-1994-533820",
                    },
                },
                fh,
            )

        class _Api:
            def associations(self, ref, association_id):
                if association_id != "162":
                    return {}
                return {
                    "InversasList": {
                        "List": [
                            {
                                "Data": "1994-11-11",
                                "Texto": "Alterados os arts. 5.º, 9.º\x00",
                                "LinkSitemapAnaliseJuridica": (
                                    "/dr/analise-juridica/informacoes-gerais/lei/37-1994-533820"
                                ),
                            }
                        ]
                    }
                }

        try:
            changed = analise_juridica.refresh_amendments(
                _Api(), tmp_path, {"pub:decreto-lei:16-1994-512030"}
            )
            assert changed == {"pub:decreto-lei:16-1994-512030"}
            index = _json.loads((tmp_path / "amendments.json").read_text())
            assert index["pub:decreto-lei:16-1994-512030"] == [
                ["1994-11-11", "DRE-1994-37-533820", "Alterados os arts. 5.º, 9.º"]
            ]
            # and it is live in the parser, not just on disk
            assert pt_parser._AMENDMENTS["pub:decreto-lei:16-1994-512030"][0][1] == (
                "DRE-1994-37-533820"
            )
        finally:
            pt_parser.set_amendments({})

    def test_a_known_amendment_produces_no_new_commit(self, tmp_path):
        """Re-running the same day must not re-commit what is already recorded."""
        import json as _json

        from legalize.fetcher.pt import analise_juridica, parser as pt_parser

        (tmp_path / "raw").mkdir()
        (tmp_path / "amendments.json").write_text(
            _json.dumps({"pub:lei:1-2020-1": [["2021-01-01", "DRE-LEI-9-2021", ""]]})
        )

        class _Api:
            def associations(self, ref, association_id):
                return {}

        try:
            assert (
                analise_juridica.refresh_amendments(_Api(), tmp_path, {"pub:lei:1-2020-1"}) == set()
            )
        finally:
            pt_parser.set_amendments({})

    def test_the_daily_propagates(self):
        import inspect

        from legalize.fetcher.pt import daily as pt_daily

        source = inspect.getsource(pt_daily.daily)
        assert "targets_named_by" in source and "refresh_amendments" in source
