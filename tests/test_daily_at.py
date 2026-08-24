"""Tests for the Austria daily incremental pipeline.

Covers:
- RISDiscovery.discover_daily (API pagination, date filtering, dedup)
- daily() orchestration (dry run, no changes, error handling, state management)
"""

from __future__ import annotations

import json
import subprocess
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from legalize.fetcher.at.client import RISClient
from legalize.pipeline import generic_daily
from legalize.state.store import MAX_LOOKBACK_DAYS, infer_last_date_from_git
from legalize.fetcher.at.discovery import _RIS_WINDOWS, RISDiscovery, _ris_window


# ─────────────────────────────────────────────
# Fixtures: RIS API responses
# ─────────────────────────────────────────────


def _ris_response(hits: int, refs: list[dict], geaendert: str | None = None) -> bytes:
    """Build a fake RIS OGD API response."""
    docs = []
    for ref in refs:
        doc = {
            "Data": {
                "Metadaten": {
                    "Allgemein": {"Geaendert": geaendert or ""},
                    "Bundesrecht": {"BrKons": {"Gesetzesnummer": ref["gesnr"]}},
                    "Technisch": {"ID": ref.get("nor_id", "NOR12345678")},
                },
            }
        }
        docs.append(doc)

    ref_value = docs if len(docs) != 1 else docs[0]
    return json.dumps(
        {
            "OgdSearchResult": {
                "OgdDocumentResults": {
                    "Hits": {"#text": str(hits)},
                    "OgdDocumentReference": ref_value,
                }
            }
        }
    ).encode("utf-8")


def _ris_empty_response() -> bytes:
    """RIS response with no results."""
    return json.dumps(
        {
            "OgdSearchResult": {
                "OgdDocumentResults": {
                    "Hits": {"#text": "0"},
                    "OgdDocumentReference": [],
                }
            }
        }
    ).encode("utf-8")


# ─────────────────────────────────────────────
# Tests: RISDiscovery.discover_daily
# ─────────────────────────────────────────────


class TestRISDiscoverDaily:
    def _mock_client(self):
        """Create a MagicMock that passes isinstance(client, RISClient)."""
        return MagicMock(spec=RISClient)

    def test_discovers_modified_gesetzesnummern(self):
        mock_client = self._mock_client()
        mock_client.get_page.return_value = _ris_response(
            hits=2,
            refs=[{"gesnr": "10002333"}, {"gesnr": "10001848"}],
            geaendert="2026-04-01",
        )

        discovery = RISDiscovery()
        result = list(discovery.discover_daily(mock_client, date(2026, 4, 1)))

        assert set(result) == {"10002333", "10001848"}

    def test_filters_by_date(self):
        mock_client = self._mock_client()
        resp = json.dumps(
            {
                "OgdSearchResult": {
                    "OgdDocumentResults": {
                        "Hits": {"#text": "2"},
                        "OgdDocumentReference": [
                            {
                                "Data": {
                                    "Metadaten": {
                                        "Allgemein": {"Geaendert": "2026-04-01"},
                                        "Bundesrecht": {"BrKons": {"Gesetzesnummer": "10002333"}},
                                    }
                                }
                            },
                            {
                                "Data": {
                                    "Metadaten": {
                                        "Allgemein": {"Geaendert": "2026-03-30"},
                                        "Bundesrecht": {"BrKons": {"Gesetzesnummer": "99999999"}},
                                    }
                                }
                            },
                        ],
                    }
                }
            }
        ).encode("utf-8")
        mock_client.get_page.return_value = resp

        discovery = RISDiscovery()
        result = list(discovery.discover_daily(mock_client, date(2026, 4, 1)))

        assert result == ["10002333"]
        assert "99999999" not in result

    def test_deduplicates(self):
        mock_client = self._mock_client()
        mock_client.get_page.return_value = _ris_response(
            hits=3,
            refs=[
                {"gesnr": "10002333"},
                {"gesnr": "10002333"},
                {"gesnr": "10002333"},
            ],
            geaendert="2026-04-01",
        )

        discovery = RISDiscovery()
        result = list(discovery.discover_daily(mock_client, date(2026, 4, 1)))

        assert result == ["10002333"]

    def test_returns_empty_when_no_changes(self):
        mock_client = self._mock_client()
        mock_client.get_page.return_value = _ris_empty_response()

        discovery = RISDiscovery()
        result = list(discovery.discover_daily(mock_client, date(2026, 4, 1)))

        assert result == []

    def test_handles_single_ref_as_dict(self):
        mock_client = self._mock_client()
        mock_client.get_page.return_value = _ris_response(
            hits=1,
            refs=[{"gesnr": "10002333"}],
            geaendert="2026-04-01",
        )

        discovery = RISDiscovery()
        result = list(discovery.discover_daily(mock_client, date(2026, 4, 1)))

        assert result == ["10002333"]

    def test_paginates_through_multiple_pages(self):
        page1 = _ris_response(hits=150, refs=[{"gesnr": "10002333"}], geaendert="2026-04-01")
        page2 = _ris_response(hits=150, refs=[{"gesnr": "20003456"}], geaendert="2026-04-01")
        page3 = _ris_empty_response()

        mock_client = self._mock_client()
        mock_client.get_page.side_effect = [page1, page2, page3]

        discovery = RISDiscovery()
        result = list(discovery.discover_daily(mock_client, date(2026, 4, 1)))

        assert "10002333" in result
        assert "20003456" in result

    def test_uses_imrisseit_filter(self):
        mock_client = self._mock_client()
        mock_client.get_page.return_value = _ris_empty_response()

        discovery = RISDiscovery()
        list(discovery.discover_daily(mock_client, date.today()))

        _, kwargs = mock_client.get_page.call_args
        assert kwargs["ImRisSeit"] in dict(_RIS_WINDOWS).values()

    def test_window_covers_the_whole_lookback(self):
        """The window RIS is asked for must reach the oldest day the daily walks.

        `EinerWoche` is 7 days and the daily walks back MAX_LOOKBACK_DAYS, so
        its three oldest days used to ask for changes the query never returned
        — no error, just nothing.
        """
        spans = dict((name, span) for span, name in _RIS_WINDOWS)
        oldest = date.today() - timedelta(days=MAX_LOOKBACK_DAYS)

        assert spans[_ris_window(oldest)] > MAX_LOOKBACK_DAYS

    def test_an_older_explicit_date_widens_the_window(self):
        spans = dict((name, span) for span, name in _RIS_WINDOWS)
        recent = _ris_window(date.today() - timedelta(days=MAX_LOOKBACK_DAYS))
        old = _ris_window(date.today() - timedelta(days=100))

        assert spans[old] > spans[recent]

    def test_the_window_is_fetched_once_for_the_whole_run(self):
        """One pagination per run, not one per date — the 55-minute timeout."""
        mock_client = self._mock_client()
        mock_client.get_page.return_value = _ris_response(
            hits=1, refs=[{"gesnr": "10002333"}], geaendert=date.today().isoformat()
        )

        discovery = RISDiscovery()
        days = [date.today() - timedelta(days=n) for n in range(MAX_LOOKBACK_DAYS + 1)]
        found = [gesnr for day in days for gesnr in discovery.discover_daily(mock_client, day)]

        assert found == ["10002333"], "only the day that actually changed"
        assert mock_client.get_page.call_count == 1


# ─────────────────────────────────────────────
# Tests: infer_last_date_from_git (AT)
# ─────────────────────────────────────────────


class TestInferLastDateFromGitAT:
    def test_infers_from_source_date(self, tmp_path):
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

        assert infer_last_date_from_git(str(repo)) == date(2026, 3, 28)

    def test_returns_none_for_empty_repo(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)

        assert infer_last_date_from_git(str(repo)) is None


# ─────────────────────────────────────────────
# Tests: daily() orchestration
# ─────────────────────────────────────────────


class TestDailyATOrchestration:
    """Tests that generic_daily works correctly for Austria."""

    def _make_config(self, tmp_path: Path):
        from legalize.config import Config, CountryConfig, GitConfig

        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        subprocess.run(["git", "init"], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t.com"], cwd=repo_path, capture_output=True
        )

        return Config(
            git=GitConfig(committer_name="Legalize", committer_email="test@test.com"),
            countries={
                "at": CountryConfig(
                    repo_path=str(repo_path),
                    data_dir=str(tmp_path / "data"),
                    state_path=str(tmp_path / "state" / "state.json"),
                    source={},
                )
            },
        )

    def _mock_countries(self):
        """Build mocks for client and discovery dispatched by generic_daily."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        mock_client_cls = MagicMock()
        mock_client_cls.create.return_value = mock_client

        mock_discovery = MagicMock()
        mock_disc_cls = MagicMock()
        mock_disc_cls.create.return_value = mock_discovery

        return mock_client, mock_client_cls, mock_discovery, mock_disc_cls

    def test_dry_run_does_not_commit(self, tmp_path):
        config = self._make_config(tmp_path)
        mock_client, mock_client_cls, mock_discovery, mock_disc_cls = self._mock_countries()
        mock_discovery.discover_daily.return_value = iter(["10002333", "10001848"])

        with (
            patch("legalize.countries.get_client_class", return_value=mock_client_cls),
            patch("legalize.countries.get_discovery_class", return_value=mock_disc_cls),
        ):
            result = generic_daily(config, "at", target_date=date(2026, 4, 1), dry_run=True)

        assert result == 0

    def test_no_changes_returns_zero(self, tmp_path):
        config = self._make_config(tmp_path)
        mock_client, mock_client_cls, mock_discovery, mock_disc_cls = self._mock_countries()
        mock_discovery.discover_daily.return_value = iter([])

        with (
            patch("legalize.countries.get_client_class", return_value=mock_client_cls),
            patch("legalize.countries.get_discovery_class", return_value=mock_disc_cls),
        ):
            result = generic_daily(config, "at", target_date=date(2026, 4, 1))

        assert result == 0

    def test_discovery_error_continues(self, tmp_path):
        config = self._make_config(tmp_path)
        mock_client, mock_client_cls, mock_discovery, mock_disc_cls = self._mock_countries()
        mock_discovery.discover_daily.side_effect = RuntimeError("API down")

        with (
            patch("legalize.countries.get_client_class", return_value=mock_client_cls),
            patch("legalize.countries.get_discovery_class", return_value=mock_disc_cls),
        ):
            result = generic_daily(config, "at", target_date=date(2026, 4, 1))

        assert result == 0
        state_path = Path(config.get_country("at").state_path)
        assert state_path.exists()

    def test_checkpoint_pushes_after_each_day(self, tmp_path):
        """A multi-day daily run pushes after each completed day (checkpoint),
        not only once at the end — so a mid-run failure keeps finished days and
        the next run resumes from the last completed day instead of restarting.
        """
        from legalize.models import Block, NormMetadata, NormStatus, Paragraph, Rank, Version

        config = self._make_config(tmp_path)
        config.git.push = True  # checkpoint only pushes when pushing is enabled
        mock_client, mock_client_cls, mock_discovery, mock_disc_cls = self._mock_countries()
        # Two days, one modified norm each.
        mock_discovery.discover_daily.side_effect = [iter(["AT-1"]), iter(["AT-2"])]
        mock_client.get_metadata.return_value = b"<m/>"
        mock_client.get_text.return_value = b"<t/>"

        def _meta(_data, nid):
            return NormMetadata(
                title=nid,
                short_title=nid,
                identifier=nid,
                country="at",
                rank=Rank.LEY,
                publication_date=date(2026, 4, 1),
                status=NormStatus.IN_FORCE,
                department="T",
                source="https://example.com/",
            )

        meta_parser = MagicMock(spec=["parse"])
        meta_parser.parse.side_effect = _meta
        block = Block(
            id="a1",
            block_type="precepto",
            title="Art 1",
            versions=(
                Version(
                    norm_id="x",
                    publication_date=date(2026, 4, 1),
                    effective_date=date(2026, 4, 1),
                    paragraphs=(Paragraph(css_class="p", text="txt"),),
                ),
            ),
        )
        text_parser = MagicMock(spec=["parse_text"])
        text_parser.parse_text.return_value = [block]

        with (
            patch("legalize.countries.get_client_class", return_value=mock_client_cls),
            patch("legalize.countries.get_discovery_class", return_value=mock_disc_cls),
            patch("legalize.countries.get_metadata_parser", return_value=meta_parser),
            patch("legalize.countries.get_text_parser", return_value=text_parser),
            patch(
                "legalize.pipeline.resolve_dates_to_process",
                return_value=[date(2026, 4, 1), date(2026, 4, 2)],
            ),
            patch("legalize.pipeline.GitRepo.push") as mock_push,
        ):
            generic_daily(config, "at", target_date=None)

        # Each of the two days produced a commit → pushed per day (>= 2),
        # not the single end-of-run push the old code did.
        assert mock_push.call_count >= 2

    def test_state_saved_after_run(self, tmp_path):
        config = self._make_config(tmp_path)
        mock_client, mock_client_cls, mock_discovery, mock_disc_cls = self._mock_countries()
        mock_discovery.discover_daily.return_value = iter([])

        with (
            patch("legalize.countries.get_client_class", return_value=mock_client_cls),
            patch("legalize.countries.get_discovery_class", return_value=mock_disc_cls),
        ):
            generic_daily(config, "at", target_date=date(2026, 4, 1))

        state_path = Path(config.get_country("at").state_path)
        state = json.loads(state_path.read_text())
        assert state["last_summary"] == "2026-04-01"
        assert len(state["runs"]) == 1
        assert state["runs"][0]["commits_created"] == 0
