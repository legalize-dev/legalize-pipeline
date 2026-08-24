#!/usr/bin/env python3
"""Resolve the subject descriptors the sampled thesaurus never reached.

pt_build_thesaurus.py samples diplomas at random until the map stops growing, which
finds the common descriptors fast and then stalls: on a 6,000-record check it left
2,095 ids unlabelled, so 57 % of the diplomas that have subjects would ship a
partial list. Random sampling cannot close a long tail — the rare descriptor is
rare precisely because few diplomas carry it.

So go the other way: read the ids the corpus actually uses out of the cache, keep
the ones with no label yet, and fetch only diplomas that carry one. Each fetch
returns every descriptor of its diploma, so taking the widest-covering diploma
first (greedy set cover) closes the gap in far fewer requests than there are ids.

    python3 scripts/pt_thesaurus_gap.py            # close the gap
    python3 scripts/pt_thesaurus_gap.py --report   # only say how big it is
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


def _corpus_subjects() -> dict[str, set[str]]:
    """LinkSitemap -> the subject ids that diploma declares."""
    out: dict[str, set[str]] = {}
    for path in RAW.glob("*.meta.json.gz"):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                published = (json.load(handle).get("published") or {})
        except Exception:
            continue
        link = (published.get("LinkSitemap") or "").strip()
        subjects = _parse_eli_rdfa(published.get("ELIMetadataHTML") or "").get("subjects") or []
        if link and subjects:
            out[link] = set(subjects)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../countries/data-pt/thesaurus.json")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    thesaurus: dict[str, str] = json.loads(out.read_text()) if out.exists() else {}

    by_ref = _corpus_subjects()
    used = {i for ids in by_ref.values() for i in ids}
    unresolved = used - set(thesaurus)
    print(
        f"{len(by_ref)} diplomas with subjects · {len(used)} ids used · "
        f"{len(thesaurus)} labelled · {len(unresolved)} unresolved",
        flush=True,
    )
    if args.report or not unresolved:
        return 0

    # Widest-covering diploma first; recomputed lazily by skipping refs whose ids
    # have all been picked up by an earlier fetch.
    candidates = sorted(
        ((ref, ids & unresolved) for ref, ids in by_ref.items() if ids & unresolved),
        key=lambda pair: -len(pair[1]),
    )
    print(f"{len(candidates)} candidate diplomas", flush=True)

    api = DREApi(requests_per_second=1.5)
    fetched = errors = 0
    start = time.time()
    for ref, _ in candidates:
        still = by_ref[ref] & unresolved
        if not still:
            continue
        try:
            thesaurus.update(api.descriptors(ref))
        except Exception:
            errors += 1
            continue
        fetched += 1
        unresolved -= set(thesaurus)
        if fetched % SAVE_EVERY == 0:
            out.write_text(json.dumps(thesaurus, ensure_ascii=False, indent=1, sort_keys=True))
            print(
                f"{fetched} fetched · {len(thesaurus)} terms · {len(unresolved)} left · "
                f"{errors} errors · {(time.time() - start) / 60:.1f} min",
                flush=True,
            )
        if not unresolved:
            break

    out.write_text(json.dumps(thesaurus, ensure_ascii=False, indent=1, sort_keys=True))
    print(
        f"DONE {len(thesaurus)} terms · {len(unresolved)} still unresolved · "
        f"{fetched} fetched · {errors} errors · {(time.time() - start) / 60:.1f} min",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
