"""Spain-specific daily processing.

Processes BOE daily summaries (sumarios) and generates commits for new legislation.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import requests
from lxml import etree

from rich.console import Console

from legalize.committer.git_ops import GitRepo
from legalize.committer.message import build_commit_info
from legalize.config import Config
from legalize.models import CommitType, Disposition, Reform
from legalize.pipeline import SKIP_WEEKDAYS, finalize_daily
from legalize.state.store import StateStore, resolve_dates_to_process
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath
from legalize.transformer.xml_parser import parse_text_xml

console = Console()
logger = logging.getLogger(__name__)


def _parse_affected_ids(xml_data: bytes) -> list[str]:
    """Extracts BOE-IDs of affected norms from a raw disposition XML.

    Parses the ``<analisis><referencias><anteriores>`` section and
    returns the ``referencia`` attribute of each ``<anterior>`` element.
    """
    root = etree.fromstring(xml_data)
    ids: list[str] = []
    for anterior in root.iter("anterior"):
        ref = anterior.get("referencia", "")
        if ref.startswith("BOE-A-"):
            ids.append(ref)
    return ids


def _resolve_affected_norms(client, disp: Disposition) -> list[str]:
    """Fetches the disposition XML and returns the IDs of affected norms."""
    try:
        xml_data = client.get_disposition_xml(disp.id_boe)
        return _parse_affected_ids(xml_data)
    except (requests.RequestException, etree.XMLSyntaxError):
        logger.warning("Could not resolve affected norms for %s", disp.id_boe)
        return []


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

            repo_root = Path(cc.repo_path)

            for disp in dispositions:
                if dry_run:
                    console.print(f"    [dim]{disp.id_boe} — {disp.title[:60]}...[/dim]")
                    continue

                if disp.is_new or disp.is_correction:
                    # Process the disposition itself (new law or correction)
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

                        changed = repo.write_and_add(file_path, markdown)
                        if not changed:
                            continue

                        commit_type = (
                            CommitType.CORRECTION if disp.is_correction else CommitType.NEW
                        )
                        reform = Reform(date=current_date, norm_id=disp.id_boe, affected_blocks=())
                        info = build_commit_info(
                            commit_type, metadata, reform, blocks, file_path, markdown
                        )
                        sha = repo.commit(info)

                        if sha:
                            commits_created += 1
                            console.print(f"    [green]✓[/green] {info.subject}")

                    except requests.HTTPError as e:
                        if e.response is not None and e.response.status_code == 404:
                            console.print(f"    [dim]⏭ {disp.id_boe} — not consolidated yet[/dim]")
                        else:
                            msg = f"Error processing {disp.id_boe}"
                            logger.error(msg, exc_info=True)
                            errors.append(msg)
                    except (requests.RequestException, ValueError, OSError):
                        msg = f"Error processing {disp.id_boe}"
                        logger.error(msg, exc_info=True)
                        errors.append(msg)
                else:
                    # Reform: re-download the affected (reformed) norms
                    affected_ids = _resolve_affected_norms(client, disp)
                    if not affected_ids:
                        console.print(f"    [dim]⏭ {disp.id_boe} — no affected norms found[/dim]")
                        continue

                    for affected_id in affected_ids:
                        if repo.has_commit_with_source_id(disp.id_boe, affected_id):
                            continue

                        try:
                            meta_xml = client.get_metadata(affected_id)
                            try:
                                diario_xml = client.get_disposition_xml(affected_id)
                            except (requests.RequestException, ValueError):
                                diario_xml = None
                            metadata = parse_metadata(meta_xml, affected_id, diario_xml=diario_xml)
                            text_xml = client.get_consolidated_text(
                                metadata.identifier, bypass_cache=True
                            )
                            blocks = parse_text_xml(text_xml)

                            file_path = norm_to_filepath(metadata)
                            if not (repo_root / file_path).exists():
                                logger.debug("Skipping %s — not in repo", affected_id)
                                continue

                            markdown = render_norm_at_date(metadata, blocks, current_date)

                            changed = repo.write_and_add(file_path, markdown)
                            if not changed:
                                continue

                            reform = Reform(
                                date=current_date,
                                norm_id=disp.id_boe,
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

                        except requests.HTTPError as e:
                            if e.response is not None and e.response.status_code == 404:
                                logger.debug(
                                    "Affected norm %s not in consolidated DB",
                                    affected_id,
                                )
                            else:
                                msg = (
                                    f"Error processing affected norm {affected_id}"
                                    f" from {disp.id_boe}"
                                )
                                logger.error(msg, exc_info=True)
                                errors.append(msg)
                        except (requests.RequestException, ValueError, OSError):
                            msg = f"Error processing affected norm {affected_id} from {disp.id_boe}"
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
