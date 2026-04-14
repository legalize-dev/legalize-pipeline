"""Cross-format consistency tests for the EUR-Lex parser.

Verifies that consolidated texts and OJ (Official Journal) texts produce
structurally consistent Markdown output, ensuring clean diffs when
regulations are updated.

11 regulations tested across both formats:
- 5 with BOTH consolidated + OJ text (format parity tests)
- 3 OJ-only (recent regulations without consolidated version yet)
- 3 consolidated-only (from the original fixture batch)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from legalize.fetcher.eu.parser import EURLexTextParser

FIXTURES = Path(__file__).parent / "fixtures" / "eu"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture(scope="module")
def parser() -> EURLexTextParser:
    return EURLexTextParser()


# ─── Helper ────────────────────────────────────────────────────────────────


def _count_types(paras) -> dict[str, int]:
    types: dict[str, int] = {}
    for p in paras:
        types[p.css_class] = types.get(p.css_class, 0) + 1
    return types


def _article_count(paras) -> int:
    return sum(1 for p in paras if p.css_class == "h4" and "Article" in p.text)


def _list_count(paras) -> int:
    return sum(1 for p in paras if p.css_class == "list")


def _chapter_count(paras) -> int:
    return sum(1 for p in paras if p.css_class == "h2")


# ─── Regulations with BOTH formats ─────────────────────────────────────────
# For each: verify both formats produce the same structural categories
# (articles, lists, chapters) and that article headings match.


_BOTH_FORMATS = [
    ("32021R0953", "COVID Cert", 17, 17),  # (celex, name, cons_articles, oj_articles)
    ("32014R0910", "eIDAS", 82, 52),
    ("32022R1925", "DMA", 54, 54),
    ("32015R2120", "Net Neutrality", 11, 10),
    ("32014R0596", "MAR", 41, 39),
]


class TestBothFormats:
    """Regulations available in both consolidated and OJ format."""

    @pytest.mark.parametrize(
        "celex,name,expected_cons_arts,expected_oj_arts",
        _BOTH_FORMATS,
        ids=[x[1] for x in _BOTH_FORMATS],
    )
    def test_both_formats_produce_articles(
        self, parser, celex, name, expected_cons_arts, expected_oj_arts
    ):
        """Both formats should produce article headings (h4)."""
        cons = parser.parse_text(_load(f"{celex}_cons.xhtml"))
        oj = parser.parse_text(_load(f"{celex}_oj.xhtml"))
        cons_arts = _article_count(cons[0].versions[0].paragraphs)
        oj_arts = _article_count(oj[0].versions[0].paragraphs)
        assert cons_arts == expected_cons_arts, f"CONS articles: {cons_arts}"
        assert oj_arts == expected_oj_arts, f"OJ articles: {oj_arts}"

    @pytest.mark.parametrize(
        "celex,name,_ca,_oa",
        _BOTH_FORMATS,
        ids=[x[1] for x in _BOTH_FORMATS],
    )
    def test_both_formats_produce_lists(self, parser, celex, name, _ca, _oa):
        """Both formats should produce list items from numbered provisions."""
        cons = parser.parse_text(_load(f"{celex}_cons.xhtml"))
        oj = parser.parse_text(_load(f"{celex}_oj.xhtml"))
        cons_lists = _list_count(cons[0].versions[0].paragraphs)
        oj_lists = _list_count(oj[0].versions[0].paragraphs)
        assert cons_lists > 0, "Consolidated text should have list items"
        assert oj_lists > 0, "OJ text should have list items"

    @pytest.mark.parametrize(
        "celex,name,_ca,_oa",
        _BOTH_FORMATS,
        ids=[x[1] for x in _BOTH_FORMATS],
    )
    def test_both_formats_have_subtitles(self, parser, celex, name, _ca, _oa):
        """Both formats should produce article subtitles (h5)."""
        cons = parser.parse_text(_load(f"{celex}_cons.xhtml"))
        oj = parser.parse_text(_load(f"{celex}_oj.xhtml"))
        cons_h5 = sum(1 for p in cons[0].versions[0].paragraphs if p.css_class == "h5")
        oj_h5 = sum(1 for p in oj[0].versions[0].paragraphs if p.css_class == "h5")
        assert cons_h5 > 0, "Consolidated text should have article subtitles"
        assert oj_h5 > 0, "OJ text should have article subtitles"

    @pytest.mark.parametrize(
        "celex,name,_ca,_oa",
        _BOTH_FORMATS,
        ids=[x[1] for x in _BOTH_FORMATS],
    )
    def test_article_heading_text_matches(self, parser, celex, name, _ca, _oa):
        """Article heading text should be identical across formats for common articles."""
        cons = parser.parse_text(_load(f"{celex}_cons.xhtml"))
        oj = parser.parse_text(_load(f"{celex}_oj.xhtml"))

        cons_headings = {
            p.text.strip()
            for p in cons[0].versions[0].paragraphs
            if p.css_class == "h4" and "Article" in p.text
        }
        oj_headings = {
            p.text.strip()
            for p in oj[0].versions[0].paragraphs
            if p.css_class == "h4" and "Article" in p.text
        }
        # Most OJ articles should appear in CONS. However, heavily amended
        # regulations (e.g., eIDAS was massively rewritten by eIDAS2) may
        # have many articles renumbered or deleted. We check that at least
        # 60% of OJ articles survive in the consolidated version.
        overlap = oj_headings & cons_headings
        assert len(overlap) / len(oj_headings) >= 0.6, (
            f"Less than 60% of OJ articles found in CONS: "
            f"{len(overlap)}/{len(oj_headings)} ({len(overlap) / len(oj_headings) * 100:.0f}%)"
        )

    @pytest.mark.parametrize(
        "celex,name,_ca,_oa",
        _BOTH_FORMATS,
        ids=[x[1] for x in _BOTH_FORMATS],
    )
    def test_no_raw_html_in_either_format(self, parser, celex, name, _ca, _oa):
        """Neither format should produce raw HTML tags (except <sup>)."""
        for suffix in ("_cons.xhtml", "_oj.xhtml"):
            blocks = parser.parse_text(_load(f"{celex}{suffix}"))
            for p in blocks[0].versions[0].paragraphs:
                cleaned = p.text.replace("<sup>", "").replace("</sup>", "")
                assert "<div" not in cleaned, f"HTML div in {suffix}: {p.text[:80]}"
                assert "<span" not in cleaned, f"HTML span in {suffix}: {p.text[:80]}"
                assert "<table" not in cleaned, f"HTML table in {suffix}: {p.text[:80]}"

    @pytest.mark.parametrize(
        "celex,name,_ca,_oa",
        _BOTH_FORMATS,
        ids=[x[1] for x in _BOTH_FORMATS],
    )
    def test_no_arrow_markers_in_either_format(self, parser, celex, name, _ca, _oa):
        """Modification arrows should not appear in output text."""
        for suffix in ("_cons.xhtml", "_oj.xhtml"):
            blocks = parser.parse_text(_load(f"{celex}{suffix}"))
            for p in blocks[0].versions[0].paragraphs:
                assert "►" not in p.text, f"Arrow in {suffix}: {p.text[:80]}"


# ─── OJ-only regulations ───────────────────────────────────────────────────


_OJ_ONLY = [
    ("32022R2065", "DSA", 93),
    ("32024R1689", "AI Act", 113),
    ("32024R0903", "eIDAS2", 23),
]


class TestOJOnly:
    """Recent regulations available only in OJ format."""

    @pytest.mark.parametrize(
        "celex,name,expected_articles",
        _OJ_ONLY,
        ids=[x[1] for x in _OJ_ONLY],
    )
    def test_oj_produces_articles(self, parser, celex, name, expected_articles):
        suffix = "_oj.xhtml" if (FIXTURES / f"{celex}_oj.xhtml").exists() else ".xhtml"
        blocks = parser.parse_text(_load(f"{celex}{suffix}"))
        arts = _article_count(blocks[0].versions[0].paragraphs)
        assert arts == expected_articles

    @pytest.mark.parametrize(
        "celex,name,_ea",
        _OJ_ONLY,
        ids=[x[1] for x in _OJ_ONLY],
    )
    def test_oj_produces_lists(self, parser, celex, name, _ea):
        suffix = "_oj.xhtml" if (FIXTURES / f"{celex}_oj.xhtml").exists() else ".xhtml"
        blocks = parser.parse_text(_load(f"{celex}{suffix}"))
        lists = _list_count(blocks[0].versions[0].paragraphs)
        assert lists > 10, f"Expected lists in {name}, got {lists}"

    @pytest.mark.parametrize(
        "celex,name,_ea",
        _OJ_ONLY,
        ids=[x[1] for x in _OJ_ONLY],
    )
    def test_oj_produces_chapters(self, parser, celex, name, _ea):
        suffix = "_oj.xhtml" if (FIXTURES / f"{celex}_oj.xhtml").exists() else ".xhtml"
        blocks = parser.parse_text(_load(f"{celex}{suffix}"))
        chapters = _chapter_count(blocks[0].versions[0].paragraphs)
        assert chapters > 0, f"Expected chapter headings in {name}"


# ─── Consolidated-only fixtures ─────────────────────────────────────────────


_CONS_ONLY = [
    ("32016R0679", "GDPR", 99),
    ("32019R2088", "SFDR", 22),
    ("32023R1114", "MiCA", 150),
]


class TestConsOnly:
    """Consolidated regulations from the original fixture batch."""

    @pytest.mark.parametrize(
        "celex,name,expected_articles",
        _CONS_ONLY,
        ids=[x[1] for x in _CONS_ONLY],
    )
    def test_cons_produces_articles(self, parser, celex, name, expected_articles):
        blocks = parser.parse_text(_load(f"{celex}.xhtml"))
        arts = _article_count(blocks[0].versions[0].paragraphs)
        assert arts == expected_articles

    @pytest.mark.parametrize(
        "celex,name,_ea",
        _CONS_ONLY,
        ids=[x[1] for x in _CONS_ONLY],
    )
    def test_cons_produces_lists(self, parser, celex, name, _ea):
        blocks = parser.parse_text(_load(f"{celex}.xhtml"))
        lists = _list_count(blocks[0].versions[0].paragraphs)
        assert lists > 10, f"Expected lists in {name}, got {lists}"
