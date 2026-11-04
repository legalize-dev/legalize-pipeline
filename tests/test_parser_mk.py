import sys
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
        ("ocr_doubtful_pages", "1"),
        ("ocr_unread_pages", "2"),
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
