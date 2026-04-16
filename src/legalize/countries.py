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
    "ad": {
        "client": ("legalize.fetcher.ad.client", "BOPAClient"),
        "discovery": ("legalize.fetcher.ad.discovery", "BOPADiscovery"),
        "text_parser": ("legalize.fetcher.ad.parser", "BOPATextParser"),
        "metadata_parser": ("legalize.fetcher.ad.parser", "BOPAMetadataParser"),
    },
    "ar": {
        "client": ("legalize.fetcher.ar.client", "InfoLEGClient"),
        "discovery": ("legalize.fetcher.ar.discovery", "InfoLEGDiscovery"),
        "text_parser": ("legalize.fetcher.ar.parser", "InfoLEGTextParser"),
        "metadata_parser": ("legalize.fetcher.ar.parser", "InfoLEGMetadataParser"),
    },
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
    "ee": {
        "client": ("legalize.fetcher.ee.client", "RTClient"),
        "discovery": ("legalize.fetcher.ee.discovery", "RTDiscovery"),
        "text_parser": ("legalize.fetcher.ee.parser", "RTTextParser"),
        "metadata_parser": ("legalize.fetcher.ee.parser", "RTMetadataParser"),
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
    "lu": {
        "client": ("legalize.fetcher.lu.client", "LegiluxClient"),
        "discovery": ("legalize.fetcher.lu.discovery", "LegiluxDiscovery"),
        "text_parser": ("legalize.fetcher.lu.parser", "LegiluxTextParser"),
        "metadata_parser": ("legalize.fetcher.lu.parser", "LegiluxMetadataParser"),
    },
    "pt": {
        "client": ("legalize.fetcher.pt.client", "DREClient"),
        "discovery": ("legalize.fetcher.pt.discovery", "DREDiscovery"),
        "text_parser": ("legalize.fetcher.pt.parser", "DRETextParser"),
        "metadata_parser": ("legalize.fetcher.pt.parser", "DREMetadataParser"),
    },
    "ro": {
        "client": ("legalize.fetcher.ro.client", "RoClient"),
        "discovery": ("legalize.fetcher.ro.discovery", "RoDiscovery"),
        "text_parser": ("legalize.fetcher.ro.parser", "RoTextParser"),
        "metadata_parser": ("legalize.fetcher.ro.parser", "RoMetadataParser"),
    },
    "uy": {
        "client": ("legalize.fetcher.uy.client", "IMPOClient"),
        "discovery": ("legalize.fetcher.uy.discovery", "IMPODiscovery"),
        "text_parser": ("legalize.fetcher.uy.parser", "IMPOTextParser"),
        "metadata_parser": ("legalize.fetcher.uy.parser", "IMPOMetadataParser"),
    },
    "lv": {
        "client": ("legalize.fetcher.lv.client", "LikumiClient"),
        "discovery": ("legalize.fetcher.lv.discovery", "LikumiDiscovery"),
        "text_parser": ("legalize.fetcher.lv.parser", "LikumiTextParser"),
        "metadata_parser": ("legalize.fetcher.lv.parser", "LikumiMetadataParser"),
    },
    "pl": {
        "client": ("legalize.fetcher.pl.client", "EliClient"),
        "discovery": ("legalize.fetcher.pl.discovery", "EliDiscovery"),
        "text_parser": ("legalize.fetcher.pl.parser", "EliTextParser"),
        "metadata_parser": ("legalize.fetcher.pl.parser", "EliMetadataParser"),
    },
    "gr": {
        "client": ("legalize.fetcher.gr.client", "GreekClient"),
        "discovery": ("legalize.fetcher.gr.discovery", "GreekDiscovery"),
        "text_parser": ("legalize.fetcher.gr.parser", "GreekTextParser"),
        "metadata_parser": ("legalize.fetcher.gr.parser", "GreekMetadataParser"),
    },
    "it": {
        "client": ("legalize.fetcher.it.client", "NormattivaClient"),
        "discovery": ("legalize.fetcher.it.discovery", "NormattivaDiscovery"),
        "text_parser": ("legalize.fetcher.it.parser", "NormattivaTextParser"),
        "metadata_parser": ("legalize.fetcher.it.parser", "NormattivaMetadataParser"),
    },
    "nl": {
        "client": ("legalize.fetcher.nl.client", "BWBClient"),
        "discovery": ("legalize.fetcher.nl.discovery", "BWBDiscovery"),
        "text_parser": ("legalize.fetcher.nl.parser", "BWBTextParser"),
        "metadata_parser": ("legalize.fetcher.nl.parser", "BWBMetadataParser"),
    },
    "no": {
        "client": ("legalize.fetcher.no.client", "LovdataClient"),
        "discovery": ("legalize.fetcher.no.discovery", "LovdataDiscovery"),
        "text_parser": ("legalize.fetcher.no.parser", "LovdataTextParser"),
        "metadata_parser": ("legalize.fetcher.no.parser", "LovdataMetadataParser"),
    },
    "be": {
        "client": ("legalize.fetcher.be.client", "JustelClient"),
        "discovery": ("legalize.fetcher.be.discovery", "JustelDiscovery"),
        "text_parser": ("legalize.fetcher.be.parser", "JustelTextParser"),
        "metadata_parser": ("legalize.fetcher.be.parser", "JustelMetadataParser"),
    },
    "cz": {
        "client": ("legalize.fetcher.cz.client", "ESbirkaClient"),
        "discovery": ("legalize.fetcher.cz.discovery", "ESbirkaDiscovery"),
        "text_parser": ("legalize.fetcher.cz.parser", "ESbirkaTextParser"),
        "metadata_parser": ("legalize.fetcher.cz.parser", "ESbirkaMetadataParser"),
    },
    "fi": {
        "client": ("legalize.fetcher.fi.client", "FinlexClient"),
        "discovery": ("legalize.fetcher.fi.discovery", "FinlexDiscovery"),
        "text_parser": ("legalize.fetcher.fi.parser", "FinlexTextParser"),
        "metadata_parser": ("legalize.fetcher.fi.parser", "FinlexMetadataParser"),
    },
    "ie": {
        "client": ("legalize.fetcher.ie.client", "ISBClient"),
        "discovery": ("legalize.fetcher.ie.discovery", "ISBDiscovery"),
        "text_parser": ("legalize.fetcher.ie.parser", "ISBTextParser"),
        "metadata_parser": ("legalize.fetcher.ie.parser", "ISBMetadataParser"),
    },
    "ua": {
        "client": ("legalize.fetcher.ua.client", "RadaClient"),
        "discovery": ("legalize.fetcher.ua.discovery", "RadaDiscovery"),
        "text_parser": ("legalize.fetcher.ua.parser", "RadaTextParser"),
        "metadata_parser": ("legalize.fetcher.ua.parser", "RadaMetadataParser"),
    },
    "dk": {
        "client": ("legalize.fetcher.dk.client", "RetsinformationClient"),
        "discovery": ("legalize.fetcher.dk.discovery", "RetsinformationDiscovery"),
        "text_parser": ("legalize.fetcher.dk.parser", "DanishTextParser"),
        "metadata_parser": ("legalize.fetcher.dk.parser", "DanishMetadataParser"),
    },
    "sk": {
        "client": ("legalize.fetcher.sk.client", "SlovLexClient"),
        "discovery": ("legalize.fetcher.sk.discovery", "SlovLexDiscovery"),
        "text_parser": ("legalize.fetcher.sk.parser", "SlovLexTextParser"),
        "metadata_parser": ("legalize.fetcher.sk.parser", "SlovLexMetadataParser"),
    },
    "eu": {
        "client": ("legalize.fetcher.eu.client", "EURLexClient"),
        "discovery": ("legalize.fetcher.eu.discovery", "EURLexDiscovery"),
        "text_parser": ("legalize.fetcher.eu.parser", "EURLexTextParser"),
        "metadata_parser": ("legalize.fetcher.eu.parser", "EURLexMetadataParser"),
    },
    "li": {
        "client": ("legalize.fetcher.li.client", "LilexClient"),
        "discovery": ("legalize.fetcher.li.discovery", "LilexDiscovery"),
        "text_parser": ("legalize.fetcher.li.parser", "LilexTextParser"),
        "metadata_parser": ("legalize.fetcher.li.parser", "LilexMetadataParser"),
    },
    "ch": {
        "client": ("legalize.fetcher.ch.client", "FedlexClient"),
        "discovery": ("legalize.fetcher.ch.discovery", "FedlexDiscovery"),
        "text_parser": ("legalize.fetcher.ch.parser", "FedlexTextParser"),
        "metadata_parser": ("legalize.fetcher.ch.parser", "FedlexMetadataParser"),
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
