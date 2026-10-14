"""Published Irish versions must remain a verified prefix of the current source history."""

import gc
import json
import subprocess
import threading
import weakref
from dataclasses import replace
from datetime import date

import pytest

from legalize import pipeline
from legalize.config import Config, CountryConfig
from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    ParsedNorm,
    Rank,
    Reform,
    TextState,
    Version,
)
from legalize.storage import save_structured_json
from legalize.transformer.slug import norm_to_filepath


def _norm(identifier="IE-2015-act-1"):
    published = date(2015, 1, 1)
    snapshot_date = date(2023, 1, 1)
    snapshot_id = f"revised-{identifier}@{snapshot_date}"
    metadata = NormMetadata(
        "Test Act — Éire",
        "Test Act — Éire",
        identifier,
        "ie",
        Rank("act"),
        published,
        NormStatus.IN_FORCE,
        "",
        "https://source.test/original",
    )
    original = Version(
        identifier,
        published,
        published,
        (Paragraph("parrafo", "Original source body"),),
        text_state=TextState.AS_ENACTED,
        source=metadata.source,
    )
    snapshot = Version(
        snapshot_id,
        published,
        snapshot_date,
        (Paragraph("parrafo", "Current consolidated body"),),
        text_state=TextState.CURRENT,
        source="https://source.test/current",
    )
    reforms = (
        Reform(published, identifier, ("full-text",), status=NormStatus.IN_FORCE),
        Reform(date(2020, 1, 1), "IE-2020-act-1", (), change_note="S. 2 substituted"),
        Reform(date(2022, 1, 1), "IE-2022-act-1", ()),
        Reform(snapshot_date, snapshot_id, ("full-text",), has_source_date=False),
    )
    return ParsedNorm(
        metadata, (Block("full-text", "document", "", (original, snapshot)),), reforms
    )


def _config(tmp_path):
    return Config(
        countries={
            "ie": CountryConfig(data_dir=str(tmp_path / "data"), repo_path=str(tmp_path / "repo"))
        }
    )


def _head(repo):
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True)


@pytest.mark.parametrize("committer", [pipeline.commit_one, pipeline.commit_all_fast])
@pytest.mark.parametrize(
    "change",
    ["date", "cutoff", "body", "source", "status", "note", "removed", "title", "warning", "extra"],
)
@pytest.mark.parametrize("new_event", [False, True])
def test_changed_published_version_is_rejected_before_any_new_commit(
    tmp_path, committer, change, new_event
):
    norm = _norm()
    config = _config(tmp_path)
    save_structured_json(tmp_path / "data", norm)
    assert pipeline.commit_all_fast(config, "ie") == 4
    previous_head = _head(tmp_path / "repo")
    path = tmp_path / "repo" / norm_to_filepath(norm.metadata)
    previous_tip = path.read_bytes()
    reforms = list(norm.reforms)
    versions = list(norm.blocks[0].versions)
    if change == "date":
        reforms[1] = replace(reforms[1], date=date(2021, 1, 1))
    elif change == "cutoff":
        versions[-1] = replace(versions[-1], effective_date=date(2023, 1, 2))
    elif change == "body":
        versions[0] = replace(
            versions[0], paragraphs=(Paragraph("parrafo", "Corrected original body"),)
        )
    elif change == "source":
        versions[0] = replace(versions[0], source="https://source.test/corrected-original")
    elif change == "status":
        reforms[0] = replace(reforms[0], status=NormStatus.PARTIALLY_REPEALED)
    elif change == "note":
        reforms[1] = replace(reforms[1], change_note="S. 3 substituted: corrected source scope")
    elif change == "removed":
        del reforms[1]
    elif change == "title":
        norm = replace(norm, metadata=replace(norm.metadata, title="Corrected canonical title"))
    elif change == "warning":
        versions[0] = replace(versions[0], source_warning="The original source is incomplete.")
    elif change == "extra":
        norm = replace(
            norm,
            metadata=replace(
                norm.metadata, extra=(("parliament_unclassified_field", "Do not ignore"),)
            ),
        )
    if new_event:
        reforms.append(Reform(date(2024, 1, 1), "IE-2024-act-1", ()))
    changed = replace(
        norm, blocks=(replace(norm.blocks[0], versions=tuple(versions)),), reforms=tuple(reforms)
    )
    save_structured_json(tmp_path / "data", changed)
    with pytest.raises(pipeline.HistoryMismatch, match="rebuild locally"):
        if committer is pipeline.commit_one:
            committer(config, "ie", norm.metadata.identifier)
        else:
            committer(config, "ie")
    assert _head(tmp_path / "repo") == previous_head
    assert path.read_bytes() == previous_tip


@pytest.mark.parametrize("committer", [pipeline.commit_one, pipeline.commit_all_fast])
@pytest.mark.parametrize("new_snapshot", [False, True])
def test_current_supplementary_metadata_does_not_rewrite_published_history(
    tmp_path, monkeypatch, committer, new_snapshot
):
    norm = _norm()
    norm = replace(
        norm,
        metadata=replace(norm.metadata, extra=(("parliament_metadata", '{"lastUpdated":"old"}'),)),
    )
    config = _config(tmp_path)
    save_structured_json(tmp_path / "data", norm)
    assert pipeline.commit_all_fast(config, "ie") == 4
    repo = tmp_path / "repo"
    before = subprocess.check_output(
        ["git", "-C", str(repo), "rev-list", "--reverse", "HEAD"], text=True
    ).splitlines()
    extra = {
        "parliament_metadata": '{"lastUpdated":"new"}',
        "parliament_title_en": "Supplementary title correction",
        "parliament_title_ga": "Supplementary title",
        "parliament_long_title_en": "Supplementary long title correction",
        "parliament_long_title_ga": "Supplementary long title",
        "parliament_date_signed": "2015-01-02",
        "oireachtas_uri": "https://parliament.test/new-catalogue-uri",
        "related_docs": "act, bill",
        "images_dropped": "1",
        "images_dropped_by_source": json.dumps({"https://source.test/new": 1}),
        "has_formulas": "true",
        "legislation_directory_notes": '[{"note":"Current editorial observation"}]',
        "legislation_directory_corrections": '[{"source_id":"IE-2024-act-1"}]',
    }
    metadata = replace(
        norm.metadata,
        extra=tuple(extra.items()),
        summary="Current parliamentary summary",
        pdf_url="https://parliament.test/verified-enacted.pdf",
    )
    versions = norm.blocks[0].versions
    reforms = norm.reforms
    if new_snapshot:
        day = date(2024, 1, 1)
        identifier = f"revised-{metadata.identifier}@{day}"
        versions += (
            Version(
                identifier,
                metadata.publication_date,
                day,
                (Paragraph("parrafo", "New official source body [image omitted]"),),
                text_state=TextState.CURRENT,
                source="https://source.test/new",
            ),
        )
        reforms += (Reform(day, identifier, ("full-text",), has_source_date=False),)
    updated = replace(
        norm,
        metadata=metadata,
        blocks=(replace(norm.blocks[0], versions=versions),),
        reforms=reforms,
    )
    save_structured_json(tmp_path / "data", updated)
    read_blob = pipeline._ie_read_history_blob
    readers = []

    def observed(process, object_id, identifier):
        readers.append(id(process))
        return read_blob(process, object_id, identifier)

    monkeypatch.setattr(pipeline, "_ie_read_history_blob", observed)
    if committer is pipeline.commit_one:
        assert committer(config, "ie", metadata.identifier) == int(new_snapshot)
    else:
        assert committer(config, "ie") == 4 + int(new_snapshot)
    assert len(readers) == 4 and len(set(readers)) == 1
    after = subprocess.check_output(
        ["git", "-C", str(repo), "rev-list", "--reverse", "HEAD"], text=True
    ).splitlines()
    assert after[:4] == before
    assert len(after) == len(before) + int(new_snapshot)
    tip = (repo / norm_to_filepath(metadata)).read_text()
    assert ("New official source body" in tip) is new_snapshot
    assert ("Current parliamentary summary" in tip) is new_snapshot


@pytest.mark.parametrize("committer", [pipeline.commit_one, pipeline.commit_all_fast])
def test_manual_head_change_to_supplementary_metadata_is_still_rejected(tmp_path, committer):
    norm = _norm()
    config = _config(tmp_path)
    save_structured_json(tmp_path / "data", norm)
    assert pipeline.commit_all_fast(config, "ie") == 4
    repo = tmp_path / "repo"
    path = repo / norm_to_filepath(norm.metadata)
    path.write_text(path.read_text().replace("---\n", '---\nimages_dropped: "999"\n', 1))
    subprocess.run(["git", "-C", str(repo), "add", str(path)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.test",
            "commit",
            "-qm",
            "Manual metadata change without a legislative event",
        ],
        check=True,
    )
    before = _head(repo)
    with pytest.raises(pipeline.HistoryMismatch, match="HEAD differs"):
        if committer is pipeline.commit_one:
            committer(config, "ie", norm.metadata.identifier)
        else:
            committer(config, "ie")
    assert _head(repo) == before


@pytest.mark.parametrize("committer", [pipeline.commit_one, pipeline.commit_all_fast])
def test_unchanged_sparse_history_uses_head_and_one_batch_per_norm(
    tmp_path, monkeypatch, committer
):
    norm = _norm()
    config = _config(tmp_path)
    # Both laws share affecting IDs; one norm ID is also a prefix of the other.
    for source in [norm, _norm("IE-2015-act-10")]:
        save_structured_json(tmp_path / "data", source)
    assert pipeline.commit_all_fast(config, "ie") == 8
    repo = tmp_path / "repo"
    before = _head(repo)
    subprocess.run(["git", "-C", str(repo), "sparse-checkout", "init", "--cone"], check=True)
    subprocess.run(["git", "-C", str(repo), "sparse-checkout", "set", "unrelated"], check=True)
    assert not (repo / norm_to_filepath(norm.metadata)).exists()
    run = subprocess.run
    calls = []

    def observed(args, **kwargs):
        calls.append(args)
        return run(args, **kwargs)

    monkeypatch.setattr(pipeline.subprocess, "run", observed)
    if committer is pipeline.commit_one:
        assert committer(config, "ie", norm.metadata.identifier) == 0
        expected_batches = 1
    else:
        assert committer(config, "ie") == 8
        expected_batches = 2
    assert sum("cat-file" in args for args in calls) == expected_batches
    assert sum("log" in args for args in calls) == 1
    assert not any("show" in args for args in calls)
    assert _head(repo) == before
    assert not (repo / norm_to_filepath(norm.metadata)).exists()


def test_parallel_fetch_releases_consumed_large_results(tmp_path, monkeypatch):
    class Payload:
        pass

    unblock = threading.Event()
    references = []
    retained = []
    identifiers = [str(index) for index in range(52)]
    config = Config(countries={"ie": CountryConfig(data_dir=str(tmp_path), max_workers=2)})
    monkeypatch.setattr(pipeline, "discover_norm_ids", lambda *args, **kwargs: identifiers)
    monkeypatch.setattr(pipeline, "overwritten_identifiers", lambda: ())

    def fetch(config, country, identifier, force=False):
        if int(identifier) >= 50:
            assert unblock.wait(5)
        result = Payload()
        if int(identifier) < 50:
            references.append(weakref.ref(result))
        return result

    def progress(message="", *args, **kwargs):
        if "[50/52]" in str(message):
            gc.collect()
            retained.append(sum(reference() is not None for reference in references))
            unblock.set()

    monkeypatch.setattr(pipeline, "generic_fetch_one", fetch)
    monkeypatch.setattr(pipeline.console, "print", progress)
    assert sorted(pipeline.generic_fetch_all(config, "ie"), key=int) == identifiers
    # The current loop variables may retain the last result, but the previous
    # fifty complete laws must not all stay attached to completed futures.
    assert retained and retained[0] <= 2


def test_same_day_activations_survive_incremental_and_fast_history(tmp_path):
    norm = _norm()
    day = date(2023, 1, 1)
    # Two already published partial repeals commence together. Both events must
    # survive even though the second changes no body, status or frontmatter.
    activations = tuple(
        Reform(
            day,
            f"effective-{identifier}@{day}",
            (),
            has_source_date=False,
            status=NormStatus.PARTIALLY_REPEALED,
        )
        for identifier in ("IE-2020-act-1", "IE-2022-act-1")
    )
    norm = replace(
        norm,
        blocks=(replace(norm.blocks[0], versions=norm.blocks[0].versions[:1]),),
        reforms=norm.reforms[:-1] + activations,
    )
    expected = [reform.norm_id for reform in norm.reforms]
    histories = []
    for mode in ("incremental", "fast"):
        root = tmp_path / mode
        config = _config(root)
        repo = root / "repo"

        def commit(mode=mode, config=config):
            if mode == "incremental":
                return pipeline.commit_one(config, "ie", norm.metadata.identifier)
            return pipeline.commit_all_fast(config, "ie")

        def history(repo=repo):
            messages = subprocess.check_output(
                ["git", "-C", str(repo), "log", "--reverse", "--format=%B"], text=True
            )
            return [
                line.removeprefix("Source-Id: ")
                for line in messages.splitlines()
                if line.startswith("Source-Id: ")
            ]

        save_structured_json(root / "data", norm)
        assert commit() == 5
        assert history() == expected
        # The final two events intentionally reference exactly the same tree.
        trees = subprocess.check_output(
            ["git", "-C", str(repo), "log", "-2", "--format=%T"], text=True
        ).splitlines()
        assert trees[0] == trees[1]
        previous_head = _head(repo)
        commit()
        assert _head(repo) == previous_head
        later = replace(
            norm,
            reforms=norm.reforms
            + (
                Reform(date(2024, 1, 1), "IE-2024-act-1", (), status=NormStatus.PARTIALLY_REPEALED),
            ),
        )
        save_structured_json(root / "data", later)
        commit()
        assert history() == expected + ["IE-2024-act-1"]
        previous_head = _head(repo)
        commit()
        assert _head(repo) == previous_head
        histories.append(history())
    assert histories[0] == histories[1]


@pytest.mark.parametrize("dry_run", [False, True])
def test_fast_import_rejects_older_detached_head_without_duplicating_events(tmp_path, dry_run):
    config = _config(tmp_path)
    norm = _norm()
    save_structured_json(tmp_path / "data", norm)
    assert pipeline.commit_all_fast(config, "ie") == 4
    repo = tmp_path / "repo"
    original_main = _head(repo)
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "--detach", "HEAD~1"],
        check=True,
        capture_output=True,
    )
    detached_head = _head(repo)
    before_file = (repo / norm_to_filepath(norm.metadata)).read_bytes()
    # The importer writes main even when an unrelated configured branch differs.
    config.git.branch = "another-configured-branch"
    with pytest.raises(pipeline.HistoryMismatch, match="HEAD differs from refs/heads/main"):
        pipeline.commit_all_fast(config, "ie", dry_run=dry_run)
    assert _head(repo) == detached_head
    assert (
        subprocess.check_output(["git", "-C", str(repo), "rev-parse", "refs/heads/main"], text=True)
        == original_main
    )
    messages = subprocess.check_output(
        ["git", "-C", str(repo), "log", "refs/heads/main", "--format=%B"], text=True
    )
    sources = [line for line in messages.splitlines() if line.startswith("Source-Id: ")]
    assert len(sources) == len(set(sources)) == 4
    assert (repo / norm_to_filepath(norm.metadata)).read_bytes() == before_file
