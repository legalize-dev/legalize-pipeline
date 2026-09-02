"""Tests for the BOE metadata parser."""

from datetime import date

from legalize.models import NormStatus, Rank
from legalize.fetcher.es.metadata import parse_metadata

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
        meta = parse_metadata(CONSTITUCION_META_XML, "BOE-A-1978-31229")
        assert meta.identifier == "BOE-A-1978-31229"
        assert meta.rank == Rank.CONSTITUCION
        assert meta.publication_date == date(1978, 12, 29)
        assert meta.department == "Cortes Generales"
        assert meta.status == NormStatus.IN_FORCE

    def test_title(self):
        meta = parse_metadata(CONSTITUCION_META_XML, "BOE-A-1978-31229")
        assert "Constitucion" in meta.title

    def test_source_url(self):
        meta = parse_metadata(CONSTITUCION_META_XML, "BOE-A-1978-31229")
        assert meta.source.startswith("https://")

    def test_rank_from_code(self):
        """The rank is resolved from code '1070' = Constitution."""
        meta = parse_metadata(CONSTITUCION_META_XML, "BOE-A-1978-31229")
        assert meta.rank == Rank.CONSTITUCION

    def test_repealed_status(self):
        """estatus_derogacion='T' results in REPEALED."""
        xml = CONSTITUCION_META_XML.replace(
            b"<estatus_derogacion>N</estatus_derogacion>",
            b"<estatus_derogacion>T</estatus_derogacion>",
        )
        meta = parse_metadata(xml, "BOE-A-1978-31229")
        assert meta.status == NormStatus.REPEALED


# The analysis block of the diary XML, which is where the subsequent references
# come from. Two element shapes: the diary's own (referencia + <palabra>) and the
# consolidated-legislation API's (<id_norma> + <relacion>) for the same block.
_DIARIO_OLD = b"""<?xml version="1.0" encoding="utf-8"?>
<documento><analisis><referencias>
  <anteriores><anterior referencia="BOE-A-1995-7240"><palabra>DEROGA</palabra></anterior></anteriores>
  <posteriores>
    <posterior referencia="BOE-A-2015-5744"><palabra>SE MODIFICA</palabra></posterior>
  </posteriores>
</referencias></analisis></documento>"""

_DIARIO_NEW = b"""<?xml version="1.0" encoding="utf-8"?>
<documento><analisis><referencias>
  <anteriores>
    <anterior><id_norma>BOE-A-1995-7240</id_norma><relacion codigo="210">DEROGA</relacion>
      <texto>Ley 2/1995, de 23 de marzo</texto></anterior>
  </anteriores>
  <posteriores>
    <posterior><id_norma>BOE-A-2020-7311</id_norma>
      <relacion codigo="331">SE DICTA EN RELACION</relacion>
      <texto>con el art. 348 bis, sobre suspension hasta el 31 de diciembre de 2020</texto>
    </posterior>
  </posteriores>
</referencias></analisis></documento>"""

# 21 subsequent references: one more than the slice this used to take.
_DIARIO_MANY = (
    b'<?xml version="1.0" encoding="utf-8"?><documento><analisis><referencias><posteriores>'
    + b"".join(
        f'<posterior referencia="BOE-A-2020-{n:04d}"><palabra>SE MODIFICA</palabra></posterior>'.encode()
        for n in range(21)
    )
    + b"</posteriores></referencias></analisis></documento>"
)


def _extra(diario: bytes) -> dict:
    meta = parse_metadata(CONSTITUCION_META_XML, "BOE-A-1978-31229", diario_xml=diario)
    return dict(meta.extra)


class TestSubsequentReferences:
    """What the gazette says happened to a law after it was published.

    It is the only record of anything that touches a law without rewriting it —
    a suspension above all, which produces no version and therefore no commit.
    """

    def test_the_diary_element_shape_parses(self):
        assert _extra(_DIARIO_OLD)["references_subsequent"] == "SE MODIFICA BOE-A-2015-5744"

    def test_the_other_endpoints_shape_parses_too(self):
        extra = _extra(_DIARIO_NEW)
        assert extra["references_subsequent"].startswith("SE DICTA EN RELACION BOE-A-2020-7311:")
        assert extra["references_previous"].startswith("DEROGA BOE-A-1995-7240:")

    def test_the_sentence_comes_with_it(self):
        """The verb says "SE DICTA EN RELACION". Only the text says "suspension"."""
        assert "suspension" in _extra(_DIARIO_NEW)["references_subsequent"]

    def test_nothing_is_dropped_past_the_twentieth(self):
        """The slice was [:20], and the LSC's 31st reference is the suspension."""
        extra = _extra(_DIARIO_MANY)
        assert extra["references_subsequent_count"] == "21"
        assert extra["references_subsequent"].count(" | ") == 20
        assert "BOE-A-2020-0020" in extra["references_subsequent"]
