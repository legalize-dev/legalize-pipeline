"""Tests for the Portuguese DRE parser and daily processing."""

from __future__ import annotations

import json
import sqlite3
from datetime import date

from legalize.countries import get_metadata_parser, get_text_parser
from legalize.fetcher.pt.parser import (
    DREMetadataParser,
    DRETextParser,
    _classify_line,
    _make_identifier,
    _strip_html,
)
from legalize.models import NormMetadata, NormStatus
from legalize.transformer.slug import norm_to_filepath


# ─── Sample data ───

SAMPLE_HTML = """
TEXTO :

PARTE I
Direitos e deveres fundamentais

TÍTULO I
Princípios gerais

Artigo 1.º
Dignidade da pessoa humana

Portugal é uma República soberana, baseada na dignidade da pessoa humana
e na vontade popular e empenhada na construção de uma sociedade livre,
justa e solidária.

Artigo 2.º
Estado de direito democrático

A República Portuguesa é um Estado de direito democrático, baseado na
soberania popular, no pluralismo de expressão e organização política
democráticas, no respeito e na garantia de efectivação dos direitos e
liberdades fundamentais e na separação e interdependência de poderes.

CAPÍTULO I
Direitos, liberdades e garantias pessoais

SECÇÃO I
Disposições gerais

Artigo 24.º
Direito à vida

1 - A vida humana é inviolável.
2 - Em caso algum haverá pena de morte.
"""

SAMPLE_HTML_WITH_TAGS = """
<sup>1</sup> - A <a href="http://example.com">vida humana</a> é inviolável.<br/>
<strong>Artigo 2.º</strong><br>
Estado de direito&nbsp;democrático
"""

SAMPLE_METADATA = {
    "claint": 123456,
    "doc_type": "LEI CONSTITUCIONAL",
    "number": "1/2005",
    "emiting_body": "ASSEMBLEIA DA REPÚBLICA",
    "source": "Serie I",
    "date": "2005-08-12",
    "notes": "Sétima revisão constitucional",
    "in_force": True,
    "series": 1,
    "dr_number": "155",
    "dre_pdf": "https://files.dre.pt/1s/2005/08/155/00005.pdf",
    "dre_key": "",
}

SAMPLE_META_DECRETO_LEI = {
    "claint": 789012,
    "doc_type": "DECRETO LEI",
    "number": "111-A/2017",
    "emiting_body": "TRABALHO; SOLIDARIEDADE E SEGURANÇA SOCIAL",
    "source": "Serie I",
    "date": "2017-08-31",
    "notes": "Altera o regime jurídico da segurança social",
    "in_force": False,
    "series": 1,
    "dr_number": "168",
    "dre_pdf": "",
    "dre_key": "",
}


# ─── Identifier tests ───


class TestMakeIdentifier:
    def test_lei(self):
        assert _make_identifier("LEI", "39/2016") == "DRE-L-39-2016"

    def test_decreto_lei(self):
        assert _make_identifier("DECRETO LEI", "111-A/2017") == "DRE-DL-111-A-2017"

    def test_lei_constitucional(self):
        assert _make_identifier("LEI CONSTITUCIONAL", "1/2005") == "DRE-LC-1-2005"

    def test_portaria(self):
        assert _make_identifier("PORTARIA", "180/2024") == "DRE-P-180-2024"

    def test_lei_organica(self):
        assert _make_identifier("LEI ORGÂNICA", "2/2023") == "DRE-LO-2-2023"

    def test_decreto_regulamentar(self):
        assert _make_identifier("DECRETO REGULAMENTAR", "5/2024") == "DRE-DR-5-2024"

    def test_empty_number(self):
        assert _make_identifier("LEI", "") == "DRE-L-UNKNOWN"

    def test_unknown_type(self):
        assert _make_identifier("TIPO RARO", "1/2024") == "DRE-X-1-2024"

    def test_filesystem_safe(self):
        ident = _make_identifier("DECRETO LEI", "111-A/2017")
        assert ":" not in ident
        assert " " not in ident
        assert "/" not in ident


# ─── HTML stripping tests ───


class TestStripHtml:
    def test_preserves_bold(self):
        assert _strip_html("<strong>bold</strong>") == "**bold**"

    def test_preserves_italic(self):
        assert _strip_html("<em>italic</em>") == "*italic*"

    def test_strips_unknown_tags(self):
        assert _strip_html("<span>text</span>") == "text"

    def test_converts_br(self):
        result = _strip_html("line1<br/>line2")
        assert "line1" in result
        assert "line2" in result

    def test_decodes_entities(self):
        assert _strip_html("A &amp; B") == "A & B"
        assert _strip_html("&nbsp;") == " "

    def test_converts_table(self):
        html = "<table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>"
        result = _strip_html(html)
        assert "| A | B |" in result
        assert "| 1 | 2 |" in result

    def test_converts_list(self):
        result = _strip_html("<ul><li>item one</li><li>item two</li></ul>")
        assert "- item one" in result
        assert "- item two" in result


# ─── Line classification tests ───


class TestClassifyLine:
    def test_artigo(self):
        btype, css, text = _classify_line("Artigo 1.º")
        assert btype == "artigo"
        assert css == "articulo"

    def test_artigo_with_title(self):
        btype, css, text = _classify_line("Artigo 1.º Objeto")
        assert btype == "artigo"
        assert "Objeto" in text

    def test_artigo_unico(self):
        btype, css, text = _classify_line("Artigo único")
        assert btype == "artigo"

    def test_capitulo(self):
        btype, css, text = _classify_line("CAPÍTULO I")
        assert btype == "capitulo"
        assert css == "capitulo_tit"

    def test_capitulo_with_title(self):
        btype, css, text = _classify_line("CAPÍTULO I — Disposições gerais")
        assert btype == "capitulo"
        assert "Disposições gerais" in text

    def test_seccao(self):
        btype, css, text = _classify_line("SECÇÃO I")
        assert btype == "seccao"
        assert css == "seccion"

    def test_titulo(self):
        btype, css, text = _classify_line("TÍTULO I")
        assert btype == "titulo"
        assert css == "titulo_tit"

    def test_parte(self):
        btype, css, text = _classify_line("PARTE I")
        assert btype == "parte"
        assert css == "titulo_tit"

    def test_normal_text(self):
        btype, css, text = _classify_line("A vida humana é inviolável.")
        assert btype == "text"
        assert css == "parrafo"


# ─── Text parser tests ───


class TestDRETextParser:
    def setup_method(self):
        self.parser = DRETextParser()

    def test_parse_produces_blocks(self):
        blocks = self.parser.parse_text(SAMPLE_HTML.encode("utf-8"))
        assert len(blocks) > 0

    def test_structural_blocks_present(self):
        blocks = self.parser.parse_text(SAMPLE_HTML.encode("utf-8"))
        types = {b.block_type for b in blocks}
        assert "artigo" in types
        assert "parte" in types
        assert "titulo" in types
        assert "capitulo" in types
        assert "seccao" in types

    def test_article_has_version(self):
        blocks = self.parser.parse_text(SAMPLE_HTML.encode("utf-8"))
        articles = [b for b in blocks if b.block_type == "artigo"]
        assert len(articles) >= 3
        for art in articles:
            assert len(art.versions) == 1
            assert len(art.versions[0].paragraphs) > 0

    def test_article_title(self):
        blocks = self.parser.parse_text(SAMPLE_HTML.encode("utf-8"))
        articles = [b for b in blocks if b.block_type == "artigo"]
        # First article should be "Artigo 1.º"
        titles = [a.title for a in articles]
        assert any("Artigo 1" in t for t in titles)

    def test_body_paragraphs(self):
        blocks = self.parser.parse_text(SAMPLE_HTML.encode("utf-8"))
        articles = [b for b in blocks if b.block_type == "artigo"]
        # Article 24 should have body text about vida humana
        art24 = [a for a in articles if "24" in a.title]
        assert len(art24) == 1
        paragraphs = art24[0].versions[0].paragraphs
        body_texts = [p.text for p in paragraphs if p.css_class == "parrafo"]
        assert any("inviolável" in t for t in body_texts)

    def test_handles_html_tags(self):
        blocks = self.parser.parse_text(SAMPLE_HTML_WITH_TAGS.encode("utf-8"))
        assert len(blocks) > 0
        # Check tags were stripped
        all_text = " ".join(p.text for b in blocks for v in b.versions for p in v.paragraphs)
        assert "<a" not in all_text
        assert "<strong" not in all_text

    def test_empty_input(self):
        blocks = self.parser.parse_text(b"")
        assert blocks == []

    def test_extract_reforms(self):
        reforms = self.parser.extract_reforms(SAMPLE_HTML.encode("utf-8"))
        assert isinstance(reforms, list)


# ─── Metadata parser tests ───


class TestDREMetadataParser:
    def setup_method(self):
        self.parser = DREMetadataParser()

    def _meta_bytes(self, data: dict) -> bytes:
        return json.dumps(data, ensure_ascii=False).encode("utf-8")

    def test_parse_lei_constitucional(self):
        meta = self.parser.parse(self._meta_bytes(SAMPLE_METADATA), "123456")
        assert isinstance(meta, NormMetadata)
        assert meta.country == "pt"
        assert meta.identifier == "DRE-LC-1-2005"
        assert meta.rank == "lei-constitucional"
        assert meta.publication_date == date(2005, 8, 12)
        assert meta.status == NormStatus.IN_FORCE

    def test_parse_decreto_lei(self):
        meta = self.parser.parse(self._meta_bytes(SAMPLE_META_DECRETO_LEI), "789012")
        assert meta.identifier == "DRE-DL-111-A-2017"
        assert meta.rank == "decreto-lei"
        assert meta.status == NormStatus.REPEALED

    def test_title_includes_numero(self):
        """Title should include 'n.º' per Portuguese convention."""
        meta = self.parser.parse(self._meta_bytes(SAMPLE_METADATA), "123456")
        assert "n.º" in meta.title
        assert "Lei Constitucional n.º 1/2005" == meta.title

    def test_department_portuguese_capitalization(self):
        """Portuguese prepositions should be lowercase in department names."""
        meta = self.parser.parse(self._meta_bytes(SAMPLE_META_DECRETO_LEI), "789012")
        assert "Trabalho" in meta.department
        assert "Solidariedade e Segurança Social" in meta.department
        # "e" should be lowercase (Portuguese conjunction)
        assert ", Solidariedade e" in meta.department

    def test_department_prepositions_lowercase(self):
        """da, do, de, e should be lowercase except at start."""
        data = {**SAMPLE_METADATA, "emiting_body": "ASSEMBLEIA DA REPÚBLICA"}
        meta = self.parser.parse(self._meta_bytes(data), "123456")
        assert meta.department == "Assembleia da República"

    def test_extra_includes_official_number(self):
        """Extra fields should include official_number."""
        meta = self.parser.parse(self._meta_bytes(SAMPLE_METADATA), "123456")
        extra_dict = dict(meta.extra)
        assert "official_number" in extra_dict
        assert extra_dict["official_number"] == "1/2005"

    def test_extra_includes_dr_number(self):
        """Extra fields should include dr_number when present."""
        meta = self.parser.parse(self._meta_bytes(SAMPLE_META_DECRETO_LEI), "789012")
        extra_dict = dict(meta.extra)
        assert "dr_number" in extra_dict
        assert extra_dict["dr_number"] == "168"

    def test_short_title(self):
        meta = self.parser.parse(self._meta_bytes(SAMPLE_METADATA), "123456")
        assert "revisão constitucional" in meta.short_title

    def test_source_url(self):
        meta = self.parser.parse(self._meta_bytes(SAMPLE_METADATA), "123456")
        assert meta.source.startswith("https://")

    def test_notes(self):
        meta = self.parser.parse(self._meta_bytes(SAMPLE_METADATA), "123456")
        assert "revisão constitucional" in meta.summary


# ─── Countries dispatch tests ───


class TestCountriesDispatchPT:
    def test_get_text_parser_pt(self):
        parser = get_text_parser("pt")
        assert isinstance(parser, DRETextParser)

    def test_get_metadata_parser_pt(self):
        parser = get_metadata_parser("pt")
        assert isinstance(parser, DREMetadataParser)


# ─── Slug tests ───


class TestSlugPortugal:
    def test_norm_path_national(self):
        meta = NormMetadata(
            title="Lei 39/2016",
            short_title="Lei 39/2016",
            identifier="DRE-L-39-2016",
            country="pt",
            rank="lei",
            publication_date=date(2016, 12, 19),
            status=NormStatus.IN_FORCE,
            department="Assembleia da República",
            source="https://dre.pt",
        )
        assert norm_to_filepath(meta) == "pt/DRE-L-39-2016.md"

    def test_norm_path_acores(self):
        meta = NormMetadata(
            title="Decreto Legislativo Regional 3/2024",
            short_title="DLR 3/2024",
            identifier="DRE-DLR-3-2024",
            country="pt",
            rank="decreto-legislativo-regional",
            publication_date=date(2024, 3, 15),
            status=NormStatus.IN_FORCE,
            department="Assembleia Legislativa dos Açores",
            source="https://dre.pt",
            jurisdiction="pt-ac",
        )
        assert norm_to_filepath(meta) == "pt-ac/DRE-DLR-3-2024.md"

    def test_norm_path_madeira(self):
        meta = NormMetadata(
            title="Decreto Legislativo Regional 1/2024",
            short_title="DLR 1/2024",
            identifier="DRE-DLR-1-2024",
            country="pt",
            rank="decreto-legislativo-regional",
            publication_date=date(2024, 1, 10),
            status=NormStatus.IN_FORCE,
            department="Assembleia Legislativa da Madeira",
            source="https://dre.pt",
            jurisdiction="pt-ma",
        )
        assert norm_to_filepath(meta) == "pt-ma/DRE-DLR-1-2024.md"


# ─── Daily processing tests ───


def _create_test_db(db_path: str) -> None:
    """Create a minimal SQLite database matching the tretas.org 2026 schema."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE dreapp_document (
            id INTEGER PRIMARY KEY,
            doc_type TEXT,
            number TEXT,
            emiting_body TEXT,
            source TEXT,
            date TEXT,
            notes TEXT,
            in_force INTEGER,
            series INTEGER,
            dr_number TEXT,
            dre_pdf TEXT,
            part TEXT DEFAULT 'L'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE dreapp_documenttext (
            id INTEGER PRIMARY KEY,
            document_id INTEGER,
            text TEXT,
            text_url TEXT,
            FOREIGN KEY (document_id) REFERENCES dreapp_document(id)
        )
        """
    )
    conn.execute(
        """INSERT INTO dreapp_document
            (id, doc_type, number, emiting_body, source, date,
             notes, in_force, series, dr_number, dre_pdf)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            1,
            "LEI",
            "50/2024",
            "ASSEMBLEIA DA REPÚBLICA",
            "Serie I",
            "2024-07-29",
            "Regime jurídico aplicável",
            1,
            1,
            "145",
            "https://files.dre.pt/example.pdf",
        ),
    )
    conn.execute(
        "INSERT INTO dreapp_documenttext (id, document_id, text, text_url) VALUES (?, ?, ?, ?)",
        (
            1,
            1,
            "Artigo 1.º\nObjeto\n\nA presente lei estabelece o regime.\n\n"
            "Artigo 2.º\nÂmbito\n\n1 - Aplica-se a todos.",
            "https://dre.pt/doc/1",
        ),
    )
    conn.execute(
        """INSERT INTO dreapp_document
            (id, doc_type, number, emiting_body, source, date,
             notes, in_force, series, dr_number, dre_pdf)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            2,
            "DECRETO LEI",
            "10/2024",
            "TRABALHO",
            "Serie I",
            "2024-07-29",
            "Altera regime",
            1,
            1,
            "145",
            "",
        ),
    )
    conn.execute(
        "INSERT INTO dreapp_documenttext (id, document_id, text, text_url) VALUES (?, ?, ?, ?)",
        (2, 2, "Artigo único\n\nO presente decreto-lei entra em vigor.", "https://dre.pt/doc/2"),
    )
    conn.commit()
    conn.close()


class TestDREClient:
    """Tests for DREClient using an in-memory-like SQLite DB."""

    def test_get_text(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _create_test_db(db_path)
        from legalize.fetcher.pt.client import DREClient

        client = DREClient(db_path=db_path)
        text = client.get_text("1")
        assert b"Artigo 1" in text
        assert b"regime" in text
        client.close()

    def test_get_metadata(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _create_test_db(db_path)
        from legalize.fetcher.pt.client import DREClient

        client = DREClient(db_path=db_path)
        meta_bytes = client.get_metadata("1")
        meta = json.loads(meta_bytes)
        assert meta["doc_type"] == "LEI"
        assert meta["number"] == "50/2024"
        assert meta["date"] == "2024-07-29"
        client.close()

    def test_missing_claint_raises(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _create_test_db(db_path)
        from legalize.fetcher.pt.client import DREClient

        import pytest

        client = DREClient(db_path=db_path)
        with pytest.raises(ValueError, match="No document found"):
            client.get_metadata("999999")
        client.close()

    def test_context_manager(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _create_test_db(db_path)
        from legalize.fetcher.pt.client import DREClient

        with DREClient(db_path=db_path) as client:
            text = client.get_text("1")
            assert len(text) > 0


class TestDREDiscovery:
    """Tests for DREDiscovery using a test SQLite DB."""

    def test_discover_all(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _create_test_db(db_path)
        from legalize.fetcher.pt.client import DREClient
        from legalize.fetcher.pt.discovery import DREDiscovery

        with DREClient(db_path=db_path) as client:
            discovery = DREDiscovery()
            ids = list(discovery.discover_all(client))
            assert len(ids) == 2
            assert "1" in ids
            assert "2" in ids

    def test_discover_daily(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _create_test_db(db_path)
        from legalize.fetcher.pt.client import DREClient
        from legalize.fetcher.pt.discovery import DREDiscovery

        with DREClient(db_path=db_path) as client:
            discovery = DREDiscovery()
            ids = list(discovery.discover_daily(client, date(2024, 7, 29)))
            assert len(ids) == 2

    def test_discover_daily_no_results(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _create_test_db(db_path)
        from legalize.fetcher.pt.client import DREClient
        from legalize.fetcher.pt.discovery import DREDiscovery

        with DREClient(db_path=db_path) as client:
            discovery = DREDiscovery()
            ids = list(discovery.discover_daily(client, date(2020, 1, 1)))
            assert ids == []


class _FakeHttpClient:
    """Mock DREHttpClient that returns test data without HTTP."""

    def __init__(self, docs):
        self._docs = docs  # list of (diploma_id, doc_type, number, text)

    @classmethod
    def create(cls, country_config):
        return cls(
            [
                (
                    "D1",
                    "LEI",
                    "50/2024",
                    "Artigo 1.º\nObjeto\n\nA presente lei estabelece o regime.",
                ),
                (
                    "D2",
                    "DECRETO LEI",
                    "10/2024",
                    "Artigo único\n\nO presente decreto-lei entra em vigor.",
                ),
            ]
        )

    def get_journals_by_date(self, date_str):
        return [{"Id": 1}]

    def get_documents_by_journal(self, journal_id, is_serie1=True):
        # LinkSitemap mirrors the real API: the detail screen is URL-driven,
        # so the daily fetches by sitemap path rather than by id.
        return [
            {
                "DiplomaConteudoId": d[0],
                "TipoActo": d[1],
                "Sumario": f"{d[1]} {d[2]}",
                "LinkSitemap": f"/dr/detalhe/lei/{d[0]}",
            }
            for d in self._docs
        ]

    @staticmethod
    def _id_from_ref(ref):
        return ref.rsplit("/", 1)[-1]

    def get_text(self, ref):
        diploma_id = self._id_from_ref(ref)
        for d in self._docs:
            if d[0] == diploma_id:
                return d[3].encode("utf-8")
        raise ValueError(f"Not found: {ref}")

    def get_metadata(self, ref):
        diploma_id = self._id_from_ref(ref)
        for d in self._docs:
            if d[0] == diploma_id:
                meta = {
                    "claint": diploma_id,
                    "doc_type": d[1],
                    "number": d[2],
                    "emiting_body": "TEST",
                    "source": "Serie I",
                    "date": "2024-07-29",
                    "notes": f"Test {d[1]} {d[2]}",
                    "in_force": True,
                    "series": 1,
                    "dr_number": "145",
                    "dre_pdf": "",
                    "dre_key": "",
                }
                return json.dumps(meta, ensure_ascii=False).encode("utf-8")
        raise ValueError(f"Not found: {diploma_id}")

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class TestDREDaily:
    """Tests for the daily() orchestration function."""

    def _init_repo(self, tmp_path):
        """Create a minimal git repo for test output."""
        import subprocess

        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        (repo_path / "pt").mkdir()
        env = {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
            "PATH": "/usr/bin:/usr/local/bin:/opt/homebrew/bin",
        }
        subprocess.run(["git", "init"], cwd=str(repo_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(repo_path),
            capture_output=True,
            env=env,
        )
        return repo_path

    def _make_config(self, repo_path, data_dir):
        from legalize.config import Config, CountryConfig, GitConfig

        return Config(
            git=GitConfig(
                committer_name="Legalize",
                committer_email="legalize@legalize.dev",
                branch="main",
                push=False,
            ),
            countries={
                "pt": CountryConfig(
                    repo_path=str(repo_path),
                    data_dir=str(data_dir),
                    source={},
                ),
            },
        )

    def test_daily_dry_run(self, tmp_path):
        """Daily dry-run discovers norms but doesn't create commits."""
        from unittest.mock import patch

        repo_path = self._init_repo(tmp_path)
        config = self._make_config(repo_path, tmp_path / "data")

        from legalize.fetcher.pt.daily import daily

        with patch("legalize.fetcher.pt.client.DREHttpClient", _FakeHttpClient):
            commits = daily(config, target_date=date(2024, 7, 29), dry_run=True)
        assert commits == 0  # dry_run doesn't create commits

    def test_daily_creates_commits(self, tmp_path):
        """Daily with real data creates commits in the repo."""
        import subprocess
        from unittest.mock import patch

        repo_path = self._init_repo(tmp_path)
        config = self._make_config(repo_path, tmp_path / "data")

        from legalize.fetcher.pt.daily import daily

        with patch("legalize.fetcher.pt.client.DREHttpClient", _FakeHttpClient):
            commits = daily(config, target_date=date(2024, 7, 29), dry_run=False)
        assert commits == 2  # Two norms on that date

        # Verify files were created
        md_files = list(repo_path.glob("pt/DRE-*.md"))
        assert len(md_files) == 2

        # Verify git log has commits
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
        )
        # init + 2 norm commits
        lines = [line for line in result.stdout.strip().split("\n") if line]
        assert len(lines) >= 3

    def test_daily_import(self):
        """Verify daily() is importable via the CLI's dynamic import pattern."""
        module = __import__("legalize.fetcher.pt.daily", fromlist=["daily"])
        assert hasattr(module, "daily")
        assert callable(module.daily)
