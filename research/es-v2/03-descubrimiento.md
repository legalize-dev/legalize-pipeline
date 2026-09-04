# ES v2 · Step 0 — Discovery

> Probe 3 of the Spain republish research pass. Resolves the open questions in
> issues **#99** (bulk discovery of the consolidated corpus is not wired) and
> **#66** (the non-consolidated acts are not ingested).
>
> Everything below was measured against the live BOE API on **2026-09-03**.
> **110 HTTP requests** to `www.boe.es`, one at a time, 0.5–1.0 s apart, with
> `User-Agent: legalize-bot/1.0 (+https://github.com/legalize-dev/legalize)`.
> No 429, no 5xx. Scratch scripts and raw captures:
> `/Users/neli/.claude/jobs/5bf7ddf4/tmp/` (`p1_docs.py` … `p13_range.py`,
> `catalog_all.json`, `sumario_sample.json`, `request_count.json`).

---

## 0. Headline

| Question | Answer | Measured how |
|---|---|---|
| Does one endpoint enumerate the whole consolidated catalogue? | **Yes. In 2 requests.** `?limit=-1&offset=0` then `?limit=-1&offset=10000` | reqs 9, 26 |
| How big is it? | **12,385 norms**, exactly | binary search on `offset`, reqs 11–25 |
| Is the `offset` walk stable? | **Yes in practice, and a `sort` parameter makes it stable by construction** | reqs 9/26 15 min apart: 0 dupes, 0 gaps; reqs 27–28, 103–104 |
| Does `?from=&to=` sweep history? | **No.** No `fecha_actualizacion` predates **2023-12-15**; a 1990 window returns nothing | reqs 31–33, 37–40 |
| Is the daily summary the only index for the non-consolidated acts? | **Yes.** Every alternative probed returns 404/400 | reqs 47–51, 86–88 |
| What does that population cost? | **~14,926 requests, ~2.0 GB, ~1 h at 4 req/s** — and it is **~110,000 acts** | 30-day sample + calendar arithmetic |
| Is #66's premise still true? | **Yes.** `…/id/BOE-A-2014-12329/metadatos` → **404** today | req 51 |

The single most consequential number: adding the non-consolidated section-I acts
since 1979 takes the repo from **12,299 files to roughly 122,000** — a **10×**
multiplication. That is the number the sharding decision has to be sized against.

---

## 1. What the documentation actually says (read, not guessed)

Fetched and read (reqs 2–7):

| Document | URL | Verdict |
|---|---|---|
| Open-data index / API reference | `/datosabiertos/api/api.php` | Full parameter list for every endpoint |
| Consolidated-legislation API spec (PDF, 12 pp, dated 2025-09-02) | `/datosabiertos/documentos/APIconsolidada.pdf` | **The real spec.** Documents `query`, `sort`, `range`, `limit=-1` |
| BOE summary API spec (PDF) | `/datosabiertos/documentos/APIsumarioBOE.pdf` | One endpoint, one path parameter, no query parameters |
| FAQ · consolidada | `/datosabiertos/faq/consolidada.php` | Consolidation lag is **1–3 days** after publication; `estado_consolidacion` = `desactualizado` while pending |
| XSD bundle | `/datosabiertos/definitions/download_schema.php?id=legislacion-consolidada-completa` | ZIP of `lista-consolidada.xsd` + `tipos.xsd` |

`GET /datosabiertos/api/legislacion-consolidada` takes **five** parameters, all
optional — this is the part `catalogo.py` never knew about:

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `from` | `AAAAMMDD` | oldest update date | filters **`fecha_actualizacion`**, not publication |
| `to` | `AAAAMMDD` | today | idem |
| `query` | JSON string | empty | `{"query":{"query_string":{...},"range":{...}},"sort":[...]}` |
| `offset` | int | 0 | |
| `limit` | int | **50** | doc says `-1` = "the complete list"; **it is capped at 10,000** (§2.1) |

Fields addressable inside `query_string`: `ambito@codigo`, `departamento@codigo`,
`rango@codigo`, `fecha_disposicion`, `numero_oficial`, `titulo`,
`fecha_publicacion`, `diario_numero`, `vigencia_agotada`,
`estado_consolidacion@codigo`, `materia@codigo`, `texto` (full text of the norm).
`range` works on date fields. `sort` takes any response field, `asc`/`desc`.

`GET /datosabiertos/api/boe/sumario/{AAAAMMDD}` takes **nothing** but the date.
Confirmed by experiment: `?limit=-1` → **400** (req 88), `/sumario/2026` → **400**
(req 86).

---

## 2. The consolidated catalogue (issue #99)

### 2.1 Total, and the real `limit` ceiling

| Request | Items returned | Bytes | Wall |
|---|---|---|---|
| no parameters (req 8) | 50 | 63,259 | 0.79 s |
| `?limit=-1` (req 9) | **10,000** | 13,002,973 | 24.2 s |
| `?limit=20000&offset=0` (req 10) | **10,000** | 13,002,973 | 22.3 s |
| `?limit=-1&offset=10000` (req 26) | **2,385** | 2,979,294 | 3.2 s |

`limit=-1` does **not** return the complete list as the PDF claims — the server
caps any page at **10,000 items**. `limit=20000` returns byte-identical content to
`limit=-1`, so the cap is a hard server ceiling, not a parameter error. The
engine's own comment in `fetch.py` ("the API has a 10,000 per request limit") is
correct; its `batch = 1000` is 10× more conservative than it needs to be.

**Exact total = 12,385**, found by binary search on `offset` with `limit=1`
(reqs 11–25, 15 requests, 1.3 KB each): `offset=12384` → 1 item
(`BOE-A-1887-4896`), `offset=12385` → `"data": ""`.

So a complete enumeration is **2 requests, 16.0 MB, ~28 s**.

### 2.2 What is in it

From the 12,385 items (union of reqs 9 and 26, saved as `catalog_all.json`):

| Dimension | Measurement |
|---|---|
| `ambito` | 8,767 Estatal · 3,618 Autonómico |
| Identifier prefixes | `BOE-A` 12,140 · 245 regional-gazette ids across 15 prefixes (`BOJA-b` 58, `BOA-d` 44, `BORM-s` 31, `DOGV-r` 30, `BOCL-h` 21, `DOGC-f` 20, `BOC-j` 11, `BOIB-i` 8, `BON-n` 6, `DOCM-q` 3, `BOCT-c` 3, `DOG-g` 3, `BOPV-p` 3, `BOCM-m` 2, `DOE-e` 2) |
| `estado_consolidacion` | 12,190 Finalizado · **195 Desactualizado** (an amendment published but not yet folded in) |
| `vigencia_agotada` | 9,973 `N` · 2,412 `S` |
| Top `rango` | Ley 3,807 · Real Decreto 3,495 · Orden 2,399 · Resolución 832 · Real Decreto-ley 309 · Decreto-ley 289 · Acuerdo Internacional 254 · Ley Foral 207 · Ley Orgánica 184 |
| `fecha_publicacion` span | **1835-11-07** (`BOE-A-1835-2348`) → 2026-09-03 |
| `fecha_actualizacion` span | **2023-12-15T13:03:25Z** → 2026-09-03T09:36:30Z |
| Publication by decade | 1830s–1950s 72 · 1960s 92 · 1970s 311 · 1980s 992 · 1990s 1,601 · 2000s 2,899 · 2010s 3,611 · 2020s 2,548 |

The 245 non-`BOE-A` identifiers matter for the layout: they are regional-gazette
norms that the BOE consolidates without a BOE document number. They already exist
in the repo, so this is not new — but any id-shaped assumption in the sharding
scheme has to survive `DOGC-f-2019-90497` as well as `BOE-A-1978-31229`.

### 2.3 Is the `offset` walk stable?

The listing is ordered by `fecha_actualizacion` **descending** and the collection
mutates while you page. Two independent findings:

1. **Measured, not reasoned.** Page 1 was fetched at req 9 and page 2 at req 26,
   roughly **15 minutes apart**. Union: 10,000 + 2,385 = **12,385 distinct
   identifiers, zero duplicates, zero gaps** — and 12,385 is exactly the total the
   binary search (req 25, taken *between* the two page fetches) independently
   found. A 15-minute walk drifted by nothing.
2. **Structurally, the drift can only duplicate, never skip.** Items enter this
   ordering only at the front (a norm's `fecha_actualizacion` is set to *now*, or a
   new norm is consolidated). A front insertion shifts everything down one place,
   so the item at index 9,999 reappears at index 10,000 — a duplicate the caller
   dedupes away. Only a *removal* from the collection could shift items up and skip
   one. With 2 pages and ~28 s of walk, the exposure is negligible.
3. **And it is avoidable entirely.** `sort` works (reqs 27–28):
   `query={"sort":[{"identificador":"asc"}]}` with `offset=0` and `offset=5`
   returned two contiguous, non-overlapping runs
   (`BOA-d-1991-90001 … BOA-d-2001-90002` then `BOA-d-2004-90019 …`).
   `identificador` never changes, so sorting by it makes the walk stable by
   construction. Cost: nothing.

`range` + `query_string` + `sort` compose (reqs 103–104), so if the catalogue ever
outgrows two pages the walk can be sharded by publication year instead of paged by
offset — each shard stays under the 10,000 cap and is independently resumable:

```
query={"query":{"range":{"fecha_publicacion":{"gte":"20200101","lte":"20201231"}}},
       "sort":[{"identificador":"asc"}]}
```

### 2.4 `?from=&to=` is not a history sweep

| Window | Items | Request |
|---|---|---|
| `from=19900101&to=19901231&limit=-1` | **0** | req 31 |
| `from=20000101&to=20101231&limit=-1` | **0** | req 32 |
| `from=20231214&to=20231214&limit=-1` | **0** | req 33 |
| `from=20231215&to=20260903` | **all 12,385** (offset 12384 → 1 item, 12385 → empty) | reqs 37–40 |
| `from=20260901&to=20260903&limit=-1` | 31 | req 34 |
| `from=20260902&to=20260902&limit=-1` | 13 | req 35 |
| `from=20260801&to=20260903` (no `limit`) | **50** — the default applies to windows too | req 36 |

The BOE re-stamped the entire collection on **2023-12-15**; nothing is older.
Sweeping windows backwards therefore enumerates **the same 12,385 norms** as the
plain walk once you reach 2023-12-15, and **nothing at all** before it. A window
sweep is a *change feed*, not a *historical index*. Its only correct use is the
daily.

Daily volume, measured: **13 norms** re-consolidated on 2026-09-02, **31** across
2026-09-01…03. One request per run, ~16–40 KB.

### 2.5 The drift the current daily is causing — 86 norms missing today

Comparing `catalog_all.json` against the 12,300 `.md` files in
`/Users/neli/projects/legalize/countries/es` (clean at `origin/main`):

- **86 catalogue norms have no file in the repo.** 77 Estatal, 9 Autonómico.
- **1 file in the repo is not in the catalogue** — and it is `README.md`. There
  are no orphans.
- **All 86** have `fecha_actualizacion` in **2026**. **74 of 86** were *published*
  before 2026 (one in the 1980s, two in the 1990s, three in the 2000s, sixteen in
  the 2010s, sixty-four in the 2020s). Only 25 were published in the last 90 days.

That distribution names the mechanism. `fetcher/es/daily.py::_commit_reforms`
walks the `from`/`to` window and then does:

```python
file_path = norm_to_filepath(metadata)
if not repo.has_file(file_path):
    logger.debug("Skipping %s — not in repo", norm_id)
    continue
```

When the BOE consolidates a norm **for the first time** — an old Real Decreto from
1982, say — it appears in the window with a 2026 update date and no file in the
repo, and the daily throws it away. The summary path cannot rescue it either,
because the norm was published in 1982 and today's summary does not mention it.
**A norm that becomes consolidated after the bootstrap can never enter the repo.**
86 in roughly eight months ≈ **130/year, growing**. The republish fixes the backlog;
only removing that `continue` (or routing it to the new-law path) stops it
recurring.

---

## 3. The non-consolidated population (issue #66)

### 3.1 The premise is still true

`GET /datosabiertos/api/legislacion-consolidada/id/BOE-A-2014-12329/metadatos`
→ **404 `La información solicitada no existe`** (req 51), exactly as #66 reported.
Its diary XML is fine: `https://www.boe.es/diario_boe/xml.php?id=BOE-A-2014-12329`
→ **200, 263,932 bytes** (req 85), with four top-level children —
`metadatos`, `metadata-eli`, `analisis`, `texto` — and an `<analisis>` carrying
**12 `referencias/anteriores/anterior`** entries with their verbs
(`DEROGA BOE-A-1998-9477`, `DEROGA BOE-A-1997-28053`, `MODIFICA BOE-A-2013-11331`, …)
and 1 posterior. Everything Stage C needs is in that one document.

### 3.2 Every alternative index I could find, and what it returned

| Candidate | Request | Result |
|---|---|---|
| `https://www.boe.es/sitemap.xml` | req 48 | **404** (HTML error page) |
| `Sitemap:` directive in `robots.txt` | req 47/52 | **none** — 13,901 lines, zero `Sitemap:`, zero `Crawl-delay:` |
| OAI-PMH at `/oai` | req 87 | **404** |
| Summary by document id: `xml.php?id=BOE-S-20260902` | req 49 | **400** |
| Year-level summary: `/api/boe/sumario/2026` | req 86 | **400** |
| Summary with paging: `/api/boe/sumario/20260902?limit=-1` | req 88 | **400** |
| ELI permalink of a non-consolidated act: `/eli/es/l/2014/11/27/28` | req 50 | **200 but HTML** (287,345 B) — resolves a *known* act, indexes nothing |
| Bulk download of the diary | docs index (req 2), api.php (req 3) | Not offered. The open-data page lists four APIs and nothing else |
| `query_string` search over the diary | — | The `query` parameter belongs to `legislacion-consolidada`; by definition it cannot return an act with no consolidated text |

Blind id enumeration is a non-starter too: `BOE-A-`, `BOE-B-` and `BOE-C-` share
one sequential counter per year, so walking `BOE-A-{year}-{n}` would 404 on the
overwhelming majority (2014 alone runs past document 150,000, of which only a few
thousand are section-I dispositions).

**The daily summary is the only index.** Nothing else enumerates.

### 3.3 How far back the summary reaches

| Probe | Result |
|---|---|
| 1960-08-15, 1960-07-15, 1960-06-15/16, 1960-01-02/04 | **404** (reqs 105, 106, 64, 65, 41, 53) |
| **1960-09-15** | **200, 36,338 B** (req 107) |
| 1960-10-03, 1960-10-15 | 200 (reqs 108, 66) |
| 1959-10-15, 1958-10-15, 1955-01-03, 1950-01-03, 1940-01-02, 1930-01-02, 1900-01-02, 1870-01-03, 1661-01-01 | **404** (reqs 109, 110, 54–60) |

Coverage begins **between 1960-08-15 and 1960-09-15** and is complete from there.
The API therefore reaches ~19 years further back than the 1979 floor the
orchestrator assumed; whether to use that reach is a scope decision, not a
technical limit (§3.5 prices both).

### 3.4 What a summary day contains — 30-day stratified sample

Thirty publication days sampled with two seeded RNGs (`p10_sample.py` seed
20260903, eight era-stratified pairs 1979/1985/1992/1999/2006/2013/2020/2025;
`p12_sample2.py` seed 777, fourteen uniform-random non-Sunday days in
1979-01-01…2026-09-01). Full per-day table in `sumario_sample.json`.

**All 30 returned HTTP 200** — every non-Sunday sampled day had an issue.

| Metric (per publication day) | Mean | 95% CI | Median | Range |
|---|---|---|---|---|
| Items, **all** sections | 189.9 | — | — | 70–367 |
| Section **I + 1A + T** (what `sumario.py::_LEGISLATIVE_SECTIONS` accepts) | **8.17** | ±2.24 | 6 | 1–27 |
| Section **1/1A only** (no Constitutional Court) | **6.33** | ±1.23 | — | 1–17 |
| Response bytes (XML) | **135,680** | ±19,830 | 148,897 | 56,960–214,071 |

Of the 245 section-I+T dispositions in the sample, **20 (8.2 %) are already in
the consolidated catalogue**. The other 91.8 % exist only as diary documents.

Two format facts for sizing:

- **No compression on the wire.** `Content-Encoding` is absent and
  `Content-Length` equals the decoded length (214,071 = 214,071, req 83) even
  though `requests` advertises gzip. The byte figures above *are* the transfer cost.
- **Ask for XML, not JSON.** The same day as JSON is **413,098 B** vs **214,071 B**
  as XML — 1.93× (reqs 83, 84).

### 3.5 The cost of the sweep, and the size of the population

Publication days, two independent methods that agree to 1 %:

| Method | 1979-01-01 → 2026-09-03 |
|---|---|
| Calendar days (17,413) minus Sundays (2,487) | **14,926** |
| Σ max(`diario_numero`) per year over 1979–2025, from the catalogue itself (BOE numbers its issues sequentially within the year, so the highest number seen is a lower bound on issues published) | **14,755** for 47 years = **314/year**; ×47.68 years = **14,970** |

Taking **14,926 publication days** (and 20,560 for the 1960-09 floor):

| | 1979-01-01 → today | 1960-09 → today |
|---|---|---|
| Summary requests | **14,926** | 20,560 |
| Transfer (XML, uncompressed) | **2.03 GB** (CI 1.73–2.32) | 2.79 GB |
| Wall clock @ 1 req/s | 4.1 h | 5.7 h |
| Wall clock @ 4 req/s (`config.yaml`'s `requests_per_second`) | **1.0 h** | 1.4 h |
| Section I+T dispositions — **EXTRAPOLATED** (14,926 × 8.17) | **121,896** (CI 88,493–155,298) | 167,907 |
| Section 1/1A only — **EXTRAPOLATED** (14,926 × 6.33) | **94,531** (CI 76,118–112,945) | — |
| minus the 11,713 that *are* consolidated (exact count from the catalogue, `fecha_publicacion ≥ 1979-01-01`) | **≈ 110,200 non-consolidated acts** | — |

> **EXTRAPOLATED.** Base measurement: 245 section-I+T items over 30 sampled
> publication days (8.17/day, sd 6.26). Multiplier: 14,926 publication days.
> The interval is wide because the per-day count is lumpy — the Constitutional
> Court dumps 17–18 rulings on a single day (1992-03-17, 2025-12-26) and section I
> ranges from 1 to 27. Treat 122K ± 33K as the honest bracket, and re-measure
> against the real sweep before sizing storage: the sweep itself produces the
> exact count as a by-product.

**What this means for the repo.** Today: 12,299 laws. Ingesting section I+1A+T
back to 1979 takes it to roughly **122,000 files, a 10× multiplication** —
and the git history multiplies with it. This is the number the sharding scheme
(spec v0.4 `{directory}/…`) has to be chosen against, not the current 12,299.
Restricting to sections 1/1A (dropping Constitutional Court rulings) saves ~27,000
files; starting at 1979 instead of 1960 saves ~46,000.

### 3.6 One compliance finding: `robots.txt` names documents, not paths

`https://www.boe.es/robots.txt` is **487,479 bytes, 13,901 lines, 12,148
`Disallow:` entries** (reqs 47 and 52). There is **no blanket path ban** — nothing
disallows `/datosabiertos`, `/diario_boe`, `/boe/dias` or `/buscar` as a prefix,
no `Crawl-delay`, no `Sitemap`. What it holds instead is **1,740 distinct document
identifiers** (845 `BOE-A`, 805 `BOE-B`, 75 `BOE-C`, 15 `BOE-T`), each listed
three times (`/*{id}.pdf`, `/*{id}&`, `/*{id}$`) — the BOE's anonymised /
right-to-be-forgotten suppressions.

**None of the 845 `BOE-A` ids is in the consolidated catalogue, and none is in the
repo today.** That is luck, not design: the consolidated corpus never touched
them. A section-I diary sweep can, so the discovery must filter the ids in
`robots.txt` out of its output. That file is 487 KB, one request, parsed once per
bootstrap — trivial, and the only place it can be enforced cheaply is discovery.

---

## 4. Where the code is, and why nothing works today

`BOEDiscovery` (`src/legalize/fetcher/es/discovery.py`) is **unreachable in both
directions** — issue #99 is right about `discover_all` and slightly generous about
`discover_daily`:

| Path | What happens |
|---|---|
| `legalize bootstrap -c es` → `pipeline.discover_norm_ids` → `discovery.discover_all` | `ImportError: iter_norms_from_catalog` — a name that has never existed in `catalogo.py` |
| `legalize daily -c es` | `cli.py:528` prefers a country's own `daily.py`, and `fetcher/es/daily.py` calls `sumario.parse_summary` **directly** (line 197). `BOEDiscovery.discover_daily` is **never called at all** |

So the class has no live caller. Beyond the invented name, the two functions that
*do* exist in `catalogo.py` cannot be used as they stand:

- `pipeline.py:456` constructs discovery as
  `get_discovery_class(country).create({**cc.source, "cache_dir": cc.data_dir})` —
  a **plain dict**. `iter_fixed_norms(config)` and
  `iter_norms_from_summaries(client, config, …)` both call `config.get_country("es")`.
- They read `cc.source["normas_fijas"]` and `cc.source["rangos"]`. Spain's
  `source:` block in `config.yaml` (lines 42–47) holds only `base_url`,
  `request_timeout`, `max_retries`, `requests_per_second`, `user_agent`.
- `pipeline.py:238` (`generic_daily`) constructs discovery with
  `cc.source or {}` — **without** `cache_dir`. Any design that caches inside
  discovery must not depend on `cache_dir` being present on the daily path.

The interface `discover_all` has to satisfy is one method returning
`Iterator[str]` of norm ids; `pipeline.discover_norm_ids` already caches the
result to `{data_dir}/discovery_ids.txt` and honours `--limit/--offset/--rediscover`.

---

## 5. Recommended design — one discovery, two surfaces

`BOEDiscovery` gets **two enumerators and no configuration decisions of its own**,
in the shape `pt` already uses (`fetcher/pt/discovery.py`: sitemaps for speed, a
journal walk for completeness, `cache_dir` read from `source` in `create`).

### 5.1 `discover_all` — the consolidated catalogue (#99)

```
def discover_all(client, **kw):
    seen = set()
    offset = 0
    while True:
        page = GET /api/legislacion-consolidada
               ?limit=-1&offset={offset}
               &query={"sort":[{"identificador":"asc"}]}     # stable key
        if not page: break
        for item in page:                                     # 10,000 per page
            if item.identificador not in seen and not suppressed(item.identificador):
                seen.add(...); yield item.identificador
        offset += len(page)
```

- **2 requests, 16.0 MB, ~28 s** for all 12,385 ids today. Measured, not estimated.
- `sort` by `identificador` removes the ordering instability that the default
  `fecha_actualizacion desc` carries. Dedupe by id anyway — it costs a set.
- `suppressed()` is the `robots.txt` id set from §3.6, fetched once.
- **Do not** filter `ambito` here. Both 8,767 state and 3,618 autonomous norms are
  already published in the repo's 18 directories; the jurisdiction split belongs in
  `metadata.py`, where `_DEPT_TO_JURISDICTION` already lives.
- Resumability: `pipeline.discover_norm_ids` already writes
  `{data_dir}/discovery_ids.txt`. Nothing to add.
- **Escape hatch, not needed today:** if the catalogue ever passes ~20,000, swap
  the offset loop for year shards using
  `{"query":{"range":{"fecha_publicacion":{"gte":…,"lte":…}}},"sort":[…]}`
  (verified working, reqs 103–104). Each shard is independently resumable and
  cannot hit the 10,000 cap. **Do not build this now** — two pages do not need a
  sharding scheme.

### 5.2 `discover_published` — the diary sweep (#66)

A second enumerator, because it answers a different question and costs 7,000×
more. It is **not** `discover_all` and must not be called by it.

```
def discover_published(client, start: date, end: date, **kw):
    for day in days(start, end):
        if day.weekday() == SUNDAY: continue
        xml = cached_get(f"/api/boe/sumario/{day:%Y%m%d}")    # Accept: application/xml
        if 404: continue                                       # holidays, pre-1960-09
        for item in sections {1, 1A, T}:
            if item.id not in seen and not suppressed(item.id):
                yield item.id
```

- **14,926 requests, 2.03 GB, ~1 h at 4 req/s** for 1979→today. ~122,000 ids.
- **XML, not JSON** — JSON is 1.93× the bytes for identical content.
- **Cache to disk, keyed by date, permanently.** A summary for 1985-04-16 can never
  change; re-running the sweep must cost zero requests. `FileCache`
  (`fetcher/cache.py`) hashes the URL and has a **24-hour TTL** — that TTL is wrong
  for this and the sweep should write its own `{cache_dir}/sumarios/{YYYY}/{YYYYMMDD}.xml`
  instead, exactly as `pt`'s discovery keeps `{cache_dir}/sitemaps/`.
  That directory *is* the resumability: a killed run resumes at the first missing file.
- 404 is normal, not an error: it means no issue that day. All 30 sampled
  non-Sunday days returned 200, so 404s should be rare — but log the count, because
  a sudden run of them is how a source outage would look.

### 5.3 Config keys

Three new keys under `countries.es.source`, replacing the two that no longer exist:

```yaml
  es:
    source:
      base_url: "https://www.boe.es/datosabiertos"
      # ... existing connection settings unchanged ...
      earliest_summary_date: "1979-01-01"   # the sweep floor; source reaches 1960-09
      summary_sections: ["1", "1A", "T"]    # replaces the vanished `rangos`
      cache_dir: ""                         # injected by pipeline.discover_norm_ids
```

- `normas_fijas` **does not come back**. It was a bootstrap crutch from Phase 2;
  `discover_all` now returns the complete catalogue in two requests, which is
  strictly better than any hand-maintained list.
- `rangos` **does not come back either**. Rank filtering was the wrong axis: the
  catalogue is already curated by the BOE ("las normas más relevantes del
  ordenamiento jurídico" — FAQ), and for the diary the meaningful filter is the
  *section*, which is what the summary actually states. `sumario.py` already hard-codes
  `_LEGISLATIVE_SECTIONS = {"1","1A","T"}`; move it to config and delete
  `ScopeConfig.ranks`, whose only effect today is to drop dispositions whose rank
  `_infer_rank_from_title` failed to guess.
- `create(source: dict)` reads these off the dict — matching every other country
  (`pt`, `uk`, `at`, …) and fixing the `Config`-vs-dict mismatch in #99 by deleting
  the assumption rather than plumbing a `Config` through.
- **Delete** `catalogo.py`. `iter_fixed_norms` loses its config key and
  `iter_norms_from_summaries` becomes `discover_published` with a cache. Keeping
  them "because they are the two halves of the feature" (commit `2d9775d`) was the
  right call while the caller was broken; once the caller is written they are two
  dead functions reading keys that do not exist.

### 5.4 Total request cost

| Run | Consolidated | Diary | Total |
|---|---|---|---|
| **Full bootstrap, discovery only** (first time) | 2 | 14,926 | **14,928** (~1 h at 4 req/s, ~2.0 GB) |
| **Full bootstrap, discovery only** (re-run, summaries cached) | 2 | 0 | **2** |
| **Daily** | 1 (`?from=<last>&to=<today>&limit=-1`) | 1 (today's summary) | **2** |
| **Backfill of N days** | 1 | N | N+1 |

The daily stays at two discovery requests regardless of window width, because
`from`/`to` accepts a range and the 10,000 cap is ~770× the observed daily volume
of 13. Fetching the norms themselves is a separate cost and out of this probe's
scope.

### 5.5 Two things this design must also change

1. **Drop the `if not repo.has_file(...): continue` guard** in
   `daily.py::_commit_reforms`, or route that case to the new-law path. It is the
   measured cause of the 86 missing norms (§2.5) and it will keep costing ~130
   norms a year after the republish.
2. **Honour `estado_consolidacion`.** 195 of 12,385 norms are `Desactualizado` —
   the BOE has published an amendment but has not folded it in yet (FAQ: 1–3 days).
   Committing one of those files stamps a text that is knowably stale. The daily
   should re-queue a `desactualizado` norm rather than treat its text as final.

---

## 6. Open questions this probe did not settle

- **Scope of the diary ingest.** 122,000 files at 1979, 168,000 at 1960, or 95,000
  if Constitutional Court rulings are excluded. That is a product decision, and it
  changes the sharding scheme's fan-out by 1.8×.
- **Sections beyond I.** Section III ("Otras disposiciones", ~25 items/day) holds
  material some users would call legislation. Not measured for consolidation
  overlap; it would roughly quadruple the corpus again.
- **What a non-consolidated act's Markdown looks like.** `<texto>` in the diary XML
  is a flat run of `<p class="…">` — a different shape from the consolidated
  `<bloque>` structure the transformer expects. Probe 2's territory, not this one.
- **The `texto` search field.** `query_string` can search the full text of
  consolidated norms server-side. Irrelevant to discovery, potentially interesting
  for the site.

---

## Appendix — HTTP budget

**110 requests to `www.boe.es`**, 2026-09-03, 0.5–1.0 s apart, single-threaded.
No 429, no 5xx, no retry.

| Reqs | Purpose |
|---|---|
| 1–7 | Documentation: open-data index, `api.php`, FAQ, XSD, two PDFs |
| 8–10 | Catalogue: default page, `limit=-1`, `limit=20000` |
| 11–25 | Binary search for the exact total (12,385) |
| 26 | Catalogue page 2 (`offset=10000`) |
| 27–30 | `sort` by `identificador`, `sort` by `fecha_publicacion`, `query_string` on `ambito` |
| 31–40 | `from`/`to` window behaviour |
| 41–46, 53–66, 105–110 | Summary reach: 1661 → 1979 |
| 47–52 | Alternative indexes: `robots.txt`, `sitemap.xml`, `BOE-S` id, ELI, `metadatos` of a non-consolidated act |
| 67–82, 89–102 | 30-day stratified summary sample |
| 83–85 | Compression check, XML vs JSON, diary XML of `BOE-A-2014-12329` |
| 86–88 | `/sumario/2026`, `/oai`, `/sumario/…?limit=-1` |
| 103–104 | `range` + `query_string` + `sort` composition |
