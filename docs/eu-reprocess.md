# Rebuilding the published EU corpus

This procedure replaces incorrectly generated legislative commits. It does not
append fictional reforms or pipeline fix-ups to legislative history. The scope
is EU institutional legislation, not national legislation. Preserve every law
in the pinned corpus. Optional catalog additions are separately qualified by
source accessibility; a catalog query is not a measured published corpus.

## Preserve the published history first

Work in an isolated engine worktree and its own Python environment. Inspect the
original checkout's branch, status and worktrees before doing anything there.
Clone a complete mirror of the published corpus, then a separate working copy:

```sh
git clone --mirror https://github.com/legalize-dev/legalize-eu.git countries/eu-backup.git
git clone --no-hardlinks countries/eu-backup.git countries/eu-reprocess
git -C countries/eu-backup.git fsck --full
git -C countries/eu-reprocess remote -v
```

The working copy's origin must point at the local backup. No rebuild command
needs access to a production push remote. Record the published HEAD and scope
before removing any generated history; keep the mirror unchanged throughout.

## Download and validate before rewriting

```sh
engine-eu-reprocess/.venv/bin/python engine-eu-reprocess/scripts/fetch_eu_reprocess.py countries/eu-reprocess countries/data-eu-reprocess --html-only --workers 3
engine-eu-reprocess/.venv/bin/python engine-eu-reprocess/scripts/fetch_eu_reprocess.py countries/eu-reprocess countries/data-eu-reprocess --pdf-only
engine-eu-reprocess/.venv/bin/python engine-eu-reprocess/scripts/check_eu_article_bodies.py countries/eu-reprocess/eu > before.json
```

`inventory.json` pins the input HEAD and law identifiers. `versions.json` records
all English consolidation manifestations, including versions unavailable as
HTML. Source files and SHA-256 download records are resumable. Missing source
versions fail the run; they are not successful histories with omitted commits.
The original publication is included even when consolidations exist. Completed
HTML may be stored as gzip; the checksum always identifies uncompressed source
bytes. Keep the frozen metadata and full public CDM work properties, including
reified date annotations. Only `EV` qualifies a generic entry-into-force date;
`MA`, partial application and unknown annotations remain raw source facts.

The default fetch path fails on unavailable or unsafe versions. A local draft
may explicitly accept reviewed exclusions with `--accept-version-gaps` in the
preparation script. Every exclusion records the source ID, date, reason and
available hash in `source-version-exclusions.json`, and is repeated in the law's
`extra.source_version_gaps`. This does not certify complete source history.
The ordinary bootstrap/daily client cannot reuse an excluded draft's cache as
a complete chain.

```sh
engine-eu-reprocess/.venv/bin/python engine-eu-reprocess/scripts/prepare_eu_reprocess.py countries/data-eu-reprocess --accept-version-gaps
engine-eu-reprocess/.venv/bin/python engine-eu-reprocess/scripts/prepare_eu_reprocess.py countries/data-eu-expansion
engine-eu-reprocess/.venv/bin/python engine-eu-reprocess/scripts/prepare_eu_reprocess.py countries/data-eu-amenders
```

Render representative original and consolidated versions through the real
pipeline into a local sandbox. Follow the full five-law gate in
[adding-a-country/step-7-quality-gate.md](../adding-a-country/step-7-quality-gate.md),
including an independent review and a PDF/HTML boundary check. Run the engine
suite and lint in the isolated environment. Review empty-article candidates
against their source: deleted or reserved provisions must be classified
separately from paragraphs lost by the converter.

## Dates and source identity

The [format specification](https://github.com/legalize-dev/legalize/blob/main/SPEC.md) takes precedence over playbook
examples. An original act is dated by its official journal publication, not its
adoption date. CELLAR exposes both older journal work dates and the newer
`official-journal-act_date_publication` property.

A consolidated CELEX identifies its own source snapshot. Its date is the
snapshot's applicability date, not an official publication date. If no official
publication date is supplied for that snapshot, omit `Source-Date`; use the base
act's `publication_date` as the Git author-date fallback required by SPEC v0.4.
Keep the applicability date in `last_updated`. Do not replace it with the run
date or clamp retroactive consolidations to the original publication date.

Queue the original first and then every consolidation in source-version order.
Some consolidated applicability dates legitimately precede the original act's
publication. Preserve these dates without letting the later original commit
overwrite the consolidated body. Bootstrap and daily must use the same real
source IDs; a synthetic daily-run ID is not a legislative source.
SPEC v0.4 permits a pre-1970 Git timestamp clamp to 1970-01-02. Keep the actual
source publication in `Source-Date` and the frontmatter; the clamp is not a
historical source date.

Unconsolidated amended acts retain their as-enacted body. Their amendment
commits update `last_amendment` using actual amending-act IDs and publication
dates; they do not claim to incorporate text unavailable from the source.

A qualified future `EV` date on an unamended original is the date of that
point-in-time text. Keep `last_updated` at this future date and the original's
`Source-Date` at publication. Preserve CELLAR's present-day in-force flag in raw
source metadata; do not label a future commencement as expiration.

Before committing, merge the prepared JSON files from the pinned scope,
qualified additions and accessible required amending acts into a separate
`countries/data-eu-rebuild/json/` directory. Copy files by name, reject duplicate
identifiers, and keep the source inventories beside their respective caches.
On APFS, `cp -c` creates independent copy-on-write files without doubling the
physical cache size; ordinary copies work on other filesystems with enough space.
Do not use symlinks or hardlinks for a directory the pipeline may write into.
The fast committer's unrelated-history guard deliberately refuses successive
disjoint scopes, so reconstruct one combined stream rather than stacking them.
Reconcile unavailable required amending-act files explicitly: the as-enacted
notice promises separate files, and missing sources/statuses are coverage gaps,
not a reason to invent legal status or drop known amendment identifiers.

## Replace the generated history in the working copy

After the source and fidelity gates pass, use `git filter-branch` on the isolated
working copy to remove generated `eu/` files from historical trees and prune
empty legislative commits. Preserve repository metadata, but remove legislative
trailers from surviving metadata-only commits. Otherwise source-ID deduplication
can mistake old metadata commits for already reconstructed laws.

From the workspace root, with the complete backup already checked:

```sh
export EU_REBUILD_REPO="$PWD/countries/eu-reprocess"
git -C "$EU_REBUILD_REPO" status --short
git -C "$EU_REBUILD_REPO" remote -v
FILTER_BRANCH_SQUELCH_WARNING=1 git -C "$EU_REBUILD_REPO" filter-branch \
  --index-filter 'git -C "$EU_REBUILD_REPO" ls-files -z eu/ | git -C "$EU_REBUILD_REPO" update-index -z --force-remove --stdin' \
  --msg-filter 'sed -E "/^(Source-Id|Source-Date|Norm-Id):/d"' \
  --prune-empty -- main
engine-eu-reprocess/.venv/bin/legalize \
  -o countries.eu.repo_path="$EU_REBUILD_REPO" \
  -o countries.eu.data_dir="$PWD/countries/data-eu-rebuild" commit -c eu --all
```

`filter-branch` also keeps `refs/original/` as a local recovery reference; the
separate mirror remains authoritative. Do not delete either during validation.
Do not use `commit --batch`: it pushes between batches. This run uses ordinary
fast-import with no push. Generate final repository metadata after the combined
stream is committed, and repeat that commit phase to prove idempotence.

Never run this against the backup or the published remote. Re-emit every source
version from the validated structured data using the engine's normal commit
path, with the configured legislative bot identity. Generate `.legalize.yml`
from the chosen layout and validate paths against it. Re-run the commit phase:
it must generate no duplicate source-version records and must leave the tree
unchanged.

Measure the rebuilt corpus, including file/version counts, empty-body
candidates, legitimate deleted/reserved provisions, content fidelity and
history/date/identity conformance. A sample measurement is not a full-corpus
measurement. Keep machine-readable before/after results with the local run.

## Publication is a separate operation

A local rewrite does not authorize pushing replacement history. Publication
needs an explicit approval of the validated result, a force-with-lease against
the pinned published HEAD, and a full reconciliation of downstream Git hashes.
An incremental ingestion cannot remove obsolete commits after a rewrite.

## Run started on 2026-10-07

The user authorized a complete local reconstruction of the currently published
EU laws. The backup is `countries/eu-backup-20261007.git`; the working copy is
`countries/eu-reprocess`; the source cache is `countries/data-eu-reprocess`.
Input HEAD: `ed827b14dc697af0b25b8ef1a9a383051912810e`.
Before: 15,959 law files, 81,139 Article headings, 7,153 empty-body candidates.
These are measured on that full pinned checkout; candidates are not yet a count
of confirmed lost articles. Current execution status is recorded in
[research/eu-v2/PROGRESS.md](../research/eu-v2/PROGRESS.md).

The user subsequently authorized easy additions with consolidated EU sources.
Of 6,545 new candidates, 3,263 had entirely HTML English version chains. After
excluding 11 recommendations outside the configured scope, one unavailable
original, three ambiguous status records, 773 image-bearing chains and one
unsupported section layout, the qualified optional scope adds 2,474 laws.
Another 1,637 candidates lacked English consolidations, 1,637 needed PDF history
validation, and eight had unsafe source identifiers. These are measured catalog
qualification counts, not completed publication counts.

Dependency closure adds 112 accessible amending acts. Another 142 required own
files remain excluded for source/type/status reasons, while their real identifiers
and dates remain in the affected laws' history. This is an explicit conformance
exception. The combined prepared scope has 18,545 laws and 32,628 source commits,
verified against every selected original, consolidation and amendment record.

CELLAR may associate later journal corrections with the same amending act. Both
metadata query paths select its earliest official publication, and the envelope
also normalizes older cached records. A later correction date cannot create a
second reform with that same source identifier. This affected 46 pinned chains.

In the pinned scope, 303 consolidated versions require PDF. Of 298 downloaded,
214 pass the text extraction guards; 62 are rasterized legal content and 22 have
unreadable font/CID mappings. Five advertised bodies cannot be downloaded. The
89 reviewed gaps affect 23 acts. Guard success is not independent fidelity
certification of all 214 sources. OCR and font recovery are deferred because
they need separate legal-text validation. Source images in HTML leave a visible
omission marker and a snapshot-specific official link; drawings are a documented
visual exception, never silently treated as reproduced.

## Completed local reconstruction — 2026-10-07

Working HEAD: `f78c15e5652859371b7e1062964d3ea383c2f041`.
The rebuilt branch contains **18,545 laws**, **32,628 legislative source commits**
and three repository-metadata commits. The pinned mirror still contains its
original 20,348 commits. `refs/original/refs/heads/main` also retains the old HEAD
inside the working clone. Nothing was pushed.

Every final file matches the prepared renderer output byte for byte. Every
legislative commit matches the expected source ID, publication-date trailer,
author date, bot identity and per-law source-version sequence. `git fsck --full`
passes. Repeating the real commit command adds zero commits and preserves both
HEAD and tree. The fast committer's return value includes already processed
sources; its console now separately reports the number actually created.

| Scope measured on final files | Files | Article N headings | Empty candidates |
|---|---:|---:|---:|
| Pinned corpus before reconstruction | 15,959 | 81,139 | 7,153 |
| Same law identifiers after reconstruction | 15,959 | 88,855 | 7 |
| Qualified optional additions | 2,474 | 18,427 | 7 |
| Required amending-act additions | 112 | 853 | 0 |
| Entire rebuilt tree | 18,545 | 108,135 | 14 |

The pinned comparison includes refreshed source histories and recovered annexes;
it is not a comparison of identical source bytes. The separate paired sample
of 357 identical sources changes from 9,145 headings / 1,517 candidates to
9,187 headings / zero candidates. GDPR changes from 37/99 empty candidates
on that measured consolidated source to zero; Articles 5 and 25 retain their
numbers and complete paragraph text.

All fourteen final candidates were checked against their exact official source:
three provisions deliberately not reproduced in the Athens Convention extract,
one deleted article, one explicitly unused article, eight false positives from
internal headings and one complete obligation carried in a source subtitle.
Thus five are legitimate source empties and nine are structural false positives;
none is a confirmed dropped body. This does not certify absence of partial text
loss elsewhere. Evidence and source checksums are in
[article-body-review.json](../research/eu-v2/article-body-review.json).

`health --deep`: zero errors, two warnings — unpublished commits and eight of
331 current `last_amendment` references without an own file. The broader history
closure has the 142 reviewed own-file exclusions described above. The v0.4
files-only checker passes every final file with zero violations.

The full hub checker reports two history findings, which remain visible:

- Its amended-history count uses only commits carrying `Source-Date`. It flags
  4,125 point-in-time files: 4,111 actually have multiple source commits, whose
  consolidation publication dates are unknown, and fourteen are unamended
  originals on a qualified future commencement date. Thirteen of those future
  originals were in the pinned corpus; the fourteenth is required amender
  `32026R2201`, published on 5 October and effective on 25 October.
- `32008R0514` has an original publication on 10 June 2008 and an official
  modification relation to `32008R0507`, published on 7 June. EUR-Lex identifies
  the latter as an implicit partial repeal with a partial end of validity on
  26 June. The source dates are preserved and the original is emitted first;
  the checker's monotonic publication-date rule flags this chronology exception.
  See the [official act information](https://eur-lex.europa.eu/legal-content/en/ALL/?uri=CELEX%3A32008R0514).

This is a locally reconstructed, measured draft with explicit source and
conformance exceptions, not a claim of complete EU-law coverage or a completely
passing global checker. Engine validation: 2,201 tests passed, 27 skipped; Ruff
and required hooks pass. Before publication, review the exceptions and the
global checker's treatment of undated and future source versions, then replace
the remote history with concurrency protection and perform a full downstream
hash reconciliation. An incremental sync cannot replace that reconciliation.

Machine-readable run summary:
[rebuild-results.json](../research/eu-v2/rebuild-results.json).

## Published reconstruction — 2026-10-07

The owner published the reviewed reconstruction with an explicit
`--force-with-lease` against the pinned old HEAD. Remote `main` was then
verified at `f78c15e5652859371b7e1062964d3ea383c2f041`; the backup remains
unchanged. The source and conformance exceptions above remain explicit.

The engine publication is isolated from unrelated pending country work. Its
renderer reproduces all 18,545 final files and all 32,628 historical source
versions byte for byte. The shared CSS/paragraph contract remains compatible.
Validation on this publication branch: 2,137 tests passed, 27 skipped; Ruff
passes. The larger earlier test count belongs to the original working branch.
Consumers must reconcile their stored Git identities with a full local sync.
