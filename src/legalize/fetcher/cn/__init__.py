"""China (CN) -- legislative fetcher components for the National Database of Laws and Regulations."""

from legalize.fetcher.cn.client import CNClient
from legalize.fetcher.cn.discovery import CNDiscovery
from legalize.fetcher.cn.parser import CNMetadataParser, CNTextParser

__all__ = ["CNClient", "CNDiscovery", "CNMetadataParser", "CNTextParser"]
