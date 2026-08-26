"""Discovery for Estonian laws via the Riigi Teataja bulk XML dump.

Riigi Teataja publishes annual ZIP archives of all currently-relevant
XML files at:

    https://www.riigiteataja.ee/avaandmed/ERT/xml.{YYYY}.zip

Notes from empirical validation (2026-04-07):
  - The zips are REGENERATED DAILY, so the "current year" zip is always
    up-to-date.
  - The zip layout is NOT strict per publication year — the 2026.en.zip
    we sampled contained globaalIDs from 2013-2025. Treat each zip as
    "all relevant XMLs as of YYYY".
  - Deduplication across versions happens via ``terviktekstiGrupiID``
    (stable group ID per law across all its consolidated versions).

Discovery strategy:
  1. For each year in the configured range, download xml.{YYYY}.zip into
     ``data_dir/bulk/`` (skip if the file exists and is fresh enough).
  2. Extract the zip into ``data_dir/legi/`` (flat layout: one .xml per law).
  3. Walk every ``*.xml`` file in legi_dir and parse only the ``<metaandmed>``
     header (~200 bytes of actual data — ``iterparse`` stops early).
  4. Filter by ``dokumentLiik`` and ``tekstiliik`` (from config.yaml ``source``).
  5. Group by ``terviktekstiGrupiID``. For each group, yield the
     ``globaalID`` of the version with the latest ``kehtivuseAlgus`` (i.e.
     the currently-in-force version). The pipeline will follow the
     ``Eelmine`` chain separately during bootstrap to pick up all
     historical versions.
"""

from __future__ import annotations

import logging
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from lxml import etree

from legalize.fetcher.base import LegislativeClient, NormDiscovery

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# Default bulk dump URL base
_DEFAULT_BULK_URL = "https://www.riigiteataja.ee/avaandmed/ERT"

# The earliest year with XML coverage. Anything before 2010 is bundled inside
# xml.2010.zip as legacy content.
_DEFAULT_START_YEAR = 2010


@dataclass
class _HeaderInfo:
    """Minimal metadata extracted from a Riigi Teataja XML header."""

    global_id: str
    group_id: str
    doc_type: str  # dokumentLiik
    text_type: str  # tekstiliik
    effective_from: date | None


class RTDiscovery(NormDiscovery):
    """Discovery via the Riigi Teataja bulk XML dump.

    Instance state is created from ``CountryConfig`` via ``create()``. All
    filesystem paths default to ``<data_dir>/bulk`` (zip archives) and
    ``<data_dir>/legi`` (extracted xml files).
    """

    def __init__(
        self,
        *,
        bulk_url: str,
        legi_dir: Path,
        bulk_dir: Path,
        document_types: tuple[str, ...],
        text_types: tuple[str, ...],
        start_year: int,
        end_year: int | None,
    ) -> None:
        self._bulk_url = bulk_url.rstrip("/")
        self._legi_dir = legi_dir
        self._bulk_dir = bulk_dir
        self._document_types = set(document_types)
        self._text_types = set(text_types)
        self._start_year = start_year
        self._end_year = end_year

    @classmethod
    def create(cls, country_config) -> "RTDiscovery":
        # Accept either a CountryConfig (from bootstrap.py / the custom flow)
        # or a bare source dict (from generic_daily / generic_fetch_all).
        if hasattr(country_config, "source"):
            source = country_config.source or {}
            data_dir = Path(country_config.data_dir)
        else:
            source = country_config or {}
            data_dir = Path(source.get("data_dir") or "../countries/data-ee")

        legi_dir = Path(source.get("legi_dir") or (data_dir / "legi"))
        bulk_dir = Path(source.get("bulk_dir") or (data_dir / "bulk"))

        doc_types = tuple(source.get("document_types") or ("seadus", "määrus"))
        text_types = tuple(source.get("text_types") or ("terviktekst", "algtekst-terviktekst"))

        return cls(
            bulk_url=source.get("bulk_url") or _DEFAULT_BULK_URL,
            legi_dir=legi_dir,
            bulk_dir=bulk_dir,
            document_types=doc_types,
            text_types=text_types,
            start_year=int(source.get("start_year") or _DEFAULT_START_YEAR),
            end_year=int(source["end_year"]) if source.get("end_year") else None,
        )

    # ─── NormDiscovery interface ───

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Yield one canonical ``globaalID`` per distinct law.

        The canonical ID is the globaalID of the currently-in-force version
        (i.e. the consolidated version whose ``kehtivuseAlgus`` is latest
        and whose ``kehtivuseLopp`` is either absent or in the future).

        Assumes ``discover_all`` runs after ``ensure_bulk_dump()``, which
        downloads and extracts the zips. Callers can pre-populate
        ``legi_dir`` manually for testing.
        """
        headers = self._walk_headers()

        # Group by terviktekstiGrupiID
        groups: dict[str, list[_HeaderInfo]] = {}
        for info in headers:
            if self._document_types and info.doc_type not in self._document_types:
                continue
            if self._text_types and info.text_type not in self._text_types:
                continue
            if not info.group_id:
                # Fallback: treat as its own group (rare)
                groups.setdefault(f"__single__{info.global_id}", []).append(info)
                continue
            groups.setdefault(info.group_id, []).append(info)

        # Sort each group by effective_from desc, pick the first
        for group_id, versions in groups.items():
            versions.sort(key=lambda h: h.effective_from or date(1900, 1, 1), reverse=True)
            yield versions[0].global_id

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Yield globaalIDs whose effective_from equals ``target_date``.

        Strategy: walk the extracted legi_dir (assumed fresh for today) and
        filter by ``kehtivuseAlgus == target_date``. The bulk dump is
        regenerated daily by Riigi Teataja, so pulling the current-year zip
        is enough for incremental updates.
        """
        for info in self._walk_headers():
            if self._document_types and info.doc_type not in self._document_types:
                continue
            if self._text_types and info.text_type not in self._text_types:
                continue
            if info.effective_from == target_date:
                yield info.global_id

    # ─── Bulk management ───

    def ensure_bulk_dump(
        self,
        *,
        years: list[int] | None = None,
        force_download: bool = False,
    ) -> None:
        """Download and extract the bulk XML dump.

        Args:
            years: Specific years to sync. Defaults to ``start_year``..current.
            force_download: Re-download zips even if they exist locally.
        """
        import requests

        self._bulk_dir.mkdir(parents=True, exist_ok=True)
        self._legi_dir.mkdir(parents=True, exist_ok=True)

        if years is None:
            end = self._end_year or date.today().year
            years = list(range(self._start_year, end + 1))

        for year in years:
            zip_name = f"xml.{year}.zip"
            zip_path = self._bulk_dir / zip_name
            url = f"{self._bulk_url}/{zip_name}"

            if zip_path.exists() and not force_download:
                logger.info("Bulk zip already present: %s", zip_path)
            else:
                logger.info("Downloading %s → %s", url, zip_path)
                with requests.get(url, stream=True, timeout=600) as resp:
                    resp.raise_for_status()
                    with zip_path.open("wb") as f:
                        for chunk in resp.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)

            logger.info("Extracting %s", zip_path)
            self._extract_zip(zip_path, self._legi_dir)

    @staticmethod
    def _extract_zip(zip_path: Path, dest: Path) -> int:
        """Extract a zip into dest (flat layout). Returns number of xml files."""
        count = 0
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.infolist():
                name = Path(member.filename).name
                if not name.endswith(".xml"):
                    continue
                target = dest / name
                # Skip if already extracted and same size
                if target.exists() and target.stat().st_size == member.file_size:
                    count += 1
                    continue
                with zf.open(member) as src, target.open("wb") as out:
                    out.write(src.read())
                count += 1
        return count

    # ─── Header walker ───

    def _walk_headers(self) -> Iterator[_HeaderInfo]:
        """Walk every .xml in legi_dir and yield its minimal header info."""
        if not self._legi_dir.is_dir():
            logger.warning("Legi dir does not exist: %s", self._legi_dir)
            return
        for xml_path in sorted(self._legi_dir.glob("*.xml")):
            try:
                info = _parse_header(xml_path)
            except etree.XMLSyntaxError as e:
                logger.warning("Malformed XML %s: %s", xml_path.name, e)
                continue
            if info is not None:
                yield info

    def find_xml_path(self, global_id: str) -> Path | None:
        """Resolve a globaalID to its path in legi_dir.

        Legacy IDs are stored with zero-padding to 12 characters in the zip
        (e.g. ``76913`` → ``000000076913.xml``). Modern 12-digit IDs match
        the filename directly. This helper tries all three variants.
        """
        for candidate in (global_id, global_id.zfill(12), global_id.lstrip("0")):
            path = self._legi_dir / f"{candidate}.xml"
            if path.exists():
                return path
        return None


# ─── Header parsing (streaming, minimal) ───


def _parse_header(path: Path) -> _HeaderInfo | None:
    """Extract only the <metaandmed> subtree from an XML file.

    Uses incremental parsing so we stop as soon as </metaandmed> is seen,
    avoiding the cost of parsing full law bodies (some are 2+ MB).
    """
    doc_type = ""
    text_type = ""
    global_id = ""
    group_id = ""
    eff_from: date | None = None

    # Stream until we close </metaandmed>
    context = etree.iterparse(str(path), events=("end",), huge_tree=True)
    try:
        for event, elem in context:
            local = etree.QName(elem.tag).localname
            if local == "dokumentLiik" and not doc_type:
                doc_type = (elem.text or "").strip()
            elif local == "tekstiliik" and not text_type:
                text_type = (elem.text or "").strip()
            elif local == "globaalID" and not global_id:
                global_id = (elem.text or "").strip()
            elif local == "terviktekstiGrupiID" and not group_id:
                group_id = (elem.text or "").strip()
            elif local == "kehtivuseAlgus" and eff_from is None:
                eff_from = _parse_date(elem.text)
            elif local == "metaandmed":
                break  # we've got everything we need
            # Free memory as we go — critical for large files
            elem.clear(keep_tail=True)
            while elem.getprevious() is not None:
                parent = elem.getparent()
                if parent is not None:
                    del parent[0]
                else:
                    break
    finally:
        del context

    if not global_id:
        return None
    return _HeaderInfo(
        global_id=global_id,
        group_id=group_id,
        doc_type=doc_type,
        text_type=text_type,
        effective_from=eff_from,
    )


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.split("+")[0].split("T")[0].strip()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None
