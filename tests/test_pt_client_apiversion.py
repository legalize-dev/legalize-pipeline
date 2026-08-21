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

from unittest.mock import MagicMock, patch

import pytest
import requests

from legalize.fetcher.pt.dre_api import (
    DOCUMENTS_BY_JOURNAL,
    JOURNALS_BY_DATE,
    PUBLISHED_DETAIL,
    DREApi,
    DREApiError,
    split_sitemap_ref,
)

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


def _client() -> DREApi:
    """A client with the network handshake skipped."""
    with patch.object(DREApi, "_handshake"):
        client = DREApi(request_timeout=5)
    client._csrf_token = "csrf-token"
    client._module_version = "9DeZ4j9NYEpfCiXfe3gDLw"
    client._endpoints = {
        name: (f"https://diariodarepublica.pt/dr/screenservices/{name}", "hash", "View.view")
        for name in (JOURNALS_BY_DATE, PUBLISHED_DETAIL, DOCUMENTS_BY_JOURNAL)
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
            client.call(JOURNALS_BY_DATE, {})

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
            client.call(JOURNALS_BY_DATE, {})

    def test_apiversion_and_module_version_are_sent(self):
        client = _client()
        client._endpoints[JOURNALS_BY_DATE] = ("https://dre.test/action", "the-hash", "Home.home")
        request = MagicMock(return_value=_json_response({"data": {}}))

        with patch.object(client, "_request", request):
            client.call(JOURNALS_BY_DATE, {})

        sent = request.call_args.kwargs["json"]
        assert sent["versionInfo"]["apiVersion"] == "the-hash"
        assert sent["versionInfo"]["moduleVersion"] == "9DeZ4j9NYEpfCiXfe3gDLw"
        assert request.call_args.kwargs["headers"]["X-CSRFToken"] == "csrf-token"
        # A Block's action must post under the *screen* viewName, or DRE answers
        # "No role validation found" — see docs/pt-dre-api.md.
        assert sent["viewName"] == "Home.home"


# ─────────────────────────────────────────────
# journals_by_date: empty day vs broken API
# ─────────────────────────────────────────────


class TestJournalsByDate:
    def test_empty_hits_is_a_legitimate_empty_day(self):
        """Sundays and holidays really do publish nothing — no false alarm."""
        client = _client()
        payload = {"data": {"Json_Out": '{"hits": {"hits": []}}'}}

        with patch.object(client, "_request", return_value=_json_response(payload)):
            assert client.journals_by_date("2026-08-16") == []

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
            journals = client.journals_by_date("2026-08-18")

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
            client.journals_by_date("2026-08-18")


# ─────────────────────────────────────────────
# The detail screen is URL-driven
# ─────────────────────────────────────────────


class TestSitemapRef:
    """The detail screen takes the URL's type and key, never a raw id."""

    def test_splits_a_sitemap_path(self):
        assert split_sitemap_ref("/dr/detalhe/decreto-lei/169-2026-1159106557") == (
            "decreto-lei",
            "169-2026-1159106557",
        )

    def test_splits_a_full_url(self):
        assert split_sitemap_ref(
            "https://diariodarepublica.pt/dr/detalhe/portaria/349-2026-1159106558"
        ) == ("portaria", "349-2026-1159106558")

    @pytest.mark.parametrize("ref", ["", "1159106557", "/dr/home", None])
    def test_unusable_reference_raises(self, ref):
        with pytest.raises(DREApiError, match="document reference"):
            split_sitemap_ref(ref)

    def test_detail_posts_tipo_and_key(self):
        """Regression: DipLegisId stopped being an input in the May 2026 deploy."""
        client = _client()
        request = MagicMock(
            return_value=_json_response(
                {"data": {"DetalheConteudo": {"Id": 1159106557, "Numero": "169/2026"}}}
            )
        )

        with patch.object(client, "_request", request):
            client.published_detail("/dr/detalhe/decreto-lei/169-2026-1159106557")

        variables = request.call_args.kwargs["json"]["screenData"]["variables"]
        assert variables["Tipo"] == "decreto-lei"
        assert variables["Key"] == "169-2026-1159106557"
        assert variables["_tipoInDataFetchStatus"] == 1
        assert variables["_keyInDataFetchStatus"] == 1
        assert "DipLegisId" not in variables


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
            client.published_detail("/dr/detalhe/decreto-lei/169-2026-1159106557")

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
            detail = client.published_detail("/dr/detalhe/decreto-lei/169-2026-1159106557")

        assert detail["Numero"] == "169/2026"


# ─────────────────────────────────────────────
# daily(): red job, state untouched
# ─────────────────────────────────────────────


class TestOutOfScopeRecords:
    """DRE indexes the Jornal Oficial dos Açores but never digitised it: 6,597 of
    the first 31,000 as-published ids are catalogue rows with no text, no PDF and
    no ELI. They are out of scope (RESEARCH-PT-v2 §11) and must not reach the
    corpus as text-less cards."""

    @staticmethod
    def _client():
        from legalize.fetcher.pt.client import DREClient

        return DREClient.__new__(DREClient)

    def test_legacor_row_yields_no_text(self):
        client = self._client()
        bundle = {
            "published": {
                "Id": "30978201",
                "Numero": "69/83",
                "Titulo": "Despacho Normativo n.º 69/83",
                "Resumo": "Efectua transferências de verbas.\x00",
                "Texto": "\x00",
                "TextoFormatado": "",
                "URL_PDF": "",
                "ELI": "",
                "TipoConteudo": "DiplomaLegacor",
                "DiplomaLegacor": {
                    "FonteRegional": "JORNAL OFICIAL DOS AÇORES - 1.ª SÉRIE, Nº 24",
                },
            }
        }
        with patch.object(type(client), "_bundle", lambda self, _id: bundle):
            with pytest.raises(ValueError, match="No text and no PDF"):
                client.get_text("pub:despacho-normativo:69-1983-30978201")

    def test_scan_only_diploma_is_kept(self):
        """The same branch must not swallow the diplomas DRE has only as a scan —
        those keep their metadata and a link to the official PDF."""
        client = self._client()
        bundle = {
            "published": {
                "Id": "559253",
                "Texto": "",
                "TextoFormatado": "",
                "URL_PDF": "https://files.diariodarepublica.pt/1s/1932/07/16200/14471448.pdf",
            }
        }
        with patch.object(type(client), "_bundle", lambda self, _id: bundle):
            assert client.get_text("pub:acordao-doutrinario:1932-559253") == b""
