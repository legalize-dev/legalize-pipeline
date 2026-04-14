"""Tests for the Slovak Slov-Lex fetcher (parser + metadata + discovery)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from legalize.countries import (
    get_client_class,
    get_discovery_class,
    get_metadata_parser,
    get_text_parser,
    supported_countries,
)
from legalize.fetcher.sk.client import SlovLexClient
from legalize.fetcher.sk.discovery import SlovLexDiscovery, _iri_to_norm_id
from legalize.fetcher.sk.parser import (
    SlovLexMetadataParser,
    SlovLexTextParser,
    _clean_text,
    _html_table_to_markdown,
    _parse_iso_date,
    _parse_sk_date,
    _type_code_to_rank,
    _type_to_rank,
    parse_version_history,
)
from legalize.models import NormStatus, Rank

FIXTURES = Path(__file__).parent / "fixtures" / "sk"


# ─────────────────────────────────────────────
# Registry dispatch
# ─────────────────────────────────────────────


class TestCountryDispatch:
    def test_registry_has_sk(self):
        assert "sk" in supported_countries()

    def test_sk_text_parser_class(self):
        parser = get_text_parser("sk")
        assert isinstance(parser, SlovLexTextParser)

    def test_sk_metadata_parser_class(self):
        parser = get_metadata_parser("sk")
        assert isinstance(parser, SlovLexMetadataParser)

    def test_sk_client_class(self):
        cls = get_client_class("sk")
        assert cls is SlovLexClient

    def test_sk_discovery_class(self):
        cls = get_discovery_class("sk")
        assert cls is SlovLexDiscovery


# ─────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────


class TestHelpers:
    def test_clean_text_strips_nbsp(self):
        assert _clean_text("a\xa0b") == "a b"

    def test_clean_text_strips_control_chars(self):
        assert _clean_text("hello\x00world\x7f") == "helloworld"

    def test_clean_text_normalizes_whitespace(self):
        assert _clean_text("  hello   world  ") == "hello world"

    def test_clean_text_empty(self):
        assert _clean_text("") == ""

    def test_parse_sk_date_ddmmyyyy(self):
        d = _parse_sk_date("01.09.1992")
        assert d == date(1992, 9, 1)

    def test_parse_sk_date_iso_fallback(self):
        d = _parse_sk_date("1992-09-01")
        assert d == date(1992, 9, 1)

    def test_parse_sk_date_none(self):
        assert _parse_sk_date(None) is None
        assert _parse_sk_date("") is None
        assert _parse_sk_date("   ") is None

    def test_parse_iso_date(self):
        assert _parse_iso_date("2025-01-01") == date(2025, 1, 1)

    def test_parse_iso_date_invalid(self):
        assert _parse_iso_date("not-a-date") is None

    def test_type_to_rank_law(self):
        assert _type_to_rank("Zákon") == "law"

    def test_type_to_rank_constitutional(self):
        assert _type_to_rank("Ústavný zákon") == "constitutional_law"

    def test_type_to_rank_ordinance(self):
        assert _type_to_rank("Vyhláška") == "ordinance"

    def test_type_to_rank_regulation(self):
        assert _type_to_rank("Nariadenie vlády") == "government_regulation"

    def test_type_to_rank_unknown(self):
        rank = _type_to_rank("Something new")
        assert rank == "something_new"

    def test_type_code_to_rank_law(self):
        assert _type_code_to_rank("Zakon") == "law"

    def test_type_code_to_rank_constitutional(self):
        assert _type_code_to_rank("UstavnyZakon") == "constitutional_law"

    def test_type_code_to_rank_ordinance(self):
        assert _type_code_to_rank("Vyhlaska") == "ordinance"

    def test_type_code_to_rank_regulation(self):
        assert _type_code_to_rank("NariadenieVlady") == "government_regulation"

    def test_iri_to_norm_id(self):
        assert _iri_to_norm_id("/SK/ZZ/2024/401/20250301") == "2024/401"
        assert _iri_to_norm_id("/SK/ZZ/1992/460/19921001") == "1992/460"

    def test_iri_to_norm_id_invalid(self):
        assert _iri_to_norm_id("") is None
        assert _iri_to_norm_id("/invalid/path") is None


# ─────────────────────────────────────────────
# Version history parsing — Constitution
# ─────────────────────────────────────────────


class TestVersionHistory:
    @pytest.fixture()
    def versions(self):
        data = (FIXTURES / "sample-constitution-history.html").read_bytes()
        return parse_version_history(data)

    def test_finds_all_versions(self, versions):
        assert len(versions) == 29

    def test_first_version_is_proclaimed(self, versions):
        assert versions[0]["is_proclaimed"] is True
        assert versions[0]["date_suffix"] == "vyhlasene_znenie"

    def test_second_version_has_dates(self, versions):
        v = versions[1]
        assert v["effective_from"] == date(1992, 10, 1)
        assert v["effective_to"] == date(1998, 8, 4)
        assert v["is_proclaimed"] is False

    def test_version_with_amendment(self, versions):
        # Version 3: amended by 244/1998 Z. z.
        v = versions[2]
        assert v["effective_from"] == date(1998, 8, 5)
        assert "244/1998" in v["amendment"]

    def test_last_version_has_no_end_date(self, versions):
        last = versions[-1]
        assert last["effective_to"] is None

    def test_version_iri_contains_date_suffix(self, versions):
        v = versions[1]
        assert v["date_suffix"] == "19921001"
        assert v["iri"] == "/SK/ZZ/1992/460/19921001"

    def test_multiple_amendments_in_one_version(self, versions):
        # Version 25: two amendments (422/2020 + 378/2022)
        v = versions[24]
        assert "422/2020" in v["amendment"]
        assert "378/2022" in v["amendment"]


# ─────────────────────────────────────────────
# Version history — Tax law (more versions)
# ─────────────────────────────────────────────


class TestVersionHistoryTaxLaw:
    @pytest.fixture()
    def versions(self):
        data = (FIXTURES / "sample-tax-law-history.html").read_bytes()
        return parse_version_history(data)

    def test_has_many_versions(self, versions):
        # Income Tax Act 595/2003 has many amendments
        assert len(versions) > 30


# ─────────────────────────────────────────────
# Metadata parser — Constitution
# ─────────────────────────────────────────────


class TestMetadataParserConstitution:
    @pytest.fixture()
    def meta(self):
        data = (FIXTURES / "api-constitution-meta.json").read_bytes()
        return SlovLexMetadataParser().parse(data, "1992/460")

    def test_title(self, meta):
        assert "Ústava Slovenskej republiky" in meta.title

    def test_identifier(self, meta):
        assert meta.identifier == "ZZ-1992-460"

    def test_country(self, meta):
        assert meta.country == "sk"

    def test_rank(self, meta):
        assert meta.rank == Rank("constitutional_law")

    def test_publication_date(self, meta):
        assert meta.publication_date == date(1992, 10, 1)

    def test_status_in_force(self, meta):
        assert meta.status == NormStatus.IN_FORCE

    def test_source_url(self, meta):
        assert "slov-lex.sk" in meta.source
        assert "1992/460" in meta.source

    def test_extra_has_official_citation(self, meta):
        extra_dict = dict(meta.extra)
        assert "official_citation" in extra_dict
        assert "460/1992" in extra_dict["official_citation"]

    def test_extra_has_type_display(self, meta):
        extra_dict = dict(meta.extra)
        assert extra_dict["type_display"] == "Ústavný zákon"

    def test_extra_has_type_code(self, meta):
        extra_dict = dict(meta.extra)
        assert extra_dict["type_code"] == "UstavnyZakon"

    def test_identifier_is_filesystem_safe(self, meta):
        assert ":" not in meta.identifier
        assert " " not in meta.identifier
        assert "/" not in meta.identifier


# ─────────────────────────────────────────────
# Text parser — Constitution
# ─────────────────────────────────────────────


class TestTextParserConstitution:
    @pytest.fixture()
    def blocks(self):
        data = (FIXTURES / "sample-constitution.html").read_bytes()
        return SlovLexTextParser().parse_text(data)

    def test_returns_blocks(self, blocks):
        assert len(blocks) >= 1

    def test_block_has_versions(self, blocks):
        assert len(blocks[0].versions) == 1

    def test_paragraphs_not_empty(self, blocks):
        paragraphs = blocks[0].versions[0].paragraphs
        assert len(paragraphs) > 100  # Constitution has many articles

    def test_has_preamble(self, blocks):
        texts = [p.text for p in blocks[0].versions[0].paragraphs]
        joined = " ".join(texts)
        assert "národ slovenský" in joined

    def test_has_article_headings(self, blocks):
        paragraphs = blocks[0].versions[0].paragraphs
        article_headings = [p for p in paragraphs if p.css_class == "h5"]
        assert len(article_headings) > 50

    def test_has_structural_headings(self, blocks):
        paragraphs = blocks[0].versions[0].paragraphs
        h2_headings = [p for p in paragraphs if p.css_class == "h2"]
        assert len(h2_headings) >= 5  # PRVÁ HLAVA, DRUHÁ HLAVA, etc.

    def test_no_html_tags_in_text(self, blocks):
        for p in blocks[0].versions[0].paragraphs:
            assert "<div" not in p.text, f"HTML tag in: {p.text[:80]}"
            assert "<span" not in p.text, f"HTML tag in: {p.text[:80]}"

    def test_no_control_chars(self, blocks):
        import re

        ctrl = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
        for p in blocks[0].versions[0].paragraphs:
            assert not ctrl.search(p.text), f"Control chars in: {p.text[:50]}"

    def test_no_toc_content(self, blocks):
        """Table of contents and history table should be excluded."""
        texts = [p.text for p in blocks[0].versions[0].paragraphs]
        joined = " ".join(texts)
        # Should NOT contain version history dates
        assert "01.10.1992 - 04.08.1998" not in joined
        # Should NOT contain TOC index-only content
        assert "Preskoč na obsah" not in joined


# ─────────────────────────────────────────────
# Text parser — Tax law with tables
# ─────────────────────────────────────────────


class TestTextParserTaxLaw:
    @pytest.fixture()
    def blocks(self):
        data = (FIXTURES / "sample-tax-law.html").read_bytes()
        return SlovLexTextParser().parse_text(data)

    def test_returns_blocks(self, blocks):
        assert len(blocks) >= 1

    def test_has_many_paragraphs(self, blocks):
        paragraphs = blocks[0].versions[0].paragraphs
        assert len(paragraphs) > 100  # Tax law (truncated fixture)

    def test_has_table_content(self, blocks):
        """Tax law should have tables converted to Markdown pipe tables."""
        texts = [p.text for p in blocks[0].versions[0].paragraphs]
        pipe_tables = [t for t in texts if "| " in t and " | " in t]
        assert len(pipe_tables) > 0, "No pipe tables found in tax law"


# ─────────────────────────────────────────────
# Text parser — Labour Code
# ─────────────────────────────────────────────


class TestTextParserLabourCode:
    @pytest.fixture()
    def blocks(self):
        data = (FIXTURES / "sample-labour-code.html").read_bytes()
        return SlovLexTextParser().parse_text(data)

    def test_returns_blocks(self, blocks):
        assert len(blocks) >= 1

    def test_has_many_paragraphs(self, blocks):
        paragraphs = blocks[0].versions[0].paragraphs
        assert len(paragraphs) > 300  # Labour Code is very large


# ─────────────────────────────────────────────
# Table conversion
# ─────────────────────────────────────────────


class TestTableConversion:
    def test_simple_table(self):
        from lxml import etree

        html = b"<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
        el = etree.fromstring(html)
        md = _html_table_to_markdown(el)
        assert "| A | B |" in md
        assert "| --- | --- |" in md
        assert "| 1 | 2 |" in md

    def test_table_with_pipe_in_content(self):
        from lxml import etree

        html = b"<table><tr><td>a|b</td></tr></table>"
        el = etree.fromstring(html)
        md = _html_table_to_markdown(el)
        assert "a\\|b" in md

    def test_empty_table(self):
        from lxml import etree

        el = etree.fromstring(b"<table></table>")
        assert _html_table_to_markdown(el) == ""


# ─────────────────────────────────────────────
# Text parser — edge cases
# ─────────────────────────────────────────────


class TestTextParserEdgeCases:
    def test_empty_html(self):
        blocks = SlovLexTextParser().parse_text(b"<html><body></body></html>")
        assert blocks == []

    def test_minimal_law(self):
        html = b"""
        <div class="predpis Skupina" id="predpis">
            <div class="predpisOznacenie">1</div>
            <div class="predpisTyp">TEST</div>
            <div class="text" id="predpis.text">Hello world</div>
        </div>
        """
        blocks = SlovLexTextParser().parse_text(html)
        assert len(blocks) == 1
        paragraphs = blocks[0].versions[0].paragraphs
        assert any("TEST" in p.text for p in paragraphs)
        assert any("Hello world" in p.text for p in paragraphs)
