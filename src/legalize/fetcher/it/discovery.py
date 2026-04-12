"""Discovery of Italian legal acts via the Normattiva OpenData API.

The API exposes two main discovery methods:

1. Full catalog search (bootstrap): POST /ricerca/semplice with text="*"
   returns ~205K acts, paginated. Each page returns up to 100 acts with
   their codiceRedazionale (unique identifier).

2. Daily updates: POST /ricerca/aggiornati with a date range returns acts
   that were modified between those dates.

Act types (denominazioneAtto codes):
  PLE = Legge
  PLL = Decreto Legislativo
  PDL = Decreto-Legge
  PPR = Decreto del Presidente della Repubblica
  PRD = Regio Decreto
  PLC = Legge Costituzionale
  COS = Costituzione
  PCM_DPC = DPCM
  PDM = Decreto Ministeriale
  D10 = Regolamento
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date

from legalize.fetcher.base import LegislativeClient, NormDiscovery
from legalize.fetcher.it.client import NormattivaClient

logger = logging.getLogger(__name__)

# Act types to include in discovery (primary legislation).
# Excludes purely administrative acts, ordinanze, deliberazioni.
PRIMARY_ACT_TYPES = frozenset({
    "LEGGE",
    "DECRETO LEGISLATIVO",
    "DECRETO-LEGGE",
    "DECRETO DEL PRESIDENTE DELLA REPUBBLICA",
    "LEGGE COSTITUZIONALE",
    "COSTITUZIONE",
    "REGIO DECRETO",
    "DECRETO DEL PRESIDENTE DEL CONSIGLIO DEI MINISTRI",
    "DECRETO MINISTERIALE",
    "REGOLAMENTO",
    "REGIO DECRETO-LEGGE",
    "DECRETO LEGISLATIVO LUOGOTENENZIALE",
    "DECRETO LEGISLATIVO DEL CAPO PROVVISORIO DELLO STATO",
    "DECRETO",
})

# Map denominazioneAtto (search result) to URN act type path segment
_DENOM_TO_URN_TYPE: dict[str, str] = {
    "LEGGE": "legge",
    "DECRETO LEGISLATIVO": "decreto.legislativo",
    "DECRETO-LEGGE": "decreto-legge",
    "DECRETO DEL PRESIDENTE DELLA REPUBBLICA": "decreto.del.presidente.della.repubblica",
    "LEGGE COSTITUZIONALE": "legge.costituzionale",
    "COSTITUZIONE": "costituzione",
    "REGIO DECRETO": "regio.decreto",
    "REGIO DECRETO-LEGGE": "regio.decreto-legge",
    "DECRETO DEL PRESIDENTE DEL CONSIGLIO DEI MINISTRI": "decreto.del.presidente.del.consiglio.dei.ministri",
    "DECRETO MINISTERIALE": "decreto.ministeriale",
    "REGOLAMENTO": "regolamento",
    "DECRETO LEGISLATIVO LUOGOTENENZIALE": "decreto.legislativo.luogotenenziale",
    "DECRETO LEGISLATIVO DEL CAPO PROVVISORIO DELLO STATO": "decreto.legislativo.del.capo.provvisorio.dello.stato",
    "DECRETO": "decreto",
}


def _build_urn(act: dict) -> str | None:
    """Construct a URN from search result fields.

    Format: urn:nir:stato:{tipo}:{anno-mese-giorno};{numero}
    """
    denom = act.get("denominazioneAtto", "")
    urn_type = _DENOM_TO_URN_TYPE.get(denom)
    if not urn_type:
        return None

    anno = act.get("annoProvvedimento", "")
    mese = act.get("meseProvvedimento", "")
    giorno = act.get("giornoProvvedimento", "")
    numero = act.get("numeroProvvedimento", "")

    if not (anno and mese and giorno and numero):
        return None

    mese = str(mese).zfill(2)
    giorno = str(giorno).zfill(2)

    return f"urn:nir:stato:{urn_type}:{anno}-{mese}-{giorno};{numero}"


class NormattivaDiscovery(NormDiscovery):
    """Discovers Italian legal acts via the Normattiva OpenData API.

    Bootstrap: paginated search returning ~205K acts
    Daily: updated-acts endpoint for a date range
    """

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Yield norm IDs from the catalog.

        Each ID is formatted as ``{codiceRedazionale}:{dataGU}:{urn}`` so the
        client can visit the URN page (required for session state) and then
        download the AKN XML.

        Paginates through the full catalog using the simple search API
        with text="*" to match all acts.
        """
        assert isinstance(client, NormattivaClient)

        page = 1
        page_size = 100
        seen: set[str] = set()
        total_pages = None

        while True:
            result = client.search(text="*", page=page, page_size=page_size)
            acts = result.get("listaAtti", [])
            total_pages = result.get("numeroPagine", 0)

            if not acts:
                break

            for act in acts:
                if not act:
                    continue
                codice = act.get("codiceRedazionale")
                data_gu = act.get("dataGU", "")
                if not codice or codice in seen:
                    continue

                denom = act.get("denominazioneAtto", "")
                if denom and denom not in PRIMARY_ACT_TYPES:
                    continue

                seen.add(codice)

                urn = _build_urn(act) or ""
                yield f"{codice}:{data_gu}:{urn}"

            if total_pages and page >= total_pages:
                break

            page += 1
            if page % 50 == 0:
                logger.info(
                    "Discovery progress: page %d/%s, %d unique IDs so far",
                    page,
                    total_pages or "?",
                    len(seen),
                )

        logger.info("Total unique IDs discovered: %d", len(seen))

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Yield codiceRedazionale of acts updated on target_date.

        Uses the ricerca/aggiornati endpoint which returns acts modified
        within a date range. We query for a single day.
        """
        assert isinstance(client, NormattivaClient)

        date_str = target_date.isoformat()
        try:
            result = client.search_updated(date_str, date_str)
        except Exception as exc:
            logger.warning("Failed to fetch updated acts for %s: %s", target_date, exc)
            return

        acts = result.get("listaAtti", [])
        seen: set[str] = set()

        for act in acts:
            if not act:
                continue
            codice = act.get("codiceRedazionale")
            data_gu = act.get("dataGU", "")
            if not codice or codice in seen:
                continue

            denom = act.get("denominazioneAtto", "")
            if denom and denom not in PRIMARY_ACT_TYPES:
                continue

            seen.add(codice)

            urn = _build_urn(act) or ""
            yield f"{codice}:{data_gu}:{urn}"

        logger.info(
            "Daily discovery for %s: %d acts found", target_date, len(seen)
        )
