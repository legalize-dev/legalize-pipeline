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
    f"{BASE}/scripts/dr.Home.WB_Serie1_List.mvc.js",
    f"{BASE}/scripts/dr.AnaliseJuridica.AnaliseJuridica.mvc.js",
    f"{BASE}/scripts/dr.AnaliseJuridica.WB_AnaliseJuridica_Associacoes.mvc.js",
    f"{BASE}/scripts/dr.Legislacao_Conteudos.Conteudo_Det_Diario.mvc.js",
    f"{BASE}/scripts/dr.Legislacao_Conteudos.Conteudo_Detalhe.mvc.js",
    f"{BASE}/scripts/dr.LegislacaoConsolidada.LegCons_Detalhe.mvc.js",
    f"{BASE}/scripts/dr.LegislacaoConsolidada.AlteracoesTimelineByDiplomaLegisId.mvc.js",
)

AJ_ASSOCIATIONS = "aj_associations"
AJ_ELEMENT_TYPE = "aj_element_type"
AJ_DATA = "aj_data"
DOCUMENTS_BY_DATE = "documents_by_date"
PUBLISHED_DETAIL = "published_detail"
CONS_HEADER = "cons_header"
CONS_SNAPSHOT = "cons_snapshot"
CONS_TIMELINE = "cons_timeline"

_VIEW_AJ = "AnaliseJuridica.AnaliseJuridica"
_VIEW_HOME = "Home.home"
_VIEW_PUBLISHED = "Legislacao_Conteudos.Conteudo_Detalhe"
_VIEW_CONSOLIDATED = "LegislacaoConsolidada.LegCons_Detalhe"

# logical name -> (action-name prefixes, viewName to post under)
_ACTIONS: dict[str, tuple[tuple[str, ...], str]] = {
    AJ_ELEMENT_TYPE: (("DataActionGetElementTypeAndApplicationSettings",), _VIEW_AJ),
    AJ_DATA: (("DataActionGetData",), _VIEW_AJ),
    AJ_ASSOCIATIONS: (("DataActionFetchAssociacoes",), _VIEW_AJ),
    DOCUMENTS_BY_DATE: (("DataActionGetDataAndApplicationSettings",), _VIEW_HOME),
    PUBLISHED_DETAIL: (
        ("DataActionGetConteudoData", "DataActionGetAllConteudoDetalhe"),
        _VIEW_PUBLISHED,
    ),
    CONS_HEADER: (("DataActionGetDiplomaFragByIdAndApplicationSetting",), _VIEW_CONSOLIDATED),
    CONS_SNAPSHOT: (("DataActionGetData",), _VIEW_CONSOLIDATED),
    CONS_TIMELINE: (("DataActionGetConsolidacaoByDiplomaFrag",), _VIEW_CONSOLIDATED),
}

# Actions whose name is ambiguous across screens must be resolved against one file.
_SCREEN_OF: dict[str, str] = {
    # Every screen with a "get the data" action declares one under a name this
    # generic; resolving against the union would hand this one another screen's
    # apiVersion, which DRE answers with "No role validation found".
    DOCUMENTS_BY_DATE: f"{BASE}/scripts/dr.Home.WB_Serie1_List.mvc.js",
    CONS_SNAPSHOT: f"{BASE}/scripts/dr.LegislacaoConsolidada.LegCons_Detalhe.mvc.js",
    AJ_DATA: f"{BASE}/scripts/dr.AnaliseJuridica.AnaliseJuridica.mvc.js",
    AJ_ASSOCIATIONS: f"{BASE}/scripts/dr.AnaliseJuridica.WB_AnaliseJuridica_Associacoes.mvc.js",
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
        self._csrf_token = ""
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
                self._csrf_token = found.group(1)
                break
        if not self._csrf_token:
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

        bodies = {url: self._request("GET", url).text for url in _SCREEN_JS}
        combined = "\n".join(bodies.values())

        endpoints: dict[str, tuple[str, str, str]] = {}
        for logical, (prefixes, view) in _ACTIONS.items():
            # Two screens both declare a "DataActionGetData"; those resolve against
            # their own screen's JS, not the union, or one silently gets the other's
            # apiVersion and DRE answers "No role validation found".
            source = _SCREEN_OF.get(logical)
            js_text = bodies[source] if source in bodies else combined
            url, api_version = self._resolve_endpoint(
                logical, js_text, source or "the DRE screen JS", prefixes
            )
            endpoints[logical] = (url, api_version, view)
        self._endpoints = endpoints
        logger.info(
            "DRE session ready: %d actions, module %s", len(self._endpoints), self._module_version
        )

    def _resolve_endpoint(
        self, name: str, js_text: str, js_url: str, prefixes: tuple[str, ...]
    ) -> tuple[str, str]:
        """Find one screen action's URL and apiVersion inside the screen JS.

        Matching on a prefix absorbs the suffixes DRE adds across deploys
        (``DataActionGetDRByDataCalendario`` became
        ``…AndCheckUserLog`` in May 2026). A wholesale rename raises, listing every
        action the JS *does* declare, so adding the new prefix is a one-line change.
        """
        actions = {
            m.group(1): (m.group(2), m.group(3)) for m in _CALL_DATA_ACTION.finditer(js_text)
        }
        for prefix in prefixes:
            for action_name, (path, api_version) in actions.items():
                if action_name.startswith(prefix):
                    return f"{BASE}/{path.lstrip('/')}", api_version
        raise DREApiError(
            f"No action matching {prefixes} in {js_url} ({len(js_text)} bytes, "
            f"{len(actions)} actions found: {sorted(actions)}). DRE renamed the "
            f"action — add the new prefix to _ACTIONS[{name!r}] and update "
            f"docs/pt-dre-api.md."
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
        response = self._request("POST", url, json=body, headers={"X-CSRFToken": self._csrf_token})
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

    def documents_by_date(self, iso_date: str) -> list[dict]:
        """Every Série I document published on one date, across that day's issues.

        This used to be two calls — the day's issues, then each issue's contents
        off ``Legislacao_Conteudos.Conteudo_Det_Diario``. On 2026-08-25 that screen
        stopped answering (``No role validation found``, DRE's way of saying the
        action no longer belongs to the view it is posted under) and the site began
        reading the same list from a block on the home screen, which takes the date
        and nests the documents inside each issue. One call, and the day's issues
        no longer have to be enumerated first.
        """
        data = self.call(DOCUMENTS_BY_DATE, {"DataSelecionada": iso_date})
        issues = (data.get("DiarioByDiaList") or {}).get("List")
        if issues is None:
            # An empty list is a legitimate answer (Sundays, holidays); a missing
            # one means the shape moved again and the day would look quiet.
            raise DREApiError(
                f"{DOCUMENTS_BY_DATE} for {iso_date} returned no DiarioByDiaList — "
                f"keys: {sorted(data)}. DRE changed the response shape."
            )
        documents: list[dict] = []
        for issue in issues:
            documents.extend(((issue.get("DiplomaLegiList") or {}).get("List")) or [])
        return documents

    def _aj_vars(tipo: str, key: str, associacao: str = "informacoes-gerais") -> dict:
        """The AnaliseJuridica screen state.

        The SPA splits the key ``47344-1966-477358`` into Numero/Year/ConteudoId
        client-side *before* the first data action fires. Post Tipo/Key alone and DRE
        answers ``IsNullElementType: true`` with every id 0 — a silent empty result.
        """
        parts = key.rsplit("-", 2)
        numero, ano, conteudo_id = (parts + ["", "", ""])[:3] if len(parts) == 3 else ("", "", key)
        return {
            "Associacao": associacao,
            "_associacaoInDataFetchStatus": 1,
            "Tipo": tipo,
            "_tipoInDataFetchStatus": 1,
            "Key": key,
            "_keyInDataFetchStatus": 1,
            "ConteudoId": conteudo_id,
            "Numero": numero,
            "Year": int(ano) if ano.isdigit() else 0,
            "TipoAssociacaoIdAux": "0",
            "HasAssociacoesEcra": True,
            "DiplomaFragId": "0",
            "IsRended": True,
            "DiplomaLegisId": "0",
            "DiplomaDGOId": "0",
            "DiplomaRegTrabId": "0",
            "DiplomaLegacorId": "0",
            "DiplomaDGAPId": "0",
            "TipoAssociacaoId": "0",
            "AssociacaoAnaliseJuridicaId": "0",
            "IsWordExport": False,
            "IsExcelExport": False,
            "TipoExportacao": "",
            "CountEcra": 0,
            "HasJurisprudenciaAssociadaVar": False,
            "IsDiretaChecked": True,
            "IsInversaChecked": True,
            "AssociacoesCounter": 0,
            "IsPageTracked": True,
            "IsShowConteudoRelacionado": True,
            "Print": False,
            "TotalAssociacoes": 0,
            "HasAssociacoesFetched": False,
        }

    # DRE's own relation table. Every field the widget renders is echoed back, so
    # the request is mostly empty scaffolding; the parts that matter are
    # TipoAssociacaoId (162 = modificações, 165 = retificações) and ConteudoId.
    _ASSOC_INVERSA_EMPTY = {
        "Data": "",
        "Texto": "",
        "Sumario": "",
        "Diploma": "",
        "TipoDiploma": "",
        "NumeroAJ": "",
        "NumeroDiploma": "",
        "LinkSitemapAnaliseJuridica": "",
        "DiplomaLegisId": "0",
        "DiplomaDGOId": "0",
        "DiplomaRegTrabId": "0",
        "DiplomaLegacorId": "0",
        "DiplomaDGAPId": "0",
        "ActoSocietarioId": "0",
        "AcordaoSTADiplomaId": "0",
        "ContratoPublicoId": "0",
    }
    _ASSOC_DIRETA_EMPTY = {
        "Data": "1900-01-01",
        "Texto": "",
        "AssociacaoAnaliseJuridicaId": "0",
        "HasLink": False,
        "HasInversa": False,
        "DiplomaLinkId": "0",
        "Numero": "",
        "Tipo": "",
    }

    def associations(self, ref: str, association_id: str = "162", limit: int = 1000) -> dict:
        """One row per diploma related to this one, as DRE itself records it.

        ``InversasList`` is what changed this law and ``DiretasList`` what this law
        changed, both dated, both naming the other diploma, and both carrying a
        ``Texto`` that says which articles moved — "Alterados os arts. 5º, 9º, 14º…".
        That is the only place DRE publishes the relation as data rather than as
        prose inside the amending act, and unlike ``eli:amended_by`` it is not
        almost entirely rectifications.
        """
        tipo, key = split_sitemap_ref(ref)
        # The DRE content id is the last segment whatever the shape: "16-1994-512030"
        # for a numbered diploma, "216-2024-1-1154275224" when the number carries a
        # third component, and "1984-264280" for the thousands of numberless ones —
        # which have no year-and-number pair to unpack and were raising here.
        content_id = key.rsplit("-", 1)[-1]
        return self.call(
            AJ_ASSOCIATIONS,
            {
                "MaxRecordsInversas": limit,
                "MaxRecordsDiretas": limit,
                "TableValuesInversas": {
                    "List": [],
                    "EmptyListItem": {"Data": "", "Diploma": "", "Link": "", "Texto": ""},
                },
                "TableValuesDiretas": {
                    "List": [],
                    "EmptyListItem": {"Data": "", "Diploma": "", "Texto": ""},
                },
                "StartIndex": 0,
                "IsListaCompleta": True,
                "StartIndexInversas": 0,
                "InversasAuxList": {"List": [], "EmptyListItem": self._ASSOC_INVERSA_EMPTY},
                "DiretasAuxList": {"List": [], "EmptyListItem": self._ASSOC_DIRETA_EMPTY},
                "IsWordExportAux": False,
                "IsExcelExportAux": False,
                "IsRendered": True,
                "IsDone": False,
                "ListaCompletaDiretas": False,
                "ListaCompletaInversas": False,
                "TipoAssociacaoId": str(association_id),
                "_tipoAssociacaoIdInDataFetchStatus": 1,
                "ConteudoId": content_id,
                "_conteudoIdInDataFetchStatus": 1,
                "IsFrom": "AJ",
                "_isFromInDataFetchStatus": 1,
                "IsWordExport": False,
                "_isWordExportInDataFetchStatus": 1,
                "TipoExportacao": "",
                "_tipoExportacaoInDataFetchStatus": 1,
                "Titulo": "",
                "_tituloInDataFetchStatus": 1,
                "IsExcelExport": False,
                "_isExcelExportInDataFetchStatus": 1,
                "Tipo": "modificacoes",
                "_tipoInDataFetchStatus": 1,
                "Key": key,
                "_keyInDataFetchStatus": 1,
                "IsPrint": False,
                "_isPrintInDataFetchStatus": 1,
                "DataPublicacao": "1900-01-01",
                "_dataPublicacaoInDataFetchStatus": 1,
            },
        )

    def descriptors(self, ref: str) -> dict[str, str]:
        """``{"30215271": "Código Civil", …}`` for one diploma.

        The keys are the same integers ``eli:is_about`` points at
        (``…/authority/legal-subject/{id}``), which do not dereference anywhere else.
        This is the only surface that publishes their labels.
        """
        tipo, key = split_sitemap_ref(ref)
        variables = self._aj_vars(tipo, key)
        element_type = self.call(AJ_ELEMENT_TYPE, variables)
        if element_type.get("IsNullElementType"):
            raise DREApiError(
                f"analise-juridica did not resolve {ref} — it answers with a silent "
                f"empty record rather than an error."
            )
        variables["GetElementTypeAndApplicationSettings"] = element_type
        variables["DiplomaLegisId"] = element_type.get("DiplomaLegisIdOut", "0")
        data = self.call(AJ_DATA, variables)
        entries = (data.get("ThesaurusTreeList") or {}).get("List") or []
        return {
            str(entry.get("ThesaurusElementId")): (entry.get("ThesaurusElementName") or "").strip()
            for entry in entries
            if entry.get("ThesaurusElementId") and entry.get("ThesaurusElementName")
        }

    # ---------------------------------------------------------------- helpers

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
