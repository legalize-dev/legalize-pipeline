"""Tests for the Polish ELI API fetcher (parser + metadata + discovery)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from legalize.countries import (
    get_metadata_parser,
    get_text_parser,
    supported_countries,
)
from legalize.fetcher.pl.client import eli_to_norm_id, norm_id_to_eli
from legalize.fetcher.pl.parser import EliMetadataParser, EliTextParser

FIXTURES = Path(__file__).parent / "fixtures" / "pl"


def _marker(norm_id: str, pub_date: str) -> bytes:
    return f"<!--LEGALIZE norm_id={norm_id} pub_date={pub_date}-->\n".encode()


def _load_html(norm_id: str, html_name: str, pub_date: str = "2024-01-01") -> bytes:
    return _marker(norm_id, pub_date) + (FIXTURES / html_name).read_bytes()


class TestCountryDispatch:
    def test_registry_has_pl(self):
        assert "pl" in supported_countries()

    def test_pl_text_parser_class(self):
        parser = get_text_parser("pl")
        assert isinstance(parser, EliTextParser)

    def test_pl_metadata_parser_class(self):
        parser = get_metadata_parser("pl")
        assert isinstance(parser, EliMetadataParser)


class TestNormIdConversion:
    def test_round_trip(self):
        assert norm_id_to_eli("DU-2024-1907") == "DU/2024/1907"
        assert eli_to_norm_id("DU/2024/1907") == "DU-2024-1907"

    def test_invalid_norm_id_raises(self):
        with pytest.raises(ValueError):
            norm_id_to_eli("DU/2024/1907")  # wrong separator
        with pytest.raises(ValueError):
            norm_id_to_eli("DU-2024")  # missing pos


class TestShortUstawa:
    """DU/2024/1976 — a 2-article ratification statute."""

    NORM_ID = "DU-2024-1976"
    HTML = "sample-ustawa-2024-1976.html"

    def test_parses_two_articles(self):
        parser = EliTextParser()
        blocks = parser.parse_text(_load_html(self.NORM_ID, self.HTML, "2024-12-05"))
        assert len(blocks) == 2
        assert all(b.block_type == "article" for b in blocks)
        assert blocks[0].title == "Art. 1."
        assert blocks[1].title == "Art. 2."

    def test_every_block_has_a_version(self):
        parser = EliTextParser()
        blocks = parser.parse_text(_load_html(self.NORM_ID, self.HTML, "2024-12-05"))
        for b in blocks:
            assert b.versions, f"block {b.id} has no versions"
            for v in b.versions:
                assert v.paragraphs, f"version of {b.id} has no paragraphs"


class TestLargeUstawa:
    """DU/2024/1907 — Civil Protection Act, deep hierarchy, cite-boxes, cross-refs."""

    NORM_ID = "DU-2024-1907"
    HTML = "sample-ustawa-protection-2024-1907.html"
    META = "sample-ustawa-protection-2024-1907.meta.json"

    def test_emits_chapters_and_articles(self):
        parser = EliTextParser()
        blocks = parser.parse_text(_load_html(self.NORM_ID, self.HTML, "2024-12-05"))
        types = Counter(b.block_type for b in blocks)
        # Expect 14 chapters (Rozdział 1..14) + many articles
        assert types["chapter"] == 14
        assert types["article"] >= 150

    def test_first_chapter_title(self):
        parser = EliTextParser()
        blocks = parser.parse_text(_load_html(self.NORM_ID, self.HTML, "2024-12-05"))
        first_chapter = next(b for b in blocks if b.block_type == "chapter")
        assert "Rozdział 1" in first_chapter.title
        assert "Przepisy ogólne" in first_chapter.title

    def test_cite_boxes_become_blockquotes(self):
        parser = EliTextParser()
        blocks = parser.parse_text(_load_html(self.NORM_ID, self.HTML, "2024-12-05"))
        all_paras = [p for b in blocks for v in b.versions for p in v.paragraphs]
        blockquotes = [p for p in all_paras if p.text.startswith(">")]
        # The act has 71 cite-boxes per the research doc — expect a substantial count
        assert len(blockquotes) >= 30

    def test_no_control_chars(self):
        parser = EliTextParser()
        blocks = parser.parse_text(_load_html(self.NORM_ID, self.HTML, "2024-12-05"))
        import re

        ctrl = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
        for b in blocks:
            for v in b.versions:
                for p in v.paragraphs:
                    assert not ctrl.search(p.text), f"control char in {b.id}"

    def test_art1_has_all_seven_pint_items(self):
        """Regression test for the lxml id() recycling bug.

        Art. 1 of the Civil Protection Act enumerates exactly 7 items
        (pint_1..pint_7). An earlier version of the parser used a Python
        ``set[int(id(el))]`` to mark consumed xText elements, and CPython
        recycled the id() across iterations as lxml proxies were GC'd,
        causing items 4, 5, 7 to be silently dropped. The fix marks
        elements via an lxml attribute.
        """
        import re

        parser = EliTextParser()
        blocks = parser.parse_text(_load_html(self.NORM_ID, self.HTML, "2024-12-05"))
        art1 = next(b for b in blocks if b.id == "arti_1" and b.block_type == "article")
        paras = list(art1.versions[0].paragraphs)
        markers = set()
        for p in paras:
            m = re.match(r"\s*(\d+)\)", p.text)
            if m:
                markers.add(int(m.group(1)))
        assert markers == {1, 2, 3, 4, 5, 6, 7}, (
            f"Expected pint markers 1..7 in Art. 1, got {sorted(markers)}"
        )

    def test_nested_list_items_not_silently_dropped(self):
        """Sanity check across the whole act: the number of list_item
        paragraphs should be in the same order of magnitude as the source
        enumeration (~1,200 items). The bug dropped it to ~370.
        """
        parser = EliTextParser()
        blocks = parser.parse_text(_load_html(self.NORM_ID, self.HTML, "2024-12-05"))
        all_paras = [p for b in blocks for v in b.versions for p in v.paragraphs]
        list_items = [p for p in all_paras if p.css_class == "list_item"]
        assert len(list_items) >= 1000, (
            f"Too few list_items emitted ({len(list_items)}), "
            "possible regression of the lxml id() recycling bug"
        )

    def test_metadata_parses(self):
        parser = EliMetadataParser()
        data = (FIXTURES / self.META).read_bytes()
        meta = parser.parse(data, self.NORM_ID)
        assert meta.country == "pl"
        assert meta.identifier == self.NORM_ID
        assert meta.rank == "ustawa"
        assert meta.status.value == "in_force"
        assert "SEJM" in meta.department
        assert meta.publication_date.isoformat() == "2024-12-05"
        assert meta.source.endswith("DU/2024/1907")
        # Subjects come from keywords
        assert len(meta.subjects) > 0

    def test_metadata_has_rich_extra(self):
        parser = EliMetadataParser()
        data = (FIXTURES / self.META).read_bytes()
        meta = parser.parse(data, self.NORM_ID)
        extra_keys = {k for k, _ in meta.extra}
        # Sentinel fields that should always be present for DU acts
        assert "eli" in extra_keys
        assert "display_address" in extra_keys
        assert "internal_address" in extra_keys
        assert "publisher" in extra_keys
        assert "entry_into_force" in extra_keys
        # Effective-date comments were present in this fixture's raw JSON
        raw = json.loads(data)
        if raw.get("comments"):
            assert "effective_date_notes" in extra_keys

    def test_keywords_mirrored_into_extra(self):
        """Fix #2: the generic frontmatter renderer does not serialize
        NormMetadata.subjects. The PL parser must mirror the keywords
        list into `extra['keywords']` so they reach the YAML.
        """
        parser = EliMetadataParser()
        data = (FIXTURES / self.META).read_bytes()
        meta = parser.parse(data, self.NORM_ID)
        extra = dict(meta.extra)
        assert "keywords" in extra, "keywords not mirrored into extra"
        # Civil Protection Act has 24 keywords per the fixture
        assert len(extra["keywords"]) > 20

    def test_pdf_url_mirrored_into_extra(self):
        """Fix #2b: pdf_url is captured on NormMetadata but the generic
        renderer ignores it. Mirror into extra.
        """
        parser = EliMetadataParser()
        data = (FIXTURES / self.META).read_bytes()
        meta = parser.parse(data, self.NORM_ID)
        extra = dict(meta.extra)
        assert "pdf_url" in extra
        assert extra["pdf_url"].startswith("https://api.sejm.gov.pl/eli/acts/DU/2024/1907")
        assert extra["pdf_url"].endswith("/text.pdf")

    def test_bool_serialized_as_lowercase(self):
        """Fix #3: bool values must render as 'true'/'false', not
        Python's 'True'/'False' repr.
        """
        parser = EliMetadataParser()
        data = (FIXTURES / self.META).read_bytes()
        meta = parser.parse(data, self.NORM_ID)
        extra = dict(meta.extra)
        assert extra.get("has_pdf") == "true"


class TestRozporzadzenieWithTables:
    """DU/2024/1977 — Health Ministry regulation with annex tables."""

    NORM_ID = "DU-2024-1977"
    HTML = "sample-rozporzadzenie-tables-2024-1977.html"
    META = "sample-rozporzadzenie-tables-2024-1977.meta.json"

    def test_parses_paragraphs_and_annex(self):
        parser = EliTextParser()
        blocks = parser.parse_text(_load_html(self.NORM_ID, self.HTML, "2024-12-30"))
        types = Counter(b.block_type for b in blocks)
        assert types["article"] == 2  # § 1 and § 2
        assert types["annex"] >= 1

    def test_annex_contains_markdown_table(self):
        parser = EliTextParser()
        blocks = parser.parse_text(_load_html(self.NORM_ID, self.HTML, "2024-12-30"))
        annex_blocks = [b for b in blocks if b.block_type == "annex"]
        assert annex_blocks, "no annex block emitted"
        table_paragraphs = [
            p
            for b in annex_blocks
            for v in b.versions
            for p in v.paragraphs
            if p.css_class == "table"
        ]
        assert table_paragraphs, "no table paragraph emitted"
        first = table_paragraphs[0].text
        # Valid Markdown pipe table has header row + separator row
        lines = first.splitlines()
        assert lines[0].startswith("|")
        assert lines[1].startswith("|") and "---" in lines[1]

    def test_rank_is_rozporzadzenie(self):
        parser = EliMetadataParser()
        data = (FIXTURES / self.META).read_bytes()
        meta = parser.parse(data, self.NORM_ID)
        assert meta.rank == "rozporzadzenie"


class TestRozporzadzenieSimple:
    """DU/2024/1984 — control regulation, no tables.

    Structure: part heading "Treść rozporządzenia" + podstawa prawna preamble
    + § 1 + § 2. Four blocks total.
    """

    NORM_ID = "DU-2024-1984"
    HTML = "sample-rozporzadzenie-simple-2024-1984.html"
    META = "sample-rozporzadzenie-simple-2024-1984.meta.json"

    def test_emits_part_heading_preamble_and_two_paragraphs(self):
        parser = EliTextParser()
        blocks = parser.parse_text(_load_html(self.NORM_ID, self.HTML, "2024-12-30"))
        types = Counter(b.block_type for b in blocks)
        assert types["part"] == 1  # "Treść rozporządzenia"
        assert types["preamble"] == 1  # "Na podstawie art. 48 ust. 2 ustawy..."
        assert types["article"] == 2  # § 1 and § 2

    def test_podstawa_prawna_captured_as_preamble(self):
        """The Sejm HTML puts the ``podstawa prawna`` (legal basis) as an
        xText directly under div.block without any unit wrapper. Ensure we
        still capture it as a preamble block.
        """
        parser = EliTextParser()
        blocks = parser.parse_text(_load_html(self.NORM_ID, self.HTML, "2024-12-30"))
        preambles = [b for b in blocks if b.block_type == "preamble"]
        assert len(preambles) == 1
        text = preambles[0].versions[0].paragraphs[0].text
        assert "Na podstawie" in text
        assert "rehabilitacji zawodowej" in text

    def test_no_annex_emitted(self):
        parser = EliTextParser()
        blocks = parser.parse_text(_load_html(self.NORM_ID, self.HTML, "2024-12-30"))
        assert not any(b.block_type == "annex" for b in blocks)


class TestKonstytucjaMetadata:
    """DU/1997/483 — PDF-only Konstytucja metadata smoke test."""

    NORM_ID = "DU-1997-483"
    META = "sample-konstytucja-meta.json"

    def test_rank_special_cased_to_konstytucja(self):
        parser = EliMetadataParser()
        data = (FIXTURES / self.META).read_bytes()
        meta = parser.parse(data, self.NORM_ID)
        # The API reports type="Ustawa" for the Konstytucja; we special-case it.
        assert meta.rank == "konstytucja"
        assert meta.country == "pl"
        assert meta.identifier == self.NORM_ID

    def test_konstytucja_is_pdf_only(self):
        """Document the fact that Konstytucja has no HTML (out of scope for v1)."""
        data = json.loads((FIXTURES / self.META).read_bytes())
        assert data["textHTML"] is False
        assert data["textPDF"] is True


class TestFilesystemSafeIdentifiers:
    def test_no_slashes_or_colons_in_identifiers(self):
        parser = EliMetadataParser()
        for fixture in FIXTURES.glob("*.meta.json"):
            data = fixture.read_bytes()
            eli = json.loads(data).get("ELI", "")
            norm_id = eli_to_norm_id(eli)
            meta = parser.parse(data, norm_id)
            assert "/" not in meta.identifier
            assert ":" not in meta.identifier
            assert " " not in meta.identifier


class TestReformExtraction:
    def test_one_reform_per_act_from_blocks(self):
        """extract_reforms() must yield exactly one Reform per act (bootstrap)."""
        from legalize.transformer.xml_parser import extract_reforms

        parser = EliTextParser()
        blocks = parser.parse_text(
            _load_html("DU-2024-1907", "sample-ustawa-protection-2024-1907.html", "2024-12-05")
        )
        reforms = extract_reforms(blocks)
        # All blocks share (pub_date, norm_id) → exactly one reform
        assert len(reforms) == 1
        assert reforms[0].date.isoformat() == "2024-12-05"


class TestAnnexTopLevelItems:
    """Regression test for the top-level unit_pass bug.

    DU/2023/1963 (Odra river act) has two annexes that are structured as
    flat lists of 123 + 259 = 382 `unit_pass` items directly under
    `div.block`, with no surrounding `unit_arti`. An earlier version of
    the walker classified these as "unknown unit — recurse" and silently
    dropped every single xText inside. The fix emits them as `item` blocks.
    """

    def test_odra_annex_items_all_emitted(self):
        parser = EliTextParser()
        blocks = parser.parse_text(
            _load_html("DU-2023-1963", "sample-ustawa-odra-2023-1963.html", "2023-09-14")
        )
        types = Counter(b.block_type for b in blocks)
        # Two annexes: 123 items in Załącznik 1 + 259 in Załącznik 2
        assert types["item"] >= 382, (
            f"expected at least 382 top-level annex items, got {types.get('item', 0)}"
        )
        # Both annex headings should be emitted as part blocks
        part_blocks = [b for b in blocks if b.block_type == "part"]
        part_titles = " ".join(b.title for b in part_blocks)
        assert "Załącznik" in part_titles, "annex part headings lost"

    def test_odra_annex_item_content_in_markdown(self):
        """Spot-check three items that were dropped in the buggy version."""
        from legalize.transformer.markdown import render_norm_at_date
        from legalize.transformer.xml_parser import extract_reforms

        tp = EliTextParser()
        mp = EliMetadataParser()
        meta_data = (FIXTURES / "sample-ustawa-odra-2023-1963.meta.json").read_bytes()
        meta = mp.parse(meta_data, "DU-2023-1963")
        blocks = tp.parse_text(
            _load_html("DU-2023-1963", "sample-ustawa-odra-2023-1963.html", "2023-09-14")
        )
        reforms = extract_reforms(blocks)
        md = render_norm_at_date(meta, blocks, reforms[0].date, include_all=True)
        # These three concrete items were dropped in the first audit
        assert "Wojcieszów" in md, "Wojcieszów item missing from annex"
        assert "Podgórzyn" in md, "Podgórzyn item missing from annex"
        assert "Sośnicowice" in md, "Sośnicowice item missing from annex"


class TestRenderedMarkdown:
    """End-to-end render checks — guards the fixes from the first quality gate."""

    def test_file_ends_with_single_newline(self):
        """Fix #4: files must end with exactly one newline, not two."""
        from legalize.transformer.markdown import render_norm_at_date
        from legalize.transformer.xml_parser import extract_reforms

        tp = EliTextParser()
        mp = EliMetadataParser()
        meta_data = (FIXTURES / "sample-ustawa-protection-2024-1907.meta.json").read_bytes()
        meta = mp.parse(meta_data, "DU-2024-1907")
        blocks = tp.parse_text(
            _load_html("DU-2024-1907", "sample-ustawa-protection-2024-1907.html", "2024-12-05")
        )
        reforms = extract_reforms(blocks)
        md = render_norm_at_date(meta, blocks, reforms[0].date, include_all=True)
        assert md.endswith("\n"), "file must end with a newline"
        assert not md.endswith("\n\n"), "file must not end with a blank line"

    def test_keywords_appear_in_frontmatter(self):
        """Fix #2: keywords must be serialized in the YAML frontmatter."""
        from legalize.transformer.markdown import render_norm_at_date
        from legalize.transformer.xml_parser import extract_reforms
        import yaml

        tp = EliTextParser()
        mp = EliMetadataParser()
        meta_data = (FIXTURES / "sample-ustawa-protection-2024-1907.meta.json").read_bytes()
        meta = mp.parse(meta_data, "DU-2024-1907")
        blocks = tp.parse_text(
            _load_html("DU-2024-1907", "sample-ustawa-protection-2024-1907.html", "2024-12-05")
        )
        reforms = extract_reforms(blocks)
        md = render_norm_at_date(meta, blocks, reforms[0].date, include_all=True)
        frontmatter = yaml.safe_load(md.split("---")[1])
        assert "keywords" in frontmatter
        assert len(frontmatter["keywords"]) > 20
        # has_pdf must be serialized as a real bool / true, not "True"
        assert frontmatter.get("has_pdf") in (True, "true")


class TestAnnexTablesAllKept:
    """Every top-level annex table becomes a block.

    The annex pass used to remember processed tables by id(); lxml proxies are
    created lazily and CPython reuses their ids, so tables after the first one
    looked processed and were dropped (DU/2024/1466 kept 1 of its 12 tables).
    """

    @staticmethod
    def _doc(n_tables: int) -> bytes:
        quoted = "".join(f"<table><tr><td>q{i}</td></tr></table>" for i in range(5))
        article = (
            '<div class="unit unit_arti" data-id="art_1"><h3>Art. 1.</h3>'
            '<div class="unit-inner"><div class="cite-box"><div class="cite-body">'
            f"{quoted}</div></div></div></div>"
        )
        annexes = "".join(
            f'<div class="part"><h2>Załącznik nr {k}</h2>'
            f"<table><tr><td>A{k}</td><td>B{k}</td></tr></table></div>"
            for k in range(1, n_tables + 1)
        )
        html = (
            '<html><body><div class="parts"><section>'
            f"{article}{annexes}</section></div></body></html>"
        )
        return _marker("DU-2024-1", "2024-01-01") + html.encode()

    def test_all_annex_tables_emitted(self):
        blocks = EliTextParser().parse_text(self._doc(10))
        annex = [b for b in blocks if b.block_type == "annex"]
        assert len(annex) == 10
        tables = [b.versions[0].paragraphs[-1].text for b in annex]
        assert [f"| A{k} | B{k} |" in t for k, t in enumerate(tables, start=1)] == [True] * 10

    def test_quoted_tables_not_emitted_as_annexes(self):
        blocks = EliTextParser().parse_text(self._doc(1))
        annex = [b for b in blocks if b.block_type == "annex"]
        assert len(annex) == 1
        assert not any("q0" in p.text for b in annex for p in b.versions[0].paragraphs)
