"""Every repo path a doc names must exist.

Docs rot silently: a file moves, the sentence that points at it does not. This
caught `scripts/render_sample.py` (told you to write it, never shipped it) and
`web/.github/workflows/sync.yml` (moved to another repo entirely). Cross-repo
paths are skipped — CI only checks out this repo — so keep those to a minimum.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# RESEARCH-*.md are per-country working notes: they propose files that do not
# exist yet, and they are deleted once the country ships.
DOCS = [p for p in ROOT.glob("*.md") if not p.name.startswith("RESEARCH-")]
DOCS += sorted((ROOT / "adding-a-country").glob("*.md"))
DOCS.sort()

# Backticked token that starts at a known repo root.
PATH_RE = re.compile(
    r"`((?:src/|tests/|scripts/|\.github/|fetcher/)[\w./{}-]*[\w}]|config\.yaml|pyproject\.toml)`"
)

# Placeholders stand for a country that does not exist yet.
PLACEHOLDER_RE = re.compile(r"\{|(^|/)(xx|XX)(/|\.|$)")


def _resolve(raw: str) -> Path:
    """`fetcher/es/client.py` is written relative to `src/legalize/`."""
    if raw.startswith("fetcher/"):
        return ROOT / "src" / "legalize" / raw
    return ROOT / raw


def _named_paths() -> list[tuple[Path, str]]:
    found = []
    for doc in DOCS:
        for raw in PATH_RE.findall(doc.read_text()):
            if not PLACEHOLDER_RE.search(raw):
                found.append((doc, raw))
    return found


@pytest.mark.parametrize(
    "doc,raw", _named_paths(), ids=lambda v: v.name if isinstance(v, Path) else v
)
def test_path_named_in_docs_exists(doc: Path, raw: str):
    assert _resolve(raw).exists(), f"{doc.name} points at {raw}, which does not exist"


def test_docs_are_actually_scanned():
    """A broken regex would make the parametrised test vacuously pass."""
    assert len(_named_paths()) > 20
