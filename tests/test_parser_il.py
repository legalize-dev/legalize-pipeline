"""Tests for Israel fetcher, parser, and date helper components (il)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from legalize.fetcher.il.client import (
    IsraelClient,
    _document_priority,
    clean_extracted_text,
    is_visual_hebrew,
    reverse_visual_line,
    is_reblaze_content,
)
from legalize.fetcher.il.dates_il import hebrew_year_to_gregorian, parse_gregorian_date
from legalize.fetcher.il.parser import IsraelMetadataParser, IsraelTextParser
from legalize.models import NormStatus

FIXTURES = Path(__file__).parent / "fixtures" / "il"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ─────────────────────────────────────────────
# Hebrew Date parsing & Gematria Tests
# ─────────────────────────────────────────────


class TestHebrewDates:
    def test_gematria_years(self):
        assert hebrew_year_to_gregorian('התש"י') == 1950
        assert hebrew_year_to_gregorian('התשמ"ב') == 1982
        assert hebrew_year_to_gregorian('התשפ"ה') == 2025
        assert hebrew_year_to_gregorian('תש"י') == 1950
        assert hebrew_year_to_gregorian('התשס"א') == 2001

    def test_parse_gregorian_date(self):
        assert parse_gregorian_date("1950-08-09T00:00:00+03:00") == date(1950, 8, 9)
        assert parse_gregorian_date("1982-08-22") == date(1982, 8, 22)
        assert parse_gregorian_date("") is None
        assert parse_gregorian_date(None) is None


# ─────────────────────────────────────────────
# Visual Hebrew Detection & Reversing Tests
# ─────────────────────────────────────────────


class TestVisualHebrew:
    def test_visual_detection(self):
        text_visual = '*1950\xad י"שת ,(םיסכנ תרבעה) חותיפ תושר קוח'
        text_logical = 'חוק רשות הפיתוח (העברת נכסים), התש"י-1950'
        assert is_visual_hebrew(text_visual) is True
        assert is_visual_hebrew(text_logical) is False

    def test_reversing_and_digits(self):
        line = "62 רפסמ"
        assert reverse_visual_line(line) == "מספר 62"

        line_complex = '*1950\xad י"שת ,(םיסכנ תרבעה) חותיפ תושר קוח'
        assert reverse_visual_line(line_complex) == 'חוק רשות פיתוח (העברת נכסים), תש"י \xad1950*'


# ─────────────────────────────────────────────
# Reblaze WAF detection tests
# ─────────────────────────────────────────────


class TestReblazeDetection:
    def test_reblaze_detect(self):
        html_block = b"<!DOCTYPE html><html><head><title>reblaze chalenge</title></head></html>"
        json_ok = b'{"value": []}'
        assert is_reblaze_content(html_block) is True
        assert is_reblaze_content(json_ok) is False


# ─────────────────────────────────────────────
# Metadata Parser Tests
# ─────────────────────────────────────────────


class TestIsraelMetadataParser:
    def test_metadata_parsing(self):
        # Build raw metadata dict simulating OData response
        meta_dict = {
            "law": {
                "Id": 2000002,
                "Name": 'חוק התקשורת (בזק ושידורים), התשמ"ב-1982',
                "IsBasicLaw": False,
                "PublicationDate": "1982-08-22T00:00:00+03:00",
                "LatestPublicationDate": "2025-06-16T00:00:00+03:00",
                "LawValidityDesc": "תקף",
                "KnessetNum": 10,
            },
            "names": [
                {"Name": 'חוק הבזק, התשמ"ב-1982', "LastUpdatedDate": "2016-05-09"},
                {
                    "Name": 'חוק התקשורת (בזק ושידורים), התשמ"ב-1982',
                    "LastUpdatedDate": "2020-05-09",
                },
            ],
            "classifications": [{"ClassificiationDesc": "תקשורת"}],
            "ministries": [{"MinistryCategoryDesc": "התקשורת"}],
        }

        parser = IsraelMetadataParser()
        meta = parser.parse(json.dumps(meta_dict).encode("utf-8"), "2000002")

        assert meta.identifier == "2000002"
        assert meta.country == "il"
        assert meta.title == 'חוק התקשורת (בזק ושידורים), התשמ"ב-1982'
        assert meta.short_title == "חוק התקשורת (בזק ושידורים)"
        assert meta.rank == "law"
        assert meta.publication_date == date(1982, 8, 22)
        assert meta.status == NormStatus.IN_FORCE
        assert meta.department == "התקשורת"
        assert "תקשורת" in meta.subjects
        extra = dict(meta.extra)
        assert extra.get("knesset_num") == "10"
        # Internal UI flag is dropped; non-budget law omits the noisy "False".
        assert "is_favorite_law" not in extra
        assert "is_budget_law" not in extra

    def test_budget_law_flag_emitted_only_when_true(self):
        meta_dict = {
            "law": {
                "Id": 1,
                "Name": "חוק התקציב",
                "IsBudgetLaw": True,
                "PublicationDate": "2020-01-01",
            }
        }
        meta = IsraelMetadataParser().parse(json.dumps(meta_dict).encode("utf-8"), "1")
        assert dict(meta.extra).get("is_budget_law") == "true"

    def test_basic_law_rank(self):
        meta_dict = {
            "law": {
                "Id": 2000037,
                "Name": "חוק-יסוד: הכנסת",
                "IsBasicLaw": True,
                "PublicationDate": "1958-02-20T00:00:00+02:00",
            }
        }
        parser = IsraelMetadataParser()
        meta = parser.parse(json.dumps(meta_dict).encode("utf-8"), "2000037")
        assert meta.rank == "basic_law"


# ─────────────────────────────────────────────
# Text Parser Tests
# ─────────────────────────────────────────────


class TestIsraelTextParser:
    def test_text_parsing(self):
        text_dict = {
            "original_text": "פרק א׳: מבוא\n\nסעיף 1. פירושים\nבחוק זה יהיו המונחים להלן...\n\nסעיף 2. רשות הפיתוח\nמדינת ישראל מקימה...",
            "reforms_text": [{"bill_id": "12345", "text": "תיקון מס׳ 1 לראות..."}],
        }

        parser = IsraelTextParser()
        blocks = parser.parse_text(json.dumps(text_dict).encode("utf-8"))

        # Should have parsed preamble, chapter, article 1, article 2, and amendment block
        assert len(blocks) >= 4

        # Check first block (preamble or chapter)
        assert blocks[0].block_type == "section"
        assert "פרק" in blocks[0].title

        # Check second block (Article 1)
        assert blocks[1].block_type == "article"
        assert "סעיף 1" in blocks[1].title

        # Check amendment block
        assert blocks[-1].block_type == "amendment"
        assert blocks[-1].id == "amendment_12345"

    def test_reform_uses_real_date_and_chronological_order(self):
        """Amendments must carry their real effective date, not a placeholder, and be ordered."""
        text_dict = {
            "original_text": "סעיף 1. פתיח\nטקסט מקורי",
            "publication_date": "1982-08-22T00:00:00+03:00",
            "reforms_text": [
                {"bill_id": "200", "text": "תיקון מאוחר", "date": "2010-05-01T00:00:00+03:00"},
                {"bill_id": "100", "text": "תיקון מוקדם", "date": "1990-03-15T00:00:00+02:00"},
            ],
        }
        parser = IsraelTextParser()
        blocks = parser.parse_text(json.dumps(text_dict).encode("utf-8"))

        amendments = [b for b in blocks if b.block_type == "amendment"]
        assert [b.id for b in amendments] == ["amendment_100", "amendment_200"]
        assert amendments[0].versions[0].effective_date == date(1990, 3, 15)
        assert amendments[1].versions[0].effective_date == date(2010, 5, 1)
        # No placeholder dates leaked into the history.
        assert all(v.effective_date != date(2000, 1, 1) for b in amendments for v in b.versions)

    def test_reform_without_date_falls_back_to_publication_date(self):
        text_dict = {
            "original_text": "סעיף 1. פתיח\nטקסט",
            "publication_date": "1982-08-22T00:00:00+03:00",
            "reforms_text": [{"bill_id": "300", "text": "תיקון ללא תאריך"}],
        }
        parser = IsraelTextParser()
        blocks = parser.parse_text(json.dumps(text_dict).encode("utf-8"))
        amendment = [b for b in blocks if b.block_type == "amendment"][0]
        assert amendment.versions[0].effective_date == date(1982, 8, 22)


# ─────────────────────────────────────────────
# Correction date map (client) tests
# ─────────────────────────────────────────────


class TestCorrectionDateMap:
    def test_maps_bill_to_earliest_date(self):
        corrections = [
            {
                "KNS_LawCorrection": {
                    "BillID": 147159,
                    "PublicationDate": "1984-01-04T00:00:00+02:00",
                }
            },
            {
                "KNS_LawCorrection": {
                    "BillID": 152082,
                    "PublicationDate": "1989-12-31T00:00:00+02:00",
                }
            },
            {
                "KNS_LawCorrection": {
                    "BillID": 152082,
                    "PublicationDate": "1989-12-07T00:00:00+02:00",
                }
            },
        ]
        result = IsraelClient._build_correction_date_map(corrections)
        assert result[147159] == "1984-01-04T00:00:00+02:00"
        # Earliest of the two 152082 dates wins.
        assert result[152082] == "1989-12-07T00:00:00+02:00"

    def test_prefers_commencement_then_publication(self):
        corrections = [
            {
                "KNS_LawCorrection": {
                    "BillID": 1,
                    "CommencementDate": "2000-01-01T00:00:00+02:00",
                    "PublicationDate": "1999-01-01T00:00:00+02:00",
                }
            }
        ]
        result = IsraelClient._build_correction_date_map(corrections)
        assert result[1] == "2000-01-01T00:00:00+02:00"

    def test_skips_missing_bill_id(self):
        corrections = [{"KNS_LawCorrection": {"PublicationDate": "2000-01-01"}}, {}]
        assert IsraelClient._build_correction_date_map(corrections) == {}


# ─────────────────────────────────────────────
# Extracted-text cleaning tests
# ─────────────────────────────────────────────


class TestCleanExtractedText:
    def test_soft_hyphen_becomes_hyphen_and_joins(self):
        # Soft hyphen (U+00AD), optionally surrounded by spaces, is a maqaf/hyphen.
        assert clean_extracted_text("חוק \u00adיסוד") == "חוק-יסוד"
        assert clean_extracted_text("על\u00adפי") == "על-פי"
        assert clean_extracted_text("צבא\u00adהגנה\u00adלישראל") == "צבא-הגנה-לישראל"

    def test_zero_width_separators_become_spaces(self):
        # Some Reshumot PDFs use U+FEFF / U+200B as word separators, not regular spaces.
        assert clean_extracted_text("ספר\ufeffהחוקים") == "ספר החוקים"
        assert clean_extracted_text("מבקר\u200bהמדינה") == "מבקר המדינה"

    def test_strips_bidi_marks_and_bom(self):
        # Leading BOM and trailing RLM are removed; the word itself is preserved.
        assert clean_extracted_text("\ufeffמבקר\u200f") == "מבקר"
        assert clean_extracted_text("א\u200eב") == "אב"

    def test_collapses_spaces_and_trims_lines(self):
        assert clean_extracted_text("מבקר   המדינה  \n  שורה   שנייה") == "מבקר המדינה\nשורה שנייה"

    def test_empty(self):
        assert clean_extracted_text("") == ""


# ─────────────────────────────────────────────
# Document selection: enacted text vs draft bill
# ─────────────────────────────────────────────


class TestDocumentSelection:
    def test_draft_bill_is_excluded(self):
        # Bills carry the explanatory memorandum (דברי הסבר) and must never be used.
        assert (
            _document_priority(
                {"GroupTypeDesc": "הצעת חוק לקריאה הראשונה", "ApplicationDesc": "PDF"}
            )
            is None
        )

    def test_image_and_ppt_formats_excluded(self):
        assert (
            _document_priority({"GroupTypeDesc": "חוק - פרסום ברשומות", "ApplicationDesc": "PIC"})
            is None
        )
        assert (
            _document_priority({"GroupTypeDesc": "חוק - פרסום ברשומות", "ApplicationDesc": "PPT"})
            is None
        )

    def test_enacted_reshumot_preferred_over_other_groups(self):
        reshumot_pdf = _document_priority(
            {"GroupTypeDesc": "חוק - פרסום ברשומות", "ApplicationDesc": "PDF"}
        )
        correction_pdf = _document_priority(
            {"GroupTypeDesc": "חוק - תיקון טעות", "ApplicationDesc": "PDF"}
        )
        other_pdf = _document_priority({"GroupTypeDesc": "משהו אחר", "ApplicationDesc": "PDF"})
        assert reshumot_pdf is not None and correction_pdf is not None and other_pdf is not None
        # Reshumot + correction are gazette publications (group rank 0); other is rank 1.
        assert reshumot_pdf[0] == 0
        assert correction_pdf[0] == 0
        assert other_pdf[0] == 1

    def test_pdf_preferred_over_doc_within_group(self):
        pdf = _document_priority({"GroupTypeDesc": "חוק - פרסום ברשומות", "ApplicationDesc": "PDF"})
        doc = _document_priority({"GroupTypeDesc": "חוק - פרסום ברשומות", "ApplicationDesc": "DOC"})
        assert pdf < doc

    def test_real_bill_fixture_has_both_enacted_and_draft_docs(self):
        bill = _load_fixture("bill_with_docs.json")["value"][0]
        docs = bill.get("KNS_DocumentBill", [])
        usable = [d for d in docs if _document_priority(d) is not None]
        excluded = [d for d in docs if _document_priority(d) is None]
        # Some docs are selectable (gazette text) and some are excluded (drafts/images).
        assert usable and excluded
        assert all("הצעת חוק" not in (d.get("GroupTypeDesc") or "") for d in usable)


# ─────────────────────────────────────────────
# Article-marker detection (visual-order PDFs)
# ─────────────────────────────────────────────


class TestArticleDetection:
    def test_visual_marginal_markers_segment_articles(self):
        # Reproduces the visual-order layout: ".N" / "heading ,N" / "heading .N (".
        text_dict = {
            "original_text": (
                ".1 ביקורת המדינה נתונה בידי מבקר המדינה.\n"
                "ביקורת המדינה .2 (א) מבקר המדינה יקיים ביקורת על המשק.\n"
                "מהות ,3 צבא הגנה לישראל הוא צבאה של המדינה.\n"
            ),
            "publication_date": "1988-02-24T00:00:00+02:00",
        }
        parser = IsraelTextParser()
        blocks = parser.parse_text(json.dumps(text_dict).encode("utf-8"))
        articles = [b for b in blocks if b.block_type == "article"]
        assert len(articles) == 3
        # The body excludes the marker; the marginal heading becomes the title.
        assert articles[1].title == "ביקורת המדינה"
        assert articles[1].versions[0].paragraphs[0].text.startswith("(א)")

    def test_subsections_are_not_markers(self):
        text_dict = {
            "original_text": "1. פתיח\n(א) משנה ראשונה\n(2) משנה שנייה\nטקסט המשך",
            "publication_date": "1990-01-01",
        }
        parser = IsraelTextParser()
        blocks = parser.parse_text(json.dumps(text_dict).encode("utf-8"))
        # Only one article ("1."); "(א)" and "(2)" stay inside it, not new blocks.
        assert len([b for b in blocks if b.block_type == "article"]) == 1


# ─────────────────────────────────────────────
# Fixture-driven tests against real Knesset OData responses (offline)
# ─────────────────────────────────────────────


class TestRealFixtures:
    def test_correction_dates_from_real_response(self):
        data = _load_fixture("corrections_for_law.json")
        result = IsraelClient._build_correction_date_map(data["value"])
        # Every mapped bill resolves to a real (non-placeholder) ISO date string.
        assert result
        assert all(d and not d.startswith("2000-01-01") for d in result.values())

    def test_bill_fixture_exposes_publication_date_and_docs(self):
        bill = _load_fixture("bill_with_docs.json")["value"][0]
        assert bill["PublicationDate"].startswith("1950-08-09")
        assert any(d.get("FilePath") for d in bill.get("KNS_DocumentBill", []))

    def test_law_name_fixture_has_titles(self):
        names = _load_fixture("KNS_IsraelLawName.json")["value"]
        assert names and all("Name" in n for n in names)
