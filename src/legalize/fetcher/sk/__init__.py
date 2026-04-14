"""Slovakia (SK) — legislative fetcher for Slov-Lex / e-Zbierka zákonov."""

from legalize.fetcher.sk.client import SlovLexClient
from legalize.fetcher.sk.discovery import SlovLexDiscovery
from legalize.fetcher.sk.parser import SlovLexMetadataParser, SlovLexTextParser

__all__ = ["SlovLexClient", "SlovLexDiscovery", "SlovLexTextParser", "SlovLexMetadataParser"]
