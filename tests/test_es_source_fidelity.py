"""Fresh BOE samples must survive fetching, caching and historical rendering."""

import gzip
import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
import yaml

from legalize.config import Config, CountryConfig
from legalize.fetcher.es.metadata import parse_metadata
from legalize.fetcher.es.parser import BOETextParser
from legalize.models import Block, Paragraph, ParsedNorm, Version
from legalize.pipeline import generic_fetch_one
from legalize.storage import load_norma_from_json, save_structured_json
from legalize.transformer.markdown import render_norm_at_date
from legalize.transformer.xml_parser import extract_reforms, parse_text_xml

FIXTURES = Path(__file__).parent / "fixtures" / "es"
SAMPLES = json.loads((FIXTURES / "samples.json").read_text())
CONSOLIDATED = [name for name, sample in SAMPLES.items() if "text" in sample["files"]]


def payload(name, kind):
    return gzip.decompress((FIXTURES / SAMPLES[name]["files"][kind]).read_bytes())


def parsed(name):
    metadata = parse_metadata(
        payload(name, "metadata"), SAMPLES[name]["identifier"], payload(name, "diary")
    )
    blocks = BOETextParser().parse_text(payload(name, "text"))
    return ParsedNorm(metadata, tuple(blocks), tuple(extract_reforms(blocks)))


@pytest.mark.parametrize("name", CONSOLIDATED)
def test_latest_published_snapshot_includes_delayed_commencement(name, tmp_path):
    norm = parsed(name)
    latest = norm.reforms[-1]
    horizon = max(v.in_force_from for b in norm.blocks for v in b.versions)
    expected = render_norm_at_date(norm.metadata, norm.blocks, horizon)
    actual = render_norm_at_date(norm.metadata, norm.blocks, latest.date, source_id=latest.norm_id)
    assert actual == expected
    cached = load_norma_from_json(save_structured_json(tmp_path, norm))
    assert (
        render_norm_at_date(cached.metadata, cached.blocks, latest.date, source_id=latest.norm_id)
        == actual
    )
    frontmatter = yaml.safe_load(actual.split("---", 2)[1])
    assert frontmatter["last_updated"] == horizon.isoformat()
    assert frontmatter["identifier"] == norm.metadata.identifier
    assert frontmatter["pdf_url"]
    extra = dict(norm.metadata.extra)
    assert extra["source_updated_at"].endswith("Z")
    assert extra["entry_into_force"]
    assert extra["consolidation_status_code"]
    assert json.loads(extra["eli_metadata"])
    assert not any(ord(c) < 32 and c not in "\n\t" for c in actual)
    assert not actual.endswith("\n\n")


def test_publication_snapshot_does_not_leak_later_retroactive_text():
    metadata = parsed("sample-constitution").metadata
    versions = (
        Version(
            "original", date(2020, 1, 1), date(2020, 2, 1), (Paragraph("parrafo", "Original"),)
        ),
        Version("reform", date(2020, 3, 1), date(2020, 4, 1), (Paragraph("parrafo", "Changed"),)),
        Version(
            "later", date(2020, 5, 1), date(2020, 4, 1), (Paragraph("parrafo", "Retroactive"),)
        ),
    )
    blocks = [Block("a1", "precepto", "Article 1", versions)]
    before = render_norm_at_date(metadata, blocks, date(2020, 3, 1), source_id="reform")
    assert "Changed" in before and "Retroactive" not in before
    strict = render_norm_at_date(metadata, blocks, date(2020, 3, 1))
    assert "Original" in strict and "Changed" not in strict
    after = render_norm_at_date(metadata, blocks, date(2020, 5, 1), source_id="later")
    assert "Retroactive" in after and "Changed" not in after


def test_expired_editorial_notes_disappear_and_survive_cache(tmp_path):
    norm = parsed("sample-constitution")
    blocks = parse_text_xml(
        b"""<texto><bloque id="a1"><version id_norma="X" fecha_publicacion="20200101" fecha_vigencia="20200101"><p class="parrafo">Operative text.</p><blockquote caduca="20200201"><p class="parrafo">Prior wording.</p></blockquote></version></bloque></texto>"""
    )
    norm = replace(norm, blocks=tuple(blocks), reforms=tuple(extract_reforms(blocks)))
    norm = load_norma_from_json(save_structured_json(tmp_path, norm))
    assert "Prior wording" in render_norm_at_date(norm.metadata, norm.blocks, date(2020, 1, 1))
    after = render_norm_at_date(norm.metadata, norm.blocks, date(2020, 2, 1))
    assert "Prior wording" not in after and "Operative text" in after


def test_generic_fetch_uses_diary_enrichment_and_rejects_transient_failure(tmp_path):
    name = "sample-code"
    norm_id = SAMPLES[name]["identifier"]
    config = Config(
        countries={"es": CountryConfig(data_dir=str(tmp_path), cache_dir=str(tmp_path / "cache"))}
    )
    with patch("legalize.fetcher.es.client.BOEClient") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.get_metadata.return_value = payload(name, "metadata")
        client.get_consolidated_text.return_value = payload(name, "text")
        client.get_disposition_xml.return_value = payload(name, "diary")
        norm = generic_fetch_one(config, "es", norm_id)
        assert norm is not None and norm.metadata.subjects and norm.metadata.pdf_url
        assert "Las modificaciones" in dict(norm.metadata.extra)["notes"]
        client.get_disposition_xml.side_effect = requests.Timeout("Temporary outage")
        assert generic_fetch_one(config, "es", norm_id, force=True) is None
        assert load_norma_from_json(tmp_path / "json" / f"{norm_id}.json").metadata.pdf_url


def test_table_cells_preserve_inline_formulas_prose_and_nested_grids():
    from lxml import etree
    from legalize.transformer.xml_parser import _cell_text, _table_paragraph

    cell = etree.fromstring(
        b"<td>Formula C<sub>18</sub>H<sub>20</sub>O<sub>6</sub>N<sub>2</sub> followed by prose.<p>First</p><p>Second</p></td>"
    )
    assert (
        _cell_text(cell)
        == "Formula C<sub>18</sub>H<sub>20</sub>O<sub>6</sub>N<sub>2</sub> followed by prose. First  Second"
    )
    source = etree.fromstring(
        b'<table class="source"><tr><td>Outer</td><td><table><thead><tr><th>Element</th><th>Minimum</th></tr></thead><tr><td>Cu</td><td>1</td></tr></table></td></tr></table>'
    )
    result = _table_paragraph(source)
    rebuilt = etree.fromstring(result.text.encode())
    assert len(list(rebuilt.iter("table"))) == 2
    assert rebuilt.findtext("tr/td/table/tr/td") == "Cu"
    assert rebuilt.findtext("tr/td/table/thead/tr/th") == "Element"
    assert "class=" not in result.text


def test_visual_indentation_is_not_a_markdown_code_block():
    from legalize.transformer.markdown import render_paragraphs

    for css in ("sangrado", "sangrado_2", "sangrado_articulo"):
        assert render_paragraphs([Paragraph(css, "Nota: substantive qualification.")]).startswith(
            "Nota:"
        )
