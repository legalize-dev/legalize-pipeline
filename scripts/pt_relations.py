#!/usr/bin/env python3
"""Harvest DRE's own relation table for every diploma in the corpus.

Until now the amendment index was built by reading prose: 96 % of its relations
came from parsing "Altera o Decreto-Lei n.º 16/94" out of an act's summary or body.
DRE publishes the same thing as data, on the análise jurídica screen, and it is
better in three ways — it is structured, so it can be audited; it names the
articles that moved ("Alterados os arts. 5º, 9º, 14º, 21º…"); and it records
repeals, which the prose route misses entirely. On Decreto-Lei 16/94 the prose gave
two amendments and DRE gives four, two of them repeals.

One call per diploma per association type, and there is no bulk endpoint: asking
with TipoAssociacaoId 0 returns nothing. Both directions come back in the same
call, so ``InversasList`` (what changed this law) and ``DiretasList`` (what this
law changed) cost the same single request.

Responses are cached under ``{data_dir}/relations/{type}/``, so the run is
resumable and a re-run costs nothing for what it already has.

    python3 scripts/pt_relations.py --report
    python3 scripts/pt_relations.py            # 162 modificações + 165 retificações
    python3 scripts/pt_relations.py --types 162
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
from legalize.fetcher.pt.dre_api import DREApi, DREApiError  # noqa: E402

# DRE's association types, from DataActionGetTipoAssociacoes. Only these two are
# amendments; the rest are case law, EU law, implementing acts and legal notes.
TYPES = {"162": "modificacoes", "165": "retificacoes"}


def _safe(norm_id: str) -> str:
    return norm_id.replace(":", "-").replace("/", "-")


def _work_list(raw_dir: Path, in_scope: set[str]) -> list[tuple[str, str]]:
    """(norm id, LinkSitemap) for every diploma that will be in the corpus."""
    out: list[tuple[str, str]] = []
    for path in raw_dir.glob("*.meta.json.gz"):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                bundle = json.load(handle)
        except Exception:
            continue
        surface = "cons" if path.name.startswith("cons-") else "pub"
        norm_id = f"{surface}:{bundle.get('tipo', '')}:{bundle.get('key', '')}"
        if in_scope and norm_id not in in_scope:
            continue
        published = bundle.get("published") or {}
        # Out of scope for the corpus, so out of scope here: no point asking DRE
        # about the Açores catalogue rows we do not publish.
        if (published.get("TipoConteudo") or "") == "DiplomaLegacor":
            continue
        link = (published.get("LinkSitemap") or "").strip()
        if link:
            out.append((norm_id, link))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--types", default="162,165")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--rps", type=float, default=0.0, help="0 = take it from config.yaml")
    args = ap.parse_args()

    config = load_config(os.environ.get("CONFIG", "config.yaml"))
    country = config.get_country("pt")
    data_dir = Path(country.data_dir)
    out_root = data_dir / "relations"

    in_scope: set[str] = set()
    for name in ("discovery_cons.txt", "discovery_pub.txt"):
        path = data_dir / name
        if path.exists():
            in_scope |= {line.strip() for line in path.read_text().splitlines() if line.strip()}

    work = _work_list(data_dir / "raw", in_scope)
    types = [t.strip() for t in args.types.split(",") if t.strip()]
    todo: list[tuple[str, str, str]] = []
    cached = 0
    for association_id in types:
        (out_root / association_id).mkdir(parents=True, exist_ok=True)
        for norm_id, link in work:
            if (out_root / association_id / f"{_safe(norm_id)}.json.gz").exists():
                cached += 1
            else:
                todo.append((norm_id, link, association_id))

    total = len(work) * len(types)
    print(
        f"{len(work)} diplomas x {len(types)} types = {total} calls · "
        f"{cached} cached · {len(todo)} to fetch",
        flush=True,
    )
    if args.report or not todo:
        return 0

    rps = args.rps or float((country.source or {}).get("requests_per_second", 5.0))
    print(f"at {rps} req/s with {args.workers} workers", flush=True)
    api = DREApi(requests_per_second=rps)

    pending: queue.Queue = queue.Queue()
    for item in todo:
        pending.put(item)
    lock, start = threading.Lock(), time.time()
    stats = {"ok": 0, "err": 0, "n": 0, "rows": 0}

    def worker() -> None:
        while True:
            try:
                norm_id, link, association_id = pending.get_nowait()
            except queue.Empty:
                return
            rows = 0
            try:
                payload = api.associations(link, association_id)
                rows = len((payload.get("InversasList") or {}).get("List") or []) + len(
                    (payload.get("DiretasList") or {}).get("List") or []
                )
                target = out_root / association_id / f"{_safe(norm_id)}.json.gz"
                with gzip.open(target, "wt", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False)
                outcome = "ok"
            except (DREApiError, OSError, ValueError):
                outcome = "err"
            with lock:
                stats["n"] += 1
                stats[outcome] += 1
                stats["rows"] += rows
                if stats["n"] % 2000 == 0:
                    rate = stats["n"] / (time.time() - start)
                    left = (len(todo) - stats["n"]) / rate / 3600
                    print(
                        f"{stats['n']}/{len(todo)} ok={stats['ok']} err={stats['err']} "
                        f"rows={stats['rows']} {rate * 60:.0f}/min eta {left:.1f}h",
                        flush=True,
                    )

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(args.workers)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    print("DONE", stats, f"in {(time.time() - start) / 3600:.2f}h", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
