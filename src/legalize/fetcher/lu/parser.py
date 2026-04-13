"""Legilux parser — Luxembourg.

Parses Akoma Ntoso CSD13 XML (with SCL Luxembourg extensions) into
Block/Version/Paragraph structures for the generic pipeline.

Handles two input formats:
1. Raw ``<akomaNtoso>`` XML — single version (original Act or Consolidation)
2. ``<legilux-multi-version>`` envelope — multiple versions bundled by the
   client, each wrapped in a ``<version>`` element with metadata attributes.

The SCL namespace (``http://www.scl.lu``) carries JOLux metadata embedded
in the ``<meta>`` section. The actual body uses standard Akoma Ntoso elements:
``<chapter>``, ``<section>``, ``<article>``, ``<paragraph>``, ``<alinea>``,
``<content>``, ``<p>``, with inline formatting via ``<b>``, ``<i>``, ``<sup>``,
``<ref>``, ``<ol>``, ``<ul>``, ``<li>``, ``<br>``.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any
from xml.etree import ElementTree as ET

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import Block, NormMetadata, NormStatus, Paragraph, Rank, Version

logger = logging.getLogger(__name__)

# ─── Namespaces ───
_AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0/CSD13"
_SCL_NS = "http://www.scl.lu"

# C0/C1 control characters to strip (keeps \n, \r, \t)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# ─── Rank mapping ───
_RANK_MAP: dict[str, str] = {
    "LOI": "loi",
    "RGD": "reglement_grand_ducal",
    "AGD": "arrete_grand_ducal",
    "AMIN": "arrete_ministeriel",
    "RMIN": "reglement_ministeriel",
    "Constitution": "constitution",
    "CODE": "code",
    "CONV": "convention",
    "TC": "traite",
    "ORD": "ordonnance",
    "DEC": "decision",
}

# ─── Status mapping ───
_STATUS_MAP: dict[str, NormStatus] = {
    "in-force": NormStatus.IN_FORCE,
    "no-longer-in-force": NormStatus.REPEALED,
    "not-yet-in-force": NormStatus.IN_FORCE,  # will be in force
    "partially-in-force": NormStatus.IN_FORCE,
}

# Authority URI prefixes to strip for human-readable values
_AUTH_PREFIX = "http://data.legilux.public.lu/resource/authority/"
_TYPE_PREFIX = f"{_AUTH_PREFIX}resource-type/"
_STATUS_PREFIX = f"{_AUTH_PREFIX}application-status/"
_INST_PREFIX = f"{_AUTH_PREFIX}legal-institution/"
_SUBJECT_PREFIX = f"{_AUTH_PREFIX}legal-subject/"


def _tag(el: ET.Element) -> str:
    """Strip namespace from an element tag."""
    return el.tag.split("}")[-1] if "}" in el.tag else el.tag


def _akn(tag: str) -> str:
    """Build a fully-qualified Akoma Ntoso tag name."""
    return f"{{{_AKN_NS}}}{tag}"


def _scl(tag: str) -> str:
    """Build a fully-qualified SCL tag name."""
    return f"{{{_SCL_NS}}}{tag}"


def _extract_text(el: ET.Element) -> str:
    """Extract text from an element, preserving inline formatting as Markdown.

    Handles: <b> → **bold**, <i> → *italic*, <sup> → <sup>...</sup>,
    <ref> → [text](href), <ol>/<ul>/<li> → list items, <br> → newline.
    """
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        ctag = _tag(child)
        child_text = _extract_text(child)

        if ctag == "b" and child_text:
            parts.append(f"**{child_text.strip()}**")
        elif ctag == "i" and child_text:
            parts.append(f"*{child_text.strip()}*")
        elif ctag == "sup" and child_text:
            parts.append(f"<sup>{child_text}</sup>")
        elif ctag == "ref":
            href = child.get("href", "")
            if href and child_text:
                parts.append(f"[{child_text}]({href})")
            elif child_text:
                parts.append(child_text)
        elif ctag == "br":
            parts.append("\n")
        elif ctag in ("noteRef", "eol"):
            # noteRef markers and end-of-line elements: skip silently
            pass
        else:
            # ol, ul, li, span, embeddedStructure, mod, and unknown: passthrough
            parts.append(child_text)

        if child.tail:
            parts.append(child.tail)

    text = "".join(parts)
    return _CONTROL_RE.sub("", text)


def _parse_list(list_el: ET.Element) -> str:
    """Parse an <ol> or <ul> element into Markdown list text."""
    items: list[str] = []
    symbol = list_el.get("symbol", "")
    start = list_el.get("start", "1")
    is_ordered = _tag(list_el) == "ol"

    for i, li in enumerate(list_el):
        if _tag(li) != "li":
            continue
        text = _extract_text(li).strip()
        if not text:
            continue
        if is_ordered:
            if symbol:
                # Use the symbol pattern (e.g., "1°", "a)", "(1)")
                try:
                    num = int(start) + i
                    marker = symbol.replace("1", str(num)).replace("a", chr(ord("a") + i))
                except (ValueError, IndexError):
                    marker = f"{i + 1}."
            else:
                marker = f"{i + 1}."
            items.append(f"{marker} {text}")
        else:
            items.append(f"- {text}")

    return "\n".join(items)


def _extract_paragraphs(body: ET.Element) -> list[Paragraph]:
    """Recursively extract paragraphs from a body/chapter/section/article tree.

    Walks the Akoma Ntoso body structure and emits flat Paragraph objects with
    css_class hints for the transformer.
    """
    paragraphs: list[Paragraph] = []
    _walk_body(body, paragraphs, depth=0)
    return paragraphs


def _walk_body(el: ET.Element, paragraphs: list[Paragraph], depth: int) -> None:
    """Walk an element tree, emitting Paragraphs for content elements."""
    tag = _tag(el)

    # Structural elements that carry a heading
    if tag in ("chapter", "section", "part", "title", "book"):
        num_el = el.find(_akn("num"))
        heading_el = el.find(_akn("heading"))
        heading_parts = []
        if num_el is not None:
            heading_parts.append(_extract_text(num_el).strip())
        if heading_el is not None:
            heading_parts.append(_extract_text(heading_el).strip())
        if heading_parts:
            level = min(depth + 2, 6)  # h2 for chapters, h3 for sections, etc.
            heading_text = " ".join(heading_parts)
            paragraphs.append(Paragraph(css_class=f"h{level}", text=heading_text))

        # Process children (skip num and heading, already handled)
        for child in el:
            if _tag(child) not in ("num", "heading"):
                _walk_body(child, paragraphs, depth + 1)
        return

    # Article
    if tag == "article":
        num_el = el.find(_akn("num"))
        heading_el = el.find(_akn("heading"))
        parts = []
        if num_el is not None:
            parts.append(_extract_text(num_el).strip())
        if heading_el is not None:
            heading_text = _extract_text(heading_el).strip()
            if heading_text:
                parts.append(heading_text)
        if parts:
            # Articles get one level deeper than their parent
            level = min(depth + 3, 6)
            paragraphs.append(Paragraph(css_class=f"h{level}", text=" ".join(parts)))

        for child in el:
            if _tag(child) not in ("num", "heading"):
                _walk_body(child, paragraphs, depth + 1)
        return

    # Paragraph (in Akoma Ntoso sense — a numbered sub-article)
    if tag == "paragraph":
        num_el = el.find(_akn("num"))
        if num_el is not None:
            num_text = _extract_text(num_el).strip()
            if num_text:
                paragraphs.append(Paragraph(css_class="num", text=num_text))
        for child in el:
            if _tag(child) != "num":
                _walk_body(child, paragraphs, depth)
        return

    # Content containers
    if tag in ("alinea", "content", "intro", "wrapUp", "interstitial"):
        for child in el:
            _walk_body(child, paragraphs, depth)
        return

    # Actual text element
    if tag == "p":
        text = _extract_text(el).strip()
        if text:
            paragraphs.append(Paragraph(css_class="abs", text=text))
        return

    # Lists
    if tag in ("ol", "ul"):
        list_text = _parse_list(el)
        if list_text:
            paragraphs.append(Paragraph(css_class="list", text=list_text))
        return

    # Blockquotes / embedded structures (amending text)
    if tag == "embeddedStructure":
        text = _extract_text(el).strip()
        if text:
            # Prefix each line with > for blockquote
            quoted = "\n".join(f"> {line}" for line in text.split("\n"))
            paragraphs.append(Paragraph(css_class="quote", text=quoted))
        return

    # Conclusions (signature block)
    if tag == "conclusions":
        for child in el:
            if _tag(child) == "p":
                text = _extract_text(child).strip()
                if text:
                    paragraphs.append(Paragraph(css_class="signature", text=text))
        return

    # Preface — skip longTitle (rendered by the pipeline as H1 from metadata.title)
    if tag == "preface":
        return

    # Preamble
    if tag == "preamble":
        for child in el:
            ctag = _tag(child)
            if ctag == "container":
                for p in child:
                    if _tag(p) == "p":
                        text = _extract_text(p).strip()
                        if text:
                            paragraphs.append(Paragraph(css_class="preamble", text=text))
            elif ctag == "formula":
                for p in child:
                    if _tag(p) == "p":
                        text = _extract_text(p).strip()
                        if text:
                            paragraphs.append(Paragraph(css_class="formula", text=text))
        return

    # Notes (footnotes in consolidations)
    if tag in ("notes", "note"):
        for child in el:
            _walk_body(child, paragraphs, depth)
        return

    # Modification metadata (skip — handled separately)
    if tag in (
        "textualMod",
        "passiveModifications",
        "activeModifications",
        "source",
        "destination",
        "passiveRef",
        "lifecycle",
        "analysis",
        "references",
        "original",
        "eventRef",
    ):
        return

    # Components container (annexes)
    if tag in ("components", "component"):
        for child in el:
            _walk_body(child, paragraphs, depth)
        return

    # Default: recurse into children
    for child in el:
        _walk_body(child, paragraphs, depth)


# ─── JOLux metadata extraction ───


def _get_jolux_values(meta_root: ET.Element) -> dict[str, list[str]]:
    """Extract all scl:jolux key-value pairs from a JOLUXLegalResource.

    Returns a dict where keys are the scl:name attributes and values are lists
    (because some fields like subjectLevel2 can repeat).
    """
    values: dict[str, list[str]] = {}
    for jolux_el in meta_root.iter(_scl("jolux")):
        name = jolux_el.get(f"{{{_SCL_NS}}}name", "")
        text = (jolux_el.text or "").strip()
        if name and text:
            values.setdefault(name, []).append(text)
    return values


def _get_expression_values(meta_root: ET.Element) -> dict[str, str]:
    """Extract title and titleShort from the JOLUXExpression block."""
    values: dict[str, str] = {}
    for expr_el in meta_root.iter(_scl("JOLUXExpression")):
        for jolux_el in expr_el.iter(_scl("jolux")):
            name = jolux_el.get(f"{{{_SCL_NS}}}name", "")
            text = (jolux_el.text or "").strip()
            if name and text:
                values[name] = text
    return values


def _parse_date(date_str: str) -> date | None:
    """Parse a YYYY-MM-DD date string, returning None on failure."""
    try:
        return date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None


def _strip_uri_prefix(uri: str, prefix: str) -> str:
    """Strip a known prefix from a URI to get a human-readable value."""
    if uri.startswith(prefix):
        return uri[len(prefix) :]
    return uri


# ─── TextParser ───


class LegiluxTextParser(TextParser):
    """Parse Legilux Akoma Ntoso XML into Block/Version/Paragraph structures."""

    def parse_text(self, data: bytes) -> list[Any]:
        """Parse consolidated text into a list of Block objects.

        Detects whether the input is a multi-version envelope or a single
        Akoma Ntoso document and handles accordingly.
        """
        text = data.decode("utf-8", errors="replace")
        text = _CONTROL_RE.sub("", text)

        root = ET.fromstring(text)
        root_tag = _tag(root)

        if root_tag == "legilux-multi-version":
            return self._parse_multi_version(root)
        elif root_tag == "akomaNtoso":
            return self._parse_single(root, norm_id="", pub_date=None)
        else:
            logger.warning("Unknown root element: %s", root_tag)
            return []

    def _parse_single(
        self,
        root: ET.Element,
        norm_id: str,
        pub_date: date | None,
    ) -> list[Block]:
        """Parse a single Akoma Ntoso document into blocks with one version."""
        act = root.find(_akn("act"))
        if act is None:
            return []

        # Extract metadata for this version
        meta = act.find(_akn("meta"))
        if meta is not None:
            jolux = _get_jolux_values(meta)
            if not norm_id:
                # Get from FRBRWork/FRBRthis
                frbr_this = meta.find(f".//{_akn('FRBRWork')}/{_akn('FRBRthis')}")
                if frbr_this is not None:
                    from legalize.fetcher.lu.client import _eli_to_norm_id

                    norm_id = _eli_to_norm_id(frbr_this.get("value", ""))

            if pub_date is None:
                date_str = (jolux.get("dateDocument") or jolux.get("publicationDate", [""]))[0]
                pub_date = _parse_date(date_str)
        else:
            jolux = {}

        if pub_date is None:
            pub_date = date(1900, 1, 1)

        # Extract body paragraphs
        paragraphs: list[Paragraph] = []

        # Preface
        preface = act.find(_akn("preface"))
        if preface is not None:
            _walk_body(preface, paragraphs, 0)

        # Preamble
        preamble = act.find(_akn("preamble"))
        if preamble is not None:
            _walk_body(preamble, paragraphs, 0)

        # Body
        body = act.find(_akn("body"))
        if body is not None:
            _walk_body(body, paragraphs, 0)

        # Conclusions
        conclusions = act.find(_akn("conclusions"))
        if conclusions is not None:
            _walk_body(conclusions, paragraphs, 0)

        if not paragraphs:
            return []

        version = Version(
            norm_id=norm_id,
            publication_date=pub_date,
            effective_date=pub_date,
            paragraphs=tuple(paragraphs),
        )

        return [
            Block(
                id="main",
                block_type="content",
                title="",
                versions=(version,),
            )
        ]

    def _parse_multi_version(self, root: ET.Element) -> list[Block]:
        """Parse a <legilux-multi-version> envelope into blocks with versions.

        Each <version> child contains an <akomaNtoso> root. The versions are
        ordered chronologically. The parser produces a single Block with
        multiple Versions (one per consolidated state of the law).
        """
        norm_id = root.get("norm-id", "")
        versions: list[Version] = []

        for version_el in root:
            if _tag(version_el) != "version":
                continue

            ver_type = version_el.get("type", "original")
            effective_date_str = version_el.get("effective-date", "")

            # Find the nested akomaNtoso
            akn_root = version_el.find(_akn("akomaNtoso"))
            if akn_root is None:
                # Try without namespace (the envelope strips it sometimes)
                akn_root = version_el.find("akomaNtoso")
            if akn_root is None:
                # The first child might be the act directly
                for child in version_el:
                    if _tag(child) == "akomaNtoso":
                        akn_root = child
                        break
                    elif _tag(child) == "act":
                        # Wrap in a fake akomaNtoso
                        akn_root = ET.Element("akomaNtoso")
                        akn_root.append(child)
                        break

            if akn_root is None:
                logger.warning("No akomaNtoso found in version %s", ver_type)
                continue

            act = akn_root.find(_akn("act"))
            if act is None:
                act = akn_root.find("act")
            if act is None:
                # If akomaNtoso IS the act
                if _tag(akn_root) == "act":
                    act = akn_root
                else:
                    continue

            # Extract the version date
            meta = act.find(_akn("meta"))
            jolux = _get_jolux_values(meta) if meta is not None else {}

            if ver_type == "original":
                # Use dateDocument for the original Act
                date_str = (jolux.get("dateDocument", [""]))[0]
                pub_date = _parse_date(date_str) or date(1900, 1, 1)
                eff_date = pub_date
            else:
                # Use effective-date attribute for consolidations
                eff_date = _parse_date(effective_date_str) or date(1900, 1, 1)
                date_str = (jolux.get("dateDocument", [""]))[0]
                pub_date = _parse_date(date_str) or eff_date

            # Extract paragraphs from body
            paragraphs: list[Paragraph] = []
            preface = act.find(_akn("preface"))
            if preface is not None:
                _walk_body(preface, paragraphs, 0)
            preamble = act.find(_akn("preamble"))
            if preamble is not None:
                _walk_body(preamble, paragraphs, 0)
            body = act.find(_akn("body"))
            if body is not None:
                _walk_body(body, paragraphs, 0)
            conclusions = act.find(_akn("conclusions"))
            if conclusions is not None:
                _walk_body(conclusions, paragraphs, 0)

            if not paragraphs:
                continue

            versions.append(
                Version(
                    norm_id=norm_id,
                    publication_date=pub_date,
                    effective_date=eff_date,
                    paragraphs=tuple(paragraphs),
                )
            )

        if not versions:
            return []

        return [
            Block(
                id="main",
                block_type="content",
                title="",
                versions=tuple(versions),
            )
        ]


# ─── MetadataParser ───


class LegiluxMetadataParser(MetadataParser):
    """Parse Legilux Akoma Ntoso XML metadata into NormMetadata."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        """Parse raw metadata into NormMetadata.

        The XML may be a multi-version envelope or a single Akoma Ntoso
        document. In either case, metadata is extracted from the first
        (original) Act's scl:JOLUXLegalResource block.
        """
        text = data.decode("utf-8", errors="replace")
        text = _CONTROL_RE.sub("", text)

        root = ET.fromstring(text)

        # If multi-version, find the first version's akomaNtoso
        if _tag(root) == "legilux-multi-version":
            for version_el in root:
                if _tag(version_el) != "version":
                    continue
                akn = version_el.find(_akn("akomaNtoso"))
                if akn is not None:
                    root = akn
                    break
                # Try the first child that looks like an act
                for child in version_el:
                    if _tag(child) in ("akomaNtoso", "act"):
                        root = child
                        break
                break

        act = root.find(_akn("act")) if _tag(root) != "act" else root
        if act is None:
            raise ValueError(f"No <act> element found for {norm_id}")

        meta = act.find(_akn("meta"))
        if meta is None:
            raise ValueError(f"No <meta> element found for {norm_id}")

        jolux = _get_jolux_values(meta)
        expr = _get_expression_values(meta)

        # Title — from expression, with whitespace normalization
        title = expr.get("title", "")
        short_title = expr.get("titleShort", "")
        if not title:
            # Fallback: try longTitle from preface
            preface = act.find(_akn("preface"))
            if preface is not None:
                lt = preface.find(_akn("longTitle"))
                if lt is not None:
                    title = _extract_text(lt).strip()
        if not title:
            title = f"[Untitled: {norm_id}]"
        # Normalize whitespace: replace literal \n sequences and runs of spaces
        title = title.replace("\\n", " ")
        title = re.sub(r"\s+", " ", title).strip()
        if short_title:
            short_title = short_title.replace("\\n", " ")
            short_title = re.sub(r"\s+", " ", short_title).strip()

        # Type / Rank
        type_uri = (jolux.get("typeDocument", [""]))[0]
        type_code = _strip_uri_prefix(type_uri, _TYPE_PREFIX)
        rank = Rank(_RANK_MAP.get(type_code, type_code.lower()))

        # Dates
        date_doc_str = (jolux.get("dateDocument", [""]))[0]
        pub_date = _parse_date(date_doc_str) or date(1900, 1, 1)

        pub_date_memorial_str = (jolux.get("publicationDate", [""]))[0]
        date_entry_str = (jolux.get("dateEntryInForce", [""]))[0]
        date_applicability_str = (jolux.get("dateApplicability", [""]))[0]

        # Status
        status_uri = (jolux.get("inForceStatus", [""]))[0]
        status_code = _strip_uri_prefix(status_uri, _STATUS_PREFIX)
        status = _STATUS_MAP.get(status_code, NormStatus.IN_FORCE)

        # Institutions
        institution_uris = jolux.get("responsibilityOf", [])
        institutions = [_strip_uri_prefix(u, _INST_PREFIX) for u in institution_uris]

        # Subjects
        subject_uris = jolux.get("subjectLevel1", []) + jolux.get("subjectLevel2", [])
        subjects = tuple(_strip_uri_prefix(u, _SUBJECT_PREFIX) for u in subject_uris)

        # Relations
        modifies = jolux.get("modifies", [])
        repeals = jolux.get("repeals", [])
        cites = jolux.get("cites", [])
        draft = (jolux.get("draft", [""]))[0]

        # Complex Work
        complex_work = (jolux.get("isMemberOf", [""]))[0]

        # Memorial
        memorial = (jolux.get("isPartOf", [""]))[0]

        # ELI URI (source URL)
        frbr_this = meta.find(f".//{_akn('FRBRWork')}/{_akn('FRBRthis')}")
        eli_uri = frbr_this.get("value", "") if frbr_this is not None else ""
        source_url = eli_uri
        if source_url and not source_url.startswith("http"):
            source_url = f"http://data.legilux.public.lu/{source_url}"

        # Department (first responsible institution)
        department = institutions[0] if institutions else ""

        # Build extra metadata
        extra_pairs: list[tuple[str, str]] = []
        if short_title:
            extra_pairs.append(("short_title", short_title))
        if pub_date_memorial_str:
            extra_pairs.append(("memorial_date", pub_date_memorial_str))
        if date_entry_str:
            extra_pairs.append(("entry_in_force", date_entry_str))
        if date_applicability_str:
            extra_pairs.append(("applicability_date", date_applicability_str))
        if memorial:
            extra_pairs.append(("memorial", memorial))
        if complex_work:
            extra_pairs.append(("complex_work", complex_work))
        if len(institutions) > 1:
            extra_pairs.append(("responsible_institutions", "; ".join(institutions)))
        if modifies:
            extra_pairs.append(("modifies", "; ".join(modifies)))
        if repeals:
            extra_pairs.append(("repeals", "; ".join(repeals)))
        if cites:
            extra_pairs.append(("cites", "; ".join(cites)))
        if draft:
            extra_pairs.append(("draft", draft))
        extra_pairs.append(("eli", eli_uri))

        return NormMetadata(
            title=title,
            short_title=short_title,
            identifier=norm_id,
            country="lu",
            rank=rank,
            publication_date=pub_date,
            status=status,
            department=department,
            source=source_url,
            subjects=subjects,
            extra=tuple(extra_pairs),
        )
