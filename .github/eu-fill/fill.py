"""Temporary: publish the EU acts the corpus missed between its pin and today.

1,006 acts published 2026-03-26..10-06 fell between the corpus pin (03-25) and the
first day of the corrected daily (10-07), and 28 after it were read before CELLAR
indexed them. 26 consolidations created weeks after their date never reached their
law. Each goes through the daily's own path (fetch_act, save_structured_json,
commit_one), oldest first, so dates and identity are the daily's.

  python fill.py <repo> <data_dir>
"""

import csv
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from legalize.committer.git_ops import GitRepo
from legalize.config import load_config
from legalize.fetcher.eu.client import EURLexClient
from legalize.fetcher.eu.daily import _published_file, fetch_act
from legalize.fetcher.eu.parser import PendingStatus
from legalize.pipeline import commit_one
from legalize.storage import save_structured_json

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
here = Path(__file__).parent
repo_path, data_dir = sys.argv[1:3]
config = load_config(
    "config.yaml", {"countries.eu.repo_path": repo_path, "countries.eu.data_dir": data_dir}
)
cc = config.get_country("eu")
repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)

acts = sorted(
    csv.DictReader(open(here / "missing_acts_1034.tsv"), delimiter="\t"),
    key=lambda r: (r["publication_date"], r["celex"]),
)
late = sorted(
    csv.DictReader(open(here / "late_consolidations_26.tsv"), delimiter="\t"),
    key=lambda r: (r["consolidation_date"], r["base_act"]),
)
queue = [r["celex"] for r in acts] + list(dict.fromkeys(r["base_act"] for r in late))


def fetch(celex: str):
    with EURLexClient.create(cc) as client:
        metadata = client.get_metadata_sparql(celex)
        return fetch_act(client, celex, metadata, _published_file(repo, celex), cc.data_dir)


created, held, failed = 0, [], []
with ThreadPoolExecutor(max_workers=cc.max_workers or 1) as pool:
    futures = [(celex, pool.submit(fetch, celex)) for celex in queue]
    for n, (celex, future) in enumerate(futures, 1):  # git writes stay serial, oldest first
        try:
            norm = future.result()
            save_structured_json(cc.data_dir, norm)
            made = commit_one(config, "eu", norm.metadata.identifier)
            created += made
            print(f"{n}/{len(queue)} {celex}: {made} commit(s)", flush=True)
        except PendingStatus as exc:
            held.append(celex)
            print(f"{n}/{len(queue)} {celex}: held, {exc}", flush=True)
        except Exception as exc:  # reported, never hidden: the job ends red below
            failed.append(celex)
            print(f"{n}/{len(queue)} {celex}: FAILED {type(exc).__name__}: {exc}", flush=True)

print(f"\ncommits {created}; held {len(held)}: {' '.join(held)}")
print(f"failed {len(failed)}: {' '.join(failed)}")
sys.exit(1 if failed else 0)
