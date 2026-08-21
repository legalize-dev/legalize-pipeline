#!/usr/bin/env bash
# Portugal: wait out the running fetches, close the gap, rebuild the repo.
#
# Chains the last three steps of the rebuild so they run unattended:
#   1. wait for the fetch/thesaurus jobs already in flight
#   2. fetch whatever the discovery lists have and the cache does not — twice, so a
#      transient failure gets a second chance rather than a hole in the corpus
#   3. reparse from raw with the final parser + thesaurus, then rebuild and health
#
# Does NOT push. The repo is left built for inspection.
#
#   scripts/pt_overnight.sh [PID ...]
set -uo pipefail
cd "$(dirname "$0")/.."

stamp() { date "+%Y-%m-%d %H:%M:%S"; }
say() { echo "[$(stamp)] $*"; }

say "waiting on ${#@} job(s): $*"
for pid in "$@"; do
    while kill -0 "$pid" 2>/dev/null; do sleep 60; done
    say "pid $pid finished"
done

for pass in 1 2; do
    say "gap pass $pass"
    python3 scripts/pt_fetch_missing.py || say "gap pass $pass exited non-zero, continuing"
done

say "final coverage"
python3 scripts/pt_fetch_missing.py --report

say "reparse + rebuild"
bash scripts/pt_reparse_and_bootstrap.sh
say "done (nothing pushed)"
