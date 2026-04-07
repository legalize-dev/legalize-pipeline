"""Country registry — dynamic dispatch for multi-country pipeline.

To add a new country:
1. Create fetcher/{code}/ with client.py, discovery.py, parser.py
2. Register the import paths in REGISTRY below

See ADDING_A_COUNTRY.md for full walkthrough.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from legalize.fetcher.base import (
        LegislativeClient,
        MetadataParser,
        NormDiscovery,
        TextParser,
    )

# ─── Registry ───
# Each country maps to (module_path, class_name) for lazy imports.
# This avoids importing all country modules at startup.

REGISTRY: dict[str, dict[str, tuple[str, str]]] = {
    "es": {
        "client": ("legalize.fetcher.es.client", "BOEClient"),
        "discovery": ("legalize.fetcher.es.discovery", "BOEDiscovery"),
        "text_parser": ("legalize.fetcher.es.parser", "BOETextParser"),
        "metadata_parser": ("legalize.fetcher.es.parser", "BOEMetadataParser"),
    },
    "fr": {
        "client": ("legalize.fetcher.fr.client", "LEGIClient"),
        "discovery": ("legalize.fetcher.fr.discovery", "LEGIDiscovery"),
        "text_parser": ("legalize.fetcher.fr.parser", "LEGITextParser"),
        "metadata_parser": ("legalize.fetcher.fr.parser", "LEGIMetadataParser"),
    },
    "se": {
        "client": ("legalize.fetcher.se.client", "SwedishClient"),
        "discovery": ("legalize.fetcher.se.discovery", "SwedishDiscovery"),
        "text_parser": ("legalize.fetcher.se.parser", "SwedishTextParser"),
        "metadata_parser": ("legalize.fetcher.se.parser", "SwedishMetadataParser"),
    },
    "at": {
        "client": ("legalize.fetcher.at.client", "RISClient"),
        "discovery": ("legalize.fetcher.at.discovery", "RISDiscovery"),
        "text_parser": ("legalize.fetcher.at.parser", "RISTextParser"),
        "metadata_parser": ("legalize.fetcher.at.parser", "RISMetadataParser"),
    },
    "de": {
        "client": ("legalize.fetcher.de.client", "GIIClient"),
        "discovery": ("legalize.fetcher.de.discovery", "GIIDiscovery"),
        "text_parser": ("legalize.fetcher.de.parser", "GIITextParser"),
        "metadata_parser": ("legalize.fetcher.de.parser", "GIIMetadataParser"),
    },
    "cl": {
        "client": ("legalize.fetcher.cl.client", "BCNClient"),
        "discovery": ("legalize.fetcher.cl.discovery", "BCNDiscovery"),
        "text_parser": ("legalize.fetcher.cl.parser", "CLTextParser"),
        "metadata_parser": ("legalize.fetcher.cl.parser", "CLMetadataParser"),
    },
    "lt": {
        "client": ("legalize.fetcher.lt.client", "TARClient"),
        "discovery": ("legalize.fetcher.lt.discovery", "TARDiscovery"),
        "text_parser": ("legalize.fetcher.lt.parser", "TARTextParser"),
        "metadata_parser": ("legalize.fetcher.lt.parser", "TARMetadataParser"),
    },
    "pt": {
        "client": ("legalize.fetcher.pt.client", "DREClient"),
        "discovery": ("legalize.fetcher.pt.discovery", "DREDiscovery"),
        "text_parser": ("legalize.fetcher.pt.parser", "DRETextParser"),
        "metadata_parser": ("legalize.fetcher.pt.parser", "DREMetadataParser"),
    },
    "uy": {
        "client": ("legalize.fetcher.uy.client", "IMPOClient"),
        "discovery": ("legalize.fetcher.uy.discovery", "IMPODiscovery"),
        "text_parser": ("legalize.fetcher.uy.parser", "IMPOTextParser"),
        "metadata_parser": ("legalize.fetcher.uy.parser", "IMPOMetadataParser"),
    },
    "ad": {
        "client": ("legalize.fetcher.ad.client", "ADClient"),
        "discovery": ("legalize.fetcher.ad.discovery", "ADDiscovery"),
        "text_parser": ("legalize.fetcher.ad.parser", "ADTextParser"),
        "metadata_parser": ("legalize.fetcher.ad.parser", "ADMetadataParser"),
    },
    # To add a new country:
    # 1. Create fetcher/{code}/ with client.py, discovery.py, parser.py
    # 2. Register here
    # See ADDING_A_COUNTRY.md
}


def _import_class(module_path: str, class_name: str):
    """Lazy import a class by module path and name."""
    from importlib import import_module

    module = import_module(module_path)
    return getattr(module, class_name)


def _get(country_code: str, component: str):
    """Get a component class for a country."""
    if country_code not in REGISTRY:
        available = ", ".join(sorted(REGISTRY.keys()))
        raise ValueError(f"Country '{country_code}' not registered. Available: {available}")
    if component not in REGISTRY[country_code]:
        raise ValueError(f"Component '{component}' not registered for country '{country_code}'")
    module_path, class_name = REGISTRY[country_code][component]
    return _import_class(module_path, class_name)


def supported_countries() -> list[str]:
    """List of registered country codes."""
    return sorted(REGISTRY.keys())


def get_client_class(country_code: str) -> type[LegislativeClient]:
    return _get(country_code, "client")


def get_discovery_class(country_code: str) -> type[NormDiscovery]:
    return _get(country_code, "discovery")


def get_text_parser(country_code: str) -> TextParser:
    return _get(country_code, "text_parser")()


def get_metadata_parser(country_code: str) -> MetadataParser:
    return _get(country_code, "metadata_parser")()
