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

from legalize.fetcher.parser_legi import (
    LEGIMetadataParser,
    LEGITextParser,
    _extract_text_legi,
    _parse_date_legi,
    _parse_legi_combined,
    _titulo_corto_fr,
)
from legalize.models import EstadoNorma, Rango


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
    def test_fecha_iso(self):
        """Real dump format: YYYY-MM-DD."""
        assert _parse_date_legi("2008-07-24") == date(2008, 7, 24)

    def test_fecha_historica_iso(self):
        assert _parse_date_legi("1958-10-05") == date(1958, 10, 5)

    def test_fecha_yyyymmdd_compat(self):
        """Backward compatibility with legacy format."""
        assert _parse_date_legi("20080724") == date(2008, 7, 24)

    def test_sentinel_2999_devuelve_none(self):
        """2999-01-01 = indefinite validity, returns None."""
        assert _parse_date_legi("2999-01-01") is None

    def test_sentinel_99999999_devuelve_none(self):
        """99999999 (legacy format) returns None."""
        assert _parse_date_legi("99999999") is None

    def test_vacia_devuelve_none(self):
        assert _parse_date_legi("") is None
        assert _parse_date_legi("   ") is None

    def test_ano_mayor_2100_devuelve_none(self):
        assert _parse_date_legi("2101-01-01") is None

    def test_fecha_invalida_devuelve_none(self):
        assert _parse_date_legi("2008-13-32") is None
        assert _parse_date_legi("abc") is None

    def test_fecha_corta_devuelve_none(self):
        assert _parse_date_legi("2008") is None


# ─────────────────────────────────────────────
# Tests: _extract_text_legi
# ─────────────────────────────────────────────


class TestExtractTextLegi:
    def test_texto_plano(self):
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
# Tests: _titulo_corto_fr
# ─────────────────────────────────────────────


class TestTituloCortoFR:
    def test_code(self):
        assert _titulo_corto_fr("Code civil") == "Code civil"

    def test_constitution(self):
        assert _titulo_corto_fr("Constitution du 4 octobre 1958") == "Constitution"

    def test_loi_avec_numero(self):
        assert _titulo_corto_fr("Loi n° 2024-123 du 1er mars 2024 relative aux transports") == "Loi n° 2024-123"

    def test_vacio(self):
        assert _titulo_corto_fr("") == ""


# ─────────────────────────────────────────────
# Tests: _parse_legi_combined (text parser)
# ─────────────────────────────────────────────


class TestParseLEGICombined:
    def test_parse_simple(self):
        bloques = _parse_legi_combined(COMBINED_XML_SIMPLE)
        # Should contain: section Titre I, article 1, section Titre II, article 5
        assert len(bloques) == 4

    def test_secciones(self):
        bloques = _parse_legi_combined(COMBINED_XML_SIMPLE)
        secciones = [b for b in bloques if b.tipo == "section"]
        assert len(secciones) == 2
        assert "souveraineté" in secciones[0].titulo
        assert "Président" in secciones[1].titulo

    def test_articulo_con_dos_versiones(self):
        """Article 1 has 2 versions (1958 and 2008), grouped by cid."""
        bloques = _parse_legi_combined(COMBINED_XML_SIMPLE)
        articulos = [b for b in bloques if b.tipo == "article"]
        art1 = [a for a in articulos if "1" in a.titulo][0]
        assert len(art1.versions) == 2
        fechas = [v.fecha_publicacion for v in art1.versions]
        assert date(1958, 10, 5) in fechas
        assert date(2008, 7, 24) in fechas

    def test_articulo_source_modif(self):
        """The 2008 version of article 1 has source_modif JORFTEXT."""
        bloques = _parse_legi_combined(COMBINED_XML_SIMPLE)
        articulos = [b for b in bloques if b.tipo == "article"]
        art1 = [a for a in articulos if "1" in a.titulo][0]
        version_2008 = [v for v in art1.versions if v.fecha_publicacion == date(2008, 7, 24)][0]
        assert version_2008.id_norma == "JORFTEXT000017237542"

    def test_articulo_solo_vigente(self):
        """Article 5 has a single version."""
        bloques = _parse_legi_combined(COMBINED_XML_SIMPLE)
        articulos = [b for b in bloques if b.tipo == "article"]
        art5 = [a for a in articulos if "5" in a.titulo][0]
        assert len(art5.versions) == 1
        assert art5.versions[0].fecha_publicacion == date(1958, 6, 4)

    def test_contenido_articulo(self):
        bloques = _parse_legi_combined(COMBINED_XML_SIMPLE)
        articulos = [b for b in bloques if b.tipo == "article"]
        art5 = [a for a in articulos if "5" in a.titulo][0]
        paragraphs = art5.versions[0].paragraphs
        assert any("Article 5" in p.text for p in paragraphs)
        assert any("Président" in p.text for p in paragraphs)

    def test_seccion_derogada_tiene_version_vacia(self):
        bloques = _parse_legi_combined(COMBINED_XML_ABROGATED_SECTION)
        secciones = [b for b in bloques if b.tipo == "section"]
        assert len(secciones) == 1
        sec = secciones[0]
        assert len(sec.versions) == 2
        assert len(sec.versions[0].paragraphs) > 0
        assert len(sec.versions[1].paragraphs) == 0
        assert sec.versions[1].fecha_publicacion == date(2010, 1, 1)

    def test_articulo_derogado_tiene_version_vacia(self):
        bloques = _parse_legi_combined(COMBINED_XML_ABROGATED_SECTION)
        articulos = [b for b in bloques if b.tipo == "article"]
        assert len(articulos) == 1
        art = articulos[0]
        assert len(art.versions) == 2
        assert len(art.versions[-1].paragraphs) == 0

    def test_xml_vacio(self):
        data = b'<legi_combined id="X"><META/></legi_combined>'
        assert _parse_legi_combined(data) == []

    def test_niv_css_mapping(self):
        bloques = _parse_legi_combined(COMBINED_XML_SIMPLE)
        secciones = [b for b in bloques if b.tipo == "section"]
        for sec in secciones:
            assert sec.versions[0].paragraphs[0].css_class == "titulo_tit"

    def test_blockquote_en_contenu(self):
        """Articles with <blockquote> (common in amending articles)."""
        bloques = _parse_legi_combined(COMBINED_XML_BLOCKQUOTE)
        assert len(bloques) == 1
        art = bloques[0]
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

        assert meta.identificador == "LEGITEXT000006071194"
        assert meta.pais == "fr"
        assert meta.rango == Rango.CONSTITUTION_FR
        assert meta.titulo == "Constitution du 4 octobre 1958"
        assert meta.titulo_corto == "Constitution"
        assert meta.fecha_publicacion == date(1958, 10, 5)
        assert meta.estado == EstadoNorma.VIGENTE
        assert meta.fecha_ultima_modificacion == date(2024, 3, 1)
        assert "legifrance" in meta.fuente

    def test_code_civil(self):
        """Code civil has DATE_PUBLI=2999-01-01, falls back to LIEN_TXT debut."""
        parser = LEGIMetadataParser()
        meta = parser.parse(STRUCTURE_XML_CODE_CIVIL, "LEGITEXT000006069414")

        assert meta.identificador == "LEGITEXT000006069414"
        assert meta.pais == "fr"
        assert meta.rango == Rango.CODE
        assert meta.titulo == "Code civil"
        assert meta.titulo_corto == "Code civil"
        # DATE_PUBLI is 2999-01-01 (sentinel) so falls back to LIEN_TXT debut
        assert meta.fecha_publicacion == date(1804, 3, 21)
        assert meta.estado == EstadoNorma.VIGENTE

    def test_sentinel_2999_no_es_fecha_valida(self):
        """2999-01-01 as sentinel must not be parsed as a date."""
        parser = LEGIMetadataParser()
        meta = parser.parse(STRUCTURE_XML_CONSTITUTION, "LEGITEXT000006071194")
        # fecha_ultima_modificacion comes from DERNIERE_MODIFICATION, not from sentinels
        assert meta.fecha_ultima_modificacion == date(2024, 3, 1)


# ─────────────────────────────────────────────
# Tests: LEGITextParser (interface)
# ─────────────────────────────────────────────


class TestLEGITextParser:
    def test_parse_texto(self):
        parser = LEGITextParser()
        bloques = parser.parse_texto(COMBINED_XML_SIMPLE)
        assert len(bloques) == 4

    def test_extract_reforms(self):
        parser = LEGITextParser()
        reforms = parser.extract_reforms(COMBINED_XML_SIMPLE)
        assert len(reforms) >= 2
        fechas = [r.fecha for r in reforms]
        assert date(1958, 10, 5) in fechas or date(1958, 6, 4) in fechas


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
        from legalize.fetcher.client_legi import LEGIClient
        assert get_client_class("fr") is LEGIClient

    def test_get_discovery_class_fr(self):
        from legalize.countries import get_discovery_class
        from legalize.fetcher.discovery_legi import LEGIDiscovery
        assert get_discovery_class("fr") is LEGIDiscovery


# ─────────────────────────────────────────────
# Tests: slug.py with French rangos
# ─────────────────────────────────────────────


class TestSlugFR:
    def test_code_folder(self):
        from legalize.transformer.slug import rango_to_folder
        assert rango_to_folder("code") == "codes"

    def test_loi_folder(self):
        from legalize.transformer.slug import rango_to_folder
        assert rango_to_folder("loi") == "lois"

    def test_constitution_fr_folder(self):
        from legalize.transformer.slug import rango_to_folder
        assert rango_to_folder("constitution_fr") == "constitutions"

    def test_norma_to_filepath_code(self):
        from legalize.models import EstadoNorma, NormaMetadata, Rango
        from legalize.transformer.slug import norma_to_filepath

        meta = NormaMetadata(
            titulo="Code civil",
            titulo_corto="Code civil",
            identificador="LEGITEXT000006069414",
            pais="fr",
            rango=Rango.CODE,
            fecha_publicacion=date(1804, 3, 21),
            estado=EstadoNorma.VIGENTE,
            departamento="",
            fuente="https://www.legifrance.gouv.fr/codes/texte_lc/LEGITEXT000006069414",
        )
        assert norma_to_filepath(meta) == "codes/LEGITEXT000006069414.md"


# ─────────────────────────────────────────────
# Tests: client_legi._id_to_subpath
# ─────────────────────────────────────────────


class TestIdToSubpath:
    def test_legitext(self):
        from legalize.fetcher.client_legi import _id_to_subpath
        result = _id_to_subpath("LEGITEXT000006071194")
        # Only 5 digit pairs in the path (first 10 of 12)
        assert result == "LEGI/TEXT/00/00/06/07/11/LEGITEXT000006071194.xml"

    def test_legiarti(self):
        from legalize.fetcher.client_legi import _id_to_subpath
        result = _id_to_subpath("LEGIARTI000006527453")
        assert result == "LEGI/ARTI/00/00/06/52/74/LEGIARTI000006527453.xml"

    def test_legiscta(self):
        from legalize.fetcher.client_legi import _id_to_subpath
        result = _id_to_subpath("LEGISCTA000006083836")
        assert result == "LEGI/SCTA/00/00/06/08/38/LEGISCTA000006083836.xml"
