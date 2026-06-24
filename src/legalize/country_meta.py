"""Per-country presentation metadata for generated repo files (README, ...).

This is the human-facing layer the rest of the pipeline lacks: country name,
native language, data source, license and attribution. It is consumed by
:mod:`legalize.committer.repo_meta` to generate each country repo's README in
its own language. Pipeline behavior (fetch / transform / commit) does NOT depend
on this module.

The actual content lives in the bundled data file ``readme_data.json`` (single
source of truth, easy to regenerate). This module loads it into typed
:class:`CountryMeta` objects and exposes the shared section :data:`LABELS`.

Only countries present in :data:`COUNTRY_META` get a generated README. Countries
not listed still get ``.github/FUNDING.yml`` (handled in ``repo_meta``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class NormType:
    """A category of norm shown in the README "what's inside" section."""

    label: str
    pattern: str = ""
    examples: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class CountryMeta:
    """Presentation metadata for one country repo's README.

    ``notes`` is free-form Markdown (already in the country's language) appended
    before the "other countries" section — use it for source-specific content
    that does not fit the structured fields (data-license statement, history
    reconstruction details, known limitations, ...).
    """

    code: str
    name: str  # country name in its own language
    language: str  # native language code (es, fr, de, ...)
    source_name: str
    source_urls: tuple[str, ...] = ()  # pre-formatted "Label: url" lines
    data_license: str = "Dominio público"
    scope: str = ""  # one-paragraph scope summary
    norm_types: tuple[NormType, ...] = field(default_factory=tuple)
    attribution: str = ""  # optional blockquote Markdown
    notes: str = ""  # optional extra Markdown (own headings allowed)


_DATA_PATH = Path(__file__).with_name("readme_data.json")
_RAW = json.loads(_DATA_PATH.read_text(encoding="utf-8"))


def _build(code: str, d: dict) -> CountryMeta:
    return CountryMeta(
        code=d.get("code", code),
        name=d["name"],
        language=d["language"],
        source_name=d["source_name"],
        source_urls=tuple(d.get("source_urls", ())),
        data_license=d.get("data_license", "Dominio público"),
        scope=d.get("scope", ""),
        norm_types=tuple(
            NormType(
                label=nt["label"],
                pattern=nt.get("pattern", ""),
                examples=tuple(nt.get("examples", ())),
                note=nt.get("note", ""),
            )
            for nt in d.get("norm_types", ())
        ),
        attribution=d.get("attribution", ""),
        notes=d.get("notes", ""),
    )


# Shared README section labels per language (English master + translations).
LABELS: dict[str, dict[str, str]] = _RAW["labels"]

COUNTRY_META: dict[str, CountryMeta] = {
    code: _build(code, d) for code, d in _RAW["countries"].items()
}
