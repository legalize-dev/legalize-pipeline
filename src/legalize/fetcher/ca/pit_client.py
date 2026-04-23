"""Justice Canada Point-in-Time (PIT) history client.

Justice Canada's own servers publish every consolidated snapshot of each
federal act and regulation going back to **2002-12-31**, directly from
their own site with no rate limiting or third-party dependencies. Each
act exposes:

- ``/{lang}/{category}/{id}/PITIndex.html`` — index of snapshot dates.
  Each link points to a dated directory containing the full document.
- ``/{lang}/{category}/{id}/{YYYYMMDD}/P1TT3xt3.html`` — the full
  consolidated HTML for that date range. (The leet-spelled filename is
  the site's own convention.)

Only HTML is published per-snapshot (no XML or PDF at historical dates),
so the suvestine pipeline treats ``pit-html`` entries with a dedicated
parser (:mod:`pit_parser`) while keeping the same downstream Version +
Reform shape as the XML sources.

Cache layout
------------

    {data_dir}/pit-html/{lang}/{category}/{id_safe}/{YYYYMMDD}.html.gz

Gzipped because each snapshot is 50-500 KB of HTML that compresses to a
fraction of that. Re-runs are idempotent — the cache is checked before
any HTTP request. A 956-act English bootstrap with ~50 snapshots per act
lands around 2-5 GB on disk; the cache is reusable across invocations
and survives country-repo deletions.

Rate limiting
-------------

Justice Canada's own server handles our load cleanly. We still cap at
``DEFAULT_RPS`` per client to be polite — a single worker pulling 100
snapshots/sec might draw attention even if the server doesn't complain.
With ``max_workers=8`` the effective fan-out is ~8 req/s which stays
well below the site's steady-state capacity.
"""

from __future__ import annotations

import base64
import gzip
import logging
import re
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


BASE_URL = "https://laws-lois.justice.gc.ca"
INDEX_URL_TEMPLATE = BASE_URL + "/{lang}/{category}/{id}/PITIndex.html"
SNAPSHOT_URL_TEMPLATE = BASE_URL + "/{lang}/{category}/{id}/{date}/P1TT3xt3.html"

DEFAULT_SLEEP_BETWEEN_REQUESTS = 0.1  # 10 req/s — site tolerates it
DEFAULT_TIMEOUT = 60

# PITIndex.html lists snapshots like:
# <li><a href='20200621/P1TT3xt3.html'>From 2020-06-21 to 2021-08-05</a></li>
# We only need the YYYYMMDD prefix on the href.
_PIT_LINK_RE = re.compile(
    r"href\s*=\s*['\"](?P<date>\d{8})/P1TT3xt3\.html['\"]",
    re.IGNORECASE,
)


class PITClient:
    """Reads Justice Canada per-date HTML snapshots from the official site.

    One instance per client/thread — stateless aside from the on-disk
    cache rooted at ``cache_dir``.
    """

    def __init__(
        self,
        cache_dir: Path,
        *,
        sleep_between_requests: float = DEFAULT_SLEEP_BETWEEN_REQUESTS,
        timeout: int = DEFAULT_TIMEOUT,
        session: requests.Session | None = None,
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._sleep = sleep_between_requests
        self._timeout = timeout
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "legalize-pipeline/1.0 (+https://legalize.dev)",
                "Accept": "text/html,application/xhtml+xml",
            }
        )

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def fetch_versions(self, norm_id: str) -> list[dict]:
        """Return every archived snapshot of ``norm_id``, oldest first.

        Each returned entry is shaped like the other suvestine sources
        (annual-statute, upstream-git), except it carries the raw HTML
        as ``body_html`` (base64-encoded) and a ``source_type`` of
        ``"pit-html"`` so the parser routes it to the HTML branch
        instead of ``_parse_root``::

            {
                "source_type": "pit-html",
                "source_id": "pit-20200621",
                "date": "2020-06-21",
                "body_html": "<base64 of the P1TT3xt3.html body>",
                "pit_url": "https://laws-lois.justice.gc.ca/...",
            }
        """
        lang, category, file_id = _parse_norm_id(norm_id)
        if lang not in ("eng", "fra"):
            return []

        try:
            dates = self._fetch_index(lang, category, file_id)
        except requests.RequestException as exc:
            logger.warning("PIT index fetch failed for %s: %s", norm_id, exc)
            return []

        if not dates:
            return []

        cache_root = self._cache_root_for(norm_id)
        cache_root.mkdir(parents=True, exist_ok=True)

        out: list[dict] = []
        for iso_date, yyyymmdd in dates:
            html_bytes = self._load_snapshot(cache_root, lang, category, file_id, yyyymmdd)
            if html_bytes is None:
                continue
            encoded = base64.b64encode(html_bytes).decode("ascii")
            # Release the raw bytes ASAP — on a 500 KB HTML snapshot the
            # base64 copy already weighs ~670 KB; keeping both doubles the
            # transient peak for no gain.
            del html_bytes

            out.append(
                {
                    "source_type": "pit-html",
                    "source_id": f"pit-{yyyymmdd}",
                    "date": iso_date,
                    "body_html": encoded,
                    "pit_url": SNAPSHOT_URL_TEMPLATE.format(
                        lang=lang, category=category, id=file_id, date=yyyymmdd
                    ),
                }
            )

        # Already oldest-first because the index is sorted — sort again for
        # robustness against future markup changes.
        out.sort(key=lambda v: v["date"])
        return out

    # -------------------------------------------------------------------------
    # Internals
    # -------------------------------------------------------------------------

    def _fetch_index(self, lang: str, category: str, file_id: str) -> list[tuple[str, str]]:
        """Return ``[(iso_date, yyyymmdd), …]`` for every snapshot listed.

        ``iso_date`` is ``YYYY-MM-DD`` (already formatted for the suvestine
        date key); ``yyyymmdd`` is the raw form the snapshot URL uses.
        """
        url = INDEX_URL_TEMPLATE.format(lang=lang, category=category, id=file_id)
        resp = self._get(url)
        if resp is None:
            return []
        text = resp.text

        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for m in _PIT_LINK_RE.finditer(text):
            yyyymmdd = m.group("date")
            if yyyymmdd in seen:
                continue
            seen.add(yyyymmdd)
            iso = f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
            out.append((iso, yyyymmdd))

        # PITIndex.html lists newest-first — reverse to oldest-first to match
        # the rest of the pipeline's ordering.
        out.reverse()
        return out

    def _load_snapshot(
        self,
        cache_root: Path,
        lang: str,
        category: str,
        file_id: str,
        yyyymmdd: str,
    ) -> bytes | None:
        """Return the HTML bytes for one snapshot, hitting cache before HTTP."""
        cache_path = cache_root / f"{yyyymmdd}.html.gz"
        if cache_path.exists():
            try:
                return gzip.decompress(cache_path.read_bytes())
            except (OSError, gzip.BadGzipFile) as exc:
                logger.warning("Invalid cache file %s (%s); redownloading", cache_path, exc)

        url = SNAPSHOT_URL_TEMPLATE.format(lang=lang, category=category, id=file_id, date=yyyymmdd)
        resp = self._get(url)
        if resp is None:
            return None
        body = resp.content
        # Sanity-check: should be a P1TT3xt3.html response. Malformed or
        # redirect-to-homepage responses are dropped silently.
        head = body[:200].lstrip().lower()
        if not head.startswith(b"<!doctype") and not head.startswith(b"<html"):
            logger.debug("PIT %s returned non-HTML (%d bytes); skipping", url, len(body))
            return None

        try:
            cache_path.write_bytes(gzip.compress(body))
        except OSError as exc:
            logger.warning("Failed to cache %s: %s", cache_path, exc)
        return body

    def _cache_root_for(self, norm_id: str) -> Path:
        """Directory holding all snapshots for one norm.

        Path shape::

            {cache_dir}/pit-html/{lang}/{category}/{id}
        """
        lang, category, file_id = _parse_norm_id(norm_id)
        safe_id = file_id.replace("/", "-")
        return self._cache_dir / "pit-html" / lang / category / safe_id

    def _get(self, url: str) -> requests.Response | None:
        """GET with a tiny sleep + one retry on 429/503.

        Returns ``None`` on any permanent failure so callers can skip the
        bad snapshot without losing the whole norm. Justice Canada's site
        is stable enough that retries are almost never needed, but the
        backoff keeps us polite if they ever rate-limit temporarily.
        """
        try:
            resp = self._session.get(url, timeout=self._timeout)
        except requests.RequestException as exc:
            logger.warning("PIT fetch failed for %s: %s", url, exc)
            return None
        if self._sleep > 0:
            time.sleep(self._sleep)
        if resp.status_code in (429, 503):
            time.sleep(self._sleep * 10)
            try:
                resp = self._session.get(url, timeout=self._timeout)
            except requests.RequestException as exc:
                logger.warning("PIT retry failed for %s: %s", url, exc)
                return None
            if self._sleep > 0:
                time.sleep(self._sleep)
        if resp.status_code >= 400:
            logger.debug("PIT %s returned %d; skipping", url, resp.status_code)
            return None
        return resp


def _parse_norm_id(norm_id: str) -> tuple[str, str, str]:
    parts = norm_id.split("/", 2)
    if len(parts) != 3:
        raise ValueError(f"Invalid CA norm_id: {norm_id!r}")
    return parts[0], parts[1], parts[2]
