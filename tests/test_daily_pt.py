"""Tests for the Portugal daily incremental pipeline.

Covers:
- _discover_daily_http (journal listing, document filtering, type matching)
- daily() orchestration (dry run, no changes, error handling, state management)
"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from legalize.fetcher.pt.daily import (
    _MAJOR_TYPES,
    _discover_daily_http,
    daily,
)
from legalize.state.store import infer_last_date_from_git


# ─────────────────────────────────────────────
# Tests: _discover_daily_http
# ─────────────────────────────────────────────


class TestDiscoverDailyHttp:
    def test_discovers_major_types(self):
        mock_client = MagicMock()
        mock_client.get_journals_by_date.return_value = [{"Id": "12345"}]
        mock_client.get_documents_by_journal.return_value = [
            {"TipoActo": "Lei", "DiplomaConteudoId": "100001", "Sumario": "Altera o Código Penal"},
            {"TipoActo": "Decreto-Lei", "DiplomaConteudoId": "100002", "Sumario": "Aprova medidas"},
        ]

        result = _discover_daily_http(mock_client, date(2026, 4, 1))

        assert len(result) == 2
        assert result[0]["diploma_id"] == "100001"
        assert result[0]["doc_type"] == "LEI"
        assert result[1]["diploma_id"] == "100002"
        assert result[1]["doc_type"] == "DECRETO-LEI"

    def test_filters_non_major_types(self):
        mock_client = MagicMock()
        mock_client.get_journals_by_date.return_value = [{"Id": "12345"}]
        mock_client.get_documents_by_journal.return_value = [
            {"TipoActo": "Lei", "DiplomaConteudoId": "100001", "Sumario": "Lei importante"},
            {"TipoActo": "Aviso", "DiplomaConteudoId": "100099", "Sumario": "Aviso menor"},
        ]

        result = _discover_daily_http(mock_client, date(2026, 4, 1))

        assert len(result) == 1
        assert result[0]["doc_type"] == "LEI"

    def test_no_journals_returns_empty(self):
        mock_client = MagicMock()
        mock_client.get_journals_by_date.return_value = []

        assert _discover_daily_http(mock_client, date(2026, 4, 1)) == []

    def test_no_documents_in_journal(self):
        mock_client = MagicMock()
        mock_client.get_journals_by_date.return_value = [{"Id": "12345"}]
        mock_client.get_documents_by_journal.return_value = []

        assert _discover_daily_http(mock_client, date(2026, 4, 1)) == []

    def test_multiple_journals(self):
        mock_client = MagicMock()
        mock_client.get_journals_by_date.return_value = [{"Id": "111"}, {"Id": "222"}]
        mock_client.get_documents_by_journal.side_effect = [
            [{"TipoActo": "Lei", "DiplomaConteudoId": "100001", "Sumario": "Lei 1"}],
            [{"TipoActo": "Decreto-Lei", "DiplomaConteudoId": "100002", "Sumario": "DL 2"}],
        ]

        result = _discover_daily_http(mock_client, date(2026, 4, 1))

        assert len(result) == 2

    def test_uses_diario_id_key(self):
        mock_client = MagicMock()
        mock_client.get_journals_by_date.return_value = [{"DiarioId": "777"}]
        mock_client.get_documents_by_journal.return_value = [
            {"TipoActo": "Portaria", "DiplomaConteudoId": "100003", "Sumario": "Test"},
        ]

        result = _discover_daily_http(mock_client, date(2026, 4, 1))

        assert len(result) == 1
        mock_client.get_documents_by_journal.assert_called_once_with(777, is_serie1=True)

    def test_skips_journal_without_id(self):
        mock_client = MagicMock()
        mock_client.get_journals_by_date.return_value = [{"Name": "no id"}]

        result = _discover_daily_http(mock_client, date(2026, 4, 1))

        assert result == []
        mock_client.get_documents_by_journal.assert_not_called()

    def test_uses_conteudo_id_fallback(self):
        mock_client = MagicMock()
        mock_client.get_journals_by_date.return_value = [{"Id": "111"}]
        mock_client.get_documents_by_journal.return_value = [
            {"TipoActo": "Lei", "ConteudoId": "FALLBACK_ID", "Sumario": "Fallback"},
        ]

        result = _discover_daily_http(mock_client, date(2026, 4, 1))

        assert result[0]["diploma_id"] == "FALLBACK_ID"

    def test_all_major_types_accepted(self):
        mock_client = MagicMock()
        mock_client.get_journals_by_date.return_value = [{"Id": "111"}]
        docs = [
            {"TipoActo": t, "DiplomaConteudoId": str(i), "Sumario": f"Test {t}"}
            for i, t in enumerate(_MAJOR_TYPES)
        ]
        mock_client.get_documents_by_journal.return_value = docs

        result = _discover_daily_http(mock_client, date(2026, 4, 1))

        assert len(result) == len(_MAJOR_TYPES)


# ─────────────────────────────────────────────
# Tests: infer_last_date_from_git (PT)
# ─────────────────────────────────────────────


class TestInferLastDateFromGitPT:
    def test_infers_from_source_date(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
        (repo / "test.md").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "test\n\nSource-Date: 2026-03-28"],
            cwd=repo,
            capture_output=True,
        )

        assert infer_last_date_from_git(str(repo)) == date(2026, 3, 28)

    def test_returns_none_for_empty_repo(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)

        assert infer_last_date_from_git(str(repo)) is None


# ─────────────────────────────────────────────
# Tests: daily() orchestration
# ─────────────────────────────────────────────


class TestDailyPTOrchestration:
    def _make_config(self, tmp_path: Path):
        from legalize.config import Config, CountryConfig, GitConfig

        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        subprocess.run(["git", "init"], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t.com"], cwd=repo_path, capture_output=True
        )

        return Config(
            git=GitConfig(committer_name="Legalize", committer_email="test@test.com"),
            countries={
                "pt": CountryConfig(
                    repo_path=str(repo_path),
                    data_dir=str(tmp_path / "data"),
                    state_path=str(tmp_path / "state" / "state.json"),
                    source={},
                )
            },
        )

    @patch("legalize.fetcher.pt.client.DREHttpClient", autospec=True)
    @patch("legalize.fetcher.pt.daily._discover_daily_http")
    def test_dry_run_does_not_commit(self, mock_discover, mock_client_cls, tmp_path):
        config = self._make_config(tmp_path)

        mock_discover.return_value = [
            {"diploma_id": "100001", "doc_type": "LEI", "title": "Test law"},
        ]

        mock_client = mock_client_cls.create.return_value
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        result = daily(config, target_date=date(2026, 4, 1), dry_run=True)

        assert result == 0

    @patch("legalize.fetcher.pt.client.DREHttpClient", autospec=True)
    @patch("legalize.fetcher.pt.daily._discover_daily_http")
    def test_no_documents_returns_zero(self, mock_discover, mock_client_cls, tmp_path):
        config = self._make_config(tmp_path)

        mock_discover.return_value = []

        mock_client = mock_client_cls.create.return_value
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        result = daily(config, target_date=date(2026, 4, 1))

        assert result == 0

    @patch("legalize.fetcher.pt.client.DREHttpClient", autospec=True)
    @patch("legalize.fetcher.pt.daily._discover_daily_http")
    def test_discovery_error_continues(self, mock_discover, mock_client_cls, tmp_path):
        config = self._make_config(tmp_path)

        mock_discover.side_effect = RuntimeError("API down")

        mock_client = mock_client_cls.create.return_value
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        result = daily(config, target_date=date(2026, 4, 1))

        assert result == 0
        state_path = Path(config.get_country("pt").state_path)
        assert state_path.exists()

    @patch("legalize.fetcher.pt.client.DREHttpClient", autospec=True)
    @patch("legalize.fetcher.pt.daily._discover_daily_http")
    def test_state_saved_after_run(self, mock_discover, mock_client_cls, tmp_path):
        config = self._make_config(tmp_path)

        mock_discover.return_value = []

        mock_client = mock_client_cls.create.return_value
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        daily(config, target_date=date(2026, 4, 1))

        state_path = Path(config.get_country("pt").state_path)
        state = json.loads(state_path.read_text())
        assert state["last_summary"] == "2026-04-01"
        assert len(state["runs"]) == 1

    @patch("legalize.fetcher.pt.client.DREHttpClient", autospec=True)
    @patch("legalize.fetcher.pt.daily._discover_daily_http")
    def test_processing_error_counted(self, mock_discover, mock_client_cls, tmp_path):
        config = self._make_config(tmp_path)

        mock_discover.return_value = [
            {
                "diploma_id": "100001",
                "ref": "/dr/detalhe/lei/1-2026-100001",
                "doc_type": "LEI",
                "title": "Bad law",
            },
        ]

        mock_client = mock_client_cls.create.return_value
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get_metadata.side_effect = RuntimeError("Parse error")

        result = daily(config, target_date=date(2026, 4, 1))

        assert result == 0
        state_path = Path(config.get_country("pt").state_path)
        state = json.loads(state_path.read_text())
        assert len(state["runs"][0]["errors"]) == 1
