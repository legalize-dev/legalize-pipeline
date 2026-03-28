"""Abstract base for legislative API clients and norm discovery."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import date
from typing import Any

from legalize.models import NormaMetadata


class LegislativeClient(ABC):
    """Base class for country-specific legislative API clients.

    Each country implements its own client with endpoints for:
    - Fetching consolidated text (XML/HTML)
    - Fetching metadata
    - Rate limiting and caching
    """

    @abstractmethod
    def get_texto(self, norm_id: str) -> bytes:
        """Fetch the consolidated text of a norm (XML or HTML)."""

    @abstractmethod
    def get_metadatos(self, norm_id: str) -> bytes:
        """Fetch metadata for a norm."""

    @abstractmethod
    def close(self) -> None:
        """Clean up resources."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class NormDiscovery(ABC):
    """Base class for discovering norms in a country's catalog.

    Each country publishes legislation differently:
    - Spain: daily BOE sumario XML
    - France: LEGI XML dumps with versioning
    - UK: Atom publication feed
    - Germany: static XML with HTTP header change detection
    """

    @abstractmethod
    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Discover all norm IDs in the catalog."""

    @abstractmethod
    def discover_daily(self, client: LegislativeClient, target_date: date, **kwargs) -> Iterator[str]:
        """Discover norms published/updated on a specific date."""


class TextParser(ABC):
    """Base class for parsing consolidated text into structured blocks.

    Each country's XML/HTML format is different, but the output
    is always a list of Bloque objects with version history.
    """

    @abstractmethod
    def parse_texto(self, data: bytes) -> list[Any]:
        """Parse consolidated text into a list of Bloque objects."""

    @abstractmethod
    def extract_reforms(self, data: bytes) -> list[Any]:
        """Extract reform timeline from consolidated text."""


class MetadataParser(ABC):
    """Base class for parsing norm metadata.

    Each country has different metadata fields, rank hierarchies,
    and status flags, but the output is always NormaMetadata.
    """

    @abstractmethod
    def parse(self, data: bytes, norm_id: str) -> NormaMetadata:
        """Parse raw metadata into NormaMetadata."""
