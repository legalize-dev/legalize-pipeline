# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. Project-wide rules and policies live here. For module-by-module code reference see [ARCHITECTURE.md](ARCHITECTURE.md). For the end-to-end country onboarding playbook see [ADDING_A_COUNTRY.md](ADDING_A_COUNTRY.md).

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

**File structure is FLAT** — one directory per country (or jurisdiction), no rank/category subdirectories. The rank goes in the YAML frontmatter, never in the directory tree.

```
legalize-es/
  es/BOE-A-1978-31229.md       ← state-level laws
  es-pv/BOE-A-2020-615.md      ← autonomous communities (jurisdiction)
legalize-at/
  at/AT-10002333.md             ← all laws flat in at/
```

**Filename:** `{country}/{official_id}.md`

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

**Commit message types:** `[bootstrap]`, `[reforma]`, `[nueva]`, `[derogacion]`, `[correccion]`, `[fix-pipeline]`

**Commit trailers:** `Source-Id`, `Source-Date`, `Norm-Id`

**Committer:** `Legalize <legalize@legalize.dev>` — set in `config.yaml::git.committer_name/email`. This is the project bot identity that signs every output commit regardless of who runs the pipeline.

**Author:** taken from the runner's `git config user.name/email`. When the pipeline runs from CI it is the GitHub App; when it runs locally it is whoever invoked it.

### Commit integrity rule

Each law's git history must contain ONLY commits that correspond to real legislative modifications (bootstrap + reforms). No fix-up commits, no pipeline corrections, no "update content" patches. If a bug in the pipeline produced incorrect Markdown, the fix is to **reprocess** the affected law (rewrite its commits from `data/`), never an additional commit on top. The commit history IS the legislative record — it must not contain artifacts from pipeline bugs. Integrity is per-file, not per-repo: a single law can be reprocessed (its commits removed and recreated via `git filter-repo`) without affecting the rest of the repo.

## Adding new countries

[ADDING_A_COUNTRY.md](ADDING_A_COUNTRY.md) is the **end-to-end playbook**. Follow every step — it takes a country from name-only to merged PR and live on legalize.dev. Do not improvise shortcuts.

High-level order:

0. **Research the source** — save 5 fixtures, inventory every metadata field and every rich-formatting construct into `RESEARCH-{CC}.md`.
1. Create `fetcher/{code}/` with `client.py`, `discovery.py`, `parser.py` implementing the 4 interfaces from `fetcher/base.py`.
2. Register in `countries.py` REGISTRY.
3. Add a `countries:` section to `config.yaml`.
4. Create the GitHub repo `legalize-dev/legalize-{code}`.
5. (Optional) Custom `daily.py` if the country has a non-standard daily flow.
6. Write parser tests against the 5 fixtures.
7. **Quality gate (mandatory):** fetch 5 sample laws, render to Markdown, and run an AI review covering TEXT correctness, METADATA completeness, STRUCTURE, RICH FORMATTING preservation, and ENCODING. Do not proceed until 5/5 PASS.
8. Tune `max_workers` against a 50-law benchmark.
9. Full bootstrap → `legalize health` → push country repo → open engine PR → verify on https://legalize.dev/{code}.

**Non-negotiable rules for the parser:**

- **Metadata completeness:** every field the source exposes must be captured (generic fields in `NormMetadata`, source-specific in `extra` with English snake_case keys). Regenerating commit history to add a forgotten field is expensive, so we capture everything up front.
- **Rich formatting preservation:** tables → Markdown pipe tables (see `fetcher/lv/parser.py` for the canonical implementation), bold → `**...**`, italic → `*...*`, lists → `- ...`, cross-references → `[text](url)`, quoted amending text → `> ...`, signatories → `firma_rey` css class. Inline bold/italic must be pre-wrapped in the parser (the CSS→MD map is paragraph-level).
- **Images are explicitly skipped** — we are not ready for binary assets. Drop image nodes and count them in `extra.images_dropped`.
- **Encoding is UTF-8 only** — decode source bytes explicitly, strip C0/C1 control chars, normalize whitespace at paragraph boundaries. Never rely on `requests` auto-detection.

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
- Commands and CLI usage are documented in `README.md`. Do not duplicate them here.

## Git commits

Two distinct identities are at play in this project — do not confuse them:

- **Output commits** to public country repos (`legalize-{code}`) carry the project bot as author + committer, configured via `config.yaml::git.committer_name/email`. These are the laws being published; they must be signed consistently regardless of who runs the pipeline.
- **Meta commits** to this repo itself (engine code, docs, CI) are authored by the human running the commit. The user is always the author — taken from their git config — and Claude is a collaborator added via the trailer.

Rules:

- Every commit body Claude creates on the user's behalf must end with the trailer `Co-Authored-By: Claude <noreply@anthropic.com>`.
- For meta commits, the author is whoever runs the commit (their git config). Never override it to credit Claude or the bot.
- Do not hardcode personal emails in this file or in commit messages — they belong in git config, not in checked-in docs.
