"""Pre-2005 EUR-Lex HTML4 (``<TXT_TE>``) parsing.

EUR-Lex switched to semantic ``oj-*`` markup around 2004/2005. Everything older
is HTML4 whose body is a ``<TXT_TE>`` element nested inside a class-less ``<p>``.
The parser used to hit that ``<p>``, treat it as a leaf and emit the whole act as
a single paragraph — 1,926 published files of ``legalize-eu`` are in that state.
See ``research/RESEARCH-EU.md`` §3.3.

The fixture ``31958R0001_old.html`` (Regulation No 1, the EEC languages
regulation) was in the repo for months with no test referencing it, which is how
the defect survived. These tests are that missing check.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from legalize.fetcher.eu.parser import EURLexTextParser

FIXTURES = Path(__file__).parent / "fixtures" / "eu"


@pytest.fixture(scope="module")
def paragraphs():
    parser = EURLexTextParser()
    data = (FIXTURES / "31958R0001_old.html").read_bytes()
    blocks = parser.parse_text(data)
    return [p for b in blocks for v in b.versions for p in v.paragraphs]


def test_legacy_document_is_not_one_blob(paragraphs):
    """The regression guard: a flattened act yields 1-2 paragraphs."""
    assert len(paragraphs) > 20, (
        f"legacy act collapsed into {len(paragraphs)} paragraphs — "
        "the <TXT_TE> container is not being walked"
    )


def test_articles_become_headings(paragraphs):
    """Regulation No 1 has 8 articles, and each must be a heading, not body text."""
    headings = [p.text for p in paragraphs if p.css_class == "h4"]
    assert headings == [f"Article {n}" for n in range(1, 9)]


def test_article_text_follows_its_heading(paragraphs):
    """Article 1 is the one that lists the official languages."""
    idx = next(i for i, p in enumerate(paragraphs) if p.text == "Article 1")
    body = paragraphs[idx + 1]
    assert body.css_class == "abs"
    assert "official languages" in body.text


def test_preamble_survives(paragraphs):
    assert any("HAS ADOPTED THIS REGULATION" in p.text for p in paragraphs)


def test_no_typographic_separator_leaks(paragraphs):
    """Old CELEX text uses ``++++`` as a separator; it is not legal content."""
    assert not any(p.text.strip("+ ") == "" for p in paragraphs)


# ─── Second legacy fixture: an act with real article structure ──────────────


@pytest.fixture(scope="module")
def reg1017():
    """Regulation 1017/68 — competition rules for transport, 31 articles."""
    parser = EURLexTextParser()
    data = (FIXTURES / "31968R1017_old.html").read_bytes()
    blocks = parser.parse_text(data)
    return [p for b in blocks for v in b.versions for p in v.paragraphs]


def test_long_legacy_act_keeps_every_article(reg1017):
    headings = [p.text for p in reg1017 if p.css_class == "h4"]
    assert headings == [f"Article {n}" for n in range(1, 32)]


def test_long_legacy_act_has_body_between_articles(reg1017):
    """Structure without text would pass the heading test and be useless."""
    body = [p for p in reg1017 if p.css_class == "abs"]
    assert len(body) > 150


# ─── The ``++++`` separator ─────────────────────────────────────────────────


def test_plus_separator_is_dropped():
    """The EEC Treaty's first paragraph is ``++++`` — a separator, not content."""
    parser = EURLexTextParser()
    data = (FIXTURES / "11957E000_old.html").read_bytes()
    paras = [p for b in parser.parse_text(data) for v in b.versions for p in v.paragraphs]
    assert paras, "treaty produced no paragraphs at all"
    assert not any(p.text.strip("+ ") == "" for p in paras)
    assert any("CLOSER UNION" in p.text.upper() for p in paras)
