"""A sparse checkout hides most of the corpus, and the daily has to write into it.

CI clones each country repo to run the daily. Materialising Portugal's working
tree — 171,722 files — took 48 minutes of the job's 55-minute budget, while the
pipeline itself ran in 7 seconds. A sparse checkout brings that to seconds, but
it changes what the committer sees: outside the cone a law is absent from disk,
so ``git add`` refuses it and the unchanged-content check reads nothing and
re-commits an identical file every morning.
"""

from __future__ import annotations

import subprocess

from legalize.committer.git_ops import GitRepo

LAW = """---
title: "Lei n.º 1/2026"
identifier: "DRE-2026-1-1"
publication_date: "2026-01-02"
---
# Uma lei
"""

OTHER = LAW.replace("1/2026", "2/2026").replace("DRE-2026-1-1", "DRE-2026-2-2")


def _git(path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=path, capture_output=True, text=True, check=True
    ).stdout.strip()


def _origin_with_two_years(tmp_path):
    """A repo holding one law in 2025 and one in 2026, as the corpus is laid out."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _git(origin, "config", "user.name", "t")
    _git(origin, "config", "user.email", "t@t")
    for year, body in (("2025", LAW), ("2026", OTHER)):
        law_dir = origin / "pt" / year
        law_dir.mkdir(parents=True)
        (law_dir / "law.md").write_text(body, encoding="utf-8")
    (origin / "README.md").write_text("# legalize-pt\n", encoding="utf-8")
    _git(origin, "add", ".")
    _git(origin, "commit", "-q", "-m", "[bootstrap] Init")
    return origin


def _sparse_clone(tmp_path, origin):
    """What CI does: clone with only the root files on disk."""
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", "--sparse", f"file://{origin}", str(clone)],
        check=True,
        capture_output=True,
    )
    _git(clone, "config", "user.name", "t")
    _git(clone, "config", "user.email", "t@t")
    return clone


def test_a_law_lands_in_a_directory_the_checkout_was_hiding(tmp_path):
    clone = _sparse_clone(tmp_path, _origin_with_two_years(tmp_path))
    assert not (clone / "pt" / "2026" / "law.md").exists()  # the cone is root-only

    repo = GitRepo(clone, "Legalize", "bot@legalize.dev")
    assert repo.write_and_add("pt/2026/nueva.md", LAW) is True
    _git(clone, "commit", "-q", "-m", "[new] Uma lei")

    committed = _git(clone, "ls-tree", "-r", "--name-only", "HEAD").split("\n")
    assert "pt/2026/nueva.md" in committed
    # and the law the cone was hiding is still in the tree, not deleted by it
    assert "pt/2025/law.md" in committed


def test_the_unchanged_check_survives_the_cone(tmp_path):
    """Writing the same law twice must stage nothing the second time.

    Outside the cone the file is not on disk, so a committer that only looks at
    the working tree calls every write new — one identical commit per law per
    run, forever.
    """
    clone = _sparse_clone(tmp_path, _origin_with_two_years(tmp_path))
    repo = GitRepo(clone, "Legalize", "bot@legalize.dev")

    assert repo.write_and_add("pt/2025/law.md", LAW) is False  # same content as origin
    assert repo.write_and_add("pt/2025/law.md", OTHER.replace("2/2026", "1/2025")) is True


def test_a_full_checkout_is_untouched(tmp_path):
    """No sparse-checkout file, no cone calls: the normal path stays the normal path."""
    origin = _origin_with_two_years(tmp_path)
    clone = tmp_path / "full"
    subprocess.run(
        ["git", "clone", "-q", f"file://{origin}", str(clone)], check=True, capture_output=True
    )
    _git(clone, "config", "user.name", "t")
    _git(clone, "config", "user.email", "t@t")

    repo = GitRepo(clone, "Legalize", "bot@legalize.dev")
    assert repo.write_and_add("pt/2025/law.md", LAW) is False
    assert repo.write_and_add("pt/2026/otra.md", OTHER) is True
