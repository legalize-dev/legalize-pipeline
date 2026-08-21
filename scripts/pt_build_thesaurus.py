#!/usr/bin/env python3
"""Build the DRE subject-descriptor map: {legal-subject id: Portuguese label}.

``eli:is_about`` gives numeric ids and the authority URIs do not dereference. The
AnaliseJuridica screen is the only surface that publishes their labels, one diploma
at a time, so the map is accumulated by sampling until it stops growing.

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

from legalize.fetcher.pt.dre_api import DREApi, DREApiError  # noqa: E402

CATALOGUE = Path("../countries/data-pt/consolidated-catalogue.jsonl.gz")
STOP_AFTER_DRY_ROUNDS = 8      # rounds of 50 diplomas that add nothing new
ROUND = 50


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "../countries/data-pt/thesaurus.json")
    thesaurus: dict[str, str] = json.loads(out.read_text()) if out.exists() else {}

    with gzip.open(CATALOGUE, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle]
    refs = [r["diploma_legis_id"] and (r, r.get("eli") or "") for r in rows if not r.get("error")]
    refs = [r for r, _ in ((x[0], x[1]) for x in refs if x)]
    random.seed(7)
    random.shuffle(refs)

    api = DREApi(requests_per_second=1.5)
    dry, seen, t0 = 0, 0, time.time()
    for start in range(0, len(refs), ROUND):
        before = len(thesaurus)
        for row in refs[start : start + ROUND]:
            link = (row.get("diploma_legis") or {}).get("LinkSitemap") if row.get("diploma_legis") else None
            ref = link or f"/dr/detalhe/{row['tipo']}/{row['numero']}-{row['ano']}-{row['diploma_legis_id']}"
            seen += 1
            try:
                thesaurus.update(api.descriptors(ref))
            except (DREApiError, Exception):
                continue
        out.write_text(json.dumps(thesaurus, ensure_ascii=False, indent=1, sort_keys=True))
        gained = len(thesaurus) - before
        print(
            f"{seen} diplomas · {len(thesaurus)} terms (+{gained}) · "
            f"{(time.time() - t0) / 60:.1f} min",
            flush=True,
        )
        dry = dry + 1 if gained == 0 else 0
        if dry >= STOP_AFTER_DRY_ROUNDS:
            print("converged", flush=True)
            break
    print("DONE", len(thesaurus), "terms", flush=True)


if __name__ == "__main__":
    main()
