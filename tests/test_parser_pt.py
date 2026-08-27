"""Portugal parser tests.

Every case here is a defect the old tretas.org-based pipeline actually shipped —
the counts in the docstrings come from the audit of `legalize-pt` at 109,929 files
(research/RESEARCH-PT-v2.md §1).
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
from legalize.fetcher.pt.identifier import (
    build_identifier,
    jurisdiction_from_eli,
    parse_eli,
    serie_of,
)
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


def _pack_published(when: str, html: str) -> bytes:
    """A minimal as-published suvestine blob, packed the way the client writes it."""
    return json.dumps(
        {
            "surface": "pub",
            "pdf_url": "",
            "versions": [{"date": when, "html_b64": _pack(html), "is_original": True}],
        }
    ).encode("utf-8")


class TestIdentifier:
    """DRE names every document it publishes, in that document's own page URL.
    The old scheme rebuilt a name instead of reading it, and every part of the
    rebuild went wrong on the real corpus: the série leaked out of ``Numero``
    into 11,161 identifiers in two spellings, the two-digit-year normalisation
    was defeated in three more, and 6,862 pairs of unrelated acts needed a
    discriminant to stop them colliding."""

    @pytest.mark.parametrize(
        "link,expected",
        [
            # The number keeps its own hyphens; the year and the id never have any.
            ("/dr/detalhe/resolucao/3-2001-1331261", "DRE-2001-3-1331261"),
            ("/dr/detalhe/portaria/790-b-1992-447283", "DRE-1992-790-B-447283"),
            ("/dr/detalhe/portaria/1033-bv-2004-284102", "DRE-2004-1033-BV-284102"),
            ("/dr/detalhe/decreto-lei/47344-1966-168776", "DRE-1966-47344-168776"),
            ("/dr/detalhe/lei/82-d-2014-30348109", "DRE-2014-82-D-30348109"),
            # Portugal published thousands of numberless "Decreto de <data>" acts.
            # The old scheme funnelled every one into a single *-UNKNOWN file.
            ("/dr/detalhe/decreto/1976-408205", "DRE-1976-408205"),
            # Absolute URLs and trailing slashes are the same document.
            (
                "https://diariodarepublica.pt/dr/detalhe/lei/29-2026-901234567/",
                "DRE-2026-29-901234567",
            ),
        ],
    )
    def test_the_name_is_read_from_dre_not_rebuilt(self, link, expected):
        assert build_identifier(link, "", "") == expected

    def test_the_year_is_always_the_second_component(self):
        """What lets the repo shard by year with a one-line rule. Searching for a
        component that looks like a year does not work: 2,931 diplomas are
        numbered like one."""
        for link in ("/dr/detalhe/lei/1999-2001-123456", "/dr/detalhe/decreto/1976-408205"):
            assert build_identifier(link, "", "").split("-")[1] in {"2001", "1976"}

    def test_a_number_that_looks_like_a_year_is_not_mistaken_for_one(self):
        assert (
            build_identifier("/dr/detalhe/lei/1999-2001-123456", "", "") == "DRE-2001-1999-123456"
        )

    def test_the_serie_is_not_in_the_name_and_cannot_leak_into_it(self):
        """``Numero`` spells the série inside itself — "1/2000 (2.ª série)" — and
        that leaked into 11,161 identifiers as ``2-A-SERIE`` and ``2-ASERIE``."""
        assert (
            build_identifier("/dr/detalhe/portaria/1-2000-1652040", "", "") == "DRE-2000-1-1652040"
        )

    def test_two_acts_sharing_a_number_and_a_year_get_different_names(self):
        """Resolução 3/2001-PG is two acts: DRE ids 1331261 and 2789653,
        published a week apart. The DRE id is what separates them, so no
        discriminant has to be invented."""
        a = build_identifier("/dr/detalhe/resolucao/3-2001-1331261", "", "")
        b = build_identifier("/dr/detalhe/resolucao/3-2001-2789653", "", "")
        assert a != b

    def test_the_type_is_not_in_the_name(self):
        """Number and year alone are ambiguous across types in 32 % of cases, so
        this is a name for a machine to resolve. The type is in the file as
        ``rank``, which is where a reader should find it."""
        assert "PORTARIA" not in build_identifier("/dr/detalhe/portaria/44-2025-911089434", "", "")

    def test_a_document_with_no_page_url_is_still_published(self):
        """One in 4,000 measured. Its DRE id still names it uniquely."""
        assert build_identifier("", "408205", 1976) == "DRE-1976-408205"
        assert build_identifier("/dr/nonsense", "408205", "1976") == "DRE-1976-408205"

    def test_a_document_that_cannot_be_named_raises_rather_than_inventing(self):
        with pytest.raises(ValueError):
            build_identifier("", "", 1976)
        with pytest.raises(ValueError):
            build_identifier("", "408205", "")

    def test_the_name_is_a_single_path_segment(self):
        """It is also the file name, so anything else writes outside the tree."""
        for link in ("/dr/detalhe/portaria/790-b-1992-447283", "/dr/detalhe/decreto/1976-408205"):
            name = build_identifier(link, "", "")
            assert "/" not in name and "\\" not in name and name == name.strip()


class TestSerie:
    """``series`` is a published field, and the série is what tells a Série I act
    from a Série II one that shares its number — 6,862 such pairs exist."""

    def test_declared_serie_wins(self):
        assert serie_of({"Serie": "II"}) == "II"

    def test_the_1976_1999_split_is_still_serie_i(self):
        """Série I was I-A and I-B for those years, and they are the same série."""
        assert serie_of({"Serie": "I-A"}) == "I"

    def test_falls_back_to_the_publication_string(self):
        """DRE fills ``Serie`` on some records and not others; ``Publicacao``
        always spells it out."""
        assert (
            serie_of({"Publicacao": "Diário da República n.º 242/2008, Série II de 2008-12-16"})
            == "II"
        )

    def test_first_source_that_knows_wins_and_silence_is_empty(self):
        assert serie_of({}, {"Serie": "I"}) == "I"
        assert serie_of({}, {}) == ""


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

    def test_as_published_takes_the_country_default(self):
        meta = DREMetadataParser().parse(self._bundle("pub"), "pub:decreto-lei:16-1994-512030")
        assert meta.text_state is None  # the country default already says as_enacted
        assert meta.last_amendment is None  # set per reform by the pipeline, not here
        assert "amended_by" not in dict(meta.extra)

    def test_each_amendment_becomes_a_reform(self):
        """The body of an as-enacted file never changes, so without a reform per
        amendment its own notice — "a commit in this file's history" — is false."""
        blob = _pack_published("1994-01-22", "<p>Texto original.</p>")
        parser_module.set_amendments(
            {
                "pub:decreto-lei:16-1994-512030": [
                    ["1994-11-11", "DRE-LEI-37-1994", "Alterados os arts. 5.º, 9.º e 14.º"],
                    ["1999-03-23", "DRE-DEC-LEI-94-1999", ""],
                ]
            }
        )
        try:
            _, reforms = DRETextParser().parse_suvestine(blob, "pub:decreto-lei:16-1994-512030")
            assert [r.norm_id for r in reforms] == [
                "pub:decreto-lei:16-1994-512030",
                "DRE-LEI-37-1994",
                "DRE-DEC-LEI-94-1999",
            ]
            assert [r.date.isoformat() for r in reforms] == [
                "1994-01-22",
                "1994-11-11",
                "1999-03-23",
            ]
        finally:
            parser_module.set_amendments({})

    def test_an_amendment_before_publication_is_ignored(self):
        """A mis-resolved reference must not date a commit before the law existed."""
        blob = _pack_published("1994-01-22", "<p>Texto.</p>")
        parser_module.set_amendments(
            {"pub:decreto-lei:16-1994-512030": [["1990-01-01", "DRE-LEI-1-1990"]]}
        )
        try:
            _, reforms = DRETextParser().parse_suvestine(blob, "pub:decreto-lei:16-1994-512030")
            assert len(reforms) == 1
        finally:
            parser_module.set_amendments({})

    def test_consolidated_overrides_back_to_point_in_time(self):
        """Its amendments are Versions in the file's own history, so declaring
        as_enacted over them would contradict the body."""
        meta = DREMetadataParser().parse(self._bundle("cons"), "cons:decreto-lei:1994-512030")
        assert meta.text_state is TextState.POINT_IN_TIME
        assert meta.last_amendment is None

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
                "LinkSitemap": "/dr/detalhe/lei/29-2026-1135578391",
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
        assert meta.identifier == "DRE-2026-29-1135578391"
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


class TestChangeNote:
    """What DRE says a reform changed travels verbatim into the commit body, on its
    own line — half of those notes are not about articles at all."""

    def test_the_note_reaches_the_commit_body(self):
        from legalize.committer.message import build_commit_info
        from legalize.models import CommitType, Reform

        metadata = DREMetadataParser().parse(
            json.dumps(
                {
                    "tipo": "decreto-lei",
                    "key": "16-1994-512030",
                    "surface": "pub",
                    "published": {
                        "Id": "512030",
                        "Numero": "16/94",
                        "TipoDiploma": "Decreto-Lei",
                        "TipoDiplomaAcronimo": "dec-lei",
                        "DataPublicacao": "1994-01-22",
                        "Sumario": "Aprova o Estatuto",
                    },
                }
            ).encode("utf-8"),
            "pub:decreto-lei:16-1994-512030",
        )
        reform = Reform(
            date=date(1994, 11, 11),
            norm_id="DRE-LEI-37-1994",
            affected_blocks=(),
            change_note="Alterados os arts. 5.º, 9.º e 14.º",
        )
        info = build_commit_info(CommitType.REFORM, metadata, reform, (), "pt/x.md", "body")
        assert "Change: Alterados os arts. 5.º, 9.º e 14.º" in info.body
        # The structural line stays what it always was: nothing was diffed here.
        assert "Affected articles: N/A" in info.body

    def test_no_note_means_no_line(self):
        """No country's output changes until its fetcher fills the field."""
        from legalize.committer.message import _build_body
        from legalize.models import CommitType, NormMetadata, NormStatus, Rank, Reform

        metadata = NormMetadata(
            title="T",
            short_title="T",
            identifier="X-1",
            country="pt",
            rank=Rank("lei"),
            publication_date=date(2020, 1, 1),
            status=NormStatus.IN_FORCE,
            department="",
            source="https://example.test",
        )
        reform = Reform(date=date(2021, 1, 1), norm_id="A", affected_blocks=())
        assert "Change:" not in _build_body(CommitType.REFORM, metadata, reform, "N/A")


class TestPublicationDate:
    """israel found `last_updated: "1900-01-01"` in the live repo, and ar and gr
    have the same. The sentinel parses as a valid date, so an `or` chain never falls
    through it and the diploma publishes claiming to predate the Diário da República
    — sorting to the very front of the repository's history."""

    def test_the_sentinel_falls_through_to_the_real_date(self):
        from legalize.fetcher.pt.client import published_date_of

        assert (
            published_date_of({"DataPublicacao": "1900-01-01", "DataDistribuicao": "2025-08-29"})
            == "2025-08-29"
        )

    def test_a_real_publication_date_always_wins(self):
        from legalize.fetcher.pt.client import published_date_of

        assert (
            published_date_of({"DataPublicacao": "1994-01-22", "DataDistribuicao": "2025-08-29"})
            == "1994-01-22"
        )

    def test_nothing_usable_stays_empty(self):
        """Empty, not the sentinel: the caller decides, and 84 of the 87 diplomas in
        this state are already excluded for having no text either."""
        from legalize.fetcher.pt.client import published_date_of

        assert published_date_of({"DataPublicacao": "1900-01-01"}) == ""


class TestUndatedVersion:
    """DRE writes 1900-01-01 where it has no date, and the parser used to keep it.

    Measured on the published corpus: three Declarações de Rectificação carried
    ``last_updated: "1900-01-01"`` while their own ``publication_date`` was right,
    because the version blob's date is the sentinel and the metadata pass had
    already walked past it into DataDistribuicao. The reform took the sentinel,
    and the reform's date is what becomes ``last_updated``.
    """

    def test_falls_back_to_the_publication_date(self):
        from datetime import date

        from legalize.fetcher.pt.parser import DRETextParser

        blob = _pack_published("1900-01-01", "<p>Texto.</p>")
        _, reforms = DRETextParser().parse_suvestine(
            blob, "pub:x:1-2023-1", published_on=date(2023, 9, 29)
        )
        assert [r.date for r in reforms] == [date(2023, 9, 29)]

    def test_a_real_version_date_still_wins(self):
        from datetime import date

        from legalize.fetcher.pt.parser import DRETextParser

        blob = _pack_published("2023-01-15", "<p>Texto.</p>")
        _, reforms = DRETextParser().parse_suvestine(
            blob, "pub:x:1-2023-1", published_on=date(2023, 9, 29)
        )
        assert [r.date for r in reforms] == [date(2023, 1, 15)]

    def test_no_date_anywhere_refuses_rather_than_inventing(self):
        from legalize.fetcher.pt.parser import DRETextParser

        blob = _pack_published("1900-01-01", "<p>Texto.</p>")
        with pytest.raises(ValueError, match="not something to guess"):
            DRETextParser().parse_suvestine(blob, "pub:x:1-2023-1")
