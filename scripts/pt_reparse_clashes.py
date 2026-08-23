#!/usr/bin/env python3
"""Reparse only the norms whose JSON was shredded by a colliding writer.

Two norms can resolve to one ``{identifier}.json`` — two acts published under the
same official number, one of them in another série. Before the write was made
atomic, eight reparse workers opened that file at once, both truncated it and both
wrote from their own offset, so what landed was one document with the tail of
another stuck to it. Every later reader skipped those files and the laws left the
corpus without a word.

This repairs them without touching the other 164,795: find the unreadable files,
work out which norms write them, and reparse just those. Nothing is fetched — it
all comes from the raw cache — and nothing is committed.

    python3 scripts/pt_reparse_clashes.py --report   # list, change nothing
    python3 scripts/pt_reparse_clashes.py

One law per pair still ends up shadowed: the file can hold one of them, so the
last writer wins. Those are printed at the end. Fixing that means changing what
the identifier is made of, which is a decision about the output format.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "src")

from legalize.config import load_config  # noqa: E402
from legalize.fetcher.pt import analise_juridica  # noqa: E402
from legalize.pipeline import generic_fetch_one  # noqa: E402
from legalize.storage import overwritten_identifiers, reset_write_tracking  # noqa: E402

DRE_LINK = re.compile(r'"dre_link":\s*"/dr/detalhe/([^/"]+)/([^"]+)"')


def unreadable(json_dir: Path) -> list[Path]:
    """Every file in json/ that no longer parses as one JSON document."""
    broken = []
    for path in sorted(json_dir.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as handle:
                json.load(handle)
        except Exception:
            broken.append(path)
    return broken


def _key(norm_id: str) -> tuple[str, str]:
    """(tipo, número-año) — what two colliding norms share and the dre_id does not."""
    _surface, tipo, key = norm_id.split(":", 2)
    number_year, _, _dreid = key.rpartition("-")
    return tipo, number_year.lower()


def in_scope_by_key(data_dir: Path) -> dict[tuple[str, str], list[str]]:
    """The corpus, grouped by what a colliding pair has in common.

    Read from the discovery lists rather than from raw/, which also holds norms
    fetched before a scope rule was corrected.
    """
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for name in ("discovery_pub.txt", "discovery_cons.txt"):
        path = data_dir / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            norm_id = line.strip()
            if norm_id:
                groups[_key(norm_id)].append(norm_id)
    return groups


def norms_behind(path: Path, groups: dict[tuple[str, str], list[str]]) -> list[str]:
    """Which norms write this file.

    The file is broken, so it cannot be parsed for its provenance — but every
    document in it carries a ``dre_link``, and those survive as plain text.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    found: list[str] = []
    for tipo, key in DRE_LINK.findall(text):
        number_year, _, _dreid = key.rpartition("-")
        for norm_id in groups.get((tipo, number_year.lower()), []):
            if norm_id not in found:
                found.append(norm_id)
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="list what would be reparsed")
    args = ap.parse_args()

    config = load_config(os.environ.get("CONFIG", "config.yaml"))
    data_dir = Path(config.get_country("pt").data_dir)
    json_dir = data_dir / "json"

    print(f"scanning {json_dir} …", flush=True)
    broken = unreadable(json_dir)
    print(f"{len(broken)} unreadable files", flush=True)
    if not broken:
        return 0

    groups = in_scope_by_key(data_dir)
    work: list[str] = []
    orphans: list[Path] = []
    for path in broken:
        norms = norms_behind(path, groups)
        if not norms:
            orphans.append(path)
            continue
        work.extend(n for n in norms if n not in work)

    print(f"{len(work)} norms to reparse for {len(broken) - len(orphans)} files", flush=True)
    if orphans:
        print(f"{len(orphans)} files no norm could be traced to:", flush=True)
        for path in orphans[:20]:
            print("   ", path.name, flush=True)

    if args.report:
        for norm_id in work:
            print("   ", norm_id, flush=True)
        return 0

    # The maps the parser reads for descriptors, subjects and last_amendment. Without
    # them the repaired files would come back thinner than their neighbours.
    print(f"análise jurídica: {analise_juridica.install(data_dir) or 'no maps found'}", flush=True)

    # Serial on purpose. These are exactly the ids that collide, and the whole point
    # is that only one of them may be in flight at a time. Published first so that a
    # consolidated twin still lands last, as in the full reparse.
    work.sort(key=lambda n: (n.startswith("cons:"), n))
    reset_write_tracking()
    ok = err = 0
    for norm_id in work:
        try:
            ok += 1 if generic_fetch_one(config, "pt", norm_id, force=True) is not None else 0
        except Exception as exc:  # noqa: BLE001 — one bad norm must not stop the repair
            err += 1
            print(f"    {norm_id}: {exc}", flush=True)
    print(f"reparsed {ok} norms, {err} errors", flush=True)

    still_broken = unreadable(json_dir)
    print(f"unreadable files now: {len(still_broken)}", flush=True)

    shadowed = overwritten_identifiers()
    if shadowed:
        print(
            f"{len(shadowed)} identifiers still hold two norms and kept the last one "
            "— the file can only carry one:",
            flush=True,
        )
        for identifier, count in sorted(shadowed.items()):
            print(f"    {identifier} (+{count} shadowed)", flush=True)

    return 1 if still_broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
