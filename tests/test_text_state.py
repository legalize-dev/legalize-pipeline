"""Text state — Legalize Format Spec v0.3.

A file must say what its body actually is. Three cases exist and only two of
them need saying, because a file with no ``text_state`` is the law as in force
on its ``last_updated``.
"""

from datetime import date

import pytest

from legalize.countries import REGISTRY, TEXT_STATE, text_state_for
from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    TextState,
    Version,
)
from legalize.transformer.markdown import render_norm_at_date

PUB = date(1981, 5, 7)


def _norm(country: str, **kwargs) -> NormMetadata:
    return NormMetadata(
        title="Consumer Protection Law",
        short_title="Consumer Protection Law",
        identifier="2000123",
        country=country,
        rank="chok",
        publication_date=PUB,
        status=NormStatus.IN_FORCE,
        department="Ministry of Economy",
        source="https://example.test/2000123",
        **kwargs,
    )


def _blocks() -> list[Block]:
    return [
        Block(
            id="art-1",
            block_type="articulo",
            title="1",
            versions=(
                Version(
                    norm_id="2000123",
                    publication_date=PUB,
                    effective_date=PUB,
                    paragraphs=(Paragraph(css_class="articulo", text="Article 1"),),
                ),
            ),
        )
    ]


def _body(md: str) -> str:
    """Everything after the closing frontmatter delimiter."""
    return md.split("\n---\n", 1)[1]


class TestDefault:
    def test_absent_country_is_point_in_time(self):
        assert text_state_for("es") is TextState.POINT_IN_TIME
        assert text_state_for("no-such-country") is TextState.POINT_IN_TIME

    def test_point_in_time_emits_nothing(self):
        md = render_norm_at_date(_norm("es"), _blocks(), date(2024, 2, 17))
        assert "text_state" not in md
        assert "last_amendment" not in md
        assert ">" not in md.split("# ", 1)[1].split("\n")[1]

    def test_point_in_time_ignores_last_amendment(self):
        md = render_norm_at_date(
            _norm("es", last_amendment="BOE-A-2024-3099"), _blocks(), date(2024, 2, 17)
        )
        assert "last_amendment" not in md


class TestAsEnacted:
    def test_frontmatter_and_notice(self):
        md = render_norm_at_date(_norm("ad"), _blocks(), PUB)
        assert 'text_state: "as_enacted"' in md
        assert "This is the law as enacted." in md

    def test_notice_sits_directly_under_the_title(self):
        md = render_norm_at_date(_norm("ad"), _blocks(), PUB)
        after_title = md.split("# Consumer Protection Law\n\n", 1)[1]
        assert after_title.startswith("> **This is the law as enacted.")

    def test_last_amendment_is_emitted(self):
        md = render_norm_at_date(
            _norm("ad", last_amendment="2243011"), _blocks(), date(2026, 3, 12)
        )
        assert 'last_amendment: "2243011"' in md

    def test_body_is_identical_across_amendments(self):
        """The whole point: an as_enacted body is written once and never rewritten.

        Only the frontmatter moves when an amendment lands, so a reform commit is
        a two-line diff and a backfilled amendment does not invalidate the text.
        """
        first = render_norm_at_date(
            _norm("ad", last_amendment="2243011"), _blocks(), date(2026, 3, 12)
        )
        later = render_norm_at_date(
            _norm("ad", last_amendment="2244136"), _blocks(), date(2026, 7, 28)
        )
        assert first != later
        assert _body(first) == _body(later)


class TestCurrent:
    def test_frontmatter_and_notice(self):
        md = render_norm_at_date(_norm("se"), _blocks(), date(2026, 1, 1))
        assert 'text_state: "current"' in md
        assert "It is not the text as it stood on the date of any given commit." in md

    def test_last_amendment_is_emitted(self):
        """Sweden is why: its body is constant and its reform dates are all
        1 January of the SFS year, so without this field two amendments from the
        same year render identically and the pipeline drops the second commit."""
        first = render_norm_at_date(
            _norm("se", last_amendment="SFS 2024:397"), _blocks(), date(2024, 1, 1)
        )
        second = render_norm_at_date(
            _norm("se", last_amendment="SFS 2024:1013"), _blocks(), date(2024, 1, 1)
        )
        assert 'last_amendment: "SFS 2024:397"' in first
        assert first != second


class TestPerNormOverride:
    def test_norm_overrides_its_country(self):
        """A consolidated country still has norms the source never consolidated."""
        md = render_norm_at_date(_norm("ar", text_state=TextState.AS_ENACTED), _blocks(), PUB)
        assert 'text_state: "as_enacted"' in md

    def test_norm_can_opt_back_into_the_default(self):
        md = render_norm_at_date(_norm("se", text_state=TextState.POINT_IN_TIME), _blocks(), PUB)
        assert "text_state" not in md


class TestConformance:
    """Every country declares the same thing in the same place."""

    @pytest.mark.parametrize("code", sorted(TEXT_STATE))
    def test_declared_country_is_registered(self, code):
        assert code in REGISTRY, f"{code} declares a text_state but is not in REGISTRY"

    @pytest.mark.parametrize("code", sorted(TEXT_STATE))
    def test_declared_state_has_a_notice(self, code):
        from legalize.transformer.markdown import _NOTICES

        assert TEXT_STATE[code] in _NOTICES

    def test_default_is_never_declared(self):
        """point_in_time is the absence of a declaration, never a value."""
        assert TextState.POINT_IN_TIME not in TEXT_STATE.values()

    @pytest.mark.parametrize("code", sorted(REGISTRY))
    def test_every_country_resolves(self, code):
        assert isinstance(text_state_for(code), TextState)


class TestOverrideSurvivesTheRoundTrip:
    """commit_all_fast renders from the JSON, not from the parser's output, so a
    per-norm override that is not persisted is silently replaced by the country
    default — the opposite claim on every consolidated norm inside an as_enacted
    country."""

    def _norm(self, tmp_path, **kw):
        from datetime import date

        from legalize.models import (
            Block,
            NormMetadata,
            NormStatus,
            Paragraph,
            ParsedNorm,
            Rank,
            Version,
        )

        meta = NormMetadata(
            title="T",
            short_title="T",
            identifier="X-1",
            country="pt",
            rank=Rank("lei"),
            publication_date=date(2020, 1, 1),
            status=NormStatus.IN_FORCE,
            department="Ministério",
            source="https://example.test",
            **kw,
        )
        block = Block(
            id="a1",
            block_type="artigo",
            title="Artigo 1.º",
            versions=(
                Version(
                    norm_id="X-1",
                    publication_date=date(2020, 1, 1),
                    effective_date=date(2020, 1, 1),
                    paragraphs=(Paragraph(css_class="parrafo", text="Texto."),),
                ),
            ),
        )
        return ParsedNorm(metadata=meta, blocks=(block,), reforms=())

    def test_point_in_time_override_round_trips(self, tmp_path):
        from legalize.models import TextState
        from legalize.storage import load_norma_from_json, save_structured_json

        path = save_structured_json(
            tmp_path, self._norm(tmp_path, text_state=TextState.POINT_IN_TIME)
        )
        assert load_norma_from_json(path).metadata.text_state is TextState.POINT_IN_TIME

    def test_last_amendment_round_trips(self, tmp_path):
        from legalize.storage import load_norma_from_json, save_structured_json

        path = save_structured_json(tmp_path, self._norm(tmp_path, last_amendment="DRE-LEI-9-2021"))
        assert load_norma_from_json(path).metadata.last_amendment == "DRE-LEI-9-2021"

    def test_absent_state_stays_absent(self, tmp_path):
        from legalize.storage import load_norma_from_json, save_structured_json

        path = save_structured_json(tmp_path, self._norm(tmp_path))
        assert load_norma_from_json(path).metadata.text_state is None


class TestLastAmendmentIsGuardedByState:
    def _meta(self, **kw):
        from datetime import date

        from legalize.models import NormMetadata, NormStatus, Rank

        return NormMetadata(
            title="T",
            short_title="T",
            identifier="X-1",
            country="pt",
            rank=Rank("lei"),
            publication_date=date(2020, 1, 1),
            status=NormStatus.IN_FORCE,
            department="Ministério",
            source="https://example.test",
            **kw,
        )

    def _reform(self):
        from datetime import date

        from legalize.models import Reform

        return Reform(date=date(2021, 1, 1), norm_id="DRE-133879986@2021-01-01", affected_blocks=())

    def test_point_in_time_norm_is_left_alone(self):
        """Its amendments are the versions; naming one states the timeline twice."""
        from legalize.models import TextState
        from legalize.pipeline import _with_last_amendment

        meta = self._meta(text_state=TextState.POINT_IN_TIME)
        assert _with_last_amendment(meta, self._reform()).last_amendment is None

    def test_as_enacted_norm_gets_the_reform_id(self):
        """Declared on the norm, not read from the registry: which countries are
        as_enacted is a separate decision from whether this helper works."""
        from legalize.models import TextState
        from legalize.pipeline import _with_last_amendment

        meta = self._meta(text_state=TextState.AS_ENACTED)
        assert _with_last_amendment(meta, self._reform()).last_amendment == (
            "DRE-133879986@2021-01-01"
        )

    def test_an_official_id_the_parser_found_is_not_overwritten(self):
        """reform.norm_id is an internal dedupe key on some countries; the field is
        documented as the official ID of the amending act."""
        from legalize.pipeline import _with_last_amendment

        meta = self._meta(last_amendment="DRE-DEC-LEI-94-1999")
        assert _with_last_amendment(meta, self._reform()).last_amendment == "DRE-DEC-LEI-94-1999"
