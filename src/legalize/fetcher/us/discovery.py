"""US Code norm discovery -- enumerates sections from downloaded title XMLs.

Reads the locally cached USLM XML files (downloaded by OLRCClient) and
yields one norm_id per section (~60,000 sections across 54 titles).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date
from xml.etree import ElementTree as ET

from legalize.fetcher.base import LegislativeClient, NormDiscovery
from legalize.fetcher.us.client import (
    USLM_NS,
    USC_TITLE_NUMBERS,
    OLRCClient,
    build_norm_id,
)

logger = logging.getLogger(__name__)


class USDiscovery(NormDiscovery):
    """Discovers US Code sections from locally cached title XMLs."""

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Yield norm_ids for every section in the current release point.

        Reads each title's XML from data_dir and enumerates ``<section>``
        elements.  Yields identifiers like ``USC-T18-S1341``.
        """
        assert isinstance(client, OLRCClient)
        release_tag = kwargs.get("release_tag", client._release_tag)

        for title_num in USC_TITLE_NUMBERS:
            yield from self._sections_in_title(client, release_tag, title_num)

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Yield norm_ids updated since *target_date*.

        Compares the two most recent cached release points and yields
        sections whose content changed.
        """
        assert isinstance(client, OLRCClient)

        cached = client.cached_release_tags()
        if len(cached) < 2:
            logger.info("Need at least 2 release points for daily diff")
            return

        prev_tag = cached[-2]
        curr_tag = cached[-1]
        logger.info("Diffing release points %s → %s", prev_tag, curr_tag)

        for title_num in USC_TITLE_NUMBERS:
            yield from self._changed_sections(client, prev_tag, curr_tag, title_num)

    # -- Internal helpers -----------------------------------------------------

    def _sections_in_title(
        self, client: OLRCClient, release_tag: str, title_num: int
    ) -> Iterator[str]:
        """Yield section norm_ids for a single title."""
        try:
            root = client._get_title_root(release_tag, title_num)
        except FileNotFoundError:
            logger.debug("Title %d not found for release %s", title_num, release_tag)
            return

        ns = f"{{{USLM_NS}}}"
        for sec in root.iter(f"{ns}section"):
            section_id = self._extract_section_id(sec, title_num)
            if section_id is not None:
                yield build_norm_id(title_num, section_id)

    def _changed_sections(
        self,
        client: OLRCClient,
        prev_tag: str,
        curr_tag: str,
        title_num: int,
    ) -> Iterator[str]:
        """Yield section norm_ids that differ between two release points."""
        try:
            prev_root = client._get_title_root(prev_tag, title_num)
            curr_root = client._get_title_root(curr_tag, title_num)
        except FileNotFoundError:
            return

        ns = f"{{{USLM_NS}}}"

        prev_sections = {
            self._extract_section_id(s, title_num): ET.tostring(s, encoding="unicode")
            for s in prev_root.iter(f"{ns}section")
            if self._extract_section_id(s, title_num) is not None
        }
        curr_sections = {
            self._extract_section_id(s, title_num): ET.tostring(s, encoding="unicode")
            for s in curr_root.iter(f"{ns}section")
            if self._extract_section_id(s, title_num) is not None
        }

        for sec_id, xml_str in curr_sections.items():
            if sec_id not in prev_sections or prev_sections[sec_id] != xml_str:
                yield build_norm_id(title_num, sec_id)

    @staticmethod
    def _extract_section_id(section_el: ET.Element, title_num: int) -> str | None:
        """Extract the section number from the identifier attribute.

        Expected format: /us/usc/t{N}/s{M}  (e.g., /us/usc/t18/s1341)
        """
        identifier = section_el.get("identifier", "")
        prefix = f"/us/usc/t{title_num}/s"
        if identifier.startswith(prefix):
            return identifier[len(prefix) :]
        return None
