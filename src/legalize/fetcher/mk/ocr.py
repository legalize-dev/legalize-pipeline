"""LDBIS OCR, post-processing, and source-artifact cleanup."""

from __future__ import annotations
import gzip
import hashlib
import json
import functools
import math
import os
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pdfplumber

ASSET_ROOT = Path(__file__).with_name("assets")
PARAGRAPH = " "
# "бр. од 198" is how some issues print their number.
HEADER = re.compile(r"^Службен (весник|лист) на .*бр\.\s*(од\s*)?\d+\s*од\s*.*$")
# A masthead on a line of its own, as in RM-2008-18-14566, where the English model reads
# „Службен весник на РМ“бр. 18 од 05.02.2008 година as »Cny>x06eH BecHuk Ha PM"6p. 18 on 05.02.2008
# roauHa. It needs the issue and the full date with nothing else on the line, so a citation in the
# text, which names the issue as 18/2008, is never taken for one.
MASTHEAD_LINE = re.compile(
    r"^[\W_A-Za-z]{0,2}(?:Службен\s*весник|(?:Cny|Chy)\S{1,10}\s*BecH\w*)\s*(?:на|Ha)\s*"
    r"(?:РС?М|PC?M)\W{0,3}(?:бр|6p|op)\.?\s*\d{1,3}\s*(?:од|o\w)\s*\d{1,2}\.\d{1,2}\.\d{4}"
    r"\s*(?:година|ro\w{2,5})?[\s\W\d]{0,4}$",
    re.I,
)
CODE = re.compile(r"^\d{11}$")
FOOTER = re.compile(r"^(\d+)\s*(?:од|on|op|oa|og|0a|of)\s*(\d+)[.!,:;]?$", re.I)
GAZETTE_HEADER = re.compile(
    r"(?:Службен\s+(?:весник|лист)\s+на\b|"
    r"(?:Cny|Chyx)[^\s]{1,15}\s+Be\w+\s+Ha\s+PM\b|"
    r"CII\w+\s+BECH\w+\s+HA\s+PEMYB\w+)",
    re.I,
)
GAZETTE_DATE = re.compile(
    r"(?:\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|"
    r"\b\d{1,2}\s+[A-Za-zА-Яа-я]{2,10}1?\s+\d{4}\b)"
)
GAZETTE_ISSUE = re.compile(r"(?:бр|bp|6p|gp|op)\.?\s*\d+", re.I)
GAZETTE_HEADER_START = re.compile(
    r"^\s*(?:(?:Cip|Cp|Crp)\.?\s*\d+\s*[-–]\s*(?:Bp|6p)\.?\s*\d+|\d{1,5})?\s*"
    r"(?:\d{1,2}\s+[A-Za-zА-Яа-я]{2,10}1?\s+\d{4}\s+)?"
    r"(?:Службен\s+(?:весник|лист)\s+на\b|"
    r"(?:Cny|Chyx)[^\s]{1,15}\s+Be\w+\s+Ha\s+PM\b|"
    r"CII\w+\s+BECH\w+\s+HA\s+PEMYB\w+)",
    re.I,
)


def iso(d):
    return f"{d[6:10]}-{d[3:5]}-{d[0:2]}" if re.fullmatch(r"\d\d\.\d\d\.\d{4}", d or "") else None


def without_stray_spaces(page):
    """Justified lines carry space glyphs lying on top of letters, which split a word in two."""
    rows = {}
    for c in page.chars:
        if c["text"].strip():
            rows.setdefault(round(c["top"]), []).append(c)

    def stray(c):
        if c["text"] != " ":
            return False
        near = (
            rows.get(round(c["top"]), [])
            + rows.get(round(c["top"]) - 1, [])
            + rows.get(round(c["top"]) + 1, [])
        )
        return any(min(c["x1"], o["x1"]) - max(c["x0"], o["x0"]) > 1.5 for o in near)

    return page.filter(lambda obj: obj.get("object_type") != "char" or not stray(obj))


LAW_HEADING = re.compile(r"^З\s?А\s?К\s?О\s?Н(\s|$)")


def law_text_only(lines, title):
    """Drops the proclamation decree before the law and the heading that repeats the title.

    The decree is a formality of the presidency, not part of the law, and its signature block
    is laid out as a table that the text layer cannot give back in reading order."""
    start = next((n for n, ln in enumerate(lines) if LAW_HEADING.match(ln)), None)
    if start is None:
        return lines
    rest = lines[start:]
    heading = re.sub(r"\W", "", " ".join(rest[:3]).casefold())
    for take in (1, 2, 3):
        if heading.startswith(re.sub(r"\W", "", title.casefold())) and re.sub(
            r"\W", "", " ".join(rest[:take]).casefold()
        ) == re.sub(r"\W", "", title.casefold()):
            return rest[take:]
    return rest


def straightened(gray):
    """The page rotated by the angle, within five degrees, at which its text rows line up best.

    A photocopy laid crooked on the glass made tesseract drop and merge words on the 2002 gazette."""
    import cv2
    import numpy as np

    ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    small = cv2.resize(ink, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    h, w = small.shape

    def row_contrast(angle):
        turned = cv2.warpAffine(small, cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1), (w, h))
        return np.var(turned.sum(axis=1))

    angle = max(np.arange(-5, 5.01, 0.25), key=row_contrast)
    if angle == 0:
        return gray
    h, w = gray.shape
    return cv2.warpAffine(
        gray,
        cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1),
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderValue=255,
    )


DOUBTFUL_LINE = 80
# How much surer the English model must be of a line before it replaces the Macedonian reading.
ENGLISH_MARGIN = 10
# How sure the English model must be of a line in another Latin-script language before it is taken.
LATIN_SURE = 50
DOUBTFUL_PAGE = 85


def tesseract_lines(png, lang, psm="6", tessdata=""):
    """Lines of a page as dicts of box, words and mean word confidence, in reading order."""
    fetch_model(tessdata, lang)
    env = {**os.environ, "TESSDATA_PREFIX": tessdata, "OMP_THREAD_LIMIT": "1"}
    out = subprocess.run(
        ["tesseract", png, "-", "-l", lang, "--psm", psm, "-c", "tessedit_create_tsv=1"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    ).stdout
    lines = {}
    for row in out.splitlines()[1:]:
        c = row.split("\t")
        if len(c) == 12 and c[11].strip() and float(c[10]) >= 0:
            x, y, w, h = map(int, c[6:10])
            ln = lines.setdefault(
                (int(c[2]), int(c[3]), int(c[4])),
                {"words": [], "confs": [], "spans": [], "top": y, "bottom": y + h},
            )
            ln["words"].append(c[11])
            ln["confs"].append(float(c[10]))
            ln["spans"].append((x, x + w))
            ln["top"], ln["bottom"] = min(ln["top"], y), max(ln["bottom"], y + h)
    found = table_rows(lines.values()) if psm == "11" else list(lines.values())
    for ln in found:
        ln["conf"] = sum(ln["confs"]) / len(ln["confs"])
    return found


def table_rows(cells):
    """The cells of a sparse reading joined into the rows they sit on, left to right.

    Sparse mode reads each cell of a table on its own, which reads its words far better than the
    block mode does across ruled columns, but gives every cell as a line of its own."""
    rows = []
    for cell in sorted(cells, key=lambda c: (c["top"] + c["bottom"]) / 2):
        middle = (cell["top"] + cell["bottom"]) / 2
        row = rows[-1] if rows and rows[-1]["top"] <= middle <= rows[-1]["bottom"] else None
        if row is None:
            rows.append(
                {
                    "words": [],
                    "confs": [],
                    "spans": [],
                    "top": cell["top"],
                    "bottom": cell["bottom"],
                    "cells": [],
                }
            )
            row = rows[-1]
        row["cells"].append(cell)
        row["top"], row["bottom"] = min(row["top"], cell["top"]), max(row["bottom"], cell["bottom"])
    for row in rows:
        for cell in sorted(row.pop("cells"), key=lambda c: c["spans"][0][0]):
            row["words"] += cell["words"]
            row["confs"] += cell["confs"]
            row["spans"] += cell["spans"]
    return rows


ENGLISH_WORDS = None


def english(words):
    """Whether most words of a line are English words, so a Macedonian line the English model
    misread with confidence ("В. Член 2Е, став 8" as "B. Ynen 2F, cTas 8") is not taken."""
    global ENGLISH_WORDS
    if ENGLISH_WORDS is None:
        # Webster's Second (web2) and the BSD propernames list, as macOS ships them in
        # /usr/share/dict, casefolded. Shipped so every machine reads the same words, since an
        # Ubuntu runner has neither file.
        ENGLISH_WORDS = set(
            gzip.open(ASSET_ROOT / "en_words.txt.gz", "rt", encoding="utf-8").read().split()
        )
    found = total = 0
    for w in words:
        w = re.sub(r"[^A-Za-z]", "", w).casefold()
        # Two-letter words prove nothing: a Macedonian table line "Од 15 до" reads as "On 15 no".
        if len(w) < 3:
            continue
        total += 1
        found += any(
            w[: len(w) - len(end)] in ENGLISH_WORDS
            for end in ("", "s", "es", "ed", "d", "ing", "ly")
            if w.endswith(end)
        )
    return total > 0 and found >= total / 2


def foreign(words):
    """Whether a Macedonian reading is not Macedonian at all: at least two Cyrillic words of four
    letters or more, and under a third of them words Macedonian text uses.

    Treaties print the partner's language beside the Macedonian, and German read by the Macedonian
    model came out as "Аџзашоск уоп Ехрепшплеп", which no Macedonian word is, while a faded
    Macedonian line still keeps most of its words. Shorter scraps ("пас", "дет") and words seen once
    or twice match by chance, so they are not counted."""
    vocab()
    cores = [c for w in words if len(c := re.sub(r"[^\w]", "", w)) >= 4 and MK_WORD.match(c)]
    known = sum(c.casefold() in VOCAB for c in cores)
    return (
        len(cores) >= 2
        and known < len(cores) / 3
        and (s := letter_score(words)) is not None
        and s < FOREIGN_SCORE
    )


# A faded Macedonian line read badly ("Логоворните стоани ја позправувзат") has few dictionary words
# too, but it keeps Macedonian runs of letters. Measured on scans, Macedonian lines scored -2.0 at
# the median and German and Slovak read in Cyrillic -3.4 to -3.7, with the cut between them.
FOREIGN_SCORE = -2.6
TRIGRAMS = None


def letter_score(words):
    """The mean log likelihood of a line's letter triples under Macedonian words, or None when the
    line has under eight triples to judge by."""
    global TRIGRAMS
    if TRIGRAMS is None:
        tri, pairs = Counter(), Counter()
        for w, c in vocab().items():
            w, weight = f"^{w}$", math.log1p(c)
            for i in range(len(w) - 2):
                tri[w[i : i + 3]] += weight
                pairs[w[i : i + 2]] += weight
        TRIGRAMS = tri, pairs
    tri, pairs = TRIGRAMS
    total = n = 0
    for w in words:
        core = re.sub(r"[^\w]", "", w).lower()
        if len(core) >= 3 and MK_WORD.match(core):
            core = f"^{core}$"
            for i in range(len(core) - 2):
                total += math.log((tri[core[i : i + 3]] + 0.1) / (pairs[core[i : i + 2]] + 3.3))
                n += 1
    return total / n if n >= 8 else None


# Below this mean confidence a line on a doubtful page may be a picture read as text.
NONSENSE_CONF = 50


def nonsense(pairs):
    """Whether a line the model was unsure of is marks in a picture rather than text: no word of
    four letters it was 60 % sure of, and under half its words of three letters or more real
    Macedonian or English words, unless it is one long word (a heading such as "ПРЕАМЊБУЛА") or
    its letters run like Macedonian (a faded line).

    Sideways tables of unit symbols (64161) and photographs of icons (63335) came out as lines such
    as "ош 01 ЕУ 1". Measured on 148,000 cached lines (31 October 2026), the rule kept the faded
    Macedonian and the badly read partner languages, but on good pages it also caught table cells
    whose words ran together, so it is applied to doubtful pages only.

    Rules and dashes are left out of the judgement, since the model reads a "=" with confidence and
    a line of a sideways table such as "не == = = щен — ти - о ===" came out as sure text."""
    pairs = [(w, c) for w, c in pairs if re.search(r"[^\W_]", w)]
    if not pairs:
        return True
    # Chinese, Arabic and the other scripts come out a character or a short run per word, which no
    # vocabulary here can judge.
    if any(re.search(r"[^\W\d_A-Za-zÀ-ɏЀ-ӿ]", w) for w, _ in pairs):
        return False
    if sum(c for _, c in pairs) / len(pairs) >= NONSENSE_CONF:
        return False
    cores = [c for w, _ in pairs if len(c := re.sub(r"\W|\d|_", "", w)) >= 3]
    if not cores:
        return any(re.search(r"[^\W\d_]", w) for w, _ in pairs)
    if any(c >= 60 and len(re.sub(r"\W|\d|_", "", w)) >= 4 for w, c in pairs) or (
        len(pairs) == 1 and len(cores[0]) >= 6
    ):
        return False
    words = [w for w, _ in pairs]
    if (
        any(MK_WORD.match(c) for c in cores)
        and (score := letter_score(words)) is not None
        and score >= FOREIGN_SCORE
    ):
        return False
    # Three letter scraps ("тот", "вши") are words by chance, as in foreign().
    cores = [c for c in cores if len(c) >= 4]
    vocab()
    english([])
    real = sum(
        c.casefold() in VOCAB or c.casefold() in SEEN
        if MK_WORD.match(c)
        else any(
            c.casefold()[: len(c) - len(end)] in ENGLISH_WORDS
            for end in ("", "s", "es", "ed", "d", "ing", "ly")
            if c.casefold().endswith(end)
        )
        for c in cores
    )
    return real < len(cores) / 2 or not cores


# A numbered article heading in any of the printed languages, kept however unsure the model was.
ARTICLE_HEADING = re.compile(r"\b(?:Член|Чл|Article|Artikel|Статья|Neni|Član|Člen)\w*\W*\d", re.I)


def scrawl(pairs):
    """Whether a line on any page is a signature, stamp or rule read as letters: three or more
    words the model was on average under 35 % sure of and never 60 % sure of one, and no word of
    four letters that is a known Macedonian or English word, no article heading and no other
    script.

    RM-2008-18-14566 printed an ambassador's signature as "p: wt on wh wy", and read again as
    "p: Le aE ws wy", "wy" at 53 %. Measured on the 31,160 confident cached pages (4 November
    2026), the 950 lines with every word under 40 % were nine in ten signatures, stamps, rules
    and Latin readings of a Cyrillic running head; widening to the average added 2,065 lines on
    38,385 pages, of which a sample of 60 held 54 marks and six garbled readings of real words
    ("Dextsing and athor modified"). The page of each is listed as unread. The exceptions named
    here ("N Artikel 22", "Општи услови", Arabic and Chinese lines) are what was left."""
    words = [(w, c) for w, c in pairs if re.search(r"[^\W_]", w)]
    confidences = [c for _, c in words]
    if len(words) < 3 or max(confidences) >= 60 or sum(confidences) >= 35 * len(words):
        return False
    line = " ".join(w for w, _ in words)
    if ARTICLE_HEADING.search(line) or re.search(r"[^\W\d_A-Za-zÀ-ɏЀ-ӿ]", line):
        return False
    vocab()
    english([])
    for word, _ in words:
        core = re.sub(r"\W|\d|_", "", word).casefold()
        if len(core) >= 4 and (core in VOCAB or core in ENGLISH_WORDS):
            return False
    return True


UNREADABLE_CONF = 30


def unreadable(pairs):
    """Whether a line of two words or more holds no known word and the model was under 30 % sure
    of its words on average.

    On a sure page such a line that is also nonsense is left out: measured on the 30,232 sure
    cached pages (6 November 2026), the 3,000 such lines are logo marks, stamps, the scrap "- o"
    under the letterhead of 14566 page 2, and running heads read in the wrong script. A one-word
    line stays, since "b)" and "cauză." were among them. A page that keeps such a line, as the
    address under the same letterhead ("mad; delegation-fymmacedonia@ec europa. eu"), is recorded
    as doubtful, because the line is not nonsense by the word list and no rule tried told its
    scraps, or the "wl ata" before "EUROPEAN UNION", from real numbering such as "(iii):"."""
    words = [(w, c) for w, c in pairs if re.search(r"[^\W_]", w)]
    return (
        len(pairs) >= 2
        and bool(words)
        and sum(c for _, c in words) / len(words) < UNREADABLE_CONF
        and not any(re.sub(r"[\W\d_]", "", w).casefold() in vocab() for w, _ in words)
    )


def readable(page):
    """A cached page's lines, without the marks in pictures (on a sure page only the unreadable
    ones), and without the signatures and stamps on any page."""
    lines = [
        pairs
        for pairs in page["lines"]
        if not nonsense(pairs) or (page["confidence"] >= DOUBTFUL_PAGE and not unreadable(pairs))
    ]
    return [
        pairs
        for pairs in lines
        if pairs[0][0].startswith(TABLE_MARK) or (without_noise(pairs) and not scrawl(pairs))
    ]


def merged_line(mkd, eng):
    """An English-looking line put together word by word: the English reading of each English word,
    and the Macedonian reading everywhere else, because the Macedonian text is what this export is
    for and a confident English misreading once turned "гас" into "rac".

    A definition such as "електрична енергија (European Network of ...)" is one printed line, and
    taking the whole English reading turned its Macedonian half into "enektpudHa eHepruja". A
    one-letter word ("a", "I") follows its neighbours, since the word list cannot judge it."""
    is_en = [english([w]) if len(re.sub(r"[^A-Za-z]", "", w)) >= 3 else None for w in eng["words"]]
    for i, v in enumerate(is_en):
        if v is None:
            is_en[i] = bool((i > 0 and is_en[i - 1]) or (i + 1 < len(is_en) and is_en[i + 1]))
    picked, taken = [], set()
    for word, conf, (x0, x1) in zip(mkd["words"], mkd["confs"], mkd["spans"], strict=True):
        over = [j for j, (a, b) in enumerate(eng["spans"]) if min(x1, b) - max(x0, a) > 0]
        if over and all(is_en[j] for j in over):
            picked += [
                (eng["spans"][j][0], eng["words"][j], eng["confs"][j])
                for j in over
                if j not in taken
            ]
            taken.update(over)
        else:
            picked.append((x0, word, conf))
    picked += [
        (eng["spans"][j][0], eng["words"][j], eng["confs"][j])
        for j in range(len(eng["words"]))
        if j not in taken
        and is_en[j]
        and not any(
            min(eng["spans"][j][1], b) - max(eng["spans"][j][0], a) > 0 for a, b in mkd["spans"]
        )
    ]
    picked.sort()
    words, confs = [w for _, w, _ in picked], [c for _, _, c in picked]
    return {"words": words, "confs": confs, "conf": sum(confs) / len(confs)}


PERCENT = re.compile(r"^[(„“]?\d[\d.,]*%[.,;:)“]*$")
NUMBER = re.compile(r"^\(?\d[\d.,]*[.,;:)]*$")
# A number the Macedonian model tangled with the letters that look like digits, "б6" for 6. A lone
# "б)" is never one, since that is an item of a list.
TANGLED = re.compile(r"^\(?[\dбзЗоО]*\d[\dбзЗоО]*[.,;:)]*$")
ROMAN = re.compile(r"^[IVXLC]+[.)]?$")
ROMAN_LOOKALIKE = re.compile(r"^[ІТУХЧЛШПГЃЏ1]{1,5}[.)]?$")


def with_signs(mkd, eng):
    """A Macedonian line with the English reading of its numbers and of the signs the Macedonian
    model has no letters for, which are % and Roman numerals.

    The Macedonian model knows 86 characters, none of them % or a Latin letter, so on a text-layer
    page read as a test "20%" came out as "2050" and the chapter numbers V, IV and XI as "У", "ТУ"
    and "Х1". The English model is also better at digits, which both print alike: it kept the 7 of
    "членот 70" that the Macedonian one dropped. A word is swapped only when a single English word
    lies under it and is one of those, so no Macedonian word is ever replaced."""
    words, confs = list(mkd["words"]), list(mkd["confs"])
    for i, (x0, x1) in enumerate(mkd["spans"]):
        over = [j for j, (a, b) in enumerate(eng["spans"]) if min(x1, b) - max(x0, a) > 0]
        if len(over) != 1:
            continue
        alt, conf = eng["words"][over[0]], eng["confs"][over[0]]
        if (
            (PERCENT.match(alt) and words[i][:1].isdigit())
            or (NUMBER.match(alt) and NUMBER.match(words[i]) and conf >= confs[i])
            or (NUMBER.match(alt) and TANGLED.match(words[i]) and not NUMBER.match(words[i]))
            or (ROMAN.match(alt) and ROMAN_LOOKALIKE.match(words[i]))
        ):
            words[i], confs[i] = alt, conf
    return {**mkd, "words": words, "confs": confs}


def same_line(a, b):
    overlap = min(a["bottom"], b["bottom"]) - max(a["top"], b["top"])
    return overlap > 0.5 * min(a["bottom"] - a["top"], b["bottom"] - b["top"])


def without_rules(gray, wide=False):
    """The page with long thin vertical and horizontal strokes painted white.

    A crease down a 2012 photocopy cut words in half, and the ruled tables of the old forms let
    tesseract find under a hundred words on a page that holds several hundred. A rule is ten
    millimetres or longer at 300 dpi, longer than any letter.

    Wide clears a broader band and joins nothing back, for a table whose rules sit close against
    its figures. The grey edge of a rule and the strokes joined across it read as marks between
    the cells of 2011's tariff quotas (23196), where wide took the page from 43 to 78 % sure. On
    running text the joining matters more, so a doubtful page is read both ways."""
    import cv2
    import numpy as np

    ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    vertical = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 120))
    )
    horizontal = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (200, 1))
    )
    out = gray.copy()
    grow = np.ones((7, 7) if wide else (3, 3), np.uint8)
    across, down = cv2.dilate(horizontal, grow) > 0, cv2.dilate(vertical, grow) > 0
    out[across | down] = 255
    if wide:
        return out
    # A rule running through a line of text took a slice out of every letter it crossed, and
    # tesseract dropped those lines (23195, where slice borders of a pasted page cross the text).
    # Strokes that reach the cleared band from both sides are joined back across it.
    ink = cv2.threshold(out, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    joined_down = (
        cv2.morphologyEx(ink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 15)))
        > 0
    )
    joined_across = (
        cv2.morphologyEx(ink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1)))
        > 0
    )
    out[(across & joined_down) | (down & joined_across)] = 0
    return out


# The gazette's own running head, printed on every scanned page: "Стр. 750 - Бр. 13 Службен весник ...".
RUNNING_HEAD = re.compile(
    r"(?:[Сс][лп]ужбен\s*весник|(?:Cny|Chyx)[^\s]{1,15}\s+Be\w+\s+Ha\s+PM|"
    r"CII\w+\s+BECH\w+\s+HA\s+PEMYB\w+)",
    re.I,
)
PAGE_REF = re.compile(r"(?:Стр\.?|C(?:tp|rp|p)\.?)\s*\d", re.I)
RUNNING_HEAD_DATE = re.compile(
    r"\b\d{1,2}\s*[A-Za-zА-Яа-я]{2,15}1?\s*\d{4}\b|\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b",
    re.I,
)
RUNNING_HEAD_SERIES = re.compile(
    r"(?:М[ЕE][ЃГG]УНАРОДНИ\s+ДОГОВОРИ|МЕГУНАРОДНИ\s+ДОГОВОРИ|"
    r"METY\w{1,14}\s+(?:\w{1,12}\s+){1,3}OBOP\w*|"
    r"METY\w{1,14}\s+(?:\w{1,10}\s+)?(?:ДОГОВОРИ|LOT\w*\s*OBOP\w*))",
    re.I,
)
RUNNING_HEAD_MARKER = re.compile(
    r"(?:Службен\s*весник\s*на\b|СЛУЖБЕН\s*ВЕСНИК\s*НА|СЛУЖБЕНВЕСНИКНА|"
    r"(?:Cny|Chyx)[^\s]{1,16}\s+Be\w+\s+Ha\s+PM\b|CII\w+\s+BECH\w+\s+HA\s+\w{3,20})",
    re.I,
)
RUNNING_PAGE_NUMBER = re.compile(r"(?:Стр|C(?:tp|rp|p)|0p|op)\.?\s*(\d+)", re.I)
RUNNING_HEAD_YEAR_SUFFIX = re.compile(r"\s+(?:година|год\.?|roguHa|roauHa|roanHa|roanHHa)\b", re.I)
FINAL_PAGE_NUMBER = re.compile(r'(?<=[.!?"”])\s+\d{1,3}\s*$')
FINAL_ACT_CLAUSE = re.compile(
    r"(?:влегува\s+во\s+сила|стапува\s+во\s+сила|влегува\s+во\s+важност|прогласувањето|с\.\s*р\.)",
    re.I,
)


def running_header_spans(line):
    """Locate a gazette running head inside a flattened text row by its page, issue, and date."""
    spans = []
    issues, pages, dates = (
        list(pattern.finditer(line)) for pattern in (GAZETTE_ISSUE, PAGE_REF, RUNNING_HEAD_DATE)
    )
    for head in RUNNING_HEAD_MARKER.finditer(line):
        for issue in issues:
            for page in pages:
                if (
                    abs(issue.start() - page.start()) > 24
                    or max(abs(issue.start() - head.start()), abs(page.start() - head.start()))
                    > 140
                ):
                    continue
                date = next((d for d in dates if abs(d.start() - head.start()) <= 160), None)
                if date is None:
                    continue
                start = min(head.start(), issue.start(), page.start(), date.start())
                end = max(head.end(), issue.end(), page.end(), date.end())
                if end - start <= 220:
                    spans.append((start, end))
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def repeated_header_spans(line):
    """Find a masthead and its adjacent issue/page pair when OCR lost the printed date."""
    spans = []
    issues = list(GAZETTE_ISSUE.finditer(line))
    pages = [
        (match.start(), match.end(), int(match.group(1)), False)
        for match in RUNNING_PAGE_NUMBER.finditer(line)
    ]
    for head in RUNNING_HEAD_MARKER.finditer(line):
        leading_counter = re.fullmatch(r"\s*(\d{1,6})\s*", line[: head.start()])
        page_candidates = pages.copy()
        if leading_counter:
            page_candidates.append(
                (
                    leading_counter.start(1),
                    leading_counter.end(1),
                    int(leading_counter.group(1)),
                    True,
                )
            )
        for issue in issues:
            for page_start, page_end, page_number, is_leading_counter in page_candidates:
                if (not is_leading_counter and abs(issue.start() - page_start) > 24) or max(
                    abs(issue.start() - head.start()), abs(page_start - head.start())
                ) > 140:
                    continue
                dates = [
                    d
                    for d in RUNNING_HEAD_DATE.finditer(line)
                    if abs(d.start() - head.start()) <= 160
                ]
                series = next(
                    (
                        s
                        for s in RUNNING_HEAD_SERIES.finditer(line)
                        if head.end() <= s.start() <= head.end() + 120
                    ),
                    None,
                )
                if not dates and series is None:
                    continue
                series_date = None
                if series:
                    m = re.match(
                        r"\s+\d{1,2}\s*[A-Za-zА-Яа-я]{3,15}(?:\s*\d{1,4})?",
                        line[series.end() : series.end() + 40],
                    )
                    if m:
                        series_date = (series.end() + m.start(), series.end() + m.end())
                start = min([head.start(), issue.start(), page_start] + [d.start() for d in dates])
                end = max(
                    [head.end(), issue.end(), page_end, series.end() if series else 0]
                    + [d.end() for d in dates]
                )
                if series_date:
                    start, end = min(start, series_date[0]), max(end, series_date[1])
                year_suffix = RUNNING_HEAD_YEAR_SUFFIX.match(line, end)
                if year_suffix:
                    end = year_suffix.end()
                if end - start <= 240:
                    spans.append((start, end, page_number))
    return spans


def remove_repeated_headers(pages):
    """Remove a gazette masthead wherever its page and issue markers identify it.

    A flattened OCR paragraph can place one running head between two legal words,
    so waiting for the same header on two pages leaves noise in short documents
    and in pages whose neighbouring header was unreadable. The span detector
    already requires the masthead, issue, page marker, and date or series to be
    close together before removing it.
    """
    found = []
    for page_index, page in enumerate(pages):
        for line_index, line in enumerate(page.splitlines()):
            found.extend(
                (page_index, line_index, start, end, number)
                for start, end, number in repeated_header_spans(line)
            )
    if not found:
        return pages
    rows = {}
    for page_index, line_index, start, end, _ in found:
        rows.setdefault((page_index, line_index), []).append((start, end))
    for page_index, page in enumerate(pages):
        lines = page.splitlines()
        for (row_page, line_index), spans in rows.items():
            if row_page != page_index:
                continue
            for start, end in sorted(spans, reverse=True):
                lines[line_index] = lines[line_index][:start] + " " + lines[line_index][end:]
            lines[line_index] = " ".join(lines[line_index].split())
        pages[page_index] = "\n".join(lines)
    return pages


PAGE_NUMBER_LINE = re.compile(r"^\s*(\d{1,3})(?:\s+(?:од\s+)?(\d{1,4}))?\s*[.)]?\s*$", re.I)


def remove_sequential_page_numbers(pages):
    """Drop isolated edge numbers only when adjacent PDF pages prove they are counters.

    The page text is joined after OCR, so a printed folio at the bottom of one page can
    land between two words in a paragraph. A number must advance by one on three
    consecutive pages and occupy the same edge position before it is removed.
    """
    rows = []
    for page in pages:
        lines = page.splitlines()
        candidates = {}
        for i, line in enumerate(lines[:4]):
            match = PAGE_NUMBER_LINE.fullmatch(line)
            if match:
                candidates[("top", i)] = (int(match.group(1)), match.group(2))
        for i in range(max(0, len(lines) - 4), len(lines)):
            match = PAGE_NUMBER_LINE.fullmatch(lines[i])
            if match:
                candidates[("bottom", len(lines) - 1 - i)] = (int(match.group(1)), match.group(2))
        rows.append((lines, candidates))

    remove = set()
    for i in range(len(rows) - 2):
        for edge_pos, number in rows[i][1].items():
            if all(
                edge_pos in rows[j][1]
                and rows[j][1][edge_pos][0] == number[0] + j - i
                and rows[j][1][edge_pos][1] == number[1]
                for j in (i + 1, i + 2)
            ):
                remove.update((j, edge_pos) for j in (i, i + 1, i + 2))

    line_indices = {}
    for page_index, edge_pos in remove:
        lines, _ = rows[page_index]
        edge, offset = edge_pos
        line_indices.setdefault(page_index, set()).add(
            offset if edge == "top" else len(lines) - 1 - offset
        )
    removed = 0
    for page_index, indices in line_indices.items():
        lines, _ = rows[page_index]
        for line_index in sorted(indices, reverse=True):
            del lines[line_index]
            removed += 1
    return ["\n".join(lines) for lines, _ in rows], removed


def without_noise(words):
    """A line's (word, confidence) pairs with the gazette's running head and dotted-rule debris
    taken out, or [] when nothing is left.

    A dotted rule reads as a long run of a few letters ("чиитииинисининии…"), which no word is."""
    line = " ".join(w for w, _ in words)
    spans = running_header_spans(line)
    if spans:
        residual = line
        for start, end in reversed(spans):
            residual = residual[:start] + residual[end:]
        if len(re.findall(r"[A-Za-zА-Яа-яЃѓЌќЅѕЈјЉљЊњЏџ]", residual)) < 2:
            return []
    # The English model reads the pronoun I as a bar, which took every "I have the honour" and
    # "I hereby declare" out of RM-2008-18-14566. A single bar in an English line with a small
    # word after it is that I; a box's border has a bar on each side or stands before a capital.
    bars = [i for i, (w, _) in enumerate(words) if w == "|"]
    if (
        len(bars) == 1
        and bars[0] + 1 < len(words)
        and re.match(r"[a-z]", words[bars[0] + 1][0])
        and english([w for w, _ in words if w != "|"])
    ):
        words = [("I", c) if i == bars[0] else (w, c) for i, (w, c) in enumerate(words)]
    # Any other lone bar is the border of a boxed title, since no law prints one.
    words = [
        (w, c)
        for w, c in words
        if w not in ("|", "||", "¦") and not (len(w) >= 15 and len(set(w)) / len(w) < 0.4)
    ]
    ink = "".join(w for w, _ in words)
    # A line holding a digit is kept, since "2);" ending an item has more signs than letters.
    return (
        words
        if any(ch.isdigit() for ch in ink) or sum(ch.isalnum() for ch in ink) >= 0.5 * len(ink)
        else []
    )


# The language a treaty is printed in beside the Macedonian, taken from the partner named in the
# title. Each treaty is printed in Macedonian, the partner's language and usually English, and a
# model for the partner's language reads its letters (Romanian ă î ș ț, Turkish ğ ş ı, Albanian ë ç)
# where the English one cannot. Treaties with Arabic or Persian text name no model here, so that
# text is left out and its page listed as having unread lines.
PARTNER_LANGS = [
    ("Турци", ["tur"]),
    ("Албани", ["sqi"]),
    ("Косов", ["sqi", "srp", "srp_latn"]),
    ("Србиј", ["srp", "srp_latn"]),
    ("Босна", ["bos", "hrv", "srp_latn"]),
    ("Бугари", ["bul"]),
    ("Црна Гора", ["srp_latn", "srp"]),
    ("Молдова", ["ron", "rus"]),
    ("Романи", ["ron"]),
    ("Холанди", ["nld"]),
    ("Словени", ["slv"]),
    ("Руск", ["rus"]),
    ("Данск", ["dan"]),
    ("Полска", ["pol"]),
    ("Хрватск", ["hrv"]),
    ("Норвешк", ["nor"]),
    ("Литван", ["lit"]),
    ("Итали", ["ita"]),
    ("Азербејџан", ["aze", "rus"]),
    ("Казахстан", ["kaz", "rus"]),
    ("Словачк", ["slk"]),
    ("Унгари", ["hun"]),
    ("Франци", ["fra"]),
    ("Белорус", ["bel", "rus"]),
    ("Финск", ["fin"]),
    ("Латви", ["lav"]),
    ("Шпан", ["spa"]),
    ("Украин", ["ukr", "rus"]),
    ("Германи", ["deu"]),
    ("Чешк", ["ces"]),
    ("Грци", ["ell"]),
    ("Португал", ["por"]),
    ("Шведск", ["swe"]),
    ("Австри", ["deu"]),
    ("Швајцари", ["deu", "fra", "ita"]),
    ("Белгиј", ["nld", "fra"]),
    ("Луксембург", ["fra", "deu"]),
    ("Канад", ["fra"]),
    ("Естониј", ["est"]),
    ("Кипар", ["ell", "tur"]),
    ("Малта", ["mlt"]),
    ("Исланд", ["isl"]),
    ("Чиле", ["spa"]),
    ("Аргентин", ["spa"]),
    ("Мексик", ["spa"]),
    ("Куба", ["spa"]),
    ("Бразил", ["por"]),
    ("Монголиј", ["mon"]),
    ("Виетнам", ["vie"]),
    ("Индонезиј", ["ind"]),
    ("Узбекистан", ["uzb", "rus"]),
    ("Киргист", ["kir", "rus"]),
    ("Грузиј", ["kat"]),
    ("Ермениј", ["hye"]),
    ("Израел", ["heb"]),
    ("Иран", ["fas"]),
    ("Кина", ["chi_sim"]),
    ("Кинеск", ["chi_sim"]),
    ("Тајван", ["chi_tra"]),
    ("Јапониј", ["jpn"]),
    ("Кореј", ["kor"]),
    ("Индиј", ["hin"]),
    ("Тајланд", ["tha"]),
    ("Арапск", ["ara"]),
    ("Катар", ["ara"]),
    ("Кувајт", ["ara"]),
    ("Египет", ["ara"]),
    ("Саудиск", ["ara"]),
    ("Јордан", ["ara"]),
    ("Алжир", ["ara", "fra"]),
    ("Тунис", ["ara", "fra"]),
    ("Либан", ["ara", "fra"]),
    ("Оман", ["ara"]),
    ("Бахреин", ["ara"]),
    ("Либиј", ["ara"]),
    ("Ирак", ["ara"]),
    ("Сириј", ["ara"]),
    ("Палестин", ["ara"]),
    ("Мароко", ["ara", "fra"]),
]
# What tesseract's script detector names, and the models to try for it on a page that still has lines
# no model could read. The title names no partner in multilateral conventions, and a list of
# countries is never complete, so this catches what the title missed.
SCRIPT_LANGS = {
    "Arabic": ["ara", "fas"],
    "Hebrew": ["heb"],
    "Han": ["chi_sim", "chi_tra"],
    "Japanese": ["jpn"],
    "Hangul": ["kor"],
    "Devanagari": ["hin"],
    "Georgian": ["kat"],
    "Armenian": ["hye"],
    "Thai": ["tha"],
    "Greek": ["ell"],
    "Cyrillic": ["bul", "rus", "srp", "ukr"],
    "Latin": ["deu", "fra", "ita", "spa", "tur", "sqi", "ron", "hrv", "pol", "nld", "hun", "ces"],
}
# Letters of the Russian, Bulgarian and Belarusian alphabets that Macedonian does not have, so a
# line holding one is not Macedonian however well the Macedonian model reads the rest.
PARTNER_ONLY = re.compile("[ъщыэёў]")
CYRILLIC_PARTNERS = {"bul", "srp", "rus", "ukr", "bel", "kaz"}
PARTNERS = None


def partner_langs(doc_id, title=""):
    """Return OCR models for the treaty partner named in the LDBIS title."""
    langs = []
    for stem, models in PARTNER_LANGS:
        if stem in title:
            langs += [model for model in models if model not in langs]
    return langs


def ocr_page(args):
    """OCR one scanned page, receiving paths explicitly for worker processes."""
    doc_id, page_number, pdf_path, output_dir, tessdata, title = args
    import numpy as np
    import pypdfium2

    page = pypdfium2.PdfDocument(pdf_path)[page_number].render(scale=300 / 72).to_pil().convert("L")
    (kept, unread), tables = read_with_tables(
        np.array(page), f"{output_dir}/{page_number}.png", partner_langs(doc_id, title), tessdata
    )
    confs = [
        confidence
        for pairs in kept
        for word, confidence in pairs
        if not word.startswith(TABLE_MARK)
    ]
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    with open(f"{output_dir}/{page_number}.json", "w", encoding="utf-8") as out:
        json.dump(
            {
                "version": OCR_VERSION,
                "lines": [[[word, round(conf)] for word, conf in pairs] for pairs in kept],
                "words": len(confs),
                "unread_lines": unread,
                "confidence": round(sum(confs) / len(confs), 1) if confs else 0,
                "doubtful_lines": sum(
                    sum(c for _, c in pairs) / len(pairs) < DOUBTFUL_LINE for pairs in kept
                ),
                "columns": PAGE_NOTES.get("columns", 1),
                "dropped": PAGE_NOTES.get("dropped", []),
                "tables": [
                    [
                        [
                            [[[word, round(conf)] for word, conf in pairs] for pairs in cell]
                            for cell in row
                        ]
                        for row in table
                    ]
                    for table in tables
                ],
            },
            out,
            ensure_ascii=False,
        )


def gutter(gray):
    """The fraction of the page width where two text columns part, or None for a single column.

    Read as one block, tesseract runs straight across both columns of a gazette page and
    interleaves their lines. The gutter is a narrow strip in the middle third that is empty on
    nearly every text row, with a solid block of text on each side; a heading across both
    columns leaves a few marks in it, so the strip may hold up to an eighth of the ink of a
    typical column. Measured on 3425, 2554 and 18729, whose columns are found, and 4518 and
    7598, whose single columns are not."""
    import cv2
    import numpy as np

    ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    ink = cv2.resize(ink, None, fx=1 / 6, fy=1 / 6, interpolation=cv2.INTER_AREA) > 60
    ink = ink[ink.sum(axis=1) > 2]
    if len(ink) < 20:
        return None
    profile = ink.sum(axis=0).astype(float)
    width = len(profile)
    typical = np.median(profile[profile > 0]) if (profile > 0).any() else 0
    strip = max(3, int(width * 0.008))
    best = min(
        range(int(width * 0.3), int(width * 0.7) - strip),
        key=lambda x: profile[x : x + strip].mean(),
        default=None,
    )
    if not typical or best is None:
        return None
    middle = best + strip // 2
    left, right = profile[:middle].sum(), profile[middle:].sum()
    gap = profile[best : best + strip].mean()
    # A short page with small print has a thin typical column, so a heading and closing line across
    # both columns (332, page 4) weigh more there; few of its text rows crossing the gap still
    # mark it. Every single column page measured had at least 0.45 and 0.088 (31 October 2026).
    if (gap <= 0.12 * typical or (gap <= 0.3 * typical and gap <= 0.07 * len(ink))) and min(
        left, right
    ) >= 0.3 * (left + right):
        return middle / width
    return None


# A table's place among a page's cached lines: a line holding only this mark and the table's
# number, which the page's "tables" hold the cells of.
TABLE_MARK = "\ue000"


def ruled_tables(gray):
    """The ruled tables on a 300 dpi page, each a list of its cells as (x, y, w, h).

    A cell is a region the page's rules enclose that is much smaller than the page, and a table is
    four or more cells on one connected set of rules, so a frame round the page, a boxed heading or
    a box round a paragraph is not one. Ruling lines are found at 100 dpi, where on 840 LDBIS PDFs
    a scan's ragged margin, a copier's edge and a framed title found none while the security
    agreements' classification tables (10930, 17003, 18006) and 2003's emission limits (20429)
    were all found (4 November 2026). A column whose outer rule was never drawn, as the last of
    RM-2008-18-14566's audit sheets on pages 45 and 103, encloses nothing; where a table's rules
    run on past its last closed cell, that strip is one more column, cut at the rows of the
    column beside it. A pale grid printed behind a page's text (RSM-2024-170-67511, page 12) is
    no table: on 600 pages compared, the two such grids had rules of a median gray of 244 and 245,
    printed rules 100 to 171 and grey ones 213 to 219, so a table's rules must be darker than 235."""
    import cv2
    import numpy as np

    small = cv2.resize(gray, None, fx=1 / 3, fy=1 / 3, interpolation=cv2.INTER_AREA)
    height, width = small.shape
    ink = cv2.adaptiveThreshold(~small, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2)
    across = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (width // 25, 1))
    )
    down = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, height // 60))
    )
    rules = cv2.dilate(across | down, np.ones((3, 3), np.uint8))
    contours, hierarchy = cv2.findContours(rules, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    tables = {}
    for contour, (_, _, _, parent) in zip(
        contours, hierarchy[0] if hierarchy is not None else [], strict=True
    ):
        x, y, w, h = cv2.boundingRect(contour)
        if (
            parent >= 0
            and w * h < 0.25 * width * height
            and w > 0.015 * width
            and h > 0.008 * height
            and cv2.contourArea(contour) > 0.8 * w * h
        ):
            tables.setdefault(parent, []).append((3 * x, 3 * y, 3 * w, 3 * h))
    found = []
    lines = (across | down) > 0
    for parent, cells in tables.items():
        if len(cells) < 4:
            continue
        x, y, w, h = cv2.boundingRect(contours[parent])
        if np.median(small[y : y + h, x : x + w][lines[y : y + h, x : x + w]]) > 235:
            continue
        found.append(cells + open_column(cells, 3 * x, 3 * (x + w), 3 * int(0.015 * width)))
    return sorted(
        found, key=lambda cells: (min(y for _, y, _, _ in cells), min(x for x, _, _, _ in cells))
    )


def open_column(cells, rules_left, rules_right, narrowest):
    """The cells of a first or last column that has rules above and below but none at its outer
    side, as (x, y, w, h): the rows of the closed column beside it, run out to where the rules end."""
    added = []
    left = min(x for x, _, _, _ in cells)
    right = max(x + w for x, _, w, _ in cells)
    if rules_right - right > narrowest:
        added += [
            (x + w, y, rules_right - x - w, h) for x, y, w, h in cells if right - (x + w) < 30
        ]
    if left - rules_left > narrowest:
        added += [(rules_left, y, x - rules_left, h) for x, y, w, h in cells if x - left < 30]
    return added


def table_grid(cells):
    """The cells laid out in rows and columns by where their edges fall, None where a cell spans
    from its left or above."""
    tolerance = 30  # a tenth of an inch at 300 dpi; rules drawn by hand wander that much

    def edges(values):
        found = []
        for value in sorted(values):
            if not found or value - found[-1] > tolerance:
                found.append(value)
        return found

    lefts = edges(x for x, _, _, _ in cells)
    tops = edges(y for _, y, _, _ in cells)
    grid = [[None] * len(lefts) for _ in tops]
    for cell in cells:
        row = min(range(len(tops)), key=lambda i: abs(tops[i] - cell[1]))
        column = min(range(len(lefts)), key=lambda i: abs(lefts[i] - cell[0]))
        grid[row][column] = cell
    return [row for row in grid if any(row)]


def read_cell(gray, cell, png, langs, tessdata):
    """The (word, confidence) lines of one cell, in whichever of the page's models read it most
    surely, a reading whose every word is a known Macedonian or English word first.

    One model per cell, never a mix: read with Macedonian and English at once, the English
    column of RM-2006-10-10930's classification table came out as "ТОР 5ЕСКЕТ". The English
    model was also the surer one of "СТРОГО СЕКРЕТНО" on its page 24, read as "CTPOI'O CEKPETHO",
    which is why a reading of known words wins."""
    import cv2

    x, y, w, h = cell
    inner = gray[y + 6 : y + h - 6, x + 6 : x + w - 6]
    if inner.size == 0 or (inner < 128).sum() < 30:
        return []
    inner = cv2.resize(inner, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    cv2.imwrite(png, cv2.copyMakeBorder(inner, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255))
    readings = []
    for lang in ["mkd", "eng", *langs]:
        # A word that is a bar and marks only is the cell's own rule (page 24's "“|").
        lines = [
            pairs
            for ln in tesseract_lines(png, lang, "6", tessdata)
            if (
                pairs := without_noise(
                    [
                        (word, conf)
                        for word, conf in zip(ln["words"], ln["confs"], strict=True)
                        if not re.fullmatch(r"[^\w|]*\|[^\w]*", word)
                    ]
                )
            )
        ]
        confs = [conf for pairs in lines for _, conf in pairs]
        readings.append((known_words(lines), sum(confs) / len(confs) if confs else 0.0, lines))
    os.remove(png)
    return max(readings, key=lambda reading: reading[:2])[2]


def known_words(lines) -> bool:
    """Whether a cell's reading has a word of four letters or more and every such word is a known
    Macedonian or English word."""
    vocab()
    english([])
    cores = [
        core
        for pairs in lines
        for word, _ in pairs
        if len(core := re.sub(r"\W|\d|_", "", word).casefold()) >= 4
    ]
    return bool(cores) and all(core in VOCAB or core in ENGLISH_WORDS for core in cores)


def open_tables(gray, taken=()):
    """The tables on a 300 dpi page that are drawn with rules across only, as grids of cell boxes.

    Older treaties set a table between three rules, one above its header, one under it and one at
    its end, with nothing between the columns: the lists of psychotropic substances in the 1971
    convention (LDBIS 623, page 22) print French and Macedonian tables side by side that way. Its
    columns are the gutters that stay empty from the header to the last row, and at least three
    are needed, so a page of two column text between two rules is never one. A row ends at a gap
    clearly wider than the gap between the lines of one entry; where every gap is alike, every
    line is a row. Areas a ruled table already holds ("taken") are left to it."""

    height, width = gray.shape
    rules, text = long_rules(gray)
    tables, used = [], set()
    for i, (top, x0, x1) in enumerate(rules):
        same = [
            rule
            for rule in rules[i + 1 :]
            if abs(rule[1] - x0) < width // 50 and abs(rule[2] - x1) < width // 50
        ]
        if i in used or len(same) < 2:
            continue
        (head, *_), (bottom, *_) = same[0], same[1]
        if not (30 < head - top < height // 12 and bottom - head > head - top):
            continue
        if x1 - x0 < width // 4 or any(
            tx < x1 and x0 < tx + tw and ty < bottom and top < ty + th for tx, ty, tw, th in taken
        ):
            continue
        # A form's lines to write on cross its body; a table's body has no rule across it.
        if any(head < y < bottom and min(x1, b) - max(x0, a) > (x1 - x0) // 2 for y, a, b in rules):
            continue
        edges = text_columns(text[top + 8 : bottom - 8, x0:x1])
        if len(edges) < 3:
            continue
        body = text[head + 8 : bottom - 8, x0:x1]
        rows = entry_rows(body, edges[0])
        header = text[top + 8 : head - 4, x0:x1]

        def inked(part, left, right):
            return (part[:, left:right] > 0).sum() > 40

        # A header names at least two of the columns, and at least two columns run down most of
        # the rows; dotted lines on a form make gutters, but no header and no filled columns.
        if (
            len(rows) < 2
            or sum(inked(header, left, right) for left, right in edges) < 2
            or sum(
                sum(inked(body[a : b + 1], left, right) for a, b in rows) * 2 >= len(rows)
                for left, right in edges
            )
            < 2
        ):
            continue
        spans = [(top + 8, head - 4)] + [(head + 8 + a - 6, head + 8 + b + 6) for a, b in rows]
        tables.append(
            [
                [(x0 + left - 6, y0, right - left + 12, y1 - y0) for left, right in edges]
                for y0, y1 in spans
            ]
        )
        used.update(i + 1 + j for j, rule in enumerate(rules[i + 1 :]) if rule in same[:2])
    return tables


def entry_rows(body, first_column):
    """The (top, bottom) spans of a table body's rows, from its ink mask.

    Entries set with a hanging indent, a number at the first column's edge and the rest of the
    name indented under it ("1. AMPHE-" over "TAMINE"), start a row wherever a line starts at that
    edge. Otherwise a row ends at a gap clearly wider than the gap between lines of one entry, and
    where every gap is alike every line is a row."""
    import numpy as np

    # A row of pixels belongs to a line of text when it crosses more ink than a few specks do.
    filled = np.flatnonzero((body > 0).sum(axis=1) > max(2, body.shape[1] // 100))
    if not len(filled):
        return []
    lines, run = [], [filled[0], filled[0]]
    for y in filled[1:]:
        if y - run[1] > 3:
            lines.append(tuple(run))
            run = [y, y]
        else:
            run[1] = y
    lines.append(tuple(run))
    left, right = first_column
    starts = []
    for top, bottom in lines:
        # A speck of dirt before a line is not where it starts: a letter's stroke is three
        # pixels of its height at least.
        ink = np.flatnonzero((body[top : bottom + 1, left:right] > 0).sum(axis=0) >= 3)
        starts.append(left + ink[0] if len(ink) else None)
    edge = min((x for x in starts if x is not None), default=None)
    at_edge = [x is not None and x - edge < 15 for x in starts]
    if edge is not None and at_edge[0] and 1 < sum(at_edge) < len(lines):
        new_row = at_edge
    else:
        gaps = [after[0] - before[1] for before, after in zip(lines, lines[1:], strict=False)]
        cut = 1.5 * min(gaps) if gaps and max(gaps) > 1.6 * min(gaps) else 0
        new_row = [True] + [gap > cut for gap in gaps]
    rows = []
    for (top, bottom), new in zip(lines, new_row, strict=True):
        if new or not rows:
            rows.append([top, bottom])
        else:
            rows[-1][1] = bottom
    return [tuple(row) for row in rows]


def text_columns(ink):
    """The (left, right) spans of an ink mask's columns of text, split at gutters.

    A column of the scan is blank when it holds no more ink than its specks of dirt, and a gutter
    is two millimetres of blank at 300 dpi, a speck narrower than a millimetre inside it ignored."""
    blank = list((ink > 0).sum(axis=0) <= max(2, ink.shape[0] // 66))
    runs, start = [], 0
    for x in range(1, len(blank) + 1):
        if x == len(blank) or blank[x] != blank[start]:
            runs.append([blank[start], start, x])
            start = x
    for k in range(1, len(runs) - 1):
        if not runs[k][0] and runs[k][2] - runs[k][1] < 10 and runs[k - 1][0] and runs[k + 1][0]:
            runs[k][0] = True
    merged = []
    for run in runs:
        if merged and merged[-1][0] == run[0]:
            merged[-1][2] = run[2]
        else:
            merged.append(run)
    runs = merged
    columns, start = [], None
    for k, (blank_run, left, right) in enumerate(runs):
        gutter = blank_run and (right - left >= 24 or k in (0, len(runs) - 1))
        if not gutter and start is None:
            start = left
        elif gutter and start is not None:
            columns.append((start, left))
            start = None
    if start is not None:
        columns.append((start, len(blank)))
    return columns


def table_box(grid):
    """The box round a grid of cells, as (x0, y0, x1, y1)."""
    cells = [cell for row in grid for cell in row if cell]
    return (
        min(x for x, _, _, _ in cells),
        min(y for _, y, _, _ in cells),
        max(x + w for x, _, w, _ in cells),
        max(y + h for _, y, _, h in cells),
    )


def long_rules(gray):
    """A 300 dpi page's rules across, as (y, left, right), and its ink with them taken out."""
    import cv2
    import numpy as np

    height, width = gray.shape
    ink = cv2.adaptiveThreshold(~gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 45, -6)
    across = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (width // 8, 1))
    )
    count, _, stats, _ = cv2.connectedComponentsWithStats(across)
    rules = sorted((y + h // 2, x, x + w) for x, y, w, h, _ in stats[1:count] if h < height // 150)
    return rules, ink & ~cv2.dilate(across, np.ones((7, 7), np.uint8))


def page_tables(gray):
    """Every table on a page as (grid of cell boxes, (x0, y0, x1, y1) the table covers).

    A form's ruled table often finds cells for its header only, its empty rows below drawn as
    rules with short ticks between the columns (the review sheets of RM-2008-18-14566, page 45).
    Those rows are part of the table, so it reaches down over the rules of its own width that
    follow it; read as text they were noise, and they framed the footnotes under them as a table
    of their own."""
    rules, _ = long_rules(gray)
    tables = []
    for cells in ruled_tables(gray):
        grid = table_grid(cells)
        x0, y0, x1, y1 = table_box(grid)
        for y, left, right in rules:
            if y1 - 10 < y < y1 + 120 and left < x0 + 60 and right > x1 - 60:
                y1 = y
        tables.append((grid, (x0, y0, x1, y1 + 5)))
    taken = [(x0, y0, x1 - x0, y1 - y0) for _, (x0, y0, x1, y1) in tables]
    return tables + [(grid, table_box(grid)) for grid in open_tables(gray, taken)]


def read_with_tables(gray, png, langs, tessdata):
    """read_image's lines and unread count for a page, with each table read cell by cell in its
    place: the text above a table is read as a page of its own, then the table, then on.

    Read as text, a table's cells ran together across its columns ("ДРЖАВНА ТАЈНА TOP SECRET
    STROGO TAJNO") and the cells' own line breaks interleaved, so the corpus had no table at all."""
    import numpy as np

    tables = page_tables(gray)
    if not tables:
        return read_image(gray, png, langs, tessdata), []
    # A table too wide for the page is printed sideways with its caption (the review sheets of
    # RM-2008-18-14566, pages 45 and 103), so the page is turned upright before it is cut up.
    turns = {"90": 3, "180": 2, "270": 1}.get(osd(gray, png, tessdata).get("Rotate"))
    if turns:
        gray = np.ascontiguousarray(np.rot90(gray, turns))
        tables = page_tables(gray)
    lines, unread, read_tables, notes = [], 0, [], {"columns": 1, "dropped": []}

    def read_text(part):
        nonlocal unread
        if part.shape[0] < 40 or (part < 128).sum() < 0.002 * part.size:
            return
        kept, missed = read_image(part, png, langs, tessdata)
        lines.extend(kept)
        unread += missed
        notes["columns"] = max(notes["columns"], PAGE_NOTES.get("columns", 1))
        notes["dropped"] += PAGE_NOTES.get("dropped", [])

    bands = []
    for grid, box in sorted(tables, key=lambda table: table[1][1]):
        _, top, _, bottom = box
        if bands and top < bands[-1][1]:
            bands[-1] = (bands[-1][0], max(bands[-1][1], bottom), bands[-1][2] + [(grid, box)])
        else:
            bands.append((top, bottom, [(grid, box)]))
    above = 0
    for top, bottom, group in bands:
        read_text(gray[above:top])
        beside = gray[top:bottom].copy()
        for grid, (x0, _, x1, _) in sorted(group, key=lambda table: table[1][0]):
            lines.append([(f"{TABLE_MARK}{len(read_tables)}", 100)])
            read_tables.append(
                [
                    [read_cell(gray, cell, png, langs, tessdata) if cell else [] for cell in row]
                    for row in grid
                ]
            )
            beside[:, x0:x1] = 255
        # Text printed beside a table, in the other column of a two column page.
        read_text(beside)
        above = bottom
    read_text(gray[above:])
    PAGE_NOTES.update(notes)
    return (lines, unread), read_tables


def with_tables(text, tables):
    """A page's text with each table mark replaced by its table in pipe rows, the first row taken
    as the header, as LDBIS tables print theirs."""
    from legalize.fetcher.mk.parser import _table_to_markdown

    out = []
    for line in text.split("\n"):
        if not line.startswith(TABLE_MARK):
            out.append(line)
            continue
        rows = [
            [corrected(cell) if cell else "" for cell in row]
            for row in tables[int(line[len(TABLE_MARK) :])]
        ]
        if markdown := _table_to_markdown(rows):
            out += [markdown, PARAGRAPH]
    return "\n".join(out)


def drawn_rows(rows):
    """pdfplumber's table rows with the rows a table printed without rules between them split
    apart: the pension law's yearly percentages (RM-2012-98-25996) came out as one row whose cells
    each held every year. A row is split only when each filled cell holds the same three or more
    lines, since a heading wrapped over two lines is one cell."""
    out = []
    for row in rows:
        cells = [(cell or "").strip() for cell in row]
        counts = {len(cell.split("\n")) for cell in cells if cell}
        if len(counts) == 1 and (lines := counts.pop()) >= 3 and sum(map(bool, cells)) > 1:
            parts = [cell.split("\n") if cell else [""] * lines for cell in cells]
            out.extend([part[i] for part in parts] for i in range(lines))
        else:
            out.append(cells)
    return out


def text_page(page):
    """A text-layer page's text with each table pdfplumber finds on it in pipe rows, in its place.

    A table is kept only when its cells hold every character printed inside it: on the same
    pension law, a cell boundary cut two of twelve percentages off, and the plain text that keeps
    them is the better copy. The text around a table takes only the letters wholly outside it, since
    a row touching the table's edge is already one of its rows."""
    from collections import Counter

    from legalize.fetcher.mk.parser import _table_to_markdown

    page = without_stray_spaces(page)
    parts, top = [], 0
    for table in sorted(page.find_tables(), key=lambda table: table.bbox[1]):
        x0, table_top, x1, bottom = table.bbox
        rows = drawn_rows(table.extract())
        printed = Counter(c["text"] for c in page.crop(table.bbox).chars if c["text"].strip())
        held = Counter(ch for row in rows for cell in row for ch in cell if ch.strip())
        if table_top < top or printed != held or not (markdown := _table_to_markdown(rows)):
            continue
        if table_top > top:
            parts.append(page.within_bbox((0, top, page.width, table_top)).extract_text() or "")
        parts += [markdown, PARAGRAPH]
        beside = page.within_bbox((0, table_top, page.width, bottom)).outside_bbox(table.bbox)
        parts.append(beside.extract_text() or "")
        top = bottom
    parts.append(page.within_bbox((0, top, page.width, page.height)).extract_text() or "")
    return "\n".join(part for part in parts if part)


PAGE_NOTES = {}


def read_image(gray, png, langs=(), tessdata=""):
    """The (word, confidence) lines of a 300 dpi greyscale page, column by column, and how many
    lines in another language could not be read.

    A page read with low confidence is read again darkened, and the darker reading kept when the
    model is surer of it. Some scans are printed in pale grey, where 2013's Chinese treaty (27488)
    came out as Cyrillic noise and its Macedonian at half confidence; darkened, both read.

    A doubtful page is also turned upright when the orientation detector says it lies on its side.
    A landscape table printed sideways (64161, the peace force's unit charts) read as marks, its
    headings with it; turned, they read word for word.

    A doubtful page is last read as a ruled table, its rules cleared more widely, and cell by
    cell. Read as text, 2011's tariff quotas (23196) came out as "ГЕКЕа заез озњеИ" across the
    columns. The cell reading can score higher by reading less, so it is kept only when it also
    has more words it is sure of."""
    import numpy as np

    best = read_page(gray, png, langs, tessdata=tessdata)
    if page_confidence(best[0]) >= DOUBTFUL_PAGE:
        return best
    turns = {"90": 3, "180": 2, "270": 1}.get(osd(gray, png, tessdata).get("Rotate"))
    upright = np.ascontiguousarray(np.rot90(gray, turns)) if turns else gray
    tries = [(upright, "block")] if turns else []
    tries += [
        ((255 * (gray / 255.0) ** 3).astype("uint8"), "block"),
        (upright, "ruled"),
        (upright, "cells"),
    ]
    for image, mode in tries:
        notes = dict(PAGE_NOTES)
        reading = read_page(image, png, langs, mode, tessdata)
        if page_confidence(reading[0]) > page_confidence(best[0]) and (
            mode != "cells" or sure_words(reading[0]) > sure_words(best[0])
        ):
            best = reading
        else:
            PAGE_NOTES.update(notes)
    return best


SURE_WORD = 70


def sure_words(lines):
    """How many words of a reading the model is at least SURE_WORD % sure of."""
    return sum(c >= SURE_WORD for pairs in lines for _, c in pairs)


def page_confidence(lines):
    confs = [c for line in lines for _, c in line]
    return sum(confs) / len(confs) if confs else 0


def read_page(gray, png, langs, mode="block", tessdata=""):
    gray = straightened(gray)
    split = gutter(gray)
    PAGE_NOTES.update(columns=2 if split else 1, dropped=[])
    first = read_columns(gray, png, langs, split, mode, tessdata)
    if not first[1]:
        return first
    extra = [
        lang for lang in SCRIPT_LANGS.get(script(gray, png, tessdata), []) if lang not in langs
    ]
    if not extra:
        return first
    notes = dict(PAGE_NOTES)
    PAGE_NOTES.update(dropped=[])
    second = read_columns(gray, png, list(langs) + extra, split, mode, tessdata)
    if second[1] < first[1]:
        return second
    PAGE_NOTES.update(notes)
    return first


def read_columns(gray, png, langs, split, mode, tessdata=""):
    if split is None:
        return read_column(gray, png, langs, mode, tessdata)
    x = int(gray.shape[1] * split)
    left, right = (
        read_column(gray[:, :x], png, langs, mode, tessdata),
        read_column(gray[:, x:], png, langs, mode, tessdata),
    )
    return left[0] + right[0], left[1] + right[1]


def script(gray, png, tessdata=""):
    """The script tesseract's detector sees most of on a page, such as "Arabic" or "Latin"."""
    return osd(gray, png, tessdata).get("Script")


def osd(gray, png, tessdata=""):
    """Tesseract's orientation and script detector's findings, such as {"Rotate": "90", "Script": "Latin"}."""
    import cv2

    cv2.imwrite(png, gray)
    env = {**os.environ, "TESSDATA_PREFIX": tessdata, "OMP_THREAD_LIMIT": "1"}
    out = subprocess.run(
        ["tesseract", png, "-", "--psm", "0", "-l", "osd"], capture_output=True, text=True, env=env
    ).stdout
    os.remove(png)
    return dict(re.findall(r"^([\w ]+): (\S+)$", out, re.M))


COLUMN_MARGIN = 8
COLUMN_SURE = 60


def column_confidence(lines):
    """The mean word confidence of a reading of a column, 0 for an empty one."""
    confs = [c for ln in lines for c in ln["confs"]]
    return sum(confs) / len(confs) if confs else 0


def read_column(gray, png, langs, mode, tessdata=""):
    """The (word, confidence) lines of one column of text, with png as the scratch file. The mode
    is "block" for text, "ruled" for a table whose rules are cleared more widely, and "cells" for
    a table read cell by cell."""
    import cv2

    cv2.imwrite(png, without_rules(gray, wide=mode == "ruled"))
    psm = "11" if mode == "cells" else "3"
    mkd, eng = (
        [with_ones(ln) for ln in tesseract_lines(png, "mkd", psm, tessdata)],
        tesseract_lines(png, "eng", psm, tessdata),
    )
    partner = [(lang, tesseract_lines(png, lang, psm, tessdata)) for lang in langs]
    os.remove(png)
    # A column printed in one language is read by the model for that language. The Macedonian model
    # reads Romanian as "теш иштетејог, есшратепе|ог" at about 55 % sure, where the Romanian model
    # is 85 % sure of the same lines, and a mixed column has no such clear winner.
    best_lang = max([("eng", eng)] + partner, key=lambda c: column_confidence(c[1]))[1]
    if column_confidence(best_lang) >= max(column_confidence(mkd) + COLUMN_MARGIN, COLUMN_SURE):
        return [
            pairs
            for ln in best_lang
            if (pairs := without_noise(list(zip(ln["words"], ln["confs"], strict=True))))
        ], 0
    lines, used, unread = [], set(), 0
    for ln in mkd:
        match = next((i for i, alt in enumerate(eng) if same_line(ln, alt)), None)
        others = [(lang, alt) for lang, lst in partner for alt in lst if same_line(ln, alt)]
        # A line in the partner's Cyrillic (Bulgarian, Russian) is read by the Macedonian model
        # almost as well, so it is told apart by the letters only those alphabets have.
        own = next(
            (
                alt
                for lang, alt in others
                if lang in CYRILLIC_PARTNERS
                and PARTNER_ONLY.search(" ".join(alt["words"]))
                and alt["conf"] >= ln["conf"] - 5
            ),
            None,
        )
        best = max(
            ([eng[match]] if match is not None else []) + [alt for _, alt in others],
            key=lambda a: a["conf"],
            default=None,
        )
        if own is not None:
            lines.append(own)
        elif match is None and best is None:
            if foreign(ln["words"]):
                unread += 1
                PAGE_NOTES["dropped"].append(" ".join(ln["words"]))
            else:
                lines.append(ln)
        elif (
            best is not None
            and best["conf"] >= max(ln["conf"], LATIN_SURE)
            and foreign(ln["words"])
        ):
            # A partner's language in Latin letters, German or Slovak, which the English model reads
            # far better than the Macedonian one. A faded Macedonian line read as "олнаси намеѓ, рот
            # екји" is no known Macedonian either, but its English reading was 3 to 32 % sure.
            lines.append(best)
        elif foreign(ln["words"]):
            # Another language neither model reads with confidence. Its Cyrillic guess is not
            # published, since the spec forbids text the publisher cannot place, and the page is
            # listed as having unread lines instead.
            unread += 1
            PAGE_NOTES["dropped"].append(" ".join(ln["words"]))
        elif match is None:
            lines.append(ln)
        elif eng[match]["conf"] < ln["conf"] + ENGLISH_MARGIN or not english(eng[match]["words"]):
            lines.append(with_signs(ln, eng[match]))
        elif match not in used:
            # Tesseract may split one English line in two in one reading, so it is taken once.
            lines.append(merged_line(ln, eng[match]))
            used.add(match)
        else:
            lines.append(with_signs(ln, eng[match]))
    return [
        pairs
        for ln in lines
        if (pairs := without_noise(list(zip(ln["words"], ln["confs"], strict=True))))
    ], unread


BAR_ONE = re.compile(r"(?<=\d)\||\|(?=[\d.)])")


def with_ones(ln):
    """A Macedonian reading with its bars made ones and its low double commas made „.

    The model writes the digit 1 as a bar, inside a number ("до 3| октомври"), as a word of its
    own after one ("Членот 5 | се брише" for 51) and alone ("точка | по"), and no law prints a bar.
    It runs before the English numbers are compared, which once made that 51 into 511."""
    words, confs, spans = [], [], []
    for w, c, s in zip(ln["words"], ln["confs"], ln["spans"], strict=True):
        w = BAR_ONE.sub("1", w).replace(",„,", "„").replace(",,", "„")
        if w == "|" and words and words[-1][-1:].isdigit():
            words[-1], confs[-1], spans[-1] = (
                words[-1] + "1",
                min(confs[-1], c),
                (spans[-1][0], s[1]),
            )
            continue
        words.append("1" if w == "|" else w)
        confs.append(c)
        spans.append(s)
    return {**ln, "words": words, "confs": confs, "spans": spans}


MK_LETTERS = "абвгдѓежзѕијклљмнњопрстќуфхцчџш"
MK_WORD = re.compile(rf"^[{MK_LETTERS}]+$", re.I)
LATIN = re.compile("[A-Za-z]")
VOCAB = None
CORRECTIONS = []  # (before, after, confidence) of every change, kept so a run can be reviewed


def vocab():
    """Macedonian word counts from tools/mk_vocab.py, leaving out words seen fewer than three times,
    which in Wikipedia are mostly typos, but keeping every word printed in a clean law.

    Without the law words the corrector turned real legal terms into commoner neighbours, such as
    "нејавна" into "нејасна" and "применливата" into "променливата"."""
    global VOCAB, SEEN, LAW_WORDS
    if VOCAB is None:
        VOCAB, SEEN = {}, set()
        LAW_WORDS = set(
            gzip.open(ASSET_ROOT / "mk_law_words.txt.gz", "rt", encoding="utf-8").read().split()
        )
        for row in gzip.open(ASSET_ROOT / "mk_words.tsv.gz", "rt", encoding="utf-8"):
            w, c = row.rstrip("\n").split("\t")
            (VOCAB.__setitem__(w, int(c)) if int(c) >= 3 else SEEN.add(w))
        for w in LAW_WORDS:
            VOCAB.setdefault(w, 1)
    return VOCAB


# Words seen only once or twice. Too rare to be offered as a correction, but a word that turns up
# anywhere is real far more often than not: holding each clean law out of the vocabulary, the
# corrector "fixed" rare terms such as "неизбор" and "нејавна" that Wikipedia had once or twice.
SEEN = set()
LAW_WORDS = set()  # every word printed in a clean law


# A word tesseract was at least this sure of is left as read: on the clean 2018 scan nearly every
# unknown word it read at 90 or more was a real word the vocabulary lacks ("загушувања", "црпни").
SURE = 90


def one_letter_swaps(word):
    """Every spelling with one letter replaced or two neighbours swapped. A letter added or dropped
    is not tried, since those "fixes" mostly ate a real letter ("Членб" lost article 6's number)."""
    return {word[:i] + ch + word[i + 1 :] for i in range(len(word)) for ch in MK_LETTERS} | {
        word[:i] + word[i + 1] + word[i] + word[i + 2 :] for i in range(len(word) - 1)
    }


# The letter pairs the model mixes up on worn scans: the swaps the corrector made most often on
# 681 OCR'd pages (31 October 2026). Where the model was sure of a word, or the word is short,
# only these are trusted, since a free swap there turns real words into commoner ones.
CONFUSED = {
    frozenset(p)
    for p in (
        "лд",
        "се",
        "вн",
        "ин",
        "пн",
        "ос",
        "кн",
        "мн",
        "гт",
        "пц",
        "пд",
        "хк",
        "џц",
        "пл",
        "нл",
        "пр",
        "тл",
        "тп",
        "шн",
        "зв",
    )
}


def confusion_swaps(word):
    return {
        word[:i] + b + word[i + 1 :]
        for i, a in enumerate(word)
        for pair in CONFUSED
        if a in pair
        for b in pair - {a}
    }


def clear_winner(candidates, least):
    """The most common known word among candidates when it is seen at least `least` times and ten
    times more often than the runner-up, and is a word printed in a clean law."""
    words = vocab()
    found = sorted(((words[c], c) for c in candidates if c in words), reverse=True)
    if (
        found
        and found[0][0] >= least
        and (len(found) == 1 or found[0][0] >= 10 * found[1][0])
        and found[0][1] in LAW_WORDS
    ):
        return found[0][1]
    return None


def spelling_fix(word, conf, macedonian, upper=False):
    """The word a misread one should be, or None. Any word of four letters or more tesseract was
    unsure of gets the nearest common spelling. On a Macedonian line three more cases are fixed
    with confused letters only: a word the model was sure of ("Договар"), a short word whose
    neighbour is hundreds of times commoner ("сс"), and a long word with two letters wrong.

    These three only ever produce a word printed in a clean law. Wikipedia lacks real words such
    as "порези" and "датувањето", which were otherwise "fixed" into "потези" and "патувањето"."""
    words = vocab()
    known = word in words or word in SEEN
    if len(word) >= 4 and not known and conf < SURE:
        return best_spelling(word)
    if not macedonian:
        return None
    if len(word) >= 4 and not known:
        fix = best_spelling(word)
        if fix and words[fix] >= 100 and fix in confusion_swaps(word) and fix in LAW_WORDS:
            return fix
        if len(word) >= 6 and not fix:
            return clear_winner(
                {c for s in confusion_swaps(word) for c in confusion_swaps(s)} - {word}, 100
            )
    # A short word in capitals is an abbreviation more often than a misreading ("РО", работна организација).
    if len(word) <= 3 and not upper:
        fix = clear_winner(confusion_swaps(word), 1000)
        if fix and words[fix] >= SHORT_RATIO * max(words.get(word, 0), 1):
            return fix
    return None


# How much commoner a short word's neighbour must be before the word is taken for a misreading.
SHORT_RATIO = 200


def best_spelling(word):
    """The known word one letter away from an unknown one, when one clearly beats every other:
    seen at least ten times and ten times more often than the runner-up."""
    words = vocab()
    found = sorted(((words[c], c) for c in one_letter_swaps(word) if c in words), reverse=True)
    if found and found[0][0] >= 10 and (len(found) == 1 or found[0][0] >= 10 * found[1][0]):
        return found[0][1]
    return None


def same_case(src, word):
    return (
        word.upper()
        if src.isupper() and len(src) > 1
        else word.capitalize()
        if src[0].isupper()
        else word
    )


CAPITALS = None
MID_SENTENCE = re.compile(rf"[{MK_LETTERS},]$")


def lowered(tokens):
    """A line's words with a capital the model misread put back in lower case.

    The model reads a small letter as its capital when the two differ only in size, so "јавен" came
    out as "Јавен" in the middle of a sentence. A word is lowered only after a small letter or a
    comma on the same line, and only when Macedonian Wikipedia writes it in lower case there at
    least twenty times as often, which keeps the capitals of names ("Јован", "Скопје").

    Only Ј is lowered, the one letter whose capital is its small form drawn larger. Lowering any
    capital took the capitals off the institutions laws name mid-sentence ("Основното јавно
    обвинителство", "Влада"), which Wikipedia writes in lower case as ordinary words."""
    global CAPITALS
    if CAPITALS is None:
        CAPITALS = {}
        for row in gzip.open(ASSET_ROOT / "mk_capitals.tsv.gz", "rt", encoding="utf-8"):
            w, low, cap = row.rstrip("\n").split("\t")
            if int(low) >= 20 and int(low) >= 20 * int(cap):
                CAPITALS[w] = True
    out = list(tokens)
    for i in range(1, len(out)):
        m = re.match(r"^(\W*)(.*?)(\W*)$", out[i])
        core = m.group(2)
        if (
            not m.group(1)
            and core[:1] == "Ј"
            and MK_WORD.match(core)
            and core.istitle()
            and MID_SENTENCE.search(out[i - 1])
            and core.lower() in CAPITALS
        ):
            CORRECTIONS.append((out[i], core.lower() + m.group(3), 100))
            out[i] = core.lower() + m.group(3)
    return out


def corrected(lines):
    """OCR lines, (word, confidence) pairs, as text with Macedonian misspellings put right.

    Tesseract's errors on a worn scan are mostly one wrong letter ("финансни", "Федерагивна") or
    a word split where a crease runs through it ("Социјали стичка"). Only purely Cyrillic words of
    four letters or more that tesseract was unsure of and no Macedonian text uses are touched, so
    names, numbers and foreign words stay as read, and a word that is wrong but spells another real
    word is left alone."""
    words = vocab()

    def known(w):
        return w.casefold() in words or w.casefold() in SEEN

    def split(token):
        m = re.match(r"^(\W*)(.*?)(\W*)$", token)
        return m.group(1), m.group(2), m.group(3)

    def fixable(core):
        """A Cyrillic word the corrector may touch. Odd capitals inside ("чЧлен") mean a stray mark
        joined to a real word, and a known word ending in a letter shaped like a digit is a number
        run on ("Членб" is "Член 6"), so neither is a misspelling."""
        return (
            MK_WORD.match(core)
            and len(core) >= 2
            and (core.islower() or core.isupper() or core.istitle())
            and not (core[-1] in "бзо" and known(core[:-1]))
        )

    out = []
    for pairs in lines:
        tokens = lowered([w for w, _ in pairs])
        confs = [c for _, c in pairs]
        # Cyrillic misreadings inside an English sentence are not Macedonian words to correct.
        if sum(bool(LATIN.search(t)) for t in tokens) > len(tokens) / 2:
            out.append(" ".join(tokens))
            continue
        cyrillic = [c for c in (split(t)[1] for t in tokens) if MK_WORD.match(c) and len(c) >= 2]
        # Only a line that is plainly Macedonian gets the bolder fixes below, so a partner's
        # Bulgarian or Russian, one letter from Macedonian in many words, is never "corrected".
        macedonian = (
            len(cyrillic) >= 3
            and sum(map(known, cyrillic)) >= 0.7 * len(cyrillic)
            and not any(PARTNER_ONLY.search(t) for t in tokens)
        )
        result, i = [], 0
        while i < len(tokens):
            pre, core, post = split(tokens[i])
            if (
                i + 1 < len(tokens)
                and MK_WORD.match(core)
                and not post
                and min(confs[i], confs[i + 1]) < SURE
            ):
                pre2, core2, post2 = split(tokens[i + 1])
                joined = (core + core2).casefold()
                if (
                    not pre2
                    and MK_WORD.match(core2)
                    and len(joined) >= 6
                    and not (known(core) and known(core2))
                ):
                    fix = (
                        joined
                        if joined in words
                        else best_spelling(joined)
                        if not known(core) and not known(core2)
                        else None
                    )
                    if fix:
                        new = pre + same_case(core, fix) + post2
                        CORRECTIONS.append(
                            (f"{tokens[i]} {tokens[i + 1]}", new, min(confs[i], confs[i + 1]))
                        )
                        result.append(new)
                        i += 2
                        continue
            # A word ending in a hyphen is the first half of one broken across lines, not a word.
            if (
                fixable(core)
                and not post.startswith("-")
                and (fix := spelling_fix(core.casefold(), confs[i], macedonian, core.isupper()))
            ):
                new = pre + same_case(core, fix) + post
                CORRECTIONS.append((tokens[i], new, confs[i]))
                result.append(new)
            else:
                result.append(tokens[i])
            i += 1
        out.append(" ".join(result))
    return "\n".join(out)


# Raised whenever reading changes what a page comes out as, so pages read the old way are read
# again and every other page is never touched twice. 2: columns read one by one and the treaty
# partner's language models. 3: the script detector for pages with unread lines, and no table
# borders. 4: pale pages read again darkened, and two columns found under a heading across
# both (31 October 2026). 5: doubtful pages turned upright when they lie on their side. 6: doubtful
# pages also read as ruled tables and cell by cell. 7: a bar read for the pronoun I in English
# kept as I rather than dropped as a box border (4 November 2026). 8: tables, ruled or set
# between rules, read cell by cell in their place and kept as tables (4 November 2026).
OCR_VERSION = 8


def ocr_current(doc_id, n, ocr_dir):
    """Whether a page's cache needs no new reading. Versions 5 and 6 changed only doubtful pages, so
    a confident version 4 or 5 page is kept rather than read again across all 5,000 laws."""
    path = Path(ocr_dir) / f"{n}.json"
    if not os.path.exists(path):
        return False
    page = json.loads(path.read_text(encoding="utf-8"))
    return page.get("version") == OCR_VERSION or (
        page.get("version") in (4, 5) and page["confidence"] >= DOUBTFUL_PAGE
    )


def without_page_edges(text, page_number, page_count):
    """Drop a gazette running head or page-count footer only at a page edge.

    OCR often turns the Macedonian gazette masthead into Latin lookalikes. Its
    combination of gazette name, issue number and publication date identifies
    the running head; requiring it to occupy an edge line protects legal citations.
    """
    lines = text.splitlines()
    if not lines:
        return text
    edge = {0, 1, len(lines) - 2, len(lines) - 1}
    kept = []
    for index, line in enumerate(lines):
        for start, end in reversed(running_header_spans(line)):
            line = line[:start] + " " + line[end:]
        line = re.sub(r"\s{2,}", " ", line).strip()
        if not line:
            continue
        if index in edge:
            header = (
                GAZETTE_HEADER_START.match(line)
                and GAZETTE_HEADER.search(line)
                and GAZETTE_DATE.search(line)
                and GAZETTE_ISSUE.search(line)
                and len(line.split()) <= 24
            )
            m = FOOTER.fullmatch(line.strip())
            if m:
                number, total = map(int, m.groups())
                page_match = number == page_number or number == page_number * 10
                total_match = total == page_count or str(page_count).startswith(str(total))
                footer = total_match and (page_match or number <= total)
            else:
                footer = False
            if header or footer:
                continue
        kept.append(line)
    if page_number == page_count:
        last = next((i for i in range(len(kept) - 1, -1, -1) if kept[i].strip()), None)
        if last is not None and FINAL_ACT_CLAUSE.search(kept[last]):
            kept[last] = FINAL_PAGE_NUMBER.sub("", kept[last])
    return "\n".join(kept)


QUOTE_OPEN = re.compile(r"([(:]\s*)С(?P<word>С?[А-ШЃЌЅЉЊЏ][а-шѓќѕљњџА-ШЃЌЅЉЊЏ]+)")
QUOTE_OPEN_M = re.compile(r"(\s+|[(:]\s*|\bво\s+)м(?P<word>С?[А-ШЃЌЅЉЊЏ][а-шѓќѕљњџА-ШЃЌЅЉЊЏ]+)")
LEGAL_QUOTE_OPEN = re.compile(
    r"(\b(?:зборовите|зборот|кои гласат|гласи):\s*)[См](?=[А-ШЃЌЅЉЊЏ])", re.I
)
# A quote that opens on a number after the word that introduces it, as "зборовите: С4.500 до
# 45.000 динарим" (RM-1993-12-3321), "гласи: С6. Имунизација" or "бројот С3м". Only these words
# open it, because a С before a digit elsewhere is a code ("(С171)", "модулите С1 или С2").
LEGAL_NUMBER_OPEN = re.compile(
    r"(\b(?:зборовите|зборот|гласи|гласат|бројот|броевите|износот|процентот|стапката)"
    r"[:;]?\s*)[См](?=\d)",
    re.I,
)
GAZETTE_OPEN = re.compile(r"\bС(?=Службен (?:весник|лист))")
# A quoted number or capitals the old text layer gives as С...м, as "зборовите: С10.000 до
# 50.000м" (SFRJ-1989-47-1700) and "зборот СПОДЕМм". Only digits, signs and the joining words of
# an amount may stand between, so a code such as "Потпрограма С1" or "60м2" is left alone.
PAIRED_QUOTE = re.compile(
    r"(?<![^\s(:/])С(?P<inner>\d(?:[\d.,%/ –-]|\b(?:до|и|или|од)\b)*?[\d%]"
    r"|[А-ШЃЌЅЉЊЏ]{2}[А-ШЃЌЅЉЊЏ\d .,/–-]*?[А-ШЃЌЅЉЊЏ])м(?=[\s,.;:)]|$)",
    re.M,
)
ARTICLE_LINE = re.compile(r"[ \t#]*Член\s+\d+\S*[ \t]*(?:\n|$)")
# Cyrillic letters Macedonian does not have, which mark a line of a partner language's text.
FOREIGN_LETTERS = re.compile(r"[ёйыэъщіїєґђћЁЙЫЭЪЩІЇЄҐЂЋ]")
MK_ALL = MK_LETTERS + MK_LETTERS.upper()
HOMOGLYPHS = str.maketrans("aceopxyiAEOPCTHKMBXjJ", "асеорхуіАЕОРСТНКМВХјЈ")
SERBIAN_MARKERS = (
    "овај",
    "снагу",
    "ступа",
    "мјесец",
    "посљед",
    "обавиј",
    "међусоб",
    "запримањ",
    "писмене",
    "уговорниц",
    "захтјев",
    "републике",
    "овог члана",
    "одредбама",
)
SERBIAN_SHORT_WORDS = re.compile(r"(?<![\w-])(?:је|у|су|ће|који|које)(?![\w-])")
ARTICLE_START = re.compile(r"\n[ \t#]*Член\s+\d")
OTHER_PARTNER_MARKERS = ("съгласно", "държав", "настоящ", "згідно", "держав", "договір")


def foreign_text_line(line):
    """Protect semantic fixes from partner-language treaty sentences."""
    lower = line.casefold()
    if any(marker in lower for marker in SERBIAN_MARKERS):
        return True
    # Serbian without ђ, ћ or a marker word still shows in its short words, which Macedonian
    # does not use ("овлашкен је да врши", "које су у категорији").
    if len(SERBIAN_SHORT_WORDS.findall(lower)) >= 2:
        return True
    return sum(marker in lower for marker in OTHER_PARTNER_MARKERS) >= 2


def fix_quote_artifacts(text):
    """Restore quotes that old LDBIS PDFs encode as Cyrillic letters.

    Some Macedonian gazette PDFs carry an opening quote as ``С`` and a closing
    quote as ``м``. The substitution is made only at legal punctuation and
    while inside a quoted span, so ordinary words containing those letters are
    not changed. OCR and selectable-text PDFs use the same pass.
    """
    words = vocab()

    def known(word):
        # Do not use the law-word exception list here: it was built from the
        # existing corpus and can contain the very OCR artifact being fixed.
        return word.casefold() in words

    def repair_mixed_script(line):
        cyrillic = sum(char in MK_ALL for char in line)
        if cyrillic < 8:
            return line

        def repair(match):
            token = match.group(0)
            candidate = token.translate(HOMOGLYPHS)
            if token.isascii() and (
                not line[match.end() :].lstrip() or line[match.end() :].lstrip()[0] not in MK_ALL
            ):
                return token
            return candidate if candidate != token and known(candidate) else token

        return re.sub(rf"[{MK_ALL}A-Za-z]+", repair, line)

    text = "".join(repair_mixed_script(line) for line in text.splitlines(keepends=True))

    text = GAZETTE_OPEN.sub("„", text)
    text = re.sub(r"\b[см]службен\s+весник\b", "„Службен весник", text, flags=re.I)

    def open_quote(match):
        word = match.group("word")
        mark = match.group(0)[-len(word) - 1]
        return match.group(1) + ("„" if known(word) and not known(mark + word) else mark) + word

    text = QUOTE_OPEN.sub(open_quote, text)
    text = QUOTE_OPEN_M.sub(open_quote, text)
    text = LEGAL_QUOTE_OPEN.sub(r"\1„", text)
    text = LEGAL_NUMBER_OPEN.sub(r"\1„", text)
    text = PAIRED_QUOTE.sub(r"„\g<inner>“", text)
    # In legal references, "член N став M" is fixed terminology. OCR often
    # turns "став" into the ordinary word "стар", which a dictionary cannot
    # reject on spelling alone.
    text = re.sub(r"\b(член\s+\d+)\s+стар\s+(\d+)\b", r"\1 став \2", text, flags=re.I)
    # In Macedonian legal references, OCR also confuses "став" with "стар"
    # when the reference is written as "стар N на/од овој член". Avoid the
    # replacement in Serbian and Bulgarian treaty text, where "стар" can be a
    # genuine word, by requiring the Macedonian phrase "овој член".
    text = re.sub(r"\bстар\s+(\d+)(?=\s+(?:на|од)\s+овој\s+член\b)", r"став \1", text, flags=re.I)
    # The tariff table's OCR joins the digit 6 to the article heading. This
    # exact heading form is distinct from the word "член" in ordinary prose.
    text = re.sub(r"(?m)^([ \t]*)Членб\b", r"\1Член 6", text)
    text = re.sub(r"(Република Македониј)ам(?=\s*(?:број|бр\.|[.,;)\"-]))", r"\1а“", text)
    out = []
    # The open quotes, innermost last. A quote opens inside another only after a bracket, as an
    # amended article citing a gazette ("„Член 9-а ... („Службен лист на СФРЈм ...) ... СРМм",
    # SFRJ-1985-3-1259); any other „ starts afresh, since the text layer may have lost a close.
    opens = []
    for pos, char in enumerate(text):
        quoted = bool(opens)
        opened = opens[-1] if opens else 0
        if char == "„":
            opens = [*opens, pos] if opens and text[pos - 1 : pos] == "(" else [pos]
        elif char == "“":
            opens = opens[:-1]
        elif char == "\n" and quoted and ARTICLE_LINE.match(text, pos + 1):
            # A quote whose closing mark the text layer lost ends at the next article, or it
            # would take an о or м from a word there ("кои гласат: „1) лото;", RM-2001-13-6441).
            opens = []
        elif (
            char in "мо"
            and quoted
            and (pos + 1 == len(text) or text[pos + 1] in " \t\n,.;:)")
            and (
                # A gazette or name in capitals, as "(„Службен весник на СРМм број 4/78".
                (char == "м" and re.search(r"[А-ШЃЌЅЉЊЏ]{2}$", text[max(0, pos - 2) : pos]))
                # An amount the quote opened on, as "„4.500 до 45.000м", "„4.м", "„10, 20,м"
                # or "„0,5%о", never metres in a quoted passage ("поголеми од 150м").
                or (
                    re.search(r"%$" if char == "о" else r"[\d%][,.]?$", text[max(0, pos - 2) : pos])
                    and text[opened + 1 : opened + 2].isdigit()
                    and pos - opened <= 40
                )
                # A space before the м only when the quote is the number alone, as "„3,5 м",
                # never a measure after a code ("„5407 20 19 00 --- 3 м или поголема“").
                or (
                    char == "м"
                    and text[pos - 1] == " "
                    and re.fullmatch(r"\d[\d.,%]*", text[opened + 1 : pos - 1])
                )
            )
        ):
            if out[-1] == " ":
                out.pop()
            char = "“"
            opens = opens[:-1]
        elif char in "мо" and quoted:
            # The whole word, capital included: "Странско" judged as "транск" lost its о.
            start = pos
            while start and text[start - 1] in MK_ALL:
                start -= 1
            base = text[start:pos]
            # A quote the text layer opened with a С stuck to the word, as "СПоединеченм" or
            # "Счленовитем". "Странско" is a word, so its С stays.
            if (
                base[:1] == "С"
                and not known(base)
                and not known(base + char)
                and known(base[1:])
                and not known(base[1:] + char)
            ):
                base = base[1:]
            # A partner language shows within a few lines, not always on the word's own line,
            # but a treaty's text in another article says nothing about this one.
            lo, hi = max(0, pos - 300), pos + 300
            for heading in ARTICLE_START.finditer(text, lo, hi):
                if heading.start() < pos:
                    lo = heading.start()
                else:
                    hi = heading.start()
                    break
            near = text[lo:hi]
            # The old PDF text layer uses both м and о as closing-quote artifacts. An о after an
            # adjective stem in н is its neuter ending, which the vocabulary may lack
            # ("„Метализирано", "„Пречистено"), not a quote.
            artifact = char == "м" or (
                base
                and not base.endswith("о")
                and not (base.endswith("н") and (known(base + "а") or known(base + "и")))
            )
            if (
                artifact
                and base
                and known(base)
                and not known(base + char)
                # A hyphen joins a word broken across lines or a compound ("хирдо- хлорната",
                # "акрило-нитрил"), never a quote's end.
                and (pos + 1 == len(text) or text[pos + 1] not in MK_LETTERS + "-\u00ac\u00ad")
                # Russian, Ukrainian and Serbian treaty text ends real words in м and о
                # ("образом", "дањем", "повторио").
                and not FOREIGN_LETTERS.search(near)
                and not foreign_text_line(near)
            ):
                char = "“"
                opens = opens[:-1]
        out.append(char)
    text = "".join(out)
    text = re.sub(r"[ \t]+:", ":", text)
    # Macedonian typing uses “ and " to open a quote as well as to close one, as in
    # 'зборовите: “до' (RM-2010-50-19233). A quote opens where a space or a line start comes
    # before it, and closes where no letter, digit or opening bracket follows it ('бројот “(1)“'),
    # so only those spaces are stray.
    text = re.sub(r"(?<=[„«])[ \t]+", "", text)
    text = re.sub(r'(?m)(^|\s)"[ \t]+(?=\w)', r'\1"', text)
    text = re.sub(r'(?<=\w)[ \t]+(?=[“»"](?![\w(]))', "", text)
    return text


# An article heading as OCR misreads it: a stray mark before it, a letter of "Член" wrong
# ("Члевп 3", "Члеа8"), б for 6, and now and then a page code run on ("Член 10 9012"). Treaties
# embedded in a ratifying law kept their articles as one paragraph without this (59321).
OCR_ARTICLE = re.compile(r"^[^\wЀ-ӿ]*Чле[а-ш]{0,2}\s*([\dбзо]{1,3})(?:\s+\d+)?\s*$")
# A line this much shorter than the page's full lines, ending a sentence, ends its paragraph.
SHORT_LINE = 0.85


def ocr_text(text):
    """An OCR'd page's text with article headings put right and paragraph ends marked.

    OCR keeps only where lines wrap, so a page came out as one paragraph. The last line of a
    paragraph stops short of the margin, which its length shows against the page's other lines."""
    lines = [
        OCR_ARTICLE.sub(lambda m: "Член " + m.group(1).translate(str.maketrans("бзо", "630")), ln)
        for ln in text.split("\n")
    ]
    full = sorted(len(ln) for ln in lines if len(ln.split()) >= 5)
    width = full[len(full) * 3 // 4] if full else 0
    out = []
    for ln in lines:
        out.append(ln)
        if width and re.search(r"[.:;!?“\"»)]$", ln) and len(ln) < SHORT_LINE * width:
            out.append(PARAGRAPH)
    return "\n".join(out)


def ocr_pages(doc_id, pages, pdf_path, output_dir, title, tessdata):
    from concurrent.futures import ProcessPoolExecutor

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    todo = []
    for page_number in pages:
        cached = Path(output_dir) / f"{page_number}.json"
        if (
            cached.exists()
            and json.loads(cached.read_text(encoding="utf-8")).get("version") == OCR_VERSION
        ):
            continue
        todo.append((doc_id, page_number, str(pdf_path), str(output_dir), tessdata, title))
    if todo:
        with ProcessPoolExecutor(min(4, len(todo))) as pool:
            list(pool.map(ocr_page, todo))
    return {
        page_number: json.loads(
            (Path(output_dir) / f"{page_number}.json").read_text(encoding="utf-8")
        )
        for page_number in pages
    }


def prepare_assets(cache_dir: str | Path) -> Path:
    """Ensure the models every scanned page uses and the local Tesseract executable are available.

    A treaty partner's model is fetched by fetch_model the first time a page needs it, so a run
    with no treaty downloads three models of the manifest's 53."""
    tessdata = Path(cache_dir) / "tessdata"
    tessdata.mkdir(parents=True, exist_ok=True)
    for lang in ("mkd", "eng", "osd"):
        fetch_model(str(tessdata), lang)
    if shutil.which("tesseract") is None:
        raise RuntimeError("Macedonian scanned-PDF OCR requires the Tesseract executable")
    return tessdata


@functools.cache
def fetch_model(tessdata: str, lang: str) -> None:
    """Download one pinned model into tessdata unless a copy with its checksum is there. Cached
    per process, since a page runs Tesseract many times and hashing a model takes a while."""
    if not tessdata:
        return
    manifest = json.loads((ASSET_ROOT / "tessdata_manifest.json").read_text(encoding="utf-8"))
    base = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/{manifest['revision']}"
    filename = f"{lang}.traineddata"
    digest = manifest["files"][filename]
    destination = Path(tessdata) / filename
    if not (
        destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == digest
    ):
        # Each worker process downloads to its own name, and the rename is atomic.
        temporary = destination.with_suffix(f".{os.getpid()}.download")
        subprocess.run(
            [
                "curl",
                "--fail",
                "--location",
                "--retry",
                "3",
                "--silent",
                "--show-error",
                f"{base}/{filename}",
                "--output",
                str(temporary),
            ],
            check=True,
        )
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
            temporary.unlink(missing_ok=True)
            raise ValueError(f"Tesseract model checksum mismatch: {filename}")
        temporary.replace(destination)


def parse_pdf(
    data: bytes, norm_id: str, title: str, cache_dir: str | Path
) -> tuple[list[str], dict]:
    """Read scanned and text-layer pages, apply reviewed fixes, and return the law text."""
    digest = hashlib.sha256(data).hexdigest()
    root = Path(cache_dir)
    pdf_dir = root / "pdf" / digest
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = pdf_dir / f"{norm_id}.pdf"
    if not pdf_path.exists():
        pdf_path.write_bytes(data)
    ocr_dir = root / "pages" / digest / norm_id
    kinds = scanned_pages_path(pdf_path)
    tessdata = str(prepare_assets(root)) if any(kinds) else ""
    lines = doc_lines(
        norm_id,
        title=title,
        pdf_path=pdf_path,
        ocr_dir=ocr_dir,
        kinds=kinds,
        tessdata=str(tessdata),
    )
    lines = law_text_only(lines, title)
    doubtful, unread = [], []
    for page_path in sorted(ocr_dir.glob("*.json"), key=lambda path: int(path.stem)):
        record = json.loads(page_path.read_text(encoding="utf-8"))
        page_number = int(page_path.stem) + 1
        kept = readable(record)
        if (
            record["confidence"] < DOUBTFUL_PAGE
            or record["words"] < 20
            or any(unreadable(pairs) for pairs in kept if not pairs[0][0].startswith(TABLE_MARK))
        ):
            doubtful.append(page_number)
        if record.get("unread_lines") or len(kept) < len(record["lines"]):
            unread.append(page_number)
    fixes = json.loads((ASSET_ROOT / "ocr_fixes.json").read_text(encoding="utf-8"))
    left_out = {page for _old, _new, *page in fixes.get(norm_id, []) for page in page}
    unread = sorted(set(unread) | left_out)
    details = {
        "source_sha256": digest,
        "text_source": text_source_from_pdf(pdf_path),
        "doubtful_pages": doubtful,
        "unread_pages": unread,
    }
    return lines, details


def text_source_from_pdf(pdf_path: Path) -> str | None:
    kinds = scanned_pages_path(pdf_path)
    return None if not any(kinds) else "ocr" if all(kinds) else "mixed"


def scanned_pages_path(pdf_path: Path) -> list[bool]:
    with pdfplumber.open(pdf_path) as pdf:
        return [
            len(page.chars) < 300
            and sum(
                (image["x1"] - image["x0"]) * (image["bottom"] - image["top"])
                for image in page.images
            )
            / (page.width * page.height)
            > 0.15
            for page in pdf.pages
        ]


def doc_lines(
    doc_id: str,
    *,
    title: str,
    pdf_path: Path,
    ocr_dir: Path,
    kinds: list[bool],
    tessdata: str,
) -> list[str]:
    scanned = [index for index, value in enumerate(kinds) if value]
    ocr = ocr_pages(doc_id, scanned, pdf_path, ocr_dir, title, tessdata) if scanned else {}
    texts = []
    with pdfplumber.open(pdf_path) as pdf:
        for index, page in enumerate(pdf.pages):
            page_text = (
                with_tables(ocr_text(corrected(readable(ocr[index]))), ocr[index].get("tables", []))
                if kinds[index]
                else text_page(page)
            )
            texts.append(without_page_edges(page_text, index + 1, len(pdf.pages)))
    texts, _removed_page_numbers = remove_sequential_page_numbers(texts)
    texts = remove_repeated_headers(texts)
    text = fix_quote_artifacts("\f".join(texts))
    fixes = json.loads((ASSET_ROOT / "ocr_fixes.json").read_text(encoding="utf-8"))
    # An entry may name the page whose unreadable letterhead or running head it leaves out
    # (14566), and parse_pdf records that page as unread.
    for old, new, *_page in fixes.get(str(doc_id), []):
        if old not in text:
            raise ValueError(f"Reviewed OCR replacement for LDBIS {doc_id} did not match: {old!r}")
        text = text.replace(old, new)
    lines = []
    for line in text.replace("\f", "\n").split("\n"):
        if line == PARAGRAPH:
            if lines and lines[-1] != PARAGRAPH:
                lines.append(line)
            continue
        line = line.strip()
        if (
            line
            and not HEADER.match(line)
            and not MASTHEAD_LINE.match(line)
            and not CODE.match(line)
        ):
            lines.append(BRACKET_FOR_I.sub("I", line))
    return without_page_counters(lines, len(kinds))


# The English model reads the capital I of IPA and IPARD as an opening bracket, "[PA" in
# RM-2008-18-14566. Only these two words: across the cached scans, a bracket before other
# capitals is as often a real bracket or a misread Cyrillic word as a lost I.
BRACKET_FOR_I = re.compile(r"\[(?=PA(?:RD)?\b)")
COUNTER_TOTAL = re.compile(r"\s([\dlI]{2,3})$")


def without_page_counters(lines: list[str], page_count: int) -> list[str]:
    """Drop the PDF's "N од 114" page footers however OCR spelled them.

    RM-2008-18-14566 prints "N од 114" under every page, read as "3o0n 114", "Jon 114",
    "55 ол 114" or, run together, "400114". The total is the same on every page, so it is
    taken from the short lines that end in it after an од-like word, when at least three do.
    It must also be within two of the PDF's page count: in 429 of the 440 cached scans that
    show such a total it equals the page count, and the other eleven were tariff codes and
    table figures ("5408 31 00") or a gazette's own page count one or two off.
    """

    def total_of(line: str) -> str | None:
        match = COUNTER_TOTAL.search(line)
        if not match or len(line) > 14 or re.search(r"[^\W\d_]{4,}", line):
            return None
        if not re.search(r"[oоOО0]", line[: match.start()]) or not re.search(r"\d", match.group(1)):
            return None
        return match.group(1).replace("l", "1").replace("I", "1")

    counts = Counter(total for total in map(total_of, lines) if total)
    if not counts or counts.most_common(1)[0][1] < 3:
        return lines
    total = counts.most_common(1)[0][0]
    if abs(int(total) - page_count) > 2:
        return lines
    # Once the total is known, a short line of digits and од-like letters ending in it is a
    # counter too, as "13001114", "540n114" and "11301114 0д 114" are.
    run_together = re.compile(rf"\d[\d\soоOО0nлдaаl]{{0,13}}{total}")
    return [line for line in lines if total_of(line) != total and not run_together.fullmatch(line)]
