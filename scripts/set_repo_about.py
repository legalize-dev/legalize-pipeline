#!/usr/bin/env python3
"""Standardize each country repo's GitHub "About" (description + homepage).

The repo "About" is GitHub metadata, NOT a file in the repo, so the normal
pipeline (which only writes git files) cannot set it — this script does, via the
GitHub API (``gh``). Run it once per new country (after the repo exists) so every
repo's About is identical in style.

  description = short native tagline + "law=file, reform=commit" clause
                (from ``legalize.country_meta.LABELS``: desc_tagline + desc_clause)
  homepage    = https://legalize.dev/{code}   (set always, even if the page is
                not live yet — it will be)

Repos in PRESERVE_DESCRIPTION keep their existing description (e.g. an external
maintainer credit) and only get the homepage. Idempotent.

Usage:
    python scripts/set_repo_about.py            # all countries in COUNTRY_META
    python scripts/set_repo_about.py es fr      # specific countries
    python scripts/set_repo_about.py --dry-run
"""

from __future__ import annotations

import subprocess
import sys

from legalize.country_meta import COUNTRY_META, LABELS

OWNER = "legalize-dev"
PRESERVE_DESCRIPTION = {"uk"}  # keep existing maintainer credit


def gh_json(repo: str, jq: str) -> str | None:
    r = subprocess.run(["gh", "api", f"repos/{OWNER}/{repo}", "--jq", jq],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    out = r.stdout.strip()
    return "" if out in ("", "null") else out


def description_for(code: str) -> str:
    meta = COUNTRY_META[code]
    labels = LABELS.get(meta.language, LABELS["en"])
    short = labels.get("desc_tagline", labels["tagline"])
    return short.format(name=meta.name) + " " + labels["desc_clause"]


def set_about(code: str, dry_run: bool = False) -> None:
    repo = f"legalize-{code}"
    home = f"https://legalize.dev/{code}"
    fields = ["-f", f"homepage={home}"]
    changes = []
    if gh_json(repo, ".homepage") != home:
        changes.append("homepage")

    desc = None
    if code not in PRESERVE_DESCRIPTION:
        desc = description_for(code)
        if len(desc) > 350:
            desc = desc[:347] + "..."
        fields += ["-f", f"description={desc}"]
        if gh_json(repo, ".description") != desc:
            changes.append("description")

    if not changes:
        print(f"  {repo}: up to date")
        return

    print(f"  {repo}: setting {', '.join(changes)}")
    if desc:
        print(f"      desc: {desc}")
    if dry_run:
        return

    r = subprocess.run(["gh", "api", "--method", "PATCH", f"repos/{OWNER}/{repo}", *fields],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"      ERROR: {r.stderr.strip()}")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    codes = [a for a in sys.argv[1:] if not a.startswith("-")] or sorted(COUNTRY_META)
    for code in codes:
        set_about(code, dry_run=dry)
