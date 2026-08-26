"""Fixtures compartidos para tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# Tests create sandbox git repositories under ``tmp_path`` and shell out
# to ``git`` via subprocess. When the test suite runs from inside another
# git command's context (e.g. a pre-commit / pre-push hook), git's wrapper
# variables (GIT_DIR, GIT_INDEX_FILE, GIT_WORK_TREE) are set in the parent
# environment and would be inherited by every subprocess, making the
# sandbox commits operate on the parent repo instead — which then triggers
# the parent's pre-commit hook recursively. Strip them once at module load
# so every test sees a clean git environment.
for _var in (
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_WORK_TREE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_COMMON_DIR",
):
    os.environ.pop(_var, None)


@pytest.fixture
def constitucion_xml() -> bytes:
    """XML de ejemplo de la Constitución Española."""
    return (FIXTURES_DIR / "constitucion-sample.xml").read_bytes()


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def sample_laws(tmp_path):
    """Create sample JSON files for testing."""
    json_dir = tmp_path / "json"
    json_dir.mkdir()

    laws = [
        ("BOE-A-TEST-001", "Constitución de Test", "constitucion", "in_force", "es"),
        ("BOE-A-TEST-002", "Ley Orgánica de Pruebas", "ley_organica", "in_force", "es"),
        ("BOE-A-TEST-003", "Real Decreto Derogado", "real_decreto", "repealed", "es"),
    ]

    for i, (lid, title, rank, status, country) in enumerate(laws):
        data = {
            "metadata": {
                "identificador": lid,
                "titulo": title,
                "pais": country,
                "rango": rank,
                "fecha_publicacion": f"2024-0{i + 1}-01",
                "ultima_actualizacion": f"2024-0{i + 1}-01",
                "estado": status,
                "departamento": "Test",
                "fuente": f"https://example.com/{lid}",
            },
            "articles": [
                {
                    "block_id": "a1",
                    "block_type": "precepto",
                    "title": "Artículo 1",
                    "position": 0,
                    "current_text": f"Texto del artículo 1 de {title}",
                    "versions": [
                        {
                            "date": f"2024-0{i + 1}-01",
                            "source_id": lid,
                            "text": f"Texto de {title}",
                        }
                    ],
                }
            ],
            "reforms": [
                {"date": f"2024-0{i + 1}-01", "source_id": lid, "articles_affected": ["Artículo 1"]}
            ],
        }
        (json_dir / f"{lid}.json").write_text(json.dumps(data), encoding="utf-8")

    return json_dir


@pytest.fixture
def no_git_identity(tmp_path, monkeypatch):
    """A machine with no git identity anywhere — which is every CI runner.

    `--fresh` makes the first commit of a rebuilt repo, and it used to inherit
    the author from ambient git config. That passes on any laptop and fails on
    every runner with "Author identity unknown", so the test has to take the
    identity away to be worth anything.
    """
    empty = tmp_path / "no-gitconfig"
    # `useConfigOnly` is what makes this faithful. Without it git invents
    # user@hostname from the OS and commits with a hint, so a laptop passes a
    # test the runner fails — which is exactly how this bug survived.
    empty.write_text("[user]\n\tuseConfigOnly = true\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(empty))
    monkeypatch.setenv("HOME", str(tmp_path / "nohome"))
    for var in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(var, raising=False)
