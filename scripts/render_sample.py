#!/usr/bin/env python3
"""Render the Step-7 fixtures of a country to Markdown, for the quality gate.

Between review rounds you edit parser.py and need fresh Markdown for the same
five laws. This does that in one command, so no round is spent hand-rendering.

    python scripts/render_sample.py xx tests/fixtures/xx/*.xml
    python scripts/render_sample.py xx LAW-2024-1=tests/fixtures/xx/a.xml.gz

The norm ID defaults to the filename stem (minus .gz); override it with
``ID=path`` when the fixture is not named after the law. See
adding-a-country/step-7-quality-gate.md.
"""

from __future__ import annotations

import argparse
import gzip
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from legalize.countries import get_metadata_parser, get_text_parser  # noqa: E402
from legalize.transformer.markdown import render_norm_at_date  # noqa: E402


def split_arg(arg: str) -> tuple[str, Path]:
    """``ID=path`` or ``path``; the bare form derives the ID from the stem."""
    norm_id, sep, raw = arg.partition("=")
    if not sep:
        raw, norm_id = arg, Path(arg).name.removesuffix(".gz").rsplit(".", 1)[0]
    return norm_id, Path(raw)


def read_fixture(path: Path) -> bytes:
    """Fixtures are stored plain or gzipped; both are read the same way here."""
    if path.suffix == ".gz":
        return gzip.decompress(path.read_bytes())
    return path.read_bytes()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("code", help="Country code, e.g. xx")
    ap.add_argument("fixtures", nargs="+", help="Fixture paths, or ID=path")
    ap.add_argument("--out", default=None, help="Output dir (default /tmp/{code}-sandbox)")
    args = ap.parse_args()

    out = Path(args.out or f"/tmp/{args.code}-sandbox")
    out.mkdir(parents=True, exist_ok=True)

    metadata_parser = get_metadata_parser(args.code)
    text_parser = get_text_parser(args.code)

    for arg in args.fixtures:
        norm_id, path = split_arg(arg)
        data = read_fixture(path)
        metadata = metadata_parser.parse(data, norm_id)
        blocks = text_parser.parse_text(data)
        markdown = render_norm_at_date(
            metadata, blocks, metadata.publication_date, include_all=True
        )
        (out / f"{norm_id}.md").write_text(markdown)
        print(f"{norm_id}: {len(markdown)} chars, {len(blocks)} blocks -> {out / norm_id}.md")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
