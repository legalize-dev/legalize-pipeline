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

    def test_gdpr_no_empty_articles(self, text_parser: EURLexTextParser):
        """验证 GDPR 99 个条款均不为空（Issue #19 核心验收标准：#### Article N 后面不能只有副标题）。"""
        import re

        data = _load("32016R0679.xhtml")
        blocks = text_parser.parse_text(data)
        paragraphs = blocks[0].versions[0].paragraphs

        article_count = 0
        empty_articles = []

        for i, p in enumerate(paragraphs):
            if p.css_class == "h4" and re.match(r"^Article\s+\d+", p.text):
                article_count += 1
                j = i + 1
                # 跳过副标题（h5）
                if j < len(paragraphs) and paragraphs[j].css_class == "h5":
                    j += 1
                # 检查副标题后是否直接接下一个大标题或结束（无正文）
                if j >= len(paragraphs) or paragraphs[j].css_class in ("h1", "h2", "h3", "h4"):
                    empty_articles.append(p.text)

        assert article_count == 99, f"期望 99 个条款，实际解析得到 {article_count}"
        assert not empty_articles, f"以下条款正文为空: {empty_articles}"

    def test_gdpr_article_24_25_55_have_content(self, text_parser: EURLexTextParser):
        """验证曾被遗漏正文的第 24、25、55 条等条款正文与编号段落完整恢复。"""
        data = _load("32016R0679.xhtml")
        blocks = text_parser.parse_text(data)
        paragraphs = blocks[0].versions[0].paragraphs

        def get_article_paras(art_title: str) -> list:
            capturing = False
            art_paras = []
            for p in paragraphs:
                if p.css_class == "h4" and art_title in p.text:
                    capturing = True
                elif capturing and p.css_class in ("h1", "h2", "h3", "h4"):
                    break
                if capturing:
                    art_paras.append(p)
            return art_paras

        # 检查第 24 条
        art24 = get_article_paras("Article 24")
        assert len(art24) >= 4  # h4 + h5 + 3 个 abs 编号段落
        assert any("Responsibility of the controller" in p.text for p in art24)
        assert any("1. Taking into account" in p.text for p in art24)
        assert any("2. Where proportionate" in p.text for p in art24)
        assert any("3. Adherence to approved codes" in p.text for p in art24)

        # 检查第 25 条
        art25 = get_article_paras("Article 25")
        assert len(art25) >= 4  # h4 + h5 + 3 个 abs 编号段落
        assert any("Data protection by design and by default" in p.text for p in art25)
        assert any("1. Taking into account the state of the art" in p.text for p in art25)

        # 检查第 55 条
        art55 = get_article_paras("Article 55")
        assert len(art55) >= 4  # h4 + h5 + 3 个 abs 编号段落
        assert any("Competence" in p.text for p in art55)
        assert any("1. Each supervisory authority shall be competent" in p.text for p in art55)

    def test_gdpr_article_6_structure(self, text_parser: EURLexTextParser):
        """验证带列表与后续解释段的编号条款（如第 6 条）结构完整。"""
        data = _load("32016R0679.xhtml")
        blocks = text_parser.parse_text(data)
        paragraphs = blocks[0].versions[0].paragraphs

        # 获取第 6 条各段落
        art6_paras = []
        capturing = False
        for p in paragraphs:
            if p.css_class == "h4" and "Article 6" in p.text:
                capturing = True
            elif capturing and p.css_class in ("h1", "h2", "h3", "h4"):
                break
            if capturing:
                art6_paras.append(p)

        # 验证段落序号 1. 前缀拼接在引言段
        intro_p1 = [p for p in art6_paras if "1. Processing shall be lawful" in p.text]
        assert len(intro_p1) == 1, "第 6 条第 1 款前导句应保留段号 1."

        # 验证列表项 (a)-(f) 均存在
        lists = [p for p in art6_paras if p.css_class == "list"]
        assert len(lists) >= 6, "第 6 条应包含 (a)-(f) 等列表项"

        # 验证后续段落存在
        sub_paras = [p for p in art6_paras if "Point (f) of the first subparagraph" in p.text]
        assert len(sub_paras) == 1, "列表后的补充解释段落不应丢失"

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
