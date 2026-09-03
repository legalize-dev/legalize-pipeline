"""What a rendered norm is made of — counted, not guessed downstream.

`article_count` used to be a regex over the finished Markdown in
`legalize-enrichment`, one of three systems reconstructing a structure the
engine already had. These tests pin the two questions one number could never
answer at once: `BOE-A-2015-10727` (Ley 42/2015) has **one** article and
**twenty-two** provisions, and reported `article_count: 1` on a 182 KB body.
"""

from __future__ import annotations

from datetime import date

import pytest

from legalize import countries
from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    ParagraphRole,
    Rank,
    Version,
)
from legalize.transformer.markdown import _PAIRED_CLASSES, _SIMPLE_CSS_MAP, render_norm_at_date
from legalize.transformer.structure import _CSS_ROLES, count_structure, role_of


def _p(css: str, text: str) -> Paragraph:
    return Paragraph(css_class=css, text=text)


def _render(country: str, *paragraphs: Paragraph) -> str:
    version = Version(
        norm_id="X",
        publication_date=date(2015, 10, 6),
        effective_date=None,
        paragraphs=paragraphs,
    )
    block = Block(id="a1", block_type="precepto", title="t", versions=(version,))
    metadata = NormMetadata(
        title="Ley de prueba",
        short_title="Ley",
        identifier="TEST-1",
        country=country,
        rank=Rank.LEY,
        publication_date=date(2015, 10, 6),
        status=NormStatus.IN_FORCE,
        department="X",
        source="https://example.test",
    )
    return render_norm_at_date(metadata, [block], date(2026, 1, 1))


class TestArticlesAndProvisionsAreDifferentQuestions:
    def test_a_disposicion_is_a_provision_and_not_an_article(self):
        counts = count_structure(
            "es",
            [
                _p("articulo", "Artículo único. Modificación de la Ley 1/2000."),
                _p("articulo", "Disposición final segunda. Entrada en vigor."),
                _p("articulo", "Disposición derogatoria única."),
                _p("parrafo", "La Ley 1/2000 queda modificada como sigue:"),
            ],
        )
        assert counts.articles == 1
        assert counts.provisions == 3

    def test_both_reach_the_frontmatter(self):
        rendered = _render(
            "es",
            _p("articulo", "Artículo 1. Objeto."),
            _p("articulo", "Disposición final única."),
        )
        assert "article_count: 1" in rendered
        assert "provision_count: 2" in rendered

    @pytest.mark.parametrize(
        "heading",
        ["Artículo 12.", "Art. 384 bis.", "Artículo único.", "ARTÍCULO 3.º", "Articulo 7"],
    )
    def test_the_shapes_the_boe_actually_writes(self, heading):
        assert count_structure("es", [_p("articulo", heading)]).articles == 1

    @pytest.mark.parametrize(
        "heading",
        ["Disposición adicional primera.", "Primero.", "1. Objeto.", "0. ÍNDICE"],
    )
    def test_what_is_not_an_article(self, heading):
        counts = count_structure("es", [_p("articulo", heading)])
        assert counts.articles == 0
        assert counts.provisions == 1


class TestACountryTheEngineCannotCountYet:
    def test_emits_no_counts_at_all(self):
        """Not zero. `article_count: 0` cannot be told apart from "we did not
        count", and `web/models.py` already carries a note about the ambiguity.
        Guessing is how Latvia and Romania scored 95 % and 86 % on coverage
        while counting regulation points and articles cited from other laws."""
        assert count_structure("ie", [_p("articulo", "Artículo 1.")]) is None
        rendered = _render("ie", _p("articulo", "Section 1."))
        assert "article_count" not in rendered
        assert "provision_count" not in rendered

    def test_a_country_joins_by_declaring_its_vocabulary(self, monkeypatch):
        import re

        monkeypatch.setitem(countries.ARTICLE_HEADING, "zz", re.compile(r"^Section\b"))
        counts = count_structure("zz", [_p("articulo", "Section 1."), _p("articulo", "Schedule 2")])
        assert (counts.articles, counts.provisions) == (1, 2)


class TestRoles:
    def test_a_parser_that_knows_its_own_vocabulary_wins(self):
        """The migration path out of #128: a fetcher sets the role and never
        consults the shared class table."""
        paragraph = Paragraph(css_class="whatever", text="x", role=ParagraphRole.ARTICLE)
        assert role_of(paragraph) is ParagraphRole.ARTICLE

    def test_anything_unrecognised_is_body_text(self):
        assert role_of(_p("a_class_no_one_has_seen", "x")) is ParagraphRole.BODY

    def test_centred_text_is_not_declared_structure(self):
        """It renders as a heading but the source declared no unit, and
        counting it would hide the defect the roles exist to find: in the
        pre-2005 diary XML everything is `parrafo` and `Artículo 1.` is prose."""
        assert role_of(_p("centro_redonda", "DISPOSICIONES")) is ParagraphRole.BODY
        assert count_structure("es", [_p("centro_redonda", "Artículo 1.")]).headings == 0

    def test_every_class_the_renderer_knows_has_a_role_or_is_body_on_purpose(self):
        """The two tables live in different modules; this is what keeps them
        from drifting apart in silence."""
        known = (
            set(_SIMPLE_CSS_MAP)
            | set(_PAIRED_CLASSES)
            | {tit for tit, _ in _PAIRED_CLASSES.values()}
        )
        deliberately_body = {
            # Centred or indented formatting, not a declared unit.
            "centro_cursiva",
            "centro_negrita",
            "centro_redonda",
            "sangrado",
            "sangrado_2",
            "sangrado_articulo",
            "formula",
            "num",
            "pre",
            # Generic heading levels other fetchers emit. What an `h6` means is
            # that country's business, and guessing is exactly #128.
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        }
        assert known - set(_CSS_ROLES) == deliberately_body
        assert not set(_CSS_ROLES) - known
