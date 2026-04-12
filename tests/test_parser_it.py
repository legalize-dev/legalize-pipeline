"""Tests for the Italian Normattiva parser (Akoma Ntoso XML)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest  # noqa: F401 (used by pytest framework)

from legalize.countries import get_metadata_parser, get_text_parser, supported_countries
from legalize.fetcher.it.parser import (
    NormattivaMetadataParser,
    NormattivaTextParser,
    _clean_text,
)
from legalize.models import NormStatus, Rank

FIXTURES = Path(__file__).parent / "fixtures" / "it"

LEGGE_2024 = FIXTURES / "sample-legge-2024.xml"
LEGGE_COST = FIXTURES / "sample-legge-costituzionale.xml"
DLGS = FIXTURES / "sample-decreto-legislativo.xml"
DL = FIXTURES / "sample-decreto-legge.xml"
CODICE_PENALE = FIXTURES / "sample-codice-penale.xml"
WITH_TABLES = FIXTURES / "sample-with-tables.xml"


# -----------------------------------------------
# Text parser
# -----------------------------------------------


class TestNormattivaTextParser:
    def setup_method(self):
        self.parser = NormattivaTextParser()

    def test_parse_legge_2024_block_count(self):
        blocks = self.parser.parse_text(LEGGE_2024.read_bytes())
        # 11 articles + preface + preamble + conclusions = ~14 blocks
        assert len(blocks) >= 13

    def test_legge_2024_has_articles(self):
        blocks = self.parser.parse_text(LEGGE_2024.read_bytes())
        articles = [b for b in blocks if b.block_type == "article"]
        assert len(articles) == 11

    def test_legge_2024_article_ids(self):
        blocks = self.parser.parse_text(LEGGE_2024.read_bytes())
        articles = [b for b in blocks if b.block_type == "article"]
        assert articles[0].id == "art_1"
        assert articles[-1].id == "art_11"

    def test_legge_2024_article_titles(self):
        blocks = self.parser.parse_text(LEGGE_2024.read_bytes())
        articles = [b for b in blocks if b.block_type == "article"]
        # Art 2 has a heading
        assert "Procedimento" in articles[1].title
        assert "intese" in articles[1].title

    def test_legge_2024_paragraphs(self):
        blocks = self.parser.parse_text(LEGGE_2024.read_bytes())
        articles = [b for b in blocks if b.block_type == "article"]
        # Art 2 has 8 numbered commi + amendment notes paragraph
        art2 = articles[1]
        paras = art2.versions[0].paragraphs
        assert len(paras) > 5

    def test_legge_2024_first_article_text(self):
        blocks = self.parser.parse_text(LEGGE_2024.read_bytes())
        articles = [b for b in blocks if b.block_type == "article"]
        all_text = " ".join(p.text for p in articles[0].versions[0].paragraphs)
        assert "unita' nazionale" in all_text or "Finalita" in all_text

    def test_legge_2024_has_preface(self):
        blocks = self.parser.parse_text(LEGGE_2024.read_bytes())
        prefaces = [b for b in blocks if b.id == "preface"]
        assert len(prefaces) == 1
        text = prefaces[0].versions[0].paragraphs[0].text
        assert "LEGGE" in text

    def test_legge_2024_has_preamble(self):
        blocks = self.parser.parse_text(LEGGE_2024.read_bytes())
        preambles = [b for b in blocks if b.id == "preamble"]
        assert len(preambles) == 1
        text = " ".join(p.text for p in preambles[0].versions[0].paragraphs)
        assert "Camera" in text or "Senato" in text

    def test_dlgs_has_chapters(self):
        """D.Lgs 13/2024 has chapters (titoli/capi) with nested articles."""
        blocks = self.parser.parse_text(DLGS.read_bytes())
        chapters = [b for b in blocks if b.block_type == "chapter"]
        assert len(chapters) >= 5

    def test_dlgs_has_all_articles(self):
        """D.Lgs 13/2024 has 43 articles nested in chapters."""
        blocks = self.parser.parse_text(DLGS.read_bytes())
        articles = [b for b in blocks if b.block_type == "article"]
        assert len(articles) == 43

    def test_legge_costituzionale_rank(self):
        blocks = self.parser.parse_text(LEGGE_COST.read_bytes())
        articles = [b for b in blocks if b.block_type == "article"]
        assert len(articles) >= 1

    def test_codice_penale_blocks(self):
        """Codice Penale AKN contains the enabling decree (3 articles)."""
        blocks = self.parser.parse_text(CODICE_PENALE.read_bytes())
        articles = [b for b in blocks if b.block_type == "article"]
        assert len(articles) >= 1

    def test_with_tables_has_table_paragraphs(self):
        """D.Lgs 237/2017 has table content in attachment appendices."""
        blocks = self.parser.parse_text(WITH_TABLES.read_bytes())
        # Tables are in attachments; check they're parsed
        attachment_blocks = [b for b in blocks if b.block_type == "attachment"]
        assert len(attachment_blocks) > 0
        # The attachment content should contain pipe chars (ASCII-art tables)
        att_text = " ".join(
            p.text for b in attachment_blocks for v in b.versions for p in v.paragraphs
        )
        assert "|" in att_text

    def test_decreto_legge(self):
        blocks = self.parser.parse_text(DL.read_bytes())
        articles = [b for b in blocks if b.block_type == "article"]
        assert len(articles) >= 10

    def test_cross_references_preserved(self):
        """Cross-references in <ref> should be converted to Markdown links."""
        blocks = self.parser.parse_text(LEGGE_2024.read_bytes())
        articles = [b for b in blocks if b.block_type == "article"]
        # Art 2 has many cross-references
        all_text = " ".join(
            p.text for p in articles[1].versions[0].paragraphs
        )
        # Should have Markdown link syntax
        assert "[" in all_text and "](" in all_text

    def test_version_has_dates(self):
        blocks = self.parser.parse_text(LEGGE_2024.read_bytes())
        articles = [b for b in blocks if b.block_type == "article"]
        version = articles[0].versions[0]
        assert version.publication_date is not None
        assert version.effective_date is not None

    def test_empty_xml(self):
        """Empty/invalid XML should return empty list."""
        result = self.parser.parse_text(
            b'<?xml version="1.0"?><akomaNtoso xmlns="http://docs.oasis-open.org/legaldocml/ns/akn/3.0"></akomaNtoso>'
        )
        assert result == []


# -----------------------------------------------
# Metadata parser
# -----------------------------------------------


class TestNormattivaMetadataParser:
    def setup_method(self):
        self.parser = NormattivaMetadataParser()

    def test_legge_2024_metadata(self):
        meta = self.parser.parse(LEGGE_2024.read_bytes(), "24G00104")
        assert meta.country == "it"
        assert "LEGGE" in meta.title
        assert "autonomia" in meta.title.lower()

    def test_legge_2024_identifier(self):
        meta = self.parser.parse(LEGGE_2024.read_bytes(), "24G00104")
        # codiceRedazionale passed as norm_id should be used
        assert meta.identifier == "24G00104"

    def test_legge_2024_rank(self):
        meta = self.parser.parse(LEGGE_2024.read_bytes(), "24G00104")
        assert meta.rank == Rank("legge")

    def test_legge_2024_publication_date(self):
        meta = self.parser.parse(LEGGE_2024.read_bytes(), "24G00104")
        assert meta.publication_date == date(2024, 6, 28)

    def test_legge_2024_source_url(self):
        meta = self.parser.parse(LEGGE_2024.read_bytes(), "24G00104")
        assert "normattiva.it" in meta.source

    def test_legge_2024_status(self):
        meta = self.parser.parse(LEGGE_2024.read_bytes(), "24G00104")
        assert meta.status == NormStatus.IN_FORCE

    def test_legge_2024_extra(self):
        meta = self.parser.parse(LEGGE_2024.read_bytes(), "24G00104")
        extra_dict = dict(meta.extra)
        assert "urn_nir" in extra_dict
        assert "urn:nir:stato:legge:2024-06-26;86" in extra_dict["urn_nir"]

    def test_dlgs_rank(self):
        meta = self.parser.parse(DLGS.read_bytes(), "24G00013")
        assert meta.rank == Rank("decreto_legislativo")

    def test_decreto_legge_rank(self):
        meta = self.parser.parse(DL.read_bytes(), "25G00211")
        assert meta.rank == Rank("decreto_legge")

    def test_legge_costituzionale_rank(self):
        meta = self.parser.parse(LEGGE_COST.read_bytes(), "02G0227")
        assert meta.rank == Rank("legge_costituzionale")

    def test_codice_penale_rank(self):
        meta = self.parser.parse(CODICE_PENALE.read_bytes(), "042U0262")
        assert meta.rank == Rank("regio_decreto")

    def test_identifier_from_urn(self):
        """When norm_id is a URN, identifier should be filesystem-safe."""
        meta = self.parser.parse(
            LEGGE_2024.read_bytes(),
            "urn:nir:stato:legge:2024-06-26;86",
        )
        assert "/" not in meta.identifier
        assert ":" not in meta.identifier


# -----------------------------------------------
# Registry
# -----------------------------------------------


class TestItalyRegistry:
    def test_registry_has_it(self):
        assert "it" in supported_countries()

    def test_get_text_parser(self):
        parser = get_text_parser("it")
        assert isinstance(parser, NormattivaTextParser)

    def test_get_metadata_parser(self):
        parser = get_metadata_parser("it")
        assert isinstance(parser, NormattivaMetadataParser)


# -----------------------------------------------
# Utility helpers
# -----------------------------------------------


class TestCleanText:
    def test_strips_control_chars(self):
        assert _clean_text("hello\x00world") == "helloworld"

    def test_collapses_whitespace(self):
        assert _clean_text("hello   world") == "hello world"

    def test_strips_nbsp(self):
        assert _clean_text("hello\u00a0world") == "hello world"
