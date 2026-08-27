"""Every repo path a doc names — and every research note the code cites — must exist.

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

# Research notes are per-country working notes: they propose files that do not
# exist yet. They live under research/ once the country ships.
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


# The research notes are the only written explanation of why a country's fetcher
# is shaped the way it is, so a module comment citing one by name is a promise
# the reader can follow it. Five of those names had never existed in this repo
# at all — 17 pointers into nothing, in a public repo. We match the note's name
# rather than a path, because the citations are prose as often as backticks.
SOURCES = sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "tests").rglob("*.py"))

RESEARCH_RE = re.compile(r"\bRESEARCH-[A-Za-z0-9][A-Za-z0-9-]*")


def _cited_notes() -> list[tuple[Path, str]]:
    found = []
    for src in SOURCES:
        for name in RESEARCH_RE.findall(src.read_text()):
            found.append((src, name))
    return found


@pytest.mark.parametrize(
    "src,name", _cited_notes(), ids=lambda v: v.name if isinstance(v, Path) else v
)
def test_research_note_cited_in_code_exists(src: Path, name: str):
    note = ROOT / "research" / f"{name}.md"
    assert note.exists(), f"{src.name} cites {name}.md, which is not in research/"


def test_research_citations_are_actually_scanned():
    """Same trap as above: no citations found would pass the parametrised test
    with zero cases, which reads identical to "every citation resolves"."""
    assert len(_cited_notes()) > 5
