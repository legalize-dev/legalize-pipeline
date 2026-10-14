"""eISB Act discovery covers all namespaces without relying on API coverage."""

from unittest.mock import Mock

import pytest

from legalize.fetcher.ie.client import CONSTITUTION_ID
from legalize.fetcher.ie.discovery import ISBDiscovery, _index_norm_ids

INDEX = b"""<html><table><tbody>
<tr><td><a href="en/act/pub/0001/index.html">Public Act</a></td></tr>
<tr><td><a href="ga/act/pub/0001/index.html">Irish public Act</a></td></tr>
<tr><td><a href="en/act/prv/0001/index.html">Private Act</a></td></tr>
<tr><td><a href="en/act/cam/0034/index.html">Constitution amendment</a></td></tr>
<tr><td><a href="../pdf/2023/en.act.2023.0002.pdf">PDF-only Act</a></td></tr>
<tr><td><a href="/2023/en/si/0001.html">SI is outside bulk scope</a></td></tr>
</tbody></table></html>"""


def test_index_deduplicates_languages_preserves_types_and_pdf_only():
    assert _index_norm_ids(INDEX, 2023) == [
        "IE-2023-act-1",
        "IE-2023-act-P1",
        "IE-2023-act-C34",
        "IE-2023-act-2",
    ]


def test_all_discovers_source_index_and_constitution_without_api():
    client = Mock()
    client.get_act_index.return_value = INDEX
    assert list(ISBDiscovery().discover_all(client, year_from=2023, year_to=2023)) == [
        CONSTITUTION_ID,
        "IE-2023-act-1",
        "IE-2023-act-P1",
        "IE-2023-act-C34",
        "IE-2023-act-2",
    ]
    client.get_act_index.assert_called_once_with(2023)
    client.get_legislation_page.assert_not_called()


@pytest.mark.parametrize("data", [b"<html>Maintenance</html>", b"<table><tbody></tbody></table>"])
def test_empty_or_changed_source_does_not_silently_hide_a_year(data):
    with pytest.raises(ValueError, match="No Acts found"):
        _index_norm_ids(data, 2023)


def test_wrong_year_pdf_is_rejected():
    with pytest.raises(ValueError, match="links to PDF"):
        _index_norm_ids(INDEX, 2024)
