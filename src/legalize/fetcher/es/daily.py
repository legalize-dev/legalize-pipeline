"""Spain-specific daily processing.

Processes BOE daily summaries (sumarios) and generates commits for new legislation.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import requests
from lxml import etree

from rich.console import Console

from legalize.committer.git_ops import GitRepo
from legalize.committer.message import build_commit_info
from legalize.config import Config
from legalize.models import CommitType, Reform
from legalize.pipeline import SKIP_WEEKDAYS, finalize_daily
from legalize.state.store import StateStore, resolve_dates_to_process
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath
from legalize.transformer.xml_parser import extract_reforms, parse_text_xml

console = Console()
logger = logging.getLogger(__name__)


def _parse_updated_ids(xml_data: bytes) -> list[str]:
    """BOE-IDs from the consolidated-updates listing, newest update first."""
    root = etree.fromstring(xml_data)
    ids: list[str] = []
    for item in root.iter("item"):
        ref = (item.findtext("identificador") or "").strip()
        if ref.startswith("BOE-A-"):
            ids.append(ref)
    return ids


def _updated_norms(client, start: date, end: date) -> list[str]:
    """Norms the BOE re-consolidated in the window, or [] if the query failed."""
    try:
        return _parse_updated_ids(client.get_updated(start, end))
    except (requests.RequestException, etree.XMLSyntaxError):
        logger.warning("Could not list norms updated between %s and %s", start, end)
        return []


def _commit_reforms(
    client,
    repo: GitRepo,
    start: date,
    current_date: date,
    errors: list[str],
) -> int:
    """Commits the norms already in the repo whose consolidated text the BOE updated.

    Deterministic end to end: the window comes from the source's own
    ``fecha_actualizacion``, and the amending norm from the ``<version>`` the source
    stamps on every block of the text. Nothing is inferred from a disposition title,
    which says "Reforma del apartado 3 del artículo 69" as readily as it says
    "modifica" — and the fourth reform of the Constitution was lost that way.
    """
    from legalize.fetcher.es.metadata import parse_metadata

    commits = 0
    for norm_id in _updated_norms(client, start, current_date):
        try:
            meta_xml = client.get_metadata(norm_id)
            try:
                diario_xml = client.get_disposition_xml(norm_id)
            except (requests.RequestException, ValueError):
                diario_xml = None
            metadata = parse_metadata(meta_xml, norm_id, diario_xml=diario_xml)

            file_path = norm_to_filepath(metadata)
            if not repo.has_file(file_path):
                logger.debug("Skipping %s — not in repo", norm_id)
                continue

            text_xml = client.get_consolidated_text(norm_id, bypass_cache=True)
            blocks = parse_text_xml(text_xml)
            reforms = extract_reforms(blocks)
            if not reforms:
                continue

            # The newest stamp the rendered text actually contains: the body below is
            # the law as of current_date, so attributing it to an amendment published
            # later would label a text with a change that is not in it. On the daily
            # that is the amendment just folded in; on a backfill of an old date it is
            # what that day published, which is what makes a range recoverable.
            # ponytail: a norm re-consolidated without being amended stamps its own
            # id here, the guard below reads that as already committed, and the run
            # produces nothing for it. That is the right call until a BOE-side
            # correction of an unamended text needs publishing.
            applicable = [r for r in reforms if r.date <= current_date]
            if not applicable:
                continue
            reform = applicable[-1]
            if repo.has_commit_with_source_id(reform.norm_id, metadata.identifier):
                continue

            markdown = render_norm_at_date(metadata, blocks, current_date)
            if not repo.write_and_add(file_path, markdown):
                continue

            info = build_commit_info(
                CommitType.REFORM, metadata, reform, blocks, file_path, markdown
            )
            if repo.commit(info):
                commits += 1
                console.print(f"    [green]✓[/green] {info.subject}")

        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                logger.debug("Updated norm %s not in consolidated DB", norm_id)
            else:
                msg = f"Error processing updated norm {norm_id}"
                logger.error(msg, exc_info=True)
                errors.append(msg)
        except (requests.RequestException, ValueError, OSError):
            msg = f"Error processing updated norm {norm_id}"
            logger.error(msg, exc_info=True)
            errors.append(msg)

    return commits


def daily(
    config: Config,
    target_date: date | None = None,
    dry_run: bool = False,
) -> int:
    """Daily processing: process BOE summary/summaries."""
    from legalize.fetcher.cache import FileCache
    from legalize.fetcher.es.client import BOEClient
    from legalize.fetcher.es.config import BOEConfig, ScopeConfig
    from legalize.fetcher.es.metadata import parse_metadata
    from legalize.fetcher.es.sumario import parse_summary

    cc = config.get_country("es")
    source = cc.source
    boe_config = BOEConfig(
        base_url=source.get("base_url", BOEConfig.base_url),
        requests_per_second=source.get("requests_per_second", BOEConfig.requests_per_second),
        request_timeout=source.get("request_timeout", BOEConfig.request_timeout),
        max_retries=source.get("max_retries", BOEConfig.max_retries),
    )
    scope = ScopeConfig(
        ranks=source.get("rangos", []),
        fixed_norms=source.get("normas_fijas", []),
    )
    cache = FileCache(cc.cache_dir)
    state = StateStore(cc.state_path)
    state.load()

    dates_to_process = resolve_dates_to_process(
        state,
        cc.repo_path,
        target_date,
        skip_weekdays=SKIP_WEEKDAYS["es"],
    )
    if dates_to_process is None:
        console.print("[yellow]No last summary found. Use --date or run bootstrap.[/yellow]")
        return 0
    if not dates_to_process:
        console.print("[green]Nothing to process — up to date[/green]")
        return 0

    console.print(f"[bold]Daily — processing {len(dates_to_process)} day(s)[/bold]")

    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    commits_created = 0
    errors: list[str] = []

    with BOEClient(boe_config, cache) as client:
        for current_date in dates_to_process:
            console.print(f"\n  [bold]{current_date}[/bold]")

            # Amendments first, and before the summary is even fetched: they are the
            # source's own list of what changed, so a day with no summary (or a failed
            # one) must not skip them. The window reaches back one day to cover the
            # Sunday the BOE consolidates on and this schedule never runs; re-seeing a
            # norm is a no-op, the Source-Id guard drops it.
            if not dry_run:
                commits_created += _commit_reforms(
                    client,
                    repo,
                    current_date - timedelta(days=1),
                    current_date,
                    errors,
                )

            try:
                xml_data = client.get_sumario(current_date)
                dispositions = parse_summary(xml_data, scope)
            except requests.RequestException:
                msg = f"Error fetching summary for {current_date}"
                logger.error(msg, exc_info=True)
                errors.append(msg)
                continue

            if not dispositions:
                console.print("    No dispositions in scope")
                continue

            console.print(f"    {len(dispositions)} dispositions in scope")

            for disp in dispositions:
                if dry_run:
                    console.print(f"    [dim]{disp.id_boe} — {disp.title[:60]}...[/dim]")
                    continue

                # A norm gets a file iff the BOE keeps a consolidated text for it.
                # That is the source's own answer to "is this a norm of the corpus?",
                # and it settles what a title cannot: a Reforma, a corrección de
                # errores or a sentencia has no consolidated text of its own, and what
                # it did to the corpus arrives as an update to the norm it touched —
                # which the amendment pass above publishes.
                try:
                    meta_xml = client.get_metadata(disp.id_boe)
                    try:
                        diario_xml = client.get_disposition_xml(disp.id_boe)
                    except (requests.RequestException, ValueError):
                        diario_xml = None
                    metadata = parse_metadata(meta_xml, disp.id_boe, diario_xml=diario_xml)
                    text_xml = client.get_consolidated_text(metadata.identifier)
                    blocks = parse_text_xml(text_xml)

                    file_path = norm_to_filepath(metadata)
                    markdown = render_norm_at_date(metadata, blocks, current_date)

                    if repo.has_commit_with_source_id(disp.id_boe):
                        continue

                    if not repo.write_and_add(file_path, markdown):
                        continue

                    reform = Reform(date=current_date, norm_id=disp.id_boe, affected_blocks=())
                    info = build_commit_info(
                        CommitType.NEW, metadata, reform, blocks, file_path, markdown
                    )
                    if repo.commit(info):
                        commits_created += 1
                        console.print(f"    [green]✓[/green] {info.subject}")

                except requests.HTTPError as e:
                    if e.response is not None and e.response.status_code == 404:
                        console.print(f"    [dim]⏭ {disp.id_boe} — no consolidated text[/dim]")
                    else:
                        msg = f"Error processing {disp.id_boe}"
                        logger.error(msg, exc_info=True)
                        errors.append(msg)
                except (requests.RequestException, ValueError, OSError):
                    msg = f"Error processing {disp.id_boe}"
                    logger.error(msg, exc_info=True)
                    errors.append(msg)

            state.last_summary_date = current_date

    return finalize_daily(
        repo,
        state,
        dates_to_process,
        commits_created,
        errors,
        dry_run=dry_run,
        push=config.git.push,
    )
