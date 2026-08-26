"""Lithuania data.gov.lt Spinta API client.

Single source: https://get.data.gov.lt (Spinta API, UAPI spec)
All data (metadata + full text via tekstas_lt) comes from data.gov.lt.
e-tar.lt is only used for source URLs, not for fetching.
License: Open data (Creative Commons)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

DEFAULT_API_URL = "https://get.data.gov.lt"
DEFAULT_DATASET = "datasets/gov/lrsk/teises_aktai/Dokumentas"
DEFAULT_SUVESTINE_DATASET = "datasets/gov/lrsk/teises_aktai/Suvestine"

# Fields needed for metadata
_META_FIELDS = (
    "dokumento_id,pavadinimas,alt_pavadinimas,rusis,galioj_busena,"
    "priimtas,isigalioja,negalioja,priemusi_inst,nuoroda,tar_kodas,pakeista,"
    "parengusi_inst,atv_dok_nr,paskelbta_tar,dok_grupe,es_teises_aktas,"
    "ratifikuota,patvirtinta,ar_nacionalinis,isigal_sal_lt,dok_busena"
)

# Fields needed for discovery
_DISCOVERY_FIELDS = "dokumento_id,rusis,galioj_busena,priimtas,pavadinimas"


class TARClient(HttpClient):
    """HTTP client for Lithuanian legislation via data.gov.lt Spinta API.

    Single-source: both metadata and full text (tekstas_lt field)
    come from the same API. e-tar.lt has Cloudflare protection and
    is not used for fetching.
    """

    @classmethod
    def create(cls, country_config: CountryConfig) -> TARClient:
        """Create TARClient from CountryConfig."""
        source = country_config.source or {}
        return cls(
            api_url=source.get("api_url", DEFAULT_API_URL),
            dataset=source.get("dataset", DEFAULT_DATASET),
            suvestine_dataset=source.get("suvestine_dataset", DEFAULT_SUVESTINE_DATASET),
            request_timeout=source.get("request_timeout", 30),
            max_retries=source.get("max_retries", 5),
            requests_per_second=source.get("requests_per_second", 2.0),
        )

    def __init__(
        self,
        api_url: str = DEFAULT_API_URL,
        dataset: str = DEFAULT_DATASET,
        suvestine_dataset: str = DEFAULT_SUVESTINE_DATASET,
        **kwargs,
    ) -> None:
        super().__init__(base_url=api_url, **kwargs)
        self._dataset = dataset
        self._suvestine_dataset = suvestine_dataset

    def get_text(self, norm_id: str) -> bytes:
        """Fetch full text from data.gov.lt via the tekstas_lt field."""
        url = (
            f"{self._base_url}/{self._dataset}"
            f'?dokumento_id="{norm_id}"&select(tekstas_lt,priimtas)&limit(1)'
        )
        return self._get(url)

    def get_metadata(self, norm_id: str) -> bytes:
        """Fetch metadata JSON from data.gov.lt Spinta API."""
        url = (
            f"{self._base_url}/{self._dataset}"
            f'?dokumento_id="{norm_id}"&select({_META_FIELDS})&limit(1)'
        )
        return self._get(url)

    def get_suvestine(self, norm_id: str) -> bytes:
        """Fetch all historical versions for a norm from the Suvestine table.

        Two-phase approach to avoid timeouts on large laws:
        1. List all version IDs + dates (lightweight, no text)
        2. Fetch each version's text individually

        Returns JSON with _data[] containing suvestines_id, galioja_nuo,
        galioja_iki, and tekstas_lt for each version, sorted chronologically.
        """
        import json

        # Phase 1: list all versions (no text — lightweight)
        _list_fields = "suvestines_id,galioja_nuo,galioja_iki"
        versions: list[dict] = []
        cursor: str | None = None

        while True:
            url = (
                f"{self._base_url}/{self._suvestine_dataset}"
                f'?dokumento_id="{norm_id}"'
                f"&select({_list_fields})&sort(galioja_nuo)&limit(500)"
            )
            if cursor:
                url += f'&page("{cursor}")'

            raw = self._get(url)
            data = json.loads(raw)
            items = data.get("_data", [])
            versions.extend(items)

            page_info = data.get("_page", {})
            cursor = page_info.get("next") if isinstance(page_info, dict) else None
            if not cursor or len(items) < 500:
                break

        if not versions:
            return json.dumps({"_data": []}).encode("utf-8")

        # Phase 2: fetch text for each version individually
        for v in versions:
            sid = v["suvestines_id"]
            text_url = (
                f"{self._base_url}/{self._suvestine_dataset}"
                f'?dokumento_id="{norm_id}"&suvestines_id="{sid}"'
                f"&select(tekstas_lt)&limit(1)"
            )
            text_raw = self._get(text_url)
            text_data = json.loads(text_raw)
            text_items = text_data.get("_data", [])
            v["tekstas_lt"] = text_items[0].get("tekstas_lt", "") if text_items else ""

        return json.dumps({"_data": versions}).encode("utf-8")

    def get_page(self, page_size: int = 100, cursor: str | None = None) -> bytes:
        """Fetch a page of documents from the Spinta API."""
        url = (
            f"{self._base_url}/{self._dataset}"
            f"?select({_DISCOVERY_FIELDS})&sort(dokumento_id)&limit({page_size})"
        )
        if cursor:
            url += f'&page("{cursor}")'
        return self._get(url)
