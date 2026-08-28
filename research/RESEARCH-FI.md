# Research: Finland (FI) — Finlex Open Data API

## Source

**Name:** Finlex  
**URL:** https://www.finlex.fi  
**API Base:** https://opendata.finlex.fi/finlex/avoindata/v1  
**Documentation:** https://www.finlex.fi/en/open-data/integration-quick-guide  
**Swagger:** https://opendata.finlex.fi/swagger-ui/index.html  
**License:** CC BY 4.0 (commercial use allowed)  
**Auth:** None required (must set User-Agent header)  
**Rate limit:** Returns HTTP 429 on overload (no published threshold)  

## Data format

Akoma Ntoso 3.0 XML (OASIS standard) with `finlex:` namespace extensions.
Each document is a self-contained XML file with `<meta>` (FRBR identification,
classification, proprietary Finlex fields) and `<body>` (structured legal text).

## Scope

| Type | Finnish name | Count (Finnish only) |
|---|---|---|
| act (laki) | Laki | ~5,758 |
| decree (asetus) | Asetus | ~18,851 |
| order (määräys) | Määräys | ~40 |
| **Total** | | **~42,500** |

Year range: 1734–2026 (includes historical statutes from the Swedish era).

## Endpoints used

| Endpoint | Purpose |
|---|---|
| `GET /akn/fi/act/statute-consolidated/list?format=json&page=N&limit=10&langAndVersion=fin@` | Discovery: paginated list of all statutes |
| `GET /akn/fi/act/statute-consolidated/{year}/{number}?page=N&limit=4` | List versions (expressions) of a specific statute |
| `GET /akn/fi/act/statute-consolidated/{year}/{number}/{langAndVersion}` | Fetch a specific consolidated version as XML |

Query parameters: `publishedSince` (ISO datetime, for daily), `typeStatute`,
`startYear`, `endYear`, `titleContains`, `keyword`, `sortBy`.

## Version history

Finlex provides **multiple consolidated versions** (point-in-time snapshots) for
each statute. Each version represents the law after a specific amendment was
incorporated.

**Version spike results (Income Tax Act 1535/1992):**
- 84 Finnish consolidated versions available via the API
- Each version identified by `fin@{versionNumber}` (e.g., `fin@20161318`)
- Version number encodes the triggering amendment: `{year}{number:04d}`
- Each amendment has `finlex:dateEntryIntoForce` → usable as `GIT_AUTHOR_DATE`
- 236 reforms listed in `finlex:amendedBy` metadata

**Version spike results (Constitution 731/1999):**
- 1 consolidated version (4 amendments applied)
- Entry-into-force: 2000-03-01

**Strategy:** For each statute, paginate through all versions, fetch each
version's XML, and create one commit per version with the amendment's
entry-into-force date as the author date.

## Metadata inventory

| Source field | Location in XML | Maps to | Notes |
|---|---|---|---|
| `FRBRnumber` | `FRBRWork` | identifier (part of) | Statute number |
| `finlex:documentYear` | `proprietary` | identifier (part of) | Statute year |
| `docTitle` | `preface` | `NormMetadata.title` | Full title in Finnish |
| `FRBRdate[@name='dateIssued']` | `FRBRWork` | `NormMetadata.publication_date` | Date the statute was issued |
| `FRBRdate[@name='datePublished']` | `FRBRWork` | (fallback pub date) | Date published in gazette |
| `FRBRdate[@name='dateConsolidated']` | `FRBRExpression` | `NormMetadata.last_modified` | Date of this consolidated version |
| `finlex:typeStatute` | `proprietary` | `NormMetadata.rank` | act, decree, order |
| `finlex:isInForce` | `proprietary` | `NormMetadata.status` | true/false |
| `finlex:dateEntryIntoForce` | `proprietary/inForce` | `extra.entry_into_force` | Original entry-into-force date |
| `finlex:administrativeBranch` | `proprietary` | `NormMetadata.department` | Responsible ministry |
| `keyword[@showAs]` | `classification` | `NormMetadata.subjects` | Subject keywords |
| `FRBRalias[@name='eli']` | `FRBRWork` | `extra.eli` | European Legislation Identifier |
| `finlex:amendedBy` | `proprietary` | Reforms list | List of amending statutes with dates |
| `finlex:issuedUnderThisAct` | `proprietary` | `extra` (if needed) | Subordinate legislation |
| `finlex:repeals` | `proprietary` | `extra` (if needed) | Statutes repealed by this one |
| `finlex:categoryStatute` | `proprietary` | `extra.category` | new-statute, amending-statute |
| `finlex:corrigenda` | `proprietary` | (not captured yet) | Official corrections |
| `finlex:noteEditorial` | `proprietary` | (not captured yet) | Editorial notes on amendments |
| `FRBRversionNumber` | `FRBRExpression` | (internal) | Version identifier |
| `FRBRlanguage` | `FRBRExpression` | (filter) | fin/swe |

## Formatting inventory

| Construct | Present? | Handling |
|---|---|---|
| Chapters (`<chapter>`) | Yes | `### num. heading` |
| Sections/§ (`<section>`) | Yes | `##### num heading` |
| Parts (`<part>`) | Yes (large codes) | `## num. heading` |
| Subsections | Yes | Normal paragraph |
| Numbered paragraphs | Yes | List items |
| Tables (`<table>`) | Yes (tax law, annexes) | Markdown pipe tables |
| Italic (`<i>`) | Yes | `*text*` |
| Bold | Not found in fixtures | N/A |
| Cross-references (`<ref>`) | Yes (many) | `[text](url)` |
| Images (`<img>`) | Not found in fixtures | Skipped, counted |
| Annexes (`attachments`) | Yes | Parsed with heading + content |
| Editorial notes (`noteAuthorial`) | Yes | Italic text |
| Preamble/enacting clause | Yes | Normal text |

## Bilingual nature

Finland has Finnish and Swedish as official languages. The API exposes both:
- `fin@` — Finnish version (primary for Legalize)
- `swe@` — Swedish version

Initial implementation processes Finnish only. Swedish could be added later
as a separate jurisdiction (`fi-sv/`) or parallel repo.

## Identifier format

- **Internal norm_id:** `{year}/{number}` (e.g., `1999/731`)
- **Metadata identifier:** `{year}-{number}` (filesystem-safe, e.g., `1999-731`)
- **Filename:** `fi/{year}-{number}.md` (e.g., `fi/1999-731.md`)
- **Official citation:** `{number}/{year}` (e.g., `731/1999`, stored in `extra.citation`)

## Fixtures

5 representative fixtures saved in `engine/tests/fixtures/fi/`:

| Fixture | Statute | Size | Features |
|---|---|---|---|
| `sample-constitution.xml` | 731/1999 (Constitution) | 185 KB | 13 chapters, 131 §, 4 reforms |
| `sample-code.xml` | 132/1999 (Land Use Act) | 446 KB | 33 chapters, 227 §, 60 reforms, italic |
| `sample-ordinary-law.xml` | 224/2024 (Immigration Act) | 63 KB | 5 chapters, 25 §, subparagraphs |
| `sample-regulation.xml` | 51/2025 (Decree) | 13 KB | No chapters, 4 §, annex with table |
| `sample-with-tables.xml` | 1535/1992 (Income Tax Act) | 1.1 MB | 7 parts, 5 tables, 236 reforms |

## Bootstrap estimate

- Discovery: ~4,250 API calls (10 items/page)
- Per-law fetch: 1 listing + 1 XML per version (avg ~3 versions per law)
- Total fetches: ~4,250 + ~127,500 = ~132,000
- At 4 workers × 2 req/s = ~8 req/s effective → ~4.5 hours
- Total bootstrap: ~5-6 hours (fetch + commit)
