from datetime import date

import pytest

from legalize.fetcher.gt.client import GTFixtureClient
from legalize.fetcher.gt.discovery import GTFixtureDiscovery


def test_gt_fixture_client_get_text():
    client = GTFixtureClient()

    data = client.get_text("decreto-57-2008")

    assert b"57-2008" in data
    assert b"ACCESO" in data


def test_gt_fixture_client_unknown_norm():
    client = GTFixtureClient()

    with pytest.raises(KeyError):
        client.get_text("does-not-exist")


def test_gt_fixture_discovery_all():
    client = GTFixtureClient()
    discovery = GTFixtureDiscovery()

    norm_ids = list(discovery.discover_all(client))

    assert norm_ids == ["decreto-57-2008", "decreto-13-2013"]


def test_gt_fixture_discovery_daily():
    client = GTFixtureClient()
    discovery = GTFixtureDiscovery()

    norm_ids = list(discovery.discover_daily(client, date(2013, 11, 12)))

    assert norm_ids == ["decreto-13-2013"]


def test_gt_fixture_discovery_daily_empty():
    client = GTFixtureClient()
    discovery = GTFixtureDiscovery()

    norm_ids = list(discovery.discover_daily(client, date(2024, 1, 1)))

    assert norm_ids == []
