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
# The later pairs: a re-issue printing the same "Updated to" date that corrects the
# catalogued file. Evidence and the reading of each: corrected-layouts-evidence.json.
_CORRECTED_PDF_LAYOUTS = {
    "d487045605971cca95feddf6dbd824188edd95e9f1e0f1d62c191cdd083e777d": "c056a097cf75e05af4f180de51d3be8623292dc0e9deff789430116d8c5a21bd",
    # IE-1991-act-17 at 2020-05-12, re-issued 2020-08-19.
    "7baddd84626261769ccaca249b2189eb4e376e5ef3556d0ebb7618220df04ff3": "fc6a3bf4d7d68c658251df180f9eb2abf2447d0db70744e2fa187414b552a424",  # pragma: allowlist secret
    # IE-2001-act-8 at 2019-09-11, re-issued 2020-07-30.
    "e61301f1ad076bcbe326b5ca267e24b422c347e1d32231f4f888d36f761a9ed9": "6bbd30b88975e712dc0ddae10cbb146b3f79e46da9cdcfb6833f3b8782e6dd06",  # pragma: allowlist secret
    # IE-2004-act-27 at 2021-08-19, re-issued 2022-01-01.
    "4e5dcf4d50c02f76847bc15f1889f2aa2316db1ac1b226a46f3370cfb463faf5": "5f818aec4e623c865decb0552125718d2e62aa7df378ba407a2dadee5407cc84",  # pragma: allowlist secret
    # IE-2005-act-27 at 2020-02-06, re-issued 2020-03-27.
    "0b19ca307f8c627340cafff49009c6d71ac48fdc2c14440f8b46874b5fa46cd6": "596b1ea03415bd9cda5bfa4f7e98e5f862ff8a0fdc7043ee04610785d4c35007",  # pragma: allowlist secret
    # IE-2005-act-27 at 2020-05-27, re-issued 2020-07-29.
    "f2c231188b824d6dcd4fc6341516245ed28ed335aa6d0c09e2fa4ddecbd63046": "cc24b5b38ede5b9c0608a67a9f6342c862b9fed5263a24e96134bd801f6b17ae",  # pragma: allowlist secret
    # IE-2007-act-10 at 2018-11-30, re-issued 2020-07-20.
    "8cdbd689e8a8e2a7ba4996e7f5f8ecb6df2ca0fb5cc7f610fe4eb08f4066efc8": "4837641e7e639aed3a254c8f45d7ae278c095f88c2bb1990823f46d0eeac0023",  # pragma: allowlist secret
    # IE-2007-act-19 at 2019-12-02, re-issued 2020-01-17.
    "2e375dc60ae9ae78ee973d6234b6615b795a61b638d887685bad20d8ebf67a9d": "517cd5f6eeccadfbad707b784fe1200271921217634d7c076ac6d117ef750c76",  # pragma: allowlist secret
    # IE-2007-act-20 at 2020-06-12, re-issued 2020-08-04.
    "47008d2c5cfcbdafc1a0add59ae7b7ec5b643aa99c33ebaa4410f3783b172f46": "0697c1a8ff093a6672c900cec1f728fe8a5449effeeaa1b7e8564e91c271568d",  # pragma: allowlist secret
    # IE-2007-act-25 at 2020-03-27, re-issued 2020-07-29.
    "dc45d32f113c93a39c0779d5f3dfa56e46aeb326f88d74235d4a15bfd4d84b68": "d4c64ae31e83c7b0e7052122d4436627106e08d5f9a861e825c894d928723681",  # pragma: allowlist secret
    # IE-2013-act-25 at 2019-12-23, re-issued 2020-07-07.
    "fbda92661514493d63f5a28ce1d6f8fbf880106f97deed04e0b7978bfeca60c2": "d34c34affd2a06c44d18eb2443e9b1b208fb1b63cb6b0c28fb7e77de9bda7a63",  # pragma: allowlist secret
    # IE-2013-act-26 at 2019-07-23, re-issued 2020-09-01.
    "776dfca5c8af5577895b98c1ffe2a935386cfd3257a7bd603fee56e397cec014": "68f8edb06d7a30d9a22e5512ce69492aa74be376be4fcad218db46e8d9c19312",  # pragma: allowlist secret
}

# Exact catalogue files that cannot stand for their snapshot. The Act is published
# with the snapshots the source does support; a changed file fails again.
_OMITTED_SNAPSHOTS = {
    "1e6941436fa6e43e2174d09637582dd039b8828b223153b7bf2c618ebd1431f3": (  # pragma: allowlist secret
        "The LRC catalogue links this file as the unannotated 20 May 2021 Consumer "
        "Protection Act 2007, but it carries annotation sections; no unannotated copy "
        "of that snapshot is published."
    ),
    "472e7e7ac73eef118984dc998eab986c11783fb2312bc5ff2a64505aeab9b739": (  # pragma: allowlist secret
        "The LRC catalogue links this file as the unannotated 10 March 2019 Planning and "
        "Development Act 2000, but its body carries an annotation block (C97, physical page "
        "149); no unannotated copy of that snapshot is published."
    ),
    "0b8d241841aed5db4a48ab2027bf2c4e1b2352adf78683ec4d054961bc9d4be4": (  # pragma: allowlist secret
        "The LRC catalogue's unannotated link for the 1 January 2019 Planning and Development "
        "Act 2000 is an unversioned URL that now serves a file with annotation blocks; no "
        "unannotated copy of that snapshot is published."
    ),
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
            if reason := _OMITTED_SNAPSHOTS.get(digest):
                editorial_notes.append(
                    {
                        "kind": "omitted_source_snapshot",
                        "url": row["url"],
                        "catalog_date": row["catalog_date"],
                        "sha256": digest,
                        "reason": reason,
                    }
                )
                continue
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
    # Spec v0.5 §Coverage: what the source cites or publishes but this file cannot date
    # or read is listed, never committed at a guessed date and never dropped in silence.
    gaps = []
    undated = []
    notes_in = []
    for note in envelope.get("editorial_notes") or []:
        if note.get("kind") == "omitted_source_snapshot":
            gaps.append(
                {
                    "norm_id": norm_id,
                    "date": note["catalog_date"],
                    "reason": note["reason"],
                    "sha256": note["sha256"],
                    "url": note["url"],
                }
            )
        elif note.get("kind") == "undatable_source":
            undated.append(
                {
                    "source_id": note["source_id"],
                    "reason": note["reason"],
                    "provision": note.get("provision", ""),
                    "basis_source": note.get("basis_source", ""),
                }
            )
        else:
            notes_in.append(note)
    grouped = defaultdict(list)
    for effect in envelope["effects"]:
        grouped[effect["source_id"]].append(effect)
    undated_sources = set()
    for identifier, effects in grouped.items():
        if identifier == norm_id:
            continue
        dates = {effect.get("publication_date") for effect in effects}
        published = (
            date.fromisoformat(next(iter(dates))) if len(dates) == 1 and None not in dates else None
        )
        if published is None or published < metadata.publication_date:
            undated_sources.add(identifier)
            undated.append(
                {
                    "source_id": identifier,
                    "reason": (
                        "The Legislation Directory gives it no single publication date."
                        if published is None
                        else f"Published {published}, before this law ({metadata.publication_date}); "
                        "the directory does not state when its effect began."
                    ),
                    "provision": "; ".join(
                        dict.fromkeys(f"{e['note']} — {e['provision']}" for e in effects)
                    ),
                }
            )
            continue
        notes = []
        for effect in effects:
            note = f"{effect['note']} — {effect['provision']}"
            if effect.get("commencement") or effect.get("commencement_source"):
                note += f"; commencement: {effect.get('commencement', '')} {effect.get('commencement_source', '')}".rstrip()
            if note not in notes:
                notes.append(note)
        reforms.append(Reform(published, identifier, (), change_note="; ".join(notes)))

    snapshot_bodies = {}
    snapshot_sources = {}
    conflicted = set()
    image_counts = {}
    for record in envelope["versions"]:
        raw = base64.b64decode(record["data"], validate=True)
        fmt = record["format"]
        warning = None
        snapshot_reform = None
        try:
            if fmt == "revised_pdf" and (
                preferred := _CORRECTED_PDF_LAYOUTS.get(hashlib.sha256(raw).hexdigest())
            ):
                if any(
                    candidate.get("format") == "revised_pdf"
                    and candidate.get("sha256") == preferred
                    and hashlib.sha256(
                        base64.b64decode(candidate["data"], validate=True)
                    ).hexdigest()
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
                        parse_revised_pdf,
                        source_warning,
                    )

                    paragraphs, cutoff = parse_revised_pdf(raw)
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
                if cutoff in conflicted:
                    raise ValueError(f"conflicting source texts at {cutoff}")
                if cutoff in snapshot_bodies:
                    if snapshot_bodies[cutoff] == paragraphs:
                        # An archived copy proves the date even if today's URL serves the same body.
                        continue
                    # A file cannot be updated to a day after its own catalogue entry: that URL
                    # was overwritten later and is not the catalogued snapshot. Keep the other.
                    kept_record, kept_version, kept_reform = snapshot_sources[cutoff]
                    day = cutoff.isoformat()
                    if record["catalog_date"] < day <= kept_record["catalog_date"]:
                        image_counts.pop(record["url"], None)
                        continue
                    image_counts.pop(kept_record["url"], None)
                    versions.remove(kept_version)
                    reforms.remove(kept_reform)
                    if not kept_record["catalog_date"] < day <= record["catalog_date"]:
                        # Two official files print this date with different bodies and
                        # nothing verified says which is right: neither is published.
                        conflicted.add(cutoff)
                        gaps.append(
                            _gap(norm_id, kept_record, f"conflicting source texts at {cutoff}")
                        )
                        raise ValueError(f"conflicting source texts at {cutoff}")
                snapshot_bodies[cutoff] = paragraphs
                source_id = f"revised-{norm_id}@{cutoff.isoformat()}"
                snapshot_reform = Reform(
                    cutoff,
                    source_id,
                    ("full-text",),
                    has_source_date=False,
                    change_note="Official consolidated snapshot; publication date not stated."
                    + (f" Source warning: {warning}" if warning else ""),
                )
            if not paragraphs:
                raise ValueError(f"{norm_id}: empty {fmt} source body")
            if missing := _missing_footnotes(paragraphs):
                raise ValueError(
                    f"{norm_id}: {fmt} has undefined normative footnotes: {sorted(missing)}"
                )
            if snapshot_reform is not None:
                reforms.append(snapshot_reform)
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
            if fmt != "enacted":
                snapshot_sources[cutoff] = (record, versions[-1], reforms[-1])
        except ValueError as exc:
            # UnsupportedPDF is a ValueError. The enacted text is the law itself: without
            # it there is nothing to publish, so that failure still rejects the law.
            if fmt == "enacted":
                raise
            if fmt in {"revised_pdf", "current_pdf"} and record["url"] in image_counts:
                image_counts.pop(record["url"], None)
            gaps.append(_gap(norm_id, record, str(exc)))

    dated_effects = [e for e in envelope["effects"] if e["source_id"] not in undated_sources]
    activations = {}
    for effect in dated_effects:
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
        # An undated repeal still counts today; it cannot be placed in the history.
        status=_status_at(envelope["effects"], today),
        extra=metadata.extra
        + (
            (
                (
                    "legislation_directory_notes",
                    json.dumps(notes_in, ensure_ascii=False, sort_keys=True),
                ),
            )
            if notes_in
            else ()
        )
        + ((("source_version_gaps", json.dumps(gaps, ensure_ascii=False)),) if gaps else ())
        + ((("undated_amendments", json.dumps(undated, ensure_ascii=False)),) if undated else ())
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
        dated_reforms.append(replace(reform, status=_status_at(dated_effects, status_date)))
    return ParsedNorm(
        metadata, (Block("full-text", "document", "", tuple(versions)),), tuple(dated_reforms)
    )


def _gap(norm_id: str, record: dict, reason: str) -> dict:
    """One spec v0.5 ``source_version_gaps`` entry for a catalogued version not published."""
    raw = base64.b64decode(record["data"], validate=True)
    return {
        "norm_id": norm_id,
        "date": record["catalog_date"],
        "reason": reason.removeprefix(f"{norm_id}: "),
        "sha256": record.get("sha256") or hashlib.sha256(raw).hexdigest(),
        "url": record["url"],
    }


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
