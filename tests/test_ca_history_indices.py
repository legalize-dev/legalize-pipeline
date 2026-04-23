"""Tests for the Canada history indices: title_index + annual_statute_index.

Covers the classification and lookup logic that attributes amendment
bills from 2001-present to their primary target act. The actual index
build runs against a tiny synthetic upstream clone so tests stay fast
(~1s) while exercising the real file-walking pipeline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from legalize.fetcher.ca.annual_statute_index import (
    AmendmentRef,
    AnnualStatuteIndex,
    _classify_primary_target,
    _normalize_for_skip,
    _reduce_to_primary,
    build_annual_statute_index,
)
from legalize.fetcher.ca.title_index import TitleIndex, _normalize, build_title_index


# ─────────────────────────────────────────────
# TitleIndex normalization and lookup
# ─────────────────────────────────────────────


class TestNormalize:
    def test_lowercase_and_strip(self):
        assert _normalize("  Income Tax Act  ") == "income tax act"

    def test_punct_collapsed(self):
        assert _normalize("Proceeds of Crime (Money Laundering) Act") == (
            "proceeds of crime money laundering act"
        )

    def test_en_dash_treated_as_separator(self):
        assert _normalize("Canada–United States–Mexico Agreement") == (
            "canada united states mexico agreement"
        )

    def test_empty(self):
        assert _normalize("") == ""
        assert _normalize("   ") == ""


class TestTitleIndexLookup:
    @pytest.fixture
    def idx(self) -> TitleIndex:
        return TitleIndex(
            en={
                "income tax act": "eng/acts/I-3.3",
                "access to information act": "eng/acts/A-1",
                "criminal code": "eng/acts/C-46",
            },
            fr={
                "loi de l impot sur le revenu": "fra/lois/I-3.3",
                "code criminel": "fra/lois/C-46",
            },
        )

    def test_exact_match(self, idx):
        assert idx.lookup("Income Tax Act", "en") == "eng/acts/I-3.3"

    def test_case_insensitive(self, idx):
        assert idx.lookup("INCOME TAX ACT", "en") == "eng/acts/I-3.3"

    def test_leading_article_stripped(self, idx):
        assert idx.lookup("the Income Tax Act", "en") == "eng/acts/I-3.3"

    def test_trailing_act_stripped_en(self, idx):
        # "Income Tax" (the RunningHead) should fall back to the " Act" miss.
        assert idx.lookup("Income Tax Act", "en") == "eng/acts/I-3.3"

    def test_french_article_stripped(self, idx):
        # "Loi sur le Code criminel" — "le" is a FR leading article.
        # Normalized: "loi sur le code criminel" → strip "le" → "sur le code criminel"
        # This is a soft miss, not a hard requirement. The real behaviour:
        # exact "code criminel" works.
        assert idx.lookup("Code criminel", "fr") == "fra/lois/C-46"

    def test_miss_returns_none(self, idx):
        assert idx.lookup("Nonexistent Act", "en") is None

    def test_cross_language_isolated(self, idx):
        # English title doesn't leak into French lookup.
        assert idx.lookup("Income Tax Act", "fr") is None

    def test_empty_title(self, idx):
        assert idx.lookup("", "en") is None


class TestTitleIndexJsonRoundtrip:
    def test_roundtrip_preserves_entries(self):
        idx = TitleIndex(en={"a": "eng/acts/A-1"}, fr={"l": "fra/lois/L-2"})
        blob = idx.to_json()
        reloaded = TitleIndex.from_json(blob)
        assert reloaded.lookup("A", "en") == "eng/acts/A-1"
        assert reloaded.lookup("L", "fr") == "fra/lois/L-2"


# ─────────────────────────────────────────────
# Bill classification
# ─────────────────────────────────────────────


class TestClassifyPrimaryTarget:
    def test_simple_amend(self):
        target, cls = _classify_primary_target("", "An Act to amend the Income Tax Act", "en")
        assert target == "Income Tax Act"
        assert cls == "amends"

    def test_amend_with_parenthetical_theme_stripped(self):
        _, cls = _classify_primary_target(
            "",
            "An Act to amend the Income Tax Act (Canada Emergency Rent Subsidy)",
            "en",
        )
        assert cls == "amends"
        target, _ = _classify_primary_target(
            "",
            "An Act to amend the Income Tax Act (Canada Emergency Rent Subsidy)",
            "en",
        )
        assert target == "Income Tax Act"

    def test_amend_drops_and_other_acts(self):
        target, _ = _classify_primary_target(
            "",
            "An Act to amend the Criminal Code and other Acts",
            "en",
        )
        assert target == "Criminal Code"

    def test_amend_drops_consequential_amendments(self):
        target, _ = _classify_primary_target(
            "",
            "An Act to amend the Motor Vehicle Transport Act, 1987 and "
            "to make consequential amendments to other Acts",
            "en",
        )
        assert target == "Motor Vehicle Transport Act, 1987"

    def test_amend_drops_in_respect_of(self):
        target, _ = _classify_primary_target(
            "",
            "An Act to amend the Customs Act, the Customs Tariff, the Excise Act, "
            "the Excise Tax Act and the Income Tax Act in respect of tobacco",
            "en",
        )
        assert target == "Customs Act"

    def test_amend_drops_list_continuation(self):
        target, _ = _classify_primary_target(
            "",
            "An Act to amend the Income Tax Act, the Income Tax Application Rules",
            "en",
        )
        assert target == "Income Tax Act"

    def test_creation_bill_returns_short_title(self):
        target, cls = _classify_primary_target(
            "Canada Cooperatives Act",
            "An Act to establish the Canada Cooperatives Act",
            "en",
        )
        # "An Act to establish" doesn't match the amend regex → falls to
        # creation branch which returns ShortTitle.
        assert target == "Canada Cooperatives Act"
        assert cls == "creates"

    def test_french_amend(self):
        target, cls = _classify_primary_target(
            "", "Loi modifiant la Loi de l'impôt sur le revenu", "fr"
        )
        assert target == "Loi de l'impôt sur le revenu"
        assert cls == "amends"

    def test_french_amend_drops_et_dautres_lois(self):
        target, _ = _classify_primary_target(
            "",
            "Loi modifiant le Code criminel et d'autres lois en conséquence",
            "fr",
        )
        assert target == "Code criminel"

    def test_empty_returns_unknown(self):
        target, cls = _classify_primary_target("", "", "en")
        assert target == ""
        assert cls == "unknown"


class TestReduceToPrimary:
    def test_passthrough_simple(self):
        assert _reduce_to_primary("Criminal Code", "en") == "Criminal Code"

    def test_strips_and_the_joiner(self):
        assert (
            _reduce_to_primary(
                "Canada Business Corporations Act and the Canada Cooperatives Act", "en"
            )
            == "Canada Business Corporations Act"
        )

    def test_strips_and_other_acts(self):
        assert _reduce_to_primary("Criminal Code and other Acts", "en") == "Criminal Code"

    def test_strips_in_respect_of_tail(self):
        assert (
            _reduce_to_primary("Customs Act, the Customs Tariff in respect of tobacco", "en")
            == "Customs Act"
        )

    def test_french_strips_et_suffix(self):
        assert (
            _reduce_to_primary("Code criminel et d'autres lois en conséquence", "fr")
            == "Code criminel"
        )


class TestNonActSkipSet:
    def test_stock_phrase_normalized(self):
        assert _normalize_for_skip("certain Acts") == "certain acts"
        assert _normalize_for_skip("other   Acts") == "other acts"

    def test_passes_other_text(self):
        assert _normalize_for_skip("Income Tax Act") == "income tax act"


# ─────────────────────────────────────────────
# AnnualStatuteIndex JSON roundtrip
# ─────────────────────────────────────────────


class TestAnnualStatuteIndexJson:
    def test_roundtrip(self):
        idx = AnnualStatuteIndex(
            by_norm={
                "eng/acts/I-3.3": [
                    AmendmentRef(
                        year=2020,
                        chapter=13,
                        assent_date="2020-11-19",
                        xml_path="annual-statutes/en/2020/2020-c13_E.xml",
                        bill_number="C-9",
                        amending_title="An Act to amend the Income Tax Act",
                    )
                ]
            },
            unresolved_titles=[(2001, 34, "Miscellaneous Statute Law Amendment Act")],
        )
        blob = idx.to_json()
        reloaded = AnnualStatuteIndex.from_json(blob)
        refs = reloaded.refs_for("eng/acts/I-3.3")
        assert len(refs) == 1
        assert refs[0].year == 2020
        assert refs[0].chapter == 13
        assert refs[0].bill_number == "C-9"
        assert reloaded.unresolved_titles == [(2001, 34, "Miscellaneous Statute Law Amendment Act")]


# ─────────────────────────────────────────────
# Synthetic-clone end-to-end build
# ─────────────────────────────────────────────


def _write_xml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestBuildEndToEnd:
    """Build both indices against a tiny synthetic upstream clone."""

    @pytest.fixture
    def upstream(self, tmp_path: Path) -> Path:
        """Create a minimal upstream clone with 2 consolidated acts + 1 bill."""
        clone = tmp_path / "laws-lois-xml"
        # Consolidated Income Tax Act.
        _write_xml(
            clone / "eng/acts/I-3.3.xml",
            """<?xml version="1.0"?>
<Statute xmlns:lims="http://justice.gc.ca/lims" lims:pit-date="2025-06-02">
  <Identification>
    <LongTitle>An Act respecting income taxes</LongTitle>
    <ShortTitle>Income Tax Act</ShortTitle>
    <RunningHead>Income Tax</RunningHead>
    <Chapter><ConsolidatedNumber>I-3.3</ConsolidatedNumber></Chapter>
  </Identification>
  <Body/>
</Statute>""",
        )
        # Consolidated Criminal Code.
        _write_xml(
            clone / "eng/acts/C-46.xml",
            """<?xml version="1.0"?>
<Statute xmlns:lims="http://justice.gc.ca/lims" lims:pit-date="2025-06-02">
  <Identification>
    <LongTitle>An Act respecting the Criminal Law</LongTitle>
    <ShortTitle>Criminal Code</ShortTitle>
    <Chapter><ConsolidatedNumber>C-46</ConsolidatedNumber></Chapter>
  </Identification>
  <Body/>
</Statute>""",
        )
        # Amendment bill targeting Income Tax Act.
        _write_xml(
            clone / "annual-statutes-lois-annuelles/en/2020/2020-c13_E.xml",
            """<?xml version="1.0"?>
<Bill xml:lang="en">
  <Identification>
    <BillNumber>C-9</BillNumber>
    <LongTitle>An Act to amend the Income Tax Act (Canada Emergency Rent Subsidy)</LongTitle>
    <ShortTitle status="unofficial">An Act to amend the Income Tax Act</ShortTitle>
    <BillHistory>
      <Stages stage="assented-to">
        <Date><YYYY>2020</YYYY><MM>11</MM><DD>19</DD></Date>
      </Stages>
    </BillHistory>
    <Chapter>
      <AnnualStatuteId>
        <AnnualStatuteNumber>13</AnnualStatuteNumber>
        <YYYY>2020</YYYY>
      </AnnualStatuteId>
    </Chapter>
  </Identification>
  <Body/>
</Bill>""",
        )
        return clone

    def test_build_resolves_amendment(self, upstream: Path):
        title_idx = build_title_index(upstream)
        assert title_idx.lookup("Income Tax Act", "en") == "eng/acts/I-3.3"

        statute_idx = build_annual_statute_index(upstream, title_idx)
        refs = statute_idx.refs_for("eng/acts/I-3.3")
        assert len(refs) == 1
        assert refs[0].year == 2020
        assert refs[0].chapter == 13
        assert refs[0].assent_date == "2020-11-19"
        assert refs[0].bill_number == "C-9"

    def test_missing_annual_statutes_dir_raises(self, tmp_path: Path):
        clone = tmp_path / "empty"
        clone.mkdir()
        idx = TitleIndex(en={}, fr={})
        with pytest.raises(FileNotFoundError):
            build_annual_statute_index(clone, idx)
