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


def _normal_title(value: str) -> str:
    """Compare LDBIS titles after its old grammatical article variants."""
    value = re.sub(r"\s+", " ", value).strip().casefold()
    value = re.sub(r"^законот\s+за\b", "закон за", value)
    value = re.sub(r"^уставот\b", "устав", value)
    return value


def _amended_title(value: str) -> str | None:
    """Return the law named by an LDBIS amending-act title, if any."""
    match = re.match(
        r"^(.+?)\s+за\s+(?:изменување|дополнување)(?:\s+и\s+дополнување)?\s+на\s+(.+)$",
        value.strip(),
        re.I,
    )
    if not match:
        return None
    return _normal_title(match.group(2))


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


def _apply_scope_filter(fields: dict[str, str]) -> None:
    """Keep bootstrap and dated discovery on the same LDBIS seed scope."""
    fields["Header$rcbVidPropis"] = "Закон"
    fields["Header_rcbVidPropis_ClientState"] = (
        '{"logEntries":[],"value":"4","text":"Закон"}'
    )
    fields["Header$chbSamoVazhechki"] = "on"


class LDBISClient(HttpClient):
    """Fetches LDBIS HTML cards and the linked official PDFs."""

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
        # An amending act is its own file and therefore gets exactly one
        # bootstrap commit. Its related links are the history of the law it
        # changes, not additional versions of the amending act.
        if _amended_title(current["title"]):
            return reforms

        seen: set[str] = {norm_id}
        for related_id in current["chain"]:
            if related_id in seen:
                continue
            seen.add(related_id)
            related = parse_card(self.get_metadata(related_id), related_id)
            if _amended_title(related["title"]) != current_target:
                continue
            if not related["publication_date"]:
                continue
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

    def discover_scope(self) -> list[str]:
        """Return IDs from the official advanced-search result set.

        LDBIS is an ASP.NET WebForms application. The hidden fields are carried
        through the same POST sequence as the public search form, so discovery
        remains source-driven rather than depending on a copied local index.
        """
        session = self._session
        url = f"{self._base_url}{_SEARCH}"
        page = session.get(url, timeout=self._timeout)
        page.raise_for_status()

        fields = _form_fields(page.text)
        fields["Header$lnkNaprednoPrebaruvanje"] = "Напредно пребарување"
        page = session.post(url, data=fields, timeout=self._timeout)
        page.raise_for_status()

        source_to = date.today().isoformat()
        fields = _form_fields(page.text)
        fields.update(_date_picker_fields("Header$rdpPochetokNaPrimenaOd", "1910-07-04"))
        fields.update(_date_picker_fields("Header$rdpPochetokNaPrimenaDo", source_to))
        # The relevant corpus is seeded by active laws. Related cards below
        # add constitutional laws, constitutions, and constitutional amendments
        # without broadening discovery to the entire LDBIS catalog.
        _apply_scope_filter(fields)
        search_button = re.search(
            r'<input[^>]*type="submit"[^>]*name="([^"]+)"[^>]*value="Пребарај"',
            page.text,
            re.I,
        ) or re.search(
            r'<input[^>]*name="([^"]+)"[^>]*type="submit"[^>]*value="Пребарај"',
            page.text,
            re.I,
        )
        if not search_button:
            raise ValueError("LDBIS advanced-search button not found")
        fields[search_button.group(1)] = "Пребарај"
        page = session.post(url, data=fields, timeout=self._timeout)
        page.raise_for_status()

        flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page.text))
        total_match = re.search(r"прописи \d+ до \d+ од (\d+)", flat)
        if not total_match:
            raise ValueError("LDBIS search result count not found")
        total = total_match.group(1)
        fields = _form_fields(page.text)
        fields.update(
            {
                "__EVENTTARGET": "Header$rgvDokumenti",
                "__EVENTARGUMENT": f"FireCommand:Header$rgvDokumenti$ctl00;PageSize;{total}",
            }
        )
        page = session.post(url, data=fields, timeout=self._timeout)
        page.raise_for_status()
        rows = re.findall(r'<tr class="rg(?:Alt)?Row"[^>]*>(.*?)</tr>', page.text, re.S)
        seed_ids = [
            match.group(1)
            for row in rows
            if (match := re.search(r'<td class="hidden">(\d+)</td>', row))
        ]
        ids = list(dict.fromkeys(seed_ids))
        seen = set(ids)
        for seed_id in seed_ids:
            card = parse_card(self.get_metadata(seed_id), seed_id)
            for related_id in card["chain"]:
                if related_id not in seen:
                    seen.add(related_id)
                    ids.append(related_id)
        return ids

    def discover_publication_date(self, target_date: date) -> list[str]:
        """Find the same active-law seed scope on one date, then its related chain."""
        session = self._session
        url = f"{self._base_url}{_SEARCH}"
        page = session.get(url, timeout=self._timeout)
        page.raise_for_status()

        fields = _form_fields(page.text)
        fields["Header$lnkNaprednoPrebaruvanje"] = "Напредно пребарување"
        page = session.post(url, data=fields, timeout=self._timeout)
        page.raise_for_status()

        fields = _form_fields(page.text)
        day = target_date.isoformat()
        fields.update(_date_picker_fields("Header$rdpNaObjavuvanjeOd", day))
        fields.update(_date_picker_fields("Header$rdpNaObjavuvanjeDo", day))
        _apply_scope_filter(fields)

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
        rows = re.findall(r'<tr class="rg(?:Alt)?Row"[^>]*>(.*?)</tr>', page.text, re.S)
        if not total_match and not rows:
            return []
        if not total_match:
            raise ValueError("LDBIS date-search result count not found")

        total = total_match.group(1)
        fields = _form_fields(page.text)
        fields.update(
            {
                "__EVENTTARGET": "Header$rgvDokumenti",
                "__EVENTARGUMENT": f"FireCommand:Header$rgvDokumenti$ctl00;PageSize;{total}",
            }
        )
        page = session.post(url, data=fields, timeout=self._timeout)
        page.raise_for_status()
        rows = re.findall(r'<tr class="rg(?:Alt)?Row"[^>]*>(.*?)</tr>', page.text, re.S)
        seed_ids = [
            match.group(1)
            for row in rows
            if (match := re.search(r'<td class="hidden">(\d+)</td>', row))
        ]
        ids = list(dict.fromkeys(seed_ids))
        seen = set(ids)
        for seed_id in seed_ids:
            card = parse_card(self.get_metadata(seed_id), seed_id)
            for related_id in card["chain"]:
                if related_id not in seen:
                    seen.add(related_id)
                    ids.append(related_id)
        return ids


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
    pdf = re.search(r"/PdfFiles/([^\"'&\s]+\.pdf)", text, re.I)
    values["pdf_name"] = pdf.group(1) if pdf else ""
    values["source"] = f"{_ROOT}{_PAGE.format(norm_id=norm_id)}"
    values["chain"] = re.findall(
        r'id="Pregled_GVNadovrzani_Title_\d+"[^>]*>.*?</a>\s*</td><td class="hidden">(\d+)</td>',
        text,
        re.S | re.I,
    )
    return values
