"""Poland (PL) -- legislative fetcher components.

Source: ELI API of the Polish Sejm (https://api.sejm.gov.pl/eli).

Scope: publisher DU (Dziennik Ustaw). Acts with HTML text go through
EliTextParser's HTML path. Acts that only have a PDF (every act since 2025,
98 acts of 2020-2023) go through parser_pdf when their year is at least
``pdf_from_year`` (config.yaml); older PDF-only acts (pre-2012 issues, the
Konstytucja 1997) are still skipped client-side on the listing's own
``textHTML`` flag.
"""

from legalize.fetcher.pl.client import EliClient
from legalize.fetcher.pl.discovery import EliDiscovery
from legalize.fetcher.pl.parser import EliMetadataParser, EliTextParser

__all__ = ["EliClient", "EliDiscovery", "EliTextParser", "EliMetadataParser"]
