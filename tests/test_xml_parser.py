"""Tests for the BOE XML parser."""

from datetime import date

from legalize.transformer.xml_parser import (
    extract_reforms,
    get_bloque_at_date,
    parse_texto_xml,
)


class TestParseTextoXml:
    def test_parse_returns_bloques(self, constitucion_xml: bytes):
        bloques = parse_texto_xml(constitucion_xml)
        assert len(bloques) > 0

    def test_bloque_has_required_fields(self, constitucion_xml: bytes):
        bloques = parse_texto_xml(constitucion_xml)
        for bloque in bloques:
            assert isinstance(bloque.id, str)
            assert isinstance(bloque.tipo, str)
            assert isinstance(bloque.titulo, str)
            assert isinstance(bloque.versions, tuple)

    def test_version_has_date_objects(self, constitucion_xml: bytes):
        bloques = parse_texto_xml(constitucion_xml)
        for bloque in bloques:
            for version in bloque.versions:
                assert isinstance(version.fecha_publicacion, date)
                assert isinstance(version.fecha_vigencia, date)

    def test_paragraphs_are_tuples(self, constitucion_xml: bytes):
        bloques = parse_texto_xml(constitucion_xml)
        for bloque in bloques:
            for version in bloque.versions:
                assert isinstance(version.paragraphs, tuple)

    def test_notas_pie_excluded(self, constitucion_xml: bytes):
        """Footnotes (reform metadata) must not appear as paragraphs."""
        bloques = parse_texto_xml(constitucion_xml)
        for bloque in bloques:
            for version in bloque.versions:
                for p in version.paragraphs:
                    assert "nota_pie" not in p.css_class

    def test_constitucion_has_17_bloques(self, constitucion_xml: bytes):
        """The sample Constitution has 17 blocks."""
        bloques = parse_texto_xml(constitucion_xml)
        assert len(bloques) == 17


class TestExtractReforms:
    def test_constitucion_has_4_reforms(self, constitucion_xml: bytes):
        bloques = parse_texto_xml(constitucion_xml)
        reforms = extract_reforms(bloques)
        assert len(reforms) == 4

    def test_reforms_are_chronological(self, constitucion_xml: bytes):
        bloques = parse_texto_xml(constitucion_xml)
        reforms = extract_reforms(bloques)
        dates = [r.fecha for r in reforms]
        assert dates == sorted(dates)

    def test_first_reform_is_original(self, constitucion_xml: bytes):
        bloques = parse_texto_xml(constitucion_xml)
        reforms = extract_reforms(bloques)
        assert reforms[0].id_norma == "BOE-A-1978-31229"
        assert reforms[0].fecha == date(1978, 12, 29)

    def test_last_reform_is_2024(self, constitucion_xml: bytes):
        bloques = parse_texto_xml(constitucion_xml)
        reforms = extract_reforms(bloques)
        assert reforms[-1].id_norma == "BOE-A-2024-3099"
        assert reforms[-1].fecha == date(2024, 2, 17)

    def test_reform_dates(self, constitucion_xml: bytes):
        bloques = parse_texto_xml(constitucion_xml)
        reforms = extract_reforms(bloques)
        expected_dates = [
            date(1978, 12, 29),
            date(1992, 8, 28),
            date(2011, 9, 27),
            date(2024, 2, 17),
        ]
        assert [r.fecha for r in reforms] == expected_dates

    def test_reform_bloques_afectados(self, constitucion_xml: bytes):
        bloques = parse_texto_xml(constitucion_xml)
        reforms = extract_reforms(bloques)

        # The original publication affects all blocks
        assert len(reforms[0].bloques_afectados) == 17

        # Subsequent reforms affect a single block each
        for reform in reforms[1:]:
            assert len(reform.bloques_afectados) == 1


class TestGetBloqueAtDate:
    def test_original_version(self, constitucion_xml: bytes):
        bloques = parse_texto_xml(constitucion_xml)
        art13 = next(b for b in bloques if b.id == "a13")

        version = get_bloque_at_date(art13, date(1990, 1, 1))
        assert version is not None
        assert version.id_norma == "BOE-A-1978-31229"

    def test_reformed_version(self, constitucion_xml: bytes):
        bloques = parse_texto_xml(constitucion_xml)
        art13 = next(b for b in bloques if b.id == "a13")

        version = get_bloque_at_date(art13, date(2000, 1, 1))
        assert version is not None
        assert version.id_norma == "BOE-A-1992-20403"

    def test_before_publication_returns_none(self, constitucion_xml: bytes):
        bloques = parse_texto_xml(constitucion_xml)
        art13 = next(b for b in bloques if b.id == "a13")

        version = get_bloque_at_date(art13, date(1970, 1, 1))
        assert version is None
