"""Client for the LEGI XML Open Data dump (Légifrance).

Reads XML files from the local dump downloaded from:
  https://echanges.dila.gouv.fr/OPENDATA/LEGI/

Actual dump structure (Freemium_legi_global + increments):

  {legi_dir}/
    legi/global/
      code_et_TNC_en_vigueur/
        code_en_vigueur/
          LEGI/TEXT/{aa}/{bb}/{cc}/{dd}/{ee}/{ff}/LEGITEXTXXX/
            texte/struct/LEGITEXTXXX.xml          ← code structure
            article/LEGI/ARTI/.../LEGIARTIYYY.xml ← articles
            section_ta/LEGI/SCTA/.../LEGISCTAZZZ.xml
        TNC_en_vigueur/
          JORF/TEXT/.../JORFTEXT.../               ← laws, decrees, etc.
      code_et_TNC_non_vigueur/...                  ← repealed

Actual format (verified with 2026-03-27 increment):
  - Root tag: <TEXTELR> (uppercase)
  - Structure: <STRUCT>, not <STRUCTURE_TXT>
  - Section title: text of <LIEN_SECTION_TA> element, NOT attribute
  - Dates: YYYY-MM-DD (not YYYYMMDD)
  - Sentinel: 2999-01-01 (not 99999999)
  - Article tag: <ARTICLE> (uppercase)
  - Content: <BLOC_TEXTUEL><CONTENU>
  - Sources: <LIENS><LIEN typelien="MODIFIE" sens="cible">
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path

from lxml import etree

from legalize.fetcher.base import LegislativeClient

logger = logging.getLogger(__name__)


def _id_to_subpath(legi_id: str) -> str:
    """Converts a LEGI ID to its subpath in the dump.

    Actual format verified with real dump (2025-07-13):
    - 12 numeric digits, but only the first 10 are used in the path (5 pairs)
    - The last 2 digits are implicit in the filename

    LEGITEXT000006071194 → LEGI/TEXT/00/00/06/07/11/LEGITEXT000006071194.xml
    LEGIARTI000006527453 → LEGI/ARTI/00/00/06/52/74/LEGIARTI000006527453.xml
    LEGISCTA000006083281 → LEGI/SCTA/00/00/06/08/32/LEGISCTA000006083281.xml
    """
    prefix = legi_id[:4]   # LEGI
    type_code = legi_id[4:8]  # TEXT, ARTI, SCTA
    digits = legi_id[8:]   # 000006083281 (12 digits)
    # Only the first 10 digits → 5 pairs for the path
    path_digits = digits[:10]
    groups = "/".join(path_digits[i:i + 2] for i in range(0, len(path_digits), 2))
    return f"{prefix}/{type_code}/{groups}/{legi_id}.xml"


def _find_text_dir(base: Path, norm_id: str) -> Path | None:
    """Finds the directory of a LEGITEXT in the dump.

    The dump organizes texts in parent folders by CID (JORFTEXT or LEGITEXT).
    Each folder contains texte/struct/, article/, section_ta/.

    Searches recursively in code_en_vigueur/ and TNC_en_vigueur/.
    """
    # Search directly in the structure by ID
    for pattern_dir in [
        "legi/global/code_et_TNC_en_vigueur/code_en_vigueur",
        "legi/global/code_et_TNC_en_vigueur/TNC_en_vigueur",
    ]:
        search_base = base / pattern_dir
        if not search_base.exists():
            continue
        # The struct is at: .../LEGITEXTXXX/texte/struct/LEGITEXTXXX.xml
        # Search by glob (the LEGITEXT can be under LEGI/TEXT/... or JORF/TEXT/...)
        for struct_path in search_base.rglob(f"texte/struct/{norm_id}.xml"):
            # struct_path = .../LEGITEXTXXX/texte/struct/LEGITEXTXXX.xml
            # Go up 3 levels: file → struct/ → texte/ → LEGITEXTXXX/
            return struct_path.parent.parent.parent
    return None


class LEGIClient(LegislativeClient):
    """Reads norms from the local LEGI database dump.

    Does not make HTTP requests. Works with the decompressed XML dump.
    get_texto() builds a combined XML with structure + inline articles.
    """

    def __init__(self, legi_dir: str | Path):
        self._base = Path(legi_dir)
        # Cache of found text directories
        self._text_dir_cache: dict[str, Path | None] = {}

    def get_texto(self, norm_id: str) -> bytes:
        """Builds combined XML with structure + article content.

        Reads the structure file (TEXTELR) and embeds the content
        of each referenced article. The result is a <legi_combined> XML
        that LEGITextParser knows how to parse.
        """
        text_dir = self._get_text_dir(norm_id)
        struct_path = text_dir / "texte" / "struct" / f"{norm_id}.xml"
        struct_tree = etree.parse(str(struct_path))
        struct_root = struct_tree.getroot()

        combined = etree.Element("legi_combined", id=norm_id)

        # Copy META from the structure file
        meta = struct_root.find("META")
        if meta is not None:
            combined.append(copy.deepcopy(meta))

        # Walk <STRUCT> emitting sections and articles in order
        elements_el = etree.SubElement(combined, "elements")
        structure = struct_root.find("STRUCT")
        if structure is not None:
            self._walk_structure(structure, elements_el, text_dir)

        return etree.tostring(combined, encoding="utf-8", xml_declaration=True)

    def get_metadatos(self, norm_id: str) -> bytes:
        """Returns the XML from the version file (contains TITRE and full META).

        In the actual dump, the struct file does NOT have TITRE_TEXTE for codes.
        The title is in texte/version/LEGITEXTXXX.xml (tag <TEXTE_VERSION>),
        which contains META_TEXTE_VERSION with TITRE, TITREFULL, ETAT, etc.
        If version does not exist, falls back to struct.
        """
        text_dir = self._get_text_dir(norm_id)
        # Prefer version file (has TITRE)
        version_path = text_dir / "texte" / "version" / f"{norm_id}.xml"
        if version_path.exists():
            return version_path.read_bytes()
        # Fallback to struct
        struct_path = text_dir / "texte" / "struct" / f"{norm_id}.xml"
        return struct_path.read_bytes()

    def get_article(self, article_id: str) -> bytes:
        """Reads the XML of an individual article (search by subpath)."""
        subpath = _id_to_subpath(article_id)
        # The article can be under article/ in any text directory
        for article_path in self._base.rglob(f"article/{subpath}"):
            return article_path.read_bytes()
        raise FileNotFoundError(f"Article not found: {article_id}")

    def close(self) -> None:
        pass

    # ── Path resolution ──

    def _get_text_dir(self, norm_id: str) -> Path:
        """Finds the text directory in the dump (with cache)."""
        if norm_id not in self._text_dir_cache:
            self._text_dir_cache[norm_id] = _find_text_dir(self._base, norm_id)
        text_dir = self._text_dir_cache[norm_id]
        if text_dir is None:
            raise FileNotFoundError(
                f"Text not found in dump: {norm_id}. "
                f"Base: {self._base}"
            )
        return text_dir

    def _article_path_in_text(self, text_dir: Path, article_id: str) -> Path:
        """Article path relative to the text directory.

        Actual structure: {text_dir}/article/LEGI/ARTI/{aa}/{bb}/.../LEGIARTIYYY.xml
        """
        return text_dir / "article" / _id_to_subpath(article_id)

    # ── Combined XML construction ──

    def _walk_structure(
        self,
        parent: etree._Element,
        target: etree._Element,
        text_dir: Path,
    ) -> None:
        """Walks <STRUCT> or <STRUCTURE_TA> emitting sections and articles.

        In the actual dump, the structure is hierarchical:
        - texte/struct/ only has level 1 LIEN_SECTION_TA
        - Each section is defined in section_ta/LEGISCTAXXX.xml
        - section_ta files contain <STRUCTURE_TA> with sub-sections and LIEN_ART
        - Must be resolved recursively by reading section_ta files

        Emits <section> and <article> in flat document order.
        """
        for child in parent:
            tag = child.tag

            if tag == "LIEN_SECTION_TA":
                titre = (child.text or "").strip()
                etat = child.get("etat", "")
                debut = child.get("debut", "")
                fin = child.get("fin", "")
                niv = child.get("niv", "1")
                section_id = child.get("id", "")

                etree.SubElement(
                    target, "section",
                    id=section_id,
                    titre=titre,
                    niv=niv,
                    debut=debut,
                    fin=fin,
                    etat=etat,
                )

                # Resolve the section by reading its section_ta file
                self._resolve_section(text_dir, section_id, target)

            elif tag == "LIEN_ART":
                art_id = child.get("id", "")
                art_el = etree.SubElement(
                    target, "article",
                    id=art_id,
                    cid=child.get("cid", art_id),
                    num=child.get("num", ""),
                    debut=child.get("debut", ""),
                    fin=child.get("fin", ""),
                    etat=child.get("etat", ""),
                    origine=child.get("origine", ""),
                )
                self._embed_article_content(text_dir, art_id, art_el)

    def _resolve_section(
        self, text_dir: Path, section_id: str, target: etree._Element
    ) -> None:
        """Reads a section_ta file and walks its STRUCTURE_TA recursively.

        File: {text_dir}/section_ta/LEGI/SCTA/.../LEGISCTAXXX.xml
        Content: <SECTION_TA><STRUCTURE_TA> with LIEN_SECTION_TA and LIEN_ART
        """
        section_path = text_dir / "section_ta" / _id_to_subpath(section_id)
        if not section_path.exists():
            logger.debug("Section_ta not found: %s", section_id)
            return

        try:
            section_tree = etree.parse(str(section_path))
            section_root = section_tree.getroot()
            structure_ta = section_root.find("STRUCTURE_TA")
            if structure_ta is not None:
                self._walk_structure(structure_ta, target, text_dir)
        except Exception:
            logger.warning("Error reading section_ta %s", section_id, exc_info=True)

    def _embed_article_content(
        self, text_dir: Path, article_id: str, target: etree._Element
    ) -> None:
        """Reads the article XML (<ARTICLE>) and embeds CONTENU + source in target."""
        try:
            art_path = self._article_path_in_text(text_dir, article_id)
            if not art_path.exists():
                logger.debug("Article not found: %s", article_id)
                return

            art_tree = etree.parse(str(art_path))
            art_root = art_tree.getroot()

            # Embed BLOC_TEXTUEL/CONTENU
            contenu = art_root.find(".//BLOC_TEXTUEL/CONTENU")
            if contenu is not None:
                target.append(copy.deepcopy(contenu))

            # Extract modification source from LIENS
            # Actual format: <LIEN typelien="MODIFIE" sens="cible" cidtexte="...">
            liens = art_root.find(".//LIENS")
            if liens is not None:
                for lien in liens.findall("LIEN"):
                    sens = lien.get("sens", "")
                    typelien = lien.get("typelien", "")
                    # sens="cible" = this article was modified BY the lien
                    if sens == "cible" and typelien in (
                        "MODIFIE", "CREATION", "CREE",
                        "TRANSFERE", "REPLACE",
                    ):
                        etree.SubElement(
                            target, "source_modif",
                            id=lien.get("cidtexte", ""),
                            date=lien.get("datesignatexte", ""),
                            nature=lien.get("naturetexte", ""),
                        )
                        break  # Only the first relevant source

        except etree.XMLSyntaxError:
            logger.warning("Invalid XML for article %s", article_id)
        except Exception:
            logger.warning("Error reading article %s", article_id, exc_info=True)
