"""Parse Justice Canada Point-in-Time (PIT) HTML into Paragraphs.

PIT snapshots (``.../{id}/{YYYYMMDD}/P1TT3xt3.html``) use the same
structural vocabulary as the XML consolidations, just rendered to HTML
with CSS classes instead of XML elements. The mapping is direct:

============================  =================================
HTML                          Conceptual equivalent
============================  =================================
``section class="intro"``     root <Introduction> preamble
``h2 class="Title-of-Act"``   <ShortTitle>
``p class="LongTitle"``       <LongTitle>
``p class="Section"``         <Section>
``p class="Subsection"``      <Subsection>
``p class="Paragraph"``       <Paragraph>
``p class="Subparagraph"``    <Subparagraph>
``span class="sectionLabel"`` Section label (``1``)
``span class="lawlabel"``     Subsection/paragraph label
                              (``(1)``, ``(a)``, ``(i)``)
``p class="MarginalNote"``    <MarginalNote>
``p class="Continued…"``      <ContinuedParagraph> / similar
``cite class="XRefExternal*"``  <XRefExternal>
``span class="DefinedTerm"``  <DefinedTermEn>/<DefinedTermFr>
``p class="HistoricalNote"``  <HistoricalNote>
============================  =================================

The output matches what :meth:`CATextParser._parse_root` emits from XML
so downstream rendering (``render_norm_at_date``) treats PIT-HTML
versions and XML versions interchangeably. The diff at the 2002/2011
boundary (pre-PIT fallback if we ever add one) is thus contained to a
few frontmatter fields, exactly the same "clean transition" story as
the PDF↔XML boundary.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

from lxml import html as lxml_html

from legalize.models import Paragraph

logger = logging.getLogger(__name__)


_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def parse_pit_html(html_bytes: bytes, lang: str = "en") -> list[Paragraph]:
    """Parse a ``P1TT3xt3.html`` snapshot into a list of :class:`Paragraph`.

    The input is the raw HTML body of one PIT snapshot. We extract the
    main ``<div id="wb-cont">`` container (the document contents) and
    walk its structural blocks in document order.
    """
    if not html_bytes:
        return []

    try:
        doc = lxml_html.fromstring(html_bytes)
    except (lxml_html.etree.ParserError, ValueError) as exc:
        logger.warning("PIT HTML parse failed: %s", exc)
        return []

    root = doc.xpath("//*[@id='wb-cont']")
    if not root:
        # Some older snapshots don't carry the wb-cont id — fall back to
        # a broad search for the main content section.
        root = doc.xpath("//main") or doc.xpath("//body") or [doc]
    container = root[0]

    paragraphs: list[Paragraph] = []
    _walk(container, paragraphs, lang)
    return paragraphs


# ─────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────


def _clean(text: str) -> str:
    """Normalize whitespace and strip C0/C1 control chars.

    ``str.split()`` + ``" ".join(...)`` is a C-level idiom that collapses
    every run of whitespace (including ``\\xa0`` non-breaking spaces, tabs,
    newlines, form feeds) and strips ends — equivalent to the old
    ``replace \\xa0 → _CTRL_RE.sub → re.sub(\\s+) → .strip()`` chain but
    about 4× faster and called ~4 M times per Criminal Code parse.
    """
    if not text:
        return ""
    if _CTRL_RE.search(text):
        text = _CTRL_RE.sub("", text)
    return " ".join(text.split())


def _classes(el) -> set[str]:
    raw = el.get("class") or ""
    return set(raw.split())


_SKIP_NESTED_CLASS_TOKENS: tuple[str, ...] = (
    "MarginalNote",
    "HistoricalNote",
    "wb-invisible",
)


def _make_nested_skip(also_classes: Iterable[str] = ()):
    """Return a predicate that matches the descendants ``_strip_nested`` used to drop.

    Mirrors the historical XPath selector (``.//ul | .//ol | .//*[contains(@class,
    'MarginalNote')] | .//*[@class='sectionLabel'] | .//*[@class='lawlabel'] |
    .//*[contains(@class, 'HistoricalNote')] | .//*[contains(@class, 'wb-invisible')]``
    plus any caller-supplied also_classes), but without ever cloning the tree.
    Used by :func:`_inline_text` so the recursion can short-circuit at those
    subtrees in-place — this avoids the O(n) ``copy.deepcopy`` that used to
    dominate Criminal Code parsing (~26 s of 103 s cProfile'd).
    """
    extras = tuple(also_classes) if also_classes else ()

    def skip(el) -> bool:
        tag = el.tag
        if tag == "ul" or tag == "ol":
            return True
        cls = el.get("class")
        if not cls:
            return False
        if cls == "sectionLabel" or cls == "lawlabel":
            return True
        for token in _SKIP_NESTED_CLASS_TOKENS:
            if token in cls:
                return True
        for extra in extras:
            if extra in cls:
                return True
        return False

    return skip


# Pre-built predicates for the two call sites that used ``_strip_nested``.
# Building these once at import time avoids the per-call closure allocation
# in the hot paths (``_emit_section``, ``_emit_paragraph``, ``_emit_definition``).
_SECTION_SKIP = _make_nested_skip()
_DEFINITION_SKIP = _make_nested_skip(("DefinedTerm", "DefinedTermLink"))


def _inline_text(el, skip_pred=None) -> str:
    """Recursive inline text extractor mirroring the XML parser's one.

    Preserves Markdown-level formatting for:

    - ``cite class="XRefExternalAct"`` → ``[text](url)`` using the href
      attribute on the child ``<a>`` when present.
    - ``span class="DefinedTerm"`` / ``DefinedTermLink`` → ``*italic*``.
    - ``strong`` / ``b`` → ``**bold**``.
    - ``em`` / ``i`` → ``*italic*``.
    - ``span class="wb-invisible"`` → skipped (accessibility label, not
      rendered text).
    - ``span class="wb-inv"`` → skipped (same accessibility idiom).
    - ``span class="sectionLabel"`` / ``span class="lawlabel"`` →
      rendered as-is (the caller decides whether to bold them).

    Everything else recurses by default.

    ``skip_pred`` (optional) is a callable evaluated on every descendant
    before the normal dispatch. When it returns True the subtree is
    omitted entirely (tail text is still preserved). This replaces the
    old ``_strip_nested`` + deepcopy pattern.
    """
    if el is None:
        return ""

    parts: list[str] = []
    if el.text:
        parts.append(el.text)

    for child in el:
        if skip_pred is not None and skip_pred(child):
            if child.tail:
                parts.append(child.tail)
            continue

        tag = child.tag.lower() if isinstance(child.tag, str) else ""
        cls = _classes(child)

        # Accessibility-only spans carry text duplicated elsewhere —
        # skipping them avoids "Marginal note: Marginal note:" artifacts.
        if "wb-invisible" in cls or "wb-inv" in cls:
            if child.tail:
                parts.append(child.tail)
            continue

        if tag == "cite" and (
            "XRefExternalAct" in cls or "XRefExternalReg" in cls or "XRefExternal" in cls
        ):
            # The inner <a> carries both the link text and the target URL.
            # Use text_content() directly instead of recursing — otherwise
            # the inner <a>'s branch also wraps as [text](url) and we end
            # up with nested "[[text](url)](url)" markers.
            anchors = child.xpath(".//a")
            href = anchors[0].get("href", "").strip() if anchors else ""
            label = _clean(child.text_content())
            if label and href:
                if href.startswith("/"):
                    href = f"https://laws-lois.justice.gc.ca{href}"
                parts.append(f"[{label}]({href})")
            elif label:
                parts.append(label)
        elif tag == "a":
            href = child.get("href", "").strip()
            label = _clean(child.text_content())
            if label and href and not href.startswith("#"):
                if href.startswith("/"):
                    href = f"https://laws-lois.justice.gc.ca{href}"
                parts.append(f"[{label}]({href})")
            elif label:
                parts.append(label)
        elif tag in ("strong", "b"):
            child_text = _inline_text(child, skip_pred)
            stripped = child_text.strip()
            if stripped:
                parts.append(f"**{stripped}**")
        elif tag in ("em", "i", "dfn"):
            child_text = _inline_text(child, skip_pred)
            stripped = child_text.strip()
            if stripped:
                parts.append(f"*{stripped}*")
        elif tag == "span" and ("DefinedTerm" in cls or "DefinedTermLink" in cls):
            child_text = _inline_text(child, skip_pred)
            stripped = child_text.strip()
            if stripped:
                parts.append(f"*{stripped}*")
        elif tag == "span" and ("sectionLabel" in cls or "lawlabel" in cls):
            # Label text is consumed by the caller — don't duplicate it.
            pass
        else:
            parts.append(_inline_text(child, skip_pred))

        if child.tail:
            parts.append(child.tail)

    return "".join(parts)


def _section_label(el, *, prefer_lawlabel: bool = False) -> str:
    """Return the ``sectionLabel`` or first ``lawlabel`` text for a block.

    Canadian drafting sometimes carries BOTH a sectionLabel and a
    lawlabel inside a ``<p class="Subsection">`` — the sectionLabel
    repeats the parent section's number while the lawlabel carries the
    actual subsection marker ``(1)``, ``(2)`` etc. For subsection blocks
    we want the lawlabel; for top-level sections we want the
    sectionLabel. ``prefer_lawlabel`` switches the priority.
    """
    first = "lawlabel" if prefer_lawlabel else "sectionLabel"
    second = "sectionLabel" if prefer_lawlabel else "lawlabel"
    labels = el.xpath(f".//span[@class='{first}']")
    if labels:
        return _clean(labels[0].text_content())
    labels = el.xpath(f".//span[@class='{second}']")
    if labels:
        return _clean(labels[0].text_content())
    return ""


def _marginal_note_for(el) -> str:
    """Return the preceding MarginalNote sibling's text (or empty)."""
    prev = el.getprevious()
    while prev is not None:
        cls = _classes(prev)
        if "MarginalNote" in cls:
            return _clean(_inline_text(prev))
        # Skip whitespace-only text nodes.
        if prev.tag is lxml_html.etree.Comment or not (prev.text_content() or "").strip():
            prev = prev.getprevious()
            continue
        break
    return ""


def _walk(container, paragraphs: list[Paragraph], lang: str) -> None:
    """Walk a container emitting Paragraphs in document order.

    We recurse through descendants looking for blocks with one of the
    known CSS classes. Nesting is handled by recursing on children only
    when the parent block doesn't fully cover them — sections with a
    ``ProvisionList`` nest subsections inside ``<li>`` children, so the
    outer block's recursive pass discovers them naturally.
    """
    for child in container:
        if child.tag is lxml_html.etree.Comment:
            continue
        cls = _classes(child)

        if "Title-of-Act" in cls:
            txt = _clean(_inline_text(child))
            if txt:
                paragraphs.append(Paragraph(css_class="titulo_tit", text=txt))
        elif "ChapterNumber" in cls:
            txt = _clean(_inline_text(child))
            if txt:
                paragraphs.append(Paragraph(css_class="parrafo", text=f"*{txt}*"))
        elif "LongTitle" in cls:
            txt = _clean(_inline_text(child))
            if txt:
                paragraphs.append(Paragraph(css_class="parrafo", text=f"> {txt}"))
        elif "Part" in cls and child.tag.lower() in ("h1", "h2"):
            txt = _clean(_inline_text(child))
            if txt:
                paragraphs.append(Paragraph(css_class="titulo_tit", text=txt))
        elif "HTitleText1" in cls or "HTitleText2" in cls or "Subheading" in cls:
            txt = _clean(_inline_text(child))
            if txt:
                paragraphs.append(Paragraph(css_class="capitulo_tit", text=txt))
        elif "MarginalNote" in cls:
            # Handled inline when we emit the following Section/Subsection.
            # A bare MarginalNote (no following block) still deserves to
            # surface as an italicized paragraph so its content isn't lost.
            nxt = child.getnext()
            if nxt is None:
                txt = _clean(_inline_text(child))
                if txt:
                    paragraphs.append(Paragraph(css_class="parrafo", text=f"*{txt}*"))
            # Otherwise skip — next block will consume it.
        elif "Section" in cls or "Subsection" in cls:
            _emit_section(child, paragraphs, cls)
            # Sections can hold nested ProvisionList children (ul.ProvisionList)
            # whose <li> elements wrap deeper Subsections/Paragraphs. Only walk
            # DIRECT li children here — ``_walk_li_children`` recurses into any
            # nested ProvisionList it finds inside each li, so the descendant
            # xpath (``.//li``) we used before was double-counting every li
            # under nested Sections up to ~350× on Criminal Code structures.
            for li in child.xpath("./li"):
                _walk_li_children(li, paragraphs)
        elif "ProvisionList" in cls:
            # Standalone provision list (rare — usually wrapped by Section).
            for li in child.xpath("./li"):
                _walk_li_children(li, paragraphs)
        elif "HistoricalNote" in cls:
            items = child.xpath(".//*[@class='HistoricalNoteSubItem']")
            if items:
                bits = [_clean(_inline_text(i)) for i in items]
                bits = [b for b in bits if b]
                if bits:
                    paragraphs.append(Paragraph(css_class="parrafo", text=f"> *{'; '.join(bits)}*"))
            else:
                txt = _clean(_inline_text(child))
                if txt:
                    paragraphs.append(Paragraph(css_class="parrafo", text=f"> *{txt}*"))
        elif "Schedule" in cls:
            _emit_schedule(child, paragraphs)
        elif "Definition" in cls:
            _emit_definition(child, paragraphs)
        elif "ContinuedSectionSubsection" in cls or "ContinuedParagraph" in cls:
            txt = _clean(_inline_text(child))
            if txt:
                paragraphs.append(Paragraph(css_class="parrafo", text=txt))
        elif cls & {"container", "row", "tocBar", "wb-txthl", "info", "archiveBar"}:
            # Layout/chrome wrappers — recurse through them to find real
            # content buried inside.
            _walk(child, paragraphs, lang)
        elif "intro" in cls or child.tag.lower() == "section":
            # Generic <section> containers nest content directly.
            _walk(child, paragraphs, lang)
        else:
            # Unknown block — recurse so we don't lose buried content.
            # Plain <p> with no recognised class gets emitted as body text.
            if child.tag.lower() == "p":
                txt = _clean(_inline_text(child))
                if txt:
                    paragraphs.append(Paragraph(css_class="parrafo", text=txt))
            elif list(child):
                _walk(child, paragraphs, lang)


def _walk_li_children(li, paragraphs: list[Paragraph]) -> None:
    """Emit paragraphs from an ``<li>`` wrapping subsections / paragraphs.

    Keeps the outer section's position in document order so ``render_*``
    sees a single flat paragraph list rather than a tree.
    """
    for child in li:
        if child.tag is lxml_html.etree.Comment:
            continue
        cls = _classes(child)
        if "MarginalNote" in cls:
            # Consumed by the next block (Subsection/Paragraph).
            continue
        if "Subsection" in cls or "Section" in cls:
            _emit_section(child, paragraphs, cls)
            # Direct li children only — see ``_walk`` for the rationale.
            for inner_li in child.xpath("./li"):
                _walk_li_children(inner_li, paragraphs)
        elif "Paragraph" in cls:
            _emit_paragraph(child, paragraphs)
        elif "Subparagraph" in cls:
            _emit_paragraph(child, paragraphs, css_class="parrafo")
        elif "ContinuedSectionSubsection" in cls or "ContinuedParagraph" in cls:
            txt = _clean(_inline_text(child))
            if txt:
                paragraphs.append(Paragraph(css_class="parrafo", text=txt))
        elif "ProvisionList" in cls:
            for inner_li in child.xpath("./li"):
                _walk_li_children(inner_li, paragraphs)


def _emit_section(el, paragraphs: list[Paragraph], cls: set[str]) -> None:
    """Emit a Section or Subsection block with its label + marginal note.

    Output mirrors the XML parser's output:
        [articulo] "N {marginal_note}"
        [parrafo]  "**(1)** *note* body text"

    Section blocks can be either self-contained ``<p class="Section">``
    (direct text body) or ``<ul class="Section ProvisionList">`` which
    delegates its body to nested ``<li>`` children. In the second case we
    emit only the articulo header here and let the caller's recursive
    ``_walk_li_children`` pass render the subsections.
    """
    is_section = "Section" in cls and "Subsection" not in cls
    is_provision_list = el.tag.lower() == "ul" or "ProvisionList" in cls
    label = _section_label(el, prefer_lawlabel=not is_section)
    marginal = _marginal_note_for(el)

    if is_section and label:
        head_parts: list[str] = [label]
        if marginal:
            head_parts.append(marginal)
        paragraphs.append(Paragraph(css_class="articulo", text=" ".join(head_parts)))

    # When the Section is a ProvisionList (ul), its text body lives inside
    # the <li> children — the recursive walk handles those. Emitting a body
    # paragraph from the outer <ul> here would duplicate each subsection.
    if is_provision_list:
        return

    txt = _clean(_inline_text(el, _SECTION_SKIP))
    if txt:
        prefix_parts: list[str] = []
        if not is_section and label:
            prefix_parts.append(f"**{label}**")
        if not is_section and marginal:
            prefix_parts.append(f"*{marginal}*")
        prefix = " ".join(prefix_parts)
        paragraphs.append(
            Paragraph(
                css_class="parrafo",
                text=f"{prefix} {txt}".strip() if prefix else txt,
            )
        )


def _emit_paragraph(el, paragraphs: list[Paragraph], css_class: str = "parrafo") -> None:
    """Emit a <p class="Paragraph"> / Subparagraph — typically ``(a)``, ``(b)``."""
    label = ""
    label_spans = el.xpath(".//span[@class='lawlabel']")
    if label_spans:
        label = _clean(label_spans[0].text_content())
    txt = _clean(_inline_text(el, _SECTION_SKIP))
    if txt:
        body = f"**{label}** {txt}".strip() if label else txt
        paragraphs.append(Paragraph(css_class=css_class, text=body))


def _emit_definition(el, paragraphs: list[Paragraph]) -> None:
    """Emit a <p class="Definition"> block.

    Definitions pair a DefinedTerm (italic) with its explanatory text.
    We render them on one line so the italic term is visually adjacent
    to the definition, matching the XML parser's convention.
    """
    term_spans = el.xpath(".//*[contains(@class, 'DefinedTerm')]")
    term = _clean(_inline_text(term_spans[0])) if term_spans else ""
    # Strip the term out of the body text to avoid duplication.
    body = _clean(_inline_text(el, _DEFINITION_SKIP))
    if term and body:
        paragraphs.append(Paragraph(css_class="parrafo", text=f"*{term}* {body}"))
    elif term:
        paragraphs.append(Paragraph(css_class="parrafo", text=f"*{term}*"))
    elif body:
        paragraphs.append(Paragraph(css_class="parrafo", text=body))


def _emit_schedule(el, paragraphs: list[Paragraph]) -> None:
    """Emit a Schedule block as a title + flattened contents.

    Schedules in PIT HTML use ``<div class="Schedule">`` with an inner
    ``scheduleLabel`` heading and a body of paragraphs/tables.
    """
    label_els = el.xpath(".//*[contains(@class, 'scheduleLabel')]")
    label = _clean(_inline_text(label_els[0])) if label_els else ""
    if label:
        paragraphs.append(Paragraph(css_class="titulo_tit", text=label))
    # Walk immediate block children for body prose.
    for child in el:
        if child.tag is lxml_html.etree.Comment:
            continue
        cls = _classes(child)
        if cls & {"scheduleLabel"}:
            continue
        txt = _clean(_inline_text(child))
        if txt:
            paragraphs.append(Paragraph(css_class="parrafo", text=txt))
