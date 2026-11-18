"""An EU version older than the newest published one is refused, not appended.

CELLAR creates a consolidation weeks after the date it carries (02020D0472-20261009
appeared on 6 Nov 2026). Appended at the tip, it would put older text at HEAD and
break the file's oldest-first history (spec §History).
"""

from __future__ import annotations

import subprocess
from datetime import date

import pytest

from legalize.config import load_config
from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    ParsedNorm,
    Rank,
    Reform,
    Version,
)
from legalize.pipeline import HistoryMismatch, commit_one
from legalize.storage import save_structured_json

LAW = "32020R0001"


def _norm(days: list[date]) -> ParsedNorm:
    ids = [f"0{LAW[1:]}-{d:%Y%m%d}" for d in days]
    return ParsedNorm(
        metadata=NormMetadata(
            title="Regulation (EU) 2020/1",
            short_title="Regulation (EU) 2020/1",
            identifier=LAW,
            country="eu",
            rank=Rank("regulation"),
            publication_date=date(2020, 1, 1),
            status=NormStatus.IN_FORCE,
            department="Test",
            source="https://example.com/32020R0001",
        ),
        blocks=(
            Block(
                id="a1",
                block_type="precepto",
                title="Article 1",
                versions=tuple(
                    Version(
                        norm_id=source_id,
                        publication_date=day,
                        effective_date=day,
                        paragraphs=(Paragraph(css_class="parrafo", text=f"text of {day}"),),
                    )
                    for source_id, day in zip(ids, days, strict=True)
                ),
            ),
        ),
        reforms=tuple(
            Reform(date=day, norm_id=source_id, affected_blocks=("a1",))
            for source_id, day in zip(ids, days, strict=True)
        ),
    )


@pytest.fixture
def eu(tmp_path):
    data, repo = tmp_path / "data", tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    config = tmp_path / "config.yaml"
    config.write_text(f'countries:\n  eu:\n    repo_path: "{repo}"\n    data_dir: "{data}"\n')
    return load_config(str(config)), data, repo


def _head(repo) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout


def test_a_late_consolidation_before_the_newest_is_refused(eu):
    config, data, repo = eu
    save_structured_json(data, _norm([date(2020, 1, 1), date(2026, 10, 20)]))
    assert commit_one(config, "eu", LAW) == 2
    head = _head(repo)

    save_structured_json(data, _norm([date(2020, 1, 1), date(2026, 10, 9), date(2026, 10, 20)]))
    with pytest.raises(HistoryMismatch, match="02020R0001-20261009"):
        commit_one(config, "eu", LAW)
    assert _head(repo) == head


def test_a_newer_version_still_lands(eu):
    config, data, _ = eu
    save_structured_json(data, _norm([date(2020, 1, 1), date(2026, 10, 9)]))
    assert commit_one(config, "eu", LAW) == 2
    save_structured_json(data, _norm([date(2020, 1, 1), date(2026, 10, 9), date(2026, 11, 2)]))
    assert commit_one(config, "eu", LAW) == 1
