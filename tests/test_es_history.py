"""A BOE publication can introduce several independently effective versions."""

import subprocess
from dataclasses import replace
from datetime import date

import pytest

from legalize.config import Config, CountryConfig
from legalize.fetcher.es.parser import extract_reforms
from legalize.models import Block, Paragraph, Version, ParsedNorm, Reform, TextState
from legalize.pipeline import commit_all_fast, commit_one
from legalize.storage import load_norma_from_json, save_structured_json
from legalize.transformer.markdown import render_norm_at_date
from tests.test_es_source_fidelity import parsed


def test_diary_promotion_is_idempotent_and_backfill_cannot_replace_head(tmp_path):
    from legalize.committer.git_ops import GitRepo
    from legalize.fetcher.es.daily import _commit_norm

    metadata = replace(
        parsed("sample-constitution").metadata,
        publication_date=date(2020, 1, 1),
        text_state=TextState.AS_ENACTED,
    )
    original = Version(
        metadata.identifier,
        date(2020, 1, 1),
        date(2020, 1, 1),
        (Paragraph("parrafo", "Original body"),),
    )
    changed = Version(
        "BOE-A-2021-1",
        date(2021, 1, 1),
        date(2021, 1, 1),
        (Paragraph("parrafo", "Consolidated body"),),
    )
    diary = ParsedNorm(
        metadata,
        (Block("x", "precepto", "Article", (original,)),),
        (
            Reform(original.publication_date, original.norm_id, ()),
            Reform(changed.publication_date, changed.norm_id, ()),
        ),
    )
    repo = GitRepo(tmp_path / "repo", "Legalize", "legalize@legalize.dev")
    repo.init()
    assert _commit_norm(repo, diary, date(2022, 1, 1)) == 2
    blocks = (replace(diary.blocks[0], versions=(original, changed)),)
    consolidated = ParsedNorm(
        replace(metadata, text_state=TextState.POINT_IN_TIME),
        blocks,
        tuple(extract_reforms(blocks)),
    )
    assert _commit_norm(repo, consolidated, date(2022, 1, 1)) == 1
    assert _commit_norm(repo, consolidated, date(2022, 1, 1)) == 0
    head = repo._run(["rev-parse", "HEAD"])
    gap = Reform(date(2020, 6, 1), "BOE-A-2020-10", (), effective_date=date(2020, 6, 1))
    with pytest.raises(ValueError, match="historical gap"):
        _commit_norm(repo, replace(consolidated, reforms=(gap,)), date(2020, 12, 1))
    assert repo._run(["rev-parse", "HEAD"]) == head


def test_projected_wording_does_not_become_operative_before_being_superseded(tmp_path):
    norm = parsed("sample-code")
    cached = load_norma_from_json(save_structured_json(tmp_path, norm))
    block = next(block for block in cached.blocks if block.id == "art56")
    projected = next(v for v in block.versions if v.norm_id == "BOE-A-2015-7391")
    assert projected.effective_date is None
    assert projected.superseded_before_commencement
    reform = next(
        r
        for r in extract_reforms(cached.blocks)
        if r.norm_id == projected.norm_id and r.effective_date is None
    )
    assert reform.change_note
    content = render_norm_at_date(
        cached.metadata, (block,), reform.date, source_id=reform.norm_id, effective_date=reform.date
    )
    assert "deficiencias o anomalías psíquicas" in content
    assert "deficiencias mentales, intelectuales o sensoriales" not in content
    assert 'last_updated: "1981-08-09"' in content
    assert 'text_state: "current"' not in content


def test_unresolved_effective_date_is_omitted_instead_of_invented(tmp_path):
    norm = parsed("sample-constitution")
    blocks = (
        Block(
            "x",
            "precepto",
            "Article",
            (Version("X", date(2020, 1, 1), None, (Paragraph("parrafo", "Source wording"),)),),
        ),
    )
    content = render_norm_at_date(
        norm.metadata, blocks, date(2020, 1, 1), source_id="X", effective_date=date(2020, 1, 1)
    )
    assert "last_updated:" not in content
    assert 'effective_date_unknown_blocks: "x"' in content
    assert "Source wording" in content


@pytest.mark.parametrize("committer", [commit_one, commit_all_fast])
def test_staged_commencement_survives_storage_and_idempotent_commits(tmp_path, committer):
    norm = parsed("sample-constitution")
    identifier = norm.metadata.identifier
    versions = (
        Version(identifier, date(2020, 1, 1), date(2020, 1, 2), (Paragraph("parrafo", "First"),)),
        Version(
            "BOE-A-2021-1", date(2021, 1, 1), date(2021, 2, 1), (Paragraph("parrafo", "Second"),)
        ),
        Version(
            "BOE-A-2021-1", date(2021, 1, 1), date(2021, 3, 1), (Paragraph("parrafo", "Third"),)
        ),
    )
    blocks = (Block("a1", "precepto", "Article 1", versions),)
    norm = replace(norm, blocks=blocks, reforms=tuple(extract_reforms(blocks)))
    data, repo = tmp_path / "data", tmp_path / "repo"
    cached = load_norma_from_json(save_structured_json(data, norm))
    assert cached.reforms == norm.reforms
    config = Config(countries={"es": CountryConfig(data_dir=str(data), repo_path=str(repo))})

    def run():
        return (
            committer(config, "es", identifier)
            if committer is commit_one
            else committer(config, "es")
        )

    assert run() == 3
    run()
    law = next((repo / "es").rglob("*.md"))
    shas = subprocess.check_output(
        ["git", "-C", str(repo), "log", "--reverse", "--format=%H", "--", str(law)], text=True
    ).splitlines()
    assert len(shas) == 3
    for sha, expected, effective in zip(
        shas, ("First", "Second", "Third"), ("2020-01-02", "2021-02-01", "2021-03-01"), strict=True
    ):
        content = subprocess.check_output(
            ["git", "-C", str(repo), "show", f"{sha}:{law.relative_to(repo)}"], text=True
        )
        message = subprocess.check_output(
            ["git", "-C", str(repo), "show", "-s", "--format=%B", sha], text=True
        )
        assert f'last_updated: "{effective}"' in content
        assert f"\n{expected}\n" in content
        assert f"Effective-Date: {effective}" in message
        assert f"Source-Date: {'2020-01-01' if expected == 'First' else '2021-01-01'}" in message
