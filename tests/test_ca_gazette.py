"""Tests for Canada Gazette Part III PDF pipeline.

Exercises the segmenter on synthetic extraction stubs so we don't need
real PDFs in the test corpus. The pdf_extractor itself is covered via
its helper functions (hyphen-merge, header dedup, normalize) rather
than full rasterisation.
"""

from __future__ import annotations

from datetime import date


from legalize.fetcher.ca.gazette_client import (
    DEFAULT_FIRST_YEAR,
    DEFAULT_LAST_YEAR,
    PDF_FILENAME_TEMPLATE,
    PDF_HREF_RE,
    _VOLUME_BASE_YEAR,
)
from legalize.fetcher.ca.gazette_index import _classify_title
from legalize.fetcher.ca.gazette_segmenter import (
    _first_chapter_from_issue,
    _parse_assent,
    _parse_bill,
    _extract_title,
    segment,
)
from legalize.fetcher.ca.pdf_extractor import (
    GazetteExtraction,
    GazettePage,
    _collect_repeated_headers,
    _merge_hyphenated,
    _normalize,
    _ocr_confidence,
)


# ─────────────────────────────────────────────
# PDF extractor helpers
# ─────────────────────────────────────────────


class TestMergeHyphenated:
    def test_merges_mid_word_hyphen(self):
        assert _merge_hyphenated(["consoli-", "dated"]) == ["consolidated"]

    def test_leaves_list_separator(self):
        # The space-before-dash guard catches "2001, -" as a list item.
        assert _merge_hyphenated(["2001, -", "c. 5"]) == ["2001, -", "c. 5"]

    def test_handles_unicode_minus(self):
        assert _merge_hyphenated(["abc−", "def"]) == ["abcdef"]

    def test_single_line_unchanged(self):
        assert _merge_hyphenated(["no hyphens here"]) == ["no hyphens here"]


class TestRepeatedHeaders:
    def test_drops_lines_appearing_on_multiple_pages(self):
        texts = [
            "title page content\nwhatever",
            "Canada Gazette\nPart III\nsome body",
            "Canada Gazette\nPart III\nmore body",
            "Canada Gazette\nPart III\neven more",
        ]
        headers = _collect_repeated_headers(texts)
        assert "Canada Gazette" in headers
        assert "Part III" in headers
        assert "some body" not in headers  # unique to one page

    def test_ignores_title_page(self):
        # The title page (index 0) is skipped — lines unique to it should
        # not be flagged even if short.
        texts = [
            "Vol. 43 No. 1\nCanada Gazette",  # title page
            "different content",
        ]
        headers = _collect_repeated_headers(texts)
        assert "Vol. 43 No. 1" not in headers

    def test_ignores_singletons(self):
        # CHAPTER markers appear once per chapter — must NOT be flagged
        # as repeated headers (that would drop them from segmentation).
        texts = [
            "title",
            "CHAPTER 1\nbody",
            "CHAPTER 2\nbody",
            "CHAPTER 3\nbody",
        ]
        headers = _collect_repeated_headers(texts)
        assert "CHAPTER 1" not in headers
        assert "CHAPTER 2" not in headers


class TestNormalize:
    def test_strips_invisibles(self):
        assert _normalize("foo­bar") == "foobar"  # soft hyphen removed

    def test_strips_control_chars(self):
        assert _normalize("foo\x00\x01bar") == "foobar"

    def test_keeps_tab_and_newline(self):
        assert _normalize("foo\tbar\nbaz") == "foo\tbar\nbaz"


class TestOcrConfidence:
    def test_clean_digital_text_returns_one(self):
        text = "This Act may be cited as the Income Tax Act of Canada"
        assert _ocr_confidence(text) == 1.0

    def test_very_short_text_returns_one(self):
        # No words → can't measure, optimistic default.
        assert _ocr_confidence("") == 1.0
        assert _ocr_confidence("ab") == 1.0


# ─────────────────────────────────────────────
# Gazette segmenter
# ─────────────────────────────────────────────


class TestParseAssent:
    def test_uppercase_month_day_year(self):
        assert _parse_assent("ASSENTED TO MARCH 13, 2020") == date(2020, 3, 13)

    def test_uppercase_day_month_year(self):
        assert _parse_assent("ASSENTED TO 13 MARCH 2020") == date(2020, 3, 13)

    def test_bracketed_with_ordinal(self):
        assert _parse_assent("[Assented to 31st March, 1998]") == date(1998, 3, 31)

    def test_bracketed_without_ordinal(self):
        assert _parse_assent("[Assented to 1 April 1999]") == date(1999, 4, 1)

    def test_missing_returns_none(self):
        assert _parse_assent("no assent date here") is None

    def test_invalid_date_returns_none(self):
        # Day 99 is out of range.
        assert _parse_assent("ASSENTED TO MARCH 99, 2020") is None


class TestParseBill:
    def test_commons_bill(self):
        assert _parse_bill("BILL C-4") == "C-4"

    def test_senate_bill(self):
        assert _parse_bill("BILL S-17") == "S-17"

    def test_normalizes_en_dash(self):
        # Older issues printed the bill number with an en-dash.
        assert _parse_bill("BILL C–13") == "C-13"

    def test_normalizes_spaces(self):
        assert _parse_bill("BILL C - 4") == "C-4"

    def test_missing_returns_empty(self):
        assert _parse_bill("no bill here") == ""


class TestFirstChapterFromIssue:
    def test_chapters_range(self):
        assert _first_chapter_from_issue("Statutes of Canada, 1998\nChapters 1 to 4") == 1

    def test_single_chapter(self):
        assert _first_chapter_from_issue("Statutes of Canada\nChapter 5") == 5

    def test_missing_returns_none(self):
        assert _first_chapter_from_issue("no chapter info") is None


class TestExtractTitle:
    def test_simple_title(self):
        cover = "STATUTES OF CANADA 2020\nCHAPTER 1\nAn Act to implement the Agreement\nASSENTED TO\nMARCH 13, 2020\nBILL C-4"
        assert _extract_title(cover, "en") == "An Act to implement the Agreement"

    def test_multiline_title(self):
        cover = (
            "CHAPTER 1\n"
            "An Act to implement the Agreement\n"
            "between Canada, the United States of\n"
            "America and the United Mexican States\n"
            "ASSENTED TO\nMARCH 13, 2020\nBILL C-4"
        )
        title = _extract_title(cover, "en")
        assert title.startswith("An Act to implement the Agreement")
        assert "United Mexican States" in title

    def test_stops_at_bracketed_assent(self):
        cover = "CHAPTER 2\nof money for the public service\n[Assented to 31st March, 1998]"
        assert _extract_title(cover, "en") == "of money for the public service"

    def test_skips_regnal_year_line(self):
        cover = (
            "CHAPTER 1\n"
            "68-69 Elizabeth II, 2019-2020\n"
            "An Act to implement\n"
            "ASSENTED TO\nMARCH 13, 2020"
        )
        title = _extract_title(cover, "en")
        assert title == "An Act to implement"


class TestSegment:
    @staticmethod
    def _fake_extraction(pages_text: list[tuple[str, str]]) -> GazetteExtraction:
        """Build a :class:`GazetteExtraction` from ``[(en, fr), …]``."""
        pages = tuple(
            GazettePage(index=i, width=612, height=792, text_en=en, text_fr=fr)
            for i, (en, fr) in enumerate(pages_text)
        )
        return GazetteExtraction(pages=pages, ocr_confidence=1.0)

    def test_simple_two_chapter_issue(self):
        ext = self._fake_extraction(
            [
                ("Vol. 43 No. 1\nCanada Gazette\nPart III\nChapters 1 to 2", "cover fr"),
                ("TABLE OF CONTENTS", "TABLE DES MATIERES"),
                (
                    "CHAPTER 1\nAn Act to amend the Income Tax Act\nASSENTED TO MARCH 13, 2020\nBILL C-4",
                    "CHAPITRE 1\nLoi modifiant la Loi de l'impôt sur le revenu",
                ),
                ("body of chapter 1", "corps du chapitre 1"),
                (
                    "CHAPTER 2\nAn Act to amend the Criminal Code\nASSENTED TO MARCH 25, 2020\nBILL C-13",
                    "CHAPITRE 2\nLoi modifiant le Code criminel",
                ),
                ("body of chapter 2", "corps du chapitre 2"),
            ]
        )
        segs = segment(ext)
        assert len(segs) == 2
        assert segs[0].chapter == 1
        assert segs[0].assent_date == date(2020, 3, 13)
        assert segs[0].bill_number == "C-4"
        assert "Income Tax Act" in segs[0].title_en
        assert segs[1].chapter == 2
        assert segs[1].assent_date == date(2020, 3, 25)

    def test_deduplicates_running_headers(self):
        # "CHAPTER 1" appears on the cover AND on body pages as running
        # header. Segmenter must keep only the cover.
        ext = self._fake_extraction(
            [
                ("cover\nChapters 1 to 1", ""),
                ("TABLE OF CONTENTS", ""),
                (
                    "CHAPTER 1\nAn Act X\nASSENTED TO MARCH 1, 2020\nBILL C-1",
                    "",
                ),
                ("CHAPTER 1\nbody page", ""),  # running header repeat
                ("CHAPTER 1\nmore body", ""),
            ]
        )
        segs = segment(ext)
        assert len(segs) == 1  # single chapter, not three

    def test_synthesizes_implicit_chapter_one(self):
        # Older issues: chapter 1 has no explicit marker; chapter 2+ do.
        ext = self._fake_extraction(
            [
                ("Chapters 1 to 2\nCanada Gazette Part III", "Partie III"),
                ("TABLE OF CONTENTS\nwhatever", ""),
                (
                    "SUMMARY\nThis enactment modernizes...\n[Assented to 30th April, 1998]",
                    "SOMMAIRE",
                ),
                ("more body of chapter 1", ""),
                (
                    "CHAPTER 2\nAn Act respecting appropriations\n[Assented to 31st March, 1998]",
                    "",
                ),
                ("body of chapter 2", ""),
            ]
        )
        segs = segment(ext)
        assert len(segs) == 2
        assert segs[0].chapter == 1  # synthesized
        assert segs[1].chapter == 2

    def test_no_chapters_found_returns_empty(self):
        ext = self._fake_extraction([("", ""), ("", "")])
        assert segment(ext) == []


# ─────────────────────────────────────────────
# Gazette index title classifier
# ─────────────────────────────────────────────


class TestGazetteClassifyTitle:
    def test_amend_strips_prefix(self):
        assert _classify_title("An Act to amend the Income Tax Act", "en") == "Income Tax Act"

    def test_french_amend(self):
        assert _classify_title("Loi modifiant le Code criminel", "fr") == "Code criminel"

    def test_creation_returns_title(self):
        # Creation bills don't match "An Act to amend" — return as-is.
        assert _classify_title("Canada Cooperatives Act", "en") == "Canada Cooperatives Act"

    def test_empty_returns_empty(self):
        assert _classify_title("", "en") == ""


# ─────────────────────────────────────────────
# Gazette client URL generation
# ─────────────────────────────────────────────


class TestGazetteClientFilenames:
    def test_volume_calculation(self):
        # Volume 1 = 1978, so 2020 = Volume 43.
        assert 2020 - _VOLUME_BASE_YEAR == 43
        assert 1998 - _VOLUME_BASE_YEAR == 21

    def test_pdf_filename_template(self):
        assert PDF_FILENAME_TEMPLATE.format(vol=43, issue=1) == "g3-04301.pdf"
        assert PDF_FILENAME_TEMPLATE.format(vol=21, issue=3) == "g3-02103.pdf"

    def test_default_years_span(self):
        assert DEFAULT_FIRST_YEAR == 1998
        assert DEFAULT_LAST_YEAR == 2000


class TestGazettePdfHrefRegex:
    def test_matches_gazette_href(self):
        html = '<a href="g3-04301.pdf">Part 1</a>'
        m = PDF_HREF_RE.search(html)
        assert m is not None
        assert m.group(1).endswith("g3-04301.pdf")

    def test_matches_absolute_url(self):
        html = '<a href="/rp-pr/p3/2020/g3-04302.pdf">PDF</a>'
        m = PDF_HREF_RE.search(html)
        assert m is not None

    def test_no_match_on_non_gazette_pdf(self):
        html = '<a href="g3-report.pdf">X</a>'
        assert PDF_HREF_RE.search(html) is None
