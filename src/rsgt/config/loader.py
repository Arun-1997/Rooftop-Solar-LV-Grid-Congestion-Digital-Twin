"""Load and validate a YAML run-config into a :class:`RunConfig`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .schema import RunConfig


def load_config(path: str | Path) -> RunConfig:
    """Read a YAML file and validate it against the run-config schema.

    Raises ``FileNotFoundError`` if the path is missing and
    ``pydantic.ValidationError`` if the contents are invalid.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Config file not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        data: Any = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping, got {type(data).__name__}")
    return RunConfig.model_validate(data)


def load_config_dict(data: dict) -> RunConfig:
    """Validate an already-parsed mapping (useful in tests)."""
    return RunConfig.model_validate(data)
