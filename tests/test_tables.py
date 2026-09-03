"""The shared table renderer, against the malformed HTML real sources emit."""

from __future__ import annotations

from lxml import html as lxml_html

from legalize.fetcher._tables import render_table


def _text(el) -> str:
    return " ".join(el.itertext()).strip().replace("|", "\\|")


def _render(markup: str) -> str:
    return render_table(lxml_html.fromstring(markup), _text)


class TestMalformedSpans:
    def test_unquoted_rowspan_does_not_kill_the_table(self):
        """DRE writes `rowspan=2>` unquoted, and lxml recovers the rest of the row
        into the attribute value — "2></td><td style='". int() on that used to raise
        out of render_table and take the whole norm with it."""
        el = lxml_html.fromstring("<table><tr><td>A</td><td>B</td></tr></table>")
        el.xpath("//td")[0].set("rowspan", "2></td><td style='")
        rendered = render_table(el, _text)
        assert "A" in rendered and "B" in rendered

    def test_empty_and_junk_spans_default_to_one(self):
        rendered = _render("<table><tr><td colspan=''>A</td><td rowspan='abc'>B</td></tr></table>")
        assert "A" in rendered and "B" in rendered

    def test_absurd_span_is_capped(self):
        """A cell claiming 100,000 columns must not allocate a 100,000-cell row."""
        rendered = _render("<table><tr><td colspan='99999'>A</td></tr></table>")
        assert rendered.count("|") < 4000

    def test_normal_spans_still_expand(self):
        rendered = _render(
            "<table><tr><td colspan='2'>A</td><td>B</td></tr>"
            "<tr><td>C</td><td>D</td><td>E</td></tr></table>"
        )
        assert "A" in rendered and "E" in rendered


class TestTheHeaderRow:
    """Markdown pipe tables need a header; most source tables have none."""

    def test_a_table_without_a_thead_keeps_its_first_row_as_data(self):
        """It used to be promoted into the header, so the row stopped being a
        row: 250 of 543 sampled tables. The BOE's borderless layout tables —
        side-by-side signature blocks — have no header by definition."""
        rendered = _render(
            "<table><tr><td>M.ª ROSA PUIG</td><td>JAUME MATAS</td></tr>"
            "<tr><td>Secretaria</td><td>Presidente</td></tr></table>"
        )
        lines = rendered.splitlines()
        assert lines[0] == "|  |  |"
        assert lines[1] == "| --- | --- |"
        assert "| M.ª ROSA PUIG | JAUME MATAS |" in lines
        assert "| Secretaria | Presidente |" in lines

    def test_a_declared_thead_is_still_the_header(self):
        rendered = _render(
            "<table><thead><tr><th>Zona</th><th>Especie</th></tr></thead>"
            "<tbody><tr><td>CAT1/01</td><td>Bivalvia</td></tr></tbody></table>"
        )
        lines = rendered.splitlines()
        assert lines[0] == "| Zona | Especie |"
        assert lines[2] == "| CAT1/01 | Bivalvia |"


class TestTheCaption:
    def test_a_caption_becomes_the_paragraph_above_the_table(self):
        """23 of 23 sampled captions were dropped — the table's own title."""
        rendered = _render(
            "<table><caption>Tabla I. Valores paramétricos</caption>"
            "<tr><td>A</td><td>B</td></tr></table>"
        )
        assert rendered.startswith("Tabla I. Valores paramétricos\n\n|")

    def test_a_table_without_one_is_unchanged(self):
        assert _render("<table><tr><td>A</td></tr></table>").startswith("|")


class TestNestedTables:
    def test_the_inner_table_does_not_leak_rows_into_the_outer_grid(self):
        """`iter()` walked the whole subtree, so the inner rows were spliced in
        and every outer row padded to the wider of the two."""
        rendered = _render(
            "<table><tr><td>outer</td></tr>"
            "<tr><td><table><tr><td>in-a</td><td>in-b</td></tr></table></td></tr></table>"
        )
        rows = [line for line in rendered.splitlines() if not set(line) <= set("| -")]
        assert len(rows) == 2, rendered
        assert all(row.count("|") == 2 for row in rows), rendered
