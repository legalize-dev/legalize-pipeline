"""Tests for DRE OutSystems endpoint discovery and loud failure (Portugal).

The daily run against diariodarepublica.pt broke in May 2026 when DRE
redeployed and renamed its screen actions.  The client kept warning
"Could not extract apiVersion", posted to the old URL, got an HTML error
page back, and the job still finished green with zero commits.

These tests pin the two halves of the fix:
  1. endpoint URL + apiVersion are read from the screen JS at runtime, and a
     renamed action is still found (or raises if it cannot be);
  2. anything that is not a readable JSON answer raises DREApiError instead
     of degrading to an empty result.
"""

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from legalize.fetcher.pt.client import (
    DOCUMENT_DETAIL,
    JOURNALS_BY_DATE,
    DREApiError,
    DREHttpClient,
)
from legalize.fetcher.pt.daily import daily

# Real shape of dr.Home.home.mvc.js after the May 2026 DRE redeploy: the
# action gained an "AndCheckUserLog" suffix and a fresh apiVersion hash.
_HOME_JS_RENAMED = (
    "var callContext = controller.callContext(callContext);\n"
    'return controller.callDataAction("DataActionGetContagens", '
    '"screenservices/dr/Home/home/DataActionGetContagens", "BdsM+VO38pdcAF3wnMGdpQ", '
    "function (b) {});\n"
    'return controller.callDataAction("DataActionGetDRByDataCalendarioAndCheckUserLog", '
    '"screenservices/dr/Home/home/DataActionGetDRByDataCalendarioAndCheckUserLog", '
    '"k+86ytikYIT6brie_oLQTQ", function (b) {});\n'
)


def _html_response(status: int = 200) -> requests.Response:
    """A real Response carrying an OutSystems HTML error page."""
    resp = requests.Response()
    resp.status_code = status
    resp._content = b"\n<!DOCTYPE html>\n<html><body>Ocorreu um erro</body></html>"
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


def _json_response(payload: dict) -> requests.Response:
    import json as _json

    resp = requests.Response()
    resp.status_code = 200
    resp._content = _json.dumps(payload).encode()
    resp.headers["Content-Type"] = "application/json; charset=utf-8"
    return resp


def _client() -> DREHttpClient:
    """A client with the network handshake skipped."""
    with patch.object(DREHttpClient, "_init_session"):
        client = DREHttpClient(timeout=5)
    client._csrf_token = "csrf-token"
    client._module_version = "9DeZ4j9NYEpfCiXfe3gDLw"
    client._endpoints = {
        name: (f"https://diariodarepublica.pt/dr/screenservices/{name}", "hash")
        for name in (JOURNALS_BY_DATE, DOCUMENT_DETAIL, "documents_by_journal")
    }
    return client


# ─────────────────────────────────────────────
# Endpoint discovery
# ─────────────────────────────────────────────


class TestResolveEndpoint:
    def test_finds_renamed_action_by_prefix(self):
        """A suffix added to the action name must not break discovery."""
        client = _client()

        url, api_version = client._resolve_endpoint(
            JOURNALS_BY_DATE, _HOME_JS_RENAMED, "home.mvc.js", ("DataActionGetDRByDataCalendario",)
        )

        assert url.endswith(
            "/screenservices/dr/Home/home/DataActionGetDRByDataCalendarioAndCheckUserLog"
        )
        assert api_version == "k+86ytikYIT6brie_oLQTQ"

    def test_missing_action_raises_with_diagnostics(self):
        """A wholesale rename must fail loudly and name what it did find."""
        client = _client()

        with pytest.raises(DREApiError) as exc:
            client._resolve_endpoint(
                JOURNALS_BY_DATE, _HOME_JS_RENAMED, "home.mvc.js", ("DataActionGetSomethingElse",)
            )

        message = str(exc.value)
        assert "DataActionGetSomethingElse" in message
        assert "DataActionGetContagens" in message  # lists what the JS does contain

    def test_empty_js_raises(self):
        """A JS file served as an error page yields no actions at all."""
        client = _client()

        with pytest.raises(DREApiError):
            client._resolve_endpoint(
                JOURNALS_BY_DATE, "", "home.mvc.js", ("DataActionGetDRByDataCalendario",)
            )


# ─────────────────────────────────────────────
# _post: HTML instead of JSON
# ─────────────────────────────────────────────


class TestPostFailsLoudly:
    def test_html_instead_of_json_raises(self):
        """The exact May 2026 failure: stale apiVersion → HTML error page."""
        client = _client()

        with (
            patch.object(client, "_request", return_value=_html_response()),
            pytest.raises(DREApiError) as exc,
        ):
            client._post(JOURNALS_BY_DATE, {})

        message = str(exc.value)
        assert "instead of JSON" in message
        assert "text/html" in message

    def test_server_exception_raises(self):
        """OutSystems answers 200 + JSON with an `exception` field."""
        client = _client()
        payload = {
            "data": {},
            "exception": {
                "name": "ServerException",
                "specificType": "System.InvalidOperationException",
                "message": "No role validation found",
            },
        }

        with (
            patch.object(client, "_request", return_value=_json_response(payload)),
            pytest.raises(DREApiError, match="No role validation found"),
        ):
            client._post(JOURNALS_BY_DATE, {})

    def test_apiversion_and_module_version_are_sent(self):
        client = _client()
        client._endpoints[JOURNALS_BY_DATE] = ("https://dre.test/action", "the-hash")
        request = MagicMock(return_value=_json_response({"data": {}}))

        with patch.object(client, "_request", request):
            client._post(JOURNALS_BY_DATE, {})

        sent = request.call_args.kwargs["json"]
        assert sent["versionInfo"]["apiVersion"] == "the-hash"
        assert sent["versionInfo"]["moduleVersion"] == "9DeZ4j9NYEpfCiXfe3gDLw"
        assert request.call_args.kwargs["headers"]["X-CSRFToken"] == "csrf-token"


# ─────────────────────────────────────────────
# get_journals_by_date: empty day vs broken API
# ─────────────────────────────────────────────


class TestJournalsByDate:
    def test_empty_hits_is_a_legitimate_empty_day(self):
        """Sundays and holidays really do publish nothing — no false alarm."""
        client = _client()
        payload = {"data": {"Json_Out": '{"hits": {"hits": []}}'}}

        with patch.object(client, "_request", return_value=_json_response(payload)):
            assert client.get_journals_by_date("2026-08-16") == []

    def test_hits_are_mapped(self):
        client = _client()
        payload = {
            "data": {
                "Json_Out": (
                    '{"hits": {"hits": [{"_source": {"dbId": 1159106555, "numero": "159",'
                    ' "dataPublicacao": "2026-08-18",'
                    ' "conteudoTitle": "Di\\u00e1rio da Rep\\u00fablica n.\\u00ba 159/2026, S\\u00e9rie I de 2026-08-18"}}]}}'
                )
            }
        }

        with patch.object(client, "_request", return_value=_json_response(payload)):
            journals = client.get_journals_by_date("2026-08-18")

        assert len(journals) == 1
        assert journals[0]["Id"] == 1159106555
        assert "Série I" in journals[0]["conteudoTitle"]

    def test_unreadable_shape_raises(self):
        """Neither Json_Out nor SerieI means DRE changed the contract."""
        client = _client()
        payload = {"data": {"SomethingNew": {"List": []}}}

        with (
            patch.object(client, "_request", return_value=_json_response(payload)),
            pytest.raises(DREApiError, match="response shape"),
        ):
            client.get_journals_by_date("2026-08-18")


# ─────────────────────────────────────────────
# get_document_detail: default record is not a document
# ─────────────────────────────────────────────


class TestDocumentDetail:
    def test_default_record_raises(self):
        """DRE answers an unknown input with Id 0 / 1900-01-01, not an error."""
        client = _client()
        payload = {
            "data": {
                "DetalheConteudo": {
                    "Id": 0,
                    "Numero": "",
                    "ELI": "",
                    "DataPublicacao": "1900-01-01",
                }
            }
        }

        with (
            patch.object(client, "_request", return_value=_json_response(payload)),
            pytest.raises(DREApiError, match="empty record"),
        ):
            client.get_document_detail("1159106557")

    def test_real_record_passes_through(self):
        client = _client()
        payload = {
            "data": {
                "DetalheConteudo": {
                    "Id": 1159106557,
                    "Numero": "169/2026",
                    "ELI": "https://data.dre.pt/eli/dec-lei/169/2026",
                    "DataPublicacao": "2026-08-18",
                    "Texto": "<p>Artigo 1.º</p>",
                }
            }
        }

        with patch.object(client, "_request", return_value=_json_response(payload)):
            detail = client.get_document_detail("1159106557")

        assert detail["Numero"] == "169/2026"


# ─────────────────────────────────────────────
# daily(): red job, state untouched
# ─────────────────────────────────────────────


class TestDailyAbortsOnApiBreak:
    def _make_config(self, tmp_path: Path):
        from legalize.config import Config, CountryConfig, GitConfig

        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        subprocess.run(["git", "init"], cwd=repo_path, capture_output=True, check=False)

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
    def test_api_break_raises_instead_of_zero_commits(
        self, mock_discover, mock_client_cls, tmp_path
    ):
        """The regression that cost three months: 0 commits used to exit green."""
        config = self._make_config(tmp_path)
        mock_discover.side_effect = DREApiError("returned text/html instead of JSON")

        mock_client = mock_client_cls.create.return_value
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with pytest.raises(DREApiError):
            daily(config, target_date=date(2026, 8, 10))

    @patch("legalize.fetcher.pt.client.DREHttpClient", autospec=True)
    @patch("legalize.fetcher.pt.daily._discover_daily_http")
    def test_api_break_does_not_advance_state(self, mock_discover, mock_client_cls, tmp_path):
        """A day we could not read must stay unprocessed, not be marked done."""
        config = self._make_config(tmp_path)
        mock_discover.side_effect = DREApiError("returned text/html instead of JSON")

        mock_client = mock_client_cls.create.return_value
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with pytest.raises(DREApiError):
            daily(config, target_date=date(2026, 8, 10))

        state_path = Path(config.get_country("pt").state_path)
        assert not state_path.exists() or "2026-08-10" not in state_path.read_text()

    @patch("legalize.fetcher.pt.client.DREHttpClient", autospec=True)
    @patch("legalize.fetcher.pt.daily._discover_daily_http")
    def test_transient_error_still_continues(self, mock_discover, mock_client_cls, tmp_path):
        """Non-contract errors keep the old per-date tolerance."""
        config = self._make_config(tmp_path)
        mock_discover.side_effect = RuntimeError("connection reset")

        mock_client = mock_client_cls.create.return_value
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        assert daily(config, target_date=date(2026, 8, 10)) == 0
