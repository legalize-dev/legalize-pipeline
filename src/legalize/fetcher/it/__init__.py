"""Italy (IT) -- legislative fetcher for Normattiva Open Data API."""

from legalize.fetcher.it.client import NormattivaClient
from legalize.fetcher.it.discovery import NormattivaDiscovery
from legalize.fetcher.it.parser import NormattivaMetadataParser, NormattivaTextParser

__all__ = [
    "NormattivaClient",
    "NormattivaDiscovery",
    "NormattivaTextParser",
    "NormattivaMetadataParser",
]
