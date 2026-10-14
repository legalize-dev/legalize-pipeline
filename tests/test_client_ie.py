"""Identity-safe Irish downloads, metadata fallback and persistent HTTP caching."""

from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

import pytest
import requests
import responses

from legalize.config import CountryConfig
from legalize.fetcher.cache import FileCache
from legalize.fetcher.ie.client import CONSTITUTION_ID, ISBClient, _parse_norm_id, refresh_sources

ISB = "https://www.irishstatutebook.ie"
API = "https://api.oireachtas.ie/v1/legislation"
FIXTURES = Path(__file__).parent / "fixtures" / "ie"


@pytest.mark.parametrize(
    ("norm_id", "expected"),
    [
        ("IE-2024-act-1", (2024, "act", "1")),
        ("IE-2015-act-C34", (2015, "ca", "34")),
        ("IE-2023-act-P1", (2023, "prv", "1")),
        ("IE-2024-si-356", (2024, "si", "356")),
    ],
)
def test_identity_namespaces(norm_id, expected):
    assert _parse_norm_id(norm_id) == expected


@pytest.mark.parametrize(
    "norm_id", ["GB-2024-act-1", "IE-2024-act-0", "IE-2024-act-01", "IE-2024-si-P1", "IE-1"]
)
def test_invalid_identity_is_rejected(norm_id):
    with pytest.raises(ValueError):
        _parse_norm_id(norm_id)


@responses.activate
def test_missing_api_metadata_uses_real_enacted_source():
    source = (FIXTURES / "sample-v04-isb-private-2023-act-1.xml").read_bytes()
    responses.get(API, json={"results": []})
    responses.get(f"{ISB}/eli/2023/prv/1/enacted/en/xml", body=source)
    with ISBClient(requests_per_second=0) as client:
        assert client.get_metadata("IE-2023-act-P1") == source
    assert any("act_no=P1" in call.request.url for call in responses.calls)


@responses.activate
def test_mismatched_api_act_cannot_overwrite_private_act():
    source = (FIXTURES / "sample-v04-isb-private-2023-act-1.xml").read_bytes()
    responses.get(
        API,
        json={
            "results": [
                {
                    "bill": {
                        "act": {
                            "actYear": "2023",
                            "actNo": "1",
                            "shortTitleEn": "Wrong public act",
                            "dateSigned": "2023-01-01",
                        }
                    }
                }
            ]
        },
    )
    responses.get(f"{ISB}/eli/2023/prv/1/enacted/en/xml", body=source)
    with ISBClient(requests_per_second=0) as client:
        assert client.get_metadata("IE-2023-act-P1") == source


@responses.activate
def test_xml_404_falls_back_but_server_errors_do_not():
    base = f"{ISB}/eli/1960/act/13/enacted/en"
    responses.get(base + "/xml", status=404)
    responses.get(base + "/print", body=b"<html>Full Act</html>")
    with ISBClient(requests_per_second=0, max_retries=1) as client:
        assert client.get_enacted_text("IE-1960-act-13") == b"<html>Full Act</html>"
    responses.reset()
    responses.get(base + "/xml", status=503)
    with ISBClient(requests_per_second=0, max_retries=1) as client:
        with pytest.raises(requests.HTTPError, match="503"):
            client.get_enacted_text("IE-1960-act-13")
    assert len(responses.calls) == 1


@responses.activate
def test_transient_catalogue_403_retries_but_persistent_denial_still_fails(tmp_path):
    url = f"{ISB}/eli/2022/act"
    responses.get(url, status=403)
    responses.get(url, body=b"complete catalogue")
    cache = FileCache(tmp_path)
    with (
        patch("legalize.fetcher.base.time.sleep"),
        ISBClient(cache=cache, requests_per_second=0, max_retries=2) as client,
    ):
        assert client.get_act_index(2022) == b"complete catalogue"
    assert len(responses.calls) == 2
    responses.reset()
    responses.get(url, status=403)
    with (
        patch("legalize.fetcher.base.time.sleep"),
        ISBClient(cache=cache, requests_per_second=0, max_retries=2) as client,
    ):
        with pytest.raises(requests.HTTPError, match="403"):
            client.get_act_index(2022, refresh=True)
    assert len(responses.calls) == 2
    assert cache.get(url).content == b"complete catalogue"


@responses.activate
def test_constitution_and_affecting_si_use_source_metadata_without_api():
    responses.get(f"{ISB}/eli/cons/en/html", body=b"<html>Constitution</html>")
    responses.get(f"{ISB}/eli/2024/si/356/made/en/html", body=b"<html>Instrument</html>")
    with ISBClient(requests_per_second=0) as client:
        assert client.get_metadata(CONSTITUTION_ID) == b"<html>Constitution</html>"
        assert client.get_metadata("IE-2024-si-356") == b"<html>Instrument</html>"
    assert all(call.request.url.startswith(ISB) for call in responses.calls)


@responses.activate
def test_cache_survives_client_and_distinguishes_query_strings(tmp_path):
    url = "https://rev-acts.s3.eu-west-1.amazonaws.com/1995/2/act_plain.pdf"
    responses.get(url + "?versionId=old", body=b"old PDF")
    responses.get(url + "?versionId=new", body=b"new PDF")
    with ISBClient(cache=FileCache(tmp_path), requests_per_second=0) as client:
        assert client._get(url, params={"versionId": "old"}) == b"old PDF"
        assert client._get(url, params={"versionId": "new"}) == b"new PDF"
    with ISBClient(cache=FileCache(tmp_path), requests_per_second=0) as client:
        assert client._get(url, params={"versionId": "old"}) == b"old PDF"
    assert len(responses.calls) == 2


@responses.activate
def test_refresh_fetches_and_updates_cached_index(tmp_path):
    url = f"{ISB}/eli/2026/act"
    responses.get(url, body=b"old index")
    responses.get(url, body=b"new index")
    with ISBClient(cache=FileCache(tmp_path), requests_per_second=0) as client:
        assert client.get_act_index(2026) == b"old index"
        assert client.get_act_index(2026) == b"old index"
        assert client.get_act_index(2026, refresh=True) == b"new index"
        assert client.get_act_index(2026) == b"new index"
    assert len(responses.calls) == 2


@responses.activate
def test_run_refreshes_mutable_sources_once_across_clients_and_restores_scope(tmp_path):
    url = f"{ISB}/isbc/1995_2.html"
    cache = FileCache(tmp_path)
    cache.put(url, b"previous run", {})
    responses.get(url, body=b"current run")
    with refresh_sources():
        with ISBClient(cache=cache, requests_per_second=0) as client:
            assert client._get(url) == b"current run"
        with refresh_sources(), ISBClient(cache=cache, requests_per_second=0) as client:
            assert client._get(url) == b"current run"
    with ISBClient(cache=cache, requests_per_second=0) as client:
        assert client._get(url) == b"current run"
    assert len(responses.calls) == 1

    responses.get(url, body=b"next run")
    with pytest.raises(RuntimeError), refresh_sources():
        with ISBClient(cache=cache, requests_per_second=0) as client:
            assert client._get(url) == b"next run"
        raise RuntimeError("Interrupted run")
    with ISBClient(cache=cache, requests_per_second=0) as client:
        assert client._get(url) == b"next run"
    assert len(responses.calls) == 2


@responses.activate
def test_run_reuses_old_immutable_archives_but_refreshes_unversioned_pdf(tmp_path):
    url = "https://rev-acts.s3.eu-west-1.amazonaws.com/1995/2/act_plain.pdf"
    cache = FileCache(tmp_path)
    with patch("legalize.fetcher.cache.time.time", return_value=1_000_000_000):
        cache.put(url + "?versionId=original", b"historic PDF", {})
        cache.put(url, b"old current PDF", {})
    responses.get(url, body=b"updated current PDF")
    with refresh_sources(), ISBClient(cache=cache, requests_per_second=0) as client:
        assert client._get(url, params={"versionId": "original"}) == b"historic PDF"
        assert client._get(url) == b"updated current PDF"
    assert len(responses.calls) == 1


@responses.activate
@pytest.mark.parametrize("query", ["?versionId=null", "?versionId=", ""])
def test_mutable_s3_objects_refresh_without_changing_the_source_url(tmp_path, query):
    url = "https://rev-acts.s3.eu-west-1.amazonaws.com/1995/2/act_plain.pdf" + query
    cache = FileCache(tmp_path)
    cache.put(url, b"previous PDF", {})
    responses.get(url, body=b"updated PDF")
    with refresh_sources():
        for _ in range(2):
            with ISBClient(cache=cache, requests_per_second=0) as client:
                assert client._get(url) == b"updated PDF"
    assert len(responses.calls) == 1
    assert responses.calls[0].request.url == url


@responses.activate
def test_worker_clients_share_refresh_scope_and_download_one_mutable_url(tmp_path):
    import time

    url = f"{ISB}/isbc/1995_2.html"
    cache = FileCache(tmp_path)
    cache.put(url, b"previous run", {})

    def download(_request):
        time.sleep(0.02)
        return 200, {}, b"current run"

    responses.add_callback(responses.GET, url, callback=download)

    def fetch(_index):
        with ISBClient(cache=FileCache(tmp_path), requests_per_second=0) as client:
            return client._get(url)

    with refresh_sources(), ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(fetch, range(2))) == [b"current run", b"current run"]
    assert len(responses.calls) == 1


def test_factory_places_raw_cache_under_country_data(tmp_path):
    with ISBClient.create(CountryConfig(data_dir=str(tmp_path))) as client:
        assert client._cache._dir == tmp_path / "raw"


def test_get_text_delegates_history_with_existing_metadata():
    with patch("legalize.fetcher.ie.history.fetch_text", return_value=b"history") as fetch:
        with ISBClient(requests_per_second=0) as client:
            assert client.get_text("IE-1995-act-2", b"metadata") == b"history"
            fetch.assert_called_once_with(client, "IE-1995-act-2", b"metadata")


@responses.activate
def test_metadata_envelope_uses_enacted_authority_over_inconsistent_parliament_fields():
    import base64
    import json
    from datetime import date

    from legalize.fetcher.ie.parser import ISBMetadataParser

    enacted = (FIXTURES / "sample-v04-isb-1922-act-1.xml").read_bytes()
    parliament = (FIXTURES / "sample-v04-parliament-1922-act-1.json").read_bytes()
    responses.get(f"{ISB}/eli/1922/act/1/enacted/en/xml", body=enacted)
    responses.get(API, body=parliament)
    with ISBClient(requests_per_second=0) as client:
        raw = client.get_metadata("IE-1922-act-1")
    envelope = json.loads(raw)
    assert envelope["legalize_ie_metadata"] == 1
    assert base64.b64decode(envelope["enacted"]) == enacted
    assert envelope["parliament"] == json.loads(parliament)
    metadata = ISBMetadataParser().parse(raw, "IE-1922-act-1")
    assert metadata.publication_date == date(1922, 12, 6)
    assert metadata.title.startswith("CONSTITUTION OF THE IRISH FREE STATE")
    assert metadata.pdf_url is None  # The API exposes a bill PDF, not the enacted Act.
    extra = dict(metadata.extra)
    assert extra["publication_date_basis"] == "isb_enactment_date"
    assert extra["enactment_date"] == "1922-12-06"
    assert extra["parliament_date_signed"] == "1922-10-25"
    assert extra["parliament_title_ga"].startswith("Constitution of the Irish Free State")
    assert "title_ga" not in extra  # The API swapped its language-labelled titles.
    assert json.loads(extra["parliament_metadata"]) == json.loads(parliament)["results"][0]["bill"]


@responses.activate
def test_source_authority_does_not_require_optional_api_title_or_signature_date():
    from datetime import date

    from legalize.fetcher.ie.parser import ISBMetadataParser

    enacted = (FIXTURES / "sample-v04-isb-1922-act-1.xml").read_bytes()
    responses.get(f"{ISB}/eli/1922/act/1/enacted/en/xml", body=enacted)
    responses.get(API, json={"results": [{"bill": {"act": {"actYear": "1922", "actNo": "1"}}}]})
    with ISBClient(requests_per_second=0) as client:
        metadata = ISBMetadataParser().parse(client.get_metadata("IE-1922-act-1"), "IE-1922-act-1")
    assert metadata.publication_date == date(1922, 12, 6)
    assert "parliament_metadata" in dict(metadata.extra)


def _fetch_revised_html(monkeypatch, source, *, with_pdf=True):
    import json
    from unittest.mock import Mock

    from legalize.fetcher.ie import effects, history

    identifier = "IE-2024-act-2"
    enacted = b"""<act><metadata><title>Digital Services Act 2024</title><number>2</number>
    <year>2024</year><dateofenactment>20240211</dateofenactment></metadata>
    <body><sect><number>1.</number><p>Original text.</p></sect></body></act>"""
    row = {
        "format": "revised_html",
        "url": "https://source.test/current.html",
        "catalog_date": "2026-01-01",
        **({"pdf_url": "https://source.test/current.pdf"} if with_pdf else {}),
    }
    pdf = (FIXTURES / "archive-digital-services-2026.pdf").read_bytes()
    sources = {
        history.REVISED_INDEX: b"catalogue",
        row["url"]: source,
        "https://source.test/current.pdf": pdf,
    }
    client = Mock()
    client.get_enacted_text.return_value = enacted
    client._get.side_effect = sources.__getitem__
    monkeypatch.setattr(history, "revised_catalog", lambda _: {identifier: (row,)})
    monkeypatch.setattr(effects, "fetch_effects", lambda *args, **kwargs: [])
    return json.loads(history.fetch_text(client, identifier, enacted)), client


def _digital_html_without_preamble_reference():
    from lxml import html

    doc = html.fromstring((FIXTURES / "archive-digital-services-2026.html").read_bytes())
    # The real source already omits definition 1. Remove only its reference to
    # isolate body/backmatter omissions instead of passing via the preamble case.
    for marker in doc.xpath('//div[@class="frontmatter"]//sup'):
        marker.drop_tree()
    return doc


def test_revised_body_undefined_superscript_uses_complete_official_pdf(monkeypatch):
    import base64
    from lxml import html

    doc = _digital_html_without_preamble_reference()
    for footer in doc.xpath('//footer[.//sup[text()="2"]]'):
        footer.drop_tree()
    source = html.tostring(doc)
    from legalize.fetcher.ie.history import _missing_footnotes
    from legalize.fetcher.ie.parser import parse_revised_html

    paragraphs, _ = parse_revised_html(source)
    assert "2022^2" in "\n".join(p.text for p in paragraphs)
    assert _missing_footnotes(paragraphs) == set()
    assert _missing_footnotes(paragraphs, source_html=source) == {"2"}
    envelope, _ = _fetch_revised_html(monkeypatch, source)
    current = envelope["versions"][-1]
    assert current["format"] == "current_pdf"
    assert current["url"] == "https://source.test/current.pdf"
    assert (
        base64.b64decode(current["data"])
        == (FIXTURES / "archive-digital-services-2026.pdf").read_bytes()
    )


@pytest.mark.parametrize("root", ["body", "backmatter"])
def test_unlinked_superscripts_in_all_normative_roots_trigger_fallback(monkeypatch, root):
    from lxml import etree, html

    doc = _digital_html_without_preamble_reference()
    destination = doc.xpath(f'//div[@class="{root}"]')[0]
    paragraph = etree.SubElement(destination, "p")
    paragraph.text = "The Regulation"
    marker = etree.SubElement(paragraph, "sup")
    marker.text, marker.tail = "9", " applies."
    envelope, _ = _fetch_revised_html(monkeypatch, html.tostring(doc))
    assert envelope["versions"][-1]["format"] == "current_pdf"


def test_undefined_numeric_superscript_without_pdf_fails_closed(monkeypatch):
    source = (FIXTURES / "archive-digital-services-2026.html").read_bytes()
    with pytest.raises(ValueError, match="undefined normative footnotes"):
        _fetch_revised_html(monkeypatch, source, with_pdf=False)


def test_revised_scan_excludes_editorial_and_definition_superscripts(monkeypatch):
    from lxml import etree, html

    doc = _digital_html_without_preamble_reference()
    body = doc.xpath('//div[@class="body"]')[0]
    for kind in ("annotations", "actsreferredto", "narrative"):
        node = etree.SubElement(body, "div", {"class": kind})
        etree.SubElement(etree.SubElement(node, "p"), "sup").text = "9"
    envelope, client = _fetch_revised_html(monkeypatch, html.tostring(doc), with_pdf=False)
    assert envelope["versions"][-1]["format"] == "revised_html"
    assert not any(call.args[0].endswith(".pdf") for call in client._get.call_args_list)


def test_numeric_exponent_is_not_silently_assumed_to_be_a_defined_footnote(monkeypatch):
    from lxml import html

    doc = _digital_html_without_preamble_reference()
    doc.xpath('//div[@class="body"]')[0].append(html.fromstring("<p>Formula: x<sup>9</sup>.</p>"))
    # Bare superscripts are ambiguous in LRC's HTML. Switching to the full PDF
    # preserves source content without inventing a footnote or guessing its role.
    envelope, _ = _fetch_revised_html(monkeypatch, html.tostring(doc))
    assert envelope["versions"][-1]["format"] == "current_pdf"
