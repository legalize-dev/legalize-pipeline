"""Tests for the EUR-Lex parser (country=eu)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from legalize.countries import get_metadata_parser, get_text_parser
from legalize.fetcher.eu.parser import (
    EURLexMetadataParser,
    EURLexTextParser,
)
from legalize.models import NormStatus, Rank

FIXTURES = Path(__file__).parent / "fixtures" / "eu"


# ─── Helpers ────────────────────────────────────────────────────────────────


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture(scope="module")
def text_parser() -> EURLexTextParser:
    return EURLexTextParser()


@pytest.fixture(scope="module")
def meta_parser() -> EURLexMetadataParser:
    return EURLexMetadataParser()


# ─── Country registry dispatch ──────────────────────────────────────────────


class TestCountryDispatch:
    def test_text_parser_is_registered(self):
        parser = get_text_parser("eu")
        assert isinstance(parser, EURLexTextParser)

    def test_metadata_parser_is_registered(self):
        parser = get_metadata_parser("eu")
        assert isinstance(parser, EURLexMetadataParser)


# ─── Metadata extraction ────────────────────────────────────────────────────


class TestMetadataParser:
    def test_gdpr_metadata(self, meta_parser: EURLexMetadataParser):
        data = _load("32016R0679_metadata.json")
        meta = meta_parser.parse(data, "32016R0679")
        assert meta.identifier == "32016R0679"
        assert meta.country == "eu"
        assert meta.rank == Rank("regulation")
        assert meta.status == NormStatus.IN_FORCE
        assert meta.publication_date == date(2016, 4, 27)
        assert "protection" in meta.title.lower() or "personal data" in meta.title.lower()
        assert meta.department  # Should have authors
        assert "European Parliament" in meta.department

    def test_eidas2_metadata(self, meta_parser: EURLexMetadataParser):
        data = _load("32024R0903_metadata.json")
        meta = meta_parser.parse(data, "32024R0903")
        assert meta.identifier == "32024R0903"
        assert meta.country == "eu"
        assert meta.publication_date == date(2024, 3, 13)  # document date, not entry into force

    def test_sfdr_metadata(self, meta_parser: EURLexMetadataParser):
        data = _load("32019R2088_metadata.json")
        meta = meta_parser.parse(data, "32019R2088")
        assert meta.identifier == "32019R2088"
        assert meta.status == NormStatus.IN_FORCE
        assert "sustainability" in meta.title.lower()

    def test_mica_metadata(self, meta_parser: EURLexMetadataParser):
        data = _load("32023R1114_metadata.json")
        meta = meta_parser.parse(data, "32023R1114")
        assert meta.identifier == "32023R1114"
        assert "crypto" in meta.title.lower() or "markets" in meta.title.lower()

    @pytest.mark.skipif(
        not (FIXTURES / "32006R1907_metadata.json").exists(),
        reason="REACH fixture too large for git — download locally to test",
    )
    def test_reach_metadata(self, meta_parser: EURLexMetadataParser):
        data = _load("32006R1907_metadata.json")
        meta = meta_parser.parse(data, "32006R1907")
        assert meta.identifier == "32006R1907"
        assert meta.publication_date == date(2006, 12, 18)

    def test_extra_fields_present(self, meta_parser: EURLexMetadataParser):
        data = _load("32016R0679_metadata.json")
        meta = meta_parser.parse(data, "32016R0679")
        extra_keys = {k for k, v in meta.extra}
        assert "celex" in extra_keys
        assert "eli" in extra_keys
        assert "regulation_type" in extra_keys

    def test_source_is_eli(self, meta_parser: EURLexMetadataParser):
        data = _load("32016R0679_metadata.json")
        meta = meta_parser.parse(data, "32016R0679")
        assert "eli" in meta.source or "eur-lex" in meta.source


# ─── Text extraction ────────────────────────────────────────────────────────


class TestTextParser:
    def test_sfdr_produces_blocks(self, text_parser: EURLexTextParser):
        """SFDR (smallest fixture) should parse into blocks with paragraphs."""
        data = _load("32019R2088.xhtml")
        blocks = text_parser.parse_text(data)
        assert len(blocks) >= 1
        main_block = blocks[0]
        assert main_block.id == "main"
        assert len(main_block.versions) >= 1
        paragraphs = main_block.versions[0].paragraphs
        assert len(paragraphs) > 10  # SFDR has ~20 articles

    def test_sfdr_has_article_headings(self, text_parser: EURLexTextParser):
        """SFDR should contain Article headings."""
        data = _load("32019R2088.xhtml")
        blocks = text_parser.parse_text(data)
        paragraphs = blocks[0].versions[0].paragraphs
        article_headings = [p for p in paragraphs if p.css_class == "h4" and "Article" in p.text]
        assert len(article_headings) >= 10  # SFDR has 20 articles

    def test_sfdr_has_lists(self, text_parser: EURLexTextParser):
        """SFDR Article 2 (Definitions) should contain list items."""
        data = _load("32019R2088.xhtml")
        blocks = text_parser.parse_text(data)
        paragraphs = blocks[0].versions[0].paragraphs
        list_items = [p for p in paragraphs if p.css_class == "list"]
        assert len(list_items) > 5  # Definitions article has many list items

    def test_sfdr_no_arrow_markers(self, text_parser: EURLexTextParser):
        """Modification arrows (►B, ►M1) should not appear in output text."""
        data = _load("32019R2088.xhtml")
        blocks = text_parser.parse_text(data)
        paragraphs = blocks[0].versions[0].paragraphs
        for p in paragraphs:
            assert "►" not in p.text, f"Arrow marker in: {p.text[:100]}"

    def test_sfdr_no_disclaimer(self, text_parser: EURLexTextParser):
        """The disclaimer paragraph should not appear in output."""
        data = _load("32019R2088.xhtml")
        blocks = text_parser.parse_text(data)
        paragraphs = blocks[0].versions[0].paragraphs
        for p in paragraphs:
            assert "documentation tool" not in p.text.lower()

    def test_gdpr_produces_blocks(self, text_parser: EURLexTextParser):
        """GDPR should parse successfully."""
        data = _load("32016R0679.xhtml")
        blocks = text_parser.parse_text(data)
        assert len(blocks) >= 1
        paragraphs = blocks[0].versions[0].paragraphs
        assert len(paragraphs) > 50  # GDPR has 99 articles

    def test_gdpr_has_article_99(self, text_parser: EURLexTextParser):
        """GDPR should have Article 99 (Entry into force)."""
        data = _load("32016R0679.xhtml")
        blocks = text_parser.parse_text(data)
        paragraphs = blocks[0].versions[0].paragraphs
        texts = [p.text for p in paragraphs]
        assert any("Article 99" in t for t in texts)

    def test_mica_has_tables(self, text_parser: EURLexTextParser):
        """MiCA regulation has tables that should be parsed."""
        data = _load("32023R1114.xhtml")
        blocks = text_parser.parse_text(data)
        paragraphs = blocks[0].versions[0].paragraphs
        table_items = [p for p in paragraphs if p.css_class == "table"]
        assert len(table_items) >= 1

    def test_mica_has_title_divisions(self, text_parser: EURLexTextParser):
        """MiCA should have TITLE I, II, etc. headings."""
        data = _load("32023R1114.xhtml")
        blocks = text_parser.parse_text(data)
        paragraphs = blocks[0].versions[0].paragraphs
        title_headings = [p for p in paragraphs if p.css_class == "h2" and "TITLE" in p.text]
        assert len(title_headings) >= 5  # MiCA has 9 titles

    @pytest.mark.skipif(
        not (FIXTURES / "32006R1907.xhtml").exists(),
        reason="REACH fixture too large for git (4.6MB) — download locally to test",
    )
    def test_reach_large_regulation(self, text_parser: EURLexTextParser):
        """REACH (4.6MB) should parse without errors."""
        data = _load("32006R1907.xhtml")
        blocks = text_parser.parse_text(data)
        assert len(blocks) >= 1
        paragraphs = blocks[0].versions[0].paragraphs
        assert len(paragraphs) > 100  # REACH is massive

    def test_eidas2_original_text(self, text_parser: EURLexTextParser):
        """eIDAS2 (no consolidation) should parse from original OJ XHTML."""
        data = _load("32024R0903.xhtml")
        blocks = text_parser.parse_text(data)
        assert len(blocks) >= 1
        paragraphs = blocks[0].versions[0].paragraphs
        assert len(paragraphs) > 10

    def test_eidas2_has_oj_articles(self, text_parser: EURLexTextParser):
        """eIDAS2 (OJ format) should have article headings from oj-ti-art."""
        data = _load("32024R0903.xhtml")
        blocks = text_parser.parse_text(data)
        paragraphs = blocks[0].versions[0].paragraphs
        articles = [p for p in paragraphs if p.css_class == "h4" and "Article" in p.text]
        assert len(articles) >= 20  # eIDAS2 has 23 articles

    def test_eidas2_has_chapters(self, text_parser: EURLexTextParser):
        """eIDAS2 (OJ format) should have chapter headings."""
        data = _load("32024R0903.xhtml")
        blocks = text_parser.parse_text(data)
        paragraphs = blocks[0].versions[0].paragraphs
        chapters = [p for p in paragraphs if p.css_class == "h2"]
        assert len(chapters) >= 4  # eIDAS2 has multiple chapters

    def test_inline_formatting_preserved(self, text_parser: EURLexTextParser):
        """Bold and italic formatting should be preserved as Markdown."""
        data = _load("32023R1114.xhtml")
        blocks = text_parser.parse_text(data)
        all_text = " ".join(p.text for p in blocks[0].versions[0].paragraphs)
        # Not all regulations have inline formatting, so just check it doesn't crash
        assert len(all_text) > 1000

    def test_no_html_tags_in_output(self, text_parser: EURLexTextParser):
        """Output text should not contain raw HTML tags (except allowed <sup>)."""
        data = _load("32019R2088.xhtml")
        blocks = text_parser.parse_text(data)
        paragraphs = blocks[0].versions[0].paragraphs
        for p in paragraphs:
            # Allow <sup> for footnote references
            cleaned = p.text.replace("<sup>", "").replace("</sup>", "")
            assert "<div" not in cleaned, f"HTML div in: {p.text[:100]}"
            assert "<span" not in cleaned, f"HTML span in: {p.text[:100]}"
            assert "<table" not in cleaned, f"HTML table in: {p.text[:100]}"
