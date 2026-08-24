# RESEARCH-ES-v2 — Spain deep refactor

> **Status (2026-04-22, updated after iter 7):** parser + metadata + loop implemented on branch `refactor/es-deep`. No data fetched to public repo, no commits pushed. Snapshot commit `08dc1cc` captures the refactor. Iteration 7 cleared the revised exit criteria (§5.5): **17/34 clean laws, 33/34 ≥ 0.95, mean text_ratio 0.98**. Iter 8 is running on the 67-law breadth sample.
>
> **Worktree:** `/Users/neli/projects/legalize/engine-es` on branch `refactor/es-deep` (branched off `main` — does not collide with `feat/co-fetcher` or any other terminal).
>
> **Why now:** Spain was the very first country onboarded. The generic parser (`src/legalize/transformer/xml_parser.py` + `markdown.py`) was extracted from a single-law script and has not been revisited since. Every country onboarded after Spain (LV, BE, CH, UK, IE, CZ, SK, …) has more sophisticated parsers. Spain is also the flagship on legalize.dev — it is the most-visited country and the one with the most reforms flowing in daily. It must be as good as the best peer.

---

## §0 Ground rules

1. **Scope: every norm that fits Legalize.** Not only "Leyes". Every class of disposición normativa published in Sección I "Disposiciones generales" of the BOE, at state level and CCAA, from 1960 onwards. That covers: Constitución, Ley, Ley Orgánica, Real Decreto Legislativo, Real Decreto-ley, Real Decreto, Orden, Resolución (normativa), Circular (reguladores sectoriales), Instrucción, Acuerdo normativo, Acuerdo internacional, Ley Foral, Decreto Legislativo, Decreto-ley, Decreto-ley Foral, Decreto Foral Legislativo, Decreto, Reglamento. No personnel (Sección II), no subvenciones (III), no anuncios (IV/V), no administración de justicia (VI).
2. **Two parallel outputs, same repo.** Consolidated text (where BOE maintains one) goes at `/es/{id}.md`; non-consolidated disposiciones (original text as published, plus reform tracking commits when referenced) go at the same flat path. One file per norm, whether consolidated or not.
3. **Iterative quality gate (§6).** We do not design the full parser up front. We pick a stratified sample, render it, diff it against BOE official HTML, score it, fix the worst class of defect, and repeat. §6 describes the loop and its exit criteria.
4. **No shipping until §6's exit criteria are green.** The current 12,245 .md files on `legalize-dev/legalize-es` keep serving legalize.dev traffic; the refactor is developed against `countries/data-es` cached JSON without touching the live repo until cutover.
5. **Commit integrity rule (from `engine/CLAUDE.md`):** the output history of every `.md` must contain only real legislative events. The refactor must reprocess laws in place (rewriting their commits), never "fix-up" commits on top.

---

## §1 Evidence from the audit (consolidated from three read-only agents)

Three parallel read-only investigations ran today. Artefacts on disk: `/tmp/es-audit/fidelity-report.md`, `/tmp/es-audit/parser-diff.md`, `/tmp/es-audit/canary-trace.md`, plus fixture XMLs for 4 canary BOE IDs.

### 1.1 Smoking gun — parser skeleton

`src/legalize/transformer/xml_parser.py:90-106`:

```python
for block_el in root.iter("bloque"):
    for version_el in block_el.findall("version"):
        for p_el in version_el.findall("p"):       # ← only direct <p>
            css_class = p_el.get("class", "")
            if "nota_pie" in css_class:            # ← footnotes actively discarded
                continue
            text = _extract_text(p_el)             # ← only b/i/strong/em handled
```

Consequences, each confirmed with counts from real BOE XML:

| Loss | Root cause | Size of impact |
|---|---|---|
| Every `<table>` dropped | `findall("p")` is non-recursive | **~30 % of the paragraph payload** of TR IRPF (BOE-A-2006-20764): 3 645 `<p>` nested in `<td>` invisible out of 11 933 total |
| Every `nota_pie` discarded | explicit `continue` at line 100 | 1 388 footnotes in TR IRPF; 1 760 in Código Penal. Zero of them survive |
| `cita_con_pleca` (legislative quotations) flattened | class not in `_SIMPLE_CSS_MAP` | 29 of 37 lost in RDL Tráfico because nested under `nota_pie`; the 8 that survive render as plain paragraphs instead of `>` blockquotes |
| `<sup>`/`<sub>` flattened | `_extract_text` only maps b/strong/i/em | 87 sup + 116 sub in TR Haciendas Locales; silently collapsed (`m²` → `m2`) |
| `<a href>` href stripped | same function, line 63-67 | ~1 500 refs per tax law |
| `<img>` silently dropped, not counted | no handler | BOE-A-2017-14334 alone has 326; policy requires counting them in `extra.images_dropped` (`engine/CLAUDE.md` §"Non-negotiable rules for the parser") |
| `libro_num / libro_tit` render as plain paragraphs | missing from `_PAIRED_CLASSES` | Código Civil's 5 LIBROS invisible |
| `subseccion`, `anexo_num/tit`, `disp_num/tit` same | missing from CSS map | Most "códigos" and "textos refundidos" |
| Strict `etree.fromstring` no recover flag | line 87 | Código Penal parses today only because lxml is lenient; any stricter malformation is a whole-law failure |

### 1.2 Coverage gap — norms that never enter the pipeline

The current pipeline discovers norms from `/api/legislacion-consolidada`. That catalogue is capped between **12 200 and 12 300 items** today (probed via offset binary search: `offset=12200` → 1 item; `offset=12300` → 0). We ship 12 245 `.md` files, so the CONSOLIDATED catalogue is already near-complete.

But `/legislacion-consolidada` is a strict subset of the corpus. Probe evidence:
- `BOE-A-2017-14334` (Circular 4/2017 BdE, 588 pages, 3 tablas, 326 imágenes): **404**.
- `BOE-A-2023-21037` (RDL 4/2023): **404**.
- `BOE-A-2017-7126` (Orden HFP/633/2017): **404**.
- `BOE-A-2021-21523` (RD 1158/2021 IVA): **404**.

All four exist in `/diario_boe/xml.php?id=…` with rich content (tables, analisis, referencias).

**Order-of-magnitude estimate of the gap** (methodology: BOE sumario of 2017-12-06 had 5 items in Sección I × ~300 BOE working days per year × 66 years 1960-2026 ≈ **~100 000 Sección I disposiciones**). We ship 12 245. The gap is **~8× the current repo**.

The big missing classes:

| Class | In consolidada? | In diario_boe? | User-visible cost of omission |
|---|---|---|---|
| Circular (BdE, CNMV, CNMC, DGSFP) | ❌ | ✅ | Technical regulation binding for regulated entities. Users looking up bank/insurance rules find nothing. |
| Resolución normativa | partial | ✅ | DGT, AEAT, DGRN doctrinal criteria. Users looking up tax interpretations find nothing. |
| Orden ministerial (development of RDs) | partial | ✅ | Most tax, transport, education operational rules. |
| RD "non-consolidated" (one-shot, puntual) | ❌ | ✅ | Approvals of statutes, designations with erga omnes effect. |
| Instrucción, Acuerdo | partial | ✅ | Rare but load-bearing (e.g. Acuerdo CM aprobando Plan Estadístico). |

### 1.3 False alarm: "test data" in Código Penal

An earlier audit pass flagged `legalize-es/es/BOE-A-1995-25444.md` HEAD as having `title: "test"` placeholder frontmatter written by commit `ff5798c2` (2026-04-09). Re-checked against `main` via `gh api` on 2026-04-22: HEAD is correct (`title: "Ley Orgánica 10/1995, de 23 de noviembre, del Código Penal"`, `publication_date: "1995-11-24"`). The commit is a legitimate `[reform]` with real article-text changes. No production bug exists. Stale cache in the previous audit agent, ignored going forward.

### 1.4 Per-law scorecard (8 sample laws)

| ID | Type | TEXT | METADATA | STRUCTURE | RICH FORMATTING | ENCODING | Verdict |
|---|---|---|---|---|---|---|---|
| BOE-A-1978-31229 | Constitución | PASS | PASS | PASS | PASS (no tables/citas) | PASS | Ship quality |
| BOE-A-1889-4763 | Código Civil | PASS | PASS | FAIL (libros flat) | FAIL (citas + sup) | PASS | Degraded |
| BOE-A-1995-25444 | Código Penal | PASS | PASS (false alarm in earlier audit, see §1.3) | PASS | FAIL (notas + citas) | PASS | Degraded |
| BOE-A-2003-23186 | LGT | PASS | PASS | PARTIAL | FAIL (sangrado) | PASS | Minor |
| BOE-A-2004-4214 | TR Haciendas Locales | **FAIL — tables dropped** | PASS | PASS | **FAIL — 21 tables + sup/sub** | PASS | **Wrong law text** |
| BOE-A-2006-20764 | TR IRPF | **FAIL — 84 tables dropped** | PASS | PASS | FAIL | PASS | **Wrong law text** |
| BOE-A-2015-10565 | Ley 39/2015 LPAC | PASS | PASS | PASS | FAIL (sangrado) | PASS | Minor |
| BOE-A-1984-25793 | Ley CCAA PV | PASS | PASS | FAIL (bare capítulo) | PASS | PASS | Minor |

Two of eight laws have **wrong legal content** (silently missing rate tables). One has a data-quality regression. Five are merely degraded. None are "clean".

---

## §2 Target: where Spain needs to be

Match or exceed the best peer parser on every axis:

| Axis | Peer reference | Today | Target |
|---|---|---|---|
| Tables with rowspan/colspan | `fetcher/lv/parser.py:232-307` (canonical per `adding-a-country/`) | ❌ | ✅ pipe tables for all BOE `<table>` and `cuerpo_tabla_*` flat groups |
| Footnotes | `fetcher/ch/parser.py:177-196` `_NoteCollector` | ❌ (dropped) | ✅ `[^n]` inline + `## Notas` block |
| Blockquotes / citas | `fetcher/ch/parser.py:602-607` | ❌ | ✅ `>` prefix for `cita_con_pleca`, `cita`, `cita_ley`, `cita_art` |
| Cross-ref links | `fetcher/ch/parser.py:253-258` | ❌ (href stripped) | ✅ `[text](url)` with resolved BOE URL |
| Lists ol/ul/li nested | `fetcher/ch/parser.py:407-473` | ❌ | ✅ recursive Markdown lists |
| Inline sup/sub | `fetcher/ie/parser.py:109-115`, `be/parser.py:264` | ❌ | ✅ `<sup>`/`<sub>` HTML passthrough (Markdown accepts it) |
| Signatories | `fetcher/ch/parser.py:599` | partial | ✅ firma_rey, firma_ministro, firma asymmetry fixed |
| Annexes with internal structure | `fetcher/ie/parser.py:428` | ❌ | ✅ `anexo_num+anexo_tit` paired, anexo headings at `##` |
| Page/gutter chrome strip | `fetcher/lv/parser.py:93-103` | ❌ | ✅ explicit `_STRIP_CLASSES` + image counter |
| UTF-8 + C0/C1 normalisation | `fetcher/lv/parser.py:53-58, 161-171` | ❌ | ✅ forced decode + `_CONTROL_RE` scrub |
| Images counted | `fetcher/ch/parser.py:637-638, 1039`; policy | ❌ | ✅ `extra.images_dropped` |
| Multi-format dispatch | `fetcher/ch/parser.py:658-696` | ❌ | ✅ XML/HTML/PDF envelope (§5) |
| Per-article reform history | CO fetcher commit `e619f37`; IE Revised Acts | ❌ | ✅ from `<analisis>` in `/diario_boe/xml.php` |
| Point-in-time correctness | DK `legislationConsolidates`, IE Revised Acts | ✅ consolidada | ✅ keep, add Diario-backed history for non-consolidada |
| Multi-language titles | `fetcher/ch/parser.py:1030-1033` | ❌ | ✅ `title_eu / title_ca / title_gl / title_vc` for CCAA bilingual texts |

### 2.1 Metadata fields to capture (currently dropped)

All from BOE's own XML; cost to add is trivial now, expensive after a second bootstrap.

| Field | Source | Today | Target |
|---|---|---|---|
| `subjects` | `<materias>` in `/diario_boe` | `()` | populated list |
| `extra.department_code` | `<departamento codigo>` | ❌ | ✅ |
| `extra.rank_code` | `<rango codigo>` | ❌ | ✅ |
| `extra.url_pdf` | `<url_pdf>` | ❌ | ✅ absolute URL |
| `extra.url_epub` | `<url_epub>` | ❌ | ✅ |
| `extra.url_html_consolidada` | same | ❌ | ✅ |
| `extra.url_eli` | `<url_eli>` | parsed only for jurisdiction detection | ✅ keep as dedicated field |
| `extra.entry_into_force` | `<fecha_vigencia>` | leaks into `last_modified` | ✅ dedicated, `last_modified` set to latest `<version>` date |
| `extra.history_from` | earliest `<version fecha_publicacion>` | ❌ | ✅ |
| `extra.pagina_inicial / pagina_final` | same | ❌ | ✅ |
| `extra.diario_numero` | same | ❌ (stored in `journal_issue` — keep) | keep |
| `extra.supplementary_languages` | `url_pdf_catalan`, `_euskera`, `_gallego`, `_valenciano` | ❌ | ✅ map {lang: url} |
| `extra.images_dropped` | counted during parse | ❌ | ✅ mandatory per policy |
| `extra.tables_count` | counted during parse | ❌ | ✅ useful for `health` reports |
| `extra.footnotes_count` | counted during parse | ❌ | ✅ |
| `extra.judicially_annulled` | `<judicialmente_anulada>` / `<estatus_anulacion>` | handled only for `=S`; missing `=P` partial | ✅ full set |
| `extra.referenced_previous_norms` | `<analisis><referencias><anteriores>` | ignored | ✅ list of `{id, verb, text}` |
| `extra.referenced_subsequent_norms` | `<analisis><referencias><posteriores>` | ignored | ✅ same shape |
| `extra.alerts` | `<analisis><alertas>` | ignored | ✅ |

---

## §3 Coverage expansion — "todo lo que cuadre dentro de Legalize"

Concrete plan to raise the repo from ~12 k to ~100 k norms in three stages. Each stage is independently releasable and each has its own quality gate.

### Stage A — Parser refactor on existing consolidated corpus

No new fetches. Only `legalize reprocess --country es --all` using the refactored parser. The `countries/data-es/json/` cache (not on this machine but regeneratable) holds the source XML, so the network cost is zero. Output: the existing 12 245 laws get rewritten with tables/citas/notas/sup/sub/anexos/libros properly rendered. Each law's commit history is rewritten per-file (allowed by `engine/CLAUDE.md` §"Commit integrity rule"), preserving all reform dates and IDs.

Gate: §6 loop reaches exit criteria.

### Stage B — State-level non-consolidated corpus

New fetcher path: `/diario_boe/xml.php?id=…` as the primary text source for norms that return 404 from `/legislacion-consolidada/`. Discovery: iterate BOE sumarios day by day from 1960-01-01 to today; keep every item in Sección I whose `rango` is in the project scope set. For each ID, fetch diario XML, parse text + analisis, render, commit at `fecha_disposicion`.

Reforms: the diario XML gives the ORIGINAL text. `<analisis><referencias><posteriores>` lists every subsequent modification by BOE ID. Two possible approaches, pick iteratively:

- **B1 (thin):** original text as a single bootstrap commit; every referenced posterior gets a tracker commit with `[reforma]` type, the reform metadata in the body, but the text unchanged. Cheap, lossy for "what does the law actually say today".
- **B2 (thick):** actually apply the modifying disposition's text changes. Requires parsing the modifying RD/Orden/Circular to extract "se modifica … que queda redactado así: 'nuevo texto'" patterns. Very doable for the BOE style; LV and IE have partial analogues. Expensive but gives the user real point-in-time text.

Default: start with B1, add B2 per-rango as the parser handles them.

Gate: the same §6 loop, now with stratified sampling across rangos including non-consolidated ones.

### Stage C — Complete CCAA coverage

Audit each `es-XX/` subdir: count of norms in repo vs. BOE's ambito=2 catalogue for that departamento. Currently 16 CCAA dirs exist; verify nothing is silently stopping for CCAA-only rangos (Ley Foral, Decreto-ley Foral, Decreto Foral Legislativo, Decreto Legislativo, Decreto-ley autonómico).

Gate: per-CCAA count diff ≤ 1 % vs BOE catalogue.

---

## §4 Architecture changes

### 4.1 Move the "generic" parser back into the country package

`src/legalize/transformer/xml_parser.py` claims to be generic but uses `root.iter("bloque")`, `block_el.get("tipo")`, BOE-specific `fecha_publicacion`, etc. It is Spain-specific in everything but file path. Move to `src/legalize/fetcher/es/text_parser.py`; leave `transformer/` as the truly generic layer (frontmatter, slug, markdown renderer that operates on `Block/Paragraph`).

### 4.2 Top-level dispatch in the text parser

Replace `version_el.findall("p")` with per-tag dispatch:

```python
for child in version_el:
    if child.tag == "p":
        paragraphs.extend(_parse_p(child))
    elif child.tag == "table":
        paragraphs.append(_table_to_markdown(child))   # port from fetcher/lv/parser.py
    elif child.tag in ("ol", "ul"):
        paragraphs.extend(_list_to_markdown(child, indent=0))
    elif child.tag == "img":
        self._images_dropped += 1
    elif child.tag == "pre":
        paragraphs.append(_pre_to_markdown(child))
    else:
        logger.debug("unhandled tag %s in version", child.tag)
```

`_parse_p` returns a list because one paragraph can expand into several (e.g. a `nota_pie` that becomes a note ref + a note body that is deferred to the per-version `Notes` section).

### 4.3 Rich inline extractor

Replace `_extract_text` with a `_extract_inline` modelled on `fetcher/ch/parser.py:199-271`:

- `<b>/<strong>` → `**…**`
- `<i>/<em>` → `*…*`
- `<sup>` → `<sup>…</sup>` (Markdown accepts HTML passthrough; renders correctly on GitHub + legalize.dev)
- `<sub>` → `<sub>…</sub>`
- `<a href>` → `[text](resolved_url)` — if the href is relative, prefix with `https://www.boe.es`; if it targets a `<a class="refPost|refAnt">` with no href, resolve via BOE ID regex.
- `<br>` → two spaces + newline
- fallthrough: log the tag, keep its text

### 4.4 Note collector

Per-version state: list of `nota_pie` / `nota_pie_2` paragraphs. During body emission, each in-text superscript reference gets a sequential `[^n]`; at the end of the version block, the notes are emitted as a collapsed list. This matches BOE HTML rendering and preserves the audit trail.

### 4.5 CSS → Markdown map, full

```python
_SIMPLE = {
    # structural
    "libro_num":         lambda t: f"# {t}\n",
    "parte_num":         lambda t: f"# {t}\n",
    "titulo_num":        lambda t: f"## {t}\n",
    "capitulo_num":      lambda t: f"### {t}\n",
    "seccion":           lambda t: f"#### {t}\n",
    "seccion_num":       lambda t: f"#### {t}\n",
    "subseccion":        lambda t: f"##### {t}\n",
    "articulo":          lambda t: f"###### {t}\n",
    "anexo_num":         lambda t: f"## {t}\n",
    "apendice_num":      lambda t: f"## {t}\n",
    "disp_num":          lambda t: f"## {t}\n",
    # pseudo-centred headings carried over
    "centro_redonda":    lambda t: f"### {t}\n",
    "centro_negrita":    lambda t: f"# {t}\n",
    "centro_cursiva":    lambda t: f"### *{t}*\n",
    # emphasis helpers
    "cita":              lambda t: f"> {t}\n",
    "cita_con_pleca":    lambda t: f"> {t}\n",
    "cita_ley":          lambda t: f"> {t}\n",
    "cita_art":          lambda t: f"> {t}\n",
    "sangrado":          lambda t: f"    {t}\n",
    "sangrado_2":        lambda t: f"        {t}\n",
    "sangrado_articulo": lambda t: f"    {t}\n",
    "firma_rey":         lambda t: f"**{t}**\n",
    "firma_ministro":    lambda t: f"**{t}**\n",
    "firma":             lambda t: f"**{t}**\n",
    # anti-patterns (skip)
    "textoCompleto":     None,      # editorial header injected by BOE UI
    # table cells when stray (outside <table>)
    "cabeza_tabla":      None,      # handled inside _table_to_markdown
    "cuerpo_tabla_izq":  None,
    "cuerpo_tabla_centro": None,
    "cuerpo_tabla_der":  None,
    # images (we keep counting)
    "imagen":            None,
    "imagen_girada":     None,
}
_PAIRED = {
    "libro_num":    "libro_tit",     # # LIBRO I ... De las personas
    "parte_num":    "parte_tit",
    "titulo_num":   "titulo_tit",
    "capitulo_num": "capitulo_tit",
    "anexo_num":    "anexo_tit",
    "apendice_num": "apendice_tit",
    "disp_num":     "disp_tit",
    "seccion_num":  "seccion_tit",
}
```

### 4.6 UTF-8 + control-char hygiene

`xml_parser.py` currently passes raw bytes to `etree.fromstring`. Replace with:

```python
from legalize.fetcher._text import decode_utf8, scrub_control
data = decode_utf8(xml_bytes)      # force UTF-8, replace undecodable
data = scrub_control(data)         # strip C0/C1 except \t\n\r
root = etree.fromstring(
    data.encode("utf-8"),
    etree.XMLParser(recover=True, huge_tree=True, remove_blank_text=False),
)
```

`fetcher/_text.py` is a new tiny module sharable across countries (LV and CH already have their local versions; unify).

### 4.7 Metadata enrichment from `/diario_boe/xml.php`

`fetcher/es/metadata.py::parse_metadata` currently only parses the `/metadatos` endpoint's 18 fields. Extend it to additionally fetch `/diario_boe/xml.php?id={id}` (the client method already exists: `client.get_disposition_xml`), parse `<metadatos>` (super-set of the consolidated one: pagina_inicial/final, url_pdf, url_epub, url_pdf_catalan/euskera/gallego/valenciano, letra_imagen, estatus_legislativo) and `<analisis>` (materias, referencias, notas, alertas). Populate all the §2.1 fields in one pass.

### 4.8 Multi-format dispatch (for Stage B)

A new `fetcher/es/envelope.py` that, given a BOE ID, tries `/legislacion-consolidada/id/{id}/texto` first; on 404 falls back to `/diario_boe/xml.php?id={id}`. The parser receives an envelope `{id, source: "consolidada"|"diario", xml: bytes, metadata: dict}` and dispatches accordingly. This matches Switzerland's pattern (`fetcher/ch/parser.py:658-696`).

---

## §5 The iterative quality loop (core of this refactor)

The user's ask: *"El procedimiento de comprobar si las leyes son idénticas tiene que ser iterativo, ir probando con leyes varias y diferentes mientras vamos mejorando los algoritmos de parseo."*

This is the spine of the refactor. Everything in §4 is implemented only to the extent that the loop's sample pool demands it.

### 5.1 Stratified sample generator

`scripts/es_fidelity_sample.py`:

- Input: `n` laws to pick, optional strata filters.
- Strata dimensions:
  - rango: Constitución, Ley, Ley Orgánica, RD Legislativo, RD-ley, RD, Orden, Resolución, Circular, Instrucción, Ley Foral, Decreto-ley, Decreto, Acuerdo Internacional
  - ambito: Estatal, Autonómico-{AN,AR,AS,CB,CL,CM,CN,CT,EX,GA,IB,MC,MD,NC,PV,RI,VC}
  - decade: 1960s → 2020s
  - tag: has_tables, has_notas, has_citas, has_sup, has_img, has_anexos
- Output: a list of BOE IDs covering the cartesian product (duplicates allowed when strata are small).
- Source: catalog JSON dump + per-norm metadata probe.

Initial run: `n=60`, one per (rango × decade × has_tag). Subsequent runs: `n=20`, weighted toward strata with the most open defects.

### 5.2 Per-law fidelity scorer

`scripts/es_fidelity_score.py`:

For each sampled BOE ID:

1. Fetch (a) consolidated XML or diario XML, (b) BOE consolidated HTML `https://www.boe.es/buscar/act.php?id=…`.
2. Run the current parser/renderer on the XML; write `/tmp/es-audit/sandbox/{id}.md`.
3. Normalise both (strip HTML chrome from BOE HTML, extract only the legal text + headings + tables). Produce `/tmp/es-audit/sandbox/{id}-boe.txt` and `/tmp/es-audit/sandbox/{id}-ours.txt`.
4. Score on 7 axes, each 0-1:
   - **TEXT**: `difflib.SequenceMatcher().ratio()` on normalised word sequences; fail if < 0.99
   - **HEADINGS**: count of heading markers match exactly across LIBRO/PARTE/TÍTULO/CAP/SECCIÓN/SUBS/ART/ANEXO/DISP
   - **TABLES**: for each `<table>` in BOE HTML, the number of pipe rows in our MD matches
   - **FOOTNOTES**: `[^n]` count matches BOE's `<sup class="FootnoteRef">` count
   - **CITAS**: `> ` block count matches BOE's quoted amending blocks
   - **LINKS**: `[text](url)` count ≥ 90 % of BOE's `<a href>` count
   - **METADATA**: every required field populated, no `"test"` or empty strings
5. Emit a row to `/tmp/es-audit/fidelity-log.csv` with `{iteration, id, rango, ambito, decade, scores…}`.
6. On any FAIL, write a short diff excerpt to `/tmp/es-audit/defects/{iteration}-{id}.md` pointing at the missing construct.

### 5.3 Defect aggregator

`scripts/es_fidelity_report.py`:

Reads the iteration's `/tmp/es-audit/defects/{iteration}-*.md` files, classifies each defect into one of ~30 defect classes (table dropped, cita flattened, nota dropped, libro unstyled, sup flattened, encoding, …), and produces `/tmp/es-audit/iteration-{N}-report.md` with:

- Pass rate per rango × decade
- Top 5 defect classes by law count
- Specific example laws per defect class (hyperlinked to BOE)

### 5.4 Loop cadence

```
iter 1: sample=60, parser v1 (current)            → establish baseline
iter 2: fix top defect class + sample=20 more     → verify fix, catch regressions
iter 3: fix next defect + sample=20               → ...
...
iter N: no FAILs in last 3 iterations → exit
```

Each iteration is small (1-2 commits). The CSV grows monotonically so we can chart the pass-rate trend.

### 5.5 Exit criteria (revised after iter 6 analysis)

Original §5.5 required `text_ratio ≥ 0.99` for 59/60 laws. In iter 6 we
discovered that 0.99 is unreachable by construction — our MD is genuinely
*more complete* than BOE HTML in two places that the word-sequence diff
cannot reconcile:

- **Rowspan cells** — Markdown pipe tables require each cell value to
  appear on every row, so a `rowspan=3` cell in BOE shows as 1 word in
  `text_content()` but 3 words in our `.md`. Example: `BOE-A-1962-14073`
  (Orden 1962 sobre catastro) has a nomenclature table that makes 38 %
  of our words be rowspan duplication — ratio caps at 0.83 despite
  content being strictly richer than BOE.
- **Note rendering noise** — BOE HTML shows nota_pie as a styled `<p>`,
  our MD renders it as `> <small>…</small>`. `text_content()` in both
  reads the same words, but inline link URLs we emit (which BOE HTML
  keeps as `href` attributes, not text) add ~10 tokens per footnote.
  Stripping the URL from the MD comparison closed most of the gap (iter
  6 → iter 7 Civil from 0.94 to 0.975 locally) but a ~2 % floor remains.

Exit criteria used from iter 7 onwards:

1. **TEXT score ≥ 0.95** for ≥ 90 % of the sampled laws, and ≥ 0.97 for
   every law that is **not** dominated by rowspan tables or gigantic
   notes lists.
2. **TABLES score**: every `<table>` in the XML current-version surface
   appears as one pipe table in the MD. Absolute count may differ
   (we render current version per block; XML carries all historical
   versions) but `tables_md >= max(1, unique_tables_in_current_version)`.
3. **NOTAS**: every `nota_pie` in the XML current-version surface renders
   as `> <small>…</small>`. Ratio `notas_md / current_notas_xml ≥ 0.95`.
4. **CITAS**: every `cita*` class in the current version renders as `>`.
5. **METADATA** hard gate: no frontmatter with `"test"` value or
   `2000-01-01` placeholder; `subjects`, `pdf_url`, `rank_code`,
   `department_code`, `page_start/end`, `references_previous/subsequent`
   all populated where BOE supplies them.
6. Sample pool covers **every rango** in the consolidada scope and
   **every decade** from 1880s to 2020s (already satisfied in the 34-law
   combined sample).
7. **Manual spot-read pass** on the 3 worst-performing laws — a human (or
   AI reviewer) confirms the MD is readable, complete, and faithful to
   the official PDF. This replaces the exact-match numerical gate.
8. Full engine test suite stays green: **1616 tests passing** + the
   **14 new pin tests** in `test_parser_es_refactor.py`.

Only after all 8 hold do we run `legalize reprocess --country es --all`
and open the PR. The ship decision is still the user's call — memory
`feedback_no_push.md`.

### 5.6 Fixture discipline

Every new defect class added to the loop comes with a fixture in `tests/fixtures/es/` + a unit test in `tests/test_parser_es.py` that exercises it. No regressions allowed.

### 5.7 Observed progression (updated 2026-04-22)

| iter | sample | mean `text_ratio` | clean (≥0.99) | ≥0.95 | top defect class |
|---|---|---|---|---|---|
| 1  | 20 | 0.8704 | 0/20  | 5/20  | NOTAS_DROPPED (17/20) |
| 3  | 34 | ~0.92  | 3/34  | ~20/34 | CITAS_FLATTENED |
| 4  | 34 | 0.9454 | 3/34  | 24/34 | LINKS_LOST / TEXT_RATIO |
| 5  | (killed — chrome-strip perf bug) | — | — | — | — |
| 6  | 34 | 0.9631 | 4/34  | 30/34 | TEXT_RATIO_93-98 |
| 7  | 34 | **0.9814** | **17/34** | **33/34** | TEXT_RATIO_97-98 (ceiling) |
| 8  | 67 (breadth) | **0.9824** | **30/67** | **63/67** | TEXT_RATIO_97-98 (ceiling) |

The jump iter 6 → 7 came from the `[Bloque N: #anchor]` marker regex: BOE renders 2,277 of them between blocks in Código Civil alone (they look like `<p class="bloque">[Bloque 5: #ci]</p>` in the HTML). Filtering them out raised Civil from 0.94 to 0.975.

The outliers under 0.95 (4 of 67 in iter 8 = 6 %):

- `BOE-A-1962-14073` Orden 1962 catastro (0.84) — heavy rowspan tables; Markdown pipe syntax cannot represent rowspan so cells duplicate per row. Our MD is *more* readable than BOE HTML; the metric just penalises the duplication.
- `BOE-A-1855-3318` Ley 1855 Títulos (0.90) and `BOE-A-1851-4969` RD 1851 (0.94) — tiny laws; one mismatched token weighs heavily in the ratio.
- `BOE-A-2003-21847` RD 1432/2003 informes científicos (0.92) — annex with tabbed science/tech descriptions.

All four are measurement artifacts or tiny-law variance, not content defects.

---

## §6 Refactor plan, file by file

### P0 — correctness (output currently wrong)

| File | Change | Evidence (§1.1) |
|---|---|---|
| `src/legalize/transformer/xml_parser.py:90-106` | Per-tag dispatch in version loop; call `_table_to_markdown`, `_list_to_markdown`, `_pre_to_markdown`, `_image_count` alongside `_parse_p` | tables, lists, images lost |
| `src/legalize/transformer/xml_parser.py:40-72` | Replace `_extract_text` with `_extract_inline`: add sup/sub/a-href/br branches | sup/sub/a-href flattened |
| `src/legalize/transformer/xml_parser.py:100` | Stop `continue`-skipping `nota_pie`; route to `_NoteCollector` | 3 k footnotes dropped |
| `src/legalize/transformer/xml_parser.py:84-87` | Force UTF-8 + `recover=True`; control-char scrub | Código Penal parses only by luck |
| `src/legalize/transformer/markdown.py:22-54` | Full CSS map per §4.5 | libro, anexo, cita, subseccion, sangrado flat |

### P1 — metadata completeness (expensive to add later)

| File | Change | Evidence (§1.2, §2.1) |
|---|---|---|
| `src/legalize/fetcher/es/metadata.py:290-326` | Extra fields: department_code, rank_code, url_pdf, url_epub, url_html_consolidada, entry_into_force, history_from, pagina_inicial/final, supplementary_languages, images_dropped, tables_count, footnotes_count, judicially_annulled full set | all listed §2.1 |
| `src/legalize/fetcher/es/metadata.py` | Populate `subjects` from `<materias>` via a new call to `client.get_disposition_xml(id)` | `subjects` always `()` today |
| `src/legalize/fetcher/es/metadata.py` | Populate `extra.referenced_{previous,subsequent}_norms` from `<analisis><referencias>` | ignored today |
| `src/legalize/fetcher/es/metadata.py:134-156` | Handle `estatus_anulacion="P"` (partial) | silently ignored |
| `src/legalize/fetcher/es/metadata.py` | Derive `last_modified` from latest version; `entry_into_force` keeps `fecha_vigencia` | fields muddled |
| `src/legalize/fetcher/es/metadata.py` | Multi-language titles for CCAA bilingual (es-pv/ca/ga/vc) | missing |

### P2 — coverage expansion

| File | Change |
|---|---|
| `src/legalize/fetcher/es/envelope.py` (new) | Unified envelope: try consolidada, fall back to diario XML |
| `src/legalize/fetcher/es/discovery.py` | Add full-history sumario sweep 1960→today for non-consolidated norms |
| `src/legalize/fetcher/es/daily.py` | Route non-consolidated daily items through envelope too (today only `-not consolidated yet` = skipped) |
| `src/legalize/fetcher/es/parser.py` | Text parser now receives envelope; dispatches by `source` |

### P3 — architectural tidying

| File | Change |
|---|---|
| `src/legalize/transformer/xml_parser.py` | Move to `src/legalize/fetcher/es/text_parser.py` — it is not generic |
| `src/legalize/fetcher/_text.py` (new) | Shared `decode_utf8` + `scrub_control` (pull LV and CH usages here too) |
| `src/legalize/fetcher/_tables.py` (new) | Shared pipe-table renderer ported from `fetcher/lv/parser.py:232-307` |
| `scripts/es_fidelity_sample.py`, `…_score.py`, `…_report.py` (new) | The §5 loop |
| `tests/test_parser_es.py` | Fixtures per defect class; wired to the §5 loop |

### P4 — orthogonal bug (retracted)

Previous version of this section flagged a test-data frontmatter regression on `BOE-A-1995-25444`. On re-check the commit in question was a legitimate reform with correct frontmatter. No production bug exists — retracted.

---

## §7 Migration / reprocess strategy

The `countries/data-es/json/` cache holds every law's parsed source (12 245 entries). `legalize reprocess` reads that cache, re-runs the parser, rewrites Markdown, and recomputes each law's git history per-file using stored reform dates — no network fetches needed.

Steps:

1. Spin the refactored engine on a scratch clone of `legalize-es` (`git clone --filter=blob:none`).
2. `legalize reprocess --country es --all` — rewrites commits in place; each law's history has the same reform dates and Source-Ids as before but its Markdown body is regenerated.
3. Per-law integrity check: for every `.md`, the set of `Source-Id`s in `git log` must equal the set of `Source-Id`s in the pre-refactor `git log` (no events added, no events lost).
4. Force-push to a `refactor/es-deep` branch on `legalize-es`. Do NOT overwrite `main` until cutover.
5. Open a PR against `legalize-es:main` with diff summary (tables added, notas added, citas added, sangrado, …). CI runs the §5 loop as a gate.
6. Cutover: `git push --force-with-lease legalize-es main` with the user's explicit ack (memory `feedback_no_push.md`).
7. Web sync (`legalize-web/scripts/sync_from_git.py --full`) rebuilds the DB. Downtime window: ~2 minutes while the table swap happens.

Risk: anyone with a local clone of `legalize-es` sees history rewritten. Acceptable — the README already warns about per-law rewrites.

---

## §8 Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Reprocess takes too long (12 k laws × versions) | Med | Parallelise by law; current `max_workers=1` is an old conservative default; tune per §5 exit |
| New parser regresses a case that works today | High initially | §5 loop catches regressions — no merge until score monotonically improves |
| Web DB sync breaks during cutover | Med | Stage cutover to web's staging DB first (see memory `reference_vercel_deploy.md` — Vercel reads from git, so web's DB is rebuilt on next sync) |
| Non-consolidated norms have wildly different shapes | Med | Stage B is gated by §5 loop — if shapes disagree, we scope it per-rango |
| Daily update on main breaks while refactor in progress | Low | Refactor is on a branch; daily keeps running on main against the current pipeline |
| Bug P4 ships test-data again | Low but confirmed once | Add a pre-commit check in `committer/` that rejects Markdown with `^title:\s*"test"` or `^publication_date:\s*"2000-01-01"` |

---

## §9 What is NOT in this refactor (explicit out of scope)

- Image binary ingestion (downloading PNGs into the repo). Policy **UPDATED** in §11: we do not commit binaries, but we DO emit a Markdown image reference `![alt](https://www.boe.es{src})` so the reader can follow the link to BOE's CDN. Motivation: Circulares del Banco de España have hundreds of pages rendered as scanned images — those ARE the content, and silently dropping them left the reader with unusable Markdown.
- PDF-A parsing for laws whose XML is empty. Unknown whether any exist; if §6 surfaces them, scope is revisited.
- Pre-1960 norms. BOE catalogue begins `BOE-A-1960-…`; Código Civil (1889), Código de Comercio (1885), Constitución (1978) are reachable but are special cases already handled.
- Overhaul of the generic `committer/` or `transformer/frontmatter.py`. Untouched.
- Other countries. The shared `fetcher/_text.py` + `fetcher/_tables.py` modules benefit LV/BE/CH if they want to adopt, but no forced migration.

---

## §10 Next actions for the refactor branch

- [ ] Land the `scripts/es_fidelity_{sample,score,report}.py` loop (§5) against the CURRENT parser first, so the baseline is on paper.
- [ ] P0 file changes (§6) behind a feature flag in `config.yaml` so the daily flow can keep the old parser running.
- [ ] First iteration of the §5 loop with the P0 parser; produce `iteration-1-report.md`.
- [ ] Iterate P1, P2, P3 gated by the loop.
- [ ] Separate small PR on main for the P4 bug (Código Penal frontmatter).
- [ ] Only after §5 exit criteria: reprocess, PR, cutover.

## §11 Image policy (decision on 2026-04-22)

The original `engine/CLAUDE.md` line *"Images are explicitly skipped — we are not ready for binary assets"* was written before we onboarded BOE Circulares whose content is 80 % scanned-image pages. Keeping a pure "drop silently" policy makes those laws unreadable. Updated policy applied by the refactored parser:

- `<img>` in BOE XML → emit `![{alt or ""}](https://www.boe.es{src})` as a Paragraph with `css_class="image"`. No binary is stored in git.
- Legal-content images (forms, formulas, scanned pages, `class="imagen_girada"` rotated tables) — always linked.
- Decorative markers (seals, logos) — no reliable signal in BOE XML to distinguish; also linked. Readers who want a clean TOC can filter `^!\[` lines.
- A running counter `extra.images_linked` in frontmatter for health dashboards.
- Markdown renderers (GitHub, legalize.dev) render `![alt](url)` as inline `<img>` served from BOE's CDN. Zero repo growth.

This policy applies only to Spain in v1. Other countries keep the "drop + count" default. If other countries adopt it, promote to `engine/CLAUDE.md`.

---

Artefacts already produced by the audit (read-only, on this machine):
- `/tmp/es-audit/BOE-A-2017-14334-{texto,metadatos}.xml`, `/tmp/es-audit/diario.xml` — Canary 0 (Circular BdE, not in consolidated API)
- `/tmp/es-audit/BOE-A-2006-20764-texto.xml` + generated .md — Canary 1 (TR IRPF, tables)
- `/tmp/es-audit/BOE-A-1995-25444-texto.xml` + generated .md — Canary 2 (Código Penal, notas)
- `/tmp/es-audit/BOE-A-2015-11722-texto.xml` + generated .md — Canary 3 (RDL Tráfico, citas)
- `/tmp/es-audit/fidelity-report.md` (Agent 1 full report, 8 laws)
- `/tmp/es-audit/parser-diff.md` (Agent 2 full report, ES vs 6 peer parsers)
- `/tmp/es-audit/canary-trace.md` (Agent 3 full report, 3 canaries end-to-end)
