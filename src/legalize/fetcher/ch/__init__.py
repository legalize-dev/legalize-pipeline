"""Switzerland (CH) — Fedlex legislative fetcher components.

Federal Swiss legislation from Fedlex (https://www.fedlex.admin.ch/).
Scope v1: Classified Compilation (eli/cc/, aka SR / Systematic Collection)
in German. XML-based via Akoma Ntoso 3.0, discovered through the Fedlex
SPARQL endpoint powered by JOLux (same ontology as Luxembourg's Legilux).

See RESEARCH-CH.md at the workspace root for full background.
"""

from legalize.fetcher.ch.client import FedlexClient
from legalize.fetcher.ch.discovery import FedlexDiscovery
from legalize.fetcher.ch.parser import FedlexMetadataParser, FedlexTextParser

__all__ = [
    "FedlexClient",
    "FedlexDiscovery",
    "FedlexMetadataParser",
    "FedlexTextParser",
]
