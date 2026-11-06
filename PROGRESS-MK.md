# Progress — legalize-mk

Currently on: **Step 9** — the relevant corpus and engine integration are
prepared; maintainer-side publication and downstream deployment remain.

## Research — Step 0

- [x] `research/RESEARCH-MK.md` contains source, licensing, API, metadata, and formatting research
- [x] Five representative fixtures are saved under `tests/fixtures/mk/`
- [x] Metadata inventory covers every field exposed by LDBIS cards
- [x] Formatting inventory covers text, tables, scans, OCR, lists, headings, and unsupported image-only content
- [x] Version-history spike shows separate dated LDBIS versions
- [x] Historical access pattern and request cost are documented
- [x] Relevant scope is documented as 5,609 cards and 5,264 publishable records

## Fetcher — Step 1

- [x] `fetcher/mk/__init__.py` re-exports the client, discovery, and parsers
- [x] `client.py` has rate limiting, retry, UTF-8 decoding, metadata, PDF, and reform-chain access
- [x] `discovery.py` implements `discover_all()` and `discover_daily()`
- [x] `parser.py` implements metadata and PDF text parsing
- [x] Born-digital text, scanned OCR, and table extraction are covered by the five-law review
- [x] All inventoried metadata fields are captured in `NormMetadata` or `extra`
- [x] Related LDBIS records produce dated reform entries
- [x] A corpus-level reform coverage checker compares saved links with Git trailers
- [x] C0/C1 controls are stripped and UTF-8 is enforced
- [x] Image-drop counting is explicitly marked not applicable for MK: PDF images are OCR input, not discarded legal content
- [x] Amending acts record the law they amend as `amends`, through a client capability rather than a country check
- [x] OCR doubtful and unread pages are recorded as lists in the JSON and in the frontmatter
- [x] Unreadable OCR lines on sure pages are left out and their pages recorded; reviewed per-law fixes live in `assets/ocr_fixes.json`
- [x] Every version is dated by its card; no date is taken from the body text

## Wiring — Steps 2–4

- [x] Country registry entry exists
- [x] `TEXT_STATE` is declared as `AS_ENACTED`
- [x] `config.yaml` contains the LDBIS source and worker settings
- [x] Sharded layout is declared in `layout.py`

## Daily path — Step 5

- [x] `fetcher/mk/daily.py` is the selected implementation: it skips saved records whose card is unchanged and takes `--since`
- [x] `legalize daily -c mk --date YYYY-MM-DD --dry-run` has been run against the committed repo
- [ ] A live reform date has been run and its reform commit verified
- [ ] The reform coverage checker has passed on a rebuilt full corpus
- [ ] Repeating the same date has been verified to create zero duplicate commits
- [ ] A whole month has been run with `--since` and its time recorded in `research/RESEARCH-MK.md`
- [x] A maintainer-owned monthly workflow is prepared in `.github/workflows/monthly-update-mk.yml`

## Tests — Step 6

- [x] `tests/test_parser_mk.py` passes against the five fixtures
- [x] Country registry dispatch is covered by tests
- [x] Ruff checks pass for the Macedonian fetcher and tests
- [x] The full suite passes on the latest branch commit locally (3,248 passed, 27 skipped)
- [ ] Pull request CI passes for the latest branch commit (no checks have run on the fork branch)

## Quality gate — Step 7

- [x] Five representative laws were fetched and rendered
- [x] Metadata, text, structure, formatting, and encoding review is recorded in `research/RESEARCH-MK.md`
- [x] Scanned OCR and table pages have a written source comparison; approval remains open
- [ ] Manual source comparison has been accepted by the repository owner
- [x] Relevant sample histories preserve chronological reform ordering

## Production — Steps 8–9

- [x] One-worker 50-law benchmark passed 50/50 in 5m58s
- [x] Existing relevant corpus bootstrap completed with 5,264 law files and 7,578 commits, before the second review's parser changes
- [x] SPEC v0.5 content validation passed
- [x] Health and deep-health checks passed on a clean corpus clone
- [x] Public fork `stojkovskistefan/legalize-mk` is populated, tagged, and has a Macedonian README
- [x] The fork's history is not imported: `legalize-dev/legalize-mk` is bootstrapped from the merged pipeline
- [x] Engine PR #184 contains the fetcher, workflow, research, and README integration, as a series of review commits rather than one squashed commit
- [ ] PR #184 must be merged by a `legalize-dev` maintainer
- [x] Maintainer-owned monthly workflow is prepared and targets `legalize-dev/legalize-mk`
- [ ] Upstream `legalize-dev/legalize-mk` must be created by a maintainer and bootstrapped from the merged pipeline
- [ ] Website country entry and Macedonian language integration
- [ ] One-time enrichment database seed
- [ ] Production page verification with a table-containing Macedonian law

The fork is intentionally not the production scheduler. The scheduled updater
is in the pipeline PR and will run under the maintainer organization after the
country repository and GitHub App secrets exist.
