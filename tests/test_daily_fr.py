"""Tests for the France daily incremental pipeline.

Covers:
- DILA directory listing regex parsing
- Increment file matching by date
- Tar extraction to legi_dir and increment_dir
- Git date inference from commit trailers
- LEGIDiscovery.discover_daily with filesystem fixtures
- Full daily() integration with mocked HTTP + filesystem
"""

from __future__ import annotations

import io
import json
import subprocess
import tarfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import responses

from legalize.fetcher.fr.daily import (
    DILA_LEGI_URL,
    _INCREMENT_RE,
    _extract_increment,
    _find_increment_for_date,
    _list_increments,
    _repo_scope,
    daily,
)
from legalize.fetcher.fr.discovery import LEGIDiscovery
from legalize.state.store import infer_last_date_from_git


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

DILA_DIRECTORY_HTML = """\
<html><body>
<h1>Index of /OPENDATA/LEGI/</h1>
<pre>
<a href="../">../</a>
<a href="Freemium_legi_global_20260325-180531.tar.gz">Freemium_legi_global_20260325-180531.tar.gz</a>  2026-03-25 18:06    3.1G
<a href="LEGI_20260327-180000.tar.gz">LEGI_20260327-180000.tar.gz</a>  2026-03-27 18:01    45M
<a href="LEGI_20260328-180000.tar.gz">LEGI_20260328-180000.tar.gz</a>  2026-03-28 18:01    12M
<a href="LEGI_20260329-180000.tar.gz">LEGI_20260329-180000.tar.gz</a>  2026-03-29 18:01    8M
<a href="LEGI_20260331-180000.tar.gz">LEGI_20260331-180000.tar.gz</a>  2026-03-31 18:01    15M
<a href="LEGI_20260401-180000.tar.gz">LEGI_20260401-180000.tar.gz</a>  2026-04-01 18:01    10M
</pre>
</body></html>
"""

STRUCT_XML_CODE = """\
<?xml version="1.0" encoding="UTF-8"?>
<TEXTELR>
<META>
<META_COMMUN>
<ID>LEGITEXT000006069414</ID>
<NATURE>CODE</NATURE>
</META_COMMUN>
</META>
<STRUCT/>
</TEXTELR>
"""

STRUCT_XML_CONSTITUTION = """\
<?xml version="1.0" encoding="UTF-8"?>
<TEXTELR>
<META>
<META_COMMUN>
<ID>LEGITEXT000006071194</ID>
<NATURE>CONSTITUTION</NATURE>
</META_COMMUN>
</META>
<STRUCT/>
</TEXTELR>
"""

STRUCT_XML_LOI = """\
<?xml version="1.0" encoding="UTF-8"?>
<TEXTELR>
<META>
<META_COMMUN>
<ID>LEGITEXT000044444444</ID>
<NATURE>LOI</NATURE>
</META_COMMUN>
</META>
<STRUCT/>
</TEXTELR>
"""

STRUCT_XML_MALFORMED = "<not valid xml"


def _make_struct_path(base: Path, norm_id: str) -> Path:
    """Create the directory structure for a LEGITEXT struct file."""
    struct_dir = base / "legi" / "global" / "code_et_TNC_en_vigueur" / "code_en_vigueur"
    struct_dir = struct_dir / "LEGI" / "TEXT" / "00" / "00" / norm_id
    struct_file = struct_dir / "texte" / "struct" / f"{norm_id}.xml"
    struct_file.parent.mkdir(parents=True, exist_ok=True)
    return struct_file


def _make_increment_tar(tmp_path: Path, date_str: str, norm_ids: dict[str, str]) -> Path:
    """Create a tar.gz that mimics a LEGI increment.

    Args:
        tmp_path: temporary directory
        date_str: e.g. "20260401"
        norm_ids: mapping of norm_id -> XML content
    Returns:
        Path to the created tar.gz
    """
    tar_path = tmp_path / f"LEGI_{date_str}-180000.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        for norm_id, xml_content in norm_ids.items():
            # DILA wraps the whole increment in a YYYYMMDD-HHMMSS/ directory.
            # The fixture used to omit it, which is why the tests never caught
            # that increments were landing outside the dump.
            rel_path = (
                f"{date_str}-180000/"
                f"legi/global/code_et_TNC_en_vigueur/code_en_vigueur/"
                f"LEGI/TEXT/00/00/{norm_id}/texte/struct/{norm_id}.xml"
            )
            data = xml_content.encode("utf-8")
            info = tarfile.TarInfo(name=rel_path)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return tar_path


# ─────────────────────────────────────────────
# Tests: _INCREMENT_RE
# ─────────────────────────────────────────────


class TestIncrementRegex:
    def test_matches_legi_files(self):
        matches = _INCREMENT_RE.findall(DILA_DIRECTORY_HTML)
        filenames = [m[0] for m in matches]
        assert "LEGI_20260327-180000.tar.gz" in filenames
        assert "LEGI_20260401-180000.tar.gz" in filenames

    def test_does_not_match_freemium(self):
        matches = _INCREMENT_RE.findall(DILA_DIRECTORY_HTML)
        filenames = [m[0] for m in matches]
        assert not any("Freemium" in f for f in filenames)

    def test_captures_timestamp(self):
        matches = _INCREMENT_RE.findall(DILA_DIRECTORY_HTML)
        timestamps = [m[1] for m in matches]
        assert "20260327-180000" in timestamps

    def test_count(self):
        matches = _INCREMENT_RE.findall(DILA_DIRECTORY_HTML)
        assert len(matches) == 5


# ─────────────────────────────────────────────
# Tests: _find_increment_for_date
# ─────────────────────────────────────────────


class TestFindIncrementForDate:
    INCREMENTS = [
        ("LEGI_20260327-180000.tar.gz", "https://example.com/LEGI_20260327-180000.tar.gz"),
        ("LEGI_20260328-180000.tar.gz", "https://example.com/LEGI_20260328-180000.tar.gz"),
        ("LEGI_20260401-180000.tar.gz", "https://example.com/LEGI_20260401-180000.tar.gz"),
    ]

    def test_finds_matching_date(self):
        result = _find_increment_for_date(self.INCREMENTS, date(2026, 3, 27))
        assert result is not None
        assert result[0] == "LEGI_20260327-180000.tar.gz"

    def test_returns_none_for_missing_date(self):
        result = _find_increment_for_date(self.INCREMENTS, date(2026, 3, 30))
        assert result is None

    def test_returns_none_for_empty_list(self):
        result = _find_increment_for_date([], date(2026, 3, 27))
        assert result is None


# ─────────────────────────────────────────────
# Tests: _list_increments
# ─────────────────────────────────────────────


class TestListIncrements:
    @responses.activate
    def test_parses_directory_listing(self):
        responses.add(responses.GET, DILA_LEGI_URL, body=DILA_DIRECTORY_HTML, status=200)
        import requests

        session = requests.Session()
        result = _list_increments(session)

        assert len(result) == 5
        assert all(isinstance(r, tuple) and len(r) == 2 for r in result)
        # Sorted by filename
        assert result[0][0] == "LEGI_20260327-180000.tar.gz"
        assert result[-1][0] == "LEGI_20260401-180000.tar.gz"
        # URLs are fully qualified
        assert result[0][1].startswith("https://")

    @responses.activate
    def test_raises_on_http_error(self):
        responses.add(responses.GET, DILA_LEGI_URL, status=500)
        import requests

        session = requests.Session()
        with pytest.raises(requests.HTTPError):
            _list_increments(session)


# ─────────────────────────────────────────────
# Tests: _extract_increment
# ─────────────────────────────────────────────


class TestExtractIncrement:
    def test_extracts_to_legi_dir_and_returns_ids(self, tmp_path):
        tar_path = _make_increment_tar(
            tmp_path, "20260401", {"LEGITEXT000006069414": STRUCT_XML_CODE}
        )
        legi_dir = tmp_path / "legi_dump"
        legi_dir.mkdir()

        ids = _extract_increment(tar_path, legi_dir)

        # Should extract to legi_dir
        struct = list(legi_dir.rglob("LEGITEXT000006069414.xml"))
        assert len(struct) == 1
        assert "CODE" in struct[0].read_text()

        # Should return discovered LEGITEXT IDs
        assert ids == {"LEGITEXT000006069414"}

    def test_merges_into_existing_legi_dir(self, tmp_path):
        legi_dir = tmp_path / "legi_dump"
        existing = legi_dir / "legi" / "global" / "existing.txt"
        existing.parent.mkdir(parents=True)
        existing.write_text("existing")

        tar_path = _make_increment_tar(
            tmp_path, "20260401", {"LEGITEXT000006069414": STRUCT_XML_CODE}
        )

        _extract_increment(tar_path, legi_dir)

        assert existing.read_text() == "existing"
        assert list(legi_dir.rglob("LEGITEXT000006069414.xml"))

    def test_returns_multiple_ids(self, tmp_path):
        tar_path = _make_increment_tar(
            tmp_path,
            "20260401",
            {
                "LEGITEXT000006069414": STRUCT_XML_CODE,
                "LEGITEXT000006071194": STRUCT_XML_CONSTITUTION,
            },
        )
        legi_dir = tmp_path / "legi_dump"
        legi_dir.mkdir()

        ids = _extract_increment(tar_path, legi_dir)
        assert ids == {"LEGITEXT000006069414", "LEGITEXT000006071194"}


# ─────────────────────────────────────────────
# Tests: infer_last_date_from_git
# ─────────────────────────────────────────────


class TestInferLastDateFromGit:
    def test_infers_from_source_date_trailer(self, tmp_path):
        # Create a git repo with a commit that has Source-Date trailer
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
        (repo / "test.md").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "test\n\nSource-Date: 2026-03-28"],
            cwd=repo,
            capture_output=True,
        )

        result = infer_last_date_from_git(str(repo))
        assert result == date(2026, 3, 28)

    def test_returns_none_without_source_date(self, tmp_path):
        """Commits without Source-Date trailers are ignored (e.g. README updates)."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
        (repo / "test.md").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "no trailer here"],
            cwd=repo,
            capture_output=True,
        )

        result = infer_last_date_from_git(str(repo))
        assert result is None

    def test_returns_none_for_empty_repo(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)

        result = infer_last_date_from_git(str(repo))
        assert result is None

    def test_returns_none_for_nonexistent_dir(self, tmp_path):
        result = infer_last_date_from_git(str(tmp_path / "nope"))
        assert result is None


# ─────────────────────────────────────────────
# Tests: LEGIDiscovery.discover_daily
# ─────────────────────────────────────────────


class TestDiscoverDaily:
    def test_discovers_code_in_increment(self, tmp_path):
        """Finds LEGITEXT with NATURE=CODE in an increment directory."""
        increment_dir = tmp_path / "20260401-180000"
        struct_file = _make_struct_path(increment_dir, "LEGITEXT000006069414")
        struct_file.write_text(STRUCT_XML_CODE)

        discovery = LEGIDiscovery(tmp_path)
        client = MagicMock()
        result = list(discovery.discover_daily(client, date(2026, 4, 1)))

        assert result == ["LEGITEXT000006069414"]

    def test_discovers_constitution(self, tmp_path):
        """Finds NATURE=CONSTITUTION too."""
        increment_dir = tmp_path / "20260401-180000"
        struct_file = _make_struct_path(increment_dir, "LEGITEXT000006071194")
        struct_file.write_text(STRUCT_XML_CONSTITUTION)

        discovery = LEGIDiscovery(tmp_path)
        client = MagicMock()
        result = list(discovery.discover_daily(client, date(2026, 4, 1)))

        assert result == ["LEGITEXT000006071194"]

    def test_filters_out_loi(self, tmp_path):
        """LOI is not in scope for the default natures (CODE, CONSTITUTION)."""
        increment_dir = tmp_path / "20260401-180000"
        struct_file = _make_struct_path(increment_dir, "LEGITEXT000044444444")
        struct_file.write_text(STRUCT_XML_LOI)

        discovery = LEGIDiscovery(tmp_path)
        client = MagicMock()
        result = list(discovery.discover_daily(client, date(2026, 4, 1)))

        assert result == []

    def test_deduplicates(self, tmp_path):
        """Same LEGITEXT in two increment dirs for same date yields once."""
        for ts in ("180000", "190000"):
            increment_dir = tmp_path / f"20260401-{ts}"
            struct_file = _make_struct_path(increment_dir, "LEGITEXT000006069414")
            struct_file.write_text(STRUCT_XML_CODE)

        discovery = LEGIDiscovery(tmp_path)
        client = MagicMock()
        result = list(discovery.discover_daily(client, date(2026, 4, 1)))

        assert result == ["LEGITEXT000006069414"]

    def test_no_increment_dir(self, tmp_path):
        """No increment dir for the target date yields nothing."""
        discovery = LEGIDiscovery(tmp_path)
        client = MagicMock()
        result = list(discovery.discover_daily(client, date(2026, 4, 1)))

        assert result == []

    def test_skips_malformed_xml(self, tmp_path):
        """Malformed XML is skipped without raising."""
        increment_dir = tmp_path / "20260401-180000"
        struct_file = _make_struct_path(increment_dir, "LEGITEXT000099999999")
        struct_file.write_text(STRUCT_XML_MALFORMED)

        # Also add a valid one
        struct_file2 = _make_struct_path(increment_dir, "LEGITEXT000006069414")
        struct_file2.write_text(STRUCT_XML_CODE)

        discovery = LEGIDiscovery(tmp_path)
        client = MagicMock()
        result = list(discovery.discover_daily(client, date(2026, 4, 1)))

        assert result == ["LEGITEXT000006069414"]

    def test_multiple_norms_discovered(self, tmp_path):
        """Multiple in-scope norms in one increment."""
        increment_dir = tmp_path / "20260401-180000"

        struct1 = _make_struct_path(increment_dir, "LEGITEXT000006069414")
        struct1.write_text(STRUCT_XML_CODE)

        # Need a separate path for the constitution
        const_dir = increment_dir / "legi" / "global" / "code_et_TNC_en_vigueur" / "TNC_en_vigueur"
        const_struct = (
            const_dir
            / "JORF"
            / "TEXT"
            / "LEGITEXT000006071194"
            / "texte"
            / "struct"
            / "LEGITEXT000006071194.xml"
        )
        const_struct.parent.mkdir(parents=True, exist_ok=True)
        const_struct.write_text(STRUCT_XML_CONSTITUTION)

        discovery = LEGIDiscovery(tmp_path)
        client = MagicMock()
        result = list(discovery.discover_daily(client, date(2026, 4, 1)))

        assert len(result) == 2
        assert set(result) == {"LEGITEXT000006069414", "LEGITEXT000006071194"}

    def test_ignores_other_dates(self, tmp_path):
        """Only scans directories matching the target date."""
        # Create increment for a different date
        increment_dir = tmp_path / "20260327-180000"
        struct_file = _make_struct_path(increment_dir, "LEGITEXT000006069414")
        struct_file.write_text(STRUCT_XML_CODE)

        discovery = LEGIDiscovery(tmp_path)
        client = MagicMock()
        result = list(discovery.discover_daily(client, date(2026, 4, 1)))

        assert result == []


# ─────────────────────────────────────────────
# Tests: daily() integration
# ─────────────────────────────────────────────


def _make_config(tmp_path: Path):
    """Build a Config with FR pointing to tmp dirs."""
    from legalize.config import Config, CountryConfig, GitConfig

    legi_dir = tmp_path / "legi"
    # The consolidated dump root: FR daily refuses to run without it.
    (legi_dir / "legi" / "global").mkdir(parents=True)
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    # The repo IS the scope. legalize-fr tracks one .md per code, named
    # after its LEGITEXT id; seed the one the fixtures modify.
    (repo_path / "fr").mkdir()
    (repo_path / "fr" / "LEGITEXT000006069414.md").write_text("seed\n")
    state_path = tmp_path / "state" / "state.json"

    # Init git repo
    subprocess.run(["git", "init"], cwd=repo_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo_path, capture_output=True)

    return Config(
        git=GitConfig(committer_name="Legalize", committer_email="test@test.com"),
        countries={
            "fr": CountryConfig(
                repo_path=str(repo_path),
                data_dir=str(tmp_path / "data"),
                state_path=str(state_path),
                source={"legi_dir": str(legi_dir)},
            )
        },
    )


class TestDailyIntegration:
    """Integration tests for the full daily() pipeline with mocked I/O."""

    def test_no_legi_dir_returns_zero(self, tmp_path):
        """Returns 0 if legi_dir is not configured."""
        from legalize.config import Config, CountryConfig, GitConfig

        config = Config(
            git=GitConfig(),
            countries={"fr": CountryConfig(source={"legi_dir": ""})},
        )
        result = daily(config, target_date=date(2026, 4, 1))
        assert result == 0

    @responses.activate
    def test_dry_run_does_not_create_commits(self, tmp_path):
        """Dry run lists increments but creates no commits."""
        config = _make_config(tmp_path)
        responses.add(responses.GET, DILA_LEGI_URL, body=DILA_DIRECTORY_HTML, status=200)

        result = daily(config, target_date=date(2026, 4, 1), dry_run=True)
        assert result == 0

        # State should be saved
        state_path = Path(config.get_country("fr").state_path)
        assert state_path.exists()
        state = json.loads(state_path.read_text())
        assert state["last_summary"] == "2026-04-01"

    @responses.activate
    def test_no_increment_for_date(self, tmp_path):
        """No increment available for the target date → 0 commits, state advances."""
        config = _make_config(tmp_path)
        # Directory listing with no matching date
        responses.add(
            responses.GET,
            DILA_LEGI_URL,
            body='<html><a href="LEGI_20260327-180000.tar.gz">LEGI_20260327-180000.tar.gz</a></html>',
            status=200,
        )

        result = daily(config, target_date=date(2026, 4, 1))
        assert result == 0

    @responses.activate
    def test_http_error_listing_returns_zero(self, tmp_path):
        """HTTP error listing increments → 0 commits."""
        config = _make_config(tmp_path)
        responses.add(responses.GET, DILA_LEGI_URL, body="Server Error", status=500)

        result = daily(config, target_date=date(2026, 4, 1))
        assert result == 0

    @responses.activate
    def test_full_pipeline_creates_commit(self, tmp_path):
        """Full happy path: download, extract, discover, process, commit."""
        config = _make_config(tmp_path)
        legi_dir = Path(config.get_country("fr").source["legi_dir"])
        repo_path = Path(config.get_country("fr").repo_path)

        # 1. Mock DILA directory listing
        responses.add(responses.GET, DILA_LEGI_URL, body=DILA_DIRECTORY_HTML, status=200)

        # 2. Create the tarball that will be "downloaded"
        tar_path = _make_increment_tar(
            tmp_path, "20260401", {"LEGITEXT000006069414": STRUCT_XML_CODE}
        )
        tar_content = tar_path.read_bytes()

        responses.add(
            responses.GET,
            f"{DILA_LEGI_URL}LEGI_20260401-180000.tar.gz",
            body=tar_content,
            status=200,
        )

        # 3. Pre-populate the legi dump with the full text data
        #    so LEGIClient can find the metadata and text
        #    We need struct + version files for the client to work
        text_dir = legi_dir / "legi" / "global" / "code_et_TNC_en_vigueur" / "code_en_vigueur"
        text_dir = text_dir / "LEGI" / "TEXT" / "00" / "00" / "LEGITEXT000006069414"

        # struct file
        struct_dir = text_dir / "texte" / "struct"
        struct_dir.mkdir(parents=True)
        (struct_dir / "LEGITEXT000006069414.xml").write_text(STRUCT_XML_CODE)

        # version file (metadata source) with proper title
        version_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<TEXTE_VERSION>
<META>
<META_COMMUN>
<ID>LEGITEXT000006069414</ID>
<NATURE>CODE</NATURE>
</META_COMMUN>
<META_SPEC>
<META_TEXTE_VERSION>
<TITRE>Code civil</TITRE>
<TITREFULL>Code civil</TITREFULL>
<ETAT>VIGUEUR</ETAT>
<DATE_DEBUT>1804-03-21</DATE_DEBUT>
<DATE_FIN>2999-01-01</DATE_FIN>
</META_TEXTE_VERSION>
<META_TEXTE_CHRONICLE>
<CID>LEGITEXT000006069414</CID>
<DATE_PUBLI>2999-01-01</DATE_PUBLI>
<DATE_TEXTE>2999-01-01</DATE_TEXTE>
<DERNIERE_MODIFICATION>2026-04-01</DERNIERE_MODIFICATION>
<TITRE_TEXTE>Code civil</TITRE_TEXTE>
</META_TEXTE_CHRONICLE>
</META_SPEC>
</META>
<VERSIONS>
<VERSION etat="VIGUEUR">
<LIEN_TXT debut="1804-03-21" fin="2999-01-01" id="LEGITEXT000006069414" num=""/>
</VERSION>
</VERSIONS>
</TEXTE_VERSION>
"""
        version_dir = text_dir / "texte" / "version"
        version_dir.mkdir(parents=True)
        (version_dir / "LEGITEXT000006069414.xml").write_text(version_xml)

        # Minimal combined XML will be built by LEGIClient from struct + articles
        # Since we have no articles, the combined XML will have empty elements
        # That's fine — render_norm_at_date will produce just frontmatter + no content

        result = daily(config, target_date=date(2026, 4, 1))

        # Should have created 1 commit
        assert result == 1

        # Verify the file was created in the repo
        md_files = list(repo_path.rglob("*.md"))
        assert len(md_files) == 1
        assert "LEGITEXT000006069414" in md_files[0].name

        # Verify git log has the commit
        log = subprocess.run(
            ["git", "log", "--oneline"], cwd=repo_path, capture_output=True, text=True
        )
        assert "Code civil" in log.stdout

        # Verify state was saved
        state_path = Path(config.get_country("fr").state_path)
        assert state_path.exists()
        state = json.loads(state_path.read_text())
        assert state["last_summary"] == "2026-04-01"
        assert state["runs"][-1]["commits_created"] == 1

    @responses.activate
    def test_no_changes_detected_skips_commit(self, tmp_path):
        """If the same date is processed twice, no duplicate commit."""
        config = _make_config(tmp_path)
        legi_dir = Path(config.get_country("fr").source["legi_dir"])

        responses.add(responses.GET, DILA_LEGI_URL, body=DILA_DIRECTORY_HTML, status=200)

        tar_path = _make_increment_tar(
            tmp_path, "20260401", {"LEGITEXT000006069414": STRUCT_XML_CODE}
        )
        tar_content = tar_path.read_bytes()
        responses.add(
            responses.GET,
            f"{DILA_LEGI_URL}LEGI_20260401-180000.tar.gz",
            body=tar_content,
            status=200,
        )

        # Pre-populate legi dump
        text_dir = legi_dir / "legi" / "global" / "code_et_TNC_en_vigueur" / "code_en_vigueur"
        text_dir = text_dir / "LEGI" / "TEXT" / "00" / "00" / "LEGITEXT000006069414"
        struct_dir = text_dir / "texte" / "struct"
        struct_dir.mkdir(parents=True)
        (struct_dir / "LEGITEXT000006069414.xml").write_text(STRUCT_XML_CODE)

        version_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<TEXTE_VERSION>
<META><META_COMMUN><ID>LEGITEXT000006069414</ID><NATURE>CODE</NATURE></META_COMMUN>
<META_SPEC><META_TEXTE_VERSION><TITRE>Code civil</TITRE><TITREFULL>Code civil</TITREFULL>
<ETAT>VIGUEUR</ETAT><DATE_DEBUT>1804-03-21</DATE_DEBUT></META_TEXTE_VERSION>
<META_TEXTE_CHRONICLE><CID>LEGITEXT000006069414</CID><DATE_PUBLI>2999-01-01</DATE_PUBLI>
<DATE_TEXTE>2999-01-01</DATE_TEXTE><DERNIERE_MODIFICATION>2026-04-01</DERNIERE_MODIFICATION>
<TITRE_TEXTE>Code civil</TITRE_TEXTE></META_TEXTE_CHRONICLE></META_SPEC></META>
<VERSIONS><VERSION etat="VIGUEUR">
<LIEN_TXT debut="1804-03-21" fin="2999-01-01" id="LEGITEXT000006069414" num=""/>
</VERSION></VERSIONS></TEXTE_VERSION>
"""
        version_dir = text_dir / "texte" / "version"
        version_dir.mkdir(parents=True)
        (version_dir / "LEGITEXT000006069414.xml").write_text(version_xml)

        # Run once to create the initial commit
        result1 = daily(config, target_date=date(2026, 4, 1))
        assert result1 == 1

        # Run again with the SAME date — same content → no commit
        responses.add(responses.GET, DILA_LEGI_URL, body=DILA_DIRECTORY_HTML, status=200)
        responses.add(
            responses.GET,
            f"{DILA_LEGI_URL}LEGI_20260401-180000.tar.gz",
            body=tar_content,
            status=200,
        )

        result2 = daily(config, target_date=date(2026, 4, 1))
        assert result2 == 0  # No new changes

    @responses.activate
    def test_safety_check_skips_short_markdown(self, tmp_path):
        """If new markdown is <50% the size of existing, skip (safety check)."""
        config = _make_config(tmp_path)
        repo_path = Path(config.get_country("fr").repo_path)

        # Pre-create a large existing file in the repo
        (repo_path / "fr").mkdir(parents=True, exist_ok=True)
        existing_file = repo_path / "fr" / "LEGITEXT000006069414.md"
        existing_file.write_text("x" * 10000)  # 10KB
        subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_path, capture_output=True)

        legi_dir = Path(config.get_country("fr").source["legi_dir"])
        responses.add(responses.GET, DILA_LEGI_URL, body=DILA_DIRECTORY_HTML, status=200)

        tar_path = _make_increment_tar(
            tmp_path, "20260401", {"LEGITEXT000006069414": STRUCT_XML_CODE}
        )
        responses.add(
            responses.GET,
            f"{DILA_LEGI_URL}LEGI_20260401-180000.tar.gz",
            body=tar_path.read_bytes(),
            status=200,
        )

        # Set up legi dump with minimal content (will produce very short markdown)
        text_dir = legi_dir / "legi" / "global" / "code_et_TNC_en_vigueur" / "code_en_vigueur"
        text_dir = text_dir / "LEGI" / "TEXT" / "00" / "00" / "LEGITEXT000006069414"
        struct_dir = text_dir / "texte" / "struct"
        struct_dir.mkdir(parents=True)
        (struct_dir / "LEGITEXT000006069414.xml").write_text(STRUCT_XML_CODE)

        version_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<TEXTE_VERSION><META><META_COMMUN><ID>LEGITEXT000006069414</ID><NATURE>CODE</NATURE></META_COMMUN>
<META_SPEC><META_TEXTE_VERSION><TITRE>Code civil</TITRE><TITREFULL>Code civil</TITREFULL>
<ETAT>VIGUEUR</ETAT><DATE_DEBUT>1804-03-21</DATE_DEBUT></META_TEXTE_VERSION>
<META_TEXTE_CHRONICLE><CID>LEGITEXT000006069414</CID><DATE_PUBLI>2999-01-01</DATE_PUBLI>
<DATE_TEXTE>2999-01-01</DATE_TEXTE><DERNIERE_MODIFICATION>2026-04-01</DERNIERE_MODIFICATION>
<TITRE_TEXTE>Code civil</TITRE_TEXTE></META_TEXTE_CHRONICLE></META_SPEC></META>
<VERSIONS><VERSION etat="VIGUEUR">
<LIEN_TXT debut="1804-03-21" fin="2999-01-01" id="LEGITEXT000006069414" num=""/>
</VERSION></VERSIONS></TEXTE_VERSION>
"""
        version_dir = text_dir / "texte" / "version"
        version_dir.mkdir(parents=True)
        (version_dir / "LEGITEXT000006069414.xml").write_text(version_xml)

        result = daily(config, target_date=date(2026, 4, 1))

        # The safety check should prevent the commit because
        # the new markdown (~200 bytes frontmatter) < 50% of 10000 bytes
        assert result == 0


# ─────────────────────────────────────────────
# Tests: the CI scenario — no LEGI dump on disk
#
# For four and a half months the FR daily ran green every day and produced
# nothing: the scope filter was built by scanning the dump, the CI runner has
# no dump, so the index came out empty and discarded 100% of the modified
# texts. These tests pin the two halves of that failure.
# ─────────────────────────────────────────────


VERSION_XML_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<TEXTE_VERSION><META><META_COMMUN><ID>{norm_id}</ID><NATURE>CODE</NATURE></META_COMMUN>
<META_SPEC><META_TEXTE_VERSION><TITRE>{title}</TITRE><TITREFULL>{title}</TITREFULL>
<ETAT>VIGUEUR</ETAT><DATE_DEBUT>1804-03-21</DATE_DEBUT></META_TEXTE_VERSION>
<META_TEXTE_CHRONICLE><CID>{norm_id}</CID><DATE_PUBLI>2999-01-01</DATE_PUBLI>
<DATE_TEXTE>2999-01-01</DATE_TEXTE><DERNIERE_MODIFICATION>2026-04-01</DERNIERE_MODIFICATION>
<TITRE_TEXTE>{title}</TITRE_TEXTE></META_TEXTE_CHRONICLE></META_SPEC></META>
<VERSIONS><VERSION etat="VIGUEUR">
<LIEN_TXT debut="1804-03-21" fin="2999-01-01" id="{norm_id}" num=""/>
</VERSION></VERSIONS></TEXTE_VERSION>
"""


def _seed_dump_text(legi_dir: Path, norm_id: str, title: str) -> Path:
    """Put a complete (struct + version) text in the consolidated dump."""
    struct_file = _make_struct_path(legi_dir, norm_id)
    struct_file.write_text(STRUCT_XML_CODE.replace("LEGITEXT000006069414", norm_id))
    version_file = struct_file.parent.parent / "version" / f"{norm_id}.xml"
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text(VERSION_XML_TEMPLATE.format(norm_id=norm_id, title=title))
    return struct_file


class TestRepoScope:
    def test_reads_legitext_files_only(self, tmp_path):
        (tmp_path / "fr").mkdir()
        (tmp_path / "fr" / "LEGITEXT000006069414.md").write_text("x")
        (tmp_path / "fr" / "LEGITEXT000006071194.md").write_text("x")
        (tmp_path / "README.md").write_text("x")

        assert _repo_scope(tmp_path) == {"LEGITEXT000006069414", "LEGITEXT000006071194"}

    def test_does_not_need_the_dump(self, tmp_path):
        """The whole point: scope resolution never touches legi_dir."""
        (tmp_path / "fr").mkdir()
        (tmp_path / "fr" / "LEGITEXT000006069414.md").write_text("x")

        assert _repo_scope(tmp_path) == {"LEGITEXT000006069414"}


class TestIncrementAppliesOverDump:
    def test_overwrites_the_dump_entry(self, tmp_path):
        """The increment must patch the dump, not land beside it.

        DILA ships increments inside a YYYYMMDD-HHMMSS/ root. Extracted as-is
        they ended up in {legi_dir}/20260401-180000/legi/global/..., which the
        client never reads, so every text re-rendered identical to the commit
        already in the repo and no reform was ever recorded.
        """
        legi_dir = tmp_path / "legi_dump"
        stale = _make_struct_path(legi_dir, "LEGITEXT000006069414")
        stale.write_text("<TEXTELR>stale</TEXTELR>")

        tar_path = _make_increment_tar(
            tmp_path, "20260401", {"LEGITEXT000006069414": STRUCT_XML_CODE}
        )
        ids = _extract_increment(tar_path, legi_dir)

        assert ids == {"LEGITEXT000006069414"}
        assert stale.read_text() == STRUCT_XML_CODE
        assert not (legi_dir / "20260401-180000").exists()
        assert list(legi_dir.rglob("LEGITEXT000006069414.xml")) == [stale]


class TestFailsLoudlyWithoutInputs:
    """A daily that cannot see its inputs must fail, not report 0 commits."""

    @responses.activate
    def test_missing_dump_raises(self, tmp_path):
        config = _make_config(tmp_path)
        legi_dir = Path(config.get_country("fr").source["legi_dir"])
        # Exactly the CI runner: repo checked out, no dump anywhere.
        (legi_dir / "legi" / "global").rmdir()
        responses.add(responses.GET, DILA_LEGI_URL, body=DILA_DIRECTORY_HTML, status=200)

        with pytest.raises(RuntimeError, match="LEGI dump not found"):
            daily(config, target_date=date(2026, 4, 1))

    @responses.activate
    def test_empty_repo_raises(self, tmp_path):
        config = _make_config(tmp_path)
        repo_path = Path(config.get_country("fr").repo_path)
        (repo_path / "fr" / "LEGITEXT000006069414.md").unlink()
        responses.add(responses.GET, DILA_LEGI_URL, body=DILA_DIRECTORY_HTML, status=200)

        with pytest.raises(RuntimeError, match="nothing in scope"):
            daily(config, target_date=date(2026, 4, 1))

    @responses.activate
    def test_dry_run_still_works_without_dump(self, tmp_path):
        """Dry run neither downloads nor renders, so it needs neither input."""
        config = _make_config(tmp_path)
        (Path(config.get_country("fr").source["legi_dir"]) / "legi" / "global").rmdir()
        responses.add(responses.GET, DILA_LEGI_URL, body=DILA_DIRECTORY_HTML, status=200)

        assert daily(config, target_date=date(2026, 4, 1), dry_run=True) == 0


class TestScopeComesFromRepo:
    @responses.activate
    def test_only_tracked_texts_are_committed(self, tmp_path):
        """The dump holds 114k texts; the repo tracks ~80 codes. Scope = repo.

        The increment modifies two codes, both present in the dump, only one
        tracked in the repo. The untracked one must not be committed — the old
        filter tested the dump index, so it would have added it.
        """
        config = _make_config(tmp_path)
        legi_dir = Path(config.get_country("fr").source["legi_dir"])
        repo_path = Path(config.get_country("fr").repo_path)

        tracked, untracked = "LEGITEXT000006069414", "LEGITEXT000006070721"
        _seed_dump_text(legi_dir, tracked, "Code civil")
        _seed_dump_text(legi_dir, untracked, "Code du travail")

        responses.add(responses.GET, DILA_LEGI_URL, body=DILA_DIRECTORY_HTML, status=200)
        tar_path = _make_increment_tar(
            tmp_path,
            "20260401",
            {tracked: STRUCT_XML_CODE, untracked: STRUCT_XML_CODE},
        )
        responses.add(
            responses.GET,
            f"{DILA_LEGI_URL}LEGI_20260401-180000.tar.gz",
            body=tar_path.read_bytes(),
            status=200,
        )

        result = daily(config, target_date=date(2026, 4, 1))

        assert result == 1
        assert {p.name for p in (repo_path / "fr").glob("*.md")} == {f"{tracked}.md"}

    @responses.activate
    def test_committed_even_when_the_dump_index_is_empty(self, tmp_path, monkeypatch):
        """Scope must not depend on the client's dump index.

        The index is forced empty here — what a CI runner produced every day
        ("Built text directory index: 0 entries"). With the old filter this run
        printed "No texts modified in scope" and committed nothing: the exact
        four-and-a-half-month silence.
        """
        monkeypatch.setattr("legalize.fetcher.fr.client._build_text_dir_index", lambda base: {})
        config = _make_config(tmp_path)
        legi_dir = Path(config.get_country("fr").source["legi_dir"])
        repo_path = Path(config.get_country("fr").repo_path)
        _seed_dump_text(legi_dir, "LEGITEXT000006069414", "Code civil")

        responses.add(responses.GET, DILA_LEGI_URL, body=DILA_DIRECTORY_HTML, status=200)
        tar_path = _make_increment_tar(
            tmp_path, "20260401", {"LEGITEXT000006069414": STRUCT_XML_CODE}
        )
        responses.add(
            responses.GET,
            f"{DILA_LEGI_URL}LEGI_20260401-180000.tar.gz",
            body=tar_path.read_bytes(),
            status=200,
        )

        result = daily(config, target_date=date(2026, 4, 1))

        assert result == 1
        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "Code civil" in log.stdout


# ─────────────────────────────────────────────
# Tests: safety cap (10-day lookback limit)
# ─────────────────────────────────────────────


class TestSafetyCap:
    def test_clamps_old_start_date(self, tmp_path):
        """resolve_dates_to_process clamps lookback to MAX_LOOKBACK_DAYS."""
        from datetime import timedelta

        from legalize.state.store import MAX_LOOKBACK_DAYS, StateStore, resolve_dates_to_process

        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        subprocess.run(["git", "init"], cwd=repo_path, capture_output=True)

        state_path = tmp_path / "state.json"
        state = StateStore(str(state_path))
        state.load()
        # Set last date to 60 days ago (well beyond the cap)
        state.last_summary_date = date.today() - timedelta(days=60)
        state.save()

        dates = resolve_dates_to_process(state, str(repo_path), target_date=None)
        assert dates is not None
        # Should have at most MAX_LOOKBACK_DAYS + 1 dates (today included)
        assert len(dates) <= MAX_LOOKBACK_DAYS + 1
        # Earliest date should be within the cap
        assert dates[0] >= date.today() - timedelta(days=MAX_LOOKBACK_DAYS)

    def test_explicit_date_bypasses_cap(self, tmp_path):
        """With --date, the cap does not apply."""
        from datetime import timedelta

        from legalize.state.store import StateStore, resolve_dates_to_process

        state_path = tmp_path / "state.json"
        state = StateStore(str(state_path))
        state.load()

        old_date = date.today() - timedelta(days=90)
        dates = resolve_dates_to_process(state, str(tmp_path), target_date=old_date)
        assert dates == [old_date]

    def test_skip_weekdays(self, tmp_path):
        """skip_weekdays filters out specified days."""
        from datetime import timedelta

        from legalize.state.store import StateStore, resolve_dates_to_process

        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        subprocess.run(["git", "init"], cwd=repo_path, capture_output=True)

        state_path = tmp_path / "state.json"
        state = StateStore(str(state_path))
        state.load()
        state.last_summary_date = date.today() - timedelta(days=8)
        state.save()

        dates = resolve_dates_to_process(
            state,
            str(repo_path),
            target_date=None,
            skip_weekdays={5, 6},
        )
        assert dates is not None
        for d in dates:
            assert d.weekday() not in (5, 6), f"{d} is a weekend day"
