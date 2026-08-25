# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. Project-wide rules and policies live here. For module-by-module code reference see [ARCHITECTURE.md](ARCHITECTURE.md). For the end-to-end country onboarding playbook see [adding-a-country/](adding-a-country/README.md).

## Project Overview

Legalize is a multi-country platform that converts official legislation into version-controlled Markdown. Each law is a file, each reform is a git commit. The public country repos are the product; this repo is the pipeline that generates them.

**Website:** https://legalize.dev

**Source of truth for the country list:** the `REGISTRY` dict in `src/legalize/countries.py` and the `countries:` section of `config.yaml`. Do not maintain a duplicate list elsewhere — read those two files when you need to know what is supported.

## Local workspace

```
~/autonomo/legalize/
├── engine/              ← this repo (legalize-pipeline)
├── countries/           ← may be empty (see "Local Storage" section)
│   ├── {code}/          ← country repos (legalize-{code}), cloned on demand
│   └── data-{code}/     ← data caches (no git), regenerable via fetch
├── hub/                 ← public hub repo (legalize-dev/legalize)
└── web/                 ← legalize.dev website (separate repo)
```

The local `countries/` directory may be empty. Do not assume repos or data dirs exist locally. Always check before running commands that depend on them.

## Language & stack

- **English only** — all code, comments, variable names, function names, and documentation must be in English. The only exceptions are string literals (XML element names from BOE/LEGI/etc.) and the content of commit messages targeting public country repos when the country uses a non-English commit format.
- **Python 3.12+** with `pyproject.toml` (hatchling build), `src/` layout
- Core dependencies: `lxml`, `requests`, `pyyaml`, `click`, `rich`
- Dev: `pytest`, `ruff`, `responses` (HTTP mocking)
- Git operations via `subprocess` (not GitPython) for full control over `GIT_AUTHOR_DATE`
- CI via GitHub App (Legalize Pipeline)

## Output format — FINAL

The output format (filenames, frontmatter, commit messages, author/committer, trailers) is **locked**. Changing any of this requires regenerating ALL commits across every country repo. Do not "improve" it without explicit user approval.

**Repository structure is defined by the Legalize Format Spec**, §Directory layout — read it there, in `hub/SPEC.md`, not here. A path is a template the repo declares in its own `.legalize.yml`, drawn from a closed vocabulary of placeholders that a consumer holding only an identifier can fill in. Two shapes are conforming:

```
{directory}/{identifier}.md                 fr/LEGITEXT000006069414.md
{directory}/{id_sha1_2}/{identifier}.md     pt/a1/DRE-DEC-16-2026.md
```

`{directory}` is the law's `jurisdiction` when it has one and its `country` otherwise; `{id_sha1_2}` is the first two hex characters of `sha1(identifier)`, giving 256 buckets. **The rank never appears in the path** — it goes in the frontmatter. There are no rank or category subdirectories, and sharding is one level deep, never more.

This repo's single implementation of that rule is `src/legalize/layout.py`, which builds the paths *and* writes the manifest from the same dict. A country's shape is one entry in its `LAYOUT`; absent means flat, which is what every repo built before spec v0.4 is. Sharding is recommended for every directory and it is what Portugal uses — but changing a country's entry rewrites every path in its repo, so it goes in with a full rebuild and never on its own.

**Frontmatter (mandatory keys):**

```yaml
---
title: "Constitucion Espanola"
identifier: "BOE-A-1978-31229"
country: "es"
rank: "constitucion"
publication_date: "1978-12-29"
last_updated: "2024-02-17"
status: "in_force"
source: "https://www.boe.es/eli/es/c/1978/12/27/(1)"
---
```

Country-specific extras go in an `extra` sub-mapping (or as additional frontmatter keys for fields downstream consumers need).

**Text state (Legalize Format Spec v0.3).** A file must say what its body actually is. Declared once per country in `countries.py::TEXT_STATE`, overridable per norm via `NormMetadata.text_state`:

| Value | The body is |
|---|---|
| `point_in_time` | the law as in force on `last_updated` |
| `current` | the latest text the source publishes, whatever the commit's date |
| `as_enacted` | the act as published; amendments are not incorporated |

`point_in_time` is the default and is **never written to the frontmatter** — a file without the field is `point_in_time`, which is why adding a country to `TEXT_STATE` changes its published output and forgetting to is the safe failure. `current` and `as_enacted` also emit a static notice below the H1; `as_enacted` additionally emits `last_amendment` (the ID of the most recent amending act), which is what makes two amendments published on the same date produce two commits instead of one.

**Commit message types:** `[bootstrap]`, `[reform]`, `[new]`, `[repeal]`, `[correction]`, `[fix-pipeline]` — the values of `CommitType` in `models.py`. (They were Spanish until spec v0.2; existing commits keep their original labels.)

**Commit trailers:** `Source-Id`, `Source-Date`, `Norm-Id`

**Committer:** `Legalize <legalize@legalize.dev>` — set in `config.yaml::git.committer_name/email`. This is the project bot identity that signs every output commit regardless of who runs the pipeline.

**Author:** taken from the runner's `git config user.name/email`. When the pipeline runs from CI it is the GitHub App; when it runs locally it is whoever invoked it.

### Commit integrity rule

Each law's git history must contain ONLY commits that correspond to real legislative modifications (bootstrap + reforms). No fix-up commits, no pipeline corrections, no "update content" patches. If a bug in the pipeline produced incorrect Markdown, the fix is to **reprocess** the affected law (rewrite its commits from `data/`), never an additional commit on top. The commit history IS the legislative record — it must not contain artifacts from pipeline bugs. Integrity is per-file, not per-repo: a single law can be reprocessed (its commits removed and recreated via `git filter-repo`) without affecting the rest of the repo.

## Adding new countries

[adding-a-country/](adding-a-country/README.md) is the **end-to-end playbook**: one
file per step, read in order, with gates you do not skip. Start at its `README.md`
and follow the chain. Do not improvise shortcuts, and do not work from a summary of
it — including this one.

The steps and the parser rules are **not** restated here on purpose. Two copies of a
ten-step procedure drift, and the copy that gets read is the one that is wrong. What
you need to know before opening it:

- It takes a country from name-only to merged PR and live on legalize.dev.
- Three gates will stop you: the version-history spike (§0.5), format coverage
  (§0.7), and the 5-law quality review (§7). Failing one means going back, not
  filing a follow-up.
- Copy its `PROGRESS-template.md` to `PROGRESS.md` and tick it as you go. A country
  onboarding outlives any single context window.

## Local storage & working without local repos

Country repos and data directories are NOT required on the developer's machine. All production workflows run in CI (GitHub Actions). Local copies are only needed for development and debugging.

**What lives where:**

- Country repos (`countries/{code}/`) → GitHub (`legalize-dev/legalize-{code}`)
- Data caches (`countries/data-{code}/`) → regenerable via `legalize fetch`
- Daily updates → CI workflow (`daily-update.yml`), not local

**To work on a country temporarily:**

```bash
# Blobless clone (structure + on-demand blobs, good for git log)
git clone --filter=blob:none git@github.com:legalize-dev/legalize-es.git ../countries/es

# When done, delete to save space
rm -rf ../countries/es
```

**Space reference per country (approximate):**

- Repo: 200 MB – 1.5 GB (depends on number of laws)
- Data cache: 400 MB – 19 GB (depends on source format)
- At 50 countries, keeping all repos locally would exceed 30 GB

## Key conventions

- Dates as `datetime.date` internally; parse at the XML boundary, format at output.
- English for all code, comments, and variable names (see "Language & stack").
- Use `git -C <dir> <command>` instead of `cd <dir> && git <command>` to keep the working directory stable.
- CI via GitHub App (Legalize Pipeline); daily runs via cron workflow.
- **GitHub App token scope:** any workflow that pushes to a country repo (`legalize-{code}`) MUST pass `owner: legalize-dev` and `repositories: legalize-{code}` to `create-github-app-token`. Without these, the token is scoped only to `legalize-pipeline` and pushes fail with 403.
- Commands and CLI usage are documented in `README.md`. Do not duplicate them here.

## Git commits

Two distinct identities are at play in this project — do not confuse them:

- **Output commits** to public country repos (`legalize-{code}`) carry the project bot as author + committer, configured via `config.yaml::git.committer_name/email`. These are the laws being published; they must be signed consistently regardless of who runs the pipeline.
- **Meta commits** to this repo itself (engine code, docs, CI) are authored by the human running the commit. The user is always the author — taken from their git config — and Claude is a collaborator added via the trailer.

Rules:

- Every commit body Claude creates on the user's behalf must end with the trailer `Co-Authored-By: Claude <noreply@anthropic.com>`.
- For meta commits, the author is whoever runs the commit (their git config). Never override it to credit Claude or the bot.
- Do not hardcode personal emails in this file or in commit messages — they belong in git config, not in checked-in docs.
