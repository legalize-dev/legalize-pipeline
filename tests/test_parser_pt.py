"""Portugal parser tests.

Every case here is a defect the old tretas.org-based pipeline actually shipped —
the counts in the docstrings come from the audit of `legalize-pt` at 109,929 files
(RESEARCH-PT-v2 §1).
"""

from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path

import pytest

from legalize.countries import get_metadata_parser, get_text_parser
from legalize.fetcher.pt.client import _pack, unpack
from legalize.fetcher.pt.discovery import _year_of
from legalize.fetcher.pt.identifier import build_identifier, jurisdiction_from_eli, parse_eli
from legalize.fetcher.pt import parser as parser_module
from legalize.fetcher.pt.parser import (
    FRAGMENT_TYPES,
    DREMetadataParser,
    DRETextParser,
    _fragment_paragraphs,
    _parse_published_html,
)
from legalize.models import NormStatus, TextState
from legalize.transformer.markdown import render_norm_at_date

FIXTURES = Path(__file__).parent / "fixtures" / "pt"


def _load_fixture(name: str) -> dict:
    plain = FIXTURES / name
    if plain.exists():
        return json.loads(plain.read_text(encoding="utf-8"))
    with gzip.open(FIXTURES / f"{name}.gz", "rt", encoding="utf-8") as handle:
        return json.load(handle)


class TestIdentifier:
    """The old scheme wrote the year with two digits for 55,742 files and four for
    32,650, funnelled every numberless diploma into two ``*-UNKNOWN`` files, and
    silently deleted characters out of 13 official numbers."""

    @pytest.mark.parametrize(
        ("eli", "numero", "expected"),
        [
            (
                "https://data.dre.pt/eli/dec-lei/47344/1966/p/cons/20260623/pt/html",
                "47344",
                "DRE-DEC-LEI-47344-1966",
            ),
            (
                "https://data.dre.pt/eli/lei/29/2026/06/23/p/dre/pt/html",
                "29/2026",
                "DRE-LEI-29-2026",
            ),
            (
                "https://data.dre.pt/eli/lei/82-d/2014/p/cons/20231229/pt/html",
                "82-D/2014",
                "DRE-LEI-82-D-2014",
            ),
            # the ELI drops the third component; Numero keeps it and so must the id
            (
                "https://data.dre.pt/eli/port/216/2024/09/23/p/dre/pt/html",
                "216/2024/1",
                "DRE-PORT-216-2024-1",
            ),
            (
                "https://data.dre.pt/eli/declegreg/2/2025/07/02/m/dre/pt/html",
                "2/2025/M",
                "DRE-DECLEGREG-2-2025-M",
            ),
            # DRE writes "4/85"; the ELI says 1985 and the ELI wins
            (
                "https://data.dre.pt/eli/lei/4/1985/p/cons/20190621/pt/html",
                "4/85",
                "DRE-LEI-4-1985",
            ),
        ],
    )
    def test_from_eli(self, eli, numero, expected):
        assert build_identifier(eli, numero) == expected

    def test_two_digit_year_normalised_without_eli(self):
        """No ELI exists before ~1990, and that is most of the corpus."""
        assert build_identifier("", "905/80", "portaria", 1980, "port") == "DRE-PORT-905-1980"

    def test_numberless_diploma_is_unique(self):
        """Two ``*-UNKNOWN`` files each held exactly one document; every other
        numberless "Decreto de <data>" was silently overwritten."""
        first = build_identifier("", "", "decreto", 1993, "dec", "159184")
        second = build_identifier("", "", "decreto", 1993, "dec", "159185")
        assert first != second
        assert "UNKNOWN" not in first

    def test_no_silent_character_deletion(self):
        """``43199(1ªparte)`` used to become ``431991parte``."""
        built = build_identifier("", "43199(1ªparte)", "decreto", 1960, "dec")
        assert built == "DRE-DEC-43199-1APARTE-1960"

    def test_rcm_and_rar_do_not_collide(self):
        """Both used to map to ``DRE-R-``, which is why 98 % of Resoluções are
        missing from the old repo."""
        rcm = build_identifier(
            "https://data.dre.pt/eli/resolconsmin/50/2020/p/dre/pt/html", "50/2020"
        )
        rar = build_identifier(
            "https://data.dre.pt/eli/resolassrep/50/2020/p/dre/pt/html", "50/2020"
        )
        assert rcm != rar

    def test_filesystem_safe(self):
        built = build_identifier("", "1/94-1ªsecção", "lei", 1994, "lei")
        assert not set(built) & set(':/\\*?"<>| ')

    def test_one_prefix_per_type_whatever_the_row_says(self):
        """DRE files 13,211 despachos normativos under three different acronyms —
        "DN" on its legacy catalogue rows, "despnorm" on the modern ones and empty
        on 559 — which split one type across three identifier prefixes."""
        modern = build_identifier(
            "https://data.dre.pt/eli/despnorm/7/1980/p/dre/pt/html",
            "7/80",
            "despacho-normativo",
            1980,
            "despnorm",
        )
        legacy = build_identifier("", "7/80", "despacho-normativo", 1980, "DN", "30993000")
        blank = build_identifier("", "7/80", "despacho-normativo", 1980, "", "30993001")
        assert modern == legacy == blank == "DRE-DESPNORM-7-1980"

    def test_unknown_type_still_falls_back(self):
        """A type DRE has not published an ELI for must still get an identifier."""
        assert build_identifier("", "3/2020", "tipo-novo", 2020, "tn") == "DRE-TN-3-2020"


class TestScopeYear:
    """`earliest_year` is 1960 because 96.9 % of what DRE holds before it is a PDF
    scan with no text layer. The filter has to actually see the year."""

    def test_numberless_key_still_yields_its_year(self):
        """Portugal published thousands of numberless acts ("Decreto de 12 de Maio de
        1911"), whose key is {year}-{dre id} with no number in front. The pattern
        only knew {number}-{year}-{dre id}, so 6,056 of them sailed past the cutoff —
        5,596 from the 1910s alone."""
        assert _year_of("1912-249008") == 1912

    @pytest.mark.parametrize(
        "key, expected",
        [
            ("7-1980-30993000", 1980),
            ("31095-1940-1", 1940),
            ("82-D-2014-12345", 2014),
            ("29-2026-1135578391", 2026),
        ],
    )
    def test_numbered_keys_are_unaffected(self, key, expected):
        assert _year_of(key) == expected


class TestJurisdiction:
    def test_from_eli_segment(self):
        assert (
            jurisdiction_from_eli("https://data.dre.pt/eli/declegreg/2/2025/07/02/m/dre/pt/html")
            == "pt-30"
        )
        assert (
            jurisdiction_from_eli("https://data.dre.pt/eli/lei/29/2026/06/23/p/dre/pt/html") is None
        )
        assert (
            parse_eli("https://data.dre.pt/eli/declegreg/2/2025/07/02/a/dre/pt/html")[
                "jurisdiction_code"
            ]
            == "a"
        )

    def test_falls_back_to_number_and_issuer(self):
        assert jurisdiction_from_eli("", "1/2013/A") == "pt-20"
        assert (
            jurisdiction_from_eli(
                "", "10/2020", "Região Autónoma da Madeira - Assembleia Legislativa"
            )
            == "pt-30"
        )


class TestFragmentTypes:
    def test_covers_dre_static_entity(self):
        """DRE's TipoFragmento entity has 19 values, 0-18."""
        assert set(FRAGMENT_TYPES) == set(range(19))

    def test_subcapitulo_is_ten(self):
        """A frequency sweep guessed id 10 was "Tabela" from three fragments; the
        app manifest says subcapítulo."""
        assert FRAGMENT_TYPES[10][0] == "Subcapítulo"

    def test_article_and_base_are_article_level(self):
        assert FRAGMENT_TYPES[11][1] == FRAGMENT_TYPES[2][1] == "articulo"


class TestPublishedHtml:
    def test_table_becomes_one_pipe_table_paragraph(self):
        """The old parser built a pipe table then split it into one paragraph per
        row, so the renderer put a blank line between rows and no table in the
        corpus ever rendered. Only 907 of 109,929 files had one."""
        html = (
            "<p class='paragraph-normal-text'>Antes</p>"
            "<table><thead><tr><th>Escalão</th><th>Taxa</th></tr></thead>"
            "<tbody><tr><td>até 7703</td><td>13,25%</td></tr>"
            "<tr><td>7703 a 11623</td><td>18,00%</td></tr></tbody></table>"
        )
        paragraphs = _parse_published_html(html)
        tables = [p for p in paragraphs if p.css_class == "table"]
        assert len(tables) == 1
        assert tables[0].text.count("\n") >= 3
        assert "\n\n" not in tables[0].text  # storage.py splits paragraphs on \n\n

    def test_image_wrapper_is_not_a_table(self):
        """109 of 129 surface-B tables are one-cell wrappers around an <img>."""
        html = (
            "<table class='imageWrapper'><tr><td>"
            "<img src='/images/1/2.png' alt='A imagem não se encontra disponível.'/>"
            "</td></tr></table>"
        )
        paragraphs = _parse_published_html(html)
        assert [p.css_class for p in paragraphs] == ["image"]
        assert paragraphs[0].text.startswith("![](https://diariodarepublica.pt/images/")

    def test_heading_absorbs_its_title(self):
        html = (
            "<p class='paragraph-center'>CAPÍTULO I</p>"
            "<p class='paragraph-bold-center-14px'>DISPOSIÇÃO GERAL</p>"
            "<p class='paragraph-center'>Artigo 1.º</p>"
            "<p class='paragraph-bold-center-14px'>Objeto</p>"
            "<p class='paragraph-normal-text'>1 - Corpo.</p>"
        )
        paragraphs = _parse_published_html(html)
        assert [(p.css_class, p.text) for p in paragraphs] == [
            ("capitulo_tit", "CAPÍTULO I — DISPOSIÇÃO GERAL"),
            ("articulo", "Artigo 1.º — Objeto"),
            ("parrafo", "1 - Corpo."),
        ]

    def test_abbreviated_article_is_recognised(self):
        """``Art. N.º`` went unrecognised in 20,332 files (18.5 % of the corpus)."""
        paragraphs = _parse_published_html("<p class='paragraph-center'>Art. 2.º</p>")
        assert paragraphs[0].css_class == "articulo"

    def test_artigo_unico_is_recognised(self):
        """6,026 files."""
        paragraphs = _parse_published_html("<p class='paragraph-center'>Artigo único</p>")
        assert paragraphs[0].css_class == "articulo"

    def test_title_paragraph_is_dropped(self):
        """98.1 % of old files repeated the H1 as body text."""
        html = "<p class='paragraph-title-bold-center-18px'>Lei n.º 29/2026</p>"
        assert _parse_published_html(html) == []

    def test_internal_id_line_is_dropped(self):
        """A bare DRE content id leaked into 7,573 files."""
        html = "<p class='paragraph-italic-right'>114808797</p><p>Real.</p>"
        assert [p.text for p in _parse_published_html(html)] == ["Real."]

    def test_cross_reference_becomes_a_link(self):
        html = (
            "<p>Altera o <a href='/dr/detalhe/lei/45-a-2024-901667918'>Lei n.º 45-A/2024</a>.</p>"
        )
        text = _parse_published_html(html)[0].text
        assert (
            "[Lei n.º 45-A/2024](https://diariodarepublica.pt/dr/detalhe/lei/45-a-2024-901667918)"
            in text
        )

    def test_style_block_is_stripped(self):
        html = "<style>.Tbl1 { border-collapse:collapse; }</style><p>Texto.</p>"
        assert [p.text for p in _parse_published_html(html)] == ["Texto."]

    def test_ver_documento_original_links_the_pdf(self):
        """The bare marker sits in 27,954 files. Nothing recovers the content, so
        link the scan rather than print a dead string."""
        html = "<p>Tabela anexa (ver documento original)</p>"
        text = _parse_published_html(html, pdf_url="https://files.dre.pt/x.pdf")[0].text
        assert "[ver documento original](https://files.dre.pt/x.pdf)" in text

    def test_control_chars_and_entities_are_cleaned(self):
        html = "<p>Nota.\x97 Durante o ciclo &amp; depois &ordm;</p>"
        text = _parse_published_html(html)[0].text
        assert "\x97" not in text
        assert "&ordm;" not in text and "&amp;" not in text

    def test_relative_href_is_resolved_against_the_site_root(self):
        """DRE links EU acts with a bare "eurlex.asp?..." that only resolves inside
        the site; in a Markdown file it is a dead link."""
        html = "<p>Ver a <a href='eurlex.asp?ano=2009&id=309L0049'>Directiva</a>.</p>"
        text = _parse_published_html(html)[0].text
        assert "(https://diariodarepublica.pt/eurlex.asp?ano=2009&id=309L0049)" in text

    def test_no_paragraph_contains_a_blank_line(self):
        """storage.py joins paragraphs with "\\n\\n" and splits on it, so a blank
        line inside one desyncs the parallel css_classes list."""
        html = "<p>Uma<br/><br/>linha</p><table><tr><td>a</td><td>b</td></tr></table>"
        assert all("\n\n" not in p.text for p in _parse_published_html(html))


class TestTextState:
    """Spec v0.3. DRE consolidates 5,561 diplomas and publishes the other 159,000
    as enacted, so a PT file that says nothing would be claiming to be the law in
    force when it is a 1994 text with two later amendments left out."""

    @staticmethod
    def _bundle(surface: str) -> bytes:
        return json.dumps(
            {
                "tipo": "decreto-lei",
                "key": "16-1994-512030",
                "surface": surface,
                "published": {
                    "Id": "512030",
                    "Numero": "16/94",
                    "TipoDiploma": "Decreto-Lei",
                    "TipoDiplomaAcronimo": "dec-lei",
                    "DataPublicacao": "1994-01-22",
                    "Sumario": "Aprova o Estatuto do Ensino Superior Particular e Cooperativo",
                },
            }
        ).encode("utf-8")

    def test_as_published_declares_as_enacted_and_names_the_last_amendment(self):
        parser_module.set_amendments(
            {"DRE-DEC-LEI-16-1994": ["DRE-LEI-37-1994", "DRE-DEC-LEI-94-1999"]}
        )
        try:
            meta = DREMetadataParser().parse(self._bundle("pub"), "pub:decreto-lei:16-1994-512030")
            assert meta.text_state is None  # the country default already says as_enacted
            assert meta.last_amendment == "DRE-DEC-LEI-94-1999"
            extra = dict(meta.extra)
            assert extra["amended_by"] == "DRE-LEI-37-1994; DRE-DEC-LEI-94-1999"
            assert extra["amended_by_count"] == "2"
        finally:
            parser_module.set_amendments({})

    def test_consolidated_overrides_back_to_point_in_time(self):
        """Its amendments are Versions in the file's own history, so naming one in
        the frontmatter would duplicate the timeline and contradict the body."""
        parser_module.set_amendments({"DRE-DEC-LEI-16-1994": ["DRE-LEI-37-1994"]})
        try:
            meta = DREMetadataParser().parse(self._bundle("cons"), "cons:decreto-lei:1994-512030")
            assert meta.text_state is TextState.POINT_IN_TIME
            assert meta.last_amendment is None
            assert "amended_by" not in dict(meta.extra)
        finally:
            parser_module.set_amendments({})

    def test_unknown_amendments_emit_nothing(self):
        """Absence is a claim we can back: no act in the corpus names this law."""
        meta = DREMetadataParser().parse(self._bundle("pub"), "pub:decreto-lei:16-1994-512030")
        assert meta.last_amendment is None
        assert "amended_by" not in dict(meta.extra)


class TestSubjectOverrides:
    """12 % of consolidated diplomas come back with an empty ELIMetadataHTML — the
    Código Civil among them — so eli:is_about names nothing and they would ship with
    no subjects. AnaliseJuridica still has them, keyed by LinkSitemap."""

    @staticmethod
    def _bundle(eli_metadata: str) -> bytes:
        return json.dumps(
            {
                "tipo": "decreto-lei",
                "key": "1966-34509075",
                "surface": "cons",
                "published": {
                    "Id": "477358",
                    "Numero": "47344",
                    "TipoDiploma": "Decreto-Lei",
                    "TipoDiplomaAcronimo": "dec-lei",
                    "DataPublicacao": "1966-11-25",
                    "Sumario": "Código Civil",
                    "LinkSitemap": "/dr/detalhe/decreto-lei/47344-1966-477358",
                    "ELIMetadataHTML": eli_metadata,
                },
            }
        ).encode("utf-8")

    def test_override_fills_a_diploma_with_no_eli_subjects(self):
        parser_module.set_subject_overrides(
            {"/dr/detalhe/decreto-lei/47344-1966-477358": ["Código Civil", "Divórcio"]}
        )
        try:
            meta = DREMetadataParser().parse(self._bundle(""), "cons:decreto-lei:1966-34509075")
            assert meta.subjects == ("Código Civil", "Divórcio")
        finally:
            parser_module.set_subject_overrides({})

    def test_override_never_shadows_a_declared_subject(self):
        """It answers "declares nothing", not "the thesaurus had no label" — or a
        hole in the thesaurus would quietly be papered over from the other source."""
        rdfa = '<span property="eli:is_about" resource="http://x/999"></span>'
        parser_module.set_thesaurus({})
        parser_module.set_subject_overrides(
            {"/dr/detalhe/decreto-lei/47344-1966-477358": ["Wrong"]}
        )
        try:
            meta = DREMetadataParser().parse(self._bundle(rdfa), "cons:decreto-lei:1966-34509075")
            assert meta.subjects == ()
            assert dict(meta.extra)["subject_ids"] == "999"
        finally:
            parser_module.set_subject_overrides({})


class TestFragment:
    """Both defects were found in the corpus itself: 34 diplomas carried tag soup in
    a heading and 16 blocks of Decreto-Lei 110/2001 shipped "&lt;" as four
    characters."""

    def test_heading_markup_is_flattened(self):
        """``Epigrafe`` holds an anchor for every EU act a heading cites, and it was
        going into the Markdown as literal tag soup."""
        entry = {
            "version": {
                "TipoFragmentoId": 11,
                "Tituo": "Artigo 13.º",
                "Epigrafe": (
                    'Transposição da Directiva n.º <a href="eurlex.asp?ano=2009&'
                    'id=309L0049" title="Link">2009/49/CE</a>, de 18 de Junho'
                ),
                "Texto": "",
            }
        }
        heading, paragraphs = _fragment_paragraphs(entry, "")
        assert "<a" not in heading and "href" not in heading
        assert "[2009/49/CE](https://diariodarepublica.pt/eurlex.asp?" in heading
        assert paragraphs[0].text == heading

    def test_escaped_angle_brackets_in_plain_body(self):
        """No tag in the body, so it takes the plain-text branch — where DRE still
        escapes its angle brackets."""
        entry = {
            "version": {
                "TipoFragmentoId": 16,
                "Tituo": "",
                "Epigrafe": "",
                "Texto": "Para os lotes &lt;15 t aplica-se o n.º 5.",
            }
        }
        _, paragraphs = _fragment_paragraphs(entry, "")
        assert paragraphs[0].text == "Para os lotes <15 t aplica-se o n.º 5."

    def test_entity_body_is_not_mistaken_for_markup(self):
        """Unescaping before the branch would hand "&lt;15 t …" to the HTML parser,
        which would swallow it as a tag."""
        entry = {
            "version": {
                "TipoFragmentoId": 16,
                "Tituo": "",
                "Epigrafe": "",
                "Texto": "a) C1.2 &lt; 15 % - 1 ponto;",
            }
        }
        _, paragraphs = _fragment_paragraphs(entry, "")
        assert paragraphs[0].text == "a) C1.2 < 15 % - 1 ponto;"


class TestSuvestine:
    """One commit per reform is the product; the old repo had zero."""

    @staticmethod
    def _fragment(frag_id: str, type_id: int, tituo: str, texto: str) -> dict:
        return {
            "frag": {"Id": f"row-{frag_id}", "Name": tituo},
            "version": {
                "FragmentoId": frag_id,
                "Tituo": tituo,
                "Texto": texto,
                "TipoFragmentoId": type_id,
                "Epigrafe": "",
            },
            "nota": [],
            "alteracoes": [],
        }

    def _blob(self, versions: list[dict]) -> bytes:
        return json.dumps(
            {
                "norm_id": "cons:lei:2000-1",
                "surface": "cons",
                "diploma_frag_id": "1",
                "versions": versions,
            }
        ).encode()

    def test_one_reform_per_effective_date(self):
        blob = self._blob(
            [
                {
                    "date": "2000-01-01",
                    "is_original": True,
                    "amending": None,
                    "fragments_b64": _pack([self._fragment("a", 11, "Artigo 1.º", "original")]),
                },
                {
                    "date": "2010-05-05",
                    "is_original": False,
                    "amending": {"legis_id": "999", "numero": "5/2010"},
                    "fragments_b64": _pack([self._fragment("a", 11, "Artigo 1.º", "reformado")]),
                },
            ]
        )
        blocks, reforms = DRETextParser().parse_suvestine(blob, "cons:lei:2000-1")
        assert len(blocks) == 1, "the same article across snapshots is one Block"
        assert len(blocks[0].versions) == 2
        assert [r.date for r in reforms] == [date(2000, 1, 1), date(2010, 5, 5)]
        assert reforms[1].norm_id == "DRE-999@2010-05-05"
        assert reforms[1].affected_blocks == ("Artigo 1.º",)

    def test_unchanged_snapshot_produces_no_reform(self):
        """commit_all_fast streams every Reform to git without checking whether the
        file changed, so the parser is the only thing preventing empty commits."""
        same = _pack([self._fragment("a", 11, "Artigo 1.º", "igual")])
        blob = self._blob(
            [
                {
                    "date": "2000-01-01",
                    "is_original": True,
                    "amending": None,
                    "fragments_b64": same,
                },
                {
                    "date": "2010-05-05",
                    "is_original": False,
                    "amending": {"legis_id": "999"},
                    "fragments_b64": same,
                },
            ]
        )
        _blocks, reforms = DRETextParser().parse_suvestine(blob, "cons:lei:2000-1")
        assert len(reforms) == 1

    def test_reform_source_id_is_stable(self):
        blob = self._blob(
            [
                {
                    "date": "2000-01-01",
                    "is_original": True,
                    "amending": None,
                    "fragments_b64": _pack([self._fragment("a", 11, "Artigo 1.º", "x")]),
                }
            ]
        )
        first = DRETextParser().parse_suvestine(blob, "cons:lei:2000-1")[1][0].norm_id
        second = DRETextParser().parse_suvestine(blob, "cons:lei:2000-1")[1][0].norm_id
        assert first == second

    def test_published_blob_is_a_single_version(self):
        blob = json.dumps(
            {
                "norm_id": "pub:lei:1",
                "surface": "pub",
                "versions": [
                    {
                        "date": "2020-03-01",
                        "is_original": True,
                        "amending": None,
                        "html_b64": _pack("<p class='paragraph-normal-text'>Texto.</p>"),
                    }
                ],
            }
        ).encode()
        blocks, reforms = DRETextParser().parse_suvestine(blob, "pub:lei:1")
        assert len(reforms) == 1
        assert reforms[0].date == date(2020, 3, 1)
        assert blocks[0].versions[0].publication_date == date(2020, 3, 1)

    def test_roundtrip_pack(self):
        assert unpack(_pack({"a": [1, "ç"]})) == {"a": [1, "ç"]}


class TestMetadata:
    def _bundle(self, **overrides) -> bytes:
        bundle = {
            "surface": "pub",
            "tipo": "lei",
            "key": "29-2026-1135578391",
            "published": {
                "Numero": "29/2026",
                "TipoDiploma": "Lei",
                "TipoDiplomaAcronimo": "lei",
                "DataPublicacao": "2026-06-23",
                "Sumario": "Cria o regime jurídico do contrato de aproveitamento energético renovável.",
                "Emissor": "Assembleia da República",
                "EmissorAcronimo": "AR",
                "Vigencia": "VIGENTE",
                "Serie": "I",
                "Pagina": "2 - 8",
                "Publicacao": "Diário da República n.º 119/2026, 1º Suplemento, Série I de 2026-06-23",
                "URL_PDF": "https://files.diariodarepublica.pt/1s/2026/06/11900/0000200008.pdf",
                "ELI": "https://data.dre.pt/eli/lei/29/2026/06/23/p/dre/pt/html",
                "Id": "1135578391",
                "ELIMetadataHTML": (
                    '<span property="eli:is_about" resource="http://data.dre.pt/eli/authority/legal-subject/30211723"></span>'
                    '<span property="eli:cites" resource="http://data.europa.eu/eli/dir/2019/944/oj"></span>'
                    '<span property="eli:in_force" resource="http://data.europa.eu/eli/ontology#InForce-inForce"></span>'
                ),
            },
        }
        bundle["published"].update(overrides)
        return json.dumps(bundle).encode()

    def test_core_fields(self):
        meta = DREMetadataParser().parse(self._bundle(), "pub:lei:29-2026-1135578391")
        assert meta.identifier == "DRE-LEI-29-2026"
        assert meta.country == "pt"
        assert meta.publication_date == date(2026, 6, 23)
        assert meta.status is NormStatus.IN_FORCE
        assert meta.source.startswith("https://data.dre.pt/eli/")
        assert meta.pdf_url

    def test_title_carries_the_descriptive_text(self):
        """A Portuguese diploma is cited by number; the search vector only indexes
        title and short_title, so the bare number made the whole corpus findable
        only by number."""
        meta = DREMetadataParser().parse(self._bundle(), "pub:lei:29-2026-1135578391")
        assert meta.title.startswith("Lei n.º 29/2026 — ")
        assert "regime jurídico" in meta.title
        assert meta.short_title and meta.short_title != meta.title
        assert len(meta.short_title) <= 81

    def test_status_vocabulary(self):
        for raw, expected in (
            ("NAO_VIGENTE", NormStatus.REPEALED),
            ("VIGENCIA_CONDICIONADA", NormStatus.PARTIALLY_REPEALED),
            ("CADUCADO", NormStatus.EXPIRED),
        ):
            meta = DREMetadataParser().parse(self._bundle(Vigencia=raw), "pub:lei:1")
            assert meta.status is expected, raw

    def test_eli_rdfa_is_captured(self):
        meta = DREMetadataParser().parse(self._bundle(), "pub:lei:1")
        extra = dict(meta.extra)
        assert "30211723" in extra["subject_ids"]
        assert "data.europa.eu" in extra["cites_eu"]
        assert extra["eli_in_force"] == "InForce-inForce"

    def test_supplement_recovered_from_publicacao(self):
        """DRE leaves Suplemento empty even for diplomas that are in one."""
        meta = DREMetadataParser().parse(self._bundle(), "pub:lei:1")
        assert dict(meta.extra)["supplement"] == "1º Suplemento"

    def test_no_placeholder_dates_or_ids(self):
        meta = DREMetadataParser().parse(self._bundle(), "pub:lei:1")
        rendered = render_norm_at_date(meta, [], meta.publication_date)
        assert "1900-01-01" not in rendered
        assert "PLACEHOLDER" not in rendered
        assert "UNKNOWN" not in rendered


class TestAgainstRealFixtures:
    def test_published_madeira_budget(self):
        """DLR 2/2025/M: 101 tables, 96 images, 472 links, jurisdiction pt-30."""
        detail = _load_fixture("aspublished-dlr-2-2025-madeira.json")["data"]["DetalheConteudo"]
        paragraphs = _parse_published_html(detail["TextoFormatado"], detail.get("URL_PDF", ""))
        classes = [p.css_class for p in paragraphs]
        assert classes.count("table") >= 1
        assert "image" in classes
        assert any("](https://diariodarepublica.pt/dr/detalhe/" in p.text for p in paragraphs)
        assert all("\n\n" not in p.text for p in paragraphs)
        assert jurisdiction_from_eli(detail["ELI"]) == "pt-30"

    def test_no_html_or_entities_survive(self):
        detail = _load_fixture("aspublished-lei-55-a-2025.json")["data"]["DetalheConteudo"]
        body = "\n".join(p.text for p in _parse_published_html(detail["TextoFormatado"]))
        assert "<p" not in body and "<div" not in body and "<td" not in body
        assert "&nbsp;" not in body and "&amp;" not in body
        assert "�" not in body


class TestCountryDispatch:
    def test_registry(self):
        assert isinstance(get_text_parser("pt"), DRETextParser)
        assert isinstance(get_metadata_parser("pt"), DREMetadataParser)
