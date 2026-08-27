"""Poland (PL) -- legislative fetcher components.

Source: ELI API of the Polish Sejm (https://api.sejm.gov.pl/eli).

Scope v1: publisher DU (Dziennik Ustaw) only, acts with HTML text only.
Acts that only have PDF (Konstytucja 1997, Obwieszczenia with consolidated
codes, pre-2012 historical acts) are skipped client-side on the listing's own
``textHTML`` flag: the pipeline publishes Markdown derived from that HTML, so a
PDF-only act would ship as a law with no text in it at all.
"""

from legalize.fetcher.pl.client import EliClient
from legalize.fetcher.pl.discovery import EliDiscovery
from legalize.fetcher.pl.parser import EliMetadataParser, EliTextParser

__all__ = ["EliClient", "EliDiscovery", "EliTextParser", "EliMetadataParser"]
