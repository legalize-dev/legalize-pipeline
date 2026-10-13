"""The official legacy XML contains a nonstandard processing instruction."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from legalize.fetcher.ie.effects import fetch_effects
from legalize.fetcher.ie.parser import ISBMetadataParser, ISBTextParser

FIXTURES = Path(__file__).parent / "fixtures/ie"


@pytest.mark.parametrize("identifier", ["IE-1937-act-38", "IE-1927-act-39"])
def test_nonstandard_processing_instruction_keeps_the_xml_parsers(identifier):
    data = (FIXTURES / f"sample-{identifier.lower()}-processing-instruction.xml").read_bytes()
    assert data.startswith(b'<?version xml="1.0"?>')
    metadata = ISBMetadataParser().parse(data, identifier)
    version = ISBTextParser().parse_text(data)[0].versions[0]
    assert metadata.identifier == identifier
    assert version.publication_date == metadata.publication_date
    assert len(version.paragraphs) > 50
    assert not any(
        "<p " in paragraph.text or "</font>" in paragraph.text for paragraph in version.paragraphs
    )


def test_effects_discovery_gets_html_links_for_legacy_xml():
    identifier = "IE-1937-act-38"
    data = (FIXTURES / f"sample-{identifier.lower()}-processing-instruction.xml").read_bytes()
    client = Mock(_base_url="https://www.irishstatutebook.ie")
    client._get.side_effect = [
        b'<a href="/isbc/1937_38.html">Directory</a>',
        b'<h3 id="effects">Effects</h3><table><tr><td>Not affected</td><td></td></tr></table>',
    ]
    assert fetch_effects(client, identifier, data) == []
    assert client._get.call_count == 2
