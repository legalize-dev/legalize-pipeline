# 02 — Taxonomy of the non-consolidated (Probe 2)

Status: **Step 0 (research) — measurement complete, no code written**
Date: 2026-09-03 · Source: BOE open data · Scope: issue #66, the scope rule
Probe: 2 of N (independent sample; does not reuse Probe 1's days)

**HTTP budget used: 142 of 150 requests to `boe.es`.** One request every 0.5–1.0 s,
`User-Agent: legalize-bot/1.0 (+https://github.com/legalize-dev/legalize)`. No 429,
no 5xx. Every request cached to disk under
`/Users/neli/.claude/jobs/5bf7ddf4/tmp/probe2/cache/` so the sample is auditable.

---

## TL;DR

**88.4 %** of Sección I items are absent from the consolidated catalogue — not the
~50 % issue #66 measured on three days. The population is *not* mostly amending acts:
amending-only acts are **22.2 %** of it. The largest slice, **27.0 %**, is
**singular/administrative acts** — direct subsidies, the creation of one committee or
one consular office, a coin issue — and *that* is the slice no field in the source can
separate from real normative content.

Three findings change the shape of the work:

1. **`rango` cleanly removes everything that is not a norm.** Correcciones de errores
   carry their own rank code (`1590`), judgments carry `1240`, TC procedural acts carry
   `63`. On a 63-act census the rule `rango ∉ {1590, 1240, 63}` dropped **12/12**
   non-norms with **zero** false drops. The brief's worry that a rank field cannot
   distinguish a *corrección de errores* is **not borne out** — the BOE ranks it.
2. **`rango` cannot decide anything else.** `rango = 1300 (Ley)` does not imply a
   consolidated text exists (`BOE-A-2014-12329`), and a subsidy RD and a regulation RD
   are both `1340` with identical `seccion`, `origen_legislativo` and
   `estatus_legislativo`. The undecidable residue is **27.0 %** of the population and
   it is a *policy* question, not a metadata one.
3. **"404 today" is "404 forever" after ~30 days, and there is a new rank code we do
   not map.** `rango 1676 = "Reforma"` — the constitutional reform `BOE-A-2026-10881` —
   is absent from `metadata.py::_RANK_CODE_MAP`.

And one finding that is not about scope at all but bounds the whole republish:
**the diary XML carries no text before 1984.** `<texto/>` is empty for 12/13 sampled
acts from 1982–1983 and populated for 100 % of acts from 1984 on.

---

## §1 Method

### 1.1 The membership oracle

The consolidated catalogue was enumerated **once**, completely, as the oracle for
"does the BOE keep a consolidated text for this id":

```
GET /api/legislacion-consolidada?limit=10000&offset={0,10000}
Accept: application/json
```

| Measure | Value |
|---|---|
| Requests | 2 |
| Catalogue size | **12,385** unique `identificador` |
| Publication range | 1835-01-01 → 2026-09-03 |
| Published 1979-01-01 or later | 11,958 (96.6 %) |
| Ámbito | Estatal 8,767 · Autonómico 3,618 |
| `estado_consolidacion` | Finalizado 12,190 · Desactualizado 195 |

Page size is 10,000; the second page returned 2,385 and the enumeration terminated.
An item is **non-consolidated** iff its `identificador` is not in this set.

> **Gotcha, cost me 24 requests.** `/api/boe/sumario/{YYYYMMDD}` returns
> **HTTP 400 — `No soportado ningún mime type de la cabecera Accept`** when the request
> carries `requests`' default `Accept: */*`. An explicit `Accept: application/xml` (or
> `application/json`) is mandatory. `engine/src/legalize/fetcher/es/client.py` already
> sets one; anything written outside the client must too.

### 1.2 The sample

Sección I items were taken from **28 gazette days spread over 1982–2026**, chosen on
June/October/September weekdays. Probe 1 sampled January days; **no day is shared**.

| Band | Days |
|---|---|
| Historical | 1982-06-15, 1983-10-18, 1984-06-19, 1985-06-18, 1987-06-16, 1988-10-18, 1993-06-15, 1998-10-20, 2003-06-17, 2008-10-21, 2013-06-18, 2017-10-17, 2021-06-15, 2024-10-15 |
| Recency ladder | 2026-09-01, 2026-08-31, 2026-08-26, 2026-08-25, 2026-08-05, 2026-08-04, 2026-07-07, 2026-07-06, 2026-06-04, 2026-06-03, 2026-03-04, 2026-03-03, 2025-09-03, 2025-09-02 |

Every item was then read from `https://www.boe.es/diario_boe/xml.php?id={id}`.

| Measure | Value |
|---|---|
| Gazette days fetched | 28 |
| Sección I items found | **112** |
| Sección I items per gazette day | **4.00** |
| Non-consolidated | **99 (88.4 %)** |
| Consolidated | 13 (11.6 %) |
| Diary XML documents fetched | **88** (all 200) |
| Full-census taxonomy sample | the **63** non-consolidated acts from the first 24 days |

Sección I is thin and **shrinking**: 6.00 items/day in 1982–2003, 3.20 in 2008–2024,
2.07 in 2025–2026 (5, 5 and 14 days respectively). Issue #66's "~6 per publication day"
holds for the 1980s–1990s, not for today.

**Cross-check against the published corpus.** All 63 non-consolidated ids were checked
against the 12,299 `.md` files in `countries/es`: **0 of 63 are present.** The gap issue
#66 describes is real and total, and the catalogue is the right oracle for it.

---

## §2 The taxonomy

Full census of the 63 non-consolidated Sección I acts. Categories were assigned by
reading each `<titulo>` and `<analisis>`; the id→category map is reproducible in
`/Users/neli/.claude/jobs/5bf7ddf4/tmp/probe2/` and every id is listed in §2.2.

### 2.1 Breakdown

| Category | n | % | What it is |
|---|---:|---:|---|
| **Singular / administrative** | 17 | **27.0 %** | Direct subsidies, creation of one committee/consular office, coin issue, homologation of one qualification, publication of a Council of Ministers agreement |
| **Autonomous general disposition** | 16 | **25.4 %** | Own normative content — a regulation approved, a tariff set, a procedure established. Includes the 2 autonomic Decretos-ley |
| **Amending-only** | 14 | **22.2 %** | Entire content is amendments to other norms ("por el que se modifica…") |
| **Judicial** | 7 | **11.1 %** | 5 Tribunal Supremo judgments + 2 TC providencias |
| **Corrección de errores** | 5 | **7.9 %** | Errata against another act |
| **International agreement** | 4 | **6.3 %** | Convenios, enmiendas, treaty-status resolutions |

Issue #66's three-day sample found "a constitutional reform, a modifying RD, an RD
granting direct subsidies, an autonomic Resolución, a Decreto-ley Foral, a corrección
de errores and a sentencia" — every one of those categories reappears here, but the
weights are different: **the modifying acts that name the issue are only the third
largest slice.**

### 2.2 Category × `rango` — the machine-readable half

| Category | `rango` code / text |
|---|---|
| Corrección de errores | `1590` Corrección (errores o erratas) × 5 |
| Judicial | `1240` Sentencia × 5 · `63` Providencia × 2 |
| International | `1180` Acuerdo Internacional × 3 · `1370` Resolución × 1 |
| Amending-only | `1340` RD × 6 · `1350` Orden × 5 · `1370` Resolución × 2 · **`1300` Ley × 1** |
| Autonomous general | `1350` Orden × 9 · `1340` RD × 4 · `1500` Decreto-ley × 2 · `1370` Resolución × 1 |
| Singular / administrative | `1340` RD × 9 · `1370` Resolución × 4 · `1350` Orden × 4 |

Read the last three rows together: **`1340`, `1350` and `1370` each appear in all three
of the "is it a norm we want?" categories.** The rank code partitions the non-norms
perfectly and the norms not at all.

Full `rango` distribution over the 63:

| Code | Text | n | Code | Text | n |
|---:|---|---:|---:|---|---:|
| 1340 | Real Decreto | 19 | 1240 | Sentencia | 5 |
| 1350 | Orden | 18 | 1180 | Acuerdo Internacional | 3 |
| 1370 | Resolución | 8 | 1500 | Decreto-ley | 2 |
| 1590 | Corrección (errores o erratas) | 5 | 63 | Providencia | 2 |
| | | | 1300 | Ley | 1 |

For contrast, the 12 **consolidated** items on the same days: Ley × 4, Orden × 3, Real
Decreto-ley × 3, Acuerdo Internacional × 1, Real Decreto × 1.

### 2.3 Fields that look decisive and are not

Every one of the 63 documents carries all of `departamento`, `rango`,
`fecha_disposicion`, `fecha_publicacion`, `numero_oficial`, `titulo`,
`origen_legislativo`, `estatus_legislativo`, `seccion`, `subseccion`, `diario_numero`,
`pagina_inicial` (63/63 each). None of the following separates keep from drop:

| Field | Non-consolidated | Consolidated | Verdict |
|---|---|---|---|
| `seccion` | `1` × 63 | `1` × 12 | constant — no signal |
| `estatus_legislativo` | `L` × 59, empty × 4 | `L` × 12 | the 4 blanks are 2 providencias, 1 corrección, 1 sentencia — a *partial* non-norm signal, and it misses 8 of the 12 non-norms |
| `origen_legislativo` | Estatal 60 / Autonómico 3 | Estatal 8 / Autonómico 4 | CCAA acts appear on **both** sides |
| `<analisis><materias>` | populated on 71/75 | — | a subject thesaurus, not a scope signal |
| summary `<epigrafe>` | — | — | see below |

**`<epigrafe>` is a trap.** It looks like a controlled vocabulary and reads like one
("Subvenciones", "Organización", "Sentencias"), but it is *topical*, not typological.
`Subvenciones` labels four singular subsidy RDs **and** an amending-only RD
(`BOE-A-2025-17511`); `Organización` labels four singular acts **and** an amending-only
Orden (`BOE-A-2026-4971`). It is also **empty on 7 of the 17** singular acts, all from
1998–2003. It cannot carry a rule.

---

## §3 The cases a rule cannot decide

This is the part that decides the work. Each case is a real id from the sample.

### 3.1 Autonomous normative content the BOE never consolidates

**`BOE-A-2026-10881` — Reforma del apartado 3 del artículo 69 de la Constitución
Española** (Formentera senator), 19 May 2026.

| What the metadata says | What it is |
|---|---|
| `rango codigo="1676"` → **Reforma** | The fourth amendment to the Spanish Constitution in history |
| `seccion 1`, `origen_legislativo Estatal`, `estatus_legislativo L` | — |
| `<analisis><anteriores>` → `MODIFICA` | It amends `BOE-A-1978-31229`, which *is* consolidated |
| Not in the consolidated catalogue | 43,496 characters / 118 `<p>` of act text exist in the diary XML |

Why a rule gets this wrong: a rule that keys on "amends something else, therefore its
content lives in the target" drops the single highest-ranked normative act in the
sample. Its effects *are* in the Constitution's consolidated text, but the act itself —
the thing a lawyer cites — exists nowhere in `legalize-es`.

**`rango 1676` is not in `engine/src/legalize/fetcher/es/metadata.py::_RANK_CODE_MAP`,
and "Reforma" is not in `_RANK_TEXT_MAP`.** `_parse_rank` returns `None` for it and
falls through to `_infer_rank_from_title`, whose first test is `"constitución" in
lower` → `Rank.CONSTITUCION`. So today this act would be typed as *the Constitution
itself*. That is a bug regardless of what the scope rule turns out to be.

**`BOE-A-2014-12329` — Ley 28/2014** (the id from the issue), verified live:

| Field | Value |
|---|---|
| `rango` | `1300` **Ley** |
| `seccion` / `origen` / `estatus` | `1` / Estatal / `L` |
| In catalogue | **no** |
| Diary `<texto>` | 216,841 chars / 934 `<p>` |
| `<anteriores>` palabras | CITA, DEROGA, MODIFICA, SUPRIME, TRANSPONE |

A rule of "keep the high ranks, they are always consolidated" is false: **a state-level
`Ley` can be absent from the catalogue.** Conversely `BOE-A-2014-13253` (RD 1074/2014,
`rango 1340`, 67,064 chars) is absent for the same reason. Rank predicts nothing about
membership.

### 3.2 "404 today" vs "404 forever" — the lag, measured

Measured on the catalogue itself, from `fecha_actualizacion − fecha_publicacion`. For a
norm published in the last 30 days and not yet amended, `fecha_actualizacion` *is* its
first consolidation date; for older norms it drifts into "last amendment" and stops
being a lag measure, which is why only the first row is clean.

| Publication window | n | median lag | p75 | max | ≤1 d | ≤7 d | ≤30 d |
|---|---:|---:|---:|---:|---:|---:|---:|
| **0–30 d ago** | 12 | **1.5 d** | 2 | **7** | 50 % | **100 %** | 100 % |
| 30–90 d | 44 | 5.0 d | 26 | 39 | 27 % | 59 % | 86 % |
| 90–180 d | 72 | 16.5 d | 39 | 168 | 25 % | 40 % | 71 % |
| 180–365 d | 113 | 41.0 d | 75 | 298 | 11 % | 19 % | 37 % |
| 1–2 y | 206 | 359.0 d | 419 | 669 | 0 % | 0 % | 0 % |

**Conclusion: when the BOE consolidates an act, it does so within a week.** Of the 12
catalogue entries published in the last 30 days, every single one appeared within 7
days of publication. The decision is therefore final by day 30, and:

> **A retroactive sumario sweep must lag the gazette by ≥30 days.** Sweeping the last
> fortnight and treating every 404 as permanent will misfile acts that were simply not
> consolidated yet. Beyond 30 days, "404" is safe to treat as "never".

The recency ladder in the sample is **too thin to confirm this independently** — the
14 ladder days yielded only 29 Sección I items, 1–10 per age band, so its
consolidated-share-by-age curve (0 %, 100 %, 0 %, 30 %, 17 %, 11 %) is noise. The
catalogue-side measurement above is the one to trust. Stated as a caveat, not hidden.

### 3.3 Correcciones de errores — the brief's worry does not hold

The brief asks for "*correcciones de errores* that a rank field does not distinguish".
On this sample there are none: **all 5 carry `rango codigo="1590"`**, and the rank text
is literally `Corrección (errores o erratas)`. Title-prefix matching on
`"corrección de err"` selects exactly the same 5. The rank field is sufficient and is
the better key (it survives accent and wording drift).

Two second-order facts matter more than the classification:

- **A corrección can target a non-consolidated act, and then its content has nowhere to
  go.** `BOE-A-2026-17003` corrects `BOE-A-2026-14655` (Orden PJC/678/2026). Neither is
  in the catalogue. If we ingest `14655` and drop `17003`, we publish a text the BOE has
  since corrected, with no record of the correction. `14655`'s own
  `<posteriores>` carries `CORRECCIÓN de errores` pointing at `17003`, so the link is
  machine-readable — but "drop correcciones" must mean *apply and reference*, not
  *ignore*.
- **A corrección can be issued by the Tribunal Constitucional against a procedural
  act.** `BOE-A-2026-11849`, `departamento = Tribunal Constitucional`, corrects
  "Conflicto entre órganos constitucionales n.º 8598-2025". `rango 1590` catches it; a
  rule keyed on `departamento ∈ {TC, TS}` also catches it; a rule keyed on "is it an
  errata of a norm we hold" would not.

### 3.4 Judgments — they are mostly *not* what the brief expects

The brief asks whether TC judgments are in Sección I at all. **They are not.**
Constitutional Court judgments live in section `T`, which is present on 4 of the 28
sampled days (1998: 14 items, 2013: 10, 2021: 21, 2026-07-07: 2) and is a separate
section from `1`. `_LEGISLATIVE_SECTIONS` in `fetcher/es/sumario.py` already includes
`"T"` alongside `"1"` and `"1A"` — **that inclusion should be revisited**, because the
sumario sweep this work needs would pull section T in wholesale.

What *is* in Sección I is **Tribunal Supremo** judgments — 5 of the 63, all `rango 1240`,
all `Sala Tercera` (contencioso-administrativo) except one `Sala Cuarta`. They appear in
"Disposiciones generales" precisely because they **annul a general disposition**:
`BOE-A-2013-6582` "por la que se anula la declaración del carácter oficial…". They are
not norms and must not become law files — but a TS judgment that annuls a regulation is
exactly the kind of event the `reforms` table exists for. Dropping them silently loses
the annulment.

The 2 TC **providencias** (`rango 63`, 1982; a third found on 1987-06-16,
`BOE-A-1987-13973`, "Planteamiento de la cuestión de inconstitucionalidad número
732/1987") are pure procedural notices — a conflict has been raised, nothing decided.
Note `rango codigo="63"` breaks the 4-digit pattern of every other rank code; a parser
that assumes 4 digits will mis-handle it.

### 3.5 CCAA acts and international agreements

**Autonomic acts sit on both sides of the line and cannot be routed by `origen_legislativo`.**
The sample has 3 non-consolidated autonomic acts against 4 consolidated ones:

| id | `rango` | `departamento` | In catalogue |
|---|---|---|---|
| `BOE-A-1993-15396` | `1300` Ley | Comunidad Autónoma de Andalucía | no |
| `BOE-A-2026-14565` | `1500` Decreto-ley | Comunidad Autónoma de Extremadura | no |
| `BOE-A-2026-14658` | `1500` Decreto-ley | Comunidad Autónoma de Cataluña | no |

The catalogue holds 3,618 Autonómico entries, so the BOE *does* consolidate CCAA law —
just not these. Both 2026 Decretos-ley carry `<posteriores>` →
`SE PUBLICA Acuerdo de convalidación`, i.e. the BOE knows they were later ratified and
still keeps no consolidated text. They have 84,286 and 54,251 characters of autonomous
normative content and would land in `es-ex/` and `es-ct/`. `origen_legislativo` tells
you which shard; it tells you nothing about scope.

**International agreements are a category the rule should keep but the ranks blur.**
3 of the 4 carry `rango 1180 (Acuerdo Internacional)`, and the corpus already holds 254
consolidated `Acuerdo Internacional` entries — so this is a *known* document type, not a
new one. The fourth, `BOE-A-2024-20998`, is `rango 1370 (Resolución)`: the Secretaría
General Técnica's periodic "aplicación del artículo 24.2 de la Ley 25/2014" bulletin —
311,195 characters of treaty status changes. It is a *list of* treaty events, not a
norm. No field distinguishes it from `BOE-A-2017-11909`, also `1370`, also a
"Resolución … por la que se aprueba el calendario y las características", which *is* a
normative act. This is one concrete member of the §3.6 residue.

### 3.6 The residue the rule cannot decide — 27.0 %

**A Real Decreto granting a direct subsidy and a Real Decreto approving a regulation are
indistinguishable in the source.** Compare, both from the same gazette day
(2025-09-03), both `rango 1340`, `seccion 1`, `origen Estatal`, `estatus L`, both
non-consolidated, both with `<anteriores>` = `DE CONFORMIDAD con`:

| id | Title | Chars | Category |
|---|---|---:|---|
| `BOE-A-2025-17506` | RD 769/2025 … por el que se regula la **concesión directa de subvenciones** destinadas a la financiación de proyectos sostenibles | 37,455 | singular |
| `BOE-A-2024-20999` | RD 919/2024 … por el que se **establece una cualificación profesional** de la familia profesional Servicios Socioculturales | 1,534,689 | autonomous general |

Nothing in `rango`, `seccion`, `departamento`, `origen_legislativo`,
`estatus_legislativo`, `materias` or `epigrafe` separates them. The only discriminator
is the verb phrase in the title, which is prose — and `fetcher/es/sumario.py` already
carries a comment recording that reading the words in a title is how "the fourth reform
of the Constitution was [mistaken for] a new law". Repeating that mistake to sort
subsidies from regulations would be the same error in a new place.

**Size of the residue: 17 of 63 = 27.0 % of the non-consolidated population.**
Extrapolated to the whole backlog (§4), that is roughly **11,000–14,000 acts** whose
inclusion cannot be decided by a rule and must be decided by a policy.

Members of the residue in this sample, so the policy can be argued against real
documents: `BOE-A-1982-14244` (creates named courts), `BOE-A-1998-24161`
(publishes a Council of Ministers agreement), `BOE-A-1998-24162`/`24163` (homologate one
teaching qualification), `BOE-A-1998-24164`/`24165` (revise economic terms of concerted
healthcare), `BOE-A-2003-12024` (Congress publishes a convalidation agreement),
`BOE-A-2008-16860` (creates the EU Presidency organising committee), `BOE-A-2008-16861`
(creates one honorary consular office in Durango, Mexico), `BOE-A-2008-16862`,
`BOE-A-2013-6579` (creates a commemorations commission), `BOE-A-2017-11907` (creates a
ministerial digital-administration committee), `BOE-A-2025-17505`/`17506`/`17508`/`17509`
(direct subsidies), `BOE-A-2026-4972` (issue and minting of a collectors' coin).

---

## §4 Volume

Directly measured, then extrapolated. **Everything in the second block is EXTRAPOLATED.**

| Measured | Value | Sample |
|---|---|---|
| Sección I items per gazette day | **4.00** | 112 items / 28 days, 1982–2026 |
| — 1982–2003 | 6.00/day | 5 days |
| — 2008–2024 | 3.20/day | 5 days |
| — 2025–2026 | 2.07/day | 14 days |
| Non-consolidated share | **88.4 %** | 99 / 112 |
| Non-norms within that (judicial + corrección) | **19.0 %** | 12 / 63 |
| Undecidable residue (singular/admin) | **27.0 %** | 17 / 63 |

**EXTRAPOLATED** — base: 4.00 Sección I items/gazette day (112 items / 28 days);
multiplier: ~305 gazette days/year (Mon–Sat) × 47.7 years (1979-01-01 → 2026-09-03)
= 14,550 gazette days.

| Quantity | Estimate |
|---|---|
| Sección I items 1979–2026 | ~58,000 |
| Non-consolidated (× 88.4 %) | **~51,000** |
| Minus judicial + correcciones (× 81.0 %) | **~42,000** ingestable acts |
| Of which undecidable residue (× 27.0 %) | ~11,000 |
| If the residue is excluded | **~30,000** acts |

**Consistency check.** The catalogue holds 11,958 norms published 1979 or later. If the
Sección I total is ~58,000, the consolidated share is 20.6 %; the sample measured
11.6 %. The two disagree by a factor of 1.8, so treat ~42,000 as the middle of a
**~25,000–45,000** range rather than a point estimate. Either end of that range is
**2–3.5× the current 12,299-file corpus**, which confirms issue #66's "close to a
second corpus" and settles the sharding question the same way.

Sección I is shrinking (6.00 → 2.07 items/day), so the backlog is weighted toward the
1980s–1990s and the ongoing daily cost is small: at ~2 items/day, ~88 % non-consolidated,
~81 % of those ingestable, the steady state is **~1.4 new acts per gazette day**, ~430/year.

---

## §5 The text is not there before 1984 — GATE

Issue #66 states "the act's text is available" at `xml.php?id=`. **True from 1984
onward; false before it.** Measured on the direct child `<documento><texto>` (note: the
`<analisis><referencias><anterior><texto>` element has the same tag name and will fool a
`.//texto` XPath — it did on the first pass of this probe):

| Year | Empty `<texto>` / fetched |
|---|---|
| 1982 | **10 / 11** |
| 1983 | **2 / 2** |
| 1984 | 0 / 2 |
| 1985 | 0 / 3 |
| 1987 | 1 / 3 |
| 1988, 1993, 1998, 2003, 2008, 2013, 2014, 2017, 2024, 2025, 2026 | **0 / 67** |

The boundary is between 1983-10-18 (2/2 empty) and 1984-06-19 (2/2 populated). The one
1982 item that *does* have text (`BOE-A-1982-14239`, 51,725 chars) is also the only
consolidated item of that day, which suggests the BOE back-digitised XML text only for
what it consolidated.

Post-1984 emptiness still occurs: `BOE-A-1987-49972` (Reglamento de Radiocomunicaciones,
`rango 1180`) is empty — a large annex published as PDF only.

**EXTRAPOLATED** — base: the 1982/1983 measurement (12/13 empty) and the early-era rate
of ~9.6 Sección I items/day (measured on 1982, 1983, 1984, 1985, 1987: 11+6+12+8+11 = 48
items / 5 days); multiplier: 5 years × 305 days. Roughly **13,000–14,000 Sección I acts
published 1979–1983 have no machine-readable text at all** — metadata plus a scanned
PDF. That is ~26 % of the non-consolidated backlog and it cannot be ingested as text
without OCR.

**This is a gate, not a detail.** The scope rule and the parser are decidable for
1984→today. For 1979–1983 the decision is a different one: metadata-only stub files, or
nothing.

---

## §6 Recommended scope rule

A decision procedure over fields that exist in
`https://www.boe.es/diario_boe/xml.php?id={id}` and the daily sumario. No prose is read.

```
INPUT: a BOE id appearing in a daily sumario, section codigo = "1"

1. GATE — freshness
   if (today - fecha_publicacion) < 30 days:  DEFER
        Consolidation completes within 7 days when it happens at all
        (measured: 12/12 catalogue entries published in the last 30 days,
        max lag 7 d). Before day 30 a 404 is not yet a decision.

2. ORACLE — membership
   if id IS IN the consolidated catalogue:  EXISTING PATH
        text_state = point_in_time, fetch /texto as today.

3. DROP — not a norm.  rango codigo IN {1590, 1240, 63}
        1590 Corrección (errores o erratas)   -> record on the target's
             history via <posteriores>, do not emit a file
        1240 Sentencia                        -> TS annulment; candidate for
             the reforms table, never a law file
        63   Providencia                      -> TC procedural notice, discard
   Measured: drops 12/12 non-norms, 0 false drops, on the 63-act census.
   Belt and braces: departamento IN {Tribunal Constitucional, Tribunal Supremo}
   selects the same 8 of those 12 and nothing else — use it as an assertion,
   not as the key.

4. GATE — text
   if <documento><texto> is empty:  METADATA-ONLY or SKIP  (policy, see §5)
        ~100 % of pre-1984 acts; occasional PDF-only annexes after.

5. KEEP — emit as a law file
   text_state = as_enacted, last_amendment per spec v0.4,
   jurisdiction from origen_legislativo / departamento (es, or es-xx).

6. RESIDUE — the rule cannot decide.  27.0 % of the population.
   Singular/administrative acts: direct subsidies, creation of one committee or
   one office, a coin issue, homologation of one qualification, publication of
   an agreement. Identical in every field to normative acts of the same rango.
   -> RECOMMENDATION: KEEP them. See below.
```

**Recommendation on the residue: keep it.** Three reasons, in order of weight.

1. **There is no rule, so "exclude" means a heuristic on title prose** — the exact
   failure mode `fetcher/es/sumario.py` already carries a comment warning against.
   A heuristic that silently drops 27 % of the population will be wrong on an unknown
   fraction of it, and the errors are invisible.
2. **The BOE already made this call.** These acts are in "I. Disposiciones generales" by
   the publisher's own classification. Deferring to the source is the same principle the
   deterministic rewrite (`f9aa3db`) adopted for consolidation itself.
3. **The cost is bounded and one-directional.** Keeping the residue costs ~11,000 files
   of the ~42,000; dropping them later is a filter, whereas adding them later requires
   another full rebuild — and issue #66 already notes "a rebuild that lands without this
   cannot pick the acts up later without rebuilding again".

If the residue is nevertheless to be excluded, exclude it **by `rango` + `departamento`
allowlist per shard**, not by title matching, and record the excluded ids so the
decision is auditable.

### 6.1 Consequences for the engine

| Where | What |
|---|---|
| `fetcher/es/metadata.py::_RANK_CODE_MAP` | Missing `1676` (Reforma), `1590` (Corrección), `1240` (Sentencia), `63` (Providencia). `1676` is the dangerous one: `_infer_rank_from_title` currently types the constitutional reform as `Rank.CONSTITUCION`. |
| `fetcher/es/sumario.py::_LEGISLATIVE_SECTIONS` | Contains `"T"`. A sumario sweep for this work would pull the whole Constitutional Court section. Decide deliberately. |
| `fetcher/es/sumario.py::_infer_rank_from_title` | Rank is available as a code on the diary XML. Inferring it from the title is unnecessary once the sweep fetches the document anyway. |
| Discovery | The catalogue cannot discover this population by definition. The only index is the daily sumario — a day-by-day sweep of ~14,550 gazette days (#99, `discover_all` not wired). |
| Any new HTTP path | `Accept` header is mandatory on `/api/boe/sumario/` — `*/*` returns 400. |

---

## §7 Caveats

- **Sample size.** The taxonomy is a full census of **63** acts from 24 gazette days;
  the membership rate uses **112** acts from 28 days. Category percentages carry roughly
  ±6 pp of binomial noise at n=63. Direction is solid; second decimals are not.
- **Seasonal bias.** Days were chosen in June, September and October. Spanish
  legislative output is seasonal (December and June peaks for budget and end-of-session
  law). The per-day rate of 4.00 may understate the annual mean.
- **Category assignment is a judgement.** The split between *singular/administrative* and
  *autonomous general disposition* is exactly the residue the rule cannot decide, so it
  is exactly where my labels are least reproducible. Every id is listed in §2 and §3.6 so
  the assignment can be re-argued.
- **The lag measure is survivorship-biased.** `fecha_actualizacion − fecha_publicacion`
  is only observable for norms that made it into the catalogue. It answers "how fast,
  when it happens", not "what fraction eventually happens". The recency ladder that
  would have answered the second question yielded too few items to be usable.
- **The 30-day freshness gate rests on n=12** (catalogue entries published in the last
  30 days). It is the right order of magnitude, not a tuned constant.
- **Not measured:** whether an act ever *leaves* the catalogue; how `estado_consolidacion
  = Desactualizado` (195 entries) behaves; PDF/OCR feasibility for 1979–1983.
- **Adjacent finding, out of scope.** 86 of the 12,385 catalogue ids have no `.md` file
  in `countries/es`. 45 are from 2026 and 7 from 2025 (daily-update lag), but **34 are
  spread across 1982–2024** — a small pre-existing hole (~0.3 %) unrelated to this issue.
  Oldest: `BOE-A-1982-9070`, `BOE-A-1992-23429`, `BOE-A-1992-26093`, `BOE-A-2004-4513`.
- **Shared scratch directory.** `/Users/neli/.claude/jobs/5bf7ddf4/tmp` is written
  concurrently by 8 agents; another agent overwrote a module of mine mid-run. This
  probe's artefacts are isolated under `tmp/probe2/`.
