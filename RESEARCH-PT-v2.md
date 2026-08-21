# RESEARCH-PT-v2 — Portugal deep rebuild

Status: **Step 0 (research) — analysis complete, implementation not started**
Branch: `feat/pt-v2` · Worktree: `engine-pt/`
Date: 2026-08-21

This document is to Portugal what `RESEARCH-ES-v2.md` was to Spain: the audit of
what we shipped, the evidence for what the source actually offers, and the plan to
close the gap. It follows the Step 0 structure of `ADDING_A_COUNTRY.md`.

---

## TL;DR

Portugal was shipped in April 2026 from a **third-party SQLite mirror**
(`dre.tretas.org`) containing the *as-published* text of each diploma, one snapshot
per law. It has **zero version history**; 99.3 % of its commits are dated
**1970-01-02** (the epoch clamp) and carry **`Source-Id: PLACEHOLDER`**; their
subjects and bodies are **in Spanish**; a scraper label `TEXTO :` sits in **75.6 %**
of the files and `(ver documento original)` replaces a table, figure or annex in
**25.4 %**; **52.9 %** have no heading at all; and it contributes **zero rows** to the
web app's `reforms` table.

Meanwhile the official source, `diariodarepublica.pt`, publishes a **fully consolidated,
article-level, point-in-time versioned corpus** of 5,561 diplomas — every amendment
dated, attributed to the amending act, and resolvable to the exact article it touched.
None of it is used today.

The rebuild is: switch to the official DRE for both surfaces, implement the
`get_suvestine`/`parse_suvestine` version-history hook, rewrite the parser, capture the
full metadata inventory (including the ELI RDFa block), and reprocess the repo from
scratch.

---

## §0 Ground rules

1. **No fix-up commits.** The output format is final and the history is the product.
   Portugal gets a full reprocess, not patches on top of a wrong history
   (memory: `feedback_commit_integrity`, `feedback_format`).
2. **Official source only.** `dre.tretas.org` is a community mirror; every `source:`
   URL in the repo must point at `diariodarepublica.pt` / `data.dre.pt`.
3. **Historical versions are non-negotiable** (`ADDING_A_COUNTRY.md` priority #2,
   memory: `feedback_versions_mandatory`). Portugal currently fails this outright.
4. Every number in this document was measured. The command is given next to it.

---

## §1 Evidence — what Portugal looks like today

Measured on a blobless clone of `legalize-dev/legalize-pt`
(`git clone --filter=blob:none --no-checkout`, HEAD of 2026-08-21).

### 1.1 The corpus

| Metric | Value | How |
|---|---|---|
| `.md` files | **109,929** | `git ls-tree -r --name-only HEAD -- pt \| wc -l` |
| Commits | **109,932** | `gh api repos/…/commits` Link header |
| Repo size | ~3.0 GB | `gh repo view --json diskUsage` |
| Commits per file | **≈ 1.00** | 109,932 commits / 109,929 files |

### 1.2 There is no history — GATE FAILURE

```
$ git log --format='%s' | count by prefix
 109162  [bootstrap]
    768  [new]
      1  [fix-pipeline]
      1  (no prefix — repo init)
```

**Zero `[reform]` commits.** Every law is a single snapshot of its *as-published*
text. A reform of the Código Civil in 2025 is nowhere in this repo.

And the snapshot is not even dated correctly. Here is a real production commit,
verbatim (`git show` on any `[bootstrap]` commit):

```
1970-01-02 00:00:00 +0000 | enrique <enriquelopezcast@gmail.com>

[bootstrap] Exonera a Drª Maria Fernanda da Silva Mendes do cargo de Secretária
Regional dos Assuntos Sociais e o Dr. Francisco Manu — versión original 1900

Publicación original de Exonera a Drª Maria Fernanda da Silva Mendes do cargo de
Secretária Regional dos Assuntos Sociais e o Dr. Francisco Manu.

Norma: DRE-D-1-2002
Fecha: 1900-01-01
Fuente: https://dre.tretas.org/dre/159184/

Source-Id: PLACEHOLDER
Source-Date: 1900-01-01
Norm-Id: DRE-D-1-2002
```

Seven distinct defects in one commit, each of them repeated ~109,000 times:

| Defect | Count | % of commits |
|---|---|---|
| Author date is the **Unix epoch clamp, 1970-01-02**, not the law's date | 109,162 | 99.30 % |
| `Source-Id: **PLACEHOLDER**` — the literal placeholder string, in production | 109,162 | 99.30 % |
| `Source-Date: 1900-01-01` — the placeholder date | 109,162 | 99.30 % |
| Subject and body **in Spanish** in a Portuguese repo ("versión original 1900", "Publicación original de") | 109,162 | 99.30 % |
| Spanish trailers `Norma:`/`Fecha:`/`Fuente:` alongside the English ones — **two incompatible schemas** | 109,431 | 99.54 % |
| Author is a **personal Gmail address**, not the Legalize bot | 109,347 | 99.47 % |
| No `Co-Authored-By` trailer | 109,932 | 100 % |
| Subject hard-truncated mid-word (mean 145.8 chars, 94.5 % ≥ 100) | ~103,900 | 94.5 % |

`git log --format=%at | sort | uniq -c | sort -rn | head -1` → `109162  86400`.

**Root cause, and it is one line.** `DRETextParser.parse_text` builds every `Version`
with `pub_date=date(1900, 1, 1)` and `norm_id="PLACEHOLDER"` — see the docstring:
*"Use placeholder values — the pipeline fills in real dates via extract_reforms()"*.
Nothing ever fills them in. `extract_reforms` reads those same placeholders, and
`committer/git_ops.py::_date_to_epoch` clamps any pre-1970 date to 1970-01-02. The
768 daily `[new]` commits, which take a different path, are dated correctly in
**768/768** cases — which is what proves the bootstrap path is the broken one.

The core promise on the front page of legalize.dev — *cada reforma um commit*, dated
when it took effect — is not merely incomplete for Portugal. It is inverted: there are
no reforms, and the dates that exist are wrong.

Worse, this is invisible in the product twice over:

- `enrichment/src/enrichment/frontmatter.py::parse_reform_commit` returns `None` for
  `[bootstrap]`, and its accept-list is `[reform`, `[nueva`, `[derogacion`,
  `[correccion` — **`[new]` is not on it** (it is the English rename of `[nueva]`;
  the parser was never updated). So the 768 daily commits are dropped too.
  → **Portugal contributes 0 rows to the `reforms` table.**
- `_ARTICLE_PATTERNS` in the same file has patterns for `Artículo`, `Article`,
  `Artikel` and `§` — **none for `Artigo`** → `laws.article_count` is 0 for every
  Portuguese law.

Both are cross-country bugs (they hit `[repeal]` and `[correction]` for every
country), but Portugal is where they bite hardest. The root cause is a half-finished
rename: `models.py::CommitType` was translated to English (`new`, `reform`, `repeal`,
`correction`) but the DB-side parser still matches the Spanish names — and
`engine/CLAUDE.md` still documents the Spanish list
(`[bootstrap]`, `[reforma]`, `[nueva]`, `[derogacion]`, `[correccion]`,
`[fix-pipeline]`) as the locked format. The docs, the emitter and the consumer
disagree three ways.

### 1.3 Text quality — 600-file random sample

Corpus-wide counts via `git grep -l … HEAD -- 'pt/*.md'`, plus a 1,000-file random
sample for the per-file statistics:

| Defect | Files | % of corpus |
|---|---|---|
| Body contains the literal scraper label **`TEXTO :`** | **83,072** | **75.6 %** |
| Body contains **`(ver documento original)`** — a table, figure or annex that was never converted (61,674 occurrences) | **27,954** | **25.4 %** |
| …of those, files where that placeholder is essentially the **entire body** | **385** | 0.35 % |
| **No heading below H1** — the whole law is one wall of paragraphs | **58,132** | **52.9 %** |
| H1 title repeated verbatim as body text | ~98 % of sample | ~98 % |
| Markdown pipe table present | **907** | **0.82 %** |
| `source:` citing the third-party scraper `dre.tretas.org` as official | 963 | 0.88 % |
| `source:` pointing at a **dead endpoint** (`dre.pt/util/getpdf.asp`, soft-404) | 1,050 | 0.96 % |
| `source:` using a `data.dre.pt` ELI | 498 | 0.45 % |
| Raw C1 control bytes (unmapped cp1252: `\x9c` for `œ`, `\x96` for `–`, `\x97` for `—`) | 4 | 0.004 % |
| Leftover HTML tags · undecoded entities · U+FFFD · empty bodies | **0** | — |

Two of these deserve to be read twice. **`(ver documento original)`** is DRE's own
"see the original document" marker, and the pipeline copies it through verbatim: one
Portuguese law in four has at least one table, figure or annex replaced by that
string, and 385 laws consist of essentially nothing else. The complete body of
`pt/DRE-DL-109-G-2021.md` is:

```markdown
# Decreto-Lei n.º 109-G/2021

Decreto-Lei n.º 109-G/2021

de 10 de dezembro

Sumário: Transpõe parcialmente a Diretiva (UE) 2019/2161…

(ver documento original)

114808797
```

That is the whole law. (The trailing `114808797` is an internal id, also copied
through.) Meanwhile `legalize-pt/README.md` tells the reader *"as tabelas são
convertidas para tabelas Markdown"* — true for **0.82 %** of files.

The good news, and it is worth stating: the HTML→text conversion itself is clean.
Zero leftover tags, zero undecoded entities, zero replacement characters, zero empty
bodies corpus-wide. The failures are structural and editorial, not encoding.

A representative file, in full shape:

```markdown
# Portaria n.º 19183

TEXTO :

Portaria n.º 19183

Manda o Governo da República Portuguesa, pelo Ministro do ultramar, nos termos
do artigo. 6.º do Decreto n.º 41026, de 9 de Março de 1957, …
```

Three defects in six lines: the scraper label, the duplicated title, and no
article structure (this portaria numbers its provisions `1.º`, `2.º` — the parser
only recognises the literal word `Artigo`).

### 1.4 Tables are structurally broken

Reproduced against the current parser:

```python
html = b"<p>Artigo 1.&ordm; Tabela</p><table><tr><th>Escal&atilde;o</th><th>Taxa</th></tr>…"
render_norm_at_date(meta, DRETextParser().parse_text(html), …)
```

```markdown
Artigo 1.&ordm; Tabela

| Escal&atilde;o | Taxa |

| --- | --- |

| at&eacute; 7703 | 13,25% |
```

Three separate bugs visible at once:

1. **`_strip_html` builds a pipe table, then `_parse_text_to_blocks` splits the text
   on `\n` and makes every row its own `parrafo` `Paragraph`.** The renderer emits a
   blank line after each paragraph, so the table never renders as a table. No
   Portuguese tax schedule, tariff annex or fee table in the repo is a table.
2. **Named HTML entities are not decoded** — a *latent* bug. `_strip_html` hand-rolls
   a table of ten entities plus `&#NNN;`; `&ordm;` (º), `&atilde;` (ã), `&eacute;` (é),
   `&ccedil;` (ç) pass through verbatim. It has not fired in production because
   neither the tretas.org dump nor the official DRE payload uses named entities
   (0 occurrences corpus-wide, 0 in every official fixture measured). It is still a
   bug the rewrite must not carry over, because it also breaks heading detection:
   `Artigo 1.&ordm;` does not match `_RE_ARTIGO`.
3. **`<style>` blocks and `(ver documento original)` markers pass straight through.**
   The regex stripper removes tags but not the text inside `<style>`, and it has no
   notion that DRE's "see the original document" marker means *a table was here*.

The local `_html_table_to_markdown` also ignores `rowspan`/`colspan` and `<thead>`,
while `src/legalize/fetcher/_tables.py::render_table` — the shared helper LV/BE/CH
already use — handles all three.

Net effect on the corpus: **907 files (0.82 %) have a Markdown table**, while 27,954
(25.4 %) have a `(ver documento original)` placeholder where a table should be, and
flattened dot-leader rows are everywhere:

> `Artigo 4.º, n.º 1), alínea a) "Aquisições … Veículos com motor» ... 422000$00`

(that line also shows a quote-normalisation bug — the opening `«` became a straight
`"` and the closing `»` survived).

### 1.5 Structural hierarchy is collapsed

`_classify_line` maps the Portuguese hierarchy onto four levels:

| Source | css_class | Renders as |
|---|---|---|
| `PARTE`, `LIVRO`, `TÍTULO` | `titulo_tit` | `##` — **three levels collapsed into one** |
| `CAPÍTULO` | `capitulo_tit` | `###` |
| `SECÇÃO`, `SUBSECÇÃO` | `seccion` | `####` — **two levels collapsed** |
| `Artigo` | `articulo` | `######` |

Nothing at all for **Anexo**, **Apêndice**, **Subtítulo**, **Divisão**, **Subdivisão**,
disposições transitórias/finais, the signature block, or the preamble formula. They
all fall through to `parrafo`.

The Código Civil has Livro > Título > Capítulo > Secção > Subsecção > Divisão >
Subdivisão — seven levels, rendered today as three.

### 1.6 Scope gaps — whole categories of law are absent

Cross-matching the 5,561-diploma official consolidated catalogue (§2.2) against the
repo's filenames by ELI type + number + year:

| ELI type | In DRE consolidated | In legalize-pt | Coverage |
|---|---|---|---|
| `dec-lei` Decreto-Lei | 2,086 | ~100 % | ok |
| `port` Portaria | 1,562 | ~100 % | ok |
| `lei` Lei | 600 | 100 % | ok |
| `declegreg` Decreto Legislativo Regional | 300 | 100 % | ok |
| `decregulreg` Decreto Regulamentar Regional | 152 | 100 % | ok |
| **`resolconsmin` Resolução do Conselho de Ministros** | **329** | **0** | **missing** |
| **`leiorg` Lei Orgânica** | **15** | **0** | **missing** |
| **`resolassrep` Resolução da AR** | 32 | 0 | missing |
| **`decpresrep` Decreto do Presidente da República** | 36 | 0 | missing |
| **`despnorm` Despacho Normativo** | 27 | 0 | missing |
| `acstj` (acórdãos uniformizadores), `declretif`, `resolalraa`/`resolalram`, `mapofic`, `av`, `regul-cmvm`, … | ~50 | 0 | missing |

The cause is `discovery.py::MAJOR_DOC_TYPES`, a hand-written list of 11 uppercase
strings. `"RESOLUÇÃO"` is on it; `"RESOLUÇÃO DO CONSELHO DE MINISTROS"` is not, and
the SQL filter is an exact `IN (...)` match. Resoluções do Conselho de Ministros are
the government's principal policy instrument — 329 of them are consolidated by DRE
and none is in the repo.

### 1.7 Identifiers are inconsistent

`_make_identifier` builds `DRE-{TYPECODE}-{number with / → -}`.

| Observation | Count | Note |
|---|---|---|
| ids ending in a 2-digit year (`DRE-D-1-74`) | **55,742** | from DRE numbers written `1/74` |
| ids ending in a 4-digit year (`DRE-L-39-2016`) | 32,650 | from DRE numbers written `39/2016` |
| ids with no year at all (`DRE-DL-47344`) | ~6,200 | pre-1976 continuous numbering — legitimate |
| `…-UNKNOWN` | 2 | numberless diplomas |
| Malformed (`DRE-DLR--2013-A.md`, empty number) | 1 | |
| Actual filename collisions | 0 | verified case-insensitively |

No data loss, but the scheme is unguessable: the same law is `DRE-D-1-74` or
`DRE-D-1-1974` depending on how DRE typed the number that day. It is also
disconnected from the official identifier Portugal already publishes (ELI, §6).

### 1.8 Regional law has no jurisdiction

5,032 files carry the regional prefixes `DRE-DLR-` (2,428) and `DRE-DRR-` (2,604),
plus regional resolutions filed as `DRE-R-1-2000-A` / `-M`. The `-A` / `-M` suffix is
the Açores/Madeira marker, carried inside the identifier. Every one of them sits in
the national `pt/` directory with `jurisdiction` unset.

Spain models this correctly (`es-pv/`, `es-ct/`, …). Portugal should have `pt-20`
(Açores) and `pt-30` (Madeira) — see §6.2.

### 1.9 The defects, ranked

| # | Defect | Scale | Fixable without a reprocess? |
|---|---|---|---|
| 1 | **No version history at all** — 0 `[reform]` commits | 109,929 laws | No |
| 2 | **Commit dates are the Unix epoch clamp (1970-01-02)**, not the law's date | 109,162 commits (99.3 %) | No |
| 3 | **`Source-Id: PLACEHOLDER` / `Source-Date: 1900-01-01`** shipped to production | 109,162 commits | No |
| 4 | Commit subjects and bodies **in Spanish** in a Portuguese repo | 109,162 commits | No |
| 5 | Two incompatible trailer schemas (`Norma/Fecha/Fuente` + `Source-Id/…`) | 109,431 commits | No |
| 6 | Commits authored by a **personal Gmail address**, not the bot | 109,347 commits | No |
| 7 | Bootstrapped from a third-party mirror, not the official DRE | 109,929 laws | No |
| 8 | `TEXTO :` scraper label in the body | **83,072 files (75.6 %)** | No |
| 9 | `(ver documento original)` where a table/figure/annex should be | **27,954 files (25.4 %)**, 385 of them almost entirely | No |
| 10 | No heading below H1 | **58,132 files (52.9 %)** | No |
| 11 | H1 title duplicated as body text | ~98 % of files | No |
| 12 | Tables destroyed by the paragraph splitter | only 907 files (0.82 %) have a table at all | No |
| 13 | `last_updated: 1900-01-01` in the frontmatter | 109,162 files (99.3 %) | No |
| 14 | `eli` in 0 files, `summary` in 0.70 %, `pdf_url` in 0.47 %; `subjects` never emitted | 109,929 laws | No |
| 15 | Whole categories missing (RCM, Lei Orgânica, Decreto do PR, …); 10 of 20 mapped act types produce zero files | ~500 consolidated diplomas + siblings | No |
| 16 | Nothing before 1960, while the README claims coverage "desde 1911" | corpus-wide | No |
| 17 | Regional law has no `jurisdiction` | 5,032 files | No |
| 18 | Inconsistent 2-digit/4-digit year in identifiers | 55,742 files | No (filenames) |
| 19 | `source:` dead or third-party | 1,050 dead + 963 tretas.org | No |
| 20 | `department` carries internal DB annotations ("(Utilizar a Partir de 29 de Julho de 2004)") | 663 files | No |
| 21 | Raw C1 control bytes (unmapped cp1252) | 4 files | No |
| 22 | No `Co-Authored-By` trailer | 109,932 commits | No |
| 23 | `[new]`/`[repeal]`/`[correction]` not parsed by the DB sync | cross-country | **Yes** — one line in `enrichment` |
| 24 | `article_count` always 0 (no `Artigo` pattern) | cross-country | **Yes** — one line in `enrichment` |

Twenty-two of the twenty-four require regenerating the repository. That is the whole
argument for rebuilding once, properly, rather than patching.

### 1.10 No tests

There is no `tests/test_parser_pt.py` and no `tests/fixtures/pt/` (both created by
this research). CI's per-country smoke job for PT runs `tests/test_daily_pt.py` and
`tests/test_pt_client_apiversion.py` — client plumbing only, nothing about output
quality.

---

## §2 The sources

### 2.1 Three surfaces, not one

| Surface | What it gives | Versions? | Used today |
|---|---|---|---|
| **A. DRE Legislação Consolidada** (`/dr/legislacao-consolidada/…`) | Article-level consolidated text, point-in-time at any date, full amendment graph | **Yes** | **No** |
| **B. DRE as-published detail** (`/dr/detalhe/…`) | The diploma exactly as printed in the Diário da República, + full metadata + ELI RDFa | No (by definition) | Daily only |
| **C. `dre.tretas.org` SQLite dump** | Third-party mirror of B, weekly | No | **Bootstrap (all 109,929 files)** |

The rebuild uses **A for the 5,561 consolidated diplomas** (the high-value core:
every code, every consolidated law) and **B for everything else**, and retires C.

### 2.2 Enumeration — the catalogue is one file

`https://diariodarepublica.pt/dr/robots.txt`:

```
User-agent: *
Sitemap: https://files.dre.pt/sitemap/sitemap.xml
```

No `Disallow`, no `Crawl-delay`. The sitemap index lists 588 per-type sitemaps.
One of them is the whole consolidated catalogue:

```
https://files.diariodarepublica.pt/sitemap/legislacao-consolidada-sitemap-1.xml
→ 852 KB, 5,561 <url> entries with <lastmod>
```

Each URL is `/dr/legislacao-consolidada/{tipo}/{ano}-{DiplomaFragId}` — the two
identifiers the API needs, for free, with no crawling.

Catalogue shape (resolved: 5,561 header calls, 33 errors, ~50 min at 4 workers /
0.6 s; saved to `countries/data-pt/consolidated-catalogue.jsonl.gz`):

| | |
|---|---|
| Diplomas | 5,561 (5,528 resolved, 33 errors) |
| Year range | 1926 – 2026 |
| By decade | 1920s 1 · 1930s 2 · 1940s 1 · 1950s 4 · 1960s 24 · 1970s 125 · 1980s 313 · 1990s 761 · 2000s 1,419 · 2010s 1,719 · 2020s 1,159 |
| Distinct ELI types | 33 |
| Distinct emissores | 570 |
| With an ELI URI | 5,466 (98.3 %) |
| `Consolidado = True` | 5,350 |
| `AnaliseJuridicaPublica = True` | 5,455 |

### 2.3 The API — how to talk to it

`diariodarepublica.pt` is an OutSystems SPA with no public API; we drive the same
`screenservices/` endpoints its own JavaScript calls. `docs/pt-dre-api.md` already
documents the handshake for surface B. Surface A adds one module,
`dr.LegislacaoConsolidada`, with **four** data actions:

| Action | Screen JS | Purpose |
|---|---|---|
| `DataActionGetDiplomaFragByIdAndApplicationSetting` | `LegCons_Detalhe` | Resolve `Tipo`+`Key` → `DiplomaLegisId`, title, ELI, header metadata |
| `DataActionGetData` | `LegCons_Detalhe` | **The point-in-time text**: all fragments as of `DataSelecionada` |
| `DataActionGetInitialDate` | `LegCons_Detalhe` | First consolidation date |
| `DataActionGetConsolidacaoByDiplomaFrag` | `AlteracoesTimelineByDiplomaLegisId` | **The amendment timeline** |

Two protocol facts that cost an hour each to find, recorded so nobody pays again
(also written into `tests/fixtures/pt/version-spike.txt`):

1. **Block actions must be posted under the *screen's* `viewName`.**
   `AlteracoesTimelineByDiplomaLegisId` is a Block; posting
   `viewName: "LegislacaoConsolidada.AlteracoesTimelineByDiplomaLegisId"` returns
   `{"exception": {"message": "No role validation found"}}`. It must be
   `"LegislacaoConsolidada.LegCons_Detalhe"`.
2. **`DataActionGetData` reads the previous action's output off the screen state.**
   Without the screen variable `GetDiplomaFragByIdAndApplicationSetting` carrying
   the full response of the header call, it throws
   `System.NullReferenceException`. With it, a 5 KB request body returns the whole
   consolidated document.

Working Python: `scripts/pt_spike_consolidada.py`, `scripts/pt_spike_timeline.py`.

### 2.4 ELI — Portugal is an ELI publisher

Every diploma carries an ELI URI:

```
https://data.dre.pt/eli/dec-lei/47344/1966/p/cons/20260623/pt/html   (consolidated)
https://data.dre.pt/eli/lei/29/2026/06/23/p/dre/pt/html              (as published)
```

`data.dre.pt` resolves these to the SPA and **drops the date component**, so they are
permalinks, not a data API — the point-in-time fetch still goes through
`DataActionGetData`. But the ELI *type token* (`dec-lei`, `port`, `declegreg`, …) is
the official, stable type vocabulary and is the right basis for our identifiers (§6).

The as-published detail also returns **`ELIMetadataHTML`** — an 8.7 KB RDFa block
using the European ELI ontology. For Lei 29/2026 it carries:

| Property | Value |
|---|---|
| `eli:number` | `29/2026` |
| `eli:id_local` | `1135578391` |
| `eli:type_document` | `…/authority/resource-type/lei` |
| `eli:responsibility_of_agent` | `…/authority/legal-agent/ar` |
| `eli:date_publication` | `2026-06-23` |
| `eli:in_force` | `…ontology#InForce-inForce` |
| **`eli:is_about` × 12** | `…/authority/legal-subject/30211723`, … — **the subject descriptors** |
| **`eli:cites` × 3** | `…/eli/dec-lei/15/2022/…`, `http://data.europa.eu/eli/dir/2019/944/oj`, `…/dir/2018/2001/oj` — **including EU directives transposed** |
| `eli:legal_value` | `…ontology#LegalValue-official` |
| `eli:licence` | `…/eli/dec-lei/83/2016/p/dr/pt/html` |
| `eli:publisher` / `eli:rightsholder_agent` | INCM |
| `eli:language` | POR |

The current parser ignores this field entirely. It is the single richest metadata
source Portugal offers, and it directly fills `NormMetadata.subjects` (empty today for
every PT law) plus cross-references to national and **EU** law.

Caveat measured: the `authority/legal-subject/{id}` URIs are **not dereferenceable** —
they redirect to the SPA. Resolving descriptor IDs to labels needs a separate lookup
(open question, §12). The as-published payload also carries a plain-text
`DiplomaExterno.Descritores` field, empty on the samples checked so far.

**The ELI path encodes jurisdiction.** Compare:

```
https://data.dre.pt/eli/dec-lei/47344/1966/    p /cons/20260623/pt/html   ← p = Portugal
https://data.dre.pt/eli/declegreg/2/2025/07/02/m /dre/pt/html             ← m = Madeira
```

That single segment is the authoritative jurisdiction marker — no need to guess from
`IsRegional` or from the `-A`/`-M` suffix in the number (§6.2).

### 2.5 Licensing and access

**robots.txt** (`https://diariodarepublica.pt/dr/robots.txt`, verbatim):

```
User-agent: *
Sitemap: https://files.dre.pt/sitemap/sitemap.xml
```

No `Disallow`, no `Crawl-delay`.

**The licence, stated by the source itself.** Every diploma's ELI RDFa carries
`eli:licence → https://data.dre.pt/eli/dec-lei/83/2016/p/dr/pt/html`, i.e.
**Decreto-Lei n.º 83/2016, de 16 de dezembro** — *"Aprova o serviço público de acesso
universal e gratuito ao Diário da República"*. Its Artigo 3.º, read from DRE's own
consolidated text:

> "1 - A edição do Diário da República é de acesso universal e gratuito.
> 2 - O acesso universal e gratuito compreende a possibilidade de impressão, arquivo,
> pesquisa e livre acesso ao conteúdo dos atos publicados nas 1.ª e 2.ª séries do
> Diário da República, em formatos eletrónicos de acesso aberto."

and its preamble commits to *"a disponibilização desses conteúdos em formatos
passíveis de reutilização (dados abertos) de forma livre e integral, a todos os
cidadãos."*

Alongside it: **Lei n.º 68/2021** (general open-data principles, transposing Directive
(EU) 2019/1024) and **Lei n.º 26/2016** (access to and reuse of administrative
documents). `eli:legal_value` is `LegalValue-official` — the electronic edition is the
authoritative one, and `eli:rightsholder_agent` is the INCM.

**One difference from Spain worth recording.** Portugal's copyright code does *not*
exclude statutes from protection the way Spain's LPI art. 13 does. `Código do Direito
de Autor e dos Direitos Conexos` (DL 63/85) **Artigo 7.º "(Exclusão de protecção)"**
lists only news of the day, petitions and pleadings, speeches before assemblies, and
political speeches. So the basis for redistributing Portuguese legislation is the
access/open-data legislation above, **not** a copyright exclusion. `readme_data.json`
for PT should cite DL 83/2016 art. 3.º + Lei 68/2021, not "public domain".

**On `dre.tretas.org`.** It is a community mirror of the DRE (the `dre` project,
GPLv3). Nothing about the current arrangement is unlawful, but three things make it
the wrong dependency for us: the data is second-hand (the `TEXTO :` artefact of §1.3
is theirs, not DRE's), it carries no consolidated versions at all, and the bootstrap
requires a human to download and decompress a ~12 GB dump before it can run — which
is why `config.yaml` still points at a file dated `2026-03-01`. Retire it.

---

## §3 Version history — the GATE

### 3.1 The spike (ADDING_A_COUNTRY.md §0.5) — PASSED

Law: **Código Civil, Decreto-Lei n.º 47344 de 1966-11-25**
`DiplomaLegisId 477358` / `DiplomaFragId 34509075`
Reproduce: `python3 scripts/pt_spike_consolidada.py out.json`

Two point-in-time snapshots of the same article:

| | snapshot at 2000-01-01 | snapshot at 2026-06-23 |
|---|---|---|
| Fragments in document | 2,868 | 2,895 |
| `Artigo 1601.º` version id | `58403586` | `1115206175` |
| `DataEntradaVigor` | 1978-04-01 | 2025-04-02 |
| Text | "…a) A idade inferior a **dezasseis anos**; b) … a interdição ou inabilitação…" | "…a) A idade inferior a **18 anos**; b) … a decisão de acompanhamento…" |

Distinct text, distinct version identity, distinct effective dates. Evidence saved as
`tests/fixtures/pt/version-spike.txt` + `version-spike.json`.

### 3.2 The amendment graph

`DataActionGetConsolidacaoByDiplomaFrag` for the same diploma
(`scripts/pt_spike_timeline.py 477358 34509075`):

```
102 amending diplomas · 1,165 individual modifications
71 distinct entry-into-force dates, 1900-01-01 → 2026-07-01
1,038 distinct target fragment versions
```

One modification record, verbatim:

```json
{ "TipoModificacao": "Altera",
  "Epigrafe": "(Inovações)",
  "FragmentoDestinoModificacao": "Artigo 1425.º",
  "FragmentoVersaoDestinoId": "1138222475",
  "PathDestinoModificacao": "Anexo > Livro III > Título II > Capítulo VI > Secção III",
  "TipoFragmento": "Artigo",
  "IdentificacaoFragmento": "1425.º",
  "FragmentoVersaoLink": "/dr/legislacao-consolidada/decreto-lei/1966-34509075-1138222475",
  "DataEntradaVigor": "2026-07-01" }
```

wrapped in its amending diploma:

```json
{ "LinkSitemap": "/dr/detalhe/lei/29-2026-1135578391", "Numero": "29/2026",
  "TipoDiploma": "Lei", "DataPublicacao": "2026-06-23",
  "SumarioDiplomaLegis": "Cria o regime jurídico do contrato de aproveitamento…",
  "DiplomaLegisId": "1135578391", "IsDiplomaOriginal": false }
```

This is exactly the legalize `Reform` model: a date (`DataEntradaVigor` → commit
author date), a source id (the amending diploma → `Source-Id`), and the affected
articles (`FragmentoDestinoModificacao` → `affected_blocks`). Nothing has to be
inferred.

### 3.3 The fragment model

Each entry of `LegConsBase.List` in a snapshot:

```
ConsolidacaoFragmento: Id · FragmentoVersaoId · PaiId · Orderm · IndexOrdem ·
  FullName ("Diploma > Livro III > Artigo 1425.º") · Name · Epigrafe ·
  PreviousID · NextId · IsAnexo · IsActive · FragmentoVersoesAnterioresId ·
  ConsolidacaoId · DataVersao · AssociacaoOrigemTitle · …
FragmentoVersao:      Id · Texto · Epigrafe · Identificacao · Ordem · Tituo ·
  TipoFragmentoId · VersaoEstadoId · DataEntradaVigor · DataProducaoEfeitos ·
  DataSuspensao · DataVersao · FragmentoPaiId · FragmentoId · …
Nivel · HasFilhos · TodosFilhosRevogados · DataEntradaVigorProximaVersao
Nota:            list of HTML notes (e.g. Constitutional Court rulings)
AlteracoesList:  list of HTML amendment notes with links to the amending act
```

**`TipoFragmentoId` is an explicit structural taxonomy** — no regex guessing. Observed
in the Código Civil (2,895 fragments):

| id | Type | Count | Target heading |
|---|---|---|---|
| 15 | Diploma | 1 | — (preamble) |
| 12 | Livro | 5 | `#` |
| 13 | Título | 19 | `##` |
| 5 | Subtítulo | 5 | `##` |
| 1 | Capítulo | 112 | `###` |
| 8 | Secção | 176 | `####` |
| 3 | Subsecção | 139 | `#####` |
| 9 | Divisão | 28 | `#####` |
| 6 | Subdivisão | 2 | `#####` |
| 11 | **Artigo** | 2,405 | `######` |
| 14 | Anexo | 1 | `##` |
| 7 | Assinatura | 2 | `**bold**` |

(ids 2, 4, 10 not seen in this diploma — likely `Parte` and others; the full map must be
built during implementation from a sweep of the catalogue.)

Plus `Nivel` (0–9) and `PaiId` give the exact tree. Today's parser reconstructs a
3-level approximation from line regexes.

### 3.4 Rich content in consolidated text — measured

Sample: 12 random consolidated diplomas from 2010+, 388 fragments, plus the Código
Civil (2,895) and the Código do Imposto do Selo (99).

- **Most consolidated `Texto` is plain text with `\n` line breaks — no HTML at all.**
  Código Civil: zero tags. Imposto do Selo: zero tags.
- **Newer consolidations do carry HTML**: one 2025 `decreto-regulamentar` in the
  sample had `<table>`/`<thead>`/`<tbody>`/`<th>`/`<td>`, `<p>`, `<div>`; others had
  `<a>` (cross-reference links) and `<sup>`.
- Aggregate over the 388-fragment sample: `p` 34 · `td` 26 · `a` 10 · `tr` 8 · `th` 8 ·
  `sup` 4 · `div` 2 · `table` 2 · `thead` 2 · `tbody` 2. **1 fragment in 388 had a table.**
- No HTML entities, no mojibake, no C1 controls found in any sample.

**Consequence — a real fidelity limit to document.** Where the printed law had a
table, older DRE consolidations flattened it into text with dot leaders:

> `1.1 – Aquisição onerosa … – sobre o valor ... 0,8%`
> (Tabela Geral do Imposto do Selo, Anexo II)

That table is lost *in the source*, not by us. The as-published surface (B) and the
`URLPDF` still have it. Options are recorded in §12 as an open question; the honest
default is to render what the consolidated source gives and record
`extra.consolidated_text_is_plain: true` so the limitation is visible.

The parser must therefore handle **both** shapes: plain text with newlines, and HTML.

### 3.5 Fetch cost

Measured: `DataActionGetData` returns the **whole document** regardless of
`FragmentoVersaoId` — setting it to a single version still returned all 2,895
fragments (6.7 MB). There is no per-fragment fetch. So the cost is
**one full snapshot per distinct version date**.

| | Código Civil | Typical diploma |
|---|---|---|
| Fragments | 2,895 | 6 – 100 |
| Snapshot size | 5.7 MB | 20 – 500 KB |
| Version dates | 71 | (to be measured across the catalogue) |
| Requests for full history | 71 | ~2 – 10 |

**N measured.** The timeline endpoint was run across a 617-diploma slice of the
catalogue (11 %, 0 errors) — `scripts/pt_spike_timeline.py` in a loop:

```
distinct effective dates per diploma: mean 5.62 · median 3 · max 71
 1 date  120 │ 2 dates 100 │ 3 dates  89 │ 4 dates  68 │ 5 dates  54
 6 dates  45 │ 7 dates  23 │ 8 dates  20 │ 9 dates  18 │ 10 dates 17
 …  20+ dates 22
amending diplomas per law: mean 6.8, max 102
modifications per law:     mean 49.1, max 1,467
100 % of consolidated diplomas have at least one dated version
```

Most-amended in the sample: Código Civil (71 dates / 102 acts), DL 486/99 (59),
DL 398/98 (52), DL 102/2008 (52), Código das Sociedades Comerciais (49),
Lei 150/99 (49).

Extrapolated to the full 5,528 resolvable diplomas:

| | |
|---|---|
| Header + timeline calls | ~11,000 |
| Point-in-time snapshots | **~31,000** |
| Total requests | **~42,000** |
| Wall clock at 4 workers / 0.6 s (the rate the catalogue dump sustained with 0 errors) | ~2–3 h |
| **Reform commits produced** | **~31,000, against 0 today** |

Bandwidth is dominated by a few dozen large codes; the median diploma is 3 snapshots
of a few hundred KB.

---

## §4 Metadata inventory

### 4.1 What we capture today

`DREMetadataParser.parse` produces: `title`, `short_title`, `identifier`, `country`,
`rank`, `publication_date`, `status`, `department`, `source`, `summary`, `pdf_url`,
and exactly **four** `extra` keys: `summary`, `official_number`, `dr_number`, `eli`.

`subjects` is always empty. `jurisdiction` is always `None`. `last_modified` is never
set. Spain emits ~25 `extra` keys.

### 4.2 What surface B (as-published) exposes

Note first: **the client fetches the wrong text field.** `DREHttpClient.get_text`
prefers `Texto` and falls back to `TextoFormatado`. Measured on Decreto Legislativo
Regional 2/2025/M (Orçamento da Madeira):

| Field | Size | `<table>` | `<img>` | `<a>` | `<p>` |
|---|---|---|---|---|---|
| `Texto` | 244,249 | 101 | 96 | **0** | 222 |
| `TextoFormatado` | 300,147 | 101 | 96 | **472** | **2,898** |

`TextoFormatado` is the richer manifestation — it keeps the cross-reference anchors
and the real paragraph structure. **Prefer it.**

`DataActionGetAllConteudoDetalheData` returns 40 fields:

```
AcordaoSTA · AtosSocietarios · ContratoPublico · DataAssinatura ·
DataDisponibilizacao · DataDistribuicao · DataPublicacao · DiarioRepublica ·
DiplomaExterno · DiplomaLegacor · DiplomaLegis · DiplomaRegTrab · ELI ·
ELIMetadataHTML · Emissor · EmissorAcronimo · Id · IsDiplomaExterno ·
IsDiplomaLegis · LinkSitemap · Notas · Numero · Pagina · PaginaOffset · Parte ·
Processo · Publicacao · Resumo · Serie · Sumario · Suplemento · Texto ·
TextoFormatado · TipoConteudo · TipoDiploma · TipoDiplomaAcronimo ·
TipoDiplomaExterno · Titulo · URL_PDF · Vigencia
```

The current client reads 10 of them. **Dropped today**: `DataAssinatura`,
`DataDistribuicao`, `DataDisponibilizacao`, `Pagina`, `PaginaOffset`, `Suplemento`,
`Serie`, `Resumo`, `Notas`, `Processo`, `TipoDiplomaAcronimo`, `Publicacao`,
`TextoFormatado`, the whole `DiarioRepublica` sub-record (`NumPaginas_PDF`,
`Tamanho_PDF`, `URL_PDF`, `Id`), and **`ELIMetadataHTML`** with everything in §2.4.

### 4.3 What surface A (consolidated) adds

Document level: `CurrentConsolidacaoId` · `LastConsolidacaoId` · `DataUltimaConsolidada`
· `IsVersaoInicial` · `IsMultipleConsolidation` · `HasIndice` · `HasFile` ·
`HasJurisprudenciaAssociada` · `URLPDF` (the original Diário do Governo scan).
Header: `DiplomaFrag{ELI, FormattedTitle, Designacao, Nota, DiplomaConsolidacaoEstadoId,
EmAtualizacao}` · `DiplomaLegis{Numero, Sumario, Resumo, Emissor, EmissorAcronimo,
Vigencia, IsRegional, Consolidado, AnaliseJuridicaPublica, DataPublicacao,
DataAlteracao, DataCriacao, LinkSitemap}` · `Serie{Nome}` · `TipoDiploma{Tipo, Acronimo}`.
Fragment level: everything in §3.3, including three distinct date semantics
(`DataEntradaVigor`, `DataProducaoEfeitos`, `DataSuspensao`) and per-article `Nota`
(Constitutional Court declarations of unconstitutionality) and `AlteracoesList`.

Example `Nota`, from the Código Civil:

> `<a href="/dr/detalhe/acordao/743-1996-413777">Acórdão n.º 743/96 …</a> Declarada
> a inconstitucionalidade, com força obrigatória geral, da norma constante no
> presente artigo…`

That is genuine legal annotation currently thrown away.

### 4.4 The rule

`ADDING_A_COUNTRY.md` §0.3: *if the source provides it, you capture it*. Every field
above goes into `NormMetadata` or `extra` with an English snake_case key, before the
bootstrap — adding one afterwards means regenerating 100k+ commits.

---

## §5 Formatting inventory

### 5.1 The as-published HTML has a small, mappable class vocabulary

Aggregated over four fixtures (`tests/fixtures/pt/aspublished-*.json`: Código Civil
1966 as printed, DLR 2/2025/M Orçamento da Madeira, Lei 55-A/2025, Portaria 416/2025) —
24,036 `<p>`, 204 `<table>`, 96 `<img>`, 484 `<a>`, 42 `<sup>`:

| Selector | Count | Meaning | Target css_class |
|---|---|---|---|
| `p.paragraph-normal-text` | 10,541 | body text | `parrafo` |
| `p.paragraph-bold-center-14px` | 662 | heading line (CAPÍTULO, Artigo, ANEXO…) | level from the text pattern |
| `p.paragraph-bold-center` | 2 | heading line | idem |
| `p.paragraph-italic-right` | 3 | date / place line before signatures | `firma` |
| `p.Tbl4`, `p.Tbl15` | 116 | text inside a table cell | consumed by `render_table` |
| `div.tableContent` | 6 | wrapper around a `<table>` | unwrap |
| `div.imageContent` | 96 | wrapper around an `<img>` | image policy |
| `<style>` | 4 | the `.TblN` rules DRE injects | **strip** |

The classes are presentational, not structural — "bold center" marks both a
`CAPÍTULO` and an `Artigo` — so the heading *level* still comes from the text pattern.
But the class reliably says *"this line is a heading"*, which is more than the current
line-regex approach has.

Two mechanical details: the HTML uses `\r\n` line endings (must be normalised — the
guide forbids CRLF in output), and **no HTML entities at all** appear in the official
payload (unlike the tretas.org text, §1.4).

Images are real, stable CDN URLs:
`<img src="https://files.diariodarepublica.pt/images/923290710/923294162.png"
alt="A imagem não se encontra disponível." />` — 96 in the Madeira budget alone.
Cross-references carry the target's title:
`<a href='/dr/detalhe/lei/45-a-2024-901667918' title='Lei n.º 45-A/2024'>`.

Tables are full HTML with `rowspan`/`colspan`/`<thead>`/`<th>` — `_tables.py::render_table`
handles all of it:

```html
<table class="Tbl1"><thead><tr><th rowspan="2"><p>Rendimento coletável (em euros)</p></th>
<th colspan="2"><p>Taxas (em percentagem)</p></th></tr>…
```

### 5.2 Construct-by-construct

| Construct | Present in source | Handled today | Target |
|---|---|---|---|
| Structural hierarchy (7 levels) | Yes — `TipoFragmentoId` + `Nivel` + `PaiId` (A); text pattern + bold-center class (B) | 3 levels, regex-guessed | Exact from the type id (A); pattern + class (B) |
| Article headings + epígrafe | Yes — `Name` + `Epigrafe` | Partially (breaks on entities) | `###### Artigo N.º — (Epígrafe)` |
| Tables | **204 in 4 as-published fixtures**, with rowspan/colspan/thead; rare in consolidated (1 fragment in 388) | **Broken** (§1.4) | `_tables.py::render_table`, one `Paragraph` |
| Bold / italic | `paragraph-bold-*`, `paragraph-italic-*` classes | Regex, non-nesting | lxml inline extractor |
| `<sup>` / `<sub>` | 42 in the fixtures | Stripped | HTML passthrough (ES pattern) |
| Cross-reference links `<a href>` | **484 in the fixtures**, with `title` | **href discarded** | `[Lei n.º 45-A/2024](https://diariodarepublica.pt/dr/detalhe/…)` |
| Lists `<ol>/<ul>` | Not seen in the fixtures — Portuguese laws number inline (`1 -`, `a)`, `i)`) | `- ` prefix via regex | keep as body text; do not invent list markup |
| Blockquote / quoted amending text | Yes (amending laws quote the new wording) | No | `cita` → `> ` |
| Footnotes / notas | Yes — `Nota` per fragment (A), `Notas` field (B) | **Dropped** | `> <small>…</small>` (`nota_pie`) |
| Amendment notes | Yes — `AlteracoesList` per fragment | **Dropped** | decide: `extra` vs rendered note |
| Anexos | Yes — `TipoFragmentoId` 14 | **No pattern** | `anexo_num` → `##` |
| Signatories | Yes — `TipoFragmentoId` 7, `paragraph-italic-right` | **No pattern** | `firma` → `**bold**` |
| Images | **96 in one law**, stable CDN URLs | Dropped, not counted | ES §11 policy: `![](url)` + `extra.images_linked` — **note this contradicts `engine/CLAUDE.md`** ("images are explicitly skipped"), which Spain already overrode in `RESEARCH-ES-v2.md §11`. Needs the same explicit decision for PT, or the rule promoted engine-wide |
| Formulas | Not seen; likely rendered as images | — | covered by the image policy |
| `<style>` blocks | 4 in the fixtures | Passed through by the regex stripper | **strip** |
| Line endings | `\r\n` in the source HTML | Not normalised | normalise to `\n` |
| Encoding | UTF-8, **zero entities** in the official payload | `errors="replace"`, no control scrub, 10-entity table | `fetcher/_text.py::clean()` |

---

## §6 Identifiers and jurisdictions

### 6.1 Identifier — move to ELI

Today: `DRE-{TYPECODE}-{number}`, with the two-digit/four-digit year inconsistency of
§1.7 and a hand-maintained `TYPE_CODE_MAP` of 19 entries against DRE's 33+ ELI types.

**Decided (D2, §12): derive from the official ELI**, which DRE already publishes for
98.3 % of the consolidated catalogue and for every as-published diploma.

```
https://data.dre.pt/eli/dec-lei/47344/1966/…  →  DRE-DEC-LEI-47344-1966
https://data.dre.pt/eli/lei/82-d/2014/…       →  DRE-LEI-82-D-2014
https://data.dre.pt/eli/port/324/2015/…       →  DRE-PORT-324-2015
https://data.dre.pt/eli/declegreg/54/2006/…   →  DRE-DECLEGREG-54-2006
```

Properties: official, stable, always four-digit year, one token per ELI type (no
hand-maintained map), filesystem-safe, and reversible to the ELI permalink. Diplomas
without an ELI (95 of 5,561 in the consolidated set) fall back to
`DRE-{tipo-slug}-{numero}-{ano}` using the sitemap's own `tipo` slug.

The filename is permanent (memory: `feedback_format`), so this was settled before any
code was written — see §12 D2. Consequence to plan for: every existing deep link to
`/pt/DRE-DL-…` breaks, so the cutover must ship an old-id → new-id redirect map.

### 6.2 Jurisdictions

Portugal has two autonomous regions with their own legislative assemblies. ISO 3166-2
codes, which is what ELI subdivision codes use:

| Region | Code | Output dir | ELI segment | Other evidence |
|---|---|---|---|---|
| Açores | `pt-20` | `pt-20/` | `…/a/dre/…` | `Emissor` "Região Autónoma dos Açores - Assembleia Legislativa" (136 diplomas), `EmissorAcronimo` `RAA-AL`, number suffix `/A` |
| Madeira | `pt-30` | `pt-30/` | `…/m/dre/…` | `Emissor` "Região Autónoma da Madeira - Assembleia Legislativa", `EmissorAcronimo` `RAM-AL`, number suffix `/M` |
| Portugal (national) | — | `pt/` | `…/p/dre/…`, `…/p/cons/…` | |

**Read it from the ELI path.** Verified on Decreto Legislativo Regional 2/2025/M:
`https://data.dre.pt/eli/declegreg/2/2025/07/02/m/dre/pt/html` — the `m` segment is
the ELI jurisdiction code. `DiplomaLegis.IsRegional` is unreliable (only 129 of 5,528
catalogue rows have it `true`, while the regional ELI types alone account for 452
diplomas), so the flag is a fallback at best.

---

## §7 Target architecture

### 7.1 The version-history hook

The pipeline already has the hook Portugal needs. `pipeline.generic_fetch_one`:

```python
if hasattr(text_parser, "parse_suvestine") and hasattr(client, "get_suvestine"):
    sv_blocks, sv_reforms = text_parser.parse_suvestine(client.get_suvestine(norm_id), norm_id)
    if sv_reforms:
        blocks, reforms = sv_blocks, sv_reforms
```

Belgium (`fetcher/be/`) is the reference implementation: `get_suvestine` returns a JSON
blob holding the whole timeline (`{versions: [{version_num, effective_date,
amending_law_pub_date, affected_articles, text_b64}], …}`), and `parse_suvestine` runs
the single-version parser per snapshot, merges blocks by id, and diffs consecutive
snapshots to decide which articles actually changed.

Portugal maps onto it cleanly:

1. `timeline()` → the ordered list of distinct `DataEntradaVigor` values + the amending
   diploma for each.
2. One `DataActionGetData` per date → one snapshot.
3. Merge fragments by `ConsolidacaoFragmento.Id` → one `Block` per article, one
   `Version` per snapshot.
4. `Version.publication_date` = the **effective** date. This is not a preference, it is
   forced: `storage.py::save_structured_json` writes only `"date": version.publication_date`,
   so **`Version.effective_date` never reaches the JSON cache at all** and a reprocess
   cannot recover it. `get_block_at_date` and `extract_reforms` read `publication_date`
   exclusively. Put `DataEntradaVigor` in `publication_date` or lose it.
5. `Version.norm_id` / `Reform.norm_id` = a stable unique key per reform, e.g.
   `{diploma_frag_id}@{yyyy-mm-dd}:{amending_diploma_legis_id}` — it becomes the
   `Source-Id` dedupe key and must not contain timestamps or randomness.
6. `reforms[0]` must be the earliest — index 0 becomes the `[bootstrap]` commit.

### 7.2 Constraints the parser must respect

- **Never emit a `Paragraph` whose text contains a blank line.** `storage.py` joins
  paragraphs with `"\n\n"` and splits on it; a `\n\n` inside one paragraph desyncs the
  parallel `css_classes` list. Single `\n` (pipe tables) is fine.
- **Diff versions yourself.** The bootstrap path `commit_all_fast` streams every
  `Reform` to `git fast-import` **without** checking whether the rendered file changed.
  Emitting a reform per amendment date without diffing produces empty commits.
- Reuse `fetcher/_tables.py::render_table` and `fetcher/_text.py::{decode_utf8,
  scrub_control, clean}` — do not re-implement.
- Parse HTML with a forced-UTF-8 `lxml.html.HTMLParser(encoding="utf-8")`; lxml's
  autodetection falls back to Latin-1 on large pages (memory: `feedback_engine_gotchas`).

### 7.3 Hybrid coverage

| Set | Size | Source | History |
|---|---|---|---|
| Consolidated diplomas | 5,561 | Surface A | Full, one commit per amendment |
| Everything else currently in the repo | ~104,000 | Surface B, **re-fetched from the official DRE** (D1) using `TextoFormatado` | Single `[bootstrap]` commit — the diploma as published never changes |
| Categories missing today (§1.6) | ~500 consolidated + their as-published siblings | A + B | — |

An as-published diploma genuinely has one version: it is the printed text. The
single-snapshot rule is correct there. The failure today is that it is *also* applied
to the 5,561 diplomas that DRE consolidates.

---

## §8 The iterative fidelity loop

Copy the Spain machinery — `scripts/es_fidelity/{sample,score,report}.py` — as
`scripts/pt_fidelity/`. Spain's progression was mean `text_ratio` 0.8704 → 0.9824 and
clean laws 0/20 → 30/67 over 8 iterations; that is the bar.

- **Strata**: ELI type × decade (1920s–2020s) × jurisdiction (pt, pt-20, pt-30) ×
  tags (`has_tables`, `has_notas`, `has_alteracoes`, `has_anexos`, `has_links`,
  `has_sup`, `is_multi_version`).
- **Reference text**: the rendered consolidated page on `diariodarepublica.pt` for
  surface A, the as-published detail `Texto` for surface B.
- **Axes**: TEXT (`difflib` ratio on normalised words) · HEADINGS (count per level vs
  `TipoFragmentoId` histogram — Portugal can score this *exactly*, Spain could not) ·
  TABLES · NOTAS · LINKS · METADATA (hard gate) · VERSIONS (number of commits per law
  equals the number of distinct `DataEntradaVigor`).
- **Exit criteria**: mirror ES §5.5, plus a PT-specific one — for a stratified sample
  of multi-version laws, `git log -- pt/{id}.md` must list exactly the timeline's
  distinct effective dates, in order.

---

## §9 Migration / reprocess strategy

The repo is 109,929 files / 109,932 commits / 3 GB, and every commit's *body* changes.
Per `REPROCESSING.md` this is the "wipe and rebuild" case, not `filter-branch`.

1. Full re-fetch into `countries/data-pt/json/` from the official DRE (both surfaces).
   The tretas.org SQLite dump is retired; nothing depends on it afterwards.
2. Rebuild the repo from scratch in a scratch clone; keep the old history on a
   `pre-v2` tag for reference.
3. Integrity check, per file: the set of `Norm-Id`s must be a superset of the old set
   (we add laws, we lose none), and every law present before must still be present.
4. `legalize health -c pt` must report zero issues.
5. Force-push to a `rebuild/pt-v2` branch first, PR against `main`, cutover with
   explicit approval.
6. `law-sync full --repo ../countries/pt` afterwards — every `reforms.sha` in the DB
   is invalidated by the rewrite.

Anyone with a local clone sees history rewritten. Acceptable and already warned about
in the README.

---

## §10 Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| OutSystems redeploy renames the consolidated actions mid-bootstrap | **High** — it happened twice already (`docs/pt-dre-api.md`) | Resolve action names by prefix from the screen JS at session start; fail loud with `DREApiError`, never degrade to empty |
| 50k snapshot requests get rate-limited or IP-blocked | Med | Catalogue dump ran 5,561×2 calls at 4 workers / 0.6 s with 0 errors; start there, back off on 429/503, resumable checkpointing |
| Big codes (5.7 MB × 71 versions) blow memory or disk | Med | Stream per-snapshot to the JSON cache, never hold all versions in memory |
| Older consolidations lost their tables in the source | **Confirmed** | Document it; record `extra` flag; consider as-published/PDF enrichment later (§12) |
| Reprocess loses laws that only the tretas dump had | Med | Diff the old filename set against the new one **before** cutover; anything only in the old set is investigated individually |
| Daily breaks while the rebuild runs | Low | Rebuild happens on `feat/pt-v2`; `main` keeps the current daily |
| The two enrichment bugs (§1.2) stay unfixed and PT still shows no history on the site | **High if forgotten** | Separate small PR on `legalize-web`/`enrichment`: add `[new`/`[repeal`/`[correction` to the accept-list and `^#{1,6}\s+Artigo` to `_ARTICLE_PATTERNS` |

---

## §11 Out of scope

- Binary assets in the repo (images stay links or counts).
- OCR of the `URLPDF` scans of pre-1970 diplomas.
- Séries II–V of the Diário da República (the repo is Série I only, correctly).
- Jurisprudence (`acordao-*`) beyond the handful DRE consolidates.
- `dados.gov.pt` / PGDL / N-Lex as alternative sources — investigated only far enough
  to confirm DRE is the authoritative machine-readable one.

---

## §12 Decisions and remaining questions

### Settled (user, 2026-08-21)

**D1 — Full re-fetch.** Every diploma is re-downloaded from the official DRE; the
tretas.org dump is retired entirely. That means ~110,000 as-published fetches
(preferring `TextoFormatado`) **plus** the ~42,000 consolidated calls of §3.5 —
roughly 150,000 requests, ~15–18 h at the rate already sustained without errors.
Rationale: any smaller scope leaves the `TEXTO :` artefact and the duplicated titles
in ~104,000 files, and leaves their tables, links and images unrecoverable, since the
tretas text simply does not contain them.

**D2 — ELI-based identifiers.** `DRE-{ELI_TYPE}-{NUMBER}-{YEAR}`:

```
dec-lei/47344/1966   →  DRE-DEC-LEI-47344-1966
lei/82-d/2014        →  DRE-LEI-82-D-2014
port/324/2015        →  DRE-PORT-324-2015
declegreg/54/2006    →  DRE-DECLEGREG-54-2006   (in pt-20/ or pt-30/)
```

Official, four-digit year always, one token per ELI type (33 of them, no hand-kept
map), reversible to the `data.dre.pt` permalink. Diplomas with no ELI (95 of 5,561 in
the consolidated set) fall back to the sitemap's own `tipo` slug:
`DRE-{TIPO-SLUG}-{NUMERO}-{ANO}`. Every filename in the repo changes — which is fine,
because D1 rebuilds the repository anyway, but the web app's existing deep links to
`/pt/DRE-DL-…` will 404 and need a redirect map generated at cutover.

### Still open

1. **Tables lost in older consolidations** (§3.4): DRE itself flattened them into text
   with dot leaders in pre-~2015 consolidations. Render as-is, or enrich from the
   as-published HTML where a `<table>` exists for the same article? Enrichment risks
   mixing two texts in one file. Default for now: render as-is and flag it in `extra`.
2. **`AlteracoesList` and `Nota`** (§4.3): render into the Markdown (as Spain does with
   `nota_pie` → `> <small>…</small>`), or keep in `extra` only? The `Nota` entries are
   real legal annotation (Constitutional Court rulings) and argue for rendering.
3. **Descriptor labels** (§2.4): `eli:is_about` yields numeric subject IDs that do not
   dereference. The DRE search screen exposes a `DescritorList` — needs a spike. Without
   a lookup, `subjects` would hold opaque IDs, which is worse than leaving it empty.
4. **Redirect map** for the identifier change (D2) — generated from old id → new id at
   cutover, applied in `legalize-web`.

---

## §12b The title problem — Portuguese laws have no title

A Portuguese diploma is cited by a number: *Decreto-Lei n.º 47344*. There is no
descriptive title in the citation the way there is in Spain (*Ley Orgánica 10/1995,
del Código Penal*). The descriptive text lives in two other fields, both of which we
currently ignore.

### 12b.1 What the source gives us

| Field | Coverage | Length (chars) | What it is |
|---|---|---|---|
| `DiplomaLegis.Sumario` | **99.1 %** (5,478 / 5,528) | mean 152, median 136 | the official summary sentence |
| `DiplomaFrag.Designacao` | **99.1 %** (5,480 / 5,528) | mean 122, median 103, max 497 | the diploma's designation — sometimes the popular name, usually a descriptive sentence |
| `DiplomaFrag.Nota` | 164 diplomas | up to ~500 | document-level legal note ("Revogado, a partir de 05.08.2022, com efeitos…") |

They are related but not the same. For the Código Civil:

```
Numero:      47344
Designacao:  "Código Civil - CC"
Sumario:     "Aprova o Código Civil e regula a sua aplicação — Revoga, a partir da
              data da entrada em vigor do novo Código Civil, toda a legislação civil
              relativa às matérias que o mesmo abrange"
```

`Designacao` is *usually* a sentence, not a short name — "Aprova o regime jurídico da
transmissão e execução de sentenças em matéria penal…" (400 chars) — but when DRE has a
popular name, that is where it lives.

(Measured length caps: the catalogue dump truncated `Sumario` at 300 chars, so the true
maximum is unknown; `Designacao` was stored whole.)

### 12b.2 Why this is worse than it looks: Portuguese law is unsearchable today

`laws.search_vector` in the web database is built from exactly two columns:

```sql
setweight(to_tsvector('simple', immutable_unaccent(coalesce(title, ''))),       'A') ||
setweight(to_tsvector('simple', immutable_unaccent(coalesce(short_title, ''))), 'B')
```

For Portugal, `title` is `"Decreto-Lei n.º 47344"` and `short_title` is **NULL for every
law** (the core renderer never emits `short_title`; the countries that have it — at, ch,
ee, lu — add it as an `extra` key, and PT does not). `extra` is **not** in the search
vector.

So the entire Portuguese corpus is searchable **only by its number**. Nobody can find
the Código Civil by typing "código civil", or the child-marriage reform by typing
"casamento de menores". This is not a rendering nicety — it is the reason Portugal is
effectively invisible on the site's search.

Compare the house style, from the site's own API docs:

```json
{ "title": "Ley Orgánica 10/1995, del Código Penal", "short_title": "Código Penal" }
```

### 12b.3 The mapping

| Target | Source | Note |
|---|---|---|
| `title` | `"{Tipo} n.º {Numero} — {Designacao}"`, `Designacao` cut at a word boundary at ~120 chars | matches the ES house style; searchable at **weight A**; keeps the citation as the leading token |
| `short_title` | `Designacao` cut at a word boundary at ~80 chars | searchable at **weight B**, and it is what `committer/message.py` puts in the commit subject — so it must stay short (today PT feeds it `summary[:120]`, which is why subjects average 145.8 chars and truncate mid-word) |
| `summary` (frontmatter) | full `Sumario` | capped at 500 per the guide |
| `extra.designation` | full `Designacao` | only when it differs from `short_title` after truncation |
| `extra.note` | `DiplomaFrag.Nota` | 164 diplomas; real legal notes, dropped today |
| **body** | `Sumario`, rendered right under the H1 | see below |

### 12b.4 Rendering the summary in the body

The reader of the `.md` on GitHub sees only `# Decreto-Lei n.º 47344` and then legal
text. The summary belongs on the page.

**Do it in the PT parser, not in the engine.** `render_norm_at_date` emits
frontmatter + `# {title}` + blocks, and `NormMetadata.summary` is never rendered for
any country. Adding a summary line to the generic renderer is a cross-country output
change and `CLAUDE.md` says that requires regenerating every country repo. Instead the
PT text parser emits the summary as the **first `Block`**, with a single `Version` dated
at the diploma's publication date so it survives every point-in-time render:

```python
Block(
    id="sumario",
    block_type="sumario",
    title="Sumário",
    versions=(Version(
        norm_id=..., publication_date=pub_date, effective_date=pub_date,
        paragraphs=(Paragraph(css_class="cita", text=sumario),),
    ),),
)
```

`cita` is already in `_SIMPLE_CSS_MAP` and renders as `> {text}`, so no renderer change
is needed. Result:

```markdown
# Decreto-Lei n.º 47344 — Código Civil - CC

> Aprova o Código Civil e regula a sua aplicação — Revoga, a partir da data da entrada
> em vigor do novo Código Civil, toda a legislação civil relativa às matérias que o
> mesmo abrange

##### Artigo 1.º — (Aprovação do Código Civil)
…
```

Because the summary is a Block with one early version, it is identical in every commit
and therefore adds no noise to any reform diff.

**Open sub-decision:** whether `title` carries the descriptive part (ES house style, and
what makes weight-A search work) or stays the bare citation with the descriptive text
only in `short_title`. Recommendation: carry it, because weight A is where search
actually bites. Either way this is a permanent choice — it is the H1, the DB `title`,
and it cannot be changed after the bootstrap without regenerating everything.

---

## §13 Before / after

### 13.1 The corpus

| | Before (today) | After |
|---|---|---|
| Source | `dre.tretas.org` SQLite mirror | `diariodarepublica.pt` + `data.dre.pt` (official) |
| Laws | 109,929 | ~110,000 + the ~500 consolidated diplomas missing today (RCM, Lei Orgânica, Decreto do PR, Despacho Normativo, Acórdãos com força obrigatória geral, Declarações de Retificação) |
| Commits | 109,932, of which **0 are reforms** | ~110,000 bootstrap + **~31,000 reform commits** |
| Laws with version history | **0** | **5,528** (every consolidated diploma), mean 5.6 versions, max 71 |
| Commit dates | 99.3 % are `1970-01-02` (epoch clamp) | the date each version entered into force (`DataEntradaVigor`) |
| `Source-Id` | `PLACEHOLDER` in 99.3 % of commits | the amending diploma's id |
| Commit language | Spanish, in a Portuguese repo | Portuguese |
| Trailers | two incompatible schemas coexisting | one |
| Author | a personal Gmail address on 109,347 commits | the Legalize bot |
| Rows in the web `reforms` table | **0** | ~31,000 |
| `article_count` in the DB | 0 for every law | real (needs the one-line `Artigo` pattern fix) |

### 13.2 One file

`pt/DRE-DL-47344.md` — the **Código Civil**. What legalize.dev serves today:

```yaml
---
title: "Decreto-Lei n.º 47344"          # the words "Código Civil" appear nowhere
identifier: "DRE-DL-47344"
country: "pt"
rank: "decreto-lei"
publication_date: "1966-11-25"
last_updated: "1900-01-01"              # placeholder
status: "in_force"
source: "https://dre.pt/application/file/477502"
department: "Ministério da Justiça - Gabinete do Ministro"
official_number: "47344"
dr_number: "274/1966"
---
# Decreto-Lei n.º 47344

TEXTO :                                  # scraper label

Decreto-Lei n.º 47344                    # title, again
…
##### ARTIGO 1601.º
São impedimentos dirimentes, obstando ao casamento da pessoa a quem respeitam
com qualquer outra:

a) A idade inferior a dezasseis ou a catorze anos, conforme se trate de
   indivíduo do sexo masculino ou do sexo feminino;
```

`git log` on that file: **one commit, dated 1970-01-02, `Source-Id: PLACEHOLDER`.**

That article text is the **1966 original**. It was amended in 1977 (sixteen for
everyone), and again by **Lei n.º 39/2025**, which raised it to 18 precisely in order to
ban child marriage. We publish the 1966 wording, marked `status: in_force`, with a
`last_updated` of 1900. A Portuguese lawyer reading legalize.dev today is reading a text
that stopped being the law 48 years ago.

After the rebuild, the same file:

```yaml
---
title: "Decreto-Lei n.º 47344"
short_title: "Código Civil - CC"          # DiplomaFrag.Designacao, available and unused today
identifier: "DRE-DEC-LEI-47344-1966"      # ELI-derived (D2)
country: "pt"
jurisdiction: null                        # from the ELI /p/ segment
rank: "decreto-lei"
publication_date: "1966-11-25"
last_updated: "2026-06-23"                # DataUltimaConsolidada
status: "in_force"
source: "https://data.dre.pt/eli/dec-lei/47344/1966/p/cons/20260623/pt/html"
pdf_url: "https://files.diariodarepublica.pt/1s/1966/11/27400/18832086.pdf"
department: "Ministério da Justiça - Gabinete do Ministro"
summary: "Aprova o Código Civil e regula a sua aplicação — Revoga, a partir da
  data da entrada em vigor do novo Código Civil, toda a legislação civil relativa
  às matérias que o mesmo abrange"
subjects: [...]                           # eli:is_about
eli: "https://data.dre.pt/eli/dec-lei/47344/1966/p/cons/20260623/pt/html"
diario_republica: "Diário do Governo n.º 274/1966, Série I de 1966-11-25"
consolidation_id: "1138226675"
consolidated_at: "2026-06-23"
amending_acts: 102
…
---
# Decreto-Lei n.º 47344 — Código Civil

##### Artigo 1601.º — (Impedimentos dirimentes absolutos)

São impedimentos dirimentes, obstando ao casamento da pessoa a quem respeitam
com qualquer outra:

a) A idade inferior a 18 anos;
…
```

and `git log -- pt/DRE-DEC-LEI-47344-1966.md`:

```
2026-07-01  [reform] Código Civil - CC — art. 1425.º        Source-Id: …lei/29-2026
2025-04-02  [reform] Código Civil - CC — art. 1601.º, …     Source-Id: …lei/39-2025
2024-07-25  [reform] Código Civil - CC — …                  Source-Id: …dec-lei/48-2024
…
1978-04-01  [reform] Código Civil - CC — art. 1601.º, …
1967-06-01  [bootstrap] Código Civil - CC — original version 1966
```

**71 commits instead of 1**, each dated when it took effect, each naming the law that
caused it. `git show` on the 2025-04-02 commit is a diff from "dezasseis anos" to
"18 anos" — which is exactly the product legalize claims to sell.

### 13.3 What does not change

- The output contract: flat `{jurisdiction}/{identifier}.md`, the frontmatter key names,
  the `[bootstrap]`/`[reform]` subject prefixes, the `Source-Id`/`Source-Date`/`Norm-Id`
  trailer names.
- The daily flow keeps running on `main` while the rebuild happens on `feat/pt-v2`.

### 13.4 What breaks, and must be planned

- **Every filename changes** (D2). The web app needs an old-id → new-id redirect map
  generated at cutover, or ~110,000 deep links start 404-ing.
- **The whole git history is rewritten.** Anyone with a local clone loses their copy's
  ancestry. The README already warns about per-law rewrites.
- **Every `reforms.sha` in the DB is invalidated** → a `law-sync full` is required after
  cutover, not an incremental sync.
- Bootstrap is a ~15–18 h run (~150,000 requests), so it needs checkpointing and a plan
  for a DRE redeploy landing mid-run.

---

## Artefacts produced by this research

| Path | What |
|---|---|
| `scripts/pt_spike_consolidada.py` | Working point-in-time consolidated fetch, pure Python |
| `scripts/pt_spike_timeline.py` | Working amendment-timeline fetch |
| `tests/fixtures/pt/version-spike.txt` | §0.5 gate evidence |
| `tests/fixtures/pt/version-spike.json` | Machine-readable spike output |
| `tests/fixtures/pt/timeline-codigo-civil.json` | 102 amending diplomas, 71 dates |
| `countries/data-pt/legislacao-consolidada-sitemap.xml` | The 5,561-URL catalogue index |
| `countries/data-pt/consolidated-catalogue.jsonl.gz` | 5,561 diplomas with ELI, title, emissor, dates |
