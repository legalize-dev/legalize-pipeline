# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Legalize is a multi-country platform that converts official legislation into version-controlled Markdown. Each law is a file, each reform is a git commit. The public repo is the product; this repo is the pipeline that generates it.

**Repos:**
- `legalize-dev/legalize` -- public hub: README, index of countries, docs
- `legalize-dev/legalize-es` -- public: Spanish laws (12,235 laws)
- `legalize-dev/legalize-fr` -- public: French laws (83 codes)
- `legalize-dev/legalize-de` -- public: German laws (5,729 laws)
- `legalize-dev/legalize-at` -- public: Austrian laws
- `legalize-dev/legalize-se` -- public: Swedish laws
- `legalize-dev/legalize-lv` -- public: Latvian laws (15,006 consolidated norms)
- `legalize-dev/legalize-pipeline` -- public: this repo. Python engine that generates the public repos.

**Local structure:**
```
~/autonomo/legalize/
├── engine/              ← this repo (legalize-pipeline)
├── countries/           ← may be empty (see "Local Storage" section below)
│   ├── {code}/          ← country repos (legalize-{code}), cloned on demand
│   └── data-{code}/     ← data caches (no git), regenerable via fetch
├── hub/                 ← hub repo (legalize)
└── web/                 ← legalize.dev website
```

**Website:** https://legalize.dev

Processing 10 countries: ES (BOE), FR (LEGI), DE (GII), AT (RIS), SE (SFSR), CL (BCN), LT (TAR), PT (DRE), UY (IMPO), LV (likumi.lv). Architecture is multi-country with a unified pipeline.

## Language & Stack

- **English only** — all code, comments, variable names, function names, and documentation must be in English. The only exceptions are string literals for XML element names (BOE/LEGI tags) and commit message content.
- **Python 3.12+** with `pyproject.toml` (hatchling build), src layout
- Dependencies: `lxml`, `requests`, `pyyaml`, `click`, `rich`
- Dev: `pytest`, `ruff`, `responses` (HTTP mocking)
- Git operations via `subprocess` (not GitPython) for full control over `GIT_AUTHOR_DATE`
- CI via GitHub App (Legalize Pipeline)

## Commands

```bash
# Install
pip install -e ".[dev]"

# Run tests (459 passing)
pytest tests/ -v

# Lint
ruff check src/ tests/

# Fetch laws to data/ (does not touch git)
legalize fetch -c es --catalog                 # Spain: full BOE catalog
legalize fetch -c fr --all --legi-dir /path    # France: LEGI dump
legalize fetch -c se --all                     # Sweden: SFSR

# Generate git commits from local data/
legalize commit -c es --all
legalize commit -c fr --all

# Full pipeline: fetch + commit
legalize bootstrap                             # Spain (default)
legalize bootstrap -c fr --legi-dir /path      # France
legalize bootstrap -c se                       # Sweden

# Daily incremental update
legalize daily -c es --date 2026-03-28

# Reprocess specific norms
legalize reprocess -c es --reason "bug fix" BOE-A-1978-31229

# Pipeline status
legalize status
legalize health -c es              # Repo health check (dates, empty files, remote, orphans)
legalize health -c se --sample 1000
```

## Architecture

Modular pipeline in `src/legalize/`:

### Fetcher (`fetcher/`)

Country-specific fetchers live in subpackages. Each implements the 4 interfaces from `fetcher/base.py`.

- `base.py` -- Abstract interfaces: `LegislativeClient`, `NormDiscovery`, `TextParser`, `MetadataParser`
- `cache.py` -- `FileCache`: local XML cache with TTL
- `es/` -- Spain (BOE API)
  - `client.py` -- `BOEClient`: HTTP with rate limiting, ETag/Last-Modified cache
  - `discovery.py` -- `BOEDiscovery`: norm discovery via catalog + sumarios
  - `parser.py` -- `BOETextParser`, `BOEMetadataParser`: BOE XML parsing
  - `sumario.py`, `catalogo.py`, `metadata.py`, `titulos.py` -- support modules
- `fr/` -- France (LEGI XML dump)
  - `client.py` -- `LEGIClient`: local XML dump reader
  - `discovery.py` -- `LEGIDiscovery`: filesystem-based discovery
  - `parser.py` -- `LEGITextParser`, `LEGIMetadataParser`: LEGI XML parsing
- `de/` -- Germany (gesetze-im-internet.de)
  - `client.py` -- `GIIClient(HttpClient)`: ZIP download + XML extraction
  - `discovery.py` -- `GIIDiscovery`: TOC XML discovery (~6900 laws)
  - `parser.py` -- `GIITextParser`, `GIIMetadataParser`: gii-norm XML parsing
- `se/` -- Sweden (SFSR / Riksdag)
  - `client.py` -- `SwedishClient`: Riksdag API client
  - `discovery.py` -- `SwedishDiscovery`: SFS catalog discovery
  - `parser.py` -- `SwedishTextParser`, `SwedishMetadataParser`: Swedish XML parsing
- `at/` -- Austria (RIS OGD API)
- `cl/` -- Chile (BCN / LeyChile)
- `lt/` -- Lithuania (TAR / data.gov.lt)
- `pt/` -- Portugal (DRE SQLite dump)
- `uy/` -- Uruguay (IMPO)
- `lv/` -- Latvia (likumi.lv HTML scraping)
  - `client.py` -- `LikumiClient(HttpClient)`: single HTML page per law (text + metadata)
  - `discovery.py` -- `LikumiDiscovery`: parses sitemap-1.xml + sitemap-2.xml (~76K URLs), filters out amendment slugs and ~483 robots.txt-disallowed IDs → ~48K consolidated laws
  - `parser.py` -- `LikumiTextParser`, `LikumiMetadataParser`: lxml HTML parsing of `TV*` CSS classes, handles tables (`TV444` → Markdown pipe tables with rowspan/colspan), forces UTF-8 to avoid mojibake, strips C0/C1 control chars

### Transformer (`transformer/`)
- `xml_parser.py` -- `parse_text_xml(bytes) -> list[Block]`, `extract_reforms()`, `get_block_at_date()`
- `markdown.py` -- `render_norm_at_date(metadata, blocks, date) -> str`. CSS->MD mapping is data-driven
- `frontmatter.py` -- `render_frontmatter(NormMetadata, date) -> str`
- `metadata.py` -- metadata parsing helpers
- `slug.py` -- `norm_to_filepath(metadata) -> str` (e.g., `es/BOE-A-1978-31229.md`)

### Committer (`committer/`)
- `git_ops.py` -- `GitRepo`: init, write_and_add, commit (historical dates), push, idempotency via `git log --grep`
- `message.py` -- `build_commit_info()`, `format_commit_message()`. Six types: `[bootstrap]`, `[reforma]`, `[nueva]`, `[derogacion]`, `[correccion]`, `[fix-pipeline]`. Trailers: `Source-Id`, `Source-Date`, `Norm-Id`
- `author.py` -- Author from `git config user.name/email` (whoever runs the pipeline)

### State (`state/`)
- `store.py` -- `StateStore`: state.json tracking last summary date and run history

### Multi-country (`countries.py`, `config.py`)
- `countries.py` -- `REGISTRY` dict with lazy imports: maps country code to `(module, class)` tuples for client, discovery, text_parser, metadata_parser. Helper functions: `get_client_class()`, `get_discovery_class()`, `get_text_parser()`, `get_metadata_parser()`, `supported_countries()`
- `config.py` -- `Config` with `CountryConfig` per country. `config.yaml` has a `countries:` section with per-country `repo_path`, `data_dir`, `source` (passed to client `create()`)

### Orchestration
- `pipeline.py` -- Generic flows: `generic_fetch_all()`, `generic_fetch_one()`, `generic_bootstrap()`, `commit_all()`, `commit_one()`, `daily()`, `reprocess()`. All country-agnostic; dispatch via `countries.py`
- `cli.py` -- Click CLI with unified `--country` / `-c` flag: `fetch`, `commit`, `bootstrap`, `daily`, `reprocess`, `status`
- `config.py` -- `Config` from `config.yaml` with CLI overrides

## Data Model (`models.py`)

Multi-country ready. Key types:
- `Rank` -- free-form string for normative rank (each country defines its own values)
- `NormMetadata` -- generic fields (`identifier`, `country`, `source`)
- `Block` -- structural unit (article, chapter) with versioned content
- `Version` -- temporal version with `publication_date` and paragraphs
- `CommitInfo` -- generic trailers (`Source-Id`, `Source-Date`, `Norm-Id`)
- Filenames = official ID: `es/BOE-A-1978-31229.md`

## Output Format (FINAL -- do not change without regenerating all commits)

**File structure is FLAT -- one directory per country, no subdirectories:**
```
legalize-es/
  es/BOE-A-1978-31229.md      ← state-level laws
  es-pv/BOE-A-2020-615.md     ← autonomous communities (jurisdiction)
legalize-at/
  at/AT-10002333.md            ← all laws flat in at/
```
Never create subdirectories by rank, category, or any other grouping. The rank goes in the YAML frontmatter, not in the directory structure.

**Filename:** `{country}/{identifier}.md` (e.g., `es/BOE-A-1978-31229.md`, `at/AT-10002333.md`)

**Frontmatter:**
```yaml
---
title: "Constitucion Espanola"
identifier: "BOE-A-1978-31229"
country: "es"
rank: "constitucion"
publication_date: "1978-12-29"
last_updated: "2024-02-17"
status: "in_force"
source: "https://www.boe.es/eli/es/c/1978/12/27/(1)"
---
```

**Commit messages:** `[reforma] Constitucion Espanola -- art. 49`
**Author:** from `git config` (whoever runs the pipeline)
**Trailers:** `Source-Id`, `Source-Date`, `Norm-Id`

**Commit integrity rule:** Each law's git history must contain ONLY commits that correspond to real legislative modifications (bootstrap + reforms). No fix-up commits, no pipeline corrections, no "update content" patches. If a bug in the pipeline produced incorrect Markdown, the fix is to reprocess the affected law (rewrite its commits from data/), never an additional commit on top. The commit history IS the legislative record -- it must not contain artifacts from pipeline bugs. Integrity is per-file, not per-repository: each law's commits are independent from other laws, so a single law can be reprocessed (its commits removed and recreated via filter-branch) without affecting the rest of the repo.

## Adding New Countries

[ADDING_A_COUNTRY.md](ADDING_A_COUNTRY.md) is the **end-to-end playbook**. Follow
every step — it takes a country from name-only to merged PR and live on
legalize.dev. Do not improvise shortcuts.

High-level order:

0. **Research the source** — save 5 fixtures, inventory every metadata field and
   every rich-formatting construct into `RESEARCH-{CC}.md`.
1. Create `fetcher/{code}/` with `client.py`, `discovery.py`, `parser.py`
   implementing the 4 interfaces from `fetcher/base.py`.
2. Register in `countries.py` REGISTRY.
3. Add `countries:` section to `config.yaml`.
4. Create the GitHub repo `legalize-dev/legalize-{code}`.
5. (Optional) Custom `daily.py` if the country has a non-standard daily flow.
6. Write parser tests against the fixtures.
7. **Quality gate (mandatory):** fetch 5 sample laws, render to MD, and run an
   AI review covering TEXT correctness, METADATA completeness, STRUCTURE,
   RICH FORMATTING preservation, and ENCODING. Do not proceed until 5/5 PASS.
8. Tune `max_workers` against a 50-law benchmark.
9. Full bootstrap → `legalize health` → push country repo → open engine PR →
   open web PR → verify on https://legalize.dev/{code}.

**Non-negotiable rules for the parser:**

- **Metadata completeness:** every field the source exposes must be captured
  (generic fields in `NormMetadata`, source-specific in `extra` with English
  snake_case keys). Regenerating commit history to add a forgotten field is
  expensive, so we capture everything up front.
- **Rich formatting preservation:** tables → Markdown pipe tables (see
  `fetcher/lv/parser.py` for the canonical implementation), bold → `**...**`,
  italic → `*...*`, lists → `- ...`, cross-references → `[text](url)`, quoted
  amending text → `> ...`, signatories → `firma_rey` css class. Inline
  bold/italic must be pre-wrapped in the parser (the CSS→MD map is paragraph-level).
- **Images are explicitly skipped** — we are not ready for binary assets. Drop
  image nodes and count them in `extra.images_dropped`.
- **Encoding is UTF-8 only** — decode source bytes explicitly, strip C0/C1
  control chars, normalize whitespace at paragraph boundaries. Never rely on
  `requests` auto-detection.

## BOE API (Spain)

Base: `https://www.boe.es/datosabiertos/`
- `/api/boe/sumario/{YYYYMMDD}` -- daily publications
- `/api/legislacion-consolidada?limit=-1` -- full catalog (1065 norms in scope)
- `/api/legislacion-consolidada/id/{id}/texto` -- full XML with versioned `<bloque>` elements
- `/api/legislacion-consolidada/id/{id}/metadatos` -- norm metadata

## Local Storage & Working Without Local Repos

Country repos and data directories are NOT required on the developer's machine.
All production workflows run in CI (GitHub Actions). Local copies are only needed
for development and debugging.

**What lives where:**
- Country repos (`countries/{code}/`) → GitHub (`legalize-dev/legalize-{code}`)
- Data caches (`countries/data-{code}/`) → regenerable via `legalize fetch`
- Daily updates → CI workflow (`daily-update.yml`), not local

**The local `countries/` directory may be empty.** Do not assume repos or data
dirs exist locally. Always check before running commands that depend on them.

**To work on a country temporarily:**
```bash
# Shallow clone (no history, ~10x smaller)
git clone --depth 1 git@github.com:legalize-dev/legalize-es.git ../countries/es

# Blobless clone (structure + on-demand blobs, good for git log)
git clone --filter=blob:none git@github.com:legalize-dev/legalize-es.git ../countries/es

# When done, delete to save space
rm -rf ../countries/es
```

**To re-create a data directory:**
```bash
legalize fetch -c es --catalog      # Spain: ~2h, downloads from BOE API
legalize fetch -c de --all          # Germany: ~1h, downloads from GII
legalize fetch -c fr --all          # France: needs LEGI dump from data.gouv.fr
```

**Space reference per country (approximate):**
- Repo: 200 MB - 1.5 GB (depends on number of laws)
- Data cache: 400 MB - 19 GB (depends on source format)
- At 50 countries, keeping all repos locally would exceed 30 GB

## Key Conventions

- Dates as `datetime.date` internally; parse at XML boundary, format at output
- English for all code, comments, and variable names
- CI via GitHub App (Legalize Pipeline); daily runs via cron workflow

## Git Commits

- The user is always the commit author (from their git config)
- Add `Co-Authored-By: Claude <noreply@anthropic.com>` to commit messages
- Never override the git author — Claude is a collaborator, not the author
