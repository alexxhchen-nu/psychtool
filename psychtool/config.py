"""Configuration loading.

Rules (ADR 0003 / 0008):
- ``api_key`` may only come from the ``PSYCHTOOL_API_KEY`` environment variable,
  never from a config file.
- ``data_tier`` defaults to ``synthetic``; ``real`` gates all network egress.
- A config file supplies ``base_url`` / ``model`` / ``data_tier``; env vars
  override file values.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

DataTier = Literal["synthetic", "real"]

ENV_BASE_URL = "PSYCHTOOL_BASE_URL"
ENV_MODEL = "PSYCHTOOL_MODEL"
ENV_JUDGE_MODEL = "PSYCHTOOL_JUDGE_MODEL"
ENV_DATA_TIER = "PSYCHTOOL_DATA_TIER"
ENV_API_KEY = "PSYCHTOOL_API_KEY"
ENV_REDACT = "PSYCHTOOL_REDACT"
ENV_TRANSPORT = "PSYCHTOOL_TRANSPORT"

DEFAULT_DATA_TIER: DataTier = "synthetic"

# The model transport is selected explicitly and defaults to the offline fake.
# ``http`` is the only mode that can open a socket and must be opted into via
# ``PSYCHTOOL_TRANSPORT=http`` (or ``transport`` in a config file).
TransportMode = Literal["fake", "http"]
DEFAULT_TRANSPORT: TransportMode = "fake"


class Config(BaseModel):
    """Runtime configuration. ``api_key`` is only ever populated from the env."""

    base_url: str = ""
    model: str = ""
    judge_model: str = ""
    data_tier: DataTier = DEFAULT_DATA_TIER
    api_key: str | None = None
    redact: bool = False
    transport: TransportMode = DEFAULT_TRANSPORT


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def should_redact(config: Config) -> bool:
    """Redaction is forced on for ``real`` data and otherwise opt-in."""
    return config.data_tier == "real" or config.redact


def _read_file(path: Path | str | None) -> dict:
    if path is None:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def load_config(path: Path | str | None = None) -> Config:
    file_cfg = _read_file(path)

    base_url = os.environ.get(ENV_BASE_URL, file_cfg.get("base_url", ""))
    model = os.environ.get(ENV_MODEL, file_cfg.get("model", ""))
    judge_model = os.environ.get(ENV_JUDGE_MODEL, file_cfg.get("judge_model", ""))
    data_tier = os.environ.get(ENV_DATA_TIER, file_cfg.get("data_tier", DEFAULT_DATA_TIER))
    # api_key is deliberately read only from the environment.
    api_key = os.environ.get(ENV_API_KEY)
    redact_raw = os.environ.get(ENV_REDACT)
    redact = _as_bool(redact_raw) if redact_raw is not None else bool(file_cfg.get("redact", False))
    transport = os.environ.get(ENV_TRANSPORT, file_cfg.get("transport", DEFAULT_TRANSPORT))
    # Fail closed: an unrecognised transport value must never enable the
    # network-capable transport, so anything but "http" falls back to "fake".
    if transport != "http":
        transport = DEFAULT_TRANSPORT

    return Config(
        base_url=base_url,
        model=model,
        judge_model=judge_model or model,
        data_tier=data_tier,  # type: ignore[arg-type]
        api_key=api_key,
        redact=redact,
        transport=transport,  # type: ignore[arg-type]
    )
