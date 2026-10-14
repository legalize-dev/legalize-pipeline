"""Older directory tables split qualifications across adjacent rows."""

from pathlib import Path

import pytest

from legalize.fetcher.ie.effects import parse_effects

FIXTURES = Path(__file__).parent / "fixtures/ie"


@pytest.mark.parametrize(
    ("number", "source_id", "qualification"),
    [
        (9, "IE-1941-act-23", "but see ss. 9 (3), 76, 78"),
        (18, "IE-1938-act-34", "but see s. 4 (5)"),
        (26, "IE-1968-act-12", "And see regs. under"),
    ],
)
def test_unlinked_qualification_stays_with_its_preceding_instrument(
    number, source_id, qualification
):
    source = (FIXTURES / f"sample-effects-continuation-1923-{number}.html").read_bytes()
    effects = parse_effects(source, f"IE-1923-act-{number}")
    qualified = [effect for effect in effects if qualification in effect["provision"]]
    assert qualified
    assert any(effect["source_id"] == source_id for effect in qualified)
    if number in (9, 18):
        assert len(effects) == len(qualified) == 1
        assert qualified[0]["whole_repeal"]
    else:
        assert {effect["source_id"] for effect in qualified} == {"IE-1968-act-12", "IE-1980-act-21"}
        assert not any(effect["whole_repeal"] for effect in qualified)


def test_qualification_without_an_identified_preceding_instrument_is_rejected():
    source = (
        b'<h3 id="effects">Effects</h3><table><tr><td></td><td>but see s. 4 (5)</td></tr></table>'
    )
    with pytest.raises(ValueError, match="unresolved affecting provision"):
        parse_effects(source, "IE-1923-act-18")


@pytest.mark.parametrize(
    ("year", "number", "suffix"), [(1927, 7, "see also s. 3"), (1933, 8, "And see oo. under")]
)
def test_other_qualification_forms_stay_with_the_preceding_instrument(year, number, suffix):
    raw = (FIXTURES / f"sample-effects-continuation-{year}-{number}.html").read_bytes()
    effects = parse_effects(raw, f"IE-{year}-act-{number}")
    assert any(e["provision"].endswith(suffix) for e in effects)


def test_standalone_see_also_introduces_the_following_citation():
    raw = (FIXTURES / "sample-effects-continuation-1930-10.html").read_bytes()
    effects = parse_effects(raw, "IE-1930-act-10")
    effect = next(e for e in effects if e["source_id"] == "IE-1998-act-29")
    assert effect["note"] == "See also"
    assert effect["provision"].startswith("See also; 29/1998,")
    assert not effect["whole_repeal"]


def test_standalone_see_also_cannot_be_lost_at_end_of_table():
    raw = b'<h3 id="effects">Effects</h3><table><tr><td></td><td>See also</td></tr></table>'
    with pytest.raises(ValueError, match="no following source citation"):
        parse_effects(raw, "IE-1930-act-10")
