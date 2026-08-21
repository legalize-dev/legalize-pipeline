#!/usr/bin/env python3
"""Reparse every cached Portuguese norm without touching the network.

{data_dir}/raw/ holds the source envelopes, so a parser change costs minutes
instead of the ~15 hours a refetch would.
"""

from __future__ import annotations

import gzip
import json
import sys
import threading
import queue
import time
from pathlib import Path

sys.path.insert(0, "src")

from legalize.config import load_config          # noqa: E402
from legalize.fetcher.pt import parser as pt_parser  # noqa: E402
from legalize.pipeline import generic_fetch_one  # noqa: E402

config = load_config("config.yaml")
data_dir = Path(config.get_country("pt").data_dir)

thesaurus_path = data_dir / "thesaurus.json"
if thesaurus_path.exists():
    terms = json.loads(thesaurus_path.read_text(encoding="utf-8"))
    pt_parser.set_thesaurus(terms)
    print(f"thesaurus: {len(terms)} terms", flush=True)
else:
    print("thesaurus: absent — subjects will stay empty", flush=True)

# The filename cannot be reversed into a norm id (the tipo itself contains hyphens),
# so read the id back out of each envelope.
ids: list[str] = []
for path in sorted((data_dir / "raw").glob("*.versions.json.gz")):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            ids.append(json.load(handle)["norm_id"])
    except Exception:
        continue

print(f"{len(ids)} norms to reparse", flush=True)
work: queue.Queue = queue.Queue()
for norm_id in ids:
    work.put(norm_id)
lock, stats, t0 = threading.Lock(), {"ok": 0, "err": 0, "n": 0}, time.time()


def worker() -> None:
    while True:
        try:
            norm_id = work.get_nowait()
        except queue.Empty:
            return
        try:
            ok = generic_fetch_one(config, "pt", norm_id, force=True) is not None
        except Exception:
            ok = False
        with lock:
            stats["n"] += 1
            stats["ok" if ok else "err"] += 1
            if stats["n"] % 2000 == 0:
                print(f"{stats['n']}/{len(ids)} ok={stats['ok']} err={stats['err']}", flush=True)


threads = [threading.Thread(target=worker, daemon=True) for _ in range(8)]
[t.start() for t in threads]
[t.join() for t in threads]
print("DONE", stats, f"in {(time.time() - t0) / 60:.1f} min", flush=True)
