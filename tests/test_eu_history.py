"""Source versions survive fetch, storage, rendering, commits and a rerun."""

import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path

import pytest
import yaml

from legalize.config import Config, CountryConfig
from legalize.fetcher.eu.client import EURLexClient
from legalize.fetcher.eu.parser import EURLexMetadataParser, EURLexTextParser
from legalize.fetcher.eu.parser_pdf import UnsupportedPDF, parse_pdf
from legalize.models import ParsedNorm
from legalize.pipeline import commit_all_fast, commit_one
from legalize.storage import save_structured_json
from legalize.transformer.markdown import render_paragraphs

FIXTURES = Path(__file__).parent / "fixtures" / "eu"
# What a daily reads back for an act the corpus already holds.
PUBLISHED = '---\nidentifier: "32016R0679"\n---\nBody\n'


def test_amending_act_is_not_repeated_for_a_later_journal_correction(monkeypatch):
    metadata = json.dumps(
        {
            "results": {
                "bindings": [
                    {
                        "publicationDate": {"value": "1968-03-04"},
                        "amendments": {
                            "value": json.dumps(
                                [
                                    {"celex": "32006R1066", "date": "2007-03-16"},
                                    {"celex": "32006R1066", "date": "2006-07-14"},
                                ]
                            )
                        },
                    }
                ]
            }
        }
    ).encode()
    with EURLexClient() as client:
        monkeypatch.setattr(client, "get_consolidated_versions", lambda _: [])
        monkeypatch.setattr(client, "get_html_manifest_uri", lambda _: "original")
        monkeypatch.setattr(
            client, "download_xhtml", lambda _: b"<html><body><p>Original body</p></body></html>"
        )
        reforms = EURLexTextParser().extract_reforms(client.get_text("31968R0259", metadata))
    assert [(r.norm_id, r.date) for r in reforms] == [
        ("31968R0259", date(1968, 3, 4)),
        ("32006R1066", date(2006, 7, 14)),
    ]


def test_frozen_source_resume_preserves_provenance_and_rejects_changed_bytes(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    from scripts.fetch_eu_reprocess import snapshot

    celex = "32016R0679"
    source = b"<html><body>Original source</body></html>"
    uri = "https://publications.europa.eu/resource/cellar/frozen-manifest"
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources" / f"{celex}.xhtml").write_bytes(source)
    (tmp_path / "inventory.json").write_text(json.dumps({"laws": [celex]}))
    (tmp_path / "versions.json").write_text(json.dumps({celex: []}))
    checkpoint = tmp_path / "downloads.json"
    checkpoint.write_text(
        json.dumps({celex: {"url": uri, "sha256": hashlib.sha256(source).hexdigest()}})
    )
    snapshot(tmp_path, tmp_path, 1, html_only=True)
    assert json.loads(checkpoint.read_text())[celex]["url"] == uri
    (tmp_path / "sources" / f"{celex}.xhtml").write_bytes(source + b"changed")
    with pytest.raises(RuntimeError, match="sources unavailable"):
        snapshot(tmp_path, tmp_path, 1, html_only=True)
    assert "frozen checksum" in json.loads(checkpoint.read_text())[celex]["error"]
    with pytest.raises(RuntimeError, match="sources unavailable"):
        snapshot(tmp_path, tmp_path, 1, html_only=True)


@pytest.mark.parametrize("committer", [commit_one, commit_all_fast])
def test_future_commencement_keeps_actual_source_publication(tmp_path, monkeypatch, committer):
    celex = "32026R2205"
    facts = {
        "date_annotations": [
            {"date": {"value": "2099-10-09"}, "typeOfDate": {"value": "{EV|authority}"}}
        ]
    }
    row = {
        "celex": {"value": celex},
        "title": {"value": "Regulation (EU) 2026/2205"},
        "publicationDate": {"value": "2026-10-06"},
        "force": {"value": "0"},
        "hasCons": {"value": "false"},
        "endValidity": {"value": "9999-12-31"},
        "rtype": {
            "value": "http://publications.europa.eu/resource/authority/resource-type/REG_IMPL"
        },
        "sourceFacts": {"value": json.dumps(facts)},
    }
    metadata_data = json.dumps({"results": {"bindings": [row]}}).encode()
    metadata = EURLexMetadataParser().parse(metadata_data, celex)
    with EURLexClient() as client:
        client._version_index = {celex: []}
        monkeypatch.setattr(client, "get_html_manifest_uri", lambda _: "original")
        monkeypatch.setattr(
            client,
            "download_xhtml",
            lambda _: (
                b'<html><body><p class="oj-ti-art">Article 1</p><p class="oj-normal">A future provision.</p></body></html>'
            ),
        )
        raw = client.get_text(celex, meta_data=metadata_data)
    parser = EURLexTextParser()
    norm = ParsedNorm(metadata, tuple(parser.parse_text(raw)), tuple(parser.extract_reforms(raw)))
    version = norm.blocks[0].versions[0]
    assert version.publication_date == date(2026, 10, 6)
    assert version.in_force_from == date(2099, 10, 9)
    assert norm.reforms[0].date == date(2026, 10, 6)
    data, repo = tmp_path / "data", tmp_path / "repo"
    save_structured_json(data, norm)
    config = Config(countries={"eu": CountryConfig(data_dir=str(data), repo_path=str(repo))})
    assert (
        committer(config, "eu", celex) if committer is commit_one else committer(config, "eu")
    ) == 1
    markdown = next((repo / "eu").rglob("*.md")).read_text()
    frontmatter = yaml.safe_load(markdown.split("---", 2)[1])
    assert str(frontmatter["publication_date"]) == "2026-10-06"
    assert str(frontmatter["last_updated"]) == "2099-10-09"
    assert frontmatter["status"] == "in_force"  # Status on the explicitly future text date.
    assert "as_enacted" not in markdown and "A future provision." in markdown
    message = subprocess.check_output(
        ["git", "-C", str(repo), "log", "-1", "--format=%as%n%B"], text=True
    )
    assert message.startswith("2026-10-06") and "Source-Date: 2026-10-06" in message


@pytest.mark.parametrize("committer", [commit_one, commit_all_fast])
def test_retroactive_and_same_day_source_versions_survive(tmp_path, monkeypatch, committer):
    celex = "31995R1802"
    metadata = json.dumps(
        {
            "results": {
                "bindings": [
                    {
                        "celex": {"value": celex},
                        "title": {"value": "Regulation No 1802/95"},
                        "publicationDate": {"value": "1995-07-26"},
                        "date": {"value": "1995-07-25"},
                        "force": {"value": "true"},
                        "hasCons": {"value": "true"},
                        "rtype": {
                            "value": "http://publications.europa.eu/resource/authority/resource-type/REG"
                        },
                    }
                ]
            }
        }
    ).encode()
    versions = [
        {"celex": "01995R1802-19950201", "date": "1995-02-01", "manifest_uri": "retroactive"},
        {"celex": "01995R1802-19950726", "date": "1995-07-26", "manifest_uri": "consolidated"},
        {"celex": "01995R1802-19950726-A", "date": "1995-07-26", "manifest_uri": "consolidated"},
    ]
    client = EURLexClient()
    monkeypatch.setattr(client, "get_metadata", lambda _: metadata)
    monkeypatch.setattr(client, "get_consolidated_versions", lambda _: versions)
    monkeypatch.setattr(client, "get_html_manifest_uri", lambda _: "original")
    monkeypatch.setattr(
        client,
        "download_xhtml",
        lambda uri: (
            f'<html><body><p class="oj-ti-art">Article 1</p>'
            f'<p class="oj-normal">1. {uri}</p></body></html>'
        ).encode(),
    )
    raw = client.get_text(celex)
    parser = EURLexTextParser()
    norm = ParsedNorm(
        metadata=EURLexMetadataParser().parse(metadata, celex),
        blocks=tuple(parser.parse_text(raw)),
        reforms=tuple(parser.extract_reforms(raw)),
    )
    data_dir, repo = tmp_path / "data", tmp_path / "repo"
    path = save_structured_json(data_dir, norm)
    stored = json.loads(path.read_text())
    assert stored["articles"][0]["current_text"].endswith("1. consolidated")
    assert [r.get("has_source_date", True) for r in stored["reforms"]] == [
        True,
        False,
        False,
        False,
    ]
    config = Config(countries={"eu": CountryConfig(data_dir=str(data_dir), repo_path=str(repo))})
    if committer is commit_one:
        assert committer(config, "eu", celex) == 4
    else:
        assert committer(config, "eu") == 4
    log = subprocess.check_output(
        [
            "git",
            "-C",
            str(repo),
            "log",
            "--reverse",
            "--format=%x1e%as%n%B",
        ],
        text=True,
    ).split("\x1e")[1:]
    assert len(log) == 4
    assert all(body.startswith("1995-07-26") for body in log)
    assert "Source-Date: 1995-07-26" in log[0]
    assert all("Source-Date:" not in body for body in log[1:])
    assert [body.split("Source-Id: ")[1].splitlines()[0] for body in log] == [celex] + [
        v["celex"] for v in versions
    ]
    final = next((repo / "eu").rglob("*.md")).read_text()
    assert "1. consolidated" in final and "1. original" not in final
    assert str(yaml.safe_load(final.split("---", 2)[1])["last_updated"]) == "1995-07-26"
    tip = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"])
    if committer is commit_one:
        assert committer(config, "eu", celex) == 0
    else:
        committer(config, "eu")  # fast path returns total already published
    assert subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]) == tip


def test_pdf_body_numbers_and_custom_marker_font():
    modern = parse_pdf((FIXTURES / "01958R0001-19730101.pdf").read_bytes())
    assert [p.text for p in modern if p.css_class == "h4"] == [f"Article {i}" for i in range(1, 9)]
    text = render_paragraphs(modern)
    assert "jurisdiction" in text and "procedure" in text
    assert "documentation tool" not in text and "1958R0001" not in text
    legacy = render_paragraphs(parse_pdf((FIXTURES / "01998R2866-20010101.pdf").read_bytes()))
    assert "#### Article 1" in legacy and "#### Article 2" in legacy
    assert "!B" not in legacy and '"M1' not in legacy
    # A text-only conversion would silently lose this scanned certificate.
    with pytest.raises(UnsupportedPDF, match="rasterized"):
        parse_pdf((FIXTURES / "01981R0139-19920609.pdf").read_bytes())


def test_client_keeps_long_histories_and_never_caches_an_excluded_chain(monkeypatch):
    client = EURLexClient()
    metadata = json.dumps(
        {"results": {"bindings": [{"publicationDate": {"value": "2016-05-04"}}]}}
    ).encode()
    versions = [
        {"celex": f"02016R0679-V{i}", "date": "2016-05-04", "manifest_uri": f"v{i}"}
        for i in range(250)
    ]
    monkeypatch.setattr(client, "get_consolidated_versions", lambda _: versions)
    monkeypatch.setattr(client, "get_html_manifest_uri", lambda _: "original")

    def download(uri):
        if uri == "v249":
            raise ValueError("unavailable source")
        return b'<html><body><p class="oj-normal">1. Body</p></body></html>'

    monkeypatch.setattr(client, "download_xhtml", download)
    raw = client.get_text(
        "32016R0679", metadata, version_exclusions={"02016R0679-V249": "reviewed gap"}
    )
    assert len(EURLexTextParser().extract_reforms(raw)) == 250
    with pytest.raises(ValueError, match="unavailable source"):
        client.get_text("32016R0679", metadata)
    assert not client._bundle_cache
    monkeypatch.setattr(
        client, "download_xhtml", lambda _: b"<html><body><p>Body</p></body></html>"
    )
    assert len(EURLexTextParser().extract_reforms(client.get_text("32016R0679", metadata))) == 251


def test_daily_real_source_ids_idempotence_and_retry(tmp_path, monkeypatch):
    from datetime import date
    from types import SimpleNamespace

    from legalize.fetcher.eu.daily import daily
    from legalize.fetcher.eu.discovery import EURLexDiscovery
    from legalize.pipeline import NothingPublished
    from legalize.state.store import StateStore

    celex = "32016R0679"
    metadata = json.loads((FIXTURES / f"{celex}_metadata.json").read_text())
    raw = b"""<eurlex-multi-version celex="32016R0679">
    <version type="original" source-id="32016R0679" effective-date="2016-05-04">
    <html><body><p class="oj-ti-art">Article 1</p><p class="oj-normal">1. Original</p></body></html>
    </version><version type="consolidation" source-id="02016R0679-20160504" effective-date="2016-05-04">
    <html><body><p class="oj-ti-art">Article 1</p><p class="oj-normal">1. Consolidated</p></body></html>
    </version></eurlex-multi-version>"""
    client = EURLexClient()
    monkeypatch.setattr(EURLexClient, "create", lambda _: client)
    monkeypatch.setattr(client, "get_metadata_sparql", lambda _: metadata)
    monkeypatch.setattr(client, "_merge_list_facts", lambda *_: None)
    monkeypatch.setattr(client, "get_text", lambda *_, **__: raw)
    monkeypatch.setattr(client, "get_consolidated_versions", lambda _: [])
    discovery = SimpleNamespace(
        discover_daily=lambda *_: [celex],
        discover_published=lambda *_: {},
        discover_consolidations_created=lambda *_: [],
    )
    monkeypatch.setattr(EURLexDiscovery, "create", lambda _: discovery)
    state_path = tmp_path / "state.json"
    repo = tmp_path / "repo"
    config = Config(
        countries={
            "eu": CountryConfig(
                data_dir=str(tmp_path / "data"),
                repo_path=str(repo),
                state_path=str(state_path),
            )
        }
    )
    assert daily(config, date(2016, 5, 4)) == 2
    tip = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"])
    assert daily(config, date(2016, 5, 4)) == 0
    assert subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]) == tip
    log = subprocess.check_output(["git", "-C", str(repo), "log", "--format=%B"], text=True)
    assert "Source-Id: 02016R0679-20160504" in log and "EU-DAILY" not in log

    def failed(*_, **__):
        raise ValueError("unavailable source")

    monkeypatch.setattr(client, "get_text", failed)
    with pytest.raises(NothingPublished):
        daily(config, date(2016, 5, 5))
    state = StateStore(state_path)
    state.load()
    assert state.last_summary_date == date(2016, 5, 4)


def test_daily_publishes_completed_day_before_interruption(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from legalize.fetcher.eu import daily as daily_module
    from legalize.state.store import StateStore

    metadata = json.loads((FIXTURES / "32016R0679_metadata.json").read_text())
    client = EURLexClient()
    monkeypatch.setattr(EURLexClient, "create", lambda _: client)
    monkeypatch.setattr(client, "get_metadata_sparql", lambda _: metadata)
    monkeypatch.setattr(client, "_merge_list_facts", lambda *_: None)
    raw = b"""<eurlex-multi-version celex="32016R0679">
    <version type="original" source-id="32016R0679" effective-date="2016-05-04">
    <html><body><p class="oj-ti-art">Article 1</p><p class="oj-normal">Original</p></body></html>
    </version></eurlex-multi-version>"""
    monkeypatch.setattr(client, "get_text", lambda *_, **__: raw)
    monkeypatch.setattr(client, "get_consolidated_versions", lambda _: [])
    days = [date(2026, 10, 12), date(2026, 10, 13)]

    def discover(_, current_date):
        if current_date == days[1]:
            raise KeyboardInterrupt("CI deadline")
        return ["32016R0679"]

    monkeypatch.setattr(
        daily_module.EURLexDiscovery,
        "create",
        lambda _: SimpleNamespace(
            discover_daily=discover,
            discover_published=lambda *_: {},
            discover_consolidations_created=lambda *_: [],
        ),
    )
    monkeypatch.setattr(daily_module, "resolve_dates_to_process", lambda *_: days)
    repo = Mock(refused=[], read=lambda _: PUBLISHED)
    monkeypatch.setattr(daily_module, "GitRepo", lambda *_: repo)
    monkeypatch.setattr(daily_module, "commit_one", lambda *_: 1)
    state_path = tmp_path / "state.json"
    config = Config(
        countries={"eu": CountryConfig(data_dir=str(tmp_path / "data"), state_path=str(state_path))}
    )
    config.git.push = True
    with pytest.raises(KeyboardInterrupt, match="CI deadline"):
        daily_module.daily(config)
    repo.push.assert_called_once_with()
    state = StateStore(state_path)
    state.load()
    assert state.last_summary_date == days[0]


def test_daily_fetches_concurrently_and_commits_in_discovery_order(tmp_path, monkeypatch):
    from threading import Barrier, Event, current_thread, main_thread
    from types import SimpleNamespace
    from unittest.mock import Mock

    from legalize.fetcher.eu import daily as daily_module

    ids = ["32016R0679", "32017R0745"]
    barrier = Barrier(2, timeout=2)
    second_finished = Event()
    clients = []
    committed = []

    def create(_):
        client = EURLexClient()
        clients.append(client)
        return client

    def get_text(_, norm_id, **kwargs):
        barrier.wait()
        if norm_id == ids[0]:
            assert second_finished.wait(2)
        else:
            second_finished.set()
        return f'''<eurlex-multi-version celex="{norm_id}">
        <version type="original" source-id="{norm_id}" effective-date="2016-05-04">
        <html><body><p>Original</p></body></html></version></eurlex-multi-version>'''.encode()

    def commit(_, country, norm_id):
        assert current_thread() is main_thread()
        committed.append(norm_id)
        return 1

    monkeypatch.setattr(EURLexClient, "create", create)
    monkeypatch.setattr(
        EURLexClient,
        "get_metadata_sparql",
        lambda _, norm_id: json.loads((FIXTURES / f"{norm_id}_metadata.json").read_text()),
    )
    monkeypatch.setattr(EURLexClient, "_merge_list_facts", lambda *_: None)
    monkeypatch.setattr(EURLexClient, "get_text", get_text)
    monkeypatch.setattr(EURLexClient, "get_consolidated_versions", lambda *_: [])
    monkeypatch.setattr(
        daily_module.EURLexDiscovery,
        "create",
        lambda _: SimpleNamespace(
            discover_daily=lambda *_: ids,
            discover_published=lambda *_: {},
            discover_consolidations_created=lambda *_: [],
        ),
    )
    monkeypatch.setattr(
        daily_module, "GitRepo", lambda *_: Mock(refused=[], read=lambda _: PUBLISHED)
    )
    monkeypatch.setattr(daily_module, "commit_one", commit)
    config = Config(
        countries={
            "eu": CountryConfig(
                max_workers=2,
                data_dir=str(tmp_path / "data"),
                state_path=str(tmp_path / "state.json"),
            )
        }
    )
    assert daily_module.daily(config, date(2026, 10, 12)) == 2
    assert committed == ids
    assert len(clients) == 3  # Discovery and one independent session per act.


def test_entry_into_force_uses_annotated_ev_not_application():
    celex = "32017R0745"
    metadata = json.loads((FIXTURES / f"{celex}_metadata.json").read_text())
    annotations = [
        {"date": {"value": "1001-01-01"}, "typeOfDate": {"value": "{MA|application}"}},
        {"date": {"value": "2017-05-25"}, "typeOfDate": {"value": "{EV|entry-into-force}"}},
    ]
    metadata["results"]["bindings"][0]["sourceFacts"] = {
        "value": json.dumps({"date_annotations": annotations})
    }
    parsed = EURLexMetadataParser().parse(json.dumps(metadata).encode(), celex)
    assert dict(parsed.extra)["entry_into_force"] == "2017-05-25"
    assert json.loads(dict(parsed.extra)["source_metadata"])["date_annotations"] == annotations


def _eu_daily(tmp_path, monkeypatch, ids, metadata, published=lambda _: "", **client):
    """One EU daily over a stubbed source and corpus; returns its config and saved norms."""
    from types import SimpleNamespace
    from unittest.mock import Mock

    from legalize.fetcher.eu import daily as daily_module

    saved = []
    monkeypatch.setattr(EURLexClient, "get_metadata_sparql", lambda _, celex: metadata[celex])
    monkeypatch.setattr(EURLexClient, "_merge_list_facts", lambda *_: None)
    for name, value in client.items():
        monkeypatch.setattr(EURLexClient, name, value)
    monkeypatch.setattr(
        daily_module.EURLexDiscovery,
        "create",
        lambda _: SimpleNamespace(
            discover_daily=lambda *_: list(ids),
            discover_published=lambda *_: {},
            discover_consolidations_created=lambda *_: [],
        ),
    )
    monkeypatch.setattr(daily_module, "GitRepo", lambda *_: Mock(refused=[], read=published))
    monkeypatch.setattr(daily_module, "save_structured_json", lambda _, norm: saved.append(norm))
    monkeypatch.setattr(daily_module, "commit_one", lambda *_: 1)
    config = Config(
        countries={
            "eu": CountryConfig(
                data_dir=str(tmp_path / "data"), state_path=str(tmp_path / "state.json")
            )
        }
    )
    return config, saved


def _act(celex: str, published_on: str, **extra) -> dict:
    row = {
        "celex": {"value": celex},
        "title": {"value": f"Act {celex}"},
        "publicationDate": {"value": published_on},
        "force": {"value": "1"},
        "rtype": {"value": "http://publications.europa.eu/resource/authority/resource-type/REG"},
    }
    row.update({key: {"value": value} for key, value in extra.items()})
    return {"results": {"bindings": [row]}}


def _envelope(self, celex, **_) -> bytes:
    return (
        f'<eurlex-multi-version celex="{celex}"><version type="original" source-id="{celex}" '
        f'effective-date="2026-11-03"><html><body><p>Body</p></body></html></version>'
        "</eurlex-multi-version>"
    ).encode()


def test_daily_refreshes_the_published_corpus_and_never_bootstraps_outside_it(
    tmp_path, monkeypatch
):
    from legalize.fetcher.eu.daily import daily
    from legalize.state.store import StateStore

    day = date(2026, 11, 3)
    metadata = {
        "32026R2387": _act("32026R2387", "2026-11-03"),  # new that day
        "32008R1272": _act("32008R1272", "2008-12-31"),  # published, amended that day
        "32005R0396": _act("32005R0396", "2005-03-16"),  # left out of the pinned scope
        "32006R1907": {"results": {"bindings": []}},  # REACH: no English HTML original
    }
    fetched = []

    def get_text(self, celex, **kwargs):
        fetched.append(celex)
        return _envelope(self, celex)

    config, saved = _eu_daily(
        tmp_path,
        monkeypatch,
        metadata,
        metadata,
        published=lambda path: PUBLISHED if path.endswith("/32008R1272.md") else "",
        get_text=get_text,
    )
    assert daily(config, day) == 2
    assert fetched == [norm.metadata.identifier for norm in saved] == ["32026R2387", "32008R1272"]
    state = StateStore(tmp_path / "state.json")
    state.load()
    assert state.last_summary_date == day


def test_daily_holds_an_agreement_until_eurlex_states_it_in_force(tmp_path, monkeypatch):
    from legalize.fetcher.eu import daily as daily_module
    from legalize.fetcher.eu.parser import PendingStatus
    from legalize.state.store import StateStore

    celex = "22026A02361"
    metadata = {celex: _act(celex, "2026-10-26")}

    def awaiting(self, norm_id, **_):
        raise PendingStatus(f"{norm_id}: source states not in force")

    config, saved = _eu_daily(tmp_path, monkeypatch, [celex], metadata, get_text=awaiting)
    # Nothing failed, so nothing turns the run red, and the day is done.
    assert daily_module.daily(config, date(2026, 10, 26)) == 0
    state = StateStore(tmp_path / "state.json")
    state.load()
    assert state.last_summary_date == date(2026, 10, 26) and celex in state.pending

    # Ratified: no query of a later day finds it, the flag does.
    monkeypatch.setattr(
        daily_module.EURLexDiscovery,
        "create",
        lambda _: __import__("types").SimpleNamespace(
            discover_daily=lambda *_: [],
            discover_published=lambda *_: {},
            discover_consolidations_created=lambda *_: [],
        ),
    )
    monkeypatch.setattr(
        EURLexClient,
        "get_source_facts",
        lambda _, ids: {i: {"resource_legal_in-force": [{"value": "1"}]} for i in ids},
    )
    monkeypatch.setattr(EURLexClient, "get_text", _envelope)
    assert daily_module.daily(config, date(2026, 11, 20)) == 1
    assert [norm.metadata.identifier for norm in saved] == [celex]
    state = StateStore(tmp_path / "state.json")
    state.load()
    assert state.pending == {}


def test_daily_keeps_a_published_laws_recorded_version_gaps(tmp_path, monkeypatch):
    from legalize.fetcher.eu.daily import daily

    celex = "32021R0403"
    reason = "CELLAR PDF contains rasterized legal text"
    gaps = json.dumps([{"norm_id": celex, "date": "2021-04-21", "reason": reason, "sha256": "c6"}])
    published = f'---\nidentifier: "{celex}"\nsource_version_gaps: {json.dumps(gaps)}\n---\nBody\n'
    seen = {}

    def merge(self, norm_id, result):
        seen["hasCons"] = result["results"]["bindings"][0]["hasCons"]["value"]

    def get_text(self, norm_id, meta_data=None, version_exclusions=None):
        seen["excluded"] = version_exclusions
        return _envelope(self, norm_id)

    config, saved = _eu_daily(
        tmp_path,
        monkeypatch,
        [celex],
        {celex: _act(celex, "2021-03-31", hasCons="1")},
        published=lambda _: published,
        get_consolidated_versions=lambda _, __: [
            {"celex": "02021R0403-20210421", "date": "2021-04-21"}
        ],
        _merge_list_facts=merge,
        get_text=get_text,
    )
    assert daily(config, date(2026, 11, 1)) == 1
    # Not downloaded again, and with no consolidation left the act stays as enacted.
    assert seen == {"hasCons": "false", "excluded": {"02021R0403-20210421": reason}}
    [norm] = saved
    assert dict(norm.metadata.extra)["source_version_gaps"] == gaps
    assert norm.metadata.text_state is None


def _pdf_version(celex: str, day: str) -> dict:
    return {"celex": celex, "date": day, "format": "pdfa2a", "manifest_uri": f"cellar/{celex}"}


def test_daily_records_an_unreadable_pdf_version_as_a_gap(tmp_path, monkeypatch):
    """A scanned consolidation joins the law's gaps instead of failing the day."""
    import hashlib

    from legalize.fetcher.eu.daily import daily
    from legalize.state.store import StateStore

    celex = "32021R0403"
    scanned = (FIXTURES / "01981R0139-19920609.pdf").read_bytes()  # a real scanned CELLAR PDF
    recorded = [
        {
            "norm_id": celex,
            "date": "2021-04-21",
            "reason": "CELLAR PDF contains rasterized legal text",
            "sha256": "c63a578aaee829d1eec474c30daab414df4d36658695b9cd61b8294422acebc9",  # pragma: allowlist secret
        }
    ]
    published = (
        f'---\nidentifier: "{celex}"\n'
        f"source_version_gaps: {json.dumps(json.dumps(recorded))}\n---\nBody\n"
    )
    seen = {}

    def merge(self, norm_id, result):
        seen["hasCons"] = result["results"]["bindings"][0]["hasCons"]["value"]

    def get_text(self, norm_id, meta_data=None, version_exclusions=None):
        seen["excluded"] = version_exclusions
        return _envelope(self, norm_id)

    config, saved = _eu_daily(
        tmp_path,
        monkeypatch,
        [celex],
        {celex: _act(celex, "2021-03-31", hasCons="1")},
        published=lambda _: published,
        get_consolidated_versions=lambda _, __: [
            _pdf_version("02021R0403-20210421", "2021-04-21"),
            _pdf_version("02021R0403-20261101", "2026-11-01"),
        ],
        download_pdf=lambda _, version: scanned,
        _merge_list_facts=merge,
        get_text=get_text,
    )
    assert daily(config, date(2026, 11, 1)) == 1
    reason = "CELLAR PDF contains rasterized legal text"
    assert seen == {
        "hasCons": "false",
        "excluded": {"02021R0403-20210421": reason, "02021R0403-20261101": reason},
    }
    [norm] = saved
    gaps = json.loads(dict(norm.metadata.extra)["source_version_gaps"])
    assert gaps == recorded + [
        {
            "norm_id": celex,
            "date": "2026-11-01",
            "reason": reason,
            "sha256": hashlib.sha256(scanned).hexdigest(),
        }
    ]
    state = StateStore(tmp_path / "state.json")
    state.load()
    assert state.last_summary_date == date(2026, 11, 1)


def test_daily_checks_again_a_gap_recorded_without_source_bytes(tmp_path, monkeypatch):
    """A failed download is not a gap: once the PDF reads, the version is published."""
    from legalize.fetcher.eu.daily import daily

    celex = "32021R0403"
    readable = (FIXTURES / "01958R0001-19730101.pdf").read_bytes()
    placeholder = [
        {
            "norm_id": celex,
            "date": "2025-02-27",
            "reason": "No retrievable English PDF body; CELLAR metadata placeholder",
            "sha256": None,
        }
    ]
    published = (
        f'---\nidentifier: "{celex}"\n'
        f"source_version_gaps: {json.dumps(json.dumps(placeholder))}\n---\nBody\n"
    )
    seen = {}

    def get_text(self, norm_id, meta_data=None, version_exclusions=None):
        seen["excluded"] = version_exclusions
        return _envelope(self, norm_id)

    config, saved = _eu_daily(
        tmp_path,
        monkeypatch,
        [celex],
        {celex: _act(celex, "2021-03-31", hasCons="1")},
        published=lambda _: published,
        get_consolidated_versions=lambda _, __: [_pdf_version("02021R0403-20250227", "2025-02-27")],
        download_pdf=lambda _, version: readable,
        get_text=get_text,
    )
    assert daily(config, date(2026, 11, 1)) == 1
    assert seen == {"excluded": None}
    [norm] = saved
    assert "source_version_gaps" not in dict(norm.metadata.extra)
    # Kept where get_text looks first, so the version is not downloaded twice.
    cached = tmp_path / "data" / "pdf" / "02021R0403-20250227.pdf"
    assert cached.read_bytes() == readable


def test_daily_still_fails_on_a_kind_of_gap_nobody_reviewed(tmp_path, monkeypatch):
    from legalize.fetcher.eu import daily as daily_module
    from legalize.fetcher.eu.parser_pdf import UnsupportedPDF
    from legalize.pipeline import NothingPublished

    celex = "32021R0403"

    def unreviewed(_):
        raise UnsupportedPDF("CELLAR PDF mathematical glyphs require layout-aware validation")

    monkeypatch.setattr(daily_module, "parse_pdf", unreviewed)
    config, saved = _eu_daily(
        tmp_path,
        monkeypatch,
        [celex],
        {celex: _act(celex, "2021-03-31", hasCons="1")},
        published=lambda _: PUBLISHED,
        get_consolidated_versions=lambda _, __: [_pdf_version("02021R0403-20261101", "2026-11-01")],
        download_pdf=lambda _, version: b"%PDF",
    )
    with pytest.raises(NothingPublished, match="mathematical glyphs"):
        daily_module.daily(config, date(2026, 11, 1))
    assert saved == []


def test_daily_fetches_what_cellar_indexed_after_its_day_was_done(tmp_path, monkeypatch):
    """The run read 17 Nov before CELLAR had its acts; a consolidation dated 9 Oct came on 6 Nov."""
    from types import SimpleNamespace
    from unittest.mock import Mock

    from legalize.fetcher.eu import daily as daily_module

    late, held = "32026R2565", "32026R2527"
    stale, current = "32020D0472", "32016R0679"
    metadata = {
        celex: _act(celex, day)
        for celex, day in [
            ("32026R2600", "2026-11-18"),
            (late, "2026-11-17"),
            (stale, "2020-03-31"),
        ]
    }
    spans = []

    def published(_, first, last):
        spans.append((first, last))
        # One the corpus lacks, one it already holds.
        return {late: date(2026, 11, 17), held: date(2026, 11, 17)}

    def created(_, since):
        spans.append(since)
        return [
            (stale, "02020D0472-20261009", date(2026, 10, 9)),  # not in its history
            (current, "02016R0679-20261001", date(2026, 10, 1)),  # already committed
            (current, "02016R0679-20270101", date(2027, 1, 1)),  # its day is still ahead
        ]

    config, saved = _eu_daily(tmp_path, monkeypatch, ["32026R2600"], metadata, get_text=_envelope)
    monkeypatch.setattr(
        daily_module.EURLexDiscovery,
        "create",
        lambda _: SimpleNamespace(
            discover_daily=lambda *_: ["32026R2600"],
            discover_published=published,
            discover_consolidations_created=created,
        ),
    )
    corpus = {held, stale, current}
    repo = Mock(
        refused=[],
        read=lambda path: PUBLISHED if path.endswith(f"{stale}.md") else "",
        has_file=lambda path: any(path.endswith(f"{celex}.md") for celex in corpus),
        has_commit_with_source_id=lambda source, norm: source == "02016R0679-20261001",
    )
    monkeypatch.setattr(daily_module, "GitRepo", lambda *_: repo)
    assert daily_module.daily(config, date(2026, 11, 18)) == 3
    # The late act as new on its own day; the act with a late consolidation refreshed.
    assert [norm.metadata.identifier for norm in saved] == ["32026R2600", late, stale]
    assert spans == [(date(2026, 11, 8), date(2026, 11, 17)), date(2026, 11, 8)]


def test_pdf_download_asks_cellar_for_the_item_when_doc_1_is_absent(monkeypatch):
    import requests

    manifest = "http://publications.europa.eu/resource/cellar/548c7b6f.0006.02"

    def get(url, **_):
        if url == manifest.replace("http://", "https://") + "/DOC_2":
            return b"%PDF-1.7"
        raise requests.HTTPError("404 Client Error")

    client = EURLexClient()
    monkeypatch.setattr(client, "_get", get)
    monkeypatch.setattr(
        client,
        "sparql_query",
        lambda _: {"results": {"bindings": [{"item": {"value": manifest + "/DOC_2"}}]}},
    )
    version = {"celex": "02021R0403-20250227", "manifest_uri": manifest, "format": "pdfa2a"}
    assert client.download_pdf(version) == b"%PDF-1.7"
