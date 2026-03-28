# legalize-pipeline

The engine behind [legalize.dev](https://legalize.dev). Converts official legislation into version-controlled Markdown and serves it as a web app + API.

Each law is a file. Each reform is a commit. Every country is a repo.

## What it does

1. **Fetches** legislation from official open data sources (BOE for Spain, LEGI for France)
2. **Parses** XML into structured data (articles, versions, reforms)
3. **Generates** Markdown files with YAML frontmatter and git commits with historical dates
4. **Serves** a web app with search, timeline, diffs, and a REST API

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
  web/              # FastAPI web app + API
    app.py            Main app, middleware, routes
    db.py             PostgreSQL (metadata) + Blob (content)
    blob.py           Provider-agnostic blob storage
    api.py            REST API v1
    middleware.py     Rate limiting, security headers
  countries.py      # Country registry (dynamic dispatch)
  models.py         # Domain models (generic, multi-country)
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

# Start web (needs PostgreSQL + env vars)
legalize serve
```

## Adding a new country

1. Implement the 4 interfaces in `fetcher/base.py`:
   - `LegislativeClient` — fetch text + metadata
   - `NormDiscovery` — discover norms in catalog
   - `TextParser` — parse XML/HTML into `Bloque` objects
   - `MetadataParser` — parse metadata into `NormaMetadata`
2. Register in `countries.py`
3. Add rango folders to `transformer/slug.py`
4. Add country config to `web/countries.py`

See `fetcher/client_legi.py` (France) as a reference implementation.

## Environment variables

See [`.env.example`](.env.example) for all required variables.

## CLI

```bash
# Spain
legalize fetch --catalog          # Download all laws from BOE
legalize commit --all             # Generate git commits
legalize daily --date 2026-03-28  # Process daily update

# France
legalize fetch-fr --discover --legi-dir /path/to/legi  # Process LEGI dump
legalize bootstrap-fr --legi-dir /path/to/legi         # Full bootstrap

# Web
legalize ingest --data-dir ../data/json   # Load data into DB + blob
legalize serve                            # Start web server
```

## Countries

| Country | Status | Source | Laws | Repo |
|---------|--------|--------|------|------|
| 🇪🇸 Spain | ✅ Live | [BOE](https://www.boe.es/) | 8,642 | [legalize-es](https://github.com/legalize-dev/legalize-es) |
| 🇫🇷 France | 🚧 Beta | [Légifrance](https://www.legifrance.gouv.fr/) | 80 codes | [legalize-fr](https://github.com/legalize-dev/legalize-fr) |
| 🇩🇪 Germany | 🔜 Wanted | [BGBL](https://www.bgbl.de/) | — | Help wanted! |
| 🇵🇹 Portugal | 🔜 Wanted | [DRE](https://dre.pt/) | — | Help wanted! |
| 🇸🇪 Sweden | 🔜 Wanted | [Riksdagen](https://www.riksdagen.se/) | — | Help wanted! |
| 🇫🇮 Finland | 🔜 Wanted | [Finlex](https://www.finlex.fi/) | — | Help wanted! |
| 🇳🇱 Netherlands | 🔜 Wanted | [Overheid.nl](https://www.overheid.nl/) | — | Help wanted! |
| 🇧🇷 Brazil | 🔜 Wanted | [LeXML](https://www.lexml.gov.br/) | — | Help wanted! |

Want to add your country? See [docs/ADDING_A_COUNTRY.md](docs/ADDING_A_COUNTRY.md).

## Contributing

We welcome contributions, especially new country parsers. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines and [docs/ADDING_A_COUNTRY.md](docs/ADDING_A_COUNTRY.md) for the step-by-step guide to adding a new country.

## License

MIT
