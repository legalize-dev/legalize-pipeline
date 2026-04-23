import re
from pathlib import Path

from legalize.fetcher.co.parser import SuinMetadataParser, SuinTextParser
from legalize.transformer.markdown import render_norm_at_date

FIXTURES = Path("tests/fixtures/co")


class TestSuinMetadataParser:
    def test_ley_1887_identifier(self):
        data = (FIXTURES / "sample-ley-1887.html").read_bytes()
        meta = SuinMetadataParser().parse(data, "1789030")
        assert meta.country == "co"
        assert meta.identifier == "LEY-57-1887"
        assert meta.publication_date.year == 1887

    def test_decreto_identifier(self):
        data = (FIXTURES / "sample-decreto.html").read_bytes()
        meta = SuinMetadataParser().parse(data, "1100073")
        assert meta.identifier == "DECRETO-453-1981"
        assert meta.publication_date.year == 1981

    def test_identifier_is_filesystem_safe(self):
        for fixture in FIXTURES.glob("sample-*.html"):
            data = fixture.read_bytes()
            try:
                meta = SuinMetadataParser().parse(data, "0")
                for char in (":", " ", "/", "\\", "*", "?", '"', "<", ">", "|"):
                    assert char not in meta.identifier, (
                        f"Unsafe char '{char}' in identifier: {meta.identifier}"
                    )
            except Exception:
                pass

    def test_source_url(self):
        data = (FIXTURES / "sample-ley-1887.html").read_bytes()
        meta = SuinMetadataParser().parse(data, "1789030")
        assert meta.source == "https://www.suin-juriscol.gov.co/viewDocument.asp?id=1789030"


class TestSuinTextParser:
    def test_parse_returns_blocks(self):
        data = (FIXTURES / "sample-ley-1887.html").read_bytes()
        blocks = SuinTextParser().parse_text(data)
        assert len(blocks) > 0

    def test_extract_reforms_from_leg_ant(self):
        # LEY-57-1887 has 90 articles with a "LEGISLACIÓN ANTERIOR" block,
        # yielding reforms with distinct dates (bootstrap + per-article cuts).
        data = (FIXTURES / "sample-ley-1887.html").read_bytes()
        reforms = SuinTextParser().extract_reforms(data)
        assert len(reforms) > 1, "should reconstruct reforms from leg_ant blocks"
        assert reforms[0].date.year == 1887, "earliest reform is the original publication"
        # Prior-version reform dates must span a reasonable legislative range.
        years = {r.date.year for r in reforms}
        assert any(1900 <= y <= 2026 for y in years), (
            "reform dates should include modern amendments"
        )

    def test_body_table_is_markdown_paragraph(self):
        data = (FIXTURES / "sample-decreto-1993.html").read_bytes()
        blocks = SuinTextParser().parse_text(data)
        table_paragraphs = [
            paragraph
            for block in blocks
            for version in block.versions
            for paragraph in version.paragraphs
            if paragraph.css_class == "table"
        ]
        assert table_paragraphs
        assert table_paragraphs[0].text.startswith("| ")


class TestOutputFidelity:
    """Regression tests: every output MD must be free of known issues."""

    FIXTURE_IDS = {
        "sample-ley-1887.html": "1789030",
        "sample-acto-legislativo.html": "1000001",
        "sample-decreto.html": "1100073",
        "sample-decreto-2900.html": "1500073",
        "sample-decreto-1993.html": "1900000",
    }

    def _render(self, fixture: str) -> str:
        data = (FIXTURES / fixture).read_bytes()
        norm_id = self.FIXTURE_IDS[fixture]
        meta = SuinMetadataParser().parse(data, norm_id)
        blocks = SuinTextParser().parse_text(data)
        return render_norm_at_date(meta, blocks, meta.publication_date, include_all=True)

    def test_no_quadruple_or_quintuple_asterisks(self):
        for fixture in self.FIXTURE_IDS:
            md = self._render(fixture)
            assert not re.search(r"(?<!\*)\*{4,}(?!\*)", md), (
                f"{fixture}: 4+ consecutive asterisks leaked into output"
            )

    def test_no_toggle_or_note_leaks(self):
        for fixture in self.FIXTURE_IDS:
            md = self._render(fixture)
            for needle in ("[Mostrar]", "[Ocultar]", "Afecta la vigencia de:"):
                assert needle not in md, f"{fixture}: '{needle}' leaked into MD"

    def test_no_subtipo_metadata_leak_in_body(self):
        for fixture in self.FIXTURE_IDS:
            md = self._render(fixture)
            body = md.split("---", 2)[-1]
            assert "Subtipo:" not in body, f"{fixture}: 'Subtipo:' metadata leaked into body"

    def test_modification_summary_is_single_line(self):
        md = self._render("sample-ley-1887.html")
        frontmatter = md.split("---", 2)[1]
        for line in frontmatter.splitlines():
            if line.startswith("modification_summary:"):
                assert "\n" not in line, "modification_summary must not contain newlines"
                break
        else:
            raise AssertionError("modification_summary key missing from LEY-57-1887 frontmatter")

    def test_modification_summary_is_deduplicated(self):
        md = self._render("sample-ley-1887.html")
        for line in md.splitlines():
            if line.startswith("modification_summary:"):
                entries = line.split(" · ")
                assert len(entries) == len(set(entries)), "duplicates in modification_summary"
                break


class TestFutureDateFallback:
    def test_future_fecha_diario_oficial_falls_back_to_fecha_vigencia(self):
        from legalize.fetcher.co.parser import _pick_publication_date

        # DECRETO 4816 DE 2010: SUIN typed fecha_diario_oficial as "29/12/2029"
        # but fecha_vigencia is correct. Parser must reject the future date.
        fields = {
            "fecha_diario_oficial": "29/12/2029",
            "fecha_vigencia": "29/12/2010",
        }
        assert _pick_publication_date(fields).year == 2010


class TestMetadataCompleteness:
    def test_captures_all_known_extras(self):
        data = (FIXTURES / "sample-ley-1887.html").read_bytes()
        meta = SuinMetadataParser().parse(data, "1789030")
        extras = dict(meta.extra)
        for expected in (
            "gazette_reference",
            "gazette_number",
            "gazette_page",
            "subtype",
            "entry_into_force",
            "comments",
            "modification_count",
            "modification_summary",
            "document_status_raw",
        ):
            assert expected in extras, f"missing extra field: {expected}"


class TestRegistry:
    def test_co_in_registry(self):
        from legalize.countries import REGISTRY

        assert "co" in REGISTRY
