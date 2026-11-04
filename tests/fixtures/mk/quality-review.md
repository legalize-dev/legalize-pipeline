# Macedonian five-law quality review

Review status: open pending maintainer approval.

The scanned fixture `RM-table-28131.pdf` was run through the branch OCR path
with the local pinned 53-model cache. The PDF has 12 pages. Pages 2 through 11
are image-only pages; pages 1 and 12 contain a text layer. The run returned
`text_source: mixed`, 359 output lines, zero doubtful pages, and zero unread
pages.

The page comparison found the following.

- The Macedonian title and articles 1 and 2 are present in the output.
- The English treaty text is retained in Latin script rather than being
  converted to Cyrillic.
- The repeated gazette header and page counters are removed from the published
  body.
- The scanned page contains OCR substitutions such as `reprasentatives` for
  `representatives` and `polilical` for `political`. These are recorded as
  review findings and mean this gate is not marked passed.

The output was generated from the official fixture PDF and inspected against
rendered source pages. The next quality pass must either correct those
language-specific substitutions through a reproducible post-OCR rule or mark
the affected lines unread before the maintainer approves the gate.
