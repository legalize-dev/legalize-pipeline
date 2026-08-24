# Step 1: Create the fetcher package

> Step 1 of 9 · [index](README.md) · previous: [`step-0-research.md`](step-0-research.md)
> If this session has been running a while, re-read [`README.md`](README.md) too — it holds every gate.

Create `src/legalize/fetcher/{code}/` with four files.

## `__init__.py`

Re-export your classes:

```python
"""Country Name ({CODE}) -- legislative fetcher components."""

from legalize.fetcher.{code}.client import MyClient
from legalize.fetcher.{code}.discovery import MyDiscovery
from legalize.fetcher.{code}.parser import MyMetadataParser, MyTextParser

__all__ = ["MyClient", "MyDiscovery", "MyTextParser", "MyMetadataParser"]
```

## `client.py` -- LegislativeClient

Fetches raw data (XML, JSON, HTML) from the source.

**Subclass `HttpClient`, not `LegislativeClient`.** `HttpClient`
(`src/legalize/fetcher/base.py`) already gives you a `requests.Session`, a
descriptive User-Agent, a thread-safe rate limiter, retry with exponential
backoff, and timeouts. You get all of it by calling `self._get(url)`. Twenty of
the fetchers in this repo do exactly that; the ones that don't are reading a
local dump instead of HTTP (`fr`) or talking to something that isn't plain HTTP.

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from legalize.fetcher.base import HttpClient

if TYPE_CHECKING:
    from legalize.config import CountryConfig

_DEFAULT_BASE_URL = "https://official-source.gov"


class MyClient(HttpClient):
    """Client for {Country}'s official legislation source."""

    @classmethod
    def create(cls, country_config: CountryConfig) -> MyClient:
        """Instantiated by the pipeline. `.source` is your config.yaml block."""
        source = country_config.source or {}
        return cls(
            base_url=source.get("base_url", _DEFAULT_BASE_URL),
            request_timeout=int(source.get("request_timeout", 30)),
            max_retries=int(source.get("max_retries", 3)),
            requests_per_second=float(source.get("requests_per_second", 2.0)),
        )

    def get_text(self, norm_id: str) -> bytes:
        """Fetch the consolidated text of a law. Returns raw bytes."""
        return self._get(f"{self._base_url}/text/{norm_id}")

    def get_metadata(self, norm_id: str) -> bytes:
        """Return the same bytes as get_text when metadata is embedded."""
        return self._get(f"{self._base_url}/metadata/{norm_id}")
```

Notes:

- The rate limit belongs in `config.yaml`, not in the code: `requests_per_second`
  is what you will be tuning in Step 8, and it has to be changeable without a
  commit.
- `close()` and the context-manager protocol come from `HttpClient`. Don't
  reimplement them. The pipeline uses `with MyClient.create(cfg) as client:`.
- Anything beyond fetching bytes — ETag caching, an auth token, a paginated
  search endpoint your discovery needs — is a normal method on this class.

**Reference:** `fetcher/ee/client.py` (the minimal shape above, verbatim),
`fetcher/es/client.py` (adds ETag caching — primary), `fetcher/fr/client.py`
(reads a local XML dump, so it subclasses `LegislativeClient` directly).

## `discovery.py` -- NormDiscovery

Finds all law IDs in the catalog:

```python
from collections.abc import Iterator
from datetime import date

from legalize.fetcher.base import LegislativeClient, NormDiscovery


class MyDiscovery(NormDiscovery):

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Yield all norm IDs in the catalog.
        Filter OUT amendment documents -- only yield base laws."""
        import json

        page = 1
        while True:
            data = json.loads(client._get(f"{client._base_url}/laws?page={page}"))
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

Go through `client._get()` rather than `client._session`: the rate limiter and
the retries live in `_get`, and discovery is usually the chattiest part of a
bootstrap. If discovery needs a request shape the client doesn't expose, add a
method to the client — that is what `us` and `pt` do.

`NormDiscovery.create(source: dict)` exists too, and receives the same
`config.yaml` block. Override it only if discovery needs its own parameters
(year ranges, a dump path); the default calls `cls()`.

**Reference:** `fetcher/es/discovery.py` (paginates BOE API — primary), `fetcher/fr/discovery.py` (scans filesystem)

## `parser.py` -- TextParser + MetadataParser

Parses raw bytes into the generic data model. This is where quality is made or lost.
Two hard requirements you must hit:

1. **Capture every metadata field the source exposes** (Step 0.3 inventory).
2. **Preserve every rich-formatting construct the source has** (Step 0.4 inventory).

```python
from datetime import date
from typing import Any

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import Block, NormMetadata, NormStatus, Paragraph, Rank, Version

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
- **`extract_reforms()` is already implemented for you.** `TextParser.extract_reforms`
  parses the text into blocks and derives the reform timeline from the version
  dates. Override it only when the timeline lives somewhere the text doesn't —
  `se` reads the SFSR amendment register, `de` reads the standangabe metadata.
  Do not override it to reimplement the default: that is a no-op you will have to
  keep in sync.

## Metadata completeness — the contract

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

## Rich formatting — preserving what the source has

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

## Encoding — UTF-8, always

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
- `fetcher/es/parser.py` — primary reference: XML with embedded versions, reforms from `<analisis>`, jurisdictions
- `fetcher/lv/parser.py` — canonical for tables, inline bold/italic, encoding
- `fetcher/fr/parser.py` — XML with embedded versions (LEGI format)
- `fetcher/ad/parser.py` — BOPA API with multiple document kinds


---

**Next → read [`step-2-4-wiring.md`](step-2-4-wiring.md) in full before doing anything else.**
Tick this step in your `PROGRESS.md` first.
