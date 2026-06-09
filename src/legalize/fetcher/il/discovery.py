"""Israel legislation discovery layer (il)."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

from legalize.fetcher.base import LegislativeClient, NormDiscovery

logger = logging.getLogger(__name__)


class IsraelDiscovery(NormDiscovery):
    """Discovers Israeli laws from Knesset OData."""

    @classmethod
    def create(cls, source: dict[str, Any]) -> IsraelDiscovery:
        """Create from source config."""
        return cls(is_basic_law_only=source.get("is_basic_law_only", False))

    def __init__(self, is_basic_law_only: bool = False) -> None:
        self.is_basic_law_only = is_basic_law_only

    def discover_all(self, client: LegislativeClient, **kwargs: Any) -> Iterator[str]:
        """Page through all KNS_IsraelLaw records and yield norm IDs.

        Can filter to Basic Laws only if configured.
        """
        # Ensure we have the IsraelClient
        il_client = client

        path = "KNS_IsraelLaw"
        if self.is_basic_law_only:
            path += "?$filter=IsBasicLaw eq true"

        logger.info("Starting Knesset discovery with path: %s", path)

        while path:
            resp_bytes = il_client._get_odata(path)
            data = json.loads(resp_bytes.decode("utf-8"))

            for item in data.get("value", []):
                norm_id = str(item.get("Id"))
                yield norm_id

            # Handle pagination via @odata.nextLink
            next_link = data.get("@odata.nextLink")
            if next_link:
                # OData next links are absolute URLs.
                # Strip the base URL to make it a relative path for the client
                base_url = il_client._base_url
                if next_link.startswith(base_url):
                    path = next_link[len(base_url) :]
                else:
                    # Fallback in case of absolute URL mismatch
                    path = next_link
            else:
                path = ""

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs: Any
    ) -> Iterator[str]:
        """Discovers Knesset laws updated on a target date."""
        il_client = client
        next_day = target_date + timedelta(days=1)

        # Query with LastUpdatedDate filter
        filter_str = (
            f"LastUpdatedDate ge {target_date.isoformat()}T00:00:00Z and "
            f"LastUpdatedDate lt {next_day.isoformat()}T00:00:00Z"
        )

        path = f"KNS_IsraelLaw?$filter={filter_str}"
        logger.info("Daily discovery query: %s", path)

        while path:
            resp_bytes = il_client._get_odata(path)
            data = json.loads(resp_bytes.decode("utf-8"))

            for item in data.get("value", []):
                norm_id = str(item.get("Id"))
                yield norm_id

            next_link = data.get("@odata.nextLink")
            if next_link:
                base_url = il_client._base_url
                if next_link.startswith(base_url):
                    path = next_link[len(base_url) :]
                else:
                    path = next_link
            else:
                path = ""
