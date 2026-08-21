"""Markdown generation from legislative blocks.

Converts the Block/Version/Paragraph structure from BOE XML
into Markdown that mirrors the legal hierarchy.

Refactored 2026-04-22 (RESEARCH-ES-v2.md):
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

from datetime import date
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
) -> str:
    """Generate the complete Markdown for a norm at a given point in time."""
    parts: list[str] = []
    parts.append(render_frontmatter(metadata, target_date))

    title = metadata.title.rstrip(". ").strip()
    parts.append(f"# {title}\n\n")

    notice = _NOTICES.get(metadata.text_state or text_state_for(metadata.country))
    if notice:
        parts.append(f"{notice}\n")

    for block in blocks:
        version = get_block_at_date(block, target_date)

        if version is None and include_all and block.versions:
            version = min(block.versions, key=lambda v: v.publication_date)

        if version is None:
            continue

        md = render_paragraphs(version.paragraphs)
        if md.strip():
            parts.append(md)
            if not md.endswith("\n\n"):
                parts.append("\n")

    return "".join(parts).rstrip("\n") + "\n"
