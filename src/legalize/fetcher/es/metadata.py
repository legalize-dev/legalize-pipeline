"""Parser for BOE norm metadata.

Converts the response from endpoint /api/legislacion-consolidada/id/{id}/metadatos
into a domain NormMetadata.

Actual API structure (XML):
    <response>
      <status><code>200</code></status>
      <data>
        <metadatos>
          <identificador>BOE-A-1978-31229</identificador>
          <departamento codigo="1220">Cortes Generales</departamento>
          <rango codigo="1070">Constitución</rango>
          <fecha_disposicion>19781227</fecha_disposicion>
          <titulo>Constitución Española.</titulo>
          <fecha_publicacion>19781229</fecha_publicacion>
          <fecha_vigencia>19781229</fecha_vigencia>
          <estatus_derogacion>N</estatus_derogacion>
          <estado_consolidacion codigo="3">Finalizado</estado_consolidacion>
          <url_eli>https://www.boe.es/eli/es/c/1978/12/27/(1)</url_eli>
          <url_html_consolidada>https://www.boe.es/buscar/act.php?id=BOE-A-1978-31229</url_html_consolidada>
        </metadatos>
      </data>
    </response>
"""

from __future__ import annotations

import logging
import re
from datetime import date

from lxml import etree

from legalize.fetcher._text import decode_utf8, strip_control

from legalize.models import NormMetadata, NormStatus, Rank, TextState
from legalize.fetcher.es.titulos import get_short_title

logger = logging.getLogger(__name__)

# Mapping of BOE rank texts (case-insensitive) to our enum
_RANK_TEXT_MAP: dict[str, Rank] = {
    # State-level
    "constitución": Rank.CONSTITUCION,
    "constitucion": Rank.CONSTITUCION,
    "ley orgánica": Rank.LEY_ORGANICA,
    "ley organica": Rank.LEY_ORGANICA,
    "ley": Rank.LEY,
    "real decreto-ley": Rank.REAL_DECRETO_LEY,
    "real decreto legislativo": Rank.REAL_DECRETO_LEGISLATIVO,
    "real decreto": Rank.REAL_DECRETO,
    "orden": Rank.ORDEN,
    "resolución": Rank.RESOLUCION,
    "resolucion": Rank.RESOLUCION,
    "acuerdo internacional": Rank.ACUERDO_INTERNACIONAL,
    "circular": Rank.CIRCULAR,
    "instrucción": Rank.INSTRUCCION,
    "instruccion": Rank.INSTRUCCION,
    "decreto": Rank.DECRETO,
    "acuerdo": Rank.ACUERDO,
    "reglamento": Rank.REGLAMENTO,
    # Autonomous communities (foral/regional)
    "ley foral": Rank.LEY_FORAL,
    "decreto legislativo": Rank.DECRETO_LEGISLATIVO,
    "decreto-ley": Rank.DECRETO_LEY,
    "decreto-ley foral": Rank.DECRETO_LEY_FORAL,
    "decreto foral legislativo": Rank.DECRETO_FORAL_LEGISLATIVO,
}

# Mapping of BOE rank codes to our enum.
# Current codes as of 2026 — the BOE has reassigned some legacy codes.
_RANK_CODE_MAP: dict[str, Rank] = {
    # State-level
    "1070": Rank.CONSTITUCION,
    "1290": Rank.LEY_ORGANICA,
    "1300": Rank.LEY,
    "1310": Rank.REAL_DECRETO_LEGISLATIVO,
    "1320": Rank.REAL_DECRETO_LEY,
    "1340": Rank.REAL_DECRETO,
    "1350": Rank.ORDEN,
    "1370": Rank.RESOLUCION,
    "1180": Rank.ACUERDO_INTERNACIONAL,
    "1390": Rank.CIRCULAR,
    "1410": Rank.INSTRUCCION,
    "1510": Rank.DECRETO,
    "1020": Rank.ACUERDO,
    # Autonomous communities (foral/regional)
    "1450": Rank.LEY_FORAL,
    "1470": Rank.DECRETO_LEGISLATIVO,
    "1500": Rank.DECRETO_LEY,
    "1325": Rank.DECRETO_LEY_FORAL,
    "1480": Rank.DECRETO_FORAL_LEGISLATIVO,
    # The last code of the BOE's own vocabulary
    # (`/api/datos-auxiliares/rangos`, 19 entries) that this map did not have.
    "1220": Rank.REGLAMENTO,
    # Ranks the gazette uses and the consolidated vocabulary does not list.
    # `1676` is the one that mattered: with no entry here `_parse_rank` fell
    # through to `_infer_rank_from_title`, whose first test is "constitución"
    # in the title — so `BOE-A-2026-10881`, the fourth amendment to the Spanish
    # Constitution, was typed as the Constitution itself.
    "1676": Rank.REFORMA,
    "1590": Rank.CORRECCION,
    "1240": Rank.SENTENCIA,
    "1250": Rank.AUTO,
    "63": Rank.PROVIDENCIA,
    "41": Rank.NOTA_DIPLOMATICA,
}


def _text_of(parent: etree._Element, tag: str) -> str:
    """Extracts the text of a sub-element, or '' if it does not exist."""
    el = parent.find(tag)
    if el is not None and el.text:
        return el.text.strip()
    return ""


def _code_of(parent: etree._Element, tag: str) -> str:
    """Extracts the 'codigo' attribute of a sub-element."""
    el = parent.find(tag)
    if el is not None:
        return el.get("codigo", "")
    return ""


def _parse_date_boe(text: str) -> date | None:
    """Parses BOE date: YYYYMMDD → date. Returns None for 99999999 (indefinite)."""
    if not text or len(text) < 8 or text.strip() == "99999999":
        return None
    try:
        parsed = date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        if parsed.year > 2100:
            return None
        return parsed
    except (ValueError, IndexError):
        logger.warning("Unparseable date: %s", text)
        return None


def _parse_rank(meta: etree._Element) -> Rank | None:
    """Resolves the rank from code or text."""
    code = _code_of(meta, "rango")
    if code and code in _RANK_CODE_MAP:
        return _RANK_CODE_MAP[code]

    text = _text_of(meta, "rango").lower()
    return _RANK_TEXT_MAP.get(text)


def _parse_status(meta: etree._Element) -> NormStatus:
    """Determines the validity status from BOE flags.

    BOE field values (all are S/N):
    - estatus_derogacion: S=repealed, N=not repealed
    - estatus_anulacion: S=judicially annulled, N=not annulled
    - vigencia_agotada: S=validity exhausted (temporary norms), N=still valid
    """
    repeal_status = _text_of(meta, "estatus_derogacion")
    if repeal_status in ("T", "S"):
        return NormStatus.REPEALED
    if repeal_status == "P":
        return NormStatus.PARTIALLY_REPEALED

    annulment = _text_of(meta, "estatus_anulacion")
    if annulment == "S":
        return NormStatus.ANNULLED

    exhausted = _text_of(meta, "vigencia_agotada")
    if exhausted == "S":
        return NormStatus.EXPIRED

    return NormStatus.IN_FORCE


def _infer_rank_from_title(title: str) -> Rank | None:
    """Attempts to infer the rank from the title."""
    lower = title.lower()
    if "constitución" in lower or "constitucion" in lower:
        return Rank.CONSTITUCION
    if "ley orgánica" in lower or "ley organica" in lower:
        return Rank.LEY_ORGANICA
    if "real decreto legislativo" in lower:
        return Rank.REAL_DECRETO_LEGISLATIVO
    if "decreto foral legislativo" in lower:
        return Rank.DECRETO_FORAL_LEGISLATIVO
    if "decreto legislativo" in lower:
        return Rank.DECRETO_LEGISLATIVO
    if "real decreto-ley" in lower:
        return Rank.REAL_DECRETO_LEY
    if "decreto-ley foral" in lower:
        return Rank.DECRETO_LEY_FORAL
    if "decreto-ley" in lower:
        return Rank.DECRETO_LEY
    if "ley foral" in lower:
        return Rank.LEY_FORAL
    if lower.startswith("ley "):
        return Rank.LEY
    if "real decreto" in lower and "ley" not in lower and "legislativo" not in lower:
        return Rank.REAL_DECRETO
    if lower.startswith("orden"):
        return Rank.ORDEN
    if lower.startswith("resolución") or lower.startswith("resolucion"):
        return Rank.RESOLUCION
    return None


# BOE departamento code → ELI jurisdiction code
# BOE departamento code → ELI jurisdiction code
# Some CCAA have multiple codes (name changes over time)
_DEPT_TO_JURISDICTION: dict[str, str] = {
    "8010": "es-an",  # Andalucía
    "8020": "es-ar",  # Aragón
    "8030": "es-cn",  # Canarias
    "8040": "es-cb",  # Cantabria
    "8060": "es-cm",  # Castilla-La Mancha
    "8070": "es-ct",  # Cataluña
    "8080": "es-ex",  # Extremadura
    "8090": "es-ga",  # Galicia
    "8100": "es-mc",  # Murcia
    "8110": "es-ri",  # La Rioja
    "8120": "es-ib",  # Illes Balears (código antiguo)
    "8121": "es-ib",  # Illes Balears (código actual)
    "8131": "es-md",  # Madrid
    "8140": "es-pv",  # País Vasco
    "8150": "es-as",  # Asturias
    "8161": "es-vc",  # Comunidad Valenciana
    "8162": "es-vc",  # Comunitat Valenciana (nombre en valenciano)
    "8170": "es-nc",  # Navarra
    "9531": "es-cl",  # Castilla y León
}


def _extract_jurisdiction(meta: etree._Element) -> str | None:
    """Extract autonomous community jurisdiction from BOE metadata.

    Uses the departamento code to determine the ELI jurisdiction.
    Returns None for state-level legislation (ambito=1).
    """
    scope_code = _code_of(meta, "ambito")
    if scope_code != "2":
        return None

    dept_code = _code_of(meta, "departamento")
    jurisdiction = _DEPT_TO_JURISDICTION.get(dept_code)

    if jurisdiction is None:
        # Fallback: try to extract from ELI URL (e.g., /eli/es-pv/l/...)
        eli = _text_of(meta, "url_eli")
        if eli and "/eli/" in eli:
            parts = eli.split("/eli/")[1].split("/")
            if parts and parts[0].startswith("es-"):
                jurisdiction = parts[0]

    return jurisdiction


def parse_metadata(
    xml_data: bytes,
    id_boe: str,
    diario_xml: bytes | None = None,
) -> NormMetadata:
    """Parse the XML response from the BOE /metadatos endpoint.

    Args:
        xml_data: Raw XML from /api/legislacion-consolidada/id/{id}/metadatos.
        id_boe: BOE identifier (fallback when not in XML).
        diario_xml: Optional raw XML from /diario_boe/xml.php?id={id}. When
            supplied, we pull the richer fields only present in the diary
            XML (pagina_inicial/final, url_pdf, multilingual URLs, subjects
            from <analisis><materias>, cross-references from <analisis>
            <referencias>, notes, alerts).

    Returns:
        Parsed NormMetadata.

    Raises:
        ValueError: If minimum information cannot be extracted.
    """
    # Through the scrubber, like every other XML entry point. BOE serves bytes
    # that declare one encoding and carry another, and a C1 character reaching
    # the frontmatter takes the whole YAML block down — not just its own field.
    root = etree.fromstring(strip_control(decode_utf8(xml_data)).encode("utf-8"))

    meta = root.find(".//metadatos")
    if meta is None:
        raise ValueError(f"<metadatos> not found in response for {id_boe}")

    identifier = _text_of(meta, "identificador") or id_boe
    title = _text_of(meta, "titulo") or id_boe
    short_title = get_short_title(identifier, title)
    department = _text_of(meta, "departamento")

    rank = _parse_rank(meta)
    if rank is None:
        rank = _infer_rank_from_title(title)
    if rank is None:
        logger.warning("Unrecognized rank for %s, using OTRO as fallback", id_boe)
        rank = Rank.OTRO

    pub_date = _parse_date_boe(_text_of(meta, "fecha_publicacion"))
    if pub_date is None:
        raise ValueError(f"Could not extract publication date for {id_boe}")

    effective_date = _parse_date_boe(_text_of(meta, "fecha_vigencia"))
    status = _parse_status(meta)

    source_url = (
        _text_of(meta, "url_eli")
        or _text_of(meta, "url_html_consolidada")
        or f"https://www.boe.es/buscar/act.php?id={identifier}"
    )

    jurisdiction = _extract_jurisdiction(meta)

    # Extra fields: everything BOE exposes that does not fit core NormMetadata.
    extra: list[tuple[str, str]] = []

    def add(key: str, val: str | None) -> None:
        if val:
            extra.append((key, val))

    # From /metadatos
    add("department_code", _code_of(meta, "departamento"))
    add("rank_code", _code_of(meta, "rango"))
    add("scope_code", _code_of(meta, "ambito"))
    add("official_number", _text_of(meta, "numero_oficial"))
    enactment_date = _parse_date_boe(_text_of(meta, "fecha_disposicion"))
    if enactment_date:
        add("enactment_date", enactment_date.isoformat())
    add("official_journal", _text_of(meta, "diario"))
    add("journal_issue", _text_of(meta, "diario_numero"))
    repeal_date = _parse_date_boe(_text_of(meta, "fecha_derogacion"))
    if repeal_date:
        add("repeal_date", repeal_date.isoformat())
    annulment = _text_of(meta, "estatus_anulacion")
    if annulment and annulment != "N":
        add("annulment_status", annulment)
    validity_exhausted = _text_of(meta, "vigencia_agotada")
    if validity_exhausted and validity_exhausted != "N":
        add("validity_exhausted", validity_exhausted)
    add("consolidation_status", _text_of(meta, "estado_consolidacion"))
    add("scope", _text_of(meta, "ambito"))
    add("url_eli", _text_of(meta, "url_eli"))
    add("url_html", _text_of(meta, "url_html_consolidada"))

    # From /diario_boe/xml.php (richer, if provided)
    subjects: list[str] = []
    pdf_url: str | None = None
    last_amendment: str | None = None
    if diario_xml:
        subjects, pdf_url, diario_extra, last_amendment = _parse_diario_xml(diario_xml)
        extra.extend(diario_extra)

    return NormMetadata(
        title=title,
        short_title=short_title,
        identifier=identifier,
        country="es",
        rank=rank,
        publication_date=pub_date,
        status=status,
        department=department,
        source=source_url,
        jurisdiction=jurisdiction,
        last_modified=effective_date,
        pdf_url=pdf_url,
        subjects=tuple(subjects),
        extra=tuple(extra),
        # Parsed on every norm, written only on the ones whose body does not
        # change. It also outranks the commit path: `_with_last_amendment` fills
        # this in from the reform that happens to land, and the source's own
        # answer is better than a guess made from whatever arrived last.
        last_amendment=last_amendment,
        # The promotion the country default expects. The condition is not a
        # test, it is where this function is: `/api/legislacion-consolidada`
        # answers for a norm the BOE consolidates and 404s for everything else,
        # so reaching here *is* "this norm has a consolidated text". An act
        # read off the gazette surface goes through its own parser and keeps
        # the country default, which is `as_enacted` (#66, #106).
        text_state=TextState.POINT_IN_TIME,
    )


def _reference(el) -> str:
    """One entry of the BOE's own analysis: "VERB BOE-id: what it says".

    ``<texto>`` is the half this used to drop, and it is not decoration. The
    verb is a code from a closed list, and the closed list has no word for a
    suspension: the one that stopped article 348 bis of the LSC until 31
    December 2020 is filed under "SE DICTA EN RELACIÓN", and the only place
    *suspensión* is written is in the sentence.

    Both element shapes are read — ``referencia``/``<palabra>``, which is what
    the diary XML sends, and ``<id_norma>``/``<relacion>``, which is what the
    consolidated-legislation API sends for the same block. The two endpoints
    disagree today; whichever one a caller passes, this keeps working.

    ``palabra@codigo`` is kept because it is the only language-neutral half of
    the relation: 210 is DEROGA, 270 MODIFICA, 231 SUSPENDE, 426 TRANSPONE. A
    cross-country normalisation built on the code costs nothing later; built on
    the Spanish label it costs a reprocess (#87, #129). It also delimits the
    entry, which the label alone cannot — verbs carry spaces ("SE DICTA EN
    RELACIÓN").
    """
    rid = (el.get("referencia") or el.findtext("id_norma") or "").strip()
    if not rid.startswith("BOE-"):
        return ""
    word = el.find("palabra")
    if word is None:
        word = el.find("relacion")
    verb = (word.text or "").strip() if word is not None else ""
    code = (word.get("codigo") or "").strip() if word is not None else ""
    note = " ".join((el.findtext("texto") or "").split())
    entry = " ".join(p for p in (verb, f"[{code}]" if code else "", rid) if p)
    return f"{entry}: {note}" if note else entry


# Which relation codes actually changed the act, as opposed to merely citing
# it. Measured over 367 non-consolidated Sección I acts (2026-09-04): 21 codes
# appear under <posteriores>, and only these change the words or whether they
# apply. The ones left out — 331 SE DICTA EN RELACIÓN, 440 SE DICTA DE
# CONFORMIDAD, 693 SE DICTA, 490 SE DESARROLLA, 300 SE PUBLICA, 402 SE
# INTERPRETA — are acts that invoke this one without touching it, and naming
# one as the last amendment tells a reader the text moved when it did not.
#
# 470 SE DECLARA is in: it is the Constitutional Court annulling a provision,
# which changes what is in force without rewriting a word. So are the three
# correction codes — a rectification changes the official text with legal
# effect, which is why Portugal counts them too (fetcher/pt/amendments.py).
#
# The BOE publishes no vocabulary for this: /api/datos-auxiliares/relaciones
# is a 404. So the list is measured, and a code outside it is simply not an
# amendment as far as this is concerned — the whole relation still ships in
# `references_subsequent`, which is never filtered.
_AMENDING_CODES = frozenset(
    {"201", "202", "203", "210", "245", "270", "401", "404", "406", "407", "408", "470"}
)

# BOE-A-2021-21788 -> (2021, 21788). The sequence is monotonic within a year.
_BOE_SEQ = re.compile(r"^BOE-[A-Z]{1,6}-(\d{4})-(\d+)$")


def last_amendment_of(referencias) -> str | None:
    """The most recent act that changed this one, from the BOE's own analysis.

    This is spec v0.3's ``last_amendment``, and it only means anything on a body
    that does not change: on a consolidated norm the amendments *are* the
    versions, so the value is parsed here and then never written — the emitter
    skips the key whenever the state is point-in-time.

    It is what makes the non-consolidated corpus (#66) honest. Those acts are
    published as enacted and never gain a second commit, so nothing on the
    commit path can name the act that superseded them; the BOE, however, ships
    ``<posteriores>`` inside the same ``xml.php`` response as the text, for acts
    that have no consolidated version at all. Measured over 367 of them: 127
    carry a subsequent reference and 96 carry an amending one.

    Ordered by identifier, never by document order. ``<posterior orden="">`` is
    empty on every entry seen, and the order the BOE ships is newest-first in
    only 106 of 127 acts — taking the first entry names the wrong act in 10 of
    96 (10.4 %). The identifier carries the year and a sequence monotonic within
    it, so ``(year, seq)`` is a total order needing no date parsing, no
    ``<texto>`` prose, and no second request.
    """
    best: tuple[tuple[int, int], str] | None = None
    for el in referencias.findall("posteriores/posterior"):
        # Both element shapes, for the same reason `_reference` reads both: the
        # diary puts the code on <palabra>, the consolidated API on <relacion>.
        # And `is None`, never truthiness — a childless lxml element is falsy,
        # so `find("palabra") or find("relacion")` silently drops every code.
        word = el.find("palabra")
        if word is None:
            word = el.find("relacion")
        if word is None or (word.get("codigo") or "").strip() not in _AMENDING_CODES:
            continue
        rid = (el.get("referencia") or el.findtext("id_norma") or "").strip()
        match = _BOE_SEQ.match(rid)
        if match is None:
            continue
        key = (int(match.group(1)), int(match.group(2)))
        if best is None or key > best[0]:
            best = (key, rid)
    return best[1] if best else None


def _parse_diario_xml(
    diario_xml: bytes,
) -> tuple[list[str], str | None, list[tuple[str, str]], str | None]:
    """Extract subjects, pdf_url and cross-reference metadata from the
    /diario_boe/xml.php payload.

    Returns:
        (subjects, pdf_url, extra_fields, last_amendment)
    """
    subjects: list[str] = []
    pdf_url: str | None = None
    extra: list[tuple[str, str]] = []
    last_amendment: str | None = None

    try:
        root = etree.fromstring(diario_xml)
    except Exception:
        logger.warning("diario XML parse failed")
        return subjects, pdf_url, extra, last_amendment

    dm = root.find("metadatos")
    if dm is not None:
        url_pdf = _text_of(dm, "url_pdf")
        if url_pdf:
            # Emitted once, as the core `pdf_url`. It used to ship twice under both
            # spellings, identical in 12,298 of 12,299 files (#129).
            pdf_url = f"https://www.boe.es{url_pdf}" if url_pdf.startswith("/") else url_pdf
        for name, key in (
            ("url_epub", "url_epub"),
            # ISO 639-1, not the Spanish exonym: a Belgian corpus emits url_pdf_nl /
            # url_pdf_fr and a consumer written against es keeps working (#129).
            ("url_pdf_catalan", "url_pdf_ca"),
            ("url_pdf_euskera", "url_pdf_eu"),
            ("url_pdf_gallego", "url_pdf_gl"),
            ("url_pdf_valenciano", "url_pdf_va"),
            ("pagina_inicial", "page_start"),
            ("pagina_final", "page_end"),
            ("letra_imagen", "image_marker"),
            ("estatus_legislativo", "legislative_status"),
        ):
            v = _text_of(dm, name)
            if v:
                if name.startswith("url_") and v.startswith("/"):
                    v = f"https://www.boe.es{v}"
                extra.append((key, v))

    analisis = root.find("analisis")
    if analisis is not None:
        materias = analisis.find("materias")
        if materias is not None:
            for m in materias.findall("materia"):
                if m.text:
                    subjects.append(m.text.strip())
        alertas = analisis.find("alertas")
        if alertas is not None:
            alist = [a.text.strip() for a in alertas.findall("alerta") if a.text]
            if alist:
                extra.append(("alerts", "; ".join(alist)))
        referencias = analisis.find("referencias")
        if referencias is not None:
            last_amendment = last_amendment_of(referencias)
            ants = referencias.find("anteriores")
            if ants is not None:
                refs = [_reference(a) for a in ants.findall("anterior")]
                refs = [r for r in refs if r]
                if refs:
                    extra.append(("references_previous", " | ".join(refs)))
            posts = referencias.find("posteriores")
            if posts is not None:
                # Whole, and with the sentence the BOE writes about each one.
                #
                # This was the 20 most recent, verb and id only. Both halves lost
                # the same thing: what touches a law without rewriting it. The
                # LSC has 31 subsequent references, and the one saying article
                # 348 bis was suspended until 31 December 2020 is the 31st — cut
                # by the slice — filed under "SE DICTA EN RELACIÓN", so even
                # uncut the verb alone would not have said "suspension". The word
                # is only in the text: "sobre suspensión hasta el 31 de diciembre
                # de 2020, de lo indicado de los apartados 1 y 4".
                #
                # A suspension changes no words, so it produces no version and no
                # commit: this field is the only place in the corpus it exists.
                #
                # Entries are separated by " | " rather than "; " because the
                # sentences carry semicolons of their own. Readers accept both.
                refs = [_reference(p) for p in posts.findall("posterior")]
                refs = [r for r in refs if r]
                if refs:
                    extra.append(("references_subsequent", " | ".join(refs)))
                    extra.append(("references_subsequent_count", str(len(refs))))

    return subjects, pdf_url, extra, last_amendment
