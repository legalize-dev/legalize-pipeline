#!/usr/bin/env python3
"""Re-fetch all Swedish norms without discovery.

Uses existing JSON filenames as norm list, skipping the slow
Riksdagen discovery pagination. Also discovers new norms from
2017-2026 by paginating from a specific start page.

Usage:
    python -m legalize.fetcher.se.refetch              # re-fetch all existing + discover new
    python -m legalize.fetcher.se.refetch --limit 10   # test with 10 norms
"""

import argparse
import logging
import re
import time
from pathlib import Path

from legalize.config import load_config
from legalize.pipeline import generic_fetch_one

logging.basicConfig(level=logging.WARNING, format="%(message)s")


def extract_norm_ids_from_json(json_dir: Path) -> list[str]:
    """Extract SFS norm IDs from existing JSON filenames."""
    norm_ids = []
    for f in sorted(json_dir.glob("*.json")):
        m = re.match(r"^SFS-(\d{4})-(.+)$", f.stem)
        if m:
            norm_ids.append(f"{m.group(1)}:{m.group(2)}")
    return norm_ids


def discover_recent(start_page: int = 488) -> list[str]:
    """Discover base statute SFS numbers from a specific page onward."""
    from legalize.fetcher.se.discovery import _is_amendment

    import requests

    seen: set[str] = set()
    norm_ids: list[str] = []
    page = start_page

    session = requests.Session()
    session.headers["User-Agent"] = "legalize-bot/1.0"
    session.headers["Accept"] = "application/json"

    while True:
        url = (
            f"https://data.riksdagen.se/dokumentlista/"
            f"?doktyp=sfs&sort=datum&sortorder=asc"
            f"&format=json&utformat=json&p={page}"
        )
        result = None
        for attempt in range(3):
            try:
                resp = session.get(url, timeout=30)
                resp.raise_for_status()
                result = resp.json()
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(2**attempt)
                else:
                    print(f"  Error on page {page} after 3 attempts: {e}")
        if result is None:
            break

        doc_list = result.get("dokumentlista", {})
        documents = doc_list.get("dokument") or []

        if not documents:
            break

        for doc in documents:
            title = doc.get("titel", "")
            sfs = doc.get("beteckning", "")
            if not sfs:
                continue
            if _is_amendment(title):
                continue
            if sfs not in seen:
                seen.add(sfs)
                norm_ids.append(sfs)

        has_more = bool(doc_list.get("@nasta_sida"))
        if not has_more:
            break

        page += 1
        time.sleep(0.1)  # Be polite

    session.close()
    return norm_ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--skip-existing", action="store_true", help="Only discover and fetch new norms (2017+)"
    )
    args = parser.parse_args()

    config = load_config()
    cc = config.get_country("se")
    json_dir = Path(cc.data_dir) / "json"

    # Phase 1: collect all norm IDs
    if args.skip_existing:
        existing_ids = []
    else:
        existing_ids = extract_norm_ids_from_json(json_dir)
        print(
            f"Existing norms: {existing_ids[-1] if existing_ids else 'none'} ({len(existing_ids)})"
        )

    # Phase 2: discover new norms (2017-2026)
    print("Discovering new norms from 2017+...")
    new_ids = discover_recent(start_page=488)
    # Filter out already-existing ones
    existing_set = set(existing_ids)
    truly_new = [nid for nid in new_ids if nid not in existing_set]
    print(f"  New norms discovered: {len(truly_new)}")

    all_ids = existing_ids + truly_new
    if args.limit:
        all_ids = all_ids[: args.limit]

    print(f"\nTotal to fetch: {len(all_ids)}")
    print(f"Estimated time: ~{len(all_ids) * 3 / 10 / 60:.0f} minutes\n")

    # Phase 3: fetch each norm
    fetched = 0
    errors = 0
    t0 = time.time()

    for i, norm_id in enumerate(all_ids, 1):
        try:
            result = generic_fetch_one(config, "se", norm_id, force=True)
            if result:
                fetched += 1
            else:
                errors += 1
        except Exception as e:
            errors += 1
            print(f"  ERROR {norm_id}: {e}")

        if i % 50 == 0:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(all_ids) - i) / rate / 60 if rate > 0 else 0
            print(
                f"  [{i}/{len(all_ids)}] {fetched} OK, {errors} errors "
                f"({rate:.1f}/s, ETA {eta:.0f}m)"
            )

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed / 60:.1f}m: {fetched} fetched, {errors} errors")


if __name__ == "__main__":
    main()
