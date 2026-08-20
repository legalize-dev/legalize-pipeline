"""PDF text extraction and cleanup for the Gaceta Oficial de la República de Cuba.

The Gaceta publishes each law as a born-digital PDF (or, for consolidated
book editions, a MINJUS typeset PDF). There is no XML, no HTML and no JSON
full-text — the PDF is the only authoritative source, exactly like Greece.

Two-stage pipeline (mirrors ``fetcher/gr``):

  1. ``extract_text_from_pdf`` — pymupdf (AGPL-3.0) per-page text layer
     extraction. Gaceta PDFs carry a reliable embedded text layer.

  2. ``convert_text`` — the cleanup + structural tagging layer, ported
     almost verbatim from the reference converter
     ``/tmp/legalize-cu/convert.py`` (the script that produced the existing
     53 ground-truth ``cu/*.md`` files). It slices the issue around the
     target document (``goc`` / ``start_regex`` / ``end_regex`` from the
     manifest), merges hyphenated line breaks, strips Gaceta masthead /
     running-head / ToC furniture, classifies article and section headings,
     and emits engine CSS classes instead of raw Markdown.

Extraction quirks handled here (verified across all 53 PDFs):

* **Soft hyphen (U+00AD)** — pymupdf emits ``disposicio\\xad`` + line break
  for mid-word split points (3,585 occurrences across 20 files). Stripped
  so the word reads cleanly.
* **ASCII-dash EOL** — real typeset hyphenation also appears as ``-`` at
  end of line (9,377 occurrences across 37 files). Joined with the next
  line unless the next line starts a new structural block.
* **Combined issues** — one Gaceta issue can contain several laws (e.g.
  No. 78 Extraordinaria de 2024 carries Decreto-Leyes 88-92; No. 133
  Ordinaria de 2022 carries Decreto-Leyes 66 and 67). Each PDF is sliced
  on its ``GOC-YYYY-NNNN-O{NN}`` code (``want_goc``) so every manifest
  entry yields exactly its own law.
* **Book editions** — Ley-109 and Decreto-Ley-304 use explicit
  ``start_regex``/``end_regex`` slices (their MINJUS PDFs bundle extra
  front matter or a following regulation).

The output of ``convert_text`` is a list of ``Paragraph`` objects with
engine CSS classes (``titulo_tit``, ``capitulo_tit``, ``seccion``,
``articulo``, ``parrafo``) so the generic ``transformer/markdown.py``
renderer produces the Markdown headings.

Algorithm credit: ``/tmp/legalize-cu/convert.py`` (the Legalize Cuba
reference converter) — ported with attribution into the pipeline.
"""

from __future__ import annotations

import base64
import gc
import hashlib
import json
import logging
import re
import warnings
from collections import OrderedDict
from pathlib import Path
from typing import Any

_SWIG_RUNTIME_NAMES = ("SwigPyPacked", "SwigPyObject", "swigvarlink")


def _patch_swig_runtime_types() -> None:
    """Set a real ``__module__`` on pymupdf's SWIG runtime heap types.

    pymupdf's ``_mupdf`` extension is SWIG-generated and built with
    Py_LIMITED_API, under which SWIG 4.3.1 emitted its runtime types
    (``SwigPyPacked``, ``SwigPyObject``, ``swigvarlink``) as heap types with no
    ``__module__`` attribute. CPython 3.14's ``PyType_FromSpec`` deprecates
    that, so ``import pymupdf`` warns once per process and the types misbehave
    under pickling/pydoc/repr. SWIG 4.4.0 fixed the generation
    (swig/swig#2881), but pymupdf's shipped wheels are still built with 4.3.1,
    so we repair the attribute here at import time.
    """
    for obj in gc.get_objects():
        if (
            isinstance(obj, type)
            and obj.__name__ in _SWIG_RUNTIME_NAMES
            and not hasattr(obj, "__module__")
        ):
            obj.__module__ = "pymupdf._mupdf"


with warnings.catch_warnings():
    # The DeprecationWarning fires from C inside the extension's import (via
    # PyType_FromSpec) before any of our code can run; contain the one-time
    # emission here and repair the root cause right after with the patch above.
    warnings.filterwarnings(
        "ignore",
        message=r"builtin type (?:SwigPyPacked|SwigPyObject|swigvarlink) has no __module__ attribute",
        category=DeprecationWarning,
    )
    import pymupdf

_patch_swig_runtime_types()

logger = logging.getLogger(__name__)

# Small LRU cache for the extraction+conversion result keyed on a SHA-1 of
# the PDF bytes. The pipeline calls parse_text and parse back-to-back on the
# same document and pytest reorders tests, so caching pays off. Cap at 8
# entries (≈ 8-32 MB of text) to keep long bootstraps bounded.
_EXTRACT_CACHE_SIZE = 8
_EXTRACT_CACHE: OrderedDict[str, list[Any]] = OrderedDict()


def _bytes_key(data: bytes) -> str:
    return hashlib.sha1(data, usedforsecurity=False).hexdigest()


def _cache_get(key: str) -> list[Any] | None:
    if key in _EXTRACT_CACHE:
        _EXTRACT_CACHE.move_to_end(key)
        return _EXTRACT_CACHE[key]
    return None


def _cache_put(key: str, value: list[Any]) -> None:
    _EXTRACT_CACHE[key] = value
    _EXTRACT_CACHE.move_to_end(key)
    while len(_EXTRACT_CACHE) > _EXTRACT_CACHE_SIZE:
        _EXTRACT_CACHE.popitem(last=False)


# ─────────────────────────────────────────────
# Constants (ported from /tmp/legalize-cu/convert.py)
# ─────────────────────────────────────────────

ARTICLE_RE = re.compile(
    r"^(ARTÍCULO|ARTICULO|Artículo|Articulo|Atículo|Aticulo)\s+(\d+)\s*[.\-]*\s*(.*)$",
    re.IGNORECASE,
)
SECTION_RE = re.compile(
    r"^(TÍTULO|TITULO|CAPÍTULO|CAPITULO|SECCIÓN|SECCION|LIBRO|PARTE|PREÁMBULO|PREAMBULO)"
    r"\b.*$"
)
DISPOSICION_RE = re.compile(
    r"^(DISPOSICIONES\s+(GENERALES|TRANSITORIAS|FINALES|ESPECIALES|ADICIONALES))\b.*$"
)

FURNITURE_RE = [
    re.compile(r"^GACETA\s+OFICIAL\b", re.IGNORECASE),
    re.compile(r"^DE LA REPÚBLICA DE CUBA\b", re.IGNORECASE),
    re.compile(r"^MINISTERIO DE JUSTICIA\b", re.IGNORECASE),
    re.compile(r"^ISSN\b"),
    re.compile(r"^EXTRAORDINARIA\b"),
    re.compile(r"^ORDINARIA\b"),
    re.compile(r"^EDICIÓN ESPECIAL\b", re.IGNORECASE),
    re.compile(r"^AÑO\s+\w+"),
    re.compile(r"^Sitio Web:? ", re.IGNORECASE),
    re.compile(r"^Teléfonos:? ", re.IGNORECASE),
    re.compile(r"^La Habana\b.*\d{4}", re.IGNORECASE),
    re.compile(r"^Número\s+\d+$", re.IGNORECASE),
    re.compile(r"^Página\s+\d+$", re.IGNORECASE),
    re.compile(r"^\d+$"),
    re.compile(r"^GOC-\d{4}-\d+-\w+$", re.IGNORECASE),
    re.compile(r"^GOC-\d{4}-(?:O|E)\d+$", re.IGNORECASE),
    re.compile(r"^\d{2}/\d{2}/\d{4}\s+GOC-\d{4}-", re.IGNORECASE),
    re.compile(r"^\d{2}/\d{2}/\d{4}$"),
    re.compile(r"^[A-ZÁÉÍÓÚÑÜ ]*SUMARIO[A-ZÁÉÍÓÚÑÜ ]*$", re.IGNORECASE),
    re.compile(r"^Información en este número$", re.IGNORECASE),
    re.compile(r"^\[Escriba texto\]$", re.IGNORECASE),
    re.compile(r"^ASAMBLEA NACIONAL DEL PODER POPULAR\s*$", re.IGNORECASE),
    re.compile(r"^\s*$"),
    # Gaceta masthead lines that pymupdf merges without spaces
    re.compile(r"^GACETA OFICIAL\w+.*ISSN\b", re.IGNORECASE),
    re.compile(r"^ISSN.*MINISTERIO DE JUSTICIA", re.IGNORECASE),
    re.compile(r"^\S*GACETA OFICIAL\S*", re.IGNORECASE),
    re.compile(r"^Número\s+\d+\s+Página", re.IGNORECASE),
    re.compile(r"^\d+\s+Página\b", re.IGNORECASE),
    re.compile(r"^Página\s+\d+\s+$", re.IGNORECASE),
    # Gaceta issue-date stamp printed as a running page header (page number +
    # "GACETA OFICIAL" + "10 de abril de 2021") — page furniture, not law text.
    re.compile(r"^\d{1,2} de \w+ de \d{4}$"),
]

# Running page headers inside a Gaceta issue (left/right header text).
RUNNING_HEAD_RE = re.compile(
    r"^(Gaceta Oficial\b|Gaceta Oficial de la República de Cuba\b|GOC\.|"
    r"ISSN \d+-\d+|Sitio Web:|Calle Zanja|Teléfonos:|Año \w+|"
    r"Gaceta Oficial Extraordinaria|Gaceta Oficial Ordinaria|"
    r"MINISTERIO DE JUSTICIA|LA HABANA,)",
    re.IGNORECASE,
)

BODY_START_RE = re.compile(r"^HAGO SABER|^POR CUANTO", re.IGNORECASE)
SIGNATURE_RE = re.compile(r"^DAD[OA] en ", re.IGNORECASE)
GOC_RE = re.compile(r"^GOC-\d{4}-\d+-(?:O|E)\d+\s*$", re.IGNORECASE)
DOC_BOUNDARY_RE = re.compile(
    r"^(LEY|DECRETO|DECRETO-LEY|RESOLUCIÓN|RESOLUCION|ACUERDO|INSTRUCCIÓN|INSTRUCCION)"
    r"\s+(No\.?\s*)?\d+(/|$)",
    re.IGNORECASE,
)

# Engine CSS classes for Gaceta structural headings. Convert.py emitted
# ``## <heading>`` for every structural line; we instead map each to the
# engine's heading vocabulary (matching Greece/Andorra/others):
#   LIBRO/PARTE/TÍTULO → titulo_tit (H2), CAPÍTULO → capitulo_tit (H3),
#   SECCIÓN/DISPOSICIONES/PREÁMBULO → seccion (H4), ARTÍCULO → articulo (H6).
_SECTION_CLASS: dict[str, str] = {
    "TÍTULO": "titulo_tit",
    "TITULO": "titulo_tit",
    "LIBRO": "titulo_tit",
    "PARTE": "titulo_tit",
    "CAPÍTULO": "capitulo_tit",
    "CAPITULO": "capitulo_tit",
    "SECCIÓN": "seccion",
    "SECCION": "seccion",
    "PREÁMBULO": "seccion",
    "PREAMBULO": "seccion",
}


def _section_css(heading: str) -> str:
    """Map a structural heading word (TÍTULO, CAPÍTULO, ...) to a CSS class."""
    for word, css in _SECTION_CLASS.items():
        if heading.startswith(word):
            return css
    return "seccion"


# ─────────────────────────────────────────────
# Line-level helpers
# ─────────────────────────────────────────────


# Ligature glyphs pymupdf emits from the MINJUS book-edition fonts (U+FB00..U+FB06).
# pymupdf inserts a space after the ligature glyph (its advance width reads as a
# word gap), so "superﬁ cie" must become "superficie", not keep the fragment split.
_LIGATURES = {
    "\ufb00": "ff",  # ﬀ
    "\ufb01": "fi",  # ﬁ
    "\ufb02": "fl",  # ﬂ
    "\ufb03": "ffi",  # ﬃ
    "\ufb04": "ffl",  # ﬄ
    "\ufb05": "ft",  # ﬅ
    "\ufb06": "st",  # ﬆ
}
# Letters that can continue a Spanish word fragment after a ligature split.
_LIG_FOLLOW = "[A-Za-zÁÉÍÓÚÑÜáéíóúñü]"


def _clean_line(line: str) -> str:
    """Strip soft hyphens, normalize ligatures and collapse whitespace."""
    line = line.replace("\xad", "")
    for lig, repl in _LIGATURES.items():
        # Merge the fragment: "superﬁ cie" -> "superficie" (drop the artifact
        # space) only when a letter continues the word; plain normalization
        # handles ligatures with no following space.
        line = re.sub(re.escape(lig) + r"\s+(?=" + _LIG_FOLLOW + r")", repl, line)
        line = line.replace(lig, repl)
    return re.sub(r"\s+", " ", line).strip()


def _is_furniture(line: str) -> bool:
    s = _clean_line(line)
    if not s:
        return True
    for rx in FURNITURE_RE:
        if rx.match(s):
            return True
    return False


def _is_running_head(line: str) -> bool:
    return bool(RUNNING_HEAD_RE.match(_clean_line(line)))


def _merge_hyphenated(raw: list[str]) -> list[str]:
    """Rejoin words split across a line break.

    Two split signals, distinguished by how the PDF text layer encodes them:

    * **Soft hyphen (U+00AD)** — the PDF content stream uses a real soft
      hyphen for word hyphenation, so pymupdf emits ``disposicio\\xad`` at
      end of line. This is an unambiguous word-split marker: strip it and
      rejoin with the next line **without** a separator (else the text reads
      ``disposicio nes``).
    * **Literal ``-``** — a plain ASCII hyphen at end of line. This may be
      typeset hyphenation *or* a genuine compound hyphen split across the
      break (e.g. ``hombre-animal-`` + ``medioambiente``), so we keep the
      hyphen, matching the historical ``/tmp/legalize-cu`` converter.

    The inner loop is chain-aware: two adjacent soft-hyphen splits
    (``...disposicio\\xad`` + ``nes...concien\\xad`` + ``tizar...``) must
    collapse into one unbroken word.
    """
    out: list[str] = []
    i = 0
    n = len(raw)
    while i < n:
        ln = raw[i]
        while True:
            r = ln.rstrip()
            is_soft_split = r.endswith("\xad")
            if not (is_soft_split or _clean_line(ln).endswith("-")):
                break
            if i + 1 >= n:
                break
            ns = _clean_line(raw[i + 1])
            if not ns or (
                ARTICLE_RE.match(ns)
                or SECTION_RE.match(ns)
                or DISPOSICION_RE.match(ns)
                or _is_furniture(ns)
                or _is_running_head(ns)
            ):
                break
            if is_soft_split:
                ln = r[:-1] + raw[i + 1].lstrip()
            else:
                ln = ln.rstrip() + raw[i + 1]
            i += 1
        out.append(ln)
        i += 1
    return out


def _find_doc_starts(text: str) -> list[tuple[str | None, int]]:
    """Return ``[(goc_code or None, line_idx)]`` for each document in an issue.

    A document is recognized by its enacting clause line (``HAGO SABER``) or,
    for older texts lacking it, a leading ``POR CUANTO``. The GOC-XXXX code on
    the line immediately before the enacting clause identifies the document and
    lets us slice secondary documents out of combined issues.
    """
    raw = text.split("\n")
    starts: list[tuple[str | None, int]] = []
    last_goc: str | None = None
    for i, ln in enumerate(raw):
        s = _clean_line(ln)
        if GOC_RE.match(s):
            last_goc = s
            continue
        if re.match(r"^HAGO SABER\b", s, re.IGNORECASE) or (
            re.match(r"^POR CUANTO\b", s, re.IGNORECASE) and not (starts and last_goc is not None)
        ):
            starts.append((last_goc, i))
            last_goc = None
    return starts


def _slice_document(
    text: str,
    want_goc: str | None = None,
    start_index: int = 0,
    start_regex: str | None = None,
    end_regex: str | None = None,
) -> str:
    """Cut ToC/masthead before the body and truncate at the next document."""
    raw = text.split("\n")

    if start_regex:
        rx = re.compile(start_regex, re.IGNORECASE)
        start = next((i for i, ln in enumerate(raw) if rx.match(_clean_line(ln))), 0)
    else:
        starts = _find_doc_starts(text)
        if not starts:
            return ""
        if want_goc:
            sel = next((s for s in starts if s[0] == want_goc), starts[start_index])
        else:
            sel = starts[start_index]
        start = sel[1]

    if end_regex:
        erx = re.compile(end_regex, re.IGNORECASE)
        for i in range(start + 1, len(raw)):
            if erx.match(_clean_line(raw[i])):
                end = i
                break
        else:
            end = len(raw)
    else:
        end = len(raw)
        signed = False
        for i in range(start, len(raw)):
            line = raw[i].strip()
            if SIGNATURE_RE.match(line):
                signed = True
                continue
            if signed and (GOC_RE.match(line) or DOC_BOUNDARY_RE.match(line)):
                end = i
                break
            if i > start and line.startswith("HAGO SABER"):
                end = i
                break
    return "\n".join(raw[start:end])


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────


def extract_text_from_pdf(pdf_path: str | Path | bytes) -> str:
    """Return the raw text layer of a Gaceta PDF as one string.

    Accepts a path or raw bytes. pymupdf is called with ``get_text("text")``
    exactly like the reference converter, so extraction fidelity matches the
    existing ``/tmp/legalize-cu`` outputs.
    """
    if isinstance(pdf_path, bytes):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_path)
        try:
            return _extract_text_uncached(Path(tmp.name))
        finally:
            try:
                Path(tmp.name).unlink()
            except OSError:
                pass

    return _extract_text_uncached(Path(pdf_path))


def _extract_text_uncached(path: Path) -> str:
    doc = pymupdf.open(path)
    try:
        parts = []
        for page in doc:
            parts.append(page.get_text("text"))
        return "\n".join(parts)
    finally:
        doc.close()


def convert_text(
    pdf_path: str | Path | bytes,
    *,
    goc: str | None = None,
    start_index: int = 0,
    start_regex: str | None = None,
    end_regex: str | None = None,
) -> list[Any]:
    """Extract + clean a Gaceta PDF and tag it with engine CSS classes.

    Returns a list of ``Paragraph`` objects (imported lazily from
    ``legalize.models`` to avoid a circular import at module load). The
    result is cached per PDF byte fingerprint so back-to-back parse calls
    only do the heavy extraction once.

    ``goc`` / ``start_index`` / ``start_regex`` / ``end_regex`` come from
    the manifest entry for the law and control document slicing inside a
    combined issue.
    """
    if isinstance(pdf_path, bytes):
        key = _bytes_key(pdf_path)
        cached = _cache_get(key)
        if cached is not None:
            return cached

    from legalize.models import Paragraph

    if isinstance(pdf_path, bytes):
        text = extract_text_from_pdf(pdf_path)
    else:
        text = extract_text_from_pdf(Path(pdf_path))

    raw = _slice_document(
        text, want_goc=goc, start_index=start_index, start_regex=start_regex, end_regex=end_regex
    ).split("\n")
    raw = _merge_hyphenated(raw)

    lines: list[str] = []
    for ln in raw:
        s = _clean_line(ln)
        if s and (_is_furniture(s) or _is_running_head(s)):
            continue
        lines.append(s)

    paragraphs: list[Paragraph] = []
    buffer: list[str] = []
    last_art = 0
    in_final_disp = False

    def flush() -> None:
        nonlocal buffer
        if buffer:
            t = re.sub(r"\s+", " ", " ".join(buffer)).strip()
            if t:
                paragraphs.append(Paragraph(css_class="parrafo", text=t))
            buffer = []

    for i, s in enumerate(lines):
        if not s:
            flush()
            continue
        am = ARTICLE_RE.match(s)
        if am:
            n = int(am.group(2))
            is_upper = am.group(1).isupper()
            if am.group(1).islower():
                # lowercase "artículo" is a cross-reference, never a heading
                buffer.append(s)
                continue
            if in_final_disp and n != last_art + 1:
                # inside a final DISPOSICIONES section, an "ARTÍCULO" line that
                # does not continue the numbering is quoted text (cross-refs,
                # amendments to other codes), never an article heading
                buffer.append(s)
                continue
            # a real monotonic article continues the body: the DISPOSICIONES was
            # a mid-body structural section (e.g. Código Civil chapters), resume
            in_final_disp = False
            if is_upper or n > last_art:
                trailing = am.group(3) or ""
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                # "Artículo 14.1" (sub-article reference, no space) is a cross-ref
                sub_ref = re.match(r"\d+\.\d", trailing)
                # a "bis" qualifier marks a genuine added article ("ARTÍCULO 231
                # bis.1. ..."), never a cross-reference; the in_final_disp rule
                # above still keeps quoted bis reproductions (Ley-156) as body
                m_bis = re.match(r"^(bis)(?:[.\s]|$)", trailing, re.IGNORECASE)
                # a title-case heading whose trailing text or next line starts
                # lowercase continues a sentence: it is a cross-reference
                CROSSREF_RE = re.compile(
                    r"^[,;:]|^(?:apartado|inciso|numeral|párrafo|parrafo|literal)"
                    r"\b|^de (?:esta|este|la presente)\b",
                    re.IGNORECASE,
                )
                if not m_bis and (
                    sub_ref
                    or CROSSREF_RE.match(trailing)
                    or (trailing and trailing[0].islower() and n != last_art + 1)
                    or (not is_upper and not trailing and nxt and nxt[0].islower())
                ):
                    buffer.append(s)
                    continue
                flush()
                last_art = n
                # "ARTÍCULO 231 bis.1. ..." / "ARTÍCULO 521. bis. ..." ->
                # keep the "bis" qualifier in the heading
                bis = ""
                if m_bis:
                    bis = " bis"
                    trailing = trailing[m_bis.end() :]
                paragraphs.append(Paragraph(css_class="articulo", text=f"Artículo {n}{bis}"))
                if trailing:
                    buffer.append(trailing)
                continue
            # non-monotonic title-case: treat as cross-reference body text
            buffer.append(s)
            continue
        sm = SECTION_RE.match(s) or DISPOSICION_RE.match(s)
        if sm:
            flush()
            paragraphs.append(Paragraph(css_class=_section_css(s), text=s))
            if DISPOSICION_RE.match(s) and "GENERALES" not in s:
                in_final_disp = True
            continue
        buffer.append(s)
    flush()

    result = paragraphs
    if isinstance(pdf_path, bytes):
        _cache_put(key, result)
    return result


def unwrap_bundle(data: bytes) -> dict[str, Any]:
    """Decode the JSON bundle produced by ``GacetaClient.get_text``.

    The bundle carries the PDF bytes (base64), the manifest slicing knobs
    (``goc``, ``start_index``, ``start_regex``, ``end_regex``) and the
    publication date so the text parser can build a correctly-dated
    ``Version`` without a second API call.
    """
    if not data:
        return {}
    try:
        bundle = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Raw PDF bytes fall through as a backwards-compatible input
        # (json.loads raises UnicodeDecodeError on binary PDF data).
        return {}
    if not isinstance(bundle, dict) or "pdf" not in bundle:
        return {}
    pdf_b64 = bundle.get("pdf") or ""
    try:
        bundle["pdf_bytes"] = base64.b64decode(pdf_b64)
    except (ValueError, TypeError):
        bundle["pdf_bytes"] = b""
    return bundle
