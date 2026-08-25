# Steps 2–4: Wire the country into the pipeline

> Steps 2–4 of 9 · [index](README.md) · previous: [`step-1-fetcher.md`](step-1-fetcher.md)
> If this session has been running a while, re-read [`README.md`](README.md) too — it holds every gate.

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

**Second dict in the same file: `TEXT_STATE`.** §0.5 classified your source as
`point_in_time`, `current` or `as_enacted`. Anything other than `point_in_time`
is one line here, in the same PR that adds the registry entry:

```python
TEXT_STATE: dict[str, TextState] = {
    # ... existing ...
    "xx": TextState.AS_ENACTED,  # one-line reason: what the source actually publishes
}
```

Countries absent from `TEXT_STATE` are `POINT_IN_TIME` by default. This line
decides what every published file of the country says about its own body
(Legalize Format Spec v0.3) — getting it wrong means regenerating the corpus, so
it is not optional and it is not a follow-up. A parser may override it per norm
when a source mixes cases (see `pt`).

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
      api_key: "optional"  # pragma: allowlist secret
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

Rank goes in the YAML frontmatter, never in the directory structure:

```
legalize-{code}/
  .legalize.yml   # the manifest — declares the layout below
  {code}/
    ID-2024-123.md
    ID-2024-456.md
  README.md       # in the country's language
  LICENSE         # MIT
```

**Decide the layout here, and only here.** A layout is a path template
([§Directory layout](https://github.com/legalize-dev/legalize/blob/main/SPEC.md#directory-layout)).
The two shapes most countries want:

```
{directory}/{identifier}.md                 flat
{directory}/{id_sha1_2}/{identifier}.md     sharded — 256 buckets by sha1 of the identifier
```

A placeholder is either a value the spec derives — `{directory}`, `{identifier}`,
`{id_sha1_2}` — or **any key of the law's own frontmatter**, used verbatim. So a country
whose corpus wants a different shape can have one without touching the spec, at any
depth:

```
{directory}/{series}/{id_sha1_2}/{identifier}.md
```

Two rules if you reach for a field. It must be one the source **cannot revise**: a path
built from a correctable value moves the file when the value is corrected, and that
rename lands in the history as a change no legislature made — prefer something the
identifier itself carries, since identifiers are stable within a major version. And it
must be present on **every** norm, or the path cannot be built at all; there is no
fallback bucket and `norm_to_filepath()` raises rather than guess.

**Sharded is the default answer.** Measured across 100 to 157,504 files, sharding is
never slower than flat and never produces a bigger pack; below ~250 files it simply
stops gaining. Flat costs `commits × files` in rewritten trees, and one real corpus of
171,735 files in a flat directory took 3 h 22 min just to commit and then could not be
pushed at all — GitHub rejects a pack over 2 GiB.

This is the last cheap moment to choose. The layout is not in any public URL, so
changing it breaks nothing a consumer has published — but it rewrites every path in the
repo, which means a full rebuild rather than an edit. Decide before Step 9, not after.

Declare it in one place — `layout.py::LAYOUT`, the same shape as `TEXT_STATE`:

```python
LAYOUT: dict[str, str] = {
    "xx": SHARDED,   # absent means FLAT
}
```

That entry is the whole switch. `norm_to_filepath()` builds every path from it and
`.legalize.yml` is generated from the same dict, so the manifest cannot promise a shape
the repo was not written in. Add the entry in the same PR that registers the fetcher, and
never to a country whose repo has already been built flat — that is a rebuild, not an
edit.


---

**Next → read [`step-5-daily.md`](step-5-daily.md) in full before doing anything else.**
Tick this step in your `PROGRESS.md` first.
