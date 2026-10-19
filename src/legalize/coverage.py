"""What a repo holds, measured against its source (Legalize Format Spec v0.5, §Coverage).

Three pieces, one per question the spec asks:

- Why did a norm fail? ``record_failure`` keeps the reason next to the data, and
  ``clear_failure`` drops it once the norm succeeds, so a stale reason never
  outlives the problem.
- What is in the repo? ``coverage_report`` counts the law files and the gaps they
  record themselves (``source_version_gaps``, ``undated_amendments``).
- What is missing? Every discovered or failed norm without a file, with its reason.

A network error is a failed run, not a gap: it is recorded with ``transient`` set,
so a report that still lists one says the run is unfinished rather than final.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import yaml

GAP_FIELDS = {"source_version_gaps": "version_gaps", "undated_amendments": "undated_amendments"}


def _failure_path(data_dir: str | Path, norm_id: str) -> Path:
    safe = norm_id.replace(":", "-").replace("/", "-").replace(" ", "")
    return Path(data_dir) / "failures" / f"{safe}.json"


def is_transient(exc: BaseException) -> bool:
    """A retry may succeed: network trouble and server errors, not absent sources."""
    import requests

    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code not in (404, 410)
    if isinstance(exc, FileNotFoundError):
        return False
    return isinstance(exc, (requests.RequestException, OSError))


def record_failure(data_dir: str | Path, norm_id: str, exc: BaseException) -> None:
    path = _failure_path(data_dir, norm_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "identifier": norm_id,
                "reason": f"{type(exc).__name__}: {exc}"[:500],
                "transient": is_transient(exc),
                "at": date.today().isoformat(),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def clear_failure(data_dir: str | Path, norm_id: str) -> None:
    _failure_path(data_dir, norm_id).unlink(missing_ok=True)


def unresolved(data_dir: str | Path, norm_ids) -> list[str]:
    """The failed norms a retry may still fix: network trouble, or no recorded reason."""
    pending = []
    for norm_id in norm_ids:
        path = _failure_path(data_dir, norm_id)
        record = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if record is None or record.get("transient"):
            pending.append(norm_id)
    return pending


def _frontmatter(path: Path) -> dict:
    lines = []
    with path.open(encoding="utf-8") as handle:
        if handle.readline().strip() != "---":
            return {}
        for line in handle:
            if line.strip() == "---":
                break
            lines.append(line)
    try:
        return yaml.safe_load("".join(lines)) or {}
    except yaml.YAMLError:
        return {}


def coverage_report(repo_dir: str | Path, data_dir: str | Path, source_index: str) -> dict:
    """The ``coverage.json`` body for a repo, measured now."""
    repo, data = Path(repo_dir), Path(data_dir)
    laws = [
        path
        for directory in sorted(repo.iterdir())
        if directory.is_dir() and not directory.name.startswith(".")
        for path in sorted(directory.rglob("*.md"))
    ]
    published = {path.stem for path in laws}
    counts = {key: 0 for total in GAP_FIELDS.values() for key in (total, f"laws_with_{total}")}
    for path in laws:
        front = _frontmatter(path)
        for field, total in GAP_FIELDS.items():
            if raw := front.get(field):
                items = json.loads(raw) if isinstance(raw, str) else raw
                counts[total] += len(items)
                counts[f"laws_with_{total}"] += 1
    index = data / "discovery_ids.txt"
    discovered = (
        [line.strip() for line in index.read_text().splitlines() if line.strip()]
        if index.exists()
        else []
    )
    failures = {}
    for path in sorted((data / "failures").glob("*.json")) if (data / "failures").exists() else []:
        record = json.loads(path.read_text(encoding="utf-8"))
        failures[record["identifier"]] = record
    excluded = [
        {
            "identifier": norm_id,
            "reason": failures.get(norm_id, {}).get("reason", "not fetched"),
            **({"transient": True} if failures.get(norm_id, {}).get("transient") else {}),
        }
        for norm_id in sorted(set(discovered) | set(failures))
        if norm_id not in published
    ]
    return {
        "spec_version": "0.5",
        "as_of": date.today().isoformat(),
        "source_index": source_index,
        "discovered": len(discovered),
        "published": len(laws),
        "excluded": excluded,
        "laws_with_version_gaps": counts["laws_with_version_gaps"],
        "version_gaps": counts["version_gaps"],
        "laws_with_undated_amendments": counts["laws_with_undated_amendments"],
        "undated_amendments": counts["undated_amendments"],
    }


def render(report: dict, previous: str | None = None) -> str:
    """Serialise, keeping the previous ``as_of`` when nothing else changed.

    Without this a daily run would commit a new coverage.json every day for its
    date alone, and the meta commits would drown the history they describe.
    """
    if previous:
        try:
            old = json.loads(previous)
        except ValueError:
            old = None
        if old and {**old, "as_of": report["as_of"]} == report:
            report = {**report, "as_of": old["as_of"]}
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"
