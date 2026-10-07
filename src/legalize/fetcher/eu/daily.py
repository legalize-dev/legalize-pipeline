"""Record EU source versions, including amendments of unconsolidated acts."""

from __future__ import annotations

import logging
import json
from datetime import date

from legalize.committer.git_ops import GitRepo
from legalize.config import Config
from legalize.fetcher.eu.client import EURLexClient
from legalize.fetcher.eu.discovery import EURLexDiscovery
from legalize.fetcher.eu.parser import EURLexMetadataParser, EURLexTextParser
from legalize.models import ParsedNorm
from legalize.pipeline import commit_one, finalize_daily
from legalize.state.store import StateStore, resolve_dates_to_process
from legalize.storage import save_structured_json

logger = logging.getLogger(__name__)


def daily(config: Config, target_date: date | None = None, dry_run: bool = False) -> int:
    """Use the same source IDs and version chain as the bootstrap."""
    cc = config.get_country("eu")
    state = StateStore(cc.state_path)
    state.load()
    dates = resolve_dates_to_process(state, cc.repo_path, target_date)
    if not dates:
        return 0
    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    discovery = EURLexDiscovery.create(cc)
    text_parser = EURLexTextParser()
    meta_parser = EURLexMetadataParser()
    created = 0
    errors = []
    with EURLexClient.create(cc) as client:
        for current_date in dates:
            errors_before = len(errors)
            try:
                ids = list(discovery.discover_daily(client, current_date))
                for norm_id in ids:
                    if dry_run:
                        logger.info("Would refresh %s", norm_id)
                        continue
                    try:
                        metadata = client.get_metadata_sparql(norm_id)
                        client._merge_list_facts(norm_id, metadata)
                        meta_data = json.dumps(metadata).encode("utf-8")
                        data = client.get_text(norm_id, meta_data=meta_data)
                        norm = ParsedNorm(
                            metadata=meta_parser.parse(meta_data, norm_id),
                            blocks=tuple(text_parser.parse_text(data)),
                            reforms=tuple(text_parser.extract_reforms(data)),
                        )
                        save_structured_json(cc.data_dir, norm)
                        created += commit_one(config, "eu", norm.metadata.identifier)
                        client.evict_cache(norm_id)
                    except Exception as exc:
                        logger.exception("Failed to refresh %s", norm_id)
                        errors.append(f"{norm_id}: {exc}")
                if len(errors) != errors_before:
                    break
                if not dry_run:
                    state.last_summary_date = current_date
            except Exception as exc:
                logger.exception("Failed to discover %s", current_date)
                errors.append(f"{current_date}: {exc}")
                break
    return finalize_daily(
        repo, state, dates, created, errors, dry_run=dry_run, push=config.git.push
    )
