"""Pin tests for the 2026-04-22 Spain parser refactor (RESEARCH-ES-v2.md).

These cover the constructs that the pre-refactor parser silently dropped
or degraded: tables, nota_pie footnotes, cita blockquotes, libro/anexo
headings, inline sup/sub/a-href, and <img> elements.
"""

from __future__ import annotations


from legalize.transformer.markdown import render_paragraphs
from legalize.transformer.xml_parser import parse_text_xml


def _wrap(body: str) -> bytes:
    """Embed a <bloque>/<version> skeleton around the test body."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<texto>"
        '<bloque id="b1" tipo="articulo" titulo="Art 1">'
        '<version id_norma="BOE-A-1978-31229" fecha_publicacion="19781229">'
        f"{body}"
        "</version>"
        "</bloque>"
        "</texto>"
    ).encode("utf-8")


class TestInlineFormatting:
    def test_bold_and_italic(self):
        blocks = parse_text_xml(_wrap("<p>Texto con <b>negrita</b> e <i>cursiva</i>.</p>"))
        ps = blocks[0].versions[0].paragraphs
        assert any("**negrita**" in p.text for p in ps)
        assert any("*cursiva*" in p.text for p in ps)

    def test_sup_and_sub_preserved(self):
        blocks = parse_text_xml(_wrap("<p>H<sub>2</sub>O y m<sup>2</sup> y 3.<sup>er</sup>.</p>"))
        text = blocks[0].versions[0].paragraphs[0].text
        assert "<sub>2</sub>" in text
        assert "<sup>2</sup>" in text
        assert "<sup>er</sup>" in text

    def test_a_href_preserved(self):
        blocks = parse_text_xml(_wrap('<p>Ver <a href="https://www.boe.es/x">x</a>.</p>'))
        assert "[x](https://www.boe.es/x)" in blocks[0].versions[0].paragraphs[0].text

    def test_a_with_referencia_attribute(self):
        blocks = parse_text_xml(
            _wrap('<p><a class="refPost" referencia="BOE-A-2015-3439">ref</a>.</p>')
        )
        text = blocks[0].versions[0].paragraphs[0].text
        assert "[ref](https://www.boe.es/buscar/doc.php?id=BOE-A-2015-3439)" in text

    def test_a_without_href_but_with_boe_id_in_text(self):
        blocks = parse_text_xml(_wrap('<p><a class="refPost">Ref. BOE-A-2014-12327</a>.</p>'))
        text = blocks[0].versions[0].paragraphs[0].text
        assert "https://www.boe.es/buscar/doc.php?id=BOE-A-2014-12327" in text


class TestTables:
    def test_table_becomes_pipe_table(self):
        xml = _wrap(
            """
            <table>
              <thead>
                <tr><th><p class="cabeza_tabla">Col A</p></th><th><p class="cabeza_tabla">Col B</p></th></tr>
              </thead>
              <tbody>
                <tr><td><p class="cuerpo_tabla_izq">v1</p></td><td><p class="cuerpo_tabla_centro">v2</p></td></tr>
              </tbody>
            </table>
            """
        )
        blocks = parse_text_xml(xml)
        ps = blocks[0].versions[0].paragraphs
        table_ps = [p for p in ps if p.css_class == "table"]
        assert len(table_ps) == 1
        rendered = table_ps[0].text
        assert "| Col A | Col B |" in rendered
        assert "| v1 | v2 |" in rendered

    def test_table_rowspan_colspan_expanded(self):
        xml = _wrap(
            """
            <table>
              <tr><td colspan="2"><p>wide</p></td></tr>
              <tr><td><p>a</p></td><td><p>b</p></td></tr>
            </table>
            """
        )
        blocks = parse_text_xml(xml)
        text = [p.text for p in blocks[0].versions[0].paragraphs if p.css_class == "table"][0]
        # First row has 2 cells with same value due to colspan expansion
        assert "| wide | wide |" in text


class TestImages:
    def test_image_becomes_markdown_ref(self):
        xml = _wrap(
            '<p class="imagen"><img alt="1" src="/datos/imagenes/disp/2017/296/14334_46947.png"/></p>'
        )
        blocks = parse_text_xml(xml)
        ps = blocks[0].versions[0].paragraphs
        img_ps = [p for p in ps if p.css_class == "image"]
        assert len(img_ps) == 1
        assert (
            img_ps[0].text
            == "![1](https://www.boe.es/datos/imagenes/disp/2017/296/14334_46947.png)"
        )


class TestNotasAndCitas:
    def test_nota_pie_retained(self):
        xml = _wrap(
            """
            <p class="parrafo">Texto vigente.</p>
            <blockquote>
              <p class="nota_pie">Se modifica por el art. 1 de la Ley 1/2015.</p>
            </blockquote>
            """
        )
        blocks = parse_text_xml(xml)
        classes = [p.css_class for p in blocks[0].versions[0].paragraphs]
        assert "nota_pie" in classes

    def test_cita_blockquote_survives(self):
        xml = _wrap(
            """
            <blockquote>
              <p class="cita_con_pleca">Redacción anterior: texto antiguo.</p>
            </blockquote>
            """
        )
        blocks = parse_text_xml(xml)
        classes = [p.css_class for p in blocks[0].versions[0].paragraphs]
        assert "cita_con_pleca" in classes

    def test_plain_paragraph_inside_blockquote_gets_quote_class(self):
        xml = _wrap(
            """
            <blockquote>
              <p class="parrafo">Texto citado literalmente.</p>
            </blockquote>
            """
        )
        blocks = parse_text_xml(xml)
        classes = [p.css_class for p in blocks[0].versions[0].paragraphs]
        # The wrapper retagged it as "cita" so the renderer emits `> ...`
        assert "cita" in classes


class TestHeadings:
    def test_libro_num_and_tit_paired(self):
        xml = _wrap(
            """
            <p class="libro_num">LIBRO PRIMERO</p>
            <p class="libro_tit">De las personas</p>
            """
        )
        blocks = parse_text_xml(xml)
        ps = blocks[0].versions[0].paragraphs
        md = render_paragraphs(ps)
        assert "# LIBRO PRIMERO. De las personas" in md

    def test_anexo_num_and_tit_paired(self):
        xml = _wrap(
            """
            <p class="anexo_num">ANEXO I</p>
            <p class="anexo_tit">Tarifas</p>
            """
        )
        blocks = parse_text_xml(xml)
        md = render_paragraphs(blocks[0].versions[0].paragraphs)
        assert "## ANEXO I. Tarifas" in md


class TestMalformedXml:
    def test_recover_on_ill_formed(self):
        """The parser must not crash on ill-formed BOE XML."""
        xml = b'<?xml version="1.0" encoding="UTF-8"?><texto><bloque id="b1"><version fecha_publicacion="19900101" id_norma="X"><p>Hello <b>world</p></version></bloque></texto>'
        blocks = parse_text_xml(xml)  # must not raise
        assert len(blocks) == 1


class TestDiarioXml:
    """Stage B: parser for /diario_boe/xml.php?id=... (non-consolidated norms)."""

    def test_parses_flat_texto_schema(self):
        from legalize.transformer.xml_parser import parse_diario_xml

        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<documento>"
            "<metadatos>"
            "<identificador>BOE-A-2017-14334</identificador>"
            "<fecha_publicacion>20171206</fecha_publicacion>"
            "</metadatos>"
            "<texto>"
            '<p class="articulo">Artículo 1</p>'
            '<p class="parrafo">Contenido del artículo.</p>'
            "<table><tr><td><p>hola</p></td></tr></table>"
            '<p class="imagen"><img alt="1" src="/datos/imagenes/disp/2017/296/14334_46947.png"/></p>'
            "</texto>"
            "</documento>"
        ).encode("utf-8")
        blocks = parse_diario_xml(xml)
        assert len(blocks) == 1
        v = blocks[0].versions[0]
        assert v.norm_id == "BOE-A-2017-14334"
        assert v.publication_date.isoformat() == "2017-12-06"
        classes = [p.css_class for p in v.paragraphs]
        assert "articulo" in classes
        assert "parrafo" in classes
        assert "table" in classes
        assert "image" in classes
