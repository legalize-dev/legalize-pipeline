"""United Kingdom (UK) — legislative fetcher components.

Source: The National Archives, https://www.legislation.gov.uk/
Format: CLML (Crown Legislation Markup Language) XML + Atom feeds.
License: Open Government Licence v3.0.

Four jurisdictions share the same schema:
    ukpga → uk/            (UK Public General Acts)
    asp   → uk-sct/        (Acts of the Scottish Parliament)
    asc/anaw/mwa → uk-wls/ (Welsh primary legislation)
    nia   → uk-nir/        (Acts of the Northern Ireland Assembly)
"""

from legalize.fetcher.uk.client import LegislationGovUkClient
from legalize.fetcher.uk.discovery import LegislationGovUkDiscovery
from legalize.fetcher.uk.parser import UKMetadataParser, UKTextParser

__all__ = [
    "LegislationGovUkClient",
    "LegislationGovUkDiscovery",
    "UKMetadataParser",
    "UKTextParser",
]
