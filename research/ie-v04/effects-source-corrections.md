# eISB amendment-directory validation and source corrections

Research and captures: 2026-10-08. The source directory is the Office of the
Attorney General's [Legislation Directory](https://www.irishstatutebook.ie/isbc/).
Exact downloaded fixture URLs, capture treatment and SHA-256 hashes are in
[`../../tests/fixtures/ie/effects-sources.json`](../../tests/fixtures/ie/effects-sources.json).

## Parsing and date semantics

Public Acts use their own two-column or four-column effects table. Private Acts
share an annual table, grouped by the official `a{number}_{year}` anchor and
rowspan. Statutory instruments can require an annual index followed by its
number-range page. The parser follows the actual source document's Legislation
Directory link; private and constitutional Acts must not be guessed into public
Act routes. A missing/404 directory or an unknown operative citation is an error,
not evidence that a norm has no amendments. Explicit `Not affected` returns no
relations. Inspected constitutional amendment Act pages have no separate effects
directory; that source limitation is logged, not represented as proved absence
of amendments. The Constitution's current page supplies its own amendment table.

Effects retain the original note, affecting provision, commencement cells and
affecting norm identity. Continuation rows retain the preceding affected provision.
Whole-Act repeal is distinguished from a repeal of one provision and from effects
explicitly marked not yet commenced. Publication/signature dates come from the
affecting Act or instrument's source metadata, never from the directory's
commencement column. The Constitution supplies 32 amendment identities and actual
signature dates directly: for example `IE-1972-act-C4` was signed **1973-01-05**.

For S.I. 356/2024, the source expressly states notice publication in *Iris Oifigiúil*
on **2024-08-02**, while it was made and took effect on **2024-07-31**. These dates
must remain distinct. When no gazette publication notice is stated, the source's
made/signature date is an official instrument date; using it as the corpus source
date must retain that basis and must not assert an unknown gazette date.

The 1922 Constitution Act's whole repeal is effective **1937-12-29**, not the
Constitution's adoption date **1937-07-01**. The directory explicitly cites
[Constitution Article 48](https://www.irishstatutebook.ie/eli/cons/en/html#article48),
which ties repeal to the Constitution's coming into operation. The same official
page expressly states the 29 December operation date in its preface. The fetcher
verifies both source statements and retains them as commencement provenance; it
does not calculate a date or generally apply one instrument's commencement date
to every effect. Missing statements cause an error instead of an adoption-date
fallback. `sample-effects-constitution-1922.html` preserves the original repeal row.

## Narrow corrections backed by operative primary text

Corrections match the affected norm and exact defective row. The original
`provision` remains unchanged, including blanks; `source_correction` records the
primary verification URL. No generic inference from neighbouring rows or dates is
used. If source wording changes, an unresolved operative citation fails visibly.

| Affected norm and defective row | Verified affecting source | Primary verification |
|---|---|---|
| Taxes Consolidation Act 1997, section 270(4) inserted; citation `2006, ss. 26(1)(a), 26(2)` lacks the Act number | Finance Act 2006, No. 6 | [Section 26](https://www.irishstatutebook.ie/eli/2006/act/6/section/26/enacted/en/html) explicitly inserts subsections beginning at 270(4); subsection (2) gives its application rule |
| Same Act, Schedule 13 paragraphs 92, 111, 128 and 180 deleted; each affecting citation is blank | Finance Act 2024, No. 43 | [Section 22(a)](https://www.irishstatutebook.ie/eli/2024/act/43/section/22/enacted/en/html) explicitly deletes those paragraphs, together with paragraph 40, whose directory row already has its citation |
| Same Act, Schedule 15 Part 1 paragraph 45 inserted; affecting cell incorrectly repeats the affected-cell text | Finance Act 2018, No. 30 | [Section 60(1)(f)(i)](https://www.irishstatutebook.ie/eli/2018/act/30/section/60/enacted/en/html) inserts paragraph 45; section 60(2)(a) states its retrospective effect. Publication remains the Act's actual signature date |
| Dundalk Urban District Council Act 1925, No. P3, section 110; certain references to sanitary authority construed as Irish Water; affecting citation blank | Water Services (No. 2) Act 2013, No. 50 | [Section 7(4)](https://www.irishstatutebook.ie/eli/2013/act/50/section/7/enacted/en/html) applies the construction to enactments concerning transferred water-services functions; the original directory's qualified wording is retained |

The relevant primary sections were downloaded as `effects-finance-2006-6-section26.html`,
`effects-finance-2024-43-section22.html`, `effects-finance-2018-30-section60.html` and
`effects-water-services-2013-50-section7.html` in this research directory.

Some source hyperlinks incorrectly use `/act/pub/` even though the visible citation
explicitly identifies an S.I. The parser preserves the explicit instrument class
and number/year. Verified examples include S.I. 451/2020 (Royal College of Surgeons
in Ireland constitution alteration) and S.I. 83/1991 (functions concerning Dundalk).
This is a citation-class correction, not a new legal identity inferred from title.

## Measured replay and remaining source limitations

The captured public tables replay as follows; counts are effect relations, not
distinct reforms or laws:

| Norm | Relations | Distinct affecting norms | Pending relations |
|---|---:|---:|---:|
| Constitution of the Irish Free State Act 1922, No. 1 | 82 | 27 | 0 |
| Taxes Consolidation Act 1997, No. 39 | 11,384 | 377 | 0 |
| Environment (Miscellaneous Provisions) Act 2015, No. 29 | 7 | 3 | 5 |
| Local Government (Mayor of Limerick) and Miscellaneous Provisions Act 2024, No. 7 | 7 | 3 | 0 |

All 75 entries across 43 captured private-directory annual pages parse without
unresolved rows, yielding 51 relations. This is **not** a new Act census: two
directory entries are misclassified (`P399/1953` points at S.I. 399/1953 and
`P44/1959` appears to duplicate public Act 44). Discovery continues to use the
73 private Acts actually present in the Act indexes.

The 2024 S.I. directory's anchor 356 and source link point to instrument 356, but
its displayed title is incorrectly about a local-government audit committee.
The official instrument itself is the paints/varnishes regulation. The parser
uses the matching anchor/link identity and records the source's `Not affected`
statement; it never imports that directory title as instrument metadata.

The five pending effects on Environment Act 2015 are partial repeals in Air
Pollution (Amendment) Act 2026, No. 14; they do not justify marking the whole 2015
Act repealed. The source explicitly says commencement orders are required.

This replay verifies these captured tables and dates. It does not certify the
unfetched full public-Act effects corpus or establish the legal status of every
old two-column-table effect. Full bootstrap must surface unresolved source rows,
missing source dates and unavailable source pages in its reconciliation.

## Refresh implementation

`refresh_sources()` starts one mutable-source refresh scope across successive
`ISBClient` instances and worker threads. Cached responses older than the scope
are replaced once per URL; per-URL locks avoid duplicate concurrent downloads.
Version-specific LRC S3 objects with an explicit `versionId` use a long-lived cache
because the version identifier denotes the immutable source object. Current PDFs,
HTML, annual indexes, metadata and effects remain mutable. Exceptions restore the
previous refresh scope; nested contexts retain the outer run's cutoff.

## Undated directory classifications — 1929/10 benchmark finding

The live [Constitution (Amendment No. 16) Act 1929 directory](https://www.irishstatutebook.ie/isbc/1929_10.html)
has two separate rows: a repeal citing Act 20/2016, sections 1 and 2 and its
schedule; and `Spent.` with an empty affecting-provision cell. The latter supplies
neither an enactment identity nor a date. The actual
[Statute Law Revision Act 2016](https://www.irishstatutebook.ie/eli/2016/act/20/enacted/en/print.html)
independently lists 1929 No. 10 in its repeal schedule and makes that schedule
operative through section 1. There is therefore a real repeal relation to retain,
alongside an undated editorial classification which must not become a fabricated
second reform or historical status transition.

`parse_effects` separates the exact `Spent`/`Spent.` classification only when its
affecting-provision and commencement cells are empty. An optional editorial-note
collector retains its wording. `fetch_effects` attaches the actual directory URL;
the source envelope preserves the note and the parsed metadata exposes it as
`extra.legislation_directory_notes` (JSON). No source identifier, publication date,
effective date or status is invented for it. Other missing or unresolved affecting
provisions continue to fail. A `Spent` row with an actual affecting citation still
passes through the normal relationship parser.

The same local benchmark exposed the spelling `Not Affected` in 1935/39, 1946/38
and 1949/29. The explicit no-effects classification is now case-insensitive, with
an optional trailing period; this does not relax unidentified legislative effects.
The complete 1929 response is retained as `sample-effects-spent-1929.html`, with
URL, retrieval date and SHA-256 in `tests/fixtures/ie/effects-sources.json`.
The 2016 primary repeal text is saved locally in this research directory as
`effects-spent-repeal-2016_20.html`.

## Inserted Pensions Act provision misdated as 1990 — Appropriation Act 2002

The [2002/28 directory](https://www.irishstatutebook.ie/isbc/2002_28.html) attributes
construction of references to the Pensions Board to Pensions Act 1990, section 9A,
and gives that Act's 21 December 1990 commencement. Its continuation row cites
2013 No. 20, section 26, with 7 March 2014 commencement. Treating the first row as
a 1990 amendment to a 2002 Act would create an impossible pre-enactment reform.

The primary [2013 Act, section 26](https://www.irishstatutebook.ie/eli/2013/act/20/section/26/enacted/en/html)
actually inserts section 9A into the Pensions Act and expressly ties construction
of references in other enactments to section 26's commencement.
[S.I. 103/2014, article 2](https://www.irishstatutebook.ie/eli/2014/si/103/made/en/html)
appoints 7 March 2014 for section 26 and the other listed provisions. Both primary
responses are retained as `effects-pensions-2013-26.html` and
`effects-pensions-2014-si-103.html`.

The correction is restricted to the observed norm, exact note and exact section
9A citation. Both directory rows remain recorded, with 2013 No. 20 as the actual
affecting enactment and 2014-03-07 as commencement. The original citation,
`directory_source_id`, `directory_commencement` and
`directory_commencement_source` remain intact; `source_correction` and the actual
commencement URL identify the primary evidence. Publication is still resolved
from the actual 2013 Act metadata, never substituted from commencement. The
general check rejecting a reform that predates the original norm remains unchanged.
Fixture: `sample-effects-appropriation-2002.html`, recorded in the source manifest.

All effects carrying `source_correction`, including the earlier verified citation
repairs, are preserved losslessly in `extra.legislation_directory_corrections` as
JSON. This ensures original and corrected values, primary evidence and directory
URLs reach the structured corpus and Markdown frontmatter rather than remaining
only in the downloaded envelope. A roundtrip regression uses the authentic
2002/28 XML and directory fixtures to verify parse → structured save/load → final
Markdown, while confirming the correction does not create an additional reform.
The affecting Act's 2013-06-28 enactment date was separately checked against its
official XML, saved as `effects-pensions-2013_20.xml`.
