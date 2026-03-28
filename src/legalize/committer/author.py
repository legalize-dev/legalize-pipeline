"""Git commit authorship.

All commits use the same author: Legalize.
"""

from __future__ import annotations

AUTHOR_NAME = "Legalize"
AUTHOR_EMAIL = "legalize@legalize.es"


def resolve_author() -> tuple[str, str]:
    """Returns (name, email) for the commit author."""
    return AUTHOR_NAME, AUTHOR_EMAIL
