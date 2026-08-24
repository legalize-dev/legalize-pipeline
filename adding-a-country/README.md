# Adding a New Country to Legalize

This directory is the **end-to-end playbook** for taking a country from "name only"
to a merged PR with the country repo live on legalize.dev. If you follow every step,
an AI agent (or a human) can go from zero to pushed bootstrap without extra instructions.

## How to read this (agents: this part is not optional)

The playbook is split into one file per step because a full country onboarding
takes hours. Whatever you read at the start of the session is gone by the time you
reach production, and a step you half-remember is a step you will get wrong.

So:

1. **Read this file in full, now.** It holds every gate. It is the only file you
   are expected to remember.
2. **Copy `PROGRESS-template.md` to `PROGRESS.md`** in your working directory and
   tick boxes as you go. That file, not your context, is where the state lives.
   When you lose track of where you are, `cat PROGRESS.md`.
3. **Read each step file in full immediately before starting that step** — not
   earlier. Every step file ends by naming the next one. Follow the chain.
4. **Never work from memory of a step file.** If you are about to run a command
   and you did not read it in this hour, re-read the file. It is 40–330 lines.

| File | Step |
|---|---|
| [`step-0-research.md`](step-0-research.md) | Research the source |
| [`step-1-fetcher.md`](step-1-fetcher.md) | Build `fetcher/{code}/` |
| [`step-2-4-wiring.md`](step-2-4-wiring.md) | Registry, config, repo plan |
| [`step-5-daily.md`](step-5-daily.md) | Daily processing |
| [`step-6-tests.md`](step-6-tests.md) | Tests |
| [`step-7-quality-gate.md`](step-7-quality-gate.md) | 5-law quality gate |
| [`step-8-workers.md`](step-8-workers.md) | Tune `max_workers` |
| [`step-9-production.md`](step-9-production.md) | Bootstrap, push, ship |
| [`reference.md`](reference.md) | Version-history strategies, subnational — consult anytime |
| [`PROGRESS-template.md`](PROGRESS-template.md) | Your checklist — copy it |

No step file is longer than ~350 lines. Re-reading one costs almost nothing;
guessing at what it said costs a bootstrap.

**Primary reference implementation:**
- **Spain** (`es/`) — the most complete fetcher. REST API with ETag caching, full
  version history via embedded XML, subnational jurisdictions (autonomous
  communities: `es-pv/`, `es-ct/`, etc.), daily reforms via affected-norms
  resolution, ~12K laws. **Read this one first.**

Secondary references for specific patterns:
- **Belgium** (`be/`) — archived-version URLs (`arch=N` walk), ~17.7K laws.
- **Latvia** (`lv/`) — HTML scraping, rich table preservation (pipe tables with
  rowspan/colspan), inline bold/italic.
- **France** (`fr/`) — local LEGI XML dump with embedded versions.
- **Andorra** (`ad/`) — Azure Functions API + blob storage.


## Execution flow — follow this order, do not skip gates

```
Step 0: Research
  ├─ 0.1 Identify source          → RESEARCH-{CC}.md created
  ├─ 0.2 Save 5 fixtures          → tests/fixtures/{code}/ populated
  ├─ 0.3 Metadata inventory       → field table in RESEARCH-{CC}.md
  ├─ 0.4 Formatting inventory     → checklist in RESEARCH-{CC}.md
  ├─ 0.5 Version history spike    → tests/fixtures/{code}/version-spike.txt
  │       ┌──────────────────────────────────────────────────────┐
  │       │ GATE: ≥2 versions extracted with dates from 1 law,  │
  │       │ and the source classified into one text_state.       │
  │       │ If not → stop and investigate. Do not write parser.  │
  │       └──────────────────────────────────────────────────────┘
  ├─ 0.6 Estimate scope           → paragraph in RESEARCH-{CC}.md
  └─ 0.7 Format-coverage table    → table in RESEARCH-{CC}.md + skip justification
          ┌──────────────────────────────────────────────────────┐
          │ GATE: every format carrying >1% of unique laws or    │
          │ unique versions is covered by the fetcher.           │
          │ If not → either extend scope or justify in writing.  │
          └──────────────────────────────────────────────────────┘

Step 1: Fetcher       → src/legalize/fetcher/{code}/ (client, discovery, parser)
Step 2: Register      → countries.py entry
Step 3: Config        → config.yaml section
Step 4: Repo plan     → (no artifact — planning only)
Step 5: Daily path    → daily.py or confirmation that generic_daily works
Step 6: Tests         → tests/test_parser_{code}.py passing

Step 7: Quality gate
  ├─ 7.1 Fetch + render 5 laws    → ../countries/{code}/{code}/*.md (sandbox)
  ├─ 7.2 AI review (5 checks)     → review output
  │       ┌──────────────────────────────────────────────────────┐
  │       │ GATE: 5/5 laws PASS on all 5 checks.                │
  │       │ If not → fix parser, re-render, re-review.           │
  │       │ Do not proceed to bootstrap.                         │
  │       └──────────────────────────────────────────────────────┘
  ├─ 7.3 Iterate until pass
  └─ 7.4 Manual spot-check

Step 8: Tune workers  → max_workers set in config.yaml
Step 9: Production
  ├─ 9.1 Create GitHub repo
  ├─ 9.2 Full bootstrap
  ├─ 9.3 Health check
  │       ┌──────────────────────────────────────────────────────┐
  │       │ GATE: `legalize health` reports zero issues.         │
  │       │ If not → fix and re-run. Do not push.                │
  │       └──────────────────────────────────────────────────────┘
  ├─ 9.4 Push to origin (mind the 2 GiB pack limit)
  ├─ 9.5 Engine PR (CI must pass)
  ├─ 9.6 CI workflows
  ├─ 9.7 Website PR (legalize-web)
  ├─ 9.8 Seed the DB (legalize-enrichment, full-local)
  ├─ 9.9 Verify on production
  └─ 9.10 Update memory
```

Each step produces a specific artifact (listed after `→`). The next step may
depend on that artifact. **If a gate fails, do not proceed — fix and re-check.**

## The five non-negotiable priorities

Every country we add must meet five requirements. They are listed in order of
how expensive they are to fix after the fact — the first is the hardest to
retrofit, the last is the easiest. **Do not ship a country that fails any of
them unless the exception is documented and justified in `RESEARCH-{CC}.md`.**

### 1. Perfect text fidelity

The rendered Markdown must be **identical to the official law**. Not "close
enough", not "most of it" — identical. This means:

- **Tables** must render as Markdown pipe tables with correct columns, rows,
  headers, and alignment. Tax schedules, tariff annexes, fee tables — if the
  source has them, the output has them.
- **Formatting** (bold, italic, lists, blockquotes, cross-references) must be
  preserved. If the gazette prints a word in bold, the Markdown has `**word**`.
- **No artifacts**: no leftover HTML/XML tags, no mojibake, no truncated
  sentences, no duplicated paragraphs, no swallowed whitespace.
- **Encoding is UTF-8, always.** Decode explicitly, strip C0/C1 control chars.

Why: the law text is the product. A user who finds a discrepancy between
legalize and the official gazette loses trust permanently. There is no "we'll
fix it later" — every bootstrap rewrites thousands of commits.

### 2. Historical versions

Legalize exists so that **every reform becomes a git commit**. One commit per
version, in chronological order, authored at the date the reform took effect.
Without this, the repo is just "current text as a file", which does not
differentiate from any other scrape.

Before you write a single line of parser code, you must answer:

1. Does the source expose historical versions? (Almost always yes — gazettes
   publish amendment decrees, and most open-data portals have them in some
   form: embedded XML, separate archive URLs, version tables, dated snapshots,
   or point-in-time queries.)
2. What is the fetch cost for the full history? (Number of HTTP requests,
   approximate bytes per version, rate-limit tolerance.)
3. What is the effective date of each version? (Required to set
   `GIT_AUTHOR_DATE` correctly. If the source only gives promulgation dates,
   use those; otherwise use entry-into-force dates.)

**Do not ship a single-snapshot country** (one commit per law = the current
text) unless you have tried and **documented in RESEARCH-{CC}.md** why
historical versions are unreachable (robots.txt disallow, no archive API,
paywalled, etc.). Single-snapshot ships are **temporary** and must have a
follow-up task to add history.

Why: rebuilding commit history after a single-snapshot ship is extremely
expensive. Every law needs `filter-branch` / fresh rewrite, and the web
database's hash-indexed commit table breaks during the migration. Getting
versions right **before** the first full bootstrap is an order of magnitude
cheaper than fixing it later.

See **[Version history strategies](#version-history-strategies)** further down
for the concrete patterns used by each existing country.

### 3. Complete metadata

Every field the source exposes must be captured — generic fields in the
`NormMetadata` dataclass, source-specific fields in `extra` with English
snake_case keys. Do not editorialize which fields are "useful". A future
consumer of the data may need any of them, and regenerating commit history to
add a forgotten field is expensive.

### 4. Commit ordering is per-file, not per-repo

Each law's git history must contain its versions **in chronological order**.
But the repository-level history does NOT need to be globally sorted. Different
laws' commits can be interleaved — what matters is that if you run
`git log -- path/to/LAW-123.md`, the commits appear in the order the reforms
were enacted.

This means the bootstrap can process laws in any order (parallelized, batched,
alphabetical) as long as each individual law's commits are written oldest-first.

Why this distinction matters: trying to sort commits globally across all laws
is fragile (ties on the same date, interleaved reforms) and provides no value.
The web's `sync_from_git.py` reads history per-file, not per-repo.

### 5. Multi-format coverage — process every format the source offers

If the official source publishes the same law in several file formats (e.g.
Switzerland's Fedlex serves the same consolidation as XML, DOCX, DOC and
PDF-A depending on the vintage), **the fetcher MUST support every format
that unlocks laws or versions the others do not**. Not just the cleanest one.

Why: picking "only XML" is a very easy trap — you end up shipping a country
with 30-60% of the classified compilation in the repo, and the missing laws
tend to be the older, most-consolidated, highest-value codes. A user who
finds that a landmark 1911 statute is absent loses trust permanently, and
bolting a second format on after bootstrap means rewriting every commit for
every law that format touches.

Concrete rule:

1. In Step 0.1, run a COUNT per format against the source (SPARQL, catalog
   scan, whatever is cheapest). Tabulate: total norms, norms reachable via
   each format, norms reachable only via a given format (`format N \ format M`).
2. The fetcher covers **every format that contributes > 1% of unique laws
   or unique versions**. Marginal formats (< 1%, or ones whose engineering
   cost dwarfs the gain — e.g. scanned-image PDFs with OCR) may be skipped,
   but the skip is justified in writing in `RESEARCH-{CC}.md`.
3. When a single law has versions across multiple formats, **the transition
   must be as seamless as the formats allow**. One version being XML and
   the next being PDF MUST NOT look like the text was rewritten — same
   article numbering, same heading depth, same paragraph numbering style,
   same footnote conventions. Before/after review is mandatory (see §7).

How to design for that:

- Make the parser format-dispatched inside a single country package. The
  envelope the client returns lists every version with an explicit
  `format="xml|docx|doc|pdf"` attribute; the parser walks each version with
  the format-appropriate extractor and emits the **same** `Block/Version/Paragraph`
  shape regardless of input.
- Normalize the output so that format-specific quirks do not leak: article
  headings use one template (`##### Art. N Title`), paragraph numbers use
  one style (`<sup>N</sup>`), tables always become Markdown pipe tables,
  footnotes always become `[^N]` + a Fussnoten/Footnotes/… block.
- For lossy formats (PDF, scanned DOC), keep the promise that **structure
  matches**, even if inline formatting (e.g. the italics in a preamble) may
  be lost. The engine rule "no artifacts" still applies — PDF output must
  not leak page headers, page numbers, "Seite 17 von 42" footers, or the
  date stamp Fedlex injects into every PDF-A.
- Cross-format fidelity is validated in Step 7 with a **before/after diff
  on a law that straddles formats**. Render version N-1 (older format) and
  version N (newer format) for the same law, diff them, iterate the parsers
  until a reader cannot tell from the Markdown which format the underlying
  manifestation was. This analysis lives in `RESEARCH-{CC}.md` under a new
  §0.7 "Cross-format fidelity check".

Countries where this matters as of 2026-04: Switzerland (XML since ~2021,
DOC/PDF for older vintages), Luxembourg (XML back to the 1950s, occasional
HTML gaps), Ireland (XML + Revised Acts HTML overlays), Estonia (PDF via
Lisa for appendices). If your country only ships one format, say so in
`RESEARCH-{CC}.md §0.1` and move on.

## Prerequisites

Before starting, you need:
- An open data source for the country's legislation (API, XML dump, or HTML)
- Understanding of the source's data format (and its licensing — must allow redistribution)
- Knowledge of the country's legal hierarchy (types of laws, reform process)
- **The access pattern for historical versions** — see priority #2 above. If
  the source only exposes current text, document the research effort that
  confirmed there is no archive and plan a follow-up to add history


## Architecture overview

The pipeline has two layers:

**Country-specific (you write this):** a fetcher that downloads and parses raw
data into generic models — `client.py`, `discovery.py`, `parser.py` under
`src/legalize/fetcher/{code}/`.

**Generic (provided for free):** Markdown rendering, YAML frontmatter, git commits
with historical dates, CLI commands, state management, web integration. These work
automatically once your fetcher produces the right data structures.

Module-by-module detail lives in [`../ARCHITECTURE.md`](../ARCHITECTURE.md); the
interfaces you must implement live in `src/legalize/fetcher/base.py`. Do not learn
either from this playbook — read the code.

## Maintaining this playbook

Three rules, each written after breaking one of them:

1. **A procedure named is a procedure shown.** If a sentence says "push in
   batches", the command below it batches. §9.4 said that for four months with a
   command that did nothing of the sort, and it cost an afternoon of failed pushes
   to find out why.
2. **A country-specific finding lives in `RESEARCH-{CC}.md` until a second country
   hits it.** Only then does it belong here. That is what keeps this from becoming
   a scrapbook of one-off war stories.
3. **Name things, don't copy them.** Interfaces live in `fetcher/base.py`, scripts
   live in `scripts/`, workflows live in `.github/`. A copy in Markdown is a copy
   that rots silently. `tests/test_docs_paths.py` fails when a path named here
   stops existing — it is not clever, but it is the only thing standing between
   these files and the next `api/countries.py` that hasn't existed for months.

---

**Start → read [`step-0-research.md`](step-0-research.md) in full.** Copy
`PROGRESS-template.md` to `PROGRESS.md` first.
