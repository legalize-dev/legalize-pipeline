"""Romanian norm discovery via SOAP API.

The Portal Legislativ SOAP API at /apiws/FreeWebService.svc provides two
methods: GetToken() and Search(). We use Search() to enumerate all norms
by year, extracting document IDs from the LinkHtml field.

The SOAP API has quirks:
- Token expires after ~5 minutes -- regenerate frequently.
- Pagination is 1-indexed: page 0 and page 1 return the same results.
- Max 100 results per page.
- Requires the zeep library for reliable SOAP interaction.

For daily discovery, we search by year and filter by publication date.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterator
from datetime import date
from typing import TYPE_CHECKING

from legalize.fetcher.base import LegislativeClient, NormDiscovery

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_DOC_ID_RE = re.compile(r"DetaliiDocument/(\d+)")

# Act types to include in bootstrap. These cover the main legislative corpus.
# Excluded: COMUNICAT, ANEXĂ, INSTRUCȚIUNE, PROTOCOL, etc. (secondary/administrative).
_INCLUDED_ACT_TYPES = {
    "CONSTITUȚIE",
    "LEGE",
    "LEGE CONSTITUȚIONALĂ",
    "COD",
    "COD CIVIL",
    "COD PENAL",
    "COD FISCAL",
    "CODUL CIVIL",
    "CODUL PENAL",
    "CODUL FISCAL",
    "CODUL MUNCII",
    "CODUL DE PROCEDURĂ CIVILĂ",
    "CODUL DE PROCEDURĂ PENALĂ",
    "ORDONANȚĂ",
    "ORDONANȚĂ DE URGENȚĂ",
    "HOTĂRÂRE",
    "DECRET",
    "DECRET-LEGE",
    "REGULAMENT",
    "NORMĂ",
    "STATUT",
}


class RoDiscovery(NormDiscovery):
    """Discover Romanian norms via the SOAP API."""

    def discover_all(
        self,
        client: LegislativeClient,
        **kwargs,
    ) -> Iterator[str]:
        """Yield all norm IDs by paginating through years via the SOAP API.

        Uses zeep to call the SOAP Search() method, paginating by year
        from the start year to the current year.
        """
        start_year = kwargs.get("start_year", 1989)
        end_year = kwargs.get("end_year", date.today().year)
        limit = kwargs.get("limit")

        try:
            from zeep import Client as SoapClient
        except ImportError:
            logger.error("zeep is required for Romanian discovery: pip install zeep")
            return

        soap = SoapClient("http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl")
        search_type = soap.get_type(
            "{http://schemas.datacontract.org/2004/07/FreeWebService}CompositeType"
        )

        seen: set[str] = set()
        count = 0
        token = soap.service.GetToken()
        token_time = time.monotonic()

        for year in range(start_year, end_year + 1):
            page = 1
            consecutive_empty = 0

            while True:
                # Refresh token every 4 minutes.
                if time.monotonic() - token_time > 240:
                    token = soap.service.GetToken()
                    token_time = time.monotonic()

                try:
                    model = search_type(
                        NumarPagina=page,
                        RezultatePagina=100,
                        SearchAn=str(year),
                    )
                    result = soap.service.Search(model, token)
                except Exception as exc:
                    if "TOKEN" in str(exc).upper():
                        token = soap.service.GetToken()
                        token_time = time.monotonic()
                        continue
                    logger.warning("SOAP error for year %d page %d: %s", year, page, exc)
                    break

                if not result:
                    consecutive_empty += 1
                    if consecutive_empty >= 2:
                        break
                    page += 1
                    continue

                consecutive_empty = 0
                for law in result:
                    link = getattr(law, "LinkHtml", None)
                    tip = getattr(law, "TipAct", "")
                    if not link:
                        continue

                    m = _DOC_ID_RE.search(link)
                    if not m:
                        continue

                    doc_id = m.group(1)
                    if doc_id in seen:
                        continue
                    seen.add(doc_id)

                    # Filter by act type if available.
                    if tip and tip.upper().strip() not in _INCLUDED_ACT_TYPES:
                        continue

                    yield doc_id
                    count += 1

                    if limit and count >= limit:
                        return

                page += 1
                time.sleep(0.3)

            logger.info("Year %d: discovered %d norms so far", year, count)

    def discover_daily(
        self,
        client: LegislativeClient,
        target_date: date,
        **kwargs,
    ) -> Iterator[str]:
        """Yield norm IDs updated on a specific date.

        Uses the SOAP API to search by year and filters results by date.
        """
        try:
            from zeep import Client as SoapClient
        except ImportError:
            logger.error("zeep is required for Romanian discovery")
            return

        soap = SoapClient("http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl")
        search_type = soap.get_type(
            "{http://schemas.datacontract.org/2004/07/FreeWebService}CompositeType"
        )

        token = soap.service.GetToken()
        seen: set[str] = set()
        page = 1

        while True:
            try:
                model = search_type(
                    NumarPagina=page,
                    RezultatePagina=100,
                    SearchAn=str(target_date.year),
                )
                result = soap.service.Search(model, token)
            except Exception as exc:
                if "TOKEN" in str(exc).upper():
                    token = soap.service.GetToken()
                    continue
                logger.warning("SOAP error for daily %s page %d: %s", target_date, page, exc)
                break

            if not result:
                break

            for law in result:
                data_vigoare = getattr(law, "DataVigoare", "")
                link = getattr(law, "LinkHtml", "")
                if not link or not data_vigoare:
                    continue

                # DataVigoare is ISO format "YYYY-MM-DD" from the SOAP API.
                try:
                    law_date = date.fromisoformat(str(data_vigoare)[:10])
                except (ValueError, TypeError):
                    continue

                if law_date != target_date:
                    continue

                m = _DOC_ID_RE.search(link)
                if not m:
                    continue

                doc_id = m.group(1)
                if doc_id not in seen:
                    seen.add(doc_id)
                    yield doc_id

            page += 1
            time.sleep(0.3)
