"""``legalize daily -c X`` must never silently run a different pipeline than X's.

The call to the country's own daily used to sit inside a try guarded by
``except (ImportError, AttributeError)``. Any AttributeError raised anywhere
inside the daily of es, fr, pt or ee — or a lazy ImportError from something they
import — was swallowed and ``generic_daily`` ran for that same country instead.
All four have complete REGISTRY entries, so it ran to completion and committed,
stamping a synthetic ``Source-Id: {CC}-DAILY-{date}`` and a fixed ``[reform]``
type on laws whose real flow had just crashed — with ``--push``. Two frozen
output fields, wrong, in a public repo, repairable only by reprocess.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from legalize.cli import cli

CONFIG = 'countries:\n  pt:\n    repo_path: "{repo}"\n    data_dir: "{data}"\n'


def _invoke(tmp_path, monkeypatch, boom):
    """Run `legalize daily -c pt` with pt's own daily raising ``boom``."""
    from legalize.fetcher.pt import daily as pt_daily

    config = tmp_path / "config.yaml"
    config.write_text(CONFIG.format(repo=tmp_path / "repo", data=tmp_path / "data"))

    def explode(*args, **kwargs):
        raise boom

    monkeypatch.setattr(pt_daily, "daily", explode)

    ran_generic = []
    monkeypatch.setattr(
        "legalize.pipeline.generic_daily",
        lambda *a, **k: ran_generic.append(a) or 0,
    )
    result = CliRunner().invoke(cli, ["--config", str(config), "daily", "-c", "pt"])
    return result, ran_generic


@pytest.mark.parametrize("boom", [AttributeError("no attribute 'foo'"), ImportError("late import")])
def test_a_crash_inside_a_country_daily_does_not_fall_back(tmp_path, monkeypatch, boom):
    result, ran_generic = _invoke(tmp_path, monkeypatch, boom)

    assert ran_generic == [], "generic_daily ran for a country that has its own daily"
    assert result.exit_code != 0
    assert isinstance(result.exception, type(boom))


def test_a_country_without_its_own_daily_still_falls_back(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text(
        'countries:\n  se:\n    repo_path: "{repo}"\n    data_dir: "{data}"\n'.format(
            repo=tmp_path / "repo", data=tmp_path / "data"
        )
    )
    ran_generic = []
    monkeypatch.setattr(
        "legalize.pipeline.generic_daily",
        lambda *a, **k: ran_generic.append(a) or 0,
    )

    result = CliRunner().invoke(cli, ["--config", str(config), "daily", "-c", "se"])

    assert result.exit_code == 0, result.output
    assert len(ran_generic) == 1
