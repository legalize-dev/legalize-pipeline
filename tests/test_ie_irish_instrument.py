"""An Irish-only official instrument remains Irish and retains its source identity."""

from datetime import date
from pathlib import Path

import pytest
import requests
import responses

from legalize.fetcher.ie.client import ISBClient
from legalize.fetcher.ie.parser import ISBMetadataParser, ISBTextParser

FIXTURES = Path(__file__).parent / "fixtures/ie"
BASE = "https://www.irishstatutebook.ie"


@responses.activate
def test_404_uses_only_the_matching_irish_manifestation_listed_in_the_index():
    raw = (FIXTURES / "sample-ie-1989-si-28-irish.html").read_bytes()
    index = (FIXTURES / "sample-si-index-1989-irish.html").read_bytes()
    responses.get(BASE + "/eli/1989/si/28/made/en/html", status=404)
    responses.get(BASE + "/eli/1989/si", body=index)
    responses.get(BASE + "/1989/ga/si/0028.html", body=raw)
    with ISBClient(requests_per_second=0, max_retries=1) as client:
        data = client.get_metadata("IE-1989-si-28")
    assert data == raw
    metadata = ISBMetadataParser().parse(data, "IE-1989-si-28")
    version = ISBTextParser().parse_text(data)[0].versions[0]
    assert metadata.publication_date == version.publication_date == date(1989, 2, 8)
    assert dict(metadata.extra)["language"] == "ga"
    assert metadata.source == BASE + "/eli/1989/si/28/made/ga/html"
    assert "An tOrdú Staidrimh" in metadata.title
    assert "an 8ú lá seo de Feabhra 1989" in " ".join(p.text for p in version.paragraphs)
    assert any("De bhun na gcumhachtaí" in p.text for p in version.paragraphs)


@responses.activate
def test_another_instrument_or_server_failure_cannot_trigger_language_fallback():
    responses.get(BASE + "/eli/1989/si/28/made/en/html", status=404)
    responses.get(BASE + "/eli/1989/si", body=b'<a href="/1989/ga/si/0029.html">Other</a>')
    with ISBClient(requests_per_second=0, max_retries=1) as client:
        with pytest.raises(requests.HTTPError, match="404"):
            client.get_enacted_text("IE-1989-si-28")
    assert len(responses.calls) == 2
    responses.reset()
    responses.get(BASE + "/eli/1989/si/28/made/en/html", status=503)
    with ISBClient(requests_per_second=0, max_retries=1) as client:
        with pytest.raises(requests.HTTPError, match="503"):
            client.get_enacted_text("IE-1989-si-28")
    assert len(responses.calls) == 1


def test_an_irish_document_cannot_overwrite_a_different_identity():
    raw = (FIXTURES / "sample-ie-1989-si-28-irish.html").read_bytes()
    with pytest.raises(ValueError, match="different instrument"):
        ISBMetadataParser().parse(raw, "IE-1989-si-29")
