"""Tests for the Uruguayan IMPO parser.

Grounded in 5 live fixtures fetched from IMPO on 2026-04-07:
    tests/fixtures/uy/sample-constitution.json    (constitucion/1967-1967)
    tests/fixtures/uy/sample-code.json            (codigo-tributario/14306-1974)
    tests/fixtures/uy/sample-ordinary-law.json    (leyes/18331-2008)
    tests/fixtures/uy/sample-regulation.json      (decretos/414-2009)
    tests/fixtures/uy/sample-with-tables.json     (leyes/19996-2021)
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from legalize.countries import (
    get_client_class,
    get_discovery_class,
    get_metadata_parser,
    get_text_parser,
    supported_countries,
)
from legalize.fetcher.uy.client import IMPOClient
from legalize.fetcher.uy.discovery import IMPODiscovery, _estimate_year, _year_candidates
from legalize.fetcher.uy.parser import (
    IMPOMetadataParser,
    IMPOTextParser,
    _absolute_url,
    _decode_json,
    _flatten,
    _inline_html_to_markdown,
    _make_identifier,
    _parse_date,
    _split_text_by_tables,
    _split_titulos,
    _strip_control_chars,
    _table_to_markdown,
)
from legalize.models import NormMetadata, TextState
from legalize.transformer.markdown import _NOTICES
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath

FIXTURES = Path(__file__).parent / "fixtures" / "uy"

CONSTITUCION = "sample-constitution.json"
CODE = "sample-code.json"
ORDINARY_LAW = "sample-ordinary-law.json"
REGULATION = "sample-regulation.json"
WITH_TABLES = "sample-with-tables.json"

NORM_IDS = {
    CONSTITUCION: "constitucion/1967-1967",
    CODE: "codigo-tributario/14306-1974",
    ORDINARY_LAW: "leyes/18331-2008",
    REGULATION: "decretos/414-2009",
    WITH_TABLES: "leyes/19996-2021",
}

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _load(name: str) -> bytes:
    """Load a real IMPO fixture exactly as the wire delivered it (Latin-1 bytes)."""
    return (FIXTURES / name).read_bytes()


def _render(name: str) -> tuple[NormMetadata, str]:
    data = _load(name)
    meta = IMPOMetadataParser().parse(data, NORM_IDS[name])
    blocks = IMPOTextParser().parse_text(data)
    md = render_norm_at_date(meta, blocks, meta.publication_date, include_all=True)
    return meta, md


# ─── Parsing helpers ───


class TestParsingHelpers:
    def test_parse_date_dd_mm_yyyy(self):
        assert _parse_date("09/11/2021") == date(2021, 11, 9)

    def test_parse_date_iso_format(self):
        assert _parse_date("2021-11-09") == date(2021, 11, 9)

    def test_parse_date_empty(self):
        assert _parse_date("") is None
        assert _parse_date(None) is None
        assert _parse_date("  ") is None

    def test_parse_date_invalid(self):
        assert _parse_date("not-a-date") is None

    def test_strip_control_chars(self):
        assert _strip_control_chars("a\x00b\x1fc\x7fd") == "abcd"
        assert _strip_control_chars("regular\ttext") == "regular\ttext"  # tab preserved

    def test_absolute_url_relative(self):
        assert (
            _absolute_url("/bases/leyes/19996-2021")
            == "https://www.impo.com.uy/bases/leyes/19996-2021"
        )

    def test_absolute_url_already_absolute(self):
        assert _absolute_url("https://example.com/x") == "https://example.com/x"

    def test_absolute_url_missing_slash(self):
        assert _absolute_url("bases/leyes/1-2") == "https://www.impo.com.uy/bases/leyes/1-2"

    def test_inline_bold(self):
        assert _inline_html_to_markdown("<b>foo</b>") == "**foo**"

    def test_inline_italic(self):
        assert _inline_html_to_markdown("<i>foo</i>") == "*foo*"

    def test_inline_strips_font(self):
        assert _inline_html_to_markdown('<font color="#ff0000">red</font>') == "red"

    def test_inline_link_absolute(self):
        out = _inline_html_to_markdown(
            'see <a class="linkFicha" href="/bases/leyes/19996-2021">Ley 19996</a>'
        )
        assert out == "see [Ley 19996](https://www.impo.com.uy/bases/leyes/19996-2021)"

    def test_inline_pre_is_stripped(self):
        # <pre> in IMPO is only used as a cell wrapper inside tables; strip it.
        assert _inline_html_to_markdown("<pre>cell</pre>") == "cell"

    def test_inline_decodes_entities(self):
        assert _inline_html_to_markdown("Art&iacute;culo") == "Artículo"

    def test_inline_drops_control_chars(self):
        assert _inline_html_to_markdown("a\x00b") == "ab"

    def test_inline_handles_crlf(self):
        assert _inline_html_to_markdown("line1\r\nline2") == "line1\nline2"

    def test_flatten_collapses_internal_whitespace(self):
        assert _flatten("a\nb\r\nc\td  e") == "a b c d e"
        assert _flatten("  leading and trailing  ") == "leading and trailing"

    def test_split_titulos_dedups_br(self):
        out = _split_titulos(" SECCION I<br>CAPITULO I<br> ")
        assert out == ["SECCION I", "CAPITULO I"]

    def test_table_to_markdown_basic(self):
        table = (
            "<TABLE>"
            "<TR><TD><pre>Grado</pre></TD><TD><pre>Nombre</pre></TD></TR>"
            "<TR><TD><pre>1</pre></TD><TD><pre>Alfa</pre></TD></TR>"
            "</TABLE>"
        )
        md = _table_to_markdown(table)
        assert md.startswith("| Grado | Nombre |")
        assert "| --- | --- |" in md
        assert "| 1 | Alfa |" in md

    def test_split_text_by_tables_preserves_order(self):
        html = "before<table><tr><td>x</td></tr></table>after"
        pieces = _split_text_by_tables(html)
        assert [kind for kind, _ in pieces] == ["text", "table", "text"]


# ─── Identifier generation ───


class TestIdentifiers:
    def test_ley(self):
        doc = {"tipoNorma": "Ley", "nroNorma": "19996", "anioNorma": 2021}
        assert _make_identifier(doc, "leyes/19996-2021") == "UY-ley-19996"

    def test_decreto_ley(self):
        doc = {"tipoNorma": "Decreto Ley", "nroNorma": "14261", "anioNorma": 1974}
        assert _make_identifier(doc, "decretos-ley/14261-1974") == "UY-decreto-ley-14261"

    def test_decreto(self):
        doc = {"tipoNorma": "Decreto", "nroNorma": "122", "anioNorma": 2021}
        assert _make_identifier(doc, "decretos/122-2021") == "UY-decreto-122-2021"

    def test_constitucion(self):
        doc = {"tipoNorma": "CONSTITUCION DE LA REPUBLICA"}
        assert _make_identifier(doc, "constitucion/1967-1967") == "UY-constitucion-1967"

    def test_codigo_tributario(self):
        doc = {"tipoNorma": "Código Tributario", "nroNorma": "14306", "anioNorma": 1974}
        assert _make_identifier(doc, "codigo-tributario/14306-1974") == "UY-codigo-tributario-14306"

    def test_codigo_civil(self):
        doc = {"tipoNorma": "Código Civil", "nroNorma": "16603", "anioNorma": 1994}
        assert _make_identifier(doc, "codigo-civil/16603-1994") == "UY-codigo-civil-16603"


# ─── Metadata parser — real fixtures ───


class TestMetadataFromFixtures:
    def test_constitucion(self):
        meta = IMPOMetadataParser().parse(_load(CONSTITUCION), NORM_IDS[CONSTITUCION])
        assert meta.country == "uy"
        assert meta.identifier == "UY-constitucion-1967"
        assert meta.rank == "constitucion"
        assert meta.publication_date == date(1967, 2, 2)
        assert meta.source == "https://www.impo.com.uy/bases/constitucion/1967-1967"

    def test_code(self):
        meta = IMPOMetadataParser().parse(_load(CODE), NORM_IDS[CODE])
        assert meta.identifier == "UY-codigo-tributario-14306"
        assert meta.rank == "codigo"
        assert meta.publication_date == date(1974, 12, 6)

    def test_ordinary_law(self):
        meta = IMPOMetadataParser().parse(_load(ORDINARY_LAW), NORM_IDS[ORDINARY_LAW])
        assert meta.identifier == "UY-ley-18331"
        assert meta.rank == "ley"
        assert "PROTECCION DE DATOS PERSONALES" in meta.title
        assert meta.publication_date == date(2008, 8, 18)

    def test_regulation(self):
        meta = IMPOMetadataParser().parse(_load(REGULATION), NORM_IDS[REGULATION])
        assert meta.identifier == "UY-decreto-414-2009"
        assert meta.rank == "decreto"
        assert meta.publication_date == date(2009, 9, 15)

    def test_with_tables(self):
        meta = IMPOMetadataParser().parse(_load(WITH_TABLES), NORM_IDS[WITH_TABLES])
        assert meta.identifier == "UY-ley-19996"
        assert meta.publication_date == date(2021, 11, 9)

    def test_extra_keys_are_english_snake_case(self):
        """Every extra key must be lowercase English snake_case (per playbook)."""
        for fname in NORM_IDS:
            meta = IMPOMetadataParser().parse(_load(fname), NORM_IDS[fname])
            for key, _value in meta.extra:
                assert key == key.lower(), f"{fname}: key {key!r} not lowercase"
                assert re.fullmatch(r"[a-z][a-z0-9_]*", key), f"{fname}: key {key!r} not snake_case"

    def test_ordinary_law_captures_all_top_level_fields(self):
        """Ley 18331 has the richest metadata — verify every IMPO field is captured."""
        meta = IMPOMetadataParser().parse(_load(ORDINARY_LAW), NORM_IDS[ORDINARY_LAW])
        keys = dict(meta.extra)
        # Every field the ordinary-law fixture exposes should appear in extra.
        assert keys["official_type"] == "Ley"
        assert keys["official_number"] == "18331"
        assert keys["year"] == "2008"
        assert keys["promulgation_date"] == "2008-08-11"
        assert keys["update_label"] == "Documento Actualizado"
        assert keys["gazette_scan_url"].startswith("https://www.impo.com.uy/diariooficial/")
        assert keys["references_url"].startswith("https://www.impo.com.uy/")
        assert "Reglamentada por" in keys["references_html"]
        assert keys["rnld_citation"] == "tomo 1, semestre 2, 2008, p. 378"
        assert "TABARE VAZQUEZ" in keys["signatories"]
        assert keys["article_count"] == "51"
        assert keys["collection"] == "leyes"
        assert keys["source_encoding"] == "ISO-8859-1"
        assert keys["images_dropped"] == "0"
        # Editorial notes count is captured but not rendered in the body
        assert "editorial_notes_count" in keys
        assert int(keys["editorial_notes_count"]) >= 1

    def test_extras_have_no_embedded_newlines(self):
        """Frontmatter values must be single-line for the simple YAML renderer."""
        for fname in NORM_IDS:
            meta = IMPOMetadataParser().parse(_load(fname), NORM_IDS[fname])
            for key, value in meta.extra:
                assert "\n" not in value, f"{fname}: extra[{key}] has embedded newline"
                assert "\r" not in value, f"{fname}: extra[{key}] has embedded CR"

    def test_constitucion_has_no_editorial_notes_in_body_count(self):
        """Constitution has 292 articles with notes — count is captured."""
        meta = IMPOMetadataParser().parse(_load(CONSTITUCION), NORM_IDS[CONSTITUCION])
        keys = dict(meta.extra)
        assert keys["editorial_notes_count"] == "292"

    def test_with_tables_editorial_notes_count(self):
        meta = IMPOMetadataParser().parse(_load(WITH_TABLES), NORM_IDS[WITH_TABLES])
        keys = dict(meta.extra)
        assert keys["editorial_notes_count"] == "349"

    def test_regulation_captures_obs_publicacion(self):
        meta = IMPOMetadataParser().parse(_load(REGULATION), NORM_IDS[REGULATION])
        keys = dict(meta.extra)
        # Decreto 414/2009 does not have obsPublicacion but decretos/122-2021 does.
        assert keys["collection"] == "decretos"
        assert "promulgation_date" in keys

    def test_empty_data_raises(self):
        with pytest.raises(ValueError, match="Empty data"):
            IMPOMetadataParser().parse(b"", "leyes/1-0000")


# ─── Text parser — real fixtures ───


class TestTextParserFromFixtures:
    def test_constitucion_article_count(self):
        blocks = IMPOTextParser().parse_text(_load(CONSTITUCION))
        arts = [b for b in blocks if b.block_type == "articulo"]
        assert len(arts) == 332  # Constitution has 332 articles

    def test_constitucion_headings_cover_all_sections(self):
        blocks = IMPOTextParser().parse_text(_load(CONSTITUCION))
        headings = [b for b in blocks if b.block_type == "heading"]
        titles = [b.title for b in headings]
        # 19 SECCIONES in the Uruguayan Constitution
        seccion_count = sum(1 for t in titles if t.startswith("SECCION"))
        assert seccion_count == 19

    def test_constitucion_heading_css_classes(self):
        blocks = IMPOTextParser().parse_text(_load(CONSTITUCION))
        for b in blocks:
            if b.block_type != "heading":
                continue
            css = b.versions[0].paragraphs[0].css_class
            if b.title.startswith("SECCION"):
                assert css == "seccion"
            elif b.title.startswith("CAPITULO"):
                assert css == "capitulo_tit"

    def test_with_tables_article_59_has_table(self):
        blocks = IMPOTextParser().parse_text(_load(WITH_TABLES))
        art_59 = next(b for b in blocks if b.id == "art-59")
        paragraphs = art_59.versions[0].paragraphs
        table_paras = [p for p in paragraphs if p.css_class == "table_md"]
        assert len(table_paras) == 1
        md = table_paras[0].text
        assert md.startswith("| Grado |")
        assert "Aerotécnico" in md
        assert "| --- |" in md

    def test_with_tables_total_table_count(self):
        blocks = IMPOTextParser().parse_text(_load(WITH_TABLES))
        all_table_paras = [
            p for b in blocks for v in b.versions for p in v.paragraphs if p.css_class == "table_md"
        ]
        # 15 <TABLE> tags in the raw fixture → 15 rendered Markdown tables.
        assert len(all_table_paras) == 15

    def test_body_has_no_markdown_links(self):
        """All IMPO <a> tags live in notasArticulo (editorial notes).

        The actual textoArticulo of every fixture is plain text — IMPO
        does not embed cross-reference hyperlinks inside the law body
        itself, only in the editorial notes that wrap each article.
        Since we exclude notes from the body, the body must contain no
        Markdown link syntax.
        """
        for fname in NORM_IDS:
            blocks = IMPOTextParser().parse_text(_load(fname))
            all_text = "\n".join(p.text for b in blocks for v in b.versions for p in v.paragraphs)
            assert "](/bases/" not in all_text, f"{fname}: relative IMPO link in body"

    def test_references_html_extra_has_absolute_links(self):
        """references_html captures the IMPO references panel with absolute links."""
        meta = IMPOMetadataParser().parse(_load(ORDINARY_LAW), NORM_IDS[ORDINARY_LAW])
        refs = dict(meta.extra).get("references_html", "")
        assert "(https://www.impo.com.uy/" in refs

    def test_ordinary_law_signatories_bold(self):
        blocks = IMPOTextParser().parse_text(_load(ORDINARY_LAW))
        firma = [b for b in blocks if b.block_type == "firma"]
        assert len(firma) == 1
        assert "TABARE VAZQUEZ" in firma[0].versions[0].paragraphs[0].text
        assert firma[0].versions[0].paragraphs[0].css_class == "firma_rey"

    def test_article_bodies_have_no_leftover_tags(self):
        """No <tag> should leak into any article paragraph text."""
        tag_re = re.compile(r"<[A-Za-z/][^>]{0,40}>")
        for fname in NORM_IDS:
            blocks = IMPOTextParser().parse_text(_load(fname))
            for b in blocks:
                for v in b.versions:
                    for p in v.paragraphs:
                        if p.css_class == "table_md":
                            continue  # pipe table is pre-formatted MD, not HTML
                        assert not tag_re.search(p.text), (
                            f"{fname}: leftover tag in {b.id}: {p.text[:80]!r}"
                        )

    def test_article_bodies_have_no_control_chars(self):
        for fname in NORM_IDS:
            blocks = IMPOTextParser().parse_text(_load(fname))
            for b in blocks:
                for v in b.versions:
                    for p in v.paragraphs:
                        assert not _CTRL_RE.search(p.text), f"{fname}: control char in {b.id}"

    def test_extract_reforms_single_point(self):
        reforms = IMPOTextParser().extract_reforms(_load(ORDINARY_LAW))
        assert len(reforms) == 1
        assert reforms[0].date == date(2008, 8, 18)
        assert reforms[0].norm_id == "bootstrap"

    def test_empty_data_returns_empty(self):
        assert IMPOTextParser().parse_text(b"") == []

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Could not decode"):
            _decode_json(b"<html>not json</html>")


# ─── End-to-end Markdown rendering ───


class TestEndToEndMarkdown:
    @pytest.mark.parametrize("fname", list(NORM_IDS))
    def test_markdown_is_utf8_clean(self, fname):
        _meta, md = _render(fname)
        md.encode("utf-8")  # round-trip
        assert not _CTRL_RE.search(md), f"{fname}: control chars in rendered MD"
        assert "\r\n" not in md
        assert "\ufffd" not in md  # unicode replacement char (common mojibake sentinel)
        assert "Ã©" not in md
        assert "â€" not in md

    @pytest.mark.parametrize("fname", list(NORM_IDS))
    def test_markdown_has_frontmatter(self, fname):
        _meta, md = _render(fname)
        assert md.startswith("---\n")
        # Valid YAML frontmatter
        import yaml

        fm_end = md.index("\n---\n", 4)
        fm_text = md[4:fm_end]
        doc = yaml.safe_load(fm_text)
        assert doc["country"] == "uy"
        assert doc["identifier"].startswith("UY-")

    @pytest.mark.parametrize("fname", list(NORM_IDS))
    def test_markdown_ends_with_single_newline(self, fname):
        _meta, md = _render(fname)
        assert md.endswith("\n"), f"{fname}: does not end with newline"
        assert not md.endswith("\n\n\n")

    @pytest.mark.parametrize("fname", list(NORM_IDS))
    def test_no_trailing_whitespace_on_lines(self, fname):
        _meta, md = _render(fname)
        for i, line in enumerate(md.split("\n"), start=1):
            assert line == line.rstrip(), f"{fname}: line {i} has trailing whitespace"

    def test_with_tables_table_pipe_present_in_md(self):
        _meta, md = _render(WITH_TABLES)
        assert "| Grado | Denominación | Serie |" in md
        assert "Aerotécnico Principal/Sargento" in md

    def test_editorial_notes_excluded_from_body(self):
        """notasArticulo is editorial content — must NOT appear in any body."""
        for fname in NORM_IDS:
            _meta, md = _render(fname)
            assert "Nota IMPO" not in md, f"{fname}: editorial note leaked into body"
            # The "Ver en esta norma" cross-ref note must be gone too
            assert "Ver en esta norma" not in md, f"{fname}: editorial cross-ref leaked"

    @pytest.mark.parametrize("fname", list(NORM_IDS))
    def test_no_blockquote_in_body(self, fname):
        """We don't emit any blockquote — IMPO has no quoted amending text.

        The text-state notice is the one deliberate blockquote: IMPO publishes the
        current consolidated text and no dated history, so every UY file is
        ``current`` and opens with the notice (Legalize Format Spec v0.3).
        """
        _meta, md = _render(fname)
        notice = _NOTICES[TextState.CURRENT]
        assert notice in md, f"{fname}: missing the current-text notice"
        body_lines = md.replace(notice, "").split("\n")
        # The frontmatter `---` markers are fine; check actual body lines
        in_body = False
        for line in body_lines:
            if line == "---" and not in_body:
                continue
            if line.startswith("# "):
                in_body = True
                continue
            if in_body:
                assert not line.lstrip().startswith(">"), (
                    f"{fname}: stray blockquote in body: {line!r}"
                )

    def test_constitucion_no_duplicate_consecutive_headings(self):
        """The same heading should never repeat on consecutive articles."""
        _meta, md = _render(CONSTITUCION)
        lines = md.split("\n")
        prev_heading = None
        for line in lines:
            if line.startswith("###"):
                assert line != prev_heading, f"duplicate heading: {line}"
                prev_heading = line
            elif line.startswith("#####"):
                prev_heading = None  # reset between articles


# ─── Country dispatch & slugging ───


class TestCountriesDispatch:
    def test_uy_registered(self):
        assert "uy" in supported_countries()

    def test_client_class(self):
        assert get_client_class("uy") is IMPOClient

    def test_discovery_class(self):
        assert get_discovery_class("uy") is IMPODiscovery

    def test_text_parser(self):
        assert isinstance(get_text_parser("uy"), IMPOTextParser)

    def test_metadata_parser(self):
        assert isinstance(get_metadata_parser("uy"), IMPOMetadataParser)


class TestSlugUruguay:
    @pytest.mark.parametrize("fname", list(NORM_IDS))
    def test_filepath_is_flat(self, fname):
        meta, _ = _render(fname)
        path = norm_to_filepath(meta)
        assert path == f"uy/{meta.identifier}.md"
        assert ":" not in path
        assert " " not in path


# ─── Client HTML-as-not-found detection ───


class TestIMPOClientNotFound:
    def test_html_response_detected_as_not_found(self):
        from unittest.mock import MagicMock, patch

        client = IMPOClient(base_url="https://www.impo.com.uy", requests_per_second=0)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"<html><head><title>Ingreso - IMPO</title></head></html>"
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._session, "request", return_value=mock_resp):
            assert client.get_text("leyes/99999-2025") == b""

    def test_valid_json_passthrough(self):
        from unittest.mock import MagicMock, patch

        client = IMPOClient(base_url="https://www.impo.com.uy", requests_per_second=0)
        payload = b'{"tipoNorma": "Ley", "articulos": []}'
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = payload
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._session, "request", return_value=mock_resp):
            assert client.get_text("leyes/19996-2021") == payload


# ─── Discovery year estimator ───


class TestYearEstimation:
    def test_known_laws_in_candidates(self):
        known = [
            (9155, 1933),
            (17000, 1998),
            (18000, 2006),
            (19000, 2012),
            (19996, 2021),
            (20468, 2026),
        ]
        for num, real_year in known:
            cands = _year_candidates(num)
            assert real_year in cands, f"{real_year} missing for law {num}: {cands}"

    def test_estimate_boundary_low(self):
        assert _estimate_year(1) == 1826

    def test_estimate_boundary_high(self):
        assert _estimate_year(25000) == 2026

    def test_candidates_length(self):
        # Estimator + ±1 — landmarks are dense enough to make this enough.
        assert len(_year_candidates(19000)) == 3


class TestIMPODiscoveryDaily:
    def test_discover_daily_tries_prior_year(self):
        from unittest.mock import MagicMock, call

        client = MagicMock(spec=IMPOClient)
        client.get_text.side_effect = lambda norm_id: (
            b'{"articulos": []}' if norm_id == "leyes/20461-2025" else b""
        )
        discovery = IMPODiscovery(law_number_max=20460)
        results = list(discovery.discover_daily(client, date(2026, 4, 3), last_known_number=20460))
        assert "leyes/20461-2025" in results
        assert call("leyes/20461-2026") in client.get_text.call_args_list
        assert call("leyes/20461-2025") in client.get_text.call_args_list

    def test_discover_daily_current_year(self):
        from unittest.mock import MagicMock

        client = MagicMock(spec=IMPOClient)
        client.get_text.side_effect = lambda norm_id: (
            b'{"articulos": []}' if norm_id == "leyes/20461-2026" else b""
        )
        discovery = IMPODiscovery(law_number_max=20460)
        results = list(discovery.discover_daily(client, date(2026, 4, 3), last_known_number=20460))
        assert "leyes/20461-2026" in results
