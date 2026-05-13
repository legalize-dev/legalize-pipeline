"""Integration tests for the bootstrap pipeline."""

import subprocess
from datetime import date
from pathlib import Path

import pytest

from legalize.committer.git_ops import FastImporter
from legalize.committer.message import build_commit_info
from legalize.config import Config, CountryConfig, GitConfig
from legalize.models import CommitType, NormMetadata, NormStatus, Rank
from legalize.pipeline import bootstrap_from_local_xml, commit_all_fast
from legalize.storage import save_structured_json
from legalize.transformer.slug import norm_to_filepath
from legalize.transformer.xml_parser import extract_reforms, parse_text_xml

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def bootstrap_config(tmp_path) -> Config:
    """Config with temporary repo."""
    repo_path = str(tmp_path / "repo")
    return Config(
        git=GitConfig(),
        countries={
            "es": CountryConfig(
                repo_path=repo_path,
                data_dir=str(tmp_path / "data"),
                state_path=str(tmp_path / "state.json"),
            ),
        },
    )


@pytest.fixture
def constitucion_metadata() -> NormMetadata:
    return NormMetadata(
        title="Constitución Española",
        short_title="Constitución Española",
        identifier="BOE-A-1978-31229",
        country="es",
        rank=Rank.CONSTITUCION,
        publication_date=date(1978, 12, 29),
        status=NormStatus.IN_FORCE,
        department="Cortes Generales",
        source="https://www.boe.es/eli/es/c/1978/12/27/(1)",
    )


class TestBootstrapPipeline:
    def test_creates_4_commits(self, bootstrap_config, constitucion_metadata):
        xml_path = FIXTURES_DIR / "constitucion-sample.xml"
        count = bootstrap_from_local_xml(bootstrap_config, constitucion_metadata, xml_path)
        assert count == 4

    def test_creates_markdown_file(self, bootstrap_config, constitucion_metadata):
        xml_path = FIXTURES_DIR / "constitucion-sample.xml"
        bootstrap_from_local_xml(bootstrap_config, constitucion_metadata, xml_path)

        md_path = Path(bootstrap_config.get_country("es").repo_path) / "es" / "BOE-A-1978-31229.md"
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "Constitución Española" in content
        assert "---" in content  # frontmatter

    def test_commits_have_correct_dates(self, bootstrap_config, constitucion_metadata):
        xml_path = FIXTURES_DIR / "constitucion-sample.xml"
        bootstrap_from_local_xml(bootstrap_config, constitucion_metadata, xml_path)

        result = subprocess.run(
            ["git", "log", "--format=%ai", "--reverse"],
            cwd=bootstrap_config.get_country("es").repo_path,
            capture_output=True,
            text=True,
        )
        dates = [line.split()[0] for line in result.stdout.strip().splitlines()]
        assert dates == ["1978-12-29", "1992-08-28", "2011-09-27", "2024-02-17"]

    def test_commits_have_trailers(self, bootstrap_config, constitucion_metadata):
        xml_path = FIXTURES_DIR / "constitucion-sample.xml"
        bootstrap_from_local_xml(bootstrap_config, constitucion_metadata, xml_path)

        result = subprocess.run(
            ["git", "log", "--format=%B", "-1"],
            cwd=bootstrap_config.get_country("es").repo_path,
            capture_output=True,
            text=True,
        )
        body = result.stdout
        assert "Source-Id:" in body
        assert "Source-Date:" in body
        assert "Norm-Id: BOE-A-1978-31229" in body

    def test_idempotent_rerun(self, bootstrap_config, constitucion_metadata):
        xml_path = FIXTURES_DIR / "constitucion-sample.xml"
        count1 = bootstrap_from_local_xml(bootstrap_config, constitucion_metadata, xml_path)
        count2 = bootstrap_from_local_xml(bootstrap_config, constitucion_metadata, xml_path)
        assert count1 == 4
        assert count2 == 0  # no new commits on second run

    def test_saves_json(self, bootstrap_config, constitucion_metadata):
        xml_path = FIXTURES_DIR / "constitucion-sample.xml"
        bootstrap_from_local_xml(bootstrap_config, constitucion_metadata, xml_path)

        assert Path(
            bootstrap_config.get_country("es").data_dir, "json", "BOE-A-1978-31229.json"
        ).exists()

    def test_dry_run_creates_no_commits(self, bootstrap_config, constitucion_metadata):
        xml_path = FIXTURES_DIR / "constitucion-sample.xml"
        count = bootstrap_from_local_xml(
            bootstrap_config, constitucion_metadata, xml_path, dry_run=True
        )
        assert count == 0
        repo_path = Path(bootstrap_config.get_country("es").repo_path)
        assert not (repo_path / ".git").exists()


class TestFastImporter:
    """Tests for the git fast-import bulk commit path."""

    def test_creates_commits(self, bootstrap_config, constitucion_metadata):
        """FastImporter should create the same number of commits as normal path."""
        xml_path = FIXTURES_DIR / "constitucion-sample.xml"
        xml_bytes = xml_path.read_bytes()
        blocks = parse_text_xml(xml_bytes)
        reforms = extract_reforms(blocks)

        from legalize.transformer.markdown import render_norm_at_date

        cc = bootstrap_config.get_country("es")

        with FastImporter(cc.repo_path, "Test", "test@test.com") as fi:
            for i, reform in enumerate(reforms):
                is_first = i == 0
                commit_type = CommitType.BOOTSTRAP if is_first else CommitType.REFORM
                markdown = render_norm_at_date(
                    constitucion_metadata, blocks, reform.date, include_all=is_first
                )
                file_path = norm_to_filepath(constitucion_metadata)
                info = build_commit_info(
                    commit_type, constitucion_metadata, reform, blocks, file_path, markdown
                )
                fi.commit(file_path, markdown, info)

        assert fi.commit_count == 4

        # Verify commits in git
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=cc.repo_path,
            capture_output=True,
            text=True,
        )
        assert len(result.stdout.strip().splitlines()) == 4

    def test_creates_markdown_file(self, bootstrap_config, constitucion_metadata):
        xml_path = FIXTURES_DIR / "constitucion-sample.xml"
        xml_bytes = xml_path.read_bytes()
        blocks = parse_text_xml(xml_bytes)
        reforms = extract_reforms(blocks)

        from legalize.transformer.markdown import render_norm_at_date

        cc = bootstrap_config.get_country("es")

        with FastImporter(cc.repo_path, "Test", "test@test.com") as fi:
            for i, reform in enumerate(reforms):
                is_first = i == 0
                commit_type = CommitType.BOOTSTRAP if is_first else CommitType.REFORM
                markdown = render_norm_at_date(
                    constitucion_metadata, blocks, reform.date, include_all=is_first
                )
                file_path = norm_to_filepath(constitucion_metadata)
                info = build_commit_info(
                    commit_type, constitucion_metadata, reform, blocks, file_path, markdown
                )
                fi.commit(file_path, markdown, info)

        md_path = Path(cc.repo_path) / "es" / "BOE-A-1978-31229.md"
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "Constitución Española" in content

    def test_commits_have_historical_dates(self, bootstrap_config, constitucion_metadata):
        xml_path = FIXTURES_DIR / "constitucion-sample.xml"
        xml_bytes = xml_path.read_bytes()
        blocks = parse_text_xml(xml_bytes)
        reforms = extract_reforms(blocks)

        from legalize.transformer.markdown import render_norm_at_date

        cc = bootstrap_config.get_country("es")

        with FastImporter(cc.repo_path, "Test", "test@test.com") as fi:
            for i, reform in enumerate(reforms):
                is_first = i == 0
                commit_type = CommitType.BOOTSTRAP if is_first else CommitType.REFORM
                markdown = render_norm_at_date(
                    constitucion_metadata, blocks, reform.date, include_all=is_first
                )
                file_path = norm_to_filepath(constitucion_metadata)
                info = build_commit_info(
                    commit_type, constitucion_metadata, reform, blocks, file_path, markdown
                )
                fi.commit(file_path, markdown, info)

        result = subprocess.run(
            ["git", "log", "--format=%ai", "--reverse"],
            cwd=cc.repo_path,
            capture_output=True,
            text=True,
        )
        dates = [line.split()[0] for line in result.stdout.strip().splitlines()]
        assert dates == ["1978-12-29", "1992-08-28", "2011-09-27", "2024-02-17"]

    def test_commits_have_trailers(self, bootstrap_config, constitucion_metadata):
        xml_path = FIXTURES_DIR / "constitucion-sample.xml"
        xml_bytes = xml_path.read_bytes()
        blocks = parse_text_xml(xml_bytes)
        reforms = extract_reforms(blocks)

        from legalize.transformer.markdown import render_norm_at_date

        cc = bootstrap_config.get_country("es")

        with FastImporter(cc.repo_path, "Test", "test@test.com") as fi:
            for i, reform in enumerate(reforms):
                is_first = i == 0
                commit_type = CommitType.BOOTSTRAP if is_first else CommitType.REFORM
                markdown = render_norm_at_date(
                    constitucion_metadata, blocks, reform.date, include_all=is_first
                )
                file_path = norm_to_filepath(constitucion_metadata)
                info = build_commit_info(
                    commit_type, constitucion_metadata, reform, blocks, file_path, markdown
                )
                fi.commit(file_path, markdown, info)

        result = subprocess.run(
            ["git", "log", "--format=%B", "-1"],
            cwd=cc.repo_path,
            capture_output=True,
            text=True,
        )
        body = result.stdout
        assert "Source-Id:" in body
        assert "Source-Date:" in body
        assert "Norm-Id: BOE-A-1978-31229" in body

    def test_commit_all_fast_integration(self, bootstrap_config, constitucion_metadata):
        """commit_all_fast should produce working commits from JSON data."""
        xml_path = FIXTURES_DIR / "constitucion-sample.xml"

        # Save JSON first (like fetch would)
        cc = bootstrap_config.get_country("es")
        xml_bytes = xml_path.read_bytes()
        blocks = parse_text_xml(xml_bytes)
        reforms = extract_reforms(blocks)

        from legalize.models import ParsedNorm

        norm = ParsedNorm(
            metadata=constitucion_metadata,
            blocks=tuple(blocks),
            reforms=tuple(reforms),
        )
        save_structured_json(cc.data_dir, norm)

        count = commit_all_fast(bootstrap_config, "es")
        assert count == 4

        md_path = Path(cc.repo_path) / "es" / "BOE-A-1978-31229.md"
        assert md_path.exists()

    def test_seeds_from_existing_main_tip(self, bootstrap_config, constitucion_metadata):
        """FastImporter should extend an existing branch instead of orphaning it.

        Regression: without an explicit ``from`` clause on the first commit,
        git fast-import refuses to fast-forward refs/heads/main onto an
        unrelated tip and the imported commits become unreachable.
        """
        xml_path = FIXTURES_DIR / "constitucion-sample.xml"
        xml_bytes = xml_path.read_bytes()
        blocks = parse_text_xml(xml_bytes)
        reforms = extract_reforms(blocks)

        from legalize.transformer.markdown import render_norm_at_date

        cc = bootstrap_config.get_country("es")

        # Seed the repo with a baseline commit on refs/heads/main.
        repo = Path(cc.repo_path)
        repo.mkdir(parents=True, exist_ok=True)
        for cmd in (
            ["git", "init", "-q", "-b", "main"],
            ["git", "config", "user.email", "test@test"],
            ["git", "config", "user.name", "test"],
        ):
            subprocess.run(cmd, cwd=repo, check=True, capture_output=True)
        (repo / "baseline.md").write_text("baseline\n")
        subprocess.run(["git", "add", "baseline.md"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "baseline"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        baseline_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        with FastImporter(cc.repo_path, "Test", "test@test.com") as fi:
            for i, reform in enumerate(reforms):
                is_first = i == 0
                commit_type = CommitType.BOOTSTRAP if is_first else CommitType.REFORM
                markdown = render_norm_at_date(
                    constitucion_metadata, blocks, reform.date, include_all=is_first
                )
                file_path = norm_to_filepath(constitucion_metadata)
                info = build_commit_info(
                    commit_type, constitucion_metadata, reform, blocks, file_path, markdown
                )
                fi.commit(file_path, markdown, info)

        # Total commits = baseline + reforms; baseline must still be reachable.
        log = subprocess.run(
            ["git", "rev-list", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        assert len(log) == fi.commit_count + 1
        assert baseline_sha in log
        assert log[-1] == baseline_sha  # oldest = baseline

        # The baseline file survives alongside the new norm file.
        assert (repo / "baseline.md").exists()
        assert (repo / "es" / "BOE-A-1978-31229.md").exists()
