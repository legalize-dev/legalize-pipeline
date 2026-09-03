"""Tests for the BOE XML parser."""

from datetime import date

from legalize.models import Block, Paragraph, Version
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


class TestTheDateAVersionTookEffect:
    """Point-in-time text is selected by when a version applied, not when its
    amendment was printed (#106).

    For Spain the two dates differ on 7,758 of 8,758 cached norms (88.6 %) —
    7,525 later, 233 retroactive — and by more than 30 days on 808 of them, so
    a law could report itself as in force on a date when none of it was.
    """

    @staticmethod
    def _block(*versions: Version) -> Block:
        return Block(id="a1", block_type="precepto", title="Artículo 1", versions=versions)

    @staticmethod
    def _version(norm_id: str, published: date, effective: date | None) -> Version:
        return Version(
            norm_id=norm_id,
            publication_date=published,
            effective_date=effective,
            paragraphs=(Paragraph(css_class="parrafo", text="x"),),
        )

    def test_an_amendment_does_not_apply_before_it_takes_effect(self):
        """Ley 12/2015: published 2015-06-25, in force 2015-10-01."""
        block = self._block(
            self._version("original", date(2015, 1, 1), None),
            self._version("amendment", date(2015, 6, 25), date(2015, 10, 1)),
        )
        assert get_block_at_date(block, date(2015, 8, 1)).norm_id == "original"
        assert get_block_at_date(block, date(2015, 10, 1)).norm_id == "amendment"

    def test_a_retroactive_amendment_applies_before_it_was_published(self):
        """233 of the cached ES norms declare a date in force that precedes
        their own publication. Reading them as published loses the fact."""
        block = self._block(
            self._version("original", date(2020, 1, 1), None),
            self._version("retroactive", date(2020, 6, 1), date(2020, 3, 1)),
        )
        assert get_block_at_date(block, date(2020, 4, 1)).norm_id == "retroactive"

    def test_a_source_that_declares_no_date_falls_back_to_publication(self):
        """se/sk/cz publish no date in force. Their corpora must render exactly
        as they did before this change."""
        block = self._block(
            self._version("original", date(2000, 1, 1), None),
            self._version("later", date(2010, 1, 1), None),
        )
        assert get_block_at_date(block, date(2005, 1, 1)).norm_id == "original"
        assert get_block_at_date(block, date(2015, 1, 1)).norm_id == "later"
        assert get_block_at_date(block, date(1999, 1, 1)) is None

    def test_the_newest_in_force_wins_even_when_published_out_of_order(self):
        """The BOE consolidates late: an amendment printed after another can
        have taken effect before it."""
        block = self._block(
            self._version("first", date(2021, 1, 1), date(2021, 1, 1)),
            self._version("printed_later_applies_earlier", date(2021, 9, 1), date(2021, 3, 1)),
            self._version("printed_earlier_applies_later", date(2021, 5, 1), date(2021, 7, 1)),
        )
        assert get_block_at_date(block, date(2021, 4, 1)).norm_id == "printed_later_applies_earlier"
        assert get_block_at_date(block, date(2021, 8, 1)).norm_id == "printed_earlier_applies_later"


class TestABlockTheSourceSaysIsGone:
    """`bloque@fecha_caducidad` marks the date a unit ceased to exist, and the
    pipeline read none of it (#106).

    The BOE materialises most repeals as one more version whose body is
    "(Derogado)", and those rendered correctly. Where it does not, the block
    keeps only its last live text and `get_block_at_date` published it as
    current law: 622 of 9,723 sampled blocks (6.4 %) across 10 of 53 documents,
    378 of them in `BOE-A-1984-12106` alone, and the Código Civil still prints
    1889 transitional provisions marked gone since 1981.
    """

    @staticmethod
    def _block(expiry: date | None, *versions: Version) -> Block:
        return Block(
            id="a244",
            block_type="precepto",
            title="Art. 244",
            versions=versions,
            expiry_date=expiry,
        )

    @staticmethod
    def _version(text: str, published: date) -> Version:
        return Version(
            norm_id="BOE-A-1984-12106",
            publication_date=published,
            effective_date=None,
            paragraphs=(Paragraph(css_class="parrafo", text=text),),
        )

    def test_an_unmaterialised_repeal_removes_the_block(self):
        block = self._block(
            date(2012, 3, 6), self._version("Para el régimen interior…", date(1984, 5, 30))
        )
        assert get_block_at_date(block, date(2012, 3, 5)) is not None
        assert get_block_at_date(block, date(2012, 3, 6)) is None
        assert get_block_at_date(block, date(2025, 1, 3)) is None

    def test_a_materialised_repeal_still_answers(self):
        """659 of the 1,281 expired blocks carry a "(Derogado)" version. Those
        render today and must keep rendering — the marker is the law."""
        block = self._block(
            date(2012, 3, 6),
            self._version("Para el régimen interior…", date(1984, 5, 30)),
            self._version("**(Derogado)**", date(2012, 3, 6)),
        )
        version = get_block_at_date(block, date(2025, 1, 3))
        assert version is not None
        assert version.paragraphs[0].text == "**(Derogado)**"

    def test_the_indefinite_validity_sentinel_is_not_an_expiry(self):
        """The BOE writes 99999999 for "no end date"; `_parse_date` already
        drops it, so the block never expires."""
        blocks = parse_text_xml(
            b'<?xml version="1.0" encoding="utf-8"?><response><data><texto>'
            b'<bloque id="a1" tipo="precepto" titulo="Art 1" fecha_caducidad="99999999">'
            b'<version id_norma="X" fecha_publicacion="19840530"><p class="parrafo">t</p></version>'
            b"</bloque></texto></data></response>"
        )
        assert blocks[0].expiry_date is None
        assert get_block_at_date(blocks[0], date(2025, 1, 1)) is not None

    def test_the_expiry_is_read_off_the_block(self):
        blocks = parse_text_xml(
            b'<?xml version="1.0" encoding="utf-8"?><response><data><texto>'
            b'<bloque id="a244" tipo="precepto" titulo="Art 244" fecha_caducidad="20120306">'
            b'<version id_norma="X" fecha_publicacion="19840530"><p class="parrafo">t</p></version>'
            b"</bloque></texto></data></response>"
        )
        assert blocks[0].expiry_date == date(2012, 3, 6)
