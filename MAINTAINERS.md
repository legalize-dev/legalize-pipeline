# Maintainers

Legalize uses a federated maintainer model: one country, one maintainer.
Shared pipeline code (committer, transformer, base parser, CI) sits with
the project lead.

The model is borrowed from how Linux runs subsystem maintainers, Mozilla
runs locale owners, and Debian runs package maintainers: each area is
independent and the maintainer is the active user.

## Current maintainers

See the **Maintainer** column in [README.md](README.md#countries). Slots
without a name fall back to the project lead.

The authoritative wiring lives in [.github/CODEOWNERS](.github/CODEOWNERS) —
that's what GitHub uses to auto-assign reviewers on PRs.

## How to become a country maintainer

You don't need to ask permission to ship a country. The path is:

1. **Build the fetcher.** Follow [adding-a-country/](adding-a-country/README.md)
   end to end. The first bootstrap always runs locally; CI takes over
   once the country repo is live.
2. **Open the engine PR.** Add your country to `countries.py`,
   `config.yaml`, the README row, and the daily-update matrix. Include
   evidence of the §7 quality gate (5 sample laws, AI review 5/5 PASS).
3. **Say in the PR body that you want to maintain it.** That's the
   request. If the country lands and you're still around, you're the
   maintainer.

Once accepted you'll get:

- Write access on `legalize-pipeline` (the engine).
- Write access on `legalize-{cc}` (the country repo).
- Your handle in `CODEOWNERS` against `src/legalize/fetcher/{cc}/`.
- Your handle in the README's Maintainer column.

There is no committee. The bar is shipping something that works.

## What a country maintainer does

Once you're on the hook for a country, you own:

- **The country fetcher.** `src/legalize/fetcher/{cc}/` is yours. You
  decide parser changes, source quirks, and edge cases in the official
  format. Stay within the locked output contract (see below).
- **The country repo.** `legalize-{cc}` is yours. Watch for daily-cron
  failures, fix parser regressions, review and merge community PRs that
  only touch your country.
- **The country's daily update.** When the cron breaks, you're the
  first contact. Pause it by removing the country from the
  `daily-update.yml` matrix while you fix things, then re-enable.
- **The country-facing surface.** README description on the country
  repo (the GitHub "About" line), the row in the engine README, and
  i18n strings for your country in `web/`.

You do not own:

- **Shared modules** — `committer/`, `transformer/`, `fetcher/base.py`,
  `fetcher/cache.py`, `pipeline.py`, `countries.py`, `config.py`,
  `cli.py`, CI workflows. PRs are welcome, they just go through the
  project lead.
- **The output format.** Filenames (= official ID), commit committer
  (`Legalize <legalize@legalize.dev>` — the project bot; the author is
  whoever ran the pipeline), commit trailers (`Source-Id`,
  `Source-Date`, `Norm-Id`), commit types (`[bootstrap]`, `[reform]`,
  `[new]`, `[repeal]`, `[correction]`, `[fix-pipeline]`), and each
  country's declared directory layout (`src/legalize/layout.py`;
  flat unless the country has a `LAYOUT` entry) are locked. Changing
  any of this requires regenerating every country's history. Don't
  touch them without explicit approval.
- **Other countries.** Stay in your lane unless a country maintainer
  invites you in or the country has no assigned maintainer.

## Ground rules

- **No force-pushes to country repos.** History is the product — see
  the integrity rule in [CLAUDE.md](CLAUDE.md#commit-integrity-rule).
  If a pipeline bug produced bad markdown, reprocess via `git
  filter-repo`, don't patch on top.
- **No `--no-verify` on commits.** Hooks exist for a reason.
- **Reform history is mandatory.** Bootstraps without reform commits
  have to be redone — it's painful, ask Italy. The full version
  history is the product, not an afterthought.
- **Pause the daily cron before bulk operations.** Concurrent writes
  to a country repo will silently lose commits when fast-import
  captures a stale parent.
- **Quality gate is non-negotiable.** Before any bootstrap touches
  production data, run the 5-sample AI review from
  [the Step 7 quality gate](adding-a-country/step-7-quality-gate.md). Don't skip it,
  even if you've shipped countries before.

## Stepping down

If you can't keep up with a country, say so — reply on your own PR or
open an issue with `[maintainer]` in the title. We'll find a successor
or revert ownership to the project lead. Don't disappear silently:
unattended cron failures degrade trust in the whole project.
