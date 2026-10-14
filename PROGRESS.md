# Progress — legalize-ie

Copy this file to `PROGRESS.md` in your working directory before Step 0 and tick
boxes as you close them. **This file, not your context, is where the state lives.**
When you lose the thread after a long run, `cat PROGRESS.md` and resume from the
first unticked box — then re-read that step's file in full before touching anything.

Currently on: **Step 8** — the PDF repair completed every Companies archive, then the benchmark stopped at 49/50 on indirect-effect identities. The relation and commencement repair passes 119 focused tests and the complete Companies effects/enacted-body preflight. The identical-sample gate must pass before full fetch. Full bootstrap and publication have not started.

Worktree: `engine-ie`, branch `feat/ie-v04`, based on `origin/main` `781ee4d`.
Existing publication: `legalize-ie/main` `046eacac6559cc6f1900a0c976e9fb40800c8f60`, cloned intact to `../countries/ie`.
User authorized the complete Ireland v0.4 migration, including reprocessing and end-to-end onboarding. Preserve unrelated workspace changes and generated legislative bot identity.
PRs #92 and #93 are merged locally with their original commits retained (merge commits 1d82c3b and 841b435).

Initial findings (2026-10-08):
- Issue #124 is still open. Source fixtures reproduce missing early-act text, missing Revised Act schedules and lost XML unicode operators.
- The public corpus has no manifest or text_state declaration; its full history must be rebuilt, not patched with fictitious amendments.
- LRC officially exposes archived PDFs. The previous research claim that no historical versions exist is false. The research worker is collecting dated evidence and format counts.
- Build and validate a new local corpus before replacing any remote ref. Keep the original clone intact; publish only after fidelity, history, health and downstream gates pass.
- Run subsequent full-local reconciliation from a fresh clone of the new history (the current consumer scans HEAD; a fresh clone also removes stale local caches).

Validation update (2026-10-08):
- Baseline: 2,143 tests passed, 27 skipped before implementation. Integration: 110 tests passed across Ireland history/client/discovery, EU history and text-state contracts.
- eISB census: 4,114 Acts plus Constitution. LRC: 576 current consolidations and 1,972 archived rows; PDF versions are required.
- Shared commit/render paths preserve original publication, per-version source/text state and real effect IDs. Archived text retains its own cutoff when later effects arrive.
- A newly discovered event preceding published history fails before writing; it requires a deliberate local rebuild.
- Full local sync remains mandatory after any published rebuild. Consumer fixes for same-day event ordering and version-specific metadata are prepared and validated separately; deploy those before replacing the corpus.
- The initial LRC reuse uncertainty was closed on 2026-10-13: the owner supplied the LRC reply dated 2026-10-08 confirming CC BY 4.0 through the Oireachtas Open Data PSI Licence. Attribution and source notices are updated.
- All fetch, benchmark, bootstrap, validation and reconciliation execution is local, as requested.

Validation before resumption (2026-10-08):
- Engine suite: 2,377 passed, 27 skipped after the complete source-warning, resume/cache and history-integrity changes.
- Sample 4: six norms, 97 legislative commits; repeating fast import creates no new commits. Structured storage preserves nested lists and blank lines.
- The five required samples are Constitution, 1922/1, Finance 2024/43, private Act 2023/1 and SI 2024/356. Adoptive Leave 1995/2 additionally verifies archived PDF to current HTML transitions.
- The 1922 Constitution Act's whole repeal takes effect on 1937-12-29, separately from publication of the 1937 Constitution on 1937-07-01.
- Headless visual comparison of SI 356 confirms the title, opening provisions and both two-column tables. Binary figures follow the playbook's explicit omission rule; non-decorative omissions are visible and source counts are retained.
- The real CLI daily dry-run completed successfully at 1 request/second. An intermittent public catalogue HTTP 403 is retried with a bounded backoff; persistent denial still fails the run.
- Repeated local ingestion and historical REST/MCP/UI checks pass against the sample. No production publication or synchronization has run.
- Four-worker benchmark: 808.55 seconds, 802 logical HTTP calls, zero final HTTP errors, 47/50 complete histories and peak RSS 3,979.4 MiB. An intermittent disconnection succeeded on retry. Remaining cases: SI 63/1979's `27th.` signature ordinal; two inherited application relations predating the Diseases of Animals Act 1966; and section 1384A in a later Companies PDF. No failed law is excluded.
- Four workers at one request/second each are the selected network limit. Large PDF parsing is serialized; the timing is not a clean speedup comparison with the first run because more historical versions completed and immutable raw files were already cached.
- All previously published IE events now have their complete Markdown, messages and publication dates validated before incremental writes, including intermediate versions. Sparse working trees are checked through HEAD, and completed fetch futures release their parsed histories.

## Resume validation (2026-10-13)

- Preserved the previous Ireland implementation in local commit `6961058` before integrating upstream `346c0b3`; merge `c7ac07a` retains both histories.
- S3 `versionId=null` now follows mutable refresh rules while retaining the exact URL. The regression failed before the fix; all 126 focused cache/history/health checks passed afterward.
- Upstream integration preserves Ireland source/text-state/warning fields alongside staged commencement and expiry data. Optional test constructor arguments now use keywords; `legal_quote` is registered with the shared structural roles.
- Final engine suite: **2,517 passed, 27 skipped**. Existing pytest fixture deprecation warnings remain. Ruff lint/format passed.
- Old raw downloads and sample outputs remain untouched. The full-run cache is an independent copy, not a symlink: `../countries/data-ie-v04-full`.
- The exact 50 benchmark identities must pass with four workers at one request/second per worker. The earlier attempt was stopped before the final structural-role fix; its logs remain separately labelled interrupted.
- Durable local runner/config/logs/results live in `.pipeline/ie-v04-resume/`. Inspect `benchmark.pid`, the actual process command, `benchmark.log`, and `benchmark-result.json` before resuming. A process exit or an incomplete result is not a passed gate.
- LRC reuse terms are confirmed; source attribution, transformation and unofficial-text notices are recorded in the generated README metadata and the updated reuse assessment.
- The resumed benchmark finished 49/50 after 1,411.93 seconds. Its Companies failure identifies the exact January 2023 source PDF (`0036beba…`), where sections 890A and 934 exist but their labels are indented beneath aligned titles. No source-omission exception was added.
- A four-page source excerpt reproduces both missing headings before the fix. The repair preserves aligned titles and rejects indented quoted titles; all 57 PDF/history checks pass. The full original PDF passes with 1,774 sections and 23,419 paragraphs in 84.7 seconds. The final complete engine suite passes **2,519 tests, 27 skipped**; Ruff passes.
- The persistent `resume.py` runs benchmark then full fetch, stopping on a failed benchmark. Its self-check verifies that failure never launches the full fetch; the fetch runner independently checks 50/50 and the source hash. No generation or publication is automated by that runner.

- The `8badcc1` benchmark completed in 2,033.55 seconds at 49/50: all Companies archive PDFs parsed, but indirect references incorrectly created events for older host Acts. The full fetch correctly did not start.
- Indirect `as inserted/substituted by` citations now identify only the later instrument, retaining the complete source citation. Eleven stale Companies commencement dates have narrowly scoped repairs backed by official orders/the commencement table; original claims remain in provenance. See `research/ie-v04/companies-effects.md`.
- All 119 focused effects/history checks pass. The complete Companies directory/enacted-body preflight resolves 1,710 effects across 66 source IDs. Invalid event dates fail before PDF extraction. The complete archive benchmark remains required. The final engine suite passes **2,524 tests, 27 skipped**; Ruff lint/format passes.

## Previous responsibility split
- Research: source census, archives, licences and saved evidence.
- Parser audit: existing issue/PR defects and regression cases.
- Rollout audit: published history, source effects, consumer compatibility.
- Integration: isolated environment, complete test baseline, shared pipeline compatibility and production sequence.


Steps are listed in execution order. Each section maps to its step number.

## Research (Step 0)
- [x] Existing `research/RESEARCH-IE.md` updated with source, licensing findings and API details; LRC confirmed its applicable reuse terms
- [x] 5 representative fixtures saved under `engine/tests/fixtures/{code}/` (different ranks, at least one with tables)
- [x] Metadata inventory table in research doc lists **every** field the source exposes
- [x] Formatting inventory in research doc covers tables, bold, italic, lists, footnotes, links, formulas, quotations, annexes, signatories (images skipped)
- [x] **Version history spike passed** (Step 0.5): at least 2 distinct versions extracted from 1 law, with dates and text, evidence saved as `tests/fixtures/{code}/version-spike.txt`
- [x] **Historical-version access pattern identified** with cost estimate and effective-date source
- [x] Total scope estimated: approximate law count, HTTP request count, fetch time

## Fetcher (Step 1)
- [x] `fetcher/{code}/__init__.py` — re-exports all classes
- [x] `fetcher/{code}/client.py` — with `create()`, rate limiting, retry, UTF-8 decoding
- [x] `fetcher/{code}/discovery.py` — `discover_all()` and `discover_daily()`
- [x] `fetcher/{code}/parser.py` — `TextParser` and `MetadataParser`
- [x] **Text fidelity**: required samples pass the source comparison, including tables, emphasis, lists and explicit image omissions; full-corpus validation remains Step 9
- [x] **Every field in the §0.3 metadata inventory** is captured (dataclass or `extra`)
- [x] **`extract_reforms()` returns the full version timeline** from source snapshots and legislative effects, with distinct publication/effective dates
- [x] Parser strips C0/C1 control chars and enforces UTF-8
- [x] Images are dropped and counted in `extra.images_dropped`; source-specific counts explain the aggregate and meaningful omissions remain visible

## Wiring (Steps 2–4)
- [x] `countries.py` — `REGISTRY` entry added
- [x] `countries.py` — `TEXT_STATE` line added, or the source is `point_in_time` (the default) and correctly needs none
- [x] `config.yaml` — country section with `repo_path`, `data_dir`, `source`, `max_workers`
- [x] `layout.py` — `LAYOUT` entry added, or the repo is flat (the default) and deliberately so. Sharded is the default answer; see Step 4

## Daily path (Step 5)
- [x] Decision made: `generic_daily` vs. custom `daily.py` (see criteria table in Step 5)
- [x] `legalize daily -c ie --date 2026-10-08 --dry-run` works against the live inventory
- [x] Reform path tested: a date with reforms resolves affected norms and creates commits
- [x] Idempotency tested: re-running the same date produces 0 duplicate commits

## Tests (Step 6)
- [x] `tests/test_parser_ie.py` — passing against the 5 fixtures
- [x] Country registry/dispatch tests — passing
- [x] `ruff check src tests` — clean

## Quality gate (Step 7) — MANDATORY
- [x] 5 sample laws fetched and bootstrapped into sandbox repo (same laws as Step 0.2 fixtures), plus Adoptive Leave archive history
- [x] AI review returned `SUMMARY: 5/5 laws fully PASS` for TEXT, METADATA, STRUCTURE, FORMATTING, ENCODING — `research/ie-v04/quality-review.md`
- [x] Manual spot-check of one MD side-by-side with source — OK
- [x] **Commit ordering verified**: authentic snapshot cutoffs are chronological, same-day effects precede snapshots, and publication/activation dates remain distinct

## Production (Steps 8–9)
- [ ] Parallelism tuned against a 50-law benchmark (Step 8)
- [ ] Full `legalize bootstrap -c {code}` run completed without errors
- [ ] `legalize health -c {code}` reports zero issues
- [ ] Country repo pushed to `legalize-dev/legalize-ie` (>20K laws: committed with `legalize commit --all --batch N`, not `legalize bootstrap`)
- [ ] GitHub repo is public, MIT licensed, README in local language, `legalize-country` topic applied
- [ ] Engine PR merged on `legalize-pipeline` (CI green)
- [ ] CI update workflow created (daily or monthly, depending on source cadence)
- [ ] Web PR merged on `legalize-web` (`_COUNTRIES_RAW` entry + language YAML if new)
- [ ] DB seeded once via `legalize-enrichment` → `sync.yml` in **full-local** mode
- [ ] `https://legalize.dev/{code}` live and renders a table-containing law correctly
- [ ] Memory updated and `RESEARCH-{CC}.md` moved to `engine/research/{CC}.md`
      (`git mv`, not deleted — code under `fetcher/{code}/` cites it by name)
