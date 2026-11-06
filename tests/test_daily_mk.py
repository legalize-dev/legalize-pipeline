from datetime import date
from types import SimpleNamespace

from legalize.fetcher.mk import daily as daily_module
from legalize.fetcher.mk.client import LDBISClient
from legalize.fetcher.mk.discovery import LDBISDiscovery


def test_daily_commits_source_versions_without_synthetic_daily_reforms(monkeypatch):
    target = date(1993, 12, 27)
    cc = SimpleNamespace(state_path="state", repo_path="repo", data_dir="data", source={})
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

        def get_metadata(self, norm_id):
            return b""

    client = FakeClient()
    discovered = SimpleNamespace(discover_daily=lambda current, day: ["3455"])
    fetched = []
    committed = []

    monkeypatch.setattr(daily_module, "StateStore", lambda _: state)
    asked = {}
    monkeypatch.setattr(
        daily_module,
        "resolve_dates_to_process",
        lambda *args, **kwargs: asked.update(kwargs) or [target],
    )
    monkeypatch.setattr(daily_module, "_unchanged", lambda *args: False)
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
    assert asked["since"] is None
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


def test_an_amendment_commit_dates_last_updated_by_the_amendment(tmp_path):
    from dataclasses import replace
    from pathlib import Path

    import yaml

    from legalize.committer.git_ops import GitRepo
    from legalize.config import Config, CountryConfig
    from legalize.fetcher.mk.parser import LDBISMetadataParser
    from legalize.models import Block, Paragraph, ParsedNorm, Reform, Version
    from legalize.pipeline import commit_one
    from legalize.storage import save_structured_json

    card = Path(__file__).parent / "fixtures" / "mk" / "card.html"
    metadata = replace(
        LDBISMetadataParser().parse(card.read_bytes(), "RM-2012-98-25996"),
        identifier="RM-2012-98-25996",
        publication_date=date(2012, 8, 1),
    )
    version = Version("", date(2012, 8, 1), None, (Paragraph("parrafo", "Член 1"),))
    reforms = (
        Reform(date(2012, 8, 1), "RM-2012-98-25996", ()),
        Reform(date(2014, 6, 26), "RM-2014-97-32407", ()),
    )
    norm = ParsedNorm(metadata, (Block("body", "article", "", (version,)),), reforms)
    data, repo_path = tmp_path / "data", tmp_path / "repo"
    save_structured_json(data, norm)
    config = Config(countries={"mk": CountryConfig(data_dir=str(data), repo_path=str(repo_path))})

    assert commit_one(config, "mk", "RM-2012-98-25996") == 2

    repo = GitRepo(repo_path, "Legalize", "legalize@legalize.dev")
    law = next((repo_path / "mk").rglob("*.md")).relative_to(repo_path)

    def frontmatter(source_id):
        sha = repo._run(["log", "--format=%H", f"--grep=^Source-Id: {source_id}$"])
        return yaml.safe_load(repo._run(["show", f"{sha}:{law}"]).split("---")[1])

    # As enacted, last_updated is the latest amendment recorded (SPEC §text_state), and a law
    # with no amendment yet keeps its publication date.
    assert str(frontmatter("RM-2012-98-25996")["last_updated"]) == "2012-08-01"
    amended = frontmatter("RM-2014-97-32407")
    assert str(amended["last_updated"]) == "2014-06-26"
    assert amended["last_amendment"] == "RM-2014-97-32407"


def test_a_saved_record_is_fetched_again_only_when_its_card_changed(tmp_path):
    from dataclasses import replace
    from pathlib import Path

    from legalize.fetcher.mk.parser import LDBISMetadataParser
    from legalize.models import Block, NormStatus, Paragraph, ParsedNorm, Reform, Version
    from legalize.storage import save_structured_json

    raw = Path(__file__).parent / "fixtures" / "mk" / "raw"
    card = (raw / "RSM-2026-212-74875.html").read_bytes()
    client = LDBISClient()
    client.get_metadata = lambda norm_id: card
    metadata = LDBISMetadataParser().parse(card, "74875")
    reforms = tuple(client.get_reforms("74875", card))
    # What the text parser adds to the card's metadata is not a change of the card.
    saved = replace(
        metadata, extra=metadata.extra + (("text_source", "ocr"), ("amends", "RSM-2020-1-1"))
    )
    version = Version("", metadata.publication_date, None, (Paragraph("parrafo", "Член 1"),))
    blocks = (Block("body", "article", "", (version,)),)

    def save(norm_metadata, norm_reforms):
        save_structured_json(tmp_path, ParsedNorm(norm_metadata, blocks, norm_reforms))

    assert not daily_module._unchanged(client, str(tmp_path), "74875")
    save(saved, reforms)
    assert daily_module._unchanged(client, str(tmp_path), "74875")
    # A law whose card now links an amendment it did not have gains a reform to commit.
    save(saved, reforms[:1] + (Reform(date(2026, 9, 1), "RSM-2026-1-1", ()),))
    assert not daily_module._unchanged(client, str(tmp_path), "74875")
    save(replace(saved, status=NormStatus.REPEALED), reforms)
    assert not daily_module._unchanged(client, str(tmp_path), "74875")


def test_an_amending_act_names_the_law_it_amends(monkeypatch):
    from legalize.fetcher.mk import client as client_module

    def card(card_id, title, day, chain):
        return {
            "id": card_id,
            "title": title,
            "publication_date": day,
            "version": "",
            "gazette": "Службен весник на РМ",
            "issue": "1",
            "chain": chain,
        }

    law = "Закон за даночна постапка"
    cards = {
        # The 2013 amendment (30409) changes the 2005 law, not the 2020 law of the same title,
        # and a law of another name in the chain is not a candidate.
        "30409": card(
            "30409", f"Закон за изменување на Законот {law[6:]}", "27.12.2013", ["11057"]
        ),
        "11057": card("11057", law, "13.02.2005", ["30409", "90000", "99999"]),
        "90000": card("90000", law, "01.03.2020", []),
        "99999": card("99999", "Закон за царинска постапка", "01.01.2004", []),
        "3455": card("3455", law, "13.02.2005", []),
    }
    monkeypatch.setattr(client_module, "parse_card", lambda data, norm_id: cards[norm_id])
    client = LDBISClient()
    client.get_metadata = lambda norm_id: b""

    assert client.amended_law("30409", b"") == "RM-2005-1-11057"
    assert client.amended_law("3455", b"") == ""


def test_ocr_pages_are_yaml_lists_that_survive_the_saved_json(tmp_path):
    from dataclasses import replace
    from pathlib import Path

    import yaml

    from legalize.fetcher.mk.parser import LDBISMetadataParser
    from legalize.models import Block, Paragraph, ParsedNorm, Version
    from legalize.storage import load_norma_from_json, save_structured_json
    from legalize.transformer.frontmatter import render_frontmatter

    card = (Path(__file__).parent / "fixtures/mk/raw/RSM-2026-212-74875.html").read_bytes()
    metadata = LDBISMetadataParser().parse(card, "74875")
    metadata = replace(
        metadata,
        extra=metadata.extra + (("ocr_doubtful_pages", (2,)), ("ocr_unread_pages", (2, 103))),
    )
    version = Version("", metadata.publication_date, None, (Paragraph("parrafo", "Член 1"),))
    path = save_structured_json(
        tmp_path, ParsedNorm(metadata, (Block("body", "article", "", (version,)),), ())
    )
    loaded = load_norma_from_json(path).metadata

    assert loaded == metadata
    fields = yaml.safe_load(render_frontmatter(loaded, metadata.publication_date).split("---")[1])
    assert fields["ocr_doubtful_pages"] == [2]
    assert fields["ocr_unread_pages"] == [2, 103]


def test_the_mk_daily_takes_since_for_a_month_at_once(monkeypatch):
    from click.testing import CliRunner

    from legalize import cli as cli_module
    from legalize.config import Config

    called = {}

    def daily(config, target_date=None, dry_run=False, since=None):
        called["since"] = since
        return 0

    monkeypatch.setattr(daily_module, "daily", daily)
    monkeypatch.setattr(cli_module, "load_config", lambda *args, **kwargs: Config())

    result = CliRunner().invoke(cli_module.cli, ["daily", "-c", "mk", "--since", "2026-10-01"])

    assert result.exit_code == 0, result.output
    assert called["since"] == date(2026, 10, 1)
