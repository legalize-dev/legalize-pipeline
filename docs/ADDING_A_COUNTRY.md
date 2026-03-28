# Adding a New Country to Legalize

This guide walks through adding a new country to the pipeline. Use France (`fr`) as the reference implementation.

## Prerequisites

Before starting, you need:
- An open data source for the country's legislation (API or XML dump)
- Understanding of the source's data format (XML, JSON, HTML)
- Knowledge of the country's legal hierarchy (types of laws, reform process)

## Step 1: Implement the 4 interfaces

Create files in `src/legalize/fetcher/`:

### a) Client — `client_{code}.py`

Implements `LegislativeClient` from `fetcher/base.py`:

```python
from legalize.fetcher.base import LegislativeClient

class UKClient(LegislativeClient):
    def get_texto(self, norm_id: str) -> bytes:
        """Fetch the consolidated text of a law. Returns raw bytes (XML/HTML)."""

    def get_metadatos(self, norm_id: str) -> bytes:
        """Fetch metadata for a law. Returns raw bytes."""

    def close(self) -> None:
        """Clean up (close HTTP sessions, etc.)."""
```

**Reference:** `client_legi.py` (reads local XML dump), `client.py` (HTTP API)

### b) Discovery — `discovery_{code}.py`

Implements `NormDiscovery` from `fetcher/base.py`:

```python
from legalize.fetcher.base import NormDiscovery

class UKDiscovery(NormDiscovery):
    def discover_all(self, client, **kwargs) -> Iterator[str]:
        """Yield all norm IDs in the catalog."""

    def discover_daily(self, client, target_date, **kwargs) -> Iterator[str]:
        """Yield norm IDs published/updated on a specific date."""
```

**Reference:** `discovery_legi.py` (scans XML dump), `discovery_boe.py` (uses API)

### c) Text Parser — `parser_{code}.py`

Implements `TextParser` and `MetadataParser` from `fetcher/base.py`:

```python
from legalize.fetcher.base import TextParser, MetadataParser

class UKTextParser(TextParser):
    def parse_texto(self, data: bytes) -> list[Bloque]:
        """Parse raw text into Bloque objects with version history."""

    def extract_reforms(self, data: bytes) -> list[Reform]:
        """Extract reform timeline from the parsed bloques."""

class UKMetadataParser(MetadataParser):
    def parse(self, data: bytes, norm_id: str) -> NormaMetadata:
        """Parse raw metadata into NormaMetadata."""
```

The output models are in `models.py`:
- `Bloque` — structural unit (article, title, chapter)
- `Version` — a temporal version of a bloque, with `fecha_publicacion` and `paragraphs`
- `Paragraph` — text with a CSS class (for markdown rendering)
- `NormaMetadata` — title, id, country, rango, dates, status
- `Reform` — a point in time where the law changed

**Key:** Your parser must produce these generic objects. The markdown renderer, git committer, and web app work with them regardless of country.

**Reference:** `parser_legi.py` (France), `parser_boe.py` (Spain)

## Step 2: Define rango types

Each country has its own legal hierarchy. Define them as simple strings:

```python
# In your parser, use:
from legalize.models import Rango

rango = Rango("act")  # UK
rango = Rango("statutory_instrument")  # UK
```

Add folder mappings in `src/legalize/transformer/slug.py`:

```python
RANGO_FOLDERS: dict[str, str] = {
    # ... existing ...
    # UK
    "act": "acts",
    "statutory_instrument": "statutory-instruments",
}
```

## Step 3: Register in the pipeline

### a) `src/legalize/countries.py`

Add to the `REGISTRY` dict:

```python
REGISTRY = {
    # ... existing ...
    "uk": {
        "client": ("legalize.fetcher.client_uk", "UKClient"),
        "discovery": ("legalize.fetcher.discovery_uk", "UKDiscovery"),
        "text_parser": ("legalize.fetcher.parser_uk", "UKTextParser"),
        "metadata_parser": ("legalize.fetcher.parser_uk", "UKMetadataParser"),
    },
}
```

### b) `src/legalize/web/countries.py`

Add the web config (UI strings, rangos display, source info):

```python
COUNTRIES = {
    # ... existing ...
    "uk": {
        "name": "United Kingdom",
        "lang": "en",
        "source": "legislation.gov.uk",
        "source_url": "https://www.legislation.gov.uk/",
        "github_repo": "legalize-dev/legalize-uk",
        "cta_enabled": False,
        "rangos": {
            "act": "Act",
            "statutory_instrument": "Statutory Instrument",
        },
        "strings": {
            "search": "Search",
            "reform_history": "Amendment history",
            # ... all UI strings in English ...
        },
    },
}
```

## Step 4: Create the pipeline orchestrator

Create `src/legalize/pipeline_{code}.py`:

```python
def fetch_one_uk(config, norm_id, force=False) -> NormaCompleta | None:
    """Fetch and parse one UK law."""

def fetch_all_uk(config, force=False) -> list[str]:
    """Discover and fetch all UK laws."""

def bootstrap_uk(config, dry_run=False) -> int:
    """Full bootstrap: discover + fetch + commit."""
```

**Reference:** `pipeline_fr.py`

## Step 5: Add CLI commands

In `src/legalize/cli.py`, add fetch and bootstrap commands:

```python
@cli.command("fetch-uk")
def fetch_uk(...):
    """Fetch UK legislation."""

@cli.command("bootstrap-uk")
def bootstrap_uk_cmd(...):
    """Full bootstrap for UK."""
```

## Step 6: Create the output repo

```bash
git init ../uk/
# Add README, LICENSE, .gitkeep in folder structure
```

## Step 7: Write tests

Create `tests/test_parser_{code}.py` with:
- Date parsing tests (handle country-specific formats)
- XML/HTML parsing tests with fixture data
- Metadata extraction tests
- Countries dispatch tests (`get_text_parser("uk")`)
- Slug tests (`rango_to_folder("act") == "acts"`)

## Checklist

- [ ] 4 interface implementations (client, discovery, text_parser, metadata_parser)
- [ ] Rango folder mappings in `slug.py`
- [ ] Registry entry in `countries.py`
- [ ] Web config in `web/countries.py` (name, lang, strings, rangos)
- [ ] Pipeline orchestrator `pipeline_{code}.py`
- [ ] CLI commands in `cli.py`
- [ ] Output repo initialized
- [ ] Tests passing
- [ ] Data ingested (`legalize ingest --data-dir ../data-{code}/json`)

## Architecture reference

```
User request → FastAPI route → DB (metadata) + Blob (content)
                                    ↑                ↑
                              ingest.py          ingest.py
                                    ↑                ↑
                              pipeline_{code}.py (fetch + parse + save)
                                    ↑
                              fetcher/{code} (client, discovery, parser)
                                    ↑
                              Official open data source
```

The generic layers (markdown, frontmatter, git, web) never change. Only the fetcher layer is country-specific.
