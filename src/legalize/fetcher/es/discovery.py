"""BOE-specific norm discovery — wraps sumario.py and catalogo.py.

Implements the NormDiscovery interface for Spain's BOE.
The existing sumario.py and catalogo.py modules do the real work.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
import json
from pathlib import Path

import requests
from lxml import etree

from legalize.fetcher.base import LegislativeClient, NormDiscovery


def diary_identifiers(client, data_dir: str | Path, start: date, end: date) -> Iterator[str]:
    """Cache the official Section I census, including extraordinary Sunday editions."""
    path = Path(data_dir) / "diary-index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    index = json.loads(path.read_text()) if path.exists() else {"days": {}}
    index.update({"from": start.isoformat(), "through": end.isoformat()})
    day = start
    while day <= end:
        key = day.isoformat()
        if key not in index["days"]:
            try:
                root = etree.fromstring(client.get_sumario(day))
            except requests.HTTPError as exc:
                if exc.response is None or exc.response.status_code != 404:
                    raise
                identifiers = []
            else:
                status = root.findtext("status/code")
                if status not in {"200", "404"}:
                    raise ValueError(f"BOE summary {key} returned status {status}")
                identifiers = sorted(
                    {
                        item.text.strip()
                        for section in root.iter("seccion")
                        if section.get("codigo") in {"1", "1A"}
                        for item in section.iter("identificador")
                        if item.text
                    }
                )
            index["days"][key] = identifiers
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(index, indent=2) + "\n")
            temporary.replace(path)
        yield from index["days"][key]
        day += timedelta(days=1)


class BOEDiscovery(NormDiscovery):
    """Discover norms via BOE sumarios and catalog API."""

    def __init__(self, config=None):
        self.config = config

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Discover all norms via BOE catalog API."""
        from legalize.fetcher.es.catalogo import iter_norms_from_catalog

        catalogue = list(iter_norms_from_catalog(client, self.config))
        seen = set(catalogue)
        yield from catalogue
        if self.config:
            cc = self.config.get_country("es")
            if since := cc.source.get("diary_since"):
                for identifier in diary_identifiers(
                    client, cc.data_dir, date.fromisoformat(str(since)), date.today()
                ):
                    if identifier not in seen:
                        seen.add(identifier)
                        yield identifier

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Discover norms from a BOE daily sumario."""
        from legalize.fetcher.es.config import ScopeConfig
        from legalize.fetcher.es.sumario import parse_summary

        if "scope" in kwargs:
            scope = kwargs["scope"]
        elif self.config:
            cc = self.config.get_country("es")
            scope = ScopeConfig(
                ranks=cc.source.get("rangos", []),
                fixed_norms=cc.source.get("normas_fijas", []),
            )
        else:
            scope = ScopeConfig()
        xml_data = client.get_sumario(target_date)
        dispositions = parse_summary(xml_data, scope)
        for disp in dispositions:
            yield disp.id_boe
