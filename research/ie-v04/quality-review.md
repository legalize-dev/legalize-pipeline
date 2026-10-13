# Ireland v0.4 — independent Step 7 quality review

Reviewed 2026-10-08. Round: **sample-4**. **SUMMARY: 5/5 laws fully PASS.**
The additional Adoptive Leave Act historical PDF-to-HTML check also **PASS**.
These conclusions apply to the captured sample, not every law in the source census.
LRC redistribution, full-corpus reconciliation and daily-operation checks remain
separate gates. No parser edits were made during this final independent review.

The full pipeline fetched, parsed, stored, rendered and committed these files in
`countries/ie-v04-sample-4`. Its structured input is in
`countries/data-ie-v04-sample-4/json`. Official fixtures in `tests/fixtures/ie/`
and the URL-keyed raw cache were compared with the final Markdown. The complete
onboarding README and Step 7 were reread. File hashes and machine-check results
are in [sample-4-review-evidence.json](sample-4-review-evidence.json). The failed
[round-2 review](quality-review-round-2.md) is retained as superseded evidence.

| Law / relative Markdown path | Text | Metadata | Structure | Rich formatting | Encoding |
|---|---|---|---|---|---|
| Constitution — `ie/66/IE-1937-constitution.md` | PASS | PASS | PASS | PASS | PASS |
| Constitution of the Irish Free State Act 1922 — `ie/e1/IE-1922-act-1.md` | PASS | PASS | PASS | PASS | PASS |
| Finance Act 2024 — `ie/49/IE-2024-act-43.md` | PASS | PASS | PASS | PASS | PASS |
| Royal Hibernian Academy Act 2023 — `ie/5b/IE-2023-act-P1.md` | PASS | PASS | PASS | PASS | PASS |
| S.I. 356/2024 — `ie/29/IE-2024-si-356.md` | PASS | PASS | PASS | PASS | PASS |
| Additional history sample: Adoptive Leave Act 1995 — `ie/37/IE-1995-act-2.md` | PASS | PASS | PASS | PASS | PASS |

## Constitution of Ireland — IE-1937-constitution

1. **TEXT CORRECTNESS: PASS.** All 542 operative source paragraphs after the first
   article anchor are present after formatting/whitespace normalization; preamble
   and article 19 are also retained. The editorial index is correctly excluded.
   No observed truncation, duplicated operative paragraphs, leaked markup or mojibake.
2. **METADATA: PASS.** Official title, rank, source, adoption date 1937-07-01,
   operation date 1937-12-29 and enrollment date 2019-11-13 are retained. The latest
   amendment is C38/2019. The current-text state and warning do not claim that
   today's Constitution is its enacted 1937 body or an archived historical text.
3. **STRUCTURE: PASS.** Articles 1–50 plus 28A and 42A appear once in order (52
   article headings), beneath their source subject headings and preamble.
4. **RICH FORMATTING: PASS.** The presidential, Council-of-State and judicial
   declarations are three legal blockquotes. Lettered subparagraphs are Markdown
   lists with legal labels retained; preamble emphasis and degree-sign numbering
   survive. No normative tables, footnotes or signatory block occur in this body.
5. **ENCODING & HYGIENE: PASS.** Shared checks below.

## Constitution of the Irish Free State Act 1922 — IE-1922-act-1

1. **TEXT CORRECTNESS: PASS.** All 265 nonempty XML body/backmatter paragraphs are
   present after normalization, including table cells and Irish accents. The
   content-bearing annex image is explicitly represented by `[image omitted]`;
   this is the permitted Step 1.7 binary-image limitation, not complete image
   reproduction. The harp and annex image are counted in `images_dropped: 2`.
2. **METADATA: PASS.** English XML supplies the canonical title and 1922-12-06
   enactment/publication date. The API's reversed English/Irish labels and conflicting
   1922-10-25 date remain separately labelled parliamentary metadata; no bill PDF
   is presented as the enacted Act. The final status is repealed on 1937-12-29.
   The July 1937 commit is only partially repealed: publication of the new
   Constitution is distinct from Article 48's operation-based whole repeal.
3. **STRUCTURE: PASS.** Three sections, 83 constitutional articles, two schedules,
   the treaty ANNEX and its six subordinate headings are distinct and ordered.
4. **RICH FORMATTING: PASS.** Both oaths are blockquotes, lettered lists preserve
   depth, and the two source tables retain cells, rowspans and column count after
   Markdown normalization. Signatories are bold. No source footnotes occur.
5. **ENCODING & HYGIENE: PASS.** Shared checks below.

## Finance Act 2024 — IE-2024-act-43

1. **TEXT CORRECTNESS: PASS.** All 3,529 nonempty body/backmatter source paragraphs
   excluding separately moved footnotes are present after normalization. Table,
   footnote and formula inspection supplements this content-presence check.
2. **METADATA: PASS.** Canonical title and 2024-11-12 date come from enacted XML;
   a genuine enacted English PDF and full parliamentary object are retained.
   Amendment identity, partially-repealed status and as-enacted warning are explicit.
3. **STRUCTURE: PASS.** Six parts, eight chapters, sections 1–118 and two schedules
   retain their order. Quoted replacement numbering does not create new top-level
   sections. All 35 footnote references have one corresponding definition.
4. **RICH FORMATTING: PASS.** Twelve data tables retain their source rows/widths
   with Markdown headers. Bold/italic, 35 footnotes, nested legal lists and quoted
   amendments survive. Section 6's nested formulas remain readable paragraph text
   inside the correct list/quote containers. The source's plain-text formulas
   retain symbols and order; `has_formulas: true` records their presence. No
   invented LaTeX or prose cross-links are needed. No signatory block occurs.
5. **ENCODING & HYGIENE: PASS.** Shared checks below.

## Royal Hibernian Academy Act 2023 — IE-2023-act-P1

1. **TEXT CORRECTNESS: PASS.** All 22 operative source paragraphs, preamble clauses,
   word substitutions and accented characters occur in the rendered text.
2. **METADATA: PASS.** P1 remains separate from public Act 1. The enacted title,
   2023-12-20 date, private-Act source route, genuine enacted PDF and lossless
   parliamentary metadata are retained. The text is explicitly as enacted.
3. **STRUCTURE: PASS.** Seven numbered sections retain their titles and order;
   preamble clauses remain before section 1. No annex occurs.
4. **RICH FORMATTING: PASS.** Lettered lists are real Markdown lists and inline
   emphasis survives. Short quoted word substitutions correctly stay inline,
   rather than becoming invented block quotations. This source has no tables,
   footnotes, long replacement blocks or final signatory block.
5. **ENCODING & HYGIENE: PASS.** Shared checks below.

## S.I. 356/2024 — IE-2024-si-356

1. **TEXT CORRECTNESS: PASS.** All 87 nonempty source paragraphs occur after
   normalization, including table cells and footnote wording. Duplicate source
   footnote bodies are normalized into two shared definitions without word loss.
2. **METADATA: PASS.** Publication 2024-08-02 is the stated gazette-notice date;
   2024-07-31 is retained separately as `made_date`. No erroneous enactment-date
   alias remains. Identity, instrument rank, title, source and date basis are explicit.
3. **STRUCTURE: PASS.** Regulations 1–4 occur once. The outer Schedule and inserted
   quoted Schedule 7 are distinct. Quoted regulations 25, 26 and 27A remain nested
   amendment content rather than new top-level instrument provisions.
4. **RICH FORMATTING: PASS.** Both two-column form tables, legal links, two proper
   Markdown footnotes, five quoted blocks, lettered/roman lists and explanatory
   bullets survive. EAMON RYAN is bold. The seal is intentionally omitted and counted.
5. **ENCODING & HYGIENE: PASS.** Shared checks below.

## Additional historical format gate — IE-1995-act-2

1. **TEXT CORRECTNESS: PASS.** The current HTML's 424 nonempty source paragraph
   elements are present after normalization (source element count differs from
   the 420 normalized output blocks). The source versions are authentic dated
   consolidations; no historical text was reconstructed by undoing amendments.
2. **METADATA: PASS.** Original title and 1995-03-15 enactment date remain separate
   from source cutoffs. Archived PDFs are point-in-time; mutable current HTML is
   explicitly current. Technical PDF dates are not used as legal publication dates.
   One duplicated index row does not create a fictitious additional text version.
3. **STRUCTURE: PASS.** Six parts and 50 sections (1–45 plus 6A and 11A–11D) remain
   ordered in inspected PDF and HTML versions. Running headers, page numbers and
   annotation explanations do not leak into operative paragraphs. Inline amendment
   markers and their brackets remain in the source text.
4. **RICH FORMATTING: PASS.** PDF/HTML preserve source headings, emphasis, nested
   lists, quoted insertions and links. These Adoptive samples have no operative
   tables, formulae or footnotes; separate Valuation/Digital Services fixtures cover
   PDF tables and notes. PDF-derived links follow actual PDF annotations, which
   need not match HTML's link coverage or destination spelling.
5. **ENCODING & HYGIENE: PASS.** Current file and the inspected historical bodies
   contain no unintended CommonMark code blocks. Shared current-file checks pass.

The current-cutoff PDF (2023-07-03) and HTML produce **11,198 word tokens in the
same order**, not merely a percentage similarity. The real
[same-cutoff Markdown diff](adoptive-same-cutoff-pdf-html.diff) was inspected:
differences are HTML-only cross-links, equivalent source URL forms, ellipsis
presentation, a space after section 6A's dash and PDF bold closing brackets.
The word comparison is supplementary: headings, nested lists, link provenance and
these residual punctuation differences were also reviewed. One HTML cross-reference
in the Adoption Act 2010 definition is already incorrectly local in the official
source; the converter preserves it rather than inventing a legal correction.

The [adjacent historical PDF-to-HTML diff](adoptive-history-pdf-html.diff) records
2021-04-01 to 2023-07-03. Genuine wording changes are present, including surviving
parent and gender-neutral pronouns; they are not a silent format substitution.
The earlier 2020-to-2021 definition change was checked against authentic PDF pages
in the Step 0 spike. Full-pipeline commits `26f63dce` (2020), `298cd29d` (2021) and
`390ba3d8` (2023) contain exactly the corresponding direct source-render body.
Their full hashes and states are recorded in the evidence JSON.

## Shared checks and manual inspection

All six YAML frontmatters parse, their identifiers match safe filenames, dates are
ISO-8601 and source routes identify the correct official pages. Every metadata
extra in the structured records is present in flattened frontmatter. The source
metadata inventory was checked for applicability: absent source values are not
invented, editorial annotations are distinct from the plain legislative body,
and per-version provenance remains in structured history/commit metadata.

All six files are valid UTF-8, have no C0 controls, CRLF, trailing spaces, observed
mojibake or leftover XML/HTML, and end with exactly one newline. Independent
CommonMark parsing finds **zero accidental code blocks** in every file. This
rechecks the previous quote-blank-line defect that had produced 1,360 such blocks
in Finance. Word-presence normalization is only a diagnostic for missing text;
it is not used to waive punctuation, structure or formatting requirements.

A headless Chromium side-by-side inspection compared the official SI HTML with
rendered final Markdown: title, initial provisions, nested schedule and both
2-column form tables are readable and complete. Screenshots were captured locally
as `/tmp/ie-cross-review/si-side-by-side.png` and `si-tables-side-by-side.png` and
visually inspected. The preview renderer lacked a footnote extension; raw `[^n]`
in that preview does not invalidate the verified Markdown reference/definition
pairs. The review did not take over desktop controls or publish a sample.

The binary-image limitation is explicit: 1922's annex image has an omission marker;
decorative source images are counted but not embedded. Aggregate image counts
include separately attributed enacted/current representations, not a claim of
that many distinct normative figures. LRC legal reuse and full-corpus correctness
are not certified by this sample gate.
