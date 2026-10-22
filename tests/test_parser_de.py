"""Tests for the German GII fetcher (parser, metadata, dispatch, slug)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from legalize.countries import get_metadata_parser, get_text_parser
from legalize.fetcher.de.parser import (
    GIIMetadataParser,
    GIITextParser,
    _infer_rank,
)
from legalize.models import NormMetadata, NormStatus
from legalize.transformer.slug import norm_to_filepath

FIXTURES = Path(__file__).parent / "fixtures"


class TestInferRank:
    def test_gesetz(self):
        assert _infer_rank("Bundesgesetz über X", "") == "bundesgesetz"

    def test_verordnung(self):
        assert _infer_rank("Verordnung über das Register", "GenRegV") == "rechtsverordnung"

    def test_grundgesetz(self):
        assert _infer_rank("Grundgesetz für die Bundesrepublik", "GG") == "grundgesetz"

    def test_grundgesetz_by_abbr(self):
        assert _infer_rank("Some title", "GG") == "grundgesetz"

    def test_bekanntmachung(self):
        assert _infer_rank("Bekanntmachung über X", "") == "bekanntmachung"

    def test_fallback(self):
        assert _infer_rank("Datenschutzgesetz", "DSG") == "bundesgesetz"


class TestGIITextParser:
    def setup_method(self):
        self.parser = GIITextParser()

    def test_parse_has_blocks(self):
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        blocks = self.parser.parse_text(xml)
        assert len(blocks) > 0

    def test_articles_parsed(self):
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        blocks = self.parser.parse_text(xml)
        articles = [b for b in blocks if b.block_type == "article"]
        assert len(articles) == 5

    def test_sections_parsed(self):
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        blocks = self.parser.parse_text(xml)
        sections = [b for b in blocks if b.block_type == "section"]
        assert len(sections) == 2

    def test_section_has_heading_paragraph(self):
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        blocks = self.parser.parse_text(xml)
        sections = [b for b in blocks if b.block_type == "section"]
        heading = sections[0].versions[0].paragraphs[0]
        assert heading.css_class == "titulo"
        assert "Grundrechte" in heading.text

    def test_article_title(self):
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        blocks = self.parser.parse_text(xml)
        articles = [b for b in blocks if b.block_type == "article"]
        art1 = next(a for a in articles if "Art 1" in a.title)
        assert "Art 1" in art1.title

    def test_article_has_heading_paragraph(self):
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        blocks = self.parser.parse_text(xml)
        articles = [b for b in blocks if b.block_type == "article"]
        art1 = next(a for a in articles if "Art 1" in a.title)
        first_para = art1.versions[0].paragraphs[0]
        assert first_para.css_class == "articulo"

    def test_article_has_content(self):
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        blocks = self.parser.parse_text(xml)
        articles = [b for b in blocks if b.block_type == "article"]
        art1 = next(a for a in articles if "Art 1" in a.title)
        assert len(art1.versions[0].paragraphs) >= 4

    def test_paragraph_text(self):
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        blocks = self.parser.parse_text(xml)
        articles = [b for b in blocks if b.block_type == "article"]
        art1 = next(a for a in articles if "Art 1" in a.title)
        content_para = art1.versions[0].paragraphs[1]
        assert "Würde des Menschen" in content_para.text

    def test_extract_reforms(self):
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        reforms = self.parser.extract_reforms(xml)
        assert isinstance(reforms, list)
        assert len(reforms) >= 1
        assert "note" in reforms[0]

    def test_versions_are_dated_by_the_builddate_timestamp(self):
        """The source writes builddate with a time ("20260928220002"). Read
        whole it did not parse, every block was dated the day the pipeline ran,
        and the daily committed 396 laws with no text."""
        xml = b"""<dokumente builddate="20260928220002" doknr="TEST">
        <norm><metadaten><jurabk>T</jurabk></metadaten></norm>
        <norm doknr="T01"><metadaten><jurabk>T</jurabk><enbez>P 1</enbez></metadaten>
        <textdaten><text format="XML"><Content><P>Text.</P></Content></text></textdaten>
        </norm></dokumente>"""
        blocks = self.parser.parse_text(xml)
        assert blocks[0].versions[0].publication_date == date(2026, 9, 28)

    def test_empty_xml(self):
        xml = b"<dokumente><norm><metadaten><jurabk>X</jurabk></metadaten></norm></dokumente>"
        blocks = self.parser.parse_text(xml)
        assert blocks == []

    def test_dl_list_parsed_as_list_items(self):
        """DL/DT/DD inside P produces list_item paragraphs."""
        xml = b"""<dokumente builddate="20250101" doknr="TEST">
        <norm><metadaten><jurabk>T</jurabk></metadaten></norm>
        <norm doknr="T01"><metadaten><jurabk>T</jurabk><enbez>P 1</enbez></metadaten>
        <textdaten><text format="XML"><Content>
          <P>Intro: <DL Font="normal" Type="arabic">
            <DT>1.</DT><DD Font="normal"><LA>first item,</LA></DD>
            <DT>2.</DT><DD Font="normal"><LA>second item.</LA></DD>
          </DL></P>
        </Content></text></textdaten></norm></dokumente>"""
        blocks = self.parser.parse_text(xml)
        paras = blocks[0].versions[0].paragraphs
        classes = [p.css_class for p in paras]
        assert "list_item" in classes
        items = [p for p in paras if p.css_class == "list_item"]
        assert len(items) == 2
        assert "1." in items[0].text
        assert "first item" in items[0].text

    def test_nested_dl_sub_items(self):
        """Nested DL (a, b, c inside 1.) produces sub-item paragraphs."""
        xml = b"""<dokumente builddate="20250101" doknr="TEST">
        <norm><metadaten><jurabk>T</jurabk></metadaten></norm>
        <norm doknr="T01"><metadaten><jurabk>T</jurabk><enbez>P 1</enbez></metadaten>
        <textdaten><text format="XML"><Content>
          <P><DL Type="arabic">
            <DT>1.</DT><DD><LA>main item <DL Type="alpha">
              <DT>a)</DT><DD><LA>sub a,</LA></DD>
              <DT>b)</DT><DD><LA>sub b.</LA></DD>
            </DL></LA></DD>
          </DL></P>
        </Content></text></textdaten></norm></dokumente>"""
        blocks = self.parser.parse_text(xml)
        items = [p for p in blocks[0].versions[0].paragraphs if p.css_class == "list_item"]
        assert len(items) == 3  # 1. + a) + b)
        assert "a)" in items[1].text
        assert "b)" in items[2].text

    def test_inline_sp_italic(self):
        """SP tags render as italic markdown."""
        xml = b"""<dokumente builddate="20250101" doknr="TEST">
        <norm><metadaten><jurabk>T</jurabk></metadaten></norm>
        <norm doknr="T01"><metadaten><jurabk>T</jurabk><enbez>P 1</enbez></metadaten>
        <textdaten><text format="XML"><Content>
          <P>Text with <SP>emphasis</SP> here.</P>
        </Content></text></textdaten></norm></dokumente>"""
        blocks = self.parser.parse_text(xml)
        paras = [p for p in blocks[0].versions[0].paragraphs if p.css_class == "abs"]
        assert any("*emphasis*" in p.text for p in paras)

    def test_inline_bold(self):
        """B tags render as bold markdown."""
        xml = b"""<dokumente builddate="20250101" doknr="TEST">
        <norm><metadaten><jurabk>T</jurabk></metadaten></norm>
        <norm doknr="T01"><metadaten><jurabk>T</jurabk><enbez>P 1</enbez></metadaten>
        <textdaten><text format="XML"><Content>
          <P>Text with <B>bold</B> word.</P>
        </Content></text></textdaten></norm></dokumente>"""
        blocks = self.parser.parse_text(xml)
        paras = [p for p in blocks[0].versions[0].paragraphs if p.css_class == "abs"]
        assert any("**bold**" in p.text for p in paras)


class TestGIIMetadataParser:
    def setup_method(self):
        self.parser = GIIMetadataParser()

    def test_parse_metadata(self):
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        meta = self.parser.parse(xml, "gg")
        assert isinstance(meta, NormMetadata)
        assert meta.country == "de"

    def test_identifier(self):
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        meta = self.parser.parse(xml, "gg")
        assert meta.identifier == "GG"

    def test_title(self):
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        meta = self.parser.parse(xml, "gg")
        assert "Grundgesetz" in meta.title

    def test_short_title(self):
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        meta = self.parser.parse(xml, "gg")
        assert meta.short_title == "GG"

    def test_publication_date(self):
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        meta = self.parser.parse(xml, "gg")
        assert meta.publication_date == date(1949, 5, 23)

    def test_rank_is_grundgesetz(self):
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        meta = self.parser.parse(xml, "gg")
        assert str(meta.rank) == "grundgesetz"

    def test_bgbl_reference(self):
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        meta = self.parser.parse(xml, "gg")
        extra = dict(meta.extra)
        assert "BGBl" in extra["bgbl_reference"]

    def test_source_url(self):
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        meta = self.parser.parse(xml, "gg")
        assert "gesetze-im-internet.de/gg/" in meta.source

    def test_extra_has_doknr(self):
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        meta = self.parser.parse(xml, "gg")
        extra = dict(meta.extra)
        assert "doknr" in extra
        assert extra["doknr"].startswith("BJNR")

    def test_extra_has_slug(self):
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        meta = self.parser.parse(xml, "gg")
        extra = dict(meta.extra)
        assert extra["slug"] == "gg"

    def test_extra_has_stand(self):
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        meta = self.parser.parse(xml, "gg")
        extra = dict(meta.extra)
        assert "stand" in extra
        assert "geändert" in extra["stand"]

    def test_enriched_metadata_amtabk(self):
        """amtabk (official abbreviation) is extracted when different from jurabk."""
        xml = b"""<dokumente doknr="BJNR001950896">
        <norm><metadaten>
          <jurabk>BGB</jurabk>
          <amtabk>BGB</amtabk>
          <ausfertigung-datum>1896-08-18</ausfertigung-datum>
          <fundstelle><periodikum>RGBl</periodikum><zitstelle>1896, 195</zitstelle></fundstelle>
          <langue>Buergerliches Gesetzbuch</langue>
        </metadaten></norm></dokumente>"""
        meta = self.parser.parse(xml, "bgb")
        extra = dict(meta.extra)
        # amtabk == jurabk, so it should NOT appear (no duplication)
        assert "amtabk" not in extra

    def test_enriched_metadata_neufassung(self):
        """Neufassung (recast) standangabe is extracted."""
        xml = b"""<dokumente doknr="BJNR001270871">
        <norm><metadaten>
          <jurabk>StGB</jurabk>
          <ausfertigung-datum>1871-05-15</ausfertigung-datum>
          <fundstelle><periodikum>RGBl</periodikum><zitstelle>1871, 127</zitstelle></fundstelle>
          <langue>Strafgesetzbuch</langue>
          <standangabe><standtyp>Neuf</standtyp>
            <standkommentar>Neugefasst durch Bek. v. 13.11.1998 I 3322;</standkommentar>
          </standangabe>
          <standangabe><standtyp>Stand</standtyp>
            <standkommentar>zuletzt geaendert</standkommentar>
          </standangabe>
        </metadaten></norm></dokumente>"""
        meta = self.parser.parse(xml, "stgb")
        extra = dict(meta.extra)
        assert extra["neufassung"] == "Neugefasst durch Bek. v. 13.11.1998 I 3322;"
        assert extra["stand"] == "zuletzt geaendert"

    def test_enriched_metadata_hinweis(self):
        """Hinweis (pending amendment) standangabe is extracted."""
        xml = b"""<dokumente doknr="BJNR001270871">
        <norm><metadaten>
          <jurabk>StGB</jurabk>
          <ausfertigung-datum>1871-05-15</ausfertigung-datum>
          <fundstelle><periodikum>RGBl</periodikum><zitstelle>1871, 127</zitstelle></fundstelle>
          <langue>Strafgesetzbuch</langue>
          <standangabe><standtyp>Stand</standtyp>
            <standkommentar>current</standkommentar>
          </standangabe>
          <standangabe><standtyp>Hinweis</standtyp>
            <standkommentar>pending amendment</standkommentar>
          </standangabe>
        </metadaten></norm></dokumente>"""
        meta = self.parser.parse(xml, "stgb")
        extra = dict(meta.extra)
        assert extra["hinweis"] == "pending amendment"

    def test_enriched_bgbl_reference_in_extra(self):
        """BGBl reference is stored in extra, not summary."""
        xml = (FIXTURES / "gii-gg.xml").read_bytes()
        meta = self.parser.parse(xml, "gg")
        extra = dict(meta.extra)
        assert "bgbl_reference" in extra
        assert extra["bgbl_reference"] == "BGBl 1949, 1"
        assert meta.summary == ""


class TestCountriesDispatch:
    def test_get_text_parser_de(self):
        parser = get_text_parser("de")
        assert isinstance(parser, GIITextParser)

    def test_get_metadata_parser_de(self):
        parser = get_metadata_parser("de")
        assert isinstance(parser, GIIMetadataParser)


class TestSlugGermany:
    def test_norm_path_gg(self):
        meta = NormMetadata(
            title="Grundgesetz",
            short_title="GG",
            identifier="GG",
            country="de",
            rank="grundgesetz",
            publication_date=date(1949, 5, 23),
            status=NormStatus.IN_FORCE,
            department="BMJ",
            source="https://www.gesetze-im-internet.de/gg/",
        )
        assert norm_to_filepath(meta) == "de/GG.md"

    def test_norm_path_bgb(self):
        meta = NormMetadata(
            title="Bürgerliches Gesetzbuch",
            short_title="BGB",
            identifier="BGB",
            country="de",
            rank="bundesgesetz",
            publication_date=date(1896, 8, 18),
            status=NormStatus.IN_FORCE,
            department="BMJ",
            source="https://www.gesetze-im-internet.de/bgb/",
        )
        assert norm_to_filepath(meta) == "de/BGB.md"
