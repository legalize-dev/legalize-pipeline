# Ireland v0.4 — independent Step 7 quality review

Reviewed 2026-10-08. Round: **sample-2**. Result: **0/5 laws fully PASS**.
Do not start full bootstrap on these outputs. This is a read-only review of the
full-pipeline Markdown, not a parser-unit-test approval. No parser fixes were
made by the reviewer during this review.

The sample repository was `countries/ie-v04-sample-2`, with the five paths below.
Line references identify that captured round and may move after regeneration.
Official fixtures under `tests/fixtures/ie/` and the URL-keyed raw source cache
were compared with the generated Markdown. The complete Step 7 and onboarding
README were reread before the review.

| Law / relative Markdown path | Text | Metadata | Structure | Rich formatting | Encoding |
|---|---|---|---|---|---|
| Constitution — `ie/66/IE-1937-constitution.md` | PASS | PASS | PASS | FAIL | PASS |
| Constitution of the Irish Free State Act 1922 — `ie/e1/IE-1922-act-1.md` | PASS | FAIL | FAIL | FAIL | PASS |
| Finance Act 2024 — `ie/49/IE-2024-act-43.md` | PASS | PASS | PASS | FAIL | PASS |
| Royal Hibernian Academy Act 2023 — `ie/5b/IE-2023-act-P1.md` | PASS | PASS | PASS | FAIL | PASS |
| S.I. 356/2024 — `ie/29/IE-2024-si-356.md` | PASS | FAIL | FAIL | FAIL | PASS |

## Constitution of Ireland — IE-1937-constitution

1. **TEXT CORRECTNESS: PASS.** All 542 operative paragraphs inspected after the
   first article anchor occur in the rendered text after normalization of Markdown
   formatting and whitespace. The following editorial index is correctly outside
   the operative body. No mojibake, leaked HTML, or observed missing operative text.
2. **METADATA: PASS.** Identifier, rank, source, adoption date, operation date,
   enrollment date and current-text warning are retained. The latest amendment is
   C38/2019, with its signature date, rather than a fabricated current-text date.
3. **STRUCTURE: PASS.** Article sequence is 1–50 plus 28A and 42A; 52 article
   headings are present in order, with subject headings and preamble. Article 19
   is present even though this source omits the otherwise usual article anchor.
4. **RICH FORMATTING: FAIL.** The presidential declaration at line 151 begins
   `"In the presence of Almighty God I do solemnly..."` as an ordinary paragraph,
   not a blockquote. Council-of-State and judicial declarations at lines 741 and
   831 have the same defect. Subparagraphs `(a)` / `(b)` in Article 23 at lines
   471–473 remain plain paragraphs rather than a Markdown list. Preserve legal
   labels when introducing list syntax. Preamble italics and degree-sign legal
   numbering are present. No normative tables, footnotes or signatory block occur
   in this sample body; source navigation and the editorial index are not tables
   to import into the law. Probable cause: `_parse_constitution_html` and
   `_html_inline_text` produce generic paragraphs without quote/list semantics.
5. **ENCODING & HYGIENE: PASS.** See shared checks below.

## Constitution of the Irish Free State Act 1922 — IE-1922-act-1

1. **TEXT CORRECTNESS: PASS.** All 265 source body/backmatter paragraphs occur in
   the normalized output; Irish accents and the bilingual second-schedule heading
   survive. Two source tables retain their rows and column counts.
2. **METADATA: FAIL.** Frontmatter line 2 gives the Irish title
   `Acht um Bunreacht Shaorstáit Eireann, 1922`, while `title_ga` contains the
   English title. The enacted English XML metadata gives
   `CONSTITUTION OF THE IRISH FREE STATE (SAORSTÁT EIREANN) ACT, 1922`.
   The rendered publication/enactment date is `1922-10-25`, but the official
   enacted XML has `<dateofenactment>19221206</dateofenactment>`. The API's
   `dateSigned` is therefore not authoritative for this enacted-text record.
   `pdf_url` points to `.../bill/1922/1/eng/ver_b/bills1922-23a-03.pdf`, a bill
   version rather than the enacted Act. Preserve the API object losslessly but
   reconcile title/date with the enacted primary source and require an enacted
   Act manifestation for the Act's PDF. Probable cause:
   `ISBMetadataParser.parse` trusting API fields and selecting the first bill PDF.
3. **STRUCTURE: FAIL.** All three original sections and 83 constitutional
   articles are present, as are two schedules. However, the treaty's `ANNEX.`
   at line 492 is a plain paragraph, with its subordinate headings such as
   `DOCKYARD PORT AT BEREHAVEN.` also plain. The annex is not its own structural
   block. Probable cause: `_parse_schedule` / `_parse_paragraph` do not recognize
   the centered annex heading in early XML.
4. **RICH FORMATTING: FAIL.** Lettered entries such as `(*a*)` / `(*b*)` at lines
   181–183 and 397 onward are flat paragraphs. The oath at line 113 and the treaty
   oath following line 423 lack blockquote structure. The signatory table at
   lines 481–492 retains names and columns, but signatories are not bold. Table
   rowspans are expanded consistently; no table text is missing. No footnotes
   are present in this source. Probable cause: XML `_parse_paragraph` and
   schedule/table handling retain inline text but omit legal list/quote/signature
   roles.
5. **ENCODING & HYGIENE: PASS.**

## Finance Act 2024 — IE-2024-act-43

1. **TEXT CORRECTNESS: PASS.** All 3,529 source body/backmatter paragraphs excluding
   moved footnotes occur in the normalized Markdown. This content-presence check
   is supplemented by table/formula inspection; it does not replace structural
   review. No observed truncation or mojibake.
2. **METADATA: PASS.** Act identity, 2024-11-12 signature/enactment date, source,
   genuine enacted PDF, English summary and Irish titles are present. The complete
   source bill object is retained in `parliament_metadata`, including arrays and
   unknown fields. Amendment identity and as-enacted warning are explicit.
3. **STRUCTURE: PASS.** Six parts, eight chapters, sections 1–118 and two schedules
   retain their sequence. The 12 data tables have the source row counts and widths
   after allowing for the added Markdown header row. All 35 footnote references
   have exactly one matching definition.
4. **RICH FORMATTING: FAIL.** There are no legal blockquotes or Markdown lettered
   lists: the only `>` lines are the generic as-enacted warning. For example,
   section 6's quoted replacement subsection beginning `“(4A) (a) For the purposes
   of this section...` is flattened with its nested `(a)`, `(i)` and `(ii)` labels.
   Lines 261 onward similarly flatten the replacement subparagraphs beginning
   `“(i) the qualifying interest paid by the claimant for—`. Nested amendment text
   must retain quote boundaries and list depth, not only its words. Inline bold
   and italics, 12 tables, and 35 real Markdown footnotes pass. The formulas
   `A - B`, `A × D/E`, `B × D/E`, `F × G/H` and `F × I/J` retain their symbols
   and order; plain-text source formulas do not require invented LaTeX. The source
   XML has no general hyperlink encoding for all prose citations, so absent
   invented cross-links are not a new failure. No signatory block is present.
   Probable cause: `_parse_paragraph` always emits `parrafo`, ignoring source
   indentation and quotation transitions.
5. **ENCODING & HYGIENE: PASS.**

## Royal Hibernian Academy Act 2023 — IE-2023-act-P1

1. **TEXT CORRECTNESS: PASS.** All 22 operative source paragraphs occur in the
   normalized body. Preamble clauses, accents and the source wording are retained.
2. **METADATA: PASS.** Private identifier P1 remains separate from public Act 1;
   actual title, 2023-12-20 enactment date, canonical private-Act source, enacted
   PDF, bilingual fields and complete parliamentary metadata are present.
3. **STRUCTURE: PASS.** All seven sections occur once, in source order, with their
   correct titles. There are no schedules or annexes in the source.
4. **RICH FORMATTING: FAIL.** Section 2's `(a)` and `(b)` at lines 53–55, and
   equivalent entries in sections 3, 5 and 6, are plain paragraphs instead of
   Markdown lists. Bold enactment formula/section markers and italics survive.
   This Act's quoted word substitutions are inline quotations, so they should
   remain inline rather than turn each sentence into a blockquote. There are no
   tables, footnotes, standalone quotation blocks or signatories. Probable cause:
   `_parse_paragraph` does not convert enumerated source paragraphs into lists.
5. **ENCODING & HYGIENE: PASS.**

## S.I. 356/2024 — IE-2024-si-356

1. **TEXT CORRECTNESS: PASS.** All 87 nonempty source body paragraphs are present
   after normalization. The source itself repeats its two footnote definitions;
   the parser has not invented their wording, but their normalized representation
   fails formatting below. No operative-text truncation observed.
2. **METADATA: FAIL.** `publication_date: 2024-08-02` and `made_date: 2024-07-31`
   correctly distinguish the gazette notice and making dates. However,
   `enactment_date: 2024-08-02` incorrectly labels that gazette notice date as the
   making/enactment date. Preserve the actual made date and explicit basis for
   any publication-date fallback. Title, SI rank, source URL and identity pass.
   Probable cause: `ISBMetadataParser._from_source` assigns the publication date
   directly to an `enactment_date` extra for every HTML source.
3. **STRUCTURE: FAIL.** Regulations 1–4 are present once. The outer Schedule and
   the quoted inserted Schedule 7 collapse into `## SCHEDULE “SCHEDULE 7` at line
   113 instead of distinct outer/inner headings. Probable cause: `_parse_html`
   pending centered-heading concatenation.
4. **RICH FORMATTING: FAIL.** References at lines 25 and 39 remain `2004^1` and
   `2010^2`, with no `[^1]` / `[^2]` links. Lines 182–188 repeat both plain-text
   definitions. Normalize them to two definitions with shared references, not
   four duplicated trailing paragraphs. Replacement regulations 25, 26 and 27A
   and the inserted schedule have no blockquote structure. Lettered/roman lists
   and the explanatory note's literal `•` lines are not Markdown lists. The
   signatory `EAMON RYAN,` at line 164 is not bold. Both two-column form tables,
   hyperlinks to cited Acts and inline italics are retained. Probable causes:
   `_html_inline_text` treats superscript as caret text without footnote context;
   `_parse_html` does not assign footnote/list/quotation/signature roles.
5. **ENCODING & HYGIENE: PASS.**

## Shared verification and next iteration

All five files parse as UTF-8; YAML frontmatter parses; identifiers match their
filenames. All files have Unix newlines, exactly one final newline, no trailing
spaces, no C0 controls and no observed mojibake or HTML in the rendered body.
Raw source URLs identify the correct official law pages. Alphanumeric paragraph
presence was used only to find missing content, not as a licence to change
punctuation or formatting. Source paragraphs with footnotes were checked with
definitions separated, and the XML footnote reference/definition sets match.

Fix first: (1) reconcile enacted primary metadata and reject bill PDF substitution;
(2) preserve legal quotes, nested lists and early/inserted annex headings across
XML and HTML; (3) normalize HTML footnotes and signature roles. Re-render all five
through the full pipeline and repeat the five dimensions with delta feedback.
The additional Adoptive Leave Act PDF-to-HTML history review remains required;
these five samples alone cannot pass the archival-PDF format gate. Historical
status projection and LRC redistribution permission are separate known gates,
not newly duplicated findings in this report.

## Direct-render format iteration before sample-3

The regenerated bodies in `/tmp/ie-rich-review/sample-*.md` were independently
reviewed after the format fixes. These are fixture renders, without metadata or
commits, so this iteration does not supersede the full-pipeline gate above.

The earlier missing declarations, oaths, legal lists, annex headings, quoted
Schedule 7, bold signatories and two SI footnotes are now represented. Private-Act
word substitutions correctly remain inline quotations. Finance retains 12 tables
and 35 footnote definitions; the SI retains both two-column form tables inside its
quoted schedule. An independent source-paragraph presence check found no omitted
text in the three XML fixtures (including table paragraphs; footnote bodies checked
separately). This normalization check is supplementary to the structural checks.

An intermediate render incorrectly broke every quoted paragraph into a separate
blockquote, producing 1,360 unintended CommonMark code blocks in Finance and six
in the SI. The corrected render preserves quotation prefixes on blank lines. A
fresh `markdown_it` parse of the final five bodies has **zero code blocks**;
Finance section 6's formulas remain paragraph text within their actual nested
list/quote containers. The SI's regulation 2(a)(i) and (ii) now share their proper
list level and both replacement definitions are blockquotes.

| Body | Blockquotes | Tables | Footnote definitions | SHA-256 |
|---|---:|---:|---:|---|
| Constitution | 3 | 0 | 0 | `4a7471376f3607afba204f5c50de5fc44ffac1eaf1d4186cc7749255e347e058` |
| 1922/1 | 2 | 2 | 0 | `1d0d024b6012c948bb8bd21cb73b03cd6910e4192c49b57de2950ed4428a19f7` |
| Finance 2024 | 250 | 12 | 35 | `364bb194aee95c10189601359e0afbc971ad1860a25112468a56fd7b2ad5fe1e` |
| Private 2023/P1 | 0 | 0 | 0 | `43dc144a6ba65d621c9c7d6ec6f6973d84259aca7f46d9e7530de62dddc64f1a` |
| SI 2024/356 | 5 | 2 | 2 | `883089bd6297c15f4a40c6c3f9ae88d01b837f747afe7153979337809d829e69` |

All five bodies have one final newline and no trailing whitespace. No remaining
format failure was identified in this iteration. Full-pipeline sample-3 must
still verify metadata reconciliation, historical state and the complete five
dimensions; the PDF-to-HTML history comparison remains additional required work.
