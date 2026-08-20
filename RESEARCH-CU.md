# Cuba (CU) — Gaceta Oficial de la República de Cuba Research

## 0.1 Source

- Official source: Gaceta Oficial de la República de Cuba, https://www.gacetaoficial.gob.cu
- Catalog landing page ("Algunas legislaciones cubanas"): `https://www.gacetaoficial.gob.cu/es/algunas-legislaciones-cubanas` — a curated list of 53 major national laws, each linking to a PDF.
- Access pattern: direct PDF download only. No REST API, no HTML full-text, no sitemap for the catalog.
- PDF URL patterns (all under `https://www.gacetaoficial.gob.cu/sites/default/files/`):
  - Daily-issue scans: `goc-{YYYY}-{E|O}{NN}[_N].pdf` (e.g. `goc-2021-ex25.pdf`, `goc-2021-o140_0.pdf`; `E` = Extraordinaria, `O` = Ordinaria).
  - Consolidated/edition PDFs: descriptive slug (e.g. `codigo_civil_actualizado_0.pdf`, `ley_150_del_sistema_de_los_recursos_naturales_y_el_medio_ambiente.pdf`).
  - MINJUS book editions (2 laws: Ley-109, Decreto-Ley-304): `https://www.minjus.gob.cu/sites/default/files/archivos/publicacion/2019-11/*.pdf`.
- `robots.txt` (`https://www.gacetaoficial.gob.cu/robots.txt`) returns 200. The catalog landing page returns **403 for curl's default UA but 200 with a browser User-Agent** — discovery must send a browser-like UA. The PDF downloads themselves return 200 with the default `legalize-bot` UA (verified: `goc-2021-ex25.pdf` 200, 782,250 bytes, last-modified 2023-07-07; `ley_109_codigo_seg_vial.pdf` 200, 3,338,774 bytes).
- TLS: valid chain. No `verify=False` needed.
- Catalog source of truth for the initial bootstrap: the existing 53-law `manifest.json` in `/tmp/legalize-cu/` (identifier → url/title/rank/publication_date/journal_issue/source, plus optional `goc`, `start_regex`/`end_regex`, `notes`).

## 0.2 Fixtures

Save raw PDF bytes under `tests/fixtures/cu/`. Five sample laws cover every rank (constitucion, codigo, ley, decreto_ley) plus both PDF hosts and both slicing modes:

| Law (identifier) | PDF file | rank | Why it was chosen |
|---|---|---|---|
| `Decreto-Ley-31-2021-Bienestar-Animal` | `goc-2021-ex25.pdf` (782 KB) | decreto_ley | Small modern Extraordinaria issue |
| `Ley-143-2021-Proceso-Penal` | `goc-2021-o140_0.pdf` (1.2 MB) | ley | Large law — 840 articles, plain issue |
| `Ley-59-1987-Codigo-Civil` | `codigo_civil_actualizado_0.pdf` (1.1 MB) | codigo | Consolidated edition, 528 articles + `bis`, `notes` |
| `Ley-109-2010-Codigo-Seguridad-Vial` | MINJUS `ley_109_codigo_seg_vial.pdf` (3.3 MB) | codigo | MINJUS book host, sliced via `start_regex`/`end_regex` |
| `Constitucion-2019` | `goc-2019-ex5_0.pdf` | constitucion | Constitution, special Gaceta 5 Extraordinaria 2019 |

## 0.3 Metadata Inventory

All metadata for the 53-law catalog lives in `manifest.json` (already normalized; no per-law crawling needed for bootstrap):

| Manifest field | Example | Maps to |
|---|---|---|
| key = identifier (file stem) | `Ley-143-2021-Proceso-Penal` | `identifier` |
| `title` | `Ley No. 143 de 2021, Del Proceso Penal` | `title` |
| `rank` | `constitucion`, `codigo`, `ley`, `decreto_ley`, `decreto` | `rank` |
| `publication_date` | `2021-12-07` (Gaceta masthead date, **not** approval date) | `publication_date` |
| `journal_issue` | `No. 140 Ordinaria de 2021` | `extra.journal_issue` |
| `goc` (some laws) | `GOC-2020-931-O88` | `extra.goc` (official GOC publication code) |
| `source` | `https://www.gacetaoficial.gob.cu/es/algunas-legislaciones-cubanas` | `source` (for Ley-109/DL-304: the MINJUS PDF URL) |
| `start_regex` / `end_regex` | `^LEY NÚMERO 109`, `^CONSEJO DE MINISTROS$` | slicing directives for book editions |
| `notes` | consolidated-edition provenance | `extra.notes` |

Identifier normalization is already done in the manifest: `Ley-NNN-YYYY`, `Decreto-Ley-NNN-YYYY`, `Decreto-NNN-YYYY`, `Constitucion-2019`. Filename year = the law's own (approval) year, not the Gaceta publication year (e.g. `Ley-150-2022` was published 2023-09-13).

Rank distribution of the 53 laws: 27 `ley`, 18 `decreto_ley`, 6 `codigo`, 1 `decreto`, 1 `constitucion`.

## 0.4 Formatting Inventory

All 53 sources are single-column, text-layer PDFs (born-digital scans of Gaceta issues or book editions). Features observed across the five samples:

| Feature | Present? | Notes |
|---|---|---|
| Masthead furniture | Yes | `GACETA OFICIAL`, `DE LA REPÚBLICA DE CUBA`, `MINISTERIO DE JUSTICIA`, `ISSN`, `EXTRAORDINARIA`/`ORDINARIA`, `SUMARIO`/ToC, `GOC-####-###-O##` codes, page numbers, running heads — all stripped |
| Enacting clause | Yes | `HAGO SABER: ... POR CUANTO: ... POR TANTO: ...` opens the body |
| Structural headings | Yes | Uppercase `TÍTULO`/`CAPÍTULO`/`SECCIÓN`/`LIBRO`/`PARTE`/`PREÁMBULO` → `seccion` |
| Final dispositions | Yes | `DISPOSICIONES GENERALES / TRANSITORIAS / FINALES / ESPECIALES / ADICIONALES` → `seccion` |
| Article headings | Yes | `ARTÍCULO N`, `Artículo N`, `ARTÍCULO N bis` → `articulo`; lowercase `artículo` is a cross-reference, never a heading |
| Numbered items | Yes | Inline `1. ... 2. ...` within paragraphs, not separate lines |
| Signatures | Yes | `DADA en La Habana, ...` + date line (e.g. `10 de abril de 2021`) at the end |
| Annexes | Yes | `ANEXO ÚNICO` / `ANEXO` (heading → `anexo`) |
| Tables / multi-column | Not observed in the five samples | Re-check during the full 53-law gate; if any, column text merges into flow text (acceptable for v1) |

Known extraction defect to fix in the parser (present in the previous generated output): pymupdf's text layer joins line-wrapped words that the PDF split *without* a hyphen into run-on fragments with a space — e.g. `disposicio nes`, `concien tizar`, `Re pública`, `crus táceos`. The tuned `merge_hyphenated` in the reference converter only rejoins lines ending in `-`; interior fragment pairs need a word-boundary pass. This is the main text-correctness item for the Step 7 gate.

## 0.5 Version History Spike

Multiple laws carry ≥2 dated versions in the same PDF — the version-spike gate is satisfied from day one:

| Law | Version 1 | Version 2 |
|---|---|---|
| `Ley-59-1987-Codigo-Civil` | Gaceta Extraordinaria de 15 de octubre de 1987 | body `ACTUALIZADO 8 DE NOVIEMBRE DE 2022` (consolidated edition; repealed arts 52, 448-465, 542-544 omitted) |
| `Ley-116-2013-Codigo-de-Trabajo` | Gaceta Extraordinaria No. 29 de 17 de junio de 2014 | body `ACTUALIZADO: 20 de febrero de 2020` |
| `Decreto-Ley-226-Registro-Mercantil` | Gaceta No. 2 de 10 de enero de 2002 | body `ACTUALIZADO 17 DE ABRIL DE 2023` + list of incorporating laws (incl. Ley-140/2021) |
| `Decreto-Ley-252-2007-Direccion-Gestion-Empresarial` | Gaceta Extraordinaria No. 41 de 17 de agosto de 2007 | body `1ra. Actualización: 14 de febrero de 2020. 2da. Actualización: 22 de marzo de 2023` |
| `Constitucion-2019` | proclaimed 2019-04-10, Gaceta No. 5 Extraordinaria de 2019-04-10 | 2025 constitutional reform PDF exists in the artifacts but is **not** part of the 53-law manifest — to be published as a separate `[new]` when promoted |

Decision: ship Cuba as a single Block + single Version per PDF, matching `gr`/`ad`/`lv`/`uy`. Consolidated editions are already republished by the Gaceta with amendments folded in, so version history is expressed as metadata (`publication_date` of the edition + `notes`), not as reform-graph Versions. The current repo's 53 files follow exactly this model, so bootstrap output will be near-identical.

## 0.6 Scope

- 53 laws (27 `ley`, 18 `decreto_ley`, 6 `codigo`, 1 `decreto`, 1 `constitucion`), each one PDF.
- Download sizes 197 KB–3.3 MB; total ≈ 40 MB. One GET per law → bootstrap completes in minutes at default worker counts.
- Daily incremental: the landing page is a *curated catalog*, not a per-issue feed. `discover_daily` re-fetches the catalog page (browser UA) and yields identifiers that are new relative to the local `data/json/` store; new PDFs are then fetched and bootstrapped like any other norm.

## 0.7 Format Coverage

Single-format source (PDF text layer only); §0.7 N/A.
