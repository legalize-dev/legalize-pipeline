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
    discovery = SimpleNamespace(discover_daily=lambda *_: [celex])
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
