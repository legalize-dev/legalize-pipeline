"""Portugal DRE (Diario da Republica Eletronico) clients.

Two client implementations:
1. DREClient (SQLite) — reads from dre.tretas.org weekly dump. For bootstrap.
2. DREHttpClient (HTTP) — fetches directly from diariodarepublica.pt. For daily.

The HTTP client accesses the OutSystems API endpoints of diariodarepublica.pt,
the official Portuguese legislation portal. Protocol details learned from the
dre.tretas.org open source project (GPLv3, https://gitlab.com/hgg/dre).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path

from legalize.fetcher.base import HttpClient, LegislativeClient

logger = logging.getLogger(__name__)

# ─── OutSystems API endpoints (diariodarepublica.pt) ───

_BASE = "https://diariodarepublica.pt/dr"
_MODULE_VERSION_URL = f"{_BASE}/moduleservices/moduleversioninfo"
_OUTSYSTEMS_JS_URL = f"{_BASE}/scripts/OutSystems.js"
# ─── Screen actions (discovered at runtime) ───
#
# The OutSystems endpoints live under screenservices/ and each one needs a
# per-action ``apiVersion`` hash that changes on every DRE deploy.  Both the
# URL path and the hash are published in the screen's MVC JavaScript as
# ``callDataAction("ActionName", "screenservices/...", "apiVersionHash", ...)``
# so we read them from there instead of hardcoding them.
#
# DRE also *renames* actions across deploys — the May 2026 redeploy turned
# ``DataActionGetDRByDataCalendario`` into
# ``DataActionGetDRByDataCalendarioAndCheckUserLog`` and replaced
# ``DataActionGetConteudoDataAndApplicationSettings`` with
# ``DataActionGetAllConteudoDetalheData`` — so each endpoint matches a list of
# known action-name prefixes rather than one exact name.  A suffix added to an
# existing name keeps working; a wholesale rename needs a new prefix here and
# raises DREApiError until it gets one, instead of silently finding nothing.
JOURNALS_BY_DATE = "journals_by_date"
DOCUMENTS_BY_JOURNAL = "documents_by_journal"
DOCUMENT_DETAIL = "document_detail"

_SCREEN_ENDPOINTS: dict[str, tuple[str, tuple[str, ...]]] = {
    JOURNALS_BY_DATE: (
        f"{_BASE}/scripts/dr.Home.home.mvc.js",
        ("DataActionGetDRByDataCalendario",),
    ),
    DOCUMENTS_BY_JOURNAL: (
        f"{_BASE}/scripts/dr.Legislacao_Conteudos.Conteudo_Det_Diario.mvc.js",
        ("DataActionGetDadosAndApplicationSettings",),
    ),
    DOCUMENT_DETAIL: (
        f"{_BASE}/scripts/dr.Legislacao_Conteudos.Conteudo_Detalhe.mvc.js",
        ("DataActionGetConteudoData", "DataActionGetAllConteudoDetalhe"),
    ),
}

# Document sitemap path: /dr/detalhe/{tipo}/{key}
_SITEMAP_REF_RE = re.compile(r"/dr/detalhe/([^/]+)/([^/?#]+)")

# callDataAction("ActionName", "screenservices/...", "apiVersionHash", ...)
_CALL_DATA_ACTION_RE = re.compile(
    r'callDataAction\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"'
)


class DREApiError(RuntimeError):
    """The DRE OutSystems API broke its contract.

    Raised instead of degrading to an empty result, so a DRE redeploy fails
    the daily run in red rather than recording a silent "no new norms" day
    and advancing the state past legislation we never saw.
    """


def _split_sitemap_ref(ref: str) -> tuple[str, str]:
    """Split a DRE sitemap path into the detail screen's (Tipo, Key) inputs.

    ``/dr/detalhe/decreto-lei/169-2026-1159106557`` → ``("decreto-lei",
    "169-2026-1159106557")``.  Accepts a full URL as well as a bare path.
    """
    match = _SITEMAP_REF_RE.search(ref or "")
    if not match:
        raise DREApiError(
            f"Cannot read a document reference out of {ref!r}. Expected a DRE "
            f"sitemap path like /dr/detalhe/decreto-lei/169-2026-1159106557."
        )
    return match.group(1), match.group(2)


def _nested_get(d: dict, *keys: str, default: str = "") -> str:
    """Safely traverse nested dicts: _nested_get(d, 'a', 'b') → d['a']['b']."""
    current = d
    for k in keys:
        if isinstance(current, dict):
            current = current.get(k, default)
        else:
            return default
    return str(current) if current != default else default


class DREHttpClient(HttpClient):
    """HTTP client for Portuguese legislation via diariodarepublica.pt.

    Uses the OutSystems internal API to fetch document lists and full text.
    Works without any local data — suitable for CI/daily updates.
    """

    @classmethod
    def create(cls, country_config):
        """Create DREHttpClient from CountryConfig."""
        source = country_config.source
        timeout = source.get("request_timeout", 30)
        return cls(timeout=timeout)

    def __init__(self, timeout: int = 30) -> None:
        super().__init__(
            request_timeout=timeout,
            requests_per_second=2.0,
            extra_headers={"Content-Type": "application/json; charset=UTF-8"},
        )
        self._csrf_token: str = ""
        self._module_version: str = ""
        # logical endpoint name → (absolute URL, apiVersion hash)
        self._endpoints: dict[str, tuple[str, str]] = {}
        self._request_count = 0
        self._init_session()

    def _init_session(self) -> None:
        """Initialize session: CSRF token, module version, and screen endpoints.

        Every piece here is a hard requirement: without a CSRF token or an
        apiVersion hash the OutSystems endpoints answer with an HTML error page
        instead of JSON.  Anything missing raises DREApiError rather than
        leaving the client half-configured to fail later as "no results".
        """
        # 1. Get CSRF token from OutSystems.js
        resp = self._request("GET", _OUTSYSTEMS_JS_URL)
        for pattern in [
            r'AnonymousCSRFToken\s*=\s*"([^"]+)"',  # Current format (2025+)
            r'"X-CSRFToken","([^"]+)"',  # Legacy format
            r'csrfTokenValue\s*=\s*"([^"]+)"',  # Older fallback
        ]:
            match = re.search(pattern, resp.text)
            if match:
                self._csrf_token = match.group(1)
                break
        if not self._csrf_token:
            raise DREApiError(
                f"No CSRF token found in {_OUTSYSTEMS_JS_URL} "
                f"({len(resp.text)} bytes) — DRE changed the token format."
            )
        logger.info("CSRF token obtained: %s...", self._csrf_token[:8])

        # 2. Get module version
        resp = self._request("GET", _MODULE_VERSION_URL)
        version_data = resp.json()
        if isinstance(version_data, dict):
            self._module_version = version_data.get("versionToken", "")
        elif isinstance(version_data, list) and version_data:
            self._module_version = version_data[0].get("versionToken", "")
        if not self._module_version:
            raise DREApiError(
                f"No versionToken in {_MODULE_VERSION_URL} response: {version_data!r:.200}"
            )
        logger.info("Module version: %s", self._module_version)

        # 3. Resolve each screen endpoint (URL + apiVersion) from its MVC JS.
        self._endpoints = {}
        js_cache: dict[str, str] = {}
        for name, (js_url, prefixes) in _SCREEN_ENDPOINTS.items():
            if js_url not in js_cache:
                js_cache[js_url] = self._request("GET", js_url).text
            self._endpoints[name] = self._resolve_endpoint(name, js_cache[js_url], js_url, prefixes)

    def _resolve_endpoint(
        self, name: str, js_text: str, js_url: str, prefixes: tuple[str, ...]
    ) -> tuple[str, str]:
        """Find the URL and apiVersion of one screen action inside its MVC JS."""
        actions = {
            m.group(1): (m.group(2), m.group(3)) for m in _CALL_DATA_ACTION_RE.finditer(js_text)
        }
        for prefix in prefixes:
            for action_name, (path, api_version) in actions.items():
                if action_name.startswith(prefix):
                    logger.info("Resolved %s → %s (apiVersion %s)", name, action_name, api_version)
                    return f"{_BASE}/{path.lstrip('/')}", api_version
        raise DREApiError(
            f"No action matching {prefixes} in {js_url} "
            f"({len(js_text)} bytes, {len(actions)} actions found: "
            f"{sorted(actions)}). DRE renamed the action — add the new prefix "
            f"to _SCREEN_ENDPOINTS[{name!r}]."
        )

    def _post(self, endpoint: str, payload: dict) -> dict:
        """POST JSON to a resolved OutSystems endpoint with CSRF + version info."""
        self._request_count += 1

        # Refresh session every 100 requests
        if self._request_count % 100 == 0:
            logger.info("Refreshing session after %d requests", self._request_count)
            self._init_session()

        url, api_version = self._endpoints[endpoint]

        payload.setdefault("versionInfo", {})
        payload["versionInfo"]["moduleVersion"] = self._module_version
        payload["versionInfo"]["apiVersion"] = api_version

        # Required since DRE OutSystems migration (2025)
        payload.setdefault("clientVariables", {})

        resp = self._request("POST", url, json=payload, headers={"X-CSRFToken": self._csrf_token})
        try:
            data = resp.json()
        except ValueError as exc:
            # A stale apiVersion/CSRF makes OutSystems answer with an HTML error
            # page.  Left alone this surfaces as JSONDecodeError deep in a
            # per-date try/except and the run still ends green.
            raise DREApiError(
                f"{endpoint} returned {resp.headers.get('Content-Type', '?')} "
                f"instead of JSON (HTTP {resp.status_code}): {resp.text[:200]!r}"
            ) from exc

        if not isinstance(data, dict):
            raise DREApiError(f"{endpoint} returned {type(data).__name__}, expected an object")

        if data.get("exception"):
            exc_info = data["exception"]
            raise DREApiError(
                f"{endpoint} raised a server exception: "
                f"{exc_info.get('name', '?')}/{exc_info.get('specificType', '?')} — "
                f"{exc_info.get('message', '?')}"
            )
        return data

    @staticmethod
    def _parse_json_out(data: dict, key: str = "Json_Out") -> dict:
        """Parse a Json_Out Elasticsearch response string from the API.

        Since the 2025 DRE migration, many endpoints return Elasticsearch
        results wrapped in a JSON string field instead of structured data.
        """
        raw = data.get(key, "")
        if isinstance(raw, str) and raw:
            return json.loads(raw)
        return {}

    def get_journals_by_date(self, date_str: str) -> list[dict]:
        """Get journal (Diario da Republica) entries for a date.

        Args:
            date_str: Date in YYYY-MM-DD format.

        Returns:
            List of journal dicts with series, number, date info.
        """
        payload = {
            "viewName": "Home.home",
            "screenData": {
                "variables": {
                    "DataCalendario": date_str,
                    "_dataCalendarioInDataFetchStatus": 1,
                    # Sentinel date required for Elasticsearch date filtering
                    "DataUltimaPublicacao": "2099-11-26",
                    "HasSerie1": True,
                    "HasSerie2": True,
                    "IsRendered": True,
                }
            },
            "clientVariables": {
                "Data": date_str,
            },
        }
        result = self._post(JOURNALS_BY_DATE, payload)
        data = result.get("data", {})

        # New format (2025+): Elasticsearch response in Json_Out.
        # An empty `hits` list is a legitimate answer (holidays, Sundays);
        # a response we cannot read at all is not — see below.
        es_data = self._parse_json_out(data)
        if es_data:
            journals = []
            for hit in es_data.get("hits", {}).get("hits", []):
                source = hit.get("_source", {})
                journals.append(
                    {
                        "Id": source.get("dbId"),
                        "DiarioId": source.get("dbId"),
                        "Numero": source.get("numero", ""),
                        "DataPublicacao": source.get("dataPublicacao", ""),
                        "conteudoTitle": source.get("conteudoTitle", ""),
                    }
                )
            return journals

        # Legacy format: structured SerieI.List
        serie1 = data.get("SerieI")
        if isinstance(serie1, dict):
            return serie1.get("List", [])
        if isinstance(serie1, list):
            return serie1

        raise DREApiError(
            f"{JOURNALS_BY_DATE} for {date_str} returned neither Json_Out nor "
            f"SerieI — keys: {sorted(data)}. DRE changed the response shape."
        )

    def get_documents_by_journal(self, journal_id: int, is_serie1: bool = True) -> list[dict]:
        """Get all documents from a journal issue.

        Args:
            journal_id: Internal journal ID.
            is_serie1: Whether this is Series I (main legislation).

        Returns:
            List of document dicts with metadata.
        """
        payload = {
            "viewName": "Legislacao_Conteudos.Conteudo_Detalhe",
            "screenData": {
                "variables": {
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
                    "IsSerieI": is_serie1,
                    "_isSerieIInDataFetchStatus": 1,
                    "Diario_DetalheConteudo": {
                        "Id": "",
                        "Titulo": "",
                        "DataPublicacao": "",
                    },
                    "_diario_DetalheConteudoInDataFetchStatus": 1,
                }
            },
            "clientVariables": {
                "Data": "",
                "DiplomaConteudoId": "",
            },
        }
        result = self._post(DOCUMENTS_BY_JOURNAL, payload)
        data = result.get("data", {})

        # Try structured response: DetalheConteudo.List (current format)
        for key in ("DetalheConteudo", "DetalheConteudo2"):
            container = data.get(key)
            if isinstance(container, dict) and container.get("List"):
                return container["List"]
            if isinstance(container, list) and container:
                return container

        # Elasticsearch response fallback
        es_data = self._parse_json_out(data)
        if es_data:
            return [hit.get("_source", {}) for hit in es_data.get("hits", {}).get("hits", [])]

        raise DREApiError(
            f"{DOCUMENTS_BY_JOURNAL} for journal {journal_id} returned no readable "
            f"document list — keys: {sorted(data)}. A journal issue always has "
            f"documents, so an unreadable response is a DRE change, not an empty day."
        )

    def get_document_detail(self, ref: str) -> dict:
        """Fetch full document detail including text.

        Args:
            ref: The document's sitemap path as published in the document
                list, e.g. ``/dr/detalhe/decreto-lei/169-2026-1159106557``.
                The detail screen is URL-driven: its inputs are the *type*
                and *key* segments of that path, not a raw id.

        Returns:
            Dict with document details including Texto/TextoFormatado.
            Field names follow the new DRE API (2025+):
            TipoDiploma, Emissor, ELI, Vigencia, etc.
        """
        tipo, key = _split_sitemap_ref(ref)
        payload = {
            "viewName": "Legislacao_Conteudos.Conteudo_Detalhe",
            "screenData": {
                "variables": {
                    "Tipo": tipo,
                    "_tipoInDataFetchStatus": 1,
                    "Key": key,
                    "_keyInDataFetchStatus": 1,
                    "ParteId": "0",
                    "_parteIdInDataFetchStatus": 1,
                },
            },
            "clientVariables": {
                "DiplomaConteudoId": "",
            },
        }
        result = self._post(DOCUMENT_DETAIL, payload)
        detail = result.get("data", {}).get("DetalheConteudo", {})

        # DRE answers an unrecognised input with a fully-populated *default*
        # record — Id 0, empty Numero, DataPublicacao 1900-01-01 — rather than
        # an error.  Left alone that becomes a committed law with no title,
        # no date and no text, so treat it as the API break it is.
        if not isinstance(detail, dict) or not (
            str(detail.get("Numero", "")).strip() or str(detail.get("ELI", "")).strip()
        ):
            raise DREApiError(
                f"{DOCUMENT_DETAIL} returned an empty record for {ref} "
                f"(Id={detail.get('Id') if isinstance(detail, dict) else detail!r}). "
                f"The screen's Tipo/Key inputs no longer resolve — see docs/pt-dre-api.md."
            )
        return detail

    def get_text(self, ref: str) -> bytes:
        """Fetch the full text of a document by its sitemap path.

        Returns HTML text as UTF-8 bytes, compatible with DRETextParser.
        """
        detail = self.get_document_detail(ref)
        text = detail.get("Texto", "").strip()
        if not text:
            text = detail.get("TextoFormatado", "").strip()
        if not text:
            raise ValueError(f"No text found for {ref}")
        return text.encode("utf-8")

    def get_metadata(self, ref: str) -> bytes:
        """Fetch metadata for a document by its sitemap path.

        Returns JSON bytes compatible with DREMetadataParser.
        Handles both legacy and new (2025+) field names from the API.
        """
        detail = self.get_document_detail(ref)

        # Vigencia: "NAO_VIGENTE" means repealed
        vigencia = detail.get("Vigencia", "")
        in_force = vigencia != "NAO_VIGENTE"

        # ELI URI (European Legislation Identifier) — preferred source URL
        eli = detail.get("ELI", "")

        # Map field names — new API (2025+) uses different names
        # New: TipoDiploma, Emissor, Id  |  Old: TipoActo, Entidade, ConteudoId
        doc_type = (
            (
                detail.get("TipoActo", "")
                or detail.get("TipoDiploma", "")
                or detail.get("TipoDiplomaExterno", "")
            )
            .strip()
            .upper()
        )

        emiting_body = (detail.get("Entidade", "") or detail.get("Emissor", "")).strip()

        dr_number = detail.get("DiarioNumero", "") or _nested_get(
            detail, "DiarioRepublica", "Numero", default=""
        )

        meta = {
            "claint": detail.get("ConteudoId", detail.get("Id", "")),
            "doc_type": doc_type,
            "number": detail.get("Numero", "").strip(),
            "emiting_body": emiting_body,
            "source": "Serie I",
            "date": detail.get("DataPublicacao", "")[:10],
            "notes": (detail.get("Sumario", "") or detail.get("Resumo", "")).strip(),
            "in_force": in_force,
            "series": 1,
            "dr_number": dr_number,
            "dre_pdf": detail.get("URL_PDF", ""),
            "dre_key": "",
            "eli": eli,
            "parte": detail.get("Parte", ""),
        }
        return json.dumps(meta, ensure_ascii=False).encode("utf-8")


# ─── SQLite client (for bootstrap) ───


class DREClient(LegislativeClient):
    """Client for Portuguese legislation via dre.tretas.org SQLite dump.

    The tretas.org project publishes weekly SQLite exports (~12 GB decompressed)
    containing all legislation from the Diario da Republica since 1911.

    Tables used:
    - dreapp_document: metadata (id, doc_type, number, date, etc.)
    - dreapp_documenttext: full HTML text (text field)
    """

    @classmethod
    def create(cls, country_config):
        """Create DREClient from CountryConfig.

        Expects config.yaml:
            pt:
              source:
                db_path: "/path/to/YYYY-MM-DD-DRE.sqlite3"
        """
        db_path = country_config.source.get("db_path", "")
        if not db_path:
            raise ValueError(
                "Portugal requires source.db_path in config.yaml "
                "pointing to the dre.tretas.org SQLite dump. "
                "Download from https://uploads.tretas.org/"
            )
        return cls(db_path=db_path)

    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        if not self._db_path.exists():
            raise FileNotFoundError(
                f"SQLite database not found: {self._db_path}. "
                "Download the tretas.org dump and decompress it."
            )
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        logger.info("Opened DRE SQLite database: %s", self._db_path)

    def get_text(self, norm_id: str) -> bytes:
        """Fetch the HTML text for a document by its ID.

        Returns the raw HTML from dreapp_documenttext as UTF-8 bytes.
        """
        cursor = self._conn.execute(
            """
            SELECT dt.text
            FROM dreapp_documenttext dt
            WHERE dt.document_id = ?
            ORDER BY dt.id DESC
            LIMIT 1
            """,
            (int(norm_id),),
        )
        row = cursor.fetchone()
        if not row or not row["text"]:
            raise ValueError(f"No text found for id={norm_id}")
        return row["text"].encode("utf-8")

    def get_metadata(self, norm_id: str) -> bytes:
        """Fetch metadata for a document by its ID.

        Returns a JSON dict with Document fields as UTF-8 bytes.
        """
        cursor = self._conn.execute(
            """
            SELECT id, doc_type, number, emiting_body, source, date,
                   notes, in_force, series, dr_number, dre_pdf
            FROM dreapp_document
            WHERE id = ?
            """,
            (int(norm_id),),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"No document found for id={norm_id}")

        data = dict(row)
        # Alias 'id' as 'claint' for parser compatibility
        data["claint"] = data["id"]
        return json.dumps(data, ensure_ascii=False).encode("utf-8")

    def close(self) -> None:
        """Close the SQLite connection."""
        if self._conn:
            self._conn.close()
            logger.info("Closed DRE SQLite database")
