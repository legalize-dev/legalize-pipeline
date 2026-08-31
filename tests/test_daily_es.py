"""Spain daily processing — amendments come from the source, not from titles.

The fourth reform of the Constitution (art. 69.3, Formentera's own senator, BOE
2026-05-20) never reached the corpus: its title reads "Reforma del apartado 3 del
artículo 69", the daily classified anything without the word "modifica" as a new
law, asked the BOE for a consolidated text a Reforma does not have, got a 404 and
dropped it. Nothing here may depend on the wording of a title again.
"""

from __future__ import annotations

import subprocess
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from legalize.committer.git_ops import GitRepo
from legalize.fetcher.es.daily import _commit_reforms, _parse_updated_ids, _updated_norms
from legalize.models import NormMetadata, NormStatus, Rank

# ── /api/legislacion-consolidada?from=&to=, as the BOE answers it ──

UPDATED_XML = b"""\
<?xml version="1.0" encoding="utf-8"?>
<response>
  <status><code>200</code><text>ok</text></status>
  <data>
    <item>
      <fecha_actualizacion>20260520T074424Z</fecha_actualizacion>
      <identificador>BOE-A-1978-31229</identificador>
      <ambito codigo="1">Estatal</ambito>
      <rango codigo="1070">Constitucion</rango>
    </item>
    <item>
      <fecha_actualizacion>20260519T221003Z</fecha_actualizacion>
      <identificador>BOE-A-2015-11430</identificador>
      <ambito codigo="1">Estatal</ambito>
      <rango codigo="1300">Ley</rango>
    </item>
    <item>
      <fecha_actualizacion>20260519T120000Z</fecha_actualizacion>
      <identificador>DOUE-L-2016-12345</identificador>
      <ambito codigo="3">Union Europea</ambito>
    </item>
  </data>
</response>"""

UPDATED_XML_EMPTY = b"""\
<?xml version="1.0" encoding="utf-8"?>
<response>
  <status><code>200</code><text>ok</text></status>
  <data/>
</response>"""

# ── The consolidated text, with the version stamp the source puts on each block ──

TEXT_XML = b"""\
<?xml version="1.0" encoding="utf-8"?>
<response>
  <status><code>200</code><text>ok</text></status>
  <data>
    <texto>
      <bloque id="a13" tipo="precepto" titulo="Articulo 13">
        <version id_norma="BOE-A-1992-20403" fecha_publicacion="19920828"
                 fecha_vigencia="19920828">
          <p>2. Solamente los espanoles seran titulares de los derechos del art. 23.</p>
        </version>
      </bloque>
      <bloque id="a69" tipo="precepto" titulo="Articulo 69">
        <version id_norma="BOE-A-1978-31229" fecha_publicacion="19781229"
                 fecha_vigencia="19781229">
          <p>3. En las provincias insulares, cada isla o agrupacion de ellas.</p>
        </version>
        <version id_norma="BOE-A-2026-10881" fecha_publicacion="20260520"
                 fecha_vigencia="20260520">
          <p>3. En las provincias insulares, cada isla con Cabildo o Consejo Insular,
             correspondiendo uno a cada una de las siguientes islas: Ibiza, Formentera,
             Menorca.</p>
        </version>
      </bloque>
    </texto>
  </data>
</response>"""

CONSTITUTION = NormMetadata(
    title="Constitucion Espanola",
    short_title="Constitucion Espanola",
    identifier="BOE-A-1978-31229",
    country="es",
    rank=Rank.CONSTITUCION,
    publication_date=date(1978, 12, 29),
    status=NormStatus.IN_FORCE,
    department="Cortes Generales",
    source="https://www.boe.es/eli/es/c/1978/12/27/(1)",
)


class TestParseUpdatedIds:
    def test_returns_ids_newest_first(self):
        assert _parse_updated_ids(UPDATED_XML) == ["BOE-A-1978-31229", "BOE-A-2015-11430"]

    def test_filters_non_boe_ids(self):
        """Only BOE-A-* norms live in the corpus — EU and other refs are not ours."""
        assert "DOUE-L-2016-12345" not in _parse_updated_ids(UPDATED_XML)

    def test_empty_window(self):
        assert _parse_updated_ids(UPDATED_XML_EMPTY) == []


class TestUpdatedNorms:
    def test_returns_empty_on_http_error(self):
        client = MagicMock()
        client.get_updated.side_effect = requests.RequestException("timeout")

        assert _updated_norms(client, date(2026, 5, 19), date(2026, 5, 20)) == []

    def test_returns_empty_on_invalid_xml(self):
        client = MagicMock()
        client.get_updated.return_value = b"not xml at all"

        assert _updated_norms(client, date(2026, 5, 19), date(2026, 5, 20)) == []


@pytest.fixture
def repo_with_constitution(tmp_path: Path) -> tuple[GitRepo, Path]:
    """A repo holding the Constitution as the corpus had it before the 2026 reform."""
    root = tmp_path / "es"
    (root / "es").mkdir(parents=True)
    (root / "es" / "BOE-A-1978-31229.md").write_text("# Constitucion Espanola\n")

    for args in (
        ["init", "-b", "main"],
        ["config", "user.name", "Legalize"],
        ["config", "user.email", "legalize@legalize.dev"],
        ["add", "."],
        ["commit", "-m", "[bootstrap] Constitucion Espanola\n\nSource-Id: BOE-A-1978-31229\n"],
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

    return GitRepo(root, "Legalize", "legalize@legalize.dev"), root


def _client() -> MagicMock:
    client = MagicMock()
    client.get_updated.return_value = UPDATED_XML
    client.get_metadata.return_value = b"<metadata/>"
    client.get_disposition_xml.return_value = b"<documento/>"
    client.get_consolidated_text.return_value = TEXT_XML
    return client


class TestCommitReforms:
    """The case that was lost: a reform whose title never says "modifica"."""

    @pytest.fixture(autouse=True)
    def _stub_metadata(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "legalize.fetcher.es.metadata.parse_metadata",
            lambda *a, **kw: CONSTITUTION,
        )

    def test_commits_the_amendment_the_source_reports(self, repo_with_constitution):
        repo, root = repo_with_constitution
        errors: list[str] = []

        commits = _commit_reforms(_client(), repo, date(2026, 5, 19), date(2026, 5, 20), errors)

        assert commits == 1
        assert errors == []

        message = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%B%n%ad", "--date=short"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        # Who amended it, when and what it touched — all from the version stamps
        assert "Source-Id: BOE-A-2026-10881" in message
        assert "Source-Date: 2026-05-20" in message
        assert "Norm-Id: BOE-A-1978-31229" in message
        assert "Articulo 69" in message
        # dated at the amendment, not at the day the run happened to notice it
        assert message.splitlines()[-1] == "2026-05-20"
        assert "Formentera" in (root / "es" / "BOE-A-1978-31229.md").read_text()

    def test_second_run_is_a_no_op(self, repo_with_constitution):
        """The window overlaps by a day, so re-seeing a norm must commit nothing."""
        repo, root = repo_with_constitution
        errors: list[str] = []

        _commit_reforms(_client(), repo, date(2026, 5, 19), date(2026, 5, 20), errors)
        again = _commit_reforms(
            _client(),
            GitRepo(root, "Legalize", "legalize@legalize.dev"),
            date(2026, 5, 20),
            date(2026, 5, 21),
            errors,
        )

        assert again == 0
        assert errors == []

    def test_publishes_a_law_the_checkout_is_hiding(self, repo_with_constitution):
        """CI keeps only .github on disk. The law is in HEAD, so it still gets published.

        Reading the working tree instead of HEAD is what stopped every Spanish
        reform for the five days after the sparse checkout landed.
        """
        repo, root = repo_with_constitution
        (root / "es" / "BOE-A-1978-31229.md").unlink()

        assert _commit_reforms(_client(), repo, date(2026, 5, 19), date(2026, 5, 20), []) == 1

    def test_never_attributes_an_amendment_published_later(self, repo_with_constitution):
        """A backfilled day must not be labelled with a change it does not contain.

        The body is rendered as of the date being processed, so the commit takes the
        newest version stamp that date actually has — never the one from the future.
        """
        repo, root = repo_with_constitution

        _commit_reforms(_client(), repo, date(2026, 5, 18), date(2026, 5, 19), [])

        message = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%B"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert "BOE-A-2026-10881" not in message
        assert "Formentera" not in (root / "es" / "BOE-A-1978-31229.md").read_text()

    def test_skips_norms_the_corpus_does_not_hold(
        self, repo_with_constitution, monkeypatch: pytest.MonkeyPatch
    ):
        """The window also lists autonomic norms this repo never published."""
        repo, _ = repo_with_constitution
        monkeypatch.setattr(
            "legalize.fetcher.es.metadata.parse_metadata",
            lambda *a, **kw: replace(CONSTITUTION, identifier="BOE-A-2015-11430"),
        )

        assert _commit_reforms(_client(), repo, date(2026, 5, 19), date(2026, 5, 20), []) == 0
