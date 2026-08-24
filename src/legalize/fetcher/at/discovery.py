"""Discovery of Austrian Bundesrecht norms via the RIS OGD API."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from legalize.fetcher.base import LegislativeClient, NormDiscovery
from legalize.fetcher.at.client import RISClient
from legalize.state.store import MAX_LOOKBACK_DAYS

logger = logging.getLogger(__name__)

# Cache file for discovered Gesetzesnummern (discovery takes ~73 min)
_CACHE_FILENAME = "gesetzesnummern.json"
_CACHE_MAX_AGE_DAYS = 7

# RIS ignores the Geaendert query parameter, so the daily asks for a coarse
# change window and filters client-side. These are the windows the API accepts,
# with the span each one covers.
_RIS_WINDOWS = (
    (7, "EinerWoche"),
    (14, "ZweiWochen"),
    (30, "EinemMonat"),
    (90, "DreiMonaten"),
    (180, "SechsMonaten"),
    (365, "EinemJahr"),
)


def _ris_window(target_date: date) -> str:
    """Smallest RIS change window that still reaches back to `target_date`.

    Never narrower than the daily's own lookback. `EinerWoche` is 7 days while
    `resolve_dates_to_process` walks back MAX_LOOKBACK_DAYS, so the oldest days
    of every window asked for changes the query had never returned — and an
    out-of-range date is not an error here, it is an empty result set, which is
    why three days a run went missing without anyone noticing.
    """
    days = max((date.today() - target_date).days, MAX_LOOKBACK_DAYS) + 1
    for span, name in _RIS_WINDOWS:
        if span >= days:
            return name
    logger.warning(
        "%s is %d days back; RIS looks back at most %d — changes may be missing",
        target_date,
        days,
        _RIS_WINDOWS[-1][0],
    )
    return _RIS_WINDOWS[-1][1]


class RISDiscovery(NormDiscovery):
    """Discovers all Gesetze (grouped by Gesetzesnummer) in the RIS catalog."""

    def __init__(self, cache_dir: str | None = None, **kwargs) -> None:
        self._cache_dir = cache_dir
        # One fetch of the change window per run, keyed by window name.
        self._recent: dict[str, list[tuple[str, str]]] = {}

    @classmethod
    def create(cls, source: dict) -> RISDiscovery:
        """Create with cache_dir from source config."""
        return cls(cache_dir=source.get("cache_dir"))

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Yield all unique Gesetzesnummern in BrKons (Bundesrecht konsolidiert).

        Uses a cached list if available and recent (< 7 days old).
        Otherwise paginates through the full catalog (~437k NOR entries).
        """
        # Try cache first
        cached = self._load_cache()
        if cached is not None:
            logger.info("Using cached discovery: %d Gesetzesnummern", len(cached))
            yield from cached
            return

        assert isinstance(client, RISClient)
        seen: set[str] = set()
        result: list[str] = []
        page = 1
        page_size = 100

        while True:
            raw = client.get_page(page=page, page_size=page_size)
            data = json.loads(raw)
            results = data["OgdSearchResult"]["OgdDocumentResults"]
            total = int(results["Hits"]["#text"])

            refs = results.get("OgdDocumentReference", [])
            if isinstance(refs, dict):
                refs = [refs]

            for ref in refs:
                br = ref["Data"]["Metadaten"]["Bundesrecht"]["BrKons"]
                gesnr = br.get("Gesetzesnummer", "")
                if gesnr and gesnr not in seen:
                    seen.add(gesnr)
                    result.append(gesnr)
                    yield gesnr

            fetched_so_far = (page - 1) * page_size + len(refs)
            if page % 500 == 0:
                logger.info(
                    "Discovery page %d: %d/%d NOR entries, %d unique laws",
                    page,
                    fetched_so_far,
                    total,
                    len(result),
                )
            if fetched_so_far >= total or not refs:
                break
            page += 1

        # Save cache for next run
        self._save_cache(result)

    def _cache_path(self) -> Path | None:
        if not self._cache_dir:
            return None
        return Path(self._cache_dir) / _CACHE_FILENAME

    def _load_cache(self) -> list[str] | None:
        path = self._cache_path()
        if path is None or not path.exists():
            return None
        import time

        age_days = (time.time() - path.stat().st_mtime) / 86400
        if age_days > _CACHE_MAX_AGE_DAYS:
            logger.info("Discovery cache expired (%.0f days old)", age_days)
            return None
        try:
            data = json.loads(path.read_text())
            return data.get("gesetzesnummern", None)
        except (json.JSONDecodeError, OSError):
            return None

    def _save_cache(self, gesnrs: list[str]) -> None:
        path = self._cache_path()
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"gesetzesnummern": gesnrs}, indent=2))
        logger.info("Saved discovery cache: %d Gesetzesnummern → %s", len(gesnrs), path)

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Yield Gesetzesnummern whose Geaendert date is target_date."""
        assert isinstance(client, RISClient)
        date_str = target_date.strftime("%Y-%m-%d")
        seen: set[str] = set()
        for geaendert, gesnr in self._recent_changes(client, _ris_window(target_date)):
            if geaendert == date_str and gesnr not in seen:
                seen.add(gesnr)
                yield gesnr

    def _recent_changes(self, client: RISClient, window: str) -> list[tuple[str, str]]:
        """(Geaendert, Gesetzesnummer) for every norm RIS reports in `window`.

        Fetched once per run. `pipeline.daily` calls discover_daily once per
        date of the lookback, and re-paginating the whole window for each of
        them is what pushed the at job into its 55-minute timeout.
        """
        if window not in self._recent:
            self._recent[window] = list(self._fetch_window(client, window))
            logger.info("RIS window %s: %d changed norm(s)", window, len(self._recent[window]))
        return self._recent[window]

    @staticmethod
    def _fetch_window(client: RISClient, window: str) -> Iterator[tuple[str, str]]:
        page = 1
        page_size = 100

        while True:
            raw = client.get_page(page=page, page_size=page_size, ImRisSeit=window)
            data = json.loads(raw)
            results = data["OgdSearchResult"].get("OgdDocumentResults")
            if not results:
                break

            total = int(results["Hits"]["#text"])
            refs = results.get("OgdDocumentReference", [])
            if isinstance(refs, dict):
                refs = [refs]

            for ref in refs:
                geaendert = ref["Data"]["Metadaten"].get("Allgemein", {}).get("Geaendert", "")
                br = ref["Data"]["Metadaten"]["Bundesrecht"]["BrKons"]
                gesnr = br.get("Gesetzesnummer", "")
                if gesnr:
                    yield geaendert, gesnr

            fetched_so_far = (page - 1) * page_size + len(refs)
            if fetched_so_far >= total or not refs:
                break
            page += 1
