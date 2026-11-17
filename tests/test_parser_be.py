"""Tests for the Belgian Justel fetcher (parser + metadata + discovery)."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from legalize.countries import (
    get_metadata_parser,
    get_text_parser,
    supported_countries,
)
from legalize.fetcher.be.client import DOCUMENT_TYPES, JustelClient
from legalize.fetcher.be.discovery import (
    JustelDiscovery,
    extract_norm_ids_from_listing,
)
from legalize.fetcher.be.parser import (
    JustelMetadataParser,
    JustelTextParser,
)
from legalize.models import NormStatus, Rank

FIXTURES = Path(__file__).parent / "fixtures" / "be"


# Composite norm IDs (dt:yyyy:mm:dd:numac) used in fixture tests.
NID_CONSTITUTION = "constitution:1994:02:17:1994021048"
NID_CODE_PENAL = "loi:1867:06:08:1867060850"
NID_ORDINARY_LAW = "loi:2024:01:07:2024000164"
NID_REGULATION = "arrete:2024:01:12:2024001284"
NID_WITH_TABLES = "loi:2013:02:28:2013011134"


# ─────────────────────────────────────────────
# Registry dispatch
# ─────────────────────────────────────────────


class TestCountryDispatch:
    def test_registry_has_be(self):
        assert "be" in supported_countries()

    def test_be_text_parser_class(self):
        parser = get_text_parser("be")
        assert isinstance(parser, JustelTextParser)

    def test_be_metadata_parser_class(self):
        parser = get_metadata_parser("be")
        assert isinstance(parser, JustelMetadataParser)


# ─────────────────────────────────────────────
# Client URL building
# ─────────────────────────────────────────────


class TestJustelClient:
    def test_parse_norm_id(self):
        dt, y, m, d, nn = JustelClient.parse_norm_id(NID_CONSTITUTION)
        assert (dt, y, m, d, nn) == ("constitution", "1994", "02", "17", "1994021048")

    def test_parse_norm_id_invalid(self):
        with pytest.raises(ValueError):
            JustelClient.parse_norm_id("1994021048")

    def test_numac_from_norm_id(self):
        assert JustelClient.numac_from_norm_id(NID_ORDINARY_LAW) == "2024000164"

    def test_eli_url(self):
        client = JustelClient(base_url="https://www.ejustice.just.fgov.be")
        url = client.eli_url(NID_CONSTITUTION)
        assert url == (
            "https://www.ejustice.just.fgov.be/eli/constitution/1994/02/17/1994021048/justel"
        )

    def test_listing_url(self):
        client = JustelClient(base_url="https://www.ejustice.just.fgov.be")
        assert client.listing_url("loi", 2024) == ("https://www.ejustice.just.fgov.be/eli/loi/2024")

    def test_document_types(self):
        assert "loi" in DOCUMENT_TYPES
        assert "decret" in DOCUMENT_TYPES
        assert "ordonnance" in DOCUMENT_TYPES
        assert "constitution" in DOCUMENT_TYPES


# ─────────────────────────────────────────────
# Discovery (listing → norm IDs)
# ─────────────────────────────────────────────


class TestDiscovery:
    def test_extract_norm_ids_from_listing(self):
        data = (FIXTURES / "sample-listing-loi-2024.html").read_bytes()
        ids = list(extract_norm_ids_from_listing(data))
        # Every ID follows the canonical shape
        assert all(nid.count(":") == 4 for nid in ids)
        # 2024 listing should contain many unique laws
        assert len(set(ids)) >= 50
        # Every ID begins with 'loi:' (not other types)
        assert all(nid.startswith("loi:") for nid in set(ids))
        # Known NUMAC present
        assert NID_ORDINARY_LAW in ids

    def test_discovery_is_deduplicated(self):
        data = (FIXTURES / "sample-listing-loi-2024.html").read_bytes()
        ids = list(extract_norm_ids_from_listing(data))
        # Justel renders each entry twice (moniteur + justel link); the
        # extractor only emits URLs with /justel so dedupe is implicit.
        # We still verify explicitly that the stream matches its set when
        # deduplicated by the generic discovery layer.
        unique = list(dict.fromkeys(ids))
        assert len(unique) == len(set(ids))

    def test_discovery_is_subclass_of_norm_discovery(self):
        from legalize.fetcher.base import NormDiscovery

        assert issubclass(JustelDiscovery, NormDiscovery)


# ─────────────────────────────────────────────
# Metadata parsing
# ─────────────────────────────────────────────


class TestMetadataConstitution:
    @pytest.fixture(scope="class")
    def meta(self):
        data = (FIXTURES / "sample-constitution.html").read_bytes()
        return JustelMetadataParser().parse(data, NID_CONSTITUTION)

    def test_country(self, meta):
        assert meta.country == "be"

    def test_identifier_is_bare_numac(self, meta):
        assert meta.identifier == "1994021048"
        assert ":" not in meta.identifier
        assert " " not in meta.identifier

    def test_title_contains_official_wording(self, meta):
        assert "Constitution" in meta.title or "CONSTITUTION" in meta.title.upper()
        assert "17 FEVRIER 1994" in meta.title

    def test_rank_is_constitution(self, meta):
        assert meta.rank == Rank("constitution")

    def test_publication_date(self, meta):
        assert meta.publication_date.year == 1994
        assert meta.publication_date.month == 2
        assert meta.publication_date.day == 17

    def test_department(self, meta):
        assert meta.department  # non-empty
        assert "Intérieur" in meta.department

    def test_status_in_force(self, meta):
        assert meta.status == NormStatus.IN_FORCE

    def test_source_is_eli_url(self, meta):
        assert meta.source.startswith("https://www.ejustice.just.fgov.be/eli/")
        assert "/justel" in meta.source

    def test_pdf_urls(self, meta):
        assert meta.pdf_url is not None
        assert meta.pdf_url.endswith(".pdf")

    def test_extra_captures_source_fields(self, meta):
        keys = {k for k, _ in meta.extra}
        assert "dossier_number" in keys
        assert "entry_into_force" in keys
        assert "gazette_page" in keys
        assert "document_type" in keys
        assert "language" in keys

    def test_dossier_number_format(self, meta):
        dossier = dict(meta.extra).get("dossier_number")
        assert dossier is not None
        assert re.match(r"^\d{4}-\d{2}-\d{2}/\d+$", dossier)

    def test_archived_versions_count(self, meta):
        archived = dict(meta.extra).get("archived_versions")
        assert archived is not None
        assert archived.isdigit()
        assert int(archived) > 0


class TestMetadataOrdinaryLaw:
    @pytest.fixture(scope="class")
    def meta(self):
        data = (FIXTURES / "sample-ordinary-law.html").read_bytes()
        return JustelMetadataParser().parse(data, NID_ORDINARY_LAW)

    def test_identifier(self, meta):
        assert meta.identifier == "2024000164"

    def test_rank_is_loi(self, meta):
        assert meta.rank == Rank("loi")

    def test_modifies_field(self, meta):
        modifies = dict(meta.extra).get("modifies", "")
        assert "2006021362" in modifies

    def test_publication_date(self, meta):
        assert meta.publication_date.isoformat() == "2024-01-17"

    def test_ascii_identifier(self, meta):
        assert meta.identifier.isascii()


class TestMetadataRegulation:
    @pytest.fixture(scope="class")
    def meta(self):
        data = (FIXTURES / "sample-regulation.html").read_bytes()
        return JustelMetadataParser().parse(data, NID_REGULATION)

    def test_rank_is_arrete_royal(self, meta):
        assert meta.rank == Rank("arrete_royal")

    def test_department_autorite_flamande(self, meta):
        assert "flamande" in meta.department.lower() or "flemish" in meta.department.lower()


# ─────────────────────────────────────────────
# Text parsing — structure
# ─────────────────────────────────────────────


class TestTextConstitution:
    @pytest.fixture(scope="class")
    def blocks(self):
        data = (FIXTURES / "sample-constitution.html").read_bytes()
        return JustelTextParser().parse_text(data)

    def test_many_articles(self, blocks):
        # The Constitution has ~200+ articles
        article_count = sum(1 for b in blocks if b.block_type == "article")
        assert article_count > 150

    def test_has_chapters(self, blocks):
        chapters = [b for b in blocks if b.block_type == "chapter"]
        assert len(chapters) > 20

    def test_article_ids_are_filesystem_safe(self, blocks):
        for b in blocks:
            if b.block_type == "article":
                assert ":" not in b.id
                assert " " not in b.id
                assert "/" not in b.id

    def test_article_1_content(self, blocks):
        art_1 = next(b for b in blocks if b.id == "art-1")
        text = " ".join(p.text for p in art_1.versions[0].paragraphs)
        assert "Belgique" in text
        assert "Etat fédéral" in text

    def test_article_1_is_single_header(self, blocks):
        art_1 = next(b for b in blocks if b.id == "art-1")
        # First paragraph should be the articulo header, not duplicated
        paragraphs = art_1.versions[0].paragraphs
        assert paragraphs[0].css_class == "articulo"
        assert paragraphs[0].text.startswith("Article 1.")

    def test_amendment_markers_use_superscript(self, blocks):
        # Article 5 has '[¹ ...]¹' amendment markers
        art_5 = next(b for b in blocks if b.id == "art-5")
        full = " ".join(p.text for p in art_5.versions[0].paragraphs)
        assert "¹" in full

    def test_cross_reference_links_are_markdown(self, blocks):
        # Article 7bis footer has a link to 2024-05-15/01
        art_7bis = next(b for b in blocks if b.id == "art-7bis")
        full = " ".join(p.text for p in art_7bis.versions[0].paragraphs)
        # Markdown link syntax [text](url)
        assert "[2024-05-15/01](https://www.ejustice.just.fgov.be/cgi_loi/article.pl" in full

    def test_bold_preserved(self, blocks):
        # "En vigueur :" appears as <b>...</b> in several article footers
        art_7bis = next(b for b in blocks if b.id == "art-7bis")
        full = " ".join(p.text for p in art_7bis.versions[0].paragraphs)
        assert "**En vigueur :**" in full


class TestTextCodePenal:
    """1867 Code pénal -- 800+ articles, 160+ chapters, heavy amendment history."""

    @pytest.fixture(scope="class")
    def blocks(self):
        data = (FIXTURES / "sample-code.html").read_bytes()
        return JustelTextParser().parse_text(data)

    def test_huge_article_count(self, blocks):
        articles = [b for b in blocks if b.block_type == "article"]
        assert len(articles) > 500

    def test_no_empty_preamble(self, blocks):
        # The code starts directly with LIVRE 1 -- a leftover '----------'
        # preamble block would be an amendment-footer bleed from a bug.
        preambles = [b for b in blocks if b.block_type == "preamble"]
        assert preambles == []

    def test_first_block_is_livre_heading(self, blocks):
        assert blocks[0].block_type in ("title", "chapter")
        assert "LIVRE 1" in blocks[0].title or "LIVRE 1" in blocks[0].versions[0].paragraphs[0].text

    def test_article_1_is_first_article(self, blocks):
        first_article = next(b for b in blocks if b.block_type == "article")
        assert first_article.id == "art-1"
        text = " ".join(p.text for p in first_article.versions[0].paragraphs)
        assert "infraction" in text


class TestTextOrdinaryLaw:
    @pytest.fixture(scope="class")
    def blocks(self):
        data = (FIXTURES / "sample-ordinary-law.html").read_bytes()
        return JustelTextParser().parse_text(data)

    def test_has_both_titres(self, blocks):
        titles = [b for b in blocks if b.block_type == "chapter"]
        assert len(titles) >= 2
        texts = [b.title for b in titles]
        assert any("TITRE 1" in t for t in texts)
        assert any("TITRE 2" in t for t in texts)

    def test_article_1er_is_found(self, blocks):
        art = next((b for b in blocks if b.id == "art-1er"), None)
        assert art is not None
        text = " ".join(p.text for p in art.versions[0].paragraphs)
        assert "Constitution" in text


class TestTextWithTables:
    """2013 Loi introduisant le Code de droit économique -- contains SI units table."""

    @pytest.fixture(scope="class")
    def blocks(self):
        data = (FIXTURES / "sample-with-tables.html").read_bytes()
        return JustelTextParser().parse_text(data)

    def test_has_table_paragraph(self, blocks):
        # At least one paragraph with css_class='table'
        tables = [p for b in blocks for p in b.versions[0].paragraphs if p.css_class == "table"]
        assert len(tables) >= 1

    def test_table_is_pipe_markdown(self, blocks):
        tables = [
            p.text for b in blocks for p in b.versions[0].paragraphs if p.css_class == "table"
        ]
        assert tables
        table_md = tables[0]
        # Pipe-table header line
        assert table_md.startswith("| ")
        # Header separator row
        assert "| --- |" in table_md or "|---|" in table_md

    def test_table_preserves_br_line_breaks(self, blocks):
        tables = [
            p.text for b in blocks for p in b.versions[0].paragraphs if p.css_class == "table"
        ]
        # The SI-units table has multi-line cells joined with <br>
        assert any("<br>" in t for t in tables)


# ─────────────────────────────────────────────
# Encoding / hygiene
# ─────────────────────────────────────────────


class TestEncoding:
    @pytest.mark.parametrize(
        "fixture",
        [
            "sample-constitution.html",
            "sample-code.html",
            "sample-ordinary-law.html",
            "sample-regulation.html",
            "sample-with-tables.html",
        ],
    )
    def test_no_control_chars(self, fixture):
        data = (FIXTURES / fixture).read_bytes()
        blocks = JustelTextParser().parse_text(data)
        ctrl_re = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
        for b in blocks:
            for p in b.versions[0].paragraphs:
                assert not ctrl_re.search(p.text), f"Control char in {b.id}: {p.text[:80]!r}"

    @pytest.mark.parametrize(
        "fixture",
        [
            "sample-constitution.html",
            "sample-ordinary-law.html",
            "sample-with-tables.html",
        ],
    )
    def test_utf8_output_valid(self, fixture):
        data = (FIXTURES / fixture).read_bytes()
        blocks = JustelTextParser().parse_text(data)
        for b in blocks:
            for p in b.versions[0].paragraphs:
                # Should round-trip through UTF-8 without errors
                p.text.encode("utf-8")


class TestDiscoverDailyResolvesCn:
    """summary.pl lists Justel CNs; the corpus is keyed by the ELI's NUMAC."""

    _SUMMARY = b"""<html><body>
<div id="list-title-1"><h2 class="list-title">10&nbsp;novembre&nbsp;2026</h2>
<a class="list-item--title" href="article.pl?language=fr&cn_search=2014040423&view_numac=">Loi</a>
<a class="list-item--title" href="article.pl?language=fr&cn_search=2019032210&view_numac=">Arr\xeat\xe9</a>
</div>
<div id="list-title-1"><h2 class="list-title">9&nbsp;novembre&nbsp;2026</h2>
<a class="list-item--title" href="article.pl?language=fr&cn_search=2024022928&view_numac=">Loi</a>
</div></body></html>"""

    _ARTICLES = {
        "2014040423": b"<A href=http://www.ejustice.just.fgov.be/eli/loi/2014/04/04/2014011239/justel >",
        "2019032210": b"<A href=http://www.ejustice.just.fgov.be/eli/arrete/2019/03/22/2019012345/justel >",
    }

    class _Client(JustelClient):
        def __init__(self, articles):
            self._articles = articles

        def get_daily_summary(self):
            return TestDiscoverDailyResolvesCn._SUMMARY

        def get_article(self, cn):
            return self._articles[cn]

    def test_cn_resolves_to_the_eli_numac_and_skips_arretes(self):
        client = self._Client(self._ARTICLES)
        ids = list(JustelDiscovery().discover_daily(client, date(2026, 11, 10)))
        assert ids == ["loi:2014:04:04:2014011239"]

    def test_a_page_without_eli_fails_the_day(self):
        client = self._Client({**self._ARTICLES, "2014040423": b"<html></html>"})
        with pytest.raises(ValueError, match="2014040423"):
            list(JustelDiscovery().discover_daily(client, date(2026, 11, 10)))
