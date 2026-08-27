# RESEARCH-US: United States Code

## 0.1 Source identification

| Field | Value |
|---|---|
| **Official name** | United States Code (USC) |
| **Publisher** | Office of the Law Revision Counsel (OLRC), U.S. House of Representatives |
| **URL** | https://uscode.house.gov |
| **Format** | USLM XML (United States Legislative Markup) |
| **License** | Public domain (17 U.S.C. § 105) |
| **Auth** | None required |
| **Rate limits** | No documented limit. Conservative 1 req/s recommended. |
| **Geo-blocking** | Non-US IPs blocked. Wayback Machine fallback available. |
| **API type** | Static file downloads (ZIP archives per title per release point) |

### Data access pattern

The OLRC publishes **release points** — complete snapshots of the entire US Code
current through a specific Public Law. Each release point contains 54 title ZIPs.
Each ZIP contains one USLM XML file with all sections of that title.

```
https://uscode.house.gov/download/releasepoints/us/pl/{congress}/{law}/xml_usc{NN}@{congress}-{law}.zip
```

Example: Title 18 at PL 119-73:
```
https://uscode.house.gov/download/releasepoints/us/pl/119/73/xml_usc18@119-73.zip
```

### Known release points (12 total, 2013-2025)

| Tag | Congress | Public Law | Date |
|---|---|---|---|
| 113-21 | 113th | PL 113-21 | 2013-07-18 |
| 113-296 | 113th | PL 113-296 | 2015-01-02 |
| 114-38 | 114th | PL 114-38 | 2015-07-08 |
| 114-329 | 114th | PL 114-329 | 2017-01-06 |
| 115-51 | 115th | PL 115-51 | 2017-08-14 |
| 115-442 | 115th | PL 115-442 | 2019-01-14 |
| 116-91 | 116th | PL 116-91 | 2019-12-19 |
| 116-344 | 116th | PL 116-344 | 2021-01-13 |
| 117-81 | 117th | PL 117-81 | 2021-12-27 |
| 117-262 | 117th | PL 117-262 | 2022-12-22 |
| 118-158 | 118th | PL 118-158 | 2024-12-31 |
| 119-73 | 119th | PL 119-73 | 2025-01-23 |

## 0.2 Fixtures

| Fixture | Description | Location |
|---|---|---|
| `sample-uscode-title1.xml` | Title 1, Section 1 (General Provisions) — section-level uscDoc | `tests/fixtures/us/` |
| `sample-comps-regulation.xml` | FAA Modernization Act compilation | `tests/fixtures/us/` |
| `sample-comps-small.xml` | Contract Disputes Act compilation | `tests/fixtures/us/` |
| `sample-public-law-small.xml` | Public Law 119-1 (standalone) | `tests/fixtures/us/` |
| `version-spike.txt` | Version history comparison (PL 113-21 vs PL 118-158) | `tests/fixtures/us/` |

## 0.3 Metadata inventory

| Source field | Type | Example | Maps to | Notes |
|---|---|---|---|---|
| `dc:title` | string | "Title 1 — General Provisions" | `NormMetadata.title` (combined with section heading) | Title-level |
| Section `identifier` | string | "/us/usc/t1/s1" | Derives `NormMetadata.identifier` as `USC-T1-S1` | Section-level |
| Section `num` | string | "§ 1." | Part of title | |
| Section `heading` | string | "Words denoting number, gender..." | Part of title | |
| `docPublicationName` | string | "Online@118-158" | `extra.release_point` | Maps to release date |
| `dcterms:created` | date | "2024-12-31" | `NormMetadata.publication_date` | |
| `property[role=is-positive-law]` | string | "yes" / "no" | `extra.positive_law` | |
| `sourceCredit` | string | "(July 30, 1947, ch. 388...)" | `extra.source_credit` | Capped at 500 chars |
| (derived) | string | "1" | `extra.title_number` | From norm_id |
| (derived) | url | "https://uscode.house.gov/..." | `NormMetadata.source` | Granule URL |
| (fixed) | string | "United States Congress" | `NormMetadata.department` | |
| (fixed) | string | "us" | `NormMetadata.country` | ISO 3166-1 |
| (fixed) | Rank | "statute" | `NormMetadata.rank` | |
| (fixed) | NormStatus | IN_FORCE | `NormMetadata.status` | All published sections |

## 0.4 Formatting inventory

- [x] **Tables** — XHTML `<table>` inside USLM. Converted to MD pipe tables.
- [x] **Bold** — `<b>`, `<strong>`, `<term>` → `**...**`
- [x] **Italic** — `<i>`, `<em>` → `*...*`
- [ ] **Lists** — `<p role="listItem">` → `- ...`
- [x] **Footnotes** — `<footnote id="...">` → `[^id]`
- [x] **Links** — `<ref href="...">` → `[text](url)`
- [ ] **Formulas** — Not observed in fixtures
- [x] **Quotations** — `<quotedText>` → `"..."`
- [ ] **Attachments** — Not applicable (sections are self-contained)
- [ ] **Signatories** — Not applicable (codified law, not enacted text)

## 0.5 Version history spike

**GATE: PASS** — See `tests/fixtures/us/version-spike.txt`

- Version 1: PL 113-21 (2013) — 40 sections, 91,758 chars
- Version 2: PL 118-158 (2024) — 40 sections, 123,738 chars
- 21 of 40 sections changed (52.5%)
- Stable identifiers across versions
- Download via Wayback Machine works as geo-block fallback

## 0.6 Scope estimate

| Metric | Value |
|---|---|
| **Total sections** | ~60,000 across 54 titles |
| **Release points** | 12 (2013-2025) |
| **HTTP requests for full history** | 54 titles × 12 release points = 648 ZIP downloads |
| **ZIP size** | 5-50 MB per title |
| **Total download size** | ~3-5 GB (all release points) |
| **Estimated fetch time** | ~2h at 1 req/s (with retries) |
| **Known blockers** | OLRC geo-blocks non-US IPs → Wayback Machine fallback |
| **Daily cadence** | Release points are published ~2x per Congress (~every 6 months) |

### Granularity decision

The pipeline works at **section granularity** (one norm = one section, ~60K norms).
This matches the OLRC's own granule identifier scheme (`/us/usc/t{N}/s{M}`).
Each section becomes one Markdown file: `us/USC-T{N}-S{M}.md`.
