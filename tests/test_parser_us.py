"""Tests for the US Code USLM parser."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from legalize.countries import get_metadata_parser, get_text_parser
from legalize.fetcher.us.client import build_norm_id, parse_norm_id
from legalize.fetcher.us.parser import USMetadataParser, USTextParser
from legalize.models import NormStatus
from legalize.transformer.slug import norm_to_filepath

FIXTURES = Path(__file__).parent / "fixtures" / "us"

# The title-1 fixture contains a full uscDoc envelope with <meta> + one <section>.
TITLE1_XML = FIXTURES / "sample-uscode-title1.xml"

# These fixtures are non-section documents (compilations, public laws, regulations).
COMPS_REGULATION = FIXTURES / "sample-comps-regulation.xml"
COMPS_SMALL = FIXTURES / "sample-comps-small.xml"
PUBLIC_LAW = FIXTURES / "sample-public-law-small.xml"


# ─────────────────────────────────────────────
# norm_id helpers
# ─────────────────────────────────────────────


class TestNormIdHelpers:
    def test_parse_norm_id_basic(self):
        title_num, section_id = parse_norm_id("USC-T18-S1341")
        assert title_num == 18
        assert section_id == "1341"

    def test_parse_norm_id_with_letter_suffix(self):
        title_num, section_id = parse_norm_id("USC-T1-S106a")
        assert title_num == 1
        assert section_id == "106a"

    def test_build_norm_id(self):
        assert build_norm_id(18, "1341") == "USC-T18-S1341"
        assert build_norm_id(1, "106a") == "USC-T1-S106a"

    def test_parse_norm_id_roundtrip(self):
        original = "USC-T42-S1983"
        title_num, section_id = parse_norm_id(original)
        assert build_norm_id(title_num, section_id) == original

    def test_parse_norm_id_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid US norm_id"):
            parse_norm_id("INVALID-FORMAT")
        with pytest.raises(ValueError, match="Invalid US norm_id"):
            parse_norm_id("USC-X1-S1")


# ─────────────────────────────────────────────
# Text parser
# ─────────────────────────────────────────────


class TestUSTextParser:
    def setup_method(self):
        self.parser = USTextParser()

    def test_title1_section1_returns_one_block(self):
        blocks = self.parser.parse_text(TITLE1_XML.read_bytes())
        assert len(blocks) == 1

    def test_title1_block_structure(self):
        blocks = self.parser.parse_text(TITLE1_XML.read_bytes())
        block = blocks[0]
        assert block.block_type == "section"
        assert block.id == "/us/usc/t1/s1"
        assert "Words denoting number" in block.title

    def test_title1_has_paragraphs(self):
        blocks = self.parser.parse_text(TITLE1_XML.read_bytes())
        paragraphs = blocks[0].versions[0].paragraphs
        assert len(paragraphs) > 50

    def test_title1_has_article_heading(self):
        blocks = self.parser.parse_text(TITLE1_XML.read_bytes())
        paragraphs = blocks[0].versions[0].paragraphs
        article_headings = [p for p in paragraphs if p.css_class == "articulo"]
        assert len(article_headings) >= 1
        assert "§ 1." in article_headings[0].text

    def test_title1_has_source_credit(self):
        """Source credit (Public Law references) should be in italic."""
        blocks = self.parser.parse_text(TITLE1_XML.read_bytes())
        paragraphs = blocks[0].versions[0].paragraphs
        italic_paras = [p for p in paragraphs if p.text.startswith("*") and p.text.endswith("*")]
        assert len(italic_paras) >= 1

    def test_title1_has_notes(self):
        """Statutory notes and editorial notes should be parsed."""
        blocks = self.parser.parse_text(TITLE1_XML.read_bytes())
        paragraphs = blocks[0].versions[0].paragraphs
        notes = [p for p in paragraphs if p.css_class == "seccion"]
        assert len(notes) >= 1

    def test_title1_publication_date(self):
        blocks = self.parser.parse_text(TITLE1_XML.read_bytes())
        pub_date = blocks[0].versions[0].publication_date
        assert isinstance(pub_date, date)
        # Release point 118-158 is dated 2024-12-31
        assert pub_date.year >= 2024

    def test_non_section_returns_empty(self):
        """Non-section documents (compilations, public laws) return no blocks."""
        for fixture in [COMPS_REGULATION, COMPS_SMALL, PUBLIC_LAW]:
            blocks = self.parser.parse_text(fixture.read_bytes())
            assert blocks == []


# ─────────────────────────────────────────────
# Metadata parser
# ─────────────────────────────────────────────


class TestUSMetadataParser:
    def setup_method(self):
        self.parser = USMetadataParser()

    def test_title1_metadata_core_fields(self):
        meta = self.parser.parse(TITLE1_XML.read_bytes(), "USC-T1-S1")
        assert meta.country == "us"
        assert meta.rank == "statute"
        assert meta.status == NormStatus.IN_FORCE
        assert meta.department == "United States Congress"
        assert "§ 1." in meta.title or "Words denoting" in meta.title

    def test_title1_metadata_identifier(self):
        meta = self.parser.parse(TITLE1_XML.read_bytes(), "USC-T1-S1")
        assert meta.identifier == "USC-T1-S1"

    def test_title1_metadata_source_url(self):
        meta = self.parser.parse(TITLE1_XML.read_bytes(), "USC-T1-S1")
        assert "uscode.house.gov" in meta.source
        assert "title1" in meta.source
        assert "section1" in meta.source

    def test_title1_extra_fields(self):
        meta = self.parser.parse(TITLE1_XML.read_bytes(), "USC-T1-S1")
        extra = dict(meta.extra)
        assert extra["title_number"] == "1"
        assert "release_point" in extra
        assert "source_credit" in extra

    def test_title1_positive_law(self):
        meta = self.parser.parse(TITLE1_XML.read_bytes(), "USC-T1-S1")
        extra = dict(meta.extra)
        assert extra.get("positive_law") == "yes"

    def test_publication_date_is_date(self):
        meta = self.parser.parse(TITLE1_XML.read_bytes(), "USC-T1-S1")
        assert isinstance(meta.publication_date, date)
        assert meta.publication_date.year >= 2024


# ─────────────────────────────────────────────
# Filepath / slug
# ─────────────────────────────────────────────


class TestSlug:
    def test_us_filepath(self):
        parser = USMetadataParser()
        meta = parser.parse(TITLE1_XML.read_bytes(), "USC-T1-S1")
        filepath = norm_to_filepath(meta)
        assert filepath == "us/USC-T1-S1.md"

    def test_us_filepath_with_letter_suffix(self):
        parser = USMetadataParser()
        meta = parser.parse(TITLE1_XML.read_bytes(), "USC-T1-S106a")
        filepath = norm_to_filepath(meta)
        assert filepath == "us/USC-T1-S106a.md"


# ─────────────────────────────────────────────
# Registry hookup
# ─────────────────────────────────────────────


class TestRegistryHookup:
    def test_text_parser_lookup(self):
        parser = get_text_parser("us")
        assert isinstance(parser, USTextParser)

    def test_metadata_parser_lookup(self):
        parser = get_metadata_parser("us")
        assert isinstance(parser, USMetadataParser)
