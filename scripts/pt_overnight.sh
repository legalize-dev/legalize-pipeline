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

# The sampled thesaurus stalls at the long tail — it labelled 4,724 of the 11,258
# descriptor ids the corpus uses. This goes after the ones it missed, and has to
# run here, once the cache is complete, or the ids from the last diplomas fetched
# would have no label baked into the reparse below.
say "descriptor gap"
python3 scripts/pt_thesaurus_gap.py || say "thesaurus gap exited non-zero, continuing"

# 12 % of consolidated diplomas come back with an empty ELIMetadataHTML — the
# Código Civil among them — so eli:is_about names nothing and they would ship with
# no subjects. AnaliseJuridica still has them.
say "subject gap (consolidated)"
python3 scripts/pt_subjects_gap.py || say "subject gap exited non-zero, continuing"

say "reparse + rebuild"
bash scripts/pt_reparse_and_bootstrap.sh
say "done (nothing pushed)"
