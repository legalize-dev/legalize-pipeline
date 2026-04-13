"""Normattiva HTTP client — Italy.

Two complementary access paths:

1. **Direct AKN download** (``caricaAKN``) — fast (~1s), requires visiting
   the law's HTML page first to extract ``dataGU``, ``codiceRedaz``, and
   ``dataVigenza`` parameters from hidden form fields. Supports multivigenza
   (historical versions) by varying the ``dataVigenza`` parameter.

2. **OpenData async API** (``dati.normattiva.it``) — slower (~30-60s per law,
   involves async search → poll → ZIP download), but does not require an HTML
   page visit. Used for discovery and as a fallback when caricaAKN fails.

**Historical versioning** — Normattiva's "multivigenza" system stores the
consolidated text of every law at every amendment date. ``get_text`` fetches
a **multi-vigenza envelope**: every historical version is downloaded by varying
the ``dataVigenza`` parameter across known amendment dates, and wrapped in a
``<normattiva-multi-vigenza>`` XML root so the parser can emit multi-``Version``
blocks and the pipeline can generate one git commit per reform.

References:
- Portal: https://dati.normattiva.it/
- API spec: dati.normattiva.it/assets/come_fare_per/API_Normattiva_OpenData.pdf
- URN format: RFC 9676 (LEX URN) — urn:nir:stato:legge:YYYY-MM-DD;NNN
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import date, datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree as ET

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://www.normattiva.it"
DEFAULT_API_URL = "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1"
MAX_VIGENZA_VERSIONS = 200


class NormativaClient(HttpClient):
    """Client for Italy's Normattiva corpus.

    norm_id is the ``codiceRedaz`` (editorial code), e.g. ``005G0104``.
    """

    @classmethod
    def create(cls, country_config: CountryConfig) -> NormativaClient:
        source = country_config.source or {}
        return cls(
            base_url=source.get("base_url", DEFAULT_BASE_URL),
            api_url=source.get("api_url", DEFAULT_API_URL),
            request_timeout=source.get("request_timeout", 30),
            max_retries=source.get("max_retries", 5),
            requests_per_second=source.get("requests_per_second", 2.0),
            include_history=bool(source.get("include_history", True)),
        )

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_url: str = DEFAULT_API_URL,
        request_timeout: int = 30,
        max_retries: int = 5,
        requests_per_second: float = 2.0,
        include_history: bool = True,
    ) -> None:
        super().__init__(
            base_url=base_url,
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
            extra_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
            },
        )
        self._api_url = api_url.rstrip("/")
        self._include_history = include_history
        self._params_cache: dict[str, dict[str, str]] = {}
        self._bundle_cache: dict[str, bytes] = {}
        self._bundle_lock = threading.Lock()

    def _extract_params_from_html(self, norm_id: str) -> dict[str, str] | None:
        """Visit a law's HTML page and extract caricaAKN parameters.

        Returns dict with dataGU, codiceRedaz, dataVigenza or None on failure.
        """
        cached = self._params_cache.get(norm_id)
        if cached:
            return cached

        url = f"{self._base_url}/atto/vediPermalink?atto.codiceRedazionale={norm_id}"
        try:
            html = self._request("GET", url).text
        except Exception as exc:
            logger.warning("Failed to load HTML for %s: %s", norm_id, exc)
            return None

        params: dict[str, str] = {}

        link_match = re.search(r'href="([^"]*caricaAKN[^"]*)"', html, re.I)
        if link_match:
            link = link_match.group(1).replace("&amp;", "&")
            parsed = urlparse(link)
            query = parse_qs(parsed.query)
            for key in ("dataGU", "codiceRedaz", "dataVigenza"):
                if key in query:
                    params[key] = query[key][0]

        if not all(k in params for k in ("dataGU", "codiceRedaz")):
            match_gu = re.search(
                r'name="atto\.dataPubblicazioneGazzetta"[^>]*value="([^"]+)"', html
            )
            match_codice = re.search(
                r'name="atto\.codiceRedazionale"[^>]*value="([^"]+)"', html
            )
            if match_gu:
                params["dataGU"] = match_gu.group(1).replace("-", "")
            if match_codice:
                params["codiceRedaz"] = match_codice.group(1)

        if "dataVigenza" not in params:
            match_vig = re.search(
                r'<input[^>]*name="dataVigenza"[^>]*value="(\d{2}/\d{2}/\d{4})"', html
            )
            if match_vig:
                d, m, y = match_vig.group(1).split("/")
                params["dataVigenza"] = f"{y}{m}{d}"
            else:
                params["dataVigenza"] = date.today().strftime("%Y%m%d")

        if all(k in params for k in ("dataGU", "codiceRedaz", "dataVigenza")):
            self._params_cache[norm_id] = params
            return params

        logger.warning("Could not extract all params for %s: got %s", norm_id, params)
        return None

    def _download_akn(self, params: dict[str, str]) -> bytes | None:
        """Download AKN XML using extracted parameters."""
        url = (
            f"{self._base_url}/do/atto/caricaAKN"
            f"?dataGU={params['dataGU']}"
            f"&codiceRedaz={params['codiceRedaz']}"
            f"&dataVigenza={params['dataVigenza']}"
        )
        try:
            content = self._get(url)
        except Exception as exc:
            logger.warning("caricaAKN failed for %s: %s", params.get("codiceRedaz"), exc)
            return None

        if content[:5] == b"<?xml" or b"<akomaNtoso" in content[:500]:
            return content
        return None

    def _extract_amendment_dates(self, xml_data: bytes) -> list[str]:
        """Extract amendment dates from an AKN XML's lifecycle events.

        Returns list of YYYYMMDD strings in chronological order.
        """
        dates: set[str] = set()
        try:
            root = ET.fromstring(xml_data)
            ns = {"akn": "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"}
            for event in root.iter("{http://docs.oasis-open.org/legaldocml/ns/akn/3.0}eventRef"):
                d = event.get("date", "")
                if d and len(d) == 10:
                    dates.add(d.replace("-", ""))

            for mod in root.iter("{http://docs.oasis-open.org/legaldocml/ns/akn/3.0}textualMod"):
                for child in mod:
                    href = child.get("href", "")
                    date_match = re.search(r":(\d{4}-\d{2}-\d{2})", href)
                    if date_match:
                        dates.add(date_match.group(1).replace("-", ""))
        except ET.ParseError:
            pass

        return sorted(dates)

    def get_text(self, norm_id: str) -> bytes:
        """Fetch the full history of an Italian law as a multi-vigenza bundle.

        If ``include_history`` is enabled, downloads the AKN XML at each
        known amendment date and wraps them in a
        ``<normattiva-multi-vigenza>`` envelope. The parser extracts
        multi-``Version`` blocks from this so the pipeline emits one git
        commit per reform.
        """
        with self._bundle_lock:
            cached = self._bundle_cache.get(norm_id)
        if cached is not None:
            return cached

        params = self._extract_params_from_html(norm_id)
        if not params:
            raise ValueError(f"Cannot extract download params for {norm_id}")

        current_xml = self._download_akn(params)
        if current_xml is None:
            raise ValueError(f"Failed to download AKN XML for {norm_id}")

        if not self._include_history:
            with self._bundle_lock:
                self._bundle_cache[norm_id] = current_xml
            return current_xml

        amendment_dates = self._extract_amendment_dates(current_xml)
        if len(amendment_dates) <= 1:
            with self._bundle_lock:
                self._bundle_cache[norm_id] = current_xml
            return current_xml

        if len(amendment_dates) > MAX_VIGENZA_VERSIONS:
            logger.info(
                "%s has %d amendment dates, truncating to most recent %d",
                norm_id,
                len(amendment_dates),
                MAX_VIGENZA_VERSIONS,
            )
            amendment_dates = amendment_dates[-MAX_VIGENZA_VERSIONS:]

        pieces: list[bytes] = [
            b"<?xml version='1.0' encoding='UTF-8'?>\n",
            f"<normattiva-multi-vigenza codice-redaz='{norm_id}'>\n".encode(),
        ]

        for vig_date in amendment_dates:
            vig_params = {**params, "dataVigenza": vig_date}
            try:
                xml_bytes = self._download_akn(vig_params)
            except Exception as exc:
                logger.warning(
                    "Failed to download vigenza %s for %s: %s", vig_date, norm_id, exc
                )
                continue
            if xml_bytes is None:
                continue

            iso_date = f"{vig_date[:4]}-{vig_date[4:6]}-{vig_date[6:8]}"
            pieces.append(f"<vigenza effective-date='{iso_date}'>\n".encode())
            inner = xml_bytes
            if inner.startswith(b"<?xml"):
                idx = inner.find(b"?>")
                if idx >= 0:
                    inner = inner[idx + 2:].lstrip()
            pieces.append(inner)
            pieces.append(b"\n</vigenza>\n")

        pieces.append(b"</normattiva-multi-vigenza>\n")
        bundle = b"".join(pieces)

        with self._bundle_lock:
            self._bundle_cache[norm_id] = bundle
        return bundle

    def get_metadata(self, norm_id: str) -> bytes:
        """Return the same data as get_text — metadata is embedded in AKN XML."""
        return self.get_text(norm_id)

    def normattiva_url_for(self, norm_id: str) -> str:
        """Build the canonical normattiva.it permalink for a codiceRedaz."""
        return f"{self._base_url}/atto/vediPermalink?atto.codiceRedazionale={norm_id}"
