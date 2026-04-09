"""Tests for the Italian Normattiva parser."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path


from legalize.countries import get_metadata_parser, get_text_parser
from legalize.fetcher.it.parser import (
    NormattivaMetadataParser,
    NormattivaTextParser,
    _clean,
    _extract_ascii_table,
    _parse_vigenza_date,
)

FIXTURES = Path(__file__).parent / "fixtures" / "it"

CONSTITUTION = FIXTURES / "sample-constitution.json"
ORDINARY_LAW = FIXTURES / "sample-ordinary-law.json"
REGULATION = FIXTURES / "sample-regulation.json"
WITH_TABLES = FIXTURES / "sample-with-tables.json"
CODE = FIXTURES / "sample-code.json"


# ─────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────


class TestRegistry:
    def test_text_parser_registered(self):
        parser = get_text_parser("it")
        assert isinstance(parser, NormattivaTextParser)

    def test_metadata_parser_registered(self):
        parser = get_metadata_parser("it")
        assert isinstance(parser, NormattivaMetadataParser)


# ─────────────────────────────────────────────
# Text cleaning
# ─────────────────────────────────────────────


class TestClean:
    def test_html_entities(self):
        assert _clean("L&rsquo;Italia &egrave; bella") == "L\u2019Italia è bella"

    def test_control_chars(self):
        assert _clean("abc\x00\x01\x0edef") == "abcdef"

    def test_nbsp(self):
        assert _clean("a\xa0b") == "a b"

    def test_whitespace_normalization(self):
        assert _clean("  a   b  \n  c  ") == "a b c"


# ─────────────────────────────────────────────
# Vigenza date parsing
# ─────────────────────────────────────────────


class TestVigenzaDate:
    def test_valid(self):
        assert _parse_vigenza_date("19900902") == date(1990, 9, 2)

    def test_current(self):
        assert _parse_vigenza_date("99999999") is None

    def test_zero(self):
        assert _parse_vigenza_date("0") is None

    def test_empty(self):
        assert _parse_vigenza_date("") is None


# ─────────────────────────────────────────────
# Text parser — Constitution
# ─────────────────────────────────────────────


class TestConstitutionText:
    def setup_method(self):
        self.parser = NormattivaTextParser()
        self.blocks = self.parser.parse_text(CONSTITUTION.read_bytes())

    def test_has_blocks(self):
        assert len(self.blocks) > 0

    def test_first_block_is_article(self):
        assert self.blocks[0].block_type == "article"

    def test_article_number_parsed(self):
        paras = self.blocks[0].versions[0].paragraphs
        art_paras = [p for p in paras if p.css_class == "articulo"]
        assert len(art_paras) >= 1
        assert "Art. 1" in art_paras[0].text

    def test_text_content(self):
        all_text = " ".join(p.text for b in self.blocks for v in b.versions for p in v.paragraphs)
        assert "Repubblica democratica" in all_text

    def test_no_html_entities(self):
        for b in self.blocks:
            for v in b.versions:
                for p in v.paragraphs:
                    assert "&egrave;" not in p.text
                    assert "&agrave;" not in p.text
                    assert "&#" not in p.text


# ─────────────────────────────────────────────
# Text parser — Ordinary law (Legge 241/1990)
# ─────────────────────────────────────────────


class TestOrdinaryLawText:
    def setup_method(self):
        self.parser = NormattivaTextParser()
        self.blocks = self.parser.parse_text(ORDINARY_LAW.read_bytes())

    def test_has_blocks(self):
        assert len(self.blocks) >= 1

    def test_preamble_preserved(self):
        paras = self.blocks[0].versions[0].paragraphs
        texts = [p.text for p in paras]
        assert any("Camera dei deputati" in t for t in texts)

    def test_firma_rey(self):
        paras = self.blocks[0].versions[0].paragraphs
        firma = [p for p in paras if p.css_class == "firma_rey"]
        assert len(firma) >= 1
        assert any("PRESIDENTE DELLA REPUBBLICA" in p.text for p in firma)

    def test_article_heading(self):
        paras = self.blocks[0].versions[0].paragraphs
        sections = [p for p in paras if p.css_class == "seccion"]
        assert len(sections) >= 1
        assert any("Principi generali" in p.text for p in sections)

    def test_comma_numbering_preserved(self):
        paras = self.blocks[0].versions[0].paragraphs
        texts = [p.text for p in paras if p.css_class == "parrafo"]
        assert any(t.startswith("1.") for t in texts)
        assert any(t.startswith("1-bis.") for t in texts)

    def test_no_mojibake(self):
        for b in self.blocks:
            for v in b.versions:
                for p in v.paragraphs:
                    assert "\ufffd" not in p.text
                    assert "\xc3" not in p.text  # UTF-8 mojibake


# ─────────────────────────────────────────────
# Text parser — Regulation (D.Lgs. 152/2006)
# ─────────────────────────────────────────────


class TestRegulationText:
    def setup_method(self):
        self.parser = NormattivaTextParser()
        self.blocks = self.parser.parse_text(REGULATION.read_bytes())

    def test_has_blocks(self):
        assert len(self.blocks) >= 1

    def test_cross_references_as_links(self):
        """Links to other laws should be preserved as Markdown."""
        all_text = " ".join(p.text for b in self.blocks for v in b.versions for p in v.paragraphs)
        assert "](http" in all_text

    def test_has_many_citations(self):
        """D.Lgs. 152/2006 cites many EU directives."""
        paras = self.blocks[0].versions[0].paragraphs
        link_paras = [p for p in paras if "](http" in p.text]
        assert len(link_paras) >= 10


# ─────────────────────────────────────────────
# Text parser — Budget law with ASCII tables
# ─────────────────────────────────────────────


class TestBudgetLawTables:
    def setup_method(self):
        self.parser = NormattivaTextParser()
        self.blocks = self.parser.parse_text(WITH_TABLES.read_bytes())

    def test_has_blocks(self):
        assert len(self.blocks) >= 1

    def test_has_table_paragraph(self):
        """Budget law Art.1 contains an ASCII pipe table."""
        paras = self.blocks[0].versions[0].paragraphs
        pre_paras = [p for p in paras if p.css_class == "pre"]
        assert len(pre_paras) >= 1

    def test_table_has_pipe_format(self):
        paras = self.blocks[0].versions[0].paragraphs
        pre_paras = [p for p in paras if p.css_class == "pre"]
        table_text = pre_paras[0].text
        assert "|" in table_text
        assert "+" in table_text or "=" in table_text

    def test_table_has_many_lines(self):
        paras = self.blocks[0].versions[0].paragraphs
        pre_paras = [p for p in paras if p.css_class == "pre"]
        lines = pre_paras[0].text.split("\n")
        assert len(lines) >= 100  # Budget law tables are huge


# ─────────────────────────────────────────────
# Text parser — Codice Civile
# ─────────────────────────────────────────────


class TestCodiceCivileText:
    def setup_method(self):
        self.parser = NormattivaTextParser()
        self.blocks = self.parser.parse_text(CODE.read_bytes())

    def test_has_blocks(self):
        assert len(self.blocks) >= 1

    def test_historical_preamble(self):
        """Codice Civile has a royal preamble."""
        paras = self.blocks[0].versions[0].paragraphs
        texts = [p.text for p in paras]
        assert any("VITTORIO EMANUELE" in t for t in texts)

    def test_link_to_codice(self):
        """The approval text links to the Codice civile itself."""
        all_text = " ".join(p.text for b in self.blocks for v in b.versions for p in v.paragraphs)
        assert "Codice civile" in all_text


# ─────────────────────────────────────────────
# Metadata parser
# ─────────────────────────────────────────────


class TestMetadataConstitution:
    def setup_method(self):
        self.parser = NormattivaMetadataParser()
        self.meta = self.parser.parse(CONSTITUTION.read_bytes(), "047EC27")

    def test_title(self):
        assert "COSTITUZIONE" in self.meta.title

    def test_country(self):
        assert self.meta.country == "it"

    def test_rank(self):
        assert str(self.meta.rank) == "costituzione"

    def test_publication_date(self):
        assert self.meta.publication_date == date(1947, 12, 27)


class TestMetadataOrdinaryLaw:
    def setup_method(self):
        self.parser = NormattivaMetadataParser()
        self.meta = self.parser.parse(ORDINARY_LAW.read_bytes(), "090G0294")

    def test_title(self):
        assert "241" in self.meta.title

    def test_rank(self):
        assert str(self.meta.rank) == "legge"

    def test_publication_date(self):
        assert self.meta.publication_date == date(1990, 8, 7)

    def test_identifier(self):
        assert self.meta.identifier == "090G0294"

    def test_source_url(self):
        assert "normattiva.it" in self.meta.source

    def test_extra_has_act_type_code(self):
        extra_dict = dict(self.meta.extra)
        assert extra_dict.get("act_type_code") == "PLE"

    def test_extra_has_act_number(self):
        extra_dict = dict(self.meta.extra)
        assert extra_dict.get("act_number") == "241"

    def test_extra_has_gu_date(self):
        extra_dict = dict(self.meta.extra)
        assert extra_dict.get("gu_date") == "1990-08-18"

    def test_extra_has_gu_number(self):
        extra_dict = dict(self.meta.extra)
        assert extra_dict.get("gu_number") == "192"


class TestMetadataRegulation:
    def setup_method(self):
        self.parser = NormattivaMetadataParser()
        self.meta = self.parser.parse(REGULATION.read_bytes(), "006G0171")

    def test_rank(self):
        assert str(self.meta.rank) == "decreto_legislativo"

    def test_publication_date(self):
        assert self.meta.publication_date == date(2006, 4, 3)

    def test_extra_has_supplement(self):
        extra_dict = dict(self.meta.extra)
        assert extra_dict.get("supplement_type") == "SO"


class TestMetadataCodiceCivile:
    def setup_method(self):
        self.parser = NormattivaMetadataParser()
        self.meta = self.parser.parse(CODE.read_bytes(), "042U0262")

    def test_rank(self):
        assert str(self.meta.rank) == "regio_decreto"

    def test_publication_date(self):
        assert self.meta.publication_date == date(1942, 3, 16)


# ─────────────────────────────────────────────
# Reforms
# ─────────────────────────────────────────────


class TestReforms:
    def test_no_reforms_from_single_article(self):
        """A single article snapshot should yield no reforms."""
        parser = NormattivaTextParser()
        reforms = parser.extract_reforms(ORDINARY_LAW.read_bytes())
        assert reforms == []

    def test_reforms_from_multi_version_articles(self):
        """Articles with different vigenza dates should yield reforms."""
        parser = NormattivaTextParser()

        combined = {
            "articles": [
                {
                    "article_num": "1",
                    "html": "<div>text</div>",
                    "vigenza_inizio": "19900902",
                    "vigenza_fine": "20050307",
                },
                {
                    "article_num": "1",
                    "html": "<div>text v2</div>",
                    "vigenza_inizio": "20050308",
                    "vigenza_fine": "99999999",
                },
                {
                    "article_num": "2",
                    "html": "<div>text</div>",
                    "vigenza_inizio": "19900902",
                    "vigenza_fine": "99999999",
                },
            ],
            "codiceRedazionale": "TEST001",
        }
        data = json.dumps(combined).encode("utf-8")
        reforms = parser.extract_reforms(data)

        assert len(reforms) == 1
        assert reforms[0].date == date(2005, 3, 8)
        assert "art1" in reforms[0].affected_blocks

    def test_reforms_multiple_dates(self):
        """Multiple reform dates should be extracted and sorted."""
        parser = NormattivaTextParser()

        combined = {
            "articles": [
                {
                    "article_num": "1",
                    "vigenza_inizio": "19900101",
                    "vigenza_fine": "20000101",
                    "html": "v1",
                },
                {
                    "article_num": "1",
                    "vigenza_inizio": "20000102",
                    "vigenza_fine": "20100101",
                    "html": "v2",
                },
                {
                    "article_num": "1",
                    "vigenza_inizio": "20100102",
                    "vigenza_fine": "99999999",
                    "html": "v3",
                },
                {
                    "article_num": "2",
                    "vigenza_inizio": "19900101",
                    "vigenza_fine": "20050601",
                    "html": "v1",
                },
                {
                    "article_num": "2",
                    "vigenza_inizio": "20050602",
                    "vigenza_fine": "99999999",
                    "html": "v2",
                },
            ],
            "codiceRedazionale": "TEST002",
        }
        data = json.dumps(combined).encode("utf-8")
        reforms = parser.extract_reforms(data)

        assert len(reforms) == 3
        assert reforms[0].date == date(2000, 1, 2)
        assert reforms[1].date == date(2005, 6, 2)
        assert reforms[2].date == date(2010, 1, 2)


# ─────────────────────────────────────────────
# ASCII table extraction
# ─────────────────────────────────────────────


class TestAsciiTable:
    def test_extract_simple_table(self):
        from lxml import html as lxml_html

        html = '<p class="table-akn">| A | B |<br>|---|---|<br>| 1 | 2 |</p>'
        el = lxml_html.fromstring(html)
        result = _extract_ascii_table(el)
        assert "| A | B |" in result
        assert "| 1 | 2 |" in result
