"""legislation.gov.uk HTTP client.

One endpoint serves everything: CLML XML, Atom feeds, RDF, HTML. There is
no API key and no separate API host.

URL patterns used:

    Latest revised law    /{type}/{year}/{number}/data.xml
    As-enacted text       /{type}/{year}/{number}/enacted/data.xml
    Point-in-time         /{type}/{year}/{number}/{YYYY-MM-DD}/data.xml
    Per-year Atom feed    /{type}/{year}/data.feed?page={N}&results-count={R}
    Publication log       /update/data.feed?start-date={D}&end-date={D}
    Change timeline       /changes/affected/{type}/{year}/{number}/data.feed?...

robots.txt sets Crawl-delay: 5. We default to 1.0 req/s per worker; callers
can tune up if their workers run strictly sequentially.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import date
from typing import TYPE_CHECKING

import requests
from lxml import etree

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://www.legislation.gov.uk"

# Legislation type codes supported by the UK fetcher.
# Primary legislation (Acts/Measures):
#   ukpga, asp, asc, anaw, mwa, nia
# Secondary legislation (Statutory Instruments):
#   uksi, ssi, wsi, nisr, nisro
LEGISLATION_TYPES: tuple[str, ...] = (
    "ukpga",  # UK Public General Acts
    "asp",  # Acts of the Scottish Parliament
    "asc",  # Acts of Senedd Cymru (2020-)
    "anaw",  # Welsh Assembly Acts (2012-2020)
    "mwa",  # Welsh Assembly Measures (2008-2011)
    "nia",  # Acts of the Northern Ireland Assembly
    "uksi",  # UK Statutory Instruments
    "ssi",  # Scottish Statutory Instruments
    "wsi",  # Welsh Statutory Instruments
    "nisr",  # Northern Ireland Statutory Rules
    "nisro",  # Northern Ireland Statutory Rules and Orders (pre-devolution)
)

# Namespaces that appear in every CLML / feed response.
NS = {
    "leg": "http://www.legislation.gov.uk/namespaces/legislation",
    "ukm": "http://www.legislation.gov.uk/namespaces/metadata",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dct": "http://purl.org/dc/terms/",
    "atom": "http://www.w3.org/2005/Atom",
    "os": "http://a9.com/-/spec/opensearch/1.1/",
    "xhtml": "http://www.w3.org/1999/xhtml",
    "m": "http://www.w3.org/1998/Math/MathML",
}


def split_norm_id(norm_id: str) -> tuple[str, int, int]:
    """Decompose a UK norm_id into (type, year, number).

    Format: ``{type}-{year}-{number}`` (lowercase), e.g. ``ukpga-2018-12``.
    """
    parts = norm_id.split("-")
    if len(parts) != 3:
        raise ValueError(f"Invalid UK norm_id {norm_id!r}: expected 'type-year-number'")
    type_code, year_s, number_s = parts
    return type_code, int(year_s), int(number_s)


class LegislationGovUkClient(HttpClient):
    """HTTP client for legislation.gov.uk (CLML + Atom)."""

    @classmethod
    def create(cls, country_config: CountryConfig) -> LegislationGovUkClient:
        source = country_config.source or {}
        return cls(
            base_url=source.get("base_url", DEFAULT_BASE_URL),
            requests_per_second=source.get("requests_per_second", 1.0),
            request_timeout=source.get("request_timeout", 45),
            max_retries=source.get("max_retries", 4),
        )

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        requests_per_second: float = 1.0,
        request_timeout: int = 45,
        max_retries: int = 4,
    ) -> None:
        super().__init__(
            base_url=base_url,
            requests_per_second=requests_per_second,
            request_timeout=request_timeout,
            max_retries=max_retries,
        )

    # ─── URL builders ───────────────────────────────────────────

    def _law_url(self, norm_id: str, version: str = "") -> str:
        type_code, year, number = split_norm_id(norm_id)
        path = f"{self._base_url}/{type_code}/{year}/{number}"
        if version:
            path += f"/{version}"
        return f"{path}/data.xml"

    def _changes_url(self, norm_id: str, page: int = 1, results_count: int = 200) -> str:
        type_code, year, number = split_norm_id(norm_id)
        return (
            f"{self._base_url}/changes/affected/{type_code}/{year}/{number}/data.feed"
            f"?results-count={results_count}&page={page}"
        )

    def year_feed_url(self, type_code: str, year: int, page: int = 1) -> str:
        return f"{self._base_url}/{type_code}/{year}/data.feed?page={page}&results-count=100"

    def type_feed_url(self, type_code: str, page: int = 1) -> str:
        """Aggregate Atom feed for a single type code (all years, paged)."""
        return f"{self._base_url}/{type_code}/data.feed?page={page}&results-count=100"

    def update_feed_url(self, target_date: date) -> str:
        iso = target_date.isoformat()
        return (
            f"{self._base_url}/update/data.feed?start-date={iso}&end-date={iso}&results-count=200"
        )

    # ─── LegislativeClient contract ─────────────────────────────

    def get_text(self, norm_id: str, meta_data: bytes | None = None) -> bytes:
        """Fetch the latest revised CLML XML for a law.

        The pipeline calls ``get_metadata`` first and then ``get_text``; for
        UK both resolve to the same ``/data.xml`` so we accept the already-
        fetched ``meta_data`` and return it as-is. That saves one HTTP
        request per law across the whole bootstrap (~3,970 requests).
        """
        if meta_data is not None:
            return meta_data
        return self._get(self._law_url(norm_id))

    def get_metadata(self, norm_id: str) -> bytes:
        """Metadata is embedded in the same XML document."""
        return self._get(self._law_url(norm_id))

    # ─── UK-specific fetchers ───────────────────────────────────

    def get_enacted(self, norm_id: str) -> bytes:
        """Fetch the as-enacted (original, immutable) CLML XML."""
        return self._get(self._law_url(norm_id, "enacted"))

    def get_at_date(self, norm_id: str, target_date: date) -> bytes:
        """Fetch the point-in-time CLML XML for a specific effective date."""
        return self._get(self._law_url(norm_id, target_date.isoformat()))

    def get_changes_feed(self, norm_id: str, *, max_pages: int = 50) -> list[bytes]:
        """Fetch every page of the change timeline for a law.

        Returns a list of Atom feed byte strings (one per page). The caller
        parses them to extract <ukm:Effect> + <ukm:InForce Applied=true>
        records.
        """
        pages: list[bytes] = []
        for page in range(1, max_pages + 1):
            try:
                body = self._get(self._changes_url(norm_id, page=page))
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status == 404:
                    break
                raise
            pages.append(body)
            # Stop when the current page has fewer entries than the page size
            try:
                root = etree.fromstring(body)
                entries = root.findall(".//atom:entry", NS)
                if len(entries) < 100:
                    break
            except etree.XMLSyntaxError:
                break
        return pages

    def get_year_feed(self, type_code: str, year: int, page: int = 1) -> bytes:
        """Fetch a per-year Atom feed (discovery)."""
        return self._get(self.year_feed_url(type_code, year, page))

    def get_type_feed(self, type_code: str, page: int = 1) -> bytes:
        """Fetch the aggregate Atom feed for a type code."""
        return self._get(self.type_feed_url(type_code, page))

    def get_update_feed(self, target_date: date) -> bytes:
        """Fetch the publication log feed for a single day (daily discovery)."""
        return self._get(self.update_feed_url(target_date))

    # ─── Historical walk (consolidated blob, consumed by parser) ────

    def get_suvestine(self, norm_id: str) -> bytes:
        """Fetch the full version timeline for a UK law as a JSON blob.

        The pipeline detects ``hasattr(client, "get_suvestine")`` to switch
        into multi-version mode. The blob keeps parsing self-contained: no
        further HTTP calls are needed to produce the list of Block objects.

        Blob shape::

            {
                "norm_id": "ukpga-2018-12",
                "versions": [
                    {
                        "effective_date": "2018-05-23",
                        "affecting_uri": null,          // bootstrap commit
                        "xml_b64": "<enacted CLML, base64>"
                    },
                    {
                        "effective_date": "2019-04-09",
                        "affecting_uri": "http://.../id/ukpga/2019/...",
                        "xml_b64": "<PIT CLML, base64>"
                    },
                    …
                ]
            }

        When the law has no applied amendments (newly passed or never
        revised), the timeline collapses to a single "enacted" entry.
        """
        # 1. Fetch enacted text — always present, even for repealed Acts.
        try:
            enacted_xml = self.get_enacted(norm_id)
        except requests.HTTPError as exc:
            # A handful of very old Acts only exist in "revised" form on TNA's
            # Statute Law Database. Fall back to the latest revised text.
            status = exc.response.status_code if exc.response is not None else None
            if status != 404:
                raise
            logger.warning("%s: no enacted XML available, falling back to latest", norm_id)
            enacted_xml = self.get_text(norm_id)

        # CloudFront WAF issues HTTP 202 with an empty body for Acts it
        # considers too expensive to render on-demand (e.g. Companies Act
        # 2006, 1,300+ sections). Treat that as a retryable failure so the
        # pipeline flags the law for a reprocess instead of committing an
        # empty snapshot.
        if not enacted_xml or len(enacted_xml) == 0:
            raise ValueError(
                f"{norm_id}: empty response from legislation.gov.uk "
                "(likely CloudFront 202 challenge or WAF hold)"
            )

        enacted_date = _extract_enacted_date(enacted_xml)

        versions: list[dict] = [
            {
                "effective_date": enacted_date,
                "affecting_uri": None,
                "xml_b64": base64.b64encode(enacted_xml).decode("ascii"),
            }
        ]

        # 2. Walk the changes feed to collect every Applied=true in-force date.
        try:
            feed_pages = self.get_changes_feed(norm_id)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status != 404:
                raise
            feed_pages = []

        applied_effects = _extract_applied_effects(feed_pages)

        # 3. Group effects by date → one commit per date.
        by_date: dict[str, list[str]] = {}
        for eff_date, affecting_uri in applied_effects:
            by_date.setdefault(eff_date, []).append(affecting_uri)

        # 4. For each date after the enacted date, fetch the PIT snapshot.
        for eff_date in sorted(by_date.keys()):
            if enacted_date and eff_date <= enacted_date:
                # The enacted commit already covers this date; a same-day
                # "amendment" is a data quirk (usually commencement of the
                # Act itself). Skip.
                continue
            try:
                parsed = date.fromisoformat(eff_date)
            except ValueError:
                logger.debug("%s: skipping malformed change date %r", norm_id, eff_date)
                continue
            try:
                pit_xml = self.get_at_date(norm_id, parsed)
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status == 404:
                    # Happens when the server has not yet rendered the PIT
                    # for a very recent amendment. Skip; the daily will pick
                    # it up later.
                    logger.warning("%s: no PIT XML for %s (404), skipping", norm_id, eff_date)
                    continue
                raise
            if not pit_xml:
                logger.warning("%s: empty PIT body for %s (WAF hold?), skipping", norm_id, eff_date)
                continue
            # Deduplicate "noop" PIT responses: if the PIT XML byte-for-byte
            # matches the previous version's, the server rendered an empty
            # diff. Skip to keep the commit log clean.
            if versions and pit_xml == base64.b64decode(versions[-1]["xml_b64"]):
                continue
            versions.append(
                {
                    "effective_date": eff_date,
                    "affecting_uri": by_date[eff_date][0],
                    "xml_b64": base64.b64encode(pit_xml).decode("ascii"),
                }
            )

        blob = {"norm_id": norm_id, "versions": versions}
        return json.dumps(blob).encode("utf-8")


# ─── Module-level helpers ────────────────────────────────────────


def _extract_enacted_date(xml_bytes: bytes) -> str | None:
    """Return the enacted/made date from a CLML XML (ISO string).

    Primary legislation uses ``<ukm:EnactmentDate>``.  Secondary legislation
    (statutory instruments) uses ``<ukm:Made Date="...">``.
    """
    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError:
        return None
    el = root.find(".//ukm:EnactmentDate", NS)
    if el is not None:
        return el.get("Date")
    # Fallback for statutory instruments.
    el = root.find(".//ukm:Made", NS)
    return el.get("Date") if el is not None else None


def _extract_applied_effects(feed_pages: list[bytes]) -> list[tuple[str, str]]:
    """Extract (effective_date, affecting_uri) tuples from changes-feed pages.

    Only entries with ``Applied="true"`` and a non-empty ``Date`` are kept.
    The tuple key is used downstream to deduplicate by (date, amending Act).
    """
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for page in feed_pages:
        try:
            root = etree.fromstring(page)
        except etree.XMLSyntaxError:
            continue
        for effect in root.findall(".//ukm:Effect", NS):
            affecting_uri = effect.get("AffectingURI", "") or ""
            for inforce in effect.findall("ukm:InForceDates/ukm:InForce", NS):
                if inforce.get("Applied") != "true":
                    continue
                eff_date = inforce.get("Date") or ""
                if not eff_date:
                    continue
                key = (eff_date, affecting_uri)
                if key in seen:
                    continue
                seen.add(key)
                out.append(key)
    return out
