# Step 7: Fetch a 5-law sample and quality-review it (MANDATORY GATE)

> Step 7 of 9 · [index](README.md) · previous: [`step-6-tests.md`](step-6-tests.md)
> If this session has been running a while, re-read [`README.md`](README.md) too — it holds every gate.

**This is the gate that separates "parser compiles" from "ready to bootstrap".**
Do not skip it and do not run the full bootstrap until every item below is green.

## 7.1 Fetch and render 5 representative laws

**Relationship to Step 0.2 fixtures:** the fixtures you saved in Step 0.2 are raw
source files (HTML/XML/JSON) used to develop and test the parser in isolation.
Here you run the **full pipeline** — fetch via the client, parse, render to
Markdown, commit to git — and review the **output** MD files. Use the same 5 laws
you saved as fixtures so you can compare source → output directly.

Pick 5 laws that between them exercise every structure you found in Step 0.4
(different ranks, at least one with tables, at least one with footnotes if the
source has them). Fetch them explicitly by ID so you get the **same** set every
time you iterate:

```bash
# Option A: fetch by explicit IDs
legalize fetch -c xx --id LAW-2024-1 --id LAW-2024-42 --id LAW-1998-100 \
                     --id LAW-2012-5 --id LAW-2023-TARIFF

# Option B: limit-based (less reproducible, OK for first smoke test)
legalize fetch -c xx --all --limit 5
```

Then render them into a sandbox country repo (do NOT push):

```bash
# Create a throwaway repo for the sample
git init ../countries/xx/
mkdir -p ../countries/xx/xx
git -C ../countries/xx commit --allow-empty -m "[bootstrap] Init sample"

# Dry-run first to see what would happen
legalize bootstrap -c xx --dry-run --limit 5

# Actually produce the 5 MD files
legalize bootstrap -c xx --limit 5
```

You should now have 5 files under `../countries/xx/xx/*.md`.

## 7.2 AI quality review — the 5 checks

Open a fresh Claude Code session in the workspace and paste the prompt below.
The agent will read each MD next to its source fixture and grade the parser on
five dimensions. **The parser is not ready until the agent reports all five as
PASS for all 5 laws.**

Ready-to-paste review prompt:

```text
You are reviewing a new-country parser for the legalize-pipeline repo.

Read these 5 generated MD files:
  ../countries/xx/xx/LAW-2024-1.md
  ../countries/xx/xx/LAW-2024-42.md
  ../countries/xx/xx/LAW-1998-100.md
  ../countries/xx/xx/LAW-2012-5.md
  ../countries/xx/xx/LAW-2023-TARIFF.md

And their source fixtures:
  engine/tests/fixtures/xx/sample-*.{html,xml,json}

Plus the research doc: RESEARCH-XX.md

For EACH of the 5 laws, grade PASS / FAIL on these five checks and explain any FAIL:

1. TEXT CORRECTNESS
   - No mojibake (Ã©, â€œ, \x00, replacement chars).
   - No leftover HTML/XML tags in the body.
   - No truncated sentences, no duplicated paragraphs.
   - UTF-8 clean (try `file ../countries/xx/xx/*.md`).

2. METADATA COMPLETENESS
   - Every field listed in RESEARCH-XX.md §0.3 metadata inventory is present
     either in the dataclass fields or in `extra:` in the frontmatter.
   - Dates are ISO-8601 (YYYY-MM-DD), not localized strings.
   - Identifier matches the filename and is filesystem-safe.
   - `source:` URL opens the correct page on the official site.

3. STRUCTURE PRESERVATION
   - Heading levels match the source hierarchy (title > chapter > section > article).
   - Article numbers and titles are correct and in order.
   - No articles skipped, no articles duplicated.
   - Annexes rendered as their own blocks.

4. RICH FORMATTING
   - Tables in the source render as Markdown pipe tables (with headers).
   - Bold / italic in the source are preserved (inline ** or *).
   - Lists in the source are real Markdown lists, not flattened paragraphs.
   - Cross-references are rendered as Markdown links.
   - Quoted / amending text uses blockquotes.
   - Signatories are bold at the end.
   - If the source has NONE of a construct, note it ("no tables in sample").

5. ENCODING & HYGIENE
   - `grep -P '[\x00-\x08\x0b\x0c\x0e-\x1f]'` on all 5 files returns nothing.
   - No `\r\n` line endings (Unix-only).
   - File ends with a single newline.
   - No trailing spaces on lines.

For any FAIL, quote the offending excerpt and point to the probable cause in
fetcher/xx/parser.py (which function, which class). Do not fix code — only
report. I will iterate on the parser based on your findings.

Report format:
  Law 1 (LAW-2024-1):
    1. TEXT CORRECTNESS: PASS
    2. METADATA: FAIL — `gazette_reference` missing from extra (see source pase-container)
    3. STRUCTURE: PASS
    4. FORMATTING: FAIL — table in annex II rendered as flat text (see lines 340-352)
    5. ENCODING: PASS
  Law 2: ...
  ...
  SUMMARY: X/5 laws fully PASS, top 3 issues to fix first: ...
```

## 7.3 Iterate until 5/5 PASS

Every FAIL points at a parser bug. Fix, re-render the 5 MDs, and re-run the
review with **delta feedback** so the agent doesn't repeat hallazgos already
resolved. The pattern that has shipped every country in the registry:

**Round 1 prompt** — use the canned template from §7.2 verbatim. Expect a
handful of FAILs; that's the first real signal of what the parser is missing.

**Round 2+ prompt** — prepend a "## Fixes applied this round" block that
lists what you changed in parser.py since the last review, so the agent
verifies the fixes landed AND grades everything fresh. Example:

```text
## Fixes applied this round (so you can verify they landed)

1. Duplicate Part/Chapter headings — rewrote _walk_recursive to iterate
   in document order, emitting each heading container as its own block
   exactly once. Finance Act: 166 bogus PART 1 headings → 6 legitimate.
2. <Inferior>/<Superior> corrupted whole table cells → added length guard.
   Finance Act: 87 corrupted cells → 0.
...
```

This cuts review cycles: the agent confirms resolved issues in one line
each and focuses its attention on regressions and remaining bugs.

**Two efficiency tricks before invoking the agent**:

(a) **Reusable render script** — don't hand-render 5 MDs each round.
    `scripts/render_sample.py` renders any country's fixtures straight through
    its registered parsers:

    ```bash
    python scripts/render_sample.py xx tests/fixtures/xx/*.xml
    ```

    The norm ID comes from the filename stem; pass `ID=path` when the fixture
    isn't named after the law, and `--out` to move the sandbox. Gzipped fixtures
    are read as-is. Between rounds this gives you fresh MDs under
    `/tmp/xx-sandbox/` in two seconds.

(b) **Numeric sanity checks before the subagent** — cheap `grep -c`
    counts filter obvious regressions so you don't spend agent tokens on
    them. Examples that caught regressions during UK iteration:

    ```bash
    # Table count (source has N tables → expect N-ish pipe tables)
    grep -c "^| ---" /tmp/xx-sandbox/LAW-WITH-TABLES.md

    # Formula count (if the Act has maths)
    grep -c '\$[^$]' /tmp/xx-sandbox/LAW-WITH-FORMULAS.md

    # Heading duplication smell test — should show unique counts
    grep "^## " /tmp/xx-sandbox/LAW.md | sort | uniq -c | sort -rn | head

    # Any leftover XML?
    grep -E "<[a-zA-Z:]+[> /]" /tmp/xx-sandbox/*.md | head
    ```

    Run these after every parser edit. Only invoke the subagent when the
    numbers look reasonable — saves rounds.

Do not move on until the reviewer returns `SUMMARY: 5/5 laws fully PASS`.
UK took 4 rounds (0/5 → 1/5 → 4/5 → 5/5). Some countries take 2. None
should take more than 5 — if you are on round 6 something structural is
wrong with the parser's model of the source and you should step back.

## 7.4 Manual spot-check (2 minutes)

Even after the AI review passes, open one MD and its source side-by-side in a
browser. Look at:
- The title line matches the official title exactly.
- The first article reads naturally in the country's language.
- A table (if present) is readable and has the right column count.
- The frontmatter YAML parses without errors: `python -c "import yaml; yaml.safe_load(open('file.md').read().split('---')[1])"`


---

**GATE IN THIS STEP:** the review must return `SUMMARY: 5/5 laws fully PASS`.
Anything less and you go back to `parser.py`. Do not start a full bootstrap on a
parser that failed this.

**Next → read [`step-8-workers.md`](step-8-workers.md) in full before doing anything else.**
Tick this step in your `PROGRESS.md` first.
