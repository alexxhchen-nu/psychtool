"""Config loading seams: api_key only from env; data_tier default synthetic."""

import os
import json

from psychtool.config import Config, load_config, should_redact


def _write_tmp_config(tmp_path, body):
    p = tmp_path / "psychtool.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def test_data_tier_defaults_to_synthetic():
    cfg = load_config()
    assert cfg.data_tier == "synthetic"


def test_api_key_comes_only_from_env(monkeypatch, tmp_path):
    # a config file may carry base_url/model/data_tier but NOT api_key
    path = _write_tmp_config(
        tmp_path,
        {"base_url": "https://example.invalid/v1", "model": "m1", "api_key": "file-secret"},
    )
    monkeypatch.setenv("PSYCHTOOL_API_KEY", "env-secret")
    cfg = load_config(path)
    assert cfg.api_key == "env-secret"  # env wins; file value ignored


def test_base_url_and_model_from_file(tmp_path):
    path = _write_tmp_config(
        tmp_path, {"base_url": "https://example.invalid/v1", "model": "m1"}
    )
    cfg = load_config(path)
    assert cfg.base_url == "https://example.invalid/v1"
    assert cfg.model == "m1"


def test_env_overrides_file_for_data_tier(monkeypatch, tmp_path):
    path = _write_tmp_config(tmp_path, {"data_tier": "synthetic"})
    monkeypatch.setenv("PSYCHTOOL_DATA_TIER", "real")
    cfg = load_config(path)
    assert cfg.data_tier == "real"


def test_redact_flag_from_env(monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_REDACT", "true")
    assert load_config().redact is True


def test_should_redact_forces_real_data_tier():
    assert should_redact(Config(data_tier="real")) is True


def test_should_redact_opt_in_for_synthetic():
    assert should_redact(Config(data_tier="synthetic")) is False
    assert should_redact(Config(data_tier="synthetic", redact=True)) is True
