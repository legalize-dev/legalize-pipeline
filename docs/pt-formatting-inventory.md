# Portugal — rich-formatting inventory (Step 0.4)

Companion to `RESEARCH-PT-v2.md`. Everything here was measured on 2026-08-21 against
the live DRE, at ≤ 2 req/s with
`User-Agent: legalize-bot/1.0 (+https://github.com/legalize-dev/legalize-pipeline)`.

**Corpora measured**

| Set | Size | What |
|---|---|---|
| **A** — consolidated (`dr.LegislacaoConsolidada`) | **222 diplomas / 20,843 fragments** | stratified over **all 42 consolidated-URL tipos** present in the 5,561-URL catalogue (every one is represented), every decade 1920s–2020s, biased to big codes and pre-1976 diplomas |
| **B** — as-published (`dr.Legislacao_Conteudos.Conteudo_Detalhe`) | **128 diplomas / 16.9 M chars of `TextoFormatado`** | the same laws through their `LinkSitemap`, plus CIRS/CIRC/CIVA which surface A does not carry |
| **C** — `(ver documento original)` probe | **73 affected diplomas** (71 resolved) + **42 consolidated twins** + 21 PDFs | drawn from the 27,954 affected files in the live `legalize-pt` |

Machine-readable backing data: `tests/fixtures/pt/formatting-inventory.json`
(the full id map, both per-document censuses, and the whole §3 probe).
New fixtures listed in §5.

---

## §1 The complete `TipoFragmentoId` map

`RESEARCH-PT-v2 §3.3` had 12 ids from one diploma and left 2, 4, 10 unknown.
Across 20,843 fragments the taxonomy is **exactly 1–15, contiguous, no gaps, nothing
above 15**. The three unknowns are **2 = Base**, **4 = Parte**, **10 = Tabela**.

| id | Name | Fragments | Docs | `OmitTipo=true` | Observed `Nivel` | Target heading | css_class |
|---:|---|---:|---:|---:|---|---|---|
| 4 | **Parte** | 86 | 21 | 52 | 1–4 | `#` | `parte_num` |
| 12 | **Livro** | 27 | 5 | 0 | 2, 4 | `#` | `libro_num` |
| 13 | **Título** | 296 | 29 | 2 | 1–6 | `##` | `titulo_tit` |
| 5 | **Subtítulo** | 8 | 2 | 0 | 4 | `##` ⚠ collapses with Título | `titulo_tit` |
| 14 | **Anexo** | 259 | 89 | 63 | 1–3 | `##` | `anexo_num` |
| 1 | **Capítulo** | 1,248 | 78 | 53 | 1–6 | `###` | `capitulo_tit` |
| 8 | **Secção** | 1,185 | 60 | 7 | 1–7 | `####` | `seccion_tit` |
| 3 | **Subsecção** | 399 | 22 | 0 | 3–7 | `#####` | `subseccion_tit` |
| 9 | **Divisão** | 124 | 9 | 1 | 1, 4–8 | `#####` ⚠ collapses | `subseccion_tit` |
| 6 | **Subdivisão** | 17 | 4 | 0 | 5, 6, 8 | `#####` ⚠ collapses | `subseccion_tit` |
| 10 | **Tabela** | 3 | 1 | 3 | 4 | `#####` ⚠ no dedicated class | `subseccion_tit` + `table` |
| 11 | **Artigo** | 16,773 | 162 | 108 | 1–9 | `######` | `articulo` |
| 2 | **Base** | 7 | 2 | 0 | 1, 2 | `######` (article-equivalent) | `articulo` |
| 7 | **Assinatura** | 200 | 192 | 0 | 1, 2 | `**bold**` | `firma` |
| 15 | **Diploma** | 211 | 211 | 0 | 0 | — (preamble body) | `parrafo` |

**Does any id's name vary?** The *type* never varies — one id, one Portuguese type
word, 20,843/20,843 fragments. What varies is whether the type word is **printed**:

- `FragmentoVersao.OmitTipo = true` (289 fragments, 1.4 %) means the diploma numbers
  that level without naming it. Then `Tituo == Identificacao` and you get bare labels:
  `I`, `II`, `A)`, `B)`, `I)`, `Tabela n.º 1`, or a free-form rubric
  (`Regulamento Geral das Estradas e Caminhos Municipais` as a `Título`, DR 2110/1961).
- id 15 renders as `Diploma` (208) or `Ato` (3) — cosmetic, both are the document root.
- id 14 with `OmitTipo` gives `Tabela I`, `Tabela II`, `ANEXO` (uppercase).

**Parser rule.** Take the heading text verbatim from `FragmentoVersao.Tituo` — it
already contains the type word plus `Identificacao` when `OmitTipo` is false, and only
the label when it is true. Take the heading *level* from `TipoFragmentoId`.
**Do not derive the level from `Nivel`**: as the table shows, `Nivel` is tree depth and
ranges 1–9 for `Artigo` alone. Append `FragmentoVersao.Epigrafe` when present
(17,399 fragments in 135/222 docs carry one).

**Coverage caveat.** 11 of the 222 diplomas (5.0 %) returned a snapshot with **zero
fragments** — mostly `acordao-*` and other tipos DRE lists in the consolidated sitemap
but does not fragment. The fetcher must treat "0 fragments" as a fall-back-to-surface-B
condition, not as an empty law.

---

## §2 Formatting census

### 2.0 Plain text vs HTML, and how it tracks the consolidation date

**Surface A is overwhelmingly plain text.** Of 17,570 fragments with any text,
**173 (1.0 %) contain a single HTML tag**; 34 of 222 documents have at least one.
The split is a pure function of *when the fragment version was written*:

| `FragmentoVersao.DataVersao` year | fragments | with HTML | % |
|---|---:|---:|---:|
| 1926–2002 | 7,262 | 1 | 0.01 % |
| 2003–2014 | 3,776 | 24 | 0.6 % |
| 2015–2022 | 4,417 | 5 | 0.1 % |
| 2023 | 1,537 | 7 | 0.5 % |
| 2024 | 182 | 4 | 2.2 % |
| **2025** | 666 | 54 | **8.1 %** |
| **2026** | 161 | 78 | **48.4 %** |

By document, using `DataUltimaConsolidada`: 0 % of documents last consolidated before
2001 have any HTML, ~25 % of 2023–2024, **55 % of 2025 and 47 % of 2026**. This is
firmer than `RESEARCH-PT-v2 §3.4`'s 12-diploma read and says the same thing louder:
**DRE is migrating the consolidated corpus to rich HTML right now**, so the parser must
handle both shapes and the HTML share will keep growing.

**Surface B is always HTML.** `TextoFormatado` is 100 % markup, and it is the richer
manifestation, confirmed over the 128-document census:

| | `Texto` | `TextoFormatado` |
|---|---:|---:|
| total chars | 13,633,484 | **16,867,991** |
| `<p>` | 589 | **100,143** |
| `<a>` | **0** | **2,864** |
| `<table>` | 129 | 129 |
| `<img>` | 109 | 109 |
| `<style>` | 0 | 5 |

`TextoFormatado` adds every paragraph boundary and every cross-reference. 111 of 128
documents have links in `TextoFormatado` and none in `Texto`. (3 documents have a
`TextoFormatado` *shorter* than `Texto` — check for empty before preferring it.)

### 2.1 Tables

| | Surface A (222 docs) | Surface B (128 docs) |
|---|---:|---:|
| `<table>` elements | 168 | 129 |
| …of which **layout-only** (`table.imageWrapper`, one cell, wraps an `<img>`) | 113 | **109** |
| **real data tables** | **55** | **20** |
| documents with ≥ 1 real table | 17 (7.7 %) | **8 (6.3 %)** |
| `<tr>` | 775 | 418 |
| cells with `rowspan` | — | 17 (3 docs) |
| cells with `colspan` | — | 7 (3 docs) |
| **nested tables** | 0 | **0** |
| `<thead>` / `<th>` | 36 / 239 | 15 / 100 |

**Correction to `RESEARCH-PT-v2 §5.1`.** It reports "204 `<table>` in 4 fixtures".
Re-counted on the same four files: **102 tables, of which 96 are `table.imageWrapper`
layout wrappers around an `<img>`; only 6 are real data tables**
(`aspublished-codigo-civil-1966` 0, `aspublished-dlr-2-2025-madeira` 101/96 layout,
`aspublished-lei-55-a-2025` 1, `aspublished-portaria-416-2025` 0). The parser must
therefore detect the wrapper (one row, one cell, contains only an `<img>`) and route it
to the *image* path, not to `render_table`.

**Real tables are a recent phenomenon.** Every real data table in the surface-B census
is either from 1926 (one, DL 12704) or from **2023 onward** (19 in 7 documents). Across
1930–2022 — 96 documents, including the Código Civil, the CPC, the Código do Trabalho,
the CCP, the CSC, the CIMI and the CPP — there is **not one `<table>` element**.
Where those laws had a printed table, DRE emits `(ver documento original)` (§3).

Layout to expect, verbatim from `aspublished-table-rowspan-lei-organica-2-2023.json`:

```html
<style>.Tbl1 { text-align:center; border-bottom-color:transparent; … }</style>
<div class="tableContent" id="DR_TABLE1">
  <table class="Tbl1">
    <thead><tr class="Tbl2"><th rowspan="2" class="Tbl3"><p class="Tbl4">Escalão</p></th>
    <th colspan="2" class="Tbl3"><p class="Tbl4">Taxas</p></th></tr>…
```

`fetcher/_tables.py::render_table` already handles `<thead>`, `rowspan`, `colspan` and
uppercase tags. It needs no change; the current PT `_html_table_to_markdown` must go.

### 2.2 Bold, italic, underline

**There are none as inline markup.** Across 350 diplomas / 30.8 M characters on both
surfaces:

| marker | surface A | surface B `TextoFormatado` |
|---|---:|---:|
| `<b>` / `<strong>` | **0** | **0** |
| `<i>` / `<em>` | **0** | **0** |
| `<u>` | **0** | **0** |
| `style="font-weight:bold"` | 0 | 0 |
| `style="font-style:italic"` | 21 (1 doc) | 4 (1 doc) |
| `text-decoration:underline` | **0** | **0** |

Emphasis is **paragraph-level, expressed by CSS class, on surface B only**. Surface A
carries no emphasis information at all. Consequence: the inline extractor pattern of
`fetcher/lv/parser.py::_inline_text` is **not needed for Portugal** for bold/italic —
only for `<a>` and `<sup>`, which do appear inline.

### 2.3 The full `p.paragraph-*` class vocabulary (surface B)

Nine class names, plus per-document generated `TblN` classes. Semantics measured by
matching the text of every classed `<p>` in all 128 documents:

| Class | Occurrences | Docs | What it actually marks | Parser action |
|---|---:|---:|---|---|
| `p.paragraph-normal-text` | 75,311 | 128 | body text; also **280 of the 299 signature lines** and 2,889 stray `Artigo N.º` headings | `parrafo`; text-pattern promotion for signatures |
| `p.paragraph-center` | **12,293** | 89 | **the structural heading line**: `Artigo N.º` 9,196 · `CAPÍTULO` 1,015 · `SECÇÃO` 1,009 · `SUBSECÇÃO` 370 · `TÍTULO` 220 · `ANEXO` 162 · `PARTE` 35 | heading; level from the text pattern |
| `p.paragraph-bold-center-14px` | 11,607 | 84 | **the epígrafe** (article rubric): 99.7 % free text — `Objeto`, `Mandato dos Deputados` | merge into the preceding heading |
| `p.paragraph-title-bold-center-18px` | 125 | 125 | exactly one per document — the diploma title | **drop** (the renderer already emits `# {metadata.title}`) |
| `p.paragraph-bold-center` | 88 | 81 | the `de 17 de Março` date line (51) and the sumário line | `parrafo` |
| `p.paragraph-italic-right` | 41 | 41 | **always the last `<p>`, always a bare integer** — DRE's internal content id (`114808797`) | **drop** |
| `p.Tbl*`, `td/th/tr.Tbl*` | 957 (36 distinct) | — | table-scoped presentation, generated per document | consumed by `render_table` |
| `div.tableContent` | 19 | 7 | wrapper around a real `<table>` | unwrap |
| `div.imageContent` + `table.imageWrapper` | 109 + 109 | 4 | wrapper around an `<img>` | image policy (§2.9) |
| *(no class)* | — | — | signature lines and loose table-cell text | `parrafo` |

**Two corrections to `RESEARCH-PT-v2 §5.1`:**

1. It attributes headings to `p.paragraph-bold-center-14px` and never mentions
   `p.paragraph-center`. It is the other way round: `paragraph-center` is the heading,
   `paragraph-bold-center-14px` is the epígrafe. **8,573 of the 9,196 `Artigo N.º`
   headings (93.2 %) are immediately followed by a `paragraph-bold-center-14px`
   epígrafe**; the remaining 623 go straight to body text. Pair them into
   `###### Artigo 1.º — Objeto`.
2. It maps `p.paragraph-italic-right` to `firma` (signatures). It is not a signature:
   **41 of 41 occurrences are the last paragraph of the document and 41 of 41 are a
   bare integer.** That is exactly the stray `114808797` that `RESEARCH-PT-v2 §1.3`
   flags at the end of `pt/DRE-DL-109-G-2021.md`. Mapping it to `firma` would ship the
   defect in bold. **Drop it.**

### 2.4 Lists

**Zero `<ol>`, `<ul>` or `<li>` on either surface.** Portuguese laws number inline. The
conventions, counted over both surfaces:

| Convention | Surface A occ / docs | Surface B occ / docs | Emit as |
|---|---|---|---|
| `Artigo N.º` heading | 521 / 24 (as raw text) | 9,247 / 87 | `###### Artigo N.º — Epígrafe` |
| `1 - ` numbered paragraph | 35,327 / 151 | 24,744 / 86 | plain paragraph, verbatim |
| `a)` alínea | 24,292 / 164 | 16,314 / 98 | plain paragraph, verbatim |
| `i)` romana | 1,510 / 95 | 766 / 63 | plain paragraph, verbatim |
| `§ único` / `§ 1.º` | 2,156 / 30 | 1,605 / 21 | plain paragraph, verbatim |
| `1.º` ordinal paragraph (portarias) | — | 1,863 / 18 | plain paragraph, verbatim |
| `Base I` (leis de bases) | 0 (comes through as `TipoFragmentoId 2`) | 0 | `###### Base I` |
| `ANEXO` line | 159 / 12 | 222 / 35 | `## ANEXO` |

61 occurrences of the en-dash variant `1 – ` appear in 6 surface-A documents — the
regex must accept `-`, `–` and `—`.

**Do not invent `- ` list markup.** `RESEARCH-PT-v2 §5.2` already says so; the numbers
confirm it. The current parser's `- ` prefixing is wrong and would renumber the law.

### 2.5 Footnotes, `Nota`, `Notas`, `AlteracoesList`

| Field | Where | Count | Shape |
|---|---|---:|---|
| `ConsolidacaoFragmento.Nota.List` | surface A, per fragment | **291 notes in 60 / 222 docs** | `<a href="/dr/detalhe/…">Artigo 55.º, Decreto Legislativo Regional n.º 1/2023/A …</a>` + plain-text annotation. Real legal annotation (Constitutional Court rulings, transitional effect). |
| `AlteracoesList.List` | surface A, per fragment | **14,148 entries in 207 / 222 docs** | `Alterado pelo/a Artigo 14.º do/a [L]<a rel ="nofollow" href="…" title=Decreto-Lei n.º 143/77 - …">…</a>[/L], em vigor a partir de 1977-04-14` |
| `DetalheConteudo.Notas` | surface B, per document | 4 / 128 docs | DRE editorial note, plain text |
| superscript footnote markers | both | `<sup>` 32 (A) / 29 (B), 5 and 4 docs | inline in text, no reference block |

**Two parser gotchas, both measured:**

- **14,132 of 14,138 `AlteracoesList` entries carry an unquoted `title=` attribute**
  (`title=Decreto-Lei n.º 143/77 - Diário…">`). Any HTML parser will truncate the title
  at the first space and invent junk attributes. Extract the `href` and the anchor text;
  never trust `title` here.
- The `[L]…[/L]` wrapper (14,138 entries) is DRE's own link delimiter, not HTML. Strip it.

`AlteracoesList` is not free content — it is the **same amendment graph** that
`DataActionGetConsolidacaoByDiplomaFrag` returns (`RESEARCH-PT-v2 §3.2`), already
attached to the fragment it modified. Rendering all 14,148 of them inline would swamp
the text; the useful part is that they let the parser attribute a fragment version to an
amending diploma **without a second call**.

Recommendation for open question §12.2: render **`Nota`** (291 entries, genuine legal
annotation) as `nota_pie` → `> <small>…</small>` right after its fragment, and keep
`AlteracoesList` in `extra` only (`extra.amendment_notes: N`), because it duplicates the
commit history that is the whole point of the rebuild.

### 2.6 Cross-reference links

**2,864 `<a>` in 111 / 128 surface-B documents. 2,864 of 2,864 (100 %) carry a `title`
attribute** giving the target's full name:

```html
<a rel='nofollow noopener noreferrer' target='_blank'
   href='/dr/detalhe/resolucao-assembleia-republica/4-1993-626584'
   title='Resolução da Assembleia da República n.º 4/93'>Resolução … n.º 4/93</a>
```

| href shape | Count | Emit |
|---|---:|---|
| `/dr/detalhe/{tipo}/{key}` (national law) | 1,299 | `[text](https://diariodarepublica.pt/dr/detalhe/…)` |
| `https://files.diariodarepublica.pt/…` (PDF page) | 1,343 | `[text](url)` |
| `https://data.europa.eu/eli/dir/…` (**EU directives**) | **218** | `[text](url)` |
| other (search/legacy) | 4 | keep as text |

Surface A has 78 `<a>` in 30 fragments across 8 documents — the consolidated text is far
poorer in links than the as-published text. Another reason `TextoFormatado` is the
right source for the ~104,000 as-published diplomas.

### 2.7 Quoted amending text

Real and structurally awkward. In surface B, **416 paragraphs start with `«` across
23 / 128 documents, but only 89 of them also end with `»`** — the quotation of new
wording routinely spans dozens of paragraphs (`«Artigo 15.º` … `»` twenty paragraphs
later). A per-paragraph test is not enough: the parser needs a small state machine that
opens a blockquote on an unbalanced `«` and closes it on the matching `»`.

Surface A has 1,853 `«…»` in 101 documents, but almost all are *inline quoted terms*
(`«serviços de interesse geral»`), not block quotations — expected, because the
consolidated text shows the amendment already applied. **Apply the blockquote state
machine on surface B only; on surface A leave guillemets inline.**

### 2.8 Formulas

**No MathML, no TeX, no `<math>` on either surface (0 occurrences).** The 380 hits for
`f[óo]rmula` are the verb *formular* ("formular pedidos de esclarecimento"), not
equations. Where a law does carry a formula it arrives either as an `<img>` (§2.9) or as
`(ver documento original)` (§3). No formula handling is required beyond the image and
marker policies.

### 2.9 Images

109 `<img>` in **4 / 128** surface-B documents; 115 in 5 / 222 surface-A documents. 96
of the 109 are the Madeira 2025 budget alone. Stable CDN URLs, constant alt text:

```html
<div class="imageContent" id="DR_IMAGE1"><table class="imageWrapper"><tr><td>
<img src="https://files.diariodarepublica.pt/images/923290710/923294162.png"
     alt="A imagem não se encontra disponível." /></td></tr></table></div>
```

The `alt` is boilerplate on every image and carries no information — do not emit it.
The wrapper `<table class="imageWrapper">` must be recognised *before* the table pass or
it becomes a one-cell Markdown table (this is what produces 109 of the 129 "tables").

Policy: follow `RESEARCH-ES-v2 §11` — emit `![](url)` plus `extra.images_linked: N`.
This contradicts `engine/CLAUDE.md` ("images are explicitly skipped"); Spain already
overrode it and Portugal needs the same explicit decision, or the rule promoted
engine-wide.

### 2.10 Annexes and signatories

- **Anexo** — `TipoFragmentoId 14`, 259 fragments in **89 / 222 documents (40 %)**.
  63 of them have `OmitTipo` and print as `Tabela I`, `ANEXO`, etc. `ConsolidacaoFragmento.IsAnexo`
  is also set. The annex is a normal fragment subtree: it has children (Capítulos,
  Artigos) and must keep its hierarchy, not be flattened.
- **Assinatura** — `TipoFragmentoId 7`, 200 fragments in **192 / 222 documents (86 %)**,
  `Nivel` 1–2, `Identificacao` always empty. Content is the real signature block
  (`Paços do Governo da República, 29 de Maio de 1968. - AMÉRICO DEUS RODRIGUES THOMAZ - …`).
  On surface B there is no class for it: all 280 signature-looking lines are
  `paragraph-normal-text`, so surface B needs a text pattern
  (`^(O Presidente da Rep|O Primeiro-Ministro|Assinado em|Referendado|Promulgado em|Publique-se|Visto e aprovado em Conselho|O Ministro|O Secretário de Estado|Aprovad[oa] em)`),
  matched 299 times in the census (280 on `paragraph-normal-text`, 19 on unclassed `<p>`).

### 2.11 `<sup>` / `<sub>` / `<style>`

- `<sup>`: 32 occurrences in 5 surface-A documents, 29 in 4 surface-B documents.
  `<sub>`: **0 on both surfaces.** Pass `<sup>` through as raw HTML (Markdown allows it).
- `<style>`: **0 on surface A**, 5 on surface B (5 documents), always in
  `TextoFormatado` and never in `Texto`. Contents are only `.TblN { … }` presentation
  rules. **Strip the element and its text.** The current PT regex stripper removes the
  tags but leaves the CSS body as visible text.

### 2.12 Line endings and encoding

| | Surface A | Surface B `TextoFormatado` |
|---|---|---|
| CRLF | 12,857 (166 / 222 docs) | 100,362 (128 / 128 docs) |
| bare LF | **78,788** | **0** |
| named HTML entities | 4 total (`&lt;` 8, `&le;` 3, `&gt;` 2, `&amp;` 1 across 222 docs) | 4 total, 1 doc |
| C0/C1 control chars | **0** | **0** |
| U+FFFD | **0** | **0** |
| mojibake (`Ã…`) | **0** | **0** |
| non-NFC | **0** | **0** |

Surface A is **mixed** CRLF/LF inside the same corpus — normalise both to `\n`.
Surface B is uniformly CRLF. The payload is clean, well-formed NFC UTF-8 on both
surfaces; `fetcher/_text.py::clean()` is sufficient and the hand-rolled 10-entity table
in the current parser can simply be deleted (a real entity decoder still belongs in the
lxml path, but it will fire ~8 times in the whole corpus).

---

## §3 `(ver documento original)` — settled

### 3.1 The corpus

Re-measured on the live `legalize-pt` working tree (109,929 files):

```
$ grep -rl "(ver documento original)" pt/ | wc -l      → 27,954   (25.4 %)
$ python3 scan_vdo.py                                  → 61,857 occurrences
```

| Decade | Affected files |
|---|---:|
| 1960s | 1,457 |
| 1970s | 2,817 |
| 1980s | 6,442 |
| **1990s** | **8,448** |
| 2000s | 4,624 |
| 2010s | 3,402 |
| 2020s | 764 |

By rank: portaria 20,157 · decreto-lei 3,450 · decreto 1,409 ·
decreto-regulamentar-regional 1,067 · decreto-regulamentar 793 · lei 500 ·
decreto-legislativo-regional 440 · resolução 138. How many files are *essentially only* the marker depends on the threshold — the sweep,
counting words of body text left after removing every marker:

| words of other body text | files |
|---|---:|
| < 20 | 0 |
| < 40 | 2 |
| < 60 | 3 |
| < 100 | 429 |
| < 150 | 1,269 |
| < 200 | 3,449 |

`RESEARCH-PT-v2 §1.3`'s "385 laws consist of essentially nothing else" sits on the
< 100-word contour. Worth pinning the definition in the doc, because at the strict end
only **3 files** are truly nothing but the marker.

### 3.2 (a) The official as-published text — 70 of 71 still show the marker

73 affected diplomas, stratified by decade and rank, resolved to their official
`/dr/detalhe/{tipo}/{key}` record and fetched:

| Outcome | N | % |
|---|---:|---:|
| resolved to the official record | 71 / 73 | 97 % |
| **official `TextoFormatado` contains the same `(ver documento original)`** | **70** | **98.6 %** |
| official text is marker-free **and has a real `<table>` where it was** | **1** | **1.4 %** |
| official record not findable (source is a `dre.tretas.org` id, no DRE match) | 2 | — |

**The marker is DRE's, not ours.** In **70 of 71** cases the marker count in the repo
file is *identical* to the marker count in the official `TextoFormatado`. The tretas.org
mirror copied DRE faithfully; the pipeline copied the mirror faithfully. Nothing was
lost by us.

The single recovery is **Portaria n.º 54-F/2023** (2023-02-27): the repo file has 5
markers, the official `TextoFormatado` has **5 real `<table>` elements and 0 markers**,
271 KB. It is a 2023 diploma — consistent with §2.1, where every real table in the
census is from 2023 onward.

By decade the split is total: 1960s 7/7, 1970s 12/12, 1980s 9/9, 1990s 10/10,
2000s 11/11, 2010s 13/13, 2020s 7/8 still show the marker.

Evidence fixture: `tests/fixtures/pt/aspublished-verdocorig-portaria-293-1982.json` —
Portaria 293/82's own official `TextoFormatado`, with its two markers where the wage
tables belong.

### 3.3 (b) The consolidated surface — 40 of 42 still show the marker

First, the ceiling: matching all 27,954 affected files against the 5,561-diploma
consolidated catalogue **on tipo + número + ano**, only **1,262 (4.5 %)** have a
consolidated twin at all. (An earlier match on número + ano alone gave 1,725 and was
wrong — it pairs `Decreto-Lei n.º 402/86` with `Portaria n.º 402/86`. Always match the
type.)

42 type-checked twins, 6 per decade, fetched at 2026-08-21:

| Outcome | N | % |
|---|---:|---:|
| consolidated text **still contains** `(ver documento original)` | **40** | **95.2 %** |
| consolidated text is marker-free but also has **no table** (content simply absent) | 2 | 4.8 % |
| **content recovered from the consolidated surface** | **0** | **0 %** |

Three of the 42 do contain a `<table>` somewhere, but never in place of the marker. The
consolidated surface inherits the marker: DRE consolidates the *text* it has, and the
text it has says "see the original document". Corpus-wide, surface A carries **409
markers across 47 of 222 (21 %) sampled consolidated diplomas** — the marker is not a
legacy artefact, it is live in the current consolidated corpus.

### 3.4 (c) The PDF

`URL_PDF` is present and returns a valid PDF for **71 of 73** affected diplomas
(the 2 misses are the 2 unresolvable ones). But whether the PDF is *readable* splits
hard on the year:

| Decade | PDFs probed | with **zero** extractable text (image scan) |
|---|---:|---:|
| 1960s | 3 | **3** |
| 1970s | 3 | **3** |
| 1980s | 3 | **3** |
| 1990s | 3 | 2 |
| 2000s | 3 | 0 |
| 2010s | 3 | 0 |
| 2020s | 3 | 0 |
| **total** | **21** | **11** |

The transition is ~1997: `DRE-DLR-9-A-97-A` (1997) yields 85,455 characters,
`DRE-DL-126-94` (1994) yields 0. Everything before is a scan of the printed Diário and
needs OCR. **64.7 % of affected files (18,081) were published before 1997-01-01.**

### 3.5 The answer, in numbers

Extrapolating the sampled rates to the 27,954 affected files:

| Recoverable from | Rate measured | Files (est.) |
|---|---|---:|
| **A — consolidated surface** | 0 / 42 twins, and only 4.5 % have a twin | **~0** |
| **B — official as-published `TextoFormatado`** | 1 / 71 (1.4 %), all 2023+ | **~400** (upper bound; 764 files are 2020s) |
| **PDF with a text layer** (1997+) | 10 / 10 probed post-1997 PDFs have text | **9,873 (35.3 %)** |
| **PDF, scan only — OCR required** | all 11 probed pre-1997 PDFs | **18,081 (64.7 %)** |
| **not recoverable from any DRE surface without OCR** | | **18,081 (64.7 %)** |

### 3.6 Recommendation — resolves open question §12.1

**Do not enrich from surface A or surface B.** It recovers ~1.4 % of the affected files,
it would mix two source texts inside one law (the thing §12.1 was worried about), and it
buys nothing at all for the 96 % of the corpus published before 2023.

**Do not put PDF extraction in the rebuild.** It is the only path that reaches a
meaningful share (35 %), it needs table reconstruction from a `-layout` text dump, it
does nothing for the 65 % that are scans, and OCR is explicitly out of scope
(`RESEARCH-PT-v2 §11`).

**Do render the marker honestly and make it useful.** Replace the bare copied string
with a pointer to the page that does have the content, and count it:

```markdown
> *(Tabela, figura ou anexo não disponível em texto na fonte —
> [ver documento original](https://files.diariodarepublica.pt/1s/1982/03/06300/05970598.pdf))*
```

emitted as `Paragraph(css_class="nota_pie", text=…)`, plus
`extra.ver_documento_original: N` in the frontmatter so the fidelity loop (§8) can score
it and the web app can surface it. That turns a dead string in 25 % of the corpus into a
working link, costs one branch in the parser, and states the limitation instead of
hiding it. The README claim *"as tabelas são convertidas para tabelas Markdown"* must be
corrected at the same time.

---

## §4 Proposed css_class map, checked against `transformer/markdown.py`

Checked against `_SIMPLE_CSS_MAP` and `_PAIRED_CLASSES` as they stand today
(`src/legalize/transformer/markdown.py`). "impl" = the class already exists and renders
as shown; "new" = no entry exists.

### 4.1 Surface A — `TipoFragmentoId` → css_class

| id | Source construct | css_class | Renders | Status |
|---:|---|---|---|---|
| 4 | Parte | `parte_num` | `# {Tituo}` | impl (paired branch, falls through to `#`) |
| 12 | Livro | `libro_num` | `# {Tituo}` | impl |
| 13 | Título | `titulo_tit` | `## {Tituo}` | impl |
| 5 | Subtítulo | `titulo_tit` | `## {Tituo}` | impl — **collapses with Título** ⚠ |
| 14 | Anexo | `anexo_num` | `## {Tituo}` | impl |
| 1 | Capítulo | `capitulo_tit` | `### {Tituo}` | impl |
| 8 | Secção | `seccion_tit` | `#### {Tituo}` | impl |
| 3 | Subsecção | `subseccion_tit` | `##### {Tituo}` | impl |
| 9 | Divisão | `subseccion_tit` | `##### {Tituo}` | impl — **collapses** ⚠ |
| 6 | Subdivisão | `subseccion_tit` | `##### {Tituo}` | impl — **collapses** ⚠ |
| 10 | Tabela (heading) | `subseccion_tit` | `##### {Tituo}` | impl — **no dedicated class** ⚠ |
| 11 | Artigo (+ Epigrafe) | `articulo` | `###### Artigo 1.º — Objeto` | impl |
| 2 | Base | `articulo` | `###### Base I` | impl |
| 7 | Assinatura | `firma` | `**{text}**` | impl |
| 15 | Diploma (preamble) | `parrafo` | plain paragraph | impl (unknown-class fallthrough) |
| — | fragment body text | `parrafo` | plain paragraph | impl |
| — | `<table>` in `Texto` | `table` | verbatim pipe table from `render_table` | impl |
| — | `imageWrapper` / `<img>` | `image` | `![](url)` | impl |
| — | `Nota.List` entry | `nota_pie` | `> <small>…</small>` | impl |
| — | `AlteracoesList` | *(none — `extra` only)* | — | decision, §2.5 |
| — | `(ver documento original)` | `nota_pie` | `> <small>… [ver documento original](pdf)</small>` | impl, §3.6 |

### 4.2 Surface B — `p.paragraph-*` → css_class

| Source construct | css_class | Renders | Status |
|---|---|---|---|
| `p.paragraph-title-bold-center-18px` | *(drop)* | — | the renderer already emits `# {metadata.title}`; keeping it re-creates defect §1.3 #11 |
| `p.paragraph-bold-center` (`de 17 de Março`, sumário) | `parrafo` | plain | impl |
| `p.paragraph-center` matching `^PARTE` | `parte_num` | `#` | impl |
| … `^LIVRO` | `libro_num` | `#` | impl |
| … `^TÍTULO` | `titulo_tit` | `##` | impl |
| … `^ANEXO` | `anexo_num` | `##` | impl |
| … `^CAPÍTULO` | `capitulo_tit` | `###` | impl |
| … `^SECÇÃO` | `seccion_tit` | `####` | impl |
| … `^SUBSECÇÃO` | `subseccion_tit` | `#####` | impl |
| … `^Artigo N.º` (+ next `p.paragraph-bold-center-14px`) | `articulo` | `###### Artigo 1.º — Objeto` | impl |
| `p.paragraph-bold-center-14px` **not** after a heading | `parrafo` | plain | impl |
| `p.paragraph-normal-text` | `parrafo` | plain | impl |
| `p.paragraph-normal-text` matching the signature pattern | `firma` | `**…**` | impl |
| `p.paragraph-normal-text` opening/inside `«…»` | `cita` | `> ` | impl (needs the §2.7 state machine) |
| `p.paragraph-italic-right` | *(drop)* | — | **always the DRE internal id — never `firma`** |
| `p` with no class | `parrafo` | plain | impl |
| `div.tableContent` → `<table>` | `table` | verbatim pipe table | impl |
| `div.imageContent` / `table.imageWrapper` → `<img>` | `image` | `![](url)` | impl |
| `<style>` | *(strip element and text)* | — | not a class; current regex stripper leaks the CSS body |
| `<a href>` inline | inline in `parrafo` text | `[Lei n.º 45-A/2024](https://…)` | pre-wrapped in the parser |
| `<sup>` inline | inline in `parrafo` text | raw `<sup>` passthrough | pre-wrapped in the parser |
| `(ver documento original)` | `nota_pie` | see §3.6 | impl |

### 4.3 Constructs with no suitable existing css_class

Four, all of them level collapses rather than lost content — the heading **text** still
carries the Portuguese type word, so a reader loses only heading depth:

| Construct | Frequency | Collapsed onto | Cost |
|---|---:|---|---|
| **Subtítulo** (id 5) | 8 frags / 2 docs (0.04 %) | `titulo_tit` (`##`), same as Título | Título and Subtítulo render at the same depth in Código Civil and Código do Trabalho |
| **Divisão** (id 9) | 124 frags / 9 docs | `subseccion_tit` (`#####`) | Subsecção > Divisão flattens |
| **Subdivisão** (id 6) | 17 frags / 4 docs | `subseccion_tit` (`#####`) | Divisão > Subdivisão flattens |
| **Tabela** (id 10) | 3 frags / 1 doc (0.01 %) | `subseccion_tit` (`#####`) | a table caption reads as a section heading |

Markdown has six heading levels; `#` is spent on the law title; the Portuguese hierarchy
has ten tiers (Parte > Livro > Título > Subtítulo > Capítulo > Secção > Subsecção >
Divisão > Subdivisão > Artigo). Adding `subtitulo_tit` / `division_tit` /
`subdivision_tit` to `_SIMPLE_CSS_MAP` would be three one-line entries but would have to
render at a level that is already taken, so it buys nothing a reader can see. **Reuse and
document.** Revisit only if the fidelity loop's HEADINGS axis (§8) shows it costs score.

One real gap that is *not* a collapse: **`table.imageWrapper` must be detected before the
table pass.** It is not a css_class question — it is a parser-ordering question — but it
is the single biggest source of wrong output if missed (109 of 129 surface-B tables and
113 of 168 surface-A tables are wrappers, not tables).

---

## §5 Artefacts

| Path | What |
|---|---|
| `tests/fixtures/pt/formatting-inventory.json` | the full `TipoFragmentoId` map with counts, both per-document censuses, and the entire §3 probe (surface-B sample, surface-A twins, PDF text-layer results) |
| `tests/fixtures/pt/legcons-base-lei-4-1973.json` | `TipoFragmentoId 2` (**Base**) — 8 fragments |
| `tests/fixtures/pt/legcons-parte-diretiva-21-a-2024.json` | `TipoFragmentoId 4` (**Parte**) with `OmitTipo`, plus `imageWrapper` layout tables |
| `tests/fixtures/pt/legcons-tabela-dr-18-2001.json` | `TipoFragmentoId 10` (**Tabela**) — the only carrier in the sample |
| `tests/fixtures/pt/legcons-anexo-assinatura-dec-28-1984.json` | `TipoFragmentoId 14` + `7` in a 4-fragment document |
| `tests/fixtures/pt/aspublished-table-rowspan-lei-organica-2-2023.json` | real `<table>` with `rowspan`/`colspan`/`<thead>` + a `<style>` block |
| `tests/fixtures/pt/aspublished-verdocorig-portaria-293-1982.json` | proof that `(ver documento original)` is DRE's own marker on the official surface |

---

## §6 Corrections to `RESEARCH-PT-v2.md`

For integration — every one of these is measured above.

1. **§3.3** — ids 2, 4, 10 are **Base**, **Parte**, **Tabela**. The taxonomy is exactly
   1–15. Heading levels for Livro/Título/Subtítulo in that table are usable; add Parte
   (`#`), Base (`######`), Tabela (`#####`).
2. **§5.1** — the four fixtures contain **102** `<table>`, not 204, and **96 of them are
   `table.imageWrapper`** layout wrappers; only 6 are data tables.
3. **§5.1** — `p.paragraph-center` (12,293 occ, 89 docs) is missing from the table and is
   *the* heading class. `p.paragraph-bold-center-14px` is the **epígrafe**, not the heading.
4. **§5.1** — `p.paragraph-italic-right` is **not** `firma`. It is DRE's internal content
   id, always the last paragraph, always numeric (41/41). Drop it.
5. **§5.1** — "no HTML entities at all in the official payload" is nearly true but not
   exactly: 4 named entities appear (`&lt;`, `&le;`, `&gt;`, `&amp;`) in 1 of 128 docs.
6. **§5.1 / §5.2** — surface A line endings are **mixed**: 78,788 bare LF and 12,857 CRLF.
   Surface B is uniformly CRLF.
7. **§3.4** — the plain/HTML split is much sharper than the 12-diploma read suggested:
   1.0 % of consolidated fragments carry HTML overall, but **48.4 % of 2026-dated
   fragment versions** do. The corpus is migrating now.
8. **§1.3** — "385 laws consist of essentially nothing else" needs a stated threshold:
   429 files have < 100 words of body text besides the marker, but only **3** have < 60
   and **0** have < 20. Pin the definition (§3.1 has the sweep).
9. **§1.3 / §5.2** — the stray trailing integer (`114808797`) is explained: it is
   `p.paragraph-italic-right`, present in 41 of 41 documents that have the class.
10. **§12.1 is settled** — see §3.6. Render as-is with a PDF pointer and a counter; do not
    enrich from A, B or the PDF.
11. **New scope fact** — **CIRS (DL 442-A/88), CIRC (DL 442-B/88) and CIVA (DL 394-B/84)
    are not in DRE's consolidated catalogue at all** (verified: 27 diplomas from 1988 in
    the consolidated sitemap, none of them 442-A/88; only one
    `legislacao-consolidada-sitemap-*.xml` exists in the 588-entry sitemap index). DRE's
    own `Notas` field on those records says the consolidated version lives in the annex of
    the republishing law (Lei 82-E/2014 for CIRS, Lei 2/2014 for CIRC, DL 102/2008 anexo
    IV for CIVA). Portugal's three biggest tax codes will therefore be **single-snapshot,
    surface-B laws** unless the republication annexes are handled specially. Worth an
    explicit decision before the bootstrap.
