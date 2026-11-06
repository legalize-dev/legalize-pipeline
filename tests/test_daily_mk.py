from datetime import date
from types import SimpleNamespace

from legalize.fetcher.mk import daily as daily_module
from legalize.fetcher.mk.client import LDBISClient
from legalize.fetcher.mk.discovery import LDBISDiscovery


def test_daily_commits_source_versions_without_synthetic_daily_reforms(monkeypatch):
    target = date(1993, 12, 27)
    cc = SimpleNamespace(state_path="state", repo_path="repo", source={})
    config = SimpleNamespace(
        get_country=lambda _: cc,
        git=SimpleNamespace(
            committer_name="Legalize", committer_email="legalize@legalize.dev", push=False
        ),
    )
    finished = []
    state = SimpleNamespace(
        load=lambda: None, finish_day=lambda current, errors: finished.append(current)
    )

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    client = FakeClient()
    discovered = SimpleNamespace(discover_daily=lambda current, day: ["3455"])
    fetched = []
    committed = []

    monkeypatch.setattr(daily_module, "StateStore", lambda _: state)
    monkeypatch.setattr(daily_module, "resolve_dates_to_process", lambda *args, **kwargs: [target])
    monkeypatch.setattr(daily_module, "GitRepo", lambda *args: object())
    monkeypatch.setattr(
        daily_module,
        "generic_fetch_one",
        lambda *args, **kwargs: (
            fetched.append((args, kwargs))
            or SimpleNamespace(metadata=SimpleNamespace(identifier="RM-1993-78-3455"))
        ),
    )
    monkeypatch.setattr(daily_module, "commit_one", lambda *args: committed.append(args) or 2)
    monkeypatch.setattr(
        daily_module, "finalize_daily", lambda repo, state, dates, count, errors, **kwargs: count
    )
    monkeypatch.setattr(LDBISClient, "create", classmethod(lambda cls, _: client))
    monkeypatch.setattr(LDBISDiscovery, "create", classmethod(lambda cls, _: discovered))

    assert daily_module.daily(config, target_date=target) == 2
    assert fetched == [((config, "mk", "3455"), {"force": True})]
    assert committed == [(config, "mk", "RM-1993-78-3455")]
    assert finished == [target]


def test_a_norm_saved_under_its_card_identifier_is_not_fetched_again(monkeypatch, tmp_path):
    # Discovery gives the numeric card id 30409, and the file is RM-2013-187-30409.json.
    from pathlib import Path

    from legalize import pipeline

    card = (Path(__file__).parent / "fixtures/mk/raw/RM-2013-187-30409.html").read_bytes()
    saved = tmp_path / "json" / "RM-2013-187-30409.json"
    saved.parent.mkdir()
    saved.write_text("{}", encoding="utf-8")
    cached = object()

    class FakeClient:
        discovery_id_field = LDBISClient.discovery_id_field

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get_metadata(self, norm_id):
            return card

        def get_text(self, norm_id, meta_data=None):
            raise AssertionError("a saved norm is not fetched again")

    monkeypatch.setattr(LDBISClient, "create", classmethod(lambda cls, _: FakeClient()))
    monkeypatch.setattr(
        pipeline, "load_norma_from_json", lambda path: cached if path == saved else None
    )
    config = SimpleNamespace(get_country=lambda _: SimpleNamespace(data_dir=str(tmp_path)))

    assert pipeline.generic_fetch_one(config, "mk", "30409") is cached
