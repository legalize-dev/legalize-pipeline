# ES v2 — Probe 5: metadata inventory (playbook §0.3)

**Date:** 2026-09-03 · **Scope:** every field the BOE exposes on the three surfaces that
feed `fetcher/es`, checked field by field against the code that parses it and against the
12,299 files published in `countries/es` at `origin/main` (commit `cc3d021`, 2026-07-03).

**HTTP requests made by this probe: 87** (all `200`, no `429`, no `5xx`; ≥0.8 s apart,
`User-Agent: legalize-bot/1.0`).

---

## 0. Method and sample

Nothing here is read from a docstring. Every row was taken from response bytes fetched
today, or counted over the published corpus on disk.

| Evidence | What it is | Size |
|---|---|---|
| **S1 — surface sample** | 14 norms fetched on all surfaces (`/metadatos` + `diario_boe/xml.php`, plus `/texto` for 6) | 14 norms, 37 requests |
| **S2 — status sample** | 46 norms drawn deterministically (`random.seed(20260903)`) from the corpus: 30 `repealed`, 8 `expired`, 8 `annulled`; `/metadatos` only | 46 norms, 46 requests |
| **S3 — consolidation probe** | `BOE-A-2006-2779`, `BOE-A-2026-18282` re-fetched to read `estado_consolidacion@codigo` | 2 requests |
| **S4 — diary re-fetch** | `BOE-A-1978-31229`, `BOE-A-1893-6023` re-fetched for exact attribute values | 2 requests |
| **S5 — diary union** | 54 `diario_boe/xml.php` documents present in the shared scratch dir: the 14 of S1 plus 40 fetched by a sibling probe of this same run. Used only for the *union of elements* and the verb census | 54 documents |
| **S6 — consolidated-text union** | 53 `/texto` documents in the same scratch dir (6 mine, 47 a sibling's) → **9,723 `<bloque>`, 16,417 `<version>` stamps** | 53 documents |
| **S7 — published corpus** | every `.md` under `countries/es` — frontmatter keys, value domains, reference verbs | **12,299 files** |

S1 ids: `BOE-A-1978-31229` (Constitution), `BOE-A-1889-4763` (Código Civil),
`BOE-A-1995-25444` (Código Penal, the worst reference truncation), `BOE-A-2015-10565`
(ordinary law), `BOE-A-2010-10544` (LSC — the suspension case), `BOE-A-2007-6820`
(regulation with tables), `BOE-A-2006-20764` (IRPF, tariff tables), `BOE-A-1893-6023`
(repealed, with `fecha_derogacion`), `BOE-A-1980-8656` (judicially annulled),
`BOE-A-1986-18158` (validity exhausted), `BOE-A-1984-25793` (CCAA — País Vasco),
`BOE-A-2026-18282` (CCAA — Madrid, was "Sin consolidar"), `BOE-A-2006-2779` (was
"Desactualizado"), `BOE-A-1954-88` (international agreement, Gaceta era).

Surface codes used in the table below:

| Code | Surface |
|---|---|
| **C** | catalogue item — `GET /api/legislacion-consolidada?limit=N&offset=M` |
| **M** | `GET /api/legislacion-consolidada/id/{id}/metadatos` |
| **D** | `GET /diario_boe/xml.php?id={id}` → `<documento><metadatos>` |
| **A** | same document → `<documento><analisis>` |
| **E** | same document → `<documento><metadata-eli>` (ELI/RDF) |
| **T** | `GET /api/legislacion-consolidada/id/{id}/texto` → `<bloque>` / `<version>` attributes |

---

## 1. The §0.3 table

`file:line` refers to `engine/src/legalize/`. "FM" = reaches the published frontmatter.

### 1.1 Fields the pipeline reads today

| Source field | Surface(s) | Type | Example | Parsed today (file:line) | FM? | Verdict |
|---|---|---|---|---|---|---|
| `identificador` | C M D | string | `BOE-A-1978-31229` | `fetcher/es/metadata.py:274` | `identifier` | OK |
| `titulo` | C M D | string | `Constitución Española.` | `metadata.py:275` | `title` | OK |
| `departamento` (text) | C M D | string | `Cortes Generales` | `metadata.py:277` | `department` | OK |
| `departamento@codigo` | C M D | code | `1220` | `metadata.py:309` | `department_code` | OK |
| `rango` (text) | C M D | string | `Constitución` | `metadata.py:132` | via `rank` | OK |
| `rango@codigo` | C M D | code | `1070` | `metadata.py:128`, `:310` | `rank_code` | OK |
| `ambito` (text) | C M | string | `Estatal` / `Autonómico` | `metadata.py:328` | `scope` | OK |
| `ambito@codigo` | C M | code `1`/`2` | `1` | `metadata.py:225`, `:311` | `ambito_code` | OK |
| `fecha_publicacion` | C M D | `YYYYMMDD` | `19781229` | `metadata.py:286` | `publication_date` | OK |
| `fecha_disposicion` | C M D | `YYYYMMDD` | `19781227` | `metadata.py:313` | `enactment_date` | OK |
| `numero_oficial` | C M D | string | `10/1995` | `metadata.py:312` | `official_number` | OK — absent on 5/14 of S1 and on 1,772/12,299 corpus files, correctly omitted |
| `diario` (text) | C M D | string | `Boletín Oficial del Estado` | `metadata.py:316` | `official_journal` | OK |
| `diario_numero` | C M D | string | `311` | `metadata.py:317` | `journal_issue` | OK |
| `fecha_vigencia` | C M D | `YYYYMMDD` | `19781229` | `metadata.py:290` → `NormMetadata.last_modified` | **no** | **missing** — see §2 |
| `estatus_derogacion` | M D | `S`/`N` | `S` | `metadata.py:144` | via `status` | OK — see §3 |
| `fecha_derogacion` | M D | `YYYYMMDD` | `20140925` | `metadata.py:318` | `repeal_date` | OK |
| `estatus_anulacion` | M | `S`/`N` | `S` | `metadata.py:150`, `:321` | `annulment_status` (only if ≠`N`) | OK |
| `vigencia_agotada` | C M D | `S`/`N` | `S` | `metadata.py:154`, `:324` | `validity_exhausted` (only if ≠`N`) | OK — but see §3 for what it actually means |
| `estado_consolidacion` (text) | C M D | string | `Finalizado` | `metadata.py:327` | `consolidation_status` | **wrong** — the element carries a `codigo` and we store only the label; see §1.3 |
| `url_eli` | C M D | url | `https://www.boe.es/eli/es/c/1978/12/27/(1)` | `metadata.py:294`, `:329` | `source`, `url_eli` | OK |
| `url_html_consolidada` | C M D | url | `.../buscar/act.php?id=BOE-A-1978-31229` | `metadata.py:295`, `:330` | `url_html_consolidada` | OK |
| `url_pdf` | D | path/url | `/boe/dias/1978/12/29/pdfs/A29313-29424.pdf` | `metadata.py:401-404` | `pdf_url` **and** `url_pdf` | **wrong** — written twice, identical in 12,298/12,299 files |
| `url_epub` | D | url | `https://www.boe.es/diario_boe/epub.php?id=BOE-A-2015-10565` | `metadata.py:406` | `url_epub` | **wrong** — source shape changed, now always lost; see §1.3 |
| `url_pdf_catalan` | D | path | `/boe_catalan/dias/2010/07/03/pdfs/…-C.pdf` | `metadata.py:407` | `url_pdf_catalan` | OK |
| `url_pdf_euskera` | D | path | `/boe_euskera/dias/2015/10/02/pdfs/…-E.pdf` | `metadata.py:408` | `url_pdf_euskera` | OK |
| `url_pdf_gallego` | D | path | `/boe_gallego/dias/2010/01/19/pdfs/…-G.pdf` | `metadata.py:409` | `url_pdf_gallego` | OK |
| `url_pdf_valenciano` | D | path | `/boe_valenciano/dias/2010/07/03/pdfs/…-V.pdf` | `metadata.py:410` | `url_pdf_valenciano` | OK |
| `pagina_inicial` | D | int | `29313` | `metadata.py:411` | `page_start` | OK |
| `pagina_final` | D | int | `29424` | `metadata.py:412` | `page_end` | OK |
| `letra_imagen` | D | letter | `A` | `metadata.py:413` | `image_marker` | OK |
| `estatus_legislativo` | D | letter | `L` | `metadata.py:414` | `legislative_status` | OK — constant `L` in 12,299/12,299 corpus files; domain unknown |
| `analisis/materias/materia` (text) | A | list[string] | `Constitución Española` | `metadata.py:424-428` | `subjects` | partial — `@codigo` dropped, see §1.2 |
| `analisis/alertas/alerta` (text) | A | list[string] | `Derecho Constitucional` | `metadata.py:429-433` | `alerts` | partial — `@codigo` dropped; the key name is misleading (these are BOE topic channels, not warnings) |
| `analisis/referencias/anteriores/anterior` | A | list | `DEROGA BOE-A-1977-165` | `metadata.py:357-374`, `:436-441` | `references_previous` | partial — see §4 |
| `analisis/referencias/posteriores/posterior` | A | list | `SE MODIFICA BOE-A-2026-10881` | `metadata.py:357-374`, `:442-464` | `references_subsequent` (+`_count`) | partial — see §4 |
| `bloque@id` | T | string | `a127` | `transformer/xml_parser.py:354` | no (drives block identity) | OK |
| `bloque@tipo` | T | enum | `precepto` | `xml_parser.py:355` | no | OK — never emitted; see §5 |
| `bloque@titulo` | T | string | `Art 127` | `xml_parser.py:356` | no | OK |
| `version@id_norma` | T | BOE id | `BOE-A-2000-323` | `xml_parser.py:345` | commit `Source-Id` | OK |
| `version@fecha_publicacion` | T | `YYYYMMDD` | `20000108` | `xml_parser.py:331` | `last_updated`, commit date | OK |
| `version@fecha_vigencia` | T | `YYYYMMDD` | `20010108` | `xml_parser.py:332` → `Version.effective_date` | **no** | **missing** — see §5 |

### 1.2 Fields the source exposes and we drop silently

Every one of these is present in the bytes we already download; none needs an extra
request.

| Source field | Surface(s) | Type | Example | Present in | Verdict |
|---|---|---|---|---|---|
| `fecha_actualizacion` | C M | timestamp | `20260520T074424Z` | 14/14 of S1, 46/46 of S2, every catalogue item | **missing** — this is the field `daily.py` discovers on, and nothing in the file records which BOE consolidation the body corresponds to |
| `documento@fecha_actualizacion` | D | timestamp | `20260520095602` | 54/54 of S5 | **missing** — a *different* timestamp from the one above for the same norm (07:44Z vs 09:56); it dates the diary entry, not the consolidation |
| `fecha_anulacion` | M D | `YYYYMMDD` | `19860620` | 1/14 of S1, 8/46 of S2 | **missing** — we write `annulment_status: "S"` and throw away the date. 24 corpus files say `status: annulled` with no date |
| `seccion` | D | code | `1`, `3`, `5`, `G` | 54/54 of S5 (49×`1`, 3×`G`, 1×`3`, 1×`5`) | **missing** — `1` = *I. Disposiciones generales*, `G` = Gaceta de Madrid. This is the field that classifies an act for the non-consolidated corpus |
| `subseccion` | D | code | (empty on 54/54) | 54/54 | missing, but empty everywhere observed |
| `diario@codigo` | D | code | `BOE`, `GAZ` | 54/54 (52×`BOE`, 2×`GAZ`) | **missing** — the machine key for the 280 corpus files whose `official_journal` is a regional gazette or the Gaceta |
| `origen_legislativo` (+`@codigo`) | D | `1`/`2` | `Estatal` | 54/54 | missing — duplicates `ambito`; harmless |
| `judicialmente_anulada` | D | `S`/`N` | `N` | 54/54 | missing — the diary's name for `estatus_anulacion`; harmless duplicate |
| `suplemento_pagina_inicial` / `_final` | D | int | `1` / `624` | 54/54 (empty on most) | **missing** — the page range in the supplement, needed to cite CCAA acts published as BOE supplements |
| `suplemento_letra_imagen` | D | letter | `C`, `R` | 54/54 | **missing** |
| `materia@codigo` | A | code | `1616` | 517 `<materia>` in S5, 364 distinct codes | **missing** — we store the Spanish label and drop the stable thesaurus id |
| `materia@orden` | A | int | `1` | 517 | missing |
| `alerta@codigo` | A | code | `111` | 74 `<alerta>` in S5, 24 distinct | **missing** |
| `analisis/notas/nota` (+`@codigo`, `@orden`) | A | list | `151` → *"Esta disposición ha dejado de estar vigente"*; `9` → *"Entrada en vigor, con la salvedad indicada, el 24 de mayo de 1996"*; `149` → *"Esta norma se entiende implícitamente derogada por Real Decreto 798/1995…"* | **37 notes in 30 of 54 documents** | **missing — the worst of them.** `<notas>` is never touched by `_parse_diario_xml`. It carries implicit repeals, real entry-into-force dates in prose, and the gazette of original CCAA publication. 12 distinct `@codigo` values in S5 |
| `anterior@orden` / `posterior@orden` | A | int | `1010` | 1,027 references in S5 | missing — the BOE's own ordering key |
| `palabra@codigo` | A | code | `210`=DEROGA/SE DEROGA, `270`=MODIFICA/SE MODIFICA, `330`=CITA, `331`=EN RELACIÓN, `440`=DE CONFORMIDAD, `231`=SUSPENDE, `426`=TRANSPONE | every reference in S5 | **missing** — see §4; the code is the machine key, the Spanish word is a label |
| `metadata-eli` (whole RDF block) | E | RDF/XML | 16,089 bytes for the Constitution alone | 54/54 of S5 | **missing — an entire surface.** See §1.4 |
| `bloque@fecha_caducidad` | T | `YYYYMMDD` | `20000108` | **1,281 of 9,723 blocks (13.2%) in S6, in 12 of 53 documents** | **missing** — see §5; it is behind a real publication defect |
| `version@fpub` | T | (empty) | `""` | 32 of 16,417 stamps (0.19%) | missing; empty everywhere observed — source noise, safe to ignore but worth logging |

### 1.3 Fields we write that the source does not support (or no longer supports)

| Frontmatter key | Problem | Measurement |
|---|---|---|
| `url_pdf` | Exact duplicate of the core field `pdf_url`. Both are written from the same `<url_pdf>` element (`metadata.py:401-404`). | identical in **12,298 of 12,299** files; the 12,299th (`BOJA-b-2020-90326`) has neither |
| `url_epub` | **Regression.** The source now nests the value: `<url_epub><url_epub>https://…</url_epub></url_epub>`. `_text_of(dm, "url_epub")` (`metadata.py:406`) reads the outer element's text, which is whitespace, so the value is lost. | nested shape on **17 of 54** S5 documents and **flat-with-text on 0 of 54**; `url_epub` is present in **5,269 corpus files** emitted on or before 2026-07-03 → those 5,269 values disappear on re-emission unless this is fixed |
| `consolidation_status` | We store the label (`Finalizado`) and drop `@codigo`. The label is also **mutable**: `BOE-A-2006-2779` is `Desactualizado` in the corpus and `Finalizado` (`codigo=3`) today; `BOE-A-2026-18282` is `Sin consolidar` in the corpus and `Finalizado` today. | corpus: `Finalizado` 12,196 · `Desactualizado` 102 · `Sin consolidar` 1. Live today: `codigo=3` on 62/62 norms sampled. The codes behind the other two labels have never been captured, precisely because we store the label |
| `alerts` | English key implies a warning. The values are BOE topic channels (`Comercio`, `Derecho Constitucional`, `Sistema financiero`). | 24 distinct values in S5; the field is really a second, coarser taxonomy next to `subjects` |
| `references_previous` / `references_subsequent` separator | The published corpus uses `"; "`; the code on `main` since `1d04644` (2026-09-02) writes `" \| "`. Any consumer splitting on `"; "` breaks at re-emission — and the sentences the new code adds contain `;` themselves. | 11,885 + 8,530 corpus files affected |

### 1.4 The ELI/RDF block — a whole surface we never open

Every `diario_boe/xml.php` response carries `<metadata-eli>` with an ELI ontology
description (54/54 documents in S5; 16 KB for `BOE-A-1978-31229`). `fetcher/pt/parser.py`
already reads exactly this kind of block for Portugal (`_parse_eli_rdfa`, line 863). For
Spain it is downloaded and discarded.

What is in it, measured over S5:

| ELI property | Occurrences | What it gives us |
|---|---|---|
| `eli:consolidated_by` | 398, in 23/54 docs | **the full list of consolidated versions with their dates**, as URIs: `…/con/20260520`, `…/con/20240217`, `…/con/20110927`, `…/con/19920828`, `…/con/19781229`. A version index without downloading the multi-MB `/texto` |
| `eli:version_date` | 398, in 23/54 docs | `2026-05-20` — matches `last_updated` of the corresponding corpus file exactly |
| `eli:is_about` | 517 + 10,579 nested | subject URIs (`…/eli/materias/1616`) — the code form of `subjects` |
| `eli:type_document`, `eli:subtype_document` | 54 / 4 | the ELI resource-type authority URI (`…/resource-type/1/c`) |
| `eli:jurisdiction` | 54 | `…/authority/jurisdiction/1/es` |
| `eli:corrected_by` / `eli:corrects` | 6 / 4 | errata links, as ELI URIs |
| `eli:is_realized_by` → `eli:LegalExpression` | 473 | per-language expressions with `eli:language`, `eli:title`, `eli:date_publication`, `eli:publisher_agent` |
| `eli:is_embodied_by` → `eli:Format` | 592 | the available formats (html, xml, pdf…) as IANA media-type URIs |
| `eli:is_another_publication_of` | 2 | the same act published twice |

The `consolidated_by` list is the interesting one for the re-emission: it is a cheap,
authoritative answer to "how many versions does this norm have and on what dates", which
today we only learn by parsing the whole consolidated text.

---

## 2. `fecha_vigencia` — entry into force

**Where it lands today.** `metadata.py:290` parses `<fecha_vigencia>` into
`NormMetadata.last_modified`. That is the only place it goes.

**Where it stops.** `transformer/frontmatter.py` never reads `last_modified`. The
frontmatter's `last_updated` (line 63) is `version_date`, the argument
`render_norm_at_date` passes in (`markdown.py:173`) — i.e. the date of the *version being
rendered*, not the entry into force. So:

> `fecha_vigencia` is fetched, parsed, stored in the domain object — and never written.
> It is absent from **all 12,299** published files. There is no `effective_date`,
> `entry_into_force` or equivalent key anywhere in the corpus.

`storage.py` makes the loss permanent in the JSON cache too: it writes `last_modified`
under the key `last_updated` (`storage.py:189-193`) and reads it back as `last_modified`
(`storage.py:327`), so a norm round-tripped through the cache has its entry-into-force
date silently replaced by its version date.

**Why it matters, measured.** Over S2 (46 norms), `fecha_vigencia ≠ fecha_publicacion` in
**41 of 46 (89.1%)** — consistent with the 88.6% already recorded in #106.

| Gap (`fecha_vigencia − fecha_publicacion`) | Norms |
|---|---|
| negative (retroactive) | 11 |
| 0 (same day) | 5 |
| 1–30 days | 27 |
| 31–365 days | 3 |

Median +1 day, maximum +184 (`BOE-A-2001-14833`), minimum **−11,489 days**
(`BOE-A-2012-6155`: published 2012-05-08, in force from 1980-11-23 — a 31-year
retroactive effect). A file that states only the publication date cannot express that.

**Where it should land.** As its own frontmatter key, not folded into `last_updated`. The
two answer different questions and disagree for 9 norms in 10.

**The block-level stamps carry one too — and it is a different date.** Over S6 (16,417
`<version>` stamps in 53 consolidated texts):

| | count | share |
|---|---|---|
| stamps carrying `fecha_vigencia` | 16,401 | 99.90% |
| `fecha_vigencia ≠ fecha_publicacion` | **15,807** | **96.3%** |
| `fecha_vigencia` absent (parser falls back to publication date, `xml_parser.py:341`) | 16 | 0.10% |

So the source dates *every amendment* twice, and the two dates differ in 96 % of cases.
The pipeline reads the second one into `Version.effective_date` (`xml_parser.py:346`) and
then nothing uses it: `get_block_at_date` selects on `publication_date`
(`xml_parser.py:384`), the commit date is the publication date, and the JSON round-trip
overwrites `effective_date` with the publication date (`storage.py:351`). A grep for
`effective_date` outside `fetcher/` returns three hits — the dataclass, the round-trip
that destroys it, and the line that sets it.

Concrete case, `BOE-A-1889-4763` article 127: the repealing version is stamped
`fecha_publicacion="20000108" fecha_vigencia="20010108"`. The article was alive for a
further year after the date our file says it died.

---

## 3. The repeal-and-annulment family

**Value domain, measured on 62 norms** (S1 14 + S2 46 + S3 2), of which 30 are `repealed`,
8 `annulled` and 8 `expired` in the corpus:

| Field | Surface | Values observed | Never observed |
|---|---|---|---|
| `estatus_derogacion` | M, D | `S`, `N` only — in S2 alone: `S` 30, `N` 16 | **`T`**, **`P`** |
| `estatus_anulacion` | M | `S`, `N` only — 9 `S` across the 62 | anything else |
| `judicialmente_anulada` | D | `S`, `N` | anything else |
| `vigencia_agotada` | C, M, D | `S` (46 in S2, mixed in S1) | anything else |
| `estado_consolidacion@codigo` | C, M, D | `3` (62/62) | codes for `Desactualizado`, `Sin consolidar` |

`_parse_status` (`metadata.py:141-159`) maps `T` and `S` to `repealed` and `P` to
`partially_repealed`. Against the corpus:

> **`partially_repealed` appears in 0 of 12,299 published files.** Since the corpus status
> is produced by exactly this mapping, `P` has never been served for any Spanish norm we
> hold. `T` cannot be distinguished from `S` in the output, but it appears in none of the
> 62 norms sampled live, including 30 known-repealed ones. Both branches are, on the
> evidence, dead code.

**`vigencia_agotada` is not a category, it is the union.** In S2 all 46 norms have
`vigencia_agotada = S`, including the 30 whose `estatus_derogacion = S`. The corpus proves
it exactly:

```
validity_exhausted: "S"   2,387 files
status repealed           1,935
status annulled              24
status expired              428
                          -----
                          2,387   ← exact match
```

So `vigencia_agotada = S` ⟺ *out of force for any reason*, and our `status: expired`
(428 files) means precisely **"out of force, and the BOE names no repeal and no
annulment"** — a residual bucket, not a statement that the norm was temporary. That is
worth saying out loud in the spec, because "expired" reads as the latter.

**Dates.** `fecha_derogacion` is captured (`repeal_date`, 1,950 corpus files);
`fecha_anulacion` exists on both M and D and is **captured by nothing** — 8 of the 46 S2
norms carry one (e.g. `BOE-A-1980-8656` → `19860620`), and the 24 corpus files marked
`annulled` carry no date at all.

---

## 4. `<analisis><referencias>` — the BOE's own analysis

Shape per entry, verified on the bytes:

```xml
<anterior referencia="BOE-A-1977-165" orden="1010">
  <palabra codigo="210">DEROGA</palabra>
  <texto>Ley 1/1977, de 4 de enero</texto>
</anterior>
<posterior referencia="BOE-A-2026-10881" orden="">
  <palabra codigo="270">SE MODIFICA</palabra>
  <texto>el art. 69.3, por Reforma de 19 de mayo de 2026</texto>
</posterior>
```

The `/api/legislacion-consolidada` variant of the same block uses `<id_norma>` and
`<relacion>` instead; `_reference` (`metadata.py:357-374`) already reads both shapes.

### 4.1 Current state of the code vs. the published corpus

`#106.1`/`#106.2` landed as commit `1d04644` on **2026-09-02**. The published corpus is
from **2026-07-03**, so *none of it is in the data yet*:

| | code on `main` today | corpus at `origin/main` |
|---|---|---|
| `posteriores` slice | whole list | `refs[:20]` |
| `<texto>` of each reference | kept | dropped |
| separator | `" \| "` | `"; "` |

Measured over all 12,299 files: `references_subsequent_count` declares **44,296**
references; only **38,151** entries are actually written. **6,145 references (13.9%) are
missing from the published corpus**, across **334 files** whose count exceeds what they
list. Worst offenders:

| File | declared | written | lost |
|---|---|---|---|
| `BOE-A-1995-25444` (Código Penal) | 175 | 20 | 155 |
| `BOE-A-1994-14960` | 170 | 20 | 150 |
| `BOE-A-1988-29622` | 159 | 20 | 139 |
| `BOE-A-1985-12666` | 146 | 20 | 126 |
| `BOE-A-2020-3692` | 135 | 20 | 115 |
| `BOE-A-2010-10544` (LSC) | 31 | 20 | 11 |

And **0 of 12,299 files** contain a `<texto>` note in either reference field.

### 4.2 The verb list

Verbs are a closed list with a numeric code shared between the two directions (`210` is
both `DEROGA` and `SE DEROGA`). **`palabra@codigo` is dropped by the code** — only the
Spanish label is stored.

Census over the whole corpus (S7), 12,299 files. *Subsequent counts are understated by the
13.9 % the slice cut.*

**`anteriores` — 24 distinct verbs, 49,994 entries in 11,885 files**

| Verb | n | | Verb | n |
|---|---|---|---|---|
| CITA | 12,963 | | AMPLÍA | 96 |
| DE CONFORMIDAD con | 12,492 | | SUPRIME | 84 |
| DEROGA | 12,323 | | **SUSPENDE** | **83** |
| MODIFICA | 9,455 | | ACTUALIZA | 58 |
| EN RELACIÓN con | 882 | | SUSTITUYE | 51 |
| AÑADE | 556 | | INTERPRETA | 43 |
| DESARROLLA | 329 | | COMPLETA | 31 |
| PRORROGA | 211 | | DECLARA | 22 |
| DECLARA la vigencia | 171 | | PUBLICA | 9 |
| DEJA SIN EFECTO | 115 | | AUTORIZA / PUBLICA el texto revisado | 7 / 7 |
| | | | CORRIGE errores 3 · APRUEBA 2 · ACEPTA 1 | |

**`posteriores` — 34 distinct verbs, 38,151 entries**

| Verb | n | | Verb | n |
|---|---|---|---|---|
| SE MODIFICA | 17,608 | | SE AMPLÍA | 220 |
| SE DEROGA | 6,139 | | **SE SUSPENDE** | **131** |
| SE DICTA DE CONFORMIDAD | 5,035 | | SE SUPRIME | 91 |
| SE DECLARA | 1,838 | | SE DECLARA la vigencia | 77 |
| CORRECCIÓN de errores | 1,576 | | SE INTERPRETA | 60 |
| **SE DICTA EN RELACIÓN** | **1,570** | | Cuestión | 59 |
| SE AÑADE | 920 | | SE COMPLETA | 51 |
| SE DESARROLLA | 394 | | SE PUBLICA | 31 |
| SE CORRIGEN errores | 342 | | SE DISPONE el cumplimiento de la Sentencia | 26 |
| SE PRORROGA | 306 | | Conflicto | 22 |
| CORRECCIÓN de erratas | 290 | | SE PUBLICA Enmienda | 21 |
| Recurso | 288 | | SE CORRIGEN erratas | 15 |
| SE ACTUALIZA | 281 | | SE PUBLICA el texto revisado | 8 |
| SE PUBLICA Acuerdo de convalidación | 262 | | SE RATIFICA | 7 |
| SE SUSTITUYE | 243 | | **SE ANULA** | **5** |
| SE DEJA SIN EFECTO | 229 | | SE APRUEBA 4 · SE ACEPTA 1 · SE AUTORIZA 1 | |

Codes seen in S5 (54 documents, 1,027 references): `201` CORRECCIÓN de errores · `202`
CORRECCIÓN de erratas · `203` CORRIGE/SE CORRIGEN errores · `210` DEROGA · `230` DEJA SIN
EFECTO · `231` SUSPENDE · `235` SUPRIME · `270` MODIFICA · `330` CITA · `331` EN RELACIÓN
· `404` ACTUALIZA · `406` AMPLÍA · `407` AÑADE · `426` **TRANSPONE** · `440` DE
CONFORMIDAD · `470` SE DECLARA · `480` DECLARA la vigencia · `490` DESARROLLA · `530`
Cuestión · `552` Recurso.

### 4.3 What matters and no version stamp records

A version stamp exists only when words changed. These verbs change a law's legal effect
without changing its words, so `references_*` is the **only** place in the corpus where
they can live:

| Fact | Verbs | Corpus count |
|---|---|---|
| **Suspension** | `SUSPENDE` / `SE SUSPENDE` | 83 + 131 = **214** — plus an unknown number hidden inside `SE DICTA EN RELACIÓN` (1,570), which is where the LSC art. 348 bis suspension lives, discoverable only from `<texto>` |
| **Loss of effect without repeal** | `DEJA SIN EFECTO` / `SE DEJA SIN EFECTO` | 344 |
| **Extension of a temporary norm** | `PRORROGA` / `SE PRORROGA`, `AMPLÍA` / `SE AMPLÍA` | 833 |
| **Judicial annulment** | `SE ANULA`, `SE DECLARA` (+`SE DISPONE el cumplimiento de la Sentencia`) | 5 + 1,838 + 26 |
| **Confirmation that a norm is still alive** | `DECLARA la vigencia` / `SE DECLARA la vigencia` | 248 |
| **Authoritative interpretation** | `INTERPRETA` / `SE INTERPRETA` | 103 |
| **Pending constitutional challenge** | `Recurso`, `Cuestión`, `Conflicto` | 369 |
| **EU transposition** | `TRANSPONE` (code `426`) | **0** — see below |

Nuance worth recording against the `1d04644` commit message: the closed list *does* have a
word for suspension (`231` / `SUSPENDE`). What the LSC case shows is that the BOE does not
always use it — some suspensions are filed under `331` and named only in `<texto>`. Both
halves of the #106 fix are needed; neither alone is sufficient.

### 4.4 A filter that drops references, still in the code

`_reference` (`metadata.py:367`) returns `""` for any reference whose id does not start
with `BOE-`. Over S5's 1,027 references, **30 (2.9%)** are dropped by that guard:

| Dropped id | n | What it is |
|---|---|---|
| `---` | 18 | reference with no target id (the verb and `<texto>` are still meaningful) |
| `DOUE-L-1994-80897`, `DOUE-L-2003-80722`, `DOUE-L-2003-80442` | 3 | **EU directives** — the targets of `TRANSPONE` |
| `BOIB-i-…` ×3, `BOPV-p-…` ×2, `BOCL-h-…`, `BOCM-m-…` | 8 | regional gazette ids |
| `B-B-1958-7949` | 2 | legacy BOE id form |

This is why `TRANSPONE` appears in the S5 codes but in **0 of 12,299** corpus files: the
verb survives the filter only if its target does, and its target is always a `DOUE-` id.
**Every EU transposition link in the Spanish corpus is invisible today.**

The regional ids are not foreign either: **243 of our own 12,299 files** have a non-`BOE-`
identifier (`BOJA-b` 58, `BOA-d` 44, `DOGV-r` 30, `BORM-s` 30, `BOCL-h` 21, `DOGC-f` 20,
`BOC-j` 10, `BOIB-i` 8, `BON-n` 6, `DOG-g` 3, `DOCM-q` 3, `BOPV-p` 3, `BOCT-c` 3, `DOE-e`
2, `BOCM-m` 2). References pointing at them are dropped, so the filter breaks links
*inside our own repository*.

---

## 5. The `<version>` and `<bloque>` stamps

Measured over S6: 53 consolidated texts, **9,723 `<bloque>`, 16,417 `<version>`**.

### 5.1 Every attribute, not just the two the pipeline reads

| Element | Attribute | Present on | Read at | Emitted |
|---|---|---|---|---|
| `<bloque>` | `id` | 9,723 / 9,723 | `xml_parser.py:354` | block identity |
| `<bloque>` | `tipo` | 9,723 / 9,723 | `xml_parser.py:355` | **no** |
| `<bloque>` | `titulo` | 9,625 / 9,723 | `xml_parser.py:356` | **no** |
| `<bloque>` | **`fecha_caducidad`** | **1,281 / 9,723 (13.2%)** | **nothing** | **no** |
| `<version>` | `id_norma` | 16,417 / 16,417 (0 empty) | `xml_parser.py:345` | commit `Source-Id` |
| `<version>` | `fecha_publicacion` | 16,417 / 16,417 | `xml_parser.py:331` | `last_updated`, commit date |
| `<version>` | `fecha_vigencia` | 16,401 / 16,417 | `xml_parser.py:332` | **no** (see §2) |
| `<version>` | `fpub` | 32 / 16,417 | nothing | no — empty in all 32 |

`bloque@tipo` domain over S6: `precepto` 7,991 · `encabezado` 1,596 · `firma` 55 ·
`preambulo` 51 · `nota_inicial` 26 · `parte_dispositiva` 4.

### 5.2 `fecha_caducidad` is behind a real publication defect

`fecha_caducidad` marks the date a block ceased to exist. Two shapes occur:

1. **The repeal is materialised.** The BOE emits one more `<version>` whose body is
   `<strong>(Derogado)</strong>` plus a `nota_pie`. The pipeline renders it correctly —
   `es/BOE-A-1889-4763.md` line 2021 reads `###### Artículo 127.` / `**(Derogado)**`.
2. **The repeal is not materialised.** No version at or after `fecha_caducidad`; the block
   keeps only its last live text. `get_block_at_date` selects that text and renders it as
   if in force.

Split of the 1,281 blocks whose `fecha_caducidad` is at or before their own file's render
date:

| | blocks |
|---|---|
| repeal materialised → renders `(Derogado)` | 659 |
| **no version at/after `fecha_caducidad` → full text published as if in force** | **622** |

622 of 9,723 blocks (**6.4 %**) in **10 of 53 documents**:
`BOE-A-1984-12106` 378 · `BOE-A-1889-4763` 127 · `BOE-A-1985-12666` 77 ·
`BOE-A-1994-14960` 13 · `BOE-A-1983-6190` 8 · `BOE-A-1986-9865` 7 · `BOE-A-1992-28740` 7 ·
`BON-n-1999-90001` 2 · `BOE-A-2014-12029` 2 · `BOE-A-2008-2389` 1.

Verified against the published file:

```
source:  <bloque id="a244" tipo="precepto" fecha_caducidad="20120306" titulo="Art 244">
           <version id_norma="BOE-A-1984-12106" fecha_publicacion="19840530" …>   ← only version
corpus:  countries/es/es/BOE-A-1984-12106.md   last_updated: "2012-03-06"
         line 1388  ###### Art. 244.
         line 1390  Para el régimen interior, se entenderá por servicios …
```

The file publishes 378 articles as current law that the source marks as gone. Same shape
in the Código Civil, where the 1889 transitional and additional provisions carry
`fecha_caducidad="19810720"` and are still printed in a file dated 2025-01-03.

This is the strongest single argument for `es` becoming **MIXED `text_state`**: the
country default asserts `point_in_time`, and for these blocks the body is not the law at
`last_updated`.

---

## 6. Verdict summary

| Verdict | Count | Fields |
|---|---|---|
| **OK** | 33 | the core eight, department/rank/ambito codes, the date trio, repeal status/date, annulment status, exhausted flag, the ELI/HTML urls, the four translated PDFs, page range, `letra_imagen`, `estatus_legislativo`, subjects, block/version identity |
| **missing** | 21 | `fecha_vigencia` (norm level and 16,401 block stamps) · `fecha_actualizacion` (both flavours) · `fecha_anulacion` · `seccion` · `subseccion` · `diario@codigo` · `origen_legislativo` · `judicialmente_anulada` · `suplemento_pagina_inicial/_final` · `suplemento_letra_imagen` · `materia@codigo/@orden` · `alerta@codigo` · **`<notas>`** · `palabra@codigo` · `anterior/posterior@orden` · **`<metadata-eli>`** · **`bloque@fecha_caducidad`** · `version@fpub` |
| **wrong** | 5 | `url_epub` (silently empty since the source nested it) · `url_pdf` (duplicate of `pdf_url`) · `consolidation_status` (label not code, and mutable) · `alerts` (misleading key) · reference separator change with no version marker |
| **partial** | 4 | `references_previous` / `references_subsequent` (non-BOE targets dropped; `<texto>` and whole list only on `main`, not in the data) · `subjects` (codes dropped) · `alerts` (codes dropped) |

### What the re-emission has to do at minimum

1. Write `fecha_vigencia` as its own key (and keep the block-level one) — 89 % of norms
   and 96 % of version stamps disagree with the date we publish.
2. Read `bloque@fecha_caducidad` and stop publishing 6.4 % of blocks as live text —
   or mark those files `text_state` ≠ `point_in_time`.
3. Drop the `startswith("BOE-")` guard in `_reference` — it is the sole reason EU
   transposition links do not exist in the corpus and why links to our own 243 regional
   files break.
4. Fix `url_epub`'s nested shape before re-emitting, or 5,269 files lose a field they
   already have.
5. Capture `<notas>`, `palabra@codigo`, `materia@codigo`, `seccion`, `fecha_anulacion` and
   `fecha_actualizacion` — all already in bytes we download.
6. Decide on `<metadata-eli>`: `eli:consolidated_by` alone is a free version index.

---

## 7. Open questions

- The codes behind `estado_consolidacion` = `Desactualizado` and `Sin consolidar` were not
  captured: both sampled norms had flipped to `Finalizado` (`codigo=3`) by today. Catching
  them needs a norm that is mid-consolidation at fetch time.
- `estatus_derogacion` values `T` and `P` were not observed in 62 live norms nor in 12,299
  published files. Whether the source ever emits them is unproven; the mapping should
  probably keep the branches but log when they fire.
- `estatus_legislativo` is `L` on 12,299/12,299 files and 54/54 live documents. Its domain
  is unknown.
- 18 references in S5 have `referencia="---"`. Whether the verb+`<texto>` of an untargeted
  reference is worth keeping is a product call, not a measurement.
- The `<notas>` `@codigo` domain (12 values in S5: `0`, `3`, `9`, `14`, `15`, `23`, `28`,
  `36`, `37`, `38`, `149`, `151`) is not documented anywhere we have; a bigger sample
  would be needed to enumerate it.
