"""Everything Portugal gets from DRE's análise jurídica screen.

Three things live behind that one screen and none of them reach the corpus through
the normal fetch path, because none of them belongs to the diploma's own record:

* **Descriptor labels.** ``eli:is_about`` names subjects as bare integers and the
  authority URIs do not dereference. This is the only surface that publishes the
  Portuguese terms.
* **Subjects for the diplomas that declare none.** 12 % of consolidated diplomas —
  the Código Civil included — return an empty ``ELIMetadataHTML``, so ``eli:is_about``
  names nothing at all for them.
* **The relation table.** Which diploma amended which, when, and in DRE's own words
  which articles moved. The corpus is 97 % as-enacted, so for most Portuguese laws
  this is the only record that they were ever changed.

All three are corpus-wide maps rather than per-norm fields, so they are built once,
cached under ``{data_dir}/``, and installed into the parser before anything renders
— by the reparse, and equally by the daily, which would otherwise publish subject-less
laws and never record an amendment against the law it amended.
"""

from __future__ import annotations

import gzip
import json
import logging
from pathlib import Path
from typing import Any

from legalize.fetcher.pt import parser as pt_parser

logger = logging.getLogger(__name__)

# DRE's association types, from DataActionGetTipoAssociacoes. These two are the
# amendments; the rest are case law, EU law, implementing acts and legal notes.
# A rectification is an amendment: it changes the official text with legal effect.
AMENDMENT_TYPES = ("162", "165")

THESAURUS_FILE = "thesaurus.json"
SUBJECTS_FILE = "subjects.json"
AMENDMENTS_FILE = "amendments.json"
RELATIONS_DIR = "relations"


def safe_name(norm_id: str) -> str:
    """The cache filename for one norm. Shared so the writer and reader agree."""
    return norm_id.replace(":", "-").replace("/", "-")


def relation_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The usable rows of one association response.

    Only ``InversasList``. ``DiretasList`` describes the same relations from the
    acting side, but not one of its rows carries a resolvable target — ``HasLink``
    is false and ``DiplomaLinkId`` is "0" throughout — while 93.9 % of them have a
    counterpart inversa. The graph is therefore complete from the amended law's side
    and unobtainable from the amending act's, which is why this is harvested per law
    and not per act.
    """
    return list((payload.get("InversasList") or {}).get("List") or [])


def install(data_dir: str | Path) -> dict[str, int]:
    """Install every análise jurídica map into the parser. Returns what was loaded.

    Safe to call when the files are absent: the parser falls back to emitting no
    subjects and no amendments, which is what it did before they existed.
    """
    root = Path(data_dir)
    loaded: dict[str, int] = {}

    thesaurus = _read_json(root / THESAURUS_FILE)
    if thesaurus:
        pt_parser.set_thesaurus(thesaurus)
        loaded["thesaurus"] = len(thesaurus)

    overrides = _read_json(root / SUBJECTS_FILE)
    if overrides:
        pt_parser.set_subject_overrides(overrides)
        loaded["subject_overrides"] = sum(1 for v in overrides.values() if v)

    amendments = _read_json(root / AMENDMENTS_FILE)
    if amendments:
        pt_parser.set_amendments(amendments)
        loaded["amendments"] = len(amendments)

    return loaded


def _read_json(path: Path) -> dict:
    if not path.exists():
        logger.info("análise jurídica map absent: %s", path)
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("unreadable análise jurídica map, ignoring: %s", path, exc_info=True)
        return {}


def read_relations(data_dir: str | Path) -> dict[str, list[dict[str, Any]]]:
    """``{norm id: [inversa row, …]}`` from the harvested cache, all types merged."""
    root = Path(data_dir) / RELATIONS_DIR
    out: dict[str, list[dict[str, Any]]] = {}
    if not root.exists():
        return out
    for type_dir in sorted(root.glob("*")):
        if not type_dir.is_dir():
            continue
        for path in type_dir.glob("*.json.gz"):
            try:
                with gzip.open(path, "rt", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, ValueError):
                continue
            rows = relation_rows(payload)
            if rows:
                out.setdefault(path.name[: -len(".json.gz")], []).extend(rows)
    return out
