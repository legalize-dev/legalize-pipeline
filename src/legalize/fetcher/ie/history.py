"""One cached source envelope for enactments, legislative effects and LRC snapshots."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from collections import defaultdict
from dataclasses import replace
from datetime import date
from functools import lru_cache
from pathlib import Path
from urllib.parse import urljoin

from lxml import html

from legalize.fetcher.ie.effects import source_date
from legalize.models import Block, NormStatus, ParsedNorm, Reform, TextState, Version

logger = logging.getLogger(__name__)
REVISED_INDEX = "https://revisedacts.lawreform.ie/revacts/chron"
# Same 2020-01-01 Companies text; the second PDF repairs the paragraph break
# at section 1181(4). See archive-companies-2020-source-gaps.json for both proofs.
_CORRECTED_PDF_LAYOUTS = {
    "d487045605971cca95feddf6dbd824188edd95e9f1e0f1d62c191cdd083e777d": "c056a097cf75e05af4f180de51d3be8623292dc0e9deff789430116d8c5a21bd",
}


@lru_cache(maxsize=1)
def _parser_revision() -> str:
    directory = Path(__file__).parent
    return hashlib.sha256(
        b"".join(path.read_bytes() for path in sorted(directory.glob("*.py")))
    ).hexdigest()


def cached_norm_for_text(json_path: Path, data: bytes | None = None) -> ParsedNorm | None:
    """Reuse parsed immutable PDFs until source bytes, parser or a legal status changes."""
    from legalize.storage import load_norma_from_json

    stamp_path = json_path.parent.parent / "source-stamps" / json_path.name
    if not json_path.exists() or not stamp_path.exists():
        return None
    try:
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        data is not None and stamp.get("source_sha256") != hashlib.sha256(data).hexdigest()
    ) or stamp.get("parser") != _parser_revision():
        return None
    if stamp.get("next_status_date") and date.today().isoformat() >= stamp["next_status_date"]:
        return None
    try:
        return load_norma_from_json(json_path)
    except (OSError, ValueError):
        return None


def save_source_stamp(json_path: Path, data: bytes) -> None:
    effects = json.loads(data)["effects"]
    future = [
        effect["effective_date"]
        for effect in effects
        if (effect.get("whole_repeal") or effect.get("partial_repeal"))
        and not effect.get("pending")
        and effect.get("effective_date")
        and effect["effective_date"] > date.today().isoformat()
    ]
    path = json_path.parent.parent / "source-stamps" / json_path.name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "source_sha256": hashlib.sha256(data).hexdigest(),
                "parser": _parser_revision(),
                "next_status_date": min(future) if future else None,
            }
        ),
        encoding="utf-8",
    )


@lru_cache(maxsize=2)
def revised_catalog(data: bytes) -> dict[str, tuple[dict, ...]]:
    """Read the published archive URLs, including their S3 version query strings."""
    doc = html.fromstring(data.decode("utf-8"))
    catalog = defaultdict(list)
    for row in doc.xpath("//tr[@data-eli]"):
        parts = row.get("data-eli", "").split("/")
        if len(parts) != 4 or parts[1] != "act" or parts[3] != "en":
            continue
        year, _, number, _ = parts
        norm_id = f"IE-{year}-act-{number}"
        updated = row.xpath('./td[contains(concat(" ",normalize-space(@class)," ")," updated ")]')
        cutoff = source_date(updated[0].text_content()) if updated else None
        if cutoff is None:
            raise ValueError(f"{norm_id}: revised catalogue row has no valid date")
        html_urls = row.xpath('.//a[contains(@href,"/front/revised/")]/@href')
        pdf_urls = row.xpath('.//a[@title="without annotations"]/@href')
        if html_urls:
            url = html_urls[0].replace("/front/revised/", "/revised/")
            fmt = "revised_html"
        elif pdf_urls:
            url, fmt = pdf_urls[0], "revised_pdf"
        else:
            raise ValueError(f"{norm_id}: revised catalogue row has no full text")
        catalog[norm_id].append(
            {
                "url": urljoin(REVISED_INDEX, url),
                "format": fmt,
                "catalog_date": cutoff.isoformat(),
                **(
                    {"pdf_url": urljoin(REVISED_INDEX, pdf_urls[0])}
                    if html_urls and pdf_urls
                    else {}
                ),
            }
        )
    if not catalog:
        raise ValueError("Revised Acts catalogue contains no English Acts")
    return {
        key: tuple(
            sorted(rows, key=lambda row: (row["catalog_date"], row["format"] == "revised_html"))
        )
        for key, rows in catalog.items()
    }


def fetch_text(client, norm_id: str, meta_data: bytes | None = None) -> bytes:
    """Fetch complete source records; a missing history source is never silently dropped."""
    from legalize.fetcher.ie.effects import fetch_effects
    from legalize.fetcher.ie.parser import ISBMetadataParser

    meta_data = meta_data if meta_data is not None else client.get_metadata(norm_id)
    metadata = ISBMetadataParser().parse(meta_data, norm_id)
    enacted = client.get_enacted_text(norm_id)
    editorial_notes = []
    effects = fetch_effects(client, norm_id, enacted, editorial_notes=editorial_notes)
    versions = [
        {
            "format": "enacted",
            "url": metadata.source,
            "data": base64.b64encode(enacted).decode("ascii"),
        }
    ]
    if "-act-" in norm_id and norm_id.rsplit("-", 1)[1].isdigit():
        rows = revised_catalog(client._get(REVISED_INDEX)).get(norm_id, ())
        seen = set()
        for row in rows:
            raw = client._get(row["url"])
            if row["format"] == "revised_html":
                from legalize.fetcher.ie.parser import parse_revised_html

                paragraphs, _ = parse_revised_html(raw)
                if _missing_footnotes(paragraphs, source_html=raw):
                    if not row.get("pdf_url"):
                        raise ValueError(
                            f"{norm_id}: source HTML has undefined normative footnotes"
                        )
                    row = {**row, "url": row["pdf_url"], "format": "current_pdf"}
                    raw = client._get(row["url"])
            digest = hashlib.sha256(raw).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            versions.append(
                {**row, "sha256": digest, "data": base64.b64encode(raw).decode("ascii")}
            )
    return json.dumps(
        {
            "legalize_ie": 1,
            "identifier": norm_id,
            "metadata": base64.b64encode(meta_data).decode("ascii"),
            "versions": versions,
            "effects": effects,
            "editorial_notes": editorial_notes,
        },
        ensure_ascii=False,
    ).encode("utf-8")


def _missing_footnotes(paragraphs, *, source_html: bytes | None = None):
    text = "\n".join(paragraph.text for paragraph in paragraphs)
    references = set(re.findall(r"\[\^([^\]]+)\](?!:)", text))
    definitions = set(re.findall(r"^\[\^([^\]]+)\]:", text, re.M))
    if source_html is not None:
        # Revised HTML has bare numeric superscripts: no link or semantic class
        # distinguishes a footnote from an exponent. Undefined ones render as
        # ^N, so Markdown-reference checks alone cannot establish completeness.
        # Use the complete official PDF conservatively; do not guess from words,
        # units or formula patterns and risk suppressing a real source omission.
        doc = html.fromstring(source_html)
        for note in doc.xpath(
            '//div[@class="frontmatter" or @class="body" or @class="backmatter"]//sup'
        ):
            if any(
                ancestor.tag == "footer"
                or set(ancestor.get("class", "").split())
                & {"annotations", "actsreferredto", "narrative"}
                for ancestor in note.iterancestors()
            ):
                continue
            marker = note.text_content().strip()
            if marker.isdigit():
                references.add(marker)
    return references - definitions


def _parse(data: bytes) -> ParsedNorm:
    return _parse_on(data, date.today())


@lru_cache(maxsize=2)
def _parse_on(data: bytes, today: date) -> ParsedNorm:
    from legalize.fetcher.ie.parser import ISBMetadataParser, ISBTextParser, parse_revised_html

    envelope = json.loads(data)
    if envelope.get("legalize_ie") != 1:
        raise ValueError("Unsupported Ireland source envelope")
    norm_id = envelope["identifier"]
    metadata = ISBMetadataParser().parse(
        base64.b64decode(envelope["metadata"], validate=True), norm_id
    )
    paragraphs = None
    versions = []
    reforms = [Reform(metadata.publication_date, norm_id, ("full-text",))]
    snapshot_bodies = {}
    image_counts = {}
    for record in envelope["versions"]:
        raw = base64.b64decode(record["data"], validate=True)
        fmt = record["format"]
        warning = None
        if fmt == "revised_pdf" and (
            preferred := _CORRECTED_PDF_LAYOUTS.get(hashlib.sha256(raw).hexdigest())
        ):
            if any(
                candidate.get("format") == "revised_pdf"
                and candidate.get("sha256") == preferred
                and hashlib.sha256(base64.b64decode(candidate["data"], validate=True)).hexdigest()
                == preferred
                for candidate in envelope["versions"]
            ):
                continue
        if fmt not in {"revised_pdf", "current_pdf"}:
            doc = html.fromstring(raw)
            # Count omitted document images, including decorative source emblems,
            # but not navigation icons or images in excluded editorial material.
            count = sum(
                not any(
                    {"annotations", "narrative", "actsreferredto", "sect-tab"}
                    & set(ancestor.get("class", "").split())
                    for ancestor in image.iterancestors()
                )
                for image in doc.xpath(
                    "//graphic | //div[@id='act' or @id='si' or @class='body' or @class='backmatter' or @class='frontmatter']//img"
                )
            )
            if count:
                image_counts[record["url"]] = count
        if fmt == "enacted":
            blocks = ISBTextParser().parse_text(raw, published_on=metadata.publication_date)
            paragraphs = tuple(p for block in blocks for p in block.versions[0].paragraphs)
            cutoff = metadata.publication_date
            state = metadata.text_state or TextState.AS_ENACTED
            source_id = norm_id
        else:
            if fmt == "revised_html":
                paragraphs, cutoff = parse_revised_html(raw)
                state = TextState.CURRENT
            elif fmt in {"revised_pdf", "current_pdf"}:
                from legalize.fetcher.ie.pdf import (
                    UnsupportedPDF,
                    parse_revised_pdf,
                    source_warning,
                )

                try:
                    paragraphs, cutoff = parse_revised_pdf(raw)
                except UnsupportedPDF as exc:
                    raise UnsupportedPDF(
                        f"{norm_id}: {record['url']} (SHA-256 {hashlib.sha256(raw).hexdigest()}): {exc}"
                    ) from exc
                warning = source_warning(raw)
                omitted = sum("[image omitted]" in paragraph.text for paragraph in paragraphs)
                if omitted:
                    image_counts[record["url"]] = omitted
                state = TextState.CURRENT if fmt == "current_pdf" else TextState.POINT_IN_TIME
            else:
                raise ValueError(f"{norm_id}: unsupported version format {fmt!r}")
            paragraphs = tuple(paragraphs)
            if cutoff is None:
                raise ValueError(f"{norm_id}: source snapshot has no stated cutoff")
            if cutoff < metadata.publication_date:
                raise ValueError(f"{norm_id}: consolidation cutoff predates the original Act")
            if cutoff.isoformat() != record["catalog_date"]:
                logger.warning(
                    "%s: catalogue date %s differs from source cover %s",
                    norm_id,
                    record["catalog_date"],
                    cutoff,
                )
            if cutoff in snapshot_bodies:
                if snapshot_bodies[cutoff] != paragraphs:
                    raise ValueError(f"{norm_id}: conflicting source texts at {cutoff}")
                # An archived copy proves the date even if today's URL serves the same body.
                continue
            snapshot_bodies[cutoff] = paragraphs
            source_id = f"revised-{norm_id}@{cutoff.isoformat()}"
            reforms.append(
                Reform(
                    cutoff,
                    source_id,
                    ("full-text",),
                    has_source_date=False,
                    change_note="Official consolidated snapshot; publication date not stated."
                    + (f" Source warning: {warning}" if warning else ""),
                )
            )
        if not paragraphs:
            raise ValueError(f"{norm_id}: empty {fmt} source body")
        if missing := _missing_footnotes(paragraphs):
            raise ValueError(
                f"{norm_id}: {fmt} has undefined normative footnotes: {sorted(missing)}"
            )
        versions.append(
            Version(
                norm_id=source_id,
                publication_date=metadata.publication_date,
                effective_date=cutoff,
                paragraphs=tuple(paragraphs),
                text_state=state,
                source=record["url"],
                source_warning=warning,
            )
        )

    grouped = defaultdict(list)
    for effect in envelope["effects"]:
        grouped[effect["source_id"]].append(effect)
    for identifier, effects in grouped.items():
        if identifier == norm_id:
            continue
        dates = {effect.get("publication_date") for effect in effects}
        if len(dates) != 1 or None in dates:
            raise ValueError(f"{norm_id}: no unique publication date for {identifier}")
        published = date.fromisoformat(next(iter(dates)))
        if published < metadata.publication_date:
            raise ValueError(f"{norm_id}: effect {identifier} predates the original publication")
        notes = []
        for effect in effects:
            note = f"{effect['note']} — {effect['provision']}"
            if effect.get("commencement") or effect.get("commencement_source"):
                note += f"; commencement: {effect.get('commencement', '')} {effect.get('commencement_source', '')}".rstrip()
            if note not in notes:
                notes.append(note)
        reforms.append(Reform(published, identifier, (), change_note="; ".join(notes)))

    activations = {}
    for effect in envelope["effects"]:
        effective = effect.get("effective_date")
        published = effect.get("publication_date")
        if not (effective and published) or effect.get("pending"):
            continue
        if not (effect.get("whole_repeal") or effect.get("partial_repeal")):
            continue
        day = date.fromisoformat(effective)
        if date.fromisoformat(published) < day <= today:
            prior = max(
                (version for version in versions if version.in_force_from < day),
                key=lambda version: (version.in_force_from, version.norm_id != norm_id),
            )
            if prior.text_state is not TextState.AS_ENACTED:
                continue
            identifier = f"effective-{effect['source_id']}@{effective}"
            activations[identifier] = Reform(
                day,
                identifier,
                (),
                change_note=f"Repeal takes effect under {effect['source_id']}, published {published}.",
                has_source_date=False,
            )
    reforms.extend(activations.values())
    source_corrections = [
        effect for effect in envelope["effects"] if effect.get("source_correction")
    ]
    metadata = replace(
        metadata,
        status=_status_at(envelope["effects"], today),
        extra=metadata.extra
        + (
            (
                (
                    "legislation_directory_notes",
                    json.dumps(envelope["editorial_notes"], ensure_ascii=False, sort_keys=True),
                ),
            )
            if envelope.get("editorial_notes")
            else ()
        )
        + (
            (
                (
                    "legislation_directory_corrections",
                    json.dumps(source_corrections, ensure_ascii=False, sort_keys=True),
                ),
            )
            if source_corrections
            else ()
        )
        + (
            ("images_dropped", str(sum(image_counts.values()))),
            ("images_dropped_by_source", json.dumps(image_counts, sort_keys=True)),
        )
        + (
            (("has_formulas", "true"),)
            if any(
                re.search(r"\bformula(?:e|s)?\b", paragraph.text, re.I)
                for version in versions
                for paragraph in version.paragraphs
            )
            else ()
        ),
    )
    # Original text is first even when a source gives a retroactive consolidation.
    reforms = reforms[:1] + sorted(reforms[1:], key=lambda reform: (reform.date, reform.norm_id))
    versions.sort(key=lambda version: (version.in_force_from, version.norm_id != norm_id))
    dated_reforms = []
    for reform in reforms:
        applicable = [
            version
            for version in versions
            if version.in_force_from < reform.date
            or version.norm_id == reform.norm_id
            or (version.norm_id == norm_id and version.in_force_from == reform.date)
        ]
        version = max(applicable, key=lambda item: (item.in_force_from, item.norm_id != norm_id))
        status_date = (
            version.in_force_from
            if version.text_state is TextState.POINT_IN_TIME
            else today
            if version.text_state is TextState.CURRENT
            else reform.date
        )
        dated_reforms.append(replace(reform, status=_status_at(envelope["effects"], status_date)))
    return ParsedNorm(
        metadata, (Block("full-text", "document", "", tuple(versions)),), tuple(dated_reforms)
    )


def _status_at(effects, day):
    status = NormStatus.IN_FORCE
    for effect in effects:
        effective = effect.get("effective_date") or effect.get("publication_date")
        if effect.get("pending") or not effective or date.fromisoformat(effective) > day:
            continue
        if effect.get("whole_repeal"):
            return NormStatus.REPEALED
        if effect.get("partial_repeal"):
            status = NormStatus.PARTIALLY_REPEALED
    return status


def parse_text(data: bytes) -> list[Block]:
    return list(_parse(data).blocks)


def extract_reforms(data: bytes) -> list[Reform]:
    return list(_parse(data).reforms)


def metadata_for_text(metadata, data: bytes):
    """Carry source-derived status through the same cache consumed by commit/daily."""
    parsed = _parse(data)
    if parsed.metadata.identifier != metadata.identifier:
        raise ValueError("Ireland text and metadata identifiers disagree")
    return parsed.metadata
