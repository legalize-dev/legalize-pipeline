"""Tests for :mod:`legalize.fetcher.ca.gazette_index`.

The index builder walks PDFs on disk, segments them, and resolves each
chapter's title against a :class:`TitleIndex`. To avoid shipping real
PDFs in the test corpus we stub the extractor + segmenter at the public
function boundary — the pure classification, attribution and JSON
roundtrip logic doesn't need a rasteriser to be verified.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from legalize.fetcher.ca import gazette_index as gi
from legalize.fetcher.ca.gazette_index import (
    GazetteIndex,
    GazetteRef,
    build_gazette_index,
    load_or_build_gazette_index,
)
from legalize.fetcher.ca.pdf_extractor import GazetteExtraction, GazettePage
from legalize.fetcher.ca.title_index import TitleIndex


# ─────────────────────────────────────────────
# JSON roundtrip
# ─────────────────────────────────────────────


class TestGazetteIndexJson:
    def test_roundtrip_preserves_refs(self):
        ref = GazetteRef(
            year=1999,
            chapter=5,
            assent_date="1999-06-14",
            pdf_path="gazette-pdf/1999/g3-02202.pdf",
            first_page=10,
            last_page=25,
            bill_number="C-5",
            title_en="An Act to amend X",
            title_fr="Loi modifiant X",
            ocr_confidence=1.0,
        )
        idx = GazetteIndex(
            by_norm={"eng/acts/X-1": [ref]},
            unresolved=[(1998, 3, "Some Bill Title")],
        )
        blob = idx.to_json()
        reloaded = GazetteIndex.from_json(blob)

        refs = reloaded.refs_for("eng/acts/X-1")
        assert len(refs) == 1
        assert refs[0].year == 1999
        assert refs[0].chapter == 5
        assert refs[0].bill_number == "C-5"
        assert refs[0].as_date() == date(1999, 6, 14)
        assert reloaded.unresolved == [(1998, 3, "Some Bill Title")]

    def test_empty_index_roundtrip(self):
        blob = GazetteIndex().to_json()
        reloaded = GazetteIndex.from_json(blob)
        assert reloaded.by_norm == {}
        assert reloaded.unresolved == []


# ─────────────────────────────────────────────
# Title classifier
# ─────────────────────────────────────────────


class TestClassifyTitle:
    def test_amend_prefix_stripped_en(self):
        assert gi._classify_title("An Act to amend the Income Tax Act", "en") == ("Income Tax Act")

    def test_amend_strips_and_other_tail(self):
        assert (
            gi._classify_title("An Act to amend the Criminal Code and the Firearms Act", "en")
            == "Criminal Code"
        )

    def test_amend_strips_parenthetical(self):
        assert (
            gi._classify_title("An Act to amend the Income Tax Act (COVID-19 subsidy)", "en")
            == "Income Tax Act"
        )

    def test_french_amend(self):
        assert gi._classify_title("Loi modifiant le Code criminel", "fr") == ("Code criminel")

    def test_french_amend_strips_et_suffix(self):
        assert (
            gi._classify_title("Loi modifiant le Code criminel et la Loi sur les armes à feu", "fr")
            == "Code criminel"
        )

    def test_creation_returns_title(self):
        assert gi._classify_title("Canada Cooperatives Act", "en") == ("Canada Cooperatives Act")

    def test_empty_returns_empty(self):
        assert gi._classify_title("", "en") == ""
        assert gi._classify_title("   ", "en") == ""


# ─────────────────────────────────────────────
# End-to-end build with stubbed extractor
# ─────────────────────────────────────────────


def _fake_extraction(chapter: int, title_en: str, title_fr: str) -> GazetteExtraction:
    """Return a one-page extraction — the build calls the segmenter on it,
    which is what we actually want to exercise here."""
    return GazetteExtraction(
        pages=(
            GazettePage(
                index=0,
                width=612,
                height=792,
                text_en=(
                    f"STATUTES OF CANADA 2020\nCHAPTER {chapter}\n"
                    f"{title_en}\nASSENTED TO MARCH 13, 2020\nBILL C-{chapter}"
                ),
                text_fr=(
                    f"LOIS DU CANADA 2020\nCHAPITRE {chapter}\n"
                    f"{title_fr}\nSANCTIONNÉE LE 13 MARS 2020\nPROJET DE LOI C-{chapter}"
                ),
            ),
            GazettePage(index=1, width=612, height=792, text_en="body", text_fr="corps"),
        ),
        ocr_confidence=1.0,
    )


class TestBuildGazetteIndex:
    @pytest.fixture
    def title_idx(self) -> TitleIndex:
        # Keys must match what ``title_index._normalize`` produces from the
        # titles the bills actually use. Unicode word-class preserves
        # accented characters (``ô``), so the FR key carries the accent.
        return TitleIndex(
            en={
                "income tax act": "eng/acts/I-3.3",
                "criminal code": "eng/acts/C-46",
            },
            fr={
                "loi de l impôt sur le revenu": "fra/lois/I-3.3",
                "code criminel": "fra/lois/C-46",
            },
        )

    def test_missing_root_returns_empty_index(self, tmp_path: Path, title_idx):
        idx = build_gazette_index(tmp_path / "nonexistent", title_idx)
        assert idx.by_norm == {}
        assert idx.unresolved == []

    def test_empty_root_returns_empty_index(self, tmp_path: Path, title_idx):
        root = tmp_path / "gazette-pdf"
        root.mkdir()
        idx = build_gazette_index(root, title_idx)
        assert idx.by_norm == {}

    def test_resolves_amendment_to_both_languages(self, tmp_path: Path, title_idx, monkeypatch):
        """Monkeypatched extractor yields one chapter that amends Income Tax
        Act — we expect two norms in the resulting index, one per language."""
        root = tmp_path / "gazette-pdf"
        root.mkdir()
        year = root / "2020"
        year.mkdir()
        fake_pdf = year / "g3-04301.pdf"
        fake_pdf.write_bytes(b"placeholder: extractor is stubbed")

        monkeypatch.setattr(
            gi,
            "extract_text_from_pdf",
            lambda p: _fake_extraction(
                chapter=1,
                title_en="An Act to amend the Income Tax Act",
                title_fr="Loi modifiant la Loi de l'impôt sur le revenu",
            ),
        )

        idx = build_gazette_index(root, title_idx)
        assert set(idx.by_norm.keys()) == {"eng/acts/I-3.3", "fra/lois/I-3.3"}
        assert idx.unresolved == []

        en_refs = idx.refs_for("eng/acts/I-3.3")
        assert len(en_refs) == 1
        assert en_refs[0].chapter == 1
        assert en_refs[0].year == 2020
        assert en_refs[0].bill_number == "C-1"
        assert en_refs[0].assent_date == "2020-03-13"
        assert en_refs[0].pdf_path.endswith("g3-04301.pdf")

    def test_unresolved_title_recorded(self, tmp_path: Path, title_idx, monkeypatch):
        """A chapter whose title doesn't map to any indexed norm should
        land in ``unresolved`` rather than silently disappearing."""
        root = tmp_path / "gazette-pdf"
        root.mkdir()
        (root / "2020").mkdir()
        (root / "2020" / "g3-04301.pdf").write_bytes(b"placeholder")

        monkeypatch.setattr(
            gi,
            "extract_text_from_pdf",
            lambda p: _fake_extraction(
                chapter=1,
                title_en="An Act to establish the Xyzzy Act",
                title_fr="Loi concernant la Xyzzy",
            ),
        )

        idx = build_gazette_index(root, title_idx)
        assert idx.by_norm == {}
        # Exactly one unresolved entry with (year, chapter, title).
        assert len(idx.unresolved) == 1
        year_u, chap_u, title_u = idx.unresolved[0]
        assert (year_u, chap_u) == (2020, 1)

    def test_refs_sorted_chronologically(self, tmp_path: Path, title_idx, monkeypatch):
        """When multiple PDFs amend the same norm, refs come out in order."""
        root = tmp_path / "gazette-pdf"
        for year in (1999, 2000):
            (root / str(year)).mkdir(parents=True)
            (root / str(year) / f"g3-0{year - 1977:02d}01.pdf").write_bytes(b"x")

        pdf_to_chapter = {
            "1999": (5, "1999-06-14"),
            "2000": (3, "2000-04-01"),
        }

        def fake_extract(pdf_path):
            year_dir = pdf_path.parent.name
            ch, assent_date = pdf_to_chapter[year_dir]
            # Embed the right year in the cover so the segmenter's assent
            # parser sees the full date.
            y, m, d = assent_date.split("-")
            month_name = [
                "JANUARY",
                "FEBRUARY",
                "MARCH",
                "APRIL",
                "MAY",
                "JUNE",
                "JULY",
                "AUGUST",
                "SEPTEMBER",
                "OCTOBER",
                "NOVEMBER",
                "DECEMBER",
            ][int(m) - 1]
            cover = (
                f"STATUTES OF CANADA {y}\nCHAPTER {ch}\n"
                f"An Act to amend the Income Tax Act\n"
                f"ASSENTED TO {month_name} {int(d)}, {y}\nBILL C-{ch}"
            )
            return GazetteExtraction(
                pages=(
                    GazettePage(
                        index=0,
                        width=612,
                        height=792,
                        text_en=cover,
                        text_fr="",
                    ),
                    GazettePage(index=1, width=612, height=792, text_en="body", text_fr=""),
                ),
                ocr_confidence=1.0,
            )

        monkeypatch.setattr(gi, "extract_text_from_pdf", fake_extract)

        idx = build_gazette_index(root, title_idx)
        refs = idx.refs_for("eng/acts/I-3.3")
        assert [r.year for r in refs] == [1999, 2000]
        assert refs[0].assent_date < refs[1].assent_date


# ─────────────────────────────────────────────
# Cache / reload
# ─────────────────────────────────────────────


class TestLoadOrBuild:
    def test_load_uses_cache_when_present(self, tmp_path: Path):
        cached = GazetteIndex(
            by_norm={
                "eng/acts/X-1": [
                    GazetteRef(
                        year=1999,
                        chapter=5,
                        assent_date="1999-06-14",
                        pdf_path="foo.pdf",
                        first_page=0,
                        last_page=10,
                        bill_number="C-5",
                        title_en="An Act X",
                        title_fr="Loi X",
                        ocr_confidence=1.0,
                    )
                ]
            }
        )
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "gazette-index.json").write_text(cached.to_json())

        # The PDF root doesn't even exist — cache hit means we never look.
        loaded = load_or_build_gazette_index(
            tmp_path / "nonexistent-pdfs",
            TitleIndex(en={}, fr={}),
            data_dir,
        )
        refs = loaded.refs_for("eng/acts/X-1")
        assert len(refs) == 1
        assert refs[0].bill_number == "C-5"

    def test_invalid_cache_triggers_rebuild(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "gazette-index.json").write_text("{not json}")

        # Rebuild from a missing PDF root → empty index, and the cache is
        # rewritten with valid JSON.
        loaded = load_or_build_gazette_index(
            tmp_path / "nonexistent-pdfs",
            TitleIndex(en={}, fr={}),
            data_dir,
        )
        assert loaded.by_norm == {}
        assert (data_dir / "gazette-index.json").read_text() != "{not json}"

    def test_force_rebuild_bypasses_cache(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Populate cache with an entry that *would* be returned if we
        # honoured the cache.
        prior = GazetteIndex(
            by_norm={
                "eng/acts/STALE": [
                    GazetteRef(
                        year=1999,
                        chapter=1,
                        assent_date="1999-01-01",
                        pdf_path="x",
                        first_page=0,
                        last_page=1,
                        bill_number="",
                        title_en="",
                        title_fr="",
                        ocr_confidence=1.0,
                    )
                ]
            }
        )
        (data_dir / "gazette-index.json").write_text(prior.to_json())

        loaded = load_or_build_gazette_index(
            tmp_path / "no-pdfs",
            TitleIndex(en={}, fr={}),
            data_dir,
            force_rebuild=True,
        )
        # Rebuild against missing PDFs → empty; stale entry gone.
        assert loaded.by_norm == {}
