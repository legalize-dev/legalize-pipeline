"""Spec v0.5 §Coverage: what a repo holds and what it left out, measured."""

import json

import requests

from legalize.coverage import (
    clear_failure,
    coverage_report,
    is_transient,
    record_failure,
    render,
    unresolved,
)
from legalize.layout import manifest, spec_version_for


def law(identifier, extra=""):
    return f'---\ntitle: "T"\nidentifier: "{identifier}"\ncountry: "ie"\n{extra}---\ntext\n'


def test_report_counts_files_gaps_and_every_unpublished_norm(tmp_path):
    repo, data = tmp_path / "repo", tmp_path / "data"
    (repo / "ie").mkdir(parents=True)
    (repo / ".github").mkdir()
    (repo / "README.md").write_text("not a law")
    gap = json.dumps([{"date": "2020-01-01", "reason": "scanned", "sha256": "ab"}] * 2)
    (repo / "ie/A.md").write_text(law("A", f"source_version_gaps: {json.dumps(gap)}\n"))
    (repo / "ie/B.md").write_text(law("B"))
    data.mkdir()
    (data / "discovery_ids.txt").write_text("A\nB\nC\nD\n")
    record_failure(data, "C", ValueError("Malformed footnote"))
    record_failure(data, "D", requests.ConnectionError("DNS"))
    record_failure(data, "SI-cited", ValueError("Unreadable table"))

    report = coverage_report(repo, data, "test index")
    assert (report["discovered"], report["published"]) == (4, 2)
    assert (report["version_gaps"], report["laws_with_version_gaps"]) == (2, 1)
    excluded = {entry["identifier"]: entry for entry in report["excluded"]}
    assert set(excluded) == {"C", "D", "SI-cited"}
    assert "Malformed footnote" in excluded["C"]["reason"]
    assert excluded["D"]["transient"] is True and "transient" not in excluded["C"]
    assert unresolved(data, ["C", "D", "never-recorded"]) == ["D", "never-recorded"]

    clear_failure(data, "C")
    assert "C" in {e["identifier"] for e in coverage_report(repo, data, "x")["excluded"]}
    assert coverage_report(repo, data, "x")["excluded"][0]["reason"] == "not fetched"


def test_as_of_only_moves_when_something_else_changes():
    report = {"as_of": "2026-10-20", "published": 2, "excluded": []}
    previous = render({**report, "as_of": "2026-10-01"})
    assert json.loads(render(report, previous))["as_of"] == "2026-10-01"
    assert json.loads(render({**report, "published": 3}, previous))["as_of"] == "2026-10-20"


def test_transient_is_network_trouble_not_an_absent_source():
    missing = requests.HTTPError(response=type("R", (), {"status_code": 404})())
    busy = requests.HTTPError(response=type("R", (), {"status_code": 503})())
    assert not is_transient(missing) and is_transient(busy)
    assert is_transient(requests.Timeout()) and not is_transient(ValueError("bad table"))


def test_only_a_country_with_coverage_declares_v05():
    assert spec_version_for("ie") == "0.5" and 'spec_version: "0.5"' in manifest("ie")
    assert spec_version_for("es") == "0.4" and 'spec_version: "0.4"' in manifest("es")


def test_health_names_every_exclusion_a_full_run_cannot_ship(tmp_path):
    import subprocess

    from click.testing import CliRunner

    from legalize.cli import cli

    repo, data = tmp_path / "repo", tmp_path / "data"
    (repo / "ie").mkdir(parents=True)
    (repo / "ie/A.md").write_text(law("A"))
    data.mkdir()
    (data / "discovery_ids.txt").write_text("A\nB\nC\nD\n")
    record_failure(data, "B", requests.ConnectionError("DNS"))
    record_failure(data, "C", ValueError("Malformed footnote"))
    (repo / "coverage.json").write_text(render(coverage_report(repo, data, "index")))
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    config = tmp_path / "config.yaml"
    config.write_text(f'countries:\n  ie:\n    repo_path: "{repo}"\n    data_dir: "{data}"\n')

    output = CliRunner().invoke(cli, ["--config", str(config), "health", "-c", "ie"]).output
    assert "1 published of 4 discovered, 3 excluded" in output, output
    assert "1 exclusion(s) are network failures" in output
    assert "1 exclusion(s) have no recorded reason" in output  # D
    assert "neither published nor excluded" not in output
