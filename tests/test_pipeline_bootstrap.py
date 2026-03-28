"""Integration tests for the bootstrap pipeline."""

import subprocess
from datetime import date
from pathlib import Path

import pytest

from legalize.config import Config, GitConfig
from legalize.models import EstadoNorma, NormaMetadata, Rango
from legalize.pipeline import bootstrap_from_local_xml

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def bootstrap_config(tmp_path) -> Config:
    """Config with temporary repo."""
    return Config(
        git=GitConfig(repo_path=str(tmp_path / "repo")),
        state_path=str(tmp_path / "state.json"),
        mappings_path=str(tmp_path / "mappings.json"),
    )


@pytest.fixture
def constitucion_metadata() -> NormaMetadata:
    return NormaMetadata(
        titulo="Constitución Española",
        titulo_corto="Constitución Española",
        identificador="BOE-A-1978-31229",
        pais="es",
        rango=Rango.CONSTITUCION,
        fecha_publicacion=date(1978, 12, 29),
        estado=EstadoNorma.VIGENTE,
        departamento="Cortes Generales",
        fuente="https://www.boe.es/eli/es/c/1978/12/27/(1)",
    )


class TestBootstrapPipeline:
    def test_creates_4_commits(self, bootstrap_config, constitucion_metadata):
        xml_path = FIXTURES_DIR / "constitucion-sample.xml"
        count = bootstrap_from_local_xml(bootstrap_config, constitucion_metadata, xml_path)
        assert count == 4

    def test_creates_markdown_file(self, bootstrap_config, constitucion_metadata):
        xml_path = FIXTURES_DIR / "constitucion-sample.xml"
        bootstrap_from_local_xml(bootstrap_config, constitucion_metadata, xml_path)

        md_path = Path(bootstrap_config.git.repo_path) / "constituciones" / "BOE-A-1978-31229.md"
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "Constitución Española" in content
        assert "---" in content  # frontmatter

    def test_commits_have_correct_dates(self, bootstrap_config, constitucion_metadata):
        xml_path = FIXTURES_DIR / "constitucion-sample.xml"
        bootstrap_from_local_xml(bootstrap_config, constitucion_metadata, xml_path)

        result = subprocess.run(
            ["git", "log", "--format=%ai", "--reverse"],
            cwd=bootstrap_config.git.repo_path,
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
            cwd=bootstrap_config.git.repo_path,
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

    def test_saves_mappings(self, bootstrap_config, constitucion_metadata):
        xml_path = FIXTURES_DIR / "constitucion-sample.xml"
        bootstrap_from_local_xml(bootstrap_config, constitucion_metadata, xml_path)

        assert Path(bootstrap_config.mappings_path).exists()
        assert Path(bootstrap_config.data_dir, "json", "BOE-A-1978-31229.json").exists()

    def test_dry_run_creates_no_commits(self, bootstrap_config, constitucion_metadata):
        xml_path = FIXTURES_DIR / "constitucion-sample.xml"
        count = bootstrap_from_local_xml(
            bootstrap_config, constitucion_metadata, xml_path, dry_run=True
        )
        assert count == 0
        repo_path = Path(bootstrap_config.git.repo_path)
        assert not (repo_path / ".git").exists()
