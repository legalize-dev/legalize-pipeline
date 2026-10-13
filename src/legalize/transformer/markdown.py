"""Markdown generation from legislative blocks.

Converts the Block/Version/Paragraph structure from BOE XML
into Markdown that mirrors the legal hierarchy.

Refactored 2026-04-22 (research/RESEARCH-ES-v2.md):
- Full CSS-class map covering libro/parte/titulo/cap/seccion/subseccion/
  articulo/anexo/apendice/disposiciones/firmas
- Blockquote rendering for cita/cita_con_pleca family
- Sangrado paragraphs keep their indentation level
- Dedicated pass-through for "table" and "image" CSS classes emitted by
  the XML parser when it meets a <table> or <img> element
- nota_pie rendered as an indented styled paragraph so the legislative
  audit trail survives
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
import re
from typing import Callable

from legalize.countries import text_state_for
from legalize.models import Block, NormMetadata, Paragraph, TextState
from legalize.transformer.frontmatter import render_frontmatter
from legalize.transformer.xml_parser import get_block_at_date


# ─────────────────────────────────────────────
# CSS class → Markdown mapping
# ─────────────────────────────────────────────

_SIMPLE_CSS_MAP: dict[str, Callable[[str], str]] = {
    # --- structural headings (no pair) ---
    "libro_num": lambda t: f"# {t}\n",
    "parte_num": lambda t: f"# {t}\n",
    "titulo": lambda t: f"## {t}\n",
    "titulo_tit": lambda t: f"## {t}\n",
    "capitulo_tit": lambda t: f"### {t}\n",
    "seccion": lambda t: f"#### {t}\n",
    "seccion_tit": lambda t: f"#### {t}\n",
    "subseccion": lambda t: f"##### {t}\n",
    "subseccion_tit": lambda t: f"##### {t}\n",
    "articulo": lambda t: f"###### {t}\n",
    "anexo": lambda t: f"### {t}\n",
    "anexo_num": lambda t: f"## {t}\n",
    "apendice": lambda t: f"### {t}\n",
    "apendice_num": lambda t: f"## {t}\n",
    "disp_num": lambda t: f"## {t}\n",
    # --- legacy / pseudo-centred headings ---
    "centro_redonda": lambda t: f"### {t}\n",
    "centro_negrita": lambda t: f"# {t}\n",
    "centro_cursiva": lambda t: f"### *{t}*\n",
    # --- emphasis / indent helpers ---
    "cita": lambda t: f"> {t}\n",
    "cita_con_pleca": lambda t: f"> {t}\n",
    "cita_ley": lambda t: f"> {t}\n",
    "cita_art": lambda t: f"> {t}\n",
    "sangrado": lambda t: f"    {t}\n",
    "sangrado_2": lambda t: f"        {t}\n",
    "sangrado_articulo": lambda t: f"    {t}\n",
    # --- nota_pie: reform provenance — keep as quoted small text ---
    "nota_pie": lambda t: f"> <small>{t}</small>\n",
    "nota_pie_2": lambda t: f"> <small>{t}</small>\n",
    # --- signatories ---
    "firma_rey": lambda t: f"**{t}**\n",
    "firma_ministro": lambda t: f"**{t}**\n",
    "firma": lambda t: f"**{t}**\n",
    # --- synthetic classes emitted by the XML parser ---
    "image": lambda t: f"{t}\n",
    "list_item": lambda t: f"{t}\n",
    "legal_quote": lambda t: f"{t}\n",
    "pre": lambda t: f"```\n{t}\n```\n",
    # --- generic fallbacks used by non-ES parsers (kept for back-compat) ---
    "h1": lambda t: f"# {t}\n",
    "h2": lambda t: f"## {t}\n",
    "h3": lambda t: f"### {t}\n",
    "h4": lambda t: f"#### {t}\n",
    "h5": lambda t: f"##### {t}\n",
    "h6": lambda t: f"###### {t}\n",
    "signature": lambda t: f"**{t}**\n",
    "preamble": lambda t: f"{t}\n",
    "formula": lambda t: f"{t}\n",
    "list": lambda t: f"{t}\n",
    "quote": lambda t: f"> {t}\n",
    "num": lambda t: f"{t}\n",
    # --- rendered tables pass through verbatim ---
    "table": lambda t: f"{t}\n",
    "table_row": lambda t: f"{t}\n",
}

# ─────────────────────────────────────────────
# Text-state notice (Legalize Format Spec v0.3)
# ─────────────────────────────────────────────

# Static on purpose: byte-identical in every file and every commit of a country.
# Everything that changes when an amendment lands — the date, the amending act —
# lives in the frontmatter, so the body of one of these files is written once at
# bootstrap and never rewritten. A count here ("amended 95 times") would be wrong
# on every later commit as soon as an older amendment is backfilled.
_NOTICES: dict[TextState, str] = {
    TextState.AS_ENACTED: (
        "> **This is the law as enacted. Amendments are not incorporated below — each one is\n"
        "> a separate file in this repository and a commit in this file's history.**\n"
    ),
    TextState.CURRENT: (
        "> **This file always contains the latest consolidated text published by the source.\n"
        "> It is not the text as it stood on the date of any given commit.**\n"
    ),
}


# Paired classes: num + tit merge into one heading.
_PAIRED_CLASSES: dict[str, tuple[str, str]] = {
    "libro_num": ("libro_tit", "#"),
    "parte_num": ("parte_tit", "#"),
    "titulo_num": ("titulo_tit", "##"),
    "capitulo_num": ("capitulo_tit", "###"),
    "seccion_num": ("seccion_tit", "####"),
    "subseccion_num": ("subseccion_tit", "#####"),
    "anexo_num": ("anexo_tit", "##"),
    "apendice_num": ("apendice_tit", "##"),
    "disp_num": ("disp_tit", "##"),
}


def render_paragraphs(paragraphs: list[Paragraph] | tuple[Paragraph, ...]) -> str:
    """Convert a list of paragraphs to Markdown."""
    lines: list[str] = []
    plist = list(paragraphs)
    i = 0

    while i < len(plist):
        p = plist[i]
        css = p.css_class
        text = p.text

        # Paired class: <num> + <tit> → one heading
        if css in _PAIRED_CLASSES:
            tit_class, prefix = _PAIRED_CLASSES[css]
            if i + 1 < len(plist) and plist[i + 1].css_class == tit_class:
                lines.append(f"{prefix} {text}. {plist[i + 1].text}")
                lines.append("")
                i += 2
                continue
            lines.append(f"{prefix} {text}")
            lines.append("")
            i += 1
            continue

        formatter = _SIMPLE_CSS_MAP.get(css)
        if formatter is not None:
            rendered = formatter(text).rstrip("\n")
            if rendered:
                # Explicit legal quote fragments share a CommonMark container.
                # An unquoted blank line closes it and turns later nested list
                # entries into code blocks. Other countries' quote classes keep
                # their existing byte-for-byte rendering.
                if css == "legal_quote" and i and plist[i - 1].css_class == "legal_quote":
                    previous = re.match(r"^([ \t]*>)(?: |$)", lines[-2].splitlines()[-1])
                    current = re.match(r"^([ \t]*>)(?: |$)", rendered)
                    if previous and current and previous[1] == current[1]:
                        lines[-1] = current[1]
                lines.append(rendered)
                lines.append("")
        else:
            # Unknown class — default to plain paragraph
            lines.append(text)
            lines.append("")

        i += 1

    return "\n".join(lines)


def render_norm_at_date(
    metadata: NormMetadata,
    blocks: list[Block] | tuple[Block, ...],
    target_date: date,
    include_all: bool = False,
    source_id: str | None = None,
) -> str:
    """Generate the complete Markdown for a norm at a given point in time."""
    selected = []
    for block in blocks:
        if metadata.country in {"eu", "ie"}:
            applicable = [
                v
                for v in block.versions
                if v.in_force_from <= target_date
                and not (
                    metadata.country == "ie"
                    and source_id is not None
                    and v.norm_id.startswith("revised-")
                    and v.in_force_from == target_date
                )
            ]
            version = (
                max(
                    applicable,
                    key=lambda v: (
                        v.in_force_from,
                        metadata.country == "ie" and v.norm_id != metadata.identifier,
                    ),
                )
                if applicable
                else None
            )
            version = next(
                (
                    v
                    for v in block.versions
                    if v.norm_id == source_id
                    and (v.in_force_from == target_date or v.publication_date == target_date)
                ),
                version,
            )
        else:
            version = get_block_at_date(block, target_date)
        selected.append(version)
    states = {v.text_state for v in selected if v is not None and v.text_state is not None}
    sources = {v.source for v in selected if v is not None and v.source}
    if len(states) > 1 or len(sources) > 1:
        raise ValueError(
            f"{metadata.identifier}: selected blocks disagree on their source or text state"
        )
    if states or sources:
        metadata = replace(
            metadata,
            text_state=next(iter(states), metadata.text_state),
            source=next(iter(sources), metadata.source),
        )
    warnings = list(
        dict.fromkeys(v.source_warning for v in selected if v is not None and v.source_warning)
    )
    if warnings or metadata.country == "ie":
        extra = dict(metadata.extra)
        # A source defect belongs to its snapshot, not every version of the law.
        extra.pop("source_warning", None)
        if warnings:
            extra["source_warning"] = " ".join(warnings)
        metadata = replace(metadata, extra=tuple(extra.items()))
    if metadata.country == "ie" and metadata.text_state is TextState.POINT_IN_TIME:
        # A later effect does not turn an archived body into a newer consolidation.
        target_date = max(v.in_force_from for v in selected if v is not None)
    if metadata.country == "eu":
        if include_all and not any(selected):
            selected = [
                min(b.versions, key=lambda v: v.in_force_from) if b.versions else None
                for b in blocks
            ]
        effective = [v.in_force_from for v in selected if v is not None]
        if effective:
            target_date = max(effective)
    parts: list[str] = []
    parts.append(render_frontmatter(metadata, target_date))

    title = metadata.title.rstrip(". ").strip()
    parts.append(f"# {title}\n\n")

    notice = _NOTICES.get(metadata.text_state or text_state_for(metadata.country))
    if notice:
        parts.append(f"{notice}\n")
    if source_warning := dict(metadata.extra).get("source_warning"):
        parts.append(f"> **Incomplete source:** {source_warning}\n\n")

    for block, version in zip(blocks, selected, strict=True):
        if version is None and include_all and metadata.country != "eu" and block.versions:
            version = min(block.versions, key=lambda v: v.publication_date)

        if version is None:
            continue

        md = render_paragraphs(version.paragraphs)
        if md.strip():
            parts.append(md)
            if not md.endswith("\n\n"):
                parts.append("\n")

    return "".join(parts).rstrip("\n") + "\n"
