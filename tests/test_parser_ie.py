"""Tests for the Ireland (IE) ISB parser."""

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from legalize.fetcher.ie.parser import (
    ISBTextParser,
    ISBMetadataParser,
    _ParseContext,
    _anchor,
    _inline_text,
)
from legalize.countries import get_text_parser, get_metadata_parser
from lxml import etree

FIXTURES = Path(__file__).parent / "fixtures" / "ie"


class TestISBTextParser:
    """Test ISB XML text parser against fixture files."""

    @pytest.fixture
    def parser(self):
        return ISBTextParser()

    def test_parse_policing_act(self, parser):
        data = (FIXTURES / "sample-policing-2024.xml").read_bytes()
        blocks = parser.parse_text(data)

        assert len(blocks) == 1
        block = blocks[0]
        assert block.id == "full-text"
        assert block.block_type == "document"

        version = block.versions[0]
        assert version.publication_date.year == 2024
        assert version.publication_date.month == 2
        assert version.publication_date.day == 7

        # Should have thousands of paragraphs
        assert len(version.paragraphs) > 4000

    def test_parse_finance_act_tables(self, parser):
        data = (FIXTURES / "sample-finance-2024.xml").read_bytes()
        blocks = parser.parse_text(data)

        assert len(blocks) == 1
        paras = blocks[0].versions[0].paragraphs

        # Finance Act has 12 tables — find pipe tables in output
        table_paras = [p for p in paras if "|" in p.text and p.text.count("|") > 4]
        assert len(table_paras) >= 10, f"Expected >=10 table paragraphs, got {len(table_paras)}"

        # Check that euro symbol is resolved
        euro_paras = [p for p in paras if "\u20ac" in p.text]
        assert len(euro_paras) > 0, "Euro symbol not found in Finance Act"

    def test_parse_finance_act_many_tables(self, parser):
        """Finance Act has 12+ tables with euro symbols."""
        data = (FIXTURES / "sample-finance-2024.xml").read_bytes()
        blocks = parser.parse_text(data)

        assert len(blocks) == 1
        paras = blocks[0].versions[0].paragraphs

        # Finance Act has many paragraphs
        assert len(paras) > 2000

        # Should have many tables (12 in the source XML)
        table_paras = [p for p in paras if "|" in p.text and "---" in p.text]
        assert len(table_paras) >= 10

        # Euro symbol present
        euro_paras = [p for p in paras if "\u20ac" in p.text]
        assert len(euro_paras) > 0, "Euro symbol not found in Finance Act"

    def test_parse_environment_act(self, parser):
        data = (FIXTURES / "sample-environment-2015.xml").read_bytes()
        blocks = parser.parse_text(data)

        assert len(blocks) == 1
        paras = blocks[0].versions[0].paragraphs

        assert len(paras) > 100

        # Check publication date
        version = blocks[0].versions[0]
        assert version.publication_date.year == 2015

    def test_fada_resolution(self, parser):
        """Irish fada characters must be resolved to Unicode."""
        data = (FIXTURES / "sample-policing-2024.xml").read_bytes()
        blocks = parser.parse_text(data)
        all_text = " ".join(p.text for p in blocks[0].versions[0].paragraphs)

        # Síochána contains ifada (í) and afada (á)
        assert "Síochána" in all_text
        # Dáil Éireann contains afada and Efada
        assert "Dáil" in all_text
        assert "Éireann" in all_text

        # No raw entity tags should remain
        assert "<ifada" not in all_text
        assert "<afada" not in all_text
        assert "<efada" not in all_text

    def test_bold_italic_preserved(self, parser):
        data = (FIXTURES / "sample-policing-2024.xml").read_bytes()
        blocks = parser.parse_text(data)
        paras = blocks[0].versions[0].paragraphs

        # Section headings should have bold
        headings = [p for p in paras if p.css_class == "articulo"]
        assert len(headings) > 100
        bold_headings = [h for h in headings if "**" in h.text]
        assert len(bold_headings) > 0

        # Italic cross-references like *section 4*
        italic_paras = [p for p in paras if "*section" in p.text or "*Part" in p.text]
        assert len(italic_paras) > 0

    def test_structure_hierarchy(self, parser):
        data = (FIXTURES / "sample-policing-2024.xml").read_bytes()
        blocks = parser.parse_text(data)
        paras = blocks[0].versions[0].paragraphs

        # Parts → titulo_tit
        parts = [p for p in paras if p.css_class == "titulo_tit"]
        assert len(parts) >= 10  # 10 parts in the act

        # Chapters → capitulo_tit
        chapters = [p for p in paras if p.css_class == "capitulo_tit"]
        assert len(chapters) > 10

        # Sections → articulo
        articles = [p for p in paras if p.css_class == "articulo"]
        assert len(articles) > 200

    def test_no_mojibake(self, parser):
        """No encoding corruption in any fixture."""
        for fixture in FIXTURES.glob("*.xml"):
            data = fixture.read_bytes()
            blocks = parser.parse_text(data)
            if not blocks:
                continue
            all_text = " ".join(p.text for p in blocks[0].versions[0].paragraphs)

            # Common mojibake patterns
            assert "\u00c3\u00a9" not in all_text, f"Mojibake in {fixture.name}"
            assert "\u00e2\u0080" not in all_text, f"Mojibake in {fixture.name}"
            assert "\ufffd" not in all_text, f"Replacement char in {fixture.name}"

    def test_no_raw_xml_tags(self, parser):
        """No raw XML/HTML tags should leak into the output."""
        for fixture in FIXTURES.glob("*.xml"):
            data = fixture.read_bytes()
            blocks = parser.parse_text(data)
            if not blocks:
                continue
            for p in blocks[0].versions[0].paragraphs:
                # Allow pipe tables which have |
                if p.text.startswith("|"):
                    continue
                assert "<p " not in p.text, f"Raw <p> tag in {fixture.name}"
                assert "<sect>" not in p.text, f"Raw <sect> in {fixture.name}"
                assert "<table" not in p.text, f"Raw <table> in {fixture.name}"

    def test_footnotes(self, parser):
        """Footnote markers should be converted to [^N]."""
        data = (FIXTURES / "sample-policing-2024.xml").read_bytes()
        blocks = parser.parse_text(data)
        all_text = " ".join(p.text for p in blocks[0].versions[0].paragraphs)

        assert "[^1]" in all_text, "Footnote marker [^1] not found"

    def test_schedules_in_backmatter(self, parser):
        """Schedules in backmatter must be parsed with tables."""
        data = (FIXTURES / "sample-policing-2024.xml").read_bytes()
        blocks = parser.parse_text(data)
        paras = blocks[0].versions[0].paragraphs

        # Look for schedule headings
        schedule_headings = [
            p for p in paras if "SCHEDULE" in p.text and p.css_class == "titulo_tit"
        ]
        assert len(schedule_headings) >= 2, "Should have at least 2 schedules"

        # Tables from schedules
        table_paras = [p for p in paras if "|" in p.text and "---" in p.text]
        assert len(table_paras) >= 2, "Schedule tables not found"

    def test_filesystem_safe_identifier(self):
        """Norm IDs must not contain filesystem-unsafe characters."""
        test_ids = [
            "IE-2024-act-1",
            "IE-1997-act-39",
            "IE-1937-act-40",
        ]
        unsafe = set(':/\\*?"<>| ')
        for norm_id in test_ids:
            for char in norm_id:
                assert char not in unsafe, f"Unsafe char '{char}' in {norm_id}"


class TestHTMLParser:
    """Test HTML print view parser."""

    @pytest.fixture
    def parser(self):
        return ISBTextParser()

    def test_parse_html_1960_act(self, parser):
        data = (FIXTURES / "sample-criminal-justice-1960.html").read_bytes()
        blocks = parser.parse_text(data)

        assert len(blocks) == 1
        paras = blocks[0].versions[0].paragraphs
        assert len(paras) > 30

        version = blocks[0].versions[0]
        assert version.publication_date.year == 1960
        assert version.publication_date.month == 7

    def test_html_section_headings(self, parser):
        """HTML parser must produce articulo headings with section titles."""
        data = (FIXTURES / "sample-criminal-justice-1960.html").read_bytes()
        blocks = parser.parse_text(data)
        paras = blocks[0].versions[0].paragraphs

        articles = [p for p in paras if p.css_class == "articulo"]
        assert len(articles) > 5
        # Section titles should be present
        titles = [a.text for a in articles]
        assert any("Definitions" in t for t in titles)

    def test_html_bold_preserved(self, parser):
        data = (FIXTURES / "sample-criminal-justice-1960.html").read_bytes()
        blocks = parser.parse_text(data)
        all_text = " ".join(p.text for p in blocks[0].versions[0].paragraphs)

        # Section numbers are bold: **1.**
        assert "**1.**" in all_text

    def test_html_no_raw_tags(self, parser):
        data = (FIXTURES / "sample-criminal-justice-1960.html").read_bytes()
        blocks = parser.parse_text(data)
        for p in blocks[0].versions[0].paragraphs:
            assert "<td" not in p.text
            assert "<tr" not in p.text
            assert "<div" not in p.text

    def test_html_format_detection(self, parser):
        """XML data routes to XML parser, HTML data to HTML parser."""
        xml_data = (FIXTURES / "sample-environment-2015.xml").read_bytes()
        html_data = (FIXTURES / "sample-environment-2015-print.html").read_bytes()

        xml_blocks = parser.parse_text(xml_data)
        html_blocks = parser.parse_text(html_data)

        # Both should produce blocks
        assert len(xml_blocks) == 1
        assert len(html_blocks) == 1

        xml_paras = xml_blocks[0].versions[0].paragraphs
        html_paras = html_blocks[0].versions[0].paragraphs

        # Core body content should be very similar in length
        # (HTML may have slightly more due to preamble)
        assert abs(len(xml_paras) - len(html_paras)) < 50

        # Both should have articulo headings
        xml_articles = [p for p in xml_paras if p.css_class == "articulo"]
        html_articles = [p for p in html_paras if p.css_class == "articulo"]
        assert len(xml_articles) > 20
        assert len(html_articles) > 20
        # Similar number of sections (HTML may detect a few extra
        # due to schedule/annex sections that XML handles differently)
        assert abs(len(xml_articles) - len(html_articles)) < 15

    def test_xml_html_body_text_similarity(self, parser):
        """The plain body text from XML and HTML should be nearly identical."""
        from legalize.transformer.markdown import render_paragraphs

        xml_data = (FIXTURES / "sample-environment-2015.xml").read_bytes()
        html_data = (FIXTURES / "sample-environment-2015-print.html").read_bytes()

        xml_md = render_paragraphs(parser.parse_text(xml_data)[0].versions[0].paragraphs)
        html_md = render_paragraphs(parser.parse_text(html_data)[0].versions[0].paragraphs)

        # Strip headings and compare body text only
        import re

        def body_only(md: str) -> str:
            lines = md.split("\n")
            body = [line for line in lines if line and not line.startswith("#")]
            text = "\n".join(body)
            # Normalize whitespace
            text = re.sub(r"\s+", " ", text).strip()
            return text

        xml_body = body_only(xml_md)
        html_body = body_only(html_md)

        # Calculate similarity (should be >95%)
        from difflib import SequenceMatcher

        ratio = SequenceMatcher(None, xml_body, html_body).ratio()
        assert ratio > 0.95, f"Body text similarity {ratio:.1%} is too low (expected >95%)"


class TestISBMetadataParser:
    """Test metadata parser against Oireachtas API JSON."""

    @pytest.fixture
    def parser(self):
        return ISBMetadataParser()

    def test_fallback_metadata(self, parser):
        """When API returns no results, fallback must work."""
        import json

        data = json.dumps({"results": [], "head": {}}).encode()
        meta = parser.parse(data, "IE-2024-act-1")

        assert meta.identifier == "IE-2024-act-1"
        assert meta.country == "ie"
        assert meta.rank == "act"
        assert meta.publication_date.year == 2024


class TestCountryDispatch:
    """Test that IE is properly registered in the country registry."""

    def test_registry_text_parser(self):
        parser = get_text_parser("ie")
        assert isinstance(parser, ISBTextParser)

    def test_registry_metadata_parser(self):
        parser = get_metadata_parser("ie")
        assert isinstance(parser, ISBMetadataParser)


class TestInlineText:
    """Test the _inline_text helper for entity resolution."""

    def test_fada_entities(self):
        xml = b"<p>S<ifada/>och<afada/>na</p>"
        elem = etree.fromstring(xml)
        result = _inline_text(elem)
        assert result == "Síochána"

    def test_emdash(self):
        xml = b"<p>text<emdash/>more</p>"
        elem = etree.fromstring(xml)
        result = _inline_text(elem)
        assert result == "text\u2014more"

    def test_quotes(self):
        xml = b"<p><odq/>hello<cdq/></p>"
        elem = etree.fromstring(xml)
        result = _inline_text(elem)
        assert result == "\u201chello\u201d"

    def test_bold_inline(self):
        xml = b"<p>this is <b>bold</b> text</p>"
        elem = etree.fromstring(xml)
        result = _inline_text(elem)
        assert result == "this is **bold** text"

    def test_italic_inline(self):
        xml = b"<p>see <i>section 5</i> above</p>"
        elem = etree.fromstring(xml)
        result = _inline_text(elem)
        assert result == "see *section 5* above"

    def test_euro_pound(self):
        xml = b"<p><euro/>100 or <pound/>50</p>"
        elem = etree.fromstring(xml)
        result = _inline_text(elem)
        assert result == "\u20ac100 or \u00a350"


class TestFootnotes:
    """Footnote definitions, and the isolation between documents.

    The definitions used to accumulate in a module-level list. `ie` bootstraps
    with max_workers: 8, so acts published one another's footnotes — the
    sequential tests below all passed while that was true, which is why the
    concurrency one exists.
    """

    def test_definitions_emitted_for_every_marker(self):
        data = (FIXTURES / "sample-finance-2024.xml").read_bytes()
        paragraphs = ISBTextParser().parse_text(data)[0].versions[0].paragraphs
        text = "\n".join(p.text for p in paragraphs)

        markers = {m for m in re.findall(r"\[\^(\w+)\](?!:)", text)}
        definitions = {m for m in re.findall(r"^\[\^(\w+)\]:", text, re.MULTILINE)}

        assert markers, "fixture has no footnote markers"
        assert markers <= definitions, f"markers with no definition: {markers - definitions}"

    def test_definition_does_not_repeat_the_marker(self):
        """ISB prints the number twice: in <marker> and again opening the body."""
        data = (FIXTURES / "sample-finance-2024.xml").read_bytes()
        paragraphs = ISBTextParser().parse_text(data)[0].versions[0].paragraphs

        definitions = [p.text for p in paragraphs if re.match(r"^\[\^\w+\]:", p.text)]
        assert definitions
        for definition in definitions:
            num = re.match(r"^\[\^(\w+)\]:", definition).group(1)
            assert not definition.startswith(f"[^{num}]: ^{num}"), definition

    def test_footnotes_do_not_leak_between_concurrent_documents(self):
        """Two acts parsed at once keep their own footnotes.

        This is the whole point of the per-document context. Run sequentially it
        passes against a module-level accumulator too, so it has to be threaded.
        """
        finance = (FIXTURES / "sample-finance-2024.xml").read_bytes()
        policing = (FIXTURES / "sample-policing-2024.xml").read_bytes()

        def count(which):
            data = finance if which % 2 == 0 else policing
            paragraphs = ISBTextParser().parse_text(data)[0].versions[0].paragraphs
            return len([p for p in paragraphs if re.match(r"^\[\^\w+\]:", p.text)])

        expected = [count(0), count(1)]
        assert expected[0] != expected[1], "fixtures must differ for this to prove anything"

        with ThreadPoolExecutor(max_workers=8) as pool:
            got = list(pool.map(count, range(8)))

        assert got == [expected[i % 2] for i in range(8)]


class TestCrossReferences:
    """<xref> targets. ISB hrefs are fragments into the act ("#SEC4")."""

    def test_links_resolve_to_a_heading_that_exists(self):
        data = (FIXTURES / "sample-environment-2015.xml").read_bytes()
        paragraphs = ISBTextParser().parse_text(data)[0].versions[0].paragraphs

        anchors = {_anchor(p.text) for p in paragraphs if p.css_class in ("articulo", "titulo_tit")}
        links = re.findall(r"\]\(#([^)]+)\)", "\n".join(p.text for p in paragraphs))

        assert links, "fixture has no internal cross-references"
        assert not [t for t in links if t not in anchors], "dead links"

    def test_unknown_target_falls_back_to_plain_text(self):
        """A reference into another act must not become a link to nowhere."""
        xml = b"""<sect id="SEC1"><number>1.</number><title>Only section</title>
        <p>see <xref href="#SEC99">section 99</xref> and
        <xref href="#SEC1">section 1</xref></p></sect>"""
        root = etree.fromstring(xml)
        ctx = _ParseContext(anchors={"SEC1": _anchor("1. Only section")})

        out = _inline_text(root.find("p"), ctx)

        assert "[section 99]" not in out, "unknown target was linked"
        assert "section 99" in out
        assert "[section 1](#1-only-section)" in out

    def test_ambiguous_anchor_is_dropped_rather_than_guessed(self):
        """Two sections rendering one heading would collide — link neither."""
        xml = b"""<act><body>
        <sect id="SEC1"><number>1.</number><title>Same</title>
          <p>see <xref href="#SEC2">that one</xref></p></sect>
        <sect id="SEC2"><number>1.</number><title>Same</title><p>body</p></sect>
        </body></act>"""
        paragraphs = ISBTextParser().parse_text(xml)[0].versions[0].paragraphs

        assert "](#" not in "\n".join(p.text for p in paragraphs)

    def test_anchor_keeps_accents_and_matches_the_heading(self):
        """Irish headings carry fadas; the anchor has to keep them."""
        assert (
            _anchor("8. **Continuation of An Garda Síochána**")
            == "8-continuation-of-an-garda-síochána"
        )
