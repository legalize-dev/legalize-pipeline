"""Reform reconstruction for Argentine legislation.

InfoLEG only serves the **current** consolidated text of each norm. To provide
real per-date versions in the git history (Argentina's headline feature), we
reconstruct each historical version by parsing the modificatorias' own texts
and applying their changes in chronological order.

The Argentine legal-drafting style is highly templated:

- ``Art. N.- Sustitúyese el artículo X de la Ley 19.550 por el siguiente: <new text>``
- ``Art. N.- Derógase el artículo X de la Ley 19.550``
- ``Art. N.- Incorpórase como artículo X bis de la Ley 19.550: <new text>``
- ``ARTICULO 1º – Sustitúyense los artículos X; Y; Z de la Ley N° 19.550 por los siguientes: "Artículo X– ..." "Artículo Y– ..."``

This module extracts those instructions from a modificatoria's HTML and
returns a list of :class:`Modification` records. The pipeline applies them
sequentially to reconstruct each version.

POC validated 2026-04-11 against Ley 19.550 (Sociedades) using Ley 27.444
(2018) as the modificatoria — 4 article substitutions extracted and matched
literally against the consolidated texact.htm.

See RESEARCH-AR.md §6 for the complete reconstruction algorithm.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from legalize.fetcher._text import strip_control

logger = logging.getLogger(__name__)


# Decode all InfoLEG HTML as cp1252 regardless of declared charset.
# Mixed ISO-8859-1 / windows-1252 declarations in the wild — see RESEARCH-AR.md §5.
INFOLEG_ENCODING = "cp1252"


def decode_infoleg(data: bytes) -> str:
    """Decode raw InfoLEG bytes as cp1252 with control-char stripping."""
    text = data.decode(INFOLEG_ENCODING, errors="replace")
    text = strip_control(text)
    return text


def html_to_plain(html: str) -> str:
    """Strip HTML tags and normalize whitespace, preserving paragraph breaks.

    Used as preprocessing for the reform extractor — we work on plain text
    because the InfoLEG HTML is too sloppy to rely on tag structure.
    """
    # Drop scripts and styles entirely
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    # Replace block-level breaks with newlines so we keep paragraph boundaries
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</p\s*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</div\s*>", "\n", html, flags=re.IGNORECASE)
    # Strip remaining tags
    html = re.sub(r"<[^>]+>", "", html)
    # HTML entities
    from html import unescape

    html = unescape(html)
    # Collapse runs of horizontal whitespace inside lines, keep newlines
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n[ \t]+", "\n", html)
    html = re.sub(r"[ \t]+\n", "\n", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


# ── Modification model ──


class ModificationKind(str, Enum):
    """Kind of change a modificatoria applies to a target norm."""

    SUBSTITUTE = "substitute"  # Sustitúyese el artículo X por: ...
    REPEAL = "repeal"  # Derógase el artículo X
    INSERT = "insert"  # Incorpórase como artículo X bis: ...
    AMOUNT_UPDATE = "amount_update"  # Resolución que actualiza monto (no diff)
    UNKNOWN = "unknown"  # Pattern matched but parser couldn't extract


@dataclass(frozen=True)
class Modification:
    """One concrete change to a target norm.

    A modificatoria typically contains multiple :class:`Modification` records
    (one per article it modifies on the target norm).
    """

    target_norm_number: str  # e.g. "19550" — number of the norm being modified
    kind: ModificationKind
    article_id: str  # e.g. "8", "8 bis", "34", "299/2"
    new_text: str  # plain text of the replacement / insertion (empty for repeal)
    source_article: str  # the article number IN the modificatoria that performs the change
    raw_excerpt: str  # short excerpt of the source for debugging


# ── Number normalization ──


def _normalize_number(s: str) -> str:
    """Strip dots, spaces, NBSP and the 'nro/Nº' prefix from a law number."""
    s = s.replace("\xa0", "").replace(" ", "").replace(".", "")
    s = re.sub(r"^[Nn][°ºoO]?", "", s)
    return s


# Pattern: "de la Ley (General de Sociedades)? (Nº)? 19.550"
# We anchor on either "Ley" or "ley" plus a number, possibly with descriptor.
_LAW_REF_RE = re.compile(
    r"(?:Ley|ley)(?:\s+General\s+de\s+Sociedades)?(?:\s+(?:N\s*[°ºoO]\.?|Nro\.?))?\s*"
    r"(\d{1,3}(?:\.\d{3})*)",
)


def _ref_targets_norm(reference: str, target_norm_number: str) -> bool:
    """Check whether a 'de la Ley X' fragment refers to ``target_norm_number``."""
    target = _normalize_number(target_norm_number)
    for m in _LAW_REF_RE.finditer(reference):
        if _normalize_number(m.group(1)) == target:
            return True
    return False


# ── Extractors ──

# Match a single substitution within a modificatoria's article block:
# "Sustitúyese el artículo X (de la Ley Y)? por el siguiente: <new text>"
_SUBSTITUTE_SINGLE_RE = re.compile(
    r"Sustit[úu]yese\s+el\s+art[íi]culo\s+(?P<art>\d+\s*(?:bis|ter|quáter|quater)?)"
    r"\s*[°º]?(?P<between>[^:]{0,400}?)"
    r"(?:por\s+el\s+siguiente|por\s+el\s+texto\s+siguiente|el\s+que\s+quedar[áa]\s+redactado[^:]{0,80})"
    r"\s*[:\.]\s*(?P<body>.+?)"
    r"(?=\bArt\.?\s*\d+[\.°º]?\s*[\-–]|\bARTICULO\s+\d+|\Z)",
    re.IGNORECASE | re.DOTALL,
)

# Plural substitution: "Sustitúyense los artículos X; Y; Z ... de la Ley N° 19.550 por los siguientes:"
# followed by one or more `"Artículo X– ..."` quoted blocks.
_SUBSTITUTE_PLURAL_HEADER_RE = re.compile(
    r"Sustit[úu]yense\s+los\s+art[íi]culos\s+(?P<list>[\d;\sy\.,°º]+?)"
    r"\s+de\s+la\s+(?P<ref>Ley[^,]{0,200})"
    r"[^:]*?por\s+los\s+siguientes\s*[:\.]",
    re.IGNORECASE | re.DOTALL,
)

# Inside a plural body, individual articles are quoted:
# "Artículo 11– <text>"  (the dash can be em dash, en dash, or hyphen)
_QUOTED_ARTICLE_RE = re.compile(
    r'["“]?\s*Art[íi]culo\s+(?P<num>\d+(?:\s*bis|\s*ter)?)\s*[°º]?'
    r"\s*[\-–—\.]\s*(?P<body>.+?)"
    r'(?=["“]?\s*Art[íi]culo\s+\d+\s*[°º]?\s*[\-–—\.]|\Z)',
    re.IGNORECASE | re.DOTALL,
)

_REPEAL_SINGLE_RE = re.compile(
    r"Der[óo]gase\s+el\s+art[íi]culo\s+(?P<art>\d+(?:\s*bis|\s*ter)?)"
    r"\s*[°º]?(?P<between>[^.]{0,300})\.",
    re.IGNORECASE,
)

_INSERT_RE = re.compile(
    r"Incorp[óo]rase\s+como\s+art[íi]culo\s+(?P<art>\d+(?:\s*bis|\s*ter|\s*quáter)?)"
    r"\s*[°º]?(?P<between>[^:]{0,300}?)\s*(?:el\s+siguiente|lo\s+siguiente)?\s*[:\.]"
    r"\s*(?P<body>.+?)"
    r"(?=\bArt\.?\s*\d+[\.°º]?\s*[\-–]|\bARTICULO\s+\d+|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def _split_modificatoria_blocks(plain: str) -> list[str]:
    """Split a modificatoria's plain text into per-article blocks.

    Each block starts with ``Art. N.-`` or ``ARTICULO N.-`` and runs until
    the next such header (or end of document).
    """
    return re.split(r"(?=\bArt\.?\s*\d+[\.°º]?\s*[\-–])", plain)


def _strip_article_header(body: str) -> str:
    """Remove a leading "Artículo N°:" header from a substitution body.

    The new text usually starts with the article number again ("Artículo 8°:")
    which is decorative — the structural article number comes from the match
    group, not from the body. Strip it for cleaner storage.
    """
    return re.sub(
        r"^\s*[\"“]?\s*Art[íi]culo\s+\d+(?:\s*bis|\s*ter)?\s*[°º]?\s*[:\.\-–—]\s*",
        "",
        body,
        count=1,
        flags=re.IGNORECASE,
    )


def _trim_body(body: str, max_chars: int = 20000) -> str:
    """Trim a substitution body at the next double newline or at max_chars.

    Modification bodies are bounded by the next ``Art. N.-`` header but
    sometimes the regex over-captures into the following article. We crop
    at the first ``\\n\\n`` to be safe, and clip to a hard maximum.
    """
    # Find the first double newline that is followed by content that
    # looks like a closing reference, signature, or date marker.
    body = body.strip()
    if len(body) > max_chars:
        body = body[:max_chars] + " […]"
    return body


def extract_modifications(modificatoria_html: bytes, target_norm_number: str) -> list[Modification]:
    """Extract every modification a modificatoria applies to a target norm.

    Args:
        modificatoria_html: raw bytes of the modificatoria's ``norma.htm``.
        target_norm_number: the unstripped numero_norma of the law being
            modified, e.g. "19550" or "19.550".

    Returns:
        List of :class:`Modification` records. Empty if the modificatoria
        does not target the requested norm or if no patterns matched.
    """
    text = decode_infoleg(modificatoria_html)
    plain = html_to_plain(text)
    target = _normalize_number(target_norm_number)

    mods: list[Modification] = []

    blocks = _split_modificatoria_blocks(plain)
    for block in blocks:
        if not block.strip():
            continue

        source_art_match = re.match(r"\bArt\.?\s*(\d+)[\.°º]?\s*[\-–]", block)
        source_art = source_art_match.group(1) if source_art_match else ""

        # Single substitution
        for m in _SUBSTITUTE_SINGLE_RE.finditer(block):
            between = m.group("between") or ""
            if not _ref_targets_norm(between, target):
                continue
            body = _strip_article_header(m.group("body"))
            mods.append(
                Modification(
                    target_norm_number=target,
                    kind=ModificationKind.SUBSTITUTE,
                    article_id=m.group("art").strip().replace(" ", " "),
                    new_text=_trim_body(body),
                    source_article=source_art,
                    raw_excerpt=block[:300].strip(),
                )
            )

        # Single insertion
        for m in _INSERT_RE.finditer(block):
            between = m.group("between") or ""
            if not _ref_targets_norm(between, target):
                continue
            body = _strip_article_header(m.group("body"))
            mods.append(
                Modification(
                    target_norm_number=target,
                    kind=ModificationKind.INSERT,
                    article_id=m.group("art").strip(),
                    new_text=_trim_body(body),
                    source_article=source_art,
                    raw_excerpt=block[:300].strip(),
                )
            )

        # Single repeal
        for m in _REPEAL_SINGLE_RE.finditer(block):
            between = m.group("between") or ""
            if not _ref_targets_norm(between, target):
                continue
            mods.append(
                Modification(
                    target_norm_number=target,
                    kind=ModificationKind.REPEAL,
                    article_id=m.group("art").strip(),
                    new_text="",
                    source_article=source_art,
                    raw_excerpt=block[:300].strip(),
                )
            )

        # Plural substitution
        for h in _SUBSTITUTE_PLURAL_HEADER_RE.finditer(block):
            ref = h.group("ref") or ""
            if not _ref_targets_norm(ref, target):
                continue
            article_list = h.group("list") or ""
            article_nums = re.findall(r"\d+(?:\s*bis|\s*ter)?", article_list)
            if not article_nums:
                continue

            # Body starts after the header match
            body_start = h.end()
            body = block[body_start:]

            quoted = list(_QUOTED_ARTICLE_RE.finditer(body))
            if not quoted:
                # We can detect a plural sustitución but cannot split it —
                # log as UNKNOWN so the pipeline can fall back to bootstrap.
                for art in article_nums:
                    mods.append(
                        Modification(
                            target_norm_number=target,
                            kind=ModificationKind.UNKNOWN,
                            article_id=art.strip(),
                            new_text="",
                            source_article=source_art,
                            raw_excerpt=block[:300].strip(),
                        )
                    )
                continue

            for q in quoted:
                num = q.group("num").strip()
                qbody = _trim_body(q.group("body"))
                mods.append(
                    Modification(
                        target_norm_number=target,
                        kind=ModificationKind.SUBSTITUTE,
                        article_id=num,
                        new_text=qbody,
                        source_article=source_art,
                        raw_excerpt=q.group(0)[:300].strip(),
                    )
                )

    return mods


__all__ = [
    "INFOLEG_ENCODING",
    "Modification",
    "ModificationKind",
    "decode_infoleg",
    "extract_modifications",
    "html_to_plain",
]
