"""BWB client: which expressions the manifest actually offers for download."""

from __future__ import annotations

from legalize.fetcher.nl import BWBClient

MANIFEST = b"""<?xml version='1.0' encoding='UTF-8'?>
<work label="BWBR0000001" _latestItem="2020-01-01_0/xml/BWBR0000001_2020-01-01_0.xml">
  <expression label="2018-01-01_0">
    <metadata><datum_inwerkingtreding>2018-01-01</datum_inwerkingtreding></metadata>
    <manifestation label="gedrukte-tekst"><item label="x.pdf" _deleted="false"/></manifestation>
  </expression>
  <expression label="2019-01-01_0">
    <metadata><datum_inwerkingtreding>2019-01-01</datum_inwerkingtreding></metadata>
    <manifestation label="xml">
      <item label="BWBR0000001_2019-01-01_0.xml" _deleted="true"/>
    </manifestation>
  </expression>
  <expression label="2020-01-01_0">
    <metadata><datum_inwerkingtreding>2020-01-01</datum_inwerkingtreding></metadata>
    <manifestation label="xml">
      <item label="BWBR0000001_2020-01-01_0.xml" _deleted="false"/>
    </manifestation>
  </expression>
</work>
"""


def test_list_expressions_skips_withdrawn_xml(monkeypatch):
    """A withdrawn item (301-to-itself upstream) must never reach the fetcher."""
    client = BWBClient()
    monkeypatch.setattr(client, "get_manifest", lambda bwb_id: MANIFEST)

    assert client.list_expressions("BWBR0000001") == [
        ("2020-01-01", "2020-01-01_0/xml/BWBR0000001_2020-01-01_0.xml")
    ]
