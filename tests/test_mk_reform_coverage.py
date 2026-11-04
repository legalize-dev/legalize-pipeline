import json
import subprocess

from scripts.check_mk_reform_coverage import missing_reforms


def test_reform_coverage_ignores_unpublished_targets(tmp_path):
    data = tmp_path / "data" / "json"
    data.mkdir(parents=True)
    (data / "RM-2000-1-2.json").write_text(
        json.dumps(
            {
                "metadata": {"identifier": "RM-2000-1-2"},
                "reforms": [{"source_id": "RM-2001-2-3"}],
            }
        ),
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    assert missing_reforms(tmp_path / "data", repo) == []


def test_reform_coverage_requires_source_and_target_pair(tmp_path):
    data = tmp_path / "data" / "json"
    data.mkdir(parents=True)
    (data / "RM-2000-1-2.json").write_text(
        json.dumps(
            {
                "metadata": {"identifier": "RM-2000-1-2"},
                "reforms": [{"source_id": "RM-2001-2-3"}],
            }
        ),
        encoding="utf-8",
    )
    (data / "RM-2001-2-3.json").write_text(
        json.dumps({"metadata": {"identifier": "RM-2001-2-3"}, "reforms": []}),
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    assert missing_reforms(tmp_path / "data", repo) == [("RM-2001-2-3", "RM-2000-1-2")]
