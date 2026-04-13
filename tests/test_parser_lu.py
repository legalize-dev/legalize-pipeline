"""Tests for the Luxembourg Legilux parser (country=lu)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from legalize.countries import get_metadata_parser, get_text_parser
from legalize.fetcher.lu.client import _eli_to_norm_id, _norm_id_to_eli
from legalize.fetcher.lu.parser import (
    LegiluxMetadataParser,
    LegiluxTextParser,
    _extract_text,
    _tag,
)
from legalize.models import NormStatus, Rank

FIXTURES = Path(__file__).parent / "fixtures" / "lu"


# ─── Helpers ────────────────────────────────────────────────────────────────


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture(scope="module")
def text_parser() -> LegiluxTextParser:
    return LegiluxTextParser()


@pytest.fixture(scope="module")
def meta_parser() -> LegiluxMetadataParser:
    return LegiluxMetadataParser()


# ─── Country registry dispatch ──────────────────────────────────────────────


class TestCountryDispatch:
    def test_text_parser_is_registered(self):
        parser = get_text_parser("lu")
        assert isinstance(parser, LegiluxTextParser)

    def test_metadata_parser_is_registered(self):
        parser = get_metadata_parser("lu")
        assert isinstance(parser, LegiluxMetadataParser)


# ─── ELI ↔ Norm ID conversion ──────────────────────────────────────────────


class TestEliConversion:
    def test_loi_roundtrip(self):
        eli = "http://data.legilux.public.lu/eli/etat/leg/loi/2022/05/27/a250/jo"
        norm_id = _eli_to_norm_id(eli)
        assert norm_id == "leg-loi-2022-05-27-a250"
        assert _norm_id_to_eli(norm_id) == eli

    def test_constitution_roundtrip(self):
        eli = "http://data.legilux.public.lu/eli/etat/leg/constitution/1868/10/17/n1/jo"
        norm_id = _eli_to_norm_id(eli)
        assert norm_id == "leg-constitution-1868-10-17-n1"
        assert _norm_id_to_eli(norm_id) == eli

    def test_rgd_roundtrip(self):
        eli = "http://data.legilux.public.lu/eli/etat/leg/rgd/2026/04/02/a185/jo"
        norm_id = _eli_to_norm_id(eli)
        assert norm_id == "leg-rgd-2026-04-02-a185"
        assert _norm_id_to_eli(norm_id) == eli


# ─── Metadata extraction ────────────────────────────────────────────────────


class TestMetadataParser:
    def test_ordinary_law_metadata(self, meta_parser: LegiluxMetadataParser):
        data = _load("sample-ordinary-law.xml")
        meta = meta_parser.parse(data, "leg-loi-2022-05-27-a250")
        assert meta.identifier == "leg-loi-2022-05-27-a250"
        assert meta.country == "lu"
        assert meta.rank == Rank("loi")
        assert "enseignement musical" in meta.title
        assert meta.publication_date == date(2022, 5, 27)
        assert meta.status == NormStatus.IN_FORCE
        assert meta.department == "MEN"
        assert "eli" in meta.source

    def test_constitution_metadata(self, meta_parser: LegiluxMetadataParser):
        data = _load("sample-constitution.xml")
        meta = meta_parser.parse(data, "leg-constitution-1868-10-17-n1")
        assert meta.identifier == "leg-constitution-1868-10-17-n1"
        assert meta.rank == Rank("constitution")
        assert meta.publication_date == date(1868, 10, 17)
        assert "Constitution" in meta.title

    def test_regulation_metadata(self, meta_parser: LegiluxMetadataParser):
        data = _load("sample-regulation.xml")
        meta = meta_parser.parse(data, "leg-rgd-2026-04-02-a185")
        assert meta.identifier == "leg-rgd-2026-04-02-a185"
        assert meta.rank == Rank("reglement_grand_ducal")
        assert meta.publication_date == date(2026, 4, 2)

    def test_extra_fields_captured(self, meta_parser: LegiluxMetadataParser):
        data = _load("sample-ordinary-law.xml")
        meta = meta_parser.parse(data, "leg-loi-2022-05-27-a250")
        extra_keys = [k for k, v in meta.extra]
        assert "eli" in extra_keys
        assert "memorial_date" in extra_keys
        assert "entry_in_force" in extra_keys
        assert "complex_work" in extra_keys

    def test_relations_captured(self, meta_parser: LegiluxMetadataParser):
        data = _load("sample-ordinary-law.xml")
        meta = meta_parser.parse(data, "leg-loi-2022-05-27-a250")
        extra = dict(meta.extra)
        assert "modifies" in extra
        assert "repeals" in extra
        assert "cites" in extra


# ─── Text parsing ────────────────────────────────────────────────────────────


class TestTextParser:
    def test_ordinary_law_produces_blocks(self, text_parser: LegiluxTextParser):
        data = _load("sample-ordinary-law.xml")
        blocks = text_parser.parse_text(data)
        assert len(blocks) >= 1
        block = blocks[0]
        assert block.id == "main"
        assert block.block_type == "content"
        assert len(block.versions) == 1

    def test_ordinary_law_paragraphs(self, text_parser: LegiluxTextParser):
        data = _load("sample-ordinary-law.xml")
        blocks = text_parser.parse_text(data)
        paras = blocks[0].versions[0].paragraphs
        # Should have preamble, articles, signatures
        assert len(paras) > 50
        # Should contain preamble elements (title is rendered by pipeline, not parser)
        preamble_paras = [p for p in paras if p.css_class == "preamble"]
        assert len(preamble_paras) > 0
        # Should contain article content
        abs_paras = [p for p in paras if p.css_class == "abs"]
        assert len(abs_paras) > 10
        # Should have chapter headings
        heading_paras = [p for p in paras if p.css_class.startswith("h")]
        assert len(heading_paras) > 5

    def test_constitution_paragraphs(self, text_parser: LegiluxTextParser):
        data = _load("sample-constitution.xml")
        blocks = text_parser.parse_text(data)
        paras = blocks[0].versions[0].paragraphs
        # Constitution has 121 articles
        h4_paras = [p for p in paras if p.css_class.startswith("h")]
        assert len(h4_paras) > 100
        # Check article numbering
        art_paras = [p for p in paras if "Art." in p.text]
        assert len(art_paras) > 100

    def test_regulation_produces_blocks(self, text_parser: LegiluxTextParser):
        data = _load("sample-regulation.xml")
        blocks = text_parser.parse_text(data)
        assert len(blocks) >= 1
        paras = blocks[0].versions[0].paragraphs
        assert len(paras) > 0

    def test_version_date_extracted(self, text_parser: LegiluxTextParser):
        data = _load("sample-ordinary-law.xml")
        blocks = text_parser.parse_text(data)
        version = blocks[0].versions[0]
        assert version.publication_date == date(2022, 5, 27)

    def test_bold_preserved(self, text_parser: LegiluxTextParser):
        data = _load("sample-ordinary-law.xml")
        blocks = text_parser.parse_text(data)
        paras = blocks[0].versions[0].paragraphs
        # Chapter headings should have bold markers
        bold_paras = [p for p in paras if "**" in p.text]
        assert len(bold_paras) > 0

    def test_superscript_preserved(self, text_parser: LegiluxTextParser):
        data = _load("sample-ordinary-law.xml")
        blocks = text_parser.parse_text(data)
        paras = blocks[0].versions[0].paragraphs
        # "1er" should be preserved as superscript
        sup_paras = [p for p in paras if "<sup>" in p.text]
        assert len(sup_paras) > 0

    def test_lists_preserved(self, text_parser: LegiluxTextParser):
        data = _load("sample-ordinary-law.xml")
        blocks = text_parser.parse_text(data)
        paras = blocks[0].versions[0].paragraphs
        list_paras = [p for p in paras if p.css_class == "list"]
        assert len(list_paras) > 0

    def test_consolidation_code_parsed(self, text_parser: LegiluxTextParser):
        """Test parsing a large consolidation XML (code-like document)."""
        data = _load("sample-code.xml")
        blocks = text_parser.parse_text(data)
        assert len(blocks) >= 1
        paras = blocks[0].versions[0].paragraphs
        # Large code should have many paragraphs
        assert len(paras) > 100


# ─── Inline formatting ──────────────────────────────────────────────────────


class TestInlineFormatting:
    def test_extract_text_bold(self):
        from xml.etree.ElementTree import fromstring

        el = fromstring("<p>Hello <b>world</b> test</p>")
        assert _extract_text(el) == "Hello **world** test"

    def test_extract_text_italic(self):
        from xml.etree.ElementTree import fromstring

        el = fromstring("<p>Hello <i>world</i> test</p>")
        assert _extract_text(el) == "Hello *world* test"

    def test_extract_text_sup(self):
        from xml.etree.ElementTree import fromstring

        el = fromstring("<p>Art. 1<sup>er</sup> text</p>")
        assert _extract_text(el) == "Art. 1<sup>er</sup> text"

    def test_extract_text_ref(self):
        from xml.etree.ElementTree import fromstring

        el = fromstring('<p>See <ref href="http://example.com">link</ref> here</p>')
        assert _extract_text(el) == "See [link](http://example.com) here"

    def test_extract_text_nested(self):
        from xml.etree.ElementTree import fromstring

        el = fromstring("<p><b>Chapter 1<sup>er</sup></b> Title</p>")
        result = _extract_text(el)
        assert "**" in result
        assert "<sup>" in result

    def test_tag_strips_namespace(self):
        from xml.etree.ElementTree import fromstring

        el = fromstring(
            '<p xmlns="http://docs.oasis-open.org/legaldocml/ns/akn/3.0/CSD13">test</p>'
        )
        assert _tag(el) == "p"

    def test_tag_no_namespace(self):
        from xml.etree.ElementTree import fromstring

        el = fromstring("<p>test</p>")
        assert _tag(el) == "p"
