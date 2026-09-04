# 04 — The format of the non-consolidated text (`diario_boe/xml.php`)

> Probe 4 of the redone Step 0 for the `es` republish. Read-only run, 2026-09-03.
> Question: is `https://www.boe.es/diario_boe/xml.php?id={id}` good enough to render at
> the standard of the playbook's priority 1 (tables as tables, bold as bold, no artifacts,
> UTF-8), and **from what year**?

## Verdict

**Yes, and the evidence is unusually strong: the `<texto>` of the diary XML is
character-for-character the same text the official BOE HTML page renders** (measured
identity ratio 1.0000 on 3 acts across three decades, §4). It carries the same
`<p class="…">` vocabulary as the consolidated XML, the same tables, the same
bold/italic/sup/blockquote/image markup. The existing paragraph dispatch in
`transformer/xml_parser.py` + `transformer/markdown.py` renders it with **zero residual
HTML tags and zero mojibake**, with no new element handlers needed.

**The hard floor is 1975.** In the sample, every Sección-I document from 1975 onward has a
populated `<texto>`; every one from 1972 and earlier has a literal `<texto/>` (empty) and
nothing but a PDF link. 1974 is a partial year (1 of 8 populated).

Three things are genuinely **lost** by taking the diary XML instead of the consolidated
one, and one thing is genuinely **gained but harmful if ignored**:

| | What |
|---|---|
| Lost 1 | The `<bloque>` / `<version>` skeleton. Today's `parse_text_xml()` returns **0 blocks** on a diary XML — it iterates `root.iter("bloque")` and there are none. A separate dispatch is mandatory, not optional. |
| Lost 2 | Cross-reference anchors. **0 `<a>` elements in 38 diary bodies**, vs 24 in one consolidated act alone. |
| Lost 3 | `nota_pie` / `nota_pie_2` — the amendment audit trail. It only exists in the consolidated surface. |
| Gained | Co-official language versions inline. One 2026 constitutional reform is the **same act five times** (es/eu/ca/gl/va) in one `<texto>`; Castilian is 22.3 % of it. Emit it naively and the file is 4.47× too big. |

---

## Method and HTTP budget

**141 requests** to `www.boe.es`: 135 × 200 and 6 × 404, every 404 an informative probe
(see below). User-Agent
`legalize-bot/1.0 (+https://github.com/legalize-dev/legalize)`, ≥0.7 s apart. No 429, no
5xx. Full log: `/Users/neli/.claude/jobs/5bf7ddf4/tmp/p4/requests.jsonl`.

| Phase | Requests | What |
|---|---|---|
| Sumario sampling | 17 | `/api/boe/sumario/{YYYYMMDD}` for 1960, 1968, 1970, 1972, 1974 (×3 dates), 1975 (×2), 1976, 1977, 1978, 1979, 1980, 1982, 1985, 1990, 1995, 2000, 2005, 2010, 2015, 2020, 2026 |
| Diary XML census | 38 | one `xml.php?id=` per act, 4 acts per sampled year 1979→2026, spread across each day's Sección I, plus the Constitution, the Código Penal and `BOE-A-2026-10881` |
| Floor sweep | 33 | `xml.php?id=` for the first Sección-I acts of 1968, 1970, 1972, 1974, 1975, 1976, 1977, 1980 |
| Consolidated comparison | 8 | `/api/legislacion-consolidada/id/{id}/texto` for acts also in the diary sample |
| Rendering comparison | 6 | `xml.php` + `diario_boe/txt.php` (the official HTML) for 3 acts |

The six 404s are findings, not errors:

- `/api/boe/sumario/19600105` → 404. The sumario API does not reach 1960.
- `/api/legislacion-consolidada/id/{id}/texto` → 404 for `BOE-A-1990-935`, `BOE-A-2000-1014`,
  `BOE-A-2010-836`, `BOE-A-2015-432`, `BOE-A-2026-1260`. **5 of 8** randomly-chosen Sección-I
  acts have no consolidated text at all — which is the gap issue #66 exists to close, and a
  reminder that the diary XML is the *only* surface for most of the corpus.

**Primary sample (S38):** 38 diary XMLs, ids listed in §1.2, drawn from Sección I
("Disposiciones generales") of one gazette day per sampled year. Rango mix: 12 Real
Decreto, 8 Ley, 5 Orden, 4 Resolución, 4 Corrección de errores, 2 Decreto, 1 Constitución,
1 Ley Orgánica, 1 Reforma constitucional.

**Caveat on reproducibility:** the raw XML of S38 was destroyed mid-run when a concurrent
agent cleared the shared scratch directory. The extracted per-document census survived
(`/Users/neli/.claude/jobs/5bf7ddf4/tmp/p4/census.json`, 38 rows with full tag counts) and
every number below is computed from it or from the 25 documents re-fetched into the private
directory `/Users/neli/.claude/jobs/5bf7ddf4/tmp/p4/raw/`. Nothing here is estimated from
memory.

---

## §1 Structure — is the *articulado* marked up?

### 1.1 Yes. The article tree is recoverable from `@class`, not from regex.

Across S38 the body is a flat run of `<p class="…">` siblings — there is no nesting — but the
classes name the hierarchy explicitly, and they are the **same vocabulary the consolidated
parser already maps**.

`<p class>` census over S38 (11,845 paragraphs total):

| class | count | % of `<p>` | docs (of 38) | in `markdown.py` map? |
|---|---:|---:|---:|---|
| `parrafo` | 5,419 | 45.7 % | 36 | falls through → plain paragraph (correct) |
| `parrafo_2` | 2,017 | 17.0 % | 29 | falls through → plain paragraph (correct) |
| **`articulo`** | **1,246** | **10.5 %** | **28** | ✅ `######` |
| `cuerpo_tabla_izq` | 907 | 7.7 % | 6 | in `_STRIP_CLASSES` — see 1.3 |
| `cuerpo_tabla_centro` | 595 | 5.0 % | 4 | idem |
| `sangrado` | 195 | 1.6 % | 5 | ⚠️ 4-space indent — see §5 D1 |
| `centro_redonda` | 194 | 1.6 % | 21 | ✅ `###` |
| `sangrado_2` | 175 | 1.5 % | 5 | ⚠️ 8-space indent — see §5 D1 |
| `capitulo_num` + `capitulo_tit` | 141 + 141 | 2.4 % | 7 | ✅ paired → `###` |
| `centro_cursiva` | 95 | 0.8 % | 7 | ✅ `### *…*` |
| `cuerpo_tabla_der` | 87 | 0.7 % | 1 | in `_STRIP_CLASSES` |
| `titulo_num` + `titulo_tit` | 63 + 63 | 1.1 % | 5 | ✅ paired → `##` |
| `anexo_num` + `anexo_tit` | 55 + 55 | 0.9 % | 8 | ✅ paired → `##` |
| `cabeza_tabla` | 55 | 0.5 % | 4 | in `_STRIP_CLASSES` |
| `seccion` | 52 | 0.4 % | 3 | ✅ `####` |
| `sangrado_articulo` | 49 | 0.4 % | 5 | ⚠️ 4-space indent |
| `firma_ministro` | 42 | 0.4 % | 18 | ✅ bold |
| `imagen` | 42 | 0.4 % | 3 | ✅ intercepted by `_parse_p` |
| `cita` | 40 | 0.3 % | 3 | ✅ `>` |
| `firma_rey` | 15 | 0.1 % | 15 | ✅ bold |
| `capitulo` (bare) | 14 | 0.1 % | 6 | ❌ **unmapped** → plain paragraph |
| `publicado` | 6 | 0.1 % | 6 | ❌ unmapped |
| `imagen_girada` | 6 | 0.1 % | 3 | ✅ intercepted |
| `libro_num`/`libro_tit`, `subseccion`, `anexo`, `titulo`, `centro_negrita`, `cita_con_pleca` | 3+3+3+2+1+1 | <0.1 % | 1–2 | ✅ mapped |
| legacy uppercase family (below) | 53 | 0.4 % | 2 | ❌ **unmapped** |
| `parrafo_custom` | 8 | 0.1 % | 1 | ❌ unmapped |
| `(none)` | 1 | 0.0 % | 1 | ❌ unmapped |

**Conclusion:** a parser recovers the article tree from `@class` alone. No regex fallback is
needed. `articulo` appears in 28 of 38 documents; the 10 without it are instruments that
genuinely have no articles — all 4 `Corrección de errores` in the sample are 2–4 paragraphs
of flat prose, and the rest are short Órdenes/Resoluciones.

### 1.2 Sample ids (S38)

```
1978: 31229
1979: 88, 94, 100, 106
1985: 805, 806
1990: 931, 932, 934, 935
1995: 1160, 1162, 1164, 1166, 25444
2000: 1001, 1005, 1010, 1014
2005: 893, 894, 895, 896
2010: 833, 834, 836, 837
2015: 432
2020: 848, 849, 850, 851
2026: 1255, 1257, 1259, 1260, 10881
```
(all prefixed `BOE-A-`)

### 1.3 A false alarm, checked and cleared

`_STRIP_CLASSES` in `xml_parser.py` drops `cabeza_tabla` / `cuerpo_tabla_*` paragraphs. In
the diary XML that is **safe**: all **1,644** such paragraphs in S38 are nested inside a
`<td>` or `<th>`, so they reach the renderer through `_cell_text` and their text survives
into the pipe table. Not one occurs standalone.

### 1.4 What the consolidated surface has that the diary does not

Measured on the three acts present in both surfaces:

| | `BOE-A-1978-31229` (Constitution) | `BOE-A-1979-88` (Ley 62/1978) | `BOE-A-2005-895` (RD 9/2005) |
|---|---|---|---|
| consolidated `<bloque>` | 210 (1 preámbulo, 24 encabezado, 184 precepto, 1 firma) | 23 | 22 |
| consolidated `<version>` | 214, 5 distinct `id_norma` | 42, 7 distinct `id_norma` | 24, 3 distinct `id_norma` |
| **diary `<bloque>` / `<version>`** | **0 / 0** | **0 / 0** | **0 / 0** |
| consolidated chars | 132,182 | 29,821 | 135,280 |
| diary chars | 113,963 | 15,941 | 80,445 |
| consolidated `<a>` | 4 | 24 | 3 |
| **diary `<a>`** | **0** | **0** | **0** |
| classes only in consolidated | `nota_pie`, `nota_pie_2` | `nota_pie`, `seccion` | `nota_pie`, `nota_pie_2`, `cuerpo_tabla_der`, `sangrado_2` |
| classes only in diary | `capitulo` | `capitulo_num`, `capitulo_tit`, `centro_redonda` | — |

Two things to read carefully here:

1. **The char difference is not truncation.** The consolidated text of Ley 62/1978 is 1.87×
   the diary text because it is the *current* text — 40 years of amendments folded in, plus
   19 `<blockquote>` and 17 `<strong>` of amendment provenance and 24 cross-ref anchors that
   the 1979 gazette page never had. The diary text is the act **as enacted**, which is
   exactly what issue #66 wants. This is a difference of *surface*, not of *quality*.
2. **`<a>` = 0 across the entire diary sample** (38 documents, every decade). The BOE only
   injects cross-reference anchors when it consolidates. Internal cross-links in
   non-consolidated files will have to be synthesised from `<analisis><referencias>`
   (which the diary XML *does* carry: 220 `<anterior>` and 225 `<posterior>` across S38) or
   not at all.

**Consequence for the code:** verified by running the real function read-only —

```
parse_text_xml(diario-BOE-A-2026-10881.xml) →  0 blocks
parse_text_xml(diario-BOE-A-2005-895.xml)  →  0 blocks
parse_text_xml(cons-BOE-A-2005-895.xml)    → 22 blocks, 24 versions
```

The envelope dispatch sketched in `RESEARCH-ES-v2.md` §4.8 is not a nicety — without it the
non-consolidated path silently emits empty files.

---

## §2 Rich content inventory

Element census inside `<texto>` over S38:

| Construct | Occurrences | Docs (of 38) | % of docs | Example id | Renderer verdict |
|---|---:|---:|---:|---|---|
| `<table>` | 129 | 12 | 32 % | `BOE-A-2026-1255` (75 tables) | ✅ `_tables.render_table` |
| `<td>` / `<tr>` / `<th>` | 11,590 / 2,461 / 849 | 12 | 32 % | `BOE-A-2020-850` (4,588 td) | ✅ |
| `rowspan` / `colspan` | 442 / 165 | — | — | `BOE-A-2005-895` | ✅ expanded into the grid |
| `<thead>`/`<tbody>`/`<tfoot>` | 119 / 122 / 10 | — | — | — | ✅ `<thead>` promotes the header row |
| **`<caption>`** | **67** | **1** | **3 %** | `BOE-A-2026-1255` | ❌ **dropped** — see §5 D2 |
| `<colgroup>` / `<col>` | 91 / 549 | — | — | — | ignored (width hints, no content) |
| `<em>` / `<i>` | 102 | 3 | 8 % | `BOE-A-2020-850` (`bonus`, `quater`) | ✅ `*…*` |
| `<strong>` / `<b>` | 15 | 1 | 3 % | `BOE-A-2026-10881` (`Artículo único.`) | ✅ `**…**` |
| `<blockquote>` | 53 | 4 | 11 % | `BOE-A-2000-1014`, `BOE-A-2026-1257` | ✅ `_parse_blockquote` |
| `<sup>` | 75 | 2 | 5 % | `BOE-A-2000-1014` (ordinal `n.º`) | ✅ HTML passthrough |
| `<sub>` | 0 | 0 | 0 % | — | n/a |
| `<img>` | 50 | 5 | 13 % | `BOE-A-2020-849` (37 imgs) | ✅ CDN-linked, policy §11 |
| `<br>` | 14 | 2 | 5 % | `BOE-A-1978-31229` | ✅ hard break |
| **`<a>`** | **0** | **0** | **0 %** | — | nothing to render |
| **`<ol>`/`<ul>`/`<li>`** | **0** | **0** | **0 %** | — | lists are flat `parrafo_2`/`sangrado` |
| `<pre>` | 0 | 0 | 0 % | — | n/a |
| MathML / TeX | 0 | 0 | 0 % | — | formulas ship as `<img>` |

Notes with evidence:

- **Images are BOE-hosted PNGs, not scans of whole pages.** All 48 with a `src` point at
  `/datos/imagenes/disp/{year}/{issue}/{doc}_{n}.png`, `class="frame-1"`/`"frame-2"`, e.g.
  `/datos/imagenes/disp/2020/18/00849_13754.png`. They are figures, formulas and signature
  rubrics embedded in the disposition. Two `<img>` in `BOE-A-2005-894` have an **empty
  `src`** and are silently dropped by `_image_paragraph` — correct behaviour, but it means
  ~4 % of images in that sample carry no target.
- **Blockquotes hold verbatim amending text**, always quoted with «…», e.g.
  `BOE-A-2000-1014` → `«Artículo 7. Tipo de gravamen. El tipo de gravamen será del 20 por 100.»`
  with 1–22 `<p>` inside. `_parse_blockquote` already forces the `> ` prefix on these.
- **`<sup>` is almost entirely the Spanish ordinal marker** (`o`, `º` in `n.º`), not
  footnote references. There are **no footnote markers and no footnote blocks** in the diary
  XML — `nota_pie` exists only on the consolidated surface.
- **`<strong>` is a modern convention.** It appears in exactly one document, the 2026
  constitutional reform, wrapping the article headings. Pre-2020 the BOE marked headings by
  `@class` only. Both survive rendering.

---

## §3 The hard floor: from what year is the XML usable?

The failure mode is unambiguous and easy to detect: the document is served 200, the
metadata block is complete, and the body is a literal self-closing `<texto/>` — zero
characters, zero `<p>`, zero `<img>`. Only `url_pdf` points at content:

```xml
<documento fecha_actualizacion="20241014210044">
  <metadatos>
    <identificador>BOE-A-1968-642</identificador>
    ...
    <url_pdf>https://www.boe.es/boe/dias/1968/06/04/pdfs/A08048-08048.pdf</url_pdf>
  </metadatos>
  <texto/>
</documento>
```

There is **no** intermediate "scanned-image body" state: it is either full text or nothing.

### 3.1 Measured, Sección I only

| Year | Docs sampled | With text | Empty `<texto/>` | Chars observed |
|---|---:|---:|---:|---|
| 1960 | — | — | — | `/api/boe/sumario/19600105` → **404**; the sumario API does not reach 1960 |
| 1968 | 1 | 0 | 1 | 0 |
| 1970 | 3 | 0 | 3 | 0, 0, 0 |
| 1972 | 2 | 0 | 2 | 0, 0 |
| 1974 | 8 | **1** | 7 | 41,156 and seven zeros |
| **1975** | **4** | **4** | **0** | 11,535 · 20,006 · 20,833 · 1,718 |
| 1976 | 3 | 3 | 0 | 56,573 · 2,265 · 1,446 |
| 1977 | 3 | 3 | 0 | 13,000 · 3,042 · 6,344 |
| 1978 | 1 | 1 | 0 | 113,963 (Constitution, 800 `<p>`) |
| 1979 | 4 | 4 | 0 | 15,941 · 968 · 3,695 · 1,746 |
| 1980 | 3 | 3 | 0 | 3,310 · 2,516 · 1,808 |
| 1982 → 2026 | 30 | 30 | 0 | see S38 census |

Dates sampled: 1968-06-04, 1970-01-20, 1972-01-18, 1974-01-15 / 1974-07-01 / 1974-12-02,
1975-01-07 / 1975-06-02, 1976-01-20, 1977-06-02, 1978-12-29, 1979-01-03, 1980-01-15,
1982-01-19, then the S38 dates.

### 3.2 The answer, with its uncertainty

> **1975.** From 1975-01-07 onward, every Sección-I document sampled has a populated
> `<texto>` (16 of 16 across 1975–1980). Before 1974, none does (6 of 6 empty across
> 1968–1972).

1974 is the transition year and it is **not a clean cut**: on 1974-12-02, the *Acuerdo
Internacional* `BOE-A-1974-1930` has 41,156 characters of text while the two Órdenes
published the same day (`-1931`, `-1932`) are empty. Digitisation in 1974 appears to have
been selective by importance of the instrument, not by date.

**Uncertainty, stated honestly.** The per-year sample is 1–8 documents. This is enough to
place the boundary in 1974–1975 with confidence, and *not* enough to guarantee there is no
scattered hole in, say, 1983. A cheap and decisive verification exists and should be run
before committing to a scope: sweep `xml.php` for every Sección-I id of one gazette day per
month from 1974 to 1985 (≈130 sumarios + ≈1,500 documents) and count empty `<texto/>` per
month. Until that runs, treat 1975 as the floor and **assume nothing about completeness
between 1975 and 1982**, where my sample is 1–4 documents per year.

### 3.3 What the corpus looks like below the floor

Below 1975 the pipeline would have metadata (title, department, rango, dates, ELI,
`<analisis>` materias and referencias — all present and populated in the 1968 sample) and a
PDF URL, but **no text**. Three options, none of them free:

- Exclude pre-1975 entirely. Clean, and the honest default.
- Emit metadata-only stubs with a link to the PDF. Cheap, but it puts thousands of empty
  laws in a corpus whose whole promise is the text, and the search index would be poisoned.
- OCR the PDFs. Not a Legalize pipeline; the playbook lists PDF scraping as a last resort
  used by exactly one country, and BOE's pre-1975 PDFs are scans of hot-metal typesetting.

Recommendation: **hard floor at 1975-01-01**, documented in `RESEARCH-ES.md` as a source
limitation, with the 1974 partial year excluded for consistency.

---

## §4 Rendered comparison against the official BOE page

For three acts spanning three decades I fed the `<texto>` children straight through the
**existing, unmodified** dispatch (`_parse_p`, `_table_paragraph`, `_parse_blockquote`,
`_image_paragraph`, then `render_paragraphs`) and compared the result to
`https://www.boe.es/diario_boe/txt.php?id=…` — the official HTML rendering of the same act.

| Act | Year | `<texto>` chars | Official HTML chars | Text identity | Markdown chars | Residual HTML tags | Mojibake |
|---|---|---:|---:|---:|---:|---:|---:|
| `BOE-A-2026-10881` (Reforma constitucional, tables + bold + images) | 2026 | 41,450 | 41,450 | **1.0000** | 42,285 | 0 | 0 |
| `BOE-A-1990-931` (Real Decreto, quoted amending text) | 1990 | 8,119 | 8,119 | **1.0000** | 8,386 | 0 | 0 |
| `BOE-A-1979-88` (Ley 62/1978, sections + articles) | 1979 | 15,581 | 15,581 | **1.0000** | 15,811 | 0 | 0 |

Identity ratio = `difflib.SequenceMatcher` matching-block coverage of the normalised
`<texto>` text against the normalised text of the official page (NFC, quote marks folded,
whitespace collapsed). The lengths are *equal*, not merely close: `xml.php` is the source
the BOE's own HTML view is generated from. Not one unhandled element type appeared in any of
the three.

### 4.1 What the Markdown actually looks like

`BOE-A-1979-88`, 1979 — correct out of the box:

```markdown
De conformidad con la Ley aprobada por las Cortes, vengo en sancionar:

###### Artículo primero.

Uno. El ejercicio de los derechos fundamentales de la persona, comprendidos en el ámbito…

### SECCIÓN PRIMERA. Garantía jurisdiccional penal

###### Artículo segundo.
```

`BOE-A-2026-10881`, 2026 — headings, bold and the signature table:

```markdown
###### **Artículo único.**
...
**FELIPE R.**

| El Presidente del Gobierno, |  | ![](https://www.boe.es/datos/imagenes/disp/2026/123/10881_17020546_1.png) |
| --- | --- | --- |
| ![](…10881_17020545_1.png) |  | ![](…10881_17020546_1.png) |
| PEDRO SÁNCHEZ PÉREZ-CASTEJÓN |  | ![](…10881_17020546_1.png) |
```

`BOE-A-1990-931`, 1990 — **the one place it fails**:

```markdown
El artículo 6.º del Real Decreto 2352/1986 … queda redactado en los siguientes términos:

        «Uno. La Secretaría General Técnica tiene a su cargo el estudio, informe, …
```

Eight leading spaces. In Markdown that is an indented code block: the quoted new wording of
the article renders in a monospace box with a horizontal scrollbar. See §5 D1 — this is a
**pre-existing defect of the consolidated corpus too**, and the diary path makes it worse
because the diary XML wraps quoted amending text in `sangrado_2` without a `<blockquote>`
(`BOE-A-1990-931`: 5 `sangrado_2`, 0 `<blockquote>`).

### 4.2 Fidelity verdict against priority 1

| Requirement | Verdict |
|---|---|
| Tables render as tables | ✅ pipe tables, rowspan/colspan expanded, `<thead>` honoured. ⚠️ `<caption>` lost (D2); rowspan on signature images duplicates the same image 3× (D3) |
| Bold as bold, italic as italic | ✅ `<strong>`→`**`, `<em>`→`*`, verified in output |
| No leftover HTML/XML tags | ✅ 0 in all three renders |
| No mojibake | ✅ 0 `Ã`, 0 U+FFFD, 0 `&#` in all three renders |
| No truncated sentences / swallowed whitespace | ✅ identity ratio 1.0000 against the official page |
| UTF-8 always | ✅ `fetcher/_text.clean()` already forces it |
| **Structure preserved** | ⚠️ headings yes; **indentation classes break it** (D1) |

**It reaches the bar, with four fixes.** None of the four is new work invented by this
probe — D1 and D2 are latent in the consolidated pipeline today.

---

## §5 Defects the re-emission must fix

Ordered by how much of the corpus they touch.

### D1 — `sangrado*` renders as a Markdown code block · **already shipped, 79,176 lines**

`markdown.py` maps `sangrado`→4 spaces, `sangrado_2`→8, `sangrado_articulo`→4.
`render_paragraphs` puts a blank line between every paragraph, so **every one of these
becomes an indented code block**.

Measured on the published corpus at `countries/es@origin/main`:

| Measurement | Value | How |
|---|---:|---|
| `es/*.md` files with ≥1 line starting with 4+ spaces | **1,152 of 8,690 (13.3 %)** | `grep -lE '^    [«A-ZÁÉÍÓÚa-z]' es/*.md` |
| Total such lines in `es/` | **79,176** | `grep -hcE '^    \S' es/*.md \| paste -sd+ \| bc` |
| Example | `es/BOE-A-1977-6061.md` line 495: `    «Artículo doscientos veintidós.` | |

In the diary corpus the exposure is higher, because quoted amending text arrives as bare
`sangrado_2` with no `<blockquote>` wrapper: 195 `sangrado` + 175 `sangrado_2` + 49
`sangrado_articulo` across S38, in 5 documents each.

Fix: render indentation as nested blockquote or as a non-breaking-space prefix — anything
but leading spaces. It is a one-line change in three map entries and it is only affordable
during a full re-emission, which is exactly what is happening.

### D2 — `<table><caption>` is dropped · 67 occurrences in 1 of 38 documents

`fetcher/_tables.render_table` iterates `table_el.iter()` for `tr` only. A `<caption>` never
reaches the output. In `BOE-A-2026-1255` (DGT road-closure resolution) the captions are the
row-group labels and carry the operative meaning:
`"Todos los viernes comprendidos entre enero y marzo…"`, `"Miércoles 18 de marzo (San José)"`.
Without them the table is 75 unlabelled grids.

Fix: emit the caption as a bold line above the pipe table. `render_table` is shared by every
country, so this fixes it everywhere at once.

### D3 — rowspan expansion duplicates signature images

`render_table` deliberately "repeats cell content into the expanded grid". For a legal
table that is right. For a BOE signature block — which is laid out as a table — it prints the
same rubric PNG three times (`BOE-A-2026-10881`, §4.1). Low severity, cosmetic, but visible
at the end of nearly every act with a graphic signature.

### D4 — co-official language versions inflate every organic law · **4.47× on the measured act**

`BOE-A-2026-10881` is published in Castilian, Basque, Catalan, Galician and Valencian, all
five inside one `<texto>`. The consolidated API returns Castilian only; the diary XML does
not.

| Measurement | Value |
|---|---:|
| Rendered Markdown, whole document | 42,285 chars / 236 lines |
| Castilian portion (lines 1–65) | 9,450 chars |
| **Castilian share** | **22.3 %** |
| **Duplication multiplier** | **4.47×** |

Detectable structurally: each translation opens with an italic-centred preamble heading
(`### *HITZAURREA*`, `### *PREÀMBUL*`, `### *PREÁMBULO*`) emitted from
`<p class="centro_cursiva">`, at lines 66, 110, 154, 198. Also visible in the metadata —
`<url_pdf_catalan>`, `<url_pdf_euskera>`, `<url_pdf_gallego>`, `<url_pdf_valenciano>` are
populated exactly for these documents.

Decide deliberately: split into per-language files, keep Castilian and drop the rest, or
keep everything. Do not let it happen by accident — organic laws and constitutional reforms
are the most-read documents in the corpus and this is a 4× size penalty on precisely those.

### D5 — legacy uppercase `@class` families are unmapped · 53 paragraphs in 2 of 38 documents

Two 2005 documents were typeset from a different template and carry:

```
ATEXTO_NORMAL (21)  RBF_SFRANySIG_ARTICULO (12)  ATEXTO_BLANCO_6 (6)
ATEXTO_BLANCO_4 (4)  RBF_SFRAN_SOLA (3)  ATEXTOySIG_BL_6 (2)  RBC_RED_CENTRO (2)
RVD_FIRMA (1)  FIRMA_MINISTRO (1)  LINEA_ANEXO (1)
```

Ids: `BOE-A-2005-893`, `BOE-A-2005-894`. All fall through to "unknown class → plain
paragraph", so `RBF_SFRANySIG_ARTICULO` — plainly an article heading — renders as body text,
and `FIRMA_MINISTRO` misses the lowercase `firma_ministro` key by case alone.

Cheapest correct fix: lowercase the class before lookup (catches `FIRMA_MINISTRO` for free),
then add the ~10 legacy aliases. Also unmapped and worth one line each: `capitulo` (bare, 14
occurrences in 6 documents — currently loses a chapter heading), `publicado` (6),
`parrafo_custom` (8).

**Unknown-class monitoring is the real fix.** These two documents are 5 % of a 38-document
sample; the full non-consolidated corpus is orders of magnitude larger and will contain
template families this sample never saw. The reprocess should log and count every unmapped
`@class` and fail a threshold, rather than silently degrading them to plain paragraphs.

### D6 — no cross-reference anchors in the non-consolidated surface

0 `<a>` in 38 documents. The consolidated files have them (`refAnt`/`refPost`), so a mixed
corpus will have clickable cross-references in the consolidated half and none in the other.
The `<analisis><referencias>` block *is* present in the diary XML (220 `<anterior>` +
225 `<posterior>` across S38, plus 341 `<materia>` and 24 `<nota>`), so the links can be synthesised at the
document level even if not at the sentence level.

---

## §6 What this means for the code

1. **A second dispatch is mandatory.** `parse_text_xml()` returns 0 blocks on a diary XML.
   Either the envelope of `RESEARCH-ES-v2.md` §4.8, or a `parse_diario_xml()` that wraps the
   flat `<p>` run in a single synthetic `Block` with one `Version` dated at
   `<fecha_disposicion>`. The paragraph-level dispatch itself is reusable **verbatim** — this
   probe proved that by rendering three acts with it and changing nothing.
2. **The `text_state` override is trivially decidable at parse time.** The diary XML has no
   `<version>` elements at all; the consolidated one does. `text_state = AS_ENACTED if
   surface == "diario" else POINT_IN_TIME` — the mirror image of the `pt` line at
   `fetcher/pt/parser.py:856`, exactly as planned.
3. **Fix D1 and D2 in the shared code, not in the `es` parser.** `markdown.py` and
   `_tables.py` are used by every country; both defects are shipped in all of them.
4. **The floor belongs in `config.yaml`, not in the fetcher.** 1975-01-01 as a discovery
   lower bound, with a comment pointing at §3 of this file.

---

## §7 Caveats and open questions

**Caveats**

1. Per-year samples in §3 are 1–8 documents. The 1974/1975 boundary is solid; per-year
   completeness between 1975 and 1982 is not established.
2. S38 is one gazette day per year. A day is a natural cluster — the same ministry, the same
   typesetting batch — so the class census may under-represent rare templates. The 2005
   legacy family (D5) showed up in *both* documents from a single ministry on a single day,
   which is exactly this effect.
3. The rendering comparison is 3 acts, not 30. Identity 1.0000 on all three is strong, but it
   compares the XML text to the BOE's *own HTML*, not to the PDF. If the BOE's HTML view has
   a defect relative to the printed gazette, this measurement inherits it.
4. Raw XML for S38 was destroyed mid-run by a concurrent agent clearing the shared scratch
   directory; the derived census survived and the 25 documents used for §3.1, §4 and §5 were
   re-fetched into a private directory. No number here was reconstructed from memory, but
   S38's raw files cannot be re-inspected without re-fetching.

**Open questions**

1. Is there a hole in the 1975–1982 text coverage? (≈130 sumarios + ≈1,500 `xml.php` calls
   settles it; the check is one script and one afternoon of polite rate-limiting.)
2. How often does the co-official multiplication (D4) occur across the whole
   non-consolidated corpus? It is detectable from the catalogue alone —
   `url_pdf_catalan`/`_euskera`/`_gallego`/`_valenciano` non-empty — with **zero** extra
   text fetches.
3. How large is the unmapped-`@class` long tail over 100k+ documents? Unknowable from 38.
   Instrument the reprocess.
4. Do `<img>` with an empty `src` (2 of 50 in S38) have a recoverable target elsewhere in
   the document, or are they genuinely dead in the source?
5. `BOE-A-1974-1930` has text while its same-day siblings do not. Is 1974 coverage a
   function of rango (international agreements re-keyed first), or of a later ad-hoc
   digitisation project? If the former, a rango-filtered 1974 might be worth including.
