#!/usr/bin/env bash
# One-shot: seed opolex-laws-es from legalize-dev/legalize-es so the BOE
# bootstrap (which would otherwise hit BOE for every law) is skipped.
#
# Usage:
#   scripts/setup-opolex.sh <github-owner>/<repo>  <local-dest-dir>
#
# Example:
#   scripts/setup-opolex.sh klomoli/opolex-laws-es ../opolex-laws-es
set -euo pipefail

slug="${1:?owner/repo arg}"
dest="${2:?dest path}"

if [ -e "$dest" ]; then
  echo "Destination $dest already exists — refusing to overwrite." >&2
  exit 1
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
git clone --depth=1 https://github.com/legalize-dev/legalize-es.git "$tmp/seed"

mkdir -p "$dest"
cd "$dest"
git init -b main
shopt -s extglob
cp -r "$tmp/seed"/es*/ .

# The legalize CLI infers the daily cursor from the most recent commit that
# carries a "Source-Date:" trailer (see legalize.state.store.infer_last_date_from_git).
# We embed it in the seed commit message so the very first `daily` run can
# pick up from SEED_DATE+1 instead of failing with "No last summary found".
SEED_DATE="$(date -I)"

cat > README.md <<'EOF'
# opolex-laws-es

OpoLex-internal corpus of Spanish legislation (BOE) in Markdown form.

Initially seeded from <https://github.com/legalize-dev/legalize-es> (BOE
content is public domain under Art. 13 LPI). Subsequent commits are produced
by our own run of <https://github.com/legalize-dev/legalize-pipeline> (MIT)
on a GitHub Action.
EOF

git add .
GIT_AUTHOR_DATE="${SEED_DATE}T00:00:00Z" GIT_COMMITTER_DATE="${SEED_DATE}T00:00:00Z" \
  git -c user.name=opolex-bot -c user.email=bot@opolex.app \
  commit -m "$(printf '[bootstrap] seed from BOE via legalize-pipeline\n\nSource-Date: %s\n' "$SEED_DATE")"

git remote add origin "git@github.com:${slug}.git"
git push -u origin main

echo
echo "Seed complete. Files: $(find . -name '*.md' | wc -l)."
