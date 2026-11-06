# Macedonia source research

Source: [LDBIS](https://ldbis.pravda.gov.mk/Prebaruvanje.aspx), the Ministry of
Justice legislation database. The source was used directly for the bootstrap on
2026-11-01. Five captured cards are retained under `tests/fixtures/mk/`.

## Scope and access

The public search is an ASP.NET WebForms page. A search is submitted with the
hidden view-state fields and returns links to `PregledNaZakon.aspx?id=N`. Each
card links to an official PDF under `/PdfFiles/`. Discovery therefore costs one
search round trip plus one card and one PDF request per listed document. The
scope (section 0.6) holds the laws, constitutional laws, the Constitution,
constitutional amendments and law corrections in force, 5,567 cards on
2026-11-05. It is deliberately not the full 61,000+ result catalogue, which also
contains regulations, decisions, instructions, agreements, declarations,
resolutions, and other acts. The first bootstrap's inventory of 5,609 cards had
5,264 with publishable source PDFs after excluding unavailable PDFs and
consolidated records.

LDBIS exposes no dependable daily change feed. The production daily path will
rescan the official result set and rely on Source-Id and Norm-Id commit
idempotency. A full rescan is intentionally conservative and costs one search,
then only changed or missing cards after the local cache is applied. The live
advanced search currently reports a Telerik grid. The discovery implementation
uses the original all-rows grid command and expands each seed card's related
version chain.

## 0.6 Scope

One scope serves both paths. `discover_scope()` for the bootstrap and
`discover_publication_date()` for the monthly job run the same searches and the
same rule (`_scope`), and `coverage.json` states the same scope. The seeds are the
active records of kind `Закон`, `Уставен закон`, `Устав` and `Амандман на Уставот`,
and the active corrections of a law or a constitutional amendment described below.
Every card a seed links is then added when it belongs (`_belongs`). It must be a
law or a constitutional record, so the decisions, decrees, rulebooks and
corrections of other acts that chains also link stay out, and it must be in force.

LDBIS's active flag alone does not say whether a law is in force. It marks some
laws repealed that are not. The 2004 nature protection law is inactive with no end
date and was last amended in January 2025, and the 1995 secondary education law
carries an expiry date of 13.08.2019 although its amendments of 2025 begin "Во
Законот за средното образование („Службен весник на Република Македонија“ број
44/1995 ...". So a card LDBIS marks repealed is kept when nothing on LDBIS shows
that its law ended: the law has no later enactment of its title, and it either has
no expiry date or was amended after that date. An amendment follows its law, the
latest enactment of its title published on or before it. That keeps the three
2012 to 2014 amendments of the 1994 wage payment law, which LDBIS marks repealed, and leaves
out the 2003 amendment of the foreign trade law, since the 2002 law it amends
expired in 2004 (LDBIS still marks the 1993 law it replaced in force).

Measured on 2026-11-05 over the cards the seeds link, 37 of the 500 laws LDBIS
marks repealed are in force by that rule, 29 with no end date and 8 amended after
their stated expiry, and 111 amendments marked repealed belong to a law in force.
The other 463 laws and their amendments, about 1,700 records, are left out. The
scope then holds 5,567 records: 5,324 active laws, 148 laws and amendments LDBIS
marks repealed, 81 corrections, the Constitution of 1991 and the federal
constitution of 1974, 8 constitutional amendments and 4 constitutional laws (one of
which LDBIS files as a constitutional law, a decision on property of the
Constitutional Court). The committed code had seeded active laws only, so no path
reached the Constitution or its amendments.

The corrections are the active records of kind `Исправка (на закон или друг
пропис)` whose title corrects a law or a constitutional amendment ("Исправка на
Законот ...", "Исправки на Законот ...", "Исправка на Амандманот ..."). Measured on
2026-11-04, LDBIS lists 573 active corrections, and 111 of them correct a law or an
amendment. The other 462 correct decisions, rulebooks, decrees, programmes,
licences and court decisions, which this corpus does not hold. A correction is its
own file with one commit, and it is also a commit on the law it corrects, or on the
law amended by the act it corrects, like an amendment.

The title does not reliably say which act a correction corrects. LDBIS lists
one law as "осигурвање" while its correction says "осигурување", another
correction says "прогласување" where its act says "престанување", and a
correction's links also reach laws of other names. The act is read from the
correction's own links instead. Each link carries the linked card's gazette
date, and the corrected act is the latest one published on or before the
correction, leaving out Constitutional Court decisions and other corrections.
That named the right act for every one of the 111 when checked by hand. A
correction is a seed when that act belongs to the corpus by the rule above, which
keeps 81. The other 30 correct repealed laws and their amendments and stay out
with them. Two of those are also a gap in the source: LDBIS links the correction
of the 2012 amendment of the labour records law (27376) and the correction of the
amendment of the financial transactions tax law (7409), a law out of force since,
to no card at all. Matching titles instead had kept 82, dropping 22 corrections of
laws in force and keeping 3 that do not belong.

Titles of one law are matched after dropping the definite article (section on the
version history), counting every dash as a space ("бонови – ваучери" and "бонови -
ваучери"), reading Latin letters typed inside a Cyrillic word as Cyrillic
("Академијатa", "нa"), and reading "Република Северна Македонија" as "Република
Македонија", since an amendment after the 2019 renaming names a law by the new name.

Run over the scope, each of the 111 amendments LDBIS marks repealed is a commit on
exactly one law, and so are 79 of the 81 corrections. 196 amendments
marked active and the other two corrections are a commit on none, though each is
published as its own file. LDBIS has no law of
their title for 136 of them, such as the law on the pay of elected and appointed
officials, or the 2007 medicines law, which LDBIS holds under its first title
"медицинските помагала" while its later amendments say "медицинските средства". 15
amend a law LDBIS holds only as a consolidated text, which enacts nothing here, 22
are dated before any law of their title, 19 amend a law that ended, which LDBIS left
marked active, and 6 are linked by no card of their law.

## 0.7 Format coverage

Of the 5,420 PDFs captured for the scope, 4,264 have a text layer on every page
and 1,156 have scanned pages, 38,385 pages in all, which are read by OCR. In the
published corpus 484 files come wholly from OCR and 665 are mixed. Text layer
tables were found on 69 pages in 33 PDFs, and the OCR reader finds 5,686 tables on
4,983 scanned pages in 198 PDFs. `tests/fixtures/mk/quality-review.md` records
how these were counted and which kinds of table are still missed.

## Metadata inventory

The card exposes title, legal-text kind, version label, territorial validity,
institution, official gazette, gazette issue, publication date, entry-into-force
date, application start, expiry date, active/inactive status, PDF URL, and links
to related versions. The seed search is restricted to active laws, constitutional
records and the corrections of a law (section 0.6) because the source has no
stable export for the complete relevant set. Related card closure adds the records
of those chains that belong to the corpus.
The parser stores the six common fields in `NormMetadata` and the remaining
source values in `extra`.

## Formatting inventory

The official text is PDF content. Born-digital pages carry selectable text;
older and pale pages may be scans and require OCR. Paragraphs, headings, lists,
tables, bold, italic, footnotes, links, formulas, quotations, annexes, and
signatories can occur in the PDF. The PDF image layer is source input for OCR,
not a separate legal object, so it is not reported as a dropped image. Only an
image intentionally omitted without preserving its legal content would need an
`images_dropped` count. The parser renders every table it finds as a pipe table.
On a text layer page that is `pdfplumber`'s table, kept when its cells hold exactly
the printed characters inside its box. On a scanned page the OCR reader finds ruled
tables from the cells their rules enclose, and tables set between rules across
only from their header band and text columns, and reads each cell on its own.
`tests/fixtures/mk/quality-review.md` compares three laws with their PDFs page by
page, and records the corpus counts and the kinds of table still missed.

## Version history spike

The card's related-version links expose a chain of original texts and amendment
texts. The bootstrap evidence is retained in `tests/fixtures/mk/version-spike.txt`
and shows two versions of one law with publication dates and separate source IDs.
Each commit is dated by the act's publication date, and the card's entry into
force date goes in the `Effective-Date` trailer.

A card links every card of the same name, so the 2012 pension law
(RM-2012-98-25996) also links the 1993 law it replaced and that law's 25
amendments. An amendment belongs to the latest enactment of the title published
on or before it. A law's card also omits some of its amendments (the same
pension law misses five that only its other amendments link), so the history
follows the links on each amendment of the title as well. The pension law then
has its own commit and the 35 amendments through 212/2026.

An amending act is recognised by its title, the act's own kind word followed by
"за изменување", "за дополнување" or both, and then "на" and the law. Older
titles say "за измени и дополненија", "за измена" or "за дополнение", two misspell
"доплнување" or end "дополнувањe" with a Latin e, and one doubles the "за". Those
25 amending acts in scope were first missed and had no commit on their law. The
words must follow the kind word directly, because 19 ratification laws, such as
"Закон за ратификација на Протоколот за изменување и дополнување на Конвенцијата
...", were first taken for amendments of the convention and lost their own
history. Both were found by comparing the old and new rule over all 61,137 index
rows.

## Reform coverage check

`scripts/check_mk_reform_coverage.py` runs on the built corpus and fails for
each (act, law) pair with no Git commit carrying that `Source-Id` and
`Norm-Id`. It makes two checks. Every act in the repository that a law's LDBIS
card chain links is owed a commit on that law. And every amending act is
matched to the law its title names, the latest enactment of that title
published on or before the act, by title rather than through the links, so an
amendment the links miss still fails. An act whose law is not in the
repository is skipped. It runs after bootstrap and after each monthly update.

## Licensing and attribution

LDBIS publishes no terms of use. The only statement on
[its search page](https://ldbis.pravda.gov.mk/Prebaruvanje.aspx), checked on
2026-11-04, is the footer "Copyright © 2016 Ministry of Justice of the Republic of
North Macedonia", with the contact ldbis@mjustice.gov.mk. No open data licence or
reuse condition is linked from it.

The texts themselves are outside copyright. The Law on Copyright and Related
Rights (Закон за авторското право и сродните права, Службен весник на РМ
115/2010, Article 16 point 2) says that official texts of a political,
legislative, administrative and judicial nature, and their official translations,
are not copyright works ("службените текстови од политичка, законодавна,
административна и судска природа и нивните службени преводи"). The notice can
therefore cover the database and its interface, not the laws. The corpus takes
only the laws and the card facts about them, links every record to its LDBIS
card, and does not claim the source text is MIT licensed. Pipeline code is MIT
licensed. Article 16 is enough to publish the laws, so no permission is needed. A
written confirmation from the Ministry of Justice has not been asked for, and
asking would be a courtesy for the maintainers to decide.

`mk_words.tsv.gz` and `mk_capitals.tsv.gz` are built by
`scripts/build_mk_vocab.py` from the Macedonian Wikipedia articles dump of
2026-10-01 (`mkwiki-20261001-pages-articles.xml.bz2`, MD5
94f0439df898709b92f5bb848372aebf, CC BY-SA 4.0) and from the LDBIS laws whose PDF
has a text layer. They hold words and counts only, no running text, and the
script's header names the dump and how to rebuild them. Run on that dump,
`mk_capitals.tsv.gz` comes out byte for byte. `mk_words.tsv.gz` was built on
2026-10-31, and the laws have been regenerated since, so a rebuild today adds
10,640 words found only in them and drops 37 of the shipped list's 1,121,591.

## Five-law quality review

Date: 2026-11-02

The cards and PDFs are official-source captures under `tests/fixtures/mk/raw/`.

| Law | Metadata | PDF text | Article structure | Encoding |
| --- | --- | ---: | ---: | --- |
| `RM-2013-187-30409` | PASS | 197 paragraphs | 18 article headings | PASS |
| `RM-2013-187-30410` | PASS | 90 paragraphs | 4 article headings | PASS |
| `RM-2013-187-30412` | PASS | 418 paragraphs | 20 article headings | PASS |
| `RSM-2026-212-74875` | PASS | 101 paragraphs | 8 article headings | PASS |
| `RM-table-28131` | PASS | scanned PDF, no table | not reviewed here | PASS |

The parser preserves line breaks, classifies Macedonian `Член N` headings as
articles, strips C0/C1 controls without deleting line feeds, and escapes pipe
characters when a text table is available from `pdfplumber`. Scanned pages are
OCR input, so `images_dropped` is zero unless a future parser deliberately omits
legal image content. The OCR path selects partner language models for treaties
and keeps the selected Latin or Cyrillic reading instead of mixing scripts.

The earlier `NRM-1945-1-145` card has no source PDF and is excluded from the
quality gate and production corpus. The additional `RM-table-28131` capture is
a scanned PDF whose scanned pages, despite its name, hold no table. The scanned
and table review is therefore made on RM-2008-18-14566, RM-2006-10-10930 and
RM-2010-50-19233 and recorded in `tests/fixtures/mk/quality-review.md`.

The repository scope is seeded by active laws, constitutional records and the
corrections of a law, and expanded through each card's related-version links
(section 0.6), without importing the entire 61,000-record LDBIS catalog. The
first bootstrap's captured scope contained 5,609 cards, of which 5,264 had
publishable PDFs after the documented exclusions. Five real
cards were fetched in the live validation and the related-version parser was
exercised against their HTML. A separate 50-law fetch benchmark completed
50/50 with zero errors in 5m58s at one worker and 0.5 requests/second. The
existing full corpus passes the SPEC v0.5 check and the pipeline health and
deep-health checks when inspected from a clean clone.

The comparison against the PDFs is recorded and awaits the maintainer's
approval. It lists what is still wrong rather than claiming a clean read.
