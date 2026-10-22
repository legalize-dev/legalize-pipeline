# RESEARCH-CA: Canada — attempted, not shipped

A Canada fetcher was built in April 2026 and never merged. This note records what
exists so the next attempt starts from it rather than from zero.

## Where the work is

- PR #53 (draft, closed 2026-10-22 without merging).
- Branch `pr-46-us-ca`, tip `b434dae`, kept on GitHub. It also carries the US
  fetcher, which reached `main` separately.

## What was built

- Sources: the Justice Canada consolidated-acts Git repository (history from 2021),
  its point-in-time HTML archive (2002+), and the annual-statute bill XMLs (2001+).
- Bilingual: one jurisdiction per language (`ca-en`, `ca-fr`).
- The fetch and parse paths worked: the Criminal Code (242 point-in-time snapshots)
  parsed in about 41 s single-threaded.

## Why it stopped

- With 8 workers the bootstrap slowed from about 22 laws/min to under 1/min after
  roughly 4 hours. The cause was never isolated.
- The longest run finished 6,041 of 11,602 norms. `legalize health` and a daily
  dry-run were never reached.

## Before resuming

The branch predates the current onboarding playbook
([`adding-a-country/`](../adding-a-country/README.md)). Start again from Step 1 and
use the branch as reference, not as a base. It also changed shared pipeline and
storage code (jurisdiction-aware JSON paths, resume from cache); compare that
with `main` before reusing any of it.
