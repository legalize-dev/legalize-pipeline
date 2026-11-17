"""Portugal-specific daily processing.

Two things happen every day and they are not the same thing:

1. **New diplomas** are published in the Diário da República. Found by walking the
   day's journal issues, committed as ``[new]``.
2. **Existing consolidated diplomas are re-consolidated** because something amended
   them. DRE does this on its own schedule, days or weeks after the amending act
   appears, so watching the day's publications would miss it.

The second is what makes Portugal a versioned corpus rather than a pile of
snapshots, and it is detected for the price of one HTTP request: the consolidated
sitemap carries a ``<lastmod>`` per diploma. Diff it against yesterday's copy and
re-fetch exactly the diplomas whose consolidation moved.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path

from rich.console import Console

from legalize.committer.git_ops import GitRepo
from legalize.committer.message import build_commit_info
from legalize.config import Config
from legalize.fetcher.pt.identifier import build_identifier
from legalize.models import CommitType, Reform
from legalize.pipeline import SKIP_WEEKDAYS, commit_one, finalize_daily
from legalize.state.store import StateStore, resolve_dates_to_process
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath

console = Console()
logger = logging.getLogger(__name__)

_URL_ENTRY = re.compile(
    r"<url>\s*<loc>([^<]+)</loc>\s*(?:<lastmod>([^<]*)</lastmod>)?", re.IGNORECASE | re.DOTALL
)
_CONS_URL = re.compile(r"/dr/legislacao-consolidada/([^/]+)/(\d{4})-(\d+)")

# DRE publishes supplements later the same day (Portaria 404-A/2026, Decreto-Lei
# 195-A/2026), after this run has walked that day, and the cursor never returns to
# it: 21 acts from 2026-08-26 to 2026-11-08, almost all of them -A/-B numbers, some on
# a Saturday this schedule never walks. So each run walks the last days again,
# weekends included; what is already published is skipped before anything is fetched.
SUPPLEMENT_LOOKBACK_DAYS = 3


def with_recent_days(dates: list[date], today: date) -> list[date]:
    """The days to walk: the cursor's, plus the last few whatever their weekday."""
    recent = {today - timedelta(days=n) for n in range(1, SUPPLEMENT_LOOKBACK_DAYS + 1)}
    return sorted(set(dates) | recent)


def _lastmod_state_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / "consolidated_lastmod.json.gz"


def _read_lastmods(data_dir: str | Path) -> dict[str, str]:
    path = _lastmod_state_path(data_dir)
    if not path.exists():
        return {}
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        logger.warning("Unreadable lastmod state at %s, treating as empty", path)
        return {}


def _write_lastmods(data_dir: str | Path, lastmods: dict[str, str]) -> None:
    path = _lastmod_state_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(lastmods, handle)


def fetch_consolidated_lastmods(client) -> dict[str, str]:
    """``{norm_id: lastmod}`` for every consolidated diploma. One request."""
    from legalize.fetcher.pt.discovery import CONSOLIDATED_SITEMAP, SITEMAP_INDEX

    index = client._api.get_text_body(SITEMAP_INDEX)
    target = next(
        (u for u in re.findall(r"<loc>([^<]+)</loc>", index) if u.endswith(CONSOLIDATED_SITEMAP)),
        None,
    )
    if not target:
        raise RuntimeError("The consolidated sitemap is no longer in the DRE index")

    lastmods: dict[str, str] = {}
    for url, lastmod in _URL_ENTRY.findall(client._api.get_text_body(target)):
        match = _CONS_URL.search(url)
        if match:
            lastmods[f"cons:{match.group(1)}:{match.group(2)}-{match.group(3)}"] = lastmod or ""
    return lastmods


def reconsolidated_since_last_run(client, data_dir: str | Path) -> tuple[list[str], dict[str, str]]:
    """Which consolidated diplomas DRE has touched since we last looked."""
    current = fetch_consolidated_lastmods(client)
    previous = _read_lastmods(data_dir)
    if not previous:
        # First run after the bootstrap: record the baseline, claim nothing changed.
        return [], current
    changed = [nid for nid, stamp in current.items() if previous.get(nid) != stamp]
    return changed, current


def daily(config: Config, target_date: date | None = None, dry_run: bool = False) -> int:
    """Daily processing for Portugal: new diplomas + re-consolidated ones."""
    from legalize.fetcher.pt import analise_juridica
    from legalize.fetcher.pt.client import DREClient
    from legalize.fetcher.pt.discovery import DREDiscovery
    from legalize.fetcher.pt.dre_api import DREApiError
    from legalize.fetcher.pt.parser import DREMetadataParser
    from legalize.pipeline import generic_fetch_one

    cc = config.get_country("pt")
    state = StateStore(cc.state_path)
    state.load()

    # Without these the daily quietly regresses every law it touches: descriptors
    # come back as nothing, and an amendment lands as a new law with no reform
    # recorded against the law it amended. They are corpus-wide maps, so nothing in
    # the per-norm fetch path would load them.
    loaded = analise_juridica.install(cc.data_dir)
    console.print(f"  [dim]análise jurídica: {loaded or 'no maps found'}[/dim]")

    dates_to_process = resolve_dates_to_process(
        # Monday to Friday: the daily has run on 121 of 125 weekdays, and the
        # four misses were Portuguese public holidays.
        state,
        cc.repo_path,
        target_date,
        skip_weekdays=SKIP_WEEKDAYS["pt"],
    )
    if dates_to_process is None:
        console.print("[yellow]No last date found. Use --date or run bootstrap.[/yellow]")
        return 0
    if target_date is None:
        dates_to_process = with_recent_days(dates_to_process, date.today())

    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    meta_parser = DREMetadataParser()
    discovery = DREDiscovery.create({**cc.source, "cache_dir": cc.data_dir})
    commits_created = 0
    errors: list[str] = []
    # Laws today's diplomas say they change. Collected as we go and resolved once at
    # the end, because the record of the amendment lives on the amended law's page,
    # not on the act's, so it has to be looked up per law rather than per act.
    amended_today: set[str] = set()

    with DREClient.create(cc) as client:
        # ---- 1. diplomas DRE re-consolidated: one commit per new reform ----
        # The sitemap baseline lives next to the run state, which the daily workflow
        # caches between runs. In data_dir, which it does not, every CI run found no
        # baseline, recorded one and claimed nothing changed: step 1 never ran there.
        lastmod_dir = Path(cc.state_path).parent
        try:
            changed, lastmods = reconsolidated_since_last_run(client, lastmod_dir)
        except DREApiError:
            logger.exception("DRE API contract broken while reading the sitemap — aborting")
            raise
        if changed:
            console.print(f"[bold]{len(changed)} diploma(s) re-consolidated[/bold]")
        published = repo.load_existing_commits() if changed and not dry_run else set()
        for norm_id in changed:
            if dry_run:
                console.print(f"  [dim]would refresh {norm_id}[/dim]")
                continue
            try:
                commits_created += _commit_versions(
                    config, norm_id, generic_fetch_one, published=published
                )
            except DREApiError:
                logger.exception("DRE API contract broken — aborting daily run")
                raise
            except Exception as exc:
                errors.append(f"Error refreshing {norm_id}: {exc}")
                logger.exception("Error refreshing %s", norm_id)

        # ---- 2. diplomas published on each pending date ----
        for current_date in dates_to_process:
            console.print(f"\n  [bold]{current_date}[/bold]")
            try:
                norm_ids = list(discovery.discover_daily(client, current_date))
            except DREApiError:
                # A broken contract is not a quiet day: every remaining date would
                # fail the same way and record itself as "no new norms".
                logger.exception("DRE API contract broken — aborting daily run")
                raise
            except Exception as exc:
                errors.append(f"Error discovering {current_date}: {exc}")
                logger.exception("Error discovering %s", current_date)
                continue

            if not norm_ids:
                console.print("    No new norms found")
                state.finish_day(current_date, errors)
                continue

            console.print(f"    {len(norm_ids)} norm(s) found")

            for norm_id in norm_ids:
                if dry_run:
                    console.print(f"    [dim]{norm_id}[/dim]")
                    continue
                _surface, tipo, key = norm_id.split(":", 2)
                identifier = build_identifier(f"/dr/detalhe/{tipo}/{key}", "")
                if repo.has_commit_with_source_id(identifier, identifier):
                    continue  # published by an earlier run: the lookback walks days twice
                try:
                    markdown = commit_new(
                        config, repo, client, meta_parser, norm_id, generic_fetch_one
                    )
                    if markdown is None:
                        continue
                    commits_created += 1
                    amended_today |= analise_juridica.targets_named_by(markdown)
                except DREApiError:
                    logger.exception("DRE API contract broken — aborting daily run")
                    raise
                except Exception as exc:
                    errors.append(f"Error processing {norm_id}: {exc}")
                    logger.exception("Error processing %s", norm_id)

            state.finish_day(current_date, errors)

        # ---- 3. the laws today's acts amended: one commit each, body unchanged ----
        if amended_today and not dry_run:
            try:
                changed_laws = analise_juridica.refresh_amendments(
                    client._api, cc.data_dir, amended_today
                )
            except Exception as exc:
                errors.append(f"Error refreshing amendments: {exc}")
                logger.exception("Error refreshing amendments")
                changed_laws = set()
            if changed_laws:
                console.print(f"\n[bold]{len(changed_laws)} law(s) amended today[/bold]")
                # Read after step 1, which commits through its own GitRepo.
                consolidated = _consolidated_laws(repo)
            for law_id in sorted(changed_laws):
                try:
                    _surface, tipo, key = law_id.split(":", 2)
                    if build_identifier(f"/dr/detalhe/{tipo}/{key}", "") in consolidated:
                        # The bootstrap's rule (bootstrap.py): a law DRE consolidates is
                        # published from that surface, and its as-published twin must
                        # never land on it. Its re-consolidation, in step 1, is what
                        # records the amendment.
                        console.print(f"  [dim]{law_id}: consolidated, not overwritten[/dim]")
                        continue
                    commits_created += _commit_versions(config, law_id, generic_fetch_one)
                except Exception as exc:
                    errors.append(f"Error recording amendment on {law_id}: {exc}")
                    logger.exception("Error recording amendment on %s", law_id)

        # Only record the sitemap baseline once the run got this far: crashing
        # mid-run must not make us forget the diplomas we had not refreshed yet.
        if not dry_run and not errors:
            _write_lastmods(lastmod_dir, lastmods)

    return finalize_daily(
        repo,
        state,
        dates_to_process,
        commits_created,
        errors,
        dry_run=dry_run,
        push=config.git.push,
    )


def commit_new(config, repo, client, meta_parser, norm_id: str, fetch_one) -> str | None:
    """Fetch one as-published diploma and commit it as ``[new]``.

    Returns its Markdown when a commit landed, None when there was nothing to
    write: no data, the same text already in the file, or another act's file.
    """
    norm = fetch_one(config, "pt", norm_id, force=True)
    if norm is None:
        return None
    metadata = meta_parser.parse(client.get_metadata(norm_id), norm_id)
    file_path = norm_to_filepath(metadata)
    markdown = render_norm_at_date(
        metadata, norm.blocks, metadata.publication_date, include_all=True
    )
    if not repo.write_and_add(file_path, markdown):
        return None
    reform = Reform(date=metadata.publication_date, norm_id=metadata.identifier, affected_blocks=())
    info = build_commit_info(CommitType.NEW, metadata, reform, norm.blocks, file_path, markdown)
    if not repo.commit(info):
        return None
    console.print(f"    [green]✓[/green] {info.subject}")
    return markdown


def _commit_versions(config, norm_id: str, fetch_one, published: set | None = None) -> int:
    """Re-fetch a diploma and commit any version or amendment it has gained.

    Through ``commit_one``, which renders each reform as the bootstrap's fast import
    does, and not a copy of it: the copy never named the amending act, so every
    amendment the daily recorded on an as-enacted law dropped its ``last_amendment``.

    ``published`` (the repo's Source-Id/Norm-Id pairs) makes it a re-consolidation:
    only versions that extend what the repo already publishes are committed.
    """
    norm = fetch_one(config, "pt", norm_id, force=True)
    if norm is None:
        return 0
    if published is not None:
        refusal = not_an_extension(norm, published)
        if refusal:
            console.print(f"  [yellow]{norm_id}: {refusal}; not committed[/yellow]")
            logger.warning("%s (%s): %s", norm_id, norm.metadata.identifier, refusal)
            return 0
    return commit_one(config, "pt", norm.metadata.identifier)


def not_an_extension(norm, published: set[tuple[str, str]]) -> str | None:
    """Why committing this consolidated history would not just extend the repo's.

    ``commit_one`` commits every version the repo lacks, in date order, onto the
    file as it stands. That is an append only when the repo already publishes the
    law from this surface and lacks nothing but its newest versions:

    - Not published from it at all — a law the repo has as published, or not at
      all — and the first commit would be a second ``[bootstrap]``, the whole text
      switched to the consolidated surface on top of its as-published history.
      The consolidated sitemap also lists diplomas the corpus leaves out
      (despachos, avisos): the same rule keeps those out.
    - A missing version is not newer than the newest one published: DRE
      back-filled an amendment, or moved one to an earlier date (the Código Penal's
      2026-09-01 version is 2026-08-24 now). Committing it would put a version
      dated earlier on top of a later one.
    """
    identifier = norm.metadata.identifier
    # A consolidated Source-Id ends in the version's date (parser._reform_source_id).
    newest = max(
        (
            source.rsplit("@", 1)[1]
            for source, law in published
            if law == identifier and "@" in source
        ),
        default=None,
    )
    if newest is None:
        return "not published from the consolidated surface"
    missing = [r for r in norm.reforms if (r.norm_id, identifier) not in published]
    if any(r.date.isoformat() <= newest for r in missing):
        return f"a missing version is not newer than the published {newest}"
    return None


def _consolidated_laws(repo: GitRepo) -> set[str]:
    """The laws this repo publishes from DRE's consolidated surface.

    Only a consolidated version has an ``@`` in its Source-Id (``_reform_source_id``
    in the parser); an act, or an as-published bootstrap, never does.
    """
    return {norm for source, norm in repo.load_existing_commits() if "@" in source}
