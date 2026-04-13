"""Tests for the Italy (Normattiva) fetcher: parser and client."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from legalize.fetcher.it.client import NormativaClient
from legalize.fetcher.it.parser import (
    NormativaMetadataParser,
    NormativaTextParser,
    _clean,
    _extract_rank_from_urn,
    _parse_iso_date,
)
from legalize.models import NormStatus, Rank

FIXTURES = Path(__file__).parent / "fixtures" / "it"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class TestCleanText:
    def test_strips_whitespace(self):
        assert _clean("  hello  world  ") == "hello world"

    def test_replaces_nbsp(self):
        assert _clean("a\xa0b") == "a b"

    def test_strips_control_chars(self):
        assert _clean("hello\x00world") == "helloworld"

    def test_none_returns_empty(self):
        assert _clean(None) == ""


class TestParseIsoDate:
    def test_valid(self):
        assert _parse_iso_date("2024-06-28") == date(2024, 6, 28)

    def test_empty(self):
        assert _parse_iso_date("") is None

    def test_sentinel(self):
        assert _parse_iso_date("9999-12-31") is None

    def test_invalid(self):
        assert _parse_iso_date("not-a-date") is None


class TestExtractRankFromUrn:
    def test_legge(self):
        assert _extract_rank_from_urn("urn:nir:stato:legge:2024-06-26;86") == "legge"

    def test_decreto_legislativo(self):
        assert _extract_rank_from_urn("urn:nir:stato:decreto.legislativo:2005-03-07;82") == "decreto_legislativo"

    def test_decreto_legge(self):
        assert _extract_rank_from_urn("urn:nir:stato:decreto.legge:2024-01-18;4") == "decreto_legge"

    def test_costituzione(self):
        assert _extract_rank_from_urn("urn:nir:stato:costituzione") == "costituzione"

    def test_regio_decreto(self):
        assert _extract_rank_from_urn("urn:nir:stato:regio.decreto:1942-03-16;262") == "regio_decreto"

    def test_unknown_falls_back(self):
        assert _extract_rank_from_urn("urn:nir:stato:tipo.sconosciuto:2024-01-01;1") == "tipo_sconosciuto"

    def test_empty(self):
        assert _extract_rank_from_urn("") == "altro"


class TestNormativaTextParser:
    @pytest.fixture()
    def parser(self):
        return NormativaTextParser()

    def test_constitution_articles(self, parser):
        blocks = parser.parse_text(_load("sample-constitution.xml"))
        articles = [b for b in blocks if b.block_type == "articolo"]
        assert len(articles) == 139

    def test_constitution_chapters(self, parser):
        blocks = parser.parse_text(_load("sample-constitution.xml"))
        chapters = [b for b in blocks if b.block_type == "chapter"]
        assert len(chapters) == 16

    def test_constitution_first_article_text(self, parser):
        blocks = parser.parse_text(_load("sample-constitution.xml"))
        articles = [b for b in blocks if b.block_type == "articolo"]
        art1 = articles[0]
        assert "Art. 1." in art1.title
        text = " ".join(p.text for v in art1.versions for p in v.paragraphs)
        assert "Repubblica democratica" in text

    def test_cad_articles(self, parser):
        blocks = parser.parse_text(_load("sample-code.xml"))
        articles = [b for b in blocks if b.block_type == "articolo"]
        assert len(articles) == 123

    def test_cad_chapters(self, parser):
        blocks = parser.parse_text(_load("sample-code.xml"))
        chapters = [b for b in blocks if b.block_type == "chapter"]
        assert len(chapters) == 17

    def test_cad_cross_references(self, parser):
        blocks = parser.parse_text(_load("sample-code.xml"))
        articles = [b for b in blocks if b.block_type == "articolo"]
        all_text = " ".join(
            p.text for a in articles for v in a.versions for p in v.paragraphs
        )
        assert "[" in all_text and "](" in all_text

    def test_dpr_articles(self, parser):
        blocks = parser.parse_text(_load("sample-dpr.xml"))
        articles = [b for b in blocks if b.block_type == "articolo"]
        assert len(articles) == 23

    def test_ordinary_law_articles(self, parser):
        blocks = parser.parse_text(_load("sample-ordinary-law.xml"))
        articles = [b for b in blocks if b.block_type == "articolo"]
        assert len(articles) == 10

    def test_tuir_articles(self, parser):
        blocks = parser.parse_text(_load("sample-with-tables.xml"))
        articles = [b for b in blocks if b.block_type == "articolo"]
        assert len(articles) == 236

    def test_tuir_chapters(self, parser):
        blocks = parser.parse_text(_load("sample-with-tables.xml"))
        chapters = [b for b in blocks if b.block_type == "chapter"]
        assert len(chapters) == 21

    def test_each_article_has_version(self, parser):
        blocks = parser.parse_text(_load("sample-constitution.xml"))
        for b in blocks:
            if b.block_type == "articolo":
                assert len(b.versions) >= 1, f"{b.id} has no versions"

    def test_empty_input_returns_empty(self, parser):
        blocks = parser.parse_text(b"<?xml version='1.0'?><empty/>")
        assert blocks == []

    def test_article_paragraphs_non_empty(self, parser):
        blocks = parser.parse_text(_load("sample-code.xml"))
        articles = [b for b in blocks if b.block_type == "articolo"]
        non_empty = sum(
            1 for a in articles
            for v in a.versions
            for p in v.paragraphs
            if p.text.strip()
        )
        assert non_empty > 100


class TestNormativaMetadataParser:
    @pytest.fixture()
    def parser(self):
        return NormativaMetadataParser()

    def test_constitution_metadata(self, parser):
        meta = parser.parse(_load("sample-constitution.xml"), "047U0001")
        assert meta.title == "COSTITUZIONE DELLA REPUBBLICA ITALIANA"
        assert meta.identifier == "047U0001"
        assert meta.country == "it"
        assert meta.rank == Rank("costituzione")
        assert meta.publication_date == date(1947, 12, 27)
        assert meta.status == NormStatus.IN_FORCE

    def test_cad_metadata(self, parser):
        meta = parser.parse(_load("sample-code.xml"), "005G0104")
        assert "amministrazione digitale" in meta.title.lower()
        assert meta.identifier == "005G0104"
        assert meta.rank == Rank("decreto_legislativo")
        assert meta.publication_date == date(2005, 5, 16)

    def test_tuir_metadata(self, parser):
        meta = parser.parse(_load("sample-with-tables.xml"), "086U0917")
        assert "imposte sui redditi" in meta.title.lower()
        assert meta.identifier == "086U0917"
        assert meta.publication_date == date(1986, 12, 31)

    def test_source_url_contains_urn(self, parser):
        meta = parser.parse(_load("sample-code.xml"), "005G0104")
        assert "urn:nir:stato:decreto.legislativo:2005-03-07;82" in meta.source

    def test_extra_contains_urn_nir(self, parser):
        meta = parser.parse(_load("sample-code.xml"), "005G0104")
        extra = dict(meta.extra)
        assert "urn_nir" in extra
        assert extra["urn_nir"].startswith("urn:nir:")

    def test_extra_contains_gu_number(self, parser):
        meta = parser.parse(_load("sample-code.xml"), "005G0104")
        extra = dict(meta.extra)
        assert extra.get("gu_number") == "112"

    def test_extra_contains_enactment_date(self, parser):
        meta = parser.parse(_load("sample-code.xml"), "005G0104")
        extra = dict(meta.extra)
        assert extra.get("enactment_date") == "2005-03-07"

    def test_extra_contains_act_type(self, parser):
        meta = parser.parse(_load("sample-code.xml"), "005G0104")
        extra = dict(meta.extra)
        assert "DECRETO LEGISLATIVO" in extra.get("act_type_code", "")

    def test_dpr_rank(self, parser):
        meta = parser.parse(_load("sample-dpr.xml"), "000G0001")
        assert "decreto" in str(meta.rank)
        assert "presidente" in str(meta.rank) or "repubblica" in str(meta.rank)


class TestNormativaClientParsing:
    def test_parse_composite_norm_id(self):
        codice, data_gu, urn = NormativaClient._parse_norm_id(
            "005G0104:2005-05-16:urn:nir:stato:decreto.legislativo:2005-03-07;82"
        )
        assert codice == "005G0104"
        assert data_gu == "2005-05-16"
        assert urn == "urn:nir:stato:decreto.legislativo:2005-03-07;82"

    def test_parse_urn_only(self):
        codice, data_gu, urn = NormativaClient._parse_norm_id(
            "urn:nir:stato:legge:2024-01-09;4"
        )
        assert codice == ""
        assert urn == "urn:nir:stato:legge:2024-01-09;4"

    def test_parse_bare_codice(self):
        codice, data_gu, urn = NormativaClient._parse_norm_id("005G0104")
        assert codice == "005G0104"


class TestItalyRegistry:
    def test_italy_in_supported(self):
        from legalize.countries import supported_countries
        assert "it" in supported_countries()

    def test_get_text_parser(self):
        from legalize.countries import get_text_parser
        parser = get_text_parser("it")
        assert type(parser).__name__ == "NormativaTextParser"

    def test_get_metadata_parser(self):
        from legalize.countries import get_metadata_parser
        parser = get_metadata_parser("it")
        assert type(parser).__name__ == "NormativaMetadataParser"
