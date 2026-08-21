"""Transport for the DRE OutSystems screenservices API.

``diariodarepublica.pt`` has no public API. This module drives the same internal
endpoints the site's own JavaScript calls, for two screens:

``Legislacao_Conteudos.Conteudo_Detalhe``
    the diploma *as published* in the Diário da República.

``LegislacaoConsolidada.LegCons_Detalhe``
    the *consolidated* text, which can be requested at any date and which is the
    only surface that carries version history.

See ``docs/pt-dre-api.md`` for how the contract was reverse-engineered and how it
has broken in the past. Two facts cost an hour each to find and are enforced here:

1. A **Block**'s data action must be posted under the *screen*'s ``viewName``.
   Posting the block's own name answers ``"No role validation found"``.
2. ``DataActionGetData`` reads the preceding action's *output* back off the screen
   state. Without the ``GetDiplomaFragByIdAndApplicationSetting`` variable it
   raises ``System.NullReferenceException``.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any

from legalize.fetcher.base import HttpClient

logger = logging.getLogger(__name__)

BASE = "https://diariodarepublica.pt/dr"
_OUTSYSTEMS_JS = f"{BASE}/scripts/OutSystems.js"
_MODULE_VERSION = f"{BASE}/moduleservices/moduleversioninfo"

# callDataAction("Name", "screenservices/...", "apiVersionHash", ...)
_CALL_DATA_ACTION = re.compile(r'callDataAction\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"')
_CSRF_PATTERNS = (
    r'AnonymousCSRFToken\s*=\s*"([^"]+)"',
    r'"X-CSRFToken","([^"]+)"',
    r'csrfTokenValue\s*=\s*"([^"]+)"',
)

# Screen JS files whose callDataAction declarations we harvest at session start.
# DRE renames actions across deploys, so each logical action matches a list of
# known name prefixes rather than one exact name.
_SCREEN_JS = (
    f"{BASE}/scripts/dr.Home.home.mvc.js",
    f"{BASE}/scripts/dr.Legislacao_Conteudos.Conteudo_Det_Diario.mvc.js",
    f"{BASE}/scripts/dr.Legislacao_Conteudos.Conteudo_Detalhe.mvc.js",
    f"{BASE}/scripts/dr.LegislacaoConsolidada.LegCons_Detalhe.mvc.js",
    f"{BASE}/scripts/dr.LegislacaoConsolidada.AlteracoesTimelineByDiplomaLegisId.mvc.js",
)

JOURNALS_BY_DATE = "journals_by_date"
DOCUMENTS_BY_JOURNAL = "documents_by_journal"
PUBLISHED_DETAIL = "published_detail"
CONS_HEADER = "cons_header"
CONS_SNAPSHOT = "cons_snapshot"
CONS_TIMELINE = "cons_timeline"

_VIEW_HOME = "Home.home"
_VIEW_DIARIO = "Legislacao_Conteudos.Conteudo_Det_Diario"
_VIEW_PUBLISHED = "Legislacao_Conteudos.Conteudo_Detalhe"
_VIEW_CONSOLIDATED = "LegislacaoConsolidada.LegCons_Detalhe"

# logical name -> (action-name prefixes, viewName to post under)
_ACTIONS: dict[str, tuple[tuple[str, ...], str]] = {
    JOURNALS_BY_DATE: (("DataActionGetDRByDataCalendario",), _VIEW_HOME),
    DOCUMENTS_BY_JOURNAL: (("DataActionGetDadosAndApplicationSettings",), _VIEW_DIARIO),
    PUBLISHED_DETAIL: (
        ("DataActionGetConteudoData", "DataActionGetAllConteudoDetalhe"),
        _VIEW_PUBLISHED,
    ),
    CONS_HEADER: (("DataActionGetDiplomaFragByIdAndApplicationSetting",), _VIEW_CONSOLIDATED),
    CONS_SNAPSHOT: (("DataActionGetData",), _VIEW_CONSOLIDATED),
    CONS_TIMELINE: (("DataActionGetConsolidacaoByDiplomaFrag",), _VIEW_CONSOLIDATED),
}

_SITEMAP_REF = re.compile(r"/dr/(?:detalhe|legislacao-consolidada)/([^/]+)/([^/?#]+)")


class DREApiError(RuntimeError):
    """The DRE OutSystems API broke its contract.

    Raised instead of degrading to an empty result, so a DRE redeploy fails the
    run in red rather than recording a silent "no norms" day.
    """


def split_sitemap_ref(ref: str) -> tuple[str, str]:
    """Split a DRE sitemap path into the screen's (Tipo, Key) inputs.

    ``/dr/detalhe/lei/29-2026-1135578391`` -> ``("lei", "29-2026-1135578391")``.
    Do not try to rebuild the key from type + number + id: a Portaria numbered
    ``349/2026/1`` does not map to its slug the way you would guess.
    """
    match = _SITEMAP_REF.search(ref or "")
    if not match:
        raise DREApiError(
            f"Cannot read a DRE document reference out of {ref!r}. Expected a path "
            f"like /dr/detalhe/lei/29-2026-1135578391."
        )
    return match.group(1), match.group(2)


class DREApi(HttpClient):
    """Authenticated session against the DRE screenservices endpoints."""

    def __init__(
        self,
        *,
        request_timeout: int = 60,
        requests_per_second: float = 2.0,
        max_retries: int = 3,
        refresh_every: int = 250,
    ) -> None:
        super().__init__(
            request_timeout=request_timeout,
            requests_per_second=requests_per_second,
            max_retries=max_retries,
            extra_headers={"Content-Type": "application/json; charset=UTF-8"},
        )
        self._refresh_every = refresh_every
        self._csrf = ""
        self._module_version = ""
        self._endpoints: dict[str, tuple[str, str, str]] = {}
        self._calls = 0
        self._lock = threading.Lock()
        self._handshake()

    # ---------------------------------------------------------------- session

    def _handshake(self) -> None:
        """Obtain the CSRF token, module version and per-action apiVersion hashes."""
        js = self._request("GET", _OUTSYSTEMS_JS).text
        for pattern in _CSRF_PATTERNS:
            found = re.search(pattern, js)
            if found:
                self._csrf = found.group(1)
                break
        if not self._csrf:
            raise DREApiError(
                f"No CSRF token in {_OUTSYSTEMS_JS} ({len(js)} bytes) — DRE changed "
                f"the token format."
            )

        version = self._request("GET", _MODULE_VERSION).json()
        if isinstance(version, list) and version:
            version = version[0]
        self._module_version = (version or {}).get("versionToken", "")
        if not self._module_version:
            raise DREApiError(f"No versionToken in {_MODULE_VERSION}: {version!r:.200}")

        declared: dict[str, tuple[str, str]] = {}
        for url in _SCREEN_JS:
            text = self._request("GET", url).text
            for name, path, api_version in _CALL_DATA_ACTION.findall(text):
                declared[name] = (path, api_version)

        # Build into a local dict and swap in one assignment. Clearing
        # ``self._endpoints`` in place while other threads read it lost 32 % of
        # requests at 8 workers in the old client (KeyError: 'document_detail').
        endpoints: dict[str, tuple[str, str, str]] = {}
        for logical, (prefixes, view) in _ACTIONS.items():
            for prefix in prefixes:
                match = next((n for n in declared if n.startswith(prefix)), None)
                if match:
                    path, api_version = declared[match]
                    endpoints[logical] = (f"{BASE}/{path.lstrip('/')}", api_version, view)
                    break
            else:
                raise DREApiError(
                    f"No action matching {prefixes} in the DRE screen JS "
                    f"({len(declared)} actions declared: {sorted(declared)}). DRE "
                    f"renamed it — add the new prefix to _ACTIONS[{logical!r}] and "
                    f"update docs/pt-dre-api.md."
                )
        self._endpoints = endpoints
        logger.info(
            "DRE session ready: %d actions, module %s", len(self._endpoints), self._module_version
        )

    # ------------------------------------------------------------------ calls

    def call(self, action: str, variables: dict[str, Any]) -> dict:
        """POST one screen data action and return its ``data`` payload."""
        with self._lock:
            self._calls += 1
            due = self._refresh_every and self._calls % self._refresh_every == 0
            if due:
                logger.info("Refreshing DRE session after %d calls", self._calls)
                self._handshake()

        url, api_version, view = self._endpoints[action]
        body = {
            "versionInfo": {"moduleVersion": self._module_version, "apiVersion": api_version},
            "viewName": view,
            "screenData": {"variables": variables},
            "clientVariables": {},
        }
        response = self._request("POST", url, json=body, headers={"X-CSRFToken": self._csrf})
        try:
            payload = response.json()
        except ValueError as exc:
            # A stale apiVersion or CSRF makes OutSystems answer with an HTML error
            # page. Left alone that surfaces as a JSONDecodeError deep in a
            # per-norm try/except and the run still ends green.
            raise DREApiError(
                f"{action} returned {response.headers.get('Content-Type', '?')} instead "
                f"of JSON (HTTP {response.status_code}): {response.text[:200]!r}"
            ) from exc

        if not isinstance(payload, dict):
            raise DREApiError(f"{action} returned {type(payload).__name__}, expected an object")
        if payload.get("exception"):
            info = payload["exception"]
            raise DREApiError(
                f"{action} raised {info.get('specificType', '?')}: {info.get('message', '?')}"
            )
        return payload.get("data") or {}

    # ------------------------------------------------------- as-published API

    def published_detail(self, ref: str) -> dict:
        """Fetch the diploma exactly as printed in the Diário da República."""
        tipo, key = split_sitemap_ref(ref)
        data = self.call(
            PUBLISHED_DETAIL,
            {
                "Tipo": tipo,
                "_tipoInDataFetchStatus": 1,
                "Key": key,
                "_keyInDataFetchStatus": 1,
                "ParteId": "0",
                "_parteIdInDataFetchStatus": 1,
            },
        )
        detail = data.get("DetalheConteudo")
        # DRE answers an unrecognised input with a fully-populated *default* record
        # (Id 0, empty Numero, DataPublicacao 1900-01-01) rather than an error.
        # Left alone that becomes a committed law with no title, date or text.
        #
        # Requiring Numero or ELI is too strict: Portugal published thousands of
        # numberless "Decreto de <data>" acts, and 24 % of a decade-stratified
        # sample has neither field. Accept any record carrying real content and
        # reject only the default one.
        if not isinstance(detail, dict) or not any(
            str(detail.get(field, "") or "").strip()
            for field in ("Numero", "ELI", "Titulo", "Sumario", "Texto", "TextoFormatado")
        ):
            raise DREApiError(
                f"{PUBLISHED_DETAIL} returned an empty record for {ref} — the screen's "
                f"Tipo/Key inputs no longer resolve. See docs/pt-dre-api.md."
            )
        return detail

    # ------------------------------------------------------- consolidated API

    @staticmethod
    def _cons_vars(
        tipo: str,
        key: str,
        ano: int,
        legis_id: str,
        frag_id: str,
        when: str,
        header: dict | None = None,
    ) -> dict:
        """The LegCons_Detalhe screen state, trimmed to what the server reads.

        Sending the index list back is what makes the site's own request 5.7 MB;
        an empty list works and keeps ours at ~5 KB.
        """
        return {
            "HasJurisprudenciaAssociadaVar": True,
            "DiplomaLegisId": legis_id,
            "IsRended": True,
            "ShowFragAlteracoes": False,
            "ShowFragDiferencas": False,
            "DiplomaFragId": frag_id,
            "DataSelecionada": when,
            "FragmentoVersaoId": "0",
            "ELI_HTML": "",
            "hasFragIdLink": False,
            "Ano": ano,
            "DataAux": when,
            "Mensagem": {"Texto": "", "IsActive": False, "AlertId": ""},
            "TituloComFragmento": "",
            "Description": "",
            "ShowRevogados": True,
            "LoadFiltro": False,
            "FragVersaoIndice": "0",
            "ShowZoom": False,
            "CurrentZoom": "1",
            "IsPageTracked": True,
            "FragmentoVersaoIdAux": "0",
            "IndexLinhaToScrollId": "",
            "IsShowConteudoRelacionado": True,
            "ShowZoomButtons": True,
            "TituloAux": "",
            "TipoConteudosBools": {
                k: False
                for k in (
                    "AcordaosSTA",
                    "Atos1",
                    "Atos2",
                    "AtosSocietarios",
                    "DGAP",
                    "DGODOUT",
                    "DiarioRepublica",
                    "Jurisprudencia",
                    "Legacor",
                    "REGTRAB",
                )
            },
            "EmissorVar": "",
            "PesquisaAvancada_Struct": _EMPTY_SEARCH,
            "IsPrint": False,
            "IsLoadingPDFConsolidacao": False,
            "Comes": "",
            "WithConteudoRevogado": True,
            "ModificanteFragId": "0",
            "IndiceList": {"List": [], "EmptyListItem": {}},
            "IsFiltrar": False,
            "WithAlteracoes": True,
            "SumarioAux": "",
            "Tipo": tipo,
            "_tipoInDataFetchStatus": 1,
            "Key": key,
            "_keyInDataFetchStatus": 1,
            # DataActionGetData reads this action's own output back off the screen.
            "GetDiplomaFragByIdAndApplicationSetting": header or {},
        }

    def consolidated_header(self, tipo: str, ano: int, frag_id: str) -> dict:
        """Resolve a consolidated diploma's header: DiplomaLegisId, ELI, title."""
        return self.call(
            CONS_HEADER,
            self._cons_vars(tipo, f"{ano}-{frag_id}", ano, "0", frag_id, "2100-01-01"),
        )

    def consolidated_snapshot(
        self, tipo: str, ano: int, frag_id: str, legis_id: str, when: str, header: dict
    ) -> dict:
        """Fetch every fragment of a consolidated diploma as of ``when``."""
        return self.call(
            CONS_SNAPSHOT,
            self._cons_vars(tipo, f"{ano}-{frag_id}", ano, legis_id, frag_id, when, header),
        )

    def consolidated_timeline(self, legis_id: str, frag_id: str) -> list[dict]:
        """Fetch the amendment timeline: every act that changed this diploma."""
        data = self.call(
            CONS_TIMELINE,
            {
                "DiplomaLegisId": legis_id,
                "_diplomaLegisIdInDataFetchStatus": 1,
                "DiplomaFragId": frag_id,
                "_diplomaFragIdInDataFetchStatus": 1,
                "Data": "2100-01-01",
                "_dataInDataFetchStatus": 1,
                "ModificanteFragId": "0",
                "_modificanteFragIdInDataFetchStatus": 1,
                "Modificacoes": {"List": [], "EmptyListItem": {}},
                "IsRendered": True,
                "IsRenderingFragmentoVersao": False,
                "IsLoadingChangesForNewDate": False,
                "ShowAllAlteracoes": True,
                "SelectedDiploLegisId": "0",
                "SelectedDataValidacao": "1900-01-01",
                "SelectedModificanteFragId": "0",
                "ModificanteFragIdAux": "",
                "DataAux": "2100-01-01",
            },
        )
        return (data.get("ModificacoesList") or {}).get("List") or []

    # ------------------------------------------------------------ journal walk

    def journals_by_date(self, iso_date: str) -> list[dict]:
        """The Diário da República issues published on one date."""
        data = self.call(
            JOURNALS_BY_DATE,
            {
                "DataCalendario": iso_date,
                "_dataCalendarioInDataFetchStatus": 1,
                # Sentinel required by DRE's Elasticsearch date filter.
                "DataUltimaPublicacao": "2099-11-26",
                "HasSerie1": True,
                "HasSerie2": False,
                "IsRendered": True,
            },
        )
        raw = data.get("Json_Out")
        if isinstance(raw, str) and raw:
            hits = (json.loads(raw).get("hits") or {}).get("hits") or []
            return [
                {
                    "Id": (h.get("_source") or {}).get("dbId"),
                    "Numero": (h.get("_source") or {}).get("numero", ""),
                    "DataPublicacao": (h.get("_source") or {}).get("dataPublicacao", ""),
                }
                for h in hits
            ]
        serie1 = data.get("SerieI")
        if isinstance(serie1, dict):
            return serie1.get("List") or []
        if isinstance(serie1, list):
            return serie1
        # An empty list is a legitimate answer (Sundays, holidays); an unreadable
        # response is not.
        raise DREApiError(
            f"{JOURNALS_BY_DATE} for {iso_date} returned neither Json_Out nor SerieI — "
            f"keys: {sorted(data)}. DRE changed the response shape."
        )

    def documents_by_journal(self, journal_id: int | str) -> list[dict]:
        """Every document in one Série I issue."""
        data = self.call(
            DOCUMENTS_BY_JOURNAL,
            {
                "DetalheConteudo2": {"List": [], "EmptyListItem": {}},
                "ParteIdAux": "0",
                "IsFinished": False,
                "DiplomaIds": {"List": [], "EmptyListItem": "0"},
                "NumeroDeResultadosPorPagina": 2500,
                "DiarioIdAux": journal_id,
                "DiarioId": journal_id,
                "_diarioIdInDataFetchStatus": 1,
                "ParteId": "0",
                "_parteIdInDataFetchStatus": 1,
                "IsSerieI": True,
                "_isSerieIInDataFetchStatus": 1,
                "Diario_DetalheConteudo": {"Id": "", "Titulo": "", "DataPublicacao": ""},
                "_diario_DetalheConteudoInDataFetchStatus": 1,
            },
        )
        for key in ("DetalheConteudo", "DetalheConteudo2"):
            container = data.get(key)
            if isinstance(container, dict) and container.get("List"):
                return container["List"]
            if isinstance(container, list) and container:
                return container
        raw = data.get("Json_Out")
        if isinstance(raw, str) and raw:
            hits = (json.loads(raw).get("hits") or {}).get("hits") or []
            return [h.get("_source") or {} for h in hits]
        raise DREApiError(
            f"{DOCUMENTS_BY_JOURNAL} for issue {journal_id} returned no readable list "
            f"— keys: {sorted(data)}. An issue always has documents."
        )

    # ---------------------------------------------------------------- helpers

    def get_json(self, url: str) -> Any:
        return json.loads(self._request("GET", url).text)

    def get_text_body(self, url: str) -> str:
        return self._request("GET", url).text

    def close(self) -> None:
        self._session.close()

    def get_text(self, norm_id: str) -> bytes:  # pragma: no cover - not used directly
        raise NotImplementedError("Use DREClient, not DREApi, as the pipeline client")

    def get_metadata(self, norm_id: str) -> bytes:  # pragma: no cover
        raise NotImplementedError("Use DREClient, not DREApi, as the pipeline client")


_EMPTY_SEARCH: dict[str, Any] = {
    "tipoConteudo": {"List": [], "EmptyListItem": ""},
    "serie": {"List": [], "EmptyListItem": ""},
    "numero": "",
    "ano": "0",
    "suplemento": "0",
    "dataPublicacao": "",
    "dataPublicacaoDe": "1900-01-01",
    "dataPublicacaoAte": "1900-01-01",
    "parte": "",
    "apendice": "",
    "fasciculo": "",
    "tipo": {"List": [], "EmptyListItem": ""},
    "emissor": {"List": [], "EmptyListItem": ""},
    "texto": "",
    "sumario": "",
    "entidadeProponente": {"List": [], "EmptyListItem": ""},
    "numeroDR": "",
    "paginaInicial": "0",
    "paginaFinal": "0",
    "dataAssinatura": "",
    "dataDistribuicao": "",
    "entidadePrincipal": {"List": [], "EmptyListItem": ""},
    "entidadeEmitente": {"List": [], "EmptyListItem": ""},
    "docType": "",
    "proferido": "",
    "processo": "",
    "assunto": "",
    "recorrente": "",
    "recorrido": "",
    "relator": "",
    "empresa": "",
    "concelho": "",
    "nif": "",
    "anuncio": "",
    "numeroDoc": "",
    "DataAssinaturaDe": "1900-01-01",
    "DataAssinaturaAte": "1900-01-01",
    "DataDistribuicaoDe": "1900-01-01",
    "DataDistribuicaoAte": "1900-01-01",
    "semestre": "",
    "IsLegConsolidadaSelected": False,
    "IsFromData": False,
    "DescritorList": {"List": [], "EmptyListItem": ""},
}
