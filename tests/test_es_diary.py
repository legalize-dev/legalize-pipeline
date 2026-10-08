"""The diary surface must retain its body and report fidelity exclusions."""

import pytest
from lxml import etree

from legalize.fetcher.es.diary import ExcludedDiary, parse_diary
from legalize.models import TextState
from legalize.transformer.markdown import render_norm_at_date
from tests.test_es_source_fidelity import payload


def test_constitutional_reform_is_as_enacted_and_uses_direct_text():
    raw = payload("sample-not-consolidated", "diary")
    norm = parse_diary(raw, "BOE-A-2026-10881")
    assert norm.metadata.text_state is TextState.AS_ENACTED
    assert str(norm.metadata.rank) == "reforma"
    assert dict(norm.metadata.extra)["has_articles"] == "true"
    assert "source_notice" not in dict(norm.metadata.extra)
    body = render_norm_at_date(norm.metadata, norm.blocks, norm.metadata.publication_date)
    assert "Formentera" in body and "as_enacted" in body
    assert len(body) > 20_000
    assert norm.reforms[0].norm_id == "BOE-A-2026-10881"


def test_image_substitution_is_a_structured_exclusion():
    with pytest.raises(ExcludedDiary) as error:
        parse_diary(payload("sample-image-substituted", "diary"), "BOE-A-2014-13617")
    assert error.value.record["reason"] == "low-density"
    assert error.value.record["pages"] == 198
    assert error.value.record["images"] >= 190
    assert error.value.record["chars_per_page"] < 600


def test_a_reference_cannot_substitute_for_an_empty_body():
    root = etree.fromstring(payload("sample-not-consolidated", "diary"))
    root.find("texto").clear()
    with pytest.raises(ExcludedDiary, match="empty-text"):
        parse_diary(etree.tostring(root), "BOE-A-2026-10881")


def test_correction_relation_excludes_an_act_even_with_resolution_rank():
    root = etree.fromstring(payload("sample-not-consolidated", "diary"))
    root.find("metadatos/rango").set("codigo", "1370")
    previous = root.find("analisis/referencias/anteriores")
    entry = etree.SubElement(previous, "anterior")
    etree.SubElement(entry, "palabra", codigo="x").text = "CORRIGE errores"
    with pytest.raises(ExcludedDiary, match="judicial-or-correction"):
        parse_diary(etree.tostring(root), "BOE-A-2026-10881")


def test_diary_jurisdiction_uses_its_own_scope_field():
    root = etree.fromstring(payload("sample-not-consolidated", "diary"))
    root.find("metadatos/origen_legislativo").set("codigo", "2")
    root.find("metadatos/departamento").set("codigo", "8070")
    root.find("metadatos/judicialmente_anulada").text = "S"
    norm = parse_diary(etree.tostring(root), "BOE-A-2026-10881")
    assert norm.metadata.jurisdiction == "es-ct"
    assert dict(norm.metadata.extra)["scope_code"] == "2"
    assert norm.metadata.status.value == "annulled"


def test_diary_client_resolves_the_official_eli_link(tmp_path):
    from unittest.mock import patch
    from legalize.fetcher.cache import FileCache
    from legalize.fetcher.es.client import BOEClient
    from legalize.fetcher.es.config import BOEConfig

    with BOEClient(BOEConfig(), FileCache(tmp_path)) as client:
        with patch.object(
            client,
            "_fetch",
            side_effect=[b'<a href="/eli/es/ref/2026/05/19/(1)/dof">ELI</a>', b"<documento/>"],
        ) as fetch:
            assert client.get_disposition_xml("BOE-A-2026-10881") == b"<documento/>"
            assert (
                fetch.call_args.args[0]
                == "https://www.boe.es/eli/es/ref/2026/05/19/(1)/dof/spa/xml"
            )
        with patch.object(client, "_fetch", return_value=b"<html>No ELI link</html>"):
            with pytest.raises(ValueError, match="no ELI"):
                client.get_disposition_xml("BOE-A-2026-10881")


def test_expansion_resume_retains_bytes_and_exclusions(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from unittest.mock import MagicMock
    import json
    from legalize.config import Config, CountryConfig
    from scripts.fetch_es_expansion import fetch_tranche

    identifier = "BOE-A-2026-10881"
    raw = payload("sample-not-consolidated", "diary")
    client = MagicMock()
    client.get_disposition_xml.return_value = raw
    monkeypatch.setattr(
        "scripts.fetch_es_expansion.BOEClient.create", lambda _: nullcontext(client)
    )
    monkeypatch.setattr(
        "scripts.fetch_es_expansion.fetch_diary",
        lambda client, ident, **kwargs: parse_diary(kwargs["xml_data"], ident),
    )
    config = Config(countries={"es": CountryConfig(data_dir=str(tmp_path))})
    identifiers = [identifier, "BOE-A-2020-999"]
    report = fetch_tranche(config, identifiers, {identifiers[1]})
    assert report["counts"] == {"fetched": 1, "excluded": 1}
    assert (tmp_path / "diary-raw" / f"{identifier}.xml.gz").exists()
    assert (
        json.loads((tmp_path / "excluded" / f"{identifiers[1]}.json").read_text())["reason"]
        == "source-suppressed"
    )
    client.get_disposition_xml.reset_mock()
    report = fetch_tranche(config, identifiers, {identifiers[1]})
    assert report["counts"] == {"cached": 1, "excluded": 1}
    client.get_disposition_xml.assert_not_called()


def test_judicial_page_without_eli_has_an_explicit_exclusion(tmp_path):
    from unittest.mock import patch
    from legalize.fetcher.cache import FileCache
    from legalize.fetcher.es.client import BOEClient
    from legalize.fetcher.es.config import BOEConfig

    page = b"<title>BOE-A-2010-10712 Sentencia de 9 de marzo de 2010</title><dl><dt>Departamento:</dt><dd>Tribunal Supremo</dd></dl>"
    with BOEClient(BOEConfig(), FileCache(tmp_path)) as client:
        with patch.object(client, "_fetch", return_value=page):
            with pytest.raises(ExcludedDiary, match="judicial-or-correction"):
                client.get_disposition_xml("BOE-A-2010-10712")


def test_all_diary_sample_text_survives_outside_table_cell_styles():
    import gzip
    import json
    from pathlib import Path
    import yaml

    fixtures = Path(__file__).parent / "fixtures" / "es"
    for sample in json.loads((fixtures / "diary-samples.json").read_text()):
        norm = parse_diary(
            gzip.decompress((fixtures / sample["file"]).read_bytes()), sample["identifier"]
        )
        body = render_norm_at_date(norm.metadata, norm.blocks, norm.metadata.publication_date)
        front = yaml.safe_load(body.split("---", 2)[1])
        if sample["identifier"] == "BOE-A-2013-9074":
            assert "Lista de menciones tradicionales específicas para el vino" in body
            assert front["article_count"] == 252
            assert "**Madrid, 31 de julio de 2013" in body
        if sample["identifier"] == "BOE-A-2026-10881":
            assert front["article_count"] == 1
            assert "**PEDRO SÁNCHEZ PÉREZ-CASTEJÓN**" in body


@pytest.mark.parametrize(
    "rank,title", [("Providencia", "Incidente de ejecución"), ("Auto", "Pleno. Auto")]
)
def test_judicial_html_rank_excludes_unusual_titles(tmp_path, rank, title):
    from unittest.mock import patch
    from legalize.fetcher.cache import FileCache
    from legalize.fetcher.es.client import BOEClient
    from legalize.fetcher.es.config import BOEConfig

    page = f'<title>BOE-A-2016-11868 {title}</title><div id="analisis"><ul><li>Rango: {rank}</li></ul></div>'
    with BOEClient(BOEConfig(), FileCache(tmp_path)) as client:
        with patch.object(client, "_fetch", return_value=page.encode()):
            with pytest.raises(ExcludedDiary, match="judicial-or-correction"):
                client.get_disposition_xml("BOE-A-2016-11868")


def test_inline_emphasis_cannot_join_legal_words():
    from legalize.transformer.xml_parser import _cell_text

    cell = etree.fromstring(b"<td><em>Cichorium </em>spp. and<strong> bold </strong>words</td>")
    assert _cell_text(cell) == "*Cichorium* spp. and **bold** words"
    cell = etree.fromstring("<td>A<sub>i </sub>= x<sup> </sup>y</td>".encode())
    assert _cell_text(cell) == "A<sub>i</sub> = x y"


@pytest.mark.parametrize(
    "identifier,paragraphs",
    [("BOE-A-2010-2329", 43), ("BOE-A-2011-20178", 12), ("BOE-A-2014-3187", 6)],
)
def test_original_html_without_eli_preserves_the_source(identifier, paragraphs):
    import gzip
    from pathlib import Path
    from lxml import html
    from legalize.fetcher.es.diary import diary_xml_from_html

    page = html.fromstring(
        gzip.decompress(
            (Path(__file__).parent / "fixtures" / "es" / f"diary-{identifier}.html.gz").read_bytes()
        )
    )
    norm = parse_diary(diary_xml_from_html(page, identifier), identifier)
    assert len(norm.blocks[0].versions[0].paragraphs) == paragraphs
    assert norm.metadata.source == f"https://www.boe.es/buscar/doc.php?id={identifier}"
    assert norm.metadata.text_state is TextState.AS_ENACTED
    assert dict(norm.metadata.extra)["source_format"] == "html"
    assert norm.metadata.pdf_url.endswith(identifier + ".pdf")
    assert dict(norm.metadata.extra)["url_epub"].startswith("https://www.boe.es/")


def test_old_official_pdf_names_still_supply_publication_dates(tmp_path):
    from datetime import date
    from unittest.mock import patch
    from legalize.fetcher.cache import FileCache
    from legalize.fetcher.es.client import BOEClient
    from legalize.fetcher.es.config import BOEConfig

    page = '<a title="Documento PDF de la publicación original" href="/boe/dias/2008/10/10/pdfs/T00003-00014.pdf">PDF</a>'
    with BOEClient(BOEConfig(), FileCache(tmp_path)) as client:
        with patch.object(client, "_fetch", return_value=page.encode()):
            assert client.get_publication_date("BOE-T-2008-16292") == date(2008, 10, 10)
