"""Tests for the LEGI parser (France).

Uses XML fixtures that replicate the REAL LEGI dump format
(verified with 2026-03-27 data from echanges.dila.gouv.fr).

Real format:
  - Root: <TEXTELR> (uppercase)
  - Structure: <STRUCT> (not STRUCTURE_TXT)
  - Section title: text of the LIEN_SECTION_TA element
  - Dates: YYYY-MM-DD (ISO 8601)
  - Sentinel: 2999-01-01 (not 99999999)
  - Article: <ARTICLE> with <BLOC_TEXTUEL><CONTENU>
"""

from __future__ import annotations

from datetime import date

from lxml import etree

from legalize.fetcher.fr.parser import (
    LEGIMetadataParser,
    LEGITextParser,
    _extract_text_legi,
    _parse_date_legi,
    _parse_legi_combined,
    _short_title_fr,
)
from legalize.models import NormStatus, Rank


# ─────────────────────────────────────────────
# XML fixtures (real LEGI dump format)
# ─────────────────────────────────────────────

STRUCTURE_XML_CONSTITUTION = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<TEXTELR>
<META>
<META_COMMUN>
<ID>LEGITEXT000006071194</ID>
<ANCIEN_ID/>
<ORIGINE>LEGI</ORIGINE>
<URL>texte/struct/LEGI/TEXT/00/00/06/07/11/LEGITEXT000006071194.xml</URL>
<NATURE>CONSTITUTION</NATURE>
</META_COMMUN>
<META_SPEC>
<META_TEXTE_CHRONICLE>
<CID>LEGITEXT000006071194</CID>
<DATE_PUBLI>1958-10-05</DATE_PUBLI>
<DATE_TEXTE>1958-06-04</DATE_TEXTE>
<DERNIERE_MODIFICATION>2024-03-01</DERNIERE_MODIFICATION>
<TITRE_TEXTE>Constitution du 4 octobre 1958</TITRE_TEXTE>
</META_TEXTE_CHRONICLE>
</META_SPEC>
</META>
<VERSIONS>
<VERSION etat="VIGUEUR">
<LIEN_TXT debut="1958-10-05" fin="2999-01-01" id="LEGITEXT000006071194" num=""/>
</VERSION>
</VERSIONS>
<STRUCT>
</STRUCT>
</TEXTELR>
"""

STRUCTURE_XML_CODE_CIVIL = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<TEXTELR>
<META>
<META_COMMUN>
<ID>LEGITEXT000006069414</ID>
<ANCIEN_ID>CCIVILL</ANCIEN_ID>
<ORIGINE>LEGI</ORIGINE>
<NATURE>CODE</NATURE>
</META_COMMUN>
<META_SPEC>
<META_TEXTE_CHRONICLE>
<CID>LEGITEXT000006069414</CID>
<DATE_PUBLI>2999-01-01</DATE_PUBLI>
<DATE_TEXTE>2999-01-01</DATE_TEXTE>
<DERNIERE_MODIFICATION>2026-01-15</DERNIERE_MODIFICATION>
<TITRE_TEXTE>Code civil</TITRE_TEXTE>
</META_TEXTE_CHRONICLE>
</META_SPEC>
</META>
<VERSIONS>
<VERSION etat="VIGUEUR">
<LIEN_TXT debut="1804-03-21" fin="2999-01-01" id="LEGITEXT000006069414" num=""/>
</VERSION>
</VERSIONS>
<STRUCT>
<LIEN_SECTION_TA cid="LEGISCTA000006117655" debut="1804-03-21" etat="VIGUEUR" fin="2999-01-01" id="LEGISCTA000006117655" niv="1" url="...">Titre pr\xc3\xa9liminaire</LIEN_SECTION_TA>
</STRUCT>
</TEXTELR>
"""

COMBINED_XML_SIMPLE = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<legi_combined id="LEGITEXT000006071194">
  <META>
    <META_COMMUN>
      <ID>LEGITEXT000006071194</ID>
      <NATURE>CONSTITUTION</NATURE>
    </META_COMMUN>
  </META>
  <elements>
    <section id="LEGISCTA000006083836" titre="Titre I - De la souverainet\xc3\xa9" niv="1"
             debut="1958-10-05" fin="2999-01-01" etat="VIGUEUR"/>
    <article id="LEGIARTI000006527453" cid="CID_ART1" num="1"
             debut="2008-07-24" fin="2999-01-01" etat="VIGUEUR">
      <CONTENU>
        <p>La France est une R\xc3\xa9publique indivisible, la\xc3\xafque, d\xc3\xa9mocratique et sociale.</p>
      </CONTENU>
      <source_modif id="JORFTEXT000017237542" date="2008-07-23" nature="LOI CONSTITUTIONNELLE"/>
    </article>
    <article id="LEGIARTI000006527450" cid="CID_ART1" num="1"
             debut="1958-10-05" fin="2008-07-23" etat="ABROGE">
      <CONTENU>
        <p>La France est une R\xc3\xa9publique indivisible.</p>
      </CONTENU>
    </article>
    <section id="LEGISCTA000006083837" titre="Titre II - Le Pr\xc3\xa9sident de la R\xc3\xa9publique" niv="1"
             debut="1958-10-05" fin="2999-01-01" etat="VIGUEUR"/>
    <article id="LEGIARTI000006527460" cid="CID_ART5" num="5"
             debut="1958-06-04" fin="2999-01-01" etat="VIGUEUR">
      <CONTENU>
        <p>Le Pr\xc3\xa9sident de la R\xc3\xa9publique veille au respect de la Constitution.</p>
      </CONTENU>
    </article>
  </elements>
</legi_combined>
"""

COMBINED_XML_ABROGATED_SECTION = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<legi_combined id="LEGITEXT000006069414">
  <META/>
  <elements>
    <section id="SEC1" titre="Titre ancien" niv="1"
             debut="1804-03-21" fin="2010-01-01" etat="ABROGE"/>
    <article id="ART1_V1" cid="CID_OLD" num="1-old"
             debut="1804-03-21" fin="2010-01-01" etat="ABROGE">
      <CONTENU>
        <p>Article abrog\xc3\xa9.</p>
      </CONTENU>
    </article>
  </elements>
</legi_combined>
"""

COMBINED_XML_BLOCKQUOTE = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<legi_combined id="TEST">
  <META/>
  <elements>
    <article id="ART_BQ" cid="CID_BQ" num="61"
             debut="2023-01-01" fin="2999-01-01" etat="VIGUEUR">
      <CONTENU>
        <p><br/>I.-A modifi\xc3\xa9 les dispositions suivantes :</p>
        <blockquote>- Code g\xc3\xa9n\xc3\xa9ral des imp\xc3\xb4ts, CGI.
        <blockquote> Art. 278-0 bis</blockquote>
        </blockquote>
        <p>II.-Le I s'applique aux livraisons.</p>
      </CONTENU>
    </article>
  </elements>
</legi_combined>
"""


# ─────────────────────────────────────────────
# Tests: _parse_date_legi
# ─────────────────────────────────────────────


class TestParseDateLegi:
    def test_iso_date(self):
        """Real dump format: YYYY-MM-DD."""
        assert _parse_date_legi("2008-07-24") == date(2008, 7, 24)

    def test_historical_iso_date(self):
        assert _parse_date_legi("1958-10-05") == date(1958, 10, 5)

    def test_yyyymmdd_compat(self):
        """Also accepts YYYYMMDD format."""
        assert _parse_date_legi("20080724") == date(2008, 7, 24)

    def test_sentinel_2999_returns_none(self):
        """2999-01-01 = indefinite validity, returns None."""
        assert _parse_date_legi("2999-01-01") is None

    def test_sentinel_99999999_returns_none(self):
        """99999999 sentinel returns None."""
        assert _parse_date_legi("99999999") is None

    def test_empty_returns_none(self):
        assert _parse_date_legi("") is None
        assert _parse_date_legi("   ") is None

    def test_year_above_2100_returns_none(self):
        assert _parse_date_legi("2101-01-01") is None

    def test_invalid_date_returns_none(self):
        assert _parse_date_legi("2008-13-32") is None
        assert _parse_date_legi("abc") is None

    def test_short_date_returns_none(self):
        assert _parse_date_legi("2008") is None


# ─────────────────────────────────────────────
# Tests: _extract_text_legi
# ─────────────────────────────────────────────


class TestExtractTextLegi:
    def test_plain_text(self):
        el = etree.fromstring(b"<p>Texto simple.</p>")
        assert _extract_text_legi(el) == "Texto simple."

    def test_bold(self):
        el = etree.fromstring(b"<p>Texto <b>importante</b> aqui.</p>")
        assert _extract_text_legi(el) == "Texto **importante** aqui."

    def test_italic(self):
        el = etree.fromstring(b"<p>Texto <i>cursiva</i> aqui.</p>")
        assert _extract_text_legi(el) == "Texto *cursiva* aqui."

    def test_br(self):
        el = etree.fromstring(b"<p>Linea 1<br/>Linea 2</p>")
        assert _extract_text_legi(el) == "Linea 1\nLinea 2"

    def test_blockquote(self):
        el = etree.fromstring(b"<p>Intro:<blockquote>Citado</blockquote>Fin.</p>")
        result = _extract_text_legi(el)
        assert "> Citado" in result

    def test_div(self):
        el = etree.fromstring(b"<p>Antes<div>Dentro</div>Despues</p>")
        result = _extract_text_legi(el)
        assert "Dentro" in result


# ─────────────────────────────────────────────
# Tests: _short_title_fr
# ─────────────────────────────────────────────


class TestShortTitleFR:
    def test_code(self):
        assert _short_title_fr("Code civil") == "Code civil"

    def test_constitution(self):
        assert _short_title_fr("Constitution du 4 octobre 1958") == "Constitution"

    def test_loi_avec_numero(self):
        assert (
            _short_title_fr("Loi n° 2024-123 du 1er mars 2024 relative aux transports")
            == "Loi n° 2024-123"
        )

    def test_vacio(self):
        assert _short_title_fr("") == ""


# ─────────────────────────────────────────────
# Tests: _parse_legi_combined (text parser)
# ─────────────────────────────────────────────


class TestParseLEGICombined:
    def test_parse_simple(self):
        blocks = _parse_legi_combined(COMBINED_XML_SIMPLE)
        # Should contain: section Titre I, article 1, section Titre II, article 5
        assert len(blocks) == 4

    def test_sections(self):
        blocks = _parse_legi_combined(COMBINED_XML_SIMPLE)
        sections = [b for b in blocks if b.block_type == "section"]
        assert len(sections) == 2
        assert "souveraineté" in sections[0].title
        assert "Président" in sections[1].title

    def test_article_with_two_versions(self):
        """Article 1 has 2 versions (1958 and 2008), grouped by cid."""
        blocks = _parse_legi_combined(COMBINED_XML_SIMPLE)
        articles = [b for b in blocks if b.block_type == "article"]
        art1 = [a for a in articles if "1" in a.title][0]
        assert len(art1.versions) == 2
        dates = [v.publication_date for v in art1.versions]
        assert date(1958, 10, 5) in dates
        assert date(2008, 7, 24) in dates

    def test_article_source_modif(self):
        """The 2008 version of article 1 has source_modif JORFTEXT."""
        blocks = _parse_legi_combined(COMBINED_XML_SIMPLE)
        articles = [b for b in blocks if b.block_type == "article"]
        art1 = [a for a in articles if "1" in a.title][0]
        version_2008 = [v for v in art1.versions if v.publication_date == date(2008, 7, 24)][0]
        assert version_2008.norm_id == "JORFTEXT000017237542"

    def test_article_single_version(self):
        """Article 5 has a single version."""
        blocks = _parse_legi_combined(COMBINED_XML_SIMPLE)
        articles = [b for b in blocks if b.block_type == "article"]
        art5 = [a for a in articles if "5" in a.title][0]
        assert len(art5.versions) == 1
        assert art5.versions[0].publication_date == date(1958, 6, 4)

    def test_article_content(self):
        blocks = _parse_legi_combined(COMBINED_XML_SIMPLE)
        articles = [b for b in blocks if b.block_type == "article"]
        art5 = [a for a in articles if "5" in a.title][0]
        paragraphs = art5.versions[0].paragraphs
        assert any("Article 5" in p.text for p in paragraphs)
        assert any("Président" in p.text for p in paragraphs)

    def test_repealed_section_has_empty_version(self):
        blocks = _parse_legi_combined(COMBINED_XML_ABROGATED_SECTION)
        sections = [b for b in blocks if b.block_type == "section"]
        assert len(sections) == 1
        sec = sections[0]
        assert len(sec.versions) == 2
        assert len(sec.versions[0].paragraphs) > 0
        assert len(sec.versions[1].paragraphs) == 0
        assert sec.versions[1].publication_date == date(2010, 1, 1)

    def test_repealed_article_has_empty_version(self):
        blocks = _parse_legi_combined(COMBINED_XML_ABROGATED_SECTION)
        articles = [b for b in blocks if b.block_type == "article"]
        assert len(articles) == 1
        art = articles[0]
        assert len(art.versions) == 2
        assert len(art.versions[-1].paragraphs) == 0

    def test_empty_xml(self):
        data = b'<legi_combined id="X"><META/></legi_combined>'
        assert _parse_legi_combined(data) == []

    def test_niv_css_mapping(self):
        blocks = _parse_legi_combined(COMBINED_XML_SIMPLE)
        sections = [b for b in blocks if b.block_type == "section"]
        for sec in sections:
            assert sec.versions[0].paragraphs[0].css_class == "titulo_tit"

    def test_blockquote_in_content(self):
        """Articles with <blockquote> (common in amending articles)."""
        blocks = _parse_legi_combined(COMBINED_XML_BLOCKQUOTE)
        assert len(blocks) == 1
        art = blocks[0]
        text = "\n".join(p.text for p in art.versions[0].paragraphs)
        assert "modifi" in text
        assert "livraisons" in text


# ─────────────────────────────────────────────
# Tests: LEGIMetadataParser
# ─────────────────────────────────────────────


class TestLEGIMetadataParser:
    def test_constitution(self):
        parser = LEGIMetadataParser()
        meta = parser.parse(STRUCTURE_XML_CONSTITUTION, "LEGITEXT000006071194")

        assert meta.identifier == "LEGITEXT000006071194"
        assert meta.country == "fr"
        assert meta.rank == Rank.CONSTITUTION_FR
        assert meta.title == "Constitution du 4 octobre 1958"
        assert meta.short_title == "Constitution"
        assert meta.publication_date == date(1958, 10, 5)
        assert meta.status == NormStatus.IN_FORCE
        assert meta.last_modified == date(2024, 3, 1)
        assert "legifrance" in meta.source

    def test_code_civil(self):
        """Code civil has DATE_PUBLI=2999-01-01, falls back to LIEN_TXT debut."""
        parser = LEGIMetadataParser()
        meta = parser.parse(STRUCTURE_XML_CODE_CIVIL, "LEGITEXT000006069414")

        assert meta.identifier == "LEGITEXT000006069414"
        assert meta.country == "fr"
        assert meta.rank == Rank.CODE
        assert meta.title == "Code civil"
        assert meta.short_title == "Code civil"
        # DATE_PUBLI is 2999-01-01 (sentinel) so falls back to LIEN_TXT debut
        assert meta.publication_date == date(1804, 3, 21)
        assert meta.status == NormStatus.IN_FORCE

    def test_sentinel_2999_not_valid_date(self):
        """2999-01-01 as sentinel must not be parsed as a date."""
        parser = LEGIMetadataParser()
        meta = parser.parse(STRUCTURE_XML_CONSTITUTION, "LEGITEXT000006071194")
        # last_modified comes from DERNIERE_MODIFICATION, not from sentinels
        assert meta.last_modified == date(2024, 3, 1)

    def test_extra_fields_from_version_file(self):
        """Version file with NOR, JORF, NUM, ORIGINE_PUBLI → extra fields."""
        version_xml = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<TEXTE_VERSION>
<META>
<META_COMMUN>
<ID>LEGITEXT000006071194</ID>
<NATURE>CONSTITUTION</NATURE>
<NOR>JUSX5800001C</NOR>
</META_COMMUN>
<META_SPEC>
<META_TEXTE_VERSION>
<TITRE>Constitution du 4 octobre 1958</TITRE>
<TITREFULL>Constitution du 4 octobre 1958</TITREFULL>
<ETAT>VIGUEUR</ETAT>
<DATE_DEBUT>1958-10-05</DATE_DEBUT>
<DATE_FIN>2999-01-01</DATE_FIN>
<NUM>58-1067</NUM>
</META_TEXTE_VERSION>
<META_TEXTE_CHRONICLE>
<CID>LEGITEXT000006071194</CID>
<NOR>JUSX5800001C</NOR>
<DATE_PUBLI>1958-10-05</DATE_PUBLI>
<DATE_TEXTE>1958-10-04</DATE_TEXTE>
<JORF>JORFTEXT000000571356</JORF>
<DERNIERE_MODIFICATION>2024-03-01</DERNIERE_MODIFICATION>
<ORIGINE_PUBLI>JORF</ORIGINE_PUBLI>
</META_TEXTE_CHRONICLE>
</META_SPEC>
</META>
<VERSIONS>
<VERSION etat="VIGUEUR">
<LIEN_TXT debut="1958-10-05" fin="2999-01-01" id="LEGITEXT000006071194" num=""/>
</VERSION>
</VERSIONS>
</TEXTE_VERSION>
"""
        parser = LEGIMetadataParser()
        meta = parser.parse(version_xml, "LEGITEXT000006071194")

        extra_dict = dict(meta.extra)
        assert extra_dict["nor"] == "JUSX5800001C"
        assert extra_dict["enactment_date"] == "1958-10-04"
        assert extra_dict["jorf"] == "JORFTEXT000000571356"
        assert extra_dict["official_number"] == "58-1067"
        assert extra_dict["official_journal"] == "JORF"

    def test_extra_empty_when_no_optional_fields(self):
        """Struct file without NOR/JORF/NUM → extra is empty."""
        parser = LEGIMetadataParser()
        meta = parser.parse(STRUCTURE_XML_CODE_CIVIL, "LEGITEXT000006069414")
        # DATE_TEXTE=2999-01-01 is sentinel → no enactment_date
        assert meta.extra == ()


# ─────────────────────────────────────────────
# Tests: LEGITextParser (interface)
# ─────────────────────────────────────────────


class TestLEGITextParser:
    def test_parse_text(self):
        parser = LEGITextParser()
        blocks = parser.parse_text(COMBINED_XML_SIMPLE)
        assert len(blocks) == 4

    def test_extract_reforms(self):
        parser = LEGITextParser()
        reforms = parser.extract_reforms(COMBINED_XML_SIMPLE)
        assert len(reforms) >= 2
        dates = [r.date for r in reforms]
        assert date(1958, 10, 5) in dates or date(1958, 6, 4) in dates


# ─────────────────────────────────────────────
# Tests: countries.py dispatch
# ─────────────────────────────────────────────


class TestCountriesDispatch:
    def test_get_text_parser_fr(self):
        from legalize.countries import get_text_parser

        parser = get_text_parser("fr")
        assert isinstance(parser, LEGITextParser)

    def test_get_metadata_parser_fr(self):
        from legalize.countries import get_metadata_parser

        parser = get_metadata_parser("fr")
        assert isinstance(parser, LEGIMetadataParser)

    def test_get_client_class_fr(self):
        from legalize.countries import get_client_class
        from legalize.fetcher.fr.client import LEGIClient

        assert get_client_class("fr") is LEGIClient

    def test_get_discovery_class_fr(self):
        from legalize.countries import get_discovery_class
        from legalize.fetcher.fr.discovery import LEGIDiscovery

        assert get_discovery_class("fr") is LEGIDiscovery


# ─────────────────────────────────────────────
# Tests: slug.py with French rangos
# ─────────────────────────────────────────────


class TestSlugFR:
    def test_norm_to_filepath_uses_pais(self):
        from legalize.models import NormStatus, NormMetadata, Rank
        from legalize.transformer.slug import norm_to_filepath

        meta = NormMetadata(
            title="Code civil",
            short_title="Code civil",
            identifier="LEGITEXT000006069414",
            country="fr",
            rank=Rank.CODE,
            publication_date=date(1804, 3, 21),
            status=NormStatus.IN_FORCE,
            department="",
            source="https://www.legifrance.gouv.fr/codes/texte_lc/LEGITEXT000006069414",
        )
        assert norm_to_filepath(meta) == "fr/LEGITEXT000006069414.md"


# ─────────────────────────────────────────────
# Tests: client_legi._id_to_subpath
# ─────────────────────────────────────────────


class TestIdToSubpath:
    def test_legitext(self):
        from legalize.fetcher.fr.client import _id_to_subpath

        result = _id_to_subpath("LEGITEXT000006071194")
        # Only 5 digit pairs in the path (first 10 of 12)
        assert result == "LEGI/TEXT/00/00/06/07/11/LEGITEXT000006071194.xml"

    def test_legiarti(self):
        from legalize.fetcher.fr.client import _id_to_subpath

        result = _id_to_subpath("LEGIARTI000006527453")
        assert result == "LEGI/ARTI/00/00/06/52/74/LEGIARTI000006527453.xml"

    def test_legiscta(self):
        from legalize.fetcher.fr.client import _id_to_subpath

        result = _id_to_subpath("LEGISCTA000006083836")
        assert result == "LEGI/SCTA/00/00/06/08/38/LEGISCTA000006083836.xml"
