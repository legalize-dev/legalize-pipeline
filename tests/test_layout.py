"""Directory layout — Legalize Format Spec v0.4.

The layout rule is implemented twice: here, and in whatever consumer resolves a
law's file (the website's ``github.py``). If the two ever disagree, every law's
metadata still resolves and every body 404s — 171,735 pages that look fine and
are empty. The spec's test vectors are the fixed point that stops that, so they
are asserted verbatim below and must stay byte-identical to SPEC.md.
"""

from __future__ import annotations

from datetime import date

import pytest
import yaml

from legalize.layout import (
    FLAT,
    LAYOUT,
    PLACEHOLDERS,
    SHARDED,
    SPEC_VERSION,
    law_path,
    layout_for,
    manifest,
)
from legalize.models import NormMetadata, NormStatus, Rank
from legalize.transformer.slug import norm_to_filepath

# SPEC.md, §Directory layout. Do not edit without editing the spec.
SPEC_VECTORS = [
    ("BOE-A-1978-31229", "bb"),
    ("SFS-1962-700", "8a"),
    ("LEGITEXT000006069414", "0c"),
]


@pytest.mark.parametrize("identifier,bucket", SPEC_VECTORS)
def test_spec_test_vectors(identifier, bucket):
    assert law_path("xx", identifier, SHARDED) == f"xx/{bucket}/{identifier}.md"


def test_vocabulary_is_closed():
    assert PLACEHOLDERS == {"directory", "identifier", "id_sha1_2"}


def test_unknown_placeholder_fails_loudly():
    """A guess here yields a path that is wrong rather than absent."""
    with pytest.raises(KeyError):
        law_path("xx", "X", "{directory}/{year}/{identifier}.md")


def test_absent_country_is_flat():
    assert layout_for("no-such-country") == FLAT
    assert law_path("fr", "LEGITEXT000006069414", FLAT) == "fr/LEGITEXT000006069414.md"


def test_every_declared_layout_is_resolvable():
    """LAYOUT is empty until a country is rebuilt under v0.4. This is the guard
    for when it is not: a typo there must fail here, not four hours into a
    bootstrap."""
    for code, template in LAYOUT.items():
        assert law_path(code, "X", template).endswith("/X.md")


def _meta(identifier: str, country: str, jurisdiction: str | None = None) -> NormMetadata:
    return NormMetadata(
        title="t",
        short_title="t",
        identifier=identifier,
        country=country,
        rank=Rank.LEY,
        publication_date=date(2020, 1, 1),
        status=NormStatus.IN_FORCE,
        department="",
        source="https://example.org",
        jurisdiction=jurisdiction,
    )


def test_directory_is_the_jurisdiction_then_the_country():
    assert norm_to_filepath(_meta("BOE-A-1978-31229", "es")) == "es/BOE-A-1978-31229.md"
    assert norm_to_filepath(_meta("BOE-A-2020-615", "es", "es-pv")) == "es-pv/BOE-A-2020-615.md"


def test_a_sharded_country_shards_all_of_its_directories(monkeypatch):
    """One repo, one shape — that is what the manifest's single ``*`` entry says.
    A jurisdiction directory is sharded like the country one, never left flat."""
    monkeypatch.setitem(LAYOUT, "xx", SHARDED)
    assert norm_to_filepath(_meta("BOE-A-1978-31229", "xx")) == "xx/bb/BOE-A-1978-31229.md"
    assert (
        norm_to_filepath(_meta("BOE-A-1978-31229", "xx", "xx-1")) == "xx-1/bb/BOE-A-1978-31229.md"
    )


def test_declaring_a_layout_is_all_it_takes(monkeypatch):
    """The whole per-country switch: one entry, and paths and manifest follow."""
    meta = _meta("BOE-A-1978-31229", "xx")
    assert norm_to_filepath(meta) == "xx/BOE-A-1978-31229.md"
    monkeypatch.setitem(LAYOUT, "xx", SHARDED)
    assert norm_to_filepath(meta) == "xx/bb/BOE-A-1978-31229.md"
    assert yaml.safe_load(manifest("xx"))["layout"][0]["path"] == SHARDED


@pytest.mark.parametrize("template", [FLAT, SHARDED])
def test_manifest_describes_the_paths_the_engine_actually_writes(monkeypatch, template):
    """The manifest is a promise to consumers: fill in what it declares and you
    get the file. Checked against what the engine really writes, both shapes."""
    monkeypatch.setitem(LAYOUT, "xx", template)
    for country in ["xx"]:
        m = yaml.safe_load(manifest(country))
        assert m["spec_version"] == SPEC_VERSION
        assert m["country"] == country
        assert len(m["layout"]) == 1
        entry = m["layout"][0]
        assert entry["directories"] == ["*"]

        meta = _meta("BOE-A-1978-31229", country)
        rebuilt = entry["path"].format(
            directory=country,
            identifier=meta.identifier,
            id_sha1_2=__import__("hashlib").sha1(meta.identifier.encode()).hexdigest()[:2],
        )
        assert rebuilt == norm_to_filepath(meta)


def test_manifest_ships_with_every_country_repo():
    from legalize.committer.repo_meta import repo_meta_files

    for country in ["es", "fr", "pt"]:
        assert ".legalize.yml" in repo_meta_files(country)


# ── Frontmatter: summary reaches the file, and nothing can break the document ──


def _fm(**kw):
    from legalize.transformer.frontmatter import render_frontmatter

    meta = _meta("X-1", "xx")
    return render_frontmatter(__import__("dataclasses").replace(meta, **kw), date(2020, 1, 1))


def test_summary_is_emitted():
    """Measured before this: 0 of 164,278 Portuguese files carried it, while the
    source states one for 93 % of the corpus."""
    assert 'summary: "Aprova o regime"' in _fm(summary="Aprova o regime")


def test_summary_absent_when_the_source_gives_none():
    assert "summary:" not in _fm(summary="")


def test_a_country_field_cannot_shadow_a_core_field():
    """Two lines with one key is invalid YAML strictly and last-one-wins loosely,
    so the file would either fail to load or load a value nobody chose."""
    out = _fm(summary="from the field", extra=(("summary", "from extra"),))
    assert out.count("summary:") == 1
    assert yaml.safe_load(out.strip().strip("-"))["summary"] == "from the field"


@pytest.mark.parametrize(
    "raw",
    ['a "quoted" title', "back\\slash", "line\nbreak", "carriage\r\nreturn", "tab\there"],
)
def test_frontmatter_survives_whatever_the_source_puts_in_a_string(raw):
    """A raw newline ends a double-quoted scalar and turns the rest of the
    frontmatter into garbage. Sources put them in titles and summaries."""
    parsed = yaml.safe_load(_fm(title=raw, summary=raw).strip().strip("-"))
    assert parsed["title"] == raw.replace("\r\n", "\n").replace("\r", "\n")
    assert parsed["summary"] == parsed["title"]
