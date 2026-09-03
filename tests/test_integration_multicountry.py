"""Integration tests for multi-country generic pipeline.

Tests that commit_one, commit_all, and storage round-trip work
correctly for norms from different countries (ES, FR, SE).
No HTTP calls — all data is synthetic ParsedNorm objects.
"""

import dataclasses
import subprocess
from datetime import date
from pathlib import Path

import pytest

from legalize.config import Config, CountryConfig, GitConfig
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
from legalize.pipeline import commit_all, commit_one
from legalize.storage import load_norma_from_json, save_structured_json
from legalize.transformer.slug import norm_to_filepath


# ─────────────────────────────────────────────
# Helpers — synthetic norm builders
# ─────────────────────────────────────────────


def _make_version(source_id: str, d: date, text: str) -> Version:
    return Version(
        norm_id=source_id,
        publication_date=d,
        effective_date=d,
        paragraphs=(Paragraph(css_class="parrafo", text=text),),
    )


def _make_block(block_id: str, title: str, versions: list[Version]) -> Block:
    return Block(
        id=block_id,
        block_type="precepto",
        title=title,
        versions=tuple(versions),
    )


def _make_norm_es() -> ParsedNorm:
    """Spanish norm with 2 blocks, 2 reforms (original + amendment)."""
    d1 = date(2000, 1, 15)
    d2 = date(2010, 6, 20)
    src1 = "BOE-A-2000-100"
    src2 = "BOE-A-2010-500"

    blocks = [
        _make_block(
            "a1",
            "Artículo 1",
            [
                _make_version(src1, d1, "Texto original del artículo 1."),
                _make_version(src2, d2, "Texto reformado del artículo 1."),
            ],
        ),
        _make_block(
            "a2",
            "Artículo 2",
            [
                _make_version(src1, d1, "Texto original del artículo 2."),
            ],
        ),
        _make_block(
            "a3",
            "Artículo 3",
            [
                _make_version(src1, d1, "Texto original del artículo 3."),
            ],
        ),
    ]

    reforms = [
        Reform(date=d1, norm_id=src1, affected_blocks=("a1", "a2", "a3")),
        Reform(date=d2, norm_id=src2, affected_blocks=("a1",)),
    ]

    metadata = NormMetadata(
        title="Ley de Prueba Española",
        short_title="Ley de Prueba",
        identifier="BOE-A-2000-100",
        country="es",
        rank=Rank.LEY,
        publication_date=d1,
        status=NormStatus.IN_FORCE,
        department="Ministerio de Justicia",
        source="https://www.boe.es/eli/es/l/2000/01/15/1",
    )

    return ParsedNorm(metadata=metadata, blocks=tuple(blocks), reforms=tuple(reforms))


def _make_norm_fr() -> ParsedNorm:
    """French norm with 2 blocks, 2 reforms."""
    d1 = date(1804, 3, 21)
    d2 = date(2016, 10, 1)
    src1 = "LEGITEXT000006070721"
    src2 = "JORFTEXT000033202746"

    blocks = [
        _make_block(
            "art1",
            "Article 1",
            [
                _make_version(src1, d1, "Toute personne est capable de contracter."),
                _make_version(
                    src2, d2, "Toute personne physique et morale est capable de contracter."
                ),
            ],
        ),
        _make_block(
            "art2",
            "Article 2",
            [
                _make_version(src1, d1, "La loi ne dispose que pour l'avenir."),
            ],
        ),
        _make_block(
            "art3",
            "Article 3",
            [
                _make_version(src1, d1, "Les lois de police et de sûreté obligent tous."),
            ],
        ),
    ]

    reforms = [
        Reform(date=d1, norm_id=src1, affected_blocks=("art1", "art2", "art3")),
        Reform(date=d2, norm_id=src2, affected_blocks=("art1",)),
    ]

    metadata = NormMetadata(
        title="Code civil",
        short_title="Code civil",
        identifier="LEGITEXT000006070721",
        country="fr",
        rank=Rank.CODE,
        publication_date=d1,
        status=NormStatus.IN_FORCE,
        department="Ministère de la Justice",
        source="https://www.legifrance.gouv.fr/codes/texte_lc/LEGITEXT000006070721",
    )

    return ParsedNorm(metadata=metadata, blocks=tuple(blocks), reforms=tuple(reforms))


def _make_norm_se() -> ParsedNorm:
    """Swedish norm with 3 blocks, 2 reforms."""
    d1 = date(1962, 1, 1)
    d2 = date(2020, 7, 1)
    src1 = "SFS-1962-700"
    src2 = "SFS-2020-321"

    blocks = [
        _make_block(
            "kap1p1",
            "1 kap. 1 §",
            [
                _make_version(src1, d1, "Brottsbalken gäller för brott som begås i Sverige."),
                _make_version(src2, d2, "Brottsbalken gäller för brott begångna inom riket."),
            ],
        ),
        _make_block(
            "kap1p2",
            "1 kap. 2 §",
            [
                _make_version(src1, d1, "Straff skall bestämmas efter lag."),
            ],
        ),
        _make_block(
            "kap1p3",
            "1 kap. 3 §",
            [
                _make_version(src1, d1, "Den som begår brott under påverkan av alkohol döms."),
            ],
        ),
    ]

    reforms = [
        Reform(date=d1, norm_id=src1, affected_blocks=("kap1p1", "kap1p2", "kap1p3")),
        Reform(date=d2, norm_id=src2, affected_blocks=("kap1p1",)),
    ]

    metadata = NormMetadata(
        title="Brottsbalk",
        short_title="Brottsbalk",
        identifier="SFS-1962-700",
        country="se",
        rank=Rank("lag"),
        publication_date=d1,
        status=NormStatus.IN_FORCE,
        department="Justitiedepartementet",
        source="https://www.riksdagen.se/sv/dokument-och-lagar/dokument/svensk-forfattningssamling/brottsbalk-1962700_sfs-1962-700/",
    )

    return ParsedNorm(metadata=metadata, blocks=tuple(blocks), reforms=tuple(reforms))


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────


def _country_config(tmp_path, code: str) -> CountryConfig:
    return CountryConfig(
        repo_path=str(tmp_path / "repo"),
        data_dir=str(tmp_path / "data"),
        state_path=str(tmp_path / f"state-{code}.json"),
    )


@pytest.fixture
def test_config(tmp_path) -> Config:
    """Config with temporary repo and data dir."""
    return Config(
        git=GitConfig(),
        countries={
            "es": _country_config(tmp_path, "es"),
            "fr": _country_config(tmp_path, "fr"),
            "se": _country_config(tmp_path, "se"),
        },
    )


def _save_norm(config: Config, norm: ParsedNorm) -> Path:
    """Save a norm to JSON and return the path."""
    cc = config.get_country(norm.metadata.country)
    return save_structured_json(cc.data_dir, norm)


def _git_log_dates(repo_path: str) -> list[str]:
    """Get commit dates in chronological order."""
    result = subprocess.run(
        ["git", "log", "--format=%ai", "--reverse"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    return [line.split()[0] for line in result.stdout.strip().splitlines() if line.strip()]


def _git_log_bodies(repo_path: str) -> list[str]:
    """Get all commit bodies."""
    result = subprocess.run(
        ["git", "log", "--format=%B---SEPARATOR---", "--reverse"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    bodies = result.stdout.split("---SEPARATOR---")
    return [b.strip() for b in bodies if b.strip()]


def _git_commit_count(repo_path: str) -> int:
    """Count total commits."""
    result = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return 0
    return int(result.stdout.strip())


# ─────────────────────────────────────────────
# TestGenericCommitMultiCountry
# ─────────────────────────────────────────────


class TestGenericCommitMultiCountry:
    """Test that commit_one works correctly with JSON files from different countries."""

    @pytest.mark.parametrize(
        "make_norm,expected_dir",
        [
            (_make_norm_es, "es"),
            (_make_norm_fr, "fr"),
            (_make_norm_se, "se"),
        ],
        ids=["spain", "france", "sweden"],
    )
    def test_correct_number_of_commits(self, test_config, make_norm, expected_dir):
        norm = make_norm()
        _save_norm(test_config, norm)
        count = commit_one(test_config, norm.metadata.country, norm.metadata.identifier)
        assert count == 2

    @pytest.mark.parametrize(
        "make_norm,expected_dir",
        [
            (_make_norm_es, "es"),
            (_make_norm_fr, "fr"),
            (_make_norm_se, "se"),
        ],
        ids=["spain", "france", "sweden"],
    )
    def test_markdown_file_at_correct_path(self, test_config, make_norm, expected_dir):
        norm = make_norm()
        _save_norm(test_config, norm)
        commit_one(test_config, norm.metadata.country, norm.metadata.identifier)

        md_path = (
            Path(test_config.get_country("es").repo_path)
            / expected_dir
            / f"{norm.metadata.identifier}.md"
        )
        assert md_path.exists(), f"Expected {md_path} to exist"

        content = md_path.read_text(encoding="utf-8")
        assert norm.metadata.short_title in content

    @pytest.mark.parametrize(
        "make_norm,expected_dir",
        [
            (_make_norm_es, "es"),
            (_make_norm_fr, "fr"),
            (_make_norm_se, "se"),
        ],
        ids=["spain", "france", "sweden"],
    )
    def test_frontmatter_has_correct_country(self, test_config, make_norm, expected_dir):
        norm = make_norm()
        _save_norm(test_config, norm)
        commit_one(test_config, norm.metadata.country, norm.metadata.identifier)

        md_path = (
            Path(test_config.get_country("es").repo_path)
            / expected_dir
            / f"{norm.metadata.identifier}.md"
        )
        content = md_path.read_text(encoding="utf-8")
        assert f'country: "{norm.metadata.country}"' in content

    @pytest.mark.parametrize(
        "make_norm,expected_dir",
        [
            (_make_norm_es, "es"),
            (_make_norm_fr, "fr"),
            (_make_norm_se, "se"),
        ],
        ids=["spain", "france", "sweden"],
    )
    def test_git_commits_have_correct_trailers(self, test_config, make_norm, expected_dir):
        norm = make_norm()
        _save_norm(test_config, norm)
        commit_one(test_config, norm.metadata.country, norm.metadata.identifier)

        bodies = _git_log_bodies(test_config.get_country("es").repo_path)
        assert len(bodies) == 2

        # Last commit should have Source-Id, Source-Date, Norm-Id
        last_body = bodies[-1]
        assert "Source-Id:" in last_body
        assert "Source-Date:" in last_body
        assert f"Norm-Id: {norm.metadata.identifier}" in last_body


# ─────────────────────────────────────────────
# TestMultiVersionNorm
# ─────────────────────────────────────────────


class TestMultiVersionNorm:
    """Test a norm with 4+ versions (like the Constitution with 4 reforms)."""

    @staticmethod
    def _make_four_version_norm() -> ParsedNorm:
        dates = [date(1978, 12, 29), date(1992, 8, 28), date(2011, 9, 27), date(2024, 2, 17)]
        sources = ["SRC-ORIG", "SRC-1992", "SRC-2011", "SRC-2024"]

        blocks = [
            _make_block(
                "a1",
                "Artículo 1",
                [
                    _make_version(sources[0], dates[0], "Versión original art 1."),
                    _make_version(sources[1], dates[1], "Versión 1992 art 1."),
                ],
            ),
            _make_block(
                "a2",
                "Artículo 2",
                [
                    _make_version(sources[0], dates[0], "Versión original art 2."),
                    _make_version(sources[2], dates[2], "Versión 2011 art 2."),
                ],
            ),
            _make_block(
                "a3",
                "Artículo 3",
                [
                    _make_version(sources[0], dates[0], "Versión original art 3."),
                    _make_version(sources[3], dates[3], "Versión 2024 art 3."),
                ],
            ),
        ]

        reforms = [
            Reform(date=dates[0], norm_id=sources[0], affected_blocks=("a1", "a2", "a3")),
            Reform(date=dates[1], norm_id=sources[1], affected_blocks=("a1",)),
            Reform(date=dates[2], norm_id=sources[2], affected_blocks=("a2",)),
            Reform(date=dates[3], norm_id=sources[3], affected_blocks=("a3",)),
        ]

        metadata = NormMetadata(
            title="Norma con Cuatro Versiones",
            short_title="Norma Cuatro Versiones",
            identifier="TEST-FOUR-VERSIONS",
            country="es",
            rank=Rank.CONSTITUCION,
            publication_date=dates[0],
            status=NormStatus.IN_FORCE,
            department="Test",
            source="https://example.com/test",
        )

        return ParsedNorm(metadata=metadata, blocks=tuple(blocks), reforms=tuple(reforms))

    def test_creates_four_commits(self, test_config):
        norm = self._make_four_version_norm()
        _save_norm(test_config, norm)
        count = commit_one(test_config, norm.metadata.country, norm.metadata.identifier)
        assert count == 4

    def test_each_commit_has_correct_historical_date(self, test_config):
        norm = self._make_four_version_norm()
        _save_norm(test_config, norm)
        commit_one(test_config, norm.metadata.country, norm.metadata.identifier)

        dates = _git_log_dates(test_config.get_country("es").repo_path)
        assert dates == ["1978-12-29", "1992-08-28", "2011-09-27", "2024-02-17"]

    def test_markdown_content_changes_between_versions(self, test_config):
        norm = self._make_four_version_norm()
        _save_norm(test_config, norm)
        commit_one(test_config, norm.metadata.country, norm.metadata.identifier)

        # Get content at each commit
        result = subprocess.run(
            ["git", "log", "--format=%H", "--reverse"],
            cwd=test_config.get_country("es").repo_path,
            capture_output=True,
            text=True,
        )
        shas = result.stdout.strip().splitlines()
        assert len(shas) == 4

        contents = []
        for sha in shas:
            show = subprocess.run(
                ["git", "show", f"{sha}:es/TEST-FOUR-VERSIONS.md"],
                cwd=test_config.get_country("es").repo_path,
                capture_output=True,
                text=True,
            )
            contents.append(show.stdout)

        # First version has "original" text
        assert "Versión original art 1" in contents[0]
        # Second version updates art 1
        assert "Versión 1992 art 1" in contents[1]
        assert "Versión 1992 art 1" not in contents[0]
        # Third version updates art 2
        assert "Versión 2011 art 2" in contents[2]
        assert "Versión 2011 art 2" not in contents[1]
        # Fourth version updates art 3
        assert "Versión 2024 art 3" in contents[3]
        assert "Versión 2024 art 3" not in contents[2]

    def test_idempotent_rerun_creates_zero_commits(self, test_config):
        norm = self._make_four_version_norm()
        _save_norm(test_config, norm)
        count1 = commit_one(test_config, norm.metadata.country, norm.metadata.identifier)
        count2 = commit_one(test_config, norm.metadata.country, norm.metadata.identifier)
        assert count1 == 4
        assert count2 == 0


# ─────────────────────────────────────────────
# TestStorageGenericRoundTrip
# ─────────────────────────────────────────────


class TestStorageGenericRoundTrip:
    """Test that save + load works identically for norms from different countries."""

    @pytest.mark.parametrize(
        "make_norm",
        [_make_norm_es, _make_norm_fr, _make_norm_se],
        ids=["spain", "france", "sweden"],
    )
    def test_metadata_round_trips(self, test_config, make_norm):
        norm = make_norm()
        json_path = _save_norm(test_config, norm)
        loaded = load_norma_from_json(json_path)

        assert loaded.metadata.title == norm.metadata.title.rstrip(". ")
        assert loaded.metadata.short_title == norm.metadata.short_title
        assert loaded.metadata.identifier == norm.metadata.identifier
        assert loaded.metadata.country == norm.metadata.country
        assert loaded.metadata.rank == norm.metadata.rank
        assert loaded.metadata.publication_date == norm.metadata.publication_date
        assert loaded.metadata.status == norm.metadata.status
        assert loaded.metadata.department == norm.metadata.department
        assert loaded.metadata.source == norm.metadata.source

    @pytest.mark.parametrize(
        "make_norm",
        [_make_norm_es, _make_norm_fr, _make_norm_se],
        ids=["spain", "france", "sweden"],
    )
    def test_blocks_round_trip(self, test_config, make_norm):
        norm = make_norm()
        json_path = _save_norm(test_config, norm)
        loaded = load_norma_from_json(json_path)

        assert len(loaded.blocks) == len(norm.blocks)
        for orig, loaded_b in zip(norm.blocks, loaded.blocks, strict=True):
            assert loaded_b.id == orig.id
            assert loaded_b.block_type == orig.block_type
            assert loaded_b.title == orig.title
            assert len(loaded_b.versions) == len(orig.versions)

            for orig_v, loaded_v in zip(orig.versions, loaded_b.versions, strict=True):
                assert loaded_v.norm_id == orig_v.norm_id
                assert loaded_v.publication_date == orig_v.publication_date
                # Paragraph text should match
                orig_text = "\n\n".join(p.text for p in orig_v.paragraphs)
                loaded_text = "\n\n".join(p.text for p in loaded_v.paragraphs)
                assert loaded_text == orig_text

    @pytest.mark.parametrize(
        "make_norm",
        [_make_norm_es, _make_norm_fr, _make_norm_se],
        ids=["spain", "france", "sweden"],
    )
    def test_reforms_round_trip(self, test_config, make_norm):
        norm = make_norm()
        json_path = _save_norm(test_config, norm)
        loaded = load_norma_from_json(json_path)

        assert len(loaded.reforms) == len(norm.reforms)
        for orig, loaded_r in zip(norm.reforms, loaded.reforms, strict=True):
            assert loaded_r.date == orig.date
            assert loaded_r.norm_id == orig.norm_id

    def test_different_pais_values_preserved(self, test_config):
        """All three countries have distinct pais values after round-trip."""
        norms = [_make_norm_es(), _make_norm_fr(), _make_norm_se()]
        loaded_pais = []
        for norm in norms:
            json_path = _save_norm(test_config, norm)
            loaded = load_norma_from_json(json_path)
            loaded_pais.append(loaded.metadata.country)

        assert loaded_pais == ["es", "fr", "se"]

    def test_different_rango_values_preserved(self, test_config):
        """Country-specific rango values survive round-trip."""
        norms = [_make_norm_es(), _make_norm_fr(), _make_norm_se()]
        loaded_rangos = []
        for norm in norms:
            json_path = _save_norm(test_config, norm)
            loaded = load_norma_from_json(json_path)
            loaded_rangos.append(str(loaded.metadata.rank))

        assert loaded_rangos == ["ley", "code", "lag"]


# ─────────────────────────────────────────────
# TestCommitAllMultiCountry
# ─────────────────────────────────────────────


class TestCommitAllMultiCountry:
    """Test commit_all with a mix of countries, each in their own data_dir."""

    @staticmethod
    def _commit_all_countries(test_config):
        """Run commit_all for each configured country, return total."""
        total = 0
        for code in test_config.countries:
            total += commit_all(test_config, code)
        return total

    def test_all_three_norms_generate_commits(self, test_config):
        norms = [_make_norm_es(), _make_norm_fr(), _make_norm_se()]
        for norm in norms:
            _save_norm(test_config, norm)

        total = self._commit_all_countries(test_config)
        # Each norm has 2 reforms = 2 commits, so 6 total
        assert total == 6

    def test_each_markdown_in_correct_country_directory(self, test_config):
        norms = [_make_norm_es(), _make_norm_fr(), _make_norm_se()]
        for norm in norms:
            _save_norm(test_config, norm)

        self._commit_all_countries(test_config)

        repo = Path(test_config.get_country("es").repo_path)
        assert (repo / "es" / "BOE-A-2000-100.md").exists()
        assert (repo / "fr" / "LEGITEXT000006070721.md").exists()
        assert (repo / "se" / "SFS-1962-700.md").exists()

    def test_each_file_has_correct_frontmatter(self, test_config):
        norms = [_make_norm_es(), _make_norm_fr(), _make_norm_se()]
        for norm in norms:
            _save_norm(test_config, norm)

        self._commit_all_countries(test_config)

        repo = Path(test_config.get_country("es").repo_path)

        es_content = (repo / "es" / "BOE-A-2000-100.md").read_text(encoding="utf-8")
        assert 'country: "es"' in es_content
        assert 'rank: "ley"' in es_content

        fr_content = (repo / "fr" / "LEGITEXT000006070721.md").read_text(encoding="utf-8")
        assert 'country: "fr"' in fr_content
        assert 'rank: "code"' in fr_content

        se_content = (repo / "se" / "SFS-1962-700.md").read_text(encoding="utf-8")
        assert 'country: "se"' in se_content
        assert 'rank: "lag"' in se_content

    def test_total_git_commits(self, test_config):
        norms = [_make_norm_es(), _make_norm_fr(), _make_norm_se()]
        for norm in norms:
            _save_norm(test_config, norm)

        self._commit_all_countries(test_config)

        count = _git_commit_count(test_config.get_country("es").repo_path)
        assert count == 6

    def test_idempotent_rerun(self, test_config):
        norms = [_make_norm_es(), _make_norm_fr(), _make_norm_se()]
        for norm in norms:
            _save_norm(test_config, norm)

        total1 = self._commit_all_countries(test_config)
        total2 = self._commit_all_countries(test_config)
        assert total1 == 6
        assert total2 == 0


# ─────────────────────────────────────────────
# TestSlugMultiCountry
# ─────────────────────────────────────────────


class TestSlugMultiCountry:
    """Test norm_to_filepath generates correct paths for each country."""

    def test_spanish_norm_path(self):
        norm = _make_norm_es()
        assert norm_to_filepath(norm.metadata) == "es/BOE-A-2000-100.md"

    def test_french_norm_path(self):
        norm = _make_norm_fr()
        assert norm_to_filepath(norm.metadata) == "fr/LEGITEXT000006070721.md"

    def test_swedish_norm_path(self):
        norm = _make_norm_se()
        assert norm_to_filepath(norm.metadata) == "se/SFS-1962-700.md"

    def test_jurisdiction_overrides_pais(self):
        """Autonomous community norms use jurisdiccion as directory."""
        meta = NormMetadata(
            title="Ley vasca",
            short_title="Ley vasca",
            identifier="BOE-A-2020-615",
            country="es",
            rank=Rank.LEY,
            publication_date=date(2020, 1, 1),
            status=NormStatus.IN_FORCE,
            department="Test",
            source="https://example.com",
            jurisdiction="es-pv",
        )
        assert norm_to_filepath(meta) == "es-pv/BOE-A-2020-615.md"


# ─────────────────────────────────────────────
# TestBootstrapIncludesAllBlocks
# ─────────────────────────────────────────────


class TestBootstrapIncludesAllBlocks:
    """A bootstrap commit carries the law as it stood that day — and nothing
    newer.

    This class used to assert the opposite, and that is how 2,553 files and
    20,523 headings reached `legalize-es` claiming a date their body does not
    match: `es/BOE-A-1985-12666.md` (LOPJ), bootstrap dated 1985-07-02, shipped
    `Artículo 4 bis` on the application of European Union law, added in 2015 —
    Spain joined the EEC in 1986. The file declares itself `point_in_time` and
    was not (#106).

    `include_all` survives for the one case it was needed for: a norm whose
    every version post-dates its own enactment would otherwise render as an
    empty file, which is what took Austria's ABGB from 759 sections to 12
    (9705ecb). That case is covered below.
    """

    @staticmethod
    def _make_norm_with_mismatched_dates() -> ParsedNorm:
        """Norm where some blocks have dates AFTER the first reform.

        Block a1: version at 2000-01-01 (matches first reform)
        Block a2: version at 2005-03-15 (AFTER first reform — would be missing without include_all)
        Block a3: version at 2010-06-20 (AFTER first reform — would be missing without include_all)
        Reform 1: 2000-01-01 (only covers a1)
        Reform 2: 2010-06-20 (covers a3)
        """
        d1 = date(2000, 1, 1)
        d2 = date(2005, 3, 15)
        d3 = date(2010, 6, 20)

        blocks = [
            _make_block(
                "a1", "Article 1", [_make_version("SRC-ORIG", d1, "Original text of article 1.")]
            ),
            _make_block(
                "a2",
                "Article 2",
                [_make_version("SRC-OTHER", d2, "Text of article 2 added later.")],
            ),
            _make_block(
                "a3",
                "Article 3",
                [
                    _make_version("SRC-OTHER", d2, "Original text of article 3."),
                    _make_version("SRC-REFORM", d3, "Reformed text of article 3."),
                ],
            ),
        ]

        reforms = [
            Reform(date=d1, norm_id="SRC-ORIG", affected_blocks=("a1",)),
            Reform(date=d3, norm_id="SRC-REFORM", affected_blocks=("a3",)),
        ]

        metadata = NormMetadata(
            title="Test Law with Mismatched Dates",
            short_title="Test Law",
            identifier="TEST-INCLUDE-ALL",
            country="es",
            rank=Rank.LEY,
            publication_date=d1,
            status=NormStatus.IN_FORCE,
            department="Test",
            source="https://example.com",
        )

        return ParsedNorm(metadata=metadata, blocks=tuple(blocks), reforms=tuple(reforms))

    def test_bootstrap_carries_only_what_was_in_force_that_day(self, test_config):
        """The 2000-01-01 commit holds a1 and nothing written in 2005 or 2010."""
        norm = self._make_norm_with_mismatched_dates()
        _save_norm(test_config, norm)
        commit_one(test_config, norm.metadata.country, norm.metadata.identifier)

        # Read the FIRST commit's content (bootstrap), not the final state
        result = subprocess.run(
            ["git", "log", "--format=%H", "--reverse"],
            cwd=test_config.get_country("es").repo_path,
            capture_output=True,
            text=True,
        )
        first_sha = result.stdout.strip().splitlines()[0]
        show = subprocess.run(
            ["git", "show", f"{first_sha}:es/TEST-INCLUDE-ALL.md"],
            cwd=test_config.get_country("es").repo_path,
            capture_output=True,
            text=True,
        )
        content = show.stdout

        assert "Original text of article 1" in content, "a1 was in force on 2000-01-01"
        assert "Text of article 2 added later" not in content, (
            "a2 was written in 2005 and cannot appear in a commit dated 2000"
        )
        assert "Original text of article 3" not in content, (
            "a3 was written in 2005 and cannot appear in a commit dated 2000"
        )
        assert 'last_updated: "2000-01-01"' in content, (
            "and the file must date itself as what it holds"
        )

    def test_a_norm_whose_every_version_is_later_still_renders(self, test_config):
        """The case `include_all` exists for: without the fallback this file
        would be frontmatter and a title. Austria's ABGB is the real one."""
        norm = self._make_norm_with_mismatched_dates()
        early = dataclasses.replace(norm.metadata, publication_date=date(1990, 1, 1))
        blocks = tuple(b for b in norm.blocks if b.id != "a1")
        reforms = (Reform(date=date(1990, 1, 1), norm_id="SRC-ORIG", affected_blocks=()),)
        _save_norm(
            test_config,
            ParsedNorm(metadata=early, blocks=blocks, reforms=reforms),
        )
        commit_one(test_config, "es", "TEST-INCLUDE-ALL")

        md_path = Path(test_config.get_country("es").repo_path) / "es" / "TEST-INCLUDE-ALL.md"
        content = md_path.read_text(encoding="utf-8")
        assert "Text of article 2 added later" in content
        assert "Original text of article 3" in content

    def test_reform_only_changes_affected_block(self, test_config):
        """Second commit (reform) should change only article 3."""
        norm = self._make_norm_with_mismatched_dates()
        _save_norm(test_config, norm)
        commits = commit_one(test_config, norm.metadata.country, norm.metadata.identifier)
        assert commits == 2

        # Get the markdown at the last commit
        md_path = Path(test_config.get_country("es").repo_path) / "es" / "TEST-INCLUDE-ALL.md"
        content = md_path.read_text(encoding="utf-8")

        # Article 3 should now have the reformed text
        assert "Reformed text of article 3" in content
        # Articles 1 and 2 should still be there unchanged
        assert "Original text of article 1" in content
        assert "Text of article 2 added later" in content
