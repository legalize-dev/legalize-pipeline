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

# Wipe the sandbox repo from Step 7 and re-init clean
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
```

`health` verifies: commit dates, empty files, remote configured, orphan files
(files in repo with no entry in state), frontmatter validity. **Every issue
reported must be zero before pushing.**

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

**Recovery — history already committed locally.** Push it in slices with
`scripts/push_slices.sh`:

```bash
scripts/push_slices.sh ../countries/xx --dry-run   # see the slices first
scripts/push_slices.sh ../countries/xx             # 25000 commits per slice
```

Four things that script encodes, each learned the hard way:

- **Keepalives are mandatory.** `GIT_SSH_COMMAND="ssh -o ServerAliveInterval=15
  -o ServerAliveCountMax=20 -o TCPKeepAlive=yes"`. Without them the connection
  dies during the silent delta computation and you never get the real error.
- **Cap each push and retry once.** A push can hang with the connection alive,
  waiting on a remote that never answers — 1h27m of nothing, observed. The script
  uses `timeout 2700`, retries once, then stops and tells you the `START=` value
  to resume from.
- **Bigger slices are cheaper, not more dangerous.** Every slice re-walks the
  commits before it to exclude them, and delta bases across slice boundaries
  can't be reused. Use the biggest slice that stays under 2 GiB. ~25000 commits
  of consolidated law lands around 240 MB, so there is room.
- **Slicing is faster than the single push it replaces**, because each
  enumeration only covers what the remote doesn't have yet instead of walking the
  whole object graph.

If you are re-pushing a rebuilt history with no common ancestor, empty the remote
first and run with `FORCE=1`. That rewrites a public repo — be sure that is what
you mean.

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
