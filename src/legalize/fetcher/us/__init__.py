"""United States (US) -- federal legislation fetcher components.

Source: Office of the Law Revision Counsel (OLRC) at uscode.house.gov.
Parses USLM XML (United States Legislative Markup) for the US Code.
Granularity: one file per US Code chapter (~3,000 chapters across 54 titles).
"""

from legalize.fetcher.us.client import OLRCClient
from legalize.fetcher.us.discovery import USDiscovery
from legalize.fetcher.us.parser import USMetadataParser, USTextParser

__all__ = ["OLRCClient", "USDiscovery", "USTextParser", "USMetadataParser"]
