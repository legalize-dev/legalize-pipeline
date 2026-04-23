# RESEARCH-CA: Canada Federal Legislation

## 0.1 Source identification

| Field | Value |
|---|---|
| **Official name** | Consolidated Acts and Regulations of Canada |
| **Publisher** | Justice Canada (Department of Justice) |
| **Primary source** | GitHub: https://github.com/justicecanada/laws-lois-xml |
| **Secondary source** | XML API: https://laws-lois.justice.gc.ca/eng/XML/{ID}.xml |
| **Format** | Custom Justice Canada XML (Statute/Regulation DTD) |
| **License** | Open Government Licence - Canada |
| **Auth** | None required |
| **Rate limits** | GitHub: standard git clone. API: no documented limit, conservative 1 req/s. |
| **Bilingual** | English (`eng/`) and French (`fra/`) — separate XML files |

### Data access patterns

**Primary (bulk):** Clone `justicecanada/laws-lois-xml` repository.
```
eng/acts/*.xml        — English consolidated acts (~956 files)
eng/regulations/*.xml — English regulations (~4,845 files)
fra/lois/*.xml        — French consolidated acts
fra/reglements/*.xml  — French regulations
```

**Secondary (per-law):** Direct XML download.
```
https://laws-lois.justice.gc.ca/eng/XML/{ConsolidatedNumber}.xml    (acts)
https://laws-lois.justice.gc.ca/eng/XML/{InstrumentNumber}.xml      (regs)
```

**Version history:** Git history of `justicecanada/laws-lois-xml`. Each "Laws Site
Update" commit (~biweekly) represents a new consolidation snapshot. The XML API
does NOT support historical versions via `?pit=` parameter — it always returns
the current text regardless. See version-spike.txt for full analysis.

### Note on hasPreviousVersion

Some XML files have `hasPreviousVersion="true"` on the root element. This does
NOT mean the API serves those versions. It only indicates that the law has been
amended. Historical versions are accessible only through git history.

## 0.2 Fixtures

| Fixture | Description | Size | Location |
|---|---|---|---|
| `sample-act-minimal.xml` | Canada Agricultural Products Act (C-0.4) — repealed, minimal structure | 1.8 KB | `tests/fixtures/ca/` |
| `sample-act-small.xml` | Budget Implementation Act, 1995 (B-9.8) — 25 sections, 2 schedules | 14 KB | `tests/fixtures/ca/` |
| `sample-act-with-tables.xml` | Alberta Natural Resources Act (A-10.6) — 2 tables, 2 schedules, emphasis | 45 KB | `tests/fixtures/ca/` |
| `sample-regulation.xml` | SOR/99-129 — small regulation, 4 sections, defined terms | 5 KB | `tests/fixtures/ca/` |
| `sample-regulation-with-tables.xml` | Lands Surveys Tariff (C.R.C., c. 1021) — 1 table in schedule | 7 KB | `tests/fixtures/ca/` |
| `version-spike.txt` | Version history analysis (A-1, 10 versions via git) | — | `tests/fixtures/ca/` |

## 0.3 Metadata inventory

### Root attributes (Statute/Regulation element)

| Source field | Type | Example | Maps to | Notes |
|---|---|---|---|---|
| Root tag (`Statute`/`Regulation`) | string | "Statute" | Determines `NormMetadata.rank` | act vs regulation |
| `lims:pit-date` | date | "2025-06-02" | `NormMetadata.publication_date` | Point-in-time date |
| `lims:lastAmendedDate` | date | "2025-06-02" | `extra.last_amended` | Last amendment date |
| `lims:current-date` | date | "2026-03-02" | `extra.current_date` | Consolidation date |
| `lims:inforce-start-date` | date | "2018-12-13" | `extra.inforce_start` | First in-force date |
| `lims:fid` | int | "167" | `extra.fid` | Justice Canada internal ID |
| `lims:id` | int | "167" | `extra.lims_id` | Justice Canada internal ID |
| `hasPreviousVersion` | bool | "true" | `extra.has_previous_version` | Has amendments |
| `in-force` | string | "yes"/"no" | `NormMetadata.status` | IN_FORCE / REPEALED |
| `bill-origin` | string | "commons"/"senate" | `extra.bill_origin` | Originating chamber |
| `bill-type` | string | "govt-public" | `extra.bill_type` | Bill classification |
| `xml:lang` | string | "en"/"fr" | Determines output path | Language |

### Identification elements

| Source field | Type | Example | Maps to | Notes |
|---|---|---|---|---|
| `ShortTitle` | string | "Access to Information Act" | `NormMetadata.title` | Official short title |
| `LongTitle` | string | "An Act to extend..." | `NormMetadata.summary` | Fallback if no ShortTitle |
| `ConsolidatedNumber` | string | "A-1" | `NormMetadata.identifier` | For acts |
| `InstrumentNumber` | string | "SOR/99-129" | `NormMetadata.identifier` | For regulations (sanitized: `/` → `-`) |
| `RunningHead` | string | "Access to Information" | `NormMetadata.short_title` | Abbreviated heading |
| `EnablingAuthority` | string | "Insurance Companies Act" | `NormMetadata.department` | For regulations |
| `BillHistory/Stages/Date` | date | "2026-03-03" | `extra.consolidation_date` | Consolidation stage date |
| `Chapter/ConsolidatedNumber` | string | "A-1" | Same as ConsolidatedNumber | |

### Section-level attributes

| Source field | Type | Example | Notes |
|---|---|---|---|
| `lims:inforce-start-date` | date | "2019-06-21" | Per-section effective date |
| `lims:lastAmendedDate` | date | "2019-06-21" | Per-section amendment date |
| `lims:enacted-date` | date | "2019-06-21" | Per-section enactment date |

### Derived fields

| Field | Value | Maps to |
|---|---|---|
| (fixed) | "ca" | `NormMetadata.country` |
| (derived from root tag) | "act" / "regulation" | `NormMetadata.rank` |
| (derived from identifier) | URL | `NormMetadata.source` |
| (fixed) | "Parliament of Canada" / EnablingAuthority | `NormMetadata.department` |

## 0.4 Formatting inventory

- [x] **Tables** — `<TableGroup>` with `<table>` (XHTML inside XML). Found in A-10.6, C.R.C. c. 1021.
- [x] **Bold/Emphasis** — `<Emphasis>` element wraps emphasized text. Found in all fixtures.
- [x] **Italic** — Defined terms use `<DefinedTermEn>` / `<DefinedTermFr>`, rendered as italic.
- [x] **Lists** — Subsection/Paragraph/Subparagraph hierarchy with `<Label>` elements.
- [ ] **Footnotes** — Not observed in fixtures. May exist in larger acts.
- [x] **Links/cross-refs** — `<XRefExternal reference-type="act" link="A-1">` for cross-law references.
- [x] **Formulas** — `<Formula>` with `<FormulaTerm>`, `<FormulaText>`, `<FormulaDefinition>`. Found in tax/financial legislation.
- [x] **Quotations/Preamble** — `<Preamble>` element for enacting clauses.
- [x] **Schedules/Annexes** — `<Schedule>` elements with their own body, headings, tables.
- [x] **Definitions** — `<Definition>` blocks with `<DefinedTermEn>` and `<DefinitionRef>`.
- [x] **Oaths** — `<Oath>` element for sworn text.
- [ ] **Images** — Not observed. Legislative XML is text-only.
- [x] **Signatories** — Not in XML (consolidated text, not as-enacted).

### Structural hierarchy

```
Statute/Regulation
  └─ Body
      ├─ Heading (level=1..N)
      │   └─ TitleText
      ├─ Part
      │   ├─ Label + TitleText
      │   └─ (recursive: Heading, Section, Division...)
      ├─ Division
      │   ├─ Label + TitleText
      │   └─ (recursive)
      ├─ Section
      │   ├─ MarginalNote (section title)
      │   ├─ Label (section number)
      │   ├─ Text (direct content)
      │   ├─ Subsection
      │   │   ├─ Label ("(1)", "(2)", ...)
      │   │   ├─ Text
      │   │   ├─ Paragraph
      │   │   │   ├─ Label ("(a)", "(b)", ...)
      │   │   │   ├─ Text
      │   │   │   └─ Subparagraph
      │   │   │       ├─ Label ("(i)", "(ii)", ...)
      │   │   │       └─ Clause → Subclause
      │   │   ├─ ContinuedParagraph
      │   │   ├─ ContinuedSubparagraph
      │   │   ├─ Item (list items)
      │   │   └─ Formula
      │   └─ Definition
      │       ├─ DefinedTermEn / DefinedTermFr
      │       └─ Text
      ├─ Schedule
      │   ├─ Label
      │   ├─ (recursive body)
      │   └─ TableGroup
      └─ Oath
```

## 0.5 Version history spike

**GATE: PASS** — See `tests/fixtures/ca/version-spike.txt`

Summary:
- 10 versions of A-1.xml observed via GitHub API (2024-11 to 2026-03)
- Two versions differ in size (485,914 vs 485,447 bytes)
- Stable identifier (ConsolidatedNumber `A-1`) across all versions
- Version access via `git log` per file — no API support for historical versions
- Dates extractable from: commit date, pit-date, lastAmendedDate in XML

### Version history strategy

1. Clone `justicecanada/laws-lois-xml` with full git history
2. For each law file, walk `git log -- path/to/file.xml` to enumerate versions
3. Each commit's version = one version of the law
4. Use `lims:pit-date` from XML as `publication_date` (more precise than commit date)
5. Use commit date as `effective_date` (when the consolidation was published)

**Version strategy — IMPLEMENTED as suvestine walk**

`JusticeCanadaClient.get_suvestine(norm_id)` shells out to `git log --follow
-- <file>` in the upstream clone, then `git show SHA:<file>` for each
commit, and packs the result as a JSON blob of
`{sha, date, base64(xml)}` entries. `CATextParser.parse_suvestine` parses
each historical XML through the same `_parse_root` used for the current
snapshot and emits one `Version` per upstream commit on that file. The
pipeline auto-picks this path via the `hasattr(client, "get_suvestine")`
hook in `pipeline.py::_fetch_single_norm`, so both bootstrap and daily
use full history for free.

Per-version mapping:
- `Version.publication_date` = upstream commit date
- `Version.effective_date` = `lims:pit-date` from the XML at that commit
  (more precise), falling back to commit date
- `Reform.norm_id` = upstream SHA (unique dedup key per revision — the
  committer's `(Source-Id, Norm-Id)` check skips re-runs safely)

**Why this works cleanly for Canada:**
- The upstream repo IS the archive; no remote API calls, no rate limits
- Identifier is stable across versions (`ConsolidatedNumber` never changes)
- `--follow` tracks any future renames defensively
- Missing XML at a given commit (file not yet created) is skipped, not fatal

**CI cadence:** `.github/workflows/biweekly-update-ca.yml` runs on the
2nd and 16th of each month. Full bootstrap runs idempotently: existing
commits (by SHA key) are skipped, only new upstream revisions land.

## 0.6 Scope estimate

| Metric | Value |
|---|---|
| **English acts** | ~956 |
| **English regulations** | ~4,845 |
| **French acts** | ~956 (parallel) |
| **French regulations** | ~4,845 (parallel) |
| **Total norms** | ~11,600 (en + fr) |
| **HTTP requests (bulk clone)** | 1 (git clone ~200 MB) |
| **HTTP requests (per-file API)** | ~11,600 (one per norm) |
| **Estimated fetch time (clone)** | ~5 min |
| **Estimated fetch time (API)** | ~3-4h at 1 req/s |
| **Daily update cadence** | Biweekly (Laws Site Update commits) |
| **Known blockers** | None — public repo, no auth, no rate limits |

### Recommended approach

Use the **git clone** approach (primary source) for bootstrap, not the API.
The local XML clone provides instant access to all ~11,600 files without
HTTP overhead. Daily updates via `git pull` are trivial.

### Bilingual handling — DECIDED

Canada's Constitution makes English and French equally authoritative for
federal law, and `justicecanada/laws-lois-xml` ships each act/regulation
as two parallel files (`eng/acts/A-1.xml` and `fra/lois/A-1.xml`) sharing
the same identifier. We therefore emit **both languages symmetrically**
as separate jurisdictions within a single repo (`legalize-ca`):

- `ca-en/A-1.md` — English text (`jurisdiction: "ca-en"`, `country: "ca"`, `extra.lang: "en"`)
- `ca-fr/A-1.md` — French text (`jurisdiction: "ca-fr"`, `country: "ca"`, `extra.lang: "fr"`)

Nothing is written directly to `ca/`. Neither language is privileged as
a "default" — the split mirrors the source's layout and matches how Canada
itself treats the two texts. The `norm_id` prefix (`eng/...` / `fra/...`)
drives the jurisdiction assignment in `CAMetadataParser`.

Upstream scope (`eng/` + `fra/`, per language):
- ~956 consolidated acts
- ~4,845 regulations
- Total per language: ~5,800 norms
- **Total across both languages: ~11,600 norms**

**Web-app implication:** `legalize.dev/ca` has no content of its own;
consumers will need to route to `ca-en` or `ca-fr` (via a language toggle
or a redirect from the locale). Document this as a web-side follow-up.

**Out of scope for v1 ingestion:**
- `annual-statutes-lois-annuelles/` — statutes as-enacted per year (bill
  texts before consolidation). Useful for reconstructing history but
  redundant with the git-log walk over `eng/acts/*.xml`. Skip for v1.
- `tops-tdlp/`, `lookup/`, `xslt/` — indices and stylesheets, no
  legislative content.
