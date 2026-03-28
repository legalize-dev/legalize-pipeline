"""Fixtures compartidos para tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Web test database URL
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://legalize:legalize@localhost:5432/legalize_test"
)


@pytest.fixture
def constitucion_xml() -> bytes:
    """XML de ejemplo de la Constitución Española."""
    return (FIXTURES_DIR / "constitucion-sample.xml").read_bytes()


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


# ─── Web test fixtures ───


@pytest.fixture(scope="session")
def _create_test_db():
    """Create the test database once per session."""
    import psycopg2

    main_url = TEST_DB_URL.rsplit("/", 1)[0] + "/legalize"
    try:
        conn = psycopg2.connect(main_url)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("DROP DATABASE IF EXISTS legalize_test")
        cur.execute("CREATE DATABASE legalize_test")
        cur.close()
        conn.close()
    except Exception:
        pytest.skip("Postgres not available (run: docker compose up -d db)")

    yield

    try:
        conn = psycopg2.connect(main_url)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("DROP DATABASE IF EXISTS legalize_test")
        cur.close()
        conn.close()
    except Exception:
        pass


@pytest.fixture
def db_url(_create_test_db):
    return TEST_DB_URL


@pytest.fixture
def sample_laws(tmp_path):
    """Create sample JSON files for testing."""
    json_dir = tmp_path / "json"
    json_dir.mkdir()

    laws = [
        ("BOE-A-TEST-001", "Constitución de Test", "constitucion", "vigente", "es"),
        ("BOE-A-TEST-002", "Ley Orgánica de Pruebas", "ley_organica", "vigente", "es"),
        ("BOE-A-TEST-003", "Real Decreto Derogado", "real_decreto", "derogada", "es"),
    ]

    for i, (lid, titulo, rango, estado, pais) in enumerate(laws):
        data = {
            "metadata": {
                "identificador": lid,
                "titulo": titulo,
                "pais": pais,
                "rango": rango,
                "fecha_publicacion": f"2024-0{i+1}-01",
                "ultima_actualizacion": f"2024-0{i+1}-01",
                "estado": estado,
                "departamento": "Test",
                "fuente": f"https://example.com/{lid}",
            },
            "articles": [{
                "block_id": "a1",
                "block_type": "precepto",
                "title": "Artículo 1",
                "position": 0,
                "current_text": f"Texto del artículo 1 de {titulo}",
                "versions": [{"date": f"2024-0{i+1}-01", "source_id": lid, "text": f"Texto de {titulo}"}],
            }],
            "reforms": [{"date": f"2024-0{i+1}-01", "source_id": lid, "articles_affected": ["Artículo 1"]}],
        }
        (json_dir / f"{lid}.json").write_text(json.dumps(data), encoding="utf-8")

    return json_dir


@pytest.fixture
def populated_db(db_url, sample_laws):
    """Ingest sample laws into test Postgres."""
    from legalize.web.ingest import ingest_all
    ingest_all(sample_laws, db_url)
    return db_url
