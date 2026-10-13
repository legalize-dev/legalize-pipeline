# Ireland v0.4 evidence

The source and scope assessment is [RESEARCH-IE.md](../RESEARCH-IE.md). The
[quality review](quality-review.md) and its [machine-readable evidence](sample-4-review-evidence.json)
cover the approved sample. The [reuse assessment](reuse-assessment.md) records
the LRC confirmation of the applicable reuse terms. Source-specific corrections are
documented in [effects-source-corrections.md](effects-source-corrections.md).

`census-summary.json` counts identities separately from language manifestations.
`http-manifest.json` records captured source URLs, response metadata and hashes;
`revised-versions.json` records the catalogue's exact snapshot links. Regression
fixtures and their provenance are under `tests/fixtures/ie/`.

The [Companies 2020 source-gap manifest](../../tests/fixtures/ie/archive-companies-2020-source-gaps.json)
identifies four official plain-PDF objects that omit the already-operative section
1384A from their bodies. They are retained with a warning attached to each affected
version, without reconstructing the missing text. Only the recorded complete-file
SHA-256 values and the exact omission `{1384A}` qualify; another omission, changed
bytes or the evidence excerpt still fails the completeness check.

Those four objects represent **three declared cutoffs**: 1 January, 21 August and
31 December 2020. The January and March objects contain the same words; March
corrects the separation of section 1181(4), while both covers still state
1 January 2020. The manifest records the textual-equivalence hash, exact source
URLs and [primary insertion](https://www.irishstatutebook.ie/eli/2017/act/9/section/83/enacted/en/html)
and [commencement evidence](https://www.irishstatutebook.ie/eli/2017/si/250/made/en/html).
The [research assessment](../RESEARCH-IE.md#explicit-source-fidelity-exception-companies-act-2014-2020-snapshots)
describes the limitation and per-version rendering in full.

Incremental updates cannot backfill or alter published historical events. A
newly discovered older event or a transition of a previously published `current`
source to an archived `point_in_time` manifestation requires a local rebuild
under the present history guard. Source/cutoff changes are not assigned today's
date. Current supplementary metadata may change without creating artificial
legislative events or weakening checks on historical text, sources and warnings.

`benchmark-ids.json` fixes the identities used in each worker comparison.
Benchmark reports retain failures and distinguish completed source retrieval
from successful parsing. A failed history is never removed from the sample to
make a later run pass.

Bulk raw captures, duplicate PDF extractions and screenshots remain local and
are ignored by Git. They are supporting inspection material, not an additional
published corpus. The source manifests and selected regression fixtures identify
the evidence needed to reproduce the checks.
