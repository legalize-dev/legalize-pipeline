"""Macedonian legislation from the official LDBIS portal."""

from legalize.fetcher.mk.client import LDBISClient
from legalize.fetcher.mk.discovery import LDBISDiscovery
from legalize.fetcher.mk.parser import LDBISMetadataParser, LDBISTextParser

__all__ = ["LDBISClient", "LDBISDiscovery", "LDBISMetadataParser", "LDBISTextParser"]
