"""Read source amendment relations without confusing commencement and publication."""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from datetime import date
from hashlib import sha256
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

from lxml import html

from legalize.fetcher.ie.client import CONSTITUTION_ID, _parse_norm_id

if TYPE_CHECKING:
    from legalize.fetcher.ie.client import ISBClient

logger = logging.getLogger(__name__)

# Complete official pages with empty effects tables; retain a coverage warning for these bytes.
_EMPTY_EFFECTS_DIRECTORIES = {
    "IE-1976-act-23": "23a7ef9449bbebd6828f176ce38e891f349133f4969fa6e5ee81d4c21705562b",
    "IE-2013-act-51": "63507250171797902d74f24b7d53ee92b336a3a8573db57556558b181bd7dabf",
}

# Exact directory claims verified against the original enactments, not later amendments.
# Evidence: tests/fixtures/ie/preexisting-rules-evidence.json.
_PRE_EXISTING_RULES = {
    ("IE-1997-act-26", "12/1992, s. 12"): (
        "Offences under Act designated disqualifying or potentially disqualifying offences, "
        "or as otherwise meriting certain treatment",
        "Section 12(b) originally applies Part III to offences involving violence or its "
        "threat. This is an earlier general evidence rule, not a later amendment of the 1997 Act.",
        "https://www.irishstatutebook.ie/eli/1992/act/12/section/12/enacted/en/html",
    ),
    ("IE-1978-act-2", "6/1957, s.42"): (
        "S.28, limitation on recovery of cert. interest.*",
        "The 1957 limitation refers to section 26 of the Agricultural Credit Act 1947. "
        "Section 28 of the 1978 Act re-enacts that provision; its directory footnote "
        "applies section 20(1) of the Interpretation Act 1937. This is inherited application.",
        "https://www.irishstatutebook.ie/eli/1978/act/2/section/28/enacted/en/html",
    ),
    (
        "IE-2011-act-19",
        "Health (Amendment) Act 1986 (No. 10 of 1986), s. 2(1)",
    ): (
        "Application of Health Acts restricted",
        "Section 1(4) includes sections 35 and 36 in the collectively cited Health Acts. "
        "This is an earlier restriction applying to that family, not a later amendment.",
        "https://www.irishstatutebook.ie/eli/2011/act/19/section/1/enacted/en/html",
    ),
    (
        "IE-2011-act-19",
        "Health Act 1970 (No. 1 of 1970), s. 53(2) as substituted by Health (Amendment) "
        "Act 2005 (No. 3 of 2005), s. 4(a)",
    ): (
        "Application of Health Acts restricted",
        "Section 1(4) includes sections 35 and 36 in the collectively cited Health Acts. "
        "This is an earlier restriction applying to that family, not a later amendment.",
        "https://www.irishstatutebook.ie/eli/2011/act/19/section/1/enacted/en/html",
    ),
    ("IE-2006-act-33", "Electoral Act 1992 (23/1992), s. 7"): (
        'Terms "presidential elector" and "elector" construed',
        "These are earlier definitions for the Presidential Elections and Referendum Acts. "
        "Sections 20(4) and 20(6) of the 2006 Act join those collective citations.",
        "https://www.irishstatutebook.ie/eli/2006/act/33/section/20/enacted/en/html",
    ),
    ("IE-2006-act-33", "Age of Majority Act 1985 (2/1985), s. 4"): (
        "Time at which person attains a particular age",
        "This is an earlier general rule for calculating age under statutory provisions, "
        "including its electoral exceptions, not a later amendment of the 2006 Act.",
        "https://www.irishstatutebook.ie/eli/1985/act/2/section/4/enacted/en/html",
    ),
    (
        "IE-2014-act-4",
        "Local Government Reform Act 2014 (No. 1 of 2014), ss. 1(22), 9(2),(3), 25(2)",
    ): (
        "References construed",
        "These are previously enacted general construction rules for local authorities "
        "and their functions in other enactments. Their later commencement is retained "
        "as reported by the directory; it is not a new enactment amending this Act.",
        "https://www.irishstatutebook.ie/eli/2014/act/1/enacted/en/html",
    ),
    ("IE-2018-act-11", "Data Protection Act 2018 (7/2018), ss. 1(3), 166"): (
        "S. 24 references to processing construed",
        "Section 166 is an earlier general construction rule for references to processing "
        "in any enactment, not a later amendment of the Childcare Support Act 2018.",
        "https://www.irishstatutebook.ie/eli/2018/act/7/section/166/enacted/en/html",
    ),
    ("IE-2005-act-26", "S.I. No. 188 of 1998, sch. A"): (
        "S. 250 applied with modifications **",
        "Schedule A originally applies section 212 of the 1993 Act, re-enacted as "
        "section 250 of the 2005 Act. Sections 361(b) and 362(2) preserve the references "
        "and instruments. The directory's separate S.I. 600/2011 amendment is retained.",
        "https://www.irishstatutebook.ie/eli/2005/act/26/section/361/enacted/en/html",
    ),
    ("IE-2018-act-11", "Data Protection Act 2018 (7/2018), ss. 9, 14(2), (4)"): (
        "S. 24 references to Data Protection Commissioner construed",
        "Section 14(2) is an earlier general rule: from the establishment day a reference "
        "in any enactment to the Data Protection Commissioner is construed as one to the "
        "Commission. The Childcare Support Act 2018 names the Commissioner; this is not a "
        "later amendment of it.",
        "https://www.irishstatutebook.ie/eli/2018/act/7/section/14/enacted/en/html",
    ),
    ("IE-1999-si-189", "32/1998, s. 4(4), (5)"): (
        "Rendered spent by expiry of enabling Act",
        "Section 4(4) ends the 1998 Act 12 months after its passing and section 4(5) allows "
        "one continuance of at most 12 months, which this order makes. The order is spent "
        "when that period ends: an earlier limit, not a later amendment.",
        "https://www.irishstatutebook.ie/eli/1998/act/32/section/4/enacted/en/html",
    ),
    ("IE-2002-si-355", "Mental Health Act 2001 (25/2001), ss. 1(3), 6, schedule"): (
        "Rendered obsolete by repeal of enabling provision",
        "The order was made under sections 162, 165 and 166 of the Mental Treatment Act "
        "1945 (Part XIV). Section 6 and the Schedule of the 2001 Act repeal the 1945 Act "
        "other than Part VIII and four sections, from a day fixed under section 1(3). The "
        "directory states no date, so none is assigned; this is not a 2001 amendment.",
        "https://www.irishstatutebook.ie/eli/2001/act/25/section/6/enacted/en/html",
    ),
    ("IE-2005-si-512", "11/2005, ss. 1(1), 47(3)"): (
        "Continued in force",
        "Section 47(3) continues regulations made under sections 18, 19, 20 and 27 of the "
        "1992 Act before its commencement. This instrument was made later, under section 27 "
        "as inserted by section 47(2); the 2005 provision is earlier, not an amendment of it.",
        "https://www.irishstatutebook.ie/eli/2005/act/11/section/47/enacted/en/html",
    ),
}

# Official instruments whose own text cannot date them. The owner decided to publish
# the affected Acts without these events rather than guess a date. Each entry is
# tied to the exact bytes eISB serves (None: an HTTP 404), so a corrected source
# stops matching and the Act fails loudly until someone re-verifies it.
_UNDATABLE_SOURCES = {
    ("IE-1950-act-12", "IE-1992-si-121"): (
        "ac330018c4282b76cf9c25eb243948fa787d6a788c27b8186612e9d6ab70c17f",  # pragma: allowlist secret
        "The official signature prints 20 May 1922, before the Act it amends; "
        "no independent source gives the correct date.",
    ),
    ("IE-1992-act-9", "IE-1993-si-60"): (
        "d34e7ce42314dbe747f3ed641f501a353e3994a48982edd75e5910dbc7cdb273",  # pragma: allowlist secret
        "The official signature prints 2 March 1992, before its enabling Act; "
        "no independent source gives the correct date.",
    ),
    ("IE-1969-act-21", "IE-1975-si-127"): (
        "ddd9f82f5bb1ca05050d47f676745879ca0c0b1a0b76091fc77857a253a35ab3",  # pragma: allowlist secret
        "The official text has no signature date.",
    ),
    ("IE-1937-act-38", "IE-1988-si-257"): (
        "c66c98348aa78e74f4bc52917744d61f145ff5a6ed8ec157c5346ad34e2c0e8b",  # pragma: allowlist secret
        "The official signature reads '29th day of 1988'; the month is absent.",
    ),
    ("IE-1981-act-1", "IE-1985-si-101"): (
        "0f634cb40aad52b1efc08c2ce0a5bb7b068764958fa84c122e7d06ab4517b062",  # pragma: allowlist secret
        "The official text is truncated after regulation 11 and has no signature.",
    ),
    ("IE-1963-act-33", "IE-1984-si-201"): (
        None,
        "The official URL returns 404 and the 1984 annual index has no such instrument; "
        "the directory citation may be erroneous.",
    ),
    ("IE-1963-act-33", "IE-1985-si-226"): (
        None,
        "The official URL returns 404 and the 1985 annual index skips from 225 to 227; "
        "the directory itself refers to S.I. No. 241 of 1984.",
    ),
    ("IE-1994-act-8", "IE-1998-si-340"): (
        "2f9405b4ae984cba49d94055c7515c09bf67a2914cdde2ee2f3359020546ba74",  # pragma: allowlist secret
        "The official text is truncated within its electoral-area table and has no signature.",
    ),
    # Instruments cited by statutory instruments, verified on 2026-10-19 from the cache.
    ("IE-2001-si-510", "IE-2026-si-156"): (
        "7a7e573626cccf7188297866abf777d504e76fd5d78bee1774eae9e33e9a9ccd",  # pragma: allowlist secret
        "eISB serves S.I. No. 155/2026 at the URL of S.I. No. 156/2026.",
    ),
    ("IE-2007-si-142", "IE-2026-si-397"): (
        "c3895d0b9250f512634ffaa16609b3fa3a9b3dc64cced5f7a142b3e51b491ba4",  # pragma: allowlist secret
        "eISB serves S.I. No. 377/2026 at the URL of S.I. No. 397/2026.",
    ),
    ("IE-1972-si-220", "IE-1975-si-127"): (
        "ddd9f82f5bb1ca05050d47f676745879ca0c0b1a0b76091fc77857a253a35ab3",  # pragma: allowlist secret
        "The official text has no signature date.",
    ),
    ("IE-1992-si-19", "IE-1993-si-206"): (
        "157c7eb358ae04b1cf46fb71bb0756a9c8d2190b14a630d4fd56e03cf6a217f3",  # pragma: allowlist secret
        "The official signature leaves the day blank: 'this day of June, 1993'.",
    ),
    ("IE-1994-si-417", "IE-1996-si-172"): (
        "6cb8856a2998b13b27113aa81d098c6ada36c1d1ff3b6e5295030e6a4fc94c96",  # pragma: allowlist secret
        "Both official signatures leave the day blank: 'this day of May, 1996'.",
    ),
    ("IE-2002-si-203", "IE-2002-si-225"): (
        "7374a034e84d85cecafec403f8831ec9868c770150b35d2711afa4f29b716936",  # pragma: allowlist secret
        "The official signature leaves the day blank: 'this day of March, 2002'.",
    ),
    ("IE-2000-si-109", "IE-2004-si-575"): (
        "2a786bb2ff115353c5e683e91ac29b4e0919134eaeff5f1e2c21222e78623515",  # pragma: allowlist secret
        "The official signature omits the year: 'this 29th day of September'.",
    ),
    ("IE-2011-si-560", "IE-2016-si-479"): (
        "13fbc342e21134b10626a69cba8149c472eca99e95dd80b51bd8c686d232f585",  # pragma: allowlist secret
        "The official text has no signature date.",
    ),
    ("IE-1976-si-115", "IE-2000-act-43"): (
        None,
        "The directory cites 43/2000, but the 2000 annual index ends at Act No. 42 and the official URL returns 404; the citation may be erroneous.",
    ),
    ("IE-1984-si-57", "IE-2000-act-43"): (
        None,
        "The directory cites 43/2000, but the 2000 annual index ends at Act No. 42 and the official URL returns 404; the citation may be erroneous.",
    ),
    ("IE-1994-si-360", "IE-2000-act-43"): (
        None,
        "The directory cites 43/2000, but the 2000 annual index ends at Act No. 42 and the official URL returns 404; the citation may be erroneous.",
    ),
    ("IE-2003-si-5", "IE-2016-act-23"): (
        None,
        "The directory cites 23/2016, but the 2016 annual index ends at Act No. 22 and the official URL returns 404; the citation may be erroneous.",
    ),
    ("IE-1996-si-179", "IE-2011-si-827"): (
        None,
        "The directory cites S.I. No. 827 of 2011, but the 2011 annual index ends at S.I. No. 741 and the official URL returns 404; the citation may be erroneous.",
    ),
    ("IE-2001-si-600", "IE-2026-si-72"): (
        None,
        "The directory cites S.I. No. 72 of 2026, but the 2026 annual index skips No. 72 and the official URL returns 404.",
    ),
}


# Directory rows whose citing cell names no instrument to date them by, verified on
# 2026-10-19 row by row: a judgment, a Dáil debate, a misprinted citation, a fragment of
# a parenthesis split across rows, or an empty cell. Each is kept as printed, as an
# editorial note, and never committed; any other such row still fails the norm.
_UNATTRIBUTED_ROWS = {
    "IE-1983-si-190": {"Sch., rls. 1, 2 amended", "Sch., rl. 2 amended"},
    "IE-1994-si-395": {"Expired"},
    "IE-1997-si-496": {"Part II application restricted"},
    "IE-1997-si-93": {
        "Sch. B, forms 34.37, 34.38 substituted",
        "Sch. C, forms 40F.01, 40F.02, 40F.03 & 40F.04 inserted",
    },
    "IE-2015-si-209": {"N/A"},
    "IE-2004-si-703": {"See"},
    "IE-2013-si-135": {")"},
    "IE-2013-si-323": {
        "S.I. No. 539 of 2012, regs. 1(b), 3 and sch. as amended by regs. 1(c), 3, 4"
    },
    "IE-2018-si-355": {
        "Sweetman v Minister for Culture, Heritage and the Gaeltacht and others, "
        "Meenan J., 5 Dec 2019, Case No. 2018 1009 JR"
    },
    "IE-2018-si-89": {"Dáil Éireann debate -Tuesday, 29 May 2018Vol. 969 No. 7"},
    "IE-2019-si-4": {
        "Friends of the Irish Environment Limited v. Minister for Communications, Climate "
        "Act and Environment and Others [2019] IEHC 646 para. 221 and [2019] IEHC 685 para. 11."
    },
    "IE-2020-si-354": {"S.I. No. 413 of 202, regs. 1(2), 3"},
}


def _check_undatable(client: ISBClient, source_id: str, digest: str | None) -> None:
    """Fail unless eISB still serves exactly the defect that was verified."""
    import requests

    try:
        data = client.get_metadata(source_id)
    except requests.HTTPError as exc:
        if digest is None and exc.response is not None and exc.response.status_code == 404:
            return
        raise
    if sha256(data).hexdigest() != digest:
        raise ValueError(f"{source_id}: official source changed since it was found undatable")


# Exact misfiled claims and host citations; see context-citations-evidence.json.
_DIRECTORY_CONTEXT = {
    (
        "IE-1991-act-29",
        "IE-1988-si-286",
        "S. 5 form prescribed",
        "S.I. No. 286 of 1988, reg. 4(1)",
    ): (
        "directory_citation_error",
        "Regulation 4(1) prescribes a certificate under the Local Government "
        "(Multi-Storey Buildings) Act 1988 (29/1988), not the B&I Line Act 1991. "
        "The directory files this claim under the wrong Act.",
        "https://www.irishstatutebook.ie/eli/1988/si/286/made/en/html",
    ),
    (
        "IE-1992-act-29",
        "IE-1988-si-286",
        "S. 4(1) application modified",
        "S.I. No. 286 of 1988, reg. 5",
    ): (
        "directory_citation_error",
        "Regulation 5 concerns a certificate under the Local Government "
        "(Multi-Storey Buildings) Act 1988 (29/1988), not the Censorship of Films "
        "(Amendment) Act 1992. The directory files this claim under the wrong Act.",
        "https://www.irishstatutebook.ie/eli/1988/si/286/made/en/html",
    ),
    (
        "IE-1996-act-21",
        "IE-1974-si-132",
        "S. 26(1)(b) applied with modifications",
        "S.I. No. 132 of 1974, reg. 2",
    ): (
        "directory_citation_error",
        "Regulation 2 explicitly concerns section 26(1)(b) of the Housing Act "
        "1966 (21/1966), not the An Bord Bia (Amendment) Act 1996. "
        "The directory files this claim under the wrong Act.",
        "https://www.irishstatutebook.ie/eli/1974/si/132/made/en/html",
    ),
    (
        "IE-1981-act-16",
        "IE-1975-si-307",
        "S.37 (1), cesser. of applic. of.",
        "S. I. No. 307 of 1975, par. 9 (2)",
    ): (
        "host_provision",
        "The 1975 Order is the host of paragraph 9(2), inserted by section 37(1) "
        "of the Finance Act 1981. The cessation comes from section 152(1) of the "
        "Finance Act 1992, retained as a separate directory effect.",
        "https://www.irishstatutebook.ie/eli/1992/act/9/section/152/enacted/en/html",
    ),
    (
        "IE-1996-si-292",
        "IE-1970-act-1",
        "Continued in force under Health Act 1970 (1/1970)",
        "Health Act 1970 (1/1970), s. 72(3)",
    ): (
        "directory_citation_error",
        "Section 72(3) continues regulations made under the Health Act 1953. This order "
        "was made in 1996 under sections 162, 165, 166 and 184 of the Mental Treatment Act "
        "1945; the 1970 provision predates it and does not concern it.",
        "https://www.irishstatutebook.ie/eli/1996/si/292/made/en/html",
    ),
}

# Order-series numbers differ from S.I. numbers; verified against the annual eISB indexes.
_DUTY_ORDERS = {
    ("E.I.D.", "117", "1937"): "IE-1937-si-3",
    ("E.I.D.", "217", "1941"): "IE-1941-si-136",
    ("E.I.D.", "223", "1941"): "IE-1941-si-464",
    ("E.I.D.", "267", "1951"): "IE-1951-si-357",
    ("E.I.D.", "273", "1952"): "IE-1952-si-71",
    ("E.I.D.", "347", "1955"): "IE-1955-si-66",
    ("E.I.D.", "357", "1955"): "IE-1955-si-173",
    ("E.I.D.", "359", "1955"): "IE-1955-si-194",
    ("E.I.D.", "397", "1957"): "IE-1957-si-77",
    ("I.D.", "14", "1958"): "IE-1958-si-30",
    ("I.D.", "19", "1958"): "IE-1958-si-39",
    ("I.D.", "128", "1962"): "IE-1962-si-163",
}

# These Companies directory dates belong to the host provisions, not their later amendments.
_COMPANIES_COMMENCEMENTS = {
    ("IE-2024-act-11", "3 June 2014"): (
        "1 June 2024",
        "https://www.irishstatutebook.ie/eli/2024/si/208/made/en/html",
        ("ss. 1(2), 20(b)",),
    ),
    ("IE-2022-act-39", "29 March 2013"): (
        "1 January 2023",
        "https://www.irishstatutebook.ie/eli/2022/si/678/made/en/html",
        ("s. 10(c)", "ss. 1(3), 15", "ss. 1(3), 9(b)"),
    ),
    ("IE-2019-act-2", "8 November 1983"): (
        "30 September 2019",
        "https://www.irishstatutebook.ie/eli/2019/si/439/made/en/html",
        ("ss. 6, 17(2)",),
    ),
    ("IE-2017-act-41", "1 November 2001"): (
        "25 December 2017",
        "https://www.irishstatutebook.ie/isbc/2017_41.html#commencement",
        ("s. 66(b)", "s. 66(c)", "s. 67(c)"),
    ),
}


# Exact directory citations verified against the actual affecting provisions.
# Evidence: tests/fixtures/ie/{later-insertion,verified-year,later-host,pension-host}-evidence.json.
_VERIFIED_EFFECT_SOURCES = {
    ("IE-1997-act-26", "6/1993, s. 5", "IE-1993-act-6"): (
        "2010/act/27/section/4",
        None,
        None,
    ),
    ("IE-1997-act-26", "23/1992, s. 15E(2)(b)", "IE-1992-act-23"): (
        "2022/act/30/section/93",
        None,
        None,
    ),
    ("IE-1997-act-26", "25/1968, s. 18A and sch. 2", "IE-1968-act-25"): (
        "2023/act/16/section/6",
        None,
        None,
    ),
    (
        "IE-2000-act-30",
        "S,I, No. 419 of 1993, sch. C. See also S.I. Nos. 135 of 2013, 268 of 2014, 39 of 2019",
        "IE-1993-si-419",
    ): (
        "2008/si/295",
        "1 August 2008",
        "2008/si/295",
    ),
    ("IE-2002-act-14", "S.I. No. 419 of 1993, reg. 6 and sch. C", "IE-1993-si-419"): (
        "2008/si/295",
        "1 August 2008",
        "2008/si/295",
    ),
    ("IE-1993-act-8", "28/1971, s. 17 and sch.", "IE-1971-act-28"): (
        "2022/act/31/section/130",
        None,
        None,
    ),
    ("IE-2005-act-26", "S.I. No. 188 of 1998, sch. B", "IE-1998-si-188"): (
        "2012/si/448",
        None,
        None,
    ),
    ("IE-1996-act-32", "S.I. No. 319 of 1996. art. 12(5)", "IE-1996-si-319"): (
        "1998/si/319",
        None,
        None,
    ),
    ("IE-1993-act-27", "7/1993, s.22 (11) (c) (13)", "IE-1993-act-7"): (
        "1996/act/7/section/22",
        None,
        None,
    ),
    ("IE-2000-act-34", "S.I. No. 414 of 2000, reg. 5", "IE-2000-si-414"): (
        "2002/si/414",
        "",  # The directory commencement belongs to an unrelated beef assurance order.
        None,
    ),
    ("IE-1989-act-6", "7/1964, s 20(4)", "IE-1964-act-7"): (
        "1997/act/40/section/11",
        None,
        None,
    ),
    ("IE-1958-act-4", "23/1935, s.1 (2) (b)", "IE-1935-act-23"): (
        "1965/act/23/section/1",
        None,
        None,
    ),
    ("IE-1977-act-12", "12/1950, s. 22A(1)(f)", "IE-1950-act-12"): (
        "2005/act/31/section/129",
        None,
        None,
    ),
    ("IE-1995-act-9", "25/1990, s. 101(6)(a) *", "IE-1990-act-25"): (
        "2002/act/18/section/3",
        "7 November 2002",
        "2002/si/502",
    ),
    ("IE-1995-act-11", "25/1990, s. 101(5)(a)", "IE-1990-act-25"): (
        "2002/act/18/section/3",
        "7 November 2002",
        "2002/si/502",
    ),
    ("IE-1995-act-11", "25/1990, s. 101(5)(b)", "IE-1990-act-25"): (
        "2002/act/18/section/3",
        "7 November 2002",
        "2002/si/502",
    ),
    ("IE-1995-act-11", "25/1990, s. 101(5)(c)", "IE-1990-act-25"): (
        "2002/act/18/section/3",
        "7 November 2002",
        "2002/si/502",
    ),
    ("IE-1997-act-39", "27/1988, s. 44A", "IE-1988-act-27"): (
        "2012/act/44/section/150",
        None,
        None,
    ),
    (
        "IE-2012-act-9",
        "Taxes Consolidation Act 1997 (39/1997), s. 959AF(4) (as inserted by the Finance Act 2017, s. 75, schedule 3(l))",
        "IE-1997-act-39",
    ): (
        "2017/act/41/schedule/3",
        None,
        None,
    ),
    (
        "IE-2013-act-18",
        "Courts (Supplemental Provisions) Act 1961 (No. 39 of 1961), s. 46(9A)(h) (see also Financial Emergency Measures in the Public Interest Act 2015 (No. 39 of 2015), ss. 1(2), 11(1)(c))",
        "IE-1961-act-39",
    ): (
        "2015/act/39/section/11",
        "1 January 2017",
        "2016/si/406",
    ),
    (
        "IE-2002-act-9",
        "37/2001, ss. 131, 131A, sch. 14A pt. 3 (see also 1/2014, ss. 1(22), 21(4), sch. 3)",
        "IE-2001-act-37",
    ): (
        "2014/act/1/section/21",
        "1 June 2014",
        "2014/si/214",
    ),
    (
        "IE-2003-act-15",
        "37/2001, s. 131A(1)(a),(4), sch. 14A pt. 1 (see also 1/2014, ss. 1(22), 21(3),(4), sch. 3)",
        "IE-2001-act-37",
    ): (
        "2014/act/1/section/21",
        "1 June 2014",
        "2014/si/214",
    ),
    # Section 2A(2)(a) of the 1930 Act names both orders; section 3 of 22/2004 inserted it.
    ("IE-2002-si-302", "2/1930, s. 2A(2)(a)(i)-(ii).", "IE-1930-act-2"): (
        "2004/act/22/section/3",
        None,
        None,
    ),
    ("IE-2002-si-358", "2/1930, s. 2A(2)(a)(i)-(ii).", "IE-1930-act-2"): (
        "2004/act/22/section/3",
        None,
        None,
    ),
}


def norm_id_from_url(url: str) -> str | None:
    """Resolve ELI and legacy citations without merging Act namespaces."""
    path = urlparse(url).path
    if re.search(r"/eli/cons(?:/|$)", path):
        return CONSTITUTION_ID
    match = re.search(r"(?:^|/)(\d{4})/(?:en|ga)/act/(pub|prv|cam)/(\d+)", path)
    if match:
        year, kind, number = match.groups()
        return (
            f"IE-{year}-act-{'P' if kind == 'prv' else 'C' if kind == 'cam' else ''}{int(number)}"
        )
    match = re.search(r"(?:^|/)(\d{4})/(?:en|ga)/si/(\d+)", path)
    if match:
        return f"IE-{match[1]}-si-{int(match[2])}"
    match = re.search(r"/eli/(\d{4})/(act|prv|ca|si)/(\d+)(?:/|$)", path)
    if match:
        year, kind, number = match.groups()
        if kind == "si":
            return f"IE-{year}-si-{int(number)}"
        return f"IE-{year}-act-{'P' if kind == 'prv' else 'C' if kind == 'ca' else ''}{int(number)}"
    return None


def source_date(text: str) -> date | None:
    """Read a stated English date, without substituting one for missing dates."""
    months = {
        name: n
        for n, name in enumerate(
            ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
        )
    }
    match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)[,.]?\s+(\d{4})\b", text)
    if not match or match[2][:3].lower() not in months:
        return None
    try:
        return date(int(match[3]), months[match[2][:3].lower()], int(match[1]))
    except ValueError:
        return None


def _text(node) -> str:
    return " ".join(node.text_content().split())


def _effect(note: str, provision: str, source_id: str, commencement="", commencement_source=""):
    effective = source_date(commencement)
    repeal = bool(re.search(r"\b(?:repealed|revoked|rep\.|rev\.)", note, re.I))
    whole = bool(re.match(r"^\*?\s*(?:Act\s+)?(?:repealed|revoked|rep\.|rev\.)", note, re.I))
    whole = whole and not re.search(r"\b(?:part|except|insofar)\b|in so far", note, re.I)
    return {
        "source_id": source_id,
        "note": note,
        "provision": provision,
        "commencement": commencement,
        "commencement_source": commencement_source,
        "effective_date": effective.isoformat() if effective else None,
        "pending": bool(
            re.search(r"not (?:yet )?commenced", commencement + " " + commencement_source, re.I)
        ),
        "whole_repeal": bool(whole),
        "partial_repeal": repeal and not whole,
    }


def _affecting_ids(cell, provision: str, norm_id: str, note: str) -> tuple[set[str], str | None]:
    # A provision inserted into an older Act derives from the named amending instrument.
    amenders = list(
        re.finditer(
            r"\b(?:as\s+)?(?:inserted|substituted|amended|ins\.|subst\.)"
            r"(?:\s*\(\d{1,2}\.\d{1,2}\.\d{4}\))?"
            r"(?:\s+by\s*|\s+(?=\d+\s*/\s*\d{4}\b))"
            r"(?!\s*(?:Directive\b|Regulation\s*\((?:EU|EC|EEC)\)))",
            cell.text_content(),
            re.I,
        )
    )
    if amenders:
        cell = deepcopy(cell)
        offset = amenders[-1].end()
        provision = " ".join(cell.text_content()[offset:].split())
        links = [
            link
            for link in cell.xpath(".//a[@href]")
            if len("".join(link.xpath("preceding::text()"))) >= offset
        ]
    else:
        links = cell.xpath(".//a[@href]")
    identifiers = {
        identifier for link in links if (identifier := norm_id_from_url(link.get("href")))
    }
    # Some directory links incorrectly use act/pub for explicitly labelled instruments.
    instruments = re.findall(
        # "S.I .No. 494 of 2004" and "S.l. No. 90 of 2013" are directory misprints of S.I.
        # "S.I. No. 157 of2004" drops the space.
        r"S[.,]?\s*[Il][.,]?\s*[.,]?\s*(?:Nol?\.?\s*)?(\d+),?\s*(?:(?:of\s*){1,2}|/)(\d{4})",
        provision,
        re.I,
    )
    for series in re.findall(
        r"S[.,]?\s*I[.,]?\s*Nos\.?\s*(\d+\s+of\s+\d{4}"
        r"(?:(?:\s*,\s*|\s+and\s+)\d+\s+of\s+\d{4})*)",
        provision,
        re.I,
    ):
        instruments.extend(re.findall(r"(\d+)\s+of\s+(\d{4})", series, re.I))
    instruments += re.findall(r"E\.I\.D\. \(No\. S\.\s*I\. (\d+)\) O\., (\d{4})", provision)
    for number, year in instruments:
        identifiers.discard(f"IE-{year}-act-{int(number)}")
        identifiers.add(f"IE-{year}-si-{int(number)}")
    for citation in re.findall(r"\b((?:E\.)?I\.D\.) \(No\. (\d+)\),? O\., (\d{4})", provision):
        if citation not in _DUTY_ORDERS:
            raise ValueError(f"{norm_id}: unresolved duties order: {citation}")
        identifiers.add(_DUTY_ORDERS[citation])
    if "Constitution of Ireland 1937" in provision:
        identifiers.add(CONSTITUTION_ID)
    # Explicit amender citations can disagree with links copied from the host Act.
    amending_citations = (
        {
            f"IE-{year}-act-{int(number)}"
            for number, year in re.findall(r"\b(\d+)\s*/\s*(\d{4})\b", provision)
        }
        if amenders and not instruments
        else set()
    )
    if amending_citations:
        identifiers = {
            linked
            for citation in amending_citations
            for linked in (
                {
                    identifier
                    for identifier in identifiers
                    if identifier.replace("-act-P", "-act-").replace("-act-C", "-act-") == citation
                }
                or {citation}
            )
        }
    if not identifiers:
        for number, year in re.findall(r"\b(\d+)\s*/\s*(\d{4})\b", provision):
            identifiers.add(f"IE-{year}-act-{int(number)}")
        if match := re.search(r"\b(\d+) of (\d{4})(?=[,) ]|$)", provision):
            identifiers.add(f"IE-{match[2]}-act-{int(match[1])}")
    correction = None
    if (
        norm_id == "IE-1923-act-15"
        and note == "S. 13 application restricted"
        and provision == "42/1942, s. 2"
    ):
        identifiers = {"IE-1924-act-42"}
        correction = "https://www.irishstatutebook.ie/eli/1924/act/42/section/2/enacted/en/html"
    if norm_id == "IE-2005-act-11" and re.fullmatch(
        r"Harbours Act 2015 \(61/2005\), s\. 1\([234]\)", provision
    ):
        identifiers = {"IE-2015-act-61"}
        correction = "https://www.irishstatutebook.ie/eli/2015/act/61/section/1/enacted/en/html"
    if (
        norm_id == "IE-1990-act-27"
        and note == "S. 2(5) inserted"
        and provision == "3434/2009, ss. 1(2), 1(3), 234, schedule 3, pt. 4, item 1"
    ):
        identifiers = {"IE-2009-act-34"}
        correction = "https://www.irishstatutebook.ie/eli/2009/act/34/schedule/3/enacted/en/html"
    if (
        norm_id == "IE-2006-act-16"
        and provision == "Employment Permits (Amendment) Act 2014 (26/2016), s. 1(2)"
    ):
        identifiers = {"IE-2014-act-26"}
        correction = "https://www.irishstatutebook.ie/eli/2014/act/26/section/1/enacted/en/html"
    if norm_id == "IE-2015-act-9" and provision == "Adoption (Amendment) Act 2017, s. 2(2)":
        identifiers = {"IE-2017-act-19"}
        correction = "https://www.irishstatutebook.ie/eli/2017/act/19/section/2/enacted/en/html"
    if norm_id == "IE-2010-act-25" and provision.startswith("Road Traffic (No. 2) Act 2011 (v),"):
        identifiers = {"IE-2011-act-28"}
        correction = "https://www.irishstatutebook.ie/eli/2011/act/28/section/9/enacted/en/html"
    if provision == "Financial Services and Pensions Ombudsman Act 2017, s. 29(2)":
        identifiers = {"IE-2017-act-22"}
        correction = "https://www.irishstatutebook.ie/eli/2017/act/22/section/29/enacted/en/html"
    if norm_id == "IE-2006-act-26" and provision.startswith(
        "Criminal Justice (Suspended Sentences of Imprisonment) Act 2017 (4/2014),"
    ):
        identifiers = {"IE-2017-act-4"}
        correction = "https://www.irishstatutebook.ie/eli/2017/act/4/section/3/enacted/en/html"
    if (
        norm_id == "IE-1983-act-24"
        and note == "Ss. 103, 104, 109, power to delegate functns. of Min."
        and not provision
    ):
        identifiers.add("IE-1990-act-18")
        correction = "https://www.irishstatutebook.ie/eli/1990/act/18/schedule/1/enacted/en/html"
    if norm_id == "IE-1983-act-35" and note == "Repealed with saver for regs." and not provision:
        identifiers.add("IE-2008-act-1")
        correction = "https://www.irishstatutebook.ie/eli/2008/act/1/section/11/enacted/en/html"
    if norm_id == "IE-2001-act-43" and note == "S. 8 repealed" and not provision:
        identifiers.add("IE-2022-act-50")
        correction = "https://www.irishstatutebook.ie/eli/2022/act/50/schedule/2/enacted/en/html"
    if norm_id == "IE-2003-act-32" and provision == "49/21, ss. 2, 20(2)":
        identifiers.add("IE-2021-act-49")
        correction = "https://www.irishstatutebook.ie/eli/2021/act/49/section/20/enacted/en/html"
    if (
        norm_id == "IE-1998-act-16"
        and provision
        == "Financial Emergency Measures in the Public Interest Act 2009 (5.2009), s. 17(a)"
    ):
        identifiers.add("IE-2009-act-5")
        correction = "https://www.irishstatutebook.ie/eli/2009/act/5/section/17/enacted/en/html"
    if re.fullmatch(
        r"Housing \(Miscellaneous Provisions\) Act 2014, s\. 19\((?:9|10)\)", provision
    ):
        identifiers = {"IE-2014-act-21"}
        correction = "https://www.irishstatutebook.ie/eli/2014/act/21/section/19/enacted/en/html"
    if norm_id == "IE-1990-act-20" and note == "S. 3(5A) inserted" and not provision:
        identifiers.add("IE-2005-act-11")
        correction = "https://www.irishstatutebook.ie/eli/2005/act/11/section/57/enacted/en/html"
    if norm_id == "IE-1979-act-27" and provision == "3/199, s. 76":
        identifiers.add("IE-1998-act-3")
        correction = "https://www.irishstatutebook.ie/eli/1998/act/3/section/76/enacted/en/html"
    if norm_id == "IE-1967-act-21" and note == "Sch., para. 5(c)(ii) substituted" and not provision:
        identifiers.add("IE-2023-act-8")
        correction = "https://www.irishstatutebook.ie/eli/2023/act/8/section/32/enacted/en/html"
    if norm_id == "IE-1942-act-22" and provision == "20/13, ss. 1(5), 26":
        identifiers.add("IE-2013-act-20")
        correction = "https://www.irishstatutebook.ie/eli/2013/act/20/section/26/enacted/en/html"
    if norm_id == "IE-1936-act-45" and note == "S.3 rep. (in pt.)." and not provision:
        identifiers.add("IE-1989-act-3")
        correction = "https://www.irishstatutebook.ie/eli/1989/act/3/schedule/1/enacted/en/html"
    if (
        norm_id == "IE-1923-act-15"
        and not provision
        and note
        == "Compensation under collectively cited Damage to Property (Compensation) "
        "Acts 1923 to 1933 may be made by payment of money"
    ):
        identifiers.add("IE-1937-act-18")
        correction = "https://www.irishstatutebook.ie/eli/1937/act/18/section/17/enacted/en/html"
    if (
        norm_id == "IE-1997-act-39"
        and note == "S. 270(4) inserted"
        and provision == "2006, ss. 26(1)(a), 26(2)"
    ):
        # The cited section itself verifies the missing Act number; retain the original citation.
        identifiers.add("IE-2006-act-6")
        correction = "https://www.irishstatutebook.ie/eli/2006/act/6/section/26/enacted/en/html"
    if (
        norm_id == "IE-1997-act-39"
        and not provision
        and re.fullmatch(r"Sch\. 13, para\. (?:92|111|128|180) deleted", note)
    ):
        identifiers.add("IE-2024-act-43")
        correction = "https://www.irishstatutebook.ie/eli/2024/act/43/section/22/enacted/en/html"
    if norm_id == "IE-1997-act-39" and note == provision == "Sch. 15, pt. 1, par. 45 inserted":
        identifiers.add("IE-2018-act-30")
        correction = "https://www.irishstatutebook.ie/eli/2018/act/30/section/60/enacted/en/html"
    if (
        norm_id == "IE-1925-act-P3"
        and note
        == 'S. 110, certain references to "sanitary authority" construed as references to "Irish Water"'
        and not provision
    ):
        identifiers.add("IE-2013-act-50")
        correction = "https://www.irishstatutebook.ie/eli/2013/act/50/section/7/enacted/en/html"
    return identifiers, correction


def _effect_cells(doc, norm_id: str) -> list[list] | None:
    """Effects rows; None when an annual directory page omits this instrument."""
    headings = doc.xpath('//*[@id="effects"]')
    if headings:
        tables = headings[0].xpath("following-sibling::table[1]")
        if not tables:
            raise ValueError(f"{norm_id}: Legislation Directory has no effects table")
        return [row.xpath("./td") for row in tables[0].xpath("./tbody/tr | ./tr")]
    year, kind, number = _parse_norm_id(norm_id)
    if kind not in ("prv", "si"):
        raise ValueError(f"{norm_id}: Legislation Directory has no effects section")
    anchor = f"a{number}_{year}"
    target = doc.xpath("//*[@id=$anchor or @name=$anchor]", anchor=anchor)
    if not target:
        # Early annual pages list only some instruments, and later ones skip a few
        # (1996 goes from 127 to 129). Only a page that lists that year's other
        # instruments shows the omission; anything else is still an error.
        if kind == "si" and any(
            re.fullmatch(rf"a\d+_{year}", node.get("id") or node.get("name") or "")
            for node in doc.xpath("//a[@id or @name]")
        ):
            return None
        # A year's index that links no range page covering this instrument (1941 skips
        # 101-150; 1942 stops at 451-469): the directory has no page for it at all.
        if kind == "si" and any(
            re.search(rf"si{year}_\d+-\d+\.html", href) for href in doc.xpath("//a/@href")
        ):
            return None
        raise ValueError(f"{norm_id}: annual Legislation Directory has no matching norm")
    start = target[0].xpath("ancestor::tr[1]")[0]
    first = start.xpath("./td")
    if len(first) != 4:
        raise ValueError(f"{norm_id}: unexpected annual directory columns")
    count = int(first[0].get("rowspan", "1"))
    rows = [first[2:]]
    siblings = start.xpath("following-sibling::tr")
    if len(siblings) < count - 1:
        raise ValueError(f"{norm_id}: truncated annual directory group")
    rows.extend(row.xpath("./td") for row in siblings[: count - 1])
    if first[0].get("rowspan") is None:
        # Some pages write a group without rowspan: its further rows leave the number
        # and title cells empty ("Art. 4 revoked" under S.I. 30/2001).
        for row in siblings:
            cells = row.xpath("./td")
            if len(cells) != 4 or any(_text(cell) for cell in cells[:2]) or cells[0].xpath(".//a"):
                break
            rows.append(cells[2:])
    return rows


def _annual_footnotes(doc, norm_id: str) -> list[tuple[str, str, set[str]]]:
    """(stars, text, cited instruments) of the "*See …" rows after an SI's annual group."""
    year, kind, number = _parse_norm_id(norm_id)
    target = doc.xpath("//*[@id=$anchor or @name=$anchor]", anchor=f"a{number}_{year}")
    if kind != "si" or not target:
        return []
    start = target[0].xpath("ancestor::tr[1]")[0]
    count = int(start.xpath("./td")[0].get("rowspan", "1"))
    footnotes = []
    for row in start.xpath("following-sibling::tr")[count - 1 :]:
        cells = row.xpath("./td")
        if len(cells) == 4 and not _text(cells[0]) and not cells[0].xpath(".//a[@id or @name]"):
            continue  # a continuation row of the same group, written without rowspan
        if len(cells) != 1:
            break
        if not (text := _text(cells[0])):
            continue  # the <hr> separator rows
        if not text.startswith("*"):
            break
        # One cell can hold several notes: "*See also 24/2004, s. 38 **See also …".
        cell = deepcopy(cells[0])
        content = cell.text_content()
        starts = [match.start() for match in re.finditer(r"\*+(?=\s*See\b)", content)]
        if not starts:
            continue  # a starred note that cites nothing, e.g. a court judgment
        for begin, end in zip(starts, starts[1:] + [len(content)], strict=True):
            links = [
                identifier
                for link in cell.xpath(".//a[@href]")
                if begin <= len("".join(link.xpath("preceding::text()"))) < end
                and (identifier := norm_id_from_url(link.get("href")))
            ]
            segment = " ".join(content[begin:end].split())
            if not links:
                links = [
                    f"IE-{year}-{'si' if instrument else 'act'}-{int(number)}"
                    for instrument, number, year in re.findall(
                        r"(S\.\s*I\.\s*)?No\.\s*(\d+)\s+of\s+(\d{4})", segment
                    )
                ] + [f"IE-{y}-act-{int(n)}" for n, y in re.findall(r"\b(\d+)/(\d{4})\b", segment)]
            stars = re.match(r"\*+", segment)[0]
            footnotes.append((stars, segment, set(links)))
    return footnotes


def _collective_citation(note: str) -> bool:
    return bool(
        re.match(
            r"^(?:Act(?:, Part \d+ \(ss\. [\d-]+\))? included in |"
            r"Collectively cited with |Collective citation ).+ Acts?\b",
            note,
        )
    )


def parse_effects(
    data: bytes, norm_id: str, *, editorial_notes: list[dict] | None = None
) -> list[dict]:
    """Preserve every resolvable effect, including continuation rows and pending changes."""
    doc = html.fromstring(data.decode("utf-8"))
    cells_by_row = _effect_cells(doc, norm_id)
    if cells_by_row is None:
        if editorial_notes is None:
            raise ValueError(f"{norm_id}: directory omission requires a provenance sink")
        editorial_notes.append(
            {
                "kind": "source_coverage_warning",
                "note": "The annual Legislation Directory does not list this instrument; "
                "this does not establish that it has never been amended or revoked.",
                "source_sha256": sha256(data).hexdigest(),
            }
        )
        return []
    annual_footnotes = _annual_footnotes(doc, norm_id)
    footnotes = [
        _text(node)
        for node in doc.xpath('//*[@id="effects"]/following-sibling::*[not(self::table)]')
        if re.search(r"(?:^|\s)(?:Ss?\.[\d\s(),a-z-]+)?\*|^Ss?\.[\d\s(),a-z-]+:", _text(node), re.I)
    ]
    if not any(cells_by_row):
        if sha256(data).hexdigest() == _EMPTY_EFFECTS_DIRECTORIES.get(norm_id):
            if editorial_notes is None:
                raise ValueError(f"{norm_id}: empty effects table requires a provenance sink")
            editorial_notes.append(
                {
                    "kind": "source_coverage_warning",
                    "note": "The official Legislation Directory has an empty effects table; "
                    "this does not establish that the Act has never been amended.",
                    "source_sha256": sha256(data).hexdigest(),
                }
            )
            return []
        raise ValueError(f"{norm_id}: effects table has no source rows")
    effects = []
    previous_effects = []
    previous_note = ""
    scope = ""
    pending_reference = False
    for row_index, cells in enumerate(cells_by_row):
        if not cells:
            previous_effects = []
            continue
        if len(cells) not in (2, 4):
            raise ValueError(f"{norm_id}: unexpected effects row with {len(cells)} columns")
        if (
            len(cells) == 2
            and re.search(
                r"\b(?:inserted|substituted|amended|ins\.|subst\.)\s+by\s*$", _text(cells[1]), re.I
            )
            and row_index + 1 < len(cells_by_row)
        ):
            following = cells_by_row[row_index + 1]
            if len(following) == 2 and not _text(following[0]) and _text(following[1]):
                # A source table can wrap the actual amender onto a second physical row.
                continuation = deepcopy(following[1])
                continuation.tag = "span"
                continuation.text = " " + (continuation.text or "")
                cells[1].append(continuation)
                cells_by_row[row_index + 1] = []
        texts = [_text(cell) for cell in cells]
        if not any(texts):
            previous_effects = []
            continue
        note = texts[0] or previous_note
        provision = texts[1]
        ids, correction = _affecting_ids(cells[1], provision, norm_id, note)
        if (
            not ids
            and _collective_citation(note)
            and (not provision or re.search(r"\b(?:Geo\.|Vict\.|Edw\.)", provision))
        ):
            if editorial_notes is None:
                raise ValueError(
                    f"{norm_id}: collective citation requires an editorial_notes destination"
                )
            editorial_notes.append(
                {"kind": "collective_citation", "note": note, "provision": provision}
            )
            previous_note = note
            continue
        if pending_reference:
            if not ids or texts[0]:
                raise ValueError(f"{norm_id}: See also has no following source citation")
            note = "See also"
            provision = f"See also; {provision}"
            pending_reference = False
        if not ids and not texts[0] and not any(texts[2:]) and provision.lower() == "see also":
            pending_reference = True
            previous_effects = []
            continue
        if (
            not ids
            and not texts[0]
            and not any(texts[2:])
            and previous_effects
            and re.fullmatch(
                r"(?:but see|see also) ss?\. [\d(), .-]+|And see (?:regs|oo)\. under|, expired(?: \d{1,2} \w+ \d{4})?\.",
                provision,
                re.I,
            )
        ):
            for effect in previous_effects:
                effect["provision"] += f"; {provision}"
            continue
        previous_effects = []
        marker = re.search(r"\*+", note + " " + provision)
        matching_footnotes = [
            footnote
            for footnote in footnotes
            if (
                (
                    marker
                    and (footnote_marker := re.search(r"\*+", footnote))
                    and footnote_marker[0] == marker[0]
                )
                or re.sub(r"[ *.]", "", note) == re.sub(r"[ *.]", "", footnote.split(":", 1)[0])
                or (
                    marker
                    and ":" in footnote
                    and (scoped := re.fullmatch(r"S\.\s*(\d+)\((\d+)\)\*+", note))
                    and re.match(rf"^S\.\s*{scoped[1]}\(", footnote)
                    and f"({scoped[2]})" in footnote.split(":", 1)[0]
                )
            )
        ]
        if not ids and provision == "Order made under*" and len(matching_footnotes) == 1:
            ids, correction = _affecting_ids(cells[1], matching_footnotes[0], norm_id, note)
        rent_amendment = (
            norm_id == "IE-2005-act-26"
            and provision == "S.I. No. 188 of 1998, sch. A"
            and note == "S. 250 applied with modifications **"
            and any("** See also S.I. No. 600 of 2011, reg. 7" in text for text in footnotes)
        )
        if rent_amendment:
            ids.add("IE-2011-si-600")
        judicial = bool(
            re.search(
                r"declared (?:unconstitutional|constitutional|invalid)|deemed incompatible with Art(?:icle|\.) \d+[.\d]* of the Constitution|not compatible with the Constitution",
                note,
                re.I,
            )
        )
        judicial = judicial and bool(re.search(r"\bv\.? .+(?:\[\d{4}\]|\(\d{4}\))", provision))
        judicial_footnotes = []
        section = re.match(r"S\.\s*(\d+[A-Z]?)", note)
        for footnote in matching_footnotes:
            if not re.search(
                r"invalid|inconsistent|not compatible|repugnant to the Constitution", footnote, re.I
            ):
                continue
            scope_matches = re.findall(r"Ss?\.\s*([^:]+):", footnote.lstrip("* "), re.I)
            if (
                scope_matches
                and section
                and not any(re.search(rf"\b{section[1]}\b", scope) for scope in scope_matches)
            ):
                continue
            judicial_footnotes.append(footnote)
        judicial = judicial or (
            (
                not provision
                or re.search(
                    r"declared (?:unconstitutional|constitutional|invalid)|deemed incompatible with Art(?:icle|\.) \d+[.\d]* of the Constitution|not compatible with the Constitution",
                    note,
                    re.I,
                )
            )
            and bool(judicial_footnotes)
        )
        if (
            not ids
            and provision
            == "Warning: this list may not be complete; it is currently being checked and will be updated as soon as possible."
        ):
            if editorial_notes is None:
                raise ValueError(
                    f"{norm_id}: source coverage warning requires an editorial_notes destination"
                )
            editorial_notes.append({"kind": "source_coverage_warning", "note": provision})
            previous_note = ""
            continue
        if not ids and judicial:
            if editorial_notes is None:
                raise ValueError(
                    f"{norm_id}: judicial source note requires an editorial_notes destination"
                )
            entry = {"note": note, "provision": provision, "kind": "judicial_finding"}
            if len(texts) == 4 and any(texts[2:]):
                entry.update(directory_date=texts[2], directory_date_source=texts[3])
            if judicial_footnotes:
                entry["footnotes"] = judicial_footnotes
            editorial_notes.append(entry)
            previous_note = ""
            continue
        if (
            not ids
            and re.fullmatch(r"S\. \d+\(\d+\) proclamation made", note)
            and re.fullmatch(r"Iris Oifigiuil,? \d+ [A-Za-z]+ \d{4}", provision)
        ):
            if editorial_notes is None:
                raise ValueError(
                    f"{norm_id}: gazette source note requires an editorial_notes destination"
                )
            gazette_date = source_date(provision)
            if gazette_date is None:
                raise ValueError(f"{norm_id}: invalid gazette proclamation date")
            editorial_notes.append(
                {
                    "kind": "gazette_proclamation",
                    "note": note,
                    "provision": provision,
                    "gazette_date": gazette_date.isoformat(),
                }
            )
            previous_note = ""
            continue
        if not ids and re.fullmatch(
            r"Resolution of (?:D[aá]il|Seanad) [EÉ]ireann: (?:Debates )?(?:Volume|Vol\.) \d+,? no\.? \d+, .+",
            provision,
            re.I,
        ):
            if editorial_notes is None:
                raise ValueError(
                    f"{norm_id}: parliamentary resolution requires an editorial_notes destination"
                )
            editorial_notes.append(
                {"kind": "parliamentary_resolution", "note": note, "provision": provision}
            )
            previous_note = note
            continue
        if (
            not ids
            and (
                note == "Virt. Rep., Principal Act, Rep."
                or re.fullmatch(r"Ceased in accordance with s\. \d+", note)
                or re.fullmatch(r"Expired at (?:the )?end of .+", note)
            )
            and not provision
        ):
            if editorial_notes is None:
                raise ValueError(
                    f"{norm_id}: undated classification requires an editorial_notes destination"
                )
            editorial_notes.append({"kind": "directory_classification", "note": note})
            previous_note = ""
            continue
        if not ids and re.fullmatch(r"Spent\.?", note, re.I) and not any(texts[2:]):
            outgoing = provision in {"Amended", "Extended duration of and amended"}
            if outgoing:
                if editorial_notes is None:
                    raise ValueError(f"{norm_id}: spent classification requires a provenance sink")
                # The continuation names the earlier Act this spent Act amended, not an incoming reform.
                for following in cells_by_row[row_index + 1 :]:
                    if len(following) != 2 or _text(following[0]):
                        break
                    provision = f"{provision} {_text(following[1])}".strip()
                    following.clear()
            if editorial_notes is not None:
                editorial_notes.append(
                    {
                        **({"kind": "directory_classification"} if outgoing else {}),
                        "note": note,
                        **({"provision": provision} if provision else {}),
                    }
                )
            previous_note = ""
            continue
        if (
            not ids
            and note == "Registration Boards established by s. 26 or by regulation under s. 4"
            and not provision
        ):
            if editorial_notes is None:
                raise ValueError(
                    f"{norm_id}: directory context requires an editorial_notes destination"
                )
            editorial_notes.append({"kind": "directory_context", "note": note})
            previous_note = ""
            continue
        if not provision and not ids:
            if row_index + 1 < len(cells_by_row) and not any(texts[2:]):
                following = cells_by_row[row_index + 1]
                if len(following) in (2, 4) and not _text(following[0]):
                    next_ids, _ = _affecting_ids(following[1], _text(following[1]), norm_id, note)
                    if next_ids:
                        previous_note = note
                        continue
            if not note or re.fullmatch(r"Not affected\.?|None", note, re.I):
                continue
            if re.fullmatch(
                r"References construed|(?:\w+ )?Schedule(?: \w+)?|Parts? (?:[IVX]+[A-Z]?|\d+[A-Z]?)(?:, (?:[IVX]+[A-Z]?|\d+[A-Z]?))*(?: Chapter \d+[A-Z]?)?(?: \(ss?\. [\dA-Z, -]+\))?",
                note,
                re.I,
            ):
                scope = "" if note.lower() == "references construed" else note
                continue
            if editorial_notes is None or note not in _UNATTRIBUTED_ROWS.get(norm_id, ()):
                raise ValueError(f"{norm_id}: effect has no affecting provision: {note}")
            editorial_notes.append(
                {"kind": "unattributed_directory_effect", "note": note, "provision": ""}
            )
            previous_note = ""
            continue
        if texts[0]:
            previous_note = note
        if not ids:
            # These source rows describe this Act's own citation or operation provisions.
            if re.fullmatch(
                r"(?:s\.?|ss\.|sch\.|section|sections|schedule|part|art\.)\s*"
                r"\d+[a-z]?(?:\([0-9a-z]+\))*(?:\s*[-,]\s*\([0-9a-z]+\))*(?:,\s*sch\.\s*\d+[a-z]?)?\.?",
                provision,
                re.I,
            ):
                continue
            # An instrument's own regulations, e.g. "Spent 31 Dec 2004 | Regs. 1(b), 3".
            if re.fullmatch(
                r"(?:regs?|arts?|rules?)\.?\s*\d+[a-z]?(?:\([0-9a-z]+\))*"
                r"(?:\s*(?:,|and)\s*(?:\d+[a-z]?(?:\([0-9a-z]+\))*|sch(?:edule)?\.?))*\.?",
                provision,
                re.I,
            ):
                if re.match(r"(?:Spent|Expired|Ceased|Lapsed)\b", note, re.I):
                    if editorial_notes is None:
                        raise ValueError(
                            f"{norm_id}: directory classification requires a provenance sink"
                        )
                    editorial_notes.append(
                        {"kind": "directory_classification", "note": note, "provision": provision}
                    )
                continue
            if editorial_notes is None or provision not in _UNATTRIBUTED_ROWS.get(norm_id, ()):
                raise ValueError(f"{norm_id}: unresolved affecting provision: {provision}")
            editorial_notes.append(
                {"kind": "unattributed_directory_effect", "note": note, "provision": provision}
            )
            continue
        for identifier in sorted(ids - {norm_id}):
            effect = _effect(
                f"{scope}: {note}" if scope else note,
                provision,
                identifier,
                texts[2] if len(texts) == 4 else "",
                texts[3] if len(texts) == 4 else "",
            )
            if correction:
                effect["source_correction"] = correction
            # Kept for fetch_effects, which can date an effect only once it knows the
            # publication dates; these keys never reach the published text.
            if cited := [
                (text, sources)
                for stars, text, sources in annual_footnotes
                if marker and stars == marker[0]
            ]:
                effect["_footnotes"] = [text for text, _ in cited]
                effect["_footnote_ids"] = sorted(set().union(*(s for _, s in cited)))
            if rent_amendment and identifier == "IE-2011-si-600":
                effect["directory_source_id"] = "IE-1998-si-188"
                effect["directory_footnotes"] = [
                    text for text in footnotes if "** See also S.I. No. 600 of 2011, reg. 7" in text
                ]
                effect["source_correction"] = (
                    "https://www.irishstatutebook.ie/eli/2011/si/600/made/en/html"
                )
            if norm_id == "IE-1983-act-35" and correction and identifier == "IE-2008-act-1":
                effect["commencement"] = "5 May 2008"
                effect["commencement_source"] = (
                    "https://www.irishstatutebook.ie/eli/2008/si/126/made/en/html"
                )
                effect["effective_date"] = "2008-05-05"
            if provision == "Order made under*" and matching_footnotes:
                effect["directory_footnotes"] = matching_footnotes
            if (
                norm_id == "IE-2014-act-38"
                and re.search(r"\bas (?:inserted|substituted) by\b", provision)
                and (
                    commencement_fix := _COMPANIES_COMMENCEMENTS.get(
                        (identifier, effect["commencement"])
                    )
                )
                and provision.endswith(commencement_fix[2])
            ):
                effect["directory_commencement"] = effect["commencement"]
                effect["directory_commencement_source"] = effect["commencement_source"]
                effect["commencement"], effect["commencement_source"] = commencement_fix[:2]
                effect["effective_date"] = source_date(effect["commencement"]).isoformat()
                effect["source_correction"] = effect["commencement_source"]
            if identifier == "IE-1990-act-25" and re.fullmatch(
                r"(?:Pensions Act 1990 \()?(?:25/1990|No\. 25 of 1990)\)?, s\. 9A(?:\s*\(see.*)?",
                provision,
            ):
                # Section 9A was inserted in 2013, with operation fixed by S.I. 103/2014.
                effect["directory_source_id"] = identifier
                effect["directory_commencement"] = effect["commencement"]
                effect["directory_commencement_source"] = effect["commencement_source"]
                effect["source_id"] = "IE-2013-act-20"
                effect["source_correction"] = (
                    "https://www.irishstatutebook.ie/eli/2013/act/20/section/26/enacted/en/html"
                )
                effect["commencement"] = "7 March 2014"
                effect["commencement_source"] = (
                    "https://www.irishstatutebook.ie/eli/2014/si/103/made/en/html"
                )
                effect["effective_date"] = "2014-03-07"
            if verified_source := _VERIFIED_EFFECT_SOURCES.get((norm_id, provision, identifier)):
                path, commencement, order = verified_source
                state = "made" if "/si/" in path else "enacted"
                source = f"https://www.irishstatutebook.ie/eli/{path}/{state}/en/html"
                effect["directory_source_id"] = identifier
                effect["source_id"] = norm_id_from_url(source)
                effect["source_correction"] = source
                if commencement is not None:
                    effect["directory_commencement"] = effect["commencement"]
                    effect["directory_commencement_source"] = effect["commencement_source"]
                    effect["commencement"] = commencement
                    effect["commencement_source"] = (
                        f"https://www.irishstatutebook.ie/eli/{order}/made/en/html" if order else ""
                    )
                    effect["effective_date"] = (
                        source_date(commencement).isoformat() if commencement else None
                    )
            effects.append(effect)
            previous_effects.append(effect)
    if pending_reference:
        raise ValueError(f"{norm_id}: See also has no following source citation")
    return effects


def constitution_effects(data: bytes) -> list[dict]:
    """Use the Constitution's own amendment/signature table, not invented enactment years."""
    doc = html.fromstring(data.decode("utf-8"))
    tables = [
        table
        for table in doc.xpath("//table")
        if any(
            "DATE OF SIGNATURE" in _text(cell) for cell in table.xpath("./tr/th | ./tbody/tr/th")
        )
    ]
    if len(tables) != 1:
        raise ValueError("Constitution has no unique amendment signature table")
    effects = []
    for row in tables[0].xpath("./tr | ./tbody/tr"):
        cells = row.xpath("./td")
        if len(cells) != 2:
            continue
        identifiers = {
            identifier
            for url in cells[0].xpath(".//a/@href")
            if (identifier := norm_id_from_url(url))
        }
        if not identifiers:
            if source_date(_text(cells[1])):
                raise ValueError(f"Unresolved constitutional amendment: {_text(row)}")
            continue
        signed = source_date(_text(cells[1]))
        if len(identifiers) != 1 or signed is None:
            raise ValueError(f"Unresolved constitutional amendment: {_text(row)}")
        effect = _effect(_text(cells[0]), _text(cells[0]), identifiers.pop())
        effect["publication_date"] = signed.isoformat()
        effect["publication_date_source"] = "Constitution amendment table: DATE OF SIGNATURE"
        effects.append(effect)
    if not effects:
        raise ValueError("Constitution has no dated amendments")
    return effects


def _constitution_repeal_commencement(data: bytes) -> tuple[str, str]:
    """Read Article 48's explicit connection to the Constitution's operation date."""
    doc = html.fromstring(data.decode("utf-8"))
    article = doc.xpath(
        '//*[@id="article48" or @name="article48"]'
        '/following::p[not(normalize-space(.)="ARTICLE 48")][1]'
    )
    required = (
        "date of the coming into operation of this Constitution",
        "Act, 1922",
        "repealed as on and from that date",
    )
    if len(article) != 1 or not all(part in _text(article[0]) for part in required):
        raise ValueError("Constitution Article 48 has no verified repeal commencement rule")
    statements = [
        _text(node) for node in doc.xpath("//p") if _text(node).startswith("In operation as from ")
    ]
    if len(statements) != 1 or (effective := source_date(statements[0])) is None:
        raise ValueError("Constitution has no unique stated operation date")
    return statements[0], effective.isoformat()


def fetch_effects(
    client: ISBClient,
    norm_id: str,
    enacted_data: bytes,
    *,
    editorial_notes: list[dict] | None = None,
) -> list[dict]:
    """Fetch source effects and attach actual affecting-instrument publication dates."""
    from legalize.fetcher.ie.parser import ISBMetadataParser, _is_xml_source

    continuity_notes = {}
    continuity_section = None
    if norm_id == CONSTITUTION_ID:
        effects = constitution_effects(enacted_data)
        directory_url = f"{client._base_url}/eli/cons/en/html"
    else:
        year, kind, number = _parse_norm_id(norm_id)
        source_url = f"{client._base_url}/eli/{year}/{kind}/{number}/"
        source_url += "made/en/html" if kind == "si" else "enacted/en/html"
        page = enacted_data
        if _is_xml_source(page):
            page = client._get(source_url)
        doc = html.fromstring(page.decode("utf-8"))
        links = {
            urljoin(source_url, link)
            for link in doc.xpath("//a/@href")
            if re.search(r"/isbc/[^/#?]+\.html(?:#|$)", link)
        }
        if not links and kind == "ca" and doc.xpath('//*[@id="act"]'):
            # eISB provides amendment Acts as enactments, without a separate effects directory.
            logger.info("%s: constitutional amendment source has no effects directory", norm_id)
            return []
        if len(links) != 1:
            raise ValueError(f"{norm_id}: source has no unique Legislation Directory link")
        directory_url = links.pop()
        # A missing directory is unknown history, not evidence that the Act was never amended.
        directory_data = client._get(directory_url)
        if kind == "si":
            ranges = []
            for link in html.fromstring(directory_data).xpath("//a/@href"):
                match = re.search(rf"si{year}_(\d+)-(\d+)\.html", link)
                if match and int(match[1]) <= int(number) <= int(match[2]):
                    ranges.append(urljoin(directory_url, link))
            if len(set(ranges)) == 1:
                directory_url = ranges[0]
                directory_data = client._get(directory_url)
            elif ranges:
                raise ValueError(f"{norm_id}: ambiguous instrument directory range")
        continuity = {
            "IE-1966-act-6": (
                "9",
                "Any document referring to any repealed enactment shall be construed "
                "as referring to this Act or the corresponding provision of this Act.",
            ),
            "IE-1958-act-11": (
                "10",
                "any document referring to any enactment repealed by subsection (1) "
                "of this section shall, unless the contrary intention appears, be construed "
                "as referring to the corresponding enactment of this Act.",
            ),
            "IE-1980-act-10": (
                "11",
                "The Landlord and Tenant (Amendment) Act, 1971, shall have effect as if "
                "the references to provisions of the Act of 1958 were to the corresponding "
                "provisions of this Act.",
            ),
            "IE-1981-act-1": (
                "311",
                "The continuity of the operation of the law relating to the matters provided "
                "for in the repealed enactments shall not be affected by the substitution of "
                "this Act for those enactments",
            ),
        }.get(norm_id)
        if continuity:
            continuity_section, continuation = continuity
            enacted_doc = html.fromstring(enacted_data)
            provision = enacted_doc.xpath(f'//*[@id="SEC{continuity_section}"]')
            if len(provision) == 1 and continuation in _text(provision[0]):
                for node in html.fromstring(directory_data).xpath(
                    '//*[@id="effects"]/following-sibling::*[not(self::table)]'
                ):
                    note = _text(node)
                    label, _, basis = note.partition(":")
                    if basis.strip() in {
                        "See s. 20 (1), Interpretation Act, 1937.",
                        "See Interpretation Act, 1937, s. 20 (1).",
                    }:
                        continuity_notes[re.sub(r"[ *]", "", label)] = note
        source_notes = []
        effects = parse_effects(directory_data, norm_id, editorial_notes=source_notes)
        if editorial_notes is not None:
            editorial_notes.extend(
                {**note, "directory_url": directory_url} for note in source_notes
            )
    parser = ISBMetadataParser()
    metadata = {}
    metadata_sources = {}
    dated_effects = []
    original_date = None
    for effect in effects:
        footnotes = effect.pop("_footnotes", [])
        footnote_ids = effect.pop("_footnote_ids", [])
        source_id = effect["source_id"]
        if undatable := _UNDATABLE_SOURCES.get((norm_id, source_id)):
            if editorial_notes is None:
                raise ValueError(f"{norm_id}: undatable source requires a provenance sink")
            _check_undatable(client, source_id, undatable[0])
            year, kind, number = _parse_norm_id(source_id)
            editorial_notes.append(
                {
                    **effect,
                    "directory_url": directory_url,
                    "kind": "undatable_source",
                    "reason": undatable[1],
                    "basis_source": f"{client._base_url}/eli/{year}/{kind}/{number}/made/en/html",
                }
            )
            continue
        if "publication_date" not in effect:
            if source_id not in metadata:
                metadata_sources[source_id] = client.get_metadata(source_id)
                metadata[source_id] = parser.parse(metadata_sources[source_id], source_id)
            source = metadata[source_id]
            effect["publication_date"] = (
                source.publication_date.isoformat() if source.publication_date else None
            )
            effect["source_url"] = source.source
        if (
            norm_id == "IE-1922-act-1"
            and source_id == CONSTITUTION_ID
            and effect["whole_repeal"]
            and re.search(r"\bArt\.\s*48\b", effect["provision"])
            and not effect["effective_date"]
            and not effect["pending"]
        ):
            commencement, effective = _constitution_repeal_commencement(metadata_sources[source_id])
            effect["commencement"] = commencement
            effect["commencement_source"] = f"{effect['source_url']}#article48"
            effect["effective_date"] = effective
        if "source_url" not in effect:
            year, kind, number = _parse_norm_id(source_id)
            effect["source_url"] = f"{client._base_url}/eli/{year}/{kind}/{number}/enacted/en/html"
        effect["directory_url"] = directory_url
        if (
            context := _DIRECTORY_CONTEXT.get(
                (norm_id, source_id, effect["note"], effect["provision"])
            )
        ) and date.fromisoformat(effect["publication_date"]) < parser.parse(
            enacted_data, norm_id
        ).publication_date:
            if editorial_notes is None:
                raise ValueError(
                    f"{norm_id}: verified directory context requires a provenance sink"
                )
            editorial_notes.append(
                {**effect, "kind": context[0], "reason": context[1], "basis_source": context[2]}
            )
            continue
        if (
            (rule := _PRE_EXISTING_RULES.get((norm_id, effect["provision"])))
            and effect["note"] == rule[0]
            and date.fromisoformat(effect["publication_date"])
            < parser.parse(enacted_data, norm_id).publication_date
        ):
            if editorial_notes is None:
                raise ValueError(f"{norm_id}: pre-existing rule requires a provenance sink")
            editorial_notes.append(
                {**effect, "kind": "pre_existing_rule", "reason": rule[1], "basis_source": rule[2]}
            )
            continue
        collective_member = _collective_citation(effect["note"])
        collective_application = re.search(
            r"\bcollectively cited\b.*\bActs\b", effect["note"], re.I
        )
        if collective_member or collective_application:
            original_date = parser.parse(enacted_data, norm_id).publication_date
            if date.fromisoformat(effect["publication_date"]) < original_date:
                if editorial_notes is None:
                    raise ValueError(
                        f"{norm_id}: earlier collective citation requires a provenance sink"
                    )
                editorial_notes.append(
                    {
                        **effect,
                        "kind": (
                            "collective_citation"
                            if collective_member
                            else "pre_existing_collective_application"
                        ),
                        "reason": (
                            "An earlier member of the collectively cited Acts is context, not a later amendment."
                            if collective_member
                            else "An earlier rule applying to the collectively cited Acts is context, "
                            "not a later amendment of this Act."
                        ),
                    }
                )
                continue
        continuity_note = None
        if continuity_notes:
            if norm_id in {"IE-1980-act-10", "IE-1981-act-1"}:
                continuity_note = continuity_notes.get(re.sub(r"[ *]", "", effect["provision"]))
            elif effect["note"] == "Excl. provns. ext. to Customs-free Airport. *" and (
                source_id,
                effect["provision"],
            ) in {
                ("IE-1947-si-115", "S.R. & O. No. 115 of 1947"),
                ("IE-1951-si-60", "S.R. & O. No. 60 of 1951"),
            }:
                continuity_note = continuity_notes.get(re.sub(r"[ *]", "", effect["note"]))
        if (
            continuity_note
            and date.fromisoformat(effect["publication_date"])
            < parser.parse(enacted_data, norm_id).publication_date
        ):
            if editorial_notes is None:
                raise ValueError(f"{norm_id}: inherited application requires a provenance sink")
            editorial_notes.append(
                {
                    **effect,
                    "type": "pre_existing_application",
                    "reason": (
                        "References to repealed enactments continue under their re-enactment; "
                        "this is not a later amending instrument."
                    ),
                    "continuity_basis": {
                        "directory_note": continuity_note,
                        "interpretation_source": (
                            "https://www.irishstatutebook.ie/eli/1937/act/38/section/20/enacted/en/html"
                        ),
                        "re_enactment_source": (
                            f"{client._base_url}/eli/{year}/{kind}/{number}/"
                            f"section/{continuity_section}/enacted/en/html"
                        ),
                    },
                }
            )
        elif (
            footnote_ids
            and effect["publication_date"]
            and date.fromisoformat(effect["publication_date"])
            < (
                original_date := original_date
                or parser.parse(enacted_data, norm_id).publication_date
            )
        ):
            # An instrument published before this one cannot have amended it on that
            # date. Date the effect only from a later instrument the directory itself
            # names; anything else still needs a verified rule.
            later = set()
            for candidate in footnote_ids:
                if candidate not in metadata:
                    metadata_sources[candidate] = client.get_metadata(candidate)
                    metadata[candidate] = parser.parse(metadata_sources[candidate], candidate)
                published = metadata[candidate].publication_date
                if published and published >= original_date:
                    later.add(candidate)
            if len(later) > 1:
                raise ValueError(
                    f"{norm_id}: directory footnote names several later sources for {source_id}"
                )
            if later:
                # "Revoked | 2/1995, s. 45*" with "*See Adoptive Leave Act 2005 (No. 25 of 2005)".
                source = metadata[later_id := later.pop()]
                effect.update(
                    directory_source_id=source_id,
                    directory_footnotes=footnotes,
                    source_id=later_id,
                    publication_date=source.publication_date.isoformat(),
                    source_url=source.source,
                    source_correction=source.source,
                )
                dated_effects.append(effect)
                continue
            # Unverified: history still refuses it until the relation is researched.
            dated_effects.append(effect)
        else:
            dated_effects.append(effect)
    return dated_effects
