"""Shared text hygiene helpers for country parsers.

- UTF-8 decoding with replacement (never rely on requests autodetect)
- C0/C1 control-character scrubbing (keep tab, LF, CR)
- Collapse of zero-width and NBSP variants to plain spaces at paragraph
  boundaries (never inside URLs or inline code)
"""

from __future__ import annotations

import re

# All C0 (0x00-0x1F) except \t \n \r. All C1 (0x80-0x9F).
_CONTROL_RE = re.compile(r"[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F-\x9F]")

# NBSP, narrow NBSP, figure space, zero-width space, zero-width non-joiner, etc.
_NBSP_MAP = {
    " ": " ",
    " ": " ",
    " ": " ",
    "​": "",
    "‌": "",
    "‍": "",
    "﻿": "",
}


def decode_utf8(data: bytes) -> str:
    """Force UTF-8 decoding, replacing undecodable bytes."""
    if isinstance(data, str):
        return data
    return data.decode("utf-8", errors="replace")


def strip_control(text: str) -> str:
    """Strip C0/C1 control chars (keeping tab, LF, CR). No other rewriting."""
    return _CONTROL_RE.sub("", text)


def scrub_control(text: str) -> str:
    """Strip C0/C1 control chars and normalize NBSP family to regular space."""
    for src, dst in _NBSP_MAP.items():
        text = text.replace(src, dst)
    return strip_control(text)


def clean(data: bytes | str) -> str:
    """Decode + scrub in one call. Safe to feed back into lxml as bytes."""
    return scrub_control(decode_utf8(data))


def collapse_inline_whitespace(text: str) -> str:
    """Collapse runs of spaces/tabs, preserve newlines and structure."""
    # Don't touch lines inside fenced code or table rows.
    out_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("|") or line.startswith("```"):
            out_lines.append(line)
            continue
        out_lines.append(re.sub(r"[ \t]+", " ", line).rstrip())
    return "\n".join(out_lines)
