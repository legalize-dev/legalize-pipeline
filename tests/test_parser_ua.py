"""Tests for the Ukraine (UA) fetcher — parser, discovery, dispatch."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from legalize.countries import get_metadata_parser, get_text_parser
from legalize.fetcher.ua.discovery import (
    RadaDiscovery,
    nreg_to_identifier,
    parse_discovery_list,
    parse_type_list,
)
from legalize.fetcher.ua.parser import RadaMetadataParser, RadaTextParser
from legalize.models import NormStatus
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath

FIXTURES = Path(__file__).parent / "fixtures" / "ua"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ─── Text Parser ───


class TestRadaTextParser:
    """Test article/chapter/preamble extraction from .txt format."""

    parser = RadaTextParser()

    def test_constitution_has_articles(self):
        blocks = self.parser.parse_text(_read("rada-constitution.txt"))
        articles = [b for b in blocks if b.block_type == "article"]
        assert len(articles) >= 100, f"Expected 100+ articles, got {len(articles)}"

    def test_constitution_has_chapters(self):
        blocks = self.parser.parse_text(_read("rada-constitution.txt"))
        chapters = [b for b in blocks if b.block_type == "chapter"]
        assert len(chapters) >= 10, f"Expected 10+ chapters, got {len(chapters)}"

    def test_constitution_has_preamble(self):
        blocks = self.parser.parse_text(_read("rada-constitution.txt"))
        preambles = [b for b in blocks if b.block_type == "preamble"]
        assert len(preambles) >= 1

    def test_article_id_format(self):
        blocks = self.parser.parse_text(_read("rada-constitution.txt"))
        articles = [b for b in blocks if b.block_type == "article"]
        first = articles[0]
        assert first.id.startswith("st"), f"Article id should start with 'st', got {first.id}"

    def test_first_article_has_paragraphs(self):
        blocks = self.parser.parse_text(_read("rada-constitution.txt"))
        articles = [b for b in blocks if b.block_type == "article"]
        first = articles[0]
        assert len(first.versions) == 1
        assert len(first.versions[0].paragraphs) >= 1

    def test_article_heading_is_articulo_class(self):
        blocks = self.parser.parse_text(_read("rada-constitution.txt"))
        articles = [b for b in blocks if b.block_type == "article"]
        first_para = articles[0].versions[0].paragraphs[0]
        assert first_para.css_class == "articulo"

    def test_simple_law_articles(self):
        blocks = self.parser.parse_text(_read("rada-1103-16-law.txt"))
        articles = [b for b in blocks if b.block_type == "article"]
        assert len(articles) >= 15, f"Expected 15+ articles, got {len(articles)}"

    def test_simple_law_has_chapters(self):
        blocks = self.parser.parse_text(_read("rada-1103-16-law.txt"))
        chapters = [b for b in blocks if b.block_type == "chapter"]
        assert len(chapters) >= 3

    def test_annotations_excluded_from_body(self):
        """Editorial annotations {in braces} should not appear in article body."""
        blocks = self.parser.parse_text(_read("rada-constitution.txt"))
        for block in blocks:
            if block.block_type != "article":
                continue
            for version in block.versions:
                for para in version.paragraphs:
                    if para.css_class == "parrafo":
                        assert not (para.text.startswith("{") and para.text.endswith("}")), (
                            f"Annotation leaked: {para.text[:60]}"
                        )

    def test_empty_data(self):
        blocks = self.parser.parse_text(b"")
        assert blocks == []

    def test_extract_reforms_empty(self):
        reforms = self.parser.extract_reforms(_read("rada-constitution.txt"))
        assert reforms == []


# ─── Metadata Parser ───


class TestRadaMetadataParser:
    """Test metadata extraction from .xml (HTML with <meta> tags)."""

    parser = RadaMetadataParser()

    def test_constitution_title(self):
        meta = self.parser.parse(_read("rada-constitution.xml"), "254к/96-ВР")
        assert "Конституція" in meta.title

    def test_constitution_status(self):
        meta = self.parser.parse(_read("rada-constitution.xml"), "254к/96-ВР")
        assert meta.status == NormStatus.IN_FORCE

    def test_constitution_rank(self):
        meta = self.parser.parse(_read("rada-constitution.xml"), "254к/96-ВР")
        assert meta.rank == "konstytutsiia"

    def test_constitution_publication_date(self):
        meta = self.parser.parse(_read("rada-constitution.xml"), "254к/96-ВР")
        assert meta.publication_date == date(1996, 6, 28)

    def test_constitution_department(self):
        meta = self.parser.parse(_read("rada-constitution.xml"), "254к/96-ВР")
        assert "Верховна Рада" in meta.department

    def test_constitution_identifier(self):
        meta = self.parser.parse(_read("rada-constitution.xml"), "254к/96-ВР")
        assert meta.identifier == "254к-96-вр"

    def test_constitution_country(self):
        meta = self.parser.parse(_read("rada-constitution.xml"), "254к/96-ВР")
        assert meta.country == "ua"

    def test_constitution_source_url(self):
        meta = self.parser.parse(_read("rada-constitution.xml"), "254к/96-ВР")
        assert meta.source == "https://zakon.rada.gov.ua/laws/show/254к/96-ВР"

    def test_simple_law_title(self):
        meta = self.parser.parse(_read("rada-1103-16-law.xml"), "1103-16")
        assert "біобезпеки" in meta.title

    def test_simple_law_rank(self):
        meta = self.parser.parse(_read("rada-1103-16-law.xml"), "1103-16")
        assert meta.rank == "zakon"

    def test_simple_law_date(self):
        meta = self.parser.parse(_read("rada-1103-16-law.xml"), "1103-16")
        assert meta.publication_date == date(2007, 5, 31)

    def test_identifier_filesystem_safe(self):
        meta = self.parser.parse(_read("rada-constitution.xml"), "254к/96-ВР")
        # No slashes, no spaces, no colons
        assert "/" not in meta.identifier
        assert " " not in meta.identifier
        assert ":" not in meta.identifier

    def test_official_number_in_extra(self):
        meta = self.parser.parse(_read("rada-constitution.xml"), "254к/96-ВР")
        extra_dict = dict(meta.extra)
        assert "official_number" in extra_dict
        assert "254к/96-ВР" in extra_dict["official_number"]


# ─── Discovery ───


class TestDiscovery:
    """Test discovery list parsing and nreg conversion."""

    def test_parse_discovery_list_cp1251(self):
        data = _read("perv1-sample.txt")
        nregs = list(parse_discovery_list(data))
        assert len(nregs) > 0
        # Verify they look like valid nregs
        for nreg in nregs:
            assert len(nreg) > 0
            assert "\n" not in nreg

    def test_parse_type_list_utf8(self):
        data = b"4818-20\n4817-20\n4820-20\n"
        nregs = list(parse_type_list(data))
        assert nregs == ["4818-20", "4817-20", "4820-20"]

    def test_parse_type_list_with_empty_lines(self):
        data = "254к/96-ВР\n\n888-09\n".encode("utf-8")
        nregs = list(parse_type_list(data))
        assert nregs == ["254к/96-ВР", "888-09"]

    def test_parse_type_list_cyrillic_nregs(self):
        data = "184-2026-р\n1389-2025-р\n".encode("utf-8")
        nregs = list(parse_type_list(data))
        assert len(nregs) == 2
        assert nregs[0] == "184-2026-р"

    def test_nreg_to_identifier_simple(self):
        assert nreg_to_identifier("2341-14") == "2341-14"

    def test_nreg_to_identifier_cyrillic(self):
        assert nreg_to_identifier("254к/96-ВР") == "254к-96-вр"

    def test_nreg_to_identifier_presidential(self):
        assert nreg_to_identifier("64/2022") == "64-2022"

    def test_nreg_to_identifier_cmu_resolution(self):
        assert nreg_to_identifier("184-2026-р") == "184-2026-р"

    def test_discovery_create_with_config(self):
        source = {
            "type_lists": ["t1", "t21"],
            "include_perv1": False,
        }
        disc = RadaDiscovery.create(source)
        assert disc._type_lists == ["t1", "t21"]
        assert disc._include_perv1 is False

    def test_discovery_create_defaults(self):
        disc = RadaDiscovery.create({})
        assert disc._type_lists == ["t1", "t21", "t216"]
        assert disc._include_perv1 is True


# ─── Countries dispatch ───


class TestCountriesDispatchUA:
    """Test that UA is properly registered in the countries module."""

    def test_get_text_parser(self):
        parser = get_text_parser("ua")
        assert isinstance(parser, RadaTextParser)

    def test_get_metadata_parser(self):
        parser = get_metadata_parser("ua")
        assert isinstance(parser, RadaMetadataParser)


# ─── Slug / filepath ───


class TestSlugUkraine:
    """Test filepath generation for Ukrainian norms."""

    def test_filepath_cyrillic(self):
        meta = RadaMetadataParser().parse(_read("rada-constitution.xml"), "254к/96-ВР")
        path = norm_to_filepath(meta)
        assert path == "ua/254к-96-вр.md"

    def test_filepath_ascii(self):
        meta = RadaMetadataParser().parse(_read("rada-1103-16-law.xml"), "1103-16")
        path = norm_to_filepath(meta)
        assert path == "ua/1103-16.md"


# ─── End-to-end Markdown rendering ───


class TestMarkdownRendering:
    """Test full markdown output (frontmatter + content)."""

    def test_render_constitution(self):
        text_parser = RadaTextParser()
        meta_parser = RadaMetadataParser()

        blocks = text_parser.parse_text(_read("rada-constitution.txt"))
        meta = meta_parser.parse(_read("rada-constitution.xml"), "254к/96-ВР")

        md = render_norm_at_date(meta, blocks, meta.publication_date, include_all=True)

        assert md.startswith("---\n")
        assert 'title: "Конституція України"' in md
        assert 'country: "ua"' in md
        assert 'rank: "konstytutsiia"' in md
        assert "##### Стаття 1" in md

    def test_render_simple_law(self):
        text_parser = RadaTextParser()
        meta_parser = RadaMetadataParser()

        blocks = text_parser.parse_text(_read("rada-1103-16-law.txt"))
        meta = meta_parser.parse(_read("rada-1103-16-law.xml"), "1103-16")

        md = render_norm_at_date(meta, blocks, meta.publication_date, include_all=True)

        assert md.startswith("---\n")
        assert 'country: "ua"' in md
        assert "##### Стаття 1" in md
        assert "## Розділ" in md
