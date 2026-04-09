"""Normattiva Open Data API client for Italian legislation.

Production API: https://api.normattiva.it/t/normattiva.api
Documentation: https://dati.normattiva.it/assets/come_fare_per/API_Normattiva_OpenData.pdf

The API returns one article at a time via URN. Text + metadata come from
the same endpoint (dettaglio-atto-urn), so get_metadata returns the same
data as get_text.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.normattiva.it/t/normattiva.api"
_BFF_PREFIX = "/bff-opendata/v1/api/v1"


class NormattivaClient(HttpClient):
    """HTTP client for Italian legislation via Normattiva Open Data API.

    The API is public (no auth) and article-level: each URN request returns
    one article's HTML. The client fetches the web page TOC to discover all
    articles, then fetches each via the API.
    """

    def __init__(
        self,
        *,
        api_base: str = DEFAULT_API_BASE,
        web_base: str = "https://www.normattiva.it",
        request_timeout: int = 30,
        max_retries: int = 5,
        requests_per_second: float = 2.0,
    ) -> None:
        super().__init__(
            base_url=api_base,
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
            extra_headers={
                "Origin": "https://dati.normattiva.it",
                "Accept": "application/json",
            },
        )
        self._web_base = web_base.rstrip("/")

    @classmethod
    def create(cls, country_config: CountryConfig) -> NormattivaClient:
        source = country_config.source or {}
        return cls(
            api_base=source.get("api_base", DEFAULT_API_BASE),
            web_base=source.get("web_base", "https://www.normattiva.it"),
            request_timeout=source.get("request_timeout", 30),
            max_retries=source.get("max_retries", 5),
            requests_per_second=source.get("requests_per_second", 2.0),
        )

    # ── Core interface ──

    def get_text(self, norm_id: str) -> bytes:
        """Fetch full consolidated text for an act.

        norm_id is the codiceRedazionale (e.g., "090G0294").
        Returns a JSON blob containing metadata + all articles' HTML,
        assembled from multiple API calls.

        Strategy:
        1. Search for the act to get metadata + build URN
        2. Try fetching article 1 via URN API
        3. If URN fails (e.g., DPR acts), fall back to web scraping
        """
        # Search for the act to get metadata
        result = self.search_simple(text=norm_id, order="recente", page=1, per_page=1)
        acts = result.get("listaAtti", [])
        if not acts:
            raise ValueError(f"Act {norm_id} not found in search")

        act_meta = acts[0]
        urn = self._act_to_urn(act_meta)

        # Try URN API first
        if urn:
            api_resp = self._fetch_urn(urn)
            if api_resp and api_resp.get("data", {}).get("atto"):
                return json.dumps(api_resp, ensure_ascii=False).encode("utf-8")

        # Fallback: fetch from normattiva.it web page
        logger.info("URN API failed for %s, falling back to web scrape", norm_id)
        return self._fetch_via_web(norm_id, act_meta)

    def _fetch_via_web(self, norm_id: str, act_meta: dict) -> bytes:
        """Fetch act content by scraping the normattiva.it web page.

        Used as fallback when the URN API doesn't support the act type
        (e.g., DPR acts). The web page contains the same AKN HTML.
        """
        # Build the web URN for the act
        tipo_code = TIPO_TO_CODE.get(act_meta.get("denominazioneAtto", ""), "")
        urn_type = URN_TYPE_MAP.get(tipo_code, "")

        anno = int(act_meta.get("annoProvvedimento", 0))
        mese = int(act_meta.get("meseProvvedimento", 0) or 0)
        giorno = int(act_meta.get("giornoProvvedimento", 0) or 0)
        numero = act_meta.get("numeroProvvedimento", "")

        if urn_type and anno and mese and giorno and numero:
            web_urn = f"urn:nir:stato:{urn_type}:{anno:04d}-{mese:02d}-{giorno:02d};{numero}"
        else:
            raise ValueError(f"Cannot build web URN for {norm_id}")

        url = f"{self._web_base}/uri-res/N2Ls?{web_urn}!vig="
        page_html = self._get(url).decode("utf-8", errors="replace")

        # Extract bodyTesto from the page.
        # Use a simple greedy match — the bodyTesto div contains all
        # article content and is terminated by the next </div>.
        # Then look for the outermost closing tag.
        article_html = ""
        start = page_html.find('<div class="bodyTesto">')
        if start >= 0:
            # Find the matching closing </div> — count nesting
            depth = 0
            i = start
            while i < len(page_html):
                if page_html[i : i + 4] == "<div":
                    depth += 1
                elif page_html[i : i + 6] == "</div>":
                    depth -= 1
                    if depth == 0:
                        article_html = page_html[start : i + 6]
                        break
                i += 1

            # Convert relative links to absolute
            if article_html:
                article_html = article_html.replace(
                    'href="/uri-res/', f'href="{self._web_base}/uri-res/'
                )

        # Extract metadata from search result
        data_gu = act_meta.get("dataGU", "")
        anno_gu = int(act_meta.get("annoDataGU", 0) or 0)
        mese_gu = 0
        giorno_gu = 0
        if data_gu and len(data_gu) >= 10:
            parts = data_gu.split("-")
            if len(parts) == 3:
                anno_gu = int(parts[0])
                mese_gu = int(parts[1])
                giorno_gu = int(parts[2])

        # Build response in the same format as the URN API
        atto = {
            "titolo": act_meta.get("descrizioneAtto", ""),
            "sottoTitolo": act_meta.get("titoloAtto", ""),
            "articoloHtml": article_html,
            "tipoProvvedimentoDescrizione": act_meta.get("denominazioneAtto", ""),
            "tipoProvvedimentoCodice": tipo_code,
            "annoProvvedimento": anno,
            "meseProvvedimento": mese,
            "giornoProvvedimento": giorno,
            "numeroProvvedimento": int(numero) if str(numero).isdigit() else 0,
            "tipoSupplementoCode": act_meta.get("tipoSupplemento", "NO"),
            "numeroSupplemento": int(act_meta.get("numeroSupplemento", 0) or 0),
            "annoGU": anno_gu,
            "meseGU": mese_gu,
            "giornoGU": giorno_gu,
            "numeroGU": int(act_meta.get("numeroGU", 0) or 0),
            "articoloDataInizioVigenza": "",
            "articoloDataFineVigenza": "99999999",
            "testoInVigore": None,
        }

        resp = {
            "code": None,
            "message": None,
            "data": {"atto": atto, "lista": None, "message": "web scrape"},
            "success": True,
        }
        return json.dumps(resp, ensure_ascii=False).encode("utf-8")

    def get_metadata(self, norm_id: str) -> bytes:
        """Fetch metadata for an act. Same data source as get_text."""
        return self.get_text(norm_id)

    # ── Version walking (reform history) ──

    def walk_article_versions(self, urn_base: str, art_num: str) -> list[dict]:
        """Walk all temporal versions of a single article.

        Uses @originale for the first version, then iterates using
        !vig=<day after articoloDataFineVigenza> until we reach the
        current version (fineVigenza=99999999).

        Returns a list of version dicts with html, vigenza dates, etc.
        """
        from datetime import date as date_cls, timedelta

        versions: list[dict] = []
        urn = f"{urn_base}~art{art_num}@originale"

        resp = self._fetch_urn(urn)
        if not resp or not resp.get("data", {}).get("atto"):
            # Try without @originale (some acts don't support it)
            urn = f"{urn_base}~art{art_num}"
            resp = self._fetch_urn(urn)
            if not resp or not resp.get("data", {}).get("atto"):
                return versions

        atto = resp["data"]["atto"]
        versions.append(
            {
                "article_num": art_num,
                "html": atto.get("articoloHtml", ""),
                "vigenza_inizio": atto.get("articoloDataInizioVigenza", ""),
                "vigenza_fine": atto.get("articoloDataFineVigenza", ""),
            }
        )

        # Walk forward
        max_versions = 50  # safety limit
        while len(versions) < max_versions:
            fine = versions[-1]["vigenza_fine"]
            if not fine or fine == "99999999" or len(fine) != 8:
                break

            try:
                d = date_cls(int(fine[:4]), int(fine[4:6]), int(fine[6:8]))
                next_day = (d + timedelta(days=1)).strftime("%Y-%m-%d")
            except ValueError:
                break

            urn = f"{urn_base}~art{art_num}!vig={next_day}"
            resp = self._fetch_urn(urn)
            if not resp or not resp.get("data", {}).get("atto"):
                break

            atto = resp["data"]["atto"]
            html = atto.get("articoloHtml", "")
            if not html:
                break

            versions.append(
                {
                    "article_num": art_num,
                    "html": html,
                    "vigenza_inizio": atto.get("articoloDataInizioVigenza", ""),
                    "vigenza_fine": atto.get("articoloDataFineVigenza", ""),
                }
            )

        return versions

    # ── Search / discovery helpers ──

    def search_simple(
        self,
        text: str = "*",
        order: str = "vecchio",
        page: int = 1,
        per_page: int = 100,
        filters: dict[str, Any] | None = None,
    ) -> dict:
        """Ricerca semplice — paginated search with optional facet filters."""
        body: dict[str, Any] = {
            "testoRicerca": text,
            "orderType": order,
            "paginazione": {
                "paginaCorrente": page,
                "numeroElementiPerPagina": per_page,
            },
        }
        if filters:
            body["filtriMap"] = filters
        url = f"{self._base_url}{_BFF_PREFIX}/ricerca/semplice"
        raw = self._request("POST", url, json=body).content
        return json.loads(raw)

    def search_updated(self, date_from: str, date_to: str) -> dict:
        """Ricerca atti aggiornati — acts modified between two ISO timestamps."""
        body = {
            "dataInizioAggiornamento": date_from,
            "dataFineAggiornamento": date_to,
        }
        url = f"{self._base_url}{_BFF_PREFIX}/ricerca/aggiornati"
        raw = self._request("POST", url, json=body).content
        return json.loads(raw)

    # ── Internal helpers ──

    def _fetch_urn(self, urn: str) -> dict | None:
        """POST to dettaglio-atto-urn and return parsed JSON."""
        url = f"{self._base_url}{_BFF_PREFIX}/atto/dettaglio-atto-urn"
        try:
            raw = self._request("POST", url, json={"urn": urn}).content
            data = json.loads(raw)
            if data.get("code") and data["code"] != "null":
                logger.debug("URN %s returned code %s: %s", urn, data["code"], data.get("message"))
                return None
            return data
        except Exception:
            logger.warning("Failed to fetch URN %s", urn, exc_info=True)
            return None

    def _build_urn_base(self, atto: dict) -> str | None:
        """Build the base URN (without article) from atto metadata."""
        tipo_code = atto.get("tipoProvvedimentoCodice", "")
        urn_type = URN_TYPE_MAP.get(tipo_code)
        if not urn_type:
            logger.warning("Unknown act type code: %s", tipo_code)
            return None

        anno = atto.get("annoProvvedimento", 0)
        mese = atto.get("meseProvvedimento", 0)
        giorno = atto.get("giornoProvvedimento", 0)
        numero = atto.get("numeroProvvedimento", 0)

        if not anno or not numero:
            return None

        if mese and giorno:
            date_str = f"{anno:04d}-{mese:02d}-{giorno:02d}"
        else:
            # Some acts (like the Constitution) have 0 for month/day
            # Use GU date instead
            anno_gu = atto.get("annoGU", 0)
            mese_gu = atto.get("meseGU", 0)
            giorno_gu = atto.get("giornoGU", 0)
            if anno_gu and mese_gu and giorno_gu:
                date_str = f"{anno_gu:04d}-{mese_gu:02d}-{giorno_gu:02d}"
            else:
                return None

        return f"urn:nir:stato:{urn_type}:{date_str};{numero}"

    def _act_to_urn(self, act: dict) -> str | None:
        """Build URN from a search result act dict."""
        tipo_desc = act.get("denominazioneAtto", "")
        code = TIPO_TO_CODE.get(tipo_desc)
        if not code:
            logger.warning("Cannot build URN for act type: %s", tipo_desc)
            return None

        urn_type = URN_TYPE_MAP.get(code)
        if not urn_type:
            return None

        # Special case: Constitution has fixed URN
        if code == "COS":
            return "urn:nir:stato:costituzione:1947-12-27;1"

        anno = int(act.get("annoProvvedimento", 0) or 0)
        mese = int(act.get("meseProvvedimento", 0) or 0)
        giorno = int(act.get("giornoProvvedimento", 0) or 0)
        numero = act.get("numeroProvvedimento", "")

        if not anno or not numero:
            return None

        numero = int(numero) if isinstance(numero, str) and numero.isdigit() else numero

        if mese and giorno:
            date_str = f"{anno:04d}-{mese:02d}-{giorno:02d}"
        else:
            # Try GU date
            data_gu = act.get("dataGU", "")
            if data_gu and len(data_gu) >= 10:
                date_str = data_gu[:10]
            else:
                return None

        return f"urn:nir:stato:{urn_type}:{date_str};{numero}"

    def _discover_articles(self, codice: str, atto: dict) -> list[str]:
        """Discover all article numbers for an act.

        Tries iterating sequential article numbers via the API,
        stopping when we get an error response.
        """
        urn_base = self._build_urn_base(atto)
        if not urn_base:
            return ["1"]

        articles = []
        # Iterate sequential articles: 1, 2, 3, ...
        # Stop after 3 consecutive misses to handle gaps
        consecutive_misses = 0
        max_articles = 1000  # safety limit
        art_num = 1

        while art_num <= max_articles and consecutive_misses < 3:
            urn = f"{urn_base}~art{art_num}"
            resp = self._fetch_urn(urn)
            if resp and resp.get("data", {}).get("atto"):
                articles.append(str(art_num))
                consecutive_misses = 0
            else:
                consecutive_misses += 1
            art_num += 1

        if not articles:
            articles = ["1"]

        return articles


# ── URN type mappings ──

URN_TYPE_MAP: dict[str, str] = {
    "COS": "costituzione",
    "PLC": "legge.costituzionale",
    "PLE": "legge",
    "PLL": "decreto.legislativo",
    "PDL": "decreto.legge",
    "PPR": "decreto.del.presidente.della.repubblica",
    "PCM_DPC": "decreto.del.presidente.del.consiglio.dei.ministri",
    "DCT": "decreto",
    "PDM": "decreto.ministeriale",
    "POR": "ordinanza",
    "DEL": "deliberazione",
    "D10": "regolamento",
    "PRD": "regio.decreto",
    "PRL": "regio.decreto.legge",
    "PLU": "decreto.luogotenenziale",
    "RDL": "regio.decreto.legislativo",
    "PLG": "decreto.legislativo.luogotenenziale",
    "DCS": "decreto.legislativo.del.capo.provvisorio.dello.stato",
    "PCS": "decreto.del.capo.provvisorio.dello.stato",
    "DLL": "decreto.legge.luogotenenziale",
    "PZP": "decreto.legislativo.presidenziale",
    "SNI": "decreto.reale",
    "DDD": "decreto.del.duce",
    "PCG": "decreto.del.capo.del.governo",
    "FAC": "decreto.del.duce.del.fascismo.capo.del.governo",
    "DPP": "decreto.presidenziale",
    "3NA": "decreto.del.capo.del.governo.primo.ministro.segretario.di.stato",
    "8ZL": "determinazione.intercommissariale",
    "GRC": "determinazione.del.commissario.per.le.finanze",
    "DPB": "determinazione.del.commissario.per.la.produzione.bellica",
}

# Reverse map: description → code
TIPO_TO_CODE: dict[str, str] = {
    "COSTITUZIONE": "COS",
    "LEGGE COSTITUZIONALE": "PLC",
    "LEGGE": "PLE",
    "DECRETO LEGISLATIVO": "PLL",
    "DECRETO-LEGGE": "PDL",
    "DECRETO DEL PRESIDENTE DELLA REPUBBLICA": "PPR",
    "DECRETO DEL PRESIDENTE DEL CONSIGLIO DEI MINISTRI": "PCM_DPC",
    "DECRETO": "DCT",
    "DECRETO MINISTERIALE": "PDM",
    "ORDINANZA": "POR",
    "DELIBERAZIONE": "DEL",
    "REGOLAMENTO": "D10",
    "REGIO DECRETO": "PRD",
    "REGIO DECRETO-LEGGE": "PRL",
    "DECRETO LUOGOTENENZIALE": "PLU",
    "REGIO DECRETO LEGISLATIVO": "RDL",
    "DECRETO LEGISLATIVO LUOGOTENENZIALE": "PLG",
    "DECRETO LEGISLATIVO DEL CAPO PROVVISORIO DELLO STATO": "DCS",
    "DECRETO DEL CAPO PROVVISORIO DELLO STATO": "PCS",
    "DECRETO-LEGGE LUOGOTENENZIALE": "DLL",
    "DECRETO LEGISLATIVO PRESIDENZIALE": "PZP",
    "DECRETO REALE": "SNI",
    "DECRETO DEL DUCE": "DDD",
    "DECRETO DEL CAPO DEL GOVERNO": "PCG",
    "DECRETO DEL DUCE DEL FASCISMO, CAPO DEL GOVERNO": "FAC",
    "DECRETO PRESIDENZIALE": "DPP",
}
