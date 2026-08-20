#!/usr/bin/env python3
"""Rewrite historical reformed commits in legalize-ie to match the standard format.

The ~560 [reforma] commits created by the original revised.py used:
  Subject: [reforma] IE-2024-act-7 — consolidated version 2024-03-15
  Trailers: Source-Id=IE-2024-act-7, Norm-Id=IE-2024-act-7

The standard format (from build_commit_info) should be:
  Subject: [reform] Finance Act 2024
  Trailers: Source-Id=revised-IE-2024-act-7, Norm-Id=IE-2024-act-7

This script uses git filter-repo to fix the commit messages.

⚠️  DESTRUCTIVE: This rewrites history. Requires force-push.

Usage:
    cd /path/to/legalize-ie
    pip install git-filter-repo
    python scripts/fix_ie_revised_commits.py
    git push --force origin main

Or dry-run (prints what would change):
    python scripts/fix_ie_revised_commits.py --dry-run
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    # Verify we're in a git repo
    repo = Path.cwd()
    if not (repo / ".git").exists():
        print("Error: not in a git repo root. cd to legalize-ie first.")
        sys.exit(1)

    # Get all commits with [reforma] in the subject
    result = subprocess.run(
        [
            "git", "log", "--all",
            "--format=%H %s",
            "--grep=\\[reforma\\]",
        ],
        capture_output=True,
        text=True,
        cwd=repo,
    )

    commits = result.stdout.strip().splitlines()
    if not commits:
        print("No [reforma] commits found.")
        return

    print(f"Found {len(commits)} [reforma] commit(s) to rewrite.")

    if dry_run:
        print("\nDry-run — showing what would change:\n")
        for line in commits[:10]:
            sha, subject = line.split(" ", 1)
            # Parse: [reforma] IE-2024-act-7 — consolidated version 2024-03-15
            m = re.match(
                r"\[reforma\]\s+(IE-\d{4}-act-\d+)\s+—\s+consolidated version\s+(.+)",
                subject,
            )
            if m:
                norm_id = m.group(1)
                new_subject = f"[reform] {norm_id}"
                print(f"  {sha[:8]}: {subject}")
                print(f"        → {new_subject}")
                print(f"        Source-Id: {norm_id} → revised-{norm_id}")
                print()
        if len(commits) > 10:
            print(f"  ... and {len(commits) - 10} more")
        print("\nRun without --dry-run to apply changes.")
        return

    # Create the message callback script for git filter-repo
    callback_script = repo / ".git" / "_rewrite_callback.py"
    callback_script.write_text(
        '''
import re

def msg_callback(message):
    msg = message.decode("utf-8", errors="replace")

    # Fix subject: [reforma] IE-YYYY-act-N — consolidated version DATE
    # →            [reform] IE-YYYY-act-N
    m = re.match(
        r"\\[reforma\\]\\s+(IE-\\d{4}-act-\\d+)\\s+—\\s+consolidated version\\s+(.+)",
        msg.split("\\n")[0],
    )
    if not m:
        return message  # Not a reforma commit, leave unchanged

    norm_id = m.group(1)
    lines = msg.split("\\n")

    # Fix subject line
    lines[0] = f"[reform] {norm_id}"

    # Fix Source-Id trailer: norm_id → revised-norm_id
    for i, line in enumerate(lines):
        if line.startswith("Source-Id:"):
            sid = line.split(":", 1)[1].strip()
            if not sid.startswith("revised-"):
                lines[i] = f"Source-Id: revised-{sid}"

    return "\\n".join(lines).encode("utf-8")

def commit_callback(commit):
    commit.message = msg_callback(commit.message)
'''
    )

    print("Running git filter-repo...")
    result = subprocess.run(
        [
            sys.executable, "-m", "git_filter_repo",
            "--force",
            "--commit-callback",
            f"exec(open(r'{callback_script}').read()); commit_callback(commit)",
        ],
        cwd=repo,
    )

    if result.returncode == 0:
        print("\n✓ History rewritten successfully.")
        print("  Run: git push --force origin main")
    else:
        print(f"\n✗ git filter-repo failed with code {result.returncode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
