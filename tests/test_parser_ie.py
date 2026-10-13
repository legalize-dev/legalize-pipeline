"""Tests for the Ireland (IE) ISB parser."""

import re
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from legalize.fetcher.ie.parser import (
    ISBTextParser,
    ISBMetadataParser,
    _ParseContext,
    _anchor,
    _clean_section_number,
    _inline_text,
    _parse_date_from_parts,
    parse_revised_html,
)
from legalize.countries import get_text_parser, get_metadata_parser
from lxml import etree

FIXTURES = Path(__file__).parent / "fixtures" / "ie"


def test_html_images_leave_visible_omissions_but_not_decorative_seals():
    from legalize.fetcher.ie.parser import _html_inline_text
    from lxml import html

    paragraph = html.fromstring(
        '<p>Before<img src="/images/seal.jpg"/> and <img src="/map.png"/>after</p>'
    )
    assert _html_inline_text(paragraph) == "Before and [image omitted]after"


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


class TestConstitutionParser:
    """Test Constitution HTML parser against fixture."""

    @pytest.fixture
    def parser(self):
        return ISBTextParser()

    def test_parse_constitution_produces_blocks(self, parser):
        """Constitution fixture must produce non-empty blocks."""
        data = (FIXTURES / "sample-constitution.html").read_bytes()
        blocks = parser.parse_text(data)

        assert len(blocks) == 1, f"Expected 1 block, got {len(blocks)}"
        paras = blocks[0].versions[0].paragraphs
        assert len(paras) > 0, "Constitution produced 0 paragraphs"

    def test_article_1_present(self, parser):
        """Article 1 text must appear in the output."""
        data = (FIXTURES / "sample-constitution.html").read_bytes()
        blocks = parser.parse_text(data)
        all_text = " ".join(p.text for p in blocks[0].versions[0].paragraphs)

        assert "ARTICLE 1" in all_text or "Article 1" in all_text
        assert "Irish nation" in all_text

    def test_part_headings(self, parser):
        """Part headings (THE NATION, THE STATE, etc.) must appear."""
        data = (FIXTURES / "sample-constitution.html").read_bytes()
        blocks = parser.parse_text(data)
        paras = blocks[0].versions[0].paragraphs

        part_headings = [p for p in paras if p.css_class == "titulo_tit"]
        assert len(part_headings) >= 5, f"Expected >=5 part headings, got {len(part_headings)}"

    def test_article_headings(self, parser):
        """All 50 articles should produce articulo headings."""
        data = (FIXTURES / "sample-constitution.html").read_bytes()
        blocks = parser.parse_text(data)
        paras = blocks[0].versions[0].paragraphs

        articles = [p for p in paras if p.css_class == "articulo"]
        assert len(articles) >= 40, f"Expected >=40 article headings, got {len(articles)}"

    def test_publication_date(self, parser):
        """Publication date should be 1 July 1937 (plebiscite date)."""
        data = (FIXTURES / "sample-constitution.html").read_bytes()
        blocks = parser.parse_text(data)
        version = blocks[0].versions[0]

        assert version.publication_date.year == 1937
        assert version.publication_date.month == 7
        assert version.publication_date.day == 1


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
        assert [p.text for p in xml_articles] == [p.text for p in html_articles]

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
            # HTML supplies external links that the XML does not carry.
            text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
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
        with pytest.raises(ValueError, match="ISB source metadata required"):
            parser.parse(data, "IE-2024-act-1")
        meta = parser.parse(
            (FIXTURES / "sample-appropriation-1922.xml").read_bytes(), "IE-1922-act-3"
        )
        assert meta.identifier == "IE-1922-act-3"
        assert meta.publication_date == date(1922, 12, 20)
        assert meta.source.endswith("/1922/act/3/enacted/en/html")
        assert meta.rank == "act"
        assert meta.publication_date.year == 1922


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
        paragraphs = (
            ISBTextParser().parse_text(xml, published_on=date(2024, 1, 1))[0].versions[0].paragraphs
        )

        assert "](#" not in "\n".join(p.text for p in paragraphs)

    def test_anchor_keeps_accents_and_matches_the_heading(self):
        """Irish headings carry fadas; the anchor has to keep them."""
        assert (
            _anchor("8. **Continuation of An Garda Síochána**")
            == "8-continuation-of-an-garda-síochána"
        )


class TestRevisedSectionNumber:
    """Revised Acts sometimes sends the anchor where the number goes."""

    def test_anchor_forms_are_reduced_to_the_number(self):
        assert _clean_section_number("SEC30N") == "30N"
        assert _clean_section_number(">257E") == "257E"

    def test_ordinary_numbers_are_untouched(self):
        for raw in ("1", "30", "257E", "12A"):
            assert _clean_section_number(raw) == raw

    def test_anything_else_is_left_alone_rather_than_guessed(self):
        """A heading that reads oddly beats one carrying an invented number."""
        for raw in ("Schedule", "SEC", "", "Part II"):
            assert _clean_section_number(raw) == raw


class TestIrelandFidelity:
    def test_finance_unicode_operators_survive(self):
        paragraphs = (
            ISBTextParser()
            .parse_text((FIXTURES / "sample-finance-2024.xml").read_bytes())[0]
            .versions[0]
            .paragraphs
        )
        text = "\n".join(p.text for p in paragraphs)
        assert "A × D/E" in text
        assert "(A – B) /A" in text
        assert text.count("×") == 23

    @pytest.mark.parametrize("value", ["wat", "110000", "D800"])
    def test_invalid_unicode_refuses_silent_data_loss(self, value):
        element = etree.fromstring(f'<p>A <unicode ch="{value}"/> B</p>'.encode())
        with pytest.raises(ValueError, match="Unicode"):
            _inline_text(element)

    @pytest.mark.parametrize(
        "filename", ["sample-appropriation-1922.xml", "sample-appropriation-1922-print.html"]
    )
    def test_early_act_sections_and_schedule_survive(self, filename):
        paragraphs = (
            ISBTextParser().parse_text((FIXTURES / filename).read_bytes())[0].versions[0].paragraphs
        )
        assert [p.text for p in paragraphs if p.css_class == "articulo"] == [
            f"{n}." for n in range(1, 6)
        ]
        text = "\n".join(p.text for p in paragraphs)
        assert "Minister of Finance may issue" in text
        assert "This Act may be cited for all purposes as the Appropriation Act, 1922" in text
        assert "Sums not exceeding" in text
        assert sum(line.startswith("| ---") for line in text.splitlines()) == 1

    def test_constitution_late_articles_preamble_and_boundaries(self):
        paragraphs = (
            ISBTextParser()
            .parse_text((FIXTURES / "sample-constitution.html").read_bytes())[0]
            .versions[0]
            .paragraphs
        )
        text = "\n".join(p.text for p in paragraphs)
        assert "Most Holy Trinity" in text
        assert "vindicate the personal rights" in text
        assert "laws in force in Saorstát Éireann immediately prior" in text
        articles = [p.text for p in paragraphs if p.css_class == "articulo"]
        assert articles == (
            [f"ARTICLE {n}" for n in range(1, 29)]
            + ["ARTICLE 28A"]
            + [f"ARTICLE {n}" for n in range(29, 43)]
            + ["ARTICLE 42A"]
            + [f"ARTICLE {n}" for n in range(43, 51)]
        )
        assert 450 < sum(p.css_class == "parrafo" for p in paragraphs) < 550
        assert "DATE OF SIGNATURE" not in text
        assert "INDEX" not in text

    def test_revised_preserves_preamble_nested_styles_and_live_internal_links(self):
        paragraphs, updated = parse_revised_html(
            (FIXTURES / "sample-adoptive-leave-1995-revised.html").read_bytes()
        )
        text = "\n".join(p.text for p in paragraphs)
        assert updated is not None
        assert "AN ACT TO ENTITLE FEMALE EMPLOYEES" in text
        assert "**3.**" in text
        assert "[section 1](#1-short-title-and-commencement)" in text
        assert "The Adoptive Leave Act 1995 (Extension of Periods of Leave)" in text
        assert "Editorial Notes:" not in text

    def test_revised_tables_schedules_and_nested_wrappers_once(self):
        raw = b"""<html><p>Updated to 12 August 2026</p>
        <div class="body"><section class="part"><div class="title">PART 1</div>
        <section class="chapter"><div class="title">Chapter 2</div>
        <section class="sect" id="SEC1"><div class="number">1</div><div class="title">Scope</div>
        <div class="nested"><p>A <b>bold <i>word</i></b> survives.</p></div>
        <table><tr><td>First</td><td>Second</td></tr><tr><td>3</td><td>4</td></tr></table>
        <div class="annotations"><p>Editorial text</p></div></section></section></section></div>
        <div class="backmatter"><section class="schedule" id="SCHED1"><div class="title">SCHEDULE 1</div>
        <p>Last legal paragraph. See <a href="#SEC1">section 1</a>.</p></section></div></html>"""
        paragraphs, updated = parse_revised_html(raw)
        assert updated == date(2026, 8, 12)
        text = "\n".join(p.text for p in paragraphs)
        assert text.count("First") == 1
        assert "| 3 | 4 |" in text
        assert "SCHEDULE 1" in text
        assert "Last legal paragraph. See [section 1](#1-scope)." in text
        assert "Editorial text" not in text
        assert "**bold *word***" in text
        assert [p.text for p in paragraphs if p.css_class == "capitulo_tit"] == ["Chapter 2"]

    @pytest.mark.parametrize("args", [(31, "February", 2024), (1, "Unknown", 2024)])
    def test_invalid_dates_fail(self, args):
        with pytest.raises(ValueError):
            _parse_date_from_parts(*args)

    def test_missing_enactment_date_requires_source_evidence(self):
        raw = b"<act><body><p>Legal body</p></body></act>"
        with pytest.raises(ValueError, match="no enactment date"):
            ISBTextParser().parse_text(raw)
        blocks = ISBTextParser().parse_text(raw, published_on=date(2024, 1, 2))
        assert blocks[0].versions[0].publication_date == date(2024, 1, 2)

    def test_metadata_must_identify_the_requested_act(self):
        import json

        raw = {
            "results": [
                {
                    "bill": {
                        "act": {
                            "actYear": "2019",
                            "actNo": "38",
                            "shortTitleEn": "Wrong Act",
                            "dateSigned": "2019-11-19",
                        }
                    }
                }
            ]
        }
        parser = ISBMetadataParser()
        with pytest.raises(ValueError, match="different Act"):
            parser.parse(json.dumps(raw).encode(), "IE-2019-act-C38")
        raw["results"][0]["bill"]["act"].update(
            actNo="C38", shortTitleEn="Constitution Amendment", dateSigned="2019-06-11"
        )
        metadata = parser.parse(json.dumps(raw).encode(), "IE-2019-act-C38")
        assert metadata.publication_date == date(2019, 6, 11)
        assert metadata.source.endswith("/2019/ca/38/enacted/en/html")

    def test_statutory_instrument_source_date_and_body(self):
        raw = (FIXTURES / "sample-v04-si-2024-356.html").read_bytes()
        metadata = ISBMetadataParser().parse(raw, "IE-2024-si-356")
        assert metadata.rank == "statutory_instrument"
        # The source distinguishes the published notice from the earlier signature.
        assert metadata.publication_date == date(2024, 8, 2)
        assert dict(metadata.extra)["made_date"] == "2024-07-31"
        assert metadata.source.endswith("/2024/si/356/made/en/html")
        paragraphs = ISBTextParser().parse_text(raw)[0].versions[0].paragraphs
        text = "\n".join(p.text for p in paragraphs)
        assert "The following are repealed:" in text
        assert [p.text for p in paragraphs if p.css_class == "articulo"] == ["1.", "2.", "3.", "4."]
        assert "SCHEDULE" in text
        assert "EAMON RYAN" in text
        assert sum(p.css_class == "legal_quote" and "> | --- |" in p.text for p in paragraphs) == 2

    def test_free_state_constitution_schedule_articles(self):
        raw = (FIXTURES / "sample-v04-isb-1922-act-1.xml").read_bytes()
        paragraphs = ISBTextParser().parse_text(raw)[0].versions[0].paragraphs
        articles = [p.text for p in paragraphs if p.css_class == "articulo"]
        assert articles[:3] == ["1.", "2.", "3."]
        assert "**Article 1.**" in articles
        assert "**Article 83.**" in articles

    def test_constitution_enrollment_does_not_invent_a_reform_date(self):
        from legalize.models import TextState

        metadata = ISBMetadataParser().parse(
            (FIXTURES / "sample-constitution.html").read_bytes(), "IE-1937-constitution"
        )
        assert metadata.text_state is TextState.CURRENT
        assert metadata.publication_date == date(1937, 7, 1)
        assert metadata.last_modified is None
        assert dict(metadata.extra)["enrollment_date"] == "2019-11-13"

    def test_wrong_source_metadata_identity_fails(self):
        raw = (FIXTURES / "sample-appropriation-1922.xml").read_bytes()
        with pytest.raises(ValueError, match="different Act"):
            ISBMetadataParser().parse(raw, "IE-1922-act-1")

    def test_waterworks_early_sections_and_last_schedule_text(self):
        paragraphs = (
            ISBTextParser()
            .parse_text((FIXTURES / "sample-waterworks-1923.xml").read_bytes())[0]
            .versions[0]
            .paragraphs
        )
        assert [p.text for p in paragraphs if p.css_class == "articulo"] == ["1.", "2.", "3."]
        text = "\n".join(p.text for p in paragraphs)
        assert "Provisional Order set out in the Schedule" in text
        assert "Townland of Kiltiernan Domain" in text
        assert "| No. on Plan |" in text

    def test_revised_annotations_inside_titles_and_normative_footnotes(self):
        raw = b"""<html><p>Updated to 18 October 2024</p><div class="body">
        <section class="part"><div class="title"><p>F34[PART 5A Occupier Assisted Valuation]</p>
        <div class="annotations"><p>Annotations</p><p>Amendments: F34 Inserted</p></div></div>
        <section class="sect" id="SEC1"><div class="number">1</div><div class="title">Scope</div>
        <p>A legal reference<sup>1</sup> and m<sup>2</sup>.</p></section>
        <footer><p><sup>1</sup> OJ L277, 27.10.2022, p. 1</p></footer></section></div></html>"""
        paragraphs, _ = parse_revised_html(raw)
        text = "\n".join(p.text for p in paragraphs)
        assert "Annotations" not in text
        assert "Amendments:" not in text
        assert "F34[PART 5A Occupier Assisted Valuation]" in text
        assert "reference[^1] and m^2" in text
        assert text.count("[^1]: OJ L277, 27.10.2022, p. 1") == 1


def test_parliament_metadata_is_preserved_without_treating_resource_uri_as_pdf():
    import json

    bill = {
        "act": {
            "actYear": "2019",
            "actNo": "C38",
            "shortTitleEn": "Constitution Amendment",
            "shortTitleGa": "Bunreacht na hÉireann",
            "dateSigned": "2019-06-11",
        },
        "stages": [{"name": "Seanad", "date": "2019-03-21"}],
        "sponsors": [{"name": "Sponsor", "uri": "https://source.test/member"}],
        "events": [{"type": "Enacted", "date": "2019-06-11"}],
        "relatedDocs": [
            {"relatedDoc": {"docType": "memorandum", "uri": "https://source.test/doc"}}
        ],
        "versions": [{"version": {"docType": "act", "uri": "https://source.test/act/enacted"}}],
    }
    parser = ISBMetadataParser()
    raw = json.dumps({"results": [{"bill": bill}]}).encode()
    metadata = parser.parse(raw, "IE-2019-act-C38")
    extra = dict(metadata.extra)
    assert extra["official_number"] == "C38"
    assert extra["year"] == "2019"
    assert extra["enactment_date"] == "2019-06-11"
    assert json.loads(extra["parliament_metadata"]) == bill
    assert "Éireann" in extra["parliament_metadata"]
    assert metadata.pdf_url is None
    bill["versions"][0]["version"]["formats"] = {"pdf": {"uri": "https://source.test/act.pdf"}}
    metadata = parser.parse(json.dumps({"results": [{"bill": bill}]}).encode(), "IE-2019-act-C38")
    assert metadata.pdf_url == "https://source.test/act.pdf"
    bill["versions"].insert(
        0,
        {
            "version": {
                "docType": "bill",
                "formats": {"pdf": {"uri": "https://source.test/draft.pdf"}},
            }
        },
    )
    metadata = parser.parse(json.dumps({"results": [{"bill": bill}]}).encode(), "IE-2019-act-C38")
    assert metadata.pdf_url == "https://source.test/act.pdf"


def test_xml_source_metadata_retains_all_fields_with_normalized_names():
    raw = b"""<act><metadata><title>Original Act</title><number>3</number><year>1922</year>
    <dateofenactment>19221220</dateofenactment><sourceNote>Official note</sourceNote>
    </metadata><body><p>Legal text</p></body></act>"""
    metadata = ISBMetadataParser().parse(raw, "IE-1922-act-3")
    assert metadata.title == "Original Act"
    assert metadata.publication_date == date(1922, 12, 20)
    assert dict(metadata.extra) == {
        "official_number": "3",
        "year": "1922",
        "enactment_date": "1922-12-20",
        "source_note": "Official note",
        "publication_date_basis": "isb_enactment_date",
    }


def test_statutory_instrument_ordinal_signature_under_government_seal():
    raw = (FIXTURES / "sample-v04-si-1997-297.html").read_bytes()
    metadata = ISBMetadataParser().parse(raw, "IE-1997-si-297")
    assert metadata.publication_date == date(1997, 7, 8)
    assert dict(metadata.extra)["made_date"] == "1997-07-08"
    paragraphs = ISBTextParser().parse_text(raw)[0].versions[0].paragraphs
    assert any(
        "Official Seal of the Government, this 8th day of July, 1997" in p.text for p in paragraphs
    )
    assert any("BERTIE AHERN" in p.text for p in paragraphs)
    missing_signature = raw.replace(
        b"Given under the Official Seal of the Government, this 8th day of July, 1997.", b""
    )
    with pytest.raises(ValueError, match="lacks its title or enactment date"):
        ISBMetadataParser().parse(missing_signature, "IE-1997-si-297")


@pytest.mark.parametrize(
    ("identifier", "expected", "signatures"),
    [
        ("IE-1997-si-118", date(1997, 3, 11), '["1996-07-23", "1997-03-11"]'),
        ("IE-1999-si-440", date(1999, 12, 24), None),
        ("IE-2001-si-30", date(2001, 2, 8), None),
        ("IE-2001-si-510", date(2001, 11, 15), '["2001-10-26", "2001-11-15"]'),
        ("IE-2003-si-155", date(2003, 3, 18), None),
    ],
)
def test_instrument_signature_variants_and_later_ministerial_concurrence(
    identifier, expected, signatures
):
    raw = (FIXTURES / f"sample-v04-{identifier[3:]}.html").read_bytes()
    metadata = ISBMetadataParser().parse(raw, identifier)
    assert metadata.publication_date == expected
    assert dict(metadata.extra)["made_date"] == expected.isoformat()
    assert "enactment_date" not in dict(metadata.extra)
    assert dict(metadata.extra).get("signature_dates") == signatures
    text = ISBTextParser().parse_text(raw)
    assert text[0].versions[0].publication_date == expected
    if identifier == "IE-2003-si-155":
        body = "\n".join(p.text for p in text[0].versions[0].paragraphs)
        assert "2003[^1]" in body
        assert "[^1]: O.J. No. L 69 of 13.3.2003, p.29." in body


def test_metadata_envelope_rejects_wrong_parliamentary_identity():
    import base64
    import json

    raw = (FIXTURES / "sample-v04-isb-1922-act-1.xml").read_bytes()
    envelope = {
        "legalize_ie_metadata": 1,
        "enacted": base64.b64encode(raw).decode(),
        "parliament": {"results": [{"bill": {"act": {"actYear": "1922", "actNo": "2"}}}]},
    }
    with pytest.raises(ValueError, match="different Act"):
        ISBMetadataParser().parse(json.dumps(envelope).encode(), "IE-1922-act-1")


def test_instrument_publication_date_basis_distinguishes_gazette_and_signature():
    parser = ISBMetadataParser()
    gazette = parser.parse(
        (FIXTURES / "sample-v04-si-2024-356.html").read_bytes(), "IE-2024-si-356"
    )
    signed = parser.parse((FIXTURES / "sample-v04-si-1997-297.html").read_bytes(), "IE-1997-si-297")
    assert dict(gazette.extra)["publication_date_basis"] == "gazette_notice"
    assert dict(gazette.extra)["made_date"] == "2024-07-31"
    assert gazette.publication_date == date(2024, 8, 2)
    assert dict(signed.extra)["publication_date_basis"] == "final_signature"
    assert signed.publication_date == date(1997, 7, 8)


def _render_fixture(name):
    from legalize.transformer.markdown import render_paragraphs

    paragraphs = (
        ISBTextParser().parse_text((FIXTURES / name).read_bytes())[0].versions[0].paragraphs
    )
    return render_paragraphs(paragraphs)


def test_constitution_declarations_are_quotes_and_lettered_provisions_are_lists():
    text = _render_fixture("sample-constitution.html")
    assert text.count('> "In the presence of Almighty God') == 3
    assert "\n- (a) is, in the case of a Bill" in text
    assert "\n- (b) is, in the case of a Money Bill" in text
    assert text.count("###### ARTICLE") == 52


def test_early_constitution_annex_oaths_and_treaty_signatories_keep_roles():
    text = _render_fixture("sample-v04-isb-1922-act-1.xml")
    assert text.count("> I _") == 2
    assert "\n## ANNEX.\n" in text
    assert "\n#### DOCKYARD PORT AT BEREHAVEN.\n" in text
    assert "\n- (*a*) Admiralty property" in text
    assert "| **D. LLOYD GEORGE.** | **ART O GRÍOBHTHA** |" in text
    assert "| **GORDON HEWART.** | **DHUBHTHAIGH.** |" in text
    assert "| December 6, 1921. |  |" in text


def test_finance_replacement_quotes_preserve_nested_labels_and_formula_characters():
    text = _render_fixture("sample-finance-2024.xml")
    assert "\n  > - “(4A)\n  >     - (a) For the purposes" in text
    assert "\n  >         - (i) where the number of days" in text
    assert "\n  >         - (ii) where the number of days" in text
    assert "\n    - (ii) by the substitution of the following definition" in text
    assert "\n  >     - (III) the qualifying period" in text
    for formula in ("A - B", "A × D/E", "B × D/E", "F × G/H", "F × I/J"):
        assert re.search(r"> +" + re.escape(formula) + r"\n", text)
    assert len(re.findall(r"^\[\^\d+\]:", text, re.M)) == 35
    assert len(re.findall(r"^###### ", text, re.M)) == 118


def test_private_act_inline_substitutions_do_not_become_blockquotes():
    text = _render_fixture("sample-v04-isb-private-2023-act-1.xml")
    assert len(re.findall(r"^- \([ab]\)", text, re.M)) == 8
    assert not re.search(r"^\s*>", text, re.M)
    assert "“Painters, Sculptors, Architects and Printmakers”" in text


def test_instrument_inserted_schedule_notes_quotes_and_signature_are_distinct():
    text = _render_fixture("sample-v04-si-2024-356.html")
    assert "\n## SCHEDULE\n\n> ### “SCHEDULE 7\n" in text
    assert "      > “‘Directive’ means Directive" in text
    assert "\n    - (ii) by substituting for the definition" in text
    assert "\n  > *“Offences*\n" in text
    assert "\n  > 27A. (1)" in text
    assert "\n  >     - (i) if the alleged offence" in text
    assert "\n**EAMON RYAN,**\n" in text
    assert text.count("\n- • ") == 3
    assert text.count("[^1]: OJ No. L143, 30.4.2004, p. 87") == 1
    assert text.count("[^2]: OJ No. L 304, 20.11.2010, p. 18") == 1
    assert text.count("2004[^1]") == text.count("2010[^2]") == 2
    assert not re.search(r"\^\d+(?!\])", text)
    assert re.findall(r"^###### (.+)$", text, re.M) == ["1.", "2.", "3.", "4."]
    assert sum(line.startswith("> | --- |") for line in text.splitlines()) == 2


def test_older_instrument_asterisk_notes_use_explicit_return_anchors():
    text = _render_fixture("sample-v04-2001-si-510.html")
    assert text.count("[^star1]: Postal address in full") == 1
    assert text.count("[^star2]: This declaration to be made") == 1
    assert text.count("at[^star1]") == 2
    assert "STATUTORY DECLARATION OF SERVICE[^star2]" in text


def test_conflicting_html_footnote_definition_is_rejected():
    data = (FIXTURES / "sample-v04-si-2024-356.html").read_bytes()
    data = data.replace(b"OJ No. L143, 30.4.2004, p. 87", b"Different reference", 1)
    with pytest.raises(ValueError, match="Conflicting ISB HTML footnote 1"):
        ISBTextParser().parse_text(data)


def test_legal_layout_keeps_every_source_word_and_punctuation():
    from legalize.fetcher.ie.parser import _legal_format
    from legalize.models import Paragraph

    source = [
        Paragraph("parrafo", "(a) insert the following:"),
        Paragraph("parrafo", "“(4A) (a) A - B, where—"),
        Paragraph("parrafo", "(i) A × D/E;"),
        Paragraph("parrafo", "and"),
        Paragraph("parrafo", "(ii) B × D/E.”,"),
        Paragraph("parrafo", "(b) substitute ‘text’ for ‘word’."),
    ]
    formatted = _legal_format(source)
    # Strip only the added line prefixes: all original symbols must be unchanged.
    stripped = [re.sub(r"(?m)^\s*(?:> )?\s*(?:- )?", "", p.text) for p in formatted]
    assert [" ".join(text.split()) for text in stripped] == [p.text for p in source]
    assert formatted[-1].text == "- (b) substitute ‘text’ for ‘word’."


@pytest.mark.parametrize(
    "fixture",
    [
        "sample-constitution.html",
        "sample-v04-isb-1922-act-1.xml",
        "sample-finance-2024.xml",
        "sample-v04-isb-private-2023-act-1.xml",
        "sample-v04-si-2024-356.html",
    ],
)
def test_legal_lists_and_quotes_render_as_legal_content_not_code(fixture):
    from markdown_it import MarkdownIt

    text = _render_fixture(fixture)
    tokens = MarkdownIt("commonmark").parse(text)
    assert not [token.content for token in tokens if token.type in ("code_block", "fence")]


def test_legal_quote_container_is_opt_in_and_legacy_quote_bytes_do_not_change():
    from legalize.models import Paragraph
    from legalize.transformer.markdown import render_paragraphs

    legacy = [Paragraph("cita", "First paragraph."), Paragraph("cita", "Second paragraph.")]
    assert render_paragraphs(legacy) == "> First paragraph.\n\n> Second paragraph.\n"
    legal = [
        Paragraph("legal_quote", "> - (1) Parent."),
        Paragraph("legal_quote", ">     - (a) Child."),
    ]
    assert render_paragraphs(legal) == "> - (1) Parent.\n>\n>     - (a) Child.\n"


def test_instrument_signature_ordinal_period_does_not_select_commencement():
    raw = (FIXTURES / "sample-v04-1979-si-63.html").read_bytes()
    metadata = ISBMetadataParser().parse(raw, "IE-1979-si-63")
    assert metadata.title == "S.I. No. 63/1979 - Value-Added Tax Regulations, 1979."
    assert metadata.publication_date == date(1979, 2, 27)
    assert dict(metadata.extra)["made_date"] == "1979-02-27"
    assert dict(metadata.extra)["publication_date_basis"] == "final_signature"
    # Regulation 1 commences on 1 March; both dated signatures are 27 February.
    text = ISBTextParser().parse_text(raw)
    assert text[0].versions[0].publication_date == date(1979, 2, 27)
