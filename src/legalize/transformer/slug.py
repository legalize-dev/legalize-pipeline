"""File path generation for norms.

The shape of the path is the repo's own, declared in ``.legalize.yml`` and
implemented once in :mod:`legalize.layout`. This module only decides *which
directory* a norm belongs to, which is the one part the spec derives from the
file rather than from the identifier.

Example: es/BOE-A-1978-31229.md          (flat)
         es/bb/BOE-A-1978-31229.md       (sharded)
         es-pv/BOE-A-2020-615.md         (jurisdiction as the directory)
"""

from __future__ import annotations

from legalize.layout import law_path, layout_for
from legalize.models import NormMetadata


def norm_to_filepath(metadata: NormMetadata) -> str:
    """Generates the path for a norm file.

    The directory is the norm's ``jurisdiction`` where it has one and its
    ``country`` otherwise — stated in the file, never inferred from the path,
    so a consumer holding a law's metadata can rebuild the path without
    listing the repo (spec v0.4, §Directories).
    """
    directory = metadata.jurisdiction or metadata.country
    return law_path(directory, metadata.identifier, layout_for(metadata.country))
