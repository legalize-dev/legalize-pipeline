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
