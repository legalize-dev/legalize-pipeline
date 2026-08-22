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
from legalize.fetcher.pt import analise_juridica  # noqa: E402
from legalize.pipeline import generic_fetch_one  # noqa: E402

config = load_config(os.environ.get("CONFIG", "config.yaml"))
data_dir = Path(config.get_country("pt").data_dir)

# One place decides what the análise jurídica maps are and how they load, shared
# with the daily — which needs exactly the same three and would otherwise drift.
loaded = analise_juridica.install(data_dir)
print(f"análise jurídica: {loaded or 'no maps found'}", flush=True)

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

# A diploma DRE consolidates is reachable from both surfaces and both resolve to the
# same identifier, so both write the same {identifier}.json and the last one wins.
# The as-published record is a single snapshot with no history; the consolidated one
# carries a Version per effective date. Letting as-published land last cost the
# Código Civil its 2,930 blocks and 54 reforms and left it a one-block stub — the
# exact failure the whole rewrite exists to prevent (§3, version history is the
# gate). Published first, consolidated second, with a barrier between: ordering
# inside a phase is not guaranteed with eight workers, so it has to be two phases
# rather than a sort.
published = [n for n in ids if not n.startswith("cons:")]
consolidated = [n for n in ids if n.startswith("cons:")]
print(
    f"{len(ids)} norms to reparse ({len(published)} published, {len(consolidated)} consolidated)",
    flush=True,
)
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


for phase, batch in (("published", published), ("consolidated", consolidated)):
    if not batch:
        continue
    print(f"-- {phase}: {len(batch)}", flush=True)
    work = queue.Queue()
    for norm_id in batch:
        work.put(norm_id)
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]

print("DONE", stats, f"in {(time.time() - t0) / 60:.1f} min", flush=True)

# The check that would have caught the overwrite: almost every consolidated diploma
# is also reachable as-published, both write {identifier}.json, and if the wrong one
# lands last the law silently loses its whole history. Count what actually survived.
survived = 0
for path in (data_dir / "json").glob("*.json"):
    try:
        with path.open(encoding="utf-8") as handle:
            meta = json.load(handle).get("metadata") or {}
    except Exception:
        continue
    if ((meta.get("extra") or {}).get("surface")) == "cons":
        survived += 1
print(f"consolidated laws in the corpus: {survived} of {len(consolidated)} reparsed", flush=True)
if consolidated and survived < len(consolidated) * 0.9:
    print(
        "FAIL: consolidated diplomas are being overwritten by their as-published "
        "twin — the corpus would ship without version history",
        flush=True,
    )
    raise SystemExit(1)
if failures:
    print(f"failures ({len(failures)} shown):", flush=True)
    for norm_id in failures:
        print("   ", norm_id, flush=True)
