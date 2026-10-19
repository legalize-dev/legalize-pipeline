"""Irish source histories retain dates, source identity and text-state transitions."""

import base64
import hashlib
import json
import subprocess
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
import yaml

from legalize.config import Config, CountryConfig
from legalize.fetcher.ie import history
from legalize.fetcher.ie.parser import ISBMetadataParser, ISBTextParser
from legalize.models import Block, NormStatus, Paragraph, ParsedNorm, Reform, TextState, Version
from legalize.pipeline import commit_all_fast, commit_one
from legalize.storage import load_norma_from_json, save_structured_json
from legalize.transformer.markdown import render_norm_at_date

FIXTURES = Path(__file__).parent / "fixtures" / "ie"
IDENTIFIER = "IE-2015-act-29"
PUB = date(2015, 7, 27)


@pytest.mark.parametrize("replacement", ["verified", "absent", "different_bytes"])
def test_verified_layout_correction_keeps_source_cutoff(monkeypatch, replacement):
    from legalize.fetcher.ie import pdf

    original, corrected = b"Original layout", b"Corrected layout"
    old_hash, new_hash = [hashlib.sha256(data).hexdigest() for data in (original, corrected)]
    monkeypatch.setattr(history, "_CORRECTED_PDF_LAYOUTS", {old_hash: new_hash})
    monkeypatch.setattr(
        pdf,
        "parse_revised_pdf",
        lambda data: ([Paragraph("parrafo", data.decode())], date(2020, 1, 1)),
    )
    records = [
        {
            "format": "revised_pdf",
            "url": "https://source.test/january.pdf",
            "catalog_date": "2020-01-01",
            "sha256": old_hash,
            "data": base64.b64encode(original).decode(),
        }
    ]
    if replacement != "absent":
        records.append(
            {
                "format": "revised_pdf",
                "url": "https://source.test/march.pdf",
                "catalog_date": "2020-03-30",
                "sha256": new_hash,
                "data": base64.b64encode(
                    corrected if replacement == "verified" else b"Different source text"
                ).decode(),
            }
        )
    raw = envelope(versions=records)
    if replacement == "different_bytes":
        # Two unverified bodies printing one date: neither is published, both are listed.
        parsed = history._parse(raw)
        assert len(parsed.blocks[0].versions) == 1
        gaps = json.loads(dict(parsed.metadata.extra)["source_version_gaps"])
        assert {g["url"] for g in gaps} == {r["url"] for r in records}
        assert all("conflicting source texts" in g["reason"] for g in gaps)
        return
    parsed = history._parse(raw)
    assert len(parsed.blocks[0].versions) == 2
    snapshot = parsed.blocks[0].versions[-1]
    assert snapshot.in_force_from == date(2020, 1, 1)
    assert snapshot.source.endswith("march.pdf" if replacement == "verified" else "january.pdf")
    assert parsed.reforms[-1].date == date(2020, 1, 1)
    assert not parsed.reforms[-1].has_source_date


@pytest.mark.parametrize(
    ("day", "source_id", "warned"),
    [
        (PUB, IDENTIFIER, False),
        (date(2020, 1, 1), f"revised-{IDENTIFIER}@2020-01-01", True),
        (date(2020, 7, 1), "IE-2020-act-1", True),
        (date(2021, 1, 1), f"revised-{IDENTIFIER}@2021-01-01", False),
    ],
)
def test_source_warning_belongs_to_selected_snapshot(monkeypatch, tmp_path, day, source_id, warned):
    from legalize.fetcher.ie import pdf

    warning = "The official snapshot omits section 1384A from its body. Verify the source."
    monkeypatch.setattr(
        pdf,
        "parse_revised_pdf",
        lambda data: (
            [Paragraph("parrafo", data.decode())],
            date(2020 if data == b"Incomplete archived body" else 2021, 1, 1),
        ),
    )
    monkeypatch.setattr(
        pdf, "source_warning", lambda data: warning if data == b"Incomplete archived body" else None
    )
    raw = envelope(
        effects=[effect(publication_date="2020-07-01")],
        versions=[
            {
                "format": "revised_pdf",
                "url": f"https://source.test/{year}.pdf?versionId=verified",
                "catalog_date": f"{year}-01-01",
                "data": base64.b64encode(body).decode(),
            }
            for year, body in [
                (2020, b"Incomplete archived body"),
                (2021, b"Complete archived body"),
            ]
        ],
    )
    norm = history._parse(raw)
    restored = load_norma_from_json(save_structured_json(tmp_path, norm))
    assert [v.source_warning for v in restored.blocks[0].versions] == [None, warning, None]
    snapshot = next(r for r in restored.reforms if r.norm_id.endswith("@2020-01-01"))
    assert warning in snapshot.change_note
    metadata = replace(
        restored.metadata,
        extra=restored.metadata.extra + (("source_warning", "HEAD warning must not leak"),),
    )
    markdown = render_norm_at_date(metadata, restored.blocks, day, source_id=source_id)
    frontmatter = yaml.safe_load(markdown.split("---", 2)[1])
    assert frontmatter.get("source_warning") == (warning if warned else None)
    assert ("> **Incomplete source:**" in markdown) is warned
    assert "HEAD warning must not leak" not in markdown
    if warned:
        assert frontmatter.get("text_state", "point_in_time") == "point_in_time"
        assert str(frontmatter["last_updated"]) == "2020-01-01"


def envelope(*, effects=(), versions=()):
    raw = (FIXTURES / "sample-environment-2015.xml").read_bytes()
    encoded = base64.b64encode(raw).decode()
    return json.dumps(
        {
            "legalize_ie": 1,
            "identifier": IDENTIFIER,
            "metadata": encoded,
            "versions": [{"format": "enacted", "url": "https://source.test/act", "data": encoded}]
            + list(versions),
            "effects": list(effects),
        }
    ).encode()


def test_pdf_failure_is_listed_with_the_exact_source_object(monkeypatch):
    from legalize.fetcher.ie import pdf

    data = b"Source with a missing section"
    url = "https://source.test/archive.pdf?versionId=original"

    def reject(_):
        raise pdf.UnsupportedPDF("Missing section 42")

    monkeypatch.setattr(pdf, "parse_revised_pdf", reject)
    raw = envelope(
        versions=[
            {
                "format": "revised_pdf",
                "url": url,
                "catalog_date": "2020-01-01",
                "data": base64.b64encode(data).decode(),
            }
        ]
    )
    parsed = history._parse(raw)
    assert len(parsed.blocks[0].versions) == 1
    [gap] = json.loads(dict(parsed.metadata.extra)["source_version_gaps"])
    assert gap["norm_id"] == IDENTIFIER and gap["url"] == url
    assert gap["sha256"] == hashlib.sha256(data).hexdigest()
    assert "Missing section 42" in gap["reason"]


def effect(identifier="IE-2020-act-1", **kwargs):
    return {
        "source_id": identifier,
        "publication_date": "2020-01-01",
        "note": "Section 2 substituted",
        "provision": "1/2020, s. 2",
        **kwargs,
    }


def test_source_envelope_keeps_original_and_dated_effects():
    raw = envelope(effects=[effect(), effect(note="Section 3 substituted")])
    blocks = ISBTextParser().parse_text(raw)
    reforms = ISBTextParser().extract_reforms(raw)
    metadata = ISBMetadataParser().parse(
        (FIXTURES / "sample-environment-2015.xml").read_bytes(), IDENTIFIER
    )
    assert blocks[0].versions[0].text_state is TextState.AS_ENACTED
    assert [(r.norm_id, r.date) for r in reforms] == [
        (IDENTIFIER, metadata.publication_date),
        ("IE-2020-act-1", date(2020, 1, 1)),
    ]
    assert "Section 2 substituted" in reforms[1].change_note
    assert "Section 3 substituted" in reforms[1].change_note
    with pytest.raises(ValueError, match="identifiers disagree"):
        history.metadata_for_text(replace(metadata, identifier="wrong"), raw)


def test_source_images_are_counted_and_meaningful_omissions_are_visible():
    raw = (FIXTURES / "sample-v04-isb-1922-act-1.xml").read_bytes()
    encoded = base64.b64encode(raw).decode()
    data = json.dumps(
        {
            "legalize_ie": 1,
            "identifier": "IE-1922-act-1",
            "metadata": encoded,
            "versions": [{"format": "enacted", "url": "https://source.test/1922", "data": encoded}],
            "effects": [],
        }
    ).encode()
    norm = history._parse(data)
    text = "\n".join(p.text for p in norm.blocks[0].versions[0].paragraphs)
    assert text.count("[image omitted]") == 1
    assert "harp.jpg" not in text
    extra = dict(norm.metadata.extra)
    assert extra["images_dropped"] == "2"
    assert json.loads(extra["images_dropped_by_source"]) == {"https://source.test/1922": 2}


def test_undated_editorial_notes_survive_without_creating_reforms_or_status_dates():
    note = {"note": "Spent.", "directory_url": "https://www.irishstatutebook.ie/isbc/1929_10.html"}
    data = json.loads(envelope())
    data["editorial_notes"] = [note]
    parsed = history._parse_on(json.dumps(data).encode(), date(2026, 10, 8))
    assert json.loads(dict(parsed.metadata.extra)["legislation_directory_notes"]) == [note]
    assert [(reform.norm_id, reform.date) for reform in parsed.reforms] == [(IDENTIFIER, PUB)]
    assert parsed.metadata.status is NormStatus.IN_FORCE


def test_source_corrections_survive_structured_storage_and_corpus_frontmatter(tmp_path):
    from legalize.fetcher.ie.effects import parse_effects
    from legalize.storage import load_norma_from_json
    from legalize.transformer.markdown import render_norm_at_date

    identifier = "IE-2002-act-28"
    raw = (FIXTURES / "sample-effects-appropriation-2002.xml").read_bytes()
    encoded = base64.b64encode(raw).decode()
    effects = parse_effects(
        (FIXTURES / "sample-effects-appropriation-2002.html").read_bytes(), identifier
    )
    for row in effects:
        row["publication_date"] = "2013-06-28"
        row["source_url"] = "https://www.irishstatutebook.ie/eli/2013/act/20/enacted/en/html"
        row["directory_url"] = "https://www.irishstatutebook.ie/isbc/2002_28.html"
    data = json.dumps(
        {
            "legalize_ie": 1,
            "identifier": identifier,
            "metadata": encoded,
            "versions": [
                {
                    "format": "enacted",
                    "url": "https://www.irishstatutebook.ie/eli/2002/act/28/enacted/en/html",
                    "data": encoded,
                }
            ],
            "effects": effects,
        }
    ).encode()
    norm = history._parse_on(data, date(2026, 10, 8))
    restored = load_norma_from_json(save_structured_json(tmp_path, norm))
    key = "legislation_directory_corrections"
    assert json.loads(dict(restored.metadata.extra)[key]) == [effects[0]]
    rendered = render_norm_at_date(restored.metadata, restored.blocks, date(2026, 10, 8))
    frontmatter = yaml.safe_load(rendered.split("---", 2)[1])
    correction = json.loads(frontmatter[key])[0]
    assert correction == effects[0]
    assert correction["directory_source_id"] == "IE-1990-act-25"
    assert correction["directory_commencement"] == "21 December 1990"
    assert correction["source_id"] == "IE-2013-act-20"
    assert correction["effective_date"] == "2014-03-07"
    assert correction["source_correction"].endswith("/section/26/enacted/en/html")
    assert [(reform.norm_id, reform.date) for reform in restored.reforms] == [
        (identifier, date(2002, 12, 13)),
        ("IE-2013-act-20", date(2013, 6, 28)),
    ]


def test_source_cache_invalidates_bytes_code_and_due_status_changes(tmp_path, monkeypatch):
    raw = envelope(effects=[effect(whole_repeal=True, effective_date="2099-01-01")])
    norm = history._parse(raw)
    path = save_structured_json(tmp_path, norm)
    history.save_source_stamp(path, raw)
    cached = history.cached_norm_for_text(path, raw)
    assert cached.blocks == norm.blocks
    assert cached.reforms == norm.reforms
    assert history.cached_norm_for_text(path, raw + b" ") is None
    with monkeypatch.context() as changed:
        changed.setattr(history, "_parser_revision", lambda: "changed-code")
        assert history.cached_norm_for_text(path, raw) is None
    stamp_path = tmp_path / "source-stamps" / path.name
    stamp = json.loads(stamp_path.read_text())
    assert stamp["next_status_date"] == "2099-01-01"
    stamp["next_status_date"] = date.today().isoformat()
    stamp_path.write_text(json.dumps(stamp))
    assert history.cached_norm_for_text(path, raw) is None


def test_bootstrap_reparses_existing_json_when_parser_revision_changes(tmp_path, monkeypatch):
    from legalize.fetcher.ie.client import ISBClient
    from legalize.pipeline import generic_fetch_one

    raw = envelope()
    norm = history._parse(raw)
    old = replace(norm, metadata=replace(norm.metadata, title="Stale parsed title"))
    path = save_structured_json(tmp_path, old)
    monkeypatch.setattr(history, "_parser_revision", lambda: "old-parser")
    history.save_source_stamp(path, raw)
    config = Config(countries={"ie": CountryConfig(data_dir=str(tmp_path))})
    calls = []

    def get_text(self, identifier, meta_data=None):
        calls.append(identifier)
        return raw

    monkeypatch.setattr(ISBClient, "get_text", get_text)
    monkeypatch.setattr(
        ISBClient,
        "get_metadata",
        lambda self, identifier: (FIXTURES / "sample-environment-2015.xml").read_bytes(),
    )
    assert generic_fetch_one(config, "ie", IDENTIFIER).metadata.title == "Stale parsed title"
    assert calls == []
    monkeypatch.setattr(history, "_parser_revision", lambda: "new-parser")
    assert generic_fetch_one(config, "ie", IDENTIFIER).metadata.title == norm.metadata.title
    assert generic_fetch_one(config, "ie", IDENTIFIER).metadata.title == norm.metadata.title
    assert calls == [IDENTIFIER]


def test_missing_publication_date_is_not_replaced_by_commencement():
    raw = envelope(effects=[effect(publication_date=None, effective_date="2020-01-01")])
    parsed = history._parse(raw)
    assert [r.norm_id for r in parsed.reforms] == [IDENTIFIER]
    [entry] = json.loads(dict(parsed.metadata.extra)["undated_amendments"])
    assert entry["source_id"] == "IE-2020-act-1" and "no single publication date" in entry["reason"]


@pytest.mark.parametrize("published", [None, "2000-01-01"])
def test_undatable_effects_are_listed_never_committed(published):
    parsed = history._parse(envelope(effects=[effect(publication_date=published)]))
    assert [r.norm_id for r in parsed.reforms] == [IDENTIFIER]
    [entry] = json.loads(dict(parsed.metadata.extra)["undated_amendments"])
    assert entry["source_id"] == "IE-2020-act-1"


def test_pending_repeal_does_not_repeal_current_law():
    from legalize.models import NormStatus

    pending = envelope(effects=[effect(whole_repeal=True, pending=True)])
    assert history._parse(pending).metadata.status is NormStatus.IN_FORCE
    active = envelope(effects=[effect(whole_repeal=True, effective_date="2020-01-01")])
    assert history._parse(active).metadata.status is NormStatus.REPEALED


def test_delayed_repeal_changes_status_on_commencement_without_invented_publication():
    raw = envelope(effects=[effect(whole_repeal=True, effective_date="2022-01-01")])
    parsed = history._parse(raw)
    assert [reform.status for reform in parsed.reforms] == [
        NormStatus.IN_FORCE,
        NormStatus.IN_FORCE,
        NormStatus.REPEALED,
    ]
    activation = parsed.reforms[-1]
    assert activation.date == date(2022, 1, 1)
    assert activation.norm_id == "effective-IE-2020-act-1@2022-01-01"
    assert activation.has_source_date is False


def test_pdf_cover_date_is_not_a_publication_date(monkeypatch):
    from legalize.fetcher.ie import pdf

    monkeypatch.setattr(
        pdf,
        "parse_revised_pdf",
        lambda _: ([Paragraph("parrafo", "Archived text")], date(2021, 4, 1)),
    )
    raw = envelope(
        versions=[
            {
                "format": "revised_pdf",
                "url": "https://source.test/archive.pdf?versionId=verified",
                "catalog_date": "2021-04-02",
                "data": base64.b64encode(b"archived PDF").decode(),
            }
        ]
    )
    parsed = history._parse(raw)
    assert parsed.reforms[-1].date == date(2021, 4, 1)
    assert parsed.reforms[-1].has_source_date is False
    assert parsed.blocks[0].versions[-1].text_state is TextState.POINT_IN_TIME
    assert parsed.blocks[0].versions[-1].publication_date == parsed.metadata.publication_date

    # A consolidation cannot predate the Act it purports to consolidate.
    monkeypatch.setattr(
        pdf,
        "parse_revised_pdf",
        lambda _: ([Paragraph("parrafo", "Wrong source")], date(2000, 1, 1)),
    )
    [gap] = json.loads(dict(history._parse(raw + b" ").metadata.extra)["source_version_gaps"])
    assert "consolidation cutoff predates the original Act" in gap["reason"]


def test_amending_instrument_closure_is_transitive_and_fails_closed(tmp_path, monkeypatch):
    from legalize.fetcher.ie import bootstrap
    from legalize.pipeline import NothingPublished

    original = history._parse(envelope(effects=[effect("IE-2020-si-1")]))
    config = Config(countries={"ie": CountryConfig(data_dir=str(tmp_path))})
    save_structured_json(tmp_path, original)
    calls = []

    def fetch(config, country, identifier):
        calls.append(identifier)
        references = (
            (Reform(date(2021, 1, 1), "IE-2021-si-2", ()),) if identifier.endswith("si-1") else ()
        )
        norm = replace(
            original, metadata=replace(original.metadata, identifier=identifier), reforms=references
        )
        save_structured_json(tmp_path, norm)
        return norm

    monkeypatch.setattr(bootstrap, "generic_fetch_one", fetch)
    assert bootstrap.fetch_dependencies(config, [IDENTIFIER]) == sorted(
        [IDENTIFIER, "IE-2020-si-1", "IE-2021-si-2"]
    )
    assert calls == ["IE-2020-si-1", "IE-2021-si-2"]
    monkeypatch.setattr(bootstrap, "generic_fetch_one", lambda *args: None)
    with pytest.raises(NothingPublished, match="amendment sources unavailable"):
        bootstrap.fetch_dependencies(config, [IDENTIFIER])


def test_source_storage_preserves_nested_lists_and_current_text(tmp_path):
    from legalize.storage import load_norma_from_json

    norm = history._parse(envelope())
    previous = norm.blocks[0].versions[0]
    paragraphs = (
        Paragraph("parrafo", "    - (i) Nested legal point"),
        Paragraph("legal_quote", "> First paragraph\n\n> Second paragraph"),
    )
    latest = replace(
        previous, norm_id="revised-source", effective_date=date(2021, 1, 1), paragraphs=paragraphs
    )
    norm = replace(norm, blocks=(replace(norm.blocks[0], versions=(previous, latest)),))
    path = save_structured_json(tmp_path, norm)
    assert load_norma_from_json(path).blocks == norm.blocks
    assert json.loads(path.read_text())["articles"][0]["current_text"] == "\n\n".join(
        p.text for p in paragraphs
    )


@pytest.mark.parametrize("committer", [commit_one, commit_all_fast])
def test_all_commit_paths_preserve_effects_between_archived_snapshots(tmp_path, committer):
    metadata = ISBMetadataParser().parse(
        (FIXTURES / "sample-environment-2015.xml").read_bytes(), IDENTIFIER
    )
    original_date = metadata.publication_date
    archived = date(2021, 4, 1)
    current = date(2023, 7, 3)
    archived_id = f"revised-{IDENTIFIER}@{archived}"
    current_id = f"revised-{IDENTIFIER}@{current}"
    versions = (
        Version(
            IDENTIFIER,
            original_date,
            original_date,
            (Paragraph("parrafo", "Original text"),),
            text_state=TextState.AS_ENACTED,
            source=metadata.source,
        ),
        Version(
            archived_id,
            original_date,
            archived,
            (Paragraph("parrafo", "Archived text"),),
            text_state=TextState.POINT_IN_TIME,
            source="https://source.test/archive.pdf",
        ),
        Version(
            current_id,
            original_date,
            current,
            (Paragraph("parrafo", "Current text"),),
            text_state=TextState.CURRENT,
            source="https://source.test/current",
        ),
    )
    reforms = (
        Reform(original_date, IDENTIFIER, ("full-text",)),
        Reform(date(2020, 1, 1), "IE-2020-act-1", ()),
        Reform(archived, archived_id, ("full-text",), has_source_date=False),
        Reform(date(2022, 1, 1), "IE-2022-act-1", ()),
        Reform(date(2022, 1, 1), "IE-2022-act-2", ()),
        Reform(current, current_id, ("full-text",), has_source_date=False),
    )
    norm = ParsedNorm(metadata, (Block("full-text", "document", "", versions),), reforms)
    data, repo = tmp_path / "data", tmp_path / "repo"
    save_structured_json(data, norm)
    config = Config(countries={"ie": CountryConfig(data_dir=str(data), repo_path=str(repo))})
    created = (
        committer(config, "ie", IDENTIFIER) if committer is commit_one else committer(config, "ie")
    )
    assert created == 6
    path = next((repo / "ie").rglob("*.md")).relative_to(repo)
    assert len(path.parts) == 3  # Manifest-compatible sharding.
    shas = subprocess.check_output(
        ["git", "-C", str(repo), "log", "--reverse", "--format=%H", "--", str(path)], text=True
    ).splitlines()
    assert len(shas) == 6  # Effects must be visible to consumers walking this file.
    for index, sha in enumerate(shas):
        content = subprocess.check_output(
            ["git", "-C", str(repo), "show", f"{sha}:{path}"], text=True
        )
        fields = yaml.safe_load(content.split("---", 2)[1])
        assert str(fields["publication_date"]) == str(original_date)
        if index == 0:
            assert "last_amendment" not in fields
        elif 2 <= index <= 4:
            assert "text_state" not in fields
            assert str(fields["last_updated"]) == str(archived)
            assert "Archived text" in content
        if index in {2, 5}:
            message = subprocess.check_output(
                ["git", "-C", str(repo), "show", "-s", "--format=%as%n%B", sha], text=True
            )
            assert "Source-Date:" not in message
            assert message.startswith(str(original_date))
            assert "Source: https://source.test/" in message
    final = (repo / path).read_text()
    assert 'last_amendment: "IE-2022-act-2"' in final
    assert 'text_state: "current"' in final
    if committer is commit_one:
        assert committer(config, "ie", IDENTIFIER) == 0
    else:
        committer(config, "ie")
    assert (
        subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        == shas[-1]
    )
    from legalize.pipeline import HistoryMismatch

    late = Reform(date(2021, 5, 1), "IE-2021-act-99", ())
    save_structured_json(data, replace(norm, reforms=reforms[:3] + (late,) + reforms[3:]))
    with pytest.raises(HistoryMismatch, match="earlier event"):
        if committer is commit_one:
            committer(config, "ie", IDENTIFIER)
        else:
            committer(config, "ie")
    assert (repo / path).read_text() == final

    save_structured_json(
        data, replace(norm, metadata=replace(metadata, title="Corrected source title"))
    )
    with pytest.raises(HistoryMismatch, match="source content changed"):
        if committer is commit_one:
            committer(config, "ie", IDENTIFIER)
        else:
            committer(config, "ie")
    assert (repo / path).read_text() == final


@pytest.mark.parametrize("committer", [commit_one, commit_all_fast])
def test_same_day_effect_does_not_preempt_its_snapshot(tmp_path, committer):
    norm = history._parse(envelope())
    day = date(2023, 7, 3)
    snapshot_id = f"revised-{IDENTIFIER}@{day}"
    snapshot = Version(
        snapshot_id,
        norm.metadata.publication_date,
        day,
        (Paragraph("parrafo", "Revised body"),),
        text_state=TextState.CURRENT,
        source="https://source.test/current",
    )
    norm = replace(
        norm,
        blocks=(replace(norm.blocks[0], versions=norm.blocks[0].versions + (snapshot,)),),
        reforms=norm.reforms
        + (
            Reform(day, "IE-2023-act-1", ()),
            Reform(day, snapshot_id, ("full-text",), has_source_date=False),
        ),
    )
    data, repo = tmp_path / "data", tmp_path / "repo"
    save_structured_json(data, norm)
    config = Config(countries={"ie": CountryConfig(data_dir=str(data), repo_path=str(repo))})
    assert (
        committer(config, "ie", IDENTIFIER) if committer is commit_one else committer(config, "ie")
    ) == 3
    messages = subprocess.check_output(["git", "-C", str(repo), "log", "--format=%B"], text=True)
    assert f"Source-Id: {snapshot_id}" in messages
    path = next((repo / "ie").rglob("*.md")).relative_to(repo)
    previous = subprocess.check_output(
        ["git", "-C", str(repo), "show", f"HEAD~1:{path}"], text=True
    )
    assert "Revised body" not in previous
    assert "Revised body" in (repo / path).read_text()


@pytest.mark.parametrize(
    ("source_format", "expected_status"),
    [("revised_pdf", NormStatus.IN_FORCE), ("current_pdf", NormStatus.REPEALED)],
)
def test_snapshot_on_original_publication_day_keeps_its_body_and_status(
    monkeypatch, source_format, expected_status
):
    from legalize.fetcher.ie import pdf
    from legalize.pipeline import _with_last_amendment
    from legalize.transformer.markdown import render_norm_at_date

    monkeypatch.setattr(
        pdf, "parse_revised_pdf", lambda _: ([Paragraph("parrafo", "Snapshot body")], PUB)
    )
    raw = envelope(
        effects=[effect(whole_repeal=True, effective_date="2021-01-01")],
        versions=[
            {
                "format": source_format,
                "url": "https://source.test/snapshot.pdf",
                "catalog_date": PUB.isoformat(),
                "data": base64.b64encode(b"same-day snapshot").decode(),
            }
        ],
    )
    parsed = history._parse_on(raw, date(2026, 10, 8))
    # Neither dated nor current consolidated text needs an AS_ENACTED status
    # activation; the dated snapshot keeps its own status, CURRENT uses today's.
    assert len(parsed.reforms) == 3
    assert parsed.reforms[0].status is NormStatus.IN_FORCE
    assert all(reform.status is expected_status for reform in parsed.reforms[1:])
    for reform in parsed.reforms[1:]:
        markdown = render_norm_at_date(
            _with_last_amendment(parsed.metadata, reform, parsed.reforms),
            parsed.blocks,
            reform.date,
            source_id=reform.norm_id,
        )
        assert markdown.split("---", 2)[2].endswith("Snapshot body\n")
        assert f'status: "{expected_status.value}"' in markdown
        assert 'source: "https://source.test/snapshot.pdf"' in markdown


@pytest.mark.parametrize("changed_event", ["original", "effect"])
def test_fast_import_rejects_changed_event_publication_dates_before_writing(
    tmp_path, changed_event
):
    from datetime import timedelta
    from legalize.pipeline import HistoryMismatch

    norm = history._parse(envelope(effects=[effect()]))
    data, repo = tmp_path / "data", tmp_path / "repo"
    config = Config(countries={"ie": CountryConfig(data_dir=str(data), repo_path=str(repo))})
    save_structured_json(data, norm)
    assert commit_all_fast(config, "ie") == 2

    def head():
        return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True)

    original_head = head()
    law = next((repo / "ie").rglob("*.md"))
    original_text = law.read_bytes()
    reforms = list(norm.reforms)
    if changed_event == "original":
        revised_date = norm.metadata.publication_date + timedelta(days=1)
        reforms[0] = replace(reforms[0], date=revised_date)
        norm = replace(
            norm,
            metadata=replace(norm.metadata, publication_date=revised_date),
            blocks=tuple(
                replace(
                    block,
                    versions=tuple(
                        replace(version, publication_date=revised_date, effective_date=revised_date)
                        for version in block.versions
                    ),
                )
                for block in norm.blocks
            ),
        )
    else:
        reforms[-1] = replace(reforms[-1], date=reforms[-1].date + timedelta(days=1))
    save_structured_json(data, replace(norm, reforms=tuple(reforms)))
    with pytest.raises(HistoryMismatch, match="publication date changed"):
        commit_all_fast(config, "ie")
    assert head() == original_head
    assert law.read_bytes() == original_text
    assert (
        subprocess.check_output(
            ["git", "-C", str(repo), "rev-list", "--count", "HEAD"], text=True
        ).strip()
        == "2"
    )


def test_each_pinned_layout_correction_has_its_evidence():
    records = json.loads((FIXTURES / "corrected-layouts-evidence.json").read_text())
    pinned = {r["replaced"]["sha256"]: r["corrected"]["sha256"] for r in records}
    assert all(history._CORRECTED_PDF_LAYOUTS[old] == new for old, new in pinned.items())
    for record in records:
        # The replaced file is the snapshot the catalogue dates to the cutoff; the
        # correction is a later re-issue printing the same date.
        assert record["replaced"]["catalog_date"] == record["cutoff"]
        assert record["corrected"]["catalog_date"] > record["cutoff"]
        assert record["basis"]
