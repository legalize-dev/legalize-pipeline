#!/usr/bin/env python3
"""Recover the subjects of diplomas whose ELI metadata is empty.

``eli:is_about`` is the normal route to a diploma's subject descriptors, but 12 % of
consolidated diplomas come back with an empty ``ELIMetadataHTML`` and so name none —
the Código Civil among them, which is not a law that should reach the site with no
subjects. AnaliseJuridica still knows them (40 for the Código Civil), one diploma at
a time, keyed by LinkSitemap.

Consolidated only. Fixing the as-published side the same way would mean ~120,000
requests at DRE's polite rate, about 22 hours, for the surface where a missing
subject list matters least.

    python3 scripts/pt_subjects_gap.py            # fill the gap
    python3 scripts/pt_subjects_gap.py --report   # only say how big it is
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

from legalize.fetcher.pt.dre_api import DREApi  # noqa: E402
from legalize.fetcher.pt.parser import _parse_eli_rdfa  # noqa: E402

RAW = Path("../countries/data-pt/raw")
SAVE_EVERY = 25


def _needy() -> list[str]:
    """LinkSitemaps of consolidated diplomas that declare no subject at all."""
    out: list[str] = []
    for path in sorted(RAW.glob("cons-*.meta.json.gz")):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                published = json.load(handle).get("published") or {}
        except Exception:
            continue
        if _parse_eli_rdfa(published.get("ELIMetadataHTML") or "").get("subjects"):
            continue
        link = (published.get("LinkSitemap") or "").strip()
        if link:
            out.append(link)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../countries/data-pt/subjects.json")
    ap.add_argument("--thesaurus", default="../countries/data-pt/thesaurus.json")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    known: dict[str, list[str]] = json.loads(out.read_text()) if out.exists() else {}
    needy = [link for link in _needy() if link not in known]

    print(f"{len(needy)} consolidated diplomas with no subjects · {len(known)} already filled")
    if args.report or not needy:
        return 0

    thesaurus_path = Path(args.thesaurus)
    thesaurus: dict[str, str] = (
        json.loads(thesaurus_path.read_text()) if thesaurus_path.exists() else {}
    )

    api = DREApi(requests_per_second=1.5)
    filled = empty = errors = 0
    start = time.time()
    for index, link in enumerate(needy, 1):
        try:
            descriptors = api.descriptors(link)
        except Exception:
            errors += 1
            continue
        if descriptors:
            known[link] = sorted(descriptors.values())
            thesaurus.update(descriptors)
            filled += 1
        else:
            # Recorded, so a re-run does not ask DRE the same question again.
            known[link] = []
            empty += 1
        if index % SAVE_EVERY == 0:
            out.write_text(json.dumps(known, ensure_ascii=False, indent=1, sort_keys=True))
            thesaurus_path.write_text(
                json.dumps(thesaurus, ensure_ascii=False, indent=1, sort_keys=True)
            )
            print(
                f"{index}/{len(needy)} · {filled} filled · {empty} genuinely none · "
                f"{errors} errors · {(time.time() - start) / 60:.1f} min",
                flush=True,
            )

    out.write_text(json.dumps(known, ensure_ascii=False, indent=1, sort_keys=True))
    thesaurus_path.write_text(json.dumps(thesaurus, ensure_ascii=False, indent=1, sort_keys=True))
    print(
        f"DONE {filled} filled · {empty} genuinely none · {errors} errors · "
        f"{(time.time() - start) / 60:.1f} min",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
