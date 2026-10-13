"""Health distinguishes legal pre-epoch clamps from unexplained epoch dates."""

from __future__ import annotations

import importlib
import os
import subprocess

import pytest
from click.testing import CliRunner

from legalize.cli import cli

NORM_ID = "DRE-1922-1-test"


def _repo(tmp_path, *, publication_date, source_date, author_date, snapshots=1):
    repo = tmp_path / "repo"
    # Use a sharded path: an undated version must find its norm through the
    # existing file inventory, not assume <country>/<identifier>.md.
    law = repo / "pt" / "1922" / f"{NORM_ID}.md"
    law.parent.mkdir(parents=True)
    law.write_text(
        f'---\nidentifier: "{NORM_ID}"\ntitle: "Example Act"\n'
        f'country: "pt"\nyear: "1922"\npublication_date: "{publication_date}"\n'
        'source: "https://example.test/act"\n---\n\n# Example Act\n\nOriginal text.\n'
    )
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", str(law)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", str(tmp_path / "unused.git")],
        check=True,
    )
    for number in range(snapshots):
        trailers = f"Source-Id: {NORM_ID}@snapshot-{number}\nNorm-Id: {NORM_ID}"
        if source_date is not None:
            trailers += f"\nSource-Date: {source_date}"
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@test",
                "commit",
                "--allow-empty",
                "-qm",
                f"[reform] Example Act\n\n{trailers}",
            ],
            env={
                **os.environ,
                "GIT_AUTHOR_DATE": f"{author_date}T00:00:00+00:00",
                "GIT_COMMITTER_DATE": "2024-01-01T00:00:00+00:00",
            },
            check=True,
        )
    config = tmp_path / "config.yaml"
    config.write_text(f'countries:\n  pt:\n    repo_path: "{repo}"\n')
    return config


@pytest.mark.parametrize(
    "publication_date,source_date,author_date,warning",
    [
        ("1922-12-06", "1922-12-06", "1970-01-02", False),
        ("1970-06-04", "1970-06-04", "1970-06-04", False),
        ("1970-01-01", "1970-01-01", "1970-01-02", False),
        ("2024-01-01", "2024-01-01", "1970-01-02", True),
        ("1922-12-06", "1922-12-06", "1970-06-04", True),
        ("1922-12-06", None, "1970-01-02", False),
        ("1970-06-04", None, "1970-06-04", False),
        ("2024-01-01", None, "1970-01-02", True),
        ("1922-12-06", "not-a-date", "1970-01-02", True),
        ("1922-12-06", "1922-12-06T00:00:00", "1970-01-02", True),
        ("1922-12-06", "", "1970-01-02", True),
        ("1922-12-06", "1922-12-06\nSource-Date: 2024-01-01", "1970-01-02", True),
        ("not-a-date", None, "1970-01-02", True),
    ],
    ids=[
        "pre-epoch-clamp",
        "real-1970",
        "git-minimum-day",
        "spurious-epoch",
        "wrong-clamp-day",
        "undated-snapshot",
        "undated-real-1970",
        "unexplained-undated-epoch",
        "malformed-source-date",
        "date-prefix-only",
        "empty-source-date",
        "ambiguous-source-dates",
        "malformed-publication-date",
    ],
)
def test_epoch_dates_need_legal_evidence(
    tmp_path, publication_date, source_date, author_date, warning
):
    config = _repo(
        tmp_path,
        publication_date=publication_date,
        source_date=source_date,
        author_date=author_date,
    )
    result = CliRunner().invoke(cli, ["--config", str(config), "health", "-c", "pt"])
    assert result.exit_code == 0, result.output
    assert ("commit(s) with epoch date (1970)" in result.output) is warning, result.output


def test_undated_snapshots_read_publication_once(tmp_path, monkeypatch):
    config = _repo(
        tmp_path,
        publication_date="1922-12-06",
        source_date=None,
        author_date="1970-01-02",
        snapshots=8,
    )
    module = importlib.import_module("legalize.cli")
    read_frontmatter = module._read_frontmatter
    reads = []

    def record_read(path):
        reads.append(path)
        return read_frontmatter(path)

    monkeypatch.setattr(module, "_read_frontmatter", record_read)
    result = CliRunner().invoke(cli, ["--config", str(config), "health", "-c", "pt"])
    assert result.exit_code == 0, result.output
    assert "epoch date" not in result.output, result.output
    assert len(reads) == 1
