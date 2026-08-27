"""Tests for the BOE XML parser."""

from datetime import date

from legalize.transformer.xml_parser import (
    extract_reforms,
    get_block_at_date,
    parse_text_xml,
)


class TestParseTextoXml:
    def test_parse_returns_blocks(self, constitucion_xml: bytes):
        blocks = parse_text_xml(constitucion_xml)
        assert len(blocks) > 0

    def test_block_has_required_fields(self, constitucion_xml: bytes):
        blocks = parse_text_xml(constitucion_xml)
        for block in blocks:
            assert isinstance(block.id, str)
            assert isinstance(block.block_type, str)
            assert isinstance(block.title, str)
            assert isinstance(block.versions, tuple)

    def test_version_has_date_objects(self, constitucion_xml: bytes):
        blocks = parse_text_xml(constitucion_xml)
        for block in blocks:
            for version in block.versions:
                assert isinstance(version.publication_date, date)
                assert isinstance(version.effective_date, date)

    def test_paragraphs_are_tuples(self, constitucion_xml: bytes):
        blocks = parse_text_xml(constitucion_xml)
        for block in blocks:
            for version in block.versions:
                assert isinstance(version.paragraphs, tuple)

    def test_notas_pie_retained(self, constitucion_xml: bytes):
        """Footnotes (reform provenance) are retained as `nota_pie` paragraphs.

        Refactor 2026-04-22: we no longer drop them; the note body is the
        legislative audit trail for each block and the markdown renderer
        emits it as a quoted small-text line. See research/RESEARCH-ES-v2.md §1.1.
        """
        blocks = parse_text_xml(constitucion_xml)
        note_classes: set[str] = set()
        for block in blocks:
            for version in block.versions:
                for p in version.paragraphs:
                    if p.css_class.startswith("nota_pie"):
                        note_classes.add(p.css_class)
        assert note_classes.issubset({"nota_pie", "nota_pie_2"})

    def test_constitucion_has_17_blocks(self, constitucion_xml: bytes):
        """The sample Constitution has 17 blocks."""
        blocks = parse_text_xml(constitucion_xml)
        assert len(blocks) == 17


class TestExtractReforms:
    def test_constitucion_has_4_reforms(self, constitucion_xml: bytes):
        blocks = parse_text_xml(constitucion_xml)
        reforms = extract_reforms(blocks)
        assert len(reforms) == 4

    def test_reforms_are_chronological(self, constitucion_xml: bytes):
        blocks = parse_text_xml(constitucion_xml)
        reforms = extract_reforms(blocks)
        dates = [r.date for r in reforms]
        assert dates == sorted(dates)

    def test_first_reform_is_original(self, constitucion_xml: bytes):
        blocks = parse_text_xml(constitucion_xml)
        reforms = extract_reforms(blocks)
        assert reforms[0].norm_id == "BOE-A-1978-31229"
        assert reforms[0].date == date(1978, 12, 29)

    def test_last_reform_is_2024(self, constitucion_xml: bytes):
        blocks = parse_text_xml(constitucion_xml)
        reforms = extract_reforms(blocks)
        assert reforms[-1].norm_id == "BOE-A-2024-3099"
        assert reforms[-1].date == date(2024, 2, 17)

    def test_reform_dates(self, constitucion_xml: bytes):
        blocks = parse_text_xml(constitucion_xml)
        reforms = extract_reforms(blocks)
        expected_dates = [
            date(1978, 12, 29),
            date(1992, 8, 28),
            date(2011, 9, 27),
            date(2024, 2, 17),
        ]
        assert [r.date for r in reforms] == expected_dates

    def test_reform_affected_blocks(self, constitucion_xml: bytes):
        blocks = parse_text_xml(constitucion_xml)
        reforms = extract_reforms(blocks)

        # The original publication affects all blocks
        assert len(reforms[0].affected_blocks) == 17

        # Subsequent reforms affect a single block each
        for reform in reforms[1:]:
            assert len(reform.affected_blocks) == 1


class TestGetBlockAtDate:
    def test_original_version(self, constitucion_xml: bytes):
        blocks = parse_text_xml(constitucion_xml)
        art13 = next(b for b in blocks if b.id == "a13")

        version = get_block_at_date(art13, date(1990, 1, 1))
        assert version is not None
        assert version.norm_id == "BOE-A-1978-31229"

    def test_reformed_version(self, constitucion_xml: bytes):
        blocks = parse_text_xml(constitucion_xml)
        art13 = next(b for b in blocks if b.id == "a13")

        version = get_block_at_date(art13, date(2000, 1, 1))
        assert version is not None
        assert version.norm_id == "BOE-A-1992-20403"

    def test_before_publication_returns_none(self, constitucion_xml: bytes):
        blocks = parse_text_xml(constitucion_xml)
        art13 = next(b for b in blocks if b.id == "a13")

        version = get_block_at_date(art13, date(1970, 1, 1))
        assert version is None
