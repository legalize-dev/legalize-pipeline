"""Check that saved Macedonian reform links became commits on their law."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def published_pairs(repo_dir: str | Path) -> set[tuple[str, str]]:
    """Return the Source-Id and Norm-Id pairs already present in Git history."""
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_dir),
            "log",
            "--all",
            "--format=%(trailers:key=Source-Id,valueonly,separator=)%x09%(trailers:key=Norm-Id,valueonly,separator=)%x00",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    pairs: set[tuple[str, str]] = set()
    for record in result.stdout.split("\0"):
        source_id, separator, norm_id = record.strip().partition("\t")
        if separator and source_id and norm_id:
            pairs.add((source_id.strip(), norm_id.strip()))
    return pairs


def missing_reforms(data_dir: str | Path, repo_dir: str | Path) -> list[tuple[str, str]]:
    """Return saved reform links whose generated commit is absent.

    The JSON is the fetcher's record of the source relationship. A reform is
    required only when its target law has a JSON file and its Source-Id/Norm-Id
    pair is absent from the target repository's history.
    """
    json_dir = Path(data_dir) / "json"
    files = {path.stem: path for path in json_dir.glob("*.json")}
    pairs = published_pairs(repo_dir)
    missing: list[tuple[str, str]] = []
    for norm_id, path in files.items():
        record = json.loads(path.read_text(encoding="utf-8"))
        metadata = record.get("metadata", {})
        norm_id = metadata.get("identifier", norm_id)
        for reform in record.get("reforms", []):
            source_id = reform.get("source_id")
            if not source_id or source_id == norm_id or source_id not in files:
                continue
            if (source_id, norm_id) not in pairs:
                missing.append((source_id, norm_id))
    return sorted(set(missing))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--repo-dir", required=True)
    args = parser.parse_args()
    missing = missing_reforms(args.data_dir, args.repo_dir)
    if missing:
        for source_id, norm_id in missing:
            print(f"MISSING reform Source-Id={source_id} Norm-Id={norm_id}")
        print(f"FAIL: {len(missing)} reform link(s) have no generated commit")
        return 1
    print("PASS: every saved Macedonian reform link has a generated commit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
