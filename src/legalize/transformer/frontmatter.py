"""YAML frontmatter generation for norm Markdown files.

8 core fields (fixed order, all countries), then department/jurisdiction
if present, then country-specific extra fields from the source API.

  ---
  title: "Real Decreto Legislativo 2/2015..."
  identifier: "BOE-A-2015-11430"
  country: "es"
  rank: "real_decreto_legislativo"
  publication_date: "2015-10-24"
  last_updated: "2026-03-30"
  status: "in_force"
  source: "https://www.boe.es/eli/es/rdlg/2015/10/23/2"
  department: "Ministerio de Empleo y Seguridad Social"
  official_number: "2/2015"
  enactment_date: "2015-10-23"
  official_journal: "Boletín Oficial del Estado"
  journal_issue: "255"
  consolidation_status: "Finalizado"
  scope: "Estatal"
  ---
"""

from __future__ import annotations

from datetime import date

from legalize.countries import text_state_for
from legalize.models import NormMetadata, NormStatus, TextState


def render_frontmatter(metadata: NormMetadata, version_date: date) -> str:
    """Generates the YAML frontmatter block for a norm at a given date.

    Core fields first (fixed order), then department/jurisdiction,
    then extra fields from country-specific metadata.
    """
    clean_title = _clean_title(metadata.title)
    status = metadata.status.value if isinstance(metadata.status, NormStatus) else metadata.status

    lines = [
        "---",
        f'title: "{_escape_yaml(clean_title)}"',
        f'identifier: "{metadata.identifier}"',
        f'country: "{metadata.country}"',
        f'rank: "{metadata.rank}"',
        f'publication_date: "{metadata.publication_date.isoformat()}"',
        f'last_updated: "{version_date.isoformat()}"',
        f'status: "{status}"',
        f'source: "{metadata.source}"',
    ]

    # Spec v0.3: emitted only when the body is not the law in force at
    # last_updated, so files that already state the law correctly never change.
    state = metadata.text_state or text_state_for(metadata.country)
    if state is not TextState.POINT_IN_TIME:
        lines.append(f'text_state: "{state.value}"')
        if metadata.last_amendment:
            lines.append(f'last_amendment: "{_escape_yaml(metadata.last_amendment)}"')

    if metadata.department:
        lines.append(f'department: "{_escape_yaml(metadata.department)}"')
    if metadata.jurisdiction:
        lines.append(f'jurisdiction: "{metadata.jurisdiction}"')
    if metadata.pdf_url:
        lines.append(f'pdf_url: "{metadata.pdf_url}"')
    if metadata.subjects:
        subj_yaml = ", ".join(f'"{_escape_yaml(s)}"' for s in metadata.subjects)
        lines.append(f"subjects: [{subj_yaml}]")

    for key, value in metadata.extra:
        lines.append(f'{key}: "{_escape_yaml(value)}"')

    lines.append("---")
    lines.append("")

    return "\n".join(lines)


def _escape_yaml(text: str) -> str:
    """Escapes special characters for YAML double-quoted strings."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _clean_title(raw_title: str) -> str:
    """Cleans the title: remove trailing period, normalize spaces."""
    return raw_title.rstrip(". ").strip()
