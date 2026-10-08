# Spain v0.4 rebuild

Updated 2026-10-08. The September branch was an intermediate implementation,
not a finished publication. Follow `adding-a-country/README.md` and its gates;
this document records the Spain-specific choices and push precautions.

## Prepare and validate locally

Use a separate candidate repository and data directory. Preserve the existing
checkout and all unpublished branches. Fetch the entire consolidated catalogue,
without a publication-year cutoff. Keep the raw responses for replay and compare
the final set against both the catalogue snapshot and the current published IDs.

Enable these together in the candidate engine branch:

- `ESCAPES_LEGAL_NUMBERING` includes `es`.
- `LAYOUT["es"]` uses `{directory}/{id_sha1_2}/{identifier}.md`.

The canonical ELI `/dof/spa/xml` response supplies the diary metadata that the
consolidated API omits. Transient errors must not be accepted as successful
metadata-poor downloads. Official publication dates remain `Source-Date`;
commencement belongs in the rendered version's `last_updated` and source metadata.
Each explicit commencement stage gets its own `Effective-Date` trailer, including
source events without a body change. Unknown commencement remains unknown: omit
`last_updated` when selected blocks lack the source date and record their IDs in
`extra.effective_date_unknown_blocks`. Never substitute publication for it.

The source-fidelity tests use fresh fixtures under `tests/fixtures/es/`. The
five-law independent review and a local rehearsal must pass before the full
build. For nested tables, preserve the source grid with intentional HTML; other
tables use Markdown pipes. Run deep health on the completed build, not while
fast-import is still materializing its working tree.

## Push in bounded slices

The supported helper is `legalize push`. `legalize commit --batch` only commits;
it does not push. The older shell helper mentioned in the September runbook no
longer exists. Never send the entire rewritten object graph in one first push.

Keep the public default branch serving the old corpus while uploading the new
history to a staging branch. On the candidate clone, configure `origin` to fetch
only that staging branch: the push helper refreshes origin first, and fetching
all refs would download the old corpus history into the new candidate.

```sh
legalize --config candidate.yaml push -c es --branch rebuild/es-v04 --slice 5000 --dry-run
legalize --config candidate.yaml push -c es --branch rebuild/es-v04 --slice 5000
```

Verify the remote staging tip equals the candidate HEAD; do not infer completion
from a process exit code alone. If a slice is too large, reduce the slice size and
resume. The helper uses SSH keepalives and a stall timeout. Do not rewrite the
public default branch to a one-law root just to make uploads easier.

Before final promotion, preserve the live tip in a reachable backup ref and
verify that no scheduled update has moved it. Coordinate consumer cache
invalidation and engine rollout. Promote the already-uploaded candidate with an
explicit `--force-with-lease` expecting that exact live SHA. Never delete and
recreate the GitHub repository.

After publication, downstream consumers must reconcile their full local history;
an incremental lookback cannot discover every rewritten historical commit.
Verify representative live bodies, version histories and tables.

## Expand coverage in separate tranches

Adding new files after the rebuild does not require another rewrite. The approved
first diary tranche is Section I from 2010 onward. Retain administrative acts with
source-derived signals instead of invented semantic classifications. Exclude
image-dominated acts with durable records. Later historical tranches need their
own fidelity checks for missing structure and empty source text.

See `00-DECISIONES.md` for the approved scope. Its historical estimates and
unimplemented proposals are evidence to recheck, not operational commands.

Run the first diary tranche locally with the maintained, resumable runner:

```sh
python scripts/fetch_es_expansion.py --config candidate.yaml --since 2010-01-01
```

It uses the official summary index for every calendar day, including extraordinary
Sunday editions. Original responses remain in the HTTP cache; `diary-raw/`
retains XML (normalized from original HTML when no ELI resource exists);
`excluded/` records policy exclusions and `diary-fetch-progress.json` records
failures. Resolve every failure before reporting the tranche complete. Acts
without consolidation remain `as_enacted`; a later official consolidation is
picked up by the daily path. The daily rejects backfills that would overwrite a
newer body and preserves existing source events on reruns.

Validation on 2026-10-08: both five-law source gates pass independently. The
consolidated gate includes delayed commencement and a projected Civil Code
wording superseded before it took effect. The diary gate includes tables, inline
formulas, multilingual text and original bodies retained across amendment events.

Original HTML without an ELI resource also passes an independent five-law gate.
It retains original source fields, links and analysis, including identical
republication notes. Regional scope is mapped only from recognized explicit
department names; unsupported regional identities and reference graphs fail
rather than being assigned to the state corpus or silently discarded.
