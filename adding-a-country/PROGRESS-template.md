# Progress — legalize-{code}

Copy this file to `PROGRESS.md` in your working directory before Step 0 and tick
boxes as you close them. **This file, not your context, is where the state lives.**
When you lose the thread after a long run, `cat PROGRESS.md` and resume from the
first unticked box — then re-read that step's file in full before touching anything.

Currently on: **Step _ ** — <one line on what you were doing>

Steps are listed in execution order. Each section maps to its step number.

## Research (Step 0)
- [ ] `RESEARCH-{CC}.md` exists at workspace root with source + licensing + API details
- [ ] 5 representative fixtures saved under `engine/tests/fixtures/{code}/` (different ranks, at least one with tables)
- [ ] Metadata inventory table in research doc lists **every** field the source exposes
- [ ] Formatting inventory in research doc covers tables, bold, italic, lists, footnotes, links, formulas, quotations, annexes, signatories (images skipped)
- [ ] **Version history spike passed** (Step 0.5): at least 2 distinct versions extracted from 1 law, with dates and text, evidence saved as `tests/fixtures/{code}/version-spike.txt`
- [ ] **Historical-version access pattern identified** with cost estimate and effective-date source
- [ ] Total scope estimated: approximate law count, HTTP request count, fetch time

## Fetcher (Step 1)
- [ ] `fetcher/{code}/__init__.py` — re-exports all classes
- [ ] `fetcher/{code}/client.py` — with `create()`, rate limiting, retry, UTF-8 decoding
- [ ] `fetcher/{code}/discovery.py` — `discover_all()` and `discover_daily()`
- [ ] `fetcher/{code}/parser.py` — `TextParser` and `MetadataParser`
- [ ] **Text fidelity** (priority #1): output Markdown is identical to the official law text — tables as pipe MD, bold/italic preserved, lists as Markdown lists, no artifacts
- [ ] **Every field in the §0.3 metadata inventory** is captured (dataclass or `extra`)
- [ ] **`extract_reforms()` returns the full version timeline** (one `Reform` per historical version, each with its effective date). Single-snapshot only if RESEARCH documents why history is unreachable
- [ ] Parser strips C0/C1 control chars and enforces UTF-8
- [ ] Images are dropped and counted in `extra.images_dropped`

## Wiring (Steps 2–4)
- [ ] `countries.py` — `REGISTRY` entry added
- [ ] `countries.py` — `TEXT_STATE` line added, or the source is `point_in_time` (the default) and correctly needs none
- [ ] `config.yaml` — country section with `repo_path`, `data_dir`, `source`, `max_workers`
- [ ] `layout.py` — `LAYOUT` entry added, or the repo is flat (the default) and deliberately so. Sharded is the default answer; see Step 4

## Daily path (Step 5)
- [ ] Decision made: `generic_daily` vs. custom `daily.py` (see criteria table in Step 5)
- [ ] `legalize daily -c {code} --date YYYY-MM-DD --dry-run` works
- [ ] Reform path tested: a date with reforms resolves affected norms and creates commits
- [ ] Idempotency tested: re-running the same date produces 0 duplicate commits

## Tests (Step 6)
- [ ] `tests/test_parser_{code}.py` — passing against the 5 fixtures
- [ ] `tests/test_countries.py::test_registry_{code}` — passing
- [ ] `ruff check src/legalize/fetcher/{code}/ tests/` — clean

## Quality gate (Step 7) — MANDATORY
- [ ] 5 sample laws fetched and bootstrapped into sandbox repo (same laws as Step 0.2 fixtures)
- [ ] AI review returned `SUMMARY: 5/5 laws fully PASS` for TEXT, METADATA, STRUCTURE, FORMATTING, ENCODING
- [ ] Manual spot-check of one MD side-by-side with source — OK
- [ ] **Commit ordering verified**: `git log -- {code}/SAMPLE-LAW.md` shows versions in chronological order

## Production (Steps 8–9)
- [ ] Parallelism tuned against a 50-law benchmark (Step 8)
- [ ] Full `legalize bootstrap -c {code}` run completed without errors
- [ ] `legalize health -c {code}` reports zero issues
- [ ] Country repo pushed to `legalize-dev/legalize-{code}` (>20K laws: committed with `legalize commit --all --batch N`, not `legalize bootstrap`)
- [ ] GitHub repo is public, MIT licensed, README in local language, `legalize-country` topic applied
- [ ] Engine PR merged on `legalize-pipeline` (CI green)
- [ ] CI update workflow created (daily or monthly, depending on source cadence)
- [ ] Web PR merged on `legalize-web` (`_COUNTRIES_RAW` entry + language YAML if new)
- [ ] DB seeded once via `legalize-enrichment` → `sync.yml` in **full-local** mode
- [ ] `https://legalize.dev/{code}` live and renders a table-containing law correctly
- [ ] Memory updated and `RESEARCH-{CC}.md` deleted

