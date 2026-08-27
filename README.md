# legalize-pipeline

[![CI](https://github.com/legalize-dev/legalize-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/legalize-dev/legalize-pipeline/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

The engine behind **[legalize.dev](https://legalize.dev)** -- converts official legislation into version-controlled Markdown in Git.

Each law is a file. Each reform is a commit. Every country is a repo.

## How it works

![Pipeline diagram](docs/pipeline-diagram.svg)

## Architecture

```
src/legalize/
  fetcher/              # Country-specific data fetching
    base.py               Abstract interfaces (LegislativeClient, NormDiscovery, TextParser, MetadataParser)
    es/                   Spain (BOE API)
      client.py             HTTP client with rate limiting, caching
      discovery.py          Norm discovery via catalog + sumarios
      parser.py             BOE XML -> Block/NormMetadata
    fr/                   France (LEGI XML dump)
      client.py             Local XML dump reader
      discovery.py          Filesystem-based discovery
      parser.py             LEGI XML -> Block/NormMetadata
    de/                   Germany (gesetze-im-internet.de)
      client.py             GIIClient: ZIP download + XML extraction
      discovery.py          TOC XML discovery (~6900 laws)
      parser.py             gii-norm XML -> Block/NormMetadata
    se/                   Sweden (SFSR / Riksdag)
      client.py             Riksdag API client
      discovery.py          SFS catalog discovery
      parser.py             Swedish XML -> Block/NormMetadata
    ad/                   Andorra (BOPA)
    ar/                   Argentina (InfoLEG)
    at/                   Austria (RIS OGD API)
    be/                   Belgium (Justel)
    cl/                   Chile (BCN / LeyChile)
    cz/                   Czech Republic (e-Sbírka)
    dk/                   Denmark (Retsinformation)
    ee/                   Estonia (Riigi Teataja)
    fi/                   Finland (Finlex AKN)
    gr/                   Greece (ET)
    ie/                   Ireland (Irish Statute Book)
    it/                   Italy (Normattiva AKN)
    lt/                   Lithuania (TAR / data.gov.lt)
    lu/                   Luxembourg (Legilux)
    lv/                   Latvia (likumi.lv HTML scraping with sitemap discovery)
    nl/                   Netherlands (BWB / wetten.overheid.nl)
    no/                   Norway (Lovdata)
    pl/                   Poland (Dziennik Ustaw / Sejm ELI)
    pt/                   Portugal (DRE SQLite dump)
    sk/                   Slovakia (Slov-Lex)
    ua/                   Ukraine (data.rada.gov.ua)
    uy/                   Uruguay (IMPO)
  transformer/          # Generic: XML -> Markdown
    xml_parser.py         Bloque/Version extraction, reform timeline
    markdown.py           Bloque -> Markdown (CSS class mapping)
    frontmatter.py        YAML frontmatter rendering
    slug.py               norm_to_filepath() -> {country_dir}/{id}.md
  committer/            # Generic: Markdown -> git commits
    git_ops.py            Git operations with historical dates
    message.py            Commit message formatting (6 types)
    author.py             Author from git config (whoever runs the pipeline)
  state/                # Pipeline state tracking
    store.py              Last processed summary, run history
  countries.py          # Country registry (lazy import dispatch)
  config.py             # Config + CountryConfig from config.yaml
  models.py             # Domain models (generic, multi-country)
  storage.py            # Save XML + JSON to data/ (intermediate cache)
  layout.py             # Directory layout per country (Format Spec v0.4)
  pipeline.py           # Generic orchestration (fetch, commit, bootstrap, daily, reprocess)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the module-by-module reference.

## Prerequisites

- Python 3.12+
- Git

## Quick start

```bash
git clone https://github.com/legalize-dev/legalize-pipeline.git
cd legalize-pipeline

pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check src/ tests/
```

## CLI

All commands use a unified `--country` / `-c` flag:

```bash
# Fetch laws to data/ (does not touch git)
legalize fetch -c es --catalog             # Spain: full BOE catalog
legalize fetch -c fr --all --legi-dir /path # France: all codes from LEGI dump
legalize fetch -c se --all                  # Sweden: all statutes from SFSR
legalize fetch BOE-A-1978-31229             # Single law by ID

# Generate git commits from local data/ (does not download)
legalize commit -c es --all
legalize commit -c fr --all

# Full pipeline: fetch + commit
legalize bootstrap                          # Spain (default)
legalize bootstrap -c fr --legi-dir /path   # France
legalize bootstrap -c se                    # Sweden

# Daily incremental update
legalize daily -c es --date 2026-03-28

# Reprocess specific norms
legalize reprocess -c es --reason "bug fix" BOE-A-1978-31229

# Pipeline status
legalize status
```

## Adding a new country

1. Create `fetcher/{code}/` with `client.py`, `discovery.py`, `parser.py`
2. Implement the 4 interfaces from `fetcher/base.py`:
   - `LegislativeClient` -- fetch raw data
   - `NormDiscovery` -- discover all laws in catalog
   - `TextParser` -- parse into `Bloque` objects
   - `MetadataParser` -- parse into `NormaMetadata`
3. Register in `countries.py` REGISTRY
4. Add `countries:` section to `config.yaml`

See [adding-a-country/](adding-a-country/README.md) for the full walkthrough.

## Countries

Source of truth for this table: `REGISTRY` in
[`src/legalize/countries.py`](src/legalize/countries.py) (which countries have
a fetcher) and the `daily-update.yml` / `monthly-update-*.yml` workflow
matrices (which of those run on a schedule). **Status** is derived from the
latter, not hand-maintained — see
[OPERATIONS.md](OPERATIONS.md#publication-calendar) for what each value means
operationally and why a handful of countries are unscheduled on purpose.

| Country | Status | Source | Repo | Maintainer |
|---------|--------|--------|------|------------|
| Andorra | Daily | [BOPA](https://www.bopa.ad/) | [legalize-ad](https://github.com/legalize-dev/legalize-ad) | — |
| Argentina | Monthly | [InfoLEG](http://www.infoleg.gob.ar/) | [legalize-ar](https://github.com/legalize-dev/legalize-ar) | — |
| Austria | Daily | [RIS](https://www.ris.bka.gv.at/) | [legalize-at](https://github.com/legalize-dev/legalize-at) | — |
| Belgium | Daily | [Justel](https://www.ejustice.just.fgov.be/) | [legalize-be](https://github.com/legalize-dev/legalize-be) | — |
| Chile | Unscheduled | [BCN](https://www.leychile.cl/) | [legalize-cl](https://github.com/legalize-dev/legalize-cl) | — |
| Colombia | Monthly | [SUIN-Juriscol](https://www.suin-juriscol.gov.co) | [legalize-co](https://github.com/legalize-dev/legalize-co) | — |
| Czech Republic | Daily | [e-Sbírka](https://www.e-sbirka.cz/) | [legalize-cz](https://github.com/legalize-dev/legalize-cz) | — |
| Denmark | Unscheduled | [Retsinformation](https://www.retsinformation.dk/) | [legalize-dk](https://github.com/legalize-dev/legalize-dk) | — |
| Estonia | Daily | [Riigi Teataja](https://www.riigiteataja.ee/) | [legalize-ee](https://github.com/legalize-dev/legalize-ee) | — |
| European Union | Daily | [EUR-Lex](https://eur-lex.europa.eu) | [legalize-eu](https://github.com/legalize-dev/legalize-eu) | — |
| Finland | Daily | [Finlex](https://www.finlex.fi/) | [legalize-fi](https://github.com/legalize-dev/legalize-fi) | — |
| France | Unscheduled | [Legifrance](https://www.legifrance.gouv.fr/) | [legalize-fr](https://github.com/legalize-dev/legalize-fr) | — |
| Germany | Daily | [gesetze-im-internet.de](https://www.gesetze-im-internet.de/) | [legalize-de](https://github.com/legalize-dev/legalize-de) | — |
| Greece | Daily | [ET](https://www.et.gr/) | [legalize-gr](https://github.com/legalize-dev/legalize-gr) | — |
| Ireland | Unscheduled | [Irish Statute Book](https://www.irishstatutebook.ie/) | [legalize-ie](https://github.com/legalize-dev/legalize-ie) | — |
| Italy | Daily | [Normattiva](https://www.normattiva.it/) | [legalize-it](https://github.com/legalize-dev/legalize-it) | — |
| Latvia | Daily | [likumi.lv](https://likumi.lv/) | [legalize-lv](https://github.com/legalize-dev/legalize-lv) | — |
| Liechtenstein | Unscheduled | [Lilex](https://www.gesetze.li) | [legalize-li](https://github.com/legalize-dev/legalize-li) | — |
| Lithuania | Daily | [TAR](https://www.e-tar.lt/) | [legalize-lt](https://github.com/legalize-dev/legalize-lt) | — |
| Luxembourg | Daily | [Legilux](https://legilux.public.lu/) | [legalize-lu](https://github.com/legalize-dev/legalize-lu) | — |
| Netherlands | Daily | [BWB](https://wetten.overheid.nl/) | [legalize-nl](https://github.com/legalize-dev/legalize-nl) | — |
| Norway | Unscheduled | [Lovdata](https://lovdata.no/) | [legalize-no](https://github.com/legalize-dev/legalize-no) | — |
| Poland | Daily | [Dziennik Ustaw](https://isap.sejm.gov.pl/) | [legalize-pl](https://github.com/legalize-dev/legalize-pl) | — |
| Portugal | Daily | [DRE](https://dre.pt/) | [legalize-pt](https://github.com/legalize-dev/legalize-pt) | — |
| Romania | Unscheduled | [Portalul Legislativ](https://legislatie.just.ro) | [legalize-ro](https://github.com/legalize-dev/legalize-ro) | — |
| Slovakia | Unscheduled | [Slov-Lex](https://www.slov-lex.sk/) | [legalize-sk](https://github.com/legalize-dev/legalize-sk) | — |
| Spain | Daily | [BOE](https://www.boe.es/) | [legalize-es](https://github.com/legalize-dev/legalize-es) | [@EnriqueLop](https://github.com/EnriqueLop) |
| Sweden | Daily | [Riksdag](https://www.riksdagen.se/) | [legalize-se](https://github.com/legalize-dev/legalize-se) | — |
| Switzerland | Monthly | [Fedlex](https://www.fedlex.admin.ch/) | [legalize-ch](https://github.com/legalize-dev/legalize-ch) | — |
| Ukraine | Unscheduled | [Rada](https://data.rada.gov.ua/) | [legalize-ua](https://github.com/legalize-dev/legalize-ua) | — |
| United Kingdom | Daily | [legislation.gov.uk](https://www.legislation.gov.uk/) | [legalize-uk](https://github.com/legalize-dev/legalize-uk) | [@florinungur](https://github.com/florinungur) |
| United States | Unscheduled | [OLRC](https://uscode.house.gov/) | [legalize-us](https://github.com/legalize-dev/legalize-us) | — |
| Uruguay | Unscheduled | [IMPO](https://www.impo.com.uy/) | [legalize-uy](https://github.com/legalize-dev/legalize-uy) | — |

South Korea ([legalize-kr](https://github.com/legalize-dev/legalize-kr),
maintained by [@9bow](https://github.com/9bow)) is live but, unlike every
country above, is **not** built by this pipeline — it has no entry in
`REGISTRY` and isn't part of this table for that reason. It's the deliberate
exception, not a second pattern to follow: a new country goes into the
pipeline as `fetcher/{cc}/` unless the source genuinely can't be brought in
that way.

Want to add your country? See [adding-a-country/](adding-a-country/README.md).

## Contributing

We welcome contributions, especially new country parsers. See
[CONTRIBUTING.md](CONTRIBUTING.md) and [adding-a-country/](adding-a-country/README.md).
If you want to look after a country long-term, [MAINTAINERS.md](MAINTAINERS.md)
explains the federated model.

## Operations

Keeping the published repos current — the publication calendar, what to do
when a scheduled run fails, and the slow-source mitigation — is documented in
[OPERATIONS.md](OPERATIONS.md).

## License

MIT
