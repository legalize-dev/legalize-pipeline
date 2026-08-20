"""France-specific daily processing.

Downloads LEGI daily increments from DILA and processes modified texts.
Increments are tar.gz files published Mon-Sat at:
  https://echanges.dila.gouv.fr/OPENDATA/LEGI/LEGI_YYYYMMDD-HHMMSS.tar.gz

Unlike Spain (BOE), France does NOT have a reform/404 problem: the
increment names the modified LEGITEXTs directly, so there is no need to
resolve "affected norms" from a reforming disposition.

An increment is a delta, not a standalone text. It carries the modified
struct plus the article and section files that changed — measured on
LEGI_20260819, 64% of the sections a modified code references were absent,
and 83% of the articles reachable through the ones present. It is applied
*over* the consolidated dump
(Freemium_legi_global_*.tar.gz), which supplies everything else; without
that dump on disk a rendered text would be a shell of headings.
"""

from __future__ import annotations

import logging
import re
import tarfile
import tempfile
from datetime import date
from pathlib import Path

import requests
from rich.console import Console

from legalize.committer.git_ops import GitRepo
from legalize.committer.message import build_commit_info
from legalize.config import Config
from legalize.models import CommitType, Reform
from legalize.pipeline import finalize_daily
from legalize.state.store import StateStore, resolve_dates_to_process
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath

console = Console()
logger = logging.getLogger(__name__)

DILA_LEGI_URL = "https://echanges.dila.gouv.fr/OPENDATA/LEGI/"
USER_AGENT = "legalize-bot/1.0 (+https://github.com/legalize-dev/legalize)"

_INCREMENT_RE = re.compile(r'href="(LEGI_(\d{8}-\d{6})\.tar\.gz)"')

# DILA wraps every increment in a YYYYMMDD-HHMMSS/ directory; the global dump
# starts at legi/. Stripping that root is what makes an increment land on top
# of the dump it patches instead of in a sibling tree nobody reads.
_INCREMENT_ROOT_RE = re.compile(r"^\d{8}-\d{6}/")


def _list_increments(session: requests.Session) -> list[tuple[str, str]]:
    """List available LEGI increment files from DILA directory listing.

    Returns sorted list of (filename, url).
    """
    resp = session.get(DILA_LEGI_URL, timeout=30)
    resp.raise_for_status()

    results = []
    for filename, _ts in sorted(_INCREMENT_RE.findall(resp.text)):
        results.append((filename, f"{DILA_LEGI_URL}{filename}"))
    return results


def _find_increment_for_date(
    increments: list[tuple[str, str]], target_date: date
) -> tuple[str, str] | None:
    """Find the increment file matching target_date (LEGI_YYYYMMDD-*.tar.gz)."""
    date_str = target_date.strftime("%Y%m%d")
    for filename, url in increments:
        if f"LEGI_{date_str}" in filename:
            return filename, url
    return None


def _download_increment(session: requests.Session, url: str, dest_path: Path) -> None:
    """Download a LEGI increment tar.gz file with streaming."""
    logger.info("Downloading %s ...", url)
    resp = session.get(url, stream=True, timeout=300)
    resp.raise_for_status()

    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    size_mb = dest_path.stat().st_size / (1024 * 1024)
    logger.info("Downloaded %s (%.1f MB)", dest_path.name, size_mb)


def _extract_increment(tar_path: Path, legi_dir: Path) -> set[str]:
    """Extract increment tar.gz over the dump and return modified LEGITEXT IDs.

    The tar's own root (``YYYYMMDD-HHMMSS/``) is dropped so its files overwrite
    the dump entries they replace. Extracted verbatim they landed in
    ``{legi_dir}/20260819-222711/legi/global/...``, which LEGIClient never
    looks at — so the client kept reading the pre-increment XML and every
    rendered text came out byte-identical to the one already committed.

    Scans tar members to find modified LEGITEXT struct files — this is
    much faster than extracting to a separate dir and doing rglob.
    """
    legitext_ids: set[str] = set()
    members: list[tarfile.TarInfo] = []

    with tarfile.open(tar_path, "r:gz") as tar:
        for member in tar.getmembers():
            member.name = _INCREMENT_ROOT_RE.sub("", member.name, count=1)
            if not member.name:
                continue  # the stripped root entry itself
            # Detect LEGITEXT struct files in the tar
            if "/texte/struct/LEGITEXT" in member.name and member.name.endswith(".xml"):
                # Extract norm_id from path: .../texte/struct/LEGITEXT000006069414.xml
                norm_id = Path(member.name).stem
                legitext_ids.add(norm_id)
            members.append(member)
        tar.extractall(path=legi_dir, members=members, filter="data")

    logger.info("Extracted %s: %d LEGITEXT(s) modified", tar_path.name, len(legitext_ids))
    return legitext_ids


def _repo_scope(repo_path: str | Path) -> set[str]:
    """LEGITEXT ids tracked in the country repo — one .md per text, named by id.

    The repo is the scope and it is present in every environment. The filter
    used to test the client's dump index instead, which is neither: it lists
    every text in the dump (~114k, not the ~80 codes we track) and it is empty
    whenever the dump is not on disk — as on a CI runner, where it silently
    discarded 100% of the daily changes for four and a half months.
    """
    return {p.stem for p in Path(repo_path).rglob("LEGITEXT*.md")}


def daily(
    config: Config,
    target_date: date | None = None,
    dry_run: bool = False,
) -> int:
    """Daily processing for France: download LEGI increment and process changes."""
    from legalize.fetcher.fr.client import LEGIClient
    from legalize.fetcher.fr.parser import LEGIMetadataParser, LEGITextParser

    cc = config.get_country("fr")
    legi_dir = cc.source.get("legi_dir", "")
    if not legi_dir:
        console.print(
            "[red]legi_dir not configured for France. "
            "Set it in config.yaml or use --legi-dir.[/red]"
        )
        return 0

    legi_path = Path(legi_dir)
    legi_path.mkdir(parents=True, exist_ok=True)

    scope = _repo_scope(cc.repo_path)

    if not dry_run:
        # Both of these used to degrade into "✓ 0 commits" — a green run that
        # had silently done nothing. They are fatal: neither is recoverable
        # from inside the run, and a daily that cannot see its inputs must say
        # so rather than report success.
        if not scope:
            raise RuntimeError(
                f"No LEGITEXT*.md found under {cc.repo_path} — nothing in scope. "
                "Wrong --repo-path, or the country was never bootstrapped."
            )
        if not (legi_path / "legi" / "global").is_dir():
            raise RuntimeError(
                f"LEGI dump not found under {legi_path}/legi/global. Daily increments "
                "only carry the fragments that changed (on LEGI_20260819, 64% of the "
                "sections a modified code references were not in the increment), so "
                "rendering a complete text needs the consolidated dump underneath. "
                f"Extract Freemium_legi_global_*.tar.gz from {DILA_LEGI_URL} and point "
                "--legi-dir at it."
            )

    state = StateStore(cc.state_path)
    state.load()

    dates_to_process = resolve_dates_to_process(
        state,
        cc.repo_path,
        target_date,
        skip_weekdays={6},
    )
    if dates_to_process is None:
        console.print("[yellow]No last date found. Use --date or run bootstrap.[/yellow]")
        return 0
    if not dates_to_process:
        console.print("[green]Nothing to process — up to date[/green]")
        return 0

    console.print(
        f"[bold]Daily FR — processing {len(dates_to_process)} day(s), "
        f"{len(scope)} text(s) in scope[/bold]"
    )

    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    commits_created = 0
    errors: list[str] = []

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    try:
        increments = _list_increments(session)
    except requests.RequestException:
        logger.error("Could not list DILA increments", exc_info=True)
        console.print("[red]Error listing DILA increments[/red]")
        return 0

    text_parser = LEGITextParser()
    meta_parser = LEGIMetadataParser()
    client = LEGIClient(legi_path)

    for current_date in dates_to_process:
        console.print(f"\n  [bold]{current_date}[/bold]")

        match = _find_increment_for_date(increments, current_date)
        if match is None:
            console.print("    No increment available (holiday/no changes)")
            state.last_summary_date = current_date
            continue

        filename, url = match

        if dry_run:
            console.print(f"    [dim]Would download {filename}[/dim]")
            state.last_summary_date = current_date
            continue

        with tempfile.TemporaryDirectory() as tmpdir:
            tar_path = Path(tmpdir) / filename
            try:
                _download_increment(session, url, tar_path)
                all_modified = _extract_increment(tar_path, legi_path)
            except (requests.RequestException, tarfile.TarError, OSError) as e:
                msg = f"Error downloading/extracting {filename}: {e}"
                logger.error(msg, exc_info=True)
                errors.append(msg)
                continue

        # Filter to the norms we actually track (the repo's own file list)
        modified_ids = sorted(all_modified & scope)

        if not modified_ids:
            console.print("    No texts modified in scope")
            state.last_summary_date = current_date
            continue

        console.print(f"    {len(modified_ids)} text(s) modified")

        for norm_id in modified_ids:
            try:
                meta_data = client.get_metadata(norm_id)
                metadata = meta_parser.parse(meta_data, norm_id)

                text_data = client.get_text(norm_id)
                blocks = text_parser.parse_text(text_data)

                file_path = norm_to_filepath(metadata)
                markdown = render_norm_at_date(metadata, blocks, current_date)

                # Safety: skip if generated markdown is suspiciously short
                existing_path = Path(cc.repo_path) / file_path
                if existing_path.exists():
                    existing_size = existing_path.stat().st_size
                    if len(markdown) < existing_size * 0.5:
                        logger.warning(
                            "Skipping %s: markdown too short (%d vs %d bytes)",
                            norm_id,
                            len(markdown),
                            existing_size,
                        )
                        continue

                changed = repo.write_and_add(file_path, markdown)
                if not changed:
                    console.print(f"    [dim]⏭ {metadata.short_title} — no changes[/dim]")
                    continue

                source_id = f"LEGI-DAILY-{current_date.isoformat()}-{norm_id}"
                reform = Reform(
                    date=current_date,
                    norm_id=source_id,
                    affected_blocks=(),
                )
                info = build_commit_info(
                    CommitType.REFORM,
                    metadata,
                    reform,
                    blocks,
                    file_path,
                    markdown,
                )
                sha = repo.commit(info)

                if sha:
                    commits_created += 1
                    console.print(f"    [green]✓[/green] {info.subject}")

            except (ValueError, FileNotFoundError, OSError) as e:
                msg = f"Error processing {norm_id}: {e}"
                logger.error(msg, exc_info=True)
                errors.append(msg)

        state.last_summary_date = current_date

    session.close()

    return finalize_daily(
        repo,
        state,
        dates_to_process,
        commits_created,
        errors,
        dry_run=dry_run,
        push=config.git.push,
    )
