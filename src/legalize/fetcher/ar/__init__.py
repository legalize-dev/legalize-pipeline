"""Argentina (AR) -- legislative fetcher for InfoLEG (Ministerio de Justicia / SAIJ).

Discovery: monthly CSV catalog downloaded from datos.jus.gob.ar.
Per-norm text: legacy HTML host servicios.infoleg.gob.ar (windows-1252).
Reform reconstruction: InfoLEG only publishes the current consolidated text, so
every historical version is rebuilt by parsing each modificatoria's own text for
"Sustitúyese..." patterns and replaying them in date order. Validated in a POC on
2026-04-11; the algorithm, its assumptions and its failure modes are documented in
:mod:`legalize.fetcher.ar.reforms` and :mod:`legalize.fetcher.ar.reconstructor`.
"""

from legalize.fetcher.ar.client import InfoLEGClient
from legalize.fetcher.ar.discovery import InfoLEGDiscovery
from legalize.fetcher.ar.parser import InfoLEGMetadataParser, InfoLEGTextParser

__all__ = [
    "InfoLEGClient",
    "InfoLEGDiscovery",
    "InfoLEGTextParser",
    "InfoLEGMetadataParser",
]
