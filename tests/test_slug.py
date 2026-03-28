"""Tests for file path generation."""

from datetime import date

from legalize.models import EstadoNorma, NormaMetadata, Rango
from legalize.transformer.slug import norma_to_filepath, rango_to_folder


def _make_metadata(
    identificador: str = "BOE-A-2024-1",
    pais: str = "es",
    rango: Rango = Rango.LEY,
) -> NormaMetadata:
    return NormaMetadata(
        titulo="Test",
        titulo_corto="Test",
        identificador=identificador,
        pais=pais,
        rango=rango,
        fecha_publicacion=date(2024, 1, 1),
        estado=EstadoNorma.VIGENTE,
        departamento="Test",
        fuente="https://example.com",
    )


class TestRangoToFolder:
    def test_ley(self):
        assert rango_to_folder(Rango.LEY) == "leyes"

    def test_constitucion(self):
        assert rango_to_folder(Rango.CONSTITUCION) == "constituciones"

    def test_real_decreto(self):
        assert rango_to_folder(Rango.REAL_DECRETO) == "reales-decretos"

    def test_ley_organica(self):
        assert rango_to_folder(Rango.LEY_ORGANICA) == "leyes-organicas"

    def test_unknown_rango(self):
        assert rango_to_folder("something_new") == "otros"

    def test_string_rango(self):
        assert rango_to_folder("ley") == "leyes"


class TestNormaToFilepath:
    def test_ley_goes_to_leyes(self):
        meta = _make_metadata("BOE-A-2015-11430", rango=Rango.LEY)
        assert norma_to_filepath(meta) == "leyes/BOE-A-2015-11430.md"

    def test_constitucion_goes_to_constituciones(self):
        meta = _make_metadata("BOE-A-1978-31229", rango=Rango.CONSTITUCION)
        assert norma_to_filepath(meta) == "constituciones/BOE-A-1978-31229.md"

    def test_real_decreto(self):
        meta = _make_metadata("BOE-A-2024-001", rango=Rango.REAL_DECRETO)
        assert norma_to_filepath(meta) == "reales-decretos/BOE-A-2024-001.md"

    def test_id_is_stable(self):
        """Two norms with the same ID but different rango go to different folders,
        but the filename is always the identificador."""
        meta1 = _make_metadata("BOE-A-1978-31229", rango=Rango.CONSTITUCION)
        meta2 = _make_metadata("BOE-A-1978-31229", rango=Rango.LEY)
        # Different folder
        assert "constituciones/" in norma_to_filepath(meta1)
        assert "leyes/" in norma_to_filepath(meta2)
        # Same filename
        assert norma_to_filepath(meta1).split("/")[1] == norma_to_filepath(meta2).split("/")[1]
