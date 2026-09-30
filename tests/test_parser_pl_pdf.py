"""Tests for Polish acts without HTML (all of 2025+): client fallback to PDF, discovery, parser_pdf."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from legalize.fetcher.pl.client import EliClient
from legalize.fetcher.pl.discovery import EliDiscovery
from legalize.fetcher.pl.parser import EliMetadataParser, EliTextParser
from legalize.fetcher.pl.parser_pdf import parse_pdf, tree_to_blocks

FIXTURES = Path(__file__).parent / "fixtures" / "pl"


def _load_pdf(pos: int, pub_date: str) -> bytes:
    marker = f"<!--LEGALIZE norm_id=DU-2025-{pos} pub_date={pub_date}-->\n".encode()
    return marker + (FIXTURES / f"sample-pdf-only-2025-{pos}.pdf").read_bytes()


def _paragraphs(blocks) -> list:
    return [p for b in blocks for p in b.versions[0].paragraphs]


def _render(pos: int, pub_date: str) -> str:
    from legalize.transformer.markdown import render_norm_at_date
    from legalize.transformer.xml_parser import extract_reforms

    blocks = EliTextParser().parse_text(_load_pdf(pos, pub_date))
    meta_bytes = (FIXTURES / f"sample-pdf-only-2025-{pos}.meta.json").read_bytes()
    meta = EliMetadataParser().parse(meta_bytes, f"DU-2025-{pos}")
    return render_norm_at_date(meta, blocks, extract_reforms(blocks)[0].date, include_all=True)


@pytest.fixture(scope="module")
def ustawa():
    """DU/2025/1705 — an amending statute: Art., pkt, lit., quoted provisions."""
    return EliTextParser().parse_text(_load_pdf(1705, "2025-11-07"))


@pytest.fixture(scope="module")
def rozporzadzenie():
    """DU/2025/1701 — § with pkt, lit. and tirets; "Na podstawie" as preamble."""
    return EliTextParser().parse_text(_load_pdf(1701, "2025-12-02"))


@pytest.fixture(scope="module")
def obwieszczenie():
    """DU/2025/1699 — consolidated text: ust. of the obwieszczenie, then annexes with their own §."""
    return EliTextParser().parse_text(_load_pdf(1699, "2025-12-01"))


class TestUstawaFromPdf:
    """DU/2025/1705 — an amending statute: Art., pkt, lit., quoted provisions."""

    def test_part_heading_like_html(self, ustawa):
        first = ustawa[0].versions[0].paragraphs[0]
        assert (first.css_class, first.text) == ("titulo_tit", "Treść ustawy")

    def test_articles(self, ustawa):
        titles = [b.title for b in ustawa if b.block_type == "article"]
        assert titles == ["Art. 1.", "Art. 2.", "Art. 3.", "Art. 4.", "Art. 5."]
        assert ustawa[1].versions[0].paragraphs[0].css_class == "articulo"

    def test_title_not_in_body(self, ustawa):
        texts = [p.text for p in _paragraphs(ustawa)]
        assert "USTAWA" not in texts
        assert not any(t.startswith("z dnia 7 listopada 2025 r.") for t in texts)

    def test_nested_units_indented_like_html(self, ustawa):
        texts = [p.text for p in _paragraphs(ustawa)]
        assert any(t.startswith("  1) w art. 3 w ust. 3") for t in texts)
        assert any(
            t.startswith("      a) w ust. 1 w pkt 2 lit. c otrzymuje brzmienie:") for t in texts
        )

    def test_quoted_provisions_are_blockquotes(self, ustawa):
        texts = [p.text for p in _paragraphs(ustawa)]
        assert "> „Art. 24." in texts
        # a quoted unit is not a unit of this act
        assert not any(t.startswith("1. EPS jest systemem") for t in texts)

    def test_dates_from_marker(self, ustawa):
        v = ustawa[1].versions[0]
        assert v.norm_id == "DU-2025-1705"
        assert v.publication_date == date(2025, 11, 7)

    def test_no_footnote_markers(self, ustawa):
        assert not any("[^" in p.text for p in _paragraphs(ustawa))


class TestRozporzadzenieFromPdf:
    """DU/2025/1701 — § with pkt, lit. and tirets; "Na podstawie" as preamble."""

    def test_structure(self, rozporzadzenie):
        assert [b.block_type for b in rozporzadzenie] == ["part", "preamble", "article", "article"]
        assert rozporzadzenie[0].title == "Treść rozporządzenia"
        assert rozporzadzenie[1].title.startswith("Na podstawie art. 29 ust. 10")
        assert [b.title for b in rozporzadzenie[2:]] == ["§ 1.", "§ 2."]

    def test_tirets_under_lit(self, rozporzadzenie):
        texts = [p.text for p in rozporzadzenie[2].versions[0].paragraphs]
        assert "            – uchyla się tiret drugie," in texts


class TestObwieszczenieWithAnnexesFromPdf:
    """DU/2025/1699 — consolidated text: ust. of the obwieszczenie, then annexes with their own §."""

    def test_annex_headings(self, obwieszczenie):
        annexes = [b.title for b in obwieszczenie if b.block_type == "annex"]
        assert len(annexes) == 2
        assert annexes[0].startswith("Załącznik do obwieszczenia Prezesa Rady Ministrów")

    def test_annex_articles_have_own_ids(self, obwieszczenie):
        ids = [b.id for b in obwieszczenie]
        assert len(ids) == len(set(ids))
        assert "annex-1/par_1" in ids and "annex-2/par_1" in ids

    def test_main_text_units(self, obwieszczenie):
        assert obwieszczenie[1].block_type == "item"
        assert (
            obwieszczenie[1]
            .versions[0]
            .paragraphs[0]
            .text.startswith("1. Na podstawie art. 16 ust. 3")
        )


class TestRenderedPdfMarkdown:
    def test_render_end_to_end(self):
        md = _render(1705, "2025-11-07")
        body = md.split("\n---\n", 1)[1]
        assert body.lstrip().startswith("# Ustawa z dnia 7 listopada 2025 r.")
        assert "\n## Treść ustawy\n" in body
        assert "\n###### Art. 1.\n" in body
        assert md.endswith("\n") and not md.endswith("\n\n")

    def test_frontmatter_points_to_pdf(self):
        md = _render(1701, "2025-12-02")
        assert 'pdf_url: "https://api.sejm.gov.pl/eli/acts/DU/2025/1701/text.pdf"' in md


class TestParsePdfDirect:
    def test_broken_pdf_gives_no_blocks(self):
        marker = b"<!--LEGALIZE norm_id=DU-2025-1 pub_date=2025-01-02-->\n"
        assert EliTextParser().parse_text(marker + b"%PDF-1.7\nnot a pdf") == []

    def test_parse_pdf_without_marker(self):
        pdf = (FIXTURES / "sample-pdf-only-2025-1701.pdf").read_bytes()
        blocks = parse_pdf(pdf, norm_id="DU-2025-1701", pub_date=date(2025, 12, 2))
        assert [b.title for b in blocks if b.block_type == "article"] == ["§ 1.", "§ 2."]

    def test_html_is_not_taken_for_pdf(self):
        html = b"<!--LEGALIZE norm_id=DU-2024-1 pub_date=2024-01-01-->\n<html><body></body></html>"
        assert EliTextParser().parse_text(html) == []

    def test_tree_without_title(self):
        tree = {
            "body": [
                {"type": "art", "num": "1", "path": "art_1", "text": "Tekst.", "children": []},
            ],
            "annexes": [],
        }
        blocks = tree_to_blocks(tree, "DU-2025-9", date(2025, 1, 2))
        assert [b.block_type for b in blocks] == ["article"]
        assert [p.text for p in blocks[0].versions[0].paragraphs] == ["Art. 1.", "Tekst."]


class TestClientPdfFallback:
    PDF = b"%PDF-1.7\n..."

    def _client(self) -> EliClient:
        return EliClient(requests_per_second=100.0)

    def test_pdf_only_act_fetches_pdf(self):
        meta = json.dumps(
            {"textHTML": False, "textPDF": True, "announcementDate": "2025-11-07"}
        ).encode()
        client = self._client()
        with patch.object(client, "_get", return_value=self.PDF) as get:
            data = client.get_text("DU-2025-1705", meta_data=meta)
        assert get.call_args_list[0].args[0].endswith("/acts/DU/2025/1705/text.pdf")
        assert get.call_count == 1  # no request for an HTML that does not exist
        assert data == b"<!--LEGALIZE norm_id=DU-2025-1705 pub_date=2025-11-07-->\n" + self.PDF

    def test_empty_html_falls_back_when_meta_lists_pdf(self):
        meta = json.dumps({"textPDF": True, "announcementDate": "2025-11-07"}).encode()
        client = self._client()
        with patch.object(client, "_get", side_effect=[b"", self.PDF]) as get:
            data = client.get_text("DU-2025-1705", meta_data=meta)
        urls = [c.args[0] for c in get.call_args_list]
        assert urls[0].endswith("/text.html") and urls[1].endswith("/text.pdf")
        assert data.endswith(self.PDF)

    def test_no_meta_looks_it_up(self):
        meta = json.dumps(
            {"textHTML": False, "textPDF": True, "announcementDate": "2025-11-07"}
        ).encode()
        client = self._client()
        with patch.object(client, "_get", side_effect=[b"", meta, self.PDF]):
            data = client.get_text("DU-2025-1705")
        assert data.startswith(b"<!--LEGALIZE norm_id=DU-2025-1705 pub_date=2025-11-07-->")

    def test_neither_html_nor_pdf_raises(self):
        meta = json.dumps({"textHTML": False, "textPDF": False}).encode()
        client = self._client()
        with patch.object(client, "_get", return_value=b""):
            with pytest.raises(ValueError):
                client.get_text("DU-2025-1", meta_data=meta)

    def test_html_act_unchanged(self):
        meta = json.dumps({"textHTML": True, "announcementDate": "2024-12-05"}).encode()
        client = self._client()
        with patch.object(client, "_get", return_value=b"<html></html>") as get:
            data = client.get_text("DU-2024-1976", meta_data=meta)
        assert get.call_count == 1
        assert data == b"<!--LEGALIZE norm_id=DU-2024-1976 pub_date=2024-12-05-->\n<html></html>"


class TestDiscoveryPdfFromYear:
    def _item(self, eli: str, html: bool, pdf: bool = True) -> dict:
        return {"ELI": eli, "textHTML": html, "textPDF": pdf}

    def test_pdf_only_acts_from_year(self):
        d = EliDiscovery(html_only=True, pdf_from_year=2012)
        assert d._wanted(self._item("DU/2025/1705", html=False), "DU")
        assert d._wanted(self._item("DU/2021/100", html=False), "DU")
        assert not d._wanted(self._item("DU/2005/1255", html=False), "DU")
        assert d._wanted(self._item("DU/2005/1256", html=True), "DU")

    def test_other_publishers_without_html_skipped(self):
        d = EliDiscovery(html_only=True, pdf_from_year=2012)
        assert not d._wanted(self._item("MP/2025/1", html=False), "DU")

    def test_no_pdf_from_year_keeps_html_only(self):
        d = EliDiscovery(html_only=True)
        assert not d._wanted(self._item("DU/2025/1705", html=False), "DU")

    def test_config_key(self):
        d = EliDiscovery.create({"year_start": 2000, "html_only": True, "pdf_from_year": 2012})
        assert d.pdf_from_year == 2012

    def test_discover_all_yields_pdf_only_acts(self):
        page = json.dumps(
            {
                "items": [
                    self._item("DU/2025/1", html=False),
                    self._item("DU/2025/2", html=False, pdf=False),
                ],
                "totalCount": 2,
                "count": 2,
            }
        ).encode()
        client = EliClient()
        d = EliDiscovery(year_start=2025, year_end=2025, html_only=True, pdf_from_year=2012)
        with patch.object(client, "search_year", return_value=page):
            assert list(d.discover_all(client)) == ["DU-2025-1"]
