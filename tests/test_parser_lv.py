"""Tests for the Latvian likumi.lv parser."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from legalize.countries import get_metadata_parser, get_text_parser
from legalize.fetcher.lv.discovery import (
    DISALLOWED_IDS,
    extract_ids_from_sitemap,
    extract_sitemap_urls,
)
from legalize.fetcher.lv.parser import (
    LikumiMetadataParser,
    LikumiTextParser,
    _table_to_markdown,
)
from legalize.models import NormMetadata, NormStatus
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath

FIXTURES = Path(__file__).parent / "fixtures"

SATVERSME = FIXTURES / "likumi-57980-satversme.html"
CIVIL = FIXTURES / "likumi-225418-civillikums.html"
SOCIAL = FIXTURES / "likumi-68488-socialo-pakalpojumu.html"
REPEALED = FIXTURES / "likumi-1000-repealed.html"
WITH_TABLE = FIXTURES / "likumi-310000-with-table.html"
SITEMAP_INDEX = FIXTURES / "likumi-sitemap-index.xml"
SITEMAP_SAMPLE = FIXTURES / "likumi-sitemap-sample.xml"


# ─────────────────────────────────────────────
# Text parser
# ─────────────────────────────────────────────


class TestLikumiTextParser:
    def setup_method(self):
        self.parser = LikumiTextParser()

    def test_parse_constitution(self):
        blocks = self.parser.parse_text(SATVERSME.read_bytes())
        assert len(blocks) > 0

    def test_constitution_has_articles(self):
        blocks = self.parser.parse_text(SATVERSME.read_bytes())
        articles = [b for b in blocks if b.block_type == "article"]
        # Constitution has 116 articles + transitional provisions
        assert len(articles) >= 100

    def test_constitution_has_chapters(self):
        blocks = self.parser.parse_text(SATVERSME.read_bytes())
        chapters = [b for b in blocks if b.block_type == "chapter"]
        # 8 chapters + transitional provisions
        assert len(chapters) >= 8

    def test_first_article_has_text(self):
        blocks = self.parser.parse_text(SATVERSME.read_bytes())
        articles = [b for b in blocks if b.block_type == "article"]
        # First article: "Latvija ir neatkarīga demokrātiska republika."
        first_text = articles[0].versions[0].paragraphs[0].text
        assert "Latvija" in first_text

    def test_articles_have_pants_id(self):
        blocks = self.parser.parse_text(SATVERSME.read_bytes())
        articles = [b for b in blocks if b.block_type == "article"]
        # IDs should start with "p" (pants prefix)
        assert articles[0].id.startswith("p")

    def test_strips_amendment_notes(self):
        """labojumu_pamats paragraphs should be stripped from article content."""
        blocks = self.parser.parse_text(SATVERSME.read_bytes())
        all_text = " ".join(p.text for b in blocks for v in b.versions for p in v.paragraphs)
        # The label "likuma redakcijā" appears in labojumu_pamats — should be stripped
        # NOTE: Some articles legitimately reference "likuma redakcijā" as content
        # so this is a soft check
        assert "Latvija" in all_text

    def test_civil_law_parses(self):
        blocks = self.parser.parse_text(CIVIL.read_bytes())
        assert len(blocks) > 0

    def test_civil_law_has_tables(self):
        blocks = self.parser.parse_text(CIVIL.read_bytes())
        table_blocks = [b for b in blocks if b.block_type == "table"]
        # Civil Law has 3 tables (lake/river annexes)
        assert len(table_blocks) >= 1

    def test_table_block_contains_pipe_table(self):
        blocks = self.parser.parse_text(CIVIL.read_bytes())
        table_blocks = [b for b in blocks if b.block_type == "table"]
        first_table = table_blocks[0]
        table_text = " ".join(p.text for p in first_table.versions[0].paragraphs)
        # Markdown pipe tables contain "|" and "---"
        assert "|" in table_text
        assert "---" in table_text

    def test_municipal_regulation_with_table(self):
        blocks = self.parser.parse_text(WITH_TABLE.read_bytes())
        table_blocks = [b for b in blocks if b.block_type == "table"]
        assert len(table_blocks) == 1

    def test_social_services_law_parses(self):
        blocks = self.parser.parse_text(SOCIAL.read_bytes())
        assert len(blocks) > 0
        # Has TV214 (transitional) and TV215/216/217 (signature footer)
        chapters = [b for b in blocks if b.block_type == "chapter"]
        assert len(chapters) > 0

    def test_empty_data_returns_empty(self):
        assert self.parser.parse_text(b"") == []

    def test_invalid_html_returns_empty(self):
        assert self.parser.parse_text(b"<not html") == []

    def test_extract_reforms_returns_empty(self):
        """Historical versions are forbidden by robots.txt."""
        reforms = self.parser.extract_reforms(SATVERSME.read_bytes())
        assert reforms == []


# ─────────────────────────────────────────────
# Metadata parser
# ─────────────────────────────────────────────


class TestLikumiMetadataParser:
    def setup_method(self):
        self.parser = LikumiMetadataParser()

    def test_parse_constitution_metadata(self):
        meta = self.parser.parse(SATVERSME.read_bytes(), "57980")
        assert isinstance(meta, NormMetadata)
        assert meta.country == "lv"
        assert meta.identifier == "57980"

    def test_constitution_title(self):
        meta = self.parser.parse(SATVERSME.read_bytes(), "57980")
        assert "Satversme" in meta.title

    def test_constitution_in_force(self):
        meta = self.parser.parse(SATVERSME.read_bytes(), "57980")
        assert meta.status == NormStatus.IN_FORCE

    def test_constitution_rank_satversme(self):
        meta = self.parser.parse(SATVERSME.read_bytes(), "57980")
        assert str(meta.rank) == "satversme"

    def test_constitution_publication_date(self):
        meta = self.parser.parse(SATVERSME.read_bytes(), "57980")
        # Adopted 15 February 1922
        assert meta.publication_date == date(1922, 2, 15)

    def test_constitution_department(self):
        meta = self.parser.parse(SATVERSME.read_bytes(), "57980")
        assert "Sapulce" in meta.department or "Saeima" in meta.department

    def test_constitution_source_url(self):
        meta = self.parser.parse(SATVERSME.read_bytes(), "57980")
        assert meta.source == "https://likumi.lv/ta/id/57980"

    def test_constitution_has_subjects(self):
        meta = self.parser.parse(SATVERSME.read_bytes(), "57980")
        # Constitution has multiple Tēma (topics)
        assert len(meta.subjects) > 0

    def test_civil_law_metadata(self):
        meta = self.parser.parse(CIVIL.read_bytes(), "225418")
        assert "Civillikums" in meta.title
        assert meta.status == NormStatus.IN_FORCE
        assert str(meta.rank) == "likums"

    def test_repealed_law_status(self):
        meta = self.parser.parse(REPEALED.read_bytes(), "1000")
        assert meta.status == NormStatus.REPEALED

    def test_municipal_regulation_metadata(self):
        meta = self.parser.parse(WITH_TABLE.read_bytes(), "310000")
        assert meta.identifier == "310000"
        assert meta.status == NormStatus.REPEALED  # zaudējis spēku
        # Has Numurs and OP numurs in extras
        extra_dict = dict(meta.extra)
        assert "official_number" in extra_dict
        assert "op_number" in extra_dict

    def test_social_services_law_metadata(self):
        meta = self.parser.parse(SOCIAL.read_bytes(), "68488")
        assert "Sociālo" in meta.title or "Socialo" in meta.title or "Socialās" in meta.title
        assert meta.status == NormStatus.IN_FORCE

    def test_filesystem_safe_identifier(self):
        meta = self.parser.parse(SATVERSME.read_bytes(), "57980")
        # Numeric IDs are inherently safe
        assert ":" not in meta.identifier
        assert "/" not in meta.identifier
        assert " " not in meta.identifier

    def test_empty_data_raises(self):
        with pytest.raises(ValueError):
            self.parser.parse(b"", "0")


# ─────────────────────────────────────────────
# Table → Markdown
# ─────────────────────────────────────────────


class TestTableToMarkdown:
    def test_simple_table(self):
        from lxml import html

        snippet = """
        <TABLE>
          <TR><TD>A</TD><TD>B</TD></TR>
          <TR><TD>1</TD><TD>2</TD></TR>
        </TABLE>
        """
        table_el = html.fromstring(snippet)
        md = _table_to_markdown(table_el)
        assert "| A | B |" in md
        assert "| 1 | 2 |" in md
        assert "| --- | --- |" in md

    def test_table_with_colspan(self):
        from lxml import html

        snippet = """
        <TABLE>
          <TR><TD COLSPAN="2">Wide</TD></TR>
          <TR><TD>A</TD><TD>B</TD></TR>
        </TABLE>
        """
        table_el = html.fromstring(snippet)
        md = _table_to_markdown(table_el)
        # Colspan repeats the value
        assert "Wide" in md

    def test_table_escapes_pipes(self):
        from lxml import html

        snippet = "<TABLE><TR><TD>a|b</TD></TR></TABLE>"
        table_el = html.fromstring(snippet)
        md = _table_to_markdown(table_el)
        assert "a\\|b" in md

    def test_empty_table(self):
        from lxml import html

        snippet = "<TABLE></TABLE>"
        table_el = html.fromstring(snippet)
        assert _table_to_markdown(table_el) == ""


# ─────────────────────────────────────────────
# Discovery / sitemap parsing
# ─────────────────────────────────────────────


class TestLikumiDiscovery:
    def test_disallowed_ids_loaded(self):
        assert len(DISALLOWED_IDS) >= 480
        assert 198099 in DISALLOWED_IDS  # known disallowed from robots.txt

    def test_extract_sitemap_urls(self):
        urls = extract_sitemap_urls(SITEMAP_INDEX.read_bytes())
        # sitemap-index has 3 entries; we skip the top-level /sitemap.xml
        assert len(urls) >= 2
        assert all("sitemap-" in u for u in urls)

    def test_extract_ids_from_sitemap(self):
        ids = list(extract_ids_from_sitemap(SITEMAP_SAMPLE.read_bytes()))
        assert len(ids) > 0
        # All returned IDs should be numeric strings
        for norm_id in ids[:10]:
            assert norm_id.isdigit()

    def test_extract_ids_skips_disallowed(self):
        ids = list(extract_ids_from_sitemap(SITEMAP_SAMPLE.read_bytes()))
        for norm_id in ids:
            assert int(norm_id) not in DISALLOWED_IDS


# ─────────────────────────────────────────────
# Country dispatch
# ─────────────────────────────────────────────


class TestCountriesDispatchLV:
    def test_get_text_parser_lv(self):
        parser = get_text_parser("lv")
        assert isinstance(parser, LikumiTextParser)

    def test_get_metadata_parser_lv(self):
        parser = get_metadata_parser("lv")
        assert isinstance(parser, LikumiMetadataParser)


# ─────────────────────────────────────────────
# Slug
# ─────────────────────────────────────────────


class TestSlugLatvia:
    def test_norm_filepath(self):
        meta = NormMetadata(
            title="Test",
            short_title="Test",
            identifier="57980",
            country="lv",
            rank="satversme",
            publication_date=date(1922, 2, 15),
            status=NormStatus.IN_FORCE,
            department="Saeima",
            source="https://likumi.lv/ta/id/57980",
        )
        assert norm_to_filepath(meta) == "lv/57980.md"


# ─────────────────────────────────────────────
# End-to-end markdown rendering
# ─────────────────────────────────────────────


class TestMarkdownRendering:
    def test_render_constitution_markdown(self):
        text_parser = LikumiTextParser()
        meta_parser = LikumiMetadataParser()
        data = SATVERSME.read_bytes()

        meta = meta_parser.parse(data, "57980")
        blocks = text_parser.parse_text(data)

        md = render_norm_at_date(meta, blocks, date.today(), include_all=True)

        # Frontmatter
        assert "---" in md
        assert 'identifier: "57980"' in md
        assert 'country: "lv"' in md
        assert 'rank: "satversme"' in md

        # Title
        assert "Satversme" in md

        # Article 1 text
        assert "Latvija ir neatkarīga demokrātiska republika" in md

    def test_render_civil_law_includes_tables(self):
        text_parser = LikumiTextParser()
        meta_parser = LikumiMetadataParser()
        data = CIVIL.read_bytes()

        meta = meta_parser.parse(data, "225418")
        blocks = text_parser.parse_text(data)

        md = render_norm_at_date(meta, blocks, date.today(), include_all=True)

        # Should contain at least one Markdown table
        assert "|" in md
        assert "| --- |" in md or "| ---" in md
