"""Tests for the Austrian RIS parser."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from legalize.countries import get_metadata_parser, get_text_parser
from legalize.fetcher.parser_ris import RISMetadataParser, RISTextParser
from legalize.models import EstadoNorma, NormaMetadata
from legalize.transformer.slug import rango_to_folder

FIXTURES = Path(__file__).parent / "fixtures"


class TestRISTextParser:
    def setup_method(self):
        self.parser = RISTextParser()

    def test_parse_nor_xml(self):
        xml = (FIXTURES / "ris-nor-NOR12030057.xml").read_bytes()
        bloques = self.parser.parse_texto(xml)
        assert len(bloques) == 1
        bloque = bloques[0]
        assert bloque.id == "NOR12030057"
        assert "§ 1" in bloque.titulo
        assert len(bloque.versions) == 1

    def test_version_has_paragraphs(self):
        xml = (FIXTURES / "ris-nor-NOR12030057.xml").read_bytes()
        bloques = self.parser.parse_texto(xml)
        version = bloques[0].versions[0]
        assert len(version.paragraphs) > 0

    def test_version_date(self):
        xml = (FIXTURES / "ris-nor-NOR12030057.xml").read_bytes()
        bloques = self.parser.parse_texto(xml)
        version = bloques[0].versions[0]
        assert version.fecha_publicacion == date(1975, 1, 17)

    def test_extract_reforms_returns_list(self):
        xml = (FIXTURES / "ris-nor-NOR12030057.xml").read_bytes()
        reforms = self.parser.extract_reforms(xml)
        assert isinstance(reforms, list)


class TestRISMetadataParser:
    def setup_method(self):
        self.parser = RISMetadataParser()

    def test_parse_metadata(self):
        json_data = (FIXTURES / "ris-metadata-10002333.json").read_bytes()
        meta = self.parser.parse(json_data, "10002333")
        assert isinstance(meta, NormaMetadata)
        assert meta.pais == "at"
        assert meta.identificador == "AT-10002333"

    def test_rango_verordnung(self):
        json_data = (FIXTURES / "ris-metadata-10002333.json").read_bytes()
        meta = self.parser.parse(json_data, "10002333")
        assert str(meta.rango) == "verordnung"

    def test_titulo_corto(self):
        json_data = (FIXTURES / "ris-metadata-10002333.json").read_bytes()
        meta = self.parser.parse(json_data, "10002333")
        assert "Produktdeklaration" in meta.titulo_corto

    def test_estado_derogada(self):
        json_data = (FIXTURES / "ris-metadata-10002333.json").read_bytes()
        meta = self.parser.parse(json_data, "10002333")
        # This law was aufgehoben in 1994
        assert meta.estado == EstadoNorma.DEROGADA


class TestCountriesDispatch:
    def test_get_text_parser_at(self):
        parser = get_text_parser("at")
        assert isinstance(parser, RISTextParser)

    def test_get_metadata_parser_at(self):
        parser = get_metadata_parser("at")
        assert isinstance(parser, RISMetadataParser)


class TestSlugAustria:
    def test_bundesgesetz_folder(self):
        assert rango_to_folder("bundesgesetz") == "bundesgesetze"

    def test_verordnung_folder(self):
        assert rango_to_folder("verordnung") == "verordnungen"

    def test_bundesverfassungsgesetz_folder(self):
        assert rango_to_folder("bundesverfassungsgesetz") == "bundesverfassungsgesetze"

    def test_kundmachung_folder(self):
        assert rango_to_folder("kundmachung") == "kundmachungen"

    def test_staatsvertrag_folder(self):
        assert rango_to_folder("staatsvertrag") == "staatsvertraege"

    def test_sonstige_folder(self):
        assert rango_to_folder("sonstige") == "sonstige"
