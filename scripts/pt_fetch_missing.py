#!/usr/bin/env python3
"""Fetch every discovered Portuguese norm that is not in the raw cache yet.

The point is the gap, not the fetch. A bootstrap reads {data_dir}/raw/, so a norm
that failed once — a timeout, a 500, a worker that died — is simply absent from the
corpus, with nothing in the repo to say so. This diffs the discovery lists against
the cache and downloads only the difference, so it is both the way to finish an
interrupted run and the way to prove one finished.

    python3 scripts/pt_fetch_missing.py            # fetch the gap
    python3 scripts/pt_fetch_missing.py --report   # only say how big it is
    python3 scripts/pt_fetch_missing.py --reverse  # second worker, meets the first
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, "src")

from legalize.config import load_config  # noqa: E402
from legalize.fetcher._text import clean  # noqa: E402
from legalize.pipeline import generic_fetch_one  # noqa: E402


def _safe(norm_id: str) -> str:
    return norm_id.replace(":", "-").replace("/", "-")


def _out_of_scope(raw_dir: Path, norm_id: str) -> bool:
    """Deliberately dropped, so not a gap. Mirrors the two guards in get_text.

    Neither kind ever reaches get_suvestine — get_text raises first — so neither has
    a versions envelope, and both would otherwise look missing on every single run.
    That matters: the whole point of --report is to answer "did the fetch finish",
    and 23,000 permanent non-answers in the count make it unreadable.
    """
    path = raw_dir / f"{_safe(norm_id)}.meta.json.gz"
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            published = json.load(handle).get("published") or {}
    except Exception:
        return False
    # DRE's legacy Açores catalogue (RESEARCH-PT-v2 §11).
    if (published.get("TipoConteudo") or "") == "DiplomaLegacor":
        return True
    # Nothing to publish: DRE holds neither the text nor a scan of it.
    body = clean(published.get("TextoFormatado") or published.get("Texto") or "").strip()
    return not body and not (published.get("URL_PDF") or "").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="count the gap, fetch nothing")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument(
        "--reverse",
        action="store_true",
        help="walk the gap back to front, to pair with a front-to-back worker",
    )
    args = ap.parse_args()

    config = load_config(os.environ.get("CONFIG", "config.yaml"))
    data_dir = Path(config.get_country("pt").data_dir)
    raw_dir = data_dir / "raw"

    discovered: list[str] = []
    for name in ("discovery_cons.txt", "discovery_pub.txt"):
        path = data_dir / name
        if not path.exists():
            print(f"missing discovery list: {path}", flush=True)
            return 2
        discovered += [line.strip() for line in path.read_text().splitlines() if line.strip()]

    cached = {p.name[: -len(".versions.json.gz")] for p in raw_dir.glob("*.versions.json.gz")}
    missing = [n for n in discovered if _safe(n) not in cached]
    skipped = [n for n in missing if _out_of_scope(raw_dir, n)]
    missing = [n for n in missing if n not in set(skipped)]

    print(
        f"{len(discovered)} discovered · {len(cached)} cached · "
        f"{len(skipped)} out of scope · {len(missing)} missing",
        flush=True,
    )
    if args.report or not missing:
        return 0
    if args.reverse:
        missing.reverse()

    work: queue.Queue = queue.Queue()
    for norm_id in missing:
        work.put(norm_id)
    lock, t0 = threading.Lock(), time.time()
    stats = {"ok": 0, "err": 0, "n": 0}

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
                if stats["n"] % 250 == 0:
                    rate = stats["n"] / (time.time() - t0)
                    print(
                        f"{stats['n']}/{len(missing)} ok={stats['ok']} err={stats['err']} "
                        f"{rate * 60:.0f}/min eta {(len(missing) - stats['n']) / rate / 60:.0f} min",
                        flush=True,
                    )

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(args.workers)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    print("DONE", stats, f"in {(time.time() - t0) / 60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
