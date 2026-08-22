#!/usr/bin/env python3
"""Reparse every cached Portuguese norm without touching the network.

{data_dir}/raw/ holds the source envelopes, so a parser change costs minutes
instead of the ~15 hours a refetch would.
"""

from __future__ import annotations

import gzip
import json
import os
import sys
import threading
import queue
import time
from pathlib import Path

sys.path.insert(0, "src")

from legalize.config import load_config  # noqa: E402
from legalize.fetcher.pt import parser as pt_parser  # noqa: E402
from legalize.pipeline import generic_fetch_one  # noqa: E402

config = load_config(os.environ.get("CONFIG", "config.yaml"))
data_dir = Path(config.get_country("pt").data_dir)

thesaurus_path = data_dir / "thesaurus.json"
if thesaurus_path.exists():
    terms = json.loads(thesaurus_path.read_text(encoding="utf-8"))
    pt_parser.set_thesaurus(terms)
    print(f"thesaurus: {len(terms)} terms", flush=True)
else:
    print("thesaurus: absent — subjects will stay empty", flush=True)

overrides_path = data_dir / "subjects.json"
if overrides_path.exists():
    overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    pt_parser.set_subject_overrides(overrides)
    print(f"subject overrides: {sum(1 for v in overrides.values() if v)} diplomas", flush=True)

# The discovery lists say what belongs in the corpus; raw/ only says what has been
# downloaded, and the two are not the same. Anything fetched before a scope rule was
# corrected is still sitting in the cache — 2,380 pre-1960 scan-only diplomas, say —
# and reparsing the directory rather than the lists would put them back in the repo.
in_scope: set[str] = set()
for name in ("discovery_cons.txt", "discovery_pub.txt"):
    path = data_dir / name
    if path.exists():
        in_scope |= {line.strip() for line in path.read_text().splitlines() if line.strip()}

# The filename cannot be reversed into a norm id (the tipo itself contains hyphens),
# so read the id back out of each envelope.
ids: list[str] = []
stale = 0
for path in sorted((data_dir / "raw").glob("*.versions.json.gz")):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            norm_id = json.load(handle)["norm_id"]
    except Exception:
        continue
    if in_scope and norm_id not in in_scope:
        stale += 1
        continue
    ids.append(norm_id)
if stale:
    print(f"{stale} cached norms are no longer in scope, skipping", flush=True)

print(f"{len(ids)} norms to reparse", flush=True)
work: queue.Queue = queue.Queue()
for norm_id in ids:
    work.put(norm_id)
lock, t0 = threading.Lock(), time.time()
stats = {"ok": 0, "skipped": 0, "err": 0, "n": 0}
# One in five ids is an out-of-scope Açores row, and generic_fetch_one reports that
# the same way it reports a crash — as None. Counted apart, or a real regression
# hides inside a five-figure "err".
failures: list[str] = []


def worker() -> None:
    while True:
        try:
            norm_id = work.get_nowait()
        except queue.Empty:
            return
        outcome = "err"
        try:
            if generic_fetch_one(config, "pt", norm_id, force=True) is not None:
                outcome = "ok"
            else:
                outcome = "skipped" if _out_of_scope(norm_id) else "err"
        except Exception:
            outcome = "err"
        with lock:
            stats["n"] += 1
            stats[outcome] += 1
            if outcome == "err" and len(failures) < 200:
                failures.append(norm_id)
            if stats["n"] % 2000 == 0:
                print(
                    f"{stats['n']}/{len(ids)} ok={stats['ok']} "
                    f"out-of-scope={stats['skipped']} err={stats['err']}",
                    flush=True,
                )


def _out_of_scope(norm_id: str) -> bool:
    """A norm dropped on purpose: DRE's legacy Açores catalogue (RESEARCH-PT-v2 §11).

    Read straight off the cached envelope — building a DREClient here would mean an
    OutSystems handshake for each of the 40,000-odd rows.
    """
    safe = norm_id.replace(":", "-").replace("/", "-")
    path = data_dir / "raw" / f"{safe}.meta.json.gz"
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            published = json.load(handle).get("published") or {}
    except Exception:
        return False
    return (published.get("TipoConteudo") or "") == "DiplomaLegacor"


threads = [threading.Thread(target=worker, daemon=True) for _ in range(8)]
[t.start() for t in threads]
[t.join() for t in threads]
print("DONE", stats, f"in {(time.time() - t0) / 60:.1f} min", flush=True)
if failures:
    print(f"failures ({len(failures)} shown):", flush=True)
    for norm_id in failures:
        print("   ", norm_id, flush=True)
