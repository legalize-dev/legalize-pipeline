"""Tests for the Chilean BCN parser.

Runs against five real fixtures downloaded from leychile.cl on 2026-04-07:

- Constitution (Decreto 100, idNorma 242302)
- Código Tributario (Decreto Ley 830, idNorma 6374) — doubly-articulated code
- Ley 21180 Transformación Digital del Estado (idNorma 1138479) — recent law with annex
- Decreto 29/1978 (idNorma 258831) — fully repealed legacy decree
- Ley 21808 Subsidio Unificado de Empleo (idNorma 1222281) — carries embedded JPEG attachments
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from legalize.countries import get_metadata_parser, get_text_parser
from legalize.fetcher.cl.discovery import _parse_csv
from legalize.fetcher.cl.parser import (
    CLMetadataParser,
    CLTextParser,
    _clean_body_text,
    _collapse_title,
    _strip_article_prefix,
)
from legalize.models import NormMetadata, NormStatus
from legalize.transformer.frontmatter import render_frontmatter
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath

FIXTURES = Path(__file__).parent / "fixtures" / "cl"

CONSTITUTION = FIXTURES / "bcn-constitucion-242302.xml"
CODIGO_TRIBUTARIO = FIXTURES / "bcn-codigo-tributario-6374.xml"
LEY_21180 = FIXTURES / "bcn-ley-21180-1138479.xml"
DECRETO_29 = FIXTURES / "bcn-decreto-29-258831.xml"
LEY_21808 = FIXTURES / "bcn-ley-21808-1222281.xml"

ALL_FIXTURES = [
    ("242302", CONSTITUTION),
    ("6374", CODIGO_TRIBUTARIO),
    ("1138479", LEY_21180),
    ("258831", DECRETO_29),
    ("1222281", LEY_21808),
]


@pytest.fixture(scope="module")
def text_parser() -> CLTextParser:
    return CLTextParser()


@pytest.fixture(scope="module")
def meta_parser() -> CLMetadataParser:
    return CLMetadataParser()


# ─────────────────────────────────────────────
# Metadata parser — §0.3 inventory contract
# ─────────────────────────────────────────────


class TestCLMetadataConstitution:
    """The Constitution exercises the rank special-case and full frontmatter."""

    def test_identifier(self, meta_parser):
        meta = meta_parser.parse(CONSTITUTION.read_bytes(), "242302")
        assert meta.identifier == "CL-242302"
        assert meta.country == "cl"

    def test_title_is_yaml_safe(self, meta_parser):
        meta = meta_parser.parse(CONSTITUTION.read_bytes(), "242302")
        assert "CONSTITUCION POLITICA" in meta.title.upper()
        assert "\n" not in meta.title

    def test_short_title_uses_common_name(self, meta_parser):
        meta = meta_parser.parse(CONSTITUTION.read_bytes(), "242302")
        assert "CONSTITUCION POLITICA" in meta.short_title.upper()

    def test_rank_is_constitucion(self, meta_parser):
        meta = meta_parser.parse(CONSTITUTION.read_bytes(), "242302")
        assert str(meta.rank) == "constitucion"

    def test_publication_date(self, meta_parser):
        meta = meta_parser.parse(CONSTITUTION.read_bytes(), "242302")
        assert meta.publication_date == date(2005, 9, 22)

    def test_in_force(self, meta_parser):
        meta = meta_parser.parse(CONSTITUTION.read_bytes(), "242302")
        assert meta.status == NormStatus.IN_FORCE

    def test_department(self, meta_parser):
        meta = meta_parser.parse(CONSTITUTION.read_bytes(), "242302")
        assert "PRESIDENCIA" in meta.department

    def test_source_url_points_to_bcn(self, meta_parser):
        meta = meta_parser.parse(CONSTITUTION.read_bytes(), "242302")
        assert meta.source == "https://www.bcn.cl/leychile/navegar?idNorma=242302"

    def test_subjects_have_constitucion_tag(self, meta_parser):
        meta = meta_parser.parse(CONSTITUTION.read_bytes(), "242302")
        assert any("Constitución" in s for s in meta.subjects)

    def test_extra_captures_inventory_fields(self, meta_parser):
        meta = meta_parser.parse(CONSTITUTION.read_bytes(), "242302")
        extra = dict(meta.extra)
        # Every §0.3 field the XML exposes must live in extra.
        assert extra["bcn_schema_version"] == "1.0"
        assert extra["is_treaty"] == "no"
        assert extra["promulgation_date"] == "2005-09-17"
        assert extra["official_type"] == "Decreto"
        assert extra["official_number"] == "100"
        assert extra["gazette"] == "Diario Oficial"
        assert extra["gazette_issue_number"] == "38268"
        assert "transitory_parts" in extra  # Constitution has 55 transitory articles

    def test_extra_keys_are_snake_case_english(self, meta_parser):
        meta = meta_parser.parse(CONSTITUTION.read_bytes(), "242302")
        for key, _value in meta.extra:
            assert key == key.lower()
            assert " " not in key


class TestCLMetadataRepealedDecree:
    """Decreto 29/1978 exercises the repealed branch."""

    def test_status_is_repealed(self, meta_parser):
        meta = meta_parser.parse(DECRETO_29.read_bytes(), "258831")
        assert meta.status == NormStatus.REPEALED

    def test_repeal_date_captured(self, meta_parser):
        meta = meta_parser.parse(DECRETO_29.read_bytes(), "258831")
        assert dict(meta.extra)["repeal_date"] == "2007-02-19"

    def test_rank_decreto(self, meta_parser):
        meta = meta_parser.parse(DECRETO_29.read_bytes(), "258831")
        assert str(meta.rank) == "decreto"

    def test_title_collapses_embedded_newline(self, meta_parser):
        meta = meta_parser.parse(DECRETO_29.read_bytes(), "258831")
        assert "\n" not in meta.title
        assert "DECLARA NORMA OFICIAL" in meta.title
        assert "QUE INDICA" in meta.title


class TestCLMetadataLey:
    """Ordinary laws map to rank=ley and carry annex/binary metadata."""

    def test_ley_21180_rank(self, meta_parser):
        meta = meta_parser.parse(LEY_21180.read_bytes(), "1138479")
        assert str(meta.rank) == "ley"

    def test_ley_21180_has_annex_flag(self, meta_parser):
        meta = meta_parser.parse(LEY_21180.read_bytes(), "1138479")
        assert dict(meta.extra)["has_annex"] == "yes"

    def test_ley_21808_counts_dropped_images(self, meta_parser):
        meta = meta_parser.parse(LEY_21808.read_bytes(), "1222281")
        extra = dict(meta.extra)
        assert extra["images_dropped"] == "2"

    def test_ley_21808_official_number(self, meta_parser):
        meta = meta_parser.parse(LEY_21808.read_bytes(), "1222281")
        assert dict(meta.extra)["official_number"] == "21808"


class TestCLMetadataCodigoTributario:
    """Decreto Ley rank + subjects inherited from the norm-level Metadatos."""

    def test_rank_is_decreto_ley(self, meta_parser):
        meta = meta_parser.parse(CODIGO_TRIBUTARIO.read_bytes(), "6374")
        assert str(meta.rank) == "decreto_ley"

    def test_publication_date(self, meta_parser):
        meta = meta_parser.parse(CODIGO_TRIBUTARIO.read_bytes(), "6374")
        assert meta.publication_date == date(1974, 12, 31)


# ─────────────────────────────────────────────
# Text parser — structure + hygiene
# ─────────────────────────────────────────────


class TestCLTextParserStructure:
    def test_constitution_has_encabezado_and_promulgacion(self, text_parser):
        blocks = text_parser.parse_text(CONSTITUTION.read_bytes())
        block_types = [b.block_type for b in blocks]
        assert "encabezado" in block_types
        assert "promulgacion" in block_types
        assert any(bt in {"capitulo", "titulo", "libro"} for bt in block_types)
        assert any(b.block_type == "articulo" for b in blocks)

    def test_constitution_article_one_body_has_no_prefix(self, text_parser):
        blocks = text_parser.parse_text(CONSTITUTION.read_bytes())
        art1 = next(b for b in blocks if b.block_type == "articulo" and b.title == "Artículo 1")
        body_paragraphs = [p.text for p in art1.versions[0].paragraphs if p.css_class == "parrafo"]
        full = " ".join(body_paragraphs)
        # The redundant "Artículo 1°.- " prefix must be stripped from the body.
        assert not full.lstrip().startswith("Artículo 1")
        assert "personas nacen libres" in full

    def test_capitulo_container_has_no_duplicate_body(self, text_parser):
        """Container headings render once, not twice (body was an echo)."""
        blocks = text_parser.parse_text(CONSTITUTION.read_bytes())
        cap = next(
            b
            for b in blocks
            if b.block_type == "capitulo" and "BASES DE LA INSTITUCIONALIDAD" in b.title
        )
        # Container block carries a single heading paragraph, no body.
        paragraphs = cap.versions[0].paragraphs
        assert len(paragraphs) == 1
        assert paragraphs[0].css_class in {"titulo_tit", "capitulo_tit"}

    def test_codigo_tributario_strips_del_art_suffix(self, text_parser):
        blocks = text_parser.parse_text(CODIGO_TRIBUTARIO.read_bytes())
        articles = [b for b in blocks if b.block_type == "articulo"]
        # "(DEL ART. 1)" suffix must not appear in any heading.
        assert all("DEL ART" not in b.title.upper() for b in articles)

    def test_codigo_tributario_has_libro_and_titulo_headings(self, text_parser):
        blocks = text_parser.parse_text(CODIGO_TRIBUTARIO.read_bytes())
        block_types = {b.block_type for b in blocks}
        assert "libro" in block_types
        assert "titulo" in block_types
        assert "parrafo_group" in block_types

    def test_ley_21180_emits_annex_block(self, text_parser):
        blocks = text_parser.parse_text(LEY_21180.read_bytes())
        annexes = [b for b in blocks if b.block_type == "anexo"]
        assert len(annexes) == 1
        assert annexes[0].versions[0].paragraphs, "annex must have content"

    def test_ley_21808_drops_binary_inserts_placeholder(self, text_parser):
        blocks = text_parser.parse_text(LEY_21808.read_bytes())
        all_text = "\n".join(p.text for b in blocks for v in b.versions for p in v.paragraphs)
        assert "[imagen omitida]" in all_text
        # No base64 payload should leak through.
        assert "/9j/4AAQSkZJRgABAQ" not in all_text

    def test_decreto_29_promulgacion_multi_signatory(self, text_parser):
        blocks = text_parser.parse_text(DECRETO_29.read_bytes())
        prom = next(b for b in blocks if b.block_type == "promulgacion")
        firmas = [p.text for p in prom.versions[0].paragraphs if p.css_class == "firma_rey"]
        assert len(firmas) >= 2  # "Anótese..." + "Lo que transcribo..."


class TestEncodingHygiene:
    @pytest.mark.parametrize("norm_id,path", ALL_FIXTURES)
    def test_no_control_characters_in_blocks(self, text_parser, norm_id, path):
        blocks = text_parser.parse_text(path.read_bytes())
        for block in blocks:
            for version in block.versions:
                for p in version.paragraphs:
                    import re

                    assert re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", p.text) is None, (
                        f"control char in {norm_id}"
                    )
                    assert "\u00a0" not in p.text, f"NBSP leaked in {norm_id}"

    @pytest.mark.parametrize("norm_id,path", ALL_FIXTURES)
    def test_rendered_markdown_is_utf8_clean(self, text_parser, meta_parser, norm_id, path):
        meta = meta_parser.parse(path.read_bytes(), norm_id)
        blocks = text_parser.parse_text(path.read_bytes())
        md = render_norm_at_date(meta, blocks, date.today(), include_all=True)
        # UTF-8 roundtrip
        md.encode("utf-8").decode("utf-8")
        import re

        assert re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", md) is None


# ─────────────────────────────────────────────
# Frontmatter / rendering integration
# ─────────────────────────────────────────────


class TestFrontmatterRendering:
    @pytest.mark.parametrize("norm_id,path", ALL_FIXTURES)
    def test_frontmatter_is_valid_yaml(self, meta_parser, norm_id, path):
        import re

        import yaml

        meta = meta_parser.parse(path.read_bytes(), norm_id)
        fm = render_frontmatter(meta, date.today())
        match = re.match(r"^---\n(.*?)\n---\n", fm, re.DOTALL)
        assert match, f"frontmatter missing boundaries for {norm_id}"
        loaded = yaml.safe_load(match.group(1))
        assert loaded["identifier"] == f"CL-{norm_id}"
        assert loaded["country"] == "cl"
        assert loaded["status"] in {"in_force", "repealed"}

    @pytest.mark.parametrize("norm_id,path", ALL_FIXTURES)
    def test_frontmatter_includes_core_fields(self, meta_parser, norm_id, path):
        meta = meta_parser.parse(path.read_bytes(), norm_id)
        fm = render_frontmatter(meta, date.today())
        for required in (
            "title:",
            "identifier:",
            "country:",
            "rank:",
            "publication_date:",
            "last_updated:",
            "status:",
            "source:",
            "bcn_schema_version:",
            "official_type:",
        ):
            assert required in fm, f"{required} missing for {norm_id}"


# ─────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────


class TestCleanBodyText:
    """Margin-annotation stripper must not eat legal text."""

    def test_strips_cpr_margin_refs(self):
        raw = (
            "     La familia es el núcleo                  CPR Art. 1° D.O.\n"
            "fundamental de la sociedad.                                         24.10.1980"
        )
        cleaned = _clean_body_text(raw)
        assert "CPR Art." not in cleaned
        assert "24.10.1980" not in cleaned
        assert "familia" in cleaned

    def test_strips_ley_margin_refs(self):
        raw = (
            "     El Estado reconoce y ampara a los grupos intermedios a         LEY N° 19.611 Art.\n"
            "través de los cuales se organiza y estructura la sociedad y         único\n"
            "les garantiza la adecuada autonomía                                Nº1 D.O. 16.06.1999"
        )
        cleaned = _clean_body_text(raw)
        assert "LEY N°" not in cleaned
        assert "16.06.1999" not in cleaned
        assert "Estado reconoce" in cleaned
        assert "autonomía" in cleaned

    def test_preserves_reform_quoted_text(self):
        raw = (
            '"Artículo 1°.- Introdúcense las siguientes modificaciones en la '
            "Ley N° 19.640, Orgánica Constitucional del Ministerio Público:"
        )
        cleaned = _clean_body_text(raw)
        assert "Ministerio Público" in cleaned
        assert "Introdúcense" in cleaned

    def test_strips_nbsp_and_controls(self):
        raw = "Texto con\u00a0nbsp y \x01 control."
        cleaned = _clean_body_text(raw)
        assert "\u00a0" not in cleaned
        assert "\x01" not in cleaned
        assert "Texto con nbsp" in cleaned


class TestCollapseTitle:
    def test_collapses_embedded_newline(self):
        raw = "DECLARA NORMA OFICIAL\nQUE INDICA\nY DEJA SIN EFECTO"
        assert _collapse_title(raw) == "DECLARA NORMA OFICIAL QUE INDICA Y DEJA SIN EFECTO"


class TestArticlePrefixStripping:
    def test_strips_numeric_prefix(self):
        assert (
            _strip_article_prefix("Artículo 1°.- Las personas nacen libres e iguales.", "Artículo")
            == "Las personas nacen libres e iguales."
        )

    def test_strips_ordinal_prefix(self):
        assert (
            _strip_article_prefix("Artículo primero.- Facúltase al Presidente...", "Artículo")
            == "Facúltase al Presidente..."
        )

    def test_preserves_opening_quote(self):
        # Reform bodies are often wholly quoted; the opening quote must survive.
        stripped = _strip_article_prefix('"Artículo 1°.- Introdúcense modificaciones.', "Artículo")
        assert stripped.startswith('"Introdúcense')

    def test_does_not_strip_non_article_text(self):
        assert _strip_article_prefix("Esta ley entra en vigencia.", "Artículo") == (
            "Esta ley entra en vigencia."
        )

    def test_no_op_for_container_types(self):
        assert _strip_article_prefix("Artículo 1°.- foo", "Capítulo") == ("Artículo 1°.- foo")


# ─────────────────────────────────────────────
# Discovery CSV parser
# ─────────────────────────────────────────────


class TestCSVParsing:
    def test_parse_csv_with_bom(self):
        csv_bytes = (
            b'\xef\xbb\xbf"Identificaci\xc3\xb3n de la Norma";"Tipo Norma";"T\xc3\xadtulo de la Norma"\n'
            b'"1222840";"Ley";"MODIFICA DIVERSOS CUERPOS LEGALES"\n'
            b'"1222799";"Ley";"SOBRE CONVIVENCIA"'
        )
        rows = _parse_csv(csv_bytes)
        assert len(rows) == 2
        assert rows[0]["Identificación de la Norma"] == "1222840"
        assert rows[0]["Tipo Norma"] == "Ley"

    def test_parse_csv_empty(self):
        assert _parse_csv(b"") == []

    def test_parse_csv_header_only(self):
        csv_bytes = '\ufeff"Identificación de la Norma";"Tipo Norma"\n'.encode("utf-8-sig")
        assert _parse_csv(csv_bytes) == []

    def test_parse_real_fixture(self):
        path = FIXTURES / "bcn-search-leyes-sample.csv"
        rows = _parse_csv(path.read_bytes())
        assert len(rows) >= 1
        assert rows[0]["Tipo Norma"] == "Ley"
        assert rows[0]["Identificación de la Norma"].isdigit()


# ─────────────────────────────────────────────
# Country registry dispatch
# ─────────────────────────────────────────────


class TestCountriesDispatch:
    def test_get_text_parser_cl(self):
        parser = get_text_parser("cl")
        assert isinstance(parser, CLTextParser)

    def test_get_metadata_parser_cl(self):
        parser = get_metadata_parser("cl")
        assert isinstance(parser, CLMetadataParser)


class TestSlugChile:
    def test_norm_path(self):
        meta = NormMetadata(
            title="Test",
            short_title="Test",
            identifier="CL-242302",
            country="cl",
            rank="constitucion",
            publication_date=date(2005, 9, 22),
            status=NormStatus.IN_FORCE,
            department="BCN",
            source="https://www.bcn.cl/leychile/navegar?idNorma=242302",
        )
        assert norm_to_filepath(meta) == "cl/CL-242302.md"
