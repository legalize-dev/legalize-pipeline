import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from legalize.countries import (
    get_client_class,
    get_discovery_class,
    get_metadata_parser,
    get_text_parser,
)
from legalize.fetcher.mk.parser import (
    LDBISMetadataParser,
    LDBISTextParser,
    _fix_ldbis_ocr_artifacts,
    _table_to_markdown,
)
from legalize.fetcher.mk.client import (
    LDBISClient,
    _amended_title,
    _belongs,
    _normal_title,
    _date_picker_fields,
    _form_fields,
    canonical_identifier,
    parse_card,
)
from legalize.fetcher.mk.discovery import LDBISDiscovery


FIXTURE = Path(__file__).parent / "fixtures" / "mk" / "card.html"


def test_metadata_parser_captures_official_fields():
    metadata = LDBISMetadataParser().parse(FIXTURE.read_bytes(), "RM-2013-187-30412")
    assert metadata.country == "mk"
    assert metadata.title == "Закон за тестирање"
    assert metadata.publication_date.isoformat() == "2013-12-30"
    assert metadata.status.value == "in_force"
    assert metadata.identifier == "RM-2013-187-30412"
    extra = dict(metadata.extra)
    assert extra["ldbis_id"] == "30412"
    assert extra["gazette_issue"] == "187/2013"
    assert extra["in_force_date"] == "2014-01-07"
    assert extra["language"] == "mk"


def test_canonical_identifier_uses_the_source_gazette_series():
    card = parse_card(FIXTURE.read_bytes(), "30412")
    assert canonical_identifier(card) == "RM-2013-187-30412"


def test_amending_card_has_only_its_own_bootstrap_reform(monkeypatch):
    card = Path(__file__).parent / "fixtures" / "mk" / "raw" / "RM-2013-187-30409.html"
    client = LDBISClient(base_url="https://ldbis.pravda.gov.mk")
    monkeypatch.setattr(client, "get_metadata", lambda _: (_ for _ in ()).throw(AssertionError()))

    reforms = client.get_reforms("30409", card.read_bytes())

    assert len(reforms) == 1
    assert reforms[0].norm_id == "RM-2013-187-30409"
    assert reforms[0].date.isoformat() == "2013-12-30"


def _card(
    title: str,
    published: str,
    issue: str,
    chain: tuple[str, ...] = (),
    version: str = "",
    kind: str = "Закон",
    active: bool = True,
    expiry: str = "",
) -> bytes:
    fields = {
        "lblNaslov": title,
        "lblVidPropis": kind,
        "lblSluzhbenoGlasilo": "Службен весник на РМ",
        "lblBrojNaIzdanie": issue,
        "lblDNaObjavuvanje": published,
        "lblVerzija": version,
        "lblDNaPrestanokNaVazhenje": expiry,
    }
    spans = "".join(f'<span id="Pregled_{key}">{value}</span>' for key, value in fields.items())
    rows = "".join(
        f'<tr><td><a id="Pregled_GVNadovrzani_Title_{n}">{label}</a></td><td class="hidden">{card_id}</td></tr>'
        for n, (card_id, label) in enumerate(
            link if isinstance(link, tuple) else (link, "x") for link in chain
        )
    )
    status = '<img src="aktiven.PNG">' if active else '<img src="neaktiven.PNG">'
    return f"<html>{spans}{status}<table>{rows}</table></html>".encode()


def _linked_cards(acts: dict[str, tuple[str, str, str]], consolidated: str = "") -> dict:
    """Build cards that all link each other the way LDBIS labels its links."""
    links = tuple(
        (card_id, f"{title} {issue} ({day})") for card_id, (title, day, issue) in acts.items()
    )
    return {
        card_id: _card(
            title, day, issue, links, "Пречистена верзија" if card_id == consolidated else ""
        )
        for card_id, (title, day, issue) in acts.items()
    }


def test_law_history_holds_only_amendments_to_that_enactment(monkeypatch):
    # LDBIS links a law's card to every card of the same name, so the 2012 pension law's
    # card also lists the 1993 law it replaced and that law's amendments.
    chain = ("3349", "3958", "25996", "27080")
    cards = {
        "3349": _card("Закон за пензиското осигурување", "30.12.1993", "80", chain),
        "3958": _card(
            "Закон за изменување на Законот за пензиското осигурување", "14.03.1995", "14", chain
        ),
        "25996": _card("Закон за пензиското осигурување", "01.08.2012", "98", chain),
        "27080": _card(
            "Закон за дополнување на Законот за пензиското осигурување", "26.12.2012", "166", chain
        ),
    }
    client = LDBISClient(base_url="https://ldbis.pravda.gov.mk")
    monkeypatch.setattr(client, "get_metadata", cards.__getitem__)

    newer = client.get_reforms("25996", cards["25996"])
    older = client.get_reforms("3349", cards["3349"])

    assert [r.norm_id for r in newer] == ["RM-2012-98-25996", "RM-2012-166-27080"]
    assert [r.norm_id for r in older] == ["RM-1993-80-3349", "RM-1995-14-3958"]


def test_law_history_follows_links_on_its_amendments(monkeypatch):
    # The 2012 pension law's card omits five of its amendments, among them 32407 of
    # 2014, which only its other amendments link.
    cards = {
        "25996": _card("Закон за пензиското осигурување", "01.08.2012", "98", ("27080",)),
        "27080": _card(
            "Закон за дополнување на Законот за пензиското осигурување",
            "26.12.2012",
            "166",
            ("25996", "32407"),
        ),
        "32407": _card(
            "Закон за изменување на Законот за пензиското осигурување", "26.06.2014", "97"
        ),
    }
    client = LDBISClient(base_url="https://ldbis.pravda.gov.mk")
    monkeypatch.setattr(client, "get_metadata", cards.__getitem__)

    reforms = client.get_reforms("25996", cards["25996"])

    assert [r.norm_id for r in reforms] == [
        "RM-2012-98-25996",
        "RM-2012-166-27080",
        "RM-2014-97-32407",
    ]


@pytest.mark.parametrize(
    ("title", "law"),
    [
        # Older and misspelt wordings of an amendment, all real LDBIS titles.
        (
            "Закон за измени и дополненија на Законот за царинската служба",
            "Закон за царинската служба",
        ),
        (
            "Закон за измена на Законот за Службата на општествено книговодство",
            "Закон за Службата на општествено книговодство",
        ),
        ("Закон за дополнение на Законот за здружениот труд", "Закон за здружениот труд"),
        (
            "Закон за изменување и доплнување на Законот за превоз на опасни материи",
            "Закон за превоз на опасни материи",
        ),
        (
            "Закон за изменување и дополнувањe на Законот за враќање на дел од данокот",
            "Закон за враќање на дел од данокот",
        ),
        (
            "Закон за за изменување и дополнување на Законот за катастар на недвижности",
            "Закон за катастар на недвижности",
        ),
        # The act names its law with the article where the law's title has none, or the reverse.
        ("Закон за изменување и дополнување на Царинскиот закон", "Царински закон"),
        ("Закон за изменување и дополнување на Кривичниот законик", "Кривичен законик"),
        ("Закон за изменување и дополнување на Изборниот законик", "Изборен законик"),
        (
            "Закон за изменување на Законот за угостителска дејност",
            "Закон за угостителската дејност",
        ),
        (
            "Закон за изменување на Законот за заштитата на природата",
            "Закон за заштита на природата",
        ),
        # A correction changes the law it names, or the law the amendment it corrects amends.
        ("Исправка на Законот за студентскиот стандард", "Закон за студентскиот стандард"),
        ("Исправки на Законот за хидрометеоролошка дејност", "Закон за хидрометеоролошка дејност"),
        (
            "Исправка на Законот за изменување и дополнување на Законот за прекршоците",
            "Закон за прекршоците",
        ),
        (
            "Исправка на Амандманот XXXI на Уставот на Република Македонија",
            "Амандман XXXI на Уставот на Република Македонија",
        ),
        # Titles of one law differ in their dashes and type Latin letters in Cyrillic words.
        (
            "Закон за изменување на Законот за издавање на вредносни бонови - ваучери",
            "Закон за издавање на вредносни бонови – ваучери",
        ),
        (
            "Закон за изменување на Законот за надворешно - трговско работење",
            "Закон за надворешно трговско работење",
        ),
        (
            "Закон за изменување и дополнување на Законот за Академијатa за судии и јавни обвинители",
            "Закон за Академијата за судии и јавни обвинители",
        ),
        ("Закон за изменување нa Законот за пасиштатa", "Закон за пасиштата"),
        (
            "Закон за изменување на Законот за минимална плата во Република Северна Македонија",
            "Закон за минимална плата во Република Македонија",
        ),
        # Laws of their own.
        ("Закон за студентскиот стандард", None),
        ("Закон за дополнителна супервизија на финансиски конгломерат", None),
        (
            "Закон за ратификација на Протоколот за изменување и дополнување на Конвенцијата за кривичните дела",
            None,
        ),
    ],
)
def test_a_title_names_the_law_it_changes(title, law):
    assert _amended_title(title) == (law and _normal_title(law))


def test_law_history_takes_its_corrections_and_those_of_its_amendments(monkeypatch):
    # The student standard law of 2013 (27500) was corrected a month later (27711).
    cards = _linked_cards(
        {
            "27500": ("Закон за студентскиот стандард", "25.01.2013", "15"),
            "27711": ("Исправка на Законот за студентскиот стандард", "26.02.2013", "27"),
            "29332": (
                "Закон за изменување на Законот за студентскиот стандард",
                "18.06.2013",
                "86",
            ),
            "29400": (
                "Исправка на Законот за изменување на Законот за студентскиот стандард",
                "01.07.2013",
                "92",
            ),
        }
    )
    client = LDBISClient(base_url="https://ldbis.pravda.gov.mk")
    monkeypatch.setattr(client, "get_metadata", cards.__getitem__)

    law = client.get_reforms("27500", cards["27500"])
    correction = client.get_reforms("27711", cards["27711"])

    assert [r.norm_id for r in law] == [
        "RM-2013-15-27500",
        "RM-2013-27-27711",
        "RM-2013-86-29332",
        "RM-2013-92-29400",
    ]
    assert [r.norm_id for r in correction] == ["RM-2013-27-27711"]


def test_a_correction_corrects_the_latest_act_published_before_it(monkeypatch):
    # LDBIS spells the voluntary health insurance law "осигурвање" and its correction
    # "осигурување". The supervision law's correction also links a later traffic
    # insurance law and a Constitutional Court decision.
    cards = {
        **_linked_cards(
            {
                "26752": ("Закон за доброволно здравствено осигурвање", "19.11.2012", "145"),
                "27264": (
                    "Исправка на Законот за доброволно здравствено осигурување",
                    "11.01.2013",
                    "7",
                ),
            }
        ),
        **_linked_cards(
            {
                "6918": ("Закон за супервизија на осигурување", "25.04.2002", "27"),
                "7647": ("Исправка на Законот за супервизија на осигурување", "27.12.2002", "98"),
                "9792": ("Закон за задолжително осигурување во сообраќајот", "19.10.2005", "88"),
                "16836": ("Одлука на Уставниот суд, У.бр.218/2008", "30.04.2009", "55"),
            }
        ),
    }
    client = LDBISClient(base_url="https://ldbis.pravda.gov.mk")
    monkeypatch.setattr(client, "get_metadata", cards.__getitem__)

    assert parse_card(cards["27264"], "27264")["corrects"] == "26752"
    assert parse_card(cards["7647"], "7647")["corrects"] == "6918"
    assert parse_card(cards["6918"], "6918")["corrects"] == ""
    assert [r.norm_id for r in client.get_reforms("26752", cards["26752"])] == [
        "RM-2012-145-26752",
        "RM-2013-7-27264",
    ]
    assert [r.norm_id for r in client.get_reforms("9792", cards["9792"])] == ["RM-2005-88-9792"]


def test_a_link_ldbis_gets_wrong_is_repaired_from_the_table(monkeypatch):
    # The 2010 budget amendment (19842) links the 2009 budget law (16234), and the correction of
    # the Ukraine tourism ratification (5744) links the culture one (5385). Neither law they
    # change links them back.
    ukraine = "Спогодбата меѓу Владата на Република Македонија и Кабинетот на министрите на Украина"
    budget = "Буџетот на Република Македонија за"
    cards = {
        **_linked_cards(
            {
                "5385": (
                    f"Закон за ратификација на {ukraine} за соработка во областа на културата",
                    "04.03.1999",
                    "13",
                ),
                "5744": (
                    f"Исправка на Законот за ратификација на {ukraine} за соработка во областа на туризмот",
                    "02.10.2000",
                    "79",
                ),
            }
        ),
        **_linked_cards(
            {
                "5652": (
                    f"Закон за ратификација на {ukraine} за соработка во областа на туризмот",
                    "17.07.2000",
                    "55",
                )
            }
        ),
        **_linked_cards(
            {
                "16234": (f"Закон за извршување на {budget} 2009 година", "29.12.2008", "166"),
                "19842": (
                    f"Закон за изменување и дополнување на Законот за извршување на {budget} 2010 година",
                    "16.07.2010",
                    "95",
                ),
            }
        ),
        **_linked_cards(
            {"18463": (f"Закон за извршување на {budget} 2010 година", "25.12.2009", "156")}
        ),
    }
    client = LDBISClient(base_url="https://ldbis.pravda.gov.mk")
    monkeypatch.setattr(client, "get_metadata", cards.__getitem__)
    history = lambda law: [r.norm_id for r in client.get_reforms(law, cards[law])]  # noqa: E731

    assert parse_card(cards["5744"], "5744")["corrects"] == "5652"
    assert history("5652") == ["RM-2000-55-5652", "RM-2000-79-5744"]
    assert history("5385") == ["RM-1999-13-5385"]
    assert history("18463") == ["RM-2009-156-18463", "RM-2010-95-19842"]
    assert history("16234") == ["RM-2008-166-16234"]


def test_a_consolidated_text_does_not_end_the_history(monkeypatch):
    # The Electoral Code's 2011 consolidated text has the code's own title.
    cards = _linked_cards(
        {
            "11974": ("Изборен законик", "31.03.2006", "40"),
            "22229": ("Изборен законик", "14.04.2011", "54"),
            "30714": ("Закон за изменување и дополнување на Изборниот законик", "24.01.2014", "14"),
        },
        consolidated="22229",
    )
    client = LDBISClient(base_url="https://ldbis.pravda.gov.mk")
    monkeypatch.setattr(client, "get_metadata", cards.__getitem__)

    assert [r.norm_id for r in client.get_reforms("11974", cards["11974"])] == [
        "RM-2006-40-11974",
        "RM-2014-14-30714",
    ]


def test_discovery_keeps_laws_in_force_with_their_amendments_and_corrections(monkeypatch):
    found = {
        "Закон": [
            ("1", "Закон за студентскиот стандард"),
            ("5", "Закон за изменување на Законот за студентскиот стандард"),
            ("17", "Закон за изменување на Законот за заштита на природата"),
        ],
        "Уставен закон": [],
        "Устав": [("11", "Устав на Република Македонија")],
        "Амандман на Уставот": [("6", "Амандман XXXI на Уставот")],
        "Исправка (на закон или друг пропис)": [
            ("2", "Исправка на Законот за студентскиот стандард"),
            ("3", "Исправка на Одлуката за тарифата"),
            ("4", "Исправка на Амандманот XXXI на Уставот на Република Македонија"),
            # The 2006 misdemeanour law is repealed, so its correction stays out with it.
            ("7", "Исправка на Законот за прекршоците"),
            # So does the correction of a repealed law an active law links.
            ("9", "Исправка на Законот за студентскиот дом"),
        ],
    }
    acts = {
        "1": ("Закон за студентскиот стандард", "25.01.2013", "15"),
        "2": ("Исправка на Законот за студентскиот стандард", "26.02.2013", "27"),
        "4": ("Исправка на Амандманот XXXI на Уставот", "20.11.2011", "150"),
        "5": ("Закон за изменување на Законот за студентскиот стандард", "18.06.2013", "86"),
        "6": ("Амандман XXXI на Уставот", "16.11.2011", "150"),
        "7": ("Исправка на Законот за прекршоците", "02.06.2006", "69"),
        "8": ("Закон за прекршоците", "19.05.2006", "62"),
        "9": ("Исправка на Законот за студентскиот дом", "10.03.1990", "9"),
        "10": ("Закон за студентскиот дом", "01.02.1990", "5"),
        "11": ("Устав на Република Македонија", "22.11.1991", "52"),
        # LDBIS marks this amendment repealed although its law is in force, and only
        # the law's other amendment links it, as with the 2012 changes of the wage law.
        "12": ("Закон за изменување на Законот за студентскиот стандард", "20.12.2013", "180"),
        "13": ("Одлука за студентскиот стандард", "01.03.2013", "30"),
        # The 1990 law of the same title and its amendment are repealed.
        "14": ("Закон за изменување на Законот за студентскиот стандард", "01.06.1995", "30"),
        "15": ("Закон за студентскиот стандард", "01.03.1990", "10"),
        "16": ("Закон за заштита на природата", "04.10.2004", "67"),
        "17": ("Закон за изменување на Законот за заштита на природата", "03.01.2025", "1"),
    }
    chains = {
        "1": ("1", "2", "5", "10", "13", "14", "15"),
        "2": ("1", "2"),
        "4": ("6", "4"),
        "5": ("1", "5", "12"),
        "6": ("6", "4"),
        "7": ("8", "7"),
        "8": ("8", "7"),
        "9": ("10", "9"),
        "10": ("1", "10", "9"),
        "11": (),
        "12": ("5", "12"),
        "13": ("1", "13"),
        "14": ("15", "14"),
        "15": ("15", "14", "1"),
        "16": ("16", "17"),
        "17": ("16", "17"),
    }
    kinds = {"6": "Амандман на Уставот", "11": "Устав", "13": "Одлука"}
    repealed = {"8", "10", "12", "14", "15", "16"}
    # LDBIS gives the repealed laws an end date. It gives the 2004 nature protection
    # law (16) none, and marks it repealed while its amendments go on.
    expired = {"8": "01.01.2015", "10": "01.01.2000", "15": "01.03.2013"}
    cards = {
        card_id: _card(
            *acts[card_id],
            tuple((j, f"{acts[j][0]} {acts[j][2]} ({acts[j][1]})") for j in chain),
            kind=kinds.get(card_id, "Закон"),
            active=card_id not in repealed,
            expiry=expired.get(card_id, ""),
        )
        for card_id, chain in chains.items()
    }
    client = LDBISClient(base_url="https://ldbis.pravda.gov.mk")
    monkeypatch.setattr(client, "_search", lambda dates, kind, value: found[kind])
    monkeypatch.setattr(client, "get_metadata", cards.__getitem__)

    expected = ["1", "5", "17", "11", "6", "2", "4", "12", "16"]
    assert client.discover_scope() == expected
    assert client.discover_publication_date(date(2013, 2, 26)) == expected
    assert [r.norm_id for r in client.get_reforms("1", cards["1"])] == [
        "RM-2013-15-1",
        "RM-2013-27-2",
        "RM-2013-86-5",
        "RM-2013-180-12",
    ]


def test_an_amendment_of_a_replaced_law_stays_out_though_ldbis_marks_the_older_one_in_force():
    # LDBIS marks the 1993 foreign trade law in force, but the 2002 law replaced it,
    # and both the 2002 law and its 2003 amendment expired in 2004. Only the 1993
    # law's card links the 2002 one, whose title has no dash.
    acts = {
        "3552": ("Закон за надворешно - трговското работење", "20.05.1993", "31", True, ""),
        "7117": (
            "Закон за изменување и дополнување на Законот за надворешно - трговско работење",
            "18.01.2002",
            "4",
            True,
            "",
        ),
        "7260": ("Закон за надворешно трговско работење", "28.06.2002", "45", False, "30.03.2004"),
        "8677": (
            "Закон за изменување и дополнување на Законот за надворешно - трговско работење",
            "05.05.2003",
            "28",
            False,
            "30.03.2004",
        ),
    }
    chains = {"3552": ("3552", "7117", "7260"), "7117": ("3552", "7117"), "7260": ("7260",)}
    chains["8677"] = ("7117",)
    cards = {
        card_id: parse_card(
            _card(title, day, issue, chains[card_id], active=active, expiry=expiry), card_id
        )
        for card_id, (title, day, issue, active, expiry) in acts.items()
    }

    assert _belongs(cards["8677"], cards.__getitem__) is False
    assert _belongs(cards["7117"], cards.__getitem__) is True


class _SearchPage:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class _SearchSession:
    """Answers the three WebForms requests of a search with one page of results."""

    def __init__(self, results):
        self.form = '<input type="submit" name="Header$btnPrebaraj" value="Пребарај" />'
        self.results = results
        self.posts = 0

    def get(self, url, timeout):
        return _SearchPage(self.form)

    def post(self, url, data, timeout):
        self.posts += 1
        return _SearchPage(self.form if self.posts == 1 else self.results)


def test_a_search_with_one_page_of_results_has_no_pager():
    # The four active constitutional laws fit on one page, which prints no
    # "прописи 1 до 10 од N" line.
    rows = "".join(
        f'<tr class="rgRow"><td class="hidden">{card_id}</td><td>{title}</td></tr>'
        for card_id, title in [
            ("43", "Уставен закон за спроведување на Уставот"),
            ("58", "Уставен закон"),
        ]
    )
    client = LDBISClient(base_url="https://ldbis.pravda.gov.mk")
    client._session = _SearchSession(f"<table>{rows}</table>")

    assert client._search({}, "Уставен закон", "6") == [
        ("43", "Уставен закон за спроведување на Уставот"),
        ("58", "Уставен закон"),
    ]
    assert client._session.posts == 2


def test_macedonia_is_registered():
    assert get_client_class("mk").__name__ == "LDBISClient"
    assert get_discovery_class("mk").__name__ == "LDBISDiscovery"
    assert get_text_parser("mk").__class__.__name__ == "LDBISTextParser"
    assert get_metadata_parser("mk").__class__.__name__ == "LDBISMetadataParser"


def test_five_captured_cards_have_metadata():
    root = FIXTURE.parent / "raw"
    cards = sorted(path for path in root.glob("*.html") if not path.name.startswith("RM-table-"))
    assert len(cards) == 5
    for card in cards:
        metadata = LDBISMetadataParser().parse(card.read_bytes(), card.stem)
        assert metadata.title
        assert metadata.publication_date
        assert metadata.source.endswith(card.stem.split("-")[-1])


def test_card_exposes_related_version_chain():
    card = parse_card(
        (FIXTURE.parent / "raw" / "RM-2013-187-30409.html").read_bytes(),
        "RM-2013-187-30409",
    )
    assert card["chain"][:3] == ["11057", "14538", "16214"]
    assert "30409" in card["chain"]


def test_webforms_scope_fields_preserve_checked_filter_and_date_state():
    fields = _form_fields(
        '<input type="checkbox" name="Header$chbSamoVazhechki" checked />'
        '<input type="text" name="ignored" value="x" />'
    )
    assert fields["Header$chbSamoVazhechki"] == "on"
    picker = _date_picker_fields("Header$rdpPochetokNaPrimenaOd", "1910-07-04")
    assert picker["Header$rdpPochetokNaPrimenaOd$dateInput"] == "04.07.1910"


def test_daily_discovery_uses_publication_date_without_rank_filter(monkeypatch):
    from datetime import date

    from legalize.fetcher.mk.client import LDBISClient

    expected = date(1993, 12, 27)
    client = LDBISClient(base_url="https://ldbis.pravda.gov.mk")
    monkeypatch.setattr(client, "discover_publication_date", lambda target: ["3455"])

    assert list(LDBISDiscovery().discover_daily(client, expected)) == ["3455"]


def test_pdf_reader_preserves_articles_and_tables():
    pytest.importorskip("pdfplumber")
    pdf_root = FIXTURE.parent / "raw"
    metadata = LDBISMetadataParser().parse(FIXTURE.read_bytes(), "30412")
    for pdf in sorted(pdf_root.glob("RM-2013*.pdf")) + [pdf_root / "RSM-2026-212-74875.pdf"]:
        blocks = LDBISTextParser().parse_text(pdf.read_bytes(), metadata=metadata)
        paragraphs = [
            p for block in blocks for version in block.versions for p in version.paragraphs
        ]
        assert len(paragraphs) > 1
    table = _table_to_markdown([["Член", "Стапка"], ["1", "18%"]])
    assert table == "| Член | Стапка |\n| --- | --- |\n| 1 | 18% |"


def test_ldbis_quote_artifacts_are_fixed_without_rewriting_serbian():
    assert (
        _fix_ldbis_ocr_artifacts("ССлужбен весник на Република Македонијам број 44/99")
        == "„Службен весник на Република Македонија“ број 44/99"
    )
    serbian = "Овај споразум ступа на снагу првог дана другог мјесеца"
    assert _fix_ldbis_ocr_artifacts(serbian) == serbian


def test_ldbis_structural_ocr_artifacts_are_fixed():
    assert _fix_ldbis_ocr_artifacts("член 2 стар 2 на овој член") == "член 2 став 2 на овој член"
    assert (
        _fix_ldbis_ocr_artifacts("Членб Доволно обработени производи")
        == "Член 6 Доволно обработени производи"
    )
    assert (
        _fix_ldbis_ocr_artifacts("Во членот 5 број 12, лицe и инспекторoт")
        == "Во членот 5 број 12, лице и инспекторот"
    )
    assert (
        _fix_ldbis_ocr_artifacts("Оваа одредба е oдземена од oвoj закон")
        == "Оваа одредба е одземена од овој закон"
    )
    assert _fix_ldbis_ocr_artifacts("Оваа е Mакедонија") == "Оваа е Македонија"
    assert _fix_ldbis_ocr_artifacts("Cnyx6eH BecHuK") == "Cnyx6eH BecHuK"
    assert (
        _fix_ldbis_ocr_artifacts("Овај споразум tл важи и MCHTM") == "Овај споразум tл важи и MCHTM"
    )
    assert _fix_ldbis_ocr_artifacts("Co Agreement") == "Co Agreement"
    assert (
        _fix_ldbis_ocr_artifacts("зборовите: мГодишна сметкао се заменуваат")
        == "зборовите: „Годишна сметка“ се заменуваат"
    )
    assert _fix_ldbis_ocr_artifacts("ЈП мМакедонски железницио") == "ЈП „Македонски железници“"


def test_post_ocr_spacing_and_homoglyph_cleanup_preserves_partner_language():
    assert (
        _fix_ldbis_ocr_artifacts("„ лице кое “; договорна страна : „ Царинска унија “")
        == "„лице кое“; договорна страна: „Царинска унија“"
    )
    # The same marks open a quote too, and the space before an opening quote is printed.
    assert (
        _fix_ldbis_ocr_artifacts('зборовите: “до 2,5%“ и „12) "Добра репутација" е, бројот “(1)“')
        == 'зборовите: “до 2,5%“ и „12) "Добра репутација" е, бројот “(1)“'
    )
    mixed = (
        "Оваа е Mакедонија. Во полскиот текст tej Umowy, a Rządem се наведува и договорната страна."
    )
    cleaned = _fix_ldbis_ocr_artifacts(mixed)
    assert "Македонија" in cleaned
    assert "tej Umowy, a Rządem" in cleaned


def test_repeated_gazette_headers_remove_glued_counters_and_year_artifacts():
    from legalize.fetcher.mk.ocr import remove_repeated_headers

    pages = [
        "body before\n150017 Cnyx6eH BecHuK Ha PM, 6p. 139 oa 7.11.2012 roauHa body after",
        "body before\n150018 Cnyx6eH BecHuK Ha PM, 6p. 139 oa 7.11.2012 roauHa body after",
    ]

    assert remove_repeated_headers(pages) == [
        "body before\nbody after",
        "body before\nbody after",
    ]


def test_pdf_parser_applies_post_fixes_before_emitting_text(monkeypatch):
    class Page:
        def extract_text(self, **kwargs):
            return "член 2 стар 2 на овој член ССлужбен весник на Република Македонија"

        def find_tables(self):
            return []

    class Pdf:
        pages = [Page()]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda data: Pdf()))

    metadata = LDBISMetadataParser().parse(FIXTURE.read_bytes(), "30412")
    blocks = LDBISTextParser().parse_text(b"fixture", metadata=metadata)
    paragraphs = [
        paragraph
        for block in blocks
        for version in block.versions
        for paragraph in version.paragraphs
    ]

    assert (
        paragraphs[0].text == "член 2 став 2 на овој член „Службен весник на Република Македонија"
    )


def test_norm_parser_runs_post_fixes_after_full_pdf_processing(monkeypatch, tmp_path):
    from legalize.fetcher.mk import ocr

    metadata = LDBISMetadataParser().parse(FIXTURE.read_bytes(), "RM-2013-187-30412")
    monkeypatch.setenv("LEGALIZE_MK_OCR_CACHE", str(tmp_path))
    monkeypatch.setattr(
        ocr,
        "parse_pdf",
        lambda data, norm_id, title, cache_dir: (
            ["член 2 стар 2 на овој член"],
            {"text_source": "ocr", "doubtful_pages": [1], "unread_pages": [2]},
        ),
    )

    blocks, enriched_metadata = LDBISTextParser().parse_norm_text(
        b"pdf", metadata.identifier, metadata
    )
    paragraph = blocks[0].versions[0].paragraphs[0]

    assert paragraph.text == "член 2 став 2 на овој член"
    assert enriched_metadata.extra[-3:] == (
        ("text_source", "ocr"),
        ("ocr_doubtful_pages", (1,)),
        ("ocr_unread_pages", (2,)),
    )


def test_local_pdf_pipeline_reads_text_layer_without_running_scanned_page_ocr(tmp_path):
    from legalize.fetcher.mk import ocr

    pdf = FIXTURE.parent / "raw" / "RM-2013-187-30409.pdf"
    lines, details = ocr.parse_pdf(
        pdf.read_bytes(),
        "30409",
        "Закон за изменување и дополнување на Законот за даночна постапка",
        tmp_path,
    )

    assert lines
    assert details["text_source"] is None
    assert not details["doubtful_pages"]
    assert not details["unread_pages"]


@pytest.mark.parametrize(
    "line",
    [
        '»Cny>x06eH BecHuk Ha PM"6p. 18 on 05.02.2008 roauHa',
        '„Службен весник на РМ"бр. 18 од 05.02.2008 година',
        '„Службен весник на РМ"бр. 18 од 05.02.2008 година !',
        '„Службен весник на РМ"бр. 18 од 05.02.2008 година 1',
        '.Cnyx6eH BecHuk Ha PM"6p. 18 oa 05.02.2008 roauHa }',
        '~CnyxxbeH BecHuk Ha PM"6p. 18 ox 05.02.2008 roauHa',
        'LCnyxbeH BecHuk Ha PM"6p. 18 oa 05.02.2008 roauHa ]',
    ],
)
def test_masthead_lines_from_rm_2008_18_14566_are_recognised(line):
    from legalize.fetcher.mk.ocr import MASTHEAD_LINE

    assert MASTHEAD_LINE.match(line)


@pytest.mark.parametrize(
    "line",
    [
        "(„Службен весник на Република Македонија“ бр. 18/2008)",
        "„Службен весник на РМ“ бр. 18/2008, се менува и гласи:",
        "објавен во „Службен весник на РМ“ бр. 18 од 05.02.2008 година, се заменува",
    ],
)
def test_citations_of_the_gazette_are_not_mastheads(line):
    from legalize.fetcher.mk.ocr import MASTHEAD_LINE

    assert not MASTHEAD_LINE.match(line)


def test_page_counters_from_rm_2008_18_14566_are_dropped():
    from legalize.fetcher.mk.ocr import without_page_counters

    lines = ["Член 1", "3o0n 114", "Текст.", "Jon 114", "55 ол 114", "Bon ll4", "400114", "Крај."]

    assert without_page_counters(lines, 114) == ["Член 1", "Текст.", "Крај."]


def test_tariff_codes_are_not_page_counters():
    from legalize.fetcher.mk.ocr import without_page_counters

    # Card 4918, an 84 page tariff schedule whose codes end in 00 like a counter's total.
    lines = ["5408 31 00", "6104 3300", "5801 35 00", "35164300", "5407 84 00", "90"]

    assert without_page_counters(lines, 84) == lines


def test_bracket_read_for_capital_i_is_restored():
    from legalize.fetcher.mk.ocr import BRACKET_FOR_I

    assert BRACKET_FOR_I.sub("I", "b) The national [PA co-ordinator (NIPAC);") == (
        "b) The national IPA co-ordinator (NIPAC);"
    )


def test_run_together_page_counters_are_dropped_once_the_total_is_known():
    from legalize.fetcher.mk.ocr import without_page_counters

    lines = ["3o0n 114", "Jon 114", "55 ол 114", "13001114", "540n114", "11301114 0д 114", "Текст."]

    assert without_page_counters(lines, 114) == ["Текст."]


def test_only_ipa_and_ipard_get_their_i_back():
    from legalize.fetcher.mk.ocr import BRACKET_FOR_I

    line = "the [PA and [PARD Agency, [IPARD, [RACVIAC) and [HS heading]"
    assert BRACKET_FOR_I.sub("I", line) == (
        "the IPA and IPARD Agency, [IPARD, [RACVIAC) and [HS heading]"
    )


def test_doubtful_and_unread_pages_are_listed_in_page_order(tmp_path, monkeypatch):
    import hashlib
    import json

    from legalize.fetcher.mk import ocr

    data = b"%PDF scanned"
    pages = tmp_path / "pages" / hashlib.sha256(data).hexdigest() / "RM-1"
    pages.mkdir(parents=True)
    for index in (102, 4, 44, 5, 56):
        record = {"confidence": 0, "words": 0, "lines": [], "unread_lines": [1]}
        (pages / f"{index}.json").write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(ocr, "scanned_pages_path", lambda path: [])
    monkeypatch.setattr(ocr, "doc_lines", lambda *args, **kwargs: [])
    monkeypatch.setattr(ocr, "law_text_only", lambda lines, title: lines)
    monkeypatch.setattr(ocr, "text_source_from_pdf", lambda path: "ocr")

    _, details = ocr.parse_pdf(data, "RM-1", "Закон", tmp_path)

    assert details["doubtful_pages"] == [5, 6, 45, 57, 103]
    assert details["unread_pages"] == [5, 6, 45, 57, 103]


def test_a_signature_read_as_letters_is_dropped():
    from legalize.fetcher.mk.ocr import scrawl

    # RM-2008-18-14566, page 2: the ambassador's signature above "Erwan FOUERE".
    assert scrawl([("p:", 0), ("wt", 0), ("on", 10), ("wh", 37), ("wy", 37)])


def test_unsure_lines_with_a_heading_a_known_word_or_another_script_are_kept():
    from legalize.fetcher.mk.ocr import scrawl

    assert not scrawl([("N", 20), ("Artikel", 30), ("22", 35)])
    assert not scrawl([("тт", 10), ("Општи", 30), ("услови", 30), ("секо", 20)])
    assert not scrawl([("مان", 10), ("سن", 10), ("مسح", 10)])
    assert not scrawl([("21", 74), ("сс", 24), ("шт", 18), ("а", 56)])


def test_a_bar_read_for_the_pronoun_i_is_restored():
    from legalize.fetcher.mk.ocr import without_noise

    def line(text):
        return " ".join(w for w, _ in without_noise([(w, 90) for w in text.split()]))

    # RM-2008-18-14566, page 3, as tesseract's English model reads it.
    assert line("| hereby declare that the Government of the Republic of Macedonia") == (
        "I hereby declare that the Government of the Republic of Macedonia"
    )
    assert line("However, | declare that the Republic of Macedonia does not accept the") == (
        "However, I declare that the Republic of Macedonia does not accept the"
    )
    assert line("| ЗАКОН ЗА ДАНОКОТ |") == "ЗАКОН ЗА ДАНОКОТ"
    assert line("| Article 5 of the Agreement") == "Article 5 of the Agreement"


def _ruled_page(rows, columns, frame=False):
    """A blank 300 dpi A4 page with a ruled grid drawn on it, as a scan would hold it."""
    import cv2
    import numpy as np

    page = np.full((3508, 2480), 255, np.uint8)
    if frame:
        cv2.rectangle(page, (100, 100), (2380, 3408), 0, 4)
    for row in range(rows + 1):
        cv2.line(page, (300, 1000 + 150 * row), (300 + 500 * columns, 1000 + 150 * row), 0, 4)
    for column in range(columns + 1):
        x = 300 + 500 * column
        cv2.line(page, (x, 1000), (x, 1000 + 150 * rows), 0, 4)
    return page


def test_a_ruled_grid_is_found_cell_by_cell_and_a_page_frame_is_not():
    from legalize.fetcher.mk.ocr import ruled_tables, table_grid

    (cells,) = ruled_tables(_ruled_page(4, 3, frame=True))
    grid = table_grid(cells)

    assert [len(row) for row in grid] == [3, 3, 3, 3]
    assert ruled_tables(_ruled_page(0, 0, frame=True)) == []


def test_a_cell_spanning_two_columns_leaves_the_second_empty():
    from legalize.fetcher.mk.ocr import table_grid

    # RM-2008-18-14566, page 103: one heading over the "1." and "2." columns.
    cells = [(0, 0, 400, 100), (0, 100, 200, 100), (205, 102, 195, 100)]

    assert table_grid(cells) == [
        [(0, 0, 400, 100), None],
        [(0, 100, 200, 100), (205, 102, 195, 100)],
    ]


def test_a_table_mark_becomes_pipe_rows_with_its_first_row_as_header():
    from legalize.fetcher.mk.ocr import PARAGRAPH, TABLE_MARK, with_tables

    def cell(text):
        return [[(word, 90) for word in text.split()]] if text else []

    # RM-2006-10-10930, page 5.
    table = [
        [cell("Република Македонија"), cell("Еквивалент на англиски јазик")],
        [cell("ДРЖАВНА ТАЈНА"), cell("TOP SECRET")],
        [cell(""), cell("")],
        [cell("ИНТЕРНО"), cell("a | b")],
    ]
    text = with_tables(f"Член 3\n{TABLE_MARK}0\nЧлен 4", [table])

    assert text.split("\n") == [
        "Член 3",
        "| Република Македонија | Еквивалент на англиски јазик |",
        "| --- | --- |",
        "| ДРЖАВНА ТАЈНА | TOP SECRET |",
        "| ИНТЕРНО | a \\| b |",
        PARAGRAPH,
        "Член 4",
    ]


def test_a_tables_rows_render_as_one_pipe_table(monkeypatch, tmp_path):
    from legalize.fetcher.mk import ocr
    from legalize.transformer.markdown import render_paragraphs

    metadata = LDBISMetadataParser().parse(FIXTURE.read_bytes(), "RM-2013-187-30412")
    monkeypatch.setenv("LEGALIZE_MK_OCR_CACHE", str(tmp_path))
    lines = ["Член 3", "| A | B |", "| --- | --- |", "| 1 | 2 |", ocr.PARAGRAPH]
    lines += ["| C |", "| --- |", ocr.PARAGRAPH, "Член 4"]
    # RM-2008-18-14566 pages 53 and 109: printed brackets read as bars are text, not rows.
    lines += [
        "|Option 3 - Adverse opinion",
        ocr.PARAGRAPH,
        "|(дел ...... од програмата во однос на: ...|",
    ]
    monkeypatch.setattr(
        ocr,
        "parse_pdf",
        lambda data, norm_id, title, cache_dir: (
            lines,
            {"text_source": "ocr", "doubtful_pages": [], "unread_pages": []},
        ),
    )

    blocks, _ = LDBISTextParser().parse_norm_text(b"pdf", metadata.identifier, metadata)
    paragraphs = [p for block in blocks for p in block.versions[0].paragraphs]

    rendered = render_paragraphs(paragraphs)
    assert "| A | B |\n| --- | --- |\n| 1 | 2 |\n\n| C |\n| --- |\n" in rendered
    assert "|Option 3 - Adverse opinion\n\n|(дел" in rendered
    assert [p.css_class for p in paragraphs][-2:] == ["parrafo", "parrafo"]


def test_article_2_of_the_pension_law_has_three_whole_list_items(monkeypatch, tmp_path):
    # The first two pages of RM-2012-98-25996, a text-layer PDF, where each list item of
    # Член 2 wraps over two printed lines.
    pdf = Path(__file__).parent / "fixtures" / "mk" / "raw" / "RM-2012-98-25996-p1-2.pdf"
    metadata = LDBISMetadataParser().parse(FIXTURE.read_bytes(), "RM-2012-98-25996")
    monkeypatch.setenv("LEGALIZE_MK_OCR_CACHE", str(tmp_path))

    blocks, _ = LDBISTextParser().parse_norm_text(pdf.read_bytes(), "25996", metadata)
    texts = [p.text for p in blocks[0].versions[0].paragraphs]
    article = texts[texts.index("Член 2") + 1 : texts.index("Член 3")]

    assert [text for text in article if text.startswith("- ")] == [
        "- задолжително пензиско и инвалидско осигурување врз основа на генерациска "
        "солидарност (во натамошниот текст: прв столб),",
        "- задолжително капитално финансирано пензиско осигурување (во натамошниот текст: "
        "втор столб) и",
        "- доброволно капитално финансирано пензиско осигурување (во натамошниот текст: "
        "трет столб).",
    ]
    assert article[0] == "(1) Системот на пензиското и инвалидското осигурување е составен од:"


def test_wrapped_lines_join_into_paragraphs_as_the_published_corpus_did(monkeypatch, tmp_path):
    from legalize.fetcher.mk import ocr

    metadata = LDBISMetadataParser().parse(FIXTURE.read_bytes(), "RM-2013-187-30412")
    monkeypatch.setenv("LEGALIZE_MK_OCR_CACHE", str(tmp_path))
    # RM-2010-50-19233, page 1, as its text layer wraps it.
    lines = [
        "ПРВ ДЕЛ",
        "ОПШТИ ОДРЕДБИ",
        "Член 1",
        "Во Законот за задолжително капитално финансирано пензиско осигурување („Службен",
        "весник на Република Македонија” број 29/2002), во членот 3 се менува и гласи:",
        "а) поединечен акционер или група акционери кои поседуваат најмалку 10% од акци-",
        "ите со право на глас;",
        "Член 5 се брише.",
        ocr.PARAGRAPH,
        "Член 2.",
    ]
    monkeypatch.setattr(
        ocr,
        "parse_pdf",
        lambda data, norm_id, title, cache_dir: (
            lines,
            {"text_source": None, "doubtful_pages": [], "unread_pages": []},
        ),
    )

    blocks, _ = LDBISTextParser().parse_norm_text(b"pdf", metadata.identifier, metadata)
    paragraphs = [(p.css_class, p.text) for p in blocks[0].versions[0].paragraphs]

    assert paragraphs == [
        ("titulo", "ПРВ ДЕЛ ОПШТИ ОДРЕДБИ"),
        ("articulo", "Член 1"),
        (
            "parrafo",
            "Во Законот за задолжително капитално финансирано пензиско осигурување („Службен "
            "весник на Република Македонија” број 29/2002), во членот 3 се менува и гласи:",
        ),
        (
            "parrafo",
            "а) поединечен акционер или група акционери кои поседуваат најмалку 10% од акциите "
            "со право на глас; Член 5 се брише.",
        ),
        ("articulo", "Член 2"),
    ]


def test_rows_a_table_drew_without_rules_are_split_apart():
    from legalize.fetcher.mk.ocr import drawn_rows

    # RM-2012-98-25996, page 14: the years and their percentages each in one cell.
    rows = [["Година", "Процент"], ["2016\n2017\n2018", "79,68\n79,36\n79,04"]]
    heading = [["Средства на задолжителниот\nпензиски фонд", "Главнина\nна друштвото"]]

    assert drawn_rows(rows) == [
        ["Година", "Процент"],
        ["2016", "79,68"],
        ["2017", "79,36"],
        ["2018", "79,04"],
    ]
    assert drawn_rows(heading) == [
        ["Средства на задолжителниот\nпензиски фонд", "Главнина\nна друштвото"]
    ]


def test_columns_split_at_gutters_and_not_at_specks_or_word_gaps():
    import numpy as np

    from legalize.fetcher.mk.ocr import text_columns

    ink = np.zeros((200, 600), np.uint8)
    ink[:, 0:100] = 255  # first column
    ink[:, 112:200] = 255  # a word gap of 12 pixels, still the first column
    ink[:, 260:262] = 255  # a speck in the gutter
    ink[:, 330:600] = 255  # the last column

    assert text_columns(ink) == [(0, 200), (330, 600)]


def test_entries_with_a_hanging_indent_are_one_row_each():
    import numpy as np

    from legalize.fetcher.mk.ocr import entry_rows

    # LDBIS 623, page 22: "1. AMPHE-" at the column's edge and "TAMINE" indented under it.
    body = np.zeros((300, 400), np.uint8)
    for top, left in [(0, 0), (40, 40), (80, 0), (120, 40), (160, 40), (200, 0)]:
        body[top : top + 20, left:300] = 255

    assert entry_rows(body, (0, 300)) == [(0, 59), (80, 179), (200, 219)]


def test_a_forms_empty_ruled_rows_belong_to_its_table():
    import cv2

    from legalize.fetcher.mk.ocr import page_tables

    # RM-2008-18-14566, page 45: cells for the header only, then rows drawn as rules alone.
    page = _ruled_page(2, 4)
    for y in (1360, 1420, 1480):
        cv2.line(page, (300, y), (2300, y), 0, 4)

    ((grid, (_, top, _, bottom)),) = page_tables(page)

    assert [len(row) for row in grid] == [4, 4]
    assert top < 1010 and bottom > 1480


def test_a_signature_with_one_surer_letter_pair_is_still_dropped():
    from legalize.fetcher.mk.ocr import scrawl

    # RM-2008-18-14566, page 2, as read again under OCR version 8.
    assert scrawl([("p:", 0), ("Le", 24), ("aE", 16), ("ws", 26), ("wy", 53)])


def test_a_cell_read_as_known_words_beats_a_surer_latin_reading():
    from legalize.fetcher.mk.ocr import known_words

    # RM-2006-10-10930, page 24: the English model was surer of the Bulgarian cell.
    assert known_words([[("СТРОГО", 80), ("СЕКРЕТНО", 85)]])
    assert not known_words([[("CTPOI'O", 90), ("CEKPETHO", 91)]])
    assert known_words([[("TOP", 95), ("SECRET", 96)]])
    assert not known_words([[("ТОР", 95), ("5ЕСКЕТ", 96)]])


def test_a_cells_own_rule_read_as_a_bar_is_dropped(monkeypatch, tmp_path):
    import numpy as np

    from legalize.fetcher.mk import ocr

    reading = {"words": ["СТРОГО", "СЕКРЕТНО", "“|"], "confs": [92, 91, 28]}
    monkeypatch.setattr(ocr, "tesseract_lines", lambda png, lang, psm, tessdata: [reading])
    gray = np.full((200, 400), 255, dtype=np.uint8)
    gray[80:120, 50:350] = 0

    cell = ocr.read_cell(gray, (0, 0, 400, 200), str(tmp_path / "cell.png"), [], "")

    # RM-2006-10-10930, page 24.
    assert cell == [[("СТРОГО", 92), ("СЕКРЕТНО", 91)]]


def test_a_run_downloads_a_partner_model_only_when_a_page_needs_it(monkeypatch, tmp_path):
    import hashlib
    import json

    from legalize.fetcher.mk import ocr

    langs = ["mkd", "eng", "osd", "bul", "ara"]
    assets = tmp_path / "assets"
    assets.mkdir()
    manifest = {
        "revision": "pinned",
        "files": {
            f"{lang}.traineddata": hashlib.sha256(lang.encode()).hexdigest() for lang in langs
        },
    }
    (assets / "tessdata_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    downloaded = []

    def curl(command, check):
        url, output = command[-3], Path(command[-1])
        downloaded.append(url.rsplit("/", 1)[1])
        output.write_bytes(url.rsplit("/", 1)[1].split(".")[0].encode())

    monkeypatch.setattr(ocr, "ASSET_ROOT", assets)
    monkeypatch.setattr(ocr.subprocess, "run", curl)
    monkeypatch.setattr(ocr.shutil, "which", lambda name: "/usr/bin/tesseract")
    ocr.fetch_model.cache_clear()

    tessdata = ocr.prepare_assets(tmp_path / "cache")
    assert downloaded == ["mkd.traineddata", "eng.traineddata", "osd.traineddata"]

    ocr.fetch_model(str(tessdata), "bul")
    ocr.fetch_model(str(tessdata), "bul")
    ocr.fetch_model.cache_clear()
    ocr.fetch_model(str(tessdata), "bul")
    assert downloaded[3:] == ["bul.traineddata"]
    assert sorted(path.name for path in tessdata.iterdir()) == [
        "bul.traineddata",
        "eng.traineddata",
        "mkd.traineddata",
        "osd.traineddata",
    ]
    ocr.fetch_model.cache_clear()


def test_a_sure_page_drops_unreadable_scraps_and_records_what_it_keeps():
    from legalize.fetcher.mk import ocr

    # Page 2 of RM-2008-18-14566 (sure at 87.5 %): the scrap under the letterhead goes, the
    # address that is not nonsense by the word list stays and marks the page doubtful, and a
    # one-word line such as a list marker stays however unsure the model was.
    scrap = [["-", 16], ["o", 1]]
    address = [["mad;", 38], ["delegation-fymmacedonia@ec", 36], ["europa.", 0], ["eu", 0]]
    marker = [["b)", 12]]
    text = [["Skopje,", 97], ["30", 97], ["October", 97], ["2007", 96]]
    page = {"confidence": 87.5, "lines": [text, scrap, address, marker]}

    kept = ocr.readable(page)

    assert kept == [text, address, marker]
    assert ocr.unreadable(address) and not ocr.unreadable(text) and not ocr.unreadable(marker)


def test_quoted_numbers_and_capitals_from_the_old_text_layer_get_their_quotes():
    from legalize.fetcher.mk.ocr import fix_quote_artifacts

    # SFRJ-1989-47-1700 and its neighbours: the text layer gives „ as С and “ as м.
    assert (
        fix_quote_artifacts("во член 70 став 1 зборовите: С10.000 до 50.000м се заменуваат")
        == "во член 70 став 1 зборовите: „10.000 до 50.000“ се заменуваат"
    )
    assert fix_quote_artifacts("процентот С60%м се заменува со процентот С100%м.") == (
        "процентот „60%“ се заменува со процентот „100%“."
    )
    assert fix_quote_artifacts("(„Службен весник на СРМм број 4/78") == (
        "(„Службен весник на СРМ“ број 4/78"
    )
    # Square metres and programme codes are not quotes.
    for text in ("од најмалку 60м2, кој", "Потпрограма С1 – Унапредување", "„објекти од 150м и"):
        assert fix_quote_artifacts(text) == text


def test_every_reviewed_ocr_fix_is_a_replacement_with_at_most_its_page():
    import json

    from legalize.fetcher.mk.ocr import ASSET_ROOT

    fixes = json.loads((ASSET_ROOT / "ocr_fixes.json").read_text(encoding="utf-8"))
    for doc_id, entries in fixes.items():
        assert doc_id.isdigit()
        for old, new, *page in entries:
            assert old and isinstance(new, str) and old != new
            assert page == [] or (len(page) == 1 and isinstance(page[0], int) and page[0] >= 1)
    # The letterhead of 14566 page 2 and the running head left on page 103 are left out.
    assert {entry[2] for entry in fixes["14566"]} == {2, 103}


def test_a_version_is_dated_by_the_card_never_by_a_date_in_the_body():
    from legalize.fetcher.mk.parser import LDBISTextParser
    from legalize.models import Paragraph

    # A deadline in the body ("до 31.12.2030") would date the version after its reform commit.
    body = [Paragraph("parrafo", "Обврската се исполнува до 31.12.2030 година.")]

    with pytest.raises(ValueError, match="card date"):
        LDBISTextParser._blocks(body)
    assert LDBISTextParser._blocks(body, date(2012, 8, 1))[0].versions[0].publication_date == date(
        2012, 8, 1
    )
