# Step 0: Research the source and inventory what it gives you

> Step 0 of 9 · [index](README.md)
> If this session has been running a while, re-read [`README.md`](README.md) too — it holds every gate.

**Do not skip this step.** Every quality problem we have ever shipped (mojibake,
missing metadata, lost tables, wrong dates) was caused by skipping it. Produce a
`RESEARCH-{CC}.md` file at the workspace root (`~/autonomo/legalize/RESEARCH-XX.md`)
before writing any code.

## 0.1 Identify the source(s)

Look for **official** open data. In this order of preference:
1. Government open-data API with bulk dump (best: ES, FR, LT, LV)
2. Government REST API with pagination (AT, SE, AD)
3. HTML scraping of the official gazette (LV likumi.lv — only if nothing else exists)
4. PDF scraping (last resort — only EE Lisa uses this)

Document in `RESEARCH-{CC}.md`:
- Base URLs, endpoints, auth requirements, rate limits, licensing
- Whether historical versions are available (see "Version history strategies" below)
- Any robots.txt / Crawl-delay constraints
- Estimated total norm count and cadence of daily updates

## 0.2 Save 5 representative fixtures

Download 5 laws **by hand** and save them to `engine/tests/fixtures/{code}/`:

```
engine/tests/fixtures/{code}/
  sample-constitution.{xml,html,json}    # highest rank
  sample-code.{xml,html,json}             # a code / compilation
  sample-ordinary-law.{xml,html,json}     # a regular law
  sample-regulation.{xml,html,json}       # a decree / regulation
  sample-with-tables.{xml,html,json}      # one that has tables/images/attachments
```

Pick laws that between them exercise every structure you expect to see. If you
cannot find a law with tables, say so in the research doc — but still look hard,
because tables almost always exist in tax codes, tariff schedules, and annexes.

## 0.3 Metadata inventory — capture EVERYTHING

Open each fixture and list **every single field** the source exposes, not just the
ones the pipeline needs today. Put this list in `RESEARCH-{CC}.md` as a table:

| Source field | Type | Example | Maps to | Notes |
|---|---|---|---|---|
| `title` | string | "Ley 1/1978..." | `NormMetadata.title` | |
| `identifier` | string | "BOE-A-1978-31229" | `NormMetadata.identifier` | |
| `publication_date` | date | "1978-12-29" | `NormMetadata.publication_date` | parse dd/mm/yyyy |
| `department` | string | "Jefatura del Estado" | `NormMetadata.department` | |
| `ministry_signatory` | string | "Juan Carlos R." | `extra.signatory` | country-specific |
| `eli` | url | "https://data.../eli/..." | `extra.eli` | country-specific |
| `official_gazette_number` | string | "BOE núm. 311" | `extra.gazette_reference` | |
| `subjects` | list[string] | ["constitución", ...] | `NormMetadata.subjects` | |
| ... | | | | |

**Rule:** if the source provides it, you capture it. Fields that don't fit the
generic `NormMetadata` dataclass go into `extra` with **English snake_case keys**.
Do not editorialize which fields are "useful" — a future consumer of the data may
need any of them, and regenerating history to add fields is expensive.

## 0.4 Formatting inventory — what rich content does the source have?

Scroll through the 5 fixtures and list every rich-formatting construct you see:

- [ ] **Tables** — any `<table>`, TSV blocks, or tabular data? Tariff schedules,
      fines, dates of effect tables, annexes?
- [ ] **Bold** — inline `<b>/<strong>` or CSS classes meaning "bold"?
- [ ] **Italic** — inline `<i>/<em>` or CSS classes?
- [ ] **Lists** — ordered/unordered, nested?
- [ ] **Footnotes / endnotes** — superscript markers, reference blocks?
- [ ] **Links** — cross-references to other laws or articles?
- [ ] **Formulas** — equations, MathML, TeX?
- [ ] **Quotations** — block quotes or amending text quoted verbatim?
- [ ] **Attachments / annexes** — appendices with their own structure?
- [ ] **Signatories** — who signed, where, on what date?

Each "yes" becomes a concrete task for `parser.py`. Each "no" becomes a documented
assumption in `RESEARCH-{CC}.md` that can be verified in the quality review (Step 7).

## 0.5 Version history spike — GATE

**Do not proceed to Step 1 until this passes.** This spike validates that you can
actually extract historical versions before you invest days building a full parser.

Pick one law that has multiple known versions (e.g., a constitution with amendments,
or any law your research shows has been reformed). Then:

1. **Download all available versions** of that single law — however the source
   exposes them (embedded XML, `arch=N` URLs, version table, point-in-time API, etc.)
2. **Confirm you can extract** for each version:
   - The full text (even roughly — you will refine the parser later)
   - The effective date (required to set `GIT_AUTHOR_DATE`)
   - A stable identifier that links all versions to the same law
3. **Save the evidence** as `tests/fixtures/{code}/version-spike.txt` (a summary
   showing "version 1: date X, N paragraphs; version 2: date Y, N paragraphs; ...")
   so the quality review in Step 7 can reference it.
4. **Classify the source** and record the answer in `RESEARCH-{CC}.md`. This is the
   same evidence, read one more time:

   ```
   Does the source give the text with amendments incorporated?
     no  → as_enacted
     yes → Does it give that text at a past date?
             yes → point_in_time   (the default; declare nothing)
             no  → current
   ```

   Anything other than `point_in_time` is declared in `countries.py::TEXT_STATE`, in
   the same PR that registers the fetcher. It is one line and it decides what every
   published file of that country says about itself — see CLAUDE.md, "Output format".

**If you cannot extract at least 2 distinct versions with dates for a single law,
stop and investigate:**

- The source may not expose history → document in `RESEARCH-{CC}.md` and decide
  whether a single-snapshot ship is acceptable (see priority #2 above).
- You may be hitting the wrong endpoint → common: the "current text" API vs. the
  "consolidated versions" API are different URLs.
- The source may use a pattern you haven't seen → check the
  [Version history strategies](#version-history-strategies) table.

**Why this step exists:** every country where we discovered version-access problems
late (DE, UY) cost a full reprocess. Catching it here costs an hour. Finding it
after a full bootstrap costs a week. The classification in point 4 is the cheap
half of the same lesson: DE and UY publish a current text with no dated history,
and nothing in their files said so for two years.

## 0.6 Estimate total scope

Before writing code, write a one-paragraph summary in `RESEARCH-{CC}.md`:

- Approximate number of laws in scope (from discovery endpoint or catalog)
- Number of HTTP requests needed for a full bootstrap (laws × versions)
- Estimated fetch time at conservative rate limits
- Any known blockers (rate limits, auth, captchas, IP restrictions)

This estimate informs the `max_workers` tuning in Step 8 and sets expectations
for bootstrap runtime.

## 0.7 Format-coverage table — GATE

If the source serves laws in a single file format (e.g. France's LEGI XML
dump), skip this step and note it: `"Single-format source (XML only); §0.7
N/A."`

Otherwise — and this is most modern open-data portals — produce a table
showing how much of the catalogue each format reaches. Use the source's
own index (SPARQL, REST, catalog dump) to get hard numbers, not guesses:

| Format | Total laws with ≥1 version in this format | Unique (no other format covers them) | % of catalogue |
|---|---|---|---|
| XML (Akoma Ntoso) | 5,139 | 0 | 29.8% |
| DOCX | 5,141 | 2 | 29.8% |
| DOC (legacy binary) | 5,166 | 27 | 30.0% |
| PDF-A | 6,791 | 1,652 | 39.4% |
| HTML | 5,140 | 1 | 29.8% |

For historical versions (not just current text), produce the same table
counting versions rather than laws — the answer can differ by an order of
magnitude (Fedlex: Constitution has 6 XML versions but 37 PDF-A versions).

**Gate:** every format that contributes `> 1%` of unique laws **or** unique
versions MUST be covered by the fetcher. Any format you skip requires a
written justification that cites either (a) < 1% coverage contribution, or
(b) engineering cost dramatically exceeding the gain — e.g. scanned-image
PDFs needing OCR, DOC binary formats without a clean reader.

**The parser must be format-dispatched.** The client bundles all versions
into a single envelope with an explicit `format` attribute on each
`<version>`; the parser emits the **same** `Block/Version/Paragraph`
structure regardless of input. Article headings use one template, paragraph
numbers use one style, tables always become pipe tables, footnotes always
become `[^N]` with a footnotes block. Format-specific quirks (PDF page
headers, "Stand am …" stamps, Word-style revision markers) are stripped so
the output cannot betray which format the underlying manifestation was.

**Cross-format before/after check**: pick one law that has versions in both
the "richest" format (usually XML) and a fallback format (usually PDF).
Render the two adjacent versions across the format boundary, diff the
Markdown, and iterate both parsers until a casual reader cannot tell which
format came from which. Save the before/after evidence in
`RESEARCH-{CC}.md §0.7` so Step 7 has a baseline to compare against.

This work is painful, but skipping it means shipping a country that
permanently misses 30-60% of its corpus and creates format-boundary
scars in every git log. Do it up front.


---

**GATES IN THIS STEP:** §0.5 version-history spike (≥2 dated versions from one law,
source classified into a `text_state`) and §0.7 format coverage (every format
carrying >1% of laws or versions is covered, or the skip is justified in writing).
Both must pass before any parser code is written.

**Next → read [`step-1-fetcher.md`](step-1-fetcher.md) in full before doing anything else.**
Tick this step in your `PROGRESS.md` first.
