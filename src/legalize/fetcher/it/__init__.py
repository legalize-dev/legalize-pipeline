"""Italy (IT) — Normattiva legislative fetcher components.

Data source: Normattiva Open Data (dati.normattiva.it)
Format: Akoma Ntoso 3.0 XML
License: CC BY 4.0 (since 2026-01-01)
Historical versions: via multivigenza (dataVigenza parameter)
"""

from legalize.fetcher.it.client import NormativaClient
from legalize.fetcher.it.discovery import NormativaDiscovery
from legalize.fetcher.it.parser import NormativaMetadataParser, NormativaTextParser

__all__ = [
    "NormativaClient",
    "NormativaDiscovery",
    "NormativaTextParser",
    "NormativaMetadataParser",
]
