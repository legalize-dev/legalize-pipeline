"""Discovery of Andorran legislation via index.json on GitHub.

The index is generated from jurisprudencia.ad data and published
to the legalize-ad repo.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import date

from legalize.fetcher.ad.client import ADClient
from legalize.fetcher.base import LegislativeClient, NormDiscovery

logger = logging.getLogger(__name__)


class ADDiscovery(NormDiscovery):
    """Discovers Andorran laws from an index.json hosted on GitHub."""

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Yield all norm IDs from the index."""
        assert isinstance(client, ADClient)
        index_data = client.get_index()
        index = json.loads(index_data)

        for entry in index:
            yield entry["identifier"]

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Yield norm IDs updated on or after target_date."""
        assert isinstance(client, ADClient)
        index_data = client.get_index()
        index = json.loads(index_data)

        for entry in index:
            last_updated = date.fromisoformat(entry["last_updated"])
            if last_updated >= target_date:
                logger.info("Updated: %s (last_updated: %s)", entry["identifier"], last_updated)
                yield entry["identifier"]
