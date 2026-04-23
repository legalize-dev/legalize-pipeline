"""Justice Canada client -- reads consolidated XML from local clone or HTTP.

Primary mode: read from a local clone of justicecanada/laws-lois-xml.
Fallback mode: download individual XML files via HTTPS.

The local clone is strongly preferred for bootstrap (instant access to all
~11,600 files without HTTP overhead). The HTTP fallback exists for daily
updates when the git clone is not available.

Suvestine (version timeline) sources
------------------------------------

``get_suvestine(norm_id)`` / ``iter_suvestine(norm_id)`` merges every
known version of a law from up to four sources:

- ``upstream-git`` — the commit history of ``justicecanada/laws-lois-xml``
  (covers 2021-02-26 to today). Consolidated XML per commit.
- ``pit-html`` — Justice Canada's own Point-in-Time HTML archive at
  ``/{lang}/{category}/{id}/{YYYYMMDD}/P1TT3xt3.html`` (covers
  2002-12-31 to 2021-02, overlapping the upstream git history safely).
  Consolidated HTML per snapshot, parsed into the same Paragraph shape
  as the XML versions.
- ``annual-statute`` — bill XMLs from
  ``annual-statutes-lois-annuelles/{en,fr}/{year}/{year}-c{N}_{E,F}.xml``
  (covers 2001 to today). Amendment bills as-enacted, not consolidated.
  Attached only to norms whose title appears in the bill title (primary
  attribution, see :class:`AnnualStatuteIndex`).
- ``gazette-pdf`` — Canada Gazette Part III PDF segments (covers 1998 to
  2000 in v1). Bill as-enacted, extracted by OCR.

Each version carries ``source_type`` so the parser can route to the right
renderer. Pre-2011 versions (annual-statute / gazette-pdf) emit amendment-
bill bodies; PIT and upstream-git versions emit consolidated bodies. The
transition at 2011 is a hard content-model boundary (amendment → full
consolidation) documented in RESEARCH-CA-HISTORY.md.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterator

# ``pygit2`` is imported lazily inside ``_thread_repo`` / ``_get_git_log_cache``.
# The pre-commit dispatch check runs under the system ``python3`` (which may
# not have pygit2 installed) and only needs to introspect class attributes,
# so keeping the import off the module's import-time path avoids a spurious
# hook failure. The library is still required at runtime when the CA fetcher
# touches an upstream clone.

from legalize.fetcher.base import HttpClient
from legalize.fetcher.ca.annual_statute_index import (
    AnnualStatuteIndex,
    load_or_build_annual_statute_index,
)
from legalize.fetcher.ca.gazette_index import (
    GazetteIndex,
    GazetteRef,
    load_or_build_gazette_index,
)
from legalize.fetcher.ca.pit_client import PITClient
from legalize.fetcher.ca.title_index import load_or_build_title_index

if TYPE_CHECKING:
    from legalize.config import CountryConfig

logger = logging.getLogger(__name__)

BASE_URL = "https://laws-lois.justice.gc.ca"
DEFAULT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_RPS = 1.0

# Namespace used in Justice Canada XML root attributes.
LIMS_NS = "http://justice.gc.ca/lims"


@dataclass(frozen=True)
class _SvManifestEntry:
    """Lightweight manifest row: ``loader`` fetches the full entry on demand.

    Used by :meth:`JusticeCanadaClient.iter_suvestine` so the client can
    sort + dedup across all sources before paying the XML-load cost. A
    100-version act's manifest is ~20 KB regardless of total XML size.
    """

    source_type: str
    source_id: str
    date: str  # ISO YYYY-MM-DD for sort keying
    loader: Callable[[], dict]


class JusticeCanadaClient(HttpClient):
    """Client for Justice Canada consolidated legislation XML.

    Reads from a local git clone of justicecanada/laws-lois-xml when
    available; falls back to HTTPS downloads for individual files.
    """

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        xml_dir: str = "",
        data_dir: str = "",
        request_timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        requests_per_second: float = DEFAULT_RPS,
        pit_enabled: bool = True,
        pit_categories: tuple[str, ...] = ("eng/acts", "fra/lois"),
    ) -> None:
        super().__init__(
            base_url=base_url,
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
        )
        self._xml_dir = Path(xml_dir) if xml_dir else None
        self._data_dir = Path(data_dir) if data_dir else Path(".")
        # Lazy-loaded indices. Built on first suvestine call and cached for
        # the life of the client — they're heavy to rebuild (~8s) but
        # stable across all norms in a single bootstrap run.
        self._annual_statute_idx: AnnualStatuteIndex | None = None
        # PIT: opt-in per-category. Acts + lois by default because they
        # have rich amendment history worth the network cost; regulations
        # rarely have meaningful PIT trails on Justice Canada's site.
        self._pit_enabled = pit_enabled
        self._pit_categories = pit_categories
        self._pit_client: PITClient | None = None
        # Gazette PDF: only used if the PDF cache exists on disk and is
        # non-empty. The first bootstrap call triggers a lazy scan.
        self._gazette_idx: GazetteIndex | None = None

    @classmethod
    def create(cls, country_config: CountryConfig) -> JusticeCanadaClient:
        source = country_config.source or {}
        # xml_dir defaults to {data_dir}/laws-lois-xml so CI can just override
        # --data-dir and clone the upstream repo into the right place without
        # editing config.yaml for each environment.
        xml_dir = source.get("xml_dir", "")
        if not xml_dir and country_config.data_dir:
            xml_dir = str(Path(country_config.data_dir) / "laws-lois-xml")
        return cls(
            base_url=source.get("base_url", BASE_URL),
            xml_dir=xml_dir,
            data_dir=country_config.data_dir,
            request_timeout=source.get("request_timeout", DEFAULT_TIMEOUT),
            max_retries=source.get("max_retries", DEFAULT_MAX_RETRIES),
            requests_per_second=source.get("requests_per_second", DEFAULT_RPS),
            pit_enabled=source.get("pit_enabled", True),
            pit_categories=tuple(source.get("pit_categories", ("eng/acts", "fra/lois"))),
        )

    # -- LegislativeClient interface ------------------------------------------

    def get_text(self, norm_id: str) -> bytes:
        """Return the full XML for a norm.

        norm_id format: "eng/acts/A-1" or "fra/reglements/SOR-99-129"
        """
        # Try local clone first.
        if self._xml_dir:
            xml_path = self._xml_dir / f"{norm_id}.xml"
            if xml_path.exists():
                return xml_path.read_bytes()

        # Fallback: HTTP download.
        lang, category, file_id = _parse_norm_id(norm_id)
        url = f"{self._base_url}/{lang}/XML/{file_id}.xml"
        logger.info("Downloading %s", url)
        return self._get(url)

    def get_metadata(self, norm_id: str) -> bytes:
        """Same data as get_text -- metadata is embedded in the XML."""
        return self.get_text(norm_id)

    # -- Suvestine -----------------------------------------------------------

    def _annual_statute_index(self) -> AnnualStatuteIndex | None:
        """Build (or reuse) the annual-statute cross-reference index.

        Returns ``None`` if the upstream clone isn't present — in that case
        the suvestine falls back to git-log-only behavior.
        """
        if self._annual_statute_idx is not None:
            return self._annual_statute_idx
        if self._xml_dir is None or not self._xml_dir.exists():
            return None
        try:
            title_idx = load_or_build_title_index(self._xml_dir, self._data_dir)
            self._annual_statute_idx = load_or_build_annual_statute_index(
                self._xml_dir, title_idx, self._data_dir
            )
        except FileNotFoundError as exc:
            logger.warning("Annual-statute index unavailable: %s", exc)
            return None
        return self._annual_statute_idx

    def _git_log_versions(self, norm_id: str) -> list[dict]:
        """Return all upstream-git versions of ``norm_id``, oldest first.

        Backed by a pygit2-built cache (one tree-diff walk at first use)
        + per-thread ``pygit2.Repository`` instances for blob reads, so
        the bootstrap never spawns a ``git`` subprocess from worker code.
        """
        if self._xml_dir is None:
            return []
        rel_path = f"{norm_id}.xml"
        cache = _get_git_log_cache(self._xml_dir)
        commits = cache.get(rel_path, [])
        if not commits:
            return []

        out: list[dict] = []
        for sha, commit_date, blob_oid in commits:
            blob = _read_blob(self._xml_dir, blob_oid)
            if blob is None:
                continue
            encoded = base64.b64encode(blob).decode("ascii")
            del blob
            out.append(
                {
                    "source_type": "upstream-git",
                    "source_id": sha,
                    "date": commit_date,
                    "xml": encoded,
                }
            )
        return out

    def _gazette_index(self) -> GazetteIndex | None:
        """Build (or reuse) the Gazette PDF cross-reference index.

        Returns ``None`` if the PDF cache is absent — the first bootstrap
        run skips gazette entirely unless the operator has populated
        ``{data_dir}/gazette-pdf/`` via ``GazetteClient.fetch_range``.
        """
        if self._gazette_idx is not None:
            return self._gazette_idx
        pdf_root = self._data_dir / "gazette-pdf"
        if not pdf_root.is_dir():
            return None
        try:
            title_idx = load_or_build_title_index(self._xml_dir, self._data_dir)  # type: ignore[arg-type]
        except (FileNotFoundError, TypeError):
            return None
        self._gazette_idx = load_or_build_gazette_index(pdf_root, title_idx, self._data_dir)
        return self._gazette_idx

    def _gazette_versions(self, norm_id: str) -> list[dict]:
        """Return Gazette-PDF chapter events attributed to ``norm_id``.

        Each entry carries the raw extracted body text (per language) plus
        metadata. The parser wraps the text as amendment-event paragraphs
        rather than feeding it through the XML renderer — there's no
        structured XML to route through when the source is a PDF.
        """
        idx = self._gazette_index()
        if idx is None:
            return []
        refs = idx.refs_for(norm_id)
        if not refs:
            return []

        out: list[dict] = []
        _, _, lang_code = _lang_for_norm(norm_id)
        for ref in refs:
            body = self._gazette_body_for(ref, lang_code)
            if not body:
                continue
            out.append(
                {
                    "source_type": "gazette-pdf",
                    "source_id": f"gazette-{ref.year}-c{ref.chapter}",
                    "date": ref.assent_date,
                    "body_text": body,
                    "bill_number": ref.bill_number,
                    "amending_title": (ref.title_en if lang_code == "en" else ref.title_fr),
                    "gazette_pdf_path": ref.pdf_path,
                    "ocr_confidence": ref.ocr_confidence,
                }
            )
        return out

    def _gazette_body_for(self, ref: GazetteRef, lang: str) -> str:
        """Extract and return the body text for one chapter in one language.

        Re-reads the PDF from cache and re-segments it — the on-disk index
        stores only metadata + page ranges, not the bulky body text. This
        keeps the index JSON tiny (a few hundred KB instead of tens of MB)
        while still giving callers fast per-norm lookup.
        """
        from legalize.fetcher.ca.gazette_segmenter import segment
        from legalize.fetcher.ca.pdf_extractor import extract_text_from_pdf

        pdf_path = self._data_dir / ref.pdf_path
        if not pdf_path.exists():
            logger.warning("Gazette PDF missing at %s", pdf_path)
            return ""
        try:
            extraction = extract_text_from_pdf(pdf_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gazette extraction failed for %s: %s", pdf_path, exc)
            return ""
        for seg in segment(extraction):
            if seg.chapter == ref.chapter and seg.year == ref.year:
                return seg.body_en if lang == "en" else seg.body_fr
        return ""

    def _pit_enabled_for(self, norm_id: str) -> bool:
        """PIT-HTML is gated per-category to keep the cache footprint sane.

        Acts + lois opt-in by default (rich amendment history: ~120
        snapshots per heavily-amended act like A-1 or C-46).
        Regulations opt-out by default — their PIT trails are shorter
        and the cache cost-to-value ratio is lower.
        """
        if not self._pit_enabled:
            return False
        for prefix in self._pit_categories:
            if norm_id.startswith(prefix + "/"):
                return True
        return False

    def _pit_versions(self, norm_id: str) -> list[dict]:
        """Return Justice Canada PIT-HTML snapshots for ``norm_id``."""
        if not self._pit_enabled_for(norm_id):
            return []
        if self._pit_client is None:
            self._pit_client = PITClient(cache_dir=self._data_dir)
        try:
            return self._pit_client.fetch_versions(norm_id)
        except Exception as exc:  # noqa: BLE001 — PIT is best-effort
            logger.warning("PIT fetch failed for %s: %s", norm_id, exc)
            return []

    def _annual_statute_versions(self, norm_id: str) -> list[dict]:
        """Return amendment-bill versions attached to ``norm_id`` from the
        annual-statute index."""
        idx = self._annual_statute_index()
        if idx is None or self._xml_dir is None:
            return []
        refs = idx.refs_for(norm_id)
        out: list[dict] = []
        for ref in refs:
            xml_path = self._xml_dir / ref.xml_path
            if not xml_path.exists():
                logger.debug("Missing annual-statute XML %s (referenced from index)", ref.xml_path)
                continue
            try:
                xml_bytes = xml_path.read_bytes()
            except OSError as exc:
                logger.warning("Could not read %s: %s", xml_path, exc)
                continue
            out.append(
                {
                    "source_type": "annual-statute",
                    "source_id": f"as-{ref.year}-c{ref.chapter}",
                    "date": ref.assent_date,
                    "xml": base64.b64encode(xml_bytes).decode("ascii"),
                    "bill_number": ref.bill_number,
                    "amending_title": ref.amending_title,
                }
            )
        return out

    # -- Streaming manifest + lazy loaders ----------------------------------

    def _iter_git_log_manifest(self, norm_id: str) -> Iterator[_SvManifestEntry]:
        """Yield one lightweight entry per upstream-git commit (no XML yet).

        Backed by the pygit2 cache (one tree-diff walk at first use)
        and per-thread ``pygit2.Repository`` instances for blob reads,
        so manifest construction and per-entry loading both run inside
        the same Python process — no ``git`` subprocess is ever spawned
        from worker code.
        """
        if self._xml_dir is None:
            return
        rel_path = f"{norm_id}.xml"
        cache = _get_git_log_cache(self._xml_dir)
        entries = cache.get(rel_path, [])
        if not entries:
            return

        xml_dir = self._xml_dir  # capture for the closures

        def _loader_for(sha: str, commit_date: str, blob_oid: str) -> Callable[[], dict]:
            def _load() -> dict:
                blob = _read_blob(xml_dir, blob_oid)
                if blob is None:
                    return {}
                encoded = base64.b64encode(blob).decode("ascii")
                del blob
                return {
                    "source_type": "upstream-git",
                    "source_id": sha,
                    "date": commit_date,
                    "xml": encoded,
                }

            return _load

        for sha, commit_date, blob_oid in entries:
            yield _SvManifestEntry(
                source_type="upstream-git",
                source_id=sha,
                date=commit_date,
                loader=_loader_for(sha, commit_date, blob_oid),
            )

    def _iter_pit_manifest(self, norm_id: str) -> Iterator[_SvManifestEntry]:
        """Yield one lightweight entry per Justice Canada PIT HTML snapshot.

        The PIT index HTML is fetched once up front (one HTTP call, a
        few KB); each snapshot's HTML is downloaded + base64-encoded
        inside the loader so at most one snapshot's payload sits in
        memory at a time.
        """
        if not self._pit_enabled_for(norm_id):
            return
        if self._pit_client is None:
            self._pit_client = PITClient(cache_dir=self._data_dir)
        client = self._pit_client

        try:
            entries = client.fetch_versions(norm_id)
        except Exception as exc:  # noqa: BLE001 — PIT is best-effort
            logger.warning("PIT fetch failed for %s: %s", norm_id, exc)
            return

        def _loader_for(entry: dict) -> Callable[[], dict]:
            return lambda: entry

        for entry in entries:
            yield _SvManifestEntry(
                source_type=entry["source_type"],
                source_id=entry["source_id"],
                date=entry["date"],
                loader=_loader_for(entry),
            )

    def _iter_annual_statute_manifest(self, norm_id: str) -> Iterator[_SvManifestEntry]:
        """Yield one lightweight entry per annual-statute amendment.

        XMLs are read from the local clone on demand inside the loader.
        """
        idx = self._annual_statute_index()
        if idx is None or self._xml_dir is None:
            return
        refs = idx.refs_for(norm_id)
        if not refs:
            return
        xml_dir = self._xml_dir  # captured

        def _loader_for(ref) -> Callable[[], dict]:
            def _load() -> dict:
                xml_path = xml_dir / ref.xml_path
                if not xml_path.exists():
                    logger.debug(
                        "Missing annual-statute XML %s (referenced from index)",
                        ref.xml_path,
                    )
                    return {}
                try:
                    xml_bytes = xml_path.read_bytes()
                except OSError as exc:
                    logger.warning("Could not read %s: %s", xml_path, exc)
                    return {}
                encoded = base64.b64encode(xml_bytes).decode("ascii")
                del xml_bytes
                return {
                    "source_type": "annual-statute",
                    "source_id": f"as-{ref.year}-c{ref.chapter}",
                    "date": ref.assent_date,
                    "xml": encoded,
                    "bill_number": ref.bill_number,
                    "amending_title": ref.amending_title,
                }

            return _load

        for ref in refs:
            yield _SvManifestEntry(
                source_type="annual-statute",
                source_id=f"as-{ref.year}-c{ref.chapter}",
                date=ref.assent_date,
                loader=_loader_for(ref),
            )

    def _iter_gazette_manifest(self, norm_id: str) -> Iterator[_SvManifestEntry]:
        """Yield one lightweight entry per Gazette PDF chapter affecting ``norm_id``.

        Body text extraction (``extract_text_from_pdf`` + ``segment``) runs
        inside the loader — the default is to re-read the PDF per yield,
        but the LRU inside the extractor absorbs back-to-back calls on
        the same file.
        """
        idx = self._gazette_index()
        if idx is None:
            return
        refs = idx.refs_for(norm_id)
        if not refs:
            return

        _, _, lang_code = _lang_for_norm(norm_id)

        def _loader_for(ref) -> Callable[[], dict]:
            def _load() -> dict:
                body = self._gazette_body_for(ref, lang_code)
                if not body:
                    return {}
                return {
                    "source_type": "gazette-pdf",
                    "source_id": f"gazette-{ref.year}-c{ref.chapter}",
                    "date": ref.assent_date,
                    "body_text": body,
                    "bill_number": ref.bill_number,
                    "amending_title": (ref.title_en if lang_code == "en" else ref.title_fr),
                    "gazette_pdf_path": ref.pdf_path,
                    "ocr_confidence": ref.ocr_confidence,
                }

            return _load

        for ref in refs:
            yield _SvManifestEntry(
                source_type="gazette-pdf",
                source_id=f"gazette-{ref.year}-c{ref.chapter}",
                date=ref.assent_date,
                loader=_loader_for(ref),
            )

    def iter_suvestine(self, norm_id: str) -> Iterator[dict]:
        """Stream one version entry at a time, chronologically sorted + deduped.

        This is the memory-efficient counterpart to :meth:`get_suvestine`.
        The pipeline prefers this path when both client and parser expose
        the streaming interface. Peak RSS during a full Criminal Code
        bootstrap drops from ~2.5 GB (bytes path) to <500 MB with the
        stream path because only the currently-yielded entry's XML (or
        body text) is resident — no JSON blob is ever materialised.

        Dedup and ordering follow the same rules as :meth:`get_suvestine`:
        chronological by event date, duplicate ``source_id``s dropped,
        gazette-pdf entries suppressed when an annual-statute entry with
        the same (year, chapter) covers the same bill.
        """
        if self._xml_dir is None or not self._xml_dir.exists():
            logger.warning(
                "No upstream clone at %s; suvestine stream falls back to current text",
                self._xml_dir,
            )
            try:
                current = self.get_text(norm_id)
            except Exception:  # noqa: BLE001 — absolute fallback, may fail offline
                return
            today = date.today().isoformat()
            yield {
                "source_type": "http-current",
                "source_id": "current",
                "date": today,
                "xml": base64.b64encode(current).decode("ascii"),
            }
            return

        # Build a lightweight manifest across all sources — metadata only,
        # no XML loaded yet. For a 100-version act the manifest is ~20 KB.
        manifest: list[_SvManifestEntry] = []
        manifest.extend(self._iter_git_log_manifest(norm_id))
        manifest.extend(self._iter_pit_manifest(norm_id))
        manifest.extend(self._iter_gazette_manifest(norm_id))
        manifest.extend(self._iter_annual_statute_manifest(norm_id))

        manifest.sort(key=lambda m: m.date)

        # Dedup: collect keys first so gazette-pdf can defer to
        # annual-statute on matching (year, chapter).
        annual_keys: set[tuple[int, int]] = set()
        for m in manifest:
            if m.source_type == "annual-statute":
                key = _statute_year_chapter(m.source_id)
                if key is not None:
                    annual_keys.add(key)

        seen_ids: set[str] = set()
        for m in manifest:
            if m.source_id in seen_ids:
                continue
            if m.source_type == "gazette-pdf":
                gkey = _statute_year_chapter(m.source_id.replace("gazette-", "as-", 1))
                if gkey is not None and gkey in annual_keys:
                    continue
            seen_ids.add(m.source_id)
            entry = m.loader()
            if not entry:
                continue
            yield entry
            # Help the allocator: the entry dict (with its base64 XML
            # string) can weigh tens of MB for big consolidated acts.
            # We can't force the consumer to release it, but we can drop
            # our own reference before moving to the next.
            del entry

    def get_suvestine(self, norm_id: str) -> bytes:
        """Return a merged chronological timeline of all known versions.

        Merges git-log consolidations (2021+) with PIT-HTML snapshots
        (2002+), annual-statute amendments (2001+), and Gazette PDF
        segments (1998-2000). Legacy bytes-based interface — the
        streaming ``iter_suvestine`` is preferred for memory reasons.
        """
        all_versions: list[dict] = []

        if self._xml_dir is None or not self._xml_dir.exists():
            logger.warning(
                "No upstream clone at %s; suvestine falls back to single snapshot",
                self._xml_dir,
            )
            current = self.get_text(norm_id)
            today = date.today().isoformat()
            all_versions.append(
                {
                    "source_type": "http-current",
                    "source_id": "current",
                    "date": today,
                    "xml": base64.b64encode(current).decode("ascii"),
                }
            )
            return json.dumps({"versions": all_versions}).encode("utf-8")

        # 1. Upstream git log (2021-02 → today).
        all_versions.extend(self._git_log_versions(norm_id))

        # 2. Justice Canada PIT-HTML snapshots (2002-12 → 2021-02). Same
        #    consolidated shape as upstream — the boundary at 2021 is
        #    invisible in the body except for metadata.
        all_versions.extend(self._pit_versions(norm_id))

        # 3. Gazette Part III PDF segments (1998 → 2000 in v1). Filled in
        #    only when the operator has populated the PDF cache.
        all_versions.extend(self._gazette_versions(norm_id))

        # 4. Annual-statute amendments (2001 → today, primary attribution).
        #    Many of these predate the upstream git log so they push history
        #    further back without overlap. When they overlap (same bill was
        #    both recorded via git-log commit AND cross-referenced), we
        #    keep both: the git-log version is the consolidated text AFTER
        #    the amendment, the annual-statute version is the amendment
        #    itself — different content, not duplicates.
        all_versions.extend(self._annual_statute_versions(norm_id))

        # Chronological sort: oldest-first. Stable ties preserve source
        # order (git log was appended first, so git-log versions win on
        # same-day ties — matters at the 2021 boundary where PIT-HTML
        # should yield to upstream).
        all_versions.sort(key=lambda v: v["date"])

        # Deduplicate. Two rules in priority order:
        # 1. Exact source_id match — a bug-level duplicate, drop.
        # 2. Same (year, chapter) across annual-statute and gazette-pdf —
        #    the annual-statute XML is authoritative and wins over the
        #    OCR-inferred gazette-pdf content. Source_ids encode the key:
        #    ``as-{Y}-c{N}`` vs ``gazette-{Y}-c{N}``.
        seen_ids: set[str] = set()
        annual_keys: set[tuple[int, int]] = set()
        for v in all_versions:
            if v.get("source_type") == "annual-statute":
                key = _statute_year_chapter(v.get("source_id", ""))
                if key:
                    annual_keys.add(key)

        deduped: list[dict] = []
        for v in all_versions:
            sid = v.get("source_id", "")
            if sid in seen_ids:
                continue
            if v.get("source_type") == "gazette-pdf":
                key = _statute_year_chapter(sid.replace("gazette-", "as-", 1))
                if key and key in annual_keys:
                    # Annual-statute covers this chapter — skip the PDF entry.
                    continue
            seen_ids.add(sid)
            deduped.append(v)

        if not deduped:
            # Final degradation: no git log, no annual statute, no clone —
            # emit the current text as a single snapshot so the pipeline
            # can still produce a valid bootstrap commit.
            current = self.get_text(norm_id)
            today = date.today().isoformat()
            deduped.append(
                {
                    "source_type": "http-current",
                    "source_id": "current",
                    "date": today,
                    "xml": base64.b64encode(current).decode("ascii"),
                }
            )

        blob = json.dumps({"versions": deduped}).encode("utf-8")
        # Release the intermediate lists before returning so the caller's
        # next call (same worker, next norm) doesn't start on top of the
        # previous law's peak. The encoded blob alone can be 100s of MB
        # for Criminal Code; holding ``all_versions`` + ``deduped`` on top
        # doubles the transient footprint until the GC decides to run.
        del all_versions, deduped, seen_ids, annual_keys
        import gc as _gc

        _gc.collect()
        return blob


def _parse_norm_id(norm_id: str) -> tuple[str, str, str]:
    """Parse 'eng/acts/A-1' into (lang, category, file_id).

    >>> _parse_norm_id("eng/acts/A-1")
    ('eng', 'acts', 'A-1')
    >>> _parse_norm_id("fra/reglements/SOR-99-129")
    ('fra', 'reglements', 'SOR-99-129')
    """
    parts = norm_id.split("/", 2)
    if len(parts) != 3:
        raise ValueError(f"Invalid CA norm_id: {norm_id!r} (expected lang/category/id)")
    return parts[0], parts[1], parts[2]


def _statute_year_chapter(source_id: str) -> tuple[int, int] | None:
    """Parse an ``as-{Y}-c{N}`` source_id into ``(year, chapter)``.

    Returns ``None`` for source_ids that don't match (git SHAs, PIT
    timestamps, etc). Used by the dedup logic to cross-reference
    annual-statute and gazette-pdf entries.
    """
    import re

    m = re.fullmatch(r"(?:as|gazette)-(\d{4})-c(\d{1,3})", source_id)
    if not m:
        return None
    try:
        return int(m.group(1)), int(m.group(2))
    except (TypeError, ValueError):
        return None


def _lang_for_norm(norm_id: str) -> tuple[str, str, str]:
    """Return ``(url_lang, category, short_lang)`` for a norm_id.

    ``short_lang`` is the 2-letter code used by the Gazette / title
    indices (``"en"``/``"fr"``) — note that in norm_id we use the 3-letter
    ``"eng"``/``"fra"`` matching Justice Canada's URL structure.
    """
    url_lang, category, _ = _parse_norm_id(norm_id)
    short_lang = "fr" if url_lang == "fra" else "en"
    return url_lang, category, short_lang


# ─────────────────────────────────────────────
# Native git access for the upstream clone (pygit2 / libgit2)
# ─────────────────────────────────────────────
#
# Per-norm ``git log`` + ``git show`` subprocesses are the single biggest
# bottleneck on a full bootstrap. With 11.6 K norms × ~5 commits each the
# naive path forks 60+ K git processes — fork/exec dominates wall-clock
# time and git's repository lock serialises the worker threads.
#
# The fetcher therefore never shells out to git. Instead:
#
# 1. ``_get_git_log_cache(xml_dir)`` walks the repo ONCE at first use via
#    ``pygit2.Repository`` + tree diffs. It records, for every changed
#    (path, commit) pair, the pre-resolved blob OID so later lookups are
#    a single ``repo[oid].data`` call with no tree navigation. The result
#    is cached module-globally per ``xml_dir``.
#
# 2. ``_read_blob(xml_dir, oid)`` reads a blob via a per-THREAD
#    ``pygit2.Repository`` instance (libgit2 objects are not thread-safe
#    across instances, but opening one per worker is cheap and eliminates
#    every form of cross-thread lock contention).
#
# The cache survives for the life of the process — safe because the
# upstream clone is read-only during a bootstrap and the cache
# invalidation story is "kill the process and re-run".

_GIT_LOG_CACHE: dict[str, dict[str, list[tuple[str, str, str]]]] = {}
_GIT_LOG_CACHE_LOCK = threading.Lock()

_REPO_TLS = threading.local()


def _thread_repo(xml_dir: Path):
    """Return a thread-local ``pygit2.Repository`` rooted at ``xml_dir``.

    Each worker thread opens its own handle on first access; libgit2
    object databases are safe to use from the thread that opened them
    but not across threads. Opening the repo is cheap (<1 ms) so the
    one-off cost per worker is negligible.
    """
    import pygit2

    key = str(xml_dir.resolve())
    cache = getattr(_REPO_TLS, "repos", None)
    if cache is None:
        cache = {}
        _REPO_TLS.repos = cache
    repo = cache.get(key)
    if repo is None:
        repo = pygit2.Repository(str(xml_dir))
        cache[key] = repo
    return repo


def _walk_tree_blobs(repo, tree, prefix: str = "") -> Iterator[tuple[str, str]]:
    """Yield ``(full_path, blob_oid)`` for every blob under ``tree``."""
    for entry in tree:
        full = entry.name if not prefix else f"{prefix}/{entry.name}"
        if entry.type_str == "tree":
            yield from _walk_tree_blobs(repo, repo[entry.id], full)
        elif entry.type_str == "blob":
            yield full, str(entry.id)


def _get_git_log_cache(xml_dir: Path) -> dict[str, list[tuple[str, str, str]]]:
    """Return the cached ``{rel_path: [(commit_sha, iso_date, blob_oid), …]}``.

    Built lazily on first access. The walk visits every commit reachable
    from the HEAD history in chronological order (oldest first) and uses
    tree diffs to record which paths changed; for the root commit every
    blob is registered. ``diff.deltas`` is iterated directly (no patch
    materialisation), which turns a ~220 s full walk into ~2 s on the
    Justice Canada clone.
    """
    import pygit2

    key = str(xml_dir.resolve())
    with _GIT_LOG_CACHE_LOCK:
        cached = _GIT_LOG_CACHE.get(key)
        if cached is not None:
            return cached
        logger.info("Building git log cache for %s via pygit2 (one-time)", xml_dir)
        repo = pygit2.Repository(str(xml_dir))

        sort = pygit2.enums.SortMode.TOPOLOGICAL | pygit2.enums.SortMode.REVERSE
        commits = list(repo.walk(repo.head.target, sort))

        cache: dict[str, list[tuple[str, str, str]]] = {}
        for commit in commits:
            iso_date = (
                datetime.fromtimestamp(commit.author.time, tz=timezone.utc).date().isoformat()
            )
            sha = str(commit.id)
            if commit.parents:
                parent_tree = commit.parents[0].tree
                diff = parent_tree.diff_to_tree(commit.tree)
                for delta in diff.deltas:
                    if delta.status == pygit2.enums.DeltaStatus.DELETED:
                        continue
                    path = delta.new_file.path
                    if not path:
                        continue
                    cache.setdefault(path, []).append((sha, iso_date, str(delta.new_file.id)))
            else:
                # Root commit — every blob counts as "added".
                for full_path, blob_oid in _walk_tree_blobs(repo, commit.tree):
                    cache.setdefault(full_path, []).append((sha, iso_date, blob_oid))

        _GIT_LOG_CACHE[key] = cache
        logger.info(
            "git log cache ready: %d files with history, %d total commits recorded",
            len(cache),
            sum(len(v) for v in cache.values()),
        )
        return cache


def _read_blob(xml_dir: Path, blob_oid: str) -> bytes | None:
    """Return the raw bytes of the blob ``blob_oid`` in the clone at ``xml_dir``.

    Goes through the thread-local ``pygit2.Repository``; returns ``None``
    if the object is missing (treated as a clean skip by callers).
    """
    import pygit2

    try:
        repo = _thread_repo(xml_dir)
        obj = repo.get(blob_oid)
    except (KeyError, ValueError, pygit2.GitError) as exc:  # noqa: BLE001
        logger.warning("blob lookup failed for %s: %s", blob_oid, exc)
        return None
    if obj is None or obj.type_str != "blob":
        return None
    return obj.data
