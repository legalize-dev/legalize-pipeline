"""Record EU source versions, including amendments of unconsolidated acts."""

from __future__ import annotations

import logging
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date

from legalize.committer.git_ops import GitRepo
from legalize.config import Config
from legalize.coverage import _frontmatter_of
from legalize.fetcher.eu.client import EURLexClient
from legalize.fetcher.eu.discovery import EURLexDiscovery
from legalize.fetcher.eu.parser import EURLexMetadataParser, EURLexTextParser, PendingStatus
from legalize.layout import layout_for, path_from_frontmatter
from legalize.models import ParsedNorm
from legalize.pipeline import commit_one, finalize_daily
from legalize.state.store import StateStore, resolve_dates_to_process
from legalize.storage import save_structured_json

logger = logging.getLogger(__name__)


def _published_file(repo: GitRepo, celex: str) -> str:
    """The act's file at HEAD, or "" when the corpus does not hold it."""
    # Same identifier rule as EURLexMetadataParser.parse: "/" becomes "-".
    front = {"identifier": celex.replace("/", "-"), "country": "eu"}
    return repo.read(path_from_frontmatter(front, layout_for("eu")))


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
    pushed = 0
    errors = []

    def fetch(norm_id: str, day: date) -> ParsedNorm | None:
        with EURLexClient.create(cc) as client:
            published = _published_file(repo, norm_id)
            metadata = client.get_metadata_sparql(norm_id)
            rows = metadata.get("results", {}).get("bindings", [])
            new = any(r.get("publicationDate", {}).get("value") == day.isoformat() for r in rows)
            if not (published or new or norm_id in state.pending):
                # An amendment or consolidation refreshes a published act; it does
                # not bootstrap one the pinned scope left out. REACH has no English
                # HTML original, and 32005R0396's 68 versions held the job past its
                # 55 minutes on five runs, 22-26 Oct 2026.
                logger.info("Skipping %s: changed on %s, not in the published corpus", norm_id, day)
                return None
            # A version the published file lists as unreadable stays out of its
            # history, and the record stays in its frontmatter (spec v0.5 §Coverage).
            gaps = _frontmatter_of(published.splitlines()).get("source_version_gaps")
            exclusions = {}
            if gaps and rows:
                reasons = {gap["date"]: gap["reason"] for gap in json.loads(gaps)}
                versions = client.get_consolidated_versions(norm_id)
                exclusions = {
                    v["celex"]: reasons[v["date"]] for v in versions if v["date"] in reasons
                }
                # As the rebuild decided it: with every consolidation excluded the
                # act is as enacted, and its amending acts are its versions.
                rows[0]["hasCons"] = {"value": str(len(versions) > len(exclusions)).lower()}
            client._merge_list_facts(norm_id, metadata)
            meta_data = json.dumps(metadata).encode("utf-8")
            data = client.get_text(
                norm_id, meta_data=meta_data, version_exclusions=exclusions or None
            )
            meta = meta_parser.parse(meta_data, norm_id)
            if gaps:
                meta = replace(meta, extra=meta.extra + (("source_version_gaps", gaps),))
            return ParsedNorm(
                metadata=meta,
                blocks=tuple(text_parser.parse_text(data)),
                reforms=tuple(text_parser.extract_reforms(data)),
            )

    with EURLexClient.create(cc) as client:
        # ponytail: rechecks only the in-force flag; an agreement repealed before it
        # ever entered into force would wait here for good. Add repealers if one does.
        facts = client.get_source_facts(sorted(state.pending)) if state.pending else {}
        due = [
            celex
            for celex in state.pending
            if any(
                v.get("value") in ("1", "true")
                for v in facts.get(celex, {}).get("resource_legal_in-force", [])
            )
        ]
        for current_date in dates:
            errors_before = len(errors)
            try:
                ids = list(discovery.discover_daily(client, current_date))
                ids += [celex for celex in due if celex not in ids]
                due = []
                if dry_run:
                    for norm_id in ids:
                        logger.info("Would refresh %s", norm_id)
                    continue
                with ThreadPoolExecutor(max_workers=cc.max_workers or 1) as pool:
                    futures = [
                        (norm_id, pool.submit(fetch, norm_id, current_date)) for norm_id in ids
                    ]
                    # Git writes stay serial and follow discovery order.
                    for norm_id, future in futures:
                        try:
                            norm = future.result()
                            if norm is None:
                                continue
                            save_structured_json(cc.data_dir, norm)
                            created += commit_one(config, "eu", norm.metadata.identifier)
                            state.pending.pop(norm_id, None)
                        except PendingStatus as exc:
                            # Not this run's failure and not publishable: held until
                            # EUR-Lex states the act in force, then fetched again.
                            logger.warning("Holding %s: %s", norm_id, exc)
                            state.pending[norm_id] = str(exc)
                        except Exception as exc:
                            logger.exception("Failed to refresh %s", norm_id)
                            errors.append(f"{norm_id}: {exc}")
                if len(errors) != errors_before:
                    break
                if not dry_run:
                    if config.git.push and created > pushed:
                        repo.push()
                        pushed = created
                    state.finish_day(current_date, errors)
                    state.save()
            except Exception as exc:
                logger.exception("Failed to complete %s", current_date)
                errors.append(f"{current_date}: {exc}")
                break
    return finalize_daily(
        repo,
        state,
        dates,
        created,
        errors,
        dry_run=dry_run,
        push=config.git.push and created > pushed,
    )
