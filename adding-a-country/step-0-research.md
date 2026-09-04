# Step 0: Research the source and inventory what it gives you

> Step 0 of 9 · [index](README.md)
> If this session has been running a while, re-read [`README.md`](README.md) too — it holds every gate.

**Do not skip this step.** Every quality problem we have ever shipped (mojibake,
missing metadata, lost tables, wrong dates) was caused by skipping it. Produce a
`RESEARCH-{CC}.md` file in `engine/research/` before writing any code. Anything bulkier
than the document itself — per-probe measurements, request logs, raw censuses — goes in
`engine/research/{cc}-v2/` alongside it, as `es` does.

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

### 0.1.1 Find every index the source publishes — do not stop at the first one

A discovery design is only as good as the indexes you found, and the cheap ones are
routinely not where you look. Spain cost a full research pass to learn this: three
independent probes tested `https://www.boe.es/sitemap.xml` (404) and grepped `robots.txt`
for a `Sitemap:` directive (absent) and concluded *"the daily summary is the only index;
nothing else enumerates"*, then designed a **14,926-request, 2 GB** sweep on top of that
conclusion. The real index is at `/eli/sitemap.xml` with a companion Atom feed, it is
linked in prose from a documentation page nobody opened, and it enumerates the corpus in
**4 requests**. That is a 3,700× error, and it was a research error, not a source
limitation.

So work the list, and write down what each one returned — including the misses, because
the next person needs to know what was already tried:

- [ ] `/sitemap.xml`, `/sitemap_index.xml`, and **the standard-adjacent paths a CMS
      actually uses** (`/{section}/sitemap.xml`, `/eli/sitemap.xml`, `/sitemaps/`)
- [ ] `robots.txt` — for a `Sitemap:` directive, and read it in full: it may also list
      **suppressed document ids** that discovery must filter out (BOE's is 487 KB and
      names 1,740 right-to-be-forgotten documents)
- [ ] **The site's own navigation and documentation pages**, not just the API docs. Follow
      the "information", "about the data", "standards" and "legal identifiers" links. An
      ELI/URN/permalink page is where a national gazette usually announces its bulk index
- [ ] RSS and Atom feeds (`/rss/`, `/feeds/`, `*.atom`) — a rolling change feed makes a
      missed cron self-healing, which no date-keyed sweep does
- [ ] OAI-PMH (`/oai`), SPARQL, a bulk download or dump, an OpenSearch descriptor
- [ ] The search UI: **submit a query in a browser and read the network requests**, so you
      learn whether the results come from a JSON endpoint you can call directly or from a
      server-rendered page you would have to parse. Either answer is worth having: for the
      BOE the trace was 21 requests and **zero XHR**, which proved there is no cleaner
      endpoint hiding behind the HTML and turned "maybe we should look harder" into a
      closed question in three minutes
- [ ] Whether the search reports an **exact result total**. A count up front means the
      bootstrap knows what "complete" means before it starts, instead of learning it as a
      by-product four hours in

**Prefer a concrete, documented call over parsing a page — but verify the population before
you prefer it.** Cheaper is not the same as correct, and this is the second half of the same
Spanish lesson. The ELI sitemap enumerates 103,070 norms in 4 requests against the search's
40; it is also a *different set* — it carries Sección III material the corpus does not want
and omits the court rulings the corpus may want. Indexing from it and filtering after the
fetch would have cost ~26,000 out-of-scope document downloads, wiping out the saving many
times over. So for each index you find, record:

| Index | Requests to enumerate | What it covers | What it omits | Documented? |
|---|---:|---|---|---|

and choose per job: the section- or type-filtered index for the **id list**, the sitemap for
`lastmod` **change detection** and any shard key its URIs carry, the feed for the **daily**.
They are not competitors.

Two rules that follow from this and have both been paid for:

1. **An undocumented HTML surface can be the right answer, but it needs a tripwire.** If the
   design parses a search page, assert the parsed row count against the total the page itself
   states and fall back to a documented path on mismatch. Markup changes silently; a count
   assertion does not.
2. **Never conclude "nothing enumerates" from two negative probes.** Say what you tested,
   with the URL and the status code, so the claim is falsifiable by the next reader.

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
