#!/usr/bin/env python3
"""Push generated repo-meta files (README.md, .github/FUNDING.yml) to country repos.

Backfill tool for repos that already exist on GitHub. For NEW countries the
normal pipeline already writes & commits these files during bootstrap (see
``legalize.pipeline.write_repo_meta``); this script is for pushing them to live
repos without a local clone — it uses the GitHub Git Data API via ``gh`` (no
clone, never touches the law blobs).

Content comes from ``legalize.committer.repo_meta.repo_meta_files`` (single
source of truth: ``src/legalize/readme_data.json``). Commits are authored by the
Legalize bot. Idempotent: skips files already matching the default branch.

Usage:
    python scripts/push_repo_meta.py            # all countries in COUNTRY_META
    python scripts/push_repo_meta.py es fr de   # specific countries
    python scripts/push_repo_meta.py --dry-run es
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys

from legalize.committer.repo_meta import repo_meta_files
from legalize.country_meta import COUNTRY_META

OWNER = "legalize-dev"
BOT_NAME = "Legalize"
BOT_EMAIL = "legalize@legalize.dev"
COMMIT_MESSAGE = "[fix-pipeline] Add README and funding metadata"


def gh(args: list[str], body: dict | None = None) -> dict | list | str:
    cmd = ["gh", "api"] + args
    inp = None
    if body is not None:
        cmd += ["--input", "-"]
        inp = json.dumps(body)
    res = subprocess.run(cmd, input=inp, capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(f"gh api failed: {' '.join(args)}\n{res.stderr}")
    out = res.stdout.strip()
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return out


def remote_content(repo: str, path: str) -> str | None:
    res = subprocess.run(
        ["gh", "api", f"repos/{OWNER}/{repo}/contents/{path}", "--jq", ".content"],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        return None
    try:
        return base64.b64decode(res.stdout.strip().replace("\n", "")).decode("utf-8")
    except Exception:
        return None


def push_country(code: str, dry_run: bool = False) -> bool:
    repo = f"legalize-{code}"
    files = repo_meta_files(code)
    changed = {p: c for p, c in files.items() if remote_content(repo, p) != c}
    if not changed:
        print(f"  {repo}: already up to date")
        return False

    print(f"  {repo}: pushing {', '.join(sorted(changed))}")
    if dry_run:
        return True

    base_sha = gh([f"repos/{OWNER}/{repo}/git/refs/heads/main", "--jq", ".object.sha"])
    base_tree = gh([f"repos/{OWNER}/{repo}/git/commits/{base_sha}", "--jq", ".tree.sha"])
    tree_entries = []
    for path, content in changed.items():
        blob = gh([f"repos/{OWNER}/{repo}/git/blobs", "--method", "POST"],
                  {"content": content, "encoding": "utf-8"})
        tree_entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    tree = gh([f"repos/{OWNER}/{repo}/git/trees", "--method", "POST"],
              {"base_tree": base_tree, "tree": tree_entries})
    commit = gh([f"repos/{OWNER}/{repo}/git/commits", "--method", "POST"], {
        "message": COMMIT_MESSAGE,
        "tree": tree["sha"],
        "parents": [base_sha],
        "author": {"name": BOT_NAME, "email": BOT_EMAIL},
        "committer": {"name": BOT_NAME, "email": BOT_EMAIL},
    })
    gh([f"repos/{OWNER}/{repo}/git/refs/heads/main", "--method", "PATCH"], {"sha": commit["sha"]})
    print(f"  {repo}: committed {commit['sha'][:10]}")
    return True


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    codes = [a for a in sys.argv[1:] if not a.startswith("-")] or sorted(COUNTRY_META)
    for code in codes:
        push_country(code, dry_run=dry)
