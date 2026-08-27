"""Portugal (PT) — client for the Diário da República Eletrónico.

Two surfaces, one client:

``cons:{tipo}:{ano}-{fragId}``
    a diploma DRE consolidates. ``get_suvestine`` walks its amendment timeline and
    returns one point-in-time snapshot per effective date, which becomes one commit
    per reform. 5,528 diplomas, 13,030 amendment dates.

``pub:{tipo}:{key}``
    every other diploma, as printed in the Diário da República. A published text
    never changes, so its "timeline" is a single snapshot.

Both shapes go through ``get_suvestine`` so the pipeline has one path.
"""

from __future__ import annotations

import base64
import gzip
import json
import logging
import threading
from typing import Any

from pathlib import Path

from legalize.fetcher._text import clean
from legalize.fetcher.base import LegislativeClient
from legalize.fetcher.pt.dre_api import DREApi, DREApiError

logger = logging.getLogger(__name__)

CONSOLIDATED = "cons"
PUBLISHED = "pub"

# DRE's placeholder for "this version has always been here": fragments carried over
# from the original text report DataEntradaVigor 1900-01-01.
_NO_DATE = "1900-01-01"


def published_date_of(detail: dict) -> str:
    """The day a diploma reached the public, as DRE actually recorded it.

    DataPublicacao is the answer almost always, but on some records DRE leaves the
    1900-01-01 sentinel there and puts the real day in DataDistribuicao. The sentinel
    parses as a valid date, so an `or` chain never falls through it — the diploma
    just publishes as 1900-01-01, sorts to the very front of the repository history
    and claims to predate the Diário da República.
    """
    for field in ("DataPublicacao", "DataDistribuicao", "DataDisponibilizacao"):
        value = (detail.get(field) or "")[:10]
        if value and value != _NO_DATE:
            return value
    return ""


# Only these fragment fields survive into the version blob. A full Código Civil
# snapshot is 5.7 MB of JSON; 71 of them held in memory at once is several GB.
_FRAG_FIELDS = (
    "Id",
    "FragmentoVersaoId",
    "PaiId",
    "Orderm",
    "IndexOrdem",
    "Name",
    "Epigrafe",
    "IsAnexo",
)
_VERSION_FIELDS = (
    # FragmentoId is the article's stable identity across consolidations.
    # ConsolidacaoFragmento.Id is NOT: it is the row id within one consolidation and
    # changes every time DRE reconsolidates, so keying blocks on it produces one
    # block per snapshot (158,186 instead of 2,895 for the Código Civil).
    "FragmentoId",
    "FragmentoPaiId",
    "Id",
    "Texto",
    "Epigrafe",
    "Identificacao",
    "Ordem",
    "Tituo",
    "OmitTipo",
    "TipoFragmentoId",
    "VersaoEstadoId",
    "DataEntradaVigor",
    "DataProducaoEfeitos",
    "DataSuspensao",
    "DataVersao",
)

_shared_api: DREApi | None = None
_shared_lock = threading.Lock()


def _shared_transport(**kwargs: Any) -> DREApi:
    """One authenticated DRE session per process.

    ``pipeline.generic_fetch_one`` builds a client per norm. Each DRE handshake costs
    four GETs, so a per-norm session would add ~440,000 requests to a full bootstrap.
    """
    global _shared_api
    with _shared_lock:
        if _shared_api is None:
            _shared_api = DREApi(**kwargs)
        return _shared_api


def parse_norm_id(norm_id: str) -> tuple[str, str, str]:
    """``cons:decreto-lei:1966-34509075`` -> ``("cons", "decreto-lei", "1966-34509075")``."""
    parts = (norm_id or "").split(":", 2)
    if len(parts) != 3 or parts[0] not in (CONSOLIDATED, PUBLISHED):
        raise ValueError(
            f"Bad PT norm id {norm_id!r}. Expected 'cons:<tipo>:<ano>-<fragId>' or "
            f"'pub:<tipo>:<key>'."
        )
    return parts[0], parts[1], parts[2]


def _pack(payload: Any) -> str:
    return base64.b64encode(
        gzip.compress(json.dumps(payload, ensure_ascii=False).encode())
    ).decode()


def unpack(blob: str) -> Any:
    return json.loads(gzip.decompress(base64.b64decode(blob)).decode("utf-8"))


def _slim(items: list[dict]) -> list[dict]:
    """Keep only the fragment fields the parser reads."""
    out = []
    for item in items:
        frag = item.get("ConsolidacaoFragmento") or {}
        version = item.get("FragmentoVersao") or {}
        out.append(
            {
                "frag": {k: frag.get(k) for k in _FRAG_FIELDS},
                "version": {k: version.get(k) for k in _VERSION_FIELDS},
                "nota": (item.get("Nota") or {}).get("List") or [],
                "alteracoes": (item.get("AlteracoesList") or {}).get("List") or [],
            }
        )
    return out


class DREClient(LegislativeClient):
    """Fetches Portuguese legislation from diariodarepublica.pt."""

    @classmethod
    def create(cls, country_config) -> DREClient:
        source = country_config.source or {}
        return cls(
            raw_dir=Path(country_config.data_dir) / "raw",
            request_timeout=int(source.get("request_timeout", 60)),
            requests_per_second=float(source.get("requests_per_second", 2.0)),
            max_retries=int(source.get("max_retries", 3)),
        )

    def __init__(self, raw_dir: Path | str | None = None, **transport_kwargs: Any) -> None:
        self._api = _shared_transport(**transport_kwargs)
        self._headers: dict[str, dict] = {}
        self._cache_lock = threading.Lock()
        # The pipeline's own cache stores the *parsed* norm, so any parser change
        # would mean re-downloading the whole corpus (~18 h). Keeping the raw
        # envelopes turns that into a 20-minute reparse.
        self._raw_dir = Path(raw_dir) if raw_dir else None
        if self._raw_dir:
            self._raw_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------- raw cache

    def _raw_path(self, norm_id: str, kind: str) -> Path | None:
        if not self._raw_dir:
            return None
        safe = norm_id.replace(":", "-").replace("/", "-")
        return self._raw_dir / f"{safe}.{kind}.json.gz"

    def _raw_load(self, norm_id: str, kind: str) -> Any | None:
        path = self._raw_path(norm_id, kind)
        if path and path.exists():
            try:
                with gzip.open(path, "rt", encoding="utf-8") as handle:
                    return json.load(handle)
            except Exception:
                logger.warning("Corrupt raw cache, refetching: %s", path)
        return None

    def _raw_save(self, norm_id: str, kind: str, payload: Any) -> None:
        path = self._raw_path(norm_id, kind)
        if not path:
            return
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        tmp.replace(path)

    # --------------------------------------------------------------- fetching

    def _published(self, tipo: str, key: str) -> dict:
        return self._api.published_detail(f"/dr/detalhe/{tipo}/{key}")

    def _header(self, tipo: str, key: str) -> dict:
        """The consolidated header, cached — three pipeline calls share one fetch."""
        cache_key = f"{tipo}/{key}"
        with self._cache_lock:
            hit = self._headers.get(cache_key)
        if hit is not None:
            return hit
        ano, frag_id = key.split("-", 1)
        header = self._api.consolidated_header(tipo, int(ano), frag_id)
        with self._cache_lock:
            self._headers[cache_key] = header
            # The pipeline processes one norm at a time per worker; keep the cache
            # from growing across a 110k-norm run.
            if len(self._headers) > 64:
                self._headers.pop(next(iter(self._headers)))
        return header

    def _bundle(self, norm_id: str) -> dict:
        """Everything the metadata parser needs, from both surfaces."""
        cached = self._raw_load(norm_id, "meta")
        if cached is not None:
            return cached
        bundle = self._build_bundle(norm_id)
        self._raw_save(norm_id, "meta", bundle)
        return bundle

    def _build_bundle(self, norm_id: str) -> dict:
        surface, tipo, key = parse_norm_id(norm_id)
        if surface == PUBLISHED:
            return {
                "surface": PUBLISHED,
                "tipo": tipo,
                "key": key,
                "published": self._published(tipo, key),
            }

        header = self._header(tipo, key)
        detail = header.get("ConsolidadaConteudoDetalhe") or {}
        published: dict = {}
        ref = ((detail.get("DiplomaLegis") or {}).get("LinkSitemap") or "").strip()
        if ref:
            # The consolidated header has no Vigencia, no ELI RDFa, no page range and
            # no signature date. The as-published record has all of them.
            try:
                published = self._api.published_detail(ref)
            except DREApiError:
                logger.warning("No as-published record for %s (%s)", norm_id, ref)
        return {
            "surface": CONSOLIDATED,
            "tipo": tipo,
            "key": key,
            "header": detail,
            "consolidation": {
                k: header.get(k)
                for k in (
                    "CurrentConsolidacaoId",
                    "LastConsolidacaoId",
                    "DataUltimaConsolidada",
                    "IsVersaoInicial",
                    "IsMultipleConsolidation",
                    "HasIndice",
                    "HasFile",
                    "HasJurisprudenciaAssociada",
                    "URLPDF",
                )
            },
            "published": published,
        }

    # ----------------------------------------------------- LegislativeClient

    def get_metadata(self, norm_id: str) -> bytes:
        return json.dumps(self._bundle(norm_id), ensure_ascii=False).encode("utf-8")

    def get_text(self, norm_id: str) -> bytes:
        """The current text. Real history comes from ``get_suvestine``."""
        surface, _tipo, _key = parse_norm_id(norm_id)
        if surface == PUBLISHED:
            # Through _bundle, not _published: the raw cache makes this free instead
            # of a second detail call for every one of 204,314 diplomas.
            detail = self._bundle(norm_id).get("published") or {}
            # Where the Jornal Oficial dos Açores leaves the corpus. 21 % of the
            # as-published ids are DRE's legacy regional catalogue — every row with
            # a FonteRegional names the Azorean gazette — and legalize-pt is the
            # Diário da República (research/RESEARCH-PT-v2.md §11). Keyed on the
            # marker, not on emptiness: 188 of those rows do carry their text, and
            # they are out of scope for being another gazette, not for being blank.
            if (detail.get("TipoConteudo") or "") == "DiplomaLegacor":
                raise ValueError(f"Jornal Oficial dos Açores, out of scope: {norm_id}")
            # clean() first: DRE writes a lone NUL into Texto on the rows it has
            # no text for, and "\x00".strip() is not empty — those would otherwise
            # ship as a law with no content at all.
            body = clean(detail.get("TextoFormatado") or detail.get("Texto") or "").strip()
            if not body and not (detail.get("URL_PDF") or "").strip():
                raise ValueError(f"No text and no PDF for {norm_id}")
            # Historical types (acórdãos doutrinários, cartas de lei, regimentos)
            # exist at DRE only as a scan. Publishing the diploma with its metadata
            # and a link to the official PDF beats leaving a hole in the corpus.
            return body.encode("utf-8")
        # For a consolidated diploma the text is assembled per version; the parser
        # works off the suvestine blob, so this only has to be non-empty.
        return b"{}"

    def get_suvestine(self, norm_id: str) -> bytes:
        """Every historical version of one diploma, as a single JSON blob.

        Named to match the pipeline hook (``hasattr(client, "get_suvestine")``); the
        semantics are Lithuania's and Belgium's — one source, many dated versions,
        one reform per version.

        A published-only diploma returns a one-version blob rather than raising, so
        the pipeline has a single path and never falls through to the "commit the
        current text as a fabricated original version" branch.
        """
        cached = self._raw_load(norm_id, "versions")
        if cached is not None:
            return json.dumps(cached, ensure_ascii=False).encode("utf-8")
        blob = self._build_suvestine(norm_id)
        self._raw_save(norm_id, "versions", blob)
        return json.dumps(blob, ensure_ascii=False).encode("utf-8")

    def _build_suvestine(self, norm_id: str) -> dict:
        surface, tipo, key = parse_norm_id(norm_id)
        bundle = self._bundle(norm_id)

        if surface == PUBLISHED:
            detail = bundle["published"]
            return {
                "norm_id": norm_id,
                "surface": PUBLISHED,
                "pdf_url": (detail.get("URL_PDF") or "").strip(),
                "versions": [
                    {
                        "date": published_date_of(detail),
                        "is_original": True,
                        "amending": None,
                        "html_b64": _pack(
                            detail.get("TextoFormatado") or detail.get("Texto") or ""
                        ),
                    }
                ],
            }

        ano, frag_id = key.split("-", 1)
        detail = bundle["header"]
        legis_id = str((detail.get("DiplomaLegis") or {}).get("Id") or "0")
        header = self._header(tipo, key)

        timeline = self._api.consolidated_timeline(legis_id, frag_id)
        # date -> the act that made the change effective on that date
        amendments: dict[str, dict] = {}
        for act in timeline:
            for mod in (act.get("ModificacaoList") or {}).get("List") or []:
                when = (mod.get("DataEntradaVigor") or "")[:10]
                if not when or when == _NO_DATE:
                    continue
                entry = amendments.setdefault(
                    when,
                    {
                        "numero": act.get("Numero"),
                        "tipo": act.get("TipoDiploma"),
                        "title": act.get("Title"),
                        "sumario": act.get("SumarioDiplomaLegis"),
                        "published_at": (act.get("DataPublicacao") or "")[:10],
                        "legis_id": act.get("DiplomaLegisId"),
                        "link": act.get("LinkSitemap"),
                        "articles": [],
                    },
                )
                label = (mod.get("FragmentoDestinoModificacao") or "").strip()
                if label and label not in entry["articles"]:
                    entry["articles"].append(label)

        original = published_date_of(bundle.get("published") or {}) or published_date_of(
            detail.get("DiplomaLegis") or {}
        )
        dates = sorted(amendments)
        if original and (not dates or original < dates[0]):
            dates = [original, *dates]
        elif not dates:
            dates = [original or _NO_DATE]

        versions = []
        for when in dates:
            snapshot = self._api.consolidated_snapshot(
                tipo, int(ano), frag_id, legis_id, when, header
            )
            fragments = (snapshot.get("LegConsBase") or {}).get("List") or []
            if not fragments and when == dates[0]:
                # 5 % of consolidated-sitemap entries (mostly acórdãos) are listed but
                # never fragmented. Signal it so the caller can fall back to surface B.
                raise DREApiError(f"{norm_id}: consolidated snapshot at {when} has no fragments")
            versions.append(
                {
                    "date": when,
                    "is_original": when not in amendments,
                    "amending": amendments.get(when),
                    "fragments_b64": _pack(_slim(fragments)),
                }
            )

        return {
            "norm_id": norm_id,
            "surface": CONSOLIDATED,
            "diploma_legis_id": legis_id,
            "diploma_frag_id": frag_id,
            "amending_acts": len(timeline),
            "pdf_url": (
                (bundle.get("published") or {}).get("URL_PDF")
                or (bundle.get("consolidation") or {}).get("URLPDF")
                or ""
            ).strip(),
            "versions": versions,
        }

    def close(self) -> None:
        """No-op: the transport is shared process-wide (see ``_shared_transport``)."""
        return
