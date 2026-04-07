"""Likumi.lv HTTP client (Latvia).

The likumi.lv portal has no REST API. Each law is a single HTML page at
/ta/id/{numeric_id} that contains both the consolidated text and metadata.

robots.txt directives (validated 2026-04-07):
- Crawl-delay: 1 (1 request per second)
- Sitemap: https://likumi.lv/sitemap-index.xml
- Disallow: /*/redakcijas-datums/  (historical versions are NOT scrapable)
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

DEFAULT_BASE_URL = "https://likumi.lv"


class LikumiClient(HttpClient):
    """HTTP client for Latvian legislation via likumi.lv HTML scraping.

    Single-source: both metadata and full text come from the same HTML page
    at /ta/id/{norm_id}. Parse once, extract both.
    """

    @classmethod
    def create(cls, country_config: CountryConfig) -> LikumiClient:
        """Create LikumiClient from CountryConfig."""
        source = country_config.source or {}
        return cls(
            base_url=source.get("base_url", DEFAULT_BASE_URL),
            request_timeout=source.get("request_timeout", 30),
            max_retries=source.get("max_retries", 5),
            requests_per_second=source.get("requests_per_second", 1.0),
        )

    def get_text(self, norm_id: str) -> bytes:
        """Fetch the full HTML page for a law (contains text + metadata)."""
        return self._get(f"{self._base_url}/ta/id/{norm_id}")

    def get_metadata(self, norm_id: str) -> bytes:
        """Same as get_text — metadata is in the same HTML page."""
        return self.get_text(norm_id)

    def get_sitemap_index(self) -> bytes:
        """Fetch the sitemap index XML listing all sub-sitemaps."""
        return self._get(f"{self._base_url}/sitemap-index.xml")

    def get_sitemap(self, sitemap_url: str) -> bytes:
        """Fetch a specific sitemap XML file (sitemap-1.xml or sitemap-2.xml)."""
        return self._get(sitemap_url)

    def get_jaunakie_page(self, target_date: date) -> bytes:
        """Fetch the 'newest' page listing laws that entered into force on a date."""
        url = (
            f"{self._base_url}/ta/jaunakie/stajas-speka/"
            f"{target_date.year}/{target_date.month:02d}/{target_date.day:02d}/"
        )
        return self._get(url)
