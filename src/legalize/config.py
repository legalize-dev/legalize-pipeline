"""Legalize pipeline configuration.

Loaded from config.yaml with optional CLI argument overrides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class GitConfig:
    """Git configuration (committer identity, branch, push)."""

    committer_name: str = "Legalize"
    committer_email: str = "legalize@legalize.dev"
    branch: str = "main"
    push: bool = False


@dataclass
class CountryConfig:
    """Configuration for a single country pipeline."""

    repo_path: str = ""
    data_dir: str = ""
    cache_dir: str = ".cache"
    max_workers: int = 1
    state_path: str = ""  # default: .pipeline/{code}/state.json
    # Days without a newly captured norm before the daily reports the
    # country as stalled. Tune per country from its observed cadence:
    # a source that legitimately goes quiet for weeks needs a longer
    # window, or the alert trains everyone to ignore it.
    stall_alert_days: int = 14
    source: dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    """Global pipeline configuration."""

    git: GitConfig = field(default_factory=GitConfig)
    countries: dict[str, CountryConfig] = field(default_factory=dict)

    def get_country(self, code: str) -> CountryConfig:
        """Get config for a country from the countries: section."""
        if code not in self.countries:
            raise ValueError(
                f"Country '{code}' not configured. "
                f"Add it to the 'countries' section of config.yaml."
            )
        cc = self.countries[code]
        if not cc.state_path:
            cc.state_path = f".pipeline/{code}/state.json"
        return cc


def load_config(path: str | Path = "config.yaml", overrides: dict | None = None) -> Config:
    """Load configuration from YAML, with optional CLI overrides."""
    config_path = Path(path)

    raw: dict = {}
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    # Merge overrides
    if overrides:
        for key, value in overrides.items():
            if value is not None:
                _set_nested(raw, key, value)

    git_raw = raw.get("git", {})

    # Parse per-country configs
    countries_raw = raw.get("countries", {})
    countries = {}
    for code, country_raw in countries_raw.items():
        countries[code] = CountryConfig(
            repo_path=country_raw.get("repo_path", ""),
            data_dir=country_raw.get("data_dir", ""),
            cache_dir=country_raw.get("cache_dir", ".cache"),
            max_workers=country_raw.get("max_workers", 1),
            state_path=country_raw.get("state_path", ""),
            stall_alert_days=country_raw.get("stall_alert_days", CountryConfig.stall_alert_days),
            source=country_raw.get("source", {}),
        )

    return Config(
        git=GitConfig(
            committer_name=git_raw.get("committer_name", GitConfig.committer_name),
            committer_email=git_raw.get("committer_email", GitConfig.committer_email),
            branch=git_raw.get("branch", GitConfig.branch),
            push=git_raw.get("push", GitConfig.push),
        ),
        countries=countries,
    )


def _set_nested(d: dict, key: str, value) -> None:
    """Allow overrides with dot notation: 'git.repo_path' -> d['git']['repo_path']."""
    parts = key.split(".")
    for part in parts[:-1]:
        d = d.setdefault(part, {})
    d[parts[-1]] = value
