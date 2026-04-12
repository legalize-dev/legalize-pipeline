# RESEARCH-IT.md - Italy (Normattiva)

## 0.1 Source identification

| Field | Value |
|-------|-------|
| Country | Italy (IT) |
| Official name | Normattiva |
| URL | https://www.normattiva.it |
| OpenData API | https://api.normattiva.it/t/normattiva.api/bff-opendata/v1 |
| Operator | Istituto Poligrafico e Zecca dello Stato (IPZS) |
| Data format | Akoma Ntoso XML (OASIS LegalDocML 3.0) |
| Licensing | Open data (Italian Open Data License / CC-BY compatible) |
| Authentication | None required |
| Rate limits | Not documented; we use 2 req/s conservatively |

## 0.2 API endpoints

### Discovery (OpenData REST API)

All endpoints are POST with JSON body on `api.normattiva.it`:

| Endpoint | Purpose | Notes |
|----------|---------|-------|
| `/api/v1/ricerca/semplice` | Full-text search, paginated | text="*" returns all ~205K acts, 100/page |
| `/api/v1/ricerca/aggiornati` | Acts updated between two dates | For daily discovery |
| `/api/v1/atto/dettaglio-atto` | Single article detail | Returns one article at a time, NOT full text |
| `/api/v1/tipologiche/denominazione-atto` | Act type codes | 30 types (PLE, PLL, PDL, etc.) |
| `/api/v1/collections/collection-predefinite` | Predefined collections | ~370K total acts |

### Full text download (normattiva.it)

The OpenData API's `dettaglio-atto` only returns one article at a time. Full text must be obtained via the `caricaAKN` endpoint:

1. `GET /uri-res/N2Ls?{urn}` - Visit HTML page (sets session cookies)
2. Extract `caricaAKN` link from HTML page
3. `GET /do/atto/caricaAKN?dataGU=...&codiceRedaz=...&dataVigenza=...` - Returns full Akoma Ntoso XML

The `dataVigenza` parameter controls which historical version (multivigenza) is returned.

## 0.3 Metadata inventory

Fields available from AKN XML `<meta>` section:

| AKN field | Maps to | Notes |
|-----------|---------|-------|
| `FRBRWork/FRBRthis` | `akn_uri` (extra) | e.g. `/akn/it/act/legge/stato/2024-06-26/86/!main` |
| `FRBRWork/FRBRalias[@name='urn:nir']` | `source` URL, `urn_nir` (extra) | e.g. `urn:nir:stato:legge:2024-06-26;86` |
| `FRBRWork/FRBRalias[@name='eli']` | `eli` (extra) | European Legislation Identifier |
| `FRBRWork/FRBRdate` | emanation date | Date the act was signed |
| `FRBRWork/FRBRcountry` | `country` | Always "it" |
| `FRBRWork/FRBRauthor` | `department` | Issuing authority |
| `FRBRExpression/FRBRdate` | `expression_date` (extra) | Date of this consolidated version |
| `FRBRExpression/FRBRlanguage` | `language` (extra) | Always "ita" |
| `publication/@date` | `publication_date` | GU publication date |
| `publication/@number` | `gu_number` (extra) | GU issue number |
| `lifecycle/eventRef` | lifecycle events (extra) | Amendment history |
| `preface` (full text) | `title` | Act type + number + title |

From search API response:

| API field | Maps to | Notes |
|-----------|---------|-------|
| `codiceRedazionale` | `identifier` | Primary key, filesystem-safe (e.g. "24G00104") |
| `dataGU` | lookup param | GU date for caricaAKN URL |
| `titoloAtto` | title (fallback) | Short title |
| `denominazioneAtto` | act type | e.g. "PLE" (Legge), "PLL" (D.Lgs) |
| `descrizioneAtto` | title (formal) | e.g. "LEGGE 26 giugno 2024, n. 86" |
| `dataUltimaModifica` | last modified | For change detection |

## 0.4 Act type mapping

| API code | Description | Rank |
|----------|-------------|------|
| PLE | LEGGE | `legge` |
| PLL | DECRETO LEGISLATIVO | `decreto_legislativo` |
| PDL | DECRETO-LEGGE | `decreto_legge` |
| PLC | LEGGE COSTITUZIONALE | `legge_costituzionale` |
| COS | COSTITUZIONE | `costituzione` |
| PPR | DPR | `decreto_presidente_repubblica` |
| PCM_DPC | DPCM | `dpcm` |
| PDM | DECRETO MINISTERIALE | `decreto_ministeriale` |
| PRD | REGIO DECRETO | `regio_decreto` |
| PRL | REGIO DECRETO-LEGGE | `regio_decreto_legge` |
| D10 | REGOLAMENTO | `regolamento` |

## 0.5 Akoma Ntoso XML structure

```xml
<akomaNtoso xmlns="http://docs.oasis-open.org/legaldocml/ns/akn/3.0">
  <act>
    <meta>
      <identification>...</identification>
      <lifecycle>...</lifecycle>
      <publication date="..." number="..."/>
      <references>...</references>
    </meta>
    <preface>...</preface>
    <preamble>...</preamble>
    <body>
      <article eId="art_1">
        <num>Art. 1.</num>
        <heading>Title</heading>
        <paragraph eId="art_1__para_1">
          <num>1.</num>
          <content><p>Text with <ref href="...">cross-ref</ref>...</p></content>
        </paragraph>
      </article>
    </body>
    <conclusions>...</conclusions>
    <attachments>
      <attachment><doc><mainBody>...</mainBody></doc></attachment>
    </attachments>
  </act>
</akomaNtoso>
```

Articles may be nested inside structural elements: `<book>`, `<part>`, `<title>`, `<chapter>`, `<section>`.

Inline elements: `<ref>` (cross-references), `<ins>` (amendment markers), `<mod>` (modifications).

Tables are pre-formatted ASCII art inside `<table>/<tr>/<td>/<p>`.

## 0.5b Formatting inventory

Verified across 6 AKN XML fixtures (sample-legge-2024, sample-codice-penale, sample-decreto-legislativo, sample-decreto-legge, sample-legge-costituzionale, sample-with-tables):

- [x] **Tables** -- Present in attachments (Tabella A, B, etc.). Pre-formatted ASCII art inside `<table>/<tr>/<td>/<p>`. Rendered as pipe Markdown tables by parser.
- [ ] **Bold** -- Not present. AKN XML has no `<b>` or `<strong>` tags.
- [ ] **Italic** -- Not present. AKN XML has no `<i>` or `<em>` tags.
- [x] **Lists** -- Lettered sub-paragraphs (a), b), c)) rendered as indented Markdown lists.
- [ ] **Footnotes / endnotes** -- Not present in AKN format.
- [x] **Links** -- Cross-references via `<ref href="...">` tags. Preserved as Markdown links.
- [ ] **Formulas** -- Not present.
- [ ] **Quotations** -- Amendment markers `<ins>` with `((text))` convention; preserved as-is (standard Italian legislative convention).
- [x] **Attachments / annexes** -- Present in `<attachments>/<attachment>/<doc>`. Parsed as separate blocks.
- [x] **Signatories** -- Present in `<conclusions>` element. Rendered as a conclusions block.
- [ ] **Images** -- Not present in AKN format. No images to drop.

## 0.6 Key identifiers

- **codiceRedazionale**: Primary unique ID, filesystem-safe (e.g. "25G00211", "042U0262")
  - Format: 2-digit year + "G"/"U" + 5-digit number
- **URN NIR**: `urn:nir:stato:{tipo}:{data};{numero}` (e.g. `urn:nir:stato:legge:2024-06-26;86`)
- **ELI**: European Legislation Identifier

## 0.7 Quirks and limitations

1. **Single article API**: The `dettaglio-atto` endpoint returns only ONE article at a time, requiring the `caricaAKN` workaround for full text
2. **Session cookies**: The `caricaAKN` endpoint requires visiting the HTML page first to establish session cookies
3. **Codici (codes)**: Major codes (Codice Penale, Codice Civile) have their actual articles in linked sub-documents, not in the main AKN XML which only contains the enabling decree
4. **Pre-formatted tables**: Tables in the AKN XML are ASCII art inside `<table>/<tr>/<td>/<p>`, not structured HTML tables. This is the native format from Normattiva -- the parser preserves them as-is
5. **WAF protection**: Direct API calls to `dati.normattiva.it/api/` are blocked by WAF; must use `api.normattiva.it` gateway
6. **No bold/italic**: AKN samples contain no inline formatting tags (`<b>`, `<i>`, etc.)
7. **Historical versions**: Available via `dataVigenza` parameter (multivigenza system) - implemented as single-snapshot for v1. The caricaAKN endpoint accepts a `dataVigenza=YYYYMMDD` parameter that returns the consolidated text as of that date. Normattiva tracks all amendments through `lifecycle/eventRef` entries in the AKN XML metadata. Full version history is technically reachable but requires: (a) fetching the current version to discover amendment dates from lifecycle events, (b) re-fetching with each historical `dataVigenza`. Cost estimate: 2 HTTP requests per version per law. Follow-up task for v2.
8. **Flattened structural hierarchy**: Normattiva encodes all structural divisions (Titolo, Capo, Sezione) as `<chapter>` elements with compound headings (e.g. num="Titolo I" heading="... Capo I ..."), rather than using proper `<title>/<chapter>` nesting. The parser maps them to `###` heading level consistently

## 0.8 Estimated corpus size

- ~205K acts via search API
- Primary legislation types (Legge, D.Lgs, D-L, DPR, L.Cost, Costituzione): ~30K acts
- Full bootstrap at 2 req/s: estimated 4-8 hours for primary legislation
