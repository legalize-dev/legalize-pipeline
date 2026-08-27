"""Parsers for Lilex (gesetze.li) consolidated text and metadata.

Two outputs from one law fetch:
  - `LilexMetadataParser.parse(meta_html, lgbl)` → NormMetadata from the landing page
  - `LilexTextParser.parse_text(envelope_json)` → list[Block] with one
    Version per historical iframe HTML.

The envelope JSON is produced by `LilexClient.get_text()`. It contains
the meta page plus one HTML body per historical version. The text
parser walks the version list and emits Blocks/Versions in
chronological order.

CSS class map (validated against 5 fixtures: constitution, PGR, StGB,
Steuergesetz, recent ordinance):

| class             | Role                                | Markdown |
|-------------------|-------------------------------------|----------|
| htit1, htit2      | Main title / subtitle               | skip (already in frontmatter) |
| vom               | "vom DD. Monat YYYY"                | skip (already in frontmatter) |
| tit1m             | Hauptstück / Teil heading           | ## |
| tit1, tit1ue      | Title heading                       | ### |
| tit2, tit2m       | Subtitle                            | #### |
| tit3, tit3m, tit4*| Deeper sub-headings                 | ##### |
| tits              | Section title                       | #### |
| sacht             | Article subject heading             | bold |
| art (container)   | Article wrapper                     | emits article block |
| abs               | Numbered subsection ("1) ...")      | normal |
| ab                | Plain paragraph                     | normal |
| bst1, bst2        | Lettered list ("a) ...")            | "- a) ..." |
| ziff              | Numbered list ("1. ...")            | "- 1. ..." |
| roem              | Roman list ("I. ...")               | "- I. ..." |
| einl              | Preamble                            | normal |
| fntext            | Footnote text                       | "[^N]: ..." |
| gezf, gezr        | Signatures                          | bold |
| udat              | Place + date                        | italic |
| zent              | Centered text                       | normal |
| inkr              | "Inkrafttreten: ..."                | bold |
| abge              | "Abgeschlossen am ..."              | bold |
| inheintrag        | TOC entry                           | skip |
| strich            | Visual separator                    | skip |
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from html import unescape
from typing import Any

from lxml import html as lxml_html

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.fetcher.li.client import to_dotted_id, to_url_id
from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    Rank,
    Version,
)
from legalize.fetcher._text import strip_control

logger = logging.getLogger(__name__)

_HTML_PARSER = lxml_html.HTMLParser(encoding="utf-8")

_WHITESPACE_RE = re.compile(r"\s+")

# German month names → numeric month
_DE_MONTHS: dict[str, int] = {
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "maerz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
}


# ─── String helpers ──────────────────────────────────────────────────────


def _clean_text(text: str) -> str:
    """Strip control chars, collapse whitespace, trim."""
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = strip_control(text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def _parse_html_bytes(data: bytes):
    return lxml_html.fromstring(data, parser=_HTML_PARSER)


def _parse_html_str(text: str):
    if not text:
        return None
    return lxml_html.fromstring(text.encode("utf-8"), parser=_HTML_PARSER)


def _parse_german_long_date(s: str) -> date | None:
    """Parse 'DD. Monat YYYY' strings (e.g. '24. Oktober 1921')."""
    if not s:
        return None
    s = s.strip().rstrip(".")
    m = re.search(r"(\d{1,2})\.\s*(\w+)\s+(\d{4})", s)
    if not m:
        return None
    day, month_name, year = m.group(1), m.group(2).lower(), m.group(3)
    month = _DE_MONTHS.get(month_name)
    if not month:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def _parse_dotted_date(s: str) -> date | None:
    """Parse DD.MM.YYYY date strings."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


def _parse_version_date_text(text: str) -> date | None:
    """Parse the date label of a version dropdown entry.

    Examples:
      '01.01.2026'                       → date(2026, 1, 1)
      '01.02.2021 - 31.12.2025'          → date(2021, 2, 1)  (start of range)
    """
    if not text:
        return None
    head = text.split("-", 1)[0].strip()
    return _parse_dotted_date(head)


# ─── Rank inference ──────────────────────────────────────────────────────

# Ordered (specific → generic) so the first match wins.
# Keys are lower-cased substrings to look for in the title.
_RANK_PATTERNS: tuple[tuple[str, str], ...] = (
    ("verfassungsgesetz", "verfassungsgesetz"),
    ("verfassung ", "verfassung"),
    ("verfassung\n", "verfassung"),
    ("verfassung,", "verfassung"),
    ("verfassung.", "verfassung"),
    ("personen- und gesellschaftsrecht", "gesetz"),
    ("staatsvertrag", "staatsvertrag"),
    ("notenaustausch", "notenaustausch"),
    ("abkommen", "abkommen"),
    ("übereinkommen", "uebereinkommen"),
    ("uebereinkommen", "uebereinkommen"),
    ("konvention", "konvention"),
    ("protokoll", "protokoll"),
    ("kundmachung", "kundmachung"),
    ("verordnung", "verordnung"),
    ("regierungsbeschluss", "regierungsbeschluss"),
    ("beschluss", "beschluss"),
    ("erklärung", "erklaerung"),
    ("erklaerung", "erklaerung"),
    ("vereinbarung", "vereinbarung"),
    ("reglement", "reglement"),
    ("ordnung", "ordnung"),
    ("statut", "statut"),
    ("gesetz", "gesetz"),
)


def _infer_rank(title: str) -> str:
    lowered = title.lower()
    for needle, rank in _RANK_PATTERNS:
        if needle in lowered:
            return rank
    return "norm"


# ─── Metadata parser ─────────────────────────────────────────────────────


_LR_NR_FROM_LINK_RE = re.compile(r'/konso/gebietssystematik\?lrstart=([^"\']+)')
_KEYWORDS_RE = re.compile(r'<meta name="keywords"[^>]*content="([^"]+)"', re.IGNORECASE)
_DESC_RE = re.compile(r'<meta name="description"[^>]*content="([^"]*)"', re.IGNORECASE)
_HEADER_DATE_RE = re.compile(
    r"ausgegeben\s+am\s+([0-9]{1,2}\.\s*[A-Za-zÄÖÜäöüß]+\s+\d{4})", re.IGNORECASE
)
_VOM_RE = re.compile(r'<div class="vom">vom\s+([^<]+)</div>')


class LilexMetadataParser(MetadataParser):
    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        """Parse the meta-page HTML (or the JSON envelope) into NormMetadata."""
        # Caller may hand us either the raw meta HTML (when called directly) or
        # a JSON envelope. The envelope from LilexClient.get_metadata() carries
        # both meta_html and the current iframe HTML; the envelope from
        # LilexClient.get_text() has meta_html plus per-version blobs.
        meta_html, current_html = _select_meta_and_current_html(data)
        dotted = to_dotted_id(norm_id)
        url_id = to_url_id(norm_id)

        tree = _parse_html_bytes(meta_html.encode("utf-8"))

        title = _extract_title(tree)
        # Landing-page titles get clipped with "..." for long treaties; pull the
        # full title from the iframe's <meta description> when that happens or
        # when the landing page lacks an <h2>.
        if (not title or title.endswith("…") or title.endswith("...")) and current_html:
            desc = _DESC_RE.search(current_html)
            if desc:
                full = _clean_text(unescape(desc.group(1)))
                if full and len(full) > len(title or ""):
                    title = full
        if not title and current_html:
            # Final fallback: htit1 + htit2 from the iframe content.
            try:
                ctree = _parse_html_str(current_html)
                pieces = []
                for cls in ("htit1", "htit2"):
                    nodes = ctree.xpath(f'//div[@class="{cls}"]')
                    if nodes:
                        pieces.append(_clean_text(nodes[0].text_content()))
                title = " ".join(p for p in pieces if p).strip()
            except Exception:  # noqa: BLE001
                pass
        if not title:
            title = f"LGBl {dotted}"

        # The "ausgegeben am" (publication) header and the "vom" (enacted)
        # subtitle live inside the iframe HTML, not the landing page. Probe
        # both sources so we work whether the caller hands us a get_metadata
        # envelope, a get_text envelope, or a raw landing HTML.
        publication_date = _extract_publication_date(current_html) or _extract_publication_date(
            meta_html
        )
        enacted_date = _extract_enacted_date(current_html) or _extract_enacted_date(meta_html)
        lr_nr = _extract_lr_nr(tree, meta_html) or _extract_lr_nr_from_iframe(current_html)
        version_options = _extract_version_table(tree)

        # last_modified = effective date of the newest version (if any)
        last_modified: date | None = None
        if version_options:
            last_modified = _parse_version_date_text(version_options[0][1])

        rank = _infer_rank(title)

        identifier = _identifier_from_lgbl(dotted)
        source = f"https://www.gesetze.li/konso/{dotted}"
        pdf_url = f"https://www.gesetze.li/konso/pdf/{url_id}"

        # Extras — render as additional YAML keys after the core fields.
        # pdf_url is set via the dataclass field (rendered by the generic
        # frontmatter writer), so we don't duplicate it here.
        extra_pairs: list[tuple[str, str]] = []
        extra_pairs.append(("lgbl_nr", dotted))
        if lr_nr:
            extra_pairs.append(("lr_nr", lr_nr))
        if enacted_date:
            extra_pairs.append(("enacted_date", enacted_date.isoformat()))
        extra_pairs.append(("version_count", str(len(version_options) if version_options else 1)))
        extra_pairs.append(("materialien_url", f"https://www.gesetze.li/konso/{url_id}/meta"))

        if not publication_date:
            # Fall back to the year encoded in the LGBl number.
            publication_date = date(int(dotted[:4]), 1, 1)

        return NormMetadata(
            title=title,
            short_title=title.split(".")[0][:140],
            identifier=identifier,
            country="li",
            rank=Rank(rank),
            publication_date=publication_date,
            status=NormStatus.IN_FORCE,
            department="",
            source=source,
            jurisdiction=None,
            last_modified=last_modified,
            pdf_url=pdf_url,
            subjects=(),
            summary="",
            extra=tuple(extra_pairs),
        )


def _identifier_from_lgbl(lgbl: str) -> str:
    """Build a filesystem-safe identifier: 'LGBl-1921-015'."""
    year, num = lgbl.split(".")
    return f"LGBl-{year}-{int(num):03d}"


def _select_meta_and_current_html(data: bytes) -> tuple[str, str]:
    """Return (meta_html, current_html) from raw HTML, get_metadata envelope,
    or get_text envelope. Either side may be empty."""
    if not data:
        return "", ""
    head = data.lstrip()[:1]
    if head == b"{":
        try:
            envelope = json.loads(data)
        except json.JSONDecodeError:
            return data.decode("utf-8", errors="replace"), ""
        meta_html = envelope.get("meta_html", "") or ""
        if envelope.get("current_html"):
            return meta_html, envelope["current_html"]
        # get_text envelope: take the newest version's HTML.
        versions = envelope.get("versions", [])
        if versions:
            try:
                newest = max(versions, key=lambda v: int(v.get("version", 0)))
            except (TypeError, ValueError):
                newest = versions[-1]
            return meta_html, newest.get("html", "") or ""
        return meta_html, ""
    return data.decode("utf-8", errors="replace"), ""


def _extract_title(tree) -> str:
    h2 = tree.xpath('//h2[contains(@class, "law-title")]')
    if h2:
        return _clean_text(h2[0].text_content())
    h3 = tree.xpath('//h3[contains(@class, "metaseite")]')
    if h3:
        return _clean_text(h3[0].text_content())
    return ""


def _extract_publication_date(meta_html: str) -> date | None:
    m = _HEADER_DATE_RE.search(meta_html)
    if not m:
        return None
    return _parse_german_long_date(m.group(1))


def _extract_enacted_date(meta_html: str) -> date | None:
    m = _VOM_RE.search(meta_html)
    if not m:
        return None
    return _parse_german_long_date(m.group(1))


def _extract_lr_nr(tree, meta_html: str) -> str:
    # First try the metadata page table: <a href="/konso/gebietssystematik?lrstart=101">101</a>
    links = tree.xpath('//a[contains(@href, "lrstart=")]')
    if links:
        m = _LR_NR_FROM_LINK_RE.search(links[0].get("href", ""))
        if m:
            return m.group(1)
    # Fallback: <meta name="keywords"> on the iframe HTML
    m = _KEYWORDS_RE.search(meta_html)
    if m:
        return m.group(1).strip()
    return ""


def _extract_lr_nr_from_iframe(current_html: str) -> str:
    if not current_html:
        return ""
    m = _KEYWORDS_RE.search(current_html)
    return m.group(1).strip() if m else ""


def _extract_version_table(tree) -> list[tuple[int, str]]:
    """Return [(version, date_text), ...] from the meta page's <select name='version'>."""
    out: list[tuple[int, str]] = []
    selects = tree.xpath('//select[@name="version"]/option')
    seen: set[int] = set()
    for opt in selects:
        try:
            n = int(opt.get("value", ""))
        except (TypeError, ValueError):
            continue
        if n in seen:
            continue
        seen.add(n)
        out.append((n, _clean_text(opt.text_content())))
    return out


# ─── Text parser ─────────────────────────────────────────────────────────


# Source heading class → renderer CSS class. The renderer maps
# h1..h6 to # ... ###### Markdown headings.
_HEADING_LEVELS: dict[str, str] = {
    "tit1m": "h2",
    "tit1": "h3",
    "tit1ue": "h3",
    "tit2m": "h4",
    "tit2": "h4",
    "tits": "h4",
    "tit3m": "h5",
    "tit3": "h5",
    "tit4m": "h6",
    "tit4": "h6",
}

# Paragraph classes that always render as plain text body.
_BODY_CLASSES = frozenset({"abs", "ab", "einl", "zent", "ziff", "bst1", "bst2", "roem"})

# Classes to skip entirely (visual artifacts already captured in frontmatter).
_SKIP_CLASSES = frozenset({"htit1", "htit2", "vom", "strich", "inheintrag"})


def _node_classes(el) -> set[str]:
    cls = el.get("class") or ""
    return set(cls.split())


def _has_class(el, name: str) -> bool:
    return name in _node_classes(el)


def _inline_text(el) -> str:
    """Collect text from an element with inline <b>/<i>/<a> wrapping preserved.

    Footnote markers (`<sup>` inside an `<a href="#fnN">`) are converted to
    `[^N]` Markdown footnote references.
    """
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        tag = child.tag.lower() if isinstance(child.tag, str) else ""
        if tag in {"div", "table", "tr", "td", "th", "tbody", "thead", "col"}:
            # Block-level children are handled by the caller; preserve any tail
            # text so we don't drop "Art. 1" prefixes etc.
            if child.tail:
                parts.append(child.tail)
            continue
        if tag == "br":
            parts.append("\n")
        elif tag in {"b", "strong"}:
            inner = _inline_text(child).strip()
            if inner:
                parts.append(f"**{inner}**")
        elif tag in {"i", "em"}:
            inner = _inline_text(child).strip()
            if inner:
                parts.append(f"*{inner}*")
        elif tag == "sup":
            inner = _inline_text(child).strip()
            if inner:
                # Only digit-only <sup> are footnote refs. Visual separators
                # (e.g. `<sup>, </sup>` between two footnote anchors) come in
                # as text and must not be turned into `[^,]`.
                if inner.isdigit():
                    parts.append(f"[^{inner}]")
                else:
                    parts.append(inner)
        elif tag == "a":
            href = (child.get("href") or "").strip()
            inner = _inline_text(child).strip()
            if href.startswith("#fn") or href.startswith("#fr"):
                # Footnote anchors — handled via the inner <sup>; suppress the link.
                if inner:
                    parts.append(inner)
            elif href and inner:
                if href.startswith("/"):
                    href = f"https://www.gesetze.li{href}"
                parts.append(f"[{inner}]({href})")
            else:
                parts.append(inner)
        else:
            parts.append(_inline_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _list_marker_for_paragraph(para_class: str, raw_text: str) -> str:
    """Return a 'list bullet' prefix for bst1/bst2/ziff/roem paragraphs.

    The Lilex source already includes the marker (e.g. 'a)\\t...') in the
    text. We just convert it to a Markdown-list-friendly form.
    """
    # The HTML has a tab between marker and content. Replace with a single space.
    text = raw_text.replace("\t", " ").strip()
    return f"- {text}"


def _build_paragraphs_from_node(node) -> list[Paragraph]:
    """Walk a top-level node (article body, einleitung, signature block, etc.)
    and emit Paragraphs in document order.

    Lists (bst1/ziff/roem) are emitted as `list_item` paragraphs with
    a `- ` prefix already applied. Plain text uses `parrafo`.
    """
    out: list[Paragraph] = []
    classes = _node_classes(node)

    if classes & _SKIP_CLASSES:
        return out

    # Headings (tit1m/tit2 etc.) — emit using renderer-recognized h2..h6 classes.
    for cls, h_class in _HEADING_LEVELS.items():
        if cls in classes:
            text = _clean_text(_inline_text(node))
            if text:
                out.append(Paragraph(css_class=h_class, text=text))
            return out

    # Article container — emit "##### Art. N" then walk children.
    if "art" in classes:
        out.extend(_paragraphs_from_article(node))
        return out

    # Footnote text: "[^N]: ..."
    if "fntext" in classes:
        text = _inline_text(node)
        cleaned = _clean_text(text)
        # The leading "1\xa0Art. 1 abgeändert durch ..." has the ref number
        # attached. Rewrite to "[^1]: Art. 1 abgeändert..."
        m = re.match(r"^\[?\^?(\d+)\]?\s*[:.\)]?\s*(.*)$", cleaned)
        if m:
            cleaned = f"[^{m.group(1)}]: {m.group(2).strip()}"
        if cleaned:
            out.append(Paragraph(css_class="parrafo", text=cleaned))
        return out

    # Signatures (gez. Karl, gez. Johann)
    if "gezf" in classes or "gezr" in classes:
        text = _clean_text(_inline_text(node))
        if text:
            out.append(Paragraph(css_class="firma_rey", text=text))
        return out

    # Place + date below signatures
    if "udat" in classes:
        text = _clean_text(_inline_text(node))
        if text:
            out.append(Paragraph(css_class="parrafo", text=f"*{text}*"))
        return out

    # Treaty markers (Inkrafttreten, Abgeschlossen am)
    if classes & {"inkr", "abge"}:
        text = _clean_text(_inline_text(node))
        if text:
            out.append(Paragraph(css_class="firma_rey", text=text))
        return out

    # Body paragraph types
    if classes & {"einl", "ab", "abs", "zent"} and not classes & {"bst1", "bst2", "ziff", "roem"}:
        out.extend(_paragraphs_from_block(node))
        return out

    # Lists (when standalone, not nested under abs)
    if classes & {"bst1", "bst2", "ziff", "roem"}:
        text = _clean_text(_inline_text(node))
        if text:
            out.append(
                Paragraph(
                    css_class="list_item",
                    text=_list_marker_for_paragraph(node.get("class", ""), text),
                )
            )
        # Recurse only into BLOCK children (nested lists / continuation paragraphs).
        # Inline children (<a>, <sup>, <b>, ...) are already captured by _inline_text.
        for child in node:
            if not isinstance(child.tag, str):
                continue
            if child.tag.lower() != "div":
                continue
            out.extend(_build_paragraphs_from_node(child))
        return out

    # Tables: skip the LGBl banner table; convert real data tables to MD pipe.
    if isinstance(node.tag, str) and node.tag.lower() == "table":
        if _is_banner_table(node):
            return out
        md = _table_to_markdown(node)
        if md:
            out.append(Paragraph(css_class="table", text=md))
        return out

    # Sachtitel (article subject heading)
    if "sacht" in classes:
        text = _clean_text(_inline_text(node))
        if text:
            out.append(Paragraph(css_class="parrafo", text=f"**{text}**"))
        return out

    # Fallback: emit children recursively, or this node's plain text.
    if len(node):
        for child in node:
            if isinstance(child.tag, str):
                out.extend(_build_paragraphs_from_node(child))
        if node.text and node.text.strip():
            out.insert(0, Paragraph(css_class="parrafo", text=_clean_text(node.text)))
    else:
        text = _clean_text(_inline_text(node))
        if text:
            out.append(Paragraph(css_class="parrafo", text=text))
    return out


def _paragraphs_from_block(node) -> list[Paragraph]:
    """For an `abs`/`einl`/`ab` div: emit one paragraph for the leading text,
    then recurse into nested list-class children.
    """
    out: list[Paragraph] = []
    # Leading text with inline siblings (b, i, sup, a) until first block child
    leading_parts: list[str] = []
    if node.text:
        leading_parts.append(node.text)
    nested: list = []
    for child in node:
        if not isinstance(child.tag, str):
            continue
        cls = _node_classes(child)
        is_block_child = child.tag.lower() == "div" and (
            cls & {"bst1", "bst2", "ziff", "roem", "abs", "fntext"}
        )
        if is_block_child:
            nested.append(child)
            if child.tail:
                leading_parts.append(child.tail)
        elif child.tag.lower() == "br":
            leading_parts.append("\n")
            if child.tail:
                leading_parts.append(child.tail)
        else:
            # Inline (b/i/sup/a) — render with formatting and continue.
            tag = child.tag.lower()
            inner = _inline_text(child).strip()
            if tag in {"b", "strong"} and inner:
                leading_parts.append(f"**{inner}**")
            elif tag in {"i", "em"} and inner:
                leading_parts.append(f"*{inner}*")
            elif tag == "sup" and inner:
                if inner.isdigit():
                    leading_parts.append(f"[^{inner}]")
                else:
                    leading_parts.append(inner)
            elif tag == "a":
                href = (child.get("href") or "").strip()
                if href.startswith("#fn") or href.startswith("#fr"):
                    if inner:
                        leading_parts.append(inner)
                elif href and inner:
                    if href.startswith("/"):
                        href = f"https://www.gesetze.li{href}"
                    leading_parts.append(f"[{inner}]({href})")
                else:
                    leading_parts.append(inner)
            else:
                leading_parts.append(_inline_text(child))
            if child.tail:
                leading_parts.append(child.tail)

    leading = _clean_text("".join(leading_parts))
    if leading:
        out.append(Paragraph(css_class="parrafo", text=leading))

    for child in nested:
        out.extend(_build_paragraphs_from_node(child))

    return out


def _paragraphs_from_article(art_node) -> list[Paragraph]:
    """Render an `<div class="art">` element.

    Structure observed:
        <div class="art">
            <a name="art:N"></a>Art. N[<sup>...]
            <div class="abs">1) ...</div>
            <div class="abs">2) ...</div>
            ...
        </div>
    """
    out: list[Paragraph] = []

    # Article header: "Art. N" with optional footnote ref.
    # Use _inline_text on the article element but exclude block-level children.
    head_parts: list[str] = []
    if art_node.text:
        head_parts.append(art_node.text)
    for child in art_node:
        if not isinstance(child.tag, str):
            continue
        if child.tag.lower() == "div":
            break  # subsequent <div> children are body blocks
        tag = child.tag.lower()
        inner = _inline_text(child).strip()
        if tag in {"b", "strong"} and inner:
            head_parts.append(f"**{inner}**")
        elif tag in {"i", "em"} and inner:
            head_parts.append(f"*{inner}*")
        elif tag == "sup" and inner:
            if inner.isdigit():
                head_parts.append(f"[^{inner}]")
            else:
                head_parts.append(inner)
        elif tag == "a":
            href = (child.get("href") or "").strip()
            if href.startswith("#fn") or href.startswith("#fr"):
                if inner:
                    head_parts.append(inner)
            elif href and inner:
                if href.startswith("/"):
                    href = f"https://www.gesetze.li{href}"
                head_parts.append(f"[{inner}]({href})")
        if child.tail:
            head_parts.append(child.tail)
    head = _clean_text("".join(head_parts))
    if head:
        # `articulo` already maps to "##### {text}" in the renderer — don't add
        # an extra prefix here.
        out.append(Paragraph(css_class="articulo", text=head))

    for child in art_node:
        if not isinstance(child.tag, str):
            continue
        if child.tag.lower() != "div":
            continue
        out.extend(_build_paragraphs_from_node(child))

    return out


# ─── Tables ──────────────────────────────────────────────────────────────


def _is_banner_table(table_node) -> bool:
    """The LGBl banner table appears at the top of every law (and again at
    every amendment merge point). Recognize it by its content markers.
    """
    text = (table_node.text_content() or "").lower()
    return (
        "liechtensteinisches landesgesetzblatt" in text
        or "ausgegeben am" in text
        and "jahrgang" in text
    )


def _table_to_markdown(table_node) -> str:
    """Render an HTML table as a Markdown pipe table.

    Liechtenstein consolidated text rarely contains real data tables (every
    `<table>` in the 5 fixtures was the LGBl banner). This implementation
    is conservative: take all <tr> rows, take their <td>/<th> cells, render
    a header row from the first row, and render the body from the rest.
    """
    rows: list[list[str]] = []
    for tr in table_node.iter("tr"):
        cells: list[str] = []
        for cell in tr:
            if not isinstance(cell.tag, str):
                continue
            if cell.tag.lower() not in {"td", "th"}:
                continue
            text = _clean_text(_inline_text(cell)).replace("|", "\\|")
            cells.append(text)
        if cells:
            rows.append(cells)

    if not rows:
        return ""

    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    header = rows[0]
    sep = ["---"] * width
    body = rows[1:] if len(rows) > 1 else []

    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(sep) + " |"]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


# ─── Top-level text parsing ──────────────────────────────────────────────


def _parse_one_version_html(html_text: str) -> list[tuple[str, str, list[Paragraph]]]:
    """Parse one version's iframe HTML into a list of (block_id, block_type, paragraphs).

    Articles become individual blocks. Structural headings (Hauptstück,
    Titel, Section) become their own blocks so they appear in source
    order between articles. Preamble text (before any heading or article)
    and final clauses (after the last article) become synthetic blocks.
    """
    if not html_text:
        return []

    tree = _parse_html_str(html_text)
    if tree is None:
        return []

    body = tree.find(".//body") if tree.tag != "body" else tree
    if body is None:
        body = tree

    state = _WalkState()
    _walk_top_level(body, state)

    blocks = list(state.blocks)
    if state.pre_paras:
        blocks.insert(0, ("preamble", "preamble", state.pre_paras))
    if state.final_paras:
        blocks.append(("final-clause", "final", state.final_paras))
    if state.fn_paras:
        blocks.append(("footnotes", "footnotes", state.fn_paras))

    return blocks


class _WalkState:
    """Mutable accumulator passed through the recursive top-level walker."""

    __slots__ = (
        "blocks",
        "article_count",
        "heading_count",
        "pre_paras",
        "final_paras",
        "fn_paras",
        "seen_first_article",
        "anchor_occurrences",
    )

    def __init__(self) -> None:
        self.blocks: list[tuple[str, str, list[Paragraph]]] = []
        self.article_count = 0
        self.heading_count = 0
        self.pre_paras: list[Paragraph] = []
        self.final_paras: list[Paragraph] = []
        self.fn_paras: list[Paragraph] = []
        self.seen_first_article = False
        # Some codes (PGR, ABGB) restart article numbering inside each
        # Abteilung, so the same `<a name="art:1">` anchor appears multiple
        # times. Track occurrences to keep block ids unique.
        self.anchor_occurrences: dict[str, int] = {}


def _walk_top_level(parent, state: _WalkState) -> None:
    """Walk a parent's children, handling articles/headings/footnotes/etc.

    Unrecognised `<div>` containers (wrappers around Abteilungen) are
    recursed into so the articles inside them get picked up.
    """
    for node in parent:
        if not isinstance(node.tag, str):
            continue
        tag = node.tag.lower()
        if tag == "script":
            continue

        classes = _node_classes(node) if tag == "div" else set()

        # 1. Article container.
        if tag == "div" and "art" in classes:
            state.seen_first_article = True
            state.article_count += 1
            anchor = node.find(".//a[@name]")
            anchor_name = (
                anchor.get("name") if anchor is not None else ""
            ) or f"art-{state.article_count}"
            base_id = anchor_name.replace(":", "-")
            occurrence = state.anchor_occurrences.get(base_id, 0) + 1
            state.anchor_occurrences[base_id] = occurrence
            block_id = base_id if occurrence == 1 else f"{base_id}-{occurrence}"
            paras = _paragraphs_from_article(node)
            if paras:
                state.blocks.append((block_id, "article", paras))
            continue

        # 2. Structural heading: emit as its own block to preserve source order.
        heading_class = next((c for c in classes if c in _HEADING_LEVELS), None)
        if heading_class:
            state.heading_count += 1
            text = _clean_text(_inline_text(node))
            if text:
                hp = Paragraph(css_class=_HEADING_LEVELS[heading_class], text=text)
                state.blocks.append((f"heading-{state.heading_count}", "heading", [hp]))
            continue

        # 3. Footnote text (amendment annotations) — collect at the end.
        if "fntext" in classes:
            state.fn_paras.extend(_build_paragraphs_from_node(node))
            continue

        # 4. Bare wrapper <div>: recurse so we don't miss nested articles.
        if tag == "div" and not classes:
            _walk_top_level(node, state)
            continue

        # 5. Anything else: preamble (before first article) or final-clause.
        node_paras = _build_paragraphs_from_node(node)
        if not node_paras:
            continue
        if state.seen_first_article:
            state.final_paras.extend(node_paras)
        else:
            state.pre_paras.extend(node_paras)


class LilexTextParser(TextParser):
    """Parse the JSON envelope produced by LilexClient into Blocks/Versions."""

    def parse_text(self, data: bytes) -> list[Any]:
        envelope = _decode_envelope(data)
        if not envelope:
            return []
        lgbl = envelope.get("lgbl", "")
        identifier = _identifier_from_lgbl(lgbl) if lgbl else "unknown"
        versions_raw: list[dict] = envelope.get("versions", [])

        # Per-version parsed structure.
        # Each version gets a synthetic per-version source id (the LGBl number
        # plus the version index, e.g. "LGBl-1921-015-v44") so that
        # extract_reforms() emits one Reform per version and the committer's
        # idempotency check doesn't collapse them into a single commit.
        version_blocks: list[tuple[date, str, list[tuple[str, str, list[Paragraph]]]]] = []
        for entry in versions_raw:
            html_text = entry.get("html") or ""
            v_date = _parse_version_date_text(entry.get("date_text", "")) or _fallback_date(lgbl)
            v_num = entry.get("version", 0)
            v_source_id = f"{identifier}-v{int(v_num):03d}" if v_num else identifier
            blocks = _parse_one_version_html(html_text)
            version_blocks.append((v_date, v_source_id, blocks))

        if not version_blocks:
            return []

        # Aggregate by block id across versions.
        # Block order = order from the newest version (most stable / current text).
        newest_blocks = version_blocks[-1][2]
        block_order: list[str] = [bid for bid, _, _ in newest_blocks]
        block_index: dict[str, tuple[str, str]] = {
            bid: (bid, btype) for bid, btype, _ in newest_blocks
        }
        # Make sure blocks that only existed in older versions are still emitted
        # (ordered after the current text).
        for _, _, blocks in version_blocks:
            for bid, btype, _ in blocks:
                if bid not in block_index:
                    block_index[bid] = (bid, btype)
                    block_order.append(bid)

        # For each block id, compose its Versions tuple in chronological order.
        # If a block exists in version N but disappears in version N+1, emit a
        # sentinel "repealed" Version with empty paragraphs at the disappear
        # date. The renderer treats empty paragraphs as no-content, so the
        # block won't render at later dates.
        result: list[Block] = []
        for bid in block_order:
            block_versions: list[Version] = []
            last_signature: tuple | None = None
            was_present = False
            for v_date, v_source_id, blocks in version_blocks:
                paras = next(
                    (p for b_id, _, p in blocks if b_id == bid),
                    None,
                )
                if paras is None:
                    if was_present:
                        # Block was present in a previous version but is gone
                        # now. Emit one repeal sentinel and stop tracking this
                        # block — further versions also lack it.
                        block_versions.append(
                            Version(
                                norm_id=v_source_id,
                                publication_date=v_date,
                                effective_date=v_date,
                                paragraphs=(),
                            )
                        )
                        was_present = False
                        last_signature = ()
                    continue
                was_present = True
                signature = tuple((p.css_class, p.text) for p in paras)
                if signature == last_signature:
                    # Block didn't change in this version; skip the duplicate.
                    continue
                last_signature = signature
                block_versions.append(
                    Version(
                        norm_id=v_source_id,
                        publication_date=v_date,
                        effective_date=v_date,
                        paragraphs=tuple(paras),
                    )
                )
            if not block_versions:
                continue
            _, btype = block_index[bid]
            title = _block_title(bid, block_versions[-1].paragraphs)
            result.append(
                Block(
                    id=bid,
                    block_type=btype,
                    title=title,
                    versions=tuple(block_versions),
                )
            )
        return result


def _decode_envelope(data: bytes) -> dict:
    if not data:
        return {}
    head = data.lstrip()[:1]
    if head != b"{":
        # Treat as a single-version raw HTML for backwards compatibility.
        return {
            "lgbl": "",
            "url_id": "",
            "meta_html": "",
            "versions": [
                {
                    "version": 1,
                    "date_text": "",
                    "html": data.decode("utf-8", errors="replace"),
                }
            ],
        }
    try:
        return json.loads(data)
    except json.JSONDecodeError as exc:
        logger.error("Could not decode envelope JSON: %s", exc)
        return {}


def _fallback_date(lgbl: str) -> date:
    """When a version has no parseable date, fall back to Jan 1 of the LGBl year."""
    if lgbl and "." in lgbl:
        try:
            return date(int(lgbl.split(".")[0]), 1, 1)
        except ValueError:
            pass
    return date(1900, 1, 1)


def _block_title(block_id: str, paragraphs: tuple[Paragraph, ...]) -> str:
    """Pick a human-readable title for a Block (used in commit subjects, etc.)."""
    for p in paragraphs:
        if p.css_class == "articulo":
            return p.text.strip()
    if block_id == "preamble":
        return "Präambel"
    if block_id == "final-clause":
        return "Schlussbestimmungen"
    if block_id == "footnotes":
        return "Fussnoten"
    return block_id
