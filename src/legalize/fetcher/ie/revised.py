"""Post-bootstrap pass: apply Revised Acts consolidated versions.

After the initial bootstrap (enacted text), this module fetches
consolidated text from revisedacts.lawreform.ie for the ~560 acts
that have revised versions, and creates a second commit per law
with the updated text.

Uses the standard GitRepo + build_commit_info infrastructure for
commit creation, ensuring consistent commit format, proper trailers,
and idempotency via Source-Id checks.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from rich.console import Console

from legalize.committer.git_ops import GitRepo
from legalize.committer.message import build_commit_info
from legalize.config import Config
from legalize.fetcher.ie.client import ISBClient
from legalize.fetcher.ie.parser import ISBMetadataParser, parse_revised_html
from legalize.models import Block, CommitType, Reform, Version
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath

logger = logging.getLogger(__name__)
console = Console()


def apply_revised_acts(
    config: Config,
    *,
    dry_run: bool = False,
    limit: int | None = None,
) -> int:
    """Fetch and apply Revised Acts versions to the Ireland repo.

    For each norm in the repo, checks if a Revised Acts version exists.
    If it does, renders the consolidated text through the standard
    pipeline (render_norm_at_date) and creates a REFORM commit via
    GitRepo + build_commit_info.

    Safe to re-run: a norm whose consolidated text has not moved renders
    byte-identical markdown, write_and_add reports no change, and no commit
    is made.

    Returns the number of commits created.
    """
    cc = config.get_country("ie")
    repo_path = Path(cc.repo_path)

    if not repo_path.exists():
        console.print("[red]Repo not found. Run bootstrap first.[/red]")
        return 0

    console.print("[bold]Revised Acts — applying consolidated versions[/bold]\n")

    # Standard committer infrastructure
    repo = GitRepo(repo_path, config.git.committer_name, config.git.committer_email)

    metadata_parser = ISBMetadataParser()

    commits_created = 0
    revised_found = 0
    skipped_unchanged = 0
    errors = 0

    with ISBClient.create(cc) as client:
        # Discover which acts have revised versions by scraping the listing
        norm_ids = _discover_revised_ids(client)
        console.print(f"  {len(norm_ids)} acts with revised versions found\n")
        for i, norm_id in enumerate(norm_ids):
            if limit and revised_found >= limit:
                break

            # A distinct prefix so Source-Id != Norm-Id. It carries no date:
            # the DB's reform key is (law_id, source_id, date), so successive
            # consolidations of one act are already distinct rows, and a
            # stable Source-Id is what the history-fix script can reproduce.
            source_id = f"revised-{norm_id}"

            # Try to fetch revised text
            try:
                revised_data = client.get_revised_text(norm_id)
            except Exception as e:
                logger.debug("Error fetching revised %s: %s", norm_id, e)
                errors += 1
                continue

            if revised_data is None:
                continue  # No revised version (404)

            revised_found += 1

            # Parse revised HTML
            paragraphs, updated_to = parse_revised_html(revised_data)
            if not paragraphs:
                logger.warning("No paragraphs from revised %s", norm_id)
                continue

            if updated_to is None:
                updated_to = date.today()

            # Fetch metadata for this norm (needed for proper commit message)
            try:
                meta_data = client.get_metadata(norm_id)
                metadata = metadata_parser.parse(meta_data, norm_id)
            except Exception:
                logger.debug("Could not fetch metadata for %s, using fallback", norm_id)
                metadata = metadata_parser._fallback_metadata(norm_id)

            # Build Block/Version from revised paragraphs
            block = Block(
                id="full-text",
                block_type="document",
                title="",
                versions=(
                    Version(
                        norm_id=norm_id,
                        publication_date=updated_to,
                        effective_date=updated_to,
                        paragraphs=tuple(paragraphs),
                    ),
                ),
            )
            blocks = [block]

            # Render to full markdown with frontmatter via standard pipeline
            file_path = norm_to_filepath(metadata)
            markdown = render_norm_at_date(metadata, blocks, updated_to, include_all=True)

            if dry_run:
                console.print(f"  [yellow]DRY-RUN[/yellow] {norm_id} → revised {updated_to}")
                commits_created += 1
                continue

            # Write and stage. This is the idempotency check: write_and_add
            # returns False when the rendered markdown is byte-identical to
            # what is already committed, which is what makes the pass
            # re-runnable — a skip keyed on Source-Id alone would apply the
            # first consolidation and then never see a later one.
            changed = repo.write_and_add(file_path, markdown)
            if not changed:
                skipped_unchanged += 1
                continue

            # Create reform and commit via standard infrastructure
            reform = Reform(
                date=updated_to,
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

            if (revised_found % 50) == 0:
                console.print(
                    f"  [{i + 1}/{len(norm_ids)}] {revised_found} revised, "
                    f"{commits_created} commits"
                )

    console.print(
        f"\n[bold green]✓ Revised Acts complete[/bold green]\n"
        f"  {revised_found} revised versions found\n"
        f"  {commits_created} commits created\n"
        f"  {skipped_unchanged} skipped (text unchanged)\n"
        f"  {errors} errors"
    )
    return commits_created


def _discover_revised_ids(client: ISBClient) -> list[str]:
    """Scrape the Revised Acts chronological listing to find all act IDs.

    Much faster than probing 4,000+ norms individually (~1 request
    vs ~4,000 requests).
    """
    import re

    url = "https://revisedacts.lawreform.ie/revacts/chron"
    try:
        data = client._get(url)
    except Exception:
        logger.warning("Could not fetch Revised Acts listing")
        return []

    html_text = data.decode("utf-8", errors="replace")

    # Extract act URLs: /eli/{year}/act/{number}/front/revised
    acts = re.findall(r"/eli/(\d{4})/act/(\d+)/front/revised", html_text)

    norm_ids = sorted({f"IE-{year}-act-{num}" for year, num in acts})
    return norm_ids
