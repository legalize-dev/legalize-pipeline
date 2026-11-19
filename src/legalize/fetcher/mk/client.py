"""HTTP client for the Macedonian LDBIS legislation portal."""

from __future__ import annotations

import html
import re
from datetime import date, datetime
from typing import Any

from legalize.fetcher.base import HttpClient
from legalize.models import Reform

_ROOT = "https://ldbis.pravda.gov.mk"
_PAGE = "/PregledNaZakon.aspx?id={norm_id}"
_PDF = "/PdfFiles/{name}"
_SEARCH = "/Prebaruvanje.aspx"
_FIELD_IDS = {
    "title": "lblNaslov",
    "rank": "lblVidPropis",
    "version": "lblVerzija",
    "territory": "lblTeritorijalnoVazhenje",
    "institution": "lblInstitucija",
    "gazette": "lblSluzhbenoGlasilo",
    "issue": "lblBrojNaIzdanie",
    "publication_date": "lblDNaObjavuvanje",
    "effective_date": "lblDNaStapuvanjeVoSila",
    "applies_from": "lblPochetokNaPrimena",
    "expiry_date": "lblDNaPrestanokNaVazhenje",
}

_SERIES = {
    "Службен весник на РМ": "RM",
    "Службен весник на РСМ": "RSM",
    "Службен весник на СРМ": "SRM",
    "Службен весник на НРМ": "NRM",
    "Службен лист на СФРЈ": "SFRJ",
    "Службен лист на ФНРЈ": "FNRJ",
    "Службен лист на ДФЈ": "DFJ",
    "Службен лист на СФРЈ - Меѓународни договори": "SFRJ-MD",
    "Службен весник на ФЕМ во ДФЈ": "FEM-DFJ",
    # The fixture and a small number of older cards omit the jurisdiction.
    "Службен весник": "RM",
}


def _clean(value: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value))).strip()


# Latin letters that look Cyrillic. Some titles type one inside a Cyrillic word
# ("Академијатa", "нa", "Македониjа"), which no reader sees but which kept their
# amendments from matching. Words wholly in Latin, such as Roman numerals, stay.
_LOOKALIKES = str.maketrans("aceopxyjABCEHJKMOPTX", "асеорхујАВСЕНЈКМОРТХ")


def _cyrillic(value: str) -> str:
    """Return the title with every Latin lookalike in a Cyrillic word made Cyrillic."""
    return re.sub(
        r"\S+",
        lambda word: (
            word[0].translate(_LOOKALIKES) if re.search(r"[\u0400-\u04ff]", word[0]) else word[0]
        ),
        value,
    )


def _normal_title(value: str) -> str:
    """Return the key two LDBIS titles of the same law share, whatever their articles.

    An amending act names its law with the definite article where the law's own title
    has none, or the other way round ("Царинскиот закон" for "Царински закон",
    "угостителска дејност" for "угостителската дејност"), and 119 amending acts in scope
    reached no law until the article was dropped from every word. The ending is cut
    while it repeats, so "заштитата" and "заштита" give the same key. An adjective in
    -ен loses its e before the article ("Кривичен законик", "Кривичниот законик"), so
    -ен and -ни both end in -н, which gave the Criminal and Electoral Codes their 65
    amendments.

    Titles of one law also differ in their dashes ("бонови – ваучери" and "бонови -
    ваучери", "надворешно - трговско" and "надворешно трговско"), so a dash counts as
    a space. And an amendment since the country's renaming in 2019 names the law
    "Република Северна Македонија" where the law's own title says "Република
    Македонија", as eight do, among them two of the 2012 minimum wage law."""
    value = re.sub(r"[-\u2010-\u2015]", " ", _cyrillic(value))
    words = []
    for word in value.casefold().split():
        while len(word) > 4 and word[-2:] in ("от", "та", "то", "те"):
            word = word[:-2]
        if len(word) > 4 and word.endswith("ен"):
            word = word[:-2] + "н"
        elif len(word) > 4 and word.endswith("ни"):
            word = word[:-1]
        words.append(word)
    return " ".join(words).replace("република северна македонија", "република македонија")


# The word forms LDBIS titles use for a change. The older laws say "измени и
# дополненија", "измена" or "дополнение", and one title misspells "доплнување".
# Whole words only, so "Закон за дополнителна супервизија" is no amendment.
_CHANGE = r"(?:изменување|измени|измена|дополнување|доплнување|дополненија|дополнение)"
# A correction published in the gazette ("Исправка на Законот за ...") changes the
# text it names, as an amendment does.
_CORRECTION = re.compile(r"^Исправк[аи]\s+на\s+(.+)$", re.I)
# Corrections of these are in scope. The others in the kind correct decisions,
# rulebooks and similar acts this corpus does not hold.
_LAW_CORRECTION = re.compile(r"^Исправк[аи]\s+на\s+(?:Законот|Амандманот)\b", re.I)


def _amended_title(value: str) -> str | None:
    """Return the law an LDBIS amending act or correction changes, if the title names one.

    The change must follow the act's own kind word ("Закон за измени на ..."), so a
    ratification of a "Протокол за измена на Конвенцијата" stays a law of its own.
    One title doubles the "за". A correction of an amending act changes the law
    that act amends, so it goes into that law's history too."""
    value = _cyrillic(value.strip())
    correction = _CORRECTION.match(value)
    if correction:
        corrected = correction.group(1)
        return _amended_title(corrected) or _normal_title(corrected)
    match = re.match(
        rf"^(?:Уставен\s+)?\S+\s+(?:за\s+)+{_CHANGE}(?:\s+и\s+{_CHANGE})?\s+на\s+(.+)$",
        value,
        re.I,
    )
    if not match:
        return None
    return _normal_title(match.group(1))


def canonical_identifier(card: dict[str, Any]) -> str:
    """Build the stable Legalize identifier used by the country repository."""
    series = _SERIES.get(card["gazette"])
    if not series:
        raise ValueError(f"Unknown LDBIS gazette series: {card['gazette']!r}")
    year_match = re.search(r"(\d{4})$", card["publication_date"])
    issue_match = re.search(r"\d+", card["issue"])
    if not year_match or not issue_match:
        raise ValueError(f"LDBIS card {card['id']} lacks year or gazette issue")
    return f"{series}-{year_match.group(1)}-{issue_match.group(0)}-{card['id']}"


def _form_fields(page: str) -> dict[str, str]:
    """Collect the successful input controls used by the WebForms postback."""
    fields: dict[str, str] = {}
    for match in re.finditer(r"<input\b([^>]*)>", page, re.I):
        tag = match.group(1)
        name_match = re.search(r'name="([^"]+)"', tag, re.I)
        if not name_match:
            continue
        kind = (re.search(r'type="([^"]+)"', tag, re.I) or (None, "text"))[1].lower()
        if kind in {"submit", "image", "button"}:
            continue
        if kind in {"checkbox", "radio"} and "checked" not in tag.lower():
            continue
        value = (re.search(r'value="([^"]*)"', tag, re.I) or (None, ""))[1]
        fields[html.unescape(name_match.group(1))] = (
            html.unescape(value) if kind != "checkbox" else html.unescape(value) or "on"
        )
    return fields


def _date_picker_fields(name: str, value: str) -> dict[str, str]:
    parsed = datetime.strptime(value, "%Y-%m-%d")
    dotted = parsed.strftime("%d.%m.%Y")
    stamp = parsed.strftime("%Y-%m-%d-00-00-00")
    return {
        name: value,
        f"{name}$dateInput": dotted,
        f"{name.replace('$', '_')}_dateInput_ClientState": (
            f'{{"enabled":true,"emptyMessage":"","validationText":"{stamp}",'
            f'"valueAsString":"{stamp}","minDateStr":"1880-01-01-00-00-00",'
            f'"maxDateStr":"3000-12-31-00-00-00","lastSetTextBoxValue":"{dotted}"}}'
        ),
    }


# The record kinds the scope is seeded from, with the value LDBIS's kind list gives
# each. The search returns active records only.
_LAW_KIND = ("Закон", "4")
_CONSTITUTIONAL_KINDS = (
    ("Уставен закон", "6"),
    ("Устав", "12"),
    ("Амандман на Уставот", "13"),
)
_CORRECTION_KIND = ("Исправка (на закон или друг пропис)", "15")
# A seed's links also reach decisions, decrees, rulebooks and corrections of other
# acts, which this corpus does not hold.
_SCOPE_KINDS = {"Закон", *(kind for kind, _ in _CONSTITUTIONAL_KINDS)}


def _all_time() -> dict[str, str]:
    return {
        **_date_picker_fields("Header$rdpPochetokNaPrimenaOd", "1910-07-04"),
        **_date_picker_fields("Header$rdpPochetokNaPrimenaDo", date.today().isoformat()),
    }


class LDBISClient(HttpClient):
    """Fetches LDBIS HTML cards and the linked official PDFs."""

    # Discovery returns the numeric card id, and the file is named by the RM-<year>-<issue>-<card>
    # identifier read from the card, so the pipeline looks for a fetched norm only after parsing it,
    # and coverage finds the card id in the law's ldbis_id field.
    discovery_id_field = "ldbis_id"

    @classmethod
    def create(cls, country_config):
        source = country_config.source or {}
        return cls(
            base_url=source.get("base_url", _ROOT),
            request_timeout=source.get("request_timeout", 120),
            max_retries=source.get("max_retries", 5),
            requests_per_second=source.get("requests_per_second", 0.5),
            user_agent=source.get(
                "user_agent", "legalize-mk/1.0 (+https://github.com/legalize-dev/legalize)"
            ),
        )

    def get_metadata(self, norm_id: str) -> bytes:
        return self._get(f"{self._base_url}{_PAGE.format(norm_id=norm_id)}")

    def get_text(self, norm_id: str, meta_data: bytes | None = None) -> bytes:
        page = meta_data or self.get_metadata(norm_id)
        match = re.search(r"/PdfFiles/([^\"'&\s]+\.pdf)", page.decode("utf-8", "replace"), re.I)
        if not match:
            raise ValueError(f"LDBIS document {norm_id} has no linked PDF")
        return self._get(f"{self._base_url}{_PDF.format(name=match.group(1))}")

    def get_reforms(self, norm_id: str, meta_data: bytes) -> list[Reform]:
        """Read the complete related-version chain from the current LDBIS card.

        LDBIS publishes the chain as links to separate cards. The PDF contains
        only the current act, so deriving reforms from PDF text would silently
        lose the source timeline.
        """
        current = parse_card(meta_data, norm_id)
        current_identifier = canonical_identifier(current)
        current_target = _normal_title(current["title"])
        own_date = datetime.strptime(current["publication_date"], "%d.%m.%Y").date()
        own_effective = (
            datetime.strptime(current["effective_date"], "%d.%m.%Y").date()
            if current["effective_date"]
            else None
        )
        reforms: list[Reform] = [
            Reform(
                date=own_date,
                norm_id=current_identifier,
                affected_blocks=(),
                change_note=current["title"],
                effective_date=own_effective,
            )
        ]
        # An amending act or a correction is its own file and therefore gets
        # exactly one bootstrap commit. Its related links are the history of
        # the law it changes, not additional versions of the act itself.
        if _amended_title(current["title"]):
            return reforms

        # A law's card does not link all of its amendments (the 2012 pension
        # law's misses five), so the links on each amendment of this title
        # are followed too, until no new card turns up.
        related_cards = []
        seen = {norm_id, current["id"]}
        pending = list(current["chain"])
        while pending:
            related_id = pending.pop(0)
            if related_id in seen:
                continue
            seen.add(related_id)
            related = parse_card(self.get_metadata(related_id), related_id)
            related_cards.append(related)
            if _amended_title(related["title"]) == current_target:
                pending.extend(related["chain"])
        # The chain links every card of the same name, including earlier and
        # later enactments of a law with this title (the 2012 pension law
        # replaced the 1993 one). An amendment belongs to the latest enactment
        # published on or before it, so this file takes only the amendments
        # between its own publication and the next enactment of the title. A
        # consolidated text ("Пречистена верзија") restates the law and enacts
        # nothing, though the links on an amendment reach it, and counted it
        # would end the Electoral Code's history at its 2011 consolidation.
        later_enactments = [
            datetime.strptime(related["publication_date"], "%d.%m.%Y").date()
            for related in related_cards
            if related["publication_date"]
            and related["version"] != "Пречистена верзија"
            and not _amended_title(related["title"])
            and _normal_title(related["title"]) == current_target
        ]
        replaced_on = min((day for day in later_enactments if day > own_date), default=None)

        def in_force_here(related: dict[str, Any]) -> bool:
            if not related["publication_date"]:
                return False
            day = datetime.strptime(related["publication_date"], "%d.%m.%Y").date()
            return own_date <= day and not (replaced_on and day >= replaced_on)

        amendments = [
            related
            for related in related_cards
            if not related["corrects"]
            and _amended_title(related["title"]) == current_target
            and in_force_here(related)
        ]
        # A correction belongs here when the act it corrects is this law or one of
        # its amendments taken above, whatever its title says (_corrected_act).
        changed_here = {norm_id, current["id"], *(related["id"] for related in amendments)}
        corrections = [related for related in related_cards if related["corrects"] in changed_here]
        for related in amendments + corrections:
            reform_date = datetime.strptime(related["publication_date"], "%d.%m.%Y").date()
            effective = (
                datetime.strptime(related["effective_date"], "%d.%m.%Y").date()
                if related["effective_date"]
                else None
            )
            reforms.append(
                Reform(
                    date=reform_date,
                    norm_id=canonical_identifier(related),
                    affected_blocks=(),
                    change_note=related["title"],
                    effective_date=effective,
                )
            )
        reforms.sort(key=lambda reform: (reform.date, reform.norm_id))
        return reforms

    def amended_law(self, norm_id: str, meta_data: bytes) -> str:
        """Return the identifier of the law an amending act or a correction changes, or "".

        It is the law whose history get_reforms gives the act, the latest enactment of the
        title the act names published on or before it, as RM-2006-13-11057 is for 30409."""
        card = parse_card(meta_data, norm_id)
        law = _amended_title(card["title"])
        if not law:
            return ""
        enactments, _ = _family(
            card, law, lambda related_id: parse_card(self.get_metadata(related_id), related_id)
        )
        enacted = _enacted_before(card, enactments)
        return canonical_identifier(enacted) if enacted else ""

    def discover_scope(self) -> list[str]:
        """Return IDs from the official advanced-search result set.

        LDBIS is an ASP.NET WebForms application. The hidden fields are carried
        through the same POST sequence as the public search form, so discovery
        remains source-driven rather than depending on a copied local index.
        """
        dates = _all_time()
        laws = self._search(dates, *_LAW_KIND)
        if not laws:
            raise ValueError("LDBIS returned no active laws")
        return self._scope(dates, laws)

    def discover_publication_date(self, target_date: date) -> list[str]:
        """Find the same scope published on one date, then its related chain."""
        day = target_date.isoformat()
        dates = {
            **_date_picker_fields("Header$rdpNaObjavuvanjeOd", day),
            **_date_picker_fields("Header$rdpNaObjavuvanjeDo", day),
        }
        return self._scope(dates, self._search(dates, *_LAW_KIND))

    def _scope(self, dates: dict[str, str], laws: list[tuple[str, str]]) -> list[str]:
        """Return the seeds in the dates, then every card their links reach that belongs.

        The seeds are the active laws, the active constitutional records, and the
        active corrections of a law or a constitutional amendment whose corrected act
        (_corrected_act) belongs to the corpus (_belongs). A correction of a repealed
        law stays out with that law."""
        cards: dict[str, dict[str, Any]] = {}

        def card(card_id: str) -> dict[str, Any]:
            if card_id not in cards:
                cards[card_id] = parse_card(self.get_metadata(card_id), card_id)
            return cards[card_id]

        seeds = [row for kind in _CONSTITUTIONAL_KINDS for row in self._search(dates, *kind)]
        for card_id, title in self._search(dates, *_CORRECTION_KIND):
            if not _LAW_CORRECTION.match(title):
                continue
            corrected = card(card_id)["corrects"]
            if corrected and (
                re.match(r"^Исправк[аи]\s+на\s+Амандманот\b", title, re.I)
                or _belongs(card(corrected), card)
            ):
                seeds.append((card_id, title))
        ids = list(dict.fromkeys(card_id for card_id, _ in laws + seeds))
        seen = set(ids)
        for seed_id in ids[:]:
            for related_id in card(seed_id)["chain"]:
                if related_id not in seen:
                    seen.add(related_id)
                    if _belongs(card(related_id), card):
                        ids.append(related_id)
        return ids

    def _search(self, dates: dict[str, str], kind: str, value: str) -> list[tuple[str, str]]:
        """Return (ID, title) for every active record of one kind the advanced search lists."""
        session = self._session
        url = f"{self._base_url}{_SEARCH}"
        page = session.get(url, timeout=self._timeout)
        page.raise_for_status()

        fields = _form_fields(page.text)
        fields["Header$lnkNaprednoPrebaruvanje"] = "Напредно пребарување"
        page = session.post(url, data=fields, timeout=self._timeout)
        page.raise_for_status()

        fields = _form_fields(page.text)
        fields.update(dates)
        fields["Header$rcbVidPropis"] = kind
        fields["Header_rcbVidPropis_ClientState"] = (
            f'{{"logEntries":[],"value":"{value}","text":"{kind}"}}'
        )
        fields["Header$chbSamoVazhechki"] = "on"
        button = re.search(
            r'<input[^>]*type="submit"[^>]*name="([^"]+)"[^>]*value="Пребарај"',
            page.text,
            re.I,
        ) or re.search(
            r'<input[^>]*name="([^"]+)"[^>]*type="submit"[^>]*value="Пребарај"',
            page.text,
            re.I,
        )
        if not button:
            raise ValueError("LDBIS advanced-search button not found")
        fields[button.group(1)] = "Пребарај"
        page = session.post(url, data=fields, timeout=self._timeout)
        page.raise_for_status()

        flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page.text))
        total_match = re.search(r"прописи \d+ до \d+ од (\d+)", flat)
        # LDBIS prints the "прописи 1 до 10 од N" pager only when the results run
        # past one page, as the four active constitutional laws do not.
        if total_match:
            fields = _form_fields(page.text)
            fields.update(
                {
                    "__EVENTTARGET": "Header$rgvDokumenti",
                    "__EVENTARGUMENT": (
                        f"FireCommand:Header$rgvDokumenti$ctl00;PageSize;{total_match.group(1)}"
                    ),
                }
            )
            page = session.post(url, data=fields, timeout=self._timeout)
            page.raise_for_status()
        rows = re.findall(r'<tr class="rg(?:Alt)?Row"[^>]*>(.*?)</tr>', page.text, re.S)
        return [
            (match.group(1), _clean(match.group(2)))
            for row in rows
            if (
                match := re.search(
                    r'<td class="hidden">(\d+)</td>\s*<td[^>]*>(.*?)</td>', row, re.S
                )
            )
        ]


# Acts whose LDBIS links miss the law their title names, by card id, with the law's card id. The
# reform checker (scripts/check_mk_reform_coverage.py) found them on the rebuild of 6 November
# 2026, and each card's links were read. Neither the act nor the law links the other, so
# parse_card adds the link both ways and a correction here corrects the law named.
_LINK_FIXES = {
    "5567": "4321",  # the 1999 enterprise transformation amendment links only 5234
    "5744": "5652",  # the Ukraine tourism ratification's correction links the culture one, 5385
    "15151": "14659",  # the ICBC China loan law's correction links an IBRD repeal law, 14654
    "19842": "18463",  # the 2010 budget execution amendment links the 2009 budget law, 16234
    "28548": "22198",  # the Prespa Lake monument amendment links 22197
    "39277": "34611",  # the 2015 guarantee amendment links nothing
    "54491": "54067",  # the 2020 ratification's correction links nothing
    "66452": "57098",  # the 2024 electrical equipment waste amendment links nothing
}


def parse_card(data: bytes, norm_id: str) -> dict[str, Any]:
    text = data.decode("utf-8", "replace")
    values = {}
    for key, field_id in _FIELD_IDS.items():
        match = re.search(rf'id="Pregled_{field_id}"[^>]*>(.*?)</span>', text, re.S | re.I)
        values[key] = _clean(match.group(1)) if match else ""
    card_id = norm_id
    if not card_id.isdigit():
        action_id = re.search(r"PregledNaZakon\.aspx\?id=(\d+)", text, re.I)
        if action_id:
            card_id = action_id.group(1)
        else:
            canonical_id = re.search(r"-(\d+)$", norm_id)
            if canonical_id:
                card_id = canonical_id.group(1)
    values["id"] = card_id
    values["active"] = "aktiven.PNG" in text and "neaktiven" not in text
    # A card shows one of three badges: Активен, Неактивен or Нов. Нов, on 259 cards from 1946
    # to 2026, says nothing about force, so only Неактивен makes a law repealed.
    values["inactive"] = "neaktiven" in text
    pdf = re.search(r"/PdfFiles/([^\"'&\s]+\.pdf)", text, re.I)
    values["pdf_name"] = pdf.group(1) if pdf else ""
    values["source"] = f"{_ROOT}{_PAGE.format(norm_id=norm_id)}"
    links = re.findall(
        r'id="Pregled_GVNadovrzani_Title_\d+"[^>]*>(.*?)</a>\s*</td><td class="hidden">(\d+)</td>',
        text,
        re.S | re.I,
    )
    values["chain"] = [related_id for _, related_id in links]
    law = _LINK_FIXES.get(card_id)
    for related_id in [law, *(act for act, fixed in _LINK_FIXES.items() if fixed == card_id)]:
        if related_id and related_id not in values["chain"]:
            values["chain"].append(related_id)
    values["corrects"] = (
        law if law and _CORRECTION.match(values["title"]) else _corrected_act(values, links)
    )
    return values


def _belongs(card: dict[str, Any], card_by_id) -> bool:
    """Return whether a card LDBIS links from the scope belongs to the corpus.

    It must be a law or a constitutional record, and in force. LDBIS's active flag
    alone does not say that. It marks repealed some laws still in force, such as the
    2004 nature protection law, and the 1995 secondary education law carries an
    expiry date of 2019 though its 2025 amendments name it ("Во Законот за средното
    образование ... број 44/1995"). It also marks repealed an amendment whose law is
    still in force, such as the three 2012 to 2014 amendments of the 1994 wage
    payment law. So a card LDBIS marks repealed stays when it is a law in force by
    _in_force, or an amendment of one. An amendment's law is the latest enactment of
    its title published on or before it."""
    if card["rank"] not in _SCOPE_KINDS:
        return False
    if card["active"]:
        return True
    law = _amended_title(card["title"])
    if not card["publication_date"]:
        return False
    if not law:
        return _in_force(card, *_family(card, _normal_title(card["title"]), card_by_id))
    enactments, amendments = _family(card, law, card_by_id)
    enacted = _enacted_before(card, enactments)
    return bool(enacted) and _in_force(enacted, enactments, amendments)


def _enacted_before(card: dict[str, Any], enactments: list[dict]) -> dict[str, Any] | None:
    """Return the latest enactment published on or before a card, the law an amendment changes."""
    published = _day(card["publication_date"])
    earlier = [enacted for enacted in enactments if _day(enacted["publication_date"]) <= published]
    return max(earlier, key=lambda related: _day(related["publication_date"]), default=None)


def _day(value: str) -> date:
    return datetime.strptime(value, "%d.%m.%Y").date()


def _family(card: dict[str, Any], law: str, card_by_id) -> tuple[list[dict], list[dict]]:
    """Return the dated enactments and amendments of a title that a card's links reach.

    Every card of the title is followed, the way get_reforms follows a law's
    amendments, since a card does not link all of them. LDBIS still marks the 1993
    foreign trade law in force, though only its card links the 2002 law that replaced
    it, whose title has no dash. A consolidated text enacts nothing."""
    enactments, amendments = [card] if not _amended_title(card["title"]) else [], []
    seen = {card["id"]}
    pending = list(card["chain"])
    while pending:
        related_id = pending.pop(0)
        if related_id in seen:
            continue
        seen.add(related_id)
        related = card_by_id(related_id)
        amends = _amended_title(related["title"])
        if amends != law and (amends or _normal_title(related["title"]) != law):
            continue
        pending.extend(related["chain"])
        if not related["publication_date"] or related["version"] == "Пречистена верзија":
            continue
        (amendments if amends else enactments).append(related)
    return enactments, amendments


def _in_force(law: dict[str, Any], enactments: list[dict], amendments: list[dict]) -> bool:
    """Return whether nothing on LDBIS shows that a law has ended.

    A law has ended when a later law of its title was enacted, or when LDBIS gives it
    an expiry date and none of its amendments came after that date."""
    if law["active"]:
        return True
    published = _day(law["publication_date"])
    if any(_day(enacted["publication_date"]) > published for enacted in enactments):
        return False
    if not law["expiry_date"]:
        return True
    expired = _day(law["expiry_date"])
    return any(_day(amendment["publication_date"]) > expired for amendment in amendments)


def _corrected_act(card: dict[str, Any], links: list[tuple[str, str]]) -> str:
    """Return the ID of the act a correction corrects, or "" for any other card.

    The title cannot say which act it is. LDBIS lists one law as "осигурвање" while
    its correction says "осигурување", another correction says "прогласување" for
    "престанување", and a chain also links laws of other names. Each link reads
    "<title> <issue> (<date>)", and the corrected act is the latest one published on
    or before the correction, leaving out Constitutional Court decisions and other
    corrections. That named the right act for each law correction checked by hand
    on 2026-11-04."""
    if not _CORRECTION.match(card["title"]) or not card["publication_date"]:
        return ""
    published = datetime.strptime(card["publication_date"], "%d.%m.%Y").date()
    corrected, corrected_on = "", None
    for label, related_id in links:
        label = _clean(label)
        dated = re.search(r"\((\d{2}\.\d{2}\.\d{4})\)$", label)
        if related_id == card["id"] or not dated or re.match(r"^(?:Одлука|Исправк)", label, re.I):
            continue
        day = datetime.strptime(dated.group(1), "%d.%m.%Y").date()
        if day <= published and (corrected_on is None or day >= corrected_on):
            corrected, corrected_on = related_id, day
    return corrected
