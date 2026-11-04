"""Parsers for China's National Database of Laws and Regulations JSON responses."""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    Rank,
    Reform,
    Version,
)

logger = logging.getLogger(__name__)

# Rank mapping from Chinese category (flxz)
_RANK_MAP: dict[str, Rank] = {
    "宪法": Rank.CONSTITUCION,
    "法律": Rank.LEY,
    "行政法规": Rank.REAL_DECRETO,
    "监察法规": Rank.REGLAMENTO,
    "司法解释": Rank("interpretacion_judicial"),
    "地方法规": Rank("ley_autonomica"),
    "部门规章": Rank("reglamento"),
    "地方政府规章": Rank("reglamento"),
}

# Status mapping from timeliness code (sxx)
_STATUS_MAP: dict[int, NormStatus] = {
    1: NormStatus.IN_FORCE,
    2: NormStatus.PARTIALLY_REPEALED,
    3: NormStatus.IN_FORCE,
    4: NormStatus.IN_FORCE,  # Promulgated / not yet effective
    5: NormStatus.REPEALED,
}


def _extract_dict(raw: bytes | str | dict[str, Any]) -> dict[str, Any]:
    """Normalize input into the core data dictionary."""
    if isinstance(raw, (bytes, str)):
        parsed = json.loads(raw)
    else:
        parsed = raw

    if isinstance(parsed, dict) and "data" in parsed and isinstance(parsed["data"], dict):
        return parsed["data"]
    if isinstance(parsed, dict):
        return parsed
    return {}


class CNMetadataParser(MetadataParser):
    """Metadata parser for Chinese legislation."""

    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        """Parse raw JSON bytes into NormMetadata."""
        row = _extract_dict(data)

        title = (row.get("title") or "").strip()
        short_title = title
        identifier = row.get("bbbs") or norm_id
        flxz = row.get("flxz") or "法律"
        rank = _RANK_MAP.get(flxz, Rank.LEY)

        # Promulgation date
        gbrq_str = row.get("gbrq")
        if gbrq_str:
            try:
                pub_date = date.fromisoformat(gbrq_str)
            except ValueError:
                pub_date = date(1949, 10, 1)
        else:
            pub_date = date(1949, 10, 1)

        # Effective date
        sxrq_str = row.get("sxrq")
        effective_date_str = sxrq_str if sxrq_str else ""

        # Status
        sxx_code = row.get("sxx")
        status = _STATUS_MAP.get(sxx_code, NormStatus.IN_FORCE) if sxx_code else NormStatus.IN_FORCE

        department = (row.get("zdjgName") or "").strip()
        source_url = f"https://flk.npc.gov.cn/detail.html?bbbs={identifier}"

        # Extra key-value pairs
        extra_pairs: list[tuple[str, str]] = []
        if effective_date_str:
            extra_pairs.append(("effective_date", effective_date_str))
        if flxz:
            extra_pairs.append(("category", flxz))
        if department:
            extra_pairs.append(("issuing_body", department))

        oss_file = row.get("ossFile") or {}
        if oss_file.get("ossWordPath"):
            extra_pairs.append(("source_word_path", str(oss_file["ossWordPath"])))
        if oss_file.get("ossPdfPath"):
            extra_pairs.append(("source_pdf_path", str(oss_file["ossPdfPath"])))
        if oss_file.get("ossWordOfdPath"):
            extra_pairs.append(("source_ofd_path", str(oss_file["ossWordOfdPath"])))

        return NormMetadata(
            title=title,
            short_title=short_title,
            identifier=identifier,
            country="cn",
            rank=rank,
            publication_date=pub_date,
            status=status,
            department=department,
            source=source_url,
            extra=tuple(extra_pairs),
        )


class CNTextParser(TextParser):
    """Text parser for Chinese statutory trees and content."""

    def parse_text(self, data: bytes) -> list[Block]:
        """Parse structured law tree into a list of Block objects."""
        row = _extract_dict(data)
        content_root = row.get("content")
        norm_id = row.get("bbbs", "")
        title = (row.get("title") or "").strip()

        pub_date_str = row.get("gbrq")
        pub_date = date.fromisoformat(pub_date_str) if pub_date_str else date(1949, 10, 1)
        eff_date_str = row.get("sxrq")
        eff_date = date.fromisoformat(eff_date_str) if eff_date_str else pub_date

        blocks: list[Block] = []
        if content_root and isinstance(content_root, dict):
            self._walk_tree(content_root, norm_id, pub_date, eff_date, blocks)

        # Fallback when content tree is not embedded
        if not blocks and title:
            version = Version(
                norm_id=norm_id,
                publication_date=pub_date,
                effective_date=eff_date,
                paragraphs=(Paragraph(css_class="parrafo", text=title),),
            )
            blocks.append(
                Block(
                    id=norm_id or "root",
                    block_type="articulo",
                    title=title,
                    versions=(version,),
                )
            )

        return blocks

    def _classify_node(self, title: str) -> tuple[str, str]:
        """Classify a node title into (block_type, css_class)."""
        t = title.strip()
        if re.match(r"^第[一二三四五六七八九十百千万0-9]+编", t):
            return "libro", "titulo"
        if re.match(r"^第[一二三四五六七八九十百千万0-9]+分编", t):
            return "parte", "titulo"
        if re.match(r"^第[一二三四五六七八九十百千万0-9]+章", t):
            return "capitulo", "capitulo_tit"
        if re.match(r"^第[一二三四五六七八九十百千万0-9]+节", t):
            return "seccion", "seccion"
        if re.match(r"^第[一二三四五六七八九十百千万0-9]+条", t):
            return "articulo", "articulo"
        if t in ("题注", "修改决定", "说明"):
            return "preamble", "cita"
        if "序言" in t or "前言" in t:
            return "preamble", "titulo"
        if "附则" in t or "总则" in t or "分则" in t:
            return "capitulo", "capitulo_tit"
        if any(w in t for w in ("附表", "税率表", "附件", "附录")):
            return "anexo", "anexo"
        return "parrafo", "parrafo"

    def _walk_tree(
        self,
        node: dict[str, Any],
        norm_id: str,
        pub_date: date,
        eff_date: date,
        blocks: list[Block],
    ) -> None:
        """Recursively convert nodes into Block items."""
        if not node:
            return

        node_id = str(node.get("id") or f"block_{len(blocks) + 1}")
        title = (node.get("title") or "").strip()
        children = node.get("children") or []
        content_text = (node.get("content") or "").strip()

        # Skip raw root repetition if title equals law title and has children
        if title and not node.get("parentId") and children:
            for child in children:
                self._walk_tree(child, norm_id, pub_date, eff_date, blocks)
            return

        if title:
            block_type, css_class = self._classify_node(title)
            paragraphs: list[Paragraph] = []

            # 1. Add heading paragraph for structural elements
            if css_class in ("titulo", "capitulo_tit", "seccion", "articulo", "anexo"):
                paragraphs.append(Paragraph(css_class=css_class, text=title))
            elif css_class == "cita":
                text_body = content_text if content_text else title
                paragraphs.append(Paragraph(css_class="cita", text=text_body))

            # 2. Add node body content if present
            if content_text and css_class != "cita":
                for line in content_text.splitlines():
                    line_str = line.strip()
                    if not line_str:
                        continue
                    if line_str.startswith("|") and line_str.endswith("|"):
                        paragraphs.append(Paragraph(css_class="table", text=line_str))
                    else:
                        paragraphs.append(Paragraph(css_class="parrafo", text=line_str))

            if paragraphs:
                version = Version(
                    norm_id=norm_id,
                    publication_date=pub_date,
                    effective_date=eff_date,
                    paragraphs=tuple(paragraphs),
                )
                blocks.append(
                    Block(
                        id=node_id,
                        block_type=block_type,
                        title=title,
                        versions=(version,),
                    )
                )

        # Recurse children
        for child in children:
            self._walk_tree(child, norm_id, pub_date, eff_date, blocks)

    def extract_reforms(self, data: bytes) -> list[Reform]:
        """Extract chronological reform timeline from lsyg."""
        row = _extract_dict(data)
        lsyg = row.get("lsyg") or []

        reforms: list[Reform] = []
        for item in lsyg:
            bbbs = item.get("bbbs")
            gbrq_str = item.get("gbrq")
            if not bbbs or not gbrq_str:
                continue
            try:
                reform_date = date.fromisoformat(gbrq_str)
                reforms.append(
                    Reform(
                        date=reform_date,
                        norm_id=bbbs,
                        affected_blocks=(),
                    )
                )
            except ValueError:
                continue

        # Sort chronological (oldest first)
        reforms.sort(key=lambda r: r.date)
        return reforms
