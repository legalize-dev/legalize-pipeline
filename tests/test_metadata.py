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

# The diary's own shape, with the code where the diary puts it: on <palabra>.
_DIARIO_CODED = b"""<?xml version="1.0" encoding="utf-8"?>
<documento><analisis><referencias><posteriores>
  <posterior referencia="BOE-A-2021-0001"><palabra codigo="440">SE TRANSPONE</palabra></posterior>
</posteriores></referencias></analisis></documento>"""

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
        assert extra["references_subsequent"].startswith(
            "SE DICTA EN RELACION [331] BOE-A-2020-7311:"
        )
        assert extra["references_previous"].startswith("DEROGA [210] BOE-A-1995-7240:")

    def test_the_verbs_numeric_code_is_kept(self):
        """The only language-neutral half of the relation (#87, #129).

        210 is DEROGA whatever the label says, so a cross-country normalisation
        can be built on it later without a reprocess. The code rides on
        ``<palabra>`` in the diary shape and on ``<relacion>`` in the API's;
        both are read.
        """
        assert "[210]" in _extra(_DIARIO_NEW)["references_previous"]
        assert "[331]" in _extra(_DIARIO_NEW)["references_subsequent"]
        assert "[440]" in _extra(_DIARIO_CODED)["references_subsequent"]

    def test_an_uncoded_verb_still_reads(self):
        """The older diary shape sends no code; the entry keeps its grammar."""
        assert _extra(_DIARIO_OLD)["references_subsequent"] == "SE MODIFICA BOE-A-2015-5744"

    def test_the_sentence_comes_with_it(self):
        """The verb says "SE DICTA EN RELACION". Only the text says "suspension"."""
        assert "suspension" in _extra(_DIARIO_NEW)["references_subsequent"]

    def test_nothing_is_dropped_past_the_twentieth(self):
        """The slice was [:20], and the LSC's 31st reference is the suspension."""
        extra = _extra(_DIARIO_MANY)
        assert extra["references_subsequent_count"] == "21"
        assert extra["references_subsequent"].count(" | ") == 20
        assert "BOE-A-2020-0020" in extra["references_subsequent"]


class TestFrontmatterKeyNames:
    """The published key names are the corpus's contract (#129).

    Renaming one rewrites all 12,299 files, so it can only ride a reprocess.
    These assertions exist so the next rename is a decision rather than an
    accident: nothing else in the engine, web, enrichment or the SDKs reads
    these keys by name, so a silent change would reach production unnoticed.
    """

    def test_scope_code_is_english(self):
        meta = parse_metadata(CONSTITUCION_META_XML, "BOE-A-1978-31229")
        keys = dict(meta.extra)
        assert keys["scope_code"] == "1"
        assert "ambito_code" not in keys

    def test_the_consolidated_html_url_drops_the_spanish_suffix(self):
        meta = parse_metadata(CONSTITUCION_META_XML, "BOE-A-1978-31229")
        keys = dict(meta.extra)
        assert keys["url_html"].endswith("id=BOE-A-1978-31229")
        assert "url_html_consolidada" not in keys

    def test_co_official_pdf_urls_use_iso_639_1_codes(self):
        """A Belgian corpus emits url_pdf_nl and a consumer written against es
        keeps working; with Spanish exonyms nothing joins."""
        diario = (
            b'<?xml version="1.0" encoding="utf-8"?><documento><metadatos>'
            b"<url_pdf>/boe/dias/2002/01/15/pdfs/A00544-00548.pdf</url_pdf>"
            b"<url_pdf_catalan>/boe_catalan/x.pdf</url_pdf_catalan>"
            b"<url_pdf_euskera>/boe_euskera/x.pdf</url_pdf_euskera>"
            b"<url_pdf_gallego>/boe_gallego/x.pdf</url_pdf_gallego>"
            b"<url_pdf_valenciano>/boe_valenciano/x.pdf</url_pdf_valenciano>"
            b"</metadatos></documento>"
        )
        keys = _extra(diario)
        assert set(keys) >= {"url_pdf_ca", "url_pdf_eu", "url_pdf_gl", "url_pdf_va"}
        assert not [
            k for k in keys if k.endswith(("_catalan", "_euskera", "_gallego", "_valenciano"))
        ]

    def test_the_pdf_url_ships_once(self):
        """It used to ship twice, identical in 12,298 of 12,299 files."""
        diario = (
            b'<?xml version="1.0" encoding="utf-8"?><documento><metadatos>'
            b"<url_pdf>/boe/dias/2002/01/15/pdfs/A00544-00548.pdf</url_pdf>"
            b"</metadatos></documento>"
        )
        meta = parse_metadata(CONSTITUCION_META_XML, "BOE-A-1978-31229", diario_xml=diario)
        assert meta.pdf_url == "https://www.boe.es/boe/dias/2002/01/15/pdfs/A00544-00548.pdf"
        assert "url_pdf" not in dict(meta.extra)


class TestEveryRankTheSourcePublishes:
    """A rank the map does not have is not a missing label — it is a guess.

    `_parse_rank` falls through to `_infer_rank_from_title`, whose first test is
    "constitución" in the title. `BOE-A-2026-10881` is *Reforma del apartado 3
    del artículo 69 de la Constitución Española*, the fourth amendment to the
    Constitution in history, and `rango codigo="1676"` was not mapped — so the
    act that amends the Constitution was typed as the Constitution.
    """

    # `GET https://www.boe.es/datosabiertos/api/datos-auxiliares/rangos`,
    # captured 2026-09-04. The source's whole vocabulary for consolidated
    # legislation, so this is coverage, not a sample.
    BOE_RANGOS = {
        "1020": "Acuerdo",
        "1180": "Acuerdo Internacional",
        "1390": "Circular",
        "1070": "Constitución",
        "1510": "Decreto",
        "1480": "Decreto Foral Legislativo",
        "1470": "Decreto Legislativo",
        "1500": "Decreto-ley",
        "1325": "Decreto-ley Foral",
        "1410": "Instrucción",
        "1300": "Ley",
        "1450": "Ley Foral",
        "1290": "Ley Orgánica",
        "1350": "Orden",
        "1340": "Real Decreto",
        "1310": "Real Decreto Legislativo",
        "1320": "Real Decreto-ley",
        "1220": "Reglamento",
        "1370": "Resolución",
    }

    def test_the_whole_published_vocabulary_is_mapped(self):
        from legalize.fetcher.es.metadata import _RANK_CODE_MAP

        missing = {c: n for c, n in self.BOE_RANGOS.items() if c not in _RANK_CODE_MAP}
        assert not missing, f"ranks the BOE publishes and the parser would guess: {missing}"

    def test_a_reforma_is_not_the_constitution(self):
        from legalize.models import Rank

        xml = CONSTITUCION_META_XML.replace(
            b'<rango codigo="1070">Constitucion</rango>',
            b'<rango codigo="1676">Reforma</rango>',
        ).replace(
            b"<titulo>Constitucion Espanola.</titulo>",
            b"<titulo>Reforma del apartado 3 del articulo 69 de la Constitucion Espanola.</titulo>",
        )
        meta = parse_metadata(xml, "BOE-A-2026-10881")
        assert meta.rank == Rank.REFORMA

    def test_the_gazette_ranks_that_are_not_norms_are_named_not_guessed(self):
        from legalize.fetcher.es.metadata import _RANK_CODE_MAP
        from legalize.models import Rank

        assert _RANK_CODE_MAP["1590"] == Rank.CORRECCION
        assert _RANK_CODE_MAP["1240"] == Rank.SENTENCIA
        assert _RANK_CODE_MAP["1250"] == Rank.AUTO
        assert _RANK_CODE_MAP["63"] == Rank.PROVIDENCIA
        assert _RANK_CODE_MAP["41"] == Rank.NOTA_DIPLOMATICA
