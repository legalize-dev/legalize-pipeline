"""Title → norm_id index built from the local clone.

Amendment bills (both ``annual-statutes-lois-annuelles`` XML and Canada Gazette
Part III PDFs) reference the acts they amend by title, not by
ConsolidatedNumber. To attribute each amendment to the right norm in our repo
we need a reverse index: "Income Tax Act" → ``I-3.3``.

Scans all consolidated acts and regulations under ``{xml_dir}/{eng,fra}/``,
extracts the ShortTitle for each, and writes a JSON blob to
``{data_dir}/title-index.json``. Rebuild is cheap (~2s for 11,600 files) and
idempotent; callers can force a rebuild when the upstream clone has new laws.

Lookup rules (in order):
    1. exact match on normalized title
    2. match with leading article stripped ("the "/"an "/"la ")
    3. match with trailing "Act"/"Loi" stripped

Returns ``None`` on miss — callers decide whether to log/skip the amendment
or fall back to a generic "ca-en/__unknown__.md" sink (we prefer skip + log
so spurious amendments never land on the wrong law).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from lxml import etree

logger = logging.getLogger(__name__)


INDEX_FILENAME = "title-index.json"

# Leading articles to strip when normalizing titles. Keep short — these are
# article-like prefixes only, not domain words.
_LEADING_ARTICLES_EN = ("the ",)
_LEADING_ARTICLES_FR = ("la ", "le ", "les ", "l'", "l’")

# Trailing "Act" / "Loi" stripping as a fallback match. "Income Tax Act" and
# "Income Tax" should both resolve to the same norm when the bill happens to
# refer to the act by its running-head form.
_TRAILING_STRIPS_EN = (" act",)
_TRAILING_STRIPS_FR = (" loi",)

# Non-alphanumerics get collapsed to a single space during normalization.
_NON_ALNUM = re.compile(r"[^\w\s]+", re.UNICODE)
_WS = re.compile(r"\s+")


def _normalize(title: str) -> str:
    """Return a canonical key for title lookup.

    Lowercase, NFKC-independent (input should already be decoded), strip
    punctuation, collapse whitespace. Leading articles are handled by the
    lookup function, not by normalize, so the index stores both forms when
    they differ.
    """
    if not title:
        return ""
    t = title.strip().lower()
    t = _NON_ALNUM.sub(" ", t)
    t = _WS.sub(" ", t).strip()
    return t


def _strip_leading_article(normalized: str, articles: tuple[str, ...]) -> str:
    for art in articles:
        if normalized.startswith(art):
            return normalized[len(art) :].strip()
    return normalized


def _strip_trailing(normalized: str, tails: tuple[str, ...]) -> str:
    for tail in tails:
        if normalized.endswith(tail):
            return normalized[: -len(tail)].strip()
    return normalized


@dataclass(frozen=True)
class TitleIndex:
    """Bidirectional map: normalized title ↔ norm_id, per language.

    Stored per-language (``en`` / ``fr``) because the same English title can
    translate to a French norm of different shape, and we never want to
    cross-resolve across languages when attributing an amendment.
    """

    en: dict[str, str]
    fr: dict[str, str]

    def lookup(self, title: str, lang: str) -> str | None:
        """Return the full norm_id for ``title`` in ``lang`` (``"en"``/``"fr"``).

        The returned value is already pipeline-ready — e.g.
        ``"eng/acts/I-3.3"`` or ``"fra/reglements/SOR-85-567"`` — and can be
        passed straight to ``client.get_text()``.
        """
        if not title:
            return None
        table = self.en if lang == "en" else self.fr
        articles = _LEADING_ARTICLES_EN if lang == "en" else _LEADING_ARTICLES_FR
        tails = _TRAILING_STRIPS_EN if lang == "en" else _TRAILING_STRIPS_FR

        key = _normalize(title)
        if key in table:
            return table[key]

        stripped = _strip_leading_article(key, articles)
        if stripped != key and stripped in table:
            return table[stripped]

        no_tail = _strip_trailing(key, tails)
        if no_tail != key and no_tail in table:
            return table[no_tail]

        combined = _strip_trailing(stripped, tails)
        if combined != stripped and combined in table:
            return table[combined]

        return None

    def to_json(self) -> str:
        return json.dumps({"en": self.en, "fr": self.fr}, sort_keys=True)

    @classmethod
    def from_json(cls, data: str) -> TitleIndex:
        payload = json.loads(data)
        return cls(en=dict(payload.get("en", {})), fr=dict(payload.get("fr", {})))


# ─────────────────────────────────────────────
# Builder
# ─────────────────────────────────────────────

_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("eng/acts", "en"),
    ("eng/regulations", "en"),
    ("fra/lois", "fr"),
    ("fra/reglements", "fr"),
)


def _titles_for(root: etree._Element) -> Iterable[str]:
    """Yield every title variant worth indexing for one XML root.

    Includes ShortTitle, RunningHead, and LongTitle — any of these can appear
    verbatim in an amending bill's text. Omitting RunningHead would miss
    cases like "Income Tax" (RunningHead) for bills that drop the trailing
    "Act"; the fallback logic covers that too but indexing the RH directly
    is cheap and more robust.
    """
    for xpath in ("Identification/ShortTitle", "Identification/RunningHead"):
        text = root.findtext(xpath, default="")
        if text:
            yield text.strip()
    # LongTitle tends to start with "An Act to…" which is noisy — index it
    # only if nothing else yields a key, to avoid cluttering the map.
    short = root.findtext("Identification/ShortTitle", default="").strip()
    if not short:
        long_title = root.findtext("Identification/LongTitle", default="").strip()
        if long_title:
            yield long_title


def _norm_id_for(subpath: str, stem: str, root: etree._Element) -> str | None:
    """Derive the full pipeline norm_id from a consolidated file.

    Returns the directory-qualified ID (``eng/acts/I-3.3``,
    ``fra/reglements/SOR-85-567``) that the pipeline uses throughout — the
    same shape ``get_text``/``get_suvestine`` accept. Callers can pass this
    directly to the client without further transformation.
    """
    consolidated = root.findtext("Identification/Chapter/ConsolidatedNumber", default="").strip()
    if consolidated:
        return f"{subpath}/{consolidated}"
    instrument = root.findtext("Identification/InstrumentNumber", default="").strip()
    if instrument:
        return f"{subpath}/{instrument.replace('/', '-')}"
    # Final fallback: filename stem (already sanitized on disk).
    return f"{subpath}/{stem}"


def build_title_index(xml_dir: Path) -> TitleIndex:
    """Walk the upstream clone and build a fresh in-memory index.

    Duplicates across files are tolerated by keeping the first mapping seen;
    in practice ShortTitle collisions are rare because Parliament avoids
    naming two acts identically.
    """
    if not xml_dir.exists():
        raise FileNotFoundError(f"upstream clone not found at {xml_dir}")

    en: dict[str, str] = {}
    fr: dict[str, str] = {}
    collisions = 0

    for subpath, lang in _CATEGORIES:
        cat_dir = xml_dir / subpath
        if not cat_dir.is_dir():
            logger.debug("Skipping missing category %s", cat_dir)
            continue
        for xml_path in sorted(cat_dir.glob("*.xml")):
            try:
                tree = etree.parse(str(xml_path))
            except etree.XMLSyntaxError as exc:
                logger.warning("Skipping unparseable %s: %s", xml_path, exc)
                continue
            root = tree.getroot()
            stem = xml_path.stem
            norm_id = _norm_id_for(subpath, stem, root)
            if not norm_id:
                continue
            target = en if lang == "en" else fr
            for title in _titles_for(root):
                key = _normalize(title)
                if not key:
                    continue
                existing = target.get(key)
                if existing and existing != norm_id:
                    collisions += 1
                    logger.debug(
                        "title collision in %s: %r maps to %s and %s — keeping first",
                        lang,
                        key,
                        existing,
                        norm_id,
                    )
                    continue
                target.setdefault(key, norm_id)

    if collisions:
        logger.info("Title index built with %d collisions (first-seen wins)", collisions)
    logger.info("Title index: %d EN entries, %d FR entries", len(en), len(fr))
    return TitleIndex(en=en, fr=fr)


def load_or_build_title_index(
    xml_dir: Path, data_dir: Path, *, force_rebuild: bool = False
) -> TitleIndex:
    """Load the cached index if present, otherwise build and cache it.

    The cache is invalidated manually by deleting ``title-index.json`` or by
    passing ``force_rebuild=True``. We don't auto-invalidate on upstream
    changes because the title set drifts slowly (Parliament enacts a handful
    of new acts per year).
    """
    cache_path = data_dir / INDEX_FILENAME
    if cache_path.exists() and not force_rebuild:
        try:
            return TitleIndex.from_json(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Title index cache invalid (%s); rebuilding", exc)

    index = build_title_index(xml_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(index.to_json(), encoding="utf-8")
    return index
