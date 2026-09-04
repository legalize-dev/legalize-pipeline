# Probe 7 — Version history (§0.5) and the block-vs-norm entry-into-force question

**Date:** 2026-09-03 · **Source:** BOE open data, `https://www.boe.es/datosabiertos`
**HTTP requests spent: 42** (budget 150), one every 0.8 s, UA `legalize-bot/1.0 (+https://github.com/legalize-dev/legalize)`.
No 429 and no 5xx were seen. Raw evidence in `/Users/neli/.claude/jobs/5bf7ddf4/tmp/`
(`texto-*.xml`, `catalogue.json`, `metadatos-sample.json`, `http-log.json`).

## Headline

**The entry-into-force date IS available at block level.** Every `<version>` in the
consolidated `/texto` carries `fecha_vigencia` alongside `fecha_publicacion` —
11,379 / 11,379 versions in the sample (100 %). The block-level half of issue #106 §2
therefore needs **no re-fetch either**; the date is in the same XML the pipeline
already downloads and already parses into `Version.effective_date`, and then throws
away. And the block-level date is not merely *a* date — it is **more correct than the
norm-level one**: on 63 of 356 checkable amending acts (17.7 %) the block's
`fecha_vigencia` disagrees with the amending norm's own `fecha_vigencia`, because a
single act can put different articles in force on different days.

Resolving via the amending norm's `/metadatos` — the fallback #106 assumed would be
needed — is both **wrong** where the two disagree and **impossible** for a third of
amending acts: 167 of 523 distinct amending acts in the sample are not in the
consolidated catalogue at all, and 10 out of 10 sampled returned HTTP 404 on
`/metadatos`.

---

## Part 1 — §0.5 version-history spike: PASS

### Method

Fetched `/api/legislacion-consolidada/id/{id}/texto` (`Accept: application/xml`) for
8 laws — the four the brief suggested plus the four most-reformed files in the
published corpus (`git -C countries/es log --name-only --diff-filter=M`). 8 requests.
Parsed with `lxml`; enumerated every attribute on every element; reconstructed the
law's text at each distinct date by taking, per `<bloque>`, the latest `<version>`
whose date is ≤ the target — the same rule `transformer/markdown.py::get_block_at_date`
uses.

### The structure, verbatim

The API answers `<response><status/><data><texto>` and then a flat run of `<bloque>`,
each holding one `<version>` per wording it has ever had:

```xml
<bloque id="a2" tipo="precepto" titulo="Artículo 2">
  <version id_norma="BOE-A-2015-11430" fecha_publicacion="20151024" fecha_vigencia="20151113">
    <p class="articulo">Artículo 2. Relaciones laborales de carácter especial.</p>
    <p class="parrafo">…</p>
  </version>
  <version id_norma="BOE-A-2017-1933" fecha_publicacion="20170225" fecha_vigencia="20170226">
    <p class="articulo">Artículo 2. Relaciones laborales de carácter especial.</p>
    <p class="parrafo">…</p>
  </version>
  <version id_norma="BOE-A-2017-3124" fecha_publicacion="20170324" fecha_vigencia="20170324">…</version>
  <version id_norma="BOE-A-2017-5270" fecha_publicacion="20170513" fecha_vigencia="20170514">…</version>
  <version id_norma="BOE-A-2022-4583" fecha_publicacion="20220323" fecha_vigencia="20220331">…</version>
</bloque>
```

The stable identifier linking the versions is the enclosing `<bloque id>`; the
identifier linking them to the law is the request id itself; the identifier of the act
that *caused* each version is `<version id_norma>`.

### Complete attribute inventory (8 laws, 5,944 `<bloque>`, 11,379 `<version>`)

| Element | Attribute | Occurrences | Meaning / notes |
|---|---|---|---|
| `bloque` | `id` | 5,944 (100 %) | stable key across versions; unique within a document |
| `bloque` | `tipo` | 5,944 (100 %) | vocabulary below |
| `bloque` | `titulo` | 5,923 (99.6 %) | absent on `preambulo` and some `firma` blocks |
| `bloque` | **`fecha_caducidad`** | **292** | the block's *end* date — see §Part 3 |
| `version` | `id_norma` | 11,379 (100 %) | BOE id of the act that introduced this wording |
| `version` | `fecha_publicacion` | 11,379 (100 %) | date the amending act was **published** |
| `version` | **`fecha_vigencia`** | **11,379 (100 %)** | date this wording **took effect** |
| `version` | `fpub` | 3 | empty-valued stray, all on 2026 acts — BOE emission bug, ignore |
| `blockquote` | `caduca` | 315 | sub-block expiry date (see §Part 3) |
| `p` | `caduca` | 3 | same, on a paragraph |

`bloque/@tipo` vocabulary, with counts: `precepto` 4,985 · `encabezado` 938 ·
`firma` 8 · `preambulo` 7 · `nota_inicial` 5 · `parte_dispositiva` 1.

There is **no** `fecha_derogacion`, no `estado`, no `orden`, no version-number
attribute. `fecha_caducidad` is the only end-date and it lives on `bloque`, never on
`version`.

### The spike evidence — content for `tests/fixtures/es/version-spike.txt`

> Copy the fenced block below verbatim to `engine/tests/fixtures/es/version-spike.txt`.
> (Not written by this probe: this run is read-only outside `research/es-v2/`.)

```text
ES version-history spike — BOE consolidated API — 2026-09-03
Endpoint: GET https://www.boe.es/datosabiertos/api/legislacion-consolidada/id/{id}/texto
Accept: application/xml   (Accept: */* is rejected with HTTP 400
                           "No soportado ningun mime type de la cabecera Accept.")

LAW A — Constitucion Espanola, BOE-A-1978-31229
  210 bloques, 214 versions, 5 distinct publication dates, 5 amending acts.
  version 1: pub 1978-12-29  eff 1978-12-29  act BOE-A-1978-31229  210 blocks   798 paragraphs
  version 2: pub 1992-08-28  eff 1992-08-28  act BOE-A-1992-20403    1 block    799 paragraphs
  version 3: pub 2011-09-27  eff 2011-09-27  act BOE-A-2011-15210    1 block    810 paragraphs
  version 4: pub 2024-02-17  eff 2024-02-17  act BOE-A-2024-3099     1 block    812 paragraphs
  version 5: pub 2026-05-20  eff 2026-05-20  act BOE-A-2026-10881    1 block    813 paragraphs
  Stable identifier across versions: bloque/@id (e.g. "a69"), verbatim:
    <bloque id="a69" tipo="precepto" titulo="Articulo 69">
      <version id_norma="BOE-A-1978-31229" fecha_publicacion="19781229" fecha_vigencia="19781229"> 7 children
      <version id_norma="BOE-A-2026-10881" fpub="" fecha_publicacion="20260520" fecha_vigencia="20260520"> 8 children

LAW B — Estatuto de los Trabajadores, BOE-A-2015-11430
  178 bloques, 295 versions, 40 distinct publication dates, 43 amending acts.
  version 1: pub 2015-10-24  eff 2015-11-13  act BOE-A-2015-11430  166 blocks  1234 paragraphs
  version 2: pub 2017-02-25  eff 2017-02-26  act BOE-A-2017-1933     1 block   1235 paragraphs
  version 3: pub 2017-03-24  eff 2017-03-24  act BOE-A-2017-3124     1 block   1235 paragraphs
  version 4: pub 2018-07-04  eff 2018-07-05  act BOE-A-2018-9268     2 blocks  1238 paragraphs
  ... 36 further dated versions through 2026-06-24 ...
  Note: publication and entry into force differ on 39 of its 43 acts.

Structural facts confirmed on 8 laws (5,944 bloques / 11,379 versions):
  - <version> ALWAYS carries id_norma, fecha_publicacion AND fecha_vigencia (100%).
  - bloque/@id is unique within a document (0 duplicates in 5,944) and is reused
    unchanged across every version of that block.
  - bloque/@fecha_caducidad marks a block that ceased to exist (292 occurrences).
  - Deepest history in the sample: bloque a91 ("Articulo 91") of BOE-A-1992-28740 with 41 versions.

CLASSIFICATION: point_in_time.
  The source incorporates amendments (yes) and lets us reconstruct the text at any
  past date from the per-block version stack (yes) -> point_in_time, the spec default,
  which is never written to the frontmatter.
```

### §0.5 classification, explicitly

Walking the playbook's decision tree against the evidence above:

- *Does the source give the text with amendments incorporated?* **Yes** — a `<bloque>`
  holds successive complete wordings, not a diff.
- *Does it give that text at a past date?* **Yes** — each wording is dated twice, and
  selecting per block by date reconstructs the law as it stood on any day.

→ **`point_in_time`** for consolidated norms. This is the spec default and is never
written to the frontmatter, so `TEXT_STATE["es"]` must **not** be set to
`point_in_time`; it is set to the *majority* value once the non-consolidated acts are
added, and the parser overrides consolidated norms back to `POINT_IN_TIME` per norm —
exactly the `pt` inversion (`fetcher/pt/parser.py:856`,
`text_state = TextState.POINT_IN_TIME if bundle.get("surface") == CONSOLIDATED else None`),
run in the opposite direction. Scale check from the catalogue (2 requests, full sweep):
**12,385 consolidated norms** exist, of which 8,767 estatal and 3,618 autonómico;
195 are `estado_consolidacion = "Desactualizado"` (the BOE's own admission that the
consolidation is behind), 12,190 `Finalizado`.

---

## Part 2 — Is the entry-into-force date available at BLOCK level? **Yes.**

### The bytes

`fecha_vigencia` is present on **11,379 of 11,379** `<version>` elements across all 8
laws. Four of them carry the empty string (`fecha_vigencia=""`, e.g. bloque `art56` of
the Código Civil under `BOE-A-2015-7391`); the existing
`transformer/xml_parser.py::_parse_date` already maps `""` and the `99999999` sentinel
to `None`. There is no third date attribute: nothing distinguishes "published",
"in force" and "applicable from" beyond these two.

So the two attributes *are* the distinction the question asks for:
`fecha_publicacion` = the day the amending act appeared in the BOE;
`fecha_vigencia` = the day this wording started to apply.

### What the engine does with it today

`xml_parser.py` parses it into `Version.effective_date` (line 347) — and nothing ever
reads it. `extract_reforms` keys on `version.publication_date`; `pipeline.py:738` calls
`render_norm_at_date(..., reform.date)`; `get_block_at_date` filters on
`v.publication_date`; `render_frontmatter` writes that same date as `last_updated`.
Grep for `effective_date` in `src/legalize/` returns one write (`xml_parser`) and one
round-trip (`storage.py:351`). **The correct date is fetched, parsed, serialised to the
JSON cache, and then discarded at every decision point.**

### Do NOT resolve it from the amending norm's `/metadatos`

Two independent reasons, both measured.

**(a) It gives a different, wrong answer 17.7 % of the time.** Joining the 523 distinct
`(id_norma, fecha_publicacion, fecha_vigencia)` triples seen at block level against the
full consolidated catalogue (12,385 entries, 2 requests):

| Comparison | Agrees | Disagrees |
|---|---|---|
| block `fecha_publicacion` vs norm `fecha_publicacion` | 349 | 7 |
| block `fecha_vigencia` vs norm `fecha_vigencia` | 293 | **63 (17.7 %)** |

Examples: `BOE-A-2025-76` — norm-level vigencia 2025-04-03, but its blocks in the LOPJ
enter into force on 2025-01-23, 2025-04-03 **and** 2025-10-03. `BOE-A-1994-28967` —
norm says 1995-01-01, the block says 1995-01-20 (verified by a live `/metadatos` call,
request 39). **32 of 589 act↔law pairs (5.4 %) put different blocks of the same law in
force on different days**; the norm-level date cannot express that, and by construction
would collapse them.

**(b) For a third of amending acts the endpoint does not exist.** 167 of 523 distinct
amending acts (31.9 %) are absent from the consolidated catalogue — they are acts the
BOE never consolidated (mostly pre-1990 and one-off amending decrees). A random sample
of 10 was fetched: `BOE-A-2005-19626`, `BOE-A-1997-6257`, `BOE-A-2010-8167`,
`BOE-A-1958-6677`, `BOE-A-1978-28627`, `BOE-A-2019-3524`, `BOE-A-1988-28027`,
`BOE-A-2008-19660`, `BOE-A-2025-1136`, `BOE-A-1972-1095` — **10 / 10 returned HTTP 404**
(`<status><code>404</code>`).

**Cost, had it been needed (EXTRAPOLATED).** Base measurement: 472 distinct amending
acts across 8 laws (59.0 per law), of which 68.1 % are resolvable. The corpus has
12,299 files. A naive one-`/metadatos`-per-act implementation with a global cache would
issue roughly `12,299 × 59 × (1 − reuse)`; even assuming the very generous reuse
implied by the catalogue (an act can only be one of 12,385 consolidated norms, plus the
non-consolidated ones), the ceiling is bounded by the number of *distinct* acts, so the
realistic figure is **one request per distinct amending act ≈ 12,385 catalogue entries
+ an unbounded tail of non-consolidated ones**, i.e. **≥ 20,000 extra requests** for a
full corpus, at the BOE's 4 req/s that is ~1.5 h added to every bootstrap — to obtain a
date that is already in bytes we hold and that is wrong 17.7 % of the time. Multiplier
and base are stated; treat the ≥20,000 as an order-of-magnitude figure, not a count.

**Correct implementation:** read `version/@fecha_vigencia`, fall back to
`fecha_publicacion` when it is empty or the `99999999` sentinel — which is what
`xml_parser.py` line 347 already does. The change is to make `extract_reforms`,
`get_block_at_date` and `render_frontmatter` use `effective_date` instead of
`publication_date`. Zero extra HTTP.

### Size of the residual error if we keep the publication date

All 11,374 parseable `(fecha_publicacion, fecha_vigencia)` pairs in the 8-law sample,
delta in days (vigencia − publicación):

| Statistic | Value |
|---|---|
| n | 11,374 |
| delta = 0 (no error) | 410 (**3.6 %**) |
| delta ≠ 0 (wrong date) | **96.4 %** |
| median | **22 days** |
| mean | 72.1 days |
| p25 / p75 | 3 / 64 days |
| p90 / p95 / p99 | 366 / 366 / 366 days |
| min / max | −345 / +3,570 days |
| \|delta\| > 30 days | 31.3 % |
| \|delta\| > 365 days | 10.3 % |

| Bucket | Versions | Share |
|---|---|---|
| negative (retroactive) | 13 | 0.1 % |
| 0 days | 410 | 3.6 % |
| 1 day (the standard *día siguiente*) | 2,213 | 19.5 % |
| 2–7 days | 434 | 3.8 % |
| 8–30 days | 4,754 | 41.8 % |
| 31–90 days | 1,424 | 12.5 % |
| 91–365 days | 956 | 8.4 % |
| > 365 days | 1,170 | 10.3 % |

Two things this table hides and should not:

- **The 366-day spike is a single act.** 1,078 of the 1,170 ">365" rows are the
  **Ley de Enjuiciamiento Civil itself**: all 1,024 of its original blocks are
  `fecha_publicacion="20000108" fecha_vigencia="20010108"` — a one-year *vacatio legis*.
  Our published `countries/es/es/BOE-A-2000-323.md` carries
  `publication_date: "2000-01-08"` and its `[bootstrap]` commit is dated **2000-01-08**,
  a text that had no legal force for another twelve months.
- **Retroactive amendments exist and are common enough to matter.** 13 versions have a
  negative delta, e.g. `BOE-A-2006-5691` published 2006-03-30 with effect from
  2006-01-01 across 6 articles of the IVA law, and `BOE-A-2025-6597` published
  2025-04-02 with effect from 2025-01-02 in art. 15 ET. A date-ordered history keyed on
  publication silently reorders these. One is a genuine data error to guard for:
  `BOE-A-1997-28053` gives `fecha_vigencia="09980101"` — year 0998, a BOE typo for 1998.
  Any switch to `effective_date` must keep a sanity window (`xml_parser._parse_date`
  already rejects year > 2100; it does **not** reject year < 1700 — add it).

### Commit-level impact — what actually changes in the re-emission

Counting a reform the way `extract_reforms` does (distinct `(date, id_norma)` pairs),
for the 8 sampled laws:

| Law | bloques | versions | commits @publicación | commits @vigencia | dates that move | commits in today's repo |
|---|---|---|---|---|---|---|
| BOE-A-1889-4763 (C. Civil) | 2,444 | 3,837 | 74 | 78 | 69 | 74 |
| BOE-A-1978-31229 (CE) | 210 | 214 | 5 | 5 | **0** | 5 |
| BOE-A-1985-12666 (LOPJ) | 971 | 1,967 | 84 | 89 | 73 | 78 |
| BOE-A-1992-28740 (IVA) | 307 | 822 | 98 | 103 | 87 | 89 |
| BOE-A-1994-14960 (LAU) | 477 | 1,079 | 107 | 114 | 94 | 99 |
| BOE-A-2000-323 (LEC) | 1,083 | 2,515 | 88 | 91 | 78 | 84 |
| BOE-A-2006-20764 (IRPF) | 274 | 650 | 96 | 103 | 75 | 92 |
| BOE-A-2015-11430 (ET) | 178 | 295 | 43 | 45 | 39 | 41 |
| **TOTAL** | **5,944** | **11,379** | **595** | **628** | **515 (86.6 %)** | **562** |

Read: switching to the entry-into-force date **moves 86.6 % of Spanish reform commit
dates** and adds ~5.5 % more commits (628 vs 595), because acts that stagger their
entry into force stop collapsing into one commit. The Constitution is the one law where
nothing changes — every one of its five amendments took effect on publication.

EXTRAPOLATED, for sizing only: 628/595 = **+5.5 % commits**; against the corpus's
44,295 commits that is roughly **+2,400 commits**, and ~38,000 commit dates moving.
Base = the 8 laws above, multiplier = the corpus/sample commit ratio. These 8 laws are
deliberately the *most* reformed in the corpus, so the per-law figures do not
generalise; only the ratios are used.

---

## Part 3 — `fecha_caducidad`, `tipo`, id stability, id recycling

**Is there an end-date on `<bloque>`? Yes — `fecha_caducidad`, 292 occurrences.** It
marks a block that ceased to exist. Verbatim:

```xml
<bloque id="sprimera" tipo="precepto" fecha_caducidad="19810720" titulo="Sección primera">
  <version id_norma="BOE-A-1889-4763" fecha_publicacion="18890725" fecha_vigencia="18890816">
    <p class="seccion">Sección primera. De las formas del matrimonio</p>
  </version>
  <version id_norma="BOE-A-1958-6677" fecha_publicacion="19580425" fecha_vigencia="19580515">
    <p class="seccion">Sección primera. De las clases de matrimonio</p>
  </version>
</bloque>
```

**The engine ignores it entirely.** `grep -rn "fecha_caducidad\|caduca" src/legalize/`
returns nothing. Consequence, verified in the published corpus: the heading
*"Sección primera. De las clases de matrimonio"*, which the BOE says expired on
1981-07-20, is still present in today's `countries/es/es/BOE-A-1889-4763.md`. Every one
of those 292 blocks is a fragment of repealed law that our "point in time" file
presents as current. **This is a second, independent correctness defect that the
re-emission should fix in the same pass** — the fix is the mirror of the version rule:
drop a block whose `fecha_caducidad` ≤ the target date.

There is a finer-grained sibling: **`@caduca` on `<blockquote>` (315) and `<p>` (3)**,
318 in total, an expiry date on part of a block's body (e.g.
`<blockquote caduca="20210430" class="soloTexto">`). Same treatment, same silence in the
current parser.

**Is `tipo` there? Yes** — 100 % coverage, 6 values, listed in Part 1. It is read today
into `Block.block_type` and is not used for anything downstream.

**Is `id` stable across versions? Yes, by construction** — versions are *children* of
the block, so the id cannot vary between them, and 41 successive wordings of
`bloque a91` ("Artículo 91" of the IVA law, BOE-A-1992-28740 — deepest in the sample) all sit under one id.

**Is a block id reused after a repeal? No — the BOE disambiguates, and lxml recycling
does not apply here.** Three separate checks:

1. **Within a document, ids are unique**: 5,944 blocks, 5,944 distinct ids, zero
   duplicates across all 8 laws. The BOE achieves this by appending a numeric suffix —
   884 ids (14.9 %) end in `-N` (`sprimera`, `sprimera-3`, `cii-4`, …). So a structural
   unit that reappears gets a *new* id, not the old one.
2. **Expired blocks keep their own id**: of the 292 blocks carrying `fecha_caducidad`,
   133 have a same-base-name sibling elsewhere in the document — and in every case the
   sibling carries a different suffixed id. The expired block is not overwritten.
3. **The lxml id() recycling gotcha does not bite here** (see memory
   `feedback_engine_gotchas`): that bug is about Python `id()` of freed element objects
   being reused, not about `@id` attributes. `xml_parser.parse_text_xml` iterates with
   `root.iter("bloque")` while holding the tree alive and reads `block_el.get("id")` —
   a string copy — so there is nothing to recycle. **No action needed.** The real
   stability risk is different and worth stating: because the suffix is positional,
   inserting a new *Sección primera* ahead of an existing one can shift `-N` suffixes
   between fetches. Do not put `bloque/@id` in a filename or any git-visible key.

---

## What this probe recommends for the re-emission

1. **Use `version/@fecha_vigencia` as the reform date and as `last_updated`.** Free, no
   re-fetch, already parsed. Moves 86.6 % of commit dates and adds ~5.5 % commits.
2. **Do not add a `/metadatos` resolution step.** It is wrong on 17.7 % of acts,
   impossible on 31.9 %, and costs ≥ 20,000 requests.
3. **Guard the date**: reject years < 1700 as well as > 2100 in
   `xml_parser._parse_date` (`fecha_vigencia="09980101"` is real), and allow negative
   deltas — retroactive amendments are legitimate, and 13/11,374 of them exist.
4. **Honour `bloque/@fecha_caducidad` and `@caduca`** in the same pass. 292 + 318
   occurrences of repealed text currently published as if in force.
5. **`TEXT_STATE["es"]` stays out of `point_in_time`.** Consolidated norms classify as
   `point_in_time` (spec default, unwritten); the country default becomes whatever the
   non-consolidated majority is, with the parser overriding consolidated norms per norm,
   `pt`-style.
6. Two side observations outside this probe's remit, recorded because they were seen in
   the bytes: `<ins>` appears 98 times (75 inside `<p>`, 9 inside `<blockquote>`, 14
   nested) and `xml_parser` has no branch for it at version level; and `version/@fpub=""`
   is emitted by the BOE on 3 recent (2026) acts and is harmless.

## Caveats

- The 8-law sample is deliberately biased towards heavily reformed laws (four were
  chosen as the corpus's most-modified files), so per-law counts are upper bounds. All
  conclusions above rest on *ratios* and on *presence/absence of attributes*, which the
  bias does not affect.
- The catalogue sweep covers the 12,385 **consolidated** norms only. Non-consolidated
  acts — the thing being added in this re-emission — are outside this endpoint and were
  only observed indirectly, as the 167 amending ids that 404 on `/metadatos`.
- `fecha_caducidad` semantics were inferred from its values and from the content of the
  blocks carrying it (a 1958 marriage-law heading expiring in 1981, the year of the
  divorce reform). The BOE publishes no schema for the consolidated `/texto` endpoint,
  so this reading is evidence-based, not documented.
