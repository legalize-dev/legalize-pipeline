"""Norm discovery in the LEGI dump.

Scans the dump directory to find consolidated texts
(codes, constitution, laws) by their NATURE in the XML metadata.

Actual dump structure (verified with 2026-03-27 increment):

  {legi_dir}/legi/global/
    code_et_TNC_en_vigueur/
      code_en_vigueur/LEGI/TEXT/.../LEGITEXTXXX/texte/struct/LEGITEXTXXX.xml
      TNC_en_vigueur/JORF/TEXT/.../JORFTEXTYYY/texte/struct/LEGITEXTZZZ.xml
    code_et_TNC_non_vigueur/...

Initial phase: 77 codes in force + Constitution.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from lxml import etree

from legalize.fetcher.base import LegislativeClient, NormDiscovery

logger = logging.getLogger(__name__)

# Text natures we process in the initial phase (codes)
_NATURES_CODES = {"CODE", "CONSTITUTION"}

# Subdirectories where to search for texts in force
_VIGUEUR_DIRS = [
    "legi/global/code_et_TNC_en_vigueur/code_en_vigueur",
    "legi/global/code_et_TNC_en_vigueur/TNC_en_vigueur",
]


class LEGIDiscovery(NormDiscovery):
    """Discovers norms in the local LEGI dump.

    Scans structure files (texte/struct/) searching for texts
    whose NATURE is CODE or CONSTITUTION (initial phase).
    """

    def __init__(self, legi_dir: str | Path, natures: set[str] | None = None):
        self._base = Path(legi_dir)
        self._natures = natures or _NATURES_CODES

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Discovers all LEGITEXT in the dump filtered by NATURE.

        Recursively scans the directories of texts in force,
        searching for texte/struct/LEGITEXT*.xml files.
        """
        count = 0
        seen: set[str] = set()

        for subdir in _VIGUEUR_DIRS:
            search_base = self._base / subdir
            if not search_base.exists():
                logger.debug("Directory does not exist: %s", search_base)
                continue

            for struct_path in search_base.rglob("texte/struct/LEGITEXT*.xml"):
                norm_id = struct_path.stem
                if norm_id in seen:
                    continue
                seen.add(norm_id)

                try:
                    nature, etat = self._read_nature_etat(struct_path)
                except Exception:
                    logger.warning("Error reading %s, skipping", struct_path)
                    continue

                if nature not in self._natures:
                    continue
                # In code_en_vigueur all should be VIGUEUR,
                # but verify just in case
                if etat and etat not in ("VIGUEUR", ""):
                    continue

                count += 1
                logger.info("Discovered: %s (%s)", norm_id, nature)
                yield norm_id

        logger.info("Total discovered: %d texts", count)

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Discovers norms from the LEGI daily increment.

        Daily increments are downloaded from:
        https://echanges.dila.gouv.fr/OPENDATA/LEGI/LEGI_YYYYMMDD-HHMMSS.tar.gz

        They are extracted in the same base directory. They contain the same
        directory structure but only with the files that changed that day.
        """
        # Search in the increment directory
        # Format: {base}/{YYYYMMDD}-{HHMMSS}/legi/global/...
        date_str = target_date.strftime("%Y%m%d")
        for increment_dir in self._base.glob(f"{date_str}-*/legi/global"):
            for struct_path in increment_dir.rglob("texte/struct/LEGITEXT*.xml"):
                yield struct_path.stem

    @staticmethod
    def _read_nature_etat(xml_path: Path) -> tuple[str, str]:
        """Extracts NATURE and ETAT from a LEGI structure file.

        Uses iterparse for efficiency (does not load the entire XML into memory).
        """
        nature = ""
        etat = ""
        for _, elem in etree.iterparse(str(xml_path), events=("end",)):
            tag = elem.tag
            if tag == "NATURE" and not nature:
                nature = (elem.text or "").strip()
            elif tag == "ETAT" and not etat:
                etat = (elem.text or "").strip()
            if nature and etat:
                break
            elem.clear()
        return nature, etat
