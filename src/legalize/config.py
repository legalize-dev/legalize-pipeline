"""Legalize pipeline configuration.

Loaded from config.yaml with optional CLI argument overrides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import yaml



@dataclass
class BOEConfig:
    """BOE API connection configuration."""

    base_url: str = "https://www.boe.es/datosabiertos"
    request_timeout: int = 30
    max_retries: int = 5
    retry_backoff_base: float = 2.0
    retry_backoff_multiplier: float = 2.0
    retry_jitter: float = 0.25
    requests_per_second: float = 2.0
    user_agent: str = "legalize-bot/1.0 (+https://github.com/legalize-dev/legalize)"


@dataclass
class ScopeConfig:
    """Pipeline scope: which norms to process."""

    rangos: list[str] = field(default_factory=list)  # Empty = all rangos accepted
    fecha_desde: Optional[date] = None
    fecha_hasta: Optional[date] = None
    normas_fijas: list[str] = field(default_factory=list)  # BOE IDs always included


@dataclass
class GitConfig:
    """Git configuration for the output repo."""

    repo_path: str = "../es"
    committer_name: str = "leyes-bot"
    committer_email: str = "bot@legalize.dev"
    branch: str = "main"
    push: bool = False


@dataclass
class Config:
    """Global pipeline configuration."""

    country: str = "es"  # ISO 3166-1 alpha-2
    boe: BOEConfig = field(default_factory=BOEConfig)
    scope: ScopeConfig = field(default_factory=ScopeConfig)
    git: GitConfig = field(default_factory=GitConfig)
    cache_dir: str = ".cache"
    data_dir: str = "../data"  # Raw XML + structured JSON (outside the repo)
    state_path: str = ".pipeline/state.json"
    mappings_path: str = ".pipeline/mappings/id-to-filename.json"
    legi_dir: str = ""  # Path to the extracted LEGI dump (France)


def _parse_date(value: str | None) -> Optional[date]:
    if value is None:
        return None
    return date.fromisoformat(value)


def _parse_rangos(values: list[str] | None) -> list[str]:
    if values is None:
        return []  # Empty = accept all
    return list(values)


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

    boe_raw = raw.get("boe", {})
    scope_raw = raw.get("scope", {})
    git_raw = raw.get("git", {})

    return Config(
        boe=BOEConfig(
            base_url=boe_raw.get("base_url", BOEConfig.base_url),
            request_timeout=boe_raw.get("request_timeout", BOEConfig.request_timeout),
            max_retries=boe_raw.get("max_retries", BOEConfig.max_retries),
            retry_backoff_base=boe_raw.get("retry_backoff_base", BOEConfig.retry_backoff_base),
            retry_backoff_multiplier=boe_raw.get(
                "retry_backoff_multiplier", BOEConfig.retry_backoff_multiplier
            ),
            retry_jitter=boe_raw.get("retry_jitter", BOEConfig.retry_jitter),
            requests_per_second=boe_raw.get(
                "requests_per_second", BOEConfig.requests_per_second
            ),
            user_agent=boe_raw.get("user_agent", BOEConfig.user_agent),
        ),
        scope=ScopeConfig(
            rangos=_parse_rangos(scope_raw.get("rangos")),
            fecha_desde=_parse_date(scope_raw.get("fecha_desde")),
            fecha_hasta=_parse_date(scope_raw.get("fecha_hasta")),
            normas_fijas=scope_raw.get("normas_fijas", []),
        ),
        git=GitConfig(
            repo_path=git_raw.get("repo_path", GitConfig.repo_path),
            committer_name=git_raw.get("committer_name", GitConfig.committer_name),
            committer_email=git_raw.get("committer_email", GitConfig.committer_email),
            branch=git_raw.get("branch", GitConfig.branch),
            push=git_raw.get("push", GitConfig.push),
        ),
        cache_dir=raw.get("cache_dir", Config.cache_dir),
        state_path=raw.get("state_path", Config.state_path),
        mappings_path=raw.get("mappings_path", Config.mappings_path),
        legi_dir=raw.get("legi_dir", Config.legi_dir),
    )


def _set_nested(d: dict, key: str, value) -> None:
    """Allow overrides with dot notation: 'git.repo_path' -> d['git']['repo_path']."""
    parts = key.split(".")
    for part in parts[:-1]:
        d = d.setdefault(part, {})
    d[parts[-1]] = value
