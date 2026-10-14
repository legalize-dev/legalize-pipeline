# Revised Act PDF fixtures

These are selectable, unannotated PDFs linked from the Law Reform
Commission's Revised Acts catalogue. All are original complete source files except
the explicitly named Companies excerpts, whose unchanged source pages and original
file hash are recorded in the provenance manifest. `archive-sources.json` records the exact
source URL, retrieval time and SHA-256. Archive URLs with `versionId` identify
historical objects; the current `/revised/en/pdf` endpoint is mutable. The date
printed as **Updated to** is a consolidation cutoff, not a publication date.

The Adoptive Leave Act snapshots demonstrate a substantive change to the
adopting-parent definition. The Digital Services snapshots demonstrate that
separate official cutoffs can contain the same legislative text: the 2024 and
2025 PDFs differ in editorial material but parse identically. Its 2026 PDF uses
a different text width and physical hyphenation; that layout change must not be
claimed as a legislative amendment. The Valuation Act exercises schedules and
a three-column table with no horizontal borders between its body rows. Its 2018
archive uses bare insertion brackets (`[28.`), without the later `F123[`
editorial prefix; all four such primary sections must still be recognized.

The matching HTML snapshots support an independent text/structure comparison.
`archive-comparison.json` enumerates every ordered token difference, with its
context and cause; golden tests reject any additional difference.
Adoptive Leave has identical word inventory and paragraph-class counts in both
formats. Digital Services preserves all five PDF footnote definitions; its HTML
source lacks the first definition. Valuation preserves every row of its statutory
table. The tests compare section order, schedules, paragraphs, actual amendments,
markup, links and text recall, and reject both a cover-only and a truncated PDF.

The remaining differences include twenty visible line-end hyphens in Digital
Services, its additional first footnote, the position of schedule locators, and
one missing word gap in the Valuation PDF source (`32of`, where HTML has `32 of`).
The PDF glyph gap at that location is smaller than its normal inter-letter gap.
No normative passage is missing in these paired fixtures.

The sources use untagged XEP layouts. The parser supports their marginal and
above-text section headings. It rejects missing sections, unassigned marginal
text, unreadable glyphs, rotated text, image-only body pages and ambiguous table
rows. A raster figure on an otherwise selectable body page becomes an explicit
`[image omitted]` paragraph in source position; its surrounding text is retained.
This follows the onboarding playbook and is not a claim that image content was
transcribed. PDF omission counts include the figures represented by these markers.
HTML/XML counts include source-document images, including omitted decorative
emblems, but exclude navigation and editorial subtrees (`sect-tab`, `annotations`,
`narrative`, `actsreferredto`). Counts are recorded per source URL and summed across
inspected representations, not deduplicated as unique figures. Source hard hyphens at physical line ends are retained: an untagged PDF
cannot reliably distinguish a discretionary hyphen from a genuine compound.
Paragraph boundaries at page breaks and division-title presentation can differ
from HTML. PDF/HTML paragraph tuples are therefore not an equivalence test.

A process-local lock serializes PDF extraction across fetch threads to avoid
concurrent whole-document glyph collections. Other source requests can continue;
this does not cap the memory occupied by already downloaded source envelopes.

Four verified Companies 2020 plain PDFs omit section 1384A from the body despite
listing it in the contents. The provision was already in force, and the annotated
PDFs supplied for the same catalogue rows have the same omission. The sources are
retained with an explicit per-version warning, without reconstructing the missing
text. `archive-companies-2020-source-gaps.json` records the exact URLs, hashes,
cover dates, alternative-source checks and primary commencement evidence. Only
those complete file hashes permit the exact missing set `{1384A}`; another missing
section, changed bytes or an excerpt still fails. `source_warning()` exposes the
limitation for callers to persist and display with the selected version.
The 2020 excerpt deliberately contains only source pages 1, 5, 61, 77, 931 and 932.
It preserves the contents entry and the body transition from 1384 to 1385 as
reviewable evidence, but its own hash is never allowed as a complete snapshot.

Visual verification used Poppler (`pdftoppm`): Adoptive Leave 2020 page 8 and
Valuation 2024 page 52, including the complete ruled table, were inspected.
Valuation 2018 page 29 confirms the bare bracket and marginal title of section 28.
Adoption 2018 page 100 shows a schedule locator wrapping through a definition;
Credit Union 2018 pages 69 and 78 distinguish a compound primary section label from
indented marginal captions belonging to quoted insertions. Companies 2018 pages
137, 198 and 622 show body-size marginal captions with an indented first line, a
raster proxy-voting form, and a single above-text title within a marginal layout.
Its page 345 has an italic citation to section 366 at the end of a physical line;
that citation must remain text, not become a second primary heading. The test
excerpt covers these geometries and is deliberately not a complete Act. The
complete cached Companies source was separately checked against every section in
its contents; `archive-companies-2018-validation.json` records both exact lists
and their differences, including inserted letter-suffixed provisions.
The August 2020 Companies overlap excerpt retains seventeen unchanged source
pages, including nineteen section openings obscured by marginal captions. Source
pages 676, 801 and 1015 were visually checked. The parser separates captions and
body numbers by their distinct glyph baselines, preserving both complete texts;
wrapped references inside captions remain part of their titles. Direct parsing
of the complete source recovers every contents entry except the independently
verified section 1384A omission. The excerpt itself receives no hash exception.
The fixtures are preparation material. No redistribution licence for LRC's
editorial consolidations has been established by the source audit; publication
of these source files remains subject to resolving that licence question.
