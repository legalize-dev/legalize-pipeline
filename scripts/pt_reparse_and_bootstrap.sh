#!/usr/bin/env bash
# Portugal: reparse everything from the raw cache, then rebuild the repo.
#
# The fetch cache under {data_dir}/raw/ holds the source envelopes, so this runs
# without touching DRE. Do it once at the end so the whole corpus is parsed by the
# final parser, with the descriptor thesaurus installed.
set -euo pipefail
cd "$(dirname "$0")/.."

# Overridable so the whole chain can be rehearsed on a slice of the cache before
# it is trusted with the real one.
CONFIG=${CONFIG:-config.yaml}
DATA=${DATA:-../countries/data-pt}
REPO=${REPO:-../countries/pt}

# Set when json/ is already right and only the repo has to be rebuilt — after a
# repair that touched a handful of norms, say. The history is chronological, so the
# commit half is all-or-nothing even when the parse half is not.
if [ "${ONLY_COMMIT:-0}" = "1" ]; then
  echo "==> ONLY_COMMIT: keeping json/ as it is ($(find "$DATA/json" -name '*.json' | wc -l | tr -d ' ') files)"
else

# json/ is keyed by identifier, and the identifier scheme changed under it (one
# prefix per type now, and the Jornal Oficial dos Açores is out of scope). A stale
# file is not overwritten by the reparse, it is simply left behind — and
# commit_all_fast reads the directory, not the id list, so every one of them would
# ship as a ghost law. raw/ is the source of truth; json/ is derived. Wipe it.
echo "==> wipe json/ ($(find "$DATA/json" -name '*.json' 2>/dev/null | wc -l | tr -d ' ') stale files)"
rm -rf "$DATA/json"
mkdir -p "$DATA/json"

# Built before the reparse: last_amendment turns an as_enacted file from a silent
# 1994 text into one that names the act that changed it.
echo "==> amendment index"
CONFIG="$CONFIG" python3 scripts/pt_amendments.py || echo "    (amendment index failed, continuing without last_amendment)"

echo "==> reparse ($(find "$DATA/raw" -name '*.versions.json.gz' | wc -l | tr -d ' ') cached norms)"
CONFIG="$CONFIG" python3 scripts/pt_reparse.py

fi

echo "==> wipe and re-init the repo"
rm -rf "$REPO"
git init -q "$REPO"
mkdir -p "$REPO/pt"
git -C "$REPO" commit -q --allow-empty -m "[bootstrap] Init legalize-pt"
git -C "$REPO" remote add origin git@github.com:legalize-dev/legalize-pt.git

# Not generic_bootstrap: that re-runs discovery and fetch_all first, which after a
# reparse is a second full parse of the same 200,000 envelopes for no new data.
# The reparse above already wrote json/; this is the commit half of bootstrap.
echo "==> commit"
python3 -c "
import sys; sys.path.insert(0,'src')
from legalize.config import load_config
from legalize.pipeline import commit_all_fast, write_country_meta, write_repo_meta
config = load_config('$CONFIG')
total = commit_all_fast(config, 'pt')
write_country_meta(config, 'pt')
write_repo_meta(config, 'pt')
print(f'{total} commits')
"

echo "==> health"
python3 -c "
import sys; sys.path.insert(0,'src')
from legalize.cli import cli
cli(['--config','$CONFIG','health','-c','pt'], standalone_mode=False)
"
