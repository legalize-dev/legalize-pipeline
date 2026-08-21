#!/usr/bin/env bash
# Portugal: reparse everything from the raw cache, then rebuild the repo.
#
# The fetch cache under {data_dir}/raw/ holds the source envelopes, so this runs
# without touching DRE. Do it once at the end so the whole corpus is parsed by the
# final parser, with the descriptor thesaurus installed.
set -euo pipefail
cd "$(dirname "$0")/.."

DATA=../countries/data-pt
REPO=../countries/pt

echo "==> reparse ($(ls "$DATA"/raw/*.versions.json.gz | wc -l) cached norms)"
python3 scripts/pt_reparse.py

echo "==> wipe and re-init the repo"
rm -rf "$REPO"
git init -q "$REPO"
mkdir -p "$REPO/pt"
git -C "$REPO" commit -q --allow-empty -m "[bootstrap] Init legalize-pt"

echo "==> bootstrap"
python3 -c "
import sys; sys.path.insert(0,'src')
from legalize.config import load_config
from legalize.pipeline import generic_bootstrap
generic_bootstrap(load_config('config.yaml'), 'pt')
"

echo "==> health"
python3 -c "
import sys; sys.path.insert(0,'src')
from legalize.cli import cli
cli(['health','-c','pt'], standalone_mode=False)
"
