# RESEARCH-DK.md — Denmark (Retsinformation)

## Source identification

**Portal:** [retsinformation.dk](https://www.retsinformation.dk) — the official Danish
legal information system, managed by Civilstyrelsen (Danish Civil Agency).

**License:** Public domain under Danish Copyright Act (Lov om ophavsret), section 9:
laws, administrative orders, judicial decisions and similar official publications are
not protected by copyright.

**Technical operator:** Schultz (contractor for Civilstyrelsen).

## APIs and data access

### A. ELI XML — primary data source (no auth)

Each document on retsinformation.dk is available as XML via European Legislation
Identifier (ELI) URLs:

```
# By accession number (most stable):
GET https://www.retsinformation.dk/eli/accn/{ACCN}/xml

# By Lovtidende A number:
GET https://www.retsinformation.dk/eli/lta/{YEAR}/{NUMBER}/xml
```

Returns LexDania 2.1 XML (proprietary Danish legal XML schema). No authentication.
No documented rate limit, but Cloudflare protects the site — use a real User-Agent.

**Schema reference:** `http://www.retsinformation.dk/offentlig/xml/schemas/2022/05/17/`

### B. Harvest API ("Høsteservice") — daily updates (no auth)

```
GET https://api.retsinformation.dk/v1/Documents?date=YYYY-MM-DD
```

Returns JSON array of documents changed since the given date (max 10 days back).
Operating hours: 03:00–23:45 Danish time. Rate limit: 1 request per 10 seconds.

Response fields: `documentId`, `accessionsnummer`, `reasonForChange`, `changeDate`,
`documentType`, `href` (ELI XML URL).

`reasonForChange` enum: `NewDocument`, `DocumentMetadataChanged`,
`DocumentContentChanged`, `DocumentMetadataChangedAndDocumentContentChanged`,
`RemovedDocument`.

### C. Metadata API — relationship data (no auth)

```
GET https://www.retsinformation.dk/api/document/metadata/{ACCN}
```

Returns JSON with `schemaOrgMetadata` (stringified JSON-LD) containing:
- `legislationConsolidates` — links to previous LBK and incorporated amendments
- `@reverse.isBasedOn` — all documents that reference this law
- `legislationType`, `legislationLegalForce`, `legislationIdentifier`

**This is the key to version history reconstruction** (see Version History section).

### D. Sitemap — discovery (no auth)

```
GET https://www.retsinformation.dk/sitemap.xml   → index of 21 sub-sitemaps
GET https://www.retsinformation.dk/sitemap.xml?page={N}  → URLs with lastmod dates
```

Total: ~192,666 documents across all types.

### E. SOAP Webservice — NOT usable

`https://services.retsinformation.dk` requires OCES certificate (Danish PKI) and
a contract with Civilstyrelsen. Not viable for Legalize.

## Document types

The sitemap contains these ELI path prefixes:

| Prefix | Count | Description |
|--------|-------|-------------|
| `eli/retsinfo/` | 74,311 | Administrative guidance, circulars |
| `eli/lta/` | 62,913 | **Lovtidende A: laws, consolidated acts, executive orders** |
| `eli/ft/` | 41,324 | Parliamentary documents (Folketinget) |
| `eli/mt/` | 6,434 | Ministertidende (ministerial gazette) |
| `eli/ltc/` | 4,776 | Lovtidende C (EU-related) |
| `eli/fob/` | 2,864 | Ombudsman reports |
| `eli/ltb/` | 44 | Lovtidende B (treaties) |

**Target for Legalize:** `eli/lta/` documents (62,913), filtered by document type:

| DocumentType | Code | Description | Scope |
|---|---|---|---|
| `LOV H` | LOKDOK01 | Original law (hovedtekst) | Include |
| `LOV Æ` | LOKDOK02 | Amendment law (ændringslov) | Skip (instructions only) |
| `LBK H` | LOKDOK03 | **Consolidated law (lovbekendtgørelse)** | **Primary target** |
| `BEK H` | LOKDOK04 | Executive order (bekendtgørelse) | Include (Rank B) |
| `BEK Æ` | — | Amendment to executive order | Skip |
| `Lov` | — | Very old law (pre-LexDania) | Include if has body |

**Primary scope:** LBK H (consolidated laws) + LOV H (original laws without LBK).
LBK documents contain the full amended text at a point in time — each is a version.

## XML structure (LexDania 2.1)

```xml
<Dokument>
  <Meta>
    <DocumentType>LBK H#LOKDOK03</DocumentType>
    <Rank>A</Rank>                          <!-- A=law, B=executive order -->
    <AccessionNumber>A20240043429</AccessionNumber>  <!-- unique ID -->
    <DocumentTitle>Bekendtgørelse af straffeloven</DocumentTitle>
    <Year>2024</Year>
    <Number>434</Number>
    <DiesSigni>2024-04-25</DiesSigni>       <!-- date of signing -->
    <StartDate>2024-05-01</StartDate>       <!-- entry into force -->
    <EndDate>2024-11-08</EndDate>           <!-- end of validity -->
    <Status>Historic|Valid</Status>
    <PopularTitle>Straffeloven</PopularTitle>
    <Ministry>Justitsministeriet</Ministry>
    <AdministrativeAuthority>...</AdministrativeAuthority>
    <Change id="change_1" />                <!-- amendment references -->
    <Ref_Accn REFid="change_1">A20240048130</Ref_Accn>
    <Ref_Af REFid="change_1">2024-05-22</Ref_Af>
    <Ref_Text REFid="change_1">Lov om ændring af...</Ref_Text>
    <Signature>...</Signature>
    <JournalNumber>...</JournalNumber>
  </Meta>
  <TitelGruppe>
    <Titel><Linea><Char>Title text</Char></Linea></Titel>
  </TitelGruppe>
  <DokumentIndhold>
    <Indledning>...</Indledning>            <!-- LBK introduction -->
    <Bog>                                   <!-- Book (optional) -->
      <Afsnit>                              <!-- Part/Section -->
        <Kapitel>                           <!-- Chapter -->
          <Explicatus>Kapitel 1</Explicatus>
          <Rubrica><Linea><Char>Title</Char></Linea></Rubrica>
          <ParagrafGruppe>
            <Paragraf id="Par1">            <!-- Article/Section (§) -->
              <Explicatus>§ 1.</Explicatus>
              <Stk id="Par1_Stk1">          <!-- Subsection -->
                <Explicatus>Stk. 2.</Explicatus>  <!-- subsec number -->
                <Exitus>
                  <Linea><Char>Text...</Char></Linea>
                </Exitus>
              </Stk>
            </Paragraf>
          </ParagrafGruppe>
        </Kapitel>
      </Afsnit>
    </Bog>
  </DokumentIndhold>
  <UnderskriftGruppe>...</UnderskriftGruppe>
</Dokument>
```

### Hierarchy mapping (Danish → block_type → heading)

| Danish element | block_type | Heading level |
|---|---|---|
| `Bog` | book | # |
| `Afsnit` | part | ## |
| `Kapitel` | chapter | ### |
| `ParagrafGruppe > Rubrica` | section_heading | #### |
| `Paragraf` | article | ##### |
| `Stk` | (content inside Paragraf) | — |

### Rich formatting

| Source construct | Occurrences (straffeloven) | Markdown output |
|---|---|---|
| `<Table>/<Tr>/<Td>` | 2 tables, 40 rows | Pipe table |
| `<Char formaChar="Bold">` | 2 | `**text**` |
| `<Char formaChar="Italic">` | 1 | `*text*` |
| `<Nota>` (footnotes) | 41 | Footnote markers + text |
| `<Indentatio>` (indented lists) | 286 | `- item` |
| `<Bilag>` (annexes) | In LOV Æ documents | Annex section |
| `<Index>` (index items) | 7 | Numbered list items |

**Note:** `<Char signiChar="AendringURN">` marks amendment cross-references in LOV Æ
documents (94 occurrences in the test fixture). These should be rendered as italic.

## Metadata inventory

| XML field | Legalize field | Notes |
|---|---|---|
| `AccessionNumber` | `identifier` | Unique ID (e.g. A20240043429) |
| `DocumentTitle` | `title` | Full official title |
| `Rank` | (infer from rank) | A=law, B=bekendtgørelse |
| `DocumentType` | `rank` | Map to: lov, lovbekendtgørelse, bekendtgørelse |
| `Status` | `status` | Valid → in_force, Historic → repealed |
| `DiesSigni` | `publication_date` | Date of signing |
| `StartDate` | `extra.start_date` | Entry into force |
| `EndDate` | `extra.end_date` | End of validity |
| `Number` | `extra.number` | Law number within year |
| `Year` | `extra.year` | Publication year |
| `PopularTitle` | `extra.popular_title` | Short name if available |
| `Ministry` | `extra.ministry` | Responsible ministry |
| `AdministrativeAuthority` | `extra.administrative_authority` | Agency |
| `AnnouncedIn` | `extra.announced_in` | Lovtidende A/B/C |
| `DiesEdicti` | `extra.publication_date` | Official publication date |
| `JournalNumber` | `extra.journal_number` | Internal reference |
| `Signature` | `extra.signatory` | Who signed |
| `Change/Ref_Accn` | `extra.changes` | Amendment reference chain |

## Version history

### Model

Denmark publishes consolidated laws as **Lovbekendtgørelse (LBK)** documents. Each
LBK is a full-text snapshot of the law at a specific point in time. When a law is
amended, a new LBK is published, and the old one becomes `Status: Historic`.

The metadata API exposes `legislationConsolidates` which links each LBK to:
1. The **previous LBK** (the prior consolidated version)
2. The **amendment law(s)** (LOV Æ) it incorporates

### Version spike result (GATE PASSED ✓)

**Test law:** "Lov om hold af dyr" (Animal Husbandry Act)

```
LBK 62/2024  (current, Valid)
  └─ consolidates: LBK 9/2022 + LOV Æ 1547/2023
       └─ consolidates: LBK 330/2021 + LOV Æ 2384/2021
            └─ ... (chain continues)
```

Each version has:
- Full consolidated XML text (via ELI XML endpoint)
- Date of signing (`DiesSigni`) for `GIT_AUTHOR_DATE`
- Accession number for `Source-Id` trailer

### Reconstruction algorithm

```
1. Start with LBK where Status=Valid for a given law
2. GET /api/document/metadata/{accn} → parse legislationConsolidates
3. First ELI URL in array → previous LBK accession number
4. Fetch its XML for the text, its metadata for the next link
5. Repeat until legislationConsolidates is empty → original LOV
6. Reverse the list → chronological order
7. Each version → one git commit (bootstrap + [reforma] commits)
```

### Version fetch cost

Per law: ~3-10 metadata API calls (one per version) + ~3-10 XML fetches.
Estimated total: ~15,000 active LBK × ~5 avg versions = ~75,000 fetches.
At 2 req/s → ~10 hours for full bootstrap with history.

## Scope estimate

| Category | Count |
|---|---|
| Total sitemap documents | 192,666 |
| Lovtidende A (eli/lta) | 62,913 |
| Active LBK (estimated) | ~4,000-6,000 |
| Active LOV without LBK | ~2,000-4,000 |
| Active BEK | ~8,000-12,000 |
| **Primary target (LBK + LOV)** | **~8,000-10,000** |
| Year range | 1852–2026 |

## Gotchas and limitations

1. **Cloudflare protection:** The site uses Cloudflare. `curl` with a real User-Agent
   works fine. The `WebFetch` tool gets 403. Must set User-Agent header.

2. **Metadata-only documents:** Very old laws (e.g., Grundloven 1953) return XML with
   `<Meta>` only, no `<DokumentIndhold>`. Skip these or fetch body from alternative
   source.

3. **LOV Æ (amendment laws):** These contain amendment *instructions*, not the full
   amended text. They use specialized elements (`<Aendring>`, `<AendringNyTekst>`,
   etc.). Skip for v1 — the consolidated text is in the LBK.

4. **The harvest API is change-only:** Max 10 days lookback. Cannot be used for
   discovery. Use sitemap for bootstrap, harvest API for daily updates.

5. **Harvest API rate limit:** 1 request per 10 seconds. But daily updates only
   need 1 call, so this is not a practical limitation.

6. **No structured "all versions" endpoint:** Version chains must be reconstructed
   by following `legislationConsolidates` links in the metadata API.

7. **Encoding:** UTF-8 throughout. Some XML files have `\n` literally embedded in
   text (e.g., JournalNumber). Strip these at parse time.

## Fixtures saved

| File | Type | Title | Size | Rich elements |
|---|---|---|---|---|
| `2024-434.xml` | LBK H | Straffeloven (Criminal Code) | 788 KB | 2 tables, 41 notes, 286 indentations, 395 §§ |
| `2024-62.xml` | LBK H | Lov om hold af dyr | 208 KB | Standard structure |
| `2024-1709.xml` | BEK H | Sygedagpenge (sick pay) | 69 KB | Executive order example |
| `2023-1547.xml` | LOV Æ | Amendment to animal law | 27 KB | Amendment instructions |
| `2020-1061.xml` | LOV Æ | Property tax amendment | 184 KB | 1 table, 103 italic, 7 indentations |

## Fetcher design

```
fetcher/dk/
  client.py      → RetsinformationClient (HttpClient)
                   - get_text(accn) → XML via ELI
                   - get_metadata(accn) → metadata API JSON
                   - get_daily_changes(date) → harvest API
  discovery.py   → RetsinformationDiscovery
                   - discover_all() → parse sitemap, yield accession numbers
                   - discover_daily() → harvest API
  parser.py      → DanishTextParser + DanishMetadataParser
                   - LexDania 2.1 XML → Blocks
                   - Meta + schema.org → NormMetadata
```
