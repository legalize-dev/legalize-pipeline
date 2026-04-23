"""Cross-reference index: which annual-statute bills amended which consolidated acts.

The upstream clone's ``annual-statutes-lois-annuelles/`` subtree holds every
bill as-enacted from 2001 onward, one XML per chapter, parallel in English
and French. Each bill's title tells us what it does:

    "An Act to amend the Income Tax Act (…)"   → amends Income Tax Act
    "Canada–United States–Mexico Agreement
     Implementation Act"                       → creates a new act (itself)

We scan every bill once, classify it, and resolve the target act's title
against the :class:`TitleIndex` to produce a reverse map::

    { "eng/acts/I-3.3": [AmendmentRef(year=2020, chapter=13, …), …],
      "fra/lois/I-3.3": [AmendmentRef(year=2020, chapter=13, …), …],
      … }

This index is consumed by :meth:`JusticeCanadaClient.get_suvestine` — for
every norm we look up its accumulated amendment list and merge those bill
XMLs into the suvestine blob alongside the upstream git-log versions.

**Primary attribution only for v1.** Omnibus bills (budget
implementations, trade agreement packages) amend dozens of acts through
embedded ``<XRefExternal>`` citations, but the citations in Summary /
Recommendation sections conflate "mentioned" with "amended" and we'd risk
false attributions. The title-based primary attribution captures ~95% of
amendment intent and is unambiguous. Secondary-act detection can come later
by walking the bill ``<Body>`` looking for "The X Act is amended by"
section headers.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from lxml import etree

from legalize.fetcher.ca.title_index import TitleIndex

logger = logging.getLogger(__name__)


ANNUAL_STATUTES_DIR = "annual-statutes-lois-annuelles"
INDEX_FILENAME = "annual-statute-index.json"

# Matches "An Act to amend [the] X", capturing X. Non-greedy, case-insensitive,
# tolerant of the Oxford-comma-free English legal drafting style.
# We deliberately require the "to amend" token — bills that "implement",
# "enact", "give effect to", etc. create new content rather than amending
# an existing act, so we route them to the self-title branch.
_AMEND_TITLE_RE = re.compile(r"^an act to amend\s+(?:the\s+)?(.+?)\s*$", re.IGNORECASE)

# French equivalent: "Loi modifiant [la] X" or "Loi modifiant X".
_MODIFIE_TITLE_RE = re.compile(
    r"^loi\s+modifiant\s+(?:la\s+|le\s+|les\s+|l['’]\s*)?(.+?)\s*$",
    re.IGNORECASE,
)

# Trailing omnibus suffixes we drop before resolving a primary act.
# "… and to make consequential amendments to other Acts" is a stock phrase
# appended to bills that amend more than one law; it doesn't name another
# act, it just telegraphs "more amendments follow in the body".
_OMNIBUS_SUFFIXES_EN = (
    re.compile(
        r",?\s+and\s+to\s+(?:make\s+(?:related|consequential)\s+"
        r"amendments\s+to\s+other\s+acts|amend\s+other\s+acts.*)$",
        re.IGNORECASE,
    ),
    re.compile(r",?\s+and\s+other\s+acts\b.*$", re.IGNORECASE),
    re.compile(r",?\s+and\s+certain\s+other\s+acts\b.*$", re.IGNORECASE),
    re.compile(
        r",?\s+(?:in\s+respect\s+of|with\s+respect\s+to|to\s+provide\s+for).*$",
        re.IGNORECASE,
    ),
)
_OMNIBUS_SUFFIXES_FR = (
    re.compile(
        r",?\s+(?:et\s+d['’]\s*autres?\s+lois|et\s+modifiant\s+d['’]\s*autres?\s+lois"
        r"|apportant\s+des\s+modifications\s+corrélatives).*$",
        re.IGNORECASE,
    ),
    re.compile(r",?\s+et\s+certaines?\s+autres?\s+lois\b.*$", re.IGNORECASE),
)

# Joiners that split a captured target into primary + secondary acts.
# "A and the B" → primary "A", secondary "B". We keep only the primary for
# v1 attribution.
_PRIMARY_JOIN_RE_EN = re.compile(r"\s+and\s+(?:the\s+|to\s+).*$", re.IGNORECASE)
_PRIMARY_JOIN_RE_FR = re.compile(r"\s+et\s+(?:la\s+|le\s+|les\s+|à\s+).*$", re.IGNORECASE)

# Secondary joiner: ", the X" (used in long lists of amended acts).
_LIST_CONT_RE_EN = re.compile(r",\s+the\s+.*$", re.IGNORECASE)
_LIST_CONT_RE_FR = re.compile(r",\s+(?:la|le|les)\s+.*$", re.IGNORECASE)

# Non-act sentinels we see captured from stock drafting phrases. When the
# classifier returns one of these we skip the bill rather than attempt a
# futile lookup.
_NON_ACT_TARGETS = frozenset(
    {
        "certain acts",
        "certain acts of canada",
        "other acts",
        "statute law",
        "other instruments",
        "certain acts and instruments",
        "certaines lois",
        "autres lois",
        "certaines dispositions législatives",
    }
)


@dataclass(frozen=True)
class AmendmentRef:
    """One bill's contribution to the timeline of a consolidated act."""

    year: int
    chapter: int
    assent_date: str  # ISO YYYY-MM-DD — str for JSON round-tripping
    xml_path: str  # relative to the upstream clone root
    bill_number: str  # e.g. "C-9" (empty if unparseable)
    amending_title: str  # bill's own ShortTitle/LongTitle (for commit subjects)

    def as_date(self) -> date:
        return date.fromisoformat(self.assent_date)


@dataclass
class AnnualStatuteIndex:
    """Map of full norm_id → sorted list of amendment refs affecting it."""

    by_norm: dict[str, list[AmendmentRef]] = field(default_factory=dict)
    unresolved_titles: list[tuple[int, int, str]] = field(default_factory=list)

    def refs_for(self, norm_id: str) -> list[AmendmentRef]:
        return list(self.by_norm.get(norm_id, ()))

    def to_json(self) -> str:
        return json.dumps(
            {
                "by_norm": {k: [asdict(r) for r in v] for k, v in sorted(self.by_norm.items())},
                "unresolved_titles": list(self.unresolved_titles),
            },
            sort_keys=True,
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, data: str) -> AnnualStatuteIndex:
        payload = json.loads(data)
        by_norm: dict[str, list[AmendmentRef]] = {}
        for k, v in payload.get("by_norm", {}).items():
            by_norm[k] = [AmendmentRef(**r) for r in v]
        unresolved = [tuple(t) for t in payload.get("unresolved_titles", [])]
        return cls(by_norm=by_norm, unresolved_titles=unresolved)


# ─────────────────────────────────────────────
# Classification
# ─────────────────────────────────────────────


def _extract_assent_date(root: etree._Element) -> date | None:
    """Return the bill's assent date from ``BillHistory/Stages[assented-to]/Date``."""
    for stages in root.findall(".//BillHistory/Stages"):
        if stages.get("stage") != "assented-to":
            continue
        date_el = stages.find("./Date")
        if date_el is None:
            continue
        try:
            y = int(date_el.findtext("YYYY", "").strip())
            m = int(date_el.findtext("MM", "").strip())
            d = int(date_el.findtext("DD", "").strip())
            return date(y, m, d)
        except (TypeError, ValueError):
            continue
    return None


def _extract_chapter_info(root: etree._Element) -> tuple[int, int] | None:
    """Return ``(year, chapter)`` from ``Chapter/AnnualStatuteId``."""
    asid = root.find(".//Chapter/AnnualStatuteId")
    if asid is None:
        return None
    try:
        year = int(asid.findtext("YYYY", "").strip())
        chapter = int(asid.findtext("AnnualStatuteNumber", "").strip())
        return year, chapter
    except (TypeError, ValueError):
        return None


def _bill_titles(root: etree._Element) -> tuple[str, str, str]:
    """Return ``(short_title, long_title, bill_number)`` stripped.

    Amendment bills frequently carry ``ShortTitle status="unofficial"`` that
    mirrors LongTitle verbatim. Either way, the "An Act to amend…" pattern
    lives in one of them; we return both so the classifier can try the
    short form first and fall back to long.
    """
    short = (root.findtext(".//Identification/ShortTitle", "") or "").strip()
    long_t = (root.findtext(".//Identification/LongTitle", "") or "").strip()
    bill = (root.findtext(".//Identification/BillNumber", "") or "").strip()
    return short, long_t, bill


def _normalize_for_skip(title: str) -> str:
    """Lowercase + collapse whitespace + strip punctuation for the skip set."""
    t = re.sub(r"[^\w\s]+", " ", title.lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


def _reduce_to_primary(captured: str, lang: str) -> str:
    """Strip omnibus suffixes and list continuations to isolate one act name.

    Canadian legal drafting stacks targets with "and the X Act, the Y Act,
    the Z Act and to amend other Acts in consequence". For primary
    attribution we want just the first act in that stack.
    """
    text = captured.strip()
    omni = _OMNIBUS_SUFFIXES_EN if lang == "en" else _OMNIBUS_SUFFIXES_FR
    join_re = _PRIMARY_JOIN_RE_EN if lang == "en" else _PRIMARY_JOIN_RE_FR
    list_re = _LIST_CONT_RE_EN if lang == "en" else _LIST_CONT_RE_FR

    # 1. Kill trailing omnibus phrases first — they can look like act names
    #    ("... and to amend other Acts") but aren't.
    for pattern in omni:
        text = pattern.sub("", text).strip()

    # 2. Cut at the first " and the " / " et la " joiner — everything after
    #    is a secondary target.
    text = join_re.sub("", text).strip()

    # 3. Cut at ", the X" list continuation. This MUST run after the join
    #    step because "Budget Implementation Act, 1997" contains a comma
    #    that's part of the act name and "A, the B" joins a new item.
    text = list_re.sub("", text).strip()

    return text


def _classify_primary_target(short: str, long_t: str, lang: str) -> tuple[str, str]:
    """Return ``(target_title, classification)`` for the bill.

    ``classification`` is one of:
        ``"amends"``  — bill amends an existing act; ``target_title`` is that act.
        ``"creates"`` — bill creates a new act named ``target_title`` (the
                        short/long title itself).

    The distinction matters only for logging; downstream consumers treat
    both cases identically (resolve ``target_title`` through TitleIndex).
    """
    amend_re = _AMEND_TITLE_RE if lang == "en" else _MODIFIE_TITLE_RE

    # Prefer LongTitle for amendment parsing — ShortTitle is sometimes a
    # short-form that loses the "to amend the X Act" anchor.
    for candidate in (long_t, short):
        if not candidate:
            continue
        # Some LongTitles end with a parenthetical theme like "(Canada
        # Emergency Rent Subsidy…)" — strip terminal parens before matching
        # so the Act name isn't polluted. Mid-string parens stay (some
        # official titles embed them: "Proceeds of Crime (Money Laundering)").
        trimmed = re.sub(r"\s*\([^)]*\)\s*$", "", candidate).strip()
        m = amend_re.match(trimmed)
        if m:
            return _reduce_to_primary(m.group(1), lang), "amends"

    # Creation path: the ShortTitle IS the new act's name.
    if short:
        return short, "creates"
    if long_t:
        return long_t, "creates"
    return "", "unknown"


# ─────────────────────────────────────────────
# Builder
# ─────────────────────────────────────────────


def _iter_bill_files(statutes_dir: Path, lang: str) -> list[Path]:
    """Return all bill XML files for one language, sorted by (year, chapter)."""
    subdir = statutes_dir / lang
    if not subdir.is_dir():
        return []
    out: list[Path] = []
    for year_dir in sorted(subdir.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        out.extend(sorted(year_dir.glob("*.xml")))
    return out


def build_annual_statute_index(xml_dir: Path, title_index: TitleIndex) -> AnnualStatuteIndex:
    """Scan every annual-statute bill and resolve its primary target.

    Parameters
    ----------
    xml_dir:
        Root of the upstream ``justicecanada/laws-lois-xml`` clone.
    title_index:
        Pre-built :class:`TitleIndex` used to resolve bill titles to norm_ids.
    """
    statutes_dir = xml_dir / ANNUAL_STATUTES_DIR
    if not statutes_dir.is_dir():
        raise FileNotFoundError(f"annual-statutes dir not found at {statutes_dir}")

    result = AnnualStatuteIndex()

    for lang, lang_short in (("en", "en"), ("fr", "fr")):
        for xml_path in _iter_bill_files(statutes_dir, lang):
            rel_path = str(xml_path.relative_to(xml_dir))
            try:
                tree = etree.parse(str(xml_path))
            except etree.XMLSyntaxError as exc:
                logger.warning("Skipping unparseable bill %s: %s", rel_path, exc)
                continue
            root = tree.getroot()

            chapter_info = _extract_chapter_info(root)
            if chapter_info is None:
                logger.debug("No chapter info in %s — skipping", rel_path)
                continue
            year, chapter = chapter_info

            assent = _extract_assent_date(root)
            if assent is None:
                # Fall back to the year with Jan 1 — some older bills omit
                # the stage date. This is rare enough that a rough date
                # beats dropping the amendment entirely.
                assent = date(year, 1, 1)

            short, long_t, bill_number = _bill_titles(root)
            target_title, classification = _classify_primary_target(short, long_t, lang_short)
            if not target_title:
                logger.debug("Unclassifiable bill %s — skipping", rel_path)
                continue

            # Stock drafting non-acts ("certain Acts", "other Acts") are a
            # dead-end for lookup — record once, move on.
            if _normalize_for_skip(target_title) in _NON_ACT_TARGETS:
                logger.debug("Skipping stock-phrase target %r in %s", target_title, rel_path)
                continue

            norm_id = title_index.lookup(target_title, lang_short)
            if norm_id is None:
                # Retry after stripping a terminal parenthetical theme.
                # "Criminal Code (organized crime and law enforcement)" →
                # "Criminal Code" which resolves to C-46.
                stripped = re.sub(r"\s*\([^)]*\)\s*$", "", target_title).strip()
                if stripped and stripped != target_title:
                    norm_id = title_index.lookup(stripped, lang_short)

            if norm_id is None:
                result.unresolved_titles.append((year, chapter, target_title))
                logger.debug(
                    "Could not resolve %s bill %d-c%d target title %r (%s)",
                    lang_short,
                    year,
                    chapter,
                    target_title,
                    classification,
                )
                continue

            ref = AmendmentRef(
                year=year,
                chapter=chapter,
                assent_date=assent.isoformat(),
                xml_path=rel_path,
                bill_number=bill_number,
                amending_title=short or long_t,
            )
            result.by_norm.setdefault(norm_id, []).append(ref)

    # Sort each norm's timeline chronologically.
    for refs in result.by_norm.values():
        refs.sort(key=lambda r: (r.assent_date, r.year, r.chapter))

    logger.info(
        "Annual-statute index: %d norms with amendments, %d unresolved titles",
        len(result.by_norm),
        len(result.unresolved_titles),
    )
    return result


def load_or_build_annual_statute_index(
    xml_dir: Path,
    title_index: TitleIndex,
    data_dir: Path,
    *,
    force_rebuild: bool = False,
) -> AnnualStatuteIndex:
    """Load the cached index or rebuild. Mirrors TitleIndex's cache pattern."""
    cache_path = data_dir / INDEX_FILENAME
    if cache_path.exists() and not force_rebuild:
        try:
            return AnnualStatuteIndex.from_json(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("Annual-statute index cache invalid (%s); rebuilding", exc)

    index = build_annual_statute_index(xml_dir, title_index)
    data_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(index.to_json(), encoding="utf-8")
    return index
