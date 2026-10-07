# EU reconstruction progress — 2026-10-07

Scope: preserve EU institutional legislation already published at
`ed827b14dc697af0b25b8ef1a9a383051912810e`, plus separately qualified easy
English consolidated EU additions. No national corpus expansion.
The user has authorized a full local history replacement; push is not authorized.

Currently on: **completed local reconstruction and validation; publication pending**. The independent
five-law gate passes with the documented CE drawing exception.
The complete image audit finds 6,074 HTML snapshots containing images across
4,093 pinned laws. Visible source links document those omissions. Required
amending acts add 23 laws with images; optional additions have none. Do not erase
generated history before all non-excluded frozen sources have been downloaded.

- [x] Inspect original engine branch, status, existing worktrees and instructions.
- [x] Isolate work in `engine-eu-reprocess`, branch `fix/eu-reprocess`, Python 3.12 venv.
- [x] Preserve full published mirror: 20,348 commits at the pinned HEAD.
- [x] Freeze 15,959 law identifiers before removing any history.
- [x] Measure full existing tree: 81,139 Article headings; 7,153 empty candidates.
- [x] Inventory English consolidated versions: 6,914 total; 6,611 HTML;
      303 require PDF (279 PDF, 24 PDF/A), 4.4% of consolidation versions.
- [x] Retrieve catalog metadata for every published law; zero missing records
      and zero missing official publication dates after checking both CDM shapes.
- [x] Verify version dates/publication dates against SPEC v0.4 and primary sources.
- [x] Qualify additions: 2,474 entirely HTML English chains without images after scope, retrieval
      and ambiguous-status exclusions; this is not a published count.
- [x] Capture public CDM work properties and qualified date annotations for both
      scopes; generic entry_into_force uses EV only, preserving raw MA/other dates.
- [x] Complete pinned HTML collection: 22,570 sources, zero errors; SHA-256
      records retained. Optional scope and required amenders also downloaded.
- [x] Classify 303 PDF-only snapshots: 214 pass extraction guards, 84 unsafe and
      five unavailable; 89 explicit gaps across 23 acts. Guard success is not full
      independent certification. Default client fails; offline draft opt-in records
      every exclusion in each law. OCR/font recovery remains a coverage exception.
- [x] Complete source metadata and representative formatting inventories; record
      the visual exception in RESEARCH-EU.md and retain version-spike.txt.
- [x] Parse every included original/consolidation with original numbering and annexes.
      Combined scope: 18,545 laws (15,959 pinned, 2,474 optional, 112 required
      amenders); 32,628 source commits. All source chains and dates match the
      frozen inventory. The remaining 142 own-file dependencies are reviewed exclusions.
- [x] Validate five historical 31958R0001 PDFs against its HTML boundary.
- [x] Commit and independently review five representative laws: 28 snapshots;
      final round SUMMARY: 5/5 fully PASS with the documented CE drawing exception.
      Source paragraphs from every original body/annex container were compared.
- [x] Test daily parity, failure retry and both commit paths' source-ID idempotence.
- [x] Measure uncached source fetch/parse on 50 laws/85 snapshots: one worker
      347.9s; four workers 160.7s at 1 req/s each; zero errors. Configure 4 × 1.
- [x] Pass engine tests, Ruff and required hooks in the dedicated environment.
      Latest full run: 2,201 passed, 27 skipped; no failures.
- [x] Validate the mirror, then remove old generated history using filter-branch
      on the isolated working copy; retain metadata and clear misleading trailers.
- [x] Re-emit the entire pinned scope and qualified additions: 18,545 files,
      32,628 legislative source commits, three metadata commits; zero import errors.
- [x] Measure every final file: 108,135 Article N headings, fourteen candidates.
      Source review: five legitimate empties, nine structural false positives,
      zero confirmed dropped bodies among the candidates. Pinned-only: 7,153 → 7.
- [x] Verify every final file against prepared output, and every source commit's
      ID, author date, bot identity and source-version sequence: zero differences.
      Git fsck passes; v0.4 files-only check passes all files. Health: zero errors,
      two warnings (unpublished commits and 8/331 unresolved current references).
      Full checker findings are reviewed in the runbook: 4,125 date-filtered
      history-count flags and the official 32008R0514 chronology exception.
- [x] Repeat commit phase: zero duplicates and unchanged HEAD/tree at `f78c15e5`.
- [x] Prepare the owned engine files and measured evidence for the human-authored
      final commit with the required Codex trailer; preserve the shared checkout.
- [ ] Publish replacement history: pending separate approval after reviewable results.

Procedure: [docs/eu-reprocess.md](../../docs/eu-reprocess.md).
Original numbered-provision investigation:
[docs/eu-article-loss-audit.md](../../docs/eu-article-loss-audit.md).
Measured results: [rebuild-results.json](rebuild-results.json).
