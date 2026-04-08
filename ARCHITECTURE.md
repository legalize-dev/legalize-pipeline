# Architecture

Module-by-module reference for `src/legalize/`. For project rules and conventions see [CLAUDE.md](CLAUDE.md). For the country onboarding playbook see [ADDING_A_COUNTRY.md](ADDING_A_COUNTRY.md).

## Pipeline flow

```
fetch → transform → commit
```

1. **Fetch** — country-specific clients hit the source API or read a local dump, normalize the response into `data-{code}/json/{id}.json`. No git side effects.
2. **Transform** — generic XML/HTML → Markdown rendering, frontmatter generation, slug computation. Country-agnostic.
3. **Commit** — generic git operations: write files, stage, commit with historical `GIT_AUTHOR_DATE`, push. Idempotent via `git log --grep` on the `Source-Id` trailer.

The CLI (`legalize fetch | commit | bootstrap | daily | reprocess | status | health`) dispatches these phases per country.

## Modules

### `fetcher/` — country-specific data acquisition

Each country lives in its own subpackage. Every fetcher implements the four interfaces from `fetcher/base.py`:

- `LegislativeClient` — HTTP/IO surface (rate limits, retries, ETag/Last-Modified caching)
- `NormDiscovery` — `discover_all()` and `discover_daily()` yield norm IDs
- `TextParser` — turns raw bytes into `list[Block]`
- `MetadataParser` — turns raw bytes into `NormMetadata`

Shared infrastructure:

- `fetcher/base.py` — abstract interfaces and `HttpClient` base class
- `fetcher/cache.py` — `FileCache`: local disk cache with TTL, used for ETag/Last-Modified short-circuit on daily runs

The current set of country fetchers is whatever lives under `fetcher/{code}/` and is registered in `src/legalize/countries.py::REGISTRY`. Read those two locations for the authoritative list — do not maintain a duplicate list in this document.

Naming convention for the per-country classes: `{Source}Client`, `{Source}Discovery`, `{Source}TextParser`, `{Source}MetadataParser`. For example Latvia (likumi.lv) uses `LikumiClient`, `LikumiDiscovery`, `LikumiTextParser`, `LikumiMetadataParser`.

### `transformer/` — generic Markdown rendering

Country-agnostic. Anything country-specific belongs in the parser, not here.

- `xml_parser.py` — `parse_text_xml(bytes) -> list[Block]`, `extract_reforms()`, `get_block_at_date()`
- `markdown.py` — `render_norm_at_date(metadata, blocks, date) -> str`. CSS → Markdown mapping is data-driven (the parser tags paragraphs with CSS classes; the renderer maps each class to a Markdown style).
- `frontmatter.py` — `render_frontmatter(NormMetadata, date) -> str`
- `metadata.py` — metadata parsing helpers
- `slug.py` — `norm_to_filepath(metadata) -> str` (e.g. `es/BOE-A-1978-31229.md`)

### `committer/` — generic git operations

- `git_ops.py` — `GitRepo`: init, write_and_add, commit (with historical `GIT_AUTHOR_DATE`), push, idempotency via `git log --grep` on the `Source-Id` trailer.
- `message.py` — `build_commit_info()`, `format_commit_message()`. Six commit types: `[bootstrap]`, `[reforma]`, `[nueva]`, `[derogacion]`, `[correccion]`, `[fix-pipeline]`. Trailers: `Source-Id`, `Source-Date`, `Norm-Id`.
- `author.py` — author resolved from `git config user.name/user.email` (whoever runs the pipeline). Committer is fixed to the project bot via `config.yaml::git.committer_name/email`.

### `state/` — pipeline state

- `store.py` — `StateStore`: `state.json` tracking `last_summary_date` and a run history. Used by the daily flow to know where to resume.

### Multi-country dispatch — `countries.py`, `config.py`

- `countries.py::REGISTRY` — dict mapping each country code to a `(module, class)` tuple per component (`client`, `discovery`, `text_parser`, `metadata_parser`). Imports are **lazy** so we don't pay the import cost of every fetcher on startup. Helpers: `get_client_class()`, `get_discovery_class()`, `get_text_parser()`, `get_metadata_parser()`, `supported_countries()`.
- `config.py::Config` — top-level config loaded from `config.yaml`. Each country has its own `CountryConfig` with `repo_path`, `data_dir`, `cache_dir`, `max_workers`, and a free-form `source` mapping that is passed to the client's `create()` factory.

### Orchestration — `pipeline.py`, `cli.py`

- `pipeline.py` — generic flows used by every country: `generic_fetch_all()`, `generic_fetch_one()`, `generic_bootstrap()`, `commit_all()`, `commit_all_fast()`, `commit_one()`, `daily()`, `reprocess()`. All dispatch through `countries.py`.
- `cli.py` — Click CLI with the unified `--country` / `-c` flag: `fetch`, `commit`, `bootstrap`, `daily`, `reprocess`, `status`, `health`.

## Data model — `models.py`

Multi-country ready. Key types:

- `Rank` — free-form string for the normative rank. Each country defines its own values (`constitucion`, `ley_organica`, `nomos`, `proedriko_diatagma`, …). The renderer treats `Rank` as opaque text.
- `NormMetadata` — generic frontmatter fields (`identifier`, `country`, `title`, `short_title`, `rank`, `publication_date`, `last_updated`, `status`, `department`, `source`, `jurisdiction`) plus an `extra` mapping for source-specific fields.
- `Block` — structural unit (article, chapter, …) with versioned content.
- `Version` — temporal version of a `Block`, with `publication_date`, `effective_date`, and `paragraphs`.
- `CommitInfo` — generic commit trailers (`Source-Id`, `Source-Date`, `Norm-Id`).

Filenames are always the official identifier under the country directory: `es/BOE-A-1978-31229.md`, `gr/FEK-A-114-2006.md`, etc.

## Concurrency notes

- Most fetchers use the engine's `ThreadPoolExecutor` with `max_workers` taken from `config.yaml`.
- Some sources are CPU-bound (`lxml` parsing) rather than IO-bound; tune `max_workers` per country with a 50-norm benchmark before committing a value.
- A few sources are NOT thread-safe under the engine's pool (currently Greece — `pypdfium2` + `pdfplumber` crash with `EXC_BREAKPOINT/SIGTRAP` at any worker count > 1). Those countries set `max_workers: 1` and document the constraint in `config.yaml`. A future refactor could move PDF extraction into a child process to lift the constraint.
