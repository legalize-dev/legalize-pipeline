# Research: Luxembourg (LU)

**Date:** 2026-04-13
**Country code:** `lu`
**Status:** Research complete, ready for implementation

## Source

**Legilux — Journal officiel du Grand-Duché de Luxembourg**

- Portal: https://legilux.public.lu
- Open Data: https://data.legilux.public.lu
- SPARQL Endpoint: `https://data.legilux.public.lu/sparqlendpoint` (GET only, `query` param)
- Filestore: `https://data.legilux.public.lu/filestore/{eli_path}/{filename}.{ext}`
- License: **CC BY 4.0** (verified in RDF metadata of each manifestation)
- Authentication: **None** — fully public
- Rate limits: **None documented** (tested multiple rapid queries without issues)
- Responsible body: Ministère d'État — Service central de législation (SCL)

Luxembourg is the **founder of the ELI standard** (European Legislation Identifier). The data
model is world-class: FRBR-based (Work/Expression/Manifestation), full SPARQL access, Akoma
Ntoso XML for every law.

## URI structure (ELI)

```
http://data.legilux.public.lu/eli/etat/{branch}/{type}/{YYYY}/{MM}/{DD}/{memorial_id}/jo
```

Components:
- `etat` = national legislation
- `{branch}` = `leg` (legislative) or `adm` (administrative)
- `{type}` = document type: `loi`, `rgd`, `amin`, `agd`, `constitution`, `code`, etc.
- `{YYYY}/{MM}/{DD}` = document date
- `{memorial_id}` = Memorial number (e.g., `a175` = Series A #175, `n1` = pre-Memorial)
- `/jo` = published in Journal officiel

Examples:
- `eli/etat/leg/loi/2022/05/27/a250/jo` — Loi du 27 mai 2022
- `eli/etat/leg/constitution/1868/10/17/n1/jo` — Constitution
- `eli/etat/leg/loi/2022/05/27/a250/consolide/20250901` — Consolidation

### Identifier for filenames

Use the ELI path as identifier. Strip the `http://data.legilux.public.lu/eli/etat/` prefix
and replace `/` with `-`:

```
eli/etat/leg/loi/2022/05/27/a250/jo  →  leg-loi-2022-05-27-a250
```

This gives a stable, unique, filesystem-safe ID derived from the official ELI.

## Data model (FRBR / JOLux)

| Level | JOLux Class | Description |
|---|---|---|
| Work | `jolux:Act` | The abstract legal act |
| Expression | `jolux:Expression` | A version in a language (always `fr`) |
| Manifestation | `jolux:Manifestation` | A concrete file (HTML, XML, PDF, DOCX) |
| Complex Work | (via `jolux:isMemberOf`) | Groups original Act + all Consolidations |

Each Act and its Consolidations share the same Complex Work URI.

## Document types in scope

Primary legislation (v1 scope):

| Code | Name | Count | Notes |
|---|---|---|---|
| `LOI` | Loi | 9,194 | Primary laws |
| `RGD` | Règlement grand-ducal | 15,236 | Grand-ducal regulations |
| `Constitution` | Constitution | 1 | 37 consolidation versions |

Total v1 scope: **~24,431 acts**

Other types (future expansion):
- `AGD` (Arrêté grand-ducal): 9,717
- `AMIN` (Arrêté ministériel): 12,338
- `PA` (Publication administrative): 41,633
- `RC` (Règlement communal): 32,547

Grand total across all types: **~148,080 acts**

## Version history

**Full version history available** via Consolidations.

Model:
- Each Act may have consolidation versions linked via `jolux:isMemberOf` on the same Complex Work
- Each Consolidation has `jolux:dateApplicability` (start) and optionally `jolux:dateEndApplicability` (end)
- Consolidation XML has the same Akoma Ntoso structure as original Acts
- Total consolidations: **4,383** for **~1,317 distinct laws**

Access pattern:
1. Query SPARQL for all Acts of type LOI/RGD
2. For each Act, query for Consolidations with the same Complex Work
3. Download XML for each version (original + all consolidations)
4. Use `dateApplicability` as `GIT_AUTHOR_DATE`

### Version spike — Constitution (37 versions, 1919–2023)

```
Version 1: 1919-05-20 → 1948-05-02
Version 2: 1948-05-02 → 1948-05-14
...
Version 37: 2023-07-01 → current
```

Full spike saved to `engine/tests/fixtures/lu/version-spike.txt`.

**GATE PASSED:** 37 distinct versions with exact applicability dates extracted.

Other examples:
- Loi du 31/07/2006 (commercial law): 55 consolidation versions
- Loi du 17/11/1808: 36 versions
- Loi du 18/06/1879: 36 versions

## Data format: Akoma Ntoso XML

Format: **OASIS LegalDocML CSD13** with SCL Luxembourg extensions (`scl:` namespace).

### XML structure

```xml
<akomaNtoso xmlns="http://docs.oasis-open.org/legaldocml/ns/akn/3.0/CSD13"
            xmlns:scl="http://www.scl.lu">
  <act contains="originalVersion" name="">
    <meta>
      <identification>
        <FRBRWork>   <!-- ELI URIs -->
        <FRBRExpression>
        <FRBRManifestation>
      <scl:JOLUXWork>
        <scl:JOLUXLegalResource>
          <scl:jolux scl:name="typeDocument">...LOI</scl:jolux>
          <scl:jolux scl:name="dateDocument">2022-05-27</scl:jolux>
          <scl:jolux scl:name="dateEntryInForce">2022-06-05</scl:jolux>
          <scl:jolux scl:name="publicationDate">2022-06-01</scl:jolux>
          <scl:jolux scl:name="inForceStatus">...in-force</scl:jolux>
          <scl:jolux scl:name="modifies">...eli/...</scl:jolux>
          <scl:jolux scl:name="repeals">...eli/...</scl:jolux>
          ...
    <preface>
      <longTitle>  <!-- Full title text -->
    <preamble>
      <container name="preamble">
      <formula>
    <body>
      <chapter id="chapitre_1er">
        <num><b>Chapitre 1<sup>er</sup></b></num>
        <heading><b>Définitions</b></heading>
        <article id="art_1er">
          <num>Art. 1<sup>er</sup></num>
          <alinea>
            <content>
              <p>Text...</p>
              <ol start="1" symbol="1°">
                <li>...</li>
              </ol>
    <conclusions>
      <p>Signature block</p>
```

### Metadata embedded in XML

All metadata is in `scl:JOLUXLegalResource` and `scl:JOLUXExpression`:

| XML path | Maps to | Example |
|---|---|---|
| `FRBRWork/FRBRthis/@value` | `identifier` (ELI URI) | `eli/etat/leg/loi/2022/05/27/a250/jo` |
| `scl:jolux[@name="dateDocument"]` | `publication_date` | `2022-05-27` |
| `scl:jolux[@name="publicationDate"]` | `extra.memorial_date` | `2022-06-01` |
| `scl:jolux[@name="dateEntryInForce"]` | `extra.entry_in_force` | `2022-06-05` |
| `scl:jolux[@name="dateApplicability"]` | `extra.applicability_date` | `2022-09-01` |
| `scl:jolux[@name="typeDocument"]` | `rank` (mapped) | `LOI` |
| `scl:jolux[@name="inForceStatus"]` | `status` (mapped) | `in-force` |
| `scl:jolux[@name="isMemberOf"]` | `extra.complex_work` | Complex Work URI |
| `scl:jolux[@name="isPartOf"]` | `extra.memorial` | Memorial URI |
| `scl:jolux[@name="responsibilityOf"]` | `extra.responsible_institutions` | Institution URIs |
| `scl:jolux[@name="subjectLevel1"]` | `extra.subjects` | Subject URIs |
| `scl:jolux[@name="modifies"]` | `extra.modifies` | List of ELI URIs |
| `scl:jolux[@name="repeals"]` | `extra.repeals` | List of ELI URIs |
| `scl:jolux[@name="cites"]` | `extra.cites` | List of ELI URIs |
| `scl:jolux[@name="draft"]` | `extra.draft` | Draft URI |
| Expression `title` | `title` | Full title text |
| Expression `titleShort` | `extra.short_title` | Short title |

### Consolidation-specific metadata

| XML path | Maps to |
|---|---|
| `scl:jolux[@name="dateApplicability"]` | Version effective date (→ `GIT_AUTHOR_DATE`) |
| `scl:jolux[@name="dateEndApplicability"]` | Version end date |

## Formatting inventory

Tags found in the XML:

- [x] **Bold** — `<b>` elements (chapter headings, article numbers)
- [x] **Italic** — `<i>` elements (found in consolidations)
- [x] **Lists** — `<ol>`, `<ul>`, `<li>` with `start` and `symbol` attributes
- [x] **Superscript** — `<sup>` (ordinal markers: 1er, 2e, etc.)
- [x] **Cross-references** — `<ref>` with `href` attribute
- [x] **Footnotes** — `<note>`, `<noteRef>` (in consolidations)
- [x] **Amendments** — `<mod>`, `<textualMod>`, `<passiveModifications>` (in consolidations)
- [x] **Line breaks** — `<br>` (sparse)
- [x] **Embedded structures** — `<embeddedStructure>` (quoted law text in amendments)
- [x] **Signatures** — `<conclusions>` block
- [ ] **Tables** — NOT found in any sampled XML. Luxembourg legal XML does not use HTML tables;
      tabular data appears as structured lists or formatted paragraphs.
- [ ] **Images** — NOT present in XML.
- [ ] **Formulas** — NOT found.

## SPARQL query patterns

### Discovery: all in-force laws

```sparql
PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
SELECT ?act ?dateDoc
WHERE {
  GRAPH ?g {
    ?act a jolux:Act .
    ?act jolux:dateDocument ?dateDoc .
    ?act jolux:typeDocument ?type .
    ?act jolux:inForceStatus <http://data.legilux.public.lu/resource/authority/application-status/in-force> .
    FILTER (?type IN (
      <http://data.legilux.public.lu/resource/authority/resource-type/LOI>,
      <http://data.legilux.public.lu/resource/authority/resource-type/RGD>,
      <http://data.legilux.public.lu/resource/authority/resource-type/Constitution>
    ))
  }
}
```

### Get XML URL for an act

```sparql
PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
SELECT ?fileUrl WHERE {
  GRAPH ?g {
    <{act_uri}> jolux:isRealizedBy ?expr .
    ?expr jolux:isEmbodiedBy ?manif .
    ?manif jolux:format <http://publications.europa.eu/resource/authority/file-type/XML> .
    ?manif jolux:isExemplifiedBy ?fileUrl .
  }
}
```

### Get consolidation versions

```sparql
PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
SELECT ?consol ?dateApplicability ?dateEndApplicability ?xmlUrl WHERE {
  GRAPH ?g {
    ?consol a jolux:Consolidation .
    ?consol jolux:isMemberOf <{complex_work_uri}> .
    OPTIONAL { ?consol jolux:dateApplicability ?dateApplicability }
    OPTIONAL { ?consol jolux:dateEndApplicability ?dateEndApplicability }
    ?consol jolux:isRealizedBy ?expr .
    ?expr jolux:isEmbodiedBy ?manif .
    ?manif jolux:format <http://publications.europa.eu/resource/authority/file-type/XML> .
    ?manif jolux:isExemplifiedBy ?xmlUrl .
  }
}
ORDER BY ?dateApplicability
```

## Scope estimate

### Bootstrap scope (v1: LOI + RGD + Constitution)

- **~24,431 acts** (9,194 LOI + 15,236 RGD + 1 Constitution)
- **~4,383 consolidation versions** across ~1,317 laws
- Total XML downloads: ~24,431 (originals) + ~4,383 (consolidations) = **~28,814 files**
- Each requires: 1 SPARQL query (batched) + 1 HTTP GET for XML
- Average XML size: ~10-200 KB
- Estimated total data: ~2-5 GB

### Fetch strategy

1. **Discovery phase:** Single SPARQL query returns all act URIs + dates (paginated if needed)
2. **Metadata phase:** Per-act SPARQL query for Complex Work + consolidation info (can batch)
3. **Download phase:** HTTP GET to filestore for each XML (original + consolidations)
4. **Parse phase:** lxml parsing of Akoma Ntoso XML

### Estimated bootstrap time

At 4 workers × 2 req/s = 8 req/s effective:
- ~28,814 files / 8 req/s = ~3,600s = **~1 hour** (XML downloads only)
- Plus SPARQL queries: ~10-15 minutes
- Plus parsing + git commits: ~30-60 minutes
- **Total estimate: ~2-3 hours**

## Daily update strategy

Query SPARQL for acts with `jolux:publicationDate` or `jolux:dateDocument` after the last
sync date. Luxembourg publishes new laws in the Memorial several times per week.

```sparql
PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
SELECT ?act WHERE {
  GRAPH ?g {
    ?act a jolux:Act .
    ?act jolux:publicationDate ?pubDate .
    FILTER (?pubDate >= "2026-04-01"^^xsd:date)
  }
}
```

## Known limitations

- **No tables in XML:** Luxembourg's Akoma Ntoso does not use HTML `<table>` elements. Any
  tabular content is formatted as structured text or lists.
- **Single language:** All legislation is in French only (`fra`).
- **SPARQL GET only:** The endpoint only accepts GET requests (not POST). Large queries must
  be URL-encoded and may hit URL length limits (~8KB). Use pagination.

## Fixtures

```
engine/tests/fixtures/lu/
  sample-constitution.xml        51 KB  — Constitution du 17/10/1868
  sample-ordinary-law.xml        69 KB  — Loi du 27/05/2022 (enseignement musical)
  sample-regulation.xml           7 KB  — RGD du 02/04/2026
  sample-with-tables.xml         10 KB  — Loi du 21/12/2017 (finance, no actual tables)
  sample-code.xml               204 KB  — Consolidation of Loi du 06/02/2009 (204KB)
  version-spike.txt                     — 37 Constitution versions with dates
```
