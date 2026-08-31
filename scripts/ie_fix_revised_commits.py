#!/usr/bin/env python3
"""Rewrite the Revised Acts commits in legalize-ie to the standard format.

The ~560 commits the first version of ``revised.py`` created are wrong in two
ways. The visible one is the message::

    [reforma] IE-2024-act-7 — consolidated version 2025-12-31
    Source-Id: IE-2024-act-7        ← same value as Norm-Id, so the
    Norm-Id:   IE-2024-act-7          idempotency check can never fire

The one that actually matters is the identity: every one of them is authored
by a person's name and personal address, because the old code set
``GIT_COMMITTER_*`` but left ``GIT_AUTHOR_*`` to the ambient git config. Spec
v0.4 §Git identity says a published corpus carries the pipeline's identity and
nothing else — a commit hash must not depend on which machine ran the job.

So this rewrites both::

    [reform] IE-2024-act-7
    Source-Id: revised-IE-2024-act-7
    Norm-Id:   IE-2024-act-7
    author:    Legalize <legalize@legalize.dev>

The author reset applies to *every* commit that is not already the pipeline
identity, not only the ``[reforma]`` ones — a corpus either carries one
identity or it does not.

⚠️  DESTRUCTIVE: rewrites history, requires a force-push. Pause the daily cron
    before running it (concurrent writes to a country repo lose commits), and
    check that branch protection allows the push.

Usage::

    cd /path/to/legalize-ie
    pip install git-filter-repo
    python /path/to/engine/scripts/ie_fix_revised_commits.py --dry-run
    python /path/to/engine/scripts/ie_fix_revised_commits.py
    git push --force origin main

    python .../ie_fix_revised_commits.py --self-check   # no repo needed
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

AUTHOR_NAME = b"Legalize"
AUTHOR_EMAIL = b"legalize@legalize.dev"

# IE-2024-act-7, plus the C (constitutional amendment) and P (private act)
# forms the id scheme allows — no revised commit uses one today, but a regex
# that silently skips a commit is not what you want on a one-shot rewrite.
_SUBJECT = re.compile(r"\[reforma\]\s+(IE-\d{4}-act-[A-Z]?\d+)\s+—\s+consolidated version\s+\S+")


def rewrite_message(message: bytes) -> bytes:
    """Return the standard-format message for one commit.

    A message that is not a ``[reforma]`` subject comes back unchanged, and a
    message already rewritten comes back unchanged too — the pass is safe to
    run twice.
    """
    msg = message.decode("utf-8", errors="replace")
    lines = msg.split("\n")
    match = _SUBJECT.match(lines[0])
    if not match:
        return message

    norm_id = match.group(1)
    lines[0] = f"[reform] {norm_id}"
    for i, line in enumerate(lines):
        if line.startswith("Source-Id:"):
            source_id = line.split(":", 1)[1].strip()
            if not source_id.startswith("revised-"):
                lines[i] = f"Source-Id: revised-{source_id}"
    return "\n".join(lines).encode("utf-8")


def _self_check() -> None:
    before = (
        "[reforma] IE-2024-act-7 — consolidated version 2025-12-31\n\n"
        "Source-Id: IE-2024-act-7\nSource-Date: 2025-12-31\nNorm-Id: IE-2024-act-7"
    ).encode()
    after = rewrite_message(before).decode()
    assert after.splitlines()[0] == "[reform] IE-2024-act-7", after
    assert "Source-Id: revised-IE-2024-act-7" in after, after
    assert "Norm-Id: IE-2024-act-7" in after, after
    assert "Source-Date: 2025-12-31" in after, after

    # Running it twice must not produce revised-revised-.
    assert rewrite_message(after.encode()) == after.encode()

    # Left alone: bootstrap subjects.
    boot = "[bootstrap] Finance Act 2024 — original version 2024".encode()
    assert rewrite_message(boot) == boot

    # Covered: the C and P id forms.
    ca = "[reforma] IE-2015-act-C34 — consolidated version 2020-01-01\nSource-Id: IE-2015-act-C34"
    assert "revised-IE-2015-act-C34" in rewrite_message(ca.encode()).decode()
    print("self-check OK")


def main() -> None:
    if "--self-check" in sys.argv:
        _self_check()
        return

    repo = Path.cwd()
    if not (repo / ".git").exists():
        sys.exit("Error: not in a git repo root. cd to legalize-ie first.")

    log = subprocess.run(
        ["git", "log", "--all", "--format=%H%x09%an <%ae>%x09%s"],
        capture_output=True,
        text=True,
        cwd=repo,
        check=True,
    ).stdout.splitlines()

    identity = f"{AUTHOR_NAME.decode()} <{AUTHOR_EMAIL.decode()}>"
    messages = [ln for ln in log if _SUBJECT.match(ln.split("\t")[2])]
    identities = [ln for ln in log if ln.split("\t")[1] != identity]

    print(f"{len(log)} commit(s) in the repo")
    print(f"  {len(messages)} with a [reforma] subject to rewrite")
    print(f"  {len(identities)} not authored as {identity}")

    if "--dry-run" in sys.argv:
        for line in messages[:5]:
            sha, author, subject = line.split("\t")
            print(f"\n  {sha[:8]}  {author}")
            print(f"    {subject}")
            print(f"    → {rewrite_message(subject.encode()).decode()}")
            print(f"    → author {identity}")
        if len(messages) > 5:
            print(f"\n  ... and {len(messages) - 5} more")
        print("\nRun without --dry-run to apply. This rewrites history.")
        return

    if not messages and not identities:
        print("Nothing to do.")
        return

    # git-filter-repo execs this string once per commit. It loads this file
    # for rewrite_message rather than duplicating the regex in a string.
    callback = (
        f"commit.author_name = {AUTHOR_NAME!r}\n"
        f"commit.author_email = {AUTHOR_EMAIL!r}\n"
        "import runpy\n"
        f"_m = runpy.run_path({str(Path(__file__).resolve())!r})\n"
        "commit.message = _m['rewrite_message'](commit.message)\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "git_filter_repo", "--force", "--commit-callback", callback],
        cwd=repo,
    )
    if result.returncode != 0:
        sys.exit(f"git filter-repo failed with code {result.returncode}")

    print("\n✓ History rewritten. Now: git push --force origin main")


if __name__ == "__main__":
    main()
