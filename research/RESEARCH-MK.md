# Macedonia source research

Source: [LDBIS](https://ldbis.pravda.gov.mk/Prebaruvanje.aspx), the Ministry of
Justice legislation database. The source was used directly for the bootstrap on
2026-11-01. Five captured cards are retained under `tests/fixtures/mk/`.

## Scope and access

The public search is an ASP.NET WebForms page. A search is submitted with the
hidden view-state fields and returns links to `PregledNaZakon.aspx?id=N`. Each
card links to an official PDF under `/PdfFiles/`. Discovery therefore costs one
search round trip plus one card and one PDF request per listed document. The
bootstrap inventory found 5,609 relevant cards. The final scope contains laws, constitutional laws, the
Constitution, constitutional amendments, and related records reached through
those cards. It is deliberately not the full 61,000+ result catalogue, which
also contains regulations, decisions, instructions, agreements, declarations,
resolutions, and other acts. Of the relevant cards, 5,264 had publishable source
PDFs after excluding unavailable PDFs and consolidated records.

LDBIS exposes no dependable daily change feed. The production daily path will
rescan the official result set and rely on Source-Id and Norm-Id commit
idempotency. A full rescan is intentionally conservative and costs one search,
then only changed or missing cards after the local cache is applied. The live
advanced search currently reports a Telerik grid. The discovery implementation
uses the original all-rows grid command and expands each seed card's related
version chain.

## Metadata inventory

The card exposes title, legal-text kind, version label, territorial validity,
institution, official gazette, gazette issue, publication date, entry-into-force
date, application start, expiry date, active/inactive status, PDF URL, and links
to related versions. The seed search is restricted to active `Закон` records
because the source has no stable export for the complete relevant set. Related
card closure adds constitutional and other records that belong to those chains.
The parser stores the six common fields in `NormMetadata` and the remaining
source values in `extra`.

## Formatting inventory

The official text is PDF content. Born-digital pages carry selectable text;
older and pale pages may be scans and require OCR. Paragraphs, headings, lists,
tables, bold, italic, footnotes, links, formulas, quotations, annexes, and
signatories can occur in the PDF. The PDF image layer is source input for OCR,
not a separate legal object, so it is not reported as a dropped image. Only an
image intentionally omitted without preserving its legal content would need an
`images_dropped` count. The current parser preserves extracted lines and renders tables as pipe
Markdown when the PDF exposes table cells. Scanned table pages use the OCR
reader's cell mode and remain part of the mandatory side-by-side review.

## Version history spike

The card's related-version links expose a chain of original texts and amendment
texts. The bootstrap evidence is retained in `tests/fixtures/mk/version-spike.txt`
and shows two versions of one law with publication dates and separate source IDs.
The source's effective-date field is used when present; otherwise publication
date is the only source-stated date.

## Reform coverage check

`scripts/check_mk_reform_coverage.py` compares every saved related-card reform
whose act is also in the published data with the generated Git `Source-Id` and
`Norm-Id` trailer pair. It is intended to run after bootstrap and after each
monthly update. A full-corpus result still requires the maintainer-side rebuild
because the prepared fork is not the engine output.

## Licensing and attribution

The corpus links back to the official LDBIS record for every law. The public LDBIS page identifies the Ministry of Justice as the database
publisher and displays a 2016 Ministry copyright notice, but no separate open
data or text-reuse licence was found on the public search page. This repository
therefore links every record to LDBIS and does not claim that source text is MIT
licensed. Pipeline code is MIT licensed. The source licence position remains a
maintainer and legal review item before redistribution beyond this contribution. The `mk_words.tsv.gz` and `mk_capitals.tsv.gz` assets are generated
from the captured Macedonian corpus for OCR post-processing. They are not
upstream Tesseract data, and no separate third-party licence statement was
found for them. Their provenance is the LDBIS-derived corpus, so they should be
removed or relicensed if source-text redistribution is not approved.

## Five-law quality review

Date: 2026-11-02

The cards and PDFs are official-source captures under `tests/fixtures/mk/raw/`.

| Law | Metadata | PDF text | Article structure | Encoding |
| --- | --- | ---: | ---: | --- |
| `RM-2013-187-30409` | PASS | 197 paragraphs | 18 article headings | PASS |
| `RM-2013-187-30410` | PASS | 90 paragraphs | 4 article headings | PASS |
| `RM-2013-187-30412` | PASS | 418 paragraphs | 20 article headings | PASS |
| `RSM-2026-212-74875` | PASS | 101 paragraphs | 8 article headings | PASS |
| `RM-table-28131` | PASS | scanned PDF | REVIEW OPEN | PASS |

The parser preserves line breaks, classifies Macedonian `Член N` headings as
articles, strips C0/C1 controls without deleting line feeds, and escapes pipe
characters when a text table is available from `pdfplumber`. Scanned pages are
OCR input, so `images_dropped` is zero unless a future parser deliberately omits
legal image content. The OCR path selects partner language models for treaties
and keeps the selected Latin or Cyrillic reading instead of mixing scripts.

The earlier `NRM-1945-1-145` card has no source PDF and is excluded from the
quality gate and production corpus. The additional `RM-table-28131` capture is
a scanned PDF. It has no selectable table cells, so `pdfplumber` cannot recover
its grid. The scanned table comparison is recorded in `tests/fixtures/mk/quality-review.md`,
but the gate remains open because the review found language-specific OCR substitutions. The fixture and OCR path are present,
but this document does not claim owner approval while that comparison is open.

The repository scope is seeded by active `Закон` records and expanded through
each card's related-version links. This includes constitutional laws,
constitutions, and constitutional amendments without importing the entire
61,000-record LDBIS catalog. The captured relevant scope contains 5,609 cards,
of which 5,264 have publishable PDFs after the documented exclusions. Five real
cards were fetched in the live validation and the related-version parser was
exercised against their HTML. A separate 50-law fetch benchmark completed
50/50 with zero errors in 5m58s at one worker and 0.5 requests/second. The
existing full corpus passes the SPEC v0.5 check and the pipeline health and
deep-health checks when inspected from a clean clone.

The five-law quality gate remains open pending the scanned-table side-by-side
comparison and an explicit review record.
