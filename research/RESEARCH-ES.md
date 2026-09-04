# RESEARCH-ES — Spain, Step 0 redone for the re-emission

> **STATUS: Step 0 CLOSED, 2026-09-03.** Research and decisions complete; no production code
> written, no country repo touched. `countries/es` is clean at `origin/main` (`cc3d02128`).
>
> **To resume:** read `research/es-v2/00-DECISIONES.md` §0 (the four decisions taken) and then
> its §7 (open questions, ordered by what it costs to be wrong). The next action is the
> **first tranche of the diary sweep, 2010→today** — it is the expensive half, it is
> idempotent and cacheable, it depends on none of the open decisions, and it produces the
> exact census that makes the remaining ones decidable. Nothing else should start before the
> single rebuild of the existing 12,299 files, which is indivisible.
>
> **Reproducible artefacts:** eight probe reports and twelve adversarial verifications in
> `research/es-v2/`; the dry-run harness and its 420-act result set in
> `research/es-v2/dry-run-*.{py,json}`. Cross-cutting findings that outlived this country are
> issues #128 (renderer contract) and #129 (frontmatter keys).

Status: **Step 0 (research) complete — no code written, no fixtures saved, corpus untouched**
Date: 2026-09-03 · Country: `es` · Source: BOE open data
Evidence: `engine/research/es-v2/01…08-*.md` (eight independent probes) and
`engine/research/es-v2/99-refutaciones.md` (twelve adversarial verifications, each with its
own disjoint sample). Decision memo for the maintainer: `engine/research/es-v2/00-DECISIONES.md`.

This document is to Spain what `RESEARCH-PT-v2.md` was to Portugal: not an onboarding, an
audit of a shipped country that is about to be re-emitted. It follows the section structure
of [`adding-a-country/step-0-research.md`](../adding-a-country/step-0-research.md) and states
an explicit verdict on every gate.

Total HTTP cost of the research pass: **at least 1,887 requests** to `www.boe.es` — 947
across the eight probes, 925 across eleven of the twelve verifiers (the twelfth does not
state its count), and 15 for the direct re-verification of the decisive figures. No 429, no
unprovoked 5xx; the only 5xx seen were deterministic responses to deliberately malformed
input.

---

## TL;DR

Spain was the first country onboarded, in April 2026, and Step 0 was never run against it
with the current playbook. Issue #106 audited the corpus for spec conformance; nobody had
ever compared the published Markdown against the BOE, measured the size of what the corpus
omits, or asked what the source offers that the fetcher does not read.

What this pass establishes:

- **The corpus is a strict subset of one BOE index and misses another entirely.** The 12,299
  published files are the consolidated catalogue (12,387 entries today) minus 86. Everything
  else the BOE publishes as general provisions — **78,908 acts of Sección I since 1979,
  exact, counted by the source** — has no representation anywhere. That is issue #66, and it
  is ~5× the corpus, not an addendum.
- **`text_state` for `es` is genuinely mixed**, and the majority is `as_enacted` once those
  acts are in. The per-norm override is decided by which endpoint answered, not by a test.
- **Both halves of issue #106 §2 are free.** `fecha_vigencia` is present on **100 %** of the
  block-level `<version>` stamps (11,379/11,379) and differs from the publication date in
  **96.4 %** of them. No re-fetch is needed for the block-level half — the date is in bytes
  the pipeline already downloads, parses into `Version.effective_date`, and discards.
- **Discovery is 4 requests, not 14,926.** `/eli/sitemap.xml` enumerates 103,070 ELI URIs
  with `lastmod`, and `/eli/eli-update-feed.atom` is a live change feed. Neither had been
  looked at. This resolves #99 and #66 with one design.
- **Text fidelity has one previously unmeasured failure and it is serious.** 5.3 % of sampled
  acts carry ~2 % of their official text — the rest is page-sized bitmaps — and those acts
  are **25.4 % of the official gazette pages** in the sample. The worst case is 2014, not the
  1970s, and 20 files in the shipped corpus already have it.
- **Two Step 0 gates PASS, one FAILS, and the Step 7 gate has never been run.**

---

## §0.1 Source(s)

Spain has **two** machine-readable surfaces, and the fetcher reads only the first.

### Surface A — consolidated legislation (what the corpus is today)

| | |
|---|---|
| Base | `https://www.boe.es/datosabiertos` |
| Catalogue | `GET /api/legislacion-consolidada?limit=&offset=&query=&from=&to=` |
| Metadata | `GET /api/legislacion-consolidada/id/{id}/metadatos` |
| Text | `GET /api/legislacion-consolidada/id/{id}/texto` |
| Aux vocabularies | `GET /api/datos-auxiliares/{estados-consolidacion,…}` |
| Spec | `/datosabiertos/documentos/APIconsolidada.pdf` (12 pp, dated 2025-09-02) |
| Auth | none |
| Formats | XML (default) and JSON via `Accept`. **An explicit `Accept` is mandatory**: the summary endpoint returns HTTP 400 `No soportado ningún mime type de la cabecera Accept` for `*/*`. Three probes lost requests to this. |
| Licence | Reuse permitted under the BOE's open-data terms; the corpus has been redistributed since April 2026 |
| `robots.txt` | **487,479 bytes, 13,901 lines, 12,148 `Disallow:` entries, no `Crawl-delay`, no `Sitemap:`.** There is no path-prefix ban: nothing disallows `/datosabiertos`, `/diario_boe`, `/boe/dias`, `/eli` or `/buscar` as a prefix. What it holds is **1,740 document identifiers** (845 `BOE-A`, 805 `BOE-B`, 75 `BOE-C`, 15 `BOE-T`), each listed three times — the BOE's right-to-be-forgotten suppressions. None of the 845 `BOE-A` ids is in the consolidated catalogue or in the repo today, which is luck rather than design: a Sección I sweep can reach them, so **discovery must filter the `robots.txt` id set out of its output** (one request, parsed once per bootstrap). |

Measured facts about the catalogue (2 requests, 16.0 MB, ~28 s, re-verified today):

| | |
|---|---:|
| Total entries | **12,387** (12,385 when the probes ran; ~8/day churn) |
| `BOE-A-` identifiers | 12,142 |
| Regional-gazette identifiers (`BOJA-b`, `BOA-d`, `BORM-s`, `DOGV-r`, `BOCL-h`, `DOGC-f`, `BOC-j`, `BOIB-i`, `BON-n`, `DOCM-q`, `BOCT-c`, `DOG-g`, `BOPV-p`, `BOCM-m`, `DOE-e`) | **245** |
| `ambito` | 8,767 Estatal / 3,618 Autonómico |
| `estado_consolidacion` | 12,190 Finalizado (3) / 195 Desactualizado (4) |
| `vigencia_agotada` | 9,973 N / 2,412 S |
| `fecha_publicacion` span | 1835-11-07 → today |
| `fecha_actualizacion` span | **2023-12-15T13:03:25Z** → today |
| Published ≥ 1979, `BOE-A` only | **11,715** |

Three API behaviours that are load-bearing for any design, all measured:

1. **`limit=-1` does not return everything.** The documented value caps at **10,000** per
   page (`limit=20000` returns byte-identical content). The two-page walk is the working
   method; `fetch.py`'s `batch = 1000` is 10× more conservative than necessary.
2. **`?from=&to=` is a change feed, not a historical index.** Nothing has a
   `fecha_actualizacion` before 2023-12-15, so a 1990 window returns zero. And it
   **silently truncates at the same 10,000 cap with an HTTP 200 and no total, no flag and no
   `Link` header**: `from=20251201&to=20251231` returns 10,000 when 10,017 exist.
3. **The backend is Solr and its errors do not follow HTTP conventions.** A malformed
   `query` returns **500**, not 400; `limit=0` and past-the-end return the same empty 200; a
   `range` on `identificador` is **discarded in silence** while a range on an unknown field
   returns 400. Consequences in §0.6.

### Surface B — the daily gazette (what the corpus omits — issue #66)

| | |
|---|---|
| Document | `GET https://www.boe.es/diario_boe/xml.php?id={id}` — or, equivalently, `GET https://www.boe.es/eli/{uri}/dof/spa/xml` (verified byte-identical size on the one act compared) |
| Daily index | `GET /datosabiertos/api/boe/sumario/{YYYYMMDD}` — spec `/datosabiertos/documentos/APIsumarioBOE.pdf`; **no query parameters at all** |
| Bulk index | `GET /eli/sitemap.xml` → 3 sitemaps → **103,070 `<loc>`, all unique, all with `<lastmod>`** (50,000 + 50,000 + 3,070; verified directly). 18 jurisdictions (`es` 93,172 + 17 `es-*`), 8,920 `/corrigendum/` entries, 1851→2026, 1,126 pre-1979. **Not the same population as Sección I** — see §0.6 |
| Change feed | `GET /eli/eli-update-feed.atom` → rolling ~8-week window, 725 entries |
| Counting oracle | `GET /buscar/boe.php` with `campo[0]=ORIS` (section) + `campo[6]=FPU` (date range), `page_hits` up to 2,000, deep offsets in one hop |
| Document structure | `<documento><metadatos/><metadata-eli/><analisis/><texto/></documento>` |

The summary archive starts **exactly 1960-09-01** (1960-08-31 → 404, 1960-09-01 → 200,
34,897 B). The search reaches 1960-01-01 and returns 2,233 Sección I acts below the summary
floor. Below 1960 is a different database — *Gazeta*, `/buscar/gazeta.php`, form-declared
1661-01-01…1959-12-31, **1,496,594 documents** — and a different decision.

**Publication cadence, measured exhaustively rather than assumed:** the BOE publishes every
day except Sunday. 0 of 8 and 0 of 5 sampled Sundays returned 200; 18 of 18 and **26 of 26**
non-Sundays did, including a contiguous 1979-12-15…1980-01-14 sweep through Christmas Day
and New Year's Day. One `<diario>` element per day, no hidden supplements — though
2026-09-02 carries two `diario_numero` (216 and 217), so *issues* and *publication days* are
not the same quantity in the modern BOE. Publication days 1979-01-01 → 2026-09-03: **14,926**
by calendar arithmetic, 14,970 by summing `max(diario_numero)` per year from the catalogue —
the two agree to 1 %.

### Historical versions

Available, dated twice, and complete — see §0.5. This is a `point_in_time` source for the
consolidated surface and an `as_enacted` source for the diary surface, which is what makes
`es` a mixed-`text_state` country.

### Daily update cadence

13 norms re-consolidated on 2026-09-02, 31 across 2026-09-01…03. One `?from=&to=` request
per run, ~16–40 KB — but see §0.6 on why one request is not safe for a backfill.

### No compression, and XML is 38× faster than JSON

`Content-Encoding` is absent on every endpoint tested and `Content-Length` equals the decoded
length, despite `requests` advertising gzip. So byte figures are transfer figures. And the
same summary day is **214,071 B as XML vs 413,098 B as JSON (1.93×)** and — measured back to
back on the same day — **0.3 s vs 11.4 s**. Over a 14,926-request sweep that is the
difference between an hour and a day. Ask for XML.

---

## §0.2 Fixtures — **NOT DONE, action item**

`engine/tests/fixtures/es/` **does not exist.** Verified: `ls tests/fixtures/es` → *No such
file or directory*, against 51 entries for other countries. Spain's only fixtures are two
loose files at the top of `tests/fixtures/` (`constitucion-sample.xml`,
`bcn-constitucion-sample.xml`) from before the per-country convention existed. This research
pass was read-only and deliberately did not create them.

The five the playbook requires, with the ids this pass established as the right choices:

| Fixture | Id | Why this one |
|---|---|---|
| `sample-constitution.xml` | `BOE-A-1978-31229` | 210 `<bloque>`, 214 `<version>`, 5 amending acts, and the only law in the sample whose every amendment took effect on publication |
| `sample-code.xml` | `BOE-A-1889-4763` (Código Civil) | 2,444 blocks / 3,837 versions; carries 127 blocks with `fecha_caducidad` and no materialised repeal — the §0.5 defect specimen |
| `sample-ordinary-law.xml` | `BOE-A-2015-11430` (Estatuto de los Trabajadores) | 43 amending acts, publication ≠ entry into force on 39 of them |
| `sample-regulation.xml` | `BOE-A-2005-895` | 22 blocks / 24 versions, present on both surfaces — the cross-surface comparison specimen |
| `sample-with-tables.xml` | `BOE-A-2013-7540` | 91 source tables, the only `<caption>` found (23 of them, carrying the operative rule text), and one nested table |
| **`sample-not-consolidated.xml`** *(new, sixth)* | `BOE-A-2026-10881` | The fourth reform of the Constitution. 404 on `/texto`, 43,496 chars in the diary XML, `rango 1676` (unmapped), and five co-official language versions in one `<texto>` |
| **`sample-image-substituted.xml`** *(new, seventh)* | `BOE-A-2014-13617` | 198 official pages, 7,235 chars of `<texto>`, 196 page-sized PNGs. The fidelity regression test the corpus has never had |
| **`version-spike.txt`** | — | Content ready to copy verbatim from `engine/research/es-v2/07-historial-versiones.md` §"The spike evidence" |

---

## §0.3 Metadata inventory

Built from response bytes, not from docstrings: 14 norms fetched on all three surfaces, 46
status-stratified norms, 54 diary documents, 53 consolidated texts (9,723 `<bloque>` /
16,417 `<version>`) and an exhaustive census of all 12,299 published files. Surface codes:
**C** = catalogue item · **M** = `/metadatos` · **D** = `diario_boe/xml.php` `<metadatos>` ·
**A** = the same document's `<analisis>` · **E** = its `<metadata-eli>` · **T** = `/texto`
`<bloque>`/`<version>` attributes. `file:line` is under `engine/src/legalize/`.

### Parsed today

| Source field | Surface | Type | Example | Parsed at | Frontmatter | Verdict |
|---|---|---|---|---|---|---|
| `identificador` | C M D | string | `BOE-A-1978-31229` | `fetcher/es/metadata.py:274` | `identifier` | OK |
| `titulo` | C M D | string | `Constitución Española.` | `metadata.py:275` | `title` | OK |
| `departamento` | C M D | string | `Cortes Generales` | `metadata.py:277` | `department` | OK |
| `departamento@codigo` | C M D | code | `1220` | `metadata.py:309` | `department_code` | OK |
| `rango` | C M D | string | `Constitución` | `metadata.py:132` | via `rank` | OK |
| `rango@codigo` | C M D | code | `1070` | `metadata.py:128`, `:310` | `rank_code` | OK |
| `ambito` / `@codigo` | C M | string / `1`,`2` | `Estatal` | `metadata.py:225`, `:311`, `:328` | `scope`, `ambito_code` | OK |
| `fecha_publicacion` | C M D | `YYYYMMDD` | `19781229` | `metadata.py:286` | `publication_date` | OK |
| `fecha_disposicion` | C M D | `YYYYMMDD` | `19781227` | `metadata.py:313` | `enactment_date` | OK |
| `numero_oficial` | C M D | string | `10/1995` | `metadata.py:312` | `official_number` | OK — absent on 1,772/12,299, correctly omitted |
| `diario` / `diario_numero` | C M D | string | `311` | `metadata.py:316-317` | `official_journal`, `journal_issue` | OK |
| **`fecha_vigencia`** | C M D | `YYYYMMDD` | `19781229` | `metadata.py:290` → `last_modified` | **no** | **missing** — never written; see below |
| `estatus_derogacion` | M D | `S`/`N` | `S` | `metadata.py:144` | via `status` | OK — domain narrower than the code assumes |
| `fecha_derogacion` | M D | `YYYYMMDD` | `20140925` | `metadata.py:318` | `repeal_date` | OK |
| `estatus_anulacion` | M | `S`/`N` | `S` | `metadata.py:150`, `:321` | `annulment_status` | OK |
| `vigencia_agotada` | C M D | `S`/`N` | `S` | `metadata.py:154`, `:324` | `validity_exhausted` | OK — but it is the union, not a category |
| `estado_consolidacion` | C M D | string | `Finalizado` | `metadata.py:327` | `consolidation_status` | **wrong** — label stored, `@codigo` dropped, and the label is mutable |
| `url_eli` | C M D | url | `…/eli/es/c/1978/12/27/(1)` | `metadata.py:294`, `:329` | `source`, `url_eli` | OK |
| `url_html_consolidada` | C M D | url | `…/buscar/act.php?id=…` | `metadata.py:295`, `:330` | `url_html_consolidada` | OK |
| `url_pdf` | D | path | `/boe/dias/1978/12/29/pdfs/…` | `metadata.py:401-404` | `pdf_url` **and** `url_pdf` | **wrong** — written twice, identical in 12,298/12,299 |
| `url_epub` | D | url | `…/diario_boe/epub.php?id=…` | `metadata.py:406` | `url_epub` | **wrong** — source nested the value; now always lost |
| `url_pdf_{catalan,euskera,gallego,valenciano}` | D | path | `/boe_catalan/dias/…` | `metadata.py:407-410` | same names | OK |
| `pagina_inicial` / `pagina_final` | D | int | `29313` / `29424` | `metadata.py:411-412` | `page_start`, `page_end` | OK — and the free density detector (§0.7) |
| `letra_imagen` | D | letter | `A` | `metadata.py:413` | `image_marker` | OK |
| `estatus_legislativo` | D | letter | `L` | `metadata.py:414` | `legislative_status` | OK — constant `L` on 12,299/12,299 and 48/48 live; zero discriminative power |
| `analisis/materias/materia` | A | list | `Constitución Española` | `metadata.py:424-428` | `subjects` | partial — `@codigo` dropped |
| `analisis/alertas/alerta` | A | list | `Derecho Constitucional` | `metadata.py:429-433` | `alerts` | partial — `@codigo` dropped; key name misleading (BOE topic channels, not warnings) |
| `analisis/referencias/anteriores/anterior` | A | list | `DEROGA BOE-A-1977-165` | `metadata.py:357-374`, `:436-441` | `references_previous` | partial — non-`BOE-` targets dropped |
| `…/posteriores/posterior` | A | list | `SE MODIFICA BOE-A-2026-10881` | `metadata.py:357-374`, `:442-464` | `references_subsequent` (+`_count`) | partial — same, plus the published `refs[:20]` slice |
| `bloque@id` | T | string | `a127` | `xml_parser.py:354` | drives block identity | OK |
| `bloque@tipo` | T | enum | `precepto` | `xml_parser.py:355` | **no** | OK — never emitted |
| `bloque@titulo` | T | string | `Art 127` | `xml_parser.py:356` | **no** | OK |
| `version@id_norma` | T | BOE id | `BOE-A-2000-323` | `xml_parser.py:345` | commit `Source-Id` | OK |
| `version@fecha_publicacion` | T | `YYYYMMDD` | `20000108` | `xml_parser.py:331` | `last_updated`, commit date | OK |
| **`version@fecha_vigencia`** | T | `YYYYMMDD` | `20010108` | `xml_parser.py:332` → `effective_date` | **no** | **missing** — parsed, cached, then discarded at every decision point |

### Exposed by the source and dropped silently — all in bytes we already download

| Source field | Surface | Example | Present in | Verdict |
|---|---|---|---|---|
| `fecha_actualizacion` | C M | `20260520T074424Z` | every catalogue item, 14/14, 46/46 | **missing** — the field `daily.py` discovers on; nothing records which consolidation the body corresponds to |
| `documento@fecha_actualizacion` | D | `20260520095602` | 54/54 | **missing** — a *different* timestamp for the same norm; it dates the diary entry |
| `fecha_anulacion` | M D | `19860620` | 1/14, 8/46 | **missing** — we write `annulment_status: "S"` and throw the date away; 24 files say `annulled` with no date |
| **`seccion`** | D | `1`, `3`, `5`, `G` | 54/54 | **missing** — the field that classifies an act for the non-consolidated corpus. `G` = Gaceta de Madrid |
| `subseccion` | D | (empty) | 54/54, 88/88 | missing; the *element* is present, the *value* never is |
| `diario@codigo` | D | `BOE`, `GAZ` | 54/54 | **missing** — the machine key for the 280 files whose journal is a regional gazette or the Gaceta |
| `origen_legislativo` (+`@codigo`) | D | `Estatal` | 54/54 | missing — duplicates `ambito`; harmless |
| `judicialmente_anulada` | D | `N` | 54/54 | missing — the diary's name for `estatus_anulacion` |
| `suplemento_pagina_inicial` / `_final` / `suplemento_letra_imagen` | D | `1` / `624` / `C` | 54/54 | **missing** — the page range needed to cite CCAA acts published as BOE supplements |
| `materia@codigo` / `@orden` | A | `1616` / `1` | 517 in 54 docs, 364 distinct codes | **missing** — we keep the Spanish label and drop the stable thesaurus id |
| `alerta@codigo` | A | `111` | 74 in 54 docs, 24 distinct | **missing** |
| **`analisis/notas/nota` (+`@codigo`, `@orden`)** | A | `149` → *"se entiende implícitamente derogada por RD 798/1995"* | **37 notes in 30 of 54 documents** | **missing — the worst of them.** Implicit repeals, real entry-into-force dates in prose, the gazette of original CCAA publication. 12 distinct `@codigo` |
| `palabra@codigo` | A | `210`=DEROGA, `231`=SUSPENDE, `330`=CITA, `426`=TRANSPONE, `440`=DE CONFORMIDAD | every reference | **missing** — the code is the machine key; the Spanish word is a label |
| `anterior@orden` / `posterior@orden` | A | `1010` | 1,027 references | missing — the BOE's own ordering key |
| **`metadata-eli` (whole RDF block)** | E | 16,089 B for the Constitution | 54/54 | **missing — an entire surface.** `eli:consolidated_by` (398 entries in 23/54) is a free version index with dates |
| **`bloque@fecha_caducidad`** | T | `20120306` | **1,281 of 9,723 blocks (13.2 %)** in 12/53 docs | **missing** — 622 of them publish repealed text as if in force |
| `blockquote@caduca` / `p@caduca` | T | `20210430` | 315 + 3 | **missing** — sub-block expiry |
| `version@fpub` | T | `""` | 32/16,417 | missing; empty everywhere — source noise, worth logging |

### Written by us but not supported by the source

| Frontmatter key | Problem | Measurement |
|---|---|---|
| `url_pdf` | exact duplicate of the core `pdf_url`, both from the same element | identical in **12,298 of 12,299** files |
| `url_epub` | the source now nests it (`<url_epub><url_epub>…`); `_text_of` reads the outer whitespace | nested on **17 of 54**, flat-with-text on **0**; **5,269 files lose the field on re-emission** unless fixed first |
| `consolidation_status` | label not code, and mutable: `BOE-A-2006-2779` reads `Desactualizado` in the corpus and `Finalizado` today | corpus: `Finalizado` 12,196 · `Desactualizado` 102 · `Sin consolidar` 1 — and that third value is no longer in the API's declared domain |
| `alerts` | the English key implies a warning; the values are BOE topic channels (`Comercio`, `Sistema financiero`) | 24 distinct values |
| reference separator | the corpus uses `"; "`; `main` since `1d04644` writes `" \| "`, and the sentences it now adds contain `;` | 11,885 + 8,530 files affected |

Verdict counts:

| Verdict | n | The ones that matter |
|---|---:|---|
| OK | 33 | the core eight, the code fields, the date trio, repeal status/date, the translated PDFs, page range, subjects |
| **missing** | **21** | `fecha_vigencia` (norm level **and** 16,401 block stamps) · `fecha_actualizacion` (two different flavours) · `fecha_anulacion` · `seccion` · `diario@codigo` · `suplemento_pagina_*` · `materia@codigo` · `alerta@codigo` · **`<analisis><notas>`** · `palabra@codigo` · **`<metadata-eli>`** · **`bloque@fecha_caducidad`** |
| **wrong** | 5 | `url_epub` · `url_pdf` · `consolidation_status` · `alerts` · the reference separator |
| partial | 4 | `references_previous`/`_subsequent` · `subjects` · `alerts` |

Per-field evidence, sample construction and the `<analisis>` verb census in full:
`engine/research/es-v2/05-inventario-metadatos.md`. The five that change the output, with
their measurement:

**1. `fecha_vigencia` is fetched, parsed, stored — and never written.** `metadata.py:290`
puts it in `NormMetadata.last_modified`; `frontmatter.py` never reads `last_modified`. It is
absent from **all 12,299** files, and `storage.py:189-193` makes the loss permanent in the
JSON cache by writing it under the key `last_updated` and reading it back as
`last_modified`. Over 46 norms it differs from the publication date in **89.1 %** of cases;
median +1 day, max +184, **minimum −11,489 days** (`BOE-A-2012-6155`: published 2012-05-08,
in force from 1980-11-23). See §0.5 for the block-level half.

**2. `bloque@fecha_caducidad` is read by nothing** — `grep -rn "fecha_caducidad\|caduca"
src/legalize/` returns zero hits — and it is behind a real publication defect. It marks the
date a block ceased to exist. **1,281 of 9,723 blocks (13.2 %) in 12 of 53 documents** carry
one at or before their file's render date. Of those, 659 have the repeal materialised as a
further `<version>` reading `(Derogado)` and render correctly; the other **622 (6.4 %) have
no version at or after the expiry date, so their last live text is published as if in
force**. `es/BOE-A-1984-12106.md` publishes **378 articles** the source marks as gone.
There is a finer sibling, `@caduca` on `<blockquote>` (315) and `<p>` (3), equally ignored.

**3. `_reference()` drops every non-`BOE-` target** (`metadata.py:367`), which is **2.9 %** of
references. That is why `TRANSPONE` (rank code 426) appears in the source and in **0 of
12,299 files**: its target is always a `DOUE-` id. **Every EU transposition link in the
Spanish corpus is invisible**, and references pointing at our own **243** regional-gazette
files break too.

**4. `<analisis><notas>` is never touched** — 37 notes in 30 of 54 documents, carrying
implicit repeals (*"Esta norma se entiende implícitamente derogada por…"*), real
entry-into-force dates in prose, and the gazette of original CCAA publication.

**5. `url_epub` silently regressed.** The source now nests the value
(`<url_epub><url_epub>…</url_epub></url_epub>`); `_text_of(dm, "url_epub")` reads the outer
element's whitespace. Nested shape on **17 of 54** documents, flat on **0**. The **5,269**
corpus files that currently carry `url_epub` lose it on re-emission unless this is fixed
first.

### The reference verbs, and what only they record

24 distinct verbs in `anteriores` (49,994 entries, 11,885 files) and 34 in `posteriores`
(38,151 entries) — full census in `05-inventario-metadatos.md` §4.2. A `<version>` stamp
exists only when words changed, so these verbs are the **only** place in the corpus where a
change of legal effect without a change of wording can live:

| Fact | Verbs | Corpus count |
|---|---|---:|
| Suspension | `SUSPENDE` / `SE SUSPENDE` (code 231) | 214, **plus an unknown number hidden inside `SE DICTA EN RELACIÓN` (1,570)** |
| Loss of effect without repeal | `DEJA SIN EFECTO` | 344 |
| Extension of a temporary norm | `PRORROGA`, `AMPLÍA` | 833 |
| Judicial annulment | `SE ANULA`, `SE DECLARA`, `SE DISPONE el cumplimiento de la Sentencia` | 1,869 |
| Confirmation still in force | `DECLARA la vigencia` | 248 |
| Pending constitutional challenge | `Recurso`, `Cuestión`, `Conflicto` | 369 |

A nuance worth recording against the `1d04644` commit message: the closed list **does** have
a word for suspension (`231`). What the LSC art. 348 bis case shows is that the BOE does not
always use it — some suspensions are filed under `331` and named only in `<texto>`. Both
halves of the #106.1/#106.2 fix are needed; neither alone is sufficient.

`palabra@codigo` is dropped — only the Spanish label is stored — which makes every consumer
match on prose.

### An entire surface never opened

Every diary XML carries `<metadata-eli>`, an ELI/RDF description (16 KB for the
Constitution, present on 54/54 documents). `fetcher/pt/parser.py::_parse_eli_rdfa` already
reads exactly this kind of block for Portugal. For Spain it is downloaded and discarded. It
contains, among others, **`eli:consolidated_by` — 398 entries in 23 of 54 documents: the full
list of consolidated versions with their dates**, as URIs. That is a free version index we
currently obtain only by parsing multi-MB `/texto` documents.

### Repeal and annulment, value domain measured

`estatus_derogacion` takes only `S`/`N` across 62 live norms (30 of them known-repealed) —
**`T` and `P` were never observed**, and `partially_repealed` appears in **0 of 12,299**
published files, so both branches of `_parse_status` are dead on the evidence. And
`vigencia_agotada` is not a category but the union: the corpus proves it exactly —
2,387 files with `validity_exhausted: "S"` = 1,935 repealed + 24 annulled + 428 expired.
So our `status: expired` means precisely *"out of force and the BOE names no repeal and no
annulment"* — a residual bucket, not a statement that the norm was temporary. Worth saying
out loud, because "expired" reads as the latter.

---

## §0.4 Formatting inventory

Measured over 46 consolidated documents (3,989 blocks, 5,252 versions) restricted to the
HEAD version of each block — the version the published file actually renders — plus a
corpus-wide exhaustive census of all 12,299 `.md` files. Full tables in
`06-cobertura-formato.md`.

| Construct | In source | % of sampled files | 95 % CI | In the published `.md` (corpus-wide) |
|---|---|---:|---|---|
| Tables | 543 (89,445 cells) | 37.0 % | 24.5–51.4 | **3,162 files (25.7 %)**, 33,680 tables, 840,649 rows |
| Cross-reference links | 3,869 `<a>` | 71.7 % | 57.5–82.7 | 8,091 files (65.8 %), 149,387 links |
| Blockquotes (footnotes + quoted amending text) | 1,655 | 67.4 % | 53.0–79.1 | 8,023 files (65.2 %), 259,727 lines |
| Bold | 1,462 | 47.8 % | 34.1–61.9 | 8,535 files (69.4 %) |
| Italic | 136 | 26.1 % | 15.6–40.3 | 3,251 files (26.4 %) |
| Superscript | 213 | 15.2 % | 7.6–28.2 | 1,335 files (10.9 %), 33,010 |
| Images / figures | 121 | 13.0 % | 6.1–25.7 | 1,608 files (13.1 %), 26,169 |
| Subscript | 3,751 (in 4 files) | 8.7 % | 3.4–20.3 | 801 files (6.5 %), 35,560 |
| Footnotes (`p.nota_pie`) | 1,628 | — | — | 7,355 files (59.8 %), 154,997 lines |
| Annexes (`p.anexo*`) | 96 | — | — | 4,067 files (33.1 %), 12,911 headings |
| Signatories | 95 | — | — | 8,218 files (66.8 %) |
| Table caption | 43 (1 file) | 2.2 % | 0.4–11.3 | **0 — dropped** |
| **Ordered / unordered lists** | **0** | 0.0 % | 0.0–7.7 | — |
| **Formulas / MathML** | **0** | 0.0 % | 0.0–7.7 | — |

Three of these decide work:

- **There are no HTML lists in BOE XML at all.** Enumerations are ordinary
  `<p class="parrafo">` whose text begins `1.`, `a)`, `Primero.`. `_list_paragraphs` is dead
  code for `es` — and this is what turns the numbering problem below from a parsing issue
  into a rendering one.
- **There is no MathML and no TeX.** Formulas ship as `<img>` or as inline `<sup>`/`<sub>`.
  `BOE-A-2014-6084` is the specimen: 14 images and 3,751 `<sub>`.
- **Rich content survives the paragraph dispatch intact.** Measured on the diary surface:
  **0 of 22,318 text units of ≥4 characters missing** across 76 acts, and no unhandled child
  element of `<texto>` in 76 documents. Measured on the consolidated surface: across 5,252
  versions there is **not one** child element outside `{p, table, ol, ul, img, pre,
  blockquote}`, and **zero** structures nested inside a `<p>`.

### Hygiene: what is not there

Exhaustive over 12,299 files: **0 mojibake · 0 C0/C1 control characters · 0 NBSP or
zero-width residue · 0 empty bodies · 0 doubled prose paragraphs.** `_text.clean()` works.
Nine files (0.073 %) carry residue, each root-caused in `06-cobertura-formato.md`; two of
them are not defects at all — the law itself documents an XML format and we un-escape it.

### Fidelity of the published Markdown against the source, version-aware

| Construct | Source (HEAD versions) | Published `.md` | Delta |
|---|---:|---:|---|
| Tables | 178 | 177 | **−1** (0.6 %) |
| Images | 110 | 100 | **−10** (9.1 %) |
| `<a>` cross-references | 1,641 | 1,617 | −24 (1.5 %) |
| `<caption>` | 23 | **0** | **−23 (100 %)** |
| `p.textoCompleto` | 11 | **0** | **−11 (100 %)** |

Per-file table counts match exactly in 45 of 46 documents. The losses are all one-line
fixes and all root-caused:

- **`<img>` as a direct child of `<td>` renders an empty cell** — `_cell_text` calls
  `_extract_inline` per child, which converts an `<img>` that is a *child* of what it is
  given but not one that *is* it. `BOE-A-1968-963` loses 10 of 11 images; the BOE's own
  `act.php` serves all 11.
- **`<caption>` is dropped** — `render_table` iterates `tr` only. In `BOE-A-2013-7540` the
  captions carry the substantive rule text.
- **`p.textoCompleto` is stripped**, and it is the BOE's own note that a *corrección de
  errores* is folded in — legislative provenance, 18 occurrences in 13 of 46 files. It was
  put in `_STRIP_CLASSES` alongside the table-cell classes; those never needed stripping and
  this never deserved it.
- **A `<table>` nested inside a `<table>` collapses into one** — `render_table` uses
  `table_el.iter()`, which descends.

### The fear that turned out to be unfounded

`_STRIP_CLASSES` deletes `cabeza_tabla` / `cuerpo_tabla_*` paragraphs. If the BOE ever
emitted them standalone, every cell of that table would vanish silently. Measured across
three independent samples spanning 190 years: **94,310 / 94,310 · 392 / 392 · 10,964 /
10,964 are inside a `<td>` or `<th>`. Zero standalone.** Keep the guard, take
`textoCompleto` out of it.

### The largest fidelity item in the corpus, and it is a rendering problem

BOE has no `<ol>`, so a numbered legal paragraph arrives as `<p class="parrafo">3. El
Estado…</p>` and is emitted verbatim as `3. El Estado…`. Every CommonMark renderer reads
that as an ordered-list item, takes the *first* number of a run as the start value and
renumbers sequentially. Exhaustive over 12,299 files:

| | Count | Share |
|---|---:|---:|
| Ordered-list runs in the published Markdown | 391,038 | |
| Runs that do not start at 1, or are not consecutive | **167,666** | **42.9 %** |
| Files containing at least one such run | **9,396** | **76.4 %** |

`es/BOE-A-1882-6036` has a run reading `[10, 6, 7]`. The file on disk is a faithful
transcription; what a reader sees is not. The re-emission is the only cheap chance to fix
it, and the cheap prerequisite is one minute of checking whether legalize.dev's renderer
already suppresses it.

### Two shipped defects the re-emission should not carry forward

- **Indentation renders as a Markdown code block.** `markdown.py` maps `sangrado`→4 spaces,
  `sangrado_2`→8, `sangrado_articulo`→4, and `render_paragraphs` puts a blank line between
  paragraphs, so each becomes an indented code block. **1,152 of 8,690 `es/` files (13.3 %)**
  and **115,948 lines** (79,176 at 4 spaces, 35,522 at 8, 1,241 at 12, 9 deeper — the
  4-space-only grep undercounts by 46 %). Exposure is higher on the diary surface, where
  quoted amending text arrives as bare `sangrado_2` with no `<blockquote>` wrapper.
- **`<sup>` / `<sub>` / `<small>`: 159,696 opening tags in the shipped corpus** — 159,677
  deliberate (94,680 `<small>`, 34,518 `<sub>`, 30,479 `<sup>`) plus 19 accidental
  `<p>`/`<td>` leaks. This is a deliberate design choice, but the playbook says *"no
  leftover HTML/XML tags"* with no exception written anywhere. Either document the
  exception or convert them.

---

## §0.5 Version-history spike — **GATE: PASS**

```
GATE §0.5 (≥2 dated versions extracted from one law, source classified into a text_state):
  **PASS** — 214 versions across 210 blocks of BOE-A-1978-31229 with 5 distinct dated
  amending acts; 11,379 versions across 5,944 blocks over 8 laws; 100 % of versions carry
  both fecha_publicacion and fecha_vigencia; bloque/@id is the stable cross-version key,
  unique within a document in 5,944 of 5,944 cases. Classification: point_in_time for the
  consolidated surface, as_enacted for the diary surface — es is a MIXED country.
```

Evidence and the `version-spike.txt` content: `07-historial-versiones.md`. The structure,
verbatim:

```xml
<bloque id="a2" tipo="precepto" titulo="Artículo 2">
  <version id_norma="BOE-A-2015-11430" fecha_publicacion="20151024" fecha_vigencia="20151113">…</version>
  <version id_norma="BOE-A-2017-1933"  fecha_publicacion="20170225" fecha_vigencia="20170226">…</version>
  <version id_norma="BOE-A-2022-4583"  fecha_publicacion="20220323" fecha_vigencia="20220331">…</version>
</bloque>
```

Complete attribute inventory (8 laws, 5,944 blocks, 11,379 versions):

| Element | Attribute | Occurrences | Read today | Emitted |
|---|---|---:|---|---|
| `bloque` | `id` | 5,944 (100 %) | `xml_parser.py:354` | block identity |
| `bloque` | `tipo` | 5,944 (100 %) | `:355` | **no** |
| `bloque` | `titulo` | 5,923 (99.6 %) | `:356` | **no** |
| `bloque` | **`fecha_caducidad`** | **292** | **nothing** | **no** |
| `version` | `id_norma` | 11,379 (100 %) | `:345` | commit `Source-Id` |
| `version` | `fecha_publicacion` | 11,379 (100 %) | `:331` | `last_updated`, commit date |
| `version` | **`fecha_vigencia`** | **11,379 (100 %)** | `:332` → `Version.effective_date` | **no** |
| `version` | `fpub` | 3 | nothing | no — empty in all 3, a BOE emission bug |
| `blockquote` | `caduca` | 315 | nothing | no |

`bloque/@tipo` domain: `precepto` 4,985 · `encabezado` 938 · `firma` 8 · `preambulo` 7 ·
`nota_inicial` 5 · `parte_dispositiva` 1. There is no `fecha_derogacion`, no `estado`, no
version-number attribute; `fecha_caducidad` is the only end-date and it lives on `bloque`.

### The question that decides the cost of a known defect: block level, not norm level

**The entry-into-force date IS available at block level, on 100 % of stamps.** So the
block-level half of issue #106 §2 needs **no re-fetch either** — the date is in the same XML
the pipeline already downloads and already parses, and then discards at every decision
point (`extract_reforms` keys on `publication_date`; `get_block_at_date` filters on
`publication_date`; `render_frontmatter` writes that same date as `last_updated`).

And the block-level date is not merely *a* date, it is **more correct than the norm-level
one**:

- On **63 of 356** checkable amending acts (**17.7 %**) the block's `fecha_vigencia`
  disagrees with the amending norm's own. `BOE-A-2025-76` puts different blocks of the LOPJ
  in force on 2025-01-23, 2025-04-03 **and** 2025-10-03; the norm-level date cannot express
  that and would collapse them. **32 of 589 act↔law pairs (5.4 %) stagger entry into force
  across blocks of the same law.**
- Resolving via the amending norm's `/metadatos` is **impossible** for a third of amending
  acts: 167 of 523 (31.9 %) are not in the consolidated catalogue, and 10 of 10 sampled
  returned 404. It would also cost **≥20,000 extra requests** for a full corpus.

Size of the residual error if the publication date is kept, over 11,374 parseable pairs:

| | |
|---|---:|
| `fecha_vigencia` = `fecha_publicacion` | 410 (**3.6 %**) |
| differ | **96.4 %** |
| median | **22 days** |
| \|Δ\| > 30 days | 31.3 % |
| \|Δ\| > 365 days | 10.3 % |
| min / max | −345 / +3,570 days |

Two things that table hides. The 366-day spike is almost entirely **one act**: 1,078 of the
1,170 ">365" rows are the Ley de Enjuiciamiento Civil, whose 1,024 original blocks are
`fecha_publicacion="20000108" fecha_vigencia="20010108"` — a one-year *vacatio legis*. Our
`es/BOE-A-2000-323.md` carries `publication_date: "2000-01-08"` and its `[bootstrap]` commit
is dated 2000-01-08: **a text that had no legal force for another twelve months**. And
retroactive amendments are real: 13 versions have a negative delta (`BOE-A-2006-5691`,
published 2006-03-30, effective 2006-01-01 across 6 articles of the IVA law). A
date-ordered history keyed on publication silently reorders these.

**Commit-level impact of switching**, on the 8 sampled laws (deliberately the most-reformed,
so only the ratios generalise): **595 → 628 commits (+5.5 %)** and **515 of 595 dates move
(86.6 %)**. Extrapolated to 44,295 commits: roughly +2,400 commits and ~38,000 dates moving.
The Constitution is the one law where nothing changes.

One guard the switch needs: `_parse_date` rejects year > 2100 but **not** year < 1700, and
`BOE-A-1997-28053` really does carry `fecha_vigencia="09980101"` — a BOE typo for 1998.

### `text_state` classification, and the override

Walking the playbook's decision tree:

- *Amendments incorporated?* **Yes** — a `<bloque>` holds successive complete wordings.
- *At a past date?* **Yes** — each wording is dated twice; selecting per block reconstructs
  any day.

→ **`point_in_time` for the consolidated surface.** That is the spec default and is never
written to the frontmatter, so **`TEXT_STATE["es"]` must not be set to `point_in_time`**.
Once the non-consolidated acts are in, they are the majority, so:

```python
# countries.py — BOE consolidates 12,387 norms and publishes everything else as
# enacted. The country default is the majority; the parser promotes the
# consolidated ones back to POINT_IN_TIME per norm.
"es": TextState.AS_ENACTED,
```

The condition that flips a norm is not a test the parser performs but a fact it already
holds: **`POINT_IN_TIME` if and only if the norm was built from
`/api/legislacion-consolidada/id/{id}/texto`.** In `es`, unlike `pt`, the two surfaces are
different endpoints with different schemas, and there is no third case — `/metadatos` and
`/texto` agree **28/28**, so an act has both or neither. Two mechanical forms, both verified:

| Where | Condition | Cost | Verified |
|---|---|---|---|
| discovery / bootstrap | `identificador in catalogue_ids` | 2 requests for the country | **79/79** and **41/41**, 0 FP, 0 FN |
| parser, given the diary XML | `<estado_consolidacion codigo> ∈ {"3","4"}` | 0 extra requests | 419/420 at n=420 — **1 disagreement**, see the dry run |

Write it as a **positive** test on the documented values, and log anything outside
`{0,3,4}`. The negative form (`codigo != "0"`) was recommended in an earlier draft of this
document and the dry run below refuted it: `BOE-A-2001-3498` carries an undeclared
`codigo="1"` and is non-consolidated, so `!= "0"` misclassifies it. The domain drifts in both
directions — the aux endpoint declares only `3` and `4`, while a `Sin consolidar` label
survives in one published file — so neither polarity is safe without the log line, and
catalogue membership stays the authority for the bootstrap.

The choice of country default is **invisible in the output** (`frontmatter.py:70-74` emits
the key only when the state is not `POINT_IN_TIME`, so both designs produce byte-identical
files) and is therefore made on failure mode: with the default at `AS_ENACTED`, a skipped
override **understates** a consolidated file; with it absent, a skipped override publishes
`point_in_time` — the spec's strongest claim — over an un-amended 1979 text. Understating is
recoverable. Full argument and the code-path trace in
`08-text-state-por-norma.md` §4 and `00-DECISIONES.md` §5.

### Two defects this section found that the re-emission must fix in the same pass

1. **622 blocks of repealed law published as current text** (§0.3, item 2). The fix is the
   mirror of the version rule: drop a block whose `fecha_caducidad` ≤ the target date.
2. **`parse_text_xml()` returns 0 blocks on a diary XML** — it iterates `root.iter("bloque")`
   and there are none. Verified by running the real function read-only on three diary
   documents. Without a separate dispatch the non-consolidated path emits **empty files
   silently**.

---

## §0.6 Scope

### Laws in scope

| Population | Count | Basis |
|---|---:|---|
| Consolidated catalogue | **12,387** | exact, 2 requests, re-verified today |
| — published in the repo today | 12,299 | filesystem census |
| — **missing from the repo** | **88** | set difference (86 when the probes ran); **42 of the 88 were published before 2026**, oldest 1982 |
| — orphans in the repo | **0** | the only non-catalogue stem is `README` |
| Sección I acts, 1979-01-01 → 2026-09-03 | **78,908** | exact, BOE's own search, verified by me and independently by two verifiers with different query constructions |
| — of which already consolidated (× 0.892) | ~10,450 | catalogue count × the measured Sección I share |
| — **non-consolidated: the issue #66 population** | **~68,458** | difference |
| Sección I, 1975 → today / 1960 → today | 86,335 / 112,251 | exact |
| Sección I + T (Constitutional Court), 1979 → today | 90,603 | exact; T = 11,695 |
| Sección III ("Otras disposiciones"), 1979 → today | **540,307** | exact — 6.8× Sección I, for anyone tempted |
| All BOE documents, 1979 → today | 2,471,700 | exact |

**89.2 % of consolidated norms sit in Sección I**, 9.8 % arrive via Sección III and 1.0 %
via II-B (n=102; independently reproduced at 95.0 % on 20 and 90.2 % pooled over 122). That
constant is why the catalogue's per-year count is not the same population as "Sección I acts
that got consolidated". Separately, the 245 regional-gazette ids are outside any BOE summary
by construction.

Two caveats on the exact counts, so they are not read as cleaner than they are:

- **The BOE's section coding is not stable across eras.** Filtering on section I in 1985
  returns 178 rows (of 2,000) labelled *"V. Comunidades Autónomas"* alongside 1,703 labelled
  *"I. Disposiciones generales"* and 119 from the TC supplement, so the 78,908 includes the
  old Sección V. Three independently chosen contrast days (1979, 2000, 2025) matched the
  summary API exactly, so this is a labelling artefact rather than a filter leak — but a
  sweep that assumes a fixed section vocabulary will misclassify the 1980s. The pre-1990
  summaries carry a `codigo="5"` section named "V. Comunidades Autónomas" (8 sampled days,
  72 items, all `BOE-A` ids) that is *not* general provisions.
- **`~10,450` is the only derived figure in the table**: the exact catalogue count times the
  measured 0.892. If the constant is really 0.902 the row moves by ~120 files, so nothing
  downstream is sensitive to it.

### Requests and time for a full bootstrap

There is **no bulk document endpoint** — the API surface is BOE sumario, BORME sumario,
`legislacion-consolidada` and `datos-auxiliares`, and the summary's `<sumario_diario>`
offers only a PDF of the issue index. So it is one `xml.php` per act.

| Phase (1979 floor, Sección I only) | Requests | Bytes |
|---|---:|---:|
| Consolidated discovery | 2 | 16.0 MB |
| Non-consolidated discovery (search, 40 + ELI sitemap, 4) | **44** | ~102 MB |
| Consolidated texts (`/texto` × 12,387) | 12,387 | — |
| Diary documents (`xml.php` × 68,458) | **68,458** | **~2.0 GB** (mean 29,155 B, median 19,784, n=24) |
| **Total** | **~80,890** | **≥2.1 GB** |

**4.8 h at 4 req/s** (`config.yaml`'s `requests_per_second`), 22 h at 1 req/s. The expensive
half is the per-document fetch, and **that** is what needs a permanent on-disk cache and a
resume point — not the discovery. Note `FileCache` has a 24-hour TTL, which is the wrong
policy for a document that can never change.

**The ELI sitemap is the cheapest index but it is not the Sección I population**, and this
is the one design point neither the probes nor the verifiers surfaced. Verified directly:
removing the 8,920 corrigenda leaves **94,150 base norms**, distributed by ELI type as
`res` 31,142 · `o` 25,681 · `rd` 17,772 · `l` 8,745 · `ai` 4,913 · `lf` 1,036 · `lo` 396.
Resoluciones and Órdenes are 56,823 of the 94,150, and most of those are published in
**Sección III, not I**. So the sitemap is the *ELI-identified* corpus: it overlaps Sección I
heavily (95.9 % title-level agreement on 1,582 numbered dispositions from three years) but it
is a different set — it includes Sección III material and excludes court rulings, which have
no ELI. Indexing from it and filtering on the fetched document's `seccion` field works and
costs nothing in index requests, but pays the filter in **~26,000 out-of-scope document
fetches** (≈1.8 h, 760 MB). The search filters by section server-side:

| Design | Index requests | Document fetches | Waste |
|---|---:|---:|---:|
| Summary sweep (the original design) | 14,926 | 68,458 | 0 |
| ELI sitemap alone, filtering on fetch | **4** | 94,150 | **~26,000** |
| **Search by section + sitemap for `lastmod`** | **44** | **68,458** | **0** |

### Known blockers

1. **`discover_all` raises `ImportError` today** (issue #99). `discovery.py:23` imports
   `iter_norms_from_catalog` from `catalogo.py`; that name has never existed. And it is not a
   rename — three things are out of joint: the name; the config **type** (discovery is built
   with a plain dict via `get_discovery_class(country).create({**cc.source, …})` while both
   functions in `catalogo.py` call `config.get_country("es")`); and the config **keys**
   (`normas_fijas`, `rangos` are gone from `config.yaml`). `discover_daily` is also never
   called — `cli.py:528` prefers `fetcher/es/daily.py`, which invokes `sumario.parse_summary`
   directly. **The class has no live caller in either direction**, and `es` is bootstrapped
   through `legalize fetch -c es --catalog` + `legalize commit --all`, bypassing discovery.
2. **`_LEGISLATIVE_SECTIONS = {"1", "1A", "T"}` accepts a code that does not exist.** Section
   `1A` appeared **0 times** across 131 + 25 + 18 + 22 summaries spanning 1970–2026, and the
   search's `ORIS` axis does not offer it. Old summaries carry a `codigo="5"` section named
   "V. Comunidades Autónomas" (8 days, 72 items) which is *not* general provisions, and
   `6A`/`6B`/`6C` for old-era anuncios.
3. **Rank codes the source uses and `_RANK_CODE_MAP` does not have**: `1676` Reforma, `1590`
   Corrección, `1240` Sentencia, `63` Providencia, `1250` Auto, `41` Nota Diplomática, `1220`
   Reglamento. **`1676` is dangerous, not merely missing**: `_parse_rank` returns `None`, so
   `_infer_rank_from_title` runs, and its first branch is `if "constitución" in lower →
   Rank.CONSTITUCION`. The fourth reform of the Constitution would today be typed as *the
   Constitution itself*. (Two functions are named `_infer_rank_from_title`; only
   `metadata.py:161` produces this.) Note `63` and `41` break the four-digit pattern — the
   two-digit case is a class, not an exception.
4. **`daily.py::_commit_reforms` can never admit a newly-consolidated old norm.** It does
   `if not repo.has_file(file_path): continue`, so a 1982 Real Decreto that the BOE
   consolidates for the first time in 2026 arrives in the `from`/`to` window with no file and
   is thrown away. This is the measured cause of the 86 missing norms — **42 of the 88 were published before 2026** — and it will keep costing ~130/year after the re-emission.
5. **`?from=&to=` truncates silently at 10,000 with an HTTP 200 and no total.** The margin
   is not "770× the daily volume of 13": the BOE re-stamped **9,980 norms in one week** of
   December 2025, and a backfill after an outage lands exactly there. A backfill must page
   the window until a page returns fewer items than requested.
6. **The Solr error surface.** A malformed `query` returns **500**, so a retry/backoff
   wrapper reads a client bug as a source outage. `limit=0` and past-the-end are the same
   empty 200, so a walk terminating on falsiness terminates on the first page if the page
   size is ever misconfigured. And a `range` on `identificador` is discarded in silence — so
   there is **no cursor walk**, and `sort` by `identificador` is the only thing that makes
   offset paging stable by construction (**72.7 % of entries share a `fecha_actualizacion`
   with another**; only 6,020 distinct timestamps for 12,387 rows, largest tie group 72).

### Recommended discovery design (resolves #99 and #66 together)

Full design, request costs and config keys: `00-DECISIONES.md` §3. In one paragraph:
`discover_all` walks the catalogue in **2 requests** with `query={"sort":[{"identificador":
"asc"}]}`, deduping by id and filtering the `robots.txt` suppression set. A sibling
`discover_published` takes its id list from **`/buscar/boe.php` filtered by section**
(40 requests, year-windowed for resumability, with the exact total up front), joins the
**ELI sitemap** (4 requests) for `lastmod` and for the jurisdiction segment that already
matches the repo's `es/` + 17 `es-*/` split, and uses **`/eli/eli-update-feed.atom`** for
the daily. The summary sweep stays as the documented fallback for any window where the
search's parsed count disagrees with the total the page itself declares. `normas_fijas` and
`rangos` do not come back: the catalogue is two requests, and the meaningful axis for the
diary is the **section**, which is what the source states.

**There is no cleaner endpoint behind the HTML, and this was checked rather than assumed.**
Loaded the search results page in a real browser and read every request it makes: **21
requests, of which zero are XHR or fetch** — the HTML document, two stylesheets, the logo
SVGs and one `desplegable.js` that drives the dropdown menus. Same on a second BOE page.
`boe.es` is server-rendered PHP end to end: the documented open-data API *is* the API, and
the search pages have nothing underneath them. So scraping the search HTML is not a shortcut
past a JSON endpoint — it is the only form this index takes, which makes the count assertion
below load-bearing rather than optional.

Two caveats on the search, both measured. It is **HTML and undocumented**, so the design must
assert its parsed id count against the `de N` total the page prints and fall back on
mismatch; and `id_busqueda` is an opaque server-side token of unknown TTL (walked across 3
requests over ~5 s, not tested for longer), which is why the walk is windowed by year — that
bounds recovery to re-issuing one window. Its fidelity as a census is established: against
the summary API on four independently chosen windows it matched **6 vs 6, 20 vs 20, 5 vs 5**
and **87 vs 87** over a contiguous fortnight, with zero items on either side only.

---

## §0.7 Format coverage — **GATE: PASS for file formats; FAIL on the fidelity requirement it exists to protect**

```
GATE §0.7 (every format contributing >1 % of unique laws or unique versions is covered):
  **PASS.** Spain is a single-format source twice over. The consolidated corpus is XML-only
  and the diary surface is XML-only. Every alternative manifestation contributes 0 unique
  laws and 0 unique versions.
```

### Shape A — the consolidated corpus

| Format | Endpoint | Laws | Versions | Unique | Verdict |
|---|---|---|---|---:|---|
| **XML** | `/api/legislacion-consolidada/id/{id}/texto` | 46/46 sampled, 200 with content | all 5,252 versions of 3,989 blocks | **all** | covered |
| HTML | `/buscar/act.php?id=` | same set | current text only, no `<version>` markup | 0 | skipped |
| PDF | `url_pdf` (12,298/12,299 files) | same set | the original gazette page, not the consolidated text | 0 | skipped |
| EPUB | `url_epub` (5,269/12,299) | subset | current text only | 0 | skipped |

Written justification, as the playbook requires: *HTML, EPUB and PDF are alternative
renderings of text the XML already carries in full, minus the
`<version fecha_publicacion= fecha_vigencia=>` attributes the whole pipeline is built on.
Covering them would add zero laws and zero versions and would lose the version markup.*
There is no cross-format boundary, so no before/after check to run.

### Shape B — the non-consolidated acts

Also single-format XML, and **there is no PDF-only era**. This was the open risk and it is
closed: `xml.php?id=` returned full `<texto>` for 21 of 21 documents sampled one per era from
1835 to 2025, and for 4 more drawn from summaries specifically because they are absent from
`countries/es`.

**But the "from what year" question has no answer as a year, and three probes each got a
different one before the refutations settled it.** Text availability is a property of the
individual document:

- **20 of 20** documents sampled from the consolidated catalogue between **1889 and 1974**
  have populated `<texto>` — the 1889 Código Civil has 639,684 characters and **1,992
  `<p class="articulo">`** — with the same class vocabulary a 2026 act uses and no legacy
  uppercase family anywhere below 1975.
- **Empty `<texto/>` occurs in 1981 and 1984**: `BOE-A-1981-50082` and `BOE-A-1984-50024`,
  both Reales Decretos of Sección I, both with titles ending `(Conclusión.)` /
  `(Continuación.)` and ids in a separate `5xxxx` band — the tail fragments of an act
  serialised across several gazette issues, where the head carries the text and the
  continuations carry none.
- On a single 1970 day, a complete Sección I census gives **5 of 14 populated**; excluding
  the one consolidated norm, **4 of 13** non-consolidated acts have text.
- The pooled post-1975 rate on complete days is **34 of 36 = 94.4 %**, not 100 %.
- There is **no intermediate "scanned body" state**: 0 `<img>`-only bodies and 0 stubs in 93
  documents. It is full text or a literal `<texto/>`. And `txt.php` — the official HTML view
  — is equally empty for the empties, so the text exists only in the PDF.

Why the probes disagreed, because it is the pattern to remember: the probe that reported
"full text since 1835" sampled documents that were **also consolidated**, and the BOE
retro-digitised text only for what it consolidated. Below 1975 the BOE loaded ~2,000
selected acts/year into a low id sequence and the rest into a high block, so a
summary-driven sample sees a cliff that belongs to the document universe, not to the text.

**Two populations, two rules — the year cut applies to only one of them.** The consolidated
catalogue is taken whole, 1835→today, exactly as the repo does now: **427 of its norms were
published before 1979 and all 427 are already in the corpus**, the oldest being
`BOE-A-1835-2348` (a Real Orden of 30 October 1835), with the Ley del Notariado of 1862 and
the 1889 Código Civil among them. The year cut governs the **diary sweep** only — the new
~68,458. A floor of 1975 applied to discovery rather than to the sweep would have dropped
286 published laws.

**And within the sweep: no year floor either. Use the text gate** — skip the document when
`<documento><texto>` is empty. Free (the document is already in hand), exact in 1889 and in
1984 alike, and a 1975 discovery floor would have **dropped 286 already-published laws
including the Código Civil and the Ley Hipotecaria**.

One trap for whoever writes it: `<texto>` is **not unique** in a diary document.
`<analisis><referencias><anterior><texto>` exists and `root.find(".//texto")` matches it
first. Two independent agents hit this today, and the symptom is a silent zero-character
render, not an error — indistinguishable from a legitimately empty pre-1975 document. It is
`root.find("texto")`, a direct child of `<documento>`.

### The gate passes and the requirement behind it fails

§0.7 exists to protect priority 1, *"the rendered Markdown must be identical to the official
law"*. Spain passes the format-coverage gate and **fails that requirement**, in a way no
check in the pipeline can currently see:

**Four acts of 76 carry 2.1 % of their official text. The rest is page-sized bitmaps.**

| Act | Official pages | PDF text chars | XML `<texto>` chars | Coverage | `<img>` |
|---|---:|---:|---:|---:|---:|
| `BOE-A-2014-13617` (perfiles de consumo eléctrico) | 198 | 686,754 | 7,235 | **1.1 %** | 196 |
| `BOE-A-2011-20544` (precios de referencia de medicamentos) | 183 | 904,793 | 18,620 | **2.1 %** | 182 |
| `BOE-A-2011-20545` | 22 | 124,738 | 7,614 | 6.1 % | 20 |
| `BOE-A-2003-12865` | 8 | 18,044 | 2,991 | 16.6 % | 7 |
| **Aggregate** | **411** | **1,734,329** | **36,460** | **2.1 %** | **405** |

Controls on the same method: `BOE-A-2014-13618` 96.5 % coverage (0 images) and
`BOE-A-2024-13049` 176 % (the XML transcribes tax-form annexes the PDF draws as forms — the
XML is *richer* there). So the measure is not broken.

One of the images was fetched and opened: `disp/2014/315/13617_5290.png`, 228 KB,
**2126 × 2493 px** — a full page at ~250 dpi — and it is **ANEXO I of the Resolution as
ordinary legal prose**: bold headings `1- Objeto`, `2- Ámbito de aplicación`, a lettered
list, superscripted profile names. Not a figure, not a formula. The articulated text of the
annex, delivered as a bitmap, 196 times. What the renderer emits for that act is ~25 lines
of preamble followed by 196 image links.

Counted by act it is a 5.3 % problem; counted by **printed law**, which is what a reader
loses, it is **411 of 1,618 sampled gazette pages = 25.4 %**. The worst case is **2014**, so
this is neither a pre-1975 nor a legacy problem. **And it is already shipped**: 1,400 of the
8,690 `es/` files (16.1 %) carry at least one image line, 22,059 image lines in total, and in
**20 files more than 30 % of non-blank lines are image links** — `BOE-A-2020-17283.md` is 180
image lines out of 274.

The detector is free and belongs in the re-emission:
`chars(<texto>) / (pagina_final − pagina_inicial + 1)`, from the document's own metadata,
zero extra requests. Median over 76 acts: **2,896 chars per official page**; the four flagged
acts sit at 37, 102, 346 and 374.

```
REQUIREMENT (priority 1, perfect text fidelity):  **FAIL, on ~5 % of acts and ~25 % of
gazette pages**, on both surfaces, undetected until now. Recommended: keep the acts, add
the density gate, and MARK them in the frontmatter rather than dropping them silently.
```

### Structure recovery from `@class`: works, or is absent, with no in-band signal

The diary XML uses the **same `p/@class` vocabulary as the consolidated XML**, so the
paragraph dispatch is reusable verbatim. Where `class="articulo"` is present it is exact —
100 % recovery against the consolidated precepto count in 6 of 10 dual-surface acts, 99.2 %
and 98.9 % in two more. But:

- **A regex fallback on the paragraph text is mandatory, not optional — measured on 420
  acts.** The probes' conclusion that *"a parser recovers the article tree from `@class`
  alone; no regex fallback is needed"* is false for a quarter of the population that issue
  #66 would add. Running the engine's own unmodified paragraph dispatch over 339 acts the
  proposed rule would emit as laws: **147 (43.4 %) render with zero headings**, of which
  **78 (23.0 %) have text that plainly opens paragraphs with `Artículo` / `Art.` /
  `Disposición` and no `class="articulo"` anywhere** — a real structure loss — while the
  other 69 (20.4 %) are legitimately flat prose (short Órdenes, correcciones). Type
  specimens, verified in the raw XML: `BOE-A-1993-15903` (Real Decreto 819/1993) has **482
  paragraphs, every one `class="parrafo"`**, with `Artículo único.`, `Artículo 1.`,
  `Artículo 2.` as plain paragraphs; `BOE-A-1997-1451` (Ley 10/1996) has 107, all `parrafo`.
  The same regex that detects the problem recovers the structure — it found 96 articles in
  RD 819/1993 where `@class` found none — so the fix and the detector are one line.

- **And the failure has a shape, which is what makes it manageable.** It depends jointly on
  the era *and* on whether the BOE consolidated the act, and the two had never been
  separated:

  | | n | with `class="articulo"` | articulated but unmarked |
  |---|---:|---:|---:|
  | Consolidated | 53 | 52 (98 %) | **0 %** |
  | **Non-consolidated** | 286 | 130 (45 %) | **27 %** |

  Within the non-consolidated population — the one #66 adds — the failure rate by sampled
  year is **0 % in 1979**, then **67 % (1984), 36 % (1989), 50 % (1993), 62 % (1997), 61 %
  (2001), 45 % (2005)**, and **0 % in 2009, 2013, 2017, 2021 and 2025**. So the diary
  surface is structurally sound for **2009→today** and for the earliest era, and unreliable
  for roughly **1984–2005**. A free per-act detector exists — `looks_articulated and not
  has_articulo_class`, which fires on 23.9 % of emitted acts — so this is gateable rather
  than merely known.

- **The legacy uppercase `@class` family is a real but much smaller thing** than the
  structure failure above, and it is not its cause. It appears in **20 of 339 acts (5.9 %),
  all of them in 2005**, and all 20 render with zero headings. The top offenders of the
  23.0 % carry `upper=0`, i.e. plain lowercase `parrafo`. Two separate defects, one of which
  the earlier evidence conflated with the other.

- **`class="articulo"` means "numbered unit", not "article".** 219 paragraphs in 25 of 40
  documents beginning *Disposición adicional / transitoria / derogatoria / final* carry it.
- **The group heading that disambiguates them is unmapped.** `DISPOSICIONES ADICIONALES`
  rides on bare `<p class="capitulo">`, which is in neither `_SIMPLE_CSS_MAP` nor
  `_PAIRED_CLASSES` (only `capitulo_num`/`capitulo_tit` are), so it becomes body text. Bare
  `capitulo` appears in 9 of 40 documents and **133 times in 21 diary documents**. Combined,
  the Constitution renders from the diary surface with **eight identically-titled H6
  headings** and the heading that separated them demoted to prose — and since anchors are
  generated from heading text, that is an anchor-collision generator.
- **150 BOE block-type sentinels leak into the text** in 25 % of documents:
  `[precepto]` 89, `[encabezado]` 41, `[ignorar]` 20, `[firma]` 1. They render verbatim
  (`###### [precepto]Primera.`), they do not exist on the consolidated surface, and they pass
  every artifact test the pipeline has because they are not HTML. **Consumed instead of
  stripped they fix the two items above for free** — `[encabezado]` promotes the group
  heading, `[precepto]` marks the unit — since they are the only in-band block-type signal
  the diary surface has. `[ignorar]` is the source saying *this paragraph is not part of the
  act*, and it needs a decision rather than a default.
- **0 `<a>` elements in the diary surface** (0 in 60 and in 76 documents). The consolidated
  files have them, so a mixed corpus has clickable cross-references in one half and none in
  the other. The amendment graph is present in `<analisis><referencias>` (220 `<anterior>` +
  225 `<posterior>` in one sample) so document-level links can be synthesised.
- **Co-official language versions inflate organic laws 4.47×.** `BOE-A-2026-10881` is the
  same act five times (es/eu/ca/gl/va) in one `<texto>`; Castilian is **22.3 %** of it.
  Detectable structurally (each translation opens with a `centro_cursiva` preamble heading)
  and from the metadata (`url_pdf_catalan` / `_euskera` / `_gallego` / `_valenciano`
  populated). Decide it deliberately: these are the most-read documents in the corpus.

**Conclusion for the parser:** a class allow-list is not enough. The re-emission must
**instrument** — log and count every unmapped `@class`, and refuse to publish a document
that ends with zero headings. There is also a free per-act oracle for anything that exists on
both surfaces: compare the `class="articulo"` count against the consolidated precepto count.

### One item flagged, not skipped

The frontmatter shows official **translations** as separate PDFs: Catalan on **3,007 files
(24.5 %)**, Galician 2,378 (19.3 %), Valencian 563 (4.6 %), Basque 353 (2.9 %). That is a
language dimension, not a format dimension, so §0.7 does not bite — but it is official text
of which we publish nothing, and 24.5 % is well over any 1 % line. Decision needed, out of
scope here.

---

---

## Dry run — the proposed rule executed over 420 real acts

The rest of this document is measurement of the source. This section is different: it is the
**proposed design run end to end**, because a design nobody has executed is not a validated
design. Everything the probes produced about the scope rule came from hand classification of
63, 75 or 98 acts; the structure claim came from 2 documents in 60.

**Method.** 12 years spread 1979–2025, one search request each for the year's complete
Sección I id list (which also tested the index side: **11 of 12 years matched their declared
total exactly**, and 1984 declared 2,519 against 2,000 parsed — `page_hits` truncating, which
the recommended count assertion caught on its first real use). Then a seeded random sample of
35 ids per year — **420 acts, all HTTP 200** — fetched as diary XML at 1 req/s. Each act was
run through the decision procedure of `00-DECISIONES.md` §2 and its body through the engine's
**own unmodified paragraph dispatch** (`_parse_p`, `_table_paragraph`, `_parse_blockquote`,
`_image_paragraph` → `render_paragraphs`), not a reimplementation. 432 requests. Harness and
raw XML: `/Users/neli/.claude/jobs/5bf7ddf4/tmp/dryrun/`.

| Step of the rule | Fires on | Rate | Against the earlier claim |
|---|---:|---:|---|
| **3 — drop, not a norm** (`rango ∈ {1590,1240,63,1250}` ∪ `<palabra> ~ /^(CORRECCIÓN\|CORRIGE)/`) | 75 / 420 | **17.9 %** | consistent with 19.0 % and 22.5 % from two hand censuses |
| — caught by `<palabra>` and *not* by `rango` | 3 | 0.7 % | confirms the verifier: the rank field alone is insufficient |
| — caught by `rango` and *not* by `<palabra>` | 32 | 7.6 % | `rango` does the bulk; both keys are needed |
| **4 — text gate** (`<documento><texto>` empty) | 6 / 345 | **1.7 %** | only 1979 and 1984, confirming a per-document floor, not a year |
| **5 — density gate** (<600 chars/page and ≥5 images) | 4 / 420 | **1.0 %** | the verifier's 5.3 % came from days picked for hard content; 1.0 % is the random-sample rate. Worst: `BOE-A-2017-3366`, **62 pages, 3,939 chars, 63.5 chars/page, 61 images** |
| **oracle** (`estado_consolidacion` vs catalogue membership) | 419 / 420 agree | **1 disagreement** | **the previously reported 48/48 and 159/159 do not hold at n=420** — see below |
| BOE block-type sentinels (`[precepto]`, `[encabezado]`, `[ignorar]`) surviving into the render | 10 docs, 46 occurrences | **2.9 %** | lower than the 25 % of documents reported on a 60-doc sample, but real |

**Two findings that change instructions written elsewhere in this document.**

1. **The oracle is not exact, and the safe form of the test is the opposite of what was
   first recommended.** `BOE-A-2001-3498` (Ley Foral 17/2000) carries
   `estado_consolidacion codigo="1"` — a value `/api/datos-auxiliares/estados-consolidacion`
   does not declare (it lists only `3` and `4`) — with an empty body, absent from the
   catalogue, and **404 on both `/texto` and `/metadatos`**. It is non-consolidated, and a
   test of `codigo != "0"` classifies it as consolidated. The domain drifts in both
   directions (a `Sin consolidar` label also survives in one published file), so the test
   must be **positive on the documented values and log anything outside `{0,3,4}`**. For the
   bootstrap, catalogue membership remains the authority.

2. **The structure failure is 23.0 %, not 3.3 %, and its cause is not what was diagnosed** —
   full numbers in §0.7 above. The short version: `class="articulo"` is present on 98 % of
   consolidated acts and 45 % of non-consolidated ones, and among the non-consolidated the
   articulated-but-unmarked rate runs 0 % (1979), 36–67 % (1984–2005), 0 % (2009→2025).

**What the dry run did not cover**, so it is not read as more than it is: it exercises steps
3, 4 and 5 and the body dispatch. It does not exercise the freshness gate (which needs
acts younger than 180 days), the `text_state` override (no code exists), `last_amendment`
derivation, the commit path, or the residue decision — the residue is a policy question and
running a rule cannot answer it. And 420 of ~78,908 is 0.53 %: the per-year failure rates
rest on ~25 emitted acts per year, so their ordering is solid and their second digit is not.

## Step 7 — the quality gate has **never been run on `es`**

```
GATE §7 (5/5 laws PASS on all 5 checks):  **NEVER RUN.**
```

Issue #106 audited `legalize-es` for conformance with spec v0.4 — identifiers, frontmatter,
dates, commit format, history. It did not compare the Markdown against the BOE, and nothing
else has. This pass is the first time any of it was measured, and it found four real losses
(§0.4), one systemic rendering hazard affecting 76.4 % of files (§0.4), 622 blocks of
repealed law published as current text (§0.3), and a fidelity failure on ~25 % of gazette
pages (§0.7). **Step 7 must run against the re-emitted output before it is pushed**, and its
five laws should include one image-substituted act and one act that exists only on the diary
surface.

---

## Gate summary

| Gate | Verdict | Basis |
|---|---|---|
| **§0.1** source identified, licensing, robots.txt, historical reach | **PASS** | two surfaces documented, `robots.txt` read in full (13,901 lines), summary floor pinned to 1960-09-01 |
| **§0.2** five fixtures saved | **FAIL — not done** | `tests/fixtures/es/` does not exist; ids selected in §0.2, saving them is an action item |
| **§0.3** metadata inventory | **PASS** | full table, 3 surfaces, 21 fields missing / 5 wrong / 4 partial identified with `file:line` |
| **§0.4** formatting inventory | **PASS** | measured percentages with Wilson intervals over 46 sampled documents plus an exhaustive census of 12,299 files |
| **§0.5** version-history spike (≥2 dated versions, source classified) | **PASS** | 214 versions / 5 dated amending acts on one law; 11,379 versions over 8 laws; `fecha_vigencia` on 100 % of stamps; classified MIXED (`point_in_time` consolidated / `as_enacted` diary) |
| **§0.6** scope estimated | **PASS** | exact counts on both populations; bootstrap costed at ~80,850 requests / ≥2.0 GB / 4.8 h; six blockers named |
| **§0.7** format coverage >1 % rule | **PASS** | single-format XML on both surfaces; every alternative contributes 0 unique laws and 0 unique versions, justified in writing |
| **priority 1** perfect text fidelity | **FAIL** | ~5 % of acts carry ~2 % of their official text; ~25 % of sampled gazette pages are bitmaps; 167,666 ordered-list runs renumber on render; 115,948 lines render as code blocks |
| **§7** five-law quality review | **NEVER RUN** | #106 audited conformance, not fidelity |

**Two gates fail and one has never been run.** §0.2 is an hour of work. §7 belongs after the
parser changes. Priority 1 is the finding of this pass, and it is not blocked on measurement
any more — it is blocked on a decision about what to do with an act whose text the BOE
publishes only as a picture.

---

## Reproducibility

Every number above is either exhaustive over the published corpus (stated as "of 12,299")
or carries its sample. Numbers a verifier could not reproduce are **not used in this
document**; they are listed with both values in `00-DECISIONES.md` §6, and the two most
consequential are worth naming here because earlier drafts of this research rested on them:

- The population of issue #66 was estimated at 121,896 acts (repo → ~122,000, 10×) from 30
  sampled days. The exact count is **90,603** for Sección I + T and **78,908** for Sección I.
  Two verifiers with different query constructions reached the same figures to the digit,
  and I re-verified 78,908 by hand.
- "The daily summary is the only index; nothing else enumerates" was wrong, and with it the
  14,926-request / 2.03 GB discovery design. It is not advertised in `robots.txt` and it is
  not at the site root — `/eli/sitemap.xml` is linked in prose from `/legislacion/eli.php`.

And one correction this document makes to the verifiers, not to the probes. Two verifiers
independently recommended the ELI sitemap as *the* index for the non-consolidated population.
Enumerating it directly shows it is a **different population**: 94,150 base norms dominated
by Resoluciones and Órdenes, most of which are published in Sección III. It is the right
source for `lastmod` and for the shard key, and the wrong one for a section-scoped id list —
using it alone costs ~26,000 out-of-scope document fetches. The recommendation in §0.6 is
therefore the search for the id list and the sitemap for change detection, which is neither
of the two designs proposed to this document.

The one number in the decision memo that is extrapolated rather than measured is the share
of the non-consolidated population that the drop rule removes (~21 %, from two independent
censuses measuring 19.0 % and 22.5 %). Everything downstream of it is labelled accordingly.

---

**Next → `engine/research/es-v2/00-DECISIONES.md`** for the scope decision, the corrected
cut rule, the discovery design with its cost, the `text_state` override, and the open
questions ordered by what it would cost to get each one wrong.

---

## What in this document was re-verified independently, and what was not

The evidence base is 8 probes and 12 verifiers. Their numbers were not taken on trust
wholesale; the ones that decide something were re-measured directly before being written
down. Recording the split so a reader knows which is which.

**Measured directly for this document (not from an agent):** the Sección I counts for every
cut year (112,251 / 86,335 / 78,908 / 38,347 / 23,012); the catalogue enumeration and the
per-cut consolidated counts; all three ELI sitemaps enumerated in full (103,070 unique
`<loc>`, 18 jurisdictions, 8,920 corrigenda, 1851→2026, and the ELI type distribution that
shows it is a different population from Sección I); the Atom feed's existence; the absence
of `tests/fixtures/es/`; the arithmetic of every row of the volume table; and the browser
network trace above.

**Re-verified against the corpus and the code, zero HTTP:** 12,299 files and 8,690 in `es/`;
0 files with `text_state` and 0 with `last_amendment`; 1,152 files and 115,948 lines of
4+-space indentation, split 79,176 / 35,522 / 1,241 / 9 by width; 159,696 HTML tags split
94,680 `<small>` / 34,518 `<sub>` / 30,479 `<sup>` / 19 `<p>`-`<td>` leaks; 0 mojibake and 1
file with U+FFFD; the ordered-list census at 42.9 % (391,418 runs, 167,854 broken, 9,406
files — reproducible only with CommonMark-correct run segmentation, where a single blank
line does not close the list; a naive line-by-line rule gives 73.4 % and is wrong);
`fecha_caducidad` and `caduca` read by nothing in `src/`; `effective_date` reaching exactly
three places outside `fetcher/` (the dataclass, the round-trip that destroys it, the line
that sets it); `text_state` set by no parser except `pt`; all seven rank codes absent from
`_RANK_CODE_MAP`; `frontmatter.py:70-72` emitting the key only when the state is not
`POINT_IN_TIME`; and 28 of 29 spot-checked code citations landing within three lines.

**Corrected during that pass, because the source figures were wrong:** the missing-norm
cohort is **42 of 88 published before 2026**, not 74 of 86 — two probes reported 74 and a
third reported the correct distribution; the 12-space indentation bucket is 1,241 and not
1,270; the `_reference` guard is at `metadata.py:372` and `parse_metadata` at `:243`.

**Still taken on the agents' word**, because re-measuring costs HTTP that the budget did not
allow twice: the 11,379/11,379 block-level `fecha_vigencia` and the 96.4 % divergence; the
1,281 / 622 `fecha_caducidad` blocks; the 2.1 %-of-PDF fidelity measurement; the membership
confusion matrices (79/79, 41/41 — the 48/48 and 159/159 were re-tested here and did
not hold); the 0.892 Sección I share; and the
consolidation-lag distribution. Each was produced by a probe and survived an adversarial
verifier with a disjoint sample, which is the strongest evidence available short of a third
measurement — but they are not first-hand here, and the two that would most change a
decision if wrong are the fidelity figure and the 0.892 constant.
