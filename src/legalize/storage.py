"""Local storage for raw and structured data.

Saves to the private repo (pipeline):
- data/xml/{id}.xml     — Raw BOE XML (original source)
- data/json/{id}.json   — Structured data ready for DB

The JSON contains all the information needed to populate the DB
without re-downloading or re-parsing anything.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from legalize.models import (
    NormaCompleta,
)

logger = logging.getLogger(__name__)


def save_raw_xml(data_dir: str | Path, identificador: str, xml_bytes: bytes) -> Path:
    """Save the raw BOE XML."""
    path = Path(data_dir) / "xml" / f"{identificador}.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(xml_bytes)
    logger.debug("XML saved: %s", path)
    return path


def save_structured_json(data_dir: str | Path, norma: NormaCompleta) -> Path:
    """Save structured data as DB-ready JSON.

    JSON structure:
    {
        "metadata": { titulo, identificador, pais, rango, ... },
        "articles": [
            {
                "block_id": "a135",
                "block_type": "precepto",
                "title": "Artículo 135",
                "position": 42,
                "current_text": "...",
                "versions": [
                    {
                        "date": "1978-12-29",
                        "source_id": "BOE-A-1978-31229",
                        "text": "..."
                    },
                    ...
                ]
            }
        ],
        "reforms": [
            {
                "date": "1992-08-28",
                "source_id": "BOE-A-1992-20403",
                "articles_affected": ["Artículo 13"]
            },
            ...
        ]
    }
    """
    data = _norma_to_dict(norma)
    path = Path(data_dir) / "json" / f"{norma.metadata.identificador}.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.debug("JSON saved: %s", path)
    return path


def _norma_to_dict(norma: NormaCompleta) -> dict:
    """Convert a NormaCompleta to a serializable dict."""
    meta = norma.metadata

    # Metadata
    metadata_dict = {
        "titulo": meta.titulo.rstrip(". "),
        "titulo_corto": meta.titulo_corto,
        "identificador": meta.identificador,
        "pais": meta.pais,
        "rango": str(meta.rango),
        "fecha_publicacion": meta.fecha_publicacion.isoformat(),
        "ultima_actualizacion": (
            meta.fecha_ultima_modificacion.isoformat()
            if meta.fecha_ultima_modificacion
            else meta.fecha_publicacion.isoformat()
        ),
        "estado": meta.estado.value,
        "departamento": meta.departamento,
        "fuente": meta.fuente,
    }

    if meta.url_pdf:
        metadata_dict["url_pdf"] = meta.url_pdf
    if meta.materias:
        metadata_dict["materias"] = list(meta.materias)

    # Articles with all their versions
    articles = []
    for i, bloque in enumerate(norma.bloques):
        article = {
            "block_id": bloque.id,
            "block_type": bloque.tipo,
            "title": bloque.titulo,
            "position": i,
            "versions": [],
        }

        for version in bloque.versions:
            text = "\n\n".join(p.text for p in version.paragraphs)
            article["versions"].append({
                "date": version.fecha_publicacion.isoformat(),
                "source_id": version.id_norma,
                "text": text,
            })

        # current_text = latest version
        if bloque.versions:
            last = max(bloque.versions, key=lambda v: v.fecha_publicacion)
            article["current_text"] = "\n\n".join(p.text for p in last.paragraphs)
        else:
            article["current_text"] = ""

        articles.append(article)

    # Reforms
    bloque_map = {b.id: b for b in norma.bloques}
    reforms = []
    for reform in norma.reforms:
        affected = []
        for bid in reform.bloques_afectados:
            b = bloque_map.get(bid)
            if b and b.titulo:
                affected.append(b.titulo)

        reforms.append({
            "date": reform.fecha.isoformat(),
            "source_id": reform.id_norma,
            "articles_affected": affected,
        })

    return {
        "metadata": metadata_dict,
        "articles": articles,
        "reforms": reforms,
    }
