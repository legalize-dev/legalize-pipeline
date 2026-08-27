"""Justel HTTP client (Belgium).

Justel has no REST API. Each law is a single HTML page at the ELI URL:

    https://www.ejustice.just.fgov.be/eli/{dt}/{yyyy}/{mm}/{dd}/{numac}/justel

For discovery, year-level listing pages at /eli/{dt}/{yyyy} return an HTML
table of every document of that type published in that year.

For historical versions, Justel exposes each archived version at:

    cgi_loi/article.pl?language=fr&arch={NNN}&lg_txt=fr&numac_search={NUMAC}
    &cn_search={CN_SEARCH}&caller=eli&view_numac={VIEW_NUMAC}

Where {NNN} is a zero-padded 3-digit version number (001..archived_versions)
and {CN_SEARCH}/{VIEW_NUMAC} come from the main page's metadata. The newest
archive page includes a sidebar listing every older version with its end
date, amending law and affected articles -- so one request to arch=N
recovers the full timeline without fetching every page first.

robots.txt disallows /eli/ but no Crawl-delay is set. The data is CC0-licensed
via data.gov.be, so we scrape politely with a descriptive User-Agent and a
conservative 1 req/s default.

Justel serves Content-Type: text/html; charset=ISO-8859-1. Consumers must
decode the bytes explicitly as Latin-1 (see parser.py).
"""

from __future__ import annotations

import base64
import json
import logging
import re
from datetime import date
from typing import TYPE_CHECKING

from lxml import html as lxml_html

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://www.ejustice.just.fgov.be"

# The URL pattern requires a delimiter before 'arch=' so we do not match
# 'numac_search=' (which contains the substring 'arch=' in 'se-arch=').
_CN_SEARCH_RE = re.compile(r"[?&]cn_search=(\d+)")
_VIEW_NUMAC_RE = re.compile(r"[?&]view_numac=([^&\"'<>]+)")
_ARCH_RE = re.compile(r"[?&]arch=0*(\d+)")

# Document types supported by Justel's ELI namespace.
# v1 scope: primary legislation only (constitution + loi + decret + ordonnance).
# arrete (secondary legislation, ~150K texts) is deferred to v2.
DOCUMENT_TYPES: tuple[str, ...] = (
    "constitution",
    "loi",
    "decret",
    "ordonnance",
)


class JustelClient(HttpClient):
    """HTTP client for Belgian consolidated legislation via Justel HTML scraping.

    Single-source: metadata and full text come from the same HTML page.
    Each norm_id is encoded as "{dt}:{yyyy}:{mm}:{dd}:{numac}" so the client
    can build the correct ELI URL without a separate lookup.
    """

    @classmethod
    def create(cls, country_config: CountryConfig) -> JustelClient:
        """Create JustelClient from CountryConfig."""
        source = country_config.source or {}
        return cls(
            base_url=source.get("base_url", DEFAULT_BASE_URL),
            request_timeout=source.get("request_timeout", 30),
            max_retries=source.get("max_retries", 5),
            requests_per_second=source.get("requests_per_second", 1.0),
        )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Tiny single-entry cache: the pipeline fetches the main /justel
        # page three times per law (once as metadata, once as text, once
        # inside get_suvestine). Caching the most recent URL avoids two
        # redundant HTTP round-trips per law -- worth ~30% of the bootstrap
        # time for a 40K-law source.
        self._cached_url: str | None = None
        self._cached_bytes: bytes | None = None

    def _cached_get(self, url: str) -> bytes:
        """GET via the single-entry cache, bypassing on cache miss."""
        if self._cached_url == url and self._cached_bytes is not None:
            return self._cached_bytes
        data = self._get(url)
        self._cached_url = url
        self._cached_bytes = data
        return data

    # ----- URL helpers -----

    @staticmethod
    def parse_norm_id(norm_id: str) -> tuple[str, str, str, str, str]:
        """Decode a norm_id of the form 'dt:yyyy:mm:dd:numac'.

        Returns (dt, yyyy, mm, dd, numac).
        """
        parts = norm_id.split(":")
        if len(parts) != 5:
            raise ValueError(f"Invalid Justel norm_id {norm_id!r}: expected 'dt:yyyy:mm:dd:numac'")
        return parts[0], parts[1], parts[2], parts[3], parts[4]

    @staticmethod
    def numac_from_norm_id(norm_id: str) -> str:
        """Extract the NUMAC (the filesystem identifier) from a composite norm_id."""
        return JustelClient.parse_norm_id(norm_id)[4]

    def eli_url(self, norm_id: str, version: str = "justel") -> str:
        """Build the ELI URL for a composite norm_id."""
        dt, yyyy, mm, dd, numac = self.parse_norm_id(norm_id)
        return f"{self._base_url}/eli/{dt}/{yyyy}/{mm}/{dd}/{numac}/{version}"

    def listing_url(self, dt: str, year: int) -> str:
        """Build the year-level ELI listing URL for discovery."""
        return f"{self._base_url}/eli/{dt}/{year}"

    def summary_url(self) -> str:
        """URL for the 'recently consolidated' page used by daily discovery."""
        return f"{self._base_url}/cgi_loi/summary.pl?language=fr&type=cons&sort=date_upd"

    # ----- LegislativeClient contract -----

    def get_text(self, norm_id: str) -> bytes:
        """Fetch the HTML page of a consolidated law.

        Returns raw bytes. Decoding as ISO-8859-1 is the parser's responsibility.
        Routes through ``_cached_get`` so three consecutive calls to the
        same URL (``get_metadata`` → ``get_text`` → ``get_suvestine``) only
        hit the network once.
        """
        return self._cached_get(self.eli_url(norm_id, version="justel"))

    def get_metadata(self, norm_id: str) -> bytes:
        """Same as get_text -- metadata is in the same HTML page."""
        return self.get_text(norm_id)

    # ----- Discovery helpers -----

    def get_listing(self, dt: str, year: int) -> bytes:
        """Fetch the year-level listing HTML for a document type.

        Example: get_listing("loi", 2024) returns the HTML listing all federal
        laws promulgated in 2024.
        """
        return self._get(self.listing_url(dt, year))

    def get_daily_summary(self) -> bytes:
        """Fetch the 'recently consolidated' page for daily discovery."""
        return self._get(self.summary_url())

    # ----- Historical version walking -----

    def _archive_url(
        self,
        version_num: int,
        cn_search: str,
        numac_search: str,
        view_numac: str,
    ) -> str:
        """Build the cgi_loi archive URL for a specific archived version."""
        return (
            f"{self._base_url}/cgi_loi/article.pl"
            f"?language=fr&arch={version_num:03d}&lg_txt=fr&type=&sort="
            f"&numac_search={numac_search}&cn_search={cn_search}"
            f"&caller=eli&&view_numac={view_numac}"
        )

    def _extract_cn_search(self, main_html: bytes) -> tuple[str, str]:
        """Extract (cn_search, view_numac) from a main /justel page's HTML.

        Justel's ELI URLs use the NUMAC in the path, but the cgi_loi
        endpoints use a separate ``cn_search`` parameter and a ``view_numac``
        with suffixes like ``1994021730fr`` that encode the language. These
        two strings are embedded in every link on the main page.
        """
        text = main_html.decode("iso-8859-1", errors="replace")
        cn_match = _CN_SEARCH_RE.search(text)
        view_match = _VIEW_NUMAC_RE.search(text)
        cn_search = cn_match.group(1) if cn_match else ""
        view_numac = view_match.group(1) if view_match else ""
        return cn_search, view_numac

    def get_suvestine(self, norm_id: str) -> bytes:
        """Fetch the full historical version timeline for a Belgian norm.

        Named ``get_suvestine`` to match the pipeline hook that looks for
        ``hasattr(client, "get_suvestine")`` — the semantics are identical
        (one HTTP source, many historical versions, one reform per version).

        Flow:

        1. Fetch the main /justel page and read its metadata to find the
           ``archived_versions`` count and the ``cn_search``/``view_numac``
           query parameters the cgi_loi endpoint needs.
        2. Fetch the newest archive page (``arch={archived_versions}``),
           which contains a sidebar listing every older version with its
           end-of-validity date and amending-law reference. Parse the
           sidebar into a timeline.
        3. Fetch each archive page (``arch=1..N``) to grab its text body.
        4. Serialise the whole thing as a JSON blob with base64 HTML so
           ``parse_suvestine`` can reparse each version independently.

        Returns a JSON blob (bytes) of the form::

            {
                "norm_id": "constitution:1994:02:17:1994021048",
                "numac": "1994021048",
                "cn_search": "1994021730",
                "view_numac": "1994021730fr",
                "total_versions": 78,
                "main_text_b64": "…",            // the /justel page
                "versions": [
                    {
                        "version_num": 1,
                        "effective_date": "1994-02-17",
                        "end_date": "1996-04-29",
                        "amending_law_pub_date": null,
                        "affected_articles": [],
                        "text_b64": "…"
                    },
                    …
                ]
            }
        """
        # 1. Fetch the main page
        main_html = self.get_text(norm_id)

        # 2. Laws with zero archived versions are handled as single
        # snapshots — no need to hit the cgi_loi archive endpoint. This
        # is the normal case for newly-published laws and is NOT an
        # error.
        total_versions = _parse_archived_versions_count(main_html)
        if not total_versions:
            return _single_snapshot_blob(norm_id, main_html)

        cn_search, view_numac = self._extract_cn_search(main_html)
        if not cn_search or not view_numac:
            logger.warning(
                "Could not extract cn_search/view_numac for %s despite %d archived"
                " versions — falling back to snapshot",
                norm_id,
                total_versions,
            )
            return _single_snapshot_blob(norm_id, main_html)

        numac = self.numac_from_norm_id(norm_id)

        # 3. Fetch the newest archive page and parse its sidebar
        sidebar_html = self._get(self._archive_url(total_versions, cn_search, numac, view_numac))
        sidebar_entries = _parse_version_sidebar(sidebar_html, total_versions)
        if not sidebar_entries:
            logger.warning(
                "No sidebar entries found in archive page for %s — snapshot fallback",
                norm_id,
            )
            return _single_snapshot_blob(norm_id, main_html)

        # 4. Fetch every archive version's HTML, reusing the sidebar page
        # for its own version (arch=N). The sidebar page IS the text of
        # version N, so we cache it to avoid a duplicate fetch.
        version_html_cache: dict[int, bytes] = {total_versions: sidebar_html}
        fetched: list[dict] = []
        for entry in sidebar_entries:
            v_num = entry["version_num"]
            if v_num == total_versions:
                html_b = sidebar_html
            else:
                html_b = version_html_cache.get(v_num)
                if html_b is None:
                    try:
                        html_b = self._get(self._archive_url(v_num, cn_search, numac, view_numac))
                    except Exception as exc:
                        logger.warning(
                            "Failed to fetch %s archive %d: %s",
                            norm_id,
                            v_num,
                            exc,
                        )
                        continue
                    version_html_cache[v_num] = html_b
            fetched.append(
                {
                    "version_num": v_num,
                    "effective_date": entry["effective_date"],
                    "end_date": entry["end_date"],
                    "amending_law_pub_date": entry["amending_law_pub_date"],
                    "affected_articles": entry["affected_articles"],
                    "text_b64": base64.b64encode(html_b).decode("ascii"),
                }
            )

        blob = {
            "norm_id": norm_id,
            "numac": numac,
            "cn_search": cn_search,
            "view_numac": view_numac,
            "total_versions": total_versions,
            "main_text_b64": base64.b64encode(main_html).decode("ascii"),
            "versions": fetched,
        }
        return json.dumps(blob).encode("utf-8")


# ─────────────────────────────────────────────
# Helpers (module-level so tests can reach them)
# ─────────────────────────────────────────────


def _single_snapshot_blob(norm_id: str, main_html: bytes) -> bytes:
    """Build a suvestine blob for a law with no archived versions.

    Produces a one-entry timeline where the only version is the current
    consolidated text, dated at the main metadata's publication date.
    The parser can reparse this into the same (blocks, reforms) tuple
    it produces for multi-version laws.
    """
    blob = {
        "norm_id": norm_id,
        "numac": JustelClient.numac_from_norm_id(norm_id) if ":" in norm_id else norm_id,
        "cn_search": "",
        "view_numac": "",
        "total_versions": 1,
        "main_text_b64": base64.b64encode(main_html).decode("ascii"),
        "versions": [
            {
                "version_num": 1,
                "effective_date": None,  # parser fills from main metadata
                "end_date": None,
                "amending_law_pub_date": None,
                "affected_articles": [],
                "text_b64": base64.b64encode(main_html).decode("ascii"),
            }
        ],
    }
    return json.dumps(blob).encode("utf-8")


def _parse_archived_versions_count(main_html: bytes) -> int:
    """Extract the number of archived versions from a main /justel page.

    Justel renders this as
        <a href="…&arch=078&…">78 versions archivées</a>
    inside the metadata card (``div#list-title-1``). We scan every <a> in
    that card for an ``&arch=NNN`` parameter and return the highest NNN.
    """
    try:
        tree = lxml_html.fromstring(main_html, parser=lxml_html.HTMLParser(encoding="iso-8859-1"))
    except Exception:
        return 0
    links = tree.xpath('//div[@id="list-title-1"]//a')
    best = 0
    for a in links:
        href = a.get("href", "") or ""
        match = _ARCH_RE.search(href)
        if match:
            n = int(match.group(1))
            if n > best:
                best = n
    return best


def _parse_version_sidebar(archive_html: bytes, newest_version: int) -> list[dict]:
    """Parse the sidebar of an archive page into one dict per version.

    The sidebar lives inside ``div#list-title-sw_roi`` and contains one
    ``<p>`` block per archived version. Each block looks like::

        <p>Modifié par LOI du 24-10-2017 publié le 29-11-2017
          Art. 12
          En vigueur jusqu'au 09-12-2017   <a href="…arch=074…">Version archivée n° 074</a>
        </p>

    **Semantics to be careful with:** the ``<p>`` block labelled
    "Version archivée n° NNN" describes the reform that *replaced*
    version NNN, not the reform that *created* it. In other words, row
    NNN documents the transition from vNNN to v(NNN+1). The amending
    law, the "Art. modifié" list and the "En vigueur jusqu'au" date all
    belong to that transition.

    So for each version K in 1..newest_version we build one entry:

    - v1 is the original text (no amending law, effective date is the
      norm's publication date, filled in by the parser).
    - v(K+1) inherits the amending-law info from row K (the transition
      that created it) and starts on row K's "En vigueur jusqu'au" date.

    Returns a list of dicts, sorted by version_num ascending::

        {
            "version_num": int,
            "effective_date": str | None,       # ISO, None for v1
            "end_date": str | None,             # ISO, None for the newest version
            "amending_law_pub_date": str | None, # publication of the amending LOI/AR
            "affected_articles": list[str],
        }
    """
    import re as _re

    try:
        tree = lxml_html.fromstring(
            archive_html, parser=lxml_html.HTMLParser(encoding="iso-8859-1")
        )
    except Exception:
        return []

    nav_box = tree.xpath('//div[@id="list-title-sw_roi"]')
    if not nav_box:
        nav_box = [tree]

    # Parse every <p> row into a transition record indexed by the version
    # number it describes (which is the FROM side of the transition).
    transitions: dict[int, dict] = {}
    for p in nav_box[0].xpath('.//p[contains(., "Version archiv")]'):
        text = " ".join(p.itertext())

        vnum_match = _re.search(r"Version archiv[^\d]*(\d+)", text)
        if not vnum_match:
            continue
        from_version = int(vnum_match.group(1))

        pub_match = _re.search(r"publi[eé] le[\s]*([0-9]{2}-[0-9]{2}-[0-9]{4})", text)
        amend_pub = _iso_from_dmy(pub_match.group(1)) if pub_match else None

        end_match = _re.search(
            r"En vigueur jusqu'au[\s]*([0-9]{2}-[0-9]{2}-[0-9]{4}|ind[eé]termin[eé]e)",
            text,
        )
        end_date: str | None = None
        if end_match:
            raw = end_match.group(1)
            if not raw.lower().startswith("ind"):
                end_date = _iso_from_dmy(raw)

        # Affected articles: "Art. 12" or "Art. modifié 5, 6bis, 7"
        art_match = _re.search(
            r"Art\.\s*(?:modifi[eé]\s*)?([0-9a-zA-Z°,\s-]+?)(?:<|En vigueur|$)",
            text,
        )
        affected: list[str] = []
        if art_match:
            raw = art_match.group(1).strip().rstrip(",")
            for token in raw.split(","):
                token = token.strip()
                if token and _re.match(r"^[0-9][0-9a-zA-Z°-]*$", token):
                    affected.append(token)

        transitions[from_version] = {
            "amending_law_pub_date": amend_pub,
            "end_date": end_date,
            "affected_articles": affected,
        }

    if not transitions and newest_version < 2:
        return []

    # Build one entry per version from 1 to newest_version.
    #
    # Date resolution rules, in order:
    # - v1 (original): effective_date is None; the parser fills it in from
    #   the main metadata's publication date.
    # - v(K+1): effective_date = row K's end_date ("En vigueur jusqu'au")
    #   when that date is present AND monotonic. Justel occasionally writes
    #   "indéterminée" for amendments whose entry-into-force is not yet
    #   fixed, and sometimes the sidebar is non-chronological when several
    #   amendments share an amending law — in both cases we fall back to
    #   the amending-law publication date, which is always present and
    #   almost always the right effective-date proxy.
    #
    # `_valid` is defined once, above the loop, and told the running date
    # explicitly. As a closure inside the loop it read `last_good_effective`
    # late, which was correct only because every call sat in the iteration
    # that defined it — one kept for later would have used the last version's
    # date without saying so.
    max_plausible = f"{date.today().year + 10}-12-31"

    def _valid(candidate: str | None, last_good: str | None) -> str | None:
        if not candidate:
            return None
        if candidate > max_plausible:
            return None  # sentinel like 2201-01-01
        if last_good is not None and candidate < last_good:
            return None
        return candidate

    entries: list[dict] = []
    last_good_effective: str | None = None
    for v in range(1, newest_version + 1):
        if v == 1:
            prior = None
        else:
            prior = transitions.get(v - 1)
        current = transitions.get(v)

        if prior is None:
            effective: str | None = None
        else:
            # Try end_date first, fall back to amending_law_pub_date, then
            # to the last known-good date. At each step, reject values that
            # would move the timeline backwards OR are sentinel dates that
            # Justel uses for "far future / indeterminate" (e.g. 01-01-2201).
            effective = (
                _valid(prior.get("end_date"), last_good_effective)
                or _valid(prior.get("amending_law_pub_date"), last_good_effective)
                or last_good_effective
            )

        if effective:
            last_good_effective = effective

        entries.append(
            {
                "version_num": v,
                "effective_date": effective,
                "end_date": current["end_date"] if current else None,
                "amending_law_pub_date": prior["amending_law_pub_date"] if prior else None,
                "affected_articles": list(prior["affected_articles"]) if prior else [],
            }
        )

    return entries


def _iso_from_dmy(text: str) -> str:
    """Convert 'DD-MM-YYYY' to 'YYYY-MM-DD'. Falls back to the original."""
    parts = text.split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return text
