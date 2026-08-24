# Step 5: Daily processing

> Step 5 of 9 · [index](README.md) · previous: [`step-2-4-wiring.md`](step-2-4-wiring.md)
> If this session has been running a while, re-read [`README.md`](README.md) too — it holds every gate.

Most countries use `generic_daily` from `pipeline.py`, which handles the standard flow: discover → fetch → parse → commit. **You don't need a custom daily.py** unless your country has a non-standard daily flow (e.g., Spain resolves reform dispositions, France processes incremental tar.gz dumps).

## When to use `generic_daily` vs. a custom `daily.py`

| Use `generic_daily` when... | Write a custom `daily.py` when... |
|---|---|
| Daily entries map 1:1 to consolidated laws | Daily entries are reform dispositions that affect other laws |
| `discover_daily()` returns the IDs you commit | You need to resolve affected norms from a reform's analysis section |
| The source updates consolidated text same-day | There is a latency window before consolidated text is updated |
| No date-dependent logic beyond "fetch norms for this date" | The daily flow needs multiple passes (classify → resolve → fetch) |

**Rule of thumb:** if `discover_daily()` yields the exact norm IDs whose files you
want to update, `generic_daily` works. If it yields reform dispositions whose
*affected* norms you need to resolve, write a custom `daily.py`.

Countries using `generic_daily` (no custom daily.py needed): DE, SE, AT, CL, LT, PT, UY, LV, BE.
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

The flow is always the same — the country-specific part is how you discover and fetch. See `fetcher/ee/daily.py` (bulk-dump diff, preserves the version chain), `fetcher/pt/daily.py` (new diplomas plus re-consolidations, which arrive on different days) and `fetcher/es/daily.py` (sumario-based) for complete examples.

**Key responsibilities:**
- Determine which dates need processing (state tracking via `StateStore`)
- Call `discover_daily()` for each date
- Fetch + parse + render markdown for each norm
- Create git commits with appropriate `CommitType` (NEW, REFORM, CORRECTION)
- Update `state.last_summary_date` after each date
- Handle `--dry-run` (print what would happen, don't commit)
- Handle `config.git.push` (push to remote after commits)

## Date resolution (centralized)

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

## Handling reforms (affected norms pattern)

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


---

**Next → read [`step-6-tests.md`](step-6-tests.md) in full before doing anything else.**
Tick this step in your `PROGRESS.md` first.
