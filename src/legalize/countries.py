"""Country registry — dynamic dispatch for multi-country pipeline.

To add a new country:
1. Implement LegislativeClient, NormDiscovery, TextParser, MetadataParser in fetcher/
2. Register the import paths in REGISTRY below
3. Add rango folders to transformer/slug.py RANGO_FOLDERS
4. Add country config to web/countries.py COUNTRIES dict
5. Create pipeline_{code}.py for fetch/bootstrap orchestration
6. Add CLI commands to cli.py

See docs/ADDING_A_COUNTRY.md for full walkthrough.
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
        "client": ("legalize.fetcher.client", "BOEClient"),
        "discovery": ("legalize.fetcher.discovery_boe", "BOEDiscovery"),
        "text_parser": ("legalize.fetcher.parser_boe", "BOETextParser"),
        "metadata_parser": ("legalize.fetcher.parser_boe", "BOEMetadataParser"),
    },
    "fr": {
        "client": ("legalize.fetcher.client_legi", "LEGIClient"),
        "discovery": ("legalize.fetcher.discovery_legi", "LEGIDiscovery"),
        "text_parser": ("legalize.fetcher.parser_legi", "LEGITextParser"),
        "metadata_parser": ("legalize.fetcher.parser_legi", "LEGIMetadataParser"),
    },
    # To add a new country (e.g. UK):
    # "uk": {
    #     "client": ("legalize.fetcher.client_uk", "UKClient"),
    #     "discovery": ("legalize.fetcher.discovery_uk", "UKDiscovery"),
    #     "text_parser": ("legalize.fetcher.parser_uk", "UKTextParser"),
    #     "metadata_parser": ("legalize.fetcher.parser_uk", "UKMetadataParser"),
    # },
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
