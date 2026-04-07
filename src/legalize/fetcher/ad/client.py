"""Andorra HTTP client -- fetches JSON data from GitHub.

Data source: https://github.com/ericrisco/legalize-ad
Format: JSON files in data/ directory, one per law.
The JSON follows the legalize-pipeline storage.py format.

The repo is maintained independently. When Andorran laws change,
the maintainer regenerates the JSON files and pushes to GitHub.
This client fetches them via raw.githubusercontent.com.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

_DEFAULT_BASE = (
    "https://raw.githubusercontent.com/ericrisco/legalize-ad/main/data"
)


class ADClient(HttpClient):
    """HTTP client for Andorran legislation JSON files on GitHub."""

    @classmethod
    def create(cls, country_config: CountryConfig) -> ADClient:
        source = country_config.source or {}
        return cls(
            base_url=source.get("base_url", _DEFAULT_BASE),
            requests_per_second=source.get("requests_per_second", 5.0),
        )

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE,
        requests_per_second: float = 5.0,
    ) -> None:
        super().__init__(
            base_url=base_url,
            requests_per_second=requests_per_second,
            max_retries=3,
            request_timeout=30,
        )

    def get_text(self, norm_id: str) -> bytes:
        """Fetch the JSON for a law. Text and metadata are in the same file."""
        url = f"{self._base_url}/{norm_id}.json"
        return self._get(url)

    def get_metadata(self, norm_id: str) -> bytes:
        """Metadata is embedded in the JSON, same file as text."""
        return self.get_text(norm_id)

    def get_index(self) -> bytes:
        """Fetch the index.json listing all available laws."""
        url = f"{self._base_url}/index.json"
        return self._get(url)
