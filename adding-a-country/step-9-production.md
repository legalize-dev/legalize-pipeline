# Step 9: Full bootstrap and push to production

> Step 9 of 9 · [index](README.md) · previous: [`step-8-workers.md`](step-8-workers.md)
> If this session has been running a while, re-read [`README.md`](README.md) too — it holds every gate.

This is the last step. By now the 5-law review has passed and parallelism is tuned.

## 9.1 Create the GitHub repo

```bash
gh repo create legalize-dev/legalize-{code} --public \
  --description "Legislation from {Country} in Markdown, version-controlled with Git"

# Tag the repo so it shows up in the legalize-country index alongside the
# other country repos. This is used by the public hub (`legalize-dev/legalize`)
# and by tooling that lists all country repos via the GitHub topic search.
gh api -X PUT repos/legalize-dev/legalize-{code}/topics \
  -f 'names[]=legalize-country'

# Wipe the sandbox repo from Step 7 and re-init clean. This is the first
# bootstrap, where there is nothing published to lose. To rebuild a country
# that is already live, do NOT do this by hand — see "Re-emitting a country
# that is already published" in 9.4, and use `legalize bootstrap --fresh`.
rm -rf ../countries/xx
git init ../countries/xx/
mkdir -p ../countries/xx/xx
git -C ../countries/xx commit --allow-empty -m "[bootstrap] Init legalize-{code}"
git -C ../countries/xx remote add origin git@github.com:legalize-dev/legalize-{code}.git
git -C ../countries/xx push -u origin main
```

The repo's **README and `.github/FUNDING.yml` are generated automatically** by
the pipeline (bootstrap runs `write_repo_meta` after the commit history is
built), so you do not add them by hand. They are rendered in the country's own language from the bundled
metadata in `src/legalize/readme_data.json` (single source of truth) — see
`legalize.country_meta` and `legalize.committer.readme`. This keeps every country
repo identical in structure and style.

To onboard a new country's presentation so it comes out identical to the rest:

1. Add a `countries` entry in `src/legalize/readme_data.json` (name, language,
   source_name, source_urls, data_license, scope, norm_types, attribution,
   notes — free text in the country's language). **Verify the data reuse license
   of the official source and cite it**; default to "public domain (official
   government publications)" only when the source has no explicit open license.
2. If the country's language is not yet in the `labels` section of
   `readme_data.json`, add it (translate the section labels, plus `desc_tagline`
   and `desc_clause`, which are used for the GitHub "About" line).
3. After the repo exists, set its GitHub "About" (description + homepage) to
   match every other repo — this is GitHub metadata, not a file, so a script
   sets it via the API:
   ```bash
   python scripts/set_repo_about.py {code}
   ```
4. Backfill only — to push README + FUNDING.yml to a repo that already exists,
   without a local clone (uses the GitHub API):
   ```bash
   python scripts/push_repo_meta.py {code}
   ```

Still add an MIT `LICENSE` by hand (not generated): it covers the repository
structure/metadata. The legislative *content* license is recorded in the README
metadata (step 1), since it varies per source.

## 9.2 Run the full bootstrap

### Rehearse on a subset first

A bootstrap is hours. A rehearsal is seconds, and it fails for the same reasons.
Commit a few hundred laws into a throwaway repo and look at what comes out before
spending the afternoon on the other 170,000.

This is not the 5-law sandbox of Step 7. That one judges the parser's prose, from
rendered Markdown. This one judges the shape of the *repo* — layout, manifest,
identifiers, health — none of which exists until the commit phase has run.

`-o KEY=VALUE` overrides any config value, dotted, and is repeatable. Point the
repo somewhere disposable and leave the data directory alone:

```bash
REHEARSAL=/tmp/xx-rehearsal
rm -rf "$REHEARSAL"; git init -q "$REHEARSAL"
git -C "$REHEARSAL" commit -q --allow-empty -m "[bootstrap] Init"

legalize -o countries.xx.repo_path=$REHEARSAL commit -c xx --all --limit 800
legalize -o countries.xx.repo_path=$REHEARSAL health -c xx --deep
```

Measured on Portugal: 800 laws, 1,342 commits, 22 seconds.

**No remote on the rehearsal repo.** It used to be given the country's real one,
so that `--fresh` would have something to carry over — and that put the production
URL on a throwaway directory in `/tmp`, one mistyped `-o` away from publishing 800
rehearsal laws over a live corpus. Nothing in the rehearsal needs it: `--fresh`
copies the remote as a string, and 9.4's re-emission runs against the real repo.
Leave it without a remote entirely: `--fresh` now asks the remote whether it holds
the history it is about to delete, so an invented URL makes it refuse rather than
carry anything over.

There is deliberately no copy of the fetch cache here. An earlier version of this
section built one out of symlinks, and it was both slower and dangerous: a run
writes into `{data_dir}` — `json/`, `country_meta.yaml`, and whatever else a
country adds — and writing through a symlink destroys the real file on the other
end. `commit` only reads `json/`, so pointing the repo away is enough.

What to look at:

```bash
cat "$REHEARSAL/.legalize.yml"                 # manifest, with the template you meant
find "$REHEARSAL" -name '*.md' | head          # a path that matches that template
grep -rh '^identifier:' "$REHEARSAL" | head    # identifiers the shape you meant
```

Two things to know before reading the output:

- **`--limit` makes `health` report orphans.** "N law(s) have data but never
  reached the repo" is the limit doing its job, not a fault — the other laws have
  JSON and no commit because you asked for 800. Everything else must be zero, and
  `health` exits non-zero when it is not.
- **A percentage measured here is not a corpus percentage.** `--limit` takes the
  first N by filename, which is not a random sample. A subset proves a field is
  emitted at all; it says nothing about how often.

Pick the subset on purpose when the default ordering hides something. `--offset`
walks to a different part of the corpus, and a country with more than one
jurisdiction or fetch surface deserves a run that reaches each — the layout is per
`{directory}`, so a rehearsal that only ever sees one directory has not rehearsed
the layout.

**Always run the first bootstrap locally, never via the `bootstrap.yml`
CI workflow.** The CI bootstrap job is for incremental re-runs and
recovery once the country is live. First runs are multi-hour operations
that need interactive debugging (rate-limit tuning, transient failures,
source-specific quirks that only surface at scale) — running them in
GitHub Actions wastes compute and makes iteration slow. After the
local bootstrap succeeds and the full history is pushed, the CI
workflow becomes useful for scheduled refreshes.

**Over ~20K laws, do not use `legalize bootstrap` for the commit phase.** Read
"The 2 GiB pack limit" in §9.4 first and split fetch from commit — it is the
difference between one push that works and an afternoon of pushes that do not.

```bash
# Kick off the bootstrap. Tail the log to a file so you can review afterwards.
legalize bootstrap -c xx 2>&1 | tee bootstrap-xx.log

# For long runs, use nohup + background
nohup legalize bootstrap -c xx > bootstrap-xx.log 2>&1 &
```

Watch `bootstrap-xx.log` for:
- Fetch errors (429, 500, connection resets) → reduce workers and restart
- Parser warnings → investigate; the 5-law review should have caught these
- Commit errors → usually date parsing; fix and `legalize reprocess`

## 9.3 Health check before pushing

```bash
legalize health -c xx                  # full scan
legalize health -c xx --sample 500     # sampled scan for big repos
legalize health -c xx --deep           # reads every file, not just its name
```

`health` verifies: commit dates, empty files, remote configured, orphan files
(files in repo with no entry in state), frontmatter validity. `--deep` adds the
check that matters most after a layout change: it fills in the template the
manifest declares from each law's own frontmatter and compares it to where the
file actually is. A repo that fails it serves every law's metadata and 404s every
body — the hardest failure here to notice, because the pages look fine.

**Every issue reported must be zero before pushing.** `health` exits non-zero when
there are errors, so it can gate a script.

## 9.4 Push to origin

```bash
git -C ../countries/xx push origin main
```

### The 2 GiB pack limit — read this before bootstrapping a large country

**GitHub refuses any pack larger than 2.00 GiB.** The real message is
`remote: fatal: pack exceeds maximum allowed size (2.00 GiB)`, but you will
almost never see it. `pack-objects` spends 20–30 minutes computing deltas before
a single byte leaves your machine, GitHub's sshd closes the idle connection
first, and what you get is:

```
fatal: the remote end hung up unexpectedly
```

That message names the connection, not the pack, and it will send you debugging
the wrong problem. Portugal cost an afternoon and four failed attempts this way
(2026-08-24): 1.2M objects, 2.86 GiB in one pack.

**Prevention — for any country over ~20K laws, don't commit with `legalize
bootstrap`.** Split fetch from commit and let the CLI push as it goes:

```bash
legalize fetch -c xx                          # fetch everything into data-xx/
legalize commit -c xx --all --batch 2000      # commit 2000 norms, push, repeat
```

`--batch` is implemented in `_commit_in_batches` (`src/legalize/cli.py`): it runs
the incremental committer and pushes `HEAD` after every batch, so no pack ever
approaches the limit. It forces the incremental path — no `git fast-import` — so
it is slower per commit. That is the trade. `legalize bootstrap` has **no**
`--batch` flag: it commits everything and leaves you one enormous push.

Reach for it when you want the pushing interleaved. You do **not** need it to
survive a dead run: the fast path commits in chunks of 25,000 and picks up from
the branch tip, so re-running the same command continues rather than restarting.
Portugal's commit phase was killed three times in one evening — at 35,000, 10,000
and 85,000 of 302,333 — and before this each death cost the whole history, because
`git fast-import` moves the ref when its stdin closes and not one commit sooner.

**Recovery — history already committed locally.** `legalize push` sends it in
slices, one push and one short-lived connection each:

```bash
legalize push -c xx --dry-run     # list the slices first
legalize push -c xx               # 25000 commits per slice
legalize push -c xx --start 7     # resume at slice 7
```

Already-pushed slices are detected and skipped, so re-running after a failure is
safe and costs nothing. Four things the command encodes, each learned the hard
way:

- **Keepalives are mandatory.** `GIT_SSH_COMMAND="ssh -o ServerAliveInterval=15
  -o ServerAliveCountMax=20 -o TCPKeepAlive=yes"`. Without them the connection
  dies during the silent delta computation and you never get the real error.
- **Cap each push and retry once.** A push can hang with the connection alive,
  waiting on a remote that never answers — 1h27m of nothing, observed. Each slice
  gets 45 minutes and one retry, then stops and tells you the `--start` value to
  resume from.
- **Refresh `origin/main` before deciding anything.** A stale remote-tracking ref
  makes every skip decision wrong: a resumed run once recomputed its start from a
  ref 75K commits behind reality and pushed a tip the remote was already past.
  Git calls that "non-fast-forward", which describes the ref and hides the cause.
  `legalize push` fetches first.
- **Slice size is linear, so pick it by what a failure costs.** Measured on
  Portugal: 2000 commits pack in 81s and 16.6 MB, 25000 in ~19 min and ~207 MB.
  A bigger slice buys no efficiency and only raises the price of a dropped
  connection — at 25000 that was 19 minutes of compression thrown away, twice in
  one evening. The default of 5000 keeps a failure under five minutes.
- **Slicing is faster than the single push it replaces**, because each
  enumeration only covers what the remote doesn't have yet instead of walking the
  whole object graph. Expect later slices to take longer anyway: the exclusion
  walk grows with how much the remote already holds, while the transfer per slice
  stays flat.

This is GitHub's own documented procedure for the 2 GiB limit — push every Nth
commit to the branch ref with `+` (force) — with the step size, keepalives,
timeout and retry filled in from what Portugal cost. See
[Troubleshooting the 2 GB push limit](https://docs.github.com/en/get-started/using-git/troubleshooting-the-2-gb-push-limit).

### Re-emitting a country that is already published

A country gets re-emitted when its identifier rule, its layout or its frontmatter
changes: every file is renamed or rewritten, so the new history shares no ancestor
with the published one. Portugal was the first, on 2026-08-25.

**The remote repository is never deleted.** Stars, forks, issues, pull requests,
topics, the description and every setting live outside the git history and survive
a force push untouched; deleting and recreating the repo is the only thing that
loses them, and `legalize-pt` had 28 stars and 5 forks the day it was re-emitted.
"Empty the remote" below means *replace the branch*, never the repository.

**1. Rebuild locally.**

```bash
legalize bootstrap -c xx --fresh
```

`--fresh` discards the repo directory and re-inits it **keeping `origin`**, empties
`data-xx/json/`, and drops the discovery cache. It refuses if the path exists and is
not a git repo, so a mistyped `repo_path` cannot delete something else. `raw/` is
never touched — it is the only copy, and refetching it is the whole corpus again.

The old local history is gone at this point, and the remote is the copy you fall
back to — so `--fresh` asks it first. It runs `git ls-remote` and refuses if the
remote does not carry the local HEAD, or cannot be reached to say. A repo with no
remote at all cannot be checked, so it prints the commit count and continues:
Denmark's 45,400 laws went in an `rm -rf` of a repo that had never been pushed,
and a number on screen is what there was instead of a question.

**2. Replace the remote branch, before the long push.**

```bash
git -C ../countries/xx push --force origin \
  $(git -C ../countries/xx rev-list --max-parents=0 HEAD):refs/heads/main
```

That is the new history's root commit — one law, five objects — so it costs nothing
to send. Order matters, and for a reason that is easy to miss:

- **`legalize push` fetches `origin` before deciding what to skip** (the bullet
  above about stale refs). Run against a remote that still holds the old history,
  that fetch **downloads back everything `--fresh` just deleted** — for Portugal,
  300,733 commits and gigabytes, straight into the repo we emptied on purpose.
  With the branch already replaced, the fetch finds one commit and returns.
- **Every slice afterwards is a fast-forward**, so `legalize push` needs no
  `--force` at all. Passing it anyway is harmless; not needing it is the point.
- **GitHub does not allow deleting the default branch**, and nothing here asks you
  to. The branch is replaced in place, so no bridge branch is needed either.

Prefer `--force-with-lease` over `--force` if anyone else can push to the repo: it
refuses when the remote moved since your last fetch, instead of overwriting it.

**3. Push the rest** exactly as above — `legalize push -c xx`.

The old commits become unreachable rather than deleted. GitHub garbage-collects
them on its own schedule, so the repository can report its old size for a while
after the re-emission; nothing needs doing about that.

## 9.5 Open the engine PR

```bash
cd engine
git checkout -b feat/{code}-initial
git add src/legalize/fetcher/{code}/ src/legalize/countries.py config.yaml \
        tests/test_parser_{code}.py tests/fixtures/{code}/
git commit -m "feat({code}): add {Country} fetcher + bootstrap"
git push -u origin feat/{code}-initial
gh pr create --fill --base main
```

CI will run the full test suite + the per-country smoke test. Wait for green.

## 9.6 Set up CI workflows

The engine CI (`ci.yml`) auto-detects new countries via the dynamic matrix — no
changes needed there. But you do need to set up the **update workflow** for the
country:

```bash
# Option A: daily updates (for sources that publish daily, e.g., ES, FR)
# → Add the country to the daily-update.yml matrix or create a dedicated workflow

# Option B: periodic updates (for sources with less frequent publication)
# → Create a monthly/weekly workflow: .github/workflows/monthly-update-{code}.yml
```

Copy the structure from an existing workflow (e.g., `monthly-update-ar.yml` for
monthly, or `daily-update.yml` for daily) and adapt the country code and schedule.

The bootstrap workflow (`bootstrap.yml`) already supports `--country` as an input
parameter — no changes needed.

## 9.7 Wire the website

Once the engine PR is merged and the country repo has commits, add the country to
the web app (`legalize-dev/legalize-web`, cloned at `../web`):

```bash
cd ../web
git checkout -b feat/{code}-web
```

Two edits:

1. **`web/src/legalize/web/countries.py`** — add a `_COUNTRIES_RAW` entry. Required
   keys, copy the shape from a country with the same jurisdiction structure:
   `name`, `name_en`, `lang`, `iso`, `dir`, `source`, `source_url`, `github_repo`,
   `start_year`, `title`, `subtitle`, `cta_enabled`, `jurisdiction_label`,
   `jurisdiction_label_singular`, `jurisdictions`, `rangos`, `strings`. The
   `strings` block holds only country-specific overrides (SEO meta, the disclaimer
   naming the official gazette); generic UI copy comes from the language YAML.
2. **`web/src/legalize/web/i18n/{lang}.yaml`** — only if the country's language is
   not already there. `ls src/legalize/web/i18n/` from the web repo to check.

```bash
git commit -m "feat({code}): enable {Country} in web app"
git push -u origin feat/{code}-web
gh pr create --fill --base main
```

## 9.8 Seed the database

The DB sync does **not** live in the web repo. It lives in
`legalize-dev/legalize-enrichment`, in its own `sync.yml` workflow (cron 11:00 UTC
Mon–Sat, one hour after the engine daily update).

**There is no country matrix to edit.** The workflow discovers country repos via
the `legalize-country` GitHub topic — the one you applied in §9.1. If you skipped
that, the sync will not see your repo.

A freshly bootstrapped country must be seeded **once** in `full-local` mode:

```bash
gh workflow run sync.yml -R legalize-dev/legalize-enrichment \
  -f mode=full-local -f country={code}
```

Do not seed it with the default `api` mode. That mode spends one GitHub API call
per commit, and a country whose entire history is inside the lookback window will
burn the hourly quota and take every other country's sync down with it. After the
full-local seed lands, the daily `api` run picks the country up on its own.

## 9.9 Verify on production

- Visit https://legalize.dev/{code} and confirm the country appears.
- Click through to a law and confirm the text, metadata, and reform history render.
- Open a law with a table (from your Step 0.4 inventory) and confirm it renders.
- Switch the UI language to the country's native language and confirm translations.

## 9.10 Update the memory and MEMORY.md

Save a one-line memory recording the country as shipped (date, law count, any
quirks discovered during bootstrap). Delete `RESEARCH-{CC}.md` from the workspace
root only after all the above is verified green.


---

**GATE IN THIS STEP:** §9.3 `legalize health` must report zero issues before
the first push. A repo pushed dirty is a repo you rewrite in public.

**Last step.** When every box in `PROGRESS.md` is ticked, delete `PROGRESS.md`
and `RESEARCH-{CC}.md`. The country is shipped.
