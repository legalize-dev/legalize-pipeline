# legalize-pipeline

The engine behind [legalize.dev](https://legalize.dev). Converts official legislation into version-controlled Markdown in Git.

Each law is a file. Each reform is a commit. Every country is a repo.

## What it does

1. **Fetches** legislation from official open data sources (BOE for Spain, LEGI for France)
2. **Parses** XML into structured data (articles, versions, reforms)
3. **Generates** Markdown files with YAML frontmatter and git commits with historical dates

## Public repos (output)

| Country | Repo | Laws | Source |
|---------|------|------|--------|
| Spain | [legalize-es](https://github.com/legalize-dev/legalize-es) | 8,642 | BOE |
| France | [legalize-fr](https://github.com/legalize-dev/legalize-fr) | 80 codes | LEGI (Legifrance) |

## Architecture

```
src/legalize/
  fetcher/          # Download from official APIs
    client.py         BOE HTTP client (Spain)
    client_legi.py    LEGI XML dump reader (France)
    base.py           Abstract interfaces (add new countries here)
  transformer/      # XML -> Markdown
    xml_parser.py     BOE XML -> Bloque/Version
    markdown.py       Bloque -> Markdown (generic)
    frontmatter.py    YAML frontmatter (generic)
  committer/        # Markdown -> git commits
    git_ops.py        Git operations with historical dates
    message.py        Commit message formatting
  state/            # Pipeline state tracking
    store.py          Last processed summary, run history
    mappings.py       BOE-ID <-> filepath mapping
  countries.py      # Country registry (dynamic dispatch)
  models.py         # Domain models (generic, multi-country)
  storage.py        # Save XML + JSON to data/ (intermediate cache)
  pipeline.py       # Spain orchestration
  pipeline_fr.py    # France orchestration
```

## Quick start

```bash
# Install
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check src/ tests/
```

## CLI

```bash
# Spain
legalize fetch --catalog          # Download all laws from BOE
legalize commit --all             # Generate git commits
legalize daily --date 2026-03-28  # Process daily update
legalize status                   # Show pipeline status

# France
legalize fetch-fr --discover --legi-dir /path/to/legi  # Process LEGI dump
legalize bootstrap-fr --legi-dir /path/to/legi         # Full bootstrap
```

## Adding a new country

1. Implement the 4 interfaces in `fetcher/base.py`:
   - `LegislativeClient` — fetch text + metadata
   - `NormDiscovery` — discover norms in catalog
   - `TextParser` — parse XML/HTML into `Bloque` objects
   - `MetadataParser` — parse metadata into `NormaMetadata`
2. Register in `countries.py`
3. Add rango folders to `transformer/slug.py`

See `fetcher/client_legi.py` (France) as a reference implementation.

## Countries

| Country | Status | Source | Laws | Repo |
|---------|--------|--------|------|------|
| Spain | Live | [BOE](https://www.boe.es/) | 8,642 | [legalize-es](https://github.com/legalize-dev/legalize-es) |
| France | Beta | [Legifrance](https://www.legifrance.gouv.fr/) | 80 codes | [legalize-fr](https://github.com/legalize-dev/legalize-fr) |
| Germany | Wanted | [BGBL](https://www.bgbl.de/) | — | Help wanted! |
| Portugal | Wanted | [DRE](https://dre.pt/) | — | Help wanted! |

Want to add your country? See [docs/ADDING_A_COUNTRY.md](docs/ADDING_A_COUNTRY.md).

## Contributing

We welcome contributions, especially new country parsers. See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/ADDING_A_COUNTRY.md](docs/ADDING_A_COUNTRY.md).

## License

MIT
