"""Cuba (CU) -- legislative fetcher components.

Source: the official Gaceta Oficial de la República de Cuba
(``gacetaoficial.gob.cu``) plus the MINJUS portal for a handful of
consolidated book editions. PDFs carry the full text layer; there is no
XML/HTML/JSON full-text.

The URL map and publication metadata live in ``manifest.json`` (shipped in
the ``legalize-cu`` repo), because the Gaceta catalog page exposes law
*names* but no ``.pdf`` links. PDF text extraction uses **pymupdf**
(AGPL-3.0) and a cleanup algorithm ported from the reference converter
``/tmp/legalize-cu/convert.py``.
"""

from legalize.fetcher.cu.client import GacetaClient
from legalize.fetcher.cu.discovery import GacetaDiscovery
from legalize.fetcher.cu.parser import (
    GacetaMetadataParser,
    GacetaTextParser,
)

__all__ = [
    "GacetaClient",
    "GacetaDiscovery",
    "GacetaMetadataParser",
    "GacetaTextParser",
]
