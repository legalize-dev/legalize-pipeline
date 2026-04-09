"""One-shot helper to build a Uruguay law-number catalog by probing IMPO in parallel.

The serial discovery loop in `IMPODiscovery._discover_leyes` is the bottleneck
of the UY bootstrap (~4 sec/number due to HTTP latency + rate limiting).
This script does the same probing in parallel with N workers and writes the
result to `<data_dir>/catalog.json`. Subsequent calls to
`IMPODiscovery._discover_leyes` will read from this catalog instead of
re-probing.

Usage:
    python -m legalize.fetcher.uy.catalog [--start 9000] [--end 20500] [--workers 16]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from legalize.fetcher.uy.discovery import _year_candidates

BASE_URL = "https://www.impo.com.uy"
USER_AGENT = "legalize-bot/1.0 (+https://github.com/legalize-dev/legalize)"

log = logging.getLogger("build_uy_catalog")


def _is_json_response(content: bytes) -> bool:
    head = content.lstrip()[:1]
    return head == b"{"


def probe_one(
    session: requests.Session,
    num: int,
    last_year_hint: int | None,
    *,
    collection: str = "leyes",
    candidate_years: list[int] | None = None,
) -> tuple[int, str | None]:
    """Try candidate years for a single norm number.

    Returns ``(num, "{collection}/N-Y")`` on the first valid hit, or
    ``(num, None)`` after exhausting all candidates.
    """
    if candidate_years is None:
        candidates = _year_candidates(num)
    else:
        candidates = list(candidate_years)
    if last_year_hint is not None and last_year_hint not in candidates:
        candidates = [last_year_hint, *candidates]
    elif last_year_hint is not None:
        candidates = [last_year_hint, *(c for c in candidates if c != last_year_hint)]

    for year in candidates:
        url = f"{BASE_URL}/bases/{collection}/{num}-{year}?json=true"
        try:
            r = session.get(url, timeout=20)
        except requests.RequestException as exc:
            log.debug("error %s on %d-%d: %s", num, num, year, exc)
            continue
        if r.status_code != 200:
            continue
        if _is_json_response(r.content):
            return (num, f"{collection}/{num}-{year}")
    return (num, None)


def build_catalog(
    start: int,
    end: int,
    workers: int,
    out_path: Path,
    *,
    collection: str = "leyes",
    candidate_years: list[int] | None = None,
) -> list[str]:
    log.info(
        "Probing %s/%d..%d with %d workers (candidates=%s)",
        collection,
        start,
        end,
        workers,
        "auto" if candidate_years is None else candidate_years,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sessions = [requests.Session() for _ in range(workers)]
    for s in sessions:
        s.headers["User-Agent"] = USER_AGENT

    found: dict[int, str] = {}
    last_year_hint: int | None = None
    started = time.time()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for i, num in enumerate(range(start, end + 1)):
            session = sessions[i % workers]
            futures[
                pool.submit(
                    probe_one,
                    session,
                    num,
                    last_year_hint,
                    collection=collection,
                    candidate_years=candidate_years,
                )
            ] = num

        completed = 0
        for fut in as_completed(futures):
            completed += 1
            num, norm_id = fut.result()
            if norm_id:
                found[num] = norm_id
                last_year_hint = int(norm_id.rsplit("-", 1)[1])
            if completed % 200 == 0:
                elapsed = time.time() - started
                rate = completed / elapsed
                eta = (end - start - completed) / max(rate, 0.1)
                log.info(
                    "  %d/%d probed (%d hits) — %.1f/s, eta %.0fs",
                    completed,
                    end - start + 1,
                    len(found),
                    rate,
                    eta,
                )

    elapsed = time.time() - started
    log.info(
        "Done: %d/%d %s found in %.1fs (%.1f probes/s)",
        len(found),
        end - start + 1,
        collection,
        elapsed,
        (end - start + 1) / elapsed,
    )

    norm_ids = [found[n] for n in sorted(found)]
    out_path.write_text(json.dumps(norm_ids, indent=2))
    log.info("Catalog written to %s (%d entries)", out_path, len(norm_ids))
    return norm_ids


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--collection",
        choices=("leyes", "decretos-ley"),
        default="leyes",
        help="Which IMPO collection to enumerate (default: leyes).",
    )
    parser.add_argument("--start", type=int, default=None)
    parser.add_argument("--end", type=int, default=None)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument(
        "--out",
        default=None,
        help="Output JSON path (default: ../countries/data-uy/{collection}.catalog.json).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    # Per-collection defaults
    if args.collection == "leyes":
        start = args.start if args.start is not None else 9000
        end = args.end if args.end is not None else 20500
        candidate_years = None  # use the year-landmark estimator
        out_default = "../countries/data-uy/catalog.json"
    else:  # decretos-ley
        # The de-facto period: laws 14001..16000 enacted between 1973 and 1985.
        start = args.start if args.start is not None else 14001
        end = args.end if args.end is not None else 16000
        candidate_years = list(range(1973, 1986))
        out_default = "../countries/data-uy/decretos-ley.catalog.json"

    out_path = Path(args.out or out_default)
    build_catalog(
        start,
        end,
        args.workers,
        out_path,
        collection=args.collection,
        candidate_years=candidate_years,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
