#!/usr/bin/env python3
"""Build the map of which diploma amends which, for last_amendment (spec v0.3).

Portugal needs this because DRE only consolidates 5,561 diplomas. For the other
159,000 the repository ships the act as enacted, and the only honest way to say
"this 1994 text is not the current law" is to name the act that changed it.

Two sources, and neither is enough alone:

* **DRE's own ``eli:amended_by`` / ``eli:amends``.** Authoritative, and 99 % of what
  it carries is Declarações de Retificação — which are amendments: a rectification
  changes the official text with legal effect. It reaches 3,470 laws.
* **The amending acts themselves.** "Altera o Decreto-Lei n.º 16/94" names its
  target in the summary, and 73.7 % of them also link it from the body. Reaches
  6,848 laws, mostly the substantive amendments DRE never marked up.

The overlap is 713, so the union — 9,605 laws — is nearly three times either one.

    python3 scripts/pt_amendments.py            # build it
    python3 scripts/pt_amendments.py --report   # coverage only
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, "src")

from legalize.config import load_config  # noqa: E402
from legalize.fetcher.pt.identifier import build_identifier  # noqa: E402

_RDFA = re.compile(r'about="([^"]*)"\s+property="eli:(amended_by|amends)"\s+resource="([^"]*)"')
_ELI_PATH = re.compile(r"/eli/([^/]+)/([^/]+)/(\d{4})")
_LINK = re.compile(r"\]\(https://diariodarepublica\.pt/dr/detalhe/([^/]+)/([^)]+)\)")
_AMENDING = re.compile(
    r"^\s*(altera|revoga|adita|republica|retifica|rectifica|derroga|prorroga|suspende)",
    re.I,
)
_UNSAFE = re.compile(r"[^A-Z0-9]+")


def _from_eli(uri: str) -> str | None:
    """``…/eli/dec-lei/16/1994/…`` -> ``DRE-DEC-LEI-16-1994``."""
    match = _ELI_PATH.search(uri or "")
    if not match:
        return None
    kind, number, year = match.groups()
    kind = _UNSAFE.sub("-", kind.upper()).strip("-")
    number = _UNSAFE.sub("-", number.upper()).strip("-")
    return f"DRE-{kind}-{number}-{year}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    config = load_config(os.environ.get("CONFIG", "config.yaml"))
    data_dir = Path(config.get_country("pt").data_dir)
    raw_dir, json_dir = data_dir / "raw", data_dir / "json"

    # -- pass 1: identity, date and summary of every cached diploma ------------
    ident_of: dict[str, str] = {}  # dre detail key -> identifier
    published_on: dict[str, str] = {}
    summary_of: dict[str, str] = {}
    amended: dict[str, set[str]] = defaultdict(set)

    for path in raw_dir.glob("*.meta.json.gz"):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                bundle = json.load(handle)
        except Exception:
            continue
        published = bundle.get("published") or {}
        when = (published.get("DataPublicacao") or "")[:10]
        try:
            year = date.fromisoformat(when).year
        except ValueError:
            year = 1900
        ident = build_identifier(
            (published.get("ELI") or "").strip(),
            (published.get("Numero") or "").strip(),
            bundle.get("tipo", ""),
            year,
            (published.get("TipoDiplomaAcronimo") or "").strip(),
            str(published.get("Id") or ""),
        )
        link = (published.get("LinkSitemap") or "").strip()
        if link:
            ident_of[
                link.rstrip("/").rsplit("/", 2)[-2] + "/" + link.rstrip("/").rsplit("/", 1)[-1]
            ] = ident
        published_on[ident] = when
        summary_of[ident] = (published.get("Sumario") or published.get("Resumo") or "").replace(
            "\x00", ""
        )
        # DRE's own relations, both directions
        for about, prop, resource in _RDFA.findall(published.get("ELIMetadataHTML") or ""):
            source, target = _from_eli(about), _from_eli(resource)
            if not source or not target:
                continue
            if prop == "amended_by":
                amended[source].add(target)
            else:
                amended[target].add(source)

    dre_only = {k: set(v) for k, v in amended.items()}
    print(f"{len(published_on)} diplomas cached · DRE names an amender for {len(amended)}")

    # -- pass 2: what each amending act says it amends -------------------------
    # The body links its target ("[Decreto-Lei n.º 16/94](https://…/16-1994-512030)"),
    # which is exact; the summary is the fallback and only names it in prose.
    linked = 0
    for path in json_dir.glob("*.json"):
        ident = path.stem
        if not _AMENDING.match(summary_of.get(ident, "")):
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for tipo, key in set(_LINK.findall(body)):
            target = ident_of.get(f"{tipo}/{key}")
            if target and target != ident:
                amended[target].add(ident)
                linked += 1

    print(f"{linked} target links read off amending-act bodies")
    inferred_only = len(set(amended) - set(dre_only))
    print(
        f"laws with a known amender: {len(amended)} "
        f"(DRE {len(dre_only)}, only from the acts {inferred_only})"
    )
    if args.report:
        return 0

    # -- write: newest amending act last, so the parser can take [-1] ----------
    out: dict[str, list[str]] = {}
    for law, acts in amended.items():
        out[law] = [a for _, a in sorted((published_on.get(a, ""), a) for a in acts)]
    target = data_dir / "amendments.json"
    target.write_text(json.dumps(out, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(f"wrote {target} — {len(out)} laws, {sum(len(v) for v in out.values())} relations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
