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
