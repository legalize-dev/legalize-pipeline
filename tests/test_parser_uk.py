"""Parser tests for UK (legislation.gov.uk CLML)."""

from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path

import pytest
import requests

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

    def test_entry_to_norm_id_accepts_si_types(self):
        assert _entry_to_norm_id("http://www.legislation.gov.uk/id/uksi/2024/1") == "uksi-2024-1"
        assert _entry_to_norm_id("http://www.legislation.gov.uk/id/ssi/2020/55") == "ssi-2020-55"
        assert _entry_to_norm_id("http://www.legislation.gov.uk/id/wsi/2019/51") == "wsi-2019-51"
        assert (
            _entry_to_norm_id("http://www.legislation.gov.uk/id/nisr/1996/267") == "nisr-1996-267"
        )
        assert (
            _entry_to_norm_id("http://www.legislation.gov.uk/id/nisro/1968/218") == "nisro-1968-218"
        )

    def test_entry_to_norm_id_filters_unknown_type(self):
        assert _entry_to_norm_id("http://www.legislation.gov.uk/id/eudr/2024/1") is None


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

    def test_extract_made_date_for_si(self):
        """SIs use <ukm:Made Date="..."> instead of <ukm:EnactmentDate>."""
        data = _read_fixture("sample-si-uksi-2020-52.xml")
        assert _extract_enacted_date(data) == "2020-01-20"

    def test_pit_5xx_is_skipped_not_fatal(self, monkeypatch):
        """A 5xx on one point-in-time fetch (e.g. a CloudFront 504 render
        timeout, after retries are exhausted) must skip that one snapshot, not
        discard the enacted base and every PIT already collected.
        """
        client = LegislationGovUkClient()
        enacted = _read_fixture("sample-dpa-2018-enacted.xml")  # enacted 2018-05-23
        pit = _read_fixture("sample-dpa-2018-pit-2023.xml")
        feed = (
            b'<feed xmlns="http://www.w3.org/2005/Atom"'
            b' xmlns:ukm="http://www.legislation.gov.uk/namespaces/metadata">'
            b'<ukm:Effect AffectingURI="http://www.legislation.gov.uk/id/ukpga/2019/1">'
            b'<ukm:InForceDates><ukm:InForce Applied="true" Date="2020-01-01"/>'
            b"</ukm:InForceDates></ukm:Effect>"
            b'<ukm:Effect AffectingURI="http://www.legislation.gov.uk/id/ukpga/2020/1">'
            b'<ukm:InForceDates><ukm:InForce Applied="true" Date="2021-01-01"/>'
            b"</ukm:InForceDates></ukm:Effect></feed>"
        )

        monkeypatch.setattr(client, "get_enacted", lambda nid: enacted)
        monkeypatch.setattr(client, "get_changes_feed", lambda nid, **kw: [feed])

        def fake_get_at_date(nid, target_date):
            if target_date.isoformat() == "2020-01-01":
                resp = requests.Response()
                resp.status_code = 504
                raise requests.HTTPError(response=resp)
            return pit

        monkeypatch.setattr(client, "get_at_date", fake_get_at_date)

        blob = json.loads(client.get_suvestine("ukpga-2018-12"))
        dates = [v["effective_date"] for v in blob["versions"]]
        # The 504 date is dropped; the enacted base and the healthy PIT both
        # survive, and get_suvestine does not raise.
        assert dates == ["2018-05-23", "2021-01-01"]


# ─── Statutory instruments ────────────────────────────────────


class TestSIMetadata:
    """Metadata parsing for all five SI types."""

    def test_uksi_metadata(self):
        data = _read_fixture("sample-si-uksi-2020-52.xml")
        meta = UKMetadataParser().parse(data, "uksi-2020-52")
        assert (
            meta.title
            == "The Veterinary Surgeons (Recognition of University Degree) (Surrey) Order of Council 2020"
        )
        assert meta.country == "uk"
        assert meta.jurisdiction is None  # state-level
        assert meta.rank == "statutory-instrument"
        assert meta.publication_date.isoformat() == "2020-01-20"
        assert meta.source == "https://www.legislation.gov.uk/uksi/2020/52"

    def test_ssi_metadata(self):
        data = _read_fixture("sample-si-ssi-2002-519.xml")
        meta = UKMetadataParser().parse(data, "ssi-2002-519")
        assert meta.jurisdiction == "uk-sct"
        assert meta.rank == "scottish-statutory-instrument"
        assert meta.publication_date.isoformat() == "2002-11-25"

    def test_wsi_metadata(self):
        data = _read_fixture("sample-si-wsi-2026-14.xml")
        meta = UKMetadataParser().parse(data, "wsi-2026-14")
        assert meta.jurisdiction == "uk-wls"
        assert meta.rank == "welsh-statutory-instrument"

    def test_nisr_metadata(self):
        data = _read_fixture("sample-si-nisr-1996-267.xml")
        meta = UKMetadataParser().parse(data, "nisr-1996-267")
        assert meta.jurisdiction == "uk-nir"
        assert meta.rank == "ni-statutory-rule"

    def test_nisro_metadata(self):
        data = _read_fixture("sample-si-nisro-1968-218.xml")
        meta = UKMetadataParser().parse(data, "nisro-1968-218")
        assert meta.jurisdiction == "uk-nir"
        assert meta.rank == "ni-statutory-rule-or-order"
        assert meta.title == "The Criminal Appeal (Northern Ireland) Rules 1968"

    def test_si_filepath_routing(self):
        """SIs route to the same jurisdiction directories as Acts."""
        uksi = UKMetadataParser().parse(_read_fixture("sample-si-uksi-2020-52.xml"), "uksi-2020-52")
        ssi = UKMetadataParser().parse(_read_fixture("sample-si-ssi-2002-519.xml"), "ssi-2002-519")
        wsi = UKMetadataParser().parse(_read_fixture("sample-si-wsi-2026-14.xml"), "wsi-2026-14")
        nisr = UKMetadataParser().parse(
            _read_fixture("sample-si-nisr-1996-267.xml"), "nisr-1996-267"
        )
        nisro = UKMetadataParser().parse(
            _read_fixture("sample-si-nisro-1968-218.xml"), "nisro-1968-218"
        )
        assert norm_to_filepath(uksi) == "uk/uksi-2020-52.md"
        assert norm_to_filepath(ssi) == "uk-sct/ssi-2002-519.md"
        assert norm_to_filepath(wsi) == "uk-wls/wsi-2026-14.md"
        assert norm_to_filepath(nisr) == "uk-nir/nisr-1996-267.md"
        assert norm_to_filepath(nisro) == "uk-nir/nisro-1968-218.md"


class TestSITextParser:
    def test_uksi_parses_sections(self):
        data = _read_fixture("sample-si-uksi-2020-52.xml")
        blocks = UKTextParser().parse_text(data)
        assert len(blocks) >= 2
        assert all(len(b.versions) == 1 for b in blocks)

    def test_nisro_parses_schedules(self):
        """nisro-1968-218 has 3 schedules."""
        data = _read_fixture("sample-si-nisro-1968-218.xml")
        blocks = UKTextParser().parse_text(data)
        assert len(blocks) >= 10
        assert any(b.block_type == "schedule-heading" for b in blocks)

    def test_si_with_tables_renders_schedule_tables(self):
        """uksi-2013-488 has 20 XHTML tables in ScheduleBody.

        Bare ``<Tabular>`` children of ``<ScheduleBody>`` (outside the
        usual ``<P1>`` envelope) must each render as a pipe-table block;
        previously the section walker descended into them looking for
        sections, found none, and the schedule body was lost.
        """
        data = _read_fixture("sample-si-uksi-2013-488-tables.xml")
        blocks = UKTextParser().parse_text(data)
        schedule_tables = [b for b in blocks if b.block_type == "schedule-table"]
        # 20 tables in the fixture's single Schedule.
        assert len(schedule_tables) == 20
        # Each table should carry pipe-table syntax (``| col | col |``).
        first = schedule_tables[0]
        rendered = " ".join(p.text for v in first.versions for p in v.paragraphs)
        assert "|" in rendered

    def test_si_schedule_titleblock_subtitle_renders(self):
        """uksi-2013-488 nests Schedule's Title under ``<TitleBlock>``.

        Newer CLML wraps Number/Title inside ``<TitleBlock>``. The
        schedule heading must still pick up "Designated Bodies" even
        though it sits one element deeper than the flat layout.
        """
        data = _read_fixture("sample-si-uksi-2013-488-tables.xml")
        blocks = UKTextParser().parse_text(data)
        schedule_heading = next((b for b in blocks if b.block_type == "schedule-heading"), None)
        assert schedule_heading is not None
        text = " ".join(p.text for v in schedule_heading.versions for p in v.paragraphs)
        assert "Designated Bodies" in text

    def test_si_forms_in_schedule_body_render(self):
        """nisro-1968-218 attaches 21 court-procedure forms to its Schedule.

        Each ``<Form>`` carries Number / TitleBlock / Reference / Figure.
        Previously the parser descended into the Form via the else
        clause of ``_walk_recursive``, found no ``<P1>``, and emitted
        nothing — losing every form.
        """
        data = _read_fixture("sample-si-nisro-1968-218.xml")
        blocks = UKTextParser().parse_text(data)
        forms = [b for b in blocks if b.block_type == "form"]
        assert len(forms) == 21
        first = forms[0]
        text = " ".join(p.text for v in first.versions for p in v.paragraphs)
        assert "FORM 1" in text
        # TitleBlock subtitles should render at h4 (## not # so we look at
        # the underlying paragraph css class).
        title_paragraphs = [p for v in first.versions for p in v.paragraphs if p.css_class == "h4"]
        assert title_paragraphs, "Form's TitleBlock subtitle should produce h4 paragraphs"

    def test_si_no_leftover_clml_tags(self):
        """Rendered SI output must not leak raw XML."""
        data = _read_fixture("sample-si-uksi-2020-52.xml")
        meta = UKMetadataParser().parse(data, "uksi-2020-52")
        blocks = UKTextParser().parse_text(data)
        md = render_norm_at_date(meta, blocks, meta.publication_date, include_all=True)
        assert md.startswith("---\n")
        assert "<Legislation" not in md
        assert "<ukm:" not in md
        assert "xmlns:" not in md

    def test_uksi_1996_690_p_body_with_p2_regulations_renders(self):
        """SI body uses ``<P><Text/><P2>regulation</P2>+</P>`` (fee amender).

        Regression: before PR #1, this shape produced 0 blocks because
        ``_render_plain_paragraph`` only read direct ``<Text>`` children of
        ``<P>``. uksi-1996-690 has an empty ``<Text/>`` at the head and the
        regulations live in ``<P2>`` siblings inside the same ``<P>``.
        """
        data = _read_fixture("sample-si-uksi-1996-690.xml")
        blocks = UKTextParser().parse_text(data)
        assert blocks, "0 blocks would crash the bootstrap"
        text = " ".join(p.text for b in blocks for v in b.versions for p in v.paragraphs)
        assert "These Regulations may be cited as" in text
        assert "£53.00" in text and "£58.00" in text

    def test_uksi_2012_1866_p_body_with_block_amendment_renders(self):
        """SI body is ``<P><BlockAmendment>…</BlockAmendment><AppendText>.</AppendText></P>``.

        Regression: before PR #1, this shape produced 0 blocks. The
        BlockAmendment is the entire substantive content of the
        resolution; ``AppendText`` is just a trailing "." that we now
        suppress.
        """
        data = _read_fixture("sample-si-uksi-2012-1866.xml")
        blocks = UKTextParser().parse_text(data)
        assert blocks, "0 blocks would crash the bootstrap"
        text = " ".join(p.text for b in blocks for v in b.versions for p in v.paragraphs)
        assert "relevant percentage to be applied each April" in text
        # The trailing "." AppendText must not surface as its own paragraph.
        for b in blocks:
            for v in b.versions:
                for p in v.paragraphs:
                    assert p.text.strip() != ".", f"orphan AppendText '.' in block {b.id}"

    def test_si_secondary_preamble_renders_in_preamble_block(self):
        """SIs use ``<SecondaryPreamble>`` not ``<Preamble>``.

        The enacting text / resolution must end up in the preamble block.
        """
        data = _read_fixture("sample-si-uksi-1996-690.xml")
        blocks = UKTextParser().parse_text(data)
        preamble = next((b for b in blocks if b.block_type == "preamble"), None)
        assert preamble is not None
        text = " ".join(p.text for v in preamble.versions for p in v.paragraphs)
        assert "Secretary of State for Trade and Industry" in text
        # SI prelim dates land in the preamble.
        assert "Made: 7th March 1996" in text
        assert "Laid before Parliament: 11th March 1996" in text
        assert "Coming into force: 8th April 1996" in text

    def test_si_signed_section_emits_dedicated_block(self):
        """`<SignedSection>` becomes a separate block with signee details."""
        data = _read_fixture("sample-si-uksi-1996-690.xml")
        blocks = UKTextParser().parse_text(data)
        signed = next((b for b in blocks if b.block_type == "signatory"), None)
        assert signed is not None
        text = " ".join(p.text for v in signed.versions for p in v.paragraphs)
        assert "John M Taylor" in text
        assert "Parliamentary Under Secretary of State" in text
        assert "5th March 1996" in text
        # Multi-signatory: the Treasury lead-in and the Lords Commissioners.
        assert "We consent," in text
        assert "Derek Conway" in text

    def test_si_explanatory_notes_emit_dedicated_block(self):
        """`<ExplanatoryNotes>` becomes a block with the disclaimer, summary,
        and every nested sub-paragraph that explains the regulation changes.

        Regression: previously the body-level ``<P>`` carrying a lead-in
        ``<Text>`` followed by ``<P2>`` siblings only emitted the lead-in,
        silently dropping every fee-change sub-paragraph. The structural
        decision in ``_render_plain_paragraph`` must be local to each
        ``<P>``, not based on the shared builder's accumulated state.
        """
        data = _read_fixture("sample-si-uksi-1996-690.xml")
        blocks = UKTextParser().parse_text(data)
        notes = next((b for b in blocks if b.block_type == "explanatory-notes"), None)
        assert notes is not None
        text = " ".join(p.text for v in notes.versions for p in v.paragraphs)
        assert "(This note is not part of the Regulations)" in text
        assert "These Regulations amend the fees" in text
        # Sub-paragraphs nested under the lead-in `<P><Text>…</Text><P2>…</P2>` envelope.
        assert "£58.00 per hour" in text
        assert "£70.00 per hour" in text
        assert "£11.50 per hour" in text
        assert "for examination staff" in text

    def test_si_footnotes_emit_dedicated_block(self):
        """Top-level `<Footnotes>` become a footnote-definition block."""
        data = _read_fixture("sample-si-uksi-2012-1866.xml")
        blocks = UKTextParser().parse_text(data)
        footnotes = next((b for b in blocks if b.block_type == "footnotes"), None)
        assert footnotes is not None
        text = " ".join(p.text for v in footnotes.versions for p in v.paragraphs)
        # GitHub-style footnote definitions, one per ukm:Footnote id.
        assert "[^f00001]:" in text
        assert "[^f00002]:" in text
        assert "[^f00003]:" in text

    def test_si_footnote_refs_render_in_body(self):
        """`<FootnoteRef Ref="…"/>` markers must survive inline in body text.

        Without the inline marker the body silently drops the reference and
        leaves the `[^id]: …` definitions in the Footnotes block dangling
        with nothing tying them back. Lawyer-visible regression that
        ``_render_footnotes`` alone (PR #61's original scope) cannot fix.
        """
        data = _read_fixture("sample-si-uksi-2012-1866.xml")
        blocks = UKTextParser().parse_text(data)
        # The body of this SI is a single `<Resolution>` carrying three
        # FootnoteRefs against citations of the 1948 Act, the 1981 Act,
        # and the 7 March 2005 Resolution.
        body_text = " ".join(
            p.text
            for b in blocks
            if b.block_type not in ("footnotes",)
            for v in b.versions
            for p in v.paragraphs
        )
        assert "[^f00001]" in body_text
        assert "[^f00002]" in body_text
        assert "[^f00003]" in body_text

    def test_si_with_zero_p1_blocks_still_emits_content(self):
        """Regression: SI with no `<P1>` and no schedules must still parse.

        Both fixtures here have ``NumberOfProvisions="0"``, no schedules,
        and no ``<P1>`` elements. Before PR #1 they returned 0 blocks
        and crashed the bootstrap at ``bootstrap.py:225``.
        """
        for fixture in ("sample-si-uksi-1996-690.xml", "sample-si-uksi-2012-1866.xml"):
            data = _read_fixture(fixture)
            blocks = UKTextParser().parse_text(data)
            assert blocks, f"{fixture}: 0 blocks would crash the bootstrap"

    def test_pre_1988_made_date_falls_back_to_year(self):
        """Pre-1988 SIs carry only `<ukm:Year>` — no Made/Laid/EnactmentDate.

        Previously the publication date fell back to ``date.today()``,
        stamping every pre-1988 SI's ``last_updated`` field with the
        build date and leaking it into the git history.
        """
        from datetime import date

        from legalize.fetcher.uk.parser import _effective_date_from_root
        from lxml import etree

        data = _read_fixture("sample-si-nisro-1968-218.xml")
        root = etree.fromstring(data)
        assert _effective_date_from_root(root) == date(1968, 1, 1)

    def test_si_block_id_stable_across_multi_version_snapshots(self):
        """Anonymous P/heading blocks must share an id across version XMLs.

        Multi-version SIs replay the same logical block across several
        point-in-time XMLs. A fallback id derived from ``sourceline``
        drifts when surrounding markup shifts, splintering the version
        timeline into multiple single-version blocks. The fallback must
        be derived from stable structure (ancestor id + sibling index),
        not file-line position.
        """
        # Synthesise two version XMLs where the same logical <P> appears
        # at different sourcelines. Both wrap the <P> inside a Schedule
        # with a stable id, so the per-version block ids must collide.
        v1 = (
            '<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation">'
            '<Secondary><Body><Schedule id="schedule-1"><ScheduleBody>'
            "<P><Text>Shared paragraph.</Text></P>"
            "</ScheduleBody></Schedule></Body></Secondary></Legislation>"
        ).encode()
        v2 = (
            '<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation">'
            '<Secondary>\n\n\n<Body>\n\n<Schedule id="schedule-1">\n<ScheduleBody>\n'
            "<P><Text>Shared paragraph.</Text></P>\n"
            "</ScheduleBody></Schedule></Body></Secondary></Legislation>"
        ).encode()
        blob = {
            "norm_id": "uksi-2020-1",
            "versions": [
                {
                    "effective_date": "2020-01-01",
                    "affecting_uri": None,
                    "xml_b64": base64.b64encode(v1).decode("ascii"),
                },
                {
                    "effective_date": "2021-01-01",
                    "affecting_uri": "http://example/affecting",
                    "xml_b64": base64.b64encode(v2).decode("ascii"),
                },
            ],
        }
        blocks = UKTextParser().parse_text(json.dumps(blob).encode())
        prose_blocks = [b for b in blocks if b.block_type == "prose"]
        # Both snapshots carry the same logical paragraph → one block, two
        # versions (collapsed to one if content is identical).
        assert len(prose_blocks) == 1, (
            f"expected one prose block across versions, got {len(prose_blocks)}: "
            f"{[b.id for b in prose_blocks]}"
        )
