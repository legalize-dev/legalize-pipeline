"""Tests for ELI jurisdiction extraction and autonomic norm support."""

from datetime import date
from unittest.mock import patch

import responses

from legalize.config import Config, ScopeConfig
from legalize.models import EstadoNorma, NormaMetadata, Rango
from legalize.transformer.metadata import extract_jurisdiccion, RANGO_CODE_MAP
from legalize.transformer.slug import norma_to_filepath


class TestExtractJurisdiccion:
    """Tests for extract_jurisdiccion()."""

    def test_state_level_from_eli(self):
        assert extract_jurisdiccion(
            "https://www.boe.es/eli/es/lo/1985/07/01/6", "BOE-A-1985-12666"
        ) == "es"

    def test_autonomic_cataluna_from_eli(self):
        assert extract_jurisdiccion(
            "https://www.boe.es/eli/es-ct/l/2017/07/20/13", "BOE-A-2017-9935"
        ) == "es-ct"

    def test_autonomic_pais_vasco_from_eli(self):
        assert extract_jurisdiccion(
            "https://www.boe.es/eli/es-pv/l/2019/12/20/11", "BOE-A-2020-615"
        ) == "es-pv"

    def test_autonomic_andalucia_from_eli(self):
        assert extract_jurisdiccion(
            "https://www.boe.es/eli/es-an/l/2021/12/07/3", "BOE-A-2022-666"
        ) == "es-an"

    def test_all_17_jurisdictions_from_eli(self):
        jurisdictions = [
            "es-ct", "es-ib", "es-vc", "es-nc", "es-ar", "es-ga", "es-pv",
            "es-cn", "es-md", "es-an", "es-ex", "es-cl", "es-cm", "es-cb",
            "es-mc", "es-ri", "es-as",
        ]
        for j in jurisdictions:
            url = f"https://www.boe.es/eli/{j}/l/2024/01/01/1"
            assert extract_jurisdiccion(url, "BOE-A-2024-1") == j

    def test_no_eli_fallback_boa(self):
        """BOA → Aragón (es-ar)."""
        assert extract_jurisdiccion("", "BOA-d-2019-90260") == "es-ar"

    def test_no_eli_fallback_boja(self):
        """BOJA → Andalucía (es-an)."""
        assert extract_jurisdiccion("", "BOJA-b-2020-90175") == "es-an"

    def test_no_eli_fallback_dogv(self):
        """DOGV → Comunidad Valenciana (es-vc)."""
        assert extract_jurisdiccion("", "DOGV-r-2018-90100") == "es-vc"

    def test_no_eli_fallback_dogc(self):
        """DOGC → Cataluña (es-ct)."""
        assert extract_jurisdiccion("", "DOGC-f-1997-90001") == "es-ct"

    def test_no_eli_fallback_boib(self):
        """BOIB → Illes Balears (es-ib)."""
        assert extract_jurisdiccion("", "BOIB-i-2005-90013") == "es-ib"

    def test_no_eli_fallback_bocl_not_boc(self):
        """BOCL should match es-cl, not BOC→es-cn."""
        assert extract_jurisdiccion("", "BOCL-x-2020-90001") == "es-cl"

    def test_no_eli_fallback_boc(self):
        """BOC → Canarias (es-cn)."""
        assert extract_jurisdiccion("", "BOC-y-2020-90001") == "es-cn"

    def test_no_eli_fallback_bocm(self):
        """BOCM → Madrid (es-md)."""
        assert extract_jurisdiccion("", "BOCM-z-2020-90001") == "es-md"

    def test_no_eli_fallback_bopv(self):
        """BOPV → País Vasco (es-pv)."""
        assert extract_jurisdiccion("", "BOPV-a-2020-90001") == "es-pv"

    def test_no_eli_no_prefix_defaults_to_es(self):
        """Unknown prefix defaults to 'es'."""
        assert extract_jurisdiccion("", "BOE-A-2024-1") == "es"

    def test_no_eli_empty_id_defaults_to_es(self):
        assert extract_jurisdiccion("", "") == "es"


class TestSlugWithJurisdiccion:
    """Tests for norma_to_filepath with jurisdiccion."""

    def _make_metadata(self, jurisdiccion: str = "es", rango: Rango = Rango.LEY, identificador: str = "BOE-A-2024-1") -> NormaMetadata:
        return NormaMetadata(
            titulo="Test",
            titulo_corto="Test",
            identificador=identificador,
            pais="es",
            rango=rango,
            fecha_publicacion=date(2024, 1, 1),
            estado=EstadoNorma.VIGENTE,
            departamento="Test",
            fuente="https://example.com",
            jurisdiccion=jurisdiccion,
        )

    def test_state_level_no_prefix(self):
        """State-level norms have no jurisdiction prefix (backwards compatible)."""
        meta = self._make_metadata("es")
        assert norma_to_filepath(meta) == "leyes/BOE-A-2024-1.md"

    def test_autonomic_has_prefix(self):
        """Autonomic norms include jurisdiction prefix."""
        meta = self._make_metadata("es-pv", identificador="BOE-A-2020-615")
        assert norma_to_filepath(meta) == "es-pv/leyes/BOE-A-2020-615.md"

    def test_autonomic_cataluna(self):
        meta = self._make_metadata("es-ct", rango=Rango.LEY_ORGANICA)
        assert norma_to_filepath(meta) == "es-ct/leyes-organicas/BOE-A-2024-1.md"

    def test_empty_jurisdiccion_defaults_to_es(self):
        """Empty jurisdiccion (legacy data) treated as state-level."""
        meta = self._make_metadata("")
        assert norma_to_filepath(meta) == "leyes/BOE-A-2024-1.md"

    def test_france_jurisdiccion(self):
        """French norms with jurisdiccion='fr' get no prefix (no dash)."""
        meta = NormaMetadata(
            titulo="Code civil",
            titulo_corto="Code civil",
            identificador="LEGITEXT000006069414",
            pais="fr",
            rango=Rango.CODE,
            fecha_publicacion=date(1804, 3, 21),
            estado=EstadoNorma.VIGENTE,
            departamento="",
            fuente="https://www.legifrance.gouv.fr",
            jurisdiccion="fr",
        )
        assert norma_to_filepath(meta) == "codes/LEGITEXT000006069414.md"


class TestFetchCatalogAmbito:
    """Tests for the ambito filter in fetch_catalog."""

    def test_scope_config_ambitos_default_empty(self):
        scope = ScopeConfig()
        assert scope.ambitos == []

    def test_scope_config_ambitos_state_only(self):
        scope = ScopeConfig(ambitos=["1"])
        assert scope.ambitos == ["1"]

    def test_scope_config_ambitos_all(self):
        scope = ScopeConfig(ambitos=["1", "2"])
        assert scope.ambitos == ["1", "2"]

    @responses.activate
    def test_fetch_catalog_filters_by_ambito(self, tmp_path):
        """fetch_catalog respects scope.ambitos filter."""
        from legalize.pipeline import fetch_catalog

        catalog_items = [
            {"identificador": "BOE-A-2024-1", "ambito": {"codigo": "1", "texto": "Estatal"}},
            {"identificador": "BOE-A-2024-2", "ambito": {"codigo": "2", "texto": "Autonómico"}},
            {"identificador": "BOE-A-2024-3", "ambito": {"codigo": "1", "texto": "Estatal"}},
        ]

        responses.add(
            responses.GET,
            "https://www.boe.es/datosabiertos/api/legislacion-consolidada",
            json={"data": catalog_items},
            status=200,
        )
        responses.add(
            responses.GET,
            "https://www.boe.es/datosabiertos/api/legislacion-consolidada",
            json={"data": []},
            status=200,
        )

        config = Config(
            scope=ScopeConfig(ambitos=["1"]),
            data_dir=str(tmp_path / "data"),
        )

        # Patch fetch_one to just record calls without hitting the API
        fetched_ids = []
        def mock_fetch_one(cfg, boe_id, force=False):
            fetched_ids.append(boe_id)
            return None

        with patch("legalize.pipeline.fetch_one", side_effect=mock_fetch_one):
            fetch_catalog(config)

        assert fetched_ids == ["BOE-A-2024-1", "BOE-A-2024-3"]

    @responses.activate
    def test_fetch_catalog_no_ambito_filter_returns_all(self, tmp_path):
        """fetch_catalog with empty ambitos returns all norms."""
        from legalize.pipeline import fetch_catalog

        catalog_items = [
            {"identificador": "BOE-A-2024-1", "ambito": {"codigo": "1", "texto": "Estatal"}},
            {"identificador": "BOE-A-2024-2", "ambito": {"codigo": "2", "texto": "Autonómico"}},
        ]

        responses.add(
            responses.GET,
            "https://www.boe.es/datosabiertos/api/legislacion-consolidada",
            json={"data": catalog_items},
            status=200,
        )
        responses.add(
            responses.GET,
            "https://www.boe.es/datosabiertos/api/legislacion-consolidada",
            json={"data": []},
            status=200,
        )

        config = Config(
            scope=ScopeConfig(ambitos=[]),
            data_dir=str(tmp_path / "data"),
        )

        fetched_ids = []
        def mock_fetch_one(cfg, boe_id, force=False):
            fetched_ids.append(boe_id)
            return None

        with patch("legalize.pipeline.fetch_one", side_effect=mock_fetch_one):
            fetch_catalog(config)

        assert fetched_ids == ["BOE-A-2024-1", "BOE-A-2024-2"]


class TestAutonomicRangoCodes:
    """Tests for autonomic rango code mappings."""

    def test_decreto_ley_code_1500(self):
        assert RANGO_CODE_MAP["1500"] == Rango.DECRETO_LEY

    def test_ley_foral_code_1450(self):
        assert RANGO_CODE_MAP["1450"] == Rango.LEY_FORAL

    def test_decreto_legislativo_code_1470(self):
        assert RANGO_CODE_MAP["1470"] == Rango.DECRETO_LEGISLATIVO

    def test_decreto_ley_foral_code_1325(self):
        assert RANGO_CODE_MAP["1325"] == Rango.DECRETO_LEY_FORAL

    def test_decreto_foral_legislativo_code_1480(self):
        assert RANGO_CODE_MAP["1480"] == Rango.DECRETO_FORAL_LEGISLATIVO

    def test_autonomic_slug_decreto_ley(self):
        from legalize.transformer.slug import rango_to_folder
        assert rango_to_folder(Rango.DECRETO_LEY) == "decretos-leyes"

    def test_autonomic_slug_ley_foral(self):
        from legalize.transformer.slug import rango_to_folder
        assert rango_to_folder(Rango.LEY_FORAL) == "leyes-forales"

    def test_full_path_autonomic_ley_foral(self):
        meta = NormaMetadata(
            titulo="Ley Foral 2/2018",
            titulo_corto="Ley Foral 2/2018",
            identificador="BOE-A-2018-6001",
            pais="es",
            rango=Rango.LEY_FORAL,
            fecha_publicacion=date(2018, 4, 13),
            estado=EstadoNorma.VIGENTE,
            departamento="Navarra",
            fuente="https://www.boe.es/eli/es-nc/lf/2018/04/13/2",
            jurisdiccion="es-nc",
        )
        assert norma_to_filepath(meta) == "es-nc/leyes-forales/BOE-A-2018-6001.md"
