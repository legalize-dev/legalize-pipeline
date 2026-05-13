"""OLRC client -- downloads US Code title ZIPs from uscode.house.gov.

Each title of the US Code is published as a ZIP containing one USLM XML
file.  The OLRC publishes "release points" -- complete snapshots of the
Code current through a specific Public Law.

The pipeline works at chapter granularity (one norm = one chapter), but
the OLRC bundles all chapters of a title into a single ZIP.  This client
downloads title ZIPs, caches the extracted XMLs locally, and serves
individual chapter XML on demand via get_text().
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

OLRC_BASE = "https://uscode.house.gov"
USLM_NS = "http://xml.house.gov/schemas/uslm/1.0"
DC_NS = "http://purl.org/dc/elements/1.1/"
DCTERMS_NS = "http://purl.org/dc/terms/"

# Register namespaces so ET.tostring preserves prefixes.
ET.register_namespace("", USLM_NS)
ET.register_namespace("dc", DC_NS)
ET.register_namespace("dcterms", DCTERMS_NS)
ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")

# All 54 title numbers in the US Code (some have letters, e.g., "54").
USC_TITLE_NUMBERS = list(range(1, 55))

# Known release points with approximate dates (from OLRC prior releases).
RELEASE_POINTS: list[dict[str, str]] = [
    {"tag": "113-21", "congress": "113", "law": "21", "date": "2013-07-18"},
    {"tag": "113-296", "congress": "113", "law": "296", "date": "2015-01-02"},
    {"tag": "114-38", "congress": "114", "law": "38", "date": "2015-07-08"},
    {"tag": "114-329", "congress": "114", "law": "329", "date": "2017-01-06"},
    {"tag": "115-51", "congress": "115", "law": "51", "date": "2017-08-14"},
    {"tag": "115-442", "congress": "115", "law": "442", "date": "2019-01-14"},
    {"tag": "116-91", "congress": "116", "law": "91", "date": "2019-12-19"},
    {"tag": "116-344", "congress": "116", "law": "344", "date": "2021-01-13"},
    {"tag": "117-81", "congress": "117", "law": "81", "date": "2021-12-27"},
    {"tag": "117-262", "congress": "117", "law": "262", "date": "2022-12-22"},
    {"tag": "118-158", "congress": "118", "law": "158", "date": "2024-12-31"},
    {"tag": "119-73", "congress": "119", "law": "73", "date": "2025-01-23"},
]

WAYBACK_PREFIX = "https://web.archive.org/web/2025"

DEFAULT_RELEASE_TAG = "119-73"
DEFAULT_TIMEOUT = 120  # Title ZIPs can be large.
DEFAULT_MAX_RETRIES = 5
DEFAULT_RPS = 1.0  # Conservative for OLRC.


def parse_norm_id(norm_id: str) -> tuple[int, str]:
    """Parse 'USC-T{n}-S{m}' into (title_num, section_id).

    >>> parse_norm_id("USC-T18-S1341")
    (18, '1341')
    """
    parts = norm_id.split("-")
    if len(parts) < 3 or parts[0] != "USC" or not parts[1].startswith("T"):
        raise ValueError(f"Invalid US norm_id: {norm_id!r}")
    title_num = int(parts[1][1:])
    section_id = "-".join(parts[2:])[1:]  # strip "S" prefix
    return title_num, section_id


def build_norm_id(title_num: int, section_id: str) -> str:
    """Build norm_id from title number and section identifier."""
    return f"USC-T{title_num}-S{section_id}"


class OLRCClient(HttpClient):
    """HTTP client for the OLRC US Code XML downloads."""

    def __init__(
        self,
        *,
        base_url: str = OLRC_BASE,
        data_dir: str = "",
        release_tag: str = DEFAULT_RELEASE_TAG,
        request_timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        requests_per_second: float = DEFAULT_RPS,
    ) -> None:
        super().__init__(
            base_url=base_url,
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
        )
        self._data_dir = Path(data_dir) if data_dir else Path(".")
        self._release_tag = release_tag
        self._title_cache: dict[tuple[str, int], ET.Element] = {}

        # OLRC requires a session cookie -- establish it on first request.
        self._session_established = False

    @classmethod
    def create(cls, country_config: CountryConfig) -> OLRCClient:
        source = country_config.source or {}
        return cls(
            base_url=source.get("base_url", OLRC_BASE),
            data_dir=country_config.data_dir,
            release_tag=source.get("release_tag", DEFAULT_RELEASE_TAG),
            request_timeout=source.get("request_timeout", DEFAULT_TIMEOUT),
            max_retries=source.get("max_retries", DEFAULT_MAX_RETRIES),
            requests_per_second=source.get("requests_per_second", DEFAULT_RPS),
        )

    # -- LegislativeClient interface ------------------------------------------

    def get_text(self, norm_id: str) -> bytes:
        """Return section XML wrapped in a uscDoc envelope.

        The returned XML contains ``<meta>`` from the parent title plus the
        single ``<section>`` element, so the parser has both title-level
        metadata and section content.
        """
        title_num, section_id = parse_norm_id(norm_id)
        return self._extract_section_xml(self._release_tag, title_num, section_id)

    def get_metadata(self, norm_id: str) -> bytes:
        """Same data as get_text -- metadata is embedded in the XML."""
        return self.get_text(norm_id)

    # -- Release-point-aware methods ------------------------------------------

    def get_release_point_text(self, norm_id: str, release_tag: str) -> bytes:
        """Return section XML for a *specific* release point."""
        title_num, section_id = parse_norm_id(norm_id)
        return self._extract_section_xml(release_tag, title_num, section_id)

    def available_release_points(self) -> list[dict[str, str]]:
        """Return the list of known release points."""
        return list(RELEASE_POINTS)

    def cached_release_tags(self) -> list[str]:
        """Return release tags whose title XMLs are already on disk."""
        rp_dir = self._data_dir / "release-points"
        if not rp_dir.exists():
            return []
        return sorted(d.name for d in rp_dir.iterdir() if d.is_dir() and any(d.glob("usc*.xml")))

    # -- Download helpers -----------------------------------------------------

    def download_release_point(self, release_tag: str) -> Path:
        """Download all 54 title ZIPs for one release point.

        Extracts each ZIP and saves the XML to
        ``data_dir/release-points/{tag}/usc{NN}.xml``.

        Returns the release-point directory path.
        """
        congress, law = release_tag.split("-", 1)
        rp_dir = self._data_dir / "release-points" / release_tag
        rp_dir.mkdir(parents=True, exist_ok=True)

        self._ensure_session()

        for title_num in USC_TITLE_NUMBERS:
            xml_path = rp_dir / f"usc{title_num:02d}.xml"
            if xml_path.exists():
                logger.debug("Already cached: %s", xml_path)
                continue

            zip_name = f"xml_usc{title_num:02d}@{release_tag}.zip"
            olrc_path = f"/download/releasepoints/us/pl/{congress}/{law}/{zip_name}"
            logger.info("Downloading %s ...", zip_name)
            try:
                zip_bytes = self._download_zip(olrc_path)
                xml_bytes = self._extract_xml_from_zip(zip_bytes, title_num)
                xml_path.write_bytes(xml_bytes)
                logger.info("  Saved %s (%d bytes)", xml_path.name, len(xml_bytes))
            except Exception:
                logger.warning("Failed to download title %d for %s", title_num, release_tag)
                # Some titles may not exist in older release points.
                continue

        # Write metadata.
        meta_path = rp_dir / "RELEASE.json"
        if not meta_path.exists():
            rp_info = next(
                (rp for rp in RELEASE_POINTS if rp["tag"] == release_tag),
                {"tag": release_tag},
            )
            meta_path.write_text(json.dumps(rp_info, indent=2))

        return rp_dir

    def download_all_release_points(self) -> list[str]:
        """Download every known release point.  Returns list of tags."""
        tags = []
        for rp in RELEASE_POINTS:
            tag = rp["tag"]
            self.download_release_point(tag)
            tags.append(tag)
        return tags

    # -- Internal helpers -----------------------------------------------------

    def _download_zip(self, olrc_path: str) -> bytes:
        """Download a ZIP, trying OLRC first, Wayback Machine as fallback.

        The OLRC blocks non-US IP addresses.  When running from CI
        (GitHub Actions, US-based), the direct URL works.  When running
        locally from outside the US, the Wayback Machine cached copy is
        used instead.
        """
        direct_url = f"{self._base_url}{olrc_path}"
        try:
            return self._get(direct_url, timeout=self._timeout)
        except Exception:
            logger.info("OLRC direct failed, trying Wayback Machine fallback")
            wayback_url = f"{WAYBACK_PREFIX}/{direct_url}"
            return self._get(wayback_url, timeout=self._timeout)

    def _ensure_session(self) -> None:
        """Establish an OLRC session cookie (required for downloads)."""
        if self._session_established:
            return
        try:
            self._session.get(f"{self._base_url}/", timeout=30)
            self._session_established = True
        except Exception:
            logger.warning("Could not establish OLRC session -- downloads may fail")

    @staticmethod
    def _extract_xml_from_zip(zip_bytes: bytes, title_num: int) -> bytes:
        """Extract the XML file from a title ZIP archive."""
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            xml_files = [n for n in zf.namelist() if n.endswith(".xml")]
            if not xml_files:
                raise ValueError(f"No XML file in ZIP for title {title_num}")
            return zf.read(xml_files[0])

    def _get_title_root(self, release_tag: str, title_num: int) -> ET.Element:
        """Load and cache a parsed title XML."""
        key = (release_tag, title_num)
        if key in self._title_cache:
            return self._title_cache[key]

        xml_path = self._data_dir / "release-points" / release_tag / f"usc{title_num:02d}.xml"
        if not xml_path.exists():
            raise FileNotFoundError(
                f"Title {title_num} XML not found at {xml_path}. "
                f"Run 'legalize fetch -c us' to download."
            )

        root = ET.parse(str(xml_path)).getroot()
        self._title_cache[key] = root
        return root

    def _extract_section_xml(self, release_tag: str, title_num: int, section_id: str) -> bytes:
        """Build a minimal uscDoc containing one section + title metadata."""
        root = self._get_title_root(release_tag, title_num)
        ns = f"{{{USLM_NS}}}"

        # Find the section element.
        section_el = None
        target_id = f"/us/usc/t{title_num}/s{section_id}"
        for sec in root.iter(f"{ns}section"):
            if sec.get("identifier") == target_id:
                section_el = sec
                break

        if section_el is None:
            raise ValueError(
                f"Section {section_id} not found in title {title_num} (release {release_tag})"
            )

        # Build a standalone document: <uscDoc> with <meta> + <main>/<section>.
        doc = ET.Element(f"{ns}uscDoc")
        doc.set("identifier", target_id)

        meta = root.find(f"{ns}meta")
        if meta is not None:
            doc.append(deepcopy(meta))

        main = ET.SubElement(doc, f"{ns}main")
        main.append(deepcopy(section_el))

        return ET.tostring(doc, encoding="unicode", xml_declaration=True).encode("utf-8")
