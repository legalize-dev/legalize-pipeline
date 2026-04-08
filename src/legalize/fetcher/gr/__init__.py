"""Greece (GR) -- legislative fetcher components.

Source: official ``searchetv99.azurewebsites.net`` Azure Functions
backend — the public API behind ``https://search.et.gr/`` (the Greek
National Printing House search portal). Discovery + metadata via the
JSON endpoints; PDFs hosted on the official Azure Blob storage at
``ia37rg02wpsa01.blob.core.windows.net/fek/``.

PDF text extraction uses ``pypdfium2`` (BSD-3-Clause) and a cleanup
algorithm adapted with attribution from Lampros Kafidas's
``fekpdf2text_2024.py`` (Harvard Dataverse, doi:10.7910/DVN/F1CNFC, MIT).
"""

from legalize.fetcher.gr.client import GreekClient
from legalize.fetcher.gr.discovery import GreekDiscovery
from legalize.fetcher.gr.parser import (
    GreekMetadataParser,
    GreekTextParser,
)

__all__ = [
    "GreekClient",
    "GreekDiscovery",
    "GreekMetadataParser",
    "GreekTextParser",
]
