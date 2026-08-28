# RESEARCH-RO: Romania (legislatie.just.ro)

## 0.1 Source identification

**Primary source:** Portal Legislativ — legislatie.just.ro  
**Operator:** Ministry of Justice (Ministerul Justiției)  
**Base URL:** `https://legislatie.just.ro/`  
**Licensing:** Public domain. Art. 9(b) of Law 8/1996 (Copyright Law) explicitly excludes official legislative texts from copyright protection. Free redistribution without restrictions.

### Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/Public/DetaliiDocumentAfis/{ID}` | GET | Consolidated text of a law (HTML with semantic CSS classes) |
| `/Public/DetaliiDocument/{ID}` | GET | Detail page with metadata + version history ("istoric consolidări") |
| `/Public/DetaliiDocument/{ID}?isFormaDeBaza=True` | GET | Original (base) form of a law |
| `/Public/FormaPrintabila/{hash}` | GET | Printable form (clean layout) |
| `/Public/actiuniSuferite` | POST `{contor: ID}` | Modifications suffered by a law |
| `/Public/actiuniInduse` | POST `{contor: ID}` | Modifications induced by a law |
| `/apiws/FreeWebService.svc/SOAP` | SOAP | API with `GetToken()` + `Search()` (see below) |

### SOAP API (limited but functional for discovery)

**WSDL:** `http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl`  
**Client library:** zeep (suds is deprecated)  
**Official Python client:** `github.com/govro/legislatie-just-python-soap-client`

**Operations:**
- `GetToken()` → returns token string (expires after ~5 minutes)
- `Search(model, tokenKey)` → returns `list[Legi]`

**SearchModel fields:**

| Field | Type | Notes |
|---|---|---|
| `NumarPagina` | int | 1-indexed (page 0 = page 1, then 2, 3...) |
| `RezultatePagina` | int | Max 100 per page |
| `SearchAn` | string | Year filter (e.g., "2024") |
| `SearchNumar` | string | Law number filter |
| `SearchText` | string | Full-text search |
| `SearchTitlu` | string | Title search |

**Legi response fields:**

| Field | Example | Notes |
|---|---|---|
| `Titlu` | `"LEGE nr. 31..."` | Full title (includes BOM + whitespace noise) |
| `TipAct` | `"LEGE"`, `"CONSTITUȚIE"`, `"ORDIN"` | Act type in Romanian |
| `Numar` | `"31"` | Law number |
| `DataVigoare` | `"2003-10-31"` | Effective date (ISO format) |
| `Emitent` | `"Parlamentul"` | Issuing authority |
| `Publicatie` | `"Monitorul Oficial"` | Publication venue |
| `LinkHtml` | `"http://legislatie.just.ro/Public/DetaliiDocument/47355"` | URL with document ID |
| `Text` | (plain text, ~100KB) | Full text content (plain, no HTML structure) |

**SOAP API limitations:**
- Pagination quirk: page 0 and page 1 return identical results; real pages start at 1
- Max 100 results per page (undocumented)
- Token expires after ~5 minutes — must regenerate
- `Text` field is plain text (no HTML tags), unsuitable for structured parsing
- No `GetById` method — cannot fetch a specific document by ID
- Manual XML SOAP requests fail with 500; only works via zeep/suds libraries

### Rate limits and access

- **robots.txt:** Returns 302 redirect (effectively no robots.txt)
- **User-Agent required:** Bare curl returns 403 Forbidden. Must include browser-like User-Agent header.
- **No known rate limits:** No 429 responses observed during testing. Conservative approach: 2 req/s.
- **HTTPS only:** HTTP redirects to HTTPS.

### robots.txt access for AI crawlers

Not applicable — no robots.txt served. The site redirects `/robots.txt` to the homepage (302).

## 0.2 Representative fixtures

Saved in `engine/tests/fixtures/ro/`:

| File | Document | Type | ID | Size | Key features |
|---|---|---|---|---|---|
| `sample-constitution.html` | Constituția din 1991 (republicată) | CONSTITUȚIE | 47355 | 468 KB | 8 titles, 156 articles, clean structure |
| `sample-code.html` | Codul Civil din 2009 (republicat) | COD | 175630 | 6.8 MB | 2,664 articles, 39 titles, massive document |
| `sample-ordinary-law.html` | Legea nr. 31/1990 (republicată) | LEGE | 169688 | 1.6 MB | 397 articles, 592 cross-references, 44 historical versions |
| `sample-regulation.html` | HG nr. 611/2008 | HOTĂRÂRE | 227381 | 795 KB | 12 tables, 180 articles, multi-level structure |
| `sample-with-tables.html` | Codul Fiscal din 2015 | COD FISCAL | 171282 | 4.5 MB | 17 tables, 503 articles, 19 images, 150+ consolidated versions |
| `sample-detail-versions.html` | Legea 31/1990 (detail page) | — | 798 | 1.9 MB | Version history with 44 consolidated entries |

## 0.3 Metadata inventory

| Source field | Location | Type | Example | Maps to | Notes |
|---|---|---|---|---|---|
| Title | `span.S_DEN` | string | "CONSTITUȚIE*) din 21 noiembrie 1991 (*republicată*)" | `NormMetadata.title` | Strip `*` markers |
| Emitent (issuer) | `span.S_EMT_BDY > li` | string | "PARLAMENTUL" | `NormMetadata.department` | Inside `<li>` tag |
| Publication | `span.S_PUB_BDY` | string | "MONITORUL OFICIAL nr. 767 din 31 octombrie 2003" | `extra.publication_reference` | Full gazette reference |
| Publication date | parsed from S_PUB_BDY | date | 2003-10-31 | `NormMetadata.publication_date` | Parse from "din DD luna YYYY" |
| Document ID | URL path | int | 47355 | `NormMetadata.identifier` → `RO-47355` | Prefix with "RO-" for filesystem safety |
| Act type (TipAct) | `span.S_DEN` first word + SOAP | string | "CONSTITUȚIE", "LEGE", "HOTĂRÂRE" | `NormMetadata.rank` | |
| Number | parsed from S_DEN | string | "31" | `extra.act_number` | |
| Source URL | constructed | URL | `https://legislatie.just.ro/Public/DetaliiDocument/47355` | `NormMetadata.source` | |
| Consolidation history | `div.forme_act > a` | list | 44 versions with dates | Used for version extraction | Date format DD.MM.YYYY |
| Modifications suffered | AJAX `/Public/actiuniSuferite` | HTML | List of modifying acts | `extra.modifications_count` | Count only |
| Cross-references | `a[href*=DetaliiDocument]` in text | links | 592 in Companies Law | Preserved as Markdown links | |

**Fields from SOAP API (for discovery only):**

| SOAP field | Maps to | Notes |
|---|---|---|
| `TipAct` | `NormMetadata.rank` | Act type string |
| `Numar` | `extra.act_number` | |
| `DataVigoare` | `NormMetadata.publication_date` | ISO format from SOAP |
| `Emitent` | `NormMetadata.department` | |
| `Publicatie` | `extra.publication_venue` | |
| `LinkHtml` | Document ID extraction | Regex `DetaliiDocument/(\d+)` |

## 0.4 Formatting inventory

Based on analysis of all 5 fixtures:

- [x] **Tables** — 12 tables in HG 611/2008, 17 in Codul Fiscal. HTML `<table>` with `border: 1px solid black`, `rowspan`, `colspan`. Cell content uses `span.S_PAR`. No CSS classes on tables (except `S_EMT` for metadata).
- [x] **Bold** — 6 `<b>` elements per fixture (structural, e.g., breadcrumb labels). No inline `<strong>` in law text. Article titles are structurally bold via CSS.
- [ ] **Italic** — 0 italic elements found in any fixture. Not used by this source.
- [x] **Lists** — Extensive. Lettered subsections via `span.S_LIT` + `span.S_LIT_TTL` (e.g., `a)`, `b)`). Numbered paragraphs via `span.S_ALN` + `span.S_ALN_TTL` (e.g., `(1)`, `(2)`).
- [x] **Footnotes/notes** — `span.S_NTA` with `span.S_NTA_PAR` for note paragraphs. Usually modification notes ("Modificat prin Legea nr. ...").
- [x] **Links/cross-references** — Very abundant (9–592 per document). Format: `<a href="~/../../../Public/DetaliiDocumentAfis/{ID}">Legea nr. 429/2003</a>`. Convert `~/../../../` prefix to absolute URL.
- [ ] **Formulas** — Not found in any fixture.
- [ ] **Quotations** — Not explicitly marked (no blockquote tags).
- [x] **Attachments/annexes** — Present as additional blocks within the document. Some documents have image-based annexes (JPG facsimiles).
- [x] **Signatories** — Not explicitly tagged. Appear as regular paragraphs at end of document.
- [x] **Images** — 7-19 per fixture. Mix of decorative icons and content images (facsimile tables in some older regulations). Must be dropped with `extra.images_dropped` count.

### HTML content structure (semantic CSS classes)

The HTML uses well-structured semantic CSS classes for all structural elements:

| CSS class | Contains | Maps to | Markdown rendering |
|---|---|---|---|
| `S_DEN` | Document title/denomination | Title line | `# {text}` or frontmatter |
| `S_EMT` / `S_EMT_BDY` / `S_EMT_TTL` | Emitent (issuer) table | Metadata | Frontmatter |
| `S_PUB` / `S_PUB_BDY` / `S_PUB_TTL` | Publication reference | Metadata | Frontmatter |
| `S_TTL` / `S_TTL_TTL` / `S_TTL_DEN` / `S_TTL_BDY` | Titlu (Title I, II...) | `## {text}` | `titulo_tit` |
| `S_CAP` / `S_CAP_TTL` / `S_CAP_DEN` / `S_CAP_BDY` | Capitol (Chapter) | `### {text}` | `capitulo_tit` |
| `S_SEC` / `S_SEC_TTL` / `S_SEC_DEN` / `S_SEC_BDY` | Secțiune (Section) | `#### {text}` | `seccion` |
| `S_ART` / `S_ART_TTL` / `S_ART_DEN` / `S_ART_BDY` | Articol (Article) | `##### {text}` | `articulo` |
| `S_ALN` / `S_ALN_TTL` / `S_ALN_BDY` | Alineat - numbered paragraph (1), (2) | Body text with numbering | `parrafo` |
| `S_LIT` / `S_LIT_TTL` / `S_LIT_BDY` | Literă - lettered subsection a), b) | Body text with letter | `parrafo` |
| `S_PAR` | Paragraph (generic) | Body text | `parrafo` |
| `S_NTA` / `S_NTA_TTL` / `S_NTA_PAR` | Notă (modification note) | Blockquote or annotation | `parrafo` with `>` prefix |
| `S_LGI` | Legislative reference (inline) | Inline text | No special rendering |
| `TAG_COLLAPSED` | Expand/collapse toggle (UI) | Skip | — |

**Key parsing notes:**
- Each element has `_TTL` (title/label), `_BDY` (body), and optionally `_DEN` (denomination) sub-elements
- Collapsible UI elements (`TAG_COLLAPSED`, `plusMinus()`) are decoration — skip them
- Element IDs follow pattern `id_artA{N}`, `id_ttlA{N}`, `id_capA{N}` (N is sequential, not article number)
- `S_ART_DEN` contains the article's descriptive name (e.g., "Statul român") if it has one
- Style attributes (`display: block; color:black;`) are uniform — ignore them
- Comment nodes `<!---->` appear frequently — strip them

## 0.5 Version history spike — GATE: PASS

**Test law:** Legea nr. 31/1990 (Companies Law)  
**Source:** https://legislatie.just.ro/Public/DetaliiDocument/798  
**Evidence:** `tests/fixtures/ro/version-spike.txt`

**Result: 44 distinct consolidated versions extracted** with dates ranging from 04.06.1991 to 06.12.2024, plus 2 republications (1998, 2004).

**Version history access pattern:**
1. Load `/Public/DetaliiDocument/{base_id}` (the detail page)
2. Find all `<a>` elements inside `div.forme_act` containers
3. Each link has format: `DD.MM.YYYY` → `/Public/DetaliiDocument/{version_id}`
4. Load `/Public/DetaliiDocumentAfis/{version_id}` for the full text of each version
5. Parse date from link text, parse content from the DetaliiDocumentAfis page

**Strategy:** "Archived-version URLs" pattern (same as Belgium `be/`). Each consolidated version has its own document ID. The detail page provides the complete version timeline.

**Effective date source:** The consolidation date in the version history list (DD.MM.YYYY format). This is the date the consolidation was published, which corresponds to when the modification entered into force.

## 0.6 Scope estimate

**Estimated total laws:** ~150,000+ normative acts (per portal description). The SOAP API indexes documents from 1989 to present, plus some pre-1989 acts.

**Document ID range:** 1 to ~310,000 (not all IDs are base documents; many are consolidated versions of the same law).

**Types of acts included:** CONSTITUȚIE, LEGE (organic + ordinary), ORDONANȚĂ, ORDONANȚĂ DE URGENȚĂ, HOTĂRÂRE (government decision), DECRET, ORDIN (ministerial order), COD (code), REGULAMENT, NORMĂ, and many more.

**Estimated HTTP requests for full bootstrap:**
- Discovery: ~3,100 SOAP API calls (paginate by year × ~100 per page × 36 years)
- Version history: 1 request per base document (to get version list)
- Text fetch: 1 request per version (many laws have 1–50+ versions)
- Conservative estimate: 200,000–500,000 requests total
- At 2 req/s with 8 workers: ~7–17 hours

**Known blockers:**
- User-Agent header required (403 without it)
- SOAP API token expires after ~5 minutes
- Large documents (Codul Civil = 6.8 MB HTML, Codul Fiscal = 4.5 MB)
- Some documents contain image facsimiles instead of text (older norms)

## Pipeline strategy

### Discovery
1. Use SOAP API `Search()` to enumerate all document IDs, paginating by year (1989–2026)
2. Extract document IDs from `LinkHtml` field
3. Filter by act type to focus on substantive legislation (LEGE, COD, ORDONANȚĂ, HOTĂRÂRE, DECRET)

### Fetch
1. For each base document ID, scrape `/Public/DetaliiDocument/{ID}` to get:
   - Metadata (title, issuer, publication)
   - Version history (list of consolidated version IDs + dates)
2. For each version ID, scrape `/Public/DetaliiDocumentAfis/{ID}` to get the structured HTML text

### Parse
1. Extract metadata from `S_DEN`, `S_EMT_BDY`, `S_PUB_BDY` elements
2. Parse text structure using semantic CSS classes (`S_TTL`, `S_CAP`, `S_SEC`, `S_ART`, `S_ALN`, `S_LIT`, `S_PAR`, `S_NTA`)
3. Convert tables to Markdown pipe tables
4. Convert cross-reference links to Markdown links
5. Drop images and count them in `extra.images_dropped`

### Identifier format
`RO-{document_id}` (e.g., `RO-47355` for the Constitution). The document ID is a stable integer from the portal URL.

### Daily updates
The portal updates daily. Use `discover_daily()` to find laws published on a given date. The SOAP API can search by year; for daily granularity, scrape the portal's homepage or recent publications section. `generic_daily` should work since daily entries map 1:1 to consolidated laws.
