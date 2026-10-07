# EU article loss and SPEC v0.4 audit

Date: 2026-10-07. Scope: legislation of EU institutions (`eu`), not national
European corpora. Engine baseline: `7dc4b87`, branch `feat/es-reemission`.
Fix branch: `fix/eu-numbered-provisions`, in an isolated worktree to preserve
concurrent changes in the shared checkout.
[Issue 19](https://github.com/legalize-dev/legalize/issues/19) was read in full,
including its distinction between observations and an inferred cause.
The initial issue-19 investigation performed no corpus reprocess, country
commit, push or publication. The subsequent authorized local reconstruction
is tracked separately below and in the runbook.

## Confirmed cause and repair

The reported symptom is reproducible, but the inferred OJ cause is incomplete.
The current walker already emits `p.oj-normal` inside unclassified paragraph
divs, with their numbers, whether or not a table follows. The live CELLAR OJ
GDPR text confirms this.

The published GDPR body matches the *consolidated* fixture instead:

```html
<div class="norm">
  <span class="no-parag">1. </span>
  <div class="norm inline-element">Taking into account ...</div>
</div>
```

`_walk_body` descended into these divs but emitted only `p` leaves. Direct div
text and the sibling numbering span were discarded. Articles 24, 25 and 55
therefore became empty. Article 5 retained the `p` and grid-list children of
paragraph 1, lost its `1.` marker, and discarded the div-only paragraph 2.

The fix emits text-bearing `div.norm` leaves, preserves inline formatting, and
prepends `span.no-parag` to the first emitted child paragraph. Containers still
recurse in document order; list and data tables retain their separate paths.
Existing `h4`, `h5`, `abs`, `list` and `table` renderer classes are preserved.
The shared renderer and the role migration discussed in
[pipeline issue 128](https://github.com/legalize-dev/legalize-pipeline/issues/128)
are unchanged.

The broad sample exposed an additional loss in `32014R1368`, Article 1:
`_is_list_table` counted columns in nested tables and rejected the outer list
table. It now examines only that table's columns. `_parse_list_table` likewise
walks only its own rows and preserves content order through nested lists,
without revisiting their rows. Quoted article labels inside amending lists
remain body text, rather than becoming articles of the enclosing act.

The HTML fallback explicitly uses UTF-8 and strips controls before lxml can
replace NUL with U+FFFD. There is no node deduplication based on Python `id()`.

## Measurements and their limits

The reusable metric is
[`check_eu_article_bodies.py`](../scripts/check_eu_article_bodies.py). It handles
non-breaking spaces, ignores subtitles as body text, stops at headings of equal
or higher level, and checks the last article at EOF. It reports **candidates**;
it does not fail a publication or infer a repeal from an empty heading.

The historical snapshot was fetched as an archive, without creating or
changing a country Git repository:
`9feae1e860f0fecd95a4e7f2ae085293dd3492d4`.
An entire scan of that snapshot found 15,892 law files, 81,131 matching article
headings, 7,144 empty candidates, and 1,044 affected files. These are fresh
measurements with the metric above, not a reproduction of the issue's older
13,827-file / 80,937-article figures. In particular, this metric includes EOF
and chapter boundaries; headings are a structural signal, not legal evidence.

A deterministic sample used seed 19, up to 30 files per publication decade
and empty/nonempty stratum, plus the 25 most articulated files and the GDPR.
This selected 358 laws. Sources were requested from CELLAR at the snapshot's
consolidation date where available, otherwise as the original OJ text.
357 sources were obtained: 167 consolidated and 190 original. `31960R0009(01)`
remained unavailable after content negotiation and a manifest lookup timed out.
Sources and SHA-256 checksums are retained in
[`issue-19-sample.csv`](../research/eu-v2/issue-19-sample.csv).

Both parser versions rendered the **same source bytes** with the same current
shared renderer. These counts describe that paired sample, not a reprocessed
corpus or all historical versions:

| Measurement | Before | After |
|---|---:|---:|
| Source files rendered | 357 | 357 |
| Matching article headings | 9,145 | 9,145 |
| Empty structural candidates | 1,517 | 1 |
| Files with candidates | 146 | 1 |
| Paragraphs emitted | 94,707 | 114,445 |
| GDPR empty candidates | 37 / 99 | 0 / 99 |

190 sample outputs changed; 167 were byte-identical. The GDPR OJ and
consolidated excerpts now render identically for Articles 5 and 25, including
`1.`, paragraph 5(2), all six lettered items and all three paragraphs of Article 25.
The fresh GDPR count is 37 rather than the issue's 35; that exact older count
was not reproduced. The fix recovers all 37 measured candidates.

The remaining candidate, `32016R1036` Article 2, is a **structural false
positive**, not a lost or repealed article: its internal `A. NORMAL VALUE`
heading is rendered as `###`, above the article's `####` depth. Its provisions
are present after that heading in the Markdown. After source review, the
sample has zero remaining confirmed empty articles caused by dropped text.
This does not certify complete text fidelity or absence of partial losses.

To check legitimate empty provisions independently, source article containers
were copied, their article labels and subtitles removed, and the remaining
text inspected after removing consolidation markers. Empty or marker-only
`deleted`, `repealed`, `reserved`, `omitted` and underscore placeholders were
checked separately. No such cases were found among 8,324 semantic article
containers in the downloaded sources. Legacy HTML lacks these IDs; that
measurement does not certify its provisions or unsampled historical versions.
Never convert the raw candidate count into a count of parser bugs without
checking the corresponding source.

```sh
.venv/bin/python scripts/check_eu_article_bodies.py /path/to/legalize-eu/eu
.venv/bin/python scripts/check_eu_article_bodies.py /path/to/rendered-sample
```

## SPEC v0.4 and onboarding review

The latest local specification is
[v0.4](https://github.com/legalize-dev/legalize/blob/main/SPEC.md).
The current [country playbook](../adding-a-country/README.md) was reviewed,
including its research, history, coverage, five-law review and health gates.
Prepared engine changes are not evidence of their publication. The inspected
historical corpus snapshot has a flat layout and no `.legalize.yml`; under
v0.4 that is the pre-manifest compatibility case, not a claimed v0.4 corpus.
The existing `hub/check_spec.py --files-only --spec hub/SPEC.md` checker scanned
all 15,892 snapshot files and returned one violation: the missing manifest.
That check does not establish source text, date provenance or Git history fidelity.
The engine already prepares `LAYOUT["eu"] = SHARDED` and the as-enacted default
with a consolidated override. Applying those changes is a separate re-emission.

An independent read-only review of five existing fixtures found **0/5 fully
passing**, despite passing article-sequence and hygiene checks:

| Fixture | Article sequence | Remaining fidelity failures |
|---|---:|---|
| GDPR | 99 / 99 | Three final footnotes outside the selected container |
| MiCA | 150 / 150 | 35 final footnotes outside the selected container |
| MAR OJ | 39 / 39 | Annexes I/II, correlation table and OJ italics |
| DSA OJ | 93 / 93 | OJ italics |
| AI Act OJ | 113 / 113 | Thirteen annexes outside the selected container |

This was parser-to-renderer fixture review, not the full fetch-to-commit gate.
It must not be labelled a Step 7 pass. Concrete remaining blockers:

1. **Text and rich formatting:** `_parse_xhtml_to_paragraphs` and the XML
   multi-version path return the first `eli-container`; sibling annexes and
   footnotes disappear. `_walk_body` drops all `oj-doc-ti`, including annex
   titles. `_extract_text` does not preserve `oj-bold` / `oj-italic` or internal
   link targets. The §0.4 inventory and rich-format review remain incomplete.
2. **History completeness:** `EURLexClient.get_text` omits the original act
   when consolidations exist, truncates chains above 200 versions and skips
   failed downloads. It can successfully return an empty version envelope.
   No rebuilt history should accept any of these as complete.
3. **Commit identity:** all EU reforms use the base CELEX as `Source-Id`.
   `commit_one` deduplicates by `(Source-Id, Norm-Id)` and skips later versions.
   The fast import route has a different date-aware deduplication; the finding
   must not be extrapolated to that path. Amended as-enacted acts also need
   the full amendment chronology, rather than only `last_amendment`.
4. **Dates:** raw XHTML creates a version dated `today()` with an empty norm
   ID. The generic reform fallback can then produce an empty `Source-Id` and
   a run-date `Source-Date`. Invalid envelope dates also fall back to today.
   Metadata calls `work_date_document` the publication date, although GDPR
   adoption is 27 April and its OJ publication is 4 May 2016. MAR similarly
   distinguishes 16 April adoption from 12 June 2014 OJ publication.
5. **Daily and metadata parity:** daily consolidation discovery still matches
   only regulation CELEX IDs, despite directives and decisions in the expanded
   config. The per-act metadata fallback merges only authors, unlike the bulk
   catalog's subjects, repealers and amendment data; it can misclassify a repeal
   as expiration. The persistent catalog also needs a refresh policy. For
   sanitized CELEX IDs without ELI, the fallback URL uses the changed identifier
   instead of the original CELEX.
6. **Unfinished evidence:** the claimed history spike cites only one GDPR
   consolidation, although MAR fixtures do demonstrate multiple dated versions.
   The prescribed `version-spike.txt` is missing. Format coverage lacks version
   counts and measurements for the expanded act types. The PDF/A exemption is
   written down but does not establish the playbook's <1% or disproportionate
   cost criteria. Metadata inventory completeness is not established by
   selective SPARQL fixtures.

There is also a documentation conflict to resolve before history changes:
the playbook asks for effective dates as `GIT_AUTHOR_DATE`, while SPEC §Dates
requires official publication dates. SPEC's future-date example itself invokes
entry into force. The operative date fields must be distinguished explicitly;
this parser fix does not redefine them or migrate the shared role contract.

## Validation and eventual repair

Dedicated environment: `engine/.venv`, Python 3.12.12, Ruff 0.15.8.
Regression fixtures contain only GDPR Articles 5 and 25, in both source formats.
Tests cover standalone and multi-version parsing, full cross-format text,
numbering, nested list ordering and duplicates, quoted article labels, UTF-8,
controls, EOF and empty/reserved metric candidates.

Validation: **2,181 passed, 27 skipped** in the isolated fix branch's full engine
suite. The shared checkout also passed with concurrent unrelated changes.
Ruff lint and
format checks pass for `src/`, `tests/` and the new metric script. No consumer
database or production job was started.

The published bootstrap and every affected reform commit need regenerated
content; appending a correction commit cannot repair the legislative record.
The current `legalize reprocess` is not that operation: it only force-fetches
and invokes `commit_one`, which skips existing source identities. Do not use it
as a history-rewrite command.

A surgical issue-19 repair would require a complete affected-file/version
inventory, preserved source versions, a backup and an isolated rehearsal, then
a reviewed `filter-branch` rewrite of the affected snapshots while preserving
actual legislative identities and dates. The user accepts a complete EU
reprocess instead. That broader v0.4 re-emission must first resolve the blockers
above and pass §0.3, §0.4, §0.5, §0.7 and the full five-law gate, followed by a
broad rehearsal and health checks. It must regenerate every legislative version,
not append fix-up commits. Corpus consumers must then reconcile the rewritten
commit hashes through a full sync. Publication remains a separate authorization.

## Subsequent reconstruction audit — 2026-10-07

The user subsequently authorized a complete local rebuild and easy English
consolidated additions. Work continues in `fix/eu-reprocess`, preserving the
initial parser commit `9f4dd03` and the shared checkout's unrelated changes.
The untouched full mirror pins `ed827b14dc697af0b25b8ef1a9a383051912810e`:
15,959 laws and 20,348 commits. A full measurement of that pinned tree found
81,139 matching Article headings, 7,153 empty candidates and 1,045 affected files.
These are the new reconstruction's baseline, distinct from the older archive.

The final parser was also rerun on the original 357 identical source files:
9,187 headings, zero empty candidates, zero affected files and 125,887
paragraphs. The baseline on those bytes remains 9,145 headings, 1,517 empty
candidates and 94,707 paragraphs. The recovered 42 headings come from previously
unhandled legacy body classes. The Article 2 internal-heading false positive is
fixed by keeping its subheadings below the article. This paired measurement
still describes a sample, not the complete rebuilt corpus.

The independent fetch-to-commit gate now passes all five checks on five laws,
including 28 historical source versions and a five-PDF-to-HTML boundary. The
final optimized parser reproduces all 28 reviewed legislative blobs byte for
byte. One CE drawing per MDR snapshot remains an explicit visual exception.
Whole-corpus PDF, image and amending-act gaps are recorded separately; the
five-law pass does not certify those unsampled sources.

Future unamended originals use qualified entry-into-force dates for their
point-in-time text and `last_updated`, preserving official publication in
`Source-Date` and the author date. All 13 actual future records were reviewed;
no new status enum is necessary. Multi-valued end dates stay in raw metadata
rather than becoming an arbitrary general expiration date.

Actual reconstruction, complete measurements and remaining exceptions are
tracked in [PROGRESS.md](../research/eu-v2/PROGRESS.md),
[RESEARCH-EU.md](../research/RESEARCH-EU.md) and
[the reconstruction procedure](eu-reprocess.md). No publication is authorized.

The local reconstruction is now complete at `f78c15e5`: 18,545 laws and
32,628 legislative source commits. The full pinned comparison is 7,153 → 7
empty candidates across the same 15,959 law identifiers; the rebuilt whole tree
has fourteen. Source review classifies five legitimate empties and nine
structural false positives, with no confirmed dropped body among those candidates.
Every final file and source commit matches the prepared output and provenance;
a repeated commit run leaves HEAD and tree unchanged. The runbook records PDF,
image, own-file and full-checker exceptions. Structural checks alone do not
certify full source fidelity.
