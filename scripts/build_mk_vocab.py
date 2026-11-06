"""Build the two word lists the Macedonian OCR cleanup reads.

Usage:
    python scripts/build_mk_vocab.py mkwiki-20261001-pages-articles.xml.bz2 <laws dir>

The dump is https://dumps.wikimedia.org/mkwiki/20261001/mkwiki-20261001-pages-articles.xml.bz2
(MD5 94f0439df898709b92f5bb848372aebf), Macedonian Wikipedia under CC BY-SA 4.0. The laws
directory holds rendered LDBIS laws; only those whose PDF has a real text layer (no
``text_source`` key) are counted, never OCR output, which would teach the corrector its own
mistakes. The lists hold words and counts only, no running text.

``mk_words.tsv.gz`` is every lower-case Cyrillic word with its count, most frequent first, for
the spelling corrector. ``mk_capitals.tsv.gz`` gives, per word, how often Wikipedia writes it in
the middle of a sentence in lower case and how often with a capital: OCR reads a small letter as
its capital when the two differ only in size ("Јавен" for "јавен"), and only these counts tell
such a word from a name, which keeps its capital.
"""

from __future__ import annotations

import bz2
import gzip
import re
import sys
from collections import Counter
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "src" / "legalize" / "fetcher" / "mk" / "assets"
LOWER = "а-шѓќѕљњџјѐѝ"
UPPER = "А-ШЃЌЅЉЊЏЈЀЍ"
WORD = re.compile(rf"[{LOWER}]+")
# A word after a small letter or a comma and one space stands in the middle of a sentence.
MID = re.compile(rf"(?<=[{LOWER},] )([{UPPER}{LOWER}][{LOWER}]+)\b")


def write(name: str, lines) -> None:
    with gzip.GzipFile(ASSETS / name, "wb", mtime=0) as raw:
        raw.write("".join(lines).encode("utf-8"))


def main(dump: Path, laws: Path) -> None:
    counts, low, cap = Counter(), Counter(), Counter()
    with bz2.open(dump, "rt", encoding="utf-8") as f:
        for line in f:
            counts.update(WORD.findall(line.casefold()))
            for word in MID.findall(line):
                (low if word[0].islower() else cap)[word.lower()] += 1
    for path in sorted(laws.glob("**/*.md")):
        text = path.read_text(encoding="utf-8")
        if "text_source" not in text.split("---")[1]:
            counts.update(WORD.findall(text.casefold()))
    write("mk_words.tsv.gz", (f"{w}\t{c}\n" for w, c in counts.most_common()))
    write("mk_capitals.tsv.gz", (f"{w}\t{low[w]}\t{cap[w]}\n" for w in sorted(low | cap)))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
