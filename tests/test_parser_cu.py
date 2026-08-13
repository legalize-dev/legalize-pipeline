"""Tests for the Cuban Gaceta Oficial parser (fetcher/cu/).

Fixtures live under ``tests/fixtures/cu/`` as raw Gaceta Oficial PDFs from
gacetaoficial.gob.cu (plus one MINJUS book edition). Each fixture exercises
a different document type:

* ``sample-constitucion``         — Constitution (Constitucion-2019)
* ``sample-bienestar-animal``     — Decreto-Ley (DL-31/2021)
* ``sample-codigo-seguridad-vial`` — MINJUS book edition (Ley-109/2010)
* ``sample-codigo-civil``         — Consolidated code with ``bis`` articles (Ley-59/1987)
* ``sample-proceso-penal``        — Large Ley (Ley-143/2021, 840 articles)

These tests are the regression baseline for the parser. If they break after
a parser change, we want loud failures, not silent regressions in production.
"""

from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path

import pytest

from legalize.countries import (
    get_metadata_parser,
    get_text_parser,
)
from legalize.fetcher.cu.parser import (
    RANK_CODIGO,
    RANK_CONSTITUCION,
    RANK_DECRETO_LEY,
    RANK_LEY,
    GacetaMetadataParser,
    GacetaTextParser,
)
from legalize.fetcher.cu.pdf_extractor import _clean_line, _merge_hyphenated
from legalize.models import Block, NormStatus

FIXTURES = Path(__file__).parent / "fixtures" / "cu"


def _read(name: str) -> bytes:
    return (FIXTURES / f"{name}.pdf").read_bytes()


def _entry(**overrides: object) -> bytes:
    """Build a manifest entry (JSON bytes) for the metadata parser."""
    entry = {
        "url": "https://www.gacetaoficial.gob.cu/sites/default/files/goc-2021-o140_0.pdf",
        "title": "Ley No. 143 de 2021, Del Proceso Penal",
        "rank": "ley",
        "publication_date": "2021-12-07",
        "journal_issue": "No. 140 Ordinaria de 2021",
        "source": "https://www.gacetaoficial.gob.cu/es/algunas-legislaciones-cubanas",
    }
    entry.update(overrides)
    return json.dumps(entry, ensure_ascii=False).encode("utf-8")


# ─────────────────────────────────────────────
# Registry dispatch
# ─────────────────────────────────────────────


class TestRegistry:
    def test_text_parser_registered(self):
        parser = get_text_parser("cu")
        assert isinstance(parser, GacetaTextParser)

    def test_metadata_parser_registered(self):
        parser = get_metadata_parser("cu")
        assert isinstance(parser, GacetaMetadataParser)


# ─────────────────────────────────────────────
# Per-fixture parser tests
# ─────────────────────────────────────────────


class TestConstitucion2019:
    fixture = "sample-constitucion"
    norm_id = "Constitucion-2019"

    @pytest.fixture
    def text_blocks(self) -> list[Block]:
        return GacetaTextParser().parse_text(_read(self.fixture))

    @pytest.fixture
    def metadata(self):
        return GacetaMetadataParser().parse(
            _entry(
                title="Constitución de la República de Cuba",
                rank="constitucion",
                publication_date="2019-04-10",
                journal_issue="No. 5 Extraordinaria de 2019",
            ),
            self.norm_id,
        )

    def test_documented_gap_no_text_layer(self, text_blocks):
        # The Gaceta constitution PDF has no usable text layer (scanned).
        # This is a documented genuine gap, not a parser failure — the parser
        # emits a single empty Block so the norm still commits and renders as
        # clean frontmatter + empty body (matching the ground-truth file).
        assert len(text_blocks) == 1
        assert text_blocks[0].versions[0].paragraphs == ()

    def test_rank_is_constitucion(self, metadata):
        assert metadata.rank == RANK_CONSTITUCION

    def test_publication_date_2019_04_10(self, metadata):
        assert metadata.publication_date == date(2019, 4, 10)

    def test_identifier_is_filename_stem(self, metadata):
        assert metadata.identifier == self.norm_id


class TestBienestarAnimal:
    fixture = "sample-bienestar-animal"
    norm_id = "Decreto-Ley-31-2021-Bienestar-Animal"

    @pytest.fixture
    def text_blocks(self) -> list[Block]:
        return GacetaTextParser().parse_text(_read(self.fixture))

    @pytest.fixture
    def metadata(self):
        return GacetaMetadataParser().parse(
            _entry(
                title="Decreto-Ley No. 31 de 2021, De Bienestar Animal",
                rank="decreto_ley",
                publication_date="2021-04-10",
                journal_issue="No. 25 Extraordinaria de 2021",
            ),
            self.norm_id,
        )

    def test_produces_one_block(self, text_blocks):
        assert len(text_blocks) == 1

    def test_93_articles(self, text_blocks):
        articles = [p for p in text_blocks[0].versions[0].paragraphs if p.css_class == "articulo"]
        assert len(articles) == 93

    def test_has_chapters_and_sections(self, text_blocks):
        sections = [
            p
            for p in text_blocks[0].versions[0].paragraphs
            if p.css_class in ("titulo_tit", "capitulo_tit", "seccion")
        ]
        assert len(sections) > 20

    def test_rank_is_decreto_ley(self, metadata):
        assert metadata.rank == RANK_DECRETO_LEY

    def test_publication_date_2021_04_10(self, metadata):
        assert metadata.publication_date == date(2021, 4, 10)

    def test_journal_issue_in_extra(self, metadata):
        assert ("journal_issue", "No. 25 Extraordinaria de 2021") in metadata.extra


class TestCodigoSeguridadVial:
    fixture = "sample-codigo-seguridad-vial"
    norm_id = "Ley-109-2010-Codigo-Seguridad-Vial"

    @pytest.fixture
    def text_blocks(self) -> list[Block]:
        return GacetaTextParser().parse_text(_read(self.fixture))

    @pytest.fixture
    def metadata(self):
        return GacetaMetadataParser().parse(
            _entry(
                title="Ley 109/2010, Código de Seguridad Vial",
                rank="codigo",
                publication_date="2010-09-17",
                journal_issue="No. 40 Ordinaria de 2010",
            ),
            self.norm_id,
        )

    def test_324_articles(self, text_blocks):
        articles = [p for p in text_blocks[0].versions[0].paragraphs if p.css_class == "articulo"]
        assert len(articles) == 324

    def test_rank_is_codigo(self, metadata):
        assert metadata.rank == RANK_CODIGO

    def test_publication_date_2010_09_17(self, metadata):
        assert metadata.publication_date == date(2010, 9, 17)


class TestCodigoCivil:
    fixture = "sample-codigo-civil"
    norm_id = "Ley-59-1987-Codigo-Civil"

    @pytest.fixture
    def text_blocks(self) -> list[Block]:
        return GacetaTextParser().parse_text(_read(self.fixture))

    @pytest.fixture
    def metadata(self):
        return GacetaMetadataParser().parse(
            _entry(
                title="Ley No. 59 de 1987, Código Civil",
                rank="codigo",
                publication_date="1987-10-15",
                journal_issue="Extraordinaria de 15 de octubre de 1987",
                notes=(
                    "Consolidated edition actualizado 8 de noviembre de 2022; "
                    "repealed articles omitted from the source: 52, 448-465, 542-544."
                ),
            ),
            self.norm_id,
        )

    def test_528_articles(self, text_blocks):
        articles = [p for p in text_blocks[0].versions[0].paragraphs if p.css_class == "articulo"]
        assert len(articles) == 528

    def test_bis_articles_preserved(self, text_blocks):
        # The code carries added articles like Artículo 231 bis / 479 bis / 521 bis
        articles = [p for p in text_blocks[0].versions[0].paragraphs if p.css_class == "articulo"]
        bis = [p.text for p in articles if p.text.endswith(" bis")]
        assert "Artículo 231 bis" in bis
        assert "Artículo 479 bis" in bis
        assert len(bis) >= 3

    def test_rank_is_codigo(self, metadata):
        assert metadata.rank == RANK_CODIGO

    def test_publication_date_1987_10_15(self, metadata):
        assert metadata.publication_date == date(1987, 10, 15)

    def test_notes_in_extra(self, metadata):
        notes = [v for k, v in metadata.extra if k == "notes"]
        assert len(notes) == 1
        assert "Consolidated edition" in notes[0]

    def test_status_in_force(self, metadata):
        assert metadata.status == NormStatus.IN_FORCE


class TestProcesoPenal:
    fixture = "sample-proceso-penal"
    norm_id = "Ley-143-2021-Proceso-Penal"

    @pytest.fixture
    def text_blocks(self) -> list[Block]:
        return GacetaTextParser().parse_text(_read(self.fixture))

    @pytest.fixture
    def metadata(self):
        return GacetaMetadataParser().parse(_entry(), self.norm_id)

    def test_produces_one_block(self, text_blocks):
        assert len(text_blocks) == 1

    def test_840_articles(self, text_blocks):
        articles = [p for p in text_blocks[0].versions[0].paragraphs if p.css_class == "articulo"]
        assert len(articles) == 840

    def test_rank_is_ley(self, metadata):
        assert metadata.rank == RANK_LEY

    def test_publication_date_2021_12_07(self, metadata):
        assert metadata.publication_date == date(2021, 12, 7)

    def test_country_is_cu(self, metadata):
        assert metadata.country == "cu"

    def test_title_from_manifest(self, metadata):
        assert "Proceso Penal" in metadata.title

    def test_department_empty(self, metadata):
        assert metadata.department == ""


# ─────────────────────────────────────────────
# Bundle path — slicing knobs + Version date
# ─────────────────────────────────────────────


class TestBundleSlicing:
    def test_version_dated_from_bundle(self):
        """The bundle carries publication_date so the Version is dated."""
        pdf = _read("sample-codigo-seguridad-vial")
        bundle = {
            "pdf": base64.b64encode(pdf).decode("ascii"),
            "start_regex": "^LEY NÚMERO 109",
            "end_regex": "^CONSEJO DE MINISTROS$",
            "publication_date": "2010-09-17",
            "title": "Ley 109/2010, Código de Seguridad Vial",
        }
        data = json.dumps(bundle, ensure_ascii=False).encode("utf-8")
        blocks = GacetaTextParser().parse_text(data)
        assert blocks[0].versions[0].publication_date == date(2010, 9, 17)
        assert blocks[0].versions[0].effective_date == date(2010, 9, 17)

    def test_raw_bytes_version_placeholder_date(self):
        """Raw-bytes input falls back to the placeholder date (metadata
        corrects it downstream in the engine)."""
        blocks = GacetaTextParser().parse_text(_read("sample-proceso-penal"))
        assert blocks[0].versions[0].publication_date == date(1900, 1, 1)


# ─────────────────────────────────────────────
# Soft-hyphen word-split rejoin
# ─────────────────────────────────────────────


class TestSoftHyphenRejoin:
    """pymupdf marks word hyphenation with U+00AD; it must collapse the
    fragments so the text reads ``disposiciones`` not ``disposicio nes``."""

    def test_soft_split_rejoined_without_separator(self):
        assert _merge_hyphenated(["...de disposicio\xad", "nes normativas..."]) == [
            "...de disposiciones normativas..."
        ]

    def test_chained_soft_splits_collapse(self):
        # Two adjacent splits: disposicio + nes...concien + tizar
        raw = ["de disposicio\xad", "nes y a concien\xad", "tizar a todos"]
        assert _merge_hyphenated(raw) == ["de disposiciones y a concientizar a todos"]

    def test_dash_split_joined_keeping_hyphen(self):
        # A literal '-' may be a compound hyphen split across the break —
        # keep the hyphen so compounds survive (ground-truth parity).
        assert _merge_hyphenated(["hombre-animal-", "medioambiente"]) == [
            "hombre-animal-medioambiente"
        ]

    def test_split_never_absorbs_an_article_heading(self):
        raw = ["texto termi-", "Artículo 5", "cuerpo"]
        out = _merge_hyphenated(raw)
        assert out[0] == "texto termi-"
        assert out[1] == "Artículo 5"

    def test_split_never_absorbs_furniture(self):
        raw = ["columna derecha -", "Página 12", "continúa"]
        assert _merge_hyphenated(raw) == ["columna derecha -", "Página 12", "continúa"]


class TestLigatureNormalization:
    """MINJUS book editions typeset fi/fl as ligature glyphs (U+FB01/U+FB02);
    pymupdf inserts a space after them, so ``superﬁ cie`` must normalize to
    ``superficie``."""

    def test_ligature_fragment_merged(self):
        assert _clean_line("la superﬁ cie del contén") == "la superficie del contén"

    def test_ligature_plain_normalized(self):
        assert _clean_line("Tráﬁ co") == "Tráfico"
        assert _clean_line("deﬁ nir") == "definir"

    def test_ligature_fl_variant(self):
        assert _clean_line("conﬂ icto") == "conflicto"

    def test_soft_hyphen_plus_ligature(self):
        assert _clean_line("disposicio\xad") == "disposicio"


# ─────────────────────────────────────────────
# MetadataParser error handling
# ─────────────────────────────────────────────


class TestMetadataParserErrors:
    def test_empty_data_raises(self):
        with pytest.raises(ValueError):
            GacetaMetadataParser().parse(b"", "Ley-143-2021-Proceso-Penal")

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError):
            GacetaMetadataParser().parse(b"not json", "Ley-143-2021-Proceso-Penal")

    def test_missing_publication_date_raises(self):
        data = _entry(publication_date="")
        with pytest.raises(ValueError):
            GacetaMetadataParser().parse(data, "Ley-143-2021-Proceso-Penal")


# ─────────────────────────────────────────────
# Encoding hygiene — every text-bearing fixture
# ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "fixture",
    [
        "sample-bienestar-animal",
        "sample-codigo-civil",
        "sample-codigo-seguridad-vial",
        "sample-proceso-penal",
    ],
)
class TestEncodingHygiene:
    """No fixture should produce mojibake or invalid Unicode after extraction."""

    @pytest.fixture
    def joined_text(self, fixture):
        blocks = GacetaTextParser().parse_text(_read(fixture))
        if not blocks:
            return ""
        paragraphs = blocks[0].versions[0].paragraphs
        return "\n".join(p.text for p in paragraphs)

    def test_no_unicode_soft_hyphen(self, joined_text):
        assert "\u00ad" not in joined_text

    def test_no_replacement_char(self, joined_text):
        assert "\ufffd" not in joined_text

    def test_no_c0_control_chars(self, joined_text):
        import re

        assert not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", joined_text)

    def test_utf8_round_trip(self, joined_text):
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
        "sample-bienestar-animal",
        "sample-codigo-civil",
        "sample-codigo-seguridad-vial",
        "sample-proceso-penal",
    ],
)
class TestStructureInvariants:
    """Articles must appear in monotonic order, never duplicated."""

    @pytest.fixture
    def article_numbers(self, fixture) -> list[int]:
        import re

        blocks = GacetaTextParser().parse_text(_read(fixture))
        articles = [p for p in blocks[0].versions[0].paragraphs if p.css_class == "articulo"]
        nums = []
        for p in articles:
            m = re.match(r"^Artículo\s+(\d+)", p.text)
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
        assert article_numbers and article_numbers[0] == 1


# ─────────────────────────────────────────────
# Filesystem-safe identifier
# ─────────────────────────────────────────────


class TestIdentifier:
    @pytest.mark.parametrize(
        "norm_id",
        [
            "Ley-143-2021-Proceso-Penal",
            "Ley-59-1987-Codigo-Civil",
            "Ley-109-2010-Codigo-Seguridad-Vial",
            "Decreto-Ley-31-2021-Bienestar-Animal",
            "Constitucion-2019",
        ],
    )
    def test_no_unsafe_chars(self, norm_id):
        for ch in [":", " ", "/", "\\", "*", "?", '"', "<", ">", "|"]:
            assert ch not in norm_id, f"Unsafe char {ch!r} in identifier"
