# Switzerland (CH) fixtures

Source: **Fedlex** — Swiss federal legislation open-data portal
(https://www.fedlex.admin.ch/). All fixtures are German-language
manifestations of the Classified Compilation (`/eli/cc/`), served in
Akoma Ntoso 3.0 XML (namespace
`http://docs.oasis-open.org/legaldocml/ns/akn/3.0`) from the Fedlex
filestore under Content-Type `application/xml`. Bytes are stored raw
(no reformatting).

The Classified Compilation (CC) is the consolidated law collection —
each ELI `cc/YYYY/N` URI is a ConsolidationAbstract grouping all
point-in-time consolidations (`.../YYYYMMDD/de/xml/...`) of one law.

## Files

| File | ELI ConsolidationAbstract | Type | Exercises |
|---|---|---|---|
| `sample-constitution.xml` | `eli/cc/1999/404` (v. 2024-03-03) | Bundesverfassung (BV) — Federal Constitution | Top rank, tables, footnotes, cross-refs, placeholders, multilingual FRBRname, deep structure (book/part/title/chapter/section/article) |
| `sample-code.xml` | `eli/cc/24/233_245_233` (v. 2026-07-01) | Schweizerisches Zivilgesetzbuch (ZGB) — Swiss Civil Code | Large code (1277 articles, 74 chapters, 4 books, 845 footnotes, 1826 refs), old (1907) with legacy ELI number format using underscores |
| `sample-ordinary-law.xml` | `eli/cc/2024/620` (v. 2025-01-01) | Bundesgesetz über das Verbot der Verhüllung des Gesichts — face-covering ban | Small recent BG (2023) with XML manifestation, minimal structure |
| `sample-regulation.xml` | `eli/cc/2026/51` (v. 2026-03-01) | Verordnung über die Kommission für historisch belastetes Kulturerbe (VKHBK) | Recent Verordnung (2026), 13 articles, preamble with authorialNote cross-reference |
| `sample-with-tables.xml` | `eli/cc/1991/1184_1184_1184` (v. 2026-01-01) | Bundesgesetz über die direkte Bundessteuer (DBG) — Federal Direct Tax Act | 2 real `<table>` with `<tr>/<th>/<td>` (tax-rate schedules), 132 articles, 92 blockLists, 2 `<img>` (binary assets to skip) |

## Raw SPARQL response fixtures

Saved alongside each XML fixture so the parser tests can replay the
discovery/manifestation queries without hitting the network. Each file
is the exact JSON response from the Fedlex Virtuoso SPARQL endpoint
(`Accept: application/json`).

| File | Describes |
|---|---|
| `sparql-constitution.json` | All DE XML consolidations of the Federal Constitution (6 manifestations, oldest 2021-01-01, newest 2024-03-03) |
| `sparql-code.json` | All DE XML consolidations of ZGB (11 manifestations, oldest 2011-01-01) |
| `sparql-ordinary-law.json` | All formats and their URLs for `cc/2024/620` (single consolidation 2025-01-01 × 4 user-formats) |
| `sparql-regulation.json` | All formats for `cc/2026/51` (single consolidation 2026-03-01 × 4 user-formats) |
| `sparql-with-tables.json` | DE XML consolidations of DBG (3 manifestations, newest 2026-01-01) |

## Version history evidence

| File | Purpose |
|---|---|
| `version-spike.txt` | Records the §0.5 GATE: ≥2 distinct DE XML versions of the Federal Constitution extracted with effective dates and text deltas. |
