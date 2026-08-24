"""Portugal (PT) — Diário da República Eletrónico fetcher.

One client over two DRE surfaces: the consolidated corpus (5,528 diplomas with
article-level version history) and the diploma as published (everything else).
See docs/pt-dre-api.md and RESEARCH-PT-v2.md.
"""

from legalize.fetcher.pt.client import DREClient
from legalize.fetcher.pt.discovery import DREDiscovery
from legalize.fetcher.pt.parser import DREMetadataParser, DRETextParser

__all__ = ["DREClient", "DREDiscovery", "DRETextParser", "DREMetadataParser"]
