"""ELI-derived identifiers and jurisdictions for Portuguese diplomas.

Portugal publishes an ELI (European Legislation Identifier) for essentially every
diploma, and it is the only stable, official, machine-readable name each law has::

    https://data.dre.pt/eli/dec-lei/47344/1966/p/cons/20260623/pt/html
    https://data.dre.pt/eli/lei/29/2026/06/23/p/dre/pt/html
    https://data.dre.pt/eli/declegreg/2/2025/07/02/m/dre/pt/html
                          ^type   ^num ^year      ^jurisdiction

The old scheme (``DRE-DL-47344``) was built from a hand-kept map of 19 type codes
against DRE's 33 ELI types, wrote the year with two digits for 55,742 files and four
for 32,650, collapsed Resolução do Conselho de Ministros and Resolução da Assembleia
da República onto the same ``DRE-R-`` prefix, and funnelled every numberless diploma
into two ``*-UNKNOWN`` files that each ended up holding a single document. See
RESEARCH-PT-v2 §1.7 and §6.1.
"""

from __future__ import annotations

import re
import unicodedata

# /eli/{type}/{number}/{year}[/{month}/{day}]/{jurisdiction}/{cons|dre}/...
_ELI = re.compile(r"/eli/(?P<type>[^/]+)/(?P<number>[^/]+)/(?P<year>\d{4})/(?P<rest>.*)$")
_JURISDICTION_SEGMENT = re.compile(r"(?:^|/)(?P<code>[pam])(?:/|$)")

# ELI jurisdiction segment -> legalize jurisdiction (ISO 3166-2, as ELI uses).
JURISDICTIONS = {"p": None, "a": "pt-20", "m": "pt-30"}

_UNSAFE = re.compile(r"[^A-Z0-9]+")

# DRE URL slug -> the ELI type token, the official short form of the same type.
#
# The record's own ``TipoDiplomaAcronimo`` cannot carry this: it is empty on 559 of
# 13,211 despachos normativos and disagrees with itself on the rest ("DN" on the
# legacy catalogue rows, "despnorm" on the modern ones), which split one type across
# three prefixes — DRE-DN-, DRE-DESPNORM- and DRE-DESPACHO-NORMATIVO-. Keyed on the
# slug instead, every diploma of a type gets one prefix whatever the row looks like.
#
# Derived from every ELI in the corpus (40 types, no type ever maps to two tokens);
# "regimento" is the one entry read off TipoDiplomaAcronimo, DRE publishing no ELI
# for it, and it matches its own sub-types rgtassrep / rgtconsest.
TYPE_TOKENS = {
    "acordao-supremo-tribunal-justica": "acstj",
    "acordao-tribunal-constitucional": "actconst",
    "acordao-tribunal-contas": "actcont",
    "assento": "asst",
    "aviso": "av",
    "aviso-banco-portugal": "avbdp",
    "declaracao": "decl",
    "declaracao-rectificacao": "declrectif",
    "declaracao-retificacao": "declretif",
    "decreto": "dec",
    "decreto-governo": "decgov",
    "decreto-legislativo-regional": "declegreg",
    "decreto-lei": "dec-lei",
    "decreto-ministro-republica": "decminrep",
    "decreto-ministro-republica-para-regiao-autonoma-acores": "decminrepraa",
    "decreto-ministro-republica-para-regiao-autonoma-madeira": "decminrepram",
    "decreto-presidente-republica": "decpresrep",
    "decreto-regional": "decreg",
    "decreto-regulamentar": "decregul",
    "decreto-regulamentar-regional": "decregulreg",
    "decreto-representante-republica-para-regiao-autonoma-acores": "decrepraa",
    "decreto-representante-republica-para-regiao-autonoma-madeira": "decrepram",
    "despacho": "desp",
    "despacho-normativo": "despnorm",
    "lei": "lei",
    "lei-constitucional": "leiconst",
    "lei-organica": "leiorg",
    "mapa-oficial": "mapofic",
    "portaria": "port",
    "regimento": "rgt",
    "regimento-assembleia-republica": "rgtassrep",
    "regimento-conselho-estado": "rgtconsest",
    "regulamento": "regul",
    "regulamento-cmvm": "regul-cmvm",
    "resolucao": "resol",
    "resolucao-assembleia-legislativa-regiao-autonoma-acores": "resolalraa",
    "resolucao-assembleia-legislativa-regiao-autonoma-madeira": "resolalram",
    "resolucao-assembleia-legislativa-regional": "resolalr",
    "resolucao-assembleia-regional": "resolassreg",
    "resolucao-assembleia-republica": "resolassrep",
    "resolucao-conselho-ministros": "resolconsmin",
}


def _slug(value: str) -> str:
    """Uppercase, de-accent and make filesystem-safe, without deleting characters.

    The old parser ran ``re.sub(r"[^a-zA-Z0-9\\-]", "", …)``, which silently turned
    ``43199(1ªparte)`` into ``431991parte`` — a citation a lawyer cannot resolve.
    Here every unsafe run becomes a single hyphen instead of vanishing.
    """
    folded = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(c for c in folded if not unicodedata.combining(c))
    return _UNSAFE.sub("-", ascii_only.upper()).strip("-")


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


def build_identifier(
    eli: str,
    numero: str,
    tipo_slug: str = "",
    ano: str | int = "",
    acronimo: str = "",
    dre_id: str = "",
) -> str:
    """Build the filesystem-safe identifier for a diploma.

    Prefers the ELI type token (official, 33 distinct values, no hand-kept map) and
    the diploma's own ``Numero`` (the authoritative citation, which may carry a third
    component the ELI drops — ``Portaria n.º 216/2024/1``). The year is appended only
    when ``Numero`` does not already contain it, so pre-1976 continuous numbering
    (``Decreto-Lei n.º 47344``) still gets one.

        dec-lei  + "47344"     + 1966 -> DRE-DEC-LEI-47344-1966
        (no ELI, slug "portaria")     -> DRE-PORT-…  (pre-1990 diplomas)
        lei      + "29/2026"          -> DRE-LEI-29-2026
        lei      + "82-D/2014"        -> DRE-LEI-82-D-2014
        port     + "216/2024/1"       -> DRE-PORT-216-2024-1
        declegreg+ "2/2025/M"         -> DRE-DECLEGREG-2-2025-M
    """
    parsed = parse_eli(eli)
    # The as-published ELI only exists from about 1990 (0/16 diplomas before, 42/42
    # after), so it cannot be the primary key for the ~104,000 older ones. The type
    # is therefore read off the DRE slug, which every diploma of a type shares by
    # construction, and only then off the record's own fields — TipoDiplomaAcronimo
    # is neither always filled nor self-consistent (see TYPE_TOKENS).
    type_token = _slug(
        TYPE_TOKENS.get(tipo_slug) or (parsed["type"] if parsed else "") or acronimo or tipo_slug
    )
    components = [c for c in (numero or "").split("/") if c.strip()]

    if parsed:
        # Take the number and the year from the ELI — it always writes the year with
        # four digits, while Numero writes "4/85" as often as "39/2016". Then append
        # any component Numero carries beyond those two: the "/1" of
        # "Portaria n.º 216/2024/1" and the "/M" of "DLR n.º 2/2025/M".
        parts = ["DRE", type_token or "X", _slug(parsed["number"]), str(parsed["year"])]
        parts += [_slug(c) for c in components[2:]]
        return "-".join(p for p in parts if p)

    # No ELI (everything before ~1990). Rebuild from Numero, normalising the
    # two-digit year DRE writes there ("905/80") to four digits, so the corpus has
    # one identifier shape instead of the 55,742-vs-32,650 split of the old repo.
    year = _slug(str(ano))
    if (
        len(components) >= 2
        and re.fullmatch(r"\d{2}", components[1])
        and year.endswith(components[1])
    ):
        components[1] = year
    number = "-".join(_slug(c) for c in components if _slug(c))
    parts = ["DRE", type_token or "X"]
    if number:
        parts.append(number)
        if year and year not in number.split("-"):
            parts.append(year)
    elif year:
        # Portugal published thousands of numberless "Decreto de <data>" acts. The old
        # scheme funnelled every one of them into DRE-D-UNKNOWN.md, which ended up
        # holding a single document — the rest were overwritten with no trace in git.
        # DRE's own content id makes each one unique.
        parts.append(year)
        if dre_id:
            parts.append(_slug(dre_id))
    return "-".join(p for p in parts if p)
