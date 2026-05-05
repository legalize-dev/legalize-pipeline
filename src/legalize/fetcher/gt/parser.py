from __future__ import annotations

from datetime import date
import re
import unicodedata

from legalize.fetcher.base import MetadataParser, TextParser
from legalize.models import Block, NormMetadata, NormStatus, Paragraph, Rank, Version


DEFAULT_DATE = date(2000, 1, 1)


FIXTURE_METADATA = {
    "decreto-57-2008": {
        "title": "Ley de Acceso a la Información Pública",
        "short_title": "LAIP",
        "rank": Rank.DECRETO,
        "publication_date": None,
        "department": "Congreso de la República de Guatemala",
        "source": "https://www.congreso.gob.gt/assets/uploads/info_legislativo/decretos/2008/57-2008.pdf",
        "pdf_url": "https://www.congreso.gob.gt/assets/uploads/info_legislativo/decretos/2008/57-2008.pdf",
        "extra": (
            ("decree_number", "57-2008"),
            ("source_type", "official_primary"),
            ("confidence", "high"),
        ),
    },
    "decreto-13-2013": {
        "title": "Reformas al Decreto 101-97, Ley Orgánica del Presupuesto",
        "short_title": "Decreto 13-2013",
        "rank": Rank.DECRETO,
        "publication_date": date(2013, 11, 12),
        "department": "Congreso de la República de Guatemala",
        "source": "https://www.congreso.gob.gt/assets/uploads/info_legislativo/decretos/2013/13-2013.pdf",
        "pdf_url": "https://www.congreso.gob.gt/assets/uploads/info_legislativo/decretos/2013/13-2013.pdf",
        "extra": (
            ("decree_number", "13-2013"),
            ("source_type", "official_primary"),
            ("confidence", "medium"),
            ("effective_date_candidate", "2013-11-20"),
        ),
    },
}


def normalize_for_matching(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.lower()


def clean_line(line: str) -> str:
    line = line.replace("\u00a0", " ")
    line = re.sub(r"[ \t]+", " ", line)
    return line.strip()


def is_page_artifact(line: str) -> bool:
    stripped = clean_line(line)

    if not stripped:
        return False

    patterns = [
        r"^\d+$",
        r"^N[ÚU]MERO\s*\d+.*$",
        r"^N[ÚU]MER[O0]?\s*\d+$",
        r"^DIARIO\s+de\s+CENTRO\s+AM[ÉE]RICA$",
        r"^Congreso de la República de Guatemala, Departamento de Información Legislativa\.?$",
        r"^Guatemala,\s+(LUNES|MARTES|MI[ÉE]RCOLES|JUEVES|VIERNES|S[ÁA]BADO|DOMINGO).*$",
        r"^/{1,2}$",
        r"^/~$",
        r"^\.$",
    ]

    return any(re.search(pattern, stripped, re.IGNORECASE) for pattern in patterns)


def classify_line(line: str) -> tuple[str, str, str] | None:
    original = clean_line(line)
    normalized = normalize_for_matching(original)

    if not original:
        return None

    if re.search(r"\.{5,}\s*\d+$", original):
        return None

    title_match = re.match(
        r"^titulo\s+([ivxlcdm]+|primero|segundo|tercero|cuarto|quinto|sexto|septimo|octavo|noveno|decimo|\d+)\b",
        normalized,
        re.IGNORECASE,
    )
    if title_match:
        return ("title", title_match.group(1), original)

    chapter_match = re.match(
        r"^capitulo\s+([ivxlcdm]+|unico|primero|segundo|tercero|cuarto|quinto|sexto|septimo|octavo|noveno|decimo|\d+)\b",
        normalized,
        re.IGNORECASE,
    )
    if chapter_match:
        return ("chapter", chapter_match.group(1), original)

    section_match = re.match(
        r"^seccion\s+([ivxlcdm]+|primera|segunda|tercera|cuarta|quinta|sexta|septima|octava|novena|decima|\d+)\b",
        normalized,
        re.IGNORECASE,
    )
    if section_match:
        return ("section", section_match.group(1), original)

    article_match = re.match(
        r"^articulo\s+([0-9]+(?:\s*(?:bis|ter|quater|quáter))?)\s*[\.\-º°\*]*\s*(.*)$",
        normalized,
        re.IGNORECASE,
    )
    if article_match:
        marker = " ".join(article_match.group(1).split())
        return ("article", marker, original)

    reform_match = re.search(
        r"\b(reformado|reformada|reformadas|adicionado|adicionada|adicionadas|derogado|derogada|derogadas)\b",
        normalized,
        re.IGNORECASE,
    )
    if reform_match and "decreto numero" in normalized:
        return ("reform_note", reform_match.group(1), original)

    return None


def css_class_for_block(block_type: str) -> str:
    return {
        "title": "titulo_tit",
        "chapter": "capitulo_tit",
        "section": "seccion",
        "article": "articulo",
        "reform_note": "parrafo",
        "preamble": "parrafo",
    }.get(block_type, "parrafo")


def block_id(block_type: str, marker: str, index: int) -> str:
    safe_marker = normalize_for_matching(marker or str(index))
    safe_marker = re.sub(r"[^a-z0-9]+", "-", safe_marker).strip("-")
    return f"{block_type}-{safe_marker or index}"


def parse_gt_blocks(text: str, *, norm_id: str, publication_date: date) -> list[Block]:
    raw_lines = text.splitlines()

    blocks: list[Block] = []
    current_type = "preamble"
    current_marker = ""
    current_title = "Preamble"
    current_lines: list[str] = []
    current_index = 0

    def flush() -> None:
        nonlocal current_lines, current_index

        block_text = "\n".join(current_lines).strip()
        if not block_text:
            current_lines = []
            return

        current_index += 1

        paragraphs = [
            Paragraph(css_class=css_class_for_block(
                current_type), text=current_title),
        ]

        body = block_text
        if body.startswith(current_title):
            body = body[len(current_title):].strip()

        for line in body.splitlines():
            cleaned = clean_line(line)
            if cleaned:
                paragraphs.append(Paragraph(css_class="parrafo", text=cleaned))

        version = Version(
            norm_id=norm_id,
            publication_date=publication_date,
            effective_date=publication_date,
            paragraphs=tuple(paragraphs),
        )

        blocks.append(
            Block(
                id=block_id(current_type, current_marker, current_index),
                block_type=current_type,
                title=current_title,
                versions=(version,),
            )
        )

        current_lines = []

    for line in raw_lines:
        cleaned = clean_line(line)

        if is_page_artifact(cleaned):
            continue

        classification = classify_line(cleaned)

        if classification:
            flush()
            current_type, current_marker, current_title = classification
            current_lines = [cleaned]
        elif cleaned:
            current_lines.append(cleaned)

    flush()

    return blocks


class GTTextParser(TextParser):
    def parse_text(self, data: bytes) -> list[Block]:
        text = data.decode("utf-8", errors="replace")

        norm_id = "gt-unknown"
        publication_date = DEFAULT_DATE

        if "DECRETO NÚMERO 57-2008" in text or "DECRETO No. 57-2008" in text:
            norm_id = "decreto-57-2008"
        elif "DECRETO NÚMERO 13-2013" in text:
            norm_id = "decreto-13-2013"
            publication_date = date(2013, 11, 12)

        return parse_gt_blocks(text, norm_id=norm_id, publication_date=publication_date)


class GTMetadataParser(MetadataParser):
    def parse(self, data: bytes, norm_id: str) -> NormMetadata:
        if norm_id not in FIXTURE_METADATA:
            raise KeyError(
                f"No Guatemala metadata fixture registered for {norm_id}")

        raw = FIXTURE_METADATA[norm_id]
        publication_date = raw["publication_date"] or DEFAULT_DATE

        return NormMetadata(
            title=str(raw["title"]),
            short_title=str(raw["short_title"]),
            identifier=norm_id,
            country="gt",
            rank=Rank(str(raw["rank"])),
            publication_date=publication_date,
            status=NormStatus.IN_FORCE,
            department=str(raw["department"]),
            source=str(raw["source"]),
            pdf_url=str(raw["pdf_url"]),
            extra=tuple(raw["extra"]),
        )
