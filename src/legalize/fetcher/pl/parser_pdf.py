"""Sejm ELI PDF parser — Poland.

Acts of the Dziennik Ustaw that the ELI API serves only as PDF (``textHTML: false``, ``textPDF: true``):
every act announced since 2025 and a few earlier ones. ``EliClient.get_text`` returns their PDF behind the
usual ``<!--LEGALIZE …-->`` marker and ``EliTextParser`` hands it here.

**Fidelity contract** (``adding-a-country/step-0-research.md`` §0.7): the same ``Block/Version/Paragraph``
shapes as the HTML path, so the renderer gives the same Markdown:

- ``## Treść rozporządzenia`` (the HTML's part heading, from the act type), ``## …`` / ``### Rozdział N. …``
  / ``#### Oddział …`` headings, ``## Załącznik …`` annex headings;
- ``###### Art. N.`` / ``###### § N.``, then ust. ``1. …``, pkt ``  1) …``, lit. ``    a) …``,
  tiret ``      – …``, with the cumulative indentation of ``parser._UNIT_DEPTH``;
- provisions quoted by amending acts as ``> …``;
- no title (the renderer prints it from the metadata), no footnotes and no signature (the HTML path
  strips those too).

Known differences (measured on 2024 acts, which have both formats): tables come out as paragraphs, row by
row, not as pipe tables; a quoted provision keeps its paragraphs (the HTML gives it as one line);
publication references "(Dz. U. … poz. …)", which the HTML leaves out, stay as printed; pages without a
text layer (scans) get a note instead of text, as there is no OCR here.

The PDF → units conversion (``pdf/convert.py``, ``pdf/tree.py``) is vendored from eli2md. Its output is a
tree of units (see ``pdf/tree.py``); this module maps the tree to blocks.
"""

from __future__ import annotations

import logging
import re
import tempfile
from datetime import date

from legalize.models import Block, Paragraph, Version

logger = logging.getLogger(__name__)

# Indentation per unit, cumulative down the tree, as parser._UNIT_DEPTH.
_DEPTH = {"ust": "", "pkt": "  ", "lit": "    ", "tir": "      ", "par": ""}
_FOOTNOTE_REF = re.compile(r"\[\^\w+\]")
_TITLE_DATE = re.compile(r"^z dnia \d{1,2} \w+ \d{4} r\.$")
_HEADINGS = {
    "dział": ("division", "titulo_tit"),
    "tytuł": ("title", "titulo_tit"),
    "część": ("part", "titulo_tit"),
    "księga": ("book", "titulo_tit"),
    "rozdział": ("chapter", "capitulo_tit"),
    "oddział": ("subsection", "seccion"),
}
# "## Treść rozporządzenia" — the HTML's part heading — from the first word of the act's title.
_GENITIVE = {
    "rozporządzenie": "rozporządzenia",
    "ustawa": "ustawy",
    "obwieszczenie": "obwieszczenia",
    "uchwała": "uchwały",
    "zarządzenie": "zarządzenia",
    "postanowienie": "postanowienia",
    "oświadczenie": "oświadczenia",
    "wyrok": "wyroku",
    "umowa": "umowy",
    "decyzja": "decyzji",
    "komunikat": "komunikatu",
    "konwencja": "konwencji",
    "protokół": "protokołu",
    "porozumienie": "porozumienia",
    "regulamin": "regulaminu",
    "sprostowanie": "sprostowania",
    "orzeczenie": "orzeczenia",
    "informacja": "informacji",
    "statut": "statutu",
    "aneks": "aneksu",
}


def _clean(text: str) -> str:
    return " ".join(_FOOTNOTE_REF.sub("", text).split())


def _marker(node: dict) -> str:
    kind, num = node["type"], node.get("num", "")
    if kind == "ust":
        return f"{num}. "
    if kind in ("pkt", "lit"):
        return f"{num}) "
    if kind == "tir":
        return "– "
    if kind == "par":
        return f"§ {num}. "
    return ""


def _leaf(node: dict, indent: str, out: list[Paragraph]) -> None:
    """A paragraph that is not a unit start: text, quoted text, a note about a page without text."""
    text = _clean(node.get("text", ""))
    if not text or node["type"] == "signature":
        return
    if node.get("quoted") or node["type"] in ("ocr", "note"):
        out.append(Paragraph(css_class="parrafo", text=f"> {text}"))
    elif indent:
        out.append(Paragraph(css_class="list_item", text=f"{indent}{text}"))
    else:
        out.append(Paragraph(css_class="parrafo", text=text))


def _children(node: dict, indent: str, out: list[Paragraph]) -> None:
    for child in node.get("children", []):
        if child["type"] in _DEPTH:
            child_indent = indent + _DEPTH[child["type"]]
            text = f"{child_indent}{_marker(child)}{_clean(child.get('text', ''))}".rstrip()
            out.append(Paragraph(css_class="list_item", text=text))
            _children(child, child_indent, out)
        else:
            _leaf(child, indent, out)


def _drop_title(nodes: list[dict]) -> tuple[list[dict], str]:
    """Drop the act's title printed at the top: type and organ in capitals ("ROZPORZĄDZENIE",
    "MINISTRA ZDROWIA"), "z dnia …" and the subject after it.

    The subject starts in lower case ("w sprawie …", "zmieniające …", "o …"); a preamble or
    "Na podstawie …" does not, so it stays, as does anything printed above the title (a note,
    "Sygn. akt …"). Titles without a "z dnia" line (some international agreements) stay. Returns the rest and the genitive of the act type ("" if the title was not
    found or the type is unknown).
    """
    lead = 0
    while (
        lead < len(nodes)
        and nodes[lead]["type"] in ("text", "note", "ocr")
        and not nodes[lead].get("quoted")
    ):
        lead += 1
    for i in range(min(lead, 8)):
        if nodes[i]["type"] == "text" and _TITLE_DATE.match(_clean(nodes[i]["text"])):
            first = i
            while (
                first > 0
                and nodes[first - 1]["type"] == "text"
                and _clean(nodes[first - 1]["text"]).isupper()
            ):
                first -= 1
            end = i + 1
            if end < lead and _clean(nodes[end]["text"])[:1].islower():
                end += 1
            kind = _clean(nodes[first]["text"]).split(" ")[0].lower() if first < i else ""
            return nodes[:first] + nodes[end:], _GENITIVE.get(kind, "")
    return nodes, ""


def tree_to_blocks(tree: dict, norm_id: str, pub_date: date) -> list[Block]:
    """Blocks from the tree of units of ``pdf.tree.md_to_tree``."""
    blocks: list[Block] = []
    seen: dict[str, int] = {}

    def emit(block_id: str, block_type: str, title: str, paras: list[Paragraph]) -> None:
        if not paras:
            return
        # a consolidated text may print an article twice (DU/2025/450: Art. 96 and "(uchylony)")
        seen[block_id] = seen.get(block_id, 0) + 1
        if seen[block_id] > 1:
            block_id = f"{block_id}-{seen[block_id]}"
        version = Version(
            norm_id=norm_id,
            publication_date=pub_date,
            effective_date=pub_date,
            paragraphs=tuple(paras),
        )
        blocks.append(Block(id=block_id, block_type=block_type, title=title, versions=(version,)))

    def part(nodes: list[dict], prefix: str) -> None:
        for k, node in enumerate(nodes, start=1):
            kind = node["type"]
            if kind in ("art", "par"):
                head = f"Art. {node['num']}." if kind == "art" else f"§ {node['num']}."
                paras = [Paragraph(css_class="articulo", text=head)]
                if text := _clean(node.get("text", "")):
                    paras.append(Paragraph(css_class="parrafo", text=text))
                _children(node, "", paras)
                emit(f"{prefix}{node['path']}", "article", head, paras)
            elif kind == "heading":
                label = _clean(node.get("label", ""))
                text = ". ".join(x for x in (label, _clean(node.get("text", ""))) if x)
                block_type, css = _HEADINGS.get(label.split(" ")[0].lower(), ("part", "titulo_tit"))
                emit(f"{prefix}{block_type}-{k}", block_type, text, [Paragraph(css, text)])
            elif kind in _DEPTH:  # ust./pkt/lit./tiret outside any article (annexes)
                indent = _DEPTH[kind]
                first = f"{indent}{_marker(node)}{_clean(node.get('text', ''))}".rstrip()
                paras = [Paragraph(css_class="list_item", text=first)]
                _children(node, indent, paras)
                emit(f"{prefix}item-{k}", "item", first.strip()[:120], paras)
            else:
                paras = []
                _leaf(node, "", paras)
                emit(
                    f"{prefix}preamble-{k}", "preamble", paras[0].text[:80] if paras else "", paras
                )

    body, genitive = _drop_title(tree["body"])
    if genitive:
        heading = f"Treść {genitive}"
        emit("part-0", "part", heading, [Paragraph(css_class="titulo_tit", text=heading)])
    part(body, "")
    for a, annex in enumerate(tree["annexes"], start=1):
        heading = _clean(annex["heading"])
        emit(f"annex-{a}", "annex", heading, [Paragraph(css_class="titulo_tit", text=heading)])
        part(annex["body"], f"annex-{a}/")
    return blocks


def parse_pdf(pdf: bytes, *, norm_id: str, pub_date: date) -> list[Block]:
    """Blocks of an act from its PDF. Raises ValueError if the PDF cannot be read."""
    from legalize.fetcher.pl.pdf.convert import convert, to_markdown
    from legalize.fetcher.pl.pdf.tree import md_to_tree

    parts = norm_id.split("-")
    # the act's position cuts it out of pages it shares with other acts (issues of 2011 and earlier)
    position = int(parts[2]) if len(parts) == 3 and parts[2].isdigit() else None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(pdf)
            f.flush()
            markdown = to_markdown(convert(f.name, position=position))
    except Exception as exc:  # noqa: BLE001 — pdfminer raises many kinds of errors
        # ValueError: the pipeline logs it and skips the act instead of committing a law
        # with no text.
        raise ValueError(f"Failed to parse PL PDF for {norm_id}: {exc}") from exc
    return tree_to_blocks(md_to_tree(markdown), norm_id, pub_date)
