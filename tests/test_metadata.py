"""Tests for the BOE metadata parser."""

from datetime import date

from legalize.models import EstadoNorma, Rango
from legalize.transformer.metadata import parse_metadatos

# Real XML from the Constitution (captured from the API)
CONSTITUCION_META_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<response>
  <status><code>200</code><text>ok</text></status>
  <data>
    <metadatos>
      <fecha_actualizacion>20260224T130836Z</fecha_actualizacion>
      <identificador>BOE-A-1978-31229</identificador>
      <ambito codigo="1">Estatal</ambito>
      <departamento codigo="1220">Cortes Generales</departamento>
      <rango codigo="1070">Constitucion</rango>
      <fecha_disposicion>19781227</fecha_disposicion>
      <titulo>Constitucion Espanola.</titulo>
      <diario>Boletin Oficial del Estado</diario>
      <fecha_publicacion>19781229</fecha_publicacion>
      <diario_numero>311</diario_numero>
      <fecha_vigencia>19781229</fecha_vigencia>
      <estatus_derogacion>N</estatus_derogacion>
      <estatus_anulacion>N</estatus_anulacion>
      <vigencia_agotada>N</vigencia_agotada>
      <estado_consolidacion codigo="3">Finalizado</estado_consolidacion>
      <url_eli>https://www.boe.es/eli/es/c/1978/12/27/(1)</url_eli>
      <url_html_consolidada>https://www.boe.es/buscar/act.php?id=BOE-A-1978-31229</url_html_consolidada>
    </metadatos>
  </data>
</response>"""


class TestParseMetadatos:
    def test_parse_constitucion(self):
        meta = parse_metadatos(CONSTITUCION_META_XML, "BOE-A-1978-31229")
        assert meta.identificador == "BOE-A-1978-31229"
        assert meta.rango == Rango.CONSTITUCION
        assert meta.fecha_publicacion == date(1978, 12, 29)
        assert meta.departamento == "Cortes Generales"
        assert meta.estado == EstadoNorma.VIGENTE

    def test_titulo(self):
        meta = parse_metadatos(CONSTITUCION_META_XML, "BOE-A-1978-31229")
        assert "Constitucion" in meta.titulo

    def test_fuente(self):
        meta = parse_metadatos(CONSTITUCION_META_XML, "BOE-A-1978-31229")
        assert meta.fuente.startswith("https://")

    def test_rango_from_code(self):
        """The rango is resolved from code '1070' = Constitution."""
        meta = parse_metadatos(CONSTITUCION_META_XML, "BOE-A-1978-31229")
        assert meta.rango == Rango.CONSTITUCION

    def test_derogada_status(self):
        """estatus_derogacion='T' results in DEROGADA."""
        xml = CONSTITUCION_META_XML.replace(
            b"<estatus_derogacion>N</estatus_derogacion>",
            b"<estatus_derogacion>T</estatus_derogacion>",
        )
        meta = parse_metadatos(xml, "BOE-A-1978-31229")
        assert meta.estado == EstadoNorma.DEROGADA
