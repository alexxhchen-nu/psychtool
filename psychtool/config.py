"""Configuration loading.

Rules (ADR 0003 / 0008 / 0022):
- ``api_key`` may only come from the ``PSYCHTOOL_API_KEY`` environment variable,
  never from a config file.
- ``data_tier`` defaults to ``synthetic``; ``real`` gates all network egress.
- A config file supplies ``base_url`` / ``model`` / ``data_tier``; env vars
  override file values.
- ``profile`` (``fake`` / ``vertex`` / ``real``) supplies defaults for transport
  and data tier. ``real`` always forces ``data_tier=real``; there is no BAA
  flag that enables cloud egress. Vertex tokens come only from
  ``PSYCHTOOL_VERTEX_ACCESS_TOKEN`` (never ADC or a config file).
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
ENV_DEBUG_TRACEBACKS = "PSYCHTOOL_DEBUG_TRACEBACKS"
ENV_PROFILE = "PSYCHTOOL_PROFILE"
ENV_VERTEX_PROJECT = "PSYCHTOOL_VERTEX_PROJECT"
ENV_VERTEX_LOCATION = "PSYCHTOOL_VERTEX_LOCATION"
ENV_VERTEX_ACCESS_TOKEN = "PSYCHTOOL_VERTEX_ACCESS_TOKEN"

DEFAULT_DATA_TIER: DataTier = "synthetic"

# The model transport is selected explicitly and defaults to the offline fake.
# ``http`` and ``vertex`` can open a socket and must be opted into via
# ``PSYCHTOOL_TRANSPORT`` / ``PSYCHTOOL_PROFILE`` (or a config file).
TransportMode = Literal["fake", "http", "vertex"]
DEFAULT_TRANSPORT: TransportMode = "fake"
ProfileName = Literal["fake", "vertex", "real"]
DEFAULT_PROFILE: ProfileName = "fake"
NETWORK_TRANSPORTS = frozenset({"http", "vertex"})


class Config(BaseModel):
    """Runtime configuration. ``api_key`` is only ever populated from the env."""

    base_url: str = ""
    model: str = ""
    judge_model: str = ""
    data_tier: DataTier = DEFAULT_DATA_TIER
    api_key: str | None = None
    redact: bool = False
    transport: TransportMode = DEFAULT_TRANSPORT
    profile: ProfileName = DEFAULT_PROFILE
    vertex_project: str = ""
    vertex_location: str = ""
    # Dev-only escape hatch (ADR 0013): when True, unhandled errors log full
    # tracebacks (which may quote request text). Only ever True for the
    # synthetic tier; main() refuses to start with the real tier.
    debug_tracebacks: bool = False


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
    explicit_transport = ENV_TRANSPORT in os.environ or "transport" in file_cfg
    explicit_tier = ENV_DATA_TIER in os.environ or "data_tier" in file_cfg
    explicit_base = ENV_BASE_URL in os.environ or "base_url" in file_cfg
    profile_raw = os.environ.get(ENV_PROFILE, file_cfg.get("profile", DEFAULT_PROFILE))
    profile = profile_raw if profile_raw in {"fake", "vertex", "real"} else DEFAULT_PROFILE

    vertex_project = os.environ.get(
        ENV_VERTEX_PROJECT, file_cfg.get("vertex_project", "")
    ) or ""
    vertex_location = os.environ.get(
        ENV_VERTEX_LOCATION, file_cfg.get("vertex_location", "")
    ) or ""

    transport = os.environ.get(ENV_TRANSPORT, file_cfg.get("transport", DEFAULT_TRANSPORT))
    # Fail closed: an unrecognised transport value must never enable a
    # network-capable transport, so only "http" and "vertex" are honoured.
    if transport not in NETWORK_TRANSPORTS:
        transport = DEFAULT_TRANSPORT

    if profile == "real":
        # No BAA flag or env can keep a real-profile run on the synthetic tier.
        data_tier = "real"
    elif profile == "vertex" and not explicit_tier:
        data_tier = "synthetic"

    if profile == "vertex" and not explicit_transport:
        transport = "vertex"
    elif profile == "fake" and not explicit_transport:
        transport = DEFAULT_TRANSPORT

    if profile == "vertex" and not explicit_base and vertex_project and vertex_location:
        from psychtool.gateway.endpoints import vertex_openapi_base_url

        base_url = vertex_openapi_base_url(vertex_project, vertex_location)
    # The debug-tracebacks switch is deliberately narrow: only the literal
    # value "1" enables it (a typo like "yes" stays off), and the real tier
    # never gets tracebacks regardless (see server/main.py, ADR 0013).
    debug_tracebacks = (
        os.environ.get(ENV_DEBUG_TRACEBACKS) == "1"
        and data_tier != "real"
    )

    return Config(
        base_url=base_url,
        model=model,
        judge_model=judge_model or model,
        data_tier=data_tier,  # type: ignore[arg-type]
        api_key=api_key,
        redact=redact,
        transport=transport,  # type: ignore[arg-type]
        profile=profile,  # type: ignore[arg-type]
        vertex_project=str(vertex_project),
        vertex_location=str(vertex_location),
        debug_tracebacks=debug_tracebacks,
    )


def debug_tracebacks_enabled(config: Config) -> bool:
    """Single decider for the dev-only traceback switch (ADR 0013).

    True only when ``PSYCHTOOL_DEBUG_TRACEBACKS=1`` was set AND the data tier
    is synthetic. The env var is re-read here (not only in ``load_config``) so
    a hand-built ``Config`` cannot sneak tracebacks past the tier check; the
    flag on the model is honoured only as a second confirmation. Fail-closed:
    any doubt means False.
    """
    return (
        config.debug_tracebacks
        and config.data_tier == "synthetic"
        and os.environ.get(ENV_DEBUG_TRACEBACKS) == "1"
    )
