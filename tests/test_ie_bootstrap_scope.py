"""The Irish bootstrap commits only its verified dependency closure."""

import gc
import subprocess
import threading
import weakref
from datetime import date
from types import SimpleNamespace

import pytest

from legalize.config import Config, CountryConfig
from legalize.fetcher.ie import bootstrap
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
from legalize.pipeline import NothingPublished, commit_all_fast
from legalize.storage import save_structured_json


def _norm(identifier, references=()):
    published = date(int(identifier.split("-")[1]), 1, 1)
    metadata = NormMetadata(
        identifier,
        identifier,
        identifier,
        "ie",
        Rank("act"),
        published,
        NormStatus.IN_FORCE,
        "",
        f"https://source.test/{identifier}",
    )
    version = Version(
        identifier,
        published,
        published,
        (Paragraph("parrafo", identifier),),
        TextState.AS_ENACTED,
        metadata.source,
    )
    reforms = (Reform(published, identifier, ("full-text",)),) + tuple(
        Reform(date(int(reference.split("-")[1]), 1, 1), reference, ()) for reference in references
    )
    return ParsedNorm(metadata, (Block("full-text", "document", "", (version,)),), reforms)


@pytest.mark.parametrize("dry_run", [False, True])
def test_bootstrap_limits_commits_to_requested_law_and_transitive_dependencies(
    tmp_path, monkeypatch, dry_run
):
    base, dependency, transitive = "IE-2020-act-20", "IE-2021-si-10", "IE-2022-act-4"
    unrelated = _norm("IE-2010-act-1")
    norms = {
        base: _norm(base, [dependency]),
        dependency: _norm(dependency, [transitive]),
        transitive: _norm(transitive),
    }
    data, repo = tmp_path / "data", tmp_path / "repo"
    config = Config(
        countries={"ie": CountryConfig(data_dir=str(data), repo_path=str(repo), max_workers=2)}
    )
    unrelated_path = save_structured_json(data, unrelated)
    original_cache = unrelated_path.read_bytes()
    calls = []

    def fetch_all(config, country, limit=None):
        assert limit == 1
        save_structured_json(data, norms[base])
        return [base]

    def fetch_one(config, country, identifier):
        calls.append(identifier)
        save_structured_json(data, norms[identifier])
        return norms[identifier]

    monkeypatch.setattr(bootstrap, "discover_norm_ids", lambda *args, **kwargs: [base])
    monkeypatch.setattr(bootstrap, "generic_fetch_all", fetch_all)
    monkeypatch.setattr(bootstrap, "generic_fetch_one", fetch_one)
    assert bootstrap.bootstrap(config, dry_run=dry_run, limit=1) == 5
    assert calls == [dependency, transitive]
    assert unrelated_path.read_bytes() == original_cache
    assert config.get_country("ie").data_dir == str(data)
    if dry_run:
        assert not (repo / ".git").exists()
    else:
        assert {path.stem for path in (repo / "ie").rglob("*.md")} == set(norms)
        history = subprocess.check_output(
            ["git", "-C", str(repo), "log", "--reverse", "--format=%B"], text=True
        )
        assert f"Norm-Id: {unrelated.metadata.identifier}" not in history
        assert history.count("Source-Id:") == 5
        dates = [
            line.split(": ", 1)[1]
            for line in history.splitlines()
            if line.startswith("Source-Date:")
        ]
        assert dates == sorted(dates)


@pytest.mark.parametrize("existing_cache", [False, True])
def test_selected_missing_json_fails_before_writing_any_law(tmp_path, existing_cache):
    data, repo = tmp_path / "data", tmp_path / "repo"
    config = Config(countries={"ie": CountryConfig(data_dir=str(data), repo_path=str(repo))})
    if existing_cache:
        save_structured_json(data, _norm("IE-2020-act-1"))
    with pytest.raises(NothingPublished, match="selected norms have no structured data"):
        commit_all_fast(config, "ie", norm_ids={"IE-2020-act-1", "IE-2021-si-10"})
    assert not (repo / ".git").exists()


def test_dependency_wave_does_not_retain_all_complete_norms(tmp_path, monkeypatch):
    class Payload:
        pass

    root = "IE-2020-act-1"
    dependencies = [f"IE-2021-si-{number:03}" for number in range(52)]
    references = []
    retained = []
    blocked = 0
    lock = threading.Lock()
    ready, release = threading.Event(), threading.Event()
    config = Config(countries={"ie": CountryConfig(data_dir=str(tmp_path), max_workers=2)})

    def load(path):
        return SimpleNamespace(
            reforms=tuple(Reform(date(2021, 1, 1), key, ()) for key in dependencies)
            if path.stem == root
            else ()
        )

    def fetch(config, country, identifier):
        nonlocal blocked
        if identifier in dependencies[-2:]:
            with lock:
                blocked += 1
                if blocked == 2:
                    ready.set()
            assert release.wait(5)
        result = Payload()
        if identifier not in dependencies[-2:]:
            references.append(weakref.ref(result))
        return result

    def observe():
        try:
            assert ready.wait(5)
            gc.collect()
            retained.append(sum(reference() is not None for reference in references))
        finally:
            release.set()

    monkeypatch.setattr(bootstrap, "load_norma_from_json", load)
    monkeypatch.setattr(bootstrap, "generic_fetch_one", fetch)
    observer = threading.Thread(target=observe)
    observer.start()
    try:
        assert bootstrap.fetch_dependencies(config, [root]) == sorted([root, *dependencies])
    finally:
        release.set()
        observer.join(timeout=5)
    assert len(references) == 50
    assert retained == [0]


@pytest.mark.parametrize("dry_run", [False, True])
def test_selected_invalid_json_fails_before_writing_preceding_valid_law(tmp_path, dry_run):
    data, repo = tmp_path / "data", tmp_path / "repo"
    config = Config(countries={"ie": CountryConfig(data_dir=str(data), repo_path=str(repo))})
    valid, invalid = "IE-2020-act-1", "IE-2021-si-10"
    save_structured_json(data, _norm(valid))
    invalid_path = data / "json" / f"{invalid}.json"
    invalid_path.write_text("{invalid")
    with pytest.raises(NothingPublished, match="selected norm cannot be loaded") as raised:
        commit_all_fast(config, "ie", norm_ids={valid, invalid}, dry_run=dry_run)
    assert str(invalid_path) in str(raised.value)
    assert not repo.exists()
