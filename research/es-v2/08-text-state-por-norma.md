# Probe 8 — `text_state` per norm for `es`

**Date:** 2026-09-03 · **Source:** BOE open data (`www.boe.es/datosabiertos`) · **HTTP requests: 130** (budget 150, no 429, no 5xx)
**Scope:** what the test for "does this act have a consolidated text?" is, what it costs, and the exact
override `es` needs once the corpus is re-emitted with non-consolidated acts in it.

Everything below states its sample. Numbers not from a measurement I ran are marked EXTRAPOLATED
or attributed to the issue that already holds them.

---

## 0. Answer in four lines

1. **Membership in the consolidated catalogue is the flag, and it costs 2 requests for the whole country.**
   The catalogue is 12,385 entries, enumerable in 2 requests. Verified end to end against `/texto` on
   79 acts: **24/24 members → 200, 55/55 non-members → 404. Zero false positives, zero false negatives.**
2. **`/metadatos` is not a second opinion.** It 404s in lockstep with `/texto` (28/28 agreement).
   The whole `/api/legislacion-consolidada/id/{id}/*` subtree only knows the consolidated set.
3. **There is a second, independent per-act flag, free of extra requests:** the diary XML the fetcher
   already downloads for every act carries `<estado_consolidacion codigo="0"/>` when there is no
   consolidated text and `codigo="3"` (Finalizado) / `"4"` (Desactualizado) when there is.
   38/38 agreement with catalogue membership. `estatus_legislativo` is useless — `"L"` on all 48 acts seen.
4. **"404 today" is time-dependent and the window is weeks, not days.** Median lag between publication
   and first consolidation is **10 days** (p75 32, p90 79, max 189) on the 173 norms published in 2026
   that are in the catalogue. The daily must therefore re-ask, not decide once.

---

## 1. Is the `/texto` 404 reliable?

### 1.1 The confusion matrix

Sample construction, all in this probe:

* **67 acts** = every `<item>` in section `codigo="1"` ("I. Disposiciones generales") of 10 BOE daily
  summaries spanning the whole archive: `19790103, 19850115, 19900116, 19950117, 20000118, 20050118,
  20100119, 20150120, 20200121, 20260120`.
* **+ 2 acts** from two more recent days (`20260901` → `BOE-A-2026-18364`, `20260812` → `BOE-A-2026-17573`),
  used specifically to hunt false negatives on ids too fresh to be in a snapshot.
* **+ 10 catalogue "corner" entries** drawn at random (seed 8) from the two awkward populations:
  5 with `estado_consolidacion` = `4 Desactualizado` (`BOE-A-2017-11001`, `BOE-A-2015-6016`,
  `BOE-A-2010-563`, `BOE-A-2020-7382`, `DOGC-f-2002-90024`) and 5 with a non-BOE identifier
  (`BOCL-h-2020-90420`, `BOA-d-2017-90392`, `BOA-d-2019-90544`, `BOA-d-2011-90078`, `BORM-s-2001-90004`).

Every one of the 79 was predicted from set membership alone, then verified with a real `GET …/{id}/texto`:

| predicted by set membership | n | `/texto` 200 | `/texto` 404 |
|---|---:|---:|---:|
| **in catalogue → consolidated** | 24 | **24** | 0 |
| **not in catalogue → not consolidated** | 55 | 0 | **55** |

**False positives: 0. False negatives: 0.** The 14 in-catalogue hits inside the sumario sample were
`BOE-A-1979-88, BOE-A-1985-806, BOE-A-2000-1006, -1007, -1009, -1011, BOE-A-2005-895, -896,
BOE-A-2010-835, BOE-A-2020-848, -849, BOE-A-2026-1255, -1256, -1258`.

### 1.2 Transient 404s

Five ids re-requested at the end of the run, ~40 requests after the first call:
`BOE-A-1979-89` 404→404, `BOE-A-2010-836` 404→404, `BOE-A-2026-1257` 404→404,
`BOE-A-1979-88` 200→200 (41,448 B both times), `BOE-A-2026-1258` 200→200 (66,920 B both times).
**5/5 stable.** No transient 404 observed. The 404 body is a well-formed envelope, not an error page:

```xml
<response><status><code>404</code><text>La información solicitada no existe</text></status><data/></response>
```

— 170 bytes, identical on all 55 misses. It is a decision by the API, not a failure.

### 1.3 Does `/metadatos` ever disagree with `/texto`?

`/metadatos` requested on 28 of the 67 (all 14 members + 14 non-members picked at random):

| | `/texto` 200 | `/texto` 404 |
|---|---:|---:|
| `/metadatos` 200 | 14 | 0 |
| `/metadatos` 404 | 0 | 14 |

**28/28 agreement.** So "404 on `/texto` but 200 on `/metadatos`" does not happen: a non-consolidated act
does not exist *at all* under `/api/legislacion-consolidada/id/…`. This matters for the parser design —
there is no cheap metadata endpoint for a non-consolidated act. Its only machine-readable surface is
`https://www.boe.es/diario_boe/xml.php?id={id}`, which is a different schema.

---

## 2. Is there a flag that answers it without one request per act?

Four candidates tested. Three work, one is dead.

### 2.1 `estado_consolidacion` in the catalogue listing — real domain

| code | text | count in the 12,385-entry catalogue |
|---|---|---:|
| `3` | Finalizado | 12,190 |
| `4` | Desactualizado | 195 |

The authoritative domain, from `GET /api/datos-auxiliares/estados-consolidacion` (1 request), is exactly:

```json
{"status":{"code":"200","text":"ok"},"data":{"3":"Finalizado","4":"Desactualizado"}}
```

**Neither value means "not consolidated."** The field answers *how current the consolidation is*
(per the BOE's own FAQ: `finalizado` = the published text is the latest; `desactualizado` = a later
amendment exists and the new version is still being drafted). It cannot discriminate consolidated from
non-consolidated, because a non-consolidated act is simply absent from the listing.

Corroborated against the published corpus (`grep '^consolidation_status:' countries/es`, 12,299 files):
`Finalizado` 12,196 · `Desactualizado` 102 · **`Sin consolidar` 1**. That third value is no longer in the
API's declared domain — evidence the domain drifts, and a reason not to hard-code a whitelist of codes.

`Desactualizado` is *not* a proxy for "no text": all 5 `Desactualizado` ids tested returned 200 with
45–850 KB of XML.

### 2.2 `estado_consolidacion` inside the diary XML — **this one works, per act, free**

The diary XML's `<metadatos>` carries the same element, and there it *does* take a third value.
Measured on 10 acts fetched into `probe8_raw/` for this probe:

| id | in catalogue | `<estado_consolidacion codigo=…>` | text |
|---|---|---|---|
| `BOE-A-2010-836` | no | `0` | *(empty)* |
| `BOE-A-1979-89` | no | `0` | *(empty)* |
| `BOE-A-2000-1008` | no | `0` | *(empty)* |
| `BOE-A-2000-1010` | no | `0` | *(empty)* |
| `BOE-A-2020-850` | no | `0` | *(empty)* |
| `BOE-A-2015-432` | no | `0` | *(empty)* |
| `BOE-A-2005-894` | no | `0` | *(empty)* |
| `BOE-A-1990-933` | no | `0` | *(empty)* |
| `BOE-A-1979-88` | **yes** | `3` | Finalizado |
| `BOE-A-2026-1258` | **yes** | `3` | Finalizado |

Confirmed earlier in the same run on a wider set of 38 cached diary XMLs (1978–2026, ids from the same
10 sumarios): **29 non-members all `codigo="0"`, 9 members all `codigo="3"` — 38/38.**
Combined, **48/48 agreement with catalogue membership across two disjoint fetches.**

This is the flag to use *inside the parser*, because the diary XML is already in hand at that point.

### 2.3 `estatus_legislativo` in the diary XML — dead

`"L"` on **all 48** diary XMLs read (38 cached + 10 fetched), covering 1978–2026, ranks Constitución,
Ley, Ley Orgánica, Real Decreto, Orden, Resolución, Decreto, Corrección de erratas and Reforma,
both `origen_legislativo` Estatal (30/38) and Autonómico (8/38), and both consolidated and not.
Cross-tab: `(in_catalog=False, "L") 29 · (in_catalog=True, "L") 9`. **Zero discriminative power.**
Corroborated on the whole published corpus: `grep '^legislative_status:'` → `"L"` on 12,299 of 12,299 files.

### 2.4 The sumario — nothing there at all

The daily summary carries **no** consolidation hint. The complete set of child elements of `<item>`,
over every item of all 10 archived sumario files (1979–2026), is:

```
control · identificador · titulo · url_html · url_pdf · url_xml
```

and `<item>` carries **no attributes** whatsoever. So discovery cannot decide the surface from the
summary; it must consult the catalogue (or the act's own diary XML).

### 2.5 The catalogue as the flag — cost

`GET /api/legislacion-consolidada?limit=10000&offset=N`, `Accept: application/json`:

| request | bytes | items | wall time |
|---|---:|---:|---:|
| `offset=0` | 13,002,973 | 10,000 | 1.18 s |
| `offset=10000` | 2,979,294 | 2,385 | 0.13 s |

**2 requests, 15.2 MB, 1.3 s → 12,385 ids, all unique.** Against the alternative of one `/texto` probe per
act, this is the difference between 2 requests and ~120,000. The set fits in memory (≈ 350 KB as ids alone).

Composition of the 12,385: `ambito` Estatal 8,767 / Autonómico 3,618; `vigencia_agotada` N 9,973 / S 2,412;
identifier schemes `BOE-A` 12,140 and 245 regional-gazette ids (`BOJA-b` 58, `BOA-d` 44, `BORM-s` 31,
`DOGV-r` 30, `BOCL-h` 21, `DOGC-f` 20, `BOC-j` 11, `BOIB-i` 8, `BON-n` 6, others 16).
The published corpus holds 12,299 files (12,056 `BOE-A` + 243 regional) — **86 catalogue entries short**,
which is a separate question and not this probe's.

---

## 3. Time dependence — does an act gain a consolidated text later?

Yes, and this is the part that makes "404 today" a *dated* answer rather than a property of the act.

### 3.1 First-consolidation lag

Measured on the **173 catalogue entries whose `fecha_publicacion` ≥ 2026-01-01**, using
`fecha_actualizacion − fecha_publicacion`. For a norm published this year and not yet amended, that
difference *is* the delay between publication and the BOE consolidating it.

| statistic | days |
|---|---:|
| min | 0 |
| p25 | 1 |
| **median** | **10** |
| p75 | 32 |
| p90 | 79 |
| max | 189 |

Bucketed: same day 38 · 1–7 days 47 · 8–30 days 40 · 31–90 days 32 · >90 days 16.

### 3.2 The backlog is visible in the catalogue itself

2026 publications present in the catalogue, by publication month:

| month | 01 | 02 | 03 | 04 | 05 | 06 | 07 | **08** | 09 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| in catalogue | 17 | 25 | 25 | 23 | 20 | 29 | 21 | **9** | 4 |

August 2026 sits at 9 against a 17–29 run rate for every earlier month of the year. Those are not
acts that will never be consolidated; they are acts still in the queue.

### 3.3 Catalogue churn — how fast a snapshot goes stale

Entries whose `fecha_actualizacion` is within the last *N* days of 2026-09-03:

| ≤ 0 d | ≤ 1 d | ≤ 3 d | ≤ 7 d | ≤ 14 d | ≤ 30 d | ≤ 90 d |
|---:|---:|---:|---:|---:|---:|---:|
| 14 | 27 | 44 | 58 | 81 | 222 | 930 |

≈ 8 entries a day are touched. A snapshot taken at the start of a bootstrap is stale by a handful of
entries by the end of it — negligible for a bootstrap, fatal for a daily that caches the set for a week.

**Consequence for the daily:** an act published today and read as `as_enacted` is very likely to be
consolidated a week or a month later. The re-emission must decide what happens then — the file's
`text_state` flips from `as_enacted` to absent (point-in-time) and its body is replaced by a
consolidated one. That is a legitimate `[reform]`-shaped event, but it is a *transition* the pipeline
does not model today.

> **Caveat on `fecha_actualizacion`:** its year histogram over the whole catalogue is
> 2023 → 80, 2024 → 47, **2025 → 10,059**, 2026 → 2,199. The 2025 bulk is a BOE-side mass re-stamp,
> not 10,059 real consolidations. The lag figures in §3.1 are computed only over 2026 publications,
> which the bulk does not touch, but nobody should read `fecha_actualizacion` as "when it was
> consolidated" for anything older.

### 3.4 False-negative hunt on fresh ids

Six section-1 items from four gazette days newer than any of the archived sumarios
(`20260812`, `20260826`, `20260901`, `20260902`): 4 already in the catalogue, 2 not
(`BOE-A-2026-18364`, `BOE-A-2026-17573`) — and both of those returned 404 on `/texto`, confirming
the snapshot had not simply missed them. No false negative even on ids two days old.

---

## 4. The proposal for `es`

### 4.1 Country default: `TEXT_STATE["es"] = TextState.AS_ENACTED`

**Read this first, because it is the thing most likely to be argued about: the choice is invisible in
the output.** `frontmatter.py:70-74` emits the key only when the effective state is *not*
`POINT_IN_TIME`, so both possible designs produce byte-identical files:

| design | consolidated file | non-consolidated file |
|---|---|---|
| A — `es` absent from `TEXT_STATE`, parser sets `AS_ENACTED` on the non-consolidated | *(no `text_state` key)* | `text_state: "as_enacted"` |
| B — `es: AS_ENACTED`, parser promotes the consolidated to `POINT_IN_TIME` (the PT mirror) | *(no `text_state` key)* | `text_state: "as_enacted"` |

So the decision is made on failure mode and on the rule `countries.py` already states, not on output.

**Take B**, for three reasons:

1. **Failure direction.** If the per-norm decision is ever skipped — a code path added later, a
   fetch that produced no diary XML, a re-parse from a cached JSON that lost the override — design A
   silently publishes `point_in_time`, the *strongest* claim the spec has, on a body that is an
   un-amended 1979 text. Design B silently publishes `as_enacted`, which understates a consolidated
   file. Understating is recoverable; overstating is the failure that puts a wrong law in front of a
   lawyer. `storage.py:223-226` already guards the round-trip for exactly this reason and its comment
   names the same hazard.
2. **Loud failure.** Under B a broken promotion shows up as 12,385 files *gaining* a `text_state` line
   in one diff. Under A a broken demotion shows up as nothing at all.
3. **The rule already written in `countries.py`:** "the country default is the majority". Once
   non-consolidated acts are in, they are the majority by a wide margin — the whole consolidated
   universe is 12,385 acts, and a single BOE year contributes thousands of section-1 dispositions.
   EXTRAPOLATED: across 14 gazette days spanning 1979–2026 (73 section-1 items), 18 were consolidated
   and 55 were not — **24.7 % consolidated**, base 18/73, so the non-consolidated corpus is
   roughly 3× the consolidated one *within section 1 alone*. Probe 3/4 own the real total; the
   direction is not in doubt.

Entry to add, in the shape the file uses:

```
# BOE consolidates 12,385 norms and publishes everything else as enacted. The
# country default is the majority; the parser promotes the consolidated ones
# back to POINT_IN_TIME per norm.
"es": TextState.AS_ENACTED,
```

### 4.2 The exact condition that flips a norm

> **`text_state = POINT_IN_TIME` if, and only if, the norm was built from
> `/api/legislacion-consolidada/id/{id}/texto`. Otherwise it keeps the country default.**

Not a test the parser performs — a fact the parser already knows. In `es`, unlike `pt`, the two
surfaces come from **different endpoints with different schemas**: a consolidated norm is
`<version>`-stamped blocks from `/texto`, and a non-consolidated act is a flat run of
`<p class="…">` inside `<texto>` of the diary XML. §1.3 proved there is no third case: `/metadatos`
and `/texto` agree 28/28, so an act either has both or neither. The branch is forced by which
endpoint answered, before the parser is called.

Two mechanical forms of the same condition, both verified here, use whichever is in hand:

| where | condition | cost | verified |
|---|---|---|---|
| discovery / bootstrap | `identificador in catalogue_ids` | 2 requests for the whole country | 79/79 (§1.1) |
| parser, given the diary XML | `<estado_consolidacion codigo> != "0"` | 0 extra requests | 48/48 (§2.2) |

Do **not** write the condition as `estado_consolidacion in {"3","4"}` — the domain has already lost a
value (`Sin consolidar`, still present once in the published corpus) and the aux endpoint's answer is
just two entries today. `codigo == "0"` for "no consolidated text" is the stable half.

### 4.3 Where it belongs in the `es` fetcher

**Who constructs `NormMetadata` for a consolidated norm today** — one function, three callers:

```
fetcher/es/metadata.py :: parse_metadata(xml_data, id_boe, diario_xml=None)   ← the only constructor
    ← fetcher/es/fetch.py :: fetch_one()          (bootstrap: legalize fetch -c es --catalog)
    ← fetcher/es/daily.py :: _commit_reforms()    (daily: re-consolidated norms)
    ← fetcher/es/parser.py :: BOEMetadataParser.parse()   (generic pipeline path)
```

`parse_metadata` is fed the `/metadatos` XML as `xml_data` and returns without ever setting
`text_state`, so today every `es` file inherits the country default. That is the one line that changes
for the consolidated half: `text_state=TextState.POINT_IN_TIME` in the `NormMetadata(...)` call at
`metadata.py:334-350`, mirroring `fetcher/pt/parser.py:827` + `:856`.

**Who would construct it for a non-consolidated act: nobody. There is no such code path.** This is the
real work, and it is a sibling, not a flag on the existing function:

* `parse_metadata` requires `<metadatos>` and raises `ValueError` without it (`metadata.py:295-297`);
  for a non-consolidated act that document does not exist (§1.3).
* The diary XML's `<metadatos>` is a *different schema* — 33 child elements including
  `origen_legislativo`, `seccion`, `subseccion`, `pagina_inicial`, `letra_imagen`,
  `judicialmente_anulada` — where the `/metadatos` document has ~15 with different names.
  `_parse_diario_xml` already reads part of it, but only as a *supplement* returning
  `(subjects, pdf_url, extra)`.
* Rank comes from `<rango>` in both, so `_parse_rank` / `_RANK_CODE_MAP` are reusable as they stand —
  and the diary XML's `<rango>` already carries values the consolidated map has never seen
  (`Corrección (errores o erratas)`, `Reforma`), so `_RANK_CODE_MAP` needs the new codes or those acts
  land on `Rank.OTRO`.

**Concretely:**

| what | where |
|---|---|
| build the catalogue id set once | `fetcher/es/catalogo.py`, next to `iter_fixed_norms` — the pagination loop currently duplicated in `fetch.py:110-131` and `fetch.py:200-221` moves here |
| decide the surface per id | `fetcher/es/discovery.py :: BOEDiscovery.discover_all` — yields the id plus its surface, the way `pt/bootstrap.py` splits `published` from `consolidated` by a `cons:` id prefix |
| construct metadata for a consolidated norm | `metadata.py :: parse_metadata` — add `text_state=TextState.POINT_IN_TIME` |
| construct metadata for a non-consolidated act | **new** `metadata.py :: parse_diario_metadata(diario_xml, id_boe)` — country default applies, so it sets *nothing*; that is the point of choosing `AS_ENACTED` as the default |
| parse the body | **new** — `<texto>` of the diary XML into `Block`s; `transformer/xml_parser.py` reads the consolidated `<version>` schema and does not apply |

**What has to be threaded through: nothing.** That is the argument for putting the default at
`AS_ENACTED`. The non-consolidated path sets no `text_state` at all and gets the right answer; only the
consolidated path, which by construction *knows* it is consolidated because it just parsed a `/texto`
document, sets the override. No set, no flag, no parameter crosses a function boundary.

> **Blocker found while tracing this.** `discovery.py:23-25` imports `iter_norms_from_catalog` from
> `catalogo.py`, and **that function does not exist** (`catalogo.py` defines only `iter_fixed_norms`
> and `iter_norms_from_summaries`; grep over `src/` and `tests/` finds no definition anywhere).
> So `legalize bootstrap -c es` → `generic_bootstrap` → `discover_norm_ids` →
> `BOEDiscovery.discover_all` raises `ImportError` today. ES is bootstrapped through
> `legalize fetch -c es --catalog` + `legalize commit --all` instead, which bypasses discovery
> entirely. Whoever writes the surface split has to fill this in first.

### 4.4 `last_amendment` for the non-consolidated acts

**Source: `<analisis><referencias><posteriores><posterior referencia="BOE-A-…"><palabra>` in the
diary XML** — the same document the act's body comes from, so again zero extra requests.

Measured on the 8 non-consolidated acts fetched in §2.2: **5 of 8 carry at least one `<posterior>`**;
24 `<posterior>` entries in the 10-act sample. Verb histogram of that sample:
`SE MODIFICA` 9 · `SE DEROGA` 7 · `CORRECCIÓN de errores` 4 · `SE DICTA DE CONFORMIDAD` 3 ·
`SE DISPONE el cumplimiento de la Sentencia` 1 · `SE AMPLÍA` 1.

Corroborated at corpus scale (free, `grep` over `countries/es`, 12,299 files — consolidated norms only,
so this is the *shape* of the field rather than the population that will use it):
**8,530 files carry `references_subsequent`, holding 38,151 references in total** (avg 4.5/file).
Verb histogram over the whole corpus:

| verb | n | amendment? |
|---|---:|---|
| SE DEROGA | 3,758 | yes |
| SE MODIFICA | 3,117 | yes |
| CORRECCIÓN de errores | 424 | yes (changes the official text) |
| SE DICTA DE CONFORMIDAD | 341 | **no — a citation** |
| SE DICTA EN RELACIÓN | 195 | **no — a citation** (and the one place a *suspension* hides) |
| SE DECLARA | 141 | depends (TC nullity) |
| CORRECCIÓN de erratas | 107 | yes |
| SE AÑADE | 95 | yes |
| SE DEJA SIN EFECTO | 73 | yes |
| SE DESARROLLA | 48 | **no** |

That split is the same fact issue #106 already records as "1 in 4 published `[reform]` commits is a
citation and not an amendment" — here it is at the source, before a commit exists. **`last_amendment`
must be filtered by verb**, and the filter is a list of Spanish verb strings, i.e. exactly the kind of
per-legislature convention `models.py` warns against generalising.

**Mechanically nothing new is needed in the pipeline.** `pipeline.py:172-186` `_with_last_amendment`
already sets `last_amendment = reform.norm_id` on every non-first commit of an `AS_ENACTED` norm, and
`storage.py:225` already round-trips it. So the right shape is PT's: derive the `Reform` rows for a
non-consolidated act from its amending `<posterior>` entries (as `pt/amendments.py` does from
`eli:amended_by`), and the existing machinery writes `last_amendment` at each commit for free.

**Three traps, all measured:**

1. **`<posterior>` has no date.** The element carries `referencia` (an id), `<palabra>` (the verb) and
   `<texto>` (prose). The date is only inside the prose — *"por Ley 3/2010, de 21 de mayo"*,
   *"por Ley 11/2022, de 28 de diciembre"*. Ordering "most recent" therefore means either parsing that
   Spanish date out of the sentence or trusting the year in `BOE-A-YYYY-N`. Since a `Reform` needs
   `date` anyway (`models.py`), this is not optional work.
2. **12.5 % of references are not `BOE-A`.** In the 10-act sample, 3 of 24 named a regional gazette:
   `BOJA-b-2009-90030`, `BOIB-i-2020-90023`, `BOCT-c-2026-90032`. The corpus *does* publish 243 files
   under those schemes, so some resolve — but `cli.py:965-988` (`legalize verify`) reports any
   unresolvable `last_amendment` as a WARN, escalating to ERROR above 50 %.
3. **The published corpus never sees them, because the pipeline drops them.**
   `metadata.py :: _reference()` returns `""` unless the id `startswith("BOE-")`. Result, measured:
   all 38,151 references in the corpus are `BOE-A` (37,895) or `BOE-T` (256), and **not one** points at
   a regional-gazette id, despite 243 such files existing in the repo. Separately, the 256 `BOE-T`
   references (Constitutional Court rulings) resolve to nothing — the corpus contains no `BOE-T`
   identifier at all — so choosing one as `last_amendment` would guarantee a WARN.

---

## 5. The consequence Enrique asked to see with numbers

Measured over `/Users/neli/projects/legalize/countries/es` at `origin/main` (`cc3d021`), clean tree:

| fact | count | how |
|---|---:|---|
| `.md` law files (excluding the repo `README.md`) | **12,299** | `find . -name '*.md' -not -path './.git/*' -not -name README.md \| wc -l` |
| of those carrying a `text_state:` key | **0** | `grep -rl '^text_state:' --include='*.md' . \| wc -l` |
| of those carrying a `last_amendment:` key | **0** | `grep -rl '^last_amendment:' --include='*.md' . \| wc -l` |

**Confirmed: today's 12,299 files carry no `text_state` key at all**, and none carries `last_amendment`.

Now the part worth being precise about, because it changes how big the rewrite is:

* **Under the emitter as it stands** (`frontmatter.py:70-74`: write the key only when the state is not
  `POINT_IN_TIME`), a mixed `es` leaves the frontmatter of all 12,299 consolidated files **unchanged in
  this respect** — they stay keyless, because they are point-in-time. Only the newly added
  non-consolidated acts gain `text_state: "as_enacted"` (+ `last_amendment:` where one is known).
  The consolidated files are rewritten by the re-emission anyway — sharding moves every path — but not
  *because* of this change.
* **If the intent is literally "every law declares its own in its frontmatter"**, then the emitter must
  change to always write the key, and that adds a `text_state: "point_in_time"` line to
  **12,299 of 12,299 files** (and to every other country's corpus that shares the emitter — `fr`, `de`,
  `at`, `se`, `pt`, `ie`, … — which is a 34-country decision, not an `es` one).

**Verified against the spec as implemented, per the probe's instruction:** absence *does* mean
`point_in_time`. `models.py:100-105` — *"POINT_IN_TIME is the default and is never written to the
frontmatter — a file without the field is the law as in force on its `last_updated`"*;
`countries.py:56` — *"Absent means POINT_IN_TIME"*; `frontmatter.py:70-74` implements exactly that;
`cli.py:1198` reads it back as `front.get("text_state") or "point_in_time"`. The repo has **no v0.4
text that changes this** — grep for `v0.4` finds `layout.py`, `slug.py`, `committer/`, `state/store.py`
and `CLAUDE.md`, all about directories, dates, history and git identity. `text_state` is still
documented as v0.3 everywhere it appears. **Recommendation: do not change the emitter.** The mixed
corpus is fully self-describing without it — a file with no key is point-in-time by spec — and changing
it rewrites six countries' corpora to state a default they already state.

---

## 6. What this probe did not settle

* How many non-consolidated acts there actually are (Probe 3/4). §4.1's 24.7 % is a 73-item,
  14-day sample, labelled EXTRAPOLATED and used only for direction.
* The 86-entry gap between the 12,385-entry catalogue and the 12,299 published files.
* What the pipeline should do when an `as_enacted` act *becomes* consolidated weeks later (§3) —
  the file's body is replaced and its `text_state` key disappears. Real, dated, and unmodelled.
* Whether `POINT_IN_TIME` is honest for all 12,299 consolidated files today: issue #106 already
  records 2,553 files carrying articles from the future, which is a body that is *not* the law at its
  `last_updated`. That is a bug to fix in the re-emission, not a `text_state` value.

## Appendix — request ledger

| stage | requests | what |
|---|---:|---|
| 1 | 2 | catalogue enumeration, `limit=10000`, offsets 0 and 10000 |
| 2 | 67 | `/texto` on all 67 section-1 ids of the 10 archived sumarios |
| 3 | 44 | 1 × `datos-auxiliares/estados-consolidacion`, 28 × `/metadatos`, 5 × repeat `/texto`, 10 × corner `/texto` |
| 4 | 3 | sumarios `20260901`, `20260804`; 1 × `/texto` |
| 5 | 4 | sumarios `20260902`, `20260826`, `20260812`; 1 × `/texto` |
| 6 | 10 | `diario_boe/xml.php` for 8 non-consolidated + 2 consolidated acts |
| **total** | **130** | budget 150 · UA `legalize-bot/1.0 (+https://github.com/legalize-dev/legalize)` · 0.8 s between requests · no 429, no 5xx |

Raw data kept at `/Users/neli/.claude/jobs/5bf7ddf4/tmp/`: `probe8_catalog.json` (12,385 entries),
`probe8_sample.json`, `probe8_texto.json`, `probe8_meta.json`, `probe8_stage3.json`,
`probe8_stage4.json`, `probe8_stage5.json`, `probe8_diario.json`, `probe8_raw/*.xml`.
Note the scratch directory is shared with the other probes and was clobbered once mid-run; every
`probe8_*` name is private to this probe.
