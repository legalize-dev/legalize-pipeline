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
    DERIVED,
    FLAT,
    LAYOUT,
    SHARDED,
    SPEC_VERSION,
    TemplateError,
    law_path,
    layout_for,
    manifest,
    path_from_frontmatter,
    placeholders_of,
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
    assert law_path(_meta(identifier, "xx"), SHARDED) == f"xx/{bucket}/{identifier}.md"


def test_the_spec_derives_these_for_every_country():
    assert set(DERIVED) == {"directory", "identifier", "id_sha1_2"}


def test_anything_else_is_a_frontmatter_field():
    """The point of the open vocabulary: a country picks a shape nobody
    anticipated, and the value is written in the file the path names."""
    meta = _meta("X-1", "xx", extra=(("series", "II"),))
    assert law_path(meta, "{directory}/{series}/{identifier}.md") == "xx/II/X-1.md"
    assert law_path(meta, "{directory}/{rank}/{identifier}.md") == "xx/ley/X-1.md"


def test_a_date_field_is_written_the_way_the_frontmatter_writes_it():
    assert (
        law_path(_meta("X-1", "xx"), "{directory}/{publication_date}/{identifier}.md")
        == "xx/2020-01-01/X-1.md"
    )


def test_a_field_no_law_carries_fails_loudly():
    """A guess here yields a path that is wrong rather than absent, and a 404 for
    a law that exists is the hardest failure here to notice."""
    with pytest.raises(TemplateError, match="nonesuch"):
        law_path(_meta("X-1", "xx"), "{directory}/{nonesuch}/{identifier}.md")


def test_an_empty_field_fails_rather_than_collapsing_a_segment():
    with pytest.raises(TemplateError, match="empty"):
        law_path(_meta("X-1", "xx", extra=(("series", "  "),)), "{series}/{identifier}.md")


@pytest.mark.parametrize("bad", ["a/b", "..", ".", "a\\b"])
def test_a_field_cannot_escape_the_directory_it_names(bad):
    """The parser is the only thing between a source's free text and a path."""
    with pytest.raises(TemplateError, match="not a path segment"):
        law_path(_meta("X-1", "xx", extra=(("series", bad),)), "{series}/{identifier}.md")


def test_depth_is_the_country_s_business():
    """v0.4 capped it at one level. Every level makes the tree git rewrites
    smaller, so the cap was prudence and not cost."""
    meta = _meta("BOE-A-1978-31229", "xx", extra=(("series", "II"),))
    template = "{directory}/{rank}/{series}/{id_sha1_2}/{identifier}.md"
    assert law_path(meta, template) == "xx/ley/II/bb/BOE-A-1978-31229.md"


def test_a_consumer_rebuilds_the_path_from_the_file_itself():
    """The spec's own side of the rule: given a law's frontmatter and the template
    its repo declares, fill it in. The engine and the consumer resolving this
    differently is what makes every law's metadata work and every body 404, so
    both sides run the same code."""
    meta = _meta("DRE-2026-16-901234567", "pt", extra=(("year", "2026"),))
    frontmatter = {"identifier": meta.identifier, "country": "pt", "year": "2026"}
    assert path_from_frontmatter(frontmatter, layout_for("pt")) == norm_to_filepath(meta)


def test_a_consumer_reads_the_jurisdiction_the_same_way_the_engine_writes_it():
    frontmatter = {"identifier": "X-1", "country": "pt", "jurisdiction": "pt-20", "year": "1976"}
    assert path_from_frontmatter(frontmatter, layout_for("pt")) == "pt-20/1976/X-1.md"


def test_a_consumer_refuses_a_file_it_cannot_place():
    with pytest.raises(TemplateError, match="year"):
        path_from_frontmatter({"identifier": "X-1", "country": "pt"}, layout_for("pt"))


def test_placeholders_are_read_off_the_template():
    assert placeholders_of(FLAT) == ["directory", "identifier"]
    assert placeholders_of(SHARDED) == ["directory", "id_sha1_2", "identifier"]


def test_absent_country_is_flat():
    assert layout_for("no-such-country") == FLAT
    meta = _meta("LEGITEXT000006069414", "fr")
    assert law_path(meta, FLAT) == "fr/LEGITEXT000006069414.md"


def test_every_declared_layout_is_resolvable():
    """A typo in LAYOUT must fail at import, not four hours into a bootstrap."""
    for code, template in LAYOUT.items():
        assert "{identifier}" in template
        assert placeholders_of(template)


# Real identifiers, one per directory of the repo, under the scheme Portugal is
# rebuilt with: DRE's own name for the document, year first. Portugal is the
# country the year layout was chosen for and the only one declared, so this is
# what stops a rebuild from silently emitting a shape the manifest does not
# promise.
PT_LAWS = [
    ("pt", "DRE-2026-16-901234567", "2026"),
    ("pt-20", "DRE-1976-408958", "1976"),
    ("pt-30", "DRE-1983-31-297783", "1983"),
]


@pytest.mark.parametrize("directory,identifier,year", PT_LAWS)
def test_portugal_shards_by_year(directory, identifier, year):
    jurisdiction = None if directory == "pt" else directory
    meta = _meta(identifier, "pt", jurisdiction, extra=(("year", year),))
    assert norm_to_filepath(meta) == f"{directory}/{year}/{identifier}.md"


def test_portugals_manifest_declares_the_year_layout():
    """What a consumer reads to rebuild the path. If it and the paths above ever
    disagree, every law's metadata resolves and every body 404s."""
    assert yaml.safe_load(manifest("pt"))["layout"][0]["path"] == layout_for("pt")


def test_a_portuguese_law_without_the_year_field_is_refused():
    """The path is built from a field, so the field has to be there. Refusing is
    the point: a guessed path 404s a law that exists."""
    with pytest.raises(TemplateError, match="year"):
        norm_to_filepath(_meta("DRE-2026-16-901234567", "pt"))


def _meta(identifier: str, country: str, jurisdiction: str | None = None, **kw) -> NormMetadata:
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
        **kw,
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
