# Portugal — full re-fetch: discovery, scope and cost

Executable plan for **D1** (RESEARCH-PT-v2 §12): every Portuguese diploma is
re-downloaded from `diariodarepublica.pt`; the `dre.tretas.org` SQLite mirror is retired.

Everything below was measured on **2026-08-21**. The command that produced each number is
given next to it. Raw sitemaps live in `countries/data-pt/sitemaps/` (587 `.xml.gz` +
`sitemap.xml`, 25 MB compressed / 785 MB raw) with a flat URL index at
`countries/data-pt/sitemaps/_all-detalhe-urls.tsv.gz` (`tipo \t key \t year`, 5.48 M rows).

---

## TL;DR — the five things that change the plan

1. **DRE has no machine-readable text before 1960.** Every sampled document from the 1910s–1950s
   returns `Texto: ""` and `TextoFormatado: ""` with only a scanned `URL_PDF`; before 1910 there is
   not even a PDF. The repo's 1960 floor is not a tretas artefact — it is exactly where DRE's
   digitised full text begins. The README's "since 1911" is true of the *catalogue*, not the text.
2. **The sitemap is not a complete discovery source.** 4.59 % of in-scope Série I documents found by
   walking the journals are absent from it — including Decreto-Lei 9/2022 and 10/2022. The
   date-by-date journal walk is **required**, not a backstop.
3. **The sitemap's `tipo` does not tell you the série.** 14 % of sampled `portaria` URLs and 100 % of
   sampled `declaracao-retificacao` URLs are Série II. Série is only knowable from the detail record
   (`Serie`) or from which journal the document was listed under.
4. **`DREHttpClient` has a thread-safety bug** that makes concurrency unusable as shipped: 32 % of
   requests failed with `KeyError: 'document_detail'` at 8 workers. See "Two client bugs" below.
5. **The server is not the constraint.** 560 detail calls at up to 16 workers / 54 req/s produced
   **zero** 429s, 503s or connection errors, p50 latency 0.13 s. Politeness is our choice, not theirs.

---

## 1 · Enumerating the corpus from the sitemaps

`https://diariodarepublica.pt/dr/robots.txt` names one sitemap and sets no `Disallow` and no
`Crawl-delay`. `https://files.dre.pt/sitemap/sitemap.xml` is an index of **588** child sitemaps
(84 KB).

```bash
curl -s -A "legalize-bot/1.0 (+https://github.com/legalize-dev/legalize-pipeline)" \
  -o countries/data-pt/sitemaps/sitemap.xml https://files.dre.pt/sitemap/sitemap.xml
grep -c "<loc>" countries/data-pt/sitemaps/sitemap.xml      # 588
```

All 588 were downloaded (5 workers, 118 s, 785 MB) — `scripts/pt_discovery/fetch_sitemaps.py`:

| | |
|---|---|
| Child sitemaps fetched | 587 / 588 |
| Unreachable | `geral-sitemap-sitemap-1.xml` → HTTP 403 `AccessDenied` (S3, permanent; also 403 on HEAD retry) |
| Total `<url>` entries | **5,893,476** |
| Per-file cap | 20,000 URLs |

### 1.1 Two traps in the sitemap index

**The child sitemap's filename is not the document type.** Classify by the URL path segment, never
by the file name:

| sitemap file | actually contains | count |
|---|---|---|
| `diploma-externo-sitemap-*` | `/dr/detalhe/acordao/…` | 404,236 |
| `contrato-publico-sitemap-*` | `/dr/detalhe/anuncio-procedimento/…` | 237,764 |
| `diploma-externo-sitemap-*` | `/dr/detalhe/parecer/…` | 10,127 |
| `contrato-publico-sitemap-*` | `/dr/detalhe/aviso-prorrogacao-prazo/…` | 25,347 |

**`analise-juridica` is a duplicate view, not a document type.** Its 408,995 URLs are
`/dr/analise-juridica/informacoes-gerais/{tipo}/{key}` — the "legal analysis" tab of documents
already listed under `/dr/detalhe/`. Same key, same document. Discarding it costs nothing.

Of the 5,893,476 URLs: **5,476,191** are `/dr/detalhe/` documents in **312** types, 408,995 are the
`analise-juridica` duplicate view, 5,561 are `/dr/legislacao-consolidada/` (surface A, already
dumped to `consolidated-catalogue.jsonl.gz`), and 2,729 are `lexionario` / `geral` / account pages.

### 1.2 Total URLs per document type

Top 45 of 312 `/dr/detalhe/` types. `1960+` / `pre-1960` split on the year embedded in the key
(`{numero}-{ano}-{id}`, or `{ano}-{id}` for numberless diplomas).

| # | URL type | total | 1960+ | pre-1960 | no year | year range |
|---:|---|---:|---:|---:|---:|---|
| 1 | `ato-societario` | 3,108,141 | 0 | 0 | 3,108,141 | — |
| 2 | `acordao` | 404,446 | 402,073 | 2,370 | 3 | 1932–2027 |
| 3 | `despacho` | 322,385 | 321,302 | 1,083 | 0 | 1910–2026 |
| 4 | `anuncio-procedimento` | 237,764 | 235,325 | 0 | 2,439 | 1967–2026 |
| 5 | `despacho-extracto` | 160,822 | 160,822 | 0 | 0 | 1979–2026 |
| 6 | **`portaria`** | **111,106** | 91,727 | 19,379 | 0 | 1856–2026 |
| 7 | `aviso-contumacia` | 110,380 | 110,380 | 0 | 0 | 2000–2006 |
| 8 | `diario-republica` | 102,922 | 82,526 | 20,396 | 0 | 1826–2026 |
| 9 | `anuncio` | 86,029 | 86,029 | 0 | 0 | 1977–2026 |
| 10 | `aviso` | 81,977 | 81,977 | 0 | 0 | 1982–2026 |
| 11 | `despacho-extrato` | 54,291 | 54,291 | 0 | 0 | 2006–2026 |
| 12 | `acordao-sta` | 53,108 | 53,108 | 0 | 0 | 1995–2016 |
| 13 | `aviso-extrato` | 47,788 | 47,788 | 0 | 0 | 2012–2026 |
| 14 | **`decreto`** | **47,469** | 8,846 | 38,623 | 0 | 1833–2026 |
| 15 | `edital` | 39,377 | 39,317 | 60 | 0 | 1921–2026 |
| 16 | `rectificacao` | 34,019 | 30,801 | 3,218 | 0 | 1910–2025 |
| 17 | **`decreto-lei`** | **31,593** | 23,512 | 8,081 | 0 | 1933–2026 |
| 18 | `louvor` | 28,788 | 28,788 | 0 | 0 | 1980–2026 |
| 19 | `aviso-extracto` | 26,536 | 26,536 | 0 | 0 | 1997–2011 |
| 20 | `declaracao` | 25,753 | 19,679 | 6,074 | 0 | 1910–2026 |
| 21 | `aviso-prorrogacao-prazo` | 25,347 | 24,965 | 1 | 381 | 1753–2024 |
| 22 | `sem-diploma` | 24,797 | 24,797 | 0 | 0 | 1978–2008 |
| 23 | `deliberacao` | 23,276 | 23,276 | 0 | 0 | 1973–2026 |
| 24 | `contrato` | 21,603 | 21,598 | 5 | 0 | 1913–2026 |
| 25 | `regulamento` | 18,422 | 18,402 | 20 | 0 | 1863–2026 |
| 26 | `deliberacao-extrato` | 15,516 | 15,516 | 0 | 0 | 2006–2026 |
| 27 | **`resolucao`** | **15,243** | 15,233 | 10 | 0 | 1916–2026 |
| 28 | `despacho-conjunto` | 15,015 | 15,015 | 0 | 0 | 1974–2025 |
| 29 | `deliberacao-extracto` | 14,796 | 14,796 | 0 | 0 | 1998–2011 |
| 30 | **`despacho-normativo`** | **13,617** | 13,617 | 0 | 0 | 1975–2026 |
| 31 | `contrato-extracto` | 13,153 | 13,153 | 0 | 0 | 1998–2011 |
| 32 | **`declaracao-rectificacao`** | **11,356** | 11,356 | 0 | 0 | 1984–2026 |
| 33 | `anuncio-concurso` | 10,763 | 10,763 | 0 | 0 | 2006–2019 |
| 34 | `parecer` | 10,747 | 10,714 | 33 | 0 | 1913–2026 |
| 35 | `edito` | 10,137 | 10,137 | 0 | 0 | 2006–2026 |
| 36 | `contrato-colectivo-trabalho-alteracao` | 7,272 | 7,271 | 1 | 0 | 1922–2026 |
| 37 | `anuncio-concurso-urgente` | 6,784 | 6,783 | 0 | 1 | 2008–2025 |
| 38 | **`lei`** | **6,703** | 4,192 | 2,511 | 0 | 1850–2026 |
| 39 | **`decreto-presidente-republica`** | **5,912** | 5,912 | 0 | 0 | 1983–2026 |
| 40 | `listagem` | 5,729 | 5,729 | 0 | 0 | 1990–2026 |
| 41 | `portaria-extensao` | 5,547 | 5,545 | 2 | 0 | 1955–2026 |
| 42 | **`declaracao-retificacao`** | **5,228** | 5,228 | 0 | 0 | 2018–2026 |
| 43 | **`resolucao-assembleia-republica`** | **4,757** | 4,756 | 1 | 0 | 1956–2026 |
| 44 | `contrato-extrato` | 4,345 | 4,345 | 0 | 0 | 2006–2026 |
| 45 | `declaracao-retificacao-anuncio` | 4,311 | 4,247 | 0 | 64 | 2012–2024 |

**Grand total `/dr/detalhe/`: 5,476,191** — 1960+ 2,258,011 · pre-1960 107,150 · no year 3,111,030
(of which 3,108,141 are `ato-societario`, whose keys are bare content ids).

Rows in **bold** are in the recommended scope (§2). The remaining 267 types hold 61,121 URLs
between them and are enumerated in `_all-detalhe-urls.tsv.gz`.

### 1.3 Justified skips

| Skipped | URLs | Why |
|---|---:|---|
| `ato-societario` | 3,108,141 | Company-registry filings (share transfers, board changes) from the Conservatórias. Not legislation. 56.8 % of the whole sitemap on its own. |
| `acordao` + `acordao-sta` + `acordao-extrato/-extracto` | 458,482 | Bulk administrative/tax case law (STA, TCA). Jurisprudence is out of scope per RESEARCH-PT-v2 §11 — with the narrow exception in §2.3 below. |
| `despacho` + `despacho-extracto` + `despacho-extrato` + `despacho-conjunto` | 552,513 | Ministerial orders: appointments, delegations of signature, individual authorisations. Overwhelmingly Série II personnel administration. `despacho-normativo` is a different act and **is** in scope. |
| `anuncio-procedimento` + `anuncio` + `anuncio-concurso*` + `anuncio-extra*` + `aviso-prorrogacao-prazo` + `declaracao-*-anuncio` + `contrato` + `contrato-extra*` | 416,951 | Public-procurement notices and contract extracts. Tenders, not norms. |
| `aviso` + `aviso-extrato` + `aviso-extracto` | 156,301 | Notices: exam results, staff lists, sectoral announcements. (`aviso-banco-portugal`, 243, is a genuine regulator norm — see §2.4.) |
| `aviso-contumacia` | 110,380 | Criminal *contumácia* declarations naming individual defendants. Personal data about private individuals; publishing these as a corpus is neither legislation nor defensible. |
| `diario-republica` | 102,922 | The journal *issues* themselves, not documents. Useful as a cross-check index; not laws. |
| `louvor` | 28,788 | Commendations of named individuals. |
| `edital` + `edito` | 49,514 | Court and municipal public notices. |
| `sem-diploma` | 24,797 | Literally "no diploma" — untyped Série II filler, 1978–2008. |
| `deliberacao*` | 53,588 | Deliberations of collegial administrative bodies, Série II. |
| `regulamento` | 18,422 | Overwhelmingly internal regulations of individual public entities (Série II), not general regulation. `regulamento-cmvm` is separate and optional (§2.4). |
| `declaracao` | 25,753 | Generic declarations — asset declarations, notices of taking office. Distinct from `declaracao-retificacao`, which **is** in scope. |
| `parecer*` | 12,207 | Advisory opinions (PGR, Conselho de Estado). Persuasive, not binding. |
| `analise-juridica` (view) | 408,995 | Duplicate of documents already counted under `/dr/detalhe/`. |
| Collective-bargaining bulk (`contrato-colectivo-trabalho*`, `acordo-*`, 41 types) | 19,607 | Sector agreements between named parties. Only their *portarias de extensão* have erga omnes effect, and those are the optional set in §2.4. |

### 1.4 Série I legislative documents reachable from the sitemap

The sitemap does not label série. Measured on 264 sampled 1960+ documents of in-scope types
(`scripts/pt_discovery/bench_detail.py`): **77.7 % Série I**, 16.3 % Série II, 6.1 % blank (numberless pre-1976
diplomas). Per type:

| url tipo | sampled | Série I | Série II |
|---|---:|---:|---:|
| `portaria` | 128 | 98 | 26 |
| `decreto-lei` | 41 | 41 | 0 |
| `despacho-normativo` | 17 | 10 | 1 |
| `decreto` | 16 | 16 | 0 |
| `declaracao-retificacao` | 14 | 0 | 14 |
| `resolucao` | 11 | 3 | 2 |
| `lei` | 10 | 10 | 0 |

Applied to the recommended scope: **198,516 URLs from 1960 onwards, of which ≈ 155,000–165,000
are Série I.** A tighter figure is not available without fetching every detail record — the série
is only in the record, which is why the journal walk (§3.4) is the better primary enumerator.

### 1.5 How this compares to what we have

| | count | source |
|---|---:|---|
| Files in `legalize-pt` today | **109,929** | `wc -l /tmp/pt-files.txt` |
| What `discovery.MAJOR_DOC_TYPES` would select from the sitemap (its 11 strings → 10 `tipo` slugs) | **219,134** total / 150,530 from 1960+ | scope A, §2.1 |
| Recommended scope (§2) | **267,433** total / 198,516 from 1960+ | scope B |
| Recommended scope, 1960+, after the 4.59 % sitemap-miss uplift (§3) | **≈ 207,600** | the number to plan the fetch against |

The existing repo's 10 identifier prefixes (`sed -E 's/^DRE-([A-Z]+)-.*/\1/' | sort | uniq -c`):
P 64,787 · DL 23,626 · D 9,166 · L 4,169 · DRR 2,604 · DLR 2,428 · DR 1,935 · R 1,203 · LC 8 · LO 3.

So even scope A — the *same* type list we already use — finds 40,601 more 1960+ documents than the
repo holds. The tretas mirror was not a complete copy of the types it did carry.

### 1.6 Year coverage — the sitemaps reach back to 1826, the text does not

```bash
find countries/pt-audit/pt -name '*.md' -print0 | xargs -0 grep -h '^publication_date:' \
  | sed -E 's/[^0-9]*([0-9]{4}).*/\1/' | sort | uniq -c | sort -k2n
```

The repo's earliest year is **1960** (1,350 files) and it has **nothing** before it. The sitemaps go
much further back: `diario-republica` to 1826, `decreto` to 1833, `lei` to 1850, `portaria` to 1856,
and the modern volume starts in 1911 — which is exactly the claim in the README.

In-scope documents by decade, and what the detail API actually returns for them
(`scripts/pt_discovery/bench_detail.py`, 560 documents stratified across 19 decades):

| decade | in-scope URLs | sampled | **with text** | with PDF | with ELI | mean payload |
|---|---:|---:|---:|---:|---:|---:|
| 1820s–1900s | 179 | 107 | **0 (0 %)** | 0 | 0 | 2.1 KB |
| 1910s | 15,309 | 37 | **0 (0 %)** | 37 | 0 | 2.4 KB |
| 1920s | 17,007 | 36 | **0 (0 %)** | 36 | 0 | 2.5 KB |
| 1930s | 15,457 | 37 | **0 (0 %)** | 37 | 0 | 2.5 KB |
| 1940s | 11,248 | 40 | **0 (0 %)** | 40 | 0 | 2.5 KB |
| 1950s | 9,716 | 37 | **1 (2.7 %)** | 37 | 0 | 2.8 KB |
| 1960s | 13,870 | 38 | 38 (100 %) | 38 | 0 | 10.4 KB |
| 1970s | 20,797 | 39 | 37 (94.9 %) | 37 | 0 | 8.6 KB |
| 1980s | 30,614 | 34 | 31 (91.2 %) | 31 | 0 | 14.9 KB |
| 1990s | 38,126 | 39 | 35 (89.7 %) | 35 | 30 | 64.3 KB |
| 2000s | 49,570 | 39 | 37 (94.9 %) | 36 | 26 | 24.6 KB |
| 2010s | 24,743 | 39 | 36 (92.3 %) | 36 | 24 | 55.4 KB |
| 2020s | 20,786 | 36 | 34 (94.4 %) | 34 | 14 | 24.4 KB |

**68,916 in-scope URLs (25.8 %) are pre-1960, and none of them has machine-readable text.** A typical
1930s record looks like this (`/dr/detalhe/decreto/1906-628528`):

```
Numero ''          Texto ''            TextoFormatado ''       URL_PDF ''
ELI    ''          Serie 'I'           TipoDiploma 'Decreto'   DataPublicacao '1906-05-18'
Emissor 'Ministério das Obras Públicas Comércio e Indústria'
Publicacao 'Diário do Govêrno n.º 111/1906, Série I de 1906-05-18'
```

From 1911 a scanned `URL_PDF` appears; before 1910 not even that. OCR of those scans is explicitly
out of scope (RESEARCH-PT-v2 §11), so **the fetchable-with-text corpus starts in 1960** and the
repo's floor was never wrong — only its README was.

---

## 2 · Scope recommendation

Rule: legalize publishes *legislative norms* — general, binding acts of the Portuguese state and the
autonomous regions. Not company filings, tenders, personnel notices or case law.

### 2.1 Scope A — what `MAJOR_DOC_TYPES` selects today (baseline, do not ship)

`lei` · `lei-constitucional` · `lei-organica` · `decreto-lei` · `decreto` · `decreto-regulamentar` ·
`decreto-legislativo-regional` · `decreto-regulamentar-regional` · `portaria` · `resolucao`
→ **219,134 total / 150,530 from 1960+**.

Its defect is the one RESEARCH-PT-v2 §1.6 already named: the SQL filter is an exact `IN (…)` match on
11 uppercase strings, so `"RESOLUÇÃO"` matches and `"RESOLUÇÃO DO CONSELHO DE MINISTROS"` does not.
Replacing that list with the URL `tipo` slug fixes the class of bug, not just the instances.

### 2.2 Scope B — recommended (51 types, **267,433 total / 198,516 from 1960+**)

Scope A, plus:

| type | URLs | why it belongs |
|---|---:|---|
| `despacho-normativo` | 13,617 | General regulatory order with external binding effect — the "regulation by despacho" instrument. Distinct from plain `despacho`. |
| `declaracao-rectificacao` | 11,356 | **Legally corrects the published text.** Without it the corpus states the uncorrected law. Non-negotiable. |
| `declaracao-retificacao` | 5,228 | Same act, post-2018 spelling. Both slugs coexist; both must be fetched. |
| `decreto-presidente-republica` | 5,912 | Head-of-state acts: ratification of treaties, appointments of ambassadors, declarations of state of emergency. |
| `resolucao-assembleia-republica` | 4,757 | Parliament's own binding resolutions — treaty approvals, referendum calls. |
| `resolucao-conselho-ministros` | 3,861 | The government's principal policy instrument. 329 are consolidated by DRE and **0** are in the repo today (§1.6 of the research). |
| `resolucao-assembleia-legislativa-*` (4 slugs, Açores + Madeira) | 1,846 | Regional parliaments' resolutions, jurisdictions `pt-20` / `pt-30`. |
| `decreto-governo` (293), `decreto-regional` (280) | 573 | Historical act types 1976–1982; the repo already carries some, miscategorised as `DECRETO`. |
| `decreto-representante-republica-*`, `decreto-ministro-republica*` (5 slugs) | 118 | Regional-representative decrees enacting regional legislation. |
| `assento` (190), `acordao-supremo-tribunal-justica` (206), `acordao-tribunal-constitucional` (165), `acordao-doutrinario` (183) | **744** | See §2.3. |
| Historical constitutional acts: `carta-lei` (47), `carta-constitucional` (1), `decreto-aprovacao-constituicao` (1) | 49 | Foundational texts. |
| `regimento`, `regimento-assembleia-republica`, `regimento-conselho-estado` | 31 | Standing orders — binding institutional norms. |
| `resolucao-assembleia-nacional`, `resolucao-assemblea-nacional` (sic, DRE's typo), `resolucao-congresso-republica`, `resolucao-conselho-revolucao`, `resolucao-conselho-ministros-para-assuntos-economicos`, `resolucao-conselho-corporativo` | 172 | Pre-1976 and transitional bodies. |
| `tratado` | 6 | International treaties published in Série I. |
| `*-extrato` / `*-extracto` variants of the above | 29 | Same act, extract publication. Cheap, avoids a hole. |

Scope B adds **48,299** documents over scope A (47,986 of them 1960+) — a 22 % larger corpus for
about 24 % more requests.

### 2.3 Should Acórdãos with força obrigatória geral be in scope? — **Yes, the 744 named above.**

The blanket exclusion of jurisprudence in RESEARCH-PT-v2 §11 is right for the 458,482 `acordao` /
`acordao-sta` bulk: those decide individual cases and bind only the parties. But four small types are
different in kind — they are *sources of law*, and Portugal publishes them in Série I for exactly
that reason:

- **`acordao-tribunal-constitucional` (165)** — only the TC rulings that declare a norm
  unconstitutional **com força obrigatória geral** (CRP art. 281–282) reach Série I. They *repeal
  norms erga omnes*. A corpus that carries a law struck down in 2019 and not the ruling that struck
  it down is wrong about the law.
- **`assento` (190)** and **`acordao-supremo-tribunal-justica` (206)** — assentos (to 1995) and their
  successors, the *acórdãos de uniformização de jurisprudência*, published in Série I and binding on
  the lower courts.
- **`acordao-doutrinario` (183)** — the historical doctrinal acórdãos, same function.

744 documents, ~0.4 % of the corpus, and they change what the rest of the corpus *means*. Include.
Everything else under `acordao*` stays out.

### 2.4 Optional — labour and sectoral regulators (**+40,482**, judgement call)

Defensible either way; my recommendation is in the last column.

| type | URLs | argument | verdict |
|---|---:|---|---|
| `rectificacao` | 34,019 | The pre-1984 spelling of a rectification, 1910–2025 — same legal function as `declaracao-rectificacao`. But it is the *generic* slug and mixes Série I corrections of laws with Série II corrections of notices. | **Include, filtered to Série I** — the série is on the record, so the filter is free once fetched. |
| `portaria-extensao` + variants | 5,644 | *Portarias de extensão* extend a collective agreement erga omnes to a whole sector — genuinely normative, and the repo already carries them today (miscategorised as `PORTARIA`, which is why §3 saw 14 unmatched `DRE-P-*`). Dropping them would be a regression. | **Include.** |
| `aviso-banco-portugal` (243), `regulamento-cmvm` (198), `norma-regulamentar-asf` (113), `norma-regulamentar-isp` (97) | 651 | Binding regulations of the financial-sector supervisors. Normative and citable, but published in Série II and a different institutional register. | Defer to a later pass; note in `country_meta`. |
| `portaria-regulamentacao-trabalho` + variants | 168 | PRTs regulate an entire sector where no agreement exists. Normative. | **Include.** |
| `mapa-oficial*` (158) | 158 | Official election-result maps. Records a fact, does not norm. | Exclude. |

**Scope C (B + all of the above) = 307,915 total / 235,778 from 1960+.**

### 2.5 The recommendation

Ship **scope B + the `rectificacao` / `portaria-extensao` / `portaria-regulamentacao-trabalho` rows
of §2.4**, restricted to **Série I** and to **1960 onwards**.

- Fetchable-with-text corpus: **≈ 208,000 documents** (198,516 sitemap 1960+ in scope B, ×1.0459 for
  the sitemap misses of §3, plus the labour/rectification rows, minus the Série II fraction that gets
  discarded after fetch).
- Roughly **1.9× the 109,929 the repo has today**.
- Pre-1960 (68,916 in scope B): **catalogue-only**. See §5.4 for what to do with it.

---

## 3 · Is the sitemap complete? — **No. 4.59 % of in-scope Série I documents are missing.**

### 3.1 Repo → sitemap: 98.95 % of what we have is findable

`scripts/pt_discovery/match_repo_to_sitemap.py` matches all 109,929 repo identifiers against the sitemap on normalised
number+year, type-agnostically (necessary: tretas normalised `portaria-extensao` → `PORTARIA`,
`decreto-governo` → `DECRETO`).

| | |
|---|---|
| Matched | **108,774 / 109,929 = 98.95 %** (95,014 on number+year, 13,760 on number alone) |
| Unmatched | 1,155 |

The 1,155:

| class | n | what it is |
|---:|---|---|
| 546 | letter-suffixed numbers (`DRE-P-302-A-2016`) | Genuinely absent — see §3.3 |
| 537 | synthetic `DD` numbers (`DRE-R-DD1653`, `DRE-D-DD18`) | Numberless diplomas ("Decreto de 20 de Abril de 1982") that tretas gave a fabricated number. DRE keys them `{tipo}/{ano}-{id}`, so no number exists to match on. They are in the sitemap; the *identifier* is unmatchable, not the document. D2's ELI identifiers fix this class permanently. |
| 72 | other | mixed |

A first, type-*aware* pass scored only 95.30 %. The 3.65-point difference is entirely tretas
mislabelling — the miss list was full of `DRE-P-148-2019` ("Portaria de extensão…", DRE type
`portaria-extensao`) and `DRE-D-6-88` ("Decreto do Governo n.º 6/88", DRE type `decreto-governo`).
Worth knowing before anyone builds a migration map on the old type codes.

### 3.2 Sitemap → repo: 72.5 % of a 200-sample is already held

200 random in-scope sitemap URLs (`random.seed(42)` over the 264,426-URL in-scope pool):
**145/200 = 72.5 %** matched an existing repo identifier; **55 absent**, of which **39 are
pre-1960** (1910s 8 · 1920s 12 · 1930s 4 · 1940s 6 · 1950s 9). Full-corpus coverage per type,
same matcher:

| tipo | sitemap | in repo | cov. |
|---|---:|---:|---:|
| `decreto-regulamentar` | 1,932 | 1,932 | 100.0 % |
| `acordao-supremo-tribunal-justica` | 206 | 205 | 99.5 % |
| `decreto-legislativo-regional` | 2,412 | 2,373 | 98.4 % |
| `decreto-regulamentar-regional` | 2,576 | 2,526 | 98.1 % |
| `lei-organica` | 92 | 90 | 97.8 % |
| `despacho-normativo` | 13,617 | 13,058 | 95.9 % |
| `resolucao-assembleia-republica` | 4,757 | 4,493 | 94.5 % |
| `resolucao` | 15,243 | 13,964 | 91.6 % |
| `resolucao-conselho-ministros` | 3,861 | 3,165 | 82.0 % |
| `decreto-lei` | 31,593 | 24,780 | 78.4 % |
| `decreto-presidente-republica` | 5,912 | 4,500 | 76.1 % |
| `portaria` | 111,106 | 83,276 | 75.0 % |
| `assento` | 190 | 122 | 64.2 % |
| `lei` | 6,703 | 4,188 | 62.5 % |
| `acordao-tribunal-constitucional` | 165 | 90 | 54.5 % |
| `declaracao-rectificacao` | 11,356 | 5,616 | 49.5 % |
| **`decreto`** | 47,469 | 14,477 | **30.5 %** |
| **`declaracao-retificacao`** | 5,228 | 1,268 | **24.3 %** |

(Number-only matching, so these are *upper bounds* on coverage — a `decreto` numbered 1/1974 counts
as covered if any repo file carries `1-1974`.) `decreto`'s 30.5 % is the pre-1960 hole: 38,623 of its
47,469 URLs predate 1960. The high figures for `despacho-normativo` (95.9 %) and
`resolucao-conselho-ministros` (82.0 %) are artefacts of that same number-only match — the research's
§1.6 finding that 0 RCMs are in the repo stands; their numbers collide with `resolucao`.

### 3.3 The decisive test: journal walk → sitemap

The sitemap is a *SEO artefact*, not a register. To test it against the register, 99 random weekdays
across 1960–2026 were walked with `get_journals_by_date` + `get_documents_by_journal`
(`scripts/pt_discovery/journal_walk.py`, `random.seed(11)`, 228 requests, 120 s at 2 req/s, **0 errors**), and
every returned `LinkSitemap` was looked up in the sitemap index.

> Beware: `"Série I" in title` is `True` for `"Série II"`. The first run over-collected 12,509
> documents through that substring bug. The correct filter is `re.search(r"Série I(?!I)", title)`.

| | |
|---|---|
| Série I documents found by the walk | 826 |
| Present in the sitemap (exact key) | 725 = **87.77 %** |
| Present on number+year (different content id) | 738 = 89.35 % |
| **In-scope Série I documents** | **675** |
| **In-scope present in the sitemap** | **644 = 95.41 %** |
| **In-scope missing** | **31 = 4.59 %** |

The 31 in-scope misses: `Portaria` 14 · `Resolução do Conselho de Ministros` 9 ·
`Declaração de Retificação` 4 · `Acórdão` 2 · `Decreto-Lei` 2. Not a marginal tail — they include:

```
2022-01-11  Decreto-Lei 9/2022    /dr/detalhe/decreto-lei/9-2022-177455548
2022-01-11  Decreto-Lei 10/2022   /dr/detalhe/decreto-lei/10-2022-177455549
2015-09-18  Portaria 290–295/2015 (six consecutive)
2018-03-01  RCM 20/2018 + Declaração de Retificação 7/2018, 8/2018
1989-05-11  RCM 18/89, RCM 19/89
```

`/dr/detalhe/decreto-lei/9-2022-177455548` fetches perfectly — full `Texto`, full `TextoFormatado`,
a valid ELI, a `URL_PDF` — it is simply **not in the sitemap**. There is no whole-issue pattern
(0 sampled dates were entirely absent; 38 dates were partially covered), so the omissions are
scattered and cannot be predicted.

Supplements are over-represented but do not explain it: 6 of the 31 misses are from *Suplemento*
issues, and `Isnoindex` is `False` on all of them. Portaria 302-A/2016
(`/dr/detalhe/portaria/302-a-2016-105300338`, 1.º Suplemento to DR 231/2016) is in the repo, live on
DRE, `IsNoIndex: False`, and absent from the sitemap.

### 3.4 Verdict — sitemap **and** journal walk, journal walk as primary

| | sitemap | journal walk |
|---|---|---|
| Requests to enumerate | 589 (static CDN, 118 s) | ~47,500 (app API) |
| Completeness on in-scope Série I | **95.41 %** | reference (the register itself) |
| Gives the série | **no** — must fetch the detail | **yes**, for free |
| Gives the issue / supplement | no | yes |
| Reaches pre-1960 | yes (to 1826) | yes |
| Gives `lastmod` | yes | no |

Neither alone is sufficient, and they cost very different things. Run **both** and union on
`LinkSitemap`:

1. **Journal walk is the primary enumerator.** It is the register, it is complete by construction, and
   it hands you the série and the issue — which the sitemap cannot, and which otherwise costs one
   detail fetch per document to learn.
2. **Sitemap is the completeness audit and the pre-1960 catalogue.** 589 cheap requests that also
   supply `lastmod` for incremental runs. Anything in the sitemap that the walk did not produce is a
   walk bug (a missed date, an API hiccup) and must be reconciled before commit, not silently dropped.
3. **Fail the run if the union is smaller than the sitemap's in-scope 1960+ count.** A silent
   shortfall is exactly how Portugal shipped with no history the first time.

---

## 4 · Cost model

All figures measured 2026-08-21 from a residential connection in Spain.
UA `legalize-bot/1.0 (+https://github.com/legalize-dev/legalize-pipeline)` throughout.

### 4.1 Per-request cost, by endpoint

| endpoint | n | latency mean / p50 | payload mean / p50 | notes |
|---|---:|---|---|---|
| child sitemap (static CDN) | 588 | — | 1.34 MB | 785 MB total, 118 s at 5 workers |
| `get_journals_by_date` | 40 | 0.147 s / 0.142 s | 1,205 B / 1,106 B | 2.33 journals/date (all séries) |
| `get_documents_by_journal` | 34 | 0.107 s / 0.103 s | 2,810 B / 2,415 B | 5.41 docs/journal |
| `get_document_detail`, 1960+ | 264 | 0.164 s / 0.121 s | **29,317 B** / 11,112 B | p90 53.6 KB · p99 580.9 KB · max 829.7 KB |
| `get_document_detail`, pre-1960 | 296 | — | 2,387 B | metadata-only stubs |

`TextoFormatado` for a 1960+ document: mean 12,487 chars, p50 2,956.

### 4.2 Concurrency — where it breaks (it doesn't)

`scripts/pt_discovery/bench_detail.py`, 560 detail calls, rate limiter disabled, workers stepped 1 → 16, aborting on
the first 429:

| workers | n | ok | errors | wall | req/s | lat mean | lat p50 | **lat p95** |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 60 | 60 | 0 | 9.8 s | 6.1 | 0.164 s | 0.121 s | 0.223 s |
| 2 | 100 | 100 | 0 | 6.7 s | 15.0 | 0.133 s | 0.125 s | 0.209 s |
| **4** | 140 | 140 | 0 | 5.5 s | 25.6 | 0.154 s | 0.133 s | **0.228 s** |
| 8 | 160 | 160 | 0 | 3.6 s | 44.7 | 0.176 s | 0.147 s | 0.543 s |
| 16 | 100 | 100 | 0 | 3.0 s | 33.4 | 0.312 s | 0.128 s | **1.216 s** |

**No 429, no 503, no connection error at any level.** DRE never rate-limited us. Throughput saturates
at 8 workers; at 16 it *falls* (33.4 req/s) while p95 latency quintuples to 1.216 s — that is DRE's
request queue backing up, and it is the point past which we are degrading the service for its actual
users. Do not go there.

The 588-file sitemap sweep at 5 workers and the 228-request journal walk at 2 req/s were likewise
error-free. The only non-200 seen all day was the permanent 403 on `geral-sitemap-sitemap-1.xml`.

### 4.3 Two client bugs the benchmark surfaced

**(a) `_post()`'s periodic session refresh is not thread-safe — blocks concurrency entirely.**
`client.py` refreshes every 100 requests, and `_init_session()` starts with `self._endpoints = {}`.
Concurrent workers then read an empty dict:

```
w4: 16/120 failed   KeyError: 'document_detail'
w8: 52/160 failed   (32 %)
```

With the refresh neutralised, the same benchmark ran **0/560 errors**. The fix is to build the new
endpoint map into a local and swap it in under `self._rate_lock` (or a dedicated lock), never to clear
the live one — and to hold the lock only across the swap so workers are not serialised on the refresh.
Cheaper alternative: one `DREHttpClient` per worker thread, which the fetch loop can do today.

**(b) The empty-record guard rejects every numberless diploma.** `get_document_detail()` raises
`DREApiError` when a record has neither `Numero` nor `ELI`. Pre-1976 diplomas legitimately have no
number ("Decreto de 20 de Abril de 1982"), and nothing before 1990 has an ELI, so the guard fires on
**29/120 = 24 %** of a decade-stratified sample. Those records are real: correct `Id`,
`DataPublicacao`, `Emissor`, `Serie`, `Publicacao`. The guard's purpose — catching the
`Id: 0 / DataPublicacao: 1900-01-01` default record — is served better by testing
`Id not in ("", "0") and DataPublicacao != "1900-01-01"`.

### 4.4 Total cost of the full re-fetch

Recommended scope, 1960+, as-published surface (B):

| phase | requests | bytes |
|---|---:|---:|
| Sitemap index + 587 children | 589 | 785 MB |
| `get_journals_by_date`, 1960-01-01 → 2026-12-31 (24,472 calendar days) | 24,472 | 29 MB |
| `get_documents_by_journal`, Série I journals (17,480 weekdays × 95 % × 1.37) | ~22,750 | 64 MB |
| `get_document_detail`, 198,516 sitemap 1960+ × 1.0459 sitemap-miss uplift | **207,628** | **6.09 GB** |
| **Subtotal, surface B** | **255,439** | **6.97 GB** |
| Consolidated surface A (RESEARCH-PT-v2 §3.5, unchanged) | ~42,000 | — |
| **Total** | **≈ 297,000** | — |

Wall clock for the 255,439 surface-B requests:

| setting | wall clock | % of measured server capacity |
|---|---:|---:|
| **2.0 req/s** (polite sustained) | **35.5 h** | 4.5 % |
| 4.0 req/s | 17.7 h | 9.0 % |
| 8.0 req/s | 8.9 h | 17.9 % |
| 8 workers uncapped (44.7 req/s) | 1.6 h | 100 % |

RESEARCH-PT-v2 §12's "~150,000 requests, ~15–18 h" was optimistic on both counts: scope B is 1.7×
the request count, and 150,000 requests in 15–18 h implies ~2.5 req/s, which is the right *order* but
was not the measured detail-call profile.

### 4.5 Recommended `config.yaml`

```yaml
  pt:
    repo_path: "../countries/pt"
    data_dir: "../countries/data-pt"
    max_workers: 4
    source:
      base_url: "https://diariodarepublica.pt/dr"
      sitemap_index: "https://files.dre.pt/sitemap/sitemap.xml"
      requests_per_second: 2.0     # global cap; 4 workers share it
      request_timeout: 60          # p99 payload is 581 KB; 30 s is tight for the 830 KB tail
      first_year: 1960             # DRE has no machine-readable text before this
      series: 1
```

Why these values:

- **`requests_per_second: 2.0`** — the politeness ceiling for sustained work, and 4.5 % of what the
  server demonstrably absorbs. Raising it to 4.0 halves the run to 17.7 h and is still under 10 % of
  measured capacity; that is a defensible call for a one-off bootstrap, but 2.0 is the default the
  daily should keep. Back off to 0.5 and re-probe on the first 429 — none was ever observed, so the
  handler is untested and should be conservative.
- **`max_workers: 4`** — the limiter in `HttpClient._wait_rate_limit` is a single global lock, so
  workers do not raise throughput past the cap. What they buy is that the 1-in-100 830 KB document
  does not stall the pipe. 4 workers held p95 at 0.228 s; 8 pushed it to 0.543 s for no benefit under
  a 2 req/s cap. **Fix bug (a) first** — at 4 workers the current client loses 13 % of requests.
- **`request_timeout: 60`** — the current 30 s is fine for p95 but the 829,662-byte tail on a slow
  link is not worth a retry.

---

## 5 · Resumability

The run is 35 h. It will be interrupted. The existing machinery in `pipeline.py` already covers most
of it; what follows is what PT adds.

### 5.1 What already works

- **`{data_dir}/discovery_ids.txt`** — `generic_fetch_all` writes the discovered id list once and
  reloads it on restart unless `--force` (`pipeline.py:358`). Discovery never re-runs by accident.
- **`{data_dir}/json/{safe_id}.json`** — `generic_fetch_one` returns the cached parse if the file
  exists and `force` is false (`pipeline.py:266`). A restart re-walks the id list and skips completed
  work at filesystem speed.
- **`--limit` / `--offset`** — splits the id list across machines (`pipeline.py`), so the 35 h can be
  four 9 h runs in parallel if that is ever wanted.

`safe_id` is `norm_id.replace(":", "-").replace("/", "-").replace(" ", "")`. With the sitemap ref as
norm_id, `/dr/detalhe/decreto-lei/9-2022-177455548` becomes
`-dr-detalhe-decreto-lei-9-2022-177455548.json` — ugly but stable, unique, and reversible. 208,000
files in one directory is fine on APFS; shard by `tipo` if it ever isn't.

### 5.2 What PT adds — the discovery cache is two-phase

`discovery_ids.txt` is written *after* discovery completes. PT's discovery is ~47,500 requests and
6.6 h at 2 req/s; losing it to a crash at hour 6 is not acceptable. Split it:

```
{data_dir}/
  sitemaps/                       # 587 .xml.gz + sitemap.xml — already on disk, re-fetch is 118 s
  sitemaps/_all-detalhe-urls.tsv.gz
  journal_walk.jsonl              # ONE LINE PER DATE, appended and fsynced as it completes
  discovery_ids.txt               # the union, written once both phases are done
  discovery_manifest.json         # provenance + the invariants to re-check on restart
```

`journal_walk.jsonl`, one record per date, appended immediately:

```json
{"date":"2016-12-02","journals":[105283973,105300329],
 "docs":[{"ref":"/dr/detalhe/portaria/302-a-2016-105300338","tipo":"Portaria",
          "num":"302-A/2016","serie":"I","sup":"1º Suplemento"}],
 "fetched_at":"2026-08-21T22:04:11Z"}
```

Restart reads the file, builds the set of completed dates, and resumes from the first gap. The walk is
date-ordered and each date is independent, so this is a `set` difference and nothing more. Dates that
errored are simply absent and get retried; a date with genuinely no Série I journal is written with
`"journals": []` so it is not retried forever.

### 5.3 Detecting a DRE redeploy mid-run

This is the failure mode that already bit Portugal once (`docs/pt-dre-api.md`, "The May 2026
redeploy"): the client kept POSTing to renamed actions, got HTML, and the daily still exited 0.

Two signals, both cheap and both already half-present:

1. **`moduleVersion` is the redeploy fingerprint.** `_init_session()` reads `versionToken` from
   `/dr/moduleservices/moduleversioninfo`. Record it in `discovery_manifest.json` at run start and
   re-read it at every session refresh. A change means DRE redeployed. It is **not** fatal — the
   `apiVersion` hashes are re-resolved from the MVC JS on the next `_init_session()`, which is the
   whole point of `_resolve_endpoint`. Log it, record the new token in the manifest, keep going.
2. **A wholesale action rename is fatal and already raises.** `_resolve_endpoint` raises `DREApiError`
   listing every action it *did* find when no known prefix matches. That must abort the run, not skip
   a batch: the fix is a one-line addition to `_SCREEN_ENDPOINTS`, and everything fetched so far is
   still on disk. Resume after the fix costs nothing.

What must **not** happen is the third case — a redeploy that changes the *response shape* without
changing an action name. The guards for that are already in the client (`_post` raises on non-JSON,
`get_journals_by_date` / `get_documents_by_journal` raise rather than return `[]`), and they should
stay strict. Add one run-level invariant: **if more than 2 % of a 500-document window fails, stop the
run.** A steady low error rate is pre-1960 stubs and is expected; a step change is a redeploy.

Recovery after any abort is the same procedure: fix the client, re-run the same command, the JSON
cache skips everything already fetched.

### 5.4 Pre-1960 and the completeness gate

The 68,916 pre-1960 in-scope URLs have no text. Do not fetch them in the main pass — 9.6 h at 2 req/s
for 165 MB of stubs that cannot become law files. Instead:

- Keep them enumerated in `sitemaps/_all-detalhe-urls.tsv.gz` (already done, cost 0).
- Record the boundary in `country_meta.yaml`: coverage starts 1960, earlier diplomas are catalogued by
  DRE as scans only. This makes the README's "1911" honest instead of wrong.
- If the catalogue is ever wanted as metadata-only records, it is a separate, resumable 9.6 h pass
  against the same `{data_dir}/json/` cache.

Before the commit phase, gate on three counts written to `discovery_manifest.json`:

```
sitemap_in_scope_1960plus   198,516     # from _all-detalhe-urls.tsv.gz
journal_walk_serie1_inscope     …       # from journal_walk.jsonl
union_fetched                   …       # count of {data_dir}/json/*.json
```

`union_fetched` must be **≥ `sitemap_in_scope_1960plus`** and the walk must have covered every date in
1960-01-01 → today with no gaps. Portugal shipped once with a silent shortfall; this is the check that
would have caught it.

---

## Reproducing any number here

| what | how |
|---|---|
| Sitemap download + URL index | `scripts/pt_discovery/fetch_sitemaps.py` → `countries/data-pt/sitemaps/` |
| Per-type counts, year split | `countries/data-pt/sitemaps/_all-detalhe-urls.tsv.gz`, `cut -f1 \| sort \| uniq -c` |
| Repo → sitemap match | `scripts/pt_discovery/match_repo_to_sitemap.py` |
| Journal walk | `scripts/pt_discovery/journal_walk.py` (`random.seed(11)`, 99 dates) |
| Concurrency benchmark + text-by-decade | `scripts/pt_discovery/bench_detail.py` (`random.seed(99)`, 560 documents) |
| Live re-check of the API contract | `docs/pt-dre-api.md`, "Re-checking the contract by hand" |

Run order: `fetch_sitemaps.py` (needs `countries/data-pt/sitemaps/sitemap.xml`; re-runs from the
`.xml.gz` cache in 4 s) → `match_repo_to_sitemap.py` → `journal_walk.py` → `bench_detail.py`.
Intermediates go to `$PT_WORK` (default `countries/data-pt/discovery-work/`); the repo filename list
comes from `$PT_FILES` (default `/tmp/pt-files.txt`).

`bench_detail.py` monkey-patches out the periodic session refresh described in §4.3(a). That patch is
a benchmark scaffold, not a fix — the real fix belongs in `client.py`.
