"""Status, text state and rank rules for EUR-Lex metadata.

The rules these pin all decide what a published file *claims about itself*, so
getting one wrong is not a rendering bug — it is a corpus that lies. See
``research/RESEARCH-EU.md`` §2.1 and §3.1 for the measurements behind them.
"""

from __future__ import annotations

import json

import pytest

from legalize.fetcher.eu.parser import EURLexMetadataParser
from legalize.models import NormStatus, Rank, TextState

_RTYPE = "http://publications.europa.eu/resource/authority/resource-type/"


def _meta(**overrides) -> bytes:
    """One SPARQL binding row, shaped as CELLAR returns it."""
    row = {
        "celex": {"value": "32016R0679"},
        "title": {"value": "Regulation (EU) 2016/679 of the Council of 27 April 2016 on data"},
        "date": {"value": "2016-04-27"},
        "force": {"value": "true"},
        "rtype": {"value": f"{_RTYPE}REG"},
    }
    for key, value in overrides.items():
        if value is None:
            row.pop(key, None)
        else:
            row[key] = {"value": value}
    return json.dumps({"results": {"bindings": [row]}}).encode()


@pytest.fixture
def parser() -> EURLexMetadataParser:
    return EURLexMetadataParser()


# ─── Status ────────────────────────────────────────────────────────────────


def test_in_force(parser):
    assert parser.parse(_meta(force="true"), "x").status is NormStatus.IN_FORCE


def test_repealed_needs_a_repealing_act(parser):
    meta = parser.parse(_meta(force="false", repealedBy="32009R0169"), "x")
    assert meta.status is NormStatus.REPEALED
    assert dict(meta.extra)["repealed_by"] == "32009R0169"


def test_no_repealing_act_means_expired_not_repealed(parser):
    """Repealing is an act of the legislature; expiring is a deadline.

    ~41,000 acts in scope ran out rather than being repealed. Calling those
    repealed invents legislation that never happened.
    """
    meta = parser.parse(_meta(force="false"), "x")
    assert meta.status is NormStatus.EXPIRED
    assert "repealed_by" not in dict(meta.extra)


def test_absent_status_raises_instead_of_guessing(parser):
    """The Austrian defect (#123) at five times the scale, refused."""
    with pytest.raises(ValueError, match="no in-force status"):
        parser.parse(_meta(force=None), "31993R0729")


# ─── Dates ─────────────────────────────────────────────────────────────────


def test_missing_date_raises_rather_than_stamping_today(parser):
    """Spec v0.4 §Dates names today() as a forbidden placeholder."""
    with pytest.raises(ValueError, match="no publication date"):
        parser.parse(_meta(date=None), "31968R1017")


# ─── Text state ────────────────────────────────────────────────────────────


def test_unconsolidated_act_falls_to_the_country_default(parser):
    """None here means countries.py TEXT_STATE decides — as_enacted for eu."""
    meta = parser.parse(_meta(hasCons="false"), "x")
    assert meta.text_state is None


def test_consolidated_act_is_point_in_time(parser):
    meta = parser.parse(_meta(hasCons="true"), "x")
    assert meta.text_state is TextState.POINT_IN_TIME


def test_amended_but_unconsolidated_act_names_its_last_amendment(parser):
    """Required by spec v0.4 on an as-enacted file that has been amended."""
    meta = parser.parse(_meta(hasCons="false", lastAmendment="32009R0169"), "x")
    assert meta.last_amendment == "32009R0169"


def test_consolidated_act_carries_no_last_amendment(parser):
    """Its history is the commits, not a frontmatter field."""
    meta = parser.parse(_meta(hasCons="true", lastAmendment="32009R0169"), "x")
    assert meta.last_amendment is None


def test_untouched_act_carries_no_last_amendment(parser):
    """70 % of a real as-enacted corpus is in this case; it is the norm."""
    assert parser.parse(_meta(hasCons="false"), "x").last_amendment is None


# ─── Rank ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("rtype", "expected"),
    [
        ("REG", "regulation"),
        ("DIR", "directive"),
        ("DEC", "decision"),
        ("TREATY", "treaty"),
        ("AGREE_INTERNATION", "international_agreement"),
    ],
)
def test_rank_follows_the_resource_type(parser, rtype, expected):
    meta = parser.parse(_meta(rtype=f"{_RTYPE}{rtype}"), "x")
    assert meta.rank == Rank(expected)


def test_unknown_resource_type_raises(parser):
    """It used to fall back to "regulation", which would have mislabelled
    4,326 directives and 23,390 decisions the moment the scope widened."""
    with pytest.raises(ValueError, match="unmapped resource type"):
        parser.parse(_meta(rtype=f"{_RTYPE}SOMETHING_NEW"), "x")


# ─── Short title ───────────────────────────────────────────────────────────


def test_short_title_keeps_the_act_identity(parser):
    """It used to keep what came *after* " on " — the subject, not the act."""
    assert parser.parse(_meta(), "x").short_title == "Regulation (EU) 2016/679"


def test_subjects_come_from_eurovoc(parser):
    meta = parser.parse(_meta(subjects="data protection|personal data"), "x")
    assert meta.subjects == ("data protection", "personal data")


# ─── Path-hostile identifiers ──────────────────────────────────────────────


def test_slash_in_celex_becomes_a_dash(parser):
    """1,394 acts in scope carry a separator: "11997D/TXT" is Amsterdam.

    Spec v0.4 §Directory layout requires rejecting a path value containing "/",
    and rejecting would drop the founding treaties.
    """
    meta = parser.parse(_meta(celex="11997D/TXT"), "11997D/TXT")
    assert meta.identifier == "11997D-TXT"


def test_sanitised_identifier_keeps_the_source_celex(parser):
    meta = parser.parse(_meta(celex="11951K/CDT/P01"), "11951K/CDT/P01")
    assert meta.identifier == "11951K-CDT-P01"
    assert dict(meta.extra)["celex"] == "11951K/CDT/P01"


def test_untouched_identifier_does_not_repeat_the_celex(parser):
    meta = parser.parse(_meta(celex="32016R0679"), "32016R0679")
    assert meta.identifier == "32016R0679"
    assert "celex" not in dict(meta.extra)
