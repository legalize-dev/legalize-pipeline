"""Andorra (AD) -- legislative fetcher components.

Source: JSON data files hosted at github.com/ericrisco/legalize-ad/data/
Maintained by the Andorran legal data community.
"""

from legalize.fetcher.ad.client import ADClient
from legalize.fetcher.ad.discovery import ADDiscovery
from legalize.fetcher.ad.parser import ADMetadataParser, ADTextParser

__all__ = ["ADClient", "ADDiscovery", "ADTextParser", "ADMetadataParser"]
