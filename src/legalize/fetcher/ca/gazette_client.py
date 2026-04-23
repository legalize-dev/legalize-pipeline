"""Fetch Canada Gazette Part III PDFs from gazette.gc.ca.

Scope for v1: 1998-2000 (3 years). The URL pattern on ``gazette.gc.ca``
is deterministic:

    https://gazette.gc.ca/rp-pr/p3/{YEAR}/g3-{VOL:03d}{ISSUE:02d}.pdf

where ``VOL = YEAR - 1977`` and ``ISSUE`` is a per-year serial that we
discover by parsing the year's HTML index page
(``/rp-pr/p3/{YEAR}/index-eng.html``) once per year. Pre-1998 issues
live on the Library and Archives Canada archive and require a separate
scraper (deferred — see RESEARCH-CA-HISTORY.md).

Downloads are cached on disk at
``{data_dir}/gazette-pdf/{YEAR}/g3-{VOL:03d}{ISSUE:02d}.pdf`` and are
idempotent across re-runs.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


GAZETTE_BASE = "https://gazette.gc.ca"
INDEX_URL_TEMPLATE = GAZETTE_BASE + "/rp-pr/p3/{year}/index-eng.html"
PDF_URL_TEMPLATE = GAZETTE_BASE + "/rp-pr/p3/{year}/g3-{vol:03d}{issue:02d}.pdf"
PDF_FILENAME_TEMPLATE = "g3-{vol:03d}{issue:02d}.pdf"

# Part III was separated from the main Gazette in December 1974; volume 1
# of Part III starts in 1978 in practice (Vol 1 = 1978). For the
# gazette.gc.ca archive the earliest available year is 1998 = Vol 21.
DEFAULT_FIRST_YEAR = 1998
DEFAULT_LAST_YEAR = 2000
_VOLUME_BASE_YEAR = 1977  # Vol 1 = 1978, so year - 1977 = volume


PDF_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']*g3-\d{5}\.pdf)["']""", re.IGNORECASE)


class GazetteClient:
    """Downloader + local cache for Canada Gazette Part III PDFs."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        sleep_between_requests: float = 1.0,
        timeout: int = 60,
        session: requests.Session | None = None,
    ) -> None:
        self._cache_root = Path(cache_dir) / "gazette-pdf"
        self._sleep = sleep_between_requests
        self._timeout = timeout
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "legalize-pipeline/1.0 (+https://legalize.dev)",
                "Accept": "text/html,application/xhtml+xml,application/pdf",
            }
        )

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def issues_for_year(self, year: int) -> list[int]:
        """Return the list of issue numbers published in ``year``.

        Parses the year's HTML index page and extracts issue numbers from
        PDF hrefs. The result is sorted ascending.
        """
        url = INDEX_URL_TEMPLATE.format(year=year)
        try:
            resp = self._get(url)
        except requests.RequestException as exc:
            logger.warning("Gazette index fetch failed for %d: %s", year, exc)
            return []

        issues: set[int] = set()
        for m in PDF_HREF_RE.finditer(resp.text):
            filename = m.group(1).rsplit("/", 1)[-1]
            # Expected filename: g3-{VOL:03d}{ISSUE:02d}.pdf (5 digits total).
            # Newest editions (Vol 43+) use 3-digit volume + 2-digit issue.
            # Older (Vol 21-42) also match because we pad leading zeros.
            m2 = re.fullmatch(r"g3-(\d{3})(\d{2})\.pdf", filename)
            if not m2:
                continue
            try:
                issue = int(m2.group(2))
            except ValueError:
                continue
            if 1 <= issue <= 99:
                issues.add(issue)
        return sorted(issues)

    def fetch_pdf(self, year: int, issue: int) -> Path | None:
        """Download one issue's PDF if not already cached; return the path.

        Returns ``None`` on a clean 404 (issue doesn't exist) so callers
        can iterate through guesses without raising.
        """
        vol = year - _VOLUME_BASE_YEAR
        filename = PDF_FILENAME_TEMPLATE.format(vol=vol, issue=issue)
        year_dir = self._cache_root / str(year)
        cache_path = year_dir / filename

        if cache_path.exists() and cache_path.stat().st_size > 1024:
            return cache_path

        url = PDF_URL_TEMPLATE.format(year=year, vol=vol, issue=issue)
        logger.info("Downloading %s", url)
        try:
            resp = self._get(url, stream=False)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            raise
        except requests.RequestException as exc:
            logger.warning("Download failed for %s: %s", url, exc)
            return None

        # Sanity-check the payload is a PDF (starts with %PDF- magic).
        body = resp.content
        if not body.startswith(b"%PDF-"):
            logger.warning("%s returned non-PDF payload (%d bytes)", url, len(body))
            return None

        year_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(body)
        return cache_path

    def fetch_year(self, year: int) -> list[Path]:
        """Download every issue of ``year`` into the local cache.

        Returns the list of successfully-cached PDF paths.
        """
        issues = self.issues_for_year(year)
        if not issues:
            logger.info("No issues discovered for year %d", year)
            return []
        out: list[Path] = []
        for issue in issues:
            path = self.fetch_pdf(year, issue)
            if path is not None:
                out.append(path)
        return out

    def fetch_range(
        self,
        first_year: int = DEFAULT_FIRST_YEAR,
        last_year: int = DEFAULT_LAST_YEAR,
    ) -> list[Path]:
        """Fetch every issue in the year range (inclusive)."""
        out: list[Path] = []
        for year in range(first_year, last_year + 1):
            out.extend(self.fetch_year(year))
        return out

    # -------------------------------------------------------------------------
    # Internals
    # -------------------------------------------------------------------------

    def _get(self, url: str, *, stream: bool = False) -> requests.Response:
        resp = self._session.get(url, timeout=self._timeout, stream=stream)
        if self._sleep > 0:
            time.sleep(self._sleep)
        if resp.status_code in (429, 503):
            time.sleep(self._sleep * 10)
            resp = self._session.get(url, timeout=self._timeout, stream=stream)
            if self._sleep > 0:
                time.sleep(self._sleep)
        resp.raise_for_status()
        return resp
