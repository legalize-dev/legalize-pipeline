# Step 8: Tune `max_workers` for the full bootstrap

> Step 8 of 9 · [index](README.md) · previous: [`step-7-quality-gate.md`](step-7-quality-gate.md)
> If this session has been running a while, re-read [`README.md`](README.md) too — it holds every gate.

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


---

**Next → read [`step-9-production.md`](step-9-production.md) in full before doing anything else.**
Tick this step in your `PROGRESS.md` first.
