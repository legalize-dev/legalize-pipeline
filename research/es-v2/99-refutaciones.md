
## taxonomy — angle 3: the 404 is a moving target, and the probe's lag instrument is a batch timestamp

**Verifier:** independent probe, 2026-09-03. **HTTP requests spent: 57 of 100.**
Scratch, caches and scripts: `/Users/neli/.claude/jobs/5bf7ddf4/tmp/refute3/`.

**Verdict: PARTIALLY REFUTED.** The taxonomy, the `rango` drop rule and the catalogue size
survive. **The consolidation-lag section (§3.2) does not, and neither does step 1 of the
recommended scope rule.** The probe's central lag claim — *"when the BOE consolidates an act,
it does so within a week… the decision is final by day 30"* — is an artefact of two stacked
measurement errors. Measured correctly, the median lag is **12 days, not 1.5**, only **44 %**
of consolidations land within 7 days, and **a third arrive after day 30**. The 30-day
freshness gate is wrong by roughly 6×.

---

### 1. My sample (deliberately disjoint from the probe's)

| Instrument | What | Sample |
|---|---|---|
| Membership oracle | Consolidated catalogue, 12,385 ids | Probe's cached bytes reused as *raw source*, re-parsed independently (see §6 on why I could not re-fetch) |
| **Clean lag cohort** (primary) | Every catalogue entry published **after 2025-12-20** | **n = 186** — 15× the probe's n=12 |
| Amendment check | `xml.php?id=` `<analisis><referencias><posteriores>` | 12 slowest + 6 fast controls = **18 ids**, listed in §4 |
| Age ladder | Sección I items from **36 gazette days**, 6 age bands | 2026-08-24..29, 08-17..22, 08-03..08, 07-13..18, 2026-03-09..14, 2025-09-08..13 — **zero overlap** with the probe's 28 days |
| Cohort density | Same calendar window (Aug 1 – Sep 3) across 13 years | offline, 0 requests |

---

### 2. The instrument is broken: 80.6 % of `fecha_actualizacion` is one batch re-stamp

The probe's entire lag table is `fecha_actualizacion − fecha_publicacion`. That field is not
a per-norm event.

| Update day | rows |
|---|---:|
| 2025-12-19 | 3,299 |
| 2025-12-18 | 2,561 |
| 2025-12-20 | 2,360 |
| 2025-12-17 | 889 |
| 2025-12-16 | 871 |
| **2025-12-16 .. 20 total** | **9,980 = 80.6 % of the catalogue** |

Those 9,980 rows carry publication years spanning **1851 to 2025, across 107 distinct
years**; 2,651 of them (27 %) were published before 2000. A norm published in 1851 was not
"amended" in the same five-day window as 9,979 others. This is a bulk re-stamp of the
consolidated corpus, and it overwrites the field the probe used as its clock.

Consequence for the probe's §3.2 table — I reproduced it exactly, then added the
contamination column:

| Cohort (publication age) | n | **batch-stamped** | median lag | ≤7 d | ≤30 d |
|---|---:|---:|---:|---:|---:|
| 0–30 d | 12 | 0 % | 1.5 | 100 % | 100 % |
| 30–90 d | 44 | 0 % | 5.0 | 59 % | 86 % |
| 90–180 d | 72 | 0 % | 16.5 | 40 % | 71 % |
| 180–365 d | 113 | **34 %** | 41.0 | 19 % | 37 % |
| 1–2 y | 206 | **61 %** | 359.0 | 0 % | 0 % |
| 2–5 y | 1,040 | **75 %** | 1,137.0 | 0 % | 0 % |

The bottom three rows measure the distance from publication to December 2025. The probe read
them as "amendments" and concluded the field *drifts* into meaning last-amendment. It does
not drift; it was overwritten. Rows ≥180 d should be struck.

### 3. The "clean" row is right-censored, and that is what produces "100 % within 7 days"

The probe's one clean row is *"published in the last 30 days"*. An act published 25 days ago
**cannot exhibit a 30-day lag** — there has not been time to observe one. That window can only
ever return lags below 30, and it oversamples the fast. It is structurally incapable of
falsifying the claim it was used to support.

The correct clean window is *published after the batch ended* — 2025-12-21 onward, **n = 186**,
8.5 months wide. Correcting for censoring (for threshold *k*, count only acts published at
least *k* days ago, so a lag of *k* is observable):

| k (days) | eligible n | P(consolidated ≤ k) | **probe's claim** |
|---:|---:|---:|---|
| 0 | 186 | 20.4 % | |
| 1 | 185 | 25.4 % | median = 1.5 d → implies 50 % |
| 3 | 182 | 36.3 % | |
| **7** | 180 | **44.4 %** | **100 %** |
| 14 | 177 | 52.0 % | |
| **30** | 174 | **66.7 %** | **100 %, "final by day 30"** |
| 60 | 154 | 81.8 % | |
| 90 | 130 | 84.6 % | |
| 120 | 105 | 90.5 % | |
| 180 | 58 | 96.6 % | |

**Median lag = 12 days. p90 = 93 days. Max = 234 days.**

### 4. Proof the long lags are consolidation, not amendment

The obvious objection: a 168-day gap could be prompt consolidation followed by an amendment.
I tested it directly — an act with **no modificative `<posteriores>`** has had nothing happen
to it since publication, so `fecha_actualizacion` can only encode its own consolidation.

Of the 12 slowest acts in the clean cohort, **6 have zero modificative posteriores**:

| BOE id | Published | Lag | `posteriores` | What it is |
|---|---|---:|---|---|
| **BOE-A-2025-27207** | 2025-12-31 | **168 d** | **zero, of any kind** | Resolución, Instituto Social de la Marina |
| **BOE-A-2026-992** | 2026-01-17 | **166 d** | **zero, of any kind** | Ley 7/2025 de la Generalitat, acceso |
| BOE-A-2026-3810 | 2026-02-19 | 161 d | 12, none modificative | Real Decreto-ley 5/2026 |
| BOE-A-2026-945 | 2026-01-16 | 152 d | 2, both *corrección de errores* | Ley 8/2025, presupuesto autonómico |
| BOE-A-2026-5060 | 2026-03-04 | 118 d | corrección + convalidación | Real Decreto-ley 6/2026 |
| BOE-A-2026-7558 | 2026-04-03 | 116 d | 2, both *corrección de errores* | Ley 2/2026, Gestión Ambiental de Andalucía |

The first two are airtight: **nothing whatsoever** is recorded against them after publication.
Their consolidated text simply appeared 166–168 days late.

Control: 6 acts with lag ≤ 1 d and age ≥ 180 d (BOE-A-2026-5128, -3815, -3001, -2727, -2625,
-2147) also have zero posteriores. So the *same field, read the same way*, yields 0 days for
some acts and 168 for others. That is the moving target, demonstrated on named ids.

### 5. What survives — the 404 is not a moving target *forever*

Two of my measurements back the probe's direction at long range, and I record them as
confirmations:

**Same-season cohort density** (kills the seasonality confound: identical calendar window,
different age). If consolidations were still arriving years later, recent cohorts would be
depleted. They are not:

| Window | age | entries | per day |
|---|---:|---:|---:|
| 2026-08-01 .. 09-03 | 0 d | 13 | 0.38 |
| 2025-08-01 .. 09-03 | 365 d | 12 | 0.35 |
| 2024-08-01 .. 09-03 | 730 d | 14 | 0.41 |
| 2019-08-01 .. 09-03 | 2,557 d | 7 | 0.21 |

No age trend; 2019 has *fewer* than 2026. Combined with the censoring-corrected curve
(96.6 % arrive within 180 days), the backlog does clear — **at six months, not at one week.**

**Age ladder, 36 gazette days, 107 Sección I items** — reported as noise, exactly as the probe
reported its own: 1w 36.4 % · 2w 0 % · 4w 28.6 % · 8w 11.6 % · 26w 23.3 % · 52w 9.1 %
(n per band 5–43). A sumario-day ladder cannot answer this question at any affordable budget;
the catalogue-side cohort can, which is why I moved the load there.

**Pooled non-consolidated share = 82.2 %** (88 of 107) against the probe's **88.4 %** (99 of
112). Overlapping at n≈110 (±7 pp). The finding "the overwhelming majority of Sección I is
never consolidated" is confirmed; **the second digit is not safe to quote.**

### 6. Numbers I could not reproduce, and one correction to the brief

The brief's endpoint path `GET /api/legislacion-consolidada` is **wrong** — it 404s. The real
path is **`/datosabiertos/api/legislacion-consolidada`**. Cost me 2 requests. The documented
`limit=-1` ("obtener todos") also 404s; the probe's `limit=10000` two-page walk is in fact the
working method. I therefore reused the probe's cached catalogue bytes as raw source rather
than burn budget rediscovering its pagination, and verified independently that it holds
12,385 rows / 12,385 unique ids with no duplicates — **catalogue size CONFIRMED.**

### 7. What this changes in the plan

Step 1 of the probe's scope rule reads:

```
if (today - fecha_publicacion) < 30 days:  DEFER
```

On my measurement that gate **misfiles 33.3 % of the acts that will eventually be
consolidated** as permanently non-consolidated. Since the re-emission is a one-shot backfill
whose output is the corpus, those become wrong files with the wrong `text_state`.

Replace with:

| Gate | Residual misfiling | Comment |
|---:|---:|---|
| 30 d | 33.3 % | the probe's value — not usable |
| 90 d | 15.4 % | |
| 120 d | 9.5 % | |
| **180 d** | **3.4 %** | recommended for the one-shot backfill |

For the daily pipeline the gate is the wrong shape entirely: an act must be **re-checked**
against the catalogue for six months after publication, not classified once and frozen. A
`DEFER` list with a 180-day re-test window is the durable form.

**Caveats on my own work.** The clean cohort (n=186) assumes the Dec-2025 batch re-stamped
*every* row it touched rather than genuinely consolidating some of them; if some were real,
my clean window is right and my contamination figure is a ceiling. The censoring correction
assumes acts consolidated and not-yet-consolidated share a lag distribution — standard, but it
still cannot see acts that will *never* arrive, so P(≤k) is conditional on eventual
consolidation. The amendment check rests on 18 ids; the two zero-posteriores cases are
airtight, the other four rely on treating *corrección de errores* as non-modificative. The
ladder is noise and I have not dressed it up as anything else.
## volume — angle 2: is the consolidated-membership oracle sound?

**Verifier:** independent probe, 2026-09-03. **HTTP spent: 98 / 100** (20 of them wasted — see
§0). No 429, no 5xx. UA `legalize-bot/1.0`, 0.75 s between requests.
**Scratch:** `/Users/neli/.claude/jobs/5bf7ddf4/tmp/v2/` (`sumarios.json`, `a_enum.json`,
`b_member.json`, `final_rows.json`).

**Verdict: PARTIALLY_REFUTED.** The membership oracle itself — the thing I was sent to break —
**survives every test I could throw at it**, and I confirm the headline file counts. What does
not survive is the **per-decade consolidated-share table (§5 of the probe)**: my independent
sample disagrees with it by up to 3.5×, in both directions, and the probe's *own* model implies
a third set of values again. That table is not safe to decide on. Fortunately nothing in the
file-count arithmetic depends on it (§6 below).

---

### 0. First, an operational finding that cost me 20 requests

`GET /api/boe/sumario/{YYYYMMDD}` **returns HTTP 400 (187 bytes) when no `Accept` header is
sent.** All 20 of my first summary requests died this way; the identical URL with
`Accept: application/xml` returns 200. Evidence: request 1–20 all 400, request 21
(`sumario/20121211`, `Accept: application/xml`) 200 / 198,800 B. The probe never hit this
because its helper always passed `accept=`. Worth a line in the engine's client.

Two more traps found on the consolidated endpoint, both free from files already on disk:

* `?limit=-1` does **not** return everything — it silently caps at **10,000**
  (`catalog_full.json` on disk: 13.0 MB, exactly 10,000 items).
* A `from`/`to` window can silently truncate at the same cap. My window
  `from=20251215&to=20251221` returned **9,980** — 20 short of the cap, by luck.
  `fecha_actualizacion` is not uniform: **10,017 of the 12,385 norms were bulk-restamped in
  December 2025**, 9,980 of them in one week. Any windowed fetch over a restamp period is one
  BOE housekeeping run away from losing rows with no error.

---

### 1. Attack A — is the enumeration complete? (11 requests) → **oracle survives**

The probe paged by `offset` over a listing sorted `fecha_actualizacion` **descending**, i.e. over
a key that mutates continuously. Classic offset-paging drift: rows re-sorted between page 1 and
page 2 are duplicated or lost. I attacked this two ways.

**A1 — five independent offset dumps, zero HTTP.** Different agents dumped the catalogue at
different moments today. All five id sets are byte-for-byte the same population:

| dump | ids | vs `catalogue_raw.json` |
|---|---:|---|
| `catalogue_raw.json` (the probe's) | 12,385 | — |
| `catalog.json` | 12,385 | 0 extra / 0 missing |
| `probe8_catalog.json` | 12,385 | 0 extra / 0 missing |
| `catalogue.json` | 12,385 | 0 extra / 0 missing |
| `catalog_all.json` | 12,385 | 0 extra / 0 missing |

**A2 — enumeration on a different axis (11 requests).** I partitioned the catalogue by
**`fecha_actualizacion` windows** instead of by offset — a different index, disjoint windows, no
`offset` parameter anywhere:

| window | items |
|---|---:|
| 19000101–20221231 | 0 |
| 20230101–20231231 | 80 |
| 20240101–20241231 | 47 |
| 20250101–20251130 | 42 |
| 20251201–20251207 | 0 |
| 20251208–20251214 | 0 |
| 20251215–20251221 | 9,980 |
| 20251222–20251231 | 37 |
| 20260101–20260331 | 759 |
| 20260401–20260630 | 789 |
| 20260701–20260910 | 651 |
| **union** | **12,385** |

**Duplicates across windows: 0. In the window union but not the offset dump: 0. In the offset
dump but not the windows: 0.** The `19000101–20221231` window returning 0 also rules out a
truncated tail of old-stamped norms. The enumeration is complete and stable.

---

### 2. Attack B — direct membership verification (41 requests) → **oracle survives, exactly**

I probed `/api/legislacion-consolidada/id/{id}/metadatos` directly on ids drawn from **my own
25-day sample** (§4), adversarially stratified. A 200 carries a real `<metadatos>` block; a
non-member returns HTTP 404 with a 170-byte `<status><code>404</code></status>` envelope.

**Confusion matrix (n = 41):**

| | `/metadatos` 200 | `/metadatos` 404 |
|---|---:|---:|
| **in the 12,385 listing** (n=14) | **14** | 0 |
| **not in the listing** (n=27) | 0 | **27** |

* False negatives 0/27 → Wilson 95 % upper bound **12.5 %**; pooled with the earlier probe's 14
  not-in-listing 404s, **0/41, upper bound 8.6 %**.
* False positives 0/14 → upper bound 21.5 %.

The 27 non-members were **not** drawn at random. I deliberately loaded the sample with the acts
where a false negative would be most damaging — high-rank Sección I acts sitting next to
in-catalogue neighbours on the same day:

| id | day | act | in listing | `/metadatos` |
|---|---|---|---|---|
| `BOE-A-1981-28939` | 1981-12-15 | Real Decreto-ley 19/1981 | no | 404 |
| `BOE-A-2008-19660` | 2008-12-05 | Ley Orgánica 2/2008 (modifica la LOPJ) | no | 404 |
| `BOE-A-2010-19961` | 2010-12-28 | Ley Foral 18/2010 | no | 404 |
| `BOE-A-2010-19962` | 2010-12-28 | Ley Foral 19/2010 | no | 404 |
| `BOE-A-2026-4524` | 2026-02-27 | Ley Foral 1/2026 | no | 404 |
| `BOE-A-2010-19959` | 2010-12-28 | Ley Foral 16/2010 | **yes** | **200** |
| `BOE-A-2010-19960` | 2010-12-28 | Ley Foral 17/2010 | **yes** | **200** |

2010-12-28 is the sharpest case available: four consecutive Leyes Forales de Navarra published
the same day, same department, same rank. The oracle says 16/2010 and 17/2010 are consolidated
and 18/2010 and 19/2010 are not — and the API agrees, id by id. The pattern is not arbitrary:
**16 and 17 create new regimes; 18 and 19 are pure amending acts** ("por la que se modifica la
Ley Foral …"), and an amending act does not become a consolidated norm of its own. Same for
`BOE-A-2008-19660`, a Ley Orgánica that only modifies the LOPJ.

**This is a substantive fact the probe did not state and issue #66 needs:** a large share of the
non-consolidated population is *amending acts whose content already reaches the corpus through
the amended norm's git history*. On my 25 days, 9 of 131 Sección I items are
`Corrección de errores` alone (0 consolidated).

**Attack B also killed my own best alternative hypothesis.** Five "odd" catalogue entries all
returned 200: a regional-gazette id (`BOA-d-2016-90453`), an `estado_consolidacion=4`
(`BOE-A-2017-1373`), a `vigencia_agotada=S` (`BOE-A-2020-3892`), a pre-1979 norm
(`BOE-A-1978-20503`) and one of the 86 catalogue-but-not-in-corpus ids (`BOE-A-1992-23429`).
So the listing does not filter by state, currency or gazette — there is no hidden sub-population
for `/texto` to serve that the listing withholds. The `BOA-d-` 200 also confirms the probe's
point that listing membership ≠ Sección I membership, which is exactly what its 0.892 correction
is for.

---

### 3. Attack C — is the oracle a time-biased snapshot? → **no**

If the BOE consolidates with a lag, a September-2026 snapshot would under-count recent acts and
inflate the "new files" population. Free test on `fecha_publicacion` month counts:

| 2025 | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 | 12 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| | 19 | 18 | 19 | 14 | 15 | 17 | 25 | 11 | 6 | 21 | 15 | 27 |
| **2026** | 17 | 25 | 25 | 23 | 20 | 29 | 21 | 9 | 4 | — | — | — |

2026 tracks 2025's shape month for month (August low both years — holidays; September partial).
No fall-off in the trailing months. No measurable consolidation lag.

---

### 4. My sample (deliberately different from the probe's)

**25 days, 131 Sección I items, 1,868 BOE-A ids of all sections.** Not one of these days appears
in the probe's 128. Chosen to break its grid: it sampled the *same ~9 calendar positions in every
year* (Jan 1/2, Feb 9/10, Mar 21–23, May 1–3, Jun 11–13, Jul 21/22, Aug 31–Sep 1, Oct 11/12,
Nov 21/22) and **never sampled December at all**. Mine is 7/25 December and covers 20 years it
never touched.

`1981-12-15 · 1983-03-10 · 1986-04-09 · 1988-12-06 · 1991-09-25 · 1993-11-26 · 1996-12-14 ·
1998-06-25 · 2001-06-27 · 2003-10-28 · 2006-03-16 · 2008-12-05 · 2010-12-28 · 2012-12-11 ·
2014-07-05 · 2016-10-26 · 2018-04-16 · 2021-06-22 · 2021-12-14 · 2022-09-20 · 2024-05-28 ·
2024-11-19 · 2025-04-15 · 2025-08-19 · 2026-02-27`

Weekday mix Mon 1 / Tue 8 / Wed 5 / Thu 4 / Fri 4 / Sat 3, no Sundays. One day
(**2025-08-19**) had no Sección I at all — 1/25 = 4 %, consistent with the probe's 10/128 = 7.8 %.

**Things of the probe's that my sample reproduces:**

| probe's number | my independent value | verdict |
|---|---|---|
| Sección I share of all BOE-A docs, `r` = **6.88 %** | **7.01 %** (131/1,868), day-bootstrap 95 % CI **[5.64 %, 8.63 %]** | reproduced |
| mean Sección I items/day = **5.01** | **5.24** | reproduced |
| share of consolidated norms sitting in Sección I = **89.2 %** (91/102) | **95.0 %** (19/20: 19 Sec I, 1 Sec III, 0 absent) → **pooled 110/122 = 90.2 %** | reproduced |
| pooled consolidated share of Sección I, 1979–2026 = **14.2 %** | **18.3 %** (24/131) → **pooled 115/772 = 14.9 %** | reproduced |
| section codes carrying general provisions = only `1`; `1A` never appears | confirmed on 25 more summaries: codes seen `1, 2A, 2B, 3, 4, 5, 5A, 5B, 5C, 6A, 6B, 6C, T`; **`1A` 0 times** | reproduced |
| catalogue total 12,385, corpus 12,299, 86 missing | reproduced via a second enumeration axis | reproduced |

---

### 5. What I could **not** reproduce: the per-decade consolidated share (§5 of the probe)

This is the one table that breaks. Three routes to the same quantity, one of them the probe's
**own model**:

| decade | probe (128 d) | **mine (25 d)** | pooled (153 d) | probe's own model-implied¹ |
|---|---:|---:|---:|---:|
| 1970s | 0/56 = 0.0 % | n/a | 0.0 % | 2.6 % |
| 1980s | 4/130 = 3.1 % | 1/32 = **3.1 %** | 3.1 % | 4.2 % |
| 1990s | 4/94 = 4.3 % | 2/22 = **9.1 %** | 5.2 % | 7.1 % |
| 2000s | 6/69 = 8.7 % | 4/13 = **30.8 %** | 12.2 % | 16.3 % |
| 2010s | 24/128 = 18.8 % | 10/29 = **34.5 %** | 21.7 % | 28.6 % |
| **2020s** | 53/164 = **32.3 %** | 7/35 = **20.0 %** | 30.2 % | **19.0 %** |
| pooled | 91/641 = 14.2 % | 24/131 = 18.3 % | **14.9 %** | — |

¹ *model-implied* = `catalogue count for that year × 0.892 ÷ the probe's own Sección I projection
`secI_R1(y)`, aggregated by decade. It uses **no day sample at all** — only the exact catalogue
census and the probe's own per-year table (`final_per_year.json`). It is the probe's model
checked against itself.

Three problems, in order of severity:

**(a) The headline sentence of §5 is contradicted by the probe's own model.** The probe writes
"**two out of three Sección I acts of the 2020s have no consolidated text**" (32.3 % consolidated).
My sample says 20.0 %; the probe's own model says 19.0 %. Both point to **four out of five**, not
two out of three. My 2020s sample is small (35 items, two-proportion z = 1.44, p = 0.15, so I
cannot reject its 32.3 % on my data alone) — but I do not need to: the model-implied route,
which has no sampling error at all, lands on 19.0 % independently.

**(b) The 32.3 % is an artefact of which years got sampled.** The probe's 2020s days are
concentrated on 2020 and 2023, the two highest-consolidation years in the whole period. Its own
per-year sampled shares:

| year | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|
| sampled share | 52.1 % (25/48) | 0 % (0/4)* | 22.2 % (6/27) | 42.9 % (18/42) | 0 % (0/5)* | 3.3 % (1/30) | 17.9 % (5/28) |
| model-implied | 53.0 % | 30.3 % | 21.4 % | 15.4 % | 10.7 % | 9.6 % | 7.7 % |

\* mine. A decade whose annual share runs 53 % → 8 % has no meaningful "decade constant", and
2020 (state of alarm — Sección I was almost entirely Reales Decretos-leyes, all consolidated) is
not a year to average with 2025.

**(c) There is a measured estimator bias, and it is significant.** The probe pools the
intersection **over items**, so large Sección I days dominate. Pooling the probe's 128 days and
my 25:

| day size | consolidated share of its Sección I items |
|---|---:|
| days with ≥ 8 Sección I items (421 items) | **13.5 %** |
| days with 1–3 Sección I items (106 items) | **22.6 %** |

z = 2.32, **p = 0.020**. Big Sección I days are systematically less consolidated (they are the
year-end and month-start `Orden`/`Resolución` blocks). An item-pooled ratio therefore runs low
against a day-weighted or year-weighted one — which is exactly the direction of the gap between
the "sampled" and "model-implied" columns in every decade before 2020.

---

### 6. Why the headline still stands anyway

The disputed §5 table is **decorative** — it does not enter the file-count arithmetic. §7
computes `new files = secI_R1 − catalogue_exact × 0.892`, and I reproduced it exactly from the
probe's own inputs:

| cut | arithmetic | new files |
|---|---|---:|
| 1979–2026 | 80,646 − 11,713 × 0.892 | **70,198** |
| 2000–2026 | 38,744 − 9,058 × 0.892 | **30,664** |
| 2010–2026 | 24,760 − 6,159 × 0.892 | **19,266** |

`frac_cons` appears nowhere in it. Both inputs that *do* appear survived my attack: `secI_R1`
rests on `r`, which I independently reproduced (7.01 % vs 6.88 %, my CI [5.64 %, 8.63 %] contains
its value), and `0.892`, which I independently reproduced (95.0 % on my 20, pooled 90.2 %). The
catalogue census is exact and now verified on a second enumeration axis.

**So: 12,299 → ~82,500 files for the full sweep, ~43,000 for 2000–2026, ~31,600 for 2010–2026
is safe to plan on.** What is not safe to quote is any per-decade consolidated share, and in
particular "two out of three acts of the 2020s".

---

### 7. Numbers I dispute, in one place

| probe's claim | my result | why it differs | safe to decide on |
|---|---|---|---|
| Consolidated share of Sección I, **2020s = 32.3 %** | **20.0 %** (mine), **19.0 %** (its own model) | its 2020s days are concentrated on 2020 and 2023, the two highest-consolidation years; item-pooling adds a further low-side bias on big days | **no** |
| Per-decade shares 2000s 8.7 %, 2010s 18.8 % | 30.8 % and 34.5 % on my days; model-implied 16.3 % and 28.6 % | n = 69 and 128 items on a grid that repeats the same 9 calendar positions every year and never samples December; measured day-size bias p = 0.020 | **no** |
| "two out of three Sección I acts of the 2020s have no consolidated text" | four out of five | follows from the above | **no** |
| Pooled consolidated share 1979–2026 = 14.2 % | 18.3 % mine, **14.9 % pooled** | agrees within sampling error | yes |
| `r` = 6.88 %, mean 5.01 Sección I/day | 7.01 %, 5.24/day | agrees | yes |
| 89.2 % of consolidated norms sit in Sección I | 95.0 % mine, 90.2 % pooled | agrees | yes |
| Catalogue = 12,385; corpus 12,299; 86 missing | reproduced on a second axis | — | yes |
| New files 70,198 / 30,664 / 19,266 → repo 82,497 / 42,963 / 31,565 | reproduced exactly | — | yes |

### 8. What I did not test

* I attacked membership, not volume. `secI_R1` rests on `A(y)`, the per-year BOE-A total, which I
  did not re-derive — I only reproduced the ratio `r` that multiplies it.
* My 2020s cell is 35 items over 8 days. It agrees with the model-implied route but is not on its
  own strong enough to reject 32.3 % (p = 0.15). The case against 32.3 % rests on the model, not
  on my n.
* I probed `/metadatos`, not `/texto`, for the 41 membership tests. The earlier probe showed
  `texto_status == meta_status` on all 28 of its ids, so I spent the budget on sample size
  instead of on confirming that again.

## volume — angle 1: the sample is unrepresentative (December, New Year's Day, weekday mix)

**Verifier:** independent probe, 2026-09-03. **HTTP spent: 100 / 100** (3 catalogue pages +
87 summary calls that returned **HTTP 400 — my own client error**, I omitted the
`Accept: application/xml` header the API requires + 10 December summaries fetched correctly).
No 429, no 5xx. UA `legalize-bot/1.0`, 0.8–0.9 s between calls.
Scratch: `/Users/neli/.claude/jobs/5bf7ddf4/tmp/refute_v1/`
(`catalogue.json`, `december.json`, `http_log.json`, `analysis*.txt`).

**Verdict: PARTIALLY REFUTED — the headline survives, the method description does not, and
the per-year table is not safe to use.**

---

### 1. My sample

| block | what | cost |
|---|---|---:|
| Catalogue census, **different pagination** (`limit=6000`, offsets 0/6000/12000) | independent re-enumeration | 3 req |
| **10 December summaries**, one per year, paired to years the probe already sampled | `19841204` (Tue) · `19891215` (Fri) · `19941210` (Sat) · `19991222` (Wed) · `20041213` (Mon) · `20091217` (Thu) · `20131211` (Wed) · `20171219` (Tue) · `20201211` (Fri) · `20251216` (Tue) | 10 req |
| 87 further summaries (1981/1986/1991/1996/2001/2006/2012/2016/2018/2021/2024, one-day-per-month grids, year-end days, 4 holiday probes) | **lost — all HTTP 400**, missing Accept header | 87 req |

Because the wide grid was lost, the rest of my work is a **re-analysis of the probe's own 128
raw days** (`summaries.json` + `summaries2.json`, which store every section's identifiers) with
my 10 December days folded in → **138 pooled days**. Re-analysing the probe's raw data is not
a weaker test here: the failure I found is in *which days it chose*, and that is visible in its
own file.

---

### 2. What the probe's sampling design actually did — REFUTED as described

The artefact says days were *"evenly spread through each calendar year"* and reports a weekday
balance with *"no weekday over-represented by more than 25 %"*. Neither holds for the 128 days
the estimator actually used.

**Months of the 128 sampled days:**

| month | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 | **12** |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| days sampled | 13 | 16 | 12 | **1** | 16 | 13 | 12 | 8 | 9 | 12 | 16 | **0** |

**December is not in the sample at all, and April has one day.** The cause is the picking rule
itself: `days[⌊i·len/n⌋]` for `i = 0…n-1` stops at 8/9 (or 3/4) of the year — about 21 November —
so the last ~11 % of every calendar year is unreachable by construction. It is not bad luck.

**New Year's Day is in the sample every single year.** `i = 0` always selects 1 January
(or 2 January when the 1st is a Sunday):

| | count | share of sample | real share of publication days |
|---|--:|--:|--:|
| 1–2 January days | **12** of 128 | **9.4 %** | **0.64 %** |

A **14.6× over-representation of the emptiest days of the year** — they average **2.33**
Sección I acts against **5.28** for every other sampled day.

**Weekday mix** over all 128 days (the artefact's figures are for Pass A's 108 days only):
Mon 25 · Tue 16 · Wed 29 · Thu 18 · Fri 23 · Sat 17 → Wed **22.7 %** (+36 % over uniform),
Tue 12.5 % (−25 %), Sat 13.3 % (−20 %). And the weekday effect is real: Monday indexes **0.58**
against the mean, Friday **1.17**.

---

### 3. So how much did it cost? — measured, and the answer is "almost nothing"

This was the point of my December buy. **Seasonal index, pooled 138 days, Jan 1–2 removed
(grand mean 5.29 Sección I acts/day):**

| month | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 | **12 (mine)** |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| n | 1 | 16 | 12 | 1 | 16 | 13 | 12 | 8 | 9 | 12 | 16 | **10** |
| secI/day | 2.00 | 6.50 | 6.00 | 11.00 | 4.44 | 5.92 | 7.17 | 3.38 | 2.00 | 3.83 | 6.19 | **5.30** |
| index | 0.38 | 1.23 | 1.14 | 2.08 | 0.84 | 1.12 | 1.36 | 0.64 | 0.38 | 0.73 | 1.17 | **1.00** |

**December indexes at 1.00 — dead average.** Paired within year against the probe's own days
for the same 10 years, December is **1.079×** the year's sampled mean (5.30 vs 4.91), and its
pooled Sección-I ratio is **0.0718** against the probe's 0.0688. The "December is a heavy
legislative month" hypothesis is **false for Sección I** — December is heavy in *pages*, not in
*disposiciones generales*. June likewise indexes 1.12, and it was sampled 13 times.

Per-day December detail (my raw measurement):

| date | wd | Sección I | BOE-A that day | same-year probe mean secI/day |
|---|---|--:|--:|--:|
| 1984-12-04 | Tue | 10 | 53 | 9.67 |
| 1989-12-15 | Fri | 2 | 125 | 4.78 |
| 1994-12-10 | Sat | 3 | 57 | 5.11 |
| 1999-12-22 | Wed | 7 | 94 | 5.33 |
| 2004-12-13 | Mon | 1 | 38 | 4.11 |
| 2009-12-17 | Thu | 2 | 80 | 3.56 |
| 2013-12-11 | Wed | 6 | 29 | 5.22 |
| 2017-12-19 | Tue | 4 | 70 | 2.67 |
| 2020-12-11 | Fri | 2 | 72 | 5.33 |
| 2025-12-16 | Tue | 16 | 120 | 3.33 |

---

### 4. Four estimators, my weighting vs the probe's — the headline holds

I rebuilt the projection from scratch on the 138 pooled days with three corrections the probe
did not make (Jan 1–2 pulled into their own stratum with their true 2/313 weight; December
present; quarter post-stratification with real publication-day weights), plus a fourth
estimator that drops the proportionality assumption entirely.

| cut | probe **R1** | **V0** Jan-fix day-mean | **V1** quarter post-strat | **R4** elasticity-corrected | spread |
|---|--:|--:|--:|--:|--:|
| 1979–2026 | 80,644 | **79,073** | **79,627** | **80,569** | **±1.0 %** |
| 2000–2026 | 38,743 | **37,648** | **37,882** | **40,173** | **±3.3 %** |
| 2010–2026 | 24,760 | **25,693** | **25,649** | **24,330** | **±2.8 %** |

*R4* fits the measured day-level relation `secI = 0.0490·BOE-A + 1.46` (OLS, n = 138) and
applies it as `secI(y) = 0.0490·A(y) + 1.46·pubdays(y)`, so it makes no proportionality
assumption at all. My own 4,000-resample within-era day bootstrap on V0 gives
**1979–2026 [67,300 – 92,200] · 2000–2026 [31,200 – 44,600] · 2010–2026 [21,300 – 30,400]**,
i.e. the same planning range the probe quoted.

**I could not break the headline.** A deliberately different weighting scheme, plus the month
the probe never touched, moves the full-sweep total by **−2 %**.

One negative result worth recording so nobody repeats it: my first attempt post-stratified by
IPF raking on quarter × weekday (24 cells against 20–37 days per era) and produced **87,646**
(+9 %). That is over-fitting, not signal — the 1990s era mean jumped 5.78 → 8.08 on 18 ordinary
days. **Discard it.** The quarter-only post-stratification above is the stable version.

---

### 5. What the design flaw *did* damage: the "lower shoulder"

The probe reported R2 (plain day-mean × publication days) = **75,704** as the low end and read
the 7 % R1–R2 gap as estimator uncertainty. It is not — it is almost entirely the New Year
artefact. The raw sample mean is 5.01 acts/day; with the 12 Jan 1–2 days carried at their true
weight it is **5.29** (+5.6 %). R1 was insulated because those days shrink numerator and
denominator together; R2 was not.

Corrected, the three routes agree to **2 %**, not 7 %. The probe's conclusion is *more* solid
than it claimed, for a reason it did not know.

---

### 6. What I do refute: the per-year table

R1 is `A(y) × r_era` — it *assumes* Sección I is proportional to the day's total BOE-A volume.
Measured on the 138 pooled days that assumption is wrong:

* `corr(Sección I, BOE-A) per day` = **0.424**; OLS intercept **+1.46**, not 0.
* **Elasticity at the mean = 0.71**, not 1.00. A day 2.5× larger carries only 1.87× the
  Sección I acts.
* Across the 17 sampled years, `corr(A(y), Sección I per day)` = **0.362**. R1 imposes
  correlation 1.0 within an era.

Consequence for the numbers people will quote out of the table:

| year | A(y) | probe R1 | R4 (elasticity-corrected) | Δ |
|---|--:|--:|--:|--:|
| 1986 | 33,874 | 2,497 | 2,117 | **−15 %** |
| 2013 | 13,837 | 1,104 | 1,135 | +3 % |
| 2016 | 12,605 | 1,005 | 1,076 | +7 % |
| 2020 | 17,418 | 1,170 | 1,312 | +12 % |
| 2024 | 27,502 | 1,847 | 1,806 | −2 % |
| 2026 | 28,801 | 1,934 | 1,868 | −3 % |

**Use the cut totals. Do not use the per-year column to size a per-year backfill batch** —
it inherits a volume signal (Sección IV/V edictos and anuncios, which is what actually drives
`A(y)` from 13,837 in 2013 to 28,801 in 2026) that Sección I does not follow.

---

### 7. Numbers I reproduced exactly

Independently re-enumerated with a different page size (`limit=6000`, 3 pages) and an
independent filesystem census of `countries/es`:

| claim | probe | mine | |
|---|--:|--:|:--|
| consolidated catalogue total (unique ids) | 12,385 | **12,385** | ✅ |
| ambito Estatal / Autonómico | 8,767 / 3,618 | **8,767 / 3,618** | ✅ |
| catalogue ids missing from the corpus | 86 | **86** | ✅ |
| corpus ids absent from the catalogue | 0 | **0** | ✅ |
| corpus `.md` files | 12,299 | **12,299** (0 duplicate basenames) | ✅ |
| consolidated with `fecha_publicacion` 1979–2026 | 11,713 | **11,958 − 245 regional-gazette ids = 11,713** | ✅ |
| pooled Sección-I share of BOE-A | 6.88 % | **6.88 %** (641/9,311, recomputed from raw) | ✅ |
| era table (days / secI / BOE-A / r / R1 / R2) | — | **reproduced to the last digit** | ✅ |
| consolidated share of Sección I, pooled | 14.2 % (91/641) | **14.2 %**; **13.8 %** (96/694) with my December days | ✅ |
| …by decade | 3.1 / 4.3 / 8.7 / 18.8 / 32.3 % | **2.8 / 4.8 / 9.7 / 18.1 / 30.2 %** | ✅ within noise |

---

### 8. Still untested — and one of them matters

1. **`publication days = 365 − Sundays` (313/yr)** is assumed by R2, V0, V1 and R4, and was
   never verified by either of us. My four holiday probes (2024-12-25, 2016-08-15, 2012-11-01,
   2021-04-02) died with the 400s. If the BOE skips any non-Sunday day, **every day-mean
   estimator is inflated proportionally** — 3 skipped days/year would be −1 %. R1 does not
   depend on it. **Cheap to settle: 4 requests.**
2. **`A(2026) = 28,801`**, annualised from one August day; carries ~2.4 % of the 48-year total.
3. **The 0.892 constant** (share of consolidated norms arriving via Sección I). My 10 December
   days yielded only n = 5 catalogue norms published on them, **5/5 in Sección I** — consistent
   with 89.2 %, far too few to test it.
4. **Rank mix of the ~70,000 non-consolidated acts** — still unmeasured by anyone, and it is
   the number that decides whether this is a 70,000-file addition or a 20,000-file one.

---

### 9. Bottom line for the decision

**The volume headline is safe.** ~80,000 Sección I acts 1979–2026, ~14 % consolidated,
~70,000 new files → **~82,000 files** for the full sweep, **~43,000** for 2000–2026,
**~31,500** for 2010–2026. Four estimators built on two different weighting schemes and two
different data pulls land within ±4 % of each other, and the month nobody had sampled turned
out to be exactly average.

**The per-year table is not safe** and should be dropped from the plan, and **the sampling
design should not be reused as described** for probes 2–8 — the picking rule
`days[⌊i·len/n⌋]` silently deletes December and pins 1 January into every stratum.

## volume — angle 3: exact year counts from the year-end summary and the diario numbering

**Verifier:** angle 3 of 3 · **Date:** 2026-09-03 · **HTTP requests spent: 94** (budget 100).
One request was wasted on a 404 (I used `https://www.boe.es/api/...`; the API lives under
`https://www.boe.es/datosabiertos/api/...`). All 93 remaining requests returned 200. No 429,
no 5xx. UA `legalize-bot/1.0`, 0.8 s between requests.
**Scratch:** `/Users/neli/.claude/jobs/5bf7ddf4/tmp/refute_v3/` (`cat.json`,
`yearend_mine.json`, `days_mine.json`, `final_mine.json`).

### Verdict: **CONFIRMED**, with three numbers I could not reproduce

I ignored the probe's method. I did not resample its 128 days, I did not reuse its ratio, and
I did not use the estimator it calibrated. Instead I bought the year counts **exactly**, from
the source it only extrapolated from, and re-measured the ratio on **10 years it never
touched**. Its three headline projections survive:

| cut | probe | **my independent projection** | Δ |
|---|---:|---:|---:|
| Sección I acts 1979–2026 | 80,646 | **79,230** | −1.8 % |
| Sección I acts 2000–2026 | 38,744 | **36,521** | −5.7 % |
| Sección I acts 2010–2026 | 24,760 | **26,372** | +6.5 % |

Pooling both day samples (179 days) on exact year counts gives 79,260 / 36,978 / 24,531 —
within 2 % of the probe on the all-time and 2010 cuts. **The "12,299 → ~82,000 files, not
120,000" conclusion holds.**

---

### 1. My sample (deliberately disjoint from the probe's)

**Catalogue census — different pagination.** `GET /datosabiertos/api/legislacion-consolidada?limit=5000&offset={0,5000,10000}`,
`Accept: application/json` → pages of 5,000 / 5,000 / **2,385**. The probe used `limit=10000`
in 2 pages. Same answer: **12,385 unique `identificador`**, 245 of them without a `BOE-A-`
prefix, 427 published before 1979. A different page size does not silently truncate the
catalogue. **3 requests.**

**Year-end summaries — the route the probe extrapolated.** The last publication day of a year
is 31 December, or 30 December when 31 December is a Sunday (verified: the rule reproduces the
probe's own 1989/2017/2023 dates). I fetched the year-end of **the 36 years the probe did not
measure** — 1980-83, 1985-88, 1990-93, 1995-98, 2000-03, 2005-08, 2010-12, 2014-16, 2018-19,
2021-22, 2024 — plus **1994 and 2020 as controls**, plus **2026-09-02** for the running year.
**38 requests.**

**Day sample — 10 years the probe never sampled**, at a phase-shifted calendar grid
(fractions 0.10/0.30/0.50/0.70/0.90 of each year's non-Sunday days, versus the probe's
`i·len/9` grid):

| year | sampled days |
|---|---|
| 1981 | 02-06, 04-20, 07-02, 09-14, 11-25 |
| 1986 | 02-06, 04-19, 07-02, 09-13, 11-25 |
| 1991 | 02-06, 04-19, 07-02, 09-13, 11-25 |
| 1996 | 02-06, 04-19, 07-02, 09-12, 11-25 |
| 2001 | 02-06, 04-19, 07-02, 09-13, 11-24 |
| 2006 | 02-07, 04-20, 07-03, 09-13, 11-24 |
| 2012 | 02-07, 04-19, 07-02, 09-13, 11-24 |
| 2016 | 02-06, 04-20, 07-02, **07-04**, 09-13, 11-25 |
| 2021 | 02-06, 04-20, 07-02, 09-14, 11-25 |
| 2024 | 02-06, 04-19, 07-02, 09-12, 11-25 |

**51 requests.** 2016-07-04 is deliberately the next publication day after 2016-07-02, to test
id contiguity across a day boundary. **Zero overlap with the probe's 128 days or its 12
year-ends.**

---

### 2. The probe's biggest extrapolation — `A(y)` for 36 years — holds

The probe measured `A(y)` (BOE-A documents in year `y`) exactly for 12 years and estimated the
other 36 with a catalogue-anchored estimator it claimed was accurate to 0.22 % MAE. I measured
those 36 directly. **Its estimator is real.**

| | value |
|---|---|
| Controls: 1994 | mine **29,041** — probe 29,041 · **exact match** |
| Controls: 2020 | mine **17,418** — probe 17,418 · **exact match** |
| MAE of the probe's estimator over 35 held-out years | **0.274 %** (it claimed 0.22 % in-sample) |
| worst single year | 2011, −0.99 % |
| Σ A(y) over the 36 years, exact | **946,524** |
| Σ A(y) over the same 36, probe-estimated | 954,802 (**+0.87 %**) |

Exact `A(y)`, measured (max BOE-A id below 40,000 on the year's last publication day):

| yr | A | yr | A | yr | A | yr | A |
|---|---:|---|---:|---|---:|---|---:|
| 1980 | 28,046 | 1991 | 31,011 | 2002 | 25,442 | 2015 | 14,368 |
| 1981 | 30,298 | 1992 | 28,962 | 2003 | 23,970 | 2016 | **12,640** |
| 1982 | **35,046** | 1993 | 31,288 | 2005 | 21,676 | 2018 | 18,152 |
| 1983 | 34,406 | 1995 | 28,016 | 2006 | 23,035 | 2019 | 18,782 |
| 1985 | 27,035 | 1996 | 29,180 | 2007 | 22,574 | 2021 | 21,969 |
| 1986 | 33,933 | 1997 | 28,095 | 2008 | 21,053 | 2022 | 24,664 |
| 1987 | 28,831 | 1998 | 30,264 | 2010 | 20,188 | 2024 | 27,623 |
| 1988 | 29,735 | 2000 | 24,482 | 2011 | 20,867 | 2026 | 18,508 *(to 02-09)* |
| 1990 | 31,368 | 2001 | 25,017 | 2012 | 15,822 | | |
| | | | | 2014 | 13,719 | | |

Minor corrections to the probe's stated range: the extremes are **12,640 (2016)** and
**35,046 (1982)**, not 12,605 and 34,845.

**The structural claim the whole method rests on also holds, and I tested it harder than the
probe did.** 2016-07-02 ends at `BOE-A-2016-6433`; 2016-07-04 starts at `BOE-A-2016-6434` —
**gap exactly 1 across the day boundary**, which the probe never checked. 50 of my 51 days
carry a perfectly contiguous BOE-A block.

**The one exception is a measured caveat on `A(y)`, in both our work.** On 1986-07-02 the
day's block is 17428–17589, but the summary also carries `BOE-A-1986-34046` (Sección II-B) and
`BOE-A-1986-49964` (Sección I). 34,046 is **above** `A(1986) = 33,933` taken from the
year-end. So `max(id on last day)` is a **lower bound**, not an exact count — short by ~0.3 %
in at least that year. And the `id < 40000` filter both of us apply silently drops a genuine
Sección I item (49964), 1 of my 263 (0.4 %).

---

### 3. The Sección I ratio, re-measured on 51 disjoint days

| era | days | Sec I | all BOE-A | **r mine** | r probe | ratio | acts/day mine | acts/day probe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1979–1989 | 10 | 81 | 1,180 | 0.0686 | 0.0737 | 0.93 | 8.10 | 6.89 |
| 1990–1999 | 10 | 59 | 881 | 0.0670 | 0.0585 | 1.14 | 5.90 | 5.22 |
| 2000–2009 | 10 | 34 | 772 | 0.0440 | 0.0608 | 0.72 | 3.40 | 3.83 |
| 2010–2019 | 11 | 47 | 436 | 0.1078 | 0.0798 | 1.35 | 4.27 | 4.27 |
| 2020–2026 | 10 | 42 | 796 | 0.0528 | 0.0672 | 0.79 | 4.20 | 4.69 |
| **pooled** | **51** | **263** | **4,065** | **0.0647** | 0.0688 | 0.94 | **5.16** | 5.01 |

Bootstrap 95 % CI on my `r` (20,000 day-resamples within each era) — **the probe's value falls
inside every one**:

| era | my 95 % CI | probe r | |
|---|---|---:|---|
| 1979–1989 | 0.0471 – 0.0968 | 0.0737 | INSIDE |
| 1990–1999 | 0.0432 – 0.0993 | 0.0585 | INSIDE |
| 2000–2009 | 0.0248 – 0.0651 | 0.0608 | INSIDE |
| 2010–2019 | 0.0746 – 0.1468 | 0.0798 | INSIDE |
| 2020–2026 | 0.0311 – 0.0810 | 0.0672 | INSIDE |

My pooled ratio is 6 % below the probe's and my acts/day 3 % above it. Neither sample can tell
the eras apart: my per-era `r` swings 0.044 → 0.108 on 10 days each. **The probe's claim that
`r` is "remarkably stable across eras" is not something either sample can support — it is a
statement the data is too thin to make. It happens not to matter, because the pooled ratio is
what drives the total and the two pooled ratios agree.**

---

### 4. The projection, rebuilt from the other end

`Sección I(y) = A(y) × r(era)`, summed. Every row below uses **exact** `A(y)` for all 48 years
except where marked.

| basis | 1979–2026 | 2000–2026 | 2010–2026 |
|---|---:|---:|---:|
| probe as published (its `A`, its days, `A(2026)=28,801`) | 80,646 | 38,744 | 24,760 |
| its days + **exact `A`**, `A(2026)=28,801` | 80,783 | 38,829 | 24,819 |
| its days + exact `A`, **`A(2026)` = 18,508 actual** | 80,092 | 38,138 | 24,128 |
| **my 51 days + exact `A`, actual 2026** | **79,230** | **36,521** | **26,372** |
| pooled 179 days + exact `A`, actual 2026 | 79,260 | 36,978 | 24,531 |
| pooled-basis 95 % CI | 70,239 – 89,577 | 31,412 – 43,399 | 20,853 – 28,647 |

Repo impact, my basis (new files = Sección I acts − catalogue count for the period × 0.892):

| cut | Sec I | consolidated via Sec I | **new files** | repo total | × today |
|---|---:|---:|---:|---:|---:|
| 1979–2026 | 79,230 | 10,667 | **68,563** | **80,862** | 6.6× |
| 2000–2026 | 36,521 | 8,285 | **28,236** | **40,535** | 3.3× |
| 2010–2026 | 26,372 | 5,651 | **20,721** | **33,020** | 2.7× |

Against the probe's 82,497 / 42,963 / 31,565. **Same decision in every cut.**

---

### 5. What I could NOT reproduce

**5.1 `A(2026) = 28,801`. Measured: 18,508.** The probe annualised one August day to a full
2026. The BOE had published exactly **18,508 BOE-A documents** by 2026-09-02 (`BOE-A-2026-18508`,
diario 217). A corpus can only hold what exists, so the year-to-date figure is the one that
belongs in a file-count projection. Its own annualisation is also 7.5 % high: 18,508 × 314/217
≈ 26,780, not 28,801. **Effect: −691 Sección I acts in every cut (−0.9 % all-time, −2.8 % on
the 2010 cut). Small, but the number as printed is wrong.**

**5.2 The consolidated-share trend "3.1 % → 32.3 %".** Its headline story is a monotone rise in
the share of Sección I acts that get consolidated. My sample does not show one:

| decade | probe | **mine** | my n |
|---|---:|---:|---|
| 1980s | 3.1 % | 3.7 % | 3 / 81 |
| 1990s | 4.3 % | **10.2 %** | 6 / 59 |
| 2000s | 8.7 % | **20.6 %** | 7 / 34 |
| 2010s | 18.8 % | 14.9 % | 7 / 47 |
| 2020s | **32.3 %** | **19.0 %** | 8 / 42 |
| pooled | 14.2 % | 11.8 % | 31 / 263 |

The 2020s gap is the one that matters and it is the one with most data on both sides: 53/164 vs
8/42, two-proportion z = 1.68, p ≈ 0.09 — **directional, not significant**. My curve rises to
the 2000s and then flattens. **Neither shape is established.** Its sentence "two out of three
Sección I acts of the 2020s have no consolidated text" reads as four out of five on my sample.
**This does not propagate to the file counts**: new files are `Sección I − consolidated`, and
`consolidated` is an exact catalogue count, never derived from this share. Treat the trend as
colour, not as a planning input.

**5.3 "consolidated (exact) = 11,713 / 9,058 / 6,159".** Counting `fecha_publicacion` year over
the same 12,385 rows I get **11,958 / 9,288 / 6,335** — higher by exactly 245 / 230 / 176. The
245 is its count of non-`BOE-A` (regional-gazette) ids, so it silently subtracted them. That is
the right call, but the artefact does not say so; anyone recomputing from the catalogue gets a
different number. Worth ~220 files (0.3 %).

---

### 6. Free corrections from the diario numbering (my angle's other lever)

`diario/@numero` on the last publication day is the **exact** number of BOE issues that year.

| years | issues |
|---|---|
| 1980–2008 | 312–315 (median 313) |
| 2010–2024 | 313–318 (median 315) |
| **2020** | **341** — 28 extra COVID emergency issues |

Its estimator R2 assumed "publication days = calendar days minus Sundays, 312–314/year". That is
**1 % low for 2010 onward and 8 % low for 2020**. R2 is only its lower shoulder, so nothing
moves — but the exact figure is now on record and is one request per year.

Also measured: 2026-09-02 carries **two** diarios (216 and 217), so *issues* and *publication
days* are not the same quantity in the modern BOE.

And a design note for anyone re-running this: **the year-end day is a terrible day to sample
for Sección I**, by a factor I measured on 38 of them — 31 December carries **2.3× to 4.7×** the
ordinary-day Sección I count (18.9 vs 8.10 in the 1980s; 16.1 vs 3.40 in the 2000s; the bias
collapses to 1.3× in the 2020s). Both the probe and I correctly kept year-end days out of the
ratio sample; the numbers above are why that matters.

---

### 7. Limits of this refutation

* My ratio rests on **51 days / 263 Sección I acts**, less than half the probe's 641. My CIs are
  correspondingly wider; I can bound its number, I cannot beat it. The *pooled* 179-day figure
  is the best number either of us has.
* `A(y)` is exact for all 48 years now, but §2 shows it is a lower bound of order 0.3 %.
* I stored identifiers only, not titles — like the probe, I have measured **acts, not laws**,
  and the rank mix of the non-consolidated population is still unmeasured by anyone.
* I did not re-verify the 0.892 "consolidated norms that sit in Sección I" constant; my sample
  reuses it from the probe. If it is wrong, every "new files" row above moves with it.

---

## taxonomy — angle 2: the drop rule keeps two non-norms, and the residue is a floor

**Verifier:** independent probe, 2026-09-03. **HTTP requests spent: 86 of 100.**
Scratch, caches and scripts: `/Users/neli/.claude/jobs/5bf7ddf4/tmp/refute2/`.

**Verdict: PARTIALLY REFUTED.**

- The headline **"`rango` cleanly removes every non-norm — 12/12 with zero false drops"**
  is **refuted on the keep side**: my sample contains two Sección I acts that are not norms
  and that the recommended rule `rango ∉ {1590, 1240, 63}` **emits as law files** —
  one of them a *corrección de errores*, the exact case the probe declared the brief was
  wrong to worry about.
- The **drop side survives, and survives more strongly than the probe proved it**: 0 of
  12,385 consolidated catalogue entries carry any of those rank codes.
- **The 27.0 % undecidable residue is CONFIRMED** — I attacked it with six fields the probe
  never tested and none of them decides it — but **27 % is a floor, not the number**: a
  whole recurring class of administrative act (periodic price and tariff publications) sits
  inside the "keep" side and was absent from the probe's 63-act census.
- **88.4 % non-consolidated and 4.00 items/gazette-day are not reproducible.** I measure
  **73.0 %** and **8.71/day** on a different 14 days. Both probes are day-selection-biased
  in opposite directions.

---

### 1. My sample — deliberately disjoint from both earlier probes

Probe 1 sampled January days; Probe 2 sampled June/September/October days. I sampled
**February, March, April, May, July, November and December**, deliberately including the
end-of-year days the probe named as its seasonal blind spot.

| Instrument | What | Sample |
|---|---|---|
| Gazette days | `GET /api/boe/sumario/{YYYYMMDD}` | **14 days**: 1986-12-31, 1991-02-14, 1996-04-25, 2000-12-30, 2004-07-20, 2007-11-16, 2011-12-31, 2015-05-13, 2018-07-24, 2020-03-14, 2022-04-06, 2023-11-28, 2025-12-31, 2026-05-19 — **no day shared with either earlier probe** |
| Sección I population | every `<item>` under `<seccion codigo="1">` | **122 items** |
| Membership oracle | `<estado_consolidacion>` on the document itself (see §5), cross-checked against the probe's cached catalogue | 122 items / 71 documents |
| Adversarial census | `xml.php?id=` for every item matching a non-norm title pattern | **38 ids** (correcciones, TC procedural acts, price lists, subsidies, "se publica", convalidación) |
| Unbiased census | `xml.php?id=` for **every** Sección I item of 2000-12-30 and 2011-12-31 | **45 ids**, of which 35 non-consolidated |
| Reform hunt | 3 extra sumarios to locate `BOE-A-2026-10881` | 1 fetched (hit on the first) |
| Re-analysis of the probe's own bytes | its 88 cached diary XML, re-parsed for fields it never reported | 0 requests |

**71 documents fetched, all HTTP 200. No 429, no 5xx.** One request per 0.5–1.0 s,
`User-Agent: legalize-bot/1.0 (+https://github.com/legalize-dev/legalize)`, persistent
on-disk counter at `refute2/r2_request_count.json`.

---

### 2. Acts the rule INCLUDES that are not norms

#### 2.1 `BOE-A-2011-20653` — a *corrección de errores* that is not `rango 1590`

> **Resolución de 28 de diciembre de 2011, de la Comisión Nacional del Mercado de Valores,
> de corrección de errores de la Circular 5/2011, de 12 de diciembre, por la que se
> modifica la Circular 12/2008…**

| Field | Value |
|---|---|
| `rango` | **`1370` Resolución** — *not* 1590 |
| `seccion` | `1` |
| `url_eli` | `https://www.boe.es/eli/es/res/2011/12/28/(3)` — **present** |
| `estatus_legislativo` / `origen_legislativo` | `L` / Estatal |
| `estado_consolidacion` | `0`, empty — not consolidated |
| `<anteriores><palabra>` | **`CORRIGE errores`** |
| chars | 6,560 |

The probe's §3.3 states: *"On this sample there are none… all 5 carry `rango codigo="1590"`
… Title-prefix matching on `"corrección de err"` selects exactly the same 5. The rank field
is sufficient and is the better key."* Both halves fail here. The rank is 1370, so
**step 3 of the recommended rule emits this errata as a law file**; and the title *starts*
`Resolución de 28 de diciembre de 2011…`, so the prefix fallback misses it too.

Rate on my sample: **1 of 12 correcciones (8.3 %)** carries a rank other than 1590.
The other 11 do carry 1590 — the probe's finding is right about the common case and wrong
about "sufficient".

#### 2.2 `BOE-A-2004-13466` — `rango 1250 Auto`, a rank code neither probe saw

> **Recurso de inconstitucionalidad núm. 1021-2004, promovido por el Presidente del
> Gobierno contra determinados preceptos de la Ley del Principado de Asturias 6/2003, de
> 30 de diciembre, de Medidas Presupuestarias, Administrativas y Fiscales.**

| Field | Value |
|---|---|
| `rango` | **`1250` Auto** — not in the drop set `{1590, 1240, 63}` |
| `departamento` | Tribunal Constitucional (`codigo 1410`) |
| `seccion` | `1` — it *is* in "I. Disposiciones generales" |
| `url_eli` | **absent** |
| `estatus_legislativo` | `L` |
| chars | 750 |

This is a pure procedural notice — the TC announcing that a challenge has been admitted and
the challenged articles suspended. It has no normative content. **The recommended rule keeps
it**, and would emit a 750-character law file. The probe's own §3.4 asserts the drop set is
complete because *"`departamento ∈ {Tribunal Constitucional, Tribunal Supremo}` selects the
same 8 of those 12 and nothing else"*; here the departamento test would have caught it and
the rank test does not — the opposite of the probe's ordering, which uses rango as the key
and departamento only "as an assertion".

#### 2.3 The class the 63-act census missed entirely: periodic price and tariff publications

Four in my fetched set, all `rango 1370`, all Sección I, all non-consolidated, all carrying a
`url_eli`, **all kept by the rule**:

| id | Title (truncated) | chars |
|---|---|---:|
| `BOE-A-2000-24371` | Resolución del Comisionado para el Mercado de Tabacos … por la que se **publican los precios de venta al público** de determinadas labores de tabaco | 4,190 |
| `BOE-A-2000-24372` | Resolución de la DG de Política Energética y Minas … por la que **se hacen públicos los nuevos precios máximos** de gases licuados del petróleo | 3,653 |
| `BOE-A-2011-20649` | Resolución de la DG de Política Energética y Minas … por la que **se publica la tarifa de último recurso** de gas natural | 10,565 |
| `BOE-A-2020-3637` | Resolución de la Presidencia del Comisionado para el Mercado de Tabacos … por la que **se publican los precios** | 5,120 |

These are published on a weekly-to-monthly cadence for decades. Their weight in a
1979–2026 backlog is far larger than 4/71 suggests, and **no field distinguishes them from
`BOE-A-2011-20646` (Orden IET/3586/2011, peajes de acceso — a genuine tariff *regulation*,
121,546 chars, same section, adjacent id)**. They belong in the probe's residue, and they
are not in its 17-member enumeration. This is why 27.0 % is a floor.

---

### 3. Acts the rule EXCLUDES — the drop side survives, and better than proved

I tested the drop set against a population 200× the probe's census, at zero HTTP cost:

> **0 of the 12,385 entries in the consolidated catalogue carry `rango` 1590, 1240, 63 or
> 1250.** The BOE never consolidates a corrección, a sentencia, a providencia or an auto.
> Method: `Counter(rcod)` over the probe's cached catalogue; the full distribution is 19
> codes, listed in `refute2/`.

Cross-checked against the published corpus: **0 of those ids appear among the 12,300 `.md`
basenames in `countries/es`**. So dropping `{1590, 1240, 63}` cannot remove anything the
corpus holds today or anything the BOE itself treats as a norm. **I found no false drop.**
The probe's claim is correct; its evidence (12 acts) was much weaker than the claim deserved.

One adjacent gap: `1250 Auto` must be **added** to the drop set, and `1220 Reglamento`
(2 catalogue entries) is missing from `engine/src/legalize/fetcher/es/metadata.py::_RANK_CODE_MAP`
— the text map catches it, so it is latent, not live.

---

### 4. The opposite claim: is the residue decidable from a field the probe overlooked?

**For correcciones: yes.** For the singular/administrative residue: **no.**

#### 4.1 The overlooked field that *does* work — `<anteriores><palabra>`

The probe used the `<analisis><referencias><anteriores><anterior><palabra>` relation
vocabulary to hand-classify and then explicitly rejected it in favour of `rango`. It is
strictly better for the one class it covers:

| Key | Catches, of my 12 correcciones |
|---|---:|
| `rango == 1590` | 11 / 12 |
| title starts `"corrección de err"` | 11 / 12 |
| **`palabra` matches `CORRECCIÓN de …` or `CORRIGE …`** | **12 / 12** |

Observed vocabulary on my 71 documents: `CORRECCIÓN de errores` ×9, `CORRECCIÓN de erratas`
×2, `CORRIGE errores` ×2 (`BOE-A-1996-9196` carries both). `BOE-A-2011-20653` is caught only
by this key. It is on the document the sweep already fetches, so it costs nothing.

#### 4.2 The six fields that do **not** decide the residue

Tested on my 71 documents **and** re-parsed from the probe's own 88 cached documents — none
of these appears in its §2.3 "fields that look decisive and are not" table, so none was ruled
out there:

| Field | Result on the residue | Verdict |
|---|---|---|
| `url_eli` | present on **17 / 17** of the probe's residue members; absent on 11 of its 88 docs — 5 sentencias, 3 providencias, 2 correcciones, 1 PDF-only treaty annex | catches non-norms (incl. the `1250 Auto`), decides nothing about the residue |
| `vigencia_agotada` | `S` on only **2 / 17** residue members; `S` on 16 of my 35 census non-consolidated including the salario-mínimo RD and *Ley 12/1998 contra la Exclusión Social* | flags **temporary norms**, not singular acts |
| `estatus_derogacion` | `S` on 11 of the probe's 88 and 1 residue member | later repeal, unrelated |
| `judicialmente_anulada` | `S` on 1 of 88 | too rare |
| `estatus_legislativo` | `L` on **35 / 35** of my census | constant |
| `subseccion` | **empty on 88 / 88** of the probe's docs | the probe lists it as "present 63/63"; the *element* is present, the *value* never is |

**The residue is real.** A second independent attempt to dissolve it with fields the first
probe did not test found nothing. The probe's §3.6 conclusion — that it is a policy call —
is CONFIRMED, and its "keep it" recommendation stands on the merits, but the price of
keeping it is higher than 27 % because of §2.3.

---

### 5. The catalogue oracle is unnecessary — the answer is on the document

`<metadatos><estado_consolidacion codigo="…">` is present on **every** diary XML and answers
membership directly:

| | in catalogue | not in catalogue |
|---|---:|---:|
| `estado_consolidacion codigo="3"` Finalizado | 12 (mine) + 12 (probe's) | 0 |
| `estado_consolidacion codigo="0"`, empty text | 0 | 59 (mine) + 76 (probe's) |

**159 / 159 agreement**, no disagreement. Step 2 of the recommended rule ("is it in the
consolidated catalogue") is one attribute on a document the sweep is fetching anyway. The
probe fetched all 88 of those documents and never reported the field.

---

### 6. Numbers I could not reproduce

| Probe's claim | My measurement | Why they differ |
|---|---|---|
| **88.4 %** of Sección I non-consolidated (99/112, 28 days) | **73.0 %** (89/122, 14 days) — range **33.3 % – 100 %** across my days | Day selection. Both are honest samples of a quantity that swings by day. Pooled: **188 / 234 = 80.3 %** over 42 non-overlapping days |
| **4.00** Sección I items per gazette day | **8.71/day** (122/14) — range **3 – 26** per day | The probe avoided December; I aimed at it. `2011-12-31` alone has 26 items, `2023-11-28` has 3. Pooled: **234 / 42 = 5.57/day** |
| **~42,000** ingestable backlog (`~25,000–45,000`) | scales linearly on the item-rate above → **~36,000–90,000** on my rate | The extrapolation's base is the disputed 4.00/day. Neither probe's day set is a random sample of gazette days; a real answer needs a systematic sweep, not more hand-picked days |
| *"the rank field is sufficient"* for correcciones | **11 / 12**, not 12 / 12 | §2.1 |
| drop set `{1590, 1240, 63}` is complete | **incomplete** — `1250 Auto` | §2.2 |

#### Not disputed — reproduced or confirmed

- **`rango 1676` → `Rank.CONSTITUCION`.** Traced in source and **confirmed exactly**.
  `_parse_rank` (`metadata.py:127`) misses `1676` in `_RANK_CODE_MAP` and `"reforma"` in
  `_RANK_TEXT_MAP`; `read_metadata` (`metadata.py:281`) then calls `_infer_rank_from_title`
  whose first branch is `if "constitución" in lower … return Rank.CONSTITUCION`. Worth
  noting for whoever fixes it: there are **two** functions named `_infer_rank_from_title` —
  `metadata.py:161` (the dangerous one) and `sumario.py:47` (four `startswith` tests, no
  constitution branch). Only the first produces the bug.
- **`_LEGISLATIVE_SECTIONS = {"1", "1A", "T"}`** at `sumario.py:44` — confirmed. Section
  `1A` did not occur on any of my 14 days; section `T` occurred on 1 (1986-12-31, 12 items).
- **TC *judgments* are not in Sección I** — confirmed. But TC **procedural** acts are, and
  routinely: 4 `Providencia` (2004, 2018 ×2, 2023) and 1 `Auto` (2004) in my 122.
- **The consolidation-lag / 30-day gate.** My own crude instrument (catalogue entries per
  publication day by age, n=83 over 120 days) showed no ramp-up in the youngest week and
  would argue the gate is *too long*. **I withdraw it** — the August dip confounds it, and
  the angle-3 section above measures the same thing properly on n=186 and reaches the
  opposite conclusion. Angle 3's number supersedes mine; do not average them.
- **A date correction, small but load-bearing for reproduction.** The probe dates
  `BOE-A-2026-10881` to "19 May 2026". That is its `fecha_disposicion`; it was **published
  on 2026-05-20**, where it is the single Sección I item of the day. A sumario sweep is
  keyed on publication date. Verified by fetching that day's sumario.

---

### 7. One volume category neither probe surfaced: CCAA reprints decades late

**9 of the 26** Sección I items on 2011-12-31 are Basque Country laws **from 1998**
republished in the BOE in 2011: `BOE-A-2011-20654`, `20655`, `20656`, `20658`, `20661`,
`20662`, `20663` and neighbours — all `rango 1300 Ley`, all `origen_legislativo Autonómico`,
all non-consolidated, 3,066 – 209,613 chars each (e.g. *Ley 12/1998, contra la Exclusión
Social*; *Ley 19/1998, de Ordenación Universitaria del País Vasco*).

The rule keeps them and should. The consequence is elsewhere: **`fecha_disposicion` and
`fecha_publicacion` diverge by up to 13 years** in this population. Anything in the rebuild
that shards, dates, orders commits or names files by publication year will place a 1998
Basque law in 2011. Given that `Source-Date` ordering is already a known defect class in
issue #106, this is worth deciding before the sweep, not after.

---

### 8. Corrected scope rule

The probe's procedure with the three defects above repaired. Changes are **bold**.

```
INPUT: a BOE id appearing in a daily sumario, section codigo = "1"
       (fetch xml.php?id= once; every field below is on that document)

1. GATE — freshness                       [see angle 3; not my measurement]

2. ORACLE — membership
   **if <estado_consolidacion codigo> == "3":  EXISTING PATH**
        No catalogue enumeration needed. 159/159 agreement with the catalogue.

3. DROP — not a norm
   a. rango codigo IN {1590, 1240, 63, **1250**}
        **1250 Auto — TC procedural act, IS in Sección I (BOE-A-2004-13466)**
   b. **any <anteriores><anterior><palabra> matching /^(CORRECCIÓN|CORRIGE)\b/**
        **catches the corrección that carries rango 1370 (BOE-A-2011-20653);**
        **12/12 vs 11/12 for rango alone**
   c. **assert: departamento IN {Tribunal Constitucional, Tribunal Supremo}**
        **=> rango must be in the set above. This assertion fires on 1250 and is**
        **how a future unseen TC rank code gets noticed instead of published.**

4. GATE — text: empty <documento><texto> -> METADATA-ONLY or SKIP

5. KEEP — emit as a law file

6. RESIDUE — the rule cannot decide.  **>= 27 %, and the floor is soft.**
   Singular/administrative acts, **plus the periodic price/tariff publications of §2.3
   which the probe's census did not contain.** Six further fields tested (§4.2), none
   decides it. -> the probe's "keep it" recommendation stands, but budget for a larger
   share than 27 % and record the class of every kept act so it can be filtered later
   without a rebuild.
```

**On the rank codes: stop maintaining a code allowlist for the DROP side.** Every rank code
that has ever appeared in the consolidated catalogue is a norm (19 codes, §3); every code
outside that set that has appeared in Sección I so far (1590, 1240, 63, 1250, 1676) is
either a non-norm or unmapped. **Invert the test** — keep what the catalogue's rank
vocabulary contains, and route anything else to a review queue. That fails safe on the next
`1250`; the current allowlist fails open.

---

### 9. Caveats on my own work

- **My adversarial sample is adversarial on purpose.** The 38 ids selected by title pattern
  are *not* a random sample and must not be read as rates. Only the 45-item census of
  2000-12-30 + 2011-12-31, and the 122-item Sección I population of the 14 days, carry rates.
- **14 days is not enough to settle the item-rate either.** My 8.71/day is as
  day-selection-biased as the probe's 4.00/day, in the opposite direction. The honest
  statement is that neither number is safe and the pooled 5.57/day over 42 days is still
  built from 42 hand-picked days out of ~14,550.
- **One corrección out of twelve is n=1.** `BOE-A-2011-20653` proves the rank field is not
  sufficient; it does not establish 8.3 % as the rate. The fix (§8, step 3b) is free
  regardless of the rate.
- **`1250 Auto` is also n=1**, from 2004. I did not measure how often TC autos reach
  Sección I.
- **I reused the probe's cached catalogue bytes** as the membership oracle for the 122-item
  population, so that one number is not independent of Probe 2. Everything downstream of a
  fetched document uses `estado_consolidacion` instead, which is independent — and §5 shows
  the two agree 159/159, so the reuse is not load-bearing.
- **Not measured:** whether "Resolución … de corrección de errores" is a recurring CNMV /
  Banco de España pattern or an isolated drafting choice; how large the price/tariff class is
  as a share of the backlog; whether `1250` has siblings.

## taxonomy — angle 1: the categories do not hold

Verifier probe against `02-taxonomia.md`. Independent sample, independent method.
**Verdict: PARTIALLY_REFUTED.** The rule survives. The taxonomy's *weights* survive.
The **denominator does not**, one category boundary the probe never named covers
**23.5 %** of the population, and two secondary claims are sampling artefacts.

**HTTP: 100 of 100 requests to `boe.es`**, `Accept` always set explicitly,
`User-Agent: legalize-bot/1.0 (+https://github.com/legalize-dev/legalize)`,
0.6 s between requests, every response cached under
`/Users/neli/.claude/jobs/5bf7ddf4/tmp/refute_tax/cache/`. No 429, no 5xx.
1 request was wasted on a 404: **the brief's path `/api/legislacion-consolidada` does
not exist** — the real one is `https://www.boe.es/datosabiertos/api/…`, as
`engine/src/legalize/fetcher/es/client.py` already knows.

---

### My sample — zero day overlap with the probe, zero with Probe 1

22 gazette days, months **Feb / Apr / May / Nov / Dec** (the probe used Jun/Sep/Oct;
Probe 1 used January), weekdays mixed Tue–Fri, years chosen to interleave with the
probe's rather than repeat them:

```
1986-11-11  1990-04-19  1991-12-05  1994-02-22  1996-11-08  1999-04-21
2000-12-14  2002-02-26  2004-11-05  2006-04-25  2009-12-10  2011-02-22
2014-11-13  2016-04-26  2018-12-13  2020-02-27  2022-11-10  2023-04-25
2025-12-11  2026-02-19  2026-04-23  2026-05-21
```

| Measure | Value |
|---|---|
| Gazette days | 22 (all HTTP 200) |
| Sección I items | **125** |
| Non-consolidated | **98 (78.4 %)** |
| Diary XML census | **75** documents, all HTTP 200 |
| Membership oracle | my own enumeration, 2 requests, **12,385** ids |

**Census selection rule, fixed before fetching:** every non-consolidated Sección I act
*except* near-identical siblings within the same day + departamento + act family, of
which one representative is kept. 23 duplicates dropped (4 TC *recursos* of 1999, 3
Navarra amending *Leyes Forales*, 3 *traspaso* RDs of 2006, 2 *zona de interés* RDs of
2002, 2 TS *sentencias* of 2018, 2 Navarra *desafectación* laws, and 7 further
one-of-a-pair drops), 75 fetched. The taxonomy below is computed on **all 98**; the
`rango` rule test on the **75** that have metadata.

---

### 1. The denominator is contaminated — 88.4 % is not a measurement of the population

The probe's own cache refutes its headline. `probe2/sec1_items.json` holds
**24 days and 75 items**, not the 28/112 the artefact reports:

```
$ python -c "d=json.load(open('probe2/sec1_items.json')); print(len(d['per_day']), len(d['items']))"
24 75
$ non-consolidated on that data: 63/75 = 84.0 %
```

The extra 37 items that lift the count to 112 come from **1983-10-18, 1984-06-19,
1985-06-18 and 1987-06-16** — the four days the probe fetched *for a different
measurement*, the pre-1984 digitisation bisect in its §5. Their per-day Sección I
counts (6, 12, 8, 11) reconcile the gap exactly. Those days were selected **because
they are old**, and almost nothing that old is consolidated, so folding them into the
membership denominator can only push the rate up.

| Non-consolidated share of Sección I | n | value |
|---|---:|---:|
| Probe, headline | 112 | **88.4 %** |
| Probe, its own stratified sample (cache) | 75 | **84.0 %** |
| **Mine, 22 days 1986–2026** | **125** | **78.4 %** |
| Mine, dropping my one outlier day (1999-04-21) | 99 | 75.8 % |

And the share is **strongly era-dependent and falling**, which no single headline
number can carry:

| Era | days | items | items/day | non-consolidated |
|---|---:|---:|---:|---:|
| 1986–2004 | 9 | 60 | 6.67 | **88.3 %** |
| 2006–2023 | 9 | 37 | 4.11 | **70.3 %** |
| 2025–2026 | 4 | 28 | 7.00 | **67.9 %** |

88.4 % is roughly the *pre-2005* rate. Applying it to the whole 1979–2026 backlog
inflates the modern end by ~20 pp, and applying it to the **steady state** — which is
what sizes the ongoing daily job — inflates it by the same.

**Not safe to decide on:** `88.4 %`, and everything derived from it in §4 of the probe
(`~42,000`, `~30,000`, `~11,000`, `~1.4 acts/gazette day`).

### 2. "Sección I is shrinking" is an August artefact

The probe reports 6.00 → 3.20 → **2.07** items/day and concludes a steady state of
~1.4 new acts per gazette day. Its 2025–2026 rate rests on a 14-day ladder of which
**five days returned zero Sección I items**: 2025-09-02, 2026-06-04, 2026-08-04,
2026-08-25, 2026-08-31 — the Spanish legislative recess and the days either side of it.

My four 2025–2026 days, in December, February, April and May, give **7.00 items/day**
(12, 6, 3, 7) — 3.4× the probe's figure, and *higher* than my own 1986–2004 mean. The
one day in my whole sample with zero Sección I items is 2022-11-10.

| | probe (Aug/Sep-weighted) | mine (Dec/Feb/Apr/May) |
|---|---:|---:|
| 2025–2026 Sección I items/day | 2.07 (14 d) | **7.00** (4 d) |
| × non-consolidated | 88.4 % | 67.9 % |
| new non-consolidated acts/gazette day | ~1.8 | **~4.8** |

Both sides are small samples and both are seasonally biased in opposite directions;
the honest statement is that the steady-state rate is **not measured**, not that it is
1.4. Sección I output is heavily overdispersed (my per-day counts run 0 → 26) and no
20-something-day sample settles it. What *is* settled is that the probe's number is the
bottom of the range, not the centre.

### 3. The `rango` rule — CONFIRMED, and stronger than the probe showed

On my 75-act census the rule `rango codigo ∉ {1590, 1240, 63}` performs exactly as
claimed, on a sample with no days in common:

| | probe | mine |
|---|---|---|
| non-norms dropped | 12 / 12 | **14 / 14** |
| false drops | 0 | **0** |
| non-norms the rule missed | (not tested) | **0** |

Rank codes seen: `1590` Corrección × 9, `63` Providencia × 4, `1240` Sentencia × 1.
Every act I independently classified as *judicial* or *corrección de errores* carries
one of the three; no act I classified as a norm does.

**Where the probe undersold itself.** It wrote that "title-prefix matching on
`corrección de err` selects the identical 5". On my sample it does **not**:

> `BOE-A-1999-8860` — *"**Rectificación de error** padecido en el edicto del recurso de
> inconstitucionalidad número 1.046/1999…"* — `rango codigo="1590"`, departamento
> Tribunal Constitucional, 689 chars, targets `BOE-A-1999-7662`.

Title-prefix catches **8 of 9**; `rango` catches 9 of 9. The two keys are **not**
equivalent, and the field is the one that works. The probe's recommendation is right;
its stated justification is wrong on a wider sample.

**Where the rule still loses text.** Of my 9 *correcciones*, **7 target a norm that is
itself not in the consolidated catalogue** — so "drop it, the BOE folds it into the
consolidated text" fails 78 % of the time, not occasionally:

| corrección | chars | target | target consolidated? |
|---|---:|---|---|
| BOE-A-2011-3428 | **43,597** | BOE-A-2010-19848 | **no** |
| BOE-A-2016-3973 | 11,087 | BOE-A-2014-9484 | yes |
| BOE-A-2002-3821 | 4,046 | BOE-A-2002-3138 | yes |
| BOE-A-2023-9960 | 1,417 | BOE-A-2023-9098 | **no** |
| BOE-A-1999-8860 | 689 | BOE-A-1999-7662 | **no** |
| BOE-A-1999-8866 | 591 | BOE-A-1999-4312 | **no** |
| BOE-A-2002-3824 | 495 | BOE-A-2002-550 | **no** |
| BOE-A-2025-25274 | 470 | BOE-A-2025-20583 | **no** |
| BOE-A-1999-8857 | 436 | BOE-A-1999-8716 | **no** |

`BOE-A-2011-3428` alone is 43,597 characters — it republishes whole tariff annexes of
an Orden that has no consolidated text anywhere. Drop it and the corpus ships the
uncorrected table. The probe's "apply and reference, do not ignore" is therefore not a
footnote; it is load-bearing for **7 of 9** cases.

### 4. The categories: 23.5 % of the population fits none of them

This is my angle's main result. I classified all 98 by hand from `<titulo>`,
`departamento`, `epígrafe` and (for the 75) `rango` + `<analisis>`. **23 acts do not
fit any of the probe's six categories without a judgement call**, and they cluster into
six families the probe's taxonomy has no name for:

| Family | n | % of 98 | `rango` seen | Why it fits nowhere |
|---|---:|---:|---|---|
| **N1 · Traspaso de funciones y servicios to a CCAA** | 7 | 7.1 % | 1340 RD | An RD approving a Comisión Mixta agreement. Not a subsidy, not a regulation, not an amendment. Permanent constitutional effect; the normative content is the annexed *acuerdo*. |
| **N2 · Publication vehicle** | 6 | 6.1 % | 1370 Res × 4, 1350 Orden | The act's whole content is *"se publica el Acuerdo / los Estatutos…"*. The norm is the annex, not the act. |
| **N3 · Recurring parametric bulletin** | 5 | 5.1 % | 1370 Res × 3, 1350 Orden | Fuel prices, calorific value, contribution bases, fiscal-effort data. Erga omnes and expiring; published on a cadence. |
| **N4 · Singular act carried by a *Ley*** | 2 | 2.0 % | 1450 Ley Foral | A law whose entire content is the deaffectation of one named plot of land. |
| **N6 · Programme procedure** | 2 | 2.0 % | 1370 Res, 1350 Orden | Processing rules for one aid programme / one financial year's account closure. |
| **N5 · Pure repeal** | 1 | 1.0 % | 1340 RD | Repeals another RD outright. Has no autonomous text but is not *"por el que se modifica"*. |
| **total misfit** | **23** | **23.5 %** | | |

The ids, so the labels can be re-argued:

- **N1** `BOE-A-1996-24628`, `BOE-A-1999-8870`, `BOE-A-1999-8871`, `BOE-A-2006-7320`,
  `BOE-A-2006-7321`, `BOE-A-2006-7322`, `BOE-A-2006-7323`
- **N2** `BOE-A-2014-11715`, `BOE-A-2023-9954`, `BOE-A-2025-25276`, `BOE-A-2025-25277`,
  `BOE-A-2025-25278`, `BOE-A-2026-10887`
- **N3** `BOE-A-1996-24626`, `BOE-A-1996-24627`, `BOE-A-2000-22620`, `BOE-A-2020-2741`,
  `BOE-A-2026-3814`
- **N4** `BOE-A-2011-3432`, `BOE-A-2011-3433`
- **N5** `BOE-A-2016-3975`
- **N6** `BOE-A-1990-9209`, `BOE-A-2004-18909`

#### The three boundaries that actually decide the corpus size

**(a) N2 breaks the probe's own definition of the residue.** The probe defines
*singular/administrative* to include "publication of a Council of Ministers agreement".
That is fine for `BOE-A-2025-25277` (Acuerdo declaring named doctorates official). It is
wrong for:

> `BOE-A-2026-10887` — *"Resolución 10/2026 … por la que se publica el Acuerdo del
> Consejo de Gobierno … por el que se **aprueban los Estatutos de la Universidad de La
> Rioja**"* — `rango 1370`, seccion 1, origen Autonómico.

Same rango, same shape, same verb (*se publica*), and the payload is a complete
constitutive general norm. Two acts identical in every machine-readable field land on
opposite sides of the keep/drop line. `BOE-A-2023-9954` is a third variant: a
*Resolución del Congreso* publishing the convalidation of a Real Decreto-ley — a
parliamentary act, not an administrative one, and again `seccion 1`.

**(b) N3 is a ±5 pp lever on the residue.** The probe's *autonomous general
disposition* is defined as including "a tariff set". Take that literally and the two
gasoline-price Resoluciones of 1996-11-08 are general dispositions. But the BOE
published those **weekly for years**; sweeping them in as law files is a
five-figure-scale decision made by a definition, not a rule. Flip N3 from *general* to
*singular* and the residue moves:

| | residue (singular) | autonomous general |
|---|---:|---:|
| N3 counted as general (my force-fit) | **27.6 %** | 22.4 % |
| N3 counted as singular | **32.7 %** | 17.3 % |

The number the whole policy decision hangs on is stable to ±0.6 pp against the probe
*only* because I happened to fit N3 the same way the probe's definition implies. It is
not a measured quantity; it is the output of one definitional choice.

**(c) N4 puts the residue inside `rango = Ley`.** The probe's §3.6 residue is described
and enumerated entirely as RD / Orden / Resolución (`1340/1350/1370`). It is not:

> `BOE-A-2011-3432` — *"**Ley Foral 24/2010** … por la que se declara de utilidad
> pública y se aprueba la desafectación de **101.986,68 metros cuadrados** de terreno
> comunal pertenecientes al Ayuntamiento de Mendavia."* — `rango 1450`.

`1450 Ley Foral` appears in my census across *autonomous general* (5), *amending-only*
(1) **and** the singular residue (1); `1300 Ley` across *autonomous general* (2) and
*amending-only* (3). Any allowlist-by-rango escape hatch for the residue (the probe's
§6 fallback, "exclude by `rango` + `departamento` allowlist per shard") therefore does
not exist: the residue is not confined to the low ranks.

#### The weights themselves survive

Force-fitting every misfit into its nearest probe category (N1,N2,N4→singular;
N3,N6→general; N5→amending):

| Category | mine n | mine % | probe % | Δ |
|---|---:|---:|---:|---:|
| singular / administrative | 27 | 27.6 | 27.0 | **+0.6** |
| autonomous general disposition | 22 | 22.4 | 25.4 | −3.0 |
| amending-only | 19 | 19.4 | 22.2 | −2.8 |
| judicial | 13 | 13.3 | 11.1 | +2.2 |
| corrección de errores | 9 | 9.2 | 7.9 | +1.3 |
| international agreement | 8 | 8.2 | 6.3 | +1.9 |
| **sum** | **98** | **100.0** | **99.9** | |

Both sets sum to 100 % over a stated denominator, and every gap is inside the probe's
own ±6 pp binomial band. **The ordering and the magnitudes reproduce on an
independent sample.** The taxonomy is a usable description of the population. What it
is not is a *decision procedure*: a quarter of the population has to be argued into a
box before the percentages exist at all.

### 5. "TC judgments are NOT in Sección I" — right about *sentencias*, wrong about the Court

The probe concludes that Sección I judicial content is Tribunal Supremo, with two TC
*providencias* as a curiosity. On my sample it is the other way round:

| | probe (63-act census) | mine (98 acts) |
|---|---:|---:|
| judicial acts in Sección I | 7 | **13** |
| — Tribunal Constitucional (procedural) | 2 | **10 (77 %)** |
| — Tribunal Supremo (sentencias) | 5 | 3 |

And the TC acts are not one type but at least four, all `rango 63 Providencia`:
*Conflicto positivo de competencia* (`BOE-A-1986-29658`, `BOE-A-1986-29659`,
`BOE-A-1999-8858`, `BOE-A-1999-8859`), *Recurso de inconstitucionalidad*
(`BOE-A-1999-8861`…`8864`), *Cuestión de inconstitucionalidad* (`BOE-A-2000-22617`,
`22618`), and a *Rectificación de error* on a TC edict (`BOE-A-1999-8860`, `rango 1590`).
On 1999-04-21 the Constitutional Court alone accounts for **7 of the day's 26** Sección I
items.

Section `T` exists but is thin and intermittent: present on 2 of my 22 days
(2000-12-14: 13 items, 2023-04-25: 7). The probe's warning about
`_LEGISLATIVE_SECTIONS` containing `"T"` stands. The correction is that dropping
section T does **not** get the Court out of the sweep — `rango 63` is what does.

### 6. Two more things the source does that no probe category covers

**A Sección I item can be a *fragment* of an act.** `BOE-A-1986-49992`, published
1986-11-11, is *"Acuerdo Europeo sobre Transporte Internacional de Mercancías
Peligrosas por Carreteras (ADR) … **(Continuación.)**"*. `rango 1180`, `seccion 1`,
`<documento><texto>` **empty**, and its sequence number (49992) is far outside the
day's range (29658–29661). It is one instalment of a document serialised across BOE
issues, each instalment with its own id and its own Sección I entry. The `rango` rule
**keeps** it, and it would be emitted as a law file that is a torso. n=1 in my sample,
so I cannot size it — but it is the one non-act the rule cannot see, and it is exactly
the shape of thing that only shows up in a full 14,550-day sweep.

**A fourth unmapped rank code, and a second two-digit one.**
`BOE-A-2009-19876` carries `rango codigo="41"`, text **"Nota Diplomática"** —
*"Instrumento de aprobación de la retirada de la reserva … al Convenio para la
prevención y la sanción del delito de genocidio"*. Checked against
`engine/src/legalize/fetcher/es/metadata.py::_RANK_CODE_MAP`, the codes in my census
that are unmapped are:

| code | text | n in my census | in probe's list? |
|---|---|---:|---|
| `1590` | Corrección (errores o erratas) | 9 | yes |
| `63` | Providencia | 4 | yes |
| `1240` | Sentencia | 1 | yes |
| **`41`** | **Nota Diplomática** | **1** | **no** |

The probe flagged `63` as "breaks the 4-digit pattern"; `41` is a second, so the
two-digit case is a class and not an exception. (`1450 Ley Foral` and
`1325 Decreto-ley Foral`, which my sample hits 7 and 1 times, *are* mapped.)

### 7. What reproduced without argument

- **Catalogue size = 12,385**, enumerated independently in 2 requests
  (page 1 = 10,000, page 2 = 2,385). Identical to the probe.
- **The corpus gap is total.** 0 of my 98 non-consolidated ids appear among the 12,300
  `.md` basenames in `/Users/neli/projects/legalize/countries/es`. (12,300, not 12,299 —
  one more file than the brief states; not chased.)
- **`rango` partitions the non-norms perfectly and the norms not at all.** `1340`,
  `1350`, `1370` and `1450` each appear in three or more of my categories.
- **`seccion` is constant** (`1` × 75) and **`estatus_legislativo` is not a non-norm
  signal**: my 4 blanks are 2 providencias, 1 sentencia and the ADR *continuación* —
  it misses 11 of my 14 non-norms and flags one act that is not a non-norm.

---

### Verdict table

| Probe claim | Verdict | Mine |
|---|---|---|
| Catalogue = 12,385 ids, 2 requests | **CONFIRMED** | 12,385 |
| Non-consolidated share = **88.4 %** | **REFUTED** | **78.4 %** (125 items / 22 days); probe's own cache says 84.0 % on 75 items / 24 days; the 112/28 denominator folds in 4 days fetched for the digitisation bisect |
| Sección I = 4.00 items/day | **PARTIALLY REFUTED** | 5.68/day; and the metric is overdispersed (0–26/day), not a constant |
| "Sección I is shrinking", 2.07/day in 2025–26 | **REFUTED** | 7.00/day on Dec/Feb/Apr/May 2025–26; the probe's ladder is 5/14 zero-item days in the August recess |
| Steady state ≈ 1.4 acts/gazette day | **REFUTED** | ~4.8/day on my days; neither figure is a measurement |
| Six-category taxonomy, weights | **CONFIRMED** | every category within 3.0 pp; both sum to 100 % of a stated denominator |
| The taxonomy is a usable *classification* | **REFUTED** | **23.5 %** (23/98) fits no category without a judgement call; six unnamed families |
| Residue (singular/administrative) = 27.0 % | **CONFIRMED but unstable** | 27.6 % force-fitting as the probe defines; **32.7 %** if recurring bulletins count as singular — one definitional choice, ±5 pp |
| Residue lives in rango 1340/1350/1370 | **REFUTED** | also `1450 Ley Foral` (`BOE-A-2011-3432/3433`), so a rango allowlist cannot fence it |
| `rango ∉ {1590,1240,63}` drops all non-norms, 0 false drops | **CONFIRMED** | 14/14 dropped, 0 false drops, 0 missed, on a disjoint 75-act census |
| Title-prefix "corrección de err" ≡ rango 1590 | **REFUTED** | 8/9; misses `BOE-A-1999-8860` "Rectificación de error…". Use the field. |
| Correcciones whose target is unconsolidated are an edge case | **REFUTED** | **7 of 9**; one is 43,597 chars |
| TC judgments are not in Sección I | **PARTIALLY REFUTED** | *sentencias* no; TC **procedural** acts yes — 10 of my 13 judicial acts, 7 on one day |
| `1676`, `1590`, `1240`, `63` unmapped in `_RANK_CODE_MAP` | **CONFIRMED + extended** | add **`41` Nota Diplomática**; two-digit codes are a class |

### What I would not decide on without more measurement

1. **Any volume figure.** Both probes' per-day rates are seasonally biased in opposite
   directions and the metric is overdispersed. Sizing the backlog needs a cheap census
   of *item counts* across many days, not a taxonomy sample — and `sumario` item counts
   cost one request per day, so a proper year-stratified count is affordable and has
   not been done.
2. **The residue's size.** 27 % vs 33 % turns on whether recurring parametric bulletins
   are norms. That question should be answered by counting how many of them the BOE
   published (fuel prices ran weekly for over a decade), not by a category label.
3. **How often a Sección I item is a `(Continuación.)` fragment.** n=1 here. If it is
   even 1 %, the sweep emits several hundred torso files.


---

## discovery — angle 1: does the endpoint actually behave as claimed?

**Verifier:** independent probe, 2026-09-03, **82 HTTP requests** to `www.boe.es`
(0.5–1.0 s apart, single-threaded, `User-Agent: legalize-bot/1.0 (+https://github.com/legalize-dev/legalize)`).
Two HTTP 500s, both deterministic responses to deliberately malformed input of mine
(§R3); no 429, no unprovoked 5xx. Scratch: `/Users/neli/.claude/jobs/5bf7ddf4/tmp/refute_a1/`
(`h.py`, `a1_walk.py`, `b_paging.py`, `d_sort.py`, `d2.py`, `e_sortwalk.py`,
`f_window.py`, `g_cursor.py`, `h_silent.py`, `i_sweep.py`, `j_reprobe.py`,
`k_fmt.py`, `reqlog.jsonl`).

**Verdict: PARTIALLY REFUTED.** The headline survives a genuinely independent
re-measurement — 12,385 norms, two requests, `#99` is a small fix, the daily
`sumario` really is the only index. What does **not** survive is the *daily*
design in §5.4 and the implicit trust the report places in the `query` parameter.
Three concrete ways to make the API lie to you, all reproduced below.

### My sample and method (deliberately different from the probe's)

The probe established the total by **binary search on `offset` with `limit=1`**
(15 requests). I did the opposite: I pulled **my own complete 12,385-item dump**
(`?limit=-1&offset=0` + `?limit=-1&offset=10000`, reqs 1–2, 15,982,267 B) and then
used it as an **offline oracle** — every subsequent API answer was checked against
a count I had already computed locally, instead of against another API answer.
That is what exposes silent filter failures, which a purely API-internal method
cannot see.

Distinct samples used:

| Sample | What |
|---|---|
| Full dump | 12,385 items, reqs 1–2 (13,002,973 B + 2,979,294 B) |
| Deep-offset windows | `offset=9995 limit=10`, `offset=9990 limit=20`, `offset=12144 limit=72` (the 72-item tie group at `fecha_actualizacion=20251216T102453Z`) |
| Time-gap re-probe | the same three windows re-fetched **35 min later** (reqs 75–80, 12:52 → 13:27) |
| Sorted walk | full `{"sort":[{"identificador":"asc"}]}` walk, both pages, reqs 27–28 |
| Offline oracles | fecha_publicacion 2020 = **773**; `ambito@codigo:2` = **3,618**; `fecha_actualizacion` in 2025-12 = **10,017**; on 2025-12-19 = **3,299**; in 2023 = **80** |
| Contiguous diary sweep | **1979-12-15 … 1980-01-14**, all 31 calendar days, no gaps, no cherry-picking (reqs 44–74) |

The probe sampled the diary with two seeded RNGs and 30 scattered days. I swept a
**contiguous month** instead, chosen to be the worst case for its central
assumption: the Christmas–Epiphany fortnight of the earliest claimed year.

---

### R1 — REFUTED: `?from=&to=` silently truncates at 10,000, HTTP 200, no total

This is the one finding that changes a design decision.

| Request | Items returned | True count (my offline oracle) |
|---|---|---|
| `?from=20251201&to=20251231&limit=-1` (req 29) | **10,000** | **10,017** |
| `?from=20251201&to=20251231&limit=-1&offset=10000` (req 30) | 17 | — |
| `?from=20251201&to=20251231&limit=-1&offset=10017` (req 31) | 0 (`"data": ""`) | — |
| `?from=20251219&to=20251219&limit=-1` (req 32) | 3,299 | 3,299 ✓ |

A single windowed request over December 2025 **drops 17 norms and says
`{"code":"200","text":"ok"}`**. The response body has exactly two top-level keys,
`status` and `data` — there is **no total, no `numFound`, no `truncated` flag, no
`Link` header**. Truncation is undetectable except by issuing another request at
`offset=10000` and finding it non-empty.

The report's §5.4 says:

> "The daily stays at two discovery requests **regardless of window width**, because
> `from`/`to` accepts a range and the 10,000 cap is ~770× the observed daily volume of 13."

The margin is not 770×. **2025-12-19 alone carries 3,299 items — 33 % of the cap**,
and the month around it carries 10,017. The BOE has now done two bulk re-stamps
(2023-12-15, and the December-2025 event visible in every dump), and a re-stamp is
exactly what a `from`/`to` backfill after an outage would land on. The cost model
"backfill of N days = 1 request" is wrong; a backfill must page the window until a
page comes back empty, the same as `discover_all`.

*(Confirmed sub-claims: `to=20240101` → 80, matching my dump's 2023 count exactly;
`from=20260901` → 31; `from>to` → 0 with 200; `from=2025-12-01` (ISO dashes) → 400.)*

### R2 — REFUTED (new): `query` fails **silently** for a known-but-unsupported field

The report treats `query` as a reliable surface (§5.1's escape hatch, §2.3's stable
sort). It is reliable only where you already know the answer.

| Probe | Result |
|---|---|
| `{"query":{"range":{"fecha_publicacion":{"gte":"20200101","lte":"20201231"}}}}` (req 25) | 773 — **matches my offline count exactly** ✓ |
| `{"query":{"query_string":{"query":"ambito@codigo:2"}}}` (req 26) | 3,618 — **matches exactly** ✓ |
| `{"query":{"range":{"no_such_field":{...}}}}` (req 40) | **400** `undefined field: "no_such_field"` ✓ |
| `{"query":{"range":{"identificador":{"gte":"BOE-A-2020-4262","lte":"BOE-A-2020-4270"}}}}` (reqs 39, 41) | **200 — filter silently discarded.** Returned the *entire* 10,000-item page (12,775,740 B), head `BOA-d-1991-90001`; expected ~9 items |

`identificador` is a valid field for `sort` (proved in R4) and a valid field for the
API's own vocabulary, but a `range` on it is **dropped without a word**. So:

1. **There is no cursor walk.** The obvious hardening of §5.1 — resume from
   `identificador > last_seen` instead of a numeric `offset` — does not exist.
   A caller who writes it gets 10,000 items per page forever and a bootstrap that
   never terminates while looking perfectly healthy.
2. **You cannot tell a working filter from an ignored one** without an
   independently-computed expectation. §5.1's year-shard escape hatch does work
   (773 verified), but the report's evidence for it (reqs 103–104: "returned 200
   with in-range data") is exactly the evidence a *silently ignored* filter also
   produces, because the unfiltered first page is in-range too. If that hatch is
   ever used, its first page must be count-checked against a known total.

The 400 body leaks the backend and explains the shape of all of this:
`Search error: [undefined field: "no_such_field"][{"query":"{!complexphrase}id:*","sort":…}]`
— it is **Apache Solr**, `identificador` maps to Solr's `id`, and `limit`/`offset`
map to `rows`/`start` (`'rows' parameter cannot be negative`, req 13;
`'start' parameter cannot be negative`, req 16).

### R3 — REFUTED (new): client-side errors return **500**, and `limit=0` looks like end-of-data

| Input | Response |
|---|---|
| `query={oops` (malformed JSON) (req 23) | **HTTP 500** |
| `{"query":{"query_string":{"query":"no_such_field:zzzz"}}}` (req 42) | **HTTP 500** |
| `limit=abc` (req 15) | 400, `El parámetro limit debe ser un entero.` |
| `limit=-2` (req 13) / `offset=-1` (req 16) | 400 |
| **`limit=0`** (req 14) | **200, `"data": ""`** |
| `offset=99999999` (req 17) | 200, `"data": ""` |

Two consequences for the design:

- Any retry/backoff wrapper — and this research pass's own abort rule — reads a
  **client bug as a source outage**. A typo in the `query` JSON will look like
  boe.es falling over, and the pipeline will retry, back off and alert instead of
  failing fast. Discovery must not retry a 500 that came from a request it built.
- `limit=0` and "past the end" are the **same response**. A walk whose termination
  condition is "empty `data`" terminates on the first page if the page size is ever
  misconfigured to 0, and reports success with zero ids. Terminate on
  `len(page) < requested` or on an explicit exhausted-offset check, not on falsiness.

### R4 — CONFIRMED, and strengthened: the recommended walk really is correct

I tried hard to make it lose or duplicate an item and could not.

| Claim | Probe | Mine | Verdict |
|---|---|---|---|
| Catalogue total | 12,385 (binary search) | **12,385** (full dump, 2 reqs, deduped) | ✓ |
| `limit=-1` ceiling | 10,000 | **10,000** (`limit=10001` → 10,000, req 11) | ✓ |
| Cap is per *page*, not per window | not tested | **`limit=10000&offset=5` → 10,000 items** (req 12) — so the walk can page past the cap | ✓ new |
| `sort` is honoured globally | 2 small pages | **asc first 5, asc [5:10], desc first 5, and `offset=12384`** all match `sorted()` over my own dump byte-for-byte (reqs 18–21) | ✓ |
| Bogus `sort` field | not tested | **400**, not silently ignored (req 22) | ✓ new |
| Sorted full walk = default walk | inferred | **Verified end-to-end** (reqs 27–28): 12,385 distinct, page 1 ∩ page 2 = ∅, boundary strictly increasing (`BOE-A-2020-4261` → `BOE-A-2020-4262`), **set identical to the default walk** | ✓ |
| Offset walk stable | 15-minute gap, 2 pages | **35-minute gap** (reqs 3/6/8 vs 75/77/80): `offset=9995 limit=10` byte-identical, the 72-item tie group identical **in order**, `offset=12384` still `BOE-A-1887-4896`, `offset=12385` still empty, sorted boundary still contiguous | ✓ |

One thing the probe did not check and that mattered: **the sort key is not unique.**
72.7 % of items (8,999 of 12,385) share a `fecha_actualizacion` with at least one
other item; there are only 6,020 distinct timestamps, the largest tie group is 72
items, and 2025-12-19 alone holds 3,299. Solr's `start`/`rows` deep paging over a
non-unique sort key is the classic place where pages silently overlap or skip. It
did not happen here — the tie group came back in identical order on both fetches
and matched my full dump's order — and the page-1/page-2 boundary happens to fall
*between* tie groups (`fa[9999]=20251218T151035Z`, `fa[10000]=…034Z`). But that is
luck, and the report should not rest on it. **§5.1's `sort` by `identificador` is
not a nicety, it is the fix**: `identificador` is unique across all 12,385 and
immutable, so it is the only key that makes the walk stable by construction.

Also independently reproduced, from my own dump, to the item:
8,767 Estatal / 3,618 Autonómico · 12,190 Finalizado / 195 Desactualizado ·
`BOE-A` 12,140 + 245 regional ids · `fecha_actualizacion` span
**20231215T130325Z → 20260903T093630Z** · **86 catalogue norms with no file** in
`countries/es`, **1** repo stem not in the catalogue (`README`), all 86 with a 2026
update date, decade split 1/2/3/16/64, 77 Estatal / 9 Autonómico. §2.5 stands.

### R5 — CONFIRMED, and strengthened: every non-Sunday publishes

The report's own caveat: *"I did not sweep a contiguous stretch, so a holiday 404
rate above ~10 % would not have shown up in this sample."* I swept one, and picked
the worst fortnight in the calendar.

**1979-12-15 … 1980-01-14, all 31 days, no gaps** (reqs 44–74):

| | Count |
|---|---|
| Non-Sundays | 26 — **26 × HTTP 200, zero 404** |
| Sundays | 5 — **5 × HTTP 404**, every one |
| Christmas Day 1979-12-25 | **200**, 35,587 B, 3 legislative items |
| New Year's Day 1980-01-01 | **200**, 32,389 B, 12 legislative items |
| Epiphany 1980-01-06 | 404 — and it was a **Sunday** |

The "publication day = any non-Sunday" rule is exact on a contiguous stretch of the
earliest era, through two national holidays. **14,926 days for 1979→today stands.**

### R6 — PARTIALLY REFUTED: the per-day item count, and therefore the 122K, is sampling-fragile

| Metric | Probe (30 scattered days) | Mine (26 contiguous published days, 1979-12/1980-01) |
|---|---|---|
| Section I+1A+T per published day | **8.17** (95 % CI ±2.24 → [5.93, 10.41]) | **5.88** (median 5, range 1–19) |
| …restricted to the probe's own pre-2003 stratum | **9.14** (n=14) | **5.88** — same era, 56 % lower |
| Summary bytes per day | 135,680 mean | 65,437 mean (era-appropriate: the probe's three 1979 days average 77,703) |

My 26-day mean lands **below the bottom of the probe's 95 % CI** and at 64 % of its
own early-era sub-mean. I am not claiming 5.88 is the corpus-wide figure — my
window is a holiday fortnight, and the byte figures show the modern era is far
denser. What it does show is that **8.17 ± 2.24 understates the real uncertainty**,
because the two samples disagree by more than the interval on the era where they
overlap. Pooling both (56 published days, 398 items) gives **7.11/day → ~106,000**
section I+T dispositions. Treat the repo-size answer as **"between about 90,000 and
130,000 new files"**, and take the report's own advice: the sweep produces the exact
count as a by-product, so size storage after it, not before.

The byte total is not affected much — 2.03 GB assumes 135,680 B/day and my
independent era-check is consistent with the probe's own era gradient (98,598 B
pre-2003 vs 168,128 B post-2003).

### R7 — CONFIRMED, with two additions for the sweep

- **No compression.** `Content-Encoding` absent, `Content-Length == len(content)`
  (52,057 == 52,057, req 81), despite `requests` advertising gzip. ✓
- **JSON is 1.91× the bytes** on 1980-01-14 (99,484 vs 52,057) — the probe measured
  1.93× on a different day. ✓
- **New: JSON is also ~38× slower.** Same day, same server, back to back:
  XML **0.3 s**, JSON **11.4 s** (reqs 81, 82). Over a 14,926-request sweep that is
  the difference between an hour and a day. "Ask for XML" is a wall-clock decision,
  not just a bandwidth one.
- **New: the summary is cached upstream but not revalidatable.** Response carries
  `Vary: Accept` and `Age: 97`, and **no `Cache-Control`, `ETag` or `Last-Modified`**.
  Repeat fetches are byte-identical. §5.2's "cache to disk permanently, keyed by
  date" is right, and it is the *only* option — there is no conditional request to
  make a cheap re-check with.

### What I could not break

`limit=-1` two-page enumeration; the 12,385 total; `sort` by `identificador`;
`range`/`query_string` on the fields the report used; `from`/`to` semantics
(`fecha_actualizacion`, nothing before 2023-12-15); the 86-norm drift and its
mechanism; every composition figure; the non-Sunday publication rule; no
compression; JSON larger than XML. All reproduced independently, most of them to
the exact integer.

### Changes this angle asks for in the design

1. **§5.4 daily/backfill:** page the `from`/`to` window until a page returns fewer
   items than requested. One request is only safe for a normal day; it is not safe
   for a backfill or a re-stamp. (R1)
2. **§5.1:** keep `sort` by `identificador` — it is load-bearing, not optional
   (R4) — but do **not** replace `offset` with a `range` cursor on `identificador`:
   that filter is silently discarded (R2).
3. **Any use of the §5.1 year-shard escape hatch** must count-check its first shard
   against a known total, because a dropped filter looks identical to a working one. (R2)
4. **Never retry a 5xx that came from a request discovery itself built** — malformed
   `query` returns 500, not 400. (R3)
5. **Terminate the walk on `len(page) < limit`,** not on empty `data`: `limit=0`
   and past-the-end are the same 200 response. (R3)
6. **Size storage from the sweep, not from the sample.** 122K ± 33K is optimistic;
   two independent samples disagree by more than that interval on the era where they
   overlap. (R6)

---

## discovery — angle 2: the sumario is not the only index, and the cost is priced on the wrong half

> **Verdict: PARTIALLY REFUTED.** The catalogue half reproduces exactly. The
> non-consolidated half does not: the daily summary is **not** the only index, the
> sweep the probe designed costs **325× more requests than necessary**, its
> population is **26 % too high**, and the number it headlines as "the cost of #66"
> is the cost of *discovery only* — the feature itself costs **6.1× more** than the
> headline. There is also a population no summary sweep can reach.
>
> 73 HTTP requests to `www.boe.es`, 2026-09-03, one at a time, 0.5–1.0 s apart,
> `User-Agent: legalize-bot/1.0 (+https://github.com/legalize-dev/legalize)`.
> No 429, no 5xx. Scripts and raw captures in
> `/Users/neli/.claude/jobs/5bf7ddf4/tmp/refute_a2/` (`pA.py`…`pK.py`,
> `reqlog.jsonl` has every request with status, bytes and wall time).

### My sample — deliberately different from the probe's

The probe sampled **30 scattered days** (16 era-stratified + 14 uniform random) and
extrapolated. I did the opposite: **contiguous days** where it sampled scattered ones,
**exact census queries** where it extrapolated, and **cost recomputed from the
document count** where it priced only discovery.

| Phase | Sample | Reqs |
|---|---|---|
| A | 8 **Sundays**, one per era: 1979-01-07, 1984-06-03, 1989-10-01, 1994-03-06, 1999-07-04, 2004-11-07, 2014-05-04, 2024-09-01 | 8 |
| A | Summary floor: 1960-09-01, 1960-08-31, 1960-09-02, 1960-09-08 | 4 |
| B | **Contiguous stretch 1998-12-22 → 1999-01-04** (14 consecutive days, spans Christmas, Boxing Day, New Year's Day, 2 Sundays) | 14 |
| B | Non-Sunday public holidays in other eras: 1979-12-25, 1985-12-25, 2007-08-15, 2013-12-25, 2020-01-01, 2026-01-01 | 6 |
| C | 14 diary XMLs, quantile-picked across the `szBytes` range the summaries report | 14 |
| D | Independent re-dump of the whole consolidated catalogue | 2 |
| E–J | `/buscar/boe.php` — form, 6 census queries, 3 index pages, 1 pre-floor document | 15 |
| K | 10 **uniform-random** diary XMLs (seed 20260903) from the 112 section-I items in my summaries | 10 |

### What reproduced — CONFIRMED

| Probe's number | Mine | How |
|---|---|---|
| Catalogue = **12,385** norms | **12,385**, 12,385 distinct | Independent re-fetch, `?limit=-1&offset=0` + `offset=10000`, reqs 47–48 |
| **2 requests, 16.0 MB, ~28 s** | 2 requests, **15,982,267 B**, **29.1 s** (24.56 s + 4.57 s) | reqs 47–48 |
| **11,713** consolidated BOE-A norms published ≥ 1979 | **11,713** | Counted on my own dump |
| Sundays are not publication days | **0 of 8** Sundays returned 200, across 1979–2024 | reqs 1–8 |
| Every non-Sunday is a publication day | **18 of 18** non-Sundays returned 200 — including a *contiguous* Christmas/New Year run and 6 holidays in 5 other eras. The 2 Sundays inside the stretch were the only 404s | reqs 13–32 |
| One issue per day | **1 `<diario>` element on all 18 days.** No hidden supplements | offline parse of `raw/*.xml` |

The probe's own caveat — "a holiday 404 rate above ~10 % would not have shown up in
this sample" — is now closed: on the worst 14-day stretch of the calendar the
non-Sunday 404 rate is **0/12**.

### 1. REFUTED — the daily summary is **not** the only index

The probe's §3.2 concludes "**The daily summary is the only index. Nothing else
enumerates.**", and its own caveat dismisses the BOE's HTML search as "~50
results/page … ~2,700 pages". **That page-size figure is a guess and it is wrong.**

`https://www.boe.es/buscar/boe.php` is a plain GET form (read from the form HTML,
req 49). Two of its fields are exactly what discovery needs:

| Field | Meaning |
|---|---|
| `campo[0]=ORIS` + `dato[0][1..5,T]` | **section filter** — the same I / II / III / IV / V / TC axis `sumario.py` filters on |
| `campo[6]=FPU` + `dato[6][0]`, `dato[6][1]` | **publication-date range** (`yyyy-mm-dd`; the form itself declares `min="1960-01-01"`) |
| `page_hits` | **50 / 200 / 500 / 1000 / 2000** — the select's own options |

**It enumerates.** With `page_hits=2000`:

| Request | Result |
|---|---|
| req 54 — section I, 1979-01-01…2026-09-03, `page_hits=2000` | `Resultados 1 a 2.000 de 78.908`, **2,000 distinct ids**, 1,949,297 B, 2.08 s |
| req 55 — same search, `id_busqueda=<token>,,-2000-2000` | `2.001 a 4.000 de 78.908`, 2,000 distinct ids, **0 overlap with page 1** |
| req 56 — `,,-78000-2000` (deep tail) | `78.001 a 78.908 de 78.908`, **908 ids**, oldest `BOE-A-1979-9` |

Page 1 ends `BOE-A-2025-721`, page 2 begins `BOE-A-2025-722` — contiguous, no gap,
no duplicate. The pager is `accion=Mas&id_busqueda=<token>,,-<offset>-<pagesize>`,
and the result page renders a direct link to offset 78000, so deep offsets are a
first-class navigation, not a trick.

`robots.txt` does **not** ban this. Its 3,430 `/buscar` entries are all per-document
(`/buscar/doc.php?id=…`, `/buscar/act.php?id=…`); there is no bare
`Disallow: /buscar` and no `Crawl-delay` (checked offline against the 487 KB file
the other probe already captured).

**Cost, measured not guessed:**

| Discovery of the non-consolidated corpus | Requests | Bytes | Wall @1 req/s |
|---|---|---|---|
| Probe's design — daily summary sweep, 1979→today | **14,926** | **2.03 GB** | 4.1 h |
| Search index, section I (40 pages) + section T (6 pages) | **46** | **~90 MB** | **~1 min** |
| **Ratio** | **325× fewer** | **23× fewer** | — |

### 2. REFUTED — the population is 26 % smaller, and it is knowable exactly

The same endpoint **counts**, so the probe's extrapolation is unnecessary.

**Validation first.** For my contiguous window 1998-12-22…1999-01-04 the search
reports **87** section-I documents (req 51). My own lxml parse of the 12 summaries
I fetched for that window counts **87** items under `seccion codigo="1"`. Exact
match — the search index is a faithful census of the diary, on the one window where
I hold independent ground truth.

| Scope | Probe (EXTRAPOLATED) | Mine (EXACT) | Error |
|---|---|---|---|
| Section I + T, 1979-01-01…2026-09-03 | 121,896 (CI 88,493–155,298) | **90,603** (78,908 + 11,695) | **+34.5 %** |
| Section I + T, 1960→today | 167,907 | **123,946** (112,251 + 11,695) | **+35.5 %** |
| Section I only, 1979→today | ~94,531 | **78,908** | +19.8 % |
| Section III, 1979→today ("roughly quadruple the corpus") | not measured | **540,307** | — |

The probe's point estimate is outside no confidence interval — 90,603 sits inside
its ±33,400 bracket — but a wide interval you do not need is not a defence when the
exact number costs one request. Requests 50, 52, 57, 58, 59, 62.

**Consequences for the two numbers the sharding decision is sized against:**

| | Probe | Mine |
|---|---|---|
| New non-consolidated files (1979 floor) | ~110,200 | **78,890** = 90,603 − 11,713 consolidated |
| Repo after the republish | "roughly **122,000** … a **10×** multiplication" | **91,189 files — 7.4×** |
| Repo at the 1960 floor | 167,907 + 12,299 ≈ 180,000 | **124,105** |

### 3. REFUTED — "the cost" is the cost of discovery, not of the feature

The probe's headline is "#66 … costing 14,926 requests / 2.0 GB / ~1 h", and its
§5.4 table is titled **Total request cost** while its rows say "discovery only".
Whoever reads the headline will size a 1-hour job. Recomputed from first
principles — one diary XML per act is unavoidable, because the API surface
(read offline from the saved `api.php`) has **no bulk document endpoint**: BOE
sumario, BORME sumario, `legislacion-consolidada` (+`/id/{id}/…`) and
`datos-auxiliares`, nothing else. The summary's `<sumario_diario>` offers only a
`url_pdf` of the whole issue's *index* — no whole-issue XML.

Measured per-document cost: **29,155 B mean**, 19,784 B median (n=24 diary XMLs:
14 quantile picks across the size range, reqs 33–46, plus 10 uniform-random draws,
seed 20260903, reqs 64–73; range 5,071–109,311 B).

| Bootstrap phase (1979 floor, sections I + T) | Requests | Bytes |
|---|---|---|
| Consolidated discovery | 2 | 16.0 MB (measured) |
| Non-consolidated discovery, via the search index | 46 | ~90 MB (measured, 1.95 MB/page) |
| Consolidated texts — 12,385 × `/id/{id}/texto` | 12,385 | not measured here |
| Non-consolidated documents — 78,890 × `xml.php` | **78,890** | **2.30 GB** (78,890 × 29,155 B) |
| **Total** | **≈ 91,323** | **≥ 2.4 GB** |

| | Probe's headline | Mine |
|---|---|---|
| Requests | 14,928 | **91,323** (**6.1×**) |
| Wall @ 4 req/s | ~1 h | **6.3 h** |
| Wall @ 1 req/s | 4.1 h | **25.4 h** |

At the 1960 floor: 63 discovery + 111,806 documents + 12,385 = **124,256 requests**,
3.26 GB of diary XML, **8.6 h @ 4 req/s**.

So the probe is wrong in **both directions at once**: it over-prices discovery by
325× and under-prices the feature by 6×. The corrected shape of the job is
"46 requests of discovery, then ~91,000 document fetches" — which changes what has
to be resumable. Caching summaries by date (§5.2 of the probe) protects the cheap
half; the expensive half is the per-document fetch, and *that* is what needs the
permanent on-disk cache and the resume point.

### 4. A population no summary sweep can reach — and a sharper floor

The probe bracketed the summary API's first date to "between 1960-08-15 and
1960-09-15". I pinned it:

| Date | Result |
|---|---|
| 1960-08-31 | **404** (req 10) |
| **1960-09-01** | **200**, 34,897 B, `diario numero="210"` (req 9) |
| 1960-09-02, 1960-09-08 | 200 (reqs 12, 11) |

**The floor is exactly 1960-09-01.** And below it there is content:

| Query | Exact count |
|---|---|
| Section I, 1960-01-01…1960-08-31 (req 62) | **2,233** |
| Section I, 1960-09-01…1978-12-31 (req 57) | 31,110 |
| Section I, 1979-01-01…2026-09-03 (req 50) | 78,908 |
| Section I, 1960-01-01…2026-09-03 (req 59) | **112,251** = 2,233 + 31,110 + 78,908 ✓ |

The arithmetic closes to the unit, so the 2,233 are real documents, not an index
artefact — and `xml.php?id=BOE-A-1960-1` returns **200, 2,251 B** (req 63). They
exist, they are fetchable, and **`discover_published` as designed cannot see one of
them**, because every summary in that window 404s. Small population, but it is the
proof that the sweep's reach is bounded by the *summary* archive, not by the *document*
archive — and the search index is bounded by neither.

Two more reach limits, measured:

- **404 is ambiguous.** The body returned for 1960-08-31 (outside coverage) is
  byte-identical, 170 B, to the body returned for a Sunday: `<code>404</code>
  <text>La información solicitada no existe</text>`. A summary sweep cannot tell
  "no issue that day" from "outside the archive" from "the source is down". The
  probe's §5.2 advice to "log the count" is the only defence available; the search
  index needs none, because it returns a total up front.
- **Autonomic norms.** Of 112 section-I items across my 18 sampled days, **2 (1.8 %)
  sit under a comunidad autónoma department** (`COMUNIDAD AUTÓNOMA DE LA RIOJA`),
  against 3,609/12,299 = 29 % of the published repo. And **245 catalogue norms have
  no BOE document number at all** (`BOJA-b` 58, `BOA-d` 44, `BORM-s` 31, `DOGV-r` 30,
  `BOCL-h` 21, `DOGC-f` 20, `BOC-j` 11, `BOIB-i` 8, `BON-n` 6, `DOCM-q`/`BOCT-c`/`DOG-g`/`BOPV-p` 3
  each, `BOCM-m`/`DOE-e` 2 each) — the BOE consolidates them straight from the
  regional gazette. Neither a summary sweep nor the BOE search can reach a
  *non-consolidated* regional norm: the BOE republishes autonomic **leyes** and
  nothing below them. The non-consolidated corpus this design adds is therefore
  ~98 % state law, and the regional half of `es` stays exactly as complete (or as
  incomplete) as the consolidated catalogue makes it.

### 5. Two smaller corrections

- **Section III is not "roughly quadruple".** It is **540,307** documents for
  1979→today (req 58) against 78,908 in section I — **6.8×**, and 6.0× the whole
  section I+T corpus. Total documents, all sections, 1979→today: **2,471,700**
  (req 53). Whatever else that settles, it is now an exact number rather than an
  open question.
- **Section code `1A` was never observed.** Across 18 days spanning 1979→2026 the
  codes seen are `1`, `2A`, `2B`, `3`, `4`, `5`, `5A`, `5B`, `5C`, `6A`, `6B`, `6C`, `T`
  — never `1A`, which `sumario.py::_LEGISLATIVE_SECTIONS` accepts and which the
  search's `ORIS` axis does not offer. `6A/6B/6C` (old-era anuncios) is a family the
  probe's table does not mention. If `1A` is dead, both the constant and any config
  key derived from it are carrying a value nothing produces.

### 6. What I would change in the recommendation

`discover_all` (§5.1) stands as written — 2 requests, `sort` by `identificador`,
dedupe by id. Nothing to add.

`discover_published` (§5.2) should walk **the search index**, not 14,926 summaries:

```
for section in ("1", "T"):
    for year_block in year_windows(start, end):          # keeps each result set walkable
        base = GET /buscar/boe.php?campo[0]=ORIS&dato[0][{section}]={section}
                   &campo[6]=FPU&dato[6][0]={y0}&dato[6][1]={y1}
                   &operador[0]=and&operador[6]=and&page_hits=2000&accion=Buscar
        total, token = parse(base)                        # "Resultados 1 a 2.000 de 78.908"
        for off in range(0, total, 2000):
            yield from ids(GET boe.php?accion=Mas&id_busqueda={token},,-{off}-2000)
```

- **46 requests** for 1979→today against 14,926. Windowing by year is not needed for
  the volume (40 pages walk fine) but it is what makes the walk **resumable** and
  makes `id_busqueda` expiry a non-event: re-issue the base query for the window you
  were in. Only the window's ids are re-read, never the whole corpus.
- It reaches **1960-01-01**, 8 months below the summary archive's floor, at no extra
  cost.
- It gives the **exact total up front**, so the run knows what "complete" means
  before it starts — the summary sweep only learns the count as a by-product after
  4 hours.
- **Keep the summary endpoint for the daily.** One documented, cacheable request per
  day, and it is what `daily.py` already calls. The search is the *bootstrap* index;
  it is not a replacement for the daily.

Two things to be honest about, because they are the only real arguments for the
sweep and I do not think they carry 325×:

1. `/buscar/boe.php` is **HTML and undocumented**, while `/api/boe/sumario/{date}` is
   a documented endpoint with a published spec. A markup change breaks the parser.
   Mitigation is cheap and belongs in the design: assert the parsed page count against
   the `de N` total the page states, and fall back to the summary sweep for any window
   that fails the assertion. The fallback is the probe's design, already costed.
2. `id_busqueda` is an **opaque server-side token of unknown TTL**. I walked it across
   3 requests over ~5 s; I did not test what it does after an hour. Year-windowing
   bounds the blast radius to one window either way.

### Numbers I could not reproduce, in one table

| Probe's claim | Mine | Safe to decide on? |
|---|---|---|
| "The daily summary is the only index. Nothing else enumerates." | `/buscar/boe.php` enumerates section I in **40 requests** | **No** |
| Non-consolidated discovery = **14,926 reqs / 2.03 GB / 1 h @4 rps** | **46 reqs / ~90 MB / ~1 min** | **No** |
| Section I+T 1979→today = **121,896** (EXTRAPOLATED, CI 88,493–155,298) | **90,603** EXACT | **No** |
| 1960 floor = **167,907** | **123,946** EXACT | **No** |
| Repo becomes **~122,000 files, ~10×** | **91,189 files, 7.4×** | **No** |
| "Total request cost … full bootstrap **14,928**" | **≈ 91,323** for the same scope | **No** |
| Summary coverage begins "between 1960-08-15 and 1960-09-15" | Exactly **1960-09-01**; and **2,233** section-I documents below it are unreachable by any summary | Directionally yes, incomplete |
| Section III would "roughly quadruple the corpus" | **540,307** docs = **6.8×** section I | Directionally yes, imprecise |
| Catalogue = 12,385 in 2 requests / 16.0 MB | Identical | **Yes** |
| 11,713 consolidated BOE-A ≥ 1979 | Identical | **Yes** |
| Sundays are not publication days; every non-Sunday is | 0/8 Sundays, 18/18 non-Sundays incl. a contiguous Christmas run | **Yes** |

**HTTP budget used: 73 of 100.** Full log with status, bytes and wall time per
request: `/Users/neli/.claude/jobs/5bf7ddf4/tmp/refute_a2/reqlog.jsonl`.

---

## format — angle 2: the floor is not a year, it is a per-document property

**Verdict: PARTIALLY_REFUTED.** The probe's structural findings survive and get stronger
(the `@class` article tree works back to **1889**). Its **hard floor of 1975 is refuted in
both directions**: I found fully usable, `articulo`-marked XML in every year from 1889 to
1974, and I found empty `<texto/>` on Sección-I *Reales Decretos* in **1981** and **1984**.
The 1975 boundary is a sampling artefact. Text availability before 1975 is a property of the
individual document, not of the year, and it does not reach 100 % even in the 1980s.

### 1. My sample — deliberately disjoint from the probe's

The probe drew its floor evidence from **sumario days** and took the *leading* Sección-I acts
of each. That method can only ever see one stratum. I attacked from the opposite end.

| Stratum | n | What | Overlap with probe |
|---|---:|---|---|
| A. Pre-1975 **consolidated** norms | 20 | `xml.php?id=` for norms drawn from the consolidated catalogue, 1889–1974, mixed rango (Ley, Decreto, Orden, Real Decreto) | **zero** — the probe fetched no consolidated-catalogue id below 1978 |
| B. Pre-1975 **non-consolidated**, same-day controls | 12 | Sección-I acts sharing a gazette day with a stratum-A norm | zero |
| C. **Complete-day** Sección-I census | 4 days | *every* Sección-I item of 1970-04-06 (14), 1979-06-19 (6), 1981-10-20 (8), 1984-06-19 (12) | zero |
| D. Post-floor mid-year sweep | 7 days | 1975-10-14, 1976-06-15, 1977-10-18, 1979-06-19, 1981-10-20, 1984-06-19, 1988-10-18 | zero — the probe used early-January days |
| E. Official-HTML cross-check | 3 | `txt.php?id=` on three documents whose XML is empty | zero |

Stratum-A ids: `BOE-A-1889-4763`, `-1955-10410`, `-1957-7537`, `-1960-10906`, `-1962-13415`,
`-1964-7544`, `-1966-3501`, `-1967-5590`, `-1968-444`, `-1968-963`, `-1969-797`, `-1970-369`,
`-1970-527`, `-1971-1196`, `-1972-1093`, `-1972-1176`, `-1973-1018`, `-1973-126`,
`-1974-289`, `-1974-204`.

Sumario days fetched: 1968-04-06, 1970-04-06, 1973-07-24, 1975-10-14, 1976-06-15,
1977-10-18, 1979-06-19, 1981-10-20, 1984-06-19, 1988-10-18, 2000-06-15, 2015-10-15.

**93 HTTP requests**, ≥0.85 s apart, UA `legalize-bot/1.0`, no 429 and no 5xx. Raw XML kept
in a private directory (`refute_fmt2/raw/`), not the shared scratch that was cleared under
the probe.

### 2. Direction 1 — usable XML *below* the floor

| Measurement | Probe | Mine |
|---|---|---|
| Populated `<texto>` before 1975 | "**none does** (6 of 6 empty across 1968–1972)" | **20 of 20 populated**, 1889–1974 (Wilson 95 % CI 84–100 %) |
| Earliest usable document | 1975-01-07 | **`BOE-A-1889-4763`** (Código Civil): 639,684 chars, 5,954 `<p>`, **1,992 `<p class="articulo">`** |
| Smallest / largest in stratum A | — | 3,011 chars (`BOE-A-1971-1196`) / 639,684 chars |
| Docs with a recoverable article tree | — | **20 of 20** have `class="articulo"` > 0 |

Rich content is there too, below the floor: `BOE-A-1968-963` carries 2 `<table>` / 27 `<tr>` /
52 `<td>` and 11 `<img>`; `BOE-A-1970-527` carries 4 `<table>` / 197 `<td>` and 6 `<sup>`.
The class census over stratum A is the *same vocabulary* the probe found in the modern
sample — `parrafo` 5,594, `articulo` 2,868, `parrafo_2` 714, `capitulo_tit/num` 206/205,
`titulo_tit/num` 89/86, `libro_num/tit` 11/8, `firma_ministro` 24, `firma_rey` 15,
`cabeza_tabla`/`cuerpo_tabla_*` 229. **No legacy uppercase class family appears anywhere
below 1975.** The 1889 Código Civil parses with exactly the classes a 2026 act uses.

Stratum B kills the "it is only the consolidated ones" escape hatch. On the *same gazette
day*, in the *same section*, some non-consolidated acts have text and some do not:

| Day | Populated / Sección I | Populated examples (non-consolidated) |
|---|---|---|
| 1968-04-06 | (picks) 1 of 4 | `BOE-A-1968-436` Ley 1/1968 — 3,943 chars, 4 `articulo` |
| **1970-04-06** | **5 of 14 (complete day)** | `-1970-374` 6,131 ch · `-1970-375` 4,265 ch · `-1970-381` 413 ch · `-1970-382` 473 ch |
| 1973-07-24 | (picks) 3 of 4 | `-1973-1012` 17,792 ch · `-1973-1016` 5,207 ch · `-1973-1021` 2,292 ch |

Excluding the one consolidated norm, **4 of 13** non-consolidated Sección-I acts on
1970-04-06 have text (30.8 %, CI 13–58 %). The probe's "0 of 3 in 1970" came from picking
three ids that happened to be in the 9-of-14 that are empty.

The empties do not follow rango: 6 of 13 `Ley` are empty and 7 populated; all 5 `Decreto`
sampled are empty; all 3 `Corrección de errores` are populated. The empty 1970 Leyes are
créditos extraordinarios and Cuentas Generales del Estado — table-heavy budget instruments.
That is a *plausible* selection criterion (dense tabular matter was skipped by the
retro-digitisation), but I did not test it and it is **inference, not measurement**.

### 3. Direction 2 — unusable XML *above* the floor

Two Sección-I **Reales Decretos**, nine and six years past the claimed floor, return a
literal empty `<texto/>`:

| id | Gazette day | Rango | Chars | Title tail |
|---|---|---|---:|---|
| `BOE-A-1981-50082` | 1981-10-20 | Real Decreto | **0** | RD 2330/1981 … Concierto Económico País Vasco: **(Conclusión.)** |
| `BOE-A-1984-50024` | 1984-06-19 | Real Decreto | **0** | RD 1129/1984 … traspaso … Andalucía **(Continuación.)** |
| `BOE-A-1976-49965` | 1976-06-15 | Resolución | **0** | (Sección II, found by the same id-band scan) |

Complete-day Sección-I rates, post-floor, measured on *every* item of the day:

| Day | Populated / total | 95 % CI |
|---|---|---|
| 1975-10-14 | 4 / 4 | 51–100 % |
| 1976-06-15 | 3 / 3 | 44–100 % |
| 1979-06-19 | **6 / 6** | 61–100 % |
| 1981-10-20 | **7 / 8** | 53–98 % |
| 1984-06-19 | **11 / 12** | 65–99 % |
| 1988-10-18 | 3 / 3 | 44–100 % |
| **pooled 1975–1988** | **34 / 36 = 94.4 %** | **82–98 %** |

So the post-floor population rate is **94 %, not 100 %** — the probe's 30/30 and 16/16 were
real but under-powered, and both of my misses land in the years its sample skipped.

**These two are a distinct, nameable failure class, not noise.** Both ids sit in a separate
id band (`5xxxx`) while their same-day neighbours run 24241–24247 and 13857–13867, and both
titles end in `(Conclusión.)` / `(Continuación.)`. They are the **tail fragments of an act
published across several gazette issues**: the head carries the text, the continuation ids
carry none. Neither is in the consolidated catalogue, so both are exactly the kind of act
issue #66 wants to add. Across my 10 pre-2000 sumario days, `5xxxx`-band ids appear on 2 of
7 post-1975 days; 15 such ids exist in the whole consolidated catalogue.

**The absence is real, not an XML-surface defect.** `txt.php` (the official HTML view) for
`BOE-A-1968-440`, `BOE-A-1981-50082` and `BOE-A-1984-50024` returns 200 with 1,800–2,908
visible characters — page chrome, title, and a PDF link, no body. The text does not exist on
any HTML surface; only the PDF has it. The probe's sub-claim that there is **no intermediate
"scanned-image body" state** is **CONFIRMED**: across 93 documents I saw no `<img>`-only body
and no stub — the shortest populated body was a 413-char corrección de errores, which is
genuinely 413 characters long.

### 4. What the probe actually detected at 1974/1975

There *is* a discontinuity there, but it is in the **document universe**, not in text
availability. Measured from the sumarios and the consolidated catalogue:

- Pre-1975 gazette days carry **two id spaces at once**. On 1968-04-06 the 91 items have a
  median id of **36,912** while the Sección-I disposiciones generales are numbered 436–445.
  On 1970-04-06: median 37,325, Sección I 369–382. On 1973-07-24: median 43,759, Sección I
  1012–1026.
- The low per-year sequence tops out at **`BOE-A-1974-2058`** (25 Dec 1974) and jumps to
  **`BOE-A-1975-26928`** (31 Dec 1975) — a **13×** step in one year.
- From 1975-10-14 onward every sampled day's ids sit in a single contiguous annual band
  (out-of-band rate 0 on 1975, 1977, 1979, 1981, 1988, 2000-06-15 and 2015-10-15; 1 stray on
  1976-06-15 and 1984-06-19).

Reading: before 1975 the BOE retro-loaded a **selected** ~2,000 acts/year into a low id
sequence and dumped the rest into a high block; from 1975 the annual sequence *is* the whole
gazette. That is why a sumario-driven sample sees a cliff. (The id-space observation is
measured; the "retro-load" explanation is inference.)

### 5. The recommendation is operationally dangerous as written

The probe recommends a **hard floor at 1975-01-01** put "in `config.yaml`, not in the
fetcher", as a **discovery** floor. Measured against the published corpus at `origin/main`:

- `countries/es/es/` holds **286 files dated before 1975**, back to **1835**
  (`ls es/*.md | sed -E 's#.*BOE-A-([0-9]{4})-.*#\1#' | awk '$1<1975' | wc -l`), out of 8,690.
- They are not stubs: `es/BOE-A-1889-4763.md` is **1,068,917 bytes with 2,441 headings**;
  `es/BOE-A-1970-369.md` is 78,954 bytes / 72 headings; even `es/BOE-A-1835-2348.md` has
  3,272 bytes / 3 headings.

A discovery floor at 1975 applied to the re-emission would **drop 286 published laws
including the Código Civil and the Ley Hipotecaria**. The floor, if one is wanted at all,
belongs on the *non-consolidated* discovery path only, and even there it is the wrong shape:
the correct rule is **"skip the document when `<texto>` is empty"**, which is free (you have
already fetched the document), exact, and correct in 1889 and in 1984 alike.

### 6. Numbers side by side

| Probe's number | My result | Reproduced? |
|---|---|---|
| Floor = **1975**; 0/6 populated 1968–1972 | 20/20 populated 1889–1974; 4/13 non-consolidated populated on one 1970 day | **NO — refuted** |
| 16/16 populated 1975–1980 | 13/13 populated on my 1975/1976/1979 days | **YES** |
| "30/30 populated 1982→2026" | 34/36 pooled 1975–1988 (94.4 %); 2 empties in 1981 and 1984 | **NO — refuted** |
| "No intermediate scanned-image body state" | 0 `<img>`-only bodies, 0 stubs in 93 documents | **YES** |
| Article tree recoverable from `@class` | 20/20 pre-1975 docs have `class="articulo"`; 1889 Código Civil has 1,992 | **YES, and extended 86 years earlier** |
| Legacy uppercase `@class` family is rare | 0 occurrences anywhere below 1975 | consistent |
| 1974 is "not a clean cut" | Correct, but so is every year — the cut is per-document | partially |

### 7. What I did not test

- **Per-year completeness 1985–2015.** My post-floor evidence stops at 1988; the two modern
  sumarios (2000, 2015) were only scanned for id bands, no documents fetched. The 94.4 %
  pooled figure must not be read as a modern rate.
- **Why a given pre-1975 document is empty.** The table-heavy-budget-instrument pattern is a
  hypothesis from 13 documents on one day.
- **The `(Continuación.)` class frequency.** I have 2 confirmed instances and an id-band
  heuristic; how many multi-issue acts exist corpus-wide is unmeasured, and it is the number
  that decides whether issue #66 needs a head/continuation stitcher.
- Nothing in the probe's §1/§2 (rendering identity, tables, captions, indentation defect) —
  a different angle owns those.

---

## discovery — angle 3: the index the probe never looked for is published, standards-based, and 3 requests wide

**Verdict: PARTIALLY_REFUTED.** The consolidated half (#99) stands. The
non-consolidated half (#66) does not: the probe's central claim — *"The daily summary is the
only index. Nothing else enumerates."* — is wrong, and the two headline numbers that follow
from it (14,926 requests / 2.03 GB; ~122,000 files) are wrong with it. The BOE publishes a
**sitemap index of the whole ELI corpus** and an **Atom update feed**, both linked from its
own ELI page. Together they enumerate **103,070 norms in 3 requests / 11.6 MB / ~3 s**,
against the probe's 14,926 requests / 2.03 GB / 1 h. Separately, the BOE's diary search
returns **exact** section-I population counts, which replace the probe's ±33,400
extrapolation and cut it by a third.

**Budget: 60 requests to `www.boe.es`**, 2026-09-03, single-threaded, 0.8 s apart,
`User-Agent: legalize-bot/1.0 (+https://github.com/legalize-dev/legalize)`. No 429, no 5xx.
26.2 MB transferred. Raw captures and scripts: `/Users/neli/.claude/jobs/5bf7ddf4/tmp/a3/`
(`h.py`, `b1.py`…`b12.py`, `log.jsonl`, `eli_sitemap{0,1,2}.xml`, `eli_urls.json`,
`s_*.html`, `y{1985,2000,2014}.html`, `headtohead.json`).

### 1. How the probe missed it

The probe tested `https://www.boe.es/sitemap.xml` (404), grepped `robots.txt` for a
`Sitemap:` directive (absent), and concluded there is no sitemap. Both observations are
correct; the conclusion is not. The sitemap is not at the site root and is not advertised in
`robots.txt` — it is at **`/eli/sitemap.xml`**, and it is linked, in prose, from
**`/legislacion/eli.php`**, a page the probe never fetched. That page is reachable in two
clicks from `/buscar/` ("Información → Identificador Europeo de Legislación").

The same page links the second thing the probe missed: **`/eli/eli-update-feed.atom`**.

| The probe wrote | What I measured | req |
|---|---|---|
| `sitemap.xml` → 404, no `Sitemap:` in robots.txt, "nothing else enumerates" | `/eli/sitemap.xml` → **200**, a `<sitemapindex>` of 3 sitemaps | 51 |
| — (never tested) | `/eli/sitemap{0,1,2}.xml` → **50,000 + 50,000 + 3,070 = 103,070 distinct `<loc>`**, every one with a `<lastmod>` | 53–55 |
| — (never tested) | `/eli/eli-update-feed.atom` → **200**, 725 entries, rolling window **2026-07-06 → 2026-09-02** | 52 |
| "ELI … resolves a *known* act to HTML but indexes nothing" | `/eli/{uri}/dof/spa/xml` returns the **diary XML**, not HTML: `…/es/l/2014/11/27/28/dof/spa/xml` → 200, **263,932 B `application/xml`** — byte-for-byte the size the probe got from `xml.php?id=BOE-A-2014-12329` | 11 |
| — (never tested) | `/buscar/boe.php` — the diary search — filters by section and date and reports **exact** result totals, 2,000 rows/page, arbitrary-offset deep paging | 17–45 |

Also missed, and relevant to how far back the corpus can go: **`/buscar/gazeta.php`** — the
historical collection, form-declared range **1661-01-01 … 1959-12-31**, holding
**1,496,594 documents** (req 46). The probe priced a "1960 floor" option at 20,560 summary
requests; the actual pre-1960 population is a different database of 1.5 M documents with no
section filter, which is not the same offer at all.

### 2. My sample and method (deliberately different)

The probe sampled **30 publication days** and multiplied. I did not sample days at all. Three
independent routes, none of which the probe used:

1. **Read the site's own navigation**, not just `/datosabiertos/`: `/buscar/` →
   `/legislacion/eli.php` → the sitemap and Atom links; `/informacion/mapa_web/` for the full
   service list; `/rss/` for the feeds. (reqs 1–16)
2. **The diary search as a counting oracle.** `/buscar/boe.php` with
   `campo[0]=ORIS`, section checkboxes `dato[0][1]=1` / `dato[0][T]=T`, `campo[6]=FPU` and an
   ISO date range. It prints `Resultados 1 a N de M`. `M` is the whole-population count for
   that filter — no sampling, no extrapolation. (reqs 17–45)
3. **Offline set arithmetic** against the probe's own 12,385-item `catalog_all.json` and
   against the 103,070 sitemap URIs — zero further requests.

Validation before I trusted (2), because a search index that silently drops rows would be
worthless:

- **Head-to-head against the summary API on 3 days I picked, not the probe's**:
  **1979-03-15**, **2000-06-20**, **2025-04-15**. Parsed each `/api/boe/sumario/{date}` with
  lxml, took every `<item>` under a `seccion` whose code starts with `1` or equals `T`, and
  set-diffed against the search's ids for the same day. **6 vs 6, 20 vs 20, 5 vs 5 — zero
  items on either side only.** (reqs 25–30, `headtohead.json`)
- **Additivity**: seven decade queries sum to 17,903 + 17,374 + 23,513 + 20,675 + 18,105 +
  16,481 + 9,895 = **123,946**, which is exactly the whole-range total from a separate
  request. (reqs 20, 34–40)
- **Paging integrity**: page 1 (offset 0) and page 2 (offset 2,000) at 2,000 rows share
  **0 ids**, and the header reads `Resultados 2.001 a 4.000 de 123.946`. A jump straight to
  offset 122,000 returns `Resultados 122.001 a 123.946` — deep paging works in one hop, no
  sequential walk. (reqs 23, 24, 45)

One nuisance worth recording: `/datosabiertos/api/boe/sumario/{date}` **400s unless you send
an explicit `Accept`** — `<text>No soportado ningún mime type de la cabecera Accept.</text>`
(req 19). `requests`' default `*/*` is not enough. Not a coverage hole; a client requirement.

### 3. The numbers, next to the probe's

#### 3.1 Population size — measured, not extrapolated

| Population | Probe (EXTRAPOLATED, 30 days × 14,926) | Mine (exact count from the search) | Δ | req |
|---|---|---|---|---|
| Section **I + T**, 1979-01-01 → 2026-09-03 | **121,896** (CI 88,493–155,298) | **90,603** | probe **+34.5 %** | 22 |
| Section **I only**, 1979 → today | **94,531** (CI 76,118–112,945) | **78,908** | probe **+19.8 %** | 33 |
| Section **I + T**, 1960-01-01 → today | 167,907 (for a 1960-09 floor) | **123,946** | probe **+35.5 %** | 20 |
| Section **I only**, 1960 → today | — | **112,251** | — | 21 |
| Consolidated `BOE-A` with `fecha_publicacion ≥ 1979` | 11,713 | **11,713** ✔ reproduced offline from `catalog_all.json` | 0 | — |
| ⇒ **non-consolidated** section I+T since 1979 | ≈ 110,200 | **≈ 78,890** | probe **+40 %** | — |
| ⇒ **resulting repo** | "roughly **122,000**, a 10× multiplication" | **≈ 91,000, a 7.4× multiplication** | probe **+34 %** | — |

The probe's point estimate sits 34 % above the truth and its interval only just contains it
(90,603 vs a CI floor of 88,493). Its own caveat — *"treat 122K ± 33K as the honest bracket"* —
was right to be nervous. It is not the bracket that matters, though: **the exact number is one
HTTP request away**, so no bracket was ever needed.

An independent corroboration of 90,603 that costs nothing: `/legislacion/eli.php` states, in
BOE's own prose, that ELI has been applied since December 2018 and *"ya se cuenta con **más de
90.000 normas** identificadas y descritas con arreglo al estándar europeo"*, to state
legislation published in the BOE **from 29/12/1978** (req 15). Two unrelated sources, one
measured and one editorial, land on the same 90 K.

#### 3.2 Cost of enumerating the non-consolidated population

| Strategy | Requests | Bytes | Wall @ 1 req/s | Gives you |
|---|---|---|---|---|
| Probe: sweep every daily summary 1979→today | **14,926** | **2.03 GB** (est.) | 4.1 h | id, title, section, per day |
| **ELI sitemap** (`/eli/sitemap.xml` + 3 files) | **4** | **11.58 MB** (measured: 5,622,260 + 5,617,858 + 342,829 + 477) | **~4 s** | 103,070 resolvable ELI URIs + `lastmod` |
| Diary search, section I+T, 2,000/page | **63** (⌈123,946/2000⌉ + 1) | **~110 MB** (measured mean 1.73 MB/page over 5 full pages) | ~2 min | id, date, BOE issue no., section label, department, **full title** |
| Daily increment: Atom feed | **1** | 187 KB | <1 s | everything changed in the last ~8 weeks |
| Daily increment: `/rss/boe.php?s=1` | **1** | **5,223 B**, 6 items | <1 s | today's section-I ids |

That is **3,700× fewer requests and 175× fewer bytes** than the design the probe recommends,
for the same discovery job. The probe's §5.2 `discover_published` diary sweep — the expensive
half of its whole artefact — should not be built.

#### 3.3 What each index actually contains (they are not the same population)

| | Section I+T search | ELI sitemap |
|---|---|---|
| Size | 123,946 (1960→today) | **103,070** URIs |
| Of which corrections | not separable | **8,920** `…/corrigendum/{date}` entries |
| Base norms | — | **94,150** |
| Date range | 1960-01-01 → today (form-declared floor) | **1851** → 2026 (first entry `/eli/es/rd/1851/10/24/(1)`); 1,126 pre-1979 |
| Jurisdictions | BOE only | **18**: `es` (93,172) + `es-ct` 1,239, `es-nc` 1,188, `es-vc` 614, `es-ib` 610, `es-pv` 599, `es-ar` 589, `es-cn` 570, `es-md` 565, `es-ga` 519, `es-an` 488, `es-cl` 460, `es-ex` 449, `es-mc` 435, `es-cm` 422, `es-cb` 400, `es-as` 388, `es-ri` 363 |
| Court rulings | **included** — Tribunal Constitucional/Supremo are **13.6 % (1985), 26.0 % (2000), 26.7 % (2014)** of rows | **excluded** (sentencias are not norms) |
| Section III normative orders/resolutions | excluded | **included** — top types are `res` 32,282 and `o` 28,418 |

Do the two agree where they overlap? Measured offline, no requests: I rebuilt the ELI URI
suffix `{type}/{year}/{month}/{day}/{number}` from the **titles** of every numbered
disposition in the 1985, 2000 and 2014 search dumps and tested membership in the 103,070-URI
set. **1,517 of 1,582 = 95.9 %** (96.4 % / 97.9 % / 93.2 % per year). Every one of the
residual misses I inspected is a `Ley Foral` — ELI type `lf`, which my title parser mapped to
`l`. Real agreement is ~99 %; the 4 % is my regex, not the BOE's.

And the URIs resolve. Five picked to be awkward — a Galician autonomic law, an 1870
corrigendum, a 1998 Orden, and two at random (seed 20260903) — **5/5 returned 200
`application/xml`** with the four expected children (`metadatos`, `metadata-eli`, `analisis`,
`texto`) and a `<identificador>` giving the BOE id: `BOE-A-1982-25035`, `BOE-A-1870-4837`,
`BOE-A-1998-366`, `BOE-A-2026-9197`, `BOE-A-2007-187` (reqs 56–60). The ELI URI → BOE id
mapping therefore costs nothing extra: it falls out of the fetch you have to do anyway.

#### 3.4 Reach: the 1960 floor is the API's, not the source's

| Claim | Probe | Mine |
|---|---|---|
| Earliest summary | coverage begins between 1960-08-15 and 1960-09-15 | **Confirmed for that endpoint**: `/api/boe/sumario/19600315` → 404 (req 32) |
| Earliest *source* | "the API reaches ~19 years further back than the 1979 floor" | The **search** returns 7 section-I ids for **1960-03-15** (`BOE-A-1960-3805/3806/3872/3880/3881/3882/3883`, req 31) where that API 404s; the search form declares a 1960-01-01 floor; **Gazeta** (`/buscar/gazeta.php`) declares 1661-01-01…1959-12-31 and reports **1,496,594** documents (req 46); and the ELI sitemap's oldest entry is **1851** |

So "coverage begins 1960-09" is a fact about one endpoint that the probe generalised into a
fact about the BOE. Three other surfaces reach further back.

#### 3.5 What I confirmed

- **11,713** consolidated `BOE-A` norms published ≥ 1979 — recomputed from the probe's own
  dump, exact match. (Also: 12,140 `BOE-A` of 12,385 total; 86 published before 1960; oldest
  `fecha_publicacion` 1835-11-07.)
- **No compression on the wire.** `Content-Encoding` empty on the 5.6 MB sitemaps, the Atom
  feed and every search page, with `requests` advertising gzip. The probe's byte figures are
  transfer figures. Confirmed on a completely different set of endpoints.
- **The summary API's per-day content is sound** — its section-I item set is identical to the
  search's on all 3 days I tested. The probe's counting method was fine; only the
  extrapolation on top of it was not.
- **`robots.txt` does not restrict either surface.** Of its 3,431 `Disallow` lines mentioning
  `/buscar`, every one is a language-variant query string (`Disallow: /buscar/doc.php?*lang=ca`
  and siblings). Nothing disallows `/eli`, `/eli/sitemap.xml`, or `/buscar/boe.php` without a
  `lang` parameter. Checked offline against the probe's own capture of the file.

### 4. What this does to the recommended design

The probe's §5.1 (consolidated catalogue in 2 requests) is untouched — I did not retest it and
have no reason to doubt it. Its §5.2 should be replaced:

| | Probe's `discover_published` | Replacement |
|---|---|---|
| Bootstrap index | 14,926 summary requests, 2.03 GB, resumable by date cursor | **4 requests**: `/eli/sitemap.xml` then the 3 `sitemapN.xml`. 11.6 MB. Resumability is trivial — it is 4 files, re-fetch them |
| Daily index | 1 summary request/day | **1 request**: `/eli/eli-update-feed.atom`, filtered on `<updated>`. A ~8-week rolling window means a missed cron for a month is self-healing — the probe's design has no such margin |
| Fetch | `xml.php?id={id}` | `{eli_uri}/dof/spa/xml` — same document, and the URI is what the index gives you. Mean **72 KB** over the 6 documents I fetched (10,611 / 8,071 / 19,898 / 27,969 / 102,453 / 263,932 B) |
| Shard key | to be decided | **already in the URI**: the jurisdiction segment gives `es` + 17 `es-*` codes, which is exactly the `es/` + 17 `es-*/` directory split the repo already has |
| Change detection | none — the sweep re-reads everything | `<lastmod>` on **all 103,070** entries |

Two things the sitemap does **not** give you, both of which the search does, and which is why
I would keep `/buscar/boe.php` as a secondary oracle rather than the primary index:

1. **Court rulings have no ELI.** 26.7 % of 2014's section-I+T rows are Tribunal
   Constitucional or Supremo. If the corpus is meant to include them, ELI alone misses them
   and the section-I search is the only index that has them.
2. **Freshness lag.** The sitemap index's `lastmod` was **2026-09-01** and `sitemap2`'s newest
   entry is `2026-08-05`; the Atom feed already carried 9 URIs absent from it. The sitemap is
   rebuilt on a cadence (looks monthly); the feed is live. Bootstrap from the sitemap, keep
   current from the feed, and never trust the sitemap for the last few weeks.

One caveat I will not paper over: `/buscar/boe.php` is HTML, undocumented, and its result
markup can change under us. **`/eli/sitemap.xml` is not** — it is a sitemaps.org document
declared in a `dct:relation` alongside the Atom feed, generated by the BOE for exactly this
purpose, and documented on `/legislacion/eli.php`. My primary recommendation rests on the
documented surface; the search is used for counting and for the court-ruling gap.

### 5. A historical-section quirk anyone building this will hit

Filtering `dato[0][1]=1` in 1985 returns rows labelled **"V. Comunidades Autónomas"** (178 of
2,000) alongside "I. Disposiciones generales" (1,703) and the TC supplement (119). The BOE's
section coding is not stable across eras, so "section I" in 2014 and "section I" in 1985 are
not the same set. The 123,946 figure includes those historical section-V rows. My three
head-to-head days (1979, 2000, 2025) all matched the summary API exactly, so this is a
labelling artefact rather than a filter leak — but a sweep that assumes a fixed section
vocabulary will mis-classify the 1980s.

### 6. What I did not test

- **The consolidated side (#99).** Out of my angle. The probe's 12,385 / 2-request result is
  unchallenged here; the only piece I touched was recomputing 11,713 from its dump.
- **Whether the ELI corpus is a strict superset of what the repo should hold.** I measured
  95.9 % title-level agreement on 1,582 numbered dispositions from 3 years, and the residue
  was my parser. I did not resolve all 103,070 URIs, so I cannot state a per-id recall.
- **`id_busqueda` token lifetime.** It survived being reused across a 6-request gap with an
  arbitrary offset. I did not test it across minutes or from a different IP. If it expires,
  the cost of recovery is one request (re-issue page 1, take the new token).
- **The Gazeta collection's machine surface.** I measured its size (1,496,594) and its
  declared range; I did not test whether its documents have XML endpoints.
- **`elidata.es`.** `/legislacion/eli.php` points at it for the controlled vocabularies
  (`/mdr/authority/{jurisdiction,type,version,language}/`) and the technical specification. It
  is a different host and outside this budget, but it is where the type vocabulary that the
  URIs use is published, and a fetcher that parses ELI URIs will want it.

### 7. Cross-reference — the counts replicate across two independent verifiers

The *discovery — angle 2* section above was written without sight of this one, from a
different query construction and a different request log, and lands on **78,908 / 90,603 /
112,251 / 91,189 files** — identical to every figure in §3.1 here, to the digit. Two agents,
two samples, one number. The corrected population is not a judgement call: **the probe's
121,896 is wrong and 90,603 is right.**

Where the two diverge is the remedy. Angle 2 recommends the diary search at **40–46
requests**. That is already 325× better than the probe, but it is HTML scraping of an
undocumented surface. **`/eli/sitemap.xml` does the same job in 4 requests off a
sitemaps.org-conformant document the BOE publishes and documents for this exact purpose**,
carries `lastmod` for change detection and a jurisdiction segment that matches the repo's
existing shard layout, and comes with a live Atom companion for the daily run. Neither of the
other two discovery sections mentions it. Use the sitemap as the index; keep the search for
the two things ELI does not cover — court rulings, and an exact section-I census.

---

## format — angle 3: the class vocabulary is not one vocabulary

**Verdict: PARTIALLY_REFUTED.** The probe's *rendering* claims reproduce (0 residual tags, 0
mojibake, 0 `<a>`, strip-classes always inside table cells). Its *structure* claim does not.
"A parser recovers the article tree from `@class` alone. No regex fallback is needed" is
false on a sample built to be different from the probe's, and it is false in three
independent ways, two of which the probe never looked for because it counted classes and
never read the text inside them.

### My sample — deliberately different from S38

The probe took **one gazette day per year** and 4 consecutive Sección-I acts off each day.
A day is one typesetting batch, which is exactly why its own caveat says rare templates are
under-represented. I inverted every axis of that design:

| | probe S38 | mine (S40 + E20 = **60 docs**) |
|---|---|---|
| how ids were chosen | leading Sección-I acts of one gazette day per year | stratified from the consolidated catalogue by decade × rango × departamento |
| distinct gazette days | 10 | **60** (one act per day, enforced) |
| distinct departments | not stated; ≤10 days' worth | **~50** (max 2 acts per department) |
| ámbito | Estatal only | 30 Estatal + 10 Autonómico (S40); E20 adds 8 more autonomic |
| gazette of origin | BOE only | BOE + `BORM-s-…`, `DOGC-f-…`, `BOIB-i-…` ids |
| dual-surface acts | 8 consolidated fetches, 5 of them 404 | **10 acts fetched on BOTH surfaces, 10/10 succeeded** |
| paragraphs censused | 11,845 | **31,899** (S40 alone) |

**S40** (40 acts, 40 different gazette days, 35 departments, 1882→2026):

```
BOE-A-1882-6036  BOE-A-1889-4763  BOE-A-1955-4699  BOE-A-1969-359   BOE-A-1978-11099
BOE-A-1978-31229 BOE-A-1979-23709 BOE-A-1979-27761 BOE-A-1980-18583 BOE-A-1980-23778
BOE-A-1981-6683  BOE-A-1984-1552  BOE-A-1985-18239 BOE-A-1987-11921 BOE-A-1990-6397
BOE-A-1990-10421 BOE-A-1991-13213 BOE-A-1993-5274  BOE-A-1993-20613 BOE-A-1999-17140
BOE-A-2002-23038 BOE-A-2004-4513  BOE-A-2005-1576  BOE-A-2007-2207  BOE-A-2007-11450
BOE-A-2008-8768  BOE-A-2015-6704  BOE-A-2015-11427 BOE-A-2016-4953  BOE-A-2017-10245
BOE-A-2018-15515 BOE-A-2019-9026  BOE-A-2021-11046 BOE-A-2023-17809 BOE-A-2024-10237
BOE-A-2024-11291 BOE-A-2024-17269 BOE-A-2026-11688 BOE-A-2026-12710 BORM-s-2019-90599
```

**E20** — a targeted 2003–2010 sweep (20 acts, 20 more distinct days, 16 departments) to test
the probe's dismissal of the legacy uppercase class family as "one day in 2005":

```
BOE-A-2003-6588  BOE-A-2003-9260  BOE-A-2003-9510  BOE-A-2004-14532 BOE-A-2004-19752
BOE-A-2006-9958  BOE-A-2007-3825  BOE-A-2007-7115  BOE-A-2007-10411 BOE-A-2007-18193
BOE-A-2008-3527  BOE-A-2008-6804  BOE-A-2008-10206 BOE-A-2008-16387 BOE-A-2008-18499
BOE-A-2009-4211  BOE-A-2010-10828 BOE-A-2010-16131 BOIB-i-2005-90013 DOGC-f-2008-90017
```

**Dual-surface set (10 acts, both `xml.php` and `/texto`):** `BOE-A-1882-6036`,
`BOE-A-1955-4699`, `BOE-A-1978-31229`, `BOE-A-1987-11921`, `BOE-A-1991-13213`,
`BOE-A-2005-1576`, `BOE-A-2007-11450`, `BOE-A-2015-6704`, `BOE-A-2024-10237`,
`BORM-s-2019-90599`.

**Method.** 88 HTTP requests, UA `legalize-bot/1.0 (+https://github.com/legalize-dev/legalize)`,
≥0.8 s apart, no 429 and no 5xx (log: `/Users/neli/.claude/jobs/5bf7ddf4/tmp/refut_fmt3/requests.jsonl`,
87 rows + 1 unlogged diagnostic GET). Offline: lxml census of `@class` **and of the text
inside each `<p>`** (the probe only did the former); a `getparent()` walk for table-cell
membership; then the acts were rendered to Markdown through the engine's own unmodified
dispatch (`_parse_p` / `_table_paragraph` / `_parse_blockquote` / `_image_paragraph` →
`render_paragraphs`) and the output compared, heading for heading, against the same act's
published file in `countries/es` at `origin/main`. Nothing was written outside my scratch
directory and this section.

> **Endpoint correction, worth 14 of my 88 requests.** The brief's
> `https://www.boe.es/api/legislacion-consolidada?limit=…` returns **404**. The working base
> is `https://www.boe.es/datosabiertos/api/…` (as `config.yaml::source.base_url` says), and
> `/texto` returns **400 "No reconocido el formato de la cabecera Accept"** unless the request
> carries `Accept: application/xml`. Also measured: `offset=30000` on the catalogue returns
> an empty `data` — the consolidated catalogue is smaller than 30,000, not merely smaller
> than 100,000.

---

### R1. `class="articulo"` is not "article". It is "numbered unit", and it swallows the disposiciones

219 paragraphs across **25 of 40 S40 documents** whose text begins *Disposición
adicional / transitoria / derogatoria / final* carry `class="articulo"` — the same class as
`Artículo 12`. `markdown.py` maps that class to `######`, so an article and a disposición
final come out at the same depth with nothing to tell them apart. Rendered from the diary
XML, `BOE-A-1991-13213` emits **10 `###### Disposición …` headings** interleaved with its
60 article headings, all H6.

That is not itself new (the consolidated path does the same), but the next two are.

### R2. The heading that says *which* group you are in is unmapped, so it disappears

The group heading — `DISPOSICIONES ADICIONALES`, `DISPOSICIÓN DEROGATORIA` — is carried by
`<p class="capitulo">` (bare, no `_num`/`_tit`). `capitulo` is **not** in
`_SIMPLE_CSS_MAP` nor in `_PAIRED_CLASSES`; only `capitulo_num`/`capitulo_tit` are. It
therefore falls through to a plain paragraph. Measured on the rendered output:

| act | line | what the diary XML renders |
|---|---|---|
| `BOE-A-1978-31229` | 1457 | `[encabezado]DISPOSICIONES ADICIONALES` — **plain paragraph, no `#`** |
| `BOE-A-1987-11921` | 1183 / 1425 / 1429 | `DISPOSICIONES ADICIONALES`, `DISPOSICIÓN DEROGATORIA`, `DISPOSICIONES FINALES` — all plain paragraphs |

Bare `capitulo` appears in **9 of 40** S40 docs (34 paragraphs) and 2 of 20 E20 docs; bare
`libro` in 5 docs, `publicado` in 7, `(none)` in 1.

Combine R1 and R2 and the Constitution comes out of the non-consolidated path with **eight
identically-titled H6 headings**: `###### Primera.` … `###### Cuarta.` for the adicionales
and again for the transitorias, with the group heading that disambiguated them demoted to
body text. The consolidated surface **rewrites that paragraph** — its `<p class="articulo">`
literally reads `Disposición adicional primera.` — which is why the published file has none
of this.

Duplicate H6 heading texts inside one file, diary render vs the published file of the same act:

| act | diary H6 total | duplicated heading texts | headings involved | published file duplicates |
|---|---:|---:|---:|---:|
| `BOE-A-1978-31229` | 182 | 4 | **8** | 0 |
| `BOE-A-1987-11921` | 119 | 7 | **17** | 0 |
| other 8 rendered acts | — | 0 | 0 | 0 |

Anchors are generated from heading text (see `law_anchors_two_forms`), so this is an
anchor-collision generator, not a cosmetic issue.

### R3. Two acts in 60 render with **zero** structure — and the probe called this a one-day artifact

`BOE-A-2007-11450` (Real Decreto 696/2007, Ministerio de la Presidencia) and
`BOE-A-2008-10206` (Ley 3/2008, Illes Balears) use only the legacy uppercase class family:

```
ATEXTO_BLANCO_4  ATEXTO_BLANCO_6  ATEXTO_NORMAL  ATEXTOySIGUIENTE  ATEXTOySIG_BL_6
RBF_SFRANySIG_ARTICULO  RBC_RED_CENTRO  RVD_FIRMA  FIRMA_MINISTRO  CBC_SUBS
```

Not one is in the engine's map (`FIRMA_MINISTRO` misses because the map key is lowercase
`firma_ministro`). **100 % of their paragraphs** fall through to plain text. Rendered:

```
==== BOE-A-2007-11450   14,955 chars, headings: 0
```

Its `Artículo 1. Objeto y Ámbito de aplicación.` is indistinguishable from body prose. The
same act's **published** file `countries/es/es/BOE-A-2007-11450.md` has **10 `######`
headings**, because it came from the consolidated surface, whose `<bloque>` skeleton is
intact: `a1`…`a7`, `daunica`, `dfprimera`, `dfsegunda`.

The probe saw this family in two documents from a single 2005 gazette day and concluded it
was a per-day typesetting batch. It is not: my two hits are **2007 and 2008**, different
days, different issuing bodies (a state ministry and an autonomous parliament), found by a
sampling design that never takes two acts from the same day.

**Rate: 2 of 60 documents = 3.3 %.** EXTRAPOLATED, and stated as an order of magnitude only:
against the ~100k+ non-consolidated acts issue #66 would add, 3.3 % is a few thousand laws
published with no article tree at all. Base = 2/60, multiplier = corpus size. The honest
reading is not "3.3 %" but "the phenomenon is real, era-spanning, and must be instrumented,
not assumed away".

### R4. The diary XML leaks BOE's own block-type sentinels into the text — 150 of them

Not a class, a **literal string prefix inside the paragraph text**. Where the consolidated
XML expresses block type as `<bloque tipo="precepto">`, the diary XML flattens the same
information into the first characters of the paragraph:

```xml
<p class="capitulo">[encabezado]DISPOSICIONES ADICIONALES</p>
<p class="articulo">[precepto]Primera.</p>
<p class="parrafo_2">[ignorar]Artículo 1.º Se aprueba el adjunto proyecto de Código…</p>
```

| sentinel | occurrences | docs (of 60) | carried by classes | example |
|---|---:|---:|---|---|
| `[precepto]` | 89 | 8 | `articulo` | `BOE-A-1882-6036` → `[precepto]Art. 384 bis.` |
| `[encabezado]` | 41 | 9 | `capitulo`, `subseccion`, `libro`, `centro_redonda`, `seccion`, `capitulo_tit` | `BOE-A-1889-4763` → `[encabezado]CÓDIGO CIVIL` |
| `[ignorar]` | 20 | 5 | `parrafo`, `parrafo_2`, `capitulo_tit` | `BOE-A-1882-6036` → the enacting articles of the LECrim |
| `[firma]` | 1 | 1 | `parrafo_2` | `DOGC-f-2008-90017` |
| **total** | **150** | **15 / 60 (25 %)** | | |

They survive rendering verbatim — `###### [precepto]Primera.` — because `_extract_inline`
has no reason to strip them. Counted in the produced Markdown: 24 in `BOE-A-1882-6036`, 17 in
`BOE-A-1978-31229`, 12 in `BOE-A-1955-4699`, 1 in `BOE-A-1991-13213`.

**They do not exist on the consolidated surface** (0 in all 10 consolidated documents) and
they are absent from the published corpus: `grep -l '\[precepto\]\|\[encabezado\]\|\[ignorar\]' es/*.md`
over the 8,690 published files returns **1 file with 1 occurrence** (`es/BOE-A-2008-9288.md`).
So this is a new artifact class the non-consolidated path introduces, and it lands squarely
on the playbook's priority 1 ("no artifacts"). The probe's own artifact test was a regex for
HTML tags and mojibake, which these pass cleanly.

`[ignorar]` deserves its own line: it is the source telling you this paragraph is not part of
the consolidated act. Twenty paragraphs in my sample carry it. A parser that ignores the
sentinel publishes text the BOE has marked as superseded scaffolding, with no marker at all.

### R5. What `<bloque>` gives that `@class` cannot, measured on the same acts

`@class` gives a *visual* level. `<bloque>` gives a *unit*: a stable id and a normalised
title. On `BOE-A-1978-31229`, **208 of 210** blocks carry a `titulo` attribute
(`Disposición adicional primera`, `Artículo 12`), and every block carries an id
(`preambulo`, `tpreliminar`, `a1`, `dd`, `df`, `primera`, `septima`). The diary XML carries
**0** of either. Anything article-level — anchors, per-article diffs, `articles_affected`,
`article_count` — is built from prose in the non-consolidated path and from a declared id in
the consolidated one.

Where `@class` *does* work, it works exactly. Counting only preceptos that already existed at
enactment (consolidated `<version fecha_publicacion>` ≤ the act's own publication date), so
that later amendments do not inflate the target:

| act | preceptos as enacted | diary `class="articulo"` | recovery |
|---|---:|---:|---:|
| `BOE-A-1955-4699` | 400 | 400 | **100 %** |
| `BOE-A-1991-13213` | 60 | 60 | **100 %** |
| `BOE-A-2005-1576` | 68 | 68 | **100 %** |
| `BOE-A-2015-6704` | 55 | 55 | **100 %** |
| `BOE-A-2024-10237` | 29 | 29 | **100 %** |
| `BORM-s-2019-90599` | 112 | 112 | **100 %** |
| `BOE-A-1987-11921` | 120 | 119 | 99.2 % |
| `BOE-A-1978-31229` | 184 | 182 | 98.9 % |
| `BOE-A-2007-11450` | 10 | **0** | **0 %** |
| `BOE-A-1882-6036` | n/a (all 1,095 versions post-date 1882) | 935 | — |

That is the real shape of the finding: the vocabulary is **either right or absent**, with no
in-band signal telling you which one you got. A count-based sanity check is available for
free during the reprocess — compare the `articulo` count against the consolidated precepto
count wherever both surfaces exist — and it catches the 0 % case immediately.

### R6. What reproduced

| probe claim | my measurement | verdict |
|---|---|---|
| `<a>` = 0 in the diary body | **0** in 60 documents | CONFIRMED |
| `_STRIP_CLASSES` paragraphs are always inside `<td>`/`<th>` (1,644/1,644) | **10,964 / 10,964** across 60 documents, 0 standalone | CONFIRMED, and on 6.7× the sample |
| 0 residual HTML tags, 0 mojibake in the rendered Markdown | 0 tags, 0 `Ã`, 0 U+FFFD, 0 `&#` in all 10 renders (1 regex hit spanning a newline, false positive) | CONFIRMED |
| `parse_text_xml()` returns 0 blocks on a diary XML | not re-run — the diary files contain literally 0 `<bloque>` and 0 `<version>` (grepped), so it follows | CONFIRMED |
| `articulo` = 1,246 instances, 10.5 % of paragraphs, 28/38 docs | **4,914 instances, 15.4 % of 31,899, 39/40 docs** | not contradicted — both are sample statistics, neither is a corpus rate. Do not put either in a plan. |

### What this changes for the republish

1. A **class-name allow-list is not enough**. The reprocess needs an instrument that logs
   every unseen `@class` *and* every document that ends with zero headings, and a gate that
   refuses to publish the second kind. Two in sixty is a few thousand files.
2. **Strip the `[...]` sentinels — and use them first.** They are the only in-band block-type
   signal the diary surface has. Consumed, they fix R1/R2 for free (`[encabezado]` promotes
   the group heading, `[precepto]` marks the unit); ignored, they are 150 visible artifacts
   per 60 documents.
3. `[ignorar]` needs a decision, not a default.
4. The `articulo`-count-vs-precepto-count check in R5 is a cheap per-act oracle for acts that
   exist on both surfaces. It is the only cross-check available, and it is the one that
   catches the failure the probe's method could not see.

*Requests: 88 (73 × 200, 4 × 404, 10 × 400 wrong-header, 1 diagnostic). No 429, no 5xx.
Scratch: `/Users/neli/.claude/jobs/5bf7ddf4/tmp/refut_fmt3/` (`census.json`, `cons_compare.json`,
`sentinels.json`, `raw/`, `md-*.md`). `engine` and `countries/es` untouched.*

---

## format — angle 1: the identity test compared the source with itself, and the law goes missing inside the images

> Adversarial verification of probe 4 (`04-formato-no-consolidado.md`). Read-only run,
> 2026-09-03. **94 HTTP requests**, all 200, no 429/5xx, ≥0.9 s apart, UA
> `legalize-bot/1.0 (+https://github.com/legalize-dev/legalize)`. Log:
> `/Users/neli/.claude/jobs/5bf7ddf4/tmp/refute_fid/requests.jsonl`.

**Verdict: PARTIALLY_REFUTED.** The probe's structural findings replicate — every one I
re-ran came out the same or stronger. Its *headline* does not. The 1.0000 identity number
is a comparison of the BOE's XML against the BOE's own HTML view **of that same XML**, and
by its own method statement it never touched the rendered Markdown. When I run the
comparison the probe's brief actually asked for — rendered output against the **official
PDF**, which is the authentic published act — four acts in my sample carry **2.1 % of their
official text**. The rest of each act is 196, 182, 20 and 7 page-sized PNG bitmaps. Those
four acts are 5.3 % of my sampled acts but **25.4 % of the official gazette pages my sample
covers**.

### My sample (deliberately different)

The probe sampled one gazette day per year, mostly early-January, Sección I, n=38, and did
its rendering comparison on 3 acts. I sampled **9 gazette days across 1996–2024, chosen for
hard content** (year-end tariff issues, budget day, a tax-form Orden, a technical-annex
Resolución), took **every Sección-I act on each day** rather than a hand-picked spread, and
compared against the **PDF**, not the HTML.

| Day | Sec-I acts taken | Why this day |
|---|---:|---|
| 1996-12-31 | 10 | year-end: tarifas, módulos, umbrales; pre-2000 typesetting |
| 1999-07-31 | 4 | mid-year control |
| 2003-06-28 | 13 | homologaciones + precios máximos |
| 2006-11-30 | 8 | mid-decade control (caught the legacy uppercase template) |
| 2011-12-30 | 3 | nomenclatura combinada (arancel), conjuntos de medicamentos |
| 2013-03-15 | 12 | mid-year control |
| 2014-12-30 | 18 | **PGE 2015** (507 pages, 124 tables) + perfiles de consumo + TUR gas |
| 2021-09-30 | 6 | modern control |
| 2024-06-28 | 2 | Orden HAC (tax-form annexes, rowspan-heavy) |
| **Total** | **76** | 1,618 official gazette pages |

Six official PDFs were fetched and text-extracted with `pdftotext -layout` for the
side-by-side: `BOE-A-2014-13617`, `BOE-A-2011-20544`, `BOE-A-2011-20545`,
`BOE-A-2003-12865`, `BOE-A-2024-13049`, `BOE-A-2014-13618`, `BOE-A-1996-29122`.
One PNG (`.../disp/2014/315/13617_5290.png`) was fetched and inspected visually.

**Method.** Same as the probe's for rendering — `<texto>` children fed straight through the
engine's own unmodified dispatch (`_parse_p`, `_table_paragraph`, `_parse_blockquote`,
`_image_paragraph`, `_list_paragraphs`, then `render_paragraphs`), nothing patched.
Everything after that is different: (1) a **per-text-node recall test** — every `.text`/
`.tail` in `<texto>` of ≥4 normalised chars, checked for presence in the flattened Markdown;
(2) a **rendered-output-vs-official-PDF** character comparison with BOE page chrome stripped;
(3) a **text-density-per-official-page** measure using `<pagina_inicial>`/`<pagina_final>`
from the document's own metadata — free, no extra request, and it is the cheap corpus-wide
detector this problem needs; (4) table-structure checks (`rowspan`/`colspan` expansion,
header-row provenance) run against `fetcher/_tables.render_table`'s actual algorithm;
(5) corpus greps against `countries/es` at `origin/main` (`cc3d0212`, clean).

---

### 1. The identity test cannot see what it was asked to see

The probe's own §4 method line: *"identity ratio = `difflib.SequenceMatcher` matching-block
coverage of the normalised **`<texto>` text** against the normalised text of the official
page"*, where "the official page" is `diario_boe/txt.php?id=` — the BOE's HTML rendering
**generated from that same XML record**. Its own table lists `<texto>` chars and Official
HTML chars as equal (41,450/41,450; 8,119/8,119; 15,581/15,581) and reports Markdown chars
in a *separate* column that no identity ratio was computed against.

So the number measures that the BOE's HTML view faithfully renders the BOE's XML. It does.
That is a property of the BOE, not of our pipeline, and it is silent on both of the
questions that matter:

- does **our rendered Markdown** preserve the XML? (the probe checked only for residual tags
  and mojibake, not for content); and
- does the **XML** preserve the **act**? (the two surfaces compared are the same surface).

The probe named the second gap in its own caveat 3 — *"it compares the XML text to the BOE's
own HTML, not to the PDF"* — and then let the 1.0000 stand as the headline anyway. It is not
a small gap. It is the entire finding.

### 2. Against the official PDF: four acts are 2.1 % text and 98 % bitmap

`pdftotext -layout` on the act's own `url_pdf`, BOE running headers/footers/`cve:` lines
stripped, NFC-normalised and whitespace-collapsed on both sides:

| Act | Official pages | PDF text chars | XML `<texto>` chars | **Coverage** | `<img>` in XML |
|---|---:|---:|---:|---:|---:|
| `BOE-A-2014-13617` (perfiles de consumo eléctrico) | 198 | 686,754 | 7,235 | **1.1 %** | 196 |
| `BOE-A-2011-20544` (conjuntos y precios de referencia de medicamentos) | 183 | 904,793 | 18,620 | **2.1 %** | 182 |
| `BOE-A-2011-20545` (idem, agrupaciones homogéneas) | 22 | 124,738 | 7,614 | **6.1 %** | 20 |
| `BOE-A-2003-12865` (Real Decreto, anexos técnicos) | 8 | 18,044 | 2,991 | **16.6 %** | 7 |
| **Aggregate** | **411** | **1,734,329** | **36,460** | **2.1 %** | **405** |

Controls on the same method, to show the measure is not broken:
`BOE-A-2014-13618` 96.5 % coverage (0 images), `BOE-A-2024-13049` 176 % (the XML transcribes
tax-form annexes that the PDF draws as forms — the XML is *richer* there).
`BOE-A-1996-29122` reads 42 % but is not usable: the 1996 PDF is a scan whose text layer is
OCR and whose page range covers neighbouring acts — I discarded it rather than count it.

**What the images are.** The probe asserts *"images are BOE-hosted PNGs, not scans of whole
pages… figures, formulas and signature rubrics"*. I fetched one —
`https://www.boe.es/datos/imagenes/disp/2014/315/13617_5290.png`, 228 KB, **2126 × 2493 px**,
i.e. a full page at ~250 dpi — and looked at it. It is **ANEXO I of the Resolution as
ordinary legal prose**: the bold headings `1- Objeto`, `2- Ámbito de aplicación`,
`3- Definiciones`, `4- Clasificación de consumidores`, `5- Periodos`, the lettered list
`a) … b) … c) … d)` and the superscripted profile names `P^a`, `P^b`. Not a figure. Not a
formula. The articulated text of the annex, delivered as a bitmap, 196 times.

What our renderer emits for that act, in full, is ~25 lines of preamble and dispositivo
followed by 196 lines of `![5290.png](https://www.boe.es/datos/imagenes/disp/2014/315/13617_5290.png)`.
The official act is 198 pages. Against the playbook's priority 1 — *"the rendered Markdown
must be identical to the official law… not 'most of it'"* — this is a total failure on the
act, and it is undetectable by any check the probe ran, because `txt.php` serves the same
196 images.

### 3. How often: the free detector, and the prevalence

`<pagina_inicial>`/`<pagina_final>` are in every diary XML's `<metadatos>`. Characters of
`<texto>` per official page is therefore a **zero-request** quality signal over the whole
corpus. On my 76 acts the median is **2,896 chars per official gazette page**. The
image-substituted acts sit two orders of magnitude below it:

| Detector: `<img> ≥ 5` **and** `< 600` chars per official page | Value |
|---|---:|
| Acts flagged | **4 of 76 (5.3 %)** |
| Official gazette pages they cover | **411 of 1,618 (25.4 %)** |
| Chars/page of the flagged acts | 37 · 102 · 346 · 374 |
| Median chars/page, all 76 | 2,896 |
| Acts with ≥1 `<img>` at all | 12 of 76 (16 %) |
| Years the flagged acts fall in | 2003, 2011, 2011, 2014 |

Counted by act it is a 5 % problem. Counted by **printed law**, which is what a reader
actually loses, it is a **quarter of the sample**. This is not a pre-1975 problem and not a
legacy problem — the worst case is 2014.

**It is already shipped.** In the published consolidated corpus at `origin/main`:

| Measurement on `countries/es/es/*.md` (8,690 files) | Value | How |
|---|---:|---|
| Files with ≥1 image line | 1,400 (16.1 %) | `grep -lE '^!\[' es/*.md` |
| Image lines total | 22,059 | `grep -hcE '^!\[' es/*.md \| paste -sd+ \| bc` |
| Files where >30 % of non-blank lines are image links (≥5 images) | **20** | python line census |
| Worst | `BOE-A-2020-17283.md` — **180 image lines of 274** (65.7 %) | idem |

So the diary surface does not *introduce* this defect; issue #66 multiplies the exposure to
it, and neither surface has ever been measured against the PDF.

### 4. "Zero residual HTML tags" holds on three acts and on nothing else

`_extract_inline` emits `<sup>…</sup>` and `<sub>…</sub>` by design, and `markdown.py` maps
`nota_pie` to `> <small>…</small>`. The probe's three acts happen to contain none of them,
so it scored priority 1's *"no leftover HTML/XML tags"* box green.

| Where | Residual HTML tags | How |
|---|---:|---|
| Probe's 3 renders | 0 | its regex sweep |
| **My 46 diary renders** | **77** (64 `<sub>`, 13 `<sup>`, + closers) | `grep -hoE '</?(sup\|sub\|small)>' md/*.md` |
| **Published corpus `es/*.md`** | **159,677 opening tags** — 94,680 `<small>`, 34,518 `<sub>`, 30,479 `<sup>`, plus 11 `<p>` and 8 `<td>` that are genuine escapes | `grep -hoE` over 8,690 files |

The `<p>`/`<td>` leaks (19 occurrences) are the only ones that are accidental; the rest are
deliberate. That is a defensible design choice — but it is a documented **exception** to
priority 1, not a green tick, and the re-emission is the moment to decide which.

Worth noting where they land: `md/BOE-A-2014-13622.md` renders a compensation formula as
`# T = [N x V] / 166,386= [S (km2) x B (kHz) x F (C<sub>1</sub>, C<sub>2</sub>, …` — HTML
subscripts inside a Markdown `#` heading, with `km2` losing its superscript two words
earlier in the same act. That is what a formula looks like when it survives as text.

### 5. Tables: content duplicated, and one row in ten is the wrong header

Both measured against `render_table`'s actual algorithm over my 76 acts.

| Table defect | My 76 acts | Probe |
|---|---:|---|
| Tables | 254 | 129 in 38 |
| `<td>`/`<th>` | 11,633 | 11,590 `<td>` |
| **Cells duplicated by rowspan/colspan expansion** | **876 (7.5 %)** | reported as D3, "low severity, cosmetic" |
| **Tables with no header row in the source, where row 1 is promoted to header** | **24 of 254 (9.4 %)** | not measured |
| Cells with ≥2 `<p>` flattened onto one line by `_cell_text` | 143 (1.6 %), 23,803 chars | not measured |
| `<caption>` | 0 | 67, all in one document |
| `<a>` / `<li>` | 0 / 0 | 0 / 0 ✅ replicated |

The duplication is not cosmetic once you leave the signature block. In `BOE-A-2024-13049`
(Orden HAC/646/2024, the tax-record layout) the rendered header row is
`| «Posiciones | Naturaleza | Descripción de los campos | Descripción de los campos |
Descripción de los campos | Descripción de los campos | Descripción de los campos |` and body
rows repeat `Concepto.` four times and `NIF PERCEPTOR:` four times. In a table that
*specifies a fixed-width record format*, a reader cannot tell a repeated cell from a real
one. The playbook forbids exactly this: *"no duplicated paragraphs"*.

The header promotion is worse because it is silent. `render_table` always emits row 1 plus a
`| --- |` separator. In the PGE the salary tables have no `<thead>` and no `cabeza_tabla`, so
the output is:

```markdown
| Sueldo (a percibir en 14 mensualidades) | 26.448,38 € |
| --- | --- |
| Otras remuneraciones (a percibir en 12 mensualidades) | 103.704,24 € |
| Total | 130.152,62 € |
```

A salary line rendered as a column heading. 24 tables in 76 acts.

### 6. What replicates, exactly

I re-ran the probe's own checks and did not find them wanting:

| Probe claim | My measurement | |
|---|---|---|
| Text of paragraphs survives the dispatch | **0 of 22,318 text units missing** across 76 acts (units ≥4 chars, both sides normalised identically) | ✅ **stronger than the probe's** |
| `parse_text_xml()` → 0 blocks on a diary XML | 0 blocks on `BOE-A-2014-13612` and `BOE-A-2024-13049` | ✅ replicated |
| 0 `<a>` in the diary surface | 0 in 76 documents | ✅ replicated |
| 0 `<ol>/<ul>/<li>` | 0 in 76 documents | ✅ replicated |
| No unhandled child tags of `<texto>` | 0 unhandled tags across 76 documents | ✅ replicated |
| D1 indentation defect, `countries/es@origin/main` | `grep -lE '^    [«A-ZÁÉÍÓÚa-z]'` → **1,152 files**; `grep -hcE '^    \S'` → **79,176 lines** | ✅ byte-for-byte replicated |
| D5 legacy uppercase `@class` is "2 documents from one 2005 day" | Also **3 of 8 acts on 2006-11-30** (`BOE-A-2006-20844/-20845/-20849`): `ATEXTO_NORMAL` 22, `ATEXTO_BLANCO_4` 21, `RBF_SFRANySIG_ARTICULO` 19, `RBC_RED_CENTRO` 4, `NBC_SUBCAPITULO` 3, `RVC_CAPITULO` 2 | ⚠️ **not a one-day cluster** — a template family spanning at least 2005–2006 |

**One number the probe undercounts.** `^    \S` matches four spaces followed by a non-space,
so it counts `sangrado`/`sangrado_articulo` and misses `sangrado_2`, which emits eight. The
indent-width histogram over `es/*.md`:

| Leading spaces | Lines |
|---:|---:|
| 4 | 79,176 |
| 8 | 35,522 |
| 12 | 1,270 |
| 14/16/18 | 15 |
| **Total ≥4** | **115,948** |

The shipped indented-code-block defect is **115,948 lines, not 79,176** — 46 % larger.

### 7. A trap in the parser that this probe's method hides

`<texto>` is not unique in a diary document. `<analisis><referencias><anterior>` contains a
`<texto>` child holding the reference wording. `root.find(".//texto")` returns **that** one,
and the body renders empty — I hit it on the first act I parsed (`BOE-A-2011-20543`) and it
produced a silent 0-character render, not an error. The body is `root.find("texto")`, a
direct child of `<documento>`. Worth one line in the new dispatch and one test, because the
failure mode is an empty file that looks like a legitimately empty pre-1975 document.

---

### Numbers side by side

| Claim | Probe | Mine | Verdict |
|---|---|---|---|
| Fidelity of the diary XML to the official act | identity **1.0000**, "reaches the bar with four fixes" | **2.1 % of official PDF text** on 4 acts / **25.4 % of sampled gazette pages** delivered as bitmaps | **REFUTED as a fidelity measure** — the probe's comparison is XML vs the HTML generated from it, and never involves the rendered Markdown |
| Images are "figures, formulas and signature rubrics, not scans of whole pages" | 50 imgs, 5 of 38 docs | one inspected: **2126×2493 px page image of annex prose**; 405 such images in 4 acts | **REFUTED** |
| Residual HTML tags in the output | **0** | **77** in 46 renders; **159,677** in the published corpus | **REFUTED as a general claim**, correct on its 3 acts |
| D1 shipped indentation defect | 79,176 lines / 1,152 files | 1,152 files ✅; **115,948 lines** | file count CONFIRMED, line count **corrected upward 46 %** |
| rowspan duplication "low severity, cosmetic" | — | **876 of 11,633 cells (7.5 %)**, incl. a fixed-width record spec | **DISPUTED as severity** |
| Header rows | "`<thead>` promotes the header row ✅" | **24 of 254 tables (9.4 %)** promote a *data* row | **new defect, not measured** |
| Text survives the paragraph dispatch | 3 acts, 1.0000 | **0 missing text units in 76 acts** | **CONFIRMED, and strengthened** |
| `parse_text_xml` → 0 blocks; 0 `<a>`; 0 `<li>`; no unhandled tags | — | identical | **CONFIRMED** |
| Legacy uppercase `@class` = 2 docs, one 2005 day | 53 paragraphs | + 3 docs on 2006-11-30, 71 paragraphs | **CONFIRMED but broader** |

### What this changes for the decision

1. **The scope question is not only "from what year".** It is also "which acts". A 1975
   floor keeps 198-page acts whose text is 1 % present. Add a second gate on the same free
   metadata: `chars(<texto>) / (pagina_final − pagina_inicial + 1)`. Below ~600, the act's
   substance is in the images and the file is a stub with an image gallery. Decide
   deliberately what to do with those — exclude, mark in frontmatter, or ship with an
   explicit `text_completeness` field — but do not let them land silently among 100k
   ordinary acts.
2. **Instrument it during the reprocess, not after.** The density ratio and the unmapped-
   `@class` counter are both nearly free and both catch a class of failure that renders
   green today.
3. **`_tables.render_table` needs three fixes, not one.** Caption (probe's D2), rowspan
   duplication for non-signature tables, and the phantom header row. All three are shared by
   every country.
4. **`<sup>`/`<sub>`/`<small>` need a ruling.** 159,677 in the shipped corpus. Either the
   playbook's "no leftover HTML tags" carries a documented exception, or the re-emission
   converts them.

### Caveats on my own work

- **The PDF comparison is 4 acts + 3 controls, not 30.** The 2.1 % figure is an aggregate
  over those four, and two of them dominate it. What is *not* sample-dependent is the
  mechanism: 405 page-sized PNGs against 411 official pages is a 1:1 substitution, and the
  one image I opened settles what they contain.
- **`pdftotext -layout` is not the printed act.** It drops nothing on digitally-typeset BOE
  PDFs (2000+) but pads columns with spaces, so my char counts are ±5 % on table-heavy pages.
  It is unusable on pre-1998 scans — I discarded the 1996 comparison for that reason rather
  than report it.
- **The 25.4 %-of-pages figure is 9 gazette days.** Days are clusters: `2014-12-30` and
  `2011-12-30` are year-end tariff issues, which is exactly where image annexes live, and I
  picked them on purpose. A month-stratified sweep would move this number, probably down.
  The 5.3 %-of-acts figure is the conservative one; the page figure is the one that describes
  what a reader loses.
- **My text-recall test is presence-of-substring, not order.** It proves nothing was
  *dropped*; it does not prove nothing was *reordered* or *duplicated* — which is why
  duplication is measured separately, from the source's span attributes.
- **I did not re-run the pre-1975 floor.** Angle 2 has that.
- Scratch, raw XML, renders and PDFs:
  `/Users/neli/.claude/jobs/5bf7ddf4/tmp/refute_fid/` (`raw/`, `md/`, `pdf/`,
  `census76.json`, `pdfcmp.json`, `requests.jsonl`).
