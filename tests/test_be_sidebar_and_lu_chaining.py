"""Regressions for the two real bugs behind the silenced bugbear ignores.

- ``be``: the date filter used by ``_parse_version_sidebar`` was a closure
  defined inside the version loop, reading ``last_good_effective`` late. It
  worked only because every call happened in the iteration that defined it.
  These cases pin the resolution rules so the hoisted version cannot drift.
- ``lu``: "No XML available" used to be raised inside ``except`` without
  ``from``, so a filestore timeout reached the log as a missing document.
"""

import pytest
import requests

from legalize.fetcher.be.client import _parse_version_sidebar
from legalize.fetcher.lu.client import LegiluxClient


def _sidebar(rows: str) -> bytes:
    return f'<html><body><div id="list-title-sw_roi">{rows}</div></body></html>'.encode("latin-1")


# Row N describes the transition OUT of version N, so row 1 dates version 2.
SIDEBAR = _sidebar(
    "<p>Modifie par LOI du 24-10-2009 publie le 01-02-2010 Art. modifie 5, 6bis "
    "En vigueur jusqu'au 01-03-2010 <a>Version archivee n° 001</a></p>"
    "<p>Modifie par LOI du 02-06-2011 publie le 05-06-2011 Art. modifie 7 "
    "En vigueur jusqu'au 01-01-2201 <a>Version archivee n° 002</a></p>"
    "<p>Modifie par LOI du 01-01-2009 publie le 01-01-2009 Art. modifie 8 "
    "En vigueur jusqu'au 02-02-2009 <a>Version archivee n° 003</a></p>"
)


def test_effective_dates_survive_sentinels_and_backwards_rows():
    entries = _parse_version_sidebar(SIDEBAR, newest_version=4)

    dates = [e["effective_date"] for e in entries]
    assert dates == [
        None,  # v1: the parser fills it in from the norm's publication date
        "2010-03-01",  # row 1's "En vigueur jusqu'au"
        "2011-06-05",  # row 2's is 2201-01-01, a sentinel: amending law instead
        "2011-06-05",  # row 3 moves backwards on both dates: last known good
    ]
    assert entries[1]["affected_articles"] == ["5", "6bis"]


def test_lu_missing_xml_keeps_the_download_failure_as_cause():
    timeout = requests.ConnectionError("filestore timed out")

    with LegiluxClient() as client:

        def _boom(url: str) -> bytes:
            raise timeout

        client.download_xml = _boom
        client.get_xml_url = lambda uri: None

        with pytest.raises(ValueError) as excinfo:
            client.get_text("leg-loi-2022-05-27-a250")

    assert excinfo.value.__cause__ is timeout
