"""A second act must not be written over the law that already holds the file name.

Portugal publishes the two séries of the Diário da República with independent
numbering, so "Portaria n.º 953/2008" is both a hunting concession (Série I) and a
table of insurance fees (Série II). They resolved to one identifier, and since the
identifier is also the file name, the daily would replace a published law with an
unrelated act and commit it as if it were a reform of that law.

The bootstrap side of this is handled where the JSON is written
(``storage._disambiguated``); this is the other door, the one every country's
daily goes through.
"""

from __future__ import annotations

import pytest

from legalize.committer.git_ops import GitRepo
from legalize.pipeline import ShadowedLaw, finalize_daily
from legalize.state.store import StateStore

FIRST = """---
title: "Portaria n.º 953/2008"
identifier: "DRE-PORT-953-2008"
publication_date: "2008-08-25"
---
# Concessiona a zona de caça turística
"""

SECOND = """---
title: "Portaria n.º 953/2008"
identifier: "DRE-PORT-953-2008"
publication_date: "2008-12-16"
---
# Valor de taxas a favor do Instituto de Seguros
"""

AMENDED_FIRST = FIRST.replace("caça turística", "caça turística, alterada")


def _repo(tmp_path) -> GitRepo:
    repo = GitRepo(tmp_path / "repo", "Legalize", "bot@legalize.dev")
    repo.init()
    return repo


def test_another_act_does_not_replace_the_published_law(tmp_path, caplog):
    repo = _repo(tmp_path)
    path = "pt/DRE-PORT-953-2008.md"
    assert repo.write_and_add(path, FIRST) is True

    assert repo.write_and_add(path, SECOND) is False
    assert (tmp_path / "repo" / path).read_text(encoding="utf-8") == FIRST
    assert "same identifier" in caplog.text


def test_a_new_version_of_the_same_law_still_lands(tmp_path):
    repo = _repo(tmp_path)
    path = "pt/DRE-PORT-953-2008.md"
    repo.write_and_add(path, FIRST)

    assert repo.write_and_add(path, AMENDED_FIRST) is True
    assert (tmp_path / "repo" / path).read_text(encoding="utf-8") == AMENDED_FIRST


def test_a_file_without_a_publication_date_is_left_alone(tmp_path):
    """READMEs, FUNDING.yml and any country that does not write the field."""
    repo = _repo(tmp_path)
    repo.write_and_add("README.md", "# one\n")

    assert repo.write_and_add("README.md", "# two\n") is True
    assert (tmp_path / "repo" / "README.md").read_text(encoding="utf-8") == "# two\n"


def test_a_refused_act_ends_the_run_red(tmp_path):
    """Everything publishable is committed and pushed first — then it fails.

    A law that exists and cannot be written is a defect in the country's
    identifier rule. Left as a log line it survives for months; as a red run it
    gets fixed.
    """
    repo = _repo(tmp_path)
    path = "pt/DRE-PORT-953-2008.md"
    repo.write_and_add(path, FIRST)
    repo.write_and_add(path, SECOND)

    state = StateStore(tmp_path / "state.json")
    errors: list[str] = []
    with pytest.raises(ShadowedLaw, match="already holds"):
        finalize_daily(repo, state, [], 0, errors, dry_run=True)

    # The refusal is in the run record too, not only in the exception.
    assert any("another act already holds" in e for e in errors)


def test_a_clean_run_does_not_raise(tmp_path):
    repo = _repo(tmp_path)
    repo.write_and_add("pt/DRE-PORT-953-2008.md", FIRST)

    state = StateStore(tmp_path / "state.json")
    assert finalize_daily(repo, state, [], 1, [], dry_run=True) == 1


def test_the_commit_index_is_returned_not_just_stored(tmp_path):
    """``load_existing_commits`` reads as a getter, so it has to behave like one.

    It returned None while storing the pairs on the instance. The one caller that
    asked ``if pair in repo.load_existing_commits()`` — the path that records what
    an act changed — raised TypeError into a broad except and logged "Error
    recording amendment on …" once per law. The daily stayed green: the laws of
    the day were committed, the reforms of the laws they amended were not.
    """
    from datetime import date as _date

    from legalize.models import CommitInfo, CommitType

    repo = _repo(tmp_path)
    assert repo.load_existing_commits() == set()

    target = "pt/DRE-PORT-953-2008.md"
    repo.write_and_add(target, FIRST)
    repo.commit(
        CommitInfo(
            commit_type=CommitType.REFORM,
            subject="[reform] Concessiona a zona de caça",
            body="",
            trailers={"Source-Id": "DRE-SRC-1", "Norm-Id": "DRE-PORT-953-2008"},
            author_name="Legalize",
            author_email="bot@legalize.dev",
            author_date=_date(2008, 8, 25),
            file_path=target,
            content=FIRST,
        )
    )
    assert ("DRE-SRC-1", "DRE-PORT-953-2008") in repo.load_existing_commits()
    assert repo.has_commit_with_source_id("DRE-SRC-1", "DRE-PORT-953-2008")
