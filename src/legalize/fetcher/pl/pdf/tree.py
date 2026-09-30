"""Tree of units (Art., §, ust., pkt, lit., tiret) from the converter's Markdown.

Vendored from eli2md 0.6.17 (eli2md/tree.py), https://github.com/PolskiAgentW/eli2md, MIT licence.
Changes: OCR left out (no tesseract here), no front matter, ruff rules of this repository
(``l`` -> ``ln``, ``zip(strict=False)``, ruff format). Otherwise the code is eli2md's; fixes belong there first.
"""

# eli2md module docstring:
# Tree of editorial units (Art., §, ust., pkt, lit., tiret) built from eli2md Markdown.
#
# The tree is built from the Markdown (not from the converter's internal blocks), so that the
# JSON can be rebuilt from the published .md files alone. The Markdown keeps what is needed: one
# paragraph per unit start, top-level units as `##### ` headings, annexes as `## `, footnotes as
# `[^n]: `. Quotation depth is recomputed from the paragraphs with the converter's rules
# (pdf.quote_depths) plus two rules for quotes the source does not open or close cleanly
# (see tree_depths). Art. nodes come only from `##### Art.` headings: a bare "Art. N." paragraph at
# depth 0 is always the number of a quoted article that the converter split off ("Art. 25." + "„1. …").
#
#     {"eli": ..., "title": ..., "converter": ...,         # from the front matter, if present
#      "body": [node, ...],                                  # main text
#      "annexes": [{"heading": "Załącznik nr 1 ...", "body": [node, ...]}],
#      "footnotes": {"1": "..."}}
#
# Unit node: {"type": "art"|"par"|"ust"|"pkt"|"lit"|"tir", "num": "41¹", "path": "art_41¹/ust_2",
#             "text": "text after the number", "children": [...]}
# Other nodes: {"type": "text", "text": ..., "quoted": true?}   paragraph that is not a unit start
#              {"type": "heading", "label": "Rozdział 2", "text": "title"}   dział/rozdział/oddział/...
#              {"type": "signature", "text": ...}   {"type": "note", "text": ...}  (content missing in PDF text)
#              {"type": "ocr", "text": ...}  paragraph read by OCR from a page without a text layer or from an
#                                            image of text on a page with one (`> ` in Markdown)
#
# Rules:
# - A unit is only recognised at quotation depth 0. Units quoted in amendments ("„Art. 5. …",
#   "1) …" after "otrzymuje brzmienie:") are `text` nodes with "quoted": true under the unit
#   that contains them.
# - Ranks: art > par (§) > ust > pkt > lit > tir (> tir under tir for "– –"). A unit becomes a child of
#   the nearest open unit of a higher rank, so an article without ust. can hold pkt directly and
#   § in codes sits under Art.
# - Numbers keep letters and superscripts as printed: "41¹", "2a"; an index with letters is all superscript
#   ("22¹ᵃ", printed "22[1a]" in 2026). Tirets have no number; `num` is their ordinal within the parent.
# - A paragraph that is not a unit start becomes a `text` child of the deepest open unit (except the
#   first one after a bare number such as `##### Art. N.` or `##### § N.`, which is that unit's own text). So a closing
#   sentence after a list of pkt ("część wspólna") ends up under the last pkt: the Markdown has no
#   indentation to tell them apart.
# - Headings of systematising units (DZIAŁ, Rozdział, Oddział, ...) are flat `heading` nodes between
#   the articles (articles are not nested in chapters); the next non-unit paragraph is their title.
#   In annexes, sections numbered "I." … "XXXIX." are `heading` nodes too (label "III.").
# - Numbered rows of tables and forms are `text`, not units (_Builder.table_row): points of lists of coordinates,
#   the rows and cell lists of a form card ("5. FUNKCJA PODSTAWOWA" … up to the next §, DU/2024/1337) and rows of
#   a table that an amendment replaces without quotes ("– – – lp. 8 otrzymuje brzmienie:" / "8. Program …").
# - Footnote markers stay in the text as `[^n]`, markers of notes printed in the text as `¹⁾` (see pdf._body_notes).
# - Each annex has its own tree (texts announced as consolidated texts have their own Art./§).
from __future__ import annotations

import json
import re

from .convert import LOWER, QUOTE_HEAD, SECONDS, SUP_CHARS, SUP_DIGITS

SUP = SUP_CHARS  # digits and letters of an index: "41¹", "22¹ᵃ"
UPPER = "A-ZĄĆĘŁŃÓŚŹŻ"
NOTE = rf"(?:\[\^\d+(?:_\d+)?\]|[{SUP_DIGITS}]+⁾)*"  # footnote markers glued to a unit number: "1a)[^2] treść",
# "Art. 5.[^3]", or markers of notes printed in the text: "2)²⁾ zamówień" (pdf._body_notes)
LEAD_NOTES = re.compile(
    r"^((?:\[\^\d+(?:_\d+)?\]\s*)+)(.*)$", re.S
)  # "[^7] 1. Treść" (marker of the Art. heading)
UNIT_RES = [  # (type, regex); groups: number, footnote markers, rest
    ("art", re.compile(rf"^Art\.\s*(\d+[a-z]*[{SUP}]*)\.({NOTE})\s*(.*)$", re.S)),
    ("par", re.compile(rf"^§\s*(\d+[a-z]*[{SUP}]*)\.({NOTE})\s*(.*)$", re.S)),
    # "2.Ustala się" (no space in the PDF) is a unit too, "1.1. Cel" is not
    ("ust", re.compile(rf"^(\d+[a-z]*[{SUP}]*)\.({NOTE})(?:\s+|(?=[{UPPER}]))(\S.*)$", re.S)),
    ("pkt", re.compile(rf"^(\d+[a-z]*[{SUP}]*)\)({NOTE})\s+(\S.*)$", re.S)),
    ("lit", re.compile(rf"^([a-z]{{1,3}}[{SUP}]*)\)({NOTE})\s+(\S.*)$", re.S)),
]
TIRET = re.compile(r"^((?:–\s*)+)\s(\S.*)$", re.S)  # "– tekst", "– – tekst"
RANK = {"art": 0, "par": 1, "ust": 2, "pkt": 3, "lit": 4, "tir": 5}
HEADING = re.compile(
    r"^((?:DZIAŁ|Dział|ROZDZIAŁ|Rozdział|ODDZIAŁ|Oddział|TYTUŁ|Tytuł|KSIĘGA|Księga|CZĘŚĆ|Część)"
    rf"\s+(?:[0-9]+[a-z]*[{SUP}]*|[IVXLC]+[a-z]*[{SUP}]*))\.?(?:\s+(.*))?$",
    re.S,
)  # "Rozdział 2. Tytuł" too
# "III. Stanowiska pracy …": a section of an annex numbered I–XXXIX. It ends the units of the section before
# (DU/2024/629: the "1)" list of section III is not under "6." of section II). Only in annexes: in the main text
# such lines are mostly rows of tables replaced by an amendment without quotes (DU/2025/330: "część I otrzymuje
# brzmienie:" / "I. Pakiet 1. …"), which must stay under the amending unit. Only as a sequence (_Builder.roman_section):
# "I. METALE" inside the table of "1. Substancje …" (DU/2024/1657) is a row of that table.
ROMAN = {"I": 1, "V": 5, "X": 10}
ROMAN_HEAD = re.compile(rf"^((?=[IVX])X{{0,3}}(?:IX|IV|V?I{{0,3}})\.)\s+([{UPPER}].*)$", re.S)
UNESCAPE = re.compile(
    r"^\\([>#|\[*+-])"
)  # the converter escapes Markdown syntax at a paragraph start
FRONT = re.compile(r"^---\n(.*?)\n---\n", re.S)
COMMON_PART = re.compile(rf"^(?:[{LOWER}]|–\s)")  # "część wspólna" after an enumeration
ANNOUNCES_QUOTE = re.compile(
    r"(?:brzmienie|brzmieniu)\s*:\s*$"
)  # "… otrzymuje brzmienie:", "… w brzmieniu:"
# the instruction of a point of an amending act ("13) art. 31 otrzymuje brzmienie:", "20) w załączniku do ustawy wprowadza
# się następujące zmiany:"), for a quote the source did not close (tree_depths)
AMENDS = re.compile(
    r"(?:brzmieni[eua]|dodaje\s+się|uchyla\s+się|skreśla\s+się|zastępuje\s+się|wprowadza\s+się"
    r"|^\S+\)\s+w\s+(?:art\.|§|załączniku)[^:]{0,40}:\s*$)"
)  # "16) w art. 34:" (DU/2007/162)
# Rows of tables and forms that look like units (_Builder.table_row). The Markdown has no table markup (pdf.py
# flattens tables into paragraphs), so these go by the text and the numbering only.
# A point of a list of coordinates: "6. 54°10′43,83″ N 19°22′52,30″ E" (DU/2024/1594), "2) 52°36'08"N 019°39'05"E"
# (DU/2025/947). Degrees followed by minutes, so "30 °C lub więcej:" stays a unit.
COORD = re.compile(r"^\d{1,3}\s?°\s?\d{1,2}(?:[,.]\d+)?\s?[′'’]")
# The label of a row of a form: an upper-case word followed by another one or by a number ("5. FUNKCJA PODSTAWOWA",
# "2. NUMER 18 3. OPIS …", "4. POLE 0,05 km²" in the cards of sea areas, DU/2024/1337), not by a sentence ("2. BGK
# przyznaje …", "ABW i SKW …").
FORM_LABEL = re.compile(rf"^[{UPPER}]{{3,}}(?:\s*$|\s+(?:[{UPPER}]{{2,}}(?![{LOWER}])|\d))")
NUM_PARTS = re.compile(rf"^(\d+)([a-z{SUP}]*)$")  # "27a" -> 27, "a"


def parse_unit(text: str) -> tuple[str, str, str] | None:
    """(type, num, text) if the paragraph starts a unit, else None. Tirets: num is the dash count."""
    for typ, rx in UNIT_RES:
        m = rx.match(text)
        if m:
            rest = m.group(3)
            return typ, m.group(1), (m.group(2) + " " + rest).strip() if m.group(2) else rest
    m = TIRET.match(text)
    if m:
        return "tir", str(m.group(1).count("–")), m.group(2)
    return None


def _next(prev: str, num: str) -> bool:
    """True if unit number num comes right after prev: "5" after "4", "27a" after "27", "28" after "27a", "e" after
    "d", "ca" after "c", "cb" after "ca"."""
    a, b = NUM_PARTS.match(prev), NUM_PARTS.match(num)
    if a and b:
        return int(b.group(1)) == int(a.group(1)) + 1 or (
            b.group(1) == a.group(1) and b.group(2) > a.group(2)
        )
    if prev.isalpha() and num.isalpha():
        return (
            len(num) == len(prev) and num[:-1] == prev[:-1] and ord(num[-1]) == ord(prev[-1]) + 1
        ) or (len(num) == len(prev) + 1 and num.startswith(prev))
    return False


def _closed_later(blocks: list[tuple[str, str]], i: int, limit: int = 60) -> bool:
    """True if a block after i closes a quote it did not open, before anything that starts a
    new top-level unit, opens a quote at its start or announces a new quote."""
    for kind, text in blocks[i + 1 : i + 1 + limit]:
        if kind in ("annex", "head"):
            return False
        t = SECONDS.sub("", text)
        if QUOTE_HEAD.match(t):
            return False
        local = 0
        for ch in t:
            if ch in "„“":
                local += 1
            elif ch in "”ˮ":
                if not local:
                    return True
                local -= 1
        if ANNOUNCES_QUOTE.search(t):
            return False
    return False


def tree_depths(blocks: list[tuple[str, str]]) -> list[int]:
    """Quotation depth at the start of each block, as pdf.quote_depths, with three changes:
    - depth is 0 at every `##### ` heading (the converter made it only at its depth 0);
    - after a block ending with "brzmienie:"/"brzmieniu:" the next blocks are quoted even if the
      source left out the opening „ (DU/2024/859: "dodaje się ust. 1a–1c w brzmieniu:" /
      "1a. Jeżeli …" / … "…”,"), but only if a later block closes the quote (_closed_later); tables
      replaced in amendments have no quotes at all (DU/2024/1141);
    - a quote opened mid-block and still open at a block ending with ":" runs into the next blocks
      ("zastępuje się wyrazami „…, w terminach:" / "1) …;" / "2) …”,", DU/2024/859), again only if a
      later block closes it.
    The pdf.quote_depths rule that other mid-block quotes end with their block is kept.
    A quote the source did not close ends at the next point of the amending act: a block "N) …" with an amending
    instruction, N right after the last point outside quotes and not after the last point at any depth inside them
    (DU/2008/539: "2) uchyla się art. 6a;" goes on the points of a quoted amending article after its own quote "1) …
    „Art. 6. … 20) …”;")
    (DU/2007/162: "…orzeczeniem sądu,”;" closes only the inner of two quotes, then "13) art. 31 otrzymuje brzmienie:";
    DU/2004/895: pkt 17 ends "…z późn. zm.)." without "”;")."""
    out, d, announced = [], 0, False
    top, inner = (
        None,
        {},
    )  # number of the last point outside quotes / at each depth inside the current quote
    for i, (kind, text) in enumerate(blocks):
        if kind in ("annex", "head"):
            d, top, inner = 0, None, {}
        t = SECONDS.sub("", text)
        head = QUOTE_HEAD.match(t)
        if announced and d == 0 and kind == "p" and not head and _closed_later(blocks, i - 1):
            d = 1
        unit = parse_unit(t) if kind == "p" and not head else None
        if (
            d
            and unit
            and unit[0] == "pkt"
            and top
            and _next(top, unit[1])
            and not any(_next(v, unit[1]) for v in inner.values())
            and AMENDS.search(t)
        ):
            d = 0
        if unit and d == 0:
            top, inner = (
                (
                    unit[1]
                    if unit[0] == "pkt"
                    else None
                    if RANK.get(unit[0], 9) < RANK["pkt"]
                    else top
                ),
                {},
            )
        elif unit and unit[0] == "pkt":
            inner = {k: v for k, v in inner.items() if k < d} | {d: unit[1]}
        elif (
            head and kind == "p" and (quoted := parse_unit(t[head.end() :])) and quoted[0] == "pkt"
        ):
            inner = {k: v for k, v in inner.items() if k <= d} | {
                d + 1: quoted[1]
            }  # "„1) …" opens a quote
        out.append(d)
        if kind == "ocr":  # OCR misreads quotes; the converter ignores them too
            continue
        carry, local = d, 0
        for k, ch in enumerate(t):
            if ch in "„“":
                if head and k == head.end() - 1:
                    carry += 1
                else:
                    local += 1
            elif ch in "”ˮ":
                if local:
                    local -= 1
                else:
                    carry = max(0, carry - 1)
        if local and t.rstrip().endswith(":") and _closed_later(blocks, i):
            carry += local
        d = carry
        announced = d == 0 and kind == "p" and bool(ANNOUNCES_QUOTE.search(t))
    return out


class _Builder:
    def __init__(self) -> None:
        self.body: list[dict] = []
        self.stack: list[tuple[int, dict]] = []  # (rank, node) of open units
        self.fresh: dict | None = (
            None  # unit with a bare number ("##### § 5.") still waiting for its text
        )
        self.heading: dict | None = None  # heading still waiting for its title
        self.common = False  # the last text was the common part after an enumeration
        self.undo: tuple[list, list] | None = (
            None  # (closed list item entries, common-part text nodes)
        )
        self.roman = 0  # number of the last "I." … "XXXIX." section heading
        self.table: int | None = (
            None  # rank of the unit that holds a form table (table_row), while it lasts
        )
        self.replaced: dict[str, str] | None = (
            None  # after a row of a table replaced without quotes (table_row):
        )
        # the number of the last row or item of that table per unit type

    def _parent_list(self) -> list[dict]:
        return self.stack[-1][1]["children"] if self.stack else self.body

    def close(self) -> None:
        self.stack.clear()
        self.fresh = self.heading = self.undo = self.table = self.replaced = None

    def table_row(self, typ: str, num: str, text: str) -> bool:
        """True if a paragraph that parses as a unit is a numbered row of a table or form (it stays text):
        - a point of a list of coordinates (COORD);
        - a row of a form, which also starts a table that lasts until the next unit of the rank of the unit
          holding it (the next § or Art., a heading, an annex): an "N." with an upper-case label (FORM_LABEL)
          that would be the first ust. of its parent and is not "1." (the cells before it were glued into other
          paragraphs: "KARTA AKWENU 1. OZNACZENIE LITEROWE" / "2. NUMER 18 3. OPIS 1. 54°…" / "5. FUNKCJA
          PODSTAWOWA" / "6. FUNKCJE DOPUSZCZALNE" / "1) badania naukowe (N);" …, DU/2024/1337). The official
          HTML marks none of the rows and lists in these cards as units;
        - a row of a table replaced by an amendment without quotes: an "N." under a unit that already holds
          pkt/lit/tirets but no ust., right after a unit that announces the new wording ("– – – lp. 3 i 4
          otrzymują brzmienie:" / "3. Realizacja Krajowego planu … 2.500 300 …", MP/2025/1248). Without the
          announcement such an ust. stays: "§ 7." + "1) …" + "2. Jeżeli termin …" (DU/2025/1895 prints no "1.").
          The units after such a row are rows or lists of the same table ("9ba. Przyjęcie zgłoszenia …: 155 zł" /
          "1) wolno stojących …" … "9) …", DU/2025/1847) until one continues a list of the act and not the list
          of the table (_next): "2) po ust. 9c dodaje się …" after "1) po ust. 9b …" and "9) …"; "– – – lp. 8
          otrzymuje brzmienie:" after "– – – lp. 3 i 4 …", "e) …" after "d) …" (MP/2025/1248)."""
        rank = RANK[typ] + (int(num) - 1 if typ == "tir" else 0)
        if self.table is not None:
            if rank > self.table:
                return True
            self.table = None
        if typ in ("ust", "pkt") and COORD.match(text):
            return True
        parent = next((node for r, node in reversed(self.stack) if r < rank), None)
        if self.replaced is not None:
            before = [
                c["num"] for c in (parent["children"] if parent else self.body) if c["type"] == typ
            ]
            if not (before and (typ == "tir" or _next(before[-1], num))) or (
                typ != "tir" and typ in self.replaced and _next(self.replaced[typ], num)
            ):
                self.replaced[typ] = num
                return True
        if typ != "ust" or parent is None or any(c["type"] == "ust" for c in parent["children"]):
            return False
        if num != "1" and FORM_LABEL.match(text):
            self.table = RANK[parent["type"]]
            return True
        if any(c["type"] in RANK for c in parent["children"]) and ANNOUNCES_QUOTE.search(
            self.stack[-1][1]["text"]
        ):
            self.replaced = {typ: num}
            return True
        return False

    def add_unit(self, typ: str, num: str, text: str) -> None:
        rank = RANK[typ]
        if typ == "tir":
            rank += int(num) - 1  # "– –" nests under "–"
        if self.undo and rank > self.undo[0][0][0]:
            # a unit below the closed list item follows ("3) … zakażeń" / "w stadzie" / "a) …"): the text
            # was the item's own text split by the layout, not the common part; put it back into the item
            closed, texts = self.undo
            parent = self._parent_list()
            del parent[len(parent) - len(texts) :]
            closed[-1][1]["children"].extend(texts)
            self.stack.extend(closed)
        self.undo = self.replaced = None
        if self.table is not None and rank <= self.table:
            self.table = None  # "##### § 2." ends the table of § 1
        while self.stack and self.stack[-1][0] >= rank:
            self.stack.pop()
        siblings = self._parent_list()
        if typ == "tir":
            num = str(1 + sum(1 for s in siblings if s["type"] == "tir"))
        seg = {"art": "art", "par": "par", "ust": "ust", "pkt": "pkt", "lit": "lit", "tir": "tir"}[
            typ
        ]
        path = (self.stack[-1][1]["path"] + "/" if self.stack else "") + f"{seg}_{num}"
        node = {"type": typ, "num": num, "path": path, "text": text, "children": []}
        self.common = False
        siblings.append(node)
        self.stack.append((rank, node))
        self.fresh = node if not text else None
        self.heading = None

    def add_text(self, text: str, quoted: bool) -> None:
        if self.fresh is not None and not quoted:
            self.fresh["text"] = text
            self.fresh = None
            return
        if self.heading is not None and not quoted and not self.heading["text"]:
            self.heading["text"] = text
            self.heading = None
            return
        self.fresh = self.heading = None
        node = {"type": "text", "text": text}
        if quoted:
            node["quoted"] = True
        elif (
            self.stack
            and (top := self.stack[-1][1])["type"] in ("pkt", "lit", "tir")
            and not top["children"]
            and not top["text"].rstrip().endswith(":")
            and COMMON_PART.match(text)
            and not self.common
        ):
            # text right after the last item of an enumeration that continues the sentence of the unit above
            # the list ("…: 1) …, 2) …" / "– w wysokości …", "oraz zmian …") belongs to that unit, not to the
            # item. Not after an item that ends with ":" (e.g. a legend of formula symbols follows)
            rank, closed = self.stack[-1][0], []
            while self.stack and self.stack[-1][0] >= rank:
                closed.insert(0, self.stack.pop())
            self.common = True  # further paragraphs of the common part stay with it
            self.undo = (closed, [])
        if self.undo:
            self.undo[1].append(node)
        self._parent_list().append(node)

    def add_heading(self, label: str, text: str) -> None:
        self.close()
        node = {"type": "heading", "label": " ".join(label.split()), "text": text}
        self.body.append(node)
        self.heading = node if not text else None

    def roman_section(self, label: str) -> bool:
        """True if "IV." is a section heading: "I." where no unit is open, the others right after the one before."""
        num = sum(
            ROMAN[a] if ROMAN[a] >= ROMAN.get(b, 0) else -ROMAN[a]
            for a, b in zip(label[:-1], label[1:], strict=False)
        )
        if (num == 1 and not self.stack) or (self.roman and num == self.roman + 1):
            self.roman = num
            return True
        return False

    def add_flat(self, typ: str, text: str) -> None:
        """Signature (ends the units) or a note about content missing from the text layer (in place)."""
        if typ == "signature":
            self.close()
            self.body.append({"type": typ, "text": text})
        else:
            self.fresh = self.heading = self.undo = None
            self._parent_list().append({"type": typ, "text": text})


def _tiret_list(blocks: list[tuple[str, str]], n: int, b: "_Builder") -> bool:
    """A "– " paragraph is a tiret when the paragraph before announces a list (ends with ":") or is itself
    a tiret (a running list); otherwise the dash opens the common part after an enumeration."""
    prev = blocks[n - 1][1].rstrip() if n else ""
    return prev.endswith(":") or bool(b.stack and b.stack[-1][1]["type"] == "tir")


def md_to_tree(md: str) -> dict:
    """Build the unit tree from eli2md Markdown (with or without front matter)."""
    out: dict = {"eli": None, "title": None, "converter": None, "source_pdf": None}
    m = FRONT.match(md)
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(": ")
            if k in out:
                out[k] = json.loads(v)
        md = md[m.end() :]
    paras = [p.strip("\n").rstrip() for p in md.split("\n\n")]  # leading spaces: see `note` below
    paras = [p for p in paras if p.strip()]
    if paras and paras[0].startswith("# "):
        out["title"] = out["title"] or paras[0][2:].strip()
        paras = paras[1:]
    footnotes: dict[str, str] = {}
    blocks: list[tuple[str, str]] = []  # (kind, text) in the converter's block kinds
    note = None  # label of the footnote whose indented paragraphs follow ("    1) wdraża…", DU/2026/421)
    for p in paras:
        if note and p.startswith("    "):
            footnotes[note] += "\n\n" + p.strip()
            continue
        p, note = p.strip(), None
        fm = re.match(r"^\[\^(\d+(?:_\d+)?)\]:\s*(.*)$", p, re.S)
        if fm:
            footnotes[fm.group(1)] = fm.group(2)
            note = fm.group(1)
        elif p.startswith("## "):
            blocks.append(("annex", p[3:].strip()))
        elif p.startswith("##### "):
            blocks.append(("head", p[6:].strip()))
        elif p.startswith("> [") and p.endswith("]"):
            blocks.append(("note", p[2:].strip()))
        elif p.startswith("> "):  # text read by OCR (a page without a text layer, an image of text)
            blocks.append(("ocr", UNESCAPE.sub(r"\1", p[2:].strip())))
        elif p.startswith("*") and p.endswith("*") and len(p) > 2:
            blocks.append(("signature", p[1:-1]))
        else:
            blocks.append(("p", UNESCAPE.sub(r"\1", p)))
    depths = tree_depths(blocks)

    parts = [("main", None, _Builder())]
    for n, ((kind, text), d) in enumerate(zip(blocks, depths, strict=False)):
        b = parts[-1][2]
        if kind == "annex":
            parts.append(("annex", text, _Builder()))
            continue
        if kind in ("signature", "note", "ocr"):
            b.add_flat(kind, text)
            continue
        notes, body = "", text
        if kind == "p" and (m := LEAD_NOTES.match(text)):
            notes, body = m.group(1).strip(), m.group(2)
        u = parse_unit(body) if d == 0 or kind == "head" else None
        if u and kind == "p" and u[0] == "art":
            # Art. N. at depth 0 that is not a heading: the converter split "Art. 25. „1. …" into
            # "Art. 25." + "„1. …" (a quoted article) or kept "Art. 30. „1. …" whole
            u = None
            d = 1
        if (
            u
            and kind == "p"
            and u[0] == "par"
            and not u[2]
            and n + 1 < len(blocks)
            and blocks[n + 1][1].startswith(("„", "“"))
        ):
            u, d = None, 1  # "§ 5." + "„1. …": the same split for a quoted §
        if u and u[0] == "tir" and kind == "p" and not _tiret_list(blocks, n, b):
            u = None  # "– …" after an enumeration that did not announce tirets: the common part, not a tiret
        if u and kind == "p" and b.table_row(*u):
            u = None
        if u:
            if (
                notes and b.fresh is not None
            ):  # "##### Art. 15c." + "[^7] 1. …": the marker belongs to Art.
                b.fresh["text"] = notes
            elif notes:
                u = (u[0], u[1], (notes + " " + u[2]).strip())
            b.add_unit(*u)
        elif d == 0 and (h := HEADING.match(text)) and len(text) < 300:
            b.add_heading(h.group(1), (h.group(2) or "").strip())
        elif (
            d == 0
            and kind == "p"
            and parts[-1][0] == "annex"
            and (h := ROMAN_HEAD.match(text))
            and b.roman_section(h.group(1))
        ):
            b.add_heading(h.group(1), h.group(2).strip())
        else:
            b.add_text(text, quoted=d > 0 or text.startswith(("„", "“")))
    out["body"] = parts[0][2].body
    out["annexes"] = [{"heading": h, "body": b.body} for _, h, b in parts[1:]]
    out["footnotes"] = footnotes
    return out


def iter_units(nodes: list[dict]):
    """All unit nodes (not text/heading/...) in document order."""
    for n in nodes:
        if n["type"] in RANK:
            yield n
        yield from iter_units(n.get("children", []))
