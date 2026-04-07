# Adding a New Country to Legalize

This guide is the **end-to-end playbook** for taking a country from "name only" to
a merged PR with the country repo live on legalize.dev. If you follow every step,
an AI agent (or a human) can go from zero to pushed bootstrap without extra instructions.

Reference implementations in order of recency and completeness:
- **Latvia** (`lv/`) — HTML scraping, rich tables, full metadata, ~15K laws. Canonical
  example for rich-formatting preservation.
- **Andorra** (`ad/`) — Azure Functions API + blob storage, BOPA gazette.
- **France** (`fr/`) — local LEGI XML dump with embedded versions.
- **Spain** (`es/`) — REST API with reforms-via-affected-norms daily pattern.

## Prerequisites

Before starting, you need:
- An open data source for the country's legislation (API, XML dump, or HTML)
- Understanding of the source's data format (and its licensing — must allow redistribution)
- Knowledge of the country's legal hierarchy (types of laws, reform process)
- Whether the source provides version history (amendments) or only current text

## Architecture overview

The pipeline has two layers:

**Country-specific (you write this):** fetcher that downloads and parses raw data into generic models.

**Generic (provided for free):** markdown rendering, YAML frontmatter, git commits with historical dates, CLI commands, state management, web app integration. These work automatically once your fetcher produces the right data structures.

```
Official data source
  |
  v
fetcher/{code}/          <-- you implement this
  client.py              LegislativeClient: fetch raw data
  discovery.py           NormDiscovery: find all laws
  parser.py              TextParser + MetadataParser: parse into Block/NormMetadata
  |
  v
Generic pipeline         <-- provided for free
  transformer/           Markdown rendering, frontmatter
  committer/             Git commits with historical dates
  cli.py                 Unified CLI (legalize fetch -c xx, legalize bootstrap -c xx)
  pipeline.py            Orchestration (fetch, commit, bootstrap, daily)
```

## Step 0: Research the source and inventory what it gives you

**Do not skip this step.** Every quality problem we have ever shipped (mojibake,
missing metadata, lost tables, wrong dates) was caused by skipping it. Produce a
`RESEARCH-{CC}.md` file at the workspace root (`~/autonomo/legalize/RESEARCH-XX.md`)
before writing any code.

### 0.1 Identify the source(s)

Look for **official** open data. In this order of preference:
1. Government open-data API with bulk dump (best: ES, FR, LT, LV)
2. Government REST API with pagination (AT, SE, AD)
3. HTML scraping of the official gazette (LV likumi.lv — only if nothing else exists)
4. PDF scraping (last resort — only EE Lisa uses this)

Document in `RESEARCH-{CC}.md`:
- Base URLs, endpoints, auth requirements, rate limits, licensing
- Whether historical versions are available (see "Version history strategies" below)
- Any robots.txt / Crawl-delay constraints
- Estimated total norm count and cadence of daily updates

### 0.2 Save 5 representative fixtures

Download 5 laws **by hand** and save them to `engine/tests/fixtures/{code}/`:

```
engine/tests/fixtures/{code}/
  sample-constitution.{xml,html,json}    # highest rank
  sample-code.{xml,html,json}             # a code / compilation
  sample-ordinary-law.{xml,html,json}     # a regular law
  sample-regulation.{xml,html,json}       # a decree / regulation
  sample-with-tables.{xml,html,json}      # one that has tables/images/attachments
```

Pick laws that between them exercise every structure you expect to see. If you
cannot find a law with tables, say so in the research doc — but still look hard,
because tables almost always exist in tax codes, tariff schedules, and annexes.

### 0.3 Metadata inventory — capture EVERYTHING

Open each fixture and list **every single field** the source exposes, not just the
ones the pipeline needs today. Put this list in `RESEARCH-{CC}.md` as a table:

| Source field | Type | Example | Maps to | Notes |
|---|---|---|---|---|
| `title` | string | "Ley 1/1978..." | `NormMetadata.title` | |
| `identifier` | string | "BOE-A-1978-31229" | `NormMetadata.identifier` | |
| `publication_date` | date | "1978-12-29" | `NormMetadata.publication_date` | parse dd/mm/yyyy |
| `department` | string | "Jefatura del Estado" | `NormMetadata.department` | |
| `ministry_signatory` | string | "Juan Carlos R." | `extra.signatory` | country-specific |
| `eli` | url | "https://data.../eli/..." | `extra.eli` | country-specific |
| `official_gazette_number` | string | "BOE núm. 311" | `extra.gazette_reference` | |
| `subjects` | list[string] | ["constitución", ...] | `NormMetadata.subjects` | |
| ... | | | | |

**Rule:** if the source provides it, you capture it. Fields that don't fit the
generic `NormMetadata` dataclass go into `extra` with **English snake_case keys**.
Do not editorialize which fields are "useful" — a future consumer of the data may
need any of them, and regenerating history to add fields is expensive.

### 0.4 Formatting inventory — what rich content does the source have?

Scroll through the 5 fixtures and list every rich-formatting construct you see:

- [ ] **Tables** — any `<table>`, TSV blocks, or tabular data? Tariff schedules,
      fines, dates of effect tables, annexes?
- [ ] **Bold** — inline `<b>/<strong>` or CSS classes meaning "bold"?
- [ ] **Italic** — inline `<i>/<em>` or CSS classes?
- [ ] **Lists** — ordered/unordered, nested?
- [ ] **Footnotes / endnotes** — superscript markers, reference blocks?
- [ ] **Links** — cross-references to other laws or articles?
- [ ] **Formulas** — equations, MathML, TeX?
- [ ] **Quotations** — block quotes or amending text quoted verbatim?
- [ ] **Attachments / annexes** — appendices with their own structure?
- [ ] **Signatories** — who signed, where, on what date?

Each "yes" becomes a concrete task for `parser.py`. Each "no" becomes a documented
assumption in `RESEARCH-{CC}.md` that can be verified in the quality review (Step 7).

## Step 1: Create the fetcher package

Create `src/legalize/fetcher/{code}/` with four files.

### `__init__.py`

Re-export your classes:

```python
"""Country Name ({CODE}) -- legislative fetcher components."""

from legalize.fetcher.{code}.client import MyClient
from legalize.fetcher.{code}.discovery import MyDiscovery
from legalize.fetcher.{code}.parser import MyMetadataParser, MyTextParser

__all__ = ["MyClient", "MyDiscovery", "MyTextParser", "MyMetadataParser"]
```

### `client.py` -- LegislativeClient

Fetches raw data (XML, JSON, HTML) from the source. Three methods to implement:

```python
from legalize.fetcher.base import LegislativeClient

class MyClient(LegislativeClient):

    @classmethod
    def create(cls, country_config):
        """Create from CountryConfig. Read source-specific params here.

        country_config.source is a dict from config.yaml:
            countries:
              xx:
                source:
                  base_url: "https://..."
                  api_key: "..."
        """
        base_url = country_config.source.get("base_url", "https://default.api/")
        return cls(base_url)

    def __init__(self, base_url: str):
        self._session = requests.Session()
        self._session.headers["User-Agent"] = (
            "legalize-bot/1.0 (+https://github.com/legalize-dev/legalize-pipeline)"
        )
        self._base_url = base_url

    def get_text(self, norm_id: str) -> bytes:
        """Fetch the consolidated text of a law. Returns raw bytes."""
        resp = self._session.get(f"{self._base_url}/text/{norm_id}")
        resp.raise_for_status()
        return resp.content

    def get_metadata(self, norm_id: str) -> bytes:
        """Fetch metadata. Can return same data as get_text if metadata is embedded."""
        resp = self._session.get(f"{self._base_url}/metadata/{norm_id}")
        resp.raise_for_status()
        return resp.content

    def close(self) -> None:
        self._session.close()
```

The `create()` classmethod is how the pipeline instantiates your client. It receives a `CountryConfig` whose `.source` dict comes from `config.yaml`. Override it to read source-specific parameters. The default implementation calls `cls()` with no arguments.

**Important:**
- Add rate limiting (respect the source -- typically 500ms-1s between requests)
- Add retry with backoff for 429/503 errors
- Set a descriptive `User-Agent`
- The client is a context manager (`with MyClient.create(cfg) as client:`)

**Reference:** `fetcher/fr/client.py` (reads from local XML dump), `fetcher/es/client.py` (HTTP API with caching)

### `discovery.py` -- NormDiscovery

Finds all law IDs in the catalog:

```python
from collections.abc import Iterator
from datetime import date
from legalize.fetcher.base import LegislativeClient, NormDiscovery

class MyDiscovery(NormDiscovery):

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Yield all norm IDs in the catalog.
        Filter OUT amendment documents -- only yield base laws."""
        # Example: paginate through an API
        page = 1
        while True:
            resp = client._session.get(f"https://api/laws?page={page}")
            data = resp.json()
            for item in data["results"]:
                yield item["id"]
            if not data.get("next"):
                break
            page += 1

    def discover_daily(self, client: LegislativeClient, target_date: date, **kwargs) -> Iterator[str]:
        """Yield norm IDs published/updated on a specific date."""
        # For amendments: yield the BASE law's ID, not the amendment's
        ...
```

**Reference:** `fetcher/fr/discovery.py` (scans filesystem), `fetcher/es/discovery.py` (paginates BOE API)

### `parser.py` -- TextParser + MetadataParser

Parses raw bytes into the generic data model. This is where quality is made or lost.
Two hard requirements you must hit:

1. **Capture every metadata field the source exposes** (Step 0.3 inventory).
2. **Preserve every rich-formatting construct the source has** (Step 0.4 inventory).

```python
from typing import Any
from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import Block, NormStatus, NormMetadata, Paragraph, Rank, Version

class MyTextParser(TextParser):

    def parse_text(self, data: bytes) -> list[Any]:
        """Parse raw text into Block objects.

        Each structural unit (chapter, section, article) becomes a Block.
        Each Block has one or more Versions with paragraphs.
        """
        return [
            Block(
                id="art-1",
                block_type="article",
                title="Article 1",
                versions=(
                    Version(
                        norm_id="LAW-2024-1",
                        publication_date=date(2024, 1, 15),
                        effective_date=date(2024, 1, 15),
                        paragraphs=(
                            Paragraph(css_class="articulo", text="Article 1"),
                            Paragraph(css_class="parrafo", text="Everyone has the right to..."),
                        ),
                    ),
                ),
            ),
        ]

    def extract_reforms(self, data: bytes) -> list[Any]:
        """Extract reform timeline from the text data."""
        blocks = self.parse_text(data)
        from legalize.transformer.xml_parser import extract_reforms
        return extract_reforms(blocks)


class MyMetadataParser(MetadataParser):

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        """Parse raw metadata into NormMetadata.

        Rule: every field the source exposes is captured. Generic fields go
        into the dataclass, source-specific fields go into `extra` with
        English snake_case keys.
        """
        # --- extract every source field (from Step 0.3 inventory) ---
        raw = _parse_source_metadata(data)
        title = raw["title"]
        publication_date = _parse_date(raw["publication_date"])
        department = raw.get("department", "")
        status = NormStatus.IN_FORCE if raw.get("in_force") else NormStatus.REPEALED

        # --- subjects / topics ---
        subjects = tuple(raw.get("subjects", []))

        # --- everything else the source gives us → extra ---
        extra: list[tuple[str, str]] = []
        for key in ("official_number", "eli", "gazette_reference", "signatory",
                    "entry_into_force", "expiry_date", "amendment_count",
                    "european_directive_refs", "summary_official"):
            if value := raw.get(key):
                extra.append((key, str(value)[:500]))  # cap to avoid giant frontmatter

        return NormMetadata(
            title=title,
            short_title=raw.get("short_title") or title,
            identifier=norm_id,                    # filesystem-safe
            country="xx",                          # ISO 3166-1 alpha-2
            rank=Rank(raw["rank"]),                # source-native rank string
            publication_date=publication_date,
            status=status,
            department=department,
            source=f"https://official-source.gov/law/{norm_id}",
            jurisdiction=raw.get("jurisdiction"),  # ELI code or None
            last_modified=_parse_date(raw.get("last_modified")),
            pdf_url=raw.get("pdf_url"),
            subjects=subjects,
            summary=raw.get("summary", ""),
            extra=tuple(extra),
        )
```

**Key rules for the output models:**

- `Block` -- structural unit (article, chapter, section) with versioned content
- `Version` -- a temporal version with `publication_date` and `paragraphs`
- `Paragraph` -- text + `css_class` (controls markdown rendering — see CSS→MD map below)
- `NormMetadata` -- title, id, country, rank, dates, status, plus `extra` tuple
- `identifier` must be filesystem-safe: no `:`, no spaces, no `/\*?"<>|`. Use `-` as separator. Example: SFS `1962:700` becomes `SFS-1962-700`
- `country` must be the ISO 3166-1 alpha-2 code (e.g., `"se"`, `"fr"`, `"es"`)
- `rank` is a free-form string (`Rank("act")`, `Rank("code")`, `Rank("lag")`). Goes in YAML frontmatter, not in the file path
- `extra` is a tuple of `(key, value)` pairs for country-specific metadata. These
  are rendered as additional YAML fields in the frontmatter, after the generic
  fields. Use English snake_case keys. **If the source exposes a field, it goes
  here — we do not pick and choose.**
- You can reuse `extract_reforms()` from `transformer/xml_parser.py` -- it works with any list of Blocks

### Metadata completeness — the contract

Regenerating commit history to add a forgotten metadata field is expensive (it
rewrites every bootstrap commit for that law). So the contract is: **capture
everything the source publishes, even if you do not think anyone will use it**.

Concrete checklist per norm:

- [ ] Every field in your `RESEARCH-{CC}.md` metadata inventory is either mapped
      to a `NormMetadata` dataclass field or appended to `extra`.
- [ ] Dates are parsed into `datetime.date` at the parser boundary (never strings).
- [ ] Strings are stripped and normalized to UTF-8 (see "Encoding" below).
- [ ] `extra` keys are English, snake_case, and stable (renaming a key forces a reprocess).
- [ ] Long values (e.g., multi-line gazette references) are capped to ~500 chars
      to keep frontmatter readable. If the full value matters, store a URL instead.
- [ ] Lists (subjects, tags) use `NormMetadata.subjects`, not `extra`, so the web
      app can index them uniformly.

### Rich formatting — preserving what the source has

The markdown renderer in `transformer/markdown.py` maps `Paragraph.css_class` to
Markdown formatting. The parser's job is to emit paragraphs with the right
`css_class` (or pre-formatted text) so nothing is lost.

**Paragraph-level CSS classes already recognized by the renderer:**

| css_class | Renders as | Use for |
|---|---|---|
| `titulo_tit`, `titulo_num` | `## {text}` | Top-level titles (libro, título) |
| `capitulo_tit`, `capitulo_num` | `### {text}` | Chapters |
| `seccion` | `#### {text}` | Sections |
| `articulo` | `##### {text}` | Article headings |
| `parrafo` (or any unknown class) | `{text}` | Body paragraphs |
| `centro_negrita` | `# {text}` | Centered bold (title pages) |
| `firma_rey` | `**{text}**` | Signatories, bold-emphasized lines |
| `list_item` | `{text}` | Individual list items (you add `- ` prefix) |
| `table_row` | `{text}` | Individual table rows (you emit full MD pipe rows) |
| `pre` | ```` ```{text}``` ```` | Preformatted code / math |

**How to handle each construct from the Step 0.4 inventory:**

1. **Tables** → emit a single `Paragraph(css_class="table", text=<full MD pipe table>)`.
   The unknown `css_class` passes through as plain text, so your pre-formatted
   Markdown table reaches the file untouched. Use `fetcher/lv/parser.py`
   (`_table_to_markdown`, `_parse_table_div`) as the reference — it handles
   rowspan/colspan, empty cells, and header rows.

2. **Bold / italic (paragraph-level)** → reuse `firma_rey` (renders as `**...**`)
   for bold lines. For italic, pre-wrap the text: `Paragraph(css_class="parrafo", text=f"*{text}*")`.

3. **Bold / italic (inline, mid-paragraph)** → the CSS→MD map is paragraph-level,
   so inline formatting must be **pre-wrapped in the parser**. Walk the source
   node's children; for each `<b>`/`<strong>` wrap the text in `**`, for each
   `<i>`/`<em>` wrap in `*`, then flatten to one string. See
   `fetcher/lv/parser.py::_inline_text` for the pattern.

4. **Lists** → emit one `Paragraph(css_class="list_item", text=f"- {item}")` per
   item. For nested lists, prefix with two spaces per level. For ordered lists,
   use `- 1. {item}` (Markdown renders correctly).

5. **Footnotes** → two options: (a) inline with `[^1]` markers and a footnote
   block at the end of the article; (b) parenthetical `(see footnote: ...)`. Pick
   the one that round-trips best from the source; document your choice in
   `RESEARCH-{CC}.md`.

6. **Links / cross-references** → emit Markdown links: `[art. 5](#art-5)` for
   internal refs, `[Ley 2/2024](https://...)` for external. Do not strip the
   reference — legal cross-references are core content.

7. **Images / figures** → **explicitly skipped.** We are not ready for binary
   assets in the repo. Drop image nodes in the parser and, if the norm relied on
   the image for meaning, append a note `[image omitted]` in place. Record the
   count of dropped images in `extra.images_dropped` so we can come back later.

8. **Formulas / math** → wrap in `$...$` (LaTeX-style) if the source has MathML
   or TeX; otherwise keep as plain text with a note in `extra.has_formulas`.

9. **Quotations / amending text** → use Markdown blockquote: prefix each line
   with `> `. Put this on a `Paragraph(css_class="parrafo", text="> ...")`.

10. **Attachments / annexes** → render as a new Block with `block_type="annex"`
    and the annex number in the title: `Block(id="annex-i", title="Annex I", ...)`.
    Same rules apply to the annex body.

11. **Signatories** → `Paragraph(css_class="firma_rey", text=...)`.

If the source has a rich construct that is not in this list, **do not silently
drop it**. Add a new `css_class` + renderer entry in `transformer/markdown.py`
and document it here.

### Encoding — UTF-8, always

Every parser MUST output valid UTF-8 text with no C0/C1 control characters.

- Decode source bytes explicitly: `data.decode("utf-8")`. If the source is
  Latin-1 / Windows-1252 / ISO-8859-*, decode with the correct codec and
  re-encode as UTF-8. **Never rely on `requests` auto-detection** — it has
  gotten us mojibake twice (LV bootstrap 2026-04-07).
- Strip C0/C1 controls before emitting paragraphs:
  ```python
  import re
  _CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
  text = _CTRL.sub("", text)
  ```
- Normalize whitespace (`\s+` → ` `, strip) at the paragraph boundary.
- Replace non-breaking spaces (`\u00a0`) with regular spaces unless they are
  semantically meaningful (e.g., in French "M. Dupont").

The sync-to-DB step in `web/scripts/sync_from_git.py` will fail loudly on bad
UTF-8, so a clean parser saves hours of bootstrap rework.

**Reference implementations:**
- `fetcher/lv/parser.py` — canonical for tables, bold, metadata completeness, encoding
- `fetcher/ad/parser.py` — BOPA API with multiple document kinds
- `fetcher/fr/parser.py` — XML with embedded versions
- `fetcher/es/parser.py` — XML with reforms extracted from `<analisis>`

## Step 2: Register in `countries.py`

Add your country to the `REGISTRY` dict in `src/legalize/countries.py`:

```python
REGISTRY: dict[str, dict[str, tuple[str, str]]] = {
    # ... existing ...
    "xx": {
        "client": ("legalize.fetcher.xx.client", "MyClient"),
        "discovery": ("legalize.fetcher.xx.discovery", "MyDiscovery"),
        "text_parser": ("legalize.fetcher.xx.parser", "MyTextParser"),
        "metadata_parser": ("legalize.fetcher.xx.parser", "MyMetadataParser"),
    },
}
```

The registry uses lazy imports -- your module is only loaded when the country is selected. This keeps startup fast and avoids importing dependencies for countries that aren't being used.

Once registered, the unified CLI commands work automatically:
- `legalize fetch -c xx`
- `legalize bootstrap -c xx`
- `legalize commit -c xx`

## Step 3: Add config.yaml section

Add your country's configuration:

```yaml
countries:
  xx:
    repo_path: "../countries/xx"           # output git repo
    data_dir: "../countries/data-xx"       # raw data + parsed JSON
    cache_dir: ".cache"
    max_workers: 1
    source:                      # passed to client.create() as country_config.source
      base_url: "https://api.example.gov/legislation"
      api_key: "optional"
      # any key-value pairs your client needs
```

The `source` dict is passed through to your client's `create()` classmethod via `country_config.source`. Put any source-specific configuration there.

## Step 4: Plan the output repo structure

**Do not create the GitHub repo yet.** Creating it now means a public, empty repo
sits on the org while you debug the parser, and a failed bootstrap leaves
garbage in the public history. The repo is created for real in Step 9.1, after
the 5-law quality gate passes.

For Step 7 (sample bootstrap) you will init a **local-only** sandbox repo under
`../countries/{code}/` with no remote. That's fine — the pipeline only needs a
git directory to commit to.

The final output structure is flat — all laws in `{country_dir}/`, rank goes in
YAML frontmatter:

```
legalize-{code}/
  {code}/
    ID-2024-123.md
    ID-2024-456.md
  README.md       # in the country's language
  LICENSE         # MIT
```

The `norm_to_filepath()` function generates `{country}/{identifier}.md` automatically.

## Step 5: Daily processing

Most countries use `generic_daily` from `pipeline.py`, which handles the standard flow: discover → fetch → parse → commit. **You don't need a custom daily.py** unless your country has a non-standard daily flow (e.g., Spain resolves reform dispositions, France processes incremental tar.gz dumps).

Countries using `generic_daily` (no custom daily.py needed): DE, SE, AT, CL, LT, PT, UY.
Countries with custom daily.py: ES (`fetcher/es/daily.py`), FR (`fetcher/fr/daily.py`).

If you do need a custom flow, create `src/legalize/fetcher/{code}/daily.py` with a `daily()` function. The CLI dispatches to this file via dynamic import (`legalize.fetcher.{code}.daily`).

```python
from datetime import date
from legalize.config import Config
from legalize.state.store import StateStore, resolve_dates_to_process

def daily(
    config: Config,
    target_date: date | None = None,
    dry_run: bool = False,
) -> int:
    """Daily processing for {country}: discover + fetch + commit new norms."""
    from legalize.fetcher.{code}.client import MyClient
    from legalize.fetcher.{code}.discovery import MyDiscovery
    from legalize.fetcher.{code}.parser import MyMetadataParser, MyTextParser

    cc = config.get_country("{code}")
    state = StateStore(cc.state_path)
    state.load()

    # Determine dates to process (includes safety cap + weekday filter)
    dates_to_process = resolve_dates_to_process(
        state, cc.repo_path, target_date,
        skip_weekdays={6},  # adapt to source's schedule
    )
    if dates_to_process is None:
        console.print("[yellow]No last date found. Use --date or run bootstrap.[/yellow]")
        return 0
    if not dates_to_process:
        console.print("[green]Nothing to process — up to date[/green]")
        return 0

    # For each date: discover → fetch → commit
    with MyClient.create(cc) as client:
        for current_date in dates_to_process:
            norm_ids = list(discovery.discover_daily(client, current_date))
            for norm_id in norm_ids:
                # fetch metadata + text
                # render markdown
                # write_and_add + commit
                ...
            state.last_summary_date = current_date

    state.save()
    return commits_created
```

The flow is always the same — the country-specific part is how you discover and fetch. See `fetcher/at/daily.py` (API-based) and `fetcher/es/daily.py` (sumario-based) for complete examples.

**Key responsibilities:**
- Determine which dates need processing (state tracking via `StateStore`)
- Call `discover_daily()` for each date
- Fetch + parse + render markdown for each norm
- Create git commits with appropriate `CommitType` (NEW, REFORM, CORRECTION)
- Update `state.last_summary_date` after each date
- Handle `--dry-run` (print what would happen, don't commit)
- Handle `config.git.push` (push to remote after commits)

### Date resolution (centralized)

Use `resolve_dates_to_process()` from `state/store.py` instead of writing the date logic by hand. It handles state inference, git fallback, the 10-day safety cap, and weekday filtering:

```python
from legalize.state.store import StateStore, resolve_dates_to_process

state = StateStore(cc.state_path)
state.load()

dates_to_process = resolve_dates_to_process(
    state, cc.repo_path, target_date,
    skip_weekdays={6},  # skip Sunday (Mon-Sat schedule)
)
if dates_to_process is None:
    console.print("[yellow]No last date found. Use --date or run bootstrap.[/yellow]")
    return 0
if not dates_to_process:
    console.print("[green]Nothing to process — up to date[/green]")
    return 0
```

The safety cap (10 days) prevents accidentally processing months of history when no `--date` is given (e.g., first CI run after setup, or after a long outage). Users can still process older dates explicitly with `--date`.

Common `skip_weekdays` values:
- `{6}` — Mon-Sat (ES, FR, CL)
- `{5, 6}` — Mon-Fri (AT, PT)
- `None` — all days (LT)

### Handling reforms (affected norms pattern)

Many data sources publish reform dispositions (amendments) before updating the consolidated text of the affected law. This means fetching the reform disposition itself may return 404 or stale data. The solution: **process the affected (reformed) norms instead of the reform disposition**.

The pattern:

1. **Classify** each daily entry as NEW, CORRECTION, or REFORM. How you detect this depends on the source — it could be a field in the metadata, a keyword in the title, or a document type code.
2. **New/Correction** → try to download the entry itself, skip on 404 (not consolidated yet)
3. **Reform** → resolve which existing laws it modifies, then re-download those:

```python
# 1. Resolve affected norm IDs.
#    How: fetch the raw entry document (not consolidated text) and parse its
#    analysis/reference section. Each source has its own format — the key is
#    extracting the IDs of the laws being modified.
affected_ids = resolve_affected_norms(client, entry)

# 2. For each affected norm already in the repo:
for affected_id in affected_ids:
    # Idempotency: use 2-arg form (Source-Id + Norm-Id pair).
    # One reform can affect multiple norms — checking only source_id
    # would block processing after the first one.
    if repo.has_commit_with_source_id(entry.id, affected_id):
        continue

    # Re-download the consolidated text (bypass cache — we need the updated version)
    meta_xml = client.get_metadata(affected_id)
    text_xml = client.get_text(affected_id, bypass_cache=True)

    # Skip norms we don't track (lower-rank regulations, etc.)
    if not (repo_root / file_path).exists():
        continue

    # Render, compare, and commit as REFORM.
    # Source-Id = the reform entry (what caused the change)
    # Norm-Id = the affected law (what changed)
    reform = Reform(date=current_date, norm_id=entry.id, affected_blocks=())
    info = build_commit_info(CommitType.REFORM, metadata, reform, ...)
```

**Key details:**
- `bypass_cache=True` forces a fresh download — the source may have updated the consolidated text since our last fetch
- Idempotency uses the 2-arg `has_commit_with_source_id(source_id, norm_id)` — one reform can affect multiple norms
- The commit's `Source-Id` trailer is the reform entry (what caused the change), `Norm-Id` is the affected law (what changed)
- Norms not in the repo are silently skipped
- If the source hasn't updated the consolidated text yet, `write_and_add()` detects no change — no commit is created

**Data source latency:** Some sources populate the analysis/reference metadata asynchronously — fresh entries may not list affected norms for 1-2 days. In normal daily operation this is fine: today's run processes dates from a few days ago, when references are already populated. For backfill runs (processing months of past data), all references will be available.

**Reference:** `fetcher/es/daily.py` implements this pattern for Spain's BOE, resolving affected norms from the raw disposition XML's `<analisis>` section.

## Step 6: Write tests

Create `tests/test_parser_{code}.py` with fixture data (and optionally `tests/test_daily_{code}.py`):

```python
import pytest
from legalize.fetcher.{code}.parser import MyTextParser, MyMetadataParser
from legalize.countries import get_text_parser, get_metadata_parser

# Save sample data from your source in tests/fixtures/

class TestParser:
    def test_parse_text(self):
        data = Path("tests/fixtures/sample_{code}.xml").read_bytes()
        parser = MyTextParser()
        blocks = parser.parse_text(data)
        assert len(blocks) > 0
        assert blocks[0].versions  # has at least one version

    def test_metadata(self):
        data = Path("tests/fixtures/sample_{code}_meta.xml").read_bytes()
        parser = MyMetadataParser()
        meta = parser.parse(data, "NORM-ID-123")
        assert meta.country == "xx"
        assert meta.identifier == "NORM-ID-123"

    def test_filesystem_safe_id(self):
        # Ensure no colons, spaces, or special chars
        meta = ...
        assert ":" not in meta.identifier
        assert " " not in meta.identifier

class TestCountryDispatch:
    def test_registry(self):
        parser = get_text_parser("xx")
        assert isinstance(parser, MyTextParser)
```

## Step 7: Fetch a 5-law sample and quality-review it (MANDATORY GATE)

**This is the gate that separates "parser compiles" from "ready to bootstrap".**
Do not skip it and do not run the full bootstrap until every item below is green.

### 7.1 Fetch and render 5 representative laws

Pick 5 laws that between them exercise every structure you found in Step 0.4
(different ranks, at least one with tables, at least one with footnotes if the
source has them). Fetch them explicitly by ID so you get the **same** set every
time you iterate:

```bash
# Option A: fetch by explicit IDs
legalize fetch -c xx --id LAW-2024-1 --id LAW-2024-42 --id LAW-1998-100 \
                     --id LAW-2012-5 --id LAW-2023-TARIFF

# Option B: limit-based (less reproducible, OK for first smoke test)
legalize fetch -c xx --all --limit 5
```

Then render them into a sandbox country repo (do NOT push):

```bash
# Create a throwaway repo for the sample
git init ../countries/xx/
mkdir -p ../countries/xx/xx
git -C ../countries/xx commit --allow-empty -m "[bootstrap] Init sample"

# Dry-run first to see what would happen
legalize bootstrap -c xx --dry-run --limit 5

# Actually produce the 5 MD files
legalize bootstrap -c xx --limit 5
```

You should now have 5 files under `../countries/xx/xx/*.md`.

### 7.2 AI quality review — the 5 checks

Open a fresh Claude Code session in the workspace and paste the prompt below.
The agent will read each MD next to its source fixture and grade the parser on
five dimensions. **The parser is not ready until the agent reports all five as
PASS for all 5 laws.**

Ready-to-paste review prompt:

```text
You are reviewing a new-country parser for the legalize-pipeline repo.

Read these 5 generated MD files:
  ../countries/xx/xx/LAW-2024-1.md
  ../countries/xx/xx/LAW-2024-42.md
  ../countries/xx/xx/LAW-1998-100.md
  ../countries/xx/xx/LAW-2012-5.md
  ../countries/xx/xx/LAW-2023-TARIFF.md

And their source fixtures:
  engine/tests/fixtures/xx/sample-*.{html,xml,json}

Plus the research doc: RESEARCH-XX.md

For EACH of the 5 laws, grade PASS / FAIL on these five checks and explain any FAIL:

1. TEXT CORRECTNESS
   - No mojibake (Ã©, â€œ, \x00, replacement chars).
   - No leftover HTML/XML tags in the body.
   - No truncated sentences, no duplicated paragraphs.
   - UTF-8 clean (try `file ../countries/xx/xx/*.md`).

2. METADATA COMPLETENESS
   - Every field listed in RESEARCH-XX.md §0.3 metadata inventory is present
     either in the dataclass fields or in `extra:` in the frontmatter.
   - Dates are ISO-8601 (YYYY-MM-DD), not localized strings.
   - Identifier matches the filename and is filesystem-safe.
   - `source:` URL opens the correct page on the official site.

3. STRUCTURE PRESERVATION
   - Heading levels match the source hierarchy (title > chapter > section > article).
   - Article numbers and titles are correct and in order.
   - No articles skipped, no articles duplicated.
   - Annexes rendered as their own blocks.

4. RICH FORMATTING
   - Tables in the source render as Markdown pipe tables (with headers).
   - Bold / italic in the source are preserved (inline ** or *).
   - Lists in the source are real Markdown lists, not flattened paragraphs.
   - Cross-references are rendered as Markdown links.
   - Quoted / amending text uses blockquotes.
   - Signatories are bold at the end.
   - If the source has NONE of a construct, note it ("no tables in sample").

5. ENCODING & HYGIENE
   - `grep -P '[\x00-\x08\x0b\x0c\x0e-\x1f]'` on all 5 files returns nothing.
   - No `\r\n` line endings (Unix-only).
   - File ends with a single newline.
   - No trailing spaces on lines.

For any FAIL, quote the offending excerpt and point to the probable cause in
fetcher/xx/parser.py (which function, which class). Do not fix code — only
report. I will iterate on the parser based on your findings.

Report format:
  Law 1 (LAW-2024-1):
    1. TEXT CORRECTNESS: PASS
    2. METADATA: FAIL — `gazette_reference` missing from extra (see source pase-container)
    3. STRUCTURE: PASS
    4. FORMATTING: FAIL — table in annex II rendered as flat text (see lines 340-352)
    5. ENCODING: PASS
  Law 2: ...
  ...
  SUMMARY: X/5 laws fully PASS, top 3 issues to fix first: ...
```

### 7.3 Iterate until 5/5 PASS

Every FAIL points at a parser bug. Fix, re-fetch with `--force`, re-render, and
re-run the review. Typical iteration loop:

```bash
# Edit fetcher/xx/parser.py
legalize fetch -c xx --id LAW-2024-1 --id LAW-2024-42 ... --force
legalize reprocess -c xx --reason "parser fix" LAW-2024-1 LAW-2024-42 ...
# (or simpler: rm -rf ../countries/xx && re-init and re-bootstrap --limit 5)
```

Do not move on until the reviewer returns `SUMMARY: 5/5 laws fully PASS`.

### 7.4 Manual spot-check (2 minutes)

Even after the AI review passes, open one MD and its source side-by-side in a
browser. Look at:
- The title line matches the official title exactly.
- The first article reads naturally in the country's language.
- A table (if present) is readable and has the right column count.
- The frontmatter YAML parses without errors: `python -c "import yaml; yaml.safe_load(open('file.md').read().split('---')[1])"`

## Step 8: Tune `max_workers` for the full bootstrap

Before running a full bootstrap, test the source API's capacity to set the right
`max_workers` in `config.yaml`. Each worker creates its own client with its own
rate limiter, so `max_workers: 8` at `requests_per_second: 2.0` = 16 req/sec total.

```bash
# 1. Quick benchmark: fetch 50 laws with 1 worker, note the time
time legalize fetch -c xx --all --limit 50

# 2. Increase max_workers in config.yaml (try 4, then 8)
# 3. Re-run the same 50 laws with --force to bypass cache
time legalize fetch -c xx --all --limit 50 --force

# 4. Check for errors — if the API returns 429 (rate limit) or
#    connection errors, reduce max_workers or requests_per_second
# 5. Estimate total time: (total_laws / laws_per_minute) / 60 = hours
```

Reference benchmarks from existing countries:

| Country | Laws | API type | max_workers | req/sec | Fetch time |
|---------|------|----------|-------------|---------|------------|
| ES | 1,065 | REST (BOE) | 1 | 2 | ~2h |
| FR | 83 | Local XML dump | 1 | N/A | ~5min |
| DE | 5,729 | ZIP download | 1 | 2 | ~1h |
| AT | 4,000+ | REST (RIS) | 8 | 2 | ~30min |
| LT | 14,957 | REST (data.gov.lt) | 8 | 2 | ~1-2h |
| LV | 48,490 (15K with content) | HTML scraping (likumi.lv) | 12 | 2 | ~70min |
| AD | 3,537 | Azure Functions API | 8 | 2 | ~45min |

Government open data APIs typically handle 10-20 req/sec without issues.
Commercial/rate-limited APIs may need `max_workers: 1`.

**HTML scraping note** (Latvia case): when the source has no API and you must scrape HTML pages, the parser becomes CPU-bound on lxml HTML parsing instead of network-bound. With `max_workers: 12 × requests_per_second: 2`, Latvia hit ~9 req/s effective (CPU was the bottleneck, not the server). The `robots.txt` `Crawl-delay: 1` directive is a politeness baseline; many state publishers tolerate higher rates without errors. Always test conservatively first and back off if the server returns 429/503 or starts dropping connections.

## Step 9: Full bootstrap and push to production

This is the last step. By now the 5-law review has passed and parallelism is tuned.

### 9.1 Create the GitHub repo

```bash
gh repo create legalize-dev/legalize-{code} --public \
  --description "Legislation from {Country} in Markdown, version-controlled with Git"

# Wipe the sandbox repo from Step 7 and re-init clean
rm -rf ../countries/xx
git init ../countries/xx/
mkdir -p ../countries/xx/xx
git -C ../countries/xx commit --allow-empty -m "[bootstrap] Init legalize-{code}"
git -C ../countries/xx remote add origin git@github.com:legalize-dev/legalize-{code}.git
git -C ../countries/xx push -u origin main
```

Add a README in the country's language and an MIT LICENSE. Copy the structure
from an existing country repo (`legalize-lv`, `legalize-ad`).

### 9.2 Run the full bootstrap

```bash
# Kick off the bootstrap. Tail the log to a file so you can review afterwards.
legalize bootstrap -c xx 2>&1 | tee bootstrap-xx.log

# For long runs, use nohup + background
nohup legalize bootstrap -c xx > bootstrap-xx.log 2>&1 &
```

Watch `bootstrap-xx.log` for:
- Fetch errors (429, 500, connection resets) → reduce workers and restart
- Parser warnings → investigate; the 5-law review should have caught these
- Commit errors → usually date parsing; fix and `legalize reprocess`

### 9.3 Health check before pushing

```bash
legalize health -c xx                  # full scan
legalize health -c xx --sample 500     # sampled scan for big repos
```

`health` verifies: commit dates, empty files, remote configured, orphan files
(files in repo with no entry in state), frontmatter validity. **Every issue
reported must be zero before pushing.**

### 9.4 Push to origin

```bash
# Push main with full history
git -C ../countries/xx push origin main

# If the remote rejects (large push), push in batches
git -C ../countries/xx push origin main --force-with-lease  # only if you own the repo
```

### 9.5 Open the engine PR

```bash
cd engine
git checkout -b feat/{code}-initial
git add src/legalize/fetcher/{code}/ src/legalize/countries.py config.yaml \
        tests/test_parser_{code}.py tests/fixtures/{code}/
git commit -m "feat({code}): add {Country} fetcher + bootstrap"
git push -u origin feat/{code}-initial
gh pr create --fill --base main
```

CI will run the full test suite + the per-country smoke test. Wait for green.

### 9.6 Wire the web sync

Once the engine PR is merged and the country repo has commits:

```bash
cd ../web
# Add {code} to the country list in api/countries.py
# Add the language mapping in src/i18n if needed
# Add the country to the sync workflow matrix
git checkout -b feat/{code}-web
# ... edit ...
git commit -m "feat({code}): enable {Country} in web app"
git push -u origin feat/{code}-web
gh pr create --fill --base main
```

The daily sync cron (`web/.github/workflows/sync.yml`) will pick up the new
country automatically on the next run. To sync immediately:

```bash
gh workflow run sync.yml -R legalize-dev/legalize-web -f country={code}
```

### 9.7 Verify on production

- Visit https://legalize.dev/{code} and confirm the country appears.
- Click through to a law and confirm the text, metadata, and reform history render.
- Open a law with a table (from your Step 0.4 inventory) and confirm it renders.
- Switch the UI language to the country's native language and confirm translations.

### 9.8 Update the memory and MEMORY.md

Save a one-line memory recording the country as shipped (date, law count, any
quirks discovered during bootstrap). Delete `RESEARCH-{CC}.md` from the workspace
root only after all the above is verified green.

## Final checklist — do not ship with any box unchecked

### Research (Step 0)
- [ ] `RESEARCH-{CC}.md` exists at workspace root with source + licensing + API details
- [ ] 5 representative fixtures saved under `engine/tests/fixtures/{code}/` (different ranks, at least one with tables)
- [ ] Metadata inventory table in research doc lists **every** field the source exposes
- [ ] Formatting inventory in research doc covers tables, bold, italic, lists, footnotes, links, formulas, quotations, annexes, signatories (images skipped)

### Fetcher (Step 1)
- [ ] `fetcher/{code}/__init__.py` — re-exports all classes
- [ ] `fetcher/{code}/client.py` — with `create()`, rate limiting, retry, UTF-8 decoding
- [ ] `fetcher/{code}/discovery.py` — `discover_all()` and `discover_daily()`
- [ ] `fetcher/{code}/parser.py` — `TextParser` and `MetadataParser`
- [ ] **Every field in the §0.3 metadata inventory** is captured (dataclass or `extra`)
- [ ] **Every construct in the §0.4 formatting inventory** is preserved (tables → pipe MD, bold → `**`, italic → `*`, lists → `-`, links → `[...]()`, quotes → `>`, signatories → `firma_rey`)
- [ ] Parser strips C0/C1 control chars and enforces UTF-8
- [ ] Images are dropped and counted in `extra.images_dropped`

### Wiring (Steps 2–4)
- [ ] `countries.py` — registry entry added
- [ ] `config.yaml` — country section with `repo_path`, `data_dir`, `source`, `max_workers`
- [ ] GitHub repo `legalize-dev/legalize-{code}` created (public, MIT) with README in local language

### Tests (Step 6)
- [ ] `tests/test_parser_{code}.py` — passing against the 5 fixtures
- [ ] `tests/test_countries.py::test_registry_{code}` — passing
- [ ] `ruff check src/legalize/fetcher/{code}/ tests/` — clean

### Quality gate (Step 7) — MANDATORY
- [ ] 5 sample laws fetched and bootstrapped into sandbox repo
- [ ] AI review returned `SUMMARY: 5/5 laws fully PASS` for TEXT, METADATA, STRUCTURE, FORMATTING, ENCODING
- [ ] Manual spot-check of one MD side-by-side with source — OK

### Daily path (Step 5)
- [ ] `legalize daily -c {code} --date YYYY-MM-DD --dry-run` works
- [ ] Reform path tested: a date with reforms resolves affected norms and creates commits
- [ ] Idempotency tested: re-running the same date produces 0 duplicate commits

### Production (Steps 8–9)
- [ ] Parallelism tuned against a 50-law benchmark
- [ ] Full `legalize bootstrap -c {code}` run completed without errors
- [ ] `legalize health -c {code}` reports zero issues
- [ ] Country repo pushed to `legalize-dev/legalize-{code}`
- [ ] Engine PR merged on `legalize-pipeline`
- [ ] Web PR merged on `legalize-web` and daily sync triggered
- [ ] `https://legalize.dev/{code}` live and renders a table-containing law correctly
- [ ] Memory updated and `RESEARCH-{CC}.md` deleted

## Version history strategies

Different countries provide different levels of historical data:

| Strategy | Example | What you get |
|----------|---------|-------------|
| **Embedded versions** | Spain (BOE), France (LEGI) | Full text at every point in time. Best case. |
| **Amendment register** | Sweden (SFSR) | Timeline of which sections changed when, but only current text. Dates are approximate (Jan 1 of the SFS year) — multiple reforms per year share the same date. |
| **Historical snapshots table** | Lithuania (Suvestine) | Separate API table with full text at each historical date. Pipeline fetches each version individually. |
| **Snapshots over time** | Germany (gesetze-im-internet) | Only current text. Build history by re-downloading periodically. |
| **Point-in-time API** | UK (legislation.gov.uk) | Request any law at any date via URL parameter. |

Choose the strategy that matches your data source. The pipeline supports all of them -- the `Reform` model is flexible enough for any.

## Subnational jurisdictions

If a country has subnational legislation (e.g., Spain's autonomous communities, Germany's Bundesländer), use the `jurisdiction` field in `NormMetadata`.

We follow the [ELI (European Legislation Identifier)](https://eur-lex.europa.eu/eli-register/what_is_eli.html) standard: `{country}` for national, `{country}-{region}` for subnational.

```
legalize-es/
  es/              # national
  es-pv/           # País Vasco
  es-ct/           # Catalunya
```

The `norm_to_filepath()` function handles this automatically based on `metadata.jurisdiction`.

All subnational laws live in the same repo as national laws.
