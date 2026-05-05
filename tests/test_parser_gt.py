from datetime import date
from pathlib import Path

from legalize.fetcher.gt.parser import GTMetadataParser, GTTextParser


FIXTURES = Path("tests/fixtures/gt")


def test_parse_laip_structure():
    data = (FIXTURES / "sample-ordinary-law-laip-official.txt").read_bytes()

    blocks = GTTextParser().parse_text(data)

    articles = [block for block in blocks if block.block_type == "article"]
    titles = [block for block in blocks if block.block_type == "title"]
    chapters = [block for block in blocks if block.block_type == "chapter"]

    assert len(articles) >= 70
    assert len(titles) >= 5
    assert len(chapters) >= 10
    assert any("Artículo 1. Objeto de la Ley" in block.title for block in articles)


def test_parse_decreto_13_2013_publication_date():
    data = (FIXTURES / "reform-decree-13-2013.txt").read_bytes()

    blocks = GTTextParser().parse_text(data)

    assert blocks
    assert all(
        version.publication_date == date(2013, 11, 12)
        for block in blocks
        for version in block.versions
    )


def test_metadata_laip():
    data = (FIXTURES / "sample-ordinary-law-laip-official.txt").read_bytes()

    meta = GTMetadataParser().parse(data, "decreto-57-2008")

    assert meta.country == "gt"
    assert meta.identifier == "decreto-57-2008"
    assert meta.title == "Ley de Acceso a la Información Pública"
    assert meta.rank == "decreto"
    assert meta.pdf_url
    assert ("decree_number", "57-2008") in meta.extra


def test_metadata_decreto_13_2013():
    data = (FIXTURES / "reform-decree-13-2013.txt").read_bytes()

    meta = GTMetadataParser().parse(data, "decreto-13-2013")

    assert meta.publication_date == date(2013, 11, 12)
    assert ("effective_date_candidate", "2013-11-20") in meta.extra


def test_gt_registry_dispatch():
    from legalize.countries import (
        get_client_class,
        get_discovery_class,
        get_metadata_parser,
        get_text_parser,
    )
    from legalize.fetcher.gt.client import GTFixtureClient
    from legalize.fetcher.gt.discovery import GTFixtureDiscovery
    from legalize.fetcher.gt.parser import GTMetadataParser, GTTextParser

    assert get_client_class("gt") is GTFixtureClient
    assert get_discovery_class("gt") is GTFixtureDiscovery
    assert isinstance(get_text_parser("gt"), GTTextParser)
    assert isinstance(get_metadata_parser("gt"), GTMetadataParser)
