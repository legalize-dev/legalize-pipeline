# Spending time and tokens

An onboarding is long, and most of what makes it long buys nothing: the same
check run again after a change it cannot see, a whole corpus re-parsed to read one
field, a status file read every minute. This file is about running each check
when it can tell you something new — not about running fewer of them. Every gate
in this playbook still applies, at full strength.

The examples are from the Ireland v0.4 rebuild (October 2026), where each of these
cost hours before it was written down. The numbers are what was measured there.

## 1. Size the check to the change

| You changed | Run | Not |
|---|---|---|
| A rule that one file or one law hits | That file, offline from the cache (seconds), plus the tests of that module | The 50-law benchmark, the full suite |
| A rule that a class of files hits | Every file of that class, once, and keep the results (§3) | The whole corpus |
| A batch of fixes, before a commit | The full test suite, once (~5 min) | The full suite after each edit |
| The code a long run will use | The benchmark/rehearsal gate, once, at the restart (~15 min) | The benchmark after each fix |

To re-run one law without the network, build the country's client on its raw
cache with HTTP disabled and call the same `get_text` → parse path the pipeline
uses. Reproducing 93 failing Irish instruments that way took about 10 minutes; one
takes seconds. A fix is verified on the files it was written for before anything
broader runs.

## 2. Never redo work a stamp can carry

Results the pipeline already accepted are the expensive part. When a code change
cannot alter them, carry them forward instead of re-parsing them:

- **Measure equivalence once**, with the long run stopped (anything it writes
  after the measurement is unmeasured), old tree against new tree, on everything
  the change can reach. Then move the stamps of every unchanged result and
  reprocess only the ones whose output changed.
- Ireland batch 31: 24,373 sources compared once; 8,898 stored results carried,
  41 reprocessed.

**Better still, make the measurement unnecessary.** When a new rule only has to
handle files the current code rejects, run the strict reading first and the new
rule only as a fallback for files it rejects. Every file the old code accepted
keeps its exact output by construction, so there is nothing to re-measure. The
October 2026 Irish PDF fixes were written this way: re-parsing every cached PDF to
prove equivalence would have cost hours.

## 3. Parse once, then analyse the stored result

- Write expensive extractions (PDF parses, fetched envelopes, surveys) to a JSON
  file as they complete, then run every question against that file. Re-parsing
  to look at another field is the most common waste: one Irish survey of 295 PDFs
  took ~2 hours with four processes; reading its JSON takes a second.
- Parallelise read-only surveys (`multiprocessing.Pool`); keep the number of
  workers below the cores a running fetch needs.
- Analysis helpers must not run on import (`if __name__ == "__main__":`).
  Importing one Irish helper silently re-ran its whole 13-Act analysis.
- Compare normalised text before diffing: equal once whitespace is removed means
  layout only. A character-level `difflib.SequenceMatcher` over two whole Acts is
  quadratic and does not finish; diff only the regions that differ.

## 4. Collect every failure in one pass

- A run that stops at its first failure yields one failure per cycle, and every
  cycle costs a restart. Let discovery, fetch and dependency closure continue
  past a failure and report the complete list at the end (the Irish dependency
  closure was changed to do this in October 2026).
- Separate transient failures (DNS, timeouts, 403 bursts) from deterministic ones
  before investigating anything. Retry only the failed items, after the network
  answers again; a gate that fails on a DNS outage is re-run on those items, not
  from scratch.
- Fix the complete list in one batch, then restart once. Each restart costs a
  benchmark and a measurement (§2).

## 5. Wait for a notification, do not poll

- Start long jobs in the background with one completion notification. A loop that
  re-reads the same status every minute costs tokens on every iteration and tells
  you nothing until the job ends.
- One watcher per job. Two watchers on the same job, or a watcher on a file that
  has since been renamed, are pure noise; stop them.

## 6. Read the rules before writing a shortcut

Before writing a generic rule that turns failures into notes or picks one source
over another, search the tests for the opposite rule. Ireland lost an afternoon to
three generic shortcuts that existing tests forbade on purpose (an unverified
earlier claim must fail). Ten minutes of `grep` would have shown it.

## 7. Keep evidence proportional

Pin an exact source by SHA-256 and its immutable URL. Store a page excerpt, not the
whole PDF, when a test needs layout; a list of hashes and URLs, not twenty full
files, when a test only checks that each pinned entry has its evidence.
