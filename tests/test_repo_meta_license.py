"""Tests for the per-country LICENSE file generated into each country repo."""

from __future__ import annotations

from legalize.committer.license import PIPELINE_URL, render_license
from legalize.committer.repo_meta import repo_meta_files
from legalize.country_meta import COUNTRY_META


def test_repo_meta_includes_license_for_known_country():
    files = repo_meta_files("es")
    assert "LICENSE" in files
    assert "README.md" in files
    assert ".github/FUNDING.yml" in files


def test_unknown_country_gets_funding_only_no_license():
    files = repo_meta_files("zz")
    assert ".github/FUNDING.yml" in files
    assert "LICENSE" not in files
    assert "README.md" not in files


def test_license_embeds_mit_pipeline_disclaimer_and_country_data_license():
    meta = COUNTRY_META["es"]
    text = render_license(meta)
    # MIT pipeline pointer
    assert "MIT License" in text
    assert PIPELINE_URL in text
    # The country's own data-license statement, verbatim
    assert meta.data_license in text
    # Country name and the non-official-text disclaimer
    assert meta.name in text
    assert "not an official or" in text.lower()


def test_license_renders_for_every_country_with_meta():
    # Every country that gets a README must also get a valid, non-empty LICENSE
    # carrying its specific data-license string (they are heterogeneous).
    for code, meta in COUNTRY_META.items():
        text = render_license(meta)
        assert text.strip(), f"empty LICENSE for {code}"
        assert meta.data_license in text, f"data_license missing for {code}"
        assert PIPELINE_URL in text, f"pipeline URL missing for {code}"
