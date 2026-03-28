"""Markdown generation from legislative blocks.

Converts the Bloque/Version/Paragraph structure from BOE XML
into readable Markdown, with headings reflecting the legal hierarchy.
"""

from __future__ import annotations

from datetime import date
from typing import Callable

from legalize.models import Bloque, NormaMetadata, Paragraph
from legalize.transformer.frontmatter import render_frontmatter
from legalize.transformer.xml_parser import get_bloque_at_date


# ─────────────────────────────────────────────
# Mapeo CSS class → Markdown (data-driven)
# ─────────────────────────────────────────────

# Format functions for simple CSS classes (no lookahead)
_SIMPLE_CSS_MAP: dict[str, Callable[[str], str]] = {
    "titulo": lambda t: f"## {t}\n",
    "titulo_tit": lambda t: f"## {t}\n",
    "capitulo_tit": lambda t: f"### {t}\n",
    "seccion": lambda t: f"#### {t}\n",
    "articulo": lambda t: f"##### {t}\n",
    "centro_redonda": lambda t: f"### {t}\n",
    "centro_negrita": lambda t: f"# {t}\n",
    "firma_rey": lambda t: f"**{t}**\n",
    "firma_ministro": lambda t: f"{t}\n",
}

# Classes requiring lookahead (combination with the next paragraph)
_PAIRED_CLASSES: dict[str, str] = {
    "titulo_num": "titulo_tit",
    "capitulo_num": "capitulo_tit",
}


def render_paragraphs(paragraphs: list[Paragraph] | tuple[Paragraph, ...]) -> str:
    """Converts a list of paragraphs to Markdown.

    Handles the combination of pairs (titulo_num + titulo_tit → ## Num. Tit)
    and applies the CSS→Markdown mapping for each paragraph.
    """
    lines: list[str] = []
    i = 0
    plist = list(paragraphs)

    while i < len(plist):
        p = plist[i]
        css = p.css_class
        text = p.text

        # Check if it's a paired class (num + tit)
        if css in _PAIRED_CLASSES:
            expected_next = _PAIRED_CLASSES[css]
            if i + 1 < len(plist) and plist[i + 1].css_class == expected_next:
                # Combine: "## TÍTULO I. De los derechos..."
                heading_level = "##" if css == "titulo_num" else "###"
                combined = f"{heading_level} {text}. {plist[i + 1].text}"
                lines.append(combined)
                lines.append("")
                i += 2
                continue
            else:
                # Number only, no following title
                heading_level = "##" if css == "titulo_num" else "###"
                lines.append(f"{heading_level} {text}")
                lines.append("")
                i += 1
                continue

        # Simple classes with direct mapping
        formatter = _SIMPLE_CSS_MAP.get(css)
        if formatter:
            lines.append(formatter(text).rstrip("\n"))
            lines.append("")
        else:
            # Normal paragraph (parrafo, parrafo_2, etc.)
            lines.append(text)
            lines.append("")

        i += 1

    return "\n".join(lines)


def render_norma_at_date(
    metadata: NormaMetadata,
    bloques: list[Bloque] | tuple[Bloque, ...],
    target_date: date,
) -> str:
    """Generates the complete Markdown for a norm at a given point in time.

    Includes YAML frontmatter + H1 title + body with all blocks in effect.

    Args:
        metadata: Norm metadata.
        bloques: List of blocks with their historical versions.
        target_date: Date for which to generate the version.

    Returns:
        String with the complete Markdown document.
    """
    parts: list[str] = []

    # Frontmatter
    parts.append(render_frontmatter(metadata, target_date))

    # H1 title (without trailing period)
    titulo = metadata.titulo.rstrip(". ").strip()
    parts.append(f"# {titulo}\n\n")

    # Blocks in effect at the date
    for bloque in bloques:
        version = get_bloque_at_date(bloque, target_date)
        if version is None:
            continue

        md = render_paragraphs(version.paragraphs)
        if md.strip():
            parts.append(md)
            # Ensure separation between blocks
            if not md.endswith("\n\n"):
                parts.append("\n")

    return "".join(parts)
