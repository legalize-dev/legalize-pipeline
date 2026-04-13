"""Discovery of Italian legal acts via the Normattiva OpenData API.

The OpenData API exposes 46 predefined collections at:
    https://api.normattiva.it/t/normattiva.api/bff-opendata/v1/api/v1/collections/

For full-catalog discovery we use the async search endpoint which
supports date-range filtering and returns paginated results. Each
result includes the ``codiceRedaz`` (editorial code) which is the
norm_id used throughout the pipeline.

For daily updates we filter by ``PubblicazioneFrom``/``PubblicazioneTo``
set to the target date.

Total estimated acts (measured 2026-04-13): ~200,000+ across all types.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from datetime import date

from legalize.fetcher.base import LegislativeClient, NormDiscovery
from legalize.fetcher.it.client import NormativaClient

logger = logging.getLogger(__name__)

_API_BASE = "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1"
_SEARCH_URL = f"{_API_BASE}/api/v1/ricerca-asincrona/nuova-ricerca"
_CONFIRM_URL = f"{_API_BASE}/api/v1/ricerca-asincrona/conferma-ricerca"
_STATUS_URL = f"{_API_BASE}/api/v1/ricerca-asincrona/check-status"
_DOWNLOAD_URL = f"{_API_BASE}/api/v1/collections/download/collection-asincrona"

_POLL_INTERVAL = 2
_POLL_MAX_ATTEMPTS = 90


class NormativaDiscovery(NormDiscovery):
    """Discovery of Italian norm IDs via the Normattiva OpenData async search.

    ``discover_all`` runs a broad search across all Republic acts (1946+)
    and Kingdom of Italy acts (1861-1946), yielding codiceRedaz identifiers.

    ``discover_daily`` searches for acts published on a specific date.
    """

    def _run_async_search(
        self,
        client: NormativaClient,
        payload: dict,
    ) -> list[str]:
        """Execute an async search and return list of codiceRedaz IDs.

        Flow: POST search → get token → PUT confirm → poll status → parse results.
        """
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        try:
            resp = client._session.post(
                _SEARCH_URL,
                headers=headers,
                data=json.dumps(payload),
                timeout=client._timeout,
            )
        except Exception as exc:
            logger.error("Search request failed: %s", exc)
            return []

        if resp.status_code != 200:
            error_body = resp.text[:300]
            if "7000" in error_body:
                logger.warning("Search returned >7000 results, need narrower query")
            else:
                logger.warning("Search failed (%d): %s", resp.status_code, error_body)
            return []

        token = resp.text.strip().strip('"')
        if not token:
            logger.warning("Empty search token received")
            return []

        try:
            client._session.put(
                _CONFIRM_URL,
                headers=headers,
                data=json.dumps({"token": token}),
                timeout=client._timeout,
            )
        except Exception:
            pass

        for _ in range(_POLL_MAX_ATTEMPTS):
            try:
                status_resp = client._session.get(
                    f"{_STATUS_URL}/{token}",
                    headers={"Accept": "application/json"},
                    timeout=client._timeout,
                )
                if status_resp.status_code == 303:
                    break
                status_data = status_resp.json()
                if status_data.get("stato") == 3:
                    total = status_data.get("totAtti", 0)
                    logger.info("Search complete: %d acts found", total)
                    break
            except Exception:
                pass
            time.sleep(_POLL_INTERVAL)
        else:
            logger.warning("Search did not complete within timeout")
            return []

        try:
            download_resp = client._session.get(
                f"{_DOWNLOAD_URL}/{token}",
                headers={"Accept": "application/json"},
                timeout=client._timeout,
            )
            download_resp.raise_for_status()
            results = download_resp.json()
        except Exception as exc:
            logger.warning("Failed to download search results: %s", exc)
            return []

        ids: list[str] = []
        if isinstance(results, list):
            for item in results:
                codice = item.get("codiceRedazionale") or item.get("codiceRedaz", "")
                if codice:
                    ids.append(codice)
        return ids

    def discover_all(
        self,
        client: LegislativeClient,
        **kwargs,
    ) -> Iterator[str]:
        """Yield every Italian norm codiceRedaz.

        Runs two searches: Republic acts (1946-present) and Kingdom of
        Italy acts (1861-1946) that are still in force (vigenti).
        """
        assert isinstance(client, NormativaClient)

        searches = [
            {
                "name": "Republic acts",
                "payload": {
                    "formato": "JSON",
                    "richiestaExport": "M",
                    "modalita": "C",
                    "tipoRicerca": "A",
                    "parametriRicerca": {
                        "EmanazioneFrom": "1946-06-20",
                        "EmanazioneTo": date.today().isoformat(),
                    },
                },
            },
            {
                "name": "Kingdom of Italy vigenti",
                "payload": {
                    "formato": "JSON",
                    "richiestaExport": "M",
                    "modalita": "C",
                    "tipoRicerca": "A",
                    "parametriRicerca": {
                        "EmanazioneFrom": "1861-01-01",
                        "EmanazioneTo": "1946-06-10",
                        "classeProvvedimento": "2",
                    },
                },
            },
        ]

        seen: set[str] = set()
        for search in searches:
            logger.info("Running discovery: %s", search["name"])
            ids = self._run_async_search(client, search["payload"])
            for norm_id in ids:
                if norm_id not in seen:
                    seen.add(norm_id)
                    yield norm_id

        logger.info("Normattiva discovery: yielded %d unique norm IDs", len(seen))

    def discover_daily(
        self,
        client: LegislativeClient,
        target_date: date,
        **kwargs,
    ) -> Iterator[str]:
        """Yield norm IDs published in the Gazzetta Ufficiale on target_date."""
        assert isinstance(client, NormativaClient)

        iso = target_date.isoformat()
        payload = {
            "formato": "JSON",
            "richiestaExport": "M",
            "modalita": "C",
            "tipoRicerca": "A",
            "parametriRicerca": {
                "PubblicazioneFrom": iso,
                "PubblicazioneTo": iso,
            },
        }

        seen: set[str] = set()
        ids = self._run_async_search(client, payload)
        for norm_id in ids:
            if norm_id not in seen:
                seen.add(norm_id)
                yield norm_id
