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

**Decide the layout here, and only here.** The spec defines two shapes
([§Directory layout](https://github.com/legalize-dev/legalize/blob/main/SPEC.md#directory-layout)):

```
{directory}/{identifier}.md                 flat
{directory}/{id_sha1_2}/{identifier}.md     sharded — 256 buckets by sha1 of the identifier
```

**Sharded is the default answer.** Measured across 100 to 157,504 files, sharding is
never slower than flat and never produces a bigger pack; below ~250 files it simply
stops gaining. Flat costs `commits × files` in rewritten trees, and one real corpus of
171,735 files in a flat directory took 3 h 22 min just to commit and then could not be
pushed at all — GitHub rejects a pack over 2 GiB.

This is the last cheap moment to choose. The layout is not in any public URL, so
changing it breaks nothing a consumer has published — but it rewrites every path in the
repo, which means a full rebuild rather than an edit. Decide before Step 9, not after.

> **Not implemented yet.** `norm_to_filepath()` emits flat for every country today, and
> nothing writes `.legalize.yml`. Until that lands, record the decision in
> `RESEARCH-{CC}.md` and ship flat. Delete this note when the engine reads a per-country
> layout.


---

**Next → read [`step-5-daily.md`](step-5-daily.md) in full before doing anything else.**
Tick this step in your `PROGRESS.md` first.
