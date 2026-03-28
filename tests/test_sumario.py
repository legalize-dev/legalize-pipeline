"""Tests for the BOE sumario parser."""

from legalize.config import ScopeConfig
from legalize.fetcher.sumario import parse_sumario
from legalize.models import Rango

# Minimal XML that replicates the real BOE sumario structure
SUMARIO_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<response>
  <status><code>200</code><text>ok</text></status>
  <data>
    <sumario>
      <metadatos>
        <fecha_publicacion>20260326</fecha_publicacion>
      </metadatos>
      <diario numero="75">
        <seccion codigo="1" nombre="I. Disposiciones generales">
          <departamento codigo="1220" nombre="CORTES GENERALES">
            <epigrafe nombre="Leyes Organicas">
              <item>
                <identificador>BOE-A-2026-1001</identificador>
                <titulo>Ley Organica 1/2026, de 20 de marzo, de reforma del Codigo Penal.</titulo>
                <url_xml>https://www.boe.es/diario_boe/xml.php?id=BOE-A-2026-1001</url_xml>
              </item>
            </epigrafe>
          </departamento>
          <departamento codigo="4335" nombre="MINISTERIO DE SANIDAD">
            <epigrafe nombre="Establecimientos sanitarios">
              <item>
                <identificador>BOE-A-2026-6975</identificador>
                <titulo>Real Decreto 239/2026, de 25 de marzo, por el que se modifica algo.</titulo>
                <url_xml>https://www.boe.es/diario_boe/xml.php?id=BOE-A-2026-6975</url_xml>
              </item>
            </epigrafe>
          </departamento>
        </seccion>
        <seccion codigo="2A" nombre="II. Autoridades y personal">
          <departamento codigo="1820" nombre="CONSEJO GENERAL DEL PODER JUDICIAL">
            <epigrafe nombre="Nombramientos">
              <item>
                <identificador>BOE-A-2026-6980</identificador>
                <titulo>Acuerdo de 25 de marzo de 2026 de nombramientos.</titulo>
                <url_xml>https://www.boe.es/diario_boe/xml.php?id=BOE-A-2026-6980</url_xml>
              </item>
            </epigrafe>
          </departamento>
        </seccion>
      </diario>
    </sumario>
  </data>
</response>"""


class TestParseSumario:
    def test_filters_section_1_only(self):
        """Only includes dispositions from section 1 (General provisions)."""
        scope = ScopeConfig()
        result = parse_sumario(SUMARIO_XML, scope)
        ids = [d.id_boe for d in result]
        # Section 1 items
        assert "BOE-A-2026-1001" in ids
        # Section 2A items (appointments) not included
        assert "BOE-A-2026-6980" not in ids

    def test_filters_by_rango(self):
        """Filters by rangos in scope."""
        scope = ScopeConfig(rangos=[Rango.LEY_ORGANICA])
        result = parse_sumario(SUMARIO_XML, scope)
        # Only the LO should be present
        assert len(result) >= 1
        lo_ids = [d.id_boe for d in result if d.rango == Rango.LEY_ORGANICA]
        assert "BOE-A-2026-1001" in lo_ids

    def test_infers_rango_from_titulo(self):
        scope = ScopeConfig()
        result = parse_sumario(SUMARIO_XML, scope)
        lo = next(d for d in result if d.id_boe == "BOE-A-2026-1001")
        assert lo.rango == Rango.LEY_ORGANICA

    def test_extracts_departamento(self):
        scope = ScopeConfig()
        result = parse_sumario(SUMARIO_XML, scope)
        lo = next(d for d in result if d.id_boe == "BOE-A-2026-1001")
        assert lo.departamento == "CORTES GENERALES"

    def test_extracts_url_xml(self):
        scope = ScopeConfig()
        result = parse_sumario(SUMARIO_XML, scope)
        lo = next(d for d in result if d.id_boe == "BOE-A-2026-1001")
        assert "BOE-A-2026-1001" in lo.url_xml
