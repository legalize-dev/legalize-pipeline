#!/usr/bin/env python3
"""What is in Colombia's official catalogue and not in legalize-co.

SUIN publishes the list of every norm it holds as an open dataset on
datos.gov.co (`fiev-nid6`), on a host that is up even when SUIN is not. The
dataset keys each norm by tipo/número/año — which is exactly how we name our
files — so the gap is a set difference, not an estimate.

Two requests: the catalogue (one CSV), the repo tree (one GitHub API call).
Neither touches SUIN.

    python3 catalog-gap.py [--json out.json]

The join is only trustworthy because it is checked in both directions: if
"published but not in the catalogue" is not close to zero, the key is wrong
and every other number here is noise. It is printed for that reason.
"""

from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import re
import subprocess
import sys
import unicodedata
import requests

CATALOG_CSV = "https://www.datos.gov.co/resource/fiev-nid6.csv?$limit=100000"
REPO = "legalize-dev/legalize-co"


def norm_key(tipo: str, numero: str, ano: str) -> str:
    """Catalogue row → the filename stem the pipeline would give it."""
    t = unicodedata.normalize("NFKD", tipo or "").encode("ascii", "ignore").decode()
    t = re.sub(r"\s+", "-", t.upper().strip())
    return f"{t}-{(numero or '').strip().upper()}-{(ano or '').strip()}"


def load_catalog() -> list[dict[str, str]]:
    # requests, not urllib: it ships certifi, and a stock python.org build on
    # macOS has no CA bundle wired up, so urllib fails here on TLS alone.
    r = requests.get(CATALOG_CSV, timeout=180)
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.content.decode("utf-8"))))


def load_published() -> set[str]:
    """Filename stems in the country repo, via the GitHub tree API."""
    sha = subprocess.run(
        ["gh", "api", f"repos/{REPO}/commits/main", "--jq", ".commit.tree.sha"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    out = subprocess.run(
        ["gh", "api", f"repos/{REPO}/git/trees/{sha}?recursive=1",
         "--jq", '.tree[] | select(.type=="blob") | .path'],
        capture_output=True, text=True, check=True,
    ).stdout
    return {
        p[3:-3].upper()
        for p in (line.strip() for line in out.splitlines())
        if p.startswith("co/") and p.endswith(".md")
    }


def year_of(row: dict[str, str]) -> int | None:
    y = (row.get("a_o") or "").strip()
    return int(y) if len(y) == 4 and y.isdigit() and 1800 <= int(y) <= 2100 else None


def main() -> int:
    ap = argparse.ArgumentParser()
    # The full result set is 4.2 MB and regenerates in two requests, so it is
    # deliberately not kept in the repo — ask for it when you need to read it.
    ap.add_argument("--json", help="write the full result set here (~4 MB, not committed)")
    args = ap.parse_args()

    catalog = load_catalog()
    published = load_published()
    keyed = [(norm_key(r["tipo"], r["n_mero"], r["a_o"]), r) for r in catalog]
    missing = [r for k, r in keyed if k not in published]
    orphans = published - {k for k, _ in keyed}

    print(f"catalogue rows        : {len(catalog):,}")
    print(f"published .md files   : {len(published):,}")
    print(f"MISSING (in catalogue, no file) : {len(missing):,}"
          f"  ({100 * len(missing) / len(catalog):.1f}% of the catalogue)")
    print(f"orphans (file, no catalogue row): {len(orphans):,}"
          f"  ({100 * len(orphans) / len(published):.2f}% of the corpus)"
          "   ← must stay near zero, else the join key is wrong")

    era = collections.Counter(
        "2015+" if (year_of(r) or 0) >= 2015 else ("<=2014" if year_of(r) else "bad year")
        for r in missing
    )
    print("\nmissing by era      :", dict(era))
    print("missing by tipo     :")
    for t, c in collections.Counter(r["tipo"] for r in missing).most_common(10):
        print(f"    {c:6d}  {t}")
    print("missing by vigencia :")
    for v, c in collections.Counter(r["vigencia"] for r in missing).most_common(5):
        print(f"    {c:6d}  {v}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(
                {"catalog": len(catalog), "published": len(published),
                 "missing": missing, "orphans": sorted(orphans)},
                fh, ensure_ascii=False, indent=1,
            )
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
