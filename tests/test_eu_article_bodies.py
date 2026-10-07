"""EU provisions must survive both OJ and consolidated markup."""

import importlib.util
import re
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from legalize.fetcher.eu.parser import EURLexTextParser
from legalize.transformer.markdown import render_paragraphs

FIXTURES = Path(__file__).parent / "fixtures" / "eu"
_SPEC = importlib.util.spec_from_file_location(
    "check_eu_article_bodies", Path(__file__).parents[1] / "scripts/check_eu_article_bodies.py"
)
metric = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(metric)


def test_replacement_quote_continuations_and_source_drawings():
    source = """<html><body>
    <div id="art_117"><p class="title-article-norm">Article 117</p>
      <p class="norm">The point is replaced by the following:</p>
      <div style="margin-left:36pt;text-indent:-36pt"><p class="norm">‘(12) Replacement.</p></div>
      <p class="list">If the dossier is incomplete, ask for more information.</p></div>
    <div id="art_118"><p class="title-article-norm">Article 118</p>
      <p class="norm">This is outside the quotation.</p></div>
    <div id="art_119"><p class="title-article-norm">Article 119</p>
      <p class="norm">The following paragraph is added:</p>
      <div class="norm"><span class="no-parag">‘4. </span>
        <div class="norm inline-element">The Commission may decide.’.</div></div>
      <p class="norm">This is outside the quotation too.</p></div>
    <p class="list">‘device’ means a medical device.</p>
    <p class="list"><img src="data:image/jpg;base64,AA==" alt="image"/></p>
    <table border="0"><tbody><tr><td><p class="oj-normal">The marking has these proportions:</p>
      <p class="oj-normal"><img src="ce.jpg" alt="CE"/></p></td></tr></tbody></table>
    <p class="oj-ti-grseq-1">10.4.1. Design and manufacture of devices</p>
    <p class="title-gr-seq-level-5">10.4.2. <span class="boldface">Chemical composition</span></p>
    <p class="oj-ti-tbl">CORRELATION TABLE</p>
    <p class="oj-tbl-txt">A source paragraph with another body class.</p>
    <table class="oj-table"><tbody><tr>
      <td><p class="oj-tbl-hdr">Old provision</p></td><td><p class="oj-tbl-hdr">New provision</p></td>
      </tr><tr><td><p class="oj-tbl-txt">1</p></td><td><p class="oj-tbl-txt">2</p></td></tr>
    </tbody></table>Text after the table.
    </body></html>""".encode("utf-8")
    paragraphs = (
        EURLexTextParser()
        .parse_text(source, norm_id="02017R0745-20260719", published_on=date(2026, 7, 19))[0]
        .versions[0]
        .paragraphs
    )
    text = render_paragraphs(paragraphs)
    assert "> If the dossier is incomplete" in text
    assert "> ‘4. The Commission may decide.’." in text
    assert "\nThis is outside the quotation." in text
    assert "\nThis is outside the quotation too." in text
    assert "\n- ‘device’ means a medical device." in text
    assert "Image omitted; see official source" in text
    assert "CELEX:02017R0745-20260719" in text
    assert "The marking has these proportions:" in text
    assert text.count("Image omitted; see official source") == 2
    assert "##### 10.4.1. Design and manufacture of devices" in text
    assert "**10.4.2. Chemical composition**" in text
    assert "##### CORRELATION TABLE" in text
    assert "A source paragraph with another body class." in text
    assert "| Old provision | New provision |\n| --- | --- |\n| 1 | 2 |" in text
    assert "Text after the table." in text


def test_h6_article_subtitle_is_not_a_body():
    assert metric.article_bodies("###### Article 25\n\n**Data protection**\n\n## ANNEX")[0][1] == ""


@pytest.mark.parametrize("format_name", ["cons", "oj"])
@pytest.mark.parametrize("bundled", [False, True])
def test_gdpr_numbered_provisions_survive(format_name, bundled):
    data = (FIXTURES / f"gdpr-articles-5-25-{format_name}.xhtml").read_bytes()
    if bundled:
        root = ET.Element("eurlex-multi-version", {"celex": "32016R0679"})
        version = ET.SubElement(root, "version", {"effective-date": "2016-05-04"})
        version.append(ET.fromstring(data))
        data = ET.tostring(root, encoding="utf-8")
    blocks = EURLexTextParser().parse_text(data, published_on=date(2016, 5, 4))
    paragraphs = blocks[0].versions[0].paragraphs
    articles = metric.article_bodies(render_paragraphs(paragraphs))
    assert [heading for heading, _ in articles] == ["#### Article 5", "#### Article 25"]
    assert len(paragraphs) == 15  # four headings, five provisions, six lettered items
    article5, article25 = (body for _, body in articles)
    assert article5.startswith("1. Personal data shall be:")
    assert re.findall(r"^- \(([a-f])\)", article5, re.M) == list("abcdef")
    assert article5.index("(f)") < article5.index("2. The controller shall be responsible")
    assert re.findall(r"^(\d)\.", article25, re.M) == ["1", "2", "3"]
    assert "pseudonymisation" in article25
    assert "individual's intervention" in article25
    assert article25.endswith("paragraphs\xa01 and 2 of this Article.")
    # OJ and consolidation must retain the same complete text, not just headings.
    oj = EURLexTextParser().parse_text(
        (FIXTURES / "gdpr-articles-5-25-oj.xhtml").read_bytes(), published_on=date(2016, 5, 4)
    )
    expected = render_paragraphs(oj[0].versions[0].paragraphs)
    assert render_paragraphs(paragraphs) == expected


def test_html_fallback_preserves_utf8_and_strips_controls():
    data = (
        '<html><body><div class="norm"><span class="no-parag">2. </span>'
        '<div class="norm inline-element">Café\x00 — <span class="italics">déjà</span>'
        "\x9a vu</div></div></body></html>"
    ).encode("utf-8")
    paragraphs = (
        EURLexTextParser().parse_text(data, published_on=date(2000, 1, 1))[0].versions[0].paragraphs
    )
    assert [(p.css_class, p.text) for p in paragraphs] == [("abs", "2. Café — *déjà* vu")]


def test_nested_oj_tables_keep_every_paragraph_once_in_order():
    # Layout from 32014R1368: nested columns must not hide the outer provision.
    data = b"""<html xmlns="http://www.w3.org/1999/xhtml"><body>
      <div class="eli-container"><div class="eli-subdivision" id="art_1">
        <p class="oj-ti-art">Article 1</p>
        <table border="0"><col width="4%"/><col width="96%"/><tbody><tr>
          <td><p class="oj-normal">(1)</p></td><td>
            <p class="oj-normal">Start</p>
            <table border="0"><col width="4%"/><col width="96%"/><tbody>
              <tr><td><p class="oj-normal">(a)</p></td>
                <td><p class="oj-normal">First</p></td></tr>
              <tr><td><p class="oj-normal">(b)</p></td>
                <td><p class="oj-normal">Second</p></td></tr>
            </tbody></table>
            <p class="oj-ti-art">Article 9</p>
            <p class="oj-normal">After</p>
          </td></tr><tr><td><p class="oj-normal">(2)</p></td>
            <td><p class="oj-normal">End</p></td></tr></tbody></table>
      </div></div></body></html>"""
    paragraphs = (
        EURLexTextParser()
        .parse_text(data, published_on=date(2014, 12, 18))[0]
        .versions[0]
        .paragraphs
    )
    assert [p.text for p in paragraphs] == [
        "Article 1",
        "- (1) Start",
        "- (a) First",
        "- (b) Second",
        "Article 9",
        "After",
        "- (2) End",
    ]
    assert [p.text for p in paragraphs if p.css_class == "h4"] == ["Article 1"]


def test_metric_checks_subtitles_chapter_boundaries_and_eof():
    articles = metric.article_bodies(
        "#### Article\xa01a\n\n##### Subtitle\n\n### CHAPTER II\n\n"
        "Chapter introduction\n\n#### Article 2\n\n##### Subtitle\n\n2. Text\n\n"
        "#### Article 3\n\n##### Reserved\n"
    )
    assert articles == [
        ("#### Article\xa01a", ""),
        ("#### Article 2", "2. Text"),
        ("#### Article 3", ""),
    ]
    # An empty candidate (including reserved provisions) needs source review;
    # the metric itself does not assert that all empty articles are defects.


def test_article_subdivisions_do_not_close_article_and_links_are_resolved():
    source = b"""<html><body><div class="eli-subdivision" id="art_2">
    <p class="title-article-norm">Article 2</p>
    <p class="stitle-article-norm">Determination of dumping</p>
    <p class="title-division-2">A. NORMAL VALUE</p>
    <p class="norm">1. See <a href="#art_5">Article 5</a> and
    <a href="/legal-content/EN/TXT/?uri=CELEX:32016R1036">the original</a>.</p>
    </div></body></html>"""
    blocks = EURLexTextParser().parse_text(source, published_on=date(2016, 6, 30))
    paragraphs = blocks[0].versions[0].paragraphs
    assert [p.css_class for p in paragraphs] == ["h4", "h5", "h5", "abs"]
    assert "(#article-5)" in paragraphs[-1].text
    assert "(https://eur-lex.europa.eu/legal-content/EN/TXT/" in paragraphs[-1].text


def test_title_chapter_section_article_hierarchy_survives():
    source = b"""<html><body>
    <p class="title-division-1">TITLE I</p>
    <p class="title-division-1">CHAPTER I</p>
    <p class="title-division-1">Section 1</p>
    <p class="title-article-norm">Article 1</p>
    <p class="stitle-article-norm">Subtitle</p>
    <p class="norm">1. Body.</p></body></html>"""
    paragraphs = (
        EURLexTextParser()
        .parse_text(source, published_on=date(2014, 3, 28))[0]
        .versions[0]
        .paragraphs
    )
    assert [p.css_class for p in paragraphs] == ["h2", "h3", "h4", "h5", "h6", "abs"]
    assert metric.article_bodies(render_paragraphs(paragraphs)) == [("##### Article 1", "1. Body.")]


def test_amending_table_inline_text_headings_and_table_notes_survive():
    source = """<html><body><p class="oj-ti-art">Article 117</p>
    <table border="0"><col width="4%"/><col width="96%"/><tbody><tr>
    <td><p class="oj-normal">‘(12)</p></td><td><span>First replacement sentence.</span>
    <p class="oj-normal">Second replacement sentence.’</p></td></tr></tbody></table>
    <p class="title-gr-seq-level-3">10.4.1. Design and manufacture</p>
    <p class="title-table">CORRELATION TABLE</p>
    <table border="1"><tbody><tr><td style="font-weight: bold">Code</td>
    <td style="font-weight: bold">Description</td></tr><tr><td>1</td>
    <td>Service<a href="#E0022"><sup>1</sup></a></td></tr>
    <tr><td colspan="2"><div class="tbl-norm"><a id="E0022">(1)</a>
    <p class="inline-element">Official note.</p></div></td></tr></tbody></table>
    </body></html>""".encode("utf-8")
    paragraphs = (
        EURLexTextParser()
        .parse_text(source, published_on=date(2017, 5, 5))[0]
        .versions[0]
        .paragraphs
    )
    text = render_paragraphs(paragraphs)
    assert "> - ‘(12) First replacement sentence." in text
    assert "> Second replacement sentence.’" in text
    assert "##### 10.4.1. Design and manufacture" in text
    assert "CORRELATION TABLE" in text
    assert "| **Code** | **Description** |" in text
    assert "[^E0022]" in text and "[^E0022]: (1) Official note." in text


def test_number_without_intro_does_not_prefix_a_pipe_table():
    from legalize.fetcher.eu.parser import _parse_xhtml_to_paragraphs

    data = b"""<html><body><div class="norm"><span class="no-parag">1.</span>
    <table><tr><th>Category</th><th>Amount</th></tr><tr><td>A</td><td>5</td></tr></table>
    </div></body></html>"""
    paragraphs = _parse_xhtml_to_paragraphs(data)
    assert paragraphs[0].css_class == "abs" and paragraphs[0].text == "1."
    assert paragraphs[1].css_class == "table" and paragraphs[1].text.startswith("|")
