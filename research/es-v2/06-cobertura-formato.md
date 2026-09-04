# 06 — Format coverage and text fidelity (§0.4 + §0.7)

Probe 6 of the Spain re-emission Step 0 · 2026-09-03 · read-only pass
Artefact: `engine/research/es-v2/06-cobertura-formato.md`

**HTTP requests to boe.es: 148** (76 × 200, 72 × 404 — the 72 were one wasted batch
against a wrong path, see *Cost of this probe* at the end). 23.7 MB downloaded, one
request every 0.8–0.9 s, no 429, no 5xx.

---

## TL;DR

1. **The published Markdown is far more faithful than expected.** Over 46 consolidated
   documents fetched today and compared block-by-block against the version each file
   actually renders at HEAD: **177 of 178 tables survive** (99.4 %), **100 of 110 images**
   (90.9 %), bold and cross-reference links are complete. There is no mojibake, no
   control characters, no NBSP residue and no doubled prose anywhere in the 12,299
   published files.
2. **Four real, root-caused losses**, all small and all one-line fixes: `<img>` as a
   *direct child* of `<td>` renders as an empty cell (10 images lost in one law);
   `<caption>` is dropped entirely (23/23); `<p class="textoCompleto">` — the BOE's own
   note that a *corrección de errores* is folded in — is stripped (18 occurrences,
   13/46 docs); a `<table>` nested inside another `<table>` collapses into one.
3. **One systemic rendering hazard, corpus-wide and measured exactly:**
   **167,666 of 391,038 Markdown ordered-list runs (42.9 %), in 9,396 of 12,299 files
   (76.4 %), do not start at 1 or are not consecutive.** A CommonMark renderer
   renumbers those — the law says "3." and the page shows "1.". The `.md` is faithful;
   the *render* is not.
4. **§0.7: Spain is a single-format source, twice over.** The consolidated corpus is
   XML-only (`/texto`), 46/46 hit. The non-consolidated acts are XML-only too
   (`/diario_boe/xml.php`) — **full text for all 21 documents sampled from 1835 to 2025**,
   and for 4 documents that were never consolidated. There is no PDF-only era and no
   format boundary to bridge. The gate is passed with a one-row table.
5. **The `_STRIP_CLASSES` fear is dead.** All 94,310 `cabeza_tabla`/`cuerpo_tabla_*`
   paragraphs in the consolidated sample and all 392 in the diary sample sit inside a
   `<td>`. **Zero standalone.** The strip guard has never deleted a table cell.

---

## Method

Two halves, deliberately built so the expensive half is small.

**Local, zero HTTP (the denominator).** All 12,299 `.md` files under
`/Users/neli/projects/legalize/countries/es` (clean at `origin/main`; `es/` = 8,690 files
plus 17 `es-*/` comunidad directories = 3,609; 967,107,839 bytes of Markdown) were
censused with `/Users/neli/.claude/jobs/5bf7ddf4/tmp/census_md.py` for every Markdown
construct and every defect signature. These are **exact counts over the whole corpus**,
not estimates.

**Remote, 148 requests (the numerator).** A stratified sample of **46 consolidated
documents** (`/api/legislacion-consolidada/id/{id}/texto`), chosen from the corpus
frontmatter to span every decade from the 1830s to the 2020s, twelve `rank` values, the
tax/tariff/annex-heavy titles where tables live, and the six files the local defect grep
had already flagged. Plus **21 diary documents** (`/diario_boe/xml.php?id=`), one per era
1835→2025, **4 never-consolidated diary documents** found via two `sumario` calls,
**2 `act.php` HTML renderings**, and **1 catalogue head**.

**The comparison is version-aware.** The `/texto` XML holds *every* version of *every*
block; a published `.md` at HEAD holds only the version `get_block_at_date` selects —
for HEAD, the latest one per block. Counting constructs over the whole XML overstates
the source by roughly 3×. Every source-vs-output number below is restricted to the HEAD
version of each block, exactly mirroring `xml_parser.get_block_at_date`. (My first pass
did not do this and produced a false "67 % of tables are missing"; it is recorded here
so nobody repeats it.)

Sample: 46 of 12,299 files = **0.37 %**. Every per-file percentage from the sample carries
a 95 % Wilson interval, given below. Corpus-wide numbers carry none — they are exhaustive.

Scripts, raw XML and JSON: `/Users/neli/.claude/jobs/5bf7ddf4/tmp/`
(`census_md.py`, `census_src.py`, `compare2.py`, `dig.py`, `dig2.py`, `diary.py`,
`raw/`, `http_log.json`).

---

## Half 1 — §0.4 formatting inventory of the source

### What the source actually uses

Presence = "at least one occurrence anywhere in the document". Sample n = 46
consolidated documents, 3,989 `bloque`, 5,252 `version`.

| Construct | Source element(s) | Files | % of sample | 95 % CI | Occurrences (all versions) | Example id |
|---|---|---:|---:|---|---:|---|
| Cross-reference links | `<a>` | 33 | 71.7 % | 57.5–82.7 | 3,869 | `BOE-A-1986-9865` |
| Blockquotes (footnotes + quoted amending text) | `<blockquote>` | 31 | 67.4 % | 53.0–79.1 | 1,655 | `BOE-A-1984-12106` |
| Bold | `<strong>` (`<b>` 1×) | 22 | 47.8 % | 34.1–61.9 | 1,462 | `BOE-A-1957-11398` |
| Tables | `<table>` | 17 | 37.0 % | 24.5–51.4 | 543 (89,445 cells) | `BOE-A-2013-7540` |
| Italic | `<em>` | 12 | 26.1 % | 15.6–40.3 | 136 | `BOE-A-2013-7540` |
| Superscript | `<sup>` | 7 | 15.2 % | 7.6–28.2 | 213 | `BOE-A-2014-6084` |
| Images / figures | `<img>` | 6 | 13.0 % | 6.1–25.7 | 121 | `BOE-A-2014-12029` |
| Subscript | `<sub>` | 4 | 8.7 % | 3.4–20.3 | 3,751 | `BOE-A-2014-6084` |
| Preformatted | `<pre>` | 1 | 2.2 % | 0.4–11.3 | 3 | `BOE-A-1999-14374` |
| Table caption | `<caption>` | 1 | 2.2 % | 0.4–11.3 | 43 | `BOE-A-2013-7540` |
| Underline | `<u>` | 1 | 2.2 % | 0.4–11.3 | 41 | `BOE-A-2013-7540` |
| **Ordered lists** | `<ol>`/`<li>` | **0** | **0.0 %** | 0.0–7.7 | **0** | — |
| **Unordered lists** | `<ul>` | **0** | **0.0 %** | 0.0–7.7 | **0** | — |
| **Formulas / MathML** | `<math>` | **0** | **0.0 %** | 0.0–7.7 | **0** | — |
| Horizontal rule | `<hr>` | 0 | 0.0 % | 0.0–7.7 | 0 | — |

Three of these deserve a sentence.

- **There are no HTML lists in BOE consolidated XML at all.** Enumerations are ordinary
  `<p class="parrafo">` whose text begins `1.`, `a)`, `Primero.`. The parser's
  `_list_paragraphs` branch is dead code for `es`. This is what makes finding 3 below a
  formatting problem rather than a parsing one.
- **There is no MathML and no TeX.** Formulas are carried as `<img>` (a rendered
  equation) or as `<sup>`/`<sub>` inline text. `BOE-A-2014-6084` (electrical safety
  regulation) is the type specimen: 14 images and 3,751 `<sub>`.
- **`<sub>` is concentrated, not spread.** 3,751 occurrences in 4 files. Chemical and
  electrical annexes.

### Footnotes, signatories, annexes, quoted amending text

These are carried by `p/@class`, not by an element, so they are counted separately.
Over the HEAD version of every block in the 46-document sample:

| Construct | Carrier | Occurrences (HEAD) | Corpus-wide in the published `.md` |
|---|---|---:|---:|
| Footnotes / legislative audit trail | `p.nota_pie`, `p.nota_pie_2` | 1,628 | 7,355 files (59.8 %), 154,997 lines |
| Quoted amending text | `<blockquote>` + `p.cita*` | 1,259 blockquotes | 8,023 files (65.2 %), 259,727 `> ` lines |
| Signatories | `p.firma_rey`, `p.firma_ministro`, `p.firma` | 95 | 8,218 files (66.8 %), 39,961 bold-only lines |
| Annexes | `p.anexo*` | 96 | 4,067 files (33.1 %), 12,911 headings |
| Appendices | `p.apendice*` | — | 85 files (0.7 %), 1,448 headings |
| Editorial "incorporates a corrección de errores" note | `p.textoCompleto` | 11 (18 over all versions, 13 files) | **0 — stripped** |

### The `p/@class` vocabulary and what `markdown.py` does with it

33,761 `<p>` elements that are **direct children of `<version>`** — the only ones `_parse_p` ever sees — across 32 distinct classes. (Counting every `<p>` including those inside `<td>` gives 132,565 across 41 classes; the extra 9 are the table-cell classes.) The interesting rows:

| Class | Occurrences | Files | Treatment | Verdict |
|---|---:|---:|---|---|
| `parrafo`, `parrafo_2` | 26,660 | 46 | unknown → plain paragraph | correct (they *are* plain paragraphs); `parrafo_2` loses its indent level |
| `articulo` | 4,285 | 44 | `###### ` | correct |
| `cerrado` | 580 | 1 | unknown → plain paragraph | benign |
| `capitulo` | 32 | 8 (17.4 %) | **unknown → plain paragraph** | **heading lost** — `capitulo_num`/`capitulo_tit` are mapped, bare `capitulo` is not |
| `libro` | 5 | 5 (10.9 %) | **unknown → plain paragraph** | **heading lost** — same gap |
| `textoCompleto` | 18 | 13 (28.3 %) | **`_STRIP_CLASSES` → dropped** | **content lost** |
| `imagen` | 102 | 5 | `_parse_p` → `![alt](src)` | correct |
| `siempreSeVe` | 13 | 12 | unknown → plain paragraph | benign |

Verified for `capitulo`: 10 of 10 sampled occurrences appear in the `.md` as plain text
and **none** as a heading — e.g. `BOE-A-1991-18227` "Fundación de las Sociedades Anónimas
Deportivas", `BOE-A-1993-25359` "Documentos notariales", `BOE-A-1964-23345` "DISTANCIAS
DE SEGURIDAD". BOE renders these centred and bold; we render them as body text.

### Two things that are *not* problems

- **Version-level dispatch is complete.** Across 5,252 versions there is **not one**
  child element outside `{p, table, ol, ul, img, pre, blockquote}`. The `else:
  logger.debug("unhandled element")` branch in `parse_text_xml` never fires for `es`.
- **No structure is nested inside `<p>`.** Zero `<table>`, `<ol>`, `<ul>`, `<blockquote>`,
  `<tr>`, `<td>` or `<li>` anywhere below a `<p>` in 46 documents, so
  `_extract_inline` never flattens a structure it should have dispatched.

---

## Half 2 — the published Markdown against the source

### Corpus-wide census of the published `.md` (n = 12,299, exhaustive)

| Construct | Files | % | Occurrences |
|---|---:|---:|---:|
| Headings (any level) | 12,299 | 100.0 % | 630,334 |
| `###### ` article headings | 12,089 | 98.3 % | 449,393 |
| Lines beginning `N. ` | 10,599 | 86.2 % | 844,755 |
| Disposition headings | 10,492 | 85.3 % | 96,352 |
| Bold | 8,535 | 69.4 % | 73,076 |
| Bold-only line (signatory) | 8,218 | 66.8 % | 39,961 |
| Links | 8,091 | 65.8 % | 149,387 |
| — of them, BOE `doc.php` cross-refs | 8,072 | 65.6 % | 149,143 |
| Blockquote lines | 8,023 | 65.2 % | 259,727 |
| — of them, `> <small>` footnotes | 7,355 | 59.8 % | 154,997 |
| ANEXO headings | 4,067 | 33.1 % | 12,911 |
| Italic | 3,251 | 26.4 % | 71,816 |
| **Pipe tables** | **3,162** | **25.7 %** | **33,680 tables / 840,649 rows** |
| Indented (`sangrado`) paragraphs | 1,662 | 13.5 % | 103,512 |
| Images | 1,608 | 13.1 % | 26,169 |
| `<sup>` | 1,335 | 10.9 % | 33,010 |
| `<sub>` | 801 | 6.5 % | 35,560 |
| Fully-empty pipe row | 189 | 1.5 % | 1,238 |
| Bullet `- ` items | 76 | 0.6 % | 1,415 |
| Code fences (`<pre>`) | 6 | 0.05 % | 40 |

### Hygiene: what is *not* there

| Defect probed corpus-wide | Files | Occurrences |
|---|---:|---:|
| UTF-8 mojibake (`Ã©`, `Â«`, …) | **0** | 0 |
| C0/C1 control characters | **0** | 0 |
| NBSP / zero-width residue | **0** | 0 |
| Leftover `class="…"` attribute text | 3 | 41 |
| Leftover HTML entities (`&quot;`) | 3 | 12 |
| Leftover `<p>`/`<td>`/`<table>` markup | 2 | ~65 |
| U+FFFD replacement character | 1 | 5 |
| Empty body | **0** | 0 |
| Body under 200 bytes | **0** | 0 |
| Doubled consecutive **prose** paragraphs | **0** | 0 |
| Doubled consecutive **table rows** | 79 | 693 |

The `_text.clean()` hygiene pass works. Sixteen years of BOE XML and not one mojibake.

The nine files that do carry residue, each identified and root-caused:

| File | What | Cause |
|---|---|---|
| `es/BOE-A-1999-14374.md` | `<td>TEXTO DE DIRECCIÓN NO ESTRUCTURADA (25 X)</td>` ×8 | the *law itself* documents an XML format; the source escapes it, we un-escape it and emit raw HTML into Markdown |
| `es/BOE-A-2008-2389.md` | `<envio> <version> <anuncios> …` ×~40 | same — a Real Decreto specifying a filing schema |
| `es/BOE-A-2013-7540.md` | `tr class="row_column_4">` | ill-formed source fragment recovered by `XMLParser(recover=True)` |
| `es-mc/BOE-A-2020-9795.md` | `class="no_partir"` leaked into body text | same |
| `es/BOE-A-2004-18910.md`, `es/BOE-A-2004-17826.md`, `es-cb/BOE-A-1993-5274.md` | `&quot;` | double-escaped in the source (`&amp;quot;`) |
| `es/BOE-A-2014-6084.md` | `1000 �` ×5 | the ohm sign Ω was already un-decodable in the source bytes; `decode_utf8(errors="replace")` did its job |

Nine files out of 12,299 = **0.073 %**. Two of them are not defects at all (the law
really does contain markup), and one is upstream. **Not worth blocking the re-emission
on**, but `<` in body text should be escaped or fenced on the way out.

### Source vs output, version-aware (n = 46, HEAD version of every block)

| Construct | In source (HEAD) | In published `.md` | Delta |
|---|---:|---:|---|
| Tables | 178 | 177 | **−1** (0.6 %) |
| Images | 110 | 100 | **−10** (9.1 %) |
| Bold | 1,005 | 1,223 | +218 — signatory classes render as `**…**`, expected |
| `<a>` cross-references | 1,641 | 1,617 | −24 (1.5 %) |
| Blockquote units → lines | 1,259 | 2,031 lines | expected (one blockquote = several lines) |
| `<caption>` | 23 | **0** | **−23** (100 %) |
| `p.textoCompleto` | 11 | **0** | **−11** (100 %) |

Per-file table counts match exactly in 45 of 46 documents, including the hard ones:
`BOE-A-2002-18310` 34→34, `BOE-A-2014-6084` 23→23, `BOE-A-2013-7540` 91→90,
`BOE-A-1995-2520` 7→7, `BOE-A-2008-2389` 5→5.

### The four confirmed losses, with root cause

**L1 — `<img>` directly inside `<td>` produces an empty cell.**
`BOE-A-1968-963` has 11 images in the version it renders at HEAD; the `.md` carries 1.
The ten lost ones sit as `<td class="imagen"><img/></td>`; the surviving one sits as
`<p class="imagen"><img/></p>`. Cause: `xml_parser._cell_text(cell)` calls
`_extract_inline(child)` on each child, and `_extract_inline` only converts `<img>` when
it is a *child* of the element it is given — an `<img>` that *is* the child returns "".
Confirmed against BOE's own rendering: `act.php?id=BOE-A-1968-963` serves all 11
(`/datos/imagenes/disp/1968/189/00963_6527951_image2..12.png`).
Sample rate 1/46 files (2.2 %, CI 0.4–11.3). Fix: two lines in `_cell_text`.

**L2 — `<caption>` is dropped.** 23/23 in the HEAD versions of `BOE-A-2013-7540`
(fertiliser regulation; the captions carry the substantive rule text, e.g. "1.4.1.1
Abonos nitrogenados — Los abonos nitrogenados simples que ut…"). Cause:
`_tables.render_table` iterates `tr` only. Sample rate 1/46 (2.2 %, CI 0.4–11.3), but
occurrence-heavy where it happens. Fix: emit the caption as a paragraph above the table.

**L3 — `p.textoCompleto` is stripped.** 18 occurrences in 13 of 46 files (28.3 %,
CI 17.2–42.6). The content is always the BOE's own consolidation note:
*"Incluye la corrección de errores publicada en BOE núm. 203, de 22 de julio de 1955.
Ref. BOE-A-1955-10464"*. This is legislative provenance, and it is the only place the
source states that a corrección is folded in. It was put in `_STRIP_CLASSES` alongside
the table-cell classes, which is where the mistake happened — the table-cell classes
never needed stripping (see below) and `textoCompleto` never deserved it.

**L4 — a `<table>` nested inside a `<table>` collapses into one.**
`BOE-A-2013-7540`, 91 source tables → 90 pipe tables. `render_table` uses
`table_el.iter()`, which descends into the nested table and merges its rows into the
outer grid. 1 nested table in 178 (0.6 %); 1 file in 46.

### Two losses that are cosmetic

- **`<u>` underline**: text survives, the underline does not (7 occurrences, 1 file).
  Markdown has no underline; nothing to fix.
- **Cross-references BOE ships with no `href` and no `referencia`**: 3,868 of 3,869
  `<a>` elements in the sample have neither. The `_BOE_ID_RE` fallback rescues 3,819 of
  them (98.7 %) by scraping the id out of the anchor text. The remaining **49 (1.27 %)**
  keep their text but lose the link — they name a non-BOE identifier (`Ref. 200/13813`,
  `Ref. BORM-s-2020-90486`). Only matters for the `es-*` comunidad corpus.

### The fear that turned out to be unfounded

`_STRIP_CLASSES` deletes `cabeza_tabla` and `cuerpo_tabla_{izq,centro,der}` paragraphs.
If the BOE ever emitted those *standalone* — the pre-`<table>` layout convention — every
cell of that table would vanish silently. Measured:

| Corpus | Strip-class paragraphs | Inside a `<td>`/`<th>` | Standalone |
|---|---:|---:|---:|
| Consolidated (46 docs) | 94,310 | **94,310** | **0** |
| Diary XML (21 docs, 1835–2025) | 392 | **392** | **0** |

Zero in 67 documents spanning 190 years. The guard is harmless. Keep it, and take
`textoCompleto` out of it.

### The one systemic problem: Markdown steals the law's numbering

BOE has no `<ol>`. A numbered legal paragraph arrives as
`<p class="parrafo">3. El Estado…</p>` and is emitted verbatim as `3. El Estado…`,
which every CommonMark renderer reads as an ordered-list item. CommonMark takes the
*first* number of a run as the start value and then renumbers sequentially, so a run
that starts at 3, or that reads `10, 6, 7`, is displayed wrong.

Measured over all 12,299 files (`dig2.py`, section C):

| | Count | Share |
|---|---:|---:|
| Ordered-list runs in the published Markdown | 391,038 | |
| Runs that do **not** start at 1, or are not consecutive | **167,666** | **42.9 %** |
| Files containing at least one such run | **9,396** | **76.4 %** |

Examples: `es/BOE-A-1862-4073` has runs `[3,4,5,6,7,8]` and `[2,3,4,5,6]`;
`es/BOE-A-1882-6036` has `[10,6,7]`. The file on disk is a faithful transcription; what
a reader sees is not. This is the single largest fidelity item in the corpus and the
re-emission is the only cheap chance to fix it (escape the separator as `3\. `, or make
`markdown.py` emit numbered legal paragraphs in a form Markdown will not claim).

### Layout tables

BOE uses borderless tables to lay out signature blocks side by side. Example, the source
of `BOE-A-2005-12949`:

```xml
<table class="sinbordes">
  <colgroup><col width="40%"/><col width="5%"/><col width="40%"/></colgroup>
  <tr><td class="cuerpo_tabla_centro">M.ª ROSA PUIG OLIVER,</td>
      <td class="cuerpo_tabla_centro"><p class="cuerpo_tabla_centro">&#160;</p></td>
      <td class="cuerpo_tabla_centro">JAUME MATAS PALOU,</td></tr>
```

which we publish as a bordered pipe table whose *first data row is promoted to a header*:

```
| M.ª ROSA PUIG OLIVER, |  | JAUME MATAS PALOU, |
| --- | --- | --- |
|  |  |  |
```

Two effects, both measured:

- **Header promotion.** `render_table` has no fallback: `header = expanded[0]` whenever
  there is no `<thead>`. In the sample only **293 of 543 tables (54.0 %)** carry a
  `<thead>`; the other **250 (46.0 %)** have their first *data* row rendered as a header.
  Markdown pipe tables require a header row, so this is a forced choice — but an empty
  header row is the honest one.
- **Layout tables.** `class="sinbordes"` is 2 of 178 HEAD tables (1.1 %). The
  corpus-wide symptom is the fully-empty pipe row: **189 files (1.5 %), 1,238 rows**.

**Rowspan expansion.** 233 of 543 tables (42.9 %) use `colspan`/`rowspan`;
`render_table` repeats the merged cell's content into every expanded slot. That is the
whole explanation for the 693 "doubled paragraphs" in 79 files: **693 of 693 are pipe-table
rows, 0 are prose**. It is a documented approximation, not a bug.

---

## §0.7 — Format-coverage gate

### Shape A — the consolidated corpus (what exists today)

**Single-format source (XML only); the gate is satisfied by one row.**

| Format | Endpoint | Laws reached | Versions reached | Unique | % of catalogue |
|---|---|---:|---:|---:|---:|
| **XML** | `/datosabiertos/api/legislacion-consolidada/id/{id}/texto` | **46/46 sampled, 200 with content** | **all 5,252 versions of the 3,989 blocks in the sample** | **all** | **100 %** |
| HTML | `/buscar/act.php?id={id}` | same set | current text only — no `<version>` markup | 0 | — |
| PDF | `url_pdf` (frontmatter: 12,298/12,299) | same set | the *original gazette page*, not the consolidated text | 0 | 100 % |
| EPUB | `url_epub` (5,269/12,299) | subset | current text only | 0 | 42.8 % |

The XML is the only manifestation that carries version history at all — every other
format serves a single snapshot. **Every non-XML format contributes 0 unique laws and 0
unique versions, so all of them fail the >1 % rule and are skipped.** Written
justification, as the playbook requires: *HTML, EPUB and PDF are alternative renderings
of text the XML already carries in full, plus version markup they lack; covering them
would add zero laws and zero versions and would lose the `<version fecha_publicacion=…>`
attributes the whole pipeline is built on.*

There is no cross-format before/after check to do, because there is no format boundary.

**One item flagged, not skipped:** the frontmatter shows official *translations* as
separate PDFs — Catalan for **3,007 files (24.5 %)**, Galician 2,378 (19.3 %), Valencian
563 (4.6 %), Basque 353 (2.9 %). These are a language dimension, not a format dimension,
so §0.7 does not bite; but they are official text we publish nothing of, and 24.5 % is
well over any 1 % line. Decision needed, out of this probe's scope.

### Shape B — the non-consolidated acts (what the re-emission adds)

**Also single-format XML. There is no PDF-only era.** This was the open risk and it is
closed.

`GET https://www.boe.es/diario_boe/xml.php?id={id}` returns
`<documento><metadatos/><metadata-eli/><analisis/><texto/></documento>`. The **document-level**
`<texto>` carries the full body. (Beware: `<analisis>/<referencias>/<anterior>/<texto>`
also exists and is matched first by a naive `.//texto` — that trap cost me an hour.)

| Era | Id sampled | `<p>` in `<texto>` | Characters | Tables |
|---|---|---:|---:|---:|
| 1835 | `BOE-A-1835-2348` | 8 | 2,182 | 0 |
| 1855 | `BOE-A-1855-3318` | 5 | 950 | 0 |
| 1870 | `BOE-A-1870-4759` | 87 | 9,416 | 0 |
| 1880 | `BOE-A-1880-6366` | 335 | 47,548 | 0 |
| 1905 | `BOE-A-1905-2635` | 82 | 12,958 | 0 |
| 1922 | `BOE-A-1922-7310` | 28 | 3,818 | 0 |
| 1945 | `BOE-A-1945-7901` | 150 | 23,120 | 1 |
| 1955 | `BOE-A-1955-10057` | 829 | 103,178 | 0 |
| 1960 | `BOE-A-1960-10905` | 525 | 65,982 | 0 |
| 1965 | `BOE-A-1965-1` | 35 | 6,727 | 0 |
| 1970 | `BOE-A-1970-1000` | 336 | 62,867 | 0 |
| 1975 | `BOE-A-1975-11040` | 25 | 6,061 | 0 |
| 1978 | `BOE-A-1978-11099` | 20 | 3,289 | 0 |
| 1980 | `BOE-A-1980-10312` | 24 | 2,560 | 0 |
| 1985 | `BOE-A-1985-10478` | 26 | 4,896 | 0 |
| 1990 | `BOE-A-1990-10420` | 100 | 16,008 | 1 |
| 1995 | `BOE-A-1995-10360` | 30 | 5,108 | 0 |
| 2000 | `BOE-A-2000-1006` | 384 | 41,348 | 1 |
| 2010 | `BOE-A-2010-10103` | 718 | 95,935 | 2 |
| 2020 | `BOE-A-2020-10072` | 14 | 4,956 | 0 |
| 2025 | `BOE-A-2025-10488` | 199 | 55,607 | 0 |

**21 of 21 carry full text. Zero empty. Earliest tested: 1835.**

Those 21 are all documents that were *also* consolidated, so four more were pulled from
gazette summaries and checked specifically because they are **not** in `countries/es`:

| Id | From summary | `<p>` | Characters |
|---|---|---:|---:|
| `BOE-A-1979-89` | 1979-01-03 (76 items, 75 not in our corpus) | 8 | 629 |
| `BOE-A-1979-90` | 1979-01-03 | 9 | 1,478 |
| `BOE-A-2026-3291` | 2026-02-13 (203 items, 203 not in our corpus) | 19 | 4,191 |
| `BOE-A-2026-3292` | 2026-02-13 | 9 | 1,607 |

| Format | Endpoint | Docs reached | Unique | Note |
|---|---|---:|---:|---|
| **XML** | `/diario_boe/xml.php?id={id}` | **25/25 sampled, 1835–2026, consolidated and not** | **all** | full text + `<analisis>` reference graph |
| PDF | `metadatos/url_pdf` | all | 0 | the scanned/typeset gazette page |
| EPUB, ca/gl/eu/va PDF | `metadatos/url_*` | subset | 0 | translations and repackaging |

**Gate: passed.** One format carries 100 % of both shapes. Nothing else clears 1 % of
unique coverage, so nothing else needs a fetcher.

### What the diary XML means for the parser

Good news, and it is worth stating plainly because it decides how much new parser code
the re-emission needs.

- **The diary XML uses the same `p/@class` vocabulary as the consolidated XML.**
  Across the 21 era documents: `parrafo` 1,815, `articulo` 737, `parrafo_2` 594,
  `cuerpo_tabla_centro` 219, `capitulo` 133, `cuerpo_tabla_der` 96, `capitulo_num` 72,
  `capitulo_tit` 71, `cuerpo_tabla_izq` 54, `firma_ministro` 30, `centro_redonda` 28,
  `seccion` 27, `cabeza_tabla` 23, `firma_rey` 16, `titulo_tit`/`titulo_num`,
  `subseccion`, `anexo_num`/`anexo_tit`/`anexo`, `imagen`, `centro_cursiva`, `sangrado_2`.
  `markdown.py`'s existing map covers all of it — including the same `capitulo` gap
  (133 occurrences here, so **the bare-`capitulo` heading fix matters much more for the
  non-consolidated acts than for the consolidated corpus**).
- **Differences to plan for:**
  - No `<bloque>`/`<version>` wrapper — the text is a flat run of `<p>` under `<texto>`.
  - **No `<a>` elements at all** (0 across 21 documents). Cross-references live in
    `<analisis>/<referencias>/<anteriores|posteriores>` with `referencia=` attributes,
    not inline. The amendment graph is there; the inline links are not.
  - **No `<blockquote>` at all** (0 across 21). Quoted amending text in a
    non-consolidated act is indistinguishable from the act's own text by markup alone.
  - Metadata is richer than the consolidated catalogue: 32 fields plus a full ELI
    RDF block (`metadata-eli`), plus `<analisis>` with `materias`, `notas`,
    `referencias`, `alertas`.

---

## What to change in the re-emission

Ordered by measured impact, not by effort.

| # | Change | Evidence | Size |
|---|---|---|---|
| 1 | Stop Markdown claiming legal paragraph numbering (escape `N\. ` or emit differently) | 167,666 runs / 9,396 files (76.4 %) renumber on render | `markdown.py`, one branch |
| 2 | Map bare `p.capitulo`, `p.libro`, `p.parte` to headings | 32 + 5 in the consolidated sample; **133 `capitulo` in 21 diary docs** | `_SIMPLE_CSS_MAP`, 3 lines |
| 3 | Take `textoCompleto` out of `_STRIP_CLASSES` | 18 occurrences, 13/46 files (28.3 %) — corrección-de-errores provenance | 1 line |
| 4 | Handle `<img>` as a direct child of `<td>` in `_cell_text` | 10 of 11 images lost in `BOE-A-1968-963` | 2 lines |
| 5 | Emit `<caption>` as a paragraph above the table | 23/23 dropped, `BOE-A-2013-7540` | `_tables.py`, 4 lines |
| 6 | Empty header row when a table has no `<thead>` | 250 of 543 tables (46.0 %) get a data row promoted | `_tables.py`, 2 lines |
| 7 | Don't descend into nested tables (`iter` → scoped walk) | 1 of 178 tables (0.6 %) | `_tables.py`, 1 line |
| 8 | Escape `<` in body text so a law that quotes markup doesn't emit markup | 2 files | `markdown.py` |
| 9 | Extend the `<a>`-text id fallback to non-BOE gazette ids (`BON-`, `BORM-`, `DOGC-`…) | 49 of 3,869 (1.27 %), concentrated in `es-*` | `xml_parser._BOE_ID_RE` |

Items 1–3 are the ones that change what a reader sees on many files. Items 4–9 are
small, cheap, and only get a chance during a re-emission.

---

## Caveats

- **46 of 12,299 consolidated documents is 0.37 %.** Every per-file percentage from
  that sample carries the Wilson interval printed beside it; several are wide
  (`<caption>`: 2.2 %, CI 0.4–11.3). The corpus-wide numbers — every table in this
  document that says "of 12,299" — are exhaustive and carry no sampling error.
- **The sample is stratified, not random.** It over-weights old decades, tax/tariff
  titles and the six files a defect grep had already flagged. That biases *upward* the
  rate at which defects appear, and *downward* nothing. Treat the defect percentages as
  ceilings.
- **HEAD only.** The comparison is between the source's latest version of each block and
  the file at `origin/main`. Historical commits were not re-rendered and not compared;
  a fidelity defect that was fixed after a file's last commit would not show up here.
- **21 diary documents across 190 years is thin.** Full text was present in all of them
  and in the 4 never-consolidated ones, but a systematic year-by-year sweep (one
  `sumario` per year, count items whose `xml.php` has an empty `<texto>`) is the honest
  way to prove "no PDF-only era", and it costs ~200 requests.
- **`BON-n-1999-90001` was fetched and works**, so the consolidated API answers for
  autonomous-gazette identifiers too — but only one such id was tested.

## Open questions

1. Is the CommonMark renumbering (finding 3) actually visible on legalize.dev, or does
   the site's renderer already suppress it? That decides whether item 1 is urgent or
   merely correct. Cheap to check against one law with a run starting at 3.
2. The official Catalan/Galician/Basque/Valencian PDFs cover 24.5 %/19.3 %/4.6 %/2.9 %
   of the corpus. Are they in scope for `es` at all, or a separate product?
3. `<caption>` was found in exactly one document. Is it rare or is the sample blind?
   A cheap answer exists once a full fetch cache is rebuilt for the re-emission —
   grep the cache, don't re-fetch.
4. Non-consolidated acts have no inline `<a>` and no `<blockquote>`. What should a
   published non-consolidated file do about cross-references — synthesise links from
   `<analisis>/<referencias>`, or leave the text bare?

---

## Cost of this probe

| | Requests |
|---|---:|
| Wasted on a wrong path (`/api/...` instead of `/datosabiertos/api/...`, all 404) | 72 |
| Consolidated `/texto` sample | 46 |
| Diary `xml.php`, one per era 1835–2025 | 21 |
| Diary `xml.php`, never-consolidated documents | 4 |
| `sumario` (1979-01-03, 2026-02-13) | 2 |
| `act.php` HTML renderings | 2 |
| Catalogue head | 1 |
| **Total** | **148** |

76 × 200, 72 × 404, no 429, no 5xx. 23.7 MB. One request every 0.8–0.9 s.
The 72 wasted requests are why the consolidated sample is 46 documents and not 72;
the base URL is `https://www.boe.es/datosabiertos` and the API path hangs off it —
`engine/src/legalize/fetcher/es/config.py`, `BOEConfig.base_url`.
