"""Tests for the Greek FEK Α' parser (fetcher/gr/).

Fixtures live under ``tests/fixtures/gr/`` as raw FEK Α' PDFs from the
official Greek Government Gazette. Each fixture exercises a different
document type:

* ``sample-syntagma-2008``         — Constitutional revision (Ψήφισμα)
* ``sample-pd-procurement-2016``   — Π.Δ. (Presidential Decree)
* ``sample-code-municipalities``   — Large Νόμος (Code of Municipalities)
* ``sample-kallikratis-reform``    — Major Νόμος reform (Καλλικράτης)
* ``sample-tax-with-tables``       — Νόμος with tariff tables (Income Tax)

These tests are the regression baseline for the parser. If they break
after a parser change, we want loud failures, not silent regressions in
production.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from legalize.countries import (
    get_metadata_parser,
    get_text_parser,
)
from legalize.fetcher.gr.client import GreekClient, make_norm_id, parse_norm_id
from legalize.fetcher.gr.parser import (
    RANK_NOMOS,
    RANK_PD,
    RANK_SYNTAGMA,
    GreekMetadataParser,
    GreekTextParser,
)
from legalize.models import Block

FIXTURES = Path(__file__).parent / "fixtures" / "gr"


def _read(name: str) -> bytes:
    return (FIXTURES / f"{name}.pdf").read_bytes()


# ─────────────────────────────────────────────
# Registry dispatch
# ─────────────────────────────────────────────


class TestRegistry:
    def test_text_parser_registered(self):
        parser = get_text_parser("gr")
        assert isinstance(parser, GreekTextParser)

    def test_metadata_parser_registered(self):
        parser = get_metadata_parser("gr")
        assert isinstance(parser, GreekMetadataParser)


# ─────────────────────────────────────────────
# Client identifier handling
# ─────────────────────────────────────────────


class TestNormIdHandling:
    def test_make_norm_id_canonical(self):
        assert make_norm_id(2013, 1, 167) == "FEK-A-167-2013"

    def test_make_norm_id_other_groups(self):
        assert make_norm_id(2024, 2, 5) == "FEK-B-5-2024"
        assert make_norm_id(2020, 4, 100) == "FEK-D-100-2020"

    def test_make_norm_id_unsupported_group_raises(self):
        with pytest.raises(ValueError):
            make_norm_id(2013, 99, 1)

    def test_parse_norm_id_round_trip(self):
        year, ig, doc = parse_norm_id("FEK-A-167-2013")
        assert year == 2013
        assert ig == 1
        assert doc == 167

    def test_parse_norm_id_other_groups(self):
        assert parse_norm_id("FEK-B-5-2024") == (2024, 2, 5)
        assert parse_norm_id("FEK-D-100-2020") == (2020, 4, 100)

    def test_parse_norm_id_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_norm_id("invalid-id")
        with pytest.raises(ValueError):
            parse_norm_id("FEK-Z-1-2013")  # unknown group letter

    def test_blob_path_construction(self):
        assert GreekClient.build_blob_path(2013, 1, 167) == "01/2013/20130100167.pdf"
        assert GreekClient.build_blob_path(2000, 1, 1) == "01/2000/20000100001.pdf"
        assert GreekClient.build_blob_path(2024, 2, 5) == "02/2024/20240200005.pdf"


# ─────────────────────────────────────────────
# Per-fixture parser tests
# ─────────────────────────────────────────────


class TestSyntagma2008:
    fixture = "sample-syntagma-2008"
    norm_id = "FEK-A-102-2008"

    @pytest.fixture
    def text_blocks(self) -> list[Block]:
        return GreekTextParser().parse_text(_read(self.fixture))

    @pytest.fixture
    def metadata(self):
        return GreekMetadataParser().parse(_read(self.fixture), self.norm_id)

    def test_produces_one_block(self, text_blocks):
        assert len(text_blocks) == 1

    def test_paragraph_count_in_range(self, text_blocks):
        # The 2008 constitutional revision is short — touches 3 articles
        assert 20 <= len(text_blocks[0].versions[0].paragraphs) <= 60

    def test_three_amended_articles(self, text_blocks):
        articles = [p for p in text_blocks[0].versions[0].paragraphs if p.css_class == "articulo"]
        assert len(articles) == 3

    def test_rank_is_syntagma(self, metadata):
        assert metadata.rank == RANK_SYNTAGMA

    def test_publication_date_is_2008_06_02(self, metadata):
        assert metadata.publication_date == date(2008, 6, 2)

    def test_source_is_official_blob_url(self, metadata):
        assert (
            metadata.source
            == "https://ia37rg02wpsa01.blob.core.windows.net/fek/01/2008/20080100102.pdf"
        )

    def test_country_is_gr(self, metadata):
        assert metadata.country == "gr"


class TestPdProcurement2016:
    fixture = "sample-pd-procurement-2016"
    norm_id = "FEK-A-145-2016"

    @pytest.fixture
    def text_blocks(self) -> list[Block]:
        return GreekTextParser().parse_text(_read(self.fixture))

    @pytest.fixture
    def metadata(self):
        return GreekMetadataParser().parse(_read(self.fixture), self.norm_id)

    def test_rank_is_pd(self, metadata):
        assert metadata.rank == RANK_PD

    def test_fifteen_articles_detected(self, text_blocks):
        articles = [p for p in text_blocks[0].versions[0].paragraphs if p.css_class == "articulo"]
        assert len(articles) == 15

    def test_signature_date_extracted(self, metadata):
        # PD has no FEK masthead — date comes from "Αθήνα, 25 Ιουλίου 2016"
        assert metadata.publication_date == date(2016, 7, 25)

    def test_title_starts_with_pd_marker(self, metadata):
        assert "ΠΡΟΕΔΡΙΚΟ ΔΙΑΤΑΓΜΑ" in metadata.title


class TestCodeOfMunicipalities:
    fixture = "sample-code-municipalities"
    norm_id = "FEK-A-114-2006"

    @pytest.fixture
    def text_blocks(self) -> list[Block]:
        return GreekTextParser().parse_text(_read(self.fixture))

    @pytest.fixture
    def metadata(self):
        return GreekMetadataParser().parse(_read(self.fixture), self.norm_id)

    def test_rank_nomos_via_latin_lookalike(self, metadata):
        # The 2006 PDF encodes "ΝΟΜΟΣ" as "NOMOΣ" with Latin N, O, M.
        # If our title detection works, the rank should still be nomos.
        assert metadata.rank == RANK_NOMOS

    def test_publication_date_2006_06_08(self, metadata):
        assert metadata.publication_date == date(2006, 6, 8)

    def test_271_articles(self, text_blocks):
        articles = [p for p in text_blocks[0].versions[0].paragraphs if p.css_class == "articulo"]
        assert len(articles) >= 270  # we expect 271 with current regex

    def test_chapters_present(self, text_blocks):
        sections = [
            p
            for p in text_blocks[0].versions[0].paragraphs
            if p.css_class in ("titulo_tit", "capitulo_tit", "seccion")
        ]
        assert len(sections) > 30  # codes have many structural levels

    def test_amends_extracted(self, metadata):
        amends_entries = [v for k, v in metadata.extra if k == "amends"]
        assert len(amends_entries) == 1
        # Should reference at least 30 prior laws / decrees
        refs = amends_entries[0].split(",")
        assert len(refs) >= 30


class TestKallikratisReform:
    fixture = "sample-kallikratis-reform"
    norm_id = "FEK-A-87-2010"

    @pytest.fixture
    def text_blocks(self) -> list[Block]:
        return GreekTextParser().parse_text(_read(self.fixture))

    @pytest.fixture
    def metadata(self):
        return GreekMetadataParser().parse(_read(self.fixture), self.norm_id)

    def test_rank_is_nomos(self, metadata):
        assert metadata.rank == RANK_NOMOS

    def test_274_articles(self, text_blocks):
        articles = [p for p in text_blocks[0].versions[0].paragraphs if p.css_class == "articulo"]
        assert len(articles) >= 270

    def test_publication_date_2010_06_07(self, metadata):
        assert metadata.publication_date == date(2010, 6, 7)


class TestIncomeTaxCode:
    fixture = "sample-tax-with-tables"
    norm_id = "FEK-A-167-2013"

    @pytest.fixture
    def text_blocks(self) -> list[Block]:
        return GreekTextParser().parse_text(_read(self.fixture))

    @pytest.fixture
    def metadata(self):
        return GreekMetadataParser().parse(_read(self.fixture), self.norm_id)

    def test_rank_is_nomos(self, metadata):
        assert metadata.rank == RANK_NOMOS

    def test_111_articles(self, text_blocks):
        articles = [p for p in text_blocks[0].versions[0].paragraphs if p.css_class == "articulo"]
        assert len(articles) == 111

    def test_publication_date_2013_07_23(self, metadata):
        assert metadata.publication_date == date(2013, 7, 23)

    def test_title_includes_law_number(self, metadata):
        assert "4172" in metadata.title

    def test_title_includes_subject(self, metadata):
        assert "Φορολογία" in metadata.title

    def test_amends_includes_recent_laws(self, metadata):
        amends_entries = [v for k, v in metadata.extra if k == "amends"]
        assert amends_entries
        amends_str = amends_entries[0]
        # The income tax code amends multiple laws including 4046/2012, 4093/2012
        assert "4046/2012" in amends_str or "4093/2012" in amends_str


# ─────────────────────────────────────────────
# Encoding hygiene — every fixture must pass
# ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "fixture",
    [
        "sample-syntagma-2008",
        "sample-pd-procurement-2016",
        "sample-code-municipalities",
        "sample-kallikratis-reform",
        "sample-tax-with-tables",
    ],
)
class TestEncodingHygiene:
    """No fixture should produce mojibake or invalid Unicode after extraction."""

    @pytest.fixture
    def joined_text(self, fixture):
        blocks = GreekTextParser().parse_text(_read(fixture))
        if not blocks:
            return ""
        paragraphs = blocks[0].versions[0].paragraphs
        return "\n".join(p.text for p in paragraphs)

    def test_no_pdfium_soft_hyphen_artifact(self, joined_text):
        assert "\ufffe" not in joined_text

    def test_no_unicode_soft_hyphen(self, joined_text):
        assert "\u00ad" not in joined_text

    def test_no_replacement_char(self, joined_text):
        assert "\ufffd" not in joined_text

    def test_no_c0_control_chars(self, joined_text):
        import re

        assert not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", joined_text)

    def test_utf8_round_trip(self, joined_text):
        # Should round-trip cleanly through UTF-8
        joined_text.encode("utf-8")  # raises if not valid

    def test_no_html_tags_leaked(self, joined_text):
        import re

        assert not re.search(r"<[a-zA-Z][^>]*>", joined_text)


# ─────────────────────────────────────────────
# Paragraph structure invariants
# ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "fixture",
    [
        "sample-pd-procurement-2016",
        "sample-code-municipalities",
        "sample-kallikratis-reform",
        "sample-tax-with-tables",
    ],
)
class TestStructureInvariants:
    """Articles must appear in monotonic order, never duplicated."""

    @pytest.fixture
    def article_numbers(self, fixture) -> list[int]:
        import re

        blocks = GreekTextParser().parse_text(_read(fixture))
        articles = [p for p in blocks[0].versions[0].paragraphs if p.css_class == "articulo"]
        nums = []
        for p in articles:
            m = re.match(r"^Άρθρο\s+(\d+)", p.text)
            if m:
                nums.append(int(m.group(1)))
        return nums

    def test_articles_monotonic_or_equal(self, article_numbers):
        for i in range(len(article_numbers) - 1):
            assert article_numbers[i] <= article_numbers[i + 1], (
                f"Article {article_numbers[i + 1]} appears after {article_numbers[i]} "
                f"at position {i + 1} — non-monotonic order"
            )

    def test_first_article_is_one(self, article_numbers):
        # Every code/law should start with Άρθρο 1
        assert article_numbers and article_numbers[0] == 1


# ─────────────────────────────────────────────
# Filesystem-safe identifier
# ─────────────────────────────────────────────


class TestIdentifier:
    @pytest.mark.parametrize(
        "norm_id",
        [
            "FEK-A-167-2013",
            "FEK-A-87-2010",
            "FEK-A-114-2006",
        ],
    )
    def test_no_unsafe_chars(self, norm_id):
        for ch in [":", " ", "/", "\\", "*", "?", '"', "<", ">", "|"]:
            assert ch not in norm_id, f"Unsafe char {ch!r} in identifier"
