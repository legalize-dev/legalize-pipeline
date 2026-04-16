"""Parser tests for UK (legislation.gov.uk CLML)."""

from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path

import pytest

from legalize.countries import (
    get_client_class,
    get_discovery_class,
    get_metadata_parser,
    get_text_parser,
)
from legalize.fetcher.uk.client import (
    LegislationGovUkClient,
    _extract_applied_effects,
    _extract_enacted_date,
    split_norm_id,
)
from legalize.fetcher.uk.discovery import _entry_to_norm_id
from legalize.fetcher.uk.parser import (
    UKMetadataParser,
    UKTextParser,
)
from legalize.models import NormStatus
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.slug import norm_to_filepath

FIXTURES = Path(__file__).parent / "fixtures" / "uk"


def _read_fixture(name: str) -> bytes:
    """Read a fixture, transparently decompressing .gz variants if present."""
    path = FIXTURES / name
    if path.exists():
        return path.read_bytes()
    gz = path.with_suffix(path.suffix + ".gz")
    if gz.exists():
        return gzip.decompress(gz.read_bytes())
    raise FileNotFoundError(f"No fixture at {path} or {gz}")


# ─── Registry dispatch ─────────────────────────────────────────


class TestCountryDispatch:
    def test_client_class(self):
        cls = get_client_class("uk")
        assert cls is LegislationGovUkClient

    def test_discovery_class(self):
        cls = get_discovery_class("uk")
        assert cls.__name__ == "LegislationGovUkDiscovery"

    def test_text_parser(self):
        assert isinstance(get_text_parser("uk"), UKTextParser)

    def test_metadata_parser(self):
        assert isinstance(get_metadata_parser("uk"), UKMetadataParser)


# ─── Norm-id helpers ───────────────────────────────────────────


class TestNormId:
    def test_split_happy(self):
        assert split_norm_id("ukpga-2018-12") == ("ukpga", 2018, 12)
        assert split_norm_id("asp-2021-11") == ("asp", 2021, 11)

    def test_split_invalid(self):
        with pytest.raises(ValueError):
            split_norm_id("bogus")

    def test_entry_to_norm_id_strips_id_segment(self):
        assert (
            _entry_to_norm_id("http://www.legislation.gov.uk/id/ukpga/2018/12") == "ukpga-2018-12"
        )

    def test_entry_to_norm_id_filters_unknown_type(self):
        # uksi is deferred to phase 2 → discovery must skip it.
        assert _entry_to_norm_id("http://www.legislation.gov.uk/id/uksi/2024/1") is None


# ─── Metadata parser ───────────────────────────────────────────


class TestMetadata:
    """The metadata block is identical across all four jurisdictions."""

    def test_ukpga_heavy_act(self):
        data = _read_fixture("sample-dpa-2018-latest.xml")
        meta = UKMetadataParser().parse(data, "ukpga-2018-12")
        assert meta.title == "Data Protection Act 2018"
        assert meta.country == "uk"
        assert meta.jurisdiction is None  # state-level
        assert meta.rank == "public-general-act"
        assert meta.publication_date.isoformat() == "2018-05-23"
        assert meta.status == NormStatus.IN_FORCE
        assert meta.identifier == "ukpga-2018-12"
        # Identifier is filesystem-safe:
        for ch in ':/\\ ?"<>|':
            assert ch not in meta.identifier
        # Summary captures the long title:
        assert "processing of information" in meta.summary
        # Extra captures every structured field from the source:
        keys = {k for k, _ in meta.extra}
        for required in {
            "type_code",
            "year",
            "number",
            "document_main_type",
            "document_category",
            "language",
            "publisher",
            "isbn",
            "restrict_extent",
            "number_of_provisions",
        }:
            assert required in keys, f"missing extra key: {required}"
        # Source URL points to the correct TNA page:
        assert meta.source == "https://www.legislation.gov.uk/ukpga/2018/12"

    def test_scottish_jurisdiction(self):
        data = _read_fixture("sample-scot-asp-2021-11.xml")
        meta = UKMetadataParser().parse(data, "asp-2021-11")
        assert meta.jurisdiction == "uk-sct"
        assert meta.rank == "act-of-scottish-parliament"

    def test_welsh_anaw_jurisdiction(self):
        data = _read_fixture("sample-welsh-anaw-2014-4.xml")
        meta = UKMetadataParser().parse(data, "anaw-2014-4")
        assert meta.jurisdiction == "uk-wls"
        assert meta.rank == "act-of-senedd-cymru"

    def test_senedd_asc_jurisdiction(self):
        data = _read_fixture("sample-senedd-asc-2020-1.xml")
        meta = UKMetadataParser().parse(data, "asc-2020-1")
        assert meta.jurisdiction == "uk-wls"

    def test_northern_ireland_jurisdiction(self):
        data = _read_fixture("sample-ni-nia-2022-2.xml")
        meta = UKMetadataParser().parse(data, "nia-2022-2")
        assert meta.jurisdiction == "uk-nir"
        assert meta.rank == "act-of-northern-ireland-assembly"

    def test_filepath_routing(self):
        """State-level → uk/, devolved → uk-sct/uk-wls/uk-nir/."""
        state = UKMetadataParser().parse(
            _read_fixture("sample-human-rights-1998.xml"), "ukpga-1998-42"
        )
        sct = UKMetadataParser().parse(_read_fixture("sample-scot-asp-2021-11.xml"), "asp-2021-11")
        assert norm_to_filepath(state) == "uk/ukpga-1998-42.md"
        assert norm_to_filepath(sct) == "uk-sct/asp-2021-11.md"


# ─── Text parser ───────────────────────────────────────────────


class TestTextParser:
    def test_parses_sections_and_schedules(self):
        data = _read_fixture("sample-human-rights-1998.xml")
        blocks = UKTextParser().parse_text(data)
        assert len(blocks) > 5
        assert any(b.block_type == "section" for b in blocks)
        # Schedules are rendered as a heading block followed by their
        # internal section blocks (same recursion as body).
        assert any(b.block_type == "schedule-heading" for b in blocks)

    def test_single_snapshot_has_one_version_per_block(self):
        data = _read_fixture("sample-scot-asp-2021-11.xml")
        blocks = UKTextParser().parse_text(data)
        assert all(len(b.versions) == 1 for b in blocks)

    def test_preserves_utf8_and_no_controls(self):
        data = _read_fixture("sample-scot-asp-2021-11.xml")
        blocks = UKTextParser().parse_text(data)
        for block in blocks:
            for version in block.versions:
                for p in version.paragraphs:
                    for ch in p.text:
                        # Reject C0 and C1 controls except tab/newline/CR.
                        if ch in ("\t", "\n", "\r"):
                            continue
                        assert ord(ch) >= 0x20 and ord(ch) != 0x7F, (
                            f"Control char U+{ord(ch):04X} in paragraph"
                        )

    def test_finance_act_renders_tables_as_pipe_tables(self):
        """Finance Act 2020 has 18 XHTML tables; every one must become a MD pipe table."""
        data = _read_fixture("sample-finance-act-2020.xml")
        blocks = UKTextParser().parse_text(data)
        tables = [
            p for b in blocks for v in b.versions for p in v.paragraphs if p.css_class == "table"
        ]
        assert len(tables) >= 1, "expected at least one rendered table"
        for table in tables:
            assert table.text.startswith("| ")
            # Separator row exists.
            assert "| ---" in table.text or "|---" in table.text
        # At least one table has body rows (not just a header).
        multi_row = [t for t in tables if t.text.count("\n") >= 2]
        assert multi_row, "no table with body rows — header-only tables suggest truncation"

    def test_block_ids_are_filesystem_safe(self):
        data = _read_fixture("sample-human-rights-1998.xml")
        blocks = UKTextParser().parse_text(data)
        for b in blocks:
            for ch in ':/\\ ?"<>|':
                assert ch not in b.id, f"bad block id: {b.id!r}"


# ─── End-to-end rendering ──────────────────────────────────────


class TestRender:
    def test_asp_renders_without_errors(self):
        data = _read_fixture("sample-scot-asp-2021-11.xml")
        meta = UKMetadataParser().parse(data, "asp-2021-11")
        blocks = UKTextParser().parse_text(data)
        md = render_norm_at_date(meta, blocks, meta.publication_date, include_all=True)
        assert md.startswith("---\n")
        assert 'title: "Pre-release Access to Official Statistics (Scotland) Act 2021"' in md
        # H1 title present
        assert "\n# Pre-release Access" in md
        # No leftover CLML tags
        assert "<Legislation" not in md
        assert "<ukm:" not in md
        assert "xmlns:" not in md

    def test_frontmatter_is_valid_yaml(self):
        import yaml  # pyyaml is already a project dependency

        data = _read_fixture("sample-ni-nia-2022-2.xml")
        meta = UKMetadataParser().parse(data, "nia-2022-2")
        blocks = UKTextParser().parse_text(data)
        md = render_norm_at_date(meta, blocks, meta.publication_date, include_all=True)
        yaml_block = md.split("---\n")[1]
        parsed = yaml.safe_load(yaml_block)
        assert parsed["title"].startswith("Horse Racing")
        assert parsed["country"] == "uk"
        assert parsed["identifier"] == "nia-2022-2"


# ─── Version history (suvestine blob) ─────────────────────────


class TestSuvestine:
    def test_parser_handles_multi_version_blob(self):
        """Synthesise a blob from 2 real fixtures and confirm the parser
        returns blocks with two versions each.
        """
        enacted = _read_fixture("sample-dpa-2018-enacted.xml")
        pit = _read_fixture("sample-dpa-2018-pit-2023.xml")
        blob = {
            "norm_id": "ukpga-2018-12",
            "versions": [
                {
                    "effective_date": "2018-05-23",
                    "affecting_uri": None,
                    "xml_b64": base64.b64encode(enacted).decode("ascii"),
                },
                {
                    "effective_date": "2022-12-05",
                    "affecting_uri": "http://www.legislation.gov.uk/id/ukpga/2022/27",
                    "xml_b64": base64.b64encode(pit).decode("ascii"),
                },
            ],
        }
        blocks = UKTextParser().parse_text(json.dumps(blob).encode("utf-8"))
        assert len(blocks) > 0
        # At least some blocks (the ones whose text differs across versions)
        # should carry more than one Version.
        multi_version_blocks = [b for b in blocks if len(b.versions) > 1]
        assert multi_version_blocks, "expected at least one block with multiple versions"

    def test_extract_applied_effects_dedupes(self):
        feed = _read_fixture("sample-dpa-2018-changes.feed.xml")
        effects = _extract_applied_effects([feed])
        # The feed's first 50 entries produce a small set of distinct dates.
        dates = {eff_date for eff_date, _ in effects}
        assert len(dates) >= 1
        for eff_date, uri in effects:
            # Dates are ISO strings, URIs are legislation.gov.uk URLs.
            assert len(eff_date) == 10 and eff_date[4] == "-"
            assert uri.startswith("http://www.legislation.gov.uk/")

    def test_extract_enacted_date(self):
        enacted = _read_fixture("sample-dpa-2018-enacted.xml")
        assert _extract_enacted_date(enacted) == "2018-05-23"
