# RESEARCH-NO.md — Norway

**Date:** 2026-04-13
**Country code:** `no`
**ISO 3166-1:** NO (Norway / Norge)

## 0.1 Data sources

### Primary: Lovdata Public Data API

- **Maintainer:** Lovdata (private foundation, appointed by Ministry of Justice)
- **URL:** https://api.lovdata.no
- **Format:** XML-compatible HTML (<!DOCTYPE html>), compressed as tar.bz2 archives
- **License:** NLOD 2.0 (Norwegian Licence for Open Government Data) — free for all purposes with attribution
- **Auth:** Public data endpoints require **no authentication**
- **Content:** 781 consolidated laws (lover) + 3,729 central regulations (sentrale forskrifter)
- **Rate limits:** N/A for public data (bulk download, not per-request)
- **Scraping policy:** "Lovdata does not allow indexing or mass downloading from its website" — but public data API is explicitly provided for bulk access

**Public data endpoints (no auth, tested 2026-04-13):**

```
GET /v1/publicData/list                              → JSON array of available packages
GET /v1/publicData/get/gjeldende-lover.tar.bz2       → 781 current laws (5.6 MB)
GET /v1/publicData/get/gjeldende-sentrale-forskrifter.tar.bz2 → 3,729 regulations (20 MB)
GET /v1/publicData/get/lovtidend-avd1-2001-2025.tar.bz2 → gazette 2001-2025 (66 MB)
GET /v1/publicData/get/lovtidend-avd1-2026.tar.bz2  → gazette current year (496 KB)
```

All packages last updated 2026-04-11, refreshed daily.

### Authenticated API (requires API key — returns 401 without)

**Tested 2026-04-13 — all return 401:**
- `/documentHistory?refID=lov/2005-05-20-28` — version change log
- `/v1/structuredRules/list` — list available structured rules
- `/v1/structuredRules/timeline/{base}/{ruleFile}` — list all versions
- `/v1/structuredRules/get/{base}/{ruleFile}/{date}` — point-in-time consolidated text
- `/listBase?base=NL` — list all documents in a legal source
- `/renderRefID?refID=lov/...` — render document as HTML

**Auth methods:** X-API-Key header or Basic Auth.
**Rate limits:** X-RateLimit-Limit/Remaining/Reset headers. 429 on excess.

The API key appears to be free (documentation says NLOD 2.0 and "free for all purposes"). Contact: api@lovdata.no

### ELI (European Legislation Identifier)

- **URL:** https://lovdata.no/eli/{type}/{year}/{month}/{day}/{number}
- **Status:** Beta (since 2016, all 3 pillars implemented)
- **Tested:** `lovdata.no/eli/lov/2005/05/20/28` → 200, HTML with RDFa metadata
- **Point-in-time:** ELI spec supports it, but unclear if Lovdata's beta implements it

### Norsk Lovtidend (Norwegian Legal Gazette)

The gazette contains **amendment texts** (what each new law changes), not consolidated text. Available as XML from 2001 in the public data dump. Useful for:
- Daily discovery of new amendments
- Tracking which laws were modified and when
- NOT useful for reconstructing full consolidated historical text

### Stortinget API

- **URL:** https://data.stortinget.no
- Covers bills, debates, votes — but NOT enacted law text
- Supplementary only (parliamentary metadata)

## 0.2 Fixtures

Saved under `/private/tmp/no-research/nl/` (from public data dump):

| File | Law | Features |
|------|-----|----------|
| `nl-18140517-000.xml` | Kongeriket Norges Grunnlov (Constitution, 1814) | Highest rank, chapters, sections, rich cross-refs |
| `nl-20050520-028.xml` | Straffeloven (Penal Code, 2005) | 370 changesToParent entries, 1,790 cross-ref links, lists |
| `nl-19970228-019.xml` | Folketrygdloven (National Insurance Act, 1997) | EEA references, large law, many amendments |
| `nl-20080515-035.xml` | Utlendingsloven (Immigration Act, 2008) | 2 tables, EU regulation refs |
| `nl-18140517-000-nn.xml` | Grunnlova (Constitution, Nynorsk) | Only Nynorsk file in dataset |

Also: `/private/tmp/no-research/lti/2026/nl-20260410-013.xml` — Lovtidend amendment entry showing amendment structure (`changesToDocuments`, `document-change`, `change` elements with `data-change-part` attributes).

## 0.3 Metadata inventory

Source format: HTML `<header><dl class="data-document-key-info">` with `<dt class="KEY">` / `<dd class="KEY">`.

| Source field (class) | Type | Example | Maps to | Notes |
|---|---|---|---|---|
| `title` | string | "Lov om straff (straffeloven)" | `NormMetadata.title` | |
| `titleShort` | string | "Straffeloven – strl." | `NormMetadata.short_title` | Contains abbreviation after "–" |
| `legacyID` | string | "LOV-2005-05-20-28" | `NormMetadata.identifier` | Filesystem-safe: `LOV-2005-05-20-28` |
| `dokid` | string | "NL/lov/2005-05-20-28" | `extra.dokid` | FRBR expression ID |
| `refid` | string | "lov/2005-05-20-28" | `extra.refid` | FRBR work ID |
| `ministry` | string | "Justis- og beredskapsdepartementet" | `NormMetadata.department` | |
| `dateInForce` | string | "2015-10-01, 2008-03-07" | `extra.date_in_force` | Can be multiple dates or "Kongen bestemmer" |
| `lastChangeInForce` | date | "2026-04-10" | `NormMetadata.last_modified` | Date of last amendment entry into force |
| `lastChangedBy` | string | "lov/2026-04-10-13" | `extra.last_changed_by` | Ref to amending law |
| `dateOfPublication` | date | "2005-05-20" | `NormMetadata.publication_date` | Not always present (old laws) |
| `legalArea` | list | "Strafferett" | `NormMetadata.subjects` | Hierarchical: "Parent > Child" |
| `changesToDocuments` | list | "lov/1902-05-22-10" | `extra.changes_to` | Laws this one replaces |
| `eeaReferences` | string | "EØS-avtalen vedlegg VI..." | `extra.eea_references` | EEA agreement refs |
| `miscInformation` | string | "Jf. tidligere..." | `extra.misc_information` | Free text with cross-refs |
| `lastupdated` | string | "2023-01-12 (fjernet...)" | `extra.last_updated_note` | Editorial note, not legal date |
| `basedOn` | list | (regulations only) | `extra.based_on` | Legal basis for regulations |
| `subunit` | string | (regulations only) | `extra.subunit` | Issuing organizational unit |
| `journalNumber` | string | "2026-0333" | `extra.journal_number` | Lovtidend only |
| `a11yStatus` | string | "Mangler vurdering." | (skip) | Accessibility status, not legal metadata |

**Identifier choice:** Use `legacyID` → `LOV-2005-05-20-28` for laws, `FOR-2026-03-27-501` for regulations. Already filesystem-safe (uppercase, dashes, digits only).

## 0.4 Formatting inventory

Checked across 5 sample laws and full corpus scan (781 laws):

- [x] **Tables** — 7 of 781 laws have `<table>` elements. Standard HTML with `<thead>`, `<tbody>`, `<th>`, `<td>`. Attributes: `data-text-align`, `data-vertical-align`. No rowspan/colspan observed. Simple pipe tables will suffice.
- [x] **Bold** — `<b>` tags present but very rare (4 in Straffeloven). Used for emphasis in section text.
- [x] **Italic** — `<i>` tags, rare (1 in Straffeloven). Used for references to previous laws.
- [x] **Lists** — `<ul>` and `<ol>` with `<li>`, frequent (217 in Straffeloven). Used for enumerated conditions, lists of exceptions.
- [x] **Links** — `<a href="lov/...">` cross-references, very frequent (1,790 in Straffeloven). Reference format: `lov/YYYY-MM-DD-NNN` or `forskrift/YYYY-MM-DD-NNN`.
- [ ] **Footnotes** — Very rare (1 footnote-like class in Straffeloven). Not a significant concern.
- [x] **Amendment history** — `<article class="changesToParent">` entries listing all modifications. 370 entries in Straffeloven. Contains dates, amending law refs, and in-force dates.
- [ ] **Blockquotes** — Not observed in sample.
- [ ] **Formulas** — Not observed.
- [ ] **Images** — Not observed.
- [ ] **Signatories** — Not in consolidated text (would be in Lovtidend gazette entries).

### HTML structure

```
<article class="legalArticle" data-name="§1" id="kapittel-1-...-paragraf-1">
  <h4 class="legalArticleHeader">
    <span class="legalArticleValue">§ 1</span>.
    <span class="legalArticleTitle">Section Title</span>
  </h4>
  <article class="legalP" id="...-ledd-1">Paragraph text...</article>
  <article class="legalP" id="...-ledd-2">Second paragraph...</article>
  <article class="changesToParent">Endret ved lov ...</article>
</article>
```

**CSS classes → semantic mapping:**
- `legalArticle` → section (§)
- `legalP` → paragraph (ledd)
- `legalArticleHeader` → section heading
- `legalArticleValue` → section number
- `legalArticleTitle` → section title
- `changesToParent` → amendment history (strip from body, use for reform tracking)
- `section` with `data-name="kapI"` → chapter
- `defaultP` → regular paragraph
- `listArticle` → list item content
- `document-change` → amendment text (in Lovtidend)
- `futureLegalArticle` → proposed new section text (in Lovtidend)

## 0.5 Version history spike

### What the public data gives us

The consolidated laws embed **amendment history** in `changesToParent` elements:

```
Endret ved lover 17 juni 2005 nr. 90 (ikr. 1 jan 2008 iflg. res. 26 jan 2007 nr. 88)
```

This tells us:
- **Amending law:** lov 17 juni 2005 nr. 90 → `lov/2005-06-17-90`
- **In-force date:** 1 jan 2008 → `2008-01-01`
- **Resolution:** res. 26 jan 2007 nr. 88 → `forskrift/2007-01-26-88`

From Straffeloven alone: 370 changesToParent entries → hundreds of distinct reform dates.

**However:** The public data dump only contains the **current consolidated text**. We know WHEN every reform happened, but we do NOT have the full text at each historical point.

### What the authenticated API gives us

The `/v1/structuredRules/timeline/{base}/{ruleFile}` endpoint lists all available versions, and `/v1/structuredRules/get/{base}/{ruleFile}/{date}` returns the full consolidated text at any point in time.

This is the **Point-in-time API** strategy (same as UK legislation.gov.uk).

### GATE STATUS: ⚠️ CONDITIONAL PASS

- We CAN extract reform dates from public data (changesToParent parsing) → dates confirmed
- We CANNOT extract historical text without an API key
- **Action required:** Email api@lovdata.no to request API key before proceeding to implementation
- **If API key obtained:** Full point-in-time bootstrap (preferred)
- **If API key denied:** Single-snapshot bootstrap with reform dates only (acceptable — similar to Germany's initial ship). Document as temporary, with follow-up to add history.

### Version spike evidence (from public data)

**Law: Straffeloven (lov/2005-05-20-28)**

| Version | In-force date | Amending law | Source |
|---------|--------------|--------------|--------|
| Original | 2005-05-20 | (enacted) | dateOfPublication |
| Amendment 1 | 2008-01-01 | lov/2005-06-17-90 | changesToParent, ikr. date |
| Amendment 2 | 2009-01-01 | lov/2008-06-27-53 | changesToParent, ikr. date |
| Amendment 3 | 2008-03-07 | lov/2005-12-21-131 | changesToParent |
| ... | ... | ... | ... |
| Latest | 2026-04-10 | lov/2026-04-10-13 | lastChangedBy |

370 changesToParent entries in Straffeloven alone confirm reform tracking is feasible.

## 0.6 Scope estimate

### Phase 1: Laws (lover) only

| Metric | Value |
|--------|-------|
| Total laws | 781 |
| Archive size (compressed) | 5.6 MB |
| Archive size (uncompressed) | 50.9 MB |
| Nynorsk variants | 1 (Constitution only) |
| Laws with tables | 7 |
| Date range | 1687 – 2026 |

**Without API key (single-snapshot):**
- 1 HTTP request to download archive
- Extract + process 781 files
- Estimated bootstrap time: < 10 minutes

**With API key (full history):**
- 781 laws × avg ~10 versions = ~7,800 HTTP requests
- At 2 req/s = ~1 hour for full bootstrap
- Need to benchmark actual rate limits with API key

### Phase 2 (optional): Central regulations (forskrifter)

| Metric | Value |
|--------|-------|
| Total regulations | 3,729 |
| Archive size (compressed) | 20 MB |
| Date range | 1890s – 2026 |

### Daily updates

Two strategies available:
1. **Re-download full archive** (5.6 MB laws, 20 MB regulations) and diff against local state — simple, similar to `lovlig` Python package approach
2. **Download current year Lovtidend** and use `changesToDocuments` to identify which laws were modified — more targeted

## Norwegian legal hierarchy

| Rank | Norwegian | Example | Count in dataset |
|------|-----------|---------|-----------------|
| Constitution | Grunnlov | Kongeriket Norges Grunnlov (1814) | 1 (+1 Nynorsk) |
| Act/Statute | Lov | Straffeloven, Folketrygdloven | 780 |
| Regulation | Forskrift | Various ministerial regulations | 3,729 (Phase 2) |

**Naming convention:** `{type} {day}. {month} {year} nr. {number}`
- Example: "Lov 20. mai 2005 nr. 28 om straff"
- Legacy ID: `LOV-2005-05-20-28`
- File ID: `LOV-2005-05-20-28` (already filesystem-safe)

**Language:** Bokmål (official standard, used in 780/781 files). Nynorsk variant exists only for the Constitution.

## Key decisions needed

1. **API key:** Email api@lovdata.no to request free API key. This unlocks historical versions (point-in-time) and is the difference between a full-history bootstrap and a single-snapshot.

2. **Scope:** Start with 781 laws only (Phase 1). Regulations can be added later in Phase 2.

3. **Identifier format:** Use `legacyID` as-is → `LOV-2005-05-20-28`. Already uppercase with dashes, unique, stable.

4. **Nynorsk:** Skip the single Nynorsk Constitution variant. Only publish Bokmål (the default/majority language).

5. **Amendment history in output:** Strip `changesToParent` from body text (it's editorial, not the law itself) but parse it for reform date tracking.

## Architecture notes for implementation

**Best case (with API key):**
- `client.py`: HTTP client wrapping authenticated Lovdata API
- `discovery.py`: `/v1/structuredRules/list/NL` for all law IDs, or parse public dump filenames
- `parser.py`: Parse XML-HTML format → Blocks/NormMetadata
- Version strategy: Point-in-time API (`/v1/structuredRules/timeline` + `/get/{base}/{ruleFile}/{date}`)

**Fallback (public data only):**
- `client.py`: Download and extract public tar.bz2 archive (like France's local LEGI dump pattern)
- `discovery.py`: List files in extracted directory
- `parser.py`: Same parser, single-version output
- Version strategy: Single-snapshot with `changesToParent` dates as `extra.reform_dates`

## References

- Lovdata public data API: https://api.lovdata.no
- API documentation (Swagger): https://api.lovdata.no/swagger/index.html
- Data.norge.no dataset: https://data.norge.no/en/datasets/c0c6a87c-f597-3735-965f-650be23426a0
- ELI implementation: https://lovdata.no/eli
- `lovlig` Python package (reference client): https://pypi.org/project/lovlig/
- GlobaLex Norway guide: https://www.nyulawglobal.org/globalex/Norway1.html
- Lovdata info (English): https://lovdata.no/info/information_in_english
