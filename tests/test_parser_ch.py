"""Tests for the Switzerland Fedlex parser (country=ch).

Covers the five research fixtures (Constitution, ZGB, DBG tax law, an
ordinary Bundesgesetz, and a recent Verordnung) and exercises the key
formatting constructs flagged in RESEARCH-CH.md §0.4:

- Akoma Ntoso structural hierarchy (book → level → article)
- Inline formatting (``<b>`` / ``<i>`` / ``<sup>`` / ``<br>``)
- Cross-references (``<ref>``)
- Block lists (``<blockList>`` / ``<item>``)
- Tables (``<table>`` with rowspan/colspan)
- Footnotes (``<authorialNote>`` → Markdown ``[^n]``)
- Placeholder artefacts (``<placeholder>`` stripped)
- Image references (dropped, counted)
- Multi-language FRBR names (titles_by_lang extra)
- Multi-version envelope parsing
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from legalize.countries import get_metadata_parser, get_text_parser
from legalize.fetcher.ch.client import eli_url_to_norm_id, norm_id_to_eli_url
from legalize.fetcher.ch.parser import (
    FedlexMetadataParser,
    FedlexTextParser,
    _rank_from_title,
)
from legalize.models import Rank

FIXTURES = Path(__file__).parent / "fixtures" / "ch"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture(scope="module")
def text_parser() -> FedlexTextParser:
    return FedlexTextParser()


@pytest.fixture(scope="module")
def meta_parser() -> FedlexMetadataParser:
    return FedlexMetadataParser(language="de")


# ─── Country registry dispatch ──────────────────────────────────────────────


def test_registry_dispatch() -> None:
    tp = get_text_parser("ch")
    mp = get_metadata_parser("ch")
    assert isinstance(tp, FedlexTextParser)
    assert isinstance(mp, FedlexMetadataParser)


# ─── ELI URI helpers ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "uri,expected",
    [
        ("https://fedlex.data.admin.ch/eli/cc/1999/404", "cc-1999-404"),
        ("https://fedlex.data.admin.ch/eli/cc/24/233_245_233", "cc-24-233_245_233"),
        ("https://fedlex.data.admin.ch/eli/cc/2020/0937_cc", "cc-2020-0937"),
        ("https://fedlex.data.admin.ch/eli/cc/1991/1184_1184_1184", "cc-1991-1184_1184_1184"),
    ],
)
def test_eli_url_to_norm_id(uri: str, expected: str) -> None:
    assert eli_url_to_norm_id(uri) == expected


@pytest.mark.parametrize(
    "norm_id,expected",
    [
        ("cc-1999-404", "https://fedlex.data.admin.ch/eli/cc/1999/404"),
        ("cc-24-233_245_233", "https://fedlex.data.admin.ch/eli/cc/24/233_245_233"),
        ("cc-1991-1184_1184_1184", "https://fedlex.data.admin.ch/eli/cc/1991/1184_1184_1184"),
    ],
)
def test_norm_id_to_eli_url(norm_id: str, expected: str) -> None:
    assert norm_id_to_eli_url(norm_id) == expected


def test_norm_id_round_trip() -> None:
    for uri in (
        "https://fedlex.data.admin.ch/eli/cc/1999/404",
        "https://fedlex.data.admin.ch/eli/cc/1991/1184_1184_1184",
        "https://fedlex.data.admin.ch/eli/cc/24/233_245_233",
    ):
        assert norm_id_to_eli_url(eli_url_to_norm_id(uri)) == uri


# ─── Filesystem-safe identifier ─────────────────────────────────────────────


def test_identifier_is_filesystem_safe() -> None:
    # Legacy ELIs keep underscores but must never contain OS-reserved chars
    forbidden = set(':\\/*?"<>| ')
    for norm_id in ("cc-1999-404", "cc-24-233_245_233", "cc-1991-1184_1184_1184"):
        assert not (forbidden & set(norm_id)), f"unsafe id: {norm_id}"


# ─── Rank inference ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Bundesverfassung der Schweizerischen Eidgenossenschaft", "bundesverfassung"),
        ("Bundesgesetz über die direkte Bundessteuer", "bundesgesetz"),
        ("Schweizerisches Zivilgesetzbuch", "bundesgesetz"),
        ("Schweizerisches Strafgesetzbuch", "bundesgesetz"),
        ("Bundesbeschluss über den Nationalstrassenbau", "bundesbeschluss"),
        ("Verordnung über das Verbot der Verhüllung", "verordnung"),
        ("Reglement der Aufsichtsbehörde", "reglement"),
        ("Zivilprozessordnung", "bundesgesetz"),
    ],
)
def test_rank_from_title(title: str, expected: str) -> None:
    assert _rank_from_title(title) == expected


# ─── Metadata: Federal Constitution (cc/1999/404) ───────────────────────────


def test_constitution_metadata(meta_parser: FedlexMetadataParser) -> None:
    raw = _load("sample-constitution.xml")
    m = meta_parser.parse(raw, "cc-1999-404")
    assert m.country == "ch"
    assert m.identifier == "cc-1999-404"
    assert m.rank == Rank("bundesverfassung")
    assert m.title.startswith("Bundesverfassung der Schweizerischen Eidgenossenschaft")
    assert m.short_title == "BV"
    assert m.publication_date == date(1999, 4, 18)
    assert m.source == "https://fedlex.data.admin.ch/eli/cc/1999/404"
    extra = dict(m.extra)
    assert extra["sr_number"] == "101"
    assert extra["entry_into_force"] == "2000-01-01"
    assert extra["applicability_date"] == "2024-03-03"
    # Multilingual parallel titles
    assert extra["title_fr"].startswith("Constitution fédérale")
    assert extra["title_it"].startswith("Costituzione federale")
    assert extra["short_title_fr"] == "Cst."
    assert extra["authoritative"] == "true"


def test_constitution_text(text_parser: FedlexTextParser) -> None:
    raw = _load("sample-constitution.xml")
    blocks = text_parser.parse_text(raw)
    assert len(blocks) == 1
    block = blocks[0]
    assert len(block.versions) == 1
    version = block.versions[0]
    assert version.effective_date == date(2024, 3, 3)
    assert version.norm_id == "cc-1999-404"

    # Research counted 231 articles in the 2022 version and 232 in 2024.
    articles = [p for p in version.paragraphs if p.css_class == "h5"]
    assert 220 <= len(articles) <= 280

    # Exactly one <table> in the 2024 BV (heavy-vehicle road tax schedule).
    tables = [p for p in version.paragraphs if p.css_class == "table"]
    assert len(tables) == 1
    assert tables[0].text.startswith("| ")
    assert "\n| ---" in tables[0].text

    # Structural hierarchy present — h2 titles, h3 chapters, h4 sections.
    h2s = [p for p in version.paragraphs if p.css_class == "h2"]
    h3s = [p for p in version.paragraphs if p.css_class == "h3"]
    assert h2s, "constitution must have at least one top-level title"
    assert h3s, "constitution must have chapters"


# ─── Metadata: Civil Code (ZGB) — legacy ELI with underscores ───────────────


def test_civil_code_metadata(meta_parser: FedlexMetadataParser) -> None:
    raw = _load("sample-code.xml")
    m = meta_parser.parse(raw, "cc-24-233_245_233")
    assert m.identifier == "cc-24-233_245_233"
    assert m.rank == Rank("bundesgesetz"), "Swiss Civil Code maps to Bundesgesetz"
    assert m.publication_date == date(1907, 12, 10)
    extra = dict(m.extra)
    assert extra["sr_number"] == "210"
    assert extra["entry_into_force"] == "1912-01-01"


def test_civil_code_text_large(text_parser: FedlexTextParser) -> None:
    raw = _load("sample-code.xml")
    blocks = text_parser.parse_text(raw)
    version = blocks[0].versions[0]
    # ~1277 articles per the research doc
    articles = [p for p in version.paragraphs if p.css_class == "h5"]
    assert len(articles) > 1000


# ─── Metadata: DBG direct tax law — tables + images + footnotes ─────────────


def test_dbg_metadata_images_dropped(meta_parser: FedlexMetadataParser) -> None:
    raw = _load("sample-with-tables.xml")
    m = meta_parser.parse(raw, "cc-1991-1184_1184_1184")
    extra = dict(m.extra)
    assert extra["sr_number"] == "642.11"
    # DBG source has 2 <img> elements in the tax-rate tables — we drop them
    # but record the count, never silently.
    assert extra["images_dropped"] == "2"


def test_dbg_tables_render(text_parser: FedlexTextParser) -> None:
    raw = _load("sample-with-tables.xml")
    version = text_parser.parse_text(raw)[0].versions[0]
    tables = [p for p in version.paragraphs if p.css_class == "table"]
    assert len(tables) == 2
    for t in tables:
        assert t.text.startswith("| ")
        assert "\n| ---" in t.text


# ─── Ordinary Bundesgesetz ──────────────────────────────────────────────────


def test_ordinary_law(text_parser: FedlexTextParser, meta_parser: FedlexMetadataParser) -> None:
    raw = _load("sample-ordinary-law.xml")
    m = meta_parser.parse(raw, "cc-2024-620")
    assert m.rank == Rank("bundesgesetz")
    assert m.short_title == "BVVG"
    version = text_parser.parse_text(raw)[0].versions[0]
    # Footnote marker [^n] should appear in the preamble where an
    # authorialNote was nested. The note body renders separately in the
    # Fussnoten section at the end — the preamble must NOT duplicate it.
    preamble_texts = [p.text for p in version.paragraphs if p.css_class == "preamble"]
    assert any("[^1]" in t for t in preamble_texts), "authorialNote marker missing from preamble"
    assert not any(
        t.strip().startswith("[SR ") or t.strip().startswith("[BBl ") for t in preamble_texts
    ), "footnote body leaked as a free-floating preamble paragraph"
    # Cross-references to BV and BBl render as Markdown links — but inside
    # the footnote bodies (which end up in the abs-class block after the
    # Fussnoten heading), not as standalone preamble lines.
    all_texts = [p.text for p in version.paragraphs]
    assert any("](https://fedlex.data.admin.ch/eli/" in t for t in all_texts), (
        "expected at least one external <ref> rendered as a Markdown link"
    )
    # Lettered list items should survive
    list_items = [p for p in version.paragraphs if p.css_class == "list_item"]
    assert list_items, "blockList items must be preserved"
    assert any(p.text.startswith("- a.") for p in list_items)


# ─── Recent Verordnung (2026) ───────────────────────────────────────────────


def test_regulation(meta_parser: FedlexMetadataParser) -> None:
    raw = _load("sample-regulation.xml")
    m = meta_parser.parse(raw, "cc-2026-51")
    assert m.rank == Rank("verordnung")
    assert m.publication_date == date(2026, 1, 28)


# ─── Multi-version envelope ─────────────────────────────────────────────────


def _wrap_envelope(parts: list[tuple[str, bytes]], norm_id: str) -> bytes:
    """Build a minimal <fedlex-multi-version> envelope from inner bodies."""
    chunks: list[bytes] = [
        b"<?xml version='1.0' encoding='UTF-8'?>",
        f"<fedlex-multi-version norm-id='{norm_id}' language='de'>".encode("utf-8"),
    ]
    for effective_date, xml in parts:
        chunks.append(
            f"<version type='consolidation' effective-date='{effective_date}'>".encode("utf-8")
        )
        body = xml
        if body.startswith(b"<?xml"):
            idx = body.find(b"?>")
            if idx >= 0:
                body = body[idx + 2 :].lstrip()
        chunks.append(body)
        chunks.append(b"</version>")
    chunks.append(b"</fedlex-multi-version>")
    return b"\n".join(chunks)


def test_multi_version_envelope(text_parser: FedlexTextParser) -> None:
    inner = _load("sample-regulation.xml")
    envelope = _wrap_envelope(
        [("2026-03-01", inner), ("2026-04-01", inner)],
        norm_id="cc-2026-51",
    )
    blocks = text_parser.parse_text(envelope)
    assert len(blocks) == 1
    block = blocks[0]
    assert len(block.versions) == 2
    assert block.versions[0].effective_date == date(2026, 3, 1)
    assert block.versions[1].effective_date == date(2026, 4, 1)
    # Versions must be ordered oldest → newest
    assert block.versions[0].effective_date < block.versions[1].effective_date


def test_multi_version_metadata_uses_latest(meta_parser: FedlexMetadataParser) -> None:
    inner = _load("sample-regulation.xml")
    envelope = _wrap_envelope(
        [("2026-03-01", inner), ("2026-04-01", inner)],
        norm_id="cc-2026-51",
    )
    m = meta_parser.parse(envelope, "cc-2026-51")
    extra = dict(m.extra)
    # history_from records the earliest version date in the envelope
    assert extra["history_from"] == "2026-03-01"


# ─── Encoding hygiene ───────────────────────────────────────────────────────


def test_no_control_chars_in_output(text_parser: FedlexTextParser) -> None:
    for name in (
        "sample-ordinary-law.xml",
        "sample-regulation.xml",
        "sample-constitution.xml",
        "sample-with-tables.xml",
    ):
        raw = _load(name)
        blocks = text_parser.parse_text(raw)
        for block in blocks:
            for version in block.versions:
                for p in version.paragraphs:
                    for ch in p.text:
                        code = ord(ch)
                        assert not (
                            0x00 <= code <= 0x08
                            or code in (0x0B, 0x0C)
                            or 0x0E <= code <= 0x1F
                            or 0x7F <= code <= 0x9F
                        ), f"control char in {name}: {hex(code)}"


def test_no_placeholder_artefacts(text_parser: FedlexTextParser) -> None:
    # <placeholder ns1:message="E40S10-TAB">[tab]</placeholder> must disappear
    raw = _load("sample-constitution.xml")
    blocks = text_parser.parse_text(raw)
    for block in blocks:
        for version in block.versions:
            for p in version.paragraphs:
                assert "[tab]" not in p.text, "placeholder text leaked to output"
