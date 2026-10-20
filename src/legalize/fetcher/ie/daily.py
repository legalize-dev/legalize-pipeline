"""Ireland's daily: refresh only the norms whose sources changed since the corpus was built.

eISB publishes no change feed that covers it all, so a run reads three cheap signals:

- the annual Act indexes, one page a year: an Act the repo does not hold is new;
- the LRC revised catalogue, one page: an Act whose rows changed has a new version;
- the Legislation Directory. Every page carries the directory's "Updated to" cursor.
  While it holds, no page has changed. When it moves, every page is read once and
  compared, without that banner, with the content the corpus was built from.

Refreshing a norm re-reads its whole source history, which for an Act with many LRC
PDFs takes minutes, so a run works to a time budget and carries what it did not reach to
the next one. A norm whose history gains an event before its published ones cannot be
appended to: it is kept for a local rebuild and reported, not retried every morning.

What the corpus was built from lives in ``sources.json`` next to the run state. Without
one, a run starts from the baseline recorded when the corpus was last built locally.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import requests
from lxml import html

from legalize.committer.git_ops import GitRepo
from legalize.config import Config
from legalize.fetcher.ie.client import CONSTITUTION_ID, ISBClient, _parse_norm_id, refresh_sources
from legalize.fetcher.ie.discovery import ISBDiscovery
from legalize.fetcher.ie.history import REVISED_INDEX, revised_catalog
from legalize.pipeline import (
    HistoryMismatch,
    _published,
    commit_one,
    console,
    finalize_daily,
    generic_fetch_one,
    write_repo_meta,
)
from legalize.state.store import StateStore, resolve_dates_to_process

logger = logging.getLogger(__name__)

BASELINE = Path(__file__).with_name("daily-baseline.json")
CONSTITUTION_PAGE = "cons"
_BANNER = re.compile(rb'<div class="outline-lead">\s*<h3[^>]*>.*?</h3>\s*</div>', re.S)
_CURSOR = re.compile(rb"Updated to ([^<]+)</span>\s*<span>([^<]*)</span>")


@dataclass
class Sources:
    """What the published corpus was built from, and what is still to do."""

    cursor: str = ""
    pages: dict[str, str] = field(default_factory=dict)  # directory page -> digest
    catalogue: dict[str, str] = field(default_factory=dict)  # Act -> LRC rows digest
    unswept: list[str] = field(default_factory=list)  # pages unread under this cursor
    pending: list[str] = field(default_factory=list)  # norms to refresh
    rebuild: dict[str, str] = field(default_factory=dict)  # norm -> why it cannot append
    next_status: dict[str, str] = field(default_factory=dict)  # norm -> status change date
    tip: str = ""  # the corpus commit this state describes

    @classmethod
    def load(cls, path: Path) -> Sources:
        source = path if path.exists() else BASELINE
        data = json.loads(source.read_text(encoding="utf-8")) if source.exists() else {}
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})

    @classmethod
    def baseline(cls) -> Sources:
        return cls.load(BASELINE)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), sort_keys=True) + "\n", encoding="utf-8")


def content_digest(page: bytes) -> str:
    """A directory page without the "Updated to" banner that every update rewrites."""
    return hashlib.sha256(_BANNER.sub(b"", page, count=1)).hexdigest()[:16]


def directory_cursor(page: bytes) -> str:
    match = _CURSOR.search(page)
    if match is None:
        raise ValueError("Legislation Directory page has no 'Updated to' banner")
    return " ".join(part.decode("utf-8").strip() for part in match.groups())


def rows_digest(rows) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:16]


def page_url(client: ISBClient, page: str) -> str:
    if page == CONSTITUTION_PAGE:
        return f"{client._base_url}/eli/cons/en/html"
    return f"{client._base_url}/isbc/{page}"


def page_of(norm_id: str, get) -> str | None:
    """The directory page a norm's effects are read from, by the links fetch_effects follows."""
    if norm_id == CONSTITUTION_ID:
        return CONSTITUTION_PAGE
    year, kind, number = _parse_norm_id(norm_id)
    if kind != "si":
        return {"act": f"{year}_{number}.html", "prv": f"pa{year}.html"}.get(kind)
    index = f"si{year}.html"
    for link in html.fromstring(get(index)).xpath("//a/@href"):
        match = re.search(rf"si{year}_(\d+)-(\d+)\.html", link)
        if match and int(match[1]) <= int(number) <= int(match[2]):
            return match[0]
    return index


class _Published:
    """The repo's norms, indexed by the directory page that lists them."""

    def __init__(self, identifiers: set[str], pages):
        self.ids = identifiers
        self._si: dict[int, list[tuple[int, str]]] = {}
        for norm_id in identifiers:
            if match := re.fullmatch(r"IE-(\d{4})-si-(\d+)", norm_id):
                self._si.setdefault(int(match[1]), []).append((int(match[2]), norm_id))
        self._ranges: dict[int, list[tuple[int, int]]] = {}
        for page in pages:
            if match := re.fullmatch(r"si(\d{4})_(\d+)-(\d+)\.html", page):
                self._ranges.setdefault(int(match[1]), []).append((int(match[2]), int(match[3])))

    def on(self, page: str) -> set[str]:
        if page == CONSTITUTION_PAGE:
            return {CONSTITUTION_ID} & self.ids
        if match := re.fullmatch(r"(\d{4})_(\d+)\.html", page):
            return {f"IE-{match[1]}-act-{match[2]}"} & self.ids
        if match := re.fullmatch(r"pa(\d{4})\.html", page):
            return {n for n in self.ids if n.startswith(f"IE-{match[1]}-act-P")}
        if match := re.fullmatch(r"si(\d{4})_(\d+)-(\d+)\.html", page):
            low, high = int(match[2]), int(match[3])
            return {n for number, n in self._si.get(int(match[1]), ()) if low <= number <= high}
        if match := re.fullmatch(r"si(\d{4})\.html", page):
            ranges = self._ranges.get(int(match[1]), ())
            return {
                n
                for number, n in self._si.get(int(match[1]), ())
                if not any(low <= number <= high for low, high in ranges)
            }
        return set()


def _excluded(repo_path: str) -> set[str]:
    """Norms coverage.json already explains; a network failure is retried instead."""
    path = Path(repo_path) / "coverage.json"
    if not path.exists():
        return set()
    entries = json.loads(path.read_text(encoding="utf-8")).get("excluded") or []
    return {entry["identifier"] for entry in entries if not entry.get("transient")}


def find_changes(cc, sources: Sources, published: set[str], until: float) -> list[str]:
    """Queue the norms the three signals point at; return the discovered Acts.

    eISB refuses bursts with a 403 now and then. A directory page it refuses goes
    back to the end of the queue for the next run; a whole batch refused stops the
    sweep, and a sweep that read nothing at all is an error.
    """
    queued: set[str] = set()
    workers = max(1, cc.max_workers or 1)
    local, lock, clients = threading.local(), threading.Lock(), ExitStack()

    def get(page: str) -> bytes | Exception:
        # One client per worker: each paces itself, as the full fetch's workers do.
        if getattr(local, "client", None) is None:
            with lock:
                local.client = clients.enter_context(ISBClient.create(cc))
        try:
            return local.client._get(page_url(local.client, page))
        except requests.RequestException as exc:
            return exc

    with ISBClient.create(cc) as client:
        for norm_id, rows in revised_catalog(client._get(REVISED_INDEX)).items():
            digest = rows_digest(rows)
            if sources.catalogue.get(norm_id) != digest:
                sources.catalogue[norm_id] = digest
                if norm_id in published:
                    queued.add(norm_id)
        discovered = list(ISBDiscovery().discover_all(client))
        excluded = _excluded(cc.repo_path)
        queued |= {n for n in discovered if n not in published and n not in excluded}
        today = date.today().isoformat()
        queued |= {n for n, day in sources.next_status.items() if day <= today and n in published}

        probe = next((p for p in sorted(sources.pages) if p != CONSTITUTION_PAGE), None)
        cursor = directory_cursor(client._get(page_url(client, probe or f"si{today[:4]}.html")))
    if cursor != sources.cursor:
        sources.cursor, sources.unswept = cursor, sorted(sources.pages)

    index = _Published(published, sources.pages)
    read, refused = 0, []
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            while sources.unswept and time.monotonic() < until:
                batch = sources.unswept[: workers * 25]
                del sources.unswept[: len(batch)]
                failed = []
                for page, data in zip(batch, pool.map(get, batch), strict=True):
                    if isinstance(data, Exception):
                        failed.append((page, data))
                    elif (digest := content_digest(data)) != sources.pages.get(page):
                        queued |= index.on(page)
                        sources.pages[page] = digest
                read += len(batch) - len(failed)
                refused += failed
                sources.unswept += [page for page, _ in failed]
                if len(failed) == len(batch):
                    break
    finally:
        clients.close()
    if left := sorted({page for page, _ in refused} & set(sources.unswept)):
        console.print(
            f"[yellow]eISB refused {len(left)} directory page(s), left for the next run: "
            f"{refused[-1][1]}[/yellow]"
        )
    if refused and not read:
        raise RuntimeError(f"eISB refused every directory page read: {refused[0][1]}")
    sources.pending = sorted(set(sources.pending) | queued)
    console.print(
        f"[bold]Ireland — {len(queued)} norm(s) changed at the source, "
        f"{len(sources.pending)} to refresh, {len(sources.unswept)} directory page(s) unread[/bold]"
    )
    return discovered


def refresh_norms(
    config: Config,
    identifiers: list[str],
    *,
    dry_run: bool = False,
    known: set[str] = frozenset(),
    outcomes: dict[str, str] | None = None,
) -> tuple[int, list[str]]:
    """Fetch complete histories and their new source instruments before committing.

    ``known`` norms are already published: a dependency among them is not fetched
    again. ``outcomes`` receives, per norm, ``ok``, ``failed`` or ``rebuild: <why>``.
    """
    from legalize.fetcher.ie.bootstrap import fetch_dependencies

    identifiers = list(dict.fromkeys(identifiers))
    outcomes = {} if outcomes is None else outcomes
    if dry_run:
        for norm_id in identifiers:
            console.print(f"  [dim]Would refresh {norm_id} and its source instruments[/dim]")
        return 0, []

    cc = config.get_country("ie")
    errors: list[str] = []
    fetched = []
    with ThreadPoolExecutor(max_workers=cc.max_workers or 1) as pool:
        futures = {
            norm_id: pool.submit(
                lambda key: generic_fetch_one(config, "ie", key, force=True) is not None,
                norm_id,
            )
            for norm_id in identifiers
        }
        for norm_id, future in futures.items():
            try:
                if not future.result():
                    raise ValueError("The complete source history could not be fetched")
                fetched.append(norm_id)
            except Exception as exc:
                logger.exception("Failed to refresh %s", norm_id)
                errors.append(f"{norm_id}: {exc}")
                outcomes[norm_id] = "failed"

    if not fetched:
        return 0, errors
    try:
        dependencies = fetch_dependencies(config, fetched, known=known)
    except Exception as exc:
        logger.exception("Failed to fetch amendment source instruments")
        errors.append(f"Amendment source instruments: {exc}")
        outcomes.update(dict.fromkeys(fetched, "failed"))
        return 0, errors

    created = 0
    for norm_id in dict.fromkeys([*dependencies, *fetched]):
        try:
            created += commit_one(config, "ie", norm_id)
            outcomes[norm_id] = "ok"
        except HistoryMismatch as exc:
            errors.append(f"{norm_id}: {exc}")
            outcomes[norm_id] = f"rebuild: {exc}"
        except Exception as exc:
            logger.exception("Failed to commit %s", norm_id)
            errors.append(f"{norm_id}: {exc}")
            outcomes[norm_id] = "failed"
    return created, errors


def _refresh(config: Config, sources: Sources, published: set[str], until: float):
    """Refresh the queue in small batches until the budget runs out."""
    cc = config.get_country("ie")
    data_dir = Path(cc.data_dir)
    created, errors = 0, []
    queue = [n for n in sources.pending if n not in sources.rebuild]
    batch_size = max(1, cc.max_workers or 1)
    while queue and time.monotonic() < until:
        batch, queue = queue[:batch_size], queue[batch_size:]
        outcomes: dict[str, str] = {}
        made, failed = refresh_norms(config, batch, known=published, outcomes=outcomes)
        created += made
        errors += failed
        with ISBClient.create(cc) as client:

            def get(page: str) -> bytes:
                return client._get(page_url(client, page))

            for norm_id, outcome in outcomes.items():
                if outcome == "ok":
                    published.add(norm_id)
                    page = page_of(norm_id, get)
                    if page and page not in sources.pages:
                        sources.pages[page] = content_digest(get(page))
                    stamp = data_dir / "source-stamps" / f"{norm_id}.json"
                    if stamp.exists() and (
                        day := json.loads(stamp.read_text())["next_status_date"]
                    ):
                        sources.next_status[norm_id] = day
                    else:
                        sources.next_status.pop(norm_id, None)
                elif outcome.startswith("rebuild: "):
                    sources.rebuild[norm_id] = outcome.removeprefix("rebuild: ")
        done = {
            n
            for n, outcome in outcomes.items()
            if outcome != "failed" or not _transient(data_dir, n)
        }
        sources.pending = [n for n in sources.pending if n not in done]
    return created, errors


def _transient(data_dir: Path, norm_id: str) -> bool:
    """A failure a retry may fix: network trouble, or one with no recorded reason."""
    from legalize.coverage import unresolved

    return bool(unresolved(data_dir, [norm_id]))


def _head(repo: GitRepo) -> str | None:
    return repo._run(["rev-parse", "--verify", "-q", "HEAD"], check=False).strip() or None


def _descends(repo: GitRepo, commit: str) -> bool:
    """HEAD contains ``commit``: false once a rebuild has force-pushed it away."""
    import subprocess

    return (
        subprocess.run(
            ["git", "-C", str(repo._path), "merge-base", "--is-ancestor", commit, "HEAD"],
            capture_output=True,
        ).returncode
        == 0
    )


def daily(config: Config, target_date: date | None = None, dry_run: bool = False) -> int:
    """Commit the source's changes since the last run, within the run's time budget."""
    from legalize.coverage import update_report

    cc = config.get_country("ie")
    state = StateStore(cc.state_path)
    state.load()
    dates = resolve_dates_to_process(state, cc.repo_path, target_date)
    if dates is None:
        console.print("[yellow]No last date found. Use --date or run bootstrap.[/yellow]")
        return 0

    repo = GitRepo(cc.repo_path, config.git.committer_name, config.git.committer_email)
    sources_path = Path(cc.state_path).with_name("sources.json")
    sources = Sources.load(sources_path)
    budget = 60 * float((cc.source or {}).get("daily_minutes", 40))
    started = time.monotonic()
    _, published = _published(cc.repo_path)
    before = _head(repo)
    if sources.tip and before and not _descends(repo, sources.tip):
        # A local rebuild replaced the history this state was built against: its
        # digests, queue and rebuild list describe a corpus that no longer exists.
        console.print("[yellow]The corpus was rebuilt; starting from its baseline.[/yellow]")
        sources = Sources.baseline()
    created, errors, discovered = 0, [], None
    with refresh_sources():
        try:
            discovered = find_changes(cc, sources, published, until=started + budget / 2)
        except Exception as exc:
            logger.exception("Failed to read the Irish source's change signals")
            errors.append(f"Source inventory: {exc}")
        else:
            if dry_run:
                refresh_norms(config, sources.pending, dry_run=True)
            else:
                made, failed = _refresh(config, sources, published, until=started + budget)
                created, errors = made, errors + failed

    if sources.rebuild:
        console.print(
            f"[yellow]{len(sources.rebuild)} law(s) gained an event before their published "
            f"history and wait for a local rebuild: {', '.join(sorted(sources.rebuild)[:10])}"
            "[/yellow]"
        )
    # A run that could not read the signals keeps the last state: a digest advanced
    # without its norm queued would lose that change for good.
    if not dry_run and discovered is not None:
        if before and (Path(cc.repo_path) / "coverage.json").exists():
            # coverage.json is written with every publication, a new exclusion included.
            report = update_report(
                cc.repo_path, before, cc.data_dir, published=published, discovered=len(discovered)
            )
            write_repo_meta(config, "ie", coverage=report)
            if not created and _head(repo) != before:
                created = 1  # the coverage commit alone still has to be pushed
        sources.tip = _head(repo) or ""
        sources.save(sources_path)
    if not dry_run:
        for current_date in dates:
            state.finish_day(current_date, errors)
    return finalize_daily(
        repo, state, dates, created, errors, dry_run=dry_run, push=config.git.push
    )


def write_baseline(config: Config, path: Path = BASELINE) -> Sources:
    """Record what the corpus in ``repo_path`` was built from, read from the local cache.

    Run after a local build and commit the file: the daily starts from it whenever
    its own state is gone. Every page is read as the build left it, whatever its age.
    The pages were fetched under more than one directory cursor, so none is recorded
    and the first run reads them all again.
    """
    from legalize.fetcher.cache import FileCache

    cc = config.get_country("ie")
    _, published = _published(cc.repo_path)
    data_dir = Path(cc.data_dir)
    cache = FileCache(data_dir / "raw", ttl_hours=24 * 365 * 100)
    base = (cc.source or {}).get("isb_base_url", "https://www.irishstatutebook.ie")

    def get(page: str) -> bytes:
        url = f"{base}/eli/cons/en/html" if page == CONSTITUTION_PAGE else f"{base}/isbc/{page}"
        if (entry := cache.get(url)) is None:
            raise FileNotFoundError(f"{url} is not in the local cache")
        return entry.content

    sources = Sources(tip=_head(GitRepo(cc.repo_path, "", "")) or "")
    for norm_id in sorted(published):
        page = page_of(norm_id, get)
        if page and page not in sources.pages:
            sources.pages[page] = content_digest(get(page))
        stamp = data_dir / "source-stamps" / f"{norm_id}.json"
        if stamp.exists() and (day := json.loads(stamp.read_text())["next_status_date"]):
            sources.next_status[norm_id] = day
    catalogue = cache.get(REVISED_INDEX)
    if catalogue is None:
        raise FileNotFoundError(f"{REVISED_INDEX} is not in the local cache")
    sources.catalogue = {
        norm_id: rows_digest(rows)
        for norm_id, rows in revised_catalog(catalogue.content).items()
        if norm_id in published
    }
    sources.save(path)
    return sources
