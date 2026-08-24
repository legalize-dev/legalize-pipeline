# Reference

Background consulted out of order. Not part of the step sequence —
nothing here is a gate.

## Version history strategies

**Reminder: historical versions are the product.** Pick the strategy that
gives you the most coverage for your source, not the easiest one. A day spent
getting the version walk right saves a week of history regeneration later.

Different countries expose their history differently:

| Strategy | Example | What you get |
|----------|---------|-------------|
| **Embedded versions** | Spain (BOE), France (LEGI) | Full text at every point in time. Best case. Parser emits one Version per embedded entry. |
| **Archived-version URLs** | Belgium (Justel `arch=N`) | Separate HTTP endpoint per historical version. Fetcher walks `arch=1..N` for every law, parses each page, extracts the effective date. Expensive but complete. |
| **Amendment register** | Sweden (SFSR) | Timeline of which sections changed when, but only current text. Dates are approximate (Jan 1 of the SFS year) — multiple reforms per year share the same date. |
| **Historical snapshots table** | Lithuania (Suvestine) | Separate API table with full text at each historical date. Pipeline fetches each version individually. |
| **Point-in-time API** | UK (legislation.gov.uk) | Request any law at any date via URL parameter. |
| **Snapshots over time** (temporary) | Germany (gesetze-im-internet) | Only current text. History is built by re-downloading periodically. **This is a fallback pattern for sources with no archive — not a target.** |

Choose the strategy that matches your data source. The pipeline supports all
of them — the `Reform` model is flexible enough for any. When in doubt, spend
an extra day on research in Step 0 to find the archive pattern; it is always
cheaper than fixing history after the fact.

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
