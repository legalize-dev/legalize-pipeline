"""File path generation for norms.

Structure: {category}/{identificador}.md
The repo already indicates the country (legalize-es, legalize-fr), no need to repeat it.

Example: leyes/BOE-A-2015-11430.md
"""

from __future__ import annotations

from legalize.models import NormaMetadata, Rango

# Mapping of rank → folder in the repo
RANGO_FOLDERS: dict[str, str] = {
    # Spain
    "constitucion": "constituciones",
    "ley_organica": "leyes-organicas",
    "ley": "leyes",
    "real_decreto_ley": "reales-decretos-leyes",
    "real_decreto_legislativo": "reales-decretos-legislativos",
    "real_decreto": "reales-decretos",
    "orden": "ordenes",
    "resolucion": "resoluciones",
    "acuerdo_internacional": "acuerdos-internacionales",
    "circular": "circulares",
    "instruccion": "instrucciones",
    "decreto": "decretos",
    "acuerdo": "acuerdos",
    "reglamento": "reglamentos",
    # France
    "code": "codes",
    "loi_organique": "lois-organiques",
    "loi": "lois",
    "ordonnance": "ordonnances",
    "decret": "decrets",
    "constitution_fr": "constitutions",
}

DEFAULT_FOLDER = "otros"


def rango_to_folder(rango: str | Rango) -> str:
    """Converts a normative rank to folder name."""
    rango_str = str(rango)
    return RANGO_FOLDERS.get(rango_str, DEFAULT_FOLDER)


def norma_to_filepath(metadata: NormaMetadata) -> str:
    """Generates the path: '{category}/{identificador}.md'.

    Example: 'leyes/BOE-A-2015-11430.md'
    """
    folder = rango_to_folder(metadata.rango)
    filename = f"{metadata.identificador}.md"
    return f"{folder}/{filename}"
