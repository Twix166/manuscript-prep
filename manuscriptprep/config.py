"""Configuration loading utilities for ManuscriptPrep.

This module provides a lightweight shared config contract for CLI tools.
All entry points should accept ``--config`` and load settings here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


class ConfigError(Exception):
    """Raised when the ManuscriptPrep config is invalid."""


@dataclass
class ManuscriptPrepConfig:
    """Typed wrapper around raw YAML config data."""

    path: Path
    data: Dict[str, Any]

    def get(self, *keys: str, default: Any = None) -> Any:
        current: Any = self.data
        for key in keys:
            if not isinstance(current, dict):
                return default
            current = current.get(key, default)
        return current

    def require(self, *keys: str) -> Any:
        value = self.get(*keys, default=None)
        if value is None:
            joined = ".".join(keys)
            raise ConfigError(f"Missing required config value: {joined}")
        return value


def load_config(path: str | Path) -> ManuscriptPrepConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise ConfigError(f"Config file does not exist: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ConfigError("Top-level config must be a mapping/object")

    validate_config(data)
    return ManuscriptPrepConfig(path=config_path, data=data)


def validate_config(data: Dict[str, Any]) -> None:
    required_top_level = ["paths", "models", "timeouts", "chunking", "logging"]
    missing = [key for key in required_top_level if key not in data]
    if missing:
        raise ConfigError(f"Missing required config sections: {', '.join(missing)}")
