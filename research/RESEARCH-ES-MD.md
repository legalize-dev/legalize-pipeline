# RESEARCH-ES-MD — Comunidad de Madrid (es-md)

Status: **Step 0 (research) in progress.** Spike of 2 fixtures saved. Not yet a parser, not yet a code change. This file is the source of truth for whether/how to add Madrid as a subjurisdiction of `es`.

## TL;DR

- Madrid is **already partially covered** by the `es` fetcher: BOE classifies autonomic laws under jurisdiction `es-md` (departamento code `8131` → `es-md` in `fetcher/es/metadata.py:207`). Whatever Madrid `Ley`/`Decreto Legislativo` BOE consolidates ends up in `legalize-es/es-md/`.
- BOE only republishes **rango-ley** of the CCAA. The bulk of Madrid normativa — `Decretos del Consejo de Gobierno`, `Órdenes de Consejería`, `Resoluciones`, `Acuerdos` — is published **only in BOCM** (Boletín Oficial de la Comunidad de Madrid) and is currently NOT in the engine.
- BOCM exposes a clean **XML + JSON-LD** open-data feed: per-issue sumario and per-disposition document. Coverage from **2010-02-15 to today** confirmed by probe.
- BOCM does **NOT** consolidate text. Each disposition is a single snapshot at publication. For consolidated text + version chain we'd need either BOE (already covered for `Ley`) or `gestiona.comunidad.madrid/wleg_pub` (a JSF app, hard to scrape; for Madrid-only consolidation of laws).
- Major fidelity caveat: BOCM `<texto>` is plain text — tables, bold, italic, lists are **flattened**. Tables only survive in PDF. This is acceptable for `Decretos`/`Órdenes` (rare tables) but not for `Leyes de Presupuestos` etc. (BOE remains the source for those).
- **Recommendation**: ship Madrid in two phases.
  - **Phase A (low cost, ~days)**: ensure the existing `es` bootstrap actually pulls every BOE-A-* with `ambito=2`+`departamento=8131`. These are the consolidated leyes of Madrid. They go into `legalize-es/es-md/` with full version history (already supported by metadata + sumario code; only the discovery scope may need widening).
  - **Phase B (new fetcher, ~1–2 weeks)**: add `fetcher/es-md/` (or extend `fetcher/es/` with a BOCM client) to ingest BOCM dispositions of Section I.A (`Disposiciones Generales`) since 2010-02-15. Single-snapshot, one commit per publication. This catches the long tail of decretos/órdenes/resoluciones not in BOE.
- Hard dependency before Phase B: agree on whether decretos/órdenes (no version history available) meet our priority #2 bar, or if we ship them as documented single-snapshot.

## 0.1 Sources

### Primary: BOCM (Boletín Oficial de la Comunidad de Madrid)

- Site: https://www.bocm.es
- Open data XML/JSON-LD endpoints (no auth, no rate-limit doc, `Crawl-delay: 10` in robots.txt)
- Coverage: 2010-02-15 → today (verified by probing weekday issues at 2010, 2015, 2020, 2024, 2026)
- Publishes **every day except Sundays, Good Friday, Dec 25, Jan 1**
- License: Law 37/2007 reuse of public sector information + attribution required (similar to UK OGL). No CC0.

#### Endpoints

```
# Daily sumario (issue index) — XML
GET https://www.bocm.es/boletin/CM_Boletin_BOCM/{YYYY}/{MM}/{DD}/BOCM-{YYYYMMDD}{NNN}.xml
    where NNN = three-digit issue number for that day (e.g. 099)
    Note: server tolerates a "wrong" issue number and redirects to the actual one;
    we should still derive NNN from a calendar-aware index pass.

# Per-disposition document
GET https://www.bocm.es/boletin/CM_Orden_BOCM/{YYYY}/{MM}/{DD}/BOCM-{YYYYMMDD}-{N}.{xml|json|PDF|epub}
    The "CM_Orden_BOCM" path component is fixed regardless of rango.
    Verified for LEY (BOCM-20241230-1), DECRETO (BOCM-20260304-1), ORDEN (BOCM-20260428-1).
```

#### Sumario XML structure (verified, fixture `tests/fixtures/es-md/sample-sumario-recent.xml`)

```xml
<sumario>
  <metadatos>
    <diario>Boletín Oficial de la Comunidad de Madrid</diario>
    <publicacion>BOCM</publicacion>
    <identificador>BOCM-20260428</identificador>
    <numero>99</numero>
    <fecha_publicacion>2026/04/27</fecha_publicacion>
    <url_html_sumario>...</url_html_sumario>
    <url_xml_sumario>...</url_xml_sumario>
    <url_pdf_sumario>...</url_pdf_sumario>
    <url_pdf_diario>...</url_pdf_diario>
  </metadatos>
  <diario numero="99">
    <sumario_diario>...</sumario_diario>
    <secciones>
      <seccion nombre="I. COMUNIDAD DE MADRID">
        <apartado nombre="A) Disposiciones Generales">
          <organismo nombre="...">
            <disposicion numero="1">
              <identificador>BOCM-20260428-1</identificador>
              <rango>LEY|DECRETO|ORDEN|RESOLUCIÓN|ACUERDO|CORRECCIÓN|EXTRACTO</rango>
              <titulo>...</titulo>
              <url_html>...</url_html>
              <url_xml>...</url_xml>
              <url_json_ld>...</url_json_ld>
              <url_pdf>...</url_pdf>
              <url_epub>...</url_epub>
            </disposicion>
          </organismo>
        </apartado>
      </seccion>
      <seccion nombre="I. COMUNIDAD DE MADRID">
        <apartado nombre="B) Autoridades y Personal">...</apartado>
      </seccion>
      ...
    </secciones>
  </diario>
</sumario>
```

Sections used in BOCM:
- **I.A — Disposiciones Generales** ← legislative core (Leyes, Decretos legislativos, Decretos, Órdenes y Resoluciones de ámbito genérico). **This is what we ingest.**
- I.B — Autoridades y Personal (HR moves, skip)
- I.C — Otras Disposiciones (sometimes legislative, mostly individual acts; case-by-case)
- I.D — Anuncios (skip)
- II — Disposiciones del Estado (already in BOE, skip)
- III, IV, V — Local, Justicia, Otros Anuncios (skip)

The 2024-12-30 issue (310 pages) had only these rangos in I.A: `LEY`, `ORDEN`, `RESOLUCIÓN`, `ACUERDO`, `CORRECCIÓN`, `EXTRACTO`. `DECRETO` confirmed in 2026-03-04 issue.

#### Disposition XML structure (verified, fixture `tests/fixtures/es-md/sample-ley-presupuestos.xml`)

```xml
<documento>
  <metadatos>
    <identificador>BOCM-20241230-1</identificador>
    <origen_legislativo>Comunidad de Madrid</origen_legislativo>
    <departamento>PRESIDENCIA DE LA COMUNIDAD</departamento>
    <rango>LEY</rango>                        <!-- empty for some Órdenes -->
    <fecha_publicacion>2024/12/30</fecha_publicacion>
    <fecha_disposicion>2024/12/26</fecha_disposicion>   <!-- enactment date, often empty -->
    <titulo>...</titulo>
    <diario codigo="BOCM">...</diario>
    <pagina_inicial>1</pagina_inicial>
    <pagina_final>1</pagina_final>
    <diario_numero>310</diario_numero>
    <seccion>I.  COMUNIDAD DE MADRID</seccion>
    <url_html|url_xml|url_json_ld|url_pdf|url_epub>...</url_*>
    <consolidada_por>https://gestiona.comunidad.madrid/wleg_pub/servlet/Servidor?opcion=VerHtml&nmnorma=13921</consolidada_por>
  </metadatos>
  <metadatos_eli>
    <rdf:RDF xmlns:eli="http://data.europa.eu/eli/ontology#">
      <eli:LegalResource rdf:about="...">...</eli:LegalResource>
    </rdf:RDF>
  </metadatos_eli>
  <analisis>
    <seccion>I. COMUNIDAD DE MADRID</seccion>
    <apartado>A) Disposiciones Generales</apartado>
    <organismo>...</organismo>
    <tipo_disposicion>LEY</tipo_disposicion>
  </analisis>
  <texto>... plain text, preserves "Artículo N", "Título I", "Capítulo II" headings; flattens tables/lists/bold ...</texto>
</documento>
```

Important: only laws get a `<consolidada_por>` link to wleg_pub. Decretos and órdenes do not — they stay single-snapshot.

### Secondary: BOE Legislación Consolidada (already wired)

- The BOE's `legislacion-consolidada` API consolidates **leyes autonómicas of Madrid** (rango: `Constitución`/`Estatuto`, `Ley`, `Decreto Legislativo`, `Decreto-ley`).
- These already classify under `es-md` via `_DEPT_TO_JURISDICTION` in `src/legalize/fetcher/es/metadata.py:207`.
- BOE's "Código de la Comunidad de Madrid" (https://www.boe.es/biblioteca_juridica/codigos/codigo.php?id=208) lists 116 such laws (Estatuto + 115 leyes/decretos legislativos in force).
- BOE provides full version history embedded as `<bloque>` XML (same path the existing `fetcher/es` parser uses).
- License: BOE reuse terms (open with attribution).

### Tertiary: Asamblea de Madrid

- https://www.asambleamadrid.es/servicios/normativa
- Compiles state + autonomic norms relevant to the parliament.
- Useful as a sanity catalog, not as a data source (no API; HTML browse only).

### Tertiary: gestiona.comunidad.madrid/wleg_pub

- The Madrid government's own **consolidated text database** for autonomic laws.
- JSF/PrimeFaces app, no clean API. URL pattern `?opcion=VerHtml&nmnorma={id}` returns full HTML.
- Could be used to cross-validate BOE consolidations of Madrid laws, but extracting structured XML from a JSF page is fragile. **Skip in v1.**

## 0.2 Fixtures saved

In `engine/tests/fixtures/es-md/` (within this worktree branch `worktree-research-es-md`):

| File | Source | Identifier | Bytes | Why |
|---|---|---|---|---|
| `sample-sumario-recent.xml` | BOCM 2026-04-28 sumario | BOCM-20260428 (#99) | 4.99 MB | Recent issue index |
| `sample-sumario-2024.xml` | BOCM 2024-12-30 sumario | BOCM-20241230 (#310) | 5.27 MB | Year-end issue with Ley de Presupuestos |
| `sample-ley-presupuestos.xml` | BOCM | BOCM-20241230-1 | 305 KB | Ley 9/2024 Presupuestos — large law with sectioning, art numbering |
| `sample-ley-presupuestos.json` | BOCM JSON-LD | BOCM-20241230-1 | 305 KB | Same law in JSON-LD |
| `sample-decreto.xml` | BOCM | BOCM-20260304-1 | 58.8 KB | Decreto 15/2026 del Consejo de Gobierno |
| `sample-decreto.json` | BOCM JSON-LD | BOCM-20260304-1 | 61 KB | Same in JSON-LD |
| `sample-orden.xml` | BOCM | BOCM-20260428-1 | 6.3 KB | Orden de Libre Designación (small, baseline) |
| `sample-orden-2010.xml` | BOCM | BOCM-20100301-1 | 4.0 KB | Old format — proves the XML feed goes back to 2010 |

Missing fixtures (acceptable gap): `Decreto Legislativo` (rare in Madrid, would come via BOE anyway), `Acuerdo`. Can be added later.

## 0.3 Metadata inventory

### BOCM disposition fields → mapping

| BOCM field | Maps to | Notes |
|---|---|---|
| `metadatos/identificador` | `NormMetadata.identifier` | `BOCM-{YYYYMMDD}-{N}` |
| `metadatos/titulo` | `NormMetadata.title` | Often two lines: lead + full title separated by `– ` |
| `metadatos/origen_legislativo` | `extra.legislative_origin` | Always "Comunidad de Madrid" for autonomic |
| `metadatos/departamento` | `NormMetadata.department` | Consejería or organism |
| `metadatos/rango` | `NormMetadata.rank` | LEY, DECRETO, ORDEN, RESOLUCIÓN, ACUERDO, etc. May be empty |
| `metadatos/fecha_publicacion` | `NormMetadata.publication_date` | `YYYY/MM/DD` |
| `metadatos/fecha_disposicion` | `extra.enactment_date` | Optional (often empty) |
| `metadatos/diario_numero` | `extra.journal_issue` | Issue number per year |
| `metadatos/pagina_inicial`, `pagina_final` | `extra.page_start`, `extra.page_end` | |
| `metadatos/seccion` | `extra.section` | Always "I. COMUNIDAD DE MADRID" for our scope |
| `metadatos/url_html` | `NormMetadata.source` | Canonical HTML link |
| `metadatos/url_pdf` | `NormMetadata.pdf_url` | Authoritative formatted version |
| `metadatos/url_epub` | `extra.url_epub` | EPUB |
| `metadatos/url_json_ld` | `extra.url_json_ld` | JSON-LD |
| `metadatos/consolidada_por` | `extra.consolidated_url` | Only for laws — link to wleg_pub |
| `metadatos_eli/rdf:RDF/eli:LegalResource[@rdf:about]` | `extra.url_eli` | ELI URI |
| `analisis/seccion`, `apartado`, `organismo`, `tipo_disposicion` | `extra.section_*` | Cross-check against metadata |
| `texto` (CDATA) | source for body Markdown | **Plain text only — no tables, bold, italic, lists** |

Defaults for `NormMetadata.country`: `"es"`. `jurisdiction`: `"es-md"`.

### Rangos to map (Madrid-specific) → `Rank` enum

These already exist in `models.py` Rank enum (verified by `_RANK_TEXT_MAP` in `fetcher/es/metadata.py:40-66`):

- `LEY` → `Rank.LEY`
- `DECRETO LEGISLATIVO` → `Rank.DECRETO_LEGISLATIVO`
- `DECRETO-LEY` → `Rank.DECRETO_LEY`
- `DECRETO` → `Rank.DECRETO`
- `ORDEN` → `Rank.ORDEN`
- `RESOLUCIÓN` → `Rank.RESOLUCION`
- `ACUERDO` → `Rank.ACUERDO`
- `INSTRUCCIÓN` → `Rank.INSTRUCCION`
- `CIRCULAR` → `Rank.CIRCULAR`
- `CORRECCIÓN`, `EXTRACTO` → skip in v1 (corrections are amendments to other norms; extracts are summaries).

No new Rank values needed.

## 0.4 Rich-formatting inventory (BOCM `<texto>`)

| Construct | Present in source | Preserved by `<texto>` | Action |
|---|---|---|---|
| Headings (`Título`, `Capítulo`, `Sección`, `Artículo`) | yes | **yes** (as plain lines) | parse with regex |
| Numbered articles | yes | **yes** | regex |
| Inline bold | yes (PDF) | **no** (flattened) | document loss in v1; PDF parse v2 |
| Inline italic | yes (PDF) | **no** | same |
| Lists (`a)`, `b)`, etc.) | yes | **yes** (as `a) ` markers) | regex/render |
| Tables | yes (Leyes de Presupuestos, anexos económicos) | **no** (flattened to whitespace) | **fidelity gap** — BOCM as source loses tables |
| Cross-references | yes | **yes** (verbatim text) | not hyperlinked |
| Footnotes | rare | **yes** (inline) | rare enough to defer |
| Images | rare | implicit drop | skip per project rule |

**Quality consequence:** for any norm with tables, BOCM XML is lossy. The mitigation:
- For Madrid **leyes**: source from BOE (which preserves tables) — already the path.
- For Madrid **decretos/órdenes**: most have no tables; a survey of 50 decretos is needed before bootstrap to confirm the loss rate is < 1% (priority #5 rule). PDF fallback is the v2 plan if survey shows higher loss.

## 0.5 Version history spike — what each source actually offers

User constraint: **if a norm has versions, the repo must reflect them.** No single-snapshot ships of norms whose source publishes a history.

Evidence collected:

| Norm class | Source for versions | What's available | GATE |
|---|---|---|---|
| Leyes (`Ley`, `Decreto Legislativo`, `Decreto-ley`) of Madrid | BOE Consolidada | Per-block `fecha_actualizacion`. Verified on `BOCM-m-2010-90068` (Decreto Legislativo 1/2010 tributos): **125 bloques**, original 2010-10-25, art. 1 modified 2023-12-21 — full version chain reconstructable by the existing ES fetcher. | ✅ pass |
| Decretos del Consejo de Gobierno | wleg_pub (`<consolidada_por>` URL in BOCM XML) | wleg_pub returns a single consolidated HTML page — the **current** text. Verified on `Decreto 15/2026` (nmnorma=14418): 373 KB HTML, 5 occurrences of "version", no date-version selector, no "see prior version" control. wleg_pub stores only the in-force text. Modifications are recorded as edits to the live page; the timeline is not exposed. | ⚠ **only "current" available** |
| Órdenes / Resoluciones / Acuerdos | None — BOCM publishes the text once, never consolidated | Single-snapshot is faithful to the source | ✅ pass (single-snapshot is correct) |

Implication: under the user constraint, the only **source-supported version chain** for Madrid norms beyond what BOE already gives us is the wleg_pub current snapshot vs. BOCM original, and even that requires reconstructing the intermediate steps from the modifier dispositions in BOCM. There are three honest ways to handle decretos:

1. **Reconstruct from modifier dispositions** — walk BOCM I.A scanning titles for "modifica el Decreto X/YYYY", resolve target, apply patch. Stage C from Spain provides the patching primitive (reused from `feat/stage-c-amendments`). Stage C is currently at ~37–46% successful application rate on BOE Spanish text — we should expect lower on BOCM `<texto>` because it is plain text without structural markers. Realistic: 20–35% of decretos with declared modifications would have correctly-applied patches; the rest would be metadata-only commits.

2. **Pull current consolidated text from wleg_pub for the final state** — bootstrap each decreto with two commits: (a) original BOCM publication = `[bootstrap]`, (b) current wleg_pub consolidation = `[reforma]` dated by the most recent declared modifier in BOCM. We document that intermediate versions are collapsed.

3. **Defer decretos until Stage C is good enough** — ship leyes (versions ✓) + órdenes (no source versions ✓), skip decretos until reconstruction is reliable.

The cleanest path that satisfies the user constraint without dishonest single-snapshots is **(3) for v1, then (1) for v2**. (2) is a hybrid that loses information silently and risks frustrating users who diff against the BOCM original.

## 0.6 Scope estimate

Probe (issues per year × dispositions per issue):

- BOCM publishes ~250 issues/year. Going back to 2010-02-15 → ~4,000 issues × ~100 dispositions = ~400K total dispositions, but the vast majority are I.B (HR), I.D (Anuncios), III–V. Filtering to **Section I.A only**:
  - Estimated ~50–80 I.A dispositions per **week** (Madrid average from public stats).
  - 16 years × 50 weeks × 70 = ~56,000 I.A dispositions across the corpus.
  - Of these: ~120 leyes (already from BOE), ~3,500 decretos del Consejo de Gobierno, ~50,000 órdenes/resoluciones de Consejería.
  - Net **new** to the engine if we ingest BOCM I.A and de-duplicate against BOE: ~55,000.

This is comparable in scale to mid-tier countries already shipped (Slovakia 26K, Czech Republic 18K, Belgium 18K). It is feasible.

## 0.7 Format-coverage table

| Format | Coverage | Carries unique norms | Action |
|---|---|---|---|
| BOCM XML | 2010-02-15 → today, all I.A dispositions | yes (decretos/órdenes/resoluciones not in BOE) | **must support** |
| BOCM JSON-LD | same | mirror of XML | XML preferred (richer schema) |
| BOCM PDF | same | yes — tables, formatting | v2 follow-up if v1 fidelity is insufficient |
| BOCM EPUB | same | duplicate of PDF (likely image-based) | **skip** |
| BOE consolidated XML | 1983 → today, leyes only | yes — all rango-ley with version history | **already used** |
| wleg_pub HTML | unknown subset, JSF-rendered | mirrors BOE for laws + a few decretos | **skip in v1** (JSF scraping cost dwarfs gain) |

Skip justifications: EPUB is a wrapper around PDF; wleg_pub is a JSF app whose unique value (consolidated decretos) covers <5% of corpus and is not worth the engineering cost in v1.

## Recommendation: phased plan (revised under "if there are versions, there must be versions")

### Phase A — confirmed by user: BOE-side already complete

User states the BOE side is covered by the existing Spain bootstrap. Repo `legalize-es/es-md/` currently holds 183 markdown files: 181 `BOE-A-*` + 2 `BOCM-m-*`. No re-bootstrap planned. Phase A reduces to a one-off audit when convenient — out of scope for this plan.

### Phase B — surface BOCM-m-* in BOE consolidada that aren't yet in the repo

Goal: extend the existing ES discovery to also iterate `BOCM-m-*` identifiers (not just `BOE-A-*`). These already give us versions for free via the same `/texto/indice` blocks endpoint (verified on `BOCM-m-2010-90068`: 125 blocks, per-block `fecha_actualizacion`).

The blocker is discovery. The BOE consolidada API does not expose a "list all es-md" query (verified: `/api/legislacion-consolidada?ambito=2&departamento=8131` → HTTP 400 "Parámetros no soportados"). Two practical paths:

- **B.1 Crawl the BOCM sumarios since 2010** for Section I.A `LEY` / `DECRETO LEGISLATIVO` / `DECRETO-LEY` rangos, then for each disposition probe whether BOE has an equivalent `BOCM-m-*` consolidation. This is a one-time pass; cheap relative to the bootstrap.
- **B.2 Walk BOE's "Código de la Comunidad de Madrid"** (https://www.boe.es/biblioteca_juridica/codigos/codigo.php?id=208) to harvest the 116 known consolidations + their cross-references for any other `BOCM-m-*`.

These two paths feed the same outcome: a complete list of consolidatable Madrid leyes. Run both, dedupe.

### Phase C — Órdenes and Resoluciones (no source-side versioning)

These are single-snapshot **by source design**. Each commit is the original BOCM publication; later corrections (`CORRECCIÓN`) become a `[correccion]` commit on the affected file (BOCM publishes corrections as separate dispositions that explicitly cite the original BOCM-{YYYYMMDD}-N).

Single-snapshot here is **not** a violation of the user constraint — there is no version chain to reflect. We document this distinction explicitly in the country `README` so users understand the contract: leyes have history, órdenes do not, because the source itself does not maintain history.

### Phase D — Decretos del Consejo de Gobierno (the genuine open question)

This is where the user constraint and the source's behaviour are in tension. **Decision required from user before we ship.** Three options, ranked by faithfulness:

- **D.1 Defer decretos until Stage C reconstruction is reliable.** Ship lays + órdenes only; circle back when Stage C amendment application crosses, say, 70%. Honest, conservative, leaves a gap users will notice.
- **D.2 Reconstruct via Stage C now (best-effort).** For each modifier disposition we detect ("modifica el Decreto X/YYYY"), apply Stage C patcher to the target. Where it succeeds → real version commit. Where it fails → metadata-only commit + flag in frontmatter (`amendment_application: deferred`). Users see partial history.
- **D.3 Hybrid wleg_pub snapshot.** Two commits per decreto: original BOCM + current wleg_pub. Loses intermediate versions silently — does NOT meet the user's bar.

D.3 is off the table given the user constraint. D.1 ships less but never lies. D.2 ships more but introduces "partial-history" commits.

### Phase E — daily flow (after the bootstrap is up)

Once the corpus is bootstrapped, daily updates are cheap:
- Fetch yesterday's BOCM sumario (XML).
- For each new I.A disposition, route by rango: leyes → poll BOE consolidada (already covered by `daily-update.yml`); órdenes/resoluciones → ingest as new file; decretos → ingest as new file + run Stage C against any prior decreto cited in the title (D.2 path).

## Code shape (relevant once Phase B/C/D start)

```
src/legalize/fetcher/es_md/
  __init__.py
  client.py        # rate-limited HTTPS client for bocm.es; respects Crawl-delay: 10
  discovery.py     # iterate sumarios over date range; emit BOCM-{YYYYMMDD}-{N} ids for I.A;
                   # for each, route to BOE-consolidada (leyes) or local parser (others)
  parser.py        # parse <documento> XML → NormMetadata + plain-text body → Markdown
  daily.py         # daily cron — yesterday's sumario, emit new I.A dispositions
```

Wire-up:
- `countries.py`: add `es-md` entry, sharing the `legalize-es` repo (subjurisdiction).
- `config.yaml`: add `es-md` section.
  ```yaml
  es-md:
    repo_path: "../countries/es"          # SAME repo as es
    data_dir: "../countries/data-es-md"
    cache_dir: ".cache"
    max_workers: 2
    source:
      base_url: "https://www.bocm.es"
      request_timeout: 30
      max_retries: 5
      requests_per_second: 0.5             # robots.txt Crawl-delay: 10
      year_start: 2010
      sections_in_scope: ["I.A"]
  ```
- Filename: `es-md/BOCM-{YYYYMMDD}-{N}.md` for new BOCM-direct ingest. Existing `BOCM-m-*` and `BOE-A-*` keep their identifiers.
- Frontmatter additions for new BOCM-direct ingest (additive `extra` fields, all flowing through `frontmatter.py:63`):
  - `source_publisher: "BOCM"` — distinguishes from BOE-consolidated entries which already say `official_journal: "Boletín Oficial del Estado"` or `"Boletín Oficial de la Comunidad de Madrid"`
  - `consolidated_url: <wleg_pub link>` when present in `<consolidada_por>`
  - `url_eli: <eli URI from metadatos_eli>`
  - `url_epub`, `url_json_ld`

## Open questions blocking implementation

1. **Phase D decision** — D.1 (defer decretos) or D.2 (Stage C best-effort). D.3 is off the table per the user constraint. Recommendation: D.1 first, measure Stage C success rate in a side experiment, upgrade to D.2 only if it crosses ~70%.
2. **Discovery cost** — BOE consolidada has no list-by-jurisdiction endpoint. Are we OK with a one-time crawl of BOCM sumarios since 2010 (~4,000 issue XMLs at 0.5 req/s ≈ 2.5 hours) to enumerate consolidatable Madrid laws plus discover decretos/órdenes? This is the unavoidable cost.
3. **Identifier policy** for new BOCM-direct ingest — confirm `BOCM-{YYYYMMDD}-{N}` (mirrors what BOE itself uses for its `BOCM-m-*` namespace, but using the native publication date format).

Until 1 and 2 are answered, no code beyond fixtures + this research doc is being written.
