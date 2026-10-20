"""The source's long tail: misprints read only where every stricter reading refused the file."""

import gzip
from hashlib import sha256
import json
from pathlib import Path

import pytest

from legalize.fetcher.ie import effects, history, parser, pdf

FIXTURES = Path(__file__).parent / "fixtures/ie"
EVIDENCE = {
    r["identifier"]: r
    for r in json.loads((FIXTURES / "pdf-lenient-level-2-evidence.json").read_text())
}


def source(identifier):
    record = EVIDENCE[identifier]
    raw = gzip.decompress((FIXTURES / record["file"]).read_bytes())
    assert sha256(raw).hexdigest() == record["sha256"]
    return raw


@pytest.mark.parametrize("identifier", sorted(EVIDENCE))
def test_level_two_reads_only_files_every_stricter_reading_refuses(identifier):
    raw = source(identifier)
    for level in (0, 1):
        with pytest.raises(pdf.UnsupportedPDF):
            pdf._parse_revised_pdf(raw, lenient=level)
    paragraphs, cutoff = pdf.parse_revised_pdf(raw)
    assert cutoff and cutoff.isoformat() == EVIDENCE[identifier]["date"]


def headings(raw):
    return [p.text for p in pdf.parse_revised_pdf(raw)[0] if p.css_class == "articulo"]


def test_a_section_title_set_in_roman_still_heads_its_section():
    """Data Protection Act 2018 s. 137: 'Investigations' is not bold in this PDF."""
    titles = headings(source("IE-2018-act-7"))
    assert "137. **Investigations**" in titles
    assert len(titles) == len(set(titles))


def test_a_subsection_title_in_the_margin_is_kept_whole_before_its_subsection():
    paragraphs = pdf.parse_revised_pdf(source("IE-1957-act-6"))[0]
    texts = [p.text for p in paragraphs]
    index = texts.index("Claiming through a person.")
    assert texts[index + 1].startswith("- (5)")
    assert "Application of Act to charges for principal sums on registered land." in texts


def test_a_closing_quote_printed_as_an_opening_one_does_not_swallow_the_act():
    paragraphs = pdf.parse_revised_pdf(source("IE-2017-act-22"))[0]
    assert sum(p.css_class == "articulo" for p in paragraphs) == 77
    credit = next(p for p in paragraphs if "Credit Reviewer“ has the meaning" in p.text)
    assert credit.css_class == "parrafo"  # a definition, not a quotation block


def test_misprinted_labels_and_quotes_are_read_without_touching_other_text():
    printed = pdf._with_printed(pdf._SECTION, frozenset({"105A1"}))
    assert printed.match("105A1.—F545[...]")[1] == "105A1"
    assert printed.match("107A.—x")[1] == "107A"
    assert pdf._with_printed(pdf._SECTION, frozenset()) is pdf._SECTION
    assert pdf._DASHED_SECTION.match("72A— Where an event occurs")[1] == "72A"
    assert pdf._DASHED_SECTION.match("72.—(1) Where") is None
    assert pdf._closing_quote_delta("F4[“Credit Reviewer“ has the meaning given") == 0
    assert pdf._closing_quote_delta("of “credit servicing“ in section 28 (1)") == 0
    assert pdf._closing_quote_delta("“(aj) the Financial") == 1


def test_footnote_marks_that_differ_from_their_notes_follow_the_links_and_say_so():
    raw = (FIXTURES / "si-2021-227-linked-marks.html").read_bytes()
    text_parser = parser.ISBTextParser()
    blocks = text_parser.parse_text(raw)
    body = "\n".join(p.text for b in blocks for p in b.versions[0].paragraphs)
    assert all(f"[^{n}]:" in body for n in range(1, 7))  # six notes, each defined once
    assert "'1' → note '2'" in text_parser.source_warning
    assert "follows its link" in text_parser.source_warning
    token = parser._FOLLOW_MARKS.set(None)
    try:
        with pytest.raises(ValueError, match="disagrees with its anchor"):
            text_parser._parse_html(raw)  # the strict reading still refuses these bytes
    finally:
        parser._FOLLOW_MARKS.reset(token)


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "GIVEN under the Official Sealof the Government this 28th day of August, 1997.",
            "1997-08-28",
        ),
        (
            "shall be calculated using the unencumbered rent.”. GIVEN the 24 May 2002 JOSEPHINE",
            "2002-05-24",
        ),
        ("Arna thabhairt faoi mo láimh, 23 Samhain 2005 ______", "2005-11-23"),
        (
            "PRESENT when the Common Seal of Bord Telecom Éireann was affixed hereto this day of June, 1993.",
            None,
        ),
    ],
)
def test_a_signature_misprint_dates_an_instrument_only_when_nothing_else_does(text, expected):
    found = parser._misprinted_signature_date(text)
    assert (found.isoformat() if found else None) == expected
    assert parser._made_date(text) is None  # the strict formulas still do not read them


def test_a_sign_the_text_defines_is_a_legend_not_a_footnote():
    from legalize.models import Paragraph

    paragraphs = [
        Paragraph("parrafo", "*In this list the sign* [^*] *indicates a priority habitat type*."),
        Paragraph("parrafo", "| 2130 | Fixed coastal dunes (grey dunes)[^*] |"),
    ]
    assert history._missing_footnotes(paragraphs) == {"*"}
    assert history._legend_signs(paragraphs) == {"*"}


def test_directory_misprints_of_si_are_read_as_instruments():
    pattern = effects.re.compile(
        r"S[.,]?\s*[Il][.,]?\s*[.,]?\s*(?:Nol?\.?\s*)?(\d+),?\s*(?:(?:of\s*){1,2}|/)(\d{4})",
        effects.re.I,
    )
    for text, expected in [
        ("S.I .No. 494 of 2004, regs. 1(2), 13(c)", ("494", "2004")),
        ("S.l. No. 90 of 2013, reg. 2(d)", ("90", "2013")),
        ("S.I. No. 157 of2004, reg. 2(a)", ("157", "2004")),
        ("S.I. No. 413 of 202, regs. 1(2), 3", None),
    ]:
        found = pattern.findall(text)
        assert (found[0] if found else None) == expected, text
    assert pattern.pattern in effects.__loader__.get_source(effects.__name__)


def test_an_index_without_a_range_page_for_an_instrument_is_a_directory_omission():
    from lxml import html

    index = html.fromstring(
        b'<html><body><a href="/isbc/si1941_1-50.html">1-50</a>'
        b'<a href="/isbc/si1941_201-250.html">201-250</a></body></html>'
    )
    assert effects._effect_cells(index, "IE-1941-si-136") is None
    with pytest.raises(ValueError, match="no matching norm"):
        effects._effect_cells(
            html.fromstring(b"<html><body><p>x</p></body></html>"), "IE-1941-si-136"
        )


def test_instruments_voided_by_non_legislation_are_recorded_as_printed():
    for norm_id, reason in history._VOID_BY_NON_LEGISLATIVE_ACT.items():
        assert norm_id.startswith("IE-") and "-si-" in norm_id
        assert reason.split(":", 1)[0] in {
            "Annulled 29 May 2018",
            "Making of instrument quashed",
            "Set aside as ultra vires 27/1972, s. 3",
        }


def test_glyph_elements_are_kept_as_printed():
    from lxml import etree

    cell = etree.fromstring(
        "<p>exceed <pound/>52<nbsp/>10s. but<nbsp/>do, subsection 5<degree/><dagger/></p>"
    )
    assert parser._inline_text(cell) == "exceed £52 10s. but do, subsection 5°†"
