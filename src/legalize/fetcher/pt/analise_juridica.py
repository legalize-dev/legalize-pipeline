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
import re
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


# ── the amendment index ───────────────────────────────────────────────────────
# Built here rather than in a script because the daily has to rebuild it too: an
# act published this morning amends a law whose relation row only exists on the
# amended law's record, so the index is not a bootstrap artefact but something
# that changes every day.

_RDFA = re.compile(r'about="([^"]*)"\s+property="eli:(amended_by|amends)"\s+resource="([^"]*)"')
_ELI_PATH = re.compile(r"/eli/([^/]+)/([^/]+)/(\d{4})")
# DRE quotes this attribute with single quotes and the neighbouring ones with
# double. Matching only one finds nothing at all.
_HREF = re.compile(r"""href=["']/dr/detalhe/([^/"']+)/([^"'?#]+)["']""")
_AMENDING = re.compile(
    r"^\s*(altera|revoga|adita|republica|retifica|rectifica|derroga|prorroga|suspende)",
    re.I,
)
_UNSAFE = re.compile(r"[^A-Z0-9]+")
_DETALHE = re.compile(r"/dr/detalhe/([^/)\"'\s]+)/([^/)\"'\s?#]+)")


def _from_eli(uri: str) -> str | None:
    """``…/eli/dec-lei/16/1994/…`` -> ``DRE-DEC-LEI-16-1994``."""
    match = _ELI_PATH.search(uri or "")
    if not match:
        return None
    kind, number, year = match.groups()
    return (
        f"DRE-{_UNSAFE.sub('-', kind.upper()).strip('-')}"
        f"-{_UNSAFE.sub('-', number.upper()).strip('-')}-{year}"
    )


def targets_named_by(markdown: str) -> set[str]:
    """The norm ids an act links to, which are its candidate amendment targets.

    A DRE detail link is ``/dr/detalhe/{tipo}/{key}`` and an as-published norm id is
    ``pub:{tipo}:{key}``, so no lookup is needed. 73.7 % of amending acts link the
    law they change.
    """
    return {f"pub:{tipo}:{key}" for tipo, key in _DETALHE.findall(markdown or "")}


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


def _identifier_of(data_dir: Path, norm_id: str) -> str | None:
    """The official identifier of a diploma already in the raw cache."""
    from datetime import date as _date

    from legalize.fetcher.pt.identifier import build_identifier, serie_of

    path = data_dir / "raw" / f"{safe_name(norm_id)}.meta.json.gz"
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            bundle = json.load(handle)
    except (OSError, ValueError):
        return None
    published = bundle.get("published") or {}
    when = (published.get("DataPublicacao") or "")[:10]
    try:
        year = _date.fromisoformat(when).year
    except ValueError:
        year = 1900
    return build_identifier(
        (published.get("ELI") or "").strip(),
        (published.get("Numero") or "").strip(),
        bundle.get("tipo", ""),
        year,
        (published.get("TipoDiplomaAcronimo") or "").strip(),
        str(published.get("Id") or ""),
        serie_of(published),
    )


def refresh_amendments(api: Any, data_dir: str | Path, targets: set[str]) -> set[str]:
    """Re-read DRE's relation table for these laws and fold it into the index.

    The daily needs this and a bootstrap-time index cannot give it. An act published
    this morning names the laws it amends, but the resolvable record of that
    amendment lives on the *amended* law's análise jurídica page, not on the act's —
    ``DiretasList`` carries no resolvable target on any row. So the only way to learn
    that yesterday's law changed is to ask DRE about the law, not about the act.

    Returns the norm ids whose amendment list actually grew, which are the laws the
    caller has to re-render and commit.
    """
    root = Path(data_dir)
    index = _read_json(root / AMENDMENTS_FILE)
    changed: set[str] = set()

    for norm_id in sorted(targets):
        if not norm_id.startswith("pub:"):
            continue  # a consolidated diploma carries its amendments as Versions
        _, tipo, key = norm_id.split(":", 2)
        rows: dict[str, tuple[str, str]] = {}
        for association_id in AMENDMENT_TYPES:
            try:
                payload = api.associations(f"/dr/detalhe/{tipo}/{key}", association_id)
            except Exception:
                logger.warning("relation lookup failed for %s [%s]", norm_id, association_id)
                continue
            cache = root / RELATIONS_DIR / association_id
            cache.mkdir(parents=True, exist_ok=True)
            with gzip.open(cache / f"{safe_name(norm_id)}.json.gz", "wt", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            for row in relation_rows(payload):
                parts = (row.get("LinkSitemapAnaliseJuridica") or "").strip("/").split("/")
                if len(parts) < 2:
                    continue
                act = _identifier_of(root, f"pub:{parts[-2]}:{parts[-1]}")
                when = (row.get("Data") or "")[:10]
                if act and when:
                    note = " ".join((row.get("Texto") or "").replace("\x00", "").split())
                    rows[act] = (when, note)

        if not rows:
            continue
        known = {r[1] for r in index.get(norm_id, [])}
        merged = {r[1]: (r[0], r[2] if len(r) > 2 else "") for r in index.get(norm_id, [])}
        merged.update(rows)
        if set(merged) != known:
            index[norm_id] = [
                [w, a, n] for a, (w, n) in sorted(merged.items(), key=lambda kv: kv[1][0])
            ]
            changed.add(norm_id)

    if changed:
        (root / AMENDMENTS_FILE).write_text(
            json.dumps(index, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        pt_parser.set_amendments(index)
    return changed
