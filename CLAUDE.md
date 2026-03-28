# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Legalize is a multi-country platform that converts official legislation into version-controlled Markdown. Each law is a file, each reform is a git commit. The public repo is the product; this repo is the pipeline that generates it.

**Repos:**
- `legalize-dev/legalize` — public hub: README, index of countries, docs
- `legalize-dev/legalize-es` — public: Spanish laws as Markdown + git history (8,642 laws, 27,866 commits)
- `legalize-dev/legalize-pipeline` — public: this repo. Python engine that generates the public repos.
- `legalize-dev/legalize-web` — public: landing page for legalize.dev

**Local structure:**
```
~/autonomo/legalize/
├── engine/     ← this repo (legalize-pipeline)
├── es/         ← Spanish laws (legalize-es)
├── web/        ← landing page (legalize-web)
├── hub/        ← hub repo (legalize)
└── data/       ← XML + JSON cache (no git)
```

**Website:** legalize.dev (coming soon)

Currently processing Spanish legislation from the BOE API. Architecture is multi-country ready (future: legalize-fr, legalize-uk, legalize-de).

## Language & Stack

- **Python 3.12+** with `pyproject.toml` (hatchling build), src layout
- Dependencies: `lxml`, `requests`, `pyyaml`, `click`, `rich`
- Dev: `pytest`, `ruff`, `responses` (HTTP mocking)
- Git operations via `subprocess` (not GitPython) for full control over `GIT_AUTHOR_DATE`

## Commands

```bash
# Install
pip install -e ".[dev]"

# Run tests (79 passing)
pytest tests/ -v

# Lint
ruff check src/ tests/

# Bootstrap from BOE API (downloads and generates commits)
python -c "from legalize.cli import cli; cli()" bootstrap

# Bootstrap from local XML (piloto)
python -c "from legalize.cli import cli; cli()" bootstrap --xml tests/fixtures/constitucion-sample.xml

# Daily update (process BOE sumario)
python -c "from legalize.cli import cli; cli()" daily --date 2026-03-27

# Reprocess specific norms
python -c "from legalize.cli import cli; cli()" reprocess --reason "bug fix" BOE-A-1978-31229

# Check pipeline status
python -c "from legalize.cli import cli; cli()" status
```

## Architecture

Modular pipeline in `src/legalize/`:

### Fetcher (`fetcher/`)
- `client.py` — `BOEClient`: HTTP with rate limiting (2 req/s), exponential backoff, ETag/Last-Modified cache
- `cache.py` — `FileCache`: local XML cache in `.cache/` with 24h TTL
- `sumario.py` — parse daily BOE summaries, filter by scope
- `catalogo.py` — discover norms via fixed list or sumario sweep

### Transformer (`transformer/`)
- `xml_parser.py` — `parse_texto_xml(bytes) → list[Bloque]`, `extract_reforms()`, `get_bloque_at_date()`
- `markdown.py` — `render_norma_at_date(metadata, bloques, date) → str`. CSS→MD mapping is data-driven
- `frontmatter.py` — `render_frontmatter(NormaMetadata, date) → str`
- `metadata.py` — `parse_metadatos(bytes, id) → NormaMetadata` from BOE API response
- `slug.py` — `norma_to_filepath(metadata) → str` (e.g., `spain/BOE-A-1978-31229.md`)

### Committer (`committer/`)
- `git_ops.py` — `GitRepo`: init, write_and_add, commit (historical dates), push, idempotency via `git log --grep`
- `message.py` — `build_commit_info()`, `format_commit_message()`. Six types: `[bootstrap]`, `[reforma]`, `[nueva]`, `[derogacion]`, `[correccion]`, `[fix-pipeline]`. Trailers: `Source-Id`, `Source-Date`, `Norm-Id`
- `author.py` — All commits by `Legalize <legalize@legalize.es>`

### State (`state/`)
- `store.py` — `StateStore`: state.json (ultimo_sumario, normas_procesadas, ejecuciones)
- `mappings.py` — `IdToFilename`: BOE-ID ↔ filepath mapping

### Multi-country (`countries.py`, `fetcher/base.py`)
- `countries.py` — Country registry with dynamic dispatch
- `fetcher/base.py` — Abstract base: LegislativeClient, NormDiscovery, TextParser, MetadataParser
- `fetcher/parser_boe.py` — BOE implementations of TextParser + MetadataParser
- `fetcher/discovery_boe.py` — BOE norm discovery via sumarios

### Orchestration
- `pipeline.py` — Three flows: `bootstrap()`, `bootstrap_from_api()`, `daily()`, `reprocess()`
- `cli.py` — Click CLI: `bootstrap`, `daily`, `reprocess`, `status`
- `config.py` — `Config` from `config.yaml` with CLI overrides

## Data Model (`models.py`)

Multi-country ready. Key types:
- `COUNTRIES` dict: `{"es": {"dir": "spain", ...}}` — extensible per country
- `NormaMetadata`: generic fields (`identificador`, `pais`, `fuente` — not BOE-specific)
- `CommitInfo`: generic trailers (`Source-Id`, `Source-Date`, `Norm-Id`)
- Filenames = official ID: `spain/BOE-A-1978-31229.md`

## Output Format (FINAL — do not change without regenerating all commits)

**Filename:** `{country_dir}/{official_id}.md` → `spain/BOE-A-1978-31229.md`

**Frontmatter:**
```yaml
---
titulo: "Constitución Española"
identificador: "BOE-A-1978-31229"
pais: "es"
rango: "constitucion"
fecha_publicacion: "1978-12-29"
ultima_actualizacion: "2024-02-17"
estado: "vigente"
fuente: "https://www.boe.es/eli/es/c/1978/12/27/(1)"
---
```

**Commit messages:** `[reforma] Constitución Española — art. 49`
**Author:** `Legalize <legalize@legalize.es>` (always)
**Trailers:** `Source-Id`, `Source-Date`, `Norm-Id`

## Adding New Laws

All 8,642 estatales laws from BOE are already processed. To add new ones published after bootstrap:
1. Run `fetch` to download new norms
2. Run `commit` to generate git commits in `../es/`

The engine outputs to `../es/` (legalize-es repo) and reads cached data from `../data/`.

## BOE API

Base: `https://www.boe.es/datosabiertos/`
- `/api/boe/sumario/{YYYYMMDD}` — daily publications
- `/api/legislacion-consolidada?limit=-1` — full catalog (1065 norms in scope)
- `/api/legislacion-consolidada/id/{id}/texto` — full XML with versioned `<bloque>` elements
- `/api/legislacion-consolidada/id/{id}/metadatos` — norm metadata (rango codes: 1070=Constitución, 1010=LO, 1020=Ley, 1040=RDL, 1050=RDLeg)

## Key Conventions

- Dates as `datetime.date` internally; parse at XML boundary, format at output
- Code comments and variable names in Spanish
- Spec in `spec-leyes-git.md` (original design doc, may be outdated vs actual implementation)
- GitHub Actions workflows exist but are NOT active — everything runs locally for now
