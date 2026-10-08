"""Fetch a resumable Section I tranche, retaining raw HTTP cache, XML and exclusions."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import gzip
import json
import logging
from pathlib import Path
import re

from legalize.config import load_config
from legalize.fetcher.es.client import BOEClient
from legalize.fetcher.es.diary import ExcludedDiary, fetch_diary, record_exclusion
from legalize.fetcher.es.discovery import diary_identifiers
from legalize.storage import save_structured_json


def fetch_tranche(config, identifiers: list[str], suppressed: set[str]) -> dict:
    cc = config.get_country("es")
    data = Path(cc.data_dir)
    raw_dir = data / "diary-raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    def fetch(identifier):
        if (data / "json" / f"{identifier}.json").exists():
            return identifier, "cached", None
        if (data / "excluded" / f"{identifier}.json").exists():
            return identifier, "excluded", None
        try:
            if identifier in suppressed:
                raise ExcludedDiary("source-suppressed", identifier)
            with BOEClient.create(cc) as client:
                path = raw_dir / f"{identifier}.xml.gz"
                if path.exists():
                    raw = gzip.decompress(path.read_bytes())
                else:
                    raw = client.get_disposition_xml(identifier)
                    temporary = path.with_suffix(".tmp")
                    temporary.write_bytes(gzip.compress(raw, mtime=0))
                    temporary.replace(path)
                norm = fetch_diary(client, identifier, xml_data=raw)
                save_structured_json(data, norm)
            return identifier, "fetched", None
        except ExcludedDiary as exc:
            record_exclusion(data, exc)
            return identifier, "excluded", None
        except Exception as exc:
            logging.exception("Could not fetch %s", identifier)
            return identifier, "failed", str(exc)

    counts = Counter()
    failed = {}
    report = {"requested": len(identifiers), "counts": counts, "failed": failed}
    with ThreadPoolExecutor(max_workers=cc.max_workers) as pool:
        for offset in range(0, len(identifiers), 100):
            for identifier, status, error in pool.map(fetch, identifiers[offset : offset + 100]):
                counts[status] += 1
                if error:
                    failed[identifier] = error
            temporary = data / "diary-fetch-progress.tmp"
            temporary.write_text(json.dumps(report, indent=2) + "\n")
            temporary.replace(data / "diary-fetch-progress.json")
            print(json.dumps(report), flush=True)
            if len(failed) >= 20:
                break
    exclusions = [
        json.loads(path.read_text()) for path in sorted((data / "excluded").glob("*.json"))
    ]
    (data / "skipped-low-density.json").write_text(
        json.dumps(
            [record for record in exclusions if record["reason"] == "low-density"],
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    if failed:
        raise RuntimeError(
            f"{len(failed)} source records failed; inspect diary-fetch-progress.json"
        )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--since", type=date.fromisoformat, default=date(2010, 1, 1))
    parser.add_argument("--through", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    config = load_config(args.config)
    cc = config.get_country("es")
    if args.since > args.through:
        parser.error("--since must not be after --through")
    with BOEClient.create(cc) as client:
        identifiers = sorted(set(diary_identifiers(client, cc.data_dir, args.since, args.through)))
        robots = client._fetch("https://www.boe.es/robots.txt").decode("utf-8")
    suppressed = set(re.findall(r"BOE-[A-Z]+-\d{4}-\d+", robots))
    print(json.dumps(fetch_tranche(config, identifiers, suppressed)), flush=True)


if __name__ == "__main__":
    main()
