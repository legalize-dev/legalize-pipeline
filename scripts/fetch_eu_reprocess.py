#!/usr/bin/env python3
"""Snapshot every English source version of the laws in an existing EU repo.

This only downloads sources. It never edits a corpus or publishes anything.
Resume with the same arguments; completed source files are reused.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

from legalize.fetcher.eu.client import EURLexClient, _CDM, _LANG_ENG, select_versions


def snapshot(
    repo: Path, data_dir: Path, workers: int, *, pdf_only: bool = False, html_only: bool = False
) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    inventory = data_dir / "inventory.json"
    if inventory.exists():
        laws = json.loads(inventory.read_text(encoding="utf-8"))["laws"]
    else:
        head = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip()
        laws = sorted(p.stem for p in (repo / "eu").rglob("*.md"))
        inventory.write_text(
            json.dumps({"head": head, "laws": laws}, indent=2) + "\n", encoding="utf-8"
        )

    with EURLexClient(request_timeout=120, max_retries=5, requests_per_second=workers) as client:
        index_path = data_dir / "versions.json"
        if index_path.exists():
            versions = json.loads(index_path.read_text(encoding="utf-8"))
        else:
            versions = {law: [] for law in laws}

            def build(cursor: str) -> str:
                cursor_filter = f'FILTER(STR(?consCelex) >= "{cursor}")' if cursor else ""
                return f"""PREFIX cdm: <{_CDM}>
SELECT DISTINCT ?baseCelex ?consCelex ?consDate ?manifest ?format WHERE {{
  ?cons cdm:act_consolidated_based_on_resource_legal ?base .
  ?base cdm:resource_legal_id_celex ?baseCelex .
  ?cons cdm:resource_legal_id_celex ?consCelex .
  ?cons cdm:work_date_document ?consDate .
  ?expr cdm:expression_belongs_to_work ?cons .
  ?expr cdm:expression_uses_language <{_LANG_ENG}> .
  ?manifest cdm:manifestation_manifests_expression ?expr .
  ?manifest cdm:manifestation_type ?format .
  {cursor_filter}
}} ORDER BY ?consCelex ?baseCelex ?manifest LIMIT 1000"""

            for celex, rows in client._paged(build, "consCelex"):
                for row in rows:
                    base = row["baseCelex"]["value"]
                    if base not in versions:
                        continue
                    versions[base].append(
                        {
                            "celex": celex,
                            "date": row["consDate"]["value"],
                            "manifest_uri": row["manifest"]["value"],
                            "format": row["format"]["value"],
                        }
                    )
            index_path.write_text(json.dumps(versions, indent=2) + "\n", encoding="utf-8")

        pdf_dir = data_dir / "pdf"
        pdf_dir.mkdir(exist_ok=True)
        pdf_results = {}
        pdf_versions = [
            version
            for rows in versions.values()
            for version in select_versions(rows)
            if version["format"].startswith("pdf")
        ]
        for i, version in enumerate([] if html_only else pdf_versions, 1):
            path = pdf_dir / f"{version['celex']}.pdf"
            if not path.exists():
                raw = client.download_pdf(version)
                temporary = path.with_suffix(".part")
                temporary.write_bytes(raw)
                temporary.replace(path)
            raw = path.read_bytes()
            pdf_results[version["celex"]] = {
                "manifest_uri": version["manifest_uri"],
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            if i % 25 == 0 or i == len(pdf_versions):
                (data_dir / "pdf-downloads.json").write_text(
                    json.dumps(pdf_results, indent=2) + "\n", encoding="utf-8"
                )
                print(f"PDF {i}/{len(pdf_versions)}", flush=True)
        if pdf_only:
            return

        documents = {law: None for law in laws}
        for rows in versions.values():
            for row in select_versions(rows):
                if row["format"] in ("xhtml", "html"):
                    documents[row["celex"]] = row["manifest_uri"]

        source_dir = data_dir / "sources"
        source_dir.mkdir(exist_ok=True)
        checkpoint = data_dir / "downloads.json"
        previous = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else {}
        results = {}

        def fetch(celex: str, manifest: str | None) -> dict:
            if any(c in celex for c in "/\\\0'\""):
                raise ValueError(f"Unsafe source identifier: {celex!r}")
            path = source_dir / f"{celex}.xhtml"
            compressed = path.with_suffix(".xhtml.gz")
            url = (
                manifest
                or f"https://publications.europa.eu/resource/celex/{quote(celex, safe='')}.ENG"
            )
            if compressed.exists():
                raw = gzip.decompress(compressed.read_bytes())
            elif path.exists():
                raw = path.read_bytes()
            else:
                if not manifest:
                    url = client.get_html_manifest_uri(celex)
                    if not url:
                        raise ValueError(f"No English HTML manifestation for {celex}") from None
                logging.info("Downloading %s from %s", celex, url)
                raw = client.download_xhtml(url)
                if b"<html" not in raw.lower():
                    raise ValueError(f"Response for {celex} is not HTML")
                temporary = compressed.with_suffix(".part")
                temporary.write_bytes(gzip.compress(raw, compresslevel=1, mtime=0))
                temporary.replace(compressed)
            digest = hashlib.sha256(raw).hexdigest()
            old = previous.get(celex, {})
            if old.get("sha256") and old["sha256"] != digest:
                raise ValueError(f"{celex}: cached source differs from its frozen checksum")
            return {"url": old.get("url", url), "bytes": len(raw), "sha256": digest}

        print(f"Frozen scope: {len(laws)} laws, {len(documents)} HTML source versions", flush=True)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            pending = {
                executor.submit(fetch, celex, uri): celex for celex, uri in documents.items()
            }
            for i, future in enumerate(as_completed(pending), 1):
                celex = pending[future]
                try:
                    results[celex] = future.result()
                except Exception as exc:
                    results[celex] = dict(previous.get(celex, {}), error=str(exc))
                    print(f"FAILED {celex}: {exc}", flush=True)
                if i % 50 == 0 or i == len(pending):
                    (data_dir / "downloads.json").write_text(
                        json.dumps(results, indent=2) + "\n", encoding="utf-8"
                    )
                    failures = sum("error" in r for r in results.values())
                    print(f"Downloaded {i}/{len(pending)}, failures={failures}", flush=True)
        failures = sum("error" in r for r in results.values())
        if failures:
            raise RuntimeError(f"{failures} sources unavailable; rebuild must not omit them")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_repo", type=Path)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--pdf-only", action="store_true")
    parser.add_argument("--html-only", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    if args.pdf_only and args.html_only:
        parser.error("--pdf-only and --html-only are mutually exclusive")
    snapshot(
        args.source_repo,
        args.data_dir,
        args.workers,
        pdf_only=args.pdf_only,
        html_only=args.html_only,
    )
