# Operations

Runbook for keeping the published country repos current. For what the pipeline
is and how it's built, see [ARCHITECTURE.md](ARCHITECTURE.md) and
[CLAUDE.md](CLAUDE.md). For onboarding a new country, see
[adding-a-country/](adding-a-country/README.md).

## Publication calendar

The [Countries table in README.md](README.md#countries) is the single source
of truth for which country is on which cadence — read it there, not here, so
there is one place to keep current. Three states:

- **Daily** — `.github/workflows/daily-update.yml`, Mon–Sat 10:00 UTC. One
  matrix leg per country, `fail-fast: false` so one broken country never hides
  a regression in the others.
- **Monthly** — a dedicated `monthly-update-{cc}.yml` per country (currently
  `ar`, `ch`, `co`), each on its own day-of-month schedule. These exist
  because the source itself only republishes monthly (Argentina's InfoLEG
  catalog, Colombia's SUIN edits) or a monthly cadence is enough to stay
  current without hammering the endpoint daily (Switzerland's Fedlex).
- **Unscheduled** — registered in `countries.py::REGISTRY` and `config.yaml`,
  but on no cron. Some have a documented reason in the `daily-update.yml`
  matrix comment (as of this writing: `uy` — the source only exposes recent
  history so a daily run always finds nothing; `ro` — bootstrap only, daily
  path not wired yet; `fr` — known-broken in CI, see that comment for the two
  stacked causes). The rest are simply not on a cron yet.

Before touching the daily matrix, read the comment block above it in
`daily-update.yml` — it is the actual list of exclusions and why, and it goes
stale if you edit the matrix without updating the comment next to it.

## When a daily leg goes red

Don't go looking for it manually — `engine-alert.yml` watches
`daily-update.yml` and the three `monthly-update-*.yml` workflows and opens a
GitHub issue (label `scheduled-run-failure`) per failed or cancelled job,
deduped so a chronic already-known failure doesn't reopen every day. Before
this existed, a broken country sat red inside an otherwise-green matrix run
for weeks unnoticed (`fail-fast: false` means the matrix as a whole stays
"green" even when one leg is red).

To investigate and recover:

1. Open the issue (or the Actions run it links to) and read the failed job's
   log — the matrix is one leg per country, so the log is scoped to that
   country only.
2. Re-run just that country: Actions → "Daily update" → "Run workflow" →
   fill in the `country` input (leave `date` empty for "today", or set it to
   backfill a specific day).
3. If the failure is a source-side outage or timeout, re-running later often
   suffices — the daily flow checkpoints per day (see
   `pipeline.generic_daily`), so a partial run resumes rather than restarting.
4. If the failure is structural (parser broke on a new field, source changed
   shape), it needs a code fix before re-running will help. Pause the
   country's daily runs is not something you do by disabling the whole
   workflow — that stops every other country too. Fix and re-run instead;
   `fail-fast: false` means leaving it red for a day costs nothing else.

## The "green and empty" failure mode

The most expensive failure to catch is not a red run — it's a run that exits 0
having actually published nothing. A source can go quiet (nothing new that
day, correctly detected — fine) or a bug can make the pipeline silently
process zero norms every day while still exiting success (not fine, and
indistinguishable from the first case in the Actions UI).

**Check any country in under two minutes:**

```bash
git -C ../countries/{cc} log -1 --format=%cI
```

Compare that timestamp against the daily schedule (Mon–Sat) or the country's
monthly date. A country that's supposed to be on the daily cron but whose last
commit is weeks old ran green the whole time while publishing nothing — that
is a real incident, not a quiet week. This exact symptom cost Portugal several
weeks of silent non-publication before it was noticed; the two-minute check
above is what should have caught it on day one.

## Slow or distant sources

Some sources are slow enough from a Europe-based runner that the daily/monthly
cron eats most of its time budget just waiting on the network — the
recurring case is South American sources (AR, UY, CL). This is a **latency**
problem, not IP geo-blocking: the source doesn't refuse requests from outside
the region, it's just an old, slow, timeout-prone server, and moving the
client closer only fixes the part of the problem that's actually network
distance. See
[RUNBOOK-REMOTE-FETCH.md](RUNBOOK-REMOTE-FETCH.md) for the mitigation
(a short-lived cloud VM near the source) and its measured limits — it cuts
latency, it does not fix a source that times out regardless of where the
client sits.

## Repos over 2 GiB

GitHub refuses any single pack over 2.00 GiB, which a first bootstrap of a
large country (Portugal: 1.2M objects, 2.86 GiB in one pack) exceeds. Use
`legalize push -c {cc}` to send an already-committed local history to origin
in slices instead of one push:

```bash
legalize push -c xx --dry-run     # list the slices first
legalize push -c xx               # 5000 commits per slice (the default)
legalize push -c xx --start 7     # resume at slice 7
```

Already-pushed slices are detected and skipped, so re-running after a failure
or a dropped connection is safe. See the command's own `--help` and
[adding-a-country/step-9-production.md](adding-a-country/step-9-production.md)
§9.4 for the full detail on why each part of it exists (keepalives, per-slice
timeout and retry, refreshing `origin/main` before deciding what to skip).

## The GitHub App token's one-hour lifetime

Every workflow that pushes to a country repo mints a GitHub App installation
token via `create-github-app-token`, and GitHub caps that token at **~1 hour**
— not something the action itself can extend. Two consequences baked into the
workflows:

- **Daily jobs are capped at 55 minutes** (`daily-update.yml`), just under the
  token's lifetime, so a slow country stops instead of burning time it can
  never push. The daily flow checkpoints per day, so the next run resumes.
- **Long-running monthly bootstraps (`ar`, `ch`, `co`) mint a second, fresh
  token right before the final push** ("Refresh GitHub App token before
  push" step), because the job itself can run for hours — long past the
  first token's expiry — even though the push at the end takes seconds.

If you add a new long-running workflow that pushes to a country repo, follow
the same pattern: either cap the job under ~1h, or refresh the token
immediately before the step that pushes.
