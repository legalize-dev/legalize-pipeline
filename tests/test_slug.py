"""Tests for file path generation."""

from datetime import date

from legalize.models import NormMetadata, NormStatus, Rank
from legalize.transformer.slug import norm_to_filepath


def _make_metadata(
    identifier: str = "BOE-A-2024-1",
    country: str = "es",
    rank: Rank = Rank.LEY,
    jurisdiction: str | None = None,
) -> NormMetadata:
    return NormMetadata(
        title="Test",
        short_title="Test",
        identifier=identifier,
        country=country,
        rank=rank,
        publication_date=date(2024, 1, 1),
        status=NormStatus.IN_FORCE,
        department="Test",
        source="https://example.com",
        jurisdiction=jurisdiction,
    )


class TestNormaToFilepath:
    def test_state_level_uses_country(self):
        meta = _make_metadata("BOE-A-2015-11430")
        assert norm_to_filepath(meta) == "es/70/BOE-A-2015-11430.md"

    def test_ccaa_uses_jurisdiction(self):
        meta = _make_metadata("BOE-A-2020-615", jurisdiction="es-pv")
        assert norm_to_filepath(meta) == "es-pv/ff/BOE-A-2020-615.md"

    def test_france(self):
        meta = _make_metadata("JORF-001", country="fr")
        assert norm_to_filepath(meta) == "fr/JORF-001.md"

    def test_filename_is_identifier(self):
        meta = _make_metadata("BOE-A-1978-31229")
        assert norm_to_filepath(meta).endswith("BOE-A-1978-31229.md")

    def test_no_rank_subfolder(self):
        """Rank does not affect the path — it's in the YAML frontmatter."""
        meta1 = _make_metadata("BOE-A-1978-31229", rank=Rank.CONSTITUCION)
        meta2 = _make_metadata("BOE-A-1978-31229", rank=Rank.LEY)
        assert norm_to_filepath(meta1) == norm_to_filepath(meta2)

    def test_layout_depth_matches_the_country(self):
        """Spain shards national and regional laws; other fixtures remain flat."""
        countries = [
            ("BOE-A-2024-1", "es", None),
            ("JORF-001", "fr", None),
            ("SFS-1962-700", "se", None),
            ("AT-10002333", "at", None),
            ("BOE-A-2020-615", "es", "es-pv"),
        ]
        for identifier, country, jurisdiction in countries:
            meta = _make_metadata(identifier, country=country, jurisdiction=jurisdiction)
            path = norm_to_filepath(meta)
            parts = path.split("/")
            assert len(parts) == (3 if country == "es" else 2), (
                f"Unexpected layout, got {len(parts)} levels: {path}"
            )
            assert parts[-1].endswith(".md"), f"File must end with .md: {path}"
            assert ".." not in path, f"Path must not contain '..': {path}"
