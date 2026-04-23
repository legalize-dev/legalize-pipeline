"""Canada (CA) -- federal legislation fetcher components.

Source: Justice Canada consolidated XML via justicecanada/laws-lois-xml.
Bilingual: English (eng/) and French (fra/) as separate files.
Granularity: one file per consolidated act or regulation (~11,600 norms).
"""

from legalize.fetcher.ca.client import JusticeCanadaClient
from legalize.fetcher.ca.discovery import CADiscovery
from legalize.fetcher.ca.parser import CAMetadataParser, CATextParser

__all__ = ["JusticeCanadaClient", "CADiscovery", "CATextParser", "CAMetadataParser"]
