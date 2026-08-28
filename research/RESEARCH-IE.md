# RESEARCH-IE.md — Ireland

**Date:** 2026-04-13
**Country code:** `ie`
**ISO 3166-1:** IE (Ireland / Éire)

## 0.1 Data sources

### Primary: Irish Statute Book (ISB)

- **Maintainer:** Office of the Attorney General
- **URL:** https://www.irishstatutebook.ie
- **Format:** XML (Acts), HTML (Statutory Instruments — out of scope for Phase 1)
- **License:** CC-BY-4.0 (Oireachtas Open Data PSI Licence, implementing EU Directive 2019/1024)
- **Content:** ~4,041 enacted Acts (1922–2025)
- **Rate limits:** None documented. No robots.txt (404). Apache/2.4.18.
- **Auth:** None
- **Version history:** Only "as enacted" text. No consolidated/point-in-time.

**ELI URL pattern:**
```
https://www.irishstatutebook.ie/eli/{year}/act/{number}/enacted/en/xml   (Act XML)
https://www.irishstatutebook.ie/eli/{year}/act/{number}/enacted/en/html  (Act HTML)
https://www.irishstatutebook.ie/eli/{year}/act/                          (Year listing HTML)
https://www.irishstatutebook.ie/eli/cons/en/html                         (Constitution — HTML only, no XML)
```

XML is available for all Acts 1922–2025. The Constitution has NO XML — only HTML at a special path.

### Discovery: Oireachtas API

- **URL:** https://api.oireachtas.ie/v1/legislation
- **Format:** JSON REST API (OpenAPI 2.0 spec)
- **Content:** 4,041 enacted Acts with rich metadata
- **Rate limits:** None documented. CloudFront-cached.
- **Auth:** None
- **Daily updates:** `last_updated` parameter works for incremental discovery

**Key parameters:**
- `act_year`, `act_no` — filter by year/number
- `bill_status=Enacted` — only enacted acts
- `date_start`, `date_end` — date range
- `last_updated` — for daily discovery
- `skip`, `limit` — pagination
- `lang` — `en` or `ga` (Irish)

**Response fields per act:**
- `actNo`, `actYear`, `dateSigned`
- `shortTitleEn`, `shortTitleGa` (bilingual titles)
- `longTitleEn`, `longTitleGa`
- `statutebookURI` — link to ISB
- `uri` — Oireachtas data URI
- `versions[]` — typically one ("As enacted"), links to PDF only
- `relatedDocs[]` — explanatory memoranda, glossaries, errata
- `events[]`, `debates[]` — parliamentary history

### Supplementary (Phase 2): Revised Acts

- **Maintainer:** Law Reform Commission (LRC)
- **URL:** https://revisedacts.lawreform.ie
- **Format:** HTML and PDF only (no XML, confirmed)
- **Content:** ~560 consolidated Acts (14% of total)
- **Excludes:** Social Welfare Consolidation Act 2005, Finance Acts
- **Version history:** "Updated to {date}" header, amendment annotations (F1, F2, ...), but NO point-in-time navigation or previous version access
- **Not used in Phase 1** — could add "current consolidated" text as a second commit per law in Phase 2

## 0.2 Fixtures

Saved under `engine/tests/fixtures/ie/`:

| File | Act | Size | Features |
|------|-----|------|----------|
| `sample-policing-2024.xml` | Policing, Security and Community Safety Act 2024 (No. 1/2024) | 874 KB | 10 parts, 302 sections, bold, italic, fada chars, 2 tables, footnotes |
| `sample-environment-2015.xml` | Environment (Miscellaneous Provisions) Act 2015 (No. 29/2015) | 171 KB | Multiple parts, cross-references, schedules |
| `sample-finance-2024.xml` | Finance Act 2024 (No. 43/2024) | 621 KB | 12 tables, 70 superscripts, 802 quote pairs, euro symbols |
| `sample-taxes-1997.xml` | Taxes Consolidation Act 1997 (No. 39/1997) | 6.4 MB | 251 tables, 8,178 xrefs, 1,104 sections, pound symbols |
| `sample-constitution.html` | Constitution of Ireland (Bunreacht na hÉireann) | 678 KB | HTML only (no XML), 50 articles, bilingual |

## 0.3 Metadata inventory

| Source field | Type | Example | Maps to | Notes |
|---|---|---|---|---|
| `title` (XML `<title>`) | string | "POLICING, SECURITY AND COMMUNITY SAFETY ACT 2024" | `NormMetadata.title` | All caps in XML, normalize to title case |
| `number` (XML `<number>`) | int | 1 | Part of `identifier` | Act number within year |
| `year` (XML `<year>`) | int | 2024 | Part of `identifier` | |
| `dateofenactment` (XML) | string | "20240207" | `NormMetadata.publication_date` | Format: YYYYMMDD |
| `shortTitleEn` (API) | string | "Policing, Security and Community Safety Act 2024" | `NormMetadata.title` | Prefer over XML title (proper case) |
| `shortTitleGa` (API) | string | "An tAcht um Póilíneacht..." | `extra.title_ga` | Irish language title |
| `longTitleEn` (API) | string | "Act to provide for..." | `NormMetadata.summary` | Long title / purpose |
| `longTitleGa` (API) | string | ... | `extra.long_title_ga` | Irish long title |
| `dateSigned` (API) | date | "2024-02-07" | `NormMetadata.publication_date` | ISO format, prefer over XML |
| `statutebookURI` (API) | url | "http://www.irishstatutebook.ie/eli/2024/act/1" | `NormMetadata.source` | Official ELI URL |
| `uri` (API) | url | "https://data.oireachtas.ie/ie/oireachtas/act/2024/1" | `extra.oireachtas_uri` | Oireachtas data URI |
| `versions[].uri` (API) | url | "https://data.oireachtas.ie/.../enacted" | `NormMetadata.pdf_url` | PDF link |
| `relatedDocs[]` (API) | array | memo, gluais, errata | `extra.related_docs` | Comma-joined doc types |
| Act rank | inferred | "act" | `NormMetadata.rank` | All items are Acts of the Oireachtas |
| Status | inferred | "in_force" | `NormMetadata.status` | Assume in_force (ISB doesn't flag repeals explicitly) |

**Identifier format:** `IE-{year}-act-{number}` (e.g., `IE-2024-act-1`). Filesystem-safe, unique, sortable.

## 0.4 Formatting inventory

Based on analysis of all 5 fixtures:

- [x] **Tables** — `<table>` with `<colgroup>`, `<tr>`, `<td>` (colspan, rowspan, valign). Taxes Act has 251 tables. Finance Act has 12.
- [x] **Bold** — `<b>` inline tags (695 in Policing, 1,121 in Taxes)
- [x] **Italic** — `<i>` inline tags (1,929 in Policing, 18,565 in Taxes). Used for cross-references and emphasis.
- [x] **Lists** — `<bull>` tag (rare, only 3 in Policing). Most lists are formatted as indented paragraphs.
- [x] **Footnotes** — `<fn>` + `<marker>` + `<su>` (superscript). Example: `<fn><marker><su>1</su></marker><p>...</p></fn>`
- [x] **Cross-references** — `<xref>` tags with `href` attribute (8,178 in Taxes). Internal links to parts/sections.
- [ ] **Formulas** — Not observed in any fixture
- [x] **Quotations** — `<odq>`/`<cdq>` (open/close double quote), `<osq>`/`<csq>` (open/close single quote). Very common in amendments.
- [x] **Schedules/Annexes** — `<schedule>` elements in body (7 in Policing, 2 in Finance, 32 in Taxes)
- [x] **Signatories** — Not as formal tags; may appear in `<backmatter>`
- [x] **Superscript/Subscript** — `<su>`, `<sb>` tags
- [ ] **Images** — `<graphic href="harp.jpg">` (state harp logo only, skip)

### Special XML elements (ISB-specific)

| Element | Meaning | Output |
|---------|---------|--------|
| `<ifada/>` | í (i with fada) | `í` |
| `<afada/>` | á (a with fada) | `á` |
| `<ufada/>` | ú (u with fada) | `ú` |
| `<ofada/>` | ó (o with fada) | `ó` |
| `<efada/>` | é (e with fada) | `é` |
| `<Ifada/>` | Í | `Í` |
| `<Afada/>` | Á | `Á` |
| `<Ufada/>` | Ú | `Ú` |
| `<Efada/>` | É | `É` |
| `<Ofada/>` | Ó | `Ó` |
| `<emdash/>` | em dash | `—` |
| `<euro/>` | euro sign | `€` |
| `<pound/>` | pound sign | `£` |
| `<odq/>` | open double quote | `"` |
| `<cdq/>` | close double quote | `"` |
| `<osq/>` | open single quote | `'` |
| `<csq/>` | close single quote | `'` |
| `<bull/>` | bullet | `•` |
| `<hr1/>` | horizontal rule | (skip) |
| `<graphic/>` | image | (skip, count in `extra.images_dropped`) |

### Paragraph class attribute

ISB uses a numeric class system: `class="-3 11 0 left 1 0"`. The 6 numbers encode indentation and alignment. Key patterns:
- `"0 0 0 center 1 0"` — centered text (titles, part headings)
- `"-3 11 0 left 1 0"` — standard indented paragraph (body text)
- `just="left"` / `just="center"` — alignment override

### Font element

`<font size="normal|small|large" smallcaps="yes|no">` — used for:
- Part/chapter headings: `size="normal" smallcaps="yes"`
- Footnotes: `size="small"`
- Title pages: `size="large"`

## 0.5 Version history spike

**GATE: FAIL** — see `tests/fixtures/ie/version-spike.txt`

ISB provides only "as enacted" text. Revised Acts provides current consolidated text for ~560 acts but no point-in-time access. Cannot extract 2 distinct versions with dates.

**Decision:** Proceed with **single-snapshot ship** (as enacted text from ISB XML).

**Justification:**
1. 4,041 acts with clean, well-structured XML
2. "As enacted" IS the official published text — it has standalone legal value
3. Ireland specifically requested by HN commenters
4. Phase 2 can add Revised Acts consolidated text for ~560 acts
5. Amendment annotations in Revised Acts could inform a future version-reconstruction effort

## 0.6 Scope estimate

| Metric | Value |
|--------|-------|
| Total Acts | ~4,041 |
| XML available | All Acts (1922–2025) |
| Constitution | HTML only (special case, handle separately or skip Phase 1) |
| Statutory Instruments | ~35,000 (HTML only, out of scope) |
| HTTP requests for full bootstrap | ~4,041 (ISB XML) + ~4,041 (Oireachtas API metadata) = ~8,100 |
| Estimated XML size | ~500 MB total (average ~125 KB/act, with outliers like Taxes at 6.4 MB) |
| Fetch time estimate (2 req/s, 8 workers) | ~30 min for API + ~30 min for XML ≈ 1 hour |
| Known blockers | None. No auth, no rate limits, no geo-blocking. |

### Daily update cadence

Ireland enacts ~30-50 acts per year. New acts appear on ISB within days of enactment. The Oireachtas API `last_updated` parameter works for incremental discovery. A weekly or monthly update cycle is sufficient.
