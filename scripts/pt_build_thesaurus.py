#!/usr/bin/env python3
"""Build the DRE subject-descriptor map: {legal-subject id: Portuguese label}.

``eli:is_about`` gives numeric ids and the authority URIs do not dereference. The
AnaliseJuridica screen is the only surface that publishes their labels, one diploma
at a time, so the map is accumulated by sampling until it stops growing.

References come from the raw fetch cache rather than being reconstructed: a Portaria
numbered ``349/2026/1`` does not map to its DRE slug the way you would guess, which
is why ``docs/pt-dre-api.md`` says to always use ``LinkSitemap``.

    python3 scripts/pt_build_thesaurus.py ../countries/data-pt/thesaurus.json
"""

from __future__ import annotations

import gzip
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

from legalize.fetcher.pt.dre_api import DREApi  # noqa: E402

RAW = Path("../countries/data-pt/raw")
STOP_AFTER_DRY_ROUNDS = 10  # rounds that add no new term
ROUND = 40


def _refs() -> list[str]:
    """Every LinkSitemap the fetch has cached so far."""
    out: list[str] = []
    for path in RAW.glob("*.meta.json.gz"):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                bundle = json.load(handle)
        except Exception:
            continue
        link = ((bundle.get("published") or {}).get("LinkSitemap") or "").strip()
        if link:
            out.append(link)
    return out


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "../countries/data-pt/thesaurus.json")
    thesaurus: dict[str, str] = json.loads(out.read_text()) if out.exists() else {}

    refs = sorted(set(_refs()))
    random.seed(7)
    random.shuffle(refs)
    print(f"{len(refs)} references available", flush=True)

    api = DREApi(requests_per_second=1.5)
    dry, seen, errors, start_time = 0, 0, 0, time.time()
    for start in range(0, len(refs), ROUND):
        before = len(thesaurus)
        for ref in refs[start : start + ROUND]:
            seen += 1
            try:
                thesaurus.update(api.descriptors(ref))
            except Exception:
                errors += 1
        out.write_text(json.dumps(thesaurus, ensure_ascii=False, indent=1, sort_keys=True))
        gained = len(thesaurus) - before
        print(
            f"{seen}/{len(refs)} diplomas · {len(thesaurus)} terms (+{gained}) · "
            f"{errors} errors · {(time.time() - start_time) / 60:.1f} min",
            flush=True,
        )
        dry = dry + 1 if gained == 0 else 0
        if dry >= STOP_AFTER_DRY_ROUNDS:
            print("converged", flush=True)
            break
    print("DONE", len(thesaurus), "terms", flush=True)


if __name__ == "__main__":
    main()
