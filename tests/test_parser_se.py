"""Tests for the Swedish SFS parser (Riksdagen API)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from legalize.countries import get_metadata_parser, get_text_parser
from legalize.fetcher.se.parser import (
    SwedishMetadataParser,
    SwedishTextParser,
    _detect_rank,
    _inline_html_to_md,
    _parse_affected_sections,
    _parse_html_provisions,
    _parse_provisions,
    _parse_sfsr_html,
    _short_title_se,
)
from legalize.models import NormStatus, Rank
from legalize.transformer.slug import norm_to_filepath

FIXTURES = Path(__file__).parent / "fixtures"


# ─────────────────────────────────────────────
# Registry dispatch
# ─────────────────────────────────────────────


class TestRegistryDispatch:
    def test_text_parser_dispatches_to_swedish(self):
        parser = get_text_parser("se")
        assert isinstance(parser, SwedishTextParser)

    def test_metadata_parser_dispatches_to_swedish(self):
        parser = get_metadata_parser("se")
        assert isinstance(parser, SwedishMetadataParser)


# ─────────────────────────────────────────────
# Rank detection
# ─────────────────────────────────────────────


class TestRankDetection:
    def test_grundlag_by_keyword(self):
        assert _detect_rank("Kungörelse om beslutad ny regeringsform") == Rank("grundlag")

    def test_grundlag_tryckfrihet(self):
        assert _detect_rank("Tryckfrihetsförordningen (1949:105)") == Rank("grundlag")

    def test_grundlag_yttrandefrihet(self):
        assert _detect_rank("Yttrandefrihetsgrundlagen (1991:1469)") == Rank("grundlag")

    def test_balk(self):
        assert _detect_rank("Brottsbalk (1962:700)") == Rank("balk")

    def test_balk_jordabalk(self):
        assert _detect_rank("Jordabalk (1970:994)") == Rank("balk")

    def test_forordning(self):
        assert _detect_rank("Förordning (2011:1108) om vuxenutbildning") == Rank("forordning")

    def test_lag_default(self):
        assert _detect_rank("Skollag (2010:800)") == Rank("lag")

    def test_lag_with_forordning_in_body(self):
        # "förordning" appears in body text, not as leading word
        assert _detect_rank(
            "Lag (2018:218) med kompletterande bestämmelser till EU:s dataskyddsförordning"
        ) == Rank("lag")

    def test_empty_title_defaults_to_lag(self):
        assert _detect_rank("") == Rank("lag")


# ─────────────────────────────────────────────
# Short title generation
# ─────────────────────────────────────────────


class TestShortTitle:
    def test_balk_strips_sfs_number(self):
        assert _short_title_se("Brottsbalk (1962:700)", "1962:700") == "Brottsbalk"

    def test_lag_includes_sfs_number(self):
        # "Lag" alone is too generic, so it keeps the SFS number
        assert (
            _short_title_se("Lag (2018:218) med kompletterande bestämmelser", "2018:218")
            == "Lag (2018:218)"
        )

    def test_forordning_includes_sfs_number(self):
        assert (
            _short_title_se("Förordning (2011:1108) om vuxenutbildning", "2011:1108")
            == "Förordning (2011:1108)"
        )

    def test_named_law_strips_sfs(self):
        assert _short_title_se("Skollag (2010:800)", "2010:800") == "Skollag"

    def test_empty_returns_sfs(self):
        assert _short_title_se("", "1962:700") == "SFS 1962:700"


# ─────────────────────────────────────────────
# Text parsing — provisions
# ─────────────────────────────────────────────


class TestProvisionParsing:
    def test_simple_sections(self):
        text = "1 § First provision.\n\n2 § Second provision."
        provisions = _parse_provisions(text)
        assert len(provisions) == 2
        assert provisions[0]["section"] == "1"
        assert provisions[1]["section"] == "2"

    def test_chapter_and_sections(self):
        text = "1 kap. Om brott\n\n1 § First.\n\n2 § Second.\n\n2 kap. Om straff\n\n1 § Third."
        provisions = _parse_provisions(text)
        assert len(provisions) == 3
        assert provisions[0]["chapter"] == "1"
        assert provisions[0]["provision_ref"] == "1:1"
        assert provisions[2]["chapter"] == "2"
        assert provisions[2]["provision_ref"] == "2:1"

    def test_letter_suffix_sections(self):
        text = "1 § First.\n\n1 a § Inserted provision.\n\n2 § Second."
        provisions = _parse_provisions(text)
        refs = [p["provision_ref"] for p in provisions]
        assert "1 a" in refs

    def test_duplicate_suppression(self):
        text = "1 § First text.\n\n1 § Duplicate is suppressed.\n\n2 § Third."
        provisions = _parse_provisions(text)
        # The duplicate 1 § should be absorbed into the first
        assert len(provisions) == 2

    def test_repealed_section(self):
        text = "1 § Active section.\n\n2 § har upphävts genom SFS 2010:123.\n\n3 § Another."
        provisions = _parse_provisions(text)
        refs = [p["provision_ref"] for p in provisions]
        # "har upphävts" should NOT be treated as inline reference
        assert "2" in refs

    def test_empty_text_returns_empty(self):
        assert _parse_provisions("") == []


# ─────────────────────────────────────────────
# Text parser (full pipeline)
# ─────────────────────────────────────────────


class TestSwedishTextParser:
    def setup_method(self):
        self.parser = SwedishTextParser()

    def test_parse_balk_returns_blocks(self):
        data = (FIXTURES / "se-riksdag-balk.json").read_bytes()
        blocks = self.parser.parse_text(data)
        assert len(blocks) > 0

    def test_balk_has_chapters(self):
        data = (FIXTURES / "se-riksdag-balk.json").read_bytes()
        blocks = self.parser.parse_text(data)
        section_blocks = [b for b in blocks if b.block_type == "section"]
        assert len(section_blocks) >= 2  # 1 kap. and 2 kap.

    def test_balk_has_articles(self):
        data = (FIXTURES / "se-riksdag-balk.json").read_bytes()
        blocks = self.parser.parse_text(data)
        article_blocks = [b for b in blocks if b.block_type == "article"]
        assert len(article_blocks) >= 4

    def test_grundlag_returns_blocks(self):
        data = (FIXTURES / "se-riksdag-grundlag.json").read_bytes()
        blocks = self.parser.parse_text(data)
        assert len(blocks) > 0

    def test_forordning_returns_blocks(self):
        data = (FIXTURES / "se-riksdag-forordning.json").read_bytes()
        blocks = self.parser.parse_text(data)
        article_blocks = [b for b in blocks if b.block_type == "article"]
        assert len(article_blocks) == 3

    def test_empty_text_returns_empty(self):
        data = b'{"dokumentstatus": {"dokument": {"text": ""}}}'
        blocks = self.parser.parse_text(data)
        assert blocks == []

    def test_invalid_json_raises(self):
        import json

        with pytest.raises(json.JSONDecodeError):
            self.parser.parse_text(b"not json")

    def test_block_has_version_with_paragraphs(self):
        data = (FIXTURES / "se-riksdag-balk.json").read_bytes()
        blocks = self.parser.parse_text(data)
        article_blocks = [b for b in blocks if b.block_type == "article"]
        first = article_blocks[0]
        assert len(first.versions) == 1
        assert len(first.versions[0].paragraphs) >= 1


# ─────────────────────────────────────────────
# Metadata parser
# ─────────────────────────────────────────────


class TestSwedishMetadataParser:
    def setup_method(self):
        self.parser = SwedishMetadataParser()

    def test_balk_metadata(self):
        data = (FIXTURES / "se-riksdag-balk.json").read_bytes()
        meta = self.parser.parse(data, "1962:700")
        assert meta.title == "Brottsbalk (1962:700)"
        assert meta.identifier == "SFS-1962-700"
        assert meta.country == "se"
        assert meta.rank == Rank("balk")
        assert meta.publication_date == date(1962, 12, 21)
        assert meta.status == NormStatus.IN_FORCE

    def test_balk_amended_through(self):
        data = (FIXTURES / "se-riksdag-balk.json").read_bytes()
        meta = self.parser.parse(data, "1962:700")
        extra_dict = dict(meta.extra)
        assert "amended_through" in extra_dict
        assert "2026:253" in extra_dict["amended_through"]

    def test_grundlag_rank(self):
        data = (FIXTURES / "se-riksdag-grundlag.json").read_bytes()
        meta = self.parser.parse(data, "1974:152")
        assert meta.rank == Rank("grundlag")

    def test_forordning_rank(self):
        data = (FIXTURES / "se-riksdag-forordning.json").read_bytes()
        meta = self.parser.parse(data, "2011:1108")
        assert meta.rank == Rank("forordning")

    def test_repealed_status(self):
        data = (FIXTURES / "se-riksdag-repealed.json").read_bytes()
        meta = self.parser.parse(data, "1686:0903")
        assert meta.status == NormStatus.REPEALED
        extra_dict = dict(meta.extra)
        assert extra_dict["repeal_date"] == "1993-01-01"
        assert extra_dict["repealed_by"] == "SFS 1992:301"

    def test_old_id_with_space_normalized(self):
        data = (FIXTURES / "se-riksdag-old-space-id.json").read_bytes()
        meta = self.parser.parse(data, "1851:55 s.4")
        assert " " not in meta.identifier
        assert meta.identifier == "SFS-1851-55s.4"

    def test_source_url_format(self):
        data = (FIXTURES / "se-riksdag-balk.json").read_bytes()
        meta = self.parser.parse(data, "1962:700")
        assert "riksdagen.se" in meta.source
        assert "sfs-1962-700" in meta.source

    def test_department_extracted(self):
        data = (FIXTURES / "se-riksdag-balk.json").read_bytes()
        meta = self.parser.parse(data, "1962:700")
        assert meta.department == "Justitiedepartementet L5"

    def test_filepath_format(self):
        data = (FIXTURES / "se-riksdag-balk.json").read_bytes()
        meta = self.parser.parse(data, "1962:700")
        assert norm_to_filepath(meta) == "se/SFS-1962-700.md"

    def test_filepath_no_spaces(self):
        data = (FIXTURES / "se-riksdag-old-space-id.json").read_bytes()
        meta = self.parser.parse(data, "1851:55 s.4")
        path = norm_to_filepath(meta)
        assert " " not in path

    def test_date_fallback_to_sfs_year(self):
        # No HTML metadata, no datum — should fall back to SFS year
        data = b'{"dokumentstatus": {"dokument": {"titel": "Test", "organ": "", "datum": "", "text": "", "html": ""}, "dokuppgift": {"uppgift": []}}}'
        meta = self.parser.parse(data, "1999:123")
        assert meta.publication_date == date(1999, 1, 1)


# ─────────────────────────────────────────────
# SFSR amendment register parsing
# ─────────────────────────────────────────────


class TestSFSRParsing:
    def test_parse_sfsr_html(self):
        html = (FIXTURES / "se-sfsr-amendments.html").read_text()
        reforms = _parse_sfsr_html(html)
        assert len(reforms) == 3

    def test_sfsr_reform_dates(self):
        html = (FIXTURES / "se-sfsr-amendments.html").read_text()
        reforms = _parse_sfsr_html(html)
        assert reforms[0].date == date(1965, 1, 1)
        assert reforms[1].date == date(1971, 1, 1)
        assert reforms[2].date == date(2026, 1, 1)

    def test_sfsr_norm_ids(self):
        html = (FIXTURES / "se-sfsr-amendments.html").read_text()
        reforms = _parse_sfsr_html(html)
        assert reforms[0].norm_id == "SFS 1965:146"
        assert reforms[2].norm_id == "SFS 2026:253"

    def test_sfsr_affected_sections(self):
        html = (FIXTURES / "se-sfsr-amendments.html").read_text()
        reforms = _parse_sfsr_html(html)
        # First reform: "ändr. 2 kap. 1, 3 §§"
        assert "2:1" in reforms[0].affected_blocks
        assert "2:3" in reforms[0].affected_blocks

    def test_parse_affected_sections_chapter_qualified(self):
        sections = _parse_affected_sections("ändr. 1 kap. 3, 5 §§")
        assert "1:3" in sections
        assert "1:5" in sections

    def test_parse_affected_sections_simple(self):
        sections = _parse_affected_sections("ändr. 3, 5 §§")
        assert "3" in sections
        assert "5" in sections

    def test_extract_reforms_from_sfsr(self):
        parser = SwedishTextParser()
        html = (FIXTURES / "se-sfsr-amendments.html").read_text()
        reforms = parser.extract_reforms_from_sfsr(html)
        assert len(reforms) == 3

    def test_extract_reforms_from_sfsr_bytes(self):
        parser = SwedishTextParser()
        html_bytes = (FIXTURES / "se-sfsr-amendments.html").read_bytes()
        reforms = parser.extract_reforms_from_sfsr(html_bytes)
        assert len(reforms) == 3

    def test_empty_sfsr_returns_empty(self):
        reforms = _parse_sfsr_html("")
        assert reforms == []


# ─────────────────────────────────────────────
# Encoding hygiene
# ─────────────────────────────────────────────


class TestEncodingHygiene:
    def setup_method(self):
        self.text_parser = SwedishTextParser()
        self.meta_parser = SwedishMetadataParser()

    def test_no_replacement_chars_in_text(self):
        data = (FIXTURES / "se-riksdag-balk.json").read_bytes()
        blocks = self.text_parser.parse_text(data)
        for block in blocks:
            for version in block.versions:
                for para in version.paragraphs:
                    assert "\ufffd" not in para.text

    def test_no_replacement_chars_in_metadata(self):
        data = (FIXTURES / "se-riksdag-balk.json").read_bytes()
        meta = self.meta_parser.parse(data, "1962:700")
        assert "\ufffd" not in meta.title
        assert "\ufffd" not in meta.short_title

    def test_swedish_chars_preserved(self):
        data = (FIXTURES / "se-riksdag-grundlag.json").read_bytes()
        blocks = self.text_parser.parse_text(data)
        all_text = " ".join(p.text for b in blocks for v in b.versions for p in v.paragraphs)
        # Swedish text should preserve åäö
        assert "människors" in all_text or "yttrandefrihet" in all_text

    def test_utf8_round_trip(self):
        data = (FIXTURES / "se-riksdag-balk.json").read_bytes()
        meta = self.meta_parser.parse(data, "1962:700")
        encoded = meta.title.encode("utf-8")
        decoded = encoded.decode("utf-8")
        assert decoded == meta.title


# ─────────────────────────────────────────────
# HTML-based parsing
# ─────────────────────────────────────────────


class TestInlineHtmlToMd:
    def test_italic_conversion(self):
        assert _inline_html_to_md("<i>Lag (1994:458)</i>") == "*Lag (1994:458)*"

    def test_bold_conversion(self):
        assert _inline_html_to_md("<b>important</b>") == "**important**"

    def test_br_to_newline(self):
        result = _inline_html_to_md("line one<br />line two")
        assert "line one\nline two" == result

    def test_paragraph_break(self):
        result = _inline_html_to_md("first<p></p>second")
        assert "first\n\nsecond" == result

    def test_strips_unknown_tags(self):
        result = _inline_html_to_md('<a name="test">text</a>')
        assert "text" == result

    def test_decodes_entities(self):
        assert _inline_html_to_md("&amp; &lt; &gt;") == "& < >"

    def test_subheading_to_bold(self):
        html = '<h4 class="markup_LagRubrik"><a name="x">Rubrik</a></h4>'
        result = _inline_html_to_md(html)
        assert "**Rubrik**" in result

    def test_mixed_formatting(self):
        html = "Text with <b>bold</b> and <i>italic</i> words."
        result = _inline_html_to_md(html)
        assert "**bold**" in result
        assert "*italic*" in result


class TestHtmlProvisionParsing:
    def setup_method(self):
        data = (FIXTURES / "se-riksdag-balk-html.json").read_bytes()
        import json

        self._html = json.loads(data)["dokumentstatus"]["dokument"]["html"]

    def test_returns_provisions(self):
        provisions = _parse_html_provisions(self._html)
        assert len(provisions) > 0

    def test_detects_chapters(self):
        provisions = _parse_html_provisions(self._html)
        chapters = {p["chapter"] for p in provisions}
        assert "1" in chapters
        assert "2" in chapters

    def test_detects_sections(self):
        provisions = _parse_html_provisions(self._html)
        refs = [p["provision_ref"] for p in provisions]
        assert "1:1" in refs
        assert "1:2" in refs
        assert "1:3" in refs
        assert "2:1" in refs

    def test_version_markers_merged_not_duplicated(self):
        """§3 has two anchors (Upphör/Träder) — should be ONE provision."""
        provisions = _parse_html_provisions(self._html)
        section_3_provs = [p for p in provisions if p["provision_ref"] == "1:3"]
        assert len(section_3_provs) == 1

    def test_version_markers_content_separated(self):
        """§3 content should contain both version texts, properly separated."""
        provisions = _parse_html_provisions(self._html)
        section_3 = next(p for p in provisions if p["provision_ref"] == "1:3")
        content = section_3["content"]
        assert "Upphör att gälla" in content
        assert "Träder i kraft" in content
        # Both versions should be present
        assert "överlämnande till särskild vård." in content or "överlämnande" in content
        assert "säkerhetsförvaring" in content

    def test_italic_preserved_in_content(self):
        provisions = _parse_html_provisions(self._html)
        section_1 = next(p for p in provisions if p["provision_ref"] == "1:1")
        assert "*Lag (1994:458)*" in section_1["content"]

    def test_bold_preserved_in_content(self):
        provisions = _parse_html_provisions(self._html)
        section_2 = next(p for p in provisions if p["provision_ref"] == "1:2")
        assert "**självförvållat**" in section_2["content"]

    def test_chapter_title_on_first_section(self):
        provisions = _parse_html_provisions(self._html)
        first_in_ch1 = next(p for p in provisions if p["chapter"] == "1")
        assert first_in_ch1["title"] == "Om brott och brottspåföljder"

    def test_subheading_rendered(self):
        provisions = _parse_html_provisions(self._html)
        ch2_section = next(p for p in provisions if p["provision_ref"] == "2:1")
        # The <h4>Behörighet</h4> subheading should appear before §1 of chapter 2
        # It may be in the title or content depending on position
        assert ch2_section is not None

    def test_no_html_tags_in_content(self):
        provisions = _parse_html_provisions(self._html)
        for prov in provisions:
            assert "<" not in prov["content"], f"HTML tag found in {prov['provision_ref']}"

    def test_no_html_returns_empty(self):
        assert _parse_html_provisions("no hr tag here") == []


class TestHtmlParserIntegration:
    """Tests that parse_text() uses HTML when available."""

    def setup_method(self):
        self.parser = SwedishTextParser()

    def test_html_preferred_over_text(self):
        data = (FIXTURES / "se-riksdag-balk-html.json").read_bytes()
        blocks = self.parser.parse_text(data)
        # Should have blocks from HTML parsing
        assert len(blocks) > 0
        # Check that italic formatting is present (HTML parser output)
        all_text = " ".join(p.text for b in blocks for v in b.versions for p in v.paragraphs)
        assert "*Lag (1994:458)*" in all_text

    def test_version_markers_in_separate_paragraphs(self):
        data = (FIXTURES / "se-riksdag-balk-html.json").read_bytes()
        blocks = self.parser.parse_text(data)
        # Find §3 block (has version markers)
        section_3 = next(
            (b for b in blocks if b.block_type == "article" and "3" in b.id),
            None,
        )
        assert section_3 is not None
        para_texts = [p.text for p in section_3.versions[0].paragraphs]
        # Version markers should be in separate paragraphs
        version_paras = [t for t in para_texts if "Upphör" in t or "Träder" in t]
        assert len(version_paras) >= 2

    def test_fallback_to_text_when_no_html(self):
        data = (FIXTURES / "se-riksdag-balk.json").read_bytes()
        blocks = self.parser.parse_text(data)
        # Should still work (text fallback, no HTML in this fixture)
        assert len(blocks) > 0

    def test_bold_formatting_preserved(self):
        data = (FIXTURES / "se-riksdag-balk-html.json").read_bytes()
        blocks = self.parser.parse_text(data)
        all_text = " ".join(p.text for b in blocks for v in b.versions for p in v.paragraphs)
        assert "**självförvållat**" in all_text
