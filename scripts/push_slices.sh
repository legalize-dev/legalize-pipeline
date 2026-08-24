#!/usr/bin/env bash
# Push a country repo's history in slices, for repos too big for one push.
#
# GitHub refuses any pack over 2.00 GiB:
#   remote: fatal: pack exceeds maximum allowed size (2.00 GiB)
# ...but you rarely see that line. pack-objects spends 20-30 minutes computing
# deltas before a single byte goes out, github's sshd closes the idle connection
# first, and all you get is "the remote end hung up unexpectedly". Hence the
# keepalives below: without them you diagnose the wrong problem for hours.
#
#   scripts/push_slices.sh ../countries/pt            # 25000 commits per slice
#   scripts/push_slices.sh ../countries/pt 10000      # smaller slices
#   scripts/push_slices.sh ../countries/pt --dry-run  # just show the slices
#   START=7 scripts/push_slices.sh ../countries/pt    # resume at slice 7
#
# FORCE=1 pushes with --force: needed only when the remote holds an unrelated
# history (a re-bootstrap), and it rewrites the public repo. Know why first.
#
# See adding-a-country/step-9-production.md §9.4.
set -uo pipefail

# --dry-run is honoured in any position: this pushes to a public repo, so a
# misplaced flag must never mean "push for real".
DRY_RUN=0
ARGS=()
for arg in "$@"; do
  if [ "$arg" = "--dry-run" ]; then DRY_RUN=1; else ARGS+=("$arg"); fi
done
set -- ${ARGS[@]+"${ARGS[@]}"}

REPO=${1:?usage: push_slices.sh <repo-path> [slice-size] [--dry-run]}
SLICE=${2:-25000}

# Bigger slices are cheaper: every slice re-walks the commits before it to
# exclude them, and cross-slice delta bases cannot be reused. Use the biggest
# slice that stays under 2 GiB, not the smallest that works. ~25000 commits of
# consolidated law lands around 240 MB.
# bash 3.2 (macOS) has no mapfile, so append in a loop.
SLICES=()
while IFS= read -r sha; do
  SLICES+=("$sha")
done < <(git -C "$REPO" rev-list --reverse HEAD | awk -v n="$SLICE" 'NR % n == 0')
TOTAL=$((${#SLICES[@]} + 1))

if [ "$DRY_RUN" = 1 ]; then
  n=0
  for sha in ${SLICES[@]+"${SLICES[@]}"}; do
    n=$((n + 1))
    echo "slice $n/$TOTAL -> ${sha:0:12}"
  done
  echo "slice $TOTAL/$TOTAL -> HEAD (remainder)"
  exit 0
fi

# pack-objects goes quiet for minutes at a time; without these the connection
# dies mid-computation and the real error never arrives.
export GIT_SSH_COMMAND="ssh -o ServerAliveInterval=15 -o ServerAliveCountMax=20 -o TCPKeepAlive=yes"
PUSH_FLAGS=(--progress)
[ "${FORCE:-0}" = 1 ] && PUSH_FLAGS+=(--force)

push_one() {
  # A push can also hang with the connection alive, waiting on a remote that
  # never answers — 1h27m of nothing, observed. Cap it and retry once.
  timeout 2700 git -C "$REPO" push "${PUSH_FLAGS[@]}" origin "$1" 2>&1 \
    | tr "\r" "\n" | grep -vE "^ *(Enumerating|Counting)" | tail -20
  return "${PIPESTATUS[0]}"
}

n=0
for sha in ${SLICES[@]+"${SLICES[@]}"} HEAD; do
  n=$((n + 1))
  [ "$n" -lt "${START:-1}" ] && continue
  echo "[$(date '+%H:%M:%S')] slice $n/$TOTAL -> ${sha:0:12}"
  if ! push_one "$sha:refs/heads/main"; then
    echo "[$(date '+%H:%M:%S')] slice $n failed, retrying in 30s"
    sleep 30
    if ! push_one "$sha:refs/heads/main"; then
      echo "[$(date '+%H:%M:%S')] slice $n failed twice — stopping. Resume with START=$n"
      exit 1
    fi
  fi
  echo "[$(date '+%H:%M:%S')] slice $n/$TOTAL ok"
done
echo "[$(date '+%H:%M:%S')] all slices pushed"
