"""Tests for the Chinese National Database of Laws and Regulations parser.

Fixtures are official JSON documents from flk.npc.gov.cn:
  - sample-constitution.json: Constitution of the PRC (2018 amendment)
  - sample-code.json: Civil Code of the PRC (1,260 articles across 7 books)
  - sample-ordinary-law.json: Criminal Law of the PRC (with amendment history)
  - sample-regulation.json: Housing Provident Fund Management Regulation
  - sample-with-tables.json: Individual Income Tax Law (tax bracket tables)
"""

from datetime import date
from pathlib import Path

import pytest

from legalize.fetcher.cn.parser import CNMetadataParser, CNTextParser
from legalize.models import NormStatus, Rank

FIXTURES = Path(__file__).parent / "fixtures" / "cn"


@pytest.fixture
def text_parser():
    return CNTextParser()


@pytest.fixture
def meta_parser():
    return CNMetadataParser()


# ─── Constitution (中华人民共和国宪法) ───


class TestConstitution:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = (FIXTURES / "sample-constitution.json").read_bytes()

    def test_metadata(self, meta_parser):
        meta = meta_parser.parse(self.data, "2c909fdd678bf17901678bf5a483004b")
        assert "宪法" in meta.title
        assert meta.identifier == "2c909fdd678bf17901678bf5a483004b"
        assert meta.country == "cn"
        assert meta.rank == Rank.CONSTITUCION
        assert meta.status == NormStatus.IN_FORCE
        assert "全国人民代表大会" in meta.department
        assert "flk.npc.gov.cn" in meta.source

    def test_parse_produces_blocks(self, text_parser):
        blocks = text_parser.parse_text(self.data)
        assert len(blocks) >= 50, f"Expected >=50 blocks, got {len(blocks)}"

    def test_chapters_and_articles(self, text_parser):
        blocks = text_parser.parse_text(self.data)
        chapters = [b for b in blocks if b.block_type == "capitulo"]
        assert len(chapters) >= 4, f"Expected >=4 chapters, got {len(chapters)}"
        articles = [b for b in blocks if b.block_type == "articulo"]
        assert len(articles) >= 100, f"Expected >=100 articles, got {len(articles)}"


# ─── Civil Code (中华人民共和国民法典) ───


class TestCivilCode:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = (FIXTURES / "sample-code.json").read_bytes()

    def test_metadata(self, meta_parser):
        meta = meta_parser.parse(self.data, "ff808081729d1efe01729d50b5c500bf")
        assert meta.title == "中华人民共和国民法典"
        assert meta.identifier == "ff808081729d1efe01729d50b5c500bf"
        assert meta.country == "cn"
        assert meta.rank == Rank.LEY
        assert meta.publication_date == date(2020, 5, 28)
        assert meta.department == "全国人民代表大会"

    def test_books_and_chapters(self, text_parser):
        blocks = text_parser.parse_text(self.data)
        books = [b for b in blocks if b.block_type == "libro"]
        assert len(books) == 7, f"Civil Code should have 7 books, got {len(books)}"

        # Check First Book Title
        assert "第一编" in books[0].title
        assert "总则" in books[0].title

    def test_articles_count(self, text_parser):
        blocks = text_parser.parse_text(self.data)
        articles = [b for b in blocks if b.block_type == "articulo"]
        assert len(articles) >= 1000, f"Expected >=1000 articles, got {len(articles)}"


# ─── Criminal Law (中华人民共和国刑法) ───


class TestCriminalLaw:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = (FIXTURES / "sample-ordinary-law.json").read_bytes()

    def test_metadata(self, meta_parser):
        meta = meta_parser.parse(self.data, "ff808181796a636a0179822a19640c92")
        assert meta.title == "中华人民共和国刑法"
        assert meta.country == "cn"
        assert meta.rank == Rank.LEY
        assert meta.publication_date == date(2020, 12, 26)

    def test_reforms_extracted(self, text_parser):
        reforms = text_parser.extract_reforms(self.data)
        assert len(reforms) >= 2, f"Expected >=2 historical reforms, got {len(reforms)}"
        # Verify chronological order
        assert reforms[0].date <= reforms[1].date
        assert reforms[0].date == date(2009, 8, 27)
        assert reforms[1].date == date(2020, 12, 26)


# ─── Administrative Regulation (住房公积金管理条例) ───


class TestRegulation:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = (FIXTURES / "sample-regulation.json").read_bytes()

    def test_metadata(self, meta_parser):
        meta = meta_parser.parse(self.data, "ff8081819ff54a6401a01df735565134")
        assert meta.title == "住房公积金管理条例"
        assert meta.country == "cn"
        assert meta.rank == Rank.REAL_DECRETO
        assert meta.department == "国务院"

    def test_blocks_present(self, text_parser):
        blocks = text_parser.parse_text(self.data)
        assert len(blocks) >= 1


# ─── Tax Law with Tables (中华人民共和国个人所得税法) ───


class TestTaxLawWithTables:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = (FIXTURES / "sample-with-tables.json").read_bytes()

    def test_metadata(self, meta_parser):
        meta = meta_parser.parse(self.data, "2c909fdd678bf17901678bf724bd0609")
        assert "个人所得税法" in meta.title
        assert meta.country == "cn"
        assert meta.rank == Rank.LEY
        assert meta.publication_date == date(2018, 8, 31)

    def test_blocks_and_structure(self, text_parser):
        blocks = text_parser.parse_text(self.data)
        assert len(blocks) >= 1
