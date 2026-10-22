"""Discovery of German federal legislation via gesetze-im-internet.de TOC."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

from legalize.fetcher.base import LegislativeClient, NormDiscovery
from legalize.fetcher.de.client import GIIClient

logger = logging.getLogger(__name__)


class GIIDiscovery(NormDiscovery):
    """Discovers all federal laws from the GII table of contents XML.

    The TOC at https://www.gesetze-im-internet.de/gii-toc.xml lists ~6900 laws.
    Each <item> has a <link> pointing to the ZIP download URL.
    The norm_id is the URL slug extracted from the link.
    """

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Yield all URL slugs from the GII TOC."""
        assert isinstance(client, GIIClient)
        toc = client.get_toc()
        root = ET.fromstring(toc)

        for item in root.findall(".//item"):
            link = item.find("link")
            if link is None or not link.text:
                continue
            slug = self._extract_slug(link.text)
            if slug:
                yield slug

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Yield slugs whose ZIP was last modified since the previous daily day.

        The window is the days after the previous day the schedule runs, up to
        and including target_date: Germany runs Mon-Fri, so Monday also takes
        what changed on the weekend. Matching the day exactly would lose those
        for good.

        The source has no change feed, so the only signal is each ZIP's
        Last-Modified: one HEAD per law, ~6,100 of them. They are read once per
        run and every day of the run is answered from that scan. Asking again
        per day multiplied the scan by the days processed: catching up 2026-09-22
        to 09-28 cost ~42,000 requests in one run. Matching ``>=`` the day also
        handed one change to every day of a catch-up, so the StGB was committed
        on the 22nd, the 23rd and the 28th for a single amendment.

        A law changed twice inside the window is committed once, on its last
        change: the source only serves the current text.

        If 'slugs' is passed in kwargs, only those slugs are checked.
        """
        assert isinstance(client, GIIClient)
        if getattr(self, "_modified", None) is None:
            self._modified = self._scan_last_modified(client, kwargs.get("slugs"))
        from legalize.pipeline import SKIP_WEEKDAYS  # pipeline imports this module

        skipped = SKIP_WEEKDAYS.get("de", set())
        previous = target_date - timedelta(days=1)
        while previous.weekday() in skipped:
            previous -= timedelta(days=1)
        for slug, day in self._modified.items():
            if previous < day <= target_date:
                yield slug

    def _scan_last_modified(self, client: GIIClient, slugs: list[str] | None) -> dict[str, date]:
        modified: dict[str, date] = {}
        for slug in slugs or list(self.discover_all(client)):
            try:
                last_mod = client.head_zip(slug).get("Last-Modified", "")
                if last_mod:
                    modified[slug] = parsedate_to_datetime(last_mod).date()
            except Exception:
                logger.debug("Could not check %s, skipping", slug)
        logger.info("Last-Modified read for %d law(s)", len(modified))
        return modified

    @staticmethod
    def _extract_slug(url: str) -> str | None:
        """Extract the law slug from a GII ZIP URL.

        Example: 'http://www.gesetze-im-internet.de/gg/xml.zip' -> 'gg'
        """
        match = re.search(r"gesetze-im-internet\.de/([^/]+)/xml\.zip", url)
        return match.group(1) if match else None
