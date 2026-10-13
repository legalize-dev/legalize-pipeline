"""LRC archived snapshots: genuine changes, layout changes and loss detection."""

import io
import json
import re
from collections import Counter
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from legalize.fetcher.ie.parser import parse_revised_html
from legalize.fetcher.ie.pdf import UnsupportedPDF, parse_revised_pdf

FIXTURES = Path(__file__).parent / "fixtures" / "ie"


@pytest.fixture(scope="module")
def snapshots():
    return {
        name: parse_revised_pdf((FIXTURES / f"archive-{name}.pdf").read_bytes())
        for name in (
            "adoptive-leave-2020",
            "adoptive-leave-2021",
            "adoptive-leave-2023",
            "digital-services-2024",
            "digital-services-2025",
            "digital-services-2026",
            "valuation-2024",
        )
    }


def _tokens(paragraphs):
    # Compare source text independently of PDF font runs and explicit URI links.
    text = " ".join(p.text for p in paragraphs)
    text = re.sub(r"\]\((?:https?://|#)[^)]+\)", "]", text)
    return re.findall(r"\w+", text.casefold())


def _words(paragraphs):
    return Counter(_tokens(paragraphs))


def _differences(pdf, html):
    a, b = _tokens(pdf), _tokens(html)
    return [
        {
            "kind": kind,
            "pdf": " ".join(a[i:j]),
            "html": " ".join(b[k:end_b]),
            "before": " ".join(a[max(0, i - 8) : i]),
            "after": " ".join(a[j : j + 8]),
        }
        for kind, i, j, k, end_b in SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
        if kind != "equal"
    ]


def test_archive_has_authentic_dated_substantive_change(snapshots):
    old, old_date = snapshots["adoptive-leave-2020"]
    new, new_date = snapshots["adoptive-leave-2021"]
    assert old_date == date(2020, 10, 14)
    assert new_date == date(2021, 4, 1)
    old_definition = next(p.text for p in old if p.text.startswith("“adopting parent” means"))
    new_definition = next(p.text for p in new if p.text.startswith("“adopting parent” means"))
    assert "employed adopting mother, adopting father or sole male adopter" in old_definition
    assert "qualifying adopter or surviving parent" in new_definition
    assert old != new


def test_editorial_cover_change_does_not_change_legal_body(snapshots):
    earlier, earlier_date = snapshots["digital-services-2024"]
    later, later_date = snapshots["digital-services-2025"]
    assert earlier_date == date(2024, 9, 2)
    assert later_date == date(2025, 6, 1)
    assert earlier == later


def test_marginal_titles_and_body_match_current_html(snapshots):
    pdf, pdf_date = snapshots["adoptive-leave-2023"]
    html, html_date = parse_revised_html(
        (FIXTURES / "sample-adoptive-leave-1995-revised.html").read_bytes()
    )
    assert pdf_date == html_date == date(2023, 7, 3)
    assert _words(pdf) == _words(html)
    assert Counter(p.css_class for p in pdf) == Counter(p.css_class for p in html)
    assert [p.text for p in pdf if p.css_class == "articulo"] == [
        p.text for p in html if p.css_class == "articulo"
    ]
    assert pdf[0].text.startswith("AN ACT TO ENTITLE FEMALE EMPLOYEES")
    assert any(p.text == "BE IT ENACTED BY THE OIREACHTAS AS FOLLOWS:" for p in pdf)
    text = "\n".join(p.text for p in pdf)
    assert "ARRANGEMENT OF SECTIONS" not in text
    assert "This Revised Act presents" not in text
    assert "ACTS REFERRED TO" not in text
    assert "as of 17 September 2026" not in text
    assert "**1.**—(1)" in text
    assert "*subsection (2A)*" in text
    assert "https://www.irishstatutebook.ie/eli/1967/act/21" in text


def test_modern_layout_retains_primary_structure_and_all_footnotes(snapshots):
    pdf, cutoff = snapshots["digital-services-2026"]
    html, html_date = parse_revised_html(
        (FIXTURES / "archive-digital-services-2026.html").read_bytes()
    )
    assert cutoff == html_date == date(2026, 1, 1)
    assert [re.match(r"\d+[A-Z]*", p.text)[0] for p in pdf if p.css_class == "articulo"] == [
        re.match(r"\d+[A-Z]*", p.text)[0] for p in html if p.css_class == "articulo"
    ]
    assert sum(p.css_class == "capitulo_tit" for p in pdf) == 10
    assert any(p.text == "SCHEDULE Oral Hearings" for p in pdf)
    assert any("16. A statement or admission made by a person" in p.text for p in pdf)
    assert any("2022[^1]" in p.text for p in pdf)
    definitions = [p.text for p in pdf if re.match(r"\[\^\d+\]:", p.text)]
    assert len(definitions) == 5
    assert "[^1]: OJ L277, 27.10.2022, p. 1" in definitions
    assert "[^4]: OJ L119, 4.5.2016, p. 1" in definitions
    # HTML omits the first footnote. Remaining token differences are the PDF's
    # physical hyphenation and marker spacing, not missing legislative passages.
    pdf_words, html_words = _words(pdf), _words(html)
    assert sum((pdf_words & html_words).values()) / sum(html_words.values()) > 0.999


def test_open_column_table_preserves_rows_and_links(snapshots):
    pdf, cutoff = snapshots["valuation-2024"]
    html, html_date = parse_revised_html((FIXTURES / "archive-valuation-2024.html").read_bytes())
    assert cutoff == html_date == date(2024, 10, 18)
    pdf_table = next(p.text for p in pdf if p.css_class == "table")
    html_table = next(p.text for p in html if p.css_class == "table")
    assert len(pdf_table.splitlines()) == len(html_table.splitlines()) == 27
    assert (
        "| 15 & 16 Vict., c. 63 | Valuation (Ireland) Act, 1852 | The whole Act (other than section 28) |"
        in pdf_table
    )
    assert (
        "| [No. 11 of 1997](https://www.irishstatutebook.ie/eli/1997/act/11) | National Cultural Institutions Act, 1997 | Section 64 |"
        in pdf_table
    )
    assert any(p.text.startswith("F132[SCHEDULE 5") for p in pdf)
    assert any(p.text == "PART 2 Commissioner of Valuation" for p in pdf)
    headings = [p.text for p in pdf if p.css_class == "articulo"]
    assert any(
        p.startswith("31. **Grounds of appeal under section 30 to be stated.") for p in headings
    )
    assert not any("Annotations" in p.text for p in pdf)
    pdf_words, html_words = _words(pdf), _words(html)
    assert sum((pdf_words & html_words).values()) / sum(html_words.values()) > 0.999


def _pages_only(filename, pages):
    with pdfium.PdfDocument(FIXTURES / filename) as source:
        with pdfium.PdfDocument.new() as subset:
            subset.import_pages(source, pages=pages)
            stream = io.BytesIO()
            subset.save(stream)
            return stream.getvalue()


def test_cover_without_body_is_rejected():
    cover = _pages_only("archive-adoptive-leave-2023.pdf", [0])
    with pytest.raises(UnsupportedPDF, match="no readable legislative body"):
        parse_revised_pdf(cover)


def test_truncated_statute_is_rejected_against_its_contents():
    truncated = _pages_only("archive-adoptive-leave-2023.pdf", list(range(6)))
    with pytest.raises(UnsupportedPDF, match="missing sections listed in its contents"):
        parse_revised_pdf(truncated)


def test_unmapped_glyph_in_legal_body_is_rejected(monkeypatch):
    import legalize.fetcher.ie.pdf as parser

    original_open = parser.pdfplumber.open

    def damaged_text_layer(*args, **kwargs):
        document = original_open(*args, **kwargs)
        char = next(c for c in document.pages[4].chars if c["top"] > 500)
        char["text"] = "(cid:42)"
        return document

    monkeypatch.setattr(parser.pdfplumber, "open", damaged_text_layer)
    with pytest.raises(UnsupportedPDF, match="Unreadable or rotated"):
        parse_revised_pdf((FIXTURES / "archive-adoptive-leave-2023.pdf").read_bytes())


@pytest.mark.parametrize("name", ["digital-services-2026", "valuation-2024"])
def test_every_crossformat_text_difference_is_accounted_for(name, snapshots):
    pdf, _ = snapshots[name]
    html, _ = parse_revised_html((FIXTURES / f"archive-{name}.html").read_bytes())
    report = json.loads((FIXTURES / "archive-comparison.json").read_text())
    expected = [
        {k: v for k, v in difference.items() if k != "cause"}
        for difference in report[name]["differences"]
    ]
    assert _differences(pdf, html) == expected


def test_archived_quotes_and_lists_render_without_code_blocks(snapshots):
    from markdown_it import MarkdownIt
    from legalize.transformer.markdown import render_paragraphs

    for name, (paragraphs, _) in snapshots.items():
        tokens = MarkdownIt("commonmark").parse(render_paragraphs(paragraphs))
        assert not [t.content for t in tokens if t.type in ("code_block", "fence")], name


def test_archive_and_html_share_legal_list_and_quote_hierarchy(snapshots):
    pdf, _ = snapshots["adoptive-leave-2023"]
    html, _ = parse_revised_html(
        (FIXTURES / "sample-adoptive-leave-1995-revised.html").read_bytes()
    )

    def hierarchy(paragraphs):
        return [(p.css_class, re.match(r"^[ >-]*", p.text)[0]) for p in paragraphs]

    assert hierarchy(pdf) == hierarchy(html)


def test_old_archive_bare_insertion_brackets_retain_primary_sections():
    paragraphs, cutoff = parse_revised_pdf((FIXTURES / "archive-valuation-2018.pdf").read_bytes())
    assert cutoff == date(2018, 11, 9)
    headings = [p.text for p in paragraphs if p.css_class == "articulo"]
    for number, title in (
        ("28", "Revision of valua- tion lists."),
        ("34", "Appeals to Tribunal."),
        ("37", "Consideration of appeals by Tribunal."),
        ("65", "Penalties."),
    ):
        assert headings.count(f"{number}. **{title}**") == 1
    text = re.sub(r"\*+", "", "\n".join(p.text for p in paragraphs))
    assert "‘property concerned’ means a property in relation to which" in text
    assert "specified person may appeal in writing to the Tribunal against—" in text
    assert "The Tribunal shall consider an appeal made to it under section 34" in text
    assert "A person guilty of an offence under this Act" in text
    # Older plain PDFs retain the brackets but omit the editorial F number.
    assert all(f"[{number}." in text for number in ("28", "34", "37", "65"))


def test_bare_bracket_section_guard_still_rejects_a_missing_source_page():
    with pdfium.PdfDocument(FIXTURES / "archive-valuation-2018.pdf") as source:
        page_numbers = [n for n in range(len(source)) if n != 28]
    incomplete = _pages_only("archive-valuation-2018.pdf", page_numbers)
    with pytest.raises(UnsupportedPDF, match="missing sections listed in its contents: 28"):
        parse_revised_pdf(incomplete)


def test_adoption_schedule_locator_keeps_wrapped_definition():
    paragraphs, cutoff = parse_revised_pdf((FIXTURES / "archive-adoption-2018.pdf").read_bytes())
    assert cutoff == date(2018, 2, 1)
    locator = "*Section 3(1) (defi- nition of “Hague Convention”) and section 3(2).*"
    assert sum(p.text == locator for p in paragraphs) == 1
    assert any(p.css_class == "titulo_tit" and "SCHEDULE 2" in p.text for p in paragraphs)
    assert any(p.css_class == "table" for p in paragraphs)
    headings = {re.match(r"\d+[A-Z]*", p.text)[0] for p in paragraphs if p.css_class == "articulo"}
    assert {"12", "17", "18", "19", "23", "30", "31", "32", "45", "58", "58A", "61"} <= headings


def test_compound_section_label_and_quoted_marginal_titles_are_distinct():
    paragraphs, cutoff = parse_revised_pdf(
        (FIXTURES / "archive-credit-union-2018.pdf").read_bytes()
    )
    assert cutoff == date(2018, 10, 22)
    headings = [p.text for p in paragraphs if p.css_class == "articulo"]
    assert [title for title in headings if title.startswith("65.")] == [
        "65. **Provision of stabilisation support.**"
    ]
    assert any(
        p.css_class == "legal_quote" and "“65.— (1) The board of directors may—" in p.text
        for p in paragraphs
    )


def test_body_size_marginal_titles_citations_and_raster_figure():
    # Original pages 1, 77, 137, 182, 198, 345 and 622, not a complete legislative snapshot.
    paragraphs, cutoff = parse_revised_pdf(
        (FIXTURES / "archive-companies-2018-excerpt.pdf").read_bytes()
    )
    assert cutoff == date(2018, 12, 19)
    headings = [p.text for p in paragraphs if p.css_class == "articulo"]
    assert "1. **Short title and commencement**" in headings
    assert "88. **Variation of rights attached to special class- es of shares**" in headings
    assert (
        "370. **Statutory audi- tors’ report on revised finan- cial statements and revised report**"
        in headings
    )
    assert any(title.startswith("157. **Sections 158 to 165 to apply") for title in headings)
    assert "861. **Relief from liability under section 858, 859 or 860**" in headings
    assert not any(title.startswith("366.") for title in headings)
    assert any("*section 366*." in p.text for p in paragraphs)
    omitted = [i for i, p in enumerate(paragraphs) if "[image omitted]" in p.text]
    assert len(omitted) == 1
    next_heading = next(p.text for p in paragraphs[omitted[0] + 1 :] if p.css_class == "articulo")
    assert next_heading.startswith("185.")
    assert any("186." in p.text for p in paragraphs)


def test_image_only_body_page_is_rejected_instead_of_omitted(monkeypatch):
    import legalize.fetcher.ie.pdf as parser

    original_open = parser.pdfplumber.open

    def scanned_page(*args, **kwargs):
        document = original_open(*args, **kwargs)
        page = document.pages[4]
        page.objects["char"] = [c for c in page.chars if c["top"] < 78]
        return document

    monkeypatch.setattr(parser.pdfplumber, "open", scanned_page)
    with pytest.raises(UnsupportedPDF, match="Image-only Revised Act PDF body page"):
        parse_revised_pdf((FIXTURES / "archive-companies-2018-excerpt.pdf").read_bytes())


def test_pdf_extractions_are_serialized_across_fetch_workers(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock
    from time import sleep

    import legalize.fetcher.ie.pdf as parser
    from legalize.models import Paragraph

    counts = {"active": 0, "peak": 0}
    counter_lock = Lock()

    def extract(data):
        with counter_lock:
            counts["active"] += 1
            counts["peak"] = max(counts["peak"], counts["active"])
        try:
            # Release the GIL so unsynchronized worker calls would overlap.
            sleep(0.025)
            return [Paragraph("parrafo", data.decode())], date(2024, 1, 1)
        finally:
            with counter_lock:
                counts["active"] -= 1

    monkeypatch.setattr(parser, "_parse_revised_pdf", extract, raising=False)
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(parser.parse_revised_pdf, [b"a", b"b", b"c", b"d"]))
    assert counts == {"active": 0, "peak": 1}
    assert [paragraphs[0].text for paragraphs, _ in results] == ["a", "b", "c", "d"]


def test_incomplete_source_excerpt_never_inherits_the_full_pdf_exception():
    from legalize.fetcher.ie.pdf import source_warning

    data = (FIXTURES / "archive-companies-2020-incomplete-excerpt.pdf").read_bytes()
    assert source_warning(data) is None
    with pytest.raises(UnsupportedPDF, match="missing sections listed in its contents"):
        parse_revised_pdf(data)


def _incomplete_source_events(monkeypatch, *, additional_missing=()):
    import legalize.fetcher.ie.pdf as parser

    data = (FIXTURES / "archive-companies-2020-incomplete-excerpt.pdf").read_bytes()
    events, cutoff, _ = parser._read(data)
    # Limit the contents metadata to the sections represented by the original
    # excerpt pages. The full-source hash is patched separately, never the bytes.
    expected = {"1", "2", "1384", "1384A", "1385", "1386", *additional_missing}
    monkeypatch.setattr(parser, "_read", lambda _: (events, cutoff, expected))
    return data


@pytest.mark.parametrize(
    "source",
    json.loads((FIXTURES / "archive-companies-2020-source-gaps.json").read_text())["sources"],
    ids=lambda source: source["catalog_dates"][0],
)
def test_verified_source_hash_allows_only_its_exact_missing_section(monkeypatch, source):
    from types import SimpleNamespace

    import legalize.fetcher.ie.pdf as parser

    data = _incomplete_source_events(monkeypatch)
    monkeypatch.setattr(
        parser,
        "sha256",
        lambda _: SimpleNamespace(hexdigest=lambda: source["plain_sha256"]),
    )
    paragraphs, cutoff = parser.parse_revised_pdf(data)
    assert cutoff == date(2020, 1, 1)
    headings = [p.text for p in paragraphs if p.css_class == "articulo"]
    assert any(title.startswith("1384.") for title in headings)
    assert any(title.startswith("1385.") for title in headings)
    assert not any(title.startswith("1384A.") for title in headings)
    warning = parser.source_warning(data)
    assert "section 1384A" in warning
    assert "incomplete" in warning
    assert "absent from the body" in warning
    assert "not been reconstructed" in warning
    assert "original amending legislation" in warning


def test_verified_hash_does_not_allow_an_additional_missing_section(monkeypatch):
    from types import SimpleNamespace

    import legalize.fetcher.ie.pdf as parser

    data = _incomplete_source_events(monkeypatch, additional_missing={"9999"})
    digest = json.loads((FIXTURES / "archive-companies-2020-source-gaps.json").read_text())[
        "sources"
    ][0]["plain_sha256"]
    monkeypatch.setattr(parser, "sha256", lambda _: SimpleNamespace(hexdigest=lambda: digest))
    with pytest.raises(UnsupportedPDF, match="1384A, 9999"):
        parser.parse_revised_pdf(data)


def test_unknown_bytes_with_the_same_missing_section_are_rejected(monkeypatch):
    import legalize.fetcher.ie.pdf as parser

    data = _incomplete_source_events(monkeypatch)
    assert parser.source_warning(data) is None
    with pytest.raises(UnsupportedPDF, match="contents: 1384A$"):
        parser.parse_revised_pdf(data)


def test_overlapping_marginal_captions_preserve_complete_titles_and_sections():
    # Unchanged source pages, including every failed overlapping heading in the
    # August 2020 Companies PDF; this excerpt is not a complete legal snapshot.
    paragraphs, cutoff = parse_revised_pdf(
        (FIXTURES / "archive-companies-2020-overlap-excerpt.pdf").read_bytes()
    )
    assert cutoff == date(2020, 8, 21)
    headings = [p.text for p in paragraphs if p.css_class == "articulo"]
    numbers = [re.match(r"\d+[A-Z]*", heading)[0] for heading in headings]
    recovered = {
        "931A",
        "934A",
        "936A",
        "936B",
        "1110A",
        "1110E",
        "1461",
        "1490",
        "1491",
        "1493",
        "1514",
        "1518",
        "1524",
        "1533",
        "1534",
        "1540",
        "1554",
        "1555",
        "1581",
    }
    assert recovered <= set(numbers)
    assert all(numbers.count(number) == 1 for number in recovered)
    for heading in (
        "931A. **F326[Investigation by disciplinary committees of prescribed accountancy bodies**",
        "936B. **F354[Communication with the CEAOB**",
        "1110E. **F411[Non-discrimination, proportionality and transparency of costs**",
        "1491. **F549[Independence, objectivity and professional scepticism**",
        "1492. **F550[Standards for purposes of sections 1489 to 1491**",
        "1518. **F581[Supplemental provisions in relation to section 1517**",
        "1555. **F625[Supplemental provisions in relation to section 1554**",
    ):
        assert heading in headings
    text = re.sub(r"\*+", "", "\n".join(p.text for p in paragraphs))
    assert "936B. (1) The Supervisory Authority shall immediately communicate to the CEAOB" in text
    assert (
        "1110E. (1) Where an intermediary charges a fee for providing a service under this" in text
    )
    assert "1491. Statutory auditors and audit firms are subject to the independence" in text
    assert (
        "1554. (1) A person shall not disclose, except in accordance with law, information" in text
    )


def test_indented_primary_labels_keep_their_aligned_titles():
    paragraphs, cutoff = parse_revised_pdf(
        (FIXTURES / "archive-companies-2023-indent-excerpt.pdf").read_bytes()
    )
    assert cutoff == date(2023, 1, 1)
    headings = [p.text for p in paragraphs if p.css_class == "articulo"]
    assert headings.count("890A. **F505[Collection of certain data by Registrar**") == 1
    assert (
        headings.count(
            "934. **Investigation of possible breaches of standards of prescribed accountancy bodies**"
        )
        == 1
    )
    text = re.sub(r"\*+", "", "\n".join(p.text for p in paragraphs))
    assert "890A. (1) The Registrar shall collect and aggregate, on an annual basis" in text
    assert "F563[934. (1) In this section—" in text
    assert "[^3]:" in text


def test_indented_quoted_titles_do_not_become_primary_sections(monkeypatch):
    import legalize.fetcher.ie.pdf as parser

    data = (FIXTURES / "archive-companies-2023-indent-excerpt.pdf").read_bytes()
    events, cutoff, expected = parser._read(data)
    quoted_titles = {
        "F505[Collection of certain data by Registrar",
        "Investigation of possible breaches of standards of prescribed accountancy",
        "bodies",
    }
    for index, event in enumerate(events):
        if isinstance(event, parser._Line) and event.text in quoted_titles:
            events[index] = parser._Line(
                [{**c, "x0": c["x0"] + 13.32, "x1": c["x1"] + 13.32} for c in event.chars],
                event.page,
                event.links,
            )
    monkeypatch.setattr(parser, "_read", lambda _: (events, cutoff, expected | {"890A", "934"}))
    with pytest.raises(UnsupportedPDF, match="missing sections listed in its contents: 890A, 934"):
        parse_revised_pdf(data)


def test_shifted_marginal_column_preserves_the_entire_caption():
    paragraphs, cutoff = parse_revised_pdf(
        (FIXTURES / "archive-parents-2021-geometry-excerpt.pdf").read_bytes()
    )
    assert cutoff == date(2021, 4, 1)
    assert [p.text for p in paragraphs if p.css_class == "articulo"] == [
        "1. **Short title and commencement**",
        "2. **Interpretation**",
    ]
    assert any("This Act may be cited as the Parent" in p.text for p in paragraphs)
    assert not any(p.text.startswith("t ") for p in paragraphs)


def test_hanging_title_continuations_keep_indented_primary_labels():
    paragraphs, cutoff = parse_revised_pdf(
        (FIXTURES / "archive-domestic-2021-geometry-excerpt.pdf").read_bytes()
    )
    assert cutoff == date(2021, 2, 10)
    headings = [p.text for p in paragraphs if p.css_class == "articulo"]
    assert "1. **Short title and commencement**" in headings
    assert (
        "5. **Factors or circumstances to which court shall have regard in determining "
        "applications for specified orders**" in headings
    )
    for number in (14, 40, 51, 52):
        assert sum(h.startswith(f"{number}.") for h in headings) == 1
    assert any(
        "Nothing in subsection (2) shall be construed as limiting" in re.sub(r"\*+", "", p.text)
        for p in paragraphs
    )


def test_inserted_section_ten_remains_quoted_under_the_actual_section_thirteen():
    paragraphs, cutoff = parse_revised_pdf(
        (FIXTURES / "archive-treasury-2018-geometry-excerpt.pdf").read_bytes()
    )
    assert cutoff == date(2018, 12, 17)
    assert [re.match(r"\d+", p.text)[0] for p in paragraphs if p.css_class == "articulo"] == [
        "1",
        "2",
        "13",
        "14",
    ]
    assert any("13. **Disqualification of members of staff**" == p.text for p in paragraphs)
    assert any(
        p.css_class == "legal_quote" and "10." in p.text and "House of the Oireachtas" in p.text
        for p in paragraphs
    )


def test_primary_marginal_caption_closes_a_source_quote_with_a_missing_delimiter(monkeypatch):
    from legalize.fetcher.ie import pdf as parser
    from legalize.models import Paragraph

    raw = (FIXTURES / "archive-parents-2021-geometry-excerpt.pdf").read_bytes()
    events, cutoff, expected = parser._read(raw)
    index = next(i for i, e in enumerate(events) if "Interpretation 2." in e.text)
    events.insert(
        index, Paragraph("parrafo", "“A source definition without its closing delimiter;")
    )
    monkeypatch.setattr(parser, "_read", lambda _: (events, cutoff, expected | {"1", "2"}))
    paragraphs, _ = parser.parse_revised_pdf(raw)
    assert "2. **Interpretation**" in [p.text for p in paragraphs if p.css_class == "articulo"]


@pytest.mark.parametrize(
    ("name", "number", "body"),
    [
        ("merchant-1952", "10", "The Minister may make rules"),
        ("criminal-1967", "34", "Where a person tried on indictment is acquitted"),
        ("employment-1977", "9", "Where an employer proposes to create collective redundancies"),
    ],
)
def test_primary_labels_survive_annotation_spaces_and_gutter_overlap(name, number, body):
    paragraphs, cutoff = parse_revised_pdf(
        (FIXTURES / f"archive-{name}-geometry-excerpt.pdf").read_bytes()
    )
    assert cutoff is not None
    headings = [p.text for p in paragraphs if p.css_class == "articulo"]
    assert sum(h.startswith(f"{number}. **") for h in headings) == 1
    assert any(body in p.text for p in paragraphs)
