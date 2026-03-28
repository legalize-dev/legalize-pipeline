"""YAML frontmatter generation for norm Markdown files.

Generic multi-country format:
  ---
  titulo: "Constitución Española"
  identificador: "BOE-A-1978-31229"
  pais: "es"
  rango: "constitucion"
  fecha_publicacion: "1978-12-29"
  ultima_actualizacion: "2024-02-17"
  estado: "vigente"
  fuente: "https://www.boe.es/eli/es/c/1978/12/27/(1)"
  ---
"""

from __future__ import annotations

from datetime import date

from legalize.models import NormaMetadata


def render_frontmatter(metadata: NormaMetadata, version_date: date) -> str:
    """Generates the YAML frontmatter block for a norm at a given date."""
    titulo = _clean_titulo(metadata.titulo)

    lines = [
        "---",
        f'titulo: "{_escape_yaml(titulo)}"',
        f'identificador: "{metadata.identificador}"',
        f'pais: "{metadata.pais}"',
        f'rango: "{metadata.rango}"',
        f'fecha_publicacion: "{metadata.fecha_publicacion.isoformat()}"',
        f'ultima_actualizacion: "{version_date.isoformat()}"',
        f'estado: "{metadata.estado}"',
        f'fuente: "{metadata.fuente}"',
    ]

    if metadata.url_pdf:
        lines.append(f'url_pdf: "{metadata.url_pdf}"')

    lines.append("---")
    lines.append("")

    return "\n".join(lines)


def _escape_yaml(text: str) -> str:
    """Escapes double quotes in YAML values."""
    return text.replace('"', '\\"')


def _clean_titulo(titulo: str) -> str:
    """Cleans the title: remove trailing period, normalize spaces."""
    return titulo.rstrip(". ").strip()
