"""What a rendered norm is made of, counted off the structure the source declared.

`article_count` has never been a fact from any source: it is a regex run over
the finished Markdown in `legalize-enrichment`, one of three systems that
independently reconstruct a structure the engine already had and threw away
when it wrote `###### {text}`. The regex is also blind by construction — the
daily sync is incremental, so a law nobody touches keeps the count of the day
it entered, and every improvement to the patterns needs a manual full sync to
be seen at all.

Counting here instead makes it a property of the file: written once, by the
only layer that knows which blocks were rendered and what the source called
them.
"""

from __future__ import annotations

from dataclasses import dataclass

from legalize.countries import article_heading_for
from legalize.models import HEADING_ROLES, Paragraph, ParagraphRole

# The migration path out of #128. A parser that knows its own vocabulary sets
# `Paragraph.role` and never consults this; everything else is resolved here,
# so no corpus moves while the fetchers are migrated one at a time.
#
# Deliberately strict. `centro_redonda` and friends render as headings but are
# centred text, not a unit the source declared, and counting them as structure
# would hide the exact defect these roles exist to find: in the pre-2005 diary
# XML the BOE labels everything `parrafo`, so a 482-paragraph decree arrives
# with `Artículo 1.` as prose and no declared article at all.
_CSS_ROLES: dict[str, ParagraphRole] = {
    "libro": ParagraphRole.BOOK,
    "libro_num": ParagraphRole.BOOK,
    "libro_tit": ParagraphRole.BOOK,
    "parte": ParagraphRole.PART,
    "parte_num": ParagraphRole.PART,
    "parte_tit": ParagraphRole.PART,
    "titulo": ParagraphRole.TITLE,
    "titulo_num": ParagraphRole.TITLE,
    "titulo_tit": ParagraphRole.TITLE,
    "capitulo": ParagraphRole.CHAPTER,
    "capitulo_num": ParagraphRole.CHAPTER,
    "capitulo_tit": ParagraphRole.CHAPTER,
    "seccion": ParagraphRole.SECTION,
    "seccion_num": ParagraphRole.SECTION,
    "seccion_tit": ParagraphRole.SECTION,
    "subseccion": ParagraphRole.SUBSECTION,
    "subseccion_num": ParagraphRole.SUBSECTION,
    "subseccion_tit": ParagraphRole.SUBSECTION,
    # A disposición adicional is a unit of the law like an article is, and the
    # BOE marks both `articulo`. `article_count` separates them by the heading
    # text; `provision_count` is the pair.
    "articulo": ParagraphRole.ARTICLE,
    "disp_num": ParagraphRole.ARTICLE,
    "disp_tit": ParagraphRole.ARTICLE,
    "anexo": ParagraphRole.ANNEX,
    "anexo_num": ParagraphRole.ANNEX,
    "anexo_tit": ParagraphRole.ANNEX,
    "apendice": ParagraphRole.APPENDIX,
    "apendice_num": ParagraphRole.APPENDIX,
    "apendice_tit": ParagraphRole.APPENDIX,
    "cita": ParagraphRole.QUOTE,
    "cita_con_pleca": ParagraphRole.QUOTE,
    "cita_ley": ParagraphRole.QUOTE,
    "cita_art": ParagraphRole.QUOTE,
    "quote": ParagraphRole.QUOTE,
    "nota_pie": ParagraphRole.NOTE,
    "nota_pie_2": ParagraphRole.NOTE,
    "firma": ParagraphRole.SIGNATURE,
    "firma_rey": ParagraphRole.SIGNATURE,
    "firma_ministro": ParagraphRole.SIGNATURE,
    "signature": ParagraphRole.SIGNATURE,
    "image": ParagraphRole.IMAGE,
    "list": ParagraphRole.LIST_ITEM,
    "list_item": ParagraphRole.LIST_ITEM,
    "table": ParagraphRole.TABLE,
    "table_row": ParagraphRole.TABLE,
    "preamble": ParagraphRole.PREAMBLE,
}


def role_of(paragraph: Paragraph) -> ParagraphRole:
    """What this paragraph is. Anything unrecognised is body text."""
    if paragraph.role is not None:
        return paragraph.role
    return _CSS_ROLES.get(paragraph.css_class, ParagraphRole.BODY)


@dataclass(frozen=True)
class StructureCounts:
    """What ended up in the file."""

    articles: int
    provisions: int
    headings: int


def count_structure(country: str, paragraphs: list[Paragraph]) -> StructureCounts | None:
    """Count the units of a rendered norm, or None if this country is not counted.

    A country is counted once its article vocabulary has been measured against
    its own published corpus (`countries.ARTICLE_HEADING`). Emitting a zero for
    a country whose structure the engine cannot yet read would be worse than
    emitting nothing: a reader cannot tell "no articles" from "not counted",
    and `article_count: 0` is already ambiguous enough that `web/models.py`
    carries a note about it.
    """
    pattern = article_heading_for(country)
    if pattern is None:
        return None

    provisions = 0
    articles = 0
    headings = 0
    for paragraph in paragraphs:
        role = role_of(paragraph)
        if role in HEADING_ROLES:
            headings += 1
        if role is ParagraphRole.ARTICLE:
            provisions += 1
            if pattern.match(paragraph.text):
                articles += 1
    return StructureCounts(articles=articles, provisions=provisions, headings=headings)
