"""The repo-meta commit, which used to delete the corpus and block every resume.

Two defects met in one commit. ``write_repo_meta`` makes a plain ``git commit``,
whose tree comes from the index — and ``fast-import`` never touches the index,
so on the failure path (three ``finally`` blocks call this) the meta commit was
built from an index that predated the whole import and removed every law from
the tip. And once written, that commit is the tip, with no trailers on it, so
``_resume_index`` read it and refused to continue the history it had just built.
"""

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import pytest

from legalize.committer.git_ops import FastImporter
from legalize.committer.message import build_commit_info
from legalize.config import load_config
from legalize.models import (
    Block,
    CommitType,
    NormMetadata,
    NormStatus,
    Paragraph,
    ParsedNorm,
    Rank,
    Reform,
    Version,
)
from legalize.pipeline import commit_all_fast, write_repo_meta
from legalize.storage import save_structured_json
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath


def _norm(identifier: str, dates: list[date]) -> ParsedNorm:
    first = dates[0]
    return ParsedNorm(
        metadata=NormMetadata(
            title=f"t {identifier}",
            short_title="t",
            identifier=identifier,
            country="pt",
            rank=Rank.LEY,
            publication_date=first,
            status=NormStatus.IN_FORCE,
            department="Test",
            source=f"https://example.com/{identifier}",
            extra=(("year", str(first.year)),),
        ),
        blocks=(
            Block(
                id="a1",
                block_type="precepto",
                title="Artigo 1",
                versions=tuple(
                    Version(
                        norm_id=identifier,
                        publication_date=when,
                        effective_date=when,
                        paragraphs=(Paragraph(css_class="parrafo", text=f"x {when}"),),
                    )
                    for when in dates
                ),
            ),
        ),
        reforms=tuple(
            Reform(date=when, norm_id=identifier, affected_blocks=("a1",)) for when in dates
        ),
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def corpus(tmp_path):
    """Three Portuguese laws, one reform each, in a repo with a main branch."""
    data, repo = tmp_path / "data", tmp_path / "repo"
    norms = [
        _norm("DRE-1990-1-100", [date(1990, 6, 1)]),
        _norm("DRE-1992-2-200", [date(1992, 6, 1)]),
        _norm("DRE-2000-3-300", [date(2000, 6, 1)]),
    ]
    for norm in norms:
        save_structured_json(data, norm)
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)

    config = tmp_path / "config.yaml"
    config.write_text(f'countries:\n  pt:\n    repo_path: "{repo}"\n    data_dir: "{data}"\n')
    return load_config(str(config)), repo, norms


def test_the_meta_commit_keeps_the_laws_fast_import_wrote(corpus):
    """The reproduction: three laws in, and the tip holds only .legalize.yml."""
    config, repo, norms = corpus

    # checkout=False is every chunk but the last of a chunked import — and the
    # state a run that died mid-import leaves behind.
    with FastImporter(repo, "Legalize", "bot@legalize.dev", checkout=False) as fi:
        for norm in norms:
            reform = norm.reforms[0]
            path = norm_to_filepath(norm.metadata)
            markdown = render_norm_at_date(norm.metadata, list(norm.blocks), reform.date)
            fi.commit(
                path,
                markdown,
                build_commit_info(
                    CommitType.BOOTSTRAP,
                    norm.metadata,
                    reform,
                    list(norm.blocks),
                    path,
                    markdown,
                ),
            )

    write_repo_meta(config, "pt")

    tree = _git(repo, "ls-tree", "-r", "--name-only", "HEAD").splitlines()
    assert ".legalize.yml" in tree
    for norm in norms:
        assert norm_to_filepath(norm.metadata) in tree, "the meta commit deleted the corpus"


def test_a_resume_is_not_blocked_by_the_meta_commit_on_the_tip(corpus):
    """After any run the tip is [fix-pipeline], and it carries no trailers."""
    config, repo, _ = corpus
    assert commit_all_fast(config, "pt") == 3
    write_repo_meta(config, "pt")
    assert _git(repo, "log", "-1", "--format=%s").startswith("[fix-pipeline]")

    # Used to raise HistoryMismatch: "start from an empty repo", on a repo whose
    # history was correct and complete.
    assert commit_all_fast(config, "pt") == 3
    assert len(_git(repo, "log", "--format=%h").splitlines()) == 4  # 3 laws + meta


def test_the_meta_command_is_wired_up():
    from legalize.cli import cli

    assert "meta" in cli.commands
