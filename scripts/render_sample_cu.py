#!/usr/bin/env python3
"""Render the 5 Step-7 fixtures to /tmp/cu-sandbox/*.md.

Runs the full pipeline path for the Cuba country package: build the JSON
bundle exactly as ``GacetaClient.get_text`` would (base64 PDF + manifest
slicing knobs + publication date), parse it with ``GacetaTextParser``, parse
the manifest entry with ``GacetaMetadataParser``, and render to Markdown.

Usage:
    python scripts/render_sample_cu.py
"""

from __future__ import annotations

import base64
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, "src")

from legalize.countries import get_metadata_parser, get_text_parser
from legalize.transformer.markdown import render_norm_at_date

SAMPLES: list[tuple[str, str, dict]] = [
    (
        "Constitucion-2019",
        "sample-constitucion",
        {
            "title": "Constitución de la República de Cuba",
            "rank": "constitucion",
            "publication_date": "2019-04-10",
            "journal_issue": "No. 5 Extraordinaria de 2019",
        },
    ),
    (
        "Decreto-Ley-31-2021-Bienestar-Animal",
        "sample-bienestar-animal",
        {
            "title": "Decreto-Ley No. 31 de 2021, De Bienestar Animal",
            "rank": "decreto_ley",
            "publication_date": "2021-04-10",
            "journal_issue": "No. 25 Extraordinaria de 2021",
        },
    ),
    (
        "Ley-109-2010-Codigo-Seguridad-Vial",
        "sample-codigo-seguridad-vial",
        {
            "title": "Ley 109/2010, Código de Seguridad Vial",
            "rank": "codigo",
            "publication_date": "2010-09-17",
            "journal_issue": "No. 40 Ordinaria de 2010",
            "source": "https://www.minjus.gob.cu/sites/default/files/archivos/publicacion/2019-11/ley_109_codigo_seg_vial.pdf",
            "start_regex": "^LEY NÚMERO 109",
            "end_regex": "^CONSEJO DE MINISTROS$",
        },
    ),
    (
        "Ley-59-1987-Codigo-Civil",
        "sample-codigo-civil",
        {
            "title": "Ley No. 59 de 1987, Código Civil",
            "rank": "codigo",
            "publication_date": "1987-10-15",
            "journal_issue": "Extraordinaria de 15 de octubre de 1987",
            "notes": (
                "Consolidated edition actualizado 8 de noviembre de 2022; repealed "
                "articles omitted from the source: 52, 448-465, 542-544."
            ),
        },
    ),
    (
        "Ley-143-2021-Proceso-Penal",
        "sample-proceso-penal",
        {
            "title": "Ley No. 143 de 2021, Del Proceso Penal",
            "rank": "ley",
            "publication_date": "2021-12-07",
            "journal_issue": "No. 140 Ordinaria de 2021",
        },
    ),
]

BASE_SOURCE = "https://www.gacetaoficial.gob.cu/es/algunas-legislaciones-cubanas"

FIXTURES = Path("tests/fixtures/cu")
OUT = Path("/tmp/cu-sandbox")


def build_bundle(pdf_bytes: bytes, entry: dict) -> bytes:
    bundle = {
        "pdf": base64.b64encode(pdf_bytes).decode("ascii"),
        "goc": entry.get("goc", ""),
        "start_index": entry.get("start_index", 0),
        "start_regex": entry.get("start_regex", ""),
        "end_regex": entry.get("end_regex", ""),
        "publication_date": entry.get("publication_date", ""),
        "title": entry.get("title", ""),
        "journal_issue": entry.get("journal_issue", ""),
    }
    return json.dumps(bundle, ensure_ascii=False).encode("utf-8")


def main() -> None:
    mp, tp = get_metadata_parser("cu"), get_text_parser("cu")
    OUT.mkdir(exist_ok=True)
    for norm_id, fixture, meta_over in SAMPLES:
        pdf_bytes = (FIXTURES / f"{fixture}.pdf").read_bytes()
        entry = {
            "url": f"https://www.gacetaoficial.gob.cu/sites/default/files/{fixture}.pdf",
            "title": meta_over["title"],
            "rank": meta_over["rank"],
            "publication_date": meta_over["publication_date"],
            "journal_issue": meta_over.get("journal_issue", ""),
            "source": meta_over.get("source", BASE_SOURCE),
        }
        for key in ("goc", "start_index", "start_regex", "end_regex", "notes"):
            if meta_over.get(key):
                entry[key] = meta_over[key]
        meta_bytes = json.dumps(entry, ensure_ascii=False).encode("utf-8")
        bundle = build_bundle(pdf_bytes, entry)

        meta = mp.parse(meta_bytes, norm_id)
        blocks = tp.parse_text(bundle)
        if not blocks and norm_id != "Constitucion-2019":
            print(f"WARN: {norm_id} produced no blocks — expected text!")
        md = render_norm_at_date(meta, blocks, date.fromisoformat(meta.publication_date.isoformat()), include_all=True)
        (OUT / f"{norm_id}.md").write_text(md)
        print(f"{norm_id}: {len(md)} chars, {len(blocks)} blocks")


if __name__ == "__main__":
    main()
