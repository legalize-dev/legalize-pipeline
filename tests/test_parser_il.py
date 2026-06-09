"""Tests for Israel fetcher, parser, and date helper components (il)."""

from __future__ import annotations

import json
from datetime import date

from legalize.fetcher.il.client import is_visual_hebrew, reverse_visual_line, is_reblaze_content
from legalize.fetcher.il.dates_il import hebrew_year_to_gregorian, parse_gregorian_date
from legalize.fetcher.il.parser import IsraelMetadataParser, IsraelTextParser
from legalize.models import NormStatus


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
        assert dict(meta.extra).get("knesset_num") == "10"

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
