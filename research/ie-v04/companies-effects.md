# Companies Act: indirect effects and commencement evidence

Verified on 2026-10-13 against the official eISB sources. The Companies Act 2014
[Legislation Directory](https://www.irishstatutebook.ie/isbc/2014_38.html) cites
older provisions *as inserted or substituted by* later instruments. The later
instrument supplies the event identity; the older host provision is retained in
the full citation rather than emitted as a second, pre-enactment amendment.

The regression fixture `tests/fixtures/ie/sample-effects-companies-2014.html`
contains the 16 unchanged indirect-effect rows plus two preceding rows needed to
retain their scope. Its comment records the full original source SHA-256.
These rows identify eight later instruments. A separate regression keeps public
and private Act namespaces distinct even when their year and number coincide.

Eleven rows also reproduce commencement dates belonging to the older host Acts.
The repairs are restricted to Companies Act 2014, the exact later instrument,
original date and cited provisions. Each retains `directory_commencement` and
`directory_commencement_source`; `source_correction` identifies the evidence.

| Later instrument and cited provision | Directory date | Correct commencement | Official evidence |
|---|---|---|---|
| Gas (Amendment) and Miscellaneous Provisions Act 2024, s. 20(b) | 3 June 2014 | 1 June 2024 | [SI 208/2024, article 4](https://www.irishstatutebook.ie/eli/2024/si/208/made/en/html) |
| Water Services (Amendment) Act 2022, ss. 9(b), 10(c), 15 | 29 March 2013 | 1 January 2023 | [SI 678/2022, article 4(b)](https://www.irishstatutebook.ie/eli/2022/si/678/made/en/html) |
| Hallmarking (Amendment) Act 2019, ss. 6, 17(2) | 8 November 1983 | 30 September 2019 | [SI 439/2019, article 2](https://www.irishstatutebook.ie/eli/2019/si/439/made/en/html) |
| Finance Act 2017, ss. 66, 67 | 1 November 2001 | 25 December 2017 | [Finance Act 2017 commencement table, ss. 61–67](https://www.irishstatutebook.ie/isbc/2017_41.html#commencement) |

The directory's Finance Act citation to s. 66(c) is retained verbatim even though
the inserted provisions appear under s. 66(b) in the
[enacted section](https://www.irishstatutebook.ie/eli/2017/act/41/section/66/enacted/en/html).
Both belong to the same dated instrument; this does not create a different event.

The full directory preflight resolves 1,710 effects across 66 instrument IDs and
parses the enacted body with all date guards intact. It does not replace the
50-law benchmark or validation of every archived PDF. Invalid effect publication
dates now fail before expensive source-body extraction.
