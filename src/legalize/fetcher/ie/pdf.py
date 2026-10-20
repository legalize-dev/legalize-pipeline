"""Recover selectable, unannotated LRC Revised Act PDF snapshots.

The archive contains two XEP layouts: older marginal section titles and newer
headings above the text. Geometry is necessary because these PDFs are untagged.
Unsupported/scanned documents fail rather than yielding an apparently valid
partial statute. Snapshot dates come from the cover, never PDF creation metadata.
"""

from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from hashlib import sha256
from itertools import groupby
from threading import Lock
from urllib.parse import urlsplit

import pdfplumber
from lxml import etree
from pdfplumber.utils import extract_text

from legalize.fetcher._tables import render_table
from legalize.fetcher._text import strip_control
from legalize.fetcher.ie.parser import _escaped_sign, _legal_format, _quote_delta
from legalize.models import Paragraph

_SECTION = re.compile(r"^(?:(?:F\d+)?\[\s*)?(\d+[A-Z]*)\s*(?:\.|(?=\(1\)))")
# A section substituted twice prints both markers: "F22[ F23[22.—".
# A label printed without its period, straight into the dash ("72A— Where an event
# occurs", Road Traffic Act 1961): read leniently, and only for a listed, unseen label.
_DASHED_SECTION = re.compile(r"^(?:(?:F\d+)?\[\s*)*(\d+[A-Z]*)(?=—)")
_NESTED_SECTION = re.compile(r"^(?:(?:F\d+)?\[\s*)*(\d+[A-Z]*)\s*(?:\.|(?=\(1\)))")
_DIVISION = re.compile(
    r"^(?:(?:F\d+)?\[)?(?:(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH) )?"
    r"(PART|CHAPTER|SCHEDULE)\s*(?:[\dIVXLCDM]+[A-Z]*)?$",
    re.I,
)
_DATE = re.compile(r"Updated to\s+(\d{1,2})\s+(\w+)\s+(\d{4})", re.I)
_MONTHS = (
    "january february march april may june july august september october november december"
).split()


def _month_number(name: str) -> int:
    """A full or three-letter month: some covers print "Updated to 8 Mar 2023"."""
    name = name.lower()
    matches = [i for i, month in enumerate(_MONTHS, 1) if len(name) >= 3 and month.startswith(name)]
    if len(matches) != 1:
        raise ValueError(f"unknown month {name!r}")
    return matches[0]


_PDF_PARSE_LOCK = Lock()

# These exact official files omit an in-force provision from their bodies while
# retaining its contents entry. Preserve the source, with an explicit warning;
# never extend this exception to other bytes or other missing provisions.
# Evidence: tests/fixtures/ie/archive-companies-2020-source-gaps.json.
_KNOWN_SOURCE_OMISSIONS = {
    digest: frozenset({"1384A"})
    for digest in (
        "d487045605971cca95feddf6dbd824188edd95e9f1e0f1d62c191cdd083e777d",
        "c056a097cf75e05af4f180de51d3be8623292dc0e9deff789430116d8c5a21bd",
        "1e6a866df584baa5f2048e81344e8944d01d4f4aed47ea6430403b9309d2bcdc",
        "a02cbaf5440607a30604171a50a483e4b8a8db5a7f742ad7e10fdde34e937947",
    )
}

# Exact original PDFs whose cover and LRC catalogue agree, but internal headings retain older dates.
# Evidence: tests/fixtures/ie/pdf-conflicting-cutoffs-evidence.json.
_KNOWN_CUTOFF_CONFLICTS = {
    "3b4981e780e5873409b7820577f0cbcef10e69fed313c526379af9e2557abee8": (  # pragma: allowlist secret
        date(2018, 10, 1),
        date(2017, 11, 22),
    ),
    "0d7d721b32e0dcaa879d7aa0a5d4aa5611e7be50a1f26777f4f7045a30afe237": (  # pragma: allowlist secret
        date(2024, 5, 22),
        date(2024, 2, 23),
    ),
    "e2d91d53fc254a5053b4ec26b6ec3d184202707c49f5b1b525a6e260e77213a1": (  # pragma: allowlist secret
        date(2024, 12, 17),
        date(2024, 9, 23),
    ),
    "c872335450cb627400c0a81f3847fe8d1a686446ae7c9033a5d2c29d97e853d3": (  # pragma: allowlist secret
        date(2023, 3, 8),
        date(2021, 9, 28),
    ),
    "3470a02b341db79ad2bab7405b500de47224c0e3076cb6961f93a2841027a24e": (  # pragma: allowlist secret
        date(2024, 8, 31),
        date(2023, 5, 3),
    ),
    "ac398f66fdbe7e7eb1a859360ab4f46639be11c214bac56dd6d344c79d3a3ab1": (  # pragma: allowlist secret
        date(2024, 9, 30),
        date(2024, 9, 2),
    ),
    "433aa13833ebcceb8f830d3c7d04e0f164244fb52f6ddf43dfcc13a6100e32de": (  # pragma: allowlist secret
        date(2023, 11, 30),
        date(2023, 8, 31),
    ),
    "d3d3c63c2ad361522f1e55bfe8d07e1b885b20ee9d8b4e0209919013273d0381": (  # pragma: allowlist secret
        date(2021, 7, 21),
        date(2021, 3, 24),
    ),
    # Pinned from the 2026-10-19 survey; evidence: tests/fixtures/ie/pdf-cover-date-pins.json.
    "2258a2660883739a686cb2574747b20277e572ef4a6869f6c567dc2cec1ff0de": (  # pragma: allowlist secret  IE-1964-act-16
        date(2023, 3, 1),
        date(2021, 12, 23),
    ),
    "2803a9de3ec2612c0c4676f7b4399c546d264c86d3a5380c265758c4dd9ff908": (  # pragma: allowlist secret  IE-1970-act-1
        date(2020, 11, 1),
        date(2020, 10, 27),
    ),
    "724cd90db7d9a955f34216ba0b5fe3305382f27eaf1ea1747030c54a29c58379": (  # pragma: allowlist secret  IE-1970-act-1
        date(2023, 4, 17),
        date(2023, 1, 1),
    ),
    "11de2291b281e7fcfdef46e058317c0314f601e1835b81db5aac372004949fa8": (  # pragma: allowlist secret  IE-1988-act-25
        date(2018, 5, 25),
        date(2018, 1, 1),
    ),
    "13d862868910e9c6489971b8aa32b4be7a30ba5ee83e4c2ba6b5b484efe82f0f": (  # pragma: allowlist secret  IE-1992-act-18
        date(2022, 1, 4),
        date(2019, 5, 1),
    ),
    "842bd2a69a759c7e6d439e56b2e7b0fa7bada8a1ae6e856be24fd23e38390ca7": (  # pragma: allowlist secret  IE-1992-act-18
        date(2023, 3, 1),
        date(2019, 5, 1),
    ),
    "b92bcbd51d168736734709845b587db24c7918d2d5622a9e150f5dc5e42f4b47": (  # pragma: allowlist secret  IE-1994-act-16
        date(2023, 4, 1),
        date(2023, 1, 1),
    ),
    "6439cfc37fdbab6ec0f25ffbe08dfb956d7aa2af83f07bd6ff8d3f47ec007d6f": (  # pragma: allowlist secret  IE-1996-act-10
        date(2024, 1, 1),
        date(2023, 9, 22),
    ),
    "64d003c81d9807732ed4ff07af879ad12ff37abf4b52ae79e33188c25ab350e7": (  # pragma: allowlist secret  IE-1999-act-23
        date(2022, 2, 15),
        date(2021, 2, 15),
    ),
    "0c021fbf8148b3ac598a53d1875de81cd4afe728b15f95d9ed196b6e9cb9a1fc": (  # pragma: allowlist secret  IE-2002-act-20
        date(2022, 11, 29),
        date(2022, 9, 6),
    ),
    "930b4258a669afa6aefac25f24972fdbc636d398f915a4cb3ec4d88a6808ae3d": (  # pragma: allowlist secret  IE-2004-act-1
        date(2021, 7, 29),
        date(2021, 1, 28),
    ),
    "c65e4a486014606bcff9d98410d62831edfec8c236c6beacd0d7e975f5e83f59": (  # pragma: allowlist secret  IE-2005-act-2
        date(2023, 5, 11),
        date(2023, 4, 5),
    ),
    "5f1d70814dd65e312c80eff11e54bc71a99dd44c54e0215e67a5129d40ede17a": (  # pragma: allowlist secret  IE-2005-act-21
        date(2019, 9, 1),
        date(2016, 10, 26),
    ),
    "45c0f75cce05b6b0413aaf74e35b7241d22ff7dd84f00761bd85c22f24f2a9c9": (  # pragma: allowlist secret  IE-2006-act-26
        date(2023, 11, 1),
        date(2023, 7, 19),
    ),
    "3aed0a97a25ef852208fc13b4c441195b7142639d6ba4815d6d4a81b6f87e751": (  # pragma: allowlist secret  IE-2006-act-8
        date(2021, 1, 28),
        date(2021, 2, 1),
    ),
    "51daaff6a1bbb691e72724bc6a8dca8510d8e1342e1dfc2d23c121137a31170a": (  # pragma: allowlist secret  IE-2009-act-18
        date(2021, 7, 14),
        date(2020, 11, 12),
    ),
}

# The contents and title identify each section; the body omits only its number.
# Evidence: pdf-incomplete-headings-evidence.json and pdf-label-defects-evidence.json fixtures.
_KNOWN_UNNUMBERED_SECTIONS = {
    "c450d687d0be72849490e9e429c2b3e3152a12b5186955aa0252783864c5359f": (  # pragma: allowlist secret
        "14",
        "Amendment of Bail Act 1997",
        "The Schedule to the Bail Act 1997 is amended by the insertion of the following",
    ),
    "dbb963cf87485993227c9213345323a3d20a35e886e443db2fb413d252c6c7ff": (  # pragma: allowlist secret
        "71M",
        "F50[Revocation of licences under Musk Rats Act 1933",
        "All licences granted under the Musk Rats Act 1933 and subsisting on the date",
    ),
    # The later Animal Health and Welfare Act 2013 snapshots, each with its own mark and wrap.
    "99607d467a9c960d555b24545769d06a6b8af43ad1b8f0bcf2cd805914cde7aa": (  # pragma: allowlist secret
        "71M",
        "F50[Revocation of licences under Musk Rats Act 1933",
        "All licences granted under the Musk Rats Act 1933 and subsisting on the date",
    ),
    "5e0ca07c6cb77d82e5e12af49aaf0a24d74e84ff382ed28c6d0d0d6986a1991e": (  # pragma: allowlist secret
        "71M",
        "F50[Revocation of licences under Musk Rats Act 1933",
        "All licences granted under the Musk Rats Act 1933 and subsisting on the date",
    ),
    "c84d4e4568125626ae40e43d15553c0400809368d1c5a3a182a788c0c1f6d8af": (  # pragma: allowlist secret
        "71M",
        "F51[Revocation of licences under Musk Rats Act 1933",
        "All licences granted under the Musk Rats Act 1933 and subsisting on the date",
    ),
    "616d038251cccd5eb0556d668a3d08489f7312fb72dcef45f2c68d61b5ce60a5": (  # pragma: allowlist secret
        "71M",
        "F51[Revocation of licences under Musk Rats Act 1933",
        "All licences granted under the Musk Rats Act 1933 and subsisting on the date",
    ),
    "6dd32ace5b956bc99d9d2364c003c36cd4460fc33e0c2ed62a6096d124abdc0e": (  # pragma: allowlist secret
        "71M",
        "F51[Revocation of licences under Musk Rats Act 1933",
        "All licences granted under the Musk Rats Act 1933 and subsisting on the date",
    ),
    "38dea8df7b99e3663e6add7b2652ebc5571afe0f9fbbdda782519c9d204f31d0": (  # pragma: allowlist secret
        "71M",
        "F51[Revocation of licences under Musk Rats Act 1933",
        "All licences granted under the Musk Rats Act 1933 and subsisting on the date",
    ),
    "29b4d19f893b9e6e46ea37c8d8b53e58200db5fa3d61f1df5ce47603d023b9b7": (  # pragma: allowlist secret
        "71M",
        "F51[Revocation of licences under Musk Rats Act 1933",
        "All licences granted under the Musk Rats Act 1933 and subsisting on the date",
    ),
    "c2d989bae87bfe6b92dad9538064636e2d48dca1c26f4f30b91618c8c28f63f2": (  # pragma: allowlist secret
        "71M",
        "F51[Revocation of licences under Musk Rats Act 1933",
        "All licences granted under the Musk Rats Act 1933 and subsisting on the date",
    ),
    "c10e76838c161e5757431f0591e3f48196b4b3e3a06ede35d7a2522fb6f1f27c": (  # pragma: allowlist secret
        "71M",
        "F51[Revocation of licences under Musk Rats Act 1933",
        "All licences granted under the Musk Rats Act 1933 and subsisting on the date immediately",
    ),
    "f2b60c101fc7e850b1d19574649675b348ded9b0f14a0e785531dd9dfb6022d7": (  # pragma: allowlist secret
        "71M",
        "F51[Revocation of licences under Musk Rats Act 1933",
        "All licences granted under the Musk Rats Act 1933 and subsisting on the date immediately",
    ),
}

# Preserve verified source numbering defects verbatim, with visible warnings and exact counts.
# Evidence: tests/fixtures/ie/pdf-label-defects-evidence.json.
_CIVIL_REGISTRATION_30M = {  # pragma: allowlist secret
    "duplicates": {"30M": 2},
    "missing": frozenset(),
    "warning": (
        "This official Civil Registration Act 2004 PDF repeats section number 30M under "
        "two Part 3C headings, for stillbirths and surrogacy. Both entries and their labels "
        "are preserved as printed. A reference to section 30M alone is ambiguous in this source."
    ),
}
_GARDA_33E = {  # pragma: allowlist secret
    "duplicates": {},
    "missing": frozenset({"33E"}),
    "warning": (
        "This official Garda Síochána Act 2005 consolidated PDF is incomplete: section 33E "
        "is listed as repealed in its contents but absent from the body. Its text has not "
        "been reconstructed. Check the original legislation for its text and repeal history."
    ),
}
_REGISTRATION_OF_TITLE_124A = {
    "duplicates": {},
    "missing": frozenset({"124A"}),
    "warning": (
        "This official Registration of Title Act 1964 consolidated PDF is incomplete: section "
        "124A ('Evidence in proceedings') is listed in its contents but absent from the body. "
        "Its text has not been reconstructed. Check the original legislation for its text."
    ),
}
_COMPETITION_15AU = {
    "duplicates": {},
    "missing": frozenset({"15AU"}),
    "warning": (
        "This official Competition Act 2002 consolidated PDF lists section 15AU in its contents "
        "without a title, and its body has no section 15AU. Nothing has been reconstructed. "
        "Check the original legislation before relying on this snapshot."
    ),
}
_EMERGENCY_MEASURES_9A = {
    "duplicates": {},
    "missing": frozenset({"9A"}),
    "warning": (
        "This official Financial Emergency Measures in the Public Interest (No. 2) Act 2009 "
        "consolidated PDF is incomplete: section 9A ('Restriction on application of direction "
        "given by Minister') is listed in its contents but absent from the body. Its text has "
        "not been reconstructed. Check the original legislation for its text."
    ),
}
_PLANNING_105A = {
    "duplicates": {},
    "missing": frozenset({"105A"}),
    "printed": frozenset({"105A1"}),
    "warning": (
        "This official Planning and Development Act 2000 consolidated PDF prints the label of "
        "section 105A ('Appointment of chairperson on interim basis', repealed) as '105A1'. Its "
        "repealed placeholder is kept as printed, after section 105; section 105A cannot be "
        "located by its label in this source."
    ),
}
_CIVIL_LIABILITY_17A = {
    "duplicates": {"17A": 2},
    "missing": frozenset(),
    "warning": (
        "This official Civil Liability and Courts Act 2004 PDF prints two different sections "
        "numbered 17A ('Pre-action offers to settle clinical negligence claims' and 'Pre-action "
        "offers of settlement in clinical negligence claims'), inserted by separate amending "
        "Acts. Both entries and their labels are preserved as printed. A reference to section "
        "17A alone is ambiguous in this source."
    ),
}

_ANIMAL_HEALTH_69 = {
    "duplicates": {"69": 2},
    "missing": frozenset({"70"}),
    "warning": (
        "This official Animal Health and Welfare Act 2013 PDF prints section number 69 twice. "
        "The second entry, 'Regulations in relation to animal marts', is numbered 70 in the "
        "contents. Both body entries and their printed labels are preserved without "
        "renumbering. Section 71M's body omits its number; its boundary is identified by the "
        "contents and matching title without inserting a number into its body text. "
        "Check the official legislation before relying on these section numbers."
    ),
}
# The same defect in every later snapshot (2023-06-01 to 2025-12-29), each matched on
# 2026-10-19 by its own 69/70 entries and its unnumbered 71M, as pinned below.


_KNOWN_LABEL_DEFECTS = {
    "69987fceb7c4fbd8d7b5209f0f80bdee32739d2a0cbe1a61f62a4dd7826766c1": _CIVIL_REGISTRATION_30M,  # pragma: allowlist secret
    "3f40f0dd15295f18d710fa9f397d6cd8664095a5947fe377e1de803de8f670db": _GARDA_33E,  # pragma: allowlist secret
    # The same defects in later snapshots, matched on 2026-10-19 by the defect each raises.
    "0ae69d58bc9806a81c6abc4ae41325cbb67655de328632404c9ddd9ab37eec4d": _GARDA_33E,  # pragma: allowlist secret
    "364a307e7e5cca3572aa628719def5d7e4cc56d9238713f85ff7dd04d2480eaa": _GARDA_33E,  # pragma: allowlist secret
    "51b37169677025ddd9987450cab922610a715af978fa54a3e0772c1d58af3f05": _GARDA_33E,  # pragma: allowlist secret
    "872c0cd81106c247ab4a745a606b91bae26d4ec5b59225bee696c17de1b9f9c4": _GARDA_33E,  # pragma: allowlist secret
    "92a3126946496a7d1fdcd3f79bfe83220e41bfe7e40be2e186cb7bb607c56ba3": _GARDA_33E,  # pragma: allowlist secret
    "975bdd11a57d656c386408f53e6dd74f6217a8dbdf7cd4adc9141aaa573d241b": _GARDA_33E,  # pragma: allowlist secret
    "b07c90147701b2460627f054778d8aa704be5bfe103d2c38e62537a3d1b65b3d": _GARDA_33E,  # pragma: allowlist secret
    "c9d62bd9f7f074ff0d4be997d15bdc8f6081feb63caa24e4f59153548bcdad11": _GARDA_33E,  # pragma: allowlist secret
    "2258a2660883739a686cb2574747b20277e572ef4a6869f6c567dc2cec1ff0de": _REGISTRATION_OF_TITLE_124A,  # pragma: allowlist secret
    "327415c90475b0203f7bdf81e8f9f8637d779120f8307a1e22ac5cfab8c1fc6f": _REGISTRATION_OF_TITLE_124A,  # pragma: allowlist secret
    "c1aa425fd404bd7f5d0d1fd8f16f7722ca520cd1e96cdb8ceaa15854a99ffdbe": _REGISTRATION_OF_TITLE_124A,  # pragma: allowlist secret
    "a55241e60e2b3e7fbaaa70f95d0e0852de60010c08bb4acc28f7fbb81fb4c423": _COMPETITION_15AU,  # pragma: allowlist secret
    "7aaee19dc15d70c1f38be779905a7f8689daf7a61f6e7392df8983e168a97ac2": _EMERGENCY_MEASURES_9A,  # pragma: allowlist secret
    "414848ee8a8158ff5ca3d316f2d4b355872dacaaa43ff29601d965ddde498fc3": _PLANNING_105A,  # pragma: allowlist secret
    "53e561416195e572907c31d162faea79ea41353fbcbb81be9926bc3350a17d21": _PLANNING_105A,  # pragma: allowlist secret
    "a7be62112d38ffecde3b1e09c3c70e9d2ab13bce3d3f190e853b8a96fcc8769c": _PLANNING_105A,  # pragma: allowlist secret
    "b9b76cb50e52d467ac76be78cc02985cc5ccc930a3f819ea195e40c2e37fe31b": _PLANNING_105A,  # pragma: allowlist secret
    "cad7814f81a4184b3ef25bc0d9d2f28be7e0afd932228bdecf595b615777c647": _PLANNING_105A,  # pragma: allowlist secret
    "e411effc12b6193d93d652db6a973773a8eb7a45c4463db85267f4f52f03fb29": _PLANNING_105A,  # pragma: allowlist secret
    "f7a06c43f9d43836e72baab191bc9ca6e84ec7a55d2f7e0a06df1d9b6d4218a3": _PLANNING_105A,  # pragma: allowlist secret
    "ce91e09f561e2ddbb3cd361305c16c9f7c4467c5524c467ece83ba53ca8237ac": _CIVIL_REGISTRATION_30M,  # pragma: allowlist secret
    "5fd11cf8114193dad43f7456783e534e94f99f2d4645c3b7d1e24a967014d0b6": _CIVIL_LIABILITY_17A,  # pragma: allowlist secret
    "dbb963cf87485993227c9213345323a3d20a35e886e443db2fb413d252c6c7ff": _ANIMAL_HEALTH_69,  # pragma: allowlist secret
    "99607d467a9c960d555b24545769d06a6b8af43ad1b8f0bcf2cd805914cde7aa": _ANIMAL_HEALTH_69,  # pragma: allowlist secret
    "5e0ca07c6cb77d82e5e12af49aaf0a24d74e84ff382ed28c6d0d0d6986a1991e": _ANIMAL_HEALTH_69,  # pragma: allowlist secret
    "c84d4e4568125626ae40e43d15553c0400809368d1c5a3a182a788c0c1f6d8af": _ANIMAL_HEALTH_69,  # pragma: allowlist secret
    "616d038251cccd5eb0556d668a3d08489f7312fb72dcef45f2c68d61b5ce60a5": _ANIMAL_HEALTH_69,  # pragma: allowlist secret
    "6dd32ace5b956bc99d9d2364c003c36cd4460fc33e0c2ed62a6096d124abdc0e": _ANIMAL_HEALTH_69,  # pragma: allowlist secret
    "38dea8df7b99e3663e6add7b2652ebc5571afe0f9fbbdda782519c9d204f31d0": _ANIMAL_HEALTH_69,  # pragma: allowlist secret
    "29b4d19f893b9e6e46ea37c8d8b53e58200db5fa3d61f1df5ce47603d023b9b7": _ANIMAL_HEALTH_69,  # pragma: allowlist secret
    "c2d989bae87bfe6b92dad9538064636e2d48dca1c26f4f30b91618c8c28f63f2": _ANIMAL_HEALTH_69,  # pragma: allowlist secret
    "c10e76838c161e5757431f0591e3f48196b4b3e3a06ede35d7a2522fb6f1f27c": _ANIMAL_HEALTH_69,  # pragma: allowlist secret
    "f2b60c101fc7e850b1d19574649675b348ded9b0f14a0e785531dd9dfb6022d7": _ANIMAL_HEALTH_69,  # pragma: allowlist secret
}


# Only these inspected appendices use the playbook's image-omission policy on whole pages.
# Evidence: tests/fixtures/ie/pdf-scanned-appendices-evidence.json.
_KNOWN_SCANNED_APPENDICES = {
    # Criminal Justice (Mutual Recognition of Custodial Sentences) Act 2023: the Annex I
    # certificate of Framework Decision 2008/909/JHA is printed as four scanned pages.
    "b100a253b232b32e13d1c254b4e0ebe005fc7fa3477705e5fd3c3f2c74999348": (  # pragma: allowlist secret
        frozenset(range(94, 98))
    ),
    "6035778c7c01464c51791f87d68449e72fee7427ec1f02b1717f8c2950185a04": (  # pragma: allowlist secret
        frozenset(range(179, 185)) | frozenset(range(198, 208))
    ),
    "1fa4abf009589948ff0ce1889a62ae35e404fd9f55b46284e92293d323c3baea": frozenset({116, 117}),
    # Later Criminal Justice (Mutual Assistance) Act 2008 snapshots: the same two scanned forms.
    "3b63bb91f136622bf67641fffbb5c01e11eaded83e5fed7ee4e58769f8dd9bad": (  # pragma: allowlist secret
        frozenset(range(183, 189)) | frozenset(range(202, 212))
    ),
    "8fa52d1c03d1d32fb8def956170f9d341b324ae1d37aeb857d340554ef80e12d": (  # pragma: allowlist secret
        frozenset(range(183, 189)) | frozenset(range(202, 212))
    ),
    "99f468f282d6913064dd6d057dc075556644ced41f6784413960aea2100dfd8d": (  # pragma: allowlist secret
        frozenset(range(179, 185)) | frozenset(range(198, 208))
    ),
    "a678f5d878a1187d25e03dc0d97992c67ce78415430b4de51b9d72b09fb95194": (  # pragma: allowlist secret
        frozenset(range(185, 191)) | frozenset(range(204, 214))
    ),
    "c7acd91474658146d27e2cbb28186a68cf092c22020707ee3618e6aa41884650": (  # pragma: allowlist secret
        frozenset(range(183, 189)) | frozenset(range(202, 212))
    ),
    "cdf64e1a0f85f320caa2a4b48293f046c35c74ec9bcdebe8825c189e305e8fe1": (  # pragma: allowlist secret
        frozenset(range(197, 203)) | frozenset(range(216, 226))
    ),
    "e1ef94da2f7381c64e8b6b2df8d7e593618dc5423b019669509dd51e173086fd": (  # pragma: allowlist secret
        frozenset(range(197, 203)) | frozenset(range(216, 226))
    ),
    "e2b99062235d3333f88a53e45d9229418290dc83f96194654ad6e89f8f9c09ad": (  # pragma: allowlist secret
        frozenset(range(185, 191)) | frozenset(range(204, 214))
    ),
    "f3b9e6ecf12d4e1004eafb7f12eae255e216f0b49e27004476ac50917c155b1d": (  # pragma: allowlist secret
        frozenset(range(197, 203)) | frozenset(range(216, 226))
    ),
}


def source_warning(data: bytes) -> str | None:
    """Return the verified limitation for an exact official PDF."""
    if pages := _KNOWN_SCANNED_APPENDICES.get(sha256(data).hexdigest()):
        return (
            "This official consolidated PDF contains scanned legal forms or tables on physical "
            f"PDF pages {', '.join(str(page) for page in sorted(pages))}. "
            "Their images are marked [image omitted] in source order and counted, but their "
            "contents are not transcribed. Consult the original PDF for these appendices."
        )
    if defect := _KNOWN_LABEL_DEFECTS.get(sha256(data).hexdigest()):
        return defect["warning"]
    if sha256(data).hexdigest() in _KNOWN_SOURCE_OMISSIONS:
        return (
            "This official Companies Act 2014 consolidated PDF is incomplete: section 1384A "
            "is listed in its contents but absent from the body. Its text has not been "
            "reconstructed. Check the original amending legislation before relying on this snapshot."
        )
    if conflict := _KNOWN_CUTOFF_CONFLICTS.get(sha256(data).hexdigest()):
        cover, older = conflict
        return (
            "This official consolidated PDF has conflicting revision dates: its front cover "
            f"and the LRC catalogue state {cover}, while internal headings state {older}. "
            f"This snapshot uses {cover}, following the cover and catalogue. "
            "Check the official source before relying on its revision date."
        )
    if missing_label := _KNOWN_UNNUMBERED_SECTIONS.get(sha256(data).hexdigest()):
        number, title, _ = missing_label
        return (
            f"This official consolidated PDF omits section {number}'s number from its body. "
            f"The section boundary is identified by its contents entry and matching title, '{title}'. "
            "The source body text is preserved without inserting a number into it."
        )
    return None


class _Contents(set):
    """The contents' section labels; ``listed`` counts a label the contents repeats."""

    def __init__(self):
        super().__init__()
        self.listed: Counter[str] = Counter()


class UnsupportedPDF(ValueError):
    """The PDF cannot be converted without risking lost or misassigned text."""


@dataclass
class _Line:
    chars: list[dict]
    page: int
    links: list[dict]

    @cached_property
    def text(self) -> str:
        return extract_text(self.chars, x_tolerance=0.75, y_tolerance=3).strip()

    @cached_property
    def top(self) -> float:
        return min(c["top"] for c in self.chars)

    @cached_property
    def bottom(self) -> float:
        return max(c["bottom"] for c in self.chars)

    @cached_property
    def x0(self) -> float:
        return min(c["x0"] for c in self.chars)

    @cached_property
    def x1(self) -> float:
        return max(c["x1"] for c in self.chars)


def _inline(line: _Line, *, emphasis: bool = True) -> str:
    """Keep font emphasis, superscripts, small caps and explicit URI links."""
    chars = sorted(line.chars, key=lambda c: c["x0"])
    size = Counter(round(c["size"], 1) for c in chars).most_common(1)[0][0]
    baseline = max(c["bottom"] for c in chars)
    largest = max(c["size"] for c in chars)

    def style(char):
        font = char["fontname"]
        sup = char["size"] < size * 0.8 and char["bottom"] < baseline - 2
        href = next(
            (
                link["uri"]
                for link in line.links
                if link["x0"] - 0.5 <= (char["x0"] + char["x1"]) / 2 <= link["x1"] + 0.5
                and link["top"] - 1 <= (char["top"] + char["bottom"]) / 2 <= link["bottom"] + 1
                and urlsplit(link.get("uri") or "").scheme in ("http", "https")
            ),
            "",
        )
        return "Bold" in font, "Italic" in font, sup, href

    result = []
    previous = None
    for (bold, italic, sup, href), run in groupby(chars, key=style):
        text = ""
        for char in run:
            if (
                previous
                and char["x0"] - previous["x1"] > 0.75
                and char["text"] not in ",;:.!?)]}’”"
            ):
                text += " "
            value = char["text"]
            # XEP renders small caps as smaller upper-case glyphs on the baseline.
            if not sup and char["size"] < largest * 0.8 and value.isalpha():
                value = value.lower()
            text += value
            previous = char
        text = strip_control(text)
        body = text.strip()
        if not body:
            result.append(text)
            continue
        if emphasis:
            if sup:
                body = _escaped_sign(body)  # still the printed text: no marks yet
            if bold and body not in ("[", "]"):
                body = f"**{body}**"
            if italic:
                body = f"*{body}*"
            if sup:
                body = f"^{body}"
            if href:
                body = f"[{body}]({href})"
        result.append(
            (" " if text[:1].isspace() else "") + body + (" " if text[-1:].isspace() else "")
        )
    return "".join(result).strip()


def _with_printed(pattern: re.Pattern, printed: frozenset[str]) -> re.Pattern:
    """The section pattern, also accepting one file's verified misprinted labels."""
    if not printed:
        return pattern
    labels = "|".join(re.escape(label) for label in sorted(printed, key=len, reverse=True))
    return re.compile(pattern.pattern.replace(r"(\d+[A-Z]*)", rf"({labels}|\d+[A-Z]*)", 1))


def _section_match(line: _Line, *, allow_plain: bool = False, pattern=_SECTION):
    """Captioned labels can be plain; an italic citation can also wrap as ``366.``."""
    match = pattern.match(line.text)
    if match is None:
        return None
    chars = sorted(line.chars, key=lambda char: char["x0"])
    number = pattern.match("".join(char["text"] for char in chars))
    if number is None:
        return None
    offset = 0
    for char in chars:
        if number.start(1) <= offset < number.end(1) and (
            "Italic" in char["fontname"] or (not allow_plain and "Bold" not in char["fontname"])
        ):
            return None
        offset += len(char["text"])
        if offset >= number.end(1):
            break
    return match


def _join(left: str, right: str) -> str:
    # Only an explicit discretionary hyphen can be removed without guessing
    # whether the source word was a hyphenated compound.
    if left.endswith("\u00ad"):
        return left[:-1] + right
    if left.endswith("-") and right[:1].islower():
        return left + right
    text = left + (" " if left else "") + right
    # A URI or emphasis run can span physical lines. Rejoin only adjacent
    # identical markup, preserving all of the underlying source characters.
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\) \[([^\]]+)\]\(\2\)", r"[\1 \3](\2)", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\* \*([^*]+)\*(?!\*)", r"*\1 \2*", text)
    text = re.sub(r"\*\*([^*]+)\*\* \*\*([^*]+)\*\*", r"**\1 \2**", text)
    return text


def _inside(char: dict, box: tuple) -> bool:
    return (
        box[0] - 0.1 <= (char["x0"] + char["x1"]) / 2 <= box[2] + 0.1
        and box[1] - 0.1 <= (char["top"] + char["bottom"]) / 2 <= box[3] + 0.1
    )


def _table(page, table, number: int, *, lenient: bool = False) -> str:
    """Recover ruled cells and paragraph-separated rows within open columns."""
    element = etree.Element("table")
    for row_index, row in enumerate(table.rows):
        cells = row.cells
        boxes = [box for box in cells if box is not None]
        if not boxes:
            continue
        top, bottom = min(b[1] for b in boxes), max(b[3] for b in boxes)
        first = next(box for box in cells if box is not None)
        first_lines = page.crop(first).extract_text_lines(x_tolerance=0.75)
        # Numbered column labels belong to one ruled header, even when they sit below wrapped titles.
        numbered_header = (
            row_index == 0
            and first_lines
            and first_lines[-1]["text"] == "(1)"
            and all(
                box is not None
                and (page.crop(box).extract_text(x_tolerance=0.75) or "").endswith(f"({column})")
                for column, box in enumerate(cells, 1)
            )
        )
        # Many statutory tables rule columns, but omit horizontal row borders.
        # A paragraph break in the first column then identifies each source row.
        cuts = [top]
        previous = None
        for line in first_lines:
            if not numbered_header and previous and line["top"] - previous["bottom"] > 4:
                cuts.append(line["top"] - 0.5)
            previous = line
        cuts.append(bottom)
        for cut in cuts[1:-1]:
            if any(
                _inside(c, table.bbox) and c["top"] + 0.1 < cut < c["bottom"] - 0.1
                for c in page.chars
            ):
                if not lenient:
                    raise UnsupportedPDF("Ambiguous row boundaries in Revised Act PDF table")
                # Keep the ruled source row whole rather than guess where its rows split.
                cuts = [top, bottom]
                break
        for start, end in zip(cuts, cuts[1:], strict=False):
            tr = etree.SubElement(element, "tr")
            for box in cells:
                td = etree.SubElement(tr, "td")
                if box is None:
                    continue
                cropped = page.crop((box[0], start, box[2], end))
                lines = [
                    _Line(line["chars"], number, page.hyperlinks)
                    for line in cropped.extract_text_lines(x_tolerance=0.75)
                ]
                td.text = " ".join(_inline(line).replace("|", "\\|") for line in lines)
    return render_table(element, lambda cell: cell.text or "")


def _read(
    data: bytes, *, lenient: bool = False
) -> tuple[list[_Line | Paragraph], date | None, set[str]]:
    events: list[_Line | Paragraph] = []
    updated = None
    started = False
    contents = False
    expected = _Contents()
    verified_cutoff = _KNOWN_CUTOFF_CONFLICTS.get(sha256(data).hexdigest())
    scanned_appendices = _KNOWN_SCANNED_APPENDICES.get(sha256(data).hexdigest(), frozenset())
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for number, page in enumerate(pdf.pages):
            lines = page.extract_text_lines(x_tolerance=0.75)
            plain = [line["text"] for line in lines]
            if (
                started
                and (
                    "About this Revised Act" in plain
                    or "Introduction" in plain
                    and any(text.startswith("This Revised Act presents the text") for text in plain)
                )
                and plain
                and re.match(r"Number\s*\d+\s*of\s*\d{4}\b", plain[0])
            ):
                break
            start = 0
            if not started:
                for i, text in enumerate(plain):
                    match = _DATE.search(text)
                    if match:
                        try:
                            found = date(int(match[3]), _month_number(match[2]), int(match[1]))
                        except ValueError as exc:
                            raise UnsupportedPDF("Invalid Revised Act PDF cover date") from exc
                        if updated and found != updated:
                            if not verified_cutoff or {updated, found} != set(verified_cutoff):
                                raise UnsupportedPDF("Conflicting Revised Act PDF cover dates")
                            updated = verified_cutoff[0]
                        else:
                            updated = found
                    if re.match(r"^(?:F\d+\[)?AN ACT\b", text, re.I):
                        start = i
                        started = True
                        break
                    if text in ("ARRANGEMENT OF SECTIONS", "CONTENTS"):
                        contents = True
                    if text == "ACTS REFERRED TO":
                        contents = False
                    if contents and (match := re.match(r"^(\d+[A-Z]*)\.\s+", text)):
                        next_number = (
                            max((int(re.match(r"\d+", n)[0]) for n in expected), default=0) + 1
                        )
                        if int(re.match(r"\d+", match[1])[0]) <= next_number:
                            expected.add(match[1])
                            expected.listed[match[1]] += 1
                if not started:
                    page.close()
                    continue
            body_top = lines[start]["top"] if start else 78
            active = [
                c for c in page.chars if c["top"] >= body_top - 0.1 and c["top"] < page.height - 36
            ]
            if any(
                "(cid:" in c["text"] or "\ufffd" in c["text"] or not c["upright"] for c in active
            ):
                raise UnsupportedPDF(
                    f"Unreadable or rotated Revised Act PDF text on page {number + 1}"
                )
            body_images = [
                image
                for image in page.images
                if image["bottom"] > body_top and image["top"] < page.height - 36
            ]
            if body_images and not active and number + 1 not in scanned_appendices:
                raise UnsupportedPDF(f"Image-only Revised Act PDF body page: {number + 1}")
            if not active and not body_images:
                # A separator may contain only XEP's white page backgrounds and running headers.
                if any(
                    shape["bottom"] > body_top
                    and shape["top"] < page.height - 36
                    and (
                        shape.get("stroke")
                        or shape.get("fill")
                        and shape.get("non_stroking_color") not in (1, (1, 1, 1))
                    )
                    for shape in page.curves + page.lines + page.rects
                ):
                    raise UnsupportedPDF(f"Empty page inside Revised Act PDF body: {number + 1}")
                page.close()
                continue
            if any(
                text in ("Annotations", "Amendments:", "Modifications (not altering text):")
                for text in plain
            ):
                raise UnsupportedPDF(
                    "Annotated Revised Act PDF supplied; an unannotated snapshot is required"
                )
            # White background rectangles describe XEP's page region, not cells.
            table_page = page.filter(lambda o: o["object_type"] != "rect" or o.get("stroke"))
            tables = [table for table in table_page.find_tables() if table.bbox[1] >= body_top]
            # A raster figure is omitted in source position under the country
            # playbook; readable text on the same page must still be retained.
            # A paragraph marker also remains inside any enclosing legal quote.
            page_events = [
                (image["top"], Paragraph("parrafo", "[image omitted]")) for image in body_images
            ]
            for table in tables:
                text = _table(page, table, number, lenient=lenient)
                if not text:
                    raise UnsupportedPDF("Empty Revised Act PDF table")
                page_events.append((table.bbox[1], Paragraph("table", text)))
            active_ids = {id(c) for c in active}
            for item in lines[start:]:
                chars = [
                    c
                    for c in item["chars"]
                    if id(c) in active_ids and not any(_inside(c, t.bbox) for t in tables)
                ]
                if chars:
                    line = _Line(chars, number, page.hyperlinks)
                    if line.text in ("ACTS REFERRED TO", "About this Revised Act"):
                        events.extend(
                            event
                            for top, event in sorted(page_events, key=lambda event: event[0])
                            if top < line.top
                        )
                        page.close()
                        return events, updated, expected
                    page_events.append((line.top, line))
            events.extend(event for _, event in sorted(page_events, key=lambda event: event[0]))
            page.close()
    if not started or not events:
        raise UnsupportedPDF("Revised Act PDF has no readable legislative body")
    return events, updated, expected


def parse_revised_pdf(data: bytes) -> tuple[list[Paragraph], date | None]:
    """Serialize glyph-heavy extraction while fetch workers can continue their I/O.

    This bounds concurrent PDF glyph collections, not the surrounding envelopes.
    """
    with _PDF_PARSE_LOCK:
        try:
            return _parse_revised_pdf(data)
        except UnsupportedPDF as strict:
            # Every file a reading accepts keeps its exact output: each more lenient one
            # only runs where every stricter one could not account for all the text, so
            # adding a level changes nothing a previous level published.
            for level in (1, 2):
                try:
                    return _parse_revised_pdf(data, lenient=level)
                except UnsupportedPDF:
                    continue
            raise strict from None


def _closing_quote_delta(text: str) -> int:
    """Quote depth where a closing quote is printed as an opening one after a term.

    "“Credit Reviewer“ has the meaning", "of “credit servicing“ in section 28"
    (2017/22): the shared rule only repairs "“term“ means/includes". Level 2 only.
    """
    return _quote_delta(re.sub(r"(“[^“”\n]*[^\s“”])“(?=[\s,.;:)]|$)", r"\1”", text))


def _lenient_margin_text(text: str) -> bool:
    """Marginal text that is not a caption: notes on a derivation, or legal text."""
    return bool(
        # "[Hague Convention, …]" or '[Cf. "dwelling" in 1960 …]' wrapped over lines.
        re.match(r"^\[(?:Cf\. [\"“]|Hague Conven)", text, re.I)
        # Consolidation sources by abbreviation: "[VATA s. 44]", "[… and FA 2010 s. 165(4)]".
        or re.fullmatch(
            r"\[[A-Z]{2,}[A-Za-z()]*\s+(?:[Ss]s?|[Ss]ch|[Aa]rt|[Pp]ara|[Rr]eg)\.\s*\d[^\[\]]*\]",
            text,
        )
        # Parenthesised derivation notes: "(New)", "(cf. 1857, s.281)", "(33/1963, s. 345 (8))".
        or (
            re.fullmatch(r"(?:\((?:[^()]|\([^()]*\))*\)\.?\s*)+", text)
            and re.search(r"\bNew\b|\b(?:1[6-9]|20)\d\d\b", text)
        )
        # A table cell in the margin column ("(5) A special order made…", "6.—(1) Upon an
        # application…") or the caption of a quoted section ("“ Supervisory authority.").
        or re.match(r"^(?:\((?:\d+[A-Z]*|[a-z]{1,4})\)\s|\d+[A-Z]*\.—|“)", text)
    )


def _parse_revised_pdf(data: bytes, *, lenient: int = 0) -> tuple[list[Paragraph], date | None]:
    """Extract the actual dated legal text, preserving marginal section titles."""
    events, updated, expected = _read(data, lenient=lenient)
    missing_label = _KNOWN_UNNUMBERED_SECTIONS.get(sha256(data).hexdigest())
    label_defect = _KNOWN_LABEL_DEFECTS.get(sha256(data).hexdigest(), {})
    allowed_duplicates = label_defect.get("duplicates", {})
    # A label printed wrong is kept as printed; the defect's warning says so.
    printed = label_defect.get("printed", frozenset())
    section = _with_printed(_SECTION, printed)
    footnotes = []
    body_events = []
    previous_note = None
    for event in events:
        if isinstance(event, _Line) and event.top > 700 and max(c["size"] for c in event.chars) < 9:
            match = re.match(r"^(\d+)\s+(.+)", event.text)
            if (
                match
                and min(c["size"] for c in event.chars) < max(c["size"] for c in event.chars) * 0.8
            ):
                rendered = re.sub(r"^\^?\d+\s*", "", _inline(event))
                footnotes.append(Paragraph("parrafo", f"[^{match[1]}]: {rendered}"))
                previous_note = event
                continue
            if (
                previous_note
                and previous_note.page == event.page
                and event.top - previous_note.bottom < 5
            ):
                footnotes[-1] = Paragraph("parrafo", _join(footnotes[-1].text, _inline(event)))
                previous_note = event
                continue
        previous_note = None
        body_events.append(event)
    events = body_events
    first = next(
        (
            event
            for event in events
            if isinstance(event, _Line) and re.search(r"\b1\.(?=[—\s(\[]|F\d+\[)", event.text)
        ),
        None,
    )
    if first is None:
        raise UnsupportedPDF("Revised Act PDF has no first section")
    first_label = None
    for char in first.chars:
        if char["text"] != "1" or "Italic" in char["fontname"]:
            continue
        candidate = _Line(
            [c for c in first.chars if c["x0"] >= char["x0"]], first.page, first.links
        )
        if (match := _section_match(candidate, allow_plain=True, pattern=section)) and match[
            1
        ] == "1":
            first_label = candidate
            break
    if first_label is None:
        raise UnsupportedPDF("Revised Act PDF has no first section label")
    marginal = first.x0 < first_label.x0 - 30
    margin_edge = first_label.x0 - 8.74
    first_index = events.index(first)
    first_title = events[first_index - 1] if first_index else None
    title_x = (
        first_title.x0
        if isinstance(first_title, _Line)
        and first_title.page == first.page
        and first.top - first_title.bottom < 25
        and sum("Bold" in c["fontname"] for c in first_title.chars) / len(first_title.chars) > 0.8
        else first_label.x0
    )
    lines: list[_Line | Paragraph] = []
    margins: list[_Line] = []
    captions: list[list[_Line]] = []
    for event in events:
        if not isinstance(event, _Line) or not marginal or event.x0 >= first_label.x0 - 52.64:
            lines.append(event)
            continue
        # XEP's caption column moves with the body margin; smaller glyphs can hang into the gutter.
        caption_fonts = {
            (round(c["top"], 2), round(c["bottom"], 2), c["fontname"])
            for c in event.chars
            if c["x0"] < first_label.x0 - 52.64
        }
        side = [
            c
            for c in event.chars
            if (c["x0"] < margin_edge or (c["x0"] < margin_edge + 4 and c["size"] < 9.5))
            and (
                not all("Bold" in font for _, _, font in caption_fonts)
                or (round(c["top"], 2), round(c["bottom"], 2), c["fontname"]) in caption_fonts
            )
        ]
        body = [c for c in event.chars if c not in side]
        caption_rows = {
            (round(c["top"], 2), round(c["bottom"], 2))
            for c in event.chars
            if c["x0"] < first_label.x0 - 52.64
        }
        recovered_body = [
            c
            for c in event.chars
            if (round(c["top"], 2), round(c["bottom"], 2)) not in caption_rows
        ]
        if recovered_body:
            recovered = _Line(recovered_body, event.page, event.links)
            if abs(recovered.x0 - first_label.x0) < 27 and _section_match(
                recovered, pattern=section
            ):
                body = recovered_body
                side = [c for c in event.chars if c not in body]
        if (
            side
            and body
            and _section_match(_Line(body, event.page, event.links), pattern=section) is None
        ):
            # Some XEP captions overlap the opening number horizontally. Their
            # glyph baselines remain distinct (even when the font sizes match).
            # Extend a caption only when this recovers a bold primary label at
            # the body column; all recovered glyphs remain in the source title.
            caption_rows = {
                (round(c["top"], 2), round(c["bottom"], 2), c["fontname"]) for c in side
            }
            overflow = [
                c
                for c in body
                if (round(c["top"], 2), round(c["bottom"], 2), c["fontname"]) in caption_rows
            ]
            candidate = [c for c in body if c not in overflow]
            if (
                overflow
                and all(c["x0"] < first_label.x0 + 10 for c in overflow)
                and (not candidate or min(c["x0"] for c in candidate) >= first_label.x0 - 10)
            ):
                side.extend(overflow)
                body = candidate
            elif candidate:
                recovered = _Line(candidate, event.page, event.links)
                if abs(recovered.x0 - first_label.x0) < 10 and _section_match(
                    recovered, pattern=section
                ):
                    side.extend(overflow)
                    body = candidate
        if side:
            side_line = _Line(side, event.page, event.links)
            # Classify complete captions below: a wrapped title can itself
            # contain a line such as "section 1517", not a schedule locator.
            margins.append(side_line)
        if body:
            lines.append(_Line(body, event.page, event.links))
    if marginal:
        margin_x = first.x0
        preserved = []
        i = 0
        while i < len(margins):
            start = margins[i]
            group = [start]
            i += 1
            while (
                i < len(margins)
                and margins[i].page == start.page
                and -2 < margins[i].top - group[-1].bottom < 4
            ):
                group.append(margins[i])
                i += 1
            # A schedule locator can wrap through a definition or subsection.
            # Inserted legislation can also have its own indented marginal
            # captions; they are quoted content, never primary section titles.
            locator = re.match(
                r"^(?:F\d+\[)?(?:(?:Sub)?Sections?\s*(?:\d|l\b|\(\d)|Paragraph\s+\d)",
                " ".join(line.text for line in group),
                re.I,
            ) and not any(
                isinstance(line, _Line)
                and line.page == start.page
                and abs(line.top - start.top) < 6
                and _section_match(line, pattern=section)
                for line in lines
            )
            # Companies captions indent their first line by 8.64pt. A quoted
            # marginal column is displaced by 25.92pt (Credit Union Act 2012).
            aligned_label = any(
                isinstance(line, _Line)
                and line.page == start.page
                and abs(line.top - start.top) < 6
                and abs(line.x0 - first_label.x0) < 20
                and _section_match(line, pattern=section)
                for line in lines
            )
            if (
                locator
                or re.match(
                    r"^\[(?:New\b|(?:Cf\. )?\d{4}\b|R\.S\.C\.|Restates\b|Enlarges powers\b|"
                    r"See \d{4}\b|Hague Conven|(?:cf\. )?Art\. \d+|"
                    r"\[?[A-Z][A-Z(). ]{0,15} [12]\d{3}\b)",
                    start.text,
                    re.I,
                )
                or re.match(r"^(?:S\.R\. & O\.|S\.I\.) No\. \d+", start.text)
                or (min(line.x0 for line in group) > margin_x + 12 and not aligned_label)
                or (lenient and _lenient_margin_text(" ".join(line.text for line in group)))
            ):
                text = ""
                for line in group:
                    text = _join(text, _inline(line))
                position = next(
                    (
                        n
                        for n, line in enumerate(lines)
                        if isinstance(line, _Line)
                        and (line.page, line.top) >= (start.page, start.top)
                    ),
                    len(lines),
                )
                lines.insert(position, Paragraph("parrafo", text))
            else:
                preserved.extend(group)
                captions.append(group)
        margins = preserved

    paragraphs: list[Paragraph] = []
    pending = ""
    pending_title = False
    pending_x = None
    previous: _Line | None = None
    seen: Counter[str] = Counter()
    schedule = False
    schedule_start = None
    primary_x = first_label.x0
    division_center = None
    quote_depth = 0

    def flush():
        nonlocal pending, pending_title
        if pending:
            paragraphs.append(Paragraph("parrafo", pending))
            pending = ""
        pending_title = False

    i = 0
    while i < len(lines):
        item = lines[i]
        i += 1
        quoted = quote_depth > 0
        if quote_depth or re.match(r"^(?:F\d+\[)?“", item.text):
            delta = _closing_quote_delta if lenient > 1 else _quote_delta
            quote_depth = max(0, quote_depth + delta(item.text))
        if isinstance(item, Paragraph):
            flush()
            paragraphs.append(item)
            previous = None
            continue
        if lenient > 1 and marginal and not schedule:
            # Level 2: a subsection's own marginal title, beside its "(4) …" line
            # (Statute of Limitations 1957 s. 2(4)-(7)), kept whole and in place as
            # source text. Any other unassigned marginal text still rejects the file.
            pool = sorted(margins, key=lambda m: (m.page, m.top))
            starts = [
                i
                for i, line in enumerate(pool)
                if not i
                or line.page != pool[i - 1].page
                or not -2 < line.top - pool[i - 1].bottom < 4
            ]
            kept = []
            for at, end_at in zip(starts, [*starts[1:], len(pool)][: len(starts)], strict=True):
                group = pool[at:end_at]
                text = " ".join(line.text for line in group)
                subsection = (
                    group[0].page == item.page
                    and abs(group[0].top - item.top) < 6
                    and re.match(r"^\(\w{1,4}\)\s", item.text)
                    and text.endswith(".")
                    and not re.match(r"^[\d(]", text)
                )
                if subsection:
                    kept.append(group)
            if kept:
                flush()
                for group in kept:
                    paragraphs.append(Paragraph("parrafo", " ".join(map(_inline, group))))
                taken = [line for group in kept for line in group]
                margins = [m for m in margins if m not in taken]
                captions = [c for c in captions if not any(m in taken for m in c)]
        if schedule:
            # Schedule captions describe their own clauses, never primary Act sections.
            remaining = [m for m in margins if (m.page, m.top) >= schedule_start]
            while remaining and (remaining[0].page, remaining[0].top) <= (item.page, item.top + 6):
                group = [remaining.pop(0)]
                while (
                    remaining
                    and remaining[0].page == group[-1].page
                    and -2 < remaining[0].top - group[-1].bottom < 4
                ):
                    group.append(remaining.pop(0))
                margins = [m for m in margins if m not in group]
                flush()
                paragraphs.append(Paragraph("parrafo", " ".join(_inline(m) for m in group)))
        text = item.text
        division = _DIVISION.fullmatch(text) if not quoted else None
        if division and division[1].upper() == "CHAPTER" and division_center is not None:
            if item.text.isupper() and abs((item.x0 + item.x1) / 2 - division_center) > 15:
                division = None
        if division:
            flush()
            kind = division[1].upper()
            division_center = (item.x0 + item.x1) / 2
            if kind == "SCHEDULE" and not schedule:
                schedule = True
                schedule_start = (item.page, item.top)
            heading = _inline(item, emphasis=False)
            # A division title is centered and may wrap, or begin on the next
            # page. A later centered paragraph is a subheading, not its title.
            last_title = None
            while i < len(lines) and isinstance(lines[i], _Line):
                following = lines[i]
                if (
                    abs((following.x0 + following.x1) / 2 - division_center) > 35
                    or _SECTION.match(following.text)
                    or _DIVISION.fullmatch(following.text)
                    or sum("Bold" in c["fontname"] for c in following.chars) / len(following.chars)
                    > 0.8
                    or (
                        last_title is not None
                        and (
                            following.page != last_title.page
                            or following.top - last_title.bottom > 5
                        )
                    )
                ):
                    break
                heading = _join(heading, _inline(following, emphasis=False))
                last_title = following
                i += 1
            paragraphs.append(
                Paragraph("capitulo_tit" if kind == "CHAPTER" else "titulo_tit", heading)
            )
            previous = None
            continue
        match = _section_match(
            item,
            allow_plain=marginal and abs(item.x0 - primary_x) < 10,
            pattern=_with_printed(_NESTED_SECTION if lenient else _SECTION, printed),
        )
        if lenient > 1 and match is None and marginal:
            dashed = _section_match(
                item, allow_plain=abs(item.x0 - primary_x) < 10, pattern=_DASHED_SECTION
            )
            match = dashed if dashed and dashed[1] in expected and dashed[1] not in seen else None
        caption = (
            next(
                (
                    group
                    for group in captions
                    if group[0].page == item.page
                    and (
                        abs(group[0].top - item.top) < 6
                        or (abs(item.x0 - primary_x) < 2 and 0 < group[0].top - item.top < 16)
                    )
                ),
                None,
            )
            # A three-line caption centred on its label starts one line above it.
            or lenient
            and next(
                (
                    group
                    for group in captions
                    if group[0].page == item.page
                    and abs(item.x0 - primary_x) < 2
                    and -12 < group[0].top - item.top < 0
                    and group[-1].bottom >= item.top
                ),
                None,
            )
            or []
            if (match or missing_label) and not schedule
            else []
        )
        if (
            match is None
            and missing_label
            and text == missing_label[2]
            and missing_label[0] in expected
            and (
                pending_title
                and re.sub(r"\*+", "", pending) == missing_label[1]
                or " ".join(_inline(m, emphasis=False) for m in caption) == missing_label[1]
            )
        ):
            match = _SECTION.match(f"{missing_label[0]}.")
        marginal_title = bool(caption)
        # A primary marginal caption ends a preceding quote even when the source omits its delimiter.
        if match and marginal_title:
            quote_depth = 0
        primary = match and not schedule and (not quoted or marginal_title)
        aligned_title = False
        if marginal:
            # A compound opening label can hang farther right. Some otherwise
            # marginal PDFs also put individual bold titles above the text.
            title_above = (
                previous is not None
                and previous.page == item.page
                and pending_title
                and pending
                and abs(item.x0 - primary_x) < 10
                and item.top - previous.bottom < 25
            )
            # A missing caption does not erase an aligned bold label listed in the contents.
            uncaptioned_label = (
                match
                and match[1] in expected
                and abs(item.x0 - primary_x) < 2
                and _section_match(item, pattern=section)
            )
            primary = primary and (marginal_title or title_above or uncaptioned_label)
        else:
            # Source labels can shift by two paragraph indents beneath an aligned title.
            indented_label = (
                previous is not None
                and previous.page == item.page
                and pending_title
                and pending
                and pending_x is not None
                and (
                    abs(pending_x - title_x) < 2
                    or (abs(item.x0 - primary_x) < 10 and abs(pending_x - title_x) < 14)
                )
                and abs(item.x0 - title_x) < 27
                and (not expected or match and match[1] in expected)
                and item.top - previous.bottom < 25
            )
            # Level 2: the next section the contents lists, under its title, where the
            # source set that title in roman at the title column (Data Protection Act
            # 2018 s. 137), or where an amendment's annotation mark hangs the inserted
            # section out of the columns (DNA Database Act 2014 s. 99: title and label
            # both left; 2021/50 s. 33B: title left, label one indent in).
            aligned_title = bool(
                lenient > 1
                and match
                and previous is not None
                and previous.page == item.page
                and pending
                and len(pending) < 150
                and item.top - previous.bottom < 25
                and match[1] in expected
                and match[1] not in seen
                and int(re.match(r"\d+", match[1])[0])
                >= max((int(re.match(r"\d+", n)[0]) for n in seen), default=0)
                and (
                    not pending_title
                    and abs(previous.x0 - title_x) < 2
                    and abs(item.x0 - title_x) < 2
                    or re.match(r"^F\d+\**\[", pending)
                    and (abs(item.x0 - previous.x0) < 2 or abs(item.x0 - primary_x) < 14)
                )
            )
            primary = primary and (abs(item.x0 - primary_x) < 2 or indented_label or aligned_title)
        if (
            lenient
            and match
            and quoted
            and not primary
            and not schedule
            and abs(item.x0 - primary_x) < 2
            and previous is not None
            and previous.page == item.page
            and pending_title
            and pending
            and item.top - previous.bottom < 25
            and match[1] in expected
            and match[1] not in seen
            and int(re.match(r"\d+", match[1])[0])
            >= max((int(re.match(r"\d+", n)[0]) for n in seen), default=0)
        ):
            # A bold title over the next section listed in the contents ends a quote the
            # source left open ("“ ‘Act of 2010’" in the 2015 Children and Family
            # Relationships Act), as a primary marginal caption already does.
            primary = match
            quote_depth = 0
        if primary:
            number = match[1]
            # Leniently, a number the contents lists twice is two sections: amending
            # Acts can insert the same number twice (two sections 144A in 2021/50).
            listed = getattr(expected, "listed", {}).get(number, 1) if lenient > 1 else 1
            if seen[number] >= max(allowed_duplicates.get(number, 1), listed):
                raise UnsupportedPDF(f"Duplicate primary section {number} in Revised Act PDF")
            seen[number] += 1
            title = ""
            if marginal_title:
                # Wrapped caption lines cannot become headings for quoted or numbered body text.
                title = " ".join(_inline(m, emphasis=False) for m in caption)
                margins = [m for m in margins if m not in caption]
                captions.remove(caption)
            else:
                # The preceding bold title was buffered as a paragraph.
                if (
                    previous
                    and previous.page == item.page
                    and (pending_title or aligned_title)
                    and pending
                ):
                    title, pending = re.sub(r"\*+", "", pending), ""
            flush()
            paragraphs.append(
                Paragraph("articulo", f"{number}. **{title}**" if title else f"{number}.")
            )
            previous = None
        new_paragraph = (
            previous is None
            or (previous.page == item.page and item.top - previous.bottom > 5)
            or (
                previous.page != item.page
                and (
                    re.match(r"^(?:F\d+\[)?[“\"(]", text)
                    or previous.x1 < 515
                    or sum("Bold" in c["fontname"] for c in item.chars) / len(item.chars) > 0.8
                )
            )
        )
        if new_paragraph:
            flush()
        if not pending:
            pending_title = sum("Bold" in c["fontname"] for c in item.chars) / len(item.chars) > 0.8
            pending_x = item.x0
            if pending_title and abs(pending_x - title_x) >= 2 and re.match(r"^F\d+\[", text):
                # An annotation marker may hang left of an otherwise aligned title.
                title_start = min(
                    (
                        c["x0"]
                        for c in item.chars
                        if "Bold" in c["fontname"] and c["text"].isalpha()
                    ),
                    default=pending_x,
                )
                pending_x = min(pending_x, title_start, key=lambda x: abs(x - title_x))
        pending = _join(pending, _inline(item))
        previous = item
    flush()
    missing = expected - seen.keys()
    allowed_missing = label_defect.get(
        "missing", _KNOWN_SOURCE_OMISSIONS.get(sha256(data).hexdigest())
    )
    if missing and missing != allowed_missing:
        raise UnsupportedPDF(
            f"Revised Act PDF is missing sections listed in its contents: {', '.join(sorted(missing))}"
        )
    if any(seen[number] != count for number, count in allowed_duplicates.items()):
        raise UnsupportedPDF("Verified duplicate section entries were not fully preserved")
    if not seen:
        raise UnsupportedPDF("Revised Act PDF has no legal sections")
    if margins:
        # Schedule cross-references are legal text, unlike running headers.
        # An orphan marginal section title indicates a structural extraction error.
        if any(
            not re.fullmatch(r"Sections?\s+\d+[A-Z]*(?:\s*(?:,|and)\s*\d+[A-Z]*)*\.?", m.text, re.I)
            for m in margins
        ):
            raise UnsupportedPDF("Unassigned marginal text in Revised Act PDF")
        paragraphs.extend(Paragraph("parrafo", _inline(m)) for m in margins)
    if footnotes:
        identifiers = {re.match(r"\[\^(\d+)\]", p.text)[1] for p in footnotes}
        paragraphs = [
            Paragraph(
                p.css_class,
                re.sub(
                    r"\^(\d+)\b", lambda m: f"[^{m[1]}]" if m[1] in identifiers else m[0], p.text
                ),
            )
            for p in paragraphs
        ]
        paragraphs.append(Paragraph("h2", "Footnotes"))
        paragraphs.extend(footnotes)
    return _legal_format(
        paragraphs, quote_delta=_closing_quote_delta if lenient > 1 else _quote_delta
    ), updated
