"""Legislative client for China's National Database of Laws and Regulations (flk.npc.gov.cn)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://flk.npc.gov.cn"
_DEFAULT_HEADERS = {
    "Referer": "https://flk.npc.gov.cn/",
    "Accept": "application/json, text/plain, */*",
}


class CNClient(HttpClient):
    """HTTP client for China's official legislation portal (flk.npc.gov.cn)."""

    @classmethod
    def create(cls, country_config: CountryConfig) -> CNClient:
        """Create a CNClient instance from configuration."""
        source = country_config.source or {}
        base_url = source.get("base_url", _DEFAULT_BASE_URL)
        rps = country_config.requests_per_second if country_config.requests_per_second is not None else 3.0
        return cls(base_url=base_url, requests_per_second=rps)

    def __init__(
        self,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        requests_per_second: float = 3.0,
        request_timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        super().__init__(
            base_url=base_url,
            requests_per_second=requests_per_second,
            request_timeout=request_timeout,
            max_retries=max_retries,
            extra_headers=_DEFAULT_HEADERS,
        )

    def get_text(self, norm_id: str) -> bytes:
        """Fetch the full structured details and text of a norm by its identifier (bbbs)."""
        url = f"{self._base_url}/law-search/search/flfgDetails"
        resp = self._request("GET", url, params={"bbbs": norm_id})
        return resp.content

    def get_metadata(self, norm_id: str) -> bytes:
        """Fetch metadata for a norm.

        Metadata and hierarchy are co-located in the flfgDetails response.
        """
        return self.get_text(norm_id)

    def search_list(
        self,
        *,
        page_num: int = 1,
        page_size: int = 50,
        search_content: str = "",
        search_type: int = 2,
        flfg_code_id: list[int] | None = None,
        zdjg_code_id: list[int] | None = None,
        gbrq_year: list[int] | None = None,
        sxx: list[int] | None = None,
        gbrq: list[str] | None = None,
        sxrq: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute a paginated query against /law-search/search/list."""
        url = f"{self._base_url}/law-search/search/list"
        payload = {
            "searchRange": 1,
            "sxrq": sxrq or [],
            "gbrq": gbrq or [],
            "searchType": search_type,
            "sxx": sxx or [],
            "gbrqYear": gbrq_year or [],
            "flfgCodeId": flfg_code_id or [],
            "zdjgCodeId": zdjg_code_id or [],
            "searchContent": search_content,
            "pageNum": page_num,
            "pageSize": page_size,
        }
        headers = {"Content-Type": "application/json;charset=UTF-8"}
        resp = self._request("POST", url, json=payload, headers=headers)
        return resp.json()
