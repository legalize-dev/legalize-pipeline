"""Read source amendment relations without confusing commencement and publication."""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from datetime import date
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

from lxml import html

from legalize.fetcher.ie.client import CONSTITUTION_ID, _parse_norm_id

if TYPE_CHECKING:
    from legalize.fetcher.ie.client import ISBClient

logger = logging.getLogger(__name__)

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
        re.finditer(r"\bas\s+(?:inserted|substituted)\s+by\s+", cell.text_content(), re.I)
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
        r"S\.?\s*I[.,]?\s*(?:No\.?\s*)?(\d+)\s*(?:of\s+|/)(\d{4})", provision, re.I
    )
    for number, year in instruments:
        identifiers.discard(f"IE-{year}-act-{int(number)}")
        identifiers.add(f"IE-{year}-si-{int(number)}")
    if "Constitution of Ireland 1937" in provision:
        identifiers.add(CONSTITUTION_ID)
    if not identifiers:
        for number, year in re.findall(r"\b(\d+)\s*/\s*(\d{4})\b", provision):
            identifiers.add(f"IE-{year}-act-{int(number)}")
    correction = None
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


def _effect_cells(doc, norm_id: str) -> list[list]:
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
    return rows


def parse_effects(
    data: bytes, norm_id: str, *, editorial_notes: list[dict] | None = None
) -> list[dict]:
    """Preserve every resolvable effect, including continuation rows and pending changes."""
    cells_by_row = _effect_cells(html.fromstring(data.decode("utf-8")), norm_id)
    if not any(cells_by_row):
        raise ValueError(f"{norm_id}: effects table has no source rows")
    effects = []
    previous_note = ""
    scope = ""
    for cells in cells_by_row:
        if not cells:
            continue
        if len(cells) not in (2, 4):
            raise ValueError(f"{norm_id}: unexpected effects row with {len(cells)} columns")
        texts = [_text(cell) for cell in cells]
        note = texts[0] or previous_note
        provision = texts[1]
        ids, correction = _affecting_ids(cells[1], provision, norm_id, note)
        if not provision and not ids:
            if not note or re.fullmatch(r"Not affected\.?", note, re.I):
                continue
            if re.fullmatch(r"Spent\.?", note, re.I) and not any(texts[2:]):
                # An undated directory classification is not an amending enactment.
                if editorial_notes is not None:
                    editorial_notes.append({"note": note})
                previous_note = ""
                continue
            if re.fullmatch(
                r"References construed|(?:\w+ )?Schedule(?: \w+)?|Part \w+", note, re.I
            ):
                scope = "" if note.lower() == "references construed" else note
                continue
            raise ValueError(f"{norm_id}: effect has no affecting provision: {note}")
        if texts[0]:
            previous_note = note
        if not ids:
            # These source rows describe this Act's own citation or operation provisions.
            if re.fullmatch(
                r"(?:s\.|ss\.|sch\.|section|sections|schedule|part|art\.)\s*"
                r"\d+[a-z]?(?:\([0-9a-z]+\))*\.?",
                provision,
                re.I,
            ):
                continue
            raise ValueError(f"{norm_id}: unresolved affecting provision: {provision}")
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
            if (
                norm_id == "IE-2002-act-28"
                and identifier == "IE-1990-act-25"
                and note == "Schedule, constr. refs. “Pensions Board”"
                and provision == "25/1990, s. 9A"
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
            effects.append(effect)
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
    from legalize.fetcher.ie.parser import ISBMetadataParser

    continuity_note = None
    if norm_id == CONSTITUTION_ID:
        effects = constitution_effects(enacted_data)
        directory_url = f"{client._base_url}/eli/cons/en/html"
    else:
        year, kind, number = _parse_norm_id(norm_id)
        source_url = f"{client._base_url}/eli/{year}/{kind}/{number}/"
        source_url += "made/en/html" if kind == "si" else "enacted/en/html"
        page = enacted_data
        if page.lstrip().startswith((b"<?xml", b"<act", b"<privateact")):
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
        if norm_id == "IE-1966-act-6":
            note = (
                "*Excl. provns. ext. to Customs-free Airport. : "
                "See s. 20 (1), Interpretation Act, 1937."
            )
            continuation = (
                "Any document referring to any repealed enactment shall be construed "
                "as referring to this Act or the corresponding provision of this Act."
            )
            enacted_doc = html.fromstring(enacted_data)
            provision = enacted_doc.xpath('//*[@id="SEC9"]')
            if (
                note in _text(html.fromstring(directory_data))
                and len(provision) == 1
                and continuation in _text(provision[0])
            ):
                continuity_note = note
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
    for effect in effects:
        source_id = effect["source_id"]
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
            continuity_note
            and effect["note"] == "Excl. provns. ext. to Customs-free Airport. *"
            and (source_id, effect["provision"])
            in {
                ("IE-1947-si-115", "S.R. & O. No. 115 of 1947"),
                ("IE-1951-si-60", "S.R. & O. No. 60 of 1951"),
            }
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
                            "https://www.irishstatutebook.ie/eli/1966/act/6/section/9/enacted/en/html"
                        ),
                    },
                }
            )
        else:
            dated_effects.append(effect)
    return dated_effects
