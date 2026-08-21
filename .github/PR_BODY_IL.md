## Summary

Adds Israel (`il`) to the Legalize pipeline using the Knesset OData V4 API.

### Data source
- **Base URL:** `https://knesset.gov.il/OdataV4/ParliamentInfo/`
- **Primary entities:** `KNS_IsraelLaw`, `KNS_IsraelLawName`, `KNS_IsraelLawClassificiation`, `KNS_IsraelLawMinistry`, `KNS_LawBinding`, `KNS_IsraelLawLawCorrections`, `KNS_DocumentBill`
- **Documents:** PDF / DOC on `fs.knesset.gov.il`
- **Challenges:** Reblaze WAF (detected & retried), visual Hebrew in legacy PDFs (reversed), RTL text

### Implementation
- `IsraelClient` — OData V4 client with Reblaze detection, Hebrew text reversal, backoff retries
- `IsraelDiscovery` — paginated `KNS_IsraelLaw` discovery with optional Basic Law filter and daily delta
- `IsraelMetadataParser` — rank inference (basic_law / ordinance / regulation / law), title cleaning, department/subject extraction
- `IsraelTextParser` — chapter/article detection, reform versioning from amendment bindings
- `dates_il` — Hebrew gematria year conversion and Gregorian date parsing

### Registration
- Added `il` to `countries.py` `REGISTRY`
- Added `il` section to `config.yaml` (2 workers, 60s timeout, 1 req/s)

### Tests
- `tests/test_parser_il.py` — 8 tests covering dates, visual Hebrew, Reblaze detection, metadata, and text parsing
- All tests pass; full suite at 1702 passed, 27 skipped
- `ruff check` and `ruff format --check` clean

### Milestone run
- Bootstrapped 18 Basic Laws → 17 law files (one repealed/empty), 130 dated `[bootstrap]`/`[reform]` commits in `legalize-il`
- Each reform is committed at its real publication date, oldest-first per law (see Status below)
- Hebrew renders correctly in Markdown frontmatter and body
- `last_updated` tracks version date (publication date for unamended laws, latest reform for amended ones)

### Decision gate findings
- **Gate 1 (document semantics): Case B (point-in-time publications).** Documents on `fs.knesset.gov.il` are not consolidated texts but original acts plus separate amending acts. Consolidation requires ordering documents chronologically and applying amendments in sequence.
- **Gate 2 (incremental discovery): `LastUpdatedDate`.** Confirmed as a working `$filter` field on `KNS_IsraelLaw`, used by `discover_daily`.

## Status

> **Draft.** An initial milestone run dated reform/amendment commits with a hardcoded
> placeholder (`2000-01-01`) instead of the real effective date — 190 of 200 commits carried
> placeholder dates, violating the historical-versions and per-file chronological-ordering
> priorities. **This has been fixed:** the client now resolves each amending bill's real
> `PublicationDate` (via `KNS_Bill?$expand=KNS_DocumentBill`, with `KNS_LawCorrection` as a
> fallback) and the parser orders amendments chronologically. `legalize-il` was regenerated
> from scratch (history reset, not patched, per the commit-integrity rule).
>
> Post-fix `legalize-il` (18 Basic Laws): **130 commits, 0 placeholder dates.** Reforms are
> dated to their real publication date and committed oldest-first per law. The only non-real
> dates are 11 commits clamped to `1970-01-02` — these are pre-1970 Basic Laws (1958–1968)
> that git fast-import cannot represent with negative Unix timestamps; this is the generic
> committer's documented behavior (see `pipeline.py`), and the commit messages carry the true
> year. `legalize health` is clean apart from the expected "no remote" (not yet pushed) and
> the epoch-date warning.

## Known limitations

- **Scope is Basic Laws only.** `config.yaml` sets `is_basic_law_only: true`, so this run covers only Basic Laws (17 files). Ordinances, ordinary laws, and secondary legislation (regulations / תקנות) are supported by the parser's rank inference but have **not** been bootstrapped at scale yet. Flip the flag and re-run to extend coverage. The local `data-il` cache still holds ~79 orphan non-Basic-Law JSON files from an earlier exploratory fetch; `legalize health` warns about these — they were intentionally excluded from the milestone repo.
- **Amendment reconstruction is partial (Case B).** Amendments are now dated to their real publication date and ordered chronologically, but each is captured as a separate amendment block derived from the amending act's text — the pipeline does **not** reconstruct a consolidated point-in-time text by applying each amending act's edits to the base text (the Knesset data does not expose structured per-article diffs). The git history is a correctly-dated amendment ledger, not a diff-applied consolidation.
- **Pre-1970 dates clamp to `1970-01-02`.** Basic Laws enacted 1958–1968 cannot be represented by git fast-import's Unix timestamps and clamp to the epoch (11 commits). This is generic committer behavior; the true year is preserved in the commit message.
- **RTL web rendering is unaddressed in this PR.** Paragraphs use the generic `css_class="parrafo"` (no Hebrew/RTL-specific class). Hebrew content is correct in the Markdown itself; visual RTL direction and `lang: "he"` handling live in the separate website repo, not in this pipeline. Tracked as a follow-up.
- **Document coverage gaps.** Some Knesset files return 406 / time out; the pipeline skips them gracefully and logs warnings rather than fabricating text. Skipped documents are not retried within a run.
- **Visual-Hebrew reversal is heuristic.** Legacy PDFs store text in visual order; the reversal heuristic is best-effort and can mis-handle mixed LTR/numeric segments. Newer documents (logical order) are unaffected.
- **Text fidelity has been improved but is not byte-perfect on legacy scans.** Extracted text is now normalized (`clean_extracted_text`): soft hyphens → maqaf, and zero-width/BOM/bidi/C0–C1 control characters stripped (~21k junk code points removed across the 18 Basic Laws). Article detection now handles the visual-order `.N` / `,N` marginal-heading layout (e.g. Basic Law: The Army 1 → 7 blocks, The Knesset 59 → 90 blocks). **Residual** issues remain from the source PDF text layer: two-column marginal headings occasionally wrap to a stray body line, and pre-1990 scans contain OCR typos (e.g. `הכטחון`, `ראשהמטה`). These are documented, not silently patched.
- **Hebrew date parsing is year-level.** `dates_il` converts gematria *years* (e.g. `התשפ"ה` → 2025); full day/month Hebrew-calendar dates in document text are not converted. Gregorian dates from OData fields are stored as ISO.
- **Test coverage is consolidated, not fixture-file-driven.** A single `test_parser_il.py` covers dates, visual Hebrew, Reblaze, metadata, and text parsing using inline data; there are no dedicated discovery / reform-extraction tests and no committed fixtures under `tests/fixtures/il/` (raw samples live in the untracked `recon/`). Tests are fully offline (no live API calls).

Generated with [Devin](https://cli.devin.ai/docs)
