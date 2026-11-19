"""Check that every Macedonian amending act and correction in the repository is a commit on its law."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from legalize.fetcher.mk.client import _amended_title, _normal_title


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
    """Return (amending act, law) pairs present in the repository with no commit.

    Two checks, since each catches what the other cannot. Every act a law's
    LDBIS card chain links, as saved in the law's reforms, must be a commit on
    that law. And each amending act is matched to the law its title names, by
    title alone and not through those links, so an amendment the links miss
    still fails here. A correction of a law, or of an act amending it, counts as
    an amending act of that law. Where several enactments share the title, the act
    belongs to the latest one published on or before it. A consolidated text
    ("Пречистена верзија") carries its law's title but enacts nothing, so it
    takes no amendment, as in the client. An act or law that is not in the
    repository has nothing to be committed.
    """
    files = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in Path(data_dir, "json").glob("*.json")
    ]
    records = [file["metadata"] for file in files]
    in_repository = {meta["identifier"] for meta in records}
    enactments: dict[str, list[tuple[str, str]]] = {}
    for meta in records:
        version = dict(meta.get("extra") or {}).get("version")
        if not _amended_title(meta["title"]) and version != "Пречистена верзија":
            enactments.setdefault(_normal_title(meta["title"]), []).append(
                (meta["publication_date"], meta["identifier"])
            )
    pairs = published_pairs(repo_dir)
    missing: set[tuple[str, str]] = set()
    for file in files:
        law = file["metadata"]["identifier"]
        for reform in file["reforms"]:
            act = reform["source_id"]
            if act != law and act in in_repository and (act, law) not in pairs:
                missing.add((act, law))
    for meta in records:
        target = _amended_title(meta["title"])
        earlier = [
            enactment
            for enactment in enactments.get(target or "", [])
            if enactment[0] <= meta["publication_date"]
        ]
        if not earlier:
            continue
        law = max(earlier)[1]
        if (meta["identifier"], law) not in pairs:
            missing.add((meta["identifier"], law))
    return sorted(missing)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--repo-dir", required=True)
    args = parser.parse_args()
    missing = missing_reforms(args.data_dir, args.repo_dir)
    if missing:
        for source_id, norm_id in missing:
            print(f"MISSING reform Source-Id={source_id} Norm-Id={norm_id}")
        print(f"FAIL: {len(missing)} amending act(s) or correction(s) have no commit on their law")
        return 1
    print(
        "PASS: every amending act and correction whose law is in the repository is a commit on it"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
