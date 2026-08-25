"""``-o KEY=VALUE`` — pointing a run somewhere other than what config.yaml says.

This is what makes a rehearsal possible: build a slice of the fetch cache, run
the real chain against it, and throw it away. Before the flag the only way was
to copy config.yaml and edit the copy, which then drifts from the original.

The health case here is the one that made the flag worth adding. Every country
repo carries a README.md, and ``--deep`` used to read it as a law: no
frontmatter, so it could not be where the manifest says, so a healthy repo
reported an error and the bootstrap script's last step went red.
"""

from __future__ import annotations

import subprocess

import pytest
from click.testing import CliRunner

from legalize.cli import cli

LAW = '---\ntitle: "t"\nidentifier: "DRE-2001-3-1331261"\ncountry: "pt"\nyear: "2001"\n---\n\n# t\n'


@pytest.fixture
def repo(tmp_path):
    """A one-law pt repo in the sharded layout, with the README every repo has."""
    path = tmp_path / "pt-repo"
    (path / "pt" / "2001").mkdir(parents=True)
    (path / "pt" / "2001" / "DRE-2001-3-1331261.md").write_text(LAW)
    (path / "README.md").write_text("# legalize-pt\n\nNot a law.\n")
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"],
        cwd=path,
        check=True,
    )
    # health treats a repo with nowhere to push as an error, which it is for a
    # real country repo and noise for this one.
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:legalize-dev/legalize-pt.git"],
        cwd=path,
        check=True,
    )
    return path


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        'countries:\n  pt:\n    repo_path: "/nonexistent"\n    data_dir: "/nonexistent"\n'
    )
    return path


def test_override_redirects_the_run(config, repo):
    """The flag wins over the file, or a rehearsal would hit the real repo."""
    result = CliRunner().invoke(
        cli, ["--config", str(config), "-o", f"countries.pt.repo_path={repo}", "health", "-c", "pt"]
    )
    assert "No git repo" not in result.output, result.output
    assert "Markdown files: 1" in result.output, result.output


def test_readme_is_not_a_law(config, repo):
    """A healthy repo exits 0. The README must not count as a misplaced law."""
    result = CliRunner().invoke(
        cli,
        [
            "--config",
            str(config),
            "-o",
            f"countries.pt.repo_path={repo}",
            "health",
            "-c",
            "pt",
            "--deep",
        ],
    )
    assert "not where the manifest says" not in result.output, result.output
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("bad", ["garbage", "=value"])
def test_malformed_override_is_refused(config, bad):
    """Silently ignoring it would run against the real paths while looking overridden."""
    result = CliRunner().invoke(cli, ["--config", str(config), "-o", bad, "health", "-c", "pt"])
    assert result.exit_code != 0
    assert "KEY=VALUE" in result.output


def test_a_law_that_cannot_be_written_ends_red(tmp_path, config):
    """Data with no file is data loss. A green run is how it ships unnoticed.

    Measured on Portugal: a corpus missing the field the layout template needs
    produced 171,737 logged tracebacks, zero laws, and an exit code of 0.

    Built through the real writer rather than hand-rolled JSON, so the fixture
    cannot drift away from the format the pipeline actually reads.
    """
    from datetime import date

    from legalize.config import load_config
    from legalize.models import (
        Block,
        NormMetadata,
        NormStatus,
        Paragraph,
        ParsedNorm,
        Rank,
        Reform,
        Version,
    )
    from legalize.pipeline import UnwritableLaw, commit_all_fast
    from legalize.storage import save_structured_json

    when = date(2001, 1, 1)
    # pt's template needs {year}, which the parser puts in `extra`. This norm has
    # no such field, so there is nowhere for it to go.
    norm = ParsedNorm(
        metadata=NormMetadata(
            title="t",
            short_title="t",
            identifier="DRE-2001-3-1331261",
            country="pt",
            rank=Rank.LEY,
            publication_date=when,
            status=NormStatus.IN_FORCE,
            department="Test",
            source="https://example.com/t",
        ),
        blocks=(
            Block(
                id="a1",
                block_type="precepto",
                title="Artigo 1",
                versions=(
                    Version(
                        norm_id="DRE-2001-3-1331261",
                        publication_date=when,
                        effective_date=when,
                        paragraphs=(Paragraph(css_class="parrafo", text="x"),),
                    ),
                ),
            ),
        ),
        reforms=(Reform(date=when, norm_id="DRE-2001-3-1331261", affected_blocks=("a1",)),),
    )

    data, repo = tmp_path / "data", tmp_path / "repo"
    save_structured_json(data, norm)
    repo.mkdir()
    cfg = load_config(
        str(config), {"countries.pt.data_dir": str(data), "countries.pt.repo_path": str(repo)}
    )
    with pytest.raises(UnwritableLaw):
        commit_all_fast(cfg, "pt")


class TestFresh:
    """``--fresh`` throws away a history so a rebuilt one can take its place.

    ``commit_all_fast`` streams a whole history through fast-import and skips
    nothing already committed, so bootstrapping over a populated repo stacks a
    second history on the first. The old shell script did the wipe by hand; it
    is a flag now because the hand step is the one that gets forgotten.
    """

    @staticmethod
    def _cfg(tmp_path, repo):
        path = tmp_path / "config.yaml"
        path.write_text(
            f'countries:\n  pt:\n    repo_path: "{repo}"\n    data_dir: "{tmp_path / "data"}"\n'
        )
        return path

    def test_refuses_a_directory_that_is_not_a_repo(self, tmp_path):
        """A repo_path typo must not delete somebody's files."""
        victim = tmp_path / "not-a-repo"
        victim.mkdir()
        (victim / "keep.txt").write_text("important")

        result = CliRunner().invoke(
            cli, ["--config", str(self._cfg(tmp_path, victim)), "bootstrap", "-c", "pt", "--fresh"]
        )
        assert result.exit_code != 0
        assert "not a git repo" in result.output
        assert (victim / "keep.txt").read_text() == "important"

    def test_empties_the_repo_and_keeps_the_remote(self, tmp_path, monkeypatch):
        """The point of rebuilding a history is to push it."""
        import subprocess

        repo = tmp_path / "repo"
        repo.mkdir()
        for args in (
            ["git", "init", "-q"],
            [
                "git",
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "-qm",
                "old",
                "--allow-empty",
            ],
            ["git", "remote", "add", "origin", "git@github.com:legalize-dev/legalize-pt.git"],
        ):
            subprocess.run(args, cwd=repo, check=True)
        (repo / "stale.md").write_text("a law that no longer exists\n")

        monkeypatch.setattr("legalize.pipeline.generic_bootstrap", lambda *a, **k: 0)
        result = CliRunner().invoke(
            cli, ["--config", str(self._cfg(tmp_path, repo)), "bootstrap", "-c", "pt", "--fresh"]
        )
        assert result.exit_code == 0, result.output
        assert not (repo / "stale.md").exists()
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"], cwd=repo, capture_output=True, text=True
        )
        assert "legalize-pt" in remote.stdout
