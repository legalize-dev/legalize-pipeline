"""Normattiva HTTP client (Italy).

Two interfaces are used:

1. OpenData API (api.normattiva.it) for discovery/search:
   - POST /ricerca/semplice       (full-text search, paginated)
   - POST /ricerca/aggiornati     (acts updated between two dates)
   - GET  /tipologiche/denominazione-atto  (act type codes)

2. normattiva.it caricaAKN endpoint for full Akoma Ntoso XML:
   - GET /uri-res/N2Ls?{urn}      (HTML page, to extract caricaAKN link)
   - GET /do/atto/caricaAKN?...   (full Akoma Ntoso XML download)

No authentication required. No documented rate limits.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

OPENDATA_API_BASE = "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1"
NORMATTIVA_BASE = "https://www.normattiva.it"


class NormattivaClient(HttpClient):
    """HTTP client for Italian legislation via Normattiva.

    Uses the OpenData API for search/discovery and the caricaAKN endpoint
    for downloading the full consolidated text as Akoma Ntoso XML.
    """

    @classmethod
    def create(cls, country_config: CountryConfig) -> NormattivaClient:
        source = country_config.source or {}
        return cls(
            opendata_api_base=source.get("opendata_api_base", OPENDATA_API_BASE),
            normattiva_base=source.get("normattiva_base", NORMATTIVA_BASE),
            request_timeout=source.get("request_timeout", 30),
            max_retries=source.get("max_retries", 5),
            requests_per_second=source.get("requests_per_second", 2.0),
        )

    def __init__(
        self,
        *,
        opendata_api_base: str = OPENDATA_API_BASE,
        normattiva_base: str = NORMATTIVA_BASE,
        request_timeout: int = 30,
        max_retries: int = 5,
        requests_per_second: float = 2.0,
    ) -> None:
        super().__init__(
            base_url=normattiva_base,
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
            extra_headers={
                "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
            },
        )
        self._opendata_api_base = opendata_api_base.rstrip("/")

    # -- OpenData API (search/discovery) --

    def search(
        self,
        text: str = "*",
        page: int = 1,
        page_size: int = 100,
        **kwargs: Any,
    ) -> dict:
        """Search acts via the OpenData simple search endpoint.

        Returns the full JSON response with listaAtti, numeroPagine, etc.
        """
        payload: dict[str, Any] = {
            "testoRicerca": text,
            "paginazione": {
                "paginaCorrente": page,
                "numeroElementiPerPagina": page_size,
            },
        }
        if kwargs.get("limit_years"):
            payload["limitaAnniVigenza"] = True
        resp = self._request(
            "POST",
            f"{self._opendata_api_base}/api/v1/ricerca/semplice",
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        return resp.json()

    def search_updated(self, date_from: str, date_to: str) -> dict:
        """Find acts updated between two dates (ISO format YYYY-MM-DD)."""
        payload = {
            "dataInizioAggiornamento": date_from,
            "dataFineAggiornamento": date_to,
        }
        resp = self._request(
            "POST",
            f"{self._opendata_api_base}/api/v1/ricerca/aggiornati",
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        return resp.json()

    # -- Full text download (Akoma Ntoso XML) --

    def get_text(self, norm_id: str) -> bytes:
        """Fetch the full Akoma Ntoso XML for a law.

        norm_id can be ``codiceRedaz:dataGU`` or just ``codiceRedaz``.
        Uses multiple strategies to download the AKN XML.
        """
        return self._download_akn(norm_id)

    def get_metadata(self, norm_id: str) -> bytes:
        """Metadata is embedded in the same AKN XML as the text."""
        return self.get_text(norm_id)

    def get_act_detail(self, data_gu: str, codice_redaz: str) -> dict:
        """Fetch act detail from the OpenData API (single article view).

        Useful for metadata extraction when AKN download fails.
        """
        payload = {
            "dataGU": data_gu,
            "codiceRedazionale": codice_redaz,
        }
        resp = self._request(
            "POST",
            f"{self._opendata_api_base}/api/v1/atto/dettaglio-atto",
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        return resp.json()

    def _download_akn(self, norm_id: str) -> bytes:
        """Download Akoma Ntoso XML via the caricaAKN endpoint.

        norm_id can be:
        - ``codiceRedaz:dataGU:urn`` (from discovery, preferred)
        - ``codiceRedaz:dataGU`` (legacy format)
        - just ``codiceRedaz`` (requires search API to resolve)

        The normattiva.it site requires visiting the act page via
        ``/uri-res/N2Ls?{urn}`` first to establish per-act session state,
        then the caricaAKN link extracted from that page returns the full
        AKN XML.
        """
        # Parse composite norm_id
        parts = norm_id.split(":", 2)
        codice_redaz = parts[0]
        data_gu = parts[1] if len(parts) > 1 else ""
        urn = parts[2] if len(parts) > 2 else ""

        # If no URN, try to resolve via search API
        if not urn and not data_gu:
            try:
                search_result = self.search(codice_redaz, page_size=5)
                for act in search_result.get("listaAtti", []):
                    if act and act.get("codiceRedazionale") == codice_redaz:
                        data_gu = act.get("dataGU", "")
                        from legalize.fetcher.it.discovery import _build_urn

                        urn = _build_urn(act) or ""
                        break
            except Exception:
                logger.debug("Search API unavailable for %s", codice_redaz)

        # Strategy 1 (preferred): visit N2Ls URN page, extract caricaAKN, download
        if urn:
            try:
                return self._download_via_urn(urn)
            except Exception:
                logger.debug("URN-based download failed for %s", codice_redaz)

        # Strategy 2: construct caricaAKN URL directly (needs prior N2Ls visit)
        # This won't work without a URN visit, but try anyway as fallback
        if data_gu:
            try:
                return self._download_via_scrape(codice_redaz, data_gu)
            except Exception:
                logger.debug("Scrape-based download failed for %s", codice_redaz)

        raise ValueError(
            f"Unable to download AKN for {norm_id}: "
            f"no URN available and search API is unreachable. "
            f"Use the format codiceRedaz:dataGU:urn for direct access."
        )

    def _download_via_urn(self, urn: str) -> bytes:
        """Visit the URN page and download caricaAKN XML."""
        html_bytes = self._get(f"{self._base_url}/uri-res/N2Ls?{urn}")
        html_str = html_bytes.decode("utf-8", errors="replace")

        match = re.search(r'href="([^"]*caricaAKN[^"]*)"', html_str, re.I)
        if not match:
            raise ValueError(f"No caricaAKN link on URN page for {urn}")

        akn_path = match.group(1).replace("&amp;", "&")
        if akn_path.startswith("/"):
            akn_url = f"{self._base_url}{akn_path}"
        else:
            akn_url = akn_path

        xml_bytes = self._get(akn_url)
        if not xml_bytes.startswith(b"<?xml"):
            raise ValueError(f"caricaAKN for {urn} returned non-XML")

        return xml_bytes

    def _download_via_scrape(self, codice_redaz: str, data_gu: str) -> bytes:
        """Visit the act detail page via dataPubblicazioneGazzetta URL,
        extract the caricaAKN link, and download XML.
        """
        # Visit the multi-article view page which has the caricaAKN link
        page_url = (
            f"{self._base_url}/atto/vediMenuExport?"
            f"atto.dataPubblicazioneGazzetta={data_gu}"
            f"&atto.codiceRedazionale={codice_redaz}"
        )
        html_bytes = self._get(page_url)
        html_str = html_bytes.decode("utf-8", errors="replace")

        match = re.search(r'href="([^"]*caricaAKN[^"]*)"', html_str, re.I)
        if match:
            akn_path = match.group(1).replace("&amp;", "&")
            if akn_path.startswith("/"):
                akn_url = f"{self._base_url}{akn_path}"
            else:
                akn_url = akn_path

            xml_bytes = self._get(akn_url)
            if xml_bytes.startswith(b"<?xml"):
                return xml_bytes

        raise ValueError(f"Scrape-based download failed for {codice_redaz}")
