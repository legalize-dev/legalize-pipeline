"""Tests for the generic multi-country pipeline.

Covers: CountryConfig, countries dispatch, storage round-trip,
StateStore persistence, and generic pipeline helpers.
"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from legalize.config import Config, CountryConfig
from legalize.countries import (
    REGISTRY,
    get_client_class,
    get_discovery_class,
    get_metadata_parser,
    get_text_parser,
    supported_countries,
)
from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    ParsedNorm,
    Rank,
    Reform,
    Version,
)
from legalize.pipeline import _extract_reforms_generic
from legalize.state.store import StateStore
from legalize.storage import load_norma_from_json, save_structured_json


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def _make_norma(
    identifier: str = "TEST-001",
    country: str = "es",
    css_classes: list[str] | None = None,
) -> ParsedNorm:
    """Build a minimal ParsedNorm for testing."""
    paragraphs = []
    if css_classes:
        for i, cls in enumerate(css_classes):
            paragraphs.append(Paragraph(css_class=cls, text=f"Paragraph {i}"))
    else:
        paragraphs.append(Paragraph(css_class="parrafo", text="Texto del articulo 1."))

    version = Version(
        norm_id=identifier,
        publication_date=date(2024, 1, 1),
        effective_date=date(2024, 1, 1),
        paragraphs=tuple(paragraphs),
    )
    block = Block(
        id="a1",
        block_type="precepto",
        title="Articulo 1",
        versions=(version,),
    )
    metadata = NormMetadata(
        title="Ley de Pruebas",
        short_title="Ley Pruebas",
        identifier=identifier,
        country=country,
        rank=Rank("ley"),
        publication_date=date(2024, 1, 1),
        status=NormStatus.IN_FORCE,
        department="Test",
        source="https://example.com/test",
        last_modified=date(2024, 6, 1),
    )
    reform = Reform(
        date=date(2024, 1, 1),
        norm_id=identifier,
        affected_blocks=("a1",),
    )
    return ParsedNorm(
        metadata=metadata,
        blocks=(block,),
        reforms=(reform,),
    )


# ─────────────────────────────────────────────
# TestCountryConfig
# ─────────────────────────────────────────────


class TestCountryConfig:
    def test_get_country_from_yaml(self):
        """Config with countries section returns correct CountryConfig."""
        cc_se = CountryConfig(repo_path="../countries/se", data_dir="../countries/data-se")
        config = Config(countries={"se": cc_se})
        result = config.get_country("se")
        assert result.repo_path == "../countries/se"
        assert result.data_dir == "../countries/data-se"

    def test_get_country_without_countries_section_raises(self):
        """Config without countries section raises ValueError."""
        config = Config()
        with pytest.raises(ValueError, match="not configured"):
            config.get_country("es")

    def test_get_country_unknown_raises(self):
        """Requesting unknown country raises ValueError."""
        config = Config()
        with pytest.raises(ValueError, match="not configured"):
            config.get_country("xx")

    def test_country_config_defaults_state_path(self):
        """Empty state_path gets default .pipeline/{code}/state.json."""
        cc = CountryConfig(
            repo_path="../countries/se", data_dir="../countries/data-se", state_path=""
        )
        config = Config(countries={"se": cc})
        result = config.get_country("se")
        assert result.state_path == ".pipeline/se/state.json"

    def test_supported_countries(self):
        """supported_countries() returns sorted list of registered codes."""
        codes = supported_countries()
        assert codes == sorted(codes)
        assert len(codes) >= 2  # at least es and fr
        assert "es" in codes
        assert "fr" in codes


# ─────────────────────────────────────────────
# TestCountriesDispatch
# ─────────────────────────────────────────────


class TestCountriesDispatch:
    REQUIRED_COMPONENTS = {"client", "discovery", "text_parser", "metadata_parser"}

    def test_all_countries_have_required_components(self):
        """Every country in REGISTRY has client, discovery, text_parser, metadata_parser."""
        for code, components in REGISTRY.items():
            missing = self.REQUIRED_COMPONENTS - set(components.keys())
            assert not missing, f"Country '{code}' missing components: {missing}"

    def test_all_clients_have_create(self):
        """Every client class has a create() classmethod."""
        for code in REGISTRY:
            cls = get_client_class(code)
            assert hasattr(cls, "create"), f"{code} client missing create()"
            assert callable(cls.create)

    def test_all_clients_are_context_managers(self):
        """Every client has __enter__ and __exit__."""
        for code in REGISTRY:
            cls = get_client_class(code)
            assert hasattr(cls, "__enter__"), f"{code} client missing __enter__"
            assert hasattr(cls, "__exit__"), f"{code} client missing __exit__"

    def test_all_parsers_have_required_methods(self):
        """TextParser has parse_text, extract_reforms; MetadataParser has parse."""
        for code in REGISTRY:
            tp = get_text_parser(code)
            assert hasattr(tp, "parse_text"), f"{code} text_parser missing parse_text"
            assert hasattr(tp, "extract_reforms"), f"{code} text_parser missing extract_reforms"

            mp = get_metadata_parser(code)
            assert hasattr(mp, "parse"), f"{code} metadata_parser missing parse"

    def test_all_discoveries_have_required_methods(self):
        """NormDiscovery has discover_all, discover_daily."""
        for code in REGISTRY:
            cls = get_discovery_class(code)
            # Check on the class (not an instance, since constructors may need args)
            assert hasattr(cls, "discover_all"), f"{code} discovery missing discover_all"
            assert hasattr(cls, "discover_daily"), f"{code} discovery missing discover_daily"


# ─────────────────────────────────────────────
# TestStorageRoundTrip
# ─────────────────────────────────────────────


class TestStorageRoundTrip:
    def test_save_and_load_norma(self, tmp_path):
        """Create a ParsedNorm, save to JSON, load back, verify all fields match."""
        norm = _make_norma()
        save_structured_json(str(tmp_path), norm)

        json_path = tmp_path / "json" / f"{norm.metadata.identifier}.json"
        assert json_path.exists()

        loaded = load_norma_from_json(json_path)
        assert loaded.metadata.identifier == norm.metadata.identifier
        assert loaded.metadata.title == norm.metadata.title.rstrip(". ")
        assert loaded.metadata.country == norm.metadata.country
        assert loaded.metadata.rank == norm.metadata.rank
        assert loaded.metadata.publication_date == norm.metadata.publication_date
        assert loaded.metadata.status == norm.metadata.status
        assert len(loaded.blocks) == len(norm.blocks)
        assert len(loaded.reforms) == len(norm.reforms)

        # Check block content round-trips
        orig_block = norm.blocks[0]
        loaded_block = loaded.blocks[0]
        assert loaded_block.id == orig_block.id
        assert loaded_block.block_type == orig_block.block_type
        assert loaded_block.title == orig_block.title
        assert len(loaded_block.versions) == len(orig_block.versions)

    def test_css_class_round_trip(self, tmp_path):
        """Save norm with non-parrafo CSS classes, load back, verify classes preserved."""
        norm = _make_norma(css_classes=["titulo_articulo", "parrafo", "lista_letra"])
        save_structured_json(str(tmp_path), norm)

        json_path = tmp_path / "json" / f"{norm.metadata.identifier}.json"
        loaded = load_norma_from_json(json_path)

        loaded_paragraphs = loaded.blocks[0].versions[0].paragraphs
        assert len(loaded_paragraphs) == 3
        assert loaded_paragraphs[0].css_class == "titulo_articulo"
        assert loaded_paragraphs[1].css_class == "parrafo"
        assert loaded_paragraphs[2].css_class == "lista_letra"

    def test_load_old_json_without_css_classes(self, tmp_path):
        """Load JSON without css_classes field, verify fallback to 'parrafo'."""
        # Simulate old JSON format (no css_classes key in versions)
        data = {
            "metadata": {
                "title": "Ley Antigua",
                "short_title": "Ley Antigua",
                "identifier": "OLD-001",
                "country": "es",
                "rank": "ley",
                "publication_date": "2020-01-01",
                "last_updated": "2020-01-01",
                "status": "in_force",
                "department": "Test",
                "source": "https://example.com",
            },
            "articles": [
                {
                    "block_id": "a1",
                    "block_type": "precepto",
                    "title": "Articulo 1",
                    "position": 0,
                    "current_text": "Line one\n\nLine two",
                    "versions": [
                        {
                            "date": "2020-01-01",
                            "source_id": "OLD-001",
                            "text": "Line one\n\nLine two",
                            # No css_classes key
                        }
                    ],
                }
            ],
            "reforms": [
                {
                    "date": "2020-01-01",
                    "source_id": "OLD-001",
                    "articles_affected": ["Articulo 1"],
                }
            ],
        }
        json_path = tmp_path / "old.json"
        json_path.write_text(json.dumps(data), encoding="utf-8")

        loaded = load_norma_from_json(json_path)
        paragraphs = loaded.blocks[0].versions[0].paragraphs
        assert len(paragraphs) == 2
        assert all(p.css_class == "parrafo" for p in paragraphs)


# ─────────────────────────────────────────────
# TestStateStorePersistence
# ─────────────────────────────────────────────


class TestStateStorePersistence:
    def test_load_state_from_json(self, tmp_path):
        """Load a state.json and verify all fields are read correctly."""
        state_path = tmp_path / "state.json"
        data = {
            "last_summary": "2024-03-15",
            "runs": [
                {
                    "timestamp": "2024-03-15T10:30:00",
                    "summaries_reviewed": ["2024-03-15"],
                    "commits_created": 5,
                    "errors": [],
                }
            ],
        }
        state_path.write_text(json.dumps(data), encoding="utf-8")

        store = StateStore(state_path)
        store.load()

        assert store.last_summary_date == date(2024, 3, 15)

    def test_save_json_structure(self, tmp_path):
        """Save state, read raw JSON, verify key structure."""
        state_path = tmp_path / "state.json"
        store = StateStore(state_path)
        store.last_summary_date = date(2024, 6, 1)
        store.save()

        raw = json.loads(state_path.read_text(encoding="utf-8"))
        assert raw["last_summary"] == "2024-06-01"
        assert isinstance(raw["runs"], list)

    def test_round_trip(self, tmp_path):
        """record_run + save + load, verify data preserved."""
        state_path = tmp_path / "state.json"

        store1 = StateStore(state_path)
        store1.last_summary_date = date(2024, 7, 1)
        store1.record_run(summaries=["2024-07-01"], commits=10, errors=["minor issue"])
        store1.save()

        store2 = StateStore(state_path)
        store2.load()

        assert store2.last_summary_date == date(2024, 7, 1)


# ─────────────────────────────────────────────
# TestGenericPipeline
# ─────────────────────────────────────────────


class TestGenericPipeline:
    def test_extract_reforms_generic_fallback(self):
        """_extract_reforms_generic falls back to extract_reforms when parser has no SFSR method."""
        mock_parser = MagicMock(spec=["parse_text", "extract_reforms"])
        mock_client = MagicMock()
        # Ensure the parser does NOT have extract_reforms_from_sfsr
        assert not hasattr(mock_parser, "extract_reforms_from_sfsr")

        blocks = [
            Block(
                id="a1",
                block_type="precepto",
                title="Articulo 1",
                versions=(
                    Version(
                        norm_id="TEST-001",
                        publication_date=date(2024, 1, 1),
                        effective_date=date(2024, 1, 1),
                        paragraphs=(Paragraph(css_class="parrafo", text="text"),),
                    ),
                ),
            )
        ]

        result = _extract_reforms_generic(mock_parser, mock_client, "TEST-001", blocks)
        # Should have called the standard extract_reforms from xml_parser (not on the mock)
        # The result should be a list of Reform objects derived from the blocks
        assert isinstance(result, list)

    def test_extract_reforms_generic_with_sfsr(self):
        """Mock a parser with extract_reforms_from_sfsr and client with get_amendment_register."""
        mock_parser = MagicMock()
        mock_parser.extract_reforms_from_sfsr.return_value = [
            Reform(
                date=date(2024, 3, 1),
                norm_id="SFS-2024:100",
                affected_blocks=(),
            )
        ]

        mock_client = MagicMock()
        mock_client.get_amendment_register.return_value = b"<html>sfsr data</html>"

        result = _extract_reforms_generic(mock_parser, mock_client, "SFS-2024:1", [])
        assert len(result) == 1
        assert result[0].norm_id == "SFS-2024:100"
        mock_client.get_amendment_register.assert_called_once_with("SFS-2024:1")
        mock_parser.extract_reforms_from_sfsr.assert_called_once_with(b"<html>sfsr data</html>")

    def test_extract_reforms_generic_sfsr_fallback_on_error(self):
        """If SFSR fetch fails, falls back to standard extract_reforms."""
        mock_parser = MagicMock()
        mock_parser.extract_reforms_from_sfsr.side_effect = Exception("Network error")

        mock_client = MagicMock()
        mock_client.get_amendment_register.side_effect = Exception("Network error")

        blocks = [
            Block(
                id="a1",
                block_type="precepto",
                title="Articulo 1",
                versions=(
                    Version(
                        norm_id="SFS-2024:1",
                        publication_date=date(2024, 1, 1),
                        effective_date=date(2024, 1, 1),
                        paragraphs=(Paragraph(css_class="parrafo", text="text"),),
                    ),
                ),
            )
        ]

        # Should not raise, falls back to extract_reforms
        result = _extract_reforms_generic(mock_parser, mock_client, "SFS-2024:1", blocks)
        assert isinstance(result, list)

    def test_a_parser_that_does_not_override_extract_reforms_parses_once(self):
        """``hasattr(parser, "extract_reforms")`` is always true — it is on the base.

        The base implementation parses the text a second time to rebuild the
        blocks this function was already handed, so the 12 countries that do not
        override it paid for two full parses of every norm — Portugal's 171,740
        included.
        """
        from legalize.fetcher.base import TextParser

        calls = []

        class PlainParser(TextParser):
            def parse_text(self, data: bytes):
                calls.append(data)
                return []

        result = _extract_reforms_generic(
            PlainParser(), MagicMock(spec=[]), "TEST-001", [], b"<x/>"
        )

        assert calls == [], "the norm was parsed a second time"
        assert result == []

    def test_a_parser_that_does_override_it_is_still_used(self):
        from legalize.fetcher.base import TextParser

        expected = [Reform(date=date(2024, 3, 1), norm_id="UA-1", affected_blocks=())]

        class AnnotationParser(TextParser):
            def parse_text(self, data: bytes):
                return []

            def extract_reforms(self, data: bytes):
                return expected

        result = _extract_reforms_generic(
            AnnotationParser(), MagicMock(spec=[]), "TEST-001", [], b"<x/>"
        )

        assert result == expected
