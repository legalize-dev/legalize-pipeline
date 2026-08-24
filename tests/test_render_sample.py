"""Argument parsing for scripts/render_sample.py (the Step-7 render helper)."""

import gzip
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "render_sample", Path(__file__).parents[1] / "scripts" / "render_sample.py"
)
render_sample = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(render_sample)


def test_split_arg_derives_id_from_stem():
    assert render_sample.split_arg("tests/fixtures/xx/LAW-1.xml") == (
        "LAW-1",
        Path("tests/fixtures/xx/LAW-1.xml"),
    )
    assert render_sample.split_arg("a/LAW-2.xml.gz")[0] == "LAW-2"
    assert render_sample.split_arg("LAW-3=a/whatever.xml") == ("LAW-3", Path("a/whatever.xml"))


def test_read_fixture_handles_gzip(tmp_path):
    plain = tmp_path / "a.xml"
    plain.write_bytes(b"<law/>")
    packed = tmp_path / "b.xml.gz"
    packed.write_bytes(gzip.compress(b"<law/>"))
    assert render_sample.read_fixture(plain) == render_sample.read_fixture(packed) == b"<law/>"
