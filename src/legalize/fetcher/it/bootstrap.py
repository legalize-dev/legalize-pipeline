"""Custom bootstrap for Italy — downloads multivigente collection ZIPs.

Italy's data source (Normattiva) provides pre-built collection ZIPs that
include all historical versions of each act. This is far more efficient
than per-act API version-walking (which hits WAF rate limits).

Strategy:
1. Download multivigente ZIPs for each collection (one request per collection)
2. Extract all HTML versions from each ZIP
3. Convert to pipeline JSON with Reform objects (one per version date)
4. For act types not covered by collections (Legge, D.Lgs., Decreto),
   fall back to per-act API version-walking

Called automatically by ``generic_bootstrap()`` when it detects
``fetcher/it/bootstrap.py`` exists.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import zipfile
from datetime import date
from pathlib import Path

import requests

from legalize.config import Config
from legalize.fetcher.it.client import TIPO_TO_CODE
from legalize.models import ParsedNorm, Reform
from legalize.pipeline import (
    commit_all_fast,
    console,
    save_structured_json,
    write_country_meta,
)

logger = logging.getLogger(__name__)

# Collections available for bulk download with multivigente format.
# Each entry: (collection_name, expected_act_count_approx)
BULK_COLLECTIONS = [
    "Leggi costituzionali",
    "DPCM",
    "DPR",
    "DL e leggi di conversione",
    "DL decaduti",
    "DL proroghe",
    "Leggi contenenti deleghe",
    "Leggi di delegazione europea",
    "Leggi di ratifica",
    "Leggi finanziarie e di bilancio",
    "Testi Unici",
    "Regolamenti governativi",
    "Regolamenti ministeriali",
    "Regolamenti di delegificazione",
    "Regi decreti legislativi",
    "Decreti legislativi luogotenenziali",
    "Codici",
    "Atti di recepimento direttive UE",
    "Atti di attuazione Regolamenti UE",
]

API_BASE = "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1/api/v1"

FNAME_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})_([A-Z0-9]+)_(ORIGINALE|VIGENZA)"
    r"(?:_(\d{4}-\d{2}-\d{2}))?_V(\d+)\.html"
)


def bootstrap(
    config: Config,
    dry_run: bool = False,
    limit: int | None = None,
) -> int:
    """Full bootstrap for Italy: bulk download + version-walk + commit."""
    cc = config.get_country("it")
    data_dir = Path(cc.data_dir)
    json_dir = data_dir / "json"
    json_dir.mkdir(parents=True, exist_ok=True)

    console.print("[bold]Bootstrap IT (custom)[/bold]\n")
    console.print(f"  Data dir: {cc.data_dir}")
    console.print(f"  Repo output: {cc.repo_path}\n")

    # Load discovery metadata
    meta_path = data_dir / "discovery_meta.json"
    if not meta_path.exists():
        console.print("[yellow]No discovery_meta.json — run discovery first[/yellow]")
        console.print("  legalize fetch -c it --all --limit 0")
        return 0
    discovery_meta = json.loads(meta_path.read_text(encoding="utf-8"))

    # Phase 1: Download and process multivigente ZIPs
    console.print("[bold]Phase 1: Bulk collection downloads (multivigente)[/bold]\n")
    phase1_acts = _download_and_process_collections(data_dir, json_dir, discovery_meta)

    # Phase 2: Version-walk remaining acts via API
    console.print("\n[bold]Phase 2: API version-walking for uncovered acts[/bold]\n")
    phase2_acts = _version_walk_remaining(config, data_dir, json_dir, discovery_meta, limit=limit)

    total_fetched = phase1_acts + phase2_acts
    console.print(f"\n[bold green]✓ {total_fetched} norms fetched[/bold green]\n")

    if dry_run:
        console.print("[yellow]dry-run: skipping commits[/yellow]")
        return 0

    # Phase 3: Generate git commits
    console.print("[bold]Phase 3: Generating git history[/bold]\n")
    total_commits = commit_all_fast(config, "it", dry_run=dry_run)
    write_country_meta(config, "it")

    console.print("\n[bold green]✓ Bootstrap IT completed[/bold green]")
    console.print(f"  {total_fetched} norms, {total_commits} commits")
    return total_commits


def _download_and_process_collections(data_dir: Path, json_dir: Path, discovery_meta: dict) -> int:
    """Download multivigente ZIPs and convert to pipeline JSON."""
    from legalize.fetcher.it.parser import NormattivaMetadataParser, NormattivaTextParser

    tp = NormattivaTextParser()
    mp = NormattivaMetadataParser()
    total = 0

    # Clean up stale empty ZIPs from previous broken runs
    for stale in data_dir.glob("*-multi.zip"):
        if stale.stat().st_size < 100:
            stale.unlink()
            logger.info("Removed stale empty ZIP: %s", stale.name)

    for col_name in BULK_COLLECTIONS:
        zip_path = data_dir / f"{col_name.replace(' ', '_')}-multi.zip"

        # Download if not already cached
        if not zip_path.exists():
            console.print(f"  Downloading [bold]{col_name}[/bold] multivigente...")
            url = (
                f"{API_BASE}/collections/download/collection-preconfezionata"
                f"?nome={urllib.parse.quote(col_name)}&formato=HTML&formatoRichiesta=M"
            )
            try:
                r = requests.get(
                    url,
                    headers={"Origin": "https://dati.normattiva.it"},
                    stream=True,
                    timeout=3600,
                    allow_redirects=True,
                )
                r.raise_for_status()
                downloaded = 0
                with open(zip_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                if downloaded == 0:
                    logger.warning(
                        "Collection %s returned 0 bytes — endpoint may be offline", col_name
                    )
                    console.print("    [yellow]0 bytes — skipping (endpoint offline?)[/yellow]")
                    zip_path.unlink(missing_ok=True)
                    continue
                console.print(f"    {downloaded / 1024 / 1024:.1f} MB downloaded")
            except Exception as e:
                console.print(f"    [red]Download failed: {e}[/red]")
                logger.warning("Download failed for collection %s: %s", col_name, e)
                continue

        # Verify ZIP
        try:
            zf = zipfile.ZipFile(zip_path)
        except Exception:
            console.print(f"    [red]Invalid ZIP: {zip_path.name}[/red]")
            logger.warning("Invalid ZIP file: %s", zip_path.name, exc_info=True)
            continue

        # Process HTML versions
        acts_in_zip = _process_zip(zf, json_dir, discovery_meta, tp, mp)
        total += acts_in_zip
        console.print(f"    [green]✓[/green] {col_name}: {acts_in_zip} acts")
        zf.close()

    if total == 0:
        console.print("[yellow]Phase 1 yielded 0 acts — all collections empty or failed[/yellow]")
        logger.warning("Phase 1 yielded 0 acts — falling through to Phase 2 as primary path")

    return total


def _process_zip(
    zf: zipfile.ZipFile,
    json_dir: Path,
    discovery_meta: dict,
    tp,
    mp,
) -> int:
    """Extract acts from a multivigente ZIP and save as pipeline JSON."""
    htmls = [n for n in zf.namelist() if n.endswith(".html")]
    act_dirs: dict[str, list[str]] = {}
    for h in htmls:
        parts = h.split("/")
        if len(parts) >= 2:
            act_dirs.setdefault(parts[0], []).append(h)

    processed = 0
    for dir_name, version_files in act_dirs.items():
        versions_data = []
        codice = None
        for vf in sorted(version_files):
            m = FNAME_RE.match(vf.split("/")[-1])
            if not m:
                continue
            codice = m.group(2)
            v_date = m.group(4) or m.group(1)
            html = zf.read(vf).decode("utf-8", errors="replace")
            body_m = re.search(r"<body>(.*)</body>", html, re.S)
            body = f'<div class="bodyTesto">{body_m.group(1).strip()}</div>' if body_m else ""
            versions_data.append({"html": body, "date": v_date})

        if not codice or not versions_data:
            continue
        safe_id = codice.replace(":", "-").replace("/", "-").replace(" ", "")
        if (json_dir / f"{safe_id}.json").exists():
            continue

        versions_data.sort(key=lambda v: v["date"])
        norm = _build_norm(codice, dir_name, versions_data, discovery_meta, tp, mp)
        if norm:
            save_structured_json(str(json_dir.parent), norm)
            processed += 1

    return processed


def _build_norm(
    codice: str,
    dir_name: str,
    versions_data: list[dict],
    discovery_meta: dict,
    tp,
    mp,
) -> ParsedNorm | None:
    """Build a ParsedNorm from version data."""
    latest = versions_data[-1]
    disc = discovery_meta.get(codice, {})

    tipo_m = re.match(r"([A-Z ]+)_\d", dir_name)
    tipo_desc = tipo_m.group(1).strip() if tipo_m else ""
    tipo_code = disc.get("denominazioneAtto", tipo_desc)
    code = TIPO_TO_CODE.get(tipo_code, TIPO_TO_CODE.get(tipo_desc, ""))

    anno = int(disc.get("annoProvvedimento", 0) or 0)
    mese = int(disc.get("meseProvvedimento", 0) or 0)
    giorno = int(disc.get("giornoProvvedimento", 0) or 0)
    if not anno:
        dm = re.search(r"_(\d{4})(\d{2})(\d{2})_", dir_name)
        if dm:
            anno, mese, giorno = int(dm.group(1)), int(dm.group(2)), int(dm.group(3))

    gu_parts = versions_data[0]["date"].split("-") if versions_data[0]["date"] else ["0", "0", "0"]

    atto = {
        "titolo": disc.get("descrizioneAtto", ""),
        "sottoTitolo": disc.get("titoloAtto", ""),
        "articoloHtml": latest["html"],
        "tipoProvvedimentoDescrizione": tipo_code or tipo_desc,
        "tipoProvvedimentoCodice": code,
        "annoProvvedimento": anno,
        "meseProvvedimento": mese,
        "giornoProvvedimento": giorno,
        "numeroProvvedimento": int(disc.get("numeroProvvedimento", 0) or 0),
        "tipoSupplementoCode": disc.get("tipoSupplemento", "NO"),
        "numeroSupplemento": int(disc.get("numeroSupplemento", 0) or 0),
        "annoGU": int(gu_parts[0]) if len(gu_parts) == 3 else 0,
        "meseGU": int(gu_parts[1]) if len(gu_parts) == 3 else 0,
        "giornoGU": int(gu_parts[2]) if len(gu_parts) == 3 else 0,
        "numeroGU": int(disc.get("numeroGU", 0) or 0),
    }

    data_bytes = json.dumps({"data": {"atto": atto}}, ensure_ascii=False).encode("utf-8")
    try:
        blocks = tp.parse_text(data_bytes)
        metadata = mp.parse(data_bytes, codice)

        reforms = []
        for v in versions_data:
            try:
                p = v["date"].split("-")
                reforms.append(
                    Reform(
                        date=date(int(p[0]), int(p[1]), int(p[2])),
                        norm_id=codice,
                        affected_blocks=(),
                    )
                )
            except (ValueError, IndexError) as e:
                logger.warning("Malformed version date %r for %s: %s", v.get("date"), codice, e)
        if not reforms:
            reforms = [Reform(date=metadata.publication_date, norm_id=codice, affected_blocks=())]

        return ParsedNorm(metadata=metadata, blocks=tuple(blocks), reforms=tuple(reforms))
    except Exception:
        logger.warning("Failed to parse %s", codice, exc_info=True)
        return None


def _version_walk_remaining(
    config: Config,
    data_dir: Path,
    json_dir: Path,
    discovery_meta: dict,
    limit: int | None = None,
) -> int:
    """Version-walk acts not covered by bulk collections via URN API.

    Probes articles 1, 2, and 5 of each law to discover reform dates
    across different parts of the act, not just Art. 1.
    """
    import time

    from legalize.fetcher.it.client import NormattivaClient, _act_to_urn
    from legalize.fetcher.it.parser import (
        NormattivaMetadataParser,
        NormattivaTextParser,
        _parse_vigenza_date,
    )

    tp = NormattivaTextParser()
    mp = NormattivaMetadataParser()

    # Types covered by bulk ZIPs
    covered = set()
    for zp in data_dir.glob("*-multi.zip"):
        try:
            with zipfile.ZipFile(zp) as zf:
                for n in zf.namelist():
                    if n.endswith(".html"):
                        m = FNAME_RE.match(n.split("/")[-1])
                        if m:
                            covered.add(m.group(2))
        except Exception:
            logger.warning("Could not read ZIP for covered-set: %s", zp.name, exc_info=True)

    # Find acts that need API version-walking
    need_api = [
        (codice, act)
        for codice, act in discovery_meta.items()
        if codice not in covered and not (json_dir / f"{codice}.json").exists()
    ]

    if limit:
        need_api = need_api[:limit]

    console.print(f"  {len(need_api)} acts need API version-walking")

    if not need_api:
        return 0

    cc = config.get_country("it")
    total = 0
    errors = 0

    # Probe multiple articles to discover reform dates across the law.
    # Art. 1 = general provisions (often unamended), Art. 2/5 = substantive
    # provisions that catch amendments Art. 1 misses.
    probe_articles = ["1", "2", "5"]

    with NormattivaClient.create(cc) as client:
        for i, (codice, act) in enumerate(need_api):
            if (json_dir / f"{codice}.json").exists():
                continue

            urn = _act_to_urn(act)
            if not urn:
                errors += 1
                continue

            # Probe multiple articles to collect all reform dates
            all_version_dates: set[str] = set()
            latest_html = ""

            for art_num in probe_articles:
                try:
                    versions = client.walk_article_versions(urn, art_num)
                except Exception:
                    continue
                for v in versions:
                    inizio = v.get("vigenza_inizio", "")
                    if inizio:
                        all_version_dates.add(inizio)
                if not latest_html and versions:
                    latest_html = versions[-1].get("html", "")

            # Fallback: fetch base URN for current text if no article worked
            if not latest_html:
                resp = client._fetch_urn(urn)
                if resp and resp.get("data", {}).get("atto"):
                    atto = resp["data"]["atto"]
                    latest_html = atto.get("articoloHtml", "")
                    inizio = atto.get("articoloDataInizioVigenza", "")
                    if inizio:
                        all_version_dates.add(inizio)

            if not latest_html and not all_version_dates:
                errors += 1
                time.sleep(0.5)
                continue

            # Build reforms from collected dates
            reforms = []
            for ds in sorted(all_version_dates):
                d = _parse_vigenza_date(ds)
                if d:
                    reforms.append(Reform(date=d, norm_id=codice, affected_blocks=()))

            # Build atto dict for parser
            gu = act.get("dataGU", "")
            gp = gu.split("-") if gu and len(gu) >= 10 else ["0", "0", "0"]
            atto_out = {
                "titolo": act.get("descrizioneAtto", ""),
                "sottoTitolo": act.get("titoloAtto", ""),
                "articoloHtml": latest_html,
                "tipoProvvedimentoDescrizione": act.get("denominazioneAtto", ""),
                "tipoProvvedimentoCodice": TIPO_TO_CODE.get(act.get("denominazioneAtto", ""), ""),
                "annoProvvedimento": int(act.get("annoProvvedimento", 0) or 0),
                "meseProvvedimento": int(act.get("meseProvvedimento", 0) or 0),
                "giornoProvvedimento": int(act.get("giornoProvvedimento", 0) or 0),
                "numeroProvvedimento": int(act.get("numeroProvvedimento", 0) or 0),
                "tipoSupplementoCode": act.get("tipoSupplemento", "NO"),
                "numeroSupplemento": int(act.get("numeroSupplemento", 0) or 0),
                "annoGU": int(gp[0]),
                "meseGU": int(gp[1]),
                "giornoGU": int(gp[2]),
                "numeroGU": int(act.get("numeroGU", 0) or 0),
            }

            data_bytes = json.dumps({"data": {"atto": atto_out}}, ensure_ascii=False).encode(
                "utf-8"
            )
            try:
                blocks = tp.parse_text(data_bytes)
                metadata = mp.parse(data_bytes, codice)
                if not reforms:
                    reforms = [
                        Reform(
                            date=metadata.publication_date,
                            norm_id=codice,
                            affected_blocks=(),
                        )
                    ]
                save_structured_json(
                    str(data_dir),
                    ParsedNorm(
                        metadata=metadata,
                        blocks=tuple(blocks),
                        reforms=tuple(reforms),
                    ),
                )
                total += 1
            except Exception:
                logger.warning("Failed to parse/save %s", codice, exc_info=True)
                errors += 1

            if total % 500 == 0 and total > 0:
                console.print(
                    f"    {total:,} done, {errors} errors, ~{len(need_api) - i - 1} remaining"
                )
            time.sleep(0.5)

    console.print(f"  [green]✓[/green] {total} acts via API ({errors} errors)")
    return total
