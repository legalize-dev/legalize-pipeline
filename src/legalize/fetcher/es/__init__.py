"""Spain (ES) — BOE legislative fetcher components."""

from legalize.fetcher.es.client import BOEClient
from legalize.fetcher.es.discovery import BOEDiscovery
from legalize.fetcher.es.parser import BOEMetadataParser, BOETextParser

__all__ = [
    "BOEClient",
    "BOEDiscovery",
    "BOETextParser",
    "BOEMetadataParser",
    "daily",
    "fetch_catalog",
    "fetch_catalog_ccaa",
    "fetch_one",
    "fetch_all",
]


def __getattr__(name):
    """Lazy imports for fetch and daily submodules."""
    if name == "daily":
        from legalize.fetcher.es.daily import daily

        return daily
    if name in ("fetch_one", "fetch_all", "fetch_catalog", "fetch_catalog_ccaa"):
        from legalize.fetcher.es import fetch as _fetch

        return getattr(_fetch, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
