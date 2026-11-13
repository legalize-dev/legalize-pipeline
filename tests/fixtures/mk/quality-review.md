# Macedonian text fidelity review against the source PDFs

Date: 2026-11-04. OCR version 8. Review status: awaiting maintainer approval.

This record compares the published text of three laws with their official PDFs,
page by page where tables or reviewed faults sit, so a maintainer can open each PDF
at the page named and check every claim. The three laws cover what the review of
PR 184 asked for: one scanned law with the faults the review quoted, one scanned
law with tables, and one law whose table is in a PDF text layer.

| Law | PDF | SHA-256 | Text source |
| --- | --- | --- | --- |
| RM-2008-18-14566 | [taztuh2piegrulm4vqnd0lcy.pdf](https://ldbis.pravda.gov.mk/PdfFiles/taztuh2piegrulm4vqnd0lcy.pdf) | `e84161bbea45fbfaa1dd7af53d29179ae04c54af58b7324dd0aea0a01b789360` | mixed, 113 of 114 pages scanned |
| RM-2006-10-10930 | [ywdoehfznnsrrmtuowvpu5gw.pdf](https://ldbis.pravda.gov.mk/PdfFiles/ywdoehfznnsrrmtuowvpu5gw.pdf) | `aec654d821df65c9af036ddcd291386ebbee63dab299cf4d45b7defe926fd1d1` | ocr, 30 pages scanned |
| RM-2010-50-19233 | [xk0t0kd4e0wr1ekyqder1ijc.pdf](https://ldbis.pravda.gov.mk/PdfFiles/xk0t0kd4e0wr1ekyqder1ijc.pdf) | `ea08a09cec71e8eacaff3b99717e8bd3d104f64b94c55034c3ada5ce513eaa9a` | text layer |

To reproduce, fetch the three laws with an empty OCR cache and read the JSON the
fetch writes.

```bash
LEGALIZE_MK_OCR_CACHE=/tmp/mk-ocr legalize fetch -c mk --force 14566 10930 19233
```

Page numbers below are the PDF's own, counted from 1.

The earlier fixture `RM-table-28131.pdf` is not used here. Despite its name its
scanned pages hold no table, so it could not show whether tables survive.

## Tables

A table is kept as a pipe table wherever the reader finds one. On a scanned page
the reader finds ruled tables from the cells their rules enclose, including a
first or last column whose outer rule was never drawn, and tables set between
rules across only from their header band and text columns. It reads each cell on
its own with the Macedonian and English models, and the treaty partner's where
there is one, and keeps the reading whose words are all known, else the more
confident one. On a text layer page the `pdfplumber` table is kept when its cells
hold exactly the printed characters inside its box. A table's rows render as one
Markdown paragraph, so the pipe table is not broken by blank lines.

### RM-2006-10-10930, scanned

Three tables, the same classification table in the Macedonian, Bulgarian and
English texts. All three match the PDF cell for cell.

Page 5.

| Република Македонија | Еквивалент на англиски јазик | Република Бугарија |
| --- | --- | --- |
| ДРЖАВНА ТАЈНА | TOP SECRET | СТРОГО СЕКРЕТНО |
| СТРОГО ДОВЕРЛИВО | SECRET | СЕКРЕТНО |
| ДОВЕРЛИВО | CONFIDENTIAL | ПОВЕРИТЕЛНО |
| ИНТЕРНО | RESTRICTED | ЗА СЛУЖБЕНО ПОЛЗВАНЕ |

Page 15, where the source itself prints the gap in "ДРЖ АВНА".

| ЗА РЕПУБЛИКА МАКЕДОНИЯ | ЕКВИВАЛЕНТ НА АНГЛИЙСКИ | ЗА РЕПУБЛИКА БЪЛГАРИЯ |
| --- | --- | --- |
| ДРЖ АВНА ТАЈНА | TOP SECRET | СТРОГО СЕКРЕТНО |
| СТРОГО ДОВЕРЛИВО | SECRET | СЕКРЕТНО |
| ДОВЕРЛИВО | CONFIDENTIAL | ПОВЕРИТЕЛНО |
| ИНТЕРНО | RESTRICTED | ЗА СЛУЖЕБНО ПОЛЗВАНЕ |

Page 24.

| For the Republic of Macedonia | Equivalent in English | For the Republic of Bulgaria |
| --- | --- | --- |
| ДРЖАВНА ТАЈНА | TOP SECRET | СТРОГО СЕКРЕТНО |
| СТРОГО ДОВЕРЛИВО | SECRET | СЕКРЕТНО |
| ДОВЕРЛИВО | CONFIDENTIAL | ПОВЕРИТЕЛНО |
| ИНТЕРНО | RESTRICTED | ЗА СЛУЖЕБНО ПОЛЗВАНЕ |

The English model was the surer reader of page 24's first Bulgarian cell and wrote
it in Latin letters, "CTPOI'O CEKPETHO", until a reading made of known words was
made to win over a surer one that is not.

### RM-2010-50-19233, text layer

Page 3, the fund size table, matches the PDF cell for cell.

| Средства на задолжителниот пензиски фонд | Главнина на друштвото |
| --- | --- |
| Од 100.000.001 до 200.000.000 евра | 2.500.000 евра |
| Од 200.000.001 до 300.000.000 евра | 3.500.000 евра |
| Од 300.000.001 до 400.000.000 евра | 4.500.000 евра |
| Од 400.000.001 до 500.000.000 евра | 5.500.000 евра |
| Од 500.000.001 до 600.000.000 евра | 6.500.000 евра |
| Од 600.000.001 до 700.000.000 евра | 7.500.000 евра |
| Од 700.000.001 до 800.000.000 евра | 8.500.000 евра |
| Од 800.000.001 до 900.000.000 евра | 9.500.000 евра |
| Над 900.000.001 евро | 10.000.000 евра |

### RM-2008-18-14566, scanned

Four tables, the two audit summary sheets of Annex C in English (page 45) and in
Macedonian (page 103, printed sideways and turned upright before it is read). The
structure matches the PDF, with every column in place, the last one included,
whose outer rule the source never drew, and the sub-columns "1. 2.", "Износ %"
and "1." under their headings. The forms' rows are empty in the source and stay
empty. The headers' small print reads less well than the body. Page 103's second
sheet.

| Фон д | Упатувањ (и (ССТ бр.) | Програма | Трошоци пријавени по рефер, годнна | Трошоци во рефер. година врз коке извршена ревизија по случаен примерок | | Износ и процент (стапка на грешки) на неправштни трошоци во случајниот примерок (3) | | Други трошоци врз коине извршена ревизија (4) | Износ на цеправилн ите трошоци во друти примероци на трошоци | Вкупно трошок пријавени кумулативно | Вкупно трошоци врз кон е извршена ревизија кумулативно како процент на вкупните кумулативно пријавени трошоци | Ниво на материјал ност (565) | Нипо на сигурност (70) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | 1. | 2. | Износ | зо | 1. | | | | | |

Where the output has "Фон д", "Упатувањ (и (ССТ бр.)", "рефер, годнна", "коке",
"неправштни", "коине", "цеправилн ите", "друти", "трошок", "кон е",
"материјал ност (565)", "Нипо на сигурност (70)" and "зо", the PDF prints "Фонд",
"Упатување (CCI бр.)", "рефер. година", "кои е", "неправилни", "кои е",
"неправилните", "други", "трошоци", "кои е", "материјалност (%)", "Ниво на
сигурност (%)" and "%". Page 45's English headers have the same kind of misreads,
such as "Dake of perfomance" for "Date of performance" and "Mmemlity" for
"Materiality".

## The review's examples in RM-2008-18-14566

Each string the review quoted, counted in the published text.

| Quoted in the review | Page | The PDF prints | Published now | Count now |
| --- | ---: | --- | --- | ---: |
| The running head, also read in Latin letters as "Cnyx6eH BecHuk Ha PM" | every page | the gazette's running head | removed | 0 |
| "[PA" | throughout | "IPA" | "IPA", as in "The national IPA co-ordinator" | 0 |
| "p: wt on wh wy" | 2 | the ambassador's signature | removed, page listed as unread | 0 |
| "400114 »" and the other page counters | every page | "N од 114" | removed | 0 |

Page 2's signature read differently under OCR version 8, as "p: Le aE ws wy", one
pair 53 % sure. The signature rule now takes a line of three or more words whose
confidence averages under 35 % and never reaches 60 %, with no known word of four
letters or more, no article heading and no other script. Over the 38,385 cached
scanned pages the wider rule drops 2,065 more lines in 388 laws. A sample of 60 of
them held 54 marks and six garbled readings of real words, such as "Dextsing and
athor modified", and every page that loses a line is listed in `ocr_unread_pages`.

## What a reader of RM-2008-18-14566 is told

The frontmatter carries `text_source: mixed`, `ocr_doubtful_pages: 5,6,45,57` and
`ocr_unread_pages: 2,5,6,16,18,49,57,61,106`. Every line left out on an unread
page was checked against the PDF. All but three are signatures, stamps, specks or
crossings read as letters, such as "ст. ..- - - пш а тт" on page 106. The three
are contents entries on pages 5, 6 and 57, the English and Macedonian tables of
contents, whose dotted leaders were read as a run of letters ("ИПА........нноетеннуннни"
on page 57). The English contents also read their leaders as words ("Article 3
Purpose EE EE TS"). Pages 5, 6 and 57 are listed as both doubtful and unread.

## What is still wrong

These faults remain in the three laws. None is hidden by a hand correction, and
`ocr_fixes.json` has no entry for any of the three.

1. Printed square brackets read as a bar. "[Option 3 - Adverse opinion" on page
   53 and "[дел ...... од програмата во однос на: ...]" on page 109 come out as
   "|Option 3" and "|(дел ...|". About twenty such bars remain in 14566, standing
   for "[", "]", "1" or "I". Across the cache a bar at the start of a word stands as
   often for "I", "l" or a cell rule as for "[", so no general rule replaces it. The
   parser no longer takes these lines for table rows.
2. Small print in the audit sheets' headers on pages 45 and 103, quoted above.
3. The EU logo on page 2 is read as "wl ata EUROPEAN UNION", and the letter head
   below it as "Mardal The 12, 1000 Skogle".
4. Leftovers of page 103's sideways running head, ".02, 2008 година" and "ЕП ко ОТ",
   follow its tables.
5. Word misreads in body text such as "authoritics" on page 12, at the rate the
   doubtful page list reports. In 10930 the English "TOP SECRET" inside a
   Macedonian sentence on page 7 comes out in Cyrillic as "ТОР ЗЕСКЕТ".

## Coverage across the corpus

Of the 5,420 LDBIS PDFs, 1,156 have scanned pages, 38,385 pages in all. Text
layer tables were found on 69 pages in 33 PDFs. The counts for scanned pages
follow.

| Scanned tables found | Tables | Pages | PDFs |
| --- | ---: | ---: | ---: |
| Ruled, read from enclosed cells | | 4,905 | 195 |
| Set between rules across only | | 85 | 20 |
| Either kind | 5,686 | 4,983 | 198 |

These are what the reader finds, not a count checked by hand. The pages in this
record were checked by hand. Before this change the corpus held one pipe table.

Two kinds are known to be missed. They stay as plain text, so no words are lost.
In SFRJ-1973-40-623, page 22, tables set between rules with an empty column were
found four times in eight. A ruled tariff grid printed sideways in
RM-2005-49-10884 is not found.

The published corpus was read before OCR version 8, so its scanned tables are
plain text until those pages are read again under version 8.
