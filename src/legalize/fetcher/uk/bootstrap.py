"""UK bulk bootstrap from local CLML XML.

Replaces the API-driven generic_bootstrap with a local-disk read of the
Legislation Research bulk dump (Legislative Texts Data + Statute Book
Metadata). Used for the one-time SI bootstrap (~150K commits across
uksi/ssi/wsi/nisr/nisro). Daily updates continue to use the API.

Detected automatically by ``pipeline.generic_bootstrap`` via the optional
``fetcher/{country}/bootstrap.py`` hook.

Bulk dir layout (defaults to ``~/Documents/legalize-bulk``; override with
``LEGALIZE_UK_BULK_DIR``)::

    enacted/{year}/{type}-{year}-{number}-enacted-data.xml
    revised/{type}/{year}/{type}-{year}-{number}-historical-{YYYY-MM-DD}.xml
    amendments/{type}-{year}-effects.xml

Output: a JSON blob whose shape matches ``LegislationGovUkClient.get_suvestine``
exactly, so ``UKTextParser.parse_suvestine`` consumes it without modification.

Additive on top of the existing primary-legislation history: SI norm_ids
(uksi-/ssi-/wsi-/nisr-/nisro-) never collide with primary norm_ids
(ukpga-/asp-/asc-/anaw-/mwa-/nia-), so fast-import takes the existing
``refs/heads/main`` tip as the parent of the first SI commit.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date as date_type
from pathlib import Path

from lxml import etree
from rich.console import Console

from legalize.committer.git_ops import FastImportDied, FastImporter
from legalize.committer.message import build_commit_info
from legalize.config import Config, CountryConfig
from legalize.fetcher.uk.client import NS, _extract_enacted_date, split_norm_id
from legalize.fetcher.uk.parser import UKMetadataParser, UKTextParser
from legalize.models import CommitType, ParsedNorm, Reform
from legalize.storage import load_norma_from_json, save_structured_json
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath

console = Console()
logger = logging.getLogger(__name__)


SI_TYPES: tuple[str, ...] = ("uksi", "ssi", "wsi", "nisr", "nisro")

DEFAULT_BULK_DIR = "~/Documents/legalize-bulk"

_ENACTED_RE = re.compile(r"^([a-z]+)-(\d+)-(\d+)-enacted-data\.xml$")
_PERMALINK_RE = re.compile(r"^https?://www\.legislation\.gov\.uk/id/([a-z]+)/(\d+)/(\d+)/?$")


def bootstrap(
    config: Config,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    workers: int | None = None,
) -> int:
    """Run the UK SI bulk bootstrap (additive on top of primary legislation).

    Three phases:

      1. **Discover** SI norm_ids by walking ``enacted/``.
      2. **Parse + persist**: for each norm, build a suvestine JSON blob
         from local files, run it through ``UKTextParser.parse_suvestine``,
         derive metadata via ``UKMetadataParser.parse``, save the
         structured ``ParsedNorm`` JSON. Parallel; resumable (existing
         JSONs are skipped).
      3. **Commit**: stream the SI norms through ``FastImporter`` in
         chronological reform order. Existing primary-legislation commits
         in the target repo are preserved.
    """
    bulk_dir = Path(os.environ.get("LEGALIZE_UK_BULK_DIR", DEFAULT_BULK_DIR)).expanduser().resolve()
    cc = config.get_country("uk")
    workers = workers or (getattr(cc, "max_workers", 4) or 4)

    console.print("[bold]Bootstrap UK — bulk SI ingest[/bold]")
    console.print(f"  Bulk dir:  {bulk_dir}")
    console.print(f"  Data dir:  {cc.data_dir}")
    console.print(f"  Repo:      {cc.repo_path}")
    console.print(f"  Workers:   {workers}")
    console.print(f"  SI types:  {', '.join(SI_TYPES)}\n")

    if not bulk_dir.is_dir():
        console.print(f"[red]Bulk dir not found: {bulk_dir}[/red]")
        console.print("[red]Set LEGALIZE_UK_BULK_DIR to the bulk dump root.[/red]")
        return 0

    # ─── Phase 1: discovery ───
    si_norm_ids = sorted(_discover_si_norm_ids(bulk_dir))
    console.print(f"  Discovered {len(si_norm_ids)} SI enacted files")
    if limit:
        si_norm_ids = si_norm_ids[:limit]
        console.print(f"  --limit applied: {len(si_norm_ids)} norms\n")
    else:
        console.print()

    if not si_norm_ids:
        return 0

    # ─── Phase 2: parse + save JSON ───
    json_dir = Path(cc.data_dir) / "json"
    json_dir.mkdir(parents=True, exist_ok=True)

    effects = _EffectsIndex(bulk_dir / "amendments")
    text_parser = UKTextParser()
    meta_parser = UKMetadataParser()

    fetched: list[str] = []
    skipped = 0
    errors: list[str] = []
    t0 = time.monotonic()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _process_one,
                nid,
                bulk_dir,
                effects,
                text_parser,
                meta_parser,
                Path(cc.data_dir),
            ): nid
            for nid in si_norm_ids
        }
        for i, future in enumerate(as_completed(futures), 1):
            nid = futures[future]
            try:
                outcome = future.result()
            except Exception as e:
                errors.append(f"{nid}: {type(e).__name__}: {e}")
                logger.error("Parse error on %s", nid, exc_info=True)
            else:
                if outcome == "skipped":
                    skipped += 1
                else:
                    fetched.append(nid)

            if i % 500 == 0:
                elapsed = time.monotonic() - t0
                rate = i / elapsed if elapsed > 0 else 0
                eta = (len(si_norm_ids) - i) / rate if rate > 0 else 0
                console.print(
                    f"  [dim][{i}/{len(si_norm_ids)}] "
                    f"{len(fetched)} parsed, {skipped} skipped, "
                    f"{len(errors)} errors, {rate:.1f}/s, "
                    f"ETA {eta / 60:.0f} min[/dim]"
                )

    elapsed = time.monotonic() - t0
    console.print(
        f"\n  [bold]Phase 2:[/bold] {len(fetched)} parsed, "
        f"{skipped} skipped, {len(errors)} errors in {elapsed / 60:.1f} min\n"
    )
    for msg in errors[:10]:
        console.print(f"    [red]✗ {msg}[/red]")
    if len(errors) > 10:
        console.print(f"    [red]... and {len(errors) - 10} more[/red]\n")

    if dry_run:
        console.print("[yellow]dry-run: skipping commit phase[/yellow]")
        return len(fetched)

    # ─── Phase 3: commit only the SI norms ───
    return _commit_si_norms(config, cc, si_norm_ids)


# ─── Discovery ─────────────────────────────────────────────────────


def _discover_si_norm_ids(bulk_dir: Path) -> set[str]:
    """Walk ``enacted/`` and return the set of SI norm_ids."""
    enacted_dir = bulk_dir / "enacted"
    out: set[str] = set()
    for year_dir in enacted_dir.iterdir():
        if not year_dir.is_dir():
            continue
        for f in year_dir.iterdir():
            m = _ENACTED_RE.match(f.name)
            if m and m.group(1) in SI_TYPES:
                out.add(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
    return out


# ─── Per-norm processing ───────────────────────────────────────────


def _process_one(
    norm_id: str,
    bulk_dir: Path,
    effects: _EffectsIndex,
    text_parser: UKTextParser,
    meta_parser: UKMetadataParser,
    data_dir: Path,
) -> str:
    """Build blob, parse, save JSON. Returns 'fetched' or 'skipped'."""
    safe_id = norm_id.replace(":", "-").replace("/", "-").replace(" ", "")
    json_path = data_dir / "json" / f"{safe_id}.json"
    if json_path.exists():
        return "skipped"

    type_code, year, number = split_norm_id(norm_id)

    enacted_path = (
        bulk_dir / "enacted" / str(year) / f"{type_code}-{year}-{number}-enacted-data.xml"
    )
    enacted_xml = enacted_path.read_bytes()

    blob = _build_suvestine_blob(norm_id, enacted_xml, bulk_dir, effects)
    blocks, reforms = text_parser.parse_suvestine(blob, norm_id)
    if not blocks:
        raise ValueError(f"{norm_id}: parse_suvestine returned 0 blocks")

    metadata = meta_parser.parse(enacted_xml, norm_id)
    norm = ParsedNorm(
        metadata=metadata,
        blocks=tuple(blocks),
        reforms=tuple(reforms),
    )
    save_structured_json(data_dir, norm)
    return "fetched"


def _build_suvestine_blob(
    norm_id: str,
    enacted_xml: bytes,
    bulk_dir: Path,
    effects: _EffectsIndex,
) -> bytes:
    """Assemble a get_suvestine-shaped JSON blob from local files."""
    type_code, year, number = split_norm_id(norm_id)
    versions: list[dict] = [
        {
            "effective_date": _extract_enacted_date(enacted_xml),
            "affecting_uri": None,
            "xml_b64": base64.b64encode(enacted_xml).decode("ascii"),
        }
    ]

    revised_dir = bulk_dir / "revised" / type_code / str(year)
    if revised_dir.is_dir():
        prefix = f"{type_code}-{year}-{number}-historical-"
        snapshots: list[tuple[str, Path]] = []
        for f in revised_dir.iterdir():
            if f.name.startswith(prefix) and f.name.endswith(".xml"):
                d = f.name[len(prefix) : -len(".xml")]
                snapshots.append((d, f))
        snapshots.sort(key=lambda x: x[0])

        date_to_uri = effects.lookup(norm_id)
        last_b64 = versions[0]["xml_b64"]

        for snap_date, snap_path in snapshots:
            xml_bytes = snap_path.read_bytes()
            new_b64 = base64.b64encode(xml_bytes).decode("ascii")
            if new_b64 == last_b64:
                continue
            versions.append(
                {
                    "effective_date": snap_date,
                    "affecting_uri": date_to_uri.get(snap_date),
                    "xml_b64": new_b64,
                }
            )
            last_b64 = new_b64

    return json.dumps({"norm_id": norm_id, "versions": versions}).encode("utf-8")


# ─── Effects index ─────────────────────────────────────────────────


class _EffectsIndex:
    """Lazy-loaded year-grouped amendment effects lookup.

    The bulk amendment dataset stores effects in
    ``amendments/{type}-{year}-effects.xml`` files, where ``year`` is the
    year of the *affected* SI. Files reach 50+ MB for busy years, so we
    iterparse with element-clear to keep memory bounded.

    ``lookup(norm_id)`` returns ``{effective_date: affecting_uri}`` for
    the requested SI. The returned mapping pairs each PIT snapshot date
    with the URI of the amending instrument (or first amending one if
    multiple effects share a date — same heuristic as the API path).
    """

    _UKM_EFFECTS = "{http://www.legislation.gov.uk/namespaces/metadata}Effects"

    def __init__(self, amendments_dir: Path) -> None:
        self._dir = amendments_dir
        self._cache: dict[tuple[str, int], dict[str, dict[str, str]]] = {}

    def lookup(self, norm_id: str) -> dict[str, str]:
        type_code, year, _ = split_norm_id(norm_id)
        key = (type_code, year)
        cached = self._cache.get(key)
        if cached is None:
            cached = self._load(type_code, year)
            self._cache[key] = cached
        return cached.get(norm_id, {})

    def _load(self, type_code: str, year: int) -> dict[str, dict[str, str]]:
        path = self._dir / f"{type_code}-{year}-effects.xml"
        if not path.exists():
            return {}

        out: dict[str, dict[str, str]] = {}
        for _, elem in etree.iterparse(str(path), events=("end",), tag=self._UKM_EFFECTS):
            permalink = elem.get("Id", "")
            m = _PERMALINK_RE.match(permalink)
            if m is None:
                _drop(elem)
                continue
            target_norm = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

            for effect in elem.findall("ukm:Effect", NS):
                affecting_uri = effect.get("AffectingURI")
                if not affecting_uri:
                    continue
                for inforce in effect.findall("ukm:InForceDates/ukm:InForce", NS):
                    if inforce.get("Applied") != "true":
                        continue
                    eff_date = inforce.get("Date") or ""
                    if not eff_date:
                        continue
                    out.setdefault(target_norm, {}).setdefault(eff_date, affecting_uri)

            _drop(elem)
        return out


def _drop(elem) -> None:
    """Free a finished iterparse element and its preceding siblings."""
    elem.clear()
    parent = elem.getparent()
    if parent is not None:
        while parent[0] is not elem and parent[0] is not None:
            del parent[0]


# ─── Commit phase ──────────────────────────────────────────────────


def _commit_si_norms(
    config: Config,
    cc: CountryConfig,
    si_norm_ids: list[str],
) -> int:
    """Fast-import only the SI norms in chronological reform order.

    Mirrors ``pipeline.commit_all_fast`` but iterates a fixed list of
    norm_ids (so primary legislation JSONs in ``data_dir/json/`` are
    untouched). Existing commits on ``refs/heads/main`` survive: the
    first commit emitted by ``FastImporter`` has no explicit ``from``,
    which makes git fast-import use the current branch tip as parent.
    """
    json_dir = Path(cc.data_dir) / "json"

    all_reforms: list[tuple[date_type, str, int, Path]] = []
    missing = 0
    for nid in si_norm_ids:
        json_file = json_dir / f"{nid}.json"
        if not json_file.exists():
            missing += 1
            continue
        try:
            norm = load_norma_from_json(json_file)
        except (OSError, ValueError):
            logger.error("Failed to load %s", json_file, exc_info=True)
            continue

        reforms = norm.reforms
        if not reforms and norm.blocks:
            reforms = (
                Reform(
                    date=norm.metadata.publication_date,
                    norm_id=norm.metadata.identifier,
                    affected_blocks=(),
                ),
            )
        for i, reform in enumerate(reforms):
            all_reforms.append((reform.date, json_file.stem, i, json_file))

    if missing:
        console.print(f"  [yellow]{missing} norms had no JSON (parse failures)[/yellow]")

    all_reforms.sort(key=lambda x: x[0])
    console.print(
        f"  [bold]Phase 3:[/bold] {len(all_reforms)} commits to fast-import "
        f"(spanning {len(si_norm_ids) - missing} SIs)\n"
    )

    norm_cache: dict[str, tuple[ParsedNorm, tuple[Reform, ...]]] = {}
    errors = 0

    with FastImporter(
        cc.repo_path,
        config.git.committer_name,
        config.git.committer_email,
    ) as fi:
        for idx, (_d, norm_id, reform_idx, json_file) in enumerate(all_reforms):
            try:
                cached = norm_cache.get(norm_id)
                if cached is None:
                    loaded = load_norma_from_json(json_file)
                    rs = loaded.reforms
                    if not rs and loaded.blocks:
                        rs = (
                            Reform(
                                date=loaded.metadata.publication_date,
                                norm_id=loaded.metadata.identifier,
                                affected_blocks=(),
                            ),
                        )
                    norm_cache[norm_id] = (loaded, rs)
                    cached = norm_cache[norm_id]

                norm, reforms_cached = cached
                reform = reforms_cached[reform_idx]
                is_first = reform_idx == 0
                commit_type = CommitType.BOOTSTRAP if is_first else CommitType.REFORM
                markdown = render_norm_at_date(
                    norm.metadata, norm.blocks, reform.date, include_all=is_first
                )
                file_path = norm_to_filepath(norm.metadata)
                info = build_commit_info(
                    commit_type, norm.metadata, reform, norm.blocks, file_path, markdown
                )
                fi.commit(file_path, markdown, info)
            except FastImportDied:
                raise
            except Exception:
                errors += 1
                logger.error("Commit error on %s reform %d", norm_id, reform_idx, exc_info=True)

            if (idx + 1) % 5000 == 0:
                console.print(
                    f"  [dim][{idx + 1}/{len(all_reforms)}] queued, {errors} errors[/dim]"
                )

            remaining = sum(1 for _, nid, _, _ in all_reforms[idx + 1 :] if nid == norm_id)
            if remaining == 0:
                norm_cache.pop(norm_id, None)

    console.print(f"\n[bold green]✓ {fi.commit_count} commits created (fast-import)[/bold green]")
    if errors:
        console.print(f"[yellow]⚠ {errors} commit errors[/yellow]")
    return fi.commit_count
