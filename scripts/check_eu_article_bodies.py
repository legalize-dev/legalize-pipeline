#!/usr/bin/env python3
"""Report EU article bodies without changing the corpus.

    python scripts/check_eu_article_bodies.py /path/to/legalize-eu/eu

Empty articles are candidates for source review, not automatic parser failures:
consolidations can legitimately leave deleted provisions as empty headings.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def article_bodies(markdown: str) -> list[tuple[str, str]]:
    """Split articles at the next heading of equal or higher level.

    Ignore subtitle headings as body text; include the final article at EOF.
    EUR-Lex uses both ordinary and non-breaking spaces in article headings.
    """
    articles: list[tuple[str, str]] = []
    heading = ""
    level = 4
    body: list[str] = []
    for line in markdown.splitlines():
        article = re.match(r"^(#{4,6})\s+Article\s+\d+\w*\s*$", line)
        boundary = re.match(r"^(#{1,6})\s", line)
        if article or (boundary and len(boundary.group(1)) <= level):
            if heading:
                articles.append((heading, "\n".join(body)))
            heading = line.strip() if article else ""
            level = len(article.group(1)) if article else 4
            body = []
        elif heading and line.strip() and not re.match(r"^#{1,6}\s", line):
            # H6 cannot nest another Markdown heading; EU emits its subtitle
            # in bold. This is still a structural candidate, needing source review.
            if level == 6 and not body and re.fullmatch(r"\*\*[^*]+\*\*", line.strip()):
                continue
            body.append(line.strip())
    if heading:
        articles.append((heading, "\n".join(body)))
    return articles


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    files = sorted(args.directory.rglob("*.md"))
    count = 0
    empty = {}
    placeholders = {}
    for path in files:
        articles = article_bodies(path.read_text(encoding="utf-8"))
        count += len(articles)
        candidates = [heading for heading, body in articles if not body]
        if candidates:
            empty[str(path.relative_to(args.directory))] = candidates
        explicit = [
            heading
            for heading, body in articles
            if body
            and re.fullmatch(r"(?:deleted|repealed|reserved|omitted)[.!]?", body.strip("* _"), re.I)
        ]
        if explicit:
            placeholders[str(path.relative_to(args.directory))] = explicit
    print(
        json.dumps(
            {
                "files": len(files),
                "articles": count,
                "empty_candidates": sum(map(len, empty.values())),
                "affected_files": len(empty),
                "candidates": empty,
                "explicit_placeholders": sum(map(len, placeholders.values())),
                "placeholder_articles": placeholders,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
