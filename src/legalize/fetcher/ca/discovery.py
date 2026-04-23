"""Canada norm discovery -- enumerates laws from local XML clone or git.

Primary mode: scan a local clone of justicecanada/laws-lois-xml to yield
all act and regulation IDs. Daily mode: use git log to find files changed
on a specific date.

Both official languages are ingested: English in ``jurisdiction=ca-en``
(output path ``ca-en/<id>.md``) and French in ``jurisdiction=ca-fr``
(``ca-fr/<id>.md``). Canada's two official languages are constitutionally
equal, so we treat them symmetrically rather than privileging one as
``ca/``. The parser derives the language from the ``norm_id`` prefix
(``eng/...`` vs ``fra/...``).
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Iterator
from datetime import date, timedelta

from legalize.fetcher.base import LegislativeClient, NormDiscovery
from legalize.fetcher.ca.client import JusticeCanadaClient

logger = logging.getLogger(__name__)

# Directories to scan in the laws-lois-xml clone, with the norm_id prefix
# to emit. English and French are both ingested; the prefix encodes the
# language, which the parser maps to jurisdiction ``ca-en`` / ``ca-fr``.
_SCAN_DIRS: list[tuple[str, str]] = [
    ("eng/acts", "eng/acts"),
    ("eng/regulations", "eng/regulations"),
    ("fra/lois", "fra/lois"),
    ("fra/reglements", "fra/reglements"),
]


class CADiscovery(NormDiscovery):
    """Discovers Canadian federal acts and regulations."""

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Yield norm_ids for every act and regulation.

        Scans the local XML directory (from JusticeCanadaClient.xml_dir).
        Yields identifiers like "eng/acts/A-1", "fra/reglements/SOR-99-129".
        """
        assert isinstance(client, JusticeCanadaClient)
        xml_dir = client._xml_dir

        if xml_dir is None or not xml_dir.exists():
            logger.error(
                "No xml_dir configured or directory does not exist. "
                "Set source.xml_dir in config.yaml to a local clone of "
                "justicecanada/laws-lois-xml."
            )
            return

        for subdir, norm_prefix in _SCAN_DIRS:
            scan_path = xml_dir / subdir
            if not scan_path.exists():
                logger.debug("Skipping %s (not found)", scan_path)
                continue

            xml_files = sorted(scan_path.glob("*.xml"))
            logger.info("Found %d files in %s", len(xml_files), subdir)

            for xml_file in xml_files:
                # norm_id = "eng/acts/A-1" (without .xml extension)
                yield f"{norm_prefix}/{xml_file.stem}"

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Yield norm_ids for files changed exactly on target_date.

        Scopes ``git log`` to the single-day window
        ``[target_date 00:00, target_date + 1 day)``. Using ``--since``
        alone would be cumulative (every commit since that date), which
        duplicates norms when generic_daily iterates over a range of
        past dates during backfill.
        """
        assert isinstance(client, JusticeCanadaClient)
        xml_dir = client._xml_dir

        if xml_dir is None or not xml_dir.exists():
            logger.warning("No xml_dir for daily discovery; skipping")
            return

        since = target_date.isoformat()
        until = (target_date + timedelta(days=1)).isoformat()
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(xml_dir),
                    "log",
                    f"--since={since} 00:00:00",
                    f"--until={until} 00:00:00",
                    "--name-only",
                    "--pretty=format:",
                    "--diff-filter=ACMR",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                logger.warning("git log failed: %s", result.stderr)
                return

            seen: set[str] = set()
            for raw_line in result.stdout.strip().split("\n"):
                line = raw_line.strip()
                if not line or not line.endswith(".xml"):
                    continue
                # Convert file path to norm_id: "eng/acts/A-1.xml" → "eng/acts/A-1"
                norm_id = line.removesuffix(".xml")
                # Only yield files in the scan directories.
                if any(norm_id.startswith(prefix) for _, prefix in _SCAN_DIRS):
                    if norm_id not in seen:
                        seen.add(norm_id)
                        yield norm_id

            logger.info("Daily discovery found %d changed norms on %s", len(seen), since)

        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("git not available for daily discovery: %s", exc)
