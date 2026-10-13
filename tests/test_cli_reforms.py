"""``legalize reforms`` — a law's history, read from the repo it lives in.

Built against a real git repo rather than a mock, because what is being tested
is a claim about git: that the ``Norm-Id`` trailer finds every commit for a law
without reading a single tree. On the Portuguese corpus that is 0.8 s against
73 minutes for ``git log --name-only``, and it keeps working when a law moves.
"""

from __future__ import annotations

import subprocess

import pytest
from click.testing import CliRunner

from legalize.cli import cli

BODY = (
    '---\ntitle: "t"\nidentifier: "{id}"\ncountry: "pt"\n{state}{amend}{refs}---\n\n# t\n\n{text}\n'
)


def _commit(repo, path, text, subject, law_id, source_id=None, state="", refs=""):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    # An as-enacted amendment leaves the body alone and moves the frontmatter,
    # which is the whole shape of that commit and what makes it a commit at all.
    amend = f'last_amendment: "{source_id}"\n' if source_id else ""
    (repo / path).write_text(BODY.format(id=law_id, state=state, text=text, amend=amend, refs=refs))
    trailers = f"\n\nNorm-Id: {law_id}"
    if source_id:
        trailers += f"\nDisposition: {source_id}\nSource-Id: {source_id}"
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", subject + trailers],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    return path


@pytest.fixture
def run(tmp_path, repo):
    config = tmp_path / "config.yaml"
    config.write_text(f'countries:\n  pt:\n    repo_path: "{repo}"\n    data_dir: "{tmp_path}/d"\n')

    def go(*args):
        return CliRunner().invoke(cli, ["--config", str(config), "reforms", "-c", "pt", *args])

    return go


def test_every_commit_carrying_the_trailer_is_listed(repo, run):
    _commit(repo, "pt/A-1.md", "v1", "[bootstrap] A", "A-1")
    _commit(repo, "pt/A-1.md", "v2", "[reform] A", "A-1", "AMEND-9")
    result = run("A-1")
    assert result.exit_code == 0
    assert "2 commit(s)" in result.output
    assert "AMEND-9" in result.output


def test_a_prefix_of_another_identifier_is_not_confused_with_it(repo, run):
    """`Norm-Id: A-1` must not answer for `A-10`, which is why the grep is
    anchored to the whole line."""
    _commit(repo, "pt/A-1.md", "v1", "[bootstrap] A", "A-1")
    _commit(repo, "pt/A-10.md", "v1", "[bootstrap] B", "A-10")
    assert "1 commit(s)" in run("A-1").output


def test_the_history_survives_the_file_moving(repo, run):
    """A path-based lookup loses the law at the rename; the trailer does not.
    Sharding a country's repo moves every file it has."""
    _commit(repo, "pt/A-1.md", "v1", "[bootstrap] A", "A-1")
    (repo / "pt" / "2020").mkdir(parents=True)
    subprocess.run(
        ["git", "mv", "pt/A-1.md", "pt/2020/A-1.md"], cwd=repo, check=True, capture_output=True
    )
    _commit(repo, "pt/2020/A-1.md", "v2", "[reform] A", "A-1")
    assert "2 commit(s)" in run("A-1").output


def test_an_as_enacted_law_says_its_body_does_not_change(repo, run):
    """97 % of the Portuguese corpus. Offering a text diff for these is offering
    something that is never there — the amending act is the whole story."""
    state = 'text_state: "as_enacted"\n'
    _commit(repo, "pt/A-1.md", "v1", "[bootstrap] A", "A-1", state=state)
    _commit(repo, "pt/A-1.md", "v1", "[reform] A", "A-1", "AMEND-9", state=state)
    out = run("A-1", "--diff").output
    assert "as_enacted" in out
    assert "body unchanged" in out


def test_a_consolidated_law_shows_what_the_text_did(repo, run):
    _commit(repo, "pt/A-1.md", "one line", "[bootstrap] A", "A-1")
    _commit(repo, "pt/A-1.md", "another line entirely", "[reform] A", "A-1")
    out = run("A-1", "--diff").output
    assert "point_in_time" in out
    assert "1 file changed" in out


def test_a_bootstrap_commit_is_never_called_unchanged(repo, run):
    """It is the commit that wrote the body, whatever the text state."""
    state = 'text_state: "as_enacted"\n'
    _commit(repo, "pt/A-1.md", "v1", "[bootstrap] A", "A-1", state=state)
    assert "body unchanged" not in run("A-1", "--diff").output


def test_a_commit_subject_cannot_be_swallowed_as_markup(repo, run):
    """Every subject starts with `[bootstrap]` or `[reform]`, which a console
    that reads markup takes for a style tag and drops."""
    _commit(repo, "pt/A-1.md", "v1", "[bootstrap] A", "A-1")
    assert "[bootstrap]" in run("A-1").output


def test_an_unknown_law_fails_rather_than_reporting_an_empty_history(repo, run):
    _commit(repo, "pt/A-1.md", "v1", "[bootstrap] A", "A-1")
    result = run("NOPE-1")
    assert result.exit_code == 1
    assert "NOPE-1" in result.output


# ── The other direction: what did this act change? ──


def test_an_act_lists_the_laws_it_amended(repo, run):
    _commit(repo, "pt/A-1.md", "v1", "[bootstrap] A", "A-1")
    _commit(repo, "pt/B-2.md", "v1", "[bootstrap] B", "B-2")
    _commit(repo, "pt/A-1.md", "v1", "[reform] A", "A-1", "ACT-7")
    _commit(repo, "pt/B-2.md", "v1", "[reform] B", "B-2", "ACT-7")

    out = run("ACT-7").output
    assert "Amends 2 law(s)" in out
    assert "A-1" in out and "B-2" in out


def test_an_act_outside_the_corpus_still_answers_for_what_it_changed(repo, run):
    # A type a country leaves out of scope amends laws that are in scope. The
    # act has no history of its own here, which is not the same as unknown.
    _commit(repo, "pt/A-1.md", "v1", "[bootstrap] A", "A-1")
    _commit(repo, "pt/A-1.md", "v1", "[reform] A", "A-1", "OUTSIDE-1")

    out = run("OUTSIDE-1").output
    assert "not published here" in out
    assert "Amends 1 law(s)" in out


def test_a_law_that_is_only_amended_reports_no_second_section(repo, run):
    _commit(repo, "pt/A-1.md", "v1", "[bootstrap] A", "A-1")
    _commit(repo, "pt/A-1.md", "v1", "[reform] A", "A-1", "ACT-7")

    assert "Amends" not in run("A-1").output


def test_a_law_the_source_never_consolidated_still_says_what_changed(repo, run):
    """The history is one bootstrap line; the answer is in the frontmatter.

    This is the whole non-consolidated corpus (#66): the body is the act as
    published, no amendment ever produces a second commit for it, so a history
    walk finds nothing to show. The publisher's own list of subsequent acts is
    in the file, and printing it is the difference between "1 commit" and the
    four acts that actually touched this law.
    """
    refs = (
        'references_subsequent: "SE MODIFICA [270] BOE-A-2012-7445: el art. 4 | '
        "SE DEROGA [210] BOE-A-2009-1: la disp. adic. 2 | "
        'SE DICTA EN RELACION [331] BOE-A-2020-7311: sobre suspension hasta 2020"\n'
    )
    _commit(
        repo,
        "pt/A-1.md",
        "v1",
        "[bootstrap] A",
        "A-1",
        state='text_state: "as_enacted"\n',
        refs=refs,
    )
    out = run("A-1").output
    assert "3 act(s) not in this history" in out
    assert "BOE-A-2012-7445" in out
    # The sentence, not just the id: a suspension is written nowhere else.
    assert "suspension" in out


def test_nothing_is_printed_when_the_source_records_nothing(repo, run):
    """An act nobody has touched must not grow an empty section."""
    _commit(repo, "pt/A-1.md", "v1", "[bootstrap] A", "A-1", state='text_state: "as_enacted"\n')
    assert "not in this history" not in run("A-1").output


def test_an_act_the_history_already_showed_is_not_repeated(repo, run):
    """A reform commit names its act; printing it again buries the ones the
    history could not show."""
    refs = 'references_subsequent: "SE MODIFICA [270] AMEND-9: el art. 4"\n'
    _commit(repo, "pt/A-1.md", "v1", "[bootstrap] A", "A-1")
    _commit(repo, "pt/A-1.md", "v2", "[reform] A", "A-1", "AMEND-9", refs=refs)
    assert "not in this history" not in run("A-1").output


def test_a_change_that_left_no_version_is_shown_on_a_consolidated_law(repo, run):
    """The suspensions gap, and the reason this is not gated on as_enacted.

    A Constitutional Court ruling changes what is in force and produces no
    version, so it appears in no commit and no diff. The source records it, and
    on a point-in-time law this is the only place it is visible.
    """
    refs = 'references_subsequent: "SE DECLARA [470] BOE-A-2024-27140: la inconstitucionalidad del art. 7"\n'
    _commit(repo, "pt/A-1.md", "v1", "[bootstrap] A", "A-1", refs=refs)
    out = run("A-1").output
    assert "1 act(s) not in this history" in out
    assert "BOE-A-2024-27140" in out
