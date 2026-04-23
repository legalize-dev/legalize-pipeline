# RESEARCH-CA-HISTORY: extending Canadian federal law history pre-2021

**Goal.** Push the per-law git history as far back as possible without
fabricating data. The current ship captures 2021-02-26 onwards (since
`justicecanada/laws-lois-xml` was created on GitHub). Users expect
longer timelines — this doc evaluates every source we could add.

## Summary — the headline

**We can reach 2011 with clean, official XML** — same format we already
parse, no new source format, minimal effort. Pre-2011 has no authoritative
XML source; it would require HTML scraping with substantially diminishing
returns. The recommended phase plan below delivers **~15 years of history
per law** (vs. the current 5) with a focused one-week implementation.

## What the current ship captures

| Source | Coverage | Quality |
|---|---|---|
| `justicecanada/laws-lois-xml` git log | 2021-02-26 → today | Perfect. Official XML per upstream commit. |

Implemented via `JusticeCanadaClient.get_suvestine` + `CATextParser.parse_suvestine`.
Walks `git log -- {file}` in the local clone and emits one `Version` per commit.

## Sources evaluated for pre-2021 history

### 1. Wayback Machine — Justice Laws XML endpoint

**Status: recommended. Best ROI.**

The Wayback Machine archived Justice Canada's XML API at
`https://laws-lois.justice.gc.ca/eng/XML/{id}.xml` and
`https://laws-lois.justice.gc.ca/fra/XML/{id}.xml` as `text/xml` since
June/May 2011. The XML format is the same `<Statute>` / `<Regulation>`
schema we parse today, with only minor attribute differences in older
snapshots (pre-2016 XMLs use `startdate="YYYYMMDD"` on the root instead
of `lims:pit-date`; post-2016 matches the current schema exactly).

**Proof of concept** (this session, against the Access to Information Act):
- English: **50 distinct XML versions** on Wayback, 2011-06-25 → 2025-12-22
- French: **38 distinct XML versions** on Wayback, 2011-05-10 → 2025-12-30
- Both parsed through the unmodified `CATextParser` with only known-unknown
  tag warnings (blindaje preserved text):
  - 2014-12 snapshot → 568 paragraphs, correct title, parseable
  - 2019-05 snapshot → 575 paragraphs, correct title, parseable

**Access pattern** (CDX Server API — cheap, built for this):

```
http://web.archive.org/cdx/search/cdx
  ?url=laws-lois.justice.gc.ca/eng/XML/A-1.xml
  &collapse=digest        # dedupe identical content
  &output=json
```

Each row gives timestamp + digest + content length. One CDX query per law
returns the complete list of distinct snapshots; we then download each
unique version via
`http://web.archive.org/web/{timestamp}id_/{original_url}` (the `id_`
suffix returns the unmodified original bytes, no Wayback navigation frame).

**Scale estimate**
| Metric | Value |
|---|---|
| Laws in scope | ~11,600 (acts + regulations, both languages) |
| Average distinct XML versions per law on Wayback | ~30-50 (high-amendment acts) to ~2-5 (stable regs) |
| Total CDX queries | ~11,600 (one per law) |
| Total XML downloads | ~300,000 (estimated upper bound) |
| Rate limit (observed + prudent) | 2 req/s per worker |
| With `max_workers: 4` | 8 req/s effective → ~10 hours |
| Local cache size | ~3–5 GB (XMLs are 30-500 KB each) |
| New commits generated | ~200,000 additional (historical reforms) |

**Parser work required**: ~1-2 days
- Add fallback for `publication_date` when `lims:pit-date` is absent:
  read `startdate` attribute → `BillHistory/Stages[consolidation]/Date` → commit timestamp
- Handle the few extra tags we saw in older XMLs (`<a>`,
  `<ContinuedSectionSubsection>`, `<BilingualGroup>`, `<BillPiece>`) with
  proper rendering instead of the blindaje fallback
- Everything else reuses the existing parser

**Client work required**: ~3-4 days
- New method `get_wayback_versions(norm_id)` that queries CDX, dedupes,
  and downloads
- Merge Wayback versions + git-log versions into the single JSON blob that
  `parse_suvestine` consumes — dedupe by content digest across sources
- Respect Wayback rate limits with backoff on 429/503

### 2. `annual-statutes-lois-annuelles/` (upstream repo, 2001-present)

**Status: supplementary, not a replacement.**

Contents: every yearly collection of statutes as-enacted by Parliament,
from 2001 onwards. Root element is `<Bill>`, not `<Statute>` — these are
amendment bills (the diff Parliament passed), not consolidated text.

Example: `2001/2001-c10_e.xml` is Bill S-17 "An Act to amend the Patent
Act", headed `R.S., c. P-4` (= Revised Statutes, chapter P-4, the Patent
Act). Inside: `<AmendedText>` elements describing which sections change.

**What we can extract**: the reform timeline — who amended what, when.
That's metadata, not reconstructed consolidated text. Applying these
diffs to rebuild snapshot text is semantically complex and error-prone;
it's not worth it when Wayback has the consolidated XML anyway.

**Useful narrow application**: emit *marker* commits pre-2011 with only
metadata (commit message, date, empty body or reference-only note) so
users see "the Patent Act was amended in 2001 by SC 2001, c. 10" in
`git log`, even though we don't have the 2001 consolidated text.

**Scope**: covers 2001-2024 (24 years). Does not help pre-2001.

### 3. Canada Gazette (1841-present) — PDF parsing path

**Status: viable as Phase 3. Precedent in the codebase (Greece).**

Part III contains Public Acts as-enacted and goes back to 1841. Formats:
- 1998-present: PDF (native digital) and parallel HTML
- Pre-1998: scanned PDF of print editions (with OCR layer for ~1990+)
- Pre-1970s: often only in print archives, incomplete OCR

Same content-type problem as annual-statutes (bills, not consolidated),
but the Gazette is the **official, legally authoritative** source going
back to Confederation. If we commit to PDF parsing we unlock reform
timeline metadata back to 1841.

**Canadian precedent in legalize**: Greece (`fetcher/gr/`) already uses
`pypdfium2` for PDF text extraction of Hellenic gazette issues. The
pattern is established: load PDF → extract text by page → run through
a post-processor that re-segments into articles. Same approach would
apply to Canada Gazette Part III.

**What we'd get from Gazette parsing**:
- Timeline of every amendment to every federal act since 1841
- Assent dates, chapter numbers, bill numbers
- The text of the amendment itself (diff), not reconstructed consolidated
  text — consistent with the annual-statutes option but going further back

**What we wouldn't get**:
- Consolidated text pre-2011 (that's only via Wayback, and the Wayback
  archive doesn't go back that far for these URLs anyway)
- Complete pre-1970s coverage (OCR quality drops, some years are print-only)

**Scale** (rough estimates):
- ~600-800 PDFs per year (Part III editions + individual act PDFs)
- 150+ years × ~700 PDFs/year = ~105K PDFs in scope
- Realistically, we'd scope to Acts only (Part III chapter PDFs), not
  every issue of the Gazette — that brings it to ~15-20K PDFs
- Each PDF: 10-200 pages, full-text extraction ~100-500 ms with pypdfium2
- Total runtime: ~5-15 hours fetch + parse

**Risks & mitigations**:
- OCR quality on pre-1995 scans. Mitigation: tag versions with an OCR
  confidence score in `extra.ocr_confidence`; let the web surface "this
  amendment text was OCR-reconstructed" where relevant
- No structured XML — we'd build a heuristic segmenter for Sections /
  Subsections / Paragraphs. See `fetcher/gr/pdf_extractor.py` for the
  reference segmentation approach
- Binary assets in the output repo? No — we'd still only emit Markdown.
  The PDFs stay in the data cache, not in the public repo

**Effort estimate**: ~2-3 weeks of focused work
- PDF fetcher + local cache (~3 days)
- Segmenter/parser (~1 week)
- Mapping amendment PDFs → affected act IDs (~3 days)
- Tests on representative year samples (1905, 1945, 1985, 2005) (~3 days)
- Bootstrap run over full history (~1 day wall-clock)

### 4. CanLII (canlii.org)

**Status: unverified — their API/robots blocks our quick checks.**

CanLII is a volunteer-run legal information service. They publish historical
versions of some federal acts, but:
- Coverage is incomplete and driven by what their volunteer editors
  prioritized
- Their terms of service restrict bulk scraping
- They are themselves a downstream consumer — ideally one day they consume
  legalize.dev

Not a viable source for a bulk history bootstrap.

### 5. Pre-2011 Wayback captures of the old `lois.justice.gc.ca`

**Status: evaluated, low value.**

The predecessor site (`lois.justice.gc.ca` French, `laws.justice.gc.ca`
English) has Wayback captures back to 2001. But those captures are of
HTML pages, not XML — Justice Canada only started publishing XML around
2011 when `laws-lois.justice.gc.ca` launched. Pre-2011 would require:
- A separate HTML parser for the old Justice layout (different from 2011+)
- Fragile scraping of section-by-section content
- Incomplete Wayback coverage in those years

Estimate: +6-10 years of coverage (2001-2010) at 5-10× the implementation
cost of the XML/Wayback path. Poor ROI unless pre-2011 history is a
product requirement.

## Recommended path

### Phase 1 — current ship (done)
- Upstream git log → 2021-02-26 onwards
- Biweekly CI update
- Shipping-ready today

### Phase 2 — Wayback XML extension (proposed)

**Timeline**: ~1 week of focused work.

**Deliverable**: ~10 additional years of history per law (2011-2021)
delivered via the same `parse_suvestine` pipeline, no new output format.

**Work breakdown**:
1. Add `JusticeCanadaClient.get_wayback_versions(norm_id)` — CDX query,
   digest dedup, parallel downloads with rate limiting. [2 days]
2. Extend `get_suvestine` to merge Wayback + git-log sources, dedupe by
   content digest (so the same XML snapshot coming from both sources
   produces one Version, not two). [1 day]
3. Harden `CATextParser` for older XML variants: `startdate` fallback
   for publication_date, proper handlers for the few extra tags the
   pre-2021 XMLs use. [1 day]
4. Tests: fixtures captured from Wayback at 2011, 2014, 2018 for both EN
   and FR; verify deduplication and date extraction. [1 day]
5. One full re-bootstrap. [~12 hours wall-clock, unattended]

**Known risks**:
- Wayback rate limiting. Mitigation: 2 req/s per worker, honor 429/503
  with exponential backoff, resumable per-law progress.
- A handful of early snapshots return `warc/revisit` or DOCTYPE errors
  instead of valid XML. Mitigation: skip on `XMLSyntaxError`, same
  graceful-degradation path as the current fallback.
- Some regulations may have moved URLs over time (pre-2013 consolidation
  renumbered). Mitigation: CDX by digest still dedupes correctly; a
  missing URL just means no pre-2011 coverage for that specific reg.

### Phase 3 — PDF parsing of Canada Gazette for 1841-2011 coverage

**Timeline**: ~2-3 weeks. Owner decision — user has approved this approach
in principle (2026-04-21): "No me parecería mal tampoco parsear pdfs como
en grecia". Greece's `fetcher/gr/` is the reference implementation.

**Scope**: Canada Gazette Part III, Public Acts as-enacted. Fetches PDFs
per chapter per year, extracts text with `pypdfium2`, segments into
Sections/Subsections using heuristics calibrated against known-good
reference years (1905, 1945, 1985, 2005, etc.).

**Output shape**: reform-event commits with:
- Correct assent date (from Gazette's own header)
- Amendment bill number + chapter reference
- The amendment text itself, OCR confidence tagged for pre-1995 scans
- Link back to the official Gazette PDF in `extra.gazette_url`

**Combined coverage after all phases**:
| Phase | Era | Source | Content type |
|---|---|---|---|
| 1 (shipped) | 2021-02 → today | upstream git log | Consolidated XML |
| 2 (Wayback) | 2011-05 → 2021-02 | Wayback CDX + XML | Consolidated XML |
| 3 (Gazette PDF) | 1841 → 2011 | Canada Gazette Part III | Amendment bills (OCR) |

A single act like the Criminal Code (originally 1892) would have a
continuous reform timeline from its enactment through today, even though
the *consolidated* text is only directly available from 2011 onwards.

### Quick-win alternative to Phase 3 (if PDF parsing is deferred)

Use `annual-statutes-lois-annuelles/` (already in our upstream clone) for
2001-2010 metadata-only commits. Gives ~20K "ghost" commits showing the
reform timeline for the gap decade. ~3-4 days of work. Strictly a subset
of what Phase 3 Gazette parsing would give.

### Not in scope under any phase

Print-only archives pre-1970s with no OCR. This is an industry-wide gap;
even Library and Archives Canada's digitization project leaves chunks of
the pre-war Gazette un-OCR'd. Not a Legalize-specific problem.

## Honest statement for the README

Proposed line for `legalize-ca/README.md`:

> Canadian federal law history begins on **2021-02-26** (when Justice
> Canada started publishing consolidated XML to GitHub) and, via the
> Wayback Machine archive of the same XML endpoint, extends back to
> **May 2011** for most acts and regulations — roughly 15 years of
> continuous consolidated text. Pre-2011 amendments are referenced in
> each act's historical notes but not rendered as separate versions;
> Justice Canada did not publish structured XML before then.
