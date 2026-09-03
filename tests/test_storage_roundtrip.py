"""Every field of a norm has to survive the JSON, or it never reaches a commit.

``storage.py`` serialises field by field, so a field added to ``NormMetadata`` or
``Reform`` is dropped by default and only kept if someone remembers to edit two
functions. Three in a row were lost that way — ``text_state``, ``last_amendment``
and ``change_note`` — and each looked correct at the parser while producing nothing
in the output, because ``commit_all_fast`` renders from the JSON rather than from
the parser. Unit tests passed throughout: they tested the parser, and the parser was
right. The failure was between two layers that nothing crossed.

These two tests close that off. The first fails the moment a field is added, so the
decision to persist it or not is made deliberately; the second proves the ones we
say we persist actually come back.
"""

from __future__ import annotations

import dataclasses
from datetime import date

from legalize.models import (
    Block,
    NormMetadata,
    NormStatus,
    Paragraph,
    ParsedNorm,
    Rank,
    Reform,
    TextState,
    Version,
)
from legalize.storage import load_norma_from_json, save_structured_json

# Every field, and what we decided about it. Adding one to the model without adding
# it here fails test_no_field_is_unaccounted_for — which is the point.
METADATA_FIELDS = {
    "title": "persisted",
    "short_title": "persisted",
    "identifier": "persisted",
    "country": "persisted",
    "rank": "persisted",
    "publication_date": "persisted",
    "status": "persisted",
    "department": "persisted",
    "source": "persisted",
    "jurisdiction": "persisted",
    "last_modified": "persisted",
    "pdf_url": "persisted",
    "subjects": "persisted",
    "summary": "persisted",
    "extra": "persisted",
    "text_state": "persisted",
    "last_amendment": "persisted",
}

REFORM_FIELDS = {
    "date": "persisted",
    "norm_id": "persisted",
    # Reconstructed on load from the versions when absent, so it is not written
    # verbatim in every case, but it does come back.
    "affected_blocks": "persisted",
    "change_note": "persisted",
}


def _norm() -> ParsedNorm:
    """A norm with every field set to something distinguishable from its default."""
    metadata = NormMetadata(
        title="Decreto-Lei n.º 16/94 — Estatuto",
        short_title="Estatuto",
        identifier="DRE-DEC-LEI-16-1994",
        country="pt",
        rank=Rank("decreto-lei"),
        publication_date=date(1994, 1, 22),
        status=NormStatus.REPEALED,
        department="Ministério da Educação",
        source="https://diariodarepublica.pt/x",
        jurisdiction="pt-20",
        last_modified=date(1999, 3, 23),
        pdf_url="https://files.diariodarepublica.pt/x.pdf",
        subjects=("Ensino Superior", "Estatuto"),
        summary="Aprova o Estatuto",
        extra=(("surface", "pub"), ("official_number", "16/94")),
        text_state=TextState.AS_ENACTED,
        last_amendment="DRE-DEC-LEI-94-1999",
    )
    version = Version(
        norm_id="pub:decreto-lei:16-1994-512030",
        publication_date=date(1994, 1, 22),
        effective_date=date(1994, 1, 22),
        paragraphs=(Paragraph(css_class="parrafo", text="Texto."),),
    )
    block = Block(id="texto", block_type="texto", title="Artigo 1.º", versions=(version,))
    reform = Reform(
        date=date(1999, 3, 23),
        norm_id="DRE-DEC-LEI-94-1999",
        affected_blocks=("texto",),
        change_note="Alterada a redacção do artº 34º e aditado o art. 56º-A",
    )
    return ParsedNorm(metadata=metadata, blocks=(block,), reforms=(reform,))


class TestNoFieldIsUnaccountedFor:
    def test_metadata(self):
        assert {f.name for f in dataclasses.fields(NormMetadata)} == set(METADATA_FIELDS), (
            "A field was added to NormMetadata. Decide whether storage.py persists it, "
            "then record the decision in METADATA_FIELDS — three fields have already "
            "been lost by skipping this step."
        )

    def test_reform(self):
        assert {f.name for f in dataclasses.fields(Reform)} == set(REFORM_FIELDS), (
            "A field was added to Reform. Decide whether storage.py persists it, then "
            "record the decision in REFORM_FIELDS."
        )


class TestEveryPersistedFieldComesBack:
    def test_metadata_survives(self, tmp_path):
        original = _norm()
        back = load_norma_from_json(save_structured_json(tmp_path, original))
        lost = [
            name
            for name, decision in METADATA_FIELDS.items()
            if decision == "persisted"
            and getattr(back.metadata, name) != getattr(original.metadata, name)
        ]
        assert not lost, f"dropped by the JSON round-trip: {lost}"

    def test_reform_survives(self, tmp_path):
        original = _norm()
        back = load_norma_from_json(save_structured_json(tmp_path, original))
        lost = [
            name
            for name, decision in REFORM_FIELDS.items()
            if decision == "persisted"
            and getattr(back.reforms[0], name) != getattr(original.reforms[0], name)
        ]
        assert not lost, f"dropped by the JSON round-trip: {lost}"


class TestTheDateInForceSurvivesTheJson:
    """`effective_date` was written to the JSON as the publication date and read
    back as the publication date, so the parsed `fecha_vigencia` was destroyed
    between the parser and the commit — the exact shape this file exists for.

    It is on 100 % of the BOE's block-level `<version>` stamps and differs from
    publication on 96.4 % of them, in bytes the pipeline already downloads.
    """

    @staticmethod
    def _with_version(effective: date | None) -> ParsedNorm:
        norm = _norm()
        version = dataclasses.replace(norm.blocks[0].versions[0], effective_date=effective)
        block = dataclasses.replace(norm.blocks[0], versions=(version,))
        return dataclasses.replace(norm, blocks=(block,))

    def test_a_date_in_force_that_differs_comes_back(self, tmp_path):
        original = self._with_version(date(1994, 6, 30))
        back = load_norma_from_json(save_structured_json(tmp_path, original))
        assert back.blocks[0].versions[0].effective_date == date(1994, 6, 30)

    def test_not_being_told_comes_back_as_not_being_told(self, tmp_path):
        """Distinct from "took effect on publication", which is what the old
        round-trip turned it into."""
        original = self._with_version(None)
        back = load_norma_from_json(save_structured_json(tmp_path, original))
        assert back.blocks[0].versions[0].effective_date is None
        assert back.blocks[0].versions[0].in_force_from == date(1994, 1, 22)


class TestTheExpiryOfABlockSurvivesTheJson:
    """`commit_all_fast` renders from the JSON, not from the parser, so a block
    field that is not persisted is a field the corpus never sees."""

    def test_an_expiry_date_comes_back(self, tmp_path):
        norm = _norm()
        block = dataclasses.replace(norm.blocks[0], expiry_date=date(2012, 3, 6))
        original = dataclasses.replace(norm, blocks=(block,))
        back = load_norma_from_json(save_structured_json(tmp_path, original))
        assert back.blocks[0].expiry_date == date(2012, 3, 6)

    def test_a_block_with_no_expiry_comes_back_without_one(self, tmp_path):
        back = load_norma_from_json(save_structured_json(tmp_path, _norm()))
        assert back.blocks[0].expiry_date is None
