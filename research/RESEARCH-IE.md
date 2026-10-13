# Ireland source research — v0.4 rebuild

Verified locally on **2026-10-08**. Country code: `ie` (ISO 3166-1 IE).
This replaces the 2026-04-13 conclusions where live evidence contradicts them.
The format-coverage work contributed by **JavierLop98 in [PR #92](https://github.com/legalize-dev/legalize-pipeline/pull/92)**
(commit `9fe61794798b2c1c7049d451cdfb55b8725158f4`) is preserved in Git history.
Its request for a measured coverage gate is retained; its inferred format counts
and assertion that Revised Acts has no archive are corrected below.

## 0.1 Sources, access and publication conditions

| Source | Role and access | Evidence |
|---|---|---|
| [electronic Irish Statute Book](https://www.irishstatutebook.ie/) (eISB), Office of the Attorney General | Enacted Acts, Constitution, instruments and Legislation Directory effects. Public HTTPS; no authentication. | `ie-v04/isb-footer.html` |
| [eISB annual Acts index](https://www.irishstatutebook.ie/eli/1922/act) | `/eli/{year}/act`, 1922–2026, includes public/private Acts and constitutional amendments. Primary coverage census, not the API count. | `ie-v04/isb-acts-catalog.json`, `ie-v04/census-summary.json` |
| [Oireachtas API](https://api.oireachtas.ie/v1/legislation?bill_status=Enacted&limit=1&lang=en) | Supplementary bill/Act metadata, pagination and `last_updated`. API `billCount` is **4,068**, not proof that the full eISB corpus or any format has that coverage. | `ie-v04/oireachtas-sample.json` |
| [Revised Acts chronological index](https://revisedacts.lawreform.ie/revacts/chron), Law Reform Commission (LRC) | Current HTML/PDF and **historical PDFs**. Archive links are already present in hidden `tr[data-eli]` rows; no browser automation or guessed URL is needed. | `ie-v04/revised-chron.html`, `ie-v04/revised-versions.json` |
| [LRC description of Revised Acts](https://www.lawreform.ie/revised-acts/) | Explains administrative consolidation and the triangular control for previous versions. | `ie-v04/lrc-history-info.html` |

### Routes and identity

- Enacted text: `https://www.irishstatutebook.ie/eli/{year}/{act|prv|ca}/{number}/enacted/{en|ga}/{xml|html|print}`.
- The annual index uses legacy HTML `en/act/{pub|prv|cam}/{padded-number}/index.html` links. Map `pub → act`, `cam → ca`; preserve `prv` as a separate namespace.
- Existing public identifiers remain `IE-{year}-act-{number}`, `IE-{year}-act-P{number}`, and `IE-{year}-act-C{number}`. The type prefix prevents public/private/constitutional collisions. Do not select API metadata by number alone.
- Constitution: `https://www.irishstatutebook.ie/eli/cons/en/html` (current bilingual source, not enacted 1937 text).
- Revised current body: `https://revisedacts.lawreform.ie/eli/{year}/act/{number}/revised/en/html`; the index's `/front/revised/en/html` is its navigation landing page.
- Archives: exact source links under `https://rev-acts.s3.eu-west-1.amazonaws.com/.../act[_new][_plain].pdf?versionId=...`. Keep the **entire query string**, including `versionId=null`; do not derive archive URLs or replace the version ID.
- eISB effects: `/isbc/{year}_{number}.html`; constitutional and private Acts have separate directory routes. The source's commencement column is not an enactment/publication date.

### Reuse and licensing

The eISB [open-data page](https://www.irishstatutebook.ie/open-data.html) explicitly
applies the Oireachtas Open Data PSI Licence, incorporating **CC BY 4.0**, to data
on that website. This is direct eISB permission, not an inference from API ownership.
Preserve source attribution. It also says XML is provided for Acts from 1922 onward.
Actual 1922/1, 1960/45 and private 2023/1 XML were downloaded and parsed successfully;
the previous blanket claim that pre-1995 Acts lack XML is false.

**LRC reuse terms confirmed on 2026-10-08.** The project owner supplied the LRC's
written reply on 2026-10-13. It confirms that Revised Acts are available under
CC BY 4.0 through the Oireachtas Open Data PSI Licence and says a matching website
notice will be added. This is direct source confirmation, superseding the earlier
unresolved classification assessment; it is not inferred from the eISB licence.
The public notice was not visible on the Revised Acts introduction page when
rechecked on 2026-10-13. The private correspondence is retained by the owner.

Credit the source bodies, link the [licence](https://www.oireachtas.ie/en/open-data/license/),
retain copyright and warranty notices, identify the Markdown transformation and
state that this is neither official text nor an official restatement. The scope
remains plain legislative text and its linked historical versions, excluding LRC
editorial annotations, commentary and logos. See the updated
[reuse assessment](ie-v04/reuse-assessment.md).

`irishstatutebook.ie/robots.txt` returned 404; LRC robots returned
`User-agent: *` and an empty `Disallow`. No published request-rate limit was found.
Research used two workers sharing a two-requests-per-second limiter for the annual
index census, with retries. A 404 robots response is not a claim of unrestricted
capacity. One alphabetical-index request disconnected; all **210 annual index
requests** (105 Act and 105 SI pages) completed without unresolved errors.
Raw-response hashes, final URLs and timestamps are in `ie-v04/http-manifest.json`;
annual-page hashes are in the local census evidence.

## 0.2 Representative fixtures and evidence

Existing fixtures remain useful; names below are actual files, not planned files.

| File under `tests/fixtures/ie/` | Coverage |
|---|---|
| `sample-v04-isb-1922-act-1.xml` | Old public Act, Irish Free State constitution schedule, accented characters, tables; not today's Constitution |
| `sample-v04-isb-private-2023-act-1.xml` | Private Act, separate identity, charter amendment quotations |
| `sample-policing-2024.xml` | Large modern Act, 302 sections, chapter/part hierarchy, tables and Irish diacritics |
| `sample-finance-2024.xml` | 12 tables, 35 footnotes, 70 superscripts, currency and mathematical characters |
| `sample-environment-2015.xml` and `sample-environment-2015-print.html` | Same enacted law across XML/HTML for fidelity comparison |
| `sample-criminal-justice-1960.html` | Older HTML presentation and layout tables |
| `sample-constitution.html` | Current bilingual Constitution, article hierarchy and amendment/editorial material |
| `version-spike.txt` | Authentic dated archive extraction, identity/date pitfalls and gate conclusion |

Local research evidence additionally contains all seven indexed Adoptive Leave Act
1995 snapshots, three Digital Services Act 2024 snapshots, raw source HTML and
plain-text PDF extractions. PDFs are **textual XEP output, not scanned images**;
the inspected files have no encryption and are not tagged PDFs. Layout still has
to be recovered: selectable text is not sufficient evidence of faithful tables.
The old research named a Taxes Consolidation fixture which is absent; it must not
be counted among validated fixtures.

## 0.3 Observed metadata inventory

Preserve original values or structured records; do not truncate arrays or overwrite
source facts with title-casing, guessed legal status, machine dates or inferred
publication dates. The API's `act` object and its surrounding `bill` record are
different entities: bill versions and bill events are not consolidated Act versions.

| Source field/group | Type | Mapping / treatment |
|---|---|---|
| XML `metadata/title`, `number`, `year`, `dateofenactment` | strings, YYYYMMDD date | `title`, `extra.official_number`, `extra.year`, `publication_date` + `extra.enactment_date`; validate identity and retain immutable year |
| Other XML metadata children | source strings | Preserve as `extra` with snake_case keys; never invent missing values |
| API `act.actNo`, `actYear`, `dateSigned` | strings, ISO date | Validate requested year/type/number; retain full API record and `extra.parliament_date_signed`. Canonical date comes from enacted eISB source because the API's 1922/1 date differs |
| API `act.shortTitleEn`, `shortTitleGa`, `longTitleEn`, `longTitleGa` | strings, long titles can contain HTML | `extra.parliament_title_en/ga`, `extra.parliament_long_title_en/ga`; English long title also supplies `summary`. Preserve source labels without asserting their language is correct: API labels are reversed for 1922/1 |
| API version `docType`, `lang`, `formats.pdf.uri` | strings/URL | Set `pdf_url` only from an English `docType=act` manifestation; retain bill drafts in parliamentary metadata without representing them as enacted PDFs |
| API `act.statutebookURI`, `act.uri` | URLs | Canonical typed eISB `source`, `extra.oireachtas_uri`; original fields retained in `extra.parliament_metadata` |
| API bill `billNo`, `billYear`, `billType`, `billTypeURI`, `uri` | strings/URLs | `extra.parliament_metadata` preserves bill identity separately from Act identity |
| API bill `shortTitleEn/Ga`, `longTitleEn/Ga` | strings | Preserve in `extra.parliament_metadata`; do not replace the enacted title |
| API bill `status`, `statusURI`, `lastUpdated` | array/URL/timestamp | Preserve in `extra.parliament_metadata`; neither parliamentary status nor freshness proves current legal force |
| API bill `method`, `methodURI`, `originHouse`, `originHouseURI`, `source`, `sourceURI` | strings/URLs | Preserve in `extra.parliament_metadata` |
| API bill `sponsors`, `stages`, `mostRecentStage`, `events`, `debates`, `amendmentLists` | structured objects/arrays | Preserve untruncated in `extra.parliament_metadata`; never interpret as statute consolidations |
| API bill `versions`, `relatedDocs` and unknown fields | structured arrays/objects | Full bill record serialized in `extra.parliament_metadata`, sorted JSON keys with original Unicode; no truncation or unknown-field loss |
| eISB index year/type/number/title/language and HTML/PDF links | strings/URLs | Discovery identity and manifestations; bilingual rows are one norm |
| eISB effects affected provision, affecting type/number/provision, effect, commencement | table cells and links | `note`, `provision`, `source_id`, `commencement`, `commencement_source`, `effective_date`, `pending`, `whole_repeal`, `partial_repeal`; attach genuine affecting-norm `publication_date` and source/directory URLs separately |
| eISB undated editorial classification with no affecting provision | text, directory URL | `extra.legislation_directory_notes` JSON preserves a recognized `Spent.` note and its source; it supplies no reform identity, date or historical status transition |
| Verified eISB directory corrections | complete corrected effect records | `extra.legislation_directory_corrections` JSON retains only records carrying `source_correction`, including original citation/commencement fields, corrected identity/dates and evidence/directory URLs; survives structured storage and corpus frontmatter |
| SI stated gazette publication notice and made/signature date | dates/text | Prefer stated *Iris Oifigiúil* publication date; preserve `made_date` separately and `publication_date_basis` (`gazette_notice` or `final_signature`). A made-date fallback is the stated instrument date, not proof of a gazette publication date |
| LRC index `data-eli`, title, updated date, annotated/plain links and archive query | strings/URLs/date | Stable norm link, snapshot cutoff, provenance and explicit format per version |
| LRC cover `Updated to`, enactments/instruments considered, disclaimer | date/text | Snapshot date and preparation scope; no inferred publication date |
| Verified omission in an exact LRC source PDF | source hash, missing section, warning | `Version.source_warning`, persisted with the version and rendered as `source_warning` frontmatter plus an incomplete-source notice only when that snapshot is selected; see the Companies 2020 exception below |
| LRC F/C/E annotation IDs, text and links | structured content | Textual/non-textual/editorial annotations; do not confuse these classes |
| Constitution article numbering, current text, amendment table and stated dates | HTML/text | Constitution content and explicit current-text provenance |
| Source graphic/image nodes, with source URL | counted nodes | `extra.images_dropped` and JSON `extra.images_dropped_by_source`; aggregate inspected enacted/current representations, omit decorative images, and put `[image omitted]` at a content-bearing figure. This records a binary-content limitation, not image reproduction |
| Source formulas and mathematical symbols | plaintext or structured source | Preserve the actual expression; `extra.has_formulas=true` when present. Do not invent LaTeX for source plaintext |
| PDF creation/modification metadata | timestamps | Technical diagnostics only, never legal dates |

The captured API sample's observed key tree can be regenerated from
`ie-v04/oireachtas-sample.json`; this sample alone is not a claim that no other
nullable API fields exist. Preserve unknown source metadata in `extra` where needed.
The implementation now preserves the complete bill object in `extra.parliament_metadata`,
including its original Act object. Enacted eISB XML/HTML supplies authoritative title,
publication/enactment date, rank and canonical source, with a metadata envelope retaining
both original source records. The eISB date basis is recorded as `isb_enactment_date`;
the parliamentary date remains labelled separately, rather than overriding a conflicting
primary source. Reconciliation was required by the full-pipeline 1922/1 sample.
Source correction evidence and the effects-fixture manifest are documented in
[`ie-v04/effects-source-corrections.md`](ie-v04/effects-source-corrections.md).
This mapping does not establish a redistribution licence: the eISB and LRC source
licensing evidence in section 0.1 establishes the separate source terms.

## 0.4 Formatting inventory

- **Tables:** real data tables and nested layout tables; rowspan/colspan, headings
  and cells containing paragraphs. Do not flatten legislative tables into prose.
- **Hierarchy:** parts, chapters, sections, schedules, schedule parts and source
  numbering. Repeated numbers inside quoted amendments are not new top-level sections.
- **Bold/italic/small caps:** XML `b`, `i`, `font` attributes and corresponding HTML;
  small-cap extraction in historical PDFs can split a word visually.
- **Lists and quotations:** nested paragraph labels, `bull`, `odq/cdq/osq/csq` and
  indented quoted amending text. Preserve punctuation and the original wording.
- **Footnotes:** XML `fn/marker/su`; footnote definitions must not duplicate inline
  bodies or become new legislative sections. Superscripts also occur outside footnotes.
- **Cross-references:** `xref` and HTML links, including internal section links,
  other Acts and statutory instruments. Resolve relative URLs against the source.
- **Characters:** `afada/ifada/...` and uppercase variants, `emdash`, `euro`, `pound`,
  `unicode`, `su`, `sb`. Finance fixtures demonstrate mathematical symbols; do not
  claim formulas are absent merely because MathML was not found.
- **Images:** the 1922 Constitution Act contains a content-bearing annex graphic
  (`en.act.1922.0001.sched1.1.jpg`) as well as a harp. The implemented Step 1.7
  policy omits binary images, records per-source/aggregate counts and puts
  `[image omitted]` at that annex graphic. Decorative harp/seal images receive no
  inline marker. The sample passes with this explicit limitation; it does not
  preserve the graphic's visual meaning or prove all corpus images decorative.
- **Schedules, signatories and instruments:** cover-to-cover fidelity includes
  schedules and genuine signature/date content; keep parliamentary navigation out.
- **PDF layout:** running page/part/section headers, page numbers, line-break
  hyphenation, margin headings, contents pages, introductory pages and annotation
  markers. `pdftotext -layout` on modern Digital Services PDF demonstrably joins
  some words; its raw output is not publication-ready Markdown.

## 0.5 Historical-version spike — PASS (access and distinct text)

The previous **FAIL / no archive** conclusion is disproved. See
`../tests/fixtures/ie/version-spike.txt` for every URL, SHA-256, extracted word
count and page count of **all seven indexed snapshots** of the Adoptive Leave Act
1995 (`IE-1995-act-2`).

| Source cover cutoff | Pages | Extracted words (including editorial pages) |
|---|---:|---:|
| 2016-08-01 | 29 | 11,988 |
| 2019-05-28 | 29 | 11,988 |
| 2019-10-24 | 29 | 12,008 |
| 2020-10-14 | 30 | 12,034 |
| 2021-04-01 | 28 | 12,220 |
| 2023-07-03 | 28 | 12,296 |

A substantive change is visible in section 2: the 2020 snapshot defines an adopting
parent using employed adopting mother, adopting father or sole male adopter; the 2021 snapshot uses qualifying
adopter/surviving parent. Evidence: `ie-v04/adoptive-leave-2020-2021.diff`.
No reverse application of amendments, invented historical text or OCR was used.

**Index anomaly:** a seventh row dated 2019-11-01 links to the same S3 object as
2019-10-24. Both have the same bytes and a 24 October cover. The seven rows are
**six distinct source objects**, not seven substantiated dated texts. Across all
Acts the 1,972 historical rows contain only **1,925 distinct plain-PDF URLs**;
full-content hashing can find additional duplicates. Never create an extra reform
solely from an index label or changed cover. Digital Services 2024's first two
snapshots are a concrete example of an editorial-only difference.

### Text state and dates

- Enacted eISB Act bodies remain **`as_enacted`**, including when their metadata
  history records amendments. A source enactment date does not establish that every
  provision was then in force.
- Immutable archived LRC consolidated texts are dated **`point_in_time` snapshots**
  at the verified source cutoff. LRC's annotations may also describe prospective
  effects: preserve their qualifications.
- The mutable current LRC HTML URL is **`current`** unless the exact body is tied
  to a verified immutable dated source. Never replay today's body at every date.
- The current Constitution is **`current`** until authentic historical full texts
  have been obtained; do not label the present Constitution as enacted in 1937.

`Updated to` is not a consolidation publication date. The PDFs' creation timestamps
also are not legal dates. One Digital Services snapshot dated 2 September 2024
states that Acts enacted in October were considered in preparation. Where the
source supplies no publication date for the change, omit `Source-Date` and use the
norm's publication date for the Git author date under SPEC v0.4; do not substitute
an index date. Resolve and retain actual affecting instruments when available.
Per-version provenance must allow enacted and consolidated semantics to coexist
without applying the latest metadata or text-state retroactively.

### Historical update boundary

Incremental publication requires the existing history to remain a verified prefix.
A newly discovered older event, a changed historical source/body/status/date or a
replacement of a published `current` HTML manifestation with an archived
`point_in_time` PDF requires a **local corpus rebuild** under the current guard.
The last case can occur even when the legislative words match: the source URL and
text-state assertion have changed. Do not append a backfill at today's date or
invent a repair event to bypass this boundary.

Current parliamentary supplements and whole-history inspection counters are
compared separately from version-specific facts. Updating those observations can
accompany a genuine new event without rewriting earlier commits; an API timestamp
alone does not create a legislative event. Historical titles, sources, statuses,
publication/cutoff dates, source warnings, text and commit messages remain protected.

## 0.6 Measured scope and cost

**Scope of this rebuild:** Acts of the Oireachtas since 6 December 1922 (public,
private and constitutional amendments), plus the current Constitution. Full
history includes the authentic LRC snapshots for these Acts where access, a legal
basis for redistribution and fidelity permit. Keep independent amending Acts as
files and use genuine eISB effects to record enacted-text amendment history.

The full annual source census found **4,114 unique Act identities**: 4,009 public,
73 private and 32 constitutional amendment Acts. There are 4,171 rendered index
rows because languages are repeated. Every identity has an indexed English HTML
route. The API's 4,068 bill/Act count is **46 fewer**, so API-only discovery cannot
establish completeness. All 105 annual Act indexes were fetched; the counts are
indexed manifestations, not successful downloads of every full text. Full bootstrap
must reconcile every discovered identity and every unresolved fetch.

The separate SI census contains **42,032 rows**, not the old guessed 35,000 laws.
Some repeat languages and at least four rows contain conflicting HTML/PDF identity
links; it would be dishonest to call that a validated distinct-law count. SIs and
pre-1922 legislation are **excluded legal classes**, not omitted file formats.
The source's pre-1922 landing page itself describes selective surviving historic
legislation; its full universe has not been counted. LRC also indexes 18 revised
SIs (35 rows) and eight `bps` norms (15 rows), all outside this Acts rebuild.
Do not advertise this scope as all Irish law or claim the SI format gate passed.
Necessary amending SIs are fetched as dependency files so their real identities,
dates and source texts support Act history. S.I. 356/2024 passes the representative
HTML sample gate; that is not a bulk SI-class coverage claim.

A conservative full run starts with 105 Act indexes, around 4,114 enacted-text
requests, up to 4,114 metadata/effects lookups, one LRC index and up to 2,548 LRC
snapshot requests before URL/body deduplication. Enacted XML failures add HTML
fallback requests. At two requests/second the network-request floor alone is
roughly 1.5–2.5 hours; large-law download, PDF extraction, retries and Git history
increase elapsed time. This is a planning estimate, not a measured bootstrap
benchmark. Measured sample PDFs range around 1–1.5 MB; do not extrapolate these two
laws into a precise full-corpus size. Daily updates must observe changes to existing
Acts and the LRC index as well as new API bills.

## 0.7 Format-coverage measurement and implementation gate

The Act denominator is the **4,114 unique eISB identities** above. LRC snapshot
rows are a separate version denominator; rows are not necessarily unique texts.

| Format/source | Acts with indexed manifestation | Indexed snapshot rows | Exclusivity / confidence |
|---|---:|---:|---|
| eISB enacted HTML | 4,114 | 4,114 enacted identities | Every Act has an HTML route; bulk download/fidelity still to validate |
| eISB enacted XML | Not exhaustively fetched | Not exhaustively fetched | Source promises Acts from 1922; genuine 1922, 1960, private 2023 and modern fixtures verified. Do not substitute API count for a format census |
| eISB enacted PDF | 1,338 | 1,338 enacted identities | Zero **indexed** PDF-only Acts after deduplicating languages; HTML covers these identities |
| Constitution HTML | 1 additional norm | 1 current text | Unique norm outside Act denominator; included despite <1% |
| LRC current HTML and PDF | 576 | 576 | Consolidated versions of Acts, not 576 new Act identities |
| LRC archived PDF | 444 Acts with history | 1,972 | **77.39% of LRC's 2,548 Act rows**; no archived HTML link in index; 1,925 distinct plain-PDF URLs |

**Gate conclusion:** the inventory establishes that XML+HTML alone is inadequate
for the requested history. Historical PDF is **required**, not a justified skip.
There is no OCR-cost exception: the inspected archival PDFs have extractable text.
This completes the source inventory and format-support design needed to start
implementation. The later implementation has now passed the representative sample
and historical cross-format checks below; **full-corpus format coverage remains
subject to download reconciliation and health checks**.

Required implementation/validation before publication:

1. Discover from annual eISB indexes and reconcile supplementary API metadata;
   retain all three Act namespaces and include the current Constitution explicitly.
2. Use an explicit format for every envelope version: enacted XML/HTML, revised
   HTML and archived PDF must yield the same block/version/paragraph model.
3. Download every relevant LRC version using the index's exact URL. Deduplicate
   identical source objects, validate cutoff dates against the body and reject or
   report inconsistent dates instead of inventing history.
4. Preserve paragraph/section numbering, tables, notes and inline structure in the
   PDF path. Compare against the same dated HTML/PDF where possible, then inspect
   adjacent historical PDF → current HTML versions. Mere text similarity is not
   proof of completeness or correct legal structure.
5. Record the real cross-format Markdown diff and source spot-check result here
   after implementation. The earlier `>95%` claim is not an accepted fidelity gate:
   five percent may contain entire operative provisions. The raw extraction diff
   in `ie-v04/adoptive-leave-2020-2021.diff` is **research evidence, not that check**.
6. Establish the applicable legal basis for LRC redistribution, then pass Step 7's
   independent five-law quality review and the full-corpus reconciliation/health
   gates locally.

The LRC count deduplicates language manifestations: `2003/act/32/ga` is the
Irish-language version of an already counted Act. The English corpus has 576
Act identities and 2,548 indexed rows; the whole LRC index has 602 identities
across 603 language-specific ELI keys. Raw source captures remain unchanged.

### Implemented cross-format fidelity check — 2026-10-08

The independent [Step 7 review](ie-v04/quality-review.md) reports **5/5 laws fully
PASS** on full-pipeline sample-4, plus the Adoptive Leave Act 1995 historical
PDF-to-HTML sample. Its [evidence JSON](ie-v04/sample-4-review-evidence.json)
records final file hashes, text-presence checks, metadata preservation, CommonMark
structure and hygiene. This supersedes the failed sample-2 format review, not the
separate licensing or full-corpus gates.

For the same authentic 2023-07-03 cutoff, Adoptive Leave PDF and HTML yield 420
normalized blocks and **11,198 ordered word tokens each with no word difference**.
The [actual Markdown diff](ie-v04/adoptive-same-cutoff-pdf-html.diff) was inspected,
including residual non-word differences: link coverage/destinations from each
source, ellipsis glyphs, one space after a section dash and bold closing brackets.
Six parts and 50 section headings retain their sequence; lists, quotations and
inline emphasis remain structural Markdown. These checks do not rely on a
percentage threshold or treat word equality alone as proof of fidelity.

The [adjacent historical diff](ie-v04/adoptive-history-pdf-html.diff) compares
authentic 2021-04-01 PDF with 2023-07-03 HTML and retains substantive changes,
including surviving-parent wording and gender-neutral pronouns. Full-pipeline Git
commits at 2020-10-14, 2021-04-01 and 2023-07-03 reproduce their source-render
bodies exactly. Archived snapshots remain point-in-time and the mutable HTML
remains current. The 2020-to-2021 source-page definition check from the initial
spike independently establishes genuine historical text change.

Adoptive Leave has no operative tables; Valuation and Digital Services source
fixtures/tests separately exercise PDF tables and footnotes. Cross-format source
differences and their measured explanations are retained in
`../tests/fixtures/ie/archive-comparison.json`. Binary images remain an explicit
Step 1.7 limitation. No full-corpus completeness, production bootstrap or
redistribution permission is certified by these sample results.

### Explicit source-fidelity exception: Companies Act 2014, 2020 snapshots

Four official plain-PDF objects downloaded in full omit **section 1384A from the
legislative body**, although their contents list it. The annotated PDFs linked
from the same catalogue rows have the same omission; no complete same-cutoff
alternative was found. This is a defect in the source consolidation, not an
uncommenced provision: [section 83 of the Companies (Accounting) Act 2017](https://www.irishstatutebook.ie/eli/2017/act/9/section/83/enacted/en/html)
inserted it, and [S.I. 246/2017](https://www.irishstatutebook.ie/eli/2017/si/246/made/en/html),
as amended by [S.I. 250/2017](https://www.irishstatutebook.ie/eli/2017/si/250/made/en/html),
commenced it on **9 June 2017**. The latter order excludes section 80 of the
amending Act, not section 83.

The adopted representation policy retains these sources with an explicit warning
on each affected version and **does not reconstruct the missing text**. The
[source-gap manifest](../tests/fixtures/ie/archive-companies-2020-source-gaps.json)
records exact URLs, SHA-256 identities, cover dates, alternative-source checks and
primary commencement evidence:

| Catalogue label(s) | Declared cover cutoff | Plain-PDF SHA-256 |
|---|---|---|
| 2020-01-01; 2020-01-21 | 2020-01-01 | `d487045605971cca95feddf6dbd824188edd95e9f1e0f1d62c191cdd083e777d` |
| 2020-03-30 | 2020-01-01 | `c056a097cf75e05af4f180de51d3be8623292dc0e9deff789430116d8c5a21bd` |
| 2020-08-21 | 2020-08-21 | `1e6a866df584baa5f2048e81344e8944d01d4f4aed47ea6430403b9309d2bcdc` |
| 2020-12-31 | 2020-12-31 | `a02cbaf5440607a30604171a50a483e4b8a8db5a7f742ad7e10fdde34e937947` |

These are **four objects but three declared cutoffs**. The two January catalogue
rows reference the same object. The March object contains the same words and
punctuation as the January object after removing running headers/page footers and
normalizing whitespace; it corrects the paragraph separation of **section 1181(4)**
and a page break at section 1184(3). Both covers retain 1 January 2020. Their common
normalized-text SHA-256 and the corrected-layout object's identity are recorded
under `presentation_equivalence` in the manifest. The March catalogue label and
PDF creation timestamp do not establish a new legal cutoff.

The exception is restricted to those **complete-file hashes and exactly the
missing-section set `{1384A}`**. Changed bytes, another missing section or an
excerpt do not qualify. The fixture
[`archive-companies-2020-incomplete-excerpt.pdf`](../tests/fixtures/ie/archive-companies-2020-incomplete-excerpt.pdf)
preserves the contents entry and the body transition from 1384 to 1385 for review;
it is deliberately partial and is never accepted as a complete snapshot.

The warning is stored on `Version.source_warning`, survives structured storage,
and appears both in frontmatter and beside the selected snapshot's rendered text.
It states that the official source is incomplete and that the missing text was
not reconstructed. It follows that source when an intervening history event still
uses its body; it is not applied to an unaffected enacted or later complete
version. Retention with this warning is an explicit fidelity limitation, not a
claim that the 2020 consolidated legislation is complete or a relaxation for
other source omissions. The redistribution and full-corpus gates remain separate.
