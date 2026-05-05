"""Guatemala (GT) legislative fetcher components."""

from legalize.fetcher.gt.client import GTFixtureClient
from legalize.fetcher.gt.discovery import GTFixtureDiscovery
from legalize.fetcher.gt.parser import GTMetadataParser, GTTextParser

__all__ = [
    "GTFixtureClient",
    "GTFixtureDiscovery",
    "GTTextParser",
    "GTMetadataParser",
]
