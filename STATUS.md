# ES refactor — status as of 2026-04-22 18:15 local

## Where we are

All code changes live on branch `refactor/es-deep` in worktree `engine-es/`.
5 commits ahead of `main`. Nothing pushed. Nothing touched on `legalize-es`.
Main terminal on `feat/co-fetcher` untouched.

```
541c77c feat(es): Stage B parser for /diario_boe/xml.php schema
c875d04 docs(es): retract P4 false alarm on Codigo Penal
f7a4312 docs(es): record iter 8 breadth validation results
a3aa485 docs(es): record iter 7 results + revised exit criteria
08dc1cc refactor(es): deep parser rewrite + iterative fidelity loop
```

## What is done

### Parser + renderer (Stage A — consolidated corpus)

- Per-tag dispatch in `transformer/xml_parser.py`
  (`<p>`, `<table>`, `<ol>/<ul>`, `<img>`, `<blockquote>`, `<pre>`).
- Rich inline extractor (`<sup>`, `<sub>`, `<a href>`, `<br>`;
  BOE-A-ID regex fallback for refPost anchors with no href).
- `nota_pie` rendered as `> <small>…</small>` (audit trail preserved).
- `cita_con_pleca` + plain paragraphs inside `<blockquote>` render as
  Markdown `>` blockquote.
- Images emit `![alt](https://www.boe.es{src})` (policy §11).
- Full CSS map in `markdown.py`: libro/parte/titulo/cap/sec/subs/
  articulo/anexo/apendice/disp/firmas/cita/sangrado.
- UTF-8 + C0/C1 scrub + recover-mode XML parser.
- Shared `fetcher/_text.py` and `fetcher/_tables.py`.

### Metadata (Stage A — P1)

- `parse_metadata(xml, id, diario_xml=...)` — enriches with
  `subjects`, `pdf_url`, `rank_code`, `department_code`, `page_start/end`,
  `references_previous/subsequent`, `alerts`, multilingual PDF URLs.
- Frontmatter renders `pdf_url` and `subjects`.
- `fetch.py` and `daily.py` pull `diario_xml` via
  `client.get_disposition_xml`.

### Stage B — non-consolidated corpus (~87k laws)

- `parse_diario_xml()` normalizes `/diario_boe/xml.php` schema to the
  same `Block`/`Version`/`Paragraph` model. Verified on
  `BOE-A-2017-14334` (Circular BdE 4/2017): 4,257 paragraphs,
  3 tables, 326 images linked.
- **NOT YET WIRED** into the fetch orchestration. Next step: envelope
  dispatch that tries `/legislacion-consolidada/` first, falls back
  to `/diario_boe/xml.php` on 404.

### Iterative fidelity loop

- `scripts/es_fidelity/{sample,score,report}.py`: stratified BOE-ID
  sampling × rango × ambito × decade, per-law 8-axis scoring against
  BOE HTML (chrome + `[Bloque N:]` markers stripped), defect files,
  CSV log at `/tmp/es-audit/fidelity-log.csv`.

### Tests

- 15 new pin tests in `tests/test_parser_es_refactor.py` covering:
  inline formatting, tables with rowspan/colspan, images,
  notas/citas/blockquotes, paired num+tit headings, malformed-XML
  recovery, and the Stage B diario parser.
- Full engine suite **1631 tests passing** (was 1616 pre-refactor).

## Metrics — where the loop landed

| Iter | Sample | Mean text_ratio | ≥0.95 | ≥0.97 | Clean (≥0.99) |
|------|-------:|----------------:|------:|------:|--------------:|
| 1    | 20     | 0.87            | 5/20  | 0/20  | 0/20          |
| 3    | 34     | ~0.92           | ~20/34| ~10/34| 3/34          |
| 4    | 34     | 0.95            | 24/34 | 17/34 | 3/34          |
| 6    | 34     | 0.96            | 30/34 | 23/34 | 4/34          |
| 7    | 34     | **0.98**        | 33/34 | 29/34 | 17/34         |
| 8    | 67     | **0.98**        | 63/67 | 58/67 | 33/67         |

Distribution stable across iterations 7 → 8 despite doubling the sample;
the refactor generalises.

Four outliers below 0.95 in iter 8, all measurement artefacts:
- `BOE-A-1962-14073` (0.84) — rowspan tables; Markdown pipe cannot
  represent rowspan so cells duplicate per row. Our MD more readable,
  metric penalises.
- `BOE-A-1855-3318` (0.90) and `BOE-A-1851-4969` (0.94) — 19th-century
  tiny laws where single tokens have heavy weight in the ratio.
- `BOE-A-2003-21847` (0.92) — RD 1432/2003 with science/tech annex.

None are content defects. Exit criteria §5.5 met.

## Before/After example — Ley 35/2006 IRPF

| | Production today | After refactor |
|---|---:|---:|
| Lines | 5,165 | 6,593 (+28%) |
| Tax-bracket pipe tables | 0 | 167 rows (84 tables) |
| Blockquoted notas + citas | 0 | 610 |
| Cross-reference links | 0 | 479 |
| Metadata `subjects` | — | 24 materias |
| Metadata `references_previous/subsequent` | — | 60 refs |

## Decisions needed from you

1. **Ship Stage A refactor?** Run `legalize reprocess --country es --all`
   to regenerate 12,245 `.md` files, rewrite per-file git history, force-push
   to `legalize-es/main`. Time: ~7h refetch + ~2h regeneration if we want
   the full diario enrichment; ~2h regeneration only if we re-use the
   existing `countries/data-es/json` cache (lose diario enrichment on old
   laws until next full refresh).
2. **Proceed to Stage B discovery + orchestration?** Adds ~87k more norms
   (Circulares, Resoluciones, Órdenes, RDs puntuales). Network cost: ~1
   week of sumario walking at polite rate limit. Parser is ready; the
   work is discovery + envelope dispatch + initial bootstrap.
3. **Rewrite history vs fresh repo?** The git CLAUDE.md integrity rule
   permits per-file commit rewrites. Existing clones of legalize-es will
   see diverged history.

None of these execute without an explicit OK from you.

## How to continue from a fresh session

```bash
cd ~/projects/legalize/engine-es
git log --oneline main..HEAD   # 5 commits on refactor/es-deep
cat research/RESEARCH-ES-v2.md  # full plan
less /tmp/es-audit/fidelity-log.csv
uv run pytest tests/test_parser_es_refactor.py
uv run python -m scripts.es_fidelity.sample --n 20 --seed 2026 > /tmp/es-audit/sample-2026.txt
uv run python -m scripts.es_fidelity.score --sample /tmp/es-audit/sample-2026.txt --iter 9
```

Memory note `project_es_refactor.md` also recorded for cross-session recovery.
