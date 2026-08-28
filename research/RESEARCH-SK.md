# Research: Slovakia (SK) — Slov-Lex / e-Zbierka

## Source

| Field | Value |
|---|---|
| Name | Slov-Lex (e-Zbierka zákonov) |
| Operator | Ministry of Justice of the Slovak Republic |
| Portal | https://www.slov-lex.sk |
| Static site | https://static.slov-lex.sk |
| API gateway | https://api-gateway.slov-lex.sk |
| Authentication | None |
| Rate limits | No documented limits. No `X-RateLimit` headers. Response time ~50ms |
| License | Government public data. Slovak legislation is public domain per EU norms |
| Update cadence | Laws published as enacted. RSS feed at `vyhladavanie.slov-lex.sk/rss/predpisZbierky` |
| robots.txt | `Allow: /` (no restrictions). HTML pages have `<meta name="robots" content="noindex, nofollow">` but robots.txt permits crawling |

## Data format

- **API gateway**: JSON (Solr-backed, returns `numFound`, `start`, `docs[]`)
- **Law text**: HTML fragments from static site (`.portal` endpoint)
- **Version history**: HTML page with structured `data-*` attributes
- **PDF**: Available at predictable URLs (legally binding copy)
- **No XML** — the native format is semantic HTML with CSS classes

## Scope

| Type | Slovak name | Count (approx.) |
|---|---|---|
| Constitutional law | Ústavný zákon | ~100 |
| Law | Zákon | ~5,995 |
| Government regulation | Nariadenie vlády | ~2,000 |
| Ordinance | Vyhláška | ~8,000 |
| Notification | Oznámenie | ~3,000 |
| Finding | Nález | ~1,000 |
| Measure | Opatrenie | ~350 |
| Decision | Rozhodnutie | ~500 |
| Resolution | Uznesenie | ~500 |
| **Total** | | **~26,389** |

Year range: 1918–2026 (82 years with data).

## Endpoints used

### API Gateway — Discovery

| Endpoint | Method | Purpose |
|---|---|---|
| `/vyhladavanie/predpisZbierky/rozsirene` | GET | Paginated catalog. Params: `rows`, `start`, `typPredp`, `rocnik`, `cislo` |
| `/vyhladavanie/predpisZbierky/znenie` | GET | Resolve current version IRI. Params: `predpis` (IRI base), `zodpovedajucaUcinnost` (date) |

Example catalog request:
```
GET https://api-gateway.slov-lex.sk/vyhladavanie/predpisZbierky/rozsirene?rows=5000&start=0
```

Response:
```json
{
  "numFound": 26389,
  "start": 0,
  "docs": [
    {
      "iri": "/SK/ZZ/2026/55/20260410",
      "vyhlaseny": "2026-04-10T00:00:00Z",
      "typPredp": "Oznamenie",
      "typPredp_value": "Oznámenie",
      "rocnik": "2026",
      "nazov": "Oznámenie...",
      "cislo": "55/2026 Z. z.",
      "ucinnyOd": "2026-04-10T00:00:00Z",
      "zodpovedajucaUcinnost": "2026-04-13T00:00:00Z",
      "nadpisy": ["heading 1", ...]
    }
  ]
}
```

Pagination: supports up to 5,000 rows per request. With ~26K total, 6 requests cover the full catalog.

### Static Site — Version History & Text

| URL pattern | Purpose |
|---|---|
| `static.slov-lex.sk/static/SK/ZZ/{year}/{number}/` | Version history page (all versions listed) |
| `static.slov-lex.sk/static/SK/ZZ/{year}/{number}/{YYYYMMDD}.portal` | Law text HTML fragment for a specific version |
| `static.slov-lex.sk/static/SK/ZZ/{year}/{number}/{YYYYMMDD}.html` | Full HTML page for a specific version |
| `static.slov-lex.sk/static/pdf/SK/ZZ/{year}/{number}/ZZ_{year}_{number}_{YYYYMMDD}.pdf` | Legally binding PDF |

### RSS — Daily Updates

```
GET https://vyhladavanie.slov-lex.sk/rss/predpisZbierky
```
Returns last 20 published laws with `<title>`, `<description>`, `<link>`, `<pubDate>`.

## Version history

**Full point-in-time versions available.** This is the ideal case for our pipeline.

The version history page for each law contains `<tr class="effectivenessHistoryItem">` rows with:
- `data-iri`: version IRI (e.g., `/SK/ZZ/1992/460/19921001`)
- `data-ucinnostod`: effective date from (ISO: `1992-10-01`)
- `data-ucinnostdo`: effective date to (ISO: `1998-08-04`, empty = current)
- `data-vyhlasene`: `"1"` for the proclaimed version, `"0"` for consolidated
- Amendment references as `<a>` links in the third `<td>` cell

Example: Constitution 460/1992 has **29 versions** from 1992 to 2025.

Strategy:
1. Parse the version history HTML page for each law
2. Extract all `effectivenessHistoryItem` rows
3. For each version, download the `.portal` text fragment
4. Each version becomes a git commit with `GIT_AUTHOR_DATE` = effective date

The `data-iri` contains the date suffix (YYYYMMDD) needed to construct the `.portal` URL.

## Metadata inventory

### From API Gateway (`rozsirene` response)

| Source field | Type | Example | Maps to | Notes |
|---|---|---|---|---|
| `iri` | string | `/SK/ZZ/2024/401/20250301` | internal | Includes version date |
| `nazov` | string | `"Zákon, ktorým..."` | `NormMetadata.title` | Full title |
| `cislo` | string | `"401/2024 Z. z."` | `NormMetadata.identifier` | Official citation number |
| `typPredp` | string | `"Zakon"` | `NormMetadata.rank` | Machine-readable type code |
| `typPredp_value` | string | `"Zákon"` | `extra.type_display` | Human-readable type name |
| `rocnik` | string | `"2024"` | `extra.year` | Publication year |
| `vyhlaseny` | datetime | `"2024-12-27T00:00:00Z"` | `NormMetadata.publication_date` | Promulgation date |
| `ucinnyOd` | datetime | `"2025-03-01T00:00:00Z"` | `extra.effective_from` | Effective date |
| `ucinnyDo` | datetime | (empty if current) | `extra.effective_to` | Effective until |
| `zodpovedajucaUcinnost` | datetime | `"2026-04-13T00:00:00Z"` | internal | Queried effectiveness date |
| `nadpisy` | list[str] | `["Prechodné ustanovenie..."]` | `extra.headings` | Section headings |

### From Static Site (`InfoTable` in `.portal` page)

| Source field | Type | Example | Maps to | Notes |
|---|---|---|---|---|
| Číslo predpisu | string | `460/1992 Zb.` | `NormMetadata.identifier` | Confirms catalog |
| Názov | string | `Ústava Slovenskej republiky` | `NormMetadata.short_title` | Short name |
| Typ | string | `Ústavný zákon` | `NormMetadata.rank` | Localized type |
| Dátum schválenia | date | `01.09.1992` | `extra.approval_date` | Approval date |
| Dátum vyhlásenia | date | `01.10.1992` | `NormMetadata.publication_date` | Promulgation date |
| Dátum účinnosti od | date | `01.10.1992` | `extra.effective_from` | Effective from |
| Dátum účinnosti do | date | (empty) | `extra.effective_to` | Effective to |
| Autor | string | varies | `NormMetadata.department` | Authoring body |
| Právna oblasť | string | varies | `NormMetadata.subjects` | Legal area |
| Čiastka | string | varies | `extra.gazette_issue` | Gazette issue number |

### Relationships (from `#Vztahy` section)

| Relation | Maps to | Notes |
|---|---|---|
| Vykonávacie predpisy | `extra.implementing_regulations` | Count only |
| Predpis je menený | `extra.amended_by` | Amendment references |
| Predpis ruší | `extra.repeals` | Repeal references |

## Formatting inventory

Based on analysis of 5 sample laws (Constitution 460/1992, Labour Code 311/2001, Income Tax Act 595/2003, Civil Code 40/1964, Social Insurance Act 461/2003):

| Construct | Present? | Source format | Handling |
|---|---|---|---|
| **Tables** | Yes | `<table border="1">` with `<tr>/<td>` | Convert to Markdown pipe tables |
| **Bold** | Yes | `<b>` tags in text | Convert to `**...**` |
| **Italic** | No | Not observed in samples | N/A |
| **Lists** | Yes | `pismeno` (letter) and `bod` (point) CSS classes | Hierarchical structure via nesting |
| **Cross-references** | Yes | `<a class="citacnyOdkazJednoduchy">` links | Convert to `[text](url)` |
| **Quotations** | Yes | `<div class="citat">` blocks | Convert to `> ...` blockquote |
| **Footnotes** | No | Not observed | N/A |
| **Formulas** | No | Not observed | N/A |
| **Images** | No | Not observed | Skip per policy |
| **Signatories** | No | Not present in consolidated text | N/A |
| **Modification markers** | Yes | CSS classes `modified`, `toBeModified` | Log only, don't render |
| **Line breaks** | Yes | `<br class="auto-merge">` | Convert to paragraph breaks |

### CSS class hierarchy (semantic structure)

```
predpis Skupina          → root document
├── predpisOznacenie     → law number ("460")
├── predpisTyp           → law type ("ÚSTAVA")
├── predpisPodnadpis     → subtitle ("SLOVENSKEJ REPUBLIKY")
├── predpisDatum         → date ("z 1. septembra 1992")
├── text                 → body text (preamble, article text)
├── hlava Skupina        → head/part (PRVÁ HLAVA)
│   ├── hlavaOznacenie   → part label
│   ├── hlavaNadpis      → part title
│   └── oddiel Skupina   → division/section
│       ├── oddielOznacenie → section label
│       ├── oddielNadpis → section title
│       └── ustavnyclanok Skupina (or clanok/paragraf) → article
│           ├── ustavnyclanokOznacenie → article number ("Čl. 1")
│           ├── ustavnyclanokNadpis    → article title
│           └── odsek Skupina          → paragraph
│               ├── odsekOznacenie     → paragraph number ("(1)")
│               ├── text               → paragraph text
│               └── pismeno Skupina    → letter item
│                   ├── pismenoOznacenie → letter ("a)")
│                   └── bod Skupina     → point item
│                       └── bodOznacenie → point number ("1.")
├── blokTextu            → free text block
├── citacnyOdkazJednoduchy → cross-reference link
└── citat                → quoted/cited text
```

Regular laws use `paragraf` and `clanok` instead of `ustavnyclanok`.

## Identifier format

The official citation format is `{number}/{year} Z. z.` (e.g., `460/1992 Zb.` for pre-1993 or `311/2001 Z. z.` for post-1993).

For filesystem-safe identifiers: `ZZ-{year}-{number}` (e.g., `ZZ-1992-460`, `ZZ-2001-311`).

The IRI path is `/SK/ZZ/{year}/{number}` which naturally maps to this.

## Estimated scope

- **26,389 laws** in the catalog (all types)
- **Versions per law**: varies widely. Constitution has 29. Average estimated ~3-5 for laws with amendments
- **Estimated total versions**: ~80,000-130,000
- **HTTP requests for full bootstrap**: ~26K (catalog) + ~26K (history pages) + ~100K (version texts) ≈ 150K requests
- **At 2 req/s per worker × 4 workers = ~8 req/s**: ~150K / 8 = ~5.2h fetch time
- **Text size**: Constitution portal = 648KB, Tax law = 3MB. Average ~200KB per version
- **Estimated total download**: ~20-25 GB
- **Known blockers**: None. No auth, no rate limits, no geo-blocking
