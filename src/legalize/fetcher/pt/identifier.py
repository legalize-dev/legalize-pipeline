"""Identifiers and jurisdictions for Portuguese diplomas.

DRE names every document it publishes, in the URL of that document's own page::

    https://diariodarepublica.pt/dr/detalhe/resolucao/3-2001-1331261
                                            ^type    ^number ^year ^DRE id

That name is read here, not rebuilt. The previous scheme reconstructed one from
the ELI type, the ``Numero`` field and the série, and every part of that
reconstruction went wrong on the real corpus: ``Numero`` spells the série inside
itself (``"1/2000 (2.ª série)"``), which leaked into 11,161 identifiers in two
different spellings and defeated the two-digit-year normalisation in three more;
the type came from a hand-kept map against 40 ELI types; and the whole thing
needed a série discriminant to stop 6,862 pairs of unrelated acts colliding.

The DRE id makes all of that unnecessary. Measured over the whole catalogue:
171,734 distinct identifiers out of 171,737 documents, the three duplicates
being one act indexed twice rather than two acts sharing a name.

The year comes first so that a consumer finds it at a fixed position — the
second hyphen-separated component, always — which is what lets the repo shard
by year with a rule short enough to state in the manifest. Searching for a
component that looks like a year does not work: 2,931 diplomas are numbered
like one.

The type is not in the identifier. It is in the file, as ``rank``, which is
where a reader who wants it should find it; number and year alone are ambiguous
across types (32 % of them are), so this is a name for a machine to resolve and
not a citation to read.
"""

from __future__ import annotations

import re

# /eli/{type}/{number}/{year}[/{month}/{day}]/{jurisdiction}/{cons|dre}/...
_ELI = re.compile(r"/eli/(?P<type>[^/]+)/(?P<number>[^/]+)/(?P<year>\d{4})/(?P<rest>.*)$")
_JURISDICTION_SEGMENT = re.compile(r"(?:^|/)(?P<code>[pam])(?:/|$)")

# ELI jurisdiction segment -> legalize jurisdiction (ISO 3166-2, as ELI uses).
JURISDICTIONS = {"p": None, "a": "pt-20", "m": "pt-30"}


def parse_eli(eli: str) -> dict | None:
    """Split an ELI URI into its type, number, year and jurisdiction."""
    match = _ELI.search(eli or "")
    if not match:
        return None
    rest = match.group("rest")
    juris = _JURISDICTION_SEGMENT.search("/" + rest)
    return {
        "type": match.group("type"),
        "number": match.group("number"),
        "year": match.group("year"),
        "jurisdiction_code": juris.group("code") if juris else "p",
    }


# Fallbacks for the 1.7 % of diplomas with no ELI: the region is also encoded in
# the trailing component of the number ("2/2025/M") and in the issuing body.
_NUMERO_REGION = re.compile(r"/(?P<code>[AM])\s*$", re.IGNORECASE)
_EMISSOR_REGION = (("A\u00e7ores", "pt-20"), ("Madeira", "pt-30"))


def jurisdiction_from_eli(eli: str, numero: str = "", emissor: str = "") -> str | None:
    """``pt-20`` for A\u00e7ores, ``pt-30`` for Madeira, ``None`` for national.

    Read from the ELI path segment, which is authoritative.
    ``DiplomaLegis.IsRegional`` is not: only 129 of 5,528 catalogue rows have it
    ``true`` while the regional ELI types alone account for 452 diplomas.
    """
    parsed = parse_eli(eli)
    if parsed:
        return JURISDICTIONS.get(parsed["jurisdiction_code"])
    match = _NUMERO_REGION.search(numero or "")
    if match:
        return "pt-20" if match.group("code").upper() == "A" else "pt-30"
    for needle, code in _EMISSOR_REGION:
        if needle.lower() in (emissor or "").lower():
            return code
    return None


_SERIE = re.compile(r"Série\s+([IVX]+)")
_ROMAN = re.compile(r"[IVX]+")


def serie_of(*sources: dict) -> str:
    """The Diário da República série an act was published in: "I", "II", "".

    DRE fills ``Serie`` on some records and not others, but ``Publicacao`` always
    spells it out ("Diário da República n.º 242/2008, Série II de 2008-12-16"), so
    the string is the fallback. Only the roman numeral is kept: between 1976 and
    1999 Série I was split into I-A and I-B, and those are the same série.
    """
    for source in sources:
        if not source:
            continue
        declared = str(source.get("Serie") or "").strip().upper().split("-")[0]
        if _ROMAN.fullmatch(declared):
            return declared
        found = _SERIE.search(source.get("Publicacao") or "")
        if found:
            return found.group(1)
    return ""


# The document's own page URL: /dr/detalhe/{type}/{number}-{year}-{id}. The
# type segment is skipped — it is in the file as ``rank`` — and the tail is read
# right to left, because the number may itself contain hyphens ("790-B", "1033-BV")
# while the id and the year never do.
_DOC_URL = re.compile(r"/dr/detalhe/[^/]+/(?P<name>[^/?#]+)/?\s*$")
_YEAR = re.compile(r"(?:1[6-9]|20)\d{2}")


def build_identifier(link: str, source_id: str, year: str | int = "") -> str:
    """``DRE-{YEAR}-{NUMBER}-{SOURCE_ID}`` — DRE's own name for the document.

        /dr/detalhe/resolucao/3-2001-1331261        -> DRE-2001-3-1331261
        /dr/detalhe/portaria/790-b-1992-447283      -> DRE-1992-790-B-447283
        /dr/detalhe/decreto/1976-408205             -> DRE-1976-408205
        (no page URL)                               -> DRE-{year}-{source_id}

    Portugal published thousands of numberless ``Decreto de <data>`` acts; those
    are the third form, and DRE's id is what separates them from each other.
    """
    match = _DOC_URL.search(link or "")
    if match:
        parts = [p for p in match.group("name").split("-") if p]
        if len(parts) >= 2 and _YEAR.fullmatch(parts[-2]):
            return "-".join(["DRE", parts[-2], *parts[:-2], parts[-1]]).upper()

    # A document with no usable page URL — one in 4,000 measured. Its id still
    # names it uniquely, so it is published rather than dropped; only the
    # citation number is missing from the name.
    source_id = str(source_id or "").strip()
    year = str(year or "").strip()
    if not source_id or not _YEAR.fullmatch(year):
        raise ValueError(
            f"no identifier can be built: link={link!r} source_id={source_id!r} year={year!r}"
        )
    return f"DRE-{year}-{source_id}".upper()
