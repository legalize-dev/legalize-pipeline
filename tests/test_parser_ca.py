"""Tests for the Canadian federal legislation parser."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from legalize.countries import get_metadata_parser, get_text_parser
from legalize.fetcher.ca.client import _parse_norm_id
from legalize.fetcher.ca.parser import CAMetadataParser, CATextParser
from legalize.models import NormStatus
from legalize.transformer.slug import norm_to_filepath

FIXTURES = Path(__file__).parent / "fixtures" / "ca"

ACT_SMALL = FIXTURES / "sample-act-small.xml"
ACT_MINIMAL = FIXTURES / "sample-act-minimal.xml"
ACT_WITH_TABLES = FIXTURES / "sample-act-with-tables.xml"
ACT_FR = FIXTURES / "sample-act-fr.xml"  # French version of B-9.8
REGULATION = FIXTURES / "sample-regulation.xml"
REGULATION_WITH_TABLES = FIXTURES / "sample-regulation-with-tables.xml"


# ─────────────────────────────────────────────
# norm_id helpers
# ─────────────────────────────────────────────


class TestNormIdHelpers:
    def test_parse_norm_id_act(self):
        lang, cat, fid = _parse_norm_id("eng/acts/A-1")
        assert lang == "eng"
        assert cat == "acts"
        assert fid == "A-1"

    def test_parse_norm_id_regulation(self):
        lang, cat, fid = _parse_norm_id("fra/reglements/SOR-99-129")
        assert lang == "fra"
        assert cat == "reglements"
        assert fid == "SOR-99-129"

    def test_parse_norm_id_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid CA norm_id"):
            _parse_norm_id("invalid")


# ─────────────────────────────────────────────
# Text parser — acts
# ─────────────────────────────────────────────


class TestCATextParserActs:
    def setup_method(self):
        self.parser = CATextParser()

    def test_small_act_returns_one_block(self):
        blocks = self.parser.parse_text(ACT_SMALL.read_bytes())
        assert len(blocks) == 1

    def test_small_act_block_structure(self):
        blocks = self.parser.parse_text(ACT_SMALL.read_bytes())
        block = blocks[0]
        assert block.block_type == "article"
        assert block.id == "body"
        assert len(block.versions) == 1

    def test_small_act_has_sections(self):
        blocks = self.parser.parse_text(ACT_SMALL.read_bytes())
        paras = blocks[0].versions[0].paragraphs
        articles = [p for p in paras if p.css_class == "articulo"]
        assert len(articles) == 25  # B-9.8 has 25 sections

    def test_small_act_has_headings(self):
        blocks = self.parser.parse_text(ACT_SMALL.read_bytes())
        paras = blocks[0].versions[0].paragraphs
        headings = [p for p in paras if p.css_class in ("titulo_tit", "capitulo_tit")]
        assert len(headings) >= 5

    def test_small_act_has_paragraphs(self):
        blocks = self.parser.parse_text(ACT_SMALL.read_bytes())
        paras = blocks[0].versions[0].paragraphs
        assert len(paras) >= 50

    def test_small_act_publication_date(self):
        blocks = self.parser.parse_text(ACT_SMALL.read_bytes())
        pub_date = blocks[0].versions[0].publication_date
        assert isinstance(pub_date, date)
        assert pub_date == date(2003, 1, 1)

    def test_minimal_act_no_body_returns_empty(self):
        """Acts with no <Body> (e.g., repealed stubs) return no blocks."""
        blocks = self.parser.parse_text(ACT_MINIMAL.read_bytes())
        assert blocks == []

    def test_act_with_tables_has_tables(self):
        blocks = self.parser.parse_text(ACT_WITH_TABLES.read_bytes())
        assert len(blocks) == 1
        paras = blocks[0].versions[0].paragraphs
        tables = [p for p in paras if p.css_class == "table"]
        # A-10.6 ships two distinct TableGroups, one nested inside a Schedule's
        # DocumentInternal/Group/Provision wrapper. Both must be recovered.
        assert len(tables) == 2

    def test_cross_references_render_as_absolute_markdown_links(self):
        """XRefExternal → absolute URL to Justice Laws Website (CH/LI/EU convention)."""
        blocks = self.parser.parse_text(ACT_SMALL.read_bytes())
        paras = blocks[0].versions[0].paragraphs
        body = "\n".join(p.text for p in paras)
        assert (
            "[Budget Implementation Act, 1995](https://laws-lois.justice.gc.ca/eng/acts/B-9.8/)"
        ) in body
        assert (
            "[Western Grain Transition Payments Act]"
            "(https://laws-lois.justice.gc.ca/eng/acts/W-7.8/)"
        ) in body

    def test_french_cross_references_use_french_urls(self):
        """French document XRefs must link to the French side of the official site."""
        blocks = self.parser.parse_text(ACT_FR.read_bytes())
        paras = blocks[0].versions[0].paragraphs
        body = "\n".join(p.text for p in paras)
        assert "https://laws-lois.justice.gc.ca/fra/lois/" in body
        # Should NOT leak English URLs into a French document.
        assert "https://laws-lois.justice.gc.ca/eng/" not in body

    def test_enacting_clause_is_preserved(self):
        """Root-level <Introduction><Enacts> ('Her Majesty...') must appear."""
        blocks = self.parser.parse_text(ACT_SMALL.read_bytes())
        paras = blocks[0].versions[0].paragraphs
        body = "\n".join(p.text for p in paras)
        assert "Her Majesty" in body
        assert "Senate and House of Commons" in body

    def test_subsection_marginal_note_is_preserved(self):
        """Section 28's subsections carry marginal notes that must surface in output."""
        blocks = self.parser.parse_text(ACT_SMALL.read_bytes())
        paras = blocks[0].versions[0].paragraphs
        body = "\n".join(p.text for p in paras)
        # "Payments under agreements" is the MarginalNote on subsection (2).
        assert "Payments under agreements" in body
        assert "Deadline for payments" in body

    def test_schedule_editorial_note_is_preserved(self):
        """Schedule II has an editorial <Note> that must render as blockquote."""
        blocks = self.parser.parse_text(ACT_SMALL.read_bytes())
        paras = blocks[0].versions[0].paragraphs
        body = "\n".join(p.text for p in paras)
        assert "Western Grain Transition Payments Act" in body
        # OriginatingRef should appear inline with the schedule heading.
        assert "(Section 29)" in body

    def test_act_with_tables_markdown_format(self):
        blocks = self.parser.parse_text(ACT_WITH_TABLES.read_bytes())
        paras = blocks[0].versions[0].paragraphs
        tables = [p for p in paras if p.css_class == "table"]
        first_table = tables[0].text
        lines = first_table.split("\n")
        # Valid pipe table: header | separator | rows
        assert lines[0].startswith("|") and lines[0].endswith("|")
        assert lines[1].startswith("| ---")
        assert len(lines) >= 3

    def test_act_with_tables_has_schedules(self):
        """Schedules outside <Body> should be parsed."""
        blocks = self.parser.parse_text(ACT_WITH_TABLES.read_bytes())
        paras = blocks[0].versions[0].paragraphs
        schedule_headings = [p for p in paras if p.css_class == "titulo_tit"]
        assert len(schedule_headings) >= 2


# ─────────────────────────────────────────────
# Text parser — regulations
# ─────────────────────────────────────────────


class TestCATextParserRegulations:
    def setup_method(self):
        self.parser = CATextParser()

    def test_regulation_returns_one_block(self):
        blocks = self.parser.parse_text(REGULATION.read_bytes())
        assert len(blocks) == 1

    def test_regulation_has_sections(self):
        blocks = self.parser.parse_text(REGULATION.read_bytes())
        paras = blocks[0].versions[0].paragraphs
        articles = [p for p in paras if p.css_class == "articulo"]
        assert len(articles) == 4  # SOR/99-129 has 4 sections

    def test_regulation_has_defined_terms(self):
        """Defined terms in regulations should be preserved."""
        blocks = self.parser.parse_text(REGULATION.read_bytes())
        paras = blocks[0].versions[0].paragraphs
        # DefinedTermEn should render as italic
        italic_paras = [p for p in paras if "*" in p.text]
        assert len(italic_paras) >= 1

    def test_regulation_with_tables(self):
        blocks = self.parser.parse_text(REGULATION_WITH_TABLES.read_bytes())
        assert len(blocks) == 1
        paras = blocks[0].versions[0].paragraphs
        tables = [p for p in paras if p.css_class == "table"]
        assert len(tables) >= 1


# ─────────────────────────────────────────────
# Metadata parser
# ─────────────────────────────────────────────


class TestCAMetadataParser:
    def setup_method(self):
        self.parser = CAMetadataParser()

    def test_act_metadata_core_fields(self):
        meta = self.parser.parse(ACT_SMALL.read_bytes(), "eng/acts/B-9.8")
        assert meta.country == "ca"
        assert meta.jurisdiction == "ca-en"
        assert meta.rank == "act"
        assert meta.status == NormStatus.IN_FORCE
        assert "Budget Implementation Act" in meta.title

    def test_act_metadata_identifier(self):
        meta = self.parser.parse(ACT_SMALL.read_bytes(), "eng/acts/B-9.8")
        assert meta.identifier == "B-9.8"

    def test_act_metadata_source_url(self):
        meta = self.parser.parse(ACT_SMALL.read_bytes(), "eng/acts/B-9.8")
        assert meta.source == "https://laws-lois.justice.gc.ca/eng/acts/B-9.8/"

    def test_act_metadata_publication_date(self):
        meta = self.parser.parse(ACT_SMALL.read_bytes(), "eng/acts/B-9.8")
        assert isinstance(meta.publication_date, date)
        assert meta.publication_date == date(2003, 1, 1)

    def test_act_metadata_extra_fields(self):
        meta = self.parser.parse(ACT_SMALL.read_bytes(), "eng/acts/B-9.8")
        extra = dict(meta.extra)
        assert extra["lang"] == "en"
        assert "last_amended" in extra
        assert "inforce_start" in extra
        assert "consolidation_date" in extra
        assert extra.get("bill_origin") == "commons"
        # Full metadata contract: as-enacted citation, assent date, lims IDs.
        assert extra.get("annual_statute") == "1995, c. 17"
        assert extra.get("assented_to") == "1995-06-22"
        assert extra.get("lims_id") == "35135"
        assert extra.get("fid") == "35135"
        assert extra.get("consolidated_number_official") == "no"

    def test_act_long_title_captured_in_summary(self):
        """LongTitle ('An Act to ...') must go into summary, not be dropped."""
        meta = self.parser.parse(ACT_SMALL.read_bytes(), "eng/acts/B-9.8")
        assert "An Act to implement" in meta.summary
        # Also mirrored in extra for structured consumers.
        assert "An Act to implement" in dict(meta.extra).get("long_title", "")

    def test_regulation_metadata(self):
        meta = self.parser.parse(REGULATION.read_bytes(), "eng/regulations/SOR-99-129")
        assert meta.country == "ca"
        assert meta.jurisdiction == "ca-en"
        assert meta.rank == "regulation"
        assert meta.identifier == "SOR-99-129"
        # Regulations have enabling authority as department, plain text only.
        assert "INSURANCE COMPANIES ACT" in meta.department
        assert "](" not in meta.department  # no markdown link inside YAML field

    def test_regulation_enabling_authority_id_captured_separately(self):
        """The enabling-act identifier goes to extra.enabling_authority_id."""
        meta = self.parser.parse(REGULATION.read_bytes(), "eng/regulations/SOR-99-129")
        extra = dict(meta.extra)
        # SOR/99-129 is enabled by the Insurance Companies Act (I-11.8).
        assert extra.get("enabling_authority_id") == "I-11.8"

    def test_regulation_metadata_source_url(self):
        meta = self.parser.parse(REGULATION.read_bytes(), "eng/regulations/SOR-99-129")
        assert meta.source == "https://laws-lois.justice.gc.ca/eng/regulations/SOR-99-129/"

    def test_minimal_act_metadata(self):
        """Minimal act (no body) should still have valid metadata."""
        meta = self.parser.parse(ACT_MINIMAL.read_bytes(), "eng/acts/C-0.4")
        assert meta.title == "Canada Agricultural Products Act"
        assert meta.identifier == "C-0.4"
        assert meta.status == NormStatus.IN_FORCE
        extra = dict(meta.extra)
        assert extra.get("has_previous_version") == "true"


# ─────────────────────────────────────────────
# Bilingual: French version of the same law
# ─────────────────────────────────────────────


class TestCABilingual:
    def setup_method(self):
        self.text_parser = CATextParser()
        self.meta_parser = CAMetadataParser()

    def test_french_metadata_jurisdiction(self):
        """French version of B-9.8 gets jurisdiction=ca-fr."""
        meta = self.meta_parser.parse(ACT_FR.read_bytes(), "fra/lois/B-9.8")
        assert meta.country == "ca"
        assert meta.jurisdiction == "ca-fr"
        assert meta.identifier == "B-9.8"  # same identifier as English version

    def test_french_metadata_title(self):
        """French fixture must have a French short title."""
        meta = self.meta_parser.parse(ACT_FR.read_bytes(), "fra/lois/B-9.8")
        assert meta.title  # non-empty
        # French title should not be identical to the English one.
        assert "Budget Implementation Act" not in meta.title

    def test_french_metadata_lang_extra(self):
        meta = self.meta_parser.parse(ACT_FR.read_bytes(), "fra/lois/B-9.8")
        extra = dict(meta.extra)
        assert extra["lang"] == "fr"

    def test_french_source_url_uses_fra(self):
        meta = self.meta_parser.parse(ACT_FR.read_bytes(), "fra/lois/B-9.8")
        assert meta.source == "https://laws-lois.justice.gc.ca/fra/lois/B-9.8/"

    def test_french_regulation_source_url_uses_reglements(self):
        meta = self.meta_parser.parse(REGULATION.read_bytes(), "fra/reglements/SOR-99-129")
        # URL category mirrors the upstream layout (lois/reglements, not acts/regulations).
        assert meta.source == "https://laws-lois.justice.gc.ca/fra/reglements/SOR-99-129/"
        assert meta.jurisdiction == "ca-fr"

    def test_french_text_parses(self):
        """Parser is language-agnostic: French XML must parse into blocks."""
        blocks = self.text_parser.parse_text(ACT_FR.read_bytes())
        assert len(blocks) == 1
        assert blocks[0].versions[0].paragraphs  # has content


# ─────────────────────────────────────────────
# Filepath / slug
# ─────────────────────────────────────────────


class TestSlug:
    def test_english_act_filepath(self):
        parser = CAMetadataParser()
        meta = parser.parse(ACT_SMALL.read_bytes(), "eng/acts/B-9.8")
        assert norm_to_filepath(meta) == "ca-en/B-9.8.md"

    def test_english_regulation_filepath(self):
        parser = CAMetadataParser()
        meta = parser.parse(REGULATION.read_bytes(), "eng/regulations/SOR-99-129")
        assert norm_to_filepath(meta) == "ca-en/SOR-99-129.md"

    def test_french_act_filepath(self):
        parser = CAMetadataParser()
        meta = parser.parse(ACT_FR.read_bytes(), "fra/lois/B-9.8")
        assert norm_to_filepath(meta) == "ca-fr/B-9.8.md"

    def test_english_and_french_paths_do_not_collide(self):
        """Sanity check: same identifier in both languages must not collide."""
        parser = CAMetadataParser()
        en = parser.parse(ACT_SMALL.read_bytes(), "eng/acts/B-9.8")
        fr = parser.parse(ACT_FR.read_bytes(), "fra/lois/B-9.8")
        assert norm_to_filepath(en) != norm_to_filepath(fr)


# ─────────────────────────────────────────────
# Registry hookup
# ─────────────────────────────────────────────


class TestRegistryHookup:
    def test_text_parser_lookup(self):
        parser = get_text_parser("ca")
        assert isinstance(parser, CATextParser)

    def test_metadata_parser_lookup(self):
        parser = get_metadata_parser("ca")
        assert isinstance(parser, CAMetadataParser)


# ─────────────────────────────────────────────
# Historical versions — suvestine (git log walk)
# ─────────────────────────────────────────────


class TestCASuvestine:
    """End-to-end test: build a mini git repo mirroring justicecanada's layout
    with two commits of B-9.8.xml on different dates, then verify that
    ``get_suvestine`` + ``parse_suvestine`` produce 2 Versions and 2 Reforms
    in chronological order with the correct dates."""

    def _build_upstream_repo(self, tmp_path):
        import subprocess as sp

        repo = tmp_path / "laws-lois-xml"
        (repo / "eng" / "acts").mkdir(parents=True)
        sp.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        sp.run(
            ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
            check=True,
        )
        sp.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)

        # First version (commit date 2024-11-15).
        xml_v1 = ACT_SMALL.read_bytes()
        (repo / "eng" / "acts" / "B-9.8.xml").write_bytes(xml_v1)
        sp.run(["git", "-C", str(repo), "add", "."], check=True)
        sp.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "v1"],
            env={
                "GIT_AUTHOR_DATE": "2024-11-15T12:00:00Z",
                "GIT_COMMITTER_DATE": "2024-11-15T12:00:00Z",
                "PATH": __import__("os").environ["PATH"],
            },
            check=True,
        )

        # Second version (commit date 2025-06-02) — minimal change so XML differs.
        xml_v2 = xml_v1.replace(b'lims:pit-date="2003-01-01"', b'lims:pit-date="2025-06-02"')
        (repo / "eng" / "acts" / "B-9.8.xml").write_bytes(xml_v2)
        sp.run(["git", "-C", str(repo), "add", "."], check=True)
        sp.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "v2"],
            env={
                "GIT_AUTHOR_DATE": "2025-06-02T12:00:00Z",
                "GIT_COMMITTER_DATE": "2025-06-02T12:00:00Z",
                "PATH": __import__("os").environ["PATH"],
            },
            check=True,
        )
        return repo

    def test_suvestine_roundtrip_two_versions(self, tmp_path):
        from legalize.fetcher.ca.client import JusticeCanadaClient

        repo = self._build_upstream_repo(tmp_path)
        # Disable Wayback so the test doesn't depend on a live internet
        # connection — we're verifying the git-log → parse roundtrip only.
        client = JusticeCanadaClient(xml_dir=str(repo), pit_enabled=False)
        parser = CATextParser()

        blob = client.get_suvestine("eng/acts/B-9.8")
        blocks, reforms = parser.parse_suvestine(blob, "eng/acts/B-9.8")

        assert len(blocks) == 1
        assert len(blocks[0].versions) == 2
        assert len(reforms) == 2

        # Oldest-first ordering (priority #4: per-file chronological commits).
        v1, v2 = blocks[0].versions
        assert v1.publication_date == date(2024, 11, 15)
        assert v2.publication_date == date(2025, 6, 2)
        # v2's effective_date comes from the lims:pit-date inside the XML.
        assert v2.effective_date == date(2025, 6, 2)
        # Reform.norm_id is the upstream SHA (dedup key per reform).
        assert len(set(r.norm_id for r in reforms)) == 2
        assert all(r.affected_blocks == ("body",) for r in reforms)

    def test_suvestine_falls_back_to_current_when_no_clone(self):
        """If xml_dir is missing the clone, return a single-version blob."""
        from legalize.fetcher.ca.client import JusticeCanadaClient

        # No xml_dir set → fallback to HTTP / single-snapshot. We can't easily
        # test HTTP here; instead verify the code path emits a 1-version blob
        # by pointing xml_dir at a non-existent path and stubbing get_text.
        client = JusticeCanadaClient(xml_dir="/nonexistent/path/xyz")
        client.get_text = lambda norm_id: ACT_SMALL.read_bytes()  # type: ignore

        blob = client.get_suvestine("eng/acts/B-9.8")
        import json

        data = json.loads(blob)
        assert len(data["versions"]) == 1
        assert data["versions"][0]["source_id"] == "current"
        assert data["versions"][0]["source_type"] == "http-current"
