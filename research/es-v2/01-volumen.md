# ES re-emission — Probe 1: Volume

**Date:** 2026-09-03 · **Source:** BOE open data (`https://www.boe.es/datosabiertos`)
**HTTP requests spent:** **147** (budget 150). No 429, no 5xx, all 147 returned 200 except one
deliberate out-of-range probe (`sumario/19600105` → 404).
**Scratch data:** `/Users/neli/.claude/jobs/5bf7ddf4/tmp/` (`catalogue_raw.json`,
`summaries.json`, `summaries2.json`, `yearend.json`, `final_per_year.json`, `eras.json`).

---

## The one-line answer

The BOE publishes **≈ 1,000–2,400 Sección I acts a year**, and **only ~14 % of them
(1979–2026 pooled; 32 % in the 2020s, 2 % in the 1980s) ever get a consolidated text**.

Adding the non-consolidated acts of issue #66 takes `legalize-es` from **12,299 files** to:

| Cut | Sección I acts | of which consolidated | **NOT consolidated (new files)** | repo files after | × today |
|---|---:|---:|---:|---:|---:|
| **1979–2026** | 80,600 (95 % CI 68,600–93,600) | 10,448 | **70,200** | **82,500** | **6.7×** |
| **2000–2026** | 38,700 (95 % CI 31,300–47,600) | 8,080 | **30,700** | **43,000** | **3.5×** |
| **2010–2026** | 24,800 (95 % CI 20,300–29,900) | 5,494 | **19,300** | **31,600** | **2.6×** |

So the "12,299 → ~120,000" fear is **too high**. The realistic ceiling for the full
1979–2026 sweep is **~82,500 files**, and the 2010–2026 cut lands at **~31,600**.

---

## 1. The consolidated catalogue is now exactly enumerated (2 requests)

`GET /api/legislacion-consolidada?limit=10000&offset=N` with `Accept: application/json`.
`limit=10000` is honoured. Two requests (offset 0 and 10000) exhaust it.

| Fact | Value | How obtained |
|---|---:|---|
| Total consolidated norms | **12,385** | 2 requests, `len(set(identificador))` over both pages; 0 duplicates |
| Estatal (`ambito` 1) | 8,767 | field count over all 12,385 |
| Autonómico (`ambito` 2) | 3,618 | idem |
| …with a `BOE-A-` id | 3,373 | prefix count |
| …with a regional-gazette id (`BOJA-b-`, `BOA-d-`, `BORM-s-`, …) | **245** | prefix count — these **never** appear in a BOE summary |
| `estado_consolidacion` = Finalizado (3) | 12,190 | field count |
| `estado_consolidacion` = Desactualizado (4) | **195** | field count |
| `vigencia_agotada` = S | 2,412 | field count |
| Earliest `fecha_publicacion` | 1835 | min over all |
| Published before 1979 | **427** | year count |

Rank distribution (top): Ley 3,807 · Real Decreto 3,495 · Orden 2,399 · Resolución 832 ·
Real Decreto-ley 309 · Decreto-ley 289 · Acuerdo Internacional 254 · Ley Foral 207 ·
Ley Orgánica 184 · Constitución 1.

By decade of `fecha_publicacion`: pre-1979 427 · 1970s 62 · 1980s 997 · 1990s 1,611 ·
2000s 2,953 · 2010s 3,679 · 2020s 2,656.

### 1.1 The published corpus is a strict subset of the catalogue — 86 norms short

`ls countries/es/{es,es-*}/*.md` → 12,299 ids, intersected with the 12,385 catalogue ids:

| | count |
|---|---:|
| In catalogue, **not** in `countries/es` | **86** |
| In `countries/es`, not in catalogue | **0** |

45 of the 86 are 2026 (the drift since the corpus last ran clean); the rest are scattered
(2025: 7, 2024: 3, 2023: 3, one from 1982, two from 1992…). So the corpus == the consolidated
catalogue, minus recent drift. **Everything the re-emission would add is genuinely new**;
nothing in the repo is outside the catalogue.

---

## 2. Sampling design — 128 summary days over 17 years

`GET /api/boe/sumario/{YYYYMMDD}` (XML). Two passes:

* **Pass A (108 requests):** 12 years × 9 days — 1979, 1984, 1989, 1994, 1999, 2004, 2009,
  2013, 2017, 2020, 2023, 2025. Days chosen by taking the list of all non-Sunday days of the
  year and picking indices `⌊i·len/9⌋`, i = 0…8 → evenly spread across the calendar.
* **Pass B (20 requests):** 5 more recent years × 4 days — 2011, 2015, 2019, 2022, 2026 —
  on a half-offset grid so they do not collide with Pass A. 2026 capped at 2026-09-02.
* **Pass C (12 requests):** the last publication day of each Pass-A year (see §3).
* **Pass D (5 requests):** the 2 catalogue pages, plus 3 reach probes (§6).

Weekday balance of the 108-day Pass A: Mon 20, Tue 16, Wed 20, Thu 17, Fri 19, Sat 16 — no
weekday over-represented by more than 25 %.

**Sample totals:** 128 days · **641 Sección I acts** · 9,311 BOE-A ids of all sections.
Sección I items per day: min 0, p25 2, **median 4**, p75 8, max 24.
**10 of 128 days carried no Sección I at all** (1989-05-03, 1994-01-01, 1994-06-13,
1999-01-01, 2009-09-01, 2017-01-02, 2020-09-01, 2023-01-02, 2025-05-02, 2026-08-03) — a
Sección-I-less BOE is normal, not an API failure.

---

## 3. The trick that made this cheap and exact: BOE-A ids are contiguous per year

Measured, not assumed. On every sampled day the BOE-A numbers form a contiguous block, and
the block is ordered **Sección I → II-A → II-B → III → T**. Example, 2023-06-12:

| section | BOE-A range | n |
|---|---|---:|
| 1 | 13798–13804 | 7 |
| 2A | 13805–13825 | 21 |
| 2B | 13826–13903 | 78 |
| 3 | 13904–13949 | 46 |
| T | 13950–13966 | 17 |

Numbering restarts at 1 every 1 January (verified: the first sampled day of each of the 12
Pass-A years has `min(BOE-A) == 1`). Therefore **the highest BOE-A number on the last
publication day of a year is an exact count of the year's BOE-A documents**, `A(y)`.
One request per year buys it. Pass C:

| year | last pub. day | **A(y) exact** | catalogue-anchored estimate | error |
|---|---|---:|---:|---:|
| 1979 | 1979-12-31 | 30,683 | 30,753 | +0.2 % |
| 1984 | 1984-12-31 | 28,386 | 28,337 | −0.2 % |
| 1989 | 1989-12-30 | 30,667 | 30,672 | +0.0 % |
| 1994 | 1994-12-31 | 29,041 | 28,972 | −0.2 % |
| 1999 | 1999-12-31 | 25,010 | 24,924 | −0.3 % |
| 2004 | 2004-12-31 | 21,965 | 21,914 | −0.2 % |
| 2009 | 2009-12-31 | 21,238 | 21,183 | −0.3 % |
| 2013 | 2013-12-31 | 13,837 | 13,811 | −0.2 % |
| 2017 | 2017-12-30 | 15,897 | 15,855 | −0.3 % |
| 2020 | 2020-12-31 | 17,418 | 17,348 | −0.4 % |
| 2023 | 2023-12-30 | 26,802 | 26,741 | −0.2 % |
| 2025 | 2025-12-31 | 27,213 | 27,207 | −0.0 % |

The right-hand column is a **zero-HTTP estimator**: take the highest-numbered consolidated
BOE-A id of that year from the catalogue, divide by the fraction of the year's publication
days that had elapsed at its `fecha_publicacion`. It is accurate to **0.22 % mean absolute
error** across all 12 calibration years, so I use it for the 36 years I did not measure
directly. `A(2026) = 28,801`, annualised from `BOE-A-2026-16931` on the sampled 2026-08-03
(the catalogue anchor gave 27,456; I use the summary anchor, +5 %).

`A(y)` for every year 1979–2026 is in `final_per_year.json`. It ranges from **12,605 (2016)
to 34,845 (1982)** — the BOE's document volume is *not* flat, which is why a plain
"acts/day × days" projection is the weaker of the two estimators.

---

## 4. Sección I acts per year — three independent routes

* **R1 — ratio estimator (preferred).** `secI(y) = A(y) × r_era`, where
  `r_era = Σ Sección-I BOE-A ids / Σ all BOE-A ids` over that era's sampled days. Both
  numerator and denominator scale with the day's size, so day-to-day volume swings cancel.
* **R2 — day-mean.** `secI(y) = mean(Sección-I items per sampled day) × publication days in y`.
  Publication days = calendar days minus Sundays (312–314/year). Justified: all 128 sampled
  non-Sunday days returned a real summary, including four 1-Januarys.
* **R3 — catalogue inversion.** `secI(era) = consolidated_exact(era) × 0.892 / frac_cons(era)`,
  where 0.892 is the measured share of consolidated norms that sit in Sección I (§5) and
  `frac_cons` is the measured consolidated share of sampled Sección I ids.

| era | days | secI in sample | BOE-A in sample | `r_era` | acts/day | consolidated in sample | `frac_cons` | R1 | R2 | R3 | consolidated (exact) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1979–1989 | 27 | 186 | 2,523 | 0.0737 | 6.89 | 4 | 0.022 | 24,819 | 23,725 | *43,718* | 1,054 |
| 1990–1999 | 18 | 94 | 1,606 | 0.0585 | 5.22 | 4 | 0.043 | 17,082 | 16,351 | *33,560* | 1,601 |
| 2000–2009 | 18 | 69 | 1,135 | 0.0608 | 3.83 | 6 | 0.087 | 13,984 | 12,002 | *29,738* | 2,899 |
| 2010–2019 | 30 | 128 | 1,605 | 0.0798 | 4.27 | 24 | 0.188 | 13,067 | 13,355 | 17,179 | 3,611 |
| 2020–2026 | 35 | 164 | 2,442 | 0.0672 | 4.69 | 53 | 0.323 | 11,693 | 10,271 | 7,033 | 2,548 |

**Pooled Sección-I share of all BOE-A documents: 641 / 9,311 = 6.88 %**, day-bootstrap 95 % CI
[5.93 %, 7.89 %], 20,000 resamples over the 128 days. The share is remarkably stable across
eras — 1979–1999: 6.78 %, 2000–2012: 6.88 %, 2013–2026: 7.00 % — which is the main reason R1
is trustworthy.

### Sanity check (this is the check §5 of the brief asked for)

R1 and R2 agree to within **3–7 %** in every era. **R3 agrees to within 5 % for 2010–2026
(24,212 vs 24,760 / 23,626) and diverges by 2–3× before 2010.** That divergence is a real
finding, not a bug: R3 divides by `frac_cons`, and before 2010 `frac_cons` is measured from
**4, 4 and 6 events**. A proportion estimated from 4 successes carries ~50 % relative error,
and inverting it amplifies that to 2–3×. **R3 is only usable from 2010 onward, where it
independently confirms R1.** I therefore report R1 as the central estimate everywhere and
R2 as the lower shoulder.

### Per-year projection (abridged; full table in `final_per_year.json`)

| year | A(y) | Sección I (R1) | consolidated via Sec. I | **not consolidated** |
|---|---:|---:|---:|---:|
| 1979 | 30,683 | 2,112 | 55 | 2,057 |
| 1985 | 26,990 | 1,858 | 114 | 1,744 |
| 1990 | 31,381 | 2,160 | 103 | 2,057 |
| 1995 | 27,975 | 1,926 | 167 | 1,759 |
| 2000 | 24,368 | 1,678 | 138 | 1,539 |
| 2005 | 21,611 | 1,488 | 260 | 1,228 |
| 2010 | 20,173 | 1,389 | 382 | 1,007 |
| 2015 | 14,348 | 988 | 415 | 573 |
| 2020 | 17,418 | 1,199 | 635 | 564 |
| 2023 | 26,802 | 1,845 | 285 | 1,561 |
| 2025 | 27,213 | 1,873 | 180 | 1,693 |
| 2026 | 28,801 | 1,983 | 153 | 1,829 |

(The per-year `r` used here is the era ratio, not the noisy per-year one; the table above
was generated with the pooled 6.88 % and matches the era-wise R1 total to within 2 %.)

---

## 5. Where a consolidated norm lives in the summary — 89.2 %, measured

Free cross-tabulation: for each of the 128 sampled days, take every catalogue entry whose
`fecha_publicacion` equals that day and look up which section of that day's summary contains
its identifier.

| location | n | share |
|---|---:|---:|
| **Sección I** | 91 | **89.2 %** |
| Sección III ("Otras disposiciones") | 10 | 9.8 % |
| Sección II-B | 1 | 1.0 % |
| not in the summary at all | 0 | 0 % |
| **total** | **102** | |

So **one consolidated norm in ten never appeared in Sección I** — it came through Sección III.
This is why the catalogue's per-year count is *not* the same population as "Sección I acts
that got consolidated", and it is the factor 0.892 used in every table above.

Separately, the **245 catalogue entries with a regional-gazette id** (`BOJA-b-…`, `BOA-d-…`,
`DOGC-f-…`, …) are by construction outside any BOE summary. The other 3,373 autonómico norms
*do* carry `BOE-A-` ids, i.e. they were republished in the BOE — which is why "Autonómico"
being 29 % of the catalogue does not mean 29 % of it is outside Sección I.

**Consolidated share of Sección I, by decade** (direct intersection of sampled Sección-I ids
against the 12,385-id catalogue — this is the headline trend):

| decade | days | Sección I ids | consolidated | share |
|---|---:|---:|---:|---:|
| 1970s (1979 only) | 9 | 56 | 0 | **0.0 %** |
| 1980s | 18 | 130 | 4 | 3.1 % |
| 1990s | 18 | 94 | 4 | 4.3 % |
| 2000s | 18 | 69 | 6 | 8.7 % |
| 2010s | 30 | 128 | 24 | 18.8 % |
| 2020s | 35 | 164 | 53 | **32.3 %** |
| **pooled 1979–2026** | **128** | **641** | **91** | **14.2 %** |

The BOE consolidates a steadily larger slice of what it publishes; even so, **two out of
three Sección I acts of the 2020s have no consolidated text**.

---

## 6. Reach and structure of the summary API

| question | answer | evidence |
|---|---|---|
| Does Sección I reach 1979? | Yes, and further | `sumario/19790101`…`19791231` all 200 with `seccion codigo="1"` |
| Does it reach before 1979? | **Yes — at least 1970** | `sumario/19700105` → 200, sections `1,2A,2B,3,4,5A,5B`, `codigo="1"` named "I. Disposiciones generales", 3 items. `sumario/19780103` → 200, same shape |
| Where does it stop? | Between 1960 and 1970 | `sumario/19600105` → **404** `"La información solicitada no existe"` |
| Does the format change over time? | **No** | Same `response/data/sumario/diario/seccion[@codigo]/departamento/…/item` tree in 1970, 1979 and 2026. `seccion@codigo="1"` and `@nombre="I. Disposiciones generales"` are constant across all 131 summaries fetched |
| Years where the API 200s but has no `seccion codigo="1"`? | Individual **days**, yes; **years, no** | 10 of 128 sampled days had no Sección I (list in §2). Every one of the 17 sampled years had Sección I on most days |
| Is another section carrying general provisions? | **No** | Full inventory below |

**Every section code seen in 131 summaries** (1970–2026):

| code | name | days seen | items |
|---|---|---:|---:|
| `1` | I. Disposiciones generales | 118 | 641 |
| `2A` | II. Autoridades y personal — Nombramientos… | 127 | 1,533 |
| `2B` | II. Autoridades y personal — Oposiciones y concursos | 128 | 2,085 |
| `3` | III. Otras disposiciones | 128 | 3,643 |
| `4` | IV. Administración de Justicia | 111 | 3,989 |
| `5` | **V. Comunidades Autónomas** (old layout) | 8 | 72 |
| `5A`,`5B`,`5C` | V. Anuncios (subastas / otros / particulares) | 113/113/76 | 5,420 |
| `6A`,`6B`,`6C` | VI. Anuncios (older numbering of the same) | 9/9/1 | 19 |
| `T` | T.C. Suplemento del Tribunal Constitucional | 6 | 64 |

Two things the current code should know:

1. **`"1A"` does not exist.** `_LEGISLATIVE_SECTIONS = {"1", "1A", "T"}` in
   `engine/src/legalize/fetcher/es/sumario.py` accepts a code that appeared **0 times in 131
   summaries spanning 1970–2026**. Harmless, but it is dead.
2. **Old summaries carry a `codigo="5"` section named "V. Comunidades Autónomas"** (8 days,
   all in the 1979/1984 samples, 72 items, all `BOE-A-` ids). It is *not* general provisions —
   it is the autonomic-legislation block of the pre-1990s layout. Whether those 72 belong in
   scope is a scoping call for the re-emission, not a bug; today they are excluded and the
   projections above exclude them too.
3. Old **T.C. supplement** documents take `BOE-A-YYYY-499xx`/`500xx` ids, outside the
   contiguous daily block. Every count above filters `id number < 40000` to exclude them.

---

## 7. Impact on the repo

New files = **non-consolidated Sección I acts** (the consolidated ones are already there).
Consolidated-via-Sección-I is `catalogue count for the period × 0.892`, an exact number times
a measured constant.

| cut | Sección I acts (R1) | 95 % CI | consolidated (exact, all sections) | consolidated **via Sec. I** | **new files** | repo total | × today |
|---|---:|---|---:|---:|---:|---:|---:|
| 1979–2026 | 80,646 | 68,553 – 93,567 | 11,713 | 10,448 | **70,198** | **82,497** | 6.7× |
| 2000–2026 | 38,744 | 31,320 – 47,576 | 9,058 | 8,080 | **30,664** | **42,963** | 3.5× |
| 2010–2026 | 24,760 | 20,292 – 29,926 | 6,159 | 5,494 | **19,266** | **31,565** | 2.6× |

Reading the CI as the planning range: the 1979–2026 sweep lands somewhere between **70,900 and
95,900 files**; the 2010–2026 cut between **27,100 and 36,700**.

Add, in every cut, the **86 catalogue norms currently missing from the corpus** and (if the
scope is widened past Sección I) the **~10 % of consolidated norms that arrive via Sección III**
— the latter are already published, so they change no file count.

Size, marked **EXTRAPOLATED**: `countries/es` is 1.58 GiB for 12,299 files + 44,295 commits.
A non-consolidated act has **one** version, so it contributes one file and one commit versus a
consolidated norm's mean 3.6 commits. Per-file bytes are the only thing I did not measure here
— Probe 2 territory — but on a naive per-file scaling the 1979–2026 sweep is ~6.7× the file
count with ~1.6× the commits, so the repo is dominated by files, not history, in a way it is
not today.

---

## 8. Caveats

1. **The projection rests on 128 sampled days out of ~15,000 publication days (0.85 %).** The
   bootstrap CIs quoted are day-resampling CIs and already absorb the day-to-day clustering
   (0–24 acts/day). They do **not** absorb a systematic seasonal effect that my
   evenly-spread-through-the-calendar design would have missed.
2. **`frac_cons` for 1979–2009 rests on 14 consolidated hits in total.** The *non-consolidated*
   counts for those eras are therefore driven almost entirely by the Sección I projection
   (which is solid) and only marginally by the consolidated share (which is not) — fortunately
   the consolidated share is small there, so the error it can inject is small in absolute terms.
3. **`A(2026) = 28,801` is an annualisation** from one August day; 2026 is 8 months old.
4. **I counted acts, not laws.** A Sección I item is one BOE disposition. Corrections
   (`corrección de errores`), extensions and repeals each count as one act. What fraction of
   the 70,198 is worth a file rather than a note on another file is Probe 2/3's question.
5. **Rank mix of the non-consolidated population is unmeasured here** — I saved only
   identifiers from the summaries, not titles. If the answer changes the decision (e.g. "keep
   only Ley/RD/RDL and drop Orden/Resolución"), it needs one more sampling pass over the same
   128 days, ~0 extra requests if the summaries are re-fetched with titles.
6. **`estado_consolidacion = 4 (Desactualizado)` on 195 catalogue norms** means the BOE itself
   says their consolidated text is stale. Those 195 are in the corpus today, presented as
   consolidated. Worth a `text_state` decision in the mixed-state work — not measured further here.
