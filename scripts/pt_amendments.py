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
from pathlib import Path

sys.path.insert(0, "src")

from legalize.config import load_config  # noqa: E402
from legalize.fetcher.pt.client import published_date_of, unpack  # noqa: E402
from legalize.fetcher.pt.identifier import build_identifier  # noqa: E402

_RDFA = re.compile(r'about="([^"]*)"\s+property="eli:(amended_by|amends)"\s+resource="([^"]*)"')
_ELI_PATH = re.compile(r"/eli/([^/]+)/([^/]+)/(\d{4})")
# The href as DRE writes it in the act's own HTML. Read from raw/ and never from a
# rendered file: the index must be a pure function of the cache, or it silently
# degrades to the RDFa alone whenever it runs before the reparse — which is when it
# runs, because the reparse consumes it. That mistake cost 19,254 laws.
# DRE quotes this attribute with single quotes, and the neighbouring ones with
# double. Accept either — matching only one silently finds nothing.
_HREF = re.compile(r"""href=["']/dr/detalhe/([^/"']+)/([^"'?#]+)["']""")
_AMENDING = re.compile(
    r"^\s*(altera|revoga|adita|republica|retifica|rectifica|derroga|prorroga|suspende)",
    re.I,
)
_UNSAFE = re.compile(r"[^A-Z0-9]+")


def _safe(norm_id: str) -> str:
    """The cache filename pt_relations.py writes. Must stay identical to it."""
    return norm_id.replace(":", "-").replace("/", "-")


def _eli_key(uri: str) -> str | None:
    """``…/eli/dec-lei/16/1994/…`` -> ``DEC-LEI/16/1994``, a join key.

    Not an identifier. An ELI names a diploma by type, number and year, and the
    identifier is DRE's own name for the *document*, which carries a document id
    an ELI does not have. This used to return something identifier-shaped, and
    the shape was the bug: it looked like a name, so it was published as one.
    Every reference the index carried was in a scheme the corpus had left —
    150,102 of them, and nothing said so.

    So it stays a key, and a key is only ever looked up in ``ident_by_eli``,
    built from the ELI of each diploma the cache holds.
    """
    match = _ELI_PATH.search(uri or "")
    if not match:
        return None
    kind, number, year = match.groups()
    kind = _UNSAFE.sub("-", kind.upper()).strip("-")
    number = _UNSAFE.sub("-", number.upper()).strip("-")
    return f"{kind}/{number}/{year}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    config = load_config(os.environ.get("CONFIG", "config.yaml"))
    data_dir = Path(config.get_country("pt").data_dir)
    raw_dir = data_dir / "raw"

    # -- pass 1: identity, date and summary of every cached diploma ------------
    ident_of: dict[str, str] = {}  # "tipo/key" as DRE links it -> identifier
    ident_of_norm: dict[str, str] = {}  # "surface:tipo:key" -> identifier
    published_on: dict[str, str] = {}
    summary_of: dict[str, str] = {}
    amended: dict[str, set[str]] = defaultdict(set)

    # DRE's relation triples, held as ELI keys until every diploma's identity is
    # known. They name diplomas by ELI, and an ELI cannot be turned into an
    # identifier on its own — it has to be looked up in the cache.
    ident_by_eli: dict[str, str] = {}
    rdfa: list[tuple[str, str, str]] = []

    for path in raw_dir.glob("*.meta.json.gz"):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                bundle = json.load(handle)
        except Exception:
            continue
        published = bundle.get("published") or {}
        # Through published_date_of, not off DataPublicacao: DRE writes its
        # 1900-01-01 sentinel there and keeps the real day in DataDistribuicao.
        when = published_date_of(published)[:10]
        link = (published.get("LinkSitemap") or "").strip()
        try:
            ident = build_identifier(link, str(published.get("Id") or ""), when[:4])
        except ValueError:
            # No page URL and no usable id: the diploma has no name, so it can
            # neither be indexed nor referred to.
            continue
        if link:
            ident_of[
                link.rstrip("/").rsplit("/", 2)[-2] + "/" + link.rstrip("/").rsplit("/", 1)[-1]
            ] = ident
        eli_key = _eli_key(published.get("ELI") or "")
        if eli_key:
            ident_by_eli[eli_key] = ident
        surface = "cons" if path.name.startswith("cons-") else "pub"
        ident_of_norm[f"{surface}:{bundle.get('tipo', '')}:{bundle.get('key', '')}"] = ident
        published_on[ident] = when
        summary_of[ident] = (published.get("Sumario") or published.get("Resumo") or "").replace(
            "\x00", ""
        )
        rdfa.extend(_RDFA.findall(published.get("ELIMetadataHTML") or ""))

    # -- pass 1a: resolve the relation triples now that every ELI is known -----
    outside = 0
    for about, prop, resource in rdfa:
        source = ident_by_eli.get(_eli_key(about) or "")
        target = ident_by_eli.get(_eli_key(resource) or "")
        if not source or not target:
            outside += 1
            continue
        if prop == "amended_by":
            amended[source].add(target)
        else:
            amended[target].add(source)
    print(
        f"DRE RDFa: {len(rdfa)} relations, {outside} naming a diploma outside the cache",
        flush=True,
    )

    dre_only = {k: set(v) for k, v in amended.items()}
    print(f"{len(published_on)} diplomas cached · DRE names an amender for {len(amended)}")

    # -- pass 1b: DRE's own relation table, harvested by pt_relations.py ---------
    # The authoritative source, and the only one carrying the articles and the
    # repeals. Only InversasList is read: DiretasList describes the same relations
    # from the acting side with no resolvable target at all — HasLink false and
    # DiplomaLinkId "0" on every row — while 93.9 % of them have a counterpart
    # inversa. The graph is complete from the amended law's side and unobtainable
    # from the act's, which is why this has to be harvested per law.
    from_dre: dict[str, dict[str, tuple[str, str]]] = {}
    safe_to_norm = {_safe(n): n for n in ident_of_norm}
    rel_rows = rel_outside = 0
    for type_dir in sorted((data_dir / "relations").glob("*")):
        if not type_dir.is_dir():
            continue
        for path in type_dir.glob("*.json.gz"):
            law = safe_to_norm.get(path.name[: -len(".json.gz")])
            if not law:
                continue
            try:
                with gzip.open(path, "rt", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except Exception:
                continue
            for row in (payload.get("InversasList") or {}).get("List") or []:
                rel_rows += 1
                parts = (row.get("LinkSitemapAnaliseJuridica") or "").strip("/").split("/")
                act = ident_of.get(f"{parts[-2]}/{parts[-1]}") if len(parts) >= 2 else None
                when = (row.get("Data") or "")[:10]
                if not act or not when:
                    rel_outside += 1
                    continue
                # Verbatim, as DRE wrote it: "Alterados os arts. 5º, 9º, 14º…".
                # Not parsed into article numbers: the drafting is a convention of
                # one legislature, not a property of law, and a taxonomy invented
                # here is one to redo in 34 countries.
                note = " ".join((row.get("Texto") or "").replace("\x00", "").split())
                from_dre.setdefault(law, {})[act] = (when, note)
    print(
        f"DRE relation table: {rel_rows} rows over {len(from_dre)} laws "
        f"({rel_outside} pointed outside the corpus)",
        flush=True,
    )

    # -- pass 2: what each amending act says it amends -------------------------
    # The body links its target ("[Decreto-Lei n.º 16/94](https://…/16-1994-512030)"),
    # which is exact; the summary is the fallback and only names it in prose.
    linked = 0
    for path in raw_dir.glob("*.versions.json.gz"):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                blob = json.load(handle)
        except Exception:
            continue
        ident = ident_of_norm.get(blob.get("norm_id", ""))
        if not ident or not _AMENDING.match(summary_of.get(ident, "")):
            continue
        for entry in blob.get("versions") or []:
            if not entry.get("html_b64"):
                continue
            html = unpack(entry["html_b64"])
            if not isinstance(html, str):
                continue
            for tipo, key in set(_HREF.findall(html)):
                target = ident_of.get(f"{tipo}/{key}")
                if target and target != ident:
                    amended[target].add(ident)
                    linked += 1

    print(f"{linked} target links read off the acts' own HTML")
    inferred_only = len(set(amended) - set(dre_only))
    print(
        f"laws with a known amender: {len(amended)} "
        f"(DRE {len(dre_only)}, only from the acts {inferred_only})"
    )
    if args.report:
        return 0

    # -- write ------------------------------------------------------------------
    # Keyed by the amended law's *norm id*, because the text parser is what consumes
    # this and a norm id is all it has. Values carry the date so each amendment can
    # become a Reform, and the official identifier of the act, which is what
    # last_amendment is documented to hold.
    #
    # Only the as-published side is emitted. A consolidated diploma already carries
    # its amendments as Versions, and the reparse writes it after its as-published
    # twin, so anything emitted for the twin is overwritten anyway.
    norm_id_of = {
        ident: norm_id for norm_id, ident in ident_of_norm.items() if norm_id.startswith("pub:")
    }
    out: dict[str, list[list[str]]] = {}
    only_prose = 0
    for law, acts in amended.items():
        norm_id = norm_id_of.get(law)
        if not norm_id:
            continue
        rows: dict[str, tuple[str, str]] = dict(from_dre.get(norm_id) or {})
        for act in acts:
            # Prose only fills what DRE never recorded, and brings no wording.
            if act not in rows and published_on.get(act):
                rows[act] = (published_on[act], "")
                only_prose += 1
        if rows:
            out[norm_id] = [
                [w, a, n] for a, (w, n) in sorted(rows.items(), key=lambda kv: kv[1][0])
            ]
    for norm_id, official in from_dre.items():
        # Laws DRE records an amender for that no act named in prose.
        if norm_id in out or not norm_id.startswith("pub:"):
            continue
        out[norm_id] = [
            [w, a, n] for a, (w, n) in sorted(official.items(), key=lambda kv: kv[1][0])
        ]
    with_wording = sum(1 for rows in out.values() for row in rows if row[2])
    print(
        f"merged: {len(out)} as-published laws · {sum(len(v) for v in out.values())} amendments "
        f"· {with_wording} carry DRE's wording · {only_prose} known only from prose",
        flush=True,
    )
    target = data_dir / "amendments.json"
    target.write_text(json.dumps(out, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(
        f"wrote {target} — {len(out)} as-published laws, "
        f"{sum(len(v) for v in out.values())} amendments"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
