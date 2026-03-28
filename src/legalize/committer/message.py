"""Structured commit message construction.

Generic multi-country format:
    [type] Title — affected articles

    Norma: BOE-A-1978-31229
    Disposición: BOE-A-2024-3099
    Fecha: 2024-02-17
    URL: https://www.boe.es/...
    Artículos afectados: Artículo 49

    Source-Id: BOE-A-2024-3099
    Source-Date: 2024-02-17
    Norm-Id: BOE-A-1978-31229
"""

from __future__ import annotations

import re

from legalize.committer.author import resolve_author
from legalize.models import (
    Bloque,
    CommitInfo,
    CommitType,
    NormaMetadata,
    Reform,
)


def build_commit_info(
    commit_type: CommitType,
    norma_metadata: NormaMetadata,
    reform: Reform,
    bloques: list[Bloque] | tuple[Bloque, ...],
    file_path: str,
    content: str,
) -> CommitInfo:
    """Builds a complete CommitInfo from domain data."""
    articulos = _get_articulos_afectados(reform, bloques)
    arts_str = ", ".join(articulos) if articulos else "N/A"

    subject = _build_subject(commit_type, norma_metadata, reform, articulos)
    body = _build_body(commit_type, norma_metadata, reform, arts_str)

    # Generic trailers (not Spain-specific)
    trailers = {
        "Source-Id": reform.id_norma,
        "Source-Date": reform.fecha.isoformat(),
        "Norm-Id": norma_metadata.identificador,
    }

    author_name, author_email = resolve_author()

    return CommitInfo(
        commit_type=commit_type,
        subject=subject,
        body=body,
        trailers=trailers,
        author_name=author_name,
        author_email=author_email,
        author_date=reform.fecha,
        file_path=file_path,
        content=content,
    )


def format_commit_message(info: CommitInfo) -> str:
    """Formats the CommitInfo as a complete git commit message."""
    parts = [info.subject, "", info.body]

    if info.trailers:
        parts.append("")
        for key, value in info.trailers.items():
            parts.append(f"{key}: {value}")

    return "\n".join(parts)


def _build_subject(
    commit_type: CommitType,
    metadata: NormaMetadata,
    reform: Reform,
    articulos: list[str] | None = None,
) -> str:
    """Builds the first line of the commit message.

    [reforma] Constitución Española — art. 49
    """
    prefix = f"[{commit_type.value}]"
    titulo = metadata.titulo_corto

    if commit_type == CommitType.BOOTSTRAP:
        return f"{prefix} {titulo} — versión original {reform.fecha.year}"

    if commit_type == CommitType.FIX_PIPELINE:
        return f"{prefix} Regenerar {titulo}"

    if articulos:
        arts_brief = _abbreviate_articulos(articulos)
        if arts_brief:
            return f"{prefix} {titulo} — {arts_brief}"

    return f"{prefix} {titulo}"


def _build_body(
    commit_type: CommitType,
    metadata: NormaMetadata,
    reform: Reform,
    articulos_str: str,
) -> str:
    """Builds the commit message body."""
    fecha_str = reform.fecha.isoformat()

    if commit_type == CommitType.BOOTSTRAP:
        return (
            f"Publicación original de {metadata.titulo_corto}.\n"
            f"\n"
            f"Norma: {metadata.identificador}\n"
            f"Fecha: {fecha_str}\n"
            f"Fuente: {metadata.fuente}"
        )

    return (
        f"Norma: {metadata.identificador}\n"
        f"Disposición: {reform.id_norma}\n"
        f"Fecha: {fecha_str}\n"
        f"Fuente: {metadata.fuente}\n"
        f"\n"
        f"Artículos afectados: {articulos_str}"
    )


def _abbreviate_articulos(articulos: list[str]) -> str:
    """Abbreviates the list of articles for the commit subject.

    ['Artículo 49'] → 'art. 49'
    ['Artículo 13', 'Artículo 14'] → 'arts. 13, 14'
    """
    nums = []
    for art in articulos:
        match = re.search(r"(\d+)", art)
        if match:
            nums.append(match.group(1))

    if not nums:
        return ""

    if len(nums) == 1:
        return f"art. {nums[0]}"

    if len(nums) <= 4:
        return f"arts. {', '.join(nums)}"

    shown = ", ".join(nums[:3])
    return f"arts. {shown} y {len(nums) - 3} más"


def _get_articulos_afectados(
    reform: Reform, bloques: list[Bloque] | tuple[Bloque, ...]
) -> list[str]:
    """Identifies the titles of the articles affected by a reform."""
    titulos = []
    bloque_map = {b.id: b for b in bloques}
    for bid in reform.bloques_afectados:
        bloque = bloque_map.get(bid)
        if bloque and bloque.titulo:
            titulos.append(bloque.titulo)
    return titulos
