"""Discovery of Portuguese legislation from diariodarepublica.pt.

Two enumerators, because neither alone is complete:

**Sitemaps** (``https://files.dre.pt/sitemap/sitemap.xml``, 588 children, 5.9 M URLs)
are cheap — the whole index downloads in about two minutes — but they miss roughly
4.6 % of in-scope Série I documents (Decreto-Lei 9/2022 and 10/2022 among them; they
fetch perfectly, they are simply not indexed), and the URL ``tipo`` does not say which
série a document belongs to: 14 % of ``portaria`` URLs are Série II.

**The journal walk** (date → journal issues → documents) is authoritative: it hands
back the série and the issue for free and cannot miss a document that was published.
It is slower, so it runs as a completeness pass over the sitemap's output.

Série is filtered at fetch time, from the detail record — the only place it exists.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

from legalize.fetcher.base import LegislativeClient, NormDiscovery
from legalize.fetcher.pt.client import CONSOLIDATED, PUBLISHED, DREClient

logger = logging.getLogger(__name__)

SITEMAP_INDEX = "https://files.dre.pt/sitemap/sitemap.xml"
CONSOLIDATED_SITEMAP = "legislacao-consolidada-sitemap-1.xml"

# DRE has no machine-readable text before 1960: every sampled 1910s-1950s document
# returns an empty Texto and TextoFormatado with only a scanned PDF. 68,916 in-scope
# URLs (25.8 %) are pre-1960 catalogue stubs. See docs/pt-discovery-plan.md §1.
EARLIEST_YEAR = 1960

# Legislative norms: general, binding acts of the Portuguese state and the autonomous
# regions. Not company filings, tenders, personnel notices or ordinary case law.
# Rationale per type in docs/pt-discovery-plan.md §2.2.
IN_SCOPE_TYPES: frozenset[str] = frozenset(
    {
        # primary legislation
        "lei",
        "lei-constitucional",
        "lei-organica",
        "decreto-lei",
        "decreto",
        "decreto-regulamentar",
        "decreto-legislativo-regional",
        "decreto-regulamentar-regional",
        "portaria",
        "resolucao",
        "despacho-normativo",
        # corrections — these legally amend the published text
        "declaracao-rectificacao",
        "declaracao-retificacao",
        "declaracao-rectificacao-extracto",
        "declaracao-retificacao-extrato",
        # head of state, parliament, government
        "decreto-presidente-republica",
        "resolucao-assembleia-republica",
        "resolucao-conselho-ministros",
        "resolucao-assembleia-legislativa-regional",
        "resolucao-assembleia-legislativa-regional-acores",
        "resolucao-assembleia-legislativa-regiao-autonoma-acores",
        "resolucao-assembleia-legislativa-regiao-autonoma-madeira",
        # historical and transitional act types
        "decreto-governo",
        "decreto-regional",
        "decreto-representante-republica-para-regiao-autonoma-madeira",
        "decreto-representante-republica-para-regiao-autonoma-acores",
        "decreto-ministro-republica",
        "decreto-ministro-republica-para-regiao-autonoma-madeira",
        "decreto-ministro-republica-para-regiao-autonoma-acores",
        "carta-lei",
        "carta-constitucional",
        "decreto-aprovacao-constituicao",
        "regimento",
        "regimento-assembleia-republica",
        "regimento-conselho-estado",
        "resolucao-assembleia-nacional",
        "resolucao-assemblea-nacional",
        "resolucao-congresso-republica",
        "resolucao-conselho-revolucao",
        "resolucao-conselho-ministros-para-assuntos-economicos",
        "resolucao-conselho-corporativo",
        "tratado",
        # jurisprudence that is a *source of law*: TC rulings with força obrigatória
        # geral repeal norms erga omnes (CRP art. 281-282); assentos and acórdãos de
        # uniformização bind the lower courts. 744 documents. The other 458,482
        # acordao* stay out — they bind only the parties.
        "acordao-tribunal-constitucional",
        "acordao-supremo-tribunal-justica",
        "assento",
        "acordao-doutrinario",
        # extract publications of the above
        "despacho-normativo-extracto",
        "despacho-normativo-extrato",
        "resolucao-extracto",
        "resolucao-extrato",
        "portaria-extracto",
        "portaria-extrato",
    }
)

_LOC = re.compile(r"<loc>([^<]+)</loc>")
_DETALHE = re.compile(r"/dr/detalhe/([^/]+)/([^/?#]+)")
_CONS = re.compile(r"/dr/legislacao-consolidada/([^/]+)/(\d{4})-(\d+)")
# /dr/detalhe/lei/29-2026-1135578391 -> the 2026 is the publication year
_KEY_YEAR = re.compile(r"-(\d{4})-\d+$")


def _year_of(key: str) -> int | None:
    match = _KEY_YEAR.search(key)
    return int(match.group(1)) if match else None


class DREDiscovery(NormDiscovery):
    """Enumerates Portuguese legislation worth publishing."""

    def __init__(
        self,
        cache_dir: str | Path = "",
        earliest_year: int = EARLIEST_YEAR,
        journal_walk: bool = True,
    ) -> None:
        self._cache = Path(cache_dir) if cache_dir else None
        self._earliest_year = earliest_year
        self._journal_walk = journal_walk

    @classmethod
    def create(cls, source: dict) -> DREDiscovery:
        return cls(
            cache_dir=source.get("cache_dir", ""),
            earliest_year=int(source.get("earliest_year", EARLIEST_YEAR)),
            journal_walk=bool(source.get("journal_walk", True)),
        )

    # ---------------------------------------------------------------- sitemaps

    def _sitemap_dir(self) -> Path | None:
        if not self._cache:
            return None
        path = self._cache / "sitemaps"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _fetch_sitemap(self, client: DREClient, url: str) -> str:
        cache_dir = self._sitemap_dir()
        cached = (cache_dir / url.rsplit("/", 1)[1]) if cache_dir else None
        if cached and cached.exists():
            return cached.read_text(encoding="utf-8")
        body = client._api.get_text_body(url)
        if cached:
            cached.write_text(body, encoding="utf-8")
        return body

    def _child_sitemaps(self, client: DREClient) -> list[str]:
        return _LOC.findall(self._fetch_sitemap(client, SITEMAP_INDEX))

    def consolidated_ids(self, client: DREClient) -> Iterator[str]:
        """Every diploma DRE consolidates — the ones that get real version history."""
        children = self._child_sitemaps(client)
        target = next((u for u in children if u.endswith(CONSOLIDATED_SITEMAP)), None)
        if not target:
            raise RuntimeError(
                f"{CONSOLIDATED_SITEMAP} is not in the DRE sitemap index "
                f"({len(children)} children). DRE moved the consolidated catalogue."
            )
        for url in _LOC.findall(self._fetch_sitemap(client, target)):
            match = _CONS.search(url)
            if match:
                yield f"{CONSOLIDATED}:{match.group(1)}:{match.group(2)}-{match.group(3)}"

    def published_ids(self, client: DREClient) -> Iterator[tuple[str, str]]:
        """Every in-scope as-published diploma from 1960 on. Yields (tipo, key)."""
        seen: set[str] = set()
        for child in self._child_sitemaps(client):
            try:
                body = self._fetch_sitemap(client, child)
            except Exception:
                # geral-sitemap-sitemap-1.xml is a permanent 403 upstream.
                logger.warning("Sitemap unreadable, skipping: %s", child)
                continue
            for url in _LOC.findall(body):
                match = _DETALHE.search(url)
                if not match:
                    continue
                tipo, key = match.group(1), match.group(2)
                # The child sitemap's filename does not match the URL type it holds
                # (diploma-externo-sitemap-* is full of /detalhe/acordao/), so filter
                # on the URL, never on the filename.
                if tipo not in IN_SCOPE_TYPES:
                    continue
                year = _year_of(key)
                if year is not None and year < self._earliest_year:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                yield tipo, key

    # ------------------------------------------------------------ journal walk

    def journal_ids(self, client: DREClient, start: date, end: date) -> Iterator[tuple[str, str]]:
        """Walk the Diário da República day by day. Authoritative but slow.

        Appends one line per date to ``{cache}/journal_walk.jsonl`` so a crash does
        not lose the enumeration done so far.
        """
        log = (self._cache / "journal_walk.jsonl") if self._cache else None
        done: set[str] = set()
        if log and log.exists():
            for line in log.read_text(encoding="utf-8").splitlines():
                try:
                    done.add(json.loads(line)["date"])
                except Exception:
                    continue

        current = start
        while current <= end:
            iso = current.isoformat()
            if iso in done:
                current += timedelta(days=1)
                continue
            refs: list[list[str]] = []
            try:
                for journal in client._api.journals_by_date(iso):
                    for doc in client._api.documents_by_journal(journal["Id"]):
                        match = _DETALHE.search(doc.get("LinkSitemap") or "")
                        if match and match.group(1) in IN_SCOPE_TYPES:
                            refs.append([match.group(1), match.group(2)])
            except Exception:
                logger.warning("Journal walk failed for %s", iso, exc_info=True)
                current += timedelta(days=1)
                continue
            if log:
                with log.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"date": iso, "refs": refs}) + "\n")
            for tipo, key in refs:
                yield tipo, key
            current += timedelta(days=1)

    # ------------------------------------------------------- NormDiscovery API

    def discover_all(self, client: LegislativeClient, **kwargs) -> Iterator[str]:
        """Yield every norm id worth fetching, consolidated first.

        A diploma DRE consolidates is yielded only as ``cons:`` — the consolidated
        surface carries the same document plus its history, so emitting both would
        write two files for one law.
        """
        assert isinstance(client, DREClient)

        cons_keys: set[str] = set()
        count = 0
        for norm_id in self.consolidated_ids(client):
            cons_keys.add(norm_id.split(":", 2)[2])
            count += 1
            yield norm_id
        logger.info("Discovery: %d consolidated diplomas", count)

        published = 0
        for tipo, key in self.published_ids(client):
            published += 1
            yield f"{PUBLISHED}:{tipo}:{key}"
        logger.info("Discovery: %d as-published diplomas", published)

    def discover_daily(
        self, client: LegislativeClient, target_date: date, **kwargs
    ) -> Iterator[str]:
        """Yield the in-scope documents published on one date."""
        assert isinstance(client, DREClient)
        for journal in client._api.journals_by_date(target_date.isoformat()):
            for doc in client._api.documents_by_journal(journal["Id"]):
                match = _DETALHE.search(doc.get("LinkSitemap") or "")
                if match and match.group(1) in IN_SCOPE_TYPES:
                    yield f"{PUBLISHED}:{match.group(1)}:{match.group(2)}"
