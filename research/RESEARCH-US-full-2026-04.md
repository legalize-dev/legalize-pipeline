# RESEARCH-US.md — United States Federal Law

Research document for adding US federal legislation to Legalize.
Covers **federal law only** (US Code). State-level law is out of scope.

## 0.1 Source identification

### Primary source: Office of the Law Revision Counsel (OLRC)

The OLRC maintains the official **United States Code** — the codification of all
general and permanent federal statutes organized by subject matter into 54 titles.

- **Website:** https://uscode.house.gov
- **Download page:** https://uscode.house.gov/download/download.shtml
- **Prior release points:** https://uscode.house.gov/download/priorreleasepoints.htm
- **Format:** USLM XML (United States Legislative Markup), derived from Akoma Ntoso
- **Schema:** https://github.com/usgpo/uslm (v2.1.0)
- **Namespace:** `http://xml.house.gov/schemas/uslm/1.0` (US Code docs)
- **Auth:** None required
- **Rate limits:** Not documented; however, automated `curl` downloads consistently
  time out — the OLRC appears to block non-browser requests or throttle heavily.
  Browser-based downloads work. This is a **key practical issue** to solve.
- **License:** Public domain (17 U.S.C. § 105). No copyright, no restrictions.
- **Update cadence:** Continuously during Congressional sessions. New release
  points published every few weeks when the OLRC updates the online Code.

### Secondary source: GovInfo (Government Publishing Office)

GovInfo provides a REST API and bulk data repository for multiple legislative
collections. Useful for Public Laws (individual acts as enacted) and Statute
Compilations (selected consolidated statutes).

- **API:** https://api.govinfo.gov/docs/
- **Bulk data:** https://www.govinfo.gov/bulkdata/
- **Auth:** Free API key from api.data.gov (also has DEMO_KEY for testing)
- **Rate limits:** 40 req/s, 1,200 req/min, 36,000 req/h
- **robots.txt:** `/bulkdata/` and `/content/` are NOT blocked
- **License:** Public domain

**Relevant GovInfo collections:**

| Collection | Code | Format | Coverage | Use for Legalize |
|---|---|---|---|---|
| Public Laws | `PLAW` | USLM XML | 113th Congress (2013) – present | Amendment tracking (which PL modified which section) |
| Statute Compilations | `COMPS` | USLM XML | ~2,100 compilations | Supplementary: standalone statutes not in positive law titles |
| US Code | `USCODE` | PDF, HTML only | 1994 – present | **NOT usable** (no XML format) |
| Statutes at Large | `STATUTE` | USLM XML (beta) | 108th Congress (2003) – present | Historical reference |

**Bulk data URLs:**
```
# Public Laws by Congress
https://www.govinfo.gov/bulkdata/PLAW/{congress}/public/
https://www.govinfo.gov/bulkdata/PLAW/{congress}/public/PLAW-{congress}publ{number}.xml

# Statute Compilations
https://www.govinfo.gov/bulkdata/COMPS/COMPS-{id}.xml
```

### Not used: Congress.gov API

Congress.gov API (https://api.congress.gov/) provides metadata about bills and
laws but **does not include full text**. Only useful for discovery, not content.

### Not used: Federal Register / eCFR

The Federal Register publishes regulations (agency rules under the CFR), not
statutes. Out of scope for the US Code.

## 0.2 Fixtures

Saved to `engine/tests/fixtures/us/`:

| File | Content | Size | Sections | Format |
|---|---|---|---|---|
| `sample-public-law-small.xml` | Laken Riley Act (PL 119-1) | 23 KB | 3 | `<pLaw>` USLM |
| `sample-public-law-large.xml` | Reconciliation Act (PL 119-21) | 2.8 MB | 338 | `<pLaw>` USLM |
| `sample-comps-small.xml` | Contract Disputes Act of 1978 | 4.4 KB | 1 | `<statuteCompilation>` USLM |
| `sample-comps-large.xml` | Social Security Act Title XVIII | 8.8 MB | 125 | `<statuteCompilation>` USLM |
| `sample-comps-regulation.xml` | FAA Modernization and Reform Act 2012 | 1.1 MB | 229 | `<statuteCompilation>` USLM |

**Missing fixture:** US Code title XML (`<uscDoc>` root element) from the OLRC.
Could not be downloaded automatically due to OLRC blocking. The XML structure is
documented by the USLM schema and the nickvido/us-code project. A manual download
is required to complete this fixture set.

**Where to get it manually:**
1. Visit https://uscode.house.gov/download/download.shtml in a browser
2. Download any title ZIP (e.g., Title 1 — General Provisions, ~350 KB)
3. Extract the `.xml` file and save as `tests/fixtures/us/sample-uscode-title.xml`

## 0.3 Metadata inventory

### US Code metadata (from USLM `<uscDoc>` schema + COMPS analysis)

| Source field | Type | Example | Maps to | Notes |
|---|---|---|---|---|
| `dc:title` | string | "Title 18—Crimes and Criminal Procedure" | `NormMetadata.title` | Dublin Core |
| `identifier` (attr) | path | `/us/usc/t18` | Used to build `NormMetadata.identifier` | On root element |
| `property[docNumber]` | string | "18" | Part of identifier | Title number |
| `property[docPublicationName]` | string | "United States Code" | `extra.publication_name` | |
| Chapter `<num>` | string | "CHAPTER 1" | Part of identifier | Chapter number |
| Chapter `<heading>` | string | "GENERAL PROVISIONS" | `NormMetadata.title` (append to title) | |
| `sourceCredit` | string | "(Pub. L. 89-554, Sept. 6, 1966, 80 Stat. 378)" | `extra.source_credit` | Public Law source attribution |
| Section `<num>` | string | "§ 1201" | For internal structure | Section numbering |
| Section `<heading>` | string | "Kidnapping" | For internal structure | |
| — (inferred from release point) | date | "2025-01-15" | `NormMetadata.publication_date` | Date of the release point |
| — (inferred from release point) | string | "P.L. 119-73" | `extra.current_through_public_law` | Which PL this version reflects |
| — | string | "us" | `NormMetadata.country` | Always "us" for federal |
| — (from title context) | string | "title" | `NormMetadata.rank` | All US Code content is statute-level |
| — | string | "in_force" | `NormMetadata.status` | Default; detect repealed chapters |
| — | string | "United States Congress" | `NormMetadata.department` | |
| `editorialNote` | string | "[Section repealed by...]" | `extra.editorial_notes` | OLRC editorial commentary |
| `footnote` | string | "This table of contents..." | Preserved in text | |
| `ref[@href]` | url | `/us/usc/t42/s1395` | Cross-reference links in text | |

### Public Law metadata (for future amendment tracking)

| Source field | Type | Example | Maps to | Notes |
|---|---|---|---|---|
| `dc:title` | string | "Public Law 119-1: To require..." | — | Full title |
| `docNumber` | string | "119-1" | — | Congress-number format |
| `approvedDate` | date | "2025-01-29" | — | Date signed into law |
| `congress` | int | 119 | — | Congress session number |
| `citableAs` | string | "Public Law 119-1" | — | Formal citation |
| `citableAs` | string | "139 Stat. 3" | — | Statutes at Large citation |
| `shortTitle` | string | "Laken Riley Act" | — | Popular name |
| `amendingAction` | elem | `<amendingAction type="amend">` | — | What the PL changes |
| `ref[@href]` | path | `/us/usc/t8/s1226/c` | — | Which USC section is modified |
| `legislativeHistory` | elem | Congressional Record dates | — | Floor action dates |

### Statute Compilation metadata (COMPS)

| Source field | Type | Example | Maps to | Notes |
|---|---|---|---|---|
| `dc:title` | string | "SOCIAL SECURITY ACT" | `NormMetadata.title` | |
| `citableAs` | string | "Public Law 95-563, as amended" | `extra.citable_as` | |
| `citableAsShortTitle` | string | "CONTRACT DISPUTES ACT" | `NormMetadata.short_title` | |
| `docNumber` | string | "563" or "ch531" | Part of identifier | PL number or chapter |
| `currentThroughPublicLaw` | string | "119-75" | `extra.current_through_public_law` | Version indicator |
| `approvedDate` | date | "1935-08-14" | `NormMetadata.publication_date` | Original enactment |
| `congress` | int | 74 | `extra.congress` | Original Congress |
| `containsShortTitle` | list | ["Medicare Act", "Medicaid Act", ...] | `NormMetadata.subjects` | Laws within compilation |
| `property[@role="fileId"]` | string | "8768" | Part of identifier | COMPS file ID |
| `processedDate` | date | "2026-02-20" | `NormMetadata.last_modified` | Last GPO processing |
| `explanationNote` | string | "Currency: This publication..." | — | Not captured; boilerplate |

## 0.4 Formatting inventory

Based on analysis of fixtures (PL 119-1, PL 119-21, Social Security Act COMPS,
FAA COMPS):

- [x] **Tables** — `<table>`, `<row>`, `<entry>` elements. Rare but present
      (1 table found in PL 119-21, 0 in Social Security Act). Tax codes and
      appropriations have more. Must support pipe tables.
- [x] **Bold** — `<b>` element. Common: 302 in SSA, 32 in PL 119-21. Used for
      editorial bracket notes (`[Repealed]`, `[Amended]`) and headings.
- [x] **Italic** — `<i>` element. Rare: 7 in PL 119-21, 0 in SSA. Used in
      enacting formulas ("Be it enacted...").
- [x] **Lists** — Structural: subsections (a)(b)(c), paragraphs (1)(2)(3),
      subparagraphs (A)(B)(C), clauses (i)(ii)(iii). Not HTML lists — they use
      `<subsection>`, `<paragraph>`, etc. with `<num>` elements. The indented
      hierarchical structure IS the list.
- [x] **Footnotes** — `<footnote>` + `<sup>` elements. Abundant: 113 in SSA.
      Editorial and substantive footnotes.
- [x] **Links / cross-references** — `<ref href="/us/usc/t42/s1395">` elements.
      Very common: 250 in SSA, 851 in PL 119-21. Point to other USC sections
      using path notation (`/us/usc/t{N}/s{section}`).
- [ ] **Formulas / math** — Not observed in fixtures. May appear in Title 26
      (Internal Revenue) tax calculations.
- [x] **Quotations / amending text** — `<quotedText>` (inline) and
      `<quotedContent>` (block). Very common in PLs (1053 + 384 in PL 119-21).
      Shows text being added/struck from existing law.
- [x] **Inline formatting** — `<inline class="smallCaps">` very common in PLs
      (2,422 in PL 119-21). Used for subsection headings. Render as UPPERCASE.
- [x] **Editorial notes** — `<editorialNote>` (149 in SSA). OLRC commentary
      about repealed sections, codification notes, etc. Render as blockquote.
- [x] **Source credits** — `<sourceCredit>` element. Shows which Public Laws
      contributed to a section: "(Pub. L. 89-554, Sept. 6, 1966, 80 Stat. 378;
      Pub. L. 95-454, title IX, Oct. 13, 1978, 92 Stat. 1224)".
- [x] **Terms** — `<term>` element (797 in SSA). Defined terms in statutory
      definitions sections. Render as bold or italic.
- [x] **Amending actions** — `<amendingAction type="amend|insert|delete|add">`
      (2,080 in PL 119-21). Shows what the law is doing to existing code.
- [ ] **Images** — Not observed. US Code is text-only. Drop if found.
- [x] **Signatories** — Not in US Code (it's codified). Present in PLs via
      `<action>` element ("Approved January 29, 2025").

### CSS→MD mapping plan

| USLM element | Renders as | css_class |
|---|---|---|
| `<title>` (US Code) | `# Title N — Name` | `titulo_tit` |
| `<subtitle>` | `## Subtitle` | `titulo_tit` |
| `<chapter>` | `## Chapter N — Name` | `capitulo_tit` |
| `<subchapter>` | `### Subchapter` | `seccion` |
| `<part>` | `### Part` | `seccion` |
| `<section>` | `##### § N. Heading` | `articulo` |
| `<subsection>` | `(a) text` | `parrafo` |
| `<paragraph>` | `(1) text` | `parrafo` |
| `<subparagraph>` | `(A) text` | `parrafo` |
| `<clause>` | `(i) text` | `parrafo` |
| `<b>` | `**text**` | inline |
| `<i>` | `*text*` | inline |
| `<inline class="smallCaps">` | `TEXT` (uppercase) | inline |
| `<ref>` | `[text](#ref)` or `[text](url)` | inline |
| `<footnote>` | `[^N]` + block at section end | — |
| `<editorialNote>` | `> [Note: text]` | blockquote |
| `<sourceCredit>` | `(Source: text)` italic | `parrafo` |
| `<term>` | `**term**` (bold) | inline |
| `<table>` | MD pipe table | `table` |
| `<quotedText>` | `"text"` | inline |

## 0.5 Version history spike

### Release points (OLRC)

The OLRC publishes "release points" — complete snapshots of the US Code updated
through a specific Public Law. Each release point includes the entire Code in XML.

**Known release points** (from nickvido/us-code project):

| Tag | Current through | Year | Notes |
|---|---|---|---|
| annual/2013 | P.L. 113-21 | 2013 | Earliest available |
| congress/113 | P.L. 113-296 | 2014 | End of 113th Congress |
| annual/2015 | P.L. 114-38 | 2015 | |
| congress/114 | P.L. 114-329 | 2017 | End of 114th Congress |
| annual/2017 | P.L. 115-51 | 2017 | |
| congress/115 | P.L. 115-442 | 2019 | End of 115th Congress |
| annual/2019 | P.L. 116-91 | 2019 | |
| congress/116 | P.L. 116-344 | 2021 | End of 116th Congress |
| annual/2021 | P.L. 117-81 | 2021 | |
| annual/2022 | P.L. 117-262 | 2022 | |
| congress/117 | P.L. 117-262 | 2022 | End of 117th Congress |
| annual/2024 | P.L. 118-158 | 2024 | |
| congress/118 | P.L. 118-158 | 2024 | End of 118th Congress |
| annual/2025 | P.L. 119-73 | 2025 | Current |

**14 release points** spanning 2013–2025. Each is a complete snapshot of all 54
titles in XML.

### Version extraction strategy

For each chapter in the US Code:

1. Download all 14 release points (54 title ZIPs × 14 = 756 ZIPs)
2. Parse each title XML, extract chapter content
3. For consecutive release points, diff the chapter content
4. If a chapter changed between release points, create a commit with:
   - `GIT_AUTHOR_DATE` = approximate date of the release point
   - `Source-Id` = the Public Law that triggered the release point
   - `Source-Date` = date the PL was signed

**Version spike result:** PARTIAL PASS.

The version history mechanism is well-documented and has been validated by the
nickvido/us-code project (which successfully created 13 release-point commits).
However, I could not independently verify by downloading two release points due
to the OLRC blocking automated downloads.

**Evidence of version tracking in COMPS:**
- Social Security Act: `currentThroughPublicLaw: 119-75` (updated 2026-02-20)
- Contract Disputes Act: `currentThroughPublicLaw: 111-350` (updated 2021-10-15)
- FAA Act: `currentThroughPublicLaw: 118-63` (updated 2024-06-14)

Each compilation tracks which Public Law it has been updated through, confirming
the version-tracking mechanism works.

**Limitation:** 14 release points means at most 14 versions per chapter. This is
coarse compared to Spain (hundreds of reforms per law) but represents the best
available granularity. Phase 2 could add per-Public-Law commits by parsing
amendment instructions in each PL.

### Gate assessment

> GATE: ≥2 versions extracted with dates from 1 law.

**Status: CONDITIONAL PASS.** The mechanism is proven (us-code project has 13
tagged releases), but our pipeline cannot yet download the data automatically.
The OLRC download issue must be resolved before implementation. Options:

1. **Manual pre-download:** User downloads ZIPs via browser, pipeline reads from
   local filesystem (like France's LEGI dump approach)
2. **Headless browser:** Use Playwright/Selenium to download
3. **Alternative mirror:** Check if Internet Archive or another mirror hosts OLRC data
4. **Request patterns:** Try different User-Agent, slower rate, connection pooling

## 0.6 Scope estimate

### US Code scope

- **54 titles** organized by subject matter
- **~3,000 chapters** (the chosen granularity for Legalize)
- **~37,500–60,400 sections** within those chapters
- **27 positive law titles** (the Code IS the law)
- **27 non-positive law titles** (Statutes at Large is authoritative; Code is
  editorial convenience)

### Fetch cost

- **Full bootstrap:** 756 ZIP downloads (54 titles × 14 release points)
- **ZIP sizes:** ~350 KB (Title 1) to ~100+ MB (Title 42), estimated ~510 MB
  total per release point
- **Total download:** ~7 GB across all 14 release points
- **Rate:** Unknown (OLRC blocking needs to be solved first)
- **Processing:** Parse 756 XMLs, split into ~3,000 chapters per release point,
  diff consecutive release points to generate commits

### Estimated output

- **~3,000 files** in `legalize-us` repo (one per chapter)
- **Up to 14 commits per chapter** (one per release point where it changed)
- **Estimated total commits:** ~10,000–20,000 (most chapters don't change every
  release point)
- **Repo size:** Estimated 200–500 MB

### Daily updates

The OLRC publishes new release points irregularly (every few weeks during
Congressional sessions). Daily update flow:

1. Check if a new release point exists on the OLRC download page
2. If yes, download the updated title ZIPs
3. Diff against the previous release point
4. Create commits for changed chapters

This is not a "daily" flow — it's more like "periodic" (bi-weekly to monthly).
The pipeline should poll for new release points rather than assuming daily updates.

### Known blockers

1. **OLRC automated download blocking** — curl/wget time out. Must be solved
   before any automated pipeline work.
2. **Large file sizes** — Some title XMLs are 100+ MB. Parser must stream or
   chunk the XML.
3. **No pre-2013 history** — Release points only go back to P.L. 113-21 (2013).
   Earlier versions would require parsing annual printed editions (PDF only).

## Architecture decisions

### What is a "norm" for the US?

| Concept | European equivalent | Legalize unit? |
|---|---|---|
| US Code Title (54) | Body of law (e.g., "Civil Code") | Too coarse — Title 42 = 76 MB |
| US Code Chapter (~3,000) | Division/book within a code | **YES — chosen granularity** |
| US Code Section (~60,000) | Individual article | Too fine — some are 2 lines |
| Public Law | Individual gazette publication | Not consolidated — "as enacted" |
| Statute Compilation (~2,100) | Consolidated individual law | Supplementary only |

**Decision: Chapter-level granularity.**

Each US Code chapter = one norm = one Markdown file. Chapters are the largest
unit that consistently produces manageable file sizes while remaining coherent
legal topics.

### Identifier convention

Format: `USC-T{title}-CH{chapter}` (filesystem-safe, stable)

Examples:
```
us/USC-T1-CH1.md     → Title 1, Chapter 1 — Rules of Construction
us/USC-T18-CH1.md    → Title 18, Chapter 1 — General Provisions
us/USC-T18-CH113.md  → Title 18, Chapter 113 — Stolen Property
us/USC-T42-CH7.md    → Title 42, Chapter 7 — Social Security
```

**Country code:** `us` (ISO 3166-1 alpha-2 for United States)

### Source URL pattern

```
https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title{N}-chapter{M}
```

### Rank

All US Code content is `Rank("statute")`. The US Code doesn't have a hierarchy
of normative ranks like European systems (constitution → organic law → law →
decree). The US Constitution is NOT in the US Code — it's a separate document.

### Phase 2: Constitution

The US Constitution and its 27 amendments are separate from the US Code. They
should be added as a single file `us/US-CONSTITUTION.md` with amendment versions
as commits. Source: https://constitution.congress.gov/ (XML available).

### Phase 2: Statute Compilations supplement

The ~2,100 COMPS on GovInfo cover statutes that aren't fully in the US Code
(non-positive law titles). These could be added as supplementary norms with
identifier format `COMP-{id}` (e.g., `us/COMP-8768.md`).

## XML structure reference

### US Code document (`<uscDoc>`)

```xml
<uscDoc xmlns="http://xml.house.gov/schemas/uslm/1.0"
        identifier="/us/usc/t18">
  <meta>
    <property name="docTitle">Title 18—Crimes and Criminal Procedure</property>
    <property name="docNumber">18</property>
    <property name="docPublicationName">United States Code</property>
  </meta>
  <main>
    <title>
      <num value="18">TITLE 18—</num>
      <heading>CRIMES AND CRIMINAL PROCEDURE</heading>

      <chapter identifier="/us/usc/t18/ch1">
        <num value="1">CHAPTER 1—</num>
        <heading>GENERAL PROVISIONS</heading>

        <section identifier="/us/usc/t18/s1">
          <num value="1">§ 1.</num>
          <heading>Offenses classified</heading>
          <subsection identifier="/us/usc/t18/s1/a">
            <num value="a">(a)</num>
            <text>Notwithstanding any Act of Congress...</text>
          </subsection>
        </section>

        <sourceCredit>(June 25, 1948, ch. 645, 62 Stat. 684;
          Pub. L. 107–273, div. B, title IV, § 4002(d)(1)(A),
          Nov. 2, 2002, 116 Stat. 1808.)</sourceCredit>
      </chapter>
    </title>
  </main>
</uscDoc>
```

### Public Law (`<pLaw>`)

```xml
<pLaw xmlns="http://schemas.gpo.gov/xml/uslm">
  <meta>
    <dc:title>Public Law 119-1: Laken Riley Act</dc:title>
    <docNumber>1</docNumber>
    <approvedDate>2025-01-29</approvedDate>
    <congress>119</congress>
  </meta>
  <main>
    <section identifier="/us/pl/119/1/s1">
      <num value="1">SECTION 1.</num>
      <heading>SHORT TITLE.</heading>
      <content>This Act may be cited as the "Laken Riley Act".</content>
    </section>
    <section identifier="/us/pl/119/1/s2" role="instruction">
      <heading>DETENTION OF CERTAIN ALIENS.</heading>
      <chapeau>Section 236(c) of the INA (8 U.S.C. 1226(c))
        <amendingAction type="amend">is amended</amendingAction>—
      </chapeau>
      <!-- amendment instructions -->
    </section>
  </main>
  <legislativeHistory>...</legislativeHistory>
</pLaw>
```

### Statute Compilation (`<statuteCompilation>`)

```xml
<statuteCompilation xmlns="http://schemas.gpo.gov/xml/uslm">
  <meta>
    <dc:title>SOCIAL SECURITY ACT</dc:title>
    <currentThroughPublicLaw>119-75</currentThroughPublicLaw>
    <approvedDate>1935-08-14</approvedDate>
    <containsShortTitle>Medicare Act</containsShortTitle>
    <property role="fileId">8768</property>
  </meta>
  <main>
    <section identifier="/us/sComp/74/271/s1801">
      <num value="1801">Sec. 1801.</num>
      <heading>Prohibition against any Federal interference.</heading>
      <content>Nothing in this title shall be construed to...</content>
      <sourceCredit>(Aug. 14, 1935, ch. 531, title XVIII, § 1801,
        as added July 30, 1965, Pub. L. 89-97, title I, § 102(a),
        79 Stat. 291.)</sourceCredit>
    </section>
  </main>
</statuteCompilation>
```

## Comparison with existing Legalize countries

| Aspect | Spain (es) | Latvia (lv) | Belgium (be) | **US (us)** |
|---|---|---|---|---|
| Source | BOE API | likumi.lv HTML | Justel HTML | OLRC XML |
| Format | XML | HTML | HTML | USLM XML |
| Norm count | ~12K | ~48K | ~17.7K | **~3K chapters** |
| Version mechanism | Embedded `<bloque>` | — (single snapshot) | `arch=N` URLs | Release points (14) |
| Daily updates | Sumario API | — | — | New release points (irregular) |
| Auth | None | None | None | None (but blocks curl) |
| Rate limits | None | Crawl-delay: 5 | None | Unknown |
| License | Reuse allowed | Public domain | Public domain | **Public domain** |

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| OLRC blocks automated downloads | Cannot fetch data | Manual pre-download; headless browser; request API access |
| Large title XMLs (100+ MB) | Memory issues during parsing | Stream-parse with `lxml.etree.iterparse`; process one chapter at a time |
| Only 14 release points | Coarse version history | Phase 2: parse PLs to reconstruct per-law amendments |
| Chapter numbering changes | Identifier instability | Use OLRC identifier paths (stable across release points) |
| Non-positive law titles | Editorial, not authoritative | Document in frontmatter; note that Statutes at Large is authoritative |

## Implementation plan

### Phase 1: MVP with manual pre-download

1. User manually downloads 14 release point ZIPs from OLRC (54 titles × 14 ≈ 756 files)
2. Pipeline reads from local filesystem (like `fr/` LEGI approach)
3. For each release point, parse each title XML and split by chapter
4. Diff consecutive release points to generate commits
5. ~3,000 files, ~10K-20K commits

### Phase 2: Automation + enrichment

1. Solve OLRC download automation (headless browser or API request)
2. Parse Public Laws to create per-PL amendment commits (finer-grained history)
3. Add US Constitution as separate norm
4. Add Statute Compilations for standalone statutes
5. Automated daily/periodic updates

## Prior art

| Project | Approach | Status |
|---|---|---|
| [nickvido/us-code](https://github.com/nickvido/us-code) | OLRC XML → chapter-level Markdown, 14 release points | Active (2025) |
| [divegeek/uscode](https://github.com/divegeek/uscode) | US Code in Git | Historical |
| [unitedstates/congress](https://github.com/unitedstates/congress) | Bill/vote/amendment scraper | Active, maintained by GovTrack |
