#!/usr/bin/env python3
"""Parse a frozen, downloaded EU scope without rewriting or publishing history."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path

from legalize.fetcher.eu.client import EURLexClient, select_versions
from legalize.fetcher.eu.parser import EURLexMetadataParser, EURLexTextParser
from legalize.models import ParsedNorm
from legalize.storage import save_structured_json


def prepare(data_dir: Path, laws: list[str], workers: int, accept_gaps: bool) -> None:
    catalog = json.loads((data_dir / "catalog.json").read_text(encoding="utf-8"))
    versions = json.loads((data_dir / "versions.json").read_text(encoding="utf-8"))
    gap_path = data_dir / "source-version-exclusions.json"
    exclusions = json.loads(gap_path.read_text(encoding="utf-8")) if accept_gaps else {}
    results = {}
    with EURLexClient(data_dir=str(data_dir)) as client:
        client._version_index = versions

        def parse(celex: str) -> dict:
            selected = select_versions(versions.get(celex, []))
            gaps = {
                v["celex"]: exclusions[v["celex"]] for v in selected if v["celex"] in exclusions
            }
            included = [v for v in selected if v["celex"] not in gaps]
            for version in [{"celex": celex, "format": "xhtml"}, *included]:
                source_id = version["celex"]
                path = (
                    data_dir / "pdf" / f"{source_id}.pdf"
                    if version["format"].startswith("pdf")
                    else data_dir / "sources" / f"{source_id}.xhtml"
                )
                if not path.exists() and not path.with_suffix(".xhtml.gz").exists():
                    raise ValueError(f"{source_id}: frozen source has not been downloaded")
            rows = json.loads(json.dumps(catalog[celex]))
            rows[0]["hasCons"] = {"value": "true" if included else "false"}
            metadata_data = json.dumps({"results": {"bindings": rows}}).encode("utf-8")
            metadata = EURLexMetadataParser().parse(metadata_data, celex)
            if gaps:
                metadata = replace(
                    metadata,
                    extra=metadata.extra
                    + (
                        (
                            "source_version_gaps",
                            json.dumps(list(gaps.values()), ensure_ascii=False),
                        ),
                    ),
                )
            try:
                raw = client.get_text(
                    celex,
                    meta_data=metadata_data,
                    version_exclusions={key: value["reason"] for key, value in gaps.items()},
                )
                parser = EURLexTextParser()
                norm = ParsedNorm(
                    metadata=metadata,
                    blocks=tuple(parser.parse_text(raw)),
                    reforms=tuple(parser.extract_reforms(raw)),
                )
                save_structured_json(data_dir, norm)
                return {"versions": len(norm.reforms), "source_version_gaps": len(gaps)}
            finally:
                client.evict_cache(celex)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            pending = {executor.submit(parse, celex): celex for celex in laws}
            for i, future in enumerate(as_completed(pending), 1):
                celex = pending[future]
                try:
                    results[celex] = future.result()
                except Exception as exc:
                    results[celex] = {"error": str(exc)}
                    print(f"FAILED {celex}: {exc}", flush=True)
                if i % 100 == 0 or i == len(laws):
                    (data_dir / "parse-results.json").write_text(
                        json.dumps(results, indent=2) + "\n", encoding="utf-8"
                    )
                    failures = sum("error" in r for r in results.values())
                    print(f"Parsed {i}/{len(laws)}, failures={failures}", flush=True)
    failures = sum("error" in r for r in results.values())
    if failures:
        raise RuntimeError(
            f"{failures} laws failed; the frozen scope is not ready for reconstruction"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--only", nargs="+", help="Explicit sample IDs from the frozen inventory")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument(
        "--accept-version-gaps",
        action="store_true",
        help="Use reviewed exclusions and record every gap in the law's metadata",
    )
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    inventory = json.loads((args.data_dir / "inventory.json").read_text(encoding="utf-8"))
    laws = args.only or inventory["laws"]
    if set(laws) - set(inventory["laws"]):
        parser.error("--only must belong to the frozen inventory")
    prepare(args.data_dir, laws, args.workers, args.accept_version_gaps)
