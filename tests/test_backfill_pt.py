"""Portugal: what the sitemaps never listed, and the subjects the daily never had.

Both defects were found in the corpus: Portaria 208/2017 is in no DRE sitemap, so the
bootstrap never saw it, and every diploma the daily published from 2026-08-26 on
carries no subjects, because their labels lived in a map the daily runs without.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from unittest.mock import MagicMock

import pytest

from legalize.committer.git_ops import GitRepo
from legalize.fetcher.pt import parser as parser_module
from legalize.fetcher.pt.backfill import missing, published_identifiers
from legalize.fetcher.pt.client import DREClient
from legalize.fetcher.pt.discovery import DREDiscovery
from legalize.fetcher.pt.dre_api import DREApiError
from legalize.fetcher.pt.parser import DREMetadataParser

_RDFA = '<span property="eli:is_about" resource="http://x/{}"></span>'


@pytest.fixture(autouse=True)
def _empty_thesaurus():
    parser_module.set_thesaurus({})
    yield
    parser_module.set_thesaurus({})


def _published(eli: str = "") -> dict:
    return {
        "Id": "107684448",
        "Numero": "208/2017",
        "TipoDiploma": "Portaria",
        "DataPublicacao": "2017-07-13",
        "Sumario": "Portaria de teste",
        "LinkSitemap": "/dr/detalhe/portaria/208-2017-107684448",
        "ELIMetadataHTML": eli,
    }


def _bundle(eli: str, descriptors: dict[str, str]) -> bytes:
    return json.dumps(
        {
            "surface": "pub",
            "tipo": "portaria",
            "key": "208-2017-107684448",
            "published": _published(eli),
            "descriptors": descriptors,
        }
    ).encode("utf-8")


class TestSubjectsTravelWithTheDiploma:
    def test_bundle_labels_name_the_subjects_without_a_map(self):
        meta = DREMetadataParser().parse(
            _bundle(_RDFA.format(11) + _RDFA.format(12), {"11": "Fiscalidade", "12": "IRC"}),
            "pub:portaria:208-2017-107684448",
        )
        assert meta.subjects == ("Fiscalidade", "IRC")

    def test_a_diploma_naming_no_subject_takes_the_screen_s_labels(self):
        meta = DREMetadataParser().parse(
            _bundle("", {"11": "Fiscalidade"}), "pub:portaria:208-2017-107684448"
        )
        assert meta.subjects == ("Fiscalidade",)

    def _client(self, found: dict[str, str] | Exception) -> DREClient:
        client = DREClient.__new__(DREClient)
        client._api = MagicMock()
        if isinstance(found, Exception):
            client._api.descriptors.side_effect = found
        else:
            client._api.descriptors.return_value = found
        return client

    def test_unknown_ids_are_fetched_once_and_learnt(self):
        client = self._client({"11": "Fiscalidade"})
        published = _published(_RDFA.format(11))
        assert client._descriptors_for(published) == {"11": "Fiscalidade"}
        # The next diploma naming the same subject costs no request.
        assert client._descriptors_for(published) == {}
        assert client._api.descriptors.call_count == 1

    def test_a_diploma_the_screen_cannot_resolve_ships_without_subjects(self):
        client = self._client(DREApiError("silent empty record"))
        assert client._descriptors_for(_published(_RDFA.format(11))) == {}


class TestJournalWalk:
    def _discovery(self, sitemap_keys, journal):
        discovery = DREDiscovery()
        discovery.consolidated_ids = lambda client: iter(())
        discovery.published_ids = lambda client: iter(("portaria", k) for k in sitemap_keys)
        discovery.journal_ids = lambda client, start, end: iter(journal)
        return discovery

    def test_discovery_adds_what_only_the_journal_lists(self):
        discovery = self._discovery(
            ["207-2017-1"],
            [
                (date(2017, 7, 13), "pub:portaria:207-2017-1"),
                (date(2017, 7, 13), "pub:portaria:208-2017-107684448"),
            ],
        )
        ids = list(discovery.discover_all(MagicMock(spec=DREClient)))
        assert ids == ["pub:portaria:207-2017-1", "pub:portaria:208-2017-107684448"]

    def test_missing_skips_what_head_holds_and_keeps_day_order(self):
        discovery = self._discovery(
            [],
            [
                (date(2017, 7, 12), "pub:portaria:207-2017-1"),
                (date(2017, 7, 13), "pub:portaria:208-2017-107684448"),
                (date(2017, 7, 13), "pub:portaria:208-2017-107684448"),
            ],
        )
        present = {"DRE-2017-207-1"}
        found = list(missing(discovery, None, present, date(2017, 7, 1), date(2017, 7, 31)))
        assert found == [
            (date(2017, 7, 13), "pub:portaria:208-2017-107684448", "DRE-2017-208-107684448")
        ]


def test_published_identifiers_reads_every_directory(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    for rel in ("pt/2017/DRE-2017-1-1.md", "pt-20/2018/DRE-2018-2-2.md", "README.md"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed")
    repo = GitRepo(tmp_path, "t", "t@t")
    assert published_identifiers(repo) == {"DRE-2017-1-1", "DRE-2018-2-2"}
